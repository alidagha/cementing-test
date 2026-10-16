"""B-2 active-source readiness, native row editing and live security lifecycle."""
from copy import deepcopy
import json

import pandas as pd
import pytest

import cement_chart_model as model
from project_io import decode_project, replace_project_state
from project_state import fingerprint
from test_uat_round8a_chart_model import balanced_state


BAD_DRAFTS = [
    [{'md_m':500.,'pore_psi':400.,'frac_psi':2000.},{'md_m':500.,'pore_psi':600.,'frac_psi':2500.},{'md_m':1000.,'pore_psi':800.,'frac_psi':3000.}],
    [{'md_m':500.,'pore_psi':2000.,'frac_psi':400.},{'md_m':1000.,'pore_psi':800.,'frac_psi':3000.}],
    [{'md_m':500.,'pore_psi':None,'frac_psi':None},{'md_m':None,'pore_psi':None,'frac_psi':None}],
    [{'md_m':900.,'pore_psi':400.,'frac_psi':2000.},{'md_m':600.,'pore_psi':600.,'frac_psi':2500.}],
]


@pytest.mark.parametrize('profile',BAD_DRAFTS)
def test_active_basic_ignores_invalid_inactive_draft_without_mutation(profile):
    state=balanced_state(); expected=model.build_chart_model(state)
    state['formation_pressure_config']={'mode':'basic','profile':deepcopy(profile)}
    before=fingerprint(profile);source=model.formation_source(state)
    for _ in range(2):
        ready=model.chart_readiness(state,True)
        assert not ready['issues'] and ready['model']==expected
        assert model.formation_source(state)==source
        state['formation_pressure_config']['mode']='advanced'
        assert model.chart_readiness(state,True)['issues']
        state['formation_pressure_config']['mode']='basic'
        assert fingerprint(state['formation_pressure_config']['profile'])==before
    if profile is not BAD_DRAFTS[2]:
        with pytest.raises(ValueError):model.validate_formation_pressure_config(state['formation_pressure_config'])


@pytest.mark.parametrize('config',[None,[],{}, {'mode':'basic','profile':{}}, {'mode':'bad','profile':[]}, {'mode':'basic','profile':[],'unknown':1}])
def test_malformed_top_level_still_blocks_active_readiness(config):
    state=balanced_state();state['formation_pressure_config']=config
    assert model.chart_readiness(state,True)['issues']


@pytest.mark.parametrize('profile',[BAD_DRAFTS[0],BAD_DRAFTS[1],BAD_DRAFTS[3]])
def test_inactive_semantic_errors_remain_strict_at_project_load(profile):
    config={'mode':'basic','profile':profile}
    current={'well_name':'Current','_compiled_doc_bytes':b'current'};before=deepcopy(current)
    with pytest.raises(ValueError):
        decoded=decode_project(json.dumps({'well_name':'Bad','formation_pressure_config':config}).encode(),lambda x:x)
        replace_project_state(current,decoded,'bad')
    assert current==before


SAFE='Static Well Security: SAFE — Hydrostatic pressure remains within the Pore–Fracture window throughout the current open-hole interval.'


def application(state=None, phase='phase2_3'):
    import test_audit_regressions as audit
    case=audit.AuditRegressions();app=case.app(balanced_state() if state is None else state)
    case.phase(app,phase)
    return case,app


def selection(app):
    return next(w for w in app.selectbox if w.label=='Formation Pressure Mode')


def number(app,label):
    return next(w for w in app.number_input if w.label==label)


def configured_profile():
    return {'mode':'advanced','profile':[
        {'md_m':500.,'pore_psi':400.,'frac_psi':2000.},
        {'md_m':650.,'pore_psi':550.,'frac_psi':2300.},
        {'md_m':1000.,'pore_psi':800.,'frac_psi':3000.}]}


