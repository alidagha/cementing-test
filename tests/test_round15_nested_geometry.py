"""ROUND15 measured reference and explicitly synthetic geometry prerequisites."""
from copy import deepcopy
import math
import pickle

import pandas as pd
import pytest

import cement_chart_model as chart
import centralizer_adapter
import pumping_simulation
from engineering_tools import BBL_TO_CUFT
from placement import hardware_choices, target_descriptions


def hardware(*rows):
    return pd.DataFrame([dict(zip(("Description", "MD (m)", "Size (in)", "ID (in)"), row),
                              **{"Joint (m)": 12.2, "Weight (ppf)": 50., "Grade": "K-55",
                                 "Collapse (psi)": 1000., "Burst (psi)": 2000.})
                         for row in rows])


def project(job, rows, td):
    state = {"job_type": job, "hardware_table": rows,
             "well_geometry": {"version": 1, "type": "Vertical", "td_m": td},
             "placement_config": {"job_type": job, "chart_excess_mode": "ignore"}}
    state["placement_config"]["target_row"] = next(iter(hardware_choices(rows, target_descriptions(job))))
    return state


def reference_casing(reverse=False):
    # Owner-supplied depths/diameters. Current ID/weight/joint are synthetic
    # prerequisites for the adapters, not claimed field measurements.
    previous = [("Previous Casing", "53", "20", 18.730),
                ("Previous Casing", "400", "13 3/8", 12.347)]
    if reverse:
        previous.reverse()
    return project('CSG 9 5/8"', hardware(
        ("Casing", "1970", "9 5/8", 8.535), *previous,
        ("Open Hole Size", "400-1970", "12.250", 12.250)), 1970.)


def synthetic_tieback(top=100., explicit=True):
    # All Tie Back measurements in this fixture are synthetic. The upstream
    # workstring is explicit; its OD matches the active OD for scalar mapping.
    rows = [("Tie Back", f"{top:g}-700" if explicit else "700", "7", 6.),
            ("Previous Casing", "800", "9 5/8", 8.535),
            ("Previous Liner", "700-1200", "7", 6.),
            ("Open Hole Size", "800-1200", "8.5", 8.5)]
    if top > 0:
        rows.append(("Drill Pipes", f"{top:g}", "7", 6.))
    state = project('TIE BACK LNR 7"', hardware(*rows), 1200.)
    state["placement_config"]["host_row"] = next(iter(hardware_choices(
        state["hardware_table"], {"Previous Casing"})))
    return state


def boundary(geometry):
    return [(s["top_md"], s["bottom_md"], s["od_in"] if s["description"] == "Open Hole Size"
             else s["id_in"]) for s in geometry["enclosing_string"]]


@pytest.mark.parametrize("reverse", [False, True])
def test_reference_nested_csg_uses_immediate_wall_and_analytical_capacity(reverse):
    state = reference_casing(reverse)
    before = pickle.dumps(state)
    geometry = chart.resolve_chart_geometry(state)
    assert boundary(geometry) == [(0., 400., 12.347), (400., 1970., 12.250)]
    for segment, diameter in zip(geometry["capacity_segments"], (12.347, 12.250)):
        expected = math.pi / 4 * (diameter**2 - 9.625**2) / 144 / .3048 / BBL_TO_CUFT
        assert segment["nominal_bbl_per_m"] == pytest.approx(expected, rel=1e-14)
    assert pickle.dumps(state) == before


def test_reference_scalar_centralizer_maps_effective_wall_not_outer_history():
    geometry = centralizer_adapter.to_engine_geometry(reference_casing())
    assert geometry["wellbore"]["prev_casing_id"] == 12.347 * .0254
    assert geometry["wellbore"]["prev_shoe_depth"] == 400.
    assert geometry["wellbore"]["hole_size"] == 12.250 * .0254


def test_explicit_nonzero_tieback_top_preserves_explicit_upstream_path_and_landing():
    state = synthetic_tieback()
    geometry = chart.resolve_chart_geometry(state)
    assert [(s["top_md"], s["bottom_md"], s["description"]) for s in geometry["active_string"]] == [
        (0., 100., "Drill Pipes"), (100., 700., "Tie Back")]
    centralizer = centralizer_adapter.to_engine_geometry(state)
    assert centralizer["wellbore"]["string_top"] == 100.
    pumping, _ = pumping_simulation._geometry(state, "tieback")
    assert [(s.z_top, s.z_bot) for s in pumping.pipe_sections] == [(0., 100.), (100., 700.), (700., 1200.)]
    assert pumping.track_depth_m == 700.


def test_scalar_tieback_endpoint_without_top_is_not_surface_evidence():
    state = synthetic_tieback(top=0., explicit=False)
    with pytest.raises(ValueError, match="[Tt]op"):
        chart.resolve_chart_geometry(state)


def test_historical_liner_has_nonzero_top_and_actual_nested_host():
    state = project('LNR 5"', hardware(
        ("Drill Pipes", "900", "5", 4.), ("Liner Hanger", "900", "5", 4.),
        ("Liner", "900-1500", "5", 4.),
        ("Previous Casing", "400", "13 3/8", 12.347),
        ("Previous Casing", "800", "9 5/8", 8.535),
        ("Previous Liner", "600-1100", "7", 6.),
        ("Open Hole Size", "1100-1500", "6.125", 6.125)), 1500.)
    geometry = chart.resolve_chart_geometry(state)
    assert boundary(geometry) == [(0., 600., 8.535), (600., 1100., 6.), (1100., 1500., 6.125)]
    assert next(s for s in geometry["active_string"] if s["description"] == "Liner")["top_md"] == 900.


def test_outer_installed_history_edit_retires_centralizer_authority():
    import phase_9_centralizer as phase9
    from test_uat_round9h_integration import configured
    catalog = centralizer_adapter.load_official_catalog()
    state = configured(catalog)
    state.update(reference_casing())
    before = phase9.source_signature(state, catalog)
    state["hardware_table"].at[1, "ID (in)"] = 18.729
    assert phase9.source_signature(state, catalog) != before


def test_dynamic_active_body_keeps_measured_upstream_od_in_fluid_path():
    from test_uat_round9e_dynamic_solver import dynamic_state, auxiliary
    from test_uat_round9d_static_solver import zones_for
    state = dynamic_state("liner")
    state["hardware_table"].loc[state["hardware_table"]["Description"] == "Drill Pipes", "Size (in)"] = "5"
    catalog = centralizer_adapter.load_official_catalog()
    # The frozen profile evaluates the active body; the fluid path still
    # includes the actual distinct workstring. No scalar hydraulic substitute.
    assert centralizer_adapter.to_engine_geometry(state)["wellbore"]["string_top"] == 400.
    result = centralizer_adapter.build_dynamic_payload(state, zones_for(catalog, "liner"), catalog, aux_rheology=auxiliary())
    assert result["payload"]["casing"]["od"] == 7. * .0254
    assert chart.resolve_chart_geometry(state)["active_string"][0]["od_in"] == 5.


def test_liner_running_fit_is_separate_from_final_upstream_workstring_wall():
    from test_uat_round9b_geometry import state_for
    state = state_for("liner")
    table = state["hardware_table"]
    host = table.loc[table["Description"] == "Previous Casing"].iloc[0].to_dict()
    host.update({"MD (m)": "100", "ID (in)": 6.5})
    state["hardware_table"] = pd.concat([pd.DataFrame([host]), table], ignore_index=True)
    # The final 5-inch workstring fits, but the 7-inch liner could never pass.
    with pytest.raises(ValueError, match="pass|restriction|fit"):
        chart.resolve_chart_geometry(state)


