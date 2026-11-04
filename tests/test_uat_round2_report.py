"""Round 2 Batch 5: report order is independent of engineering traversal."""
from copy import deepcopy
from io import BytesIO
from html import unescape
import re
import unittest
from unittest.mock import patch

import pandas as pd
import pytest
from docx import Document
from docx.oxml.ns import qn
from docxtpl import DocxTemplate
import test_audit_regressions as audit
import phase_10_procedure as report
from centralizer_fixtures import ensure_current_centralizer
from phase_5_cement import (build_components, calculate_base_results,
                            build_cement_tables, refresh_cement_calculations)
from phase_7_lab import build_lab_df_from_phase5
from placement import slurry_intervals, hardware_choices, HOST_DESCRIPTIONS

ORDER = ['Lead', 'Lead #1', 'Lead #2', 'Main', 'Tail']
HYDRAULIC_SLURRIES = ['Main', 'Lead', 'Lead #1', 'Lead #2', 'Tail']


class Round2ReportUAT(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        case = audit.AuditRegressions()
        app = case.configured_app('CSG 9 5/8"', optional_fluids=True, include_standalone_spacer=False)
        project = audit.round_trip(app.session_state.to_dict())
        project['fluids_config']['active'] = ['Pre Flush', 'Spacer Ahead',
                                             *ORDER, 'Spacer Behind', 'Displacement Fluid']
        for i, slurry in enumerate(ORDER):
            project['fluids_config']['params'][slurry] = deepcopy(project['fluids_config']['params']['Main'])
            project['cement_params'][slurry] = deepcopy(project['cement_params']['Main'])
            placement_index = ['Main', 'Lead', 'Lead #1', 'Lead #2', 'Tail'].index(slurry)
            project['cement_params'][slurry].update(top_mode='Not entered', top_depth=None,
                                                    top_job_type=project['job_type'])
            project['cement_additives_dfs'][slurry] = pd.DataFrame([
                {'Material Type': 'Extender', 'Name': 'Micro Silica', 'Physical State': 'Powder',
                 'Mix Method': 'Dry Blend', 'User Input': 5., 'Density': 2.3},
                {'Material Type': 'F.L. Controller', 'Name': 'O-uniFLC5', 'Physical State': 'Powder',
                 'Mix Method': 'In Mix Water', 'User Input': .5, 'Density': 1.5},
                {'Material Type': 'Anti Gas Migration', 'Name': 'O-GAS BLOCK', 'Physical State': 'Liquid',
                 'Mix Method': 'In Mix Water', 'User Input': .1, 'Density': 1.2}])
            project['lab_qc_params'][slurry] = {'free_water': float(i),
                'free_water_45': i + .5, 'surface_hardened_hours': 8. + i,
                'thickening_time': '03:30', 'thickening_endpoint': '70 Bc',
                'rheology': audit.valid_export_rheology_fixture(), **audit.thickening_fixture(), **audit.compressive_fixture()}
        app = case.app(audit.round_trip(project))
        for phase in ('phase2_3', 'phase4', 'phase5', 'phase6', 'phase7'):
            case.phase(app, phase)
        for button in list(app.button):
            if button.label == 'Sync with Phase V':
                app.button(key=button.key).click().run()
        for _ in ORDER:
            next(b for b in app.button if b.label == 'Confirm measured lab results').click().run()
        case.export(app, build_timeout=120)
        cls.state = app.session_state.to_dict()

    def context(self, state=None):
        prepared = deepcopy(state or self.state)
        ensure_current_centralizer(prepared)
        with patch.object(report.st, 'session_state', prepared):
            return report.build_master_context()

    def word(self, context):
        doc = DocxTemplate(report.TEMPLATE_PATH)
        doc.render(context)
        output = BytesIO(); doc.save(output)
        return Document(BytesIO(output.getvalue()))

    def assert_word_order(self, doc, expected):
        program = [t.rows[0].cells[0].text.removesuffix(' Cement Slurry Data') for t in doc.tables
                   if t.rows[0].cells[0].text.endswith(' Cement Slurry Data')]
        lab = [p.text.removesuffix(' Cement Slurry Results') for p in doc.paragraphs
               if p.text.endswith(' Cement Slurry Results')]
        self.assertEqual(program, expected)
        self.assertEqual(lab, expected)

    def test_actual_word_sections_share_one_report_order(self):
        context = self.context()
        self.assertEqual([s['name'] for s in context['slurries']], ORDER)
        self.assert_word_order(self.word(context), ORDER)

    def test_subset_order_for_all_five_job_families(self):
        for job in audit.BATCH1_JOBS:
            for subset in (['Lead', 'Tail'], ['Lead #2', 'Main', 'Tail'], ['Main']):
                with self.subTest(job=job, subset=subset):
                    state = deepcopy(self.state)
                    state['job_type'] = state['doc_control']['job_type'] = job
                    state.update(audit.valid_export_chart_fixture(job))
                    state['placement_config'].update(job_type=job, host_row=next(iter(hardware_choices(state['hardware_table'], HOST_DESCRIPTIONS))))
                    state['fluids_config']['active'] = [*subset, 'Displacement Fluid']
                    for slurry in subset:
                        state['cement_params'][slurry].update(top_job_type=job, last_job_type=job)
                        if job in ('CMT PLUG', 'CMT SQUEEZE'):
                            state['cement_params'][slurry].update(top_mode='Depth (m MD)',
                                top_depth=500. + HYDRAULIC_SLURRIES.index(slurry)*500.)
                    # Current well/formulation inputs remain unchanged; report text is auto-generated.
                    state.pop('procedure_text', None); state.pop('exec_summary_text', None)
                    state.pop('report_text_state', None)
                    context = self.context(state)
                    self.assertEqual([s['name'] for s in context['slurries']], subset)
                    self.assert_word_order(self.word(context), subset)

    def test_report_order_ignores_interval_mapping_insertion_order(self):
        real_intervals = report.slurry_intervals
        def reverse_mapping(*args, **kwargs):
            return dict(reversed(list(real_intervals(*args, **kwargs).items())))
        original = self.context()
        with patch.object(report, 'slurry_intervals', side_effect=reverse_mapping):
            reordered = self.context()
        self.assertEqual(reordered['slurries'], original['slurries'])
        self.assertEqual([s['name'] for s in reordered['slurries']], ORDER)

    def test_chained_interval_values_and_summary_remain_engineering_order(self):
        for job in ('CSG 9 5/8"', 'LNR 7"'):
            with self.subTest(job=job):
                state = deepcopy(self.state)
                state['job_type'] = state['doc_control']['job_type'] = job
                state.update(audit.valid_export_chart_fixture(job))
                state['placement_config']['job_type'] = job
                for p in state['cement_params'].values():
                    p.update(top_job_type=job, last_job_type=job)
                state.pop('procedure_text', None); state.pop('exec_summary_text', None)
                state.pop('report_text_state', None)
                intervals = slurry_intervals(state['hardware_table'], job, state['placement_config'],
                                             HYDRAULIC_SLURRIES, state['cement_params'], state['fluids_config']['params'])
                self.assertEqual(list(intervals), list(reversed(HYDRAULIC_SLURRIES)))
                context = self.context(state)
                for payload in context['slurries']:
                    self.assertEqual(payload['top'], intervals[payload['name']]['top'])
                    self.assertEqual(payload['bottom'], f"{intervals[payload['name']]['bottom_depth']:.1f} m MD")
                self.assertEqual([name.title() for name in re.findall(
                    r'(lead(?: #\d)?|main|tail) cement slurry will be cemented from', context['exec_summary'])], list(reversed(HYDRAULIC_SLURRIES)))
                self.assert_word_order(self.word(context), ORDER)

    def test_operational_fluids_procedure_and_timing_are_not_sorted_for_report(self):
        state = deepcopy(self.state)
        context = self.context(state)
        self.assertEqual([f['name'] for f in context['fluids_train']], state['fluids_config']['active'])
        self.assertEqual(unescape(context['procedure_text']), state['procedure_text'])
        positions = [context['procedure_text'].index(f'{s} cement slurry (') for s in HYDRAULIC_SLURRIES]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(state['total_pump_time_min'], 112.5)
        self.assertIn('Safety Factor is 141 min', context['note_maxpump'])

    def test_existing_preflush_spacer_payload_and_document_flow(self):
        context = self.context()
        self.assertTrue(context['has_preflush']); self.assertFalse(context['has_spacer'])
        self.assertEqual(context['spacers'], [])
        self.assertEqual([f['name'] for f in context['fluids_train']
                          if f['name'] in ('Spacer Ahead', 'Spacer Behind')],
                         ['Spacer Ahead', 'Spacer Behind'])
        self.assertEqual(context['spacer_volume_bbl'], 100.)
        self.assertEqual(context['spacer_density_note'], '80.0')
        self.assertEqual(context['preflush']['volume'], 50.)
        doc = self.word(context)
        titles = [t.rows[0].cells[0].text for t in doc.tables]
        self.assertEqual(titles.count('Pre Flush Data'), 1)
        self.assertNotIn('Spacer Formulation Data', titles)
        self.assertNotIn('Spacer Additives Data', titles)
        sequence = next(t for t in doc.tables if any(c.text == 'Spacer Behind' for r in t.rows for c in r.cells))
        for fluid in ('Spacer Ahead', 'Spacer Behind'):
            self.assertEqual(sum(r.cells[0].text == fluid for r in sequence.rows), 1)
        # XML body order includes paragraphs and tables, unlike separate python-docx lists.
        text = '\n'.join(''.join(t.text or '' for t in node.iter(qn('w:t'))) for node in doc.element.body)
        self.assertLess(text.index('Tail Cement Slurry Additives Data'), text.index('Pre Flush Data'))
        self.assertLess(text.index('Pre Flush Data'), text.rindex('VII. Laboratory Report'))
        self.assertNotIn('Spacer Cement Slurry Results', text)
        self.assertNotIn('Pre Flush Cement Slurry Results', text)

    def test_both_mix_note_paths_keep_base_water_tank_and_remove_only_suffix(self):
        context = self.context()
        for s in context['slurries']:
            with self.subTest(slurry=s['name']):
                p = deepcopy(self.state['cement_params'][s['name']])
                df = self.state['cement_additives_dfs'][s['name']]
                result = calculate_base_results(p, s['volume_bbl'], float(s['density_pcf']), *build_components(df))
                blend, adds, note = build_cement_tables(p, df, result)
                self.assertEqual(note, f"Mix above Additives in **{p['mix_water'] + p['dead_vol']:.1f} bbl** Fresh Water at **{p['tank_name']}**.")
                self.assertRegex(s['note_mix'], rf"^NOTE \d+: Mix above Additives in {s['total_water_bbl']:.1f} bbl Fresh Water at {p['tank_name']}\.$")
                pd.testing.assert_frame_equal(blend, self.state['cement_blend_' + s['name']])
                pd.testing.assert_frame_equal(adds, self.state['cement_calc_' + s['name']])
                self.assertIn('Micro Silica', blend['Name'].tolist())
                self.assertNotIn('Micro Silica', adds['Name'].tolist())
        doc = self.word(context)
        text = '\n'.join(p.text for p in doc.paragraphs)
        self.assertNotIn('pre-blended dry with bulk cement', text)
        self.assertEqual(text.count('Mix above Additives in '), 5)

    def test_note_counter_sequence_and_slurry_association(self):
        context = self.context()
        numbers = [int(re.match(r'NOTE (\d+):', n).group(1)) for n in context['all_notes']]
        self.assertEqual(numbers, list(range(1, 29)))
        self.assertEqual(len(numbers), len(set(numbers)))
        for i, s in enumerate(context['slurries']):
            self.assertTrue(s['note_mix'].startswith(f'NOTE {7 + i}:'))
            self.assertTrue(s['lab']['note_thickening'].endswith(f'After {8+i} Hours'))
        doc = Document(BytesIO(self.state['_compiled_doc_bytes']))
        actual = [int(re.match(r'NOTE (\d+):', p.text.strip()).group(1)) for p in doc.paragraphs
                  if re.match(r'NOTE \d+:', p.text.strip())]
        self.assertEqual(actual, numbers)

    def test_density_override_engineering_and_lab_are_unchanged_by_notes(self):
        state = deepcopy(self.state)
        before = deepcopy(state['cement_params'])
        self.assertEqual(refresh_cement_calculations(state), [])
        self.assertEqual(state['cement_params'], before)
        for s in ORDER:
            df = state['cement_additives_dfs'][s]
            powders, liquids, _ = build_components(df)
            self.assertEqual(powders[0]['density_pcf'], 2.3 * 62.4)
            self.assertEqual(powders[1]['density_pcf'], 1.5 * 62.4)
            self.assertEqual(liquids[0]['density_ppg'], 1.2 * (62.4 / 7.48051945))
            expected = build_lab_df_from_phase5(df, base_cement=before[s]['base_cement'],
                slurry_weight_pcf=118., slurry_volume_bbl=50., cmt_sg=3.2, recalculate_mass=True)
            pd.testing.assert_frame_equal(expected, state['lab_grid_dfs'][s])


if __name__ == '__main__':
    unittest.main()


@pytest.fixture(scope='module')
def r17_lab_context():
    # Reuse the genuine formulation → measured synthetic QC → explicit review
    # sequence above; no signatures or successful receipts are fabricated.
    Round2ReportUAT.setUpClass()
    case = audit.AuditRegressions()
    app = case.app(deepcopy(Round2ReportUAT.state))
    for i,name in enumerate(ORDER):
        frame = app.session_state['cement_additives_dfs'][name]
        frame.loc[0,'User Input'] = 5. + i*1.25
        frame.loc[2,'User Input'] = .15 + i*.05
    case.phase(app,'phase5'); case.phase(app,'phase7')
    for button in list(app.button):
        if button.label == 'Sync with Phase V':
            app.button(key=button.key).click().run()
    for _ in ORDER:
        next(b for b in app.button if b.label == 'Confirm measured lab results').click().run()
    case.healthy(app)
    return Round2ReportUAT().context(app.session_state.to_dict())


def r17_lab_word(context, processor=None):
    import well_report
    tpl = DocxTemplate(report.TEMPLATE_PATH)
    tpl.render(report._word_quantity_context(context))
    stream = BytesIO(); tpl.save(stream)
    processor = processor or well_report.postprocess_well_report
    return processor(stream.getvalue(), context['well_profile_report'],
        context['note_vertical'], context['cement_chart_report'], context['centralizer_report'],
        section_vi_programs={key:context[key] for key in ('has_preflush','has_spacer')})


def test_r17_lab_totals_are_attached_only_under_mass_column(r17_lab_context, tmp_path):
    context = deepcopy(r17_lab_context)
    original = deepcopy([(s['lab_conventional'],s['lab_additives']) for s in context['slurries']])
    data = r17_lab_word(context)
    (tmp_path/'lab-totals.docx').write_bytes(data)
    doc = Document(BytesIO(data))
    tables = [t for t in doc.tables if t.cell(0,0).text == 'Conventional']
    assert len(tables) == len(ORDER) == 5
    for key in ('lab_conventional','lab_additives'):
        assert len({s[key][-1]['Mass'] for s in context['slurries']}) == 5
    for table, slurry in zip(tables, context['slurries']):
        assert len(table._tbl.tblGrid.gridCol_lst) == 6
        labels = [i for i,r in enumerate(table.rows) if r.cells[0].text in ('Conventional','Additives')]
        assert len(labels) == 2
        for start,end,key in ((labels[0],labels[1],'lab_conventional'),(labels[1],len(table.rows),'lab_additives')):
            rows = table.rows[start+2:end]
            totals = [r for r in rows if not any(c.text for c in r.cells[:5]) and r.cells[5].text]
            assert len(totals) == 1
            total = totals[0]
            assert total.cells[5].text == slurry[key][-1]['Mass']
            assert total._tr.getparent() is table._tbl
            assert len(total._tr.tc_lst) == 6
            for cell in total.cells[:5]:
                for edge in ('top','left','bottom','right'):
                    borders = cell._tc.tcPr.find(qn('w:tcBorders'))
                    assert borders is not None
                    border = borders.find(qn('w:'+edge))
                    assert border is not None and border.get(qn('w:val')) == 'nil'
            last = total.cells[5]._tc.tcPr.find(qn('w:tcBorders'))
            for edge in ('left','bottom','right'):
                assert last.find(qn('w:'+edge)).get(qn('w:val')) == 'single'
    assert [(s['lab_conventional'],s['lab_additives']) for s in context['slurries']] == original


@pytest.fixture(scope='module')
def r17_lab_pair(r17_lab_context):
    import ast, subprocess, well_report
    parent = subprocess.check_output(['git','show',
        '47e9650b93fbad85ca5be56cfb7a0f3615c629a4:well_report.py'])
    node = next(n for n in ast.parse(parent).body if isinstance(n,ast.FunctionDef)
                and n.name == 'postprocess_well_report')
    namespace = dict(well_report.__dict__)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'approved_parent_processor','exec'),namespace)
    return (r17_lab_word(r17_lab_context,namespace['postprocess_well_report']),
            r17_lab_word(r17_lab_context))


