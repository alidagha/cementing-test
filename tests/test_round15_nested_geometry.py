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
        if path.name=='cfw128_integration_abi.py':
            gate2_assert_bridge_imports(path); continue
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
        if file.name=='cfw128_er03_numeric_adapter.py':gate3_assert_numeric_imports(file)
        elif file.name not in ('cfw128_hb_intake.py','cfw128_hb_numeric.py'):assert 'cfw128_hb_intake' not in imports
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
        if f.name=='cfw128_er03_numeric_adapter.py':gate3_assert_numeric_imports(f)
        elif f.name not in ('cfw128_hb03t_frozen.py','cfw128_hb_numeric.py'):
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
        if path.name=='cfw128_integration_abi.py':
            gate2_assert_bridge_imports(path); continue
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
        if path.name=='cfw128_integration_abi.py':
            gate2_assert_bridge_imports(path); continue
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
        if path.name=='cfw128_integration_abi.py':
            gate2_assert_bridge_imports(path); continue
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
        if other.name=='cfw128_integration_abi.py':
            gate2_assert_bridge_imports(other); continue
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
        if root.name=='cfw128_integration_abi.py':
            gate2_assert_bridge_imports(root); continue
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
            if other.name=='cfw128_c2e8_post_pull_review.py':
                batcha_assert_imports(other);continue
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
            if other.name=='cfw128_integration_abi.py':
                gate2_assert_bridge_imports(other); continue
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
            if other.name=='cfw128_integration_abi.py':
                gate2_assert_bridge_imports(other); continue
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


# C2e-6b: nominal dry-pipe ID Mud recovery versus new make-up, no remapping.
def cfw128_c2e6b_inputs(state=None,names=('Main','Displacement Fluid')):
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state,args=cfw128_c2e6a_inputs(state,names)
    closure=audit_post_pull_closure(*args,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    return state,args,closure


def test_cfw128_c2e6b_new_uat19_dry_pipe_ledger_requirement():
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    state,args,closure=cfw128_c2e6b_inputs();g,b,d,s,t,p=args
    result=audit_dry_pipe_makeup(g,b,closure,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert result.status=='DISABLED_DRY_PIPE_MUD_MAKEUP_AUDIT'
    assert result.removed_pipe_outer_displacement_bbl==pytest.approx(223.096590253813,abs=1e-10)
    assert result.drained_internal_mud_bbl==pytest.approx(163.165492848024,abs=1e-10)
    assert result.new_mud_makeup_bbl==pytest.approx(59.931097405789,abs=1e-10)
    assert result.new_mud_makeup_bbl!=d.derived_displacement_bbl
    assert result.final_toc=='NOT_EVALUATED' and result.currentness=='NOT_CURRENTNESS_PROOF'


def cfw128_c2e6b_rebind_closure(c):
    from dataclasses import fields
    from project_state import fingerprint
    plain=lambda rows:tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)
    object.__setattr__(c,'projection_identity',fingerprint(['cfw128-c2e6a-closure/1',c.app_source_sha,c.receipt_projection_identities,plain(c.cement_inventory),plain(c.noncement_inventory),c.initial_mud_remaining_bbl,c.ideal_initial_mud_returned_bbl,c.initial_mud_occupancy,c.preserved_placement_holds,c.inventory_evidence,c.capture_completeness,c.physical_remap_status,c.unresolved_decisions,'FINAL_POST_PULL_TOC_NOT_EVALUATED']))
    return c


def cfw128_c2e6b_rebind_gap(b):
    from dataclasses import fields
    from project_state import fingerprint
    plain=lambda rows:tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)
    object.__setattr__(b,'projection_identity',fingerprint(['cfw128-c2e3-geometric-gap/1',b.app_source_sha,b.geometry_source_identity,b.geometry_projection_identity,b.job,b.kind,b.lap_md,b.shoe_md,b.status,plain(b.slices),b.unchanged_injection_bbl,b.unchanged_lower_annulus_bbl,b.upper_pumping_bbl,b.upper_post_pull_bbl,b.capacity_gap_bbl,b.post_pull_fluid_boundary,b.displacement_volume_authority,b.other_pumped_volume_authority,b.currentness]))
    return b


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_c2e6b_eight_jobs_dp_only_sections_and_independent_steel_balance(job):
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    from cement_chart_model import _capacity
    state,args,c=cfw128_c2e6b_inputs(bug01_geometry_case(job),('Spacer','Main','Lead','Tail','Spacer Behind','Displacement Fluid'))
    g,b,d,s,t,p=args;before=pickle.dumps((state,args,c));r=audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.dumps((state,args,c))==before
    assert r.preserved_placement_holds==c.preserved_placement_holds==p.reason_codes
    assert r.preserved_closure_holds==c.unresolved_decisions
    assert r.original_pumping_displacement_bbl==d.derived_displacement_bbl and r.original_displacement_end_md==d.end_md
    if r.kind=='casing':
        assert r.status=='NOT_APPLICABLE' and not r.intervals
        assert r.removed_pipe_outer_displacement_bbl is r.drained_internal_mud_bbl is r.new_mud_makeup_bbl is r.independent_steel_volume_bbl is None
    else:
        assert r.status=='DISABLED_DRY_PIPE_MUD_MAKEUP_AUDIT'
        assert len(r.intervals)==len(b.slices)
        cursor=0.;manual_id=manual_od=manual_steel=0.
        for row,gap in zip(r.intervals,b.slices):
            assert row.top_md==cursor and row.bottom_md<=g.captured_geometry.string_top_md
            cursor=row.bottom_md
            original=next(v for v in g.captured_geometry.active_sections if v.top_md<=row.top_md and row.bottom_md<=v.bottom_md)
            assert original.description=='Drill Pipes'
            assert (row.internal_id_in,row.outer_od_in,row.source_rows,row.wall_source_rows)==(original.id_in,original.od_in,original.source_rows,gap.wall_source_rows)
            assert all(state['hardware_table'].iloc[i]['Description']=='Drill Pipes' for i in row.source_rows)
            length=row.bottom_md-row.top_md
            manual_id+=cfw128_c2e4_manual_bbl(length,row.internal_id_in)
            manual_od+=cfw128_c2e4_manual_bbl(length,row.outer_od_in)
            manual_steel+=cfw128_c2e4_manual_bbl(length,row.outer_od_in)-cfw128_c2e4_manual_bbl(length,row.internal_id_in)
            assert row.independent_steel_volume_bbl==length*_capacity(row.outer_od_in,row.internal_id_in)
            assert row.drained_internal_mud_bbl==length*_capacity(row.internal_id_in)
            assert row.removed_pipe_outer_displacement_bbl==gap.capacity_gap_bbl
            assert row.new_mud_makeup_bbl==gap.capacity_gap_bbl-row.drained_internal_mud_bbl>0.
            assert set(row.captured_mud_stages)<={'Mud','Displacement Fluid'} and row.captured_mud_stages
        assert cursor==g.captured_geometry.string_top_md
        assert r.drained_internal_mud_bbl==pytest.approx(manual_id,abs=1e-10)
        assert r.removed_pipe_outer_displacement_bbl==b.capacity_gap_bbl==pytest.approx(manual_od,abs=1e-10)
        assert r.new_mud_makeup_bbl==pytest.approx(manual_steel,abs=1e-10)
        assert r.removed_pipe_outer_displacement_bbl==pytest.approx(r.drained_internal_mud_bbl+r.new_mud_makeup_bbl,abs=1e-10)
        assert r.new_mud_makeup_bbl<r.removed_pipe_outer_displacement_bbl
        if '5"' in job or '4 1/2' in job:
            assert [(v.top_md,v.bottom_md) for v in r.intervals]==[(v[0],v[1]) for v in CFW128_C2E3_SEGMENTS[job]]
            assert len({v.wall_source_rows for v in r.intervals})==2


def test_cfw128_c2e6b_uat19_hand_check_does_not_move_25m_cement_or_double_count_mud():
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    state,args,c=cfw128_c2e6b_inputs();g,b,d,s,t,p=args;before=pickle.dumps((state,args,c))
    r=audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    od=cfw128_c2e4_manual_bbl(2800.,5.);internal=cfw128_c2e4_manual_bbl(2800.,4.276)
    assert r.removed_pipe_outer_displacement_bbl==pytest.approx(od,abs=1e-10)
    assert r.drained_internal_mud_bbl==pytest.approx(internal,abs=1e-10)
    assert r.new_mud_makeup_bbl==pytest.approx(od-internal,abs=1e-10)
    assert r.new_mud_makeup_bbl+r.drained_internal_mud_bbl==pytest.approx(223.096590253813,abs=1e-10)
    assert [(v.top_md,v.bottom_md,v.internal_id_in,v.outer_od_in,v.source_rows) for v in r.intervals]==[(0.,2800.,4.276,5.,(7,))]
    assert r.original_pumping_displacement_bbl==pytest.approx(284.947218881107,abs=1e-10) and r.original_displacement_end_md==3860.
    cement=c.cement_inventory[0]
    assert cement.actually_entered_bbl==40. and cement.injection_bbl==pytest.approx(2.872210519648,abs=1e-10)
    assert cement.lower_annulus_bbl==pytest.approx(37.127789480352,abs=1e-10) and cement.upper_pumping_annulus_bbl==cement.ideal_returned_bbl==0.
    assert r.active_shoe_md==3885. and c.initial_mud_remaining_bbl>0. and not c.surface_cement_return_present
    assert 'HOLD_CEMENT_REMAINS_IN_INJECTION' in r.preserved_placement_holds
    assert len(r.preserved_closure_holds)==4 and r.physical_remap_status=='HOLD_POST_PULL_FLUID_BOUNDARY_AND_TRANSFER_UNPROVEN'
    assert pickle.dumps((state,args,c))==before


@pytest.mark.parametrize('case',['zero','near_zero','sectional_dp','previous_taper'])
def test_cfw128_c2e6b_zero_lap_tapers_and_actual_piecewise_wall_provenance(case):
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    state=synthetic_tieback(top=0. if case=='zero' else .001) if case in ('zero','near_zero') else cfw128_c2e5_tapered_state(674.) if case=='sectional_dp' else r18c_tapered_state(100.)
    state,args,c=cfw128_c2e6b_inputs(state);g,b,d,s,t,p=args;r=audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    if case=='zero':
        assert not r.intervals and r.removed_pipe_outer_displacement_bbl==r.drained_internal_mud_bbl==r.new_mud_makeup_bbl==0.
    else:
        assert r.intervals[0].top_md==0. and r.intervals[-1].bottom_md==g.captured_geometry.string_top_md
        assert r.new_mud_makeup_bbl>0.
    if case=='sectional_dp':
        assert [(v.top_md,v.bottom_md,v.outer_od_in,v.internal_id_in) for v in r.intervals]==[(0.,200.,5.,4.276),(200.,400.,4.5,4.)]
    if case=='previous_taper':
        assert any(v.description=='Previous Tie Back Liner Shoe' for v in g.captured_geometry.installed_strings)
        assert len(r.intervals)>1 and len({v.wall_source_rows for v in r.intervals})>1


@pytest.mark.parametrize('field,value',[('ID (in)',4.3),('Size (in)','5 1/2')])
def test_cfw128_c2e6b_fresh_dp_id_and_od_edits_change_only_their_true_capacity_contributions(field,value):
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    state,args,c=cfw128_c2e6b_inputs();g,b,d,s,t,p=args;a=audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    changed=cfw128_c1_uat19_state();changed['hardware_table'].at[7,field]=value
    state2,args2,c2=cfw128_c2e6b_inputs(changed);g2,b2,d2,s2,t2,p2=args2
    z=audit_dry_pipe_makeup(g2,b2,c2,t2,s2,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert z.projection_identity!=a.projection_identity and z.geometry_source_identity!=a.geometry_source_identity
    if field=='ID (in)':
        assert z.removed_pipe_outer_displacement_bbl==a.removed_pipe_outer_displacement_bbl
        assert z.drained_internal_mud_bbl>a.drained_internal_mud_bbl and z.new_mud_makeup_bbl<a.new_mud_makeup_bbl
        assert d2.derived_displacement_bbl!=d.derived_displacement_bbl  # Fresh measured injection ID changes the separate original calculation too.
    else:
        assert z.removed_pipe_outer_displacement_bbl>a.removed_pipe_outer_displacement_bbl and z.new_mud_makeup_bbl>a.new_mud_makeup_bbl
        assert z.drained_internal_mud_bbl==a.drained_internal_mud_bbl and d2.derived_displacement_bbl==d.derived_displacement_bbl
    with pytest.raises((ValueError,TypeError)):audit_dry_pipe_makeup(g2,b,c2,t2,s2,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert a.original_pumping_displacement_bbl==d.derived_displacement_bbl


@pytest.mark.parametrize('fault',['geometry_none','gap_none','closure_none','tracking_none','schedule_none','wrong_sha','sibling_gap','sibling_closure','sibling_tracking','sibling_schedule','gap_hash','gap_total','gap_rows','gap_host','gap_boolean_MD','closure_hash','closure_parent','closure_stage','closure_inventory','closure_lost_hold','closure_empty_parent','closure_boolean','schedule_hash','schedule_stage','tracking_hash','tracking_volume','tracking_path_rows','tracking_density','geometry_flags','gap_flags','closure_flags','tracking_flags','schedule_flags','bad_ID','bad_OD','nan','inf','wrong_job'])
def test_cfw128_c2e6b_receipt_source_stage_and_deep_mutations_fail_closed(fault):
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    state,args,c=deepcopy(cfw128_c2e6b_inputs());g,b,d,s,t,p=args;values=[g,b,c,t,s];sha=C2D1_APP_SOURCE_SHA
    mapping={'geometry_none':0,'gap_none':1,'closure_none':2,'tracking_none':3,'schedule_none':4}
    if fault in mapping:values[mapping[fault]]=None
    elif fault=='wrong_sha':sha='0'*40
    elif fault.startswith('sibling_'):
        other,a2,c2=cfw128_c2e6b_inputs(bug01_geometry_case('LNR 7"'));g2,b2,d2,s2,t2,p2=a2
        index={'sibling_gap':1,'sibling_closure':2,'sibling_tracking':3,'sibling_schedule':4}[fault];values[index]=[g2,b2,c2,t2,s2][index]
    elif fault=='gap_hash':object.__setattr__(b,'projection_identity','0'*64)
    elif fault=='gap_total':object.__setattr__(b,'capacity_gap_bbl',b.capacity_gap_bbl+1.);cfw128_c2e6b_rebind_gap(b)
    elif fault=='gap_rows':object.__setattr__(b.slices[0],'running_source_rows',());cfw128_c2e6b_rebind_gap(b)
    elif fault=='gap_host':object.__setattr__(b.slices[0],'host_id_in',9.);cfw128_c2e6b_rebind_gap(b)
    elif fault=='gap_boolean_MD':object.__setattr__(b.slices[0],'top_md',False);cfw128_c2e6b_rebind_gap(b)
    elif fault=='closure_hash':object.__setattr__(c,'projection_identity','0'*64)
    elif fault=='closure_parent':object.__setattr__(c,'receipt_projection_identities',tuple((a,'0'*64 if a=='derived' else v) for a,v in c.receipt_projection_identities));cfw128_c2e6b_rebind_closure(c)
    elif fault=='closure_stage':object.__setattr__(c.cement_inventory[0],'stage_source_identity','0'*64);cfw128_c2e6b_rebind_closure(c)
    elif fault=='closure_inventory':object.__setattr__(c.cement_inventory[0],'injection_bbl',0.);cfw128_c2e6b_rebind_closure(c)
    elif fault=='closure_lost_hold':object.__setattr__(c,'preserved_placement_holds',());cfw128_c2e6b_rebind_closure(c)
    elif fault=='closure_empty_parent':object.__setattr__(c,'receipt_projection_identities',((),));cfw128_c2e6b_rebind_closure(c)
    elif fault=='closure_boolean':object.__setattr__(c.cement_inventory[0],'ideal_returned_bbl',False);cfw128_c2e6b_rebind_closure(c)
    elif fault=='schedule_hash':object.__setattr__(s,'source_identity','0'*64)
    elif fault=='schedule_stage':object.__setattr__(s.stages[0],'source_identity','0'*64)
    elif fault=='tracking_hash':object.__setattr__(t,'source_identity','0'*64)
    elif fault=='tracking_volume':object.__setattr__(t.occupancy[0],'volume_bbl',t.occupancy[0].volume_bbl+1.);cfw128_c2e2_rebind(t)
    elif fault=='tracking_path_rows':object.__setattr__(t.path[0],'running_source_rows',());cfw128_c2e2_rebind(t)
    elif fault=='tracking_density':object.__setattr__(t.stages[0],'raw_density',True)
    elif fault.endswith('_flags'):
        target={'geometry_flags':g.captured_geometry,'gap_flags':b,'closure_flags':c,'tracking_flags':t,'schedule_flags':s}[fault];object.__setattr__(target,'enabled',True)
    elif fault=='bad_ID':object.__setattr__(g.captured_geometry.active_sections[0],'id_in',0.)
    elif fault=='bad_OD':object.__setattr__(g.captured_geometry.active_sections[0],'od_in',g.captured_geometry.active_sections[0].id_in)
    elif fault in ('nan','inf'):object.__setattr__(g.captured_geometry.active_sections[0],'id_in',float(fault))
    elif fault=='wrong_job':object.__setattr__(g.captured_geometry,'job','LNR 7"')
    with pytest.raises((ValueError,TypeError)):audit_dry_pipe_makeup(*values,expected_app_source_sha=sha)


def test_cfw128_c2e6b_does_not_relabel_dp_cement_or_partial_schedule_as_drained_mud():
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    from cfw128_c2e_volume_tracking import preview_fluid_tracking
    from cfw128_c2e2_cement_placement import assess_cement_placement
    from cfw128_c2e6a_post_pull_closure import audit_post_pull_closure
    state,args,c=cfw128_c2e6b_inputs(synthetic_tieback(top=676.));g,b,d,s,t,p=args
    assert d.end_md==675.<g.captured_geometry.string_top_md
    assert any(o.fluid=='Main' and t.path[o.section_index].domain=='injection' and min(o.inlet_md,o.outlet_md)<676. for o in t.occupancy)
    with pytest.raises(ValueError,match='HOLD_DP_INTERNAL_MUD_NOT_PROVEN'):audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    state,args,c=cfw128_c2e6b_inputs();g,b,d,s,t,p=args;overlay=cfw128_c2e5_test_composition(state,g,d)['overlay']
    partial=preview_fluid_tracking(g,overlay,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=1)
    place=assess_cement_placement(partial,g,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    held=audit_post_pull_closure(g,b,d,s,partial,place,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    with pytest.raises(ValueError,match='HOLD_SOURCE_PUMPING_NOT_COMPLETE'):audit_dry_pipe_makeup(g,b,held,partial,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


def test_cfw128_c2e6b_source_roundoff_proof_cannot_mask_changed_capacity(monkeypatch):
    import cfw128_c2e6b_dry_pipe_mud_makeup as module
    state,args,c=cfw128_c2e6b_inputs();g,b,d,s,t,p=args;original=module._capacity
    monkeypatch.setattr(module,'_capacity',lambda a,z=0.:original(a,z)*1.01)
    with pytest.raises(ValueError):module.audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


def test_cfw128_c2e6b_frozen_serialization_replay_and_no_source_mutation():
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    from dataclasses import FrozenInstanceError,replace
    state,args,c=cfw128_c2e6b_inputs();g,b,d,s,t,p=args;before=pickle.dumps((state,args,c));r=audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.dumps((state,args,c))==before and pickle.loads(pickle.dumps(r))==r
    assert audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    for flag in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'):
        assert getattr(r,flag) is False
        with pytest.raises(ValueError):replace(r,**{flag:True})
    with pytest.raises(FrozenInstanceError):r.intervals[0].internal_id_in=5.
    with pytest.raises(TypeError):r.intervals[0]=r.intervals[0]
    state['hardware_table'].at[7,'ID (in)']=4.3
    assert audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    assert r.currentness=='NOT_CURRENTNESS_PROOF' and r.hydraulics==r.final_toc=='NOT_EVALUATED'


def test_cfw128_c2e6b_import_isolation_and_negative_runtime_caller_mutations(monkeypatch):
    import ast,subprocess,sys
    from pathlib import Path
    root=Path('.');path=root/'cfw128_c2e6b_dry_pipe_mud_makeup.py'
    def verify():
        for file in root.glob('*.py'):
            tree=ast.parse(file.read_text());imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
            if file==path:
                assert imports<={'dataclasses','fractions','math','re','typing','cement_chart_model','engineering_tools','materials_db','project_state'}
                assert not {'eval','exec','__import__','import_module','open'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
            else:assert path.stem not in imports
    verify();original=Path.read_text
    for target,addition in ((path,'\nimport cfw128_c2e6a_post_pull_closure\n'),(root/'main.py','\nimport cfw128_c2e6b_dry_pipe_mud_makeup\n')):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda f,*a,**k:original(f,*a,**k)+addition if f==target else original(f,*a,**k))
            with pytest.raises(AssertionError):verify()
    forbidden={'scipy','pumping_simulation','fluids_charts_module_v1_4_2','centralizer_optimizer_engine','cement_charts_engine','streamlit','well_report'}
    subprocess.run([sys.executable,'-B','-W','error','-c','import sys,cfw128_c2e6b_dry_pipe_mud_makeup; assert not any(n.startswith("cfw128") and n!="cfw128_c2e6b_dry_pipe_mud_makeup" for n in sys.modules); assert not '+repr(forbidden)+' & set(sys.modules)'],check=True)


@pytest.mark.parametrize('fault',['boolean_path_md','boolean_trajectory_md','boolean_gap_lap'])
def test_cfw128_c2e6b_boolean_numeric_metadata_is_not_an_equivalent_source_record(fault):
    from cfw128_c2e6b_dry_pipe_mud_makeup import audit_dry_pipe_makeup
    state,args,c=cfw128_c2e6b_inputs(synthetic_tieback(top=0.) if fault=='boolean_gap_lap' else None)
    g,b,d,s,t,p=args
    if fault=='boolean_path_md':object.__setattr__(t.path[0],'inlet_md',False)
    elif fault=='boolean_trajectory_md':
        assert t.trajectory[0][0]==0.
        object.__setattr__(t,'trajectory',((False,t.trajectory[0][1]),)+t.trajectory[1:])
    else:object.__setattr__(b,'lap_md',False)
    with pytest.raises((ValueError,TypeError)):audit_dry_pipe_makeup(g,b,c,t,s,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


# Gate 2: receipt-native composition; the prior overlay remains a test oracle only.
@pytest.mark.parametrize('job', BUG01_JOBS)
def test_cfw128_gate2_native_effective_schedule_matches_nominal_oracle(job):
    from cfw128_integration_abi import compose_nominal_tracking
    state,g,d=cfw128_c2e5_inputs(bug01_geometry_case(job))
    state['fluids_config']['params']['Main']['volume']=40.
    before=pickle.dumps(state)
    r=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    oracle=cfw128_c2e5_test_composition(state,g,d)
    assert r.status=='DISABLED_COMPOSITION_ONLY'
    assert r.schedule==oracle['schedule'] and r.geometry==g and r.displacement==d
    for name in ('path','occupancy','ledgers','mud_remaining_bbl','mud_displaced_bbl','trajectory'):
        assert getattr(r.tracking,name)==getattr(oracle['tracking'],name)
    assert r.tracking.stages==r.schedule.stages
    assert r.currentness=='NOT_CURRENTNESS_PROOF' and r.enabled is r.hydraulic_admissible is False
    assert pickle.dumps(state)==before


def gate2_assert_bridge_imports(path):
    """Owner's named bridge exception: exact static dependencies, no escape."""
    import ast
    expected={
        'cfw128_adapter':('snapshot_geometry','GeometrySnapshot'),
        'cfw128_er03_contract':('prepare_er03_preview',),
        'cfw128_er03_boundary':('assess_er03_boundary',),
        'cfw128_er03_volume':('audit_geometric_capacity',),
        'cfw128_c2d_geometry_view':('build_geometry_view','GeometryView'),
        'cfw128_c2e4_derived_displacement':('derive_displacement','DerivedDisplacement'),
        'cfw128_c2e5_effective_schedule':('build_effective_schedule','EffectiveSchedule'),
        'cfw128_c2e_volume_tracking':('preview_effective_schedule','TrackingPreview'),
    }
    tree=ast.parse(path.read_text());found={};count=0
    for n in ast.walk(tree):
        if isinstance(n,ast.ImportFrom) and (n.module or '').startswith('cfw128'):
            assert n.level==0 and all(a.asname is None for a in n.names)
            found[n.module]=tuple(a.name for a in n.names);count+=1
        if isinstance(n,ast.Import):assert not any(a.name.startswith('cfw128') for a in n.names)
    assert found==expected and count==len(expected)
    all_imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
    assert all_imports==set(expected)|{'copy','dataclasses','typing','math','project_state'}
    assert not {'eval','exec','__import__','import_module','open'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}


@pytest.mark.parametrize('fault',['sha','volume','density','derived_id','source','projection','stage_source','order','duplicate','flag','bool','nan','total'])
def test_cfw128_gate2_receipt_native_boundary_rejects_mutation(fault):
    from cfw128_c2e_volume_tracking import preview_effective_schedule
    from cfw128_c2e5_effective_schedule import build_effective_schedule
    state,g,d=cfw128_c2e5_inputs();r=build_effective_schedule(g,d,state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    r=deepcopy(r);stage=r.stages[0]
    if fault=='sha':object.__setattr__(r,'app_source_sha','f'*40)
    elif fault=='volume':object.__setattr__(stage,'volume_bbl',stage.volume_bbl+1)
    elif fault=='density':object.__setattr__(stage,'density_pcf',stage.density_pcf+1)
    elif fault=='derived_id':object.__setattr__(r,'derived_projection_identity','a'*64)
    elif fault in ('source','projection'):object.__setattr__(r,fault+'_identity','a'*64)
    elif fault=='stage_source':object.__setattr__(stage,'source_identity','a'*64)
    elif fault=='order':object.__setattr__(r,'stages',tuple(reversed(r.stages)))
    elif fault=='duplicate':object.__setattr__(r,'stages',(*r.stages,r.stages[-1]))
    elif fault=='flag':object.__setattr__(r,'enabled',True)
    elif fault=='bool':object.__setattr__(stage,'volume_bbl',True)
    elif fault=='nan':object.__setattr__(stage,'volume_bbl',float('nan'))
    else:object.__setattr__(r,'total_volume_exact_bbl',(1,1))
    with pytest.raises((ValueError,TypeError)):
        preview_effective_schedule(g,r,expected_app_source_sha=C2D1_APP_SOURCE_SHA,mud_type='WBM')


@pytest.mark.parametrize('fault',['empty','inactive','duplicate','negative','boolean','nan','overflow','wrong_host','draft','short_shoe'])
def test_cfw128_gate2_invalid_current_source_fails_closed(fault):
    from cfw128_integration_abi import compose_nominal_tracking
    state,g,d=cfw128_c2e5_inputs()
    if fault=='empty':state={}
    elif fault=='inactive':state['fluids_config']['active'].remove('Displacement Fluid')
    elif fault=='duplicate':state['fluids_config']['active'].append('Main')
    elif fault in ('negative','boolean','nan','overflow'):
        state['fluids_config']['params']['Main']['volume']={'negative':-1.,'boolean':True,'nan':float('nan'),'overflow':10**400}[fault]
    elif fault=='wrong_host':state['placement_config']['host_row']='retired'
    elif fault=='draft':state['hardware_editor_draft']=state['hardware_table'].copy();state['hardware_editor_draft'].at[0,'MD (m)']='999'
    else:state['hardware_table'].loc[state['hardware_table']['Description']=='Tie Back Liner Shoe','MD (m)']='25'
    before=pickle.dumps(state)
    with pytest.raises((ValueError,TypeError)):
        compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert pickle.dumps(state)==before


def test_cfw128_gate2_uat19_authorities_replay_and_numerical_holds():
    from cfw128_integration_abi import compose_nominal_tracking
    from dataclasses import FrozenInstanceError
    state,g,d=cfw128_c2e5_inputs();state['fluids_config']['params']['Main']['volume']=40.
    r=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert r.displacement.derived_displacement_bbl==pytest.approx(284.947218881107)
    assert r.displacement.end_md==3860. and r.captured_geometry.shoe_md==3885.
    cement=next(v for v in r.tracking.ledgers if v.fluid=='Main')
    injection=sum(o.volume_bbl for o in r.tracking.occupancy if o.fluid=='Main' and r.tracking.path[o.section_index].domain=='injection')
    assert injection==pytest.approx(2.872210519648)
    assert cement.entered_bbl==40. and cement.ideal_returned_bbl==0.
    assert r.tracking.mud_displaced_bbl>0 and cement.in_path_bbl==40.
    saved=deepcopy(state)
    for value in (None,False,'bad',float('nan'),99999.):
        state['fluids_config']['params']['Displacement Fluid']['volume']=value
        assert compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    state=deepcopy(saved);state['fluids_config']['params']['Main']['volume']=50.
    changed=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert next(v.volume_bbl for v in changed.schedule.stages if v.name=='Main')==50. and changed.tracking.occupancy!=r.tracking.occupancy
    assert compose_nominal_tracking(saved,expected_app_source_sha=C2D1_APP_SOURCE_SHA)==r
    assert r.currentness=='NOT_CURRENTNESS_PROOF'
    state=deepcopy(saved);state['fluids_config']['params']['Main'].update(pump_rate='7',material_name='source material')
    metadata=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    assert metadata.source_identity!=r.source_identity and metadata.tracking==r.tracking
    assert ('Main','pump_rate','7') in metadata.numerical_source_fields
    assert 'GATE3_NUMERICAL_RATE_MATERIAL_AND_RHEOLOGY_NOT_VALIDATED' in metadata.holds
    assert 'DOWNSTREAM_C2E2_AND_POST_PULL_CLOSURE_NOT_COMPOSED' in r.holds
    with pytest.raises(FrozenInstanceError):r.enabled=True
    assert pickle.loads(pickle.dumps(r))==r


@pytest.mark.parametrize('state',[synthetic_tieback(top=0.),synthetic_tieback(top=.001),r18c_tapered_state(100.)])
def test_cfw128_gate2_measured_special_geometry_and_stage_boundaries(state):
    from cfw128_integration_abi import compose_nominal_tracking
    state,g,d=cfw128_c2e5_inputs(state,('Main','Lead','Tail','Spacer Behind','Displacement Fluid'))
    full=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    zero=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,stage_end=0)
    assert zero.tracking.cumulative_injected_bbl==0. and all(v.fluid=='Mud' for v in zero.tracking.occupancy)
    assert full.tracking.path==zero.tracking.path
    assert [v.name for v in full.schedule.stages]==['Main','Lead','Tail','Spacer Behind','Displacement Fluid']
    assert max(v.bottom_md for v in full.geometry.injection)==full.captured_geometry.shoe_md


def test_cfw128_gate2_import_firewall_and_named_exception_mutations(monkeypatch):
    from pathlib import Path
    import ast,subprocess,sys
    bridge=Path('cfw128_integration_abi.py');gate2_assert_bridge_imports(bridge)
    for p in Path('.').glob('*.py'):
        if p==bridge:continue
        if p.name=='cfw128_c2e8_post_pull_review.py':
            batcha_assert_imports(p);continue
        if p.name=='cfw128_er03_numeric_adapter.py':
            gate3_assert_numeric_imports(p);continue
        if p.name=='cfw128_c2e7_native_placement.py':
            gate7_assert_imports(p);continue
        if p.name=='cfw128_shadow_word_bridge.py':
            gate8_assert_imports(p);continue
        tree=ast.parse(p.read_text())
        assert not any(isinstance(n,ast.ImportFrom) and n.module==bridge.stem or isinstance(n,ast.Import) and any(a.name==bridge.stem for a in n.names) for n in ast.walk(tree))
    read=Path.read_text
    for addition in ('\nimport cfw128_adapter\n','\nfrom cfw128_c2e_volume_tracking import preview_fluid_tracking\n','\nimport pumping_simulation\n'):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+addition if p==bridge else read(p,*a,**k))
            with pytest.raises(AssertionError):gate2_assert_bridge_imports(bridge)
    subprocess.run([sys.executable,'-B','-W','error','-c',
        'import sys,cfw128_integration_abi; assert not {"scipy","cfw128_hb03t_frozen","pumping_simulation","fluids_charts_module_v1_4_2","well_report"} & set(sys.modules)'],check=True)


@pytest.mark.parametrize('fault',['derived_volume','derived_row','derived_flag','sibling_geometry'])
def test_cfw128_gate2_fresh_chain_rejects_injected_derived_corruption(fault,monkeypatch):
    import cfw128_integration_abi as abi
    state,g,d=cfw128_c2e5_inputs();d=deepcopy(d)
    if fault=='derived_volume':object.__setattr__(d,'derived_displacement_bbl',d.derived_displacement_bbl+1)
    elif fault=='derived_row':object.__setattr__(d.sections[0],'source_rows',(999,))
    elif fault=='derived_flag':object.__setattr__(d,'hydraulic_admissible',True)
    else:object.__setattr__(d,'geometry_projection_identity','a'*64)
    monkeypatch.setattr(abi,'derive_displacement',lambda *a,**k:d)
    with pytest.raises((ValueError,TypeError)):abi.compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)


@pytest.mark.parametrize('mode',['legacy','canonical_bad','spacer_edit','geometry_edit','directional','unreviewed_lab'])
def test_cfw128_gate2_source_precedence_and_unassessed_lab(mode):
    from cfw128_integration_abi import compose_nominal_tracking
    state,g,d=cfw128_c2e5_inputs();r=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    if mode=='legacy':state['fluid_data']={'Main':state['fluids_config']['params'].pop('Main')}
    elif mode=='canonical_bad':state['fluid_data']={'Main':deepcopy(state['fluids_config']['params']['Main'])};state['fluids_config']['params']['Main']={}
    elif mode=='spacer_edit':state['fluids_config']['params']['Spacer']['volume']=60.
    elif mode=='geometry_edit':state['hardware_table'].loc[state['hardware_table']['Description']=='Drill Pipes','ID (in)']=4.2
    elif mode=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,90.],[6000.,60.,90.]],columns=['MD','Deviation','Azimuth'])}
    else:state['lab_qc_params']={'Main':{'reviewed':False}}
    before=pickle.dumps(state)
    if mode=='canonical_bad':
        with pytest.raises(ValueError):compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA)
    else:
        changed=compose_nominal_tracking(state,expected_app_source_sha=C2D1_APP_SOURCE_SHA,query_md=(50.,) if mode=='directional' else ())
        if mode=='legacy':assert next(v.record_source for v in changed.schedule.stages if v.name=='Main')=='fluid_data'
        elif mode=='spacer_edit':assert changed.tracking.occupancy!=r.tracking.occupancy
        elif mode=='geometry_edit':assert changed.displacement.derived_displacement_bbl!=r.displacement.derived_displacement_bbl and changed.source_identity!=r.source_identity
        elif mode=='directional':assert dict(changed.tracking.trajectory)[50.]==pytest.approx(47.7464829275686)
        else:assert changed==r and 'LAB_REVIEW_AND_INSTRUMENT_NOT_ASSESSED' in changed.holds
    assert pickle.dumps(state)==before


