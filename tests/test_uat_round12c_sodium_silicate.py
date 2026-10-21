"""Round 12C: catalog registration through the existing cement additive paths."""
from copy import deepcopy
from io import BytesIO
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docx import Document
import pandas as pd
import pytest

import test_audit_regressions as audit
import materials_db as db
import engineering_tools as eng
import phase_5_cement as phase5
import phase_7_lab as phase7
import phase_10_procedure as report
import project_state as ps
from centralizer_fixtures import ensure_current_centralizer
from test_uat_round10c_integration import save_project, restore_project


NAME = "Sodium Silicate"
IDENTITY = (NAME, "Liquid Extender", "Liquid")
CASE = audit.AuditRegressions()
TEMPLATE_SHA = "c213115a30353fdcdae1986f8cb08caaea0a7f2342880fc99872d131738b6670"


def stale_row(name=NAME, density=None, dosage=0.50):
    return pd.DataFrame([{
        "Material Type": "Other (Custom)", "Name": name,
        "Physical State": "Powder", "Mix Method": "Dry Blend",
        "User Input": dosage, "Density": density,
    }])


def test_canonical_identity():
    assert db.resolve_known_material(NAME) == IDENTITY


def test_catalog_membership():
    assert db.ALL_MATERIAL_NAMES.count(NAME) == 1
    assert db.MATERIAL_TAXONOMY["Liquid Extender"] == {
        "names": ["Micro Block", NAME], "state": "Liquid"}
    assert db.NAME_TO_MATERIAL[NAME] == IDENTITY[1:]
    assert db.NAME_TO_MATERIAL_CI[NAME.lower()] == IDENTITY
    assert db.MATERIAL_TYPES.count("Liquid Extender") == 1


def test_exact_liquid_property():
    assert eng.DEFAULT_LIQUID_PROPERTIES[NAME.lower()] == {
        "density_ppg": 1.50 * eng.WATER_LB_PER_GAL,
        "lab_factor": 1.50 * eng.WATER_LB_PER_GAL / eng.CEMENT_SACK_LB,
    }
    assert eng.default_additive_density_gcm3(NAME, "Liquid") == pytest.approx(1.50)


def test_phase5_normalizes_stale_identity_and_blank_density():
    row = phase5._normalize_additive_rows(stale_row()).iloc[0]
    assert tuple(row[key] for key in ("Name", "Material Type", "Physical State")) == IDENTITY
    assert row["Density"] == pytest.approx(1.50)
    assert eng.normalize_additive_mix(row["Physical State"], row["Mix Method"],
                                     row["Name"], row["Material Type"]) == ("In Mix Water", False)


@pytest.mark.parametrize("name", ["sodium silicate", "SODIUM SILICATE", "Sodium SILICATE"])
def test_case_insensitive_lookup_without_extra_catalog_names(name):
    assert db.resolve_known_material(name) == IDENTITY
    assert name not in db.ALL_MATERIAL_NAMES


@pytest.mark.parametrize("alias", ["Na2SiO3", "Water Glass", "Liquid Sodium Silicate"])
def test_unapproved_aliases_are_not_registered(alias):
    assert db.resolve_known_material(alias) is None
    assert alias not in db.ALL_MATERIAL_NAMES


@pytest.mark.parametrize("name,physical,sg", [
    ("Micro Block", "Liquid", 1.32), ("Liquid Extender", "Liquid", 1.32),
    ("Anti Foam", "Liquid", 62.17825699 / eng.WATER_DENSITY_PCF),
    ("Defoamer", "Liquid", 62.17825699 / eng.WATER_DENSITY_PCF),
    ("Anti Settling", "Powder", 157.9427643 / 62.4), ("NaCl", "Powder", 2.16),
])
def test_existing_material_density_controls(name, physical, sg):
    assert eng.default_additive_density_gcm3(name, physical) == pytest.approx(sg)
    if name == "Anti Settling":
        assert db.resolve_known_material(name) == (name, name, "Powder")
        assert sg == pytest.approx(2.53, abs=0.002)


def sodium(density=None, dosage=0.50):
    return phase5._normalize_additive_rows(stale_row(density=density, dosage=dosage))