def r17_restore_allowed_border_delta(before, after):
    """Independent comparator: only total-cell border changes are eligible."""
    from lxml import etree
    old = Document(BytesIO(before));new = Document(BytesIO(after))
    targets = 0
    for a,b in zip(old.tables,new.tables):
        if a.cell(0,0).text != 'Conventional':
            continue
        assert len(a.rows) == len(b.rows)
        for aa,bb in zip(a.rows,b.rows):
            if any(c.text for c in aa.cells[:5]) or not aa.cells[5].text:
                continue
            targets += 1
            for index,(left,right) in enumerate(zip(aa.cells,bb.cells)):
                old_border = left._tc.tcPr.find(qn('w:tcBorders'))
                new_border = right._tc.tcPr.find(qn('w:tcBorders'))
                if index == 5:
                    expected = deepcopy(aa.cells[4]._tc.tcPr.find(qn('w:tcBorders')).find(qn('w:right')))
                    expected.tag = qn('w:left')
                    actual = new_border.find(qn('w:left'))
                    assert actual.tag == expected.tag and dict(actual.attrib) == dict(expected.attrib)
                    assert len(actual) == len(expected) == 0
                    new_border.replace(new_border.find(qn('w:left')),deepcopy(old_border.find(qn('w:left'))))
                else:
                    right._tc.tcPr.replace(new_border,deepcopy(old_border))
    assert targets == 10
    return etree.tostring(old.element),etree.tostring(new.element)


