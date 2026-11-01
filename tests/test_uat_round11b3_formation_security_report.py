"""Round 11B-3: passive prepared overlays and the existing Section-IV Word image."""
import ast
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch

from docx import Document
from matplotlib.colors import to_hex
import numpy as np
from PIL import Image
import pytest

import cement_chart_model as model
import cement_chart_report as report
from project_state import fingerprint, is_project_key, prepare_calculations
from test_uat_round8a_chart_model import balanced_state


def case_state(kind='safe', mode='advanced', state=None):
    """Use real placement/hydrostatic; source pressures reuse the core evaluator."""
    state = balanced_state() if state is None else deepcopy(state)
    if mode == 'basic':
        state['formation_pressure_config'] = {'mode': 'basic', 'profile': []}
        state[model.PORE_FIELD], state[model.FRAC_FIELD] = {
            'safe': (10., 250.), 'frac': (10., 20.), 'pore': (200., 250.)}[kind]
        return state
    base = model.build_chart_model(state)
    domain = base['static_security']['domain']
    top, bottom = domain['top_md'], domain['bottom_md']
    depths = [top+(bottom-top)*i/4 for i in range(5)]
    if kind.startswith('contact'):
        depths = sorted({top, bottom, *(md for md in base['hydrostatic']['md_m'] if top < md < bottom)})
    from well_profile import tvd_at_md
    pressures = [model._linear_pressure(base['hydrostatic']['tvd_m'], base['hydrostatic']['pressure_psi'], t)
                 for t in tvd_at_md(state['well_geometry'], depths)]
    pore, frac = [p-200. for p in pressures], [p+200. for p in pressures]
    delta = [-100., 100., -100., 100. if kind.startswith('disconnected') else -100., -100.]
    if kind in ('frac', 'disconnected_frac'):
        frac = [p-d for p, d in zip(pressures, delta)]
    elif kind in ('pore', 'disconnected_pore'):
        pore = [p+d for p, d in zip(pressures, delta)]
    elif kind == 'both':
        pore = [p+d for p, d in zip(pressures, [-200., 100., -200., -200., -200.])]
        frac = [p-d for p, d in zip(pressures, [-200., -200., -200., 100., -200.])]
    elif kind == 'contact_frac':
        frac = pressures
    elif kind == 'contact_pore':
        pore = pressures
    state['formation_pressure_config'] = {'mode': 'advanced', 'profile': [
        {'md_m': md, 'pore_psi': p, 'frac_psi': f} for md, p, f in zip(depths, pore, frac)]}
    return state


def regions(axis, boundary):
    return [p for p in axis.patches if (p.get_gid() or '').startswith('security:region:'+boundary+':')]


@pytest.mark.parametrize('mode', ['basic', 'advanced'])
def test_safe_core_lines_and_fluid_panel_remain_complete(mode):
    prepared = model.build_chart_model(case_state(mode=mode))
    figure = report.build_chart_figure(prepared)
    try:
        left, right = figure.axes
        lines = {line.get_label(): line for line in left.lines}
        for label, color, source, key in [('Hydrostatic', '#ff0000', prepared['hydrostatic'], 'pressure_psi'),
                ('Frac', '#0000ff', prepared['pore_frac'], 'frac_psi'),
                ('Pore', '#00b040', prepared['pore_frac'], 'pore_psi')]:
            assert to_hex(lines[label].get_color()) == color
            indices=list(range(len(source['tvd_m'])))
            if label!='Hydrostatic' and mode=='basic':
                domain=prepared['static_security']['domain']
                indices=[i for i,md in enumerate(source['md_m']) if domain['top_md']<=md<=domain['bottom_md']]
            np.testing.assert_array_equal(lines[label].get_xdata(), np.array([source[key][i] for i in indices])/1000.)
            np.testing.assert_array_equal(lines[label].get_ydata(), [source['tvd_m'][i] for i in indices])
        assert not regions(left, 'frac') and not regions(left, 'pore')
        assert not any(t.get_gid() == 'security:summary' for t in left.texts)
        assert right.title.get_text() == 'Fluid Sequence'
        assert any(p.get_gid() == 'shoe-track' for p in right.patches)
        if mode == 'advanced':
            assert min(lines['Pore'].get_ydata()) == prepared['static_security']['domain']['top_tvd'] > 0
            assert max(lines['Frac'].get_ydata()) == prepared['static_security']['domain']['bottom_tvd']
    finally:
        figure.clear()


