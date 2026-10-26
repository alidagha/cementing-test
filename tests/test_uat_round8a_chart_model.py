"""Owner-approved Round 8A engineering/readiness contract; no renderer."""
import importlib
import importlib.util
import json
import math
from copy import deepcopy

import pandas as pd
import pytest

import materials_db
from engineering_tools import BBL_TO_CUFT, compute_phase_status
from placement import hardware_choices
from project_io import decode_project
from project_state import prepare_calculations, refresh_well_derived
from well_profile import integrate_survey


def chart_module():
    assert importlib.util.find_spec("cement_chart_model"), "Round 8A shared chart model is absent"
    return importlib.import_module("cement_chart_model")


def hardware(*rows):
    return pd.DataFrame([{"Joint (m)": 12., "Weight (ppf)": 50., "Grade": "K-55",
                          "Collapse (psi)": 1000., "Burst (psi)": 2000.,
                          **dict(zip(("Description", "MD (m)", "Size (in)", "ID (in)"), row))}
                         for row in rows])


def chart_state():
    return {"job_type": 'CSG 9 5/8"',
            "well_geometry": {"version": 1, "type": "Vertical", "td_m": 1000.},
            "geothermal_config": {"version": 1, "source": "BHST", "surface_temp": 80., "value": 200.},
            "pore_gradient_emw_pcf": 70., "frac_gradient_emw_pcf": 160., "mud_density": "80-82",
            "hardware_table": hardware(("Casing", "1000", "9.625", 8.535),
                                       ("Previous Casing", "500", "13.375", 12.25),
                                       ("Open Hole Size", "1000", "12.25", 12.25)),
            "placement_config": {"job_type": 'CSG 9 5/8"', "target_row": "__manual__",
                                 "manual_depth_m": 1000., "chart_excess_mode": "ignore"},
            "fluids_config": {"active": ["Main", "Displacement Fluid"], "params": {
                "Main": {"volume": 50., "density": "118", "pump_rate": "4"},
                "Displacement Fluid": {"volume": 100., "density": "81", "pump_rate": "4"}}},
            "cement_params": {"Main": {"top_mode": "Depth (m MD)", "top_depth": 800.,
                                        "top_job_type": 'CSG 9 5/8"'}}}


def test_unfinished_job_selection_is_controlled_without_inventing_placement():
    from placement import slurry_intervals
    state = chart_state()
    state.pop("job_type")
    state["cement_additives_dfs"] = {"Main": pd.DataFrame()}
    intervals = slurry_intervals(state["hardware_table"], "", state["placement_config"],
                                ["Main"], state["cement_params"], state["fluids_config"]["params"])
    assert intervals["Main"]["top_depth"] is intervals["Main"]["bottom_depth"] is None
    assert "Unsupported chart job" in intervals["Main"]["issue"]
    assert compute_phase_status(state)["phase5"]["level"] != "ok"
    assert chart_module().chart_readiness(state, True)["issues"]
    assert prepare_calculations(state)
    assert "_compiled_doc_bytes" not in state


def test_direct_well_page_without_job_selection_is_a_safe_draft():
    import test_audit_regressions as audit
    app = audit.AuditRegressions().app({"_app_mode_key": "phase2_3"})
    assert not app.exception
    assert not [widget for widget in app.selectbox if widget.label == "Chart Capacity Excess Mode"]


@pytest.mark.parametrize("inactive", [False, True])
def test_negative_report_bottom_is_rejected_before_current_state_replacement(inactive):
    from project_io import replace_project_state
    project = {"job_type": 'CSG 9 5/8"', "cement_params": {"Main": {"report_bottom_depth": -1.}}}
    if inactive:
        project["inactive_slurry_drafts"] = {"Main": {"cement_params": project.pop("cement_params")["Main"]}}
    current = {"well_name": "Original project", "unchanged": [1, 2, 3]}
    original = deepcopy(current)
    with pytest.raises(ValueError, match="report_bottom_depth.*nonnegative"):
        restored = decode_project(json.dumps(project).encode(), lambda value: value)
        replace_project_state(current, restored, "bad")
    assert current == original


@pytest.mark.parametrize("depth", [None, 0., 2100.])
def test_optional_report_bottom_draft_and_surface_roundtrip(depth):
    project = {"job_type": 'CSG 9 5/8"', "cement_params": {"Main": {"report_bottom_depth": depth}}}
    restored = decode_project(json.dumps(project).encode(), lambda value: value)
    assert restored["cement_params"]["Main"]["report_bottom_depth"] == depth


