"""Full cement review admission must agree with the Phase-VII operator gate."""
from copy import deepcopy
from unittest.mock import patch

import pandas as pd
import pytest

import engineering_tools as eng
import phase_10_procedure as report
import project_state as ps
import test_audit_regressions as audit


CASE = audit.AuditRegressions()
DOC_KEYS = ("_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature")


@pytest.fixture(scope="module")
def reviewed_main():
    app = CASE.configured_app("CMT PLUG", optional_fluids=False)
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "ok"
    state = deepcopy(app.session_state.to_dict())
    assert ps.prepare_calculations(state) == []
    return state


def edit_main(reviewed_main):
    app = CASE.app(deepcopy(reviewed_main))
    CASE.phase(app, "phase7")
    reading = next(w for w in app.text_input if w.key.startswith("_rheo_main_surface_down_300_"))
    assert reading.value == "168"
    reading.set_value("169")
    CASE.phase(app, "phase1")
    qc = app.session_state["lab_qc_params"]["Main"]
    assert qc["rheology"]["surface_down"]["readings"]["300"] == "169"
    assert qc["review_signature"] != eng.lab_review_signature(qc, app.session_state["lab_grid_dfs"]["Main"])
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "warning"
    return app


def stale_document(state):
    state.update(zip(DOC_KEYS, (b"previous compiled document", "old.docx", "old signature")))


def reject(state, consumer, slurry):
    if consumer == "prepare":
        issues = ps.prepare_calculations(state)
        assert any(slurry in issue and "Phase VII" in issue for issue in issues), issues
    else:
        with patch.object(report.st, "session_state", state):
            with pytest.raises(ValueError, match=rf"{slurry}.*Phase VII"):
                report.build_master_context(calculations_prepared=consumer == "prepared")
    assert f"lab_payload_{slurry}" not in state
    assert all(key not in state for key in DOC_KEYS)


@pytest.mark.parametrize("consumer", ["prepare", "context", "prepared"])
def test_main_edit_is_rejected_at_every_admission(reviewed_main, consumer):
    app = edit_main(reviewed_main)
    state = deepcopy(app.session_state.to_dict())
    qc = deepcopy(state["lab_qc_params"])
    grid = state["lab_grid_dfs"]["Main"].copy(deep=True)
    source = deepcopy(state["lab_source_signatures"])
    stale_document(state)
    reject(state, consumer, "Main")
    assert state["lab_qc_params"] == qc
    pd.testing.assert_frame_equal(state["lab_grid_dfs"]["Main"], grid)
    assert state["lab_source_signatures"] == source
    CASE.phase(app, "phase10")
    assert next(b for b in app.button if b.label == "Build Word Document").disabled


@pytest.mark.parametrize("prepared", [False, True])
def test_explicit_main_rereview_recovers_current_context(reviewed_main, prepared):
    app = edit_main(reviewed_main)
    qc_before = deepcopy(app.session_state["lab_qc_params"]["Main"])
    grid = app.session_state["lab_grid_dfs"]["Main"].copy(deep=True)
    sources = deepcopy(app.session_state["lab_source_signatures"])
    CASE.phase(app, "phase7")
    button = next(b for b in app.button if b.label == "Confirm measured lab results")
    assert not button.disabled
    button.click().run()
    CASE.healthy(app)
    state = deepcopy(app.session_state.to_dict())
    qc = state["lab_qc_params"]["Main"]
    assert {k: v for k, v in qc.items() if k not in ("reviewed", "review_signature")} == {
        k: v for k, v in qc_before.items() if k not in ("reviewed", "review_signature")}
    pd.testing.assert_frame_equal(state["lab_grid_dfs"]["Main"], grid)
    assert state["lab_source_signatures"] == sources
    assert qc["reviewed"] and qc["review_signature"] == eng.lab_review_signature(qc, grid)
    assert eng.compute_phase_status(state)["phase7"]["level"] == "ok"
    assert ps.prepare_calculations(state) == []
    with patch.object(report.st, "session_state", state):
        ctx = report.build_master_context(calculations_prepared=prepared)
    expected = eng.validate_lab_rheology(qc, "Main")
    assert ctx["slurries"][0]["lab"]["rheology"] == expected


@pytest.mark.parametrize("slurry", ["Lead", "Tail"])
@pytest.mark.parametrize("defect", ["missing_qc", "missing_grid", "missing_both", "empty_grid", "missing_source", "stale_source", "missing_review", "unreviewed", "stale_signature"])
@pytest.mark.parametrize("consumer", ["prepare", "context", "prepared"])
def test_missing_or_unreviewed_sibling_cannot_use_old_payload(reviewed_main, slurry, defect, consumer):
    state = deepcopy(reviewed_main)
    state["fluids_config"]["active"] = [slurry, "Displacement Fluid"]
    state["fluids_config"]["params"][slurry] = state["fluids_config"]["params"].pop("Main")
    state["fluid_data"][slurry] = state["fluid_data"].pop("Main")
    state["fluid_data"][slurry]["name"] = slurry
    for key in ("cement_params", "cement_additives_dfs", "lab_grid_dfs", "lab_qc_params", "lab_source_signatures"):
        state[key][slurry] = state[key].pop("Main")
    state[f"lab_payload_{slurry}"] = state.pop("lab_payload_Main")
    assert state["lab_source_signatures"][slurry] == ps.lab_source_signature(state, slurry)
    assert state["lab_qc_params"][slurry]["review_signature"] == eng.lab_review_signature(
        state["lab_qc_params"][slurry], state["lab_grid_dfs"][slurry])
    if defect in ("missing_qc", "missing_both"):
        state["lab_qc_params"].pop(slurry)
    if defect in ("missing_grid", "missing_both"):
        state["lab_grid_dfs"].pop(slurry)
    if defect == "empty_grid":
        state["lab_grid_dfs"][slurry] = state["lab_grid_dfs"][slurry].iloc[:0].copy()
    if defect == "missing_source":
        state["lab_source_signatures"].pop(slurry)
    elif defect == "stale_source":
        state["lab_source_signatures"][slurry] = "previous formulation"
    if defect == "missing_review":
        state["lab_qc_params"][slurry].pop("reviewed")
        state["lab_qc_params"][slurry].pop("review_signature")
    elif defect == "unreviewed":
        state["lab_qc_params"][slurry]["reviewed"] = False
    elif defect == "stale_signature":
        state["lab_qc_params"][slurry]["rheology"]["surface_down"]["readings"]["300"] = "169"
    before_qc = deepcopy(state["lab_qc_params"])
    before_grids = deepcopy(state["lab_grid_dfs"])
    before_sources = deepcopy(state["lab_source_signatures"])
    stale_document(state)
    reject(state, consumer, slurry)
    assert state["lab_qc_params"] == before_qc
    assert state["lab_source_signatures"] == before_sources
    assert state["lab_grid_dfs"].keys() == before_grids.keys()
    for name, grid in before_grids.items():
        pd.testing.assert_frame_equal(state["lab_grid_dfs"][name], grid)
