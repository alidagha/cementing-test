"""Round 9F project-owned Phase IX inputs; Word readiness remains advisory."""
from copy import deepcopy
import importlib.util
import json
import pickle
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import centralizer_adapter as adapter
import engineering_tools as tools
import materials_db
from project_io import decode_project, replace_project_state
from project_state import is_project_key
import test_audit_regressions as audit
from test_uat_round9d_static_solver import zones_for
from test_uat_round9e_dynamic_solver import dynamic_state, auxiliary


def phase9():
    assert importlib.util.find_spec("phase_9_centralizer"), "Phase IX UI/state module is missing"
    import phase_9_centralizer
    return phase_9_centralizer


def custom(custom_id="opaque-one", **changes):
    return {**dict(custom_id=custom_id, identification="Project Centralizer", manufacturer="Owner",
                description="Project product", pipe_size_in=9.625, hole_size_in=12.25,
                kind="rigid", bows=0, max_od_in=12., min_od_in=12.,
                starting_force_lbf=0., running_force_lbf=0., restoring_force_lbf=0.), **changes}


@pytest.fixture(scope="module")
def catalog():
    return adapter.load_official_catalog()


def configured(catalog, kind="casing", physics="static", mode="direct", use_custom=False):
    state = dynamic_state(kind)
    config = phase9().new_config()
    config.update(physics_mode=physics, placement_mode=mode, zones=zones_for(catalog, kind),
                  aux_rheology=auxiliary())
    for zone in config["zones"]:
        zone["custom_product_id"] = None
    if use_custom:
        product = custom()
        if kind != "casing":
            product["pipe_size_in"] = 7.
        config["custom_products"] = [product]
        config["zones"][0].update(product_nr=None, custom_product_id=product["custom_id"])
    state["centralizer_config"] = config
    return state


def test_custom_engine_mapping_is_pure_and_explicit():
    assert callable(getattr(adapter, "to_engine_custom_product", None)), "Custom product mapper is absent"
    product = custom()
    before = deepcopy(product)
    mapped = adapter.to_engine_custom_product(product)
    assert product == before
    assert mapped["kind"] == "rigid" and mapped["name"] != "OFFICIAL-CENT-opaque-one"
    assert mapped["code"] == "opaque-one"
    assert mapped["max_od"] == 12. * adapter.INCH_TO_M
    assert mapped["rated_hole"] == 12.25 * adapter.INCH_TO_M
    product.update(kind="spring", restoring_force_lbf=100., min_od_in=10.)
    assert adapter.to_engine_custom_product(product)["restoring_force"] == 100. * adapter.LBF_TO_N
    product["restoring_force_lbf"] = 0.
    assert adapter.to_engine_custom_product(product)["kind"] == "spring"


@pytest.mark.parametrize("field,value", [("identification", " "), ("manufacturer", ""),
    ("description", None), ("custom_id", ""), ("pipe_size_in", 0.), ("hole_size_in", -1.),
    ("max_od_in", float("inf")), ("min_od_in", 13.), ("bows", True), ("bows", 1.5),
    ("bows", -1), ("kind", "RIGID"), ("starting_force_lbf", -1.),
    ("running_force_lbf", True), ("restoring_force_lbf", float("nan"))])
def test_custom_saved_records_are_validated(field, value):
    assert callable(getattr(adapter, "validate_custom_products", None)), "Custom record validation is absent"
    record = custom(); record[field] = value
    with pytest.raises(ValueError):
        adapter.validate_custom_products([record])


@pytest.mark.parametrize("physics", ["static", "dynamic"])
@pytest.mark.parametrize("mode", ["direct", "optimize"])
@pytest.mark.parametrize("kind", ["casing", "liner", "tieback"])
@pytest.mark.parametrize("use_custom", [False, True])
def test_all_routes_execute_once_and_report_current(catalog, physics, mode, kind, use_custom):
    state = configured(catalog, kind, physics, mode, use_custom)
    before = pickle.dumps({k:v for k,v in state.items() if is_project_key(k)})
    result = phase9().execute(state, catalog)
    assert result is state["_centralizer_result"] and result["zones"]
    assert before == pickle.dumps({k:v for k,v in state.items() if is_project_key(k)})
    assert tools.compute_phase_status(state)["phase9"]["level"] == "ok"
    with patch.object(adapter, "solve_static", side_effect=AssertionError("Rerun executed solver")), \
         patch.object(adapter, "solve_dynamic", side_effect=AssertionError("Rerun executed solver")):
        assert phase9().result_is_current(state, catalog)
        assert tools.compute_phase_status(state)["phase9"]["level"] == "ok"
    if use_custom:
        assert result["zones"][0]["custom_product_id"] == "opaque-one"
        assert result["zones"][0]["product_nr"] is None