@pytest.mark.parametrize("fault", ["contradictory_top", "missing_workstring", "missing_receiver", "ambiguous_receiver", "missing_host", "stale_host", "outside_host"])
def test_tieback_insufficient_or_inconsistent_authority_blocks_all_consumers(fault):
    state = synthetic_tieback()
    if fault == "contradictory_top":
        state["placement_config"]["tie_back_liner_lap_m"] = 0.
    elif fault == "missing_workstring":
        state["hardware_table"] = state["hardware_table"].loc[lambda f: f["Description"] != "Drill Pipes"]
    elif fault == "missing_receiver":
        state["hardware_table"] = state["hardware_table"].loc[lambda f: f["Description"] != "Previous Liner"]
    elif fault == "ambiguous_receiver":
        state["hardware_table"] = pd.concat([state["hardware_table"], state["hardware_table"].iloc[[2]]], ignore_index=True)
    elif fault == "missing_host":
        state["placement_config"].pop("host_row")
    elif fault == "stale_host":
        state["placement_config"]["host_row"] = "obsolete-token"
    else:
        extra = hardware(("Previous Casing", "900", "13 3/8", 12.347))
        state["hardware_table"] = pd.concat([state["hardware_table"], extra], ignore_index=True)
        state["placement_config"]["host_row"] = next(token for token, row in hardware_choices(
            state["hardware_table"], {"Previous Casing"}).items() if row["depth"] == 900.)
    before = pickle.dumps(state)
    for consumer in (chart.resolve_chart_geometry, centralizer_adapter.to_engine_geometry,
                     lambda s: pumping_simulation._geometry(s, "tieback")):
        with pytest.raises(ValueError):
            consumer(state)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize("top,interval", [(0., True), (0., False), (100., True), (100., False)])
def test_explicit_tieback_top_interval_or_metadata_roundtrips_without_inference(top, interval):
    from test_audit_regressions import round_trip
    state = synthetic_tieback(top=top, explicit=interval)
    if not interval:
        state["placement_config"]["tie_back_liner_lap_m"] = top
    # Target row tokens are based on the actual scalar/interval input.
    restored = round_trip(state)
    pd.testing.assert_frame_equal(restored["hardware_table"], state["hardware_table"], check_dtype=False)
    for source in (state, restored):
        active = chart.resolve_chart_geometry(source)["active_string"]
        assert next(s for s in active if s["description"] == "Tie Back")["top_md"] == top
        assert centralizer_adapter.to_engine_geometry(source)["wellbore"]["string_top"] == top


@pytest.mark.parametrize("fault", ["running_fit", "historical_fit", "duplicate", "missing_hole"])
def test_nested_invalid_physical_geometry_remains_fail_closed_without_mutation(fault):
    state = reference_casing()
    if fault == "running_fit":
        state["hardware_table"].at[2, "ID (in)"] = 9.
    elif fault == "historical_fit":
        state["hardware_table"].at[1, "ID (in)"] = 13.
    elif fault == "duplicate":
        state["hardware_table"] = pd.concat([state["hardware_table"], state["hardware_table"].iloc[[2]]], ignore_index=True)
    else:
        state["hardware_table"] = state["hardware_table"].iloc[:-1]
    before = pickle.dumps(state)
    with pytest.raises(ValueError):
        chart.resolve_chart_geometry(state)
    assert pickle.dumps(state) == before


def test_multiple_effective_cased_ids_remain_valid_chart_but_unrepresentable_centralizer():
    state = reference_casing()
    state["hardware_table"].at[1, "MD (m)"] = "500"
    # Inner 13-3/8 shoe at400, then the measured outer20 wall through500.
    state["hardware_table"].at[3, "MD (m)"] = "500-1970"
    assert boundary(chart.resolve_chart_geometry(state)) == [
        (0., 400., 12.347), (400., 500., 18.730), (500., 1970., 12.250)]
    with pytest.raises(ValueError, match="scalar ID"):
        centralizer_adapter.to_engine_geometry(state)


def test_csg7_immediate_host_comes_from_measured_hardware_not_job_taxonomy():
    state = project('CSG 7"', hardware(
        ("Casing", "2500", "7", 6.), ("Previous Casing", "53", "20", 18.730),
        ("Previous Casing", "400", "13 3/8", 12.347),
        ("Previous Casing", "1970", "9 5/8", 8.535),
        ("Open Hole Size", "1970-2500", "8.5", 8.5)), 2500.)
    assert boundary(chart.resolve_chart_geometry(state)) == [(0., 1970., 8.535), (1970., 2500., 8.5)]


@pytest.mark.parametrize("kind", ["casing", "tieback"])
def test_schematic_retains_physical_history_and_exact_active_top(kind):
    import well_schematic_adapter as schematic
    state = reference_casing() if kind == "casing" else synthetic_tieback()
    payload = schematic.prepare_schematic(state)
    if kind == "casing":
        casings = {(s["size_in"], s["top_md"], s["shoe_md"]) for s in payload["casings"]}
        assert {(20., 0., 53.), (13.375, 0., 400.), (9.625, 0., 1970.)} == casings
        assert payload["open_holes"][0]["top_md"] == 400.
    else:
        active = next(s for s in payload["casings"] if s["type"] == "tieback")
        receiver = next(s for s in payload["casings"] if s["type"] == "liner")
        assert (active["top_md"], active["shoe_md"]) == (100., 700.)
        assert (receiver["top_md"], receiver["shoe_md"]) == (700., 1200.)


def test_explicit_top_is_consumed_by_pumping_signature_even_with_scalar_md():
    state = synthetic_tieback(explicit=False)
    state["placement_config"]["tie_back_liner_lap_m"] = 100.
    before = pumping_simulation.source_signature(state)
    state["placement_config"]["tie_back_liner_lap_m"] = 101.
    assert pumping_simulation.source_signature(state) != before


def test_schematic_cannot_disagree_with_running_restriction_above_liner_hanger():
    import well_schematic_adapter as schematic
    from test_uat_round9b_geometry import state_for
    state = state_for("liner")
    state["placement_config"]["target_row"] = next(iter(hardware_choices(state["hardware_table"], {"Liner"})))
    host = state["hardware_table"].loc[lambda f: f["Description"] == "Previous Casing"].iloc[0].to_dict()
    host.update({"MD (m)": "100", "ID (in)": 6.5})
    state["hardware_table"] = pd.concat([pd.DataFrame([host]), state["hardware_table"]], ignore_index=True)
    with pytest.raises(ValueError, match="pass|restriction|fit"):
        schematic.prepare_schematic(state)


