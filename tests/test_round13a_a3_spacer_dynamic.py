"""A3: reviewed Phase-VII Spacer is the sole hydraulic rheology source."""
from copy import deepcopy
import pickle
import math

import pytest

import centralizer_adapter as ca
import phase_9_centralizer as p9
import pumping_simulation as pumping
import project_state as ps
import materials_db as db
import test_audit_regressions as audit
from test_uat_round10a_pumping_simulation import program_state
from test_uat_round9d_static_solver import zones_for
from test_uat_round10c_integration import save_project, restore_project
import rheology


def confirm(state):
    ps.refresh_spacer_lab(state)
    qc = state["lab_qc_params"]["Spacer"]
    from engineering_tools import lab_review_signature
    qc["reviewed"] = True
    qc["review_signature"] = lab_review_signature(qc, state["lab_grid_dfs"]["Spacer"])


def project(kind="casing"):
    state = program_state(kind, {"Pre Flush": 10., "Spacer": 20., "Tail": 30., "Displacement Fluid": 100.})
    state.update(audit.well_profile_fixture(1200., bhst=200.))
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": None, "Burst (psi)": None})
    state.update(bhct=150., bhst=200., standalone_spacer_config={
        "mode": "Barite", "dead_vol": 0., "tank_name": db.get_tank_name(state["job_type"])})
    state.setdefault("well_data", {}).update(bhct=150., bhst=200.)
    state["lab_qc_params"]["Spacer"] = {"rheology": audit.valid_export_rheology_fixture()}
    config = p9.new_config()
    config.update(physics_mode="dynamic", placement_mode="direct", zones=zones_for(ca.load_official_catalog(), kind),
                  aux_rheology=state["centralizer_config"]["aux_rheology"])
    if kind == "tieback":
        config["zones"][0]["bottom_md"] = 400.
    state["centralizer_config"] = config
    confirm(state)
    return state


def centralizer(state):
    return ca.build_dynamic_payload(state, state["centralizer_config"]["zones"], ca.load_official_catalog(),
                                    aux_rheology=state["centralizer_config"]["aux_rheology"])


@pytest.mark.parametrize("consumer", [centralizer, pumping.prepare_pumping_simulation])
def test_valid_phase7_needs_no_spacer_auxiliary(consumer):
    state = project()
    del state["centralizer_config"]["aux_rheology"]["Spacer"]
    before = pickle.dumps(state)
    consumer(state)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize("consumer", [centralizer, pumping.prepare_pumping_simulation])
def test_unreviewed_phase7_cannot_fall_back_to_valid_auxiliary(consumer):
    state = project()
    state["lab_qc_params"]["Spacer"]["reviewed"] = False
    with pytest.raises(ValueError, match="Spacer"):
        consumer(state)


@pytest.mark.parametrize("signature", [p9.source_signature, pumping.source_signature])
def test_consumed_phase7_changes_signature(signature):
    state = project()
    before = signature(state)
    state["lab_qc_params"]["Spacer"]["rheology"]["bhct_down"]["readings"]["300"] = "169"
    confirm(state)
    assert signature(state) != before


def test_phase9_has_no_spacer_editor_but_keeps_preflush():
    app = audit.AuditRegressions().app(project())
    audit.AuditRegressions().phase(app, "phase9")
    keys = [w.key for w in app.number_input]
    assert not any((key or "").startswith("_centralizer_aux_Spacer_") for key in keys)
    assert all(f"_centralizer_aux_Pre Flush_{rpm}" in keys for rpm in (300,200,100,60,30,6,3))


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_both_consumers_use_identical_bingham_values_units_and_current_stage_identity(kind):
    state = project(kind)
    before = pickle.dumps(state)
    points = [(rpm, float(state["lab_qc_params"]["Spacer"]["rheology"]["bhct_down"]["readings"][str(rpm)]))
              for rpm in rheology.RPM_ORDER]
    expected = rheology.calculate_cemcade_bingham(points)
    dynamic = centralizer(state)
    actual = dynamic["diagnostics"]["rheology"]["Spacer"]
    assert actual["source"] == "lab_bhct_down"
    inputs = pumping.prepare_pumping_simulation(state)["inputs"]
    for field in ("pv_cp", "ty_lbf_100ft2", "iod"):
        assert actual[field] == expected[field] and math.isfinite(actual[field])
    assert inputs["fluid_data"]["Spacer"]["pv_cp"] == expected["pv_cp"]
    assert inputs["fluid_data"]["Spacer"]["yp_lbf100ft2"] == expected["ty_lbf_100ft2"]
    assert inputs["fluid_data"]["Spacer"]["volume"] == 20.
    for stage in dynamic["diagnostics"]["stages_rheology"]:
        if stage["name"] == "Spacer":
            assert stage["pv_pa_s"] == expected["pv_cp"] * ca.CP_TO_PA_S
            assert stage["ty_pa"] == expected["ty_lbf_100ft2"] * ca.LBF_100FT2_TO_PA
    assert pickle.dumps(state) == before


@pytest.mark.parametrize("fault", ["missing", "qc_shape", "unselected", "incomplete", "zero", "boolean", "extra_rpm",
                                     "bad_fit", "stale_formula", "stale_review", "missing_grid"])
