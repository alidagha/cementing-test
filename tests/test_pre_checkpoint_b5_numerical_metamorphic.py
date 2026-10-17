"""B5: relationships derived from existing formulas, not new engineering rules.

Each test names its authority/invariant. Float32 fitting is compared to its own
fresh fit; display precision is never reused as source or a conservation basis.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import engineering_tools as eng
import materials_db as db
import phase_5_cement as phase5
import phase_7_lab as phase7
import phase_9_centralizer as phase9
import project_state as ps
import rheology
import placement
import cement_chart_model as chart
import centralizer_adapter as centralizer
import pumping_simulation as pumping
import well_schematic_adapter as schematic
import test_audit_regressions as audit
from centralizer_fixtures import execute_centralizer
from test_uat_round8a_chart_model import balanced_state
from test_uat_round9e_dynamic_solver import readings
from test_uat_round10a_pumping_simulation import program_state
from test_uat_round10c_integration import save_project, restore_project
from test_pre_checkpoint_b2_cross_module_integration import (
    projects as integrated_projects, context, sources, select_target, assert_shared_geometry,
)


CASE = audit.AuditRegressions()


def additives(specs):
    rows = []
    for name, dose, density in specs:
        canonical, kind, physical = db.resolve_known_material(name)
        rows.append({"Name": canonical, "Material Type": kind, "Physical State": physical,
                     "Mix Method": "Dry Blend", "User Input": dose, "Density": density})
    return phase5._normalize_additive_rows(pd.DataFrame(rows))


FORMULATIONS = {
    "neat": [],
    "powder": [("Micro Silica", 2., None)],
    "liquid": [("Micro Block", .5, None)],
    "Sodium catalog": [("Sodium Silicate", .5, None)],
    "Sodium measured": [("Sodium Silicate", .5, 1.47)],
    "salt": [("SALT", 18., None)],
    "mixed": [("Micro Silica", 2., None), ("Sodium Silicate", .5, 1.47), ("SALT", 18., None)],
}


def calculate(table, volume=50., density=118.):
    powders, liquids, salt = phase5.build_components(table)
    return eng.calculate_slurry_from_components(density, volume, cmt_sg=3.2,
                                                powders=powders, liquids=liquids, salt_pct=salt)


def finite(value):
    if isinstance(value, dict):
        for item in value.values(): finite(item)
    elif isinstance(value, (list, tuple, np.ndarray)):
        for item in value: finite(item)
    elif isinstance(value, (int, float, np.number)):
        assert math.isfinite(value)


@pytest.mark.parametrize("formulation", FORMULATIONS)
@pytest.mark.parametrize("density", [118., 152.])
def test_unrounded_mass_absolute_volume_and_field_lab_scale(formulation, density):
    """Universal per-sack balance + field volume scaling; D044 salt volume."""
    table = additives(FORMULATIONS[formulation])
    powders, liquids, salt = phase5.build_components(table)
    before = ps.fingerprint(table)
    results = [calculate(table, volume, density) for volume in (25., 50., 100.)]
    for result, volume in zip(results, (25., 50., 100.)):
        finite(result)
        powder_mass = sum(p["percent"] * 110 / 100 for p in powders)
        powder_volume = sum(p["percent"] * 110 / 100 / p["density_pcf"] for p in powders)
        liquid_mass = sum(l["gal_per_sk"] * l["density_ppg"] for l in liquids)
        liquid_volume = sum(l["gal_per_sk"] for l in liquids) / eng.GAL_PER_CUFT
        water = result["water_vol_per_sack"]
        salt_mass = water * eng.WATER_DENSITY_PCF * salt / 100
        salt_volume = salt_mass * eng.dissolved_nacl_gal_per_lb(salt) / eng.GAL_PER_CUFT
        absolute_volume = 110 / (3.2 * eng.WATER_DENSITY_PCF) + powder_volume + liquid_volume + water + salt_volume
        mass = 110 + powder_mass + liquid_mass + water * eng.WATER_DENSITY_PCF + salt_mass
        assert water >= 0
        assert result["yield_ft3_per_sk"] == pytest.approx(absolute_volume, rel=1e-12)
        assert mass / absolute_volume == pytest.approx(density, rel=1e-12)
        assert result["field_sacks"] * absolute_volume == pytest.approx(volume * eng.BBL_TO_CUFT, rel=1e-12)
        assert result["ma_additives"] == pytest.approx(powder_mass + liquid_mass, rel=1e-12)
        assert result["va_additives"] == pytest.approx(powder_volume + liquid_volume, rel=1e-12)
        assert result["lab_cmt_gr"] * result["yield_ft3_per_sk"] == pytest.approx(1058., rel=1e-12)
        for source, field, lab in zip(liquids, result["field_liquids"], result["lab_liquids"]):
            assert field["field_gal"] == pytest.approx(source["gal_per_sk"] * result["field_sacks"], rel=1e-12)
            assert lab["lab_gr"] == pytest.approx(result["lab_cmt_gr"] * source["gal_per_sk"] * source["density_ppg"] / 110, rel=1e-12)
    for field in ("field_sacks", "field_water_bbl", "field_solution_bbl", "salt_field_lb"):
        assert results[2][field] == pytest.approx(2 * results[1][field], rel=1e-12)
        assert results[0][field] == pytest.approx(.5 * results[1][field], rel=1e-12)
    for field in ("yield_ft3_per_sk", "water_vol_per_sack", "lab_cmt_gr", "lab_water_gr", "lab_liquids", "lab_powders"):
        assert results[0][field] == results[1][field] == results[2][field]
    assert ps.fingerprint(table) == before


@pytest.mark.parametrize("density", [1.47, 1.50])
def test_liquid_table_dosage_sack_scaling_dead_allowance_and_source_independence(density):
    """Existing manual field basis: dosage*sacks; allowance*(1+dead/mix)."""
    table = additives([("Sodium Silicate", .50, density)])
    result = calculate(table)
    for factor in (.5, 1., 2.):
        for dead in (0., 5., 10.):
            params = {"auto_calc": False, "total_sacks": 100. * factor, "mix_water": 25.,
                      "dead_vol": dead, "tank_name": "Batch Mixer Tanks"}
            before = ps.fingerprint((params, table, result))
            blend, adds, _ = phase5.build_cement_tables(params, table, result)
            row = adds.iloc[0]
            assert float(row["lbs or gal"].split()[0]) == .5 * 100 * factor
            assert float(row["lbs or gal (with dead Vol.)"].split()[0]) == pytest.approx(.5 * 100 * factor * (25 + dead) / 25)
            assert float(row["(lbs or gal)/bbl"].split()[0]) == 2 * factor
            assert "Sodium Silicate" not in blend["Name"].tolist()
            assert ps.fingerprint((params, table, result)) == before


@pytest.mark.parametrize("representation", [150, 150., "150", "150.0"])
def test_only_accepted_scalar_representations_are_equivalent(representation):
    assert eng.require_positive_density(representation) == 150.
    assert eng.require_positive_pump_rate(representation) == 150.
    assert eng.calculate_slurry_from_components(representation, 50.) == eng.calculate_slurry_from_components(150., 50.)
    # Chart's numeric schema intentionally excludes strings; do not widen it.
    if isinstance(representation, str):
        with pytest.raises(ValueError): chart._number(representation, "source")
    else:
        assert chart._number(representation, "source") == 150.
        assert ps.fingerprint(representation) == ps.fingerprint(150.)


@pytest.mark.parametrize("representation", [.5, "0.5", "0.50", "۰٫۵"])
def test_additive_accepted_numeric_representations_reach_same_engine_and_lab(representation):
    table = additives([("Sodium Silicate", .5, 1.47)])
    # Phase V's normalizer uses pandas numeric text; Persian digits belong to
    # the shared scalar parser, so exercise that authority before normalization.
    table.at[0, "User Input"] = eng.require_nonnegative_number(representation)
    expected = additives([("Sodium Silicate", .5, 1.47)])
    assert calculate(table) == calculate(expected)
    assert phase7.build_lab_df_from_phase5(table, cmt_sg=3.2, recalculate_mass=True).equals(
        phase7.build_lab_df_from_phase5(expected, cmt_sg=3.2, recalculate_mass=True))


@pytest.mark.parametrize("value,valid", [(-.001, False), (0., False), (.001, True)])
def test_positive_density_and_pump_rate_exact_zero_boundary(value, valid):
    for validator in (eng.require_positive_density, eng.require_positive_pump_rate):
        if valid: assert validator(value) == value
        else:
            with pytest.raises(ValueError): validator(value)


@pytest.mark.parametrize("density,valid", [(74.999, False), (75., True), (75.001, True),
                                         (179.999, True), (180., True), (180.001, False)])
def test_existing_slurry_density_admission_endpoints(density, valid):
    if valid: finite(eng.calculate_slurry_from_components(density, 1.))
    else:
        with pytest.raises(ValueError): eng.calculate_slurry_from_components(density, 1.)


@pytest.mark.parametrize("salt,valid", [(0., True), (1.999999, False), (2., True), (2.000001, True),
                                      (37.199999, True), (37.2, True), (37.200001, False)])
def test_d044_admission_and_node_neighborhoods(salt, valid):
    if valid:
        finite(eng.calculate_slurry_from_components(118., 1., salt_pct=salt))
    else:
        with pytest.raises(ValueError): eng.dissolved_nacl_gal_per_lb(salt)


@pytest.mark.parametrize("precision", [1, 2, 3])
@pytest.mark.parametrize("sign", [1, -1])
def test_half_up_neighbors_are_decimal_and_never_mutate_source(precision, sign):
    quantum = Decimal(1).scaleb(-precision)
    for offset in (Decimal(".49"), Decimal(".50"), Decimal(".51")):
        source = sign * (Decimal("12") + offset * quantum)
        expected = float(source.quantize(quantum, rounding=ROUND_HALF_UP))
        assert eng.round_half_up(str(source), precision) == expected


@pytest.mark.parametrize("density,valid", [(50.999999, False), (51., True), (51.000001, True),
                                         (53.999999, True), (54., True), (54.000001, False)])
def test_diesel_density_endpoints_and_no_range_mean(density, valid):
    if valid: assert eng.require_diesel_density(density) == density
    else:
        with pytest.raises(ValueError): eng.require_diesel_density(density)
    with pytest.raises(ValueError): eng.require_diesel_density("51-54")


@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_rheology_minimum_and_additional_points_are_fresh_and_finite(count):
    points = list(zip(rheology.RPM_ORDER, (168, 116, 64, 41, 24, 8, 6)))[:count]
    if count == 3:
        # The exactly collinear triple hits the existing convergence limit;
        # use a nearby convergent measured triple for the admitted-fit control.
        points[-1] = (100, 64.01)
    if count < 2:
        with pytest.raises(ValueError): rheology.calculate_cemcade_bingham(points)
    else:
        fit = rheology.calculate_cemcade_bingham(points)
        finite(fit)
        assert fit["pv_cp"] > 0 and fit["valid_point_count"] == count
        assert fit == rheology.calculate_cemcade_bingham([(str(r), str(d)) for r, d in points])
        assert fit == rheology.calculate_cemcade_bingham(points)


def test_collinear_fit_limit_is_controlled_and_never_uses_a_previous_fit():
    """Positive point count alone does not promise nonlinear convergence."""
    qc = {"rheology": {"bhct_down": {"selected": True,
        "readings": {"300": "168", "200": "116", "100": "64"},
        "gel_10_sec": "-", "gel_10_min": "10"}}}
    result, issues = rheology.build_rheology(qc)
    assert issues and "converge" in result["bhct_down"]["validation_message"]
    assert result["bhct_down"]["is_valid_bingham"] is False
    assert result["bhct_down"]["pv_cp"] is None
    assert result["bhct_down"]["ty_lbf_100ft2"] is None


@pytest.mark.parametrize("dose,valid", [(-.001, False), (0., True), (.001, True)])
def test_additive_dosage_keeps_existing_nonnegative_boundary(dose, valid):
    table = additives([("Sodium Silicate", dose, 1.47)])
    if valid:
        result = calculate(table)
        assert result["ma_additives"] == dose * 1.47 * eng.WATER_LB_PER_GAL
    else:
        with pytest.raises(ValueError): phase5.build_components(table)


def test_equal_rheology_readings_either_resolve_or_are_controlled_without_stale_fit():
    qc = {"rheology": {"bhct_down": {"selected": True, "readings": readings((10.,) * 7),
                                      "gel_10_sec": "-", "gel_10_min": "10"}}}
    result, issues = rheology.build_rheology(qc)
    if issues:
        assert result["bhct_down"]["is_valid_bingham"] is False
    else:
        finite(result)
        assert result["bhct_down"]["pv_cp"] > 0


@pytest.mark.parametrize("boundary", ["pore", "frac"])
@pytest.mark.parametrize("delta", [-1e-5, 0., 1e-5])
def test_formation_exact_contact_and_meaningful_neighbors(boundary, delta):
    """Same production TVD-linear authority at domain endpoints and interior."""
    state = balanced_state()
    hydro = chart.build_chart_model(state)["hydrostatic"]
    domain = chart.current_open_hole_domain(state)
    # Preserve every slope break when offsetting this piecewise-linear curve.
    depths = sorted({domain["top_md"], (domain["top_md"] + domain["bottom_md"]) / 2,
                     domain["bottom_md"], *(md for md in hydro["md_m"]
                                            if domain["top_md"] < md < domain["bottom_md"])})
    rows = []
    for depth in depths:
        h = chart._linear_pressure(hydro["tvd_m"], hydro["pressure_psi"], depth)
        rows.append({"md_m": depth, "pore_psi": h + delta if boundary == "pore" else h - 100.,
                     "frac_psi": h + delta if boundary == "frac" else h + 100.})
    state["formation_pressure_config"] = {"mode": "advanced", "profile": rows}
    model = chart.build_chart_model(state)
    security = model["static_security"]
    expected_warning = delta > 0 if boundary == "pore" else delta < 0
    assert (security["status"] == "warning") == expected_warning
    if expected_warning:
        assert security[boundary + "_violations"]
        assert max(row["max_delta_psi"] for row in security[boundary + "_violations"]) == pytest.approx(abs(delta), abs=1e-9)
    elif delta == 0:
        assert security["crossings"]
    assert chart.build_chart_model(audit.round_trip(state))["static_security"] == security


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_chart_capacity_placement_direction_and_conservation_within_one_regime(kind):
    state = program_state(kind, fluids={"Main": 50., "Displacement Fluid": 10.})
    # These fixtures have one active-string section and sufficient cement.
    geometry = chart.resolve_chart_geometry(state)
    track = geometry["shoe_track_bbl"]
    cap = geometry["capacity_segments"][-1]["bbl_per_m"]
    bottom = geometry["shoe_md"]
    state["fluids_config"]["params"]["Main"]["volume"] = track + 20. * cap
    baseline = chart.resolve_cement_placement(state)[0]
    for extra in (-.001, 0., .001):
        state["fluids_config"]["params"]["Main"]["volume"] = track + (20. + extra) * cap
        row = chart.resolve_cement_placement(state)[0]
        assert row["top_md"] == pytest.approx(bottom - 20. - extra, abs=1e-9)
        assert row["in_well_bbl"] + row["shoe_track_bbl"] + row["returned_bbl"] == pytest.approx(row["entered_bbl"], rel=1e-12)
    state["fluids_config"]["params"]["Main"]["volume"] = baseline["entered_bbl"]
    frame = state["hardware_table"]
    description = "Previous Casing" if kind == "tieback" else "Open Hole Size"
    field = "ID (in)" if kind == "tieback" else "Size (in)"
    frame[field] = frame[field].astype(object)
    mask = frame.Description == description
    old = float(frame.loc[mask, field].iloc[0])
    frame.loc[mask, field] = old + .001
    changed = chart.resolve_chart_geometry(state)
    assert changed["capacity_segments"][-1]["bbl_per_m"] > cap
    assert chart.resolve_cement_placement(state)[0]["top_md"] > baseline["top_md"]


@pytest.mark.parametrize("offset", [-1e-7, 0., 1e-7])
def test_shoe_track_and_full_return_conserve_at_capacity_boundaries(offset):
    state = balanced_state()
    geometry = chart.resolve_chart_geometry(state)
    track = geometry["shoe_track_bbl"]
    state["fluids_config"]["params"]["Main"]["volume"] = track + offset
    if offset < 0:
        with pytest.raises(ValueError, match="Shoe Track"): chart.resolve_cement_placement(state)
    else:
        row = chart.resolve_cement_placement(state)[0]
        assert row["shoe_track_bbl"] == track
        assert row["in_well_bbl"] == pytest.approx(offset, abs=1e-12)
    annulus = chart.interval_volume(geometry["capacity_segments"], 0., geometry["shoe_md"])
    state["fluids_config"]["params"]["Main"]["volume"] = track + annulus + offset
    final = chart.resolve_final_fluid_intervals(state, geometry)
    row = final["cement_placement"][0]
    assert row["returned_bbl"] == pytest.approx(max(0., offset), abs=1e-11)
    assert math.fsum(r["in_well_bbl"] for r in final["annular_intervals"]) == pytest.approx(annulus, rel=1e-12)


def small_program(kind="casing", diesel=False):
    state = program_state(kind, fluids={"Main": 2., "Displacement Fluid": 2.})
    if diesel:
        state["mud_type"] = "OBM"
        state["fluids_config"]["active"].insert(0, "Diesel")
        state["fluids_config"]["params"]["Diesel"] = {"volume": 1., "density": "51", "pump_rate": "4", "material_name": "Diesel"}
        state["lab_qc_params"]["Diesel"] = deepcopy(state["lab_qc_params"]["Main"])
    return state


@pytest.mark.parametrize("kind,diesel", [("casing", False), ("liner", False), ("tieback", False), ("casing", True)])
def test_real_frozen_pumping_is_finite_repeatable_and_stage_conservative(kind, diesel):
    state = small_program(kind, diesel)
    source = ps.fingerprint(state)
    prepared = pumping.prepare_pumping_simulation(state)
    previous = None
    for _ in range(2):
        result = pumping.run_pumping_simulation(state)
        try:
            arrays = {key: value for key, value in vars(result["result"]).items() if isinstance(value, np.ndarray)}
            assert arrays
            finite(arrays)
            if previous is not None:
                for key in arrays: np.testing.assert_array_equal(arrays[key], previous[key])
            previous = deepcopy(arrays)
            train = prepared["inputs"]["fluid_data"]
            assert list(train) == [name for name in db.HYDRAULIC_EXECUTION_ORDER if name in train]
            assert math.fsum(row["volume"] for row in train.values()) == sum(
                row["volume"] for row in state["fluids_config"]["params"].values())
        finally:
            pumping.fcm.plt.close(result["figure"])
    assert ps.fingerprint(state) == source
    state["fluids_config"]["params"]["Main"]["volume"] += .001
    perturbed = pumping.run_pumping_simulation(state)
    try:
        finite({key: value for key, value in vars(perturbed["result"]).items() if isinstance(value, np.ndarray)})
    finally:
        pumping.fcm.plt.close(perturbed["figure"])


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_actual_geometry_representation_equivalence_and_shared_si_values(kind):
    state = program_state(kind)
    expected_chart = chart.resolve_chart_geometry(state)
    expected_centralizer = centralizer.to_engine_geometry(state)
    expected_pump = asdict(pumping.prepare_pumping_simulation(state)["inputs"]["geometry"])
    state["hardware_table"]["MD (m)"] = state["hardware_table"]["MD (m)"].map(
        lambda value: str(float(value)) if "-" not in str(value) else value)
    state["hardware_table"]["Size (in)"] = state["hardware_table"]["Size (in)"].map(eng.parse_fractional_size)
    # Row tokens deliberately include entered text. Explicitly reselect the same
    # physical target/host instead of requiring identity tokens to alias.
    select_target(state)
    if kind == "tieback":
        state["placement_config"]["host_row"] = next(iter(placement.hardware_choices(state["hardware_table"], {"Previous Casing"})))
    assert chart.resolve_chart_geometry(state) == expected_chart
    assert centralizer.to_engine_geometry(state) == expected_centralizer
    assert asdict(pumping.prepare_pumping_simulation(state)["inputs"]["geometry"]) == expected_pump


@pytest.mark.parametrize("gap", [-.0001, 0., .0001])
def test_annular_clearance_exact_boundary_follows_capacity_authority(gap):
    state = program_state()
    mask = state["hardware_table"].Description == "Open Hole Size"
    state["hardware_table"]["Size (in)"] = state["hardware_table"]["Size (in)"].astype(object)
    state["hardware_table"].loc[mask, "Size (in)"] = 9.625 + gap
    if gap <= 0:
        with pytest.raises(ValueError, match="exceed"): chart.resolve_chart_geometry(state)
    else:
        geometry = chart.resolve_chart_geometry(state)
        expected = math.pi / 4 * ((9.625 + gap)**2 - 9.625**2) / 144 / .3048 / eng.BBL_TO_CUFT
        assert geometry["capacity_segments"][-1]["bbl_per_m"] == expected > 0
        finite(centralizer.to_engine_geometry(state))


@pytest.mark.parametrize("gap", [-.0001, 0., .0001])
def test_centralizer_pipe_wall_requires_strictly_positive_clearance(gap):
    state = program_state()
    state["hardware_table"].loc[lambda frame: frame.Description == "Casing", "ID (in)"] = 9.625 - gap
    if gap <= 0:
        with pytest.raises(ValueError): centralizer.to_engine_geometry(state)
    else:
        value = centralizer.to_engine_geometry(state)
        assert value["casing"]["od"] > value["casing"]["id"] > 0


@pytest.mark.parametrize("edit", ["previous shoe", "liner hanger", "target depth"])
def test_small_depth_edits_change_capacity_by_area_times_changed_length(edit):
    """Piecewise cylindrical capacity; stay inside the same row-order regime."""
    state = program_state("liner" if edit == "liner hanger" else "casing")
    before = chart.resolve_chart_geometry(state)
    old_volume = chart.interval_volume(before["capacity_segments"], 0., before["shoe_md"])
    frame = state["hardware_table"]
    if edit == "previous shoe":
        frame.loc[frame.Description == "Previous Casing", "MD (m)"] = "500.001"
        expected_delta = .001 * (before["capacity_segments"][0]["bbl_per_m"] - before["capacity_segments"][-1]["bbl_per_m"])
    elif edit == "liner hanger":
        frame.loc[frame.Description.isin(["Liner Hanger", "Drill Pipes"]), "MD (m)"] = "400.001"
        expected_delta = .001 * (before["capacity_segments"][0]["bbl_per_m"] - before["capacity_segments"][1]["bbl_per_m"])
    else:
        frame.loc[frame.Description == "Casing", "MD (m)"] = "999.999"
        select_target(state)
        expected_delta = -.001 * before["capacity_segments"][-1]["bbl_per_m"]
    after = chart.resolve_chart_geometry(state)
    new_volume = chart.interval_volume(after["capacity_segments"], 0., after["shoe_md"])
    assert new_volume - old_volume == pytest.approx(expected_delta, abs=1e-11)
    translated = centralizer.to_engine_geometry(state)
    pump = pumping.prepare_pumping_simulation(state)["inputs"]["geometry"]
    assert translated["wellbore"]["string_shoe"] == pump.track_depth_m == after["shoe_md"]
    if edit == "previous shoe": assert translated["wellbore"]["prev_shoe_depth"] == 500.001
    if edit == "liner hanger":
        assert translated["wellbore"]["string_top"] == pump.pipe_sections[0].z_bot == 400.001


@pytest.fixture(scope="module")
def projects():
    return integrated_projects.__wrapped__()


def test_signed_zero_zone_representation_cannot_retire_identical_engineering_or_block_word(projects):
    """Nonnegative depth admits +/-zero; Python equality and engine input agree."""
    state = projects()
    assert phase9.result_is_current(state)
    assert state["centralizer_config"]["zones"][0]["top_md"] == 0.
    config = state["centralizer_config"]
    catalog = centralizer.load_official_catalog()
    before = centralizer.build_dynamic_payload(state, config["zones"], catalog,
                                               aux_rheology=config["aux_rheology"])
    before_context = context(state)
    config["zones"][0]["top_md"] = -0.0
    phase9.validate_config(config)
    after = centralizer.build_dynamic_payload(state, config["zones"], catalog,
                                              aux_rheology=config["aux_rheology"])
    assert after == before
    after_context = context(state)
    assert phase9.result_is_current(state), "Signed zero falsely retired an identical Centralizer design"
    assert after_context["fluids_train"] == before_context["fluids_train"]
    assert after_context["procedure_text"] == before_context["procedure_text"]


@pytest.mark.parametrize("container", ["scalar", "nested", "numpy scalar", "numpy array", "table"])
def test_fingerprint_zero_equivalence_is_recursive_without_rounding_nonzero_source(container):
    def wrap(value):
        if container == "nested": return {"depth": [value]}
        if container == "numpy scalar": return np.float64(value)
        if container == "numpy array": return np.array([value])
        if container == "table": return pd.DataFrame({"Top MD": [value]})
        return value
    assert ps.fingerprint(wrap(-0.0)) == ps.fingerprint(wrap(0.0))
    for value in (-1e-15, 1e-15):
        assert ps.fingerprint(wrap(value)) != ps.fingerprint(wrap(0.0))
    assert ps.fingerprint(False) != ps.fingerprint(0.)
    assert ps.fingerprint("0") != ps.fingerprint(0.)


@pytest.mark.parametrize("change", ["density", "volume", "rate", "reading", "surface", "gel"])
def test_diesel_independent_numerical_sources_and_centralizer_currentness(projects, change):
    state = projects()
    initial = deepcopy(state)
    before_static = chart.build_chart_model(state)
    before_rheo = pumping.prepare_pumping_simulation(state)["inputs"]["rheology"]["Diesel"]
    params = state["fluids_config"]["params"]["Diesel"]
    row = state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]
    if change == "density": params["density"] = "54"
    elif change == "volume": params["volume"] *= 2
    elif change == "rate": params["pump_rate"] = str(2 * eng.require_positive_pump_rate(params["pump_rate"]))
    elif change == "reading": row["readings"]["300"] = str(float(row["readings"]["300"]) + .01)
    elif change == "surface": state["lab_qc_params"]["Diesel"]["rheology"]["surface_down"] = deepcopy(row)
    else: row["gel_10_min"] = "14"
    prepared = pumping.prepare_pumping_simulation(state)["inputs"]
    ps.refresh_fluids(state)
    if change in ("rate", "reading", "surface", "gel"):
        assert chart.build_chart_model(state) == before_static
    if change in ("density", "volume", "rate", "surface"):
        assert prepared["rheology"]["Diesel"] == before_rheo
    if change == "reading":
        fit = rheology.calculate_cemcade_bingham([(rpm, row["readings"][str(rpm)]) for rpm in rheology.RPM_ORDER])
        assert fit != rheology.calculate_cemcade_bingham([(rpm, initial["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]["readings"][str(rpm)]) for rpm in rheology.RPM_ORDER])
    if change == "volume":
        assert state["fluid_data"]["Diesel"]["duration_min"] == 2 * initial["fluid_data"]["Diesel"]["duration_min"]
    if change == "rate":
        assert state["fluid_data"]["Diesel"]["duration_min"] == .5 * initial["fluid_data"]["Diesel"]["duration_min"]
    assert phase9.result_is_current(state) == (change in ("rate", "surface", "gel"))
    assert state["fluids_config"]["params"]["Pre Flush"] == initial["fluids_config"]["params"]["Pre Flush"]


@pytest.mark.parametrize("job,density", [('CSG 9 5/8"', 1.47), ('CSG 9 5/8"', 1.50),
                                       ('LNR 4 1/2"', None), ('TIE BACK LNR 5"', None),
                                       ('CSG 9 5/8"', "Advanced")])
def test_repeated_rebuild_and_two_real_roundtrips_preserve_numerical_meaning(projects, job, density):
    state = projects(job)
    if isinstance(density, float):
        state["cement_additives_dfs"]["Main"].at[0, "Density"] = density
    if density == "Advanced":
        domain = chart.current_open_hole_domain(state)
        state["formation_pressure_config"] = {"mode": "advanced", "profile": [
            {"md_m": domain["top_md"], "pore_psi": 1000., "frac_psi": 8000.},
            {"md_m": domain["bottom_md"], "pore_psi": 2000., "frac_psi": 15000.}]}
    state["fluids_config"]["params"]["Diesel"]["density"] = "51" if density == 1.47 else "54"
    # A source edit can require review; numerical rebuilds still must stabilize.
    ps.prepare_calculations(state)
    checkpoint = sources(state)
    expected = (chart.build_chart_model(state), schematic.prepare_schematic(state),
                asdict(pumping.prepare_pumping_simulation(state)["inputs"]["geometry"]),
                centralizer.build_fluid_snapshot(state))
    for _ in range(3):
        ps.prepare_calculations(state)
        assert sources(state) == checkpoint
        assert (chart.build_chart_model(state), schematic.prepare_schematic(state),
                asdict(pumping.prepare_pumping_simulation(state)["inputs"]["geometry"]),
                centralizer.build_fluid_snapshot(state)) == expected
    for _ in range(2):
        app = restore_project(save_project(SimpleNamespace(session_state=state)))
        state = app.session_state.to_dict()
        ps.prepare_calculations(state)
        assert sources(state) == checkpoint
        assert (chart.build_chart_model(state), schematic.prepare_schematic(state),
                asdict(pumping.prepare_pumping_simulation(state)["inputs"]["geometry"]),
                centralizer.build_fluid_snapshot(state)) == expected


@pytest.mark.parametrize("job", ['CSG 9 5/8"', 'LNR 4 1/2"', 'TIE BACK LNR 5"'])
def test_small_consumed_geometry_change_stales_real_centralizer_and_shared_word_facts(projects, job):
    state = projects(job)
    description = {"casing": "Casing", "liner": "Liner", "tieback": "Tie Back"}[chart.chart_job_kind(job)]
    frame = state["hardware_table"]
    frame.loc[frame.Description == description, "ID (in)"] -= .001
    assert not phase9.result_is_current(state)
    assert ps.prepare_calculations(state) == []
    execute_centralizer(state, physics="dynamic")
    assert phase9.result_is_current(state)
    finite(state["_centralizer_result"]["profile"])
    assert_shared_geometry(state, context(state))
