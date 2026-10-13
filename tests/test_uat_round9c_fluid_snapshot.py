"""Round 9C continuous displacement, distinct from Round 8 final placement."""
from copy import deepcopy
import math

import pandas as pd
import pytest

import centralizer_adapter as adapter
import cement_chart_model as model
from test_uat_round9b_geometry import state_for, hardware


ORDER = ("Displacement Fluid", "Tail", "Lead #2", "Lead #1", "Lead", "Main",
         "Scavenger", "Spacer", "Spacer Ahead", "Pre Flush")


def fluid_state(kind="casing", **fluids):
    state = state_for(kind)
    state["mud_density"] = "80-82"
    state["fluids_config"] = {"active": list(fluids), "params": {
        name: {"volume": volume, "density": str(90 + index * 5)}
        for index, (name, volume) in enumerate(fluids.items())}}
    return state


def capacities(state):
    geometry = model.resolve_chart_geometry(state)
    inside = math.fsum((s["bottom_md"] - s["top_md"]) * model._capacity(s["id_in"])
                       for s in geometry["active_string"])
    annulus = model.interval_volume(geometry["capacity_segments"], 0., geometry["shoe_md"])
    return inside, annulus


def snapshot(state, **kwargs):
    assert callable(getattr(adapter, "build_fluid_snapshot", None)), "Round 9C snapshot is absent"
    return adapter.build_fluid_snapshot(state, **kwargs)


def assert_conserved(result, shoe=1000.):
    assert result["diagnostics_available"] is True
    for column in ("inside", "annulus"):
        rows = result[f"{column}_intervals"]
        assert rows[0]["top_md"] == 0. and rows[-1]["bottom_md"] == shoe
        assert all(r["top_md"] < r["bottom_md"] for r in rows)
        assert all(a["bottom_md"] == b["top_md"] for a, b in zip(rows, rows[1:]))
        assert result["fluids"][f"{column}_fluids"] == [
            [r["top_md"], r["density_pcf"] * model.PCF_TO_KG_M3] for r in rows]
    for row in result["per_fluid"].values():
        assert row["entered_bbl"] == pytest.approx(row["in_path_bbl"] + row["returned_bbl"], rel=1e-12)
        assert row["in_path_bbl"] >= 0 and row["returned_bbl"] >= 0
    occupied = math.fsum(r["in_path_bbl"] for col in ("inside", "annulus")
                         for r in result[f"{col}_intervals"])
    assert occupied == pytest.approx(result["capacity_bbl"]["total"], rel=1e-12)
    totals = result["totals"]
    assert totals["entered_bbl"] == pytest.approx(totals["in_path_bbl"] + totals["returned_bbl"], rel=1e-12)


def test_simple_casing_exact_capacity_and_initial_mud():
    state = fluid_state()
    result = snapshot(state)
    inside, annulus = capacities(state)
    assert result["capacity_bbl"] == {"inside": inside, "annulus": annulus, "total": math.fsum((inside, annulus))}
    assert result["fluids"]["mud_density"] == 81. * model.PCF_TO_KG_M3
    assert result["per_fluid"] == {}
    assert result["totals"] == {"entered_bbl": 0., "in_path_bbl": 0., "returned_bbl": 0.}
    assert all(r["fluid"] == "Mud" for col in ("inside", "annulus") for r in result[f"{col}_intervals"])
    assert_conserved(result)


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_exact_displacement_locks_shoe_to_surface_owner_order(kind):
    state = fluid_state(kind)
    inside, annulus = capacities(state)
    state["fluids_config"] = {"active": list(reversed(ORDER)), "params": {
        name: {"volume": inside if name == "Displacement Fluid" else annulus / 20., "density": str(90 + index)}
        for index, name in enumerate(ORDER)}}
    result = snapshot(state)
    assert [r["fluid"] for r in result["inside_intervals"]] == ["Displacement Fluid"]
    assert [r["fluid"] for r in reversed(result["annulus_intervals"])] == list(ORDER[1:]) + ["Mud"]
    assert all(r["returned_bbl"] == 0. for r in result["per_fluid"].values())
    assert_conserved(result)


