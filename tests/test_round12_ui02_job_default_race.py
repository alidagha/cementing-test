"""Replay the browser's old dependent-widget frame through real callbacks."""
from copy import deepcopy

import pytest
import materials_db as db
import test_audit_regressions as audit
from project_state import request_description_for_job


CASE = audit.AuditRegressions()
JOBS = ['CSG 9 5/8"', 'LNR 4 1/2"', 'LNR 7"', 'TIE BACK LNR 5"',
        'CMT PLUG', 'CMT SQUEEZE']
TRANSITIONS = [(a, b) for job in JOBS for a, b in [('CSG 20"', job), (job, 'CSG 20"')]]


def control(widgets, label):
    return next(w for w in widgets if w.label == label)


def replay_old_frame(app, old_frame, job):
    """Server handled Job Type; client navigates with its previous widget IDs."""
    app.selectbox(key="_w_job_type").set_value(job).run()
    CASE.healthy(app)
    for widget in old_frame.widgets:
        if widget.id == app.selectbox(key="_w_job_type").id:
            widget.string_value = job
        elif widget.id == app.radio(key="_app_mode_key").id:
            widget.string_value = "Phase II & III: Well Data"
    app._run(widget_state=old_frame)
    CASE.healthy(app)
    assert app.radio(key="_app_mode_key").value == "phase2_3"
    CASE.phase(app, "phase1")


@pytest.mark.parametrize("before,after", TRANSITIONS)
def test_delayed_navigation_keeps_new_automatic_default_and_descriptions(before, after):
    app = CASE.app({"job_type": before, "hole_size": db.DEFAULT_HOLE_SIZES[before],
                    "hole_size_customized": False})
    old_frame = deepcopy(app._tree.get_widget_states())
    replay_old_frame(app, old_frame, after)
    expected = db.DEFAULT_HOLE_SIZES[after]
    assert control(app.text_input, "Hole Size (in)").value == expected
    for state in (app.session_state.to_dict(), audit.round_trip(app.session_state.to_dict())):
        assert state["hole_size"] == state["doc_control"]["hole_size"] == expected
        assert state["hole_size_customized"] is False
        assert state["job_type"] == state["doc_control"]["job_type"] == after
        assert state["cementing_method"] == state["doc_control"]["cementing_method"] == db.get_cementing_method(after)
        for field in ("request_description", "revision_description"):
            assert state[field] == state["doc_control"][field] == request_description_for_job(after)
            assert state[field + "_customized"] is False


@pytest.mark.parametrize("before,after", TRANSITIONS)
def test_real_override_survives_job_change_delayed_frame_and_restore(before, after):
    app = CASE.app({"job_type": before, "hole_size": db.DEFAULT_HOLE_SIZES[before],
                    "hole_size_customized": False})
    control(app.text_input, "Hole Size (in)").set_value('Inside approved 9 5/8" CSG').run()
    old_frame = deepcopy(app._tree.get_widget_states())
    replay_old_frame(app, old_frame, after)
    restored = CASE.app(audit.round_trip(app.session_state.to_dict()))
    assert control(restored.text_input, "Hole Size (in)").value == 'Inside approved 9 5/8" CSG'
    assert restored.session_state["hole_size_customized"] is True


@pytest.mark.parametrize("hole,marker,expected", [
    ("Legacy approved hole", None, "Legacy approved hole"),
    ('26"', None, '6"'), ('26"', True, '26"'), ('26"', False, '6"'),
])
def test_legacy_customization_precedence_is_unchanged(hole, marker, expected):
    state = {"doc_control": {"job_type": 'CSG 20"', "hole_size": hole}}
    if marker is not None:
        state["hole_size_customized"] = marker
    app = CASE.app(audit.round_trip(state))
    app.selectbox(key="_w_job_type").set_value('LNR 4 1/2"').run()
    CASE.healthy(app)
    assert control(app.text_input, "Hole Size (in)").value == expected


@pytest.mark.parametrize("label,value", [
    ("Hole Size (in)", "First manual hole edit"),
    ("Request Description", "First manual request edit"),
])
def test_real_edit_and_job_selection_in_same_frame_preserve_user_intent(label, value):
    app = CASE.app()
    frame = deepcopy(app._tree.get_widget_states())
    edited_id = control(app.text_input, label).id
    for widget in frame.widgets:
        if widget.id == app.selectbox(key="_w_job_type").id:
            widget.string_value = 'LNR 4 1/2"'
        elif widget.id == edited_id:
            widget.string_value = value
    app._run(widget_state=frame)
    CASE.healthy(app)
    assert control(app.text_input, label).value == value
    field = "hole_size" if label == "Hole Size (in)" else "request_description"
    assert app.session_state[field] == app.session_state["doc_control"][field] == value
    assert app.session_state[field + "_customized"] is True


def test_multiple_pending_edits_are_not_overwritten_by_description_sync():
    app = CASE.app()
    edits = {"Hole Size (in)": "Manual hole", "Request Description": "Manual request",
             "Revision Description": "Manual revision"}
    ids = {control(app.text_input, label).id: value for label, value in edits.items()}
    frame = deepcopy(app._tree.get_widget_states())
    for widget in frame.widgets:
        if widget.id == app.selectbox(key="_w_job_type").id:
            widget.string_value = 'LNR 4 1/2"'
        elif widget.id in ids:
            widget.string_value = ids[widget.id]
    app._run(widget_state=frame)
    CASE.healthy(app)
    for label, value in edits.items():
        assert control(app.text_input, label).value == value


@pytest.mark.parametrize("customized", [False, True])
def test_repeated_return_to_prior_job_does_not_resurrect_old_echoes(customized):
    app = CASE.app()
    if customized:
        control(app.text_input, "Hole Size (in)").set_value("Real override").run()
    for job in ['LNR 4 1/2"', 'CSG 20"', 'CMT PLUG', 'CSG 20"', 'LNR 4 1/2"']:
        replay_old_frame(app, deepcopy(app._tree.get_widget_states()), job)
        assert control(app.text_input, "Hole Size (in)").value == (
            "Real override" if customized else db.DEFAULT_HOLE_SIZES[job])
        assert app.session_state["hole_size_customized"] is customized


def test_unrendered_prior_job_cannot_replace_later_real_overrides():
    app = CASE.app()
    original = deepcopy(app._tree.get_widget_states())
    job_id, nav_id = app.selectbox(key="_w_job_type").id, app.radio(key="_app_mode_key").id
    for job in ['LNR 4 1/2"', 'CMT PLUG']:
        frame = deepcopy(original)
        for widget in frame.widgets:
            if widget.id == job_id:
                widget.string_value = job
            elif widget.id == nav_id:
                widget.string_value = "Phase II & III: Well Data"
        app._run(widget_state=frame)
        CASE.healthy(app)
    CASE.phase(app, "phase1")
    edits = {"Hole Size (in)": "Real approved hole", "Request Description": "Real request",
             "Revision Description": "Real revision"}
    for label, value in edits.items():
        control(app.text_input, label).set_value(value).run()
    app.selectbox(key="_w_job_type").set_value('LNR 4 1/2"').run()
    CASE.healthy(app)
    for label, value in edits.items():
        assert control(app.text_input, label).value == value
    assert app.session_state["hole_size_customized"] is True