@pytest.mark.parametrize('kind', ['frac', 'pore', 'both', 'disconnected_frac', 'disconnected_pore'])
def test_exact_prepared_regions_contacts_and_compact_summary(kind):
    prepared = model.build_chart_model(case_state(kind))
    before = deepcopy(prepared)
    security = prepared['static_security']
    figure = report.build_chart_figure(prepared)
    try:
        axis = figure.axes[0]
        assert security['status'] == 'warning'
        for boundary, color in [('frac', '#ff0000'), ('pore', '#ffa500')]:
            rows = security[boundary+'_violations']
            overlays = security['plot_regions'][boundary]
            patches = regions(axis, boundary)
            assert len(patches) == len(overlays) == len(rows)
            if kind == 'disconnected_'+boundary:
                assert len(patches) == 2
            for row, overlay, polygon in zip(rows, overlays, patches):
                assert overlay['tvd_m'][0] == row['start_tvd_m']
                assert overlay['tvd_m'][-1] == row['end_tvd_m']
                assert min(overlay['tvd_m']) >= security['domain']['top_tvd']
                assert max(overlay['tvd_m']) <= security['domain']['bottom_tvd']
                vertices = np.column_stack((np.array(overlay['hydro_psi']+overlay['limit_psi'][::-1])/1000.,
                                           overlay['tvd_m']+overlay['tvd_m'][::-1]))
                np.testing.assert_array_equal(polygon.get_xy()[:len(vertices)], vertices)
                assert to_hex(polygon.get_facecolor()) == color
                assert polygon.get_hatch() and 0 < polygon.get_facecolor()[-1] < .3
                assert polygon.get_zorder() < axis.lines[0].get_zorder()
        markers = [line for line in axis.lines if (line.get_gid() or '').startswith('security:contact:')]
        assert len(markers) == len(security['crossings'])
        for marker, record in zip(markers, security['crossings']):
            assert marker.get_xdata()[0] == record['pressure_psi']/1000.
            assert marker.get_ydata()[0] == record['tvd_m']
            assert record['boundary'] in marker.get_gid()
        if kind == 'both':
            assert len({marker.get_marker() for marker in markers}) == 2
        summary, = [t.get_text() for t in axis.texts if t.get_gid() == 'security:summary']
        assert f"Frac violation intervals: {len(security['frac_violations'])}" in summary
        assert f"Underbalance intervals: {len(security['pore_violations'])}" in summary
        for boundary, label in [('frac', 'Worst Frac exceedance'), ('pore', 'Worst Underbalance')]:
            rows = security[boundary+'_violations']
            if rows:
                worst = max(rows, key=lambda r: r['max_delta_psi'])
                assert (f"{label}: {worst['max_delta_psi']:.0f} psi\n"
                        f"@ MD {worst['max_at_md_m']:.1f} m / TVD {worst['max_at_tvd_m']:.1f} m") in summary
            else:
                assert label not in summary
        assert len(summary.splitlines()) == 2+2*sum(bool(security[b+'_violations']) for b in ('frac', 'pore'))
        assert prepared == before
    finally:
        figure.clear()


@pytest.mark.parametrize('boundary', ['frac', 'pore'])
def test_equality_contacts_have_markers_without_fake_violation(boundary):
    prepared = model.build_chart_model(case_state('contact_'+boundary))
    security = prepared['static_security']
    assert security['status'] == 'safe' and security['crossings']
    figure = report.build_chart_figure(prepared)
    try:
        axis = figure.axes[0]
        assert not regions(axis, 'frac') and not regions(axis, 'pore')
        assert not any(t.get_gid() == 'security:summary' for t in axis.texts)
        assert len([line for line in axis.lines if (line.get_gid() or '').startswith('security:contact:')]) == len(security['crossings'])
    finally:
        figure.clear()


