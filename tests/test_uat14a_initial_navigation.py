"""Sidebar presentation is neutral only for actual pristine project sources."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest
import test_audit_regressions as audit
from engineering_tools import compute_phase_status
from phase_9_centralizer import new_config
import phase_10_procedure as report
import project_state as ps
from test_pre_round14_ui02_navigation_persistence import upload


CASE = audit.AuditRegressions()
PHASES = ("phase1", "phase2_3", "phase4", "phase5", "phase6", "phase7", "phase9", "phase10")


def caption(app, phase):
    return app.radio(key="_app_mode_key").proto.captions[PHASES.index(phase)]


def assert_pristine_captions(app):
    status = compute_phase_status(app.session_state)
    assert status["phase2_3"]["level"] == "warning"
    assert status["phase9"]["level"] == "warning"
    assert caption(app, "phase2_3") == "⚪ Not started"
    assert caption(app, "phase9") == "⚪ Not started"


def test_actual_fresh_launch_has_neutral_sidebar_only(tmp_path):
    app = CASE.app()
    state = app.session_state.to_dict()
    (tmp_path / "initialized.json").write_text(json.dumps(audit.namespace["serialize_item"](
        {k: v for k, v in state.items() if not k.startswith("_")}), ensure_ascii=False, indent=2))
    assert app.radio(key="_app_mode_key").value == "phase1"
    assert_pristine_captions(app)
    before = deepcopy(compute_phase_status(app.session_state))
    app.run()
    CASE.healthy(app)
    assert compute_phase_status(app.session_state) == before
    assert_pristine_captions(app)
    assert not any("unsaved changes" in w.value for w in app.warning)


def test_start_new_recreates_neutral_sidebar_without_completed_engineering():
    app = CASE.app()
    app.text_input(key="_w_well_name").set_value("Synthetic previous project").run()
    next(b for b in app.button if "Start New / Clear All Data" in b.label).click().run()
    app.button(key="_confirm_clear_yes").click().run()
    CASE.healthy(app)
    assert app.session_state["well_name"] == ""
    assert app.radio(key="_app_mode_key").value == "phase1"
    assert_pristine_captions(app)


def test_default_navigation_keeps_neutral_captions_and_selection(tmp_path):
    app = CASE.app()
    snapshots = {}
    observed = []
    for phase in ("phase2_3", "phase9", "phase1", "phase4", "phase5", "phase6", "phase7", "phase10", "phase1"):
        CASE.phase(app, phase)
        assert app.radio(key="_app_mode_key").value == phase
        snapshots[phase] = audit.namespace["serialize_item"](
            {k: v for k, v in app.session_state.to_dict().items() if not k.startswith("_")})
        observed.append((caption(app, "phase2_3"), caption(app, "phase9")))
        assert not any("unsaved changes" in w.value for w in app.warning)
    (tmp_path / "navigation.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2))
    assert all(pair == ("⚪ Not started", "⚪ Not started") for pair in observed)


@pytest.mark.parametrize("project", [
    {"well_name": "Operator work"},
    {"well_geometry": {"version": 1, "type": "Vertical", "td_m": 100.0}},
    {"well_geometry": {"version": 1, "type": "Vertical", "td_m": -1.0}},
    {"mud_density": "unreadable"},
    {"centralizer_config": {**new_config(), "physics_mode": "dynamic"}},
    {"centralizer_config": {**new_config(), "zones": [{"top_md": 100.0}]}},
    {"placement_config": {"job_type": 'CSG 20"', "excess_csg_oh_pct": 0.0}},
    {"fluids_config": {"active": ["Displacement Fluid"], "params": {"Main": {"volume": 1.0}}}},
])
def test_meaningful_or_invalid_sources_keep_actionable_computed_warnings(project):
    app = CASE.app(deepcopy(project))
    before = deepcopy(compute_phase_status(app.session_state))
    for phase in ("phase2_3", "phase9"):
        assert before[phase]["level"] == "warning"
        assert caption(app, phase) == "⚠️ Needs review"
    app.run()
    CASE.healthy(app)
    assert compute_phase_status(app.session_state) == before
    for phase in PHASES:
        if phase == "phase10":
            assert caption(app, phase) == ""
        else:
            expected = {"ok": "✅ Complete", "warning": "⚠️ Needs review", "empty": "⚪ Not started"}
            assert caption(app, phase) == expected[before[phase]["level"]]


def test_real_job_change_does_not_hide_unexecuted_centralizer():
    app = CASE.app()
    options = list(app.radio(key="_app_mode_key").options)
    app.selectbox(key="_w_job_type").set_value('CSG 9 5/8"').run()
    CASE.healthy(app)
    assert caption(app, "phase9") == "⚠️ Needs review"
    assert caption(app, "phase2_3") == "⚠️ Needs review"
    assert list(app.radio(key="_app_mode_key").options) == options
    assert app.radio(key="_app_mode_key").value == "phase1"


@pytest.mark.parametrize("project", [{"job_type": 'CSG 20"'}, {"well_name": "Loaded unfinished project"}])
def test_actual_loaded_checkpoint_keeps_warning_and_exact_receipt(project):
    app = CASE.app()
    with upload(app, json.dumps(project).encode()):
        app.run()
        CASE.healthy(app)
        receipt = app.session_state["_saved_sig"]
        assert app.session_state["last_loaded_hash"]
        for phase in ("phase2_3", "phase9"):
            assert caption(app, phase) == "⚠️ Needs review"
        app.run()
        CASE.healthy(app)
        assert app.session_state["_saved_sig"] == receipt
        assert not any("unsaved changes" in w.value for w in app.warning)


def test_neutral_caption_does_not_authorize_word_or_change_engineering_status():
    app = CASE.app()
    before = deepcopy(compute_phase_status(app.session_state))
    state = app.session_state.to_dict()
    assert ps.prepare_calculations(deepcopy(state))
    for prepared in (False, True):
        independent = deepcopy(state)
        with patch.object(report.st, "session_state", independent):
            with pytest.raises(ValueError):
                report.build_master_context(calculations_prepared=prepared)
        assert "_compiled_doc_bytes" not in independent
    CASE.phase(app, "phase10")
    assert not [b for b in app.button if b.label == "Build Word Document" and not b.disabled]
    assert compute_phase_status(app.session_state) == before
    assert "_compiled_doc_bytes" not in app.session_state


@pytest.mark.parametrize("phase,widget,value", [
    ("phase2_3", "_w_geometry_type", "Vertical"),
    ("phase9", "_centralizer_physics", "dynamic"),
])
def test_first_real_phase_input_refreshes_caption_without_changing_status_level(phase, widget, value):
    app = CASE.app()
    CASE.phase(app, phase)
    assert_pristine_captions(app)
    before = deepcopy(compute_phase_status(app.session_state))
    control = app.selectbox(key=widget) if phase == "phase2_3" else app.radio(key=widget)
    control.set_value(value).run()
    CASE.healthy(app)
    assert app.radio(key="_app_mode_key").value == phase
    assert caption(app, phase) == "⚠️ Needs review"
    assert compute_phase_status(app.session_state)[phase]["level"] == before[phase]["level"] == "warning"


@pytest.mark.parametrize("job", ["CMT PLUG", "CMT SQUEEZE", "CMT PLUG WITH CT"])
def test_nonapplicable_centralizer_caption_keeps_original_semantics(job):
    app = CASE.app({"job_type": job})
    assert compute_phase_status(app.session_state)["phase9"]["level"] == "ok"
    assert "Not applicable" in compute_phase_status(app.session_state)["phase9"]["message"]
    assert caption(app, "phase9") == "✅ Complete"
