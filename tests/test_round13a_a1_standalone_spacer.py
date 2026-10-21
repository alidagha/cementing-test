"""Gate A1: fixed-20°C balances, input ownership and unfinished-export safety."""
from copy import deepcopy
from decimal import Decimal, localcontext
from unittest.mock import patch
import json
import math

import pandas as pd
import pytest

import cement_chart_model as chart
import engineering_tools as et
import materials_db as db
import phase_10_procedure as report
import project_state as ps
import centralizer_adapter
import pumping_simulation
import standalone_spacer as sp
from project_io import decode_project, replace_project_state
import test_audit_regressions as audit
import test_regression_guardrails as guards
from test_uat_round10a_pumping_simulation import program_state
from test_uat_round9e_dynamic_solver import reviewed_spacer
from test_uat_round10c_integration import restore_project

CASE = audit.AuditRegressions()


def state(mode="Barite", dead=5., job='CMT PLUG'):
    return {"job_type": job, "mud_density": "80", "fluids_config": {
        "active": ["Spacer"], "params": {"Spacer": {"volume": 20., "density": "110",
        "pump_rate": "3-5", "material_name": "Weighted Spacer"}}},
        sp.CONFIG_KEY: {"mode": mode, "dead_vol": dead, "tank_name": db.get_tank_name(job),
                        "limestone_available_lb": 1500., "barite_available_lb": 5000.}}


def oracle(volume, density, agent):
    """Independent high-precision solution of the handoff's two balances."""
    with localcontext() as ctx:
        ctx.prec = 45
        D = Decimal
        rbbl = lambda rho: D(str(rho)) * D("0.158987294928") * D("2.2046226218487758")
        rw, br = rbbl("998.20675"), rbbl("1201.13")
        ro, rs, rd = rbbl(1620), rbbl(940), rbbl(1000)
        ra = rbbl({"Limestone": 2700, "Barite": 4200, "Ferro Bar": 4800}[agent])
        a = rw + 126 + 10 + D(2) / 42 * rs + D(".5") / 42 * rd
        b = (rw + 126) / br + 10 / ro + D(2) / 42 + D(".5") / 42
        v, t = D(str(volume)), D(str(density)) * 42 / D("7.48051948051948")
        water = v * (1 - t / ra) / (b - a / ra)
        return float(water), float(v * t - a * water)


def assert_closure(recipe):
    # Reconstruct from ingredient quantities, not the solver's closure fields.
    q = {r["name"]: r["base"] for r in recipe["materials"]}
    water = recipe["water_base_bbl"]
    kg_lb, bbl_m3 = 2.2046226218487758, .158987294928
    per_bbl = lambda rho: rho * bbl_m3 * kg_lb
    mass = water * per_bbl(998.20675) + q["Salt"] + q["O-Spacer"]
    mass += q["Surfactant"] / 42 * per_bbl(940) + q["Defoamer"] / 42 * per_bbl(1000)
    mass += sum(recipe["solids_lb"].values())
    volume = (water * per_bbl(998.20675) + q["Salt"]) / per_bbl(1201.13)
    volume += q["O-Spacer"] / per_bbl(1620) + q["Surfactant"] / 42 + q["Defoamer"] / 42
    volume += sum(m / per_bbl({"Limestone": 2700, "Barite": 4200, "Ferro Bar": 4800}[n])
                  for n, m in recipe["solids_lb"].items())
    assert volume == pytest.approx(recipe["volume_bbl"], rel=1e-12)
    assert mass == pytest.approx(recipe["density_pcf"] * recipe["volume_bbl"] * 42 / 7.48051948051948, rel=1e-12)
    assert mass / volume / (42 / 7.48051948051948) == pytest.approx(recipe["density_pcf"], abs=1e-10)
    for row in recipe["materials"]:
        assert row["gross"] == pytest.approx(row["base"] * recipe["scale"], rel=1e-14)
    assert all(math.isfinite(n) for n in recipe["closure"].values())


