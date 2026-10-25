"""Round 12A-1: operational Diesel sources; downstream consumers stay deferred."""
from copy import deepcopy
from unittest.mock import patch

import pytest

import materials_db as db
import engineering_tools as et
import phase_4_fluids as phase4
import project_state as ps
from project_io import decode_project, replace_project_state
import test_audit_regressions as audit


OLD_ORDER = ("Pre Flush", "Spacer", "Spacer Ahead", "Scavenger", "Main", "Lead",
             "Lead #1", "Lead #2", "Tail", "Spacer Behind", "Displacement Fluid")
DIESEL = {"volume": 20.0, "density": "52.5", "pump_rate": "3-5", "material_name": "Diesel"}
CASE = audit.AuditRegressions()


def project(mud="OBM", active=True):
    return {"job_type": 'CSG 9 5/8"', "mud_type": mud, "mud_density": "80-82",
            "fluids_config": {"active": (["Diesel"] if active else []) + ["Displacement Fluid"],
                              "params": {"Diesel": deepcopy(DIESEL), "Displacement Fluid": {
                                  "volume": 30.0, "pump_rate": "2-4"}}},
            "lab_qc_params": {"Diesel": {"rheology": audit.rheology_fixture()}},
            **audit.well_profile_fixture()}


def mark_document(state):
    for key, value in {"_compiled_doc_bytes": b"old document", "_compiled_doc_filename": "old.docx",
                       "_compiled_doc_signature": "old signature"}.items():
        state[key] = value


def assert_no_document(state):
    assert not any(key in state for key in ("_compiled_doc_bytes", "_compiled_doc_filename",
                                           "_compiled_doc_signature"))


def test_operational_taxonomy_order_and_fixed_default():
    assert db.HYDRAULIC_EXECUTION_ORDER == ("Diesel", *OLD_ORDER)
    assert db.FLUID_TYPES == list(db.HYDRAULIC_EXECUTION_ORDER)
    assert db.DEFAULT_MATERIAL_NAMES["Diesel"] == "Diesel"


def test_rheology_only_declaration_keeps_downstream_taxonomy_separate():
    assert db.RHEOLOGY_ONLY_FLUIDS == ("Diesel", "Pre Flush")
    assert db.CEMENT_FORMULATION_FLUIDS == ("Scavenger", *db.PLACEMENT_SLURRIES)
    assert "Diesel" not in db.CEMENT_FORMULATION_FLUIDS
    assert "Diesel" not in db.PLACEMENT_SLURRIES
    assert db.RHEOLOGY_LAB_FLUIDS == db.CEMENT_FORMULATION_FLUIDS
    app = CASE.app(project())
    CASE.phase(app, "phase4")
    CASE.phase(app, "phase7")
    assert "Diesel" in [tab.label for tab in app.tabs]  # A-2 enables Phase VII only.
    assert not app.error


@pytest.mark.parametrize("value", [51, 51.0, "51.0", 52, "52.3", 52.5, 54, "54", "۵۲.۳"])
def test_strict_density_valid(value):
    assert et.require_diesel_density(value) == float(et.normalize_digits(value))


@pytest.mark.parametrize("value", [50, 50.999, 54.001, 55, "", "  ", None, True, False,
                                  float("nan"), float("inf"), "NaN", "Infinity",
                                  "51-54", "52-53", "52/53", "51 / 54", [52]])
def test_strict_density_invalid(value):
    with pytest.raises(ValueError, match="Diesel density must be a single value between 51 and 54 pcf"):
        et.require_diesel_density(value)


def test_generic_density_range_remains_mean():
    assert et.require_positive_density("51-54") == 52.5
    assert et.require_positive_density("80/84") == 82.0


