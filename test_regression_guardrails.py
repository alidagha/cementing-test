"""
test_regression_guardrails.py — ZERO-REGRESSION CONTRACT REGRESSION AUTHORITY
=============================================================================
Unified Regression Authority (38/38 Tests)
Merged with owner-approved Audit Batch 3 fixes (F-01, F-02, F-03).

Contract mapping:
  * Section 2.4 — this file IS the Regression Authority; do not modify during
    ordinary bug-fix work. Changing a guardrail requires an explicit
    specification change authorized by the owner.
  * Section 5   — GROUP C encodes the human-readable invariant table 1:1
    (13 rows -> 13 tests). Changing any invariant is a SPECIFICATION CHANGE.

Groups:
  GROUP A — bug reproduction & audit-fix tests (18 tests):
            BUG-04, 05, 12, 13, 15, 16, 22, 25/26, P0-01/F1, F2, F3, F4,
            plus Batch 3 audit fixes: F-01, F-02, F-03.
  GROUP B — protection tests (7 tests: "Verified Working — Do Not Break",
            report section 0): the regression tripwire; ANY red here means
            a change injected a new bug -> revert.
  GROUP C — contract Section 5 invariants (13 tests: Yield, Lab cup,
            Mix water, Temperature, Depth, Parsing, Digits, Density/rate,
            Time, JSON I/O, Additives, Word notes, Placement).

Run:  cd <project root> && pytest test_regression_guardrails.py -v
Stack: Python 3.12, Streamlit 1.64.0, pandas 2.2.3, numpy 2.1.3,
       docxtpl 0.20.2, python-docx 1.2.0 (requirements.txt, BUG-17 pin).
"""
import io
import json
import math
import os
import sys
import warnings
import zipfile

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import pytest

from engineering_tools import (parse_effective_numeric, compute_phase_status,
                               calculate_slurry_from_components,
                               require_positive_density,
                               require_positive_pump_rate,
                               lab_temperature_valid, format_to_hr_mm,
                               normalize_digits, normalize_additive_mix,
                               safe_float)
from project_state import (fingerprint, purge_inactive_slurries,
                           prepare_calculations)
from phase_10_procedure import _phase_for_issue
import placement
import materials_db
import project_io

# ---------------------------------------------------------------------------
# Shared benchmark seed — well WZ-217 (report section 9)
# ---------------------------------------------------------------------------
TARGET_ROW = fingerprint(["Casing", "1200.0-2816.0", "9.625"])

_SELF_NAME = "test_regression_guardrails.py"
_LEGACY_NAME = "test_reproduction_suite.py"
APP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")


def _benchmark_hardware() -> pd.DataFrame:
    return pd.DataFrame([{
        "Description": "Casing", "MD (m)": "1200.0-2816.0", "Size (in)": "9.625",
        "ID (in)": 8.535, "Joint (m)": 0.0, "Weight (ppf)": 47.0, "Grade": "K-55",
        "Collapse (psi)": 0.0, "Burst (psi)": 0.0}])


def _seed_session():
    """Seed st.session_state with the WZ-217 profile so build_master_context
    passes every export gate headlessly (verified in the Rev 2 audit)."""
    import streamlit as st
    seed = {
        "job_type": 'CSG 9 5/8"',
        "geo_md": 3000.0, "geo_tvd": 3000.0,
        "hardware_table": _benchmark_hardware(),
        "fluids_config": {"active": ["Pre Flush", "Spacer", "Lead", "Tail",
                                     "Displacement Fluid"]},
        "fluid_data": {
            "Pre Flush": {"volume": 80.0, "density": 75.0, "min_rate": 5.0},
            "Spacer": {"volume": 150.0, "density": 95.0, "min_rate": 4.0},
            "Lead": {"volume": 500.0, "density": 104.0, "min_rate": 4.0},
            "Tail": {"volume": 300.0, "density": 118.0, "min_rate": 3.0},
            "Displacement Fluid": {"volume": 1200.0, "density": 65.0, "min_rate": 6.0},
        },
        "cement_params": {
            "Lead": {"yield": 1.818, "mix_water": 40.0, "dead_vol": 2.0,
                     "tank_name": "Tank 1", "base_cement": "Cement G Delijan",
                     "solution": "Fresh Water", "top_mode": "Depth (m MD)",
                     "top_depth": 1250.0},
            "Tail": {"yield": 1.360, "mix_water": 25.0, "dead_vol": 1.0,
                     "tank_name": "Tank 2", "base_cement": "Cement G Delijan",
                     "solution": "Fresh Water", "top_mode": "Depth (m MD)",
                     "top_depth": 2000.0},
        },
        "cement_calc_Lead": pd.DataFrame(
            [{"Additive": "Fluid Loss", "Concentration": "0.5 %"}]),
        "cement_calc_Tail": pd.DataFrame(
            [{"Additive": "Retarder", "Concentration": "0.2 %"}]),
        "spacer_dfs": {"Spacer": pd.DataFrame([
            {"Chemical": "Hematite", "User Input (% or gal)": 5.0,
             "Weighting Agent Type": "Hematite"}])},
        "preflush_config": {"type": "Combined (Water + NaCl + Wash)",
                            "nacl_multiplier": 126.0, "wash_multiplier": 3.0},
        "preflush_calc": {"density_pcf": 75.0},
        "lab_payload_Lead": {"surface_hardened_hours": 8.0, "free_water_45": 0.0},
        "lab_payload_Tail": {"surface_hardened_hours": 8.0, "free_water_45": 0.0},
        "total_pump_time_min": 210.0,
        "placement_config": {"job_type": 'CSG 9 5/8"', "target_row": TARGET_ROW,
                             "excess_csg_oh_pct": 30.0, "excess_csg_csg_pct": 10.5},
    }
    for key, value in seed.items():
        st.session_state[key] = value
    return st.session_state