def test_renderer_is_passive_and_png_is_transient(tmp_path, monkeypatch):
    prepared = model.build_chart_model(case_state('both'))
    before = deepcopy(prepared)
    def forbidden(*args, **kwargs):
        raise AssertionError('renderer rediscovered engineering')
    for name in ('analyze_static_security', 'resolve_formation_profile', 'resolve_chart_geometry',
                 'resolve_final_fluid_intervals', '_linear_pressure', '_crossing_md', 'tvd_at_md'):
        monkeypatch.setattr(model, name, forbidden)
    import well_profile
    monkeypatch.setattr(well_profile, 'tvd_at_md', forbidden)
    tree = ast.parse(Path(report.__file__).read_text())
    forbidden_names = {'analyze_static_security', 'resolve_formation_profile', 'resolve_chart_geometry',
                       'resolve_final_fluid_intervals', 'tvd_at_md', 'interp', 'interpolate'}
    assert not any(isinstance(n, ast.Call) and
                   (n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else '')
                   in forbidden_names for n in ast.walk(tree))
    monkeypatch.chdir(tmp_path)
    png = report.render_chart_png(prepared)
    with Image.open(BytesIO(png)) as image:
        assert image.size == (2300, 1680)
    assert prepared == before and list(tmp_path.iterdir()) == []


def test_overlay_retains_hydrostatic_knots_without_changing_source_or_persistence():
    state = case_state('frac', mode='basic')
    before = fingerprint(state)
    prepared = model.build_chart_model(state)
    security = prepared['static_security']
    overlay, = security['plot_regions']['frac']
    row, = security['frac_violations']
    expected = [md for md in prepared['hydrostatic']['md_m'] if row['start_md_m'] <= md <= row['end_md_m']]
    assert set(expected) <= set(overlay['tvd_m'])  # Vertical fixture: MD == TVD.
    assert len(overlay['tvd_m']) > 2
    assert fingerprint(state) == before
    assert not is_project_key('_cement_chart_model')
    assert not is_project_key('_cement_chart_source')
    assert 'plot_regions' not in json.dumps(state, default=str)


def test_compact_summary_fits_beside_legend_inside_pressure_panel():
    figure = report.build_chart_figure(model.build_chart_model(case_state('both')))
    try:
        figure.canvas.draw()
        axis = figure.axes[0]
        text, = [t for t in axis.texts if t.get_gid() == 'security:summary']
        canvas = figure.canvas.get_renderer()
        box = text.get_bbox_patch().get_window_extent(canvas)
        legend = axis.get_legend().get_window_extent(canvas)
        assert box.width+legend.width < axis.bbox.width
        assert not box.overlaps(legend)
        assert axis.bbox.contains(box.x0, box.y0) and axis.bbox.contains(box.x1, box.y1)
    finally:
        figure.clear()


def test_directional_overlay_uses_prepared_tvd_and_preserves_every_curve_edge():
    import pandas as pd
    state = balanced_state()
    state['well_geometry'] = {'type': 'Directional', 'survey': pd.DataFrame({
        'MD': [0., 1000.], 'Deviation': [0., 60.], 'Azimuth': [0., 0.]})}
    prepared = model.build_chart_model(case_state('frac', mode='basic', state=state))
    security = prepared['static_security']
    assert security['domain']['bottom_md'] != security['domain']['bottom_tvd']
    for overlay in security['plot_regions']['frac']:
        for t, h, f in zip(overlay['tvd_m'], overlay['hydro_psi'], overlay['limit_psi']):
            assert h == pytest.approx(model._linear_pressure(prepared['hydrostatic']['tvd_m'],
                prepared['hydrostatic']['pressure_psi'], t), rel=0, abs=1e-9)
            assert f == pytest.approx(model._linear_pressure(prepared['pore_frac']['tvd_m'],
                prepared['pore_frac']['frac_psi'], t), rel=0, abs=1e-9)


def test_cased_gaps_and_equality_separate_prepared_regions():
    from test_uat_round11b1_formation_security import synthetic
    parts = [{'top_md': 500., 'bottom_md': 600., 'top_tvd': 500., 'bottom_tvd': 600.},
             {'top_md': 800., 'bottom_md': 1000., 'top_tvd': 800., 'bottom_tvd': 1000.}]
    security = synthetic([100.]*5, [900.]*5, segments=parts)
    assert [(r['tvd_m'][0], r['tvd_m'][-1]) for r in security['plot_regions']['frac']] == [(500., 600.), (800., 1000.)]
    contact = synthetic([100.]*3, [900., 1500., 1900.], depths=[500., 750., 1000.])
    assert [(r['tvd_m'][0], r['tvd_m'][-1]) for r in contact['plot_regions']['frac']] == [(500., 750.), (750., 1000.)]


