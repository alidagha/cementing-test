"""Full cement review admission must agree with the Phase-VII operator gate."""
from copy import deepcopy
from unittest.mock import patch

import pandas as pd
import pytest

import engineering_tools as eng
import phase_10_procedure as report
import project_state as ps
import test_audit_regressions as audit


CASE = audit.AuditRegressions()
DOC_KEYS = ("_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature")


@pytest.fixture(scope="module")
def reviewed_main():
    app = CASE.configured_app("CMT PLUG", optional_fluids=False)
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "ok"
    state = deepcopy(app.session_state.to_dict())
    assert ps.prepare_calculations(state) == []
    return state


def edit_main(reviewed_main):
    app = CASE.app(deepcopy(reviewed_main))
    CASE.phase(app, "phase7")
    reading = next(w for w in app.text_input if w.key.startswith("_rheo_main_surface_down_300_"))
    assert reading.value == "168"
    reading.set_value("169")
    CASE.phase(app, "phase1")
    qc = app.session_state["lab_qc_params"]["Main"]
    assert qc["rheology"]["surface_down"]["readings"]["300"] == "169"
    assert qc["review_signature"] != eng.lab_review_signature(qc, app.session_state["lab_grid_dfs"]["Main"])
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "warning"
    return app


def stale_document(state):
    state.update(zip(DOC_KEYS, (b"previous compiled document", "old.docx", "old signature")))


def reject(state, consumer, slurry):
    if consumer == "prepare":
        issues = ps.prepare_calculations(state)
        assert any(slurry in issue and "Phase VII" in issue for issue in issues), issues
    else:
        with patch.object(report.st, "session_state", state):
            with pytest.raises(ValueError, match=rf"{slurry}.*Phase VII"):
                report.build_master_context(calculations_prepared=consumer == "prepared")
    assert f"lab_payload_{slurry}" not in state
    assert all(key not in state for key in DOC_KEYS)


@pytest.mark.parametrize("consumer", ["prepare", "context", "prepared"])
def test_main_edit_is_rejected_at_every_admission(reviewed_main, consumer):
    app = edit_main(reviewed_main)
    state = deepcopy(app.session_state.to_dict())
    qc = deepcopy(state["lab_qc_params"])
    grid = state["lab_grid_dfs"]["Main"].copy(deep=True)
    source = deepcopy(state["lab_source_signatures"])
    stale_document(state)
    reject(state, consumer, "Main")
    assert state["lab_qc_params"] == qc
    pd.testing.assert_frame_equal(state["lab_grid_dfs"]["Main"], grid)
    assert state["lab_source_signatures"] == source
    CASE.phase(app, "phase10")
    assert next(b for b in app.button if b.label == "Build Word Document").disabled


@pytest.mark.parametrize("prepared", [False, True])
def test_explicit_main_rereview_recovers_current_context(reviewed_main, prepared):
    app = edit_main(reviewed_main)
    qc_before = deepcopy(app.session_state["lab_qc_params"]["Main"])
    grid = app.session_state["lab_grid_dfs"]["Main"].copy(deep=True)
    sources = deepcopy(app.session_state["lab_source_signatures"])
    CASE.phase(app, "phase7")
    button = next(b for b in app.button if b.label == "Confirm measured lab results")
    assert not button.disabled
    button.click().run()
    CASE.healthy(app)
    state = deepcopy(app.session_state.to_dict())
    qc = state["lab_qc_params"]["Main"]
    assert {k: v for k, v in qc.items() if k not in ("reviewed", "review_signature")} == {
        k: v for k, v in qc_before.items() if k not in ("reviewed", "review_signature")}
    pd.testing.assert_frame_equal(state["lab_grid_dfs"]["Main"], grid)
    assert state["lab_source_signatures"] == sources
    assert qc["reviewed"] and qc["review_signature"] == eng.lab_review_signature(qc, grid)
    assert eng.compute_phase_status(state)["phase7"]["level"] == "ok"
    assert ps.prepare_calculations(state) == []
    with patch.object(report.st, "session_state", state):
        ctx = report.build_master_context(calculations_prepared=prepared)
    expected = eng.validate_lab_rheology(qc, "Main")
    assert ctx["slurries"][0]["lab"]["rheology"] == expected


