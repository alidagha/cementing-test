"""Round 12A-3: Diesel uses the existing final annulus, pressure and renderer."""
from copy import deepcopy
from itertools import groupby
from io import BytesIO
import math

import pandas as pd
from matplotlib.colors import to_hex
from PIL import Image
import pytest

import cement_chart_model as model
import cement_chart_report as report
import engineering_tools as engineering
from placement import hardware_choices, target_descriptions
from test_uat_round8a_chart_model import chart_state, hardware
from well_profile import tvd_at_md


JOBS = ('CSG 9 5/8"', 'LNR 7"', 'TIE BACK LNR 7"')
AHEAD = ("Scavenger", "Spacer Ahead", "Spacer", "Pre Flush", "Diesel")


def diesel_state(job=JOBS[0], excess="ignore"):
    """Reuse Round-8 physical geometry; official volumes specify test depth bands."""
    state = chart_state()
    state['job_type'] = state['placement_config']['job_type'] = job
    state['mud_type'] = 'OBM'
    if job == JOBS[1]:
        state['hardware_table'] = hardware(
            ('Drill Pipes', '400', '5', 4.), ('Liner', '700', '7', 6.2),
            ('Liner', '1000', '7', 6.), ('Liner Hanger', '400', '7', 6.),
            ('Previous Casing', '500', '9.625', 8.535), ('Open Hole Size', '1000', '8.5', 8.5))
    elif job == JOBS[2]:
        state['hardware_table'] = hardware(
            ('Tie Back', '1000', '7', 6.), ('Previous Casing', '1000', '9.625', 8.535),
            ('Previous Liner', '500-1300', '8.625', 7.5))
        state['placement_config']['host_row'] = next(iter(
            hardware_choices(state['hardware_table'], {'Previous Casing'})))
    state['placement_config'].update(
        target_row=next(token for token, row in
                        hardware_choices(state['hardware_table'], target_descriptions(job)).items()
                        if row['depth'] == 1000.),
        chart_excess_mode=excess, excess_csg_oh_pct=20., excess_csg_csg_pct=10.)
    geometry = model.resolve_chart_geometry(state)
    capacity = geometry['capacity_segments']
    state['fluids_config']['active'] = ['Diesel', 'Pre Flush', 'Spacer', 'Spacer Ahead',
                                       'Scavenger', 'Main', 'Displacement Fluid']
    for name, top, bottom, density in (
            ('Main', 900., 1000., '118'), ('Scavenger', 850., 900., '90'),
            ('Spacer Ahead', 800., 850., '95'), ('Spacer', 750., 800., '96'),
            ('Pre Flush', 700., 750., '62.4'), ('Diesel', 400., 700., '52.0')):
        state['fluids_config']['params'][name] = {
            'volume': model.interval_volume(capacity, top, bottom)
                      + (geometry['shoe_track_bbl'] if name == 'Main' else 0.),
            'density': density, 'pump_rate': '4'}
    return state


@pytest.mark.parametrize('job', JOBS)
@pytest.mark.parametrize('excess', ['ignore', 'apply'])
def test_final_order_and_conservation_use_existing_capacity_and_track(job, excess):
    state = diesel_state(job, excess)
    before = deepcopy(state['fluids_config'])
    result = model.build_chart_model(state)
    rows = result['annular_intervals']
    assert [name for name, _ in groupby(r['fluid'] for r in reversed(rows))] == [
        'Main', *AHEAD, 'Mud']
    diesel = [r for r in rows if r['fluid'] == 'Diesel']
    assert diesel[0]['top_md'] == pytest.approx(400., abs=1e-10)
    assert diesel[-1]['bottom_md'] == pytest.approx(700., abs=1e-10)
    assert all(r['density_pcf'] == 52. for r in diesel)
    assert rows[0]['top_md'] == 0. and rows[-1]['bottom_md'] == 1000.
    assert all(a['bottom_md'] == b['top_md'] for a, b in zip(rows, rows[1:]))
    assert math.fsum(r['in_well_bbl'] for r in rows) == pytest.approx(result['original_annular_bbl'], abs=1e-10)
    for name in AHEAD:
        placed = math.fsum(r['in_well_bbl'] for r in rows if r['fluid'] == name)
        assert placed + result['returned_bbl'][name] == pytest.approx(before['params'][name]['volume'], abs=1e-10)
    cement, = result['cement_placement']
    assert cement['in_well_bbl'] + cement['shoe_track_bbl'] + cement['returned_bbl'] == pytest.approx(
        cement['entered_bbl'], abs=1e-10)
    assert cement['top_md'] == pytest.approx(900., abs=1e-10)
    assert state['fluids_config'] == before