def test_native_default_basic_and_explicit_mode_preserve_both_drafts():
    case,app=application()
    assert selection(app).value=='basic'
    assert 'formation_pressure_config' not in app.session_state
    assert any(w.label=='Pore Gradient (pcf EMW)' for w in app.number_input)
    assert not any('Pore Pressure (psig)' in w.label for w in app.number_input)
    basic=(app.session_state['pore_gradient_emw_pcf'],app.session_state['frac_gradient_emw_pcf'])
    selection(app).set_value('advanced').run()
    assert app.session_state['formation_pressure_config']['profile']==[
        {'md_m':500.,'pore_psi':None,'frac_psi':None}, {'md_m':1000.,'pore_psi':None,'frac_psi':None}]
    number(app,'Pore Pressure (psig) — Top endpoint').set_value(401.)
    case.phase(app,'phase4');case.phase(app,'phase2_3')
    assert number(app,'Pore Pressure (psig) — Top endpoint').value==401.
    draft=deepcopy(app.session_state['formation_pressure_config']['profile'])
    selection(app).set_value('basic').run()
    assert (app.session_state['pore_gradient_emw_pcf'],app.session_state['frac_gradient_emw_pcf'])==basic
    selection(app).set_value('advanced').run()
    assert app.session_state['formation_pressure_config']['profile']==draft
    case.healthy(app)


def test_endpoint_lock_readonly_tvd_add_edit_delete_and_invalid_station_retained():
    case,app=application();selection(app).set_value('advanced').run()
    assert not any(w.label.startswith(('MD (m) — Top','MD (m) — Bottom','TVD (m)')) for w in app.number_input)
    assert not any(w.label.startswith(('Remove Top','Remove Bottom')) for w in app.button)
    next(b for b in app.button if b.label=='Add station below Top endpoint').click().run()
    number(app,'MD (m) — Station 2').set_value(500.).run()
    assert app.session_state['formation_pressure_config']['profile'][1]['md_m']==500.
    assert any('strictly increasing' in w.value for w in app.warning)
    selection(app).set_value('basic').run()
    assert model.chart_readiness(app.session_state,True)['model'] is not None
    selection(app).set_value('advanced').run()
    assert app.session_state['formation_pressure_config']['profile'][1]['md_m']==500.
    number(app,'MD (m) — Station 2').set_value(700.)
    case.phase(app,'phase1');case.phase(app,'phase2_3')
    assert number(app,'MD (m) — Station 2').value==700.
    next(b for b in app.button if b.label=='Remove Station 2').click().run()
    assert [r['md_m'] for r in app.session_state['formation_pressure_config']['profile']]==[500.,1000.]


def test_domain_accessor_is_readonly_delegation_and_lifecycle_does_not_sort(monkeypatch):
    from project_state import reconcile_formation_profile
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    before=fingerprint(state);real=model._security_domain;calls=[]
    def observe(g,t):calls.append(1);return real(g,t)
    monkeypatch.setattr(model,'_security_domain',observe)
    assert model.current_open_hole_domain(state)['top_md']==500.
    assert calls==[1] and fingerprint(state)==before
    reconcile_formation_profile(state)
    state['formation_pressure_config']['profile'].insert(2,{'md_m':600.,'pore_psi':510.,'frac_psi':2200.})
    draft=deepcopy(state['formation_pressure_config']['profile'])
    reconcile_formation_profile(state)
    assert state['formation_pressure_config']['profile']==draft
    assert model.chart_readiness(state,True)['issues']


def test_hardware_endpoint_change_keeps_interior_and_unchanged_endpoint_only():
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    state['formation_pressure_config']['profile'].insert(1,{'md_m':550.,'pore_psi':450.,'frac_psi':2100.})
    case,app=application(state)
    case.hardware_event(app,{'edited_rows':{'1':{'MD (m)':'600'}}})
    rows=app.session_state['formation_pressure_config']['profile']
    assert rows==[{'md_m':600.,'pore_psi':None,'frac_psi':None}, configured_profile()['profile'][1],configured_profile()['profile'][-1]]
    assert model.chart_readiness(app.session_state,True)['issues']
    assert not any(r['md_m'] in (500.,550.) for r in rows)


