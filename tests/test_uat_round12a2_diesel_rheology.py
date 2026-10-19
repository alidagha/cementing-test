"""Round 12A-2: Diesel uses shared rheology, never the cement-lab pipeline."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import engineering_tools as et
import materials_db as db
import phase_7_lab as lab
import project_state as ps
import rheology
from project_io import decode_project, replace_project_state
import test_audit_regressions as audit
from test_uat_round12a1_diesel_foundation import project as operational_project, mark_document, assert_no_document


CASE = audit.AuditRegressions()


def qc_source():
    rows = {key: rheology.new_rheology_dataset() for key, _ in rheology.RHEOLOGY_DATASETS}
    for key in ("surface_down", "bhct_down"):
        rows[key] = deepcopy(audit.rheology_fixture()["surface_down"])
    return {"rheology": rows}


def project(mud="OBM", active=True):
    state = operational_project(mud, active)
    state["bhct"] = 150.
    state["lab_qc_params"]["Diesel"] = qc_source()
    return state


def status(state):
    return et.compute_phase_status(state)["phase7"]


def element(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def assert_no_cement_diesel(state):
    for key in ("cement_params", "cement_additives_dfs", "lab_grid_dfs", "lab_source_signatures",
                "inactive_slurry_drafts"):
        assert "Diesel" not in state.get(key, {})
    for key in ("lab_initialized_slurries", "cement_initialized_slurries"):
        assert "Diesel" not in state.get(key, [])
    assert "lab_payload_Diesel" not in state
    # An intentionally absent rheology draft must not be populated by status.
    assert set(state["lab_qc_params"]["Diesel"]) <= {"rheology"}


def test_phase7_composition_does_not_widen_downstream_taxonomy():
    assert db.PHASE7_LAB_FLUIDS == (*db.CEMENT_FORMULATION_FLUIDS, *db.RHEOLOGY_ONLY_FLUIDS)
    assert db.RHEOLOGY_LAB_FLUIDS == db.CEMENT_FORMULATION_FLUIDS
    assert "Diesel" not in db.RHEOLOGY_LAB_FLUIDS
    assert "Diesel" not in db.CEMENT_FORMULATION_FLUIDS
    assert "Diesel" not in db.PLACEMENT_SLURRIES


@pytest.mark.parametrize("job", audit.BATCH1_JOBS)
def test_active_diesel_tab_reuses_renderer_without_any_cement_lab_path(job):
    state = project()
    state["job_type"] = job
    with patch.object(lab, "_render_rheology", wraps=lab._render_rheology) as render:
        app = CASE.app(state)
        CASE.phase(app, "phase7")
        assert [tab.label for tab in app.tabs] == ["Diesel"]
        assert [call.args[0] for call in render.call_args_list] == ["Diesel"]
    assert not app.error and not app.exception
    labels = [item.label for group in (app.checkbox, app.number_input, app.text_input, app.selectbox, app.button)
              for item in group]
    forbidden = ("Cement SG", "Base Cement", "Mix Water", "Filtrate", "Free Water", "Thickening",
                 "UCA", "Crush", "Sync with Phase V", "Keep reviewed lab entries", "Confirm measured lab results")
    assert not any(word in label for label in labels for word in forbidden)
    assert not any(word in item.value for item in app.markdown
                   for word in ("Blend & Additives", "600 mL", "cement lab"))
    assert not app.dataframe
    assert_no_cement_diesel(app.session_state.to_dict())
    assert status(app.session_state)["level"] == "ok"


def test_existing_renderer_and_fresh_bingham_authority_are_working_controls():
    # GREEN baseline controls: these authorities work already and must be reused.
    source = qc_source()
    before = deepcopy(source)
    expected, issues = rheology.build_rheology(source)
    assert not issues
    for fluid in ("Scavenger", "Diesel"):
        result, issues = et.build_lab_rheology(source, fluid)
        assert not issues and result == expected
    assert source == before
    app = AppTest.from_string('''
import streamlit as st
from phase_7_lab import _render_rheology
_render_rheology("Scavenger", st.session_state["lab_qc_params"]["Scavenger"], "control")
''', default_timeout=30)
    app.session_state["lab_qc_params"] = {"Scavenger": deepcopy(source)}
    app.run()
    assert not app.exception and not app.warning
    assert len(app.metric) == 6


def test_exact_existing_datasets_rpms_gels_and_math_are_used():
    app = CASE.app(project())
    observed = []
    original = rheology.calculate_cemcade_bingham
    def capture(points):
        points = list(points)
        observed.append(points)
        return original(points)
    with patch.object(rheology, "calculate_cemcade_bingham", side_effect=capture):
        CASE.phase(app, "phase7")
    for key, label in rheology.RHEOLOGY_DATASETS:
        assert element(app, "checkbox", f"{label} - Diesel").value == (key != "bhct_up")
        if key == "bhct_up":
            continue
        assert [int(w.label.split(" RPM")[0]) for w in app.text_input
                if w.label.endswith(f"RPM - {label} - Diesel")] == list(rheology.RPM_ORDER)
        for gel in ("10 Sec Gel", "10 Min Gel"):
            assert element(app, "text_input", f"{gel} - {label} - Diesel")
    expected = [(rpm, float(qc_source()["rheology"]["bhct_down"]["readings"][str(rpm)]))
                for rpm in rheology.RPM_ORDER]
    assert observed and all(points == expected for points in observed)
    assert len(app.metric) == 6
    assert_no_cement_diesel(app.session_state.to_dict())


@pytest.mark.parametrize("defect", ["absent", "surface_only", "partial", "gel", "bad_fit", "optional_selected"])
def test_active_missing_or_invalid_diesel_blocks_phase7_without_fake_lab_data(defect):
    state = project()
    qc = state["lab_qc_params"]["Diesel"]
    if defect == "absent":
        qc.clear()
    elif defect == "surface_only":
        qc["rheology"]["bhct_down"]["selected"] = False
    elif defect == "partial":
        qc["rheology"]["bhct_down"]["readings"] = {"300": "168"}
    elif defect == "gel":
        qc["rheology"]["bhct_down"]["gel_10_min"] = ""
    elif defect == "bad_fit":
        qc["rheology"]["bhct_down"]["readings"] = dict(zip(
            map(str, rheology.RPM_ORDER), map(str, (150, 100, 50, 30, 15, 2, 1))))
    else:
        qc["rheology"]["bhct_up"]["selected"] = True
    result = status(state)
    assert result["level"] == "warning" and "Diesel" in result["message"]
    assert_no_cement_diesel(state)


def test_required_and_optional_dataset_policy_matches_scavenger():
    source = qc_source()
    source["rheology"]["bhct_up"]["readings"] = {"300": "168"}
    for fluid in ("Scavenger", "Diesel"):
        assert et.validate_lab_rheology(source, fluid)["bhct_down"]["is_valid_bingham"]
        broken = deepcopy(source)
        broken["rheology"]["bhct_down"]["selected"] = False
        with pytest.raises(ValueError, match="BHCT.*Ramp-Down"):
            et.validate_lab_rheology(broken, fluid)
        broken = deepcopy(source)
        broken["rheology"]["bhct_up"]["selected"] = True
        with pytest.raises(ValueError, match="BHCT.*Ramp-Up"):
            et.validate_lab_rheology(broken, fluid)
    # Preserve the shared fitter's own point-count validity, without adding
    # a Diesel-only seven-complete-readings rule or another Bingham formula.
    source["rheology"]["bhct_down"]["readings"] = {"300": "168", "200": "116"}
    assert et.validate_lab_rheology(source, "Diesel") == et.validate_lab_rheology(source, "Scavenger")


def test_valid_cement_does_not_hide_missing_active_diesel_rheology():
    app = CASE.configured_app('CSG 9 5/8"')
    state = deepcopy(app.session_state.to_dict())
    assert status(state)["level"] == "ok"
    state["mud_type"] = "OBM"
    state["fluids_config"]["active"].insert(0, "Diesel")
    state["fluids_config"]["params"]["Diesel"] = operational_project()["fluids_config"]["params"]["Diesel"]
    result = status(state)
    assert result["level"] == "warning" and "Diesel" in result["message"]
    state.setdefault("lab_qc_params", {})["Diesel"] = qc_source()
    assert status(state)["level"] == "ok"
    state["fluids_config"]["active"].remove("Diesel")
    assert not ps.prepare_calculations(state)
    mark_document(state)
    state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]["readings"] = {"300": "1"}
    assert status(state)["level"] == "ok"
    assert not ps.prepare_calculations(state)
    assert state["_compiled_doc_bytes"] == b"old document"


def test_mixed_diesel_scavenger_and_main_keep_separate_ui_and_source_paths():
    from test_uat_round6_scavenger_bhct import state_for
    state = state_for("Scavenger", "Main")
    state["mud_type"] = "OBM"
    state["fluids_config"]["active"].insert(0, "Diesel")
    state["fluids_config"]["params"]["Diesel"] = operational_project()["fluids_config"]["params"]["Diesel"]
    state["lab_qc_params"]["Diesel"] = qc_source()
    ps.refresh_fluids(state)
    # Supply the same dormant source rows the existing renderer initializes,
    # then review the legacy fluids through their normal signature authority.
    for name in ("Scavenger", "Main"):
        qc = state["lab_qc_params"][name]
        for key, _ in rheology.RHEOLOGY_DATASETS:
            qc["rheology"].setdefault(key, rheology.new_rheology_dataset())
        qc["review_signature"] = et.lab_review_signature(qc, state["lab_grid_dfs"][name])
    app = CASE.app(state)
    CASE.phase(app, "phase7")
    assert [tab.label for tab in app.tabs] == ["Diesel", "Scavenger", "Main"]
    diesel, scavenger, main = app.tabs
    assert not diesel.dataframe and not diesel.number_input and not diesel.button
    assert not any("600 mL" in item.value for item in diesel.markdown)
    assert scavenger.dataframe and main.dataframe
    assert any("Filtrate" in item.label for item in main.number_input)
    assert not any("Filtrate" in item.label for item in scavenger.number_input)
    assert status(app.session_state)["level"] == "ok"
    assert_no_cement_diesel(app.session_state.to_dict())


@pytest.mark.parametrize("field,dataset", [("selected", "bhct_up"), ("readings", "bhct_down"),
                                          ("gel_10_min", "bhct_down")])
def test_active_first_edit_navigation_invalidates_and_survives_roundtrip(field, dataset):
    app = CASE.app(project())
    CASE.phase(app, "phase7")
    label = dict(rheology.RHEOLOGY_DATASETS)[dataset]
    if field == "selected":
        widget, value = element(app, "checkbox", f"{label} - Diesel"), True
    elif field == "readings":
        widget, value = element(app, "text_input", f"300 RPM - {label} - Diesel"), "170"
    else:
        widget, value = element(app, "text_input", f"10 Min Gel - {label} - Diesel"), "14"
    mark_document(app.session_state)
    widget.set_value(value)
    CASE.phase(app, "phase1")
    row = app.session_state["lab_qc_params"]["Diesel"]["rheology"][dataset]
    assert (row["readings"]["300"] if field == "readings" else row[field]) == value
    assert_no_document(app.session_state)
    saved = audit.round_trip(app.session_state.to_dict())
    restored = CASE.app(saved)
    CASE.phase(restored, "phase7")
    assert element(restored, "checkbox" if field == "selected" else "text_input", widget.label).value == value
    assert_no_cement_diesel(saved)


def test_obm_wbm_roundtrip_preserves_exact_draft_and_does_not_reactivate():
    app = CASE.app(project())
    CASE.phase(app, "phase7")
    before = deepcopy(app.session_state["lab_qc_params"]["Diesel"])
    CASE.phase(app, "phase2_3")
    element(app, "selectbox", "Mud Type").set_value("WBM")
    CASE.phase(app, "phase1")
    saved = audit.round_trip(app.session_state.to_dict())
    assert saved["lab_qc_params"]["Diesel"] == before
    assert "Diesel" not in saved["fluids_config"]["active"]
    restored = CASE.app(saved)
    CASE.phase(restored, "phase7")
    assert not restored.tabs
    CASE.phase(restored, "phase2_3")
    element(restored, "selectbox", "Mud Type").set_value("OBM").run()
    CASE.phase(restored, "phase4")
    assert not restored.checkbox(key="chk_fluid_Diesel").value
    restored.checkbox(key="chk_fluid_Diesel").check().run()
    CASE.phase(restored, "phase7")
    assert [tab.label for tab in restored.tabs] == ["Diesel"]
    assert restored.session_state["lab_qc_params"]["Diesel"] == before
    assert status(restored.session_state)["level"] == "ok"
    assert_no_cement_diesel(restored.session_state.to_dict())


def test_inactive_draft_and_stale_callback_do_not_invalidate_current_document():
    state = project(active=False)
    state["_stale_diesel_rpm"] = "170"
    mark_document(state)
    with patch.object(lab.st, "session_state", state):
        lab._commit_rheology("Diesel", "bhct_down", "readings", "_stale_diesel_rpm", 300)
    assert state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]["readings"]["300"] == "170"
    assert state["_compiled_doc_bytes"] == b"old document"
    assert status(state)["level"] == "empty"


@pytest.mark.parametrize("active,mud", [(True, "OBM"), (False, "WBM")])
def test_source_schema_roundtrip_rebuilds_fits_and_never_creates_payload(active, mud):
    state = project(mud, active)
    before = deepcopy(state["lab_qc_params"]["Diesel"])
    expected = et.validate_lab_rheology(before, "Scavenger")
    restored = audit.round_trip(state)
    assert restored["lab_qc_params"]["Diesel"] == before
    assert et.validate_lab_rheology(restored["lab_qc_params"]["Diesel"], "Diesel") == expected
    assert ps.refresh_lab_payloads(restored) == []
    assert_no_cement_diesel(restored)
    for row in restored["lab_qc_params"]["Diesel"]["rheology"].values():
        assert set(row) == {"selected", "readings", "gel_10_sec", "gel_10_min"}


@pytest.mark.parametrize("bad", [{"pv_cp": 10}, {"bhct_down": {"selected": "yes"}},
    {"bhct_down": {"selected": True, "readings": {"900": "10"}}},
    {"bhct_down": {"selected": True, "gel_10_min": True}}])
def test_malformed_saved_rheology_still_rejects_transactionally(bad):
    state = project()
    state["lab_qc_params"]["Diesel"]["rheology"] = bad
    raw = json.dumps({key: audit.namespace["serialize_item"](value) for key, value in state.items()}).encode()
    current = {"well_name": "Keep current", "_compiled_doc_bytes": b"current"}
    before = deepcopy(current)
    with pytest.raises(ValueError):
        replace_project_state(current, decode_project(raw, audit.namespace["deserialize_item"]), "bad")
    assert current == before
