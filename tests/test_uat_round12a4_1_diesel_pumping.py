"""Round 12A-4-1: explicit Phase-VII Diesel rheology in the frozen Pumping API."""
from copy import deepcopy
import pickle
from unittest.mock import patch

import numpy as np
import pytest

import materials_db
import phase_7_lab as phase7
import pumping_simulation as pumping
import rheology
from project_state import reconcile_fluid_applicability, refresh_fluids
from test_uat_round10a_pumping_simulation import program_state
from test_uat_round12a1_diesel_foundation import mark_document, assert_no_document


KINDS = ('casing', 'liner', 'tieback')


def diesel_state(kind='casing', mixed=False):
    fluids = {'Diesel': 1., 'Tail': 2., 'Displacement Fluid': 2.}
    if mixed:
        fluids.update({'Pre Flush': 1., 'Spacer': 1., 'Spacer Ahead': 1., 'Scavenger': 1.})
    state = program_state(kind, fluids=fluids)
    state['mud_type'] = 'OBM'
    state['fluids_config']['params']['Diesel'].update(density='52', material_name='Diesel')
    state['lab_qc_params']['Diesel'] = deepcopy(state['lab_qc_params']['Tail'])
    return state


def forbidden(*args, **kwargs):
    raise AssertionError('Invalid or merely prepared state reached frozen simulation')


def test_frozen_explicit_contract_accepts_diesel_without_taxonomy_change():
    state = diesel_state()
    refresh_fluids(state)
    fit, issues = rheology.build_rheology(state['lab_qc_params']['Diesel'])
    assert not issues
    explicit = pumping.fcm.rheology_from_lab({'Diesel': fit})
    stages, _ = pumping.fcm.stages_from_fluid_data(state['fluid_data'])
    tail = pumping.fcm.rheology_from_lab({'Tail': fit})
    fluids, warnings, frictionless = pumping.fcm._build_fluids(
        stages, 81., rheology=explicit, slurry_rheology=tail, mud_pv_yp=(10., 1.))
    assert not warnings and not frictionless
    assert not fluids['Diesel'].frictionless_fluid
    assert fluids['Diesel'].mu_p_cp == fit['bhct_down']['pv_cp']
    assert fluids['Diesel'].tau_y == fit['bhct_down']['ty_lbf_100ft2']
    assert 'Diesel' not in pumping.fcm.SLURRY_TYPES
    assert 'Diesel' not in pumping.fcm.SPACER_TYPES


@pytest.mark.parametrize('kind', KINDS)
def test_fresh_rebuild_and_shared_bhct_down_fit_project_explicitly(kind, monkeypatch):
    state = diesel_state(kind, mixed=True)
    state['fluid_data'] = {'Diesel': {'effective_density': 999., 'volume': 999.}}
    state['lab_qc_params']['Diesel']['rheology'].update(surface_down=None, bhct_up=None)
    state['centralizer_config']['aux_rheology']['Diesel'] = 'not a Diesel authority'
    before = pickle.dumps(state)
    rebuilds, datasets = [], []
    real_rebuild, real_fit = pumping.refresh_fluids, rheology.build_rheology
    def rebuild(projected):
        rebuilds.append(projected.get('mud_type'))
        return real_rebuild(projected)
    def fit(source):
        datasets.append(deepcopy(source))
        return real_fit(source)
    monkeypatch.setattr(pumping, 'refresh_fluids', rebuild)
    monkeypatch.setattr(rheology, 'build_rheology', fit)
    inputs = pumping.prepare_pumping_simulation(state)['inputs']
    assert rebuilds == ['OBM']
    source = state['lab_qc_params']['Diesel']['rheology']['bhct_down']
    assert {'rheology': {'bhct_down': source}} in datasets
    expected = pumping.fcm.rheology_from_lab({'Diesel': real_fit({'rheology': {'bhct_down': source}})[0]})
    assert inputs['rheology']['Diesel'] == expected['Diesel']
    assert set(inputs['rheology']) == {'Diesel', 'Scavenger'}
    assert set(inputs['slurry_rheology']) == {'Tail'}
    assert inputs['rheology']['Diesel']['source'] == 'phase7:bhct_down'
    record = inputs['fluid_data']['Diesel']
    assert record['name'] == record['material_name'] == 'Diesel'
    assert record['volume'] == 1. and record['effective_density'] == 52.
    assert record['min_rate'] == 4. and record['duration_min'] == .25
    assert 'pv_cp' not in record  # Explicit mapping, not the spacer-record path.
    assert vars(inputs['options']) == vars(pumping.fcm.ChartOptions())
    assert inputs['geometry'].td_m == 1000.
    assert inputs['geometry'].track_depth_m == (400. if kind == 'tieback' else 1000.)
    assert pickle.dumps(state) == before
    assert 'Diesel' not in materials_db.RHEOLOGY_LAB_FLUIDS