def test_custom_management_identity_maximum_and_selected_deletion(catalog):
    state = configured(catalog, use_custom=True)
    phase9().execute(state, catalog)
    saved = phase9().save_custom_product(state, {k:v for k,v in custom().items() if k != "custom_id"})
    assert saved["custom_id"] != "opaque-one"
    assert phase9().result_is_current(state, catalog)  # Unused product addition.
    phase9().save_custom_product(state, {**saved, "description":"Unused edited"}, custom_id=saved["custom_id"])
    assert phase9().result_is_current(state, catalog)
    phase9().save_custom_product(state, {**custom(), "description":"Selected edited"}, custom_id="opaque-one")
    assert not phase9().result_is_current(state, catalog)
    phase9().execute(state, catalog)
    phase9().delete_custom_product(state, "opaque-one")
    assert state["centralizer_config"]["zones"][0]["custom_product_id"] == "opaque-one"
    assert not phase9().result_is_current(state, catalog)
    with pytest.raises(ValueError): phase9().execute(state, catalog)
    while len(state["centralizer_config"]["custom_products"]) < 5:
        phase9().save_custom_product(state, {k:v for k,v in custom().items() if k != "custom_id"})
    before = deepcopy(state["centralizer_config"])
    with pytest.raises(ValueError): phase9().save_custom_product(state, custom())
    assert state["centralizer_config"] == before


@pytest.mark.parametrize("job", materials_db.JOB_TYPES)
def test_phase9_job_applicability(job):
    result = tools.compute_phase_status({"job_type":job})
    assert "phase9" in result, "Phase IX status is missing"
    if job in ("CMT PLUG", "CMT SQUEEZE"):
        assert result["phase9"]["level"] == "ok"
        assert "Not applicable" in result["phase9"]["message"]
    else:
        assert result["phase9"]["level"] in ("empty", "warning")


def test_current_json_custom_roundtrip_requires_fresh_execution(catalog):
    state = configured(catalog, use_custom=True)
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)":None, "Burst (psi)":None})
    phase9().execute(state, catalog)
    project = audit.round_trip(state)
    assert project["centralizer_config"] == state["centralizer_config"]
    assert not any(key.startswith("_centralizer") for key in project)
    restored = {"job_type":"CMT PLUG", "_centralizer_result":state["_centralizer_result"]}
    replace_project_state(restored, project, "current-project")
    assert not phase9().result_is_current(restored, catalog)
    assert tools.compute_phase_status(restored)["phase9"]["level"] == "warning"
    phase9().execute(restored, catalog)
    assert phase9().result_is_current(restored, catalog)


def test_malformed_custom_json_rejected_before_replacement():
    project = {"job_type":"CMT PLUG", "centralizer_config": {
        "version":1, "placement_mode":"direct", "physics_mode":"static", "zones":[],
        "custom_products":[{**custom(), "bows":True}], "aux_rheology":{}}}
    with pytest.raises(ValueError):
        decode_project(json.dumps(project).encode(), audit.namespace["deserialize_item"])


def test_phase9_navigation_and_help_no_automatic_solver(catalog):
    state = configured(catalog)
    app = AppTest.from_file(str(audit.ROOT / "main.py"), default_timeout=30)
    for key,value in state.items(): app.session_state[key] = value
    app.run()
    assert "Phase IX: Centralizer" in app.radio(key="_app_mode_key").options, "Phase IX navigation is absent"
    with patch.object(adapter, "solve_static", side_effect=AssertionError("Implicit execution")), \
         patch.object(adapter, "solve_dynamic", side_effect=AssertionError("Implicit execution")):
        app.radio(key="_app_mode_key").set_value("phase9").run()
        assert not app.exception
        assert app.radio(key="_centralizer_physics").proto.help
        assert "hydrostatic" in app.radio(key="_centralizer_physics").proto.help
        assert "API RP 13D" in app.radio(key="_centralizer_physics").proto.help


