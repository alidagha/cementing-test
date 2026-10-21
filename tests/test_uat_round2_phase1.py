"""Functional UAT Round 2: document descriptions, calendars and Word title."""
from copy import deepcopy
from datetime import date
from io import BytesIO
import hashlib
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import test_audit_regressions as audit
from docx import Document
import materials_db
import phase_10_procedure as report
from project_state import request_description_for_job

DATES = ("request_date", "prepared_date", "checked_date", "approved_date", "revision_date")
TEXT_LABELS = {"request_description": "Request Description",
               "revision_description": "Revision Description", "revision_no": "Revision No."}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"


class Round2Phase1UAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    healthy = audit.AuditRegressions.healthy
    phase = audit.AuditRegressions.phase
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export

    def descriptions(self, app, request, revision):
        for field, expected in (("request_description", request), ("revision_description", revision)):
            self.assertEqual(app.session_state[field], expected)
            self.assertEqual(app.session_state["doc_control"][field], expected)
            if app.radio(key="_app_mode_key").value == "phase1":
                self.assertEqual(next(w for w in app.text_input if w.label == TEXT_LABELS[field]).value, expected)

    def test_job_family_formatting_and_conservative_future_fallback(self):
        expected = {
            'CSG 30"': '30" CSG Cementing', 'CSG 24"': '24" CSG Cementing',
            'CSG 20"': '20" CSG Cementing', 'CSG 18 5/8"': '18 5/8" CSG Cementing',
            'CSG 13 3/8"': '13 3/8" CSG Cementing', 'CSG 9 5/8"': '9 5/8" CSG Cementing',
            'CSG 7"': '7" CSG Cementing', 'LNR 7"': '7" LNR Cementing',
            'LNR 5"': '5" LNR Cementing', 'LNR 4 1/2"': '4 1/2" LNR Cementing',
            'CMT PLUG': 'CMT PLUG Cementing', 'CMT SQUEEZE': 'CMT SQUEEZE Cementing',
            'TIE BACK LNR 7"': '7" TIE BACK LNR Cementing',
            'TIE BACK LNR 5"': '5" TIE BACK LNR Cementing',
        }
        self.assertEqual(list(expected), materials_db.JOB_TYPES)
        for job, description in expected.items():
            with self.subTest(job=job):
                self.assertEqual(request_description_for_job(job), description)
        for job in ('Future Job', 'CSG 42"'):
            with self.subTest(future=job):
                self.assertEqual(request_description_for_job(job), job + ' Cementing')

    def test_untouched_descriptions_follow_job_before_navigation(self):
        app = self.app()
        self.descriptions(app, '20" CSG Cementing', '20" CSG Cementing')
        self.assertFalse(any('unsaved changes' in w.value for w in app.warning))
        for job, expected in (('CSG 13 3/8"', '13 3/8" CSG Cementing'),
                              ('LNR 7"', '7" LNR Cementing'),
                              ('TIE BACK LNR 7"', '7" TIE BACK LNR Cementing'),
                              ('CMT PLUG', 'CMT PLUG Cementing'),
                              ('CMT SQUEEZE', 'CMT SQUEEZE Cementing')):
            with self.subTest(job=job):
                app.selectbox(key='_w_job_type').set_value(job)
                self.phase(app, 'phase2_3')
                self.descriptions(app, expected, expected)
                self.phase(app, 'phase1')
                self.descriptions(app, expected, expected)
                self.assertFalse(app.session_state['request_description_customized'])
                self.assertFalse(app.session_state['revision_description_customized'])

    def test_request_manual_first_edit_follows_to_untouched_revision(self):
        app = self.app()
        next(w for w in app.text_input if w.label == 'Request Description').set_value('Owner request')
        self.phase(app, 'phase2_3')
        self.descriptions(app, 'Owner request', 'Owner request')
        self.phase(app, 'phase1')
        self.descriptions(app, 'Owner request', 'Owner request')
        app.selectbox(key='_w_job_type').set_value('LNR 7"').run()
        self.healthy(app)
        self.descriptions(app, 'Owner request', 'Owner request')
        self.assertTrue(app.session_state['request_description_customized'])
        self.assertFalse(app.session_state['revision_description_customized'])

    def test_explicit_request_edit_not_inferred_from_its_text(self):
        # An intentional edit back to a suggestion, or to blank, is still manual.
        for text in ('', '20" CSG Cementing'):
            with self.subTest(text=text):
                app = self.app()
                next(w for w in app.text_input if w.label == 'Request Description').set_value('Interim text').run()
                next(w for w in app.text_input if w.label == 'Request Description').set_value(text).run()
                app.selectbox(key='_w_job_type').set_value('CMT PLUG').run()
                self.healthy(app)
                self.descriptions(app, text, text)
                self.assertTrue(app.session_state['request_description_customized'])

    def test_revision_manual_first_edit_is_independent(self):
        app = self.app()
        next(w for w in app.text_input if w.label == 'Revision Description').set_value('Independent revision')
        self.phase(app, 'phase2_3')
        self.descriptions(app, '20" CSG Cementing', 'Independent revision')
        self.phase(app, 'phase1')
        app.selectbox(key='_w_job_type').set_value('CMT PLUG').run()
        self.descriptions(app, 'CMT PLUG Cementing', 'Independent revision')
        next(w for w in app.text_input if w.label == 'Request Description').set_value('Changed request').run()
        self.descriptions(app, 'Changed request', 'Independent revision')
        self.assertTrue(app.session_state['revision_description_customized'])

    def test_current_json_preserves_all_customization_combinations(self):
        for request_custom in (False, True):
            for revision_custom in (False, True):
                with self.subTest(request=request_custom, revision=revision_custom):
                    app = self.app()
                    if request_custom:
                        next(w for w in app.text_input if w.label == 'Request Description').set_value('Current request').run()
                    if revision_custom:
                        next(w for w in app.text_input if w.label == 'Revision Description').set_value('Current revision').run()
                    self.phase(app, 'phase2_3')
                    saved = audit.round_trip(app.session_state.to_dict())
                    self.assertEqual(saved['request_description_customized'], request_custom)
                    self.assertEqual(saved['revision_description_customized'], revision_custom)
                    restored = self.app(saved)
                    request = 'Current request' if request_custom else '20" CSG Cementing'
                    revision = 'Current revision' if revision_custom else request
                    self.descriptions(restored, request, revision)
                    restored.selectbox(key='_w_job_type').set_value('CMT SQUEEZE').run()
                    request = 'Current request' if request_custom else 'CMT SQUEEZE Cementing'
                    revision = 'Current revision' if revision_custom else request
                    self.descriptions(restored, request, revision)
                    next(w for w in restored.text_input if w.label == 'Request Description').set_value('Restored edit').run()
                    self.descriptions(restored, 'Restored edit', 'Current revision' if revision_custom else 'Restored edit')

    def test_all_five_calendar_first_entries_commit_before_navigation(self):
        app = self.app()
        for index, field in enumerate(DATES):
            with self.subTest(field=field):
                self.assertIsNone(app.date_input(key='_w_' + field).value)
                selected = date(2026, 10, 5 + index)
                app.date_input(key='_w_' + field).set_value(selected)
                self.phase(app, 'phase2_3')
                self.assertEqual(app.session_state[field], selected.isoformat())
                self.assertEqual(app.session_state['doc_control'][field], selected.isoformat())
                self.phase(app, 'phase1')
                self.assertEqual(app.date_input(key='_w_' + field).value, selected)

    def test_current_json_restores_all_five_iso_calendar_dates(self):
        app = self.app()
        for index, field in enumerate(DATES):
            app.date_input(key='_w_' + field).set_value(date(2026, 10, 5 + index)).run()
        self.phase(app, 'phase2_3')
        saved = audit.round_trip(app.session_state.to_dict())
        restored = self.app(saved)
        for index, field in enumerate(DATES):
            with self.subTest(field=field):
                selected = date(2026, 10, 5 + index)
                self.assertEqual(saved[field], selected.isoformat())
                self.assertEqual(restored.date_input(key='_w_' + field).value, selected)
                self.assertEqual(restored.session_state['doc_control'][field], selected.isoformat())

    def test_customization_markers_require_booleans_at_json_boundary(self):
        for field in ('request_description_customized', 'revision_description_customized'):
            for invalid in ('false', 0, None, [], {}):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaisesRegex(ValueError, field + ' must be a boolean'):
                        audit.round_trip({'job_type': 'CMT PLUG', field: invalid})

    def test_current_descriptions_context_and_actual_word_for_five_workflows(self):
        for job in audit.BATCH1_JOBS:
            with self.subTest(job=job):
                app = self.configured_app(job)
                self.phase(app, 'phase1')
                for field, value in (('request_description', 'Operator request'),
                                     ('revision_description', 'Operator revision'), ('revision_no', '7')):
                    next(w for w in app.text_input if w.label == TEXT_LABELS[field]).set_value(value).run()
                restored = self.app(audit.round_trip(app.session_state.to_dict()))
                for phase in ('phase2_3', 'phase4', 'phase5', 'phase7'):
                    self.phase(restored, phase)
                self.export(restored)
                with patch.object(report.st, 'session_state', deepcopy(restored.session_state.to_dict())):
                    context = report.build_master_context()
                self.assertEqual(context['request_description'], 'Operator request')
                self.assertEqual(context['revision_description'], 'Operator revision')
                self.assertEqual(context['job_type'], job)
                self.assertEqual(context['revision_no'], '7')
                doc = Document(BytesIO(restored.session_state['_compiled_doc_bytes']))
                paragraphs = {p.get(W14 + 'paraId'): ''.join(t.text or '' for t in p.iter(W + 't'))
                              for p in doc.element.iter(W + 'p')}
                self.assertEqual(paragraphs['47C1ADEC'], '')
                self.assertEqual(paragraphs['70FBB566'], 'Operator request')
                self.assertEqual(paragraphs['2F3C4677'], 'Operator revision')
                self.assertEqual(paragraphs['355F3FFE'], job)
                self.assertEqual(paragraphs['40EF166E'], '7')
                text = '\n'.join(paragraphs.values())
                self.assertNotIn('Document Name and Version:', text)
                self.assertIn('Cementing Program', text)

    def test_template_change_preserves_all_structure_and_other_zip_parts(self):
        with ZipFile(audit.ROOT / 'master_template.docx') as z:
            root = ET.fromstring(z.read('word/document.xml'))
            # Round 6's three-table insertion is checked separately. Pin the
            # remaining structure to the approved A4 Spacer field/NOTE/lab layout.
            body = root.find(W + 'body')
            nodes = list(body)
            text = lambda node: ''.join(t.text or '' for t in node.iter(W + 't'))
            start = next(i for i, node in enumerate(nodes) if text(node) == '{%p if has_scavenger %}')
            end = next(i for i, node in enumerate(nodes) if i > start and text(node) == '{%p endif %}')
            inserted = nodes[start:end + 1]
            self.assertEqual(sum(node.tag == W + 'tbl' for node in inserted), 3)
            for node in inserted:
                body.remove(node)
            # Ignore text values only: retain every element, property and attribute,
            # including fonts, spacing, page settings and complete table structure.
            structure = [(e.tag, sorted(e.attrib.items()), None if e.tag == W + 't' else e.text, e.tail)
                         for e in root.iter()]
            self.assertEqual(hashlib.sha256(json.dumps(structure, ensure_ascii=False).encode()).hexdigest(),
                             '417ad56058e3028133b336007925102e3bd1f149178606e5a879190a8640d9df')
            parts = [(n, hashlib.sha256(z.read(n)).hexdigest()) for n in sorted(z.namelist())
                     if n != 'word/document.xml']
            self.assertEqual(hashlib.sha256(json.dumps(parts).encode()).hexdigest(),
                             'ddc72f1d3a17172292a248ca6797f333394bd0050fd5b4b0e4ad0a90dc9ec1c3')
            self.assertEqual({t: len(list(root.iter(W + t))) for t in ('tbl', 'tr', 'tc', 'sectPr')},
                             {'tbl': 24, 'tr': 163, 'tc': 662, 'sectPr': 1})
            paragraphs = {p.get(W14 + 'paraId'): ''.join(t.text or '' for t in p.iter(W + 't'))
                          for p in root.iter(W + 'p')}
            self.assertEqual(paragraphs['47C1ADEC'], '')
            self.assertEqual(paragraphs['355F3FFE'], '{{ job_type }}')
            self.assertEqual(paragraphs['40EF166E'], '{{ revision_no }}')

    def test_template_integrity_rejects_structure_parts_and_protected_text(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with ZipFile(audit.ROOT / 'master_template.docx') as archive:
            parts = [(info, archive.read(info.filename)) for info in archive.infolist()]
        for change in ('table_width', 'styles_part', 'job_placeholder'):
            with self.subTest(change=change), TemporaryDirectory(prefix='round2-template-') as folder:
                with ZipFile(Path(folder) / 'master_template.docx', 'w') as archive:
                    for info, original in parts:
                        data = original
                        if info.filename == 'word/document.xml' and change != 'styles_part':
                            root = ET.fromstring(data)
                            if change == 'table_width':
                                next(root.iter(W + 'tblW')).set(W + 'w', '1')
                            else:
                                paragraph = next(p for p in root.iter(W + 'p')
                                                 if p.get(W14 + 'paraId') == '355F3FFE')
                                next(paragraph.iter(W + 't')).text = 'Unapproved job placeholder'
                            data = ET.tostring(root)
                        elif info.filename == 'word/styles.xml' and change == 'styles_part':
                            data += b'<!-- unapproved change -->'
                        archive.writestr(info, data)
                with patch.object(audit, 'ROOT', Path(folder)), self.assertRaises(AssertionError):
                    self.test_template_change_preserves_all_structure_and_other_zip_parts()
