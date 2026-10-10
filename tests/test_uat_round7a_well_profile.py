"""Round 7A canonical geometry/geothermal and downstream state contract."""
import json
from copy import deepcopy

import pandas as pd
import pytest

from project_state import refresh_well_derived
from project_io import decode_project
import test_audit_regressions as audit


def inputs(td=3000.0, source="BHST", value=200.0, surface=80.0):
    return {"well_geometry": {"version": 1, "type": "Vertical", "td_m": td,
                              "survey": pd.DataFrame(columns=["MD", "Deviation", "Azimuth"])},
            "geothermal_config": {"version": 1, "source": source,
                                  "surface_temp": surface, "value": value}}


def test_canonical_vertical_replaces_saved_projections():
    state = {**inputs(), "geo_md": 9999., "geo_tvd": 1234., "bhst": 777.,
             "geo_gradient": 9., "well_data": {}, "mud_density": "80-82",
             "well_auto_fields": {"bhsp": True}}
    refresh_well_derived(state)
    assert state["geo_md"] == state["geo_tvd"] == 3000.
    assert state["bhst"] == 200.
    assert state["geo_gradient"] == (200.-80.)/(3000.*3.28084)*100.
    assert float(state["bhsp"]) == pytest.approx(5603.88)


def test_gradient_source_owns_bhst_without_gradient_provenance():
    state = {**inputs(source="Temperature Gradient", value=1.5),
             "geo_tvd": 100., "bhst": 999., "well_auto_fields": {"bhsp": False}}
    refresh_well_derived(state)
    assert state["bhst"] == 80.+1.5*(3000.*3.28084/100.)
    assert state["geo_gradient"] == 1.5


def test_fresh_ui_has_explicit_unselected_geometry_and_temperature():
    app = audit.AuditRegressions().app()
    audit.AuditRegressions().phase(app, "phase2_3")
    geometry = next(w for w in app.selectbox if w.label == "Well Geometry")
    source = next(w for w in app.selectbox if w.label == "Temperature Source")
    assert geometry.value is None
    assert source.value is None


def test_malformed_canonical_geometry_rejected_before_replacement():
    raw = json.dumps({"job_type": "CMT PLUG", "well_geometry": []}).encode()
    with pytest.raises(ValueError, match="well_geometry"):
        decode_project(raw, audit.namespace["deserialize_item"])

from well_profile import (integrate_survey, resolve_well_profile, validate_well_inputs,
                          geometry_defaults, geothermal_defaults)
from project_state import lab_source_signature, prepare_calculations, restore_canonical_fields
from engineering_tools import compute_phase_status


def survey(md, inc, azi):
    return pd.DataFrame(zip(md, inc, azi), columns=["MD", "Deviation", "Azimuth"])


@pytest.mark.parametrize("md,inc,azi,expected", [
    ([0,500,1000], [35,45,55], [0,0,0], (1, "TVD", 1321.54-939, .01)),
    ([0,1000], [0,30], [0,0], (1, "TVD", 1954.93-1000, .01)),
    ([0,1000], [0,30], [0,0], (1, "North", 255.87, .01)),
    ([0,1000], [0,30], [0,0], (1, "DLS (deg/100 m)", 3., .005)),
    ([0,1000], [90,90], [0,90], (1, "North", 636.62, .01)),
    ([0,1000], [90,90], [0,90], (1, "Horizontal Departure", 900.32, .01)),
    ([0,1000], [90,90], [0,90], (1, "DLS (deg/100 m)", 9., .005)),
    ([0,8.5], [.3,1.], [180,117.5], (1, "East", .05541198, .0001)),
    ([0,8.5], [.3,1.], [180,117.5], (1, "North", -.07365608, .0001)),
])
def test_v22_authority_anchors(md, inc, azi, expected):
    # Offset examples are evaluated on relative MD; absolute-volume/depth
    # increments and DLS are translation invariant. No offset UI authority.
    index, field, value, tolerance = expected
    output = integrate_survey(survey(md, inc, azi))
    assert output.iloc[index][field] == pytest.approx(value, abs=tolerance)


