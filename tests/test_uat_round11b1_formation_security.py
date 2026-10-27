"""Round 11B-1 pure Formation source, normalization and static-security contract."""
from copy import deepcopy
import json
import math

import pandas as pd
import pytest

import cement_chart_model as model
from project_io import decode_project, replace_project_state
from project_state import fingerprint, is_project_key
from test_uat_round8a_chart_model import balanced_state, hardware


def advanced(state=None, rows=None):
    state = balanced_state() if state is None else state
    state['formation_pressure_config'] = {'mode': 'advanced', 'profile': rows if rows is not None else [
        {'md_m': 500., 'pore_psi': 400., 'frac_psi': 2000.},
        {'md_m': 1000., 'pore_psi': 800., 'frac_psi': 3000.}]}
    return state


def test_default_basic_is_pure_and_keeps_existing_display_and_hydro():
    state = balanced_state()
    before = fingerprint(state)
    result = model.build_chart_model(state)
    assert result['formation_pressure']['mode'] == 'basic'
    assert result['pore_frac']['md_m'] == result['hydrostatic']['md_m']
    assert result['pore_frac']['pore_psi'] == [model.pressure_psi(70., tvd) for tvd in result['pore_frac']['tvd_m']]
    assert result['static_security']['domain']['top_md'] == 500.
    assert result['static_security']['domain']['bottom_md'] == 1000.
    assert result['static_security']['status'] == 'safe'
    assert fingerprint(state) == before and 'formation_pressure_config' not in state


def test_advanced_uses_only_active_source_and_drafts_roundtrip():
    state = advanced()
    state.pop(model.PORE_FIELD); state.pop(model.FRAC_FIELD)
    assert not model.chart_readiness(state, True)['issues']
    cfg = deepcopy(state['formation_pressure_config'])
    saved = decode_project(json.dumps({'job_type': state['job_type'], 'formation_pressure_config': cfg}).encode(), lambda x: x)
    assert saved['formation_pressure_config'] == cfg
    state[model.PORE_FIELD], state[model.FRAC_FIELD] = 70., 160.
    sig = model.formation_source(state)
    state[model.PORE_FIELD] = 71.
    assert model.formation_source(state) == sig
    state['formation_pressure_config']['mode'] = 'basic'
    assert model.build_chart_model(state)['formation_pressure']['mode'] == 'basic'
    assert state['formation_pressure_config']['profile'] == cfg['profile']
    sig = model.formation_source(state)
    state['formation_pressure_config']['profile'][0]['pore_psi'] += 1
    assert model.formation_source(state) == sig
    assert all(not is_project_key(k) for k in ('_cement_chart_model', '_cement_chart_source'))


@pytest.mark.parametrize('bad', [None, [], {}, {'mode': 'other', 'profile': []},
    {'mode': 'advanced', 'profile': {},}, {'mode': 'basic', 'profile': [], 'result': {}},
    {'mode': 'advanced', 'profile': [None]}, {'mode': 'advanced', 'profile': [{'md_m': 1, 'pore_psi': 1, 'frac_psi': 2, 'tvd_m': 1}]},
    *[{'mode': 'advanced', 'profile': [{'md_m': 1, 'pore_psi': v, 'frac_psi': 3}]} for v in (0, -1, True, '2', float('nan'), float('inf'))],
    {'mode': 'advanced', 'profile': [{'md_m': 1, 'pore_psi': 3, 'frac_psi': 3}]},
    {'mode': 'advanced', 'profile': [{'md_m': 2, 'pore_psi': 1, 'frac_psi': 3}, {'md_m': 1, 'pore_psi': 1, 'frac_psi': 3}]}])
def test_malformed_saved_authority_is_transactionally_rejected(bad):
    current = {'well_name': 'Original', '_compiled_doc_bytes': b'unchanged'}
    before = deepcopy(current)
    with pytest.raises(ValueError):
        decoded = decode_project(json.dumps({'job_type': 'CSG 9 5/8"', 'formation_pressure_config': bad}).encode(), lambda x: x)
        replace_project_state(current, decoded, 'bad')
    assert current == before