@pytest.mark.parametrize("kind", ["reference", "liner7", "liner5", "tieback7", "tieback5"])
@pytest.mark.parametrize("physics", ["static", "dynamic"])
def test_scalar_representable_measured_paths_execute_real_frozen_solver(kind, physics):
    from centralizer_fixtures import execute_centralizer
    from test_uat_round9e_dynamic_solver import dynamic_state
    import phase_9_centralizer as phase9
    state = dynamic_state("casing", **{"Tail": 2., "Displacement Fluid": 2.})
    if kind == "reference":
        geometry = reference_casing()
    elif kind.startswith("liner"):
        size, inner = (7., 6.) if kind == "liner7" else (5., 4.)
        geometry = project(f'LNR {size:g}"', hardware(
            ("Drill Pipes", "400", str(size), inner), ("Liner Hanger", "400", str(size), inner),
            ("Liner", "400-1000", str(size), inner),
            ("Previous Casing", "500", "9 5/8", 8.535),
            ("Open Hole Size", "500-1000", "8.5", 8.5)), 1000.)
    else:
        geometry = synthetic_tieback()
        if kind == "tieback5":
            geometry["job_type"] = geometry["placement_config"]["job_type"] = 'TIE BACK LNR 5"'
            selected = geometry["hardware_table"]["Description"].isin(("Tie Back", "Drill Pipes", "Previous Liner"))
            geometry["hardware_table"].loc[selected, "Size (in)"] = "5"
            geometry["hardware_table"].loc[selected, "ID (in)"] = 4.
            geometry["placement_config"]["target_row"] = next(iter(hardware_choices(
                geometry["hardware_table"], {"Tie Back"})))
    state.update(geometry)
    if kind.startswith("tieback"):
        resolved = chart.resolve_chart_geometry(state)
        state["fluids_config"]["params"]["Tail"]["volume"] = (
            chart.interval_volume(resolved["capacity_segments"], 500., 700.) + resolved["shoe_track_bbl"])
    result = execute_centralizer(state, physics=physics)
    assert result["mode"] == "direct"
    assert result["zones"] and all(isinstance(z["count"], int) for z in result["zones"])
    assert phase9.result_is_current(state)
    expected_top = 400. if kind.startswith("liner") else 100. if kind.startswith("tieback") else 0.
    assert state["centralizer_config"]["zones"][0]["top_md"] == expected_top
    if kind.startswith("tieback"):
        selected = state["centralizer_config"]["zones"][0]
        generated = phase9.auto_populate(state)
        assert generated[0]["top_md"] == 100.
        assert generated[-1]["bottom_md"] == 700.
        state["centralizer_config"]["zones"] = [{**zone, "product_nr": selected["product_nr"],
            "custom_product_id": selected["custom_product_id"]} for zone in generated]
        assert phase9.execute(state)["zones"]
        assert phase9.result_is_current(state)


def test_reference_real_word_roundtrip_and_stale_admission(tmp_path):
    from io import BytesIO
    from docx import Document
    import test_audit_regressions as audit
    import project_state
    import phase_9_centralizer as phase9
    import centralizer_report
    from centralizer_fixtures import execute_centralizer
    case = audit.AuditRegressions()
    base = case.configured_app('CSG 9 5/8"').session_state.to_dict()
    base.update(reference_casing())
    app = case.app(audit.round_trip(base))
    case.phase(app, "phase7")
    next(b for b in app.button if b.key.startswith("_sync_btn_main_")).click().run()
    next(b for b in app.button if b.key.startswith("_confirm_lab_btn_main_")).click().run()
    case.healthy(app)
    execute_centralizer(app.session_state, physics="dynamic")
    case.export(app)
    data = app.session_state["_compiled_doc_bytes"]
    (tmp_path / "reference-nested-csg.docx").write_bytes(data)
    document = Document(BytesIO(data))
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    assert "Previous Casing" in cells and "12.347" in cells and "18.73" in cells
    assert len(document._element.body.xpath('.//wp:docPr[@descr="Well Schematic"]')) == 1
    assert boundary(app.session_state["_cement_chart_model"]) == [(0., 400., 12.347), (400., 1970., 12.250)]
    state = app.session_state.to_dict()
    assert phase9.result_is_current(state)
    # A measured outer-shell edit must stale the executed authority even if it
    # leaves the immediate annular boundary and analytical capacities unchanged.
    state["hardware_table"].at[1, "ID (in)"] = 18.729
    assert not phase9.result_is_current(state)
    pending = centralizer_report.prepare_report(state)
    assert pending["current"] is False and pending["analysis"] is None
    project_state.prepare_calculations(state)
    assert "_compiled_doc_bytes" not in state
    restored = audit.round_trip(state)
    assert not phase9.result_is_current(restored)
    pd.testing.assert_frame_equal(restored["hardware_table"], state["hardware_table"], check_dtype=False)
    # Valid physical wall steps can still be outside the scalar solver domain.
    unsupported = deepcopy(state)
    unsupported["hardware_table"].at[1, "MD (m)"] = "500"
    unsupported["hardware_table"].at[3, "MD (m)"] = "500-1970"
    assert len(boundary(chart.resolve_chart_geometry(unsupported))) == 3
    assert not phase9.result_is_current(unsupported)
    from unittest.mock import patch
    import phase_10_procedure as report
    with patch.object(report.st, "session_state", unsupported):
        pending = report.build_master_context()["centralizer_report"]
        assert pending["current"] is False and pending["analysis"] is None
    assert "_compiled_doc_bytes" not in unsupported


def test_interior_landing_retains_receiver_as_wall_above_tie_in_only():
    state = synthetic_tieback()
    state["hardware_table"].loc[2, ["MD (m)", "Size (in)", "ID (in)"]] = ["400-1200", "8", 7.5]
    assert boundary(chart.resolve_chart_geometry(state)) == [(0., 400., 8.535), (400., 700., 7.5)]
    geometry, _ = pumping_simulation._geometry(state, "tieback")
    assert [(s.z_top, s.z_bot, s.do_in, s.di_in) for s in geometry.ann_sections] == [
        (0., 400., 8.535, 7.), (400., 700., 7.5, 7.),
        (700., 800., 8.535, 8.), (800., 1200., 8.5, 8.)]
    with pytest.raises(ValueError, match="scalar ID"):
        centralizer_adapter.to_engine_geometry(state)


@pytest.mark.parametrize("row,value", [(0, "-9.625"), (1, "-20")])
def test_negative_running_or_historical_od_cannot_become_positive_fractional_size(row, value):
    state = reference_casing()
    state["hardware_table"].at[row, "Size (in)"] = value
    state["placement_config"]["target_row"] = next(iter(hardware_choices(state["hardware_table"], {"Casing"})))
    with pytest.raises(ValueError, match="positive|greater than zero"):
        chart.resolve_chart_geometry(state)


def test_schematic_rejects_active_body_larger_than_measured_open_hole():
    import well_schematic_adapter as schematic
    from test_uat_round9b_geometry import state_for
    state = state_for("liner")
    state["placement_config"]["target_row"] = next(iter(hardware_choices(state["hardware_table"], {"Liner"})))
    state["hardware_table"].loc[state["hardware_table"]["Description"] == "Open Hole Size", ["Size (in)", "ID (in)"]] = ["6.5", 6.5]
    with pytest.raises(ValueError, match="pass|fit|restriction"):
        schematic.prepare_schematic(state)


def test_deepest_liner_top_cannot_overrule_a_different_innermost_receiving_bore():
    state = project('TIE BACK LNR 5"', hardware(
        ("Tie Back", "100-700", "5", 4.), ("Drill Pipes", "100", "5", 4.),
        ("Previous Casing", "1000", "13 3/8", 12.25),
        ("Previous Liner", "100-1200", "7", 6.),
        ("Previous Liner", "200-1100", "9 5/8", 8.535),
        ("Open Hole Size", "1100-1200", "12.25", 12.25)), 1200.)
    state["placement_config"]["host_row"] = next(token for token, row in hardware_choices(
        state["hardware_table"], {"Previous Liner"}).items() if row["size"] == "7")
    with pytest.raises(ValueError, match="receiving.*(ambiguous|innermost)"):
        chart.resolve_chart_geometry(state)


def test_protected_geometry_engines_catalog_template_and_negative_mutation():
    import hashlib
    from pathlib import Path
    expected = {
        "centralizer_optimizer_engine.py": "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9",
        "cement_charts_engine.py": "68b275c0c3fd0e804a926d39e1123b451f7e22b2c5aad31f6d0ab3e8236709d4",
        "fluids_charts_module_v1_4_2.py": "ceaaff1311b241c8793fc65b0004a8ca28bef463d93db0957d9b650522bdc5ea",
        "ds_cent_products.json": "837010c1a67a7a9252317f4b2e9b8f08b29f39f431cc8e45cfcc5eb6c94a1329",
        "master_template.docx": "a1128b0e9352e1dd7c8768eecc9335c50858356cee80ed33c0ec275e26c4d08b",
    }
    root = Path(__file__).resolve().parents[1]
    for name, digest in expected.items():
        original = (root / name).read_bytes()
        assert hashlib.sha256(original).hexdigest() == digest
        changed = bytes([original[0] ^ 1]) + original[1:]
        assert hashlib.sha256(changed).hexdigest() != digest


