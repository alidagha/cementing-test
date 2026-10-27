"""Round 10A pure Pumping Simulation boundary; existing workflows stay independent."""
import hashlib
import importlib
import importlib.util
import math
from pathlib import Path
import pickle

import pandas as pd
import pytest

import centralizer_adapter
import cement_chart_model
import materials_db
import rheology
from placement import hardware_choices, target_descriptions
from test_uat_round9b_geometry import hardware, state_for
from test_uat_round9d_static_solver import zones_for
from test_uat_round9e_dynamic_solver import dynamic_state, auxiliary, readings, reviewed_spacer


def adapter():
    assert importlib.util.find_spec("pumping_simulation") is not None, "Round 10A pure adapter is absent"
    return importlib.import_module("pumping_simulation")


def program_state(kind="casing", fluids=None):
    state = state_for(kind)
    if kind == "tieback":
        state["placement_config"]["tie_back_liner_lap_m"] = 0.
        state["hardware_table"] = hardware(
            ("Tie Back", "400", "7", 6.),
            ("Previous Casing", "800", "9 5/8", 8.535),
            ("Previous Liner", "400-1000", "7", 6.),
            ("Open Hole Size", "1000", "8.5", 8.5))
        state["placement_config"]["host_row"] = next(iter(hardware_choices(
            state["hardware_table"], {"Previous Casing"})))
    state["placement_config"]["target_row"] = next(iter(hardware_choices(
        state["hardware_table"], target_descriptions(state["job_type"]))))
    state.update(mud_density="80-82", plastic_viscosity="10", yield_point="1",
                 effective_pv=999., effective_yp=999., bhsp="7300+1000")
    fluids = {"Tail": 2., "Displacement Fluid": 2.} if fluids is None else fluids
    state["fluids_config"] = {"active": list(fluids), "params": {
        name: {"volume": volume, "density": "118", "pump_rate": "4-6",
               "material_name": "WATER" if name == "Pre Flush" else name}
        for name, volume in fluids.items()}}
    state["lab_qc_params"] = {name: {"rheology": {"bhct_down": {
        "selected": True, "readings": readings(), "gel_10_sec": "-", "gel_10_min": "10"}}}
        for name in fluids if name in ("Main", "Tail", "Lead", "Lead #1", "Lead #2", "Scavenger")}
    state["centralizer_config"] = {"aux_rheology": auxiliary()}
    return reviewed_spacer(state)


def test_zero_mud_yp_is_blocked_before_engine_acceptance_without_fabrication(monkeypatch):
    app = adapter()
    state = program_state()
    state["yield_point"] = "0"
    before = pickle.dumps(state)
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid Mud reached frozen simulation")
    monkeypatch.setattr(app.fcm, "build_three_charts", forbidden)
    monkeypatch.setattr(app.fcm, "_build_fluids", forbidden)
    with pytest.raises(ValueError, match="Phase II.*Mud.*Pumping Simulation.*YP > 0"):
        app.prepare_pumping_simulation(state)
    with pytest.raises(ValueError, match="Phase II.*Mud.*Pumping Simulation.*YP > 0"):
        app.run_pumping_simulation(state)
    assert pickle.dumps(state) == before


def test_positive_mud_rheology_reaches_intended_engine_path_without_gel(monkeypatch):
    app = adapter()
    state = program_state()
    prepared = app.prepare_pumping_simulation(state)
    assert prepared["inputs"]["mud_pv_yp"] == (10., 1.)
    assert "Displacement Fluid" not in prepared["inputs"]["rheology"]
    calls = []
    def capture(**kwargs):
        calls.append(kwargs)
        return "figure", "result", ["frozen non-rheology warning"]
    monkeypatch.setattr(app.fcm, "build_three_charts", capture)
    result = app.run_pumping_simulation(state)
    assert len(calls) == 1 and calls[0]["mud_pv_yp"] == (10., 1.)
    assert "Displacement Fluid" not in calls[0]["rheology"]
    assert result["figure"] == "figure" and result["result"] == "result"
    assert "frozen non-rheology warning" in result["warnings"]