def _seed_wz217_apptest(at):
    """Seed benchmark profile on a live AppTest session for F-01 testing."""
    seed = {
        "job_type": 'CSG 9 5/8"',
        "hole_size": '12 1/4"',
        "well_name": "WZ-217", "client": "NIDC",
        "geo_md": 3000.0, "geo_tvd": 3000.0,
        "hardware_table": _benchmark_hardware(),
        "fluids_config": {"active": ["Pre Flush", "Spacer", "Lead", "Tail",
                                     "Displacement Fluid"]},
        "fluid_data": {
            "Pre Flush": {"name": "Pre Flush", "material_name": "Salt Saturated Water",
                          "volume": 80.0, "density": "75.0", "min_rate": 5.0},
            "Spacer": {"name": "Spacer", "material_name": "Weighted Spacer",
                       "volume": 150.0, "density": "95.0", "min_rate": 4.0},
            "Lead": {"name": "Lead", "material_name": "Cement Slurry",
                     "volume": 500.0, "density": "104.0", "min_rate": 4.0},
            "Tail": {"name": "Tail", "material_name": "Cement Slurry",
                     "volume": 300.0, "density": "118.0", "min_rate": 3.0},
            "Displacement Fluid": {"name": "Displacement Fluid", "material_name": "Mud",
                                   "volume": 1200.0, "density": "65.0", "min_rate": 6.0},
        },
        "cement_params": {
            "Lead": {"yield": 1.818, "mix_water": 40.0, "dead_vol": 2.0,
                     "tank_name": "Tank 1", "base_cement": "Cement G Delijan",
                     "solution": "Fresh Water", "top_mode": "Depth (m MD)",
                     "top_depth": 1250.0},
            "Tail": {"yield": 1.360, "mix_water": 25.0, "dead_vol": 1.0,
                     "tank_name": "Tank 2", "base_cement": "Cement G Delijan",
                     "solution": "Fresh Water", "top_mode": "Depth (m MD)",
                     "top_depth": 2000.0},
        },
        "cement_calc_Lead": pd.DataFrame(
            [{"Additive": "Fluid Loss", "Concentration": "0.5 %"}]),
        "cement_calc_Tail": pd.DataFrame(
            [{"Additive": "Retarder", "Concentration": "0.2 %"}]),
        "spacer_dfs": {"Spacer": pd.DataFrame([
            {"Chemical": "Hematite", "User Input (% or gal)": 5.0,
              "Weighting Agent Type": "Hematite"}])},
        "preflush_config": {"type": "Combined (Water + NaCl + Wash)",
                            "nacl_multiplier": 126.0, "wash_multiplier": 3.0},
        "total_pump_time_min": 210.0,
        "placement_config": {"job_type": 'CSG 9 5/8"', "target_row": TARGET_ROW,
                             "excess_csg_oh_pct": 30.0, "excess_csg_csg_pct": 10.5},
    }
    for k, v in seed.items():
        at.session_state[k] = v
    return at


def _app_exceptions(at):
    return [str(e.value) for e in at.exception]