@pytest.mark.parametrize("displacement_fraction", [.75, 1.25])
def test_under_and_over_displacement_allow_a_fluid_to_straddle_shoe(displacement_fraction):
    state = fluid_state()
    inside, annulus = capacities(state)
    state = fluid_state(**{"Displacement Fluid": inside * displacement_fraction, "Tail": inside / 2.})
    result = snapshot(state)
    crossing = "Tail" if displacement_fraction < 1 else "Displacement Fluid"
    assert any(r["fluid"] == crossing for r in result["inside_intervals"])
    assert any(r["fluid"] == crossing for r in result["annulus_intervals"])
    assert_conserved(result)


def test_liner_internal_flow_includes_drill_pipes_and_does_not_invent_interfaces():
    state = fluid_state("liner", Main=1.)
    inside, annulus = capacities(state)
    assert inside == math.fsum((400. * model._capacity(4.), 600. * model._capacity(6.)))
    state["fluids_config"]["params"]["Main"]["volume"] = inside * .9
    result = snapshot(state)
    rows = [r for r in result["inside_intervals"] if r["fluid"] == "Main"]
    assert len(rows) == 1 and rows[0]["top_md"] == 0. and rows[0]["bottom_md"] > 400.
    assert result["capacity_bbl"]["inside"] == inside
    assert_conserved(result)


def test_equal_densities_do_not_erase_real_fluid_identity_boundary():
    state = fluid_state(Main=20., Tail=20.)
    for row in state["fluids_config"]["params"].values():
        row["density"] = "118"
    result = snapshot(state)
    assert [r["fluid"] for r in result["inside_intervals"]] == ["Tail", "Main", "Mud"]
    assert len(result["fluids"]["inside_fluids"]) == 3
    assert_conserved(result)


@pytest.mark.parametrize("kind,overflow_kind", [("casing", "surface_dump"), ("liner", "overlap_excess"),
                                               ("tieback", "overlap_excess")])
def test_excess_is_returned_per_fluid_without_capacity_block_or_density_averaging(kind, overflow_kind):
    state = fluid_state(kind, Tail=1., Main=1.)
    inside, annulus = capacities(state)
    state["fluids_config"]["params"]["Tail"]["volume"] = inside + annulus / 2.
    state["fluids_config"]["params"]["Main"]["volume"] = 1e8
    result = snapshot(state)
    assert result["overflow_kind"] == overflow_kind
    assert result["per_fluid"]["Main"]["returned_bbl"] == pytest.approx(1e8 - annulus / 2.)
    first_tables = deepcopy(result["fluids"])
    state["fluids_config"]["params"]["Main"]["volume"] *= 2.
    assert snapshot(state)["fluids"] == first_tables
    assert_conserved(result)


@pytest.mark.parametrize("subset", [("Main",), ("Lead #1", "Tail"), ("Spacer", "Spacer Ahead"),
                                    ("Pre Flush", "Scavenger", "Lead #2", "Displacement Fluid")])
def test_subsets_use_locked_order_and_ignore_spacer_behind_and_inactive_data(subset):
    state = fluid_state(**{name: 10. for name in subset})
    state["fluids_config"]["params"]["Inactive"] = {"volume": float("nan"), "density": None}
    baseline = snapshot(state)
    assert [r["fluid"] for r in baseline["inside_intervals"] if r["fluid"] != "Mud"] == [n for n in ORDER if n in subset]
    state["fluids_config"]["active"].append("Spacer Behind")
    state["fluids_config"]["params"]["Spacer Behind"] = {"volume": float("nan"), "density": None}
    assert snapshot(state) == baseline
    assert_conserved(baseline)


