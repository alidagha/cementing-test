"""Round 13B B1: exact CT job, one measured depth and blocked report boundary."""
from copy import deepcopy
from unittest.mock import patch
import pandas as pd
import pytest
import materials_db as db
import placement
import project_state as ps
import engineering_tools as et
import phase_10_procedure as report
from phase_5_cement import REQUIRED_ADDITIVE_COLUMNS
import test_audit_regressions as audit
from phase_2_3_well_data import HARDWARE_COLUMNS

JOB = "CMT PLUG WITH CT"
CASE = audit.AuditRegressions()


def hardware(md="3527", **values):
    row = dict.fromkeys(HARDWARE_COLUMNS, None)
    row.update(Description="CT", **{"MD (m)": md}, **values)
    return pd.DataFrame([row], columns=HARDWARE_COLUMNS)


def state():
    s = {"job_type": JOB, "hardware_table": hardware(),
         "fluids_config": {"active": ["Main", "Displacement Fluid"], "params": {
             "Main": {"volume": 20., "density": "118", "pump_rate": "0.7-1.2"},
             "Displacement Fluid": {"volume": 10., "pump_rate": "2"}}},
         "mud_density": "80", "cement_params": {"Main": {
             "top_mode": "Depth (m MD)", "top_depth": 3470., "top_job_type": JOB}}}
    s.update(audit.well_profile_fixture(4000.))
    return s


def test_registration_and_existing_defaults():
    assert JOB in db.JOB_TYPES
    assert db.get_cementing_method(JOB) == "Remedial Cementing"
    assert db.DEFAULT_HOLE_SIZES[JOB] == db.DEFAULT_HOLE_SIZES["CMT PLUG"]
    assert db.get_available_tanks(JOB) == db.get_available_tanks("CMT PLUG")
    assert ps.request_description_for_job(JOB) == JOB + " Cementing"


def test_single_depth_overrides_no_manual_target():
    assert placement.target_depth(hardware(), JOB, {}) == 3527.
    assert placement.target_depth(hardware(), JOB, {"job_type": JOB, "target_row": "__manual__", "manual_depth_m": 123.}) == 3527.


def test_main_only_eligibility():
    eligible = ps.available_fluid_types(state())
    assert "Main" in eligible
    assert not set(eligible) & {"Scavenger", "Lead", "Lead #1", "Lead #2", "Tail"}
    assert {"Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind", "Displacement Fluid"} <= set(eligible)


def test_current_ct_json_round_trip():
    s = state();restored = audit.round_trip(s)
    assert restored["job_type"] == JOB
    assert placement.target_depth(restored["hardware_table"], JOB, {}) == 3527.
    assert restored["hardware_table"].iloc[0]["Size (in)"] is None


@pytest.mark.parametrize("prepared", [False, True])
def test_report_boundary_blocks_pending_ct_and_retires_download(prepared):
    s = state();s["_compiled_doc_bytes"] = b"old"
    with patch.object(report.st, "session_state", s):
        with pytest.raises(ValueError, match="Phase V CT stages"):
            report.build_master_context(calculations_prepared=prepared)
    assert "_compiled_doc_bytes" not in s


@pytest.mark.parametrize("raw", [None, "", 0, -1, "12-3527", "nan", "inf", float("nan"), float("inf"), True, [], {}, "unknown"])
def test_invalid_ct_depth_is_controlled(raw):
    with pytest.raises(ValueError, match="CT Setting Depth.*positive finite scalar"):
        placement.ct_setting_depth(hardware(raw))


@pytest.mark.parametrize("count", [0, 2, 3])
def test_ct_row_count_is_never_silently_resolved(count):
    table = pd.concat([hardware()] * count, ignore_index=True) if count else hardware().iloc[:0]
    with pytest.raises(ValueError, match="exactly one CT Hardware row"):
        placement.ct_setting_depth(table)


@pytest.mark.parametrize("md", [742.25, 3527., 4111.75, "3.527e3"])
def test_dynamic_placement_and_canonical_bottom(md):
    s = state();s["hardware_table"] = hardware(md)
    bottom = float(md);s["cement_params"]["Main"]["top_depth"] = bottom - 40.
    result = placement.slurry_intervals(s["hardware_table"], JOB, {}, ["Main"], s["cement_params"])["Main"]
    assert result["bottom_depth"] == bottom
    assert result["top_depth"] == bottom - 40.
    assert result["bottom"] == f"{bottom:.1f} m MD"
    assert placement.ct_setting_depth(audit.round_trip(s)["hardware_table"]) == bottom


