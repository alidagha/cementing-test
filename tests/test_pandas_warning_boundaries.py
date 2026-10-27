"""Lossless editor append and project-serialization compatibility boundaries."""
from copy import deepcopy
import json
import warnings
from unittest.mock import patch

import pandas as pd
import pytest

import editor_state
import project_io
import test_audit_regressions as audit
from test_pre14_sh_batch_a import TABLE_PATHS, duplicate_table_project
from phase_2_3_well_data import HARDWARE_COLUMNS

CASE = audit.AuditRegressions()


@pytest.mark.parametrize('dtype,values,added,expected_dtype', [
    ('object', [None], [{'value': 1.25}, {}], 'object'),
    ('float64', [1.25], [{}], 'float64'),
    ('Int64', [1, pd.NA], [{}], 'Int64'),
    ('Float64', [1.25, pd.NA], [{}], 'Float64'),
    ('string', ['owner text', pd.NA], [{}], 'string'),
    ('object', [], [{}, {'value': 'pending'}, {}], 'object'),
])
def test_append_keeps_blank_rows_values_nullable_types_and_source(dtype, values, added, expected_dtype):
    source = pd.DataFrame({'value': pd.Series(values, dtype=dtype),
                           'note': pd.Series(['owner'] * len(values), dtype=object)})
    before = source.copy(deep=True)
    state = {'source': source, 'editor': {'added_rows': added}, 'drafts': {}}
    with warnings.catch_warnings():
        warnings.simplefilter('error', FutureWarning)
        with patch.object(editor_state.st, 'session_state', state):
            editor_state._commit_editor_change('editor', 'source', ('drafts', 'table'))
    actual = state['drafts']['table']
    assert list(actual.columns) == ['value', 'note']
    assert len(actual) == len(source) + len(added)
    assert str(actual['value'].dtype) == expected_dtype
    for index, value in enumerate(values + [row.get('value') for row in added]):
        assert pd.isna(actual.at[index, 'value']) if pd.isna(value) else actual.at[index, 'value'] == value
    assert actual['note'].iloc[:len(source)].tolist() == ['owner'] * len(source)
    assert actual['note'].iloc[len(source):].isna().all()
    pd.testing.assert_frame_equal(source, before)
    encoded = audit.namespace['serialize_item'](actual, 'drafts.table')
    restored = audit.namespace['deserialize_item'](json.loads(json.dumps(encoded, allow_nan=False)))
    assert len(restored) == len(actual) and list(restored.columns) == list(actual.columns)
    assert restored.isna().equals(actual.isna())
    assert audit.namespace['serialize_item'](restored) == encoded


@pytest.mark.parametrize('path', TABLE_PATHS)
def test_duplicate_labels_reject_before_lossy_records_with_exact_nested_path(path):
    state = duplicate_table_project(path)
    before = deepcopy(state)
    current = {'job_type': 'CMT PLUG', 'well_name': 'keep', '_compiled_doc_bytes': b'keep'}
    with warnings.catch_warnings():
        warnings.simplefilter('error', UserWarning)
        with pytest.raises(ValueError, match='[Dd]uplicate.*column') as error:
            raw = audit.namespace['serialize_item'](state)
            project_io.replace_project_state(current, project_io.decode_project(
                json.dumps(raw).encode(), audit.namespace['deserialize_item']), 'must not publish')
    assert 'project.' + '.'.join(path) in str(error.value)
    assert current == {'job_type': 'CMT PLUG', 'well_name': 'keep', '_compiled_doc_bytes': b'keep'}
    original, unchanged = state, before
    for key in path:
        original, unchanged = original[key], unchanged[key]
    pd.testing.assert_frame_equal(original, unchanged)


def test_duplicate_labels_inside_list_reject_with_index():
    table = pd.DataFrame([[1, 2]], columns=['owner', 'owner'])
    with warnings.catch_warnings():
        warnings.simplefilter('error', UserWarning)
        with pytest.raises(ValueError, match=r'project.drafts\[0\].table.*[Dd]uplicate.*column'):
            audit.namespace['serialize_item']({'drafts': [{'table': table}]})


def test_numeric_grade_open_hole_real_mount_keeps_other_grades_and_json():
    source = pd.DataFrame([
        ['Casing', '1500.25', '7', 6.276, 12.2, 23., 55, 1000., 2000.],
        ['Open Hole Size', '1500.25', '8.5', 8.5, 12.2, 23., 55, 1000., 2000.],
    ], columns=HARDWARE_COLUMNS)
    before = source.copy(deep=True)
    app = CASE.app(audit.round_trip({'job_type': 'CSG 7"', 'hardware_table': source}))
    with warnings.catch_warnings():
        warnings.simplefilter('error', FutureWarning)
        CASE.phase(app, 'phase2_3')
    CASE.healthy(app)
    actual = app.session_state['hardware_table'].copy(deep=True)
    assert actual['Grade'].tolist() == ['55', '-']
    assert actual['MD (m)'].tolist() == ['1500.25', '1500.25']
    for column in ('Joint (m)', 'Weight (ppf)', 'Collapse (psi)', 'Burst (psi)'):
        assert actual.iloc[1][column] == 0.0
        assert actual.iloc[0][column] == source.iloc[0][column]
    restored = audit.round_trip(app.session_state.to_dict())
    pd.testing.assert_frame_equal(restored['hardware_table'], actual)
    CASE.phase(app, 'phase1')
    CASE.phase(app, 'phase2_3')
    pd.testing.assert_frame_equal(app.session_state['hardware_table'], actual)
    pd.testing.assert_frame_equal(source, before)
