"""Owner-approved Round 4 Stage 1: one physical mass/volume basis."""
import math
import unittest
from copy import deepcopy

import pandas as pd
import engineering_tools as eng
import test_audit_regressions as audit
from phase_5_cement import build_components, calculate_base_results, refresh_cement_calculations
from project_state import refresh_fluids

SACK = 110.0
WATER = 62.4
GAL = 7.48051945
BBL = 42.0 / GAL
NODES = [(2., .0371), (4., .0378), (6., .0384), (8., .0390), (10., .0394),
         (12., .0399), (14., .0403), (16., .0407), (18., .0412), (20., .0416),
         (22., .0420), (24., .0424), (26., .0428), (28., .0430), (30., .0433),
         (32., .0436), (34., .0439), (37.2, .0442)]


def formulation(tail=False):
    specs = ([('Boric Acid', .1, 1.43), ('SALT', 15., None), ('O-CFR4', .2, 1.43),
              ('O-R12', .1, 1.23), ('O-GAS BLOCK', .6, 1.05), ('Anti Foam', .01, 1.)]
             if tail else [('Hidense', 90., 5.2), ('Boric Acid', .2, 1.43), ('SALT', 18., None),
              ('O-uniFLC5', .2, 1.36), ('O-CFR4', .7, 1.43), ('O-R5', .15, 1.23),
              ('O-GAS BLOCK', .4, 1.05), ('TA-47', .01, 1.)])
    import materials_db
    rows = []
    for name, dosage, sg in specs:
        _, kind, state = materials_db.resolve_known_material(name)
        rows.append({'Material Type': kind, 'Name': name, 'Physical State': state,
                     'Mix Method': 'Dry Blend' if name == 'Hidense' else 'In Mix Water',
                     'User Input': dosage, 'Density': sg})
    return pd.DataFrame(rows)


def benchmark(tail=False):
    return eng.calculate_slurry_from_components(123. if tail else 152., 79. if tail else 731.,
                                                powders=build_components(formulation(tail))[0],
                                                liquids=build_components(formulation(tail))[1],
                                                salt_pct=15. if tail else 18.)


