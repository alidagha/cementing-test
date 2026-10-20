"""Gate A2: finished-Spacer cup, shared measured rheology and review lifecycle."""
from copy import deepcopy
import json
import math
import pytest

import engineering_tools as et
import project_state as ps
import standalone_spacer as sp
import materials_db as db
import rheology
import test_audit_regressions as audit
from project_io import decode_project, replace_project_state
from test_round13a_a1_standalone_spacer import state as a1_state
from test_uat_round10c_integration import save_project, restore_project

CASE = audit.AuditRegressions()


def state(mode="Limestone + Barite", dead=0.):
    result = a1_state(mode, dead)
    result.update(audit.well_profile_fixture(100., bhst=200.))
    result["bhct"] = 150.
    result["well_data"] = {"bhct": 150., "bhst": 200.}
    ps.refresh_fluids(result)
    return result


def test_mix_a_finished_cup_benchmark():
    recipe = sp.formulation_from_state(state())
    sample = sp.lab_sample(recipe)
    assert sample["mass_g"] == pytest.approx(1057.2185827, abs=5e-8)
    assert sample["volume_ml"] == pytest.approx(600., abs=1e-9)
    assert sample["density_pcf"] == pytest.approx(110., abs=1e-9)
    assert [r["Material"] for r in sample["rows"]] == [
        "Fresh Water", "Salt", "O-Spacer", "Surfactant", "Defoamer", "Limestone", "Barite"]


def test_spacer_tab_and_only_applicable_sections():
    app = CASE.app(state())
    CASE.phase(app, "phase7")
    assert [tab.label for tab in app.tabs] == ["Spacer"]
    text = "\n".join(item.value for item in app.markdown)
    assert "Spacer Lab Data" in [item.value for item in app.subheader]
    assert "Blend & Additives — 600 mL Cup" in text
    assert "Fann 35 / R1B1 / Spring 1.0" in text
    assert not any(word in text for word in ("Test Basic Data", "Thickening", "Compressive", "Free Water"))
    assert len(app.dataframe) == 1


def test_unreviewed_spacer_is_not_ready():
    result = et.compute_phase_status(state())["phase7"]
    assert result["level"] == "warning" and "Spacer" in result["message"]


def test_composition_source_signature_is_not_cement_signature():
    source = state("Barite")
    before = ps.lab_source_signature(source, "Spacer")
    source[sp.CONFIG_KEY]["mode"] = "Ferro Bar"
    assert ps.lab_source_signature(source, "Spacer") != before


def test_source_signature_uses_full_precision_not_rounded_table():
    source = state("Barite")
    before = ps.lab_source_signature(source, "Spacer")
    grid = ps.spacer_lab_grid(source)
    source["fluids_config"]["params"]["Spacer"]["density"] = "110.000000000001"
    assert ps.spacer_lab_grid(source).equals(grid)
    assert ps.lab_source_signature(source, "Spacer") != before


def measured(source):
    ps.refresh_spacer_lab(source)
    qc = source["lab_qc_params"]["Spacer"]
    qc["rheology"] = audit.valid_export_rheology_fixture()
    qc["reviewed"] = True
    qc["review_signature"] = et.lab_review_signature(qc, source["lab_grid_dfs"]["Spacer"])
    return source


@pytest.mark.parametrize("mode,density", [("Limestone", 75), ("Limestone", 100),
    ("Barite", 75), ("Barite", 125), ("Ferro Bar", 75), ("Ferro Bar", 160),
    ("Limestone + Barite", 100), ("Limestone + Barite", 110), ("Limestone + Barite", 125)])
def test_all_modes_independent_cup_closure_and_concentration_bases(mode, density):
    source = state(mode)
    source["fluids_config"]["params"]["Spacer"]["density"] = str(density)
    source[sp.CONFIG_KEY]["barite_available_lb"] = 20000.
    recipe = sp.formulation_from_state(source)
    before = deepcopy(recipe)
    sample = sp.lab_sample(recipe)
    assert recipe == before
    rows = {row["Material"]: row for row in sample["rows"]}
    grams = {name: row["Mass"] for name, row in rows.items()}
    # Independent reconstruction: dissolved salt shares brine solution volume.
    ml = (grams["Fresh Water"] + grams["Salt"]) / 1.20113
    ml += grams["O-Spacer"] / 1.62 + grams["Surfactant"] / .94 + grams["Defoamer"]
    for material, sg in (("Limestone", 2.70), ("Barite", 4.20), ("Ferro Bar", 4.80)):
        if material in grams:
            ml += grams[material] / sg
    total = math.fsum(grams.values())
    assert ml == pytest.approx(600., abs=1e-9)
    assert total == pytest.approx(density * (42 / 7.48051948051948) * 600 / 158987.294928 * 453.59237, rel=1e-12)
    assert sample["mass_g"] == total
    assert rows["Salt"]["Concentration"] == 126.
    assert rows["Salt"]["Unit"] == "lb/bbl freshwater"
    assert rows["Surfactant"]["Unit"] == "gal/bbl freshwater"
    assert rows["Defoamer"]["Unit"] == "gal/bbl finished Spacer"
    assert grams["Defoamer"] == pytest.approx(600 * .5 / 42, rel=1e-13)
    assert set(grams) == {"Fresh Water", *[row["name"] for row in recipe["materials"]]}