@pytest.mark.parametrize("agent,density", [
    ("Limestone", 75), ("Limestone", 95), ("Limestone", 100), ("Barite", 75),
    ("Barite", 100), ("Barite", 110), ("Barite", 125), ("Ferro Bar", 75),
    ("Ferro Bar", 125), ("Ferro Bar", 140), ("Ferro Bar", 160)])
def test_solo_endpoints_and_decimal_oracle(agent, density):
    r = sp.calculate_spacer(20., density, agent, 0.)
    expected_w, expected_m = oracle(20, density, agent)
    assert r["water_base_bbl"] == pytest.approx(expected_w, rel=1e-13)
    assert r["solids_lb"][agent] == pytest.approx(expected_m, rel=1e-12)
    assert_closure(r)


def mix_oracle(volume, density, dead, stock_l):
    """45-digit simultaneous balances plus the gross-stock quadratic root."""
    with localcontext() as context:
        context.prec = 45
        D = Decimal
        v, rho, dead, stock = map(lambda x: D(str(x)), (volume, density, dead, stock_l))
        rb = lambda r: D(str(r)) * D(".158987294928") * D("2.2046226218487758")
        rw, br, ro, rs, rd, rl, rh = map(rb, ("998.20675", "1201.13", 1620, 940, 1000, 2700, 4200))
        a = rw + 126 + 10 + D(2) / 42 * rs + D(".5") / 42 * rd
        b = (rw + 126) / br + 10 / ro + D(2) / 42 + D(".5") / 42
        t = rho * 42 / D("7.48051948051948")
        t100 = D(100) * 42 / D("7.48051948051948")
        cap_water = v * (rl - t100) / (rl * b - a)
        cap = v * t100 - a * cap_water
        intercept = v * (rh - t) / (rh * b - a)
        slope = (1 - rh / rl) / (rh * b - a)
        coefficient = intercept + dead - stock * slope
        stock_limit = 2 * stock * intercept / (coefficient + (coefficient**2 + 4 * slope * stock * intercept).sqrt())
        limestone = min(cap, stock_limit)
        water = intercept + slope * limestone
        barite = v * t - a * water - limestone
        return tuple(float(x) for x in (water, limestone, barite, cap))


@pytest.mark.parametrize("dead,stock_l,stock_b", [(0., 1500., 5000.),
    (0., 10000., 10000.), (1., 1500., 5000.)])
def test_mix_a_b_d_gross_inventory_and_maximum_limestone(dead, stock_l, stock_b):
    r = sp.calculate_spacer(20, 110, "Limestone + Barite", dead, stock_l, stock_b)
    w, l, b, _ = mix_oracle(20, 110, dead, stock_l)
    assert r["water_base_bbl"] == pytest.approx(w, rel=2e-13)
    assert r["solids_lb"]["Limestone"] == pytest.approx(l, rel=2e-13)
    assert r["solids_lb"]["Barite"] == pytest.approx(b, rel=2e-13)
    assert r["inventory"]["Barite"]["used_lb"] == pytest.approx(b * (1 + dead / w), rel=2e-13)
    assert all(0 <= v["remaining_lb"] <= v["available_lb"] for v in r["inventory"].values())
    cap = oracle(20, 100, "Limestone")[1]
    if r["solids_lb"]["Limestone"] < cap - 1e-6:
        assert r["inventory"]["Limestone"]["used_lb"] == pytest.approx(stock_l, abs=1e-9)
    else:
        assert r["solids_lb"]["Limestone"] == pytest.approx(cap, abs=1e-9)
    assert_closure(r)


def test_mix_c_shortage_and_100_pcf_true_mix_rule():
    need = mix_oracle(20, 110, 0, 1500)[2]
    with pytest.raises(ValueError, match=rf"Barite inventory shortage.*{need:.6f}.*{need - 4000:.6f}"):
        sp.calculate_spacer(20, 110, "Limestone + Barite", 0, 1500, 4000)
    with pytest.raises(ValueError, match="zero-Barite.*Limestone-only"):
        sp.calculate_spacer(20, 100, "Limestone + Barite", 0, 10000, 10000)
    assert_closure(sp.calculate_spacer(20, 100, "Limestone + Barite", 0, 1500, 5000))


