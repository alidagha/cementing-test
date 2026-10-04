"""Round 2 Batch 4: one editable g/cm³ contract for formulation and lab."""
import json
import unittest
from unittest.mock import patch

import pandas as pd
import test_audit_regressions as audit
import editor_state
import materials_db
from engineering_tools import (DEFAULT_LIQUID_PROPERTIES, DEFAULT_POWDER_DENSITIES_PCF,
    resolve_additive_density, compute_phase_status,
    calculate_slurry_from_components)
from phase_5_cement import (_normalize_additive_rows, REQUIRED_ADDITIVE_COLUMNS,
    build_components, calculate_base_results)
from phase_7_lab import build_lab_df_from_phase5
from project_state import lab_source_signature


def row(name, method='In Mix Water', density=None):
    _, kind, state = materials_db.resolve_known_material(name)
    return {'Material Type': kind, 'Name': name, 'Physical State': state,
            'Mix Method': method, 'User Input': .1 if state == 'Liquid' else .5,
            'Density': density}


class Round2DensityUAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export
    assert_export_blocked = audit.AuditRegressions.assert_export_blocked

    def editor(self, app):
        return next(e for e in app.dataframe if '_editor_additives_main_' in e.proto.id)

    def edit_rows(self, app, edits):
        widgets = app._tree.get_widget_states()
        event = widgets.widgets.add()
        event.id = self.editor(app).proto.id
        event.string_value = json.dumps({'edited_rows': edits, 'added_rows': [], 'deleted_rows': []})
        app._run(widgets)
        self.healthy(app)

    def test_catalog_coverage_and_prefill_every_recognized_name(self):
        for name in materials_db.ALL_MATERIAL_NAMES:
            with self.subTest(name=name):
                source = row(name)
                liquid = source['Physical State'] == 'Liquid'
                table = DEFAULT_LIQUID_PROPERTIES if liquid else DEFAULT_POWDER_DENSITIES_PCF
                prop = table[name.casefold()]
                expected = prop['density_ppg'] / 8.342 if liquid else prop / 62.4
                for method in ('In Mix Water', 'Dry Blend'):
                    source['Mix Method'] = method
                    result = _normalize_additive_rows(pd.DataFrame([source]))
                    self.assertEqual(result.at[0, 'Density'], expected)
                    self.assertEqual(result.at[0, 'Mix Method'], method)
                    self.assertEqual(result.at[0, 'Physical State'], source['Physical State'])

    def test_untouched_defaults_preserve_exact_engineering_and_lab_results(self):
        for name in materials_db.ALL_MATERIAL_NAMES:
            source = row(name)
            if source['Material Type'] == 'Cement':
                continue  # Base cement remains the separate selector.
            methods = ('In Mix Water', 'Dry Blend') if source['Physical State'] == 'Powder' else ('In Mix Water',)
            for method in methods:
                with self.subTest(name=name, method=method):
                    source['Mix Method'] = method
                    before = pd.DataFrame([source])
                    after = _normalize_additive_rows(before)
                    old = build_components(before)
                    new = build_components(after)
                    self.assertEqual(new, old)
                    p = {'cmt_sg': 3.2, 'dead_vol': 20, 'mix_water': 30, 'total_sacks': 100, 'tank_name': 'Test'}
                    self.assertEqual(calculate_base_results(p, 50, 118, *new), calculate_base_results(p, 50, 118, *old))
                    pd.testing.assert_frame_equal(build_lab_df_from_phase5(after, recalculate_mass=True),
                                                  build_lab_df_from_phase5(before, recalculate_mass=True))
                    if not name.casefold() == 'salt':
                        if source['Physical State'] == 'Liquid':
                            prop = DEFAULT_LIQUID_PROPERTIES[name.casefold()]
                            self.assertEqual(new[1][0]['density_ppg'], prop['density_ppg'])
                            self.assertEqual(new[1][0]['lab_factor'], prop['lab_factor'])
                        else:
                            self.assertEqual(new[0][0]['density_pcf'], DEFAULT_POWDER_DENSITIES_PCF[name.casefold()])

    def test_manual_overrides_change_engine_and_lab_on_both_mix_paths(self):
        for name, method, density in (('O-uniFLC5', 'In Mix Water', 1.5),
                ('Bentonite', 'Dry Blend', 2.8), ('Micro Silica', 'Dry Blend', 2.3),
                ('O-GAS BLOCK', 'In Mix Water', 1.2)):
            with self.subTest(name=name, method=method):
                default = _normalize_additive_rows(pd.DataFrame([row(name, method)]))
                edited = default.copy(); edited.at[0, 'Density'] = density
                edited = _normalize_additive_rows(edited, default)
                self.assertEqual(edited.at[0, 'Density'], density)
                powders, liquids, salt = build_components(edited)
                if liquids:
                    self.assertEqual(liquids[0]['density_ppg'], density * 8.342)
                    self.assertEqual(liquids[0]['lab_factor'], density * 8.342 / 109.9)
                else:
                    self.assertEqual(powders[0]['density_pcf'], density * 62.4)
                expected = calculate_slurry_from_components(118, 50, powders=powders, liquids=liquids, salt_pct=salt)
                params = {'cmt_sg': 3.2, 'dead_vol': 20}
                calculated = calculate_base_results(params, 50, 118, powders, liquids, salt)
                self.assertEqual(calculated, expected)
                self.assertNotEqual(calculated, calculate_base_results(params, 50, 118, *build_components(default)))
                self.assertFalse(build_lab_df_from_phase5(edited, recalculate_mass=True).equals(
                    build_lab_df_from_phase5(default, recalculate_mass=True)))
                custom = edited.copy(); custom.at[0, 'Name'] = 'Other (Custom)'
                custom.at[0, 'Material Type'] = 'Other (Custom)'
                self.assertEqual(build_components(custom), (powders if not powders else [dict(powders[0], name='Other (Custom)')],
                    liquids if not liquids else [dict(liquids[0], name='Other (Custom)')], salt))
                a = build_lab_df_from_phase5(edited, recalculate_mass=True)
                b = build_lab_df_from_phase5(custom, recalculate_mass=True)
                self.assertEqual(a['Mass'].tolist(), b['Mass'].tolist())

    def test_name_change_resets_density_without_cross_row_leaks(self):
        before = _normalize_additive_rows(pd.DataFrame([row('Micro Silica'), row('O-GAS BLOCK')]))
        before.at[0, 'Density'] = 2.3
        edited = before.copy(); edited.at[0, 'Name'] = 'Hidense'
        result = _normalize_additive_rows(edited, before)
        self.assertEqual(result.at[0, 'Density'], 5.2)
        self.assertEqual(result.at[1, 'Density'], 1.05)
        edited.at[0, 'Name'] = 'O-GAS BLOCK'
        self.assertEqual(_normalize_additive_rows(edited, before).at[0, 'Density'], 1.05)
        same = _normalize_additive_rows(before, before)
        self.assertEqual(same.at[0, 'Density'], 2.3)
        blank = before.copy(); blank.at[0, 'Density'] = None
        self.assertEqual(_normalize_additive_rows(blank, before).at[0, 'Density'], 2.2)

    def test_callback_commits_resets_before_navigation_and_aligns_deleted_rows(self):
        source = _normalize_additive_rows(pd.DataFrame([row('Micro Silica'), row('O-uniFLC5')]))
        source.at[1, 'Density'] = 1.5
        state = {'source': source, 'editor': {'edited_rows': {'1': {'Name': 'Hidense'}},
            'deleted_rows': [0], 'added_rows': [row('O-GAS BLOCK')]}, 'cement_additives_dfs': {}}
        with patch.object(editor_state.st, 'session_state', state):
            editor_state._commit_editor_change('editor', 'source', ('cement_additives_dfs', 'Main'), _normalize_additive_rows)
        saved = state['cement_additives_dfs']['Main']
        self.assertEqual(saved['Name'].tolist(), ['Hidense', 'O-GAS BLOCK'])
        self.assertEqual(saved['Density'].tolist(), [5.2, 1.05])
        pd.testing.assert_frame_equal(state['source'], source)

    def test_density_column_is_last_editable_gcm3_two_decimals(self):
        app = self.configured_app(audit.BATCH1_JOBS[0], additives=True)
        self.phase(app, 'phase5')
        proto = self.editor(app).proto
        self.assertEqual(list(proto.column_order), REQUIRED_ADDITIVE_COLUMNS + ['Density'])
        config = json.loads(proto.columns)['Density']
        self.assertEqual(config['label'], 'Measured Density (g/cm³)')
        self.assertEqual(config['type_config']['format'], '%.2f')
        self.assertFalse(config.get('disabled', False))

    def test_manual_first_edit_navigation_current_json_and_name_reset(self):
        app = self.configured_app(audit.BATCH1_JOBS[0])
        app.session_state['cement_additives_dfs']['Main'] = pd.DataFrame([
            row('O-uniFLC5'), row('Micro Silica', 'Dry Blend'), row('O-GAS BLOCK')])
        self.phase(app, 'phase5')
        self.edit_rows(app, {'0': {'Density': 1.5}, '1': {'Density': 2.3}, '2': {'Density': 1.2}})
        self.phase(app, 'phase2_3'); self.phase(app, 'phase5')
        self.assertEqual(app.session_state['cement_additives_dfs']['Main']['Density'].tolist(), [1.5, 2.3, 1.2])
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, 'phase5')
        self.assertEqual(restored.session_state['cement_additives_dfs']['Main']['Density'].tolist(), [1.5, 2.3, 1.2])
        self.edit_rows(restored, {'1': {'Name': 'Hidense'}})
        self.phase(restored, 'phase7')
        df = restored.session_state['cement_additives_dfs']['Main']
        self.assertEqual(df['Density'].tolist(), [1.5, 5.2, 1.2])
        self.assertEqual(df.at[1, 'Name'], 'Hidense')

    def test_custom_and_invalid_known_density_block_calculation(self):
        for state in ('Powder', 'Liquid'):
            for value in (None, '', 0, -1, float('nan'), float('inf'), 'broken'):
                with self.subTest(state=state, value=value):
                    df = pd.DataFrame([{'Material Type': 'Other (Custom)', 'Name': 'Other (Custom)',
                        'Physical State': state, 'Mix Method': 'In Mix Water', 'User Input': .1, 'Density': value}])
                    with self.assertRaises(ValueError): build_components(df)
                    with self.assertRaises(ValueError): build_lab_df_from_phase5(df, recalculate_mass=True)
            for value in (0, -1, float('inf'), 'broken'):
                with self.subTest(known_state=state, value=value):
                    with self.assertRaises(ValueError):
                        resolve_additive_density('O-GAS BLOCK' if state == 'Liquid' else 'Micro Silica', state, value)

    def test_density_edit_invalidates_existing_lab_signature_and_word(self):
        app = self.configured_app(audit.BATCH1_JOBS[0], additives=True)
        self.export(app)
        old = lab_source_signature(app.session_state, 'Main')
        self.phase(app, 'phase5'); self.edit_rows(app, {'0': {'Density': 1.2}})
        self.assertNotEqual(old, lab_source_signature(app.session_state, 'Main'))
        self.assertNotEqual(compute_phase_status(app.session_state)['phase7']['level'], 'ok')
        self.assertNotIn('_compiled_doc_bytes', app.session_state)
        self.assert_export_blocked(app)

    def test_salt_formula_ignores_display_density(self):
        before = _normalize_additive_rows(pd.DataFrame([row('SALT')]))
        after = before.copy(); after.at[0, 'Density'] = 5.0
        self.assertEqual(build_components(before), build_components(after))
        pd.testing.assert_frame_equal(build_lab_df_from_phase5(before, recalculate_mass=True),
                                      build_lab_df_from_phase5(after, recalculate_mass=True))

    def test_valid_exports_all_five_workflows_with_current_overrides(self):
        for job in audit.BATCH1_JOBS:
            with self.subTest(job=job):
                app = self.configured_app(job)
                app.session_state['cement_additives_dfs']['Main'] = pd.DataFrame([
                    row('O-uniFLC5', density=1.5), row('Micro Silica', 'Dry Blend', 2.3), row('O-GAS BLOCK', density=1.2)])
                self.phase(app, 'phase5'); self.phase(app, 'phase7')
                next(b for b in app.button if b.label == 'Sync with Phase V').click().run()
                next(b for b in app.button if b.label == 'Confirm measured lab results').click().run()
                restored = self.app(audit.round_trip(app.session_state.to_dict()))
                self.phase(restored, 'phase5'); self.phase(restored, 'phase7')
                self.assertEqual(restored.session_state['cement_additives_dfs']['Main']['Density'].tolist(), [1.5, 2.3, 1.2])
                self.assertEqual(compute_phase_status(restored.session_state)['phase7']['level'], 'ok')
                self.export(restored)


if __name__ == '__main__':
    unittest.main()