@pytest.mark.parametrize("slurry", materials_db.PLACEMENT_SLURRIES)
def test_volume_driven_single_slurry_ignores_manual_top(slurry):
    state = balanced_state(top=850.)
    state["fluids_config"]["active"] = [slurry, "Displacement Fluid"]
    state["fluids_config"]["params"][slurry] = state["fluids_config"]["params"].pop("Main")
    state["cement_params"] = {slurry: {"top_mode": "Depth (m MD)", "top_depth": 700.}}
    output = chart_module().build_chart_model(state)
    row = next(r for r in output["annular_intervals"] if r["fluid"] == slurry)
    assert (row["top_md"], row["bottom_md"]) == pytest.approx((850., 1000.))


@pytest.mark.parametrize("names", [("Main",), ("Lead", "Tail"), ("Lead #1", "Tail"),
    ("Lead #1", "Lead #2", "Tail"), materials_db.PLACEMENT_SLURRIES])
def test_volume_driven_subset_final_order_and_shoe_track(names):
    state = chart_state()
    mod = chart_module()
    geometry = mod.resolve_chart_geometry(state)
    capacity = geometry["capacity_segments"][-1]["bbl_per_m"]
    state["fluids_config"]["active"] = [*names, "Displacement Fluid"]
    for name in names:
        state["fluids_config"]["params"][name] = {"volume": 40.*capacity,
            "density": "118", "pump_rate": "4"}
    state["fluids_config"]["params"][names[-1]]["volume"] += geometry["shoe_track_bbl"]
    output = mod.build_chart_model(state)
    rows = [r for r in reversed(output["annular_intervals"]) if r["fluid"] != "Mud"]
    assert [r["fluid"] for r in rows] == list(reversed(names))
    assert output["shoe_track_fluid"] == names[-1]
    assert [(r["bottom_md"], r["top_md"]) for r in rows] == pytest.approx(
        [(1000.-40*i, 960.-40*i) for i in range(len(names))])


@pytest.mark.parametrize("basis", ["auto", "unspecified", "excess", "client_request", "direct"])
def test_volume_metadata_never_changes_engineering_placement(basis):
    state = balanced_state(top=850.)
    state["cement_params"]["Main"]["top_depth"] = 700.
    state["executive_summary_config"] = {"version": 1, "job_type": state["job_type"],
        "per_slurry": {"Main": {"volume_basis": basis}}}
    result = chart_module().build_chart_model(state)
    assert next(r for r in result["annular_intervals"] if r["fluid"] == "Main")["top_md"] == pytest.approx(850.)


def test_baseline_missing_pore_frac_blocks_phase23():
    state = chart_state()
    refresh_well_derived(state)
    state.pop("pore_gradient_emw_pcf")
    state.pop("frac_gradient_emw_pcf")
    status = compute_phase_status(state)["phase2_3"]
    assert status["level"] == "warning" and "Pore" in status["message"]


def test_baseline_missing_excess_mode_blocks_phase23():
    state = chart_state()
    refresh_well_derived(state)
    state["placement_config"].pop("chart_excess_mode")
    status = compute_phase_status(state)["phase2_3"]
    assert status["level"] == "warning" and "Excess Mode" in status["message"]


@pytest.mark.parametrize("field,value", [("pore_gradient_emw_pcf", True),
                                        ("frac_gradient_emw_pcf", "160"),
                                        ("pore_gradient_emw_pcf", -1.)])
def test_new_inputs_rejected_at_json_trust_boundary(field, value):
    with pytest.raises(ValueError, match="Gradient"):
        decode_project(json.dumps({"job_type": 'CSG 9 5/8"', field: value}).encode(), lambda x: x)


def test_official_volume_places_cement_without_changing_manual_report_top():
    state = chart_state()
    original = deepcopy(state["cement_params"])
    mod = chart_module()
    result = mod.build_chart_model(state)
    cement = result["cement_placement"][0]
    capacity = result["capacity_segments"][-1]["bbl_per_m"]
    expected_top = 1000. - (50. - result["shoe_track_bbl"])/capacity
    assert cement["top_md"] == pytest.approx(expected_top, abs=1e-12)
    assert cement["top_md"] != original["Main"]["top_depth"]
    assert cement["in_well_bbl"] + cement["shoe_track_bbl"] == pytest.approx(50., abs=1e-12)
    assert not mod.chart_readiness(state, True)["issues"]
    assert state["cement_params"] == original
    state["fluids_config"]["params"]["Main"]["volume"] = result["shoe_track_bbl"] - .1
    with pytest.raises(ValueError, match="below Shoe Track"):
        mod.build_chart_model(state)
    assert state["cement_params"] == original