def test_dead_volume_full_composition_and_display_bases():
    source = state()
    before = ps.fingerprint(source)
    r = sp.formulation_from_state(source)
    assert ps.fingerprint(source) == before
    assert r["water_base_bbl"] == pytest.approx(13.4378344880, abs=1e-10)
    assert r["water_total_bbl"] == pytest.approx(18.4378344880, abs=1e-10)
    assert r["mixed_volume_bbl"] == pytest.approx(20 * (1 + 5 / oracle(20, 110, "Barite")[0]), rel=1e-13)
    assert r["pumped_volume_bbl"] == source["fluids_config"]["params"]["Spacer"]["volume"] == 20.
    rows = sp.field_rows(r)
    assert list(rows[0]) == sp.FIELD_COLUMNS and len(rows[0]) == 6
    assert [row["Name"] for row in rows] == ["Salt", "O-Spacer", "Surfactant", "Defoamer", "Barite"]
    assert [row[sp.FIELD_COLUMNS[5]] for row in rows] == [f"{et.round_half_up(row['base'] * (1 + 5 / oracle(20, 110, 'Barite')[0]), 1):.1f} {row['unit']}" for row in r["materials"]]
    assert r["materials"][3]["basis"] == "freshwater"
    assert r["materials"][3]["gross"] == pytest.approx(.5 * r["water_total_bbl"], rel=1e-14)
    assert r["note"] == f"Mix above Additives in 18.4 bbl Fresh Water at {db.get_tank_name('CMT PLUG')}."
    assert_closure(r)


@pytest.mark.parametrize("mode,density", [("Limestone", 74.99), ("Limestone", 100.01),
    ("Barite", 74.99), ("Barite", 125.01), ("Ferro Bar", 74.99), ("Ferro Bar", 160.01),
    ("Limestone + Barite", 99.99), ("Limestone + Barite", 125.01), (None, 110), ("Ferro + Barite", 110)])
def test_mode_density_bands(mode, density):
    with pytest.raises(ValueError):
        sp.calculate_spacer(20, density, mode, 0, 1500, 5000)


@pytest.mark.parametrize("field,value", [("volume_bbl", 0), ("volume_bbl", -1),
    ("volume_bbl", True), ("volume_bbl", "bad"), ("density_pcf", "115-118"),
    ("density_pcf", False), ("density_pcf", float("nan")), ("dead_vol_bbl", -1),
    ("dead_vol_bbl", float("inf")), ("limestone_available_lb", 0),
    ("barite_available_lb", -1), ("barite_available_lb", None)])
def test_controlled_invalid_inputs(field, value):
    args = dict(volume_bbl=20, density_pcf=110, mode="Limestone + Barite", dead_vol_bbl=0,
                limestone_available_lb=1500, barite_available_lb=5000)
    args[field] = value
    with pytest.raises(ValueError):
        sp.calculate_spacer(**args)


@pytest.mark.parametrize("value", [110, 110., "110", "110.0", "۱۱۰"])
def test_spacer_scalar_representations(value):
    assert et.require_fluid_density("Spacer", value) == 110.


@pytest.mark.parametrize("value", ["115-118", "115/118", "0", "-110", "inf", "NaN", "", None, True])
def test_spacer_range_or_invalid_cannot_enter_shared_consumers(value):
    s = state()
    s["fluids_config"]["params"]["Spacer"]["density"] = value
    for index, operation in enumerate((lambda: et.require_fluid_density("Spacer", value),
                      lambda: ps.refresh_fluids(s), lambda: chart._fluid(s, "Spacer"),
                      lambda: sp.formulation_from_state(s))):
        expected = "enter the fluid density" if index == 1 and value in (None, "") else "single.*scalar"
        with pytest.raises(ValueError, match=expected):
            operation()


