"""B4 consumes canonical CT placement, stages and current measured lab sources."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import re
import pandas as pd
import pytest
from docx import Document
from docxtpl import DocxTemplate
import materials_db as db
import project_state as ps
import phase_10_procedure as report
import well_report
import well_schematic_adapter as schematic
from ct_stages import ct_stage_projection, stage_note
import test_audit_regressions as audit
from test_round13b_b3_ct_schematic import state, row, PLACEHOLDER

CASE=audit.AuditRegressions()

@pytest.fixture(scope='module')
def valid_ct():
    s=state();s['ct_stage_config']['count']=3;s['bhct']=150.
    app=CASE.app(s)
    app.text_input(key='_w_client').set_value('B4 CT & Client <review>').run()
    CASE.phase(app,'phase5')
    app.session_state['lab_qc_params']={'Main':{'rheology':audit.rheology_fixture(),**audit.thickening_fixture(),**audit.compressive_fixture()}}
    CASE.phase(app,'phase7')
    for label,value in [('Free Water Collected (45° angle) (ml) - Main',0.),('Surface Sample Hours - Main',8.)]:
        next(w for w in app.number_input if w.label==label).set_value(value).run()
    next(w for w in app.text_input if w.label=='70 Bc (HH:MM) - Main').set_value('03:30').run()
    button=next(w for w in app.button if w.label=='Confirm measured lab results')
    assert not button.disabled, [w.value for w in app.warning]+[w.value for w in app.error]+[w.value for w in app.caption]
    button.click().run()
    source=app.session_state.to_dict()
    # Explicit synthetic Phase VII sources for the operational-fluid tests below;
    # legacy Phase IX drafts are never promoted into measured Lab authority.
    from test_uat_round10a_pumping_simulation import readings
    for name in ('Spacer Ahead','Spacer Behind'):
        source['lab_qc_params'][name]={'rheology':{'bhct_down':{
            'selected':True,'readings':readings(),'gel_10_sec':'-','gel_10_min':'-'}}}
    return source


def context(s,prepared=False):
    with patch.object(report.st,'session_state',s):
        return report.build_master_context(calculations_prepared=prepared)


def homa_summary_source(valid_ct):
    """Representative of the Owner-supplied dimensions, using the admitted CT fixture."""
    source = deepcopy(valid_ct)
    hardware = source['hardware_table']
    ct = hardware.loc[hardware['Description'].eq('CT')].iloc[0].to_dict()
    ct['MD (m)'] = '2987'
    hole = row('Open Hole Size', '2799.5-2987', '6 1/5', 6.125)
    # Correct the fixture's Hardware size only. The document-control draft is not geometry.
    hole['Size (in)'] = '6 1/8'
    source['hardware_table'] = pd.DataFrame([
        row('Previous Casing', '2400', '13 3/8', 12.415),
        row('Previous Liner Shoe', '2200-2799.5', '7', 6.276),
        hole,
        ct,
    ], columns=hardware.columns)
    source['doc_control'] = {**source.get('doc_control', {}), 'hole_size': '6 1/5'}
    source['fluids_config']['params']['Main'].update(volume=24.1, density='118')
    source['cement_params']['Main']['top_depth'] = 2785.
    source['ct_stage_config'].update(main_volume='24.1', count=3)
    return source


def test_uat21_ct_summary_homa_uses_verified_crossing_and_current_stages(valid_ct):
    source = homa_summary_source(valid_ct)
    source['executive_summary_config'] = {
        'version': 1, 'job_type': db.CT_JOB, 'volume_basis': 'client_request',
    }
    assert ps.prepare_calculations(source) == []
    plug = schematic.prepare_schematic(source)['payload']['cement_plugs'][0]
    assert plug == {'top_md': 2785., 'bottom_md': 2987.}
    before = ps.fingerprint([source['hardware_table'], source['fluids_config'],
                             source['cement_params'], ct_stage_projection(source)])
    paragraphs = context(source)['executive_summary'].split('\n\n')
    assert paragraphs[2] == (
        'Cement plug will be set at 2987.0 m MD. Neat cement design will be used to cement '
        '6 1/8" open hole and 7" liner; 118 pcf Main cement slurry will be cemented '
        'from 2987.0 m to 2785.0 m. The calculated cement volume is 24.1 bbl based on client request.'
    )
    assert paragraphs[3:] == [
        'Important: Due to the anticipated cement slurry volume, as well as the requirement to perform '
        'the cementing operation through Coiled Tubing (CT), the operation shall be conducted in three stages.'
    ]
    assert ps.fingerprint([source['hardware_table'], source['fluids_config'],
                           source['cement_params'], ct_stage_projection(source)]) == before


@pytest.mark.parametrize('geometry,volume,count,ending,wall', [
    ('complete', 12, None, 'one stage.', '7" liner'),
    ('casing', 24, 2, 'a minimum of two stages.', '7" casing'),
    ('hole', 24, 2, 'a minimum of two stages.', '12 1/4" open hole'),
    ('partial', 24, 2, 'a minimum of two stages.', None),
])
def test_uat21_ct_summary_other_walls_and_stage_counts(valid_ct, geometry, volume, count, ending, wall):
    source = deepcopy(valid_ct)
    source['hardware_table'] = state(geometry)['hardware_table']
    source['fluids_config']['params']['Main']['volume'] = volume
    source.pop('ct_stage_config')
    if count is not None:
        source['ct_stage_config'] = {'job_type': db.CT_JOB, 'main_volume': str(volume), 'count': count}
    summary = context(source)['executive_summary']
    paragraphs = summary.split('\n\n')
    assert summary.count('Important:') == 1 and len(paragraphs) == 4
    assert paragraphs[3] == (
        'Important: Due to the anticipated cement slurry volume, as well as the requirement to perform '
        'the cementing operation through Coiled Tubing (CT), the operation shall be conducted in ' + ending
    )
    assert 'Cement plug will be set at 3527.0 m MD.' in paragraphs[2]
    assert 'from 3527.0 m to 3470.0 m.' in paragraphs[2]
    assert f'The calculated cement volume is {volume:.1f} bbl.' in paragraphs[2]
    if wall:
        assert f'cement design will be used to cement {wall};' in paragraphs[2]
    else:
        assert not schematic.prepare_schematic(source)['available']
        assert 'cement design will be used. 118 pcf Main' in paragraphs[2]
    assert 'configured Main plug interval' not in summary


def test_uat21_ct_summary_geometry_and_review_are_source_bound(valid_ct):
    source = homa_summary_source(valid_ct)
    # A top exactly at the shoe occupies no positive interval inside the liner.
    source['cement_params']['Main']['top_depth'] = 2799.5
    assert '6 1/8" open hole;' in context(source)['executive_summary']
    hole = source['hardware_table']['Description'].eq('Open Hole Size')
    source['hardware_table'].loc[hole, ['Size (in)', 'ID (in)']] = ['6.147', 6.147]
    assert '6.147" open hole;' in context(source)['executive_summary']
    source['hardware_table'].loc[hole, 'Size (in)'] = '6 1/5'
    source['_compiled_doc_bytes'] = b'stale'
    with pytest.raises(ValueError, match='Size and ID/Bit Size must match'):
        context(source, prepared=True)
    assert '_compiled_doc_bytes' not in source


def test_uat21_ct_summary_only_claims_explicit_current_client_basis(valid_ct):
    source = deepcopy(valid_ct)
    source['executive_summary_config'] = {
        'version': 1, 'job_type': db.CT_JOB,
        'per_slurry': {'Main': {'volume_basis': 'client_request', 'excess_csg_oh_pct': 9.0,
                                'wet_stands': 3.0, 'liner_lap_m': 2.0}},
    }
    summary = context(source)['executive_summary']
    assert 'client request' not in summary
    assert 'stands wet' not in summary and 'liner lap' not in summary
    assert 'based on 9% excess for OH-CSG, giving 20.0 bbl for main slurry.' in summary
    source['executive_summary_config']['volume_basis'] = 'client_request'
    assert 'The calculated cement volume is 20.0 bbl based on client request.' in context(source)['executive_summary']


@pytest.mark.parametrize('fault', ['missing', 'stale', 'invalid'])
def test_uat21_ct_summary_rejects_unusable_stage_selection(valid_ct, fault):
    source = deepcopy(valid_ct)
    if fault == 'missing':
        source.pop('ct_stage_config')
    elif fault == 'stale':
        source['ct_stage_config']['main_volume'] = '21'
    else:
        source['ct_stage_config']['count'] = 4
    with patch.object(report.st, 'session_state', source):
        with pytest.raises(ValueError, match='Phase V CT stages'):
            report.synchronize_report_texts()
    assert not source.get('exec_summary_text')


def test_uat21_ct_summary_stage_and_geometry_edits_preserve_manual_review(valid_ct):
    source = deepcopy(valid_ct)
    source['ct_stage_config']['count'] = 2
    before = context(source)
    first = source['report_text_state']['exec_summary_text']['source_signature']
    source['ct_stage_config']['count'] = 3
    after = context(source)
    assert 'a minimum of two stages.' in before['executive_summary']
    assert 'three stages.' in after['executive_summary']
    assert source['report_text_state']['exec_summary_text']['source_signature'] != first
    assert report.document_signature(before, report.TEMPLATE_PATH) != report.document_signature(after, report.TEMPLATE_PATH)

    liner = source['hardware_table']['Description'].eq('Previous Liner Shoe')
    source['hardware_table'].loc[liner, 'Size (in)'] = '7 5/8'
    geometry_edit = context(source)
    assert '7 5/8" liner' in geometry_edit['executive_summary']
    assert report.document_signature(after, report.TEMPLATE_PATH) != report.document_signature(geometry_edit, report.TEMPLATE_PATH)

    manual = 'Operator-reviewed CT Executive Summary.'
    source['exec_summary_text'] = manual
    with patch.object(report.st, 'session_state', source):
        spec = report.synchronize_report_texts()['exec_summary_text']
        ps.accept_report_text(source, 'exec_summary_text', spec['generated'], spec['signature'])
        source['ct_stage_config']['count'] = 2
        updated = report.synchronize_report_texts()['exec_summary_text']
        assert updated['pending'] and updated['signature'] != spec['signature']
        assert source['exec_summary_text'] == manual
        with pytest.raises(ValueError, match='preserved manual'):
            report.build_master_context()
    restored = audit.round_trip(source)
    assert restored['exec_summary_text'] == manual
    with patch.object(report.st, 'session_state', restored):
        assert report.synchronize_report_texts()['exec_summary_text']['pending']


def test_uat21_ct_summary_word_has_same_text_as_editor_and_keeps_template_style(valid_ct, tmp_path):
    source = homa_summary_source(valid_ct)
    app = CASE.app(audit.round_trip(source))
    CASE.phase(app, 'phase10')
    editor = next(w for w in app.text_area if w.label == 'Executive Summary Text (Official NIDC Format):')
    build = next(w for w in app.button if w.label == 'Build Word Document')
    assert not build.disabled, [w.value for w in app.error]
    build.click().run(timeout=90)
    CASE.healthy(app)
    data = app.session_state['_compiled_doc_bytes']
    word = Document(BytesIO(data))
    body = next(p for p in word.paragraphs if p.text.startswith('Enclosed are our recommendations'))
    template = next(p for p in Document(report.TEMPLATE_PATH).paragraphs if '{{ executive_summary }}' in p.text)
    assert body.text == editor.value
    assert body.style.style_id == template.style.style_id
    assert body.alignment == template.alignment
    assert body.paragraph_format.line_spacing == template.paragraph_format.line_spacing
    preamble, safety, placement, important = body.text.split('\n\n')
    assert preamble == ('Enclosed are our recommendations for NIDC Cement Engineering and Planning Department '
                        'intervention on the referenced well. The proposal includes well data, materials and '
                        'resources requirements.')
    assert safety == ('NIDC has established a safety policy to which all NIDC personnel must adhere. A pre-job '
                      'safety meeting will be held with client representatives and other on location personnel '
                      'to familiarize everyone with existing hazards and safety procedures. We would appreciate '
                      'close cooperation between the client representative and the NIDC representative to ensure '
                      'a safe operation.')
    assert '6 1/8" open hole and 7" liner;' in placement and '6 1/5' not in placement
    assert important.startswith('Important:') and important.endswith('three stages.')
    assert sum(p.text.count('Important:') for p in word.paragraphs) == 1
    (tmp_path / 'uat21-a-ct-summary.docx').write_bytes(data)


def test_uat21_b_homa_note5_in_actual_word(valid_ct, tmp_path):
    source = homa_summary_source(valid_ct)
    source['cement_params']['Main'].update(
        mix_water=14.021480453863592, dead_vol=1.98, tank_name='Cement Unit Tanks',
    )
    app = CASE.app(audit.round_trip(source))
    CASE.phase(app, 'phase10')
    build = next(w for w in app.button if w.label == 'Build Word Document')
    assert not build.disabled, [w.value for w in app.error]
    build.click().run(timeout=90)
    CASE.healthy(app)
    data = app.session_state['_compiled_doc_bytes']
    (tmp_path / 'uat21-b-note5.docx').write_bytes(data)
    projection = ct_stage_projection(app.session_state)
    assert f"{projection['display_water_bbl']:.1f}" == '16.0'
    assert tuple(f'{water:.1f}' for water in projection['water_bbl']) == ('5.3', '5.3', '5.4')
    assert sum(projection['water_bbl']) == projection['display_water_bbl']

    paragraphs = Document(BytesIO(data)).paragraphs
    note_index = next(index for index, p in enumerate(paragraphs) if p.text.startswith('NOTE 5:'))
    note = paragraphs[note_index]
    assert note.text == (
        'NOTE 5: Mix above Additives in 16.0 bbl. fresh water at Cement Unit Tanks. '
        '(Three stages: 5.3, 5.3 and 5.4 bbl. fresh water.)'
    )
    assert 'pump truck tanks' not in note.text
    assert 'Main cement stages (bbl)' not in note.text and 'Mixing water stages (bbl)' not in note.text
    assert sum(p.text == note.text for p in paragraphs) == 1
    program = next(i for i, p in enumerate(paragraphs) if p.text.strip() == 'V. Cementing Program')
    preflush = next(i for i, p in enumerate(paragraphs) if p.text.strip() == 'VI. Pre-flush Program')
    assert program < note_index < preflush
    numbers = [int(hit[1]) for p in paragraphs if (hit := re.match(r'NOTE (\d+):', p.text.lstrip()))]
    assert numbers == list(range(1, 10))
    template_note = next(p for p in Document(report.TEMPLATE_PATH).paragraphs if '{{ s.note_mix }}' in p.text)
    assert note.style.style_id == template_note.style.style_id
    assert note.alignment == template_note.alignment
    assert note.paragraph_format.space_after == template_note.paragraph_format.space_after

    technical_note = stage_note(projection)
    assert app.session_state['cement_note_Main'].endswith(technical_note)
    assert any(p.text.startswith('5. Prepare Cement Unit Tanks with 16.0 bbl Fresh Water')
               and p.text.endswith(technical_note) for p in paragraphs)
    summary = next(p.text for p in paragraphs if p.text.startswith('Enclosed are our recommendations'))
    assert '6 1/8" open hole and 7" liner;' in summary
    assert summary.count('Important:') == 1 and summary.endswith('three stages.')


@pytest.mark.parametrize('volume,count,water,tank,allocation,detail', [
    (12, None, 14., 'Cement Unit Tanks', ('16.0',), 'One stage: 16.0 bbl. fresh water.'),
    (20, 2, 14., 'Cement Unit Tanks', ('8.0', '8.0'), 'Two stages and each stage 8.0 bbl. fresh water.'),
    (19, 2, 14., 'Mud Reserve Tanks', ('8.4', '7.6'), 'Two stages: 8.4 and 7.6 bbl. fresh water.'),
    (18, 3, 13., 'Mud Reserve Tanks', ('5.0', '5.0', '5.0'), 'Three stages and each stage 5.0 bbl. fresh water.'),
])
def test_uat21_b_note_uses_current_allocation_and_tank(valid_ct, volume, count, water, tank, allocation, detail):
    source = deepcopy(valid_ct)
    source['fluids_config']['params']['Main']['volume'] = volume
    source['cement_params']['Main'].update(mix_water=water, dead_vol=2., tank_name=tank)
    source.pop('ct_stage_config')
    if count is not None:
        source['ct_stage_config'] = {'job_type': db.CT_JOB, 'main_volume': str(volume), 'count': count}
    assert ps.prepare_calculations(source) == []
    projection = ct_stage_projection(source)
    assert projection['count'] == len(allocation)
    assert tuple(f'{amount:.1f}' for amount in projection['water_bbl']) == allocation
    assert sum(projection['water_bbl']) == projection['display_water_bbl']
    before = ps.fingerprint([source['cement_params'], source['fluids_config'],
                             source['lab_qc_params'], projection])
    ctx = context(source)
    assert ctx['slurries'][0]['note_mix'] == (
        f"NOTE 5: Mix above Additives in {water + 2:.1f} bbl. fresh water at {tank}. ({detail})"
    )
    assert ctx['slurries'][0]['mix_water_bbl'] == water
    assert ctx['slurries'][0]['total_water_bbl'] == water + 2
    assert stage_note(projection) in ctx['procedure']
    assert source['cement_note_Main'].endswith(stage_note(projection))
    assert ps.fingerprint([source['cement_params'], source['fluids_config'],
                           source['lab_qc_params'], ct_stage_projection(source)]) == before


def test_uat21_b_repeated_word_and_source_edits_retire_stale_note(valid_ct):
    source = deepcopy(valid_ct)
    source['ct_stage_config']['count'] = 2
    source['cement_params']['Main'].update(mix_water=14., dead_vol=2., tank_name='Cement Unit Tanks')
    app = CASE.app(audit.round_trip(source))

    def build_word():
        CASE.phase(app, 'phase10')
        build = next(w for w in app.button if w.label == 'Build Word Document')
        assert not build.disabled, [w.value for w in app.error]
        build.click().run(timeout=90)
        CASE.healthy(app)
        data = app.session_state['_compiled_doc_bytes']
        note = next(p.text for p in Document(BytesIO(data)).paragraphs if p.text.startswith('NOTE 5:'))
        with ZipFile(BytesIO(data)) as package:
            return note, app.session_state['_compiled_doc_signature'], package.read('word/document.xml')

    first = build_word()
    assert '(Two stages and each stage 8.0 bbl. fresh water.)' in first[0]
    assert build_word() == first
    CASE.phase(app, 'phase5')
    before = ps.fingerprint([app.session_state['cement_params'], app.session_state['fluids_config'],
                             app.session_state['lab_qc_params']])
    next(w for w in app.selectbox if w.label == 'Stage count - Main').set_value('3 stages').run()
    assert '_compiled_doc_bytes' not in app.session_state
    assert ps.fingerprint([app.session_state['cement_params'], app.session_state['fluids_config'],
                           app.session_state['lab_qc_params']]) == before
    resplit = build_word()
    assert '(Three stages: 5.6, 5.6 and 4.8 bbl. fresh water.)' in resplit[0]
    assert resplit[1] != first[1] and resplit[2] != first[2]

    CASE.phase(app, 'phase5')
    dead_volume = next(w for w in app.number_input if w.label == 'Dead Vol (bbl) - Main')
    dead_volume.set_value(3.).run()
    assert '_compiled_doc_bytes' not in app.session_state
    refilled = build_word()
    assert '17.0 bbl. fresh water' in refilled[0]
    assert refilled[1] != resplit[1] and refilled[2] != resplit[2]
    assert app.session_state['cement_params']['Main']['mix_water'] == 14.


def test_uat21_abc_homa_program_in_actual_word(valid_ct, tmp_path):
    source = homa_summary_source(valid_ct)
    source['cement_params']['Main'].update(
        mix_water=14.021480453863592, dead_vol=1.98, tank_name='Cement Unit Tanks',
    )
    config = source['fluids_config']
    config['active'] = ['Displacement Fluid', 'Spacer Behind', 'Main', 'Spacer Ahead']
    for name, volume in [('Spacer Ahead', 5.), ('Spacer Behind', .5)]:
        config['params'][name] = dict(volume=volume, density='80', pump_rate='0.7-1.2',
                                      material_name='Fresh Water')
    config['params']['Displacement Fluid'].update(volume=26., material_name='Mud')
    app = CASE.app(audit.round_trip(source))
    CASE.phase(app, 'phase10')
    build = next(w for w in app.button if w.label == 'Build Word Document')
    assert not build.disabled, [w.value for w in app.error]
    build.click().run(timeout=90)
    CASE.healthy(app)
    data = app.session_state['_compiled_doc_bytes']
    (tmp_path / 'uat21-abc-homa.docx').write_bytes(data)
    document = Document(BytesIO(data))
    paragraphs = [p.text.strip() for p in document.paragraphs]
    train = [p for p in paragraphs if re.match(r'(8|9|10|11)\. ', p)]
    note = next(p for p in paragraphs if p.startswith('NOTE 5:'))
    assert (train, note) == ([
        '8. Pump 5.0 bbl Fresh Water as spacer ahead.',
        '9. Mix and pump 24.1 bbl Main cement slurry (118 pcf). (Three stages: 8.0, 8.0 and 8.1 bbl.)',
        '10. Pump 0.5 bbl Fresh Water as spacer behind.',
        '11. Displace cement slurry with 26.0 bbl Mud (planned; confirm final volume at rig site).',
    ], 'NOTE 5: Mix above Additives in 16.0 bbl. fresh water at Cement Unit Tanks. '
       '(Three stages: 5.3, 5.3 and 5.4 bbl. fresh water.)')
    assert sum(p.startswith('NOTE 5:') for p in paragraphs) == 1
    assert not re.search(r'\brespectively\b', ' '.join(document.element.xpath('.//w:t/text()')), re.I)
    assert any(p.startswith('12. Displacement Volume: Calculate at rig site.') for p in paragraphs)
    assert any('6 1/8" open hole and 7" liner;' in p and 'Important:' in p for p in paragraphs)
    assert stage_note(ct_stage_projection(app.session_state)) in next(p for p in paragraphs if p.startswith('5. Prepare '))


@pytest.mark.parametrize('volume,count,detail', [
    (12, None, 'One stage: 12.0 bbl.'),
    (20, 2, 'Two stages and each stage 10.0 bbl.'),
    (12.01, 2, 'Two stages: 6.0 and 6.01 bbl.'),
    (18, 3, 'Three stages and each stage 6.0 bbl.'),
    (20, 3, 'Three stages: 7.0, 7.0 and 6.0 bbl.'),
])
def test_uat21_abc_pumping_cement_projection_preserves_stage_precision(valid_ct, volume, count, detail):
    source = deepcopy(valid_ct)
    source['fluids_config']['params']['Main']['volume'] = volume
    source.pop('ct_stage_config')
    if count is not None:
        source['ct_stage_config'] = {'job_type': db.CT_JOB, 'main_volume': str(volume), 'count': count}
    assert ps.prepare_calculations(source) == []
    projection = ct_stage_projection(source)
    sources = ps.fingerprint([source['fluid_data'], source['fluids_config'], source['cement_params'], projection])
    ctx = context(source)
    steps = ctx['procedure'].splitlines()
    main = next(line for line in steps if 'Mix and pump' in line)
    assert main.endswith(f'Main cement slurry (118 pcf). ({detail})')
    from decimal import Decimal
    assert Decimal(main.split('Mix and pump ')[1].split()[0]) == projection['source_main_bbl']
    assert sum(projection['cement_bbl']) == projection['source_main_bbl']
    assert 'as spacer ahead' not in ctx['procedure'] and 'as spacer behind' not in ctx['procedure']
    assert not re.search(r'\brespectively\b', ' '.join([ctx['procedure'], ctx['exec_summary'], *ctx['all_notes']]), re.I)
    assert sources == ps.fingerprint([source['fluid_data'], source['fluids_config'], source['cement_params'],
                                       ct_stage_projection(source)])


def test_uat21_abc_optional_fluids_keep_selected_materials_and_order(valid_ct):
    source = deepcopy(valid_ct)
    source['mud_type'] = 'OBM'
    source['well_data']['mud_type'] = 'OBM'
    config = source['fluids_config']
    config['active'] = ['Displacement Fluid', 'Main', 'Spacer Ahead', 'Pre Flush', 'Diesel']
    for name, volume, material in [('Diesel', 1., 'Diesel'), ('Pre Flush', 2.3, 'Field wash'),
                                   ('Spacer Ahead', 4.2, 'Weighted brine')]:
        config['params'][name] = dict(volume=volume, density='52' if name == 'Diesel' else '80',
                                      pump_rate='1', material_name=material)
    source['preflush_config'] = {'type': 'Fresh Water Only', 'nacl_multiplier': 126., 'wash_multiplier': 3.}
    ctx = context(source)
    assert [row['name'] for row in ctx['fluids_train']] == ['Diesel', 'Pre Flush', 'Spacer Ahead', 'Main',
                                                          'Displacement Fluid']
    steps = ctx['procedure'].splitlines()
    assert [line for line in steps if re.match(r'(8|9|10)\. ', line)] == [
        '8. Pump 1.0 bbl Diesel.',
        '9. Pump 2.3 bbl Field wash as pre flush.',
        '10. Pump 4.2 bbl Weighted brine as spacer ahead.',
    ]
    assert any(line.startswith('13. Displacement Volume: Calculate at rig site.') for line in steps)
    assert not any('as spacer behind' in line for line in steps)


def test_current_ct_is_admitted_and_dedicated_procedure_uses_sources(valid_ct):
    s=deepcopy(valid_ct)
    assert ps.prepare_calculations(s)==[]
    ctx=context(s)
    text=ctx['procedure'] if 'procedure' in ctx else s['procedure_text']
    assert ctx['job_type']==db.CT_JOB
    assert '3527.0 m MD' in text and '3470.0 m' in ctx['executive_summary']
    for term in ['Coiled Tubing','3000 psi','DAQ','30 m above','Displacement Volume: Calculate at rig site.','WOC']:
        assert term in text,term
    assert 'Mix and pump 20.0 bbl Main cement slurry (118 pcf). (Three stages: 7.0, 7.0 and 6.0 bbl.)' in text
    main = next(row for row in ctx['fluids_train'] if row['name'] == 'Main')
    assert main['pump_rate'] == '0.7-1.2' and main['duration_min'] == 20 / .7
    assert 'calculated duration' not in text and '0.7–1.2 bpm' not in text
    assert stage_note(ct_stage_projection(s)) in text
    assert ctx['slurries'][0]['note_mix'] == (
        'NOTE 5: Mix above Additives in 14.0 bbl. fresh water at Mud Reserve Tanks. '
        '(Three stages: 4.9, 4.9 and 4.2 bbl. fresh water.)'
    )
    assert '7 + 7 + 6' in text and '4.9 + 4.9 + 4.2' in text
    assert not re.search(r'drill.?pipe|swage|stands|bump|plug release',text,re.I)
    steps=[int(x) for x in re.findall(r'(?m)^(\d+)\. ',text)]
    assert steps==list(range(1,len(steps)+1))


@pytest.mark.parametrize('kind',['complete','partial'])
def test_actual_ct_docx_uses_existing_section_ii_and_canonical_context(valid_ct,kind,tmp_path):
    s=deepcopy(valid_ct);s['hardware_table']=state(kind)['hardware_table']
    ctx=context(s)
    doc=DocxTemplate('master_template.docx');doc.render(report._word_quantity_context(ctx));buf=BytesIO();doc.save(buf)
    result=well_report.postprocess_well_report(buf.getvalue(),ctx['well_profile_report'],ctx['note_vertical'],ctx['cement_chart_report'],ctx['centralizer_report'],
        pumping_report=__import__('pumping_simulation').prepare_pumping_simulation(s),
        schematic_report=schematic.prepare_schematic(s))
    out=Document(BytesIO(result));xml=ZipFile(BytesIO(result)).read('word/document.xml').decode()
    from test_uat_round9g_centralizer_word import ix_region
    from docx.oxml.ns import qn
    region=ix_region(out)
    section_text='\n'.join(''.join(t.text or '' for t in e.iter(qn('w:t'))) for e in region)
    assert section_text.count('Not applicable (Plug/Squeeze).')==1
    assert not any(t._tbl in region for t in out.tables)
    assert not any(e.xpath('.//w:drawing') for e in region)
    assert len(region[-1].xpath('.//w:br[@w:type="page"]'))==1
    assert db.CT_JOB in xml and 'B4 CT &amp; Client &lt;review&gt;' in xml
    assert 'Spacer Formulation Data' not in xml and 'Spacer Additives Data' not in xml
    assert '{{' not in xml and '{%' not in xml
    assert '3527.0 m MD' in xml and '3470.0 m' in xml
    assert 'Displacement Volume: Calculate at rig site.' in xml
    if kind=='partial':assert PLACEHOLDER in '\n'.join(p.text for p in out.paragraphs)
    else:assert out.inline_shapes
    (tmp_path/f'ct-{kind}.docx').write_bytes(result)


@pytest.mark.parametrize('prepared',[False,True])
@pytest.mark.parametrize('fault',['depth','top','stage','rate','volume','lab','geometry'])
def test_all_ct_report_entry_points_fail_closed_and_invalidate(valid_ct,prepared,fault):
    s=deepcopy(valid_ct);s['_compiled_doc_bytes']=b'stale'
    if fault=='depth':s['hardware_table'].loc[s['hardware_table']['Description']=='CT','MD (m)']='3500-3527'
    elif fault=='top':s['cement_params']['Main']['top_depth']=3527.
    elif fault=='stage':s['ct_stage_config']['count']=2;s['fluids_config']['params']['Main']['volume']=30.
    elif fault=='rate':s['fluids_config']['params']['Main']['pump_rate']='0'
    elif fault=='volume':s['fluids_config']['params']['Displacement Fluid']['volume']=0.
    elif fault=='lab':s['lab_qc_params']['Main']['reviewed']=False
    elif fault=='geometry':s['hardware_table'].loc[0,'ID (in)']=20.
    with pytest.raises(ValueError):context(s,prepared)
    assert '_compiled_doc_bytes' not in s


def test_stage_depth_and_operational_edits_preserve_manual_text_for_review(valid_ct):
    s=deepcopy(valid_ct);context(s)
    s['procedure_text']+='\nEngineer reviewed CT instruction.'
    with patch.object(report.st,'session_state',s):
        spec=report.synchronize_report_texts()['procedure_text']
        ps.accept_report_text(s,'procedure_text',spec['generated'],spec['signature'])
        s['ct_stage_config']['count']=2
        specs=report.synchronize_report_texts()
    assert specs['procedure_text']['pending']
    assert s['procedure_text'].endswith('Engineer reviewed CT instruction.')
    with pytest.raises(ValueError,match='preserved manual'):context(s)


@pytest.mark.parametrize('job',[db.CT_JOB,'CMT PLUG','CMT SQUEEZE'])
def test_explicit_nonapplicable_centralizer_contract(job):
    import centralizer_report as bridge
    expected={'applicable':False,'analysis':None,'view':None,'source':None,'warning':False}
    assert bridge.prepare_report({'job_type':job})==expected


@pytest.mark.parametrize('job',['CSG 9 5/8"','LNR 7"','TIE BACK LNR 7"'])
def test_applicable_jobs_still_require_executed_centralizer(job):
    import centralizer_report as bridge
    assert bridge.prepare_report({'job_type':job}) == {
        'applicable':True, 'current':False, 'analysis':None,
        'view':None, 'source':None, 'warning':True}

COMBINATIONS=[(),('Spacer Ahead',),('Spacer Behind',),('Spacer Ahead','Spacer Behind'),('Pre Flush',),('Pre Flush','Spacer Ahead')]


@pytest.mark.parametrize('fluid',['Spacer Ahead','Spacer Behind'])
def test_uat20_ct_selected_auxiliary_retains_program_without_phase7_source(valid_ct,fluid):
    s=deepcopy(valid_ct)
    s['fluids_config']['active'].insert(0,fluid)
    s['fluids_config']['params'][fluid]={'volume':7.5,'density':'80','pump_rate':'0.7-1.2','material_name':fluid}
    s['lab_qc_params'].pop(fluid)
    ps.refresh_fluids(s)
    ctx = context(s)
    assert fluid in [row['name'] for row in ctx['fluids_train']]
    assert fluid not in s['lab_qc_params']

    s['lab_qc_params']['Main']['reviewed'] = False
    with pytest.raises(ValueError, match='Main: Phase VII internal lab results must be confirmed'):
        context(s)


@pytest.mark.parametrize('job',db.JOB_TYPES)
@pytest.mark.parametrize('selected',COMBINATIONS)
def test_all_job_operational_procedure_contract(valid_ct,job,selected):
    from test_round13b_b4_operational_spacers import operational
    s=deepcopy(valid_ct) if job==db.CT_JOB else operational(job)
    cfg=s['fluids_config'];cfg['active']=[*selected,'Main','Displacement Fluid']
    for name in selected:
        cfg['params'][name]={'volume':7.5,'density':'80','pump_rate':'0.7-1.2','material_name':name+' field & material'}
    s['preflush_config']={'type':'Fresh Water Only','nacl_multiplier':126.,'wash_multiplier':3.}
    ps.refresh_fluids(s);ps.refresh_preflush(s)
    before=deepcopy(s.get('cement_params'))
    with patch.object(report.st,'session_state',s):
        text=report.generate_official_procedure(job,s['fluid_data'],cfg['active'],s['cement_params'],s.get('cement_additives_dfs',{}),s.get('preflush_calc'),s.get('geo_md'),s.get('total_pump_time_min'),s.get('placement_config'))
    assert s['cement_params']==before
    positions=[]
    for name in cfg['active']:
        if name in ('Spacer Ahead','Spacer Behind'):
            record=s['fluid_data'][name]
            if job == db.CT_JOB:
                line = next(l for l in text.splitlines() if l.endswith(f'as {name.lower()}.'))
                assert line.split('. ', 1)[1] == f"Pump 7.5 bbl {record['material_name']} as {name.lower()}."
                assert record['pump_rate'] == '0.7-1.2' and record['duration_min'] == 7.5 / .7
                ctx = context(s)
                word_row = next(row for row in report._word_quantity_context(ctx)['fluids_train']
                                if row['name'] == name)
                assert word_row['pump_rate'] == '0.7–1.2' and word_row['duration_str'] != '00:00'
            else:
                line=next(l for l in text.splitlines() if 'as '+name in l)
                assert record['material_name'] in line and '0.7–1.2' in line
                from engineering_tools import format_to_hr_mm
                index=cfg['active'].index(name)
                previous=s['fluid_data'][cfg['active'][index-1]]['cumul_time_min'] if index else 0
                def minute_boundary(value):
                    h,m=map(int,format_to_hr_mm(value).split(':'));return h*60+m
                expected=format_to_hr_mm(minute_boundary(record['cumul_time_min'])-minute_boundary(previous))
                assert f'duration {expected} (HH:MM).' in line
            positions.append((cfg['active'].index(name),text.index(line)))
    pump_main=next(l for l in text.splitlines() if ('as Main' in l or 'Main cement slurry' in l))
    for index,position in positions:
        assert (position<text.index(pump_main))==(index<cfg['active'].index('Main'))
    if 'Pre Flush' in selected:assert 'pre flush' in text.lower()
    assert 'Hematite' not in text


def test_ct_ui_build_restore_and_operational_edits_retire_download(valid_ct,tmp_path):
    from test_uat_round10c_integration import save_project,restore_project
    app=CASE.app(deepcopy(valid_ct));CASE.phase(app,'phase4')
    for name in ('Pre Flush','Spacer Ahead','Spacer Behind'):
        app.checkbox(key='chk_fluid_'+name).check().run()
        app.number_input(key='vol_'+name).set_value(7.5).run()
        app.text_input(key='den_'+name).set_value('80').run()
        app.text_input(key='rate_'+name).set_value('0.7-1.2').run()
    assert all(app.checkbox(key='chk_fluid_'+name).value for name in ('Pre Flush','Spacer Ahead'))
    CASE.phase(app,'phase6')
    assert not any('_editor_spacer_' in e.proto.id for e in app.dataframe)
    assert any(w.label=='Pre-flush Fluid Type' for w in app.selectbox)
    saved=save_project(app);app=restore_project(saved)
    CASE.phase(app,'phase7')
    # The established Main review survives compatible operational-only edits.
    assert app.session_state['lab_qc_params']['Main']['reviewed']
    CASE.phase(app,'phase10')
    assert not app.error,[e.value for e in app.error]
    button=next(b for b in app.button if b.label=='Build Word Document')
    assert not button.disabled
    button.click().run(timeout=120);CASE.healthy(app)
    assert not app.error,[e.value for e in app.error]
    blob=app.session_state['_compiled_doc_bytes'];doc=Document(BytesIO(blob))
    text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert all(name in text for name in ('Spacer Ahead','Spacer Behind','Pre Flush','CMT PLUG WITH CT'))
    assert 'Spacer Additives Data' not in text and 'Spacer Formulation Data' not in text
    (tmp_path/'ct-ui-actual-build.docx').write_bytes(blob)
    CASE.phase(app,'phase4');app.number_input(key='vol_Spacer Ahead').set_value(8.).run()
    CASE.phase(app,'phase10')
    assert '_compiled_doc_bytes' not in app.session_state


def test_unrelated_guardrails_and_all_frozen_authorities_are_unchanged():
    import ast,subprocess
    before=ast.parse(subprocess.check_output(['git','show','f185c0f88bdcb9fc5342dcbf5eb306dd29c0cee6:test_regression_guardrails.py']))
    after=ast.parse(Path('test_regression_guardrails.py').read_text())
    approved=ast.parse(subprocess.check_output(['git','show','e4db7795135fc3039fe9ce281586ec80f42b75c5:test_regression_guardrails.py']))
    fixture_names={'test_master_context_contains_placement_keys','test_blank_volume_basis_exports_as_na',
                   'test_preflush_payload_recomputed_at_export_time','test_spacer_densities_sort_numerically'}
    fixture_nodes={node.name:node for node in approved.body
                   if isinstance(node,ast.FunctionDef) and node.name in fixture_names}
    assert set(fixture_nodes)==fixture_names
    before.body=[fixture_nodes.get(node.name,node) if isinstance(node,ast.FunctionDef) else node
                 for node in before.body]
    for tree in (before,after):
        tree.body=[node for node in tree.body if not(isinstance(node,ast.FunctionDef) and node.name=='test_render_master_document_smoke')]
    assert ast.dump(before)==ast.dump(after)
    for name in ('well_schematic_engine.py','cement_charts_engine.py','centralizer_optimizer_engine.py','standalone_spacer.py','ct_stages.py','placement.py','phase_5_cement.py','phase_7_lab.py','rheology.py','project_io.py','requirements.txt'):
        if name == 'well_schematic_engine.py':
            from test_round13b_b3_ct_schematic import assert_authorized_radial_renderer
            assert_authorized_radial_renderer(Path(name).read_bytes())
            continue
        if name == 'project_io.py':
            import hashlib
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == '20ec22a012d42de360cd84d54ffcbec923896b5a228e48b540d1e8f91a2518d2'
            continue
        if name == 'phase_7_lab.py':
            import hashlib
            from test_uat_bhsp_word import r15cd_original_lab_source
            assert hashlib.sha256(r15cd_original_lab_source(Path(name).read_bytes())).hexdigest() == 'f95e337cc8445a5b6cf8c582bb09c982a36e9d638608582d41fb50922f56903f'
            continue
        if name == 'phase_5_cement.py':
            import hashlib
            from test_round13b_b3_ct_schematic import ui03_original_display_source
            assert hashlib.sha256(ui03_original_display_source(Path(name).read_bytes(), name)).hexdigest() == '3422ef74b39d665d64dd7f5709be19e9314d75300ce55d272cdbeacda4a6dd14'
            continue
        reference='f185c0f88bdcb9fc5342dcbf5eb306dd29c0cee6'
        source = Path(name).read_bytes()
        if name == 'requirements.txt':
            source = b2a_original_requirements(source)
        if name == 'placement.py':
            from test_round13b_b1_ct_foundation import r17_original_placement_source
            source = r17_original_placement_source(source)
        assert source==subprocess.check_output(['git','show',f'{reference}:{name}'])
    from test_round13b_post_b4_word_quality import test_template_changes_only_approved_sample_text_payloads
    test_template_changes_only_approved_sample_text_payloads()


@pytest.mark.parametrize('tank',[None,'','Unknown tank'])
@pytest.mark.parametrize('prepared',[True,False])
def test_ct_tank_admission_preserves_draft_and_lab_but_retires_word(valid_ct,tank,prepared):
    s=deepcopy(valid_ct);s['cement_params']['Main']['tank_name']=tank
    s['_compiled_doc_bytes']=b'stale';review=s['lab_qc_params']['Main']['review_signature']
    with pytest.raises(ValueError,match='Phase V CT Main: select a Mixing Tank'):
        context(s,prepared)
    assert '_compiled_doc_bytes' not in s
    assert s['cement_params']['Main']['tank_name']==tank
    assert s['lab_qc_params']['Main']['reviewed']
    assert s['lab_qc_params']['Main']['review_signature']==review


@pytest.mark.parametrize('tank',db.get_available_tanks(db.CT_JOB))
def test_ct_report_uses_selected_catalog_tank_without_changing_formulation(valid_ct,tank):
    s=deepcopy(valid_ct);s['cement_params']['Main']['tank_name']=tank
    before=deepcopy(s['cement_params']);review=s['lab_qc_params']['Main']['review_signature']
    ctx=context(s)
    assert ctx['slurries'][0]['mixing_tank']==tank
    assert tank in ctx['slurries'][0]['note_mix'] and tank in s['procedure_text']
    assert s['cement_params']==before
    assert s['lab_qc_params']['Main']['reviewed']
    assert s['lab_qc_params']['Main']['review_signature']==review


def b2a_original_requirements(source):
    """Reverse only the one exact Owner-authorized B2a appended SciPy line."""
    added = b"scipy==1.14.1\n"
    assert source.endswith(added) and source.count(added) == 1
    return source[:-len(added)]
