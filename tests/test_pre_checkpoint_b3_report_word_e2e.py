"""B3: adversarial edits between real Word builds, reviews and checkpoints."""
from copy import deepcopy
from io import BytesIO
from html import unescape
import hashlib
import re
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
import pytest

import engineering_tools as eng
import materials_db as db
import project_state as ps
import phase_10_procedure as report
import phase_9_centralizer as phase9
import cement_chart_model as chart
import pumping_simulation as pumping
import test_audit_regressions as audit
from centralizer_fixtures import execute_centralizer
from test_uat_round10c_integration import build, save_project, restore_project
from test_uat_round12a5_diesel_word_e2e import numbered_steps
from test_pre_checkpoint_b2_cross_module_integration import (
    projects as integrated_projects, JOBS, CSG, LNR, select_target, signatures, assert_advisory_section, assert_advisory_payload,
)


CASE = audit.AuditRegressions()


@pytest.fixture(scope="module")
def r17b2_sources(r17_filename_source):
    """Synthetic repository prerequisites; measured lab is confirmed through its UI."""
    cache = {CSG: deepcopy(r17_filename_source)}

    def get(job):
        if job not in cache:
            if job == db.CT_JOB:
                from test_round13b_b4_ct_report import valid_ct
                state = valid_ct.__wrapped__()
            else:
                state = CASE.configured_app(job, include_standalone_spacer=False).session_state.to_dict()
            if job == 'LNR 7"':
                state['fluids_config']['active'] = ['Lead', 'Tail', 'Displacement Fluid']
                for name in ('Lead', 'Tail'):
                    state['fluids_config']['params'][name] = deepcopy(state['fluids_config']['params']['Main'])
                    state['cement_params'][name] = dict(state['cement_params']['Main'], top_mode='Not entered', top_depth=None)
                    state['cement_additives_dfs'][name] = state['cement_additives_dfs']['Main'].copy()
                    state['lab_qc_params'][name] = dict(state['lab_qc_params']['Main'], reviewed=False)
                app = CASE.app(audit.round_trip(state))
                for phase in ('phase4', 'phase5', 'phase7'):
                    CASE.phase(app, phase)
                for key in [b.key for b in app.button if b.label == 'Sync with Phase V']:
                    app.button(key=key).click().run()
                for _ in ('Lead', 'Tail'):
                    next(b for b in app.button if b.label == 'Confirm measured lab results' and not b.disabled).click().run()
                execute_centralizer(app.session_state)
                state = app.session_state.to_dict()
            cache[job] = state
        return deepcopy(cache[job])
    return get


def r17b2_engineering(state):
    from placement import slurry_intervals
    import well_schematic_adapter as schematic
    names = report.active_slurry_names(state['fluids_config']['active'])
    keys = ('hardware_table', 'well_data', 'well_geometry', 'placement_config', 'fluid_data',
            'fluids_config', 'cement_params', 'lab_qc_params')
    values = {k: state.get(k) for k in keys}
    values.update({k: v for k, v in state.items() if k.startswith(('cement_calc_', 'cement_raw_calc_', 'lab_payload_'))})
    return (ps.fingerprint(values), ps.fingerprint(chart.build_chart_model(state)),
            phase9.source_signature(state), pumping.source_signature(state), schematic.source_signature(state),
            tuple((n, ps.lab_source_signature(state, n)) for n in names),
            slurry_intervals(state['hardware_table'], state['job_type'], state['placement_config'], names,
                             state['cement_params'], state['fluid_data']),
            {k: v for k, v in eng.compute_phase_status(state).items() if k != 'phase10'})


def r17b2_build(app, sentence, path):
    from streamlit.elements.widgets import button as buttons
    with patch.object(buttons, 'marshall_file', wraps=buttons.marshall_file) as served:
        data = build(app)
    matches = [c.args for c in served.call_args_list if c.args[2].label == 'Download Final Document (.docx)']
    assert matches and matches[-1][1] == data
    expected_name = ('Cementing Program - CSG 9.625 - Regression Well - R #0.docx' if app.session_state['job_type'] == CSG else
                     'Cementing Program - LNR 7 - Regression Well - R #0.docx')
    assert matches[-1][4] == app.session_state['_compiled_doc_filename'] == expected_name
    doc = Document(BytesIO(data))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert text.count(sentence) == 1
    assert app.session_state['_compiled_doc_signature'] == report.document_signature(context(app.session_state.to_dict()), report.TEMPLATE_PATH)
    signature = app.session_state['_compiled_doc_signature']
    next(b for b in app.get('download_button') if b.label == 'Download Final Document (.docx)').click().run()
    assert app.session_state['_compiled_doc_bytes'] == data
    assert app.session_state['_compiled_doc_signature'] == signature
    assert app.session_state['_compiled_doc_filename'] == expected_name
    path.write_bytes(data)
    return data


def r17b2_project_download(app):
    from streamlit.elements.widgets import button as buttons
    with patch.object(buttons, 'marshall_file', wraps=buttons.marshall_file) as served:
        next(b for b in app.button if b.label == 'Prepare project download').click().run()
    matches = [c.args for c in served.call_args_list if c.args[2].label == 'Download Project (.json)']
    assert matches
    data = matches[-1][1]
    next(b for b in app.get('download_button') if b.label == 'Download Project (.json)').click().run()
    CASE.healthy(app)
    return data.encode() if isinstance(data, str) else data