def test_phase9_advisory_readiness_deep_link_and_baseline_word_retention():
    case = audit.AuditRegressions()
    app = case.configured_app('CSG 9 5/8"')
    case.phase(app, "phase10")
    assert any("Phase IX" in item.value for item in app.warning), "Advisory Phase IX is missing from readiness"
    deep_link = next((button for button in app.button if button.label == "→ Phase IX"), None)
    assert deep_link is not None, "Phase IX readiness deep-link is missing"
    assert not next(button for button in app.button if button.label == "Build Word Document").disabled, [e.value for e in app.error]
    case.export(app)  # Existing export helper and fixture stay unchanged.
    assert "_compiled_doc_bytes" in app.session_state
    app.button(key="_rescue_phase9").click().run()
    assert not app.exception and app.radio(key="_app_mode_key").value == "phase9"


@pytest.mark.parametrize("field", ["pipe_size_in", "hole_size_in", "max_od_in", "min_od_in",
                                   "starting_force_lbf", "running_force_lbf", "restoring_force_lbf"])
@pytest.mark.parametrize("value", [True, "12", None, float("inf"), float("nan")])
def test_every_saved_custom_numeric_field_rejects_malformed(field, value):
    with pytest.raises(ValueError): adapter.validate_custom_products([custom(**{field:value})])


def test_custom_dimension_and_force_boundaries_explicit_kind():
    adapter.validate_custom_products([custom(bows=0, min_od_in=12., max_od_in=12., kind="spring")])
    with pytest.raises(ValueError): adapter.validate_custom_products([custom(), custom()])
    with pytest.raises(ValueError): adapter.validate_custom_products([custom(str(i)) for i in range(6)])
    assert adapter.to_engine_custom_product(custom(kind="rigid", min_od_in=10., bows=99))["kind"] == "rigid"


@pytest.mark.parametrize("nr,custom_id", [(None,None), (25,"opaque-one"), (None,"missing"),
                                         (True,None), ("25",None)])
def test_zone_bindings_cannot_be_ambiguous(catalog, nr, custom_id):
    state = configured(catalog, use_custom=True)
    state["centralizer_config"]["zones"][0].update(product_nr=nr, custom_product_id=custom_id)
    with pytest.raises(ValueError): phase9().execute(state, catalog)
    assert "_centralizer_result" not in state and "_centralizer_signature" not in state


def test_combined_candidates_use_only_pipe_size_and_never_display_api_rf(catalog):
    saved = [custom("one", hole_size_in=99.), custom("two", pipe_size_in=7.)]
    before = pickle.dumps([catalog, saved])
    candidates = phase9().product_candidates(catalog, saved, '9 5/8"')
    official = [row for row in candidates if row["product_nr"] is not None]
    user = [row for row in candidates if row["custom_product_id"] is not None]
    assert len(official) == len(adapter.filter_official_products(catalog, 9.625))
    assert [row["custom_product_id"] for row in user] == ["one"]
    assert all(row["product"]["pipe_size_in"] == 9.625 for row in candidates)
    assert phase9().product_candidates(catalog, saved, 999.) == []
    for candidate in candidates:
        assert set(phase9().product_view(candidate)) == {"Identification","Hole Size (in)","Kind","Restoring Force (lbf)"}
        assert "API" not in str(phase9().product_view(candidate))
    assert pickle.dumps([catalog,saved]) == before
    assert phase9().product_view(user[0])["Identification"].startswith("[Custom]")


def test_duplicate_display_names_keep_exact_source_identity(catalog):
    groups = {}
    for product in adapter.filter_official_products(catalog, 9.625):
        groups.setdefault(product["identification"], []).append(product)
    duplicates = next(rows for rows in groups.values() if len(rows) > 1)
    chosen = duplicates[:2]
    zones = [dict(top_md=i*500., bottom_md=(i+1)*500., density="1/3", target_standoff_pct=70.,
                  product_nr=product["nr"], custom_product_id=None) for i,product in enumerate(chosen)]
    payload = adapter.build_static_payload(dynamic_state(), zones, catalog)
    assert [zone["product_name"] for zone in payload["zones"]] == [f"OFFICIAL-CENT-{p['nr']}" for p in chosen]
    assert len(payload["products"]) == 2