def test_survey_edit_retains_sources_and_rebuilds_readonly_tvd():
    import well_profile
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    case,app=application(state);before=deepcopy(app.session_state['formation_pressure_config'])
    app.session_state['well_geometry']['survey']=pd.DataFrame({'MD':[0.,1000.],'Deviation':[30.,30.],'Azimuth':[0.,0.]})
    app.selectbox(key='_w_geometry_type').set_value('Directional').run()
    assert app.session_state['formation_pressure_config']==before
    tvds=well_profile.tvd_at_md(app.session_state['well_geometry'],[500.,650.,1000.])
    assert all(any(f'{tvd:.1f}'==text.value for text in app.text) for tvd in tvds)
    assert model.chart_readiness(app.session_state,True)['model']['formation_pressure']['tvd_m']==tvds


@pytest.mark.parametrize('phase',['phase2_3','phase4'])
def test_live_safe_unsafe_and_neutral_states_consume_current_core(phase):
    case,app=application(phase=phase)
    assert any(s.value==SAFE for s in app.success)
    if phase=='phase2_3':
        number(app,'Fracture Gradient (pcf EMW)').set_value(81.).run()
    else:
        app.text_input(key='den_Main').set_value('1000').run()
    core=model.chart_readiness(app.session_state,True)
    assert not core['issues'] and core['model']['static_security']['frac_violations']
    assert any('Risk of formation breakdown / lost circulation' in w.value for w in app.warning)
    state=balanced_state();state['fluids_config']['active']=['Displacement Fluid']
    _,empty=application(state,phase)
    assert any('Static Well Security is not available yet.' in i.value for i in empty.info)
    assert not any(s.value==SAFE for s in empty.success)


def test_phase4_density_volume_change_live_without_navigation_rate_is_irrelevant():
    _,app=application(phase='phase4')
    original=model.chart_readiness(app.session_state,True)['model']
    app.text_input(key='den_Main').set_value('150').run()
    dense=model.chart_readiness(app.session_state,True)['model']
    assert dense['hydrostatic']!=original['hydrostatic']
    app.number_input(key='vol_Main').set_value(app.session_state['fluids_config']['params']['Main']['volume']+5.).run()
    larger=model.chart_readiness(app.session_state,True)['model']
    assert larger['hydrostatic']!=dense['hydrostatic']
    app.text_input(key='rate_Main').set_value('12').run()
    assert model.chart_readiness(app.session_state,True)['model']==larger
    assert app.radio(key='_app_mode_key').value=='phase4'


@pytest.mark.parametrize('boundary',['frac','pore'])
def test_all_prepared_violations_and_contacts_are_presented_without_new_math(boundary):
    state=balanced_state();base=model.build_chart_model(state);h=base['hydrostatic']
    rows=[]
    for md,delta in zip([500.,625.,750.,875.,1000.],[-100.,100.,-100.,100.,-100.]):
        hydro=model._linear_pressure(h['tvd_m'],h['pressure_psi'],md)
        rows.append({'md_m':md,'pore_psi':hydro+delta if boundary=='pore' else 1.,
                     'frac_psi':hydro+200. if boundary=='pore' else hydro-delta})
    state['formation_pressure_config']={'mode':'advanced','profile':rows}
    _,app=application(state,'phase4')
    security=model.chart_readiness(app.session_state,True)['model']['static_security']
    label='Fracture limit exceeded' if boundary=='frac' else 'Underbalance detected'
    warnings=[w.value for w in app.warning if w.value.startswith(label)]
    assert len(warnings)==len(security[boundary+'_violations'])==2
    for row,text in zip(security[boundary+'_violations'],warnings):
        assert f"{row['start_md_m']:.1f}" in text and f"{row['max_at_tvd_m']:.1f}" in text
    frame=next(d.value for d in app.dataframe if 'Boundary' in d.value.columns)
    assert frame['MD (m)'].tolist()==[f"{r['md_m']:.1f}" for r in security['crossings']]
    assert frame['Pressure (psi)'].tolist()==[f"{r['pressure_psi']:.0f}" for r in security['crossings']]