@pytest.mark.parametrize("change", ["tank", "dead", "volume", "unused_inventory"])
def test_solo_independent_sources_do_not_drift_lab_or_erase_review(change):
    source = measured(state("Barite"))
    before = ps.lab_source_signature(source, "Spacer")
    original = deepcopy(source["lab_qc_params"]["Spacer"])
    if change == "tank":
        source[sp.CONFIG_KEY]["tank_name"] = "Cement Unit Tanks"
    elif change == "dead":
        source[sp.CONFIG_KEY]["dead_vol"] = 5.
    elif change == "volume":
        source["fluids_config"]["params"]["Spacer"]["volume"] = 32.
    else:
        source[sp.CONFIG_KEY]["limestone_available_lb"] = 9000.
    assert ps.lab_source_signature(source, "Spacer") == before
    ps.spacer_lab_payload(source)
    assert source["lab_qc_params"]["Spacer"] == original


@pytest.mark.parametrize("change", ["density", "mode", "mix_dead", "inventory", "mix_volume", "bhct", "bhst"])
def test_consumed_changes_rebuild_masses_preserve_manual_data_and_retire_review(change):
    source = measured(state())
    source["lab_grid_dfs"]["Spacer"].loc[0, "Lot No"] = "FW lot 01"
    source["lab_qc_params"]["Spacer"]["review_signature"] = et.lab_review_signature(
        source["lab_qc_params"]["Spacer"], source["lab_grid_dfs"]["Spacer"])
    before = ps.lab_source_signature(source, "Spacer")
    manual = deepcopy(source["lab_qc_params"]["Spacer"]["rheology"])
    source["_compiled_doc_bytes"] = b"old document"
    source["lab_payload_Spacer"] = {"stale": True}
    if change == "density":
        source["fluids_config"]["params"]["Spacer"]["density"] = "111"
    elif change == "mode":
        source[sp.CONFIG_KEY]["mode"] = "Barite"
    elif change == "mix_dead":
        source[sp.CONFIG_KEY]["dead_vol"] = 1.
    elif change == "inventory":
        source[sp.CONFIG_KEY]["limestone_available_lb"] = 1400.
    elif change == "mix_volume":
        source["fluids_config"]["params"]["Spacer"]["volume"] = 19.
    else:
        source["well_data"][change] += 1.
    assert ps.lab_source_signature(source, "Spacer") != before
    ps.refresh_spacer_lab(source)
    assert source["lab_grid_dfs"]["Spacer"].iloc[0]["Lot No"] == "FW lot 01"
    assert source["lab_qc_params"]["Spacer"]["rheology"] == manual
    assert source["lab_qc_params"]["Spacer"]["reviewed"] is False
    assert "_compiled_doc_bytes" not in source and "lab_payload_Spacer" not in source
    with pytest.raises(ValueError, match="Confirm measured"):
        ps.spacer_lab_payload(source)
    assert et.compute_phase_status(source)["phase7"]["level"] == "warning"


def test_readiness_is_pure_and_repeated_rebuild_is_stable():
    source = measured(state())
    before = ps.fingerprint(source)
    for _ in range(3):
        assert et.compute_phase_status(source)["phase7"]["level"] == "ok"
        assert ps.fingerprint(source) == before
        ps.spacer_lab_payload(source)
        assert ps.fingerprint(source) == before
    blank = state()
    before = ps.fingerprint(blank)
    et.compute_phase_status(blank)
    assert ps.fingerprint(blank) == before