def test_centralizer_zero_yp_contract_remains_unchanged():
    state = dynamic_state()
    state["plastic_viscosity"], state["yield_point"] = "10", "0"
    catalog = centralizer_adapter.load_official_catalog()
    result = centralizer_adapter.build_dynamic_payload(state, zones_for(catalog), catalog,
                                                       aux_rheology=auxiliary())
    assert result["diagnostics"]["rheology"]["Displacement Fluid"]["ty_lbf_100ft2"] == 0.


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_current_hardware_geometry_is_prepared_purely(kind):
    app = adapter()
    state = program_state(kind)
    before = pickle.dumps(state)
    prepared = app.prepare_pumping_simulation(state)
    assert prepared["applicable"] is True
    assert prepared["inputs"]["geometry"].td_m == 1000.
    assert pickle.dumps(state) == before


def test_frozen_admission_hash_and_defaults():
    app = adapter()
    assert hashlib.sha256(Path(app.fcm.__file__).read_bytes()).hexdigest() == (
        "ceaaff1311b241c8793fc65b0004a8ca28bef463d93db0957d9b650522bdc5ea")
    assert app.fcm.SLURRY_TYPES == ("Main", "Tail", "Lead", "Lead #1", "Lead #2")
    options = app.prepare_pumping_simulation(program_state())["inputs"]["options"]
    assert vars(options) == vars(app.fcm.ChartOptions())
    assert options.dt_min == .02 and options.tail_cap_min == 60. and options.shutin_ramp_min == 10.


@pytest.mark.parametrize("job", materials_db.JOB_TYPES)
def test_exact_supported_applicability(job, monkeypatch):
    app = adapter()
    def forbidden(*args, **kwargs):
        raise AssertionError("N/A job executed or parsed simulation inputs")
    shallow = job in ('CSG 30"', 'CSG 24"', 'CSG 20"', 'CSG 18 5/8"')
    if shallow or job in ("CMT PLUG", "CMT SQUEEZE", materials_db.CT_JOB):
        monkeypatch.setattr(app.fcm, "build_three_charts", forbidden)
        result = app.run_pumping_simulation({"job_type": job})
        assert result["applicable"] is False
        assert result["message"] == ("Not applicable (shallow casing)." if shallow else "Not applicable (Plug/Squeeze).")
        if shallow:
            assert cement_chart_model.chart_job_kind(job) == "casing"
        assert result["figure"] is None and result["result"] is None and result["inputs"] is None
    else:
        kind = cement_chart_model.chart_job_kind(job)
        state = program_state(kind)
        state["job_type"] = state["placement_config"]["job_type"] = job
        assert app.prepare_pumping_simulation(state)["applicable"] is True


def test_unknown_job_does_not_infer_a_family():
    with pytest.raises(ValueError):
        adapter().prepare_pumping_simulation({"job_type": 'CSG FUTURE 99"'})


@pytest.mark.parametrize("field", ["plastic_viscosity", "yield_point"])
@pytest.mark.parametrize("value", [None, "", 0, -1, float("nan"), float("inf"), True, "bad"])
def test_bad_mud_is_controlled_before_simulation(field, value, monkeypatch):
    app = adapter()
    state = program_state()
    state[field] = value
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid Mud reached solver")
    monkeypatch.setattr(app.fcm, "build_three_charts", forbidden)
    with pytest.raises(ValueError, match="Phase II.*Mud.*YP > 0"):
        app.run_pumping_simulation(state)


