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


def test_dynamic_upstream_od_step_cannot_be_emulated_by_scalar_solver():
    from test_uat_round9e_dynamic_solver import dynamic_state, auxiliary
    from test_uat_round9d_static_solver import zones_for
    state = dynamic_state("liner")
    state["hardware_table"].loc[state["hardware_table"]["Description"] == "Drill Pipes", "Size (in)"] = "5"
    catalog = centralizer_adapter.load_official_catalog()
    # Static projection legitimately excludes the upstream workstring.
    assert centralizer_adapter.to_engine_geometry(state)["wellbore"]["string_top"] == 400.
    with pytest.raises(ValueError, match="[Dd]ynamic.*(OD|diameter)|upstream"):
        centralizer_adapter.build_dynamic_payload(state, zones_for(catalog, "liner"), catalog, aux_rheology=auxiliary())


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
    with pytest.raises(ValueError, match="Phase IX"):
        centralizer_report.prepare_report(state)
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
        with pytest.raises(ValueError, match="Phase IX"):
            report.build_master_context()
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