# Gate 3 is an isolated numerical test boundary, never an App execution lane.
GATE3_APP_SOURCE_SHA = '964a22c79a361fa2ff5dc9764b1917a44183f457'  # Independently verified Gate2 baseline.
def test_cfw128_gate3_new_typed_boundary_is_disabled():
    from cfw128_er03_numeric_adapter import NumericBoundary
    b=NumericBoundary('SYNTHETIC_TEST_ONLY',0.,None,0.,False,.2,0.,1.,'SURFACE_REFERENCE_PSI','TARGET_NOT_INCREMENT','FANN35_R1B1_SPRING1_SOFTWARE_CONVENTION_ONLY',(('Main',0.),('Displacement Fluid',0.),('Mud',0.)))
    assert b.evidence_class=='SYNTHETIC_TEST_ONLY'


def gate3_assert_numeric_imports(path):
    import ast
    tree=ast.parse(path.read_text())
    expected={'DOC58_SI_CANDIDATE_03_TF2R_ER03':'vertical','DOC58_G2D1_DIR_SCRATCH_01_ER03':'directional',
        'cfw128_er03_event_aligned_vertical':'event_vertical','cfw128_er03_event_aligned_directional':'event_directional'}
    actual=[(a.name,a.asname) for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
    assert sorted(actual)==sorted([*expected.items(),('math',None)])
    wanted={'copy':('deepcopy',),'dataclasses':('dataclass','field','fields'),'typing':('Literal',),'fractions':('Fraction',),
        'cfw128_integration_abi':('compose_nominal_tracking','CompositionReceipt'),
        'cfw128_hb_intake':('snapshot_lab_intake','LabIntakeSnapshot','DialReading','_dial','_duplicate_columns','_positional_source'),
        'cfw128_hb03t_frozen':('fit_full_hb','to_engine_field','InstrumentConfig'),
        'engineering_tools':('require_positive_pump_rate','validate_lab_rheology','lab_temperature_valid'),'centralizer_adapter':('_dynamic_fann',),'project_state':('fingerprint','spacer_lab_payload','phase7_lab_fluids','lab_source_signature','available_fluid_types'),'rheology':('RPM_ORDER','RHEOLOGY_DATASETS'),
        'fluids_charts_module_v1_4_2':('JobChartsSpec','autoscale_x','autoscale_y','render_three_charts')}
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert len(nodes)==len(wanted) and {n.module:tuple(a.name for a in n.names) for n in nodes}==wanted
    assert all(n.level==0 and all(a.asname is None for a in n.names) for n in nodes)
    assert not {'eval','exec','__import__','import_module','open'}&{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}


def gate3_case(base,job='CSG 9 5/8"'):
    # SYNTHETIC_TEST_ONLY source record + explicit test review, not field data.
    from project_state import lab_source_signature,mud_lab_source_signature
    from engineering_tools import lab_review_signature
    state=deepcopy(base);geometry=bug01_geometry_case(job)
    for key in ('job_type','hardware_table','placement_config','well_geometry'):state[key]=geometry[key]
    state['mud_density']='80';state['well_data']['mud_density']='80'
    state['fluids_config']={'active':['Main','Displacement Fluid'],'params':{
        'Main':{'volume':1.,'density':'118','pump_rate':'40','material_name':'Synthetic test cement'},
        'Displacement Fluid':{'volume':'ignored','density':'80','pump_rate':'40','material_name':'Synthetic test Mud'}}}
    dials=(45,37,27,22,16,9,8)
    qc=state['lab_qc_params']['Main'];qc['rheology']['bhct_down']['readings']={str(r):v for r,v in zip((300,200,100,60,30,6,3),dials)}
    state['lab_source_signatures']['Main']=lab_source_signature(state,'Main');qc['reviewed']=True
    qc['review_signature']=lab_review_signature(qc,state['lab_grid_dfs']['Main'])
    mud={'rheology':{'bhct_down':{'selected':True,'readings':{str(r):v for r,v in zip((300,200,100,60,30,6,3),dials)},'gel_10_sec':'-','gel_10_min':'-'}},'reviewed':True}
    state['lab_qc_params']['Displacement Fluid']=mud
    state['lab_source_signatures']['Displacement Fluid']=mud_lab_source_signature(state)
    mud['review_signature']=lab_review_signature(mud,None)
    # Explicit synthetic four-minute stages on an exact binary time grid.
    # These are test inputs, not an operational rate recommendation or adapter
    # correction. The original unaligned program remains a negative control.
    from cfw128_integration_abi import compose_nominal_tracking
    derived=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA).displacement
    state['fluids_config']['params']['Main']['pump_rate']=state['fluids_config']['params']['Main']['volume']/4.
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']=derived.derived_displacement_bbl/4.
    return state


def gate3_boundary(bhsp=None):
    from cfw128_er03_numeric_adapter import NumericBoundary
    return NumericBoundary('SYNTHETIC_TEST_ONLY',0.,bhsp,0.,False,.25,0.,1.,'SURFACE_REFERENCE_PSI','TARGET_NOT_INCREMENT','FANN35_R1B1_SPRING1_SOFTWARE_CONVENTION_ONLY',(('Main',0.),('Displacement Fluid',0.),('Mud',0.)))


@pytest.fixture(scope='module')
def gate3_numeric_source(bug01_reviewed_report_base):
    return gate3_case(bug01_reviewed_report_base)


@pytest.mark.parametrize('engine',['vertical','directional'])
def test_cfw128_gate3_typed_smoke_nonzero_yield_and_raw_series(gate3_numeric_source,engine):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from dataclasses import FrozenInstanceError
    state=deepcopy(gate3_numeric_source);before=pickle.dumps(state)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine=engine)
    assert r.status=='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED',r.holds
    assert r.app_source_sha==GATE3_APP_SOURCE_SHA
    assert len(r.time_min)==len(r.whp_kpsi)==len(r.total_pressure_kpsi)==len(r.q_out_bpm)>1
    assert all(math.isfinite(v) for name in ('whp_kpsi','pump_kpsi','hydrostatic_kpsi','total_pressure_kpsi','q_in_bpm','q_out_bpm') for v in getattr(r,name))
    assert r.pressure_station_md==1200. and dict(r.events)['t_eod']>0
    for f in r.fluids:
        assert f.tau_y_pa>0 and f.tau_y_field_lbf_100ft2==f.tau_y_pa/.47880259
        assert f.k_pa_s_n>0 and f.n_dimensionless>0 and f.instrument_provenance=='UNVERIFIED'
        assert f.tau_y_pa==pytest.approx(2.089010265509999,rel=1e-6)
    assert r.enabled is r.hydraulic_admissible is r.scientifically_qualified is False
    assert r.final_post_pull_toc=='NOT_EVALUATED' and r.currentness=='NOT_CURRENTNESS_PROOF'
    assert pickle.loads(pickle.dumps(r))==r and pickle.dumps(state)==before
    with pytest.raises(FrozenInstanceError):r.enabled=True


@pytest.mark.parametrize('fault',['rate','material','review','stale','rpm','yield_zero','density','datum','bhsp_increment','boolean_option','composition'])
def test_cfw128_gate3_input_holds_and_source_corruption(gate3_numeric_source,fault):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_integration_abi import compose_nominal_tracking
    from dataclasses import replace
    state=deepcopy(gate3_numeric_source);b=gate3_boundary();kwargs={}
    if fault=='rate':state['fluids_config']['params']['Main'].pop('pump_rate')
    elif fault=='material':state['fluids_config']['params']['Main'].pop('material_name')
    elif fault=='review':state['lab_qc_params']['Main']['reviewed']=False
    elif fault in ('stale','rpm','yield_zero'):
        row=state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']
        if fault=='stale':row['300']=46
        elif fault=='rpm':row.pop('3')
        else:
            from engineering_tools import lab_review_signature
            row.update({k:1 for k in row});qc=state['lab_qc_params']['Main'];qc['review_signature']=lab_review_signature(qc,state['lab_grid_dfs']['Main'])
    elif fault=='density':state['mud_density']=float('nan')
    elif fault=='datum':b=replace(b,pressure_datum='PSIA')
    elif fault=='bhsp_increment':b=replace(b,bhsp_semantics='INCREMENT')
    elif fault=='boolean_option':b=replace(b,dt_min=True)
    else:
        c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
        state['fluids_config']['params']['Main']['volume']=2.;kwargs['composition']=c
    before=pickle.dumps(state)
    if fault in ('density','datum','bhsp_increment','boolean_option','composition'):
        with pytest.raises((ValueError,TypeError)):run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,**kwargs)
    else:
        r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
        assert r.status=='HOLD' and r.time_min==()
    assert pickle.dumps(state)==before


def test_cfw128_gate3_directional_intermediate_tvd_is_explicit_hold(gate3_numeric_source):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    state=deepcopy(gate3_numeric_source)
    state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional')
    assert r.time_min and 'DIRECTIONAL_INTERIOR_TVD_CONVENTION_HOLD' not in r.holds
    assert r.directional_tvd_proof[0]=='APP_WELL_PROFILE_DERIVED_STATION_KNOTS'
    md,app,er03=r.tvd_comparison[0]
    assert md==50. and app==pytest.approx(47.7464829275686) and app!=pytest.approx(er03)


def test_cfw128_gate3_sources_and_static_import_firewall(monkeypatch):
    from pathlib import Path
    import ast,hashlib
    pins={'DOC58_SI_CANDIDATE_03_TF2R_ER03.py':'79d1a76962c706c305cf9a44ee58778d8ee2ca4231fd02f1a6d52f5b5f231e5f','DOC58_G2D1_DIR_SCRATCH_01_ER03.py':'2cd8896069327ba96fef4f22038bf70538dcc06b37e966b8bb58ad36ac39bd61'}
    for name,h in pins.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==h
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    import DOC58_G2D1_DIR_SCRATCH_01_ER03 as d
    assert d.JobDesign is v.JobDesign and d.Fluid is v.Fluid
    path=Path('cfw128_er03_numeric_adapter.py');gate3_assert_numeric_imports(path)
    for p in Path('.').glob('*.py'):
        if p==path:continue
        if p.name=='cfw128_c2e8_post_pull_review.py':
            batcha_assert_imports(p);continue
        if p.name=='cfw128_c2e7_native_placement.py':
            gate7_assert_imports(p);continue
        if p.name=='cfw128_shadow_word_bridge.py':
            gate8_assert_imports(p);continue
        nodes=ast.walk(ast.parse(p.read_text()));names={n.module for n in nodes if isinstance(n,ast.ImportFrom)}
        assert path.stem not in names
    read=Path.read_text
    for added in ('\nimport pumping_simulation\n','\nimport cfw128_adapter\n','\nfrom cfw128_hb03t_frozen import HBFitResult\n'):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+added if p==path else read(p,*a,**k))
            with pytest.raises(AssertionError):gate3_assert_numeric_imports(path)


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_gate3_canonical_job_geometry_admission(bug01_reviewed_report_base,job):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_integration_abi import compose_nominal_tracking
    state=gate3_case(bug01_reviewed_report_base,job)
    c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),composition=c)
    assert r.status=='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED',r.holds
    assert r.composition_projection_identity==c.projection_identity
    assert r.pressure_station_md==c.captured_geometry.shoe_md
    assert r.stages[-1][2]==c.displacement.derived_displacement_bbl
    assert r.stages[0][2]==1. and r.stages[0][4]==.25
    assert all(entered==observed for name,entered,observed,ratio in r.stage_volume_audit)
    # Frozen ER03 retains its own original conversion constant, never repinned
    # to App nominal bbl. Both measured paths have the same MD/ID topology.
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    expected=sum(math.pi/4*(p.id_in*.0254)**2/v.BBL_TO_M3*(p.bottom_md-p.top_md) for p in c.captured_geometry.active_sections)
    assert r.engine_injection_capacity_bbl==pytest.approx(expected,rel=1e-14)


def test_cfw128_gate3_bhsp_total_target_and_initial_mud_raw_channels(gate3_numeric_source,monkeypatch):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    original=v.simulate;observed={}
    def trace(job):
        observed['initial']=job.displacement_fluid
        observed['keys']=tuple(job.fluids)
        observed['raw']=original(job)
        return observed['raw']
    monkeypatch.setattr(v,'simulate',trace)
    from dataclasses import replace
    state=deepcopy(gate3_numeric_source)
    state['fluids_config']['params']['Main']['pump_rate']='40'
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']='40'
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=replace(gate3_boundary(5000.),dt_min=.2))
    assert r.status=='HOLD' and 'BHSP_TARGET_STATION_NOT_PROVED' in r.holds
    events=dict(r.events)
    assert events['bottom_shutin_psi']==5000. and events['t_shutin'] is not None
    mud=next(f for f in r.fluids if f.name=='Displacement Fluid')
    assert r.hydrostatic_kpsi[0]==pytest.approx(v.rho_si(mud.density_ppg)*v.G0*1200.*v.KPSI_PER_PA,rel=1e-12)
    assert events['whp_final_psi'] is not None
    assert r.q_in_bpm==tuple(observed['raw'].q_in) and r.q_out_bpm==tuple(observed['raw'].q_out)
    assert observed['initial']=='Mud' and {'Mud','Displacement Fluid'}<=set(observed['keys'])
    assert r.total_pressure_kpsi[-1]==observed['raw'].dyn[-1]
    assert r.total_pressure_kpsi[-1]*1000.!=pytest.approx(5000.,abs=1e-8)
    assert events['t_eod']==sum(stage[2]/stage[4] for stage in r.stages)


def test_cfw128_gate3_uat19_only_active_shoe_and_derived_displacement(bug01_reviewed_report_base):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from project_state import lab_source_signature
    from engineering_tools import lab_review_signature
    state=gate3_case(bug01_reviewed_report_base);geometry=cfw128_c1_uat19_state()
    for key in ('job_type','hardware_table','placement_config','well_geometry'):state[key]=geometry[key]
    state['fluids_config']['params']['Main']['volume']=40.
    state['lab_source_signatures']['Main']=lab_source_signature(state,'Main')
    state['lab_qc_params']['Main']['review_signature']=lab_review_signature(state['lab_qc_params']['Main'],state['lab_grid_dfs']['Main'])
    from cfw128_integration_abi import compose_nominal_tracking
    derived=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA).displacement
    state['fluids_config']['params']['Main']['pump_rate']=10.
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']=derived.derived_displacement_bbl/4.
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
    assert r.status=='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED' and r.pressure_station_md==3885.
    assert r.stages[-1][2]==pytest.approx(284.947218881107) and r.stages[0][2]==40.
    assert r.final_post_pull_toc=='NOT_EVALUATED'


@pytest.mark.parametrize('fault',['literal_zero_gate','true_gate','boolean_source_row'])
def test_cfw128_gate3_supplied_capture_requires_exact_primitive_identity(gate3_numeric_source,fault,monkeypatch):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_integration_abi import compose_nominal_tracking
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    c=deepcopy(compose_nominal_tracking(gate3_numeric_source,expected_app_source_sha=GATE3_APP_SOURCE_SHA))
    if fault=='literal_zero_gate':object.__setattr__(c.geometry,'ready_to_run',0)
    elif fault=='true_gate':object.__setattr__(c.schedule,'enabled',True)
    else:
        # In this fixture the actual first active source row is positional1;
        # bool True must never impersonate that numeric provenance index.
        part=c.captured_geometry.active_sections[0]
        assert part.source_rows==(1,)
        object.__setattr__(part,'source_rows',(True,))
    def forbidden(*a,**k):raise AssertionError('Unproved supplied capture reached numerical execution')
    monkeypatch.setattr(v,'simulate',forbidden)
    with pytest.raises((ValueError,TypeError)):
        run_numeric_test_case(gate3_numeric_source,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),composition=c)


@pytest.mark.parametrize('fault',['gel_missing','gel_duplicate','gel_boolean','gel_nan','gel_non_tuple','gel_initial_missing','option_overflow','bad_engine','bad_declaration'])
def test_cfw128_gate3_explicit_model_boundary_never_infers_missing_inputs(gate3_numeric_source,fault,monkeypatch):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from dataclasses import replace
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    b=gate3_boundary();kwargs={}
    if fault=='gel_missing':b=replace(b,gel_pa_by_fluid=())
    elif fault=='gel_duplicate':b=replace(b,gel_pa_by_fluid=(*b.gel_pa_by_fluid,b.gel_pa_by_fluid[0]))
    elif fault in ('gel_boolean','gel_nan'):b=replace(b,gel_pa_by_fluid=(('Main',True if fault=='gel_boolean' else float('nan')),*b.gel_pa_by_fluid[1:]))
    elif fault=='gel_non_tuple':b=replace(b,gel_pa_by_fluid=list(b.gel_pa_by_fluid))
    elif fault=='gel_initial_missing':b=replace(b,gel_pa_by_fluid=b.gel_pa_by_fluid[:-1])
    elif fault=='option_overflow':b=replace(b,dt_min=10**400)
    elif fault=='bad_engine':kwargs['engine']=False
    else:b=replace(b,evidence_class=True)
    def forbidden(*a,**k):raise AssertionError('Malformed boundary reached engine')
    monkeypatch.setattr(v,'simulate',forbidden)
    with pytest.raises((ValueError,TypeError)):
        run_numeric_test_case(gate3_numeric_source,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,**kwargs)