def _hostile_lab_project():
    """A structurally valid project JSON whose lab grid carries numeric dtypes."""
    return {
        "well_name": "WZ-217", "job_type": 'CSG 20"',
        "fluids_config": {"active": ["Lead"],
                          "params": {"Lead": {"volume": 500.0, "density": "104.0",
                                              "pump_rate": "4.0",
                                              "material_name": "Cement Slurry"}}},
        "fluid_data": {"Lead": {"name": "Lead", "material_name": "Cement Slurry",
                                "volume": 500.0, "density": "104.0", "min_rate": 4.0}},
        "cement_params": {"Lead": {"yield": 1.818, "mix_water": 40.0, "dead_vol": 2.0,
                                   "tank_name": "Tank 1",
                                   "base_cement": "Cement G Delijan",
                                   "solution": "Fresh Water",
                                   "top_mode": "Depth (m MD)", "top_depth": 1250.0}},
        "lab_grid_dfs": {"Lead": {
            "__type__": "DataFrame",
            "columns": ["Material", "Concentration", "Unit", "Mass", "Lot No"],
            "data": [{"Material": "Cement G Delijan", "Concentration": 100.0,
                      "Unit": "% BWOC", "Mass": 582.0, "Lot No": None}]}},
        "bhct": 150, "well_data": {"bhct": 150},
        "lab_qc_params": {"Lead": {"api_fl": 4.0, "free_water": 0.0,
                                   "comp_test": "UCA", "thickening_time": "3:30",
                                   "reviewed": True}},
        "cement_initialized_slurries": ["Lead"],
        "lab_initialized_slurries": ["Lead"],
    }


# ===========================================================================
# GROUP A — bug reproduction & audit-fix tests (18 tests)
# ===========================================================================

def test_interval_md_does_not_trigger_warning():
    """BUG-12: interval MD rows must pass the hardware-completeness check."""
    seeded = {"hardware_table": _benchmark_hardware(),
              "geo_md": 3000.0, "geo_tvd": 3000.0,
              "job_type": 'CSG 9 5/8"'}
    status = compute_phase_status({**seeded,
                                   "placement_config": {"job_type": 'CSG 9 5/8"',
                                                        "target_row": TARGET_ROW}})
    assert status["phase2_3"]["level"] == "ok", \
        f"Interval MD still flagged: {status['phase2_3']['message']}"
    status2 = compute_phase_status({**seeded, "placement_config": {}})
    assert status2["phase2_3"]["message"] != \
        "Complete hardware description, depth, size and ID.", \
        "Interval MD still trips the hardware completeness check (BUG-12 unfixed)"


def test_fingerprint_int_float_equivalence():
    """BUG-16: fingerprinting must treat 150 and 150.0 identically."""
    assert fingerprint({"bhct": 150}) == fingerprint({"bhct": 150.0}), \
        "int/float fingerprint divergence (BUG-16 unfixed)"


def test_negative_range_parsing():
    """BUG-22: multi-hyphen leading-negative must stay visibly negative."""
    assert parse_effective_numeric("-80-82") == pytest.approx(-81.0), \
        "BUG-22 semantics: leading-negative range must negate the mean"
    assert parse_effective_numeric("-118") == -118.0


def test_lab_density_guard():
    """BUG-13: a 55 pcf slurry must be rejected before negative lab quantities."""
    rejected = False
    try:
        density = require_positive_density("55")
        calc = calculate_slurry_from_components(slurry_weight_pcf=density,
                                                slurry_volume_bbl=500.0,
                                                cmt_sg=3.2)
        rejected = (calc["water_vol_per_sack"] > 0
                    and calc["yield_ft3_per_sk"] > 0)
    except ValueError:
        rejected = True
    assert rejected, "55 pcf was accepted and produced negative water/yield (BUG-13 unfixed)"


def test_purge_removes_editor_revision_keys():
    """BUG-15: deactivating a slurry must not leave editor revision/source keys."""
    state = {"cement_additives_dfs": {"Main": pd.DataFrame({"A": [1]})},
             "cement_params": {"Main": {}},
             "lab_grid_dfs": {"Main": pd.DataFrame()},
             "lab_qc_params": {"Main": {}},
             "lab_source_signatures": {},
             "cement_initialized_slurries": ["Main"],
             "lab_initialized_slurries": ["Main"],
             "_editor_additives_slurry_main_revision": 3,
             "_editor_source__editor_additives_main_default_3": "stale"}
    purge_inactive_slurries(state, active=["Tail"])
    assert "_editor_additives_slurry_main_revision" not in state, \
        "revision key survives purge (BUG-15 unfixed)"
    assert not [k for k in state if str(k).startswith("_editor_source_")], \
        "_editor_source_ keys survive purge (BUG-15 unfixed)"


def test_master_context_contains_placement_keys():
    """BUG-04: every slurry payload must carry top/bottom/excess_oh/excess_csg."""
    from phase_10_procedure import build_master_context
    _seed_session()
    ctx = build_master_context(calculations_prepared=True)
    assert ctx["slurries"], "no slurry payload built"
    for s in ctx["slurries"]:
        for key in ("top", "bottom", "excess_oh", "excess_csg"):
            assert key in s, f"payload key '{key}' missing (BUG-04 unfixed)"
            assert s[key] != "....", \
                f"{s['name']}.{key} renders the '....' fallback (BUG-04 unfixed)"


def test_template_has_spacer_block():
    """BUG-05: the Word template must consume the spacers payload."""
    xml = zipfile.ZipFile(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "master_template.docx")
                          ).read("word/document.xml").decode("utf-8")
    assert "has_spacer" in xml and "spacers" in xml, \
        "Spacer block missing from template (BUG-05 unfixed)"