def test_phase_ii_raw_ranges_and_config_first_fluid_rebuild_ignore_stale_caches():
    app = adapter()
    state = program_state(fluids={"Displacement Fluid": 7., "Scavenger": 5., "Spacer": 3., "Tail": 2.})
    state.update(plastic_viscosity="10-12", yield_point="1-3")
    state["fluid_data"] = {name: {"volume": 999., "density": "999", "min_rate": 999.,
        "duration_min": 999., "cumul_time_min": 999.} for name in state["fluids_config"]["active"]}
    state["fluids_config"]["params"]["Tail"]["density"] = "116-120"
    prepared = app.prepare_pumping_simulation(state)["inputs"]
    assert prepared["mud_pv_yp"] == (11., 2.)
    assert list(prepared["fluid_data"]) == ["Spacer", "Scavenger", "Tail", "Displacement Fluid"]
    cumulative = 0.
    for name, row in prepared["fluid_data"].items():
        assert row["volume"] == state["fluids_config"]["params"][name]["volume"]
        assert row["min_rate"] == 4. and row["duration_min"] == row["volume"] / 4.
        cumulative += row["duration_min"]
        assert row["cumul_time_min"] == cumulative
        assert row["effective_density"] == (81. if name == "Displacement Fluid" else 118.)
    assert prepared["bhsp"] == "7300+1000"
    assert app.fcm.parse_bhsp_psi(prepared["bhsp"]) == 7300.


def test_piecewise_casing_and_liner_use_exact_resolved_hardware_dimensions():
    app = adapter()
    for kind in ("casing", "liner"):
        state = program_state(kind)
        geometry = app.prepare_pumping_simulation(state)["inputs"]["geometry"]
        canonical = cement_chart_model.resolve_chart_geometry(state)
        assert [(s.z_top, s.z_bot, s.id_in, s.od_in) for s in geometry.pipe_sections] == [
            (s["top_md"], s["bottom_md"], s["id_in"], s["od_in"]) for s in canonical["active_string"]]
        if kind == "liner":
            assert geometry.pipe_sections[0].z_bot == geometry.pipe_sections[1].z_top == 400.
            assert geometry.pipe_sections[0].id_in == 4. and geometry.pipe_sections[1].id_in == 6.
    state = program_state()
    first = state["hardware_table"].iloc[0].to_dict()
    first.update({"MD (m)": "300", "Size (in)": "10", "ID (in)": 9.})
    state["hardware_table"] = pd.concat([pd.DataFrame([first]), state["hardware_table"]], ignore_index=True)
    geometry = app.prepare_pumping_simulation(state)["inputs"]["geometry"]
    assert [(s.z_top, s.z_bot, s.id_in) for s in geometry.pipe_sections] == [(0., 300., 9.), (300., 1000., 8.535)]


def test_tie_back_flows_through_actual_old_liner_to_its_shoe():
    app = adapter()
    state = program_state("tieback")
    state["hardware_table"].at[2, "ID (in)"] = 6.276
    geometry = app.prepare_pumping_simulation(state)["inputs"]["geometry"]
    assert [(s.z_top, s.z_bot, s.id_in) for s in geometry.pipe_sections] == [(0., 400., 6.), (400., 1000., 6.276)]
    assert [(s.z_top, s.z_bot, s.do_in) for s in geometry.ann_sections] == [(0., 800., 8.535), (800., 1000., 8.5)]
    assert geometry.track_depth_m == 400. and geometry.td_m == 1000.


def test_tie_back_explicit_host_overrules_conflicting_frozen_auto_host_without_truncating_flow():
    app = adapter()
    state = program_state("tieback")
    state["hardware_table"].at[2, "ID (in)"] = 6.276
    extra = {"Joint (m)": 12.2, "Weight (ppf)": 50., "Grade": "K-55", "Description": "Casing",
             "MD (m)": "0-1000", "Size (in)": "13 3/8", "ID (in)": 12.415}
    state["hardware_table"] = pd.concat([state["hardware_table"], pd.DataFrame([extra])], ignore_index=True)
    before = pickle.dumps(state)
    canonical = cement_chart_model.resolve_chart_geometry(state)
    assert canonical["enclosing_string"][0]["id_in"] == 8.535
    rows = state["hardware_table"].to_dict("records")
    automatic, _ = app.fcm.geometry_from_hardware(rows, target_row=rows[0], job_type=state["job_type"])
    assert automatic.ann_sections[0].do_in == 12.415
    geometry = app.prepare_pumping_simulation(state)["inputs"]["geometry"]
    assert geometry.ann_sections[0].do_in == 8.535
    assert geometry.track_depth_m == 400. and geometry.td_m == 1000.
    assert [(s.z_top, s.z_bot, s.id_in) for s in geometry.pipe_sections] == [(0., 400., 6.), (400., 1000., 6.276)]
    assert pickle.dumps(state) == before


