"""Adversarial transitions through canonical state, real navigation and JSON I/O."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

import test_audit_regressions as audit
import engineering_tools as eng
import materials_db as db
import phase_5_cement as phase5
import phase_7_lab as phase7
import phase_9_centralizer as phase9
import phase_10_procedure as report
import project_state as ps
import pumping_simulation as pumping
import cement_chart_model as chart
import well_schematic_adapter as schematic
import standalone_spacer as standalone
from centralizer_fixtures import ensure_current_centralizer, execute_centralizer
from test_uat_round10c_integration import save_project, restore_project
from test_uat_round12c_sodium_silicate import project as sodium_project
from test_uat_round12a5_diesel_word_e2e import projects as diesel_projects, word, assert_diesel_word_scope
from test_uat_round12b_lnr_4_1_2 import word_project as liner_project


CASE = audit.AuditRegressions()


@pytest.fixture(scope="module")
def complete_project():
    return sodium_project.__wrapped__()


def saved(state):
    return save_project(SimpleNamespace(session_state=state))


def context(state):
    with patch.object(report.st, "session_state", state):
        return report.build_master_context()


def no_document(state):
    assert not any(key in state for key in (
        "_compiled_doc_bytes", "_compiled_doc_signature", "_compiled_doc_filename"))


@pytest.fixture(scope="module")
def compiled_project(complete_project):
    app = restore_project(saved(deepcopy(complete_project)))
    CASE.export(app)
    return app.session_state.to_dict()


@pytest.fixture(scope="module")
def operational_project():
    return diesel_projects.__wrapped__()()


def test_restore_reconciles_duplicate_active_fluid_identity(complete_project):
    state = deepcopy(complete_project)
    state["fluids_config"]["active"].insert(0, "Main")
    restored = audit.round_trip(state)
    assert restored["fluids_config"]["active"] == ["Main", "Displacement Fluid"]
    assert restored["fluids_config"]["params"] == state["fluids_config"]["params"]


def test_rebuild_does_not_count_a_duplicate_stage_twice(complete_project):
    state = deepcopy(complete_project)
    expected = state["total_pump_time_min"]
    state["fluids_config"]["active"].insert(0, "Main")
    assert ps.prepare_calculations(state) == []
    assert state["total_pump_time_min"] == expected
    assert len(state["fluids_config"]["active"]) == len(state["fluid_data"])


def test_duplicate_saved_selection_cannot_crash_real_phase7(complete_project):
    state = deepcopy(complete_project)
    state["fluids_config"]["active"].insert(0, "Main")
    app = restore_project(saved(state))
    CASE.phase(app, "phase7")
    assert not app.exception
    assert app.session_state["fluids_config"]["active"] == ["Main", "Displacement Fluid"]


@pytest.mark.parametrize("fluid", db.FLUID_TYPES)
def test_duplicate_reconciliation_preserves_each_source_and_first_seen_order(fluid):
    active = [fluid, "Displacement Fluid", fluid, "Displacement Fluid"]
    params = {name: {"volume": 7.5, "density": "52.5" if name == "Diesel" else "90",
                     "pump_rate": "3-5"} for name in active}
    state = {"mud_type": "OBM", "fluids_config": {"active": active, "params": deepcopy(params)}}
    ps.restore_canonical_fields(state)
    assert state["fluids_config"]["active"] == list(dict.fromkeys(active))
    assert state["fluids_config"]["params"] == params
    before = ps.fingerprint(state)
    ps.restore_canonical_fields(state)
    assert ps.fingerprint(state) == before


def review(app, slurry):
    token = phase7.get_slurry_key(slurry, "btn")
    sync = next(b for b in app.button if b.key.startswith("_sync_" + token + "_"))
    sync.click().run()
    CASE.healthy(app)
    confirm = next(b for b in app.button if b.key.startswith("_confirm_lab_" + token + "_"))
    assert not confirm.disabled
    confirm.click().run()
    CASE.healthy(app)


@pytest.mark.parametrize("slurry,material", [
    ("Main", "Sodium Silicate"), ("Lead", "Micro Block"),
    ("Lead #1", "Sodium Silicate"), ("Lead #2", "Micro Block"),
    ("Tail", "Sodium Silicate"), ("Scavenger", "Micro Block"),
])
def test_repeated_slurry_archive_navigation_restore_and_explicit_reactivation(complete_project, slurry, material):
    state = deepcopy(complete_project)
    if slurry != "Main":
        for key in ("cement_params", "cement_additives_dfs", "lab_grid_dfs", "lab_qc_params", "lab_source_signatures"):
            state[key][slurry] = deepcopy(state[key]["Main"])
            if slurry != "Scavenger":
                state[key].pop("Main")
        state["fluids_config"]["params"][slurry] = deepcopy(state["fluids_config"]["params"]["Main"])
        state["fluids_config"]["active"] = (["Main", slurry, "Displacement Fluid"] if slurry == "Scavenger"
                                             else [slurry, "Displacement Fluid"])
    canonical, kind, physical = db.resolve_known_material(material)
    state["cement_additives_dfs"][slurry] = pd.DataFrame([{
        "Material Type": kind, "Name": canonical, "Physical State": physical,
        "Mix Method": "Dry Blend", "User Input": 0.50,
        "Density": 1.47 if material == "Sodium Silicate" else 1.32}])
    app = restore_project(saved(state))
    CASE.phase(app, "phase4")
    CASE.phase(app, "phase5")
    CASE.phase(app, "phase7")
    review(app, slurry)
    expected = app.session_state["cement_additives_dfs"][slurry].to_dict("records")
    grid = app.session_state["lab_grid_dfs"][slurry].to_dict("records")
    params = deepcopy(app.session_state["cement_params"][slurry])
    qc = deepcopy(app.session_state["lab_qc_params"][slurry])
    fluid = deepcopy(app.session_state["fluids_config"]["params"][slurry])
    assert ps.prepare_calculations(app.session_state.to_dict()) == []
    for _ in range(2):
        CASE.phase(app, "phase4")
        app.checkbox(key="chk_fluid_" + slurry).uncheck().run()
        for phase in ("phase10", "phase5", "phase1", "phase7"):
            CASE.phase(app, phase)
        assert slurry not in app.session_state["fluids_config"]["active"]
        assert slurry not in app.session_state["cement_additives_dfs"]
        assert "lab_payload_" + slurry not in app.session_state
        draft = app.session_state["inactive_slurry_drafts"][slurry]
        assert draft["cement_additives_dfs"].to_dict("records") == expected
        assert draft["lab_grid_dfs"].to_dict("records") == grid
        assert draft["lab_qc_params"] == qc
        assert draft["cement_params"] == params
        app = restore_project(saved(app.session_state.to_dict()))
        assert slurry not in app.session_state["fluids_config"]["active"]
        CASE.phase(app, "phase4")
        assert not app.checkbox(key="chk_fluid_" + slurry).value
        app.checkbox(key="chk_fluid_" + slurry).check().run()
        assert app.session_state["fluids_config"]["active"].count(slurry) == 1
        assert app.session_state["fluids_config"]["params"][slurry] == fluid
        assert app.session_state["cement_additives_dfs"][slurry].to_dict("records") == expected
        assert slurry not in app.session_state["inactive_slurry_drafts"]
        assert slurry not in app.session_state["lab_source_signatures"]
        assert eng.compute_phase_status(app.session_state)["phase7"]["level"] != "ok"
        CASE.phase(app, "phase5")
        CASE.phase(app, "phase7")
        assert any("Formulation Drift" in item.value for item in app.warning)
        review(app, slurry)
        assert app.session_state["lab_grid_dfs"][slurry].to_dict("records") == grid
        qc = deepcopy(app.session_state["lab_qc_params"][slurry])
        params = deepcopy(app.session_state["cement_params"][slurry])


@pytest.mark.parametrize("fluid", ["Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind"])
def test_operational_fluid_deactivation_restore_and_policy_specific_formulation(operational_project, fluid):
    app = restore_project(saved(deepcopy(operational_project)))
    CASE.phase(app, "phase4")
    if fluid == "Spacer":
        # Its A1 formulation is intentionally absent from the export fixture.
        # Enter it through the real controls before exercising the lifecycle.
        app.checkbox(key="chk_fluid_Spacer").check().run()
        app.number_input(key="vol_Spacer").set_value(12.).run()
        app.text_input(key="den_Spacer").set_value("95").run()
        app.text_input(key="rate_Spacer").set_value("4").run()
        CASE.phase(app, "phase6")
        audit.configure_standalone_spacer(app, dead_vol=2.)
        expected_formulation = deepcopy(app.session_state[standalone.CONFIG_KEY])
        expected_recipe = standalone.formulation_from_state(app.session_state)
        CASE.phase(app, "phase4")
    expected = deepcopy(app.session_state["fluids_config"]["params"][fluid])
    historical_draft = deepcopy(app.session_state.get("spacer_dfs", {}).get(fluid))
    for _ in range(2):
        app.checkbox(key="chk_fluid_" + fluid).uncheck().run()
        for phase in ("phase6", "phase10", "phase1"):
            CASE.phase(app, phase)
        state = app.session_state.to_dict()
        assert fluid not in state["fluid_data"]
        if fluid in ("Spacer Ahead", "Spacer Behind"):
            pd.testing.assert_frame_equal(state["spacer_dfs"][fluid], historical_draft)
        elif fluid == "Spacer":
            assert fluid not in state["spacer_dfs"]
            assert standalone.CONFIG_KEY not in state
        else:
            assert state["preflush_calc"] is None
        app = restore_project(saved(state))
        if fluid in ("Spacer Ahead", "Spacer Behind"):
            pd.testing.assert_frame_equal(app.session_state["spacer_dfs"][fluid], historical_draft)
        CASE.phase(app, "phase4")
        assert not app.checkbox(key="chk_fluid_" + fluid).value
        assert app.session_state["fluids_config"]["params"][fluid] == expected
        app.checkbox(key="chk_fluid_" + fluid).check().run()
        assert app.session_state["fluids_config"]["active"].count(fluid) == 1
        assert app.session_state["fluid_data"][fluid]["volume"] == expected["volume"]
        if fluid == "Spacer":
            CASE.phase(app, "phase6")
            assert next(w for w in app.selectbox if w.label == "Weighting Agent Mode").value is None
            assert eng.compute_phase_status(app.session_state)["phase6"]["level"] != "ok"
            audit.configure_standalone_spacer(app, dead_vol=2.)
            assert app.session_state[standalone.CONFIG_KEY] == expected_formulation
            assert standalone.formulation_from_state(app.session_state) == expected_recipe
            CASE.phase(app, "phase4")


def test_obm_wbm_roundtrip_navigation_and_explicit_diesel_reactivation(operational_project):
    app = restore_project(saved(deepcopy(operational_project)))
    CASE.phase(app, "phase7")
    expected = deepcopy(app.session_state["fluids_config"]["params"]["Diesel"])
    lab = deepcopy(app.session_state["lab_qc_params"]["Diesel"])
    CASE.phase(app, "phase2_3")
    app.selectbox(key="_w_mud_type").set_value("WBM")
    CASE.phase(app, "phase7")
    assert all(tab.label != "Diesel" for tab in app.tabs)
    for phase in ("phase10", "phase4", "phase1", "phase5", "phase7"):
        CASE.phase(app, phase)
    state = app.session_state.to_dict()
    assert "Diesel" not in state["fluids_config"]["active"]
    assert "Diesel" not in state["fluid_data"]
    assert state["fluids_config"]["params"]["Diesel"] == expected
    assert state["lab_qc_params"]["Diesel"] == lab
    assert not phase9.result_is_current(state)
    unfinished = deepcopy(state)
    unfinished["lab_qc_params"].pop("Main")
    assert eng.compute_phase_status(unfinished)["phase7"]["level"] != "ok"
    assert "Diesel" not in pumping.prepare_pumping_simulation(state)["inputs"]["fluid_data"]
    final = chart.resolve_final_fluid_intervals(state, chart.resolve_chart_geometry(state))
    assert all(row["fluid"] != "Diesel" for row in final["annular_intervals"])
    ensure_current_centralizer(state)
    ctx = context(state)
    assert_diesel_word_scope(word(ctx), False)
    app = restore_project(saved(state))
    no_document(app.session_state)
    CASE.phase(app, "phase2_3")
    app.selectbox(key="_w_mud_type").set_value("OBM")
    CASE.phase(app, "phase4")
    assert not app.checkbox(key="chk_fluid_Diesel").value
    assert app.session_state["fluids_config"]["params"]["Diesel"] == expected
    app.checkbox(key="chk_fluid_Diesel").check().run()
    assert app.session_state["fluid_data"]["Diesel"]["volume"] == expected["volume"]
    CASE.phase(app, "phase7")
    assert app.session_state["lab_qc_params"]["Diesel"] == lab
    state = app.session_state.to_dict()
    assert ps.prepare_calculations(state) == []
    execute_centralizer(state, physics="dynamic")
    assert "Diesel" in state["_centralizer_result"]["diagnostics"]["rheology"]
    assert "Diesel" in pumping.prepare_pumping_simulation(state)["inputs"]["rheology"]
    assert_diesel_word_scope(word(context(state)), True)


INVALID_SOURCES = [
    ("density", ("fluids_config", "params", "Main", "density"), ""),
    ("pump rate", ("fluids_config", "params", "Main", "pump_rate"), "0"),
    ("volume", ("fluids_config", "params", "Main", "volume"), 0.0),
    ("BHCT", ("bhct",), None),
    ("BHST", ("geothermal_config", "value"), None),
    ("lab readings", ("lab_qc_params", "Main", "rheology", "bhct_down", "readings"), {"300": "168"}),
]


@pytest.mark.parametrize("label,path,invalid", INVALID_SOURCES, ids=[row[0] for row in INVALID_SOURCES])
def test_valid_invalid_valid_invalid_rebuild_and_restore(compiled_project, label, path, invalid):
    state = deepcopy(compiled_project)
    container = state
    for key in path[:-1]:
        container = container[key]
    key = path[-1]
    original = deepcopy(container[key])
    for _ in range(2):
        container[key] = invalid
        ps.restore_canonical_fields(state)
        assert ps.prepare_calculations(state), label
        no_document(state)
        with pytest.raises(ValueError):
            context(state)
        app = restore_project(saved(state))
        restored = app.session_state.to_dict()
        assert ps.prepare_calculations(restored), label
        no_document(restored)
        container[key] = original
        ps.restore_canonical_fields(state)
        assert ps.prepare_calculations(state) == [], label


@pytest.mark.parametrize("field,invalid", [("User Input", None), ("Density", 0.0)])
def test_additive_invalid_cycles_preserve_repairable_draft_and_retire_lab(compiled_project, field, invalid):
    state = deepcopy(compiled_project)
    df = state["cement_additives_dfs"]["Main"]
    original = df.at[0, field]
    for _ in range(2):
        df.at[0, field] = invalid
        assert ps.prepare_calculations(state)
        assert eng.compute_phase_status(state)["phase5"]["level"] != "ok"
        assert "lab_payload_Main" not in state
        no_document(state)
        restored = restore_project(saved(state))
        assert eng.compute_phase_status(restored.session_state)["phase5"]["level"] != "ok"
        with pytest.raises(ValueError):
            context(restored.session_state.to_dict())
        df.at[0, field] = original
        assert ps.prepare_calculations(state) == []


def test_hardware_and_formation_invalid_cycles_block_prior_outputs(compiled_project):
    for source in ("hardware", "formation"):
        state = deepcopy(compiled_project)
        original = deepcopy(state["hardware_table"] if source == "hardware" else state.get("formation_pressure_config"))
        for _ in range(2):
            if source == "hardware":
                frame = state["hardware_table"]
                frame.loc[frame["Description"] == "Casing", "ID (in)"] = 99.0
            else:
                state["formation_pressure_config"] = {"mode": "advanced", "profile": [
                    {"md_m": 1500.0, "pore_psi": None, "frac_psi": None},
                    {"md_m": 3000.0, "pore_psi": None, "frac_psi": None}]}
            assert ps.prepare_calculations(state)
            no_document(state)
            assert chart.chart_readiness(state, include_fluids=True)["model"] is None
            with pytest.raises(ValueError):
                context(state)
            if source == "hardware":
                assert not phase9.result_is_current(state)
                with pytest.raises(ValueError):
                    pumping.prepare_pumping_simulation(state)
                with pytest.raises(ValueError):
                    schematic.prepare_schematic(state)
                state["hardware_table"] = deepcopy(original)
            elif original is None:
                state.pop("formation_pressure_config", None)
            else:
                state["formation_pressure_config"] = deepcopy(original)
            assert ps.prepare_calculations(state) == []


def test_unchanged_rebuilds_preserve_sources_signatures_reviews_and_document(compiled_project):
    state = deepcopy(compiled_project)
    source = ps.fingerprint(json.loads(saved(state)))
    document = tuple(state[key] for key in ("_compiled_doc_bytes", "_compiled_doc_signature"))
    signatures = tuple(state[key] for key in ("_cement_chart_source", "_pumping_simulation_source", "_well_schematic_source"))
    model = ps.fingerprint(state["_cement_chart_model"])
    for _ in range(3):
        assert ps.prepare_calculations(state) == []
        assert ps.fingerprint(json.loads(saved(state))) == source
        assert tuple(state[key] for key in ("_compiled_doc_bytes", "_compiled_doc_signature")) == document
        assert tuple(state[key] for key in ("_cement_chart_source", "_pumping_simulation_source", "_well_schematic_source")) == signatures
        assert ps.fingerprint(state["_cement_chart_model"]) == model
        assert phase9.result_is_current(state)


def test_last_phase5_editor_and_phase7_reading_edits_survive_unusual_navigation(complete_project):
    app = restore_project(saved(deepcopy(complete_project)))
    for phase in ("phase4", "phase10", "phase5"):
        CASE.phase(app, phase)
    editor = next(e for e in app.dataframe if "_editor_additives_main_" in e.proto.id)
    app.radio(key="_app_mode_key").set_value("phase1")
    widgets = app._tree.get_widget_states()
    change = widgets.widgets.add()
    change.id = editor.proto.id
    change.string_value = json.dumps({"edited_rows": {"0": {"User Input": 0.75}},
                                      "added_rows": [], "deleted_rows": []})
    app._run(widgets)
    CASE.healthy(app)
    assert app.radio(key="_app_mode_key").value == "phase1"
    assert app.session_state["cement_additives_dfs"]["Main"].at[0, "User Input"] == 0.75
    # Save immediately after the callback, before Phase V can rebuild its
    # still-0.50 projection. Restore must preserve the new source and drift.
    assert app.session_state["cement_calc_Main"].at[0, "(lbs or gal)/sk"] == "0.50 gal/sk"
    app = restore_project(saved(app.session_state.to_dict()))
    assert app.session_state["cement_additives_dfs"]["Main"].at[0, "User Input"] == 0.75
    CASE.phase(app, "phase7")
    assert any("Formulation Drift" in item.value for item in app.warning)
    reading = next(w for w in app.text_input if w.key.startswith("_rheo_main_bhct_down_300_"))
    reading.set_value("169")
    CASE.phase(app, "phase2_3")
    CASE.phase(app, "phase10")
    assert app.session_state["cement_calc_Main"].at[0, "(lbs or gal)/sk"] == "0.75 gal/sk"
    CASE.phase(app, "phase4")
    assert app.session_state["lab_qc_params"]["Main"]["rheology"]["bhct_down"]["readings"]["300"] == "169"
    app = restore_project(saved(app.session_state.to_dict()))
    CASE.phase(app, "phase7")
    assert any("Formulation Drift" in item.value for item in app.warning)
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] != "ok"


def test_real_built_document_is_retired_on_last_upstream_edit(compiled_project):
    app = CASE.app(deepcopy(compiled_project))
    assert app.session_state["_compiled_doc_bytes"] == compiled_project["_compiled_doc_bytes"]
    CASE.phase(app, "phase4")
    app.number_input(key="vol_Main").set_value(51.0)
    CASE.phase(app, "phase1")
    assert app.session_state["fluids_config"]["params"]["Main"]["volume"] == 51.0
    no_document(app.session_state)
    CASE.phase(app, "phase10")
    no_document(app.session_state)
    assert not phase9.result_is_current(app.session_state)
    assert next(b for b in app.button if b.label == "Build Word Document").disabled


def test_job_family_switches_keep_source_drafts_but_retire_old_placement_and_document(compiled_project):
    app = restore_project(saved(deepcopy(compiled_project)))
    hardware = app.session_state["hardware_table"].to_dict("records")
    for job in ('LNR 4 1/2"', 'LNR 5"', 'LNR 7"', 'TIE BACK LNR 7"', 'CMT PLUG', 'CMT SQUEEZE', 'CSG 9 5/8"'):
        CASE.phase(app, "phase1")
        app.selectbox(key="_w_job_type").set_value(job).run()
        assert app.session_state["job_type"] == job
        assert app.session_state["hole_size"] == db.DEFAULT_HOLE_SIZES[job]
        no_document(app.session_state)
        CASE.phase(app, "phase10")
        state = app.session_state.to_dict()
        assert ps.prepare_calculations(state)
        assert state["_cement_chart_model"] is None
        assert not phase9.result_is_current(state)
        CASE.phase(app, "phase2_3")
        assert app.session_state["placement_config"]["job_type"] == job
        assert app.session_state["hardware_table"].to_dict("records") == hardware
        app = restore_project(saved(app.session_state.to_dict()))
        assert app.session_state["job_type"] == job


def test_fractional_liner_active_diesel_checkpoint_rebuilds_from_sources():
    state = liner_project.__wrapped__()
    original = state["hardware_table"].to_dict("records")
    app = restore_project(saved(state))
    no_document(app.session_state)
    assert "_centralizer_result" not in app.session_state
    state = app.session_state.to_dict()
    assert ps.prepare_calculations(state) == []
    assert state["job_type"] == 'LNR 4 1/2"'
    assert state["hardware_table"].to_dict("records") == original
    execute_centralizer(state, physics="dynamic")
    assert phase9.result_is_current(state)
    ctx = context(state)
    assert "running 4 1/2 in Liner" in ctx["procedure_text"]
    assert_diesel_word_scope(word(ctx), True)
