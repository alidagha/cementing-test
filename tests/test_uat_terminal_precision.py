"""Full-precision arithmetic; independently formatted terminal quantities."""
from copy import deepcopy
from io import BytesIO
import inspect
import unittest
from unittest.mock import patch

import pandas as pd
from docx import Document
import engineering_tools as eng
import phase_5_cement as cement
import phase_10_procedure as report
import test_audit_regressions as audit
from project_state import prepare_calculations, lab_source_signature, fingerprint
from test_uat_round4_mass_balance import formulation


def state_for(auto=True):
    return {'fluids_config': {'active': ['Main']},
            'fluid_data': {'Main': {'volume': 731., 'density': '152'}},
            'cement_params': {'Main': {'auto_calc': auto, 'cmt_sg': 3.2,
                                      'yield': 1.321, 'mix_water': 123.4567,
                                      'dead_vol': 31.1234, 'tank_name': 'Test'}},
            'cement_additives_dfs': {'Main': formulation()}}


def additive(state, mix, dosage):
    return pd.DataFrame([{'Material Type': 'Local Additive', 'Name': 'FIELD-X',
                         'Physical State': state, 'Mix Method': mix,
                         'User Input': dosage, 'Density': 2.2 if state == 'Powder' else 1.1}])


class TerminalPrecision(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export

    def refreshed(self, auto=True):
        state = state_for(auto)
        self.assertEqual(cement.refresh_cement_calculations(state), [])
        result = eng.calculate_slurry_from_components(152., 731., cmt_sg=3.2,
                                                      powders=cement.build_components(formulation())[0],
                                                      liquids=cement.build_components(formulation())[1],
                                                      salt_pct=18.)
        return state['cement_params']['Main'], result

    def test_auto_fresh_water_is_raw(self):
        p, result = self.refreshed()
        self.assertEqual(p['mix_water'], result['field_water_bbl'])

    def test_auto_sacks_are_raw(self):
        p, result = self.refreshed()
        self.assertEqual(p['total_sacks'], result['field_sacks'])

    def test_solution_is_raw(self):
        p, result = self.refreshed()
        self.assertEqual(p['solution'], result['field_solution_bbl'])

    def test_manual_sacks_are_raw(self):
        p, _ = self.refreshed(False)
        self.assertEqual(p['total_sacks'], 731. * eng.BBL_TO_CUFT / 1.321)
        self.assertEqual((p['yield'], p['mix_water']), (1.321, 123.4567))

    def tables(self, state, mix, dosage, auto=False):
        df = additive(state, mix, dosage)
        p = {'auto_calc': auto, 'mix_water': 123.4567, 'total_sacks': 2345.6789,
             'dead_vol': 31.1234, 'tank_name': 'Test'}
        raw = {'field_water_bbl': 123.4567, 'field_sacks': 2345.6789}
        before = deepcopy(p)
        blend, adds, note = cement.build_cement_tables(p, df, raw)
        self.assertEqual(p, before)
        return blend, adds, note, p

    def test_dry_blend_total_uses_raw_concentration(self):
        blend, _, _, p = self.tables('Powder', 'Dry Blend', 2.123)
        self.assertEqual(blend.iloc[1]['sks or lbs'],
                         f"{eng.round_half_up(2.123 * 1.1 * p['total_sacks'], 1):.1f} lb")

    def assert_wet(self, physical, dosage, decimals):
        _, adds, _, p = self.tables(physical, 'In Mix Water', dosage)
        concentration = dosage * 1.1 if physical == 'Powder' else dosage
        per_bbl = concentration * p['total_sacks'] / p['mix_water']
        with_dead = per_bbl * (p['mix_water'] + p['dead_vol'])
        self.assertEqual(float(adds.iloc[0]['(lbs or gal)/bbl'].split()[0]),
                         eng.round_half_up(per_bbl, 3))
        self.assertEqual(float(adds.iloc[0]['lbs or gal (with dead Vol.)'].split()[0]),
                         eng.round_half_up(with_dead, decimals))

    def test_wet_powder_has_no_cascading_rounding(self):
        self.assert_wet('Powder', 2.123, 1)

    def test_liquid_has_no_cascading_rounding(self):
        self.assert_wet('Liquid', .042, 2)

    def test_master_context_fallback_uses_exact_conversion(self):
        self.assertNotIn('5.6146', inspect.getsource(report.build_master_context))

    def test_logistics_fallback_uses_exact_conversion(self):
        self.assertNotIn('5.6146', inspect.getsource(report.render))

    def test_runtime_sacks_fallback_and_logistics_sum_raw(self):
        app = self.configured_app(audit.BATCH1_JOBS[0])
        state = deepcopy(app.session_state.to_dict())
        state['cement_params']['Main'].pop('total_sacks')
        p = state['cement_params']['Main']
        expected = 50. * eng.BBL_TO_CUFT / p['yield']
        with patch.object(report.st, 'session_state', state):
            payload = report.build_master_context(calculations_prepared=True)['slurries'][0]
        self.assertEqual(payload['total_sacks'], expected)
        app.session_state['cement_params']['Main'].pop('total_sacks')
        with patch.object(report, 'prepare_calculations', return_value=[]):
            self.phase(app, 'phase10')
        info = next(i.value for i in app.info if 'Total Cement Sacks' in i.value)
        self.assertIn(f'{expected:.1f} sacks', info)
        # Two raw counts round to 10.0 individually but must total 20.1.
        state['cement_params']['Main']['total_sacks'] = 10.04
        state['cement_params']['Lead'] = dict(p, total_sacks=10.04, top_mode='Surface')
        state['cement_params']['Main'].update(top_mode='Depth (m MD)', top_depth=1000.)
        state['fluid_data']['Lead'] = dict(state['fluid_data']['Main'])
        state['fluids_config']['active'] = ['Lead', 'Main']
        state['fluids_config']['params']['Lead'] = dict(state['fluids_config']['params']['Main'])
        state['cement_additives_dfs']['Lead'] = state['cement_additives_dfs']['Main'].copy()
        app = self.app(state)
        with patch.object(report, 'prepare_calculations', return_value=[]):
            self.phase(app, 'phase10')
        info = next(i.value for i in app.info if 'Total Cement Sacks' in i.value)
        self.assertIn('20.1 sacks', info)

    def test_word_formatting_is_a_terminal_copy(self):
        context = {'slurries': [{'yield_cuft_sk': 1.811171284123,
                                'solution': 123.45678,
                                'lab': {'base_fluid': 6.25412345, 'mix_fluid': 7.15945678}}]}
        before = deepcopy(context)
        terminal = report._word_quantity_context(context)
        self.assertEqual(context, before)
        self.assertEqual(terminal['slurries'][0]['yield_cuft_sk'], '1.811')
        self.assertEqual(terminal['slurries'][0]['solution'], '123.5')
        self.assertEqual(terminal['slurries'][0]['lab']['base_fluid'], '6.254')

    def test_auto_tables_use_engine_sources_and_salt_is_unchanged(self):
        df = pd.concat([additive('Powder', 'Dry Blend', 2.123),
                        additive('Powder', 'In Mix Water', 2.123),
                        additive('Liquid', 'In Mix Water', .413), formulation().query("Name == 'SALT'")],
                       ignore_index=True)
        raw = {'field_water_bbl': 123.4567, 'field_sacks': 2345.6789}
        p = {'auto_calc': True, 'mix_water': 123.5, 'total_sacks': 2345.7,
             'dead_vol': 31.1234, 'tank_name': 'Test'}
        blend, adds, note = cement.build_cement_tables(p, df, raw)
        self.assertEqual(blend.iloc[1]['sks or lbs'],
                         f"{eng.round_half_up(2.123 * 1.1 * raw['field_sacks'], 1):.1f} lb")
        salt = eng.calculate_salt_field_amounts(18., raw['field_water_bbl'], raw['field_sacks'], p['dead_vol'])
        self.assertEqual(adds.iloc[-1].to_dict(), cement.build_salt_additive_row(
            3, 'SALT', df.iloc[-1]['Material Type'], 18., raw['field_water_bbl'], raw['field_sacks'], p['dead_vol']))
        self.assertEqual(float(adds.iloc[-1]['lbs or gal']), eng.round_half_up(salt['base_lb'], 1))
        self.assertIn(f"{eng.round_half_up(raw['field_water_bbl'] + p['dead_vol'], 1):.1f} bbl", note)

    def test_current_review_navigation_restore_and_terminal_word(self):
        app = self.configured_app(audit.BATCH1_JOBS[0], additives=True)
        source = lab_source_signature(app.session_state, 'Main')
        reviewed = deepcopy(app.session_state['lab_qc_params']['Main'])
        self.phase(app, 'phase5')
        p = deepcopy(app.session_state['cement_params']['Main'])
        result = cement.calculate_base_results(deepcopy(p), 50., 118.,
                    *cement.build_components(app.session_state['cement_additives_dfs']['Main']))
        for field, key in (('yield', 'yield_ft3_per_sk'), ('mix_water', 'field_water_bbl'),
                           ('total_sacks', 'field_sacks'), ('solution', 'field_solution_bbl')):
            self.assertEqual(p[field], result[key])
        self.assertEqual(next(m.value for m in app.metric if m.label == 'Fresh Water'),
                         f"{result['field_water_bbl']:.2f} bbl")
        self.assertEqual(source, lab_source_signature(app.session_state, 'Main'))
        self.assertEqual(reviewed, app.session_state['lab_qc_params']['Main'])
        self.phase(app, 'phase2_3'); self.phase(app, 'phase5')
        self.assertEqual(app.session_state['cement_params']['Main'], p)
        state = audit.round_trip(app.session_state.to_dict())
        legacy = deepcopy(state)
        legacy['cement_params']['Main'].update(mix_water=round(p['mix_water'], 1),
                                              total_sacks=round(p['total_sacks'], 1), solution='Historical text')
        self.assertEqual(prepare_calculations(legacy), [])
        self.assertEqual(legacy['cement_params']['Main'], p)
        restored = self.app(audit.round_trip(legacy))
        self.export(restored)
        for _ in range(2):
            snapshot = audit.round_trip(restored.session_state.to_dict())
            signature = fingerprint(snapshot)
            self.phase(restored, 'phase5'); self.phase(restored, 'phase10')
            self.assertEqual(fingerprint(audit.round_trip(restored.session_state.to_dict())), signature)
        doc = Document(BytesIO(restored.session_state['_compiled_doc_bytes']))
        text = '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn(f"{p['yield']:.3f} cuft/sk", text)
        self.assertNotIn(str(p['yield']), text)
        self.assertIn(f"{p['solution']:.1f} bbl", text)
        self.assertIn(f"{p['base_fluid_gal_sk']:.3f} gal/sk", text)


if __name__ == '__main__':
    unittest.main()
