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
        else: assert 'cfw128_adapter' not in modules


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