def calculate(df):
    powders, liquids, salt = phase5.build_components(df)
    return eng.calculate_slurry_from_components(118.0, 50.0, cmt_sg=3.2,
                                                powders=powders, liquids=liquids, salt_pct=salt)


def test_measured_density_override_remains_authoritative():
    df = sodium(density=1.47)
    assert df.iloc[0]["Density"] == 1.47
    powders, liquids, salt = phase5.build_components(df)
    assert (powders, salt) == ([], 0.0)
    assert liquids[0]["density_ppg"] == 1.47 * eng.WATER_LB_PER_GAL
    assert liquids[0]["lab_factor"] == liquids[0]["density_ppg"] / eng.CEMENT_SACK_LB
    assert calculate(df)["ma_additives"] != calculate(sodium())["ma_additives"]


def test_build_components_uses_liquid_bucket_even_with_raw_dry_blend():
    df = sodium()
    assert df.iloc[0]["Mix Method"] == "Dry Blend"
    powders, liquids, salt = phase5.build_components(df)
    assert powders == []
    assert salt == 0.0
    assert liquids == [{"name": NAME, "gal_per_sk": 0.50,
                        "density_ppg": 1.50 * eng.WATER_LB_PER_GAL,
                        "lab_factor": 1.50 * eng.WATER_LB_PER_GAL / 110}]


def test_universal_mass_balance_and_lab_mass():
    result = calculate(sodium())
    assert all(math.isfinite(value) for value in result.values() if isinstance(value, (int, float)))
    assert result["field_liquids"] == [{"name": NAME, "gal_per_sk": 0.50,
                                        "field_gal": 0.50 * result["field_sacks"]}]
    assert result["ma_additives"] == pytest.approx(0.50 * 1.50 * eng.WATER_LB_PER_GAL)
    assert result["va_additives"] == pytest.approx(0.50 / eng.GAL_PER_CUFT)
    water = result["water_vol_per_sack"]
    assert (110 + result["ma_additives"] + water * eng.WATER_DENSITY_PCF) / result["yield_ft3_per_sk"] == pytest.approx(118)
    assert result["yield_ft3_per_sk"] == pytest.approx(110 / (3.2 * eng.WATER_DENSITY_PCF) + water + 0.50 / eng.GAL_PER_CUFT)
    assert result["lab_liquids"][0]["lab_gr"] > 0
    assert result["lab_liquids"][0]["lab_gr"] == pytest.approx(result["lab_cmt_gr"] * 0.50 * 1.50 * eng.WATER_LB_PER_GAL / 110)


def test_additives_table_preserves_dead_volume_basis_and_blend_separation():
    params = {"auto_calc": False, "total_sacks": 100.0, "mix_water": 25.0,
              "dead_vol": 5.0, "tank_name": "Batch Mixer Tanks"}
    before = deepcopy(params)
    blend, adds, note = phase5.build_cement_tables(params, sodium(), calculate(sodium()))
    assert params == before
    assert NAME not in blend["Name"].tolist()
    assert adds.to_dict("records") == [{
        "Item": 1, "Name": NAME, "Material Type": "Liquid Extender",
        "lbs or gal": "50.0 gal", "(lbs or gal)/sk": "0.50 gal/sk",
        "(lbs or gal)/bbl": "2.000 gal/bbl", "lbs or gal (with dead Vol.)": "60.0 gal"}]
    assert "**30.0 bbl**" in note


def test_phase7_uses_shared_liquid_mass_and_gal_per_sack():
    result = calculate(sodium())
    grid = phase7.build_lab_df_from_phase5(sodium(), cmt_sg=3.2, recalculate_mass=True)
    row = grid.loc[grid["Material"] == NAME].iloc[0]
    assert row["Unit"] == "gal/sk"
    assert row["Concentration"] == "0.50"
    assert float(row["Mass"]) > 0
    assert float(row["Mass"]) == pytest.approx(result["lab_liquids"][0]["lab_gr"], abs=0.05)


