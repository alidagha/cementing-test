"""Round 9E Dynamic circulation consumes certified 9A–9D and Bingham sources."""
from copy import deepcopy
import hashlib
import math
import pickle
from pathlib import Path

import pandas as pd
import pytest

import centralizer_adapter as adapter
import centralizer_optimizer_engine as engine
import engineering_tools as tools
import materials_db
import rheology
from test_uat_round9c_fluid_snapshot import fluid_state, capacities
from test_uat_round9d_static_solver import zones_for, forbidden


DIALS = (168., 116., 64., 41., 24., 8., 6.)
AUX = ("Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind")


@pytest.fixture(scope="module")
def catalog():
    return adapter.load_official_catalog()


def readings(dials=DIALS):
    return dict(zip(map(str, rheology.RPM_ORDER), dials))


def dynamic_state(kind="casing", **fluids):
    if not fluids:
        fluids = {"Displacement Fluid": 200., "Tail": 100., "Spacer": 50.}
    state = fluid_state(kind, **fluids)
    state.update(plastic_viscosity="15-17", yield_point="8-12", effective_pv=999., effective_yp=999.)
    for row in state["fluids_config"]["params"].values():
        row.update(pump_rate="4-6", min_rate=999.)
    state["lab_qc_params"] = {name: {"rheology": {"bhct_down": {
        "selected": True, "readings": readings(), "gel_10_sec": "", "gel_10_min": ""}}}
        for name in fluids if name in materials_db.RHEOLOGY_LAB_FLUIDS}
    return state


def auxiliary():
    return {name: readings() for name in AUX}


def prepare(state, zones, catalog, **kwargs):
    assert callable(getattr(adapter, "build_dynamic_payload", None)), "Round 9E Dynamic payload is absent"
    return adapter.build_dynamic_payload(state, zones, catalog, **kwargs)


def solve(state, zones, catalog, *, mode="direct", **kwargs):
    assert callable(getattr(adapter, "solve_dynamic", None)), "Round 9E Dynamic solver is absent"
    return adapter.solve_dynamic(state, zones, catalog, mode=mode, **kwargs)


def test_frozen_engine_identity():
    assert hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest() == (
        "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9")


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_real_dynamic_execution_matches_engine_and_is_finite(catalog, kind, mode):
    state, zones = dynamic_state(kind), zones_for(catalog, kind)
    prepared = prepare(state, zones, catalog, aux_rheology=auxiliary())
    wd = prepared["payload"]
    official = engine.compute_standoff_profile(wd) if mode == "direct" else engine.optimize_placement(wd)
    result = solve(state, zones, catalog, mode=mode, aux_rheology=auxiliary())
    assert result["profile"] == official and result["mode"] == mode
    assert result["diagnostics"] == prepared["diagnostics"]
    assert result["profile"]["centralizer_md"]
    for field in ("tension_force", "normal_force", "stdf_at", "between_stdf"):
        assert all(math.isfinite(x) for x in result["profile"][field])
    assert wd["settings"] == {"calculation_mode": "dynamic_circulating", "include_hydrostatic": True}
    assert result["diagnostics"]["pump_rate_bpm"] == 4.
    assert result["diagnostics"]["pump_rate_m3_s"] == 4. * .00264979
    engine.validate_well_data(wd)


