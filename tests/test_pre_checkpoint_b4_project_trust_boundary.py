"""B4: JSON publication is safe only when its real first consumer is safe."""
from copy import deepcopy
from datetime import date
from io import BytesIO
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

import engineering_tools as eng
import project_io as io
import project_state as ps
import materials_db as db
import test_audit_regressions as audit
import phase_9_centralizer as phase9
from centralizer_fixtures import execute_centralizer
from test_uat_round10c_integration import save_project, restore_project, build
from test_pre_checkpoint_b2_cross_module_integration import projects as integrated_projects
from test_pre_checkpoint_b3_report_word_e2e import review_main, blocked, sequence_table
import cement_chart_model as chart


CASE = audit.AuditRegressions()
DESERIALIZE = audit.namespace["deserialize_item"]
SERIALIZE = audit.namespace["serialize_item"]


@pytest.fixture(scope="module")
def project():
    return integrated_projects.__wrapped__()()


def encode(state):
    return json.dumps({key: SERIALIZE(value) for key, value in state.items()},
                      ensure_ascii=False, allow_nan=False).encode()


def publish(raw):
    prepared = io.decode_project(raw, DESERIALIZE)
    app = AppTest.from_file(str(audit.ROOT / "main.py"), default_timeout=30)
    io.replace_project_state(app.session_state, prepared, io.content_signature(raw))
    app.run()
    CASE.healthy(app)
    return app


def saved(state):
    return save_project(SimpleNamespace(session_state=state))


DF_PROBES = [
    ("hardware numeric MD", "phase2_3"), ("hardware numeric Size", "phase2_3"),
    ("hardware numeric Grade", "phase2_3"), ("hardware numeric Description", "phase2_3"),
    ("hardware text ID", "phase2_3"), ("hardware boolean ID", "phase2_3"),
    ("hardware draft text Weight", "phase2_3"),
    ("additive numeric Name", "phase5"), ("additive numeric Mix", "phase5"),
    ("additive text Density", "phase5"), ("additive boolean Density", "phase5"),
    ("additive list Density", "phase5"), ("additive dict Density", "phase5"),
    ("additive boolean dosage", "phase5"), ("additive missing Name", "phase5"),
    ("lab numeric text", "phase7"), ("lab missing Material", "phase7"),
    ("spacer numeric Chemical", "phase6"), ("spacer text dosage", "phase6"),
    ("spacer boolean dosage", "phase6"), ("spacer missing Chemical", "phase6"),
]


def dataframe_probe(state, change):
    if change.startswith("hardware "):
        table = state["hardware_table"]
        if change == "hardware numeric MD": table["MD (m)"] = pd.to_numeric(table["MD (m)"])
        elif change == "hardware numeric Size": table["Size (in)"] = pd.to_numeric(table["Size (in)"])
        elif change == "hardware numeric Grade": table["Grade"] = 55
        elif change == "hardware numeric Description": table["Description"] = 123
        elif change == "hardware text ID": table["ID (in)"] = table["ID (in)"].astype(str)
        elif change == "hardware boolean ID": table["ID (in)"] = True
        else:
            state["hardware_editor_draft"] = table.copy(deep=True)
            state["hardware_editor_draft"]["Weight (ppf)"] = "100.0"
    elif change.startswith("additive "):
        table = state["cement_additives_dfs"]["Main"]
        if change == "additive numeric Name": table["Name"] = 123
        elif change == "additive numeric Mix": table["Mix Method"] = 123
        elif change == "additive text Density": table["Density"] = "1.47"
        elif change == "additive boolean Density": table["Density"] = True
        elif change == "additive list Density": table["Density"] = pd.Series([[1.47, 1.50]] * len(table), dtype=object)
        elif change == "additive dict Density": table["Density"] = pd.Series([{"value": 1.47}] * len(table), dtype=object)
        elif change == "additive boolean dosage": table["User Input"] = True
        else: state["cement_additives_dfs"]["Main"] = table.drop(columns="Name")
    elif change.startswith("lab "):
        table = state["lab_grid_dfs"]["Main"]
        if change == "lab numeric text":
            table["Concentration"] = 1.0
            table["Mass"] = 100.0
            table["Lot No"] = 123
        else: state["lab_grid_dfs"]["Main"] = table.drop(columns="Material")
    else:
        table = state["spacer_dfs"]["Spacer"]
        if change == "spacer numeric Chemical": table["Chemical"] = 123
        elif change == "spacer text dosage": table["User Input (% or gal)"] = "1.0"
        elif change == "spacer boolean dosage": table["User Input (% or gal)"] = True
        else: state["spacer_dfs"]["Spacer"] = table.drop(columns="Chemical")