@pytest.mark.parametrize('job,mode', [(CSG, 'apply'), ('LNR 7"', 'ignore')])
def test_r17b2_real_word_toggle_download_and_uploaded_restore(r17b2_sources, job, mode, tmp_path):
    app = CASE.app(r17b2_sources(job))
    names = ['Main'] if job == CSG else ['Lead', 'Tail']
    app.session_state['executive_summary_config'] = {'version': 1, 'job_type': job, 'per_slurry': {
        name: {'volume_basis': 'direct', 'excess_csg_oh_pct': 25. + 25. * i,
               'excess_csg_csg_pct': 10.5 if i == 0 else 20.} for i, name in enumerate(names)}}
    CASE.phase(app, 'phase2_3')
    for label, value in [('Excess CSG-OH %', 25.), ('Excess CSG-CSG %', 10.5)]:
        next(w for w in app.number_input if w.label == label).set_value(value).run()
    control = next(w for w in app.selectbox if w.label == 'Chart Capacity Excess Mode')
    control.set_value('ignore').run()
    ignored = chart.resolve_cement_placement(app.session_state)
    next(w for w in app.selectbox if w.label == 'Chart Capacity Excess Mode').set_value('apply').run()
    assert chart.resolve_cement_placement(app.session_state) != ignored  # The engineering control stays effective.
    next(w for w in app.selectbox if w.label == 'Chart Capacity Excess Mode').set_value(mode).run()
    execute_centralizer(app.session_state)
    receipt = r17b2_engineering(app.session_state.to_dict())
    if job == CSG:
        client = 'The calculated cement volume is based on client request, giving 50.0 bbl for main slurry.'
        actual = 'The calculated cement volume is based on 25% excess for OH-CSG and 10.5% excess for CSG-CSG, giving 50.0 bbl for main slurry.'
    else:
        client = 'The calculated cement volume is based on client request, giving 50.0 bbl for lead slurry and 50.0 bbl for tail slurry.'
        actual = ('The calculated cement volume is based on 25% excess for OH-CSG and 10.5% excess for CSG-CSG, giving 50.0 bbl for lead slurry. '
                  'The calculated cement volume is based on 50% excess for OH-CSG and 20% excess for CSG-CSG, giving 50.0 bbl for tail slurry.')
    documents = []
    for basis, sentence in [('client_request', client), ('excess', actual)]:
        CASE.phase(app, 'phase2_3')
        choices = [w for w in app.selectbox if w.label == 'Volume Basis']
        assert len(choices) == 1 and choices[0].options == ['Client Request', 'Actual Calculation']
        old_sig = app.session_state.to_dict().get('_compiled_doc_signature')
        choices[0].set_value(basis).run()
        no_document(app.session_state)
        assert r17b2_engineering(app.session_state.to_dict()) == receipt
        assert next(w for w in app.selectbox if w.label == 'Chart Capacity Excess Mode').value == mode
        CASE.phase(app, 'phase10')
        assert not any(w.label.startswith('Volume basis — ') for w in app.selectbox)
        for name in names:
            for label in ('Excess CSG-OH % override — ', 'Excess CSG-CSG % override — '):
                assert any(w.label == label + name for w in app.number_input)
            if job.startswith('LNR'):
                assert any(w.label == 'Wet stands — ' + name for w in app.number_input)
                assert any(w.label == 'Liner lap (m) — ' + name for w in app.number_input)
        data = r17b2_build(app, sentence, tmp_path / (basis + '.docx'))
        assert app.session_state['_compiled_doc_signature'] != old_sig
        assert r17b2_engineering(app.session_state.to_dict()) == receipt
        documents.append(data)
        raw = r17b2_project_download(app)
        (tmp_path / (basis + '.json')).write_bytes(raw)
        fresh = CASE.app()
        next(w for w in fresh.file_uploader if w.label == 'Load Project (.json)').set_value((basis + '.json', raw, 'application/json')).run()
        if any(b.key == '_confirm_upload_replacement' for b in fresh.button):
            assert any('unsaved changes' in w.value for w in fresh.warning)
            fresh.button(key='_confirm_upload_replacement').click().run()
        CASE.healthy(fresh)
        no_document(fresh.session_state)
        assert not phase9.result_is_current(fresh.session_state)
        assert fresh.session_state['executive_summary_config'] == app.session_state['executive_summary_config']
        execute_centralizer(fresh.session_state)  # Genuine backend rebuild; no restored private receipt is trusted.
        CASE.phase(fresh, 'phase2_3')
        assert next(w for w in fresh.selectbox if w.label == 'Volume Basis').value == basis
        assert r17b2_engineering(fresh.session_state.to_dict()) == receipt
        r17b2_build(fresh, sentence, tmp_path / (basis + '-restored.docx'))
        CASE.phase(app, 'phase2_3')
    # Same ZIP members and byte-equal parts; only the exact checked prose differs in document.xml.
    with ZipFile(BytesIO(documents[0])) as a, ZipFile(BytesIO(documents[1])) as b:
        assert a.namelist() == b.namelist()
        for name in a.namelist():
            x, y = a.read(name), b.read(name)
            if name == 'word/document.xml':
                assert x.count(client.encode()) == y.count(actual.encode()) == 1
                x, y = x.replace(client.encode(), b'VOLUME_SENTENCE'), y.replace(actual.encode(), b'VOLUME_SENTENCE')
            assert x == y, name


def test_r17b2_manual_review_build_keep_regenerate_restore(r17b2_sources, tmp_path):
    app = CASE.app(r17b2_sources(CSG))
    CASE.phase(app, 'phase2_3')
    next(w for w in app.selectbox if w.label == 'Volume Basis').set_value('client_request').run()
    client = 'The calculated cement volume is based on client request, giving 50.0 bbl for main slurry.'
    r17b2_build(app, client, tmp_path / 'client.docx')
    receipt = r17b2_engineering(app.session_state.to_dict())
    manual = app.session_state['exec_summary_text'] + '\n\nOperator-reviewed summary annotation.'
    next(w for w in app.text_area if w.label.startswith('Executive Summary Text')).set_value(manual).run()
    CASE.phase(app, 'phase2_3')
    next(w for w in app.selectbox if w.label == 'Volume Basis').set_value('excess').run()
    CASE.phase(app, 'phase10')
    blocked(app)
    assert app.session_state['exec_summary_text'] == manual
    app.button(key='_keep_exec_summary_text').click().run()
    kept = r17b2_build(app, client, tmp_path / 'kept.docx')
    assert '\n\nOperator-reviewed summary annotation.' in '\n'.join(semantics(kept)[0])
    app.button(key='_regenerate_exec_summary_text').click().run()
    actual = 'The calculated cement volume is 50.0 bbl.'  # No excess source was supplied.
    regenerated = r17b2_build(app, actual, tmp_path / 'regenerated.docx')
    assert 'Operator-reviewed summary annotation.' not in '\n'.join(semantics(regenerated)[0])
    app.button(key='_restore_exec_summary_text').click().run()
    blocked(app)
    assert app.session_state['exec_summary_text'] == manual
    assert r17b2_engineering(app.session_state.to_dict()) == receipt


@pytest.mark.parametrize('fault', ['rate', 'lab', 'geometry'])
def test_r17b2_basis_never_bypasses_independent_admission(r17b2_sources, fault, tmp_path):
    app = CASE.app(r17b2_sources(CSG))
    CASE.phase(app, 'phase2_3')
    next(w for w in app.selectbox if w.label == 'Volume Basis').set_value('client_request').run()
    r17b2_build(app, 'The calculated cement volume is based on client request, giving 50.0 bbl for main slurry.', tmp_path / 'before.docx')
    if fault == 'rate':
        CASE.phase(app, 'phase4')
        app.text_input(key='rate_Main').set_value('bad').run()
    elif fault == 'lab':
        CASE.phase(app, 'phase7')
        next(w for w in app.number_input if w.label == 'Surface Sample Hours - Main').set_value(8.25).run()
        qc = app.session_state['lab_qc_params']['Main']
        assert qc['surface_hardened_hours'] == 8.25
        assert qc['review_signature'] != eng.lab_review_signature(qc, app.session_state['lab_grid_dfs']['Main'])
        assert any(b.label == 'Confirm measured lab results' for b in app.button)
    else:
        CASE.phase(app, 'phase2_3')
        next(w for w in app.selectbox if w.label == 'Target shoe / treatment depth source').set_value('').run()
    CASE.phase(app, 'phase2_3')
    next(w for w in app.selectbox if w.label == 'Volume Basis').set_value('excess').run()
    blocked(app)
    phase = {'rate': 'phase4', 'lab': 'phase7', 'geometry': 'phase2_3'}[fault]
    assert eng.compute_phase_status(app.session_state)[phase]['level'] != 'ok'


@pytest.mark.parametrize('job', ['TIE BACK LNR 7"', 'CMT PLUG', 'CMT SQUEEZE', db.CT_JOB])
def test_r17b2_lightweight_sibling_ui_and_report_context(r17b2_sources, job):
    app = CASE.app(r17b2_sources(job))
    for basis in ('client_request', 'excess'):
        CASE.phase(app, 'phase2_3')
        next(w for w in app.selectbox if w.label == 'Volume Basis').set_value(basis).run()
        CASE.phase(app, 'phase10')
        assert not any(w.label.startswith('Volume basis — ') for w in app.selectbox)
        ctx = context(app.session_state.to_dict())
        assert ('based on client request' in unescape(ctx['exec_summary'])) == (basis == 'client_request')
        assert not next(b for b in app.button if b.label == 'Build Word Document').disabled


