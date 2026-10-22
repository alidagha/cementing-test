"""CT stages are report projections; cement and pumping remain single batches."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from unittest.mock import patch

import pandas as pd
import pytest
import materials_db as db
import engineering_tools as eng
import project_state as ps
import project_io
import phase_5_cement as phase5
import phase_10_procedure as report
import test_audit_regressions as audit
from test_round13b_b1_ct_foundation import state as foundation_state

CASE = audit.AuditRegressions()
D = Decimal


def state(volume=20, count=None, water=12, dead=2):
    s = foundation_state()
    s['fluids_config']['params']['Main']['volume'] = volume
    s['cement_params']['Main'].update(auto_calc=False)
    s['cement_params']['Main'].update({'yield': 1.36, 'mix_water': water,
        'dead_vol': dead, 'tank_name': db.get_tank_name(db.CT_JOB), 'total_sacks': 80.,
        'cmt_sg': eng.catalog_cement_sg(), 'cmt_sg_source': 'catalog'})
    s['material_property_schema'] = eng.MATERIAL_PROPERTY_SCHEMA
    s['cement_additives_dfs'] = {'Main': pd.DataFrame(columns=phase5.REQUIRED_ADDITIVE_COLUMNS)}
    ps.refresh_fluids(s)
    if count is not None:
        s['ct_stage_config'] = {'job_type': db.CT_JOB, 'main_volume': str(volume), 'count': count}
    return s


@pytest.mark.parametrize('volume,count,expected', [
    ('12.0',None,'12'), ('0.001',None,'0.001'), ('12.01',2,'6 + 6.01'),
    ('20.0',2,'10 + 10'), ('20.0',3,'7 + 7 + 6'),
    ('21.6',3,'7.2 + 7.2 + 7.2'), ('24.1',3,'8 + 8 + 8.1'),
    ('30',3,'10 + 10 + 10'), ('36',3,'12 + 12 + 12')])
def test_approved_allocations(volume, count, expected):
    from ct_stages import allocate_stages, decimal_text
    stages = allocate_stages(volume, count)
    assert ' + '.join(map(decimal_text, stages)) == expected
    assert sum(stages) == D(volume)
    assert all(0 < v <= 12 for v in stages)
    assert allocate_stages(volume, count) == stages


@pytest.mark.parametrize('volume,count,match', [
    ('12.01',None,'select'), ('24.1',2,'12 bbl'), ('36.01',2,'36 bbl'),
    ('36.01',3,'36 bbl'), (0,None,'positive'), (-1,None,'positive'),
    ('20-30',2,'finite'), ('NaN',2,'finite'), ('Infinity',2,'finite'),
    (True,2,'finite'), (20,1,'2 or 3'), (20,2.0,'2 or 3'),
    (20,'2','2 or 3'), (20,True,'2 or 3'), (12,2,'implicit')])
def test_invalid_allocation_is_controlled(volume, count, match):
    from ct_stages import allocate_stages
    with pytest.raises(ValueError, match=match):
        allocate_stages(volume, count)


@pytest.mark.parametrize('volume', ['12.00000000000000000000000000000001',
    '19.99999999999999999999999999999', '23.99999999999999999999999', '35.99999999999999999999999999999'])
def test_source_precision_and_decimal_context_are_preserved(volume):
    from ct_stages import allocate_stages
    count = 2 if D(volume) <= 24 else 3
    with localcontext() as ctx:
        ctx.prec = 6
        stages = allocate_stages(volume, count)
    assert sum(map(Fraction, stages)) == Fraction(D(volume))
    assert all(0 < x <= 12 for x in stages)


@pytest.mark.parametrize('volume,count,water,dead', [
    (20,3,12,2),(24.1,3,1.333333333333,0.0123456789),
    (36,3,0,0),(12,None,1.2345,2.3456),(20,2,.02,.03)])
def test_water_reconciles_display_and_preserves_sources(volume,count,water,dead):
    from ct_stages import ct_stage_projection
    s = state(volume,count,water,dead); before = deepcopy(s)
    p = ct_stage_projection(s)
    total = water + dead
    assert p['source_water_bbl'] == D(str(total))
    assert p['display_water_bbl'] == D(str(eng.round_half_up(total,1)))
    assert sum(p['water_bbl']) == p['display_water_bbl']
    for cement, share in zip(p['cement_bbl'], p['water_bbl']):
        exact = Fraction(p['display_water_bbl']) * Fraction(cement) / Fraction(D(str(volume)))
        assert abs(Fraction(share) - exact) < Fraction(1,10)
    assert s['cement_params'] == before['cement_params']
    assert s['fluids_config'] == before['fluids_config']
    if volume == 20 and count == 3:
        assert p['water_bbl'] == (D('4.9'),D('4.9'),D('4.2'))


def test_generated_note_and_future_projection_have_one_authority():
    from ct_stages import ct_stage_projection, stage_note
    s = state(20,3); base = deepcopy(s['cement_params']['Main'])
    assert phase5.refresh_cement_calculations(s) == []
    note = s['cement_note_Main']; p = ct_stage_projection(s)
    assert '14.0 bbl' in note and base['tank_name'] in note
    assert note.endswith(stage_note(p))
    assert '7 + 7 + 6' in note and '4.9 + 4.9 + 4.2' in note
    assert s['cement_params']['Main']['mix_water'] == 12
    assert s['total_pump_time_min'] == 20/.7+5


@pytest.mark.parametrize('auto', [False,True])
def test_stage_count_cannot_change_cement_or_lab_sources(auto):
    from ct_stages import ct_stage_projection
    s = state(20,2); s['cement_params']['Main']['auto_calc'] = auto
    assert phase5.refresh_cement_calculations(s) == []
    before = deepcopy(s)
    lab_sig = ps.lab_source_signature(s,'Main')
    s['ct_stage_config']['count'] = 3
    assert phase5.refresh_cement_calculations(s) == []
    assert s['cement_params'] == before['cement_params']
    assert ps.lab_source_signature(s,'Main') == lab_sig
    for key in ['cement_blend_Main','cement_calc_Main']:
        pd.testing.assert_frame_equal(s[key],before[key])
    assert s['fluid_data'] == before['fluid_data']
    assert s['cement_note_Main'] != before['cement_note_Main']
    assert ct_stage_projection(s)['source_main_bbl'] == D('20')


def test_readiness_and_stale_note_retirement():
    s = state(20)
    assert 'select' in eng.compute_phase_status(s)['phase5']['message'].lower()
    s['cement_note_Main'] = 'stale note'; s['_compiled_doc_bytes'] = b'old'
    issues = phase5.refresh_cement_calculations(s)
    assert any('stage' in issue.lower() for issue in issues)
    assert 'cement_note_Main' not in s and '_compiled_doc_bytes' not in s
    s['ct_stage_config'] = {'job_type':db.CT_JOB,'main_volume':'20','count':2}
    assert eng.compute_phase_status(s)['phase5']['level'] == 'ok'
    s['fluids_config']['params']['Main']['volume'] = 24.1
    assert 'stale' in eng.compute_phase_status(s)['phase5']['message'].lower()
    ps.refresh_fluids(s)
    assert 'ct_stage_config' not in s
    assert eng.compute_phase_status(s)['phase5']['level'] != 'ok'


@pytest.mark.parametrize('mutation', [
    [], {'count':2}, {'job_type':db.CT_JOB,'main_volume':'20','count':True},
    {'job_type':db.CT_JOB,'main_volume':'20','count':'2'},
    {'job_type':db.CT_JOB,'main_volume':'20','count':4},
    {'job_type':'CMT PLUG','main_volume':'20','count':2},
    {'job_type':db.CT_JOB,'main_volume':'21','count':2},
    {'job_type':db.CT_JOB,'main_volume':'20','count':2,'unexpected':1}])
def test_malformed_stage_import_rejected_before_atomic_publication(mutation):
    s = state(20); s['ct_stage_config'] = mutation
    published = {'well_name':'keep','_compiled_doc_bytes':b'keep'}
    before = deepcopy(published)
    raw = json.dumps({k:audit.namespace['serialize_item'](v) for k,v in s.items()}).encode()
    with pytest.raises(ValueError, match='CT.*stage'):
        prepared = project_io.decode_project(raw,audit.namespace['deserialize_item'])
        project_io.replace_project_state(published,prepared,'invalid')
    assert published == before


def test_valid_choice_roundtrip_and_project_isolation():
    from ct_stages import ct_stage_projection
    s = state(20,3); expected = ct_stage_projection(s)
    restored = audit.round_trip(s)
    assert ct_stage_projection(restored) == expected
    assert restored['ct_stage_config'] == s['ct_stage_config']
    fresh = audit.round_trip(foundation_state())
    assert 'ct_stage_config' not in fresh
    for key in ('cement_bbl','water_bbl','source_water_bbl'):
        assert key not in restored


def selector(app):
    found = [w for w in app.selectbox if w.label == 'Stage count - Main']
    assert len(found) == 1, 'CT Main stage selector is missing'
    return found[0]


def test_live_selector_navigation_thresholds_restore_and_job_switch():
    app = CASE.app(state(20)); CASE.phase(app,'phase5')
    w = selector(app)
    assert w.options == ['2 stages','3 stages'] and w.value is None
    w.set_value('3 stages')
    CASE.phase(app,'phase7')
    assert app.session_state['ct_stage_config']['count'] == 3
    restored = CASE.app(audit.round_trip(app.session_state.to_dict()))
    CASE.phase(restored,'phase5'); assert selector(restored).value == '3 stages'
    assert '7 + 7 + 6' in restored.session_state['cement_note_Main']
    CASE.phase(restored,'phase4')
    restored.number_input(key='vol_Main').set_value(24.1).run()
    assert 'ct_stage_config' not in restored.session_state
    CASE.phase(restored,'phase5'); assert selector(restored).value is None
    selector(restored).set_value('2 stages').run()
    assert any('12 bbl' in x.value for x in restored.error)
    assert selector(restored).value == '2 stages'
    assert 'cement_note_Main' not in restored.session_state
    selector(restored).set_value('3 stages').run()
    assert '8 + 8 + 8.1' in restored.session_state['cement_note_Main']
    CASE.phase(restored,'phase4'); restored.number_input(key='vol_Main').set_value(12.).run()
    CASE.phase(restored,'phase5')
    assert not any(w.label == 'Stage count - Main' for w in restored.selectbox)
    assert 'ct_stage_config' not in restored.session_state
    CASE.phase(restored,'phase4'); restored.number_input(key='vol_Main').set_value(20.).run()
    CASE.phase(restored,'phase5'); assert selector(restored).value is None
    selector(restored).set_value('2 stages').run()
    CASE.phase(restored,'phase1'); restored.selectbox(key='_w_job_type').set_value('CMT PLUG').run()
    assert 'ct_stage_config' not in restored.session_state
    CASE.phase(restored,'phase5')
    assert not any(w.label == 'Stage count - Main' for w in restored.selectbox)
    CASE.phase(restored,'phase1'); restored.selectbox(key='_w_job_type').set_value(db.CT_JOB).run()
    CASE.phase(restored,'phase5'); assert selector(restored).value is None


@pytest.mark.parametrize('volume,count', [(12,None),(12.01,None),(24.1,2),(36.01,None)])
def test_ui_capacity_and_single_stage_controls(volume,count):
    app = CASE.app(state(volume,count)); CASE.phase(app,'phase5')
    if volume <= 12:
        assert not any(w.label == 'Stage count - Main' for w in app.selectbox)
        assert eng.compute_phase_status(app.session_state)['phase5']['level'] == 'ok'
    else:
        assert eng.compute_phase_status(app.session_state)['phase5']['level'] != 'ok'
        assert 'cement_note_Main' not in app.session_state


@pytest.mark.parametrize('prepared',[False,True])
def test_b1_export_gate_remains_for_valid_stages(prepared):
    s = state(20,2); s['_compiled_doc_bytes'] = b'old'
    with patch.object(report.st,'session_state',s):
        with pytest.raises(ValueError,match='Phase VII'):
            report.build_master_context(calculations_prepared=prepared)
    assert '_compiled_doc_bytes' not in s


@pytest.mark.parametrize('job',[j for j in db.JOB_TYPES if j != db.CT_JOB])
def test_legacy_notes_remain_identical(job):
    s = state(20); s['job_type'] = job
    assert phase5.refresh_cement_calculations(s) == []
    p = s['cement_params']['Main']; result = phase5.calculate_base_results(p,20,118,[],[],0)
    assert s['cement_note_Main'] == phase5.build_cement_tables(p,s['cement_additives_dfs']['Main'],result)[2]
    assert 'ct_stage_config' not in s


def test_decimal_boundary_matrix_has_no_rounded_capacity_admission():
    from ct_stages import allocate_stages
    for units in range(1,3602):
        total = D(units) / 100
        for count in (None,2,3):
            valid = ((total <= 12 and count is None)
                     or (12 < total <= 12 * (count or 0) and count in (2,3)))
            if valid:
                values = allocate_stages(total,count)
                assert sum(map(Fraction,values)) == Fraction(total)
                assert all(0 < x <= 12 for x in values)
            else:
                with pytest.raises(ValueError):
                    allocate_stages(total,count)


@pytest.mark.parametrize('change',['inactive','job','invalid_volume','threshold','new_volume'])
def test_transition_retires_only_stage_choice_and_note(change):
    s = state(20,3); original = deepcopy(s['cement_params'])
    s['cement_note_Main'] = 'stale'; s['_compiled_doc_bytes'] = b'old'
    if change == 'inactive': s['fluids_config']['active'].remove('Main')
    if change == 'job': s['job_type'] = 'CMT PLUG'
    if change in ('invalid_volume','threshold','new_volume'):
        s['fluids_config']['params']['Main']['volume'] = {'invalid_volume':None,'threshold':12,'new_volume':21}[change]
    ps.restore_canonical_fields(s)
    assert 'ct_stage_config' not in s and 'cement_note_Main' not in s
    assert '_compiled_doc_bytes' not in s
    assert s['cement_params'] == original
    if change == 'invalid_volume':
        s['fluids_config']['params']['Main']['volume'] = 20
        with pytest.raises(ValueError,match='select'):
            from ct_stages import ct_stage_projection
            ct_stage_projection(s)


@pytest.mark.parametrize('field,value',[('dead_vol',None),('mix_water',None)])
def test_invalid_water_cannot_leave_a_previous_note(field,value):
    s = state(20,2); assert phase5.refresh_cement_calculations(s) == []
    s['_compiled_doc_bytes'] = b'old'; s['cement_params']['Main'][field] = value
    assert phase5.refresh_cement_calculations(s)
    assert 'cement_note_Main' not in s and '_compiled_doc_bytes' not in s


def test_stage_and_water_callbacks_retire_notes_without_changing_review():
    s = state(20,2); s['lab_qc_params'] = {'Main':{'reviewed':True,'review_signature':'review'}}
    for field,value in [('dead_vol',3.),('tank_name','Cement Unit Tanks')]:
        s['cement_note_Main'] = 'stale'; s['_compiled_doc_bytes'] = b'old'; s['_test_edit'] = value
        with patch.object(phase5.st,'session_state',s):
            phase5._commit_cement_param('Main',field,'_test_edit')
        assert 'cement_note_Main' not in s and '_compiled_doc_bytes' not in s
        assert s['lab_qc_params']['Main']['review_signature'] == 'review'
    s['cement_note_Main'] = 'stale'; s['_compiled_doc_bytes'] = b'old'; s['_test_edit'] = '3 stages'
    before = deepcopy(s['cement_params'])
    with patch.object(phase5.st,'session_state',s): phase5._commit_ct_stage_count('_test_edit')
    assert s['ct_stage_config']['count'] == 3
    assert s['cement_params'] == before
    assert 'cement_note_Main' not in s and '_compiled_doc_bytes' not in s
    assert s['lab_qc_params']['Main']['reviewed']


def test_real_prepare_download_serialization_and_transactional_restore(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    offered = []; native = st.download_button
    def observe(**kwargs):
        offered.append(kwargs)
        return native(**kwargs)
    monkeypatch.setattr(st,'download_button',observe)
    app = CASE.app(state(20)); CASE.phase(app,'phase5')
    selector(app).set_value('3 stages').run()
    next(b for b in app.button if b.label == 'Prepare project download').click().run()
    CASE.healthy(app); assert len(app.get('download_button')) == 1
    raw = offered[-1]['data'].encode()
    project = project_io.decode_project(raw,audit.namespace['deserialize_item'])
    assert project['ct_stage_config'] == {'job_type':db.CT_JOB,'main_volume':'20','count':3}
    assert not any(k.startswith('_ct_stage') for k in project)
    restored = AppTest.from_file(str(audit.ROOT/'main.py'),default_timeout=30)
    project_io.replace_project_state(restored.session_state,project,project_io.content_signature(raw))
    restored.run(); CASE.healthy(restored); CASE.phase(restored,'phase5')
    assert selector(restored).value == '3 stages'
    assert restored.session_state['cement_note_Main'] == app.session_state['cement_note_Main']


@pytest.mark.parametrize('count',[None,2.0,1,-1])
def test_additional_malformed_count_json_rejected(count):
    s = state(20,2); s['ct_stage_config']['count'] = count
    with pytest.raises(ValueError,match='CT stages'):
        audit.round_trip(s)


@pytest.mark.parametrize('source',['NaN','20-21','wrong'])
def test_bad_stage_source_json_rejected(source):
    s = state(20,2); s['ct_stage_config']['main_volume'] = source
    with pytest.raises(ValueError,match='CT stages'):
        audit.round_trip(s)


def test_near_capacity_residual_is_distributed_without_exceeding_limit():
    from ct_stages import allocate_stages
    assert allocate_stages('35.81',3) == (D('12'),D('11.9'),D('11.91'))


def test_implicit_note_is_retired_on_volume_edit_and_canonical_rebuild():
    s = state(12); assert phase5.refresh_cement_calculations(s) == []
    s['_compiled_doc_bytes'] = b'old'
    s['fluids_config']['params']['Main']['volume'] = 11
    ps.refresh_fluids(s)
    assert 'cement_note_Main' not in s and '_compiled_doc_bytes' not in s
    app = CASE.app(state(12)); CASE.phase(app,'phase5')
    assert 'cement_note_Main' in app.session_state
    CASE.phase(app,'phase4'); app.number_input(key='vol_Main').set_value(11.).run()
    assert 'cement_note_Main' not in app.session_state
    CASE.phase(app,'phase5')
    assert 'Main cement stages (bbl): 11.' in app.session_state['cement_note_Main']


@pytest.mark.parametrize('field,value',[('fluids_config',[]),('fluids_config',{'active':['Main'],'params':[]}),
    ('fluids_config',{'active':['Main'],'params':{'Main':[]}})])
def test_stage_admission_preserves_existing_malformed_container_diagnostics(field,value):
    s = state(20,2); s[field] = value
    with pytest.raises(ValueError,match='fluids_config'):
        audit.round_trip(s)


@pytest.mark.parametrize('canonical,cached',[(12,20),(20,12)])
def test_selector_threshold_uses_canonical_main_not_restored_derived_cache(canonical,cached):
    s = state(canonical)
    s['fluid_data']['Main']['volume'] = cached
    app = CASE.app(audit.round_trip(s)); CASE.phase(app,'phase5')
    controls = [w for w in app.selectbox if w.label == 'Stage count - Main']
    assert len(controls) == (1 if canonical > 12 else 0)
    if controls: assert controls[0].value is None