@pytest.mark.parametrize("field", ["Weight (ppf)", "Joint (m)"])
def test_unused_historical_mechanical_metadata_does_not_retire_current_solver(field):
    from test_uat_round9f_phase9 import configured
    import phase_9_centralizer as phase9
    catalog = centralizer_adapter.load_official_catalog()
    state = configured(catalog)
    phase9.execute(state, catalog)
    geometry = centralizer_adapter.to_engine_geometry(state)
    historical = state["hardware_table"]["Description"] == "Previous Casing"
    state["hardware_table"].loc[historical, field] = 42.
    assert centralizer_adapter.to_engine_geometry(state) == geometry
    assert phase9.result_is_current(state, catalog)


@pytest.mark.parametrize("row", [0, 2])
def test_installed_and_running_tubular_id_equal_to_od_is_not_physical(row):
    from engineering_tools import parse_fractional_size
    state = reference_casing()
    state["hardware_table"].at[row, "ID (in)"] = parse_fractional_size(state["hardware_table"].at[row, "Size (in)"])
    with pytest.raises(ValueError, match="ID"):
        chart.resolve_chart_geometry(state)


@pytest.mark.parametrize("source", ["scalar", "unrelated_interval", "earlier_interval"])
def test_c1_selected_receiver_requires_its_own_source_interval_at_tie_in(source):
    from test_uat_round11a_schematic import tieback_state
    import well_schematic_adapter as schematic
    state = tieback_state()
    table = state["hardware_table"]
    if source == "unrelated_interval":
        # A real outer liner has an explicit interval, but cannot authorize the
        # actual inner scalar receiver selected at the 2500-m tie-in.
        extra = table.iloc[2].to_dict()
        extra.update({"MD (m)": "2400-3500", "Size (in)": "8", "ID (in)": 7.5})
        # Synthetic owner-consistent hanger for the additional 8-inch liner.
        hanger = {**extra, "Description": "Previous Liner Hanger", "MD (m)": "2400"}
        state["hardware_table"] = pd.concat([table, pd.DataFrame([extra, hanger])], ignore_index=True)
    elif source == "earlier_interval":
        # Even an explicit section of the SAME string cannot authorize a later
        # endpoint-only section spanning the tie-in. Physical geometry is valid.
        table.loc[2, ["Size (in)", "ID (in)"]] = ["8", 7.5]
        table.loc[4, ["MD (m)", "Size (in)", "ID (in)"]] = ["2000", "8", 7.5]
        first = table.iloc[2].to_dict()
        first["MD (m)"] = "2000-2400"
        state["hardware_table"] = pd.concat([table.iloc[:2], pd.DataFrame([first]),
                                              table.iloc[2:]], ignore_index=True)
    before = pickle.dumps(state)
    chart.resolve_chart_geometry(state)
    schematic.prepare_schematic(state)
    with pytest.raises(ValueError, match="explicit old-liner interval"):
        pumping_simulation.prepare_pumping_simulation(state)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize("continuation", ["single", "endpoint_section", "tapered_section"])
def test_c1_explicit_receiver_preserves_measured_multisection_flow_and_json(continuation):
    from test_uat_round11a_schematic import tieback_state
    from test_audit_regressions import round_trip
    from phase_9_centralizer import new_config
    state = tieback_state(True)
    # The old hydraulic-only fixture omits the persisted config's input fields.
    state["centralizer_config"] = {**new_config(), **state["centralizer_config"]}
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": 1000., "Burst (psi)": 2000.})
    expected = [(0., 2500., 6., 7.), (2500., 4000., 6.276, 7.)]
    if continuation != "single":
        table = state["hardware_table"]
        table.at[2, "MD (m)"] = "2500-3300"
        row = table.iloc[2].to_dict()
        row["MD (m)"] = "4000" if continuation == "endpoint_section" else "3300-4000"
        if continuation == "tapered_section":
            row.update({"Size (in)": "6.5", "ID (in)": 5.75})
        state["hardware_table"] = pd.concat([table, pd.DataFrame([row])], ignore_index=True)
        expected = [(0., 2500., 6., 7.), (2500., 3300., 6.276, 7.),
                    (3300., 4000., row["ID (in)"], float(row["Size (in)"]))]
    before = pickle.dumps(state)
    signature = pumping_simulation.source_signature(state)
    for current in (state, round_trip(state)):
        snapshot = pickle.dumps(current)
        geometry = pumping_simulation.prepare_pumping_simulation(current)["inputs"]["geometry"]
        assert [(s.z_top, s.z_bot, s.id_in, s.od_in) for s in geometry.pipe_sections] == expected
        assert geometry.track_depth_m == 2500. and geometry.td_m == 4000.
        assert [(s.z_top, s.z_bot, s.do_in, s.di_in) for s in geometry.ann_sections] == (
            [(0., 3000., 8.535, 7.), (3000., 4000., 8.5, 7.)]
            if continuation != "tapered_section" else
            [(0., 3000., 8.535, 7.), (3000., 3300., 8.5, 7.), (3300., 4000., 8.5, 6.5)])
        assert pumping_simulation.source_signature(current) == signature
        assert pickle.dumps(current) == snapshot
    assert pickle.dumps(state) == before


def test_c1_loss_of_explicit_receiver_blocks_export_and_retires_compiled_document():
    from test_uat_round10a_pumping_simulation import program_state
    from test_audit_regressions import AuditRegressions
    from centralizer_fixtures import execute_centralizer
    import project_state
    import phase_10_procedure as report
    from unittest.mock import patch
    case = AuditRegressions()
    app = case.configured_app('TIE BACK LNR 7"')
    source = program_state("tieback")
    for column in ("Collapse (psi)", "Burst (psi)"):
        source["hardware_table"][column] = app.session_state["hardware_table"].iloc[0][column]
    for key in ("hardware_table", "placement_config"):
        app.session_state[key] = deepcopy(source[key])
    execute_centralizer(app.session_state)
    state = app.session_state.to_dict()
    assert project_state.prepare_calculations(state) == []
    old_signature = pumping_simulation.source_signature(state)
    # The existing interval is 400-1000; only its source authority is removed.
    table = state["hardware_table"]
    hanger = {**table.iloc[2].to_dict(), "Description": "Previous Liner Hanger", "MD (m)": "400"}
    table.at[2, "MD (m)"] = "1000"
    state["hardware_table"] = pd.concat([table, pd.DataFrame([hanger])], ignore_index=True)
    assert pumping_simulation.source_signature(state) != old_signature
    # Sentinel document bytes exercise invalidation, not successful admission.
    state.update(_compiled_doc_bytes=b"old", _compiled_doc_filename="old.docx", _compiled_doc_signature="old")
    issues = project_state.prepare_calculations(state)
    assert any("Pumping Simulation" in issue and "explicit old-liner interval" in issue for issue in issues), issues
    assert not any(key.startswith("_compiled_doc_") for key in state)
    with patch.object(report.st, "session_state", state):
        with pytest.raises(ValueError, match="explicit old-liner interval"):
            report.build_master_context()