@pytest.mark.parametrize("slurry", ["Lead", "Tail"])
@pytest.mark.parametrize("defect", ["missing_qc", "missing_grid", "missing_both", "empty_grid", "missing_source", "stale_source", "missing_review", "unreviewed", "stale_signature"])
@pytest.mark.parametrize("consumer", ["prepare", "context", "prepared"])
def test_missing_or_unreviewed_sibling_cannot_use_old_payload(reviewed_main, slurry, defect, consumer):
    state = deepcopy(reviewed_main)
    state["fluids_config"]["active"] = [slurry, "Displacement Fluid"]
    state["fluids_config"]["params"][slurry] = state["fluids_config"]["params"].pop("Main")
    state["fluid_data"][slurry] = state["fluid_data"].pop("Main")
    state["fluid_data"][slurry]["name"] = slurry
    for key in ("cement_params", "cement_additives_dfs", "lab_grid_dfs", "lab_qc_params", "lab_source_signatures"):
        state[key][slurry] = state[key].pop("Main")
    state[f"lab_payload_{slurry}"] = state.pop("lab_payload_Main")
    assert state["lab_source_signatures"][slurry] == ps.lab_source_signature(state, slurry)
    assert state["lab_qc_params"][slurry]["review_signature"] == eng.lab_review_signature(
        state["lab_qc_params"][slurry], state["lab_grid_dfs"][slurry])
    if defect in ("missing_qc", "missing_both"):
        state["lab_qc_params"].pop(slurry)
    if defect in ("missing_grid", "missing_both"):
        state["lab_grid_dfs"].pop(slurry)
    if defect == "empty_grid":
        state["lab_grid_dfs"][slurry] = state["lab_grid_dfs"][slurry].iloc[:0].copy()
    if defect == "missing_source":
        state["lab_source_signatures"].pop(slurry)
    elif defect == "stale_source":
        state["lab_source_signatures"][slurry] = "previous formulation"
    if defect == "missing_review":
        state["lab_qc_params"][slurry].pop("reviewed")
        state["lab_qc_params"][slurry].pop("review_signature")
    elif defect == "unreviewed":
        state["lab_qc_params"][slurry]["reviewed"] = False
    elif defect == "stale_signature":
        state["lab_qc_params"][slurry]["rheology"]["surface_down"]["readings"]["300"] = "169"
    before_qc = deepcopy(state["lab_qc_params"])
    before_grids = deepcopy(state["lab_grid_dfs"])
    before_sources = deepcopy(state["lab_source_signatures"])
    stale_document(state)
    reject(state, consumer, slurry)
    assert state["lab_qc_params"] == before_qc
    assert state["lab_source_signatures"] == before_sources
    assert state["lab_grid_dfs"].keys() == before_grids.keys()
    for name, grid in before_grids.items():
        pd.testing.assert_frame_equal(state["lab_grid_dfs"][name], grid)


@pytest.fixture(scope="module")
def reviewed_preflush(reviewed_main):
    app = CASE.app(deepcopy(reviewed_main))
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_Pre Flush").check().run()
    app.number_input(key="vol_Pre Flush").set_value(25.0).run()
    app.text_input(key="den_Pre Flush").set_value("80.0").run()
    app.text_input(key="rate_Pre Flush").set_value("4.0").run()
    CASE.phase(app, "phase6")
    assert all(v["level"] == "ok" for v in eng.compute_phase_status(app.session_state).values())
    CASE.export(app)
    state = deepcopy(app.session_state.to_dict())
    assert state["_compiled_doc_bytes"].startswith(b"PK")
    assert ps.prepare_calculations(deepcopy(state)) == []
    return state


