"""Adversarial lifecycle, transactional-load and repeated-report hardening."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import random
from unittest.mock import patch

from docx import Document
from docx.oxml.ns import qn
import pytest

import centralizer_adapter as adapter
import centralizer_report as bridge
import engineering_tools as tools
import phase_9_centralizer as phase9
import phase_10_procedure as report
from project_io import decode_project, replace_project_state
from project_state import fingerprint, is_project_key, restore_canonical_fields
import test_audit_regressions as audit
from test_uat_round9e_dynamic_solver import readings
from test_uat_round9f_phase9 import configured, custom, ui_app
from test_uat_round9g_centralizer_word import ix_region
from test_uat_round9h_integration import (
    test_real_phase_x_build_and_section_ix_contract as verify_word,
    word_projects,
)


@pytest.fixture(scope="module")
def catalog():
    return adapter.load_official_catalog()


def saved_bytes(state):
    return json.dumps({k: audit.namespace["serialize_item"](v) for k, v in state.items()
                       if is_project_key(k)}, allow_nan=False, sort_keys=True).encode()


@pytest.mark.parametrize("use_custom", [False, True])
def test_repeated_restore_execute_failure_repair_cannot_resurrect_success(catalog, use_custom):
    state = configured(catalog, physics="dynamic", use_custom=use_custom)
    # Keep the auxiliary failure/repair cycle on an actual Phase-IX auxiliary.
    state["fluids_config"]["active"] = ["Spacer Ahead" if name == "Spacer" else name
                                         for name in state["fluids_config"]["active"]]
    state["fluids_config"]["params"]["Spacer Ahead"] = dict(state["fluids_config"]["params"]["Spacer"])
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": None, "Burst (psi)": None})
    state["well_data"] = {}
    restore_canonical_fields(state)
    state = audit.round_trip(state)  # Establish the normal decode/rebuild projection first.
    expected = saved_bytes(state)
    signatures, profiles = [], []
    for cycle in range(4):
        phase9.execute(state, catalog)
        signatures.append(state["_centralizer_signature"])
        profiles.append(fingerprint(state["_centralizer_result"]))
        assert saved_bytes(state) == expected  # Derived output cannot grow project JSON.
        raw = json.loads(expected)
        raw.update(_centralizer_result={"hostile": True}, _centralizer_signature="resurrected")
        decoded = decode_project(json.dumps(raw).encode(), audit.namespace["deserialize_item"])
        replace_project_state(state, decoded, str(cycle))
        assert not any(key.startswith("_centralizer") for key in state)
        assert not phase9.result_is_current(state, catalog)
        with pytest.raises(ValueError, match="Phase IX"):
            bridge.prepare_report(state)
        phase9.execute(state, catalog)
        state["centralizer_config"]["aux_rheology"].pop("Spacer Ahead")
        with pytest.raises(ValueError, match="MissingRheology"):
            phase9.execute(state, catalog)
        state["centralizer_config"]["aux_rheology"]["Spacer Ahead"] = readings()
        assert not phase9.result_is_current(state, catalog)  # Repair alone is not Execute.
        assert "_centralizer_result" not in state and "_centralizer_signature" not in state
        phase9.execute(state, catalog)
        assert saved_bytes(state) == expected
    assert len(set(signatures)) == len(set(profiles)) == 1


def test_reindexed_widget_generations_ignore_retired_callbacks(catalog):
    state = configured(catalog)
    first = state["centralizer_config"]["zones"][0]
    state["centralizer_config"]["zones"] = [{**first, "top_md": i * 250., "bottom_md": (i + 1) * 250.}
                                           for i in range(4)]
    rng = random.Random(901)
    with patch.object(phase9.st, "session_state", state):
        for _ in range(20):
            zones = state["centralizer_config"]["zones"]
            epoch = state.get("_centralizer_zone_epoch", 0)
            index = rng.randrange(len(zones))
            state["_retired"] = -999.
            survivor = deepcopy(zones[:index] + zones[index + 1:])
            phase9._zones_action("delete", index)
            phase9._commit("top_md", "_retired", index, epoch=epoch)
            phase9._commit("product", "_retired", index, epoch=epoch)
            assert zones == survivor
            phase9._zones_action("add")
            newest = len(zones) - 1
            state["_current"] = float(100 + newest)
            phase9._commit("top_md", "_current", newest, epoch=state["_centralizer_zone_epoch"])
            assert zones[newest]["top_md"] == state["_current"]
            assert zones[:-1] == survivor


def test_middle_delete_then_first_edit_and_failed_execute_survive_navigation(catalog):
    state = configured(catalog)
    original = state["centralizer_config"]["zones"][0]
    state["centralizer_config"]["zones"] = [{**original, "top_md": i * 250., "bottom_md": (i + 1) * 250.}
                                           for i in range(4)]
    app = ui_app(state)
    app.button(key="_centralizer_execute").click().run()
    for turn in range(3):
        app.button(key=f"_centralizer_zone_{turn * 2}_1_delete").click().run()
        expected = deepcopy(app.session_state["centralizer_config"]["zones"])
        epoch = app.session_state["_centralizer_zone_epoch"]
        app.number_input(key=f"_centralizer_zone_{epoch}_1_top_md").set_value(510. + turn)
        app.radio(key="_app_mode_key").set_value("phase10").run()
        expected[1]["top_md"] = 510. + turn
        assert not app.exception and app.radio(key="_app_mode_key").value == "phase10"
        assert app.session_state["centralizer_config"]["zones"] == expected
        assert "_compiled_doc_bytes" not in app.session_state
        app.radio(key="_app_mode_key").set_value("phase9").run()
        assert app.number_input(key=f"_centralizer_zone_{epoch}_1_top_md").value == 510. + turn
        app.button(key="_centralizer_add_zone").click().run()
        assert app.session_state["centralizer_config"]["zones"][:-1] == expected
        app.button(key="_centralizer_execute").click().run()  # New zone is unfinished.
        assert not app.exception and app.error
        assert "_centralizer_result" not in app.session_state
        assert "_centralizer_signature" not in app.session_state


@pytest.mark.parametrize("physics", ["static", "dynamic"])
def test_mode_and_active_auxiliary_transition_cycle_consumes_only_current_sources(catalog, physics):
    state = configured(catalog, physics=physics)
    phase9.execute(state, catalog)
    original = state["_centralizer_signature"]
    state["fluids_config"]["active"].append("Spacer Behind")
    assert phase9.result_is_current(state, catalog) == (physics == "static")
    if physics == "dynamic":
        state["centralizer_config"]["aux_rheology"].pop("Spacer Behind")
        with pytest.raises(ValueError, match="MissingRheology.*Spacer Behind"):
            phase9.execute(state, catalog)
        state["centralizer_config"]["aux_rheology"]["Spacer Behind"] = readings()
        assert not phase9.result_is_current(state, catalog)
        phase9.execute(state, catalog)
    state["fluids_config"]["active"].remove("Spacer Behind")
    phase9.execute(state, catalog)
    assert state["_centralizer_signature"] == original
    state["centralizer_config"]["physics_mode"] = "dynamic" if physics == "static" else "static"
    assert not phase9.result_is_current(state, catalog)
    phase9.execute(state, catalog)
    state["centralizer_config"]["aux_rheology"]["Pre Flush"]["300"] += 1.
    assert phase9.result_is_current(state, catalog)  # Inactive auxiliary does not participate.


FAULTS = [
    (("version",), None), (("zones",), None), (("zones", 0), []),
    (("zones", 0, "top_md"), True), (("zones", 0, "bottom_md"), "1000"),
    (("zones", 0, "target_standoff_pct"), float("inf")),
    (("zones", 0, "product_nr"), False), (("zones", 0, "custom_product_id"), " "),
    (("placement_mode",), "DIRECT"), (("physics_mode",), []),
    (("aux_rheology", "Spacer", "300"), float("nan")),
    (("aux_rheology", "Spacer", "60"), False), (("aux_rheology", "Spacer"), [1, 2]),
    (("custom_products", 0, "custom_id"), ""), (("custom_products", 0, "bows"), True),
    (("custom_products", 0, "restoring_force_lbf"), -1.),
    (("custom_products", 0, "pipe_size_in"), "9.625"),
]


@pytest.mark.parametrize("path,value", FAULTS)
def test_hostile_load_cannot_partially_replace_executed_project(catalog, path, value):
    state = configured(catalog, use_custom=True)
    phase9.execute(state, catalog)
    state["_compiled_doc_bytes"] = b"existing-document"
    before = fingerprint(state)
    incoming = json.loads(saved_bytes(state))
    cursor = incoming["centralizer_config"]
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    with pytest.raises(ValueError):
        decoded = decode_project(json.dumps(incoming).encode(), audit.namespace["deserialize_item"])
        replace_project_state(state, decoded, "hostile")
    assert fingerprint(state) == before
    assert phase9.result_is_current(state, catalog)


@pytest.mark.parametrize("fault", ["missing", "extra", "duplicate_id", "six_products", "duplicate_json_key"])
def test_structural_faults_are_transactional_at_real_decode_boundary(catalog, fault):
    state = configured(catalog, use_custom=True)
    phase9.execute(state, catalog)
    before = fingerprint(state)
    incoming = json.loads(saved_bytes(state))
    config = incoming["centralizer_config"]
    if fault == "missing": config.pop("physics_mode")
    elif fault == "extra": config["result"] = {"old": True}
    elif fault == "duplicate_id": config["custom_products"] *= 2
    elif fault == "six_products": config["custom_products"] = [custom(str(i)) for i in range(6)]
    raw = json.dumps(incoming)
    if fault == "duplicate_json_key":
        raw = raw.replace('"version": 1', '"version": 1, "version": 1')
    with pytest.raises(ValueError):
        replace_project_state(state, decode_project(raw.encode(), audit.namespace["deserialize_item"]), "bad")
    assert fingerprint(state) == before


def test_deleted_selected_identity_reopens_without_redirect_or_old_success(catalog):
    state = configured(catalog, use_custom=True)
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": None, "Burst (psi)": None})
    phase9.execute(state, catalog)
    selected = state["centralizer_config"]["zones"][0]["custom_product_id"]
    state["centralizer_config"]["custom_products"].append(custom("same-display"))
    phase9.delete_custom_product(state, selected)
    decoded = audit.round_trip(state)
    assert decoded["centralizer_config"]["zones"][0]["custom_product_id"] == selected
    app = ui_app(decoded)
    assert app.selectbox(key="_centralizer_zone_0_0_product").value == "custom:" + selected
    app.button(key="_centralizer_execute").click().run()
    assert not app.exception and app.error
    assert not phase9.result_is_current(app.session_state.to_dict(), catalog)
    assert len(app.session_state["centralizer_config"]["custom_products"]) == 1


def test_replace_write_failure_rolls_back_current_result_document_and_custom_identity(catalog):
    class FailOnce(dict):
        def __setitem__(self, key, value):
            if key == "centralizer_config" and self.fail:
                self.fail = False
                raise RuntimeError("Injected replacement write failure")
            super().__setitem__(key, value)
    state = FailOnce(configured(catalog, use_custom=True))
    state.fail = False
    phase9.execute(state, catalog)
    state["_compiled_doc_bytes"] = b"current-word"
    before = fingerprint(state)
    project = decode_project(b'{"job_type":"CMT PLUG","centralizer_config":' +
                             json.dumps(phase9.new_config()).encode() + b'}',
                             audit.namespace["deserialize_item"])
    state.fail = True
    with pytest.raises(RuntimeError, match="replacement write"):
        replace_project_state(state, project, "replace-failed")
    assert fingerprint(state) == before and phase9.result_is_current(state, catalog)


def test_rejected_custom_form_submit_is_not_project_data_or_false_dirty_change(catalog):
    state = configured(catalog)
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": None, "Burst (psi)": None})
    state["centralizer_config"]["custom_products"] = [custom(str(i)) for i in range(5)]
    app = ui_app(state)
    inputs = deepcopy(app.session_state["centralizer_config"])
    next(b for b in app.button if b.label == "Save / Apply Custom Centralizer").click().run()
    assert not app.exception and any("at most five" in e.value for e in app.error)
    assert app.session_state["centralizer_config"] == inputs
    payload = saved_bytes(app.session_state.to_dict())
    assert not any(key.startswith("FormSubmitter:") for key in json.loads(payload))
    app.run()
    assert saved_bytes(app.session_state.to_dict()) == payload
    # The same save/load boundary must reject injected widget resurrection.
    hostile = json.loads(payload)
    hostile["FormSubmitter:_centralizer_custom_form_hostile-Save / Apply Custom Centralizer"] = True
    decoded = decode_project(json.dumps(hostile).encode(), audit.namespace["deserialize_item"])
    assert not any(key.startswith("FormSubmitter:") for key in decoded)


def test_real_job_selector_cycle_does_not_leak_completion_or_jump(catalog):
    state = configured(catalog, use_custom=True)
    phase9.execute(state, catalog)
    app = ui_app(state)
    original = deepcopy(state["centralizer_config"])
    for job in ('LNR 7"', 'TIE BACK LNR 7"', 'CMT PLUG', 'CMT SQUEEZE', 'CSG 9 5/8"'):
        app.radio(key="_app_mode_key").set_value("phase1").run()
        app.selectbox(key="_w_job_type").set_value(job).run()
        app.radio(key="_app_mode_key").set_value("phase9").run()
        assert not app.exception and app.radio(key="_app_mode_key").value == "phase9"
        assert app.session_state["centralizer_config"] == original
        status = tools.compute_phase_status(app.session_state)["phase9"]
        if job in ('CMT PLUG', 'CMT SQUEEZE'):
            assert status["level"] == "ok" and "Not applicable" in status["message"]
            assert not any(b.label == "Execute Centralizer" for b in app.button)
        elif job != state["job_type"]:
            assert status["level"] != "ok"
            assert not phase9.result_is_current(app.session_state.to_dict(), catalog)
        assert "_compiled_doc_bytes" not in app.session_state


def test_geometry_pipe_change_keeps_unavailable_product_identity_visible(catalog):
    state = configured(catalog, use_custom=True)
    phase9.execute(state, catalog)
    identity = state["centralizer_config"]["zones"][0]["custom_product_id"]
    active = state["hardware_table"]["Description"] == "Casing"
    state["hardware_table"].loc[active, "Size (in)"] = "7"
    state["hardware_table"].loc[active, "ID (in)"] = 6.
    app = ui_app(state)
    assert not phase9.result_is_current(app.session_state.to_dict(), catalog)
    assert any("not in the current pipe-size candidate list" in w.value for w in app.warning)
    assert app.selectbox(key="_centralizer_zone_0_0_product").value == "custom:" + identity
    assert app.session_state["centralizer_config"]["zones"][0]["custom_product_id"] == identity


@pytest.mark.parametrize("target", [0.0001, 100.])
def test_touching_gapped_and_shallow_zone_sets_use_real_engine(catalog, target):
    state = configured(catalog)
    zone = state["centralizer_config"]["zones"][0]
    state["centralizer_config"]["zones"] = [
        {**zone, "top_md": top, "bottom_md": bottom, "target_standoff_pct": target}
        for top, bottom in ((0., 0.1), (0.1, 400.), (500., 1000.))]
    before = saved_bytes(state)
    phase9.execute(state, catalog)
    assert saved_bytes(state) == before and phase9.result_is_current(state, catalog)
    assert len(state["_centralizer_result"]["zones"]) == 3


def test_parallel_and_failed_companion_rendering_leave_caller_figures_and_no_files(catalog):
    companion = bridge._companion()
    owned = companion.plt.figure()
    baseline = set(companion.plt.get_fignums())
    temporary = set(Path("/tmp").glob("round9g-standoff-*"))
    prepared = []
    for label, kind in (("Independent Casing", "casing"), ("Independent Liner", "liner")):
        state = configured(catalog, kind, use_custom=True)
        state["well_name"] = label
        phase9.execute(state, catalog)
        prepared.append(bridge.prepare_report(state))
    before = fingerprint(prepared)
    try:
        expected = [bridge.render_chart_png(p) for p in prepared]
        assert expected[0] != expected[1]
        with ThreadPoolExecutor(max_workers=2) as workers:
            actual = list(workers.map(bridge.render_chart_png, prepared * 3))
        assert actual == expected * 3 and fingerprint(prepared) == before
        assert set(companion.plt.get_fignums()) == baseline
        original = companion.render_pipe_standoff_chart
        def failed(*args, **kwargs):
            original(*args, **kwargs)
            companion.plt.figure()
            raise ValueError("Injected failure after PNG write")
        with patch.object(companion, "render_pipe_standoff_chart", side_effect=failed), \
             pytest.raises(ValueError, match="after PNG"):
            bridge.render_chart_png(prepared[0])
        assert set(companion.plt.get_fignums()) == baseline
        assert set(Path("/tmp").glob("round9g-standoff-*")) == temporary
    finally:
        companion.plt.close(owned)


STRESS_CASES = [
    ('CSG 9 5/8"', "static", "direct", False, 1, False),
    ('CSG 9 5/8"', "dynamic", "optimize", True, 2, True),
    ('LNR 7"', "static", "optimize", True, 5, False),
    ('TIE BACK LNR 7"', "dynamic", "direct", False, 8, False),
]


@pytest.mark.parametrize("job,physics,mode,use_custom,zones,miss", STRESS_CASES)
def test_repeated_phase_x_builds_one_two_five_eight_zone_reports(
        word_projects, job, physics, mode, use_custom, zones, miss):
    instances = []
    original = audit.AuditRegressions.app
    def capture(self, *args, **kwargs):
        app = original(self, *args, **kwargs)
        instances.append(app)
        return app
    with patch.object(audit.AuditRegressions, "app", capture):
        verify_word(word_projects, job, physics, mode, use_custom, zones, miss)
    app = instances[-1]
    before = saved_bytes(app.session_state.to_dict())
    signatures, pictures = [], []
    companion = bridge._companion()
    figures = set(companion.plt.get_fignums())
    for _ in range(3):
        next(b for b in app.button if b.label == "Build Word Document").click().run(timeout=120)
        assert not app.exception and not app.error
        state = app.session_state.to_dict()
        assert saved_bytes(state) == before and phase9.result_is_current(state)
        with patch.object(report.st, "session_state", state):
            context = report.build_master_context()
        signatures.append(report.document_signature(context, audit.ROOT / "master_template.docx"))
        doc = Document(BytesIO(state["_compiled_doc_bytes"]))
        region = ix_region(doc)
        tables = [t for t in doc.tables if t._tbl in region]
        assert len(tables[1].rows) == zones + 2
        styles = [tuple(str(cell._tc.tcPr.xml) for cell in row.cells) for row in tables[1].rows[2:]]
        assert len(set(styles)) == 1
        assert len(region[-1].xpath('.//w:br[@w:type="page"]')) == 1
        drawing = next(e for e in region if e.xpath('.//w:drawing'))
        rid = drawing.xpath('.//a:blip')[0].get(qn("r:embed"))
        pictures.append(doc.part.related_parts[rid].blob)
        assert context["all_notes"][-1] == context["note_centralizer"]
        assert len(context["all_notes"]) == len(set(context["all_notes"]))
    assert len(set(signatures)) == len(set(pictures)) == 1
    assert set(companion.plt.get_fignums()) == figures