@pytest.mark.parametrize("change,phase", DF_PROBES, ids=[row[0] for row in DF_PROBES])
def test_foreign_dataframe_representation_is_rejected_or_opens_real_consumer_safely(project, change, phase):
    state = deepcopy(project)
    dataframe_probe(state, change)
    try:
        prepared = io.decode_project(encode(state), DESERIALIZE)
    except ValueError:
        return  # Malformed representation may be rejected before publication.
    app = publish(encode(prepared))
    CASE.phase(app, phase)
    if change == "additive boolean dosage":
        assert eng.compute_phase_status(app.session_state)["phase5"]["level"] != "ok", "JSON true became a valid engineering dosage"
    if change == "hardware boolean ID":
        row = app.session_state["hardware_table"].loc[lambda df: df.Description == "Casing"].iloc[0]
        assert row["ID (in)"] != 1., "JSON true became a one-inch engineering ID"


@pytest.mark.parametrize("archived", [False, True])
def test_numeric_lab_text_and_nulls_are_normalized_before_real_activation(project, archived):
    state = deepcopy(project)
    grid = state["lab_grid_dfs"]["Main"]
    grid["Concentration"] = [100., None, .5][:len(grid)]
    grid["Mass"] = [600., None, 50.][:len(grid)]
    grid["Lot No"] = 123
    if archived:
        state["fluids_config"]["active"].remove("Main")
        ps.purge_inactive_slurries(state, state["fluids_config"]["active"])
    raw = encode(state)
    decoded = io.decode_project(raw, DESERIALIZE)
    normalized = (decoded["inactive_slurry_drafts"]["Main"]["lab_grid_dfs"] if archived
                  else decoded["lab_grid_dfs"]["Main"])
    assert normalized.at[0, "Concentration"] == "100.0"
    assert pd.isna(normalized.at[1, "Concentration"])
    app = publish(raw)
    CASE.phase(app, "phase4")
    if archived: app.checkbox(key="chk_fluid_Main").check().run()
    CASE.phase(app, "phase7")
    assert app.session_state["lab_grid_dfs"]["Main"].at[0, "Lot No"] == "123"


@pytest.mark.parametrize("token", [[], {}, 123, True])
def test_malformed_target_token_cannot_be_published_then_crash_a_real_consumer(project, token):
    state = deepcopy(project)
    state["placement_config"]["target_row"] = token
    try:
        raw = encode(state)
        io.decode_project(raw, DESERIALIZE)
    except ValueError:
        return
    app = publish(raw)
    CASE.phase(app, "phase2_3")
    CASE.phase(app, "phase10")
    assert next(b for b in app.button if b.label == "Build Word Document").disabled


@pytest.mark.parametrize("key,value,phase", [
    ("report_text_state", {"exec_summary_text": {"history": True}}, "phase10"),
    ("preflush_config", {"wash_multiplier": []}, "phase6"),
    ("fluid_data", {"Main": {"volume": "unreadable legacy draft"}}, "phase4"),
])
def test_nested_drafts_reject_or_reopen_without_a_framework_crash(project, key, value, phase):
    state = deepcopy(project)
    state[key] = value
    try:
        raw = encode(state)
        io.decode_project(raw, DESERIALIZE)
    except ValueError:
        return
    app = publish(raw)
    CASE.phase(app, phase)


@pytest.mark.parametrize("field,value", [("User Input", True), ("Density", True)])
def test_archived_boolean_numeric_additive_cannot_crash_or_become_valid_after_activation(project, field, value):
    state = deepcopy(project)
    state["cement_additives_dfs"]["Main"][field] = value
    state["fluids_config"]["active"].remove("Main")
    ps.purge_inactive_slurries(state, state["fluids_config"]["active"])
    try:
        raw = encode(state)
        io.decode_project(raw, DESERIALIZE)
    except ValueError:
        return
    app = publish(raw)
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_Main").check().run()
    CASE.phase(app, "phase5")
    assert eng.compute_phase_status(app.session_state)["phase5"]["level"] != "ok"