def test_restore_reconciles_wbm_without_losing_drafts_or_mirrors():
    state = project("WBM")
    draft, lab = deepcopy(state["fluids_config"]["params"]["Diesel"]), deepcopy(state["lab_qc_params"])
    state["active_fluids"] = {"Diesel": True, "Displacement Fluid": True}
    state["chk_fluid_Diesel"] = True
    state["fluid_data"] = {"Diesel": {"effective_density": 52.5}}
    mark_document(state)
    ps.restore_canonical_fields(state)
    assert state["fluids_config"]["active"] == ["Displacement Fluid"]
    assert state["fluids_config"]["params"]["Diesel"] == draft
    assert state["lab_qc_params"] == lab
    assert not state.get("active_fluids", {}).get("Diesel")
    assert not state.get("chk_fluid_Diesel")
    assert "Diesel" not in state["fluid_data"]
    assert "Diesel" not in state.get("inactive_slurry_drafts", {})
    assert_no_document(state)
    state["mud_type"] = "OBM"
    ps.restore_canonical_fields(state)
    assert "Diesel" not in state["fluids_config"]["active"]
    assert state["fluids_config"]["params"]["Diesel"] == draft


def test_density_callback_does_not_publish_a_range_mean():
    state = project()
    state["fluid_data"] = {"Diesel": {"density": "52", "effective_density": 52.0}}
    state["den_Diesel"] = "51-54"
    mark_document(state)
    with patch.object(phase4.st, "session_state", state):
        phase4._commit_fluid_widget("Diesel", "density", "den_Diesel")
    assert state["fluids_config"]["params"]["Diesel"]["density"] == "51-54"
    assert state["fluid_data"]["Diesel"]["effective_density"] == 0.0
    assert_no_document(state)


def test_generic_rebuild_uses_fixed_identity_and_existing_schedule():
    state = project()
    state["fluids_config"]["params"]["Diesel"]["material_name"] = "Cannot rename Diesel"
    ps.refresh_fluids(state)
    record = state["fluid_data"]["Diesel"]
    assert record == {"name": "Diesel", "material_name": "Diesel", "volume": 20.,
                      "density": "52.5", "effective_density": 52.5, "pump_rate": "3-5",
                      "min_rate": 3., "duration_min": 20./3., "duration_str": "00:06",
                      "cumul_time_min": 20./3., "cumul_time_str": "00:06"}
    assert state["fluid_data"]["Displacement Fluid"]["effective_density"] == 81.
    assert state["total_pump_time_min"] == 20./3.+15.
    assert list(state["fluid_data"]) == ["Diesel", "Displacement Fluid"]
    status = et.compute_phase_status(state)
    assert status["phase4"]["level"] == "ok"
    assert status["phase5"]["level"] == "empty"
    assert status["phase6"]["level"] == "empty"
    state["fluids_config"]["active"] = ["Diesel"]
    assert et.compute_phase_status(state)["phase4"]["level"] == "ok"


@pytest.mark.parametrize("field,value", [("density", "51-54"), ("density", None),
    ("density", True), ("volume", 0.), ("volume", float("inf")), ("pump_rate", "0-4")])
def test_invalid_active_diesel_blocks_status_rebuild_and_preparation(field, value):
    state = project()
    state["fluids_config"]["params"]["Diesel"][field] = value
    status = et.compute_phase_status(state)["phase4"]
    assert status["level"] == "warning" and "Diesel" in status["message"]
    with pytest.raises(ValueError, match="Diesel"):
        ps.refresh_fluids(state)
    mark_document(state)
    issues = ps.prepare_calculations(state)
    assert any("Diesel" in issue for issue in issues)
    assert_no_document(state)


def test_stale_wbm_rebuild_deactivates_before_calculation():
    state = project("WBM")
    ps.refresh_fluids(state)
    assert state["fluids_config"]["active"] == ["Displacement Fluid"]
    assert list(state["fluid_data"]) == ["Displacement Fluid"]
    assert state["total_pump_time_min"] == 15.
    assert state["fluids_config"]["params"]["Diesel"] == DIESEL


@pytest.mark.parametrize("mud,active,expected", [("OBM", True, True), ("WBM", False, False),
                                               ("WBM", True, False)])
