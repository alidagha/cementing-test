"""Round 9D explicit zones and frozen-engine Static execution only."""
import ast
import hashlib
import pickle
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest

import centralizer_adapter as adapter
import centralizer_optimizer_engine as engine
from test_uat_round9c_fluid_snapshot import fluid_state


ENGINE_SHA = "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9"
LADDER = ("1/4", "1/3", "1/2", "2/3", "3/4", "1/1", "4/3", "3/2", "2/1", "3/1", "4/1")


@pytest.fixture(scope="module")
def catalog():
    return adapter.load_official_catalog()


def zones_for(catalog, kind="casing", *, density="1/3", target=70.):
    pipe = 9.625 if kind == "casing" else 7.
    product = next(p for p in adapter.filter_official_products(catalog, pipe) if p["kind"] == "rigid")
    return [{"top_md": 400. if kind == "liner" else 0., "bottom_md": 1000.,
             "density": density, "target_standoff_pct": target, "product_nr": product["nr"]}]


def payload(state, zones, catalog, **kwargs):
    assert callable(getattr(adapter, "build_static_payload", None)), "Round 9D Static payload is absent"
    return adapter.build_static_payload(state, zones, catalog, **kwargs)


def solve(state, zones, catalog, *, mode="direct", **kwargs):
    assert callable(getattr(adapter, "solve_static", None)), "Round 9D Static solver adapter is absent"
    return adapter.solve_static(state, zones, catalog, mode=mode, **kwargs)


def forbidden(*args, **kwargs):
    pytest.fail("Forbidden solver/side effect was invoked")


def test_certified_engine_and_ladder_identity():
    assert hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest() == ENGINE_SHA
    assert tuple(f"{p}/{q}" for p, q in engine._DENSITY_LADDER) == LADDER


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_real_static_execution_and_exact_engine_diagnostics(catalog, kind, mode):
    state = fluid_state(kind, **{"Displacement Fluid": 200., "Tail": 150., "Spacer": 50.})
    zones = zones_for(catalog, kind)
    wd = payload(state, zones, catalog)
    official = (engine.compute_standoff_profile(wd) if mode == "direct" else engine.optimize_placement(wd))
    result = solve(state, zones, catalog, mode=mode)
    assert result["mode"] == mode
    assert result["profile"] == official
    assert result["profile"]["centralizer_md"]
    row = result["zones"][0]
    assert row["top_md"] == zones[0]["top_md"] and row["bottom_md"] == 1000.
    assert row["density_design"] == "1/3" and row["target"] == .7
    assert row["product_nr"] == zones[0]["product_nr"]
    assert row["product_name"] == wd["zones"][0]["product_name"] == wd["products"][0]["name"]
    assert row["product_kind"] == "rigid"
    if mode == "direct":
        assert row["density_computed"] == "1/3"
        assert row["min_stdf"] == official["zones_min"][0]["min_stdf"]
        assert row["min_depth"] == official["zones_min"][0]["min_depth"]
        assert row["meets_target"] == (row["min_stdf"] >= row["target"])
    else:
        raw = official["zones"][0]
        for field in ("density_computed", "count", "min_stdf", "meets_target"):
            assert row[field] == raw[field]
        assert row["min_depth"] is None  # The optimizer probe does not return its depth.
        assert Fraction(row["density_computed"]) >= Fraction(row["density_design"])


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_payload_reuses_geometry_snapshot_and_locks_static_settings(catalog, kind):
    state = fluid_state(kind, Tail=300.)
    wd = payload(state, zones_for(catalog, kind, target=100.), catalog)
    geometry = adapter.to_engine_geometry(state)
    assert {key: wd[key] for key in geometry} == geometry
    assert wd["fluids"] == adapter.build_fluid_snapshot(state)["fluids"]
    assert wd["settings"] == {"calculation_mode": "static", "include_hydrostatic": True}
    assert wd["zones"][0]["target_standoff"] == 1.
    assert "circulation" not in wd["fluids"]
    engine.validate_well_data(wd)


@pytest.mark.parametrize("percent", [.001, 33.3, 67., 99.99999, 100.])
def test_percent_is_converted_exactly_once_and_engine_target_never_exceeds_one(catalog, percent):
    wd = payload(fluid_state(), zones_for(catalog, target=percent), catalog)
    assert wd["zones"][0]["target_standoff"] == percent / 100.
    assert 0 < wd["zones"][0]["target_standoff"] <= 1.


def test_unrelated_state_cannot_override_static_settings_or_inject_dynamic_inputs(catalog):
    state = fluid_state()
    state.update(settings={"calculation_mode": "dynamic_circulating", "include_hydrostatic": False},
                 products=[{"name": "unselected"}], zones=[{"density": "invalid"}],
                 fluids={"circulation": {"pump_rate_m3_s": 100.}})
    wd = payload(state, zones_for(catalog), catalog)
    assert wd["settings"] == {"calculation_mode": "static", "include_hydrostatic": True}
    assert "circulation" not in wd["fluids"] and wd["products"][0]["name"].startswith("OFFICIAL-CENT-")