def test_v22_build_drop_horizontal_wrap_and_nonnegative_dls():
    for frame in (survey([0,2500,5000],[0,60,0],[0,0,0]),
                  survey([0,2000,4000],[0,45,90],[45,45,45]),
                  survey([0,1000],[45,45],[350,10]),
                  survey([0,1000,2000,3000],[0,90,100,110],[0,0,0,0])):
        result = integrate_survey(frame)
        assert result.iloc[-1]["TVD"] < frame.iloc[-1]["MD"]
        assert result.iloc[-1]["Horizontal Departure"] > 0
        assert (result["DLS (deg/100 m)"] >= 0).all()
        for _, row in result.iterrows():
            assert row["Horizontal Departure"] == __import__('math').hypot(row["North"], row["East"])
    assert integrate_survey(survey([0,1000],[45,45],[350,10])).iloc[-1]["DLS (deg/100 m)"] < 5
    vertical = integrate_survey(survey([0,1000,3927],[0,0,0],[0,0,0]))
    assert vertical["TVD"].tolist() == [0.,1000.,3927.]
    assert vertical["North"].tolist() == vertical["East"].tolist() == [0.,0.,0.]


@pytest.mark.parametrize("frame", [
    survey([1,100],[0,0],[0,0]), survey([0,100,100],[0,0,0],[0,0,0]),
    survey([0,100,50],[0,0,0],[0,0,0]), survey([0,100],[-1,0],[0,0]),
    survey([0,100],[0,181],[0,0]), survey([0,100],[0,0],[0,-1]),
    survey([0,100],[0,0],[0,360]), survey([0,100],[0,float('inf')],[0,0]),
    pd.DataFrame([[0,True,0],[100,0,0]], columns=["MD","Deviation","Azimuth"]),
])
def test_invalid_stations_rejected_without_sort_or_repair(frame):
    original = frame.copy(deep=True)
    with pytest.raises(ValueError): integrate_survey(frame)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("record,key,value", [
    ("well_geometry","type", "horizontal"), ("well_geometry","type", []),
    ("well_geometry","version", 2), ("well_geometry","version", True),
    ("well_geometry","td_m", True), ("well_geometry","td_m", "3000"),
    ("well_geometry","td_m", float('inf')), ("well_geometry","td_m", -1),
    ("geothermal_config","source", []), ("geothermal_config","source", "absolute"),
    ("geothermal_config","version", "1"), ("geothermal_config","value", True),
    ("geothermal_config","surface_temp", float('nan')),
    ("geothermal_config","surface_temp", "80"),
])
def test_hostile_inputs_fail_transactionally(record,key,value):
    state = {"job_type": 'CMT PLUG', **inputs()}
    state[record][key] = value
    untouched = deepcopy(state)
    with pytest.raises(ValueError): audit.round_trip(state)
    from project_state import fingerprint
    assert fingerprint(state) == fingerprint(untouched)


@pytest.mark.parametrize("kind", [None,"Vertical","Directional"])
def test_incomplete_drafts_round_trip_but_block_readiness(kind):
    state = {"job_type": 'CMT PLUG', "well_geometry": geometry_defaults(),
             "geothermal_config": geothermal_defaults()}
    state["well_geometry"]["type"] = kind
    if kind == "Directional":
        state["well_geometry"]["survey"] = survey([0,None],[0,None],[0,None])
    restored = audit.round_trip(state)
    assert restored["well_geometry"]["type"] == kind
    assert restored["geothermal_config"]["source"] is None
    assert restored["geothermal_config"]["surface_temp"] == 80.
    assert compute_phase_status(restored)["phase2_3"]["level"] != "ok"
    assert prepare_calculations(restored)