def test_source_roundtrip_and_transactional_publication(mud, active, expected):
    original = project(mud, active)
    original["fluid_data"] = {"Diesel": {"effective_density": 999., "duration_min": 999.}}
    restored = audit.round_trip(original)
    assert ("Diesel" in restored["fluids_config"]["active"]) is expected
    assert restored["fluids_config"]["params"]["Diesel"] == DIESEL
    assert restored["lab_qc_params"] == original["lab_qc_params"]
    current = {"well_name": "Replace me", "_compiled_doc_bytes": b"stale"}
    replace_project_state(current, restored, "current-json")
    ps.refresh_fluids(current)
    assert_no_document(current)
    assert current["total_pump_time_min"] == (20./3.+15. if expected else 15.)
    assert "Diesel" not in current.get("inactive_slurry_drafts", {})
    assert not any(key.startswith("diesel_") for key in current)


@pytest.mark.parametrize("raw", [b'{"job_type":"CMT PLUG","mud_type":"WBM","mud_type":"OBM"}',
    b'{"job_type":"CMT PLUG","fluids_config":{"active":["Diesel"],"params":{"Diesel":{"volume":1e999}}}}',
    b'{"job_type":"CMT PLUG","fluids_config":{"active":["Diesel"],"params":{"Diesel":{"volume":true}}}}',
    b'{"job_type":"CMT PLUG","fluids_config":{"active":"Diesel","params":{}}}'])
def test_malformed_load_stays_transactional(raw):
    current = {"well_name": "Keep me", "_compiled_doc_bytes": b"current"}
    before = deepcopy(current)
    with pytest.raises(ValueError):
        replace_project_state(current, decode_project(raw, audit.namespace["deserialize_item"]), "bad-json")
    assert current == before


@pytest.mark.parametrize("job", audit.BATCH1_JOBS)
def test_obm_selection_fixed_inputs_and_no_phase5_or_phase6_diesel(job):
    state = project(active=False)
    state["job_type"] = job
    app = CASE.app(state)
    CASE.phase(app, "phase4")
    assert not app.checkbox(key="chk_fluid_Diesel").value
    mark_document(app.session_state)
    app.checkbox(key="chk_fluid_Diesel").check().run()
    assert_no_document(app.session_state)
    assert app.session_state["fluids_config"]["active"] == ["Diesel", "Displacement Fluid"]
    assert not any(w.label == "Material Name - Diesel" for w in app.text_input)
    assert app.number_input(key="vol_Diesel").value == DIESEL["volume"]
    assert app.text_input(key="den_Diesel").value == DIESEL["density"]
    assert app.text_input(key="rate_Diesel").value == DIESEL["pump_rate"]
    assert app.session_state["fluid_data"]["Diesel"]["material_name"] == "Diesel"
    CASE.phase(app, "phase5")
    assert not app.tabs
    CASE.phase(app, "phase6")
    assert not app.tabs


def test_mud_change_blur_navigation_deactivates_and_preserves_draft():
    app = CASE.app(project())
    CASE.phase(app, "phase4")
    saved_lab = deepcopy(app.session_state["lab_qc_params"]["Diesel"])
    CASE.phase(app, "phase2_3")
    mark_document(app.session_state)
    app.selectbox(key="_w_mud_type").set_value("WBM")
    CASE.phase(app, "phase1")  # Commit on navigation without returning to Phase IV.
    assert app.session_state["fluids_config"]["active"] == ["Displacement Fluid"]
    assert app.session_state["fluids_config"]["params"]["Diesel"] == DIESEL
    assert app.session_state["lab_qc_params"]["Diesel"] == saved_lab
    assert not app.session_state["active_fluids"].get("Diesel")
    assert_no_document(app.session_state)
    CASE.phase(app, "phase4")
    assert "Diesel" not in [w.label for w in app.checkbox]
    CASE.phase(app, "phase2_3")
    app.selectbox(key="_w_mud_type").set_value("OBM").run()
    CASE.phase(app, "phase4")
    assert not app.checkbox(key="chk_fluid_Diesel").value
    app.checkbox(key="chk_fluid_Diesel").check().run()
    assert app.session_state["fluid_data"]["Diesel"]["density"] == DIESEL["density"]