@pytest.mark.parametrize("top", [None, -1, 0, 3527, 3528])
def test_main_toc_must_be_explicit_and_shallower(top):
    s = state();s["cement_params"]["Main"]["top_depth"] = top
    result = placement.slurry_intervals(s["hardware_table"], JOB, {}, ["Main"], s["cement_params"])["Main"]
    assert result["top_depth"] is None
    assert result["bottom_depth"] == 3527.


def test_surface_semantics_and_job_owned_toc():
    s = state();s["cement_params"]["Main"].update(top_mode="Surface", top_depth=0.)
    assert placement.slurry_intervals(s["hardware_table"], JOB, {}, ["Main"], s["cement_params"])["Main"]["top_depth"] == 0.
    s["cement_params"]["Main"]["top_job_type"] = "CMT PLUG"
    assert placement.slurry_intervals(s["hardware_table"], JOB, {}, ["Main"], s["cement_params"])["Main"]["top_depth"] is None


@pytest.mark.parametrize("value", [None, 0.])
def test_optional_dimensions_never_become_required_or_measured(value):
    s = state()
    for f in ("ID (in)", "Joint (m)", "Weight (ppf)", "Collapse (psi)", "Burst (psi)"):
        s["hardware_table"][f] = value
    assert placement.ct_setting_depth(s["hardware_table"]) == 3527.
    restored = audit.round_trip(s)
    pd.testing.assert_frame_equal(restored["hardware_table"], s["hardware_table"], check_dtype=False)


@pytest.mark.parametrize("values", [{"Size (in)": "2", "ID (in)": 2.}, {"Size (in)": "bad"}, {"ID (in)": -1}, {"Joint (m)": -1}, {"Weight (ppf)": "bad"}, {"Burst (psi)": float("inf")}])
def test_supplied_ct_measurements_are_validated(values):
    with pytest.raises(ValueError, match="CT Hardware"):
        placement.ct_setting_depth(hardware(**values))


def test_actual_optional_geometry_remains_actual():
    table = hardware(**{"Size (in)": "2", "ID (in)": 1.75, "Joint (m)": 0.})
    before = table.copy(deep=True)
    assert placement.ct_setting_depth(table) == 3527.
    pd.testing.assert_frame_equal(table, before)


@pytest.mark.parametrize("slurry", ["Scavenger", "Lead", "Lead #1", "Lead #2", "Tail"])
def test_invalid_import_is_rejected_without_publishing_or_dropping_drafts(slurry):
    s = state();s["fluids_config"]["active"].insert(0, slurry)
    s["cement_params"][slurry] = {"draft": "retain"}
    before = deepcopy(s)
    with pytest.raises(ValueError, match="permits only Main"):
        audit.round_trip(s)
    assert s["cement_params"] == before["cement_params"]
    assert s["fluids_config"] == before["fluids_config"]
    with pytest.raises(ValueError, match="permits only Main"):
        ps.refresh_fluids(s)
    assert s["fluids_config"] == before["fluids_config"]


@pytest.mark.parametrize("raw", ["20-30", 0, -1, "Infinity", "nan", "NaN", True])
def test_invalid_import_depth_is_rejected(raw):
    with pytest.raises(ValueError, match="CT Setting Depth"):
        audit.round_trip({"job_type": JOB, "hardware_table": hardware(raw)})


def test_unfinished_ct_project_can_be_saved_without_fabricating_depth():
    s = {"job_type": JOB, "hardware_table": hardware(None)}
    restored = audit.round_trip(s)
    assert restored["hardware_table"].iloc[0]["MD (m)"] is None
    with pytest.raises(ValueError, match="CT Setting Depth"):
        placement.ct_setting_depth(restored["hardware_table"])