def test_no_fallback_from_manual_projections_or_saved_calculated_rows():
    state = {"geo_md": 3000., "geo_tvd": 3000., "bhst": 200., "geo_gradient": 1.2,
             "well_data": {"geo_md": 3000., "geo_tvd": 3000., "bhst": 200.}}
    restore_canonical_fields(state)
    assert all(state[k] is None for k in ("geo_md","geo_tvd","bhst","geo_gradient"))
    assert state["well_geometry"]["type"] is state["geothermal_config"]["source"] is None
    assert state["_survey_result"].empty


def test_first_edits_switches_navigation_and_restore():
    case = audit.AuditRegressions()
    app = case.app()
    case.phase(app,"phase2_3")
    app.selectbox(key="_w_geometry_type").set_value("Vertical").run()
    app.number_input(key="_w_vertical_td").set_value(3000.)
    case.phase(app,"phase1")
    case.phase(app,"phase2_3")
    assert app.number_input(key="_w_vertical_td").value == 3000.
    app.selectbox(key="_w_temperature_source").set_value("BHST").run()
    app.number_input(key="_w_geothermal_bhst").set_value(200.)
    case.phase(app,"phase7")
    case.phase(app,"phase2_3")
    assert app.session_state["bhst"] == 200.
    original = deepcopy(app.session_state["_survey_result"])
    app.number_input(key="_w_surface_temp").set_value(90.).run()
    assert app.session_state["bhst"] == 200.
    assert app.session_state["geo_gradient"] == (200.-90.)/(3000.*3.28084)*100.
    pd.testing.assert_frame_equal(original, app.session_state["_survey_result"])
    app.selectbox(key="_w_temperature_source").set_value("Temperature Gradient").run()
    assert app.number_input(key="_w_geothermal_gradient").value is None
    assert app.session_state["bhst"] is None
    assert app.session_state["geothermal_config"]["surface_temp"] == 90.
    app.number_input(key="_w_geothermal_gradient").set_value(1.5)
    case.phase(app,"phase1")
    restored = case.app(audit.round_trip(app.session_state.to_dict()))
    case.phase(restored,"phase2_3")
    assert restored.number_input(key="_w_geothermal_gradient").value == 1.5
    assert restored.session_state["bhst"] == 90.+1.5*(3000.*3.28084/100.)
    restored.selectbox(key="_w_temperature_source").set_value("BHST").run()
    assert restored.number_input(key="_w_geothermal_bhst").value is None
    assert not [w for w in restored.number_input if w.label in ("MD (m)","TVD (m)")]


def test_geometry_and_temperature_invalidation_are_dependency_sensitive():
    state = {**inputs(), "bhct": 150., "mud_density": "80-82", "well_auto_fields": {"bhsp": True}}
    restore_canonical_fields(state)
    signature = lab_source_signature(state,"Main")
    state["_compiled_doc_bytes"] = b"old"
    state["geothermal_config"]["surface_temp"] = 90.
    refresh_well_derived(state)
    assert lab_source_signature(state,"Main") == signature
    assert "_compiled_doc_bytes" not in state
    state["well_geometry"]["td_m"] = 3100.
    refresh_well_derived(state)
    assert state["bhst"] == 200.
    assert lab_source_signature(state,"Main") != signature
    state["well_auto_fields"]["bhsp"] = False
    state["bhsp"] = state["well_data"]["bhsp"] = "7000+500"
    signature = lab_source_signature(state,"Main")
    state["well_geometry"]["td_m"] = 3200.
    refresh_well_derived(state)
    assert state["bhsp"] == "7000+500"
    assert lab_source_signature(state,"Main") == signature
    state["geothermal_config"].update(source="Temperature Gradient",value=1.5)
    refresh_well_derived(state)
    assert lab_source_signature(state,"Main") != signature