@pytest.mark.parametrize("fluid", ["Pre Flush", "Spacer Ahead", "Spacer Behind", "Lead", "Tail", "Main"])
def test_other_fluid_range_semantics_preserved(fluid):
    assert et.require_fluid_density(fluid, "115-118") == 116.5


def test_scalar_rule_reaches_centralizer_and_pumping_admission_without_solver_changes():
    s = program_state("casing", fluids={"Spacer": 2., "Main": 2., "Displacement Fluid": 2.})
    s["fluids_config"]["params"]["Spacer"]["density"] = "115-118"
    for operation in (lambda: centralizer_adapter.build_fluid_snapshot(s),
                      lambda: pumping_simulation.prepare_pumping_simulation(s)):
        with pytest.raises(ValueError, match="single.*scalar"):
            operation()
    s["fluids_config"]["params"]["Spacer"]["density"] = "110"
    reviewed_spacer(s)  # A3 requires A2 review of the newly selected density.
    assert centralizer_adapter.build_fluid_snapshot(s)["diagnostics_available"]
    prepared = pumping_simulation.prepare_pumping_simulation(s)
    assert prepared["inputs"]["fluid_data"]["Spacer"]["effective_density"] == 110.


@pytest.mark.parametrize("volume", [.5, 10., 40., 137.123])
def test_dynamic_volumes_dead_volume_scaling_and_repeatability(volume):
    r = sp.calculate_spacer(volume, 110, "Barite", 3.)
    assert_closure(r)
    assert r == sp.calculate_spacer(volume, 110, "Barite", 3.)
    assert r["water_base_bbl"] == pytest.approx(oracle(volume, 110, "Barite")[0], rel=1e-13)
    assert r["pumped_volume_bbl"] == volume


@pytest.mark.parametrize("mode,density", [("Limestone", 95.), ("Barite", 110.),
                                         ("Ferro Bar", 140.), ("Limestone + Barite", 110.)])
def test_phase6_all_modes_prepare_download_restore_and_mix_draft_retention(mode, density, monkeypatch):
    import streamlit as st
    native = st.download_button
    offered = []

    def observe(**kwargs):
        offered.append(kwargs)
        return native(**kwargs)

    monkeypatch.setattr(st, "download_button", observe)  # native download boundary only
    s = state(mode=mode, dead=1.)
    s[sp.CONFIG_KEY]["barite_available_lb"] = 6000.
    s["fluids_config"]["params"]["Spacer"]["density"] = str(density)
    app = CASE.app(s)
    CASE.phase(app, "phase6")
    widget(app, "selectbox", "Mixing Tank - Spacer").set_value("Cement Unit Tanks").run()
    widget(app, "number_input", "Dead Volume (bbl) - Spacer").set_value(2.)
    widget(app, "button", "Prepare project download").click().run()
    assert offered
    raw = offered[-1]["data"].encode()
    decoded = decode_project(raw, audit.namespace["deserialize_item"])
    assert decoded[sp.CONFIG_KEY]["dead_vol"] == 2.
    assert decoded[sp.CONFIG_KEY]["mode"] == mode
    assert decoded[sp.CONFIG_KEY]["tank_name"] == "Cement Unit Tanks"
    expected = sp.formulation_from_state(decoded)
    restored = restore_project(raw)
    CASE.phase(restored, "phase6")
    assert sp.formulation_from_state(restored.session_state) == expected
    assert widget(restored, "number_input", "Dead Volume (bbl) - Spacer").value == 2.
    assert list(restored.table[0].value.columns) == sp.FIELD_COLUMNS
    if mode == "Limestone + Barite":
        stocks = {k: decoded[sp.CONFIG_KEY][k] for k in ("limestone_available_lb", "barite_available_lb")}
        widget(restored, "selectbox", "Weighting Agent Mode").set_value("Barite").run()
        CASE.phase(restored, "phase1")
        CASE.phase(restored, "phase6")
        widget(restored, "selectbox", "Weighting Agent Mode").set_value("Limestone + Barite").run()
        assert all(restored.session_state[sp.CONFIG_KEY][k] == v for k, v in stocks.items())
        assert sp.formulation_from_state(restored.session_state) == expected