@pytest.mark.parametrize("both_hangers", [False, True])
def test_c2_nested_receiver_drawing_is_independent_of_hydraulic_admission(both_hangers):
    from test_uat_round11a_schematic import tieback_state
    from test_audit_regressions import round_trip
    from phase_9_centralizer import new_config
    from unittest.mock import patch
    import well_schematic_adapter as schematic
    state = tieback_state()
    state["centralizer_config"] = {**new_config(), **state["centralizer_config"]}
    # Synthetic mechanical prerequisites for the real project JSON schema.
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": 1000., "Burst (psi)": 2000.})
    table = state["hardware_table"]
    # Explicitly synthetic outer liner/hanger, not owner field measurements.
    outer = {**table.iloc[2].to_dict(), "MD (m)": "2400-3500", "Size (in)": "8", "ID (in)": 7.5}
    extra = [outer]
    if both_hangers:
        extra.append({**outer, "Description": "Previous Liner Hanger", "MD (m)": "2400"})
    state["hardware_table"] = pd.concat([table, pd.DataFrame(extra)], ignore_index=True)
    before = pickle.dumps(state)
    interval = deepcopy(state)
    interval["hardware_table"].at[2, "MD (m)"] = "2500-4000"
    payload = schematic.prepare_schematic(state)
    assert payload == schematic.prepare_schematic(interval)
    tb = payload["casings"][payload["current_job"]["target_index"]]
    receiver = payload["casings"][tb["landing_liner_index"]]
    assert (tb["top_md"], tb["shoe_md"], receiver["size_in"],
            receiver["top_md"], receiver["shoe_md"]) == (0., 2500., 7., 2500., 4000.)
    hole = payload["open_holes"][0]
    # Drilled bore originates at the casing shoe, not the outer liner's3500-m
    # installed annular-wall transition (whose7.5-inch bore cannot drill8.5in).
    assert (hole["top_md"], hole["bottom_md"], hole["hole_size_in"]) == (3000., 4000., 8.5)
    for source in (state, round_trip(state), interval, round_trip(interval)):
        snapshot = pickle.dumps(source)
        with patch.object(pumping_simulation, "_geometry", side_effect=AssertionError("Schematic called Pumping")), \
             patch.object(pumping_simulation, "_tieback_paths", side_effect=AssertionError("Schematic called Pumping")):
            assert schematic.prepare_schematic(source) == payload
        assert pickle.dumps(source) == snapshot
    with pytest.raises(ValueError, match="explicit old-liner interval"):
        pumping_simulation.prepare_pumping_simulation(state)
    assert pumping_simulation.prepare_pumping_simulation(interval)["inputs"]["geometry"].td_m == 4000.
    assert pickle.dumps(state) == before


R15A_INITIAL = [('CSG 30"', 30., 36.), ('CSG 24"', 24., 28.),
                ('CSG 20"', 20., 26.), ('CSG 18 5/8"', 18.625, 22.)]


def initial_casing(job, size, hole, previous=False):
    rows = [('Casing', '150', str(size), size-1.)]
    if previous:
        rows.append(('Previous Casing', '50', str(hole+2.), hole+1.))
    rows.append(('Open Hole Size', '50-150' if previous else '0-150', str(hole), hole))
    return project(job, hardware(*rows), 150.)


@pytest.mark.parametrize('job,size,hole', R15A_INITIAL)
def test_r15a_first_casing_uses_explicit_surface_hole(job, size, hole):
    state = initial_casing(job, size, hole)
    before = pickle.dumps(state)
    geom = chart.resolve_chart_geometry(state)
    assert boundary(geom) == [(0., 150., hole)]
    expected = math.pi/4*(hole**2-size**2)/144/.3048/BBL_TO_CUFT
    assert geom['capacity_segments'] == [dict(top_md=0.,bottom_md=150.,
        nominal_bbl_per_m=expected,bbl_per_m=expected,kind='open_hole')]
    assert chart.interval_volume(geom['capacity_segments'],0.,150.) == pytest.approx(150.*expected)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize('job,size,hole', R15A_INITIAL)
def test_r15a_initial_casing_retains_physical_previous_path(job, size, hole):
    state=initial_casing(job,size,hole,previous=True)
    geometry=chart.resolve_chart_geometry(state)
    assert boundary(geometry)==[(0.,50.,hole+1.),(50.,150.,hole)]
    assert [v['kind'] for v in geometry['capacity_segments']]==['cased','open_hole']


@pytest.mark.parametrize('fault', ['missing','gap','overlap','undersized','equal','bit','id_missing','duplicate_string'])
def test_r15a_initial_casing_invalid_hole_or_string_never_fabricates_wall(fault):
    state=initial_casing('CSG 20"',20.,26.)
    t=state['hardware_table']
    if fault=='missing':state['hardware_table']=t.iloc[:1].copy()
    elif fault in ('gap','overlap'):
        t.at[1,'MD (m)']='0-70'
        row=t.iloc[1].to_dict();row['MD (m)']='80-150' if fault=='gap' else '60-150'
        state['hardware_table']=pd.concat([t,pd.DataFrame([row])],ignore_index=True)
    elif fault in ('undersized','equal'):
        t.loc[1,['Size (in)','ID (in)']]=['19' if fault=='undersized' else '20',19. if fault=='undersized' else 20.]
    elif fault=='bit':t.at[1,'ID (in)']=25.
    elif fault=='id_missing':t.at[1,'ID (in)']=None
    else:state['hardware_table']=pd.concat([t,t.iloc[:1]],ignore_index=True)
    before=pickle.dumps(state)
    with pytest.raises(ValueError):chart.resolve_chart_geometry(state)
    assert pickle.dumps(state)==before


def test_r15a_initial_measured_sections_excess_and_placement_share_capacity():
    state=initial_casing('CSG 20"',20.,26.)
    t=state['hardware_table'];t.at[1,'MD (m)']='0-70'
    row=t.iloc[1].to_dict();row['MD (m)']='70-150'
    state['hardware_table']=pd.concat([t,pd.DataFrame([row])],ignore_index=True)
    state['placement_config'].update(chart_excess_mode='apply',excess_csg_oh_pct=20.)
    geom=chart.resolve_chart_geometry(state)
    expected=math.pi/4*(26.**2-20.**2)/144/.3048/BBL_TO_CUFT*1.2
    assert chart.interval_volume(geom['capacity_segments'],0.,150.)==pytest.approx(expected*150.)
    state['fluids_config']={'active':['Main'],'params':{'Main':{'volume':geom['shoe_track_bbl']+expected*50.,'density':'118'}}}
    cement=chart.resolve_cement_placement(state,geom)[0]
    assert cement['top_md']==pytest.approx(100.)
    assert cement['in_well_bbl']+cement['shoe_track_bbl']==pytest.approx(cement['entered_bbl'])


@pytest.mark.parametrize('kind',['liner','tieback'])
def test_r15a_measured_hole_cannot_replace_liner_or_tieback_history(kind):
    if kind=='liner':
        state=project('LNR 7"',hardware(('Drill Pipes','50','5',4.),('Liner Hanger','50','7',6.),
            ('Liner','50-150','7',6.),('Open Hole Size','0-150','9',9.)),150.)
    else:
        state=project('TIE BACK LNR 7"',hardware(('Tie Back','0-150','7',6.),('Open Hole Size','0-150','9',9.)),150.)
    with pytest.raises(ValueError,match='Previous|host|Liner'):chart.resolve_chart_geometry(state)


@pytest.fixture(scope='module')
def r15a_report_source():
    import test_audit_regressions as audit
    cache={}
    def get(job):
        if job not in cache:
            cache[job]=audit.round_trip(audit.AuditRegressions().configured_app(job).session_state.to_dict())
        return deepcopy(cache[job])
    return get