def test_r17b2_unsupported_basis_json_upload_is_rejected_without_source_replacement(r17b2_sources):
    import json
    app = CASE.app(r17b2_sources(CSG))
    CASE.phase(app, 'phase2_3')
    next(w for w in app.selectbox if w.label == 'Volume Basis').set_value('client_request').run()
    before = deepcopy(app.session_state['executive_summary_config'])
    checkpoint = json.loads(save_project(app))
    for invalid in ('auto', 0, None, ['excess']):
        bad = deepcopy(checkpoint)
        bad['executive_summary_config']['volume_basis'] = invalid
        raw = json.dumps(bad).encode()
        next(w for w in app.file_uploader if w.label == 'Load Project (.json)').set_value(('invalid.json', raw, 'application/json')).run()
        CASE.healthy(app)
        assert any('executive_summary_config.volume_basis is not supported' in e.value for e in app.error)
        assert app.session_state['executive_summary_config'] == before


@pytest.fixture(scope="module")
def r17_filename_source():
    app = CASE.configured_app(CSG, include_standalone_spacer=False)
    return app.session_state.to_dict()


@pytest.mark.parametrize("fields,expected", [
    ({"well_location": "South Pars", "well_name": "SP-101", "rig_name": "Rig-28",
      "proposal_number": "1457", "revision_no": "2"},
     "Cementing Program - CSG 9.625 - South Pars - SP-101 - Rig-28 - PR #1457 - R #2.docx"),
    ({"well_location": " ", "well_name": "SP-101", "rig_name": "",
      "proposal_number": "", "revision_no": " "},
     "Cementing Program - CSG 9.625 - SP-101.docx"),
])
def test_r17_download_filename_real_build_and_navigation(r17_filename_source, fields, expected, tmp_path):
    from streamlit.elements.widgets import button as buttons
    app = CASE.app(deepcopy(r17_filename_source))
    CASE.phase(app, "phase1")
    for field, value in fields.items():
        app.text_input(key="_w_" + field).set_value(value).run()
    CASE.phase(app, "phase10")
    raw = deepcopy(app.session_state["doc_control"])
    qc = deepcopy(app.session_state["lab_qc_params"])
    ctx = context(app.session_state.to_dict())
    signature = report.document_signature(ctx, report.TEMPLATE_PATH)
    source_signatures = signatures(app.session_state)
    with patch.object(buttons, "marshall_file", wraps=buttons.marshall_file) as served:
        data = build(app)
    downloads = [call.args for call in served.call_args_list
                 if call.args[2].label == "Download Final Document (.docx)"]
    assert downloads and downloads[-1][1] == data and downloads[-1][4] == expected
    (tmp_path / "actual.docx").write_bytes(data)
    (tmp_path / "filename.txt").write_text(app.session_state["_compiled_doc_filename"])
    assert app.session_state["doc_control"] == raw
    assert app.session_state["lab_qc_params"] == qc
    assert signatures(app.session_state) == source_signatures
    assert app.session_state["_compiled_doc_signature"] == signature
    assert app.session_state["_compiled_doc_filename"] == expected
    assert app.get("download_button")[-1].proto.label == "Download Final Document (.docx)"
    CASE.phase(app, "phase1")
    CASE.phase(app, "phase10")
    assert app.session_state["_compiled_doc_bytes"] == data
    assert app.session_state["_compiled_doc_signature"] == signature
    assert app.session_state["_compiled_doc_filename"] == expected
    if fields["rig_name"]:
        CASE.phase(app, "phase1")
        app.text_input(key="_w_rig_name").set_value("Rig-29").run()
        CASE.phase(app, "phase10")
        no_document(app.session_state)
        updated = build(app)
        assert app.session_state["_compiled_doc_filename"] == expected.replace("Rig-28", "Rig-29")
        assert app.session_state["_compiled_doc_signature"] != signature
        assert "Rig-29" in [t.text for t in Document(BytesIO(updated)).element.iter(qn("w:t"))]


