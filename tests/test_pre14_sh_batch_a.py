"""PRE14-SH Batch A: real decode, publication and numeric repair boundaries."""
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
import json
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import engineering_tools as eng
import input_guard
import phase_10_procedure as report
import project_io as io
import project_state as ps
import test_audit_regressions as audit
from phase_2_3_well_data import HARDWARE_COLUMNS


CASE = audit.AuditRegressions()
SERIALIZE = audit.namespace["serialize_item"]
DESERIALIZE = audit.namespace["deserialize_item"]
BASE = {"job_type": "CMT PLUG", "well_name": "Synthetic boundary project"}
DOC_KEYS = ("_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature")
TEXT_FIELDS = [("doc_control", key) for key in ("field", "client", "rig_name", "request_number", "revision_no", "request_date", "prepared_date")]
TEXT_FIELDS += [("well_data", key) for key, value in ps.WELL_DATA_DEFAULTS.items() if isinstance(value, str)]


def encode(state):
    return json.dumps({key: SERIALIZE(value) for key, value in state.items()}, allow_nan=False).encode()


def decode(state):
    return io.decode_project(encode(state), DESERIALIZE)


def legacy(**values):
    return dict(BASE, fluids_config={"active": ["Pre Flush"], "params": {}},
                fluid_data={"Pre Flush": {"volume": "25.5", "density": "80-82", "pump_rate": "0.7-1.2",
                                          "effective_density": 81.0, "material_name": "Wash & <field>", **values}})


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("container,field", TEXT_FIELDS)
@pytest.mark.parametrize("value", [123, True, ["invalid"]])
def test_a1_nontext_fields_reject_before_replacement(nested, container, field, value):
    incoming = dict(BASE, **{container: {field: value}}) if nested else dict(BASE, **{field: value})
    current = {**BASE, "_app_mode_key": "phase7", **dict(zip(DOC_KEYS, (b"old word", "old.docx", "signature")))}
    before = deepcopy(current)
    with pytest.raises(ValueError, match=field):
        prepared = io.decode_project(encode(incoming), DESERIALIZE)
        io.replace_project_state(current, prepared, "incoming")
    assert current == before


@pytest.mark.parametrize("value", [True, 123, [], {}])
def test_a1_report_date_rejects_wrong_widget_types(value):
    with pytest.raises(ValueError, match="report_date"):
        decode(dict(BASE, report_date=value))


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("value", [date(2026, 10, 24), datetime(2026, 10, 24, 12), "2026-10-24", "legacy date draft", None])
def test_a1_supported_calendar_types_are_not_treated_as_plain_text(nested, value):
    from phase_1_doc_control import DOCUMENT_DATE_FIELDS
    fields = dict.fromkeys(DOCUMENT_DATE_FIELDS, value)
    state = dict(BASE, doc_control=fields) if nested else dict(BASE, **fields)
    result = decode(state)
    for field in DOCUMENT_DATE_FIELDS:
        assert result[field] == value


@pytest.mark.parametrize("value", [date(2026, 10, 24), "2026-10-24", None, ""])
def test_a1_legacy_nested_report_date_restoration_remains_supported(value):
    result = decode(dict(BASE, doc_control={"date": value}))
    if value:
        assert result["report_date"] == date(2026, 10, 24)
    else:
        assert "report_date" not in result


@pytest.mark.parametrize("nested", [False, True])
def test_a1_valid_text_nullable_numeric_and_calendar_contracts_survive(nested):
    text = {key: "" for key in ps.DOC_CONTROL_DEFAULTS if key not in ("job_type", "well_name")}
    well = {key: value for key, value in ps.WELL_DATA_DEFAULTS.items()}
    well.update(mud_density="80-82", plastic_viscosity="20", yield_point="10", bhct=None,
                pore_gradient_emw_pcf=None, frac_gradient_emw_pcf=100.0)
    state = dict(BASE, doc_control=text, well_data=well) if nested else dict(BASE, **text, **well)
    state.setdefault("doc_control", {})
    state["report_date"] = date(2026, 10, 24)
    result = decode(state)
    assert result["mud_density"] == "80-82"
    assert result["bhct"] is None
    assert result["well_data"]["frac_gradient_emw_pcf"] == 100.0 if nested else result["frac_gradient_emw_pcf"] == 100.0
    assert result["report_date"] == date(2026, 10, 24)
    assert result["doc_control"]["date"] == "2026-10-24"


@pytest.mark.parametrize("field", ["volume", "density", "effective_density"])
@pytest.mark.parametrize("value", ["abc", True, False, [], {}, 10**400, "1e999"])
def test_a2_a5_malformed_legacy_numeric_records_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        decode(legacy(**{field: value}))


@pytest.mark.parametrize("field", ["pump_rate", "min_rate", "duration_min", "cumul_time_min"])
@pytest.mark.parametrize("value", [True, False, [], {}])
def test_a5_legacy_consumed_numbers_cannot_be_booleans_or_containers(field, value):
    with pytest.raises(ValueError, match=field):
        decode(legacy(**{field: value}))