@pytest.mark.parametrize("kind", ["casing","liner","tieback"])
def test_auto_populate_consumes_calculated_toc_not_report_overrides(catalog, kind):
    from cement_chart_model import resolve_chart_geometry, interval_volume
    state = configured(catalog, kind)
    geometry = resolve_chart_geometry(state)
    top = 0. if kind != "liner" else 400.
    toc = 450. if kind != "tieback" else 600.
    row = state["fluids_config"]["params"]["Tail"]
    row["volume"] = interval_volume(geometry["capacity_segments"], toc, 1000.) + geometry["shoe_track_bbl"]
    state["cement_params"] = {"Tail":{"top_depth":999., "report_bottom_depth":1.}}
    before = pickle.dumps(state)
    zones = phase9().auto_populate(state)
    assert pickle.dumps(state) == before
    assert zones[0]["top_md"] == top and zones[-1]["bottom_md"] == 1000.
    assert zones[0]["bottom_md"] == pytest.approx(toc)
    assert zones[0]["density"] == "1/4" and zones[0]["target_standoff_pct"] == 67.
    assert all(zone["product_nr"] is None and zone["custom_product_id"] is None for zone in zones)
    assert all(zone["top_md"] < zone["bottom_md"] for zone in zones)
    assert all(a["bottom_md"] == b["top_md"] for a,b in zip(zones,zones[1:]))
    if kind == "tieback":
        assert len(zones) == 2  # Previous Shoe == String Shoe: drop zero width only.
    else:
        assert [zone["density"] for zone in zones] == ["1/4","1/3","1/1"]


def test_invalid_auto_populate_preserves_current_zones(catalog):
    state = configured(catalog)
    state["fluids_config"]["params"]["Tail"]["volume"] = 20.
    before = deepcopy(state["centralizer_config"]["zones"])
    with pytest.raises(ValueError, match="TOC"):
        phase9().auto_populate(state)
    with patch.object(phase9().st, "session_state", state): phase9()._zones_action("auto")
    assert state["centralizer_config"]["zones"] == before
    assert state["_centralizer_error"]


@pytest.mark.parametrize("physics", ["static","dynamic"])
@pytest.mark.parametrize("edit", ["volume","density","survey","hardware","zone","mode","selected_custom"])
def test_consumed_source_edits_stale_without_execution(catalog, physics, edit):
    state = configured(catalog, physics=physics, use_custom=True)
    phase9().execute(state, catalog)
    if edit == "volume": state["fluids_config"]["params"]["Tail"]["volume"] += 1.
    elif edit == "density": state["mud_density"] = "85"
    elif edit == "survey": state["well_geometry"]["td_m"] += 1.
    elif edit == "hardware": state["hardware_table"].loc[0,"Weight (ppf)"] += 1.
    elif edit == "zone": state["centralizer_config"]["zones"][0]["target_standoff_pct"] = 71.
    elif edit == "mode": state["centralizer_config"]["placement_mode"] = "optimize"
    else: state["centralizer_config"]["custom_products"][0]["running_force_lbf"] = 1.
    with patch.object(adapter, "solve_static", side_effect=AssertionError("Implicit solver")), \
         patch.object(adapter, "solve_dynamic", side_effect=AssertionError("Implicit solver")):
        assert not phase9().result_is_current(state, catalog)
        assert tools.compute_phase_status(state)["phase9"]["level"] == "warning"


@pytest.mark.parametrize("edit", ["report_text","report_top","grade","static_aux","static_pv",
                                 "static_pump_rate","spacer_behind","unused_custom","custom_order"])
def test_unconsumed_static_sources_do_not_stale(catalog, edit):
    state = configured(catalog, use_custom=True)
    state["centralizer_config"]["custom_products"].append(custom("unused"))
    phase9().execute(state, catalog)
    if edit == "report_text": state["procedure_text"] = "Report text changed"
    elif edit == "report_top": state["cement_params"] = {"Tail":{"top_depth":999., "report_bottom_depth":1.}}
    elif edit == "grade": state["hardware_table"].loc[0,"Grade"] = "L80"
    elif edit == "static_aux": state["centralizer_config"]["aux_rheology"]["Spacer"]["300"] = 10.
    elif edit == "static_pv": state["plastic_viscosity"] = "20"
    elif edit == "static_pump_rate": state["fluids_config"]["params"]["Displacement Fluid"]["pump_rate"] = "5"
    elif edit == "spacer_behind": state["fluids_config"]["active"].append("Spacer Behind")
    elif edit == "unused_custom": state["centralizer_config"]["custom_products"][1]["running_force_lbf"] = 111.
    else: state["centralizer_config"]["custom_products"].reverse()
    assert phase9().result_is_current(state, catalog)