@pytest.fixture(scope="module")
def project():
    app = CASE.configured_app('CSG 9 5/8"')
    app.session_state["cement_additives_dfs"]["Main"] = stale_row()
    CASE.phase(app, "phase5")
    CASE.phase(app, "phase7")
    next(b for b in app.button if b.label == "Sync with Phase V").click().run()
    next(b for b in app.button if b.label == "Confirm measured lab results").click().run()
    CASE.healthy(app)
    ensure_current_centralizer(app.session_state)
    state = app.session_state.to_dict()
    assert ps.prepare_calculations(state) == []
    assert eng.compute_phase_status(state)["phase7"]["level"] == "ok"
    return state


def test_real_phase7_drift_and_sync_preserve_lot(project):
    app = CASE.app(audit.round_trip(project))
    CASE.phase(app, "phase7")
    grid = app.session_state["lab_grid_dfs"]["Main"]
    index = grid.index[grid["Material"] == NAME][0]
    grid.at[index, "Lot No"] = "SODIUM-LOT-12C"
    old_mass = grid.at[index, "Mass"]
    before = ps.lab_source_signature(app.session_state, "Main")
    app.session_state["cement_additives_dfs"]["Main"].at[0, "User Input"] = 0.75
    app.run()
    CASE.healthy(app)
    after = ps.lab_source_signature(app.session_state, "Main")
    assert after != before
    assert app.session_state["lab_source_signatures"]["Main"] != after
    assert any("Formulation Drift" in warning.value for warning in app.warning)
    assert any("Phase VII" in issue for issue in ps.prepare_calculations(app.session_state.to_dict()))
    next(b for b in app.button if b.label == "Sync with Phase V").click().run()
    CASE.healthy(app)
    row = app.session_state["lab_grid_dfs"]["Main"].loc[lambda df: df["Material"] == NAME].iloc[0]
    assert row["Concentration"] == "0.75"
    assert row["Mass"] != old_mass
    assert row["Lot No"] == "SODIUM-LOT-12C"
    assert app.session_state["lab_source_signatures"]["Main"] == after
    assert not app.session_state["lab_qc_params"]["Main"]["reviewed"]
    next(b for b in app.button if b.label == "Confirm measured lab results").click().run()
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "ok"


def test_real_save_restore_preserves_row_fields_and_rebuilds(project):
    raw = save_project(SimpleNamespace(session_state=deepcopy(project)))
    app = restore_project(raw)
    expected = project["cement_additives_dfs"]["Main"]
    assert app.session_state["cement_additives_dfs"]["Main"].to_dict("records") == expected.to_dict("records")
    CASE.phase(app, "phase5")
    assert app.session_state["cement_additives_dfs"]["Main"].to_dict("records") == expected.to_dict("records")
    assert phase5.refresh_cement_calculations(app.session_state.to_dict()) == []
    assert app.session_state["cement_calc_Main"].iloc[0]["Name"] == NAME


@pytest.mark.parametrize("density,expected", [(None, 1.50), (1.47, 1.47)])
def test_old_custom_row_self_heals_after_restore_and_render(project, density, expected):
    state = deepcopy(project)
    state["cement_additives_dfs"]["Main"] = stale_row(name="sodium silicate", density=density)
    raw = save_project(SimpleNamespace(session_state=state))
    app = restore_project(raw)
    CASE.phase(app, "phase5")
    row = app.session_state["cement_additives_dfs"]["Main"].iloc[0]
    assert tuple(row[key] for key in ("Name", "Material Type", "Physical State")) == IDENTITY
    assert row["Density"] == pytest.approx(expected)
    assert row["User Input"] == 0.50
    assert app.session_state["material_property_schema"] == eng.MATERIAL_PROPERTY_SCHEMA == 1
    assert NAME not in eng.LEGACY_ADDITIVE_SG