@pytest.mark.parametrize("field", ["target_row", "host_row"])
def test_list_token_is_rejected_before_first_real_readiness(project, field):
    state = deepcopy(project)
    state["placement_config"][field] = []
    try:
        raw = encode(state)
        io.decode_project(raw, DESERIALIZE)
    except ValueError:
        return
    app = publish(raw)
    CASE.phase(app, "phase2_3")


@pytest.mark.parametrize("history", [True, 12, [12]])
def test_malformed_saved_report_history_cannot_crash_restore_action(project, history):
    state = deepcopy(project)
    state["report_text_state"]["procedure_text"]["history"] = history
    try:
        raw = encode(state)
        io.decode_project(raw, DESERIALIZE)
    except ValueError:
        return
    app = publish(raw)
    execute_centralizer(app.session_state, physics="dynamic")
    CASE.phase(app, "phase10")
    app.button(key="_restore_procedure_text").click().run()
    CASE.healthy(app)


def test_valid_saved_report_history_restores_the_actual_previous_revision(project):
    state = deepcopy(project)
    prior = 'Previous owner revision & <متن> "review"'
    state["report_text_state"]["procedure_text"]["history"] = [prior]
    app = publish(saved(state))
    execute_centralizer(app.session_state, physics="dynamic")
    CASE.phase(app, "phase10")
    app.button(key="_restore_procedure_text").click().run()
    CASE.healthy(app)
    assert app.session_state["procedure_text"] == prior
    assert app.session_state["report_text_state"]["procedure_text"]["history"] == []
    assert app.session_state["report_text_state"]["procedure_text"]["source_signature"] is None
    assert any("Your text is preserved" in message.value for message in app.warning)


def malformed_project(project, fault):
    state = deepcopy(project)
    if fault == "JSON syntax": return b'{"job_type":'
    if fault == "duplicate top key": return b'{"job_type":"CMT PLUG","job_type":"CMT SQUEEZE"}'
    if fault == "duplicate nested key": return b'{"well_name":"Bad","well_data":{"bhct":100,"bhct":110}}'
    if fault == "job": state["job_type"] = "Unsupported legacy job"
    elif fault == "fluid container": state["fluids_config"] = []
    elif fault == "fluid record": state["fluids_config"]["params"]["Main"] = []
    elif fault == "unknown active": state["fluids_config"]["active"].append("Foreign Slurry")
    elif fault == "hardware shape": state["hardware_table"] = state["hardware_table"].drop(columns="ID (in)")
    elif fault == "additive table": state["cement_additives_dfs"]["Main"] = []
    elif fault == "lab record": state["lab_qc_params"]["Main"] = []
    elif fault == "formation": state["formation_pressure_config"] = {"mode": "advanced", "profile": {}}
    elif fault == "centralizer": state["centralizer_config"]["version"] = 2
    elif fault == "schematic": state["schematic_config"] = []
    elif fault == "future material": state["material_property_schema"] = eng.MATERIAL_PROPERTY_SCHEMA + 1
    elif fault == "archive identity": state["inactive_slurry_drafts"] = {"Foreign Slurry": {}}
    elif fault == "archive shape": state["inactive_slurry_drafts"] = {"Tail": {"lab_grid_dfs": pd.DataFrame({"Material": ["Cement"]})}}
    elif fault == "archive QC": state["inactive_slurry_drafts"] = {"Tail": {"lab_qc_params": []}}
    elif fault == "boolean geometry": state["hardware_table"]["ID (in)"] = True
    elif fault == "boolean dosage": state["cement_additives_dfs"]["Main"]["User Input"] = True
    elif fault == "boolean density": state["cement_additives_dfs"]["Main"]["Density"] = True
    elif fault == "target token": state["placement_config"]["target_row"] = []
    elif fault == "report history": state["report_text_state"]["procedure_text"]["history"] = [12]
    return encode(state)