@pytest.mark.parametrize('fault', ['missing_lab', 'missing_fluid', 'wrong_qc', 'missing_rheology',
    'wrong_rheology', 'missing_bhct', 'wrong_dataset', 'unselected', 'bad_selection',
    'bad_readings', 'incomplete', 'nonfinite', 'invalid_fit', 'missing_gel'])
def test_invalid_diesel_bhct_blocks_before_frozen_admission(fault, monkeypatch):
    state = diesel_state()
    qc = state['lab_qc_params']['Diesel']
    row = qc['rheology']['bhct_down']
    # A valid Surface dataset and Phase-IX entry must never provide a fallback.
    qc['rheology']['surface_down'] = deepcopy(row)
    state['centralizer_config']['aux_rheology']['Diesel'] = deepcopy(row['readings'])
    if fault == 'missing_lab': state.pop('lab_qc_params')
    elif fault == 'missing_fluid': state['lab_qc_params'].pop('Diesel')
    elif fault == 'wrong_qc': state['lab_qc_params']['Diesel'] = []
    elif fault == 'missing_rheology': qc.pop('rheology')
    elif fault == 'wrong_rheology': qc['rheology'] = []
    elif fault == 'missing_bhct': qc['rheology'].pop('bhct_down')
    elif fault == 'wrong_dataset': qc['rheology']['bhct_down'] = []
    elif fault == 'unselected': row['selected'] = False
    elif fault == 'bad_selection': row['selected'] = 'yes'
    elif fault == 'bad_readings': row['readings'] = []
    elif fault == 'incomplete': row['readings'] = {'300': '168'}
    elif fault == 'nonfinite': row['readings']['300'] = float('inf')
    elif fault == 'invalid_fit': row['readings'] = {str(rpm): float(rpm) for rpm in rheology.RPM_ORDER}
    else: row['gel_10_min'] = ''
    before = pickle.dumps(state)
    monkeypatch.setattr(pumping.fcm, 'build_three_charts', forbidden)
    monkeypatch.setattr(pumping.fcm, '_build_fluids', forbidden)
    with pytest.raises(ValueError, match='Phase VII Diesel.*bhct_down Bingham'):
        pumping.run_pumping_simulation(state)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize('source,value', [('volume', 2.), ('density', '54'), ('pump_rate', '5-7'),
    ('material_name', 'Changed source'), ('reading', '169'), ('gel', '11'), ('selected', False)])
def test_active_consumed_diesel_source_changes_signature(source, value):
    state = diesel_state()
    initial = pumping.source_signature(state)
    if source in ('reading', 'gel', 'selected'):
        row = state['lab_qc_params']['Diesel']['rheology']['bhct_down']
        if source == 'reading': row['readings']['300'] = value
        else: row['gel_10_min' if source == 'gel' else 'selected'] = value
    else:
        state['fluids_config']['params']['Diesel'][source] = value
    assert pumping.source_signature(state) != initial


def test_only_bhct_down_is_consumed_and_preparation_signature_never_run_solver(monkeypatch):
    state = diesel_state()
    initial = pumping.source_signature(state)
    baseline = pumping.prepare_pumping_simulation(state)
    monkeypatch.setattr(pumping.fcm, 'build_three_charts', forbidden)
    monkeypatch.setattr(pumping.fcm, 'simulate', forbidden)
    state['lab_qc_params']['Diesel']['rheology'].update(surface_down=None, bhct_up=None)
    state['centralizer_config']['aux_rheology']['Diesel'] = {'300': '999'}
    assert pumping.source_signature(state) == initial
    assert pickle.dumps(pumping.prepare_pumping_simulation(state)) == pickle.dumps(baseline)


def test_inactive_diesel_drafts_do_not_change_prepared_inputs_or_signature():
    state = diesel_state(mixed=True)
    state['fluids_config']['active'].remove('Diesel')
    initial, prepared = pumping.source_signature(state), pumping.prepare_pumping_simulation(state)
    state['fluids_config']['params']['Diesel'].update(volume=-1., density='51-54', pump_rate='bad')
    state['lab_qc_params']['Diesel'] = None
    assert pumping.source_signature(state) == initial
    assert pickle.dumps(pumping.prepare_pumping_simulation(state)) == pickle.dumps(prepared)
    assert set(prepared['inputs']['rheology']) == {'Scavenger'}