@pytest.fixture(scope="module")
def custom_preflush(reviewed_preflush):
    app = CASE.app(deepcopy(reviewed_preflush))
    CASE.phase(app, "phase6")
    app.selectbox(key="_w_preflush_name_choice").set_value("Custom").run()
    app.text_input(key="_w_preflush_name_custom").set_value("Wash Alpha & <original>").run()
    CASE.export(app)
    return deepcopy(app.session_state.to_dict())


def edit_preflush_name(project, origin, value, *, selector=False):
    app = CASE.app(deepcopy(project))
    CASE.phase(app, origin)
    assert all(key in app.session_state for key in DOC_KEYS)
    key = "_w_preflush_name_choice" if selector else "_w_preflush_name_custom"
    app.selectbox(key=key).set_value(value) if selector else app.text_input(key=key).set_value(value)
    CASE.phase(app, "phase1")
    assert app.session_state["fluids_config"]["params"]["Pre Flush"]["material_name"] == (
        "" if selector and value == "Custom" else value)
    assert app.session_state["fluid_data"]["Pre Flush"]["material_name"] == project["fluid_data"]["Pre Flush"]["material_name"]
    return app


def preflush_context(state, prepared):
    with patch.object(report.st, "session_state", state):
        return report.build_master_context(calculations_prepared=prepared)


@pytest.mark.parametrize("origin", ["phase4", "phase6"])
@pytest.mark.parametrize("consumer", ["prepare", "context", "prepared"])
def test_preflush_blank_name_navigation_requires_current_admission(reviewed_preflush, origin, consumer):
    app = edit_preflush_name(reviewed_preflush, origin, "Custom", selector=True)
    state = deepcopy(app.session_state.to_dict())
    assert eng.compute_phase_status(state)["phase4"]["level"] == "warning"
    before = deepcopy(state["fluids_config"])
    if consumer == "prepare":
        assert any("Phase IV" in issue and "Pre Flush" in issue for issue in ps.prepare_calculations(state))
    else:
        with pytest.raises(ValueError, match="Phase IV.*Pre Flush"):
            preflush_context(state, consumer == "prepared")
    assert state["fluids_config"] == before
    assert all(key not in state for key in DOC_KEYS)


@pytest.mark.parametrize("origin", ["phase4", "phase6"])
def test_preflush_valid_rename_retires_compiled_document_before_navigation(custom_preflush, origin):
    app = edit_preflush_name(custom_preflush, origin, "Wash Beta & <2>")
    assert eng.compute_phase_status(app.session_state)["phase4"]["level"] == "ok"
    assert all(key not in app.session_state for key in DOC_KEYS)


@pytest.mark.parametrize("origin", ["phase4", "phase6"])
@pytest.mark.parametrize("prepared", [False, True])
def test_preflush_valid_rename_context_and_authoritative_recovery(custom_preflush, origin, prepared):
    app = edit_preflush_name(custom_preflush, origin, "Wash Beta & <2>")
    state = deepcopy(app.session_state.to_dict())
    params = deepcopy(state["fluids_config"])
    cement = deepcopy(state["cement_params"])
    qc = deepcopy(state["lab_qc_params"])
    grid = state["lab_grid_dfs"]["Main"].copy(deep=True)
    if prepared:
        with pytest.raises(ValueError, match="Phase IV.*Pre Flush"):
            preflush_context(state, True)
        assert all(key not in state for key in DOC_KEYS)
    else:
        ctx = preflush_context(state, False)
        assert next(r for r in ctx["fluids_train"] if r["name"] == "Pre Flush")["material_name"] == "Wash Beta &amp; &lt;2&gt;"
    ps.refresh_fluids(state)
    ctx = preflush_context(state, True)
    fluid = next(r for r in ctx["fluids_train"] if r["name"] == "Pre Flush")
    assert fluid["material_name"] == "Wash Beta &amp; &lt;2&gt;"
    assert {k: v for k, v in fluid.items() if k != "material_name"} == {
        k: v for k, v in custom_preflush["fluid_data"]["Pre Flush"].items() if k != "material_name"}
    assert state["fluids_config"] == params
    assert state["cement_params"] == cement
    assert state["lab_qc_params"] == qc
    pd.testing.assert_frame_equal(state["lab_grid_dfs"]["Main"], grid)
    assert audit.round_trip(state)["fluids_config"]["params"]["Pre Flush"]["material_name"] == "Wash Beta & <2>"