@pytest.mark.parametrize("defect", ["empty", "one_point", "gel", "invalid_fit", "selected_incomplete", "bhct", "review"])
def test_incomplete_or_invalid_measurements_never_ready(defect):
    source = measured(state())
    qc = source["lab_qc_params"]["Spacer"]
    if defect == "empty":
        qc["rheology"] = {}
    elif defect == "one_point":
        qc["rheology"]["bhct_down"]["readings"] = {"300": "168"}
    elif defect == "gel":
        qc["rheology"]["bhct_down"]["gel_10_sec"] = ""
    elif defect == "invalid_fit":
        qc["rheology"]["bhct_down"]["readings"] = dict(zip(map(str, rheology.RPM_ORDER), map(str, (150,100,50,30,15,2,1))))
    elif defect == "selected_incomplete":
        qc["rheology"]["bhct_up"] = {**rheology.new_rheology_dataset(), "selected": True}
    elif defect == "bhct":
        source["well_data"]["bhct"] = 201.
    else:
        qc["reviewed"] = False
    assert et.compute_phase_status(source)["phase7"]["level"] == "warning"
    assert any("Spacer" in issue for issue in ps.refresh_lab_payloads(source))
    assert "lab_payload_Spacer" not in source


def test_bingham_authority_unchanged_with_no_cement_qc_requirement():
    source = measured(state())
    actual = ps.spacer_lab_payload(source)
    expected, issues = rheology.build_rheology(source["lab_qc_params"]["Spacer"])
    assert not issues and actual["rheology"] == expected
    assert set(actual) == {"grid", "rheology", "bhct", "bhst"}
    assert set(source["lab_qc_params"]["Spacer"]) == {"rheology", "reviewed", "review_signature"}
    assert "Spacer" not in db.PHASE7_LAB_FLUIDS  # A3 routing not implemented by A2.


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def edit_lot_with_navigation(app, index, value):
    editor = next(item for item in app.dataframe if "_editor_lab_tbl_spacer_" in item.proto.id)
    app.radio(key="_app_mode_key").set_value("phase1")
    widgets = app._tree.get_widget_states()
    event = widgets.widgets.add()
    event.id = editor.proto.id
    event.string_value = json.dumps({"edited_rows": {str(index): {"Lot No": value}}, "added_rows": [], "deleted_rows": []})
    app._run(widgets)
    CASE.healthy(app)


def test_first_manual_edits_navigation_confirmation_and_actual_project_restore():
    app = CASE.app(state())
    CASE.phase(app, "phase7")
    editor = next(item for item in app.dataframe if "_editor_lab_tbl_spacer_" in item.proto.id)
    columns = json.loads(editor.proto.columns)
    assert all(columns[name]["disabled"] for name in ("Material", "Concentration", "Unit", "Mass"))
    assert not columns["Lot No"].get("disabled", False)
    assert widget(app, "button", "Confirm measured lab results").disabled
    widget(app, "checkbox", "BHCT — Ramp-Down - Spacer").check().run()
    assert widget(app, "button", "Confirm measured lab results").disabled
    readings = audit.valid_export_rheology_fixture()["bhct_down"]
    for rpm in rheology.RPM_ORDER:
        widget(app, "text_input", f"{rpm} RPM - BHCT — Ramp-Down - Spacer").set_value(readings["readings"][str(rpm)])
        CASE.phase(app, "phase1")
        CASE.phase(app, "phase7")
        assert widget(app, "text_input", f"{rpm} RPM - BHCT — Ramp-Down - Spacer").value == readings["readings"][str(rpm)]
    for label, value in (("10 Sec Gel", "8"), ("10 Min Gel", "12")):
        widget(app, "text_input", f"{label} - BHCT — Ramp-Down - Spacer").set_value(value).run()
    edit_lot_with_navigation(app, 0, "Water lot α & <1>")
    CASE.phase(app, "phase7")
    assert app.session_state["lab_grid_dfs"]["Spacer"].iloc[0]["Lot No"] == "Water lot α & <1>"
    widget(app, "button", "Confirm measured lab results").click().run()
    assert et.compute_phase_status(app.session_state)["phase7"]["level"] == "ok"
    expected = deepcopy(app.session_state["lab_qc_params"]["Spacer"])
    # UI-01's real snapshot preparation remains available after lab edits.
    widget(app, "button", "Prepare project download").click().run()
    assert app.get("download_button")
    raw = save_project(app)
    restored = restore_project(raw)
    CASE.phase(restored, "phase7")
    assert restored.session_state["lab_qc_params"]["Spacer"] == expected
    assert restored.session_state["lab_grid_dfs"]["Spacer"].iloc[0]["Lot No"] == "Water lot α & <1>"
    assert et.compute_phase_status(restored.session_state)["phase7"]["level"] == "ok"
    widget(restored, "text_input", "300 RPM - BHCT — Ramp-Down - Spacer").set_value("169")
    CASE.phase(restored, "phase1")
    assert restored.session_state["lab_qc_params"]["Spacer"]["rheology"]["bhct_down"]["readings"]["300"] == "169"
    assert not restored.session_state["lab_qc_params"]["Spacer"]["reviewed"]
    assert et.compute_phase_status(restored.session_state)["phase7"]["level"] == "warning"