@pytest.mark.parametrize("metadata,expected", [
    ({}, "Cementing Program.docx"),
    (dict.fromkeys(("job_type", "well_location", "well_name", "rig_name", "proposal_number", "revision_no")),
     "Cementing Program.docx"),
    ({"job_type": " ", "well_location": "\t", "well_name": "\n", "revision_no": " "},
     "Cementing Program.docx"),
    ({"well_location": "South Pars", "revision_no": 0}, "Cementing Program - South Pars - R #0.docx"),
    ({"proposal_number": 1457, "revision_no": 2}, "Cementing Program - PR #1457 - R #2.docx"),
    ({"proposal_number": " PR #1457 ", "revision_no": "R #2"}, "Cementing Program - PR #1457 - R #2.docx"),
    ({"proposal_number": "pr#PR #1457", "revision_no": "r#R #0"}, "Cementing Program - PR #1457 - R #0.docx"),
    ({"proposal_number": "PR # ", "revision_no": "R#"}, "Cementing Program.docx"),
    ({"job_type": 'CSG 13 3/8"'}, "Cementing Program - CSG 13.375.docx"),
    ({"job_type": 'LNR 4 1/2"'}, "Cementing Program - LNR 4.5.docx"),
    ({"job_type": 'TIE BACK LNR 4 1/2"'}, "Cementing Program - TIE BACK LNR 4.5.docx"),
    ({"job_type": 'CSG 18 5/8"'}, "Cementing Program - CSG 18.625.docx"),
    ({"job_type": 'CSG 20"'}, "Cementing Program - CSG 20.docx"),
    ({"job_type": 'CSG 9.625"'}, "Cementing Program - CSG 9.625.docx"),
    ({"job_type": 'CSG 9 63/64"'}, "Cementing Program - CSG 9.984375.docx"),
    ({"job_type": "CMT PLUG WITH CT"}, "Cementing Program - CMT PLUG WITH CT.docx"),
    ({"job_type": 'CSG 9 8/8"'}, "Cementing Program - CSG 9 8 8.docx"),
    ({"job_type": 'CSG 9 5/0"'}, "Cementing Program - CSG 9 5 0.docx"),
    ({"job_type": 'CSG 9+5/8"'}, "Cementing Program - CSG 9+5 8.docx"),
    ({"job_type": 'Unknown 9 5/8"'}, "Cementing Program - Unknown 9 5 8.docx"),
    ({"well_name": "SP-101 9 5/8", "well_location": "2026-11-04", "rig_name": "Rig-28"},
     "Cementing Program - 2026-11-04 - SP-101 9 5 8 - Rig-28.docx"),
    ({"well_name": '  SP/101\\West: <a>|?*\x00\n..  ', "rig_name": '"Rig-28". '},
     "Cementing Program - SP 101 West a - Rig-28.docx"),
    ({"well_name": "../..\\", "proposal_number": "\x00<>"}, "Cementing Program.docx"),
    ({"well_name": "چاه ۱۰۱", "rig_name": "CON"}, "Cementing Program - چاه ۱۰۱ - CON.docx"),
])
def test_r17_download_filename_is_a_pure_metadata_projection(metadata, expected):
    original = deepcopy(metadata)
    assert report._word_download_filename(metadata) == expected
    assert metadata == original
    assert not re.search(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', expected)


@pytest.fixture(scope="module")
def projects():
    return integrated_projects.__wrapped__()


def context(state):
    with patch.object(report.st, "session_state", state):
        return report.build_master_context()


def checkpoint(state):
    return restore_project(save_project(SimpleNamespace(session_state=state)))


def no_document(state):
    assert not any(key in state for key in (
        "_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature"))


def blocked(app):
    CASE.phase(app, "phase10")
    assert next(b for b in app.button if b.label == "Build Word Document").disabled
    no_document(app.session_state)


def advisory_build(app):
    # Only valid, revalidated sources may take this advisory path; blocked() stays strict.
    CASE.phase(app, "phase10")
    no_document(app.session_state)
    assert ps.prepare_calculations(app.session_state.to_dict()) == []
    assert not phase9.result_is_current(app.session_state)
    assert eng.compute_phase_status(app.session_state)["phase9"]["level"] == "warning"
    assert app.button(key="_rescue_phase9")
    assert not next(b for b in app.button if b.label == "Build Word Document").disabled
    with patch.object(phase9, "execute", side_effect=AssertionError("implicit Centralizer execution")):
        data = build(app)
    doc, ctx = assert_document(data, app.session_state.to_dict())
    assert_advisory_payload(ctx)
    assert_advisory_section(doc)
    assert not phase9.result_is_current(app.session_state)
    assert app.session_state["_compiled_doc_signature"] == report.document_signature(ctx, report.TEMPLATE_PATH)
    return data


def review_main(app, sync=False):
    CASE.phase(app, "phase7")
    if sync:
        next(b for b in app.button if b.key.startswith("_sync_btn_main_")).click().run()
        assert not app.session_state["lab_qc_params"]["Main"]["reviewed"]
    button = next(b for b in app.button if b.key.startswith("_confirm_lab_btn_main_"))
    assert not button.disabled
    button.click().run()
    CASE.healthy(app)
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "ok"


def rebuild(app):
    CASE.phase(app, "phase10")  # Run the real rebuild against Streamlit's proxy.
    assert ps.prepare_calculations(app.session_state.to_dict()) == []
    if not phase9.result_is_current(app.session_state):
        execute_centralizer(app.session_state, physics="dynamic")
    return build(app)


def semantics(data):
    doc = Document(BytesIO(data))
    return ([p.text for p in doc.paragraphs],
            [[[c.text for c in row.cells] for row in table.rows] for table in doc.tables],
            [node.get("descr") for node in doc.element.body.iter(qn("wp:docPr"))])


def media_signatures(data):
    with ZipFile(BytesIO(data)) as archive:
        return {hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                if name.startswith("word/media/")}


def sequence_table(doc):
    matches = [t for t in doc.tables if t.rows[0].cells[0].text.strip() == "Fluids"]
    assert len(matches) == 1
    table = matches[0]
    body = list(doc.element.body)
    headings = {p.text.strip(): body.index(p._p) for p in doc.paragraphs}
    assert headings["IV. Fluids Sequence"] < body.index(table._tbl) < headings["V. Cementing Program"]
    return table


def expected_word_fluid_cell(raw, decimals, *, rate=False):
    """Independent Decimal display oracle for already-admitted fixture components."""
    from decimal import Decimal
    pieces = re.split(r'([-/])', eng.normalize_digits(raw).strip())
    values = []
    for token in pieces[::2]:
        number = Decimal(token.strip())
        precision = max(decimals, -number.as_tuple().exponent)
        text = format(number, f'.{precision}f')
        if rate:
            text = text.rstrip('0').rstrip('.')
            if '.' not in text: text += '.0'
        values.append(('+' if token.strip().startswith('+') else '') + text)
    result = values[0]
    for delimiter, value in zip(pieces[1::2], values[1:]):
        result += ('–' if delimiter == '-' else '/') + value
    return result


def assert_document(data, state):
    doc = Document(BytesIO(data))
    text = "\n".join(node.text or "" for node in doc.element.body.iter(qn("w:t")))
    with ZipFile(BytesIO(data)) as archive:
        for name in archive.namelist():
            if name.startswith("word/") and name.endswith(".xml"):
                xml = archive.read(name).decode()
                assert "{{" not in xml and "{%" not in xml, name
    for heading in ("II. Well Data Summary", "III. Geothermal Temperature Profile",
                    "IV. Fluids Sequence", "V. Cementing Program",
                    "IX. Centralizer Placement Recommendation"):
        assert [p.text.strip() for p in doc.paragraphs].count(heading) == 1
    rows = [[c.text.strip() for c in row.cells] for row in sequence_table(doc).rows]
    names = [r[0] for r in rows if r[0] in db.HYDRAULIC_EXECUTION_ORDER]
    active = state["fluids_config"]["active"]
    assert names == [n for n in db.HYDRAULIC_EXECUTION_ORDER if n in active]
    assert len(names) == len(set(names))
    ctx = context(state)
    for source in ctx["fluids_train"]:
        row = next(r for r in rows if r[0] == source["name"])
        assert row[2:5] == [expected_word_fluid_cell(source["density"], 1),
                            f'{source["volume"]:.1f}', expected_word_fluid_cell(source["pump_rate"], 1, rate=True)]
    actual_steps = [p.text.strip() for p in doc.paragraphs if re.match(r"^\d+\. ", p.text.strip())]
    steps = numbered_steps(unescape(ctx["procedure_text"]))
    assert actual_steps == [f"{number}. {body}" for number, body in steps]
    assert [n for n, _ in steps] == list(range(1, len(steps) + 1))
    notes = [p.text.strip() for p in doc.paragraphs if re.match(r"^NOTE \d+:", p.text.strip())]
    assert notes == [unescape(note) for note in ctx["all_notes"]]
    if "Diesel" in active:
        source = state["fluid_data"]["Diesel"]
        sentence = f'Pump {source["volume"]:.1f} bbl Diesel as pre flush.({source["density"]} pcf)'
        assert [body for _, body in steps].count(sentence) == 1
        assert not any("Diesel" in note for note in notes)
    else:
        assert "Diesel" not in text
    hardware = next(t for t in doc.tables if t.rows[0].cells[0].text.strip() == "Tubular and Casing Hardware")
    hardware_text = "\n".join(c.text for r in hardware.rows for c in r.cells)
    for row in state["hardware_table"].to_dict("records"):
        assert row["Description"] in hardware_text
        assert str(row["MD (m)"]) in hardware_text
    return doc, ctx


@pytest.mark.parametrize("job", JOBS)
def test_actual_word_structure_and_sequence_for_eight_job_families(projects, job):
    state = projects(job)
    doc, ctx = assert_document(state["_compiled_doc_bytes"], state)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert ctx["job_type"] == job
    if job.startswith("LNR "):
        size = job[len("LNR "):-1]
        assert f"running {size} in Liner" in text
        assert ("raised and lowered with a 7 in liner" in text) == (job == 'LNR 7"')
        pressure = 100 if job == 'LNR 7"' else 150
        assert f'hold {pressure} psi pressure' in text
    if job in ("CMT PLUG", "CMT SQUEEZE"):
        assert not ctx["has_centralizer"]
        assert not pumping.prepare_pumping_simulation(state)["applicable"]


@pytest.mark.parametrize("job", [CSG, LNR, "CMT PLUG"])
def test_repeated_real_build_and_checkpoint_are_semantically_idempotent(projects, job):
    app = CASE.app(projects(job))
    before = save_project(app)
    signature = app.session_state["_compiled_doc_signature"]
    first = build(app)
    second = build(app)
    assert semantics(first) == semantics(second)
    assert app.session_state["_compiled_doc_signature"] == signature
    assert save_project(app) == before
    restored = restore_project(before)
    no_document(restored.session_state)
    third = rebuild(restored)
    assert semantics(third) == semantics(second)
    assert save_project(restored) == before


@pytest.mark.parametrize("change", ["hardware", "volume", "rate", "density", "Diesel rheology", "Formation"])
def test_source_edit_navigation_gate_and_new_actual_docx(projects, change):
    app = CASE.app(projects())
    old_signature = app.session_state["_compiled_doc_signature"]
    old_bytes = app.session_state["_compiled_doc_bytes"]
    state = app.session_state
    if change == "hardware":
        state["hardware_table"].loc[state["hardware_table"]["Description"] == "Casing", "ID (in)"] = 8.4
    elif change in ("volume", "rate", "density"):
        CASE.phase(app, "phase4")
        if change == "volume":
            app.number_input(key="vol_Main").set_value(51.)
        else:
            app.text_input(key=("rate_Main" if change == "rate" else "den_Main")).set_value("5" if change == "rate" else "120")
    elif change == "Diesel rheology":
        CASE.phase(app, "phase7")
        next(w for w in app.text_input if w.key.startswith("_rheo_diesel_bhct_down_300_")).set_value("169")
    else:
        state[chart.PORE_FIELD] = state["well_data"][chart.PORE_FIELD] = 71.
    CASE.phase(app, "phase1")
    CASE.phase(app, "phase10")
    no_document(state)
    if change in ("hardware", "volume", "density", "Diesel rheology"):
        assert not phase9.result_is_current(state)
        # Only the independent Main lab review (density) still blocks here.
        assert next(b for b in app.button if b.label == "Build Word Document").disabled == (change == "density")
    else:
        assert phase9.result_is_current(state)
    if change == "density":
        review_main(app, sync=True)
    data = rebuild(app)
    assert app.session_state["_compiled_doc_signature"] != old_signature
    assert semantics(data) != semantics(old_bytes) or media_signatures(data) != media_signatures(old_bytes)
    assert_document(data, app.session_state.to_dict())


def test_report_override_clear_restore_and_engineering_change_remain_separate(projects):
    app = CASE.app(projects())
    baseline = signatures(app.session_state)
    source = app.session_state["cement_params"]["Main"]
    source.update(top_mode="Depth (m MD)", top_depth=2100., report_bottom_depth=2900.)
    overridden = build(app)
    assert signatures(app.session_state) == baseline
    doc, ctx = assert_document(overridden, app.session_state.to_dict())
    assert ctx["slurries"][0]["top"] == "2100.0 m"
    assert ctx["slurries"][0]["bottom"] == "2900.0 m MD"
    assert "2100.0 m" in "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    app = checkpoint(app.session_state.to_dict())
    assert app.session_state["cement_params"]["Main"]["top_depth"] == 2100.
    assert semantics(rebuild(app)) == semantics(overridden)
    # Explicit report overrides remain intentional even as engineering changes.
    app.session_state["fluids_config"]["params"]["Main"]["volume"] = 51.
    updated = advisory_build(app)
    assert app.session_state["_compiled_doc_signature"] != projects()["_compiled_doc_signature"]
    assert semantics(updated) != semantics(overridden)
    app.session_state["cement_params"]["Main"].update(top_mode="Not entered", top_depth=None, report_bottom_depth=None)
    data = build(app)
    _, ctx = assert_document(data, app.session_state.to_dict())
    interval = next(r for r in chart.resolve_cement_placement(app.session_state) if r["fluid"] == "Main")
    assert ctx["slurries"][0]["top"] == ("surface" if interval["top_md"] == 0 else f'{interval["top_md"]:.1f} m')
    assert ctx["slurries"][0]["bottom"] == f'{interval["bottom_md"]:.1f} m MD'


@pytest.mark.parametrize("change", ["rheology", "thickening", "compressive", "lab mass"])
def test_measured_lab_edit_saved_before_review_blocks_then_exports_current_values(projects, change):
    state = projects()
    qc = state["lab_qc_params"]["Main"]
    if change == "rheology":
        qc["rheology"]["bhct_down"]["readings"]["300"] = "169"
    elif change == "thickening":
        qc["thickening_time"] = "03:45"
    elif change == "compressive":
        qc["compressive"]["crush"]["force_1"] = 450.
    else:
        grid = state["lab_grid_dfs"]["Main"]
        grid.at[0, "Mass"] = str(float(grid.at[0, "Mass"]) + 1.)
    assert qc["review_signature"] != eng.lab_review_signature(qc, state["lab_grid_dfs"]["Main"])
    app = checkpoint(state)
    blocked(app)
    review_main(app)
    data = rebuild(app)
    doc, ctx = assert_document(data, app.session_state.to_dict())
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "ok"
    assert semantics(data) != semantics(projects()["_compiled_doc_bytes"])
    assert ctx["slurries"][0]["lab"]["grid"] == app.session_state["lab_grid_dfs"]["Main"].to_dict("records")


@pytest.mark.parametrize("density,expected", [(None, 1.50), (1.47, 1.47)])
def test_sodium_edit_checkpoint_sync_resets_review_and_word_uses_current_additive(projects, density, expected):
    state = projects()
    old_mass = state["lab_grid_dfs"]["Main"].loc[lambda d: d.Material == "Sodium Silicate", "Mass"].iloc[0]
    row = state["cement_additives_dfs"]["Main"]
    row.at[0, "User Input"] = .75
    row.at[0, "Density"] = density
    app = checkpoint(state)
    blocked(app)
    CASE.phase(app, "phase5")
    assert app.session_state["cement_additives_dfs"]["Main"].at[0, "Density"] == expected
    CASE.phase(app, "phase7")
    next(b for b in app.button if b.key.startswith("_sync_btn_main_")).click().run()
    assert not app.session_state["lab_qc_params"]["Main"]["reviewed"]
    blocked(app)
    review_main(app)
    data = rebuild(app)
    doc, ctx = assert_document(data, app.session_state.to_dict())
    slurry = ctx["slurries"][0]
    assert "Sodium Silicate" not in [r["Name"] for r in slurry["blends"]]
    lab = next(r for r in slurry["lab_additives"] if r["Code"] == "Sodium Silicate")
    assert lab["Mass"] != old_mass
    rows = [" | ".join(c.text for c in r.cells) for t in doc.tables for r in t.rows]
    sodium = [r for r in rows if "Sodium Silicate" in r]
    assert len(sodium) == 2 and all("Liquid Extender" in r for r in sodium)
    assert any("0.75 gal/sk" in r for r in sodium)
    assert any(str(lab["Mass"]) in r and "gal/sk" in r for r in sodium)
    assert "Sodium Silicate" not in [r["name"] for r in ctx["fluids_train"]]


@pytest.mark.parametrize("invalid", ["target", "geometry", "density", "lab", "Formation"])
def test_export_invalid_valid_invalid_cannot_resurrect_old_docx(projects, invalid):
    app = CASE.app(projects())
    state = app.session_state
    original = deepcopy(state.to_dict())
    def corrupt():
        if invalid == "target":
            state["placement_config"]["target_row"] = "missing-target"
        elif invalid == "geometry":
            state["hardware_table"].loc[state["hardware_table"]["Description"] == "Casing", "ID (in)"] = 10.
        elif invalid == "density":
            state["fluids_config"]["params"]["Diesel"]["density"] = ""
        elif invalid == "lab":
            state["lab_qc_params"]["Main"]["rheology"]["bhct_down"]["selected"] = False
        else:
            domain = chart.current_open_hole_domain(state)
            state["formation_pressure_config"] = {"mode": "advanced", "profile": [
                {"md_m": domain["top_md"], "pore_psi": None, "frac_psi": None},
                {"md_m": domain["bottom_md"], "pore_psi": 4000., "frac_psi": 10000.}]}
    corrupt()
    blocked(app)
    for key in ("placement_config", "hardware_table", "fluids_config", "lab_qc_params", "formation_pressure_config"):
        if key in original:
            state[key] = deepcopy(original[key])
        elif key in state:
            del state[key]
    data = rebuild(app)
    assert_document(data, state.to_dict())
    corrupt()
    blocked(app)


@pytest.mark.parametrize("diesel,preflush,mud", [(True, False, "OBM"), (False, True, "OBM"), (False, False, "WBM")])
def test_independent_diesel_preflush_selection_never_leaks_inactive_drafts(projects, diesel, preflush, mud):
    state = projects()
    active = state["fluids_config"]["active"]
    if not diesel:
        active.remove("Diesel")
    if not preflush:
        active.remove("Pre Flush")
    state["mud_type"] = state["well_data"]["mud_type"] = mud
    app = checkpoint(state)
    data = rebuild(app)
    doc, ctx = assert_document(data, app.session_state.to_dict())
    assert ctx["has_preflush"] == preflush
    assert "Diesel" in app.session_state["lab_qc_params"]  # Preserved draft is not report authority.
    assert ("Diesel" in ctx["procedure_text"]) == diesel
    if not preflush:
        pumps = [body for _, body in numbered_steps(ctx["procedure_text"]) if body.startswith("Pump ")]
        assert all("preflush" not in line and ("pre flush" not in line or "Diesel" in line) for line in pumps)
    if diesel and preflush:
        names = [r["name"] for r in ctx["fluids_train"]]
        assert names.index("Diesel") + 1 == names.index("Pre Flush")


def test_manual_report_edits_xml_escape_review_and_regeneration_preserve_current_sources(projects):
    app = CASE.app(projects())
    CASE.phase(app, "phase10")
    summary = app.session_state["exec_summary_text"] + "\nOwner review: A & B < C > D."
    procedure = app.session_state["procedure_text"] + "\nOwner instruction: A & B < C > D."
    next(w for w in app.text_area if w.key.startswith("_exec_summary_editor_area_")).set_value(summary).run()
    next(w for w in app.text_area if w.key.startswith("_proc_editor_area_")).set_value(procedure).run()
    first = build(app)
    assert "Owner review: A & B < C > D." in "\n".join(semantics(first)[0])
    CASE.phase(app, "phase4")
    app.number_input(key="vol_Diesel").set_value(24.)
    CASE.phase(app, "phase1")
    blocked(app)
    assert app.session_state["exec_summary_text"] == summary
    assert app.session_state["procedure_text"] == procedure
    with patch.object(report.st, "session_state", app.session_state.to_dict()):
        specs = report.synchronize_report_texts()
    assert not specs["exec_summary_text"]["pending"]
    assert specs["procedure_text"]["pending"]
    next(b for b in app.button if b.key == "_regenerate_procedure_text").click().run()
    assert app.session_state["procedure_text"] != procedure
    assert app.session_state["report_text_state"]["procedure_text"]["history"][-1] == procedure
    current = rebuild(app)
    assert_document(current, app.session_state.to_dict())
    assert app.session_state["exec_summary_text"] == summary
    next(b for b in app.button if b.key == "_restore_procedure_text").click().run()
    blocked(app)
    assert app.session_state["procedure_text"] == procedure
    # The existing Keep action is the owner's explicit approval of manual text.
    next(b for b in app.button if b.key == "_keep_procedure_text").click().run()
    reviewed = build(app)
    assert "Owner instruction: A & B < C > D." in semantics(reviewed)[0]
    assert app.session_state["exec_summary_text"] == summary


def test_unused_diesel_surface_source_does_not_drift_current_word_or_engineering(projects):
    app = CASE.app(projects())
    old_doc = app.session_state["_compiled_doc_bytes"]
    old_signature = app.session_state["_compiled_doc_signature"]
    physics = signatures(app.session_state)
    app.session_state["lab_qc_params"]["Diesel"]["rheology"]["surface_down"]["readings"]["300"] = "169"
    CASE.phase(app, "phase1")
    CASE.phase(app, "phase10")
    assert signatures(app.session_state) == physics
    assert app.session_state["_compiled_doc_signature"] == old_signature
    assert app.session_state["_compiled_doc_bytes"] == old_doc
    assert semantics(build(app)) == semantics(old_doc)


@pytest.fixture(scope="module")
def multi_slurry(projects):
    app = CASE.app(projects())
    CASE.phase(app, "phase4")
    for name in ("Scavenger", "Lead", "Tail"):
        app.checkbox(key="chk_fluid_" + name).check().run()
        app.number_input(key="vol_" + name).set_value(50.).run()
        app.text_input(key="den_" + name).set_value("118").run()
        app.text_input(key="rate_" + name).set_value("4").run()
        app.session_state["cement_params"][name] = deepcopy(app.session_state["cement_params"]["Main"])
        app.session_state["lab_qc_params"][name] = deepcopy(app.session_state["lab_qc_params"]["Main"])
    CASE.phase(app, "phase5")
    CASE.phase(app, "phase7")
    for name in ("Scavenger", "Lead", "Tail"):
        sync = next((b for b in app.button if (b.key or "").startswith(f"_sync_btn_{name.lower()}_")), None)
        assert sync is not None, [error.value for error in app.error]
        sync.click().run()
        next(b for b in app.button if (b.key or "").startswith(f"_confirm_lab_btn_{name.lower()}_")).click().run()
    rebuild(app)
    return app.session_state.to_dict()


def test_multislurry_scavenger_and_legacy_spacers_render_once_in_their_own_orders(multi_slurry):
    state = deepcopy(multi_slurry)
    doc, ctx = assert_document(state["_compiled_doc_bytes"], state)
    assert [r["name"] for r in ctx["fluids_train"]] == ["Diesel", "Pre Flush", "Spacer Ahead", "Scavenger",
                                                     "Main", "Lead", "Tail", "Spacer Behind", "Displacement Fluid"]
    assert ctx["has_scavenger"]
    assert [r["name"] for r in ctx["slurries"]] == ["Lead", "Main", "Tail"]
    actual = [p.text for p in doc.paragraphs if p.text.endswith(" Cement Slurry Results")]
    assert actual == [f"{name} Cement Slurry Results" for name in ("Lead", "Main", "Tail")]
    steps = [body for _, body in numbered_steps(unescape(ctx["procedure_text"]))]
    selected = [line for line in steps if line.startswith(("Pump ", "Mix and pump "))]
    expected_names = [r["name"] for r in ctx["fluids_train"] if r["name"] not in ("Pre Flush", "Displacement Fluid")]
    indices = [next(i for i, line in enumerate(selected) if name in line) for name in expected_names]
    assert indices == sorted(indices) and len(indices) == len(set(indices))


def test_inactive_sodium_archive_survives_restore_without_ghost_word_content(multi_slurry):
    app = CASE.app(deepcopy(multi_slurry))
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_Main").uncheck().run()
    app = checkpoint(app.session_state.to_dict())
    archived = app.session_state["inactive_slurry_drafts"]["Main"]["cement_additives_dfs"]
    assert archived.at[0, "Name"] == "Sodium Silicate"
    data = rebuild(app)
    doc, ctx = assert_document(data, app.session_state.to_dict())
    assert "Main" not in [r["name"] for r in ctx["slurries"]]
    assert "Sodium Silicate" not in "\n".join(node.text or "" for node in doc.element.body.iter(qn("w:t")))
    assert app.session_state["inactive_slurry_drafts"]["Main"]["cement_additives_dfs"].equals(archived)


@pytest.mark.parametrize("change", ["hardware", "placement", "Diesel", "Sodium", "Phase VII"])
def test_checkpoint_after_edit_before_any_rebuild_exports_new_canonical_truth(projects, change):
    state = projects()
    if change == "hardware":
        state["hardware_table"].loc[state["hardware_table"]["Description"] == "Casing", "MD (m)"] = "2900"
        select_target(state)
    elif change == "placement":
        state["cement_params"]["Main"].update(top_mode="Depth (m MD)", top_depth=2100., report_bottom_depth=2900.)
    elif change == "Diesel":
        state["fluids_config"]["params"]["Diesel"].update(density="54", volume=24.)
        state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]["readings"]["300"] = "169"
    elif change == "Sodium":
        state["cement_additives_dfs"]["Main"].at[0, "User Input"] = .75
    else:
        state["lab_qc_params"]["Main"]["api_fl"] = .5
    app = checkpoint(state)
    if change in ("Sodium", "Phase VII"):
        blocked(app)  # Independent lab review remains mandatory after restore.
        review_main(app, sync=change == "Sodium")
        data = rebuild(app)
    else:
        data = advisory_build(app)
        assert app.session_state["_compiled_doc_signature"] != projects()["_compiled_doc_signature"]
    doc, ctx = assert_document(data, app.session_state.to_dict())
    if change == "hardware":
        assert any(r["Description"] == "Casing" and r["MD (m)"] == "2900.0" for r in ctx["hardware"])
        frame = app.session_state["hardware_table"]
        assert frame.loc[frame.Description == "Casing", "MD (m)"].tolist() == ["2900"]
        hardware_table = next(t for t in doc.tables if t.rows[0].cells[0].text.strip() == "Tubular and Casing Hardware")
        assert any("Casing" in [c.text.strip() for c in row.cells] and
                   "2900.0" in [c.text.strip() for c in row.cells] for row in hardware_table.rows)
    elif change == "placement":
        assert ctx["slurries"][0]["top"] == "2100.0 m"
        assert ctx["slurries"][0]["bottom"] == "2900.0 m MD"
    elif change == "Diesel":
        assert "Pump 24.0 bbl Diesel as pre flush.(54 pcf)" in ctx["procedure_text"]
        assert app.session_state["lab_qc_params"]["Diesel"]["rheology"]["bhct_down"]["readings"]["300"] == "169"
    elif change == "Sodium":
        assert ctx["slurries"][0]["additives"][0]["(lbs or gal)/sk"] == "0.75 gal/sk"
    else:
        assert ctx["slurries"][0]["lab"]["api_fl_collected"] == .5
        assert ctx["slurries"][0]["lab"]["fluid_loss"] == 1.