def test_serialize_numpy_and_nat():
    """BUG-25/BUG-26: save path must unwrap numpy scalars and neutralize NaT."""
    from main import serialize_item, deserialize_item
    value = serialize_item(np.int64(42))
    assert value == 42 and not isinstance(value, str), \
        "np.int64 stringified on save (BUG-25 unfixed)"
    round_trip = deserialize_item(serialize_item(pd.NaT))
    assert round_trip is None, "pd.NaT breaks JSON reload (BUG-26 unfixed)"


def test_blank_volume_basis_exports_as_na():
    """Optional placement percentages remain N/A when neither is supplied."""
    from phase_10_procedure import build_master_context
    state = _seed_session()
    cfg = dict(state["placement_config"])
    cfg["excess_csg_oh_pct"] = None
    cfg["excess_csg_csg_pct"] = None
    state["placement_config"] = cfg
    ctx = build_master_context(calculations_prepared=True)
    assert ctx["slurries"], "no slurry payload built"
    for s in ctx["slurries"]:
        assert s["excess_oh"] == "N/A", f"{s['name']}.excess_oh={s['excess_oh']!r}"
        assert s["excess_csg"] == "N/A", f"{s['name']}.excess_csg={s['excess_csg']!r}"
        assert s["top"] != "...." and s["bottom"] != "....", \
            "top/bottom must keep their real values here"