def test_current_callbacks_invalidate_immediately_and_retired_callbacks_do_nothing(monkeypatch):
    import formation_pressure_ui as ui
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    from project_state import reconcile_formation_profile
    reconcile_formation_profile(state);epoch=state.get('_formation_epoch',0)
    state['_compiled_doc_bytes']=b'old';state['cell']=600.
    monkeypatch.setattr(ui.st,'session_state',state)
    ui._commit_station(1,'md_m','cell',epoch)
    assert '_compiled_doc_bytes' not in state and state['formation_pressure_config']['profile'][1]['md_m']==600.
    before=deepcopy(state['formation_pressure_config']);state['cell']=700.
    ui._commit_station(1,'md_m','cell',epoch-1)
    ui._commit_station(0,'md_m','cell',epoch)
    assert state['formation_pressure_config']==before


def test_valid_drafts_restore_exactly_without_transient_domain_or_tvd():
    import test_audit_regressions as audit
    state=balanced_state();state['formation_pressure_config']=configured_profile();state['formation_pressure_config']['mode']='basic'
    case,app=application(state)
    restored=audit.round_trip(app.session_state.to_dict())
    assert restored['formation_pressure_config']==state['formation_pressure_config']
    assert set(restored['formation_pressure_config']['profile'][0])=={'md_m','pore_psi','frac_psi'}
    assert not any(k.startswith('_formation') for k in restored)
    case,new=application(restored);selection(new).set_value('advanced').run()
    assert new.session_state['formation_pressure_config']['profile']==state['formation_pressure_config']['profile']
    assert (new.session_state['pore_gradient_emw_pcf'],new.session_state['frac_gradient_emw_pcf'])==(70.,160.)


@pytest.mark.parametrize('job',['CMT PLUG','CMT SQUEEZE'])
@pytest.mark.parametrize('phase',['phase2_3','phase4'])
def test_special_jobs_show_na_without_formation_controls(job,phase):
    state=balanced_state();state['job_type']=job;state['placement_config']['job_type']=job
    _,app=application(state,phase)
    assert not any(w.label=='Formation Pressure Mode' for w in app.selectbox)
    assert any('Static Well Security: Not applicable' in i.value for i in app.info)


def test_pending_browser_edits_survive_mode_and_structural_callbacks():
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    case,app=application(state)
    number(app,'Pore Pressure (psig) — Station 2').set_value(559.)
    next(b for b in app.button if b.label=='Add station below Top endpoint').click().run()
    assert app.session_state['formation_pressure_config']['profile'][2]['pore_psi']==559.
    next(b for b in app.button if b.label=='Remove Station 2').click().run()
    number(app,'Fracture Pressure (psig) — Station 2').set_value(2399.)
    selection(app).set_value('basic').run()
    assert app.session_state['formation_pressure_config']['profile'][1]['frac_psi']==2399.
    selection(app).set_value('advanced').run()
    assert number(app,'Fracture Pressure (psig) — Station 2').value==2399.