@pytest.mark.parametrize("consumer", [centralizer, pumping.prepare_pumping_simulation])
def test_required_phase7_admission_has_no_legacy_fallback(consumer, fault):
    state = project()
    qc = state["lab_qc_params"]["Spacer"]
    row = qc["rheology"]["bhct_down"]
    if fault == "missing":
        del state["lab_qc_params"]["Spacer"]
    elif fault == "qc_shape":
        state["lab_qc_params"]["Spacer"] = None
    elif fault == "unselected":
        row["selected"] = False
    elif fault == "incomplete":
        row["readings"] = {"300": "168"}
    elif fault == "zero":
        row["readings"]["300"] = "0"
    elif fault == "boolean":
        row["readings"]["300"] = True
    elif fault == "extra_rpm":
        row["readings"]["600"] = "300"
    elif fault == "bad_fit":
        row["readings"] = dict(zip(map(str, rheology.RPM_ORDER), (150,100,50,30,15,2,1)))
    elif fault == "stale_formula":
        state["standalone_spacer_config"]["mode"] = "Ferro Bar"
    elif fault == "stale_review":
        qc["review_signature"] = "stale"
    else:
        del state["lab_grid_dfs"]["Spacer"]
    before = pickle.dumps(state)
    with pytest.raises(ValueError, match="Spacer"):
        consumer(state)
    assert pickle.dumps(state) == before


def test_valid_two_point_lab_fit_cannot_weaken_hydraulic_seven_reading_rule():
    state = project()
    state["lab_qc_params"]["Spacer"]["rheology"]["bhct_down"]["readings"] = {"300": "168", "200": "116"}
    confirm(state)
    assert ps.spacer_lab_payload(state, rebuild=False)["rheology"]["bhct_down"]["is_valid_bingham"]
    for consumer in (centralizer, pumping.prepare_pumping_simulation):
        with pytest.raises(ValueError, match="seven RPM"):
            consumer(state)


@pytest.mark.parametrize("legacy", [None, {}, {"300": 1.}, dict.fromkeys(map(str, rheology.RPM_ORDER), 0.)])
def test_legacy_auxiliary_is_loadable_ignored_and_cannot_invalidate_current_result(legacy):
    state = project()
    signature = p9.source_signature(state)
    pumping_signature = pumping.source_signature(state)
    if legacy is None:
        state["centralizer_config"]["aux_rheology"].pop("Spacer")
    else:
        state["centralizer_config"]["aux_rheology"]["Spacer"] = legacy
    restored = audit.round_trip(state)
    assert p9.source_signature(restored) == signature
    assert pumping.source_signature(restored) == pumping_signature
    centralizer(restored)
    pumping.prepare_pumping_simulation(restored)


def test_signatures_are_pure_static_independent_and_only_consume_reviewed_hydraulic_sources():
    state = project()
    p9.execute(state)
    original = p9.source_signature(state)
    pump_original = pumping.source_signature(state)
    before = pickle.dumps(state)
    assert p9.result_is_current(state)
    assert p9.source_signature(state) == original and pumping.source_signature(state) == pump_original
    assert pickle.dumps(state) == before
    # The A2 review must be reconfirmed after an edit, even if the edited source
    # is not used by hydraulics. Once admitted, unused data must not force a solve.
    state["lab_qc_params"]["Spacer"]["rheology"]["surface_down"]["readings"]["300"] = "169"
    state["lab_qc_params"]["Spacer"]["reviewed"] = False
    assert not p9.result_is_current(state)
    confirm(state)
    assert p9.source_signature(state) == original
    assert pumping.source_signature(state) == pump_original
    assert p9.result_is_current(state)
    state["lab_qc_params"]["Spacer"]["rheology"]["bhct_down"]["readings"]["300"] = "170"
    confirm(state)
    assert not p9.result_is_current(state)
    assert pumping.source_signature(state) != pump_original
    state["centralizer_config"]["physics_mode"] = "static"
    p9.execute(state)
    state["lab_qc_params"]["Spacer"] = {}
    assert p9.result_is_current(state)
    assert centralizer_static_signature(state) == p9.source_signature(state)


def centralizer_static_signature(state):
    before = pickle.dumps(state)
    result = p9.source_signature(state)
    assert pickle.dumps(state) == before
    return result


def test_phase7_edit_navigation_restore_and_explicit_review_drive_phase9_currentness():
    case = audit.AuditRegressions()
    app = case.app(project())
    case.phase(app, "phase9")
    app.button(key="_centralizer_execute").click().run()
    assert p9.result_is_current(app.session_state)
    case.phase(app, "phase7")
    next(w for w in app.text_input if w.label == "300 RPM - BHCT — Ramp-Down - Spacer").set_value("169")
    case.phase(app, "phase9")
    assert not p9.result_is_current(app.session_state)
    assert app.session_state["lab_qc_params"]["Spacer"]["rheology"]["bhct_down"]["readings"]["300"] == "169"
    restored = restore_project(save_project(app))
    case.phase(restored, "phase9")
    assert not p9.result_is_current(restored.session_state)
    with pytest.raises(ValueError, match="Spacer"):
        pumping.prepare_pumping_simulation(restored.session_state)
    case.phase(restored, "phase7")
    next(w for w in restored.button if (w.key or "").startswith("_confirm_lab_btn_spacer_")).click().run()
    case.phase(restored, "phase9")
    restored.button(key="_centralizer_execute").click().run()
    assert p9.result_is_current(restored.session_state)
    pumping.prepare_pumping_simulation(restored.session_state)


@pytest.mark.parametrize("job", ["CMT PLUG", "CMT SQUEEZE"])
def test_not_applicable_flows_need_no_spacer_rheology(job):
    state = project()
    state["job_type"] = job
    state["lab_qc_params"].pop("Spacer")
    assert ca.solve_dynamic(state, [], [], mode="direct") is None
    assert not pumping.prepare_pumping_simulation(state)["applicable"]