def test_blank_string_additive_cell_is_detected():
    """Owner critique round: count blank-STRING cell ('') as empty, not only NaN."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    blank_row = {"Material Type": "Liquid", "Name": "Fluid Loss",
                 "Physical State": "Liquid", "Mix Method": "In Mix Water",
                 "User Input": ""}
    nan_row = {"Material Type": "Liquid", "Name": "Retarder",
               "Physical State": "Liquid", "Mix Method": "In Mix Water",
               "User Input": np.nan}
    at.session_state["fluids_config"] = {"active": ["Lead"]}
    at.session_state["cement_additives_dfs"] = {
        "Lead": pd.DataFrame([blank_row, nan_row])}
    at.run()
    cards = [w.value for w in at.sidebar.warning] + [w.value for w in at.warning]
    text = " | ".join(str(c) for c in cards)
    assert "Lead: row 1, 2" in text, \
        f"blank-string cell (row 1) missed by the sidebar aggregation: {text!r}"


def test_preflush_payload_recomputed_at_export_time():
    """F1 / P0-01: Word payload must be recomputed from preflush_config + fluid_data."""
    from phase_10_procedure import build_master_context
    state = _seed_session()
    ctx = build_master_context(calculations_prepared=True)
    assert ctx["preflush"]["volume"] == 80.0, ctx["preflush"].get("volume")
    assert any(r["Name"] == "Salt" and r["amount"] == "10080.0 lb"
               for r in ctx["preflush"]["rows"]), ctx["preflush"]["rows"]

    state["fluid_data"]["Pre Flush"]["volume"] = 25.0
    state["preflush_calc"] = {"type": "Combined (Water + NaCl + Wash)",
                              "volume_bbl": 80.0, "density_pcf": 75.0,
                              "effective_density": 75.0, "water_bbl": 80.0,
                              "nacl_lbs": 10080.0, "wash_gal": 240.0,
                              "nacl_multiplier": 126.0, "wash_multiplier": 3.0}
    ctx2 = build_master_context(calculations_prepared=True)
    assert ctx2["preflush"]["volume"] == 25.0, \
        "Word payload reused the stale Phase VI preflush_calc snapshot (P0-01)"
    rows = ctx2["preflush"]["rows"]
    assert rows[0]["amount"] == "25.0 bbl", rows[0]
    assert any(r["Name"] == "Salt" and r["amount"] == "3150.0 lb" for r in rows), rows
    assert ctx2["preflush"]["weight"] == "75.0", ctx2["preflush"].get("weight")


def test_preflush_payload_type_variants():
    """F1: compute_preflush_payload must mirror Phase VI render semantics."""
    from phase_6_spacer import compute_preflush_payload
    base_cfg = {"nacl_multiplier": 126.0, "wash_multiplier": 3.0}
    info = {"volume": 80.0, "density": 75.0}

    fresh = compute_preflush_payload({**base_cfg, "type": "Fresh Water Only"}, info)
    assert (fresh["water_bbl"], fresh["nacl_lbs"], fresh["wash_gal"]) == (80.0, 0.0, 0.0)

    brine = compute_preflush_payload({**base_cfg, "type": "Brine (Water + NaCl)"}, info)
    assert brine["nacl_lbs"] == 10080.0 and brine["wash_gal"] == 0.0
    assert brine["nacl_multiplier"] == 126.0 and brine["wash_multiplier"] == 0.0

    wash = compute_preflush_payload({**base_cfg, "type": "Water + Chemical Wash"},
                                    {"volume": 40.0, "density": 75.0})
    assert wash["wash_gal"] == 120.0 and wash["nacl_lbs"] == 0.0
    assert wash["nacl_multiplier"] == 0.0

    custom = compute_preflush_payload({**base_cfg, "type": "Combined / Custom"}, info)
    assert custom["type"] == "Combined (Water + NaCl + Wash)"
    assert custom["nacl_lbs"] == 10080.0 and custom["wash_gal"] == 240.0

    legacy = compute_preflush_payload({**base_cfg, "type": "Chemical Wash"},
                                      {"volume": 40.0, "density": 75.0})
    assert legacy["type"] == "Water + Chemical Wash"
    assert fresh["density_pcf"] == "75.0" and fresh["volume_bbl"] == 80.0


def test_thickening_time_semantic_range():
    """F2 / P1-02: validate thickening time range (00:01 to 24:00 inclusive)."""
    from engineering_tools import thickening_time_valid
    for good in ("03:30", "3:30", " 03:30 ", "24:00", "0:30"):
        assert thickening_time_valid(good) is True, good
    for bad in ("00:00", "24:01", "25:00", "99:59", "3:3", "03.30", "abc", ""):
        assert thickening_time_valid(bad) is False, bad


def test_spacer_densities_sort_numerically():
    """F4 / P2-01: order spacer densities numerically, handling ranges safely."""
    from phase_10_procedure import build_master_context
    state = _seed_session()
    state["fluids_config"]["active"] = ["Pre Flush", "Spacer", "Spacer Ahead",
                                        "Lead", "Tail", "Displacement Fluid"]
    state["fluid_data"]["Spacer"]["density"] = "100.0"
    state["fluid_data"]["Spacer Ahead"] = {"volume": 120.0, "density": "95.0",
                                           "min_rate": 4.0}
    state["spacer_dfs"]["Spacer Ahead"] = pd.DataFrame(
        [{"Chemical": "Bentonite", "User Input (% or gal)": 2.0,
          "Weighting Agent Type": "-"}])
    ctx = build_master_context(calculations_prepared=True)
    assert ctx["spacer_density_note"] == "95.0, 100.0", \
        ctx["spacer_density_note"]

    state["fluid_data"]["Spacer"]["density"] = "115-118"
    ctx2 = build_master_context(calculations_prepared=True)
    assert ctx2["spacer_density_note"] == "95.0, 115-118", \
        ctx2["spacer_density_note"]


def test_unreadable_fluid_volume_blocks_with_clear_message():
    """F3 / P1-03: malformed volume surfaces as controlled export-block naming fluid."""
    from phase_10_procedure import build_master_context
    state = _seed_session()
    state["fluid_data"]["Spacer"]["volume"] = "abc"
    with pytest.raises(ValueError) as ei:
        build_master_context(calculations_prepared=True)
    assert "Spacer" in str(ei.value) and "volume" in str(ei.value), str(ei.value)

    state2 = _seed_session()
    state2["fluid_data"]["Pre Flush"]["volume"] = "abc"
    with pytest.raises(ValueError) as ei2:
        build_master_context(calculations_prepared=True)
    assert "Pre Flush" in str(ei2.value), str(ei2.value)

    state3 = _seed_session()
    state3["fluid_data"]["Lead"]["volume"] = ""
    with pytest.raises(ValueError) as ei3:
        build_master_context(calculations_prepared=True)
    assert "Lead" in str(ei3.value), str(ei3.value)


def test_f01_phase10_logistics_cards_survive_textual_volume():
    """F-01: Phase X logistics summary cards render honest N/A on textual volume."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP_PATH, default_timeout=180)
    _seed_wz217_apptest(at)
    at.run()
    assert not at.exception, _app_exceptions(at)

    at.session_state["fluid_data"]["Lead"]["volume"] = "GARBAGE"
    at.session_state["_app_mode_key"] = "phase10"
    at.run()

    assert not at.exception, (
        "Phase X crashed with a raw exception on a textual fluid volume "
        f"(F-01 unfixed): {_app_exceptions(at)}")

    errors = " | ".join(str(e.value) for e in at.error)
    assert "Unreadable numeric volume in Phase IV fluid data" in errors, errors
    assert "Lead → volume ('GARBAGE')" in errors, errors

    table_text = " | ".join(
        (t.value.to_string() if isinstance(getattr(t, "value", None), pd.DataFrame)
         else repr(getattr(t, "value", None)))
        for t in at.table)
    assert "N/A" in table_text, (
        f"unreadable volume must render as an honest N/A card cell, got: {table_text!r}")
    assert "300.0" in table_text, table_text