@pytest.mark.parametrize("fault", [
    "JSON syntax", "duplicate top key", "duplicate nested key", "job", "fluid container", "fluid record",
    "unknown active", "hardware shape", "additive table", "lab record", "formation", "centralizer", "schematic",
    "future material", "archive identity", "archive shape", "archive QC", "boolean geometry", "boolean dosage",
    "boolean density", "target token", "report history",
])
def test_failed_load_leaves_current_real_project_document_and_navigation_intact(project, fault):
    app = CASE.app(deepcopy(project))
    CASE.phase(app, "phase10")
    before = ps.fingerprint(app.session_state.to_dict())
    raw = malformed_project(project, fault)
    with pytest.raises(ValueError):
        io.replace_project_state(app.session_state, io.decode_project(raw, DESERIALIZE), "bad-load")
    assert ps.fingerprint(app.session_state.to_dict()) == before
    assert phase9.result_is_current(app.session_state)
    assert app.session_state["_compiled_doc_bytes"].startswith(b"PK")
    app.run()
    CASE.healthy(app)
    assert app.radio(key="_app_mode_key").value == "phase10"
    assert not next(b for b in app.button if b.label == "Build Word Document").disabled


@pytest.mark.parametrize("failing_key", ["cement_params", "last_loaded_hash", "_reset_navigation_to_phase1"])
def test_publication_write_failure_rolls_back_even_after_final_project_write(project, failing_key):
    class FailOnce(dict):
        armed = False
        def __setitem__(self, key, value):
            if self.armed and key == failing_key:
                self.armed = False
                raise RuntimeError("controlled write failure")
            super().__setitem__(key, value)
    state = FailOnce(deepcopy(project))
    state.update(proj_uploader="preserved uploader", last_loaded_hash="old hash", _app_mode_key="phase7")
    before = ps.fingerprint(state)
    incoming = io.decode_project(saved(project), DESERIALIZE)
    state.armed = True
    with pytest.raises(RuntimeError, match="controlled write failure"):
        io.replace_project_state(state, incoming, "new hash", preserved_keys=("proj_uploader",))
    assert ps.fingerprint(state) == before
    app = CASE.app(dict(state))
    assert app.radio(key="_app_mode_key").value == "phase7"
    assert phase9.result_is_current(app.session_state)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_is_rejected_before_publication(number):
    with pytest.raises(ValueError):
        io.decode_project(('{"well_name":"Nonfinite","well_data":{"bhct":' + number + '}}').encode(), DESERIALIZE)


@pytest.mark.parametrize("field,value", [("tie_back_liner_lap_m", -1), ("squeeze_depth_m", True),
                                         ("squeeze_depth_m", "1500")])
def test_existing_numeric_placement_contract_is_preserved(project, field, value):
    state = deepcopy(project)
    state["placement_config"][field] = value
    with pytest.raises(ValueError):
        io.decode_project(encode(state), DESERIALIZE)


@pytest.mark.parametrize("draft", ["zero fluid", "nullable temperature", "large finite fluid", "incomplete additive"])
def test_saveable_unfinished_numeric_drafts_reopen_without_fabricated_readiness(project, draft):
    state = deepcopy(project)
    phase = "phase4"
    if draft == "zero fluid": state["fluids_config"]["params"]["Main"]["volume"] = 0.
    elif draft == "nullable temperature":
        state["bhct"] = state["well_data"]["bhct"] = None
        phase = "phase7"
    elif draft == "large finite fluid": state["fluids_config"]["params"]["Main"]["volume"] = 1e12
    else:
        state["cement_additives_dfs"]["Main"]["User Input"] = None
        phase = "phase5"
    app = publish(encode(state))
    CASE.phase(app, phase)
    if draft == "large finite fluid":
        assert app.session_state["fluids_config"]["params"]["Main"]["volume"] == 1e12
    else:
        # BHCT completion belongs to Phase VII, not hardware readiness.
        assert eng.compute_phase_status(app.session_state)[phase]["level"] != "ok"
    CASE.phase(app, "phase10")
    assert next(b for b in app.button if b.label == "Build Word Document").disabled