@pytest.mark.parametrize('top,bottom',[(450.,1000.),(500.,1100.),(600.,1100.)])
def test_reconciled_boundaries_do_not_copy_old_endpoint_pressures(top,bottom):
    from project_state import reconcile_formation_profile
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    original=deepcopy(state['formation_pressure_config']['profile'])
    reconcile_formation_profile(state)
    state['hardware_table'].loc[1,'MD (m)']=str(top)
    state['hardware_table'].loc[0,'MD (m)']=str(bottom)
    state['hardware_table'].loc[2,'MD (m)']=str(bottom)
    state['placement_config']['manual_depth_m']=bottom
    state['well_geometry']['td_m']=bottom
    state['_compiled_doc_bytes']=b'old'
    reconcile_formation_profile(state)
    rows=state['formation_pressure_config']['profile']
    assert rows[0]==(original[0] if top==500. else {'md_m':top,'pore_psi':None,'frac_psi':None})
    assert rows[-1]==(original[-1] if bottom==1000. else {'md_m':bottom,'pore_psi':None,'frac_psi':None})
    assert rows[1:-1]==[original[1]]
    assert '_compiled_doc_bytes' not in state
    assert model.chart_readiness(state,True)['issues']


@pytest.mark.parametrize('phase',['phase2_3','phase4'])
def test_tieback_advanced_is_unavailable_and_draft_is_not_erased(phase):
    from test_uat_round8a_chart_model import hardware
    from placement import hardware_choices
    state=balanced_state();state['job_type']=state['placement_config']['job_type']='TIE BACK LNR 7"'
    state['hardware_table']=hardware(('Tie Back','1000','7',6.276),('Previous Casing','1200','9.625',8.535))
    state['placement_config']['host_row']=next(iter(hardware_choices(state['hardware_table'],{'Previous Casing'})))
    state['formation_pressure_config']=configured_profile()
    draft=deepcopy(state['formation_pressure_config'])
    case,app=application(state,phase)
    assert app.session_state['formation_pressure_config']==draft
    assert not any(w.label.startswith('Pore Pressure (psig)') for w in app.number_input)
    assert not any(s.value==SAFE for s in app.success)
    assert any(i.value=='Advanced Formation Profile is not applicable because no current open-hole interval is exposed for this job.' for i in app.info)
    if phase=='phase2_3':
        selection(app).set_value('basic').run()
        assert model.chart_readiness(app.session_state,True)['model']['pore_frac']['kind']=='markers'
        assert app.session_state['formation_pressure_config']['profile']==draft['profile']
    else:
        assert any('no Current Open Hole' in w.value for w in app.warning)


@pytest.mark.parametrize('field,value',[('md_m',700.),('pore_psi',560.),('frac_psi',2400.)])
def test_each_advanced_edit_invalidates_compiled_document_and_source(field,value,monkeypatch):
    import formation_pressure_ui as ui
    from project_state import reconcile_formation_profile
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    reconcile_formation_profile(state);epoch=state.get('_formation_epoch',0)
    source=fingerprint(model.formation_source(state));state['_compiled_doc_bytes']=b'old';state['_compiled_doc_signature']='old'
    state['cell']=value;monkeypatch.setattr(ui.st,'session_state',state)
    ui._commit_station(1,field,'cell',epoch)
    assert '_compiled_doc_bytes' not in state and '_compiled_doc_signature' not in state
    assert fingerprint(model.formation_source(state))!=source


def test_explicit_mode_callback_invalidates_without_changing_either_draft(monkeypatch):
    import formation_pressure_ui as ui
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    profile=deepcopy(state['formation_pressure_config']['profile']);state['mode']='basic'
    state['_compiled_doc_bytes']=b'old';monkeypatch.setattr(ui.st,'session_state',state)
    ui._commit_mode('mode')
    assert '_compiled_doc_bytes' not in state and state['formation_pressure_config']['mode']=='basic'
    assert state['formation_pressure_config']['profile']==profile
    assert (state['pore_gradient_emw_pcf'],state['frac_gradient_emw_pcf'])==(70.,160.)


