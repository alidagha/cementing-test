"""PR14 recovery: physical sources, active solver domain and honest admission."""
from copy import deepcopy
import json
import math
import pickle
from unittest.mock import patch

import pandas as pd
import pytest

import centralizer_adapter as adapter
import centralizer_optimizer_engine as engine
import cement_chart_model as chart
from engineering_tools import BBL_TO_CUFT
from test_round15_nested_geometry import reference_casing
from test_uat_round9e_dynamic_solver import dynamic_state, auxiliary
from test_uat_round9d_static_solver import zones_for
from test_uat_round12a5_diesel_word_e2e import projects, sync, context, word, NO_DIESEL_A42


@pytest.mark.parametrize("mode", ["direct", "optimize"])
def test_dynamic_liner_consumes_active_body_not_upstream_cumulative_pressure(monkeypatch, mode):
    state = dynamic_state("liner")
    # Distinct measured synthetic workstring and liner ODs, never homogenized.
    state["hardware_table"].loc[lambda t: t["Description"] == "Drill Pipes", "Size (in)"] = "5"
    original = pickle.dumps(state)
    catalog = adapter.load_official_catalog()
    payload = adapter.build_dynamic_payload(state, zones_for(catalog, "liner"), catalog,
                                            aux_rheology=auxiliary())["payload"]
    top = payload["wellbore"]["string_top"]
    assert top == 400. and payload["casing"]["od"] == 7. * .0254
    changed = deepcopy(payload)
    changed["fluids"]["circulation"]["stages_rheology"].insert(0, {
        "name": "Synthetic upstream-only rheology", "top_md": 0., "bottom_md": top - 1.,
        "pv_pa_s": 1., "ty_pa": 50.})
    # The scalar engine does compute a different unused surface integral.
    assert engine._WellModel(payload).hydraulics._cum != engine._WellModel(changed).hydraulics._cum
    reads = {"drag": [], "tension": []}
    drag, tension = engine._AnnularHydraulics.drag_per_m_at, engine._TensionModel.tension_at

    def local_drag(self, md):
        reads["drag"].append(md)
        return drag(self, md)

    def local_tension(self, md):
        reads["tension"].append(md)
        return tension(self, md)

    def forbid_cumulative_pressure(*args):
        raise AssertionError("Active-body profile consumed upstream cumulative pressure")

    monkeypatch.setattr(engine._AnnularHydraulics, "drag_per_m_at", local_drag)
    monkeypatch.setattr(engine._TensionModel, "tension_at", local_tension)
    monkeypatch.setattr(engine._AnnularHydraulics, "friction_pressure_at", forbid_cumulative_pressure)
    solve = engine.compute_standoff_profile if mode == "direct" else engine.optimize_placement
    snapshots = [pickle.dumps(p) for p in (payload, changed)]
    assert solve(payload) == solve(changed)  # Entire actual result, no successful solver mock.
    assert reads["drag"] and reads["tension"]
    assert min(reads["drag"]) >= top and min(reads["tension"]) >= top
    assert snapshots == [pickle.dumps(p) for p in (payload, changed)]
    assert pickle.dumps(state) == original


@pytest.mark.parametrize("shoe", [100., 150., 400.])
def test_csg_target_cannot_precede_or_equal_measured_previous_shoe(shoe):
    state = reference_casing()
    state["placement_config"].update(target_row="__manual__", manual_depth_m=shoe)
    before = pickle.dumps(state)
    with pytest.raises(ValueError, match="Previous shoe must lie above"):
        chart.resolve_chart_geometry(state)
    assert pickle.dumps(state) == before