def test_density_range_source_precedence_and_displacement_mud_authority():
    state = fluid_state(**{"Main": 10., "Displacement Fluid": 10.})
    state["fluids_config"]["params"]["Main"]["density"] = "100-120"
    state["fluids_config"]["params"]["Displacement Fluid"]["density"] = "junk"
    state["fluid_data"] = {"Main": {"volume": 999., "density": "150"}}
    result = snapshot(state)
    assert [r["density_pcf"] for r in result["inside_intervals"]] == [81., 110., 81.]
    assert result["per_fluid"]["Main"]["entered_bbl"] == 10.
    del state["fluids_config"]["params"]["Main"]
    assert snapshot(state)["per_fluid"]["Main"]["entered_bbl"] == 999.


@pytest.mark.parametrize("column", ["inside_fluids", "annulus_fluids"])
@pytest.mark.parametrize("table", [None, "junk", [[0.]], [[0., 1000., 2.]], [[True, 1000.]],
    [[0., True]], [[float("nan"), 1000.]], [[0., float("inf")]], [[0., 0.]], [[0., -1.]],
    [[-1., 1000.]], [[1001., 1000.]], [[0., 1000.], [0., 1200.]]])
def test_tier2_malformed_pairs_are_controlled(column, table):
    override = {"inside_fluids": [[0., 1000.]], "annulus_fluids": [[0., 1000.]], column: table}
    with pytest.raises(ValueError):
        snapshot(fluid_state(), override=override)


@pytest.mark.parametrize("override", [{}, {"inside_fluids": []}, {"annulus_fluids": []}])
def test_tier2_partial_override_blocks(override):
    with pytest.raises(ValueError, match="both|Both"):
        snapshot(fluid_state(), override=override)


def test_tier2_forwards_value_type_and_order_identically_and_marks_diagnostics_unavailable():
    state = fluid_state()
    state["fluids_config"] = "invalid Tier-1 must not be read"
    state["fluid_data"] = None
    override = {"inside_fluids": [(700, 1234.56789), (0, 900), (1000, 1300)],
                "annulus_fluids": ((500, 1000), (0, 1100))}
    original = deepcopy(override)
    result = snapshot(state, override=override)
    assert result["fluids"] == {"mud_density": 81. * model.PCF_TO_KG_M3, **override}
    assert type(result["fluids"]["annulus_fluids"]) is tuple
    assert result["diagnostics_available"] is False
    for field in ("inside_intervals", "annulus_intervals", "per_fluid", "capacity_bbl", "totals", "original_mud", "overflow_kind"):
        assert result[field] is None
    assert override == original
    result["fluids"]["inside_fluids"].append((123, 456))
    assert override == original


def test_tier2_empty_columns_use_engine_mud_default_without_fake_accounting():
    result = snapshot(fluid_state(), override={"inside_fluids": [], "annulus_fluids": []})
    assert result["fluids"] == {"mud_density": 81. * model.PCF_TO_KG_M3,
                                "inside_fluids": [], "annulus_fluids": []}
    assert result["per_fluid"] is None and result["diagnostics_available"] is False


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1., 0., True, "junk"])
@pytest.mark.parametrize("name", ["Main", "Displacement Fluid"])
def test_active_volume_must_be_numeric_positive_finite(name, value):
    state = fluid_state(**{name: 10.})
    state["fluids_config"]["params"][name]["volume"] = value
    with pytest.raises(ValueError, match="volume"):
        snapshot(state)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1., 0., True, "100-0", "junk"])
def test_active_non_displacement_density_must_be_valid(value):
    state = fluid_state(Main=10.)
    state["fluids_config"]["params"]["Main"]["density"] = value
    with pytest.raises(ValueError, match="density"):
        snapshot(state)


@pytest.mark.parametrize("override", [None, {"inside_fluids": [], "annulus_fluids": []}])
@pytest.mark.parametrize("value", [None, float("inf"), 0., -1., True, "junk"])
def test_both_tiers_require_real_phaseii_mud_without_density_fallback(override, value):
    state = fluid_state(**{"Displacement Fluid": 20.})
    state["mud_density"] = value
    state["fluids_config"]["params"]["Displacement Fluid"]["density"] = "99"
    with pytest.raises(ValueError, match="density"):
        snapshot(state, override=override)