@pytest.mark.parametrize('mode',['basic','advanced'])
def test_real_decode_replace_restores_exact_sources_and_rebuilds_tvd_only(mode):
    import test_audit_regressions as audit
    state=balanced_state();state['formation_pressure_config']=configured_profile();state['formation_pressure_config']['mode']=mode
    _,app=application(state)
    saved={key:audit.namespace['serialize_item'](value) for key,value in app.session_state.to_dict().items() if audit.is_project_key(key)}
    raw=json.dumps(saved,allow_nan=False).encode()
    assert not any(k.startswith('_') for k in saved)
    assert b'static_security' not in raw and b'_formation' not in raw
    decoded=decode_project(raw,audit.namespace['deserialize_item'])
    current={'well_name':'Other','_formation_domain':(1.,2.),'_compiled_doc_bytes':b'old'}
    replace_project_state(current,decoded,'restored')
    assert current['formation_pressure_config']==state['formation_pressure_config']
    assert '_compiled_doc_bytes' not in current and '_formation_domain' not in current
    _,restored=application(current)
    assert selection(restored).value==mode
    if mode=='advanced':
        assert number(restored,'Pore Pressure (psig) — Top endpoint').value==400.
        assert model.chart_readiness(restored.session_state,True)['model']['formation_pressure']['tvd_m']==[500.,650.,1000.]


def test_underbalance_risk_and_maximum_are_shown_from_prepared_records():
    state=balanced_state();state['formation_pressure_config']=configured_profile()
    for row in state['formation_pressure_config']['profile']:
        row['pore_psi']=2500.;row['frac_psi']=3500.
    _,app=application(state,'phase4')
    security=model.chart_readiness(app.session_state,True)['model']['static_security']
    warnings=[w.value for w in app.warning if w.value.startswith('Underbalance detected')]
    assert len(warnings)==len(security['pore_violations'])
    for text,row in zip(warnings,security['pore_violations']):
        assert f"{row['max_delta_psi']:.0f} psi" in text
        assert f"TVD {row['max_at_tvd_m']:.1f} m" in text
        assert 'Risk of formation influx / well flow.' in text


def test_empty_phase4_and_unsafe_phase_status_remain_controlled():
    state=balanced_state();state['fluids_config']['active']=[]
    _,app=application(state,'phase4')
    assert any('Static Well Security is not available yet.' in i.value for i in app.info)
    from engineering_tools import compute_phase_status
    state=balanced_state();state['frac_gradient_emw_pcf']=81.
    _,app=application(state)
    result=model.chart_readiness(app.session_state,True)
    assert not result['issues'] and result['model']['static_security']['status']=='warning'
    assert compute_phase_status(app.session_state)['phase2_3']['level']=='ok'


def test_liner_editor_locks_open_hole_endpoints_instead_of_overlap_hanger():
    from test_uat_round8a_chart_model import hardware
    state=balanced_state();state['job_type']=state['placement_config']['job_type']='LNR 7"'
    state['hardware_table']=hardware(('Drill Pipes','400','5',4.),('Liner','1000','7',6.),
        ('Liner Hanger','400','7',6.),('Previous Casing','500','9.625',8.535),('Open Hole Size','1000','8.5',8.5))
    state['formation_pressure_config']={'mode':'advanced','profile':[]}
    _,app=application(state)
    assert [r['md_m'] for r in app.session_state['formation_pressure_config']['profile']]==[500.,1000.]
    assert not any(w.label.startswith(('MD (m) — Top','MD (m) — Bottom')) for w in app.number_input)


def test_incomplete_saved_interior_station_is_not_mistaken_for_an_old_endpoint():
    import test_audit_regressions as audit
    row={'md_m':750.,'pore_psi':600.,'frac_psi':2500.}
    state=balanced_state();state['formation_pressure_config']={'mode':'advanced','profile':[row]}
    restored=audit.round_trip(state)
    _,app=application(restored)
    assert app.session_state['formation_pressure_config']['profile']==[
        {'md_m':500.,'pore_psi':None,'frac_psi':None}, row,
        {'md_m':1000.,'pore_psi':None,'frac_psi':None}]
    assert model.chart_readiness(app.session_state,True)['issues']