def test_inactive_manual_draft_cannot_satisfy_reactivation_review():
    source = measured(state())
    app = CASE.app(source)
    CASE.phase(app, "phase7")
    manual = deepcopy(app.session_state["lab_qc_params"]["Spacer"]["rheology"])
    edit_lot_with_navigation(app, 0, "retain")
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_Spacer").uncheck().run()
    assert "Spacer" not in app.session_state["fluid_data"]
    assert sp.CONFIG_KEY not in app.session_state
    restored = restore_project(save_project(app))
    CASE.phase(restored, "phase4")
    restored.checkbox(key="chk_fluid_Spacer").check().run()
    CASE.phase(restored, "phase7")
    assert restored.error  # Phase VI cleared source, not an old lab recipe.
    CASE.phase(restored, "phase6")
    audit.configure_standalone_spacer(restored, mode="Barite", dead_vol=0.)
    CASE.phase(restored, "phase7")
    assert not restored.error
    assert restored.session_state["lab_grid_dfs"]["Spacer"].iloc[0]["Lot No"] == "retain"
    assert restored.session_state["lab_qc_params"]["Spacer"]["rheology"] == manual
    assert not restored.session_state["lab_qc_params"]["Spacer"]["reviewed"]


@pytest.mark.parametrize("change", ["mass", "unit", "concentration", "material", "source"])
def test_saved_computed_cache_cannot_override_canonical_recipe(change):
    source = measured(state())
    source["lab_grid_dfs"]["Spacer"].loc[0, "Lot No"] = "keep"
    if change == "source":
        source[sp.CONFIG_KEY]["dead_vol"] = 1.
    else:
        field = {"mass": "Mass", "unit": "Unit", "concentration": "Concentration", "material": "Material"}[change]
        source["lab_grid_dfs"]["Spacer"].loc[1, field] = "99999"
    restored = CASE.app(audit.round_trip(source))
    CASE.phase(restored, "phase7")
    assert not restored.error
    grid = restored.session_state["lab_grid_dfs"]["Spacer"]
    assert grid.iloc[1]["Material"] == "Salt"
    assert grid.iloc[1]["Concentration"] == "126"
    assert grid.iloc[1]["Unit"] == "lb/bbl freshwater"
    assert grid.iloc[1]["Mass"] != "99999"
    assert grid.iloc[0]["Lot No"] == "keep"
    assert et.compute_phase_status(restored.session_state)["phase7"]["level"] == "warning"


@pytest.mark.parametrize("bad", [
    {"rheology": []}, {"rheology": {"foreign": {}}},
    {"rheology": {"bhct_down": {"selected": "true"}}},
    {"rheology": {"bhct_down": {"readings": {"600": 20}}}},
    {"rheology": {"bhct_down": {"readings": {"300": True}}}},
    {"rheology": {"bhct_down": {"gel_10_sec": "NaN"}}},
    {"reviewed": "true"}, {"review_signature": []}])
def test_malformed_lab_import_rejected_before_publication(bad):
    current = state()
    before = ps.fingerprint(current)
    project = state()
    project["lab_qc_params"] = {"Spacer": bad}
    raw = json.dumps(audit.namespace["serialize_item"](project), allow_nan=False).encode()
    with pytest.raises(ValueError):
        decoded = decode_project(raw, audit.namespace["deserialize_item"])
        replace_project_state(current, decoded, "unexpected")
    assert ps.fingerprint(current) == before


def test_compiled_document_retires_on_lot_edit_and_final_word_stays_blocked():
    app = CASE.app(measured(state()))
    CASE.phase(app, "phase7")
    app.session_state["_compiled_doc_bytes"] = b"old"
    edit_lot_with_navigation(app, 1, "Salt lot updated")
    assert "_compiled_doc_bytes" not in app.session_state
    assert "lab_payload_Spacer" not in app.session_state
    CASE.phase(app, "phase10")
    assert widget(app, "button", "Build Word Document").disabled
    assert any("Gates A2–A4" in error.value for error in app.error)