@pytest.mark.parametrize("edit", ["pv","yp","q","lab","aux","behind","inside_only"])
def test_dynamic_consumed_sources_stale(catalog, edit):
    state = configured(catalog, physics="dynamic")
    phase9().execute(state, catalog)
    if edit == "pv": state["plastic_viscosity"] = "20"
    elif edit == "yp": state["yield_point"] = "11"
    elif edit == "q": state["fluids_config"]["params"]["Displacement Fluid"]["pump_rate"] = "5"
    elif edit == "lab": state["lab_qc_params"]["Tail"]["rheology"]["bhct_down"]["readings"]["300"] += 1.
    elif edit == "aux": state["centralizer_config"]["aux_rheology"]["Spacer"]["300"] += 1.
    elif edit == "inside_only": state["fluids_config"]["params"]["Displacement Fluid"]["volume"] = 1.
    else: state["fluids_config"]["active"].append("Spacer Behind")
    assert not phase9().result_is_current(state, catalog)


def test_dynamic_unconsumed_caches_gels_and_inactive_readings_do_not_stale(catalog):
    state = configured(catalog, physics="dynamic")
    phase9().execute(state, catalog)
    state.update(effective_pv=123., effective_yp=123., procedure_text="irrelevant")
    state["fluids_config"]["params"]["Displacement Fluid"].update(min_rate=123., density="999")
    state["lab_qc_params"]["Tail"]["rheology"]["bhct_down"]["gel_10_sec"] = "99"
    state["centralizer_config"]["aux_rheology"]["Pre Flush"]["300"] = 99.
    assert phase9().result_is_current(state, catalog)


@pytest.mark.parametrize("physics", ["static","dynamic"])
@pytest.mark.parametrize("mode", ["direct","optimize"])
def test_low_target_result_is_success_not_export_requirement(catalog, physics, mode):
    state = configured(catalog, physics=physics, mode=mode)
    function = "solve_static" if physics == "static" else "solve_dynamic"
    result = {"zones":[{"meets_target":False}], "profile":{}}
    with patch.object(adapter, function, return_value=result) as call:
        assert phase9().execute(state,catalog) is result
        assert call.call_count == 1 and call.call_args.kwargs["mode"] == mode
    assert tools.compute_phase_status(state)["phase9"]["level"] == "ok"


@pytest.mark.parametrize("path,value", [
    (("version",),True), (("version",),2), (("physics_mode",),"fast"), (("placement_mode",),"mixed"),
    (("zones",),{}), (("zones",0,"top_md"),True), (("zones",0,"bottom_md"),"1000"),
    (("zones",0,"product_nr"),True), (("zones",0,"custom_product_id"),3),
    (("aux_rheology",),[]), (("aux_rheology","Spacer"),[]),
    (("aux_rheology","Spacer","300"),True), (("aux_rheology","Spacer","300"),"168"),
    (("custom_products",),{}), (("custom_products",0,"bows"),True),
    (("custom_products",0,"kind"),"auto"), (("custom_products",0,"hole_size_in"),-1.),
])
def test_project_input_types_rejected_transactionally(catalog, path, value):
    config = configured(catalog, use_custom=True)["centralizer_config"]
    cursor = config
    for part in path[:-1]: cursor = cursor[part]
    cursor[path[-1]] = value
    existing = {"job_type":"CMT PLUG", "well_name":"Existing project"}
    before = deepcopy(existing)
    with pytest.raises(ValueError):
        project = decode_project(json.dumps({"job_type":"CMT PLUG","centralizer_config":config}).encode(),
                                 audit.namespace["deserialize_item"])
        replace_project_state(existing, project, "bad-project")
    assert existing == before


def test_incomplete_current_phase9_draft_roundtrip_and_no_config_project(catalog):
    config = phase9().new_config()
    config["zones"] = [{"top_md":None,"bottom_md":None,"density":"1/4","target_standoff_pct":None,
                        "product_nr":None,"custom_product_id":None}]
    config["aux_rheology"] = {"Spacer":{"300":None,"200":0.}}
    project = audit.round_trip({"job_type":"CMT PLUG","centralizer_config":config})
    assert project["centralizer_config"] == config
    assert "centralizer_config" not in audit.round_trip({"job_type":"CMT PLUG"})
    assert not any(is_project_key(key) for key in ("_centralizer_result","_centralizer_signature","_centralizer_error"))


@pytest.mark.parametrize("extra", ["source_signature","result","payload","official_products","chart_bytes"])
def test_derived_data_not_permitted_in_canonical_config(extra):
    config = phase9().new_config(); config[extra] = "not a user input"
    with pytest.raises(ValueError): phase9().validate_config(config)


