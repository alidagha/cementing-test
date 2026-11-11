"""ROUND15 measured reference and explicitly synthetic geometry prerequisites."""
from copy import deepcopy
import math
import pickle

import pandas as pd
import pytest

import cement_chart_model as chart
import centralizer_adapter
import pumping_simulation
from engineering_tools import BBL_TO_CUFT
from placement import hardware_choices, target_descriptions


def r18c_tapered_state(previous_top=0., expanding=False):
    """Synthetic measured previous string; no product or reviewed-lab claim."""
    state = r18b_previous_state(previous_top=previous_top)
    table = state['hardware_table']
    table.at[4,'MD (m)'] = '150'
    extra = table.iloc[[4]].copy()
    extra['MD (m)'] = '150-300';extra['Size (in)'] = '6.5';extra['ID (in)'] = 5.8
    if expanding:
        table.at[3,'Size (in)'] = table.at[4,'Size (in)'] = '6.5'
        table.at[4,'ID (in)'] = 5.8
        extra['Size (in)'] = '7';extra['ID (in)'] = 6.094
    state['hardware_table'] = pd.concat([table.iloc[:5],extra,table.iloc[5:]],ignore_index=True)
    return state


@pytest.mark.parametrize('previous_top,expanding',[(0.,False),(100.,False),(0.,True),(100.,True)])
def test_r18c_one_tapered_previous_string_projects_all_measured_sections(previous_top,expanding):
    import installed_geometry as installed
    import well_schematic_adapter as schematic
    state = r18c_tapered_state(previous_top,expanding)
    before = pickle.dumps(state)
    physical = next(s for s in installed.physical_strings(state['hardware_table'].to_dict('records'),
        chart._segments,{'Previous Casing','Previous Liner Shoe'}) if s['description']=='Previous Tie Back Liner Shoe')
    drawing = schematic.prepare_schematic(state)
    previous = [c for c in drawing['casings'] if c['type']=='tieback' and c['shoe_md']==300.]
    assert len(previous)==1
    assert previous[0]['top_md']==previous_top
    assert previous[0]['sections']==[{'top_md':s['top_md'],'shoe_md':s['bottom_md'],
        'size_in':s['od_in'],'id_in':s['id_in']} for s in physical['sections']]
    host = drawing['casings'][previous[0]['host_index']]
    receiver = drawing['casings'][previous[0]['landing_liner_index']]
    assert host['type']=='casing' and host['size_in']==9.625 and host['id_in']==8.535
    assert receiver['type']=='liner' and (receiver['top_md'],receiver['shoe_md'])==(300.,1000.)
    assert len([c for c in drawing['casings'] if c['type']=='tieback'])==2
    assert centralizer_adapter.to_engine_geometry(state)['wellbore']['string_top']==400.
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('expanding',[False,True])
def test_r18c_real_png_has_connected_measured_taper_walls_and_boundary_labels(expanding,tmp_path,monkeypatch):
    import well_schematic_adapter as schematic
    import well_schematic_engine as engine
    from matplotlib.axes import Axes
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Polygon
    from PIL import Image
    state = r18c_tapered_state(100.,expanding)
    before = pickle.dumps(state)
    drawing = schematic.prepare_schematic(state)
    walls=[];original=Axes.add_patch
    def capture(ax,patch):
        if isinstance(patch,Polygon) and patch.get_zorder()==3.0 and patch.get_facecolor()==to_rgba(engine.C_TUBULAR_FILL):
            walls.append(patch.get_xy().copy())
        return original(ax,patch)
    monkeypatch.setattr(Axes,'add_patch',capture)
    path=tmp_path/'measured-taper.png'
    engine.render_well_schematic(drawing,str(path),dpi=150,strict=True)
    assert len(walls)==2  # One connected polygon per side of one previous string.
    geo=engine.layout_geometry();c1,c2,_=geo['col_frac'];body=1-geo['header_frac']
    y=body*(1-150./engine.resolve_depth_axis(drawing)[0])
    for side,vertices in zip((-1,1),walls):
        step=[(x,z) for x,z in vertices if abs(z-y)<1e-12]
        for od in (6.5,7.):
            expected=c1+c2*(.5+side*od*.385/9.625)
            assert any(abs(x-expected)<1e-12 for x,_ in step)
    labels=engine._collect_labels(drawing,drawing['open_holes'])
    assert len([r for r in labels if '→' in r['text'] and r['depth']==150.])==1
    assert any('TB LNR Shoe @ 300 m' in r['text'] and r['text'].startswith('7"' if expanding else '6 1/2"') for r in labels)
    with Image.open(path) as image:
        assert image.size==(900,1140) and image.info['dpi'][0]==pytest.approx(round(150./.0254)*.0254,abs=1e-10)
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('fault',['empty','missing_field','gap','reversed','end','summary_od','summary_id','bad_id','bad_fit','nonfinite','duplicate','wrong_type'])
def test_r18c_section_renderer_rejects_invalid_measured_contract(fault,tmp_path):
    import well_schematic_adapter as schematic
    import well_schematic_engine as engine
    data=schematic.prepare_schematic(r18c_tapered_state())
    previous=next(c for c in data['casings'] if 'sections' in c)
    if fault=='empty':previous['sections']=[]
    elif fault=='missing_field':del previous['sections'][1]['id_in']
    elif fault=='gap':previous['sections'][1]['top_md']=151.
    elif fault=='reversed':previous['sections'].reverse()
    elif fault=='end':previous['sections'][1]['shoe_md']=299.
    elif fault=='summary_od':previous['size_in']=6.75
    elif fault=='summary_id':previous['id_in']=6.
    elif fault=='bad_id':previous['sections'][1]['id_in']=6.5
    elif fault=='bad_fit':previous['sections'][1].update(size_in=9.,id_in=8.)
    elif fault=='nonfinite':previous['sections'][1]['shoe_md']=float('inf')
    elif fault=='duplicate':previous['sections'].append(deepcopy(previous['sections'][1]))
    else:previous['type']='casing'
    with pytest.raises(ValueError,match='section|Tie Back|fit|clearance'):
        engine.render_well_schematic(data,str(tmp_path/'invalid.png'),dpi=90,strict=True)
    assert not (tmp_path/'invalid.png').exists()


def r18c_ct_state():
    import materials_db as db
    state=r18c_tapered_state()
    state['fluids_config']={'active':['Main','Displacement Fluid']}
    state['cement_params']={'Main':{'top_mode':'Depth (m MD)','top_depth':100.,'top_job_type':db.CT_JOB}}
    state['hardware_table']=pd.concat([state['hardware_table'],hardware(('CT','200','2 3/8',1.9))],ignore_index=True)
    state['job_type']=db.CT_JOB;state['placement_config']['job_type']=db.CT_JOB
    return state


def test_r18c_ct_and_plug_use_the_actual_previous_section_at_each_depth(tmp_path,monkeypatch):
    import well_schematic_adapter as schematic
    import well_schematic_engine as engine
    from matplotlib.axes import Axes
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Polygon
    state=r18c_ct_state()
    before=pickle.dumps(state)
    drawing=schematic.prepare_schematic(state)
    assert drawing['available'] and drawing['missing_geometry']==[]
    payload=drawing['payload'];previous=next(c for c in payload['casings'] if 'sections' in c)
    assert payload['cement_plugs']==[{'top_md':100.,'bottom_md':200.}]
    assert engine._pipe_at(previous,125.)['size_in']==7.
    assert engine._pipe_at(previous,175.)['size_in']==6.5
    plugs=[];original=Axes.add_patch
    def capture(ax,patch):
        if isinstance(patch,Polygon) and patch.get_facecolor()==to_rgba(engine.C_PLUG_FILL):plugs.append(patch.get_xy())
        return original(ax,patch)
    monkeypatch.setattr(Axes,'add_patch',capture)
    engine.render_well_schematic(payload,str(tmp_path/'ct-taper.png'),dpi=150,strict=True)
    assert len(plugs)==1
    body=1-engine.layout_geometry()['header_frac'];y=body*(1-150./engine.resolve_depth_axis(payload)[0])
    assert len([v for v in plugs[0] if abs(v[1]-y)<1e-12])>=4
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('fault',['gap','duplicate','bad_id','bad_host_fit'])
def test_r18c_ct_unknown_other_history_cannot_hide_invalid_previous_sections(fault):
    import well_schematic_adapter as schematic
    state=r18c_ct_state();table=state['hardware_table']
    if fault=='gap':table.at[5,'MD (m)']='151-300'
    elif fault=='duplicate':table=pd.concat([table,table.iloc[[3]]],ignore_index=True)
    elif fault=='bad_id':table.at[5,'ID (in)']=6.5
    else:table.at[5,'Size (in)']='9'
    missing=hardware(('Previous Casing',None,None,None)).iloc[0].to_dict()
    state['hardware_table']=pd.DataFrame.from_records([*table.to_dict('records'),missing],columns=table.columns)
    before=pickle.dumps(state)
    with pytest.raises(ValueError,match='Previous Tie Back|gap|overlap|ID'):
        schematic.prepare_schematic(state)
    assert pickle.dumps(state)==before


@pytest.fixture(scope='module')
def r18c_reference_renderer():
    import subprocess
    reference={'__name__':'r18c_archived_renderer'}
    source=subprocess.check_output(['git','show','cdb58925886d4ee649d583052ea138286f1e6f79:well_schematic_engine.py'])
    exec(compile(source,'archived-well-schematic-engine','exec'),reference)
    return reference['render_well_schematic']


def test_r18c_section_guards_do_not_reinterpret_unrelated_scalar_admission(r18c_reference_renderer,tmp_path):
    import well_schematic_engine as engine
    data=engine.get_preset_schematic_data('tieback_7in')
    data['casings'][-1]['shoe_md']=3000.  # Existing scalar renderer's interior-landing convention.
    r18c_reference_renderer(data,str(tmp_path/'scalar-reference.png'),dpi=90,strict=True)
    data['casings'].extend([
        {'type':'liner','size_in':8.,'id_in':7.5,'top_md':1000.,'shoe_md':1200.,'host_index':2},
        {'type':'tieback','size_in':8.,'top_md':500.,'shoe_md':1000.,'host_index':2,'landing_liner_index':5,
         'sections':[{'size_in':8.,'id_in':7.5,'top_md':500.,'shoe_md':750.},
                     {'size_in':7.75,'id_in':7.5,'top_md':750.,'shoe_md':1000.}]}])
    engine.validate_schematic_data(data)
    assert engine.check_well_design(data)==[]
    engine.render_well_schematic(data,str(tmp_path/'sectioned-with-scalar-history.png'),dpi=90,strict=True)


@pytest.mark.parametrize('job',['CSG 13 3/8"','CSG 9 5/8"','LNR 7"','LNR 5"','LNR 4 1/2"',
    'TIE BACK LNR 7"','TIE BACK LNR 5"','TIE BACK LNR 4 1/2"','CMT PLUG','CMT SQUEEZE','CMT PLUG WITH CT'])
def test_r18c_nontapered_job_png_bytes_equal_the_independent_merged_renderer(job,r18c_reference_renderer,tmp_path):
    import well_schematic_adapter as schematic
    import well_schematic_engine as engine
    if job=='CMT PLUG WITH CT':
        from test_round13b_b3_ct_schematic import state
        source=state('complete')
    elif job in ('CMT PLUG','CMT SQUEEZE'):
        import test_audit_regressions as audit
        source={'job_type':job,**audit.valid_export_chart_fixture(job)}
        source['fluids_config']={'active':['Main','Displacement Fluid']}
        source['cement_params']={'Main':{'top_mode':'Depth (m MD)','top_depth':2000.,'top_job_type':job}}
    else:source=bug01_geometry_case(job)
    before=pickle.dumps(source)
    drawing=schematic.prepare_schematic(source)
    if job=='CMT PLUG WITH CT':
        assert drawing['available'];drawing=drawing['payload']
    assert not any('sections' in c for c in drawing['casings'])
    r18c_reference_renderer(drawing,str(tmp_path/'original.png'),dpi=90,strict=True)
    engine.render_well_schematic(drawing,str(tmp_path/'current.png'),dpi=90,strict=True)
    assert (tmp_path/'current.png').read_bytes()==(tmp_path/'original.png').read_bytes()
    assert pickle.dumps(source)==before


@pytest.mark.parametrize('mode',['ignore','apply'])
@pytest.mark.parametrize('physics,placement_mode',[('static','direct'),('static','optimize'),('dynamic','direct'),('dynamic','optimize')])
def test_r18c_tapered_history_uses_full_nominal_flow_and_active_mechanical_domain(mode,physics,placement_mode):
    import phase_9_centralizer as phase9
    from placement import slurry_intervals
    state=bug01_solver_state('TIE BACK LNR 5"');state.update(r18c_tapered_state(100.))
    state['centralizer_config']['zones'][0].update(top_md=400.,bottom_md=700.)
    state['centralizer_config'].update(physics_mode=physics,placement_mode=placement_mode)
    state['placement_config'].update(chart_excess_mode=mode,excess_csg_csg_pct=12.5,excess_csg_oh_pct=20.)
    source=pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')})
    chart_geometry=chart.resolve_chart_geometry(state)
    assert boundary(chart_geometry)==[(0.,100.,8.535),(100.,150.,6.094),(150.,300.,5.8),(300.,700.,6.094)]
    pumping,_=pumping_simulation._geometry(state,'tieback')
    assert [(s.z_top,s.z_bot,s.id_in,s.od_in) for s in pumping.pipe_sections]==[
        (0.,400.,2.764,3.5),(400.,700.,4.276,5.),(700.,1200.,4.276,5.)]
    for segment in chart_geometry['capacity_segments']:
        mid=(segment['top_md']+segment['bottom_md'])/2
        pipe=next(s for s in pumping.pipe_sections if s.z_top<=mid<s.z_bot)
        wall=next(s for s in pumping.ann_sections if s.z_top<=mid<s.z_bot)
        assert wall.di_in==pipe.od_in
        assert chart._capacity(wall.do_in,wall.di_in)==segment['nominal_bbl_per_m']
        assert segment['bbl_per_m']==pytest.approx(segment['nominal_bbl_per_m']*(1.125 if mode=='apply' else 1.))
    projected=centralizer_adapter.to_engine_geometry(state)
    assert projected['wellbore']['string_top']==400. and projected['wellbore']['string_shoe']==700.
    assert projected['wellbore']['prev_casing_id']==6.094*.0254
    intervals=slurry_intervals(state['hardware_table'],state['job_type'],state['placement_config'],['Main'],state.get('cement_params',{}),state['fluids_config']['params'])
    assert intervals['Main']['bottom_depth']==700.
    assert phase9.execute(state)['profile']
    assert phase9.result_is_current(state)
    assert pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')})==source


def test_r18c_editor_delete_incomplete_add_repair_and_navigation_keep_measured_identity():
    import test_audit_regressions as audit
    import phase_9_centralizer as phase9
    case=audit.AuditRegressions();app=case.app(r18c_tapered_state())
    case.phase(app,'phase2_3')
    original=app.session_state['hardware_table'].copy(deep=True)
    config=deepcopy(app.session_state['placement_config'])
    lap_index=int(original.index[original['Description']=='Tie Back Liner Lap'][0])
    expected=chart.resolve_chart_geometry(app.session_state)
    case.hardware_event(app,{'deleted_rows':[lap_index]})
    assert not app.session_state['hardware_table']['Description'].eq('Tie Back Liner Lap').any()
    with pytest.raises(ValueError,match='Top is missing'):chart.resolve_chart_geometry(app.session_state)
    incomplete=original.iloc[lap_index].to_dict();incomplete['MD (m)']=None
    # Mounted Streamlit editors send cumulative edits against their stable source frame.
    case.hardware_event(app,{'deleted_rows':[lap_index],'added_rows':[incomplete]})
    row=app.session_state['hardware_table'].iloc[-1]
    assert row['Description']=='Tie Back Liner Lap' and row['MD (m)']==''
    assert app.session_state['hardware_table']['Description'].eq('Tie Back Liner Lap').sum()==1
    assert not phase9.result_is_current(app.session_state)
    case.phase(app,'phase4');case.phase(app,'phase2_3')
    index=len(app.session_state['hardware_table'])-1
    case.hardware_event(app,{'edited_rows':{str(index):{'MD (m)':'400'}}})
    assert chart.resolve_chart_geometry(app.session_state)==expected
    assert app.session_state['placement_config']==config
    source=app.session_state['hardware_table'].copy(deep=True)
    case.phase(app,'phase4');case.phase(app,'phase2_3')
    pd.testing.assert_frame_equal(app.session_state['hardware_table'],source)
    restored=audit.round_trip(app.session_state.to_dict())
    pd.testing.assert_frame_equal(restored['hardware_table'],source,check_dtype=False)
    assert restored['placement_config']==config
    assert chart.resolve_chart_geometry(restored)==expected


def r18b_previous_state(top=400., previous_top=0.):
    """Explicitly synthetic measured strings, products/labs supplied separately."""
    rows = hardware(
        ('Previous Casing', '500', '9 5/8', 8.535),
        ('Previous Liner Shoe', '300-1000', '7', 6.094),
        ('Previous Liner Shoe', '700-1200', '5', 4.276),
        ('Previous Tie Back Liner Lap', str(previous_top), '7', 6.094),
        ('Previous Tie Back Liner Shoe', '300', '7', 6.094),
        ('Tie Back Liner Lap', str(top), '5', 4.276),
        ('Drill Pipes', str(top), '3 1/2', 2.764),
        ('Tie Back Liner Shoe', '700', '5', 4.276),
        ('Open Hole Size', '1000-1200', '6', 6.))
    state = project('TIE BACK LNR 5"', rows, 1200.)
    state['placement_config']['host_row'] = next(iter(hardware_choices(rows.iloc[[1]], {'Previous Liner Shoe'})))
    return state


def test_r18b_three_catalog_entries_are_exact_distinct_roles():
    import materials_db as db
    from placement import HOST_DESCRIPTIONS
    expected = {'Tie Back Liner Lap', 'Previous Tie Back Liner Lap', 'Previous Tie Back Liner Shoe'}
    assert expected <= set(db.HARDWARE_DESCRIPTIONS)
    assert not expected & HOST_DESCRIPTIONS
    assert not expected & target_descriptions('TIE BACK LNR 5"')


@pytest.mark.parametrize('top', [0., 100.])
def test_r18b_current_measured_lap_is_top_without_a_fabricated_interval(top):
    state = synthetic_tieback(top=top)
    table = state['hardware_table']
    table.at[0, 'MD (m)'] = '700'
    lap = hardware(('Tie Back Liner Lap', str(top), '7', 6.))
    state['hardware_table'] = pd.concat([table, lap], ignore_index=True)
    state['placement_config']['target_row'] = next(iter(hardware_choices(state['hardware_table'], target_descriptions(state['job_type']))))
    before = pickle.dumps(state)
    geometry = chart.resolve_chart_geometry(state)
    expected = ([(0., top, 'Drill Pipes')] if top else []) + [(top, 700., 'Tie Back Liner Shoe')]
    assert [(r['top_md'], r['bottom_md'], r['description']) for r in geometry['active_string']] == expected
    assert centralizer_adapter.to_engine_geometry(state)['wellbore']['string_top'] == top
    assert pickle.dumps(state) == before


@pytest.mark.parametrize('top', [0., 100.])
def test_r18b_previous_tieback_is_a_measured_installed_string(top):
    import installed_geometry as installed
    state = r18b_previous_state(previous_top=top)
    rows = state['hardware_table'].to_dict('records')
    strings = installed.physical_strings(rows, chart._segments, {'Previous Casing', 'Previous Liner Shoe'})
    previous = [s for s in strings if s['description'] == 'Previous Tie Back Liner Shoe']
    assert len(previous) == 1
    assert (previous[0]['top_md'], previous[0]['shoe_md']) == (top, 300.)
    assert previous[0]['indices'] == [4]
    assert previous[0]['sections'] == [{'top_md': top, 'bottom_md': 300., 'od_in': 7.,
        'id_in': 6.094, 'description': 'Previous Tie Back Liner Shoe'}]
    geometry = chart.resolve_chart_geometry(state)
    expected = ([(0., top, 8.535)] if top else []) + [(top, 300., 6.094), (300., 700., 6.094)]
    assert boundary(geometry) == expected


@pytest.mark.parametrize('interval,metadata', [(True,False),(False,True),(True,True)])
def test_r18b_agreeing_explicit_top_authorities_do_not_rewrite_hardware(interval,metadata):
    state = r18b_previous_state()
    if interval:
        state['hardware_table'].at[7,'MD (m)'] = '400-700'
        state['placement_config']['target_row'] = next(iter(hardware_choices(
            state['hardware_table'],target_descriptions(state['job_type']))))
    if metadata:state['placement_config']['tie_back_liner_lap_m'] = 400.
    before = pickle.dumps(state)
    assert centralizer_adapter.to_engine_geometry(state)['wellbore']['string_top'] == 400.
    assert pickle.dumps(state) == before


def test_r18b_zero_depth_admission_is_only_for_measured_lap_roles():
    from engineering_tools import compute_phase_status
    from test_audit_regressions import well_profile_fixture
    state = r18b_previous_state(previous_top=0.)
    state.update(well_profile_fixture(md=1200.))
    state.update(geo_md=1200.,geo_tvd=1200.)
    state['well_data'] = {chart.PORE_FIELD:55.,chart.FRAC_FIELD:125.}  # Explicit synthetic formation prerequisites.
    status = compute_phase_status(state)['phase2_3']
    assert status['level'] == 'ok', status
    for role,value in [('Previous Tie Back Liner Lap',''),('Previous Tie Back Liner Lap','0-100'),
                       ('Previous Tie Back Liner Lap','-1'),('Previous Tie Back Liner Lap','nan'),
                       ('Previous Casing','0'),('Drill Pipes','0')]:
        changed = deepcopy(state)
        changed['hardware_table'].loc[changed['hardware_table']['Description']==role,'MD (m)'] = value
        assert compute_phase_status(changed)['phase2_3']['level'] != 'ok'


def test_r18b_ct_history_consumes_previous_roles_without_inventing_missing_boundaries():
    from well_schematic_adapter import _ct_history_facts
    state = r18b_previous_state(previous_top=0.)
    rows = state['hardware_table'].to_dict('records')
    before = pickle.dumps(rows)
    assert _ct_history_facts(rows,1200.,state['placement_config']) == []
    assert pickle.dumps(rows) == before
    for role in ('Previous Tie Back Liner Lap','Previous Tie Back Liner Shoe','Tie Back Liner Shoe'):
        with pytest.raises(ValueError,match='Tie Back'):
            _ct_history_facts([r for r in rows if r['Description']!=role],1200.,state['placement_config'])


@pytest.mark.parametrize('fault', ['missing', 'negative', 'nonfinite', 'interval', 'duplicate',
                                  'size', 'config', 'shoe', 'missing_dp', 'short_dp'])
def test_r18b_current_top_conflicts_and_incomplete_path_fail_closed(fault):
    state = r18b_previous_state()
    table = state['hardware_table']
    if fault == 'missing': table.at[5, 'MD (m)'] = None
    elif fault == 'negative': table.at[5, 'MD (m)'] = '-1'
    elif fault == 'nonfinite': table.at[5, 'MD (m)'] = 'inf'
    elif fault == 'interval': table.at[5, 'MD (m)'] = '390-400'
    elif fault == 'duplicate': state['hardware_table'] = pd.concat([table, table.iloc[[5]]], ignore_index=True)
    elif fault == 'size': table.at[5, 'Size (in)'] = '7'
    elif fault == 'config': state['placement_config']['tie_back_liner_lap_m'] = 399.
    elif fault == 'shoe':
        table.at[7, 'MD (m)'] = '399-700'
        state['placement_config']['target_row'] = next(iter(hardware_choices(table, target_descriptions(state['job_type']))))
    elif fault == 'missing_dp': state['hardware_table'] = table.drop(index=6)
    else: table.at[6, 'MD (m)'] = '399'
    before = pickle.dumps(state)
    with pytest.raises(ValueError, match='Lap|Top|Hardware|geometry|Drill Pipes'):
        chart.resolve_chart_geometry(state)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize('fault', ['missing_lap', 'missing_shoe', 'duplicate_lap', 'duplicate_shoe',
                                  'second_previous', 'lap_size', 'missing_id', 'bad_id', 'negative_id',
                                  'reversed', 'gap', 'lap_interval', 'nonfinite', 'implicit_taper', 'short_host'])
def test_r18b_previous_pair_cannot_infer_repair_or_create_a_second_string(fault):
    import installed_geometry as installed
    state = r18b_previous_state()
    table = state['hardware_table']
    if fault == 'missing_lap': table = table.drop(index=3)
    elif fault == 'missing_shoe': table = table.drop(index=4)
    elif fault == 'duplicate_lap': table = pd.concat([table, table.iloc[[3]]], ignore_index=True)
    elif fault == 'duplicate_shoe': table = pd.concat([table, table.iloc[[4]]], ignore_index=True)
    elif fault == 'second_previous':
        extra = table.iloc[[3,4]].copy();extra['Size (in)'] = '6';extra['ID (in)'] = 5.5
        table = pd.concat([table, extra], ignore_index=True)
    elif fault == 'lap_size': table.at[3, 'Size (in)'] = '5'
    elif fault == 'missing_id': table.at[4, 'ID (in)'] = None
    elif fault == 'bad_id': table.at[4, 'ID (in)'] = 7.
    elif fault == 'negative_id': table.at[4, 'ID (in)'] = -1.
    elif fault == 'reversed': table.at[4, 'MD (m)'] = '300-100'
    elif fault == 'gap': table.at[4, 'MD (m)'] = '100-300'
    elif fault == 'lap_interval': table.at[3, 'MD (m)'] = '0-100'
    elif fault == 'nonfinite': table.at[3, 'MD (m)'] = 'nan'
    elif fault == 'implicit_taper':
        extra = table.iloc[[4]].copy();extra['MD (m)'] = '350';extra['Size (in)'] = '6.5';extra['ID (in)'] = 5.8
        table = pd.concat([table.iloc[:5], extra, table.iloc[5:]], ignore_index=True)
    else: table.at[0, 'MD (m)'] = '200'
    rows = table.to_dict('records');before = pickle.dumps(rows)
    with pytest.raises(ValueError, match='Previous Tie Back|Hardware|OD|ID|host|clearance|overlap'):
        installed.physical_strings(rows, chart._segments, {'Previous Casing', 'Previous Liner Shoe'})
    assert pickle.dumps(rows) == before


@pytest.mark.parametrize('taper', [False, True])
def test_r18b_previous_sections_keep_source_order_identity_and_true_dimensions(taper):
    import installed_geometry as installed
    import well_schematic_adapter as schematic
    state = r18b_previous_state()
    table = state['hardware_table']
    table.at[4, 'MD (m)'] = '100'
    extra = table.iloc[[4]].copy();extra['MD (m)'] = '100-300';extra['ID (in)'] = 5.8
    if taper: extra['Size (in)'] = '6.5'
    state['hardware_table'] = pd.concat([table.iloc[:5], extra, table.iloc[5:]], ignore_index=True)
    previous = next(s for s in installed.physical_strings(state['hardware_table'].to_dict('records'), chart._segments,
        {'Previous Casing','Previous Liner Shoe'}) if s['description'] == 'Previous Tie Back Liner Shoe')
    assert previous['indices'] == [4,5]
    assert [(s['top_md'],s['bottom_md'],s['od_in'],s['id_in']) for s in previous['sections']] == [
        (0.,100.,7.,6.094),(100.,300.,6.5 if taper else 7.,5.8)]
    drawing=schematic.prepare_schematic(state)
    assert len([c for c in drawing['casings'] if c['type']=='tieback']) == 2
    previous_drawing=next(c for c in drawing['casings'] if c['shoe_md']==300.)
    assert previous_drawing['sections']==[{'top_md':s['top_md'],'shoe_md':s['bottom_md'],
        'size_in':s['od_in'],'id_in':s['id_in']} for s in previous['sections']]
    reversed_rows = list(reversed(previous['rows']))
    rows = state['hardware_table'].to_dict('records')
    rows[4:6] = reversed_rows
    with pytest.raises(ValueError, match='Previous Tie Back|reversed|gap|overlap'):
        installed.physical_strings(rows, chart._segments, {'Previous Casing','Previous Liner Shoe'})


def r18b_solver_state(previous_top=0.):
    state = bug01_solver_state('TIE BACK LNR 5"')
    state.update(r18b_previous_state(previous_top=previous_top))
    state['centralizer_config']['zones'][0].update(top_md=400., bottom_md=700.)
    return state


@pytest.mark.parametrize('previous_top', [0., 100.])
@pytest.mark.parametrize('physics,mode', [('static','direct'),('static','optimize'),('dynamic','direct'),('dynamic','optimize')])
def test_r18b_frozen_modes_use_active_body_and_preserve_measured_upstream_flow(previous_top, physics, mode):
    import phase_9_centralizer as phase9
    import centralizer_optimizer_engine as engine
    import centralizer_report
    import test_audit_regressions as audit
    state = r18b_solver_state(previous_top)
    state['centralizer_config'].update(physics_mode=physics, placement_mode=mode)
    geometry = chart.resolve_chart_geometry(state)
    assert [(r['top_md'],r['bottom_md'],r['description']) for r in geometry['active_string']] == [
        (0.,400.,'Drill Pipes'),(400.,700.,'Tie Back Liner Shoe')]
    projected = centralizer_adapter.to_engine_geometry(state)
    assert projected['wellbore']['string_top'] == 400.
    assert projected['wellbore']['string_shoe'] == projected['wellbore']['prev_shoe_depth'] == 700.
    assert projected['wellbore']['prev_casing_id'] == projected['wellbore']['hole_size'] == 6.094*.0254
    pumping,_ = pumping_simulation._geometry(state,'tieback')
    assert [(s.z_top,s.z_bot,s.od_in,s.id_in) for s in pumping.pipe_sections] == [
        (0.,400.,3.5,2.764),(400.,700.,5.,4.276),(700.,1200.,5.,4.276)]
    assert not any(s.od_in in (7.,9.625) for s in pumping.pipe_sections)
    catalog = centralizer_adapter.load_official_catalog()
    payload = (centralizer_adapter.build_static_payload(state,state['centralizer_config']['zones'],catalog)
        if physics=='static' else centralizer_adapter.build_dynamic_payload(state,state['centralizer_config']['zones'],catalog)['payload'])
    before = pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')})
    result = phase9.execute(state)
    solve = engine.compute_standoff_profile if mode=='direct' else engine.optimize_placement
    assert result['profile'] == solve(payload)
    assert pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')}) == before
    assert phase9.result_is_current(state)
    restored = audit.round_trip(state)
    pd.testing.assert_frame_equal(restored['hardware_table'],state['hardware_table'],check_dtype=False)
    assert restored['placement_config'] == state['placement_config']
    assert phase9.source_signature(restored) == phase9.source_signature(state)
    assert not phase9.result_is_current(restored)
    state['hardware_table'].at[4,'ID (in)'] = 6.093
    assert centralizer_adapter.to_engine_geometry(state) == projected
    assert not phase9.result_is_current(state)
    assert not centralizer_report.prepare_report(state)['current']
    state['hardware_table'].at[4,'ID (in)'] = 4.4
    with pytest.raises(ValueError,match='restriction|pass|fit'):
        chart.resolve_chart_geometry(state)


def test_r18b_inside_active_two_ids_and_previous_host_selection_stay_blocked():
    state = r18b_previous_state()
    table = state['hardware_table']
    state['placement_config']['host_row'] = next(iter(hardware_choices(table, {'Previous Tie Back Liner Shoe'})))
    with pytest.raises(ValueError, match='host'):
        chart.resolve_chart_geometry(state)
    table.at[0,'MD (m)']='650';table.at[1,'MD (m)']='600-1000'
    table.at[3,'MD (m)']='500';table.at[4,'MD (m)']='600'
    state['placement_config']['host_row'] = next(iter(hardware_choices(table.iloc[[0]], {'Previous Casing'})))
    assert boundary(chart.resolve_chart_geometry(state)) == [(0.,500.,8.535),(500.,600.,6.094),(600.,700.,6.094)]
    with pytest.raises(ValueError, match='identical scalar ID'):
        centralizer_adapter.to_engine_geometry(state)


@pytest.mark.parametrize('previous', [False, True, 'taper', 'expanding_taper'])
def test_r18b_actual_editor_json_currentness_and_word(bug01_reviewed_report_base, previous, tmp_path):
    import json
    from io import BytesIO
    from docx import Document
    import test_audit_regressions as audit
    import phase_9_centralizer as phase9
    import well_schematic_adapter as schematic
    from test_uat_round10c_integration import save_project, restore_project, build
    from test_uat_round9g_centralizer_word import ix_region
    case = audit.AuditRegressions()
    if previous:
        measured = (r18c_tapered_state(100.,previous=='expanding_taper') if isinstance(previous,str)
                    else r18b_previous_state(previous_top=100.))
        job = 'TIE BACK LNR 5"'
    else:
        measured = synthetic_tieback(top=0.)
        measured['hardware_table'].at[0,'MD (m)'] = '700'
        measured['hardware_table'] = pd.concat([measured['hardware_table'],
            hardware(('Tie Back Liner Lap','0','7',6.))],ignore_index=True)
        job = 'TIE BACK LNR 7"'
        measured['placement_config']['target_row'] = next(iter(hardware_choices(measured['hardware_table'], target_descriptions(job))))
    app = case.app(deepcopy(bug01_reviewed_report_base))
    case.phase(app,'phase1');app.selectbox(key='_w_job_type').set_value(job).run()
    for key in ('hardware_table','well_geometry','placement_config'):app.session_state[key] = deepcopy(measured[key])
    for name in ('Main','Displacement Fluid'):app.session_state['fluids_config']['params'][name]['volume'] = 8.
    app.session_state['cement_params']['Main'].update(top_mode='Not entered',top_depth=None,report_bottom_depth=None)
    selected = deepcopy(measured['placement_config'])
    case.phase(app,'phase2_3')
    editor = next(e for e in app.dataframe if '_editor_hardware_' in e.proto.id)
    options = json.loads(editor.proto.columns)['Description']['type_config']['options']
    assert {'Tie Back Liner Lap','Previous Tie Back Liner Lap','Previous Tie Back Liner Shoe'} <= set(options)
    host = next(w for w in app.selectbox if w.label.startswith('Tie Back host'))
    assert host.value == selected['host_row']
    assert not any('Previous Tie Back' in value for value in host.options)
    assert not any('Tie Back Top' in w.label for w in app.number_input)
    assert 'tie_back_liner_lap_m' not in app.session_state['placement_config']
    for key, value in selected.items():
        assert app.session_state['placement_config'][key] == value
    selected = deepcopy(app.session_state['placement_config'])
    case.phase(app,'phase1');case.phase(app,'phase2_3')
    assert app.session_state['placement_config'] == selected
    case.phase(app,'phase5');case.phase(app,'phase7')
    sync_button = next((b for b in app.button if (b.key or '').startswith('_sync_btn_main_')),None)
    if sync_button is not None:sync_button.click().run()
    confirm = next(b for b in app.button if (b.key or '').startswith('_confirm_lab_btn_main_'))
    assert not confirm.disabled;confirm.click().run();case.healthy(app)
    state = app.session_state.to_dict()
    configured = bug01_solver_state(job)['centralizer_config']
    top = 400. if previous else 0.
    configured['zones'][0].update(top_md=top,bottom_md=700.)
    configured.update(physics_mode='dynamic',placement_mode='direct')
    state['centralizer_config'] = configured
    phase9.execute(state)
    source_signature = phase9.source_signature(state)
    saved = save_project(type('Project',(),{'session_state':state})())
    restored = restore_project(saved)
    second = save_project(restored)
    again = restore_project(second)
    for candidate in (restored,again):
        pd.testing.assert_frame_equal(candidate.session_state['hardware_table'],state['hardware_table'],check_dtype=False)
        assert candidate.session_state['placement_config'] == selected
        assert phase9.source_signature(candidate.session_state) == source_signature
        assert not phase9.result_is_current(candidate.session_state)
        assert '_compiled_doc_bytes' not in candidate.session_state
    case.phase(again,'phase9');again.button(key='_centralizer_execute').click().run();case.healthy(again)
    assert phase9.result_is_current(again.session_state)
    drawing = schematic.prepare_schematic(again.session_state)
    assert len([s for s in drawing['casings'] if s['type']=='tieback']) == (2 if previous else 1)
    case.phase(again,'phase10')
    assert not next(b for b in again.button if b.label == 'Build Word Document').disabled, [
        w.value for w in list(again.warning)+list(again.error)]
    data = build(again)
    document = Document(BytesIO(data))
    table = next(t for t in document.tables if t.cell(0,0).text=='Tubular and Casing Hardware')
    assert len(table._tbl.tblGrid.gridCol_lst) == 10 and len(table.rows[1].cells) == 9
    rows = state['hardware_table'].to_dict('records')
    assert [r.cells[0].text for r in table.rows[3:3+len(rows)]] == [r['Description'] for r in rows]
    assert any(r.cells[0].text=='Tie Back Liner Lap' and r.cells[1].text==f'{top:.1f}' for r in table.rows)
    from phase_2_3_well_data import HARDWARE_COLUMNS
    for rendered,source_row in zip(table.rows[3:3+len(rows)],rows):
        assert len(rendered.cells)==9
        for cell,field in zip(rendered.cells,HARDWARE_COLUMNS):
            value=source_row[field]
            if source_row['Description']=='Open Hole Size' and field in ('Joint (m)','Weight (ppf)','Grade','Collapse (psi)','Burst (psi)'):
                expected='-'
            elif field=='MD (m)' and '-' not in str(value):expected=f'{float(value):.1f}'
            else:expected=str(value)
            assert cell.text==expected
    from zipfile import ZipFile
    import well_report
    assert schematic.prepare_schematic(again.session_state)==drawing
    actual_schematic=well_report.render_schematic_png(drawing)
    with ZipFile(BytesIO(data)) as archive,ZipFile('master_template.docx') as template:
        assert actual_schematic in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        from lxml import etree
        for name in ('word/styles.xml','word/fontTable.xml','word/theme/theme1.xml'):
            # python-docx serializes XML declarations; compare all format/style XML canonically.
            canonical=lambda raw:etree.tostring(etree.fromstring(raw),method='c14n')
            assert canonical(archive.read(name))==canonical(template.read(name))
    region = ix_region(document)
    assert any(e.xpath('.//w:drawing') for e in region)
    assert len(region[-1].xpath('.//w:br[@w:type="page"]')) == 1
    (tmp_path/'measured-tieback.docx').write_bytes(data)
    (tmp_path/'project-first.json').write_bytes(saved)
    (tmp_path/'project-second.json').write_bytes(second)
    case.phase(again,'phase2_3')
    index = 3 if previous else len(state['hardware_table'])-1
    value = '101' if previous else '-1'
    case.hardware_event(again,{'edited_rows':{str(index):{'MD (m)':value}}})
    case.phase(again,'phase10')
    assert '_compiled_doc_bytes' not in again.session_state
    assert not phase9.result_is_current(again.session_state)


def test_r18_catalog_and_exact_target_roles():
    import materials_db as db
    from placement import hardware_context_label
    expected = {"Previous Liner Lap", "Previous Liner Shoe", "Liner Shoe",
                "Liner Lap", "Tie Back Liner Shoe"}
    assert expected <= set(db.HARDWARE_DESCRIPTIONS)
    assert not {"Previous Liner Hanger", "Previous Liner", "Liner", "Liner Hanger",
                "Tie Back"} & set(db.HARDWARE_DESCRIPTIONS)
    assert target_descriptions('LNR 5"') == {"Liner Shoe"}
    assert target_descriptions('TIE BACK LNR 5"') == {"Tie Back Liner Shoe"}
    assert target_descriptions('CMT PLUG') == {"Casing", "Liner Shoe", "Tie Back Liner Shoe", "Open Hole Size"}
    rows = hardware(("Tie Back Liner Shoe", "200-700", "5", 4.),
                    ("Liner Shoe", "400-900", "5", 4.))
    choices = hardware_choices(rows, target_descriptions('TIE BACK LNR 5"'))
    assert len(choices) == 1
    assert next(iter(choices.values()))["description"] == "Tie Back Liner Shoe"
    assert hardware_context_label(rows, next(iter(choices))) == '5" Tie Back'
    from installed_geometry import receiving_liner
    from well_schematic_adapter import _renderer_type
    assert _renderer_type("Tie Back Liner Shoe") == "tieback"
    with pytest.raises(ValueError, match="receiving Liner"):
        receiving_liner([{"description": "Tie Back Liner Shoe", "top_md": 100.,
                          "shoe_md": 1000.}], 500.)


@pytest.mark.parametrize('job', ['LNR 5"', 'TIE BACK LNR 4 1/2"'])
def test_r18_editor_choices_first_edit_navigation_and_json_identity(job):
    import json
    import test_audit_regressions as audit
    import phase_9_centralizer as phase9
    from phase_2_3_well_data import HARDWARE_COLUMNS
    case = audit.AuditRegressions()
    source = bug01_solver_state(job)
    app = case.app(deepcopy(source))
    case.phase(app, 'phase2_3')
    editor = next(e for e in app.dataframe if '_editor_hardware_' in e.proto.id)
    options = json.loads(editor.proto.columns)['Description']['type_config']['options']
    assert {'Previous Liner Lap', 'Previous Liner Shoe', 'Liner Shoe',
            'Liner Lap', 'Tie Back Liner Shoe'} <= set(options)
    assert not {'Previous Liner Hanger', 'Previous Liner', 'Liner', 'Liner Hanger', 'Tie Back'} & set(options)
    assert list(editor.value.columns) == HARDWARE_COLUMNS
    before = app.session_state['hardware_table'].copy(deep=True)
    tokens = deepcopy(app.session_state['placement_config'])
    signature = phase9.source_signature(app.session_state)
    # Navigation retains the editor draft; returning commits it through the
    # established Hardware cleaner, without bypassing pending-draft admission.
    inner = float(before.at[0, 'ID (in)'])-.001
    case.hardware_event(app, {'edited_rows': {'0': {'ID (in)': inner}}}, navigate='phase1')
    assert app.session_state['hardware_editor_draft'].at[0, 'ID (in)'] == inner
    case.phase(app, 'phase2_3')
    before.at[0, 'ID (in)'] = inner
    pd.testing.assert_frame_equal(app.session_state['hardware_table'], before, check_dtype=False)
    assert app.session_state['placement_config'] == tokens
    assert phase9.source_signature(app.session_state) != signature
    saved = audit.round_trip(app.session_state.to_dict())
    again = audit.round_trip(saved)
    pd.testing.assert_frame_equal(saved['hardware_table'], again['hardware_table'], check_dtype=False)
    assert saved['placement_config'] == again['placement_config'] == tokens
    assert phase9.source_signature(saved) == phase9.source_signature(again)
    assert chart.resolve_chart_geometry(saved) == chart.resolve_chart_geometry(again)
    restored = case.app(saved)
    case.phase(restored, 'phase2_3')
    pd.testing.assert_frame_equal(restored.session_state['hardware_table'], before, check_dtype=False)
    assert restored.session_state['placement_config'] == tokens


def hardware(*rows):
    return pd.DataFrame([dict(zip(("Description", "MD (m)", "Size (in)", "ID (in)"), row),
                              **{"Joint (m)": 12.2, "Weight (ppf)": 50., "Grade": "K-55",
                                 "Collapse (psi)": 1000., "Burst (psi)": 2000.})
                         for row in rows])


def project(job, rows, td):
    state = {"job_type": job, "hardware_table": rows,
             "well_geometry": {"version": 1, "type": "Vertical", "td_m": td},
             "placement_config": {"job_type": job, "chart_excess_mode": "ignore"}}
    state["placement_config"]["target_row"] = next(iter(hardware_choices(rows, target_descriptions(job))))
    return state


def reference_casing(reverse=False):
    # Owner-supplied depths/diameters. Current ID/weight/joint are synthetic
    # prerequisites for the adapters, not claimed field measurements.
    previous = [("Previous Casing", "53", "20", 18.730),
                ("Previous Casing", "400", "13 3/8", 12.347)]
    if reverse:
        previous.reverse()
    return project('CSG 9 5/8"', hardware(
        ("Casing", "1970", "9 5/8", 8.535), *previous,
        ("Open Hole Size", "400-1970", "12.250", 12.250)), 1970.)


def synthetic_tieback(top=100., explicit=True):
    # All Tie Back measurements in this fixture are synthetic. The upstream
    # workstring is explicit; its OD matches the active OD for scalar mapping.
    rows = [("Tie Back Liner Shoe", f"{top:g}-700" if explicit else "700", "7", 6.),
            ("Previous Casing", "800", "9 5/8", 8.535),
            ("Previous Liner Shoe", "700-1200", "7", 6.),
            ("Open Hole Size", "800-1200", "8.5", 8.5)]
    if top > 0:
        rows.append(("Drill Pipes", f"{top:g}", "7", 6.))
    state = project('TIE BACK LNR 7"', hardware(*rows), 1200.)
    state["placement_config"]["host_row"] = next(iter(hardware_choices(
        state["hardware_table"], {"Previous Casing"})))
    return state


def boundary(geometry):
    return [(s["top_md"], s["bottom_md"], s["od_in"] if s["description"] == "Open Hole Size"
             else s["id_in"]) for s in geometry["enclosing_string"]]


@pytest.mark.parametrize("reverse", [False, True])
def test_reference_nested_csg_uses_immediate_wall_and_analytical_capacity(reverse):
    state = reference_casing(reverse)
    before = pickle.dumps(state)
    geometry = chart.resolve_chart_geometry(state)
    assert boundary(geometry) == [(0., 400., 12.347), (400., 1970., 12.250)]
    for segment, diameter in zip(geometry["capacity_segments"], (12.347, 12.250)):
        expected = math.pi / 4 * (diameter**2 - 9.625**2) / 144 / .3048 / BBL_TO_CUFT
        assert segment["nominal_bbl_per_m"] == pytest.approx(expected, rel=1e-14)
    assert pickle.dumps(state) == before


def test_reference_scalar_centralizer_maps_effective_wall_not_outer_history():
    geometry = centralizer_adapter.to_engine_geometry(reference_casing())
    assert geometry["wellbore"]["prev_casing_id"] == 12.347 * .0254
    assert geometry["wellbore"]["prev_shoe_depth"] == 400.
    assert geometry["wellbore"]["hole_size"] == 12.250 * .0254


def test_explicit_nonzero_tieback_top_preserves_explicit_upstream_path_and_landing():
    state = synthetic_tieback()
    geometry = chart.resolve_chart_geometry(state)
    assert [(s["top_md"], s["bottom_md"], s["description"]) for s in geometry["active_string"]] == [
        (0., 100., "Drill Pipes"), (100., 700., "Tie Back Liner Shoe")]
    centralizer = centralizer_adapter.to_engine_geometry(state)
    assert centralizer["wellbore"]["string_top"] == 100.
    pumping, _ = pumping_simulation._geometry(state, "tieback")
    assert [(s.z_top, s.z_bot) for s in pumping.pipe_sections] == [(0., 100.), (100., 700.), (700., 1200.)]
    assert pumping.track_depth_m == 700.


def test_scalar_tieback_endpoint_without_top_is_not_surface_evidence():
    state = synthetic_tieback(top=0., explicit=False)
    with pytest.raises(ValueError, match="[Tt]op"):
        chart.resolve_chart_geometry(state)


def test_historical_liner_has_nonzero_top_and_actual_nested_host():
    state = project('LNR 5"', hardware(
        ("Drill Pipes", "900", "5", 4.), ("Liner Lap", "900", "5", 4.),
        ("Liner Shoe", "900-1500", "5", 4.),
        ("Previous Casing", "400", "13 3/8", 12.347),
        ("Previous Casing", "800", "9 5/8", 8.535),
        ("Previous Liner Shoe", "600-1100", "7", 6.),
        ("Open Hole Size", "1100-1500", "6.125", 6.125)), 1500.)
    geometry = chart.resolve_chart_geometry(state)
    assert boundary(geometry) == [(0., 600., 8.535), (600., 1100., 6.), (1100., 1500., 6.125)]
    assert next(s for s in geometry["active_string"] if s["description"] == "Liner Shoe")["top_md"] == 900.


def test_outer_installed_history_edit_retires_centralizer_authority():
    import phase_9_centralizer as phase9
    from test_uat_round9h_integration import configured
    catalog = centralizer_adapter.load_official_catalog()
    state = configured(catalog)
    state.update(reference_casing())
    before = phase9.source_signature(state, catalog)
    state["hardware_table"].at[1, "ID (in)"] = 18.729
    assert phase9.source_signature(state, catalog) != before


def test_dynamic_active_body_keeps_measured_upstream_od_in_fluid_path():
    from test_uat_round9e_dynamic_solver import dynamic_state, auxiliary
    from test_uat_round9d_static_solver import zones_for
    state = dynamic_state("liner")
    state["hardware_table"].loc[state["hardware_table"]["Description"] == "Drill Pipes", "Size (in)"] = "5"
    catalog = centralizer_adapter.load_official_catalog()
    # The frozen profile evaluates the active body; the fluid path still
    # includes the actual distinct workstring. No scalar hydraulic substitute.
    assert centralizer_adapter.to_engine_geometry(state)["wellbore"]["string_top"] == 400.
    result = centralizer_adapter.build_dynamic_payload(state, zones_for(catalog, "liner"), catalog, aux_rheology=auxiliary())
    assert result["payload"]["casing"]["od"] == 7. * .0254
    assert chart.resolve_chart_geometry(state)["active_string"][0]["od_in"] == 5.


def test_liner_running_fit_is_separate_from_final_upstream_workstring_wall():
    from test_uat_round9b_geometry import state_for
    state = state_for("liner")
    table = state["hardware_table"]
    host = table.loc[table["Description"] == "Previous Casing"].iloc[0].to_dict()
    host.update({"MD (m)": "100", "ID (in)": 6.5})
    state["hardware_table"] = pd.concat([pd.DataFrame([host]), table], ignore_index=True)
    # The final 5-inch workstring fits, but the 7-inch liner could never pass.
    with pytest.raises(ValueError, match="pass|restriction|fit"):
        chart.resolve_chart_geometry(state)


@pytest.mark.parametrize("fault", ["contradictory_top", "missing_workstring", "missing_receiver", "ambiguous_receiver", "missing_host", "stale_host", "outside_host"])
def test_tieback_insufficient_or_inconsistent_authority_blocks_all_consumers(fault):
    state = synthetic_tieback()
    if fault == "contradictory_top":
        state["placement_config"]["tie_back_liner_lap_m"] = 0.
    elif fault == "missing_workstring":
        state["hardware_table"] = state["hardware_table"].loc[lambda f: f["Description"] != "Drill Pipes"]
    elif fault == "missing_receiver":
        state["hardware_table"] = state["hardware_table"].loc[lambda f: f["Description"] != "Previous Liner Shoe"]
    elif fault == "ambiguous_receiver":
        state["hardware_table"] = pd.concat([state["hardware_table"], state["hardware_table"].iloc[[2]]], ignore_index=True)
    elif fault == "missing_host":
        state["placement_config"].pop("host_row")
    elif fault == "stale_host":
        state["placement_config"]["host_row"] = "obsolete-token"
    else:
        extra = hardware(("Previous Casing", "900", "13 3/8", 12.347))
        state["hardware_table"] = pd.concat([state["hardware_table"], extra], ignore_index=True)
        state["placement_config"]["host_row"] = next(token for token, row in hardware_choices(
            state["hardware_table"], {"Previous Casing"}).items() if row["depth"] == 900.)
    before = pickle.dumps(state)
    for consumer in (chart.resolve_chart_geometry, centralizer_adapter.to_engine_geometry,
                     lambda s: pumping_simulation._geometry(s, "tieback")):
        with pytest.raises(ValueError):
            consumer(state)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize("top,interval", [(0., True), (0., False), (100., True), (100., False)])
def test_explicit_tieback_top_interval_or_metadata_roundtrips_without_inference(top, interval):
    from test_audit_regressions import round_trip
    state = synthetic_tieback(top=top, explicit=interval)
    if not interval:
        state["placement_config"]["tie_back_liner_lap_m"] = top
    # Target row tokens are based on the actual scalar/interval input.
    restored = round_trip(state)
    pd.testing.assert_frame_equal(restored["hardware_table"], state["hardware_table"], check_dtype=False)
    for source in (state, restored):
        active = chart.resolve_chart_geometry(source)["active_string"]
        assert next(s for s in active if s["description"] == "Tie Back Liner Shoe")["top_md"] == top
        assert centralizer_adapter.to_engine_geometry(source)["wellbore"]["string_top"] == top


@pytest.mark.parametrize("fault", ["running_fit", "historical_fit", "duplicate", "missing_hole"])
def test_nested_invalid_physical_geometry_remains_fail_closed_without_mutation(fault):
    state = reference_casing()
    if fault == "running_fit":
        state["hardware_table"].at[2, "ID (in)"] = 9.
    elif fault == "historical_fit":
        state["hardware_table"].at[1, "ID (in)"] = 13.
    elif fault == "duplicate":
        state["hardware_table"] = pd.concat([state["hardware_table"], state["hardware_table"].iloc[[2]]], ignore_index=True)
    else:
        state["hardware_table"] = state["hardware_table"].iloc[:-1]
    before = pickle.dumps(state)
    with pytest.raises(ValueError):
        chart.resolve_chart_geometry(state)
    assert pickle.dumps(state) == before


def test_multiple_effective_cased_ids_remain_valid_chart_but_unrepresentable_centralizer():
    state = reference_casing()
    state["hardware_table"].at[1, "MD (m)"] = "500"
    # Inner 13-3/8 shoe at400, then the measured outer20 wall through500.
    state["hardware_table"].at[3, "MD (m)"] = "500-1970"
    assert boundary(chart.resolve_chart_geometry(state)) == [
        (0., 400., 12.347), (400., 500., 18.730), (500., 1970., 12.250)]
    with pytest.raises(ValueError, match="scalar ID"):
        centralizer_adapter.to_engine_geometry(state)


def test_csg7_immediate_host_comes_from_measured_hardware_not_job_taxonomy():
    state = project('CSG 7"', hardware(
        ("Casing", "2500", "7", 6.), ("Previous Casing", "53", "20", 18.730),
        ("Previous Casing", "400", "13 3/8", 12.347),
        ("Previous Casing", "1970", "9 5/8", 8.535),
        ("Open Hole Size", "1970-2500", "8.5", 8.5)), 2500.)
    assert boundary(chart.resolve_chart_geometry(state)) == [(0., 1970., 8.535), (1970., 2500., 8.5)]


@pytest.mark.parametrize("kind", ["casing", "tieback"])
def test_schematic_retains_physical_history_and_exact_active_top(kind):
    import well_schematic_adapter as schematic
    state = reference_casing() if kind == "casing" else synthetic_tieback()
    payload = schematic.prepare_schematic(state)
    if kind == "casing":
        casings = {(s["size_in"], s["top_md"], s["shoe_md"]) for s in payload["casings"]}
        assert {(20., 0., 53.), (13.375, 0., 400.), (9.625, 0., 1970.)} == casings
        assert payload["open_holes"][0]["top_md"] == 400.
    else:
        active = next(s for s in payload["casings"] if s["type"] == "tieback")
        receiver = next(s for s in payload["casings"] if s["type"] == "liner")
        assert (active["top_md"], active["shoe_md"]) == (100., 700.)
        assert (receiver["top_md"], receiver["shoe_md"]) == (700., 1200.)


def test_explicit_top_is_consumed_by_pumping_signature_even_with_scalar_md():
    state = synthetic_tieback(explicit=False)
    state["placement_config"]["tie_back_liner_lap_m"] = 100.
    before = pumping_simulation.source_signature(state)
    state["placement_config"]["tie_back_liner_lap_m"] = 101.
    assert pumping_simulation.source_signature(state) != before


def test_schematic_cannot_disagree_with_running_restriction_above_liner_hanger():
    import well_schematic_adapter as schematic
    from test_uat_round9b_geometry import state_for
    state = state_for("liner")
    state["placement_config"]["target_row"] = next(iter(hardware_choices(state["hardware_table"], {"Liner Shoe"})))
    host = state["hardware_table"].loc[lambda f: f["Description"] == "Previous Casing"].iloc[0].to_dict()
    host.update({"MD (m)": "100", "ID (in)": 6.5})
    state["hardware_table"] = pd.concat([pd.DataFrame([host]), state["hardware_table"]], ignore_index=True)
    with pytest.raises(ValueError, match="pass|restriction|fit"):
        schematic.prepare_schematic(state)


@pytest.mark.parametrize("kind", ["reference", "liner7", "liner5", "tieback7", "tieback5"])
@pytest.mark.parametrize("physics", ["static", "dynamic"])
def test_scalar_representable_measured_paths_execute_real_frozen_solver(kind, physics):
    from centralizer_fixtures import execute_centralizer
    from test_uat_round9e_dynamic_solver import dynamic_state
    import phase_9_centralizer as phase9
    state = dynamic_state("casing", **{"Tail": 2., "Displacement Fluid": 2.})
    if kind == "reference":
        geometry = reference_casing()
    elif kind.startswith("liner"):
        size, inner = (7., 6.) if kind == "liner7" else (5., 4.)
        geometry = project(f'LNR {size:g}"', hardware(
            ("Drill Pipes", "400", str(size), inner), ("Liner Lap", "400", str(size), inner),
            ("Liner Shoe", "400-1000", str(size), inner),
            ("Previous Casing", "500", "9 5/8", 8.535),
            ("Open Hole Size", "500-1000", "8.5", 8.5)), 1000.)
    else:
        geometry = synthetic_tieback()
        if kind == "tieback5":
            geometry["job_type"] = geometry["placement_config"]["job_type"] = 'TIE BACK LNR 5"'
            selected = geometry["hardware_table"]["Description"].isin(("Tie Back Liner Shoe", "Drill Pipes", "Previous Liner Shoe"))
            geometry["hardware_table"].loc[selected, "Size (in)"] = "5"
            geometry["hardware_table"].loc[selected, "ID (in)"] = 4.
            geometry["placement_config"]["target_row"] = next(iter(hardware_choices(
                geometry["hardware_table"], {"Tie Back Liner Shoe"})))
    state.update(geometry)
    if kind.startswith("tieback"):
        resolved = chart.resolve_chart_geometry(state)
        state["fluids_config"]["params"]["Tail"]["volume"] = (
            chart.interval_volume(resolved["capacity_segments"], 500., 700.) + resolved["shoe_track_bbl"])
    result = execute_centralizer(state, physics=physics)
    assert result["mode"] == "direct"
    assert result["zones"] and all(isinstance(z["count"], int) for z in result["zones"])
    assert phase9.result_is_current(state)
    expected_top = 400. if kind.startswith("liner") else 100. if kind.startswith("tieback") else 0.
    assert state["centralizer_config"]["zones"][0]["top_md"] == expected_top
    if kind.startswith("tieback"):
        selected = state["centralizer_config"]["zones"][0]
        generated = phase9.auto_populate(state)
        assert generated[0]["top_md"] == 100.
        assert generated[-1]["bottom_md"] == 700.
        state["centralizer_config"]["zones"] = [{**zone, "product_nr": selected["product_nr"],
            "custom_product_id": selected["custom_product_id"]} for zone in generated]
        assert phase9.execute(state)["zones"]
        assert phase9.result_is_current(state)


def test_reference_real_word_roundtrip_and_stale_admission(tmp_path):
    from io import BytesIO
    from docx import Document
    import test_audit_regressions as audit
    import project_state
    import phase_9_centralizer as phase9
    import centralizer_report
    from centralizer_fixtures import execute_centralizer
    case = audit.AuditRegressions()
    base = case.configured_app('CSG 9 5/8"').session_state.to_dict()
    base.update(reference_casing())
    app = case.app(audit.round_trip(base))
    case.phase(app, "phase7")
    next(b for b in app.button if b.key.startswith("_sync_btn_main_")).click().run()
    next(b for b in app.button if b.key.startswith("_confirm_lab_btn_main_")).click().run()
    case.healthy(app)
    execute_centralizer(app.session_state, physics="dynamic")
    case.export(app)
    data = app.session_state["_compiled_doc_bytes"]
    (tmp_path / "reference-nested-csg.docx").write_bytes(data)
    document = Document(BytesIO(data))
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    assert "Previous Casing" in cells and "12.347" in cells and "18.73" in cells
    assert len(document._element.body.xpath('.//wp:docPr[@descr="Well Schematic"]')) == 1
    assert boundary(app.session_state["_cement_chart_model"]) == [(0., 400., 12.347), (400., 1970., 12.250)]
    state = app.session_state.to_dict()
    assert phase9.result_is_current(state)
    # A measured outer-shell edit must stale the executed authority even if it
    # leaves the immediate annular boundary and analytical capacities unchanged.
    state["hardware_table"].at[1, "ID (in)"] = 18.729
    assert not phase9.result_is_current(state)
    pending = centralizer_report.prepare_report(state)
    assert pending["current"] is False and pending["analysis"] is None
    project_state.prepare_calculations(state)
    assert "_compiled_doc_bytes" not in state
    restored = audit.round_trip(state)
    assert not phase9.result_is_current(restored)
    pd.testing.assert_frame_equal(restored["hardware_table"], state["hardware_table"], check_dtype=False)
    # Valid physical wall steps can still be outside the scalar solver domain.
    unsupported = deepcopy(state)
    unsupported["hardware_table"].at[1, "MD (m)"] = "500"
    unsupported["hardware_table"].at[3, "MD (m)"] = "500-1970"
    assert len(boundary(chart.resolve_chart_geometry(unsupported))) == 3
    assert not phase9.result_is_current(unsupported)
    from unittest.mock import patch
    import phase_10_procedure as report
    with patch.object(report.st, "session_state", unsupported):
        pending = report.build_master_context()["centralizer_report"]
        assert pending["current"] is False and pending["analysis"] is None
    assert "_compiled_doc_bytes" not in unsupported


def test_interior_landing_retains_receiver_as_wall_above_tie_in_only():
    state = synthetic_tieback()
    state["hardware_table"].loc[2, ["MD (m)", "Size (in)", "ID (in)"]] = ["400-1200", "8", 7.5]
    assert boundary(chart.resolve_chart_geometry(state)) == [(0., 400., 8.535), (400., 700., 7.5)]
    geometry, _ = pumping_simulation._geometry(state, "tieback")
    assert [(s.z_top, s.z_bot, s.do_in, s.di_in) for s in geometry.ann_sections] == [
        (0., 400., 8.535, 7.), (400., 700., 7.5, 7.),
        (700., 800., 8.535, 8.), (800., 1200., 8.5, 8.)]
    with pytest.raises(ValueError, match="scalar ID"):
        centralizer_adapter.to_engine_geometry(state)


@pytest.mark.parametrize("row,value", [(0, "-9.625"), (1, "-20")])
def test_negative_running_or_historical_od_cannot_become_positive_fractional_size(row, value):
    state = reference_casing()
    state["hardware_table"].at[row, "Size (in)"] = value
    state["placement_config"]["target_row"] = next(iter(hardware_choices(state["hardware_table"], {"Casing"})))
    with pytest.raises(ValueError, match="positive|greater than zero"):
        chart.resolve_chart_geometry(state)


def test_schematic_rejects_active_body_larger_than_measured_open_hole():
    import well_schematic_adapter as schematic
    from test_uat_round9b_geometry import state_for
    state = state_for("liner")
    state["placement_config"]["target_row"] = next(iter(hardware_choices(state["hardware_table"], {"Liner Shoe"})))
    state["hardware_table"].loc[state["hardware_table"]["Description"] == "Open Hole Size", ["Size (in)", "ID (in)"]] = ["6.5", 6.5]
    with pytest.raises(ValueError, match="pass|fit|restriction"):
        schematic.prepare_schematic(state)


def test_deepest_liner_top_cannot_overrule_a_different_innermost_receiving_bore():
    state = project('TIE BACK LNR 5"', hardware(
        ("Tie Back Liner Shoe", "100-700", "5", 4.), ("Drill Pipes", "100", "5", 4.),
        ("Previous Casing", "1000", "13 3/8", 12.25),
        ("Previous Liner Shoe", "100-1200", "7", 6.),
        ("Previous Liner Shoe", "200-1100", "9 5/8", 8.535),
        ("Open Hole Size", "1100-1200", "12.25", 12.25)), 1200.)
    state["placement_config"]["host_row"] = next(token for token, row in hardware_choices(
        state["hardware_table"], {"Previous Liner Shoe"}).items() if row["size"] == "7")
    with pytest.raises(ValueError, match="receiving.*(ambiguous|innermost)"):
        chart.resolve_chart_geometry(state)


def test_protected_geometry_engines_catalog_template_and_negative_mutation():
    import hashlib
    from pathlib import Path
    expected = {
        "centralizer_optimizer_engine.py": "b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9",
        "cement_charts_engine.py": "68b275c0c3fd0e804a926d39e1123b451f7e22b2c5aad31f6d0ab3e8236709d4",
        "fluids_charts_module_v1_4_2.py": "ceaaff1311b241c8793fc65b0004a8ca28bef463d93db0957d9b650522bdc5ea",
        "ds_cent_products.json": "837010c1a67a7a9252317f4b2e9b8f08b29f39f431cc8e45cfcc5eb6c94a1329",
        "master_template.docx": "a1128b0e9352e1dd7c8768eecc9335c50858356cee80ed33c0ec275e26c4d08b",
    }
    root = Path(__file__).resolve().parents[1]
    for name, digest in expected.items():
        original = (root / name).read_bytes()
        assert hashlib.sha256(original).hexdigest() == digest
        changed = bytes([original[0] ^ 1]) + original[1:]
        assert hashlib.sha256(changed).hexdigest() != digest


@pytest.mark.parametrize("field", ["Weight (ppf)", "Joint (m)"])
def test_unused_historical_mechanical_metadata_does_not_retire_current_solver(field):
    from test_uat_round9f_phase9 import configured
    import phase_9_centralizer as phase9
    catalog = centralizer_adapter.load_official_catalog()
    state = configured(catalog)
    phase9.execute(state, catalog)
    geometry = centralizer_adapter.to_engine_geometry(state)
    historical = state["hardware_table"]["Description"] == "Previous Casing"
    state["hardware_table"].loc[historical, field] = 42.
    assert centralizer_adapter.to_engine_geometry(state) == geometry
    assert phase9.result_is_current(state, catalog)


@pytest.mark.parametrize("row", [0, 2])
def test_installed_and_running_tubular_id_equal_to_od_is_not_physical(row):
    from engineering_tools import parse_fractional_size
    state = reference_casing()
    state["hardware_table"].at[row, "ID (in)"] = parse_fractional_size(state["hardware_table"].at[row, "Size (in)"])
    with pytest.raises(ValueError, match="ID"):
        chart.resolve_chart_geometry(state)


@pytest.mark.parametrize("source", ["scalar", "unrelated_interval", "earlier_interval"])
def test_c1_selected_receiver_requires_its_own_source_interval_at_tie_in(source):
    from test_uat_round11a_schematic import tieback_state
    import well_schematic_adapter as schematic
    state = tieback_state()
    table = state["hardware_table"]
    if source == "unrelated_interval":
        # A real outer liner has an explicit interval, but cannot authorize the
        # actual inner scalar receiver selected at the 2500-m tie-in.
        extra = table.iloc[2].to_dict()
        extra.update({"MD (m)": "2400-3500", "Size (in)": "8", "ID (in)": 7.5})
        # Synthetic owner-consistent hanger for the additional 8-inch liner.
        hanger = {**extra, "Description": "Previous Liner Lap", "MD (m)": "2400"}
        state["hardware_table"] = pd.concat([table, pd.DataFrame([extra, hanger])], ignore_index=True)
    elif source == "earlier_interval":
        # Even an explicit section of the SAME string cannot authorize a later
        # endpoint-only section spanning the tie-in. Physical geometry is valid.
        table.loc[2, ["Size (in)", "ID (in)"]] = ["8", 7.5]
        table.loc[4, ["MD (m)", "Size (in)", "ID (in)"]] = ["2000", "8", 7.5]
        first = table.iloc[2].to_dict()
        first["MD (m)"] = "2000-2400"
        state["hardware_table"] = pd.concat([table.iloc[:2], pd.DataFrame([first]),
                                              table.iloc[2:]], ignore_index=True)
    before = pickle.dumps(state)
    chart.resolve_chart_geometry(state)
    schematic.prepare_schematic(state)
    with pytest.raises(ValueError, match="explicit old-liner interval"):
        pumping_simulation.prepare_pumping_simulation(state)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize("continuation", ["single", "endpoint_section", "tapered_section"])
def test_c1_explicit_receiver_preserves_measured_multisection_flow_and_json(continuation):
    from test_uat_round11a_schematic import tieback_state
    from test_audit_regressions import round_trip
    from phase_9_centralizer import new_config
    state = tieback_state(True)
    # The old hydraulic-only fixture omits the persisted config's input fields.
    state["centralizer_config"] = {**new_config(), **state["centralizer_config"]}
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": 1000., "Burst (psi)": 2000.})
    expected = [(0., 2500., 6., 7.), (2500., 4000., 6.276, 7.)]
    if continuation != "single":
        table = state["hardware_table"]
        table.at[2, "MD (m)"] = "2500-3300"
        row = table.iloc[2].to_dict()
        row["MD (m)"] = "4000" if continuation == "endpoint_section" else "3300-4000"
        if continuation == "tapered_section":
            row.update({"Size (in)": "6.5", "ID (in)": 5.75})
        state["hardware_table"] = pd.concat([table, pd.DataFrame([row])], ignore_index=True)
        expected = [(0., 2500., 6., 7.), (2500., 3300., 6.276, 7.),
                    (3300., 4000., row["ID (in)"], float(row["Size (in)"]))]
    before = pickle.dumps(state)
    signature = pumping_simulation.source_signature(state)
    for current in (state, round_trip(state)):
        snapshot = pickle.dumps(current)
        geometry = pumping_simulation.prepare_pumping_simulation(current)["inputs"]["geometry"]
        assert [(s.z_top, s.z_bot, s.id_in, s.od_in) for s in geometry.pipe_sections] == expected
        assert geometry.track_depth_m == 2500. and geometry.td_m == 4000.
        assert [(s.z_top, s.z_bot, s.do_in, s.di_in) for s in geometry.ann_sections] == (
            [(0., 3000., 8.535, 7.), (3000., 4000., 8.5, 7.)]
            if continuation != "tapered_section" else
            [(0., 3000., 8.535, 7.), (3000., 3300., 8.5, 7.), (3300., 4000., 8.5, 6.5)])
        assert pumping_simulation.source_signature(current) == signature
        assert pickle.dumps(current) == snapshot
    assert pickle.dumps(state) == before


def test_c1_loss_of_explicit_receiver_blocks_export_and_retires_compiled_document():
    from test_uat_round10a_pumping_simulation import program_state
    from test_audit_regressions import AuditRegressions
    from centralizer_fixtures import execute_centralizer
    import project_state
    import phase_10_procedure as report
    from unittest.mock import patch
    case = AuditRegressions()
    app = case.configured_app('TIE BACK LNR 7"')
    source = program_state("tieback")
    for column in ("Collapse (psi)", "Burst (psi)"):
        source["hardware_table"][column] = app.session_state["hardware_table"].iloc[0][column]
    for key in ("hardware_table", "placement_config"):
        app.session_state[key] = deepcopy(source[key])
    execute_centralizer(app.session_state)
    state = app.session_state.to_dict()
    assert project_state.prepare_calculations(state) == []
    old_signature = pumping_simulation.source_signature(state)
    # The existing interval is 400-1000; only its source authority is removed.
    table = state["hardware_table"]
    hanger = {**table.iloc[2].to_dict(), "Description": "Previous Liner Lap", "MD (m)": "400"}
    table.at[2, "MD (m)"] = "1000"
    state["hardware_table"] = pd.concat([table, pd.DataFrame([hanger])], ignore_index=True)
    assert pumping_simulation.source_signature(state) != old_signature
    # Sentinel document bytes exercise invalidation, not successful admission.
    state.update(_compiled_doc_bytes=b"old", _compiled_doc_filename="old.docx", _compiled_doc_signature="old")
    issues = project_state.prepare_calculations(state)
    assert any("Pumping Simulation" in issue and "explicit old-liner interval" in issue for issue in issues), issues
    assert not any(key.startswith("_compiled_doc_") for key in state)
    with patch.object(report.st, "session_state", state):
        with pytest.raises(ValueError, match="explicit old-liner interval"):
            report.build_master_context()


@pytest.mark.parametrize("both_hangers", [False, True])
def test_c2_nested_receiver_drawing_is_independent_of_hydraulic_admission(both_hangers):
    from test_uat_round11a_schematic import tieback_state
    from test_audit_regressions import round_trip
    from phase_9_centralizer import new_config
    from unittest.mock import patch
    import well_schematic_adapter as schematic
    state = tieback_state()
    state["centralizer_config"] = {**new_config(), **state["centralizer_config"]}
    # Synthetic mechanical prerequisites for the real project JSON schema.
    state["hardware_table"] = state["hardware_table"].assign(**{"Collapse (psi)": 1000., "Burst (psi)": 2000.})
    table = state["hardware_table"]
    # Explicitly synthetic outer liner/hanger, not owner field measurements.
    outer = {**table.iloc[2].to_dict(), "MD (m)": "2400-3500", "Size (in)": "8", "ID (in)": 7.5}
    extra = [outer]
    if both_hangers:
        extra.append({**outer, "Description": "Previous Liner Lap", "MD (m)": "2400"})
    state["hardware_table"] = pd.concat([table, pd.DataFrame(extra)], ignore_index=True)
    before = pickle.dumps(state)
    interval = deepcopy(state)
    interval["hardware_table"].at[2, "MD (m)"] = "2500-4000"
    payload = schematic.prepare_schematic(state)
    assert payload == schematic.prepare_schematic(interval)
    tb = payload["casings"][payload["current_job"]["target_index"]]
    receiver = payload["casings"][tb["landing_liner_index"]]
    assert (tb["top_md"], tb["shoe_md"], receiver["size_in"],
            receiver["top_md"], receiver["shoe_md"]) == (0., 2500., 7., 2500., 4000.)
    hole = payload["open_holes"][0]
    # Drilled bore originates at the casing shoe, not the outer liner's3500-m
    # installed annular-wall transition (whose7.5-inch bore cannot drill8.5in).
    assert (hole["top_md"], hole["bottom_md"], hole["hole_size_in"]) == (3000., 4000., 8.5)
    for source in (state, round_trip(state), interval, round_trip(interval)):
        snapshot = pickle.dumps(source)
        with patch.object(pumping_simulation, "_geometry", side_effect=AssertionError("Schematic called Pumping")), \
             patch.object(pumping_simulation, "_tieback_paths", side_effect=AssertionError("Schematic called Pumping")):
            assert schematic.prepare_schematic(source) == payload
        assert pickle.dumps(source) == snapshot
    with pytest.raises(ValueError, match="explicit old-liner interval"):
        pumping_simulation.prepare_pumping_simulation(state)
    assert pumping_simulation.prepare_pumping_simulation(interval)["inputs"]["geometry"].td_m == 4000.
    assert pickle.dumps(state) == before


R15A_INITIAL = [('CSG 30"', 30., 36.), ('CSG 24"', 24., 28.),
                ('CSG 20"', 20., 26.), ('CSG 18 5/8"', 18.625, 22.)]


def initial_casing(job, size, hole, previous=False):
    rows = [('Casing', '150', str(size), size-1.)]
    if previous:
        rows.append(('Previous Casing', '50', str(hole+2.), hole+1.))
    rows.append(('Open Hole Size', '50-150' if previous else '0-150', str(hole), hole))
    return project(job, hardware(*rows), 150.)


@pytest.mark.parametrize('job,size,hole', R15A_INITIAL)
def test_r15a_first_casing_uses_explicit_surface_hole(job, size, hole):
    state = initial_casing(job, size, hole)
    before = pickle.dumps(state)
    geom = chart.resolve_chart_geometry(state)
    assert boundary(geom) == [(0., 150., hole)]
    expected = math.pi/4*(hole**2-size**2)/144/.3048/BBL_TO_CUFT
    assert geom['capacity_segments'] == [dict(top_md=0.,bottom_md=150.,
        nominal_bbl_per_m=expected,bbl_per_m=expected,kind='open_hole')]
    assert chart.interval_volume(geom['capacity_segments'],0.,150.) == pytest.approx(150.*expected)
    assert pickle.dumps(state) == before


@pytest.mark.parametrize('job,size,hole', R15A_INITIAL)
def test_r15a_initial_casing_retains_physical_previous_path(job, size, hole):
    state=initial_casing(job,size,hole,previous=True)
    geometry=chart.resolve_chart_geometry(state)
    assert boundary(geometry)==[(0.,50.,hole+1.),(50.,150.,hole)]
    assert [v['kind'] for v in geometry['capacity_segments']]==['cased','open_hole']


@pytest.mark.parametrize('fault', ['missing','gap','overlap','undersized','equal','bit','id_missing','duplicate_string'])
def test_r15a_initial_casing_invalid_hole_or_string_never_fabricates_wall(fault):
    state=initial_casing('CSG 20"',20.,26.)
    t=state['hardware_table']
    if fault=='missing':state['hardware_table']=t.iloc[:1].copy()
    elif fault in ('gap','overlap'):
        t.at[1,'MD (m)']='0-70'
        row=t.iloc[1].to_dict();row['MD (m)']='80-150' if fault=='gap' else '60-150'
        state['hardware_table']=pd.concat([t,pd.DataFrame([row])],ignore_index=True)
    elif fault in ('undersized','equal'):
        t.loc[1,['Size (in)','ID (in)']]=['19' if fault=='undersized' else '20',19. if fault=='undersized' else 20.]
    elif fault=='bit':t.at[1,'ID (in)']=25.
    elif fault=='id_missing':t.at[1,'ID (in)']=None
    else:state['hardware_table']=pd.concat([t,t.iloc[:1]],ignore_index=True)
    before=pickle.dumps(state)
    with pytest.raises(ValueError):chart.resolve_chart_geometry(state)
    assert pickle.dumps(state)==before


def test_r15a_initial_measured_sections_excess_and_placement_share_capacity():
    state=initial_casing('CSG 20"',20.,26.)
    t=state['hardware_table'];t.at[1,'MD (m)']='0-70'
    row=t.iloc[1].to_dict();row['MD (m)']='70-150'
    state['hardware_table']=pd.concat([t,pd.DataFrame([row])],ignore_index=True)
    state['placement_config'].update(chart_excess_mode='apply',excess_csg_oh_pct=20.)
    geom=chart.resolve_chart_geometry(state)
    expected=math.pi/4*(26.**2-20.**2)/144/.3048/BBL_TO_CUFT*1.2
    assert chart.interval_volume(geom['capacity_segments'],0.,150.)==pytest.approx(expected*150.)
    state['fluids_config']={'active':['Main'],'params':{'Main':{'volume':geom['shoe_track_bbl']+expected*50.,'density':'118'}}}
    cement=chart.resolve_cement_placement(state,geom)[0]
    assert cement['top_md']==pytest.approx(100.)
    assert cement['in_well_bbl']+cement['shoe_track_bbl']==pytest.approx(cement['entered_bbl'])


@pytest.mark.parametrize('kind',['liner','tieback'])
def test_r15a_measured_hole_cannot_replace_liner_or_tieback_history(kind):
    if kind=='liner':
        state=project('LNR 7"',hardware(('Drill Pipes','50','5',4.),('Liner Lap','50','7',6.),
            ('Liner Shoe','50-150','7',6.),('Open Hole Size','0-150','9',9.)),150.)
    else:
        state=project('TIE BACK LNR 7"',hardware(('Tie Back Liner Shoe','0-150','7',6.),('Open Hole Size','0-150','9',9.)),150.)
    with pytest.raises(ValueError,match='Previous|host|Liner'):chart.resolve_chart_geometry(state)


@pytest.fixture(scope='module')
def r15a_report_source():
    import test_audit_regressions as audit
    cache={}
    def get(job):
        if job not in cache:
            cache[job]=audit.round_trip(audit.AuditRegressions().configured_app(job).session_state.to_dict())
        return deepcopy(cache[job])
    return get


@pytest.mark.parametrize('job,size,hole',R15A_INITIAL)
@pytest.mark.parametrize('previous',[False,True])
def test_r15a_actual_first_casing_word_and_json(r15a_report_source,job,size,hole,previous,tmp_path):
    import json
    from io import BytesIO
    from docx import Document
    import project_state as ps
    import test_audit_regressions as audit
    import well_schematic_adapter as schematic
    import well_schematic_engine as renderer
    from test_uat_round11a_schematic import schematic_picture
    case=audit.AuditRegressions()
    source=r15a_report_source(job)
    source.update(initial_casing(job,size,hole,previous))
    source.update(geo_md=150.,geo_tvd=150.)
    source['hardware_editor_draft']=source['hardware_table'].copy(deep=True)
    source['fluids_config']['params']['Main']['volume']=1000.  # Synthetic measured large-bore job, above shoe-track volume.
    ps.refresh_well_derived(source)
    source=audit.round_trip(source)
    geom=chart.resolve_chart_geometry(source)
    assert chart.resolve_cement_placement(source,geom)[0]['shoe_track_bbl']==geom['shoe_track_bbl']
    app=case.app(source)
    case.phase(app,'phase7')
    keep=[b for b in app.button if b.label=='Keep reviewed lab entries']
    if keep:keep[0].click().run()
    confirm=[b for b in app.button if b.label=='Confirm measured lab results']
    for button in confirm:
        assert not button.disabled
        app.button(key=button.key).click().run()
    assert ps.prepare_calculations(app.session_state.to_dict())==[]
    physical=deepcopy((app.session_state['hardware_table'],app.session_state['well_geometry'],
                       app.session_state['placement_config'],app.session_state['fluids_config']))
    case.export(app)
    data=app.session_state['_compiled_doc_bytes'];doc=Document(BytesIO(data))
    assert doc._element.xpath('.//wp:docPr[@descr="Static Well Security and Fluid Sequence"]')
    assert not doc._element.xpath('.//wp:docPr[@descr="Pumping Simulation Charts"]')
    _,image=schematic_picture(doc)
    (tmp_path/'initial-casing.docx').write_bytes(data);(tmp_path/'embedded-schematic.png').write_bytes(image)
    pd.testing.assert_frame_equal(app.session_state['hardware_table'],physical[0])
    assert ps.fingerprint((app.session_state['well_geometry'],app.session_state['placement_config'],app.session_state['fluids_config']))==ps.fingerprint(physical[1:])
    saved=audit.round_trip(app.session_state.to_dict())
    assert chart.resolve_chart_geometry(saved)==geom
    payload=schematic.prepare_schematic(saved)
    assert renderer.resolve_depth_axis(payload)==(165.,[0.,82.5,165.])
    assert payload['casings'][-1]['shoe_md']==150.
    assert payload['open_holes'][0]['hole_size_in']==hole
    (tmp_path/'geometry-and-axis.json').write_text(json.dumps({'job':job,'previous':previous,'geometry':geom,
        'axis':[165.,[0.,82.5,165.]],'payload':payload},indent=2))


# BUG-01: measured geometry and explicitly synthetic solver/report prerequisites.
def bug01_dq19():
    rows = [
        ('Previous Casing', '253.0', '18 5/8', 17.755, 87.5),
        ('Previous Casing', '2190', '13 3/8', 12.347, 72.),
        ('Previous Casing', '2800', '9 5/8', 8.535, 53.5),
        ('Previous Liner Lap', '2650', '7', 6.094, 32.),
        ('Previous Liner Shoe', '3839', '7', 6.094, 32.),
        ('Drill Pipes', '3419', '3 1/2', 2.764, 18.),
        ('Liner Lap', '3419', '5', 4.276, 18.),
        ('Liner Shoe', '4500', '5', 4.276, 18.),
        ('Open Hole Size', '4550', '6', 6., 0.),
    ]
    frame = pd.DataFrame([{'Description': desc, 'MD (m)': md, 'Size (in)': size,
        'ID (in)': inner, 'Joint (m)': 0. if desc == 'Open Hole Size' else 12.2,
        'Weight (ppf)': weight, 'Grade': '-', 'Collapse (psi)': 0., 'Burst (psi)': 0.}
        for desc, md, size, inner, weight in rows])
    state = project('LNR 5"', frame, 4550.)
    assert state['placement_config']['target_row'] == '569a8120e7b2faf846abe57d5ccd6b646f6743e1d3d120fd62a01a49769226e2'
    state['centralizer_config'] = {'version': 1, 'physics_mode': 'static', 'placement_mode': 'optimize',
        'custom_products': [], 'aux_rheology': {}, 'zones': [
            {'top_md': top, 'bottom_md': bottom, 'density': '1/4', 'target_standoff_pct': 67.,
             'product_nr': None, 'custom_product_id': None} for top, bottom in ((3419., 3839.), (3839., 4500.))]}
    return state


def bug01_geometry_case(job):
    if job == 'LNR 5"':
        return bug01_dq19()
    if job in ('CSG 13 3/8"', 'CSG 9 5/8"'):
        od, inner, host, host_id, hole = ((13.375, 12.25, 20., 18.73, 17.5)
            if job == 'CSG 13 3/8"' else (9.625, 8.535, 13.375, 12.347, 12.25))
        return project(job, hardware(('Previous Casing', '400', str(host), host_id),
            ('Casing', '1200', str(od), inner), ('Open Hole Size', '400-1200', str(hole), hole)), 1200.)
    if job == 'LNR 7"':
        return project(job, hardware(('Previous Casing', '700', '9 5/8', 8.535),
            ('Drill Pipes', '400', '3 1/2', 2.764), ('Liner Lap', '400', '7', 6.094),
            ('Liner Shoe', '1200', '7', 6.094), ('Open Hole Size', '700-1200', '8.5', 8.5)), 1200.)
    if job == 'LNR 4 1/2"':
        return project(job, hardware(('Previous Casing', '300', '9 5/8', 8.535),
            ('Previous Liner Shoe', '200-700', '7', 6.094), ('Drill Pipes', '400', '3 1/2', 2.764),
            ('Liner Lap', '400', '4 1/2', 4.), ('Liner Shoe', '1200', '4 1/2', 4.),
            ('Open Hole Size', '700-1200', '6', 6.)), 1200.)
    od, inner = {'TIE BACK LNR 7"': ('7', 6.094), 'TIE BACK LNR 5"': ('5', 4.276),
                 'TIE BACK LNR 4 1/2"': ('4 1/2', 4.)}[job]
    rows = [('Previous Casing', '1100' if od == '7' else '300', '9 5/8', 8.535)]
    if od != '7':
        rows.append(('Previous Liner Shoe', '100-1100', '7', 6.094))
    host_index = len(rows)-1
    rows += [('Previous Liner Shoe', '700-1200', od, inner), ('Drill Pipes', '200', '3 1/2', 2.764),
             ('Tie Back Liner Shoe', '200-700', od, inner),
             ('Open Hole Size', '1100-1200', '8.5' if od == '7' else '6', 8.5 if od == '7' else 6.)]
    state = project(job, hardware(*rows), 1200.)
    state['placement_config']['host_row'] = next(iter(hardware_choices(
        state['hardware_table'].iloc[[host_index]], {'Previous Casing', 'Previous Liner Shoe'})))
    return state


def test_bug01_dq19_active_wall_ignores_only_upstream_cased_ids():
    state = bug01_dq19()
    before = pickle.dumps(state)
    assert boundary(chart.resolve_chart_geometry(state)) == [
        (0., 2650., 8.535), (2650., 3839., 6.094), (3839., 4500., 6.)]
    result = centralizer_adapter.to_engine_geometry(state)
    assert result['wellbore'] == {'prev_casing_id': 6.094*.0254, 'hole_size': 6.*.0254,
        'prev_shoe_depth': 3839., 'open_hole_top': 3839., 'open_hole_bottom': 4500.,
        'string_top': 3419., 'string_shoe': 4500.}
    assert (result['wellbore']['prev_casing_id']-result['casing']['od'])/2/.0254 == pytest.approx(.547)
    assert (result['wellbore']['hole_size']-result['casing']['od'])/2/.0254 == pytest.approx(.5)
    assert pickle.dumps(state) == before


def test_bug01_tieback_four_half_is_an_explicit_new_capability():
    import materials_db as db
    job = 'TIE BACK LNR 4 1/2"'
    assert job in db.JOB_TYPES
    assert chart.chart_job_kind(job) == 'tieback'
    result = centralizer_adapter.to_engine_geometry(bug01_geometry_case(job))
    assert result['casing']['od'] == 4.5*.0254
    assert result['wellbore']['prev_casing_id'] == result['wellbore']['hole_size'] == 6.094*.0254
    assert result['wellbore']['prev_shoe_depth'] == result['wellbore']['string_shoe'] == 700.


BUG01_JOBS = ('CSG 13 3/8"', 'CSG 9 5/8"', 'LNR 7"', 'LNR 5"', 'LNR 4 1/2"',
              'TIE BACK LNR 7"', 'TIE BACK LNR 5"', 'TIE BACK LNR 4 1/2"')


def bug01_solver_state(job):
    import materials_db as db
    import phase_9_centralizer as phase9
    import project_state as ps
    import test_audit_regressions as audit
    state = bug01_geometry_case(job)
    # All fluid, rheology and product prerequisites here are explicitly synthetic;
    # only bug01_dq19's Hardware/target are the sanitized owner measurements.
    state.update(mud_density='80', plastic_viscosity='16', yield_point='10',
        well_data={'mud_density': '80', 'plastic_viscosity': '16', 'yield_point': '10'},
        fluids_config={'active': ['Main', 'Displacement Fluid'], 'params': {
            name: {'volume': 8., 'density': '118' if name == 'Main' else '80',
                   'pump_rate': '4', 'material_name': db.DEFAULT_MATERIAL_NAMES[name]}
            for name in ('Main', 'Displacement Fluid')}},
        lab_qc_params={'Main': {'rheology': audit.valid_export_rheology_fixture()}})
    ps.refresh_fluids(state)
    geometry = centralizer_adapter.to_engine_geometry(state)
    od = geometry['casing']['od']/.0254
    catalog = centralizer_adapter.load_official_catalog()
    product = next(p for p in centralizer_adapter.filter_official_products(catalog, od)
                   if p['kind'] == 'rigid' and od < p['max_od_in'] <= min(
                       geometry['wellbore']['prev_casing_id'], geometry['wellbore']['hole_size'])/.0254)
    top, shoe, seat = (geometry['wellbore'][k] for k in ('string_top','string_shoe','prev_shoe_depth'))
    bounds = [top, seat, shoe] if top < seat < shoe else [top, shoe]
    config = phase9.new_config()
    config['zones'] = [{'top_md': a, 'bottom_md': b, 'density': '1/4', 'target_standoff_pct': 67.,
                       'product_nr': product['nr'], 'custom_product_id': None} for a,b in zip(bounds,bounds[1:])]
    state['centralizer_config'] = config
    return state


@pytest.mark.parametrize('job', BUG01_JOBS)
@pytest.mark.parametrize('physics,mode', [('static','direct'),('static','optimize'),('dynamic','direct'),('dynamic','optimize')])
def test_bug01_eight_hardware_resolved_jobs_execute_all_frozen_modes(job, physics, mode):
    import hashlib
    from pathlib import Path
    import phase_9_centralizer as phase9
    import centralizer_optimizer_engine as engine
    import centralizer_report
    state = bug01_solver_state(job)
    state['centralizer_config'].update(physics_mode=physics, placement_mode=mode)
    geometry = chart.resolve_chart_geometry(state)
    source = pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')})
    snapshot = centralizer_adapter.build_fluid_snapshot(state)
    assert snapshot['capacity_bbl']['inside'] == pytest.approx(sum(
        (s['bottom_md']-s['top_md'])*chart._capacity(s['id_in']) for s in geometry['active_string']), rel=1e-14)
    assert snapshot['capacity_bbl']['annulus'] == chart.interval_volume(geometry['capacity_segments'], 0., geometry['shoe_md'])
    result = phase9.execute(state)
    assert result['mode'] == mode and result['profile']['centralizer_md']
    assert phase9.result_is_current(state)
    assert centralizer_report.prepare_report(state)['analysis'] is not None
    assert pickle.dumps({k:v for k,v in state.items() if not k.startswith('_')}) == source
    payload = (centralizer_adapter.build_static_payload(state,state['centralizer_config']['zones'],centralizer_adapter.load_official_catalog())
        if physics == 'static' else centralizer_adapter.build_dynamic_payload(state,state['centralizer_config']['zones'],centralizer_adapter.load_official_catalog())['payload'])
    frozen = engine.compute_standoff_profile(payload) if mode == 'direct' else engine.optimize_placement(payload)
    assert result['profile'] == frozen
    assert hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest() == 'b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9'
    if 'TIE BACK' in job:
        assert all(s['description'] != 'Open Hole Size' for s in geometry['enclosing_string']
                   if s['bottom_md'] > 200.)
        assert payload['wellbore']['prev_shoe_depth'] == payload['wellbore']['string_shoe']
        assert payload['wellbore']['hole_size'] == payload['wellbore']['prev_casing_id']
        zones = phase9.auto_populate(state)
        assert zones and all(z['bottom_md'] <= 700. and z['product_nr'] is None for z in zones)
    # A source edit retires currentness even when it only changes upstream flow.
    previous = deepcopy(state)
    state['hardware_table'].loc[state['hardware_table']['Description']=='Previous Casing','ID (in)'] -= .001
    assert not phase9.result_is_current(state)
    assert centralizer_report.prepare_report(state)['current'] is False
    assert phase9.result_is_current(previous)


def test_bug01_dq19_null_products_stay_incomplete_after_geometry_fix():
    import phase_9_centralizer as phase9
    state = bug01_dq19()
    # No fabricated lab/product is needed to demonstrate the next real prerequisite.
    with pytest.raises(ValueError, match='select exactly one Official or Custom'):
        centralizer_adapter.build_static_payload(state,state['centralizer_config']['zones'],centralizer_adapter.load_official_catalog())
    assert not phase9.result_is_current(state)


@pytest.mark.parametrize('job', ['LNR 4 1/2"','LNR 5"','TIE BACK LNR 5"','TIE BACK LNR 4 1/2"'])
def test_bug01_upstream_restrictions_still_reject_deeper_body(job):
    state = bug01_geometry_case(job)
    # This restriction is above the active Top, yet the deeper OD must pass it.
    row = state['hardware_table'].index[state['hardware_table']['Description']=='Previous Casing'][0]
    state['hardware_table'].at[row,'ID (in)'] = 4.4
    with pytest.raises(ValueError, match='clearance|restriction|host|pass'):
        centralizer_adapter.to_engine_geometry(state)


@pytest.mark.parametrize('fault', ['missing_host','stale_host','short_host','receiver_missing','receiver_ambiguous','target','top','gap','duplicate','clearance'])
def test_bug01_tieback_new_job_physical_negatives_are_not_bypassed(fault):
    state = bug01_geometry_case('TIE BACK LNR 4 1/2"')
    if fault == 'receiver_missing':
        # Removing the inner receiver alone leaves the measured 7-inch liner
        # as a lawful receiver. Use a cased-host fixture with NO liner instead.
        state = bug01_geometry_case('TIE BACK LNR 7"')
    table = state['hardware_table']
    if fault == 'missing_host': state['placement_config'].pop('host_row')
    elif fault == 'stale_host': state['placement_config']['host_row'] = 'stale-token'
    elif fault == 'short_host': table.at[1,'MD (m)'] = '100-600'
    elif fault == 'receiver_missing': state['hardware_table'] = table.drop(index=1)
    elif fault == 'receiver_ambiguous': state['hardware_table'] = pd.concat([table,table.iloc[[2]]],ignore_index=True)
    elif fault == 'target': state['placement_config']['target_row'] = 'stale-token'
    elif fault == 'top': table.at[4,'MD (m)'] = '700'
    elif fault == 'gap': table.at[3,'MD (m)'] = '190'
    elif fault == 'duplicate': state['hardware_table'] = pd.concat([table,table.iloc[[1]]],ignore_index=True)
    else: table.at[1,'ID (in)'] = 4.5
    with pytest.raises(ValueError, match='host|Host|Top|target|Target|Previous|Liner|clearance|overlap|missing|continuous|receiving|restriction|pass|ambiguous'):
        centralizer_adapter.to_engine_geometry(state)


@pytest.fixture(scope='module')
def bug01_reviewed_report_base():
    import test_audit_regressions as audit
    # Real existing UI sequence: formulation, measured Fann/QC and explicit review.
    return audit.AuditRegressions().configured_app('CSG 9 5/8"').session_state.to_dict()


@pytest.mark.parametrize('job', BUG01_JOBS)
def test_bug01_actual_ui_restore_pumping_schematic_and_current_word(bug01_reviewed_report_base, job, tmp_path):
    import test_audit_regressions as audit
    import project_state as ps
    import phase_9_centralizer as phase9
    import phase_10_procedure as report
    import materials_db as db
    import well_schematic_adapter as schematic
    from test_uat_round10c_integration import save_project, restore_project, build
    from test_uat_round9g_centralizer_word import ix_region
    from docx import Document
    from io import BytesIO
    case = audit.AuditRegressions()
    app = case.app(deepcopy(bug01_reviewed_report_base))
    case.phase(app,'phase1')
    assert job in app.selectbox(key='_w_job_type').options
    app.selectbox(key='_w_job_type').set_value(job).run()
    case.healthy(app)
    assert app.session_state['doc_control']['request_description'] == ps.request_description_for_job(job)
    measured = bug01_geometry_case(job)
    for key in ('hardware_table','well_geometry','placement_config'):
        app.session_state[key] = deepcopy(measured[key])
    for name in ('Main','Displacement Fluid'):
        app.session_state['fluids_config']['params'][name]['volume'] = 8.
    app.session_state['cement_params']['Main'].update(top_mode='Not entered',top_depth=None,report_bottom_depth=None)
    case.phase(app,'phase2_3')
    case.phase(app,'phase5')
    case.phase(app,'phase7')
    sync = next((b for b in app.button if (b.key or '').startswith('_sync_btn_main_')),None)
    if sync is not None: sync.click().run()
    confirm = next(b for b in app.button if (b.key or '').startswith('_confirm_lab_btn_main_'))
    assert not confirm.disabled
    confirm.click().run()
    state = app.session_state.to_dict()
    assert ps.prepare_calculations(state) == []
    # Supply an explicit real catalog selection, not a fabricated current receipt.
    prerequisites = bug01_solver_state(job)
    state['centralizer_config'] = deepcopy(prerequisites['centralizer_config'])
    state['centralizer_config'].update(physics_mode='dynamic',placement_mode='direct')
    phase9.execute(state)
    assert phase9.result_is_current(state)
    source = pickle.dumps(state['hardware_table'])
    restored = restore_project(save_project(type('Project',(),{'session_state':state})()))
    assert restored.session_state['job_type'] == job
    pd.testing.assert_frame_equal(restored.session_state['hardware_table'],state['hardware_table'],check_dtype=False)
    assert not phase9.result_is_current(restored.session_state)
    assert not any(k.startswith('_compiled_doc_') for k in restored.session_state.to_dict())
    case.phase(restored,'phase9')
    restored.button(key='_centralizer_execute').click().run()
    case.healthy(restored)
    assert phase9.result_is_current(restored.session_state)
    assert [z['product_nr'] for z in restored.session_state['centralizer_config']['zones']] == [z['product_nr'] for z in state['centralizer_config']['zones']]
    drawing = schematic.prepare_schematic(restored.session_state)
    assert drawing['current_job']['type'] == chart.chart_job_kind(job)
    prepared = pumping_simulation.prepare_pumping_simulation(restored.session_state)
    assert prepared['applicable'] and prepared['inputs']['geometry'].track_depth_m == chart.resolve_chart_geometry(state)['shoe_md']
    if 'TIE BACK' in job:
        # The genuine hydraulic continuation goes below tie-in; it is not a
        # fabricated open-hole section in the active force solve.
        assert prepared['inputs']['geometry'].td_m == 1200.
        assert centralizer_adapter.to_engine_geometry(state)['wellbore']['prev_shoe_depth'] == 700.
    data = build(restored)
    assert phase9.result_is_current(restored.session_state)
    doc = Document(BytesIO(data));region = ix_region(doc)
    hardware_tables = [t for t in doc.tables if t.cell(0,0).text == 'Tubular and Casing Hardware']
    assert len(hardware_tables) == 1
    hardware_table = hardware_tables[0]
    assert len(hardware_table.columns) == len(hardware_table._tbl.tblGrid.gridCol_lst) == 10
    assert [c.text for c in hardware_table.rows[1].cells] == [
        'Description', 'MD', 'Size', 'ID', 'Joint', 'Weight', 'Grade', 'Collapse', 'Burst']
    from lxml import etree
    reference = next(t for t in Document(report.TEMPLATE_PATH).tables
                     if t.cell(0,0).text == 'Tubular and Casing Hardware')
    xml = lambda node: etree.tostring(node, method='c14n')
    assert xml(hardware_table._tbl.tblGrid) == xml(reference._tbl.tblGrid)
    for actual, original in zip(hardware_table.rows[:3], reference.rows[:3]):
        assert xml(actual._tr) == xml(original._tr)
    descriptions = state['hardware_table']['Description'].tolist()
    assert [r.cells[0].text for r in hardware_table.rows[3:3+len(descriptions)]] == descriptions
    from phase_2_3_well_data import HARDWARE_COLUMNS
    material_row = reference.rows[4]
    for actual, source_row in zip(hardware_table.rows[3:3+len(descriptions)],
                                  state['hardware_table'].to_dict('records')):
        assert len(actual.cells) == 9
        assert xml(actual._tr.trPr) == xml(material_row._tr.trPr)
        for cell, original, field in zip(actual.cells, material_row.cells, HARDWARE_COLUMNS):
            assert xml(cell._tc.tcPr) == xml(original._tc.tcPr)
            value = source_row[field]
            if source_row['Description'] == 'Open Hole Size' and field in (
                    'Joint (m)', 'Weight (ppf)', 'Grade', 'Collapse (psi)', 'Burst (psi)'):
                expected = '-'
            elif field == 'MD (m)' and '-' not in str(value):
                expected = f'{float(value):.1f}'
            else:
                expected = str(value)
            assert cell.text == expected
    tables = [t for t in doc.tables if t._tbl in region]
    assert [len(t.rows) for t in tables] == [4,2+len(state['centralizer_config']['zones'])]
    assert tables[0].cell(3,1).text == f"{chart.resolve_chart_geometry(state)['shoe_md']:.1f} m"
    assert any(e.xpath('.//w:drawing') for e in region)
    assert any(c.text.strip() not in ('','-') for row in tables[1].rows[2:] for c in row.cells)
    assert len(region[-1].xpath('.//w:br[@w:type="page"]')) == 1
    assert restored.session_state['_compiled_doc_signature'] != ''
    assert pickle.dumps(state['hardware_table']) == source
    (tmp_path/'current-centralizer-report.docx').write_bytes(data)
    (tmp_path/'canonical-hardware.json').write_text(state['hardware_table'].to_json(orient='records'))
    if job == 'TIE BACK LNR 4 1/2"':
        assert restored.session_state['hole_size'] == db.DEFAULT_HOLE_SIZES[job] == '6"'
        assert 4.5 == prepared['inputs']['geometry'].pipe_sections[0].od_in or any(
            s.od_in == 4.5 for s in prepared['inputs']['geometry'].pipe_sections)
        (tmp_path/'source-project.json').write_bytes(save_project(restored))
    # A valid consumed Hardware edit retires the old report and Centralizer;
    # the new labels must not conceal stale result/download authority.
    case.phase(restored, 'phase2_3')
    case.hardware_event(restored, {'edited_rows': {'0': {'ID (in)': float(state['hardware_table'].iloc[0]['ID (in)'])-.001}}})
    case.phase(restored, 'phase10')
    assert not phase9.result_is_current(restored.session_state)
    assert '_compiled_doc_bytes' not in restored.session_state


@pytest.mark.parametrize('change', ['host_id','host_md','host_token','top','receiver','od','zone','product','fluid'])
def test_bug01_new_tieback_sources_retire_current_results(change):
    import phase_9_centralizer as phase9
    import centralizer_report
    state = bug01_solver_state('TIE BACK LNR 4 1/2"')
    phase9.execute(state)
    assert phase9.result_is_current(state)
    table = state['hardware_table']
    if change == 'host_id': table.at[1,'ID (in)'] = 6.095
    elif change == 'host_md': table.at[1,'MD (m)'] = '100-1099'
    elif change == 'host_token': state['placement_config']['host_row'] = 'retired-host'
    elif change == 'top': table.at[4,'MD (m)'] = '201-700'
    elif change == 'receiver': table.at[2,'ID (in)'] = 3.99
    elif change == 'od': table.at[4,'Size (in)'] = '4.6'
    elif change == 'zone': state['centralizer_config']['zones'][0]['density'] = '1/3'
    elif change == 'product': state['centralizer_config']['zones'][0]['product_nr'] = None
    else: state['fluids_config']['params']['Displacement Fluid']['volume'] = 9.
    assert not phase9.result_is_current(state)
    report = centralizer_report.prepare_report(state)
    assert report['current'] is False and report['analysis'] is None


# CFW128 Batch A: inert source projection only, never a hydraulic request.
@pytest.mark.parametrize('job', BUG01_JOBS)
def test_cfw128_canonical_geometry_copies_are_inert_and_do_not_touch_source(job):
    from cfw128_adapter import snapshot_geometry
    state = bug01_geometry_case(job)
    before = pickle.dumps(state)
    frame = state['hardware_table']
    result = snapshot_geometry(state, app_source_sha='146d9694d8e6c69fb3d03091a8e573b930155475')
    assert result.status in ('GEOMETRY_REPRESENTABLE', 'ENGINE_INTERFACE_NOT_REPRESENTABLE')
    assert all(getattr(result, k) is False for k in ('enabled', 'ready_to_run', 'hb_admissible', 'hydraulic_admissible'))
    resolved = chart.resolve_chart_geometry(state)
    assert [(s.top_md, s.bottom_md, s.od_in, s.id_in, s.description) for s in result.active_sections] == [
        (s['top_md'], s['bottom_md'], s['od_in'], s['id_in'], s['description']) for s in resolved['active_string']]
    assert [(s.top_md, s.bottom_md, s.id_in) for s in result.enclosing_sections] == [
        (s['top_md'], s['bottom_md'], s['id_in']) for s in resolved['enclosing_string']]
    assert result == snapshot_geometry(state, app_source_sha=result.app_source_sha)
    assert state['hardware_table'] is frame and pickle.dumps(state) == before
    assert result.target_token == state['placement_config']['target_row']
    assert result.active_sections[0].top_md == 0. and result.active_sections[-1].bottom_md == result.shoe_md
    state['hardware_table'].at[0, 'ID (in)'] += .001
    assert snapshot_geometry(state, app_source_sha=result.app_source_sha).source_identity != result.source_identity


@pytest.mark.parametrize('top', [0., 100.])
def test_cfw128_scalar_tieback_proof_and_point_a_zero_are_distinct(top):
    from cfw128_adapter import snapshot_geometry
    state = synthetic_tieback(top=top)
    # Measured scalar Lap is optional only where an explicit Shoe interval already establishes Top.
    state['hardware_table'] = pd.concat([state['hardware_table'], hardware(
        ('Tie Back Liner Lap', str(top), '7', 6.))], ignore_index=True)
    result = snapshot_geometry(state, app_source_sha='a'*40)
    assert result.string_top_md == top and result.shoe_md == 700.
    assert result.receiver.top_md == 700. and result.receiver.shoe_md == 1200.
    assert result.host_token == state['placement_config']['host_row']
    assert result.selected_host.top_md == 0. and result.selected_host.shoe_md == 800.
    assert result.status == ('GEOMETRY_REPRESENTABLE' if top else 'ENGINE_INTERFACE_NOT_REPRESENTABLE')
    assert ('POINT_A_ZERO' in result.reason_codes) == (top == 0)
    assert [s.description for s in result.active_sections] == (['Drill Pipes', 'Tie Back Liner Shoe'] if top else ['Tie Back Liner Shoe'])
    if top:
        assert result.reason_codes == ('SCALAR_TIEBACK_SOURCE_PROVED',)
        assert {(s.id_in, s.od_in) for s in result.active_sections} == {(6., 7.)}
    assert result.ready_to_run is False


def test_cfw128_tapered_previous_and_piecewise_wall_are_preserved_not_averaged():
    from cfw128_adapter import snapshot_geometry
    state = r18c_tapered_state(100.)
    before = pickle.dumps(state)
    result = snapshot_geometry(state, app_source_sha='b'*40)
    assert result.status == 'ENGINE_INTERFACE_NOT_REPRESENTABLE'
    assert 'SEGMENTED_ENCLOSURE' in result.reason_codes
    previous = [s for s in result.installed_strings if s.description == 'Previous Tie Back Liner Shoe']
    assert len(previous) == 1
    assert [(s.top_md, s.bottom_md, s.od_in, s.id_in) for s in previous[0].sections] == [
        (100., 150., 7., 6.094), (150., 300., 6.5, 5.8)]
    assert previous[0].source_rows == (4, 5)
    assert [(s.top_md, s.bottom_md, s.id_in) for s in result.enclosing_sections] == [
        (0., 100., 8.535), (100., 150., 6.094), (150., 300., 5.8), (300., 700., 6.094)]
    assert result.selected_host.source_rows == (1,)
    assert result.receiver.source_rows == (2,)
    assert result.receiver.sections[0].bottom_md == 1200.
    assert result.string_top_md == 400.
    assert pickle.dumps(state) == before


@pytest.mark.parametrize('fault,code', [
    ('draft', 'HARDWARE_DRAFT_PENDING'), ('missing_table', 'HARDWARE_MISSING'),
    ('missing_target', 'TARGET_NOT_SELECTED'), ('wrong_target', 'TARGET_NOT_SELECTED'),
    ('wrong_host', 'HOST_NOT_SELECTED'), ('previous_as_host', 'HOST_NOT_SELECTED'),
    ('duplicate_lap', 'APP_GEOMETRY_INVALID'), ('missing_lap', 'APP_GEOMETRY_INVALID'),
    ('conflicting_top', 'APP_GEOMETRY_INVALID'), ('bad_id', 'APP_GEOMETRY_INVALID'),
    ('gap', 'APP_GEOMETRY_INVALID'), ('duplicate_previous', 'APP_GEOMETRY_INVALID'),
    ('bad_survey', 'TRAJECTORY_INVALID'), ('partial_survey', 'TRAJECTORY_INVALID'),
    ('old_description', 'NONCANONICAL_HARDWARE'), ('missing_shoe', 'TARGET_NOT_SELECTED')])
def test_cfw128_invalid_or_incomplete_sources_are_honest_and_nonmutating(fault, code):
    from cfw128_adapter import snapshot_geometry
    state = r18c_tapered_state(100.)
    table = state['hardware_table']
    if fault == 'draft':
        state['hardware_editor_draft'] = table.copy(); state['hardware_editor_draft'].at[0,'MD (m)'] = '501'
    elif fault == 'missing_table': state.pop('hardware_table')
    elif fault in ('missing_target', 'wrong_target'): state['placement_config']['target_row'] = None if fault == 'missing_target' else 'retired'
    elif fault in ('wrong_host', 'previous_as_host'):
        state['placement_config']['host_row'] = 'retired' if fault == 'wrong_host' else next(iter(hardware_choices(table, {'Previous Tie Back Liner Shoe'})))
    elif fault == 'duplicate_lap': state['hardware_table'] = pd.concat([table, table.iloc[[6]]],ignore_index=True)
    elif fault == 'missing_lap': state['hardware_table'] = table[table['Description'] != 'Tie Back Liner Lap'].copy()
    elif fault == 'conflicting_top': state['placement_config']['tie_back_liner_lap_m'] = 399.
    elif fault == 'bad_id': table.at[4, 'ID (in)'] = 7.
    elif fault == 'gap': table.at[5, 'MD (m)'] = '151-300'
    elif fault == 'duplicate_previous': state['hardware_table'] = pd.concat([table,table.iloc[[3,4]]],ignore_index=True)
    elif fault in ('bad_survey', 'partial_survey'):
        state['well_geometry'] = {'type':'Directional', 'survey':pd.DataFrame([[0.,0.,0.],[1200.,181. if fault=='bad_survey' else None,0.]],columns=['MD','Deviation','Azimuth'])}
    elif fault == 'old_description': table.at[8,'Description'] = 'Tie Back'
    else: state['hardware_table'] = table[table['Description'] != 'Tie Back Liner Shoe'].copy()
    before = pickle.dumps(state)
    result = snapshot_geometry(state, app_source_sha='c'*40)
    assert result.status == 'INVALID_INPUT' and result.reason_codes == (code,)
    assert result.active_sections == () and result.enabled is False
    assert pickle.dumps(state) == before


def test_cfw128_directional_tvd_is_canonical_at_interior_and_knots_not_linear():
    from cfw128_adapter import snapshot_geometry
    from well_profile import tvd_at_md
    state = synthetic_tieback()
    state['well_geometry'] = {'type':'Directional','survey':pd.DataFrame(
        [[0.,0.,0.],[100.,60.,90.],[1200.,60.,90.]],columns=['MD','Deviation','Azimuth'])}
    result = snapshot_geometry(state, app_source_sha='d'*40, query_md=(50.,100.,700.))
    assert result.status == 'GEOMETRY_REPRESENTABLE'  # Geometry only; TVD convention remains an explicit hold.
    assert 'DIRECTIONAL_TVD_CONVENTION' in result.future_gates
    values = {s.md:s.tvd for s in result.trajectory}
    assert values[50.] == tvd_at_md(state['well_geometry'],[50.])[0] == pytest.approx(47.7464829275686)
    assert values[100.] == tvd_at_md(state['well_geometry'],[100.])[0]
    assert values[50.] != pytest.approx(values[100.]/2)
    assert [(s.md,s.deviation_deg,s.azimuth_deg) for s in result.survey] == [(0.,0.,0.),(100.,60.,90.),(1200.,60.,90.)]
    assert result.hydraulic_admissible is False
    assert snapshot_geometry(state, app_source_sha='d'*40, query_md=(1201.,)).reason_codes == ('TRAJECTORY_INVALID',)


def test_cfw128_deep_immutability_provenance_and_excess_do_not_rewrite_geometry():
    from cfw128_adapter import snapshot_geometry
    from dataclasses import FrozenInstanceError, fields, is_dataclass
    state = r18c_tapered_state(100.)
    before = pickle.dumps(state)
    result = snapshot_geometry(state, app_source_sha='e'*40)
    def immutable(value):
        if is_dataclass(value):
            for field in fields(value): immutable(getattr(value,field.name))
        elif isinstance(value,tuple):
            for item in value: immutable(item)
        else: assert value is None or type(value) in (str,float,int,bool)
    immutable(result)
    with pytest.raises(FrozenInstanceError): result.enabled = True
    with pytest.raises(FrozenInstanceError): result.enclosing_sections[0].id_in = 99.
    with pytest.raises(TypeError): result.enclosing_sections[0] = result.enclosing_sections[1]
    assert pickle.dumps(state) == before
    state['placement_config'].update(chart_excess_mode='apply',excess_csg_csg_pct=50.,excess_csg_oh_pct=60.)
    changed = snapshot_geometry(state, app_source_sha='e'*40)
    assert changed.active_sections == result.active_sections and changed.enclosing_sections == result.enclosing_sections
    assert changed.source_identity != result.source_identity
    assert snapshot_geometry(state, app_source_sha='f'*40).request_identity != changed.request_identity


@pytest.mark.parametrize('job', ['CMT PLUG','CMT SQUEEZE','CMT PLUG WITH CT'])
def test_cfw128_not_applicable_is_distinct_from_unknown_or_unfinished(job):
    from cfw128_adapter import snapshot_geometry
    result = snapshot_geometry({'job_type':job}, app_source_sha='a'*40)
    assert result.status == 'NOT_APPLICABLE' and result.reason_codes == ('NON_CHART_OPERATION',)
    assert result.ready_to_run is False
    assert snapshot_geometry({'job_type':'unknown'},app_source_sha='a'*40).status == 'INVALID_INPUT'
    assert snapshot_geometry({},app_source_sha='a'*40).reason_codes == ('JOB_NOT_SELECTED',)


def test_cfw128_adapter_remains_unimported_by_production_and_research_free():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in root.glob('*.py'):
        tree = ast.parse(path.read_text())
        modules = [n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        modules += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        if path.name == 'cfw128_adapter.py':
            assert set(modules) <= {'__future__','collections.abc','copy','dataclasses','math','re','typing','pandas','cement_chart_model','installed_geometry','placement','project_state','well_profile'}
        elif path.name != 'cfw128_er03_contract.py': assert 'cfw128_adapter' not in modules


@pytest.mark.parametrize('fault', ['target_type','host_type','description_type','well_record','query_bool','query_nan','query_outside'])
def test_cfw128_malformed_typed_sources_cannot_escape_or_hide_behind_deduplication(fault):
    from cfw128_adapter import snapshot_geometry
    state = synthetic_tieback()
    query = ()
    if fault == 'target_type': state['placement_config']['target_row'] = ['invalid']
    elif fault == 'host_type': state['placement_config']['host_row'] = ['invalid']
    elif fault == 'description_type': state['hardware_table'].at[0,'Description'] = ['invalid']
    elif fault == 'well_record': state['well_data'] = 4
    else: query = {'query_bool':(False,), 'query_nan':(float('nan'),), 'query_outside':(1201.,)}[fault]
    before = pickle.dumps(state)
    result = snapshot_geometry(state, app_source_sha='a'*40, query_md=query)
    assert result.status == 'INVALID_INPUT'
    assert result.active_sections == () and result.ready_to_run is False
    assert pickle.dumps(state) == before


@pytest.mark.parametrize('fault', ['host_coverage','two_active_walls','dp_taper','body_taper'])
def test_cfw128_app_valid_non_scalar_boundaries_are_not_malformed(fault):
    from cfw128_adapter import snapshot_geometry
    state = synthetic_tieback(top=400.)
    t = state['hardware_table']
    if fault == 'host_coverage':
        # Actual outer Casing covers the top; explicitly selected installed liner starts at100.
        state = bug01_geometry_case('TIE BACK LNR 5"')
    elif fault == 'two_active_walls':
        state = r18c_tapered_state(100.)
        state['hardware_table'].loc[state['hardware_table']['Description']=='Tie Back Liner Lap','MD (m)']='0'
        state['hardware_table'] = state['hardware_table'][state['hardware_table']['Description']!='Drill Pipes'].reset_index(drop=True)
        state['placement_config']['host_row']=next(iter(hardware_choices(state['hardware_table'],{'Previous Casing'})))
    elif fault == 'dp_taper':
        dp = t.index[t['Description']=='Drill Pipes'][0]
        t.at[dp,'MD (m)']='200'
        extra=t.iloc[[dp]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    else:
        t.at[0,'MD (m)']='400-500'
        extra=t.iloc[[0]].copy();extra['MD (m)']='500-700';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t.iloc[:1],extra,t.iloc[1:]],ignore_index=True)
        state['placement_config']['target_row']=next(k for k,v in hardware_choices(state['hardware_table'],target_descriptions(state['job_type'])).items() if v['depth']==700.)
    chart.resolve_chart_geometry(state)  # Independent App validity, not archive constructor acceptance.
    before = pickle.dumps(state)
    result=snapshot_geometry(state,app_source_sha='b'*40)
    assert result.status=='ENGINE_INTERFACE_NOT_REPRESENTABLE'
    assert {'host_coverage':'HOST_NOT_FULL_PATH','two_active_walls':'SEGMENTED_ENCLOSURE',
            'dp_taper':'SEGMENTED_DRILL_PIPE','body_taper':'SEGMENTED_TIEBACK_BODY'}[fault] in result.reason_codes
    assert result.enabled is False and pickle.dumps(state)==before


def test_cfw128_no_rheology_or_solver_calls_and_input_sha_contract(monkeypatch):
    from cfw128_adapter import snapshot_geometry, GeometrySnapshot
    def forbidden(*args,**kwargs): raise AssertionError('A disabled snapshot must not execute physics.')
    monkeypatch.setattr(pumping_simulation,'run_pumping_simulation',forbidden)
    monkeypatch.setattr(centralizer_adapter,'build_dynamic_payload',forbidden)
    state=synthetic_tieback()
    state['lab_qc_params']={'invalid':'not consumed'}
    result=snapshot_geometry(state,app_source_sha='c'*40)
    assert result.status=='GEOMETRY_REPRESENTABLE'
    with pytest.raises(ValueError,match='40-character'):
        snapshot_geometry(state,app_source_sha='unverified')
    with pytest.raises(TypeError):
        GeometrySnapshot('GEOMETRY_REPRESENTABLE',(),'', 'c'*40,'x','y','job', enabled=True)


@pytest.mark.parametrize('location,reason', [('hardware_table','HARDWARE_INCOMPLETE'),
    ('survey','TRAJECTORY_INVALID'), ('hardware_editor_draft','HARDWARE_DRAFT_INVALID')])
def test_cfw128_duplicate_columns_reject_without_warning_and_keep_dropped_values(location, reason):
    from cfw128_adapter import snapshot_geometry
    import warnings
    state = synthetic_tieback()
    if location == 'survey':
        frame = pd.DataFrame([[0.,0.,0.],[1200.,60.,90.]],columns=['MD','Deviation','Azimuth'])
        state['well_geometry'] = {'type':'Directional','survey':frame}
    else: frame = state['hardware_table']
    duplicate = pd.concat([frame.iloc[:,[0]],frame],axis=1)
    if location == 'survey': state['well_geometry']['survey'] = duplicate
    else: state[location] = duplicate
    before = pickle.dumps(state)
    with warnings.catch_warnings(record=True) as emitted:
        first = snapshot_geometry(state,app_source_sha='a'*40)
        repeated = snapshot_geometry(state,app_source_sha='a'*40)
    assert not emitted
    assert first == repeated
    assert first.status == 'INVALID_INPUT' and first.reason_codes == (reason,)
    assert first.active_sections == first.enclosing_sections == first.installed_strings == first.trajectory == ()
    assert all(getattr(first,k) is False for k in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible'))
    assert pickle.dumps(state) == before
    assert (state['well_geometry']['survey'] if location=='survey' else state[location]) is duplicate
    # Only the FIRST duplicate changes: the published records serializer discarded this column.
    duplicate.iat[0,0] = 17. if location=='survey' else 'otherwise-dropped-value'
    changed_before = pickle.dumps(state)
    with warnings.catch_warnings(record=True) as emitted:
        changed = snapshot_geometry(state,app_source_sha='a'*40)
    assert not emitted and changed.reason_codes == first.reason_codes
    assert changed.source_identity != first.source_identity
    assert changed.request_identity != first.request_identity
    assert pickle.dumps(state) == changed_before


@pytest.mark.parametrize('left,right', [(None,'None'), (1,1.), (True,1), (-0.,0.),
    (2**53,2**53+1), ('one','two'), (pd.NA,None), ([1,2],[1,3])])
def test_cfw128_duplicate_identity_preserves_positional_cell_types_and_values(left,right):
    from cfw128_adapter import snapshot_geometry
    state = synthetic_tieback()
    frame = pd.DataFrame([[left,'unchanged']],columns=['Description','Description'],dtype=object)
    state['hardware_table'] = frame
    first = snapshot_geometry(state,app_source_sha='b'*40)
    frame.iat[0,0] = right
    second = snapshot_geometry(state,app_source_sha='b'*40)
    assert first.reason_codes == second.reason_codes == ('HARDWARE_INCOMPLETE',)
    assert first.source_identity != second.source_identity
    assert first.request_identity != second.request_identity


def test_cfw128_duplicate_empty_columns_and_column_order_are_not_silently_repaired():
    from cfw128_adapter import snapshot_geometry
    state = synthetic_tieback()
    ids = []
    for columns in (['Description','Description','MD (m)'], ['Description','MD (m)','Description']):
        state['hardware_table'] = pd.DataFrame(columns=columns)
        before = pickle.dumps(state)
        result = snapshot_geometry(state,app_source_sha='c'*40)
        assert result.reason_codes == ('HARDWARE_INCOMPLETE',)
        assert pickle.dumps(state) == before
        ids.append(result.source_identity)
    assert ids[0] != ids[1]


@pytest.mark.parametrize('location', ['hardware_table','survey','hardware_editor_draft'])
def test_cfw128_duplicate_preflight_mutation_cannot_reintroduce_unsafe_fingerprint(location,monkeypatch):
    import cfw128_adapter as adapter
    state = synthetic_tieback()
    frame = state['hardware_table']
    if location == 'survey':
        frame = pd.DataFrame([[0.,0.,0.],[1200.,60.,90.]],columns=['MD','Deviation','Azimuth'])
        state['well_geometry'] = {'type':'Directional','survey':frame}
        state['well_geometry']['survey'] = pd.concat([frame.iloc[:,[0]],frame],axis=1)
    else: state[location] = pd.concat([frame.iloc[:,[0]],frame],axis=1)
    assert adapter.snapshot_geometry(state,app_source_sha='d'*40).status == 'INVALID_INPUT'
    # Actual mutation of the guard: without it the original Pandas warning must escape under -W error.
    monkeypatch.setattr(adapter,'_duplicate_column_reason',lambda source: None)
    with pytest.raises(UserWarning,match='columns are not unique'):
        adapter.snapshot_geometry(state,app_source_sha='d'*40)


def test_cfw128_unique_source_outputs_and_identities_equal_fixed_published_adapter(monkeypatch):
    from dataclasses import asdict
    from pathlib import Path
    import hashlib
    import subprocess
    import sys
    from types import ModuleType
    import cfw128_adapter as adapter
    root = Path(__file__).resolve().parents[1]
    original = subprocess.check_output(['git','show','bf98f73676e784de37e620fd6ae0217744883ae9:cfw128_adapter.py'],cwd=root)
    assert hashlib.sha256(original).hexdigest() == '3591c557ddc396a5f4b8f9411513d06fadb0762018c4f7cbb2aa4acab45b645c'
    reference = ModuleType('_cfw128_c1_fixed_published_reference')
    monkeypatch.setitem(sys.modules,reference.__name__,reference)
    exec(compile(original,'<fixed-published-bf98f736-adapter>','exec'),reference.__dict__)
    states = [bug01_geometry_case(job) for job in BUG01_JOBS]
    states += [synthetic_tieback(top=0.),r18c_tapered_state(100.),{}, {'job_type':'CMT PLUG'},
               {'job_type':'CMT SQUEEZE'},{'job_type':'CMT PLUG WITH CT'}]
    directional = synthetic_tieback()
    directional['well_geometry'] = {'type':'Directional','survey':pd.DataFrame(
        [[0.,0.,0.],[100.,60.,90.],[1200.,60.,90.]],columns=['MD','Deviation','Azimuth'])}
    states.append(directional)
    pending = synthetic_tieback();pending['hardware_editor_draft']=pending['hardware_table'].copy()
    pending['hardware_editor_draft'].at[0,'MD (m)']='101-700';states.append(pending)
    for state in states:
        before = pickle.dumps(state)
        kwargs = {'app_source_sha':'e'*40, 'query_md':(50.,100.)}
        expected = asdict(reference.snapshot_geometry(state,**kwargs))
        actual = asdict(adapter.snapshot_geometry(state,**kwargs))
        assert pickle.dumps(actual) == pickle.dumps(expected)
        assert pickle.dumps(state) == before


def test_cfw128_duplicate_identity_does_not_truncate_nested_array_cells():
    from cfw128_adapter import snapshot_geometry
    import numpy as np
    state = synthetic_tieback()
    frame = pd.DataFrame([[None,'unchanged']],columns=['Description','Description'],dtype=object)
    values = np.zeros(10000)
    frame.iat[0,0] = values
    state['hardware_table'] = frame
    before = pickle.dumps(state)
    first = snapshot_geometry(state,app_source_sha='f'*40)
    assert first.reason_codes == ('HARDWARE_INCOMPLETE',) and pickle.dumps(state) == before
    values[5000] = 1.  # This element is omitted by NumPy's abbreviated repr.
    second = snapshot_geometry(state,app_source_sha='f'*40)
    assert second.source_identity != first.source_identity
    assert second.request_identity != first.request_identity
    assert second == snapshot_geometry(state,app_source_sha='f'*40)


# B1 is a new disabled source-intake capability, not an App physics repair.
def test_cfw128_b1_intact_reviewed_source_is_captured_without_instrument_claim(bug01_reviewed_report_base):
    import project_state as ps
    from engineering_tools import lab_review_signature
    from rheology import RPM_ORDER
    state=deepcopy(bug01_reviewed_report_base)
    qc=state['lab_qc_params']['Main'];grid=state['lab_grid_dfs']['Main']
    assert qc['reviewed'] is True and qc['review_signature']==lab_review_signature(qc,grid)
    assert state['lab_source_signatures']['Main']==ps.lab_source_signature(state,'Main')
    from cfw128_hb_intake import snapshot_lab_intake
    before=pickle.dumps(state);grid_object=state['lab_grid_dfs']['Main']
    result=snapshot_lab_intake(state,'Main',app_source_sha='a'*40)
    assert result.status=='CAPTURED_FOR_FUTURE_REVIEW'
    assert result.reason_codes==('INTACT_REVIEWED_BHCT_DOWN_SOURCE','INSTRUMENT_PROVENANCE_UNVERIFIED')
    source=qc['rheology']['bhct_down']['readings']
    assert tuple(r.rpm for r in result.readings)==RPM_ORDER
    assert tuple((r.raw,r.raw_type,r.dial) for r in result.readings)==tuple((source[str(r)],type(source[str(r)]).__name__,int(source[str(r)])) for r in RPM_ORDER)
    assert result.review_signature==qc['review_signature']
    assert result.formulation_signature==state['lab_source_signatures']['Main']
    assert result.material_name==state['cement_params']['Main']['base_cement']
    assert result.instrument_provenance=='UNVERIFIED'
    assert all(getattr(result,k) is False for k in ('enabled','fit_admissible','ready_to_run','chart_admissible','hydraulic_admissible'))
    assert result==snapshot_lab_intake(state,'Main',app_source_sha='a'*40)
    assert pickle.dumps(state)==before and state['lab_grid_dfs']['Main'] is grid_object


@pytest.mark.parametrize('fault,reason',[
    ('unselected','BHCT_DOWN_NOT_SELECTED'),('wrong_ramp','BHCT_DOWN_NOT_SELECTED'),
    ('empty','DIAL_MISSING'),('missing_key','RPM_MISSING'),('extra_key','RPM_KEYS_INVALID'),
    ('colliding_key','RPM_KEYS_INVALID'),('duplicate_pairs','RPM_RECORD_INVALID'),
    ('bool','DIAL_BOOLEAN'),('fractional','DIAL_FRACTIONAL'),('tiny_fraction','DIAL_FRACTIONAL'),
    ('negative','DIAL_NEGATIVE'),('nonfinite','DIAL_NONFINITE'),('expression','DIAL_SYNTAX'),
    ('exponent','DIAL_SYNTAX'),('unreviewed','LAB_NOT_REVIEWED'),
    ('reading_edit','REVIEW_SIGNATURE_MISMATCH'),('grid_edit','REVIEW_SIGNATURE_MISMATCH'),
    ('formulation_edit','FORMULATION_SIGNATURE_MISMATCH'),('signature_edit','FORMULATION_SIGNATURE_MISMATCH'),
    ('duplicate_grid','DUPLICATE_SOURCE_COLUMNS'),('duplicate_additives','DUPLICATE_SOURCE_COLUMNS'),
    ('other_fluid','LAB_SOURCE_MISSING')])
def test_cfw128_b1_bad_or_stale_sources_never_carry_captured_readings(bug01_reviewed_report_base,fault,reason):
    from cfw128_hb_intake import snapshot_lab_intake
    state=deepcopy(bug01_reviewed_report_base);fluid='Main';qc=state['lab_qc_params']['Main'];row=qc['rheology']['bhct_down'];readings=row['readings']
    if fault in ('unselected','wrong_ramp'):
        row['selected']=False
        if fault=='wrong_ramp':qc['rheology']['surface_down']=deepcopy(row);qc['rheology']['surface_down']['selected']=True
    elif fault=='empty':readings['300']=''
    elif fault=='missing_key':readings.pop('3')
    elif fault=='extra_key':readings['600']='1'
    elif fault=='colliding_key':readings[300]='999'
    elif fault=='duplicate_pairs':row['readings']=[('300','168'),('300','169')]
    elif fault in ('bool','fractional','tiny_fraction','negative','nonfinite','expression','exponent'):
        readings['300']={'bool':True,'fractional':'168.5','tiny_fraction':'168.00000000000000000000001','negative':'-1','nonfinite':float('inf'),'expression':'100+68','exponent':'1.68e2'}[fault]
    elif fault=='unreviewed':qc['reviewed']=False
    elif fault=='reading_edit':readings['300']='169'
    elif fault=='grid_edit':state['lab_grid_dfs']['Main'].at[0,'Lot No']='different lot'
    elif fault=='formulation_edit':state['fluid_data']['Main']['density']='119.0'
    elif fault=='signature_edit':state['lab_source_signatures']['Main']='stale'
    elif fault in ('duplicate_grid','duplicate_additives'):
        key='lab_grid_dfs' if fault=='duplicate_grid' else 'cement_additives_dfs'
        frame=state[key]['Main']
        if not len(frame.columns):frame=pd.DataFrame([['x']],columns=['Name'])
        state[key]['Main']=pd.concat([frame.iloc[:,[0]],frame],axis=1)
    else:state['fluids_config']['active'].append('Lead');fluid='Lead'
    before=pickle.dumps(state)
    result=snapshot_lab_intake(state,fluid,app_source_sha='b'*40)
    assert result.status!='CAPTURED_FOR_FUTURE_REVIEW' and result.reason_codes==(reason,)
    assert result.readings==()
    assert all(getattr(result,k) is False for k in ('enabled','fit_admissible','ready_to_run','chart_admissible','hydraulic_admissible'))
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('fluid,reason', [('Displacement Fluid','MUD_SOURCE_MISSING'),('Mud','MUD_ALIAS_NOT_CANONICAL'),
    ('Diesel','UNSUPPORTED_RHEOLOGY_ONLY_FLUID'),('Pre Flush','UNSUPPORTED_RHEOLOGY_ONLY_FLUID'),
    ('Spacer','UNSUPPORTED_SPACER_SOURCE'),('Spacer Ahead','UNSUPPORTED_FLUID_STAGE'),('unknown','UNSUPPORTED_FLUID')])
def test_cfw128_b1_unsupported_fluids_do_not_become_measured_from_pv_yp(fluid,reason):
    from cfw128_hb_intake import snapshot_lab_intake
    state={'fluids_config':{'active':[fluid]},'plastic_viscosity':45.,'yield_point':15.,'mud_density':80.}
    result=snapshot_lab_intake(state,fluid,app_source_sha='c'*40)
    assert result.status==('INCOMPLETE_INPUT' if fluid=='Displacement Fluid' else 'NOT_AVAILABLE') and result.reason_codes==(reason,)
    assert result.readings==() and result.fit_admissible is False


@pytest.mark.parametrize('fluid', ['Main','Lead','Lead #1','Lead #2','Tail','Scavenger'])
def test_cfw128_b1_formulation_identity_is_active_and_job_eligible_not_inferred(fluid):
    from cfw128_hb_intake import snapshot_lab_intake
    result=snapshot_lab_intake({},fluid,app_source_sha='d'*40)
    assert result.status=='NOT_APPLICABLE' and result.reason_codes==('FLUID_NOT_ACTIVE',)
    if fluid!='Main':
        result=snapshot_lab_intake({'job_type':'CMT PLUG WITH CT','fluids_config':{'active':[fluid]}},fluid,app_source_sha='d'*40)
        assert result.reason_codes==('FLUID_NOT_ELIGIBLE',)


def test_cfw128_b1_restore_raw_types_and_currentness_are_read_only(bug01_reviewed_report_base):
    import test_audit_regressions as audit
    from cfw128_hb_intake import snapshot_lab_intake
    from project_state import fingerprint
    source=deepcopy(bug01_reviewed_report_base);state=audit.round_trip(source)
    before=pickle.dumps(state);first=snapshot_lab_intake(state,'Main',app_source_sha='e'*40)
    assert first.status=='CAPTURED_FOR_FUTURE_REVIEW'
    assert pickle.dumps(state)==before
    assert fingerprint(source['lab_qc_params'])==fingerprint(state['lab_qc_params'])
    assert source['lab_source_signatures']==state['lab_source_signatures']
    # Actual project serialization sorts keys; RPM association is semantic, not dict insertion order.
    assert tuple(r.rpm for r in first.readings)==(300,200,100,60,30,6,3)
    state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']='169'
    changed=snapshot_lab_intake(state,'Main',app_source_sha='e'*40)
    assert changed.reason_codes==('REVIEW_SIGNATURE_MISMATCH',)
    assert changed.source_identity!=first.source_identity and changed.request_identity!=first.request_identity
    state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']=source['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']
    assert snapshot_lab_intake(state,'Main',app_source_sha='e'*40)==first


def test_cfw128_b1_operator_review_transition_is_real_and_instrument_stays_unverified(bug01_reviewed_report_base):
    import test_audit_regressions as audit
    import project_state as ps
    from cfw128_hb_intake import snapshot_lab_intake
    case=audit.AuditRegressions();app=case.app(deepcopy(bug01_reviewed_report_base));case.phase(app,'phase7')
    box=next(w for w in app.text_input if w.label=='300 RPM - BHCT — Ramp-Down - Main')
    box.set_value('169').run()
    assert snapshot_lab_intake(app.session_state.to_dict(),'Main',app_source_sha='f'*40).status!='CAPTURED_FOR_FUTURE_REVIEW'
    confirm=next(w for w in app.button if w.label=='Confirm measured lab results');assert not confirm.disabled
    confirm.click().run()
    state=app.session_state.to_dict();before=pickle.dumps(state);result=snapshot_lab_intake(state,'Main',app_source_sha='f'*40)
    assert result.status=='CAPTURED_FOR_FUTURE_REVIEW' and result.readings[0].raw=='169'
    assert result.instrument_provenance=='UNVERIFIED' and result.fit_admissible is False
    assert pickle.dumps(state)==before
    assert state['lab_source_signatures']['Main']==ps.lab_source_signature(state,'Main')
    # An ad-hoc external claim is not a canonical instrument authority.
    state['instrument_evidence']={'family':'Fann35','rotor':'R1','bob':'B1','spring':1.0,'verified':True}
    assert snapshot_lab_intake(state,'Main',app_source_sha='f'*40).instrument_provenance=='UNVERIFIED'


def test_cfw128_b1_deep_immutability_and_no_fitting_or_physics_imports(bug01_reviewed_report_base,monkeypatch):
    import ast,sys,subprocess
    from pathlib import Path
    from dataclasses import fields,is_dataclass,FrozenInstanceError
    import rheology
    from cfw128_hb_intake import snapshot_lab_intake
    def forbidden(*args,**kwargs):raise AssertionError('B1 must not fit or execute physics')
    monkeypatch.setattr(rheology,'calculate_cemcade_bingham',forbidden)
    result=snapshot_lab_intake(deepcopy(bug01_reviewed_report_base),'Main',app_source_sha='a'*40)
    assert result.status=='CAPTURED_FOR_FUTURE_REVIEW'
    def frozen(value):
        if is_dataclass(value):
            for f in fields(value):frozen(getattr(value,f.name))
        elif isinstance(value,tuple):
            for x in value:frozen(x)
        else:assert value is None or type(value) in (str,int,float,bool)
    frozen(result)
    with pytest.raises(FrozenInstanceError):result.fit_admissible=True
    with pytest.raises(FrozenInstanceError):result.readings[0].dial=9
    root=Path(__file__).resolve().parents[1]
    for file in root.glob('*.py'):
        tree=ast.parse(file.read_text());imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]+[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        if file.name not in ('cfw128_hb_intake.py','cfw128_hb_numeric.py'):assert 'cfw128_hb_intake' not in imports
    code='import sys, cfw128_hb_intake; assert not any(n in sys.modules for n in ("scipy", "pumping_simulation", "fluids_charts_module_v1_4_2"))'
    subprocess.run([sys.executable,'-B','-W','error','-c',code],cwd=root,check=True)


@pytest.mark.parametrize('raw', [168,168.0,' 00168.00 '])
def test_cfw128_b1_real_confirmation_retains_numeric_or_text_source_types(bug01_reviewed_report_base,raw):
    import test_audit_regressions as audit
    from cfw128_hb_intake import snapshot_lab_intake
    state=deepcopy(bug01_reviewed_report_base)
    state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']=raw
    state['lab_qc_params']['Main']['reviewed']=False
    case=audit.AuditRegressions();app=case.app(state);case.phase(app,'phase7')
    confirm=next(w for w in app.button if w.label=='Confirm measured lab results');assert not confirm.disabled
    confirm.click().run()
    source=app.session_state.to_dict();before=pickle.dumps(source)
    result=snapshot_lab_intake(source,'Main',app_source_sha='b'*40)
    assert result.status=='CAPTURED_FOR_FUTURE_REVIEW'
    reading=result.readings[0]
    assert reading.raw==raw and type(reading.raw) is type(raw) and reading.raw_type==type(raw).__name__
    assert reading.dial==168 and pickle.dumps(source)==before


def test_cfw128_b1_duplicate_grid_identity_and_guard_mutation_preserve_every_cell(bug01_reviewed_report_base,monkeypatch):
    import cfw128_hb_intake as intake
    state=deepcopy(bug01_reviewed_report_base);frame=state['lab_grid_dfs']['Main']
    duplicate=pd.concat([frame.iloc[:,[0]],frame],axis=1);state['lab_grid_dfs']['Main']=duplicate
    before=pickle.dumps(state);first=intake.snapshot_lab_intake(state,'Main',app_source_sha='c'*40)
    assert first.reason_codes==('DUPLICATE_SOURCE_COLUMNS',) and pickle.dumps(state)==before
    assert first==intake.snapshot_lab_intake(state,'Main',app_source_sha='c'*40)
    duplicate.iat[0,0]='otherwise-lost-material'
    second=intake.snapshot_lab_intake(state,'Main',app_source_sha='c'*40)
    assert first.source_identity!=second.source_identity and first.request_identity!=second.request_identity
    monkeypatch.setattr(intake,'_duplicate_columns',lambda value:False)
    with pytest.raises(UserWarning,match='columns are not unique'):
        intake.snapshot_lab_intake(state,'Main',app_source_sha='c'*40)


def test_cfw128_b1_positional_encoding_matches_locked_ac1_without_runtime_import():
    import ast,inspect
    import cfw128_adapter as geometry
    import cfw128_hb_intake as intake
    def body(function):
        node=ast.parse(inspect.getsource(function)).body[0]
        return ast.dump(ast.Module(body=node.body[1:],type_ignores=[]),include_attributes=False)
    assert body(geometry._positional_source)==body(intake._positional_source)
    for value in [pd.DataFrame([[1,2],[3,4]],columns=['x','x']), {'300':168,'200':116.0}, [None,pd.NA,True,2**60,-0.0]]:
        assert geometry._positional_source(value)==intake._positional_source(value)


@pytest.mark.parametrize('raw,expected', [(0,0),(168,168),(168.0,168),(' 00168.00 ',168),('0',0),('-0.00',0)])
def test_cfw128_b1_documented_integer_syntax_is_exact_without_fit(raw,expected):
    from cfw128_hb_intake import _dial
    assert _dial(raw)==(expected,None)


@pytest.mark.parametrize('fault,reason',[('empty_qc','RHEOLOGY_SOURCE_MISSING'),('unknown_ramp','RHEOLOGY_KEYS_INVALID'),
    ('dataset_extra','DATASET_KEYS_INVALID'),('selection_type','SELECTION_INVALID'),('review_signature','REVIEW_SIGNATURE_MISMATCH'),
    ('nonfinite_text','DIAL_NONFINITE'),('bad_type','DIAL_TYPE')])
def test_cfw128_b1_additional_source_shape_and_review_mutations_are_honest(bug01_reviewed_report_base,fault,reason):
    from cfw128_hb_intake import snapshot_lab_intake
    state=deepcopy(bug01_reviewed_report_base);qc=state['lab_qc_params']['Main'];row=qc['rheology']['bhct_down']
    if fault=='empty_qc':qc.clear()
    elif fault=='unknown_ramp':qc['rheology']['invented_down']={}
    elif fault=='dataset_extra':row['instrument']='Fann35'
    elif fault=='selection_type':row['selected']=1
    elif fault=='review_signature':qc['review_signature']='different-review'
    elif fault=='nonfinite_text':row['readings']['300']='NaN'
    else:row['readings']['300']={'dial':168}
    before=pickle.dumps(state);result=snapshot_lab_intake(state,'Main',app_source_sha='e'*40)
    assert result.reason_codes==(reason,) and result.readings==()
    assert result.fit_admissible is False and pickle.dumps(state)==before


def test_cfw128_b1_snapshot_pickle_and_clone_cannot_enable_fitting(bug01_reviewed_report_base):
    from dataclasses import asdict,replace
    from cfw128_hb_intake import snapshot_lab_intake
    result=snapshot_lab_intake(deepcopy(bug01_reviewed_report_base),'Main',app_source_sha='f'*40)
    assert pickle.loads(pickle.dumps(result))==result
    for name in ('enabled','fit_admissible','ready_to_run','chart_admissible','hydraulic_admissible','scientifically_qualified'):
        assert asdict(result)[name] is False
        with pytest.raises(ValueError):replace(result,**{name:True})


def test_cfw128_b1m_real_mud_editor_confirm_restore_and_consumers(bug01_reviewed_report_base,tmp_path):
    import test_audit_regressions as audit
    import project_state as ps
    import materials_db as db
    from cfw128_hb_intake import snapshot_lab_intake
    from engineering_tools import build_lab_rheology,compute_phase_status
    import phase_9_centralizer as p9
    case=audit.AuditRegressions();source=deepcopy(bug01_reviewed_report_base)
    old_status=compute_phase_status(source);old_pump=pumping_simulation.source_signature(source);old_cent=p9.source_signature(source)
    app=case.app(source);case.phase(app,'phase7')
    labels=[t.label for t in app.tabs];assert labels.count('Displacement Fluid (Mud)')==1
    mud=next(t for t in app.tabs if t.label=='Displacement Fluid (Mud)')
    assert [w.label for w in mud.checkbox]==['BHCT — Ramp-Down - Displacement Fluid']
    mud.checkbox[0].check().run()
    dials=('168','116','64','41','24','8','6')
    for rpm,value in zip((300,200,100,60,30,6,3),dials):
        next(w for w in app.text_input if w.label==f'{rpm} RPM - BHCT — Ramp-Down - Displacement Fluid').set_value(value).run()
    mud=next(t for t in app.tabs if t.label=='Displacement Fluid (Mud)')
    assert [w.label for w in mud.text_input]==[f'{rpm} RPM - BHCT — Ramp-Down - Displacement Fluid' for rpm in (300,200,100,60,30,6,3)]
    assert [(m.label,m.value) for m in mud.metric]==[('PV (cP)','159.218'),('Ty (lbf/100ft²)','9.47')]
    qc=app.session_state['lab_qc_params']['Displacement Fluid'];fit,issues=build_lab_rheology(qc,'Displacement Fluid');assert not issues
    assert f"{fit['bhct_down']['pv_cp']:.3f}"=='159.218' and f"{fit['bhct_down']['ty_lbf_100ft2']:.2f}"=='9.47'
    assert snapshot_lab_intake(app.session_state.to_dict(),'Displacement Fluid',app_source_sha='a'*40).reason_codes==('LAB_NOT_REVIEWED',)
    next(w for w in app.button if w.label=='Confirm measured Mud lab results').click().run()
    state=app.session_state.to_dict();before=pickle.dumps(state);result=snapshot_lab_intake(state,'Displacement Fluid',app_source_sha='a'*40)
    assert result.status=='CAPTURED_FOR_FUTURE_REVIEW' and tuple(r.raw for r in result.readings)==dials
    assert result.instrument_provenance=='UNVERIFIED'
    assert all(getattr(result,k) is False for k in ('enabled','fit_admissible','ready_to_run','chart_admissible','hydraulic_admissible','scientifically_qualified'))
    assert pickle.dumps(state)==before
    assert 'Displacement Fluid' not in state.get('lab_grid_dfs',{}) and 'Displacement Fluid' not in state.get('cement_params',{})
    assert db.RHEOLOGY_ONLY_FLUIDS==('Diesel','Pre Flush') and db.RHEOLOGY_LAB_FLUIDS==db.CEMENT_FORMULATION_FLUIDS
    assert db.PHASE7_LAB_FLUIDS==(*db.CEMENT_FORMULATION_FLUIDS,*db.RHEOLOGY_ONLY_FLUIDS)
    assert db.PHASE7_VISIBLE_LAB_FLUIDS==(*db.PHASE7_LAB_FLUIDS,'Displacement Fluid')
    assert ps.phase7_lab_fluids(state)==ps.phase7_lab_fluids(source)
    assert compute_phase_status(state)==old_status
    assert pumping_simulation.source_signature(state)==old_pump and p9.source_signature(state)==old_cent
    case.phase(app,'phase4');case.phase(app,'phase7')
    assert snapshot_lab_intake(app.session_state.to_dict(),'Displacement Fluid',app_source_sha='a'*40)==result
    restored=audit.round_trip(app.session_state.to_dict())
    assert snapshot_lab_intake(restored,'Displacement Fluid',app_source_sha='a'*40)==result
    second=case.app(restored);case.phase(second,'phase7')
    assert snapshot_lab_intake(second.session_state.to_dict(),'Displacement Fluid',app_source_sha='a'*40)==result
    # Two real Build-button exports: measured Mud is deliberately outside cement Word.
    from test_uat_round10c_integration import build
    from zipfile import ZipFile
    from io import BytesIO
    # Compare identical restored trust boundaries; restore intentionally retires Centralizer.
    without_mud=deepcopy(restored)
    without_mud['lab_qc_params'].pop('Displacement Fluid')
    without_mud['lab_source_signatures'].pop('Displacement Fluid')
    original_doc=build(case.app(without_mud))
    measured_doc=build(second)
    (tmp_path/'before-mud.docx').write_bytes(original_doc)
    (tmp_path/'reviewed-mud.docx').write_bytes(measured_doc)
    with ZipFile(BytesIO(original_doc)) as old,ZipFile(BytesIO(measured_doc)) as new:
        assert old.namelist()==new.namelist()
        for part in old.namelist():
            if part!='docProps/core.xml':  # ZIP/core creation time is not report content.
                assert old.read(part)==new.read(part),part
    isolated=case.app(deepcopy(bug01_reviewed_report_base));case.phase(isolated,'phase7')
    assert not isolated.session_state['lab_qc_params']['Displacement Fluid']['rheology']['bhct_down']['selected']
    # A dial edit commits before navigation, retires review and compiled Word, but not hydraulic sources.
    app.session_state['_compiled_doc_bytes']=b'old test document'
    next(w for w in app.text_input if w.label=='300 RPM - BHCT — Ramp-Down - Displacement Fluid').set_value('169').run()
    case.phase(app,'phase4');case.phase(app,'phase7')
    changed=app.session_state.to_dict();assert changed['lab_qc_params']['Displacement Fluid']['rheology']['bhct_down']['readings']['300']=='169'
    assert not changed.get('_compiled_doc_bytes')
    assert snapshot_lab_intake(changed,'Displacement Fluid',app_source_sha='a'*40).status!='CAPTURED_FOR_FUTURE_REVIEW'
    assert snapshot_lab_intake(restored,'Displacement Fluid',app_source_sha='a'*40)==result
    next(w for w in app.text_input if w.label=='300 RPM - BHCT — Ramp-Down - Displacement Fluid').set_value('168.5').run()
    mud=next(t for t in app.tabs if t.label=='Displacement Fluid (Mud)')
    assert not mud.metric and not any(b.label=='Confirm measured Mud lab results' for b in mud.button)
    case.phase(app,'phase4');case.phase(app,'phase7')
    assert app.session_state['lab_qc_params']['Displacement Fluid']['rheology']['bhct_down']['readings']['300']=='168.5'


@pytest.mark.parametrize('fault', ['missing','partial','wrong_ramp','bad_key','bool','fraction','nonfinite','unreviewed','edited',
    'bhct','density','material','inactive','instrument'])
def test_cfw128_b1m_mud_negative_source_contract(bug01_reviewed_report_base,fault):
    import test_audit_regressions as audit
    import project_state as ps
    from cfw128_hb_intake import snapshot_lab_intake
    # Cache only a genuinely UI-confirmed synthetic source, never manufacture its signature.
    case=audit.AuditRegressions();app=case.app(deepcopy(bug01_reviewed_report_base));case.phase(app,'phase7')
    next(w for w in app.checkbox if w.label=='BHCT — Ramp-Down - Displacement Fluid').check().run()
    for rpm,value in zip((300,200,100,60,30,6,3),('168','116','64','41','24','8','6')):
        next(w for w in app.text_input if w.label==f'{rpm} RPM - BHCT — Ramp-Down - Displacement Fluid').set_value(value).run()
    next(w for w in app.button if w.label=='Confirm measured Mud lab results').click().run()
    state=app.session_state.to_dict();qc=state['lab_qc_params']['Displacement Fluid'];row=qc['rheology']['bhct_down']
    original=snapshot_lab_intake(state,'Displacement Fluid',app_source_sha='b'*40);assert original.status=='CAPTURED_FOR_FUTURE_REVIEW'
    if fault=='missing':state['lab_qc_params'].pop('Displacement Fluid')
    elif fault=='partial':row['readings'].pop('3')
    elif fault=='wrong_ramp':qc['rheology']['surface_down']=qc['rheology'].pop('bhct_down')
    elif fault=='bad_key':row['readings'][300]='168'
    elif fault=='bool':row['readings']['300']=True
    elif fault=='fraction':row['readings']['300']='168.0000000000001'
    elif fault=='nonfinite':row['readings']['300']=float('nan')
    elif fault=='unreviewed':qc['reviewed']=False
    elif fault=='edited':row['readings']['300']='169'
    elif fault=='bhct':state['well_data']['bhct']=151.
    elif fault=='density':state['mud_density']='81'
    elif fault=='material':state['fluids_config']['params']['Displacement Fluid']['material_name']='different actual mud'
    elif fault=='inactive':
        state['fluids_config']['active'].remove('Displacement Fluid');ps.purge_inactive_slurries(state,state['fluids_config']['active'])
    else:qc['instrument_verified']=True
    before=pickle.dumps(state);held=snapshot_lab_intake(state,'Displacement Fluid',app_source_sha='b'*40)
    assert held.status!='CAPTURED_FOR_FUTURE_REVIEW' and held.readings==()
    assert held.instrument_provenance=='UNVERIFIED' and held.fit_admissible is False
    assert held.source_identity!=original.source_identity and pickle.dumps(state)==before
    assert snapshot_lab_intake(state,'Mud',app_source_sha='b'*40).reason_codes==('MUD_ALIAS_NOT_CANONICAL',)
    if fault=='inactive':
        state['fluids_config']['active'].append('Displacement Fluid')
        assert snapshot_lab_intake(state,'Displacement Fluid',app_source_sha='b'*40).reason_codes==('LAB_NOT_REVIEWED',)


def test_cfw128_b1m_visible_list_mutation_and_unrelated_context_do_not_bypass_contract(bug01_reviewed_report_base,monkeypatch):
    import materials_db as db
    import project_state as ps
    state=deepcopy(bug01_reviewed_report_base)
    before=ps.mud_lab_source_signature(state)
    state['well_name']='unrelated display';state['fluids_config']['params']['Displacement Fluid']['volume']=123.
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']='5'
    assert ps.mud_lab_source_signature(state)==before
    expected=(*db.PHASE7_LAB_FLUIDS,'Displacement Fluid')
    assert db.PHASE7_VISIBLE_LAB_FLUIDS==expected
    monkeypatch.setattr(db,'PHASE7_VISIBLE_LAB_FLUIDS',db.PHASE7_LAB_FLUIDS)
    with pytest.raises(AssertionError):assert 'Displacement Fluid' in ps.phase7_lab_fluids(state,include_mud=True)


def test_cfw128_b1m_original_cement_snapshot_remains_byte_equivalent(bug01_reviewed_report_base,monkeypatch):
    import hashlib,subprocess,sys
    from types import ModuleType
    from pathlib import Path
    from dataclasses import asdict
    import cfw128_hb_intake as current
    root=Path(__file__).resolve().parents[1]
    source=subprocess.check_output(['git','show','7b0e42a1561485853ab07d8e66470e5cb782235e:cfw128_hb_intake.py'],cwd=root)
    assert hashlib.sha256(source).hexdigest()=='b52e466b985936a6fe17ded990537f29253277057125afaf7a304fed01f65d81'
    old=ModuleType('_b1m_original_cement_reference');monkeypatch.setitem(sys.modules,old.__name__,old)
    exec(compile(source,'<fixed-B1-reference>','exec'),old.__dict__)
    state=deepcopy(bug01_reviewed_report_base)
    for fluid in ('Main','Lead','Scavenger','Diesel','Pre Flush','Spacer'):
        assert pickle.dumps(asdict(current.snapshot_lab_intake(state,fluid,app_source_sha='c'*40)))==pickle.dumps(asdict(old.snapshot_lab_intake(state,fluid,app_source_sha='c'*40)))


# B2a historical SOFTWARE benchmarks; not live sample instrument evidence.
B2A_SOFTWARE_BENCHMARKS = [('HB-T01', (45, 37, 27, 22, 16, 9, 8), (2.089010265509999, 0.7853358920369178, 0.5261585706020849)), ('HB-T02', (45, 40, 32, 27, 22, 15, 13), (3.3526935511535374, 1.7204227058387223, 0.3917889412622261)), ('HB-T03', (67, 50, 31, 22, 14, 5, 3), (0.3669405174698402, 0.412302373383494, 0.7064610493520076)), ('HB-T04', (75, 51, 28, 19, 12, 6, 5), (2.3449862860684094, 0.07205055082398323, 0.9958707344605118)), ('HB-T05', (73, 65, 54, 48, 41, 31, 28), (9.865668980488294, 2.3748041403583895, 0.392237770834758)), ('HB-T06', (97, 67, 36, 23, 13, 3, 2), (0.2674618920188657, 0.17374262431457674, 0.905510321730862)), ('HB-T07', (54, 44, 31, 25, 20, 14, 13), (5.744581796668518, 0.28178872442667724, 0.6984323731258377))]

@pytest.mark.parametrize('case,dials,expected', B2A_SOFTWARE_BENCHMARKS)
def test_cfw128_b2a_frozen_benchmark_replay_and_exact_unit_boundary(case,dials,expected,tmp_path):
    import json,hashlib
    import cfw128_hb03t_frozen as hb
    # Fixed numerical replay tolerance: 1 ppm relative / 1e-9 SI absolute.
    # This is binary-environment replay, not a CemCADE or physical acceptance tolerance.
    instrument=hb.InstrumentConfig('Fann 35','R1B1','1.0')  # Historical TEST ONLY assumption.
    assert all(type(v) is int for v in dials)
    result=hb.fit_full_hb(dials,hb.RPM_ORDER,instrument=instrument,ramp_type='bhct_down',reviewed=True)
    assert result.status=='OK' and result.fail_reason_code is None and result.n_starts==60
    actual=(result.tau_y_pa,result.k_pa_s_n,result.n_dimensionless)
    assert actual==pytest.approx(expected,rel=1e-6,abs=1e-9)
    again=hb.fit_full_hb(tuple(reversed(dials)),tuple(reversed(hb.RPM_ORDER)),instrument=instrument,ramp_type='bhct_down',reviewed=True)
    assert (again.tau_y_pa,again.k_pa_s_n,again.n_dimensionless)==actual
    assert again.determinism_receipt==result.determinism_receipt and len(result.determinism_receipt)==64
    assert result.input_readings_rpm_to_dial=={str(r):v for r,v in zip(hb.RPM_ORDER,dials)}
    engine=hb.to_engine_field(*actual)
    assert hb.PA_PER_FIELD_TY==0.47880259
    assert engine.tau_y_field_lbf_100ft2==actual[0]/0.47880259
    assert engine.k_pa_s_n==actual[1] and engine.n_dimensionless==actual[2] and engine.mu_p_cp==0.0
    with pytest.raises(TypeError):hb.to_engine_field(engine,actual[1],actual[2])
    assert result.scientifically_qualified_for_hydraulic_charts is result.chart_lane_admissible is False
    for gate in ('scientifically_qualified_for_hydraulic_charts','chart_lane_admissible'):
        with pytest.raises(AttributeError):setattr(result,gate,True)
        assert result.to_dict()[gate] is False
    assert hashlib.sha256(__import__('pathlib').Path(hb.__file__).read_bytes()).hexdigest()=='e62678f87867a1b34261a31114e6c692384f0f753c7cbcc92510dd8a5171194f'
    (tmp_path/(case+'.json')).write_text(json.dumps(result.to_dict(),indent=2,allow_nan=False))


@pytest.mark.parametrize('fault,reason',[('missing','INCOMPLETE_DIAL_SET'),('rpm_duplicate','INCOMPLETE_DIAL_SET'),
    ('fraction','NONINTEGER_DIAL_ENTRY'),('negative','INVALID_READING_VALUE'),('nan','NONFINITE_READING'),
    ('nonmonotone','NONMONOTONE_READINGS'),('flat','NEAR_NONIDENTIFIABLE'),('instrument','INSTRUMENT_OR_RAMP_MISMATCH'),
    ('ramp','INSTRUMENT_OR_RAMP_MISMATCH')])
def test_cfw128_b2a_frozen_negative_intake_is_fail_closed(fault,reason):
    import cfw128_hb03t_frozen as hb
    dials=list(B2A_SOFTWARE_BENCHMARKS[0][1]);rpms=list(hb.RPM_ORDER)
    inst=hb.InstrumentConfig('Fann 35','R1B1','1.0');ramp='bhct_down'
    if fault=='missing':dials.pop()
    elif fault=='rpm_duplicate':rpms[-1]=6
    elif fault=='fraction':dials[0]=45.5
    elif fault=='negative':dials[-1]=-1
    elif fault=='nan':dials[0]=float('nan')
    elif fault=='nonmonotone':dials[-1]=46
    elif fault=='flat':dials=[1]*7
    elif fault=='instrument':inst=hb.InstrumentConfig('unknown','R1B1','1.0')
    else:ramp='not_a_measured_ramp'
    before=pickle.dumps((dials,rpms,inst))
    result=hb.fit_full_hb(dials,rpms,instrument=inst,ramp_type=ramp,reviewed=False)
    assert result.status=='FAIL_CLOSED' and result.fail_reason_code==reason
    assert result.tau_y_pa is result.k_pa_s_n is result.n_dimensionless is None
    assert result.scientifically_qualified_for_hydraulic_charts is result.chart_lane_admissible is False
    assert pickle.dumps((dials,rpms,inst))==before


@pytest.mark.parametrize('raw',[True,'45',None,{'pv_cp':45}])
def test_cfw128_b2a_frozen_programmer_types_never_become_dials(raw):
    import cfw128_hb03t_frozen as hb
    dials=list(B2A_SOFTWARE_BENCHMARKS[0][1]);dials[0]=raw
    with pytest.raises(TypeError):
        hb.fit_full_hb(dials,hb.RPM_ORDER,instrument=hb.InstrumentConfig('Fann 35','R1B1','1.0'),ramp_type='bhct_down')


@pytest.mark.parametrize('consumer',['ct','chart'])
@pytest.mark.parametrize('fault',['missing','changed_scipy','duplicate','inserted','numpy','existing','extra'])
def test_cfw128_b2a_requirements_historical_consumers_reject_mutations(consumer,fault,monkeypatch):
    from pathlib import Path
    from test_round13b_b4_ct_report import test_unrelated_guardrails_and_all_frozen_authorities_are_unchanged as ct
    from test_uat_round8b_report import test_template_dependency_and_protected_sources_identical as chart
    fn={'ct':ct,'chart':chart}[consumer];fn()
    path=Path('requirements.txt').resolve();source=path.read_bytes();line=b'scipy==1.14.1\n'
    if fault=='missing':changed=source[:-len(line)]
    elif fault=='changed_scipy':changed=source.replace(line,b'scipy==1.14.2\n')
    elif fault=='duplicate':changed=source+line
    elif fault=='inserted':changed=line+source[:-len(line)]
    elif fault=='numpy':changed=source.replace(b'numpy==2.1.3',b'numpy==2.2.0')
    elif fault=='existing':changed=source.replace(b'pandas==2.2.3',b'pandas==2.2.4')
    else:changed=source[:-len(line)]+b'new_dependency==1.0\n'+line
    assert changed!=source
    original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda f:changed if f.resolve()==path else original(f))
    with pytest.raises(AssertionError):fn()


@pytest.mark.parametrize('fault',['current','unreviewed','stale','incomplete'])
def test_cfw128_b2a_unverified_cement_snapshot_cannot_fit_or_enable(bug01_reviewed_report_base,fault,monkeypatch):
    from dataclasses import replace,asdict
    from cfw128_hb_intake import snapshot_lab_intake
    import cfw128_hb03t_frozen as hb
    def forbidden(*a,**k):raise AssertionError('Live source must never reach the frozen fitter.')
    monkeypatch.setattr(hb,'fit_full_hb',forbidden)
    state=deepcopy(bug01_reviewed_report_base)
    if fault=='unreviewed':state['lab_qc_params']['Main']['reviewed']=False
    elif fault=='stale':state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']='169'
    elif fault=='incomplete':state['lab_qc_params']['Main']['rheology']['bhct_down']['readings'].pop('3')
    before=pickle.dumps(state);snapshot=snapshot_lab_intake(state,'Main',app_source_sha='a'*40);intent=snapshot
    assert intent.instrument_provenance=='UNVERIFIED'
    assert (intent.status=='CAPTURED_FOR_FUTURE_REVIEW') is (fault=='current')
    assert intent==snapshot_lab_intake(state,'Main',app_source_sha='a'*40) and pickle.dumps(state)==before
    if fault!='current':assert intent.readings==()
    assert not any(k in asdict(intent) for k in ('tau_y_pa','k_pa_s_n','n_dimensionless','pressure'))
    for name in ('enabled','fit_admissible','hydraulic_admissible','chart_admissible','ready_to_run','scientifically_qualified'):
        assert getattr(intent,name) is False
        with pytest.raises((TypeError,AttributeError)):setattr(intent,name,True)
        with pytest.raises((TypeError,ValueError)):replace(intent,**{name:True})
        assert getattr(pickle.loads(pickle.dumps(intent)),name) is False
    with pytest.raises(ValueError):snapshot_lab_intake({'plastic_viscosity':45},'Main',app_source_sha='not-verified')


def test_cfw128_b2a_real_reviewed_mud_remains_a_hold(bug01_reviewed_report_base):
    import test_audit_regressions as audit
    from cfw128_hb_intake import snapshot_lab_intake
    case=audit.AuditRegressions();app=case.app(deepcopy(bug01_reviewed_report_base));case.phase(app,'phase7')
    next(w for w in app.checkbox if w.label=='BHCT — Ramp-Down - Displacement Fluid').check().run()
    for rpm,value in zip((300,200,100,60,30,6,3),('168','116','64','41','24','8','6')):
        next(w for w in app.text_input if w.label==f'{rpm} RPM - BHCT — Ramp-Down - Displacement Fluid').set_value(value).run()
    next(w for w in app.button if w.label=='Confirm measured Mud lab results').click().run()
    snapshot=snapshot_lab_intake(app.session_state.to_dict(),'Displacement Fluid',app_source_sha='a'*40)
    assert snapshot.status=='CAPTURED_FOR_FUTURE_REVIEW'
    assert tuple(r.raw for r in snapshot.readings)==('168','116','64','41','24','8','6')
    assert all(type(r.dial) is int for r in snapshot.readings)
    assert snapshot.instrument_provenance=='UNVERIFIED' and snapshot.fit_admissible is False
    current=app.session_state.to_dict()
    for fault in ('unreviewed','stale','incomplete'):
        state=deepcopy(current);qc=state['lab_qc_params']['Displacement Fluid']
        if fault=='unreviewed':qc['reviewed']=False
        elif fault=='stale':qc['rheology']['bhct_down']['readings']['300']='169'
        else:qc['rheology']['bhct_down']['readings'].pop('3')
        held=snapshot_lab_intake(state,'Displacement Fluid',app_source_sha='a'*40)
        assert held.status!='CAPTURED_FOR_FUTURE_REVIEW' and held.readings==()
        assert held.instrument_provenance=='UNVERIFIED' and held.fit_admissible is False


def test_cfw128_b2a_runtime_pins_and_production_import_isolation():
    import ast,hashlib,sys,subprocess
    from pathlib import Path
    import numpy,scipy
    assert sys.version_info[:3]==(3,12,16)
    assert numpy.__version__=='2.1.3' and scipy.__version__=='1.14.1'
    raw=Path('requirements.txt').read_bytes();assert raw.endswith(b'scipy==1.14.1\n') and raw.count(b'scipy==1.14.1\n')==1
    original=subprocess.check_output(['git','show','4c92e4c9b4eab32d2525a356c4e74272fb9171aa:requirements.txt'])
    assert raw==original+b'scipy==1.14.1\n'
    for f in Path('.').glob('*.py'):
        imports={n.module for n in ast.walk(ast.parse(f.read_text())) if isinstance(n,ast.ImportFrom)}
        imports|={a.name for n in ast.walk(ast.parse(f.read_text())) if isinstance(n,ast.Import) for a in n.names}
        if f.name not in ('cfw128_hb03t_frozen.py','cfw128_hb_numeric.py'):
            assert not {'cfw128_hb03t_frozen','cfw128_hb_numeric'} & imports
    script='''import sys
from streamlit.testing.v1 import AppTest
import phase_7_lab,cfw128_hb_intake
try:
 app=AppTest.from_file("main.py",default_timeout=30).run()
 assert not app.exception
 assert "scipy" not in sys.modules and "cfw128_hb03t_frozen" not in sys.modules
finally:
 import streamlit.testing.v1.app_test as t
 t.TMP_DIR.cleanup()
'''
    subprocess.run([sys.executable,'-B','-W','error','-c',script],check=True,capture_output=True,text=True)


def test_cfw128_b2a_immutable_intake_and_frozen_public_gates_reject_forgery(bug01_reviewed_report_base):
    import copy
    from dataclasses import replace
    from cfw128_hb_intake import snapshot_lab_intake
    import cfw128_hb03t_frozen as hb
    snapshot=snapshot_lab_intake(deepcopy(bug01_reviewed_report_base),'Main',app_source_sha='b'*40)
    assert isinstance(snapshot.readings,tuple) and isinstance(snapshot.reason_codes,tuple)
    assert copy.deepcopy(snapshot)==snapshot
    with pytest.raises(ValueError):replace(snapshot,instrument_provenance='claimed_verified')
    for gate in ('enabled','fit_admissible','ready_to_run','chart_admissible','hydraulic_admissible','scientifically_qualified'):
        with pytest.raises(ValueError):replace(snapshot,**{gate:True})
        assert getattr(snapshot,gate) is False
    with pytest.raises(AttributeError):hb.SCIENTIFIC_QUALIFICATION_GATE=True
    with pytest.raises(AttributeError):del hb.SCIENTIFIC_QUALIFICATION_GATE
    result=hb.HBFitResult()
    for gate in ('scientifically_qualified_for_hydraulic_charts','chart_lane_admissible'):
        with pytest.raises(TypeError):replace(result,**{gate:True})
        assert getattr(pickle.loads(pickle.dumps(result)),gate) is False
        assert result.to_dict()[gate] is False


B2B_APP_SOURCE_SHA = '0391def0bfe859249331bdb9d94744cc94607af0'


@pytest.fixture(scope='module')
def cfw128_b2b_reviewed_sources(bug01_reviewed_report_base):
    import test_audit_regressions as audit
    from cfw128_hb_intake import snapshot_lab_intake
    case=audit.AuditRegressions();state=deepcopy(bug01_reviewed_report_base)
    state['lab_qc_params']['Main']['reviewed']=False
    app=case.app(state);case.phase(app,'phase7')
    next(b for b in app.button if b.label=='Confirm measured lab results').click().run()
    cement=app.session_state.to_dict()
    next(w for w in app.checkbox if w.label=='BHCT — Ramp-Down - Displacement Fluid').check().run()
    for rpm,value in zip((300,200,100,60,30,6,3),('168','116','64','41','24','8','6')):
        next(w for w in app.text_input if w.label==f'{rpm} RPM - BHCT — Ramp-Down - Displacement Fluid').set_value(value).run()
    next(b for b in app.button if b.label=='Confirm measured Mud lab results').click().run()
    mud=app.session_state.to_dict()
    result={}
    for fluid,source in [('Main',cement),('Displacement Fluid',mud)]:
        snapshot=snapshot_lab_intake(source,fluid,app_source_sha=B2B_APP_SOURCE_SHA)
        assert snapshot.status=='CAPTURED_FOR_FUTURE_REVIEW'
        result[fluid]=(source,snapshot)
    return result


@pytest.mark.parametrize('fluid',['Main','Displacement Fluid'])
def test_cfw128_b2b_real_reviewed_sources_raw_pairing_restore_and_no_fit(cfw128_b2b_reviewed_sources,fluid,monkeypatch,tmp_path):
    from dataclasses import asdict
    from project_state import fingerprint
    import test_audit_regressions as audit
    from cfw128_hb_intake import snapshot_lab_intake
    from cfw128_hb_numeric import prepare_hb_intent
    import cfw128_hb03t_frozen as hb
    def forbidden(*a,**kw):raise AssertionError('A handoff cannot fit or convert engine units.')
    monkeypatch.setattr(hb,'fit_full_hb',forbidden);monkeypatch.setattr(hb,'to_engine_field',forbidden)
    state,snapshot=deepcopy(cfw128_b2b_reviewed_sources[fluid]);before=pickle.dumps((state,snapshot))
    intent=prepare_hb_intent(snapshot,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    assert intent.status=='HOLD_INSTRUMENT_PROVENANCE_UNVERIFIED' and intent.instrument_provenance=='UNVERIFIED'
    assert intent.rpm_order==snapshot.rpm_order==hb.RPM_ORDER==(300,200,100,60,30,6,3)
    assert intent.dials==tuple(r.dial for r in snapshot.readings)
    assert tuple((r.rpm,r.raw,r.raw_type,r.dial) for r in intent.readings)==tuple((r.rpm,r.raw,r.raw_type,r.dial) for r in snapshot.readings)
    assert all(type(r.dial) is int and r is not old for r,old in zip(intent.readings,snapshot.readings))
    assert intent.upstream_status==snapshot.status and intent.upstream_reason_codes==snapshot.reason_codes
    assert intent.upstream_source_identity==snapshot.source_identity and intent.upstream_request_identity==snapshot.request_identity
    assert intent.request_identity==fingerprint(['cfw128-b2b-request/1',intent.source_identity,B2B_APP_SOURCE_SHA])
    assert intent==prepare_hb_intent(snapshot,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    restored=snapshot_lab_intake(audit.round_trip(state),fluid,app_source_sha=B2B_APP_SOURCE_SHA)
    assert prepare_hb_intent(restored,expected_app_source_sha=B2B_APP_SOURCE_SHA)==intent
    assert pickle.dumps((state,snapshot))==before
    for gate in ('enabled','fit_admissible','ready_to_run','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(intent,gate) is False and asdict(intent)[gate] is False
    assert not {'tau_y_pa','k_pa_s_n','n_dimensionless','pressure','qout','pv_cp'} & asdict(intent).keys()
    # Preview is capture-time data, not a currentness receipt for subsequently edited state.
    state['lab_qc_params'][fluid]['rheology']['bhct_down']['readings']['300']='169'
    assert prepare_hb_intent(snapshot,expected_app_source_sha=B2B_APP_SOURCE_SHA)==intent
    stale=snapshot_lab_intake(state,fluid,app_source_sha=B2B_APP_SOURCE_SHA)
    held=prepare_hb_intent(stale,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    assert held.status=='SOURCE_NOT_READY' and held.dials==held.readings==()
    import json
    (tmp_path/(fluid.replace(' ','-')+'-intent.json')).write_text(json.dumps(asdict(intent),indent=2))


@pytest.mark.parametrize('fault,upstream',[('unselected','NOT_SELECTED'),('incomplete','INCOMPLETE_INPUT'),
    ('invalid','INVALID_INPUT'),('unreviewed','REVIEW_REQUIRED'),('stale','STALE_REVIEW'),
    ('inactive','NOT_APPLICABLE'),('unavailable','NOT_AVAILABLE')])
def test_cfw128_b2b_upstream_holds_are_exact_and_empty(cfw128_b2b_reviewed_sources,fault,upstream,monkeypatch):
    from cfw128_hb_intake import snapshot_lab_intake
    from cfw128_hb_numeric import prepare_hb_intent
    import cfw128_hb03t_frozen as hb
    monkeypatch.setattr(hb,'fit_full_hb',lambda *a,**k:pytest.fail('No live fitting'))
    monkeypatch.setattr(hb,'to_engine_field',lambda *a,**k:pytest.fail('No live field conversion'))
    state,_=deepcopy(cfw128_b2b_reviewed_sources['Main']);qc=state['lab_qc_params']['Main'];fluid='Main'
    if fault=='unselected':qc['rheology']['bhct_down']['selected']=False
    elif fault=='incomplete':qc['rheology']['bhct_down']['readings'].pop('3')
    elif fault=='invalid':qc['rheology']['bhct_down']['readings']['300']=True
    elif fault=='unreviewed':qc['reviewed']=False
    elif fault=='stale':qc['rheology']['bhct_down']['readings']['300']='169'
    elif fault=='inactive':state['fluids_config']['active'].remove('Main')
    else:fluid='Mud'
    snapshot=snapshot_lab_intake(state,fluid,app_source_sha=B2B_APP_SOURCE_SHA);assert snapshot.status==upstream
    before=pickle.dumps((state,snapshot));held=prepare_hb_intent(snapshot,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    assert held.status=='SOURCE_NOT_READY' and held.readings==held.dials==held.rpm_order==()
    assert held.upstream_status==upstream and held.upstream_reason_codes==snapshot.reason_codes
    assert pickle.dumps((state,snapshot))==before


@pytest.mark.parametrize('fault',['dial','raw_type','fraction','negative','nan','bool','dial_float','rpm_duplicate',
    'rpm_order','rpm_type','missing','dataset','alias','review_missing','request','instrument','authorization'])
def test_cfw128_b2b_captured_source_mutations_fail_closed(cfw128_b2b_reviewed_sources,fault):
    from dataclasses import replace
    from cfw128_hb_numeric import prepare_hb_intent
    _,original=cfw128_b2b_reviewed_sources['Main'];source=deepcopy(original);rows=list(source.readings)
    if fault=='dial':rows[0]=replace(rows[0],dial=rows[0].dial+1)
    elif fault=='raw_type':rows[0]=replace(rows[0],raw_type='float')
    elif fault=='fraction':rows[0]=replace(rows[0],raw='168.0000000000001')
    elif fault=='negative':rows[0]=replace(rows[0],raw=-1,raw_type='int',dial=-1)
    elif fault=='nan':rows[0]=replace(rows[0],raw=float('nan'),raw_type='float')
    elif fault=='bool':rows[0]=replace(rows[0],raw=True,raw_type='bool')
    elif fault=='dial_float':rows[0]=replace(rows[0],dial=float(rows[0].dial))
    elif fault=='rpm_duplicate':rows[1]=replace(rows[1],rpm=rows[0].rpm)
    elif fault=='rpm_type':rows[0]=replace(rows[0],rpm=float(rows[0].rpm))
    elif fault=='missing':rows.pop()
    elif fault=='dataset':object.__setattr__(source,'dataset','surface_down')
    elif fault=='rpm_order':object.__setattr__(source,'rpm_order',tuple(reversed(source.rpm_order)))
    elif fault=='alias':source=replace(source,fluid_name='Mud')
    elif fault=='review_missing':source=replace(source,review_signature=None)
    elif fault=='request':source=replace(source,request_identity='a'*64)
    elif fault=='instrument':object.__setattr__(source,'instrument_provenance','claimed_Fann35_verified')
    else:object.__setattr__(source,'enabled',True)
    if fault in ('dial','raw_type','fraction','negative','nan','bool','dial_float','rpm_duplicate','rpm_type','missing'):
        source=replace(source,readings=tuple(rows))
    before=pickle.dumps(source);held=prepare_hb_intent(source,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    assert held.status=='INVALID_SNAPSHOT' and held.readings==held.dials==()
    assert held.instrument_provenance=='UNVERIFIED'
    assert pickle.dumps(source)==before
    assert all(getattr(held,g) is False for g in ('enabled','fit_admissible','ready_to_run','hydraulic_admissible','chart_admissible','scientifically_qualified'))


@pytest.mark.parametrize('value',[2**53+1,2**53+3,10**400,2**20000],ids=['2pow53plus1','2pow53plus3','tenpow400','2pow20000'])
def test_cfw128_b2b_precision_unsafe_integer_hold_is_lossless(cfw128_b2b_reviewed_sources,value):
    from dataclasses import replace
    from cfw128_hb_numeric import prepare_hb_intent
    _,source=cfw128_b2b_reviewed_sources['Main'];r=source.readings[0]
    changed=replace(source,readings=(replace(r,raw=value,raw_type='int',dial=value),*source.readings[1:]))
    first=prepare_hb_intent(changed,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    assert first.status=='HOLD_NUMERIC_REPRESENTATION' and first.reason_codes==('FLOAT_REPRESENTATION_UNSAFE',)
    assert first.readings==first.dials==()
    assert first==prepare_hb_intent(changed,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    other=replace(changed,readings=(replace(changed.readings[0],raw=value+2,dial=value+2),*changed.readings[1:]))
    assert prepare_hb_intent(other,expected_app_source_sha=B2B_APP_SOURCE_SHA).source_identity!=first.source_identity


def test_cfw128_b2b_identities_preserve_raw_types_spelling_and_upstream_provenance(cfw128_b2b_reviewed_sources):
    from dataclasses import replace
    from project_state import fingerprint
    from cfw128_hb_numeric import prepare_hb_intent
    _,source=cfw128_b2b_reviewed_sources['Main'];r=source.readings[0];identities=[]
    for raw in (r.dial,float(r.dial),str(r.dial),' 00'+str(r.dial)+'.00 '):
        changed=replace(source,readings=(replace(r,raw=raw,raw_type=type(raw).__name__),*source.readings[1:]))
        intent=prepare_hb_intent(changed,expected_app_source_sha=B2B_APP_SOURCE_SHA)
        assert intent.status=='HOLD_INSTRUMENT_PROVENANCE_UNVERIFIED' and intent.readings[0].raw==raw
        assert intent.readings[0].raw_type==type(raw).__name__
        identities.append((intent.source_identity,intent.request_identity,intent.projection_identity))
    assert all(len({ids[i] for ids in identities})==4 for i in range(3))
    changed=replace(source,source_identity='b'*64,request_identity=fingerprint([1,B2B_APP_SOURCE_SHA,'Main','b'*64]))
    assert prepare_hb_intent(changed,expected_app_source_sha=B2B_APP_SOURCE_SHA).source_identity!=prepare_hb_intent(source,expected_app_source_sha=B2B_APP_SOURCE_SHA).source_identity
    # A coherent edit cannot be authenticated from a receipt-only snapshot: it is
    # explicitly still a hold, with changed identities, never revalidated review.
    changed=replace(source,readings=(replace(r,raw=str(r.dial+1),raw_type='str',dial=r.dial+1),*source.readings[1:]))
    assert prepare_hb_intent(changed,expected_app_source_sha=B2B_APP_SOURCE_SHA).status=='HOLD_INSTRUMENT_PROVENANCE_UNVERIFIED'


def test_cfw128_b2b_counterfeit_sha_and_clone_authorization_negatives(cfw128_b2b_reviewed_sources,monkeypatch):
    import copy
    from dataclasses import asdict,replace,fields,is_dataclass,FrozenInstanceError
    from types import SimpleNamespace
    from cfw128_hb_intake import LabIntakeSnapshot
    import cfw128_hb_numeric as bridge
    _,source=cfw128_b2b_reviewed_sources['Main']
    for counterfeit in ({'pv_cp':45,'yield_point':15},SimpleNamespace(**asdict(source))):
        with pytest.raises(TypeError):bridge.prepare_hb_intent(counterfeit,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    class Counterfeit(LabIntakeSnapshot):pass
    fake=Counterfeit(**{f.name:getattr(source,f.name) for f in fields(source) if f.init})
    with pytest.raises(TypeError):bridge.prepare_hb_intent(fake,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    for sha in ('wrong',B2B_APP_SOURCE_SHA.upper(),'b'*40,True):
        with pytest.raises(ValueError):bridge.prepare_hb_intent(source,expected_app_source_sha=sha)
    with pytest.raises(TypeError):bridge.prepare_hb_intent(source,expected_app_source_sha=B2B_APP_SOURCE_SHA,instrument='Fann 35')
    monkeypatch.setenv('CFW128_HB_ENABLED','True');monkeypatch.setattr(bridge,'enabled',True,raising=False)
    result=bridge.prepare_hb_intent(source,expected_app_source_sha=B2B_APP_SOURCE_SHA)
    def immutable(v):
        if is_dataclass(v):
            for f in fields(v):immutable(getattr(v,f.name))
        elif type(v) is tuple:
            for x in v:immutable(x)
        else:assert v is None or type(v) in (str,int,float,bool)
    immutable(result)
    assert copy.copy(result)==copy.deepcopy(result)==pickle.loads(pickle.dumps(result))==result
    for gate in ('enabled','fit_admissible','ready_to_run','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(result,gate) is False and asdict(result)[gate] is False
        with pytest.raises(FrozenInstanceError):setattr(result,gate,True)
        with pytest.raises(ValueError):replace(result,**{gate:True})
        changed=asdict(result);changed[gate]=True
        with pytest.raises(TypeError):type(result)(**changed)
    with pytest.raises(FrozenInstanceError):result.readings[0].dial=0
    with pytest.raises(TypeError):replace(result,readings=[*result.readings])
    with pytest.raises(ValueError):replace(result,status='OK')


def test_cfw128_b2b_bridge_no_runtime_callers_or_forbidden_imports():
    import ast,subprocess,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    forbidden={'scipy','cfw128_hb03t_frozen','pumping_simulation','cement_chart_model','cement_charts_engine',
               'cement_chart_report','fluids_charts_module_v1_4_2','centralizer_adapter','centralizer_optimizer_engine'}
    for f in root.glob('*.py'):
        nodes=list(ast.walk(ast.parse(f.read_text())))
        imports={n.module.split('.')[0] for n in nodes if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split('.')[0] for n in nodes if isinstance(n,ast.Import) for a in n.names}
        if f.name=='cfw128_hb_numeric.py':assert not imports & forbidden
        else:assert 'cfw128_hb_numeric' not in imports
    script='import sys,cfw128_hb_numeric; assert not '+repr(forbidden)+' & set(sys.modules)'
    subprocess.run([sys.executable,'-B','-W','error','-c',script],cwd=root,check=True)


_B2B_OTHER_ROOTS=sorted(p.name for p in __import__('pathlib').Path(__file__).resolve().parents[1].glob('*.py')
                       if p.name not in ('cfw128_hb_intake.py','cfw128_hb_numeric.py'))


@pytest.mark.parametrize('filename',_B2B_OTHER_ROOTS)
@pytest.mark.parametrize('module',['cfw128_hb_intake','cfw128_hb_numeric'])
def test_cfw128_b2b_every_other_root_rejects_import_mutation(filename,module,bug01_reviewed_report_base,monkeypatch):
    from pathlib import Path
    root=Path(__file__).resolve().parents[1];target=root/filename;original=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda path,*a,**kw:original(path,*a,**kw)+'\nimport '+module+'\n' if path==target else original(path,*a,**kw))
    with pytest.raises(AssertionError):
        if module=='cfw128_hb_intake':
            test_cfw128_b1_deep_immutability_and_no_fitting_or_physics_imports(bug01_reviewed_report_base,monkeypatch)
        else:test_cfw128_b2b_bridge_no_runtime_callers_or_forbidden_imports()


C1_APP_SOURCE_SHA = 'b8293cc8c643916bcad647ca523fb3c747be4de4'


def cfw128_c1_uat19_state():
    # Only these eight descriptions/MD/OD/ID values are owner field evidence.
    rows=[('Previous Casing','224','20',18.730),('Previous Casing','2547','13 3/8',12.215),
          ('Previous Casing','4033','9 5/8',8.535),('Previous Liner Lap','3885','7',6.184),
          ('Previous Liner Shoe','4860','7',6.184),('Tie Back Liner Lap','2800','7',6.004),
          ('Tie Back Liner Shoe','3885','7',6.004),('Drill Pipes','2800','5',4.276)]
    table=pd.DataFrame(rows,columns=['Description','MD (m)','Size (in)','ID (in)'])
    # Synthetic scaffolding only: job taxonomy, vertical trajectory with TD=5000,
    # and report/chart excess mode. No pressure, fluids, rates or lab facts.
    job='TIE BACK LNR 7"'
    state={'job_type':job,'hardware_table':table,'well_geometry':{'version':1,'type':'Vertical','td_m':5000.},
        'placement_config':{'job_type':job,'chart_excess_mode':'ignore'}}
    state['placement_config']['target_row']=next(iter(hardware_choices(table,target_descriptions(job))))
    state['placement_config']['host_row']=next(iter(hardware_choices(table.iloc[[2]],{'Previous Casing'})))
    return state



def test_cfw128_c1_uat19_field_geometry_partial_return_preview(tmp_path):
    import json
    from dataclasses import asdict
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    state=cfw128_c1_uat19_state();frame=state['hardware_table'];before=pickle.dumps(state)
    snapshot=snapshot_geometry(state,app_source_sha=C1_APP_SOURCE_SHA)
    assert snapshot.status=='GEOMETRY_REPRESENTABLE'
    result=prepare_er03_preview(snapshot,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert result.status=='HOLD_ENGINE_CONTRACT'
    assert [(s.top_md,s.bottom_md,s.od_in,s.id_in,s.source_rows) for s in result.injection_sections]==[
        (0.,2800.,5.,4.276,(7,)),(2800.,3885.,7.,6.004,(6,))]
    assert (result.string_top_md,result.shoe_md)==(2800.,3885.)
    assert (result.return_top_md,result.return_bottom_md,result.return_travel_md)==(2800.,3885.,(3885.,2800.))
    assert [(s.top_md,s.bottom_md,s.wall.id_in,s.running.od_in,s.wall.source_rows,s.running.source_rows) for s in result.return_sections]==[(2800.,3885.,8.535,7.,(2,),(6,))]
    assert result.selected_host.source_rows==(2,) and result.selected_host.sections[0].id_in==8.535
    assert (result.receiver.top_md,result.receiver.shoe_md,result.receiver.source_rows)==(3885.,4860.,(4,))
    assert result.target_token==state['placement_config']['target_row'] and result.host_token==state['placement_config']['host_row']
    assert result.installed_strings==snapshot.installed_strings and result.enclosing_sections==snapshot.enclosing_sections
    assert all(s.bottom_md<=3885. for s in result.injection_sections)
    assert all(2800.<=s.top_md<s.bottom_md<=3885. for s in result.return_sections)
    assert 'Open Hole Size' not in frame.Description.values
    assert {'TIEBACK_RETURN_TERMINATES_AT_TOP','ER03_SCALAR_PATH_MISMATCH',
        'UAT19_TIEBACK_PARTIAL_RETURN_ENGINE_NOT_VALIDATED','TIEBACK_OUTLET_PRESSURE_BC_UNDEFINED'}<=set(result.reason_codes)
    assert not any(k in state for k in ('fluid_data','fluids_config','lab_qc_params','pump_rate','outlet_pressure'))
    assert frame is state['hardware_table'] and pickle.dumps(state)==before
    (tmp_path/'uat19-field-topology.json').write_text(json.dumps(asdict(result),indent=2))


@pytest.mark.parametrize('fault',['typo_lap','missing_lap','duplicate_lap','missing_shoe','duplicate_shoe',
    'missing_top','duplicate_top','stale_host','clearance','fake_hole','missing_dp','gap','overlap','tb_top_conflict'])
def test_cfw128_c1_uat19_invalid_hardware_never_becomes_topology(fault):
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    state=cfw128_c1_uat19_state();t=state['hardware_table']
    if fault=='typo_lap':t.at[3,'MD (m)']='3913'  # O19-01 user typo, NOT a product bug.
    elif fault in ('missing_lap','missing_shoe','missing_top','missing_dp'):
        state['hardware_table']=t.drop(index={'missing_lap':3,'missing_shoe':4,'missing_top':5,'missing_dp':7}[fault]).reset_index(drop=True)
    elif fault in ('duplicate_lap','duplicate_shoe','duplicate_top'):
        state['hardware_table']=pd.concat([t,t.iloc[[{'duplicate_lap':3,'duplicate_shoe':4,'duplicate_top':5}[fault]]]],ignore_index=True)
    elif fault=='stale_host':state['placement_config']['host_row']='f'*64
    elif fault=='clearance':t.at[2,'ID (in)']=7.
    elif fault=='fake_hole':t.at[2,'Description']='Open Hole Size'
    elif fault=='gap':t.at[7,'MD (m)']='1-2800'
    elif fault=='overlap':
        t.at[7,'MD (m)']='0-1700';extra=t.iloc[[7]].copy();extra['MD (m)']='1600-2800'
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    else:t.at[6,'MD (m)']='2801-3885'
    before=pickle.dumps(state);snap=snapshot_geometry(state,app_source_sha=C1_APP_SOURCE_SHA)
    assert snap.status=='INVALID_INPUT',snap.detail
    result=prepare_er03_preview(snap,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert result.status=='SOURCE_INVALID' and result.upstream_reason_codes==snap.reason_codes
    assert result.injection_sections==result.return_sections==() and pickle.dumps(state)==before


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c1_all_jobs_preserve_real_paths_and_host_specific_return(job):
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    state=bug01_geometry_case(job);before=pickle.dumps(state)
    source=snapshot_geometry(state,app_source_sha=C1_APP_SOURCE_SHA)
    result=prepare_er03_preview(source,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert result.status in ('STRUCTURAL_PREVIEW_ONLY','HOLD_ENGINE_CONTRACT'),result.reason_codes
    assert result.upstream_status==source.status and result.upstream_reason_codes==source.reason_codes
    assert set(source.reason_codes)<=set(result.reason_codes)
    assert result.injection_sections==source.active_sections and result.enclosing_sections==source.enclosing_sections
    assert result.return_top_md==(source.string_top_md if source.kind=='tieback' else 0.)
    assert result.return_bottom_md==source.shoe_md
    assert result.return_sections[0].top_md==result.return_top_md and result.return_sections[-1].bottom_md==source.shoe_md
    if job in ('TIE BACK LNR 5"','TIE BACK LNR 4 1/2"'):
        assert result.return_sections[0].wall.id_in==6.094  # Actual synthetic installed 7-in liner, not 8.535 default.
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('case',['a_zero','taper','piecewise_active','dp_taper','body_taper'])
def test_cfw128_c1_unrepresentable_app_geometry_keeps_holds_and_exact_sections(case):
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    state=synthetic_tieback(top=0.) if case=='a_zero' else r18c_tapered_state(100.) if case in ('taper','piecewise_active') else synthetic_tieback(top=400.)
    if case=='piecewise_active':
        state['hardware_table'].loc[state['hardware_table'].Description=='Tie Back Liner Lap','MD (m)']='0'
        state['hardware_table']=state['hardware_table'][state['hardware_table'].Description!='Drill Pipes'].reset_index(drop=True)
        state['placement_config']['host_row']=next(iter(hardware_choices(state['hardware_table'],{'Previous Casing'})))
    elif case=='dp_taper':
        t=state['hardware_table'];i=t.index[t.Description=='Drill Pipes'][0];t.at[i,'MD (m)']='200'
        extra=t.iloc[[i]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    elif case=='body_taper':
        t=state['hardware_table'];t.at[0,'MD (m)']='400-500';extra=t.iloc[[0]].copy()
        extra['MD (m)']='500-700';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t.iloc[:1],extra,t.iloc[1:]],ignore_index=True)
        state['placement_config']['target_row']=next(k for k,v in hardware_choices(state['hardware_table'],target_descriptions(state['job_type'])).items() if v['depth']==700.)
    source=snapshot_geometry(state,app_source_sha=C1_APP_SOURCE_SHA)
    assert source.status=='ENGINE_INTERFACE_NOT_REPRESENTABLE',source.detail
    result=prepare_er03_preview(source,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert result.status=='HOLD_ENGINE_CONTRACT',result.reason_codes
    assert set(source.reason_codes)<=set(result.reason_codes)
    assert result.installed_strings==source.installed_strings and result.injection_sections==source.active_sections
    assert result.return_top_md==source.string_top_md and result.return_travel_md==(source.shoe_md,source.string_top_md)
    if case=='a_zero':
        assert 'POINT_A_ZERO' in result.reason_codes and not any(s.description=='Drill Pipes' for s in result.injection_sections)
    if case=='taper':
        previous=next(s for s in result.installed_strings if s.description=='Previous Tie Back Liner Shoe')
        assert len(previous.sections)==2 and previous.sections[0].od_in!=previous.sections[1].od_in


def test_cfw128_c1_directional_interior_values_are_app_owned_not_linear_er03():
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    state=synthetic_tieback();state['well_geometry']={'type':'Directional','survey':pd.DataFrame(
        [[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    source=snapshot_geometry(state,app_source_sha=C1_APP_SOURCE_SHA,query_md=(50.,))
    result=prepare_er03_preview(source,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert result.status=='HOLD_ENGINE_CONTRACT' and 'DIRECTIONAL_INTERIOR_TVD_CONVENTION_HOLD' in result.reason_codes
    assert result.survey==source.survey and result.trajectory==source.trajectory
    points={p.md:p.tvd for p in result.trajectory}
    assert points[50.]==pytest.approx(47.7464829275686,abs=1e-12)
    linear=.5*(points[0.]+points[100.]);assert linear==pytest.approx(41.3496671566,abs=1e-8)
    assert points[50.]!=pytest.approx(linear,abs=1.)


@pytest.mark.parametrize('fault',['gap','overlap','order','missing','diameter','nan','source_rows','body_role',
    'selected_host','receiver','target','top','outer_provenance','fake_hole','trajectory','job','source_id'])
def test_cfw128_c1_snapshot_mutations_reject_without_engine(fault):
    from dataclasses import replace
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    source=snapshot_geometry(cfw128_c1_uat19_state(),app_source_sha=C1_APP_SOURCE_SHA)
    a=source.active_sections;outer=source.enclosing_sections
    if fault=='gap':source=replace(source,active_sections=(a[0],replace(a[1],top_md=2801.)))
    elif fault=='overlap':source=replace(source,active_sections=(a[0],replace(a[1],top_md=2799.)))
    elif fault=='order':source=replace(source,active_sections=tuple(reversed(a)))
    elif fault=='missing':source=replace(source,active_sections=a[1:])
    elif fault=='diameter':source=replace(source,active_sections=(a[0],replace(a[1],od_in=9.)))
    elif fault=='nan':source=replace(source,active_sections=(replace(a[0],id_in=float('nan')),a[1]))
    elif fault=='source_rows':source=replace(source,active_sections=(replace(a[0],source_rows=(-1,)),a[1]))
    elif fault=='body_role':source=replace(source,active_sections=(a[0],replace(a[1],description='Liner Shoe')))
    elif fault=='selected_host':source=replace(source,selected_host=replace(source.selected_host,shoe_md=3000.))
    elif fault=='receiver':source=replace(source,receiver=replace(source.receiver,top_md=3913.))
    elif fault=='target':source=replace(source,target_token='stale-token')
    elif fault=='top':source=replace(source,string_top_md=2700.)
    elif fault=='outer_provenance':source=replace(source,enclosing_sections=(replace(outer[0],source_rows=(999,)),))
    elif fault=='fake_hole':source=replace(source,enclosing_sections=(replace(outer[0],description='Open Hole Size',od_in=8.535,id_in=8.535,source_rows=(99,)),))
    elif fault=='trajectory':source=replace(source,trajectory=source.trajectory[1:])
    elif fault=='job':source=replace(source,job='LNR 7"')
    else:source=replace(source,source_identity='invalid')
    before=pickle.dumps(source);result=prepare_er03_preview(source,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert result.status=='INVALID_SNAPSHOT',result.reason_codes
    assert result.injection_sections==result.return_sections==() and pickle.dumps(source)==before


def test_cfw128_c1_identity_clone_boundary_and_stale_capture_contract():
    from dataclasses import replace,asdict,FrozenInstanceError,fields,is_dataclass
    import copy
    from cfw128_adapter import snapshot_geometry
    import cfw128_er03_contract as c1
    state=cfw128_c1_uat19_state();snapshot=snapshot_geometry(state,app_source_sha=C1_APP_SOURCE_SHA)
    result=c1.prepare_er03_preview(snapshot,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert result==c1.prepare_er03_preview(snapshot,expected_app_source_sha=C1_APP_SOURCE_SHA)
    assert copy.copy(result)==copy.deepcopy(result)==pickle.loads(pickle.dumps(result))==result
    assert all(a is not b for a,b in zip(snapshot.active_sections,result.injection_sections))
    def frozen(v):
        if is_dataclass(v):
            for f in fields(v):frozen(getattr(v,f.name))
        elif type(v) is tuple:
            for x in v:frozen(x)
        else:assert v is None or type(v) in (str,int,float,bool)
    frozen(result)
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert asdict(result)[flag] is False
        with pytest.raises(FrozenInstanceError):setattr(result,flag,True)
        with pytest.raises(ValueError):replace(result,**{flag:True})
        data=asdict(result);data[flag]=True
        with pytest.raises(TypeError):type(result)(**data)
    with pytest.raises(ValueError):replace(result,return_top_md=0.)
    with pytest.raises(ValueError):replace(result,return_bottom_md=4860.)
    with pytest.raises(TypeError):c1.prepare_er03_preview({'GeometrySpec':'fake'},expected_app_source_sha=C1_APP_SOURCE_SHA)
    with pytest.raises(ValueError):c1.prepare_er03_preview(snapshot,expected_app_source_sha='f'*40)
    for modified in (replace(snapshot,source_identity='a'*64),replace(snapshot,request_identity='b'*64),
                     replace(snapshot,target_token='c'*64)):
        changed=c1.prepare_er03_preview(modified,expected_app_source_sha=C1_APP_SOURCE_SHA)
        assert changed.projection_identity!=result.projection_identity and changed.ready_to_run is False
    state['hardware_table'].at[2,'ID (in)']=8.534
    assert c1.prepare_er03_preview(snapshot,expected_app_source_sha=C1_APP_SOURCE_SHA)==result
    fresh=snapshot_geometry(state,app_source_sha=C1_APP_SOURCE_SHA)
    assert c1.prepare_er03_preview(fresh,expected_app_source_sha=C1_APP_SOURCE_SHA).projection_identity!=result.projection_identity
    invalid=snapshot_geometry({},app_source_sha=C1_APP_SOURCE_SHA)
    assert c1.prepare_er03_preview(invalid,expected_app_source_sha=C1_APP_SOURCE_SHA).status=='SOURCE_INVALID'
    na=snapshot_geometry({'job_type':'CMT PLUG'},app_source_sha=C1_APP_SOURCE_SHA)
    assert c1.prepare_er03_preview(na,expected_app_source_sha=C1_APP_SOURCE_SHA).status=='NOT_APPLICABLE'


def test_cfw128_c1_import_call_isolation_and_canonical_metadata():
    import ast,subprocess,sys
    from pathlib import Path
    import cfw128_er03_contract
    root=Path(__file__).resolve().parents[1]
    forbidden={'scipy','pumping_simulation','fluids_charts_module_v1_4_2','cement_charts_engine','cement_chart_report',
        'centralizer_optimizer_engine','centralizer_adapter','cfw128_hb03t_frozen'}
    for path in root.glob('*.py'):
        tree=ast.parse(path.read_text());imports={n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        if path.name=='cfw128_er03_contract.py':assert not imports & forbidden
        elif path.name != 'cfw128_er03_boundary.py':assert 'cfw128_er03_contract' not in imports
    script='import sys,cfw128_er03_contract; assert not '+repr(forbidden)+' & set(sys.modules)'
    subprocess.run([sys.executable,'-B','-W','error','-c',script],cwd=root,check=True)


_C1_OTHER_ROOTS=sorted(p.name for p in __import__('pathlib').Path(__file__).resolve().parents[1].glob('*.py')
                       if p.name not in ('cfw128_adapter.py','cfw128_er03_contract.py','cfw128_er03_boundary.py'))


@pytest.mark.parametrize('filename',_C1_OTHER_ROOTS)
@pytest.mark.parametrize('module',['cfw128_adapter','cfw128_er03_contract'])
def test_cfw128_c1_all_other_roots_reject_import_mutation(filename,module,monkeypatch):
    from pathlib import Path
    root=Path(__file__).resolve().parents[1];target=root/filename;read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+'\nimport '+module+'\n' if p==target else read(p,*a,**k))
    with pytest.raises(AssertionError):
        if module=='cfw128_adapter':test_cfw128_adapter_remains_unimported_by_production_and_research_free()
        else:test_cfw128_c1_import_call_isolation_and_canonical_metadata()


# C2a adds only a disabled physical-port/unknown-law hold after accepted C1.
C2A_APP_SOURCE_SHA = '225eabe0f56d5eae043eaea82d69a45093ae340a'


def cfw128_c2a_capture(state=None, query_md=()):
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    state = cfw128_c1_uat19_state() if state is None else state
    return prepare_er03_preview(snapshot_geometry(state,app_source_sha=C2A_APP_SOURCE_SHA,query_md=query_md),
                                expected_app_source_sha=C2A_APP_SOURCE_SHA)


def test_cfw128_c2a_uat19_ports_are_locations_only_with_no_pressure_invention(tmp_path):
    from dataclasses import asdict
    import json
    from cfw128_er03_boundary import assess_er03_boundary
    state=cfw128_c1_uat19_state();before=pickle.dumps(state);preview=cfw128_c2a_capture(state)
    result=assess_er03_boundary(preview,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert result.status=='HOLD_ENGINE_BOUNDARY_UNVERIFIED' and result.preview==preview
    assert [(p.md_m,p.leg,p.direction) for p in result.physical_ports]==[
        (0.,'injection','entry'),(3885.,'injection','exit'),
        (3885.,'annular_return','entry'),(2800.,'annular_return','exit')]
    assert result.qout_location_only.name=='Tie Back Lap (MD=A)' and result.qout_location_only.md_m==2800.
    assert result.qout_rate==result.mass_volume_conservation==result.fluid_inventory_transport=='NOT_EVALUATED'
    assert result.return_outlet_pressure==result.pressure_datum==result.pressure_reference=='UNSPECIFIED'
    assert result.inlet_outlet_pressure_closure==result.shutin_bhsp_reference==result.freefall_tail_interpretation==result.three_chart_labels=='NOT_EVALUATED'
    assert result.instrument_provenance=='UNVERIFIED'
    assert set(preview.reason_codes)<=set(result.reason_codes)
    assert {'HOLD_PARTIAL_RETURN_PRESSURE_BC','HOLD_ER03_SURFACE_UTUBE_MODEL',
        'HOLD_RETURN_FLOW_AND_INVENTORY_LAW','HOLD_SHUTIN_BHSP_REFERENCE',
        'UAT19_TIEBACK_PARTIAL_RETURN_ENGINE_NOT_VALIDATED','TIEBACK_OUTLET_PRESSURE_BC_UNDEFINED'}<=set(result.reason_codes)
    assert preview.selected_host.source_rows==(2,) and preview.selected_host.sections[0].id_in==8.535
    assert (preview.receiver.top_md,preview.receiver.shoe_md,preview.receiver.sections[0].id_in)==(3885.,4860.,6.184)
    assert [(v.top_md,v.bottom_md,v.id_in) for v in preview.injection_sections]==[(0.,2800.,4.276),(2800.,3885.,6.004)]
    assert preview.return_travel_md==(3885.,2800.) and len(preview.return_sections)==1
    assert not any(v.description=='Open Hole Size' for v in preview.enclosing_sections)
    assert state['hardware_table'].shape==(8,4) and pickle.dumps(state)==before
    (tmp_path/'uat19-boundary-hold.json').write_text(json.dumps(asdict(result),indent=2))


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2a_all_jobs_keep_host_specific_ports_and_c1_identity(job):
    from cfw128_er03_boundary import assess_er03_boundary
    state=bug01_geometry_case(job);before=pickle.dumps(state);p=cfw128_c2a_capture(state)
    r=assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert r.preview==p and r.status=='HOLD_ENGINE_BOUNDARY_UNVERIFIED'
    assert r.physical_ports[0].md_m==0. and r.physical_ports[1].md_m==r.physical_ports[2].md_m==p.shoe_md
    assert r.physical_ports[-1].md_m==(p.string_top_md if p.kind=='tieback' else 0.)
    assert r.preview.source_identity==p.source_identity and r.preview.projection_identity==p.projection_identity
    if job in ('TIE BACK LNR 5"','TIE BACK LNR 4 1/2"'):
        assert r.preview.return_sections[0].wall.id_in==6.094  # Synthetic measured 7-in host, not field casing.
    assert pickle.dumps(state)==before and r.instrument_provenance=='UNVERIFIED'


@pytest.mark.parametrize('case',['a_zero','taper','piecewise_active','dp_taper','body_taper'])
def test_cfw128_c2a_segmented_and_zero_cases_remain_explicit_holds(case):
    from cfw128_er03_boundary import assess_er03_boundary
    state=synthetic_tieback(top=0.) if case=='a_zero' else r18c_tapered_state(100.) if case in ('taper','piecewise_active') else synthetic_tieback(top=400.)
    if case=='piecewise_active':
        state['hardware_table'].loc[state['hardware_table'].Description=='Tie Back Liner Lap','MD (m)']='0'
        state['hardware_table']=state['hardware_table'][state['hardware_table'].Description!='Drill Pipes'].reset_index(drop=True)
        state['placement_config']['host_row']=next(iter(hardware_choices(state['hardware_table'],{'Previous Casing'})))
    elif case=='dp_taper':
        t=state['hardware_table'];i=t.index[t.Description=='Drill Pipes'][0];t.at[i,'MD (m)']='200'
        extra=t.iloc[[i]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    elif case=='body_taper':
        t=state['hardware_table'];t.at[0,'MD (m)']='400-500';extra=t.iloc[[0]].copy()
        extra['MD (m)']='500-700';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t.iloc[:1],extra,t.iloc[1:]],ignore_index=True)
        state['placement_config']['target_row']=next(k for k,v in hardware_choices(state['hardware_table'],target_descriptions(state['job_type'])).items() if v['depth']==700.)
    p=cfw128_c2a_capture(state);r=assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert p.upstream_status=='ENGINE_INTERFACE_NOT_REPRESENTABLE' and r.preview==p
    assert r.status=='HOLD_ENGINE_BOUNDARY_UNVERIFIED' and set(p.reason_codes)<=set(r.reason_codes)
    if p.string_top_md==0.:
        assert 'HOLD_TIEBACK_POINT_A_ZERO_TYPED_INTERFACE' in r.reason_codes
        assert r.physical_ports[-1].md_m==0. and all(s.description!='Drill Pipes' for s in p.injection_sections)
    if case!='a_zero':assert 'HOLD_SEGMENTED_GEOMETRY_INTERFACE' in r.reason_codes
    if case=='taper':assert len(next(s for s in p.installed_strings if s.description=='Previous Tie Back Liner Shoe').sections)==2


def test_cfw128_c2a_directional_interior_convention_is_preserved_not_hydraulic_parity():
    from cfw128_er03_boundary import assess_er03_boundary
    state=synthetic_tieback();state['well_geometry']={'type':'Directional','survey':pd.DataFrame(
        [[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    p=cfw128_c2a_capture(state,(50.,));r=assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    points={v.md:v.tvd for v in r.preview.trajectory}
    assert points[50.]==pytest.approx(47.7464829275686,abs=1e-12)
    assert .5*points[100.]==pytest.approx(41.3496671566,abs=1e-8)
    assert r.preview.survey==p.survey and r.preview.trajectory==p.trajectory
    assert 'HOLD_DIRECTIONAL_INTERIOR_TVD' in r.reason_codes


@pytest.mark.parametrize('state',[{}, {'job_type':'CMT PLUG'}])
def test_cfw128_c2a_unavailable_sources_have_no_ports_or_fake_laws(state):
    from cfw128_er03_boundary import assess_er03_boundary
    p=cfw128_c2a_capture(state);r=assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert r.status=='SOURCE_NOT_READY' and r.preview==p
    assert r.physical_ports==() and r.qout_location_only is None and 'C1_SOURCE_NOT_READY' in r.reason_codes
    assert r.return_outlet_pressure=='UNSPECIFIED' and r.qout_rate=='NOT_EVALUATED'


@pytest.mark.parametrize('fault',['top','shoe','return_top','return_bottom','missing_dp','gap','clearance','nan','bool',
    'source_rows','host','receiver','fake_hole','source_identity','upstream_identity','upstream_source','target_token','host_token','projection_identity','reason','mutable','enabled','wrong_sha'])
def test_cfw128_c2a_forged_c1_members_fail_closed(fault):
    from copy import deepcopy
    from dataclasses import replace
    from cfw128_er03_boundary import assess_er03_boundary
    p=deepcopy(cfw128_c2a_capture())
    if fault=='top':object.__setattr__(p,'string_top_md',2799.)
    elif fault=='shoe':object.__setattr__(p,'shoe_md',4860.)
    elif fault=='return_top':object.__setattr__(p,'return_top_md',0.)
    elif fault=='return_bottom':object.__setattr__(p,'return_bottom_md',4860.)
    elif fault=='missing_dp':object.__setattr__(p,'injection_sections',p.injection_sections[1:])
    elif fault in ('gap','clearance','nan','bool','source_rows'):
        s=p.injection_sections[0]
        kwargs={'gap':{'bottom_md':2799.},'clearance':{'od_in':9.},'nan':{'id_in':float('nan')},
                'bool':{'top_md':False},'source_rows':{'source_rows':(-1,)}}[fault]
        object.__setattr__(p,'injection_sections',(replace(s,**kwargs),p.injection_sections[1]))
    elif fault=='host':object.__setattr__(p,'selected_host',None)
    elif fault=='receiver':object.__setattr__(p,'receiver',replace(p.receiver,top_md=3913.))
    elif fault=='fake_hole':object.__setattr__(p,'enclosing_sections',(replace(p.enclosing_sections[0],description='Open Hole Size',od_in=8.535),))
    elif fault in ('source_identity','projection_identity'):object.__setattr__(p,fault,'a'*64)
    elif fault=='upstream_identity':object.__setattr__(p,'upstream_request_identity','b'*64)
    elif fault=='upstream_source':object.__setattr__(p,'upstream_source_identity','b'*64)
    elif fault in ('target_token','host_token'):object.__setattr__(p,fault,'c'*64)
    elif fault=='reason':object.__setattr__(p,'reason_codes',('SCALAR_TIEBACK_SOURCE_PROVED',))
    elif fault=='mutable':object.__setattr__(p,'injection_sections',list(p.injection_sections))
    elif fault=='enabled':object.__setattr__(p,'enabled',True)
    else:object.__setattr__(p,'app_source_sha','a'*40)
    before=pickle.dumps(p)
    with pytest.raises((ValueError,TypeError)):assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert pickle.dumps(p)==before


def test_cfw128_c2a_identities_stale_capture_and_coherent_counterfeit_are_not_authentication():
    from dataclasses import replace
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    from cfw128_er03_boundary import assess_er03_boundary
    state=cfw128_c1_uat19_state();p=cfw128_c2a_capture(state)
    a=assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert a==assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)
    state['hardware_table'].at[2,'ID (in)']=8.534
    assert assess_er03_boundary(p,expected_app_source_sha=C2A_APP_SOURCE_SHA)==a  # Old capture cannot consult new state.
    b=assess_er03_boundary(cfw128_c2a_capture(state),expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert a.projection_identity!=b.projection_identity and a.preview.return_sections!=b.preview.return_sections
    source=snapshot_geometry(state,app_source_sha=C2A_APP_SOURCE_SHA)
    for kwargs in ({'source_identity':'a'*64},{'request_identity':'b'*64},{'target_token':'c'*64}):
        coherent=prepare_er03_preview(replace(source,**kwargs),expected_app_source_sha=C2A_APP_SOURCE_SHA)
        r=assess_er03_boundary(coherent,expected_app_source_sha=C2A_APP_SOURCE_SHA)
        assert r.projection_identity!=b.projection_identity and 'CAPTURE_ONLY_REQUIRES_FRESH_APP_RESNAPSHOT' in r.reason_codes
        assert r.enabled is r.hydraulic_admissible is False


def test_cfw128_c2a_frozen_clone_serialization_and_port_datum_mutations_cannot_enable(monkeypatch):
    from copy import copy,deepcopy
    from dataclasses import asdict,replace,FrozenInstanceError
    from cfw128_er03_boundary import assess_er03_boundary,BoundaryHold
    r=assess_er03_boundary(cfw128_c2a_capture(),expected_app_source_sha=C2A_APP_SOURCE_SHA)
    assert copy(r)==deepcopy(r)==pickle.loads(pickle.dumps(r))==r
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        monkeypatch.setenv('CFW128_'+flag.upper(),'true')
        assert getattr(r,flag) is False
        with pytest.raises(FrozenInstanceError):setattr(r,flag,True)
        with pytest.raises(ValueError):replace(r,**{flag:True})
        data=asdict(r);data[flag]=True
        with pytest.raises(TypeError):BoundaryHold(**data)
    for kwargs in ({'return_outlet_pressure':0.},{'pressure_datum':'surface gauge'},
                   {'status':'READY'},{'reason_codes':()}, {'projection_identity':'a'*64}):
        with pytest.raises(ValueError):replace(r,**kwargs)
    for port in (replace(r.physical_ports[-1],md_m=0.),replace(r.physical_ports[-1],md_m=4860.),
                 replace(r.physical_ports[-1],direction='entry')):
        with pytest.raises(ValueError):replace(r,physical_ports=(*r.physical_ports[:-1],port))
    with pytest.raises(TypeError):assess_er03_boundary(asdict(r.preview),expected_app_source_sha=C2A_APP_SOURCE_SHA)
    for sha in ('f'*40,'BAD',None):
        with pytest.raises(ValueError):assess_er03_boundary(r.preview,expected_app_source_sha=sha)


def test_cfw128_c2a_import_isolation_in_fresh_process_and_all_root_callers():
    import ast,subprocess,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    forbidden={'scipy','pumping_simulation','fluids_charts_module_v1_4_2','cement_charts_engine',
        'cement_chart_report','well_report','phase_10_procedure','centralizer_optimizer_engine',
        'centralizer_adapter','cfw128_hb03t_frozen','cfw128_hb_numeric','cfw128_hb_intake'}
    for path in root.glob('*.py'):
        tree=ast.parse(path.read_text());imports={n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        if path.name=='cfw128_er03_boundary.py':assert not imports & forbidden
        elif path.name != 'cfw128_er03_volume.py':assert 'cfw128_er03_boundary' not in imports
    script='import sys,cfw128_er03_boundary; assert not '+repr(forbidden)+' & set(sys.modules)'
    subprocess.run([sys.executable,'-B','-W','error','-c',script],cwd=root,check=True)


@pytest.mark.parametrize('filename',sorted(p.name for p in __import__('pathlib').Path(__file__).resolve().parents[1].glob('*.py')
                                         if p.name not in ('cfw128_er03_boundary.py','cfw128_er03_volume.py')))
def test_cfw128_c2a_unauthorized_root_import_mutation_is_rejected(filename,monkeypatch):
    from pathlib import Path
    target=Path(__file__).resolve().parents[1]/filename;read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+'\nimport cfw128_er03_boundary\n' if p==target else read(p,*a,**k))
    with pytest.raises(AssertionError):test_cfw128_c2a_import_isolation_in_fresh_process_and_all_root_callers()


# C2b is a new nominal geometric audit, not a pre-existing hydraulic bug fix.
C2B_APP_SOURCE_SHA = 'fd3e387a4a786dba197e89ad7fba293764b22951'


def cfw128_c2b_boundary(state=None, query_md=()):
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    from cfw128_er03_boundary import assess_er03_boundary
    state=cfw128_c1_uat19_state() if state is None else state
    source=snapshot_geometry(state,app_source_sha=C2B_APP_SOURCE_SHA,query_md=query_md)
    return assess_er03_boundary(prepare_er03_preview(source,expected_app_source_sha=C2B_APP_SOURCE_SHA),
                               expected_app_source_sha=C2B_APP_SOURCE_SHA)


def test_cfw128_c2b_uat19_nominal_sections_app_and_independent_si_oracle(tmp_path):
    import math,json
    from dataclasses import asdict
    from cement_chart_model import _capacity
    from cfw128_er03_volume import audit_geometric_capacity
    state=cfw128_c1_uat19_state();frame=state['hardware_table'];before=pickle.dumps(state)
    boundary=cfw128_c2b_boundary(state);held=pickle.dumps(boundary)
    r=audit_geometric_capacity(boundary,expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert r.status=='HOLD_GEOMETRIC_CAPACITY_ONLY'
    expected=[('injection',0.,2800.,0.,4.276,(7,),()),
              ('injection',2800.,3885.,0.,6.004,(6,),()),
              ('annular_return',2800.,3885.,7.,8.535,(6,),(2,))]
    assert [(s.leg,s.top_md,s.bottom_md,s.inner_diameter_in,s.outer_diameter_in,
             s.running_source_rows,s.wall_source_rows) for s in r.sections]==expected
    si_volumes=[]
    for s in r.sections:
        cap=_capacity(s.outer_diameter_in,s.inner_diameter_in)
        si=math.pi/4*((s.outer_diameter_in*.0254)**2-(s.inner_diameter_in*.0254)**2)/.15898730
        assert s.nominal_capacity_bbl_per_m==cap
        assert s.nominal_section_volume_bbl==cap*(s.bottom_md-s.top_md)
        # Independent SI barrel is rounded: observed relative discrepancy ~2.7822e-8.
        assert cap!=si and abs(cap-si)/si<3e-8
        assert (cap-si)/si==pytest.approx(2.7822059e-8,abs=2e-15)
        si_volumes.append(si*(s.bottom_md-s.top_md))
    assert [s.nominal_section_volume_bbl for s in r.sections]==pytest.approx(
        [163.16549284802392,124.65393655273077,82.46017806284104],abs=1e-10,rel=0)
    assert r.nominal_injection_volume_bbl==_capacity(4.276)*2800+_capacity(6.004)*1085
    assert r.nominal_annular_return_volume_bbl==_capacity(8.535,7.)*1085
    assert r.nominal_injection_volume_bbl==pytest.approx(287.8194294007547,abs=1e-10,rel=0)
    assert r.nominal_injection_volume_bbl!=r.nominal_annular_return_volume_bbl  # Distinct spaces, NOT a leak.
    assert r.boundary.preview.receiver.shoe_md==4860. and max(s.bottom_md for s in r.sections)==3885.
    assert r.boundary.preview.selected_host.source_rows==(2,) and r.boundary.physical_ports[-1].md_m==2800.
    assert r.boundary.return_outlet_pressure=='UNSPECIFIED' and r.boundary.mass_volume_conservation==r.boundary.qout_rate=='NOT_EVALUATED'
    assert 'Open Hole Size' not in frame.Description.values and frame is state['hardware_table']
    assert before==pickle.dumps(state) and held==pickle.dumps(boundary)
    (tmp_path/'uat19-capacity-audit.json').write_text(json.dumps({'audit':asdict(r),'independent_si_section_volumes_bbl':si_volumes,'relative_unit_constant_tolerance':3e-8},indent=2))


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2b_all_jobs_copy_nominal_source_slice_capacity_without_excess(job):
    from cement_chart_model import _capacity
    from cfw128_er03_volume import audit_geometric_capacity
    state=bug01_geometry_case(job);before=pickle.dumps(state);b=cfw128_c2b_boundary(state)
    r=audit_geometric_capacity(b,expected_app_source_sha=C2B_APP_SOURCE_SHA)
    p=b.preview;injection=tuple(s for s in r.sections if s.leg=='injection');returns=tuple(s for s in r.sections if s.leg=='annular_return')
    assert len(injection)==len(p.injection_sections) and len(returns)==len(p.return_sections)
    for out,src in zip(injection,p.injection_sections):
        assert (out.top_md,out.bottom_md,out.outer_diameter_in,out.running_source_rows)==(src.top_md,src.bottom_md,src.id_in,src.source_rows)
        assert out.inner_diameter_in==0. and out.nominal_capacity_bbl_per_m==_capacity(src.id_in)
    for out,src in zip(returns,p.return_sections):
        assert (out.top_md,out.bottom_md,out.outer_diameter_in,out.inner_diameter_in)==(src.top_md,src.bottom_md,src.wall.id_in,src.running.od_in)
        assert out.wall_source_rows==src.wall.source_rows and out.running_source_rows==src.running.source_rows
    assert returns[0].top_md==(p.string_top_md if p.kind=='tieback' else 0.)
    assert returns[-1].bottom_md==injection[-1].bottom_md==p.shoe_md
    if job in ('TIE BACK LNR 5"','TIE BACK LNR 4 1/2"'):assert returns[0].outer_diameter_in==6.094
    assert set(b.reason_codes)<=set(r.reason_codes) and pickle.dumps(state)==before
    # Chart-excess settings remain source metadata, never a multiplier on nominal geometry.
    altered=deepcopy(state);altered['placement_config']['chart_excess_mode']='apply'
    incomplete=audit_geometric_capacity(cfw128_c2b_boundary(altered),expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert incomplete.status=='SOURCE_NOT_READY' and incomplete.sections==()
    # Explicitly synthetic admission prerequisites; never field measurements.
    altered['placement_config'].update(excess_csg_oh_pct=12.5,excess_csg_csg_pct=25.)
    changed=audit_geometric_capacity(cfw128_c2b_boundary(altered),expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert changed.sections==r.sections and changed.nominal_injection_volume_bbl==r.nominal_injection_volume_bbl


@pytest.mark.parametrize('case',['a_zero','taper','piecewise_active','dp_taper','body_taper','directional'])
def test_cfw128_c2b_sectional_and_directional_capacity_preserves_md_provenance(case):
    from cfw128_er03_volume import audit_geometric_capacity
    state=synthetic_tieback(top=0.) if case=='a_zero' else r18c_tapered_state(100.) if case in ('taper','piecewise_active') else synthetic_tieback(top=400.)
    if case=='piecewise_active':
        state['hardware_table'].loc[state['hardware_table'].Description=='Tie Back Liner Lap','MD (m)']='0'
        state['hardware_table']=state['hardware_table'][state['hardware_table'].Description!='Drill Pipes'].reset_index(drop=True)
        state['placement_config']['host_row']=next(iter(hardware_choices(state['hardware_table'],{'Previous Casing'})))
    elif case=='dp_taper':
        t=state['hardware_table'];i=t.index[t.Description=='Drill Pipes'][0];t.at[i,'MD (m)']='200'
        extra=t.iloc[[i]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    elif case=='body_taper':
        t=state['hardware_table'];t.at[0,'MD (m)']='400-500';extra=t.iloc[[0]].copy()
        extra['MD (m)']='500-700';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t.iloc[:1],extra,t.iloc[1:]],ignore_index=True)
        state['placement_config']['target_row']=next(k for k,v in hardware_choices(state['hardware_table'],target_descriptions(state['job_type'])).items() if v['depth']==700.)
    elif case=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame(
        [[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    b=cfw128_c2b_boundary(state,(50.,) if case=='directional' else ());r=audit_geometric_capacity(b,expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert r.boundary==b and len(r.sections)==len(b.preview.injection_sections)+len(b.preview.return_sections)
    assert set(b.reason_codes)<=set(r.reason_codes)
    if case=='a_zero':
        assert 'HOLD_TIEBACK_POINT_A_ZERO_TYPED_INTERFACE' in r.reason_codes
        assert not any(s.description=='Drill Pipes' for s in b.preview.injection_sections)
    if case=='directional':
        pts={v.md:v.tvd for v in r.boundary.preview.trajectory}
        assert pts[50.]==pytest.approx(47.7464829275686,abs=1e-12)
        assert .5*pts[100.]==pytest.approx(41.3496671566,abs=1e-8)
        vertical=deepcopy(state);vertical['well_geometry']={'type':'Vertical','td_m':1200.}
        assert audit_geometric_capacity(cfw128_c2b_boundary(vertical),expected_app_source_sha=C2B_APP_SOURCE_SHA).sections==r.sections


@pytest.mark.parametrize('state',[{}, {'job_type':'CMT PLUG'}, {'job_type':'CMT SQUEEZE'}])
def test_cfw128_c2b_missing_or_nonapplicable_sources_cannot_mint_zero_inventory(state):
    from cfw128_er03_volume import audit_geometric_capacity
    r=audit_geometric_capacity(cfw128_c2b_boundary(state),expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert r.status=='SOURCE_NOT_READY' and r.sections==()
    assert r.nominal_injection_volume_bbl is r.nominal_annular_return_volume_bbl is None
    assert r.boundary.physical_ports==() and r.hydraulic_admissible is False


@pytest.mark.parametrize('fault',['port_top','port_bottom','port_direction','return_top','return_bottom','missing_dp',
    'clearance','rows','gap','overlap','duplicate','nan','bool','source_identity','job','mutable','flags','pressure','qout','instrument','unknown_mutable','sha'])
def test_cfw128_c2b_changed_c2a_or_source_never_yields_capacity(fault):
    from dataclasses import replace
    from cfw128_er03_volume import audit_geometric_capacity
    b=deepcopy(cfw128_c2b_boundary());p=b.preview
    if fault.startswith('port_'):
        kwargs={'port_top':{'md_m':0.},'port_bottom':{'md_m':4860.},'port_direction':{'direction':'entry'}}[fault]
        object.__setattr__(b,'physical_ports',(*b.physical_ports[:-1],replace(b.physical_ports[-1],**kwargs)))
    elif fault in ('return_top','return_bottom'):object.__setattr__(p,'return_top_md' if fault=='return_top' else 'return_bottom_md',0. if fault=='return_top' else 4860.)
    elif fault in ('clearance','rows','gap','overlap','nan','bool'):
        kwargs={'clearance':{'od_in':9.},'rows':{'source_rows':(999,)},'gap':{'top_md':2801.},
                'overlap':{'top_md':2799.},'nan':{'id_in':float('nan')},'bool':{'top_md':True}}[fault]
        object.__setattr__(p,'injection_sections',(p.injection_sections[0],replace(p.injection_sections[1],**kwargs)))
    elif fault=='missing_dp':object.__setattr__(p,'injection_sections',p.injection_sections[1:])
    elif fault=='duplicate':object.__setattr__(p,'injection_sections',(*p.injection_sections,p.injection_sections[-1]))
    elif fault=='source_identity':object.__setattr__(b,'projection_identity','a'*64)
    elif fault=='job':object.__setattr__(p,'job','LNR 7"')
    elif fault=='mutable':object.__setattr__(b,'physical_ports',list(b.physical_ports))
    elif fault=='flags':object.__setattr__(b,'hydraulic_admissible',True)
    elif fault=='pressure':object.__setattr__(b,'return_outlet_pressure',0.)
    elif fault=='qout':object.__setattr__(b,'qout_rate',1.)
    elif fault=='instrument':object.__setattr__(b,'instrument_provenance','CERTIFIED')
    elif fault=='unknown_mutable':object.__setattr__(b,'fluid_inventory_transport',[])
    else:object.__setattr__(b,'expected_app_source_sha','f'*40)
    before=pickle.dumps(b)
    with pytest.raises((ValueError,TypeError)):audit_geometric_capacity(b,expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert pickle.dumps(b)==before


def test_cfw128_c2b_receipt_clone_flags_totals_sections_and_pressure_fail_closed(monkeypatch):
    from dataclasses import replace,asdict,FrozenInstanceError
    from copy import copy
    from cfw128_er03_volume import audit_geometric_capacity,FrozenCapacityAudit,CapacitySection
    b=cfw128_c2b_boundary();r=audit_geometric_capacity(b,expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert copy(r)==deepcopy(r)==pickle.loads(pickle.dumps(r))==r
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        monkeypatch.setenv('CFW128_'+flag.upper(),'true');assert getattr(r,flag) is False
        with pytest.raises(FrozenInstanceError):setattr(r,flag,True)
        with pytest.raises(ValueError):replace(r,**{flag:True})
        data=asdict(r);data[flag]=True
        with pytest.raises(TypeError):FrozenCapacityAudit(**data)
    for kwargs in ({'nominal_injection_volume_bbl':0.},{'nominal_annular_return_volume_bbl':float('inf')},
                   {'nominal_injection_volume_bbl':True},{'sections':()}, {'projection_identity':'a'*64},
                   {'boundary_projection_identity':'b'*64},{'status':'READY'}):
        with pytest.raises(ValueError):replace(r,**kwargs)
    with pytest.raises(ValueError):replace(r,method_id='SI')
    with pytest.raises(TypeError):replace(r,pressure_psi=0.)
    with pytest.raises(TypeError):replace(r,sections=list(r.sections))
    class MutableString(str):
        pass
    disguised=tuple(MutableString(v) for v in r.reason_codes)
    disguised[0].mutable=[]
    with pytest.raises(TypeError):replace(r,reason_codes=disguised)
    for kwargs in ({'nominal_capacity_bbl_per_m':1.},{'top_md':True},{'inner_diameter_in':float('nan')},
                   {'nominal_section_volume_bbl':-1.},{'running_source_rows':(True,)}):
        with pytest.raises(ValueError):replace(r.sections[0],**kwargs)
    altered=replace(r.sections[0],running_source_rows=(999,))
    with pytest.raises(ValueError):replace(r,sections=(altered,*r.sections[1:]))
    with pytest.raises(TypeError):audit_geometric_capacity(asdict(b),expected_app_source_sha=C2B_APP_SOURCE_SHA)
    for sha in ('f'*40,'BAD',None):
        with pytest.raises(ValueError):audit_geometric_capacity(b,expected_app_source_sha=sha)


def test_cfw128_c2b_fresh_source_edits_change_identity_without_currentness_claim():
    from cfw128_er03_volume import audit_geometric_capacity
    state=cfw128_c1_uat19_state();b=cfw128_c2b_boundary(state)
    a=audit_geometric_capacity(b,expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert a==audit_geometric_capacity(b,expected_app_source_sha=C2B_APP_SOURCE_SHA)
    state['hardware_table'].at[2,'ID (in)']=8.534
    assert audit_geometric_capacity(b,expected_app_source_sha=C2B_APP_SOURCE_SHA)==a
    changed=audit_geometric_capacity(cfw128_c2b_boundary(state),expected_app_source_sha=C2B_APP_SOURCE_SHA)
    assert changed.projection_identity!=a.projection_identity and changed.sections!=a.sections
    assert changed.nominal_injection_volume_bbl==a.nominal_injection_volume_bbl
    assert changed.nominal_annular_return_volume_bbl!=a.nominal_annular_return_volume_bbl
    assert changed.enabled is changed.hydraulic_admissible is False
    assert 'CAPTURE_ONLY_REQUIRES_FRESH_APP_RESNAPSHOT' in changed.reason_codes


def test_cfw128_c2b_import_isolation_in_clean_process_and_all_root_callers():
    import ast,subprocess,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    forbidden={'scipy','cfw128_hb03t_frozen','cfw128_hb_numeric','cfw128_hb_intake','pumping_simulation',
        'fluids_charts_module_v1_4_2','cement_charts_engine','centralizer_optimizer_engine','centralizer_adapter',
        'streamlit','well_report','phase_10_procedure','cement_chart_report'}
    for path in root.glob('*.py'):
        tree=ast.parse(path.read_text());imports={n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        if path.name=='cfw128_er03_volume.py':assert not imports & forbidden
        else:assert 'cfw128_er03_volume' not in imports
    script='import sys,cfw128_er03_volume; assert not '+repr(forbidden)+' & set(sys.modules); assert not any(n.startswith("streamlit.runtime") for n in sys.modules)'
    subprocess.run([sys.executable,'-B','-W','error','-c',script],cwd=root,check=True)


@pytest.mark.parametrize('filename',sorted(p.name for p in __import__('pathlib').Path(__file__).resolve().parents[1].glob('*.py')
                                         if p.name!='cfw128_er03_volume.py'))
def test_cfw128_c2b_unauthorized_root_import_mutation_remains_rejected(filename,monkeypatch):
    from pathlib import Path
    target=Path(__file__).resolve().parents[1]/filename;read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+'\nimport cfw128_er03_volume\n' if p==target else read(p,*a,**k))
    with pytest.raises(AssertionError):test_cfw128_c2b_import_isolation_in_clean_process_and_all_root_callers()


C2D1_APP_SOURCE_SHA = '9efd9d56429b5346c08a73f125686b7efbe8201f'


def cfw128_c2d1_inputs(state=None,query_md=()):
    from cfw128_adapter import snapshot_geometry
    from cfw128_er03_contract import prepare_er03_preview
    from cfw128_er03_boundary import assess_er03_boundary
    from cfw128_er03_volume import audit_geometric_capacity
    state=cfw128_c1_uat19_state() if state is None else state
    s=snapshot_geometry(state,app_source_sha=C2D1_APP_SOURCE_SHA,query_md=query_md)
    p=prepare_er03_preview(s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    b=assess_er03_boundary(p,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    return s,audit_geometric_capacity(b,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


def test_cfw128_c2d1_uat19_surface_corridor_and_post_pull_are_nominal_only():
    from cfw128_c2d_geometry_view import build_geometry_view
    from cement_chart_model import _capacity
    state=cfw128_c1_uat19_state();before=pickle.dumps(state);s,a=cfw128_c2d1_inputs(state);proof=pickle.dumps((s,a))
    r=build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.currentness=='NOT_CURRENTNESS_PROOF' and r.corridor_contract=='OWNER_SURFACE_CONNECTED_2026_11_11'
    assert r.nominal_injection_bbl==a.nominal_injection_volume_bbl==pytest.approx(287.819429400755,abs=1e-10)
    total=lambda parts:sum(v.nominal_volume_bbl for v in parts)
    assert total(r.lower_annulus)==a.nominal_annular_return_volume_bbl==pytest.approx(82.460178062841,abs=1e-10)
    assert total(r.upper_pumping_annulus)==_capacity(8.535,5.)*2800==pytest.approx(426.973186160669,abs=1e-10)
    assert total(r.upper_post_pull_bore)==_capacity(8.535)*2800==pytest.approx(650.069776414482,abs=1e-10)
    assert [(v.top_md,v.bottom_md,v.inner_diameter_in,v.outer_diameter_in) for v in r.pumping_return]==[(0.,2800.,5.,8.535),(2800.,3885.,7.,8.535)]
    assert [(v.top_md,v.bottom_md,v.inner_diameter_in,v.outer_diameter_in) for v in r.post_pull_return]==[(0.,2800.,0.,8.535),(2800.,3885.,7.,8.535)]
    assert r.upper_post_pull_bore[0].running_source_rows==() and r.upper_post_pull_bore[0].wall_source_rows==(2,)
    assert a.boundary.physical_ports[-1].md_m==2800.  # Historical scope preserved, not the new discharge.
    assert a.boundary.preview.receiver.shoe_md==4860. and all(v.bottom_md<=3885. for v in r.injection+r.pumping_return)
    assert r.hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc=='NOT_EVALUATED'
    assert pickle.dumps((s,a))==proof and pickle.dumps(state)==before


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2d1_all_jobs_partition_once_without_new_hardware(job):
    from cfw128_c2d_geometry_view import build_geometry_view
    state=bug01_geometry_case(job);before=pickle.dumps(state);s,a=cfw128_c2d1_inputs(state)
    r=build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    volume=lambda parts:sum(v.nominal_volume_bbl for v in parts)
    assert r.nominal_injection_bbl==a.nominal_injection_volume_bbl
    assert r.pumping_return[0].top_md==0. and r.pumping_return[-1].bottom_md==s.shoe_md
    assert all(x.bottom_md==y.top_md for x,y in zip(r.pumping_return,r.pumping_return[1:]))
    if s.kind=='casing':
        assert r.upper_pumping_annulus==r.upper_post_pull_bore==() and r.post_pull_return is None
        assert r.nominal_pumping_return_bbl==a.nominal_annular_return_volume_bbl
    elif s.kind=='liner':
        assert r.nominal_pumping_return_bbl==a.nominal_annular_return_volume_bbl
        assert r.lower_annulus[0].top_md==s.string_top_md and r.upper_pumping_annulus[-1].bottom_md==s.string_top_md
    else:
        assert volume(r.lower_annulus)==a.nominal_annular_return_volume_bbl
        assert r.nominal_pumping_return_bbl==volume(r.upper_pumping_annulus)+volume(r.lower_annulus)
    if job in ('LNR 5"','TIE BACK LNR 5"','TIE BACK LNR 4 1/2"'):assert len({v.outer_diameter_in for v in r.upper_pumping_annulus})>1
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('case',['a_zero','taper','dp_taper','body_taper','directional'])
def test_cfw128_c2d1_sectional_upper_walls_and_zero_top_remain_measured(case):
    from cfw128_c2d_geometry_view import build_geometry_view
    state=synthetic_tieback(top=0.) if case=='a_zero' else r18c_tapered_state(100.) if case=='taper' else synthetic_tieback(top=400.)
    if case=='dp_taper':
        t=state['hardware_table'];i=t.index[t.Description=='Drill Pipes'][0];t.at[i,'MD (m)']='200'
        extra=t.iloc[[i]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    elif case=='body_taper':
        t=state['hardware_table'];t.at[0,'MD (m)']='400-500';extra=t.iloc[[0]].copy();extra['MD (m)']='500-700';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t.iloc[:1],extra,t.iloc[1:]],ignore_index=True)
        state['placement_config']['target_row']=next(k for k,v in hardware_choices(state['hardware_table'],target_descriptions(state['job_type'])).items() if v['depth']==700.)
    elif case=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    s,a=cfw128_c2d1_inputs(state,(50.,) if case=='directional' else ());r=build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    if case=='directional':assert next(v.tvd for v in s.trajectory if v.md==50.)==pytest.approx(47.7464829275686,abs=1e-12)
    assert r.captured_geometry.survey==s.survey and r.captured_geometry.trajectory==s.trajectory
    if case=='a_zero':assert r.upper_pumping_annulus==r.upper_post_pull_bore==() and r.post_pull_return==r.lower_annulus
    else:assert sum(v.bottom_md-v.top_md for v in r.upper_pumping_annulus)==s.string_top_md
    if case=='taper':assert len(next(v for v in s.installed_strings if v.description=='Previous Tie Back Liner Shoe').sections)==2


@pytest.mark.parametrize('fault',['top','shoe','gap','rows','diameter','host','receiver','identity','flags','mutable','port','proof_total','old_source'])
def test_cfw128_c2d1_mutated_capture_or_historical_proof_fails_closed(fault):
    from dataclasses import replace
    from cfw128_c2d_geometry_view import build_geometry_view
    s,a=deepcopy(cfw128_c2d1_inputs())
    if fault=='top':object.__setattr__(s,'string_top_md',2799.)
    elif fault=='shoe':object.__setattr__(s,'shoe_md',4860.)
    elif fault in ('gap','rows','diameter'):
        kwargs={'gap':{'top_md':2801.},'rows':{'source_rows':(999,)},'diameter':{'od_in':9.}}[fault]
        object.__setattr__(s,'active_sections',(s.active_sections[0],replace(s.active_sections[1],**kwargs)))
    elif fault=='host':object.__setattr__(s,'selected_host',None)
    elif fault=='receiver':object.__setattr__(s,'receiver',None)
    elif fault=='identity':object.__setattr__(a,'projection_identity','f'*64)
    elif fault=='flags':object.__setattr__(a,'enabled',True)
    elif fault=='mutable':object.__setattr__(s,'active_sections',list(s.active_sections))
    elif fault=='port':object.__setattr__(a.boundary,'physical_ports',(*a.boundary.physical_ports[:-1],replace(a.boundary.physical_ports[-1],md_m=0.)))
    elif fault=='proof_total':object.__setattr__(a,'nominal_injection_volume_bbl',0.)
    else:
        state=cfw128_c1_uat19_state();state['hardware_table'].at[2,'ID (in)']=8.534;s,_=cfw128_c2d1_inputs(state)
    with pytest.raises((ValueError,TypeError)):build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


def test_cfw128_c2d1_immutability_and_no_currentness_or_pressure_promotion():
    from dataclasses import replace,FrozenInstanceError,asdict
    from cfw128_c2d_geometry_view import build_geometry_view
    s,a=cfw128_c2d1_inputs();r=build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert deepcopy(r)==pickle.loads(pickle.dumps(r))==r
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(r,flag) is False
        with pytest.raises(FrozenInstanceError):setattr(r,flag,True)
        with pytest.raises(ValueError):replace(r,**{flag:True})
    with pytest.raises(ValueError):replace(r,currentness='CURRENT')
    with pytest.raises(ValueError):replace(r,lower_annulus=())
    with pytest.raises(TypeError):build_geometry_view(asdict(s),a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    with pytest.raises(ValueError):build_geometry_view(s,a,expected_app_source_sha='f'*40)
    with pytest.raises(TypeError):build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA,current=True)
    state=cfw128_c1_uat19_state();state['hardware_table'].at[2,'ID (in)']=8.534
    assert build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    fresh,proof=cfw128_c2d1_inputs(state)
    assert build_geometry_view(fresh,proof,expected_app_source_sha=C2D1_APP_SOURCE_SHA).projection_identity!=r.projection_identity


def test_cfw128_c2d1_import_isolation_no_callbacks_or_runtime_escape():
    import ast,sys,subprocess
    from pathlib import Path
    root=Path(__file__).resolve().parents[1];path=root/'cfw128_c2d_geometry_view.py';tree=ast.parse(path.read_text())
    imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
    assert imports<={'dataclasses','math','re','typing','cement_chart_model','project_state'}
    assert not {'eval','exec','__import__','import_module'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
    for other in root.glob('*.py'):
        if other==path:continue
        t=ast.parse(other.read_text());names={n.module for n in ast.walk(t) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names}
        assert 'cfw128_c2d_geometry_view' not in names
    forbidden={'cfw128_adapter','cfw128_er03_contract','cfw128_er03_boundary','cfw128_er03_volume','cfw128_hb_intake','cfw128_hb_numeric','cfw128_hb03t_frozen','scipy','streamlit','pumping_simulation','fluids_charts_module_v1_4_2','cement_charts_engine','centralizer_optimizer_engine','well_report'}
    script='import sys,cfw128_c2d_geometry_view; assert not '+repr(forbidden)+' & set(sys.modules)'
    subprocess.run([sys.executable,'-B','-W','error','-c',script],cwd=root,check=True)


@pytest.mark.parametrize('state',[{}, {'job_type':'CMT PLUG'}])
def test_cfw128_c2d1_unavailable_sources_have_no_nominal_payload(state):
    from cfw128_c2d_geometry_view import build_geometry_view
    s,a=cfw128_c2d1_inputs(state);r=build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status=='SOURCE_NOT_READY' and r.injection==r.pumping_return==()
    assert r.post_pull_return is r.nominal_injection_bbl is r.nominal_pumping_return_bbl is None


@pytest.mark.parametrize('filename',sorted(p.name for p in __import__('pathlib').Path(__file__).resolve().parents[1].glob('*.py')
                                         if p.name!='cfw128_c2d_geometry_view.py'))
def test_cfw128_c2d1_other_roots_reject_import_mutation(filename,monkeypatch):
    from pathlib import Path
    target=Path(__file__).resolve().parents[1]/filename;read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+'\nimport cfw128_c2d_geometry_view\n' if p==target else read(p,*a,**k))
    with pytest.raises(AssertionError):test_cfw128_c2d1_import_isolation_no_callbacks_or_runtime_escape()


# C2e-1 additive disabled tracking checks; all earlier tests remain byte-exact.
def cfw128_c2e_view(state=None, query_md=()):
    from cfw128_c2d_geometry_view import build_geometry_view
    state=cfw128_c1_uat19_state() if state is None else state
    s,a=cfw128_c2d1_inputs(state,query_md)
    return build_geometry_view(s,a,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


def cfw128_c2e_fluids(state,names=('Main','Displacement Fluid'),volume=2000.):
    state['mud_density']=80.;state['mud_type']='OBM'
    state['fluids_config']={'active':list(reversed(names)),'params':{
        n:{'volume':volume,'density':52. if n=='Diesel' else 110.} for n in names}}
    return state


def test_cfw128_c2e_new_disabled_interface_requirement():
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state());view=cfw128_c2e_view(state)
    r=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status=='DISABLED_VOLUME_TRACKING_PREVIEW' and r.currentness=='NOT_CURRENTNESS_PROOF'
    assert r.hydraulics=='HYDRAULICS_NOT_EVALUATED' and r.toc=='TOC_NOT_EVALUATED'
    assert all(getattr(r,n) is False for n in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
    assert {v.fluid for v in r.occupancy}=={'Mud'}


@pytest.mark.parametrize('milestone',['zero','first','shoe','lap','surface','over','end'])
def test_cfw128_c2e_uat19_fronts_and_per_stage_conservation(milestone):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from cement_chart_model import _capacity
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state());view=cfw128_c2e_view(state)
    injection=view.nominal_injection_bbl;lower=sum(s.nominal_volume_bbl for s in view.lower_annulus)
    upper=sum(s.nominal_volume_bbl for s in view.upper_pumping_annulus);total=injection+lower+upper
    V={'zero':0.,'first':1.,'shoe':injection,'lap':injection+lower,'surface':total,'over':total+10.,'end':4000.}[milestone]
    before=pickle.dumps((state,view));r=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=V)
    assert injection==pytest.approx(287.819429400755,abs=1e-10)
    assert lower==pytest.approx(82.460178062841,abs=1e-10) and upper==pytest.approx(426.973186160669,abs=1e-10)
    assert r.total_nominal_capacity_bbl==pytest.approx(total)
    assert [(p.domain,p.inlet_md,p.outlet_md) for p in r.path]==[
        ('injection',0.,2800.),('injection',2800.,3885.),('lower_annulus',3885.,2800.),('upper_pumping_annulus',2800.,0.)]
    assert not any(p.domain=='upper_post_pull_bore' or max(p.inlet_md,p.outlet_md)>3885. for p in r.path)
    assert sum(o.volume_bbl for o in r.occupancy)==pytest.approx(total,abs=1e-10)
    for ledger in r.ledgers:
        assert ledger.entered_bbl==pytest.approx(ledger.in_path_bbl+ledger.ideal_returned_bbl)
        assert ledger.in_path_bbl==pytest.approx(sum(o.volume_bbl for o in r.occupancy if o.fluid==ledger.fluid))
    assert total==pytest.approx(r.mud_remaining_bbl+r.mud_displaced_bbl)
    assert r.mud_displaced_bbl==pytest.approx(min(V,total))
    if milestone=='first':assert r.mud_displaced_bbl==1. and r.ledgers[0].ideal_returned_bbl==0.
    if milestone=='over':assert r.ledgers[0].ideal_returned_bbl==pytest.approx(10.)
    if milestone in ('shoe','lap'):
        front=next(o for o in reversed(r.occupancy) if o.fluid=='Main')
        assert front.outlet_md==pytest.approx(3885. if milestone=='shoe' else 2800.)
    assert pickle.dumps((state,view))==before
    assert r==preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=V)


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2e_jobs_sections_and_equal_density_identity(job):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from materials_db import HYDRAULIC_EXECUTION_ORDER
    state=cfw128_c2e_fluids(bug01_geometry_case(job),HYDRAULIC_EXECUTION_ORDER,100.)
    view=cfw128_c2e_view(state);r=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=500.)
    assert tuple(s.name for s in r.stages)==HYDRAULIC_EXECUTION_ORDER
    assert 'Spacer Behind' in tuple(s.name for s in r.stages)
    assert len({s.name for s in r.stages})==len(r.stages)
    assert r.stages[-1].name=='Displacement Fluid' and r.stages[-1].density_pcf==r.initial_mud_density_pcf
    assert sum(o.volume_bbl for o in r.occupancy)==pytest.approx(r.total_nominal_capacity_bbl)
    assert all(a.outlet_md==b.inlet_md for a,b in zip(r.path,r.path[1:]))
    assert r.path[0].inlet_md==r.path[-1].outlet_md==0.
    assert sum(p.end_bbl-p.start_bbl for p in r.path)==pytest.approx(view.nominal_injection_bbl+view.nominal_pumping_return_bbl)


@pytest.mark.parametrize('case',['zero','taper','directional','dp_sections'])
def test_cfw128_c2e_measured_special_sections_and_trajectory(case):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=synthetic_tieback(top=0. if case=='zero' else 400.) if case!='taper' else r18c_tapered_state(100.)
    if case=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    if case=='dp_sections':
        t=state['hardware_table'];i=t.index[t.Description=='Drill Pipes'][0];t.at[i,'MD (m)']='200'
        extra=t.iloc[[i]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    cfw128_c2e_fluids(state);view=cfw128_c2e_view(state,(50.,) if case=='directional' else ())
    r=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=20.)
    if case=='zero':assert not any(p.domain=='upper_pumping_annulus' for p in r.path)
    if case=='directional':assert dict(r.trajectory)[50.]==pytest.approx(47.7464829275686,abs=1e-12)
    if case=='taper':assert len(next(s for s in view.captured_geometry.installed_strings if s.description=='Previous Tie Back Liner Shoe').sections)==2
    if case=='dp_sections':assert [(p.inlet_md,p.outlet_md) for p in r.path[:2]]==[(0.,200.),(200.,400.)]


@pytest.mark.parametrize('fault',['duplicate','unknown','diesel_wbm','missing','invalid_canonical','bool','fraction_text','nan','negative','density','mud','job','too_far','overflow','swallowed'])
def test_cfw128_c2e_invalid_fluid_sources_fail_closed(fault):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state());view=cfw128_c2e_view(state);V=0.
    if fault=='duplicate':state['fluids_config']['active'].append('Main')
    elif fault=='unknown':state['fluids_config']['active'].append('Mud')
    elif fault=='diesel_wbm':state['mud_type']='WBM';state['fluids_config']['active'].append('Diesel')
    elif fault=='missing':del state['fluids_config']['params']['Main']
    elif fault=='invalid_canonical':state['fluid_data']={'Main':{'volume':20.,'density':110.}};state['fluids_config']['params']['Main']=None
    elif fault in ('bool','fraction_text','nan','negative'):state['fluids_config']['params']['Main']['volume']={'bool':True,'fraction_text':'1/2','nan':float('nan'),'negative':-1.}[fault]
    elif fault=='density':state['fluids_config']['params']['Main']['density']=False
    elif fault=='mud':state['mud_density']=float('inf')
    elif fault=='job':state['job_type']='CSG 20"'
    elif fault=='too_far':V=4001.
    elif fault=='overflow':state['fluids_config']['params']['Main']['volume']=1e308;state['fluids_config']['params']['Displacement Fluid']['volume']=1e308
    elif fault=='swallowed':state['fluids_config']['params']['Main']['volume']=1e20;state['fluids_config']['params']['Displacement Fluid']['volume']=1.
    before=pickle.dumps(state)
    with pytest.raises((ValueError,TypeError)):preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=V)
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('fault',['sha','identity','projection','rows','diameter','gap','flags','source_pair','postpull','mutable'])
def test_cfw128_c2e_changed_capture_and_forged_gate_rejected(fault):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state());view=deepcopy(cfw128_c2e_view(state));sha=C2D1_APP_SOURCE_SHA
    if fault=='sha':sha='0'*40
    elif fault=='identity':object.__setattr__(view,'source_identity','0'*64)
    elif fault=='projection':object.__setattr__(view,'projection_identity','0'*64)
    elif fault=='rows':object.__setattr__(view.injection[0],'running_source_rows',(999,))
    elif fault=='diameter':object.__setattr__(view.lower_annulus[0],'outer_diameter_in',100.)
    elif fault=='gap':object.__setattr__(view.injection[0],'bottom_md',2799.)
    elif fault=='flags':object.__setattr__(view,'enabled',True)
    elif fault=='source_pair':object.__setattr__(view.captured_geometry,'host_token','unrelated')
    elif fault=='postpull':object.__setattr__(view,'lower_annulus',view.upper_post_pull_bore)
    elif fault=='mutable':object.__setattr__(view,'injection',list(view.injection))
    with pytest.raises((ValueError,TypeError)):preview_fluid_tracking(view,state,expected_app_source_sha=sha)


def test_cfw128_c2e_mutation_currentness_legacy_fallback_and_immutable_receipt():
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from dataclasses import replace,FrozenInstanceError
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state());view=cfw128_c2e_view(state)
    kwargs={'expected_app_source_sha':C2D1_APP_SOURCE_SHA,'cumulative_injected_bbl':10.}
    r=preview_fluid_tracking(view,state,**kwargs)
    state['hardware_table'].at[2,'ID (in)']=8.534
    assert preview_fluid_tracking(view,state,**kwargs)==r  # Replay cannot detect unseen Hardware; NEVER currentness proof.
    assert preview_fluid_tracking(cfw128_c2e_view(state),state,**kwargs).source_identity!=r.source_identity
    state['fluids_config']['params']['Main']['volume']=2001.
    assert preview_fluid_tracking(view,state,**kwargs).source_identity!=r.source_identity
    state['fluid_data']={'Main':state['fluids_config']['params'].pop('Main')}
    legacy=preview_fluid_tracking(view,state,**kwargs)
    assert next(s for s in legacy.stages if s.name=='Main').source=='fluid_data'
    assert pickle.loads(pickle.dumps(r))==r
    with pytest.raises(FrozenInstanceError):r.enabled=True
    with pytest.raises(ValueError):replace(r,enabled=True)
    with pytest.raises(TypeError):r.stages[0]=r.stages[0]


def test_cfw128_c2e_no_selection_and_resolution_limits():
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state(),());view=cfw128_c2e_view(state)
    r=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert not r.stages and r.mud_displaced_bbl==0. and all(o.fluid=='Mud' for o in r.occupancy)
    cfw128_c2e_fluids(state,('Main',),1e-300)
    tiny=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=1e-300)
    assert tiny.ledgers[0].entered_bbl==tiny.ledgers[0].in_path_bbl==1e-300
    assert tiny.occupancy[0].inlet_md<tiny.occupancy[0].outlet_md


def test_cfw128_c2e_import_isolation_and_mutation_negative(monkeypatch):
    import ast
    from pathlib import Path
    path=Path('cfw128_c2e_volume_tracking.py');tree=ast.parse(path.read_text())
    imports={n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module}
    imports.update(a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names)
    assert not any(n.startswith('cfw128') or n in ('scipy','pumping_simulation','fluids_charts_module_v1_4_2','streamlit','well_report') for n in imports)
    for root in Path('.').glob('*.py'):
        if root==path:continue
        t=ast.parse(root.read_text(encoding='utf-8-sig'))
        assert not any(isinstance(n,ast.ImportFrom) and n.module==path.stem or isinstance(n,ast.Import) and any(a.name==path.stem for a in n.names) for n in ast.walk(t))
    original=Path.read_text
    with monkeypatch.context() as m:
        m.setattr(Path,'read_text',lambda p,*a,**k:original(p,*a,**k)+'\nimport cfw128_adapter\n' if p==path else original(p,*a,**k))
        with pytest.raises(AssertionError):test_cfw128_c2e_import_isolation_and_mutation_negative_no_recursion(path)


def test_cfw128_c2e_import_isolation_and_mutation_negative_no_recursion(path=None):
    import ast
    from pathlib import Path
    p=Path('cfw128_c2e_volume_tracking.py') if path is None else path
    tree=ast.parse(p.read_text())
    assert not any(isinstance(n,ast.Import) and any(a.name.startswith('cfw128') for a in n.names) or isinstance(n,ast.ImportFrom) and (n.module or '').startswith('cfw128') for n in ast.walk(tree))


@pytest.mark.parametrize('main_volume',[20.,30000.])
def test_cfw128_c2e_equivalent_supported_round9c_accounting(main_volume):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from centralizer_adapter import build_fluid_snapshot
    state=cfw128_c2e_fluids(synthetic_tieback(top=400.))
    state['fluids_config']['params']['Main']['volume']=main_volume
    state['fluids_config']['params']['Displacement Fluid']['volume']=10.
    before=pickle.dumps(state);view=cfw128_c2e_view(state)
    r=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=main_volume+10.)
    old=build_fluid_snapshot(state)
    assert r.total_nominal_capacity_bbl==pytest.approx(old['capacity_bbl']['total'])
    for v in r.ledgers:
        assert v.entered_bbl==pytest.approx(old['per_fluid'][v.fluid]['entered_bbl'])
        assert v.in_path_bbl==pytest.approx(old['per_fluid'][v.fluid]['in_path_bbl'])
        assert v.ideal_returned_bbl==pytest.approx(old['per_fluid'][v.fluid]['returned_bbl'])
    assert pickle.dumps(state)==before


def test_cfw128_c2e_clean_process_has_no_engine_capture_or_ui_imports():
    import subprocess,sys
    forbidden={'cfw128_adapter','cfw128_er03_contract','cfw128_er03_boundary','cfw128_er03_volume',
               'cfw128_c2d_geometry_view','cfw128_hb_intake','cfw128_hb_numeric','cfw128_hb03t_frozen',
               'scipy','pumping_simulation','fluids_charts_module_v1_4_2','streamlit','well_report',
               'centralizer_optimizer_engine','cement_charts_engine'}
    script='import sys,cfw128_c2e_volume_tracking; assert not '+repr(forbidden)+' & set(sys.modules)'
    subprocess.run([sys.executable,'-B','-W','error','-c',script],check=True)


@pytest.mark.parametrize('kind',['request','stage'])
def test_cfw128_c2e_nonrepresentable_integer_volume_is_not_coerced(kind):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state(),volume=1e20);view=cfw128_c2e_view(state)
    if kind=='stage':state['fluids_config']['params']['Main']['volume']=10**20+1
    with pytest.raises(ValueError,match='Nonrepresentable'):
        preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,cumulative_injected_bbl=10**20+1 if kind=='request' else 0.)


def test_cfw128_c2e_fractional_stage_end_is_exact_without_rounding_source():
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state());state['fluids_config']['params']['Main']['volume']=.1
    state['fluids_config']['params']['Displacement Fluid']['volume']=.2;view=cfw128_c2e_view(state)
    r=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=2)
    assert [v.entered_bbl for v in r.ledgers]==[.1,.2]
    assert [v.in_path_bbl for v in r.ledgers]==[.1,.2]
    for bad in (True,-1,3):
        with pytest.raises(ValueError):preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=bad)
    with pytest.raises(ValueError):preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=1,cumulative_injected_bbl=.01)


# C2e-2: additive, disabled pump-end assessment; prior bytes stay unchanged.
def cfw128_c2e2_capture(state=None, volumes=None, stage_end=None, injected=None, query_md=()):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c1_uat19_state() if state is None else state
    volumes={'Main':40.} if volumes is None else dict(volumes)
    view=cfw128_c2e_view(state,query_md)
    if 'Displacement Fluid' not in volumes:volumes['Displacement Fluid']=view.nominal_injection_bbl
    cfw128_c2e_fluids(state,tuple(volumes))
    for name,volume in volumes.items():state['fluids_config']['params'][name]['volume']=volume
    kwargs={'stage_end':len(volumes) if stage_end is None else stage_end} if injected is None else {'cumulative_injected_bbl':injected}
    track=preview_fluid_tracking(view,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,**kwargs)
    return view,track


def test_cfw128_c2e2_new_interface_is_a_disabled_pumping_state_candidate_only():
    from cfw128_c2e2_cement_placement import assess_cement_placement
    view,track=cfw128_c2e2_capture()
    r=assess_cement_placement(track,view,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status=='DISABLED_PUMP_END_PLACEMENT_PREVIEW'
    assert r.currentness=='NOT_CURRENTNESS_PROOF' and r.hydraulics=='HYDRAULICS_NOT_EVALUATED'
    assert r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'
    assert r.post_pull_reason=='HOLD_POST_PULL_REMAP_UNDEFINED'
    assert r.pumping_state_toc_candidate_md is not None


def cfw128_c2e2_rebind(track):
    from dataclasses import fields
    from project_state import fingerprint
    plain=lambda rows:tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)
    object.__setattr__(track,'projection_identity',fingerprint(['cfw128-c2e-volume/1',track.source_identity,track.cumulative_injected_bbl,
        plain(track.occupancy),plain(track.ledgers),track.mud_remaining_bbl,track.mud_displaced_bbl]))
    return track


@pytest.mark.parametrize('amount,position',[(40.,'below'),(200.,'above'),(512.,'surface')])
def test_cfw128_c2e2_uat19_actual_pumping_toc_below_above_lap_and_surface(amount,position):
    from cfw128_c2e2_cement_placement import assess_cement_placement
    from cement_chart_model import _capacity
    state=cfw128_c1_uat19_state();view=cfw128_c2e_view(state)
    volumes={'Main':amount}
    # Synthetic, exactly representable source schedule, not a field recommendation.
    if position=='surface':volumes['Pre Flush']=512.-view.nominal_injection_bbl
    g,t=cfw128_c2e2_capture(state,volumes);before=pickle.dumps((g,t))
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert g.nominal_injection_bbl==pytest.approx(287.819429400755,abs=1e-10)
    assert sum(p.nominal_volume_bbl for p in g.lower_annulus)==pytest.approx(82.460178062841,abs=1e-10)
    assert sum(p.nominal_volume_bbl for p in g.upper_pumping_annulus)==pytest.approx(426.973186160669,abs=1e-10)
    assert sum(p.nominal_volume_bbl for p in g.upper_post_pull_bore)==pytest.approx(650.069776414482,abs=1e-10)
    assert not r.reason_codes and r.pumping_state_toc_candidate_md is not None
    lower=sum(p.nominal_volume_bbl for p in g.lower_annulus)
    expected=3885.-amount/_capacity(8.535,7.) if position=='below' else 2800.-(amount-lower)/_capacity(8.535,5.) if position=='above' else 0.
    assert r.pumping_state_toc_candidate_md==pytest.approx(expected,abs=1e-9)
    assert all(v.bottom_md<=3885. for v in r.annular_intervals)
    assert r.surface_cement_return_present is (position=='surface')
    assert r.post_pull_reason=='HOLD_POST_PULL_REMAP_UNDEFINED'
    assert pickle.dumps((g,t))==before


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2e2_all_jobs_preserve_stage_ledgers_and_geometry_roles(job):
    from cfw128_c2e2_cement_placement import assess_cement_placement
    g,t=cfw128_c2e2_capture(bug01_geometry_case(job),{'Main':20.,'Lead':20.,'Tail':20.})
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert tuple(v.fluid for v in r.stages)==('Main','Lead','Tail')
    for v in r.stages:
        source=next(x for x in t.ledgers if x.fluid==v.fluid)
        assert v.entered_bbl==source.entered_bbl and v.ideal_surface_returned_bbl==source.ideal_returned_bbl
        assert v.retained_injection_bbl+v.retained_lower_annulus_bbl+v.retained_upper_annulus_bbl==pytest.approx(source.in_path_bbl)
    assert r.post_pull_reason==('NOT_APPLICABLE' if g.captured_geometry.kind=='casing' else 'HOLD_POST_PULL_REMAP_UNDEFINED')
    # Conservative precision HOLD is explicit, never a rounded TOC acceptance.
    if r.pumping_state_toc_candidate_md is None:assert r.reason_codes==('HOLD_TERMINAL_VOLUME_PRECISION_UNPROVEN',) or 'HOLD_VOLUME_RECONCILIATION_PRECISION' in r.reason_codes
    else:assert r.pumping_state_toc_candidate_md==min(v.top_md for v in r.annular_intervals)
    assert {v.fluid for v in r.annular_intervals}=={'Main','Lead','Tail'}


@pytest.mark.parametrize('case',['partial','inside','none','scavenger','spacer_behind','past_shoe','fractional_terminal'])
def test_cfw128_c2e2_unproved_or_ambiguous_toc_is_held(case):
    from cfw128_c2e2_cement_placement import assess_cement_placement
    state=cfw128_c1_uat19_state()
    if case=='partial':g,t=cfw128_c2e2_capture(state,stage_end=1)
    elif case=='inside':g,t=cfw128_c2e2_capture(state,{'Main':40.,'Displacement Fluid':10.})
    elif case=='none':g,t=cfw128_c2e2_capture(state,{'Displacement Fluid':20.})
    elif case=='scavenger':g,t=cfw128_c2e2_capture(state,{'Scavenger':40.})
    elif case=='spacer_behind':g,t=cfw128_c2e2_capture(state,{'Main':40.,'Spacer Behind':10.})
    elif case=='past_shoe':
        v=cfw128_c2e_view(state);g,t=cfw128_c2e2_capture(state,{'Main':40.,'Displacement Fluid':v.nominal_injection_bbl+20.})
    else:g,t=cfw128_c2e2_capture(state,{'Main':.1,'Displacement Fluid':.2})
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.pumping_state_toc_candidate_md is None
    expected={'partial':'HOLD_SCHEDULE_INCOMPLETE','inside':'HOLD_CEMENT_REMAINS_IN_INJECTION','none':'HOLD_NO_PLACED_CEMENT',
              'scavenger':'HOLD_NO_PLACED_CEMENT','spacer_behind':'HOLD_CEMENT_NOT_ANCHORED_AT_SHOE','past_shoe':'HOLD_CEMENT_NOT_ANCHORED_AT_SHOE','fractional_terminal':'HOLD_TERMINAL_VOLUME_PRECISION_UNPROVEN'}[case]
    assert expected in r.reason_codes
    if case=='scavenger':assert not r.stages and not r.annular_intervals and any(x[0]=='Scavenger' for x in r.other_fluid_occupancy)


@pytest.mark.parametrize('case',['zero_top','previous_taper','directional','sectional_dp'])
def test_cfw128_c2e2_measured_special_cases_remain_captured(case):
    from cfw128_c2e2_cement_placement import assess_cement_placement
    state=synthetic_tieback(top=0. if case=='zero_top' else 400.) if case!='previous_taper' else r18c_tapered_state(100.)
    if case=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    if case=='sectional_dp':
        t=state['hardware_table'];i=t.index[t.Description=='Drill Pipes'][0];t.at[i,'MD (m)']='200'
        extra=t.iloc[[i]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    g,t=cfw128_c2e2_capture(state,{'Main':10.},query_md=(50.,) if case=='directional' else ());before=pickle.dumps((state,g,t))
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.geometry_projection_identity==g.projection_identity and r.tracking_projection_identity==t.projection_identity
    assert r.post_pull_reason=='HOLD_POST_PULL_REMAP_UNDEFINED'
    assert all(v.bottom_md<=g.captured_geometry.shoe_md for v in r.annular_intervals)
    assert pickle.dumps((state,g,t))==before
    if case=='directional':assert dict(t.trajectory)[50.]==pytest.approx(47.7464829275686,abs=1e-12)


@pytest.mark.parametrize('fault',['wrong_sha','wrong_view','source_id','projection_id','flags','view_flags','missing','duplicate','row','path','density','gap','volume','ledger','mud','stage','nan','overflow','underflow'])
def test_cfw128_c2e2_malformed_or_mismatched_capture_is_rejected(fault):
    from cfw128_c2e2_cement_placement import assess_cement_placement
    from dataclasses import replace
    g,t=deepcopy(cfw128_c2e2_capture());sha=C2D1_APP_SOURCE_SHA
    if fault=='wrong_sha':sha='0'*40
    elif fault=='wrong_view':
        state=cfw128_c1_uat19_state();state['hardware_table'].at[2,'ID (in)']=8.534;g=cfw128_c2e_view(state)
    elif fault=='source_id':object.__setattr__(t,'source_identity','0'*64)
    elif fault=='projection_id':object.__setattr__(t,'projection_identity','0'*64)
    elif fault=='flags':object.__setattr__(t,'enabled',True)
    elif fault=='view_flags':object.__setattr__(g,'hydraulic_admissible',True)
    elif fault=='missing':object.__setattr__(t,'occupancy',t.occupancy[1:]);cfw128_c2e2_rebind(t)
    elif fault=='duplicate':object.__setattr__(t,'occupancy',t.occupancy+t.occupancy[:1]);cfw128_c2e2_rebind(t)
    elif fault=='row':object.__setattr__(t.path[0],'running_source_rows',(999,))
    elif fault=='path':object.__setattr__(t.path[-1],'outlet_md',4860.)
    elif fault=='density':object.__setattr__(t.occupancy[0],'density_pcf',1.);cfw128_c2e2_rebind(t)
    elif fault=='gap':object.__setattr__(t.occupancy[0],'outlet_md',t.occupancy[0].outlet_md+1.);cfw128_c2e2_rebind(t)
    elif fault=='volume':object.__setattr__(t.occupancy[0],'volume_bbl',41.);cfw128_c2e2_rebind(t)
    elif fault=='ledger':object.__setattr__(t.ledgers[0],'in_path_bbl',39.);cfw128_c2e2_rebind(t)
    elif fault=='mud':object.__setattr__(t,'mud_remaining_bbl',0.);cfw128_c2e2_rebind(t)
    elif fault=='stage':object.__setattr__(t.stages[0],'volume_bbl',39.)
    elif fault=='nan':object.__setattr__(t.occupancy[0],'volume_bbl',float('nan'))
    elif fault=='overflow':object.__setattr__(t.stages[0],'raw_volume',10**1000);object.__setattr__(t.stages[0],'volume_bbl',10**1000)
    elif fault=='underflow':object.__setattr__(t.occupancy[0],'volume_bbl',5e-324);cfw128_c2e2_rebind(t)
    with pytest.raises((ValueError,TypeError)):assess_cement_placement(t,g,expected_app_source_sha=sha)


def test_cfw128_c2e2_capture_edit_freshness_and_immutable_flags():
    from cfw128_c2e2_cement_placement import assess_cement_placement
    from dataclasses import replace,FrozenInstanceError
    state=cfw128_c1_uat19_state();g,t=cfw128_c2e2_capture(state)
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    state['hardware_table'].at[2,'ID (in)']=8.534
    assert assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r  # Replay is NOT_CURRENTNESS_PROOF.
    fresh,ft=cfw128_c2e2_capture(state)
    assert assess_cement_placement(ft,fresh,expected_app_source_sha=C2D1_APP_SOURCE_SHA).projection_identity!=r.projection_identity
    assert pickle.loads(pickle.dumps(r))==r
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(r,flag) is False
        with pytest.raises(ValueError):replace(r,**{flag:True})
    with pytest.raises(FrozenInstanceError):r.enabled=True
    with pytest.raises(TypeError):r.stages[0]=r.stages[0]
    # Coherently changing an unauthenticated source tag cannot authenticate state.
    counterfeit=deepcopy(t);object.__setattr__(counterfeit,'source_identity','a'*64);cfw128_c2e2_rebind(counterfeit)
    cr=assess_cement_placement(counterfeit,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert cr.currentness=='NOT_CURRENTNESS_PROOF' and cr.enabled is False


def test_cfw128_c2e2_import_isolation_and_mutation_negatives(monkeypatch):
    import ast,subprocess,sys
    from pathlib import Path
    root=Path('.');p=root/'cfw128_c2e2_cement_placement.py'
    def verify():
        tree=ast.parse(p.read_text());names={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        assert names<={'dataclasses','fractions','math','re','typing','cement_chart_model','engineering_tools','materials_db','project_state'}
        assert not {'eval','exec','__import__','import_module'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        for other in root.glob('*.py'):
            if other==p:continue
            t=ast.parse(other.read_text());imports={n.module for n in ast.walk(t) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names}
            assert p.stem not in imports
    verify();original=Path.read_text
    for target,addition in ((p,'\nimport cfw128_c2e_volume_tracking\n'),(root/'main.py','\nimport cfw128_c2e2_cement_placement\n')):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda path,*a,**k:original(path,*a,**k)+addition if path==target else original(path,*a,**k))
            with pytest.raises(AssertionError):verify()
    forbidden={'cfw128_adapter','cfw128_c2d_geometry_view','cfw128_c2e_volume_tracking','cfw128_er03_contract','cfw128_er03_boundary','cfw128_er03_volume','cfw128_hb_intake','cfw128_hb_numeric','cfw128_hb03t_frozen','scipy','pumping_simulation','fluids_charts_module_v1_4_2','streamlit','well_report','centralizer_optimizer_engine','cement_charts_engine'}
    subprocess.run([sys.executable,'-B','-W','error','-c','import sys,cfw128_c2e2_cement_placement; assert not '+repr(forbidden)+' & set(sys.modules)'],check=True)


def test_cfw128_c2e2_disconnected_cement_pockets_never_get_a_toc():
    from cfw128_c2e2_cement_placement import assess_cement_placement
    from dataclasses import replace
    g,t=deepcopy(cfw128_c2e2_capture(bug01_geometry_case('LNR 5"'),{'Scavenger':40.,'Main':400.}))
    cement=[(i,o) for i,o in enumerate(t.occupancy) if o.fluid=='Main' and t.path[o.section_index].domain!='injection']
    assert len(cement)>=3
    eligible=[v for v in cement[1:-1] if not any(o.fluid=='Scavenger' and o.section_index==v[1].section_index for o in t.occupancy)]
    assert eligible
    idx,row=eligible[0];moved=row.volume_bbl
    occ=list(t.occupancy);occ[idx]=replace(row,fluid='Scavenger')
    object.__setattr__(t,'occupancy',tuple(occ))
    stages=[];ledgers=[]
    for stage,ledger in zip(t.stages,t.ledgers):
        change=moved if stage.name=='Scavenger' else -moved if stage.name=='Main' else 0.
        stages.append(replace(stage,volume_bbl=stage.volume_bbl+change,raw_volume=stage.volume_bbl+change))
        ledgers.append(replace(ledger,entered_bbl=ledger.entered_bbl+change,in_path_bbl=ledger.in_path_bbl+change))
    object.__setattr__(t,'stages',tuple(stages));object.__setattr__(t,'ledgers',tuple(ledgers));cfw128_c2e2_rebind(t)
    # A coherent copied ledger cannot authenticate transport. Its interposed
    # non-cement partition must still prevent a shoe-to-top cement claim.
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.pumping_state_toc_candidate_md is None and 'HOLD_DISCONNECTED_ANNULAR_CEMENT' in r.reason_codes


def test_cfw128_c2e2_no_selected_stages_stays_mud_and_no_placement():
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from cfw128_c2e2_cement_placement import assess_cement_placement
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state(),());g=cfw128_c2e_view(state)
    t=preview_fluid_tracking(g,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert not r.stages and not r.annular_intervals and not r.surface_cement_return_present
    assert r.pumping_state_toc_candidate_md is None and 'HOLD_NO_PLACED_CEMENT' in r.reason_codes
    assert {x[0] for x in r.other_fluid_occupancy}=={'Mud'}


@pytest.mark.parametrize('missing',['tracking','geometry','proof','host','rows'])
def test_cfw128_c2e2_missing_proofs_and_source_rows_fail_closed(missing):
    from cfw128_c2e2_cement_placement import assess_cement_placement
    g,t=deepcopy(cfw128_c2e2_capture())
    if missing=='tracking':t=None
    elif missing=='geometry':g=None
    elif missing=='proof':object.__setattr__(g,'historical_capacity_audit',None)
    elif missing=='host':object.__setattr__(g.captured_geometry,'host_token','stale-token')
    else:object.__setattr__(t.path[0],'running_source_rows',())
    with pytest.raises((ValueError,TypeError)):assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


# C2e-3 v7: paired nominal geometry only; all earlier test bytes are preserved.
def test_cfw128_c2e3_new_geometric_gap_interface_requirement():
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    g=cfw128_c2e_view(cfw128_c1_uat19_state())
    r=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status=='DISABLED_POST_PULL_CAPACITY_GAP_AUDIT'
    assert r.capacity_gap_bbl==pytest.approx(223.096590253813,abs=1e-10)
    assert r.displacement_volume_authority=='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED'
    assert r.post_pull_fluid_boundary=='HOLD_POST_PULL_FLUID_BOUNDARY_UNDEFINED'


CFW128_C2E3_SEGMENTS={
 'LNR 7"':((0.,400.,8.535,3.5),),
 'TIE BACK LNR 7"':((0.,200.,8.535,3.5),),
 'LNR 5"':((0.,2650.,8.535,3.5),(2650.,3419.,6.094,3.5)),
 'TIE BACK LNR 5"':((0.,100.,8.535,3.5),(100.,200.,6.094,3.5)),
 'LNR 4 1/2"':((0.,200.,8.535,3.5),(200.,400.,6.094,3.5)),
 'TIE BACK LNR 4 1/2"':((0.,100.,8.535,3.5),(100.,200.,6.094,3.5)),
}


@pytest.mark.parametrize('job',tuple(CFW128_C2E3_SEGMENTS))
def test_cfw128_c2e3_six_jobs_exact_piecewise_pairing_and_provenance(job):
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    from cement_chart_model import _capacity
    state=bug01_geometry_case(job);before=pickle.dumps(state);g=cfw128_c2e_view(state)
    proof=pickle.dumps(g);r=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert tuple((p.top_md,p.bottom_md,p.host_id_in,p.drill_pipe_od_in) for p in r.slices)==CFW128_C2E3_SEGMENTS[job]
    assert len(r.slices)==len(g.upper_pumping_annulus)==len(g.upper_post_pull_bore)
    assert r.unchanged_injection_bbl==g.nominal_injection_bbl
    assert r.unchanged_lower_annulus_bbl==sum(v.nominal_volume_bbl for v in g.lower_annulus)
    for row,pump,post in zip(r.slices,g.upper_pumping_annulus,g.upper_post_pull_bore):
        assert (row.top_md,row.bottom_md,row.host_id_in,row.wall_source_rows)==(post.top_md,post.bottom_md,post.outer_diameter_in,post.wall_source_rows)
        assert (row.drill_pipe_od_in,row.running_source_rows)==(pump.inner_diameter_in,pump.running_source_rows)
        assert post.inner_diameter_in==0. and not post.running_source_rows
        assert all(state['hardware_table'].iloc[i].Description=='Drill Pipes' for i in row.running_source_rows)
        assert all(state['hardware_table'].iloc[i].Description in ('Previous Casing','Previous Liner Shoe') for i in row.wall_source_rows)
        assert row.pumping_role=='PUMPING_DP_PRESENT' and row.post_pull_role=='POST_PULL_DP_REMOVED'
        assert row.pumping_capacity_bbl_per_m==_capacity(row.host_id_in,row.drill_pipe_od_in)
        assert row.post_pull_capacity_bbl_per_m==_capacity(row.host_id_in)
        length=row.bottom_md-row.top_md
        assert row.pumping_volume_bbl==length*_capacity(row.host_id_in,row.drill_pipe_od_in)
        assert row.post_pull_volume_bbl==length*_capacity(row.host_id_in)
        assert row.capacity_gap_bbl==row.post_pull_volume_bbl-row.pumping_volume_bbl>0.
        assert row.capacity_gap_bbl==pytest.approx(length*_capacity(row.drill_pipe_od_in),abs=1e-10)
    if '5"' in job or '4 1/2' in job:
        assert [(p.host_id_in,q.outer_diameter_in) for p,q in zip(r.slices,g.upper_post_pull_bore)]==[(8.535,8.535),(6.094,6.094)]
        assert r.slices[0].bottom_md==r.slices[1].top_md
        assert r.slices[0].wall_source_rows!=r.slices[1].wall_source_rows
    assert r.capacity_gap_bbl==sum(v.capacity_gap_bbl for v in r.slices)
    assert r.capacity_gap_bbl==pytest.approx(r.upper_post_pull_bbl-r.upper_pumping_bbl,abs=1e-10)
    assert pickle.dumps(state)==before and pickle.dumps(g)==proof


def test_cfw128_c2e3_uat19_gap_is_geometric_never_derived_displacement():
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    from dataclasses import fields
    g=cfw128_c2e_view(cfw128_c1_uat19_state());r=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.upper_pumping_bbl==pytest.approx(426.973186160669,abs=1e-10)
    assert r.upper_post_pull_bbl==pytest.approx(650.069776414482,abs=1e-10)
    assert r.capacity_gap_bbl==pytest.approx(223.096590253813,abs=1e-10)
    assert r.unchanged_lower_annulus_bbl==pytest.approx(82.460178062841,abs=1e-10)
    assert r.unchanged_injection_bbl==pytest.approx(287.819429400755,abs=1e-10)
    assert [(p.top_md,p.bottom_md,p.host_id_in,p.drill_pipe_od_in,p.running_source_rows,p.wall_source_rows) for p in r.slices]==[(0.,2800.,8.535,5.,(7,),(2,))]
    assert r.shoe_md==3885. and g.captured_geometry.receiver.shoe_md==4860.
    assert all(v.bottom_md<=3885. for v in g.injection+g.lower_annulus+g.upper_pumping_annulus)
    assert r.displacement_volume_authority=='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED'
    assert r.other_pumped_volume_authority=='ENTERED_PHASE_IV_STAGE_VOLUMES'
    assert r.post_pull_fluid_boundary=='HOLD_POST_PULL_FLUID_BOUNDARY_UNDEFINED'
    assert not any(f.name in ('computed_displacement_bbl','final_toc_md','post_pull_fill_bbl') for f in fields(r))


@pytest.mark.parametrize('case',['zero_top','dp_taper','previous_taper','directional'])
def test_cfw128_c2e3_measured_special_geometry_and_zero_lap(case):
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    state=synthetic_tieback(top=0. if case=='zero_top' else 400.) if case!='previous_taper' else r18c_tapered_state(100.)
    if case=='dp_taper':
        t=state['hardware_table'];i=t.index[t.Description=='Drill Pipes'][0];t.at[i,'MD (m)']='200'
        extra=t.iloc[[i]].copy();extra['MD (m)']='200-400';extra['Size (in)']='6.5';extra['ID (in)']=5.8
        state['hardware_table']=pd.concat([t,extra],ignore_index=True)
    if case=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    g=cfw128_c2e_view(state,(50.,) if case=='directional' else ());before=pickle.dumps(g)
    r=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    if case=='zero_top':assert r.upper_pumping_bbl==r.upper_post_pull_bbl==r.capacity_gap_bbl==0. and not r.slices
    else:assert r.slices[0].top_md==0. and r.slices[-1].bottom_md==r.lap_md
    if case=='dp_taper':assert [(v.top_md,v.bottom_md,v.drill_pipe_od_in) for v in r.slices]==[(0.,200.,7.),(200.,400.,6.5)]
    if case=='previous_taper':assert [(v.top_md,v.bottom_md,v.host_id_in) for v in r.slices]==[(0.,100.,8.535),(100.,150.,6.094),(150.,300.,5.8),(300.,400.,6.094)]
    if case=='directional':assert next(v.tvd for v in g.captured_geometry.trajectory if v.md==50.)==pytest.approx(47.7464829275686,abs=1e-12)
    assert r.displacement_volume_authority=='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED'
    assert pickle.dumps(g)==before


@pytest.mark.parametrize('job',BUG01_JOBS[:2])
def test_cfw128_c2e3_casing_has_no_fictitious_pull_or_unknown_zero(job):
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    g=cfw128_c2e_view(bug01_geometry_case(job));r=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status==r.post_pull_fluid_boundary=='NOT_APPLICABLE'
    assert r.upper_pumping_bbl is r.upper_post_pull_bbl is r.capacity_gap_bbl is None
    assert not r.slices and r.unchanged_injection_bbl==g.nominal_injection_bbl
    assert r.displacement_volume_authority=='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED'


@pytest.mark.parametrize('stage,overflow',[('Main',False),('Main',True),('Spacer',False),('Spacer',True),('Displacement Fluid',False)])
def test_cfw128_c2e3_stage_volume_authority_and_geometry_independence(stage,overflow):
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state(),('Spacer','Main','Displacement Fluid'))
    state['fluids_config']['params']['Main']['volume']=2000. if overflow else 40.
    state['fluids_config']['params']['Spacer']['volume']=10.
    state['fluids_config']['params']['Displacement Fluid']['volume']=20.  # Entered what-if only; NOT derived.
    g=cfw128_c2e_view(state);before=pickle.dumps(g)
    def preview():return preview_fluid_tracking(g,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=3)
    a=preview();gap=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    original=state['fluids_config']['params'][stage]['volume'];state['fluids_config']['params'][stage]['volume']=original+20.
    intended=pickle.dumps(state);b=preview();same=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    la,lb=(next(v for v in r.ledgers if v.fluid==stage) for r in (a,b))
    assert lb.entered_bbl==la.entered_bbl+20.
    assert next(v for v in b.stages if v.name==stage).volume_bbl==original+20.
    if overflow:assert lb.ideal_returned_bbl==pytest.approx(la.ideal_returned_bbl+20.)
    else:assert lb.in_path_bbl==pytest.approx(la.in_path_bbl+20.)
    assert a.occupancy!=b.occupancy or a.ledgers!=b.ledgers
    assert gap==same and pickle.dumps(g)==before and pickle.dumps(state)==intended
    assert b.source_identity!=a.source_identity
    assert gap.other_pumped_volume_authority=='ENTERED_PHASE_IV_STAGE_VOLUMES'
    assert gap.displacement_volume_authority=='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED'
    if stage=='Displacement Fluid':
        assert next(v for v in b.stages if v.name=='Main').volume_bbl==next(v for v in a.stages if v.name=='Main').volume_bbl
        assert next(v for v in b.stages if v.name=='Displacement Fluid').density_pcf==b.initial_mud_density_pcf
        assert any(o.fluid=='Mud' for o in b.occupancy) and any(o.fluid=='Displacement Fluid' for o in b.occupancy)


def test_cfw128_c2e3_mud_returns_do_not_put_cement_at_surface_or_final_toc():
    from cfw128_c2e2_cement_placement import assess_cement_placement
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    # Existing entered what-if fixture, NOT an approved operational displacement
    # rule. Main's 40 bbl is its intended pumped amount in this synthetic case.
    g,t=cfw128_c2e2_capture(cfw128_c1_uat19_state(),{'Main':40.})
    r=assess_cement_placement(t,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    gap=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert t.mud_displaced_bbl>0. and r.pumping_state_toc_candidate_md>2800.
    assert not r.surface_cement_return_present
    assert next(v for v in t.ledgers if v.fluid=='Main').entered_bbl==40.
    assert r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'
    assert gap.final_toc=='NOT_EVALUATED' and gap.displacement_volume_authority=='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED'


def cfw128_c2e3_rebind_view(g):
    from cfw128_c2d_geometry_view import _tree,_view_id
    from project_state import fingerprint
    source=fingerprint(['c2d1-captured-input/1',g.app_source_sha,_tree(g.captured_geometry),_tree(g.historical_capacity_audit)])
    object.__setattr__(g,'source_identity',source)
    values=(g.status,g.injection,g.lower_annulus,g.upper_pumping_annulus,g.upper_post_pull_bore)
    object.__setattr__(g,'projection_identity',_view_id(source,g.app_source_sha,values))
    return g


@pytest.mark.parametrize('fault',['none','dict','sha','flags','nested_flags','source_hash','projection_hash','proof','host','receiver','unpaired','overlap','running_rows','wall_rows','host_ID','DP_OD','negative_MD','nan','inf','body_ID','old_receiver_flow','wrong_role'])
def test_cfw128_c2e3_invalid_or_corrupt_geometry_fails_closed(fault):
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    g=deepcopy(cfw128_c2e_view(cfw128_c1_uat19_state()));sha=C2D1_APP_SOURCE_SHA
    if fault=='none':g=None
    elif fault=='dict':g={}
    elif fault=='sha':sha='0'*40
    elif fault=='flags':object.__setattr__(g,'enabled',True)
    elif fault=='nested_flags':object.__setattr__(g.captured_geometry,'hydraulic_admissible',True)
    elif fault=='source_hash':object.__setattr__(g,'source_identity','0'*64)
    elif fault=='projection_hash':object.__setattr__(g,'projection_identity','0'*64)
    elif fault=='proof':object.__setattr__(g,'historical_capacity_audit',None)
    elif fault=='host':object.__setattr__(g.captured_geometry,'host_token','stale-selected-host')
    elif fault=='receiver':object.__setattr__(g.captured_geometry,'receiver',None)
    elif fault=='unpaired':object.__setattr__(g,'upper_post_pull_bore',());cfw128_c2e3_rebind_view(g)
    elif fault=='overlap':object.__setattr__(g.upper_post_pull_bore[0],'top_md',1.);cfw128_c2e3_rebind_view(g)
    elif fault=='running_rows':object.__setattr__(g.upper_pumping_annulus[0],'running_source_rows',());cfw128_c2e3_rebind_view(g)
    elif fault=='wall_rows':object.__setattr__(g.upper_post_pull_bore[0],'wall_source_rows',(999,));cfw128_c2e3_rebind_view(g)
    elif fault=='host_ID':
        object.__setattr__(g.upper_pumping_annulus[0],'outer_diameter_in',9.);object.__setattr__(g.upper_post_pull_bore[0],'outer_diameter_in',9.);cfw128_c2e3_rebind_view(g)
    elif fault=='DP_OD':object.__setattr__(g.upper_pumping_annulus[0],'inner_diameter_in',8.535);cfw128_c2e3_rebind_view(g)
    elif fault=='negative_MD':object.__setattr__(g.upper_pumping_annulus[0],'top_md',-1.)
    elif fault in ('nan','inf'):object.__setattr__(g.upper_post_pull_bore[0],'outer_diameter_in',float(fault))
    elif fault=='body_ID':object.__setattr__(g.injection[-1],'outer_diameter_in',5.);cfw128_c2e3_rebind_view(g)
    elif fault=='old_receiver_flow':object.__setattr__(g.lower_annulus[-1],'bottom_md',4860.);cfw128_c2e3_rebind_view(g)
    elif fault=='wrong_role':object.__setattr__(g.upper_pumping_annulus[0],'domain','lower_annulus');cfw128_c2e3_rebind_view(g)
    with pytest.raises((ValueError,TypeError)):audit_post_pull_gap(g,expected_app_source_sha=sha)


def test_cfw128_c2e3_deep_immutability_and_no_currentness_claim():
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    from dataclasses import replace,FrozenInstanceError
    import inspect
    assert tuple(inspect.signature(audit_post_pull_gap).parameters)==('view','expected_app_source_sha')
    state=cfw128_c1_uat19_state();g=cfw128_c2e_view(state);r=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.loads(pickle.dumps(r))==r and r==audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.hydraulics==r.final_toc=='NOT_EVALUATED' and r.currentness=='NOT_CURRENTNESS_PROOF'
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(r,flag) is False
        with pytest.raises(ValueError):replace(r,**{flag:True})
    with pytest.raises(FrozenInstanceError):r.slices[0].host_id_in=9.
    with pytest.raises(FrozenInstanceError):r.enabled=True
    with pytest.raises(TypeError):r.slices[0]=r.slices[0]
    state['hardware_table'].at[2,'ID (in)']=8.534
    assert audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r  # A replay cannot prove fresh App state.
    fresh=audit_post_pull_gap(cfw128_c2e_view(state),expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert fresh.projection_identity!=r.projection_identity and fresh.geometry_source_identity!=r.geometry_source_identity
    assert fresh.capacity_gap_bbl==pytest.approx(r.capacity_gap_bbl,abs=1e-10)


def test_cfw128_c2e3_import_and_no_production_caller_isolation(monkeypatch):
    import ast,sys,subprocess
    from pathlib import Path
    root=Path('.');path=root/'cfw128_c2e3_post_pull_gap.py'
    def verify():
        tree=ast.parse(path.read_text());names={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        assert names<={'dataclasses','math','re','typing','cement_chart_model','project_state'}
        assert not {'eval','exec','__import__','import_module','open'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        for other in root.glob('*.py'):
            if other==path:continue
            t=ast.parse(other.read_text());imports={n.module for n in ast.walk(t) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names}
            assert path.stem not in imports
    verify();original=Path.read_text
    for target,addition in ((path,'\nimport cfw128_c2d_geometry_view\n'),(root/'main.py','\nimport cfw128_c2e3_post_pull_gap\n')):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:original(p,*a,**k)+addition if p==target else original(p,*a,**k))
            with pytest.raises(AssertionError):verify()
    forbidden={'cfw128_adapter','cfw128_c2d_geometry_view','cfw128_c2e_volume_tracking','cfw128_c2e2_cement_placement','cfw128_er03_contract','cfw128_er03_boundary','cfw128_er03_volume','cfw128_hb_intake','cfw128_hb_numeric','cfw128_hb03t_frozen','scipy','pumping_simulation','fluids_charts_module_v1_4_2','streamlit','well_report','centralizer_optimizer_engine','cement_charts_engine'}
    subprocess.run([sys.executable,'-B','-W','error','-c','import sys,cfw128_c2e3_post_pull_gap; assert not '+repr(forbidden)+' & set(sys.modules)'],check=True)


# C2e-4: disabled capacity MD0..active Shoe-25m, no App integration.
def test_cfw128_c2e4_new_disabled_derived_displacement_interface():
    from cfw128_c2e4_derived_displacement import derive_displacement
    g=cfw128_c2e_view(cfw128_c1_uat19_state())
    r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status=='DISABLED_DERIVED_DISPLACEMENT_PREVIEW'
    assert r.active_shoe_md==3885. and r.end_md==3860. and r.reserved_shoe_interval_m==25.
    assert r.derived_displacement_bbl==pytest.approx(284.947218881107,abs=1e-10)


CFW128_C2E4_PARTS={
 'CSG 13 3/8"':((0.,1175.,12.25,(1,)),),
 'CSG 9 5/8"':((0.,1175.,8.535,(1,)),),
 'LNR 7"':((0.,400.,2.764,(1,)),(400.,1175.,6.094,(3,))),
 'LNR 5"':((0.,3419.,2.764,(5,)),(3419.,4475.,4.276,(7,))),
 'LNR 4 1/2"':((0.,400.,2.764,(2,)),(400.,1175.,4.,(4,))),
 'TIE BACK LNR 7"':((0.,200.,2.764,(2,)),(200.,675.,6.094,(3,))),
 'TIE BACK LNR 5"':((0.,200.,2.764,(3,)),(200.,675.,4.276,(4,))),
 'TIE BACK LNR 4 1/2"':((0.,200.,2.764,(3,)),(200.,675.,4.,(4,))),
}


def cfw128_c2e4_manual_bbl(length,internal_id):
    # Independent area_ft2 * length_ft / bbl_ft3, exact published App constants;
    # no _capacity or production derived-volume function is called here.
    return math.pi*(internal_id/24.)**2*(length/.3048)/(42./7.48051945)


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2e4_eight_jobs_exact_internal_ids_clips_and_rows(job):
    from cfw128_c2e4_derived_displacement import derive_displacement
    state=bug01_geometry_case(job);before=pickle.dumps(state);g=cfw128_c2e_view(state);proof=pickle.dumps(g)
    r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert tuple((p.top_md,p.bottom_md,p.internal_id_in,p.source_rows) for p in r.sections)==CFW128_C2E4_PARTS[job]
    assert r.end_md==g.captured_geometry.shoe_md-25. and r.sections[-1].bottom_md==r.end_md
    assert r.sections[0].top_md==0. and all(a.bottom_md==b.top_md for a,b in zip(r.sections,r.sections[1:]))
    assert r.reserved_shoe_interval_m==25. and r.surface_line_volume=='NONE_ADDED'
    assert r.volume_basis=='NOMINAL_INTERNAL_STRING_CAPACITY'
    assert r.derived_displacement_bbl==pytest.approx(sum(cfw128_c2e4_manual_bbl(b-a,diam) for a,b,diam,rows in CFW128_C2E4_PARTS[job]),abs=1e-10)
    assert r.derived_displacement_bbl==sum(p.nominal_volume_bbl for p in r.sections)
    for p in r.sections:
        source=g.injection[p.source_section_index]
        assert p.original_bottom_md==source.bottom_md and p.internal_id_in==source.outer_diameter_in
        assert p.source_rows==source.running_source_rows
        assert all(state['hardware_table'].iloc[i]['ID (in)']==p.internal_id_in for i in p.source_rows)
        assert p.nominal_volume_bbl==pytest.approx(cfw128_c2e4_manual_bbl(p.bottom_md-p.top_md,p.internal_id_in),abs=1e-10)
    if job in ('LNR 5"','LNR 4 1/2"','TIE BACK LNR 5"','TIE BACK LNR 4 1/2"'):
        assert {p.outer_diameter_in for p in g.upper_pumping_annulus}=={8.535,6.094}
        assert len(r.sections)==2  # Host transitions do not fabricate injection-ID sections.
    assert pickle.dumps(g)==proof and pickle.dumps(state)==before


def test_cfw128_c2e4_uat19_independent_reference_excludes_gap_and_receiver():
    from cfw128_c2e4_derived_displacement import derive_displacement
    g=cfw128_c2e_view(cfw128_c1_uat19_state());r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert [(p.top_md,p.bottom_md,p.internal_id_in,p.source_rows) for p in r.sections]==[(0.,2800.,4.276,(7,)),(2800.,3860.,6.004,(6,))]
    manual=cfw128_c2e4_manual_bbl(2800.,4.276)+cfw128_c2e4_manual_bbl(1060.,6.004)
    assert r.derived_displacement_bbl==pytest.approx(manual,abs=1e-10)
    assert r.derived_displacement_bbl==pytest.approx(284.947218881107,abs=1e-10)
    assert g.nominal_injection_bbl==pytest.approx(287.819429400755,abs=1e-10)
    assert g.nominal_injection_bbl-r.derived_displacement_bbl==pytest.approx(cfw128_c2e4_manual_bbl(25.,6.004),abs=1e-10)
    assert r.derived_displacement_bbl!=pytest.approx(223.096590253813,abs=1e-8)
    assert g.captured_geometry.receiver.shoe_md==4860. and r.active_shoe_md==3885.
    assert r.hydraulics=='HYDRAULICS_NOT_EVALUATED' and r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'


@pytest.mark.parametrize('top',[674.,675.,676.])
def test_cfw128_c2e4_endpoint_before_at_after_lap_is_measured_md(top):
    from cfw128_c2e4_derived_displacement import derive_displacement
    state=synthetic_tieback(top=top);frame=state['hardware_table'];i=frame.index[frame.Description=='Drill Pipes'][0]
    frame.at[i,'Size (in)']='5';frame.at[i,'ID (in)']=4.276
    r=derive_displacement(cfw128_c2e_view(state),expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    expected=[(0.,min(top,675.),4.276)]
    if top<675.:expected.append((top,675.,6.))
    assert [(p.top_md,p.bottom_md,p.internal_id_in) for p in r.sections]==expected
    assert r.end_md==675. and r.active_shoe_md==700.


@pytest.mark.parametrize('edge',[674.,675.,676.])
def test_cfw128_c2e4_tapered_dp_and_body_endpoint_partition(edge):
    from cfw128_c2e4_derived_displacement import derive_displacement
    job='TIE BACK LNR 7"';table=hardware(
        ('Previous Casing','800','9 5/8',8.535),('Previous Liner Shoe','700-1200','7',6.),
        ('Drill Pipes','200','5',4.276),('Drill Pipes','200-400','4 1/2',4.),
        ('Tie Back Liner Shoe',f'400-{edge:g}','7',6.),('Tie Back Liner Shoe',f'{edge:g}-700','6 1/2',5.8),
        ('Open Hole Size','800-1200','8.5',8.5))
    state=project(job,table,1200.)
    state['placement_config']['host_row']=next(iter(hardware_choices(table,{'Previous Casing'})))
    state['placement_config']['target_row']=next(k for k,v in hardware_choices(table,target_descriptions(job)).items() if v['depth']==700.)
    g=cfw128_c2e_view(state);r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    expected=[(0.,200.,4.276),(200.,400.,4.),(400.,min(edge,675.),6.)]
    if edge<675.:expected.append((edge,675.,5.8))
    assert [(p.top_md,p.bottom_md,p.internal_id_in) for p in r.sections]==expected
    assert r.derived_displacement_bbl==pytest.approx(sum(cfw128_c2e4_manual_bbl(b-a,d) for a,b,d in expected),abs=1e-10)
    assert [p.source_rows for p in r.sections]==[(2,),(3,),(4,)]+([(5,)] if edge<675. else [])


@pytest.mark.parametrize('case',['zero_top','previous_taper','directional'])
def test_cfw128_c2e4_nonhydraulic_special_captures(case):
    from cfw128_c2e4_derived_displacement import derive_displacement
    state=synthetic_tieback(top=0.) if case=='zero_top' else r18c_tapered_state(100.) if case=='previous_taper' else synthetic_tieback(top=400.)
    if case=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    g=cfw128_c2e_view(state,(50.,) if case=='directional' else ());before=pickle.dumps(g)
    r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.end_md==g.captured_geometry.shoe_md-25. and pickle.dumps(g)==before
    if case=='zero_top':assert len(r.sections)==1 and r.sections[0].description=='Tie Back Liner Shoe' and r.sections[0].top_md==0.
    if case=='directional':
        assert next(v.tvd for v in g.captured_geometry.trajectory if v.md==50.)==pytest.approx(47.7464829275686,abs=1e-12)
        vertical=deepcopy(state);vertical['well_geometry']={'version':1,'type':'Vertical','td_m':1200.}
        assert derive_displacement(cfw128_c2e_view(vertical),expected_app_source_sha=C2D1_APP_SOURCE_SHA).derived_displacement_bbl==r.derived_displacement_bbl


@pytest.mark.parametrize('shoe',[24.5,25.])
def test_cfw128_c2e4_actual_short_shoe_has_no_authorized_endpoint(shoe):
    from cfw128_c2e4_derived_displacement import derive_displacement
    state=project('CSG 9 5/8"',hardware(('Previous Casing','5','13 3/8',12.347),('Casing',str(shoe),'9 5/8',8.535),('Open Hole Size',f'5-{shoe:g}','12.25',12.25)),shoe)
    g=cfw128_c2e_view(state)
    assert g.status=='DISABLED_GEOMETRY_VIEW'
    with pytest.raises(ValueError,match='25'):derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


@pytest.mark.parametrize('stage',['Displacement Fluid','Main','Spacer'])
def test_cfw128_c2e4_entered_volumes_do_not_override_derived_geometry(stage):
    from cfw128_c2e4_derived_displacement import derive_displacement
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    state=cfw128_c2e_fluids(cfw128_c1_uat19_state(),('Spacer','Main','Displacement Fluid'))
    for n,v in (('Spacer',10.),('Main',40.),('Displacement Fluid',20.)):state['fluids_config']['params'][n]['volume']=v
    g=cfw128_c2e_view(state);r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    a=preview_fluid_tracking(g,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=3)
    old=state['fluids_config']['params'][stage]['volume'];state['fluids_config']['params'][stage]['volume']=old+20.
    intended=pickle.dumps(state);b=preview_fluid_tracking(g,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=3)
    assert derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    assert next(v for v in b.ledgers if v.fluid==stage).entered_bbl==next(v for v in a.ledgers if v.fluid==stage).entered_bbl+20.
    assert a.occupancy!=b.occupancy and pickle.dumps(state)==intended
    assert next(v for v in b.stages if v.name==stage).volume_bbl==old+20.  # Existing what-if untouched; other entered pumped volumes authoritative.
    if stage=='Displacement Fluid':assert next(v for v in b.stages if v.name==stage).volume_bbl!=r.derived_displacement_bbl


def test_cfw128_c2e4_actual_injection_id_and_depth_edits_change_source_and_result():
    from cfw128_c2e4_derived_displacement import derive_displacement
    state=bug01_geometry_case('CSG 9 5/8"');g=cfw128_c2e_view(state);r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    changed=deepcopy(state);changed['hardware_table'].at[1,'ID (in)']=8.5
    fresh=derive_displacement(cfw128_c2e_view(changed),expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert fresh.derived_displacement_bbl<r.derived_displacement_bbl and fresh.geometry_source_identity!=r.geometry_source_identity
    deeper=project('CSG 9 5/8"',hardware(('Previous Casing','400','13 3/8',12.347),('Casing','1250','9 5/8',8.535),('Open Hole Size','400-1250','12.25',12.25)),1250.)
    deep=derive_displacement(cfw128_c2e_view(deeper),expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert deep.derived_displacement_bbl-r.derived_displacement_bbl==pytest.approx(cfw128_c2e4_manual_bbl(50.,8.535),abs=1e-10)
    assert deep.geometry_source_identity!=r.geometry_source_identity
    changed_host=deepcopy(state);changed_host['hardware_table'].at[0,'ID (in)']=12.3
    host=derive_displacement(cfw128_c2e_view(changed_host),expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert host.derived_displacement_bbl==r.derived_displacement_bbl  # Host is provenance, never injection ID.
    assert host.geometry_source_identity!=r.geometry_source_identity
    assert derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r and r.currentness=='NOT_CURRENTNESS_PROOF'


@pytest.mark.parametrize('fault',['none','dict','sha','malformed_sha','flags','nested_flags','source_id','projection_id','proof','missing_section','gap','overlap','id','rows','duplicate_rows','wall_rows','nan','inf','negative_md','wrong_job','kind','role','source_id_changed','missing_slot','old_receiver_end'])
def test_cfw128_c2e4_invalid_changed_or_incomplete_capture_rejected(fault):
    from cfw128_c2e4_derived_displacement import derive_displacement
    g=deepcopy(cfw128_c2e_view(cfw128_c1_uat19_state()));sha=C2D1_APP_SOURCE_SHA
    if fault=='none':g=None
    elif fault=='dict':g={}
    elif fault=='sha':sha='0'*40
    elif fault=='malformed_sha':sha='not-a-sha'
    elif fault=='flags':object.__setattr__(g,'ready_to_run',True)
    elif fault=='nested_flags':object.__setattr__(g.captured_geometry,'hydraulic_admissible',True)
    elif fault=='source_id':object.__setattr__(g,'source_identity','0'*64)
    elif fault=='projection_id':object.__setattr__(g,'projection_identity','0'*64)
    elif fault=='proof':object.__setattr__(g,'historical_capacity_audit',None)
    elif fault=='missing_section':object.__setattr__(g,'injection',g.injection[1:]);cfw128_c2e3_rebind_view(g)
    elif fault=='gap':object.__setattr__(g.injection[1],'top_md',2801.);cfw128_c2e3_rebind_view(g)
    elif fault=='overlap':object.__setattr__(g.injection[1],'top_md',2799.);cfw128_c2e3_rebind_view(g)
    elif fault=='id':object.__setattr__(g.injection[1],'outer_diameter_in',6.184);cfw128_c2e3_rebind_view(g)
    elif fault=='rows':object.__setattr__(g.injection[0],'running_source_rows',());cfw128_c2e3_rebind_view(g)
    elif fault=='duplicate_rows':object.__setattr__(g.injection[0],'running_source_rows',(7,7));cfw128_c2e3_rebind_view(g)
    elif fault=='wall_rows':object.__setattr__(g.injection[0],'wall_source_rows',(2,));cfw128_c2e3_rebind_view(g)
    elif fault in ('nan','inf'):object.__setattr__(g.injection[0],'outer_diameter_in',float(fault))
    elif fault=='negative_md':object.__setattr__(g.injection[0],'top_md',-1.)
    elif fault=='wrong_job':object.__setattr__(g.captured_geometry,'job','CMT PLUG')
    elif fault=='kind':object.__setattr__(g.captured_geometry,'kind','openhole')
    elif fault=='role':object.__setattr__(g.captured_geometry.active_sections[0],'description','Previous Liner Shoe');cfw128_c2e3_rebind_view(g)
    elif fault=='source_id_changed':object.__setattr__(g.captured_geometry.active_sections[0],'id_in',4.5);cfw128_c2e3_rebind_view(g)
    elif fault=='missing_slot':object.__delattr__(g.injection[0],'outer_diameter_in')
    elif fault=='old_receiver_end':object.__setattr__(g.injection[-1],'bottom_md',4860.);cfw128_c2e3_rebind_view(g)
    with pytest.raises((ValueError,TypeError)):derive_displacement(g,expected_app_source_sha=sha)


def test_cfw128_c2e4_frozen_flags_and_replayed_input_never_prove_liveness():
    from cfw128_c2e4_derived_displacement import derive_displacement
    from dataclasses import replace,FrozenInstanceError
    import inspect
    assert tuple(inspect.signature(derive_displacement).parameters)==('view','expected_app_source_sha')
    state=cfw128_c1_uat19_state();g=cfw128_c2e_view(state);r=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.loads(pickle.dumps(r))==r and r==derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(r,flag) is False
        with pytest.raises(ValueError):replace(r,**{flag:True})
    with pytest.raises(ValueError):replace(r,reserved_shoe_interval_m=0.)
    with pytest.raises(FrozenInstanceError):r.sections[0].internal_id_in=99.
    with pytest.raises(TypeError):r.sections[0]=r.sections[0]
    state['hardware_table'].at[7,'ID (in)']=4.3
    assert derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    fresh=derive_displacement(cfw128_c2e_view(state),expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert fresh.projection_identity!=r.projection_identity and fresh.derived_displacement_bbl!=r.derived_displacement_bbl
    assert r.currentness==fresh.currentness=='NOT_CURRENTNESS_PROOF'


def test_cfw128_c2e4_import_and_production_caller_isolation(monkeypatch):
    import ast,sys,subprocess
    from pathlib import Path
    root=Path('.');path=root/'cfw128_c2e4_derived_displacement.py'
    def verify():
        tree=ast.parse(path.read_text());names={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        assert names<={'dataclasses','math','re','typing','cement_chart_model','project_state'}
        assert not {'eval','exec','__import__','import_module','open'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        for other in root.glob('*.py'):
            if other==path:continue
            t=ast.parse(other.read_text());imports={n.module for n in ast.walk(t) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names}
            assert path.stem not in imports
    verify();original=Path.read_text
    for target,addition in ((path,'\nimport cfw128_c2e3_post_pull_gap\n'),(root/'main.py','\nimport cfw128_c2e4_derived_displacement\n')):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:original(p,*a,**k)+addition if p==target else original(p,*a,**k))
            with pytest.raises(AssertionError):verify()
    forbidden={'cfw128_adapter','cfw128_c2d_geometry_view','cfw128_c2e_volume_tracking','cfw128_c2e2_cement_placement','cfw128_c2e3_post_pull_gap','cfw128_er03_contract','cfw128_er03_boundary','cfw128_er03_volume','cfw128_hb_intake','cfw128_hb_numeric','cfw128_hb03t_frozen','scipy','pumping_simulation','fluids_charts_module_v1_4_2','streamlit','well_report','centralizer_optimizer_engine','cement_charts_engine'}
    subprocess.run([sys.executable,'-B','-W','error','-c','import sys,cfw128_c2e4_derived_displacement; assert not '+repr(forbidden)+' & set(sys.modules)'],check=True)


# C2e-5: source-bound effective schedule; composition bridge is TEST ONLY.
def cfw128_c2e5_inputs(state=None,names=('Spacer','Main','Displacement Fluid')):
    from cfw128_c2e4_derived_displacement import derive_displacement
    state=cfw128_c1_uat19_state() if state is None else state
    cfw128_c2e_fluids(state,names,volume=40.)
    if 'Displacement Fluid' in names:state['fluids_config']['params']['Displacement Fluid']['volume']=20.
    g=cfw128_c2e_view(state);d=derive_displacement(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    return state,g,d


def test_cfw128_c2e5_new_effective_schedule_receipt_requirement():
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=cfw128_c2e5_inputs()
    r=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status=='DISABLED_EFFECTIVE_PUMPING_SCHEDULE'
    mud=next(v for v in r.stages if v.name=='Displacement Fluid')
    assert mud.volume_bbl==pytest.approx(284.947218881107,abs=1e-10)
    assert mud.volume_authority=='DERIVED_C2E4_INTERNAL_STRING_CAPACITY' and mud.raw_entered_volume is None


def cfw128_c2e5_test_composition(state,g,d):
    """TEST_ONLY_SYNTHETIC_COMPOSITION; never a production/currentness bridge."""
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from cfw128_c2e2_cement_placement import assess_cement_placement
    schedule=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    overlay=deepcopy(state);params=overlay['fluids_config'].setdefault('params',{})
    params.setdefault('Displacement Fluid',{})['volume']=next(s.volume_bbl for s in schedule.stages if s.name=='Displacement Fluid')
    tracking=preview_fluid_tracking(g,overlay,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=len(schedule.stages))
    placement=assess_cement_placement(tracking,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    return {'evidence_class':'TEST_ONLY_SYNTHETIC_COMPOSITION','schedule':schedule,'overlay':overlay,'tracking':tracking,'placement':placement}


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2e5_eight_jobs_source_amounts_and_test_only_pump_end(job):
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=cfw128_c2e5_inputs(bug01_geometry_case(job),('Spacer','Main','Lead','Tail','Spacer Behind','Displacement Fluid'))
    state['fluids_config']['params']['Main']['volume']=40
    state['fluids_config']['params']['Main']['density']='110-112'
    for name in ('Spacer','Lead','Tail','Spacer Behind'):state['fluids_config']['params'][name]['volume']=10.
    # Twenty entered bbl exceeds the largest fixture's reserved 25m capacity,
    # so this scenario specifically proves trailing-Spacer shoe separation.
    state['fluids_config']['params']['Spacer Behind']['volume']=20.
    before=pickle.dumps((state,g,d));r=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    manual=sum(cfw128_c2e4_manual_bbl(b-a,diam) for a,b,diam,rows in CFW128_C2E4_PARTS[job])
    assert next(v.volume_bbl for v in r.stages if v.name=='Displacement Fluid')==pytest.approx(manual,abs=1e-10)
    assert [v.name for v in r.stages]==['Spacer','Main','Lead','Tail','Spacer Behind','Displacement Fluid']
    for v in r.stages:
        if v.name=='Displacement Fluid':
            assert v.volume_authority=='DERIVED_C2E4_INTERNAL_STRING_CAPACITY' and v.record_source=='C2E4'
            assert v.raw_entered_volume is None and v.density_pcf==80.
        else:
            row=state['fluids_config']['params'][v.name]
            assert v.raw_entered_volume==row['volume'] and type(v.raw_entered_volume) is type(row['volume'])
            assert v.volume_bbl==row['volume'] and v.raw_density==row['density']
            assert v.volume_authority=='ENTERED_PHASE_IV' and v.record_source=='fluids_config.params'
    assert next(v.density_pcf for v in r.stages if v.name=='Main')==111.
    evidence=cfw128_c2e5_test_composition(state,g,d)
    assert evidence['evidence_class']=='TEST_ONLY_SYNTHETIC_COMPOSITION'
    assert evidence['placement'].pumping_state_toc_candidate_md is None
    assert 'HOLD_CEMENT_NOT_ANCHORED_AT_SHOE' in evidence['placement'].reason_codes
    assert evidence['placement'].final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'
    for name,row in state['fluids_config']['params'].items():
        if name!='Displacement Fluid':assert evidence['overlay']['fluids_config']['params'][name]==row
    assert pickle.dumps((state,g,d))==before


@pytest.mark.parametrize('display',['missing',None,0.,-20.,float('nan'),float('inf'),True,'bad volume',{'bad':'volume'},[1,2]])
def test_cfw128_c2e5_ignored_mud_display_never_changes_schedule_or_composition(display):
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=cfw128_c2e5_inputs(names=('Main','Displacement Fluid'))
    baseline=cfw128_c2e5_test_composition(state,g,d)
    if type(display) is str and display=='missing':state['fluids_config']['params']['Displacement Fluid'].pop('volume')
    else:state['fluids_config']['params']['Displacement Fluid']['volume']=display
    before=pickle.dumps(state);changed=cfw128_c2e5_test_composition(state,g,d)
    assert changed['schedule']==baseline['schedule']
    assert changed['tracking']==baseline['tracking'] and changed['placement']==baseline['placement']
    assert pickle.dumps(state)==before
    assert changed['schedule'].derived_projection_identity==d.projection_identity
    assert changed['tracking'].stages[-1].raw_volume==d.derived_displacement_bbl
    assert changed['schedule'].stages[-1].raw_entered_volume is None  # Never mislabel the derived value as entered.


def test_cfw128_c2e5_ignored_displacement_record_is_not_serialized_or_called():
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=cfw128_c2e5_inputs();r=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    class Trap:
        def __float__(self):raise AssertionError('ignored display was read')
        def __repr__(self):raise AssertionError('ignored display was serialized')
        def __deepcopy__(self,memo):raise AssertionError('ignored display was copied')
    for ignored in (Trap(),None,{},pd.DataFrame([[1,2]],columns=['duplicate','duplicate'])):
        state['fluids_config']['params']['Displacement Fluid']=ignored
        assert build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    state['fluids_config']['params'].pop('Displacement Fluid')
    assert build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r


@pytest.mark.parametrize('names',[('Main','Displacement Fluid'),('Pre Flush','Scavenger','Lead #1','Lead #2','Tail','Displacement Fluid'),('Diesel','Spacer Ahead','Spacer Behind','Displacement Fluid')])
def test_cfw128_c2e5_all_selected_stages_source_precedence_and_density_authorities(names):
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    from materials_db import HYDRAULIC_EXECUTION_ORDER
    state,g,d=cfw128_c2e5_inputs(names=names)
    state['mud_density']='80-82'
    nonmud=next(n for n in names if n!='Displacement Fluid')
    state['fluid_data']={nonmud:{'volume':999.,'density':52. if nonmud=='Diesel' else 120.}}
    a=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert tuple(v.name for v in a.stages)==tuple(n for n in HYDRAULIC_EXECUTION_ORDER if n in names)
    assert next(v for v in a.stages if v.name==nonmud).volume_bbl==40.
    assert a.stages[-1].density_pcf==81. and a.stages[-1].raw_density=='80-82'
    state['fluids_config']['params'].pop(nonmud)
    b=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert next(v for v in b.stages if v.name==nonmud).record_source=='fluid_data'
    assert next(v for v in b.stages if v.name==nonmud).volume_bbl==999.
    state['mud_density']=None;state['well_data']={'mud_density':'83-85'}
    c=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert c.stages[-1].density_pcf==84. and c.stages[-1].density_source=='well_data.mud_density'


@pytest.mark.parametrize('stage',['Main','Spacer'])
def test_cfw128_c2e5_entered_nonmud_edits_change_schedule_and_test_composition(stage):
    state,g,d=cfw128_c2e5_inputs();before=cfw128_c2e5_test_composition(state,g,d)
    original=state['fluids_config']['params'][stage]['volume'];state['fluids_config']['params'][stage]['volume']=original+20.
    after=cfw128_c2e5_test_composition(state,g,d)
    assert next(v for v in after['schedule'].stages if v.name==stage).volume_bbl==original+20.
    assert after['schedule'].source_identity!=before['schedule'].source_identity and after['schedule'].projection_identity!=before['schedule'].projection_identity
    assert after['tracking'].occupancy!=before['tracking'].occupancy
    assert after['schedule'].stages[-1].volume_bbl==before['schedule'].stages[-1].volume_bbl==d.derived_displacement_bbl
    assert after['placement'].pumping_state_toc_candidate_md is None


def test_cfw128_c2e5_uat19_remaining_25m_cement_and_mud_returns_are_not_toc_release():
    state,g,d=cfw128_c2e5_inputs(names=('Main','Displacement Fluid'));e=cfw128_c2e5_test_composition(state,g,d)
    r=e['schedule'];t=e['tracking'];p=e['placement']
    assert r.stages[-1].volume_bbl==pytest.approx(284.947218881107,abs=1e-10)
    assert r.stages[-1].volume_bbl==pytest.approx(cfw128_c2e4_manual_bbl(2800.,4.276)+cfw128_c2e4_manual_bbl(1060.,6.004),abs=1e-10)
    assert [(v.domain,v.inlet_md,v.outlet_md) for v in t.path]==[('injection',0.,2800.),('injection',2800.,3885.),('lower_annulus',3885.,2800.),('upper_pumping_annulus',2800.,0.)]
    assert t.mud_displaced_bbl>0. and not p.surface_cement_return_present
    assert p.pumping_state_toc_candidate_md is None and 'HOLD_CEMENT_REMAINS_IN_INJECTION' in p.reason_codes
    assert all(min(v.inlet_md,v.outlet_md)>2800. for v in t.occupancy if v.fluid=='Main')
    assert p.stages[0].retained_injection_bbl==pytest.approx(cfw128_c2e4_manual_bbl(25.,6.004),abs=1e-10)
    assert p.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'


def cfw128_c2e5_tapered_state(edge=674.):
    job='TIE BACK LNR 7"';table=hardware(('Previous Casing','800','9 5/8',8.535),('Previous Liner Shoe','700-1200','7',6.),
        ('Drill Pipes','200','5',4.276),('Drill Pipes','200-400','4 1/2',4.),('Tie Back Liner Shoe',f'400-{edge:g}','7',6.),
        ('Tie Back Liner Shoe',f'{edge:g}-700','6 1/2',5.8),('Open Hole Size','800-1200','8.5',8.5))
    state=project(job,table,1200.);state['placement_config']['host_row']=next(iter(hardware_choices(table,{'Previous Casing'})))
    state['placement_config']['target_row']=next(k for k,v in hardware_choices(table,target_descriptions(job)).items() if v['depth']==700.)
    return state


@pytest.mark.parametrize('case',['zero_top','previous_taper','taper_before','taper_at','taper_after','lap_cross'])
def test_cfw128_c2e5_special_endpoints_and_test_only_composition(case):
    state=synthetic_tieback(top=0. if case=='zero_top' else 676.) if case in ('zero_top','lap_cross') else r18c_tapered_state(100.) if case=='previous_taper' else cfw128_c2e5_tapered_state({'taper_before':674.,'taper_at':675.,'taper_after':676.}[case])
    state,g,d=cfw128_c2e5_inputs(state,names=('Main','Tail','Displacement Fluid'))
    e=cfw128_c2e5_test_composition(state,g,d)
    assert e['schedule'].stages[-1].volume_bbl==d.derived_displacement_bbl
    assert e['placement'].pumping_state_toc_candidate_md is None
    assert 'HOLD_CEMENT_REMAINS_IN_INJECTION' in e['placement'].reason_codes
    assert all(v.bottom_md<=g.captured_geometry.shoe_md for v in d.sections)


def test_cfw128_c2e5_small_trailing_spacer_does_not_invent_shoe_separation():
    state,g,d=cfw128_c2e5_inputs(bug01_geometry_case('CSG 13 3/8"'),('Main','Spacer Behind','Displacement Fluid'))
    state['fluids_config']['params']['Spacer Behind']['volume']=10.
    e=cfw128_c2e5_test_composition(state,g,d)
    assert 'HOLD_CEMENT_REMAINS_IN_INJECTION' in e['placement'].reason_codes
    assert 'HOLD_CEMENT_NOT_ANCHORED_AT_SHOE' not in e['placement'].reason_codes
    assert e['placement'].pumping_state_toc_candidate_md is None


def cfw128_c2e5_rebind_derived(d):
    from dataclasses import fields
    from project_state import fingerprint
    encoded=tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in d.sections)
    object.__setattr__(d,'projection_identity',fingerprint(['cfw128-c2e4-derived-displacement/1',d.app_source_sha,d.geometry_source_identity,d.geometry_projection_identity,d.job,d.kind,d.active_shoe_md,d.end_md,25.,encoded,d.derived_displacement_bbl,'NOMINAL_INTERNAL_STRING_CAPACITY','NONE_ADDED']))
    return d


@pytest.mark.parametrize('fault',['geometry_none','derived_none','numeric','sha','sibling','geometry_hash','derived_hash','derived_parent','derived_flags','geometry_nested_flags','endpoint','receiver_shoe','job','reserved','lost_section','section_id','section_rows','section_md','section_capacity','forged_total','nan','inf'])
def test_cfw128_c2e5_receipt_and_geometry_mutations_fail_closed(fault):
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=deepcopy(cfw128_c2e5_inputs());sha=C2D1_APP_SOURCE_SHA
    if fault=='geometry_none':g=None
    elif fault=='derived_none':d=None
    elif fault=='numeric':d=284.947218881107
    elif fault=='sha':sha='0'*40
    elif fault=='sibling':state2,g2,d2=cfw128_c2e5_inputs(bug01_geometry_case('LNR 7"'));d=d2
    elif fault=='geometry_hash':object.__setattr__(g,'source_identity','0'*64)
    elif fault=='derived_hash':object.__setattr__(d,'projection_identity','0'*64)
    elif fault=='derived_parent':object.__setattr__(d,'geometry_projection_identity','0'*64)
    elif fault=='derived_flags':object.__setattr__(d,'hydraulic_admissible',True)
    elif fault=='geometry_nested_flags':object.__setattr__(g.captured_geometry,'ready_to_run',True)
    elif fault=='endpoint':object.__setattr__(d,'end_md',3861.);cfw128_c2e5_rebind_derived(d)
    elif fault=='receiver_shoe':object.__setattr__(d,'active_shoe_md',4860.);object.__setattr__(d,'end_md',4835.);cfw128_c2e5_rebind_derived(d)
    elif fault=='job':object.__setattr__(d,'job','TIE BACK LNR 5"')
    elif fault=='reserved':object.__setattr__(d,'reserved_shoe_interval_m',0.)
    elif fault=='lost_section':object.__setattr__(d,'sections',d.sections[1:]);cfw128_c2e5_rebind_derived(d)
    elif fault=='section_id':object.__setattr__(d.sections[0],'internal_id_in',5.);cfw128_c2e5_rebind_derived(d)
    elif fault=='section_rows':object.__setattr__(d.sections[0],'source_rows',());cfw128_c2e5_rebind_derived(d)
    elif fault=='section_md':object.__setattr__(d.sections[1],'top_md',2801.);cfw128_c2e5_rebind_derived(d)
    elif fault=='section_capacity':object.__setattr__(d.sections[0],'capacity_bbl_per_m',1.);cfw128_c2e5_rebind_derived(d)
    elif fault=='forged_total':object.__setattr__(d,'derived_displacement_bbl',d.derived_displacement_bbl+1.);cfw128_c2e5_rebind_derived(d)
    elif fault in ('nan','inf'):object.__setattr__(d,'derived_displacement_bbl',float(fault))
    with pytest.raises((ValueError,TypeError)):build_effective_schedule(g,d,state,expected_app_source_sha=sha)


@pytest.mark.parametrize('fault',['no_mud_selection','duplicate','unknown','ineligible','wrong_job','nonmud_none','nonmud_zero','nonmud_negative','nonmud_bool','nonmud_nan','nonmud_inf','nonmud_string','missing_record','bad_record_stale','bad_density','mud_missing','mud_nan','mud_inf','mud_zero','mud_bool','overflow','precision_lost','bad_active','bad_params','bad_legacy','bad_well','mud_type_object'])
def test_cfw128_c2e5_invalid_selected_source_or_density_is_rejected(fault):
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=cfw128_c2e5_inputs()
    if fault=='no_mud_selection':state['fluids_config']['active'].remove('Displacement Fluid')
    elif fault=='duplicate':state['fluids_config']['active'].append('Main')
    elif fault=='unknown':state['fluids_config']['active'].append('Mud')
    elif fault=='ineligible':state['mud_type']='WBM';state['fluids_config']['active'].append('Diesel')
    elif fault=='wrong_job':state['job_type']='LNR 7"'
    elif fault.startswith('nonmud_'):state['fluids_config']['params']['Main']['volume']={'nonmud_none':None,'nonmud_zero':0.,'nonmud_negative':-1.,'nonmud_bool':True,'nonmud_nan':float('nan'),'nonmud_inf':float('inf'),'nonmud_string':'40'}[fault]
    elif fault=='missing_record':state['fluids_config']['params'].pop('Main')
    elif fault=='bad_record_stale':state['fluids_config']['params']['Main']=None;state['fluid_data']={'Main':{'volume':40.,'density':110.}}
    elif fault=='bad_density':state['fluids_config']['params']['Spacer']['density']='110-112'
    elif fault.startswith('mud_') and fault!='mud_type_object':state['mud_density']={'mud_missing':None,'mud_nan':float('nan'),'mud_inf':float('inf'),'mud_zero':0.,'mud_bool':True}[fault]
    elif fault=='overflow':state['fluids_config']['params']['Main']['volume']=1e308;state['fluids_config']['active'].append('Tail');state['fluids_config']['params']['Tail']={'volume':1e308,'density':110.}
    elif fault=='precision_lost':state['fluids_config']['params']['Main']['volume']=1e20
    elif fault=='bad_active':state['fluids_config']['active']='Main'
    elif fault=='bad_params':state['fluids_config']['params']=[]
    elif fault=='bad_legacy':state['fluid_data']=[]
    elif fault=='bad_well':state['well_data']=[]
    elif fault=='mud_type_object':state['mud_type']=True
    before=pickle.dumps(state)
    with pytest.raises((ValueError,TypeError)):build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.dumps(state)==before


def test_cfw128_c2e5_short_shoe_and_fresh_measured_id_changes():
    from cfw128_c2e4_derived_displacement import derive_displacement
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=cfw128_c2e5_inputs();r=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    changed=deepcopy(state);changed['hardware_table'].at[7,'ID (in)']=4.3
    fresh=cfw128_c2e_view(changed);nd=derive_displacement(fresh,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    with pytest.raises(ValueError):build_effective_schedule(fresh,d,changed,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    nr=build_effective_schedule(fresh,nd,changed,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert nr.stages[-1].volume_bbl!=r.stages[-1].volume_bbl and nr.source_identity!=r.source_identity
    short=project('CSG 9 5/8"',hardware(('Previous Casing','5','13 3/8',12.347),('Casing','25','9 5/8',8.535),('Open Hole Size','5-25','12.25',12.25)),25.)
    sg=cfw128_c2e_view(short);cfw128_c2e_fluids(short,('Main','Displacement Fluid'))
    with pytest.raises(ValueError):build_effective_schedule(sg,d,short,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


def test_cfw128_c2e5_immutable_replay_and_exact_stage_sum():
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    from dataclasses import replace,FrozenInstanceError
    from fractions import Fraction
    state,g,d=cfw128_c2e5_inputs();before=pickle.dumps((state,g,d));r=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.dumps((state,g,d))==before and pickle.loads(pickle.dumps(r))==r
    assert Fraction(*r.total_volume_exact_bbl)==sum((Fraction(v.volume_bbl) for v in r.stages),Fraction(0))
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(r,flag) is False
        with pytest.raises(ValueError):replace(r,**{flag:True})
    with pytest.raises(FrozenInstanceError):r.stages[0].volume_bbl=999.
    with pytest.raises(TypeError):r.stages[0]=r.stages[0]
    state['hardware_table'].at[7,'ID (in)']=4.3
    assert build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    assert r.currentness=='NOT_CURRENTNESS_PROOF' and r.hydraulics=='HYDRAULICS_NOT_EVALUATED' and r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'


def test_cfw128_c2e5_import_and_no_production_caller_isolation(monkeypatch):
    import ast,sys,subprocess
    from pathlib import Path
    root=Path('.');path=root/'cfw128_c2e5_effective_schedule.py'
    def verify():
        tree=ast.parse(path.read_text());names={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        assert names<={'dataclasses','fractions','math','re','typing','cement_chart_model','project_state','materials_db','engineering_tools'}
        assert not {'eval','exec','__import__','import_module','open'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        for other in root.glob('*.py'):
            if other==path:continue
            t=ast.parse(other.read_text());imports={n.module for n in ast.walk(t) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names}
            assert path.stem not in imports
    verify();original=Path.read_text
    for target,addition in ((path,'\nimport cfw128_c2e4_derived_displacement\n'),(root/'main.py','\nimport cfw128_c2e5_effective_schedule\n')):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:original(p,*a,**k)+addition if p==target else original(p,*a,**k))
            with pytest.raises(AssertionError):verify()
    forbidden={'cfw128_adapter','cfw128_c2d_geometry_view','cfw128_c2e_volume_tracking','cfw128_c2e2_cement_placement','cfw128_c2e3_post_pull_gap','cfw128_c2e4_derived_displacement','cfw128_er03_contract','cfw128_er03_boundary','cfw128_er03_volume','cfw128_hb_intake','cfw128_hb_numeric','cfw128_hb03t_frozen','scipy','pumping_simulation','fluids_charts_module_v1_4_2','streamlit','well_report','centralizer_optimizer_engine','cement_charts_engine'}
    subprocess.run([sys.executable,'-B','-W','error','-c','import sys,cfw128_c2e5_effective_schedule; assert not '+repr(forbidden)+' & set(sys.modules)'],check=True)


# C2e-6a: post-pull physical-closure diagnostics, no remapping law.
def cfw128_c2e6a_inputs(state=None,names=('Main','Displacement Fluid')):
    from cfw128_c2e3_post_pull_gap import audit_post_pull_gap
    state,g,d=cfw128_c2e5_inputs(state,names)
    evidence=cfw128_c2e5_test_composition(state,g,d)
    gap=audit_post_pull_gap(g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    return state,(g,gap,d,evidence['schedule'],evidence['tracking'],evidence['placement'])


def test_cfw128_c2e6a_new_closure_audit_is_not_a_final_toc():
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state,args=cfw128_c2e6a_inputs();r=audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.status=='DISABLED_POST_PULL_CLOSURE_AUDIT'
    assert r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'
    assert r.physical_remap_status=='HOLD_POST_PULL_PHYSICAL_REMAP_UNDEFINED'
    assert r.cement_inventory[0].injection_bbl>0.


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2e6a_eight_jobs_captured_compartments_and_physical_holds(job):
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state,args=cfw128_c2e6a_inputs(bug01_geometry_case(job),('Main','Lead','Tail','Spacer Behind','Displacement Fluid'))
    before=pickle.dumps((state,args));r=audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    g,b,d,s,t,p=args
    assert r.preserved_placement_holds==p.reason_codes
    assert r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'
    assert r.terminal_shoe_behavior=='HOLD_25M_TERMINAL_PLACEMENT_BEHAVIOR_UNDEFINED'
    assert [v.fluid for v in r.cement_inventory]==['Main','Lead','Tail']
    for v,old in zip(r.cement_inventory,p.stages):
        assert (v.actually_entered_bbl,v.injection_bbl,v.lower_annulus_bbl,v.upper_pumping_annulus_bbl,v.ideal_returned_bbl)==(old.entered_bbl,old.retained_injection_bbl,old.retained_lower_annulus_bbl,old.retained_upper_annulus_bbl,old.ideal_surface_returned_bbl)
        assert v.volume_authority=='ENTERED_PHASE_IV' and v.raw_entered_volume==40.
        assert v.actually_entered_bbl==pytest.approx(v.injection_bbl+v.lower_annulus_bbl+v.upper_pumping_annulus_bbl+v.ideal_returned_bbl,abs=1e-10)
    assert any(v.fluid=='Spacer Behind' for v in r.noncement_inventory)
    assert r.nominal_capacity_gap_bbl==b.capacity_gap_bbl
    if r.kind=='casing':
        assert r.gap_status=='NOT_APPLICABLE' and r.nominal_capacity_gap_bbl is None and not r.unresolved_decisions
    else:
        assert len(r.unresolved_decisions)==4 and r.physical_remap_status=='HOLD_POST_PULL_PHYSICAL_REMAP_UNDEFINED'
    assert pickle.dumps((state,args))==before


def test_cfw128_c2e6a_uat19_injection_cement_is_not_moved_by_post_pull_gap():
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state,args=cfw128_c2e6a_inputs();r=audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert (r.active_lap_md,r.active_shoe_md,r.displacement_end_md)==(2800.,3885.,3860.)
    assert r.derived_displacement_bbl==pytest.approx(284.947218881107,abs=1e-10)
    assert r.upper_pumping_capacity_bbl==pytest.approx(426.973186160669,abs=1e-10)
    assert r.upper_post_pull_capacity_bbl==pytest.approx(650.069776414482,abs=1e-10)
    assert r.nominal_capacity_gap_bbl==pytest.approx(223.096590253813,abs=1e-10)
    c=r.cement_inventory[0]
    assert c.injection_bbl==pytest.approx(cfw128_c2e4_manual_bbl(25.,6.004),abs=1e-10)
    assert c.lower_annulus_bbl>0. and c.upper_pumping_annulus_bbl==c.ideal_returned_bbl==0.
    assert r.ideal_initial_mud_returned_bbl>0. and not r.surface_cement_return_present
    assert 'HOLD_CEMENT_REMAINS_IN_INJECTION' in r.preserved_placement_holds
    assert all(max(a,b)<=3885. for i,a,b,v in r.initial_mud_occupancy)


@pytest.mark.parametrize('case',['zero','previous_taper','taper_before','taper_after','lap_cross'])
def test_cfw128_c2e6a_measured_tapers_zero_lap_and_endpoint(case):
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state=synthetic_tieback(top=0. if case=='zero' else 676.) if case in ('zero','lap_cross') else r18c_tapered_state(100.) if case=='previous_taper' else cfw128_c2e5_tapered_state(674. if case=='taper_before' else 676.)
    state,args=cfw128_c2e6a_inputs(state,('Main','Tail','Displacement Fluid'));r=audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.nominal_capacity_gap_bbl==args[1].capacity_gap_bbl
    assert r.preserved_placement_holds==args[-1].reason_codes
    assert r.displacement_end_md==r.active_shoe_md-25.
    if case=='zero':assert r.nominal_capacity_gap_bbl==0. and r.upper_pumping_capacity_bbl==0.


@pytest.mark.parametrize('fault',['missing','sha','sibling','gap_hash','gap_volume','derived_endpoint','derived_rows','schedule_hash','schedule_amount','schedule_flag','tracking_hash','occupancy','ledger','placement_hash','placement_partition','geometry_flag','nan','negative','path_rows'])
def test_cfw128_c2e6a_mutated_or_mixed_receipts_fail_closed(fault):
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state,args=deepcopy(cfw128_c2e6a_inputs());args=list(args);g,b,d,s,t,p=args;sha=C2D1_APP_SOURCE_SHA
    if fault=='missing':args[3]=None
    elif fault=='sha':sha='0'*40
    elif fault=='sibling':args[1]=cfw128_c2e6a_inputs(bug01_geometry_case('LNR 7"'))[1][1]
    elif fault=='gap_hash':object.__setattr__(b,'projection_identity','0'*64)
    elif fault=='gap_volume':object.__setattr__(b,'capacity_gap_bbl',b.capacity_gap_bbl+1.)
    elif fault=='derived_endpoint':object.__setattr__(d,'end_md',d.end_md+1.);cfw128_c2e5_rebind_derived(d)
    elif fault=='derived_rows':object.__setattr__(d.sections[0],'source_rows',());cfw128_c2e5_rebind_derived(d)
    elif fault=='schedule_hash':object.__setattr__(s,'source_identity','0'*64)
    elif fault=='schedule_amount':object.__setattr__(s.stages[0],'volume_bbl',41.)
    elif fault=='schedule_flag':object.__setattr__(s,'enabled',True)
    elif fault=='tracking_hash':object.__setattr__(t,'source_identity','0'*64)
    elif fault=='occupancy':object.__setattr__(t.occupancy[0],'volume_bbl',t.occupancy[0].volume_bbl+1.);cfw128_c2e2_rebind(t)
    elif fault=='ledger':object.__setattr__(t.ledgers[0],'in_path_bbl',39.);cfw128_c2e2_rebind(t)
    elif fault=='placement_hash':object.__setattr__(p,'projection_identity','0'*64)
    elif fault=='placement_partition':object.__setattr__(p.stages[0],'retained_injection_bbl',0.)
    elif fault=='geometry_flag':object.__setattr__(g.captured_geometry,'hydraulic_admissible',True)
    elif fault in ('nan','negative'):object.__setattr__(t.occupancy[0],'volume_bbl',float('nan') if fault=='nan' else -1.)
    elif fault=='path_rows':object.__setattr__(t.path[0],'running_source_rows',());cfw128_c2e2_rebind(t)
    with pytest.raises((ValueError,TypeError)):audit_post_pull_closure(*args,expected_app_source_sha=sha)


def test_cfw128_c2e6a_immutable_deterministic_replay_never_proves_currentness():
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    from dataclasses import FrozenInstanceError,replace
    state,args=cfw128_c2e6a_inputs();r=audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.loads(pickle.dumps(r))==r
    assert audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(r,flag) is False
        with pytest.raises(ValueError):replace(r,**{flag:True})
    with pytest.raises(FrozenInstanceError):r.cement_inventory[0].injection_bbl=0.
    state['hardware_table'].at[7,'ID (in)']=4.3
    assert audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    assert r.currentness=='NOT_CURRENTNESS_PROOF'


def test_cfw128_c2e6a_import_isolation_has_mutation_negative(monkeypatch):
    import ast,subprocess,sys
    from pathlib import Path
    root=Path('.');path=root/'cfw128_c2e6a_post_pull_closure.py'
    def verify():
        for file in root.glob('*.py'):
            tree=ast.parse(file.read_text());imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
            if file==path:
                assert imports<={'dataclasses','fractions','math','re','typing','cement_chart_model','engineering_tools','materials_db','project_state'}
                assert not {'eval','exec','__import__','import_module','open'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
            else:assert path.stem not in imports
    verify();original=Path.read_text
    for target,addition in ((path,'\nimport cfw128_c2e_volume_tracking\n'),(root/'main.py','\nimport cfw128_c2e6a_post_pull_closure\n')):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:original(p,*a,**k)+addition if p==target else original(p,*a,**k))
            with pytest.raises(AssertionError):verify()
    subprocess.run([sys.executable,'-B','-W','error','-c','import sys,cfw128_c2e6a_post_pull_closure; assert not any(n.startswith("cfw128") and n!="cfw128_c2e6a_post_pull_closure" for n in sys.modules)'],check=True)


def test_cfw128_c2e6a_partial_checkpoint_preserves_holds_and_actual_entered_amounts():
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from cfw128_c2e2_cement_placement import assess_cement_placement
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state,args=cfw128_c2e6a_inputs();g,b,d,s,t,p=args
    overlay=cfw128_c2e5_test_composition(state,g,d)['overlay']
    partial=preview_fluid_tracking(g,overlay,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=1)
    placement=assess_cement_placement(partial,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    r=audit_post_pull_closure(g,b,d,s,partial,placement,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.capture_completeness=='HOLD_SCHEDULE_INCOMPLETE'
    assert r.preserved_placement_holds==placement.reason_codes
    assert 'HOLD_SCHEDULE_INCOMPLETE' in r.preserved_placement_holds
    mud=next(v for v in r.noncement_inventory if v.fluid=='Displacement Fluid')
    assert mud.configured_bbl==d.derived_displacement_bbl and mud.actually_entered_bbl==0.
    assert r.cement_inventory[0].actually_entered_bbl==40.
    assert r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'


def test_cfw128_c2e6a_rehashed_placement_cannot_drop_precision_hold():
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    from dataclasses import fields
    from project_state import fingerprint
    state,args=cfw128_c2e6a_inputs(bug01_geometry_case('LNR 5"'),('Main','Lead','Tail','Spacer Behind','Displacement Fluid'))
    g,b,d,s,t,p=args
    assert 'HOLD_VOLUME_RECONCILIATION_PRECISION' in p.reason_codes
    object.__setattr__(p,'reason_codes',tuple(v for v in p.reason_codes if v!='HOLD_VOLUME_RECONCILIATION_PRECISION'))
    plain=lambda rows:tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)
    object.__setattr__(p,'projection_identity',fingerprint(['cfw128-c2e2-placement/1',C2D1_APP_SOURCE_SHA,g.source_identity,g.projection_identity,t.source_identity,t.projection_identity,plain(p.stages),plain(p.annular_intervals),p.other_fluid_occupancy,p.pumping_state_toc_candidate_md,p.reason_codes,p.post_pull_reason]))
    with pytest.raises(ValueError):audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


@pytest.mark.parametrize('fault',['missing_schedule_source','boolean_section_index','boolean_section_top','missing_no_cement_hold'])
def test_cfw128_c2e6a_continuation_receipt_types_and_all_inherited_holds(fault):
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    from dataclasses import fields
    from project_state import fingerprint
    names=('Displacement Fluid',) if fault=='missing_no_cement_hold' else ('Main','Displacement Fluid')
    state,args=cfw128_c2e6a_inputs(names=names);g,b,d,s,t,p=args
    plain=lambda rows:tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)
    if fault=='missing_schedule_source':
        object.__setattr__(s,'source_identity',None)
        object.__setattr__(s,'projection_identity',fingerprint(['cfw128-c2e5-effective-schedule/1',s.source_identity,plain(s.stages),s.total_volume_bbl,s.total_volume_exact_bbl,s.completion_basis]))
    elif fault=='boolean_section_index':object.__setattr__(d.sections[0],'source_section_index',False)
    elif fault=='boolean_section_top':object.__setattr__(d.sections[0],'top_md',False)
    else:
        assert 'HOLD_NO_PLACED_CEMENT' in p.reason_codes
        object.__setattr__(p,'reason_codes',tuple(v for v in p.reason_codes if v!='HOLD_NO_PLACED_CEMENT'))
        object.__setattr__(p,'projection_identity',fingerprint(['cfw128-c2e2-placement/1',C2D1_APP_SOURCE_SHA,g.source_identity,g.projection_identity,t.source_identity,t.projection_identity,plain(p.stages),plain(p.annular_intervals),p.other_fluid_occupancy,p.pumping_state_toc_candidate_md,p.reason_codes,p.post_pull_reason]))
    with pytest.raises((ValueError,TypeError)):audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


@pytest.mark.parametrize('case',['no_cement','ideal_cement_return'])
def test_cfw128_c2e6a_positive_no_cement_and_surface_return_never_resolve_remap(case):
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    names=('Displacement Fluid',) if case=='no_cement' else ('Main','Displacement Fluid')
    state,args=cfw128_c2e6a_inputs(names=names);g,b,d,s,t,p=args
    if case=='ideal_cement_return':
        state['fluids_config']['params']['Main']['volume']=1000.
        e=cfw128_c2e5_test_composition(state,g,d);s,t,p=e['schedule'],e['tracking'],e['placement']
    r=audit_post_pull_closure(g,b,d,s,t,p,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.preserved_placement_holds==p.reason_codes
    if case=='no_cement':
        assert not r.cement_inventory and not r.surface_cement_return_present
        assert 'HOLD_NO_PLACED_CEMENT' in r.preserved_placement_holds
    else:
        c=r.cement_inventory[0]
        assert c.configured_bbl==c.actually_entered_bbl==1000.
        assert c.ideal_returned_bbl>0. and r.surface_cement_return_present
        assert c.actually_entered_bbl==pytest.approx(c.injection_bbl+c.lower_annulus_bbl+c.upper_pumping_annulus_bbl+c.ideal_returned_bbl,abs=1e-10)
    assert len(r.unresolved_decisions)==4 and r.physical_remap_status=='HOLD_POST_PULL_PHYSICAL_REMAP_UNDEFINED'
    assert r.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'