def test_advanced_formation_and_incomplete_endpoint_cycle_replaces_real_word_chart(projects):
    app = CASE.app(projects())
    state = app.session_state
    domain = chart.current_open_hole_domain(state)
    state["formation_pressure_config"] = {"mode": "advanced", "profile": [
        {"md_m": domain["top_md"], "pore_psi": 2000., "frac_psi": 6000.},
        {"md_m": domain["bottom_md"], "pore_psi": 4000., "frac_psi": 10000.}]}
    assert phase9.result_is_current(state)
    first = build(app)
    assert_document(first, state.to_dict())
    state["hardware_table"].loc[state["hardware_table"]["Description"] == "Previous Casing", "MD (m)"] = "1600"
    draft = state.to_dict()
    ps.reconcile_formation_profile(draft)
    state["formation_pressure_config"] = draft["formation_pressure_config"]
    assert state["formation_pressure_config"]["profile"][0]["pore_psi"] is None
    blocked(app)
    app = checkpoint(state.to_dict())
    blocked(app)
    app.session_state["formation_pressure_config"]["profile"][0].update(pore_psi=2200., frac_psi=6500.)
    second = rebuild(app)
    doc, ctx = assert_document(second, app.session_state.to_dict())
    formation = ctx["cement_chart_report"]["model"]["formation_pressure"]
    assert formation["domain"]["top_md"] == 1600.
    assert formation["mode"] == "advanced"
    assert app.session_state["formation_pressure_config"]["profile"][0]["pore_psi"] == 2200.
    assert app.session_state["_compiled_doc_signature"] != projects()["_compiled_doc_signature"]