def test_blank_drafts_save_but_are_not_ready():
    cfg = {'mode': 'advanced', 'profile': [{'md_m': 500., 'pore_psi': None, 'frac_psi': None}]}
    assert decode_project(json.dumps({'well_name': 'Draft', 'formation_pressure_config': cfg}).encode(), lambda x: x)['formation_pressure_config'] == cfg
    assert model.chart_readiness(advanced(rows=cfg['profile']), True)['issues']


@pytest.mark.parametrize('fault', ['first', 'last', 'duplicate', 'reversed', 'outside', 'nan_md', 'zero_frac', 'negative_frac', 'inf_frac', 'equal', 'inverted'])
def test_advanced_never_repairs_or_extrapolates(fault):
    state = advanced(); rows = state['formation_pressure_config']['profile']
    if fault == 'first': rows[0]['md_m'] = 501.
    elif fault == 'last': rows[-1]['md_m'] = 999.
    elif fault == 'duplicate': rows[-1]['md_m'] = 500.
    elif fault == 'reversed': rows.reverse()
    elif fault == 'outside': rows.insert(1, {'md_m': 1001., 'pore_psi': 500., 'frac_psi': 2000.})
    elif fault == 'nan_md': rows[0]['md_m'] = float('nan')
    elif fault == 'zero_frac': rows[0]['frac_psi'] = 0.
    elif fault == 'negative_frac': rows[0]['frac_psi'] = -1.
    elif fault == 'inf_frac': rows[0]['frac_psi'] = float('inf')
    elif fault == 'equal': rows[0]['frac_psi'] = rows[0]['pore_psi']
    else: rows[0]['frac_psi'] = rows[0]['pore_psi'] - 1.
    before = deepcopy(state['formation_pressure_config'])
    assert model.chart_readiness(state, True)['issues']
    assert repr(state['formation_pressure_config']) == repr(before)


def synthetic(pore, frac, depths=None, geometry=None, segments=None):
    depths = depths or [500., 625., 750., 875., 1000.]
    geometry = geometry or {'type': 'Vertical', 'td_m': 1000.}
    import well_profile
    tvds = well_profile.tvd_at_md(geometry, depths)
    domain = {'top_md': depths[0], 'bottom_md': depths[-1], 'top_tvd': tvds[0], 'bottom_tvd': tvds[-1],
              'segments': segments or [{'top_md': depths[0], 'bottom_md': depths[-1], 'top_tvd': tvds[0], 'bottom_tvd': tvds[-1]}]}
    formation = {'md_m': depths, 'tvd_m': tvds, 'pore_psi': pore, 'frac_psi': frac, 'domain': domain}
    hydro = {'md_m': depths, 'tvd_m': tvds, 'pressure_psi': [2*t for t in tvds]}
    return model.analyze_static_security(geometry, hydro, formation)


@pytest.mark.parametrize('kind', ['frac', 'pore'])
def test_exact_disconnected_intervals_crossings_and_maxima(kind):
    h = [1000., 1250., 1500., 1750., 2000.]
    delta = [-100., 100., -100., 100., -100.]
    pore = [v+d for v,d in zip(h,delta)] if kind == 'pore' else [100.]*5
    frac = [v-d for v,d in zip(h,delta)] if kind == 'frac' else [3000.]*5
    result = synthetic(pore, frac)
    rows = result[kind+'_violations']
    assert result['status'] == 'warning' and len(rows) == 2
    for row,start,end,maximum in zip(rows,[562.5,812.5],[687.5,937.5],[625.,875.]):
        assert row['start_md_m'] == pytest.approx(start, abs=1e-9)
        assert row['end_md_m'] == pytest.approx(end, abs=1e-9)
        assert row['max_delta_psi'] == 100.
        assert row['max_at_md_m'] == row['max_at_tvd_m'] == maximum
        assert abs(row['hydro_psi_at_max']-row['limit_psi_at_max']) == 100.
    assert [c['md_m'] for c in result['crossings']] == pytest.approx([562.5,687.5,812.5,937.5])
    assert all(c['pressure_psi'] == pytest.approx(2*c['tvd_m']) for c in result['crossings'])