def test_fresh_restore_direct_phase_x_rebuilds_before_lab_signature_check():
    case = audit.AuditRegressions()
    app = case.configured_app('CSG 9 5/8"')
    saved = app.session_state.to_dict()
    saved.update(geo_md=9999.,geo_tvd=111.,bhst=777.,geo_gradient=9.)
    saved["well_data"].update(geo_md=9999.,geo_tvd=111.,bhst=777.,geo_gradient=9.)
    restored = case.app(audit.round_trip(saved))
    case.export(restored)  # No Phase II/III or Phase VII visit after restore.
    assert restored.session_state["geo_md"] == restored.session_state["geo_tvd"] == 3000.
    assert restored.session_state["lab_payload_Main"]["bhst"] == 200.
    assert restored.session_state["lab_payload_Main"]["bhct"] == 150.
    assert restored.session_state["_compiled_doc_bytes"]


def test_hidden_bhst_default_removed_and_bhct_helper_remains_advisory():
    case = audit.AuditRegressions()
    app = case.app({"fluids_config":{"active":["Main"]}})
    case.phase(app,"phase7")
    assert app.session_state.to_dict().get("bhst") is None
    assert not [w for w in app.number_input if "BHCT" in w.label]
    app = case.app(inputs(td=3100.))
    case.phase(app,"phase2_3")
    assert app.session_state["bhct"] is None
    assert any(b.key == "_apply_well_bhct" for b in app.button)
    app.number_input(key="_w_surface_temp").set_value(100.).run()
    assert app.session_state["bhct"] is None
    next(b for b in app.button if b.key == "_apply_well_bhct").click().run()
    assert app.session_state["bhct"] is not None
    app.number_input(key="_w_vertical_td").set_value(1000.).run()
    assert not [b for b in app.button if b.key == "_apply_well_bhct"]


def test_existing_low_bhst_advisory_is_preserved():
    case = audit.AuditRegressions()
    app = case.app(inputs(value=70.))
    case.phase(app, "phase2_3")
    assert app.session_state["bhst"] == 70.
    assert any("Thermal Alert" in warning.value for warning in app.warning)


@pytest.mark.parametrize("unfinished", ["surface", "geometry"])
def test_measured_bhst_authority_survives_unfinished_independent_inputs(unfinished):
    state = {**inputs(), "bhct": 150., "bhsp": "7000+500",
             "well_auto_fields": {"bhsp": False}}
    restore_canonical_fields(state)
    signature = lab_source_signature(state, "Main")
    state["_compiled_doc_bytes"] = b"old"
    if unfinished == "surface":
        state["geothermal_config"]["surface_temp"] = None
    else:
        state["well_geometry"]["td_m"] = None
    assert refresh_well_derived(state)
    assert state["bhst"] == state["well_data"]["bhst"] == 200.
    assert state["geo_gradient"] is None
    assert lab_source_signature(state, "Main") == signature
    assert "_compiled_doc_bytes" not in state


def test_gradient_authority_survives_unfinished_geometry():
    state = inputs(td=None, source="Temperature Gradient", value=1.5)
    assert refresh_well_derived(state)
    assert state["geo_gradient"] == 1.5
    assert state["bhst"] is None


@pytest.mark.parametrize("source,other,key,value", [
    ("BHST", "Temperature Gradient", "_w_geothermal_bhst", 220.),
    ("Temperature Gradient", "BHST", "_w_geothermal_gradient", 1.4),
])
def test_pending_temperature_edit_cannot_survive_a_source_switch(source,other,key,value):
    case = audit.AuditRegressions()
    app = case.app(inputs(source=source, value=200. if source == "BHST" else 1.5))
    case.phase(app, "phase2_3")
    app.number_input(key=key).set_value(value)
    app.selectbox(key="_w_temperature_source").set_value(other).run()
    assert not app.exception
    assert app.session_state["geothermal_config"]["source"] == other
    assert app.session_state["geothermal_config"]["value"] is None
    assert app.session_state["geothermal_config"]["surface_temp"] == 80.
    assert app.session_state["bhst"] is app.session_state["geo_gradient"] is None