@pytest.mark.parametrize("fault", ["missing", "unresolved", "ambiguous", "invalid_diameter"])
def test_unresolved_tie_back_host_never_falls_back_to_automatic_walk(fault, monkeypatch):
    app = adapter()
    state = program_state("tieback")
    if fault == "missing":
        state["placement_config"].pop("host_row")
    elif fault == "unresolved":
        state["placement_config"]["host_row"] = "unresolved-current-host"
    elif fault == "ambiguous":
        state["hardware_table"] = pd.concat([state["hardware_table"], state["hardware_table"].iloc[[1]]], ignore_index=True)
    else:
        state["hardware_table"].at[1, "ID (in)"] = 6.
    def forbidden(*args, **kwargs):
        raise AssertionError("Unresolved host reached automatic host inference")
    monkeypatch.setattr(app.fcm, "geometry_from_hardware", forbidden)
    with pytest.raises(ValueError):
        app.prepare_pumping_simulation(state)


@pytest.mark.parametrize("fault", ["missing_old_liner", "point_without_top", "reversed_interval", "ambiguous_old_liner",
                                  "invalid_old_id", "missing_open_hole", "invalid_host_below_tie_in"])
def test_unresolved_tie_back_continuation_has_no_geometry_defaults(fault):
    state = program_state("tieback")
    if fault == "missing_old_liner":
        state["hardware_table"] = state["hardware_table"].drop(index=2)
    elif fault == "point_without_top":
        state["hardware_table"].at[2, "MD (m)"] = "1000"
    elif fault == "reversed_interval":
        state["hardware_table"].at[2, "MD (m)"] = "1000-400"
    elif fault == "ambiguous_old_liner":
        state["hardware_table"] = pd.concat([state["hardware_table"], state["hardware_table"].iloc[[2]]], ignore_index=True)
    elif fault == "invalid_old_id":
        state["hardware_table"].at[2, "ID (in)"] = 8.
    elif fault == "missing_open_hole":
        state["hardware_table"] = state["hardware_table"].drop(index=3)
    else:
        row = state["hardware_table"].iloc[1].to_dict()
        state["hardware_table"].at[1, "MD (m)"] = "500"
        row.update({"MD (m)": "500-800", "Size (in)": "8", "ID (in)": 6.5})
        state["hardware_table"] = pd.concat([state["hardware_table"].iloc[:2], pd.DataFrame([row]),
                                             state["hardware_table"].iloc[2:]], ignore_index=True)
        state["placement_config"]["host_row"] = next(iter(hardware_choices(
            state["hardware_table"], {"Previous Casing"})))
    with pytest.raises(ValueError):
        adapter().prepare_pumping_simulation(state)


def test_tie_back_report_origin_cannot_move_hydraulic_bounds():
    app = adapter()
    state = program_state("tieback")
    expected = app.prepare_pumping_simulation(state)["inputs"]["geometry"]
    for origin in ("Target depth", "Tie Back Sleeve", "Shoe"):
        state["executive_summary_config"] = {"version": 1, "job_type": state["job_type"], "tie_back_origin": origin}
        assert app.prepare_pumping_simulation(state)["inputs"]["geometry"] == expected