def test_scalar_tieback_reference_has_verified_sources_repeatable_json_and_real_word(projects, tmp_path):
    import test_audit_regressions as audit
    import phase_9_centralizer as phase9
    import project_state as ps
    from centralizer_fixtures import execute_centralizer
    job = 'TIE BACK LNR 7"'
    state = projects(job, active=False, include_standalone_spacer=True)
    table = state["hardware_table"]
    # Owner-approved SYNTHETIC certification geometry, not the interior two-ID well.
    assert [(r["Description"], r["MD (m)"], float(r["Size (in)"]), r["ID (in)"])
            for r in table.to_dict("records")] == [
        ("Previous Casing", "3300.0", 13.375, 12.25),
        ("Tie Back", "0-3000.0", 7., 6.276),
        ("Previous Liner", "3000.0-3300.0", 9.625, 8.535)]
    from placement import hardware_choices
    assert state["placement_config"]["host_row"] == next(iter(hardware_choices(table, {"Previous Casing"})))
    assert state["placement_config"]["target_row"] == next(iter(hardware_choices(table, {"Tie Back"})))
    assert [(s["top_md"], s["bottom_md"], s["id_in"])
            for s in chart.resolve_chart_geometry(state)["enclosing_string"]] == [(0., 3000., 12.25)]
    bounds = adapter.to_engine_geometry(state)["wellbore"]
    assert (bounds["string_top"], bounds["string_shoe"], bounds["prev_casing_id"]) == (0., 3000., 12.25 * .0254)
    assert "Diesel" not in state["fluids_config"]["active"] and phase9.result_is_current(state)
    keys = ("hardware_table", "placement_config", "fluids_config", "well_geometry", "cement_params",
            "cement_additives_dfs", "lab_grid_dfs", "lab_qc_params")
    sources = ps.fingerprint({k: state[k] for k in keys})
    specs = sync(state)
    assert tuple(specs[k]["signature"] for k in ("exec_summary_text", "procedure_text")) == NO_DIESEL_A42[job]
    assert specs == sync(state)
    assert sources == ps.fingerprint({k: state[k] for k in keys})
    assert "7\" Tie Back cementing" in specs["exec_summary_text"]["generated"]
    assert "[PLACEMENT INCOMPLETE]" not in specs["exec_summary_text"]["generated"]
    for spec in specs.values():
        assert "Diesel" not in spec["generated"]
    restored = audit.round_trip(state)
    pd.testing.assert_frame_equal(restored["hardware_table"], table, check_dtype=False)
    assert ps.prepare_calculations(restored) == []
    assert not phase9.result_is_current(restored)
    execute_centralizer(restored, physics="dynamic")
    restored_specs = sync(restored)
    for key in specs:
        assert restored_specs[key]["signature"] == specs[key]["signature"]
        assert restored_specs[key]["generated"] == specs[key]["generated"]
    ctx = context(restored)
    document = word(ctx)
    document.save(tmp_path / "synthetic-scalar-tieback-no-diesel.docx")
    (tmp_path / "synthetic-scalar-tieback-project.json").write_text(json.dumps({
        k: audit.namespace["serialize_item"](v) for k, v in restored.items() if ps.is_project_key(k)},
        ensure_ascii=False, allow_nan=False, indent=2))
    text = "\n".join([p.text for p in document.paragraphs] +
                      [c.text for t in document.tables for r in t.rows for c in r.cells])
    assert "7\" Tie Back cementing" in text and "Diesel" not in text
    assert "0-3000.0" in text and "3000.0-3300.0" in text
    changed = deepcopy(state)
    changed["hardware_table"].at[0, "ID (in)"] = 12.249
    assert sync(changed)["exec_summary_text"]["signature"] != specs["exec_summary_text"]["signature"]
    (tmp_path / "scalar-reference-signatures.json").write_text(json.dumps({
        "provenance": "Owner-approved synthetic receiver-at-tie-in; NOT the old two-ID example",
        "hardware": table.to_dict("records"),
        "signatures": {k: specs[k]["signature"] for k in specs},
        "generated": {k: specs[k]["generated"] for k in specs},
        "source_immutable": True, "json_and_repeatable": True, "mutation_detected": True}, indent=2))