def test_cfw128_gate3_published_typed_abi_and_numeric_evidence(gate3_numeric_source,tmp_path):
    import json
    from dataclasses import fields,asdict
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    assert tuple(f.name for f in fields(v.FluidStageSpec))==('fluid_type','material_name','volume_bbl','density_pcf','rate_bpm','pv_cp','yp_lbf100ft2')
    assert tuple(f.name for f in fields(v.Fluid))==('name','rho_ppg','mu_p_cp','tau_y','n_pl','K_pl','gel_pa','frictionless_fluid')
    assert tuple(f.name for f in fields(v.JobDesign))==('geo','fluids','displacement_fluid','placement','back_pressure_psi','float_equipment','surface_line_kpsi_at_8bpm','dt_min','tail_cap_min','frictionless','bhsp_psi','shutin_ramp_min')
    assert tuple(f.name for f in fields(v.SimResult))==('t','whp','pump','hydro','dyn','q_in','q_out','t_atcp','t_eod','t_marker','t_freefall_start','t_freefall_end','final_hydro_kpsi','hydro0_kpsi','t_shutin','whp_final_psi','bottom_shutin_psi','diag')
    r=run_numeric_test_case(gate3_numeric_source,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
    assert r.status=='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED'
    for f in r.fluids:
        assert (f.tau_y_pa,f.k_pa_s_n,f.n_dimensionless)==pytest.approx((2.089010265509999,.7853358920369178,.5261585706020849),rel=1e-6,abs=1e-9)
    payload=asdict(r)
    assert all(payload[n] is False for n in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
    (tmp_path/'numeric_evidence.json').write_text(json.dumps(payload,indent=2,allow_nan=False))


@pytest.mark.parametrize('fluid',['Main','Displacement Fluid'])
@pytest.mark.parametrize('fault',['missing','unreviewed','stale','fraction','boolean','nonfinite','duplicate_rpm','wrong_ramp'])
def test_cfw128_gate3_each_seven_rpm_source_must_be_current(gate3_numeric_source,fluid,fault,monkeypatch):
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    state=deepcopy(gate3_numeric_source);qc=state['lab_qc_params'][fluid]
    if fault=='missing':state['lab_qc_params'].pop(fluid)
    elif fault=='unreviewed':qc['reviewed']=False
    elif fault=='stale':qc['rheology']['bhct_down']['readings']['300']=46
    elif fault=='wrong_ramp':qc['rheology']['bhct_up']=qc['rheology'].pop('bhct_down')
    else:
        readings=qc['rheology']['bhct_down']['readings']
        if fault=='duplicate_rpm':readings[300]=readings['300']
        else:readings['300']={'fraction':45.5,'boolean':True,'nonfinite':float('nan')}[fault]
    def forbidden(*a,**k):raise AssertionError('Missing/stale/malformed measurements reached numerical engine')
    monkeypatch.setattr(v,'simulate',forbidden)
    before=pickle.dumps(state)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
    assert r.status=='HOLD' and r.time_min==() and r.fluids==()
    assert any(code.startswith('LAB_SOURCE_HOLD:'+fluid+':') for code in r.holds)
    assert pickle.dumps(state)==before


def test_cfw128_gate3_fixed_time_step_cannot_silently_change_entered_volumes(gate3_numeric_source):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from dataclasses import replace
    state=deepcopy(gate3_numeric_source)
    # Retain the originally observed unaligned synthetic program verbatim.
    state['fluids_config']['params']['Main']['pump_rate']='40'
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']='40'
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=replace(gate3_boundary(),dt_min=.2))
    assert r.stages[0][2]==1.
    assert math.fsum(q*.2 for q in r.q_in_bpm)!=math.fsum(v[2] for v in r.stages)
    assert r.status=='HOLD' and 'FROZEN_TIMESTEP_STAGE_VOLUME_NOT_PROVED' in r.holds

    assert r.stage_volume_audit[0][1:3]==(1.,8.)


# Gate 4B: event stepping only; all inputs below are synthetic numerical probes.
def gate4b_job(v, *, dt=.2, tail=0., densities=(12.,15.8), float_on=False, volumes=(1.,2.345), rates=(40.,13.7)):
    fluids={'Mud':v.Fluid('Mud',densities[0],mu_p_cp=20.,tau_y=2.,n_pl=.7,K_pl=.5),
            'Main':v.Fluid('Main',densities[1],mu_p_cp=30.,tau_y=3.,n_pl=.7,K_pl=.6)}
    geo=v.GeometrySpec(td_m=1200.,track_depth_m=1200.,hole_id_in=8.5,pipe_od_in=5.,pipe_id_in=4.)
    stages=[v.FluidStageSpec(name,'SYNTHETIC_TEST_ONLY',vol,v.ppg_to_pcf(fluids[name].rho_ppg),rate)
            for name,vol,rate in zip(('Main','Mud'),volumes,rates)]
    return v.JobDesign(geo,fluids,'Mud',stages,dt_min=dt,tail_cap_min=tail,float_equipment=float_on)


@pytest.mark.parametrize('directional',[False,True])
def test_cfw128_gate4b_unaligned_executed_volume(directional):
    import cfw128_er03_event_aligned_vertical as v
    import cfw128_er03_event_aligned_directional as d
    job=gate4b_job(v)
    r=d.simulate(d.attach_survey(job,d.Survey.vertical(1200.))) if directional else v.simulate(job)
    rows=r.diag['event_intervals']
    for stage in job.placement:
        observed=math.fsum(q*duration for a,b,duration,name,q,qo,branch in rows if name==stage.fluid_type)
        assert observed==pytest.approx(stage.volume_bbl,rel=2e-14,abs=1e-14)
    assert r.diag['vol_audit']['qi_tot']==pytest.approx(3.345,rel=2e-14)
    assert rows[-1][2]==0 and rows[-1][4]==0
    assert all(0<z[2]<=job.dt_min for z in rows[:-1])
    assert all(a[1]==b[0] for a,b in zip(rows,rows[1:]))
    assert rows[-1][0]==r.t_eod


@pytest.mark.parametrize('dt,volumes,rates',[
    (.2,(1.,2.345),(40.,13.7)),(.025,(1.,2.345),(40.,13.7)),
    (.25,(1.,2.),(.25,.5)),(.2,(1e-11,1e-10),(40.,13.7)),
    (.2,(.1,.1),(40.,40.)),(.2,(0.,.123),(0.,13.7)),
    (.2,(8.,16.),(40.,40.)),(.2,(1.23456789,2.3456789),(7.3,13.7))])
def test_cfw128_gate4b_fractional_events_and_vertical_limit(dt,volumes,rates):
    import cfw128_er03_event_aligned_vertical as v
    import cfw128_er03_event_aligned_directional as d
    job=gate4b_job(v,dt=dt,volumes=volumes,rates=rates)
    a=v.simulate(job);b=d.simulate(d.attach_survey(job,d.Survey.vertical(1200.)))
    for name in ('t','whp','pump','hydro','dyn','q_in','q_out'):
        assert tuple(getattr(a,name))==tuple(getattr(b,name))
    rows=a.diag['event_intervals'];assert rows==b.diag['event_intervals']
    assert rows[-1][0]==a.t_eod and rows[-1][2]==0
    for st in job.placement:
        actual=math.fsum(row[4]*row[2] for row in rows if row[3]==st.fluid_type)
        assert actual==pytest.approx(st.volume_bbl,rel=3e-14,abs=1e-25)
    assert all(row[2]>=0 and row[2]<=dt for row in rows)


@pytest.fixture(scope='module')
def gate4b_flow_cases():
    import cfw128_er03_event_aligned_vertical as v
    results=[]
    for density in ((8.,18.),(18.,8.)):
        for float_on in (False,True):
            for rates in ((40.,13.7),(2.,40.)):
                job=gate4b_job(v,dt=.2,tail=.35,densities=density,float_on=float_on,volumes=(250.,250.),rates=rates)
                results.append((job,v.simulate(job)))
    return results


def test_cfw128_gate4b_all_transport_duration_ledgers(gate4b_flow_cases):
    branches=set()
    for job,r in gate4b_flow_cases:
        rows=r.diag['event_intervals'];a=r.diag['vol_audit'];branches.update(z[6] for z in rows)
        assert all(0<=z[2]<=job.dt_min and z[1]<=r.t_eod+job.tail_cap_min for z in rows)
        assert all(x[1]==y[0] for x,y in zip(rows,rows[1:]))
        assert all(math.isfinite(x) and x>=0 for x in (a['Cp_end'],a['Ca_end'],a['gap_end']))
        assert a['Cp_end']+a['gap_end']==pytest.approx(a['V_pipe0'],abs=1e-9)
        assert a['qi_tot']==pytest.approx(500.,abs=1e-9)
        assert a['qi_tot']==pytest.approx(math.fsum(z[4]*z[2] for z in rows),abs=1e-9)
        assert a['qo_tot']==pytest.approx(math.fsum(z[5]*z[2] for z in rows),abs=1e-9)
        assert max(map(abs,a['leak_bbl'].values()))<1e-9
        assert max(map(abs,a['dres_pipe_bbl'].values()))<1e-9
    assert {'normal','freefall','ffrefill','freeex','tail_ff','tail_rev'}<=branches,branches


@pytest.mark.parametrize('engine',['vertical','directional'])
def test_cfw128_gate4b_explicit_adapter_preserves_default_and_holds(gate3_numeric_source,engine):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from dataclasses import replace,fields
    state=deepcopy(gate3_numeric_source);before=pickle.dumps(state)
    state['fluids_config']['params']['Main']['pump_rate']='40'
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']='40'
    changed=pickle.dumps(state);b=replace(gate3_boundary(),dt_min=.2)
    old=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine=engine)
    new=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine=engine,stepping='event_aligned_test_only')
    assert old.stage_volume_audit[0][1:3]==(1.,8.) and old.engine==engine
    assert new.stage_volume_audit[0][1:3]==(1.,1.)
    assert all(a==pytest.approx(o,rel=2e-14) for name,a,o,ratio in new.stage_volume_audit)
    assert new.engine=='event_aligned_'+engine and new.source_identity!=old.source_identity
    assert len(new.source_hashes)==5 and new.fluids==old.fluids
    assert 'EVENT_ALIGNED_TEST_ONLY' in new.holds
    assert all(getattr(new,f.name) is False for f in fields(new) if f.name in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
    assert pickle.dumps(state)==changed and changed!=before
    with pytest.raises(ValueError):run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping='automatic')
    directional=deepcopy(state);directional['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    held=run_numeric_test_case(directional,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine='directional',stepping='event_aligned_test_only')
    assert held.time_min and 'DIRECTIONAL_INTERIOR_TVD_CONVENTION_HOLD' not in held.holds
    pressure=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=replace(b,bhsp_target_psi=5000.),engine=engine,stepping='event_aligned_test_only')
    assert 'BHSP_TARGET_STATION_NOT_PROVED' in pressure.holds


@pytest.mark.parametrize('engine',['vertical','directional'])
@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_gate4b_eight_job_admission_and_source_hold(bug01_reviewed_report_base,engine,job):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    state=gate3_case(bug01_reviewed_report_base,job);before=pickle.dumps(state)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine=engine,stepping='event_aligned_test_only')
    assert r.status=='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED',r.holds
    assert all(entered==pytest.approx(observed,rel=2e-14) for name,entered,observed,ratio in r.stage_volume_audit)
    assert r.final_post_pull_toc=='NOT_EVALUATED' and r.currentness=='NOT_CURRENTNESS_PROOF'
    assert pickle.dumps(state)==before
    state['lab_qc_params']['Main']['reviewed']=False
    hold=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine=engine,stepping='event_aligned_test_only')
    assert hold.status=='HOLD' and hold.time_min==()


def test_cfw128_gate4b_aligned_frozen_channels_and_terminal_observation():
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as original
    import cfw128_er03_event_aligned_vertical as derivative
    a=original.simulate(gate4b_job(original,dt=.25,volumes=(1.,2.),rates=(.25,.5)))
    b=derivative.simulate(gate4b_job(derivative,dt=.25,volumes=(1.,2.),rates=(.25,.5)))
    for name in ('t','whp','pump','hydro','dyn','q_in','q_out'):
        assert tuple(getattr(a,name))==tuple(getattr(b,name))
    assert b.diag['vol_audit']['branch_min']['tail_bal']==0
    assert a.diag['vol_audit']['branch_min']['tail_bal']==.25
    assert b.diag['event_intervals'][-1][2]==0


def gate4b_assert_sources_and_firewall():
    from pathlib import Path
    import ast,hashlib
    pins={'cfw128_er03_event_aligned_vertical.py':'35452adbe71c0285baea95ea8e73464cfb47c721ec3a3c39cda7b48ee8230dbf',
          'cfw128_er03_event_aligned_directional.py':'d944f5c5daf1356564f40ac7d2efc3289c0ccdc5a80c8501af2147756df7d24f'}
    parents=('DOC58_SI_CANDIDATE_03_TF2R_ER03.py','DOC58_G2D1_DIR_SCRATCH_01_ER03.py')
    for (name,pin),parent in zip(pins.items(),parents):
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==pin
        before=ast.parse(Path(parent).read_text());after=ast.parse(Path(name).read_text())
        for tree in (before,after):
            tree.body=[n for n in tree.body if not isinstance(n,ast.FunctionDef) or n.name!='simulate']
        if 'directional' in name:
            node=next(n for n in after.body if isinstance(n,ast.ImportFrom) and n.module=='cfw128_er03_event_aligned_vertical')
            node.module='DOC58_SI_CANDIDATE_03_TF2R_ER03'
        assert ast.dump(before)==ast.dump(after)
    permitted={'cfw128_er03_numeric_adapter.py':set(pins),'cfw128_er03_event_aligned_directional.py':{'cfw128_er03_event_aligned_vertical.py'}}
    for path in Path('.').glob('*.py'):
        tree=ast.parse(path.read_text());imports={a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        imports.update(n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom))
        used={f for f in pins if f[:-3] in imports}
        assert used<=permitted.get(path.name,set())
    gate3_assert_numeric_imports(Path('cfw128_er03_numeric_adapter.py'))


def test_cfw128_gate4b_source_law_and_import_mutation_negatives(monkeypatch):
    from pathlib import Path
    gate4b_assert_sources_and_firewall()
    raw=Path.read_bytes;read=Path.read_text
    for name in ('cfw128_er03_event_aligned_vertical.py','cfw128_er03_event_aligned_directional.py'):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_bytes',lambda p,*a,**k:raw(p,*a,**k).replace(b'step_dt',b'dt',1) if p.name==name else raw(p,*a,**k))
            with pytest.raises(AssertionError):gate4b_assert_sources_and_firewall()
    for target,added in (('main.py','\nimport cfw128_er03_event_aligned_vertical\n'),('cfw128_er03_numeric_adapter.py','\nimport pumping_simulation\n')):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+added if p.name==target else read(p,*a,**k))
            with pytest.raises(AssertionError):gate4b_assert_sources_and_firewall()


# Gate 4C is source admission only; these fixtures reuse real source authorities.
def gate4c_spacer_source(base):
    from test_round13a_a2_spacer_lab import state as spacer_state, measured
    from project_state import refresh_spacer_lab
    from engineering_tools import lab_review_signature
    state=deepcopy(base);fixture=measured(spacer_state('Barite'))
    state['standalone_spacer_config']=fixture['standalone_spacer_config']
    state['fluids_config']['active'].insert(0,'Spacer')
    state['fluids_config']['params']['Spacer']=deepcopy(fixture['fluids_config']['params']['Spacer'])
    state['fluids_config']['params']['Spacer']['pump_rate']=5.
    refresh_spacer_lab(state)
    qc=deepcopy(fixture['lab_qc_params']['Spacer'])
    qc['rheology']['bhct_down']['readings']={str(r):str(v) for r,v in zip((300,200,100,60,30,6,3),(55,45,33,26,20,11,9))}
    qc['reviewed']=True;state['lab_qc_params']['Spacer']=qc
    qc['review_signature']=lab_review_signature(qc,state['lab_grid_dfs']['Spacer'])
    return state


@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
def test_cfw128_gate4c_reviewed_spacer_new_admission(gate3_numeric_source,stepping):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from dataclasses import replace
    state=gate4c_spacer_source(gate3_numeric_source);before=pickle.dumps(state)
    b=replace(gate3_boundary(),gel_pa_by_fluid=(*gate3_boundary().gel_pa_by_fluid,('Spacer',0.)))
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping=stepping)
    assert r.status=='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED',r.holds
    assert [f.name for f in r.fluids]==['Spacer','Main','Displacement Fluid']
    assert dict(r.fluids[0].raw_readings)[300]=='55'
    assert r.fluids[0].tau_y_pa>0 and r.fluids[0].tau_y_pa!=r.fluids[1].tau_y_pa
    assert pickle.dumps(state)==before


@pytest.mark.parametrize('fault',['missing','review','fake_review','signature','grid','composition','temperature','wrong_ramp','duplicate_rpm','missing_rpm','bool','fraction','negative','nan','instrument','duplicate_columns'])
def test_cfw128_gate4c_spacer_source_fails_closed(gate3_numeric_source,fault):
    from cfw128_er03_numeric_adapter import _stage_lab_intake
    state=gate4c_spacer_source(gate3_numeric_source);qc=state['lab_qc_params']['Spacer']
    raw=qc['rheology']['bhct_down']['readings']
    if fault=='missing':state['lab_qc_params'].pop('Spacer')
    elif fault=='review':qc['reviewed']=False
    elif fault=='fake_review':qc['reviewed']=1
    elif fault=='signature':state['lab_source_signatures']['Spacer']='stale'
    elif fault=='grid':state['lab_grid_dfs']['Spacer'].iloc[0,0]='changed'
    elif fault=='composition':state['fluids_config']['params']['Spacer']['density']='111'
    elif fault=='temperature':state['well_data']['bhct']=1.
    elif fault=='wrong_ramp':qc['rheology']['surface_down']=qc['rheology'].pop('bhct_down')
    elif fault=='duplicate_rpm':raw[300]=55
    elif fault=='missing_rpm':raw.pop('3')
    elif fault=='instrument':qc['instrument_provenance']='VERIFIED'
    elif fault=='duplicate_columns':state['lab_grid_dfs']['Spacer'].columns=['Material','Material','Unit','Mass','Lot No']
    else:raw['300']={'bool':True,'fraction':55.5,'negative':-1,'nan':float('nan')}[fault]
    before=pickle.dumps(state);r=_stage_lab_intake(state,'Spacer',GATE3_APP_SOURCE_SHA)
    assert r.status!='CAPTURED_FOR_FUTURE_REVIEW' and r.readings==()
    assert r.instrument_provenance=='UNVERIFIED' and pickle.dumps(state)==before


@pytest.mark.parametrize('name',['Diesel','Pre Flush','Spacer Ahead','Spacer Behind'])
@pytest.mark.parametrize('fault',['intact','absent','unselected','fraction','duplicate','boolean','negative','nonfinite','fake_review'])
def test_cfw128_gate4c_unsupported_review_authorities_are_holds(gate3_numeric_source,name,fault):
    from cfw128_er03_numeric_adapter import _stage_lab_intake
    state=deepcopy(gate3_numeric_source);state['mud_type']='OBM';state['fluids_config']['active'].insert(0,name)
    raw={str(r):v for r,v in zip((300,200,100,60,30,6,3),(55,45,33,26,20,11,9))}
    qc={'rheology':{'bhct_down':{'selected':True,'readings':raw,'gel_10_sec':'-','gel_10_min':'-'}}}
    if name in ('Diesel','Pre Flush'):state['lab_qc_params'][name]=qc
    else:state.setdefault('centralizer_config',{}).setdefault('aux_rheology',{})[name]=raw
    if fault=='absent':raw.clear()
    elif fault=='unselected':qc['rheology']['bhct_down']['selected']=False
    elif fault=='duplicate':raw[300]=55
    elif fault=='fake_review':qc.update(reviewed=True,review_signature='forged')
    elif fault not in ('intact',):raw['300']={'fraction':55.5,'boolean':True,'negative':-1,'nonfinite':float('nan')}[fault]
    before=pickle.dumps(state);r=_stage_lab_intake(state,name,GATE3_APP_SOURCE_SHA)
    valid=fault=='intact' or name in ('Spacer Ahead','Spacer Behind') and fault in ('unselected','fake_review')
    if valid:
        assert r.status=='CAPTURED_FOR_FUTURE_REVIEW' and len(r.readings)==7
        assert r.operator_review=='NOT_ASSERTED' and r.fit_reviewed is False
    else:
        assert r.status!='CAPTURED_FOR_FUTURE_REVIEW' and not r.readings
    assert pickle.dumps(state)==before


def test_cfw128_gate4c_current_preflush_never_falls_back_and_aux_names_do_not_share(gate3_numeric_source):
    from cfw128_er03_numeric_adapter import _stage_lab_intake
    state=deepcopy(gate3_numeric_source);state['fluids_config']['active']+=['Pre Flush','Spacer Ahead','Spacer Behind']
    raw={str(r):v for r,v in zip((300,200,100,60,30,6,3),(55,45,33,26,20,11,9))}
    state['centralizer_config']={'aux_rheology':{'Pre Flush':raw,'Spacer Ahead':deepcopy(raw)}}
    legacy=_stage_lab_intake(state,'Pre Flush',GATE3_APP_SOURCE_SHA);assert legacy.status=='CAPTURED_FOR_FUTURE_REVIEW' and legacy.actual_ramp=='UNKNOWN'
    state['lab_qc_params']['Pre Flush']={}
    current=_stage_lab_intake(state,'Pre Flush',GATE3_APP_SOURCE_SHA);assert current.reason_codes==('BHCT_DOWN_NOT_SELECTED',)
    state['centralizer_config']['aux_rheology']['Pre Flush']['300']=999
    assert _stage_lab_intake(state,'Pre Flush',GATE3_APP_SOURCE_SHA)==current
    ahead=_stage_lab_intake(state,'Spacer Ahead',GATE3_APP_SOURCE_SHA)
    behind=_stage_lab_intake(state,'Spacer Behind',GATE3_APP_SOURCE_SHA)
    assert ahead.status=='CAPTURED_FOR_FUTURE_REVIEW' and ahead.operator_review=='NOT_ASSERTED' and behind.reason_codes==('AUXILIARY_SOURCE_MISSING',)
    assert ahead.source_identity!=behind.source_identity


@pytest.mark.parametrize('name',['Scavenger','Main','Lead','Lead #1','Lead #2','Tail'])
def test_cfw128_gate4c_each_formulation_uses_own_existing_review(gate3_numeric_source,name):
    from cfw128_er03_numeric_adapter import _stage_lab_intake
    from project_state import lab_source_signature
    from engineering_tools import lab_review_signature
    state=deepcopy(gate3_numeric_source)
    if name!='Main':
        state['fluids_config']['active'].insert(0,name)
        for key in ('cement_params','fluid_data','cement_additives_dfs','lab_grid_dfs','lab_qc_params'):
            state[key][name]=deepcopy(state[key]['Main'])
    qc=state['lab_qc_params'][name];qc['rheology']['bhct_down']['readings']['300']=46
    state['lab_source_signatures'][name]=lab_source_signature(state,name)
    qc['review_signature']=lab_review_signature(qc,state['lab_grid_dfs'][name])
    r=_stage_lab_intake(state,name,GATE3_APP_SOURCE_SHA)
    assert r.status=='CAPTURED_FOR_FUTURE_REVIEW' and r.readings[0].dial==46
    assert r.fluid_name==name and r.instrument_provenance=='UNVERIFIED'
    qc['rheology']['bhct_down']['readings']['300']=47
    assert _stage_lab_intake(state,name,GATE3_APP_SOURCE_SHA).status=='STALE_REVIEW'


def test_cfw128_gate4c_spacer_source_identity_and_bingham_are_read_only(gate3_numeric_source):
    from cfw128_er03_numeric_adapter import _stage_lab_intake
    from engineering_tools import build_lab_rheology,lab_review_signature
    state=gate4c_spacer_source(gate3_numeric_source);qc=state['lab_qc_params']['Spacer']
    before=build_lab_rheology(qc,'Spacer');r=_stage_lab_intake(state,'Spacer',GATE3_APP_SOURCE_SHA)
    state['lab_qc_params']['inactive']={'anything':float('nan')}
    assert _stage_lab_intake(state,'Spacer',GATE3_APP_SOURCE_SHA)==r
    assert build_lab_rheology(qc,'Spacer')==before
    qc['rheology']['bhct_down']['readings']['300']='56'
    stale=_stage_lab_intake(state,'Spacer',GATE3_APP_SOURCE_SHA)
    assert stale.status=='STALE_REVIEW' and stale.source_identity!=r.source_identity
    qc['review_signature']=lab_review_signature(qc,state['lab_grid_dfs']['Spacer'])
    fresh=_stage_lab_intake(state,'Spacer',GATE3_APP_SOURCE_SHA)
    assert fresh.status=='CAPTURED_FOR_FUTURE_REVIEW' and fresh.source_identity not in (r.source_identity,stale.source_identity)


@pytest.mark.parametrize('name',['Diesel','Pre Flush','Spacer Ahead','Spacer Behind'])
@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
def test_cfw128_gate4c_public_boundary_holds_unreviewed_stages(gate3_numeric_source,name,stepping,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    from dataclasses import replace
    state=deepcopy(gate3_numeric_source);state['mud_type']='OBM'
    state['fluids_config']['active'].insert(0,name)
    state['fluids_config']['params'][name]={'volume':1.,'density':52. if name=='Diesel' else 80.,'pump_rate':.25,'material_name':'Diesel' if name=='Diesel' else 'Synthetic measured fluid'}
    raw={str(r):v for r,v in zip((300,200,100,60,30,6,3),(55,45,33,26,20,11,9))}
    if name in ('Diesel','Pre Flush'):
        state['lab_qc_params'][name]={'rheology':{'bhct_down':{'selected':True,'readings':raw,'gel_10_sec':'-','gel_10_min':'-'}}}
    else:state['centralizer_config']={'aux_rheology':{name:raw}}
    from project_state import mud_lab_source_signature
    state['lab_source_signatures']['Displacement Fluid']=mud_lab_source_signature(state)
    b=replace(gate3_boundary(),gel_pa_by_fluid=(*gate3_boundary().gel_pa_by_fluid,(name,0.)))
    before=pickle.dumps(state)
    result=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping=stepping)
    assert result.time_min and {f.name for f in result.fluids}>={name,'Main','Displacement Fluid'}
    own=next(f for f in result.fluids if f.name==name)
    assert own.tau_y_pa>0 and own.operator_review=='NOT_ASSERTED' and own.fit_reviewed is False
    assert own.actual_ramp==('UNKNOWN' if name.startswith('Spacer ') else 'bhct_down')
    assert result.currentness=='NOT_CURRENTNESS_PROOF' and pickle.dumps(state)==before


@pytest.mark.parametrize('name',['Diesel','Pre Flush','Spacer Ahead','Spacer Behind'])
def test_cfw128_gate4d_validated_own_source_is_admitted_without_review(gate3_numeric_source,name):
    from cfw128_er03_numeric_adapter import _stage_lab_intake
    state=deepcopy(gate3_numeric_source);state['mud_type']='OBM';state['fluids_config']['active'].append(name)
    raw={str(r):str(v) for r,v in zip((300,200,100,60,30,6,3),(55,45,33,26,20,11,9))}
    if name in ('Diesel','Pre Flush'):
        state['lab_qc_params'][name]={'rheology':{'bhct_down':{'selected':True,'readings':raw,'gel_10_sec':'-','gel_10_min':'-'}}}
    else:state['centralizer_config']={'aux_rheology':{name:raw}}
    before=pickle.dumps(state);r=_stage_lab_intake(state,name,GATE3_APP_SOURCE_SHA)
    assert r.status=='CAPTURED_FOR_FUTURE_REVIEW',r.reason_codes
    assert r.readings[0].raw=='55' and r.operator_review=='NOT_ASSERTED' and r.fit_reviewed is False
    assert r.actual_ramp==('UNKNOWN' if name.startswith('Spacer ') else 'bhct_down')
    assert pickle.dumps(state)==before