@pytest.mark.parametrize('value', ['51', '52.0', '54'])
def test_static_density_accepts_shared_valid_values(value):
    state = diesel_state()
    state['fluids_config']['params']['Diesel']['density'] = value
    assert model._fluid(state, 'Diesel')[1] == engineering.require_fluid_density('Diesel', value)
    rows = model.build_chart_model(state)['annular_intervals']
    assert {r['density_pcf'] for r in rows if r['fluid'] == 'Diesel'} == {float(value)}


@pytest.mark.parametrize('value', ['51-54', '52/53', 50, 55, None, True, float('nan'), float('inf')])
def test_static_density_rejects_invalid_diesel_before_model(value):
    state = diesel_state()
    state['fluids_config']['params']['Diesel']['density'] = value
    with pytest.raises(ValueError, match='Diesel density must be a single value between 51 and 54 pcf'):
        model._fluid(state, 'Diesel')
    readiness = model.chart_readiness(state, include_fluids=True)
    assert readiness['model'] is None
    assert any('Diesel density' in issue for issue in readiness['issues'])


def test_non_diesel_range_mean_remains_unchanged():
    state = diesel_state()
    state['fluids_config']['params']['Scavenger']['density'] = '80-84'
    assert model._fluid(state, 'Scavenger')[1] == 82.


def test_static_model_calls_the_shared_density_dispatcher(monkeypatch):
    calls = []
    def observe(fluid, value):
        calls.append((fluid, value))
        return engineering.require_fluid_density(fluid, value)
    monkeypatch.setattr(model, 'require_fluid_density', observe)
    model.build_chart_model(diesel_state())
    assert calls.count(('Diesel', '52.0')) == 1
    assert ('Main', '118') in calls


@pytest.mark.parametrize('job', JOBS)
@pytest.mark.parametrize('directional', [False, True])
def test_in_well_density_changes_existing_cumulative_hydrostatic(job, directional):
    state = diesel_state(job)
    if directional:
        state['well_geometry'] = {'version': 1, 'type': 'Directional', 'survey': pd.DataFrame(
            [[0., 60., 350.], [1000., 60., 10.]], columns=['MD', 'Deviation', 'Azimuth'])}
    state['fluids_config']['params']['Diesel']['density'] = '51'
    low = model.build_chart_model(state)
    state['fluids_config']['params']['Diesel']['density'] = '54'
    high = model.build_chart_model(state)
    assert low['hydrostatic']['md_m'] == high['hydrostatic']['md_m']
    assert low['cement_placement'] == high['cement_placement']
    diesel_tvd = math.fsum(tvd_at_md(state['well_geometry'], [r['bottom_md']])[0]
                          - tvd_at_md(state['well_geometry'], [r['top_md']])[0]
                          for r in low['annular_intervals'] if r['fluid'] == 'Diesel')
    assert diesel_tvd > 0
    delta = high['hydrostatic']['pressure_psi'][-1] - low['hydrostatic']['pressure_psi'][-1]
    assert delta > 0
    assert delta == pytest.approx(model.pressure_psi(3., diesel_tvd), abs=1e-10)
    for output in (low, high):
        expected = math.fsum(model.pressure_psi(r['density_pcf'],
            tvd_at_md(state['well_geometry'], [r['bottom_md']])[0]
            - tvd_at_md(state['well_geometry'], [r['top_md']])[0]) for r in output['annular_intervals'])
        assert output['hydrostatic']['pressure_psi'][-1] == pytest.approx(expected, abs=1e-10)


def test_excess_diesel_uses_existing_surface_return_behavior():
    state = diesel_state()
    geometry = model.resolve_chart_geometry(state)
    entered = model.interval_volume(geometry['capacity_segments'], 0., 700.) + 5.
    state['fluids_config']['params']['Diesel']['volume'] = entered
    result = model.build_chart_model(state)
    diesel = [r for r in result['annular_intervals'] if r['fluid'] == 'Diesel']
    assert diesel and diesel[0]['top_md'] == 0.
    assert result['returned_bbl']['Diesel'] == pytest.approx(5., abs=1e-10)
    assert math.fsum(r['in_well_bbl'] for r in diesel) + result['returned_bbl']['Diesel'] == pytest.approx(entered)
    assert 'Mud' not in [r['fluid'] for r in result['annular_intervals']]


def test_fully_returned_diesel_has_no_interval_or_pressure_contribution():
    state = diesel_state()
    geometry = model.resolve_chart_geometry(state)
    # Deliberate 1-bbl surplus ensures exhaustion, independent of depth roundoff.
    state['fluids_config']['params']['Pre Flush']['volume'] = model.interval_volume(
        geometry['capacity_segments'], 0., 750.) + 1.
    outputs = []
    for density in ('51', '54'):
        state['fluids_config']['params']['Diesel']['density'] = density
        result = model.build_chart_model(state)
        assert result['returned_bbl']['Pre Flush'] == pytest.approx(1., abs=1e-10)
        assert not any(r['fluid'] == 'Diesel' for r in result['annular_intervals'])
        assert result['returned_bbl']['Diesel'] == state['fluids_config']['params']['Diesel']['volume']
        outputs.append(result)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize('job', JOBS)