class Round4MassBalance(unittest.TestCase):
    app = audit.AuditRegressions.app
    healthy = audit.AuditRegressions.healthy
    phase = audit.AuditRegressions.phase
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export
    assert_export_blocked = audit.AuditRegressions.assert_export_blocked
    def test_nelson_nodes_interpolation_and_zero(self):
        helper = getattr(eng, 'dissolved_nacl_gal_per_lb', None)
        self.assertIsNotNone(helper, 'No shared Nelson-table absolute-volume helper')
        for pct, expected in NODES:
            with self.subTest(pct=pct): self.assertEqual(helper(pct), expected)
        self.assertEqual(helper(0), 0)
        for pct, expected in [(3., .03745), (15., .0405), (35.6, .04405)]:
            with self.subTest(pct=pct): self.assertAlmostEqual(helper(pct), expected, places=14)

    def test_salt_supported_range_is_enforced(self):
        for value in (.5, 1.9999, 37.20001, 50.):
            with self.subTest(pct=value):
                with self.assertRaises(ValueError): eng.calculate_slurry_from_components(118, 50, salt_pct=value)

    def test_field_salt_uses_direct_fresh_water_mass(self):
        got = eng.calculate_salt_field_amounts(18., 123.456, 987.65, 31.)
        per_bbl = WATER * BBL * .18
        self.assertAlmostEqual(got['lbs_per_bbl'], per_bbl, places=12)
        self.assertAlmostEqual(got['base_lb'], 123.456 * per_bbl, places=10)
        self.assertAlmostEqual(got['lbs_per_sk'], 123.456 * per_bbl / 987.65, places=12)
        self.assertAlmostEqual(got['with_dead_lb'], (123.456 + 31.) * per_bbl, places=10)

    def test_first_principles_mass_and_volume_conservation(self):
        powders, liquids, salt = build_components(formulation())
        got = benchmark()
        vc = SACK / (3.2 * WATER)
        mp = sum(p['percent'] * SACK / 100 for p in powders)
        vp = sum(p['percent'] * SACK / 100 / p['density_pcf'] for p in powders)
        ml = sum(l['gal_per_sk'] * l['density_ppg'] for l in liquids)
        vl = sum(l['gal_per_sk'] for l in liquids) / GAL
        w = got['water_vol_per_sack']; ms = w * WATER * .18; vs = ms * .0412 / GAL
        self.assertAlmostEqual(got['yield_ft3_per_sk'], vc + vp + vl + w + vs, places=12)
        self.assertAlmostEqual((SACK + mp + ml + w * WATER + ms) / got['yield_ft3_per_sk'], 152., places=12)

    def test_canonical_fluid_metrics_include_salt_and_wet_powders(self):
        p = {'cmt_sg': 3.2}
        got = calculate_base_results(p, 731., 152., *build_components(formulation()))
        base = got['water_vol_per_sack'] * GAL
        salt = got['water_vol_per_sack'] * WATER * .18 * .0412
        wet = sum(x['percent'] * SACK / 100 / x['density_pcf'] * GAL
                  for x in build_components(formulation())[0] if x['in_solution'])
        liquid = .41
        self.assertIn('mix_water_gal_sk', p)
        self.assertAlmostEqual(p['base_fluid_gal_sk'], base, places=12)
        self.assertAlmostEqual(p['mix_water_gal_sk'], base + salt, places=12)
        self.assertAlmostEqual(p['mix_fluid_gal_sk'], base + salt + wet + liquid, places=12)
        self.assertAlmostEqual(got['field_solution_bbl'], (base + salt + wet + liquid) * got['field_sacks'] / 42, places=10)

    def test_lab_water_comes_from_per_sack_mass_ratio(self):
        got = benchmark()
        self.assertAlmostEqual(got['lab_cmt_gr'], 1058. / got['yield_ft3_per_sk'], places=12)
        self.assertAlmostEqual(got['lab_water_gr'], got['lab_cmt_gr'] * got['water_vol_per_sack'] * WATER / SACK, places=12)

    def test_phase5_fresh_water_label_and_three_per_sack_metrics(self):
        app = self.configured_app(audit.BATCH1_JOBS[0])
        self.phase(app, 'phase5')
        labels = [m.label for m in app.metric]
        for label in ('Fresh Water', 'Base Fluid', 'Mix Water', 'Mix. Fluid'):
            self.assertIn(label, labels)
        for m in app.metric:
            if m.label == 'Mix Water': self.assertIn('gal/sk', m.value)

    def test_manual_sack_conversion_rounding_boundary(self):
        app = self.configured_app(audit.BATCH1_JOBS[0])
        state = app.session_state.to_dict()
        volume = 1000.0508 * 1.3 / 5.6146
        state['fluids_config']['params']['Main']['volume'] = volume
        p = state['cement_params']['Main']; p.update(auto_calc=False)
        p['yield'] = 1.3; p['mix_water'] = 123.4
        refresh_fluids(state)
        self.assertEqual(refresh_cement_calculations(state), [])
        self.assertEqual(p['mix_water'], 123.4)
        self.assertEqual(state['cement_params']['Main']['total_sacks'], eng.round_half_up(volume * BBL / 1.3, 1))
        self.assertNotEqual(eng.round_half_up(volume * BBL / 1.3, 1), eng.round_half_up(volume * 5.6146 / 1.3, 1))

    def test_shared_constants_liquid_density_and_mass_ratio(self):
        self.assertEqual(eng.CEMENT_SACK_LB, SACK)
        self.assertEqual(eng.WATER_DENSITY_PCF, WATER)
        self.assertEqual(eng.GAL_PER_CUFT, GAL)
        self.assertEqual(eng.BBL_TO_CUFT, BBL)
        self.assertEqual(eng.LAB_SCALE, 1058.)
        for name, sg in [('O-GAS BLOCK', 1.05), ('TA-47', 1.)]:
            default = eng.resolve_additive_density(name, 'Liquid')
            override = eng.resolve_additive_density('FIELD-X', 'Liquid', sg, require_measured=True)
            self.assertEqual(default, override)
            self.assertEqual(default, (sg * WATER / GAL, sg * WATER / GAL / SACK))

    def test_fluid_definitions_and_all_lab_masses_for_both_benchmarks(self):
        for tail in (False, True):
            with self.subTest(tail=tail):
                powders, liquids, salt = build_components(formulation(tail))
                result = benchmark(tail)
                av = .0405 if tail else .0412
                water = result['water_vol_per_sack'] * WATER
                salt_volume_gal = water * salt / 100 * av
                base = result['water_vol_per_sack'] * GAL
                wet_volume_gal = sum(p['percent'] * SACK / 100 / p['density_pcf'] * GAL
                                     for p in powders if p['in_solution'])
                self.assertAlmostEqual(result['base_fluid_gal_sk'], base, places=12)
                self.assertAlmostEqual(result['mix_water_gal_sk'], base + salt_volume_gal, places=12)
                self.assertAlmostEqual(result['mix_fluid_gal_sk'], base + salt_volume_gal + wet_volume_gal
                                       + sum(l['gal_per_sk'] for l in liquids), places=12)
                self.assertAlmostEqual(result['field_sacks'] * result['yield_ft3_per_sk'], (79 if tail else 731) * BBL, places=10)
                self.assertAlmostEqual(result['field_water_bbl'] * BBL, result['water_vol_per_sack'] * result['field_sacks'], places=10)
                self.assertAlmostEqual(result['salt_field_lb'], water * salt / 100 * result['field_sacks'], places=10)
                self.assertAlmostEqual(result['salt_lab_gr'], result['lab_water_gr'] * salt / 100, places=12)
                for powder, mass in zip(powders, result['lab_powders']):
                    self.assertAlmostEqual(mass['lab_gr'], result['lab_cmt_gr'] * powder['percent'] / 100, places=12)
                for liquid, mass in zip(liquids, result['lab_liquids']):
                    self.assertAlmostEqual(mass['lab_gr'], result['lab_cmt_gr'] * liquid['gal_per_sk'] * liquid['density_ppg'] / SACK, places=12)
                solution = result['lab_water_gr'] + result['salt_lab_gr'] + sum(l['lab_gr'] for l in result['lab_liquids'])
                solution += sum(l['lab_gr'] for p, l in zip(powders, result['lab_powders']) if p['in_solution'])
                self.assertAlmostEqual(result['lab_solution_gr'], solution, places=12)
                self.assertEqual(result, benchmark(tail))

    def test_dry_wet_powder_only_changes_tank_liquid_metric(self):
        powder = {'name': 'FIELD-X', 'percent': 2., 'density_pcf': 2.2 * WATER, 'in_solution': False}
        dry = eng.calculate_slurry_from_components(118, 50, powders=[powder])
        wet = eng.calculate_slurry_from_components(118, 50, powders=[dict(powder, in_solution=True)])
        for metric in ('yield_ft3_per_sk', 'field_sacks', 'field_water_bbl', 'base_fluid_gal_sk', 'mix_water_gal_sk', 'lab_cmt_gr', 'lab_water_gr'):
            self.assertEqual(dry[metric], wet[metric], metric)
        self.assertAlmostEqual(wet['mix_fluid_gal_sk'] - dry['mix_fluid_gal_sk'], 2.2 / (2.2 * WATER) * GAL, places=12)
        self.assertEqual(dry['lab_solution_gr'] + dry['lab_powders'][0]['lab_gr'], wet['lab_solution_gr'])

    def test_dead_volume_is_only_an_operational_allowance(self):
        from phase_5_cement import build_cement_tables
        results = []; params = []; notes = []; totals = []
        for dead in (0., 31.):
            p = {'cmt_sg': 3.2, 'dead_vol': dead, 'auto_calc': True, 'tank_name': 'Test'}
            result = calculate_base_results(p, 731, 152, *build_components(formulation()))
            p.update({'mix_water': eng.round_half_up(result['field_water_bbl'], 1),
                      'total_sacks': eng.round_half_up(result['field_sacks'], 1)})
            _, adds, note = build_cement_tables(p, formulation(), result)
            results.append(result); params.append(p); notes.append(note)
            totals.append(adds['lbs or gal (with dead Vol.)'].tolist())
        self.assertEqual(results[0], results[1])
        for metric in ('solution', 'base_fluid_gal_sk', 'mix_water_gal_sk', 'mix_fluid_gal_sk', 'total_sacks', 'mix_water'):
            self.assertEqual(params[0][metric], params[1][metric])
        self.assertNotEqual(totals[0], totals[1]); self.assertNotEqual(notes[0], notes[1])

    def test_per_sack_lab_masses_do_not_depend_on_field_volume(self):
        powders, liquids, salt = build_components(formulation())
        results = [eng.calculate_slurry_from_components(152, volume, powders=powders, liquids=liquids, salt_pct=salt) for volume in (0., 1., 731.)]
        for result in results[1:]:
            for key in ('lab_cmt_gr', 'lab_water_gr', 'salt_lab_gr', 'lab_powders', 'lab_liquids', 'lab_solution_gr'):
                self.assertEqual(results[0][key], result[key])

    def test_salt_boundaries_and_invalid_values(self):
        for pct in (0., 2., 37.2):
            with self.subTest(pct=pct):
                self.assertTrue(math.isfinite(eng.calculate_slurry_from_components(118, 50, salt_pct=pct)['yield_ft3_per_sk']))
        for pct in (-1., .00001, 1.999999, 37.200001, float('nan'), float('inf'), 'bad'):
            with self.subTest(pct=pct):
                with self.assertRaises(ValueError): eng.dissolved_nacl_gal_per_lb(pct)
                with self.assertRaises(ValueError): eng.calculate_salt_field_amounts(pct, 50., 100., 31.)

    def test_manual_values_switch_navigation_and_current_restore(self):
        app = self.configured_app(audit.BATCH1_JOBS[0])
        self.phase(app, 'phase5')
        checkbox = next(w for w in app.checkbox if w.label == 'Manual Override (Custom Yield/Water)')
        checkbox.check().run()
        next(w for w in app.number_input if w.label == 'Custom Yield (cuft/sk)').set_value(1.321).run()
        next(w for w in app.number_input if w.label == 'Custom Fresh Water (bbl)').set_value(123.4).run()
        self.phase(app, 'phase2_3'); self.phase(app, 'phase5')
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, 'phase5')
        p = restored.session_state['cement_params']['Main']
        self.assertEqual((p['yield'], p['mix_water'], p['manual_mix_water']), (1.321, 123.4, 123.4))
        checkbox = next(w for w in restored.checkbox if w.label == 'Manual Override (Custom Yield/Water)')
        checkbox.uncheck().run()
        next(w for w in restored.checkbox if w.label == 'Manual Override (Custom Yield/Water)').check().run()
        self.assertEqual(restored.session_state['cement_params']['Main']['mix_water'], 123.4)

    def test_schema_bump_stales_old_review_sync_then_word_uses_engine(self):
        from io import BytesIO
        from docx import Document
        from unittest.mock import patch
        import phase_10_procedure as report
        from project_state import fingerprint, lab_source_signature, prepare_calculations
        from phase_7_lab import build_lab_df_from_phase5
        app = self.configured_app(audit.BATCH1_JOBS[0])
        app.session_state['fluids_config']['params']['Main']['density'] = '152'
        app.session_state['fluids_config']['params']['Main']['volume'] = 731.
        app.session_state['cement_additives_dfs']['Main'] = formulation()
        self.phase(app, 'phase5'); self.phase(app, 'phase7')
        next(b for b in app.button if b.label == 'Sync with Phase V').click().run()
        next(b for b in app.button if b.label == 'Confirm measured lab results').click().run()
        state = app.session_state.to_dict(); p = state['cement_params']['Main']; fluid = state['fluid_data']['Main']; well = state['well_data']
        old = fingerprint({'schema': 2, 'base_cement': p.get('base_cement', 'Cement G Delijan'), 'cmt_sg': p.get('cmt_sg', 3.2),
                          'density': fluid.get('density', '118.0'), 'effective_density': fluid.get('effective_density'),
                          'bhst': well.get('bhst', state.get('bhst', '-')), 'bhsp': well.get('bhsp', ''),
                          'additives': state['cement_additives_dfs']['Main']})
        self.assertNotEqual(old, lab_source_signature(state, 'Main'))
        state['lab_source_signatures']['Main'] = old
        restored = self.app(audit.round_trip(state))
        self.assertTrue(restored.session_state['lab_qc_params']['Main']['reviewed'])
        self.assert_export_blocked(restored)
        self.phase(restored, 'phase7')
        self.assertTrue(any('Formulation Drift' in w.value for w in restored.warning))
        next(b for b in restored.button if b.label == 'Sync with Phase V').click().run()
        self.assertFalse(restored.session_state['lab_qc_params']['Main']['reviewed'])
        next(b for b in restored.button if b.label == 'Confirm measured lab results').click().run()
        self.export(restored)
        state = deepcopy(restored.session_state.to_dict())
        self.assertEqual(prepare_calculations(state), [])
        pd.testing.assert_frame_equal(state['lab_grid_dfs']['Main'], build_lab_df_from_phase5(formulation(),
                                      slurry_weight_pcf=152, slurry_volume_bbl=731, recalculate_mass=True))
        with patch.object(report.st, 'session_state', state): context = report.build_master_context()
        payload = context['slurries'][0]
        for field, key in [('base_fluid', 'base_fluid_gal_sk'), ('mix_fluid', 'mix_fluid_gal_sk')]:
            self.assertEqual(payload['lab'][field], state['cement_params']['Main'][key])
        self.assertEqual(state['lab_payload_Main']['mix_water'], state['cement_params']['Main']['mix_water_gal_sk'])
        doc = Document(BytesIO(restored.session_state['_compiled_doc_bytes']))
        texts = [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
        self.assertTrue(any('6.231' in text for text in texts)); self.assertTrue(any('7.145' in text for text in texts))
        self.assertTrue(any('584.2' in text for text in texts))

    def test_invalid_salt_blocks_status_and_export_then_recovers(self):
        app = self.configured_app(audit.BATCH1_JOBS[0])
        df = formulation(); df.loc[df['Name'] == 'SALT', 'User Input'] = 38.
        app.session_state['cement_additives_dfs']['Main'] = df
        self.phase(app, 'phase5')
        self.assertTrue(any('37.2' in e.value for e in app.error))
        self.assertNotEqual(eng.compute_phase_status(app.session_state)['phase5']['level'], 'ok')
        self.assert_export_blocked(app)
        df.loc[df['Name'] == 'SALT', 'User Input'] = 18.
        app.session_state['cement_additives_dfs']['Main'] = df
        self.phase(app, 'phase5')
        self.assertFalse(app.error)
        self.assertEqual(eng.compute_phase_status(app.session_state)['phase5']['level'], 'ok')