def test_inactive_slurry_archive_roundtrip_and_reactivation(project):
    state = deepcopy(project)
    expected = state["cement_additives_dfs"]["Main"].copy(deep=True)
    lab = state["lab_grid_dfs"]["Main"].copy(deep=True)
    state["fluids_config"]["active"].remove("Main")
    ps.purge_inactive_slurries(state, state["fluids_config"]["active"])
    assert "Main" not in state["cement_additives_dfs"]
    pd.testing.assert_frame_equal(state["inactive_slurry_drafts"]["Main"]["cement_additives_dfs"], expected)
    raw = save_project(SimpleNamespace(session_state=state))
    app = restore_project(raw)
    assert "Main" not in app.session_state["fluids_config"]["active"]
    state = app.session_state.to_dict()
    state["fluids_config"]["active"].append("Main")
    ps.purge_inactive_slurries(state, state["fluids_config"]["active"])
    assert "Main" not in state["inactive_slurry_drafts"]
    assert state["cement_additives_dfs"]["Main"].to_dict("records") == expected.to_dict("records")
    pd.testing.assert_frame_equal(state["lab_grid_dfs"]["Main"], lab)
    assert "Main" not in state["lab_source_signatures"]
    app = CASE.app(state)
    CASE.phase(app, "phase5")
    assert app.session_state["cement_additives_dfs"]["Main"].to_dict("records") == expected.to_dict("records")
    assert app.session_state["cement_calc_Main"].iloc[0]["Name"] == NAME


@pytest.mark.parametrize("names,line", [
    (["Anti Foam", NAME, "NaCl"], "Add Sodium Silicate and allow mixing for 10 min."),
    (["Anti Foam", NAME], "Add Sodium Silicate and allow mixing until the cement operation will finish."),
    ([NAME, "Anti Foam"], "Add Sodium Silicate to Fresh Water and allow mixing for 10 min."),
])
def test_generic_procedure_timing_and_position(names, line):
    text = report.build_additives_mixing_procedure("Main", pd.DataFrame({"Name": names}))
    assert line in text
    assert text.count(NAME) == 1


def test_actual_word_export_existing_additive_and_lab_tables(project, tmp_path):
    assert hashlib.sha256(Path(report.TEMPLATE_PATH).read_bytes()).hexdigest() == TEMPLATE_SHA
    app = restore_project(save_project(SimpleNamespace(session_state=deepcopy(project))))
    CASE.export(app)
    state = app.session_state.to_dict()
    with patch.object(report.st, "session_state", state):
        ctx = report.build_master_context()
    slurry = ctx["slurries"][0]
    assert [row["Name"] for row in slurry["additives"]] == [NAME]
    assert slurry["additives"][0]["Material Type"] == "Liquid Extender"
    assert NAME not in [row["Name"] for row in slurry["blends"]]
    lab = next(row for row in slurry["lab_additives"] if row["Code"] == NAME)
    assert lab["Material Type"] == "Liquid Extender"
    assert lab["Design Unit"] == "gal/sk"
    (tmp_path / "sodium-silicate.docx").write_bytes(state["_compiled_doc_bytes"])
    doc = Document(BytesIO(state["_compiled_doc_bytes"]))
    rows = [" | ".join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows]
    sodium_rows = [row for row in rows if NAME in row]
    assert len(sodium_rows) == 2, sodium_rows
    assert all("Liquid Extender" in row for row in sodium_rows)
    assert any("gal/sk" in row and "gal/bbl" in row for row in sodium_rows)
    assert any("gal/sk" in row and str(lab["Mass"]) in row for row in sodium_rows)
    assert "Sodium Silicate" in ctx["procedure_text"]
    assert hashlib.sha256(Path(report.TEMPLATE_PATH).read_bytes()).hexdigest() == TEMPLATE_SHA


def test_spacer_diesel_liner_and_schema_controls():
    assert NAME not in db.SPACER_CHEMICALS
    assert NAME not in db.WEIGHTING_AGENTS
    assert NAME not in db.PREFLUSH_CHEMICALS
    assert NAME not in db.FORCED_DRY_BLEND_NAMES
    assert 'LNR 4 1/2"' in db.JOB_TYPES
    assert db.DEFAULT_HOLE_SIZES['LNR 4 1/2"'] == '6"'
    order = db.HYDRAULIC_EXECUTION_ORDER
    assert order.index("Diesel") + 1 == order.index("Pre Flush")
    assert "Diesel" in db.PHASE7_LAB_FLUIDS
    assert "Diesel" not in db.CEMENT_FORMULATION_FLUIDS
    assert eng.MATERIAL_PROPERTY_SCHEMA == 1
    assert NAME not in eng.LEGACY_ADDITIVE_SG