def test_inventory_and_source_edits_cannot_reuse_a_prior_valid_projection():
    s = state("Limestone + Barite", 1.)
    first = sp.formulation_from_state(s)
    assert et.compute_phase_status(s)["phase6"]["level"] == "ok"
    s[sp.CONFIG_KEY]["barite_available_lb"] = 4000.
    assert et.compute_phase_status(s)["phase6"]["level"] == "warning"
    with pytest.raises(ValueError, match="Barite inventory shortage"):
        sp.formulation_from_state(s)
    s[sp.CONFIG_KEY]["barite_available_lb"] = 6000.
    s["fluids_config"]["params"]["Spacer"]["volume"] = 21.
    fresh = sp.formulation_from_state(s)
    assert fresh != first
    assert fresh["pumped_volume_bbl"] == 21.
    assert_closure(fresh)


def test_restored_invalid_density_cannot_use_saved_effective_density_as_authority():
    s = state()
    s["fluids_config"]["params"]["Spacer"]["density"] = "115-118"
    s["fluid_data"] = {"Spacer": {"volume": 20., "density": "110", "effective_density": 110.}}
    restored = audit.round_trip(s)  # saveable text draft; readiness, not JSON, owns completion
    assert et.compute_phase_status(restored)["phase4"]["level"] != "ok"
    assert et.compute_phase_status(restored)["phase6"]["level"] != "ok"
    with pytest.raises(ValueError, match="single.*scalar"):
        sp.formulation_from_state(restored)


@pytest.mark.parametrize("fluid", ["Spacer Ahead", "Spacer Behind"])
def test_sibling_generic_editor_navigation_and_roundtrip_are_unchanged(fluid):
    s = state()
    s["fluids_config"]["active"] = [fluid]
    s["fluids_config"]["params"][fluid] = s["fluids_config"]["params"].pop("Spacer")
    s["spacer_dfs"] = {fluid: pd.DataFrame([{"Chemical": "Mud", "User Input (% or gal)": .125,
                                           "Weighting Agent Type": "-"}])}
    app = CASE.app(s)
    CASE.phase(app, "phase4")
    CASE.phase(app, "phase6")
    assert not any(w.label == "Weighting Agent Mode" for w in app.selectbox)
    editor = next(e for e in app.dataframe if e.key and e.key.startswith("_editor_spacer_"))
    frame = app._tree.get_widget_states()
    event = frame.widgets.add()
    event.id = editor.proto.id
    event.string_value = json.dumps({"edited_rows": {"0": {"User Input (% or gal)": .25}},
                                    "added_rows": [], "deleted_rows": []})
    app._run(frame)
    CASE.phase(app, "phase1")
    restored = CASE.app(audit.round_trip(app.session_state.to_dict()))
    CASE.phase(restored, "phase6")
    assert restored.session_state["spacer_dfs"][fluid].iloc[0]["User Input (% or gal)"] == .25
    assert et.compute_phase_status(restored.session_state)["phase6"]["level"] == "ok"


def widget(app, group, label):
    return next(w for w in getattr(app, group) if w.label == label)