def test_arbitrary_md_query_is_part_of_existing_survey_authority():
    import well_profile
    assert callable(getattr(well_profile, "tvd_at_md", None)), "No shared v2.2 arbitrary-MD authority"
    frame = pd.DataFrame([[0., 0., 350.], [1000., 60., 10.]], columns=["MD", "Deviation", "Azimuth"])
    result = integrate_survey(frame)
    assert well_profile.tvd_at_md({"type": "Directional", "survey": frame}, [0., 1000.]) == result["TVD"].tolist()
    assert well_profile.tvd_at_md({"type": "Directional", "survey": frame}, [500.])[0] == pytest.approx(
        1000.*math.sin(math.radians(30))/math.radians(60), abs=1e-12)


def balanced_state(top=800., ahead=None):
    """Explicit fixture volumes follow fixed depths, never change production placement."""
    state = chart_state()
    state["cement_params"]["Main"].update(top_mode="Surface" if top == 0 else "Depth (m MD)", top_depth=top)
    model = chart_module()
    geometry = model.resolve_chart_geometry(state)
    state["fluids_config"]["params"]["Main"]["volume"] = (
        model.interval_volume(geometry["capacity_segments"], top, 1000.)+geometry["shoe_track_bbl"])
    for name, volume in (ahead or {}).items():
        state["fluids_config"]["active"].insert(0, name)
        state["fluids_config"]["params"][name] = {"volume": volume, "density": "90", "pump_rate": "4"}
    return state


def test_exact_job_mapping_and_no_future_inference():
    mod = chart_module()
    assert set(mod.CHART_JOBS) == set(materials_db.JOB_TYPES)
    assert list(mod.CHART_JOBS.values()).count("casing") == 7
    for job in ("CMT PLUG", "CMT SQUEEZE"):
        state = {"job_type": job}
        assert mod.chart_readiness(state) == {"issues": [], "warnings": [], "model": None}
        assert mod.build_chart_model(state) is None
    with pytest.raises(ValueError, match="Unsupported"):
        mod.chart_job_kind('CSG 42"')


@pytest.mark.parametrize("field,value", [("pore_gradient_emw_pcf", 0.), ("frac_gradient_emw_pcf", float("inf")),
    ("pore_gradient_emw_pcf", []), ("frac_gradient_emw_pcf", False)])
def test_pore_frac_numeric_domain(field, value):
    state = chart_state()
    state[field] = value
    assert chart_module().chart_readiness(state)["issues"]


@pytest.mark.parametrize("pore,frac", [(160., 160.), (170., 160.)])
def test_pore_must_be_strictly_below_frac(pore, frac):
    state = chart_state()
    state.update(pore_gradient_emw_pcf=pore, frac_gradient_emw_pcf=frac)
    assert "less than" in chart_module().chart_readiness(state)["issues"][0]


def test_pressure_overflow_blocks_readiness_without_inventing_an_input_limit():
    state = chart_state()
    state.update(pore_gradient_emw_pcf=1e307, frac_gradient_emw_pcf=1e308)
    mod = chart_module()
    mod.validate_chart_inputs(state, state["placement_config"])
    result = mod.chart_readiness(state, True)
    assert result["model"] is None and "finite" in result["issues"][0]
    with pytest.raises(ValueError, match="finite"):
        mod.build_chart_model(state)
    state.update(pore_gradient_emw_pcf=1e6, frac_gradient_emw_pcf=2e6)
    assert not mod.chart_readiness(state, True)["issues"]
    reference = 70.*mod.PCF_TO_KG_M3*mod.STANDARD_GRAVITY*1000./mod.PA_PER_PSI
    assert mod.pressure_psi(70., 1000.) == reference


def test_mud_range_uses_mean_and_outside_is_warning_only():
    state = balanced_state()
    mod = chart_module()
    state.update(mud_density="70-90", pore_gradient_emw_pcf=79., frac_gradient_emw_pcf=81.)
    result = mod.chart_readiness(state, True)
    assert not result["issues"]
    assert not any(warning.startswith("Mud Weight") for warning in result["warnings"])
    assert any(warning.startswith("Static Well Security: Fracture") for warning in result["warnings"])
    security = result["model"]["static_security"]
    assert result["model"]["static_security_ready"] and security["status"] == "warning"
    assert len(security["frac_violations"]) == 1
    violation = security["frac_violations"][0]
    assert violation["kind"] == "over_frac" and violation["end_md_m"] == 1000.
    assert violation["max_delta_psi"] == pytest.approx(150.3718285214352, rel=0, abs=1e-10)
    state["pore_gradient_emw_pcf"] = 80.5
    result = mod.chart_readiness(state, True)
    assert not result["issues"] and result["warnings"]
    assert any(warning.startswith("Mud Weight") for warning in result["warnings"])
    assert any(warning.startswith("Static Well Security: Fracture") for warning in result["warnings"])
    assert result["model"]["static_security"]["frac_violations"] == security["frac_violations"]
    refresh_well_derived(state)
    assert compute_phase_status(state)["phase2_3"]["level"] == "ok"
    assert result["model"]["annular_intervals"][0]["density_pcf"] == 80.


