"""Round 4 Batch 2: formatted displays must not round canonical results."""
from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import patch

import pandas as pd
from docx import Document

import engineering_tools as eng
import test_audit_regressions as audit
from phase_5_cement import (_normalize_additive_rows, build_components, calculate_base_results,
                            refresh_cement_calculations)
from project_state import prepare_calculations
from test_uat_round4_mass_balance import formulation


METRICS = ('base_fluid_gal_sk', 'mix_water_gal_sk', 'mix_fluid_gal_sk')


def engine(df, tail=False, sg=3.2):
    return eng.calculate_slurry_from_components(123. if tail else 152., 79. if tail else 731.,
                                                cmt_sg=sg, powders=build_components(df)[0],
                                                liquids=build_components(df)[1],
                                                salt_pct=build_components(df)[2])


class Round4Precision(unittest.TestCase):
    app = audit.AuditRegressions.app
    healthy = audit.AuditRegressions.healthy
    phase = audit.AuditRegressions.phase
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export

    def benchmark_app(self):
        app = self.configured_app(audit.BATCH1_JOBS[0])
        app.session_state['fluids_config']['params']['Main'].update(density='152', volume=731.)
        app.session_state['cement_additives_dfs']['Main'] = formulation()
        self.phase(app, 'phase4')
        self.phase(app, 'phase5')
        return app

    def assert_auto_precision(self, state):
        df = state['cement_additives_dfs']['Main']
        p = state['cement_params']['Main']
        result = engine(df, sg=p['cmt_sg'])
        for key, source in [('yield', 'yield_ft3_per_sk')] + [(key, key) for key in METRICS]:
            self.assertEqual(p[key], result[source], key)
        return result

    def test_base_results_preserve_exact_engine_fluid_metrics(self):
        for tail in (False, True):
            p = {'cmt_sg': 3.2}
            result = calculate_base_results(p, 79. if tail else 731., 123. if tail else 152.,
                                            *build_components(formulation(tail)))
            for key in METRICS:
                with self.subTest(tail=tail, metric=key):
                    self.assertEqual(p[key], result[key])

    def test_auto_refresh_preserves_exact_yield_and_fluid_metrics(self):
        for tail in (False, True):
            name = 'Tail' if tail else 'Lead'
            df = formulation(tail)
            state = {'fluids_config': {'active': [name]},
                     'fluid_data': {name: {'volume': 79. if tail else 731., 'density': '123' if tail else '152'}},
                     'cement_params': {name: {'auto_calc': True, 'cmt_sg': 3.2,
                                             'dead_vol': 31., 'tank_name': 'Test'}},
                     'cement_additives_dfs': {name: df}}
            self.assertEqual(refresh_cement_calculations(state), [])
            result = engine(df, tail)
            p = state['cement_params'][name]
            for key, source in [('yield', 'yield_ft3_per_sk')] + [(key, key) for key in METRICS]:
                with self.subTest(tail=tail, metric=key):
                    self.assertEqual(p[key], result[source])

    def test_render_preserves_full_auto_state(self):
        app = self.benchmark_app()
        result = engine(formulation())
        p = app.session_state['cement_params']['Main']
        for key, source in [('yield', 'yield_ft3_per_sk')] + [(key, key) for key in METRICS]:
            with self.subTest(metric=key):
                self.assertEqual(p[key], result[source])

    def test_display_formats_do_not_change_engine_or_field_quantity_rules(self):
        app = self.benchmark_app()
        state = app.session_state.to_dict()
        result = self.assert_auto_precision(state)
        for label, source, unit in [('Calculated Yield', 'yield_ft3_per_sk', 'cuft/sk'),
                                    ('Base Fluid', METRICS[0], 'gal/sk'),
                                    ('Mix Water', METRICS[1], 'gal/sk'),
                                    ('Mix. Fluid', METRICS[2], 'gal/sk')]:
            metric = next(m for m in app.metric if m.label == label)
            self.assertEqual(metric.value, f'{result[source]:.3f} {unit}')
            self.assertNotEqual(float(metric.value.split()[0]), result[source])
        p = state['cement_params']['Main']
        for key, source in [('total_sacks', 'field_sacks'), ('mix_water', 'field_water_bbl'),
                            ('solution', 'field_solution_bbl')]:
            self.assertEqual(p[key], result[source])
        before = engine(state['cement_additives_dfs']['Main'])
        self.phase(app, 'phase2_3'); self.phase(app, 'phase5')
        self.assertEqual(before, self.assert_auto_precision(app.session_state.to_dict()))

    def test_sg_two_decimal_display_preserves_catalog_and_restored_precision(self):
        df = formulation()
        df['Density'] = None
        normalized = _normalize_additive_rows(df)
        normalized['Density'] = normalized['Density'].astype(float)
        for _, row in normalized.iterrows():
            name, physical = row['Name'], row['Physical State']
            sg = eng.default_additive_density_gcm3(name, physical)
            self.assertEqual(row['Density'], sg)
            self.assertEqual(eng.resolve_additive_density(name, physical, sg),
                             eng.resolve_additive_density(name, physical))
        # SALT's computed catalog SG contains more precision than its visible 2.16.
        salt_sg = normalized.loc[normalized['Name'] == 'SALT', 'Density'].iloc[0]
        self.assertNotEqual(salt_sg, float(f'{salt_sg:.2f}'))
        state = self.benchmark_app().session_state.to_dict()
        state['cement_params']['Main']['cmt_sg'] = 3.20123456789
        custom_sg = 1.23456789123
        custom = pd.DataFrame([{'Material Type': 'Local Liquid', 'Name': 'FIELD-X',
                               'Physical State': 'Liquid', 'Mix Method': 'In Mix Water',
                               'User Input': .5, 'Density': custom_sg}])
        state['cement_additives_dfs']['Main'] = pd.concat([normalized, custom], ignore_index=True)
        app = self.app(audit.round_trip(state))
        self.phase(app, 'phase5')
        sg_widget = next(w for w in app.number_input if w.label == 'Cement SG - Main')
        self.assertEqual(sg_widget.proto.format, '%.2f')
        self.assertEqual(sg_widget.value, 3.20123456789)
        editor = next(w for w in app.dataframe if 'Density' in w.proto.column_order)
        self.assertEqual(json.loads(editor.proto.columns)['Density']['type_config']['format'], '%.2f')
        actual = app.session_state['cement_additives_dfs']['Main']
        pd.testing.assert_frame_equal(actual, state['cement_additives_dfs']['Main'])
        self.assertEqual(build_components(actual)[1][-1]['density_ppg'], custom_sg * eng.WATER_LB_PER_GAL)
        self.assert_auto_precision(app.session_state.to_dict())
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, 'phase5')
        pd.testing.assert_frame_equal(restored.session_state['cement_additives_dfs']['Main'], actual)
        self.assertEqual(restored.session_state['cement_params']['Main']['cmt_sg'], sg_widget.value)
        self.assert_auto_precision(restored.session_state.to_dict())

    def test_current_restore_phase7_refresh_and_word_payload_keep_precision(self):
        import phase_10_procedure as report
        app = self.benchmark_app()
        original = deepcopy(app.session_state['cement_params']['Main'])
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, 'phase5')
        self.assertEqual(restored.session_state['cement_params']['Main'], original)
        result = self.assert_auto_precision(restored.session_state.to_dict())
        self.phase(restored, 'phase7')
        next(b for b in restored.button if b.label == 'Sync with Phase V').click().run()
        next(b for b in restored.button if b.label == 'Confirm measured lab results').click().run()
        for field, key in [('base_fluid', METRICS[0]), ('mix_water', METRICS[1]), ('mix_fluid', METRICS[2])]:
            self.assertEqual(restored.session_state['lab_payload_Main'][field], result[key])
        self.export(restored)
        state = deepcopy(restored.session_state.to_dict())
        self.assertEqual(prepare_calculations(state), [])
        self.assert_auto_precision(state)
        for field, key in [('base_fluid', METRICS[0]), ('mix_water', METRICS[1]), ('mix_fluid', METRICS[2])]:
            self.assertEqual(state['lab_payload_Main'][field], result[key])
        with patch.object(report.st, 'session_state', state):
            payload = report.build_master_context()['slurries'][0]
        self.assertEqual(payload['yield_cuft_sk'], result['yield_ft3_per_sk'])
        self.assertEqual(payload['lab']['base_fluid'], result[METRICS[0]])
        self.assertEqual(payload['lab']['mix_water'], result[METRICS[1]])
        self.assertEqual(payload['lab']['mix_fluid'], result[METRICS[2]])
        # Template-facing formatting is terminal; report payload remains raw.
        doc = Document(BytesIO(restored.session_state['_compiled_doc_bytes']))
        text = '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn(f"{result['yield_ft3_per_sk']:.3f} cuft/sk", text)
        self.assertIn(f"{result['mix_fluid_gal_sk']:.3f} gal/sk", text)

    def test_manual_yield_remains_exact_entered_value_across_auto_and_restore(self):
        app = self.benchmark_app()
        next(w for w in app.checkbox if w.label == 'Manual Override (Custom Yield/Water)').check().run()
        next(w for w in app.number_input if w.label == 'Custom Yield (cuft/sk)').set_value(1.321).run()
        next(w for w in app.number_input if w.label == 'Custom Fresh Water (bbl)').set_value(123.4).run()
        self.phase(app, 'phase2_3'); self.phase(app, 'phase5')
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, 'phase5')
        p = restored.session_state['cement_params']['Main']
        self.assertEqual((p['yield'], p['manual_yield'], p['mix_water'], p['manual_mix_water']),
                         (1.321, 1.321, 123.4, 123.4))
        state = deepcopy(restored.session_state.to_dict())
        self.assertEqual(refresh_cement_calculations(state), [])
        self.assertEqual((state['cement_params']['Main']['yield'], state['cement_params']['Main']['mix_water']),
                         (1.321, 123.4))
        next(w for w in restored.checkbox if w.label == 'Manual Override (Custom Yield/Water)').uncheck().run()
        self.assert_auto_precision(restored.session_state.to_dict())
        next(w for w in restored.checkbox if w.label == 'Manual Override (Custom Yield/Water)').check().run()
        self.assertEqual(restored.session_state['cement_params']['Main']['yield'], 1.321)