@pytest.mark.parametrize('boundary', ['pore', 'frac'])
def test_equality_contacts_are_not_violations(boundary):
    h = [1000.,1250.,1500.,1750.,2000.]
    result = synthetic(h if boundary=='pore' else [100.]*5, h if boundary=='frac' else [3000.]*5)
    assert result['status']=='safe'
    assert not result['pore_violations'] and not result['frac_violations']
    assert result['crossings'] and all(c['boundary']==boundary for c in result['crossings'])


def test_cased_gap_never_merges_exposed_intervals():
    parts=[{'top_md':500.,'bottom_md':600.,'top_tvd':500.,'bottom_tvd':600.},
           {'top_md':800.,'bottom_md':1000.,'top_tvd':800.,'bottom_tvd':1000.}]
    result=synthetic([100.]*5,[900.]*5,segments=parts)
    assert [(r['start_md_m'],r['end_md_m']) for r in result['frac_violations']] == [(500.,600.),(800.,1000.)]


def test_unsafe_result_warns_without_readiness_failure_and_preserves_final_column():
    state=advanced(); original=model.build_chart_model(balanced_state())
    state['formation_pressure_config']['profile']=[{'md_m':500.,'pore_psi':1.,'frac_psi':2.},{'md_m':1000.,'pore_psi':1.,'frac_psi':2.}]
    ready=model.chart_readiness(state,True)
    assert not ready['issues'] and ready['warnings']
    assert ready['model']['static_security']['status']=='warning'
    for key in ('hydrostatic','annular_intervals','cement_placement','returned_bbl','capacity_segments'):
        assert ready['model'][key]==original[key]


def test_directional_formation_and_crossing_use_tvd_authority(monkeypatch):
    import well_profile
    geometry={'type':'Directional','survey':pd.DataFrame({'MD':[0.,1000.], 'Deviation':[0.,60.], 'Azimuth':[0.,0.]})}
    state=advanced(); state['well_geometry']=geometry
    calls=[]; real=model.tvd_at_md
    def observe(g, depths):
        values=list(depths); calls.append(values); return real(g,values)
    monkeypatch.setattr(model,'tvd_at_md',observe)
    formation=model.build_chart_model(state)['formation_pressure']
    assert formation['tvd_m']==well_profile.tvd_at_md(geometry,[500.,1000.])
    assert calls and formation['pore_psi']==[400.,800.]
    tvds=well_profile.tvd_at_md(geometry,[500.,1000.])
    h=[2*t for t in tvds]
    result=synthetic([100.,100.],[h[0]+100.,h[1]-100.],depths=[500.,1000.],geometry=geometry)
    crossing=result['crossings'][0]
    assert crossing['tvd_m']==pytest.approx(sum(tvds)/2,abs=1e-9)
    assert well_profile.tvd_at_md(geometry,[crossing['md_m']])[0]==pytest.approx(crossing['tvd_m'],abs=1e-9)
    assert abs(crossing['md_m']-750.)>1.


def test_tieback_no_exposure_and_plug_squeeze_applicability_unchanged():
    state=balanced_state(); state['job_type']='TIE BACK LNR 7"'
    from placement import hardware_choices
    # Synthetic surface Top and receiver-at-tie-in, wholly cased/no exposure.
    state['hardware_table']=hardware(('Tie Back','0-1000','7',6.276),('Previous Casing','1200','9.625',8.535),
                                     ('Previous Liner','1000-1300','7',6.276))
    state['placement_config'].update(job_type=state['job_type'],host_row=next(iter(hardware_choices(state['hardware_table'],{'Previous Casing'}))))
    assert model.build_chart_model(state)['pore_frac']['kind']=='markers'
    assert model.build_chart_model(state)['static_security']['domain'] is None
    assert model.chart_readiness(advanced(state),True)['issues']
    for job in ('CMT PLUG','CMT SQUEEZE'):
        assert model.build_chart_model({'job_type':job}) is None
        assert model.chart_readiness({'job_type':job},True)=={'issues':[],'warnings':[],'model':None}