@pytest.mark.parametrize("key,value,field", [("vol_Diesel", 24., "volume"),
    ("den_Diesel", "51-54", "density"), ("rate_Diesel", "4-6", "pump_rate")])
def test_last_source_edit_commits_and_invalidates_before_navigation(key, value, field):
    app = CASE.app(project())
    CASE.phase(app, "phase4")
    mark_document(app.session_state)
    widget = app.number_input(key=key) if field == "volume" else app.text_input(key=key)
    widget.set_value(value)
    CASE.phase(app, "phase1")
    assert app.session_state["fluids_config"]["params"]["Diesel"][field] == value
    assert_no_document(app.session_state)
    if field == "density":
        assert app.session_state["fluid_data"]["Diesel"]["effective_density"] == 0.
        CASE.phase(app, "phase4")
        assert any("Diesel density" in e.value for e in app.error)
        assert app.session_state["fluid_data"]["Diesel"]["effective_density"] == 0.


@pytest.mark.parametrize("mud", ["WBM", "OBM"])
def test_inactive_drafts_do_not_change_existing_operational_results(mud):
    state = project(mud, active=False)
    ps.refresh_fluids(state)
    before = deepcopy(state["fluid_data"]), et.compute_phase_status(state)
    state["fluids_config"]["params"]["Diesel"].update(volume=999., density="51-54", pump_rate="")
    state["lab_qc_params"]["Diesel"] = {}
    ps.refresh_fluids(state)
    assert (state["fluid_data"], et.compute_phase_status(state)) == before
    assert state["total_pump_time_min"] == 15.


def test_default_train_does_not_auto_enable_diesel():
    app = CASE.app()
    CASE.phase(app, "phase4")
    assert app.session_state["fluids_config"]["active"] == ["Displacement Fluid"]
    assert "Diesel" not in [w.label for w in app.checkbox]
    CASE.phase(app, "phase2_3")
    app.selectbox(key="_w_mud_type").set_value("OBM").run()
    CASE.phase(app, "phase4")
    assert not app.checkbox(key="chk_fluid_Diesel").value
    app.checkbox(key="chk_fluid_Diesel").check().run()
    assert app.number_input(key="vol_Diesel").value == 0.
    assert app.text_input(key="den_Diesel").value == ""
    assert app.text_input(key="rate_Diesel").value == ""
    draft = deepcopy(app.session_state["fluids_config"]["params"]["Diesel"])
    mark_document(app.session_state)
    app.checkbox(key="chk_fluid_Diesel").uncheck().run()
    assert_no_document(app.session_state)
    assert app.session_state["fluids_config"]["params"]["Diesel"] == draft


def test_inactive_diesel_draft_does_not_stale_prepared_document():
    app = CASE.configured_app('CSG 9 5/8"')
    state = deepcopy(app.session_state.to_dict())
    assert not ps.prepare_calculations(state)
    before = state["_cement_chart_source"], ps.fingerprint(state["_cement_chart_model"])
    mark_document(state)
    state["fluids_config"]["params"]["Diesel"] = {**DIESEL, "density": "51-54"}
    assert not ps.prepare_calculations(state)
    assert (state["_cement_chart_source"], ps.fingerprint(state["_cement_chart_model"])) == before
    assert state["_compiled_doc_bytes"] == b"old document"
    # A stale WBM active claim is reconciled even if Phase IV is never visited.
    state["mud_type"] = "WBM"
    state["fluids_config"]["active"].insert(0, "Diesel")
    lab = deepcopy(state.get("lab_qc_params", {}).get("Diesel"))
    assert not ps.prepare_calculations(state)
    assert "Diesel" not in state["fluids_config"]["active"]
    assert "Diesel" not in state["fluid_data"]
    assert state.get("lab_qc_params", {}).get("Diesel") == lab
    assert_no_document(state)