def test_pore_frac_and_mode_roundtrip_and_draft_restore():
    import test_audit_regressions as audit
    state = balanced_state()
    restored = audit.round_trip(state)
    assert restored["pore_gradient_emw_pcf"] == 70.
    assert restored["frac_gradient_emw_pcf"] == 160.
    assert restored["placement_config"]["chart_excess_mode"] == "ignore"
    assert chart_module().build_chart_model(restored) == chart_module().build_chart_model(state)
    for key in ("pore_gradient_emw_pcf", "frac_gradient_emw_pcf"):
        state[key] = None
    state["placement_config"]["chart_excess_mode"] = None
    assert audit.round_trip(state)["pore_gradient_emw_pcf"] is None
    assert chart_module().chart_readiness(state)["issues"]


@pytest.mark.parametrize("mode", [True, "automatic", 0, [], {}])
def test_mode_malformed_load_is_transactional(mode):
    from project_io import replace_project_state
    current = {"well_name": "KEEP ME"}
    raw = json.dumps({"job_type": 'CSG 9 5/8"', "placement_config": {"chart_excess_mode": mode}}).encode()
    with pytest.raises(ValueError, match="Excess Mode"):
        decoded = decode_project(raw, lambda x: x)
        replace_project_state(current, decoded)
    assert current == {"well_name": "KEEP ME"}


def test_csg_continuous_and_mixed_intervals_tapered_ids():
    state = chart_state()
    state["hardware_table"] = hardware(
        ("Casing", "300", "10", 9.), ("Casing", "300-700", "9.625", 8.535),
        ("Casing", "1000", "8.625", 7.5), ("Previous Casing", "200", "15", 13.),
        ("Previous Casing", "200-500", "13.375", 12.25), ("Open Hole Size", "1000", "12.25", 12.25))
    geom = chart_module().resolve_chart_geometry(state)
    assert [(s["top_md"], s["bottom_md"], s["id_in"]) for s in geom["active_string"]] == [
        (0., 300., 9.), (300., 700., 8.535), (700., 1000., 7.5)]
    assert [s["top_md"] for s in geom["capacity_segments"]] == [0., 200., 300., 500., 700.]
    expected_track = math.pi/4 * 7.5**2 /144/.3048/BBL_TO_CUFT*12.2
    assert geom["shoe_track_bbl"] == pytest.approx(expected_track, abs=1e-12)


@pytest.mark.parametrize("rows", [
    (("Casing", "700", "9.625", 8.535), ("Casing", "600", "9.625", 8.535)),
    (("Casing", "500", "9.625", 8.535), ("Casing", "500", "9.625", 8.535)),
    (("Casing", "300", "9.625", 8.535), ("Casing", "400-1000", "9.625", 8.535)),
    (("Casing", "700", "9.625", 8.535), ("Casing", "500-1000", "9.625", 8.535)),
    (("Casing", "1000", "9.625", 0.),),
    (("Casing", "1000", "bad", 8.535),),
    (("Casing", "1000", "9.625", 10.),),
])
def test_bad_active_geometry_never_repaired(rows):
    state = chart_state()
    state["hardware_table"] = pd.concat([hardware(*rows), state["hardware_table"].iloc[1:]], ignore_index=True)
    original = state["hardware_table"].copy(deep=True)
    assert chart_module().chart_readiness(state)["issues"]
    pd.testing.assert_frame_equal(state["hardware_table"], original)


def test_manual_depth_uses_hardware_diameters_and_no_defaults(monkeypatch):
    state = chart_state()
    monkeypatch.setattr(materials_db, "DEFAULT_HOLE_SIZES", {})
    assert chart_module().resolve_chart_geometry(state)["shoe_md"] == 1000.
    state["hardware_table"] = state["hardware_table"].iloc[:2]
    assert "Open Hole" in chart_module().chart_readiness(state)["issues"][0]
    state["hardware_table"] = state["hardware_table"].iloc[1:]
    assert chart_module().chart_readiness(state)["issues"]