def test_direct_calls_only_compute_and_keeps_design_density(catalog, monkeypatch):
    real = engine.compute_standoff_profile
    calls = []
    def compute(wd):
        calls.append(deepcopy(wd))
        return real(wd)
    monkeypatch.setattr(engine, "compute_standoff_profile", compute)
    monkeypatch.setattr(engine, "optimize_placement", forbidden)
    monkeypatch.setattr(engine, "run_full_analysis", forbidden)
    result = solve(fluid_state(), zones_for(catalog, density="2/3"), catalog)
    assert len(calls) == 1 and calls[0]["zones"][0]["density"] == "2/3"
    assert result["zones"][0]["density_computed"] == "2/3"


def test_optimize_calls_engine_optimizer_and_its_certified_walk(catalog, monkeypatch):
    optimize, candidates = engine.optimize_placement, engine._density_candidates
    optimizer_calls, ladder_calls = [], []
    def optimizer(wd):
        optimizer_calls.append(deepcopy(wd))
        return optimize(wd)
    def walk(density):
        ladder_calls.append(density)
        return candidates(density)
    monkeypatch.setattr(engine, "optimize_placement", optimizer)
    monkeypatch.setattr(engine, "_density_candidates", walk)
    monkeypatch.setattr(engine, "run_full_analysis", forbidden)
    result = solve(fluid_state(), zones_for(catalog, density="3/4"), catalog, mode="optimize")
    assert len(optimizer_calls) == 1 and ladder_calls == ["3/4"]
    assert Fraction(result["zones"][0]["density_computed"]) >= Fraction("3/4")


@pytest.mark.parametrize("density", LADDER)
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_all_certified_design_densities_work_without_sparsifying(catalog, density, mode):
    result = solve(fluid_state(), zones_for(catalog, density=density), catalog, mode=mode)
    row = result["zones"][0]
    assert row["density_design"] == density
    assert Fraction(row["density_computed"]) >= Fraction(density)
    if mode == "direct":
        assert row["density_computed"] == density


INVALID_FIELDS = [
    ("target_standoff_pct", 0), ("target_standoff_pct", -1), ("target_standoff_pct", 100.1),
    ("target_standoff_pct", None), ("target_standoff_pct", True), ("target_standoff_pct", "70"),
    ("target_standoff_pct", float("nan")), ("target_standoff_pct", float("inf")),
    ("target_standoff_pct", 5e-324),
    ("top_md", True), ("top_md", None), ("top_md", "0"), ("top_md", -1),
    ("top_md", 1000), ("top_md", 1001), ("top_md", float("nan")),
    ("bottom_md", False), ("bottom_md", 0), ("bottom_md", -1), ("bottom_md", 1000.001),
    ("bottom_md", float("inf")), ("bottom_md", "1000"),
    ("density", None), ("density", True), ("density", 1), ("density", []),
    ("density", "1/5"), ("density", "2/2"), ("density", "0/1"), ("density", "1/0"),
    ("density", " 1/1"), ("density", "1/1/2"),
    ("product_nr", None), ("product_nr", True), ("product_nr", 911.),
    ("product_nr", "911"), ("product_nr", -99999),
]


@pytest.mark.parametrize("field,value", INVALID_FIELDS)
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_invalid_explicit_zone_blocks_before_any_solver(catalog, monkeypatch, field, value, mode):
    for name in ("compute_standoff_profile", "optimize_placement", "run_full_analysis"):
        monkeypatch.setattr(engine, name, forbidden)
    zones = zones_for(catalog)
    zones[0][field] = value
    with pytest.raises(ValueError):
        solve(fluid_state(), zones, catalog, mode=mode)