def test_nested_well_mud_and_density_conversion_use_current_authorities():
    state = fluid_state(Main=10.)
    del state["mud_density"]
    state["well_data"] = {"mud_density": "۸۰-۸۲"}
    result = snapshot(state)
    assert result["fluids"]["mud_density"] == 81. * (.45359237 / .3048 ** 3)
    assert result["fluids"]["inside_fluids"][0][1] == 90. * model.PCF_TO_KG_M3


@pytest.mark.parametrize("record", [None, [], "junk"])
def test_malformed_selected_source_does_not_fallback_to_stale_fluid_data(record):
    state = fluid_state(Main=10.)
    state["fluids_config"]["params"]["Main"] = record
    state["fluid_data"] = {"Main": {"volume": 100., "density": "118"}}
    with pytest.raises(ValueError, match="Phase IV Main"):
        snapshot(state)


@pytest.mark.parametrize("override", [True, [], "junk", {"inside_fluids": [], "annulus_fluids": [], "extra": []}])
def test_malformed_override_container_is_controlled(override):
    with pytest.raises(ValueError):
        snapshot(fluid_state(), override=override)


@pytest.mark.parametrize("active", [None, "Main", ["Main", "Main"], [True], ["Future Fluid"]])
def test_malformed_active_selection_does_not_silently_drop_volume(active):
    state = fluid_state(Main=10.)
    state["fluids_config"]["active"] = active
    with pytest.raises(ValueError):
        snapshot(state)


def test_apply_excess_consumes_existing_segment_specific_capacity_once():
    state = fluid_state(Main=10.)
    nominal = snapshot(state)["capacity_bbl"]
    state["placement_config"].update(chart_excess_mode="apply", excess_csg_csg_pct=20., excess_csg_oh_pct=100.)
    result = snapshot(state)
    geometry = model.resolve_chart_geometry(state)
    assert result["capacity_bbl"]["inside"] == nominal["inside"]
    assert result["capacity_bbl"]["annulus"] == model.interval_volume(geometry["capacity_segments"], 0., 1000.)
    assert result["capacity_bbl"]["annulus"] == pytest.approx(nominal["annulus"] * 1.6)
    assert_conserved(result)


def test_snapshot_has_no_shoe_track_volume_block_or_round8_placement_side_effect():
    state = fluid_state(Tail=.001)
    geometry = model.resolve_chart_geometry(state)
    assert state["fluids_config"]["params"]["Tail"]["volume"] < geometry["shoe_track_bbl"]
    with pytest.raises(ValueError, match="Shoe Track"):
        model.resolve_cement_placement(state)
    result = snapshot(state)
    assert result["per_fluid"]["Tail"]["in_path_bbl"] == .001
    with pytest.raises(ValueError, match="Shoe Track"):
        model.resolve_cement_placement(state)
    assert_conserved(result)