@pytest.mark.parametrize("name", ["", "  ", None, "Custom", False, 123])
@pytest.mark.parametrize("prepared", [False, True])
def test_preflush_invalid_canonical_identity_cannot_use_valid_cache(reviewed_preflush, name, prepared):
    state = deepcopy(reviewed_preflush)
    state["fluids_config"]["params"]["Pre Flush"]["material_name"] = name
    before = deepcopy(state["fluids_config"])
    with pytest.raises(ValueError, match="Phase IV.*Pre Flush"):
        preflush_context(state, prepared)
    assert state["fluids_config"] == before
    assert all(key not in state for key in DOC_KEYS)


@pytest.mark.parametrize("prepared", [False, True])
def test_preflush_legacy_record_remains_the_identity_fallback(custom_preflush, prepared):
    state = deepcopy(custom_preflush)
    state["fluids_config"]["params"].pop("Pre Flush")
    ctx = preflush_context(state, prepared)
    expected = dict(custom_preflush["fluid_data"]["Pre Flush"], material_name="Wash Alpha &amp; &lt;original&gt;")
    assert next(r for r in ctx["fluids_train"] if r["name"] == "Pre Flush") == expected
    assert ctx["preflush"]["volume"] == 25.0


@pytest.mark.parametrize("selector", [False, True])
def test_preflush_unchanged_name_callback_preserves_compiled_authority(reviewed_preflush, custom_preflush, selector):
    import phase_4_fluids as fluids
    state = deepcopy(reviewed_preflush if selector else custom_preflush)
    before = {key: state[key] for key in DOC_KEYS}
    state["_unchanged_name"] = state["fluids_config"]["params"]["Pre Flush"]["material_name"]
    with patch.object(fluids.st, "session_state", state):
        fluids._commit_preflush_name("_unchanged_name", selector)
    assert {key: state[key] for key in DOC_KEYS} == before


def test_preflush_malformed_volume_precedes_invalid_name(reviewed_preflush):
    state = deepcopy(reviewed_preflush)
    state["fluids_config"]["params"]["Pre Flush"]["material_name"] = ""
    state["fluid_data"]["Pre Flush"]["volume"] = "abc"
    with pytest.raises(ValueError, match="Unreadable numeric volume.*Pre Flush"):
        preflush_context(state, True)
    assert all(key not in state for key in DOC_KEYS)


def test_preflush_recovered_identity_reaches_actual_word_without_quantity_drift(custom_preflush):
    from io import BytesIO
    from docx import Document
    app = edit_preflush_name(custom_preflush, "phase6", "Wash Beta & <2>")
    CASE.export(app)
    state = app.session_state.to_dict()
    doc = Document(BytesIO(state["_compiled_doc_bytes"]))
    fluid_table = next(t for t in doc.tables if any(c.text == "Type" for r in t.rows for c in r.cells))
    row = next(r for r in fluid_table.rows if any(c.text == "Pre Flush" for c in r.cells))
    assert "Wash Beta & <2>" in [c.text for c in row.cells]
    assert "Wash Alpha & <original>" not in [c.text for c in row.cells]
    assert state["preflush_calc"] == custom_preflush["preflush_calc"]
    assert state["cement_params"] == custom_preflush["cement_params"]
    assert state["lab_qc_params"] == custom_preflush["lab_qc_params"]