def test_phase6_callbacks_navigation_rebuild_and_independent_cement_sources():
    s = state()
    s["fluids_config"]["active"].append("Main")
    s["fluids_config"]["params"]["Main"] = {"volume": 10., "density": "118", "pump_rate": "4"}
    s["cement_params"] = {"Main": {"dead_vol": 99., "tank_name": "Cement Unit Tanks"}}
    app = CASE.app(s)
    CASE.phase(app, "phase4")
    CASE.phase(app, "phase6")
    assert et.compute_phase_status(app.session_state)["phase6"]["level"] == "ok"
    assert len(app.get("data_editor")) == 0
    assert any("18.4 bbl" in note.value for note in app.info)
    app.session_state["_compiled_doc_bytes"] = b"old"
    widget(app, "number_input", "Dead Volume (bbl) - Spacer").set_value(6.)
    CASE.phase(app, "phase1")  # last edit commits in callback before phase disposal
    assert app.session_state[sp.CONFIG_KEY]["dead_vol"] == 6.
    assert "_compiled_doc_bytes" not in app.session_state
    CASE.phase(app, "phase6")
    widget(app, "selectbox", "Weighting Agent Mode").set_value("Limestone + Barite").run()
    widget(app, "number_input", "Available Limestone (lb)").set_value(3000.).run()
    widget(app, "number_input", "Available Barite (lb)").set_value(10000.)
    CASE.phase(app, "phase4")
    app.number_input(key="vol_Spacer").set_value(21.)
    CASE.phase(app, "phase6")
    CASE.healthy(app)
    r = sp.formulation_from_state(app.session_state)
    assert r["pumped_volume_bbl"] == 21.
    assert app.session_state[sp.CONFIG_KEY]["barite_available_lb"] == 10000.
    assert app.session_state["cement_params"]["Main"]["dead_vol"] == 99.
    assert app.session_state["cement_params"]["Main"]["tank_name"] == "Cement Unit Tanks"
    assert any("Volume: 21.0 bbl" in text.value for text in app.markdown)


def test_phase4_invalid_scalar_callback_and_phase6_invalid_valid_invalid():
    app = CASE.app(state())
    CASE.phase(app, "phase4")
    for density, valid in (("115-118", False), ("110", True), ("115-118", False)):
        app.text_input(key="den_Spacer").set_value(density)
        CASE.phase(app, "phase6")
        assert app.session_state["fluids_config"]["params"]["Spacer"]["density"] == density
        assert app.session_state["fluid_data"]["Spacer"]["effective_density"] == (110. if valid else 0.)
        assert (et.compute_phase_status(app.session_state)["phase6"]["level"] == "ok") == valid
        CASE.phase(app, "phase4")


@pytest.mark.parametrize("job", db.JOB_TYPES)
def test_job_tank_authority_and_input_only_roundtrip(job):
    s = state(job=job)
    for tank in db.get_available_tanks(job):
        s[sp.CONFIG_KEY]["tank_name"] = tank
        r = sp.formulation_from_state(s)
        restored = audit.round_trip(s)
        assert restored[sp.CONFIG_KEY] == s[sp.CONFIG_KEY]
        assert sp.formulation_from_state(restored) == r
        assert not any(key in restored for key in ("spacer_recipe", "spacer_calc"))
        assert tank in r["note"]


@pytest.mark.parametrize("config", [[], {"mode": "Hematite"}, {"dead_vol": -1},
    {"dead_vol": True}, {"dead_vol": "5"}, {"dead_vol": float("inf")},
    {"tank_name": "Invented Tank"}, {"barite_available_lb": -2}, {"recipe": {}}])
def test_malformed_new_state_rejected_before_atomic_publication(config):
    current = {"well_name": "Keep me", "_app_mode_key": "phase6"}
    before = deepcopy(current)
    incoming = {"job_type": "CMT PLUG", sp.CONFIG_KEY: config}
    with pytest.raises(ValueError):
        decoded = decode_project(json.dumps(incoming).encode(), audit.namespace["deserialize_item"])
        replace_project_state(current, decoded, "bad")
    assert current == before


def test_incomplete_draft_readiness_restore_and_no_legacy_recipe_authority():
    s = state(mode=None, dead=None)
    s["spacer_dfs"] = {"Spacer": pd.DataFrame([{"Chemical": "Hematite", "User Input (% or gal)": 5., "Weighting Agent Type": "Hematite"}])}
    restored = audit.round_trip(s)
    assert et.compute_phase_status(restored)["phase6"]["level"] != "ok"
    app = CASE.app(restored)
    CASE.phase(app, "phase6")
    assert widget(app, "selectbox", "Weighting Agent Mode").value is None
    assert widget(app, "number_input", "Dead Volume (bbl) - Spacer").value is None
    widget(app, "selectbox", "Weighting Agent Mode").set_value("Barite").run()
    widget(app, "number_input", "Dead Volume (bbl) - Spacer").set_value(0.).run()
    assert et.compute_phase_status(app.session_state)["phase6"]["level"] == "ok"


