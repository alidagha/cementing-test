"""PR13: truthful caption inspection and stable explicit-cleared metadata."""
import ast
from copy import deepcopy
import math
from pathlib import Path
import pickle

import pandas as pd
import pytest

import materials_db
import project_state as ps
from placement import EXCESS_FIELDS
import test_audit_regressions as audit
from test_round13a_a2_spacer_lab import state as spacer_state


CASE = audit.AuditRegressions()


def navigation_predicate():
    # Execute the actual pure view helper, using the same standard AST pattern
    # as the existing serializer/comparison tests; admission remains unmocked.
    tree = ast.parse(Path('main.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_navigation_sources_not_started')
    namespace = {'pd': pd, 'materials_db': materials_db,
                 'DOC_CONTROL_DEFAULTS': ps.DOC_CONTROL_DEFAULTS,
                 'WELL_DATA_DEFAULTS': ps.WELL_DATA_DEFAULTS,
                 'EXCESS_FIELDS': EXCESS_FIELDS,
                 'serialize_item': audit.namespace['serialize_item']}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), namespace)
    return namespace[node.name]


@pytest.mark.parametrize('field', [field for field, _, _ in EXCESS_FIELDS])
@pytest.mark.parametrize('invalid', [-1., float('nan'), float('inf'), float('-inf'), 'bad'])
def test_invalid_caption_sources_remain_readonly_and_unsavable(field, invalid):
    state = {'job_type': 'CSG 20"', 'placement_config': {'job_type': 'CSG 20"', field: invalid}}
    original = pickle.dumps(state)
    assert navigation_predicate()(state) is False
    assert pickle.dumps(state) == original
    if isinstance(invalid, float) and not math.isfinite(invalid):
        with pytest.raises(ValueError, match='Non-finite'):
            audit.namespace['serialize_item'](state)
    with pytest.raises(ValueError):
        audit.round_trip(state)  # Full save/load trust boundary stays strict.


@pytest.mark.parametrize('lot', [None, '', 'Operator & <lot>', 'None'])
def test_existing_lot_identity_clear_is_stable_not_a_new_default(lot):
    state = spacer_state()
    grid = ps.refresh_spacer_lab(state)
    assert grid.loc[grid.Material == 'Fresh Water', 'Lot No'].item() == 'Lab Sample'
    grid.loc[grid.Material == 'Fresh Water', 'Lot No'] = lot
    before = grid.drop(columns='Lot No').copy(deep=True)
    state['lab_grid_dfs']['Spacer'] = grid
    expected = '' if lot is None else lot
    for restored in (False, True):
        if restored:
            state = audit.round_trip(state)
        current = ps.refresh_spacer_lab(state)
        assert current.loc[current.Material == 'Fresh Water', 'Lot No'].item() == expected
        pd.testing.assert_frame_equal(current.drop(columns='Lot No'), before)


@pytest.mark.parametrize('job', ['CSG 9 5/8"', 'LNR 7"'])
def test_valid_restored_open_hole_seed_is_separate_from_missing_geometry(job):
    valid = CASE.configured_app(job)
    state = audit.round_trip(valid.session_state.to_dict())
    rows = state['hardware_table'].loc[state['hardware_table'].Description == 'Open Hole Size']
    assert len(rows) == 1
    expected = float(rows.iloc[0]['MD (m)'])
    assert expected > 0
    state['well_geometry']['td_m'] = None
    for field in ('geo_md', 'geo_tvd'):
        state[field] = state['well_data'][field] = None
    app = CASE.app(state)
    CASE.phase(app, 'phase2_3')
    assert app.number_input(key='_w_vertical_td').value == expected
    assert app.session_state['well_geometry']['td_m'] == expected
    assert app.session_state['geo_md'] == app.session_state['geo_tvd'] == expected
    assert audit.compute_phase_status(app.session_state)['phase2_3']['level'] == 'ok'
    override = expected - 100.125
    app.number_input(key='_w_vertical_td').set_value(override).run()
    CASE.phase(app, 'phase1')
    restored = audit.round_trip(app.session_state.to_dict())
    assert restored['well_geometry']['td_m'] == override


@pytest.mark.parametrize('field', [field for field, _, _ in EXCESS_FIELDS])
def test_actual_nan_mount_retains_navigation_warning_and_repair(field):
    app = CASE.app({'placement_config': {'job_type': 'CSG 20"', field: float('nan')}})
    CASE.phase(app, 'phase2_3')
    assert app.radio(key='_app_mode_key').value == 'phase2_3'
    assert any('Correct Excess' in w.label for w in app.text_input)
    assert audit.compute_phase_status(app.session_state)['phase2_3']['level'] == 'warning'
    assert math.isnan(app.session_state['placement_config'][field])
    CASE.assert_export_blocked(app)


@pytest.mark.parametrize('raw_md', ['', 'broken', '1000-1500'])
def test_missing_invalid_or_interval_hardware_cannot_invent_vertical_td(raw_md):
    app = CASE.configured_app('CSG 9 5/8"')
    state = audit.round_trip(app.session_state.to_dict())
    state['well_geometry']['td_m'] = None
    for field in ('geo_md', 'geo_tvd'):
        state[field] = state['well_data'][field] = None
    for table_key in ('hardware_table', 'hardware_editor_draft'):
        table = state.get(table_key)
        if isinstance(table, pd.DataFrame):
            table.loc[table.Description == 'Open Hole Size', 'MD (m)'] = raw_md
    restored = CASE.app(state)
    CASE.phase(restored, 'phase2_3')
    assert restored.session_state['well_geometry']['td_m'] is None
    assert audit.compute_phase_status(restored.session_state)['phase2_3']['level'] != 'ok'
    rows = restored.session_state['hardware_table'].loc[
        restored.session_state['hardware_table'].Description == 'Open Hole Size']
    assert rows['MD (m)'].item() == raw_md
    CASE.assert_export_blocked(restored)
