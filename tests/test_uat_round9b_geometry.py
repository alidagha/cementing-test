"""Round 9B pure projection into the frozen Centralizer geometry contract."""
import hashlib
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

import centralizer_adapter as adapter
import centralizer_optimizer_engine as engine
import cement_chart_model
import materials_db
import well_profile
from placement import hardware_choices


def hardware(*rows):
    return pd.DataFrame([{"Joint (m)": 12.2, "Weight (ppf)": 50., "Grade": "K-55",
                         **dict(zip(("Description", "MD (m)", "Size (in)", "ID (in)"), row))}
                        for row in rows])


def state_for(kind="casing"):
    job = {"casing": 'CSG 9 5/8"', "liner": 'LNR 7"', "tieback": 'TIE BACK LNR 7"'}[kind]
    if kind == "casing":
        rows = (("Casing", "1000", "9 5/8", 8.535),
                ("Previous Casing", "500", "13 3/8", 12.25),
                ("Open Hole Size", "1000", "12.25", 12.25))
    elif kind == "liner":
        rows = (("Drill Pipes", "400", "5", 4.), ("Liner", "1000", "7", 6.),
                ("Liner Hanger", "400", "7", 6.),
                ("Previous Casing", "500", "9 5/8", 8.535),
                ("Open Hole Size", "1000", "8.5", 8.5))
    else:
        rows = (("Tie Back", "1000", "7", 6.),
                ("Previous Casing", "1100", "9 5/8", 8.535),
                ("Previous Liner", "1000-1200", "7", 6.),
                ("Open Hole Size", "1100-1200", "8.5", 8.5))
    state = {"job_type": job, "hardware_table": hardware(*rows),
             "well_geometry": {"version": 1, "type": "Vertical", "td_m": 1200.},
             "placement_config": {"job_type": job, "target_row": "__manual__",
                                  "manual_depth_m": 1000., "chart_excess_mode": "ignore"}}
    if kind == "tieback":
        state["placement_config"]["tie_back_liner_lap_m"] = 0.  # Explicit synthetic surface Top.
        state["placement_config"]["host_row"] = next(iter(hardware_choices(
            state["hardware_table"], {"Previous Casing"})))
    return state


def project(state):
    assert callable(getattr(adapter, "to_engine_geometry", None)), "Round 9B geometry adapter is absent"
    return adapter.to_engine_geometry(state)


def split_active(state, **changes):
    frame = state["hardware_table"]
    original = frame.iloc[0].to_dict()
    second = {**original, **changes}
    first = {**original, "MD (m)": "400"}
    state["hardware_table"] = pd.DataFrame([first, second, *frame.iloc[1:].to_dict("records")])


def test_uniform_casing_exact_si_contract_and_vertical_survey():
    result = project(state_for())
    assert set(result) == {"job_type", "survey", "casing", "wellbore"}
    assert result["job_type"] == "casing"
    assert result["survey"] == {"md": [0., 1200.], "inc_deg": [0., 0.], "azi_deg": [0., 0.]}
    assert result["casing"] == {"od": 9.625 * .0254, "id": 8.535 * .0254,
                                "weight_kg_m": 50. * .45359237 / .3048, "joint_length": 12.2}
    assert result["wellbore"] == {"prev_casing_id": 12.25 * .0254, "hole_size": 12.25 * .0254,
                                  "prev_shoe_depth": 500., "open_hole_top": 500.,
                                  "open_hole_bottom": 1000., "string_top": 0., "string_shoe": 1000.}
    assert engine.CasingProperties(**result["casing"]).steel_grade == ""
    engine.WellboreGeometry(**result["wellbore"])


def test_directional_stations_pass_through_exactly_without_derived_trajectory():
    state = state_for()
    frame = pd.DataFrame({"MD": [0., 311.123456789, 800., 1300.],
                          "Deviation": [0., 10.123456789, 45., 60.],
                          "Azimuth": [359., 1., 89.987654321, 91.]}, index=[10, 30, 70, 90])
    state["well_geometry"] = {"version": 1, "type": "Directional", "survey": frame}
    result = project(state)
    assert result["survey"] == {"md": frame["MD"].tolist(),
                                "inc_deg": frame["Deviation"].tolist(),
                                "azi_deg": frame["Azimuth"].tolist()}
    assert set(result["survey"]) == {"md", "inc_deg", "azi_deg"}