def test_liner_hanger_and_explicit_running_string_geometry():
    state = chart_state()
    state["job_type"] = state["placement_config"]["job_type"] = 'LNR 7"'
    state["hardware_table"] = hardware(("Drill Pipes", "400", "5", 4.),
        ("Liner", "700", "7", 6.2), ("Liner", "1000", "7", 6.),
        ("Liner Hanger", "400", "7", 6.), ("Previous Casing", "500", "9.625", 8.535),
        ("Open Hole Size", "1000", "8.5", 8.5))
    geometry = chart_module().resolve_chart_geometry(state)
    assert [s["top_md"] for s in geometry["active_string"]] == [0., 400., 700.]
    assert geometry["active_string"][0]["description"] == "Drill Pipes"
    state["hardware_table"] = state["hardware_table"].iloc[1:]
    assert "Drill Pipes" in chart_module().chart_readiness(state)["issues"][0]


def test_tieback_host_is_selected_and_pore_frac_are_shoe_markers():
    state = chart_state()
    state["job_type"] = state["placement_config"]["job_type"] = 'TIE BACK LNR 7"'
    state["cement_params"]["Main"]["top_job_type"] = state["job_type"]
    state["hardware_table"] = hardware(("Tie Back", "1000", "7", 6.),
        ("Previous Casing", "1100", "9.625", 8.535),
        ("Previous Liner", "1000-1200", "7", 6.))
    state["placement_config"]["tie_back_liner_lap_m"] = 0.  # Explicit synthetic Top.
    assert "selected" in chart_module().chart_readiness(state)["issues"][0]
    state["placement_config"]["host_row"] = next(iter(hardware_choices(state["hardware_table"], {"Previous Casing"})))
    mod = chart_module()
    geometry = mod.resolve_chart_geometry(state)
    assert geometry["capacity_segments"][0]["kind"] == "cased"
    state["fluids_config"]["params"]["Main"]["volume"] = mod.interval_volume(geometry["capacity_segments"], 800., 1000.)+geometry["shoe_track_bbl"]
    output = mod.build_chart_model(state)
    assert output["pore_frac"]["kind"] == "markers"
    assert output["pore_frac"]["md_m"] == [1000.]


def test_offsets_are_project_rules_and_landing_is_reference_only(monkeypatch):
    mod = chart_module()
    state = balanced_state()
    before = mod.build_chart_model(state)
    assert before["float_collar_md"] == 987.8
    assert before["landing_collar_md"] == 975.6
    monkeypatch.setattr(mod, "LANDING_COLLAR_OFFSET_M", 25.4)
    after = mod.build_chart_model(state)
    assert after.pop("landing_collar_md") != before.pop("landing_collar_md")
    assert before == after
    state["placement_config"]["manual_depth_m"] = 20.
    assert "shallow" in mod.chart_readiness(state)["issues"][0]


def test_apply_excess_capacity_for_every_fluid_and_zero_is_real_zero():
    mod = chart_module()
    state = balanced_state(ahead={"Scavenger": 10., "Spacer Ahead": 10., "Spacer": 10., "Pre Flush": 10.})
    nominal = mod.resolve_chart_geometry(state)
    state["placement_config"].update(chart_excess_mode="apply", excess_csg_oh_pct=100., excess_csg_csg_pct=20.)
    geom = mod.resolve_chart_geometry(state)
    assert [s["bbl_per_m"]/s["nominal_bbl_per_m"] for s in geom["capacity_segments"]] == [1.2, 2.]
    state["fluids_config"]["params"]["Main"]["volume"] = mod.interval_volume(geom["capacity_segments"], 800., 1000.)+geom["shoe_track_bbl"]
    output = mod.build_chart_model(state)
    for row in output["annular_intervals"]:
        assert row["in_well_bbl"] == pytest.approx(mod.interval_volume(geom["capacity_segments"], row["top_md"], row["bottom_md"]), abs=1e-12)
    state["placement_config"].update(excess_csg_oh_pct=0., excess_csg_csg_pct=0.)
    assert mod.resolve_chart_geometry(state)["capacity_segments"] == nominal["capacity_segments"]


@pytest.mark.parametrize("missing", ["excess_csg_oh_pct", "excess_csg_csg_pct"])
def test_apply_missing_relevant_excess_blocks(missing):
    state = chart_state()
    state["placement_config"].update(chart_excess_mode="apply", excess_csg_oh_pct=0., excess_csg_csg_pct=0.)
    state["placement_config"][missing] = None
    assert missing in chart_module().chart_readiness(state)["issues"][0]


@pytest.mark.parametrize("delta", [-1., 1.])
def test_volume_change_moves_modelled_placement_not_manual_report_top(delta):
    mod = chart_module()
    state = balanced_state()
    params = deepcopy(state["cement_params"])
    state["fluids_config"]["params"]["Main"]["volume"] += delta
    result = mod.build_chart_model(state)
    expected_top = 800. - delta/result["capacity_segments"][-1]["bbl_per_m"]
    assert result["cement_placement"][0]["top_md"] == pytest.approx(expected_top, abs=1e-12)
    assert result["returned_bbl"]["Main"] == 0.
    assert state["cement_params"] == params
    assert not mod.chart_readiness(state, True)["issues"]