def test_failed_custom_draft_does_not_mutate_saved_record_or_identity(catalog):
    state = configured(catalog, use_custom=True)
    before = deepcopy(state["centralizer_config"])
    with pytest.raises(ValueError): phase9().save_custom_product(state, custom(bows=-1),custom_id="opaque-one")
    assert state["centralizer_config"] == before
    record = phase9().save_custom_product(state, custom(custom_id="editable-display-id",description="Edited"),custom_id="opaque-one")
    assert record["custom_id"] == "opaque-one"


def test_solver_failure_retires_old_success(catalog):
    state = configured(catalog); phase9().execute(state,catalog)
    with patch.object(adapter,"solve_static",side_effect=ValueError("Controlled solver failure")):
        with pytest.raises(ValueError,match="Controlled"): phase9().execute(state,catalog)
    assert "_centralizer_result" not in state and "_centralizer_signature" not in state
    assert not phase9().result_is_current(state,catalog)


def test_manual_zone_add_delete_and_callbacks_preserve_unrelated_values(catalog):
    state = configured(catalog)
    original = deepcopy(state["centralizer_config"]["zones"][0])
    with patch.object(phase9().st,"session_state",state):
        phase9()._zones_action("add")
        assert state["centralizer_config"]["zones"][0] == original
        state["_edit"] = 500.
        phase9()._commit("top_md","_edit",1)
        assert state["centralizer_config"]["zones"][1]["top_md"] == 500.
        phase9()._zones_action("delete",1)
    assert state["centralizer_config"]["zones"] == [original]


def ui_app(state):
    app = AppTest.from_file(str(audit.ROOT / "main.py"),default_timeout=30)
    for key,value in state.items(): app.session_state[key] = value
    app.run()
    app.radio(key="_app_mode_key").set_value("phase9").run()
    assert not app.exception
    return app


def test_first_zone_edit_survives_immediate_navigation(catalog):
    app = ui_app(configured(catalog))
    app.number_input(key="_centralizer_zone_0_0_top_md").set_value(25.)
    app.radio(key="_app_mode_key").set_value("phase10").run()
    assert not app.exception and app.radio(key="_app_mode_key").value == "phase10"
    assert app.session_state["centralizer_config"]["zones"][0]["top_md"] == 25.
    app.radio(key="_app_mode_key").set_value("phase9").run()
    assert app.number_input(key="_centralizer_zone_0_0_top_md").value == 25.


def test_fresh_phase9_defaults_and_products_are_not_auto_selected(catalog):
    state = configured(catalog); state.pop("centralizer_config")
    app = ui_app(state)
    assert app.session_state["centralizer_config"] == phase9().new_config()
    assert next(widget for widget in app.selectbox if widget.label=="Kind").value is None
    app.button(key="_centralizer_add_zone").click().run()
    assert app.selectbox(key="_centralizer_zone_1_0_product").value is None
    assert app.number_input(key="_centralizer_zone_1_0_top_md").value is None
    assert app.session_state["centralizer_config"]["zones"][0]["product_nr"] is None


@pytest.mark.parametrize("job", ["CMT PLUG","CMT SQUEEZE"])
def test_na_ui_has_no_centralizer_controls_or_solver(catalog, job):
    state = configured(catalog);state["job_type"] = job;state.pop("centralizer_config")
    with patch.object(adapter,"solve_static",side_effect=AssertionError("N/A solver")), \
         patch.object(adapter,"solve_dynamic",side_effect=AssertionError("N/A solver")):
        app = ui_app(state)
    assert any("Not applicable" in item.value for item in app.info)
    assert not any(button.label == "Execute Centralizer" for button in app.button)
    assert "centralizer_config" not in app.session_state


def test_dynamic_widgets_are_exact_active_aux_readings_and_persist(catalog):
    app = ui_app(configured(catalog))
    app.radio(key="_centralizer_physics").set_value("dynamic").run()
    readings = [widget for widget in app.number_input if (widget.key or "").startswith("_centralizer_aux_")]
    assert len(readings) == 7
    assert {widget.label for widget in readings} == {f"{rpm} RPM — Spacer" for rpm in phase9().rheology.RPM_ORDER}
    app.number_input(key="_centralizer_aux_Spacer_300").set_value(169.)
    app.radio(key="_app_mode_key").set_value("phase7").run()
    assert not app.exception and app.session_state["centralizer_config"]["aux_rheology"]["Spacer"]["300"] == 169.
    app.radio(key="_app_mode_key").set_value("phase9").run()
    app.radio(key="_centralizer_physics").set_value("static").run()
    assert not any((widget.key or "").startswith("_centralizer_aux_") for widget in app.number_input)
    assert app.session_state["centralizer_config"]["aux_rheology"]["Spacer"]["300"] == 169.


