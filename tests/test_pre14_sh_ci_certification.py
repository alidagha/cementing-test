"""Incomplete Pre Flush drafts must not infer an engineering job at startup."""
from copy import deepcopy

import pytest

import engineering_tools as tools
import materials_db
from cement_chart_model import chart_job_kind
from test_uat_round9e_dynamic_solver import readings


def draft(measured=False):
    state = {'fluids_config': {'active': ['Pre Flush'], 'params': {
        'Pre Flush': {'volume': 25., 'density': '80', 'pump_rate': '4',
                      'material_name': 'Fresh Water'}}}}
    if measured:
        state['lab_qc_params'] = {'Pre Flush': {'rheology': {'bhct_down': {
            'selected': True, 'readings': readings()}}}}
    return state


@pytest.mark.parametrize('job_source', ['absent', 'null'])
@pytest.mark.parametrize('measured', [False, True])
def test_missing_job_is_an_unchanged_incomplete_draft(job_source, measured):
    state = draft(measured)
    if job_source == 'null':
        state['job_type'] = None
    before = deepcopy(state)
    status = tools.compute_phase_status(state)
    assert status['phase7']['level'] == 'warning'
    assert 'Pre Flush' in status['phase7']['message']
    assert status['phase9']['level'] == 'empty'
    assert state == before
    # Status may handle an unfinished selection; the engineering model cannot.
    with pytest.raises(ValueError, match='Unsupported chart job'):
        chart_job_kind(state.get('job_type'))


@pytest.mark.parametrize('job', ['', 'Unknown job', 'CSG 42"'])
def test_supplied_unsupported_job_still_fails_closed(job):
    state = draft(measured=True)
    state['job_type'] = job
    before = deepcopy(state)
    with pytest.raises(ValueError, match='Unsupported chart job'):
        tools.compute_phase_status(state)
    assert state == before


@pytest.mark.parametrize('job', materials_db.JOB_TYPES)
@pytest.mark.parametrize('measured', [False, True])
def test_valid_job_preflush_status_keeps_existing_applicability(job, measured):
    state = draft(measured)
    state['job_type'] = job
    before = deepcopy(state)
    status = tools.compute_phase_status(state)
    not_applicable = job in ('CMT PLUG', 'CMT SQUEEZE', materials_db.CT_JOB)
    assert status['phase7']['level'] == ('ok' if measured or not_applicable else 'warning')
    assert state == before
