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