@pytest.mark.parametrize("dataset,field,value", [
    ("surface_down", "300", "169"), ("bhct_up", "300", "169"),
    ("surface_down", "gel_10_min", "14"), ("bhct_up", "selected", False),
])
def test_unused_diesel_widget_does_not_retire_a_current_real_document(projects, dataset, field, value):
    state = projects()
    if dataset == "bhct_up":
        state["lab_qc_params"]["Diesel"]["rheology"][dataset] = deepcopy(
            state["lab_qc_params"]["Diesel"]["rheology"]["surface_down"])
    app = CASE.app(state)
    current_bytes = app.session_state["_compiled_doc_bytes"]
    current_signature = app.session_state["_compiled_doc_signature"]
    before = signatures(app.session_state)
    CASE.phase(app, "phase7")
    widgets = app.checkbox if field == "selected" else app.text_input
    next(w for w in widgets if (w.key or "").startswith(f"_rheo_diesel_{dataset}_{field}_")).set_value(value).run()
    row = app.session_state["lab_qc_params"]["Diesel"]["rheology"][dataset]
    assert (row["readings"]["300"] if field == "300" else row[field]) == value
    assert eng.compute_phase_status(app.session_state)["phase7"]["level"] == "ok"
    assert signatures(app.session_state) == before
    CASE.phase(app, "phase1")
    CASE.phase(app, "phase10")
    ctx = context(app.session_state.to_dict())
    assert report.document_signature(ctx, str(report.TEMPLATE_PATH)) == current_signature
    assert "_compiled_doc_bytes" in app.session_state, "Unused Diesel dataset edit retired a current real DOCX"
    assert app.session_state["_compiled_doc_signature"] == current_signature
    assert app.session_state["_compiled_doc_bytes"] == current_bytes