@pytest.mark.parametrize('job,size,hole',R15A_INITIAL)
@pytest.mark.parametrize('previous',[False,True])
def test_r15a_actual_first_casing_word_and_json(r15a_report_source,job,size,hole,previous,tmp_path):
    import json
    from io import BytesIO
    from docx import Document
    import project_state as ps
    import test_audit_regressions as audit
    import well_schematic_adapter as schematic
    import well_schematic_engine as renderer
    from test_uat_round11a_schematic import schematic_picture
    case=audit.AuditRegressions()
    source=r15a_report_source(job)
    source.update(initial_casing(job,size,hole,previous))
    source.update(geo_md=150.,geo_tvd=150.)
    source['hardware_editor_draft']=source['hardware_table'].copy(deep=True)
    source['fluids_config']['params']['Main']['volume']=1000.  # Synthetic measured large-bore job, above shoe-track volume.
    ps.refresh_well_derived(source)
    source=audit.round_trip(source)
    geom=chart.resolve_chart_geometry(source)
    assert chart.resolve_cement_placement(source,geom)[0]['shoe_track_bbl']==geom['shoe_track_bbl']
    app=case.app(source)
    case.phase(app,'phase7')
    keep=[b for b in app.button if b.label=='Keep reviewed lab entries']
    if keep:keep[0].click().run()
    confirm=[b for b in app.button if b.label=='Confirm measured lab results']
    for button in confirm:
        assert not button.disabled
        app.button(key=button.key).click().run()
    assert ps.prepare_calculations(app.session_state.to_dict())==[]
    physical=deepcopy((app.session_state['hardware_table'],app.session_state['well_geometry'],
                       app.session_state['placement_config'],app.session_state['fluids_config']))
    case.export(app)
    data=app.session_state['_compiled_doc_bytes'];doc=Document(BytesIO(data))
    assert doc._element.xpath('.//wp:docPr[@descr="Static Well Security and Fluid Sequence"]')
    assert not doc._element.xpath('.//wp:docPr[@descr="Pumping Simulation Charts"]')
    _,image=schematic_picture(doc)
    (tmp_path/'initial-casing.docx').write_bytes(data);(tmp_path/'embedded-schematic.png').write_bytes(image)
    pd.testing.assert_frame_equal(app.session_state['hardware_table'],physical[0])
    assert ps.fingerprint((app.session_state['well_geometry'],app.session_state['placement_config'],app.session_state['fluids_config']))==ps.fingerprint(physical[1:])
    saved=audit.round_trip(app.session_state.to_dict())
    assert chart.resolve_chart_geometry(saved)==geom
    payload=schematic.prepare_schematic(saved)
    assert renderer.resolve_depth_axis(payload)==(165.,[0.,82.5,165.])
    assert payload['casings'][-1]['shoe_md']==150.
    assert payload['open_holes'][0]['hole_size_in']==hole
    (tmp_path/'geometry-and-axis.json').write_text(json.dumps({'job':job,'previous':previous,'geometry':geom,
        'axis':[165.,[0.,82.5,165.]],'payload':payload},indent=2))


# BUG-01: measured geometry and explicitly synthetic solver/report prerequisites.
def bug01_dq19():
    rows = [
        ('Previous Casing', '253.0', '18 5/8', 17.755, 87.5),
        ('Previous Casing', '2190', '13 3/8', 12.347, 72.),
        ('Previous Casing', '2800', '9 5/8', 8.535, 53.5),
        ('Previous Liner Hanger', '2650', '7', 6.094, 32.),
        ('Previous Liner', '3839', '7', 6.094, 32.),
        ('Drill Pipes', '3419', '3 1/2', 2.764, 18.),
        ('Liner Hanger', '3419', '5', 4.276, 18.),
        ('Liner', '4500', '5', 4.276, 18.),
        ('Open Hole Size', '4550', '6', 6., 0.),
    ]
    frame = pd.DataFrame([{'Description': desc, 'MD (m)': md, 'Size (in)': size,
        'ID (in)': inner, 'Joint (m)': 0. if desc == 'Open Hole Size' else 12.2,
        'Weight (ppf)': weight, 'Grade': '-', 'Collapse (psi)': 0., 'Burst (psi)': 0.}
        for desc, md, size, inner, weight in rows])
    state = project('LNR 5"', frame, 4550.)
    assert state['placement_config']['target_row'] == '0f925f04a60228e7d2a10b2f1473a6d997896c578e2de2d05b5a96366d0f3ab6'
    state['centralizer_config'] = {'version': 1, 'physics_mode': 'static', 'placement_mode': 'optimize',
        'custom_products': [], 'aux_rheology': {}, 'zones': [
            {'top_md': top, 'bottom_md': bottom, 'density': '1/4', 'target_standoff_pct': 67.,
             'product_nr': None, 'custom_product_id': None} for top, bottom in ((3419., 3839.), (3839., 4500.))]}
    return state


def bug01_geometry_case(job):
    if job == 'LNR 5"':
        return bug01_dq19()
    if job in ('CSG 13 3/8"', 'CSG 9 5/8"'):
        od, inner, host, host_id, hole = ((13.375, 12.25, 20., 18.73, 17.5)
            if job == 'CSG 13 3/8"' else (9.625, 8.535, 13.375, 12.347, 12.25))
        return project(job, hardware(('Previous Casing', '400', str(host), host_id),
            ('Casing', '1200', str(od), inner), ('Open Hole Size', '400-1200', str(hole), hole)), 1200.)
    if job == 'LNR 7"':
        return project(job, hardware(('Previous Casing', '700', '9 5/8', 8.535),
            ('Drill Pipes', '400', '3 1/2', 2.764), ('Liner Hanger', '400', '7', 6.094),
            ('Liner', '1200', '7', 6.094), ('Open Hole Size', '700-1200', '8.5', 8.5)), 1200.)
    if job == 'LNR 4 1/2"':
        return project(job, hardware(('Previous Casing', '300', '9 5/8', 8.535),
            ('Previous Liner', '200-700', '7', 6.094), ('Drill Pipes', '400', '3 1/2', 2.764),
            ('Liner Hanger', '400', '4 1/2', 4.), ('Liner', '1200', '4 1/2', 4.),
            ('Open Hole Size', '700-1200', '6', 6.)), 1200.)
    od, inner = {'TIE BACK LNR 7"': ('7', 6.094), 'TIE BACK LNR 5"': ('5', 4.276),
                 'TIE BACK LNR 4 1/2"': ('4 1/2', 4.)}[job]
    rows = [('Previous Casing', '1100' if od == '7' else '300', '9 5/8', 8.535)]
    if od != '7':
        rows.append(('Previous Liner', '100-1100', '7', 6.094))
    host_index = len(rows)-1
    rows += [('Previous Liner', '700-1200', od, inner), ('Drill Pipes', '200', '3 1/2', 2.764),
             ('Tie Back', '200-700', od, inner),
             ('Open Hole Size', '1100-1200', '8.5' if od == '7' else '6', 8.5 if od == '7' else 6.)]
    state = project(job, hardware(*rows), 1200.)
    state['placement_config']['host_row'] = next(iter(hardware_choices(
        state['hardware_table'].iloc[[host_index]], {'Previous Casing', 'Previous Liner'})))
    return state


def test_bug01_dq19_active_wall_ignores_only_upstream_cased_ids():
    state = bug01_dq19()
    before = pickle.dumps(state)
    assert boundary(chart.resolve_chart_geometry(state)) == [
        (0., 2650., 8.535), (2650., 3839., 6.094), (3839., 4500., 6.)]
    result = centralizer_adapter.to_engine_geometry(state)
    assert result['wellbore'] == {'prev_casing_id': 6.094*.0254, 'hole_size': 6.*.0254,
        'prev_shoe_depth': 3839., 'open_hole_top': 3839., 'open_hole_bottom': 4500.,
        'string_top': 3419., 'string_shoe': 4500.}
    assert (result['wellbore']['prev_casing_id']-result['casing']['od'])/2/.0254 == pytest.approx(.547)
    assert (result['wellbore']['hole_size']-result['casing']['od'])/2/.0254 == pytest.approx(.5)
    assert pickle.dumps(state) == before