def test_obm_wbm_deactivation_stales_identity_preserving_both_drafts():
    state = diesel_state()
    original = pumping.source_signature(state)
    assert 'Diesel' in pumping.prepare_pumping_simulation(state)['inputs']['rheology']
    source, lab = deepcopy(state['fluids_config']['params']['Diesel']), deepcopy(state['lab_qc_params']['Diesel'])
    mark_document(state)
    state['mud_type'] = 'WBM'
    reconcile_fluid_applicability(state)
    assert_no_document(state)
    assert pumping.source_signature(state) != original
    assert 'Diesel' not in pumping.prepare_pumping_simulation(state)['inputs']['fluid_data']
    state['mud_type'] = 'OBM'
    reconcile_fluid_applicability(state)
    assert 'Diesel' not in state['fluids_config']['active']
    assert state['fluids_config']['params']['Diesel'] == source
    assert state['lab_qc_params']['Diesel'] == lab


@pytest.mark.parametrize('active', [False, True])
def test_existing_rheology_callback_and_signature_freshness(active):
    state = diesel_state()
    if not active: state['fluids_config']['active'].remove('Diesel')
    initial = pumping.source_signature(state)
    mark_document(state)
    state['_edit'] = '169'
    with patch.object(phase7.st, 'session_state', state):
        phase7._commit_rheology('Diesel', 'bhct_down', 'readings', '_edit', rpm=300)
    assert (pumping.source_signature(state) != initial) == active
    if active: assert_no_document(state)
    else: assert state['_compiled_doc_bytes'] == b'old document'


@pytest.mark.parametrize('density', ['51-54', 50, 55])
def test_fresh_phase_iv_strict_density_still_blocks(density, monkeypatch):
    state = diesel_state()
    state['fluids_config']['params']['Diesel']['density'] = density
    monkeypatch.setattr(pumping.fcm, 'build_three_charts', forbidden)
    with pytest.raises(ValueError, match=r'Diesel density must be a single value between 51 and 54 pcf\.'):
        pumping.run_pumping_simulation(state)


@pytest.mark.parametrize('kind', KINDS)
def test_real_engine_diesel_simulation_preserves_order_physics_and_figure_ownership(kind, monkeypatch):
    state = diesel_state(kind, mixed=True)
    before = pickle.dumps(state)
    calls = []
    real = pumping.fcm.simulate
    def observe(job):
        calls.append(job)
        return real(job)
    monkeypatch.setattr(pumping.fcm, 'simulate', observe)
    figures = pumping.fcm.plt.get_fignums()
    output = pumping.run_pumping_simulation(state)
    try:
        assert len(calls) == 1
        job, = calls
        expected = [name for name in materials_db.HYDRAULIC_EXECUTION_ORDER
                    if name in state['fluids_config']['active']]
        assert [stage.fluid_type for stage in job.placement] == expected
        assert expected[:5] == ['Diesel', 'Pre Flush', 'Spacer', 'Spacer Ahead', 'Scavenger']
        assert not job.frictionless and all(not f.frictionless_fluid for f in job.fluids.values())
        fit = rheology.build_rheology(state['lab_qc_params']['Diesel'])[0]['bhct_down']
        assert job.fluids['Diesel'].mu_p_cp == fit['pv_cp']
        assert job.fluids['Diesel'].tau_y == fit['ty_lbf_100ft2']
        assert isinstance(output['result'], pumping.fcm.SimResult)
        assert output['result'].dyn is not None
        assert all(np.isfinite(getattr(output['result'], field)).all()
                   for field in ('t', 'pump', 'hydro', 'dyn', 'q_in', 'q_out'))
        assert output['result'].t_eod == sum(state['fluids_config']['params'][n]['volume']/4. for n in expected)
        assert len(output['figure'].axes) == 3
        assert not any('HYDROSTATIC-ONLY' in w or 'contribution only' in w for w in output['warnings'])
        assert pickle.dumps(state) == before
    finally:
        pumping.fcm.plt.close(output['figure'])
    assert pumping.fcm.plt.get_fignums() == figures


@pytest.mark.parametrize('job', ['CMT PLUG', 'CMT SQUEEZE'])
def test_plug_squeeze_remain_na_even_with_unfinished_diesel(job, monkeypatch):
    monkeypatch.setattr(pumping.fcm, 'build_three_charts', forbidden)
    state = {'job_type': job, 'fluids_config': {'active': ['Diesel']}, 'lab_qc_params': None}
    output = pumping.run_pumping_simulation(state)
    assert output['applicable'] is False and output['message'] == 'Not applicable (Plug/Squeeze).'
    assert output['inputs'] is output['figure'] is output['result'] is None
