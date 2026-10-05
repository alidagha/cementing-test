"""Round 2 Batch 3: explicit operational inputs and nullable slurry drafts."""
from copy import deepcopy
import json
import unittest

import materials_db
import test_audit_regressions as audit
from engineering_tools import compute_phase_status, validate_cement_parameters
from project_state import refresh_fluids
from phase_5_cement import build_cement_tables, build_components, calculate_base_results
import pandas as pd

SLURRIES = ('Main', 'Lead', 'Lead #1', 'Lead #2', 'Tail')


class Round2Phase45UAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export
    assert_export_blocked = audit.AuditRegressions.assert_export_blocked

    def select_slurries(self, app):
        self.phase(app, 'phase4')
        for slurry in SLURRIES:
            app.checkbox(key='chk_fluid_' + slurry).check().run()
        self.phase(app, 'phase5')

    def dead(self, app, slurry):
        return next(w for w in app.number_input if w.label == 'Dead Vol (bbl) - ' + slurry)

    def test_all_initial_and_missing_fluid_inputs_blank_materials_preserved(self):
        for missing_params in (False, True):
            with self.subTest(missing_params=missing_params):
                app = self.app({'fluids_config': {'active': materials_db.FLUID_TYPES[:], 'params': {}}} if missing_params else None)
                self.phase(app, 'phase4')
                if not missing_params:
                    for fluid in materials_db.FLUID_TYPES:
                        app.checkbox(key='chk_fluid_' + fluid).check().run()
                for fluid in materials_db.FLUID_TYPES:
                    with self.subTest(fluid=fluid):
                        params = app.session_state['fluids_config']['params'][fluid]
                        self.assertEqual(app.text_input(key='rate_' + fluid).value, '')
                        self.assertEqual(params['pump_rate'], '')
                        if fluid != 'Displacement Fluid':
                            self.assertEqual(app.text_input(key='den_' + fluid).value, '')
                            self.assertEqual(params['density'], '')
                        material = (app.selectbox(key='_w_preflush_name_choice') if fluid == 'Pre Flush'
                                    else app.text_input(key='matname_' + fluid))
                        self.assertEqual(material.value, materials_db.DEFAULT_MATERIAL_NAMES[fluid])
                        self.assertEqual(params['volume'], 0.0)
                        record = app.session_state['fluid_data'][fluid]
                        self.assertEqual(record['duration_str'], 'INVALID RATE')
                        self.assertEqual(record['cumul_time_str'], 'INVALID RATE')
                self.assertNotEqual(compute_phase_status(app.session_state)['phase4']['level'], 'ok')

    def test_blank_rate_untouched_but_entered_four_is_meaningful(self):
        app = self.app()
        self.phase(app, 'phase4')
        self.phase(app, 'phase1')
        self.assertFalse(any('unsaved changes' in w.value for w in app.warning))
        self.phase(app, 'phase4')
        app.text_input(key='rate_Displacement Fluid').set_value('4')
        self.phase(app, 'phase1')
        self.assertTrue(any('unsaved changes' in w.value for w in app.warning))
        self.assertEqual(app.session_state['fluids_config']['params']['Displacement Fluid']['pump_rate'], '4')

    def test_density_rate_first_entry_navigation_json_and_mud_dependency(self):
        app = self.app()
        self.phase(app, 'phase2_3')
        app.text_input(key='_w_mud_density').set_value('82-84').run()
        self.phase(app, 'phase4')
        for fluid in materials_db.FLUID_TYPES:
            app.checkbox(key='chk_fluid_' + fluid).check().run()
            if fluid != 'Displacement Fluid':
                app.text_input(key='den_' + fluid).set_value('118' if fluid in SLURRIES else '90')
            app.text_input(key='rate_' + fluid).set_value('3-5')
            self.phase(app, 'phase1')
            self.phase(app, 'phase4')
            self.assertEqual(app.text_input(key='rate_' + fluid).value, '3-5')
            if fluid != 'Displacement Fluid':
                self.assertEqual(app.text_input(key='den_' + fluid).value, '118' if fluid in SLURRIES else '90')
        self.assertEqual(app.text_input(key='den_disp_live').value, '82-84')
        self.assertEqual(app.session_state['fluid_data']['Displacement Fluid']['effective_density'], 83.0)
        saved = audit.round_trip(app.session_state.to_dict())
        restored = self.app(saved)
        self.phase(restored, 'phase4')
        self.assertEqual(restored.session_state['fluids_config'], saved['fluids_config'])
        self.phase(restored, 'phase2_3')
        restored.text_input(key='_w_mud_density').set_value('90').run()
        self.phase(restored, 'phase4')
        self.assertEqual(restored.text_input(key='den_disp_live').value, '90')
        self.assertEqual(restored.session_state['fluid_data']['Displacement Fluid']['effective_density'], 90.0)

    def test_all_slurry_dead_volume_blank_zero_edits_and_current_restore(self):
        app = self.app()
        self.select_slurries(app)
        for slurry in SLURRIES:
            self.assertIsNone(self.dead(app, slurry).value)
            self.assertIsNone(app.session_state['cement_params'][slurry]['dead_vol'])
        for value in (7.5, None, 0.0):
            for slurry in SLURRIES:
                with self.subTest(slurry=slurry, value=value):
                    self.dead(app, slurry).set_value(value)
                    self.phase(app, 'phase1')
                    self.phase(app, 'phase5')
                    self.assertEqual(self.dead(app, slurry).value, value)
                    self.assertEqual(app.session_state['cement_params'][slurry]['dead_vol'], value)
            saved = audit.round_trip(app.session_state.to_dict())
            restored = self.app(saved)
            self.phase(restored, 'phase5')
            self.assertEqual(restored.session_state['cement_params'], saved['cement_params'])
            for slurry in SLURRIES:
                self.assertEqual(self.dead(restored, slurry).value, value)

    def test_current_json_nullable_active_and_inactive_dead_volume_is_strict(self):
        for slurry in SLURRIES:
            for container in ('cement_params', 'inactive_slurry_drafts'):
                for value in (None, 0.0, 7.5):
                    with self.subTest(slurry=slurry, container=container, value=value):
                        params = {'dead_vol': value}
                        project = {'job_type': 'CSG 20"', container: {slurry: params if container == 'cement_params' else {'cement_params': params}}}
                        restored = audit.round_trip(project)[container][slurry]
                        self.assertEqual((restored if container == 'cement_params' else restored['cement_params'])['dead_vol'], value)
                for value in ('', 'bad', True, float('inf'), float('nan')):
                    with self.subTest(slurry=slurry, container=container, invalid=value):
                        params = {'dead_vol': value}
                        project = {'job_type': 'CSG 20"', container: {slurry: params if container == 'cement_params' else {'cement_params': params}}}
                        with self.assertRaises(ValueError):
                            audit.decode_project(json.dumps(project).encode(), audit.namespace['deserialize_item'])

    def test_inactive_drafts_preserve_blank_and_zero_through_restore_reselection(self):
        app = self.app()
        self.select_slurries(app)
        for values in ((None,) * 5, (0.0,) * 5, (7.5, 0.0, None, None, None)):
            with self.subTest(values=values):
                for slurry, value in zip(SLURRIES, values):
                    self.dead(app, slurry).set_value(value).run()
                self.phase(app, 'phase4')
                for slurry in SLURRIES:
                    app.checkbox(key='chk_fluid_' + slurry).uncheck().run()
                saved = audit.round_trip(app.session_state.to_dict())
                self.assertEqual(tuple(saved['inactive_slurry_drafts'][s]['cement_params']['dead_vol'] for s in SLURRIES), values)
                app = self.app(saved)
                self.select_slurries(app)
                self.assertEqual(tuple(self.dead(app, s).value for s in SLURRIES), values)
                self.assertFalse(app.session_state['inactive_slurry_drafts'])

    def test_blank_dead_volume_blocks_stale_export_and_keeps_repair_for_every_slurry(self):
        for job in audit.BATCH1_JOBS:
            app = self.configured_app(job)
            self.export(app)
            saved = app.session_state.to_dict()
            for slurry in SLURRIES:
                with self.subTest(job=job, slurry=slurry):
                    project = deepcopy(saved)
                    project['fluids_config']['active'] = [slurry, 'Displacement Fluid']
                    project['fluids_config']['params'][slurry] = deepcopy(project['fluids_config']['params']['Main'])
                    project['cement_params'][slurry] = deepcopy(project['cement_params']['Main'])
                    project['cement_params'][slurry]['dead_vol'] = None
                    project['cement_additives_dfs'][slurry] = project['cement_additives_dfs']['Main'].copy()
                    restored = audit.round_trip(project)
                    restored.update({k: saved[k] for k in ('_compiled_doc_bytes', '_compiled_doc_filename', '_compiled_doc_signature')})
                    app = self.app(restored)
                    for phase in ('phase4', 'phase5', 'phase7', 'phase10'):
                        self.phase(app, phase)
                    self.assertIsNone(app.session_state['cement_params'][slurry]['dead_vol'])
                    self.assertNotEqual(compute_phase_status(app.session_state)['phase5']['level'], 'ok')
                    self.assert_export_blocked(app)
                    self.phase(app, 'phase5')
                    self.assertTrue(any(w.label == 'Dead Vol (bbl) - ' + slurry for w in app.number_input))
        for value in (None, -1.0):
            with self.assertRaises(ValueError):
                validate_cement_parameters({'dead_vol': value})
        validate_cement_parameters({'dead_vol': 0.0})

    def test_explicit_schedule_water_and_additive_results_unchanged(self):
        state = {'mud_density': '90', 'fluids_config': {'active': ['Lead', 'Main', 'Displacement Fluid'], 'params': {
            'Lead': {'volume': 30.0, 'density': '104', 'pump_rate': '3-5'},
            'Main': {'volume': 45.0, 'density': '118', 'pump_rate': '4.5'},
            'Displacement Fluid': {'volume': 20.0, 'pump_rate': '4'}}}}
        refresh_fluids(state)
        self.assertEqual([state['fluid_data'][s]['duration_min'] for s in state['fluids_config']['active']], [10.0, 10.0, 5.0])
        self.assertEqual([state['fluid_data'][s]['cumul_time_min'] for s in state['fluids_config']['active']], [10.0, 20.0, 25.0])
        self.assertEqual(state['total_pump_time_min'], 25.0)
        missing = deepcopy(state);missing['fluids_config']['params']['Main']['pump_rate'] = ''
        with self.assertRaises(ValueError):refresh_fluids(missing)
        additives = pd.DataFrame([{'Material Type': 'Anti Foam', 'Name': 'Anti Foam', 'Physical State': 'Liquid', 'Mix Method': 'In Mix Water', 'User Input': .6}])
        for slurry in SLURRIES:
            with self.subTest(slurry=slurry):
                p = {'mix_water': 30.0, 'dead_vol': 20.0, 'total_sacks': 100.0, 'auto_calc': False, 'tank_name': slurry}
                result = calculate_base_results(p, 50.0, 118.0, *build_components(additives))
                original = deepcopy(p)
                _, rows, note = build_cement_tables(p, additives, result)
                self.assertEqual(p, original)
                self.assertEqual(rows.iloc[0]['(lbs or gal)/bbl'], '2.000 gal/bbl')
                self.assertEqual(rows.iloc[0]['lbs or gal (with dead Vol.)'], '100.0 gal')
                self.assertIn('**50.0 bbl**', note)