def gate4d_program(base,names,legacy=False):
    from project_state import mud_lab_source_signature
    state=deepcopy(base)
    if 'Diesel' in names:state['mud_type']='OBM'
    state['lab_source_signatures']['Displacement Fluid']=mud_lab_source_signature(state)
    for i,name in enumerate(names):
        state['fluids_config']['active'].append(name)
        state['fluids_config']['params'][name]={'volume':1.,'density':52. if name=='Diesel' else 80.,'pump_rate':.25,'material_name':'Diesel' if name=='Diesel' else 'Synthetic source '+name}
        raw={str(r):str(v+i) for r,v in zip((300,200,100,60,30,6,3),(55,45,33,26,20,11,9))}
        if name.startswith('Spacer ') or legacy:
            state.setdefault('centralizer_config',{}).setdefault('aux_rheology',{})[name]=raw
        else:state['lab_qc_params'][name]={'rheology':{'bhct_down':{'selected':True,'readings':raw,'gel_10_sec':'-','gel_10_min':'-'}}}
    return state


@pytest.mark.parametrize('engine',['vertical','directional'])
@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
@pytest.mark.parametrize('names,legacy',[(('Pre Flush',),False),(('Diesel',),False),(('Spacer Ahead',),False),(('Spacer Behind',),False),(('Pre Flush',),True),(('Diesel','Pre Flush','Spacer Ahead','Spacer Behind'),False)])
def test_cfw128_gate4d_numeric_stage_truth_and_full_hb(gate3_numeric_source,engine,stepping,names,legacy,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    from dataclasses import replace,asdict
    state=gate4d_program(gate3_numeric_source,names,legacy);before=pickle.dumps(state)
    b=replace(gate3_boundary(),gel_pa_by_fluid=(*gate3_boundary().gel_pa_by_fluid,*((name,0.) for name in names)))
    original=adapter.fit_full_hb;calls={}
    def traced(dials,rpms,**kwargs):
        result=original(dials,rpms,**kwargs);calls[kwargs['fluid_id']]=(tuple(dials),kwargs,result);return result
    monkeypatch.setattr(adapter,'fit_full_hb',traced)
    r=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine=engine,stepping=stepping)
    assert r.status=='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED',r.holds
    for name in names:
        proof=next(f for f in r.fluids if f.name==name);dials,kw,fit=calls[name];assumed=name.startswith('Spacer ') or legacy
        assert proof.raw_readings==tuple((rpm,str(value)) for rpm,value in zip((300,200,100,60,30,6,3),dials))
        assert proof.tau_y_pa==fit.tau_y_pa>0
        assert proof.tau_y_field_lbf_100ft2==proof.tau_y_pa/.47880259
        assert (proof.k_pa_s_n,proof.n_dimensionless)==(fit.k_pa_s_n,fit.n_dimensionless)
        assert kw['reviewed'] is False and fit.reviewed is False and fit.bhct_down_dataset_eligible is False
        assert kw['ramp_type']=='bhct_down' and proof.operator_review=='NOT_ASSERTED'
        assert proof.actual_ramp==('UNKNOWN' if assumed else 'bhct_down')
        assert proof.fit_ramp==('ASSUMED_BHCT_DOWN' if assumed else 'bhct_down')
        assert kw['temperature_condition']==(None if assumed else 'BHCT_CONTEXT_ONLY')
        assert name+':'+proof.qualification_hold in r.holds
    assert calls['Main'][1]['reviewed'] is True and calls['Displacement Fluid'][1]['reviewed'] is True
    from cfw128_integration_abi import compose_nominal_tracking
    expected=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA).displacement.derived_displacement_bbl
    assert r.stages[-1][0]=='Displacement Fluid' and r.stages[-1][2]==expected
    assert all(asdict(r)[key] is False for key in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
    assert pickle.dumps(state)==before and r.currentness=='NOT_CURRENTNESS_PROOF' and r.final_post_pull_toc=='NOT_EVALUATED'


@pytest.mark.parametrize('fault',['inactive','duplicate','diesel_wbm','wrong_ramp','current_empty','current_unselected','boolean','fraction','negative','nan','extra_key','missing','invalid_text','instrument'])
def test_cfw128_gate4d_rejected_source_never_executes(gate3_numeric_source,fault,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    from dataclasses import replace
    name='Diesel' if fault=='diesel_wbm' else 'Pre Flush';state=gate4d_program(gate3_numeric_source,(name,))
    qc=state['lab_qc_params'][name];raw=qc['rheology']['bhct_down']['readings']
    if fault=='inactive':state['fluids_config']['active'].remove(name)
    elif fault=='duplicate':state['fluids_config']['active'].append(name)
    elif fault=='diesel_wbm':state['mud_type']='WBM'
    elif fault=='wrong_ramp':qc['rheology']['bhct_up']=qc['rheology'].pop('bhct_down')
    elif fault=='current_empty':state['lab_qc_params'][name]={}
    elif fault=='current_unselected':qc['rheology']['bhct_down']['selected']=False
    elif fault=='extra_key':raw[300]=55
    elif fault=='missing':raw.pop('3')
    elif fault=='instrument':qc['instrument_provenance']='VERIFIED'
    else:raw['300']={'boolean':True,'fraction':55.5,'negative':-1,'nan':float('nan'),'invalid_text':'55+1'}[fault]
    state['centralizer_config']={'aux_rheology':{'Pre Flush':{str(r):v for r,v in zip((300,200,100,60,30,6,3),(55,45,33,26,20,11,9))}}}
    def forbidden(*a,**k):raise AssertionError('Rejected source reached engine')
    for module in (adapter.vertical,adapter.directional,adapter.event_vertical,adapter.event_directional):monkeypatch.setattr(module,'simulate',forbidden)
    intake=adapter._stage_lab_intake(state,name,GATE3_APP_SOURCE_SHA)
    assert intake.status!='CAPTURED_FOR_FUTURE_REVIEW' and intake.readings==()
    if fault=='inactive':return  # unselected data is not consumed by the schedule
    b=replace(gate3_boundary(),gel_pa_by_fluid=(*gate3_boundary().gel_pa_by_fluid,(name,0.)))
    if fault in ('duplicate','diesel_wbm'):
        with pytest.raises(ValueError):adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    else:assert adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b).status=='HOLD'


def test_cfw128_gate4d_assumption_identity_and_frozen_provenance(gate3_numeric_source):
    from cfw128_er03_numeric_adapter import _stage_lab_intake
    from dataclasses import FrozenInstanceError,replace
    state=gate4d_program(gate3_numeric_source,('Spacer Ahead','Spacer Behind'))
    a=_stage_lab_intake(state,'Spacer Ahead',GATE3_APP_SOURCE_SHA);b=_stage_lab_intake(state,'Spacer Behind',GATE3_APP_SOURCE_SHA)
    assert a.source_identity!=b.source_identity and a.dataset is None and a.temperature_condition is None
    state['well_data']['bhct']=999.
    assert _stage_lab_intake(state,'Spacer Ahead',GATE3_APP_SOURCE_SHA)==a  # no measured temperature was consumed
    state['centralizer_config']['aux_rheology']['Spacer Ahead']['300']='56'
    c=_stage_lab_intake(state,'Spacer Ahead',GATE3_APP_SOURCE_SHA);assert c.source_identity!=a.source_identity
    assert _stage_lab_intake(state,'Spacer Behind',GATE3_APP_SOURCE_SHA)==b
    with pytest.raises(FrozenInstanceError):a.actual_ramp='bhct_down'
    with pytest.raises(ValueError):replace(a,fit_reviewed=True)
    assert pickle.loads(pickle.dumps(a))==a


def gate4f_resign(evidence, **changes):
    """Explicit synthetic precomputed evidence; consistency is not authenticity."""
    from dataclasses import replace
    from project_state import fingerprint
    r=replace(evidence,**changes)
    channels=tuple(getattr(r,n) for n in ('time_min','whp_kpsi','pump_kpsi','hydrostatic_kpsi','total_pressure_kpsi','q_in_bpm','q_out_bpm'))
    identity=fingerprint(['cfw128-gate3-result/1',r.source_identity,channels,r.events,r.engine_injection_capacity_bbl,r.tvd_comparison,r.stage_volume_audit,r.status,r.holds])
    identity=fingerprint(['cfw128-gate5bp1-result/1',identity,r.trajectory_source,r.directional_tvd_proof])
    if r.native_observation is not None:
        from cfw128_er03_numeric_adapter import _primitive
        identity=fingerprint(['cfw128-gate6c-observation/1',identity,_primitive(r.native_observation)])
    return replace(r,projection_identity=identity)


@pytest.fixture
def gate4f_precomputed():
    from cfw128_er03_numeric_adapter import NumericEvidence
    r=NumericEvidence(GATE3_APP_SOURCE_SHA,'a'*64,'b'*64,'c'*64,'NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED',('PHYSICAL_INSTRUMENT_UNVERIFIED',),'vertical',3885.,(),(),287.,287.,
        time_min=(0.,1.,2.,3.,4.),whp_kpsi=(.2,.4,.5,.3,.2),pump_kpsi=(.3,.5,.6,.4,.3),
        hydrostatic_kpsi=(2.,2.1,2.2,2.3,2.4),total_pressure_kpsi=(2.2,2.3,2.4,2.5,2.6),q_in_bpm=(1.,2.,2.,0.,0.),q_out_bpm=(1.,1.5,2.2,.3,0.),
        events=(('t_atcp',1.),('t_eod',2.),('t_marker',3.),('t_freefall_start',None),('t_freefall_end',None),('t_shutin',3.),('whp_final_psi',5000.),('bottom_shutin_psi',6000.)))
    return gate4f_resign(r)


def test_cfw128_gate4f_missing_presentation_boundary(gate4f_precomputed):
    from cfw128_er03_numeric_adapter import render_numeric_test_charts
    import matplotlib.pyplot as plt
    fig=render_numeric_test_charts(gate4f_precomputed)
    try:assert len(fig.axes)==3
    finally:plt.close(fig)


@pytest.mark.parametrize('dynamic,marker',[(True,3.),(False,3.),(True,2.)])
def test_cfw128_gate4f_shared_spec_pixels_png_and_no_numeric_calls(gate4f_precomputed,dynamic,marker,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    import fluids_charts_module_v1_4_2 as legacy
    import matplotlib.pyplot as plt
    import numpy as np
    from dataclasses import asdict
    from io import BytesIO
    r=gate4f_resign(gate4f_precomputed,total_pressure_kpsi=gate4f_precomputed.total_pressure_kpsi if dynamic else (),
        events=tuple((n,marker if n in ('t_marker','t_shutin') else v) for n,v in gate4f_precomputed.events))
    before=pickle.dumps(r);captured={};original=adapter.render_three_charts
    def spy(spec):captured['spec']=spec;return original(spec)
    def forbidden(*a,**k):raise AssertionError('Presentation executed numerical/App code')
    monkeypatch.setattr(adapter,'render_three_charts',spy)
    for name in ('compose_nominal_tracking','fit_full_hb','_stage_lab_intake','run_numeric_test_case'):
        monkeypatch.setattr(adapter,name,forbidden)
    for module in (adapter.vertical,adapter.directional,adapter.event_vertical,adapter.event_directional):monkeypatch.setattr(module,'simulate',forbidden)
    for name in ('simulate','build_three_charts','_build_fluids','geometry_from_hardware','stages_from_fluid_data'):
        monkeypatch.setattr(legacy,name,forbidden)
    fig=adapter.render_numeric_test_charts(r);other=None
    try:
        t=r.time_min;hydro=r.hydrostatic_kpsi;dyn=r.total_pressure_kpsi
        spec=legacy.JobChartsSpec(calc_cem_hp=(t,r.whp_kpsi),calc_pump_press=(t,r.pump_kpsi),hydrostatic=(t,hydro),dynamic=(t,dyn) if dynamic else None,
            q_in=(t,r.q_in_bpm),q_out=(t,r.q_out_bpm),depth_m=3885.,depth_unit='m',event_times=(1.,2.),marker_time=None if marker==2. else marker,
            axis_x=legacy.autoscale_x(4.),axis_y1=legacy.autoscale_y(0.,.6,True),axis_y2=legacy.autoscale_y(min(*hydro,*dyn),max(*hydro,*dyn),False),axis_y3=legacy.autoscale_y(0.,2.2,False))
        assert asdict(captured['spec'])==asdict(spec)
        other=legacy.render_three_charts(spec);fig.canvas.draw();other.canvas.draw()
        assert np.array_equal(fig.canvas.buffer_rgba(),other.canvas.buffer_rgba())
        a=BytesIO();b=BytesIO();fig.savefig(a,format='png',dpi=200,facecolor='white');other.savefig(b,format='png',dpi=200,facecolor='white');assert a.getvalue()==b.getvalue()
        assert tuple(fig.get_size_inches())==(10.,12.) and len(fig.axes)==3
        expected=[['Calc. CemHP','Acquired Pressure','Back Pressure','Calc. Pump Press.'],['Hydrostatic','Dynamic'],['Acquired Q Out','Acquired Q In','Q In','Q Out']]
        for ax,labels in zip(fig.axes,expected):
            assert [s.get_text() for s in ax.get_legend().texts]==labels
            assert ax.get_facecolor()==(240/255,240/255,240/255,1.) and ax.get_xlabel()=='Time (min)'
            assert all(s.get_linewidth()==1.1 for s in ax.spines.values())
            assert ax.xaxis.label.get_fontsize()==11. and ax.get_legend().texts[0].get_fontsize()==13.
        assert fig.axes[0].get_title()=='' and fig.axes[1].get_title()=='Depth =  3885 m' and fig.axes[2].get_title()=='Fluids at   3885 m'
        for i,ax in enumerate(fig.axes):
            assert sum(l.get_color()=='#00D200' for l in ax.lines)==(0 if i==0 else 2)
            assert sum(l.get_color()=='#808080' for l in ax.lines)==(0 if i==0 or marker==2. else 1)
        assert not any(l.get_color()=='#FF0000' for l in fig.axes[0].lines)
        assert pickle.dumps(r)==before and r.chart_admissible is False and r.final_post_pull_toc=='NOT_EVALUATED'
    finally:
        plt.close(fig)
        if other is not None:plt.close(other)


@pytest.mark.parametrize('fault',['type','missing','length','nan','inf','boolean','duplicate_time','decreasing_time','negative_time','depth_zero','depth_nan','depth_bool','event_unknown','event_duplicate','event_missing','event_shape','event_nan','event_bool','event_outside','event_eod_absent','event_freefall_order','event_marker_mismatch','source_sha','source_identity','source_hash','projection','channel_mutation','flag','nested_flag','qualification','empty_hold','bad_status','bad_engine'])
def test_cfw128_gate4f_rejects_before_renderer(gate4f_precomputed,fault,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    from dataclasses import replace
    r=gate4f_precomputed
    if fault=='type':r={}
    elif fault in ('missing','length','nan','inf','boolean','channel_mutation'):
        value={'missing':(),'length':(1.,),'nan':(float('nan'),)*5,'inf':(float('inf'),)*5,'boolean':(True,)*5,'channel_mutation':(3.,)*5}[fault];r=replace(r,whp_kpsi=value)
    elif fault in ('duplicate_time','decreasing_time','negative_time'):r=replace(r,time_min={'duplicate_time':(0.,1.,1.,3.,4.),'decreasing_time':(0.,2.,1.,3.,4.),'negative_time':(-1.,1.,2.,3.,4.)}[fault])
    elif fault.startswith('depth_'):r=replace(r,pressure_station_md={'depth_zero':0.,'depth_nan':float('nan'),'depth_bool':True}[fault])
    elif fault.startswith('event_'):
        rows=list(r.events)
        if fault=='event_unknown':rows[0]=('pressure_as_time',1.)
        elif fault=='event_duplicate':rows[0]=rows[1]
        elif fault=='event_missing':rows.pop(1)
        elif fault=='event_shape':rows[0]=('t_atcp',)
        elif fault=='event_freefall_order':rows[3]=('t_freefall_start',2.);rows[4]=('t_freefall_end',1.)
        elif fault=='event_marker_mismatch':rows[2]=('t_marker',1.)
        else:
            index=1 if fault=='event_eod_absent' else 0
            rows[index]=(rows[index][0],{'event_nan':float('nan'),'event_bool':True,'event_outside':5000.,'event_eod_absent':None}[fault])
        r=replace(r,events=tuple(rows))
    elif fault=='source_sha':r=replace(r,app_source_sha='not-a-sha')
    elif fault=='source_identity':r=replace(r,source_identity='d'*64)
    elif fault=='source_hash':r=replace(r,source_hashes=('forged',))
    elif fault=='projection':r=replace(r,projection_identity='d'*64)
    elif fault=='flag':object.__setattr__(r,'enabled',True)
    elif fault=='nested_flag':object.__setattr__(r,'chart_admissible',0)
    elif fault=='qualification':object.__setattr__(r,'qualification','CERTIFIED')
    elif fault=='empty_hold':r=replace(r,status='HOLD',time_min=())
    elif fault=='bad_status':r=replace(r,status='READY')
    elif fault=='bad_engine':r=replace(r,engine='App')
    def forbidden(*a,**k):raise AssertionError('Invalid evidence reached renderer')
    monkeypatch.setattr(adapter,'render_three_charts',forbidden)
    with pytest.raises((TypeError,ValueError)):adapter.render_numeric_test_charts(r)


def test_cfw128_gate4f_actual_numeric_receipt_read_only(gate3_numeric_source):
    from cfw128_er03_numeric_adapter import run_numeric_test_case,render_numeric_test_charts
    import matplotlib.pyplot as plt
    source=pickle.dumps(gate3_numeric_source)
    r=run_numeric_test_case(gate3_numeric_source,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
    before=pickle.dumps(r);fig=render_numeric_test_charts(r)
    try:assert len(fig.axes)==3 and pickle.dumps(r)==before and pickle.dumps(gate3_numeric_source)==source
    finally:plt.close(fig)


def test_cfw128_gate4f_import_exception_is_presentation_only(tmp_path):
    from pathlib import Path
    import ast
    source=Path('cfw128_er03_numeric_adapter.py').read_text();gate3_assert_numeric_imports(Path('cfw128_er03_numeric_adapter.py'))
    for symbol in ('simulate','build_three_charts','_build_fluids'):
        p=tmp_path/'forbidden.py';p.write_text(source.replace('JobChartsSpec, autoscale_x, autoscale_y, render_three_charts','JobChartsSpec, autoscale_x, autoscale_y, render_three_charts, '+symbol))
        with pytest.raises(AssertionError):gate3_assert_numeric_imports(p)
    tree=ast.parse(source);entry=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='render_numeric_test_charts')
    calls={n.func.id for n in ast.walk(entry) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    assert not calls&{'run_numeric_test_case','compose_nominal_tracking','fit_full_hb','simulate','build_three_charts','_stage_lab_intake'}


@pytest.mark.parametrize('gate',['enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'])
def test_cfw128_gate4f_each_false_gate_is_mandatory(gate4f_precomputed,gate,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    object.__setattr__(gate4f_precomputed,gate,True)
    def forbidden(*a,**k):raise AssertionError('Enabled receipt reached renderer')
    monkeypatch.setattr(adapter,'render_three_charts',forbidden)
    with pytest.raises(ValueError):adapter.render_numeric_test_charts(gate4f_precomputed)


def test_cfw128_gate4f_signed_flow_and_complete_hold_preserved(gate4f_precomputed,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    r=gate4f_resign(gate4f_precomputed,status='HOLD',holds=('BHSP_TARGET_STATION_NOT_PROVED',),q_out_bpm=(-1.,1.5,2.2,.3,0.))
    before=pickle.dumps(r);sentinel=object();seen={}
    def capture(spec):seen['spec']=spec;return sentinel
    monkeypatch.setattr(adapter,'render_three_charts',capture)
    assert adapter.render_numeric_test_charts(r) is sentinel
    assert seen['spec'].q_out==(r.time_min,r.q_out_bpm) and seen['spec'].q_in!=(r.time_min,r.q_out_bpm)
    assert seen['spec'].axis_y3[0]<0 and seen['spec'].axis_x[1]>r.time_min[-1]>dict(r.events)['t_eod']
    assert pickle.dumps(r)==before and r.status=='HOLD' and r.chart_admissible is False
    from dataclasses import replace
    with pytest.raises(ValueError):adapter.render_numeric_test_charts(replace(r,whp_kpsi=(10**400,)*5))


@pytest.mark.parametrize('shutin',[2.,3.,4.,None])
def test_cfw128_gate4fp1_shutin_chronology_before_render(gate4f_precomputed,shutin,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    r=gate4f_resign(gate4f_precomputed,status='HOLD',holds=('BHSP_TARGET_STATION_NOT_PROVED',),
        events=tuple((n,3. if n=='t_eod' else shutin if n in ('t_marker','t_shutin') else v) for n,v in gate4f_precomputed.events))
    before=pickle.dumps(r);seen=[];sentinel=object()
    def capture(spec):seen.append(spec);return sentinel
    monkeypatch.setattr(adapter,'render_three_charts',capture)
    if shutin==2.:
        with pytest.raises(ValueError,match='Shut-in precedes EOD'):adapter.render_numeric_test_charts(r)
        assert seen==[]
    else:
        assert adapter.render_numeric_test_charts(r) is sentinel
        assert seen[0].marker_time==(None if shutin in (None,3.) else shutin)
    assert pickle.dumps(r)==before and r.status=='HOLD' and r.chart_admissible is False


@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
def test_cfw128_gate5b_directional_admits_app_knots(gate3_numeric_source,stepping):
    from cfw128_er03_numeric_adapter import run_numeric_test_case,render_numeric_test_charts
    from dataclasses import FrozenInstanceError
    import matplotlib.pyplot as plt
    state=deepcopy(gate3_numeric_source)
    state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    before=pickle.dumps(state)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional',stepping=stepping)
    assert r.time_min and 'DIRECTIONAL_INTERIOR_TVD_CONVENTION_HOLD' not in r.holds
    proof=r.directional_tvd_proof
    assert proof[0:2]==('APP_WELL_PROFILE_DERIVED_STATION_KNOTS','ER03_PIECEWISE_LINEAR_INTERIOR')
    assert proof[2]==((0.,0.,0.),(100.,60.,0.),(1200.,60.,0.))
    assert proof[3][1]==pytest.approx((100.,82.69933431326882))
    assert r.tvd_comparison[0]==pytest.approx((50.,47.7464829275686,41.34966715663441))
    assert pickle.dumps(state)==before and r.currentness=='NOT_CURRENTNESS_PROOF' and r.chart_admissible is False
    fig=render_numeric_test_charts(r);plt.close(fig)
    with pytest.raises(FrozenInstanceError):r.directional_tvd_proof=()


@pytest.mark.parametrize('fault',['surface','bottom','duplicate','order','nan','missing','vertical_engine','sibling_receipt','edited_proof'])
def test_cfw128_gate5b_directional_invalid_source_or_binding(gate3_numeric_source,fault,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    from cfw128_integration_abi import compose_nominal_tracking
    from dataclasses import replace
    state=deepcopy(gate3_numeric_source)
    state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    frame=state['well_geometry']['survey'];composition=None
    if fault=='surface':frame.loc[0,'MD']=1.
    elif fault=='bottom':frame.loc[2,'MD']=1100.
    elif fault=='duplicate':frame.loc[1,'MD']=0.
    elif fault=='order':state['well_geometry']['survey']=frame.iloc[[0,2,1]].reset_index(drop=True)
    elif fault=='nan':frame.loc[1,'Deviation']=float('nan')
    elif fault=='missing':state['well_geometry']['survey']=frame.drop(columns=['Azimuth'])
    elif fault=='sibling_receipt':
        composition=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
        frame.loc[1,'Deviation']=55.
    elif fault=='edited_proof':
        r=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional')
        before=pickle.dumps(r);changed=replace(r,directional_tvd_proof=(*r.directional_tvd_proof[:3],((0.,0.),(100.,80.),(1200.,600.)),*r.directional_tvd_proof[4:]))
        def bad_render(*a,**k):raise AssertionError('Altered provenance reached renderer')
        monkeypatch.setattr(adapter,'render_three_charts',bad_render)
        with pytest.raises(ValueError):adapter.render_numeric_test_charts(changed)
        assert pickle.dumps(r)==before
        return
    def forbidden(*a,**k):raise AssertionError('Invalid directional source reached simulation')
    for module in (adapter.vertical,adapter.directional,adapter.event_vertical,adapter.event_directional):monkeypatch.setattr(module,'simulate',forbidden)
    if fault=='vertical_engine':
        r=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='vertical')
        assert r.time_min==() and 'DIRECTIONAL_SOURCE_REQUIRES_DIRECTIONAL_ENGINE' in r.holds
    else:
        with pytest.raises((ValueError,TypeError)):adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional',composition=composition)


def test_cfw128_gate5b_source_edit_identity_and_unaligned_hold(gate3_numeric_source):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from dataclasses import replace
    state=deepcopy(gate3_numeric_source);state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    a=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional')
    state['well_geometry']['survey'].loc[1,'Deviation']=55.
    b=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional')
    assert a.source_identity!=b.source_identity and a.projection_identity!=b.projection_identity and a.directional_tvd_proof!=b.directional_tvd_proof
    state['fluids_config']['params']['Main']['pump_rate']='40';state['fluids_config']['params']['Displacement Fluid']['pump_rate']='40'
    frozen=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=replace(gate3_boundary(),dt_min=.2),engine='directional')
    aligned=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=replace(gate3_boundary(),dt_min=.2),engine='directional',stepping='event_aligned_test_only')
    assert 'FROZEN_TIMESTEP_STAGE_VOLUME_NOT_PROVED' in frozen.holds and frozen.stage_volume_audit[0][1:3]==(1.,8.)
    assert all(entered==pytest.approx(executed,rel=2e-14) for _,entered,executed,_ in aligned.stage_volume_audit)


@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
@pytest.mark.parametrize('fault',['empty','reverse','surface','bottom','duplicate','negative','nan','slope','inclination','azimuth','ref','request','source_version','vertical_contradiction','boolean'])
def test_cfw128_gate5bp1_generated_rendering_proof_boundary(gate3_numeric_source,stepping,fault,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    from dataclasses import replace
    state=deepcopy(gate3_numeric_source);state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    r=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional',stepping=stepping)
    proof=r.directional_tvd_proof;raw=list(proof[2]);knots=list(proof[3]);changes={}
    if fault=='empty':changes['directional_tvd_proof']=()
    elif fault=='reverse':raw.reverse();knots.reverse()
    elif fault=='surface':raw=raw[1:];knots=knots[1:]
    elif fault=='bottom':raw=raw[:-1];knots=knots[:-1]
    elif fault=='duplicate':raw[1]=raw[0];knots[1]=knots[0]
    elif fault in ('negative','nan','slope'):knots[1]=(100.,{'negative':-1.,'nan':float('nan'),'slope':101.}[fault])
    elif fault=='inclination':raw[1]=(100.,181.,0.)
    elif fault=='azimuth':raw[1]=(100.,60.,360.)
    elif fault=='boolean':raw[0]=(False,0.,0.)
    elif fault in ('ref','request'):proof=(*proof[:4],'bad' if fault=='ref' else proof[4],'bad' if fault=='request' else proof[5])
    elif fault in ('source_version','vertical_contradiction'):changes['trajectory_source']='UNKNOWN' if fault=='source_version' else 'VERTICAL_SOURCE_V1'
    if fault not in ('empty','ref','request','source_version','vertical_contradiction'):
        proof=(*proof[:2],tuple(raw),tuple(knots),*proof[4:])
    changes.setdefault('directional_tvd_proof',proof)
    changed=gate4f_resign(r,**changes)
    def forbidden(*a,**k):raise AssertionError('Malformed generated proof reached renderer')
    monkeypatch.setattr(adapter,'render_three_charts',forbidden)
    with pytest.raises((ValueError,TypeError)):adapter.render_numeric_test_charts(changed)


@pytest.mark.parametrize('engine',['vertical','directional'])
@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
def test_cfw128_gate5bp1_vertical_source_engine_independent(gate3_numeric_source,engine,stepping,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    r=adapter.run_numeric_test_case(gate3_numeric_source,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine=engine,stepping=stepping)
    assert r.trajectory_source=='VERTICAL_SOURCE_V1' and r.directional_tvd_proof==() and r.time_min
    monkeypatch.setattr(adapter,'render_three_charts',lambda spec:spec)
    assert adapter.render_numeric_test_charts(r).depth_m==r.pressure_station_md


@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
def test_cfw128_gate5bp1_decreasing_tvd_and_early_hold(gate3_numeric_source,stepping,monkeypatch):
    import cfw128_er03_numeric_adapter as adapter
    state=deepcopy(gate3_numeric_source);state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[1000.,80.,0.],[1200.,120.,0.]],columns=['MD','Deviation','Azimuth'])}
    before=pickle.dumps(state)
    r=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional',stepping=stepping)
    assert r.trajectory_source=='APP_DIRECTIONAL_STATION_TVD_V1' and r.directional_tvd_proof[3][-1][1]<r.directional_tvd_proof[3][-2][1]
    monkeypatch.setattr(adapter,'render_three_charts',lambda spec:spec)
    assert adapter.render_numeric_test_charts(r).depth_m==1200.
    held=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='vertical',stepping=stepping)
    assert held.trajectory_source=='APP_DIRECTIONAL_STATION_TVD_V1' and held.status=='HOLD' and not held.time_min
    with pytest.raises(ValueError):adapter.render_numeric_test_charts(held)
    assert pickle.dumps(state)==before and r.chart_admissible is False


@pytest.mark.parametrize('engine',['vertical','directional'])
@pytest.mark.parametrize('stepping',['frozen','event_aligned_test_only'])
@pytest.mark.parametrize('back_pressure',[0.,250.])
def test_cfw128_gate6a_equal_numbers_do_not_prove_bhsp_station(gate3_numeric_source,engine,stepping,back_pressure,monkeypatch):
    from dataclasses import replace
    from engineering_tools import lab_review_signature
    from project_state import lab_source_signature
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    state=deepcopy(gate3_numeric_source)
    # Homogeneous synthetic fluid makes the annular endpoint equal the target;
    # it supplies no independent BHSP station/datum certificate.
    state['fluids_config']['params']['Main']['density']='80'
    state['lab_source_signatures']['Main']=lab_source_signature(state,'Main')
    state['lab_qc_params']['Main']['review_signature']=lab_review_signature(state['lab_qc_params']['Main'],state['lab_grid_dfs']['Main'])
    if engine=='directional':
        state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    import cfw128_er03_numeric_adapter as adapter
    solver=getattr(adapter,('event_' if stepping!='frozen' else '')+engine)
    simulate=solver.simulate;raw=[]
    def capture(job):
        result=simulate(job);raw.append(result);return result
    monkeypatch.setattr(solver,'simulate',capture)
    before=pickle.dumps(state)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=replace(gate3_boundary(),bhsp_target_psi=5000.,back_pressure_psi=back_pressure,gel_pa_by_fluid=tuple((n,25.) for n,v in gate3_boundary().gel_pa_by_fluid)),engine=engine,stepping=stepping)
    assert pickle.dumps(state)==before
    for channel,original in zip(('time_min','whp_kpsi','pump_kpsi','hydrostatic_kpsi','total_pressure_kpsi','q_in_bpm','q_out_bpm'),('t','whp','pump','hydro','dyn','q_in','q_out')):
        assert getattr(r,channel)==tuple(getattr(raw[0],original))
    assert r.events==tuple((name,getattr(raw[0],name)) for name,value in r.events)
    events=dict(r.events);shutin=events['t_shutin']
    assert events['t_eod']<=shutin<r.time_min[-1]
    assert all(qi==qo==0. for t,qi,qo in zip(r.time_min,r.q_in_bpm,r.q_out_bpm) if t>shutin)
    assert r.pressure_station_md==1200.
    assert all(getattr(r,name) is False for name in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
    assert 'FIELD_PRESSURE_DATUM_NOT_CERTIFIED' in r.holds
    assert r.total_pressure_kpsi[-1]*1000.==pytest.approx(5000.,abs=1e-9)
    assert dict(r.events)['bottom_shutin_psi']==5000.  # target echo only
    assert r.status=='HOLD' and 'BHSP_TARGET_STATION_NOT_PROVED' in r.holds


@pytest.mark.parametrize('engine',['vertical','directional'])
def test_cfw128_gate6c_native_ports_all_branches_and_closure(engine):
    import cfw128_er03_event_aligned_vertical as v
    import cfw128_er03_event_aligned_directional as d
    from cfw128_er03_numeric_adapter import NativePortObservation,_validate_native_observation
    branches=set();head=0.;mouth=0.
    for density in ((8.,18.),(18.,8.)):
        for float_on in (False,True):
            for rates in ((40.,13.7),(2.,40.)):
                job=gate4b_job(v,dt=.2,tail=.35,densities=density,float_on=float_on,volumes=(250.,250.),rates=rates)
                if engine=='directional':job=d.attach_survey(job,d.Survey([0.,100.,1200.],[0.,82.69933431326882,632.699334313269]))
                result=(v if engine=='vertical' else d).simulate(job)
                payload=result.diag['native_port_inventory_v1']
                o=NativePortObservation('a'*64,('b'*64,),payload)
                channels=tuple(tuple(getattr(result,n)) for n in ('t','whp','pump','hydro','dyn','q_in','q_out'))
                events=(('t_eod',result.t_eod),('t_shutin',result.t_shutin))
                _validate_native_observation(o,'a'*64,('b'*64,),channels,events,tuple((s.fluid_type,s.volume_bbl,s.rate_bpm) for s in job.placement),tuple(job.fluids),job.geo.total_pipe_bbl)
                assert payload[3][0]==result.t_eod and payload[4][0]==result.diag['event_intervals'][-1][1]
                branches.update(row[3] for row in payload[2])
                totals=dict(o.cumulative_returns);head+=sum(x for n,x in totals['PIPE_HEAD']);mouth+=sum(x for n,x in totals['ANNULAR_MOUTH'])
                assert math.fsum(x for rows in totals.values() for n,x in rows)==pytest.approx(result.diag['vol_audit']['qo_tot'],abs=1e-9)
    assert {'normal','freefall','ffrefill','gapclose','freeex','tail_ff','tail_rev','tail_bal','tail_cap'}<=branches
    assert head>0 and mouth>head


@pytest.mark.parametrize('engine',['vertical','directional'])
@pytest.mark.parametrize('fault',['missing','version','source','hash','port','fluid','negative','nan','bool','time','duplicate','injected','eod','tail','snapshot','identity','zero_terminal','duplicate_injection'])
def test_cfw128_gate6c_adversarial_receipt_before_render(gate3_numeric_source,engine,fault):
    from dataclasses import replace
    import cfw128_er03_numeric_adapter as a
    state=deepcopy(gate3_numeric_source)
    if engine=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    r=a.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine=engine,stepping='event_aligned_test_only')
    o=r.native_observation;assert o.status=='OBSERVATION_ONLY_HOLD'
    payload=list(o.payload);rows=list(payload[2]);row=list(rows[0])
    if fault=='missing':bad=replace(r,native_observation=None)
    elif fault=='source':bad=replace(r,native_observation=replace(o,source_identity='0'*64))
    elif fault=='hash':bad=replace(r,native_observation=replace(o,source_hashes=('0'*64,)))
    elif fault=='identity':bad=replace(r,native_observation=replace(o,payload=(*o.payload[:4],(999.,*o.payload[4][1:]))))
    else:
        if fault=='zero_terminal':
            row=list(rows[-1]);assert row[2]==0.
            ports=list(row[6]);ports[0]=('ANNULAR_MOUTH',(('Mud',1e-10),));row[6]=tuple(ports);rows[-1]=tuple(row)
        elif fault=='duplicate_injection':
            n,x=row[5][0];row[5]=((n,x/2),(n,x/2))
        elif fault=='version':payload[0]='UNKNOWN'
        elif fault=='time':row[0]=.01
        elif fault=='duplicate':rows.insert(0,rows[0])
        elif fault=='injected':row[5]=(('Mud',1.),)
        elif fault in ('eod','tail','snapshot'):
            index=3 if fault=='eod' else 4;snap=list(payload[index])
            if fault=='snapshot':snap[1]=()
            else:snap[0]+=1.
            payload[index]=tuple(snap)
        else:
            ports=list(row[6]);port,chunks=ports[0]
            if fault=='port':ports[0]=('PIPE_HEAD',chunks)
            else:
                name,value=chunks[0]
                ports[0]=(port,(({'fluid':'FOREIGN'}.get(fault,name),{'negative':-1.,'nan':float('nan'),'bool':True}.get(fault,value)),*chunks[1:]))
            row[6]=tuple(ports)
        if fault not in ('duplicate','zero_terminal'):rows[0]=tuple(row)
        payload[2]=tuple(rows);bad=replace(r,native_observation=replace(o,payload=tuple(payload)))
    # Rebind deliberately to challenge semantic validation, not just the hash.
    if fault not in ('identity','nan'):bad=gate4f_resign(bad)
    with pytest.raises((ValueError,TypeError)):a.render_numeric_test_charts(bad)


@pytest.mark.parametrize('engine',['vertical','directional'])
def test_cfw128_gate6c_observation_held_and_frozen_absent(gate3_numeric_source,engine):
    import cfw128_er03_numeric_adapter as a
    import matplotlib.pyplot as plt
    state=deepcopy(gate3_numeric_source);before=pickle.dumps(state)
    frozen=a.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine=engine)
    assert frozen.native_observation is None and frozen.native_observation_status=='ABSENT_UNQUALIFIED'
    r=a.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine=engine,stepping='event_aligned_test_only')
    assert r.native_observation_status=='OBSERVATION_ONLY_HOLD' and r.qualification=='NOT_GRANTED'
    assert r.currentness=='NOT_CURRENTNESS_PROOF' and r.final_post_pull_toc=='NOT_EVALUATED'
    assert pickle.dumps(state)==before
    fig=a.render_numeric_test_charts(r);plt.close(fig)