def test_switch_archives_disallowed_slurries_and_keeps_auxiliary_inputs():
    s = state();s["fluids_config"]["active"] += ["Tail", "Scavenger", "Spacer Ahead"]
    s["material_property_schema"] = et.MATERIAL_PROPERTY_SCHEMA
    for params in s["cement_params"].values():
        params.update(cmt_sg=et.catalog_cement_sg(), cmt_sg_source="catalog")
    expected = {"draft": 77., "cmt_sg": et.catalog_cement_sg(), "cmt_sg_source": "catalog"}
    s["cement_params"]["Tail"] = deepcopy(expected)
    s["cement_additives_dfs"] = {"Tail": pd.DataFrame([{**dict.fromkeys(REQUIRED_ADDITIVE_COLUMNS, ""), "Name": "retained", "User Input": 0.}])}
    s["fluids_config"]["params"]["Spacer Ahead"] = {"volume": 13., "density": "90", "pump_rate": "2"}
    before = deepcopy(s["fluids_config"]["params"]["Spacer Ahead"])
    ps.reconcile_fluid_applicability(s)
    assert s["fluids_config"]["active"] == ["Main", "Displacement Fluid", "Spacer Ahead"]
    assert s["inactive_slurry_drafts"]["Tail"]["cement_params"] == expected
    assert s["fluids_config"]["params"]["Spacer Ahead"] == before
    s = audit.round_trip(s)
    s["job_type"] = "CMT PLUG";s["fluids_config"]["active"].append("Tail")
    ps.purge_inactive_slurries(s, s["fluids_config"]["active"])
    assert s["cement_params"]["Tail"] == expected
    assert s["cement_additives_dfs"]["Tail"].iloc[0]["Name"] == "retained"


def test_noncement_eligibility_and_durations_are_unchanged():
    from cement_chart_model import chart_job_kind, chart_readiness
    from pumping_simulation import prepare_pumping_simulation
    from centralizer_adapter import centralizer_applicable
    s = state()
    assert chart_job_kind(JOB) is None
    assert chart_readiness(s) == {"issues": [], "warnings": [], "model": None}
    assert prepare_pumping_simulation(s)["applicable"] is False
    assert not centralizer_applicable(JOB)
    assert et.compute_phase_status(s)["phase9"] == {"level": "ok", "message": "Not applicable (Plug/Squeeze)."}
    for mud in ("OBM", "WBM"):
        s["mud_type"] = mud
        ordinary = {**s, "job_type": "CMT PLUG"}
        assert set(ps.available_fluid_types(s)) - {"Main"} == set(ps.available_fluid_types(ordinary)) - set(db.CEMENT_FORMULATION_FLUIDS)
    ps.refresh_fluids(s)
    assert s["fluid_data"]["Main"]["duration_min"] == 20. / .7
    assert s["total_pump_time_min"] == 20. / .7 + 5.


@pytest.mark.parametrize("consumer", ["generate_official_procedure", "generate_executive_summary", "synchronize_report_texts"])
def test_direct_report_consumers_cannot_generate_ordinary_plug_text(consumer):
    s = state();s["_compiled_doc_bytes"] = b"old"
    with patch.object(report.st, "session_state", s):
        with pytest.raises(ValueError, match="Phase V CT stages"):
            if consumer == "generate_official_procedure":
                report.generate_official_procedure(JOB, {}, [], {}, {}, {})
            elif consumer == "generate_executive_summary":
                report.generate_executive_summary(JOB, {}, [], {})
            else:
                report.synchronize_report_texts()
    assert "_compiled_doc_bytes" not in s


def test_live_navigation_main_toc_and_save_restore():
    app = CASE.app(state())
    CASE.phase(app, "phase2_3")
    assert not any(w.label == "Target shoe / treatment depth source" for w in app.selectbox)
    assert any("3527 m MD" in w.value for w in app.caption)
    assert not any("Unsupported" in w.value for w in app.warning)
    table = app.session_state["hardware_table"]
    assert pd.isna(table.iloc[0]["ID (in)"])
    CASE.phase(app, "phase4")
    assert {w.label for w in app.checkbox} >= {"Main", "Pre Flush", "Spacer Ahead"}
    assert not {w.label for w in app.checkbox} & {"Lead", "Lead #1", "Lead #2", "Tail", "Scavenger"}
    CASE.phase(app, "phase5")
    top = next(w for w in app.number_input if w.label == "Top of cement depth (m MD) - Main")
    top.set_value(3460.).run()
    CASE.phase(app, "phase7")
    restored = CASE.app(audit.round_trip(app.session_state.to_dict()))
    assert restored.session_state["cement_params"]["Main"]["top_depth"] == 3460.
    assert restored.session_state["job_type"] == JOB
    CASE.phase(restored, "phase10")
    assert any("Phase V CT stages" in w.value for w in restored.warning)
    assert not any("Build" in w.label for w in restored.button)
    assert "_compiled_doc_bytes" not in restored.session_state