def test_bug01_tieback_four_half_is_an_explicit_new_capability():
    import materials_db as db
    job = 'TIE BACK LNR 4 1/2"'
    assert job in db.JOB_TYPES
    assert chart.chart_job_kind(job) == 'tieback'
    result = centralizer_adapter.to_engine_geometry(bug01_geometry_case(job))
    assert result['casing']['od'] == 4.5*.0254
    assert result['wellbore']['prev_casing_id'] == result['wellbore']['hole_size'] == 6.094*.0254
    assert result['wellbore']['prev_shoe_depth'] == result['wellbore']['string_shoe'] == 700.


BUG01_JOBS = ('CSG 13 3/8"', 'CSG 9 5/8"', 'LNR 7"', 'LNR 5"', 'LNR 4 1/2"',
              'TIE BACK LNR 7"', 'TIE BACK LNR 5"', 'TIE BACK LNR 4 1/2"')


def bug01_solver_state(job):
    import materials_db as db
    import phase_9_centralizer as phase9
    import project_state as ps
    import test_audit_regressions as audit
    state = bug01_geometry_case(job)
    # All fluid, rheology and product prerequisites here are explicitly synthetic;
    # only bug01_dq19's Hardware/target are the sanitized owner measurements.
    state.update(mud_density='80', plastic_viscosity='16', yield_point='10',
        well_data={'mud_density': '80', 'plastic_viscosity': '16', 'yield_point': '10'},
        fluids_config={'active': ['Main', 'Displacement Fluid'], 'params': {
            name: {'volume': 8., 'density': '118' if name == 'Main' else '80',
                   'pump_rate': '4', 'material_name': db.DEFAULT_MATERIAL_NAMES[name]}
            for name in ('Main', 'Displacement Fluid')}},
        lab_qc_params={'Main': {'rheology': audit.valid_export_rheology_fixture()}})
    ps.refresh_fluids(state)
    geometry = centralizer_adapter.to_engine_geometry(state)
    od = geometry['casing']['od']/.0254
    catalog = centralizer_adapter.load_official_catalog()
    product = next(p for p in centralizer_adapter.filter_official_products(catalog, od)
                   if p['kind'] == 'rigid' and od < p['max_od_in'] <= min(
                       geometry['wellbore']['prev_casing_id'], geometry['wellbore']['hole_size'])/.0254)
    top, shoe, seat = (geometry['wellbore'][k] for k in ('string_top','string_shoe','prev_shoe_depth'))
    bounds = [top, seat, shoe] if top < seat < shoe else [top, shoe]
    config = phase9.new_config()
    config['zones'] = [{'top_md': a, 'bottom_md': b, 'density': '1/4', 'target_standoff_pct': 67.,
                       'product_nr': product['nr'], 'custom_product_id': None} for a,b in zip(bounds,bounds[1:])]
    state['centralizer_config'] = config
    return state


@pytest.mark.parametrize('job', BUG01_JOBS)
@pytest.mark.parametrize('physics,mode', [('static','direct'),('static','optimize'),('dynamic','direct'),('dynamic','optimize')])
def test_bug01_eight_hardware_resolved_jobs_execute_all_frozen_modes(job, physics, mode):
    import hashlib
    from pathlib import Path
    import phase_9_centralizer as phase9
    import centralizer_optimizer_engine as engine
    import centralizer_report
    state = bug01_solver_state(job)
    state['centralizer_config'].update(physics_mode=physics, placement_mode=mode)
    geometry = chart.resolve_chart_geometry(state)
    source = pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')})
    snapshot = centralizer_adapter.build_fluid_snapshot(state)
    assert snapshot['capacity_bbl']['inside'] == pytest.approx(sum(
        (s['bottom_md']-s['top_md'])*chart._capacity(s['id_in']) for s in geometry['active_string']), rel=1e-14)
    assert snapshot['capacity_bbl']['annulus'] == chart.interval_volume(geometry['capacity_segments'], 0., geometry['shoe_md'])
    result = phase9.execute(state)
    assert result['mode'] == mode and result['profile']['centralizer_md']
    assert phase9.result_is_current(state)
    assert centralizer_report.prepare_report(state)['analysis'] is not None
    assert pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')}) == source
    payload = (centralizer_adapter.build_static_payload(state,state['centralizer_config']['zones'],centralizer_adapter.load_official_catalog())
        if physics == 'static' else centralizer_adapter.build_dynamic_payload(state,state['centralizer_config']['zones'],centralizer_adapter.load_official_catalog())['payload'])
    frozen = engine.compute_standoff_profile(payload) if mode == 'direct' else engine.optimize_placement(payload)
    assert result['profile'] == frozen
    assert hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest() == 'b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9'
    if 'TIE BACK' in job:
        assert all(s['description'] != 'Open Hole Size' for s in geometry['enclosing_string']
                   if s['bottom_md'] > 200.)
        assert payload['wellbore']['prev_shoe_depth'] == payload['wellbore']['string_shoe']
        assert payload['wellbore']['hole_size'] == payload['wellbore']['prev_casing_id']
        zones = phase9.auto_populate(state)
        assert zones and all(z['bottom_md'] <= 700. and z['product_nr'] is None for z in zones)
    # A source edit retires currentness even when it only changes upstream flow.
    previous = deepcopy(state)
    state['hardware_table'].loc[state['hardware_table']['Description']=='Previous Casing','ID (in)'] -= .001
    assert not phase9.result_is_current(state)
    assert centralizer_report.prepare_report(state)['current'] is False
    assert phase9.result_is_current(previous)


def test_bug01_dq19_null_products_stay_incomplete_after_geometry_fix():
    import phase_9_centralizer as phase9
    state = bug01_dq19()
    # No fabricated lab/product is needed to demonstrate the next real prerequisite.
    with pytest.raises(ValueError, match='select exactly one Official or Custom'):
        centralizer_adapter.build_static_payload(state,state['centralizer_config']['zones'],centralizer_adapter.load_official_catalog())
    assert not phase9.result_is_current(state)


@pytest.mark.parametrize('job', ['LNR 4 1/2"','LNR 5"','TIE BACK LNR 5"','TIE BACK LNR 4 1/2"'])
def test_bug01_upstream_restrictions_still_reject_deeper_body(job):
    state = bug01_geometry_case(job)
    # This restriction is above the active Top, yet the deeper OD must pass it.
    row = state['hardware_table'].index[state['hardware_table']['Description']=='Previous Casing'][0]
    state['hardware_table'].at[row,'ID (in)'] = 4.4
    with pytest.raises(ValueError, match='clearance|restriction|host|pass'):
        centralizer_adapter.to_engine_geometry(state)