def test_deactivation_restore_reactivation_clears_formulation_not_operational_draft():
    app = CASE.app(state())
    CASE.phase(app, "phase4")
    CASE.phase(app, "phase6")
    original = deepcopy(app.session_state["fluids_config"]["params"]["Spacer"])
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_Spacer").uncheck().run()
    CASE.phase(app, "phase1")
    restored = audit.round_trip(app.session_state.to_dict())
    assert sp.CONFIG_KEY not in restored
    assert restored["fluids_config"]["params"]["Spacer"] == original
    app = CASE.app(restored)
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_Spacer").check().run()
    CASE.phase(app, "phase6")
    assert widget(app, "selectbox", "Weighting Agent Mode").value is None
    assert et.compute_phase_status(app.session_state)["phase6"]["level"] != "ok"


@pytest.mark.parametrize("prepared", [True, False])
def test_export_block_includes_prepared_context_and_retires_old_bytes(prepared):
    s = dict(guards._seed_session())
    s["fluids_config"]["active"].insert(0, "Spacer")
    s["fluid_data"]["Spacer"] = {"volume": 20., "density": "110", "min_rate": 4.}
    s["fluids_config"]["params"] = {name: {**row, "pump_rate": str(row["min_rate"])}
                                      for name, row in s["fluid_data"].items()}
    s["_compiled_doc_bytes"] = b"old"
    with patch.object(report.st, "session_state", s):
        with pytest.raises(ValueError, match="Standalone Spacer.*Mixing Tank"):
            report.build_master_context(calculations_prepared=prepared)
    assert "_compiled_doc_bytes" not in s


def test_invalid_volume_message_precedes_formulation_admission():
    s = dict(guards._seed_session())
    s["fluids_config"]["active"].append("Spacer")
    s["fluid_data"]["Spacer"] = {"volume": "abc", "density": "110"}
    with patch.object(report.st, "session_state", s):
        with pytest.raises(ValueError, match="Unreadable numeric volume.*Spacer"):
            report.build_master_context(calculations_prepared=True)


def test_incomplete_phase10_has_no_legacy_download_or_review_loss():
    app = CASE.app(state())
    CASE.phase(app, "phase6")
    app.session_state["_compiled_doc_bytes"] = b"old"
    app.session_state["procedure_text"] = "Owner reviewed operational instruction."
    app.session_state["report_text_state"] = {"procedure_text": {
        "history": ["previous reviewed text"], "generated": "Previous generated instruction.",
        "source_signature": "previous source"}}
    before = deepcopy(app.session_state["report_text_state"])
    CASE.phase(app, "phase10")
    assert widget(app, "button", "Build Word Document").disabled
    assert any("Spacer" in error.value for error in app.error)
    assert "_compiled_doc_bytes" not in app.session_state
    assert not app.get("download_button")
    assert app.session_state["procedure_text"] == "Owner reviewed operational instruction."
    assert app.session_state["report_text_state"]["procedure_text"] == before["procedure_text"]


@pytest.mark.parametrize("mode,density,dead,water,gross", [
    ("Limestone", 95, 5, 12.9669852355, 8.9834926177),
    ("Barite", 110, 5, 13.4378344880, 9.2189172440),
    ("Ferro Bar", 140, 5, 11.7501266437, 8.3750633218),
    ("Limestone + Barite", 110, 1, 12.8299828150, 6.9149914075)])
def test_corrected_freshwater_defoamer_independent_references(mode, density, dead, water, gross):
    recipe = sp.calculate_spacer(20, density, mode, dead, 1500, 5000)
    assert recipe["water_base_bbl"] == pytest.approx(water, abs=6e-11)
    defoamer = next(row for row in recipe["materials"] if row["name"] == "Defoamer")
    assert defoamer["base"] == .5 * recipe["water_base_bbl"]
    assert defoamer["gross"] == pytest.approx(gross, abs=6e-11)
    assert defoamer["basis"] == "freshwater"
    assert_closure(recipe)


