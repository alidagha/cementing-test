"""Round 3 Batch 4: Tail top initialization uses the existing placement target."""
from copy import deepcopy
from io import BytesIO
import unittest

from docx import Document
import test_audit_regressions as audit
from engineering_tools import compute_phase_status
from placement import hardware_choices, target_descriptions, slurry_intervals


class TailPlacementUAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy
    export = audit.AuditRegressions.export
    assert_export_blocked = audit.AuditRegressions.assert_export_blocked

    @classmethod
    def setUpClass(cls):
        case = audit.AuditRegressions()
        app = case.configured_app(audit.BATCH1_JOBS[0])
        cls.project = audit.round_trip(app.session_state.to_dict())
        cls.project['fluids_config']['active'] = ['Tail', 'Displacement Fluid']
        for field in ('cement_params', 'cement_additives_dfs', 'lab_qc_params'):
            cls.project[field] = {'Tail': deepcopy(cls.project[field]['Main'])}
        cls.project['fluids_config']['params']['Tail'] = deepcopy(cls.project['fluids_config']['params']['Main'])
        cls.project['cement_params']['Tail'].update(top_mode='Not entered', top_depth=None)
        cls.project['cement_params']['Tail'].pop('draft_top_depth', None)
        cls.project['lab_qc_params']['Tail']['reviewed'] = False
        cls.project['lab_qc_params']['Tail'].pop('review_signature', None)

    def mode(self, app, slurry='Tail'):
        return next(w for w in app.selectbox if w.label == f'Top of cement - {slurry}')

    def depth(self, app):
        return next(w for w in app.number_input if w.label == 'Top of cement depth (m MD) - Tail')

    def start(self, project=None):
        app = self.app(audit.round_trip(deepcopy(project or self.project)))
        self.phase(app, 'phase4')
        self.phase(app, 'phase5')
        return app

    def test_tail_options_and_both_target_sources_seed_2850(self):
        for source in ('manual', 'hardware'):
            with self.subTest(source=source):
                project = deepcopy(self.project)
                if source == 'hardware':
                    project['hardware_table'].loc[0, 'Description'] = 'Casing'
                    project['placement_config']['target_row'] = next(iter(hardware_choices(
                        project['hardware_table'], target_descriptions(project['job_type']))))
                app = self.start(project)
                self.assertEqual(self.mode(app).options, ['Not entered', 'Depth (m MD)'])
                self.assertIsNone(app.session_state['cement_params']['Tail']['top_depth'])
                self.mode(app).set_value('Depth (m MD)').run()
                self.healthy(app)
                self.assertEqual(self.depth(app).value, 2850.)

    def test_manual_first_edit_navigation_restore_and_target_change(self):
        app = self.start()
        self.mode(app).set_value('Depth (m MD)').run()
        self.assertEqual(self.depth(app).value, 2850.)
        self.depth(app).set_value(2800.)
        app.radio(key='_app_mode_key').set_value('phase2_3').run()
        self.healthy(app)
        next(w for w in app.number_input if w.label == 'Measured target depth (m MD)').set_value(3200.).run()
        self.phase(app, 'phase5')
        self.assertEqual(self.depth(app).value, 2800.)
        app.run(); self.assertEqual(self.depth(app).value, 2800.)
        app = self.start(audit.round_trip(app.session_state.to_dict()))
        self.assertEqual(self.depth(app).value, 2800.)
        self.mode(app).set_value('Not entered').run()
        self.assertIsNone(app.session_state['cement_params']['Tail']['top_depth'])
        self.mode(app).set_value('Depth (m MD)').run()
        self.assertEqual(self.depth(app).value, 2800.)

    def test_valid_saved_depth_and_draft_win(self):
        for mode, top, draft in [('Depth (m MD)', 2700., 2600.),
                                 ('Not entered', None, 2650.)]:
            with self.subTest(mode=mode):
                project = deepcopy(self.project)
                project['cement_params']['Tail'].update(top_mode=mode, top_depth=top,
                    draft_top_depth=draft, draft_top_job_type=project['job_type'])
                app = self.start(project)
                if mode == 'Not entered':
                    self.mode(app).set_value('Depth (m MD)').run()
                self.assertEqual(self.depth(app).value, top or draft)

    def test_missing_invalid_shallow_target_never_fabricates_depth(self):
        for target in (None, 'bad', -10., 0., 100., 150.):
            with self.subTest(target=target):
                project = deepcopy(self.project)
                project['placement_config']['manual_depth_m'] = target
                app = self.start(project)
                self.mode(app).set_value('Depth (m MD)').run()
                self.healthy(app)
                self.assertIsNone(self.depth(app).value)
                self.assertNotEqual(compute_phase_status(app.session_state)['phase5']['level'], 'ok')
                self.assert_export_blocked(app)

    def test_invalid_draft_cannot_supply_tail_depth(self):
        for draft in ('bad', -20., 0., None):
            with self.subTest(draft=draft):
                project = deepcopy(self.project)
                project['cement_params']['Tail']['draft_top_depth'] = draft
                app = self.start(project)
                self.mode(app).set_value('Depth (m MD)').run()
                self.healthy(app)
                self.assertEqual(self.depth(app).value, 2850.)

    def test_restored_surface_is_unfinished_and_blocked(self):
        project = deepcopy(self.project)
        project['cement_params']['Tail'].update(top_mode='Surface', top_depth=0.)
        app = self.start(project)
        self.assertEqual(self.mode(app).value, 'Not entered')
        self.assertNotIn('Surface', self.mode(app).options)
        self.assertIsNone(app.session_state['cement_params']['Tail']['top_depth'])
        self.assertNotEqual(compute_phase_status(app.session_state)['phase5']['level'], 'ok')
        self.assert_export_blocked(app)

    def test_non_tail_surface_and_unset_depth_remain_unchanged(self):
        for slurry in ('Main', 'Lead', 'Lead #1', 'Lead #2'):
            with self.subTest(slurry=slurry):
                project = deepcopy(self.project)
                project['fluids_config']['active'] = [slurry, 'Displacement Fluid']
                project['fluids_config']['params'][slurry] = project['fluids_config']['params']['Tail']
                for field in ('cement_params', 'cement_additives_dfs', 'lab_qc_params'):
                    project[field] = {slurry: project[field]['Tail']}
                app = self.start(project)
                self.assertEqual(self.mode(app, slurry).options, ['Not entered', 'Depth (m MD)', 'Surface'])
                self.mode(app, slurry).set_value('Depth (m MD)').run()
                self.assertEqual(next(w for w in app.number_input if w.label ==
                    f'Top of cement depth (m MD) - {slurry}').value, 0.)
                self.mode(app, slurry).set_value('Surface').run()
                self.assertEqual(app.session_state['cement_params'][slurry]['top_depth'], 0.)

    def test_normal_review_and_actual_word_use_existing_tail_interval(self):
        app = self.start()
        self.mode(app).set_value('Depth (m MD)').run()
        self.depth(app).set_value(2800.).run()
        self.phase(app, 'phase7')
        for b in list(app.button):
            if b.label == 'Sync with Phase V':
                app.button(key=b.key).click().run()
        next(b for b in app.button if b.label == 'Confirm measured lab results').click().run()
        self.healthy(app)
        self.export(app)
        state = app.session_state.to_dict()
        interval = slurry_intervals(state['hardware_table'], state['job_type'],
            state['placement_config'], ['Tail'], state['cement_params'])['Tail']
        self.assertEqual((interval['top_depth'], interval['bottom_depth']), (2800., 3000.))
        doc = Document(BytesIO(state['_compiled_doc_bytes']))
        table = next(t for t in doc.tables if t.rows[0].cells[0].text == 'Tail Cement Slurry Data')
        text = '\n'.join(c.text for row in table.rows for c in row.cells)
        self.assertIn('2800.0 m', text)
        self.assertIn('3000.0 m MD', text)
