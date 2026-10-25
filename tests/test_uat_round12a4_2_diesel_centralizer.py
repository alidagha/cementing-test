"""A-4-2: canonical Diesel translation into the frozen Round-9 contracts."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path

import pytest

import centralizer_adapter as adapter
import centralizer_optimizer_engine as engine
import cement_chart_model as model
import materials_db
import phase_9_centralizer as phase9
import project_state
import rheology
from test_uat_round9c_fluid_snapshot import ORDER, assert_conserved, capacities, fluid_state
from test_uat_round9d_static_solver import forbidden, zones_for
from test_uat_round9e_dynamic_solver import auxiliary, dynamic_state, readings


ENGINE_SHA = "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9"


@pytest.fixture(scope="module")
def catalog():
    return adapter.load_official_catalog()


def project(catalog, kind="casing", physics="dynamic", mode="direct"):
    inside, annulus = capacities(fluid_state(kind))
    state = dynamic_state(kind, **{"Displacement Fluid": inside, "Diesel": annulus / 4.})
    state["mud_type"] = "OBM"
    state["fluids_config"]["params"]["Diesel"]["density"] = "52.5"
    state["lab_qc_params"]["Diesel"] = {"rheology": {
        "bhct_down": {"selected": True, "readings": readings()}}}
    state["centralizer_config"] = phase9.new_config()
    state["centralizer_config"].update(physics_mode=physics, placement_mode=mode,
                                        zones=zones_for(catalog, kind))
    return state


def carrier(state):
    """Existing supported stage supplies identical volume/density for contract isolation.

    This bypasses only the known Tier-1 taxonomy rejection in two RED probes;
    it never substitutes a solver or invents displacement/placement arithmetic.
    """
    state = deepcopy(state)
    cfg = state["fluids_config"]
    cfg["active"] = ["Spacer Ahead" if name == "Diesel" else name for name in cfg["active"]]
    cfg["params"]["Spacer Ahead"] = cfg["params"].pop("Diesel")
    return state


def isolated_snapshot(state):
    snapshot = adapter.build_fluid_snapshot(carrier(state))
    snapshot["per_fluid"]["Diesel"] = snapshot["per_fluid"].pop("Spacer Ahead")
    for column in ("inside_intervals", "annulus_intervals"):
        for row in snapshot[column]:
            if row["fluid"] == "Spacer Ahead":
                row["fluid"] = "Diesel"
    return snapshot


@pytest.mark.parametrize("physics", ["static", "dynamic"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_real_frozen_engine_accepts_diesel_contract(catalog, physics, mode):
    assert hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest() == ENGINE_SHA
    state = carrier(project(catalog))
    zones = state["centralizer_config"]["zones"]
    snapshot = adapter.build_fluid_snapshot(state)
    # The real Static engine contract is numeric [[top_md, density_kg_m3]],
    # not a fluid-name taxonomy. Feed the Diesel density/volume through it.
    assert any(row["density_pcf"] == 52.5 for row in snapshot["annulus_intervals"])
    if physics == "static":
        payload = adapter.build_static_payload(state, zones, catalog)
    else:
        payload = adapter.build_dynamic_payload(state, zones, catalog,
                                                 aux_rheology={"Spacer Ahead": readings()})["payload"]
        stages = payload["fluids"]["circulation"]["stages_rheology"]
        assert stages and all(row["name"] == "Spacer Ahead" for row in stages)
        for row in stages:
            row["name"] = "Diesel"
    engine.validate_well_data(payload)
    result = (engine.compute_standoff_profile(payload) if mode == "direct"
              else engine.optimize_placement(payload))
    assert result["centralizer_md"]
    assert all(math.isfinite(value) for value in result["tension_force"])


def test_tier1_projects_active_diesel(catalog):
    snapshot = adapter.build_fluid_snapshot(project(catalog))
    assert snapshot["per_fluid"]["Diesel"]["in_path_bbl"] > 0.
    assert any(row["fluid"] == "Diesel" for row in snapshot["annulus_intervals"])


def test_static_includes_active_diesel(catalog):
    state = project(catalog, physics="static")
    payload = adapter.build_static_payload(state, state["centralizer_config"]["zones"], catalog)
    assert any(rho == 52.5 * model.PCF_TO_KG_M3 for _, rho in payload["fluids"]["annulus_fluids"])


def test_dynamic_classification_consumes_phase7_not_aux(catalog, monkeypatch):
    state = project(catalog)
    snapshot = isolated_snapshot(state)
    monkeypatch.setattr(adapter, "build_fluid_snapshot", lambda *args, **kwargs: deepcopy(snapshot))
    prepared = adapter.build_dynamic_payload(state, state["centralizer_config"]["zones"], catalog,
                                               aux_rheology={"Diesel": readings(tuple(v * 2 for v in readings().values()))})
    fit = rheology.calculate_cemcade_bingham([(rpm, readings()[str(rpm)]) for rpm in rheology.RPM_ORDER])
    assert prepared["diagnostics"]["rheology"]["Diesel"] == {
        "source": "lab_bhct_down", **{key: fit[key] for key in ("pv_cp", "ty_lbf_100ft2", "iod")}}


def test_dynamic_signature_fingerprints_consumed_diesel(catalog, monkeypatch):
    state = project(catalog)
    snapshot = isolated_snapshot(state)
    monkeypatch.setattr(adapter, "build_fluid_snapshot", lambda *args, **kwargs: deepcopy(snapshot))
    before = phase9.source_signature(state, catalog)
    state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]["readings"]["300"] += 1.
    assert phase9.source_signature(state, catalog) != before


def test_auxiliary_family_and_version_remain_protected():
    assert phase9.AUX_FLUIDS == ("Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind")
    assert "Diesel" in materials_db.PHASE7_LAB_FLUIDS
    assert "Diesel" not in materials_db.RHEOLOGY_LAB_FLUIDS
    config = phase9.new_config()
    assert config["version"] == 1
    config["aux_rheology"]["Diesel"] = readings()
    with pytest.raises(ValueError, match="auxiliary fluid records only"):
        phase9.validate_config(config)


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("remaining_fraction", [1., .5, 0.])
def test_diesel_full_partial_and_complete_return_conserve_existing_path(catalog, kind, remaining_fraction):
    state = project(catalog, kind)
    inside, annulus = capacities(state)
    total, volume = math.fsum((inside, annulus)), annulus / 4.
    if remaining_fraction != 1.:
        state["fluids_config"]["params"]["Displacement Fluid"]["volume"] = total - volume * remaining_fraction
    snapshot = adapter.build_fluid_snapshot(state)
    assert_conserved(snapshot)
    row = snapshot["per_fluid"]["Diesel"]
    assert row["entered_bbl"] == volume
    assert row["in_path_bbl"] == pytest.approx(volume * remaining_fraction)
    assert row["returned_bbl"] == pytest.approx(volume * (1. - remaining_fraction))
    entered = snapshot["totals"]["entered_bbl"]
    assert snapshot["original_mud"] == {"initial_bbl": total, "in_path_bbl": max(0., total - entered),
                                         "displaced_bbl": min(entered, total)}
    assert snapshot["overflow_kind"] == ("surface_dump" if kind == "casing" else "overlap_excess")
    names = {row["fluid"] for row in snapshot["annulus_intervals"]}
    assert ("Diesel" in names) == (remaining_fraction > 0.)


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_diesel_is_above_preflush_without_changing_any_previous_order(catalog, kind, monkeypatch):
    state = project(catalog, kind)
    inside, annulus = capacities(state)
    order = (*ORDER, "Diesel")
    state["fluids_config"] = {"active": list(reversed(order)), "params": {
        name: {"volume": inside if name == "Displacement Fluid" else annulus / 20.,
               "density": "52.5" if name == "Diesel" else str(90 + index)}
        for index, name in enumerate(order)}}
    original = model._fluid
    consumed = []
    def shared_fluid(source, name):
        consumed.append(name)
        return original(source, name)
    monkeypatch.setattr(model, "_fluid", shared_fluid)
    monkeypatch.setattr(model, "resolve_final_fluid_intervals", forbidden)
    monkeypatch.setattr(model, "resolve_cement_placement", forbidden)
    snapshot = adapter.build_fluid_snapshot(state)
    annular = snapshot["annulus_intervals"]
    assert [row["fluid"] for row in reversed(annular)] == [*order[1:], "Mud"]
    assert consumed == list(order[1:])
    diesel = next(row for row in annular if row["fluid"] == "Diesel")
    preflush = next(row for row in annular if row["fluid"] == "Pre Flush")
    assert diesel["bottom_md"] == preflush["top_md"]
    assert diesel["density_pcf"] == 52.5
    assert_conserved(snapshot)


@pytest.mark.parametrize("density", [50.99, 54.01, "51-54", True, None, float("nan"), float("inf")])
def test_static_uses_shared_strict_diesel_density(catalog, density, monkeypatch):
    state = project(catalog)
    state["fluids_config"]["params"]["Diesel"]["density"] = density
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    with pytest.raises(ValueError, match="Diesel density must be a single value between 51 and 54 pcf"):
        adapter.solve_static(state, state["centralizer_config"]["zones"], catalog, mode="direct")


@pytest.mark.parametrize("density", [51., 54., "۵۲.۳"])
def test_static_accepts_shared_diesel_density_limits(catalog, density):
    state = project(catalog)
    state["fluids_config"]["params"]["Diesel"]["density"] = density
    snapshot = adapter.build_fluid_snapshot(state)
    assert snapshot["per_fluid"]["Diesel"]["in_path_bbl"] > 0.


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("physics", ["static", "dynamic"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_real_diesel_execute_is_finite_current_and_uses_frozen_engine(catalog, kind, physics, mode):
    state = project(catalog, kind, physics, mode)
    before = project_state.fingerprint(state)
    zones = state["centralizer_config"]["zones"]
    if physics == "dynamic":
        prepared = adapter.build_dynamic_payload(state, zones, catalog)
        payload = prepared["payload"]
        diagnostic = prepared["diagnostics"]["rheology"]["Diesel"]
        assert diagnostic["source"] == "lab_bhct_down"
        fit = rheology.calculate_cemcade_bingham([(rpm, readings()[str(rpm)]) for rpm in rheology.RPM_ORDER])
        assert {key: diagnostic[key] for key in ("pv_cp", "ty_lbf_100ft2", "iod")} == {
            key: fit[key] for key in ("pv_cp", "ty_lbf_100ft2", "iod")}
        stages = payload["fluids"]["circulation"]["stages_rheology"]
        assert stages and {row["name"] for row in stages} == {"Diesel"}
        for row in stages:
            assert row["pv_pa_s"] == diagnostic["pv_cp"] * adapter.CP_TO_PA_S
            assert row["ty_pa"] == diagnostic["ty_lbf_100ft2"] * adapter.LBF_100FT2_TO_PA
    else:
        payload = adapter.build_static_payload(state, zones, catalog)
    engine.validate_well_data(payload)
    expected = (engine.compute_standoff_profile(payload) if mode == "direct"
                else engine.optimize_placement(payload))
    result = phase9.execute(state, catalog)
    assert result["profile"] == expected and result["mode"] == mode
    assert all(math.isfinite(value) for value in result["profile"]["tension_force"])
    assert phase9.result_is_current(state, catalog)
    for key in ("_centralizer_result", "_centralizer_signature"):
        state.pop(key)
    assert project_state.fingerprint(state) == before


@pytest.mark.parametrize("defect", ["missing_lab", "missing_qc", "missing_rheology", "missing_down", "unselected",
    "numeric_selection", "incomplete", "extra_rpm", "nonfinite", "negative", "bad_fit"])
def test_invalid_diesel_blocks_before_solver_and_retires_result_without_fallback(catalog, monkeypatch, defect):
    state = project(catalog)
    assert phase9.execute(state, catalog) is not None
    qc = state["lab_qc_params"]["Diesel"]
    row = qc["rheology"]["bhct_down"]
    # Every alternate source is valid and deliberately different. None is a fallback.
    qc["rheology"].update(surface_down={"selected": True, "readings": readings()},
                           bhct_up={"selected": True, "readings": readings()})
    state["lab_payload_Diesel"] = {"rheology": {"bhct_down": {"pv_cp": 100., "ty_lbf_100ft2": 10.}}}
    if defect == "missing_lab": state.pop("lab_qc_params")
    elif defect == "missing_qc": state["lab_qc_params"].pop("Diesel")
    elif defect == "missing_rheology": qc.pop("rheology")
    elif defect == "missing_down": qc["rheology"].pop("bhct_down")
    elif defect == "unselected": row["selected"] = False
    elif defect == "numeric_selection": row["selected"] = 1
    elif defect == "incomplete": row["readings"].pop("3")
    elif defect == "extra_rpm": row["readings"]["gel"] = 6.
    elif defect == "nonfinite": row["readings"]["300"] = float("nan")
    elif defect == "negative": row["readings"]["300"] = -1.
    else: row["readings"] = readings((150., 100., 50., 30., 15., 2., 1.))
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    monkeypatch.setattr(engine, "optimize_placement", forbidden)
    monkeypatch.setattr(adapter, "solve_static", forbidden)
    assert not phase9.result_is_current(state, catalog)
    with pytest.raises(ValueError, match="MissingRheology") as error:
        phase9.execute(state, catalog)
    assert "Phase VII BHCT — Ramp-Down" in str(error.value)
    assert "Phase IX" not in str(error.value) and "switch to Static" not in str(error.value)
    assert "_centralizer_result" not in state and "_centralizer_signature" not in state
    assert state["_centralizer_error"] == str(error.value)


@pytest.mark.parametrize("volumes", [(1., 1.), (1e6, 1.)])
def test_diesel_inside_only_or_fully_returned_still_requires_phase7(catalog, volumes):
    state = project(catalog)
    for name, volume in zip(("Displacement Fluid", "Diesel"), volumes):
        state["fluids_config"]["params"][name]["volume"] = volume
    assert not any(row["fluid"] == "Diesel" for row in adapter.build_fluid_snapshot(state)["annulus_intervals"])
    state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]["selected"] = False
    with pytest.raises(ValueError, match="MissingRheology"):
        adapter.build_dynamic_payload(state, state["centralizer_config"]["zones"], catalog,
                                        aux_rheology={"Diesel": readings()})


@pytest.mark.parametrize("field", ["selected", "readings", "volume", "density"])
@pytest.mark.parametrize("physics", ["static", "dynamic"])
def test_currentness_tracks_only_consumed_active_diesel_authority(catalog, physics, field):
    state = project(catalog, physics=physics)
    assert phase9.execute(state, catalog) is not None
    signature = phase9.source_signature(state, catalog)
    if field == "selected":
        state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"][field] = False
    elif field == "readings":
        state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"][field]["300"] += 1.
    else:
        state["fluids_config"]["params"]["Diesel"][field] = 53. if field == "density" else 40.
    consumed = physics == "dynamic" or field in ("volume", "density")
    assert (phase9.source_signature(state, catalog) != signature) == consumed
    assert phase9.result_is_current(state, catalog) == (not consumed)


@pytest.mark.parametrize("unused", ["surface_down", "bhct_up", "gel", "aux", "derived_fit"])
def test_unconsumed_diesel_datasets_and_auxiliary_drafts_do_not_stale_or_change_execution(catalog, unused):
    state = project(catalog)
    result = phase9.execute(state, catalog)
    signature = phase9.source_signature(state, catalog)
    rheo = state["lab_qc_params"]["Diesel"]["rheology"]
    if unused in ("surface_down", "bhct_up"):
        rheo[unused] = {"selected": True, "readings": {"300": "invalid unused draft"}}
    elif unused == "gel":
        rheo["bhct_down"].update(gel_10_sec=-999., gel_10_min=float("nan"))
    elif unused == "aux":
        state["centralizer_config"]["aux_rheology"]["Spacer"] = {"300": 1.}
    else:
        rheo["bhct_down"].update(pv_cp=-999., ty_lbf_100ft2=-999., is_valid_bingham=False)
    assert phase9.source_signature(state, catalog) == signature
    assert phase9.result_is_current(state, catalog)
    assert phase9.execute(state, catalog) == result


@pytest.mark.parametrize("physics", ["static", "dynamic"])
def test_inactive_diesel_drafts_do_not_affect_snapshot_signature_or_execution(catalog, physics):
    state = project(catalog, physics=physics)
    state["fluids_config"]["active"].remove("Diesel")
    snapshot = adapter.build_fluid_snapshot(state)
    result = phase9.execute(state, catalog)
    signature = phase9.source_signature(state, catalog)
    state["fluids_config"]["params"]["Diesel"] = {"density": "bad draft", "volume": float("nan")}
    state["lab_qc_params"]["Diesel"] = None
    assert adapter.build_fluid_snapshot(state) == snapshot
    assert phase9.source_signature(state, catalog) == signature
    assert phase9.result_is_current(state, catalog)
    assert phase9.execute(state, catalog) == result


@pytest.mark.parametrize("physics", ["static", "dynamic"])
def test_obm_wbm_lifecycle_preserves_drafts_retires_currentness_and_never_reactivates(catalog, physics):
    state = project(catalog, physics=physics)
    assert phase9.execute(state, catalog) is not None
    params = deepcopy(state["fluids_config"]["params"]["Diesel"])
    lab = deepcopy(state["lab_qc_params"]["Diesel"])
    state["mud_type"] = "WBM"
    project_state.reconcile_fluid_applicability(state)
    assert "Diesel" not in state["fluids_config"]["active"]
    assert not phase9.result_is_current(state, catalog)
    assert state["fluids_config"]["params"]["Diesel"] == params
    assert state["lab_qc_params"]["Diesel"] == lab
    signature = phase9.source_signature(state, catalog)
    state["mud_type"] = "OBM"
    project_state.reconcile_fluid_applicability(state)
    assert "Diesel" not in state["fluids_config"]["active"]
    assert state["fluids_config"]["params"]["Diesel"] == params
    assert state["lab_qc_params"]["Diesel"] == lab
    assert phase9.source_signature(state, catalog) == signature
    result = phase9.execute(state, catalog)
    assert "Diesel" not in result.get("diagnostics", {}).get("rheology", {})
    assert phase9.result_is_current(state, catalog)


def test_tier2_static_stays_explicit_and_dynamic_stays_unsupported(catalog):
    state = project(catalog)
    zones = state["centralizer_config"]["zones"]
    override = {"inside_fluids": [[0., 1300.]], "annulus_fluids": [[0., 1500.]]}
    before = deepcopy(override)
    state["fluids_config"]["params"]["Diesel"]["density"] = "invalid unused Tier-1 source"
    snapshot = adapter.build_fluid_snapshot(state, override=override)
    assert snapshot["diagnostics_available"] is False
    assert {key: snapshot["fluids"][key] for key in override} == before
    assert adapter.solve_static(state, zones, catalog, mode="direct", override=override)["profile"]["centralizer_md"]
    with pytest.raises(ValueError, match="Tier-2"):
        adapter.build_dynamic_payload(state, zones, catalog, override=override)
    assert override == before


@pytest.mark.parametrize("job", ["CMT PLUG", "CMT SQUEEZE"])
def test_plug_squeeze_remain_not_applicable_with_no_solver_admission(catalog, job, monkeypatch):
    state = {"job_type": job, "fluids_config": {"active": ["Diesel"], "params": {"Diesel": {}}}}
    monkeypatch.setattr(engine, "compute_standoff_profile", forbidden)
    monkeypatch.setattr(engine, "optimize_placement", forbidden)
    assert adapter.build_fluid_snapshot(state) is None
    assert adapter.build_static_payload(state, [], catalog) is None
    assert adapter.build_dynamic_payload(state, [], catalog) is None
    assert phase9.execute(state, catalog) is None


def test_diesel_uses_fresh_seven_rpm_authority_in_canonical_order(catalog, monkeypatch):
    state = project(catalog)
    row = state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]
    row["readings"] = dict(reversed(list(readings().items())))
    row.update(pv_cp=-999., ty_lbf_100ft2=-999., is_valid_bingham=False, gel_10_sec="", gel_10_min="")
    calls = []
    original = rheology.calculate_cemcade_bingham
    def fresh_fit(points):
        points = list(points)
        calls.append(points)
        return original(points)
    monkeypatch.setattr(rheology, "calculate_cemcade_bingham", fresh_fit)
    prepared = adapter.build_dynamic_payload(state, state["centralizer_config"]["zones"], catalog)
    assert calls == [[(rpm, readings()[str(rpm)]) for rpm in rheology.RPM_ORDER]]
    assert prepared["diagnostics"]["rheology"]["Diesel"]["pv_cp"] == original(calls[0])["pv_cp"]


def test_diesel_does_not_create_phase9_auxiliary_controls(catalog):
    from test_uat_round9f_phase9 import ui_app
    app = ui_app(project(catalog))
    assert not app.exception
    assert any("Cement/Scavenger/Diesel/Spacer/Pre Flush: Phase VII BHCT" in item.value for item in app.caption)
    assert not any((widget.key or "").startswith("_centralizer_aux_") for widget in app.number_input)
    assert "Diesel" not in app.session_state["centralizer_config"]["aux_rheology"]


def test_existing_non_diesel_missing_rheology_guidance_is_unchanged():
    with pytest.raises(ValueError) as error:
        adapter._dynamic_fann(None, "Spacer Ahead")
    assert str(error.value) == (
        "[MissingRheology] Missing Bingham parameters (PV/Ty) for fluid 'Spacer Ahead'. "
        "Complete fluid rheology in Phase IX/Lab Report or switch to Static Parity mode. "
        "Exactly all seven RPM readings are required.")