@pytest.mark.parametrize("record", [
    {"volume": "25.5", "density": "80-82", "pump_rate": "0.7-1.2"},
    {"volume": 0.0, "density": "", "pump_rate": "", "effective_density": 0.0},
    {"volume": None, "density": None, "pump_rate": None},
])
def test_a2_valid_legacy_and_unfinished_records_preserve_values(record):
    state = legacy(**record)
    result = decode(state)
    assert result["fluid_data"]["Pre Flush"] == state["fluid_data"]["Pre Flush"]
    assert decode(result)["fluid_data"] == result["fluid_data"]


TABLE_PATHS = [
    ("hardware_table",), ("hardware_editor_draft",), ("cement_additives_dfs", "Main"),
    ("spacer_dfs", "Spacer Behind"), ("lab_grid_dfs", "Main"),
    ("inactive_slurry_drafts", "Main", "cement_additives_dfs"),
    ("inactive_slurry_drafts", "Main", "lab_grid_dfs"),
    ("well_geometry", "survey"), ("synthetic_draft", "nested", "table"),
]


def with_table(path, table):
    state = dict(BASE)
    current = state
    for part in path[:-1]:
        current = current.setdefault(part, {})
    current[path[-1]] = table
    return state


def duplicate_table_project(path):
    if path[0].startswith("hardware"):
        columns = list(HARDWARE_COLUMNS)
        values = ["Casing", "3000", "7", 6.276, 12.0, 23.0, "K-55", 0.0, 0.0]
        duplicate = "ID (in)"
    elif path[-1] == "lab_grid_dfs" or path[0] == "lab_grid_dfs":
        columns = ["Material", "Concentration", "Unit", "Mass", "Lot No"]
        values = ["Cement", "100", "BWOB", "600", "LOT-1"]
        duplicate = "Unit"
    elif path[0] == "spacer_dfs":
        columns = ["Chemical", "User Input (% or gal)", "Weighting Agent Type"]
        values = ["Spacer", 1.0, "-"]
        duplicate = "User Input (% or gal)"
    elif path[0] == "well_geometry":
        columns, values, duplicate = ["MD", "Deviation", "Azimuth"], [0.0, 0.0, 0.0], "MD"
    else:
        columns = ["Material Type", "Name", "Physical State", "Mix Method", "User Input"]
        values = ["Anti Foam", "Anti Foam", "Liquid", "In Mix Water", 0.01]
        duplicate = "User Input"
    table = pd.DataFrame([values + [values[columns.index(duplicate)]]], columns=columns + [duplicate])
    state = with_table(path, table)
    if path[0] == "well_geometry":
        state["well_geometry"].update(version=1, type="Directional")
    return state


@pytest.mark.parametrize("path", TABLE_PATHS)
def test_a4_duplicate_columns_reject_before_normalization_or_editor(path):
    with pytest.raises(ValueError, match="[Dd]uplicate.*column"):
        decode(duplicate_table_project(path))


@pytest.mark.parametrize("empty", [False, True])
def test_a4_unique_hardware_extra_columns_nulls_and_order_are_preserved(empty):
    table = pd.DataFrame(columns=list(reversed(HARDWARE_COLUMNS)) + ["Owner Note"])
    if not empty:
        table.loc[0] = [None] * len(table.columns)
        table.loc[0, "Description"] = "CT"
        table.loc[0, "Owner Note"] = "retained"
    result = decode(with_table(("hardware_table",), table))
    pd.testing.assert_frame_equal(result["hardware_table"], table, check_dtype=False)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("integer", [False, True])
def test_a5_boolean_is_not_a_numeric_repair(value, integer):
    assert input_guard._parse(value, integer=integer) is None


@pytest.mark.parametrize("value,expected", [(0, 0.0), (25.5, 25.5), ("25.5", 25.5), ("12", 12.0)])
def test_a5_legitimate_repair_numbers_retain_meaning(value, expected):
    assert input_guard._parse(value) == expected


@pytest.mark.parametrize("scope,name", [("active", name) for name in ("Main", "Lead", "Tail", "Pre Flush", "Diesel", "Spacer")]
                         + [("archived", name) for name in ("Main", "Lead", "Tail")])
@pytest.mark.parametrize("value", ["yes", "false", 1, 0, None, []])
def test_a6_reviewed_metadata_is_an_actual_boolean(scope, name, value):
    state = dict(BASE)
    if scope == "archived":
        state["inactive_slurry_drafts"] = {name: {"lab_qc_params": {"reviewed": value}}}
    else:
        state["lab_qc_params"] = {name: {"reviewed": value}}
    with pytest.raises(ValueError, match="reviewed"):
        decode(state)


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("value", [True, False])
def test_a6_boolean_metadata_is_preserved_without_auto_review(archived, value):
    record = {"reviewed": value}
    state = dict(BASE, **({"inactive_slurry_drafts": {"Main": {"lab_qc_params": record}}} if archived
                        else {"lab_qc_params": {"Main": record}}))
    result = decode(state)
    actual = result["inactive_slurry_drafts"]["Main"]["lab_qc_params"] if archived else result["lab_qc_params"]["Main"]
    assert actual == record  # No signatures or operator approval invented by decode.