def test_job_switch_callback_and_late_disallowed_checkbox():
    import phase_4_fluids as phase4
    app = CASE.app({"fluids_config": {"active": ["Tail", "Displacement Fluid"], "params": {}},
                    "cement_params": {"Tail": {"draft": 12.}}})
    app.selectbox(key="_w_job_type").set_value(JOB)
    CASE.phase(app, "phase4")
    assert app.session_state["fluids_config"]["active"] == ["Displacement Fluid"]
    assert app.session_state["inactive_slurry_drafts"]["Tail"]["cement_params"]["draft"] == 12.
    s = app.session_state.to_dict();s["chk_fluid_Tail"] = True
    with patch.object(phase4.st, "session_state", s):
        phase4._commit_fluid_selection("Tail", "chk_fluid_Tail")
    assert "Tail" not in s["fluids_config"]["active"]


@pytest.mark.parametrize("change", ["depth", "top", "rows", "order", "job", "fluids"])
def test_source_changes_retire_documents_and_placement_is_live(change):
    s = state();ps.prepare_calculations(s)
    source = s.get("_cement_chart_source")
    s["_compiled_doc_bytes"] = b"old"
    if change == "depth":
        s["hardware_table"].loc[0, "MD (m)"] = "3537"
    elif change == "top":
        s["cement_params"]["Main"]["top_depth"] = 3460.
    elif change in ("rows", "order"):
        extra = hardware().iloc[0].to_dict();extra.update(Description="Previous Casing", **{"MD (m)": "1000", "Size (in)": "7", "ID (in)": 6.276})
        s["hardware_table"] = pd.DataFrame([*s["hardware_table"].to_dict("records"), extra], columns=HARDWARE_COLUMNS)
        if change == "order":
            ps.prepare_calculations(s);source = s.get("_cement_chart_source")
            s["_compiled_doc_bytes"] = b"old"
            s["hardware_table"] = s["hardware_table"].iloc[::-1].reset_index(drop=True)
    elif change == "job":
        s["job_type"] = "CMT PLUG"
    else:
        s["fluids_config"]["params"]["Main"]["volume"] = 21.
    issues = ps.prepare_calculations(s)
    assert "_compiled_doc_bytes" not in s
    assert source != s.get("_cement_chart_source")
    if change != "job":
        assert any("Phase V CT stages" in issue for issue in issues)
        assert not any("Unsupported chart job" in issue for issue in issues)


def test_ct_hardware_editor_commits_before_navigation_without_synthetic_dimensions():
    app = CASE.app(state());CASE.phase(app, "phase2_3")
    CASE.hardware_event(app, {"edited_rows": {"0": {"MD (m)": "3550"}}}, navigate="phase5")
    assert ps.hardware_draft_pending(app.session_state)
    assert et.compute_phase_status(app.session_state)["phase2_3"]["level"] == "warning"
    CASE.phase(app, "phase2_3")  # Existing review/commit boundary publishes the edited row.
    CASE.phase(app, "phase5")
    restored = audit.round_trip(app.session_state.to_dict())
    assert placement.ct_setting_depth(restored["hardware_table"]) == 3550.
    assert pd.isna(restored["hardware_table"].iloc[0]["ID (in)"])
    assert restored["cement_params"]["Main"]["top_depth"] == 3470.


def test_original_taxonomy_and_hardware_options_are_preserved():
    original = ['CSG 30"', 'CSG 24"', 'CSG 20"', 'CSG 18 5/8"', 'CSG 13 3/8"',
                'CSG 9 5/8"', 'CSG 7"', 'LNR 7"', 'LNR 5"', 'LNR 4 1/2"',
                'CMT PLUG', 'CMT SQUEEZE', 'TIE BACK LNR 7"', 'TIE BACK LNR 5"']
    assert [job for job in db.JOB_TYPES if job != JOB] == original
    assert len(db.JOB_TYPES) == 15
    assert "Drill Pipes" in db.HARDWARE_DESCRIPTIONS
    assert "CT" not in db.HARDWARE_DESCRIPTIONS
    for alias in ("CMT PLUG CT", "CT PLUG", "CMT PLUG with CT"):
        assert alias not in db.JOB_TYPES