def test_duplicate_order_and_transient_widgets_do_not_become_restored_authority(project):
    state = deepcopy(project)
    order = ["Main", "Diesel", "Main", "Pre Flush", "Displacement Fluid", "Diesel"]
    state["fluids_config"]["active"] = order
    for key in ("_app_mode_key", "app_mode_key", "chk_fluid_Tail", "vol_Main", "den_Main", "$$ID:old", "FormSubmitter:old"):
        state[key] = "foreign widget state"
    decoded = io.decode_project(encode(state), DESERIALIZE)
    assert decoded["fluids_config"]["active"] == list(dict.fromkeys(order))
    assert "vol_Main" not in decoded and "app_mode_key" not in decoded
    app = publish(encode(state))
    assert app.radio(key="_app_mode_key").value == "phase1"
    CASE.phase(app, "phase4")
    active = app.session_state["fluids_config"]["active"]
    assert len(active) == len(set(active))
    assert active == [name for name in db.HYDRAULIC_EXECUTION_ORDER if name in set(order)]
    assert app.session_state["fluids_config"]["params"]["Main"] == project["fluids_config"]["params"]["Main"]
    assert not app.checkbox(key="chk_fluid_Tail").value
    CASE.phase(app, "phase7")


def test_wbm_saved_active_diesel_is_deactivated_without_losing_or_reactivating_drafts(project):
    state = deepcopy(project)
    state["mud_type"] = state["well_data"]["mud_type"] = "WBM"
    app = publish(encode(state))
    for phase in ("phase4", "phase7", "phase10"):
        CASE.phase(app, phase)
        assert "Diesel" not in app.session_state["fluids_config"]["active"]
        assert "Diesel" not in app.session_state["fluid_data"]
    app = restore_project(saved(app.session_state.to_dict()))
    CASE.phase(app, "phase2_3")
    app.selectbox(key="_w_mud_type").set_value("OBM").run()
    CASE.phase(app, "phase4")
    assert not app.checkbox(key="chk_fluid_Diesel").value
    assert app.session_state["fluids_config"]["params"]["Diesel"] == project["fluids_config"]["params"]["Diesel"]
    assert app.session_state["lab_qc_params"]["Diesel"] == project["lab_qc_params"]["Diesel"]


@pytest.mark.parametrize("legacy_source", [False, True])
def test_missing_fluid_parameters_use_only_the_existing_explicit_legacy_source(project, legacy_source):
    state = deepcopy(project)
    state["fluids_config"]["params"].pop("Main")
    if not legacy_source:
        state["fluid_data"].pop("Main")
    app = publish(saved(state))
    CASE.phase(app, "phase4")
    main = app.session_state["fluids_config"]["params"]["Main"]
    if legacy_source:
        for field in ("volume", "density", "pump_rate", "material_name"):
            assert main[field] == project["fluid_data"]["Main"][field]
    else:
        assert main["volume"] == 0.
        assert eng.compute_phase_status(app.session_state)["phase4"]["level"] != "ok"
        blocked(app)


@pytest.mark.parametrize("table,phase", [("hardware", "phase2_3"), ("additive", "phase5"), ("lab", "phase7")])
def test_empty_tables_with_required_columns_are_supported_unfinished_drafts(project, table, phase):
    state = deepcopy(project)
    if table == "hardware": state["hardware_table"] = state["hardware_table"].iloc[:0].copy()
    elif table == "additive": state["cement_additives_dfs"]["Main"] = state["cement_additives_dfs"]["Main"].iloc[:0].copy()
    else: state["lab_grid_dfs"]["Main"] = state["lab_grid_dfs"]["Main"].iloc[:0].copy()
    app = publish(saved(state))
    CASE.phase(app, phase)
    blocked(app)


def test_flat_legacy_conflicts_and_derived_geometry_converge_across_real_roundtrips(project):
    state = deepcopy(project)
    state["doc_control"].update(job_type='LNR 7"', well_name="Nested old name", date="2020-01-01")
    state.update(well_name="Flat current name", report_date=date(2026, 10, 17),
                 mud_density="81", plastic_viscosity="25", yield_point="12", bhct=155., geo_md=9999., bhst=999.)
    state["well_data"].update(mud_density="90", plastic_viscosity="99", yield_point="99", bhct=170., geo_md=8888., bhst=888.)
    decoded = io.decode_project(encode(state), DESERIALIZE)
    for key in ("job_type", "well_name", "mud_density", "plastic_viscosity", "yield_point", "bhct"):
        nested = "doc_control" if key in ("job_type", "well_name") else "well_data"
        assert decoded[key] == decoded[nested][key] == state[key]
    assert decoded["doc_control"]["date"] == "2026-10-17"
    assert decoded["geo_md"] == project["geo_md"] != 9999.
    assert decoded["bhst"] == project["bhst"] != 999.
    before = ps.fingerprint(decoded)
    ps.restore_canonical_fields(decoded)
    assert ps.fingerprint(decoded) == before
    app = publish(encode(decoded))
    CASE.phase(app, "phase2_3")
    first = saved(app.session_state.to_dict())
    app = restore_project(first)
    CASE.phase(app, "phase2_3")
    assert saved(app.session_state.to_dict()) == first