@pytest.mark.parametrize("field", ["top_md", "bottom_md", "density", "target_standoff_pct", "product_nr"])
def test_missing_required_zone_value_has_no_default(catalog, field, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    zones = zones_for(catalog)
    del zones[0][field]
    with pytest.raises(ValueError):
        solve(fluid_state(), zones, catalog)


@pytest.mark.parametrize("zones", [None, [], (), {}, "zones", [None], [[]], ["zone"]])
def test_malformed_or_empty_zone_collection_blocks(catalog, zones):
    with pytest.raises(ValueError):
        solve(fluid_state(), zones, catalog)


@pytest.mark.parametrize("bounds", [[(0., 600.), (500., 1000.)], [(500., 1000.), (0., 400.)]])
def test_overlap_and_disordered_zones_are_not_sorted_or_repaired(catalog, bounds, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    original = zones_for(catalog)[0]
    zones = [{**original, "top_md": top, "bottom_md": bottom} for top, bottom in bounds]
    before = deepcopy(zones)
    with pytest.raises(ValueError):
        solve(fluid_state(), zones, catalog)
    assert zones == before


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_zone_gaps_and_shared_boundaries_allowed_without_changing_bounds(catalog, kind):
    original = zones_for(catalog, kind)[0]
    top = original["top_md"]
    zones = [{**original, "top_md": top, "bottom_md": 600.},
             {**original, "top_md": 700., "bottom_md": 850.},
             {**original, "top_md": 850., "bottom_md": 1000.}]
    for mode in ("direct", "optimize"):
        result = solve(fluid_state(kind), tuple(zones), catalog, mode=mode)
        assert [(z["top_md"], z["bottom_md"]) for z in result["zones"]] == [
            (z["top_md"], z["bottom_md"]) for z in zones]


def test_liner_zones_above_mechanical_hanger_are_blocked(catalog):
    zones = zones_for(catalog, "liner")
    zones[0]["top_md"] = 399.999
    with pytest.raises(ValueError):
        solve(fluid_state("liner"), zones, catalog)


def test_duplicate_catalog_nr_blocks_without_selection(catalog, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    zones = zones_for(catalog)
    product = adapter.resolve_official_product(catalog, zones[0]["product_nr"])
    with pytest.raises(ValueError, match="ambiguous"):
        solve(fluid_state(), zones, [product, deepcopy(product)])


@pytest.mark.parametrize("products", [None, {}, "catalog", [None], [{}], [{"nr": True}]])
def test_malformed_catalog_cannot_reach_solver(catalog, monkeypatch, products):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    with pytest.raises(ValueError):
        solve(fluid_state(), zones_for(catalog), products)


def test_every_zone_is_validated_before_solver_execution(catalog, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    zones = zones_for(catalog)
    zones[0]["bottom_md"] = 500.
    zones.append({**zones[0], "top_md": 500., "bottom_md": 1000., "product_nr": -99999})
    with pytest.raises(ValueError, match="missing or ambiguous"):
        solve(fluid_state(), zones, catalog)


def test_nr_binding_ignores_duplicate_identification_and_deduplicates_reused_nr(catalog):
    by_label = {}
    for product in adapter.filter_official_products(catalog, 9.625):
        by_label.setdefault(product["identification"], []).append(product)
    pair = next(products[:2] for products in by_label.values() if len(products) > 1)
    assert pair[0]["nr"] != pair[1]["nr"]
    zones = [{"top_md": top, "bottom_md": bottom, "density": "1/1", "target_standoff_pct": 70.,
              "product_nr": product["nr"]} for top, bottom, product in
             [(0., 400., pair[0]), (400., 700., pair[1]), (700., 1000., pair[0])]]
    wd = payload(fluid_state(), zones, catalog)
    assert len(wd["products"]) == 2
    assert [p["name"] for p in wd["products"]] == [f"OFFICIAL-CENT-{p['nr']}" for p in pair]
    assert [z["product_name"] for z in wd["zones"]] == [
        f"OFFICIAL-CENT-{z['product_nr']}" for z in zones]
    result = solve(fluid_state(), zones, catalog)
    assert [z["product_nr"] for z in result["zones"]] == [z["product_nr"] for z in zones]


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_different_product_kinds_across_zones(catalog, mode):
    products = [next(p for p in adapter.filter_official_products(catalog, 9.625) if p["kind"] == kind)
                for kind in ("rigid", "spring")]
    zones = [{"top_md": top, "bottom_md": bottom, "density": "1/1", "target_standoff_pct": 70.,
              "product_nr": product["nr"]} for top, bottom, product in
             [(0., 500., products[0]), (500., 1000., products[1])]]
    result = solve(fluid_state(), zones, catalog, mode=mode)
    assert [z["product_kind"] for z in result["zones"]] == ["rigid", "spring"]


@pytest.mark.parametrize("mode", ["direct", "optimize"])
@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_tier2_static_forwards_columns_and_bypasses_bad_tier1(catalog, mode, kind):
    state = fluid_state(kind)
    state["fluids_config"] = "intentionally invalid Tier-1"
    override = {"inside_fluids": [(800., 1700.), (0., 1200.)],
                "annulus_fluids": [[500., 1600.], [0., 1300.]]}
    before = deepcopy(override)
    wd = payload(state, zones_for(catalog, kind), catalog, override=override)
    assert wd["fluids"]["inside_fluids"] == override["inside_fluids"]
    assert wd["fluids"]["annulus_fluids"] == override["annulus_fluids"]
    assert wd["fluids"]["mud_density"] == adapter.build_fluid_snapshot(state, override=override)["fluids"]["mud_density"]
    assert solve(state, zones_for(catalog, kind), catalog, mode=mode, override=override)["profile"]["centralizer_md"]
    assert override == before


@pytest.mark.parametrize("override", [
    {"inside_fluids": [[0., 1200.]]},
    {"inside_fluids": [[0., 1200.]], "annulus_fluids": [[1001., 1200.]]},
    {"inside_fluids": [[0., 1200.]], "annulus_fluids": [[0., 0.]]},
])
def test_invalid_tier2_blocks_static_before_engine(catalog, override, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    with pytest.raises(ValueError):
        solve(fluid_state(), zones_for(catalog), catalog, override=override)


def test_invalid_tier1_volume_blocks_static_before_engine(catalog, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    with pytest.raises(ValueError, match="volume"):
        solve(fluid_state(Tail=-1.), zones_for(catalog), catalog)


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_actual_low_standoff_is_successful_and_target_miss_preserved(catalog, mode):
    state = fluid_state(Tail=200.)
    state["well_geometry"] = {"version": 1, "type": "Directional", "survey": pd.DataFrame(
        {"MD": [0., 1200.], "Deviation": [60., 60.], "Azimuth": [0., 0.]})}
    result = solve(state, zones_for(catalog, target=100.), catalog, mode=mode)
    row = result["zones"][0]
    assert result["profile"]["centralizer_md"]
    assert row["min_stdf"] < 1. and row["meets_target"] is False
    if mode == "optimize":
        assert row["density_computed"] == "4/1"


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_input_state_zones_products_and_snapshot_are_not_mutated(catalog, mode, monkeypatch):
    state, zones, products = fluid_state(Tail=100.), zones_for(catalog), deepcopy(catalog)
    geometry = adapter.to_engine_geometry(state)
    snapshot = adapter.build_fluid_snapshot(state)
    before = pickle.dumps((state, zones, products, geometry, snapshot))
    monkeypatch.setattr(adapter, "to_engine_geometry", lambda state: geometry)
    monkeypatch.setattr(adapter, "build_fluid_snapshot", lambda state, **kwargs: snapshot)
    solve(state, zones, products, mode=mode)
    assert pickle.dumps((state, zones, products, geometry, snapshot)) == before
    # Payload is independently writable; source helpers/rows are not shadow state.
    wd = payload(state, zones, products)
    wd["survey"]["md"][0] = -100.
    wd["fluids"]["inside_fluids"][0][1] = -1.
    wd["zones"][0]["top_md"] = -1.
    wd["products"][0]["name"] = "changed"
    assert pickle.dumps((state, zones, products, geometry, snapshot)) == before


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_prevalidated_product_records_are_not_loaded_from_disk_or_using_session(catalog, monkeypatch, mode):
    import builtins
    import socket
    import streamlit as st
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    class NoSession:
        def __getattr__(self, name):
            forbidden()
        def __getitem__(self, key):
            forbidden()
        def __setitem__(self, key, value):
            forbidden()
    monkeypatch.setattr(st, "session_state", NoSession())
    assert solve(fluid_state(), zones_for(catalog), catalog, mode=mode)["profile"]["centralizer_md"]


@pytest.mark.parametrize("mode", [None, "dynamic", "direct_check", "", True])
def test_unknown_execution_mode_blocks(catalog, mode, monkeypatch):
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    monkeypatch.setattr(engine, "optimize_placement", forbidden)
    with pytest.raises(ValueError):
        solve(fluid_state(), zones_for(catalog), catalog, mode=mode)


@pytest.mark.parametrize("job", ["CMT PLUG", "CMT SQUEEZE"])
def test_not_applicable_job_never_executes_or_requires_zones(catalog, job, monkeypatch):
    for name in ("compute_standoff_profile", "optimize_placement", "run_full_analysis"):
        monkeypatch.setattr(engine, name, forbidden)
    state = {"job_type": job}
    assert payload(state, [], catalog) is None
    assert solve(state, [], catalog) is None


def test_adapter_contains_no_optimizer_physics_or_dynamic_state():
    tree = ast.parse(Path(adapter.__file__).read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in
                 ("build_static_payload", "solve_static")]
    assert len(functions) == 2
    forbidden_names = {"_density_candidates", "place_zone_centralizers", "run_full_analysis", "_WellModel",
                       "_beam_reaction", "standoff_fraction", "get_contract_template", "session_state",
                       "calculate_cemcade_bingham", "compute_phase_status", "fingerprint"}
    for function in functions:
        references = {node.attr if isinstance(node, ast.Attribute) else node.id for node in ast.walk(function)
                      if isinstance(node, (ast.Attribute, ast.Name))}
        assert not references & forbidden_names