# Gate7 consumes validation/source authorities only, never numeric execution.
def gate7_assert_imports(path):
    import ast
    tree=ast.parse(path.read_text())
    expected={'dataclasses':('dataclass','field'),'fractions':('Fraction',),'materials_db':('PLACEMENT_SLURRIES',),
              'cement_chart_model':('_capacity',),'engineering_tools':('require_positive_pump_rate',),'project_state':('fingerprint',),
              'cfw128_integration_abi':('CompositionReceipt','compose_nominal_tracking'),
              'cfw128_er03_numeric_adapter':('NumericEvidence','_primitive','_stage_lab_intake','validate_numeric_evidence')}
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert len(nodes)==len(expected) and {n.module:tuple(a.name for a in n.names) for n in nodes}==expected
    assert all(n.level==0 and all(a.asname is None for a in n.names) for n in nodes)
    assert [(a.name,a.asname) for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]==[('math',None)]
    assert not {'eval','exec','__import__','import_module','run_numeric_test_case','simulate','render_three_charts'} & {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}


@pytest.fixture(scope='module')
def gate7_cases(bug01_reviewed_report_base,c2_native_geometries):
    from dataclasses import replace
    from cfw128_er03_numeric_adapter import run_numeric_test_case,event_vertical
    cases={}
    for job in BUG01_JOBS:
        for volume in (1.,40.,200.):
            state=gate3_case(bug01_reviewed_report_base,job)
            state['fluids_config']['params']['Main'].update(volume=volume,pump_rate=volume/4.)
            b=replace(gate3_boundary(),float_equipment=True,back_pressure_psi=250.,tail_cap_min=.35,
                      gel_pa_by_fluid=tuple((n,25.) for n,v in gate3_boundary().gel_pa_by_fluid))
            original=event_vertical.simulate
            def observe(design):
                c2_native_geometries[job,volume]=design.geo
                return original(design)
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(event_vertical,'simulate',observe)
                r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping='event_aligned_test_only')
            cases[job,volume]=(state,r,b)
    return cases


@pytest.mark.parametrize('job',BUG01_JOBS)
@pytest.mark.parametrize('volume',[1.,40.,200.])
def test_cfw128_gate7_actual_eod_placement_cases(gate7_cases,job,volume):
    from cfw128_c2e7_native_placement import assess_native_placement
    state,r,b=gate7_cases[job,volume];before=pickle.dumps((state,r))
    a=assess_native_placement(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    eod=r.native_observation.payload[3]
    assert a.pump_end_min==eod[0] and a.pipe_gap_bbl==eod[3]
    assert a.annular_cement_bbl==math.fsum(v for n,v in eod[2] if n=='Main')
    assert a.pipe_cement_bbl==math.fsum(v for n,v in eod[1] if n=='Main')
    assert all(abs(row[-1])<=1e-9 for row in a.fluid_balances)
    assert a.enabled is a.ready_to_run is a.hb_admissible is a.hydraulic_admissible is a.chart_admissible is a.scientifically_qualified is False
    assert set(r.holds)<=set(a.holds) and a.qualification=='NOT_GRANTED'
    assert pickle.dumps((state,r))==before
    if volume==1.:assert a.static_candidate_md is None and 'NO_NATIVE_ANNULAR_CEMENT' in a.case_holds
    if volume==200. and job.startswith(('LNR 7','TIE BACK')):
        assert a.static_candidate_md is not None and a.region=='ABOVE_LAP'
        assert a.basis=='OWNER_STATIC_CONSERVED_ANNULAR_CEMENT_POST_DP_PULL'
    if a.static_candidate_md is not None:
        assert not a.case_holds and all(row[1]<row[2] for row in a.mapped_intervals)
        assert math.fsum(row[3] for row in a.mapped_intervals)==pytest.approx(a.annular_cement_bbl,abs=1e-9)
    else:assert a.case_holds
    if job.startswith('CSG'):assert a.basis=='CASING_NATIVE_PUMP_END_NO_DP_PULL'


@pytest.mark.parametrize('job',['CSG 9 5/8"','LNR 7"','TIE BACK LNR 7"'])
def test_cfw128_gate7_canonical_inverse_boundaries_only(gate7_cases,job):
    # Geometry-only inversions, not fabricated native receipts or field values.
    from fractions import Fraction
    from cfw128_integration_abi import compose_nominal_tracking
    from cfw128_c2e7_native_placement import _map_static
    from cement_chart_model import _capacity
    state,r,b=gate7_cases[job,200.];c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    g=c.geometry;sections=g.post_pull_return or g.pumping_return;shoe=c.captured_geometry.shoe_md
    total=sum((Fraction(_capacity(n.outer_diameter_in,n.inner_diameter_in))*Fraction(n.bottom_md-n.top_md) for n in sections),Fraction())
    rows,md,reason=_map_static((('Main',total),),sections,shoe)
    assert md==0. and reason is None
    assert _map_static((('Main',total+1),),sections,shoe)[2]=='STATIC_CEMENT_EXCEEDS_CANONICAL_CAPACITY'
    if c.captured_geometry.kind!='casing':
        lower=sum((Fraction(_capacity(n.outer_diameter_in,n.inner_diameter_in))*Fraction(n.bottom_md-n.top_md) for n in g.lower_annulus),Fraction())
        assert _map_static((('Lead',lower/2),('Tail',lower/2)),sections,shoe)[1]==c.captured_geometry.string_top_md
        assert _map_static((('Main',lower/2),),sections,shoe)[1]>c.captured_geometry.string_top_md


@pytest.mark.parametrize('fault',['state_geometry','composition','numeric_id','observation','source','fluid','stage_echo','fluid_echo','result_candidate','flag','lab'])
def test_cfw128_gate7_source_and_projection_mutations(gate7_cases,fault):
    from dataclasses import replace
    from cfw128_integration_abi import compose_nominal_tracking
    from cfw128_c2e7_native_placement import assess_native_placement
    state,r,b=gate7_cases['LNR 7"',200.];state=deepcopy(state);kw={}
    if fault=='state_geometry':state['hardware_table'].loc[state['hardware_table']['Description']=='Liner Lap','MD (m)']='450'
    elif fault=='composition':
        kw['composition']=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
        state['fluids_config']['params']['Main']['volume']=201.
    elif fault=='numeric_id':r=replace(r,projection_identity='0'*64)
    elif fault=='observation':r=replace(r,native_observation=None)
    elif fault=='source':r=replace(r,composition_projection_identity='0'*64)
    elif fault=='fluid':r=replace(r,fluids=())
    elif fault=='stage_echo':r=replace(r,stages=((r.stages[0][0],'Changed material',*r.stages[0][2:]),*r.stages[1:]))
    elif fault=='fluid_echo':r=replace(r,fluids=(replace(r.fluids[0],raw_readings=((300,99),*r.fluids[0].raw_readings[1:])),*r.fluids[1:]))
    elif fault=='lab':state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']=47
    if fault in ('result_candidate','flag'):
        a=assess_native_placement(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
        with pytest.raises((ValueError,TypeError)):
            replace(a,**({'static_candidate_md':1.} if fault=='result_candidate' else {'enabled':True}))
    else:
        with pytest.raises((ValueError,TypeError)):
            assess_native_placement(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,**kw)


def test_cfw128_gate7_directional_and_frozen_absence(gate7_cases):
    from dataclasses import replace
    from cfw128_c2e7_native_placement import assess_native_placement
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    state,r,b=gate7_cases['LNR 7"',200.];state=deepcopy(state)
    state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    d=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine='directional',stepping='event_aligned_test_only')
    a=assess_native_placement(state,d,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    assert a.annular_cement_bbl==sum(v for n,v in d.native_observation.payload[3][2] if n=='Main')
    f=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine='directional')
    absent=assess_native_placement(state,f,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    assert absent.annular_cement_bbl is None and absent.static_candidate_md is None
    assert absent.case_holds==('NATIVE_EOD_OBSERVATION_ABSENT',)


def test_cfw128_gate7_named_import_exception_and_mutation(monkeypatch):
    from pathlib import Path
    path=Path('cfw128_c2e7_native_placement.py');gate7_assert_imports(path)
    read=Path.read_text
    for added in ('\nfrom cfw128_er03_numeric_adapter import run_numeric_test_case\n','\nimport pumping_simulation\n'):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+added if p==path else read(p,*a,**k))
            with pytest.raises(AssertionError):gate7_assert_imports(path)



def test_cfw128_gate7_casing_surface_capacity_mismatch_holds(gate7_cases):
    from cfw128_c2e7_native_placement import assess_native_placement
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    state,r,b=gate7_cases['CSG 9 5/8"',200.];state=deepcopy(state)
    state['fluids_config']['params']['Main'].update(volume=800.,pump_rate=200.)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping='event_aligned_test_only')
    assert all(n=='Main' for n,v in r.native_observation.payload[3][2])
    a=assess_native_placement(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    assert a.static_candidate_md is None
    assert a.case_holds==('CASING_SURFACE_VOLUME_CANONICAL_CAPACITY_NOT_PROVED',)


@pytest.mark.parametrize('scavenger',[False,True])
def test_cfw128_gate7_native_multiple_cement_fluid_identities(gate7_cases,scavenger):
    # Reuse Gate4C's existing own-formulation synthetic review procedure. These
    # records are software test inputs, never field/operator approval evidence.
    from dataclasses import replace
    from project_state import lab_source_signature
    from engineering_tools import lab_review_signature
    from materials_db import PLACEMENT_SLURRIES
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_c2e7_native_placement import assess_native_placement
    state,r,b=gate7_cases['LNR 7"',200.];state=deepcopy(state)
    state['fluids_config']['params']['Main'].update(volume=100.,pump_rate=25.)
    names=('Tail','Scavenger') if scavenger else ('Tail',)
    for name in names:
        state['fluids_config']['active'].insert(0,name)
        state['fluids_config']['params'][name]=dict(state['fluids_config']['params']['Main'])
        for key in ('cement_params','fluid_data','cement_additives_dfs','lab_grid_dfs','lab_qc_params'):
            state[key][name]=deepcopy(state[key]['Main'])
        state['lab_source_signatures'][name]=lab_source_signature(state,name)
        state['lab_qc_params'][name]['review_signature']=lab_review_signature(state['lab_qc_params'][name],state['lab_grid_dfs'][name])
    b=replace(b,gel_pa_by_fluid=(*b.gel_pa_by_fluid,*((n,25.) for n in names)))
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping='event_aligned_test_only')
    a=assess_native_placement(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    eod=r.native_observation.payload[3]
    assert {'Main','Tail'}<=set(n for n,v in eod[2])
    assert a.annular_cement_bbl==math.fsum(v for n,v in eod[2] if n in PLACEMENT_SLURRIES)
    assert a.pipe_cement_bbl==math.fsum(v for n,v in eod[1] if n in PLACEMENT_SLURRIES)
    assert all(abs(row[-1])<=1e-9 for row in a.fluid_balances)
    if scavenger:
        assert any(row[0]=='Scavenger' and row[2]>0 for row in a.fluid_balances)
        assert 'Scavenger' not in PLACEMENT_SLURRIES
    if a.static_candidate_md is not None:
        assert {'Main','Tail'}==set(row[0] for row in a.mapped_intervals)
    else:assert 'NONCEMENT_BELOW_OR_BETWEEN_CEMENT_SLUGS' in a.case_holds


def gate8_assert_imports(path):
    import ast
    tree=ast.parse(path.read_text())
    wanted={'contextlib':('contextmanager',),'copy':('deepcopy',),'dataclasses':('dataclass','field'),
        'io':('BytesIO',),'docxtpl':('DocxTemplate',),'project_state':('fingerprint','prepare_calculations'),
        'pumping_simulation':('source_signature',),'well_report':('canonical_report_source','prepared_well_report','postprocess_well_report'),
        'cement_chart_report':('prepared_cement_report',),'well_schematic_adapter':('source_signature','prepare_schematic'),
        'phase_10_procedure':('TEMPLATE_PATH','document_signature','_word_quantity_context'),
        'cfw128_er03_numeric_adapter':('NumericBoundary','NumericEvidence','_primitive','run_numeric_test_case','validate_numeric_evidence','render_numeric_test_charts'),
        'cfw128_c2e7_native_placement':('NativePlacementAssessment','assess_native_placement'),
        'cfw128_c2e8_post_pull_review':('PostPullConditions','PostPullReview','assess_post_pull','validate_post_pull_review')}
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert len(nodes)==len(wanted) and {n.module:tuple(a.name for a in n.names) for n in nodes}==wanted
    assert all(n.level==0 for n in nodes)
    assert [(n.module,a.name,a.asname) for n in nodes for a in n.names if a.asname is not None]==[('well_schematic_adapter','source_signature','schematic_source_signature')]
    assert [(a.name,a.asname) for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]==[('matplotlib.pyplot','plt')]
    assert not {'eval','exec','__import__','import_module','run_pumping_simulation','build_three_charts','simulate'} & {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}


@pytest.fixture(scope='module')
def gate8_cases(bug01_reviewed_report_base):
    from dataclasses import replace
    from cfw128_shadow_word_bridge import prepare_shadow
    cases={}
    for job in BUG01_JOBS:
        state=gate3_case(bug01_reviewed_report_base,job)
        state['fluids_config']['params']['Main'].update(volume=200.,pump_rate=50.)
        b=replace(gate3_boundary(),float_equipment=True,back_pressure_psi=250.,tail_cap_min=.35,
            gel_pa_by_fluid=tuple((n,25.) for n,v in gate3_boundary().gel_pa_by_fluid))
        cases[job]=(state,b,prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b))
    return cases


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_gate8_eight_native_shadow_families(gate8_cases,job,monkeypatch):
    import cfw128_shadow_word_bridge as bridge
    import fluids_charts_module_v1_4_2 as legacy
    import matplotlib.pyplot as plt
    from io import BytesIO
    import numpy as np
    state,b,r=gate8_cases[job];before=pickle.dumps((state,r));figures=plt.get_fignums()
    def forbidden(*a,**k):raise AssertionError('Shadow called legacy numerical solver')
    for name in ('simulate','build_three_charts'):monkeypatch.setattr(legacy,name,forbidden)
    with bridge.shadow_pumping_report(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b) as p:
        assert p['result'] is r and len(p['figure'].axes)==3
        other=bridge.render_numeric_test_charts(r.numeric)
        try:
            p['figure'].canvas.draw();other.canvas.draw()
            assert np.array_equal(p['figure'].canvas.buffer_rgba(),other.canvas.buffer_rgba())
            left=BytesIO();right=BytesIO()
            p['figure'].savefig(left,format='png',dpi=200,facecolor='white');other.savefig(right,format='png',dpi=200,facecolor='white')
            assert left.getvalue()==right.getvalue() and tuple(p['figure'].get_size_inches())==(10.,12.)
        finally:plt.close(other)
        assert any('ANNULAR_MOUTH_PLUS_PIPE_HEAD' in v for v in p['warnings'])
        assert all(getattr(r,n) is False for n in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
        assert r.numeric.native_observation is not None and r.placement.final_post_pull_toc=='FINAL_POST_PULL_TOC_NOT_EVALUATED'
    assert plt.get_fignums()==figures and pickle.dumps((state,r))==before


@pytest.mark.parametrize('fault',['job','volume','rate','material','lab','review','survey','sha','boundary','numeric','native','placement','prefix','late'])
def test_cfw128_gate8_stale_and_mixed_sources_reject_before_figure(gate8_cases,fault,monkeypatch):
    from dataclasses import replace
    import cfw128_shadow_word_bridge as bridge
    state,b,r=gate8_cases['LNR 7"'];state=deepcopy(state);sha=GATE3_APP_SOURCE_SHA
    if fault=='job':state['job_type']='TIE BACK LNR 7"'
    elif fault in ('volume','rate','material'):state['fluids_config']['params']['Main'][{'rate':'pump_rate','material':'material_name'}.get(fault,fault)]='changed'
    elif fault=='lab':state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']=46
    elif fault=='review':state['lab_qc_params']['Main']['reviewed']=False
    elif fault=='survey':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0,0,0],[1200,60,0]],columns=['MD','Deviation','Azimuth'])}
    elif fault=='sha':sha='0'*40
    elif fault=='boundary':b=replace(b,back_pressure_psi=251.)
    elif fault in ('numeric','native','placement','prefix'):
        with pytest.raises((ValueError,TypeError)):
            if fault=='numeric':replace(r,numeric=replace(r.numeric,projection_identity='0'*64))
            elif fault=='native':replace(r,numeric=replace(r.numeric,native_observation=None))
            elif fault=='placement':replace(r,placement=gate8_cases['CSG 9 5/8"'][2].placement)
            else:replace(r,schema='LIVE')
        return
    else:state['well_data']['well_name']='Different session'
    monkeypatch.setattr(bridge,'render_numeric_test_charts',lambda *a:pytest.fail('Stale source rendered'))
    with pytest.raises((ValueError,TypeError)):
        with bridge.shadow_pumping_report(state,r,expected_app_source_sha=sha,boundary=b):pass


