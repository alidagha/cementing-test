"""Manual mode must commit before navigation unmounts its Phase V checkbox."""
from copy import deepcopy
from unittest.mock import patch

import pytest

import materials_db
import phase_5_cement as cement
import test_audit_regressions as audit
from test_uat_round10c_integration import restore_project, save_project


CASE = audit.AuditRegressions()
LABEL = "Manual Override (Custom Yield/Water)"
DOC_KEYS = ("_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature")


@pytest.mark.parametrize("manual", [True, False], ids=["auto-to-manual", "manual-to-auto"])
def test_manual_override_same_frame_navigation_commits_mode(manual):
    job = "CMT PLUG"
    app = CASE.app({
        **audit.well_profile_fixture(), **audit.valid_export_chart_fixture(job),
        "job_type": job, "mud_density": "80",
        "fluids_config": {"active": ["Main"], "params": {
            "Main": {"volume": 20., "density": "118", "pump_rate": "4"}}},
        "cement_params": {"Main": {
            "auto_calc": True, "cmt_sg": 3.2, "cmt_sg_source": "manual",
            "dead_vol": 1., "tank_name": materials_db.get_tank_name(job),
            "top_mode": "Depth (m MD)", "top_depth": 1000., "top_job_type": job}},
    })
    CASE.phase(app, "phase4")
    CASE.phase(app, "phase5")
    automatic = tuple(app.session_state["cement_params"]["Main"][k]
                      for k in ("yield", "mix_water"))
    next(w for w in app.checkbox if w.label == LABEL).check().run()
    next(w for w in app.number_input if w.label == "Custom Yield (cuft/sk)").set_value(1.321).run()
    next(w for w in app.number_input if w.label == "Custom Fresh Water (bbl)").set_value(123.4).run()
    if manual:
        next(w for w in app.checkbox if w.label == LABEL).uncheck().run()
    CASE.healthy(app)
    assert app.session_state["cement_params"]["Main"]["auto_calc"] is manual

    for key in DOC_KEYS:
        app.session_state[key] = b"old" if key.endswith("bytes") else "old"
    next(w for w in app.checkbox if w.label == LABEL).set_value(manual)
    app.radio(key="_app_mode_key").set_value("phase1").run()
    CASE.healthy(app)
    assert app.radio(key="_app_mode_key").value == "phase1"
    assert app.session_state["cement_params"]["Main"]["auto_calc"] is not manual
    assert all(key not in app.session_state for key in DOC_KEYS)

    # Serialize before Phase V can render again and repair a lost mode change.
    raw = save_project(app)
    decoded = audit.decode_project(raw, audit.namespace["deserialize_item"])
    assert decoded["cement_params"]["Main"]["auto_calc"] is not manual
    restored = restore_project(raw)
    for current in (app, restored):
        CASE.phase(current, "phase5")
        assert next(w for w in current.checkbox if w.label == LABEL).value is manual
        params = current.session_state["cement_params"]["Main"]
        assert (params["manual_yield"], params["manual_mix_water"], params["manual_job_type"]) == (
            1.321, 123.4, job)
        assert (params["yield"], params["mix_water"]) == ((1.321, 123.4) if manual else automatic)
        assert audit.compute_phase_status(current.session_state)["phase5"]["level"] == "ok"


@pytest.mark.parametrize("job", [*audit.BATCH1_JOBS, materials_db.CT_JOB])
def test_mode_commit_preserves_job_drafts_and_invalidates_only_on_change(job):
    # Isolate invalidation from main.py's independent incomplete-phase cleanup.
    params = {"auto_calc": True, "yield": 2.345, "mix_water": 55.,
              "manual_yield": 1.321, "manual_mix_water": 123.4, "manual_job_type": job}
    state = {"job_type": job, "cement_params": {"Main": params}, "_mode": False,
             **{key: "old" for key in DOC_KEYS}}
    with patch.object(cement.st, "session_state", state):
        unchanged = deepcopy(state)
        cement._commit_calculation_mode("Main", "_mode")
        assert state == unchanged
        state["_mode"] = True
        cement._commit_calculation_mode("Main", "_mode")
        assert params["auto_calc"] is False
        assert (params["yield"], params["mix_water"]) == (1.321, 123.4)
        assert all(key not in state for key in DOC_KEYS)
        state.update({key: "current" for key in DOC_KEYS})
        unchanged = deepcopy(state)
        cement._commit_calculation_mode("Main", "_mode")
        assert state == unchanged
        state["_mode"] = False
        cement._commit_calculation_mode("Main", "_mode")
        assert params["auto_calc"] is True
        assert all(key not in state for key in DOC_KEYS)
        assert (params["manual_yield"], params["manual_mix_water"], params["manual_job_type"]) == (
            1.321, 123.4, job)
        params.update({"yield": 2.345, "mix_water": 55., "manual_job_type": "different job"})
        state["_mode"] = True
        cement._commit_calculation_mode("Main", "_mode")
        assert params["auto_calc"] is False
        assert (params["yield"], params["mix_water"]) == (2.345, 55.)
        assert (params["manual_yield"], params["manual_mix_water"]) == (1.321, 123.4)