@pytest.mark.parametrize("directional", [False, True])
def test_shoe_outside_trajectory_is_blocked_by_well_profile(directional):
    state = state_for()
    state["well_geometry"] = ({"type": "Directional", "survey": pd.DataFrame(
        {"MD": [0., 999.], "Deviation": [0., 30.], "Azimuth": [0., 10.]})}
        if directional else {"type": "Vertical", "td_m": 999.})
    with pytest.raises(ValueError, match="outside the canonical trajectory"):
        project(state)


@pytest.mark.parametrize("rows", [
    [(1., 0., 0.), (1200., 0., 0.)],
    [(0., 0., 0.), (1200., 0., 0.), (1200., 0., 0.)],
    [(0., 0., 0.), (1200., 0., 0.), (1100., 0., 0.)],
    [(0., 0., 0.), (1200., 181., 0.)],
    [(0., 0., 0.), (1200., 0., 360.)],
    [(0., 0., 0.), (1200., None, 0.)],
    [(0., 0., 0.), (1200., float("inf"), 0.)],
    [(0., 0., 0.)],
])
def test_invalid_or_incomplete_survey_never_repaired(rows):
    state = state_for()
    state["well_geometry"] = {"type": "Directional", "survey": pd.DataFrame(
        rows, columns=well_profile.SURVEY_COLUMNS)}
    with pytest.raises(ValueError):
        project(state)


@pytest.mark.parametrize("field,value", [("Size (in)", "10"), ("ID (in)", 8.536),
    ("Weight (ppf)", 50.00000000000001), ("Joint (m)", 12.200000000000001)])
def test_any_active_string_property_variation_is_blocked_without_tolerance(field, value):
    state = state_for()
    split_active(state, **{field: value})
    with pytest.raises(ValueError, match="uniform|varying|Tapered"):
        project(state)


def test_equivalent_numeric_sizes_and_grade_variation_are_not_tapered():
    state = state_for()
    split_active(state, **{"Size (in)": "9.625", "Grade": "P-110"})
    result = project(state)
    assert result["casing"]["od"] == 9.625 * .0254
    assert "steel_grade" not in result["casing"]


@pytest.mark.parametrize("field", ["Size (in)", "ID (in)", "Weight (ppf)", "Joint (m)"])
@pytest.mark.parametrize("value", [0., -1., float("nan"), float("inf"), None, True])
def test_active_values_are_finite_positive_and_not_boolean(field, value):
    state = state_for()
    state["hardware_table"][field] = state["hardware_table"][field].astype(object)
    state["hardware_table"].at[0, field] = value
    with pytest.raises(ValueError):
        project(state)


def test_active_id_equal_to_od_is_not_physical():
    state = state_for()
    state["hardware_table"].at[0, "ID (in)"] = 9.625
    with pytest.raises(ValueError, match="ID|id"):
        project(state)


@pytest.mark.parametrize("value", [-10., "-10", '"-10"'])
def test_negative_od_cannot_become_positive_through_fraction_separator_parsing(value):
    state = state_for()
    state["hardware_table"].at[0, "Size (in)"] = value
    with pytest.raises(ValueError, match="greater than zero"):
        project(state)


@pytest.mark.parametrize("value", [1.7e308, 5e-324])
def test_finite_ppf_must_produce_finite_positive_engine_weight(value):
    state = state_for()
    state["hardware_table"].at[0, "Weight (ppf)"] = value
    with pytest.raises(ValueError, match="weight_kg_m.*(finite|greater than zero)"):
        project(state)


def test_liner_uses_hanger_to_shoe_and_excludes_workstring_uniformity():
    state = state_for("liner")
    frame = state["hardware_table"]
    second_pipe = frame.iloc[0].to_dict()
    frame.at[0, "MD (m)"] = "200"
    second_pipe.update({"Size (in)": "5.5", "ID (in)": 4.5, "Joint (m)": 9., "Weight (ppf)": 22.})
    state["hardware_table"] = pd.concat([frame.iloc[:1], pd.DataFrame([second_pipe]), frame.iloc[1:]],
                                         ignore_index=True)
    result = project(state)
    assert result["job_type"] == "liner"
    assert result["wellbore"]["string_top"] == 400.
    assert result["wellbore"]["string_shoe"] == 1000.
    assert result["casing"] == {"od": 7. * .0254, "id": 6. * .0254,
                                "weight_kg_m": 50. * .45359237 / .3048, "joint_length": 12.2}