@pytest.mark.parametrize('fault', ['missing_host','stale_host','short_host','receiver_missing','receiver_ambiguous','target','top','gap','duplicate','clearance'])
def test_bug01_tieback_new_job_physical_negatives_are_not_bypassed(fault):
    state = bug01_geometry_case('TIE BACK LNR 4 1/2"')
    if fault == 'receiver_missing':
        # Removing the inner receiver alone leaves the measured 7-inch liner
        # as a lawful receiver. Use a cased-host fixture with NO liner instead.
        state = bug01_geometry_case('TIE BACK LNR 7"')
    table = state['hardware_table']
    if fault == 'missing_host': state['placement_config'].pop('host_row')
    elif fault == 'stale_host': state['placement_config']['host_row'] = 'stale-token'
    elif fault == 'short_host': table.at[1,'MD (m)'] = '100-600'
    elif fault == 'receiver_missing': state['hardware_table'] = table.drop(index=1)
    elif fault == 'receiver_ambiguous': state['hardware_table'] = pd.concat([table,table.iloc[[2]]],ignore_index=True)
    elif fault == 'target': state['placement_config']['target_row'] = 'stale-token'
    elif fault == 'top': table.at[4,'MD (m)'] = '700'
    elif fault == 'gap': table.at[3,'MD (m)'] = '190'
    elif fault == 'duplicate': state['hardware_table'] = pd.concat([table,table.iloc[[1]]],ignore_index=True)
    else: table.at[1,'ID (in)'] = 4.5
    with pytest.raises(ValueError, match='host|Host|Top|target|Target|Previous|Liner|clearance|overlap|missing|continuous|receiving|restriction|pass|ambiguous'):
        centralizer_adapter.to_engine_geometry(state)


@pytest.fixture(scope='module')
def bug01_reviewed_report_base():
    import test_audit_regressions as audit
    # Real existing UI sequence: formulation, measured Fann/QC and explicit review.
    return audit.AuditRegressions().configured_app('CSG 9 5/8"').session_state.to_dict()


@pytest.mark.parametrize('job', BUG01_JOBS)
def test_bug01_actual_ui_restore_pumping_schematic_and_current_word(bug01_reviewed_report_base, job, tmp_path):
    import test_audit_regressions as audit
    import project_state as ps
    import phase_9_centralizer as phase9
    import phase_10_procedure as report
    import materials_db as db
    import well_schematic_adapter as schematic
    from test_uat_round10c_integration import save_project, restore_project, build
    from test_uat_round9g_centralizer_word import ix_region
    from docx import Document
    from io import BytesIO
    case = audit.AuditRegressions()
    app = case.app(deepcopy(bug01_reviewed_report_base))
    case.phase(app,'phase1')
    assert job in app.selectbox(key='_w_job_type').options
    app.selectbox(key='_w_job_type').set_value(job).run()
    case.healthy(app)
    assert app.session_state['doc_control']['request_description'] == ps.request_description_for_job(job)
    measured = bug01_geometry_case(job)
    for key in ('hardware_table','well_geometry','placement_config'):
        app.session_state[key] = deepcopy(measured[key])
    for name in ('Main','Displacement Fluid'):
        app.session_state['fluids_config']['params'][name]['volume'] = 8.
    app.session_state['cement_params']['Main'].update(top_mode='Not entered',top_depth=None,report_bottom_depth=None)
    case.phase(app,'phase2_3')
    case.phase(app,'phase5')
    case.phase(app,'phase7')
    sync = next((b for b in app.button if (b.key or '').startswith('_sync_btn_main_')),None)
    if sync is not None: sync.click().run()
    confirm = next(b for b in app.button if (b.key or '').startswith('_confirm_lab_btn_main_'))
    assert not confirm.disabled
    confirm.click().run()
    state = app.session_state.to_dict()
    assert ps.prepare_calculations(state) == []
    # Supply an explicit real catalog selection, not a fabricated current receipt.
    prerequisites = bug01_solver_state(job)
    state['centralizer_config'] = deepcopy(prerequisites['centralizer_config'])
    state['centralizer_config'].update(physics_mode='dynamic',placement_mode='direct')
    phase9.execute(state)
    assert phase9.result_is_current(state)
    source = pickle.dumps(state['hardware_table'])
    restored = restore_project(save_project(type('Project',(),{'session_state':state})()))
    assert restored.session_state['job_type'] == job
    pd.testing.assert_frame_equal(restored.session_state['hardware_table'],state['hardware_table'],check_dtype=False)
    assert not phase9.result_is_current(restored.session_state)
    assert not any(k.startswith('_compiled_doc_') for k in restored.session_state.to_dict())
    case.phase(restored,'phase9')
    restored.button(key='_centralizer_execute').click().run()
    case.healthy(restored)
    assert phase9.result_is_current(restored.session_state)
    assert [z['product_nr'] for z in restored.session_state['centralizer_config']['zones']] == [z['product_nr'] for z in state['centralizer_config']['zones']]
    drawing = schematic.prepare_schematic(restored.session_state)
    assert drawing['current_job']['type'] == chart.chart_job_kind(job)
    prepared = pumping_simulation.prepare_pumping_simulation(restored.session_state)
    assert prepared['applicable'] and prepared['inputs']['geometry'].track_depth_m == chart.resolve_chart_geometry(state)['shoe_md']
    if 'TIE BACK' in job:
        # The genuine hydraulic continuation goes below tie-in; it is not a
        # fabricated open-hole section in the active force solve.
        assert prepared['inputs']['geometry'].td_m == 1200.
        assert centralizer_adapter.to_engine_geometry(state)['wellbore']['prev_shoe_depth'] == 700.
    data = build(restored)
    assert phase9.result_is_current(restored.session_state)
    doc = Document(BytesIO(data));region = ix_region(doc)
    tables = [t for t in doc.tables if t._tbl in region]
    assert [len(t.rows) for t in tables] == [4,2+len(state['centralizer_config']['zones'])]
    assert tables[0].cell(3,1).text == f"{chart.resolve_chart_geometry(state)['shoe_md']:.1f} m"
    assert any(e.xpath('.//w:drawing') for e in region)
    assert any(c.text.strip() not in ('','-') for row in tables[1].rows[2:] for c in row.cells)
    assert len(region[-1].xpath('.//w:br[@w:type="page"]')) == 1
    assert restored.session_state['_compiled_doc_signature'] != ''
    assert pickle.dumps(state['hardware_table']) == source
    (tmp_path/'current-centralizer-report.docx').write_bytes(data)
    (tmp_path/'canonical-hardware.json').write_text(state['hardware_table'].to_json(orient='records'))
    if job == 'TIE BACK LNR 4 1/2"':
        assert restored.session_state['hole_size'] == db.DEFAULT_HOLE_SIZES[job] == '6"'
        assert 4.5 == prepared['inputs']['geometry'].pipe_sections[0].od_in or any(
            s.od_in == 4.5 for s in prepared['inputs']['geometry'].pipe_sections)
        (tmp_path/'source-project.json').write_bytes(save_project(restored))


@pytest.mark.parametrize('change', ['host_id','host_md','host_token','top','receiver','od','zone','product','fluid'])
def test_bug01_new_tieback_sources_retire_current_results(change):
    import phase_9_centralizer as phase9
    import centralizer_report
    state = bug01_solver_state('TIE BACK LNR 4 1/2"')
    phase9.execute(state)
    assert phase9.result_is_current(state)
    table = state['hardware_table']
    if change == 'host_id': table.at[1,'ID (in)'] = 6.095
    elif change == 'host_md': table.at[1,'MD (m)'] = '100-1099'
    elif change == 'host_token': state['placement_config']['host_row'] = 'retired-host'
    elif change == 'top': table.at[4,'MD (m)'] = '201-700'
    elif change == 'receiver': table.at[2,'ID (in)'] = 3.99
    elif change == 'od': table.at[4,'Size (in)'] = '4.6'
    elif change == 'zone': state['centralizer_config']['zones'][0]['density'] = '1/3'
    elif change == 'product': state['centralizer_config']['zones'][0]['product_nr'] = None
    else: state['fluids_config']['params']['Displacement Fluid']['volume'] = 9.
    assert not phase9.result_is_current(state)
    report = centralizer_report.prepare_report(state)
    assert report['current'] is False and report['analysis'] is None