def test_circulation_uses_raw_sources_exact_units_and_annulus_boundaries(catalog):
    state = dynamic_state(**{"Displacement Fluid": 100., "Main": 80., "Tail": 90.,
                             "Scavenger": 30., "Pre Flush": 20., "Spacer": 20., "Spacer Ahead": 20.})
    snapshot = adapter.build_fluid_snapshot(state)
    prepared = prepare(state, zones_for(catalog), catalog, aux_rheology=auxiliary())
    wd, diagnostic = prepared["payload"], prepared["diagnostics"]
    assert {k: v for k, v in wd["fluids"].items() if k != "circulation"} == snapshot["fluids"]
    circulation = wd["fluids"]["circulation"]
    assert circulation["default_mud_pv_pa_s"] == 16. * .001
    assert circulation["default_mud_ty_pa"] == 10. * .4788026
    mud = diagnostic["rheology"]["Displacement Fluid"]
    assert mud == {"source": "phase_ii_mud", "pv_cp": 16., "ty_lbf_100ft2": 10., "iod": None}
    fit = rheology.calculate_cemcade_bingham(zip(rheology.RPM_ORDER, DIALS))
    for fluid in state["fluids_config"]["active"]:
        if fluid == "Displacement Fluid":
            continue
        row = diagnostic["rheology"][fluid]
        assert {key: row[key] for key in ("pv_cp", "ty_lbf_100ft2", "iod")} == {
            key: fit[key] for key in ("pv_cp", "ty_lbf_100ft2", "iod")}
        assert row["source"] == ("lab_bhct_down" if fluid in materials_db.RHEOLOGY_LAB_FLUIDS else "aux_rheology")
    annulus = [r for r in snapshot["annulus_intervals"] if r["fluid"] not in ("Mud", "Displacement Fluid")]
    assert circulation["stages_rheology"] == [{"name": r["fluid"], "top_md": r["top_md"],
        "bottom_md": r["bottom_md"], "pv_pa_s": fit["pv_cp"] * .001,
        "ty_pa": fit["ty_lbf_100ft2"] * .4788026} for r in annulus]
    assert diagnostic["stages_rheology"] == circulation["stages_rheology"]


@pytest.mark.parametrize("override", [{}, {"inside_fluids": []},
    {"inside_fluids": [[0., 1300.]], "annulus_fluids": [[0., 1500.]]}])
def test_dynamic_tier2_blocks_before_snapshot_fit_or_solver(catalog, override, monkeypatch):
    monkeypatch.setattr(adapter, "build_fluid_snapshot", forbidden)
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", forbidden)
    for name in ("compute_standoff_profile", "optimize_placement", "run_full_analysis"):
        monkeypatch.setattr(engine, name, forbidden)
    with pytest.raises(ValueError, match="Tier-2"):
        solve(dynamic_state(), zones_for(catalog), catalog, override=override)


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_static_behavior_is_unchanged_and_requires_no_dynamic_inputs(catalog, kind, mode, monkeypatch):
    state, zones = fluid_state(kind), zones_for(catalog, kind)
    override = {"inside_fluids": [[0., 1300.]], "annulus_fluids": [[0., 1500.]]}
    wd = adapter.build_static_payload(state, zones, catalog, override=override)
    official = engine.compute_standoff_profile(wd) if mode == "direct" else engine.optimize_placement(wd)
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", forbidden)
    result = adapter.solve_static(state, zones, catalog, mode=mode, override=override)
    assert set(result) == {"mode", "zones", "profile"}
    assert result["profile"] == official
    assert result["zones"][0]["density_design"] == zones[0]["density"]
    assert result["zones"][0]["product_nr"] == zones[0]["product_nr"]
    assert wd["settings"] == {"calculation_mode": "static", "include_hydrostatic": True}


@pytest.mark.parametrize("fluid", materials_db.RHEOLOGY_LAB_FLUIDS)
def test_every_active_lab_fluid_requires_selected_bhct_down_even_inside(catalog, fluid):
    state = dynamic_state(**{"Displacement Fluid": 1., fluid: 1.})
    snapshot = adapter.build_fluid_snapshot(state)
    assert any(r["fluid"] == fluid for r in snapshot["inside_intervals"])
    assert all(r["fluid"] == "Mud" for r in snapshot["annulus_intervals"])
    state["lab_qc_params"][fluid]["rheology"]["bhct_down"]["selected"] = False
    with pytest.raises(ValueError, match="MissingRheology"):
        solve(state, zones_for(catalog), catalog)


@pytest.mark.parametrize("fluid", AUX)
def test_active_auxiliary_including_excluded_spacer_behind_requires_readings(catalog, fluid):
    state = dynamic_state(**{"Displacement Fluid": 1., fluid: 1.})
    with pytest.raises(ValueError, match="MissingRheology"):
        solve(state, zones_for(catalog), catalog)
    prepared = prepare(state, zones_for(catalog), catalog, aux_rheology={fluid: readings()})
    assert prepared["diagnostics"]["rheology"][fluid]["source"] == "aux_rheology"
    if fluid == "Spacer Behind":
        assert prepared["payload"]["fluids"]["circulation"]["stages_rheology"] == []