def test_summary_selects_worst_prepared_record_not_first_interval():
    state = case_state('disconnected_frac')
    state['formation_pressure_config']['profile'][3]['frac_psi'] -= 50.
    prepared = model.build_chart_model(state)
    rows = prepared['static_security']['frac_violations']
    assert rows[1]['max_delta_psi'] > rows[0]['max_delta_psi']
    figure = report.build_chart_figure(prepared)
    try:
        summary, = [t.get_text() for t in figure.axes[0].texts if t.get_gid() == 'security:summary']
        worst = rows[1]
        assert f"Worst Frac exceedance: {worst['max_delta_psi']:.0f} psi" in summary
        assert f"@ MD {worst['max_at_md_m']:.1f} m / TVD {worst['max_at_tvd_m']:.1f} m" in summary
    finally:
        figure.clear()


@pytest.mark.parametrize('failure', [False, True])
def test_owned_render_figure_is_cleared_without_closing_unrelated_figure(failure, monkeypatch):
    from matplotlib.figure import Figure
    unrelated = Figure(); unrelated.subplots()
    owned = []
    original_build = report.build_chart_figure
    def observe(prepared):
        figure = original_build(prepared)
        owned.append(figure)
        return figure
    monkeypatch.setattr(report, 'build_chart_figure', observe)
    if failure:
        def failed_save(*args, **kwargs):
            raise ValueError('controlled PNG failure')
        monkeypatch.setattr(Figure, 'savefig', failed_save)
        with pytest.raises(ValueError, match='controlled PNG failure'):
            report.render_chart_png(model.build_chart_model(case_state('frac')))
    else:
        assert report.render_chart_png(model.build_chart_model(case_state('frac'))).startswith(b'\x89PNG')
    assert len(owned) == 1 and owned[0].axes == []
    assert len(unrelated.axes) == 1
    unrelated.clear()


@pytest.fixture(scope='module')
def word_project():
    import test_audit_regressions as audit
    return audit.AuditRegressions().configured_app('CSG 9 5/8"').session_state.to_dict()


WORD_CASES = [('basic', 'safe'), ('basic', 'frac'), ('basic', 'pore'),
              ('advanced', 'safe'), ('advanced', 'frac'), ('advanced', 'pore'),
              ('advanced', 'disconnected_frac')]


@pytest.mark.parametrize('mode,kind', WORD_CASES)
def test_actual_word_builds_safe_and_unsafe_at_existing_anchor(word_project, mode, kind, monkeypatch, tmp_path):
    import test_audit_regressions as audit
    import pumping_simulation
    from test_uat_round10c_integration import inspect_word, save_project
    from test_uat_round10b_pumping_word import drawing_paragraph, image_bytes
    state = case_state(kind, mode, word_project)
    assert prepare_calculations(state) == []
    expected = deepcopy(state['_cement_chart_model'])
    assert expected['static_security']['status'] == ('safe' if kind == 'safe' else 'warning')
    if kind == 'disconnected_frac':
        assert len(expected['static_security']['frac_violations']) == 2
    images = []
    original = report.render_chart_png
    def observe(prepared):
        png = original(prepared)
        images.append((deepcopy(prepared), png))
        return png
    monkeypatch.setattr(report, 'render_chart_png', observe)
    original_build=report.build_chart_figure
    def observe_actual_figure(prepared):
        figure=original_build(prepared)
        domain=prepared['static_security']['domain']
        for line in figure.axes[0].lines:
            if line.get_label() in ('Pore','Frac'):
                assert min(line.get_ydata())==domain['top_tvd']>0
                assert max(line.get_ydata())==domain['bottom_tvd']
        return figure
    monkeypatch.setattr(report,'build_chart_figure',observe_actual_figure)
    case = audit.AuditRegressions()
    figures = pumping_simulation.fcm.plt.get_fignums()
    app = case.app(deepcopy(state))
    assert not images  # Rendering/readiness/navigation does not generate a PNG.
    case.export(app)  # The real Phase-X Build, including Pumping and schematic.
    assert len(images) == 1 and images[0][0] == expected
    data = app.session_state['_compiled_doc_bytes']
    inspect_word(data)
    doc = Document(BytesIO(data))
    assert report.CHART_ANCHOR not in [p.text for p in doc.paragraphs]
    diagnostic = drawing_paragraph(doc, 'Static Well Security and Fluid Sequence')
    assert len(diagnostic._p.xpath('.//w:drawing')) == 1
    assert image_bytes(doc, diagnostic) == images[0][1]
    drawing_paragraph(doc, 'Well Schematic')
    # Existing template logo + Centralizer, then temperature/diagnostic/Pumping/schematic.
    assert len(doc.inline_shapes) == 6
    assert pumping_simulation.fcm.plt.get_fignums() == figures
    raw = save_project(app)
    assert all(token not in raw for token in (b'plot_regions', b'static_security', b'PNG', b'crossings'))
    (tmp_path / f'{mode}-{kind}.docx').write_bytes(data)
    (tmp_path / f'{mode}-{kind}.png').write_bytes(images[0][1])