@pytest.mark.parametrize("physics", ["static", "dynamic"])
def test_original_two_id_tieback_stays_truthful_and_cannot_reuse_scalar_result(projects, physics, tmp_path):
    import test_audit_regressions as audit
    import phase_9_centralizer as phase9
    import centralizer_report
    import well_schematic_adapter as schematic
    import project_state as ps
    import phase_10_procedure as report
    import engineering_tools as tools
    from centralizer_fixtures import execute_centralizer
    state = projects('TIE BACK LNR 7"', active=False)
    execute_centralizer(state, physics=physics)
    assert phase9.result_is_current(state)
    # Restore the exact original receiving liner, with explicit surface Top
    # retained only to remove the old source's independent Top ambiguity.
    state["hardware_table"].loc[lambda t: t["Description"] == "Previous Liner", "MD (m)"] = "2500.0-3300.0"
    before = pickle.dumps(state)
    assert [(s["top_md"], s["bottom_md"], s["id_in"])
            for s in chart.resolve_chart_geometry(state)["enclosing_string"]] == [
        (0., 2500., 12.25), (2500., 3000., 8.535)]
    payload = schematic.prepare_schematic(state)
    liner = next(c for c in payload["casings"] if c["type"] == "liner")
    assert (liner["top_md"], liner["shoe_md"], liner["id_in"]) == (2500., 3300., 8.535)
    for check in (adapter.to_engine_geometry, adapter.require_dynamic_geometry):
        with pytest.raises(ValueError, match="one identical scalar ID"):
            check(state)
    assert pickle.dumps(state) == before
    import pumping_simulation
    hydraulic = pumping_simulation.prepare_pumping_simulation(state)["inputs"]["geometry"]
    assert (hydraulic.track_depth_m, hydraulic.td_m) == (3000., 3300.)
    assert pickle.dumps(state) == before
    assert not phase9.result_is_current(state)
    assert tools.compute_phase_status(state)["phase9"]["level"] == "warning"
    with pytest.raises(ValueError, match="Phase IX"):
        centralizer_report.prepare_report(state)
    state.update(_compiled_doc_bytes=b"stale scalar result", _compiled_doc_signature="old")
    ps.prepare_calculations(state)
    assert not any(k.startswith("_compiled_doc_") for k in state)
    with patch.object(report.st, "session_state", state):
        with pytest.raises(ValueError, match="Phase IX"):
            report.build_master_context()
    restored = audit.round_trip(state)
    pd.testing.assert_frame_equal(restored["hardware_table"], state["hardware_table"], check_dtype=False)
    assert not phase9.result_is_current(restored)
    (tmp_path / "original-two-id-tieback-project.json").write_text(json.dumps({
        k: audit.namespace["serialize_item"](v) for k, v in restored.items() if ps.is_project_key(k)},
        ensure_ascii=False, allow_nan=False, indent=2))


def test_liner_diesel_seed_and_snapshot_retain_piecewise_measured_pipe_geometry():
    from test_uat_round12a4_2_diesel_centralizer import project
    from test_uat_round9c_fluid_snapshot import capacities, fluid_state
    inside, annulus = capacities(fluid_state("liner"))
    state = project(adapter.load_official_catalog(), "liner")
    before = pickle.dumps(state)
    geometry = chart.resolve_chart_geometry(state)
    assert [(s["top_md"], s["bottom_md"], s["od_in"], s["id_in"])
            for s in geometry["active_string"]] == [(0., 400., 5., 4.), (400., 1000., 7., 6.)]
    area = lambda wall, pipe: math.pi / 4 * (wall**2 - pipe**2) / 144 / .3048 / BBL_TO_CUFT
    expected = 400. * area(8.535, 5.) + 100. * area(8.535, 7.) + 500. * area(8.5, 7.)
    snapshot = adapter.build_fluid_snapshot(state)
    assert annulus == pytest.approx(expected, rel=1e-13)
    assert snapshot["capacity_bbl"]["annulus"] == pytest.approx(expected, rel=1e-13)
    assert snapshot["capacity_bbl"]["inside"] == inside
    assert pickle.dumps(state) == before


def test_job_specific_summary_fixtures_never_conceal_incomplete_geometry():
    import materials_db
    from test_uat_executive_summary import generate
    for job in materials_db.JOB_TYPES:
        if job == materials_db.CT_JOB:
            continue  # Existing CT guard is separately exercised by the original References test.
        text = generate(job, ("Main",), excess=False)
        assert "[PLACEMENT INCOMPLETE]" not in text, job
        assert "[TARGET DEPTH NOT SELECTED" not in text, job