def test_invalid_unused_diesel_dataset_still_blocks_recovered_export(projects):
    app = CASE.app(projects())
    for invalid in (True, False, True):
        CASE.phase(app, "phase7")
        next(w for w in app.text_input if w.key.startswith("_rheo_diesel_surface_down_300_")).set_value("bad" if invalid else "168").run()
        if invalid:
            blocked(app)
        else:
            assert phase9.result_is_current(app.session_state)
            assert_document(build(app), app.session_state.to_dict())


def test_reported_cement_surface_widget_still_retires_word_and_requires_review(projects):
    app = CASE.app(projects())
    CASE.phase(app, "phase7")
    next(w for w in app.text_input if w.key.startswith("_rheo_main_surface_down_300_")).set_value("169").run()
    no_document(app.session_state)
    blocked(app)
    assert phase9.result_is_current(app.session_state)
    review_main(app)
    data = build(app)
    _, ctx = assert_document(data, app.session_state.to_dict())
    assert ctx["slurries"][0]["lab"]["rheology"]["surface_down"]["readings"]["300"] == 169.


def test_consumed_diesel_bhct_gel_retires_word_without_false_centralizer_staleness(projects):
    app = CASE.app(projects())
    previous = pumping.source_signature(app.session_state)
    CASE.phase(app, "phase7")
    next(w for w in app.text_input if (w.key or "").startswith("_rheo_diesel_bhct_down_gel_10_min_")).set_value("14").run()
    no_document(app.session_state)
    assert phase9.result_is_current(app.session_state)
    assert pumping.source_signature(app.session_state) != previous
    data = build(app)
    assert_document(data, app.session_state.to_dict())


R16C_DATES = ("date","request_date","prepared_date","checked_date","approved_date","revision_date")