@pytest.mark.parametrize("directional", [False, True])
@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_pure_repeatable_snapshot_preserves_state_dataframes_and_uses_no_solver_io(kind, directional, monkeypatch):
    import builtins
    import socket
    import streamlit
    import centralizer_optimizer_engine as engine
    state = fluid_state(kind, Tail=20., Main=30., Spacer=10.)
    if directional:
        state["well_geometry"] = {"type": "Directional", "survey": pd.DataFrame(
            {"MD": [0., 700., 1200.], "Deviation": [0., 30., 40.], "Azimuth": [0., 350., 10.]})}
    original = deepcopy(state)
    def forbidden(*args, **kwargs):
        pytest.fail("Snapshot invoked an out-of-scope side effect or authority")
    for name in ("compute_standoff_profile", "optimize_placement", "run_full_analysis"):
        monkeypatch.setattr(engine, name, forbidden)
    monkeypatch.setattr(model, "resolve_cement_placement", forbidden)
    monkeypatch.setattr(model, "resolve_final_fluid_intervals", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(streamlit, "session_state", object())
    result = snapshot(state)
    assert snapshot(state) == result
    pd.testing.assert_frame_equal(state["hardware_table"], original.pop("hardware_table"))
    original_geometry = original.pop("well_geometry")
    if directional:
        pd.testing.assert_frame_equal(state["well_geometry"]["survey"], original_geometry.pop("survey"))
    assert {k: v for k, v in state["well_geometry"].items() if k != "survey"} == original_geometry
    assert {k: v for k, v in state.items() if k not in ("well_geometry", "hardware_table")} == original
    assert_conserved(result)


def test_locked_snapshot_order_does_not_depend_on_operational_hydraulic_order(monkeypatch):
    import materials_db
    original = tuple(materials_db.HYDRAULIC_EXECUTION_ORDER)
    state = fluid_state(**{name: 1. for name in reversed(ORDER)})
    baseline = snapshot(state)
    assert tuple(materials_db.HYDRAULIC_EXECUTION_ORDER) == original
    monkeypatch.setattr(materials_db, "HYDRAULIC_EXECUTION_ORDER", ())
    assert snapshot(state) == baseline


@pytest.mark.parametrize("job", ["CMT PLUG", "CMT SQUEEZE"])
def test_not_applicable_jobs_never_parse_fluids_or_calculate(job):
    assert snapshot({"job_type": job, "fluids_config": "invalid", "mud_density": "invalid"}) is None


def test_tier2_still_requires_valid_geometry():
    state = fluid_state()
    state["hardware_table"] = state["hardware_table"].iloc[:1]
    with pytest.raises(ValueError):
        snapshot(state, override={"inside_fluids": [], "annulus_fluids": []})


@pytest.mark.parametrize("scale", [1e-8, 1e-4, 1., 10., 1000., 1e8])
def test_multiple_small_and_large_stages_preserve_all_quantity_accounting(scale):
    state = fluid_state(**{name: scale * (index + 1) for index, name in enumerate(ORDER)})
    result = snapshot(state)
    assert_conserved(result)


@pytest.mark.parametrize("volume", [.001, 1e-4, 1e-8])
def test_small_real_stage_after_a_large_stage_is_not_lost_or_falsely_blocked(volume):
    state = fluid_state(Tail=100., Main=volume)
    result = snapshot(state)
    assert result["per_fluid"]["Main"]["in_path_bbl"] == volume
    assert any(r["fluid"] == "Main" and r["top_md"] < r["bottom_md"] for r in result["inside_intervals"])
    assert_conserved(result)


def test_interface_exactly_at_liner_hanger_remains_exact():
    state = fluid_state("liner", Tail=400. * model._capacity(4.), Main=20.)
    result = snapshot(state)
    assert result["inside_intervals"][0]["bottom_md"] == 400.
    assert result["inside_intervals"][1]["top_md"] == 400.
    assert_conserved(result)


def test_finite_capacity_or_volume_sum_overflow_fails_controlled():
    state = fluid_state(Tail=1.7e308, Main=1.7e308)
    with pytest.raises(ValueError, match="finite arithmetic"):
        snapshot(state)


def test_unrepresentable_positive_stage_fails_instead_of_disappearing():
    state = fluid_state(Tail=100., Main=5e-324)
    with pytest.raises(ValueError, match="precision"):
        snapshot(state)


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("fraction", [.1, .75, 1., 1.25, 2.])
def test_named_md_intervals_reproduce_actual_piecewise_capacity(kind, fraction):
    state = fluid_state(kind)
    inside, annulus = capacities(state)
    state = fluid_state(kind, **{"Displacement Fluid": inside * fraction,
                                "Tail": annulus / 3., "Main": annulus / 4.})
    geometry = model.resolve_chart_geometry(state)
    columns = {"inside": [{**s, "bbl_per_m": model._capacity(s["id_in"])} for s in geometry["active_string"]],
               "annulus": geometry["capacity_segments"]}
    result = snapshot(state)
    for column, segments in columns.items():
        for row in result[f"{column}_intervals"]:
            physical_volume = model.interval_volume(segments, row["top_md"], row["bottom_md"])
            assert physical_volume == pytest.approx(row["in_path_bbl"], rel=1e-12, abs=1e-12)
    assert_conserved(result)