def test_surface_surplus_returns_and_lower_volume_leaves_resolved_ahead_fluid():
    state = balanced_state(top=0., ahead={"Scavenger": 10., "Pre Flush": 20.})
    mod = chart_module()
    state["fluids_config"]["params"]["Main"]["volume"] += 5.
    output = mod.build_chart_model(state)
    assert output["returned_bbl"] == pytest.approx({"Main": 5., "Scavenger": 10., "Pre Flush": 20.})
    assert {row["fluid"] for row in output["annular_intervals"]} == {"Main"}
    state["fluids_config"]["params"]["Main"]["volume"] -= 6.
    output = mod.build_chart_model(state)
    assert output["cement_placement"][0]["top_md"] == pytest.approx(
        1./output["capacity_segments"][0]["bbl_per_m"], abs=1e-12)
    assert output["returned_bbl"] == pytest.approx({"Main": 0., "Scavenger": 9., "Pre Flush": 20.})
    assert {row["fluid"] for row in output["annular_intervals"]} == {"Main", "Scavenger"}
    assert math.fsum(row["in_well_bbl"] for row in output["annular_intervals"]) == pytest.approx(
        output["original_annular_bbl"], abs=1e-12)
    assert state["cement_params"]["Main"]["top_mode"] == "Surface"


def test_deepest_canonical_slurry_gets_track_and_placement_authority_is_reused(monkeypatch):
    import placement
    state = balanced_state()
    state["fluids_config"]["active"] = ["Lead", "Tail", "Displacement Fluid"]
    state["cement_params"] = {"Lead": {"top_mode": "Depth (m MD)", "top_depth": 600.},
                              "Tail": {"top_mode": "Depth (m MD)", "top_depth": 800.}}
    mod = chart_module()
    geom = mod.resolve_chart_geometry(state)
    for name, top, bottom, track in (("Lead", 600., 800., 0.), ("Tail", 800., 1000., geom["shoe_track_bbl"])):
        state["fluids_config"]["params"][name] = {"volume": mod.interval_volume(geom["capacity_segments"], top, bottom)+track,
                                                  "density": "118", "pump_rate": "4"}
    real = mod.resolve_cement_placement
    calls = []
    def traced(*args):
        calls.append(args[0]["fluids_config"]["active"])
        return real(*args)
    monkeypatch.setattr(mod, "resolve_cement_placement", traced)
    result = mod.build_chart_model(state)
    projected = placement.slurry_intervals(state["hardware_table"], state["job_type"],
        state["placement_config"], ["Lead", "Tail"], state["cement_params"],
        state["fluids_config"]["params"])
    assert calls == [["Lead", "Tail", "Displacement Fluid"], ["Lead", "Tail"]]
    assert [(name, p["top_depth"], p["bottom_depth"]) for name, p in projected.items()] == [
        (row["fluid"], row["top_md"], row["bottom_md"]) for row in result["cement_placement"]]
    assert result["shoe_track_fluid"] == "Tail"
    assert [r["shoe_track_bbl"] for r in result["annular_intervals"] if r["fluid"] in {"Lead", "Tail"}] == [0., geom["shoe_track_bbl"]]


def test_ahead_order_clipping_conservation_and_excluded_fluids():
    state = balanced_state(ahead={"Pre Flush": 200., "Spacer": 20., "Spacer Ahead": 20., "Scavenger": 20., "Spacer Behind": 10.})
    params = deepcopy(state["cement_params"])
    output = chart_module().build_chart_model(state)
    assert state["cement_params"] == params and "Scavenger" not in params
    names = [r["fluid"] for r in reversed(output["annular_intervals"])]
    assert names[0] == "Main"
    assert names.index("Scavenger") < names.index("Spacer Ahead") < names.index("Spacer") < names.index("Pre Flush")
    assert "Spacer Behind" not in names and "Displacement Fluid" not in names and "Mud" not in names
    assert output["returned_bbl"]["Pre Flush"] > 0
    assert sum(r["in_well_bbl"] for r in output["annular_intervals"]) == pytest.approx(output["original_annular_bbl"], abs=1e-12)
    for name in ("Scavenger", "Spacer Ahead", "Spacer", "Pre Flush"):
        placed = math.fsum(r["in_well_bbl"] for r in output["annular_intervals"] if r["fluid"] == name)
        assert placed+output["returned_bbl"][name] == pytest.approx(state["fluids_config"]["params"][name]["volume"], abs=1e-12)


