"""Presentation-only Word corrections; engineering and template structure stay pinned."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re
import subprocess
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from docx import Document
from docxtpl import DocxTemplate

import phase_10_procedure as report
import project_state as ps
from test_round13b_b4_ct_report import valid_ct, context

PARENT = "acfe9d216f5b2ff24c62b240cf1e8729326c797e"


def neutralize_centralizer_samples(xml):
    """Replace only text payloads in the 18 owner-allowlisted sample cells."""
    edits = []
    tables = list(re.finditer(rb'<w:tbl[ >].*?</w:tbl>', xml, re.S))
    for title, indices in ((b'Centralizer Data', (2, 4, 6, 8, 10, 12)),
                           (b'Centralizer Placement', range(7, 19))):
        matches = [m for m in tables if b''.join(re.findall(
            rb'<w:t(?: [^>]*)?>(.*?)</w:t>', m.group(), re.S)).startswith(title)]
        assert len(matches) == 1
        table = matches[0]
        cells = list(re.finditer(rb'<w:tc[ >].*?</w:tc>', table.group(), re.S))
        assert len(cells) == (13 if title == b'Centralizer Data' else 19)
        for index in indices:
            cell = cells[index]
            texts = list(re.finditer(rb'<w:t(?: [^>]*)?>(.*?)</w:t>', cell.group(), re.S))
            assert texts
            for i, text in enumerate(texts):
                offset = table.start() + cell.start()
                edits.append((offset + text.start(1), offset + text.end(1), b'-' if i == 0 else b''))
    for start, end, value in sorted(edits, reverse=True):
        xml = xml[:start] + value + xml[end:]
    return xml


def approved_template_xml(xml):
    """Historical tests retain every old check after exact new-cell verification."""
    parent = ZipFile(BytesIO(subprocess.check_output([
        'git', 'show', PARENT + ':master_template.docx'])))
    original = parent.read('word/document.xml')
    assert xml == neutralize_centralizer_samples(original)
    return original


def test_template_changes_only_approved_sample_text_payloads():
    with ZipFile(BytesIO(subprocess.check_output(['git', 'show', PARENT + ':master_template.docx']))) as old, \
         ZipFile(report.TEMPLATE_PATH) as new:
        assert old.namelist() == new.namelist()
        for name in old.namelist():
            if name == 'word/document.xml':
                assert approved_template_xml(new.read(name)) == old.read(name)
            else:
                assert new.read(name) == old.read(name), name


@pytest.mark.parametrize('part,old,new', [
    ('word/document.xml', b'Top Cent. MD', b'Unapproved label'),
    ('word/document.xml', b'<w:t>-</w:t>', b'<w:t>123</w:t>'),
    ('word/document.xml', b'<w:br w:type="page"/>', b'<w:br/>'),
    ('word/styles.xml', b'</w:styles>', b'<!-- changed --></w:styles>'),
    ('word/_rels/document.xml.rels', b'</Relationships>', b'<!-- changed --></Relationships>'),
])
def test_template_contract_rejects_changes_beyond_neutral_sample_values(tmp_path, monkeypatch, part, old, new):
    target = tmp_path / 'mutated.docx'
    with ZipFile(report.TEMPLATE_PATH) as source, ZipFile(target, 'w') as archive:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == part:
                assert old in data
                data = data.replace(old, new, 1)
            archive.writestr(info, data)
    monkeypatch.setattr(report, 'TEMPLATE_PATH', target)
    with pytest.raises(AssertionError):
        test_template_changes_only_approved_sample_text_payloads()


@pytest.mark.parametrize('missing', [None, np.nan, pd.NA, '', '   '])
def test_hardware_missing_cells_are_report_only_dashes(valid_ct, missing):
    s = deepcopy(valid_ct)
    frame = s['hardware_table'].astype(object)
    ct = frame.index[frame.Description == 'CT'][0]
    for column in ('Grade', 'Joint', 'Weight (lb/ft)'):
        if column in frame: frame.at[ct, column] = missing
    frame.at[ct, 'Grade'] = missing
    s['hardware_table'] = frame
    before = frame.copy(deep=True)
    ctx = context(s)
    row = next(r for r in ctx['hardware'] if r['Description'] == 'CT')
    assert row['Grade'] == '-'
    pd.testing.assert_frame_equal(frame, before)
    doc = DocxTemplate(report.TEMPLATE_PATH); doc.render(report._word_quantity_context(ctx))
    stream = BytesIO(); doc.save(stream)
    out = Document(BytesIO(stream.getvalue()))
    table = next(t for t in out.tables if any(c.text == 'CT' for r in t.rows for c in r.cells))
    text = '\n'.join(c.text for r in table.rows for c in r.cells)
    assert not re.search(r'\b(?:None|nan|<NA>)\b', text)


@pytest.mark.parametrize('value', [0, 0.0, '0', 'N-80', 'Measured & <grade>'])
def test_hardware_nonmissing_values_and_sources_are_preserved(valid_ct, value):
    s = deepcopy(valid_ct)
    frame = s['hardware_table'].astype(object)
    ct = frame.index[frame.Description == 'CT'][0]
    frame.at[ct, 'Grade'] = value
    s['hardware_table'] = frame
    ctx = context(s)
    assert next(r for r in ctx['hardware'] if r['Description'] == 'CT')['Grade'] == report._escape_xml_special_chars(value)
    assert frame.at[ct, 'Grade'] == value


@pytest.mark.parametrize('volume,rate,display', [(1., '0.7-1.2', '1.43'),
    (7.5, '0.7-1.2', '10.71'), (10., '2', '5.00')])
def test_ct_duration_is_one_decimal_minute_projection(valid_ct, volume, rate, display):
    s = deepcopy(valid_ct)
    s['fluids_config']['params']['Displacement Fluid'].update(volume=volume, pump_rate=rate)
    ps.refresh_fluids(s)
    before = deepcopy(s['fluid_data'])
    with patch.object(report.st, 'session_state', s):
        text = report._ct_procedure(s)
    line = next(l for l in text.splitlines() if 'as Displacement Fluid' in l)
    assert f'calculated duration {display} min.' in line
    assert 'HH:MM' not in line
    assert f'at {rate} bpm' in line
    assert s['fluid_data'] == before
    assert before['Displacement Fluid']['duration_min'] == volume / float(rate.split('-')[0])