@pytest.mark.parametrize("bad", [None, "", "0", "-1", "NaN", "inf", True])
@pytest.mark.parametrize("field", ["plastic_viscosity", "yield_point", "pump_rate"])
def test_invalid_dynamic_raw_inputs_block_before_solver(catalog, bad, field, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    state = dynamic_state(**{"Displacement Fluid": 100.})
    if field == "pump_rate":
        state["fluids_config"]["params"]["Displacement Fluid"][field] = bad
    else:
        state[field] = bad
    if field == "yield_point" and bad == "0":
        assert prepare(state, zones_for(catalog), catalog)["payload"]["fluids"]["circulation"]["default_mud_ty_pa"] == 0.
    else:
        with pytest.raises(ValueError):
            solve(state, zones_for(catalog), catalog)


def test_displacement_fluid_is_mandatory(catalog, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    with pytest.raises(ValueError, match="Displacement Fluid.*active"):
        solve(dynamic_state(Tail=100.), zones_for(catalog), catalog)


@pytest.mark.parametrize("raw,expected", [("3.5-5.0", 3.5), ("5-3.5", 3.5), ("۴-۶", 4.),
    ("+4.25", 4.25), (6., 6.), (".25-.5", .25)])
def test_raw_rate_calls_shared_parser_and_ignores_all_min_rate_caches(catalog, raw, expected, monkeypatch):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state["fluids_config"]["params"]["Displacement Fluid"].update(pump_rate=raw, min_rate=-123.)
    state["fluid_data"] = {"Displacement Fluid": {"pump_rate": "99-100", "min_rate": float("nan")}}
    calls = []
    def rate(value):
        calls.append(value)
        return tools.require_positive_pump_rate(value)
    monkeypatch.setattr(adapter, "require_positive_pump_rate", rate)
    result = prepare(state, zones_for(catalog), catalog)
    assert calls == [raw]
    assert result["diagnostics"]["pump_rate_bpm"] == expected
    assert result["diagnostics"]["pump_rate_m3_s"] == expected * .00264979


def test_displacement_row_config_first_precedence_and_fallback(catalog):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state["fluid_data"] = {"Displacement Fluid": {"volume": 123., "density": "999",
                                                   "pump_rate": "2-3", "min_rate": -999.}}
    assert prepare(state, zones_for(catalog), catalog)["diagnostics"]["pump_rate_bpm"] == 4.
    state["fluids_config"]["params"].pop("Displacement Fluid")
    assert prepare(state, zones_for(catalog), catalog)["diagnostics"]["pump_rate_bpm"] == 2.
    state["fluids_config"]["params"]["Displacement Fluid"] = {"volume": 100.}
    with pytest.raises(ValueError, match="pump rate"):
        prepare(state, zones_for(catalog), catalog)


@pytest.mark.parametrize("raw", ["4/6", "4 bpm", "0-4", "4-0", "-4", "4-x", "1e3", [], {}, False])
def test_malformed_or_nonpositive_rate_has_no_cached_fallback(catalog, raw):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state["fluids_config"]["params"]["Displacement Fluid"].update(pump_rate=raw, min_rate=4.)
    with pytest.raises(ValueError, match="pump rate"):
        prepare(state, zones_for(catalog), catalog)


def test_positive_rate_that_underflows_si_is_blocked(catalog):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state["fluids_config"]["params"]["Displacement Fluid"]["pump_rate"] = "0." + "0" * 322 + "1"
    with pytest.raises(ValueError, match="positive after SI"):
        prepare(state, zones_for(catalog), catalog)


@pytest.mark.parametrize("pv,yp,expected_pv,expected_ty", [("12/16", "0", 14., 0.),
    ("۱۲-۱۶", "۸-۱۲", 14., 10.), (12.3456789012345, 6.9876543210123, 12.3456789012345, 6.9876543210123)])
def test_raw_mud_calls_shared_parser_and_exact_unrounded_units(catalog, pv, yp, expected_pv, expected_ty, monkeypatch):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state.update(plastic_viscosity=pv, yield_point=yp, effective_pv=float("nan"), effective_yp=-999.)
    state["well_data"] = {"plastic_viscosity": "999", "yield_point": "999", "effective_pv": -999.}
    calls = []
    def parse(raw, default=0.):
        calls.append(raw)
        return tools.parse_effective_numeric(raw, default=default)
    monkeypatch.setattr(adapter, "parse_effective_numeric", parse)
    result = prepare(state, zones_for(catalog), catalog)
    assert calls == [pv, yp]
    circulation = result["payload"]["fluids"]["circulation"]
    assert circulation["default_mud_pv_pa_s"] == expected_pv * .001
    assert circulation["default_mud_ty_pa"] == expected_ty * .4788026
    assert result["diagnostics"]["rheology"]["Displacement Fluid"]["iod"] is None


def test_nested_raw_well_fields_and_explicit_empty_flat_authority(catalog):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state.pop("plastic_viscosity"); state.pop("yield_point")
    state["well_data"] = {"plastic_viscosity": "12-16", "yield_point": "0", "effective_pv": 999.}
    assert prepare(state, zones_for(catalog), catalog)["diagnostics"]["rheology"]["Displacement Fluid"]["pv_cp"] == 14.
    state["plastic_viscosity"] = ""
    with pytest.raises(ValueError, match="Mud PV"):
        prepare(state, zones_for(catalog), catalog)


@pytest.mark.parametrize("field", ["plastic_viscosity", "yield_point"])
@pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf"), "-2-4"])
def test_nonfinite_or_negative_raw_mud_never_uses_effective_cache(catalog, field, raw):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state[field] = raw
    with pytest.raises(ValueError):
        prepare(state, zones_for(catalog), catalog)


@pytest.mark.parametrize("source", ["lab", "aux"])
@pytest.mark.parametrize("bad", [None, "", " ", "-", 0, -1, True, float("nan"), float("inf"),
                                 "NaN", "inf", "8-12", [], 1e300])
def test_every_reading_must_be_positive_finite_and_resolvable(catalog, source, bad, monkeypatch):
    fluid = "Tail" if source == "lab" else "Spacer"
    state = dynamic_state(**{"Displacement Fluid": 100., fluid: 100.})
    auxiliary_inputs = {"Spacer": readings()}
    inputs = (state["lab_qc_params"]["Tail"]["rheology"]["bhct_down"]["readings"]
              if source == "lab" else auxiliary_inputs["Spacer"])
    inputs["6"] = bad
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    with pytest.raises(ValueError, match="MissingRheology"):
        solve(state, zones_for(catalog), catalog, aux_rheology=auxiliary_inputs)


@pytest.mark.parametrize("source", ["lab", "aux"])
@pytest.mark.parametrize("change", ["missing", "extra", "integer_keys", "not_dict"])
def test_exact_fixed_rpm_key_set_required(catalog, source, change):
    fluid = "Tail" if source == "lab" else "Spacer"
    state = dynamic_state(**{"Displacement Fluid": 100., fluid: 100.})
    values = readings()
    if change == "missing": values.pop("3")
    elif change == "extra": values["gel_10_sec"] = "-"
    elif change == "integer_keys": values = dict(zip(rheology.RPM_ORDER, DIALS))
    else: values = list(DIALS)
    aux = {"Spacer": values}
    if source == "lab": state["lab_qc_params"]["Tail"]["rheology"]["bhct_down"]["readings"] = values
    with pytest.raises(ValueError, match="MissingRheology"):
        prepare(state, zones_for(catalog), catalog, aux_rheology=aux)


@pytest.mark.parametrize("change", ["missing_lab", "bad_lab", "missing_fluid", "bad_qc", "missing_rheology",
    "bad_rheology", "missing_down", "bad_down", "no_selection", "false_selection", "numeric_selection"])
def test_incomplete_or_malformed_lab_source_never_falls_back(catalog, change):
    state = dynamic_state(**{"Displacement Fluid": 100., "Tail": 100.})
    lab = state["lab_qc_params"]
    qc = lab["Tail"]
    qc["rheology"].update(surface_down=deepcopy(qc["rheology"]["bhct_down"]),
                           bhct_up=deepcopy(qc["rheology"]["bhct_down"]))
    state["lab_payload_Tail"] = {"rheology": {"bhct_down": {"pv_cp": 100., "ty_lbf_100ft2": 10., "is_valid_bingham": True}}}
    if change == "missing_lab": state.pop("lab_qc_params")
    elif change == "bad_lab": state["lab_qc_params"] = []
    elif change == "missing_fluid": lab.pop("Tail")
    elif change == "bad_qc": lab["Tail"] = None
    elif change == "missing_rheology": qc.pop("rheology")
    elif change == "bad_rheology": qc["rheology"] = []
    elif change == "missing_down": qc["rheology"].pop("bhct_down")
    elif change == "bad_down": qc["rheology"]["bhct_down"] = None
    elif change == "no_selection": qc["rheology"]["bhct_down"].pop("selected")
    elif change == "false_selection": qc["rheology"]["bhct_down"]["selected"] = False
    else: qc["rheology"]["bhct_down"]["selected"] = 1
    with pytest.raises(ValueError, match="MissingRheology"):
        prepare(state, zones_for(catalog), catalog)


@pytest.mark.parametrize("source", ["lab", "aux"])
def test_actual_ty_zero_fit_is_invalid_for_dynamic(catalog, source):
    values = readings((150., 100., 50., 30., 15., 2., 1.))
    assert rheology.calculate_cemcade_bingham([(rpm, values[str(rpm)]) for rpm in rheology.RPM_ORDER])["is_valid_bingham"] is False
    fluid = "Tail" if source == "lab" else "Spacer"
    state = dynamic_state(**{"Displacement Fluid": 100., fluid: 100.})
    if source == "lab": state["lab_qc_params"]["Tail"]["rheology"]["bhct_down"]["readings"] = values
    with pytest.raises(ValueError, match="MissingRheology"):
        prepare(state, zones_for(catalog), catalog, aux_rheology={"Spacer": values})


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_all_active_fann_fits_use_authority_in_rpm_order_and_ignore_gels(catalog, kind, monkeypatch):
    # Diesel dynamic-consumer integration is deferred; retain the certified train.
    program = {name: 1. for name in materials_db.HYDRAULIC_EXECUTION_ORDER if name != "Diesel"}
    state, aux = dynamic_state(kind, **program), auxiliary()
    expected = []
    for i, fluid in enumerate(name for name in program if name != "Displacement Fluid"):
        values = {str(rpm): str(dial * (1. + i / 10.)) for rpm, dial in zip(rheology.RPM_ORDER, DIALS)}
        values = dict(reversed(list(values.items())))  # Input dict order is not RPM order.
        if fluid in materials_db.RHEOLOGY_LAB_FLUIDS:
            row = state["lab_qc_params"][fluid]["rheology"]["bhct_down"]
            row.update(readings=values, gel_10_sec={"not_consumed": True}, gel_10_min=None)
            row.update(pv_cp=-999., ty_lbf_100ft2=-999., iod=-999., is_valid_bingham=False)
        else:
            aux[fluid] = values
        expected.append((fluid, [(rpm, float(values[str(rpm)])) for rpm in rheology.RPM_ORDER]))
    calls, fits = [], []
    real = rheology.calculate_cemcade_bingham
    def fit(points):
        points = list(points)
        calls.append(points)
        result = real(points)
        fits.append(deepcopy(result))
        return result
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", fit)
    monkeypatch.setattr(rheology, "build_rheology", forbidden)  # Would impose Lab Gel completion.
    prepared = prepare(state, zones_for(catalog, kind), catalog, aux_rheology=aux)
    assert calls == [points for _, points in expected]
    assert len(calls) == len(materials_db.RHEOLOGY_LAB_FLUIDS) + len(AUX)
    for (fluid, _), raw in zip(expected, fits):
        diagnostic = prepared["diagnostics"]["rheology"][fluid]
        assert {field: diagnostic[field] for field in ("pv_cp", "ty_lbf_100ft2", "iod")} == {
            field: raw[field] for field in ("pv_cp", "ty_lbf_100ft2", "iod")}
    assert set(prepared["diagnostics"]["rheology"]) == set(program)
    assert prepared["payload"]["fluids"]["circulation"]["stages_rheology"] == []  # All stages fit inside.


@pytest.mark.parametrize("fluid", materials_db.RHEOLOGY_LAB_FLUIDS)
def test_fully_returned_active_lab_fluid_still_requires_rheology(catalog, fluid):
    state = dynamic_state(**{"Displacement Fluid": 1e6, fluid: 1.})
    snapshot = adapter.build_fluid_snapshot(state)
    assert snapshot["per_fluid"][fluid]["in_path_bbl"] == 0.
    assert snapshot["per_fluid"][fluid]["returned_bbl"] == 1.
    state["lab_qc_params"].pop(fluid)
    with pytest.raises(ValueError, match="MissingRheology"):
        prepare(state, zones_for(catalog), catalog)


def test_inactive_fluid_rheology_is_never_required_or_consumed(catalog, monkeypatch):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    state["lab_qc_params"] = {fluid: {"rheology": "invalid inactive draft"}
                              for fluid in materials_db.RHEOLOGY_LAB_FLUIDS}
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", forbidden)
    prepared = prepare(state, zones_for(catalog), catalog, aux_rheology={name: None for name in AUX})
    assert set(prepared["diagnostics"]["rheology"]) == {"Displacement Fluid"}
    assert prepared["payload"]["fluids"]["circulation"]["stages_rheology"] == []


def test_excluded_spacer_behind_changes_no_snapshot_or_stage_but_requires_a_fit(catalog):
    state = dynamic_state(**{"Displacement Fluid": 100., "Tail": 150., "Spacer Behind": 1.})
    before = prepare(state, zones_for(catalog), catalog, aux_rheology={"Spacer Behind": readings()})
    state["fluids_config"]["params"]["Spacer Behind"] = {"volume": float("nan"), "density": "invalid", "pump_rate": "invalid"}
    after = prepare(state, zones_for(catalog), catalog, aux_rheology={"Spacer Behind": readings()})
    assert after == before
    assert all(s["name"] != "Spacer Behind" for s in after["diagnostics"]["stages_rheology"])
    with pytest.raises(ValueError, match="MissingRheology"):
        prepare(state, zones_for(catalog), catalog, aux_rheology={"Spacer Behind": {}})


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_same_density_names_keep_independent_fits_and_exact_annulus_interfaces(catalog, kind, monkeypatch):
    state = dynamic_state(kind)
    inside, annulus = capacities(state)
    state = dynamic_state(kind, **{"Displacement Fluid": inside / 2., "Tail": inside * .75,
                                  "Lead": annulus * .1, "Spacer": annulus * .1})
    for name, row in state["fluids_config"]["params"].items():
        row["density"] = "100"
    lead = readings(tuple(d * 1.3 for d in DIALS))
    state["lab_qc_params"]["Lead"]["rheology"]["bhct_down"]["readings"] = lead
    aux = {"Spacer": readings(tuple(d * 1.6 for d in DIALS))}
    snapshot = adapter.build_fluid_snapshot(state)
    assert any(r["fluid"] == "Tail" for r in snapshot["inside_intervals"])
    assert any(r["fluid"] == "Tail" for r in snapshot["annulus_intervals"])
    # Deliberately unusable inside diagnostics prove annular-stage ownership.
    snapshot["inside_intervals"] = [{"fluid": "not_a_real_stage", "top_md": -99., "bottom_md": 99999.}]
    monkeypatch.setattr(adapter, "build_fluid_snapshot", lambda state, **kwargs: snapshot)
    prepared = prepare(state, zones_for(catalog, kind), catalog, aux_rheology=aux)
    stages = prepared["diagnostics"]["stages_rheology"]
    actual = [r for r in snapshot["annulus_intervals"] if r["fluid"] not in ("Mud", "Displacement Fluid")]
    assert [(s["name"], s["top_md"], s["bottom_md"]) for s in stages] == [
        (r["fluid"], r["top_md"], r["bottom_md"]) for r in actual]
    assert {s["name"] for s in stages} == {"Tail", "Lead", "Spacer"}
    assert len({s["pv_pa_s"] for s in stages}) == 3
    for row in stages:
        fit = prepared["diagnostics"]["rheology"][row["name"]]
        assert row["pv_pa_s"] == fit["pv_cp"] * .001
        assert row["ty_pa"] == fit["ty_lbf_100ft2"] * .4788026


@pytest.mark.parametrize("displacement_fraction", [.5, 1., 1.5, 100.])
def test_mud_and_displacement_never_create_redundant_stages(catalog, displacement_fraction):
    state = dynamic_state(**{"Displacement Fluid": 100.})
    inside, _ = capacities(state)
    state["fluids_config"]["params"]["Displacement Fluid"]["volume"] = inside * displacement_fraction
    prepared = prepare(state, zones_for(catalog), catalog)
    assert prepared["payload"]["fluids"]["circulation"]["stages_rheology"] == []
    assert prepared["diagnostics"]["rheology"]["Displacement Fluid"]["iod"] is None


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_solver_routing_uses_only_chosen_entry_point(catalog, monkeypatch, mode):
    compute, optimize = engine.compute_standoff_profile, engine.optimize_placement
    calls = []
    def direct(wd, **kwargs):
        # compute calls made internally by the frozen optimizer are legitimate.
        calls.append(("compute", wd["settings"]["calculation_mode"]))
        return compute(wd, **kwargs)
    def optimizer(wd):
        calls.append(("optimize", wd["settings"]["calculation_mode"]))
        return optimize(wd)
    monkeypatch.setattr(engine, "compute_standoff_profile", direct)
    monkeypatch.setattr(engine, "optimize_placement", optimizer if mode == "optimize" else forbidden)
    monkeypatch.setattr(engine, "run_full_analysis", forbidden)
    result = solve(dynamic_state(), zones_for(catalog), catalog, mode=mode, aux_rheology=auxiliary())
    assert result["profile"]["centralizer_md"]
    if mode == "direct":
        assert calls == [("compute", "dynamic_circulating")]
        assert result["zones"][0]["density_computed"] == "1/3"
    else:
        assert calls[0] == ("optimize", "dynamic_circulating")
        assert sum(name == "optimize" for name, _ in calls) == 1
        assert all(physics == "dynamic_circulating" for _, physics in calls)


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_low_standoff_remains_successful_in_dynamic(catalog, mode):
    state = dynamic_state()
    state["well_geometry"] = {"version": 1, "type": "Directional", "survey": pd.DataFrame(
        {"MD": [0., 1200.], "Deviation": [60., 60.], "Azimuth": [0., 0.]})}
    result = solve(state, zones_for(catalog, target=100.), catalog, mode=mode, aux_rheology=auxiliary())
    assert result["profile"]["centralizer_md"] and result["diagnostics"]["pump_rate_m3_s"] > 0.
    assert result["zones"][0]["min_stdf"] < 1.
    assert result["zones"][0]["meets_target"] is False


def test_dynamic_positive_q_produces_circulating_coupling_not_static_result(catalog):
    state, zones = dynamic_state(), zones_for(catalog)
    static = adapter.solve_static(state, zones, catalog, mode="direct")
    dynamic = solve(state, zones, catalog, aux_rheology=auxiliary())
    assert dynamic["profile"]["tension_force"] != static["profile"]["tension_force"]
    assert dynamic["profile"]["centralizer_md"] == static["profile"]["centralizer_md"]


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_state_zones_products_aux_snapshot_and_engine_result_remain_unmutated(catalog, kind, mode, monkeypatch):
    state, zones, products, aux = dynamic_state(kind), zones_for(catalog, kind), deepcopy(catalog), auxiliary()
    inside, annulus = capacities(state)
    for fluid, volume in (("Displacement Fluid", inside), ("Tail", annulus / 4.), ("Spacer", annulus / 4.)):
        state["fluids_config"]["params"][fluid]["volume"] = volume
    snapshot = adapter.build_fluid_snapshot(state)
    prepared = prepare(state, zones, products, aux_rheology=aux)
    profile = (engine.compute_standoff_profile(prepared["payload"]) if mode == "direct"
               else engine.optimize_placement(prepared["payload"]))
    before = pickle.dumps((state, zones, products, aux, snapshot, profile))
    monkeypatch.setattr(adapter, "build_fluid_snapshot", lambda state, **kwargs: snapshot)
    monkeypatch.setattr(engine, "compute_standoff_profile", lambda wd: profile)
    monkeypatch.setattr(engine, "optimize_placement", lambda wd: profile)
    result = solve(state, zones, products, mode=mode, aux_rheology=aux)
    assert result["profile"] is profile
    assert pickle.dumps((state, zones, products, aux, snapshot, profile)) == before
    prepared = prepare(state, zones, products, aux_rheology=aux)
    stage = prepared["payload"]["fluids"]["circulation"]["stages_rheology"][0]
    original_stage = deepcopy(prepared["diagnostics"]["stages_rheology"][0])
    stage["pv_pa_s"] = -999.
    assert prepared["diagnostics"]["stages_rheology"][0] == original_stage
    prepared["diagnostics"]["rheology"]["Displacement Fluid"]["pv_cp"] = -999.
    assert pickle.dumps((state, zones, products, aux, snapshot, profile)) == before


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_dynamic_execution_has_no_file_network_session_or_autoload_side_effects(catalog, monkeypatch, mode):
    import builtins
    import socket
    import streamlit as st
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(adapter, "load_official_catalog", forbidden)
    monkeypatch.setattr(engine, "run_full_analysis", forbidden)
    class NoSession:
        def __getattr__(self, name): forbidden()
        def __getitem__(self, key): forbidden()
        def __setitem__(self, key, value): forbidden()
    monkeypatch.setattr(st, "session_state", NoSession())
    result = solve(dynamic_state(), zones_for(catalog), catalog, mode=mode, aux_rheology=auxiliary())
    assert result["profile"]["centralizer_md"]


@pytest.mark.parametrize("mode", [None, "", True, "dynamic", "direct_check", "static"])
def test_invalid_placement_mode_blocks_before_solver(catalog, mode, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    monkeypatch.setattr(engine, "optimize_placement", forbidden)
    with pytest.raises(ValueError, match="placement mode"):
        solve(dynamic_state(), zones_for(catalog), catalog, mode=mode, aux_rheology=auxiliary())


@pytest.mark.parametrize("job", ["CMT PLUG", "CMT SQUEEZE"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_not_applicable_jobs_require_no_dynamic_input_and_never_execute(catalog, job, mode, monkeypatch):
    for name in ("compute_standoff_profile", "optimize_placement", "run_full_analysis"):
        monkeypatch.setattr(engine, name, forbidden)
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", forbidden)
    assert prepare({"job_type": job}, [], catalog) is None
    assert solve({"job_type": job}, [], catalog, mode=mode) is None


@pytest.mark.parametrize("field,value", [("target_standoff_pct", 0), ("target_standoff_pct", 101.),
    ("product_nr", None), ("top_md", -1.), ("bottom_md", 1001.), ("density", "1/5")])
def test_dynamic_cannot_bypass_round9d_zone_product_validation(catalog, field, value, monkeypatch):
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", forbidden)
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    zones = zones_for(catalog)
    zones[0][field] = value
    with pytest.raises(ValueError):
        solve(dynamic_state(), zones, catalog, aux_rheology=auxiliary())


@pytest.mark.parametrize("source", ["lab", "aux"])
def test_reported_invalid_bingham_fit_is_never_accepted_from_positive_readings(catalog, source, monkeypatch):
    fluid = "Tail" if source == "lab" else "Spacer"
    state = dynamic_state(**{"Displacement Fluid": 100., fluid: 100.})
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", lambda points: {
        "is_valid_bingham": False, "pv_cp": 100., "ty_lbf_100ft2": 10., "iod": .99})
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    with pytest.raises(ValueError, match="MissingRheology"):
        solve(state, zones_for(catalog), catalog, aux_rheology={"Spacer": readings()})


@pytest.mark.parametrize("source", ["lab", "aux"])
def test_validity_flag_cannot_hide_a_nonfinite_fit_diagnostic(catalog, source, monkeypatch):
    fluid = "Tail" if source == "lab" else "Spacer"
    state = dynamic_state(**{"Displacement Fluid": 100., fluid: 100.})
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", lambda points: {
        "is_valid_bingham": True, "pv_cp": 100., "ty_lbf_100ft2": 10., "iod": float("nan")})
    with pytest.raises(ValueError, match="MissingRheology"):
        prepare(state, zones_for(catalog), catalog, aux_rheology={"Spacer": readings()})


def test_auxiliary_fann_inputs_cannot_replace_canonical_lab_rheology(catalog):
    state = dynamic_state(**{"Displacement Fluid": 100., "Tail": 100.})
    state["lab_qc_params"] = {}
    with pytest.raises(ValueError, match="MissingRheology"):
        prepare(state, zones_for(catalog), catalog, aux_rheology={"Tail": readings()})