def test_r17_only_total_borders_change_and_other_tables_are_protected(r17_lab_pair, tmp_path):
    from zipfile import ZipFile
    before,after = r17_lab_pair
    (tmp_path/'before.docx').write_bytes(before);(tmp_path/'after.docx').write_bytes(after)
    with ZipFile(BytesIO(before)) as a, ZipFile(BytesIO(after)) as b:
        assert a.namelist() == b.namelist()
        assert all(a.read(n)==b.read(n) for n in a.namelist() if n!='word/document.xml')
    old,new = r17_restore_allowed_border_delta(before,after)
    assert old == new
    other = Document(BytesIO(after))
    table = next(t for t in other.tables if 'Cement Slurry Additives Data' in t.cell(0,0).text)
    table.cell(1,0).text = 'MUTATION'
    stream = BytesIO();other.save(stream)
    old,new = r17_restore_allowed_border_delta(before,stream.getvalue())
    assert old != new  # A change in another Additives table cannot hide in the allowlist.


@pytest.mark.parametrize('fault',['section','header','duplicate','grid','total_merge','second_total'])
def test_r17_ambiguous_or_changed_lab_layout_fails_closed(r17_lab_pair, fault):
    import well_report
    doc = Document(BytesIO(r17_lab_pair[0]))
    table = next(t for t in doc.tables if t.cell(0,0).text == 'Conventional')
    total = next(r for r in table.rows if not any(c.text for c in r.cells[:5]) and r.cells[5].text)
    if fault == 'section':
        next(p for p in doc.paragraphs if p.text=='VII. Laboratory Report').text='Changed laboratory section'
    elif fault == 'header': table.cell(1,5).text='Changed mass units'
    elif fault == 'duplicate': table._tbl.addnext(deepcopy(table._tbl))
    elif fault == 'grid': table._tbl.tblGrid.remove(table._tbl.tblGrid.gridCol_lst[-1])
    elif fault == 'total_merge': total.cells[0].merge(total.cells[1])
    else: total._tr.addprevious(deepcopy(total._tr))
    with pytest.raises(ValueError,match='Lab Report.*six-column'):
        well_report._attach_lab_total_cells(doc)