def test_cfw128_gate8_directional_and_uat19_hold(bug01_reviewed_report_base,monkeypatch):
    import cfw128_shadow_word_bridge as bridge
    import cfw128_er03_numeric_adapter as adapter
    state=gate3_case(bug01_reviewed_report_base,'LNR 7"')
    state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    r=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional')
    assert r.numeric.trajectory_source=='APP_DIRECTIONAL_STATION_TVD_V1'
    state['well_geometry']['survey'].loc[2,'MD']=50.
    with pytest.raises(ValueError):bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),engine='directional')
    uat=cfw128_c1_uat19_state();before=pickle.dumps(uat)
    from cfw128_adapter import snapshot_geometry
    g=snapshot_geometry(uat,app_source_sha=GATE3_APP_SOURCE_SHA)
    assert g.shoe_md==3885. and g.receiver.shoe_md==4860.
    assert [(p.top_md,p.bottom_md) for p in g.active_sections]==[(0.,2800.),(2800.,3885.)]
    monkeypatch.setattr(adapter.event_vertical,'simulate',lambda *a:pytest.fail('Invented UAT19 field inputs'))
    with pytest.raises((ValueError,KeyError)):bridge.prepare_shadow(uat,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
    assert pickle.dumps(uat)==before


def test_cfw128_gate8_word_package_and_context_binding(bug01_reviewed_report_base,monkeypatch,tmp_path):
    from unittest.mock import patch
    from io import BytesIO
    from zipfile import ZipFile
    import hashlib
    from docx import Document
    from docxtpl import DocxTemplate
    import phase_10_procedure as report
    import well_report
    import cfw128_shadow_word_bridge as bridge
    import matplotlib.pyplot as plt
    from centralizer_fixtures import execute_centralizer
    from test_uat_round10b_pumping_word import drawing_paragraph,image_bytes
    from project_state import prepare_calculations,lab_source_signature,mud_lab_source_signature
    from engineering_tools import lab_review_signature
    from cfw128_integration_abi import compose_nominal_tracking
    state=gate3_case(bug01_reviewed_report_base)
    state['fluids_config']['params']['Main'].update(volume=40.,pump_rate=10.)
    state['fluids_config']['params']['Displacement Fluid']['volume']=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA).displacement.derived_displacement_bbl
    # Word preparation rebuilds formulation before review, as in the existing
    # reviewed synthetic UI fixture. Recheck that current source, not old cache.
    prepare_calculations(state)
    for name in ('Main','Displacement Fluid'):
        state['lab_source_signatures'][name]=lab_source_signature(state,name) if name=='Main' else mud_lab_source_signature(state)
        qc=state['lab_qc_params'][name];qc['reviewed']=True
        qc['review_signature']=lab_review_signature(qc,state['lab_grid_dfs'].get(name))
    execute_centralizer(state)
    with patch.object(report.st,'session_state',state):context=report.build_master_context()
    r=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),word_context=context)
    before=pickle.dumps((state,context,r));other=plt.figure();baseline=plt.get_fignums()
    try:
        with bridge.shadow_pumping_report(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary()) as p:
            png=BytesIO();p['figure'].savefig(png,format='png',dpi=200,facecolor='white')
        output=bridge.shadow_word_bytes(state,r,context,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
        (tmp_path/'shadow.docx').write_bytes(output['bytes']);(tmp_path/'shadow.png').write_bytes(png.getvalue())
        doc=Document(BytesIO(output['bytes']));paragraph=drawing_paragraph(doc,'Pumping Simulation Charts')
        assert image_bytes(doc,paragraph)==png.getvalue()
        original=next(p for p in Document(report.TEMPLATE_PATH).paragraphs if p.text==well_report.PUMPING_CHART_ANCHOR)
        assert paragraph._p.pPr.xml==original._p.pPr.xml
        # The same official template/context with an absent pumping chart is a
        # package reference: styles and every non-pumping page/table stay exact.
        template=DocxTemplate(report.TEMPLATE_PATH);template.render(report._word_quantity_context(context));raw=BytesIO();template.save(raw)
        reference=well_report.postprocess_well_report(raw.getvalue(),context['well_profile_report'],context['note_vertical'],context['cement_chart_report'],context['centralizer_report'],pumping_report={'applicable':False},schematic_report=bridge.prepare_schematic(state),section_vi_programs={k:context[k] for k in ('has_preflush','has_spacer')})
        ref=Document(BytesIO(reference));refp=next(p for p in ref.paragraphs if p.text=='Pumping simulation charts: Not applicable.')
        paragraph._p.getparent().remove(paragraph._p);refp._p.getparent().remove(refp._p)
        # One inserted image renumbers OOXML drawing IDs/relationships. Bind
        # every remaining reference to its actual bytes before normalizing IDs.
        from docx.oxml.ns import qn
        for current in (doc,ref):
            for index,node in enumerate(current._element.xpath('.//wp:docPr')):
                node.set('id',str(index));node.set('name','Picture '+str(index))
            for node in current._element.xpath('.//a:blip'):
                key=qn('r:embed');node.set(key,hashlib.sha256(current.part.related_parts[node.get(key)].blob).hexdigest())
            for node in current._element.xpath('.//pic:cNvPr'):
                node.set('name','image.png')
        assert doc._element.xml==ref._element.xml
        with ZipFile(BytesIO(output['bytes'])) as z,ZipFile(BytesIO(reference)) as base:
            for part in base.namelist():
                if part not in ('word/document.xml','word/_rels/document.xml.rels','[Content_Types].xml') and not part.startswith('word/media/'):
                    assert z.read(part)==base.read(part),part
            extra=set(z.namelist())-set(base.namelist())
            assert len(extra)==1 and next(iter(extra)).startswith('word/media/')
            assert any(z.read(n)==png.getvalue() for n in z.namelist() if n.startswith('word/media/'))
        assert output['qualification']=='NOT_GRANTED' and '67.264' not in '\n'.join(p.text for p in doc.paragraphs)
        assert pickle.dumps((state,context,r))==before and plt.get_fignums()==baseline
        bad_state=deepcopy(state);bad_context=deepcopy(context)
        bad_state['_cement_chart_model']=None;bad_context['cement_chart_report']['model']=None
        with pytest.raises(ValueError):
            bridge.prepare_shadow(bad_state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),word_context=bad_context)
        processor=bridge.postprocess_well_report
        for fault in ('missing','duplicate'):
            def broken(raw,*args,**kwargs):
                changed=Document(BytesIO(raw));anchor=next(p for p in changed.paragraphs if p.text==well_report.PUMPING_CHART_ANCHOR)
                if fault=='missing':anchor._p.getparent().remove(anchor._p)
                else:changed.add_paragraph(well_report.PUMPING_CHART_ANCHOR)
                data=BytesIO();changed.save(data)
                return processor(data.getvalue(),*args,**kwargs)
            with monkeypatch.context() as m:
                m.setattr(bridge,'postprocess_well_report',broken)
                with pytest.raises(ValueError,match='anchor'):
                    bridge.shadow_word_bytes(state,r,context,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
            assert plt.get_fignums()==baseline
        changed=deepcopy(context);changed['procedure']='late context edit'
        monkeypatch.setattr(bridge,'DocxTemplate',lambda *a:pytest.fail('Stale context created Word'))
        with pytest.raises(ValueError):bridge.shadow_word_bytes(state,r,changed,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
    finally:plt.close(other)


# Batch A Rev3: explicit diagnostic consumer, never production admission.
def batcha_assert_imports(path):
    import ast
    tree=ast.parse(path.read_text())
    expected={'dataclasses':('dataclass','field','fields'),'fractions':('Fraction',),
        'DOC58_SI_CANDIDATE_03_TF2R_ER03':('GeometrySpec','PipeSection','AnnSection'),
        'cement_chart_model':('_capacity',),'materials_db':('PLACEMENT_SLURRIES',),
        'project_state':('fingerprint',),'cfw128_integration_abi':('compose_nominal_tracking',),
        'cfw128_er03_numeric_adapter':('NumericEvidence','_primitive'),
        'cfw128_c2e7_native_placement':('assess_native_placement','_map_static'),
        'cfw128_c2e3_post_pull_gap':('audit_post_pull_gap',)}
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert len(nodes)==len(expected) and {n.module:tuple(a.name for a in n.names) for n in nodes}==expected
    assert all(n.level==0 and all(a.asname is None for a in n.names) for n in nodes)
    assert [(a.name,a.asname) for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]==[('math',None)]
    forbidden={'eval','exec','__import__','import_module','open','run_numeric_test_case','simulate',
               'render_three_charts','render_numeric_test_charts','run_pumping_simulation'}
    assert not forbidden & {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
    assert not forbidden & {n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}


@pytest.mark.parametrize('job',BUG01_JOBS)
@pytest.mark.parametrize('volume',[1.,40.,200.])
def test_cfw128_batcha_native_reconstruction_matrix(gate7_cases,job,volume):
    from cfw128_c2e8_post_pull_review import assess_post_pull,validate_post_pull_review,PostPullConditions
    from cfw128_c2e7_native_placement import assess_native_placement
    state,r,b=gate7_cases[job,volume];old=assess_native_placement(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    before=pickle.dumps((state,r,old));conditions=PostPullConditions(True,True,True)
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=conditions)
    validate_post_pull_review(state,r,a,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=conditions)
    assert a.eod_balances==old.fluid_balances and a.prior_static_candidate_md==old.static_candidate_md
    assert set(old.holds)<=set(a.holds)
    assert a.currentness=='NOT_CURRENTNESS_PROOF' and a.qualification=='NOT_GRANTED'
    assert a.final_field_toc=='FINAL_FIELD_TOC_NOT_EVALUATED'
    assert all(getattr(a,n) is False for n in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
    assert pickle.dumps((state,r,assess_native_placement(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA)))==before
    if old.kind=='casing':
        assert a.additional_mud_bbl is None and a.returned_dp_mud==a.withdrawn_sections==a.post_pull_balances==()
        assert a.surface_status=='HOLD_SURFACE_NOT_PROVED'
    else:
        assert a.withdrawn_sections and a.annular_bands,a.case_holds
        assert a.additional_mud_bbl>0
        assert all(n in ('Mud','Displacement Fluid') for n,v in a.returned_dp_mud)
        assert all(abs(row[-1])<=1e-9 for row in a.post_pull_balances)
        assert 'HOLD_NATIVE_CANONICAL_VOLUME_BASIS' in a.case_holds
        assert all(t<b and v>0 for n,origin,t,b,v,ratio in a.annular_bands)
        assert all(x[2]>=y[3] for x,y in zip(a.annular_bands,a.annular_bands[1:]))
        if old.static_candidate_md is not None:assert a.achieved_cement_top_md==old.static_candidate_md
    if volume==1.:
        terminal=math.fsum(v for n,role,t,bot,v,ratio,last in a.pipe_bands if last and n=='Main')
        assert terminal<=1.+1e-9
    if job=='CSG 9 5/8"' and volume==40.:
        assert a.achieved_cement_top_md>0 and 'HOLD_SURFACE_NOT_PROVED' in a.case_holds


@pytest.mark.parametrize('condition,reason',[
    ((False,True,True),'HOLD_CONNECTED_RETURN_NOT_PROVED'),
    ((True,False,True),'HOLD_LOSS_OR_UNRECORDED_RETURN'),
    ((True,True,False),'HOLD_DP_MUD_RECOVERY_UNPROVED')])
def test_cfw128_batcha_unsupported_conditions_hold(gate7_cases,condition,reason):
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    state,r,b=gate7_cases['LNR 7"',200.]
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=PostPullConditions(*condition))
    assert reason in a.case_holds and a.annular_bands==a.post_pull_balances==()
    assert a.achieved_cement_top_md is None and a.additional_mud_bbl is None
    with pytest.raises(TypeError):PostPullConditions(1,True,True)


@pytest.mark.parametrize('fault',['volume','density','rate','lab','geometry','job','numeric','missing_native',
    'receipt','resigned_bands','resigned_return','resigned_makeup','resigned_surface','resigned_conditions','flag'])
def test_cfw128_batcha_fresh_validation_rejects_mutation(gate7_cases,fault):
    from dataclasses import replace,fields
    from project_state import fingerprint
    from cfw128_er03_numeric_adapter import _primitive
    from cfw128_c2e8_post_pull_review import assess_post_pull,validate_post_pull_review,PostPullConditions,SCHEMA
    state,r,b=gate7_cases['LNR 7"',200.];state=deepcopy(state);cond=PostPullConditions(True,True,True)
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)
    if fault in ('volume','density','rate'):
        key={'volume':'volume','density':'density','rate':'pump_rate'}[fault]
        state['fluids_config']['params']['Main'][key]=999.
    elif fault=='lab':state['lab_qc_params']['Main']['rheology']['bhct_down']['readings']['300']=999.
    elif fault=='geometry':state['hardware_table'].at[0,'ID (in)']=8.5
    elif fault=='job':state['job_type']='TIE BACK LNR 7"'
    elif fault=='numeric':r=replace(r,projection_identity='0'*64)
    elif fault=='missing_native':r=replace(r,native_observation=None)
    else:
        a=deepcopy(a)
        if fault=='receipt':object.__setattr__(a,'projection_identity','0'*64)
        elif fault=='flag':object.__setattr__(a,'enabled',True)
        else:
            key,value={'resigned_bands':('annular_bands',()),'resigned_return':('returned_dp_mud',()),
                'resigned_makeup':('additional_mud_bbl',0.),'resigned_surface':('surface_status','CEMENT_TO_SURFACE_PROVED'),
                'resigned_conditions':('conditions',PostPullConditions(False,True,True))}[fault]
            object.__setattr__(a,key,value)
            values=tuple(getattr(a,f.name) for f in fields(a) if f.init and f.name!='projection_identity')
            object.__setattr__(a,'projection_identity',fingerprint([SCHEMA,_primitive(values)]))
    with pytest.raises((ValueError,TypeError)):
        validate_post_pull_review(state,r,a,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)


def test_cfw128_batcha_casing_actual_surface_return_is_native_only(gate7_cases):
    from dataclasses import replace
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    state,r,b=gate7_cases['CSG 9 5/8"',200.];state=deepcopy(state)
    state['fluids_config']['params']['Main'].update(volume=800.,pump_rate=200.)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping='event_aligned_test_only')
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=PostPullConditions(True,True,True))
    assert all(n=='Main' for n,v in r.native_observation.payload[3][2])
    main=next(row for row in a.eod_balances if row[0]=='Main')
    assert main[3]>0 and main[2]==800. and abs(main[-1])<=1e-9
    assert a.surface_status=='CEMENT_TO_SURFACE_PROVED_IN_NATIVE_MODEL' and a.achieved_cement_top_md==0.
    assert 'CASING_SURFACE_VOLUME_CANONICAL_CAPACITY_NOT_PROVED' in a.holds
    assert 'CASING_PLUG_BUMP_NOT_PROVED' in a.holds and a.prior_static_candidate_md is None
    assert a.additional_mud_bbl is None and a.returned_dp_mud==()
    # A re-signed counterfeit within the older bookkeeping audit bound must
    # not turn an underfilled annulus into an exact native surface claim.
    payload=list(r.native_observation.payload);eod=list(payload[3]);n,value=eod[2][0]
    eod[2]=((n,value-1e-10),);payload[3]=tuple(eod)
    bad=gate4f_resign(replace(r,native_observation=replace(r.native_observation,payload=tuple(payload))))
    held=assess_post_pull(state,bad,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=PostPullConditions(True,True,True))
    assert held.surface_status=='HOLD_SURFACE_NOT_PROVED'


def test_cfw128_batcha_import_firewall_negative_and_production_isolation(monkeypatch):
    import ast
    from pathlib import Path
    path=Path('cfw128_c2e8_post_pull_review.py');batcha_assert_imports(path);read=Path.read_text
    for added in ('\nfrom cfw128_er03_numeric_adapter import run_numeric_test_case\n',
                  '\nimport pumping_simulation\n','\nGeometrySpec.simulate()\n'):
        with monkeypatch.context() as m:
            m.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+added if p==path else read(p,*a,**k))
            with pytest.raises(AssertionError):batcha_assert_imports(path)
    for other in Path('.').glob('*.py'):
        if other==path:continue
        if other.name=='cfw128_shadow_word_bridge.py':
            gate8_assert_imports(other);continue
        tree=ast.parse(other.read_text())
        assert not any(isinstance(n,ast.ImportFrom) and n.module==path.stem or
            isinstance(n,ast.Import) and any(a.name==path.stem for a in n.names) for n in ast.walk(tree))


def batcha_homogeneous_source(base,job='LNR 7"',volume=70.,geometry=None):
    # Existing Gate6A homogeneous synthetic control; real existing readings and
    # the repository's synthetic review procedure, not invented field evidence.
    from project_state import lab_source_signature
    from engineering_tools import lab_review_signature
    from cfw128_integration_abi import compose_nominal_tracking
    state=gate3_case(base,job)
    if geometry is not None:
        for key in ('job_type','hardware_table','placement_config','well_geometry'):state[key]=deepcopy(geometry[key])
    state['fluids_config']['params']['Main'].update(volume=volume,pump_rate=volume/4.,density='80')
    state['lab_source_signatures']['Main']=lab_source_signature(state,'Main')
    state['lab_qc_params']['Main']['review_signature']=lab_review_signature(state['lab_qc_params']['Main'],state['lab_grid_dfs']['Main'])
    c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']=c.displacement.derived_displacement_bbl/4.
    return state


@pytest.mark.parametrize('job,volume,region',[
    ('LNR 7"',10.,'BELOW_LAP'),('LNR 7"',70.,'ABOVE_LAP'),('LNR 7"',200.,'ABOVE_LAP'),
    ('TIE BACK LNR 7"',10.,'BELOW_LAP'),('TIE BACK LNR 7"',50.,'ABOVE_LAP'),('TIE BACK LNR 7"',200.,'ABOVE_LAP')])
def test_cfw128_batcha_ordered_front_is_not_hydraulic_outlet(bug01_reviewed_report_base,job,volume,region):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    state=batcha_homogeneous_source(bug01_reviewed_report_base,job,volume)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),stepping='event_aligned_test_only')
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=PostPullConditions(True,True,True))
    assert a.region==region and a.achieved_cement_top_md>0,a.case_holds
    assert all(row[0] in ('Main','Mud','Displacement Fluid') for row in a.annular_bands)
    assert all(abs(row[-1])<=1e-9 for row in a.post_pull_balances)
    mouth=next(row[3] for row in a.eod_balances if row[0]=='Main')
    assert (mouth>0)==(volume==200.)
    assert a.basis=='POST_PULL_IDEALIZED_STATIC_CANDIDATE'
    assert 'WITHDRAWAL_RETURN_ORDER_NOT_OBSERVED' in a.holds


def test_cfw128_batcha_actual_nonmud_dp_and_terminal_split_hold(bug01_reviewed_report_base):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    geometry=synthetic_tieback(top=676.)
    frame=geometry['hardware_table'];i=frame.index[frame.Description=='Drill Pipes'][0]
    frame.at[i,'Size (in)']='5';frame.at[i,'ID (in)']=4.276
    state=batcha_homogeneous_source(bug01_reviewed_report_base,'TIE BACK LNR 7"',200.,geometry)
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary(),stepping='event_aligned_test_only')
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=PostPullConditions(True,True,True))
    assert 'HOLD_DP_CONTAINS_NONMUD' in a.case_holds
    assert 'HOLD_TERMINAL_INTERVAL_CROSSES_WITHDRAWABLE_DP' in a.case_holds
    assert {'WITHDRAWABLE_DP','INSTALLED_BODY'}=={row[1] for row in a.pipe_bands if row[-1] and row[0]=='Main'}
    assert a.additional_mud_bbl is None and a.returned_dp_mud==a.annular_bands==()
    assert a.achieved_cement_top_md is None


def test_cfw128_batcha_directional_tail_terminal_and_readonly_pixels(gate7_cases,monkeypatch):
    from dataclasses import replace
    import cfw128_er03_numeric_adapter as adapter
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    import matplotlib.pyplot as plt
    import numpy as np
    state,r,b=gate7_cases['LNR 7"',200.];cond=PostPullConditions(True,True,True)
    zero=adapter.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=replace(b,tail_cap_min=0.),stepping='event_aligned_test_only')
    assert zero.native_observation.payload[2][-1][2]==0.
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)
    z=assess_post_pull(state,zero,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)
    assert a.annular_bands==z.annular_bands and a.eod_balances==z.eod_balances
    assert r.native_observation.payload[3]!=r.native_observation.payload[4]
    direction=deepcopy(state);direction['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    dr=adapter.run_numeric_test_case(direction,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine='directional',stepping='event_aligned_test_only')
    da=assess_post_pull(direction,dr,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)
    assert da.achieved_cement_top_md==a.achieved_cement_top_md and dr.trajectory_source=='APP_DIRECTIONAL_STATION_TVD_V1'
    fig=adapter.render_numeric_test_charts(r);fig.canvas.draw();pixels=np.asarray(fig.canvas.buffer_rgba()).copy();plt.close(fig)
    before=pickle.dumps((state,r));monkeypatch.setattr(adapter.event_vertical,'simulate',lambda *a:pytest.fail('Static review invoked a solver'))
    assert assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)==a
    assert pickle.dumps((state,r))==before
    fig=adapter.render_numeric_test_charts(r);fig.canvas.draw();assert np.array_equal(pixels,np.asarray(fig.canvas.buffer_rgba()));plt.close(fig)


@pytest.mark.parametrize('scavenger',[False,True])
def test_cfw128_batcha_multiple_stage_identities_and_order(gate7_cases,scavenger):
    from project_state import lab_source_signature
    from engineering_tools import lab_review_signature
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    state,r,b=gate7_cases['LNR 7"',200.];state=deepcopy(state)
    state['fluids_config']['params']['Main'].update(volume=100.,pump_rate=25.)
    names=('Tail','Scavenger') if scavenger else ('Tail',)
    for name in names:
        state['fluids_config']['active'].insert(0,name)
        state['fluids_config']['params'][name]=deepcopy(state['fluids_config']['params']['Main'])
        for key in ('cement_params','fluid_data','cement_additives_dfs','lab_grid_dfs','lab_qc_params'):
            state[key][name]=deepcopy(state[key]['Main'])
        state['lab_source_signatures'][name]=lab_source_signature(state,name)
        state['lab_qc_params'][name]['review_signature']=lab_review_signature(state['lab_qc_params'][name],state['lab_grid_dfs'][name])
    from dataclasses import replace
    b=replace(b,gel_pa_by_fluid=(*b.gel_pa_by_fluid,*((n,25.) for n in names)))
    r=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,stepping='event_aligned_test_only')
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=PostPullConditions(True,True,True))
    assert {'Main','Tail'}<=set(row[0] for row in a.annular_bands)
    assert [row[0] for row in r.stages]==[*(['Scavenger'] if scavenger else []),'Main','Tail','Displacement Fluid']
    assert all(abs(row[-1])<=1e-9 for row in a.post_pull_balances)
    if scavenger:assert any(row[0]=='Scavenger' for row in a.eod_balances)


def test_cfw128_batcha_frozen_uat19_missing_source_and_false_geometry_hold(gate7_cases):
    from cfw128_er03_numeric_adapter import run_numeric_test_case
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    state,r,b=gate7_cases['LNR 7"',40.];cond=PostPullConditions(True,True,True)
    frozen=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    a=assess_post_pull(state,frozen,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)
    assert a.case_holds==('HOLD_NATIVE_EOD_ABSENT',) and a.annular_bands==()
    uat=cfw128_c1_uat19_state()
    with pytest.raises((ValueError,KeyError)):
        assess_post_pull(uat,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)
    gap=deepcopy(state);frame=gap['hardware_table'];i=frame.index[frame.Description=='Drill Pipes'][0]
    frame.at[i,'MD (m)']='1-400'
    with pytest.raises(ValueError):assess_post_pull(gap,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)


@pytest.mark.parametrize('job',['CSG 9 5/8"','LNR 7"','TIE BACK LNR 7"'])
def test_cfw128_batcha_independent_fluid_and_section_ledger(gate7_cases,job):
    from fractions import Fraction
    from cfw128_integration_abi import compose_nominal_tracking
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    from cfw128_c2e6b_dry_pipe_mud_makeup import _product_bounds,_intersect
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as v
    state,r,b=gate7_cases[job,40. if job.startswith('CSG') else 200.]
    a=assess_post_pull(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=PostPullConditions(True,True,True))
    c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA);eod=r.native_observation.payload[3]
    # Independently start with raw observation tokens, not the new ledger.
    for name,initial,injected,mouth,head,pipe,ann,residual in a.eod_balances:
        assert abs(math.fsum((initial,injected,-mouth,-head,-pipe,-ann)))<=1e-9
        actual_pipe=math.fsum(amount for fluid,amount in eod[1] if fluid==name)
        actual_ann=math.fsum(amount for fluid,amount in eod[2] if fluid==name)
        assert pipe==actual_pipe and ann==actual_ann
    if c.captured_geometry.kind=='casing':
        assert a.basis=='CASING_NATIVE_PUMP_END_NO_DP_PULL' and a.achieved_cement_top_md>0
        return
    native_dp=math.fsum(math.pi/4*(p.id_in*.0254)**2/v.BBL_TO_M3*(p.bottom_md-p.top_md)
        for p in c.captured_geometry.active_sections if p.bottom_md<=c.captured_geometry.string_top_md)
    assert math.isclose(math.fsum(amount for name,amount in a.returned_dp_mud),native_dp,rel_tol=0.,abs_tol=1e-9)
    for left,right,native,inner,outer,steel,residual in a.withdrawn_sections:
        p=next(p for p in c.captured_geometry.active_sections if p.top_md<=left and right<=p.bottom_md)
        length=right-left
        # Existing captured-product bounds, not a new geometric tolerance.
        ob=_product_bounds(p.od_in,0.,length,outer);ib=_product_bounds(p.id_in,0.,length,inner)
        _intersect((ob[0]-ib[1],ob[1]-ib[0]),_product_bounds(p.od_in,p.id_in,length,steel))
    for name,before_pipe,before_ann,external,after_pipe,after_ann,residual in a.post_pull_balances:
        moved=math.fsum(value for fluid,value in a.returned_dp_mud if fluid==name)
        assert after_pipe==float(Fraction(before_pipe)-sum((Fraction(value) for fluid,value in a.returned_dp_mud if fluid==name),Fraction()))
        exact_ann=sum((Fraction(*row[5]) for row in a.annular_bands if row[0]==name),Fraction())
        assert after_ann==float(exact_ann) and abs(residual)<=1e-9
        if name!='Displacement Fluid':assert external==0.
        # Each band's source amount is recovered independently from the raw EOD
        # annulus or internal transfer; do not double-count recovered DP Mud.
        for origin,expected in [('NATIVE_EOD_ANNULUS',before_ann),('RETURNED_DP_INTERNAL',moved),('EXTERNAL_MAKEUP_MUD',external)]:
            got=sum((Fraction(*row[5]) for row in a.annular_bands if row[0]==name and row[1]==origin),Fraction())
            assert abs(got-Fraction(expected))<=Fraction(1e-9)