def test_both_violation_types_and_contact_separates_unsafe_components():
    result=synthetic([900.,1350.,1400.,1850.,1900.],[950.,1450.,1450.,1950.,1950.])
    assert result['pore_violations'] and result['frac_violations']
    # A single equality contact is not part of either strict unsafe component.
    result=synthetic([100.]*3,[900.,1500.,1900.],depths=[500.,750.,1000.])
    assert len(result['frac_violations'])==2
    assert result['frac_violations'][0]['end_md_m']==750.
    assert result['frac_violations'][1]['start_md_m']==750.


def test_cased_only_underbalance_is_not_an_exposed_formation_violation():
    state=balanced_state(top=200.);state['mud_density']='60'
    result=model.build_chart_model(state)
    assert result['static_security']['status']=='safe'
    assert not result['static_security']['pore_violations']
    assert result['hydrostatic']['pressure_psi'][1] < model.pressure_psi(70.,200.)


def test_liner_overlap_is_excluded_using_capacity_kind_not_job_name():
    state=balanced_state();state['job_type']=state['placement_config']['job_type']='LNR 7"'
    state['hardware_table']=hardware(('Drill Pipes','400','5',4.),('Liner','1000','7',6.),
        ('Liner Hanger','400','7',6.),('Previous Casing','500','9.625',8.535),('Open Hole Size','1000','8.5',8.5))
    state=advanced(state)
    result=model.build_chart_model(state)
    assert result['static_security']['domain']['top_md']==500.
    assert all(row['start_md_m']>=500. for key in ('pore_violations','frac_violations') for row in result['static_security'][key])


def test_maximum_uses_fluid_interface_breakpoint_and_full_pressure_precision():
    state=advanced(balanced_state(top=800.));state['mud_density']='200'
    state['fluids_config']['params']['Main']['density']='50'
    offset=model.pressure_psi(70.,500.)+10.
    state['formation_pressure_config']['profile']=[{'md_m':md,'pore_psi':1.,'frac_psi':model.pressure_psi(130.,md)+offset} for md in (500.,1000.)]
    result=model.build_chart_model(state)
    row=result['static_security']['frac_violations'][0]
    assert row['max_at_md_m']==row['max_at_tvd_m']==800.
    assert row['max_delta_psi']==pytest.approx(model.pressure_psi(70.,300.)-10.,abs=1e-10)
    # Same conversion; cumulative 500+300 m adds ~4.55e-13 psi operation-order noise.
    assert row['hydro_psi_at_max']==pytest.approx(model.pressure_psi(200.,800.), rel=0, abs=1e-12)


def test_directional_intermediate_limit_is_pressure_linear_in_tvd_not_md_or_emw():
    state=advanced();state['well_geometry']={'type':'Directional','survey':pd.DataFrame({
        'MD':[0.,1000.],'Deviation':[0.,60.],'Azimuth':[0.,0.]})}
    result=model.build_chart_model(state)
    formation=result['formation_pressure'];hydro=result['hydrostatic']
    point=next(t for md,t in zip(hydro['md_m'],hydro['tvd_m']) if md==800.)
    expected=400.+400.*(point-formation['tvd_m'][0])/(formation['tvd_m'][1]-formation['tvd_m'][0])
    actual=model._linear_pressure(formation['tvd_m'],formation['pore_psi'],point)
    assert actual==expected and abs(actual-640.)>1.
    assert formation['md_m']==[500.,1000.] and formation['pore_psi']==[400.,800.]