def test_custom_manager_ui_invalid_save_valid_save_edit_delete(catalog):
    app = ui_app(configured(catalog))
    next(button for button in app.button if button.label == "Save / Apply Custom Centralizer").click().run()
    assert not app.exception and not app.session_state["centralizer_config"]["custom_products"]
    assert app.error
    for label,value in (("Identification","UI Custom"),("Manufacturer","Owner"),("Description","Saved UI product")):
        next(widget for widget in app.text_input if widget.label == label).set_value(value)
    next(widget for widget in app.selectbox if widget.label=="Kind").set_value("rigid")
    for label,value in (("Pipe Size (in)",9.625),("Hole Size (in)",12.25),("Max OD (in)",12.),("Min OD (in)",12.),
                        ("Starting Force (lbf)",0.),("Running Force (lbf)",0.),("Restoring Force (lbf)",0.),("Bows",0)):
        next(widget for widget in app.number_input if widget.label == label).set_value(value)
    next(button for button in app.button if button.label == "Save / Apply Custom Centralizer").click().run()
    assert not app.exception
    saved = app.session_state["centralizer_config"]["custom_products"][0]
    assert saved["custom_id"] and saved["identification"] == "UI Custom"
    token = "custom:" + saved["custom_id"]
    app.selectbox(key="_centralizer_zone_0_0_product").set_value(token).run()
    app.button(key="_centralizer_execute").click().run()
    assert not app.exception and phase9().result_is_current(app.session_state.to_dict(),catalog)
    app.selectbox(key="_centralizer_custom_choice").set_value(saved["custom_id"]).run()
    next(widget for widget in app.text_input if widget.label == "Description").set_value("Edited UI product")
    next(button for button in app.button if button.label == "Save / Apply Custom Centralizer").click().run()
    assert not app.exception
    assert app.session_state["centralizer_config"]["custom_products"][0]["custom_id"] == saved["custom_id"]
    assert not phase9().result_is_current(app.session_state.to_dict(),catalog)
    app.button(key="_centralizer_delete_custom").click().run()
    assert not app.exception
    assert not app.session_state["centralizer_config"]["custom_products"]
    assert app.session_state["centralizer_config"]["zones"][0]["custom_product_id"] == saved["custom_id"]
    assert app.selectbox(key="_centralizer_zone_0_0_product").value == token


def test_custom_manager_duplicate_labels_keep_selected_id(catalog):
    state = configured(catalog,use_custom=True)
    state["centralizer_config"]["custom_products"].append(custom("second",description="Second record"))
    app = ui_app(state)
    app.selectbox(key="_centralizer_custom_choice").set_value("second").run()
    assert app.selectbox(key="_centralizer_custom_choice").value == "second"
    assert next(widget for widget in app.text_input if widget.label == "Description").value == "Second record"


def test_selected_custom_record_list_order_is_not_a_source_change(catalog):
    state = configured(catalog,use_custom=True)
    state["centralizer_config"]["custom_products"].append(custom("second"))
    first = state["centralizer_config"]["zones"][0];first["bottom_md"] = 500.
    state["centralizer_config"]["zones"].append({**first,"top_md":500.,"bottom_md":1000.,"custom_product_id":"second"})
    phase9().execute(state,catalog)
    state["centralizer_config"]["custom_products"].reverse()
    assert phase9().result_is_current(state,catalog)


@pytest.mark.parametrize("job", [job for job in materials_db.JOB_TYPES if adapter.centralizer_applicable(job)])
def test_current_execution_supports_every_applicable_job(catalog,job):
    from cement_chart_model import chart_job_kind
    from placement import hardware_choices, HOST_DESCRIPTIONS
    state = dynamic_state();state.update(audit.chart_fixture(job),job_type=job)
    state["well_geometry"]["td_m"] = 3500.
    if chart_job_kind(job) == "tieback":
        state["placement_config"]["host_row"] = next(iter(hardware_choices(state["hardware_table"],HOST_DESCRIPTIONS)))
    geometry = adapter.to_engine_geometry(state)
    description = {"casing":"Casing","liner":"Liner","tieback":"Tie Back"}[geometry["job_type"]]
    row = next(row for row in state["hardware_table"].to_dict("records") if row["Description"] == description)
    record = custom(pipe_size_in=tools.parse_fractional_size(row["Size (in)"]),
                    hole_size_in=geometry["wellbore"]["hole_size"]/adapter.INCH_TO_M,
                    max_od_in=geometry["wellbore"]["hole_size"]/adapter.INCH_TO_M,
                    min_od_in=geometry["wellbore"]["hole_size"]/adapter.INCH_TO_M)
    config = phase9().new_config();config.update(placement_mode="direct",custom_products=[record],
        zones=[dict(top_md=geometry["wellbore"]["string_top"],bottom_md=3000.,density="1/3",
                    target_standoff_pct=70.,product_nr=None,custom_product_id="opaque-one")])
    state["centralizer_config"] = config
    assert phase9().execute(state,catalog)["zones"]
    assert tools.compute_phase_status(state)["phase9"]["level"] == "ok"