@pytest.mark.parametrize("kind", ["liner", "tieback"])
def test_real_engine_smoke_for_liner_and_tie_back(kind):
    app = adapter()
    state = program_state(kind)
    before = pickle.dumps(state)
    result = app.run_pumping_simulation(state)
    try:
        assert isinstance(result["result"], app.fcm.SimResult)
        assert len(result["figure"].axes) == 3
        assert all(math.isfinite(value) for value in result["result"].hydro)
        assert result["result"].dyn is not None
        assert pickle.dumps(state) == before
    finally:
        app.fcm.plt.close(result["figure"])


def test_frozen_zero_yp_reproduction_is_preserved_without_fabricated_gel():
    app = adapter()
    inputs = app.prepare_pumping_simulation(program_state())["inputs"]
    with pytest.raises(app.fcm.ChartInputError, match="Displacement Fluid.*YP>0 or gel>0"):
        app.fcm.build_three_charts(**{**inputs, "mud_pv_yp": (10., 0.)})


def test_real_scavenger_only_run_does_not_redefine_frozen_atcp_slurry_types():
    app = adapter()
    result = app.run_pumping_simulation(program_state(fluids={"Scavenger": 1., "Displacement Fluid": 1.}))
    try:
        assert result["result"].dyn is not None
        assert result["result"].t_atcp is None
        assert "Scavenger" not in app.fcm.SLURRY_TYPES
        assert any("No slurry reaches the track depth" in warning for warning in result["warnings"])
    finally:
        app.fcm.plt.close(result["figure"])


@pytest.mark.parametrize("target", [None, "missing", "__manual__"])
def test_missing_or_manual_unidentified_target_blocks_without_guess(target):
    state = program_state()
    state["placement_config"]["target_row"] = target
    with pytest.raises(ValueError, match="explicitly selected Hardware target"):
        adapter().prepare_pumping_simulation(state)


@pytest.mark.parametrize("fluid", ["Main", "Tail", "Lead", "Lead #1", "Lead #2", "Scavenger"])
def test_phase_vii_bhct_down_and_measured_gel_reach_frozen_mapping(fluid):
    app = adapter()
    state = program_state(fluids={fluid: 2., "Displacement Fluid": 2.})
    expected = rheology.build_rheology(state["lab_qc_params"][fluid])[0]["bhct_down"]
    prepared = app.prepare_pumping_simulation(state)["inputs"]
    mapped = prepared["rheology"][fluid] if fluid == "Scavenger" else prepared["slurry_rheology"][fluid]
    assert mapped["pv_cp"] == expected["pv_cp"]
    assert mapped["yp_lbf100ft2"] == expected["ty_lbf_100ft2"]
    assert mapped["gel_10_min"] == 10. and mapped["source"] == "phase7:bhct_down"
    if fluid == "Scavenger":
        assert fluid in prepared["fluid_data"] and fluid not in prepared["slurry_rheology"]
        assert fluid not in app.fcm.SLURRY_TYPES


@pytest.mark.parametrize("fluid", ["Tail", "Scavenger"])
@pytest.mark.parametrize("fault", ["absent", "unselected", "invalid_fit", "nonfinite", "wrong_shape"])
def test_missing_or_invalid_consumed_lab_rheology_blocks(fluid, fault):
    state = program_state(fluids={fluid: 2., "Displacement Fluid": 2.})
    row = state["lab_qc_params"][fluid]["rheology"]["bhct_down"]
    if fault == "absent":
        state["lab_qc_params"].pop(fluid)
    elif fault == "unselected":
        row["selected"] = False
    elif fault == "invalid_fit":
        row["readings"] = {str(rpm): float(rpm) for rpm in rheology.RPM_ORDER}
    elif fault == "nonfinite":
        row["readings"]["300"] = float("nan")
    else:
        state["lab_qc_params"][fluid] = None
    with pytest.raises(ValueError, match=f"Phase VII {fluid}.*bhct_down"):
        adapter().prepare_pumping_simulation(state)