def test_r17_no_total_rows_are_neither_invented_nor_reformatted(r17_lab_pair):
    import well_report
    from lxml import etree
    # Projection-only missing/zero mass cases; these are not claimed to be
    # independently admissible, reviewed Phase VII engineering projects.
    for mass in ('-','0'):
        frame = pd.DataFrame([{'Material':'Cement','Mass':mass,'Unit':'BWOB'},
                              {'Material':'Base Water','Mass':mass,'Unit':'BWOW'}])
        conv,adds = report.separate_lab_tables(frame)
        assert len(conv)==len(adds)==1
    doc = Document(BytesIO(r17_lab_pair[0]))
    for table in doc.tables:
        if table.cell(0,0).text == 'Conventional':
            for row in list(table.rows):
                if not any(c.text for c in row.cells[:5]) and row.cells[5].text:
                    table._tbl.remove(row._tr)
    before = etree.tostring(doc.element)
    well_report._attach_lab_total_cells(doc)
    assert etree.tostring(doc.element)==before


def r17_bug03_sources(job, names=('Main',)):
    from test_round15_nested_geometry import bug01_geometry_case, BUG01_JOBS
    state = (bug01_geometry_case(job) if job in BUG01_JOBS else
             {'job_type':job, **audit.valid_export_chart_fixture(job, target=3000.)})
    state['cement_params'] = {name: {'top_mode':'Depth (m MD)',
        'top_depth':3719. if job=='LNR 5"' else 100., 'top_job_type':job} for name in names}
    state['fluid_data'] = {name:{'volume':57. if job=='LNR 5"' else 8.,
        'density':'118', 'pump_rate':'4'} for name in names}
    if job in ('CSG 30"','CSG 24"','CSG 20"','CSG 18 5/8"'):
        state['fluid_data']['Main']['volume']=100.
    state['fluids_config'] = {'active':list(names),'params':deepcopy(state['fluid_data'])}
    return state