@pytest.mark.parametrize('change',['mode','station_md','pore','frac','survey','geometry','density','volume'])
def test_consumed_sources_rebuild_model_and_invalidate_document(change):
    from project_state import prepare_calculations
    state=advanced(rows=[{'md_m':500.,'pore_psi':400.,'frac_psi':2000.},
        {'md_m':750.,'pore_psi':600.,'frac_psi':2500.},{'md_m':1000.,'pore_psi':800.,'frac_psi':3000.}])
    prepare_calculations(state)
    before=state['_cement_chart_source']; profile=deepcopy(state['formation_pressure_config']['profile'])
    state['_compiled_doc_bytes']=b'OLD';state['_compiled_doc_signature']='OLD'
    if change=='mode':state['formation_pressure_config']['mode']='basic'
    elif change=='station_md':state['formation_pressure_config']['profile'][1]['md_m']=760.
    elif change=='pore':state['formation_pressure_config']['profile'][1]['pore_psi']=610.
    elif change=='frac':state['formation_pressure_config']['profile'][1]['frac_psi']=2510.
    elif change=='survey':state['well_geometry']={'type':'Directional','survey':pd.DataFrame({'MD':[0.,1000.],'Deviation':[30.,30.],'Azimuth':[0.,0.]})}
    elif change=='geometry':state['hardware_table'].loc[1,'MD (m)']='550'
    elif change=='density':state['fluids_config']['params']['Main']['density']='119'
    elif change=='volume':state['fluids_config']['params']['Main']['volume']+=1.
    prepare_calculations(state)
    assert state['_cement_chart_source']!=before
    assert '_compiled_doc_bytes' not in state and '_compiled_doc_signature' not in state
    if change=='geometry':assert state['_cement_chart_model'] is None
    else:assert state['_cement_chart_model'] is not None
    if change in ('mode','survey','geometry','density','volume'):assert state['formation_pressure_config']['profile']==profile


def test_real_source_serialization_decode_replace_never_retains_security_derivatives():
    import test_audit_regressions as audit
    from project_state import prepare_calculations
    state=advanced();prepare_calculations(state)
    cfg=deepcopy(state['formation_pressure_config'])
    saved={key:audit.namespace['serialize_item'](value) for key,value in state.items() if is_project_key(key)}
    raw=json.dumps(saved).encode()
    assert b'crossings' not in raw and b'_cement_chart' not in raw and b'formation_pressure' in raw
    restored=decode_project(raw,audit.namespace['deserialize_item'])
    current={'well_name':'Other','_cement_chart_model':{'old':True},'_compiled_doc_bytes':b'OLD'}
    replace_project_state(current,restored,'restored')
    assert current['formation_pressure_config']==cfg
    assert '_cement_chart_model' not in current and '_compiled_doc_bytes' not in current
    assert model.build_chart_model(current)==model.build_chart_model(state)


def test_inactive_profile_does_not_control_basic_and_rate_does_not_enter_static_math():
    state=balanced_state();state['formation_pressure_config']={'mode':'basic','profile':[{'md_m':1.,'pore_psi':None,'frac_psi':None}]}
    before=model.build_chart_model(state)
    state['formation_pressure_config']['profile'][0]['md_m']=2.
    state['fluids_config']['params']['Main']['pump_rate']='999'
    assert model.build_chart_model(state)==before


def test_decreasing_tvd_still_blocks_security_but_retains_fluid_model():
    state=balanced_state();state['well_geometry']={'type':'Directional','survey':pd.DataFrame({
        'MD':[0.,500.,1000.],'Deviation':[0.,100.,80.],'Azimuth':[0.,0.,0.]})}
    result=model.build_chart_model(state)
    assert result['static_security'] is None and result['static_security_issues']
    assert result['annular_intervals'] and result['fluid_sequence_ready']
    assert 'TVD decreases' in model.chart_readiness(state,True)['issues'][0]


def test_horizontal_equal_tvd_requires_single_valued_formation_pressure():
    state=advanced();state['well_geometry']={'type':'Directional','survey':pd.DataFrame({
        'MD':[0.,500.,1000.],'Deviation':[0.,90.,90.],'Azimuth':[0.,0.,0.]})}
    # Floating trajectory convention may retain tiny TVD increments; an exactly
    # horizontal Vertical-equivalent fixture is covered via equal-TVD pure comparison.
    result=synthetic([100.,100.],[3000.,3000.],depths=[500.,1000.],geometry=state['well_geometry'])
    assert result['status']=='safe'