def test_f02_refresh_fluids_errors_carry_phase_iv_deeplink_token():
    """F-02: refresh_fluids errors carry 'Phase IV:' token to resolve deep-link."""
    cases = {
        "negative volume": {"Lead": {"name": "Lead", "material_name": "Cement Slurry",
                                     "volume": -5.0, "density": "104.0",
                                     "pump_rate": "4.0"}},
        "missing density": {"Lead": {"name": "Lead", "material_name": "Cement Slurry",
                                     "volume": 100.0, "pump_rate": "4.0"}},
        "missing pump rate": {"Lead": {"name": "Lead", "material_name": "Cement Slurry",
                                       "volume": 100.0, "density": "104.0"}},
        "unreadable volume": {"Lead": {"name": "Lead", "material_name": "Cement Slurry",
                                       "volume": "GARBAGE", "density": "104.0",
                                       "pump_rate": "4.0"}},
        "missing volume": {"Lead": {"name": "Lead", "material_name": "Cement Slurry",
                                    "density": "104.0", "pump_rate": "4.0"}},
    }
    for label, fluid_data in cases.items():
        state = {"fluids_config": {"active": ["Lead"]}, "fluid_data": fluid_data}
        issues = prepare_calculations(state)
        assert issues, f"[{label}] expected a blocking issue"
        wrapped = issues[0]
        assert "Phase IV:" in wrapped, (
            f"[{label}] refresh_fluids error lost the Phase IV token "
            f"(deep-link rescue dead): {wrapped!r}")
        assert _phase_for_issue(wrapped) == "phase4", (
            f"[{label}] no rescue phase resolved from: {wrapped!r}")
        assert "Lead" in wrapped, f"[{label}] offender name missing: {wrapped!r}"

    state = {"fluids_config": {"active": ["Lead"]},
             "fluid_data": cases["unreadable volume"]}
    wrapped = prepare_calculations(state)[0]
    assert "unreadable fluid volume" in wrapped and "'GARBAGE'" in wrapped, wrapped
    assert "could not convert string to float" not in wrapped, wrapped


def test_f03_lab_grid_text_columns_coerced_to_str_on_decode():
    """F-03: decode_project coerces lab grid text columns to string at load time."""
    from main import deserialize_item
    raw = json.dumps(_hostile_lab_project()).encode("utf-8")

    prepared = project_io.decode_project(raw, deserialize_item)
    grid = prepared["lab_grid_dfs"]["Lead"]
    # Compatible across pandas 2.x ('object') and pandas 3.x ('str'/'string')
    assert str(grid["Concentration"].dtype) in ("object", "str", "string"), (
        f"Concentration stayed numeric ({grid['Concentration'].dtype}) — "
        f"Phase VII will crash with StreamlitAPIException (F-03 unfixed)")
    assert grid.iloc[0]["Concentration"] == "100.0"
    assert grid.iloc[0]["Mass"] == "582.0"
    assert grid.iloc[0]["Unit"] == "% BWOC"
    assert grid.iloc[0]["Material"] == "Cement G Delijan"
    assert grid.iloc[0]["Lot No"] is None or pd.isna(grid.iloc[0]["Lot No"]), (
        "missing cells must stay missing, not become 'None'/'nan' text")

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP_PATH, default_timeout=180)
    at.run()
    at.file_uploader[0].set_value(("hostile_project.json", raw, "application/json"))
    at.run()
    assert not at.exception, _app_exceptions(at)
    loaded = at.session_state["lab_grid_dfs"]["Lead"]
    assert str(loaded["Concentration"].dtype) in ("object", "str", "string"), str(loaded.dtypes)
    assert loaded.iloc[0]["Concentration"] == "100.0"
    at.session_state["_app_mode_key"] = "phase7"
    at.run()
    assert not at.exception, (
        f"Phase VII crashed after loading a numeric lab grid (F-03 unfixed): "
        f"{_app_exceptions(at)}")


# ===========================================================================
# GROUP B — protection tests (7 tests: the regression tripwire)
# ===========================================================================

def test_all_modules_compile():
    """Section 0: all project modules must stay importable and compilable."""
    import glob
    import py_compile
    base = os.path.dirname(os.path.abspath(__file__))
    modules = [f for f in sorted(glob.glob(os.path.join(base, "*.py")))
               if not f.endswith((_SELF_NAME, _LEGACY_NAME))]
    assert modules, "no project modules found"
    for path in modules:
        py_compile.compile(path, doraise=True)