def test_inactive_diesel_draft_has_zero_effect(job):
    state = diesel_state(job)
    state['fluids_config']['active'].remove('Diesel')
    state['fluids_config']['params'].pop('Diesel')
    baseline = model.build_chart_model(state)
    state['fluids_config']['params']['Diesel'] = {'volume': float('nan'), 'density': '51-54', 'pump_rate': 'bad'}
    assert model.build_chart_model(state) == baseline
    assert 'Diesel' not in baseline['returned_bbl']
    figure = report.build_chart_figure(baseline)
    try:
        assert 'Diesel' not in [t.get_text() for t in figure.axes[1].texts]
    finally:
        figure.clear()


def test_security_responds_to_hydrostatic_only_and_unsafe_stays_warning():
    state = diesel_state()
    state['fluids_config']['params']['Diesel']['density'] = '51'
    base = model.build_chart_model(state)
    hydro = base['hydrostatic']
    state['formation_pressure_config'] = {'mode': 'advanced', 'profile': [
        {'md_m': md, 'pore_psi': 1., 'frac_psi': pressure + 1.}
        for md, pressure in zip(hydro['md_m'], hydro['pressure_psi']) if 500. <= md <= 1000.]}
    low = model.chart_readiness(state, include_fluids=True)
    assert not low['issues'] and low['model']['static_security']['status'] == 'safe'
    formation = deepcopy(state['formation_pressure_config'])
    state['fluids_config']['params']['Diesel']['density'] = '54'
    high = model.chart_readiness(state, include_fluids=True)
    assert not high['issues']
    result = high['model']
    assert result['static_security']['status'] == 'warning'
    assert result['static_security']['frac_violations']
    assert any('Static Well Security: Fracture window exceeded' in w for w in high['warnings'])
    assert result['static_security'] == model.analyze_static_security(
        state['well_geometry'], result['hydrostatic'], result['formation_pressure'])
    assert state['formation_pressure_config'] == formation
    assert result['formation_pressure'] == low['model']['formation_pressure']


@pytest.mark.parametrize('job', JOBS)
def test_renderer_exact_diesel_color_key_layout_and_in_memory_png(job, tmp_path, monkeypatch):
    assert report.COLORS['Diesel'] == '#C19552'
    assert {k: v for k, v in report.COLORS.items() if k != 'Diesel'} == {
        'Mud': '#8B1010', 'Pre Flush': '#0066E0', 'Spacer': '#00C000', 'Spacer Ahead': '#00C000',
        'Scavenger': '#C6D2BD', 'Main': '#6E6E6E', 'Lead': '#ABABAB', 'Lead #1': '#B8B8B8',
        'Lead #2': '#A2A2A2', 'Tail': '#6E6E6E'}
    prepared = model.build_chart_model(diesel_state(job))
    before = deepcopy(prepared)
    figure = report.build_chart_figure(prepared)
    try:
        assert tuple(figure.get_size_inches()) == (11.5, 8.4)
        left, right = figure.axes
        assert (left.get_title(), right.get_title()) == ('Static Well Security', 'Fluid Sequence')
        assert (left.get_ylabel(), right.get_ylabel()) == ('TVD (m)', 'MD (m)')
        bands = [p for p in right.patches if p.get_gid() == 'annulus:Diesel']
        assert bands and all(to_hex(p.get_facecolor()).upper() == '#C19552' for p in bands)
        labels = [t.get_text() for t in right.texts]
        assert labels.count('Diesel') == 1
        keys = [line for line in right.lines if line.get_transform() == right.transAxes]
        assert to_hex(keys[labels.index('Diesel')].get_color()).upper() == '#C19552'
    finally:
        figure.clear()
    monkeypatch.chdir(tmp_path)
    png = report.render_chart_png(prepared)
    assert isinstance(png, bytes) and png.startswith(b'\x89PNG\r\n\x1a\n')
    with Image.open(BytesIO(png)) as image:
        assert image.size == (2300, 1680)
    assert prepared == before and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('job', ['CMT PLUG', 'CMT SQUEEZE'])
def test_special_jobs_remain_static_chart_not_applicable(job):
    state = diesel_state()
    state['job_type'] = job
    assert model.build_chart_model(state) is None
    assert model.chart_readiness(state, include_fluids=True) == {'issues': [], 'warnings': [], 'model': None}
    assert report.prepared_cement_report(state) == {'kind': None, 'model': None}