def test_a5_multiple_field_repair_is_atomic_with_actual_widgets():
    app = AppTest.from_string('''
import streamlit as st
from input_guard import repair_invalid_inputs
if 'sources' not in st.session_state:
    st.session_state.sources = {'volume': True, 'dose': False}
s = st.session_state.sources
if repair_invalid_inputs([(s,'volume','Volume',0.,None,False), (s,'dose','Dose',0.,None,False)], 'batch_a'):
    st.stop()
st.write('Ready')
''').run()
    assert not app.exception
    assert len(app.text_input) == 2
    app.text_input[0].set_value("25.5").run()
    app.text_input[1].set_value("bad").run()
    app.button[0].click().run()
    assert app.session_state["sources"] == {"volume": True, "dose": False}
    assert app.session_state["sources"]["volume"] is True
    assert app.session_state["sources"]["dose"] is False
    app.text_input[1].set_value("0.5").run()
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["sources"] == {"volume": 25.5, "dose": 0.5}


@pytest.mark.parametrize("value", [True, False])
def test_a5_phase_iv_legacy_boolean_stops_before_numeric_widget(value):
    app = CASE.app(legacy(volume=value))
    CASE.phase(app, "phase4")
    assert app.error
    assert app.session_state["fluids_config"]["params"]["Pre Flush"]["volume"] is value
    assert app.session_state["fluid_data"]["Pre Flush"]["volume"] is value
    correction = next(w for w in app.text_input if w.label.startswith("Correct Volume"))
    correction.set_value("25.5").run()
    next(b for b in app.button if b.label == "Apply corrected values").click().run()
    CASE.healthy(app)
    assert app.session_state["fluids_config"]["params"]["Pre Flush"]["volume"] == 25.5


@pytest.mark.parametrize("field,value", [("volume", "abc"), ("volume", True), ("density", "bad")])
def test_a2_phase_vi_invalid_source_has_controlled_phase_iv_repair(field, value):
    state = legacy(**{field: value})
    state.update(zip(DOC_KEYS, (b"old", "old.docx", "signature")))
    app = CASE.app(state)
    CASE.phase(app, "phase6")
    assert app.error
    assert any("Phase IV" in e.value for e in app.error)
    assert app.session_state["fluid_data"]["Pre Flush"][field] == value
    assert not any(key in app.session_state for key in DOC_KEYS)
    next(b for b in app.button if "Phase IV" in b.label).click().run()
    CASE.healthy(app)
    assert app.radio(key="_app_mode_key").value == "phase4"


def test_a2_phase_vi_rebuilds_derived_density_from_valid_source():
    app = CASE.app(legacy(effective_density="bad derived cache"))
    CASE.phase(app, "phase6")
    assert not app.error
    assert app.session_state["preflush_calc"]["effective_density"] == 81.0
    assert app.session_state["fluid_data"]["Pre Flush"]["density"] == "80-82"


def test_valid_decoded_project_keeps_review_and_both_word_context_paths():
    app = CASE.configured_app("CMT PLUG")
    current = app.session_state.to_dict()
    for prepared in (False, True):
        state = decode(current)
        qc = deepcopy(state["lab_qc_params"]["Main"])
        grid = state["lab_grid_dfs"]["Main"].copy(deep=True)
        assert qc["review_signature"] == eng.lab_review_signature(qc, grid)
        assert state["lab_source_signatures"]["Main"] == ps.lab_source_signature(state, "Main")
        assert ps.prepare_calculations(state) == []
        with patch.object(report.st, "session_state", state):
            context = report.build_master_context(calculations_prepared=prepared)
        assert context["slurries"][0]["name"] == "Main"
        assert state["lab_qc_params"]["Main"] == qc
        pd.testing.assert_frame_equal(state["lab_grid_dfs"]["Main"], grid)
    CASE.export(app)
    assert app.session_state["_compiled_doc_bytes"].startswith(b"PK")
    CASE.phase(app, "phase7")
    before = ps.fingerprint(app.session_state.to_dict())
    for incoming in (dict(BASE, field=True), legacy(volume=False),
                     dict(BASE, lab_qc_params={"Main": {"reviewed": "yes"}}),
                     duplicate_table_project(("hardware_table",))):
        with pytest.raises(ValueError):
            io.replace_project_state(app.session_state, decode(incoming), "invalid incoming")
        assert ps.fingerprint(app.session_state.to_dict()) == before
    app.run()
    CASE.healthy(app)
    assert app.radio(key="_app_mode_key").value == "phase7"
    assert app.session_state["_compiled_doc_bytes"].startswith(b"PK")


def test_authorized_project_io_identity_rejects_one_mutated_byte_in_memory():
    from test_round13b_b4_ct_report import test_unrelated_guardrails_and_all_frozen_authorities_are_unchanged as identity
    read_bytes = Path.read_bytes
    checked = []

    def altered(path):
        data = read_bytes(path)
        if path == Path("project_io.py"):
            checked.append(True)
            return data[:-1] + bytes([data[-1] ^ 1])
        return data

    with patch.object(Path, "read_bytes", altered):
        with pytest.raises(AssertionError):
            identity()
    assert checked == [True]