def test_mass_balance_reference_yields():
    """Section 0: slurry yield matches the API Spec 10A hand calculation."""
    lead = calculate_slurry_from_components(slurry_weight_pcf=104.0,
                                            slurry_volume_bbl=500.0, cmt_sg=3.2)
    tail = calculate_slurry_from_components(slurry_weight_pcf=118.0,
                                            slurry_volume_bbl=300.0, cmt_sg=3.2)
    assert abs(lead["yield_ft3_per_sk"] - 1.818) < 0.005, \
        f"Lead yield drifted: {lead['yield_ft3_per_sk']}"
    assert abs(tail["yield_ft3_per_sk"] - 1.360) < 0.005, \
        f"Tail yield drifted: {tail['yield_ft3_per_sk']}"
    assert lead["water_vol_per_sack"] > 0 and tail["water_vol_per_sack"] > 0


def test_single_negative_parse_still_fixed():
    """Section 0: the single-negative interval fix must not regress."""
    assert parse_effective_numeric("-118") == -118.0
    assert parse_effective_numeric("80-82") == 81.0


def test_plausible_density_still_accepted():
    """Section 0: valid densities must keep passing the input guard."""
    assert require_positive_density("104") == pytest.approx(104.0)
    assert require_positive_density("75-80") == pytest.approx(77.5)


def test_hostile_json_rejected():
    """Section 0: decode_project must keep rejecting malformed payloads."""
    from main import deserialize_item
    for hostile in (b'{"x": NaN}', b'{"a": 1, "a": 2}', b'[1, 2, 3]'):
        with pytest.raises(Exception):
            project_io.decode_project(hostile, deserialize_item)


def test_editor_state_importable():
    """Section 0: the persistent_data_editor wrapper must stay importable."""
    from editor_state import persistent_data_editor  # noqa: F401


def test_render_master_document_smoke():
    """Section 0: end-to-end Word engine smoke test mirroring production path."""
    from phase_10_procedure import build_master_context
    _seed_session()
    ctx = build_master_context(calculations_prepared=True)
    assert ctx.get("has_spacer") is True, \
        "seeded spacer_dfs must produce has_spacer=True (critique round)"
    assert any(r.get("Name") == "Hematite" for r in ctx.get("spacers", [])), \
        "seeded spacer chemical missing from payload"
    assert ctx["preflush"]["volume"] == 80.0, ctx["preflush"].get("volume")
    assert any(r.get("Name") == "Salt" and r.get("amount") == "10080.0 lb"
               for r in ctx["preflush"].get("rows", [])), ctx["preflush"].get("rows")
    pytest.importorskip("docxtpl")
    from docxtpl import DocxTemplate
    template = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "master_template.docx")
    doc = DocxTemplate(template)
    doc.render(ctx)
    buffer = io.BytesIO()
    doc.save(buffer)
    rendered = buffer.getvalue()
    assert len(rendered) > 10000, \
        "rendered Word document missing or suspiciously small"
    rendered_xml = zipfile.ZipFile(io.BytesIO(rendered)).read(
        "word/document.xml").decode("utf-8")
    assert "Spacer Formulation Data" in rendered_xml, \
        "spacer table block did not render into the document (critique round)"
    assert "Hematite" in rendered_xml, \
        "seeded spacer chemical did not render into the document"
    assert "Pre Flush Data" in rendered_xml, \
        "pre-flush table block did not render into the document (F11)"
    assert "10080.0 lb" in rendered_xml, \
        "recomputed preflush NaCl row did not render into the document (F11/F1)"


# ===========================================================================
# GROUP C — Zero-Regression Contract Section 5 invariants (13 tests)
# ===========================================================================

def test_invariant_yield_reference():
    """§5 Yield: Lead 104 pcf/SG 3.20 -> 1.818; Tail 118 pcf -> 1.360."""
    lead = calculate_slurry_from_components(slurry_weight_pcf=104.0,
                                            slurry_volume_bbl=500.0, cmt_sg=3.20)
    tail = calculate_slurry_from_components(slurry_weight_pcf=118.0,
                                            slurry_volume_bbl=300.0, cmt_sg=3.20)
    assert abs(lead["yield_ft3_per_sk"] - 1.818) < 0.001
    assert abs(tail["yield_ft3_per_sk"] - 1.360) < 0.001


def test_invariant_lab_cup_reference():
    """§5 Lab cup: lab_cmt_gr = 1058.0 / yield; Lead reference -> 582.0 g."""
    lead = calculate_slurry_from_components(slurry_weight_pcf=104.0,
                                            slurry_volume_bbl=500.0, cmt_sg=3.20)
    cup = lead["lab_cmt_gr"]
    assert round(cup, 1) == 582.0, f"lab_cmt_gr={cup}"
    assert abs(cup - 1058.0 / lead["yield_ft3_per_sk"]) < 0.01


def test_invariant_mix_water_limit():
    """§5 Mix water: more than 20 ft³/sk raises ValueError."""
    for pcf in (62.5, 65.0, 70.0):
        with pytest.raises(ValueError):
            calculate_slurry_from_components(slurry_weight_pcf=pcf,
                                             slurry_volume_bbl=500.0, cmt_sg=3.20)
    res = calculate_slurry_from_components(slurry_weight_pcf=75.0,
                                           slurry_volume_bbl=500.0, cmt_sg=3.20)
    w = res["water_vol_per_sack"]
    assert math.isfinite(w) and 0 < w <= 20.0, w