def test_invalid_advanced_blocks_word_and_retires_download_before_render(word_project, monkeypatch):
    import test_audit_regressions as audit
    import pumping_simulation
    state = case_state('safe', 'advanced', word_project)
    state['formation_pressure_config']['profile'][0]['pore_psi'] = None
    state['_compiled_doc_bytes'] = b'stale document'
    state['_compiled_doc_signature'] = 'stale'
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid Formation reached a renderer/solver')
    monkeypatch.setattr(report, 'render_chart_png', forbidden)
    monkeypatch.setattr(pumping_simulation, 'run_pumping_simulation', forbidden)
    case = audit.AuditRegressions()
    app = case.app(state)
    case.phase(app, 'phase10')
    assert next(b for b in app.button if b.label == 'Build Word Document').disabled
    assert '_compiled_doc_bytes' not in app.session_state
    assert any('Formation' in e.value for e in app.error)


@pytest.mark.parametrize('directional',[False,True])
def test_r15b_basic_formation_artists_begin_at_resolved_open_hole(directional,tmp_path):
    state=case_state(mode='basic')
    if directional:
        import pandas as pd
        survey=pd.DataFrame([[0.,0.,0.],[500.,60.,0.],[1000.,60.,0.]],columns=['MD','Deviation','Azimuth'])
        state['well_geometry']={'version':1,'type':'Directional','td_m':1000.,'survey':survey}
    prepared=model.build_chart_model(state);before=deepcopy(prepared)
    figure=report.build_chart_figure(prepared)
    try:
        lines={line.get_label():line for line in figure.axes[0].lines}
        domain=prepared['static_security']['domain']
        figure.savefig(tmp_path/'basic-open-hole.png')
        assert domain['top_md']==500.
        for name,key in [('Pore','pore_psi'),('Frac','frac_psi')]:
            assert min(lines[name].get_ydata())==domain['top_tvd']>0
            assert max(lines[name].get_ydata())==domain['bottom_tvd']
            for x,t in zip(lines[name].get_xdata(),lines[name].get_ydata()):
                assert x*1000.==pytest.approx(model.pressure_psi(state[model.PORE_FIELD if name=='Pore' else model.FRAC_FIELD],t))
        np.testing.assert_array_equal(lines['Hydrostatic'].get_ydata(),before['hydrostatic']['tvd_m'])
        np.testing.assert_array_equal(lines['Hydrostatic'].get_xdata(),np.array(before['hydrostatic']['pressure_psi'])/1000.)
        figure.savefig(tmp_path/'basic-open-hole.png')
    finally:figure.clear()
    assert prepared==before