def r17_bug03_summary(state):
    with patch.object(report.st,'session_state',state):
        return report.generate_executive_summary(state['job_type'],state['fluid_data'],
            state['fluids_config']['active'],state.get('cement_additives_dfs',{}),
            state['hardware_table'],cement_params=state['cement_params'],
            placement_config=state['placement_config'])


@pytest.mark.parametrize('job,shoe,top', [('LNR 5"',4500.,3719.),('CSG 9 5/8"',1200.,100.)])
def test_r17_bug03_manual_top_governs_summary_without_moving_engine(job,shoe,top,tmp_path):
    from project_state import fingerprint
    state=r17_bug03_sources(job)
    before=fingerprint(state)
    intervals=slurry_intervals(state['hardware_table'],job,state['placement_config'],
        ['Main'],state['cement_params'],state['fluid_data'])
    if job=='LNR 5"':
        assert f"{intervals['Main']['top_depth']:.1f}"=='3206.3'
        assert state['fluid_data']['Main']['volume']==57.
    text=r17_bug03_summary(state)
    (tmp_path/'summary.txt').write_text(text)
    assert f'from the shoe at {shoe:.1f} m to {top:.1f} m' in text
    assert fingerprint(state)==before
    assert slurry_intervals(state['hardware_table'],job,state['placement_config'],
        ['Main'],state['cement_params'],state['fluid_data'])==intervals