def test_residual_mud_is_remaining_original_volume_and_no_gap():
    output = chart_module().build_chart_model(balanced_state(ahead={"Scavenger": 20.}))
    rows = output["annular_intervals"]
    assert rows[0]["fluid"] == "Mud"
    assert rows[0]["in_well_bbl"] == pytest.approx(output["original_annular_bbl"]-sum(r["in_well_bbl"] for r in rows[1:]))
    assert all(a["bottom_md"] == b["top_md"] for a,b in zip(rows, rows[1:]))


def test_pressure_uses_actual_density_and_tvd_not_md():
    mod = chart_module()
    state = balanced_state(ahead={"Scavenger": 20.})
    state["well_geometry"] = {"version": 1, "type": "Directional", "survey": pd.DataFrame(
        [[0., 60., 350.], [1000., 60., 10.]], columns=["MD", "Deviation", "Azimuth"])}
    output = mod.build_chart_model(state)
    expected = math.fsum(mod.pressure_psi(r["density_pcf"], (r["bottom_md"]-r["top_md"])*math.cos(math.radians(60.)))
                         for r in output["annular_intervals"])
    assert output["hydrostatic"]["pressure_psi"][-1] == pytest.approx(expected, abs=1e-10)
    assert output["pore_frac"]["pore_psi"][-1] == pytest.approx(mod.pressure_psi(70., 500.), abs=1e-10)
    assert output["pore_frac"]["kind"] == "curves"
    assert output["pore_frac"]["frac_psi"][-1] > output["pore_frac"]["pore_psi"][-1]


def test_continuous_tvd_drop_blocks_only_security_not_survey_or_fluid_sequence():
    state = balanced_state()
    frame = pd.DataFrame([[0., 0., 0.], [1000., 100., 0.]], columns=["MD", "Deviation", "Azimuth"])
    state["well_geometry"] = {"version": 1, "type": "Directional", "survey": frame}
    stations = integrate_survey(frame)
    assert stations.iloc[-1]["TVD"] > 0  # Endpoint-only test would miss the terminal descent.
    mod = chart_module()
    output = mod.build_chart_model(state)
    assert output["fluid_sequence_ready"] is True
    assert output["static_security_ready"] is False
    assert output["hydrostatic"]["pressure_psi"] == []
    assert "TVD decreases" in mod.chart_readiness(state, True)["issues"][0]
    pd.testing.assert_frame_equal(integrate_survey(frame), stations)


def test_station_output_bit_parity_and_partial_interval_branch(tmp_path):
    import runpy
    import subprocess
    import well_profile
    path = tmp_path / "baseline_well_profile.py"
    path.write_bytes(subprocess.check_output(["git", "show", "HEAD:well_profile.py"]))
    original = runpy.run_path(str(path))["integrate_survey"]
    for frame in (pd.DataFrame([[0., 20., 350.], [100., 60., 10.], [1000., 90., 100.]], columns=["MD", "Deviation", "Azimuth"]),
                  pd.DataFrame([[0., 20., 0.], [1000., 20.+1e-10, 0.]], columns=["MD", "Deviation", "Azimuth"])):
        before = original(frame)
        pd.testing.assert_frame_equal(integrate_survey(frame), before, check_exact=True)
        assert well_profile.tvd_at_md({"type": "Directional", "survey": frame}, before["MD"].tolist()) == before["TVD"].tolist()
    assert well_profile.trajectory_tvd_decreases({"type": "Directional", "survey": frame}, 1000.) is False


@pytest.fixture(scope="module")
def reviewed_project():
    """Existing Lab prerequisites plus explicit, consistent current chart Hardware."""
    import test_audit_regressions as audit
    case = audit.AuditRegressions()
    state = audit.round_trip(case.configured_app('CSG 9 5/8"').session_state.to_dict())
    state.update(pore_gradient_emw_pcf=70., frac_gradient_emw_pcf=160.)
    state["placement_config"]["chart_excess_mode"] = "ignore"
    state["hardware_table"] = hardware(("Casing", "3000", "9.625", 8.535),
        ("Previous Casing", "1500", "10", 9.65), ("Open Hole Size", "3000", "9.65", 9.65))
    state["placement_config"]["target_row"] = next(iter(hardware_choices(state["hardware_table"], {"Casing"})))
    assert not prepare_calculations(state)
    return state