@pytest.mark.parametrize("physics",["static","dynamic"])
@pytest.mark.parametrize("mode",["direct","optimize"])
def test_saved_spring_custom_product_executes_through_frozen_engine(catalog,physics,mode):
    state = configured(catalog,physics=physics,mode=mode,use_custom=True)
    state["centralizer_config"]["custom_products"][0].update(kind="spring",bows=6,
        min_od_in=10.,max_od_in=12.25,restoring_force_lbf=1000.,starting_force_lbf=100.,running_force_lbf=50.)
    assert phase9().execute(state,catalog)["zones"][0]["product_kind"] == "spring"


def test_retired_zone_callback_cannot_overwrite_a_surviving_zone(catalog):
    state = configured(catalog)
    state["centralizer_config"]["zones"].append({**state["centralizer_config"]["zones"][0],"top_md":500.})
    old_key = "_centralizer_zone_0_0_top_md"
    state[old_key] = 99.
    with patch.object(phase9().st,"session_state",state):
        phase9()._zones_action("delete",0)
        phase9()._commit("top_md",old_key,0,epoch=0)
    assert state["centralizer_config"]["zones"][0]["top_md"] == 500.


def test_ui_results_show_named_percent_units_not_internal_payload(catalog):
    app = ui_app(configured(catalog))
    app.button(key="_centralizer_execute").click().run()
    assert not app.exception
    frame = app.dataframe[-1].value
    assert list(frame.columns) == ["Zone #","Computed Density","Min Standoff (%)","Status"]
    assert frame.iloc[0]["Min Standoff (%)"] == app.session_state["_centralizer_result"]["zones"][0]["min_stdf"] * 100


def test_deleted_custom_reference_in_one_zone_does_not_break_other_zone_callbacks(catalog):
    state = configured(catalog,use_custom=True)
    state["centralizer_config"]["zones"][0]["bottom_md"] = 500.
    state["centralizer_config"]["zones"].append({**zones_for(catalog)[0],"top_md":500.,"custom_product_id":None})
    state["centralizer_config"]["custom_products"] = []
    app = ui_app(state)
    app.selectbox(key="_centralizer_zone_0_1_product").set_value("official:"+str(zones_for(catalog)[0]["product_nr"])).run()
    assert not app.exception
    assert app.session_state["centralizer_config"]["zones"][0]["custom_product_id"] == "opaque-one"


def test_execute_button_runs_solver_once_and_rerun_never_reexecutes(catalog):
    app = ui_app(configured(catalog))
    with patch.object(adapter,"solve_static",wraps=adapter.solve_static) as call:
        app.button(key="_centralizer_execute").click().run()
        assert not app.exception and call.call_count == 1
        app.run()
        assert not app.exception and call.call_count == 1


@pytest.mark.parametrize("field,value",[("top_md",-1.),("bottom_md",-1.),("target_standoff_pct",101.),("aux",-1.)])
def test_restored_finite_out_of_widget_bounds_draft_remains_editable(catalog,field,value):
    state = configured(catalog,physics="dynamic" if field=="aux" else "static")
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)":None,"Burst (psi)":None})
    if field=="aux": state["centralizer_config"]["aux_rheology"]["Spacer"]["300"] = value
    else: state["centralizer_config"]["zones"][0][field] = value
    restored = audit.round_trip(state)
    app = ui_app(restored)
    assert not app.exception
    assert app.session_state["centralizer_config"] == restored["centralizer_config"]
    key = "_centralizer_aux_Spacer_300" if field=="aux" else f"_centralizer_zone_0_0_{field}"
    app.number_input(key=key).set_value(10.).run()
    assert not app.exception and app.radio(key="_app_mode_key").value=="phase9"
    config = app.session_state["centralizer_config"]
    assert (config["aux_rheology"]["Spacer"]["300"] if field=="aux" else config["zones"][0][field]) == 10.