def test_real_phase_iv_order_tabs_and_manual_sources_stay_independent():
    source = state()
    cfg = source["fluids_config"]
    cfg["active"] = ["Diesel", "Spacer", "Spacer Ahead", "Main", "Spacer Behind"]
    for fluid, density in (("Diesel", "51"), ("Spacer Ahead", "90"), ("Main", "118"), ("Spacer Behind", "90")):
        cfg["params"][fluid] = {"volume": 5., "density": density, "pump_rate": "3-5"}
    source["mud_type"] = "OBM"
    source["well_data"]["mud_type"] = "OBM"
    source["lab_qc_params"] = {"Diesel": {"rheology": audit.valid_export_rheology_fixture()}}
    app = CASE.app(source)
    CASE.phase(app, "phase4")
    CASE.phase(app, "phase7")
    assert [tab.label for tab in app.tabs] == ["Diesel", "Spacer", "Main"]
    before = deepcopy(app.session_state["lab_qc_params"]["Diesel"])
    widget(app, "checkbox", "Surface — Ramp-Down - Spacer").check().run()
    widget(app, "text_input", "300 RPM - Surface — Ramp-Down - Spacer").set_value("168")
    CASE.phase(app, "phase6")
    assert app.session_state["lab_qc_params"]["Diesel"] == before
    CASE.phase(app, "phase7")
    assert widget(app, "text_input", "300 RPM - Surface — Ramp-Down - Spacer").value == "168"


def test_mode_and_inventory_ui_changes_rebuild_current_cup_with_metadata():
    app = CASE.app(measured(state()))
    CASE.phase(app, "phase7")
    manual = deepcopy(app.session_state["lab_qc_params"]["Spacer"]["rheology"])
    edit_lot_with_navigation(app, 0, "Water retained")
    CASE.phase(app, "phase6")
    widget(app, "number_input", "Dead Volume (bbl) - Spacer").set_value(1.)
    CASE.phase(app, "phase7")
    grid_d = app.session_state["lab_grid_dfs"]["Spacer"].copy()
    assert grid_d.iloc[0]["Lot No"] == "Water retained"
    expected = 1390.942174 * 453.59237 * 600 / (20 * 158987.294928)
    assert float(grid_d.loc[grid_d["Material"] == "Limestone", "Mass"].iloc[0]) == pytest.approx(expected, abs=6e-8)
    CASE.phase(app, "phase6")
    widget(app, "selectbox", "Weighting Agent Mode").set_value("Barite")
    CASE.phase(app, "phase7")
    grid = app.session_state["lab_grid_dfs"]["Spacer"]
    assert "Limestone" not in set(grid["Material"])
    assert grid.iloc[0]["Lot No"] == "Water retained"
    assert app.session_state["lab_qc_params"]["Spacer"]["rheology"] == manual
    assert et.compute_phase_status(app.session_state)["phase7"]["level"] == "warning"


@pytest.mark.parametrize("defect", ["mode", "density", "volume", "inventory"])
def test_invalid_formulation_retires_payload_and_cannot_recover_old_review(defect):
    source = measured(state())
    source["lab_payload_Spacer"] = ps.spacer_lab_payload(source)
    source["_compiled_doc_bytes"] = b"stale"
    original = deepcopy(source)
    if defect == "mode":
        source[sp.CONFIG_KEY]["mode"] = None
    elif defect == "density":
        source["fluids_config"]["params"]["Spacer"]["density"] = "110-111"
    elif defect == "volume":
        source["fluids_config"]["params"]["Spacer"]["volume"] = 0.
    else:
        source[sp.CONFIG_KEY]["barite_available_lb"] = 1.
    assert ps.refresh_lab_payloads(source)
    assert "lab_payload_Spacer" not in source and "_compiled_doc_bytes" not in source
    source[sp.CONFIG_KEY] = original[sp.CONFIG_KEY]
    source["fluids_config"] = original["fluids_config"]
    assert et.compute_phase_status(source)["phase7"]["level"] == "warning"
    with pytest.raises(ValueError, match="Confirm measured"):
        ps.spacer_lab_payload(source)


def test_publication_failure_rolls_back_spacer_manual_data():
    class FailOnce(dict):
        failed = False
        def __setitem__(self, key, value):
            if key == "last_loaded_hash" and not self.failed:
                self.failed = True
                raise RuntimeError("controlled publication failure")
            super().__setitem__(key, value)
    original = measured(state())
    original["lab_grid_dfs"]["Spacer"].loc[0, "Lot No"] = "rollback lot"
    current = FailOnce(deepcopy(original))
    before = ps.fingerprint(current)
    with pytest.raises(RuntimeError, match="controlled publication"):
        replace_project_state(current, state("Ferro Bar"), "new project")
    assert ps.fingerprint(current) == before