@pytest.mark.parametrize("mode,density", [
    ("Limestone", d) for d in (75, 87.375, 95, 100)] + [
    ("Barite", d) for d in (75, 99.125, 110, 125)] + [
    ("Ferro Bar", d) for d in (75, 117.875, 140, 160)] + [
    ("Limestone + Barite", d) for d in (100, 110, 112.625, 125)])
@pytest.mark.parametrize("volume", [.125, 20., 137.375, 1000.])
@pytest.mark.parametrize("dead", [0., 1.375, 25.])
def test_parametric_freshwater_recipe_and_finished_sample(mode, density, volume, dead):
    # Stock is an actual gross ceiling, independently varied with operational scale.
    stock_l, stock_b = 75 * volume, 5000 * (volume + dead)
    r = sp.calculate_spacer(volume, density, mode, dead, stock_l, stock_b)
    if mode == "Limestone + Barite":
        water, limestone, barite, cap = mix_oracle(volume, density, dead, stock_l)
        assert r["solids_lb"] == pytest.approx({"Limestone": limestone, "Barite": barite}, rel=2e-12)
        assert 0 < limestone <= cap
        assert barite > 0
        assert r["inventory"]["Limestone"]["used_lb"] == pytest.approx(stock_l, rel=2e-12)
        assert r["inventory"]["Barite"]["used_lb"] <= stock_b
    else:
        water, mass = oracle(volume, density, mode)
        assert r["solids_lb"][mode] == pytest.approx(mass, rel=2e-12)
    assert r["water_base_bbl"] == pytest.approx(water, rel=2e-13)
    assert r["water_total_bbl"] == pytest.approx(water + dead, rel=2e-13)
    assert r["pumped_volume_bbl"] == volume
    assert r["mixed_volume_bbl"] == pytest.approx(volume * (water + dead) / water, rel=2e-13)
    for row in r["materials"]:
        amount = (row["dose"] * water if row["name"] not in r["solids_lb"] else r["solids_lb"][row["name"]])
        assert row["base"] == pytest.approx(amount, rel=2e-13)
        assert row["gross"] == pytest.approx(amount * (water + dead) / water, rel=2e-13)
        assert row["basis"] == "freshwater"
    assert len(r["materials"]) == (6 if mode == "Limestone + Barite" else 5)
    assert r == sp.calculate_spacer(volume, density, mode, dead, stock_l, stock_b)
    assert_closure(r)
    sample = sp.lab_sample(r)
    assert sample["volume_ml"] == pytest.approx(600, abs=1e-9)
    assert sample["density_pcf"] == pytest.approx(density, abs=1e-9)
    grams = {row["Material"]: row["Mass"] for row in sample["rows"]}
    assert grams["Defoamer"] == pytest.approx(.5 * water / volume / 42 * 600, rel=2e-13)
    # Independently reconstruct the final cup using grams and physical SGs.
    ml = (grams["Fresh Water"] + grams["Salt"]) / 1.20113
    ml += grams["O-Spacer"] / 1.62 + grams["Surfactant"] / .94 + grams["Defoamer"]
    ml += sum(grams[n] / sg for n, sg in (("Limestone", 2.7), ("Barite", 4.2), ("Ferro Bar", 4.8)) if n in grams)
    assert ml == pytest.approx(600, abs=1e-9)


@pytest.mark.parametrize("mode,bound", [(m, b) for m, lo, hi in (
    ("Limestone", 75, 100), ("Barite", 75, 125), ("Ferro Bar", 75, 160),
    ("Limestone + Barite", 100, 125)) for b in (lo - .000001, hi + .000001)])
def test_immediately_outside_density_bands_is_rejected(mode, bound):
    with pytest.raises(ValueError, match="target density"):
        sp.calculate_spacer(20, bound, mode, 1, 1500, 5000)