def test_unicode_and_structural_characters_survive_real_save_decode_replace_save(project):
    state = deepcopy(project)
    text = '  آزمایش & <نمونه> "quoted"\nSecond line  '
    for key in ("well_name", "client", "request_description", "revision_description"):
        state[key] = state["doc_control"][key] = text
    state.update(request_description_customized=True, revision_description_customized=True)
    app = restore_project(saved(state))
    for _ in range(2):
        for key in ("well_name", "client", "request_description", "revision_description"):
            assert app.session_state[key] == text
        raw = saved(app.session_state.to_dict())
        app = restore_project(raw)
        assert saved(app.session_state.to_dict()) == raw


@pytest.mark.parametrize("token", [None, "", "retired:Casing:unknown"])
def test_missing_or_retired_target_is_repairable_without_falling_back_to_another_row(project, token):
    state = deepcopy(project)
    state["placement_config"]["target_row"] = token
    app = publish(encode(state))
    CASE.phase(app, "phase2_3")
    # The existing selector clears an unavailable token to its empty choice.
    assert app.session_state["placement_config"]["target_row"] == ""
    assert chart.chart_readiness(app.session_state, True)["issues"]
    blocked(app)


def test_old_domain_advanced_profile_reopens_without_fabricating_new_endpoint_pressures(project):
    state = deepcopy(project)
    domain = chart.current_open_hole_domain(state)
    profile = [{"md_m": domain["top_md"], "pore_psi": 1500., "frac_psi": 7000.},
               {"md_m": domain["bottom_md"], "pore_psi": 3000., "frac_psi": 14000.}]
    state["formation_pressure_config"] = {"mode": "advanced", "profile": profile}
    state["hardware_table"].loc[lambda df: df.Description == "Previous Casing", "MD (m)"] = "1600"
    raw = saved(state)
    assert io.decode_project(raw, DESERIALIZE)["formation_pressure_config"]["profile"] == profile
    app = restore_project(raw)
    CASE.phase(app, "phase2_3")
    current = app.session_state["formation_pressure_config"]["profile"]
    assert current[0] == {"md_m": 1600., "pore_psi": None, "frac_psi": None}
    assert current[-1] == profile[-1]
    assert chart.chart_readiness(app.session_state, True)["issues"]
    blocked(app)


@pytest.mark.parametrize("schema", [None, 0, 1])
@pytest.mark.parametrize("archived", [False, True])
def test_material_migration_preserves_measured_drafts_and_converges_after_activation(project, schema, archived):
    state = deepcopy(project)
    rows = [("Sodium Silicate", "Liquid Extender", "Liquid", None),
            ("Sodium Silicate", "Liquid Extender", "Liquid", 1.47),
            ("Micro Block", "Liquid Extender", "Liquid", 1.32),
            ("Anti Settling", "Anti Settling", "Powder", 2.53),
            ("NaCl", "Salt", "Powder", 2.16)]
    state["cement_additives_dfs"]["Main"] = pd.DataFrame([
        {"Name": name, "Material Type": kind, "Physical State": physical, "Density": density,
         "Mix Method": "Dry Blend", "User Input": .5} for name, kind, physical, density in rows])
    if schema is None: state.pop("material_property_schema")
    else: state["material_property_schema"] = schema
    if archived:
        state["fluids_config"]["active"].remove("Main")
        ps.purge_inactive_slurries(state, state["fluids_config"]["active"])
    decoded = io.decode_project(saved(state), DESERIALIZE)
    assert decoded["material_property_schema"] == eng.MATERIAL_PROPERTY_SCHEMA
    before = ps.fingerprint(decoded)
    assert not ps.migrate_material_properties(decoded)
    assert ps.fingerprint(decoded) == before
    assert "sodium silicate" not in {name.lower() for name in eng.LEGACY_ADDITIVE_SG}
    app = publish(saved(decoded))
    if archived:
        CASE.phase(app, "phase4")
        assert "Main" not in app.session_state["fluids_config"]["active"]
        app.checkbox(key="chk_fluid_Main").check().run()
    CASE.phase(app, "phase5")
    actual = app.session_state["cement_additives_dfs"]["Main"]
    assert actual["Density"].tolist()[:3] == [1.50, 1.47, 1.32]
    expected_anti = 2.53 if schema == 1 else eng.default_additive_density_gcm3("Anti Settling", "Powder")
    assert actual.iloc[3]["Density"] == pytest.approx(expected_anti)
    assert actual.iloc[4]["Density"] == 2.16
    raw = saved(app.session_state.to_dict())
    restored = restore_project(raw)
    CASE.phase(restored, "phase5")
    pd.testing.assert_frame_equal(restored.session_state["cement_additives_dfs"]["Main"], actual)