def test_direct_fresh_restore_and_existing_word_build_gate(reviewed_project):
    import test_audit_regressions as audit
    import phase_10_procedure as report
    from unittest.mock import patch
    current = audit.round_trip(reviewed_project)
    assert not prepare_calculations(current)
    assert current["_cement_chart_model"]["static_security_ready"]
    audit.ensure_current_centralizer(current)
    with patch.object(report.st, "session_state", current):
        context = report.build_master_context()
    assert context["slurries"][0]["name"] == "Main"
    saved = {key: audit.namespace["serialize_item"](value) for key,value in current.items()
             if audit.is_project_key(key)}
    assert "_cement_chart_model" not in saved and "_cement_chart_source" not in saved
    assert "hydrostatic" not in saved and not any(key.endswith("_raw") for key in saved)
    for field in ("pore_gradient_emw_pcf", "frac_gradient_emw_pcf"):
        broken = deepcopy(current)
        broken[field] = None
        with patch.object(report.st, "session_state", broken), pytest.raises(ValueError, match="Gradient"):
            report.build_master_context()
        assert "_compiled_doc_bytes" not in broken


def test_pore_frac_edit_stales_word_but_does_not_stale_lab(reviewed_project):
    from project_state import lab_source_signature
    state = deepcopy(reviewed_project)
    assert not prepare_calculations(state)
    signature = lab_source_signature(state, "Main")
    qc = deepcopy(state["lab_qc_params"]["Main"])
    state["_compiled_doc_bytes"] = b"STALE"
    state["_compiled_doc_signature"] = "OLD"
    state["pore_gradient_emw_pcf"] = 75.
    assert not prepare_calculations(state)
    assert "_compiled_doc_bytes" not in state
    assert lab_source_signature(state, "Main") == signature
    assert state["lab_qc_params"]["Main"] == qc and qc["reviewed"] is True


def test_both_word_overrides_are_isolated_after_fresh_restore(reviewed_project):
    import test_audit_regressions as audit
    import phase_10_procedure as report
    from project_state import lab_source_signature
    from unittest.mock import patch
    state = deepcopy(reviewed_project)
    assert not prepare_calculations(state)
    model = deepcopy(state["_cement_chart_model"])
    source = lab_source_signature(state, "Main")
    state["_compiled_doc_bytes"] = b"OLD"
    state["cement_params"]["Main"].update(top_mode="Depth (m MD)", top_depth=2100.,
        top_job_type=state["job_type"], report_bottom_depth=2900.)
    assert not prepare_calculations(state)
    assert "_compiled_doc_bytes" not in state
    assert state["_cement_chart_model"] == model
    restored = audit.round_trip(state)
    assert not prepare_calculations(restored)
    assert restored["_cement_chart_model"] == model
    assert lab_source_signature(restored, "Main") == source
    audit.ensure_current_centralizer(restored)
    with patch.object(report.st, "session_state", restored):
        payload = report.build_master_context()["slurries"][0]
    assert payload["top"] == "2100.0 m" and payload["bottom"] == "2900.0 m MD"


def test_new_shadow_widgets_first_edit_navigation_restore(reviewed_project):
    import test_audit_regressions as audit
    case = audit.AuditRegressions()
    app = case.app(audit.round_trip(reviewed_project))
    case.phase(app, "phase2_3")
    app.number_input(key="_w_pore_gradient_emw_pcf").set_value(72.).run()
    case.phase(app, "phase4")
    assert app.session_state["pore_gradient_emw_pcf"] == 72.
    assert app.session_state["well_data"]["pore_gradient_emw_pcf"] == 72.
    case.phase(app, "phase2_3")
    app.number_input(key="_w_frac_gradient_emw_pcf").set_value(150.).run()
    mode = next(w for w in app.selectbox if w.label == "Chart Capacity Excess Mode")
    mode.set_value("apply").run()
    case.phase(app, "phase5")
    assert app.session_state["placement_config"]["chart_excess_mode"] == "apply"
    restored = case.app(audit.round_trip(app.session_state.to_dict()))
    case.phase(restored, "phase2_3")
    assert restored.number_input(key="_w_pore_gradient_emw_pcf").value == 72.
    assert restored.number_input(key="_w_frac_gradient_emw_pcf").value == 150.
    assert next(w for w in restored.selectbox if w.label == "Chart Capacity Excess Mode").value == "apply"
    case.healthy(restored)


def test_fresh_mode_is_explicitly_unselected():
    import test_audit_regressions as audit
    case = audit.AuditRegressions()
    app = case.app()
    case.phase(app, "phase2_3")
    assert next(w for w in app.selectbox if w.label == "Chart Capacity Excess Mode").value is None
    assert app.number_input(key="_w_pore_gradient_emw_pcf").value is None
    assert app.number_input(key="_w_frac_gradient_emw_pcf").value is None