@pytest.mark.parametrize('fault',['negative_qout','missing_native','swapped_placement','wrong_engine','frozen'])
def test_cfw128_gate8_resigned_receipts_still_reject(gate8_cases,fault,monkeypatch):
    from dataclasses import replace
    from project_state import fingerprint
    from cfw128_er03_numeric_adapter import _primitive,run_numeric_test_case
    from cfw128_c2e7_native_placement import assess_native_placement
    import cfw128_shadow_word_bridge as bridge
    state,b,r=gate8_cases['LNR 7"'];numeric=r.numeric;placement=r.placement;engine=r.engine;source=r.source_identity
    if fault=='negative_qout':numeric=gate4f_resign(replace(numeric,q_out_bpm=(-1.,*numeric.q_out_bpm[1:])))
    elif fault=='missing_native':numeric=gate4f_resign(replace(numeric,native_observation=None))
    elif fault=='swapped_placement':placement=gate8_cases['CSG 9 5/8"'][2].placement
    elif fault=='wrong_engine':engine='directional';source=bridge._source(state,GATE3_APP_SOURCE_SHA,b,engine)
    else:
        numeric=run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
        placement=assess_native_placement(state,numeric,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    identity=fingerprint([bridge.SCHEMA,r.app_source_sha,source,_primitive(b),engine,_primitive(numeric),_primitive(placement),r.context_identity,r.document_identity])
    bad=replace(r,numeric=numeric,placement=placement,engine=engine,source_identity=source,projection_identity=identity)
    monkeypatch.setattr(bridge,'render_numeric_test_charts',lambda *a:pytest.fail('Forged evidence rendered'))
    with pytest.raises(ValueError):
        with bridge.shadow_pumping_report(state,bad,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b):pass


def test_cfw128_gate8_no_annular_cement_and_zero_stage_hold(bug01_reviewed_report_base):
    import cfw128_shadow_word_bridge as bridge
    state=gate3_case(bug01_reviewed_report_base)
    r=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())
    assert r.placement.annular_cement_bbl==0. and r.placement.static_candidate_md is None
    assert 'NO_NATIVE_ANNULAR_CEMENT' in r.placement.case_holds
    state['fluids_config']['params']['Main']['volume']=0.
    with pytest.raises(ValueError):bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=gate3_boundary())


@pytest.fixture(scope='module')
def gate8p_cases(bug01_reviewed_report_base):
    # Exact Gate8V common-control source preparation; no field values inferred.
    from dataclasses import replace
    from unittest.mock import patch
    from project_state import prepare_calculations,lab_source_signature,mud_lab_source_signature
    from engineering_tools import lab_review_signature
    from cfw128_integration_abi import compose_nominal_tracking
    from centralizer_fixtures import execute_centralizer
    import phase_10_procedure as report
    import cfw128_shadow_word_bridge as bridge
    cases={}
    for job in ('CSG 9 5/8"','LNR 7"','TIE BACK LNR 7"'):
        state=gate3_case(bug01_reviewed_report_base,job)
        state['fluids_config']['params']['Main'].update(volume=40.,pump_rate=10.)
        state['fluids_config']['params']['Displacement Fluid']['volume']=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA).displacement.derived_displacement_bbl
        prepare_calculations(state)
        for name in ('Main','Displacement Fluid'):
            state['lab_source_signatures'][name]=lab_source_signature(state,name) if name=='Main' else mud_lab_source_signature(state)
            qc=state['lab_qc_params'][name];qc['reviewed']=True
            qc['review_signature']=lab_review_signature(qc,state['lab_grid_dfs'].get(name))
        execute_centralizer(state)
        with patch.object(report.st,'session_state',state):context=report.build_master_context()
        inputs=pumping_simulation.prepare_pumping_simulation(state)['inputs']
        gel=inputs['slurry_rheology']['Main']['gel_10_min']*pumping_simulation.fcm.LBF100FT2_TO_PA
        b=replace(gate3_boundary(),back_pressure_psi=inputs['options'].back_pressure_psi,
            bhsp_target_psi=pumping_simulation.fcm.parse_bhsp_psi(inputs['bhsp']),surface_line_kpsi_at_8bpm=inputs['options'].surface_line_kpsi_at_8bpm,
            gel_pa_by_fluid=(('Main',gel),('Displacement Fluid',0.),('Mud',0.)))
        cases[job]=(state,b,bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,word_context=context),context)
    return cases


@pytest.mark.parametrize('job',['CSG 9 5/8"','LNR 7"','TIE BACK LNR 7"'])
def test_cfw128_gate8p_terminal_interval_projection(gate8p_cases,job,monkeypatch):
    import cfw128_er03_numeric_adapter as a
    import matplotlib.pyplot as plt
    state,b,shadow,context=gate8p_cases[job];r=shadow.numeric;before=pickle.dumps((state,shadow,context))
    rows=r.native_observation.payload[2];eod=r.native_observation.payload[3]
    assert rows[-1][:3]==(8.,8.,0.) and not rows[-1][5] and all(not tokens for port,tokens in rows[-1][6])
    assert eod==r.native_observation.payload[4] and r.time_min[-2:]==(7.75,8.)
    assert r.q_in_bpm[-2]>0 and r.q_in_bpm[-1]==r.q_out_bpm[-1]==0
    seen={};original=a.render_three_charts
    def capture(spec):seen['spec']=spec;return original(spec)
    monkeypatch.setattr(a,'render_three_charts',capture)
    fig=a.render_numeric_test_charts(r)
    try:
        spec=seen['spec']
        assert tuple(spec.calc_cem_hp[0])==r.time_min[:-1]
        for name,raw in (('calc_cem_hp',r.whp_kpsi),('calc_pump_press',r.pump_kpsi),('hydrostatic',r.hydrostatic_kpsi),('dynamic',r.total_pressure_kpsi),('q_in',r.q_in_bpm),('q_out',r.q_out_bpm)):
            assert tuple(getattr(spec,name)[1])==raw[:-1]
        assert spec.axis_x==a.autoscale_x(r.time_min[-1]) and 8. in spec.event_times
        assert spec.axis_y2==a.autoscale_y(min(*r.hydrostatic_kpsi,*r.total_pressure_kpsi),max(*r.hydrostatic_kpsi,*r.total_pressure_kpsi),zero_based=False)
        assert pickle.dumps((state,shadow,context))==before
    finally:plt.close(fig)


@pytest.mark.parametrize('engine',['vertical','directional'])
@pytest.mark.parametrize('mode',['zero_tail','real_tail','shutin'])
def test_cfw128_gate8p_native_domains(gate8p_cases,engine,mode,monkeypatch):
    from dataclasses import replace
    from project_state import lab_source_signature
    from engineering_tools import lab_review_signature
    import cfw128_er03_numeric_adapter as a
    import matplotlib.pyplot as plt
    state,b,shadow,context=gate8p_cases['LNR 7"'];state=deepcopy(state)
    b=replace(b,bhsp_target_psi=None)
    if engine=='directional':state['well_geometry']={'type':'Directional','survey':pd.DataFrame([[0.,0.,0.],[100.,60.,0.],[1200.,60.,0.]],columns=['MD','Deviation','Azimuth'])}
    if mode=='real_tail':b=replace(b,tail_cap_min=.35)
    if mode=='shutin':
        # Reuse Gate6A's actual homogeneous-fluid shut-in control; not a field
        # pressure certificate. Existing source/review authorities stay intact.
        state['fluids_config']['params']['Main']['density']='80'
        state['lab_source_signatures']['Main']=lab_source_signature(state,'Main')
        state['lab_qc_params']['Main']['review_signature']=lab_review_signature(state['lab_qc_params']['Main'],state['lab_grid_dfs']['Main'])
        b=replace(b,bhsp_target_psi=5000.,gel_pa_by_fluid=tuple((n,25.) for n,v in b.gel_pa_by_fluid))
    r=a.run_numeric_test_case(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,engine=engine,stepping='event_aligned_test_only')
    before=pickle.dumps(r);seen={};original=a.render_three_charts
    def capture(spec):seen['spec']=spec;return original(spec)
    monkeypatch.setattr(a,'render_three_charts',capture)
    fig=a.render_numeric_test_charts(r)
    try:
        expected=r.time_min[:-1] if mode=='zero_tail' else r.time_min
        assert tuple(seen['spec'].q_out[0])==expected
        if mode=='real_tail':
            assert any(row[1]>dict(r.events)['t_eod'] and row[2]>0 for row in r.native_observation.payload[2])
            assert any(q>0 for t,q in zip(r.time_min,r.q_out_bpm) if t>dict(r.events)['t_eod'])
        if mode=='shutin':
            assert dict(r.events)['t_shutin'] is not None and r.time_min[-1]>dict(r.events)['t_eod']
        assert pickle.dumps(r)==before
    finally:plt.close(fig)


@pytest.mark.parametrize('fault',['frozen','no_eod','no_transition','interior_drop','marker_at_eod','missing_native','forged_source'])
def test_cfw128_gate8p_ambiguous_or_invalid_records(gate8p_cases,gate4f_precomputed,fault,monkeypatch):
    from dataclasses import replace
    import cfw128_er03_numeric_adapter as a
    import matplotlib.pyplot as plt
    r=gate8p_cases['LNR 7"'][2].numeric
    if fault=='missing_native':r=replace(r,native_observation=None)
    elif fault=='forged_source':r=replace(r,source_identity='0'*64)
    elif fault=='no_eod':r=gate4f_resign(gate4f_precomputed,events=tuple((n,None if n=='t_eod' else v) for n,v in gate4f_precomputed.events))
    elif fault=='marker_at_eod':r=gate4f_resign(r,events=tuple((n,8. if n in ('t_marker','t_shutin') else v) for n,v in r.events))
    else:
        r=gate4f_precomputed
        if fault=='no_transition':r=gate4f_resign(r,q_in_bpm=(0.,)*5,q_out_bpm=(0.,)*5)
        elif fault=='interior_drop':r=gate4f_resign(r,whp_kpsi=(.2,.4,0.,.3,.2))
    before=pickle.dumps(r);seen={};original=a.render_three_charts
    def capture(spec):seen['spec']=spec;return original(spec)
    monkeypatch.setattr(a,'render_three_charts',capture)
    if fault in ('no_eod','missing_native','forged_source'):
        with pytest.raises(ValueError):a.render_numeric_test_charts(r)
        assert not seen
    else:
        fig=a.render_numeric_test_charts(r)
        try:
            assert tuple(seen['spec'].calc_cem_hp[0])==r.time_min
            assert tuple(seen['spec'].calc_cem_hp[1])==r.whp_kpsi
            if fault=='marker_at_eod':assert seen['spec'].marker_time is None and 8. in seen['spec'].event_times
        finally:plt.close(fig)
    assert pickle.dumps(r)==before


def test_cfw128_gate8p_shadow_word_and_legacy_package_unchanged(gate8p_cases):
    from io import BytesIO
    from zipfile import ZipFile
    from docx import Document
    from docxtpl import DocxTemplate
    import phase_10_procedure as report
    import cfw128_shadow_word_bridge as bridge
    import matplotlib.pyplot as plt
    state,b,shadow,context=gate8p_cases['CSG 9 5/8"'];before=pickle.dumps((state,shadow,context))
    template=DocxTemplate(report.TEMPLATE_PATH);template.render(report._word_quantity_context(context));raw=BytesIO();template.save(raw)
    def pack(p):
        return bridge.postprocess_well_report(raw.getvalue(),context['well_profile_report'],context['note_vertical'],context['cement_chart_report'],context['centralizer_report'],pumping_report=p,schematic_report=bridge.prepare_schematic(state),section_vi_programs={k:context[k] for k in ('has_preflush','has_spacer')})
    legacy=pumping_simulation.run_pumping_simulation(state)
    try:
        image=BytesIO();legacy['figure'].savefig(image,format='png',dpi=200,facecolor='white');old_png=image.getvalue();old_word=pack(legacy)
    finally:plt.close(legacy['figure'])
    with bridge.shadow_pumping_report(state,shadow,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b) as p:
        image=BytesIO();p['figure'].savefig(image,format='png',dpi=200,facecolor='white');shadow_png=image.getvalue()
    output=bridge.shadow_word_bytes(state,shadow,context,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    doc=Document(BytesIO(output['bytes']));paragraph=next(p for p in doc.paragraphs if p._p.xpath('.//wp:docPr[@descr="Pumping Simulation Charts"]'))
    assert doc.part.related_parts[paragraph._p.xpath('.//a:blip/@r:embed')[0]].blob==shadow_png
    legacy=pumping_simulation.run_pumping_simulation(state)
    try:
        image=BytesIO();legacy['figure'].savefig(image,format='png',dpi=200,facecolor='white')
        assert image.getvalue()==old_png
        with ZipFile(BytesIO(old_word)) as old,ZipFile(BytesIO(pack(legacy))) as new:
            assert old.namelist()==new.namelist()
            assert all(old.read(n)==new.read(n) for n in old.namelist())
    finally:plt.close(legacy['figure'])
    assert pickle.dumps((state,shadow,context))==before


def test_cfw128_gate8_import_route_and_cleanup(gate8_cases,monkeypatch):
    from pathlib import Path
    import cfw128_shadow_word_bridge as bridge
    import matplotlib.pyplot as plt
    path=Path('cfw128_shadow_word_bridge.py');gate8_assert_imports(path)
    read=Path.read_text
    with monkeypatch.context() as m:
        m.setattr(Path,'read_text',lambda p,*a,**k:read(p,*a,**k)+'\nimport pumping_simulation\n' if p==path else read(p,*a,**k))
        with pytest.raises(AssertionError):gate8_assert_imports(path)
    for name in ('main.py','phase_10_procedure.py','pumping_simulation.py','well_report.py'):
        assert 'cfw128_shadow_word_bridge' not in Path(name).read_text()
    state,b,r=gate8_cases['LNR 7"'];other=plt.figure();initial=plt.get_fignums()
    try:
        with pytest.raises(RuntimeError):
            with bridge.shadow_pumping_report(state,r,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b):raise RuntimeError('later failure')
        assert plt.get_fignums()==initial
    finally:plt.close(other)


@pytest.mark.parametrize('job',BUG01_JOBS)
def test_cfw128_batchb_sidecar_eight_job_runtime_matrix(gate8_cases,job,monkeypatch):
    import cfw128_shadow_word_bridge as bridge
    import cfw128_er03_numeric_adapter as adapter
    from cfw128_c2e8_post_pull_review import PostPullConditions,PostPullReview
    state,b,parent=gate8_cases[job];before=pickle.dumps((state,parent))
    for solver in (adapter.event_vertical,adapter.event_directional):
        monkeypatch.setattr(solver,'simulate',lambda *a:pytest.fail('Sidecar ran a second solver'))
    monkeypatch.setattr(bridge,'run_numeric_test_case',lambda *a,**k:pytest.fail('Sidecar reran numeric intake'))
    cond=PostPullConditions(True,True,True)
    child=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=cond)
    bridge.validate_shadow_post_pull(state,parent,child,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=cond)
    assert type(child) is bridge.ShadowPostPullEvidence and type(child.review) is PostPullReview
    assert child.shadow_identity==parent.projection_identity and child.source_identity==parent.source_identity
    assert child.review.numeric_identity==parent.numeric.projection_identity
    assert child.review.placement_identity==parent.placement.projection_identity
    assert child.review.composition_identity==parent.numeric.composition_projection_identity
    assert child.review.eod_balances==parent.placement.fluid_balances
    assert set(parent.placement.holds)<=set(child.review.holds)
    assert all(row[-1]==0. for row in child.review.post_pull_balances)
    assert all(getattr(child,n) is False and getattr(child.review,n) is False for n in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified'))
    if job.startswith('CSG'):
        assert child.review.surface_status=='HOLD_SURFACE_NOT_PROVED' and child.review.additional_mud_bbl is None
    else:
        assert child.review.returned_dp_mud and child.review.additional_mud_bbl>0
        assert child.review.annular_bands and child.review.region=='ABOVE_LAP'
    assert pickle.dumps((state,parent))==before


@pytest.mark.parametrize('fault',['state','job','host','receiver','lab','sha','boundary','conditions','child',
    'resigned_source','resigned_parent','resigned_review','resigned_conditions','flags','late'])
def test_cfw128_batchb_stale_mixed_and_resigned_sidecars_reject(gate8_cases,fault,monkeypatch):
    from dataclasses import replace
    from project_state import fingerprint
    from cfw128_er03_numeric_adapter import _primitive
    from cfw128_c2e8_post_pull_review import PostPullConditions,assess_post_pull
    import cfw128_shadow_word_bridge as bridge
    state,b,parent=gate8_cases['TIE BACK LNR 7"'];state=deepcopy(state);cond=PostPullConditions(True,True,True);sha=GATE3_APP_SOURCE_SHA
    child=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=sha,boundary=b,conditions=cond)
    if fault=='state':state['well_data']['well_name']='Different well, same numeric physics'
    elif fault=='job':state['job_type']='TIE BACK LNR 5"'
    elif fault=='host':state['hardware_table'].at[0,'ID (in)']=8.5
    elif fault=='receiver':
        i=state['hardware_table'].index[state['hardware_table'].Description=='Previous Liner Shoe'][0]
        state['hardware_table'].at[i,'MD (m)']='700-1250'
    elif fault=='lab':state['lab_qc_params']['Main']['reviewed']=False
    elif fault=='sha':sha='0'*40
    elif fault=='boundary':b=replace(b,back_pressure_psi=251.)
    elif fault=='conditions':cond=PostPullConditions(True,True,False)
    elif fault=='child':object.__setattr__(child,'projection_identity','0'*64)
    elif fault=='flags':object.__setattr__(child,'enabled',True)
    elif fault=='late':
        real=bridge.assess_post_pull
        def changed(*a,**k):
            result=real(*a,**k);state['well_data']['well_name']='Late edit';return result
        monkeypatch.setattr(bridge,'assess_post_pull',changed)
        with pytest.raises(ValueError):bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=sha,boundary=b,conditions=cond)
        return
    else:
        child=deepcopy(child)
        if fault=='resigned_source':object.__setattr__(child,'source_identity','0'*64)
        elif fault=='resigned_parent':object.__setattr__(child,'shadow_identity','0'*64)
        elif fault=='resigned_review':object.__setattr__(child,'review',assess_post_pull(gate8_cases['LNR 5"'][0],gate8_cases['LNR 5"'][2].numeric,expected_app_source_sha=sha,conditions=cond))
        else:object.__setattr__(child,'review',assess_post_pull(state,parent.numeric,expected_app_source_sha=sha,conditions=PostPullConditions(False,True,True)))
        object.__setattr__(child,'projection_identity',fingerprint([bridge.POST_PULL_SIDECAR_SCHEMA,child.shadow_identity,child.source_identity,_primitive(child.review)]))
    with pytest.raises((ValueError,TypeError)):
        bridge.validate_shadow_post_pull(state,parent,child,expected_app_source_sha=sha,boundary=b,conditions=cond)


@pytest.mark.parametrize('values,reason',[(None,'typed'),((False,True,True),'HOLD_CONNECTED_RETURN_NOT_PROVED'),
    ((True,False,True),'HOLD_LOSS_OR_UNRECORDED_RETURN'),((True,True,False),'HOLD_DP_MUD_RECOVERY_UNPROVED')])
def test_cfw128_batchb_explicit_conditions_fail_closed(gate8_cases,values,reason):
    import cfw128_shadow_word_bridge as bridge
    from cfw128_c2e8_post_pull_review import PostPullConditions
    state,b,parent=gate8_cases['LNR 7"']
    if values is None:
        with pytest.raises(TypeError):bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=None)
    else:
        a=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=PostPullConditions(*values))
        assert reason in a.review.case_holds and a.review.annular_bands==() and a.review.achieved_cement_top_md is None


def test_cfw128_batchb_word_png_and_legacy_ast_unchanged(gate8p_cases):
    from io import BytesIO
    from zipfile import ZipFile
    from pathlib import Path
    import ast,subprocess
    import cfw128_shadow_word_bridge as bridge
    from cfw128_c2e8_post_pull_review import PostPullConditions
    state,b,parent,context=gate8p_cases['CSG 9 5/8"'];before=pickle.dumps((state,b,parent,context))
    def png():
        with bridge.shadow_pumping_report(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b) as p:
            assert len(p['figure'].axes)==3 and 'post_pull' not in p
            image=BytesIO();p['figure'].savefig(image,format='png',dpi=200,facecolor='white');return image.getvalue()
    original_png=png();original_word=bridge.shadow_word_bytes(state,parent,context,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    sidecar=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=PostPullConditions(True,True,True))
    assert sidecar.review.surface_status=='HOLD_SURFACE_NOT_PROVED'
    assert png()==original_png
    after=bridge.shadow_word_bytes(state,parent,context,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    assert set(after)==set(original_word) and 'post_pull' not in after
    with ZipFile(BytesIO(original_word['bytes'])) as left,ZipFile(BytesIO(after['bytes'])) as right:
        assert left.namelist()==right.namelist() and all(left.read(n)==right.read(n) for n in left.namelist())
    baseline=ast.parse(subprocess.check_output(['git','show','5d26995bc46377119c66fbbe78573d7686acdc91:cfw128_shadow_word_bridge.py'],text=True))
    current=ast.parse(Path('cfw128_shadow_word_bridge.py').read_text())
    for name in ('ShadowEvidence','_source','prepare_shadow','_validate','shadow_pumping_report','shadow_word_bytes'):
        assert ast.dump(next(x for x in baseline.body if getattr(x,'name',None)==name))==ast.dump(next(x for x in current.body if getattr(x,'name',None)==name))
    assert pickle.dumps((state,b,parent,context))==before


@pytest.mark.parametrize('volume,region',[(10.,'BELOW_LAP'),(70.,'ABOVE_LAP')])
def test_cfw128_batchb_real_finite_fronts(bug01_reviewed_report_base,volume,region):
    import cfw128_shadow_word_bridge as bridge
    from cfw128_c2e8_post_pull_review import PostPullConditions
    state=batcha_homogeneous_source(bug01_reviewed_report_base,volume=volume)
    b=gate3_boundary();parent=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    a=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=PostPullConditions(True,True,True))
    assert a.review.region==region and a.review.achieved_cement_top_md>0


def test_cfw128_batchb_native_csg_surface_and_nonmud_dp_hold(gate8_cases,bug01_reviewed_report_base):
    import cfw128_shadow_word_bridge as bridge
    from cfw128_c2e8_post_pull_review import PostPullConditions
    cond=PostPullConditions(True,True,True)
    state,b,parent=gate8_cases['CSG 9 5/8"'];state=deepcopy(state);state['fluids_config']['params']['Main'].update(volume=800.,pump_rate=200.)
    parent=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    a=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=cond)
    assert a.review.surface_status=='CEMENT_TO_SURFACE_PROVED_IN_NATIVE_MODEL' and a.review.achieved_cement_top_md==0.
    assert next(row[3] for row in a.review.eod_balances if row[0]=='Main')>0
    geometry=synthetic_tieback(top=676.);frame=geometry['hardware_table'];i=frame.index[frame.Description=='Drill Pipes'][0]
    frame.at[i,'Size (in)']='5';frame.at[i,'ID (in)']=4.276
    state=batcha_homogeneous_source(bug01_reviewed_report_base,'TIE BACK LNR 7"',200.,geometry)
    b=gate3_boundary();parent=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b)
    a=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=cond)
    assert 'HOLD_DP_CONTAINS_NONMUD' in a.review.case_holds and a.review.annular_bands==()


def test_cfw128_batchb_counterfeit_underfill_and_full_parent_binding(gate8_cases):
    from dataclasses import replace
    from project_state import fingerprint
    from cfw128_er03_numeric_adapter import _primitive
    from cfw128_c2e8_post_pull_review import PostPullConditions
    import cfw128_shadow_word_bridge as bridge
    state,b,parent=gate8_cases['LNR 7"'];cond=PostPullConditions(True,True,True)
    child=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=cond)
    def resign(p):
        object.__setattr__(p,'projection_identity',fingerprint([bridge.SCHEMA,p.app_source_sha,p.source_identity,_primitive(p.boundary),p.engine,_primitive(p.numeric),_primitive(p.placement),p.context_identity,p.document_identity]))
        return p
    other=deepcopy(parent);object.__setattr__(other,'context_identity','d'*64);resign(other)
    with pytest.raises(ValueError):bridge.validate_shadow_post_pull(state,other,child,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=cond)
    for delta in (-1.,1.):
        payload=list(parent.numeric.native_observation.payload);eod=list(payload[3]);name,amount=eod[2][0]
        eod[2]=((name,amount+delta),*eod[2][1:]);payload[3]=tuple(eod)
        numeric=gate4f_resign(replace(parent.numeric,native_observation=replace(parent.numeric.native_observation,payload=tuple(payload))))
        other=deepcopy(parent);object.__setattr__(other,'numeric',numeric);resign(other)
        with pytest.raises(ValueError):bridge.prepare_shadow_post_pull(state,other,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=b,conditions=cond)


@pytest.fixture(scope='module')
def c2_native_geometries():
    return {}


@pytest.fixture(scope='module')
def c2_native_cases(gate7_cases,c2_native_geometries):
    """Observe existing real fixture runs, including after fixture caching."""
    assert c2_native_geometries.keys()==gate7_cases.keys()
    return {key:(*values,c2_native_geometries[key]) for key,values in gate7_cases.items()}