@pytest.mark.parametrize("other_job", ["CMT PLUG", 'CSG 9 5/8"', 'LNR 7"', 'TIE BACK LNR 5"', "CMT SQUEEZE"])
@pytest.mark.parametrize("dimensions", ["null", "zero", "measured"])
def test_retained_ct_hardware_survives_other_job_editor_restore_and_return(other_job, dimensions):
    s = state()
    if dimensions != "null":
        for field in ("ID (in)", "Joint (m)", "Weight (ppf)", "Collapse (psi)", "Burst (psi)"):
            s["hardware_table"][field] = 0.
        s["hardware_table"]["Size (in)"] = "0.0" if dimensions == "zero" else "2"
        if dimensions == "measured":
            s["hardware_table"]["ID (in)"] = 1.75
    app = CASE.app(s);CASE.phase(app, "phase2_3")
    original = app.session_state["hardware_table"].copy(deep=True)
    CASE.phase(app, "phase1")
    app.selectbox(key="_w_job_type").set_value(other_job).run()
    CASE.phase(app, "phase2_3")
    pd.testing.assert_frame_equal(app.session_state["hardware_table"], original, check_dtype=False)
    restored = CASE.app(audit.round_trip(app.session_state.to_dict()))
    assert restored.session_state["job_type"] == other_job
    CASE.phase(restored, "phase2_3")
    pd.testing.assert_frame_equal(restored.session_state["hardware_table"], original, check_dtype=False)
    CASE.phase(restored, "phase1")
    restored.selectbox(key="_w_job_type").set_value(JOB).run()
    CASE.phase(restored, "phase2_3")
    pd.testing.assert_frame_equal(restored.session_state["hardware_table"], original, check_dtype=False)
    assert placement.ct_setting_depth(restored.session_state["hardware_table"]) == 3527.


@pytest.mark.parametrize("size", [None, "", "0", "0.0", "0.000", 0.])
def test_optional_size_default_zero_never_becomes_measured_geometry(size):
    assert placement.ct_setting_depth(hardware(**{"Size (in)": size, "ID (in)": 0.})) == 3527.


def legacy_placement_source(source):
    """Exclude only B1's explicit CT extension; retain every original source byte."""
    import ast
    text = source.decode()
    tree = ast.parse(text)
    added = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "ct_setting_depth"]
    if not added:
        return source
    assert len(added) == 1 and not added[0].decorator_list
    following = next(node for node in tree.body if node.lineno > added[0].lineno)
    assert isinstance(following, ast.FunctionDef) and following.name == "target_descriptions"
    lines = text.splitlines(keepends=True)
    text = "".join(lines[:added[0].lineno - 1] + lines[following.lineno - 1:])
    for guard in ('    if job_type == "CMT PLUG WITH CT":\n        return {"CT"}\n',
                  '    if job_type == "CMT PLUG WITH CT":\n        return ct_setting_depth(table)\n'):
        assert text.count(guard) == 1
        text = text.replace(guard, "", 1)
    controlled_target = '''    try:
        target = target_depth(table, job_type, config)
    except ValueError as exc:
        return {name: {"top": ".... m [PLACEMENT INCOMPLETE]", "top_depth": None,
                       "bottom": ".... m [PLACEMENT INCOMPLETE]", "bottom_depth": None,
                       "issue": str(exc)} for name in active_slurries}
'''
    assert text.count(controlled_target) == 1
    return text.replace(controlled_target, '    target = target_depth(table, job_type, config)\n', 1).encode()


@pytest.mark.parametrize("change", ["depth_parser", "legacy_top", "ct_guard", "ct_handler", "import_side_effect", "formatting"])
def test_legacy_placement_integrity_rejects_changes_outside_ct_allowlist(change):
    import subprocess
    from pathlib import Path
    source = Path("placement.py").read_bytes()
    original = subprocess.check_output(["git", "show", "a61d61e:placement.py"])
    assert legacy_placement_source(source) == original
    mutations = {
        "depth_parser": (b'depth = max(float(x)', b'depth = min(float(x)'),
        "legacy_top": (b'text, depth = "surface", 0.0', b'text, depth = "surface", 1.0'),
        "ct_guard": (b'if job_type == "CMT PLUG WITH CT":', b'if "PLUG" in job_type:'),
        "ct_handler": (b'"issue": str(exc)} for name in active_slurries}', b'"issue": "ignored"} for name in active_slurries}'),
        "import_side_effect": (b'import math\n', b'import math\nmath.pi = 3.0\n'),
        "formatting": (b'HOST_DESCRIPTIONS =', b'HOST_DESCRIPTIONS  ='),
    }
    old, new = mutations[change]
    assert old in source
    with pytest.raises(AssertionError):
        assert legacy_placement_source(source.replace(old, new, 1)) == original
