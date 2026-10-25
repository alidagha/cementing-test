"""Legacy Top values must reach explicit repair before the Phase V widget."""
from copy import deepcopy
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_audit_regressions as audit
import project_state as ps


@pytest.fixture(scope="module")
def reviewed_plug():
    case = audit.AuditRegressions()
    return deepcopy(case.configured_app("CMT PLUG").session_state.to_dict())


def restored_top(project, depth, mode=None, owner="CMT PLUG"):
    state = deepcopy(project)
    params = state["cement_params"]["Main"]
    params.pop("draft_top_depth", None)
    params.pop("draft_top_job_type", None)
    params.pop("top_mode", None)
    if mode is not None:
        params["top_mode"] = mode
    params.update(top_depth=depth, top_job_type=owner)
    return audit.round_trip(state)


@pytest.mark.parametrize("depth", ["broken", -1.0])
@pytest.mark.parametrize("mode", [None, "Depth (m MD)"])
def test_legacy_top_requires_explicit_repair_before_mount(reviewed_plug, depth, mode):
    state = restored_top(reviewed_plug, depth, mode)
    # The actual decoder accepts these legacy values; invalid placement still
    # cannot enter the ordinary report preparation path.
    assert state["cement_params"]["Main"]["top_depth"] == depth
    assert any("Top" in issue for issue in ps.prepare_calculations(deepcopy(state)))
    case = audit.AuditRegressions()
    app = case.app(state)
    app.radio(key="_app_mode_key").set_value("phase5").run()
    case.healthy(app)
    repair = next(w for w in app.text_input if w.label.startswith("Correct Top depth - Main"))
    assert app.session_state["cement_params"]["Main"]["top_depth"] == depth
    assert not [w for w in app.number_input if w.label == "Top of cement depth (m MD) - Main"]
    # Invalid Apply is non-destructive; entering a correction alone also does
    # not publish it until the operator explicitly applies it.
    repair.set_value("still invalid").run()
    next(b for b in app.button if b.label == "Apply corrected values").click().run()
    case.healthy(app)
    assert app.session_state["cement_params"]["Main"]["top_depth"] == depth
    next(w for w in app.text_input if w.label.startswith("Correct Top depth - Main")).set_value("1250.25").run()
    assert app.session_state["cement_params"]["Main"]["top_depth"] == depth
    next(b for b in app.button if b.label == "Apply corrected values").click().run()
    case.healthy(app)
    assert next(w for w in app.number_input if w.label == "Top of cement depth (m MD) - Main").value == 1250.25
    assert app.session_state["cement_params"]["Main"]["top_depth"] == 1250.25
    case.phase(app, "phase2_3")
    case.phase(app, "phase5")
    restored = audit.round_trip(app.session_state.to_dict())
    assert restored["cement_params"]["Main"]["top_depth"] == 1250.25
    assert not ps.prepare_calculations(deepcopy(restored))


@pytest.mark.parametrize("mode,depth,owner,expected", [
    ("Depth (m MD)", 1250.25, "CMT PLUG", 1250.25),
    ("Surface", 0.0, "CMT PLUG", 0.0),
    ("Not entered", None, "CMT PLUG", None),
    (None, "broken", 'CSG 20"', None),
    ("Depth (m MD)", -1.0, 'CSG 20"', None),
    ("Surface", "broken", "CMT PLUG", 0.0),
])
def test_top_controls_respect_effective_mode_and_job(reviewed_plug, mode, depth, owner, expected):
    state = restored_top(reviewed_plug, depth, mode, owner)
    state["cement_params"]["Tail"] = deepcopy(state["cement_params"]["Main"])
    state["cement_params"]["Tail"].update(top_depth="inactive bad", top_mode="Depth (m MD)")
    case = audit.AuditRegressions()
    app = case.app(state)
    case.phase(app, "phase5")
    assert not [w for w in app.text_input if w.label.startswith("Correct Top depth")]
    assert app.session_state["cement_params"]["Main"]["top_depth"] == expected
    assert app.session_state["cement_params"]["Tail"]["top_depth"] == "inactive bad"


def test_phase5_literal_pins_reject_one_changed_byte_in_memory():
    source = Path("phase_5_cement.py").read_bytes()
    changed = bytes([source[0] ^ 1]) + source[1:]
    digests = set()
    for path, name in (
        ("tests/test_round13b_b3_ct_schematic.py", "test_frozen_renderer_template_and_previous_ct_authorities_match_parent"),
        ("tests/test_round13b_b4_ct_report.py", "test_unrelated_guardrails_and_all_frozen_authorities_are_unchanged"),
    ):
        function = next(n for n in ast.parse(Path(path).read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == name)
        branch = next(n for n in ast.walk(function) if isinstance(n, ast.If)
                      and ast.unparse(n.test) == "name == 'phase_5_cement.py'")
        check = next(n for n in branch.body if isinstance(n, ast.Assert))
        expected = ast.literal_eval(check.test.comparators[0])
        assert isinstance(expected, str) and len(expected) == 64
        digests.add(expected)
        # Execute each actual pinned assertion with in-memory file bytes;
        # production and historical test files themselves are never mutated.
        code = compile(ast.Module(body=[check], type_ignores=[]), path, "exec")

        def verify(data):
            exec(code, {"hashlib": hashlib, "name": "phase_5_cement.py",
                        "Path": lambda _: SimpleNamespace(read_bytes=lambda: data)})

        verify(source)
        with pytest.raises(AssertionError):
            verify(changed)
    assert len(digests) == 1