def c2_section_bridge(canonical,native):
    """Exact captured-float accounting, bbl; positive = canonical - native.

    C1's five *bookkeeping* terms are not these five scientific categories.
    Expand both capacity-basis terms into unit/geometry/evaluation terms;
    retain EOD stock and coordinate terms, and put gain/ID/steel arithmetic
    in evaluation. No residual is used to define a component.
    """
    from fractions import Fraction as F
    from cement_chart_model import _capacity
    app_bbl=F(42)/F('7.48051945')*F('0.3048')**3
    native_bbl=F('0.15898730')
    assert float(app_bbl)==0.1589872955766461
    assert app_bbl<native_bbl
    def reference(row,unit):
        top,bottom,outer,inner=row
        return F(math.pi)/4*(F(outer)**2-F(inner)**2)*F('0.0254')**2*F(bottom-top)/unit
    ar=reference(canonical,app_bbl);nr=reference(native,native_bbl)
    common_native=reference(native,app_bbl)
    a=F(_capacity(canonical[2],canonical[3]))*F(canonical[1]-canonical[0])
    # Reproduce the native source's actual calculation order, not a fitted
    # coefficient or an approximate equality against the App capacity.
    import DOC58_SI_CANDIDATE_03_TF2R_ER03 as engine
    cap=math.pi*((native[2]*.0254)**2-(native[3]*.0254)**2)/4*engine.BBL_PER_M3
    n=F(cap)*F(native[1]-native[0])
    unit=common_native-nr;geometry=ar-common_native
    evaluation=(a-ar)-(n-nr)
    assert unit>0 and nr-common_native<0  # Native minus App is negative.
    assert unit+geometry+evaluation==a-n
    return a,n,ar,nr,unit,geometry,evaluation


def c2_assert_signed_terms(terms,observed):
    from fractions import Fraction as F
    assert tuple(terms)==('unit','geometry','eod_stock','coordinate','evaluation')
    assert sum(terms.values(),F())==observed


@pytest.mark.parametrize('job',BUG01_JOBS)
@pytest.mark.parametrize('volume',[1.,40.,200.])
def test_cfw128_c2_five_signed_terms(c2_native_cases,job,volume):
    from fractions import Fraction as F
    from cfw128_integration_abi import compose_nominal_tracking
    from cfw128_c2e8_post_pull_review import assess_post_pull,PostPullConditions
    from cement_chart_model import _capacity
    state,numeric,boundary,geo=c2_native_cases[job,volume]
    before=pickle.dumps((state,numeric))
    c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    review=assess_post_pull(state,numeric,expected_app_source_sha=GATE3_APP_SOURCE_SHA,
                            conditions=PostPullConditions(True,True,True))
    initial,intervals,eod,tail=numeric.native_observation.payload[1:]
    assert eod[0]<tail[0] and eod[3]==0.
    # Native raw dimensions and canonical measured source rows must match,
    # independently of the nonzero unit conversion discrepancy.
    ann=sorted(geo.ann_sections,key=lambda p:p.z_top)
    assert len(ann)==len(c.geometry.pumping_return)
    sections=[]
    for a,n in zip(c.geometry.pumping_return,ann):
        canonical=(a.top_md,a.bottom_md,a.outer_diameter_in,a.inner_diameter_in)
        native=(n.z_top,n.z_bot,n.do_in,n.di_in)
        assert canonical==native and a.wall_source_rows and a.running_source_rows
        row=c2_section_bridge(canonical,native)
        section=next(p for p in geo.chan_ann.sections if (p.z_top,p.z_bot)==native[:2])
        assert row[1]==F(section.cap_bbl_per_m)*F(section.z_bot-section.z_top)
        assert row[5]==0  # Verified exact geometry delta; not a tolerance.
        sections.append(row)
    # Pipe capacity uses a distinct native expression: verify every measured
    # ID against the actual Channel rather than substituting annulus math.
    for p,n in zip(sorted(c.captured_geometry.active_sections,key=lambda p:p.top_md),
                   sorted(geo.pipe_sections,key=lambda p:p.z_top)):
        assert (p.top_md,p.bottom_md,p.id_in,p.od_in)==(n.z_top,n.z_bot,n.id_in,n.od_in)
    cp=geo.chan_pipe;ca=geo.chan_ann
    for channel in (cp,ca):
        windows=list(channel._windows(True))
        assert windows[0][1]==0. and windows[-1][2]==channel.total_volume()
        assert all(left[2]==right[1] for left,right in zip(windows,windows[1:]))
        for section,lo,hi in windows:
            # Window coverage versus unrounded width is separately observable.
            width=F(section.cap_bbl_per_m)*F(section.z_bot-section.z_top)
            coordinate=F(hi)-F(lo)-width
            assert width+coordinate==F(hi)-F(lo)
    ap=sum((r[0] for r in sections),F());na=F(ca.total_volume())
    ar=sum((r[2] for r in sections),F());nr=sum((r[3] for r in sections),F())
    unit=sum((r[4] for r in sections),F());geometry=sum((r[5] for r in sections),F())
    evaluation=(ap-ar)-(na-nr)
    ea=sum((F(v) for name,v in eod[2]),F());stock=na-ea
    # A second, independently measured checkpoint uses the native unit on
    # both sides: exact section products versus actual EOD stock. This is
    # near zero without normalizing the canonical/native discrepancy away.
    exact_native=sum((F(p.cap_bbl_per_m)*F(p.z_bot-p.z_top) for p in ca.sections),F())
    near_terms=dict(unit=F(),geometry=F(),eod_stock=stock,coordinate=F(),evaluation=exact_native-na)
    c2_assert_signed_terms(near_terms,exact_native-ea)
    assert abs(exact_native-ea)<=F(1e-9)
    coordinate=F();target=ap;returned=F();makeup=F()
    if not job.startswith('CSG'):
        lap=c.captured_geometry.string_top_md;nd=F(cp.volume_above(lap))
        ad=F();adr=F();ndr=F();dp_unit=F();dp_geometry=F();steel_reference=F()
        for top,bottom,actual,inner,outer,steel,residual in review.withdrawn_sections:
            p=next(p for p in geo.pipe_sections if p.z_top<=top and bottom<=p.z_bot)
            run=next(p for p in c.captured_geometry.active_sections if p.top_md<=top and bottom<=p.bottom_md)
            assert run.description=='Drill Pipes' and run.source_rows
            row=c2_section_bridge((top,bottom,run.id_in,0.),(top,bottom,p.id_in,0.))
            assert row[5]==0 and inner==_capacity(run.id_in)*(bottom-top)
            ad+=F(inner);adr+=row[2];ndr+=row[3];dp_unit+=row[4];dp_geometry+=row[5]
            assert outer==_capacity(run.od_in)*(bottom-top)
            assert steel==_capacity(run.od_in,run.id_in)*(bottom-top)
            steel_dimensions=(top,bottom,run.od_in,run.id_in)
            steel_reference+=c2_section_bridge(steel_dimensions,steel_dimensions)[2]
        returned=sum((F(v) for name,v in review.returned_dp_mud),F())
        makeup=F(review.additional_mud_bbl)
        target=sum((F(_capacity(p.outer_diameter_in,p.inner_diameter_in))*F(p.bottom_md-p.top_md)
                    for p in c.geometry.post_pull_return),F())
        post_reference=F()
        for p in c.geometry.post_pull_return:
            dimensions=(p.top_md,p.bottom_md,p.outer_diameter_in,p.inner_diameter_in)
            post_reference+=c2_section_bridge(dimensions,dimensions)[2]
        gain_geometry=post_reference-ar-adr-steel_reference
        assert gain_geometry==0  # Also prove post-pull gain, not only pumping geometry.
        unit+=dp_unit;geometry+=dp_geometry+gain_geometry;coordinate=nd-returned
        evaluation+=(ad-adr)-(nd-ndr)+(target-ap-ad-makeup-gain_geometry)
        # Independent top-window intersection of actual EOD tokens.
        left=nd;available=F();dp_by_fluid={}
        for name,value in reversed(eod[1]):
            take=min(left,F(value));left-=take;available+=take
            if take:
                assert name in ('Mud','Displacement Fluid')
                dp_by_fluid[name]=dp_by_fluid.get(name,F())+take
        assert left==0 and abs(available-returned)<=F(1e-9)
        for name,amount in dp_by_fluid.items():
            assert abs(amount-sum((F(v) for n,v in review.returned_dp_mud if n==name),F()))<=F(1e-9)
        assert all(r[1]=='INSTALLED_BODY' for r in review.pipe_bands if r[6])
        assert c.displacement.end_md==c.captured_geometry.shoe_md-25.
        left=F(cp.total_volume())-F(cp.volume_above(c.displacement.end_md));terminal_by_fluid={}
        for name,value in eod[1]:
            take=min(left,F(value));left-=take
            terminal_by_fluid[name]=terminal_by_fluid.get(name,F())+take
        assert left==0
        for name,amount in terminal_by_fluid.items():
            located=sum((F(*r[5]) for r in review.pipe_bands if r[0]==name and r[6]),F())
            assert abs(amount-located)<=F(1e-9)
        terminal_total=sum((F(*r[5]) for r in review.pipe_bands if r[6]),F())
        assert abs(terminal_total-(F(cp.total_volume())-F(cp.volume_above(c.displacement.end_md))))<=F(1e-9)
        assert float(target-ea-returned-makeup)==dict(review.capacity_residuals)['POST_PULL_CANONICAL_UNFILLED_BBL']
    else:
        assert not review.withdrawn_sections and not review.returned_dp_mud
        assert review.additional_mud_bbl is None
    terms=dict(unit=unit,geometry=geometry,eod_stock=stock,coordinate=coordinate,evaluation=evaluation)
    observed=target-ea-returned-makeup
    c2_assert_signed_terms(terms,observed)
    assert observed!=0 and abs(stock)<=F(1e-9)  # Nonzero basis; near-zero stock.
    # Every nonzero term is necessary with its actual sign, even below the
    # existing transport audit bound. No approximate closure hides roundoff.
    for key,value in terms.items():
        if value:
            for replacement in (F(),-value):
                mutant=dict(terms);mutant[key]=replacement
                with pytest.raises(AssertionError):c2_assert_signed_terms(mutant,observed)
    grouped=dict(terms);grouped['unit']+=grouped.pop('evaluation')
    with pytest.raises(AssertionError):c2_assert_signed_terms(grouped,observed)
    # Keeping all labels and the same total still cannot move evaluation
    # roundoff into the independently derived conversion category.
    regrouped=dict(terms);regrouped['unit']+=regrouped['evaluation'];regrouped['evaluation']=F()
    if evaluation:
        with pytest.raises(AssertionError):assert regrouped['unit']==unit
    # An unrecorded injection/return/makeup changes stock, never the measured
    # capacity components. Use an actual entered stage amount, no new limit.
    for sign in (-1,1):
        with pytest.raises(AssertionError):c2_assert_signed_terms(terms,observed+sign*F(volume))
    for name,initial_stock,injected,mouth,head,pipe,annulus,residual in review.eod_balances:
        actual_pipe=sum((F(v) for n,v in eod[1] if n==name),F())
        actual_ann=sum((F(v) for n,v in eod[2] if n==name),F())
        native_initial=sum((F(v) for col in initial[1:3] for n,v in col if n==name),F())
        executed=tuple(row for row in intervals if row[1]<=eod[0])
        native_injected=sum((F(v) for row in executed for n,v in row[5] if n==name),F())
        ports=tuple(sum((F(v) for row in executed for p,col in row[6] if p==port for n,v in col if n==name),F())
                    for port in ('ANNULAR_MOUTH','PIPE_HEAD'))
        assert (initial_stock,injected,mouth,head)==tuple(map(float,(native_initial,native_injected,*ports)))
        assert float(actual_pipe)==pipe and float(actual_ann)==annulus
        assert abs(F(initial_stock)+F(injected)-F(mouth)-F(head)-actual_pipe-actual_ann)<=F(1e-9)
    assert all(getattr(review,f) is False for f in ('enabled','ready_to_run','hb_admissible',
        'hydraulic_admissible','chart_admissible','scientifically_qualified'))
    assert review.currentness=='NOT_CURRENTNESS_PROOF' and review.qualification=='NOT_GRANTED'
    assert set(numeric.holds)<=set(review.holds) and pickle.dumps((state,numeric))==before


def test_cfw128_c2_geometry_and_section_provenance_negatives(c2_native_cases):
    from dataclasses import replace
    from cfw128_integration_abi import compose_nominal_tracking
    state,numeric,boundary,geo=c2_native_cases['LNR 5"',200.]
    c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    a=c.geometry.pumping_return[0];n=sorted(geo.ann_sections,key=lambda p:p.z_top)[0]
    canonical=(a.top_md,a.bottom_md,a.outer_diameter_in,a.inner_diameter_in)
    native=(n.z_top,n.z_bot,n.do_in,n.di_in)
    assert c2_section_bridge(canonical,native)[5]==0
    # A geometry delta cannot be declared zero after changing a measured MD.
    changed=(native[0],native[1]+1.,native[2],native[3])
    assert c2_section_bridge(canonical,changed)[5]!=0
    with pytest.raises(AssertionError):assert c2_section_bridge(canonical,changed)[5]==0
    expected=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA).geometry.pumping_return
    for forged in (replace(a,wall_source_rows=(max(a.wall_source_rows)+1,)),
                   replace(a,running_source_rows=(max(a.running_source_rows)+1,))):
        with pytest.raises(AssertionError):assert (forged,*c.geometry.pumping_return[1:])==expected


@pytest.mark.parametrize('fault',['injection','return','makeup'])
def test_cfw128_c2_resigned_unrecorded_volume_rejected(c2_native_cases,fault):
    from dataclasses import fields
    from project_state import fingerprint
    from cfw128_er03_numeric_adapter import _primitive
    from cfw128_c2e8_post_pull_review import assess_post_pull,validate_post_pull_review,PostPullConditions,SCHEMA
    state,numeric,boundary,geo=c2_native_cases['LNR 7"',200.]
    cond=PostPullConditions(True,True,True)
    review=assess_post_pull(state,numeric,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)
    forged=deepcopy(review);amount=numeric.stages[0][2]
    if fault in ('injection','return'):
        rows=list(forged.eod_balances);row=list(rows[0])
        row[2]+=amount
        row[5 if fault=='injection' else 3]+=amount
        rows[0]=tuple(row);object.__setattr__(forged,'eod_balances',tuple(rows))
    else:
        object.__setattr__(forged,'additional_mud_bbl',forged.additional_mud_bbl+amount)
        rows=list(forged.post_pull_balances)
        i=next(i for i,row in enumerate(rows) if row[0]=='Displacement Fluid');row=list(rows[i])
        row[3]+=amount;row[5]+=amount;rows[i]=tuple(row)
        object.__setattr__(forged,'post_pull_balances',tuple(rows))
    values=tuple(getattr(forged,f.name) for f in fields(forged) if f.init and f.name!='projection_identity')
    object.__setattr__(forged,'projection_identity',fingerprint([SCHEMA,_primitive(values)]))
    forged.__post_init__()  # Internally re-signed is not source validation.
    with pytest.raises(ValueError):
        validate_post_pull_review(state,numeric,forged,expected_app_source_sha=GATE3_APP_SOURCE_SHA,conditions=cond)


def c3_integrated_stock(state,boundary,parent):
    """Independently reconcile native tokens through the existing sidecar."""
    from fractions import Fraction as F
    from cfw128_integration_abi import compose_nominal_tracking
    from cfw128_c2e8_post_pull_review import PostPullConditions
    import cfw128_shadow_word_bridge as bridge
    before=pickle.dumps((state,boundary,parent))
    conditions=PostPullConditions(True,True,True)
    child=bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,
                                          boundary=boundary,conditions=conditions)
    bridge.validate_shadow_post_pull(state,parent,child,expected_app_source_sha=GATE3_APP_SOURCE_SHA,
                                      boundary=boundary,conditions=conditions)
    c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    r=child.review;numeric=parent.numeric
    initial,intervals,eod,tail=numeric.native_observation.payload[1:]
    assert child.shadow_identity==parent.projection_identity and child.source_identity==parent.source_identity
    assert r.numeric_identity==numeric.projection_identity and r.placement_identity==parent.placement.projection_identity
    assert r.composition_identity==c.projection_identity and r.eod_balances==parent.placement.fluid_balances
    assert [(row[0],row[2]) for row in numeric.stages]==[(s.name,s.volume_bbl) for s in c.schedule.stages]
    assert dict(numeric.events)['t_eod']==eod[0]<=tail[0]
    def amount(tokens,name):return sum((F(v) for n,v in tokens if n==name),F())
    executed=tuple(row for row in intervals if row[1]<=eod[0])
    for name,start,injected,mouth,head,pipe,annulus,residual in r.eod_balances:
        stock=sum((amount(col,name) for col in initial[1:3]),F())
        delivered=sum((amount(row[5],name) for row in executed),F())
        outlets=tuple(sum((amount(col,name) for row in executed for p,col in row[6] if p==port),F())
                      for port in ('ANNULAR_MOUTH','PIPE_HEAD'))
        ep=amount(eod[1],name);ea=amount(eod[2],name)
        assert (start,injected,mouth,head,pipe,annulus)==tuple(map(float,(stock,delivered,*outlets,ep,ea)))
        assert abs(stock+delivered-sum(outlets,F())-ep-ea)<=F(1e-9)
        located=sum((F(*band[5]) for band in r.pipe_bands if band[0]==name),F())
        assert abs(ep-located)<=F(1e-9)
        if r.post_pull_balances:
            retained=sum((F(*band[5]) for band in r.pipe_bands if band[0]==name and band[1]=='INSTALLED_BODY'),F())
            after_ann=sum((F(*band[5]) for band in r.annular_bands if band[0]==name),F())
            external=F(r.additional_mud_bbl) if name=='Displacement Fluid' else F()
            assert abs(ep+ea+external-retained-after_ann)<=F(1e-9)
            for origin,expected in (('NATIVE_EOD_ANNULUS',ea),('RETURNED_DP_INTERNAL',amount(r.returned_dp_mud,name)),
                                     ('EXTERNAL_MAKEUP_MUD',external)):
                observed=sum((F(*band[5]) for band in r.annular_bands if band[0]==name and band[1]==origin),F())
                assert abs(expected-observed)<=F(1e-9)
    assert all(0<=row[2]<row[3]<=c.captured_geometry.shoe_md and row[4]>0 for row in r.annular_bands)
    assert all(left[2]>=right[3] for left,right in zip(r.annular_bands,r.annular_bands[1:]))
    if c.captured_geometry.kind=='casing':
        assert r.additional_mud_bbl is None and not r.returned_dp_mud and not r.withdrawn_sections
    else:
        assert all(row[1]=='INSTALLED_BODY' for row in r.pipe_bands if row[6])
        assert c.displacement.end_md==c.captured_geometry.shoe_md-25.
        for top,bottom,native,inside,outside,steel,residual in r.withdrawn_sections:
            section=next(s for s in c.captured_geometry.active_sections if s.top_md<=top and bottom<=s.bottom_md)
            assert section.description=='Drill Pipes' and bottom<=c.captured_geometry.string_top_md
            assert (inside,outside,steel)==tuple(chart._capacity(*dims)*(bottom-top)
                for dims in ((section.id_in,),(section.od_in,),(section.od_in,section.id_in)))
        assert all(row[-1]==0. for row in r.post_pull_balances)
    for receipt in (parent,child,r):
        assert all(getattr(receipt,name) is False for name in ('enabled','ready_to_run','hb_admissible',
            'hydraulic_admissible','chart_admissible','scientifically_qualified'))
        assert receipt.currentness=='NOT_CURRENTNESS_PROOF' and receipt.qualification=='NOT_GRANTED'
    assert set(numeric.holds)<=set(r.holds) and r.final_field_toc=='FINAL_FIELD_TOC_NOT_EVALUATED'
    assert pickle.dumps((state,boundary,parent))==before
    return child


@pytest.fixture(scope='module')
def c3_shadow_cases(bug01_reviewed_report_base,gate8_cases):
    import cfw128_shadow_word_bridge as bridge
    cases={(job,200.):values for job,values in gate8_cases.items()}
    for job in BUG01_JOBS:
        state=gate3_case(bug01_reviewed_report_base,job);boundary=gate8_cases[job][1]
        cases[job,1.]=(state,boundary,bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=boundary))
    return cases


@pytest.mark.parametrize('job',BUG01_JOBS)
@pytest.mark.parametrize('volume',[1.,200.])
def test_cfw128_c3_eight_family_full_shadow(c3_shadow_cases,job,volume):
    state,boundary,parent=c3_shadow_cases[job,volume]
    child=c3_integrated_stock(state,boundary,parent);r=child.review
    if volume==1.:assert r.achieved_cement_top_md is None and 'NO_NATIVE_ANNULAR_CEMENT' in r.case_holds
    elif job.startswith('CSG'):assert r.achieved_cement_top_md>0 and r.surface_status=='HOLD_SURFACE_NOT_PROVED'
    else:assert r.region=='ABOVE_LAP' and r.achieved_cement_top_md>0


@pytest.mark.parametrize('volume,position',[(40.,'BELOW_LAP'),(200.,'ABOVE_LAP'),(800.,'RETURNED_AT_SURFACE')])
def test_cfw128_c3_uat19_native_connected_path(bug01_reviewed_report_base,volume,position,monkeypatch):
    from project_state import lab_source_signature
    from engineering_tools import lab_review_signature
    from cfw128_integration_abi import compose_nominal_tracking
    import cfw128_shadow_word_bridge as bridge
    import cfw128_er03_numeric_adapter as adapter
    # The eight Hardware rows are UAT19 evidence. All fluid/rate/lab/boundary
    # inputs below are the existing Gate3 synthetic controls, never field facts.
    state=gate3_case(bug01_reviewed_report_base,'TIE BACK LNR 7"');geometry=cfw128_c1_uat19_state()
    for key in ('job_type','hardware_table','placement_config','well_geometry'):state[key]=deepcopy(geometry[key])
    state['fluids_config']['params']['Main'].update(volume=volume,pump_rate=volume/4.)
    state['lab_source_signatures']['Main']=lab_source_signature(state,'Main')
    state['lab_qc_params']['Main']['review_signature']=lab_review_signature(state['lab_qc_params']['Main'],state['lab_grid_dfs']['Main'])
    c=compose_nominal_tracking(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA)
    state['fluids_config']['params']['Displacement Fluid']['pump_rate']=c.displacement.derived_displacement_bbl/4.
    boundary=gate3_boundary();captured=[];original=adapter.event_vertical.simulate
    def observed(design):
        result=original(design);captured.append((design.geo,result));return result
    monkeypatch.setattr(adapter.event_vertical,'simulate',observed)
    parent=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=boundary)
    monkeypatch.setattr(adapter.event_vertical,'simulate',lambda *a:pytest.fail('Post-pull replayed solver'))
    child=c3_integrated_stock(state,boundary,parent);r=child.review
    assert len(captured)==1
    geo,raw=captured[0]
    assert [(p.z_top,p.z_bot) for p in geo.pipe_sections]==[(0.,2800.),(2800.,3885.)]
    assert [(p.z_top,p.z_bot,p.do_in,p.di_in) for p in geo.ann_sections]==[(0.,2800.,8.535,5.),(2800.,3885.,8.535,7.)]
    assert not any(row.Description=='Open Hole Size' for row in state['hardware_table'].itertuples())
    assert c.captured_geometry.receiver.shoe_md==4860. and parent.numeric.pressure_station_md==3885.
    assert c.geometry.corridor_contract=='OWNER_SURFACE_CONNECTED_2026_11_11'
    assert c.geometry.pumping_return[0].top_md==0. and c.geometry.pumping_return[-1].bottom_md==3885.
    assert math.fsum(v for n,v in parent.numeric.native_observation.payload[1][2])==geo.total_ann_bbl
    assert geo.total_ann_bbl>math.fsum(s.nominal_volume_bbl for s in c.geometry.lower_annulus)
    for field,channel in zip(('time_min','whp_kpsi','pump_kpsi','hydrostatic_kpsi','total_pressure_kpsi','q_in_bpm','q_out_bpm'),
                             ('t','whp','pump','hydro','dyn','q_in','q_out')):
        assert getattr(parent.numeric,field)==tuple(getattr(raw,channel))
    main=next(row for row in r.eod_balances if row[0]=='Main')
    if position=='RETURNED_AT_SURFACE':assert main[3]>0
    else:assert main[3]==0 and r.region==position
    assert any(row[0]=='Mud' and row[3]>0 for row in r.eod_balances)
    assert r.returned_dp_mud and r.additional_mud_bbl>0


@pytest.mark.parametrize('job',['CSG 9 5/8"','LNR 7"','TIE BACK LNR 7"'])
def test_cfw128_c3_ordered_auxiliary_stage_sidecar(bug01_reviewed_report_base,job):
    from dataclasses import replace
    import cfw128_shadow_word_bridge as bridge
    names=('Pre Flush','Spacer Ahead','Spacer Behind')
    state=gate4d_program(gate3_case(bug01_reviewed_report_base,job),names)
    state['fluids_config']['params']['Main'].update(volume=200.,pump_rate=50.)
    boundary=replace(gate3_boundary(),gel_pa_by_fluid=(*gate3_boundary().gel_pa_by_fluid,*((name,0.) for name in names)))
    parent=bridge.prepare_shadow(state,expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=boundary)
    child=c3_integrated_stock(state,boundary,parent)
    assert [row[0] for row in parent.numeric.stages]==['Pre Flush','Spacer Ahead','Main','Spacer Behind','Displacement Fluid']
    assert set(names)<=set(row[0] for row in child.review.eod_balances)
    assert all(next(p for p in parent.numeric.fluids if p.name==name).operator_review=='NOT_ASSERTED' for name in names)
    assert any('UNKNOWN' in hold or 'UNVERIFIED' in hold for hold in child.review.holds)


@pytest.mark.parametrize('fault',['reversed_transfer','false_surface','unrecorded_makeup'])
def test_cfw128_c3_resigned_physical_claims_rejected(gate8_cases,fault):
    from dataclasses import fields
    from project_state import fingerprint
    from cfw128_er03_numeric_adapter import _primitive
    from cfw128_c2e8_post_pull_review import PostPullConditions,SCHEMA
    import cfw128_shadow_word_bridge as bridge
    state,boundary,parent=gate8_cases['CSG 9 5/8"' if fault=='false_surface' else 'LNR 7"']
    conditions=PostPullConditions(True,True,True)
    child=deepcopy(bridge.prepare_shadow_post_pull(state,parent,expected_app_source_sha=GATE3_APP_SOURCE_SHA,
        boundary=boundary,conditions=conditions));review=child.review
    if fault=='reversed_transfer':object.__setattr__(review,'returned_dp_mud',tuple((n,-v) for n,v in review.returned_dp_mud))
    elif fault=='false_surface':
        object.__setattr__(review,'surface_status','CEMENT_TO_SURFACE_PROVED_IN_NATIVE_MODEL')
        object.__setattr__(review,'achieved_cement_top_md',0.)
    else:object.__setattr__(review,'additional_mud_bbl',review.additional_mud_bbl+parent.numeric.stages[0][2])
    values=tuple(getattr(review,f.name) for f in fields(review) if f.init and f.name!='projection_identity')
    object.__setattr__(review,'projection_identity',fingerprint([SCHEMA,_primitive(values)]))
    object.__setattr__(child,'projection_identity',fingerprint([bridge.POST_PULL_SIDECAR_SCHEMA,
        child.shadow_identity,child.source_identity,_primitive(review)]))
    child.__post_init__()
    with pytest.raises(ValueError):bridge.validate_shadow_post_pull(state,parent,child,
        expected_app_source_sha=GATE3_APP_SOURCE_SHA,boundary=boundary,conditions=conditions)