@pytest.mark.parametrize('job', [j for j in report.materials_db.JOB_TYPES if j!=report.materials_db.CT_JOB])
@pytest.mark.parametrize('mode', ['Depth (m MD)','Surface','Not entered','other job','legacy'])
def test_r17_bug03_top_modes_all_report_families_preserve_sources(job,mode):
    from project_state import fingerprint
    state=r17_bug03_sources(job)
    p=state['cement_params']['Main']
    p['top_mode']='Depth (m MD)' if mode=='other job' else mode
    if mode=='legacy': p.pop('top_mode');p.pop('top_job_type')
    if mode=='other job':p['top_job_type']='CSG 24"' if job!='CSG 24"' else 'LNR 7"'
    before=fingerprint(state)
    interval=slurry_intervals(state['hardware_table'],job,state['placement_config'],
        ['Main'],state['cement_params'],state['fluid_data'])['Main']
    assert 'issue' not in interval
    text=r17_bug03_summary(state)
    payload=report._attach_placement_fields({'name':'Main'},p,state['hardware_table'],job,
        state['placement_config'],interval)
    if mode in ('Depth (m MD)','legacy'):
        expected=f"{p['top_depth']:.1f} m"
    elif mode=='Surface':expected='surface'
    else:expected=interval['top']
    if job=='CMT SQUEEZE':
        assert f"at {interval['bottom_depth']:.1f} m MD" in text
        assert 'cement slurry will be cemented from' not in text
        assert ('with top of cement at '+expected in text)==(mode in ('Depth (m MD)','Surface','legacy'))
    else:assert 'to '+expected in text
    assert payload['top']==(expected if mode not in ('Not entered','other job') or interval['top_depth'] is not None else '....')
    assert fingerprint(state)==before


@pytest.mark.parametrize('raw', [None,0,-1,1200.,1201.,float('nan'),float('inf'),'bad','100-200',True])
def test_r17_bug03_invalid_top_keeps_existing_admission_and_sources(raw):
    import ast,subprocess
    from project_state import fingerprint
    state=r17_bug03_sources('CSG 9 5/8"');state['cement_params']['Main']['top_depth']=raw
    before=fingerprint(state)
    parent=ast.parse(subprocess.check_output(['git','show','8133dc03cd57743ead434b9a39d876410eab8b33:phase_10_procedure.py']))
    namespace=dict(report.__dict__)
    exec(compile(ast.Module(body=[n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='generate_executive_summary'],type_ignores=[]),'prior_admission','exec'),namespace)
    with patch.object(report.st,'session_state',state):
        old=namespace['generate_executive_summary'](state['job_type'],state['fluid_data'],['Main'],{},
            state['hardware_table'],cement_params=state['cement_params'],placement_config=state['placement_config'])
    text=r17_bug03_summary(state)
    assert text==old  # No new rejection, gate token or invented manual depth.
    specs={'exec_summary_text':{'generated':text},'procedure_text':{'generated':''}}
    with patch.object(report.st,'session_state',{}):
        assert report.unresolved_export_inputs(specs)==[]
    assert fingerprint(state)==before