@pytest.fixture(scope="module")
def r16c_document_source():
    from datetime import date
    app=CASE.configured_app(CSG)
    CASE.phase(app,"phase1")
    for index,field in enumerate(R16C_DATES):
        key="_w_report_date" if field=="date" else "_w_"+field
        app.date_input(key=key).set_value(date(2026,10,3+index)).run()
    for label in ("Request Description","Prepared Phone"):
        next(w for w in app.text_input if w.label==label).set_value("2026-10-03").run()
    CASE.phase(app,"phase7")
    next(w for w in app.number_input if w.label=="Surface Sample Hours - Main").set_value(8.25).run()
    next(b for b in app.button if b.label=="Confirm measured lab results").click().run()
    CASE.phase(app,"phase10")
    return app.session_state.to_dict()


def r16c_date_paragraphs(doc):
    import re
    from lxml import etree
    from zipfile import ZipFile
    w14="{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
    with ZipFile(report.TEMPLATE_PATH) as source:
        root=etree.fromstring(source.read("word/document.xml"))
    result={}
    for field in R16C_DATES:
        matches=[p for p in root.iter(qn("w:p")) if re.search(r"{{\s*"+field+r"\s*}}",
            "".join(t.text or "" for t in p.iter(qn("w:t"))))]
        assert len(matches)==1
        identity=matches[0].get(w14)
        paragraphs=[p for p in doc.element.iter(qn("w:p")) if p.get(w14)==identity]
        assert len(paragraphs)==1
        result[field]="".join(t.text or "" for t in paragraphs[0].iter(qn("w:t")))
    return result


@pytest.mark.parametrize("restored",[False,True])
def test_r16c_real_word_dates_surface_note_restore_and_cache(r16c_document_source,restored,tmp_path):
    state=deepcopy(r16c_document_source)
    if restored:state=audit.round_trip(state)
    app=CASE.app(state)
    if restored:
        assert "_centralizer_result" not in state
        pending = context(app.session_state.to_dict())["centralizer_report"]
        assert pending["current"] is False and pending["view"] is None
    execute_centralizer(app.session_state)  # Real Phase IX rebuild, never a restored private receipt.
    CASE.phase(app,"phase10")
    ctx=context(app.session_state.to_dict())
    expected_iso={field:f"2026-10-{3+i:02d}" for i,field in enumerate(R16C_DATES)}
    assert {field:ctx[field] for field in R16C_DATES}==expected_iso
    raw=deepcopy(app.session_state["doc_control"])
    qc=deepcopy(app.session_state["lab_qc_params"])
    before=signatures(app.session_state)
    CASE.export(app)
    data=app.session_state["_compiled_doc_bytes"]
    (tmp_path/"report.docx").write_bytes(data)
    doc=Document(BytesIO(data))
    dates=r16c_date_paragraphs(doc)
    paragraphs=["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in doc.element.iter(qn("w:p"))]
    text="\n".join(paragraphs)
    # Controls are checked before the intended baseline RED assertions.
    assert app.session_state["doc_control"]==raw
    assert app.session_state["lab_qc_params"]==qc
    assert signatures(app.session_state)==before
    assert raw["date"]=="2026-10-03" and qc["Main"]["surface_hardened_hours"]==8.25
    assert "2026-10-03" in text  # Actual phone/description bindings are not dates.
    assert "2026-10-03" not in app.session_state["_compiled_doc_filename"]
    assert app.session_state["_compiled_doc_filename"].startswith("Cementing Program - ")
    (tmp_path/"observed-fields.json").write_text(__import__("json").dumps({
        "dates":dates,"surface_notes":[p for p in paragraphs if "Hours" in p and "NOTE " in p],
        "raw_dates":expected_iso,"raw_hours":qc["Main"]["surface_hardened_hours"]},indent=2))
    errors=[]
    for index,field in enumerate(R16C_DATES):
        expected=f"2026/10/{3+index:02d}"
        if expected not in dates[field] or expected_iso[field] in dates[field]:errors.append((field,dates[field],expected))
    expected_note="NOTE 10: The Surface Sample Exhibited Hardening After 8.25 Hours"
    if text.count(expected_note)!=1:errors.append(("surface note",[p for p in paragraphs if "Hard" in p and "NOTE " in p],expected_note))
    assert not errors,errors
    notes=[p.strip() for p in paragraphs if p.strip().startswith("NOTE ")]
    assert notes==[unescape(n) for n in ctx["all_notes"]]
    signature=app.session_state["_compiled_doc_signature"]
    CASE.phase(app,"phase10")
    assert app.session_state["_compiled_doc_signature"]==signature
    assert report.document_signature(context(app.session_state.to_dict()),report.TEMPLATE_PATH)==signature
    # An actual baseline signature is obsolete; review/source signatures are untouched.
    import ast,subprocess
    source=subprocess.check_output(["git","show","a582f7593efedda2e69d27eb71f3d43e56254019:phase_10_procedure.py"])
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=="document_signature")
    namespace=dict(report.__dict__)
    exec(compile(ast.Module(body=[node],type_ignores=[]),"previous_Word_signature","exec"),namespace)
    previous=namespace["document_signature"](ctx,report.TEMPLATE_PATH)
    assert previous!=signature
    app.session_state["_compiled_doc_signature"]=previous
    CASE.phase(app,"phase10")
    no_document(app.session_state)
    assert app.session_state["doc_control"]==raw and app.session_state["lab_qc_params"]==qc


@pytest.mark.parametrize("value,expected", [
    ("2026-10-03", "2026/10/03"), ("2024-02-29", "2024/02/29"),
    ("0001-01-01", "0001/01/01"), (None, None), ("", ""), ("-", "-"),
    ("1405/07/11", "1405/07/11"), ("2026/10/03", "2026/10/03"),
    ("2026-02-29", "2026-02-29"), ("2026-13-03", "2026-13-03"),
    ("2026-10", "2026-10"), ("20261003", "20261003"),
    (" 2026-10-03 ", " 2026-10-03 "), ("2026-10-03T12:34:56", "2026-10-03T12:34:56"),
    ("Phone: 2026-10-03", "Phone: 2026-10-03"), (False, False),
    ("2026-00-03", "2026-00-03"), ("0000-01-01", "0000-01-01"),
])
def test_r16c_terminal_dates_are_explicit_valid_calendar_fields_only(value, expected):
    original = {key: value for key in R16C_DATES}
    original.update(phone="2026-10-03", description="2026-10-03", generated="2026-10-03",
                    filename="Cementing_Program_2026-10-03.docx", doc_control={"date": value})
    snapshot = deepcopy(original)
    rendered = report._word_quantity_context(original)
    assert {key: rendered[key] for key in R16C_DATES} == dict.fromkeys(R16C_DATES, expected)
    assert original == snapshot
    for key in ("phone", "description", "generated", "filename", "doc_control"):
        assert rendered[key] == snapshot[key]
    assert not any(key in report._word_quantity_context({}) for key in R16C_DATES)


@pytest.mark.parametrize("kind", ["date", "datetime"])
def test_r16c_native_calendar_objects_render_in_actual_template(r16c_document_source, kind, tmp_path):
    from datetime import date, datetime, timezone, timedelta
    ctx = context(deepcopy(r16c_document_source))
    values = {key: date(2026, 10, 3+i) if kind == "date" else
              datetime(2026, 10, 3+i, 0, 15, tzinfo=timezone(timedelta(hours=3)))
              for i, key in enumerate(R16C_DATES)}
    ctx.update(values)
    doc = report.DocxTemplate(report.TEMPLATE_PATH)
    doc.render(report._word_quantity_context(ctx))
    target = tmp_path / (kind + ".docx")
    doc.save(target)
    actual = r16c_date_paragraphs(Document(target))
    assert actual == {key: f"2026/10/{3+i:02d}" for i, key in enumerate(R16C_DATES)}
    assert {key: ctx[key] for key in R16C_DATES} == values