@pytest.mark.parametrize("field,value", [("Size (in)", "7.1"), ("ID (in)", 6.1),
                                       ("Weight (ppf)", 51.), ("Joint (m)", 12.)])
def test_liner_active_variation_still_blocks(field, value):
    state = state_for("liner")
    frame = state["hardware_table"]
    first, second = frame.iloc[1].to_dict(), frame.iloc[1].to_dict()
    first["MD (m)"] = "700"
    second[field] = value
    state["hardware_table"] = pd.DataFrame([frame.iloc[0].to_dict(), first, second,
                                            *frame.iloc[2:].to_dict("records")])
    with pytest.raises(ValueError, match="uniform|varying|Tapered"):
        project(state)


@pytest.mark.parametrize("kind", ["casing", "liner"])
def test_cased_envelope_id_variation_cannot_be_averaged(kind):
    state = state_for(kind)
    frame = state["hardware_table"]
    index = frame.index[frame["Description"] == "Previous Casing"][0]
    first, second = frame.loc[index].to_dict(), frame.loc[index].to_dict()
    first["MD (m)"] = "200"
    second["ID (in)"] -= .1
    state["hardware_table"] = pd.concat([frame.drop(index), pd.DataFrame([first, second])], ignore_index=True)
    with pytest.raises(ValueError, match="enclosing|scalar|diameter|ID"):
        project(state)


def test_open_hole_variation_cannot_be_averaged_or_replaced_by_caliper():
    state = state_for()
    frame = state["hardware_table"]
    first, second = frame.iloc[-1].to_dict(), frame.iloc[-1].to_dict()
    first["MD (m)"] = "700"
    second["Size (in)"] = "12.5"
    state["hardware_table"] = pd.DataFrame([*frame.iloc[:-1].to_dict("records"), first, second])
    with pytest.raises(ValueError, match="open.hole|scalar|diameter"):
        project(state)


def test_multiple_contiguous_identical_envelope_rows_collapse_exactly():
    state = state_for()
    state["hardware_table"] = hardware(("Casing", "300", "9 5/8", 8.535),
        ("Casing", "300-1000", "9.625", 8.535), ("Previous Casing", "200", "13 3/8", 12.25),
        ("Previous Casing", "200-500", "13.375", 12.25),
        ("Open Hole Size", "700", "12.25", 12.25), ("Open Hole Size", "700-1000", "12.25", 12.25))
    result = project(state)
    assert result["wellbore"] == project(state_for())["wellbore"]
    assert not any("caliper" in key for key in result["wellbore"])


def test_tieback_uses_exact_selected_host_and_continuity_at_shoe():
    state = state_for("tieback")
    state["hardware_table"] = pd.concat([state["hardware_table"],
        hardware(("Previous Casing", "1200", "13 3/8", 12.347))], ignore_index=True)
    result = project(state)
    assert result["job_type"] == "tieback"
    assert result["wellbore"] == {"prev_casing_id": 8.535 * .0254, "hole_size": 8.535 * .0254,
                                  "prev_shoe_depth": 1000., "open_hole_top": 1000.,
                                  "open_hole_bottom": 1000., "string_top": 0., "string_shoe": 1000.}


def test_tieback_host_scalar_variation_blocks_and_identical_segments_pass():
    state = state_for("tieback")
    state["hardware_table"] = hardware(("Tie Back", "1000", "7", 6.),
        ("Previous Casing", "500", "9 5/8", 8.535),
        ("Previous Casing", "500-1100", "9.625", 8.535),
        ("Previous Liner", "1000-1200", "7", 6.),
        ("Open Hole Size", "1100-1200", "8.5", 8.5))
    state["placement_config"]["host_row"] = next(iter(hardware_choices(
        state["hardware_table"], {"Previous Casing"})))
    assert project(state)["wellbore"]["prev_casing_id"] == 8.535 * .0254
    state["hardware_table"].at[2, "ID (in)"] = 8.536
    with pytest.raises(ValueError, match="enclosing.*ID"):
        project(state)


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_missing_required_hardware_is_not_fabricated(kind):
    state = state_for(kind)
    description = {"casing": "Open Hole Size", "liner": "Drill Pipes", "tieback": "Previous Casing"}[kind]
    state["hardware_table"] = state["hardware_table"].loc[
        state["hardware_table"]["Description"] != description]
    with pytest.raises(ValueError):
        project(state)