def test_r17_bug03_existing_review_and_signatures_are_unchanged():
    import ast,subprocess
    import project_state as ps
    # Keep source signatures and the explicit existing Regenerate workflow.
    parent=ast.parse(subprocess.check_output(['git','show','8133dc03cd57743ead434b9a39d876410eab8b33:phase_10_procedure.py']))
    names={'generate_executive_summary','synchronize_report_texts'}
    namespace=dict(report.__dict__)
    exec(compile(ast.Module(body=[n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'r17_parent_report','exec'),namespace)
    state=r17_bug03_sources('LNR 5"')
    with patch.object(report.st,'session_state',state):
        old=namespace['synchronize_report_texts']()
        assert 'to 3206.3 m' in state['exec_summary_text']
        new=report.synchronize_report_texts()
        assert 'to 3719.0 m' in new['exec_summary_text']['generated']
        assert new['exec_summary_text']['signature']==old['exec_summary_text']['signature']
        assert 'to 3206.3 m' in state['exec_summary_text']  # Stored text is never silently rewritten.
        ps.accept_report_text(state,'exec_summary_text',new['exec_summary_text']['generated'],
            new['exec_summary_text']['signature'],replace=True)
        assert 'to 3719.0 m' in state['exec_summary_text']
        assert new['procedure_text']==old['procedure_text']
        assert new==report.synchronize_report_texts()
        state['exec_summary_text']='Owner-reviewed custom TOC narrative.'
        state['cement_params']['Main']['top_depth']=3700.
        pending=report.synchronize_report_texts()['exec_summary_text']
        assert pending['pending'] and state['exec_summary_text']=='Owner-reviewed custom TOC narrative.'
        ps.accept_report_text(state,'exec_summary_text',pending['generated'],pending['signature'])
        assert not report.synchronize_report_texts()['exec_summary_text']['pending']
        ps.accept_report_text(state,'exec_summary_text',pending['generated'],pending['signature'],replace=True)
        assert 'to 3700.0 m' in state['exec_summary_text']
        ps.restore_previous_text(state,'exec_summary_text')
        assert state['exec_summary_text']=='Owner-reviewed custom TOC narrative.'
        assert report.synchronize_report_texts()['exec_summary_text']['pending']
    # No revision/source drift for Not entered or unchanged Plug semantics.
    for job in ('CSG 9 5/8"','CMT PLUG'):
        state=r17_bug03_sources(job)
        if job!='CMT PLUG':state['cement_params']['Main']['top_mode']='Not entered'
        with patch.object(report.st,'session_state',state):
            assert namespace['synchronize_report_texts']()==report.synchronize_report_texts()


def test_r17_bug03_planned_boundaries_do_not_replace_calculated_boundaries():
    from project_state import fingerprint
    import test_regression_guardrails as guards
    guards._seed_session()
    state=report.st.session_state.to_dict()
    # The permanent benchmark is the authoritative existing positive source.
    intervals=slurry_intervals(state['hardware_table'],state['job_type'],state['placement_config'],
        ['Lead','Tail'],state['cement_params'],state['fluid_data'])
    before=fingerprint(state)
    assert state['cement_params']['Lead']['top_depth']==1250.
    assert state['cement_params']['Tail']['top_depth']==2000.
    assert f"{intervals['Tail']['top_depth']:.1f}"=='1192.2'
    text=r17_bug03_summary(state)
    assert 'tail cement slurry will be cemented from the shoe at 2816.0 m to 2000.0 m' in text
    assert 'lead cement slurry will be cemented from 2000.0 m to 1250.0 m' in text
    assert fingerprint(state)==before
    assert slurry_intervals(state['hardware_table'],state['job_type'],state['placement_config'],
        ['Lead','Tail'],state['cement_params'],state['fluid_data'])==intervals


def test_r17_bug03_five_slurry_word_uses_planned_tops_only(r17_lab_context,tmp_path):
    import project_state as ps
    # Reuse genuine synthetic measured QC and explicit reviews from BUG01.
    state=deepcopy(Round2ReportUAT.state)
    engine=slurry_intervals(state['hardware_table'],state['job_type'],state['placement_config'],
        HYDRAULIC_SLURRIES,state['cement_params'],state['fluid_data'])
    original=ps.fingerprint({k:state[k] for k in ('fluid_data','lab_qc_params','hardware_table')})
    for i,name in enumerate(ORDER):
        state['cement_params'][name].update(top_mode='Depth (m MD)',
            top_depth=100.+HYDRAULIC_SLURRIES.index(name)*100.,top_job_type=state['job_type'])
    with patch.object(report.st,'session_state',state):
        ctx=report.build_master_context()
        signature=report.document_signature(ctx,str(report.TEMPLATE_PATH))
    data=r17_lab_word(ctx);(tmp_path/'five-planned-tops.docx').write_bytes(data)
    doc=Document(BytesIO(data));text='\n'.join(p.text for p in doc.paragraphs)
    for i,name in enumerate(ORDER):
        top=f'{100.+HYDRAULIC_SLURRIES.index(name)*100.:.1f} m'
        assert 'to '+top in ctx['exec_summary'] and 'to '+top in text
        table=next(t for t in doc.tables if t.cell(0,0).text==name+' Cement Slurry Data')
        row=next(r for r in table.rows if r.cells[0].text=='Bottom')
        assert row.cells[3].text==top
    assert ps.fingerprint({k:state[k] for k in ('fluid_data','lab_qc_params','hardware_table')})==original
    assert slurry_intervals(state['hardware_table'],state['job_type'],state['placement_config'],
        HYDRAULIC_SLURRIES,state['cement_params'],state['fluid_data'])==engine
    restored=audit.round_trip(state)
    assert restored['cement_params']==state['cement_params']
    assert '_compiled_doc_bytes' not in restored
    import phase_9_centralizer as phase9
    assert not phase9.result_is_current(restored)  # JSON correctly retires computed results.
    with patch.object(report.st,'session_state',restored):
        rebuilt=report.build_master_context()
        assert rebuilt['exec_summary']==ctx['exec_summary']
    ensure_current_centralizer(restored)  # Real solver, not a seeded receipt.
    assert phase9.result_is_current(restored)
    with patch.object(report.st,'session_state',restored):
        rebuilt=report.build_master_context()
        assert report.document_signature(rebuilt,str(report.TEMPLATE_PATH))==signature
    changed=deepcopy(state);changed['_r17_top_edit']=150.
    from phase_5_cement import _commit_cement_param
    with patch.object(report.st,'session_state',changed):
        _commit_cement_param('Main','top_depth','_r17_top_edit')
        assert '_compiled_doc_bytes' not in changed
        fresh=report.build_master_context()
        assert report.document_signature(fresh,str(report.TEMPLATE_PATH))!=signature
    assert 'to 150.0 m' in fresh['exec_summary']


from test_round13b_b4_ct_report import valid_ct as r17_bug03_valid_ct


@pytest.mark.parametrize('top',[3470.,3500.])
def test_r17_bug03_ct_keeps_independent_top_and_bottom(r17_bug03_valid_ct,top,tmp_path):
    import project_state as ps
    state=deepcopy(r17_bug03_valid_ct)
    state['cement_params']['Main']['top_depth']=top
    before=ps.fingerprint(state['fluids_config'])
    with patch.object(report.st,'session_state',state):
        ctx=report.build_master_context()
    assert f'from 3527.0 m to {top:.1f} m' in ctx['exec_summary']
    assert ctx['slurries'][0]['top']==f'{top:.1f} m'
    assert ctx['slurries'][0]['bottom']=='3527.0 m MD'
    data=r17_lab_word(ctx);(tmp_path/'ct-planned-top.docx').write_bytes(data)
    assert f'to {top:.1f} m' in '\n'.join(p.text for p in Document(BytesIO(data)).paragraphs)
    assert ps.fingerprint(state['fluids_config'])==before


def test_r17_bug03_dq19_real_word_and_prior_source_comparison(r17_lab_context,tmp_path):
    import ast,subprocess
    import project_state as ps
    from zipfile import ZipFile
    from lxml import etree
    measured=r17_bug03_sources('LNR 5"')
    # Measured DQ-19 geometry/57bbl/3719m plus explicitly synthetic
    # formulation, measured QC and genuine UI review; zone products stay NULL.
    from test_round15_nested_geometry import bug01_dq19
    measured_geometry=bug01_dq19()
    state=deepcopy(Round2ReportUAT.state)
    state.update(measured_geometry)
    state.update(audit.well_profile_fixture(4550.))
    state['doc_control']['job_type']=state['job_type']
    state['fluids_config']={'active':['Main','Displacement Fluid'],'params':{
        'Main':dict(state['fluids_config']['params']['Main'],volume=57.),
        'Displacement Fluid':deepcopy(state['fluids_config']['params']['Displacement Fluid'])}}
    state['cement_params']['Main'].update(measured['cement_params']['Main'],last_job_type=state['job_type'])
    state.pop('exec_summary_text',None);state.pop('procedure_text',None);state.pop('report_text_state',None)
    case=audit.AuditRegressions();app=case.app(audit.round_trip(state))
    for phase in ('phase2_3','phase4','phase5','phase7'):case.phase(app,phase)
    for button in list(app.button):
        if button.label=='Sync with Phase V':app.button(key=button.key).click().run()
    next(b for b in app.button if b.label=='Confirm measured lab results' and not b.disabled).click().run()
    case.phase(app,'phase10');case.healthy(app)
    build=next(b for b in app.button if b.label=='Build Word Document')
    assert not build.disabled
    build.click().run(timeout=120);case.healthy(app);assert not app.error
    state=app.session_state.to_dict();data=state['_compiled_doc_bytes']
    assert all(z['product_nr'] is None for z in state['centralizer_config']['zones'])
    assert state['fluid_data']['Main']['volume']==57.
    assert state['cement_params']['Main']['top_depth']==3719.
    interval=slurry_intervals(state['hardware_table'],state['job_type'],state['placement_config'],
        ['Main'],state['cement_params'],state['fluid_data'])['Main']
    assert f"{interval['top_depth']:.1f}"=='3206.3'
    with patch.object(report.st,'session_state',state):ctx=report.build_master_context()
    parent=ast.parse(subprocess.check_output(['git','show','8133dc03cd57743ead434b9a39d876410eab8b33:phase_10_procedure.py']))
    namespace=dict(report.__dict__)
    exec(compile(ast.Module(body=[n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='generate_executive_summary'],type_ignores=[]),'parent_summary','exec'),namespace)
    old=namespace['generate_executive_summary'](state['job_type'],state['fluid_data'],state['fluids_config']['active'],
        state['cement_additives_dfs'],state['hardware_table'],cement_params=state['cement_params'],placement_config=state['placement_config'])
    assert 'from the shoe at 4500.0 m to 3206.3 m' in old
    assert ctx['exec_summary']==old.replace('to 3206.3 m','to 3719.0 m',1)
    old_ctx=dict(ctx,exec_summary=old,executive_summary=old)
    before=r17_lab_word(old_ctx);after=r17_lab_word(ctx)
    (tmp_path/'dq19-browser-independent-build.docx').write_bytes(data)
    (tmp_path/'dq19-before.docx').write_bytes(before);(tmp_path/'dq19-after.docx').write_bytes(after)
    doc=Document(BytesIO(data));assert 'to 3719.0 m' in '\n'.join(p.text for p in doc.paragraphs)
    table=next(t for t in doc.tables if t.cell(0,0).text=='Main Cement Slurry Data')
    row=next(r for r in table.rows if r.cells[0].text=='Bottom');assert row.cells[3].text=='3719.0 m'
    with ZipFile(BytesIO(before)) as a,ZipFile(BytesIO(after)) as b:
        assert a.namelist()==b.namelist()
        assert all(a.read(n)==b.read(n) for n in a.namelist() if n!='word/document.xml')
        root=etree.fromstring(b.read('word/document.xml'));count=0
        for t in root.iter(qn('w:t')):
            if t.text and 'from the shoe at 4500.0 m to 3719.0 m' in t.text:
                t.text=t.text.replace('to 3719.0 m','to 3206.3 m',1);count+=1
        assert count==1
        assert etree.tostring(root)==etree.tostring(etree.fromstring(a.read('word/document.xml')))