@pytest.mark.parametrize("fluid", ["Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind"])
def test_each_auxiliary_uses_exact_seven_rpm_bingham_authority(fluid, monkeypatch):
    app = adapter()
    state = program_state(fluids={fluid: 1., "Tail": 2., "Displacement Fluid": 2.})
    original = rheology.calculate_cemcade_bingham
    calls = []
    def trace(points):
        points = tuple(points)
        calls.append(points)
        return original(points)
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", trace)
    prepared = app.prepare_pumping_simulation(state)["inputs"]
    expected = original(zip(rheology.RPM_ORDER, readings().values()))
    assert prepared["fluid_data"][fluid]["pv_cp"] == expected["pv_cp"]
    assert prepared["fluid_data"][fluid]["yp_lbf100ft2"] == expected["ty_lbf_100ft2"]
    assert tuple(zip(rheology.RPM_ORDER, readings().values())) in calls


@pytest.mark.parametrize("fault", ["absent", "incomplete", "extra", "bool", "nonfinite", "zero", "invalid_fit", "wrong_shape"])
def test_bad_auxiliary_readings_are_controlled(fault):
    state = program_state(fluids={"Spacer Ahead": 1., "Tail": 2., "Displacement Fluid": 2.})
    source = state["centralizer_config"]["aux_rheology"]["Spacer Ahead"]
    if fault == "absent":
        state["centralizer_config"]["aux_rheology"].pop("Spacer Ahead")
    elif fault == "incomplete":
        source.pop("3")
    elif fault == "extra":
        source["600"] = 200.
    elif fault == "invalid_fit":
        source.update({str(rpm): float(rpm) for rpm in rheology.RPM_ORDER})
    elif fault == "wrong_shape":
        state["centralizer_config"]["aux_rheology"] = None
    else:
        source["300"] = {"bool": True, "nonfinite": float("inf"), "zero": 0.}[fault]
    with pytest.raises(ValueError, match="Phase IX Spacer Ahead.*seven-RPM"):
        adapter().prepare_pumping_simulation(state)


def test_real_engine_scavenger_smoke_retains_actual_train_and_no_project_writes(monkeypatch):
    app = adapter()
    # Diesel Pumping integration is deferred; retain the certified eleven-stage smoke.
    fluids = tuple(name for name in materials_db.HYDRAULIC_EXECUTION_ORDER if name != "Diesel")
    state = program_state(fluids={name: 1. for name in reversed(fluids)})
    before = pickle.dumps(state)
    original = app.fcm.simulate
    jobs = []
    def trace(job):
        jobs.append(job)
        return original(job)
    monkeypatch.setattr(app.fcm, "simulate", trace)
    baseline_figures = app.fcm.plt.get_fignums()
    result = app.run_pumping_simulation(state)
    try:
        assert len(jobs) == 1
        job = jobs[0]
        assert [s.fluid_type for s in job.placement] == list(fluids)
        assert "Scavenger" in job.fluids and not job.frictionless
        assert all(not f.frictionless_fluid for f in job.fluids.values())
        fit = rheology.build_rheology(state["lab_qc_params"]["Scavenger"])[0]["bhct_down"]
        assert job.fluids["Scavenger"].mu_p_cp == fit["pv_cp"]
        assert job.fluids["Scavenger"].tau_y == fit["ty_lbf_100ft2"]
        assert job.fluids["Scavenger"].gel_pa == 10. * app.fcm.LBF100FT2_TO_PA
        assert isinstance(result["result"], app.fcm.SimResult)
        assert len(result["figure"].axes) == 3
        assert all(math.isfinite(x) for x in result["result"].hydro)
        assert result["result"].dyn is not None
        assert result["result"].t_eod == pytest.approx(len(fluids) / 4.)
        assert not any("HYDROSTATIC-ONLY" in w or "contribution only" in w for w in result["warnings"])
        assert pickle.dumps(state) == before
    finally:
        app.fcm.plt.close(result["figure"])
    assert app.fcm.plt.get_fignums() == baseline_figures