def test_weight_and_joint_beyond_the_resolved_shoe_are_not_active_properties():
    state = state_for()
    frame = state["hardware_table"]
    state["hardware_table"] = pd.concat([frame.iloc[:1],
        hardware(("Casing", "1000-1200", "9.625", 8.535)), frame.iloc[1:]], ignore_index=True)
    state["hardware_table"].at[1, "Weight (ppf)"] = 99.
    state["hardware_table"].at[1, "Joint (m)"] = 9.
    assert project(state)["casing"] == project(state_for())["casing"]


@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_presentation_overrides_and_fluid_values_never_drive_geometry(kind):
    state = state_for(kind)
    before = project(state)
    state["cement_params"] = {"Main": {"top_depth": 42., "report_bottom_depth": 999999.}}
    state["fluids_config"] = {"active": ["Spacer Behind"], "params": {"Spacer Behind": {"volume": 123.}}}
    assert project(state) == before


@pytest.mark.parametrize("job", ["CMT PLUG", "CMT SQUEEZE"])
def test_plug_and_squeeze_return_controlled_na_without_geometry_or_solver(job, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("N/A job accessed geometry or an engine calculation")
    monkeypatch.setattr(cement_chart_model, "resolve_chart_geometry", forbidden)
    for name in ("compute_standoff_profile", "optimize_placement", "run_full_analysis"):
        monkeypatch.setattr(engine, name, forbidden)
    assert project({"job_type": job}) is None


@pytest.mark.parametrize("job", [None, "CSG 8\"", "LNR 9\"", "TIE BACK LNR 9 5/8\"", "FUTURE CSG 7\""])
def test_unknown_jobs_are_rejected_without_substring_inference(job):
    with pytest.raises(ValueError, match="Unsupported|supported"):
        project({"job_type": job})


@pytest.mark.parametrize("directional", [False, True])
@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
def test_pure_deterministic_projection_no_solver_io_session_cache_or_input_mutation(kind, directional, monkeypatch):
    state = state_for(kind)
    if directional:
        state["well_geometry"] = {"type": "Directional", "survey": pd.DataFrame(
            {"MD": [0., 600., 1200.], "Deviation": [0., 25., 40.], "Azimuth": [359., 1., 90.]})}
    original = deepcopy(state)
    def forbidden(*args, **kwargs):
        pytest.fail("Projection invoked a solver, I/O or session state")
    for name in ("compute_standoff_profile", "optimize_placement", "run_full_analysis"):
        monkeypatch.setattr(engine, name, forbidden)
    import builtins
    import streamlit
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(streamlit, "session_state", object())
    first = project(state)
    assert first == project(state)
    pd.testing.assert_frame_equal(state["hardware_table"], original.pop("hardware_table"))
    original_geometry = original.pop("well_geometry")
    if directional:
        pd.testing.assert_frame_equal(state["well_geometry"]["survey"], original_geometry.pop("survey"))
    assert {k: v for k, v in state["well_geometry"].items() if k != "survey"} == original_geometry
    assert {k: v for k, v in state.items() if k not in ("hardware_table", "well_geometry")} == original
    first["survey"]["md"][0] = 99.
    assert project(state)["survey"]["md"][0] == 0.


def test_frozen_artifacts_and_catalog_unchanged():
    root = Path(__file__).resolve().parents[1]
    for name, sha in {
        "centralizer_optimizer_engine.py": "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9",
        "cement_charts_engine.py": "68b275c0c3fd0e804a926d39e1123b451f7e22b2c5aad31f6d0ab3e8236709d4",
        "ds_cent_products.json": "837010c1a67a7a9252317f4b2e9b8f08b29f39f431cc8e45cfcc5eb6c94a1329",
    }.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == sha


@pytest.mark.parametrize("job", materials_db.JOB_TYPES)
def test_every_exact_supported_job_maps_only_through_existing_authorities(job):
    kind = cement_chart_model.chart_job_kind(job)
    if kind is None:
        assert project({"job_type": job}) is None
    else:
        state = state_for(kind)
        state["job_type"] = state["placement_config"]["job_type"] = job
        if job in ('CSG 30"', 'CSG 24"', 'CSG 20"', 'CSG 18 5/8"'):
            # Casing remains an independent chart/geometry job; only Centralizer is N/A.
            assert kind == "casing"
            assert project(state) is None
            assert cement_chart_model.resolve_chart_geometry(state)["kind"] == "casing"
        else:
            assert project(state)["job_type"] == kind