@pytest.mark.parametrize("archived", [False, True])
def test_extra_reordered_columns_and_incomplete_additive_rows_reopen_as_drafts(project, archived):
    state = deepcopy(project)
    table = state["cement_additives_dfs"]["Main"]
    table["User Comment"] = "preserved extra column"
    table = table[list(reversed(table.columns))].copy().astype(object)
    table.loc[len(table)] = {"Name": "", "User Input": None, "Density": None, "User Comment": "draft"}
    state["cement_additives_dfs"]["Main"] = table
    if archived:
        state["fluids_config"]["active"].remove("Main")
        ps.purge_inactive_slurries(state, state["fluids_config"]["active"])
    app = publish(saved(state))
    if archived:
        CASE.phase(app, "phase4")
        app.checkbox(key="chk_fluid_Main").check().run()
    CASE.phase(app, "phase5")
    CASE.phase(app, "phase7")
    assert app.session_state["cement_additives_dfs"]["Main"].iloc[0]["Density"] == 1.50
    assert app.session_state["cement_additives_dfs"]["Main"].iloc[0]["User Comment"] == "preserved extra column"


def test_stale_persisted_derived_data_cannot_outrank_sources_or_resurrect_word(project):
    state = deepcopy(project)
    persisted = json.loads(saved(state))
    assert {"fluid_data", "cement_calc_Main", "lab_payload_Main", "lab_source_signatures"} <= set(persisted)
    assert not any(key.startswith("_") for key in persisted)
    original_volume = state["fluids_config"]["params"]["Main"]["volume"]
    state["fluid_data"]["Main"]["volume"] = 9999.
    state["cement_calc_Main"] = pd.DataFrame({"Name": ["Forged stale additive"], "Total": [9999.]})
    state["lab_payload_Main"] = {"Forged": "stale payload"}
    state["cement_additives_dfs"]["Main"].loc[0, ["User Input", "Density"]] = [.75, 1.47]
    state["phase_status"] = {"phase7": {"level": "ok"}}
    state["_compiled_doc_bytes"] = b"stale-document"
    app = publish(encode(state))
    assert "_compiled_doc_bytes" not in app.session_state
    assert not phase9.result_is_current(app.session_state)
    CASE.phase(app, "phase4")
    assert app.session_state["fluid_data"]["Main"]["volume"] == original_volume
    CASE.phase(app, "phase5")
    assert app.session_state["cement_calc_Main"].iloc[0]["Name"] == "Sodium Silicate"
    CASE.phase(app, "phase7")
    assert any("Formulation Drift" in message.value for message in app.warning)
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] != "ok"
    blocked(app)
    review_main(app, sync=True)
    execute_centralizer(app.session_state, physics="dynamic")
    document = Document(BytesIO(build(app)))
    train = [row.cells[0].text for row in sequence_table(document).rows[1:]]
    assert train.count("Main") == train.count("Diesel") == 1
    assert app.session_state["fluid_data"]["Main"]["volume"] == original_volume
    sodium = [row for table in document.tables for row in table.rows if "Sodium Silicate" in [cell.text for cell in row.cells]]
    assert len(sodium) == 2
    assert any("0.75" in cell.text for row in sodium for cell in row.cells)