def test_invariant_temperature_ordering():
    """§5 Temperature: BHCT <= BHST through lab_temperature_valid."""
    assert lab_temperature_valid(250, 260) is True
    assert lab_temperature_valid(270, 260) is False


def test_invariant_tvd_not_exceed_md():
    """§5 Depth: TVD > MD is flagged as physically inconsistent."""
    seeded = {"hardware_table": _benchmark_hardware(),
              "geo_md": 3000.0, "geo_tvd": 3100.0,
              "job_type": 'CSG 9 5/8"',
              "placement_config": {"job_type": 'CSG 9 5/8"', "target_row": TARGET_ROW}}
    status = compute_phase_status(seeded)
    assert "exceeds MD" in status["phase2_3"]["message"], \
        status["phase2_3"]["message"]


def test_invariant_parsing_signed_and_ranges():
    """§5 Parsing: '-118' -> -118.0; '80-82' -> 81.0; '-80-82' -> -81.0."""
    assert parse_effective_numeric("-118") == -118.0
    assert parse_effective_numeric("80-82") == 81.0
    assert parse_effective_numeric("-80-82") == pytest.approx(-81.0)


def test_invariant_digit_normalization():
    """§5 Digits: Persian and Arabic digits normalize to Latin before parsing."""
    assert parse_effective_numeric("۱۱۸") == 118.0
    assert normalize_digits("٨٢") == "82"


def test_invariant_density_and_rate_positive():
    """§5 Density/rate: positive only; rate range returns its minimum."""
    assert require_positive_density("104") == pytest.approx(104.0)
    assert require_positive_pump_rate("3.5-5.0") == pytest.approx(3.5)
    for bad in ("0", "-3", "0-5"):
        with pytest.raises(ValueError):
            require_positive_pump_rate(bad)


def test_invariant_time_format():
    """§5 Time: format_to_hr_mm(75.0) == '01:15'; negative raises ValueError."""
    assert format_to_hr_mm(75.0) == "01:15"
    with pytest.raises(ValueError):
        format_to_hr_mm(-1.0)


def test_invariant_json_io_rollback():
    """§5 JSON I/O: reject NaN/Infinity/duplicate keys; rollback on failure."""
    from main import deserialize_item
    for hostile in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a":1,"a":2}', b'[1,2]'):
        with pytest.raises(ValueError):
            project_io.decode_project(hostile, deserialize_item)

    class FlakyDict(dict):
        def __init__(self):
            super().__init__()
            self._armed = False

        def __setitem__(self, k, v):
            if self._armed:
                self._armed = False
                raise RuntimeError("transient write failure")
            super().__setitem__(k, v)

    state = FlakyDict()
    state["dead_vol"] = 5.0
    state["qc_bhct"] = 150.0
    state._armed = True
    with pytest.raises(RuntimeError):
        project_io.replace_project_state(state, {"a": 1, "b": 2}, "sig")
    assert state["dead_vol"] == 5.0 and state["qc_bhct"] == 150.0, dict(state)
    assert "a" not in state and "b" not in state \
        and "last_loaded_hash" not in state, dict(state)


def test_invariant_additive_forcing():
    """§5 Additives: liquids to 'In Mix Water'; FORCED_DRY_BLEND_NAMES to 'Dry Blend'."""
    assert normalize_additive_mix("Liquid", "Dry Blend", "Some Chemical")[0] == \
        "In Mix Water"
    forced = list(materials_db.FORCED_DRY_BLEND_NAMES)
    assert forced, "FORCED_DRY_BLEND_NAMES empty"
    assert normalize_additive_mix("Powder", "In Mix Water", forced[0])[0] == \
        "Dry Blend"


def test_invariant_word_notes_counter_and_escaping():
    """§5 Word notes: NoteCounter stays sequential and preserves reserved NOTE 20."""
    import phase_10_procedure as p10
    counter = p10.NoteCounter(reserved_numbers=(20,))
    notes = [counter.next("x") for _ in range(25)]
    numbers = [int(n.split()[1].rstrip(":")) for n in notes]
    assert numbers == [n for n in range(1, 27) if n != 20], numbers
    assert "NOTE 20" not in notes
    escaped = p10._escape_xml_special_chars('A&B<C>"D"')
    assert "&amp;" in escaped and "&lt;" in escaped and "&gt;" in escaped


def test_invariant_placement_mappings_stable():
    """§5 Placement: measured_depth and target_descriptions mappings stable."""
    assert placement.measured_depth("1200.0-2816.0") == 2816.0
    descriptions = placement.target_descriptions('CSG 9 5/8"')
    assert descriptions, "no target descriptions"