@pytest.mark.parametrize('mode',['basic','advanced'])
def test_r15b_synthetic_prepared_gaps_are_independent_exact_segments(mode):
    # Prepared-domain contract example, not a claim of measured field geometry.
    state=case_state(mode='basic')
    if mode=='advanced':
        state['formation_pressure_config']={'mode':'advanced','profile':[
            {'md_m':500.,'pore_psi':100.,'frac_psi':1500.},
            {'md_m':1000.,'pore_psi':300.,'frac_psi':3500.}]}
    prepared=model.build_chart_model(state)
    domain=deepcopy(prepared['formation_pressure']['domain'])
    domain['segments']=[dict(top_md=500.,bottom_md=600.,top_tvd=500.,bottom_tvd=600.),
                        dict(top_md=800.,bottom_md=1000.,top_tvd=800.,bottom_tvd=1000.)]
    prepared['formation_pressure']['domain']=domain
    prepared['static_security']=model.analyze_static_security(state['well_geometry'],prepared['hydrostatic'],prepared['formation_pressure'])
    before=deepcopy(prepared);figure=report.build_chart_figure(prepared)
    try:
        left=figure.axes[0]
        for name,color,key in [('Pore','#00b040','pore_psi'),('Frac','#0000ff','frac_psi')]:
            lines=[line for line in left.lines if to_hex(line.get_color())==color and line.get_linewidth()==3.8]
            assert [(min(l.get_ydata()),max(l.get_ydata())) for l in lines]==[(500.,600.),(800.,1000.)]
            assert left.get_legend_handles_labels()[1].count(name)==1
            for line in lines:
                for pressure,depth in zip(line.get_xdata(),line.get_ydata()):
                    if mode=='advanced':
                        expected=(100.+(depth-500.)*.4) if name=='Pore' else (1500.+(depth-500.)*4.)
                    else:expected=model.pressure_psi(state[model.PORE_FIELD if name=='Pore' else model.FRAC_FIELD],depth)
                    assert pressure*1000.==pytest.approx(expected,rel=1e-14)
        hydro=next(l for l in left.lines if l.get_label()=='Hydrostatic')
        np.testing.assert_array_equal(hydro.get_ydata(),before['hydrostatic']['tvd_m'])
    finally:figure.clear()
    assert prepared==before


def test_r15b_no_exposed_curve_and_no_extrapolation():
    pressure={'kind':'curves','md_m':[500.,1000.],'tvd_m':[500.,1000.],
              'pore_psi':[100.,300.],'frac_psi':[1500.,3500.]}
    assert report._formation_plot_segments(pressure,None)==[]
    with pytest.raises(ValueError,match='extrapolate'):
        report._formation_plot_segments(pressure,{'segments':[dict(top_md=400.,bottom_md=1000.,top_tvd=400.,bottom_tvd=1000.)]})


def test_r15b_actual_tieback_markers_remain_shoe_only_without_exposure():
    from test_uat_round12a3_diesel_static import diesel_state
    prepared=model.build_chart_model(diesel_state('TIE BACK LNR 7"'))
    assert prepared['static_security']['domain'] is None
    before=deepcopy(prepared);figure=report.build_chart_figure(prepared)
    try:
        lines={line.get_label():line for line in figure.axes[0].lines}
        for name,key in [('Pore','pore_psi'),('Frac','frac_psi')]:
            assert lines[name].get_marker()=='o'
            assert list(lines[name].get_ydata())==[1000.]
            np.testing.assert_array_equal(lines[name].get_xdata(),np.array(prepared['pore_frac'][key])/1000.)
    finally:figure.clear()
    assert prepared==before


def test_r15b_horizontal_open_hole_preserves_equal_tvd_values():
    import pandas as pd
    state=case_state(mode='basic');state['well_geometry']={'version':1,'type':'Directional','td_m':1000.,
        'survey':pd.DataFrame([[0.,0.,0.],[500.,90.,0.],[1000.,90.,0.]],columns=['MD','Deviation','Azimuth'])}
    prepared=model.build_chart_model(state);figure=report.build_chart_figure(prepared)
    try:
        lines={l.get_label():l for l in figure.axes[0].lines};top=prepared['static_security']['domain']['top_tvd']
        for name in ('Pore','Frac'):
            assert np.allclose(lines[name].get_ydata(),top,rtol=0,atol=1e-10)
    finally:figure.clear()


def test_r15b_surface_exposure_keeps_real_zero_pressure_endpoint():
    pressure={'kind':'curves','md_m':[0.,500.,1000.],'tvd_m':[0.,500.,1000.],
              'pore_psi':[0.,100.,200.],'frac_psi':[0.,1500.,3000.]}
    parts=report._formation_plot_segments(pressure,{'segments':[
        dict(top_md=0.,bottom_md=1000.,top_tvd=0.,bottom_tvd=1000.)]})
    assert parts==[{'tvd_m':[0.,500.,1000.],'pore_psi':[0.,100.,200.],'frac_psi':[0.,1500.,3000.]}]
