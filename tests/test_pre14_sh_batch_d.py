"""One default-aware comparison protects all serializable project work."""
from copy import deepcopy
import hashlib
import json
from unittest.mock import patch

import pytest
import streamlit as st

import test_audit_regressions as audit
from test_pre_round14_ui02_navigation_persistence import dirty, upload
from test_round12_ui01_project_download import downloads, prepare
from test_uat_round10c_integration import save_project

CASE = audit.AuditRegressions()
INCOMING = b'{"well_name":"Batch D incoming"}'
CHANGES = {
    'preflush_config': {'wash_multiplier': 6.0},
    'schematic_config': {'squeeze_target_id': 'retained-source'},
    'formation_pressure_config': {'mode': 'advanced', 'profile': [
        {'md_m': 100., 'pore_psi': None, 'frac_psi': None}]},
    'standalone_spacer_config': {'mode': 'Barite', 'dead_vol': 0.0},
    'report_text_state': {'procedure_text': {'history': ['Retained operator wording']}},
}


def mark_saved(app, calls):
    prepare(app)
    offered = calls[-1]
    # Invoke the actual native-download callback (AppTest cannot click it),
    # retaining the production offered-byte and comparison authorities.
    receipt = app.session_state.to_dict()
    with patch.object(st, 'session_state', receipt):
        offered['on_click'](*offered['args'])
    for key in ('_saved_sig', '_saved_comparison_sig', '_saved_at'):
        app.session_state[key] = receipt[key]
    for key in ('_saved_from_upload', '_baseline_loaded_project'):
        if key in app.session_state and key not in receipt:
            del app.session_state[key]
    app.run()
    CASE.healthy(app)
    assert receipt['_saved_sig'] == hashlib.md5(offered['data'].encode()).hexdigest()
    return offered


def assert_replacement_guard(app):
    before = save_project(app)
    warning = dirty(app)
    with upload(app, INCOMING):
        app.run()
        CASE.healthy(app)
        assert warning and any(b.key == '_confirm_upload_replacement' for b in app.button)
        assert save_project(app) == before
        app.button(key='_cancel_upload_replacement').click().run()
        CASE.healthy(app)
        assert save_project(app) == before
    with upload(app, INCOMING):
        app.run()
        app.button(key='_confirm_upload_replacement').click().run()
        CASE.healthy(app)
        assert app.session_state['well_name'] == 'Batch D incoming'
        assert not dirty(app)


@pytest.mark.parametrize('key', list(CHANGES))
def test_h1_each_retained_configuration_guards_replacement_and_cancel(key):
    app = CASE.app()
    app.session_state[key] = deepcopy(CHANGES[key])
    app.run()
    assert app.session_state[key] == CHANGES[key]
    assert_replacement_guard(app)


@pytest.mark.parametrize('value', [0, False, None, {}, [], ''])
def test_h1_unknown_serializable_values_are_not_disposable(value):
    app = CASE.app()
    app.session_state['future_operator_draft'] = value
    app.run()
    assert_replacement_guard(app)


def test_m2_real_save_then_navigation_only_stays_clean(downloads):
    app = CASE.app({'well_name': 'Batch D saved'})
    mark_saved(app, downloads)
    receipt = app.session_state['_saved_sig']
    for phase in ('phase2_3', 'phase5', 'phase6', 'phase7', 'phase10', 'phase1'):
        CASE.phase(app, phase)
        assert not dirty(app), phase
        assert app.session_state['_saved_sig'] == receipt
    with upload(app, INCOMING):
        app.run()
        assert app.session_state['well_name'] == 'Batch D incoming'
        assert not any(b.key == '_confirm_upload_replacement' for b in app.button)


def test_l9_default_phase9_mount_is_clean_and_keeps_json_configuration():
    import phase_9_centralizer as p9
    app = CASE.app()
    CASE.phase(app, 'phase9')
    assert app.session_state['centralizer_config'] == p9.new_config()
    assert json.loads(save_project(app))['centralizer_config'] == p9.new_config()
    assert not dirty(app)
    with upload(app, INCOMING):
        app.run()
        assert app.session_state['well_name'] == 'Batch D incoming'
        assert not any(b.key == '_confirm_upload_replacement' for b in app.button)


def test_l1_pending_baseline_survives_serialization_failure():
    import phase_1_doc_control as phase1
    render = phase1.render
    def fail_post_load():
        render()
        if st.session_state.get('_baseline_loaded_project'):
            st.session_state['synthetic_unserializable'] = float('inf')
    app = CASE.app()
    with patch.object(phase1, 'render', fail_post_load), upload(app, b'{"well_name":"Loaded baseline"}'):
        app.run()
        CASE.healthy(app)
    assert any('invalid value' in e.value for e in app.error)
    assert app.session_state.get('_baseline_loaded_project') is True
    assert '_saved_sig' not in app.session_state
    assert dirty(app)


@pytest.mark.parametrize('edited', [False, True])
def test_l1_failed_first_render_recovery_cannot_swallow_an_operator_edit(edited):
    import phase_1_doc_control as phase1
    render = phase1.render
    def fail_post_load():
        render()
        if st.session_state.get('_baseline_loaded_project'):
            st.session_state['synthetic_unserializable'] = float('inf')
    app = CASE.app()
    with patch.object(phase1, 'render', fail_post_load), upload(app, b'{"well_name":"Recovery checkpoint"}'):
        app.run()
        CASE.healthy(app)
    baseline = app.session_state['_saved_comparison_sig']
    with upload(app, INCOMING):
        app.run()
        assert any(b.key == '_confirm_upload_replacement' for b in app.button)
        assert app.session_state['well_name'] == 'Recovery checkpoint'
        assert app.session_state['synthetic_unserializable'] == float('inf')
        app.button(key='_cancel_upload_replacement').click().run()
        assert app.session_state['_baseline_loaded_project'] is True
        assert app.session_state['_saved_comparison_sig'] == baseline
    del app.session_state['synthetic_unserializable']
    if edited:
        app.text_input(key='_w_well_name').set_value('Unsaved recovery edit')
        CASE.phase(app, 'phase2_3')
    else:
        app.run()
    CASE.healthy(app)
    assert '_baseline_loaded_project' not in app.session_state
    assert dirty(app) is edited
    assert app.session_state['_saved_comparison_sig'] == baseline
    if edited:
        assert '_saved_sig' not in app.session_state
        assert_replacement_guard(app)
    else:
        expected = json.dumps(json.loads(save_project(app)), indent=4, ensure_ascii=False, sort_keys=True)
        assert app.session_state['_saved_sig'] == hashlib.md5(expected.encode()).hexdigest()


def test_real_inactive_preflush_ratio_draft_is_not_disposable():
    app = CASE.app()
    CASE.phase(app, 'phase4')
    app.checkbox(key='chk_fluid_Pre Flush').check().run()
    app.number_input(key='vol_Pre Flush').set_value(25.).run()
    app.text_input(key='den_Pre Flush').set_value('80').run()
    app.text_input(key='rate_Pre Flush').set_value('4').run()
    CASE.phase(app, 'phase6')
    widget = next(w for w in app.number_input if 'Wash' in w.label)
    widget.set_value(7.).run()
    CASE.phase(app, 'phase4')
    app.number_input(key='vol_Pre Flush').set_value(0.).run()
    app.text_input(key='den_Pre Flush').set_value('').run()
    app.text_input(key='rate_Pre Flush').set_value('').run()
    app.checkbox(key='chk_fluid_Pre Flush').uncheck().run()
    CASE.phase(app, 'phase6')
    CASE.phase(app, 'phase1')
    assert app.session_state['preflush_config']['wash_multiplier'] == 7.
    assert_replacement_guard(app)


def test_ct_stage_only_edit_protects_an_existing_saved_checkpoint(downloads):
    import materials_db as db
    app = CASE.app({'job_type': db.CT_JOB, 'fluids_config': {'active': ['Main'], 'params': {
        'Main': {'volume': 20., 'density': '118', 'pump_rate': '1'}}}})
    mark_saved(app, downloads)
    assert not dirty(app)
    app.session_state['ct_stage_config'] = {'job_type': db.CT_JOB, 'main_volume': '20', 'count': 3}
    app.run()
    decoded = audit.decode_project(save_project(app), audit.namespace['deserialize_item'])
    assert decoded['ct_stage_config']['count'] == 3
    assert_replacement_guard(app)


@pytest.mark.parametrize('control', ['physics', 'placement', 'zone', 'auxiliary', 'custom'])
def test_real_centralizer_changes_are_significant_after_default_only_mount(control):
    app = CASE.app()
    CASE.phase(app, 'phase9')
    assert not dirty(app)
    if control == 'physics':
        app.radio(key='_centralizer_physics').set_value('dynamic').run()
    elif control == 'placement':
        app.radio(key='_centralizer_placement').set_value('direct').run()
    elif control == 'zone':
        app.button(key='_centralizer_add_zone').click().run()
    elif control == 'auxiliary':
        app.session_state['centralizer_config']['aux_rheology']['Pre Flush'] = {'300': 168.}
        app.run()
    else:
        from test_uat_round9f_phase9 import custom
        app.session_state['centralizer_config']['custom_products'] = [custom()]
        app.run()
    CASE.phase(app, 'phase1')
    assert_replacement_guard(app)


def test_saved_unfinished_active_sources_mount_only_verified_empty_defaults(downloads):
    app = CASE.app()
    CASE.phase(app, 'phase4')
    for fluid in ('Main', 'Pre Flush'):
        app.checkbox(key='chk_fluid_' + fluid).check().run()
    CASE.phase(app, 'phase1')
    offered = mark_saved(app, downloads)
    before = json.loads(offered['data'])
    for phase in ('phase2_3', 'phase5', 'phase6', 'phase7', 'phase10', 'phase9', 'phase1'):
        CASE.phase(app, phase)
        assert not dirty(app), phase
        after = json.loads(save_project(app))
        assert {key: after[key] for key in before} == before
    assert app.session_state['_saved_sig'] == hashlib.md5(offered['data'].encode()).hexdigest()
    CASE.phase(app, 'phase5')
    next(w for w in app.number_input if w.label == 'Dead Vol (bbl) - Main').set_value(0.)
    CASE.phase(app, 'phase1')
    assert app.session_state['cement_params']['Main']['dead_vol'] == 0.
    assert_replacement_guard(app)


@pytest.mark.parametrize('old,new', [(0, False), (False, 0), (None, {}), ({}, '')])
def test_saved_unknown_fields_preserve_explicit_value_distinctions(downloads, old, new):
    app = CASE.app({'future_operator_draft': old})
    mark_saved(app, downloads)
    assert not dirty(app)
    app.session_state['future_operator_draft'] = new
    app.run()
    assert_replacement_guard(app)


def test_report_manual_text_and_history_remain_significant_after_auto_mount(downloads):
    app = CASE.app()
    mark_saved(app, downloads)
    CASE.phase(app, 'phase10')
    assert not dirty(app)
    text = next(w for w in app.text_area if 'Execution Instructions' in w.label)
    text.set_value(text.value + '\nOperator field instruction.')
    CASE.phase(app, 'phase1')
    assert 'Operator field instruction.' in app.session_state['procedure_text']
    assert_replacement_guard(app)


@pytest.mark.parametrize('manual', ['none', 'lab_lot', 'lab_mass', 'lab_reading'])
def test_valid_main_navigation_recognizes_only_exact_automatic_lab_initialization(downloads, manual):
    app = CASE.app()
    CASE.phase(app, 'phase4')
    app.checkbox(key='chk_fluid_Main').check().run()
    app.number_input(key='vol_Main').set_value(10.).run()
    app.text_input(key='den_Main').set_value('118').run()
    app.text_input(key='rate_Main').set_value('4').run()
    mark_saved(app, downloads)
    for phase in ('phase2_3', 'phase5', 'phase6', 'phase7', 'phase10', 'phase1'):
        CASE.phase(app, phase)
        assert not dirty(app), phase
    if manual == 'lab_lot':
        app.session_state['lab_grid_dfs']['Main'].loc[0, 'Lot No'] = 'Operator lot 14'
    elif manual == 'lab_mass':
        app.session_state['lab_grid_dfs']['Main'].loc[0, 'Mass'] = '777.8'
    elif manual == 'lab_reading':
        CASE.phase(app, 'phase7')
        next(w for w in app.checkbox if w.label == 'BHCT — Ramp-Down - Main').check().run()
        next(w for w in app.text_input if w.label == '300 RPM - BHCT — Ramp-Down - Main').set_value('169')
        CASE.phase(app, 'phase1')
    else:
        with upload(app, INCOMING):
            app.run()
            assert app.session_state['well_name'] == 'Batch D incoming'
        return
    app.run()
    assert_replacement_guard(app)


def test_legacy_explicit_blank_pressure_preserves_manual_provenance_without_false_dirty():
    app = CASE.app()
    with upload(app, b'{"well_name":"Legacy manual pressure","bhsp":""}'):
        app.run()
        assert not dirty(app)
        CASE.phase(app, 'phase2_3')
        assert app.session_state['well_auto_fields']['bhsp'] is False
        assert not dirty(app)
        app.text_input(key='_w_bhsp').set_value('0')
        CASE.phase(app, 'phase1')
        assert app.session_state['bhsp'] == '0'
        assert dirty(app)
    assert_replacement_guard(app)


def test_preflush_legacy_measurement_migration_is_clean_but_real_reading_edit_is_dirty(downloads):
    import phase_9_centralizer as p9
    from test_uat_round10a_pumping_simulation import program_state
    state = program_state(fluids={'Pre Flush': 10., 'Displacement Fluid': 10.})
    aux = deepcopy(state['centralizer_config']['aux_rheology'])
    state['centralizer_config'] = {**p9.new_config(), 'aux_rheology': aux}
    app = CASE.app(state)
    mark_saved(app, downloads)
    assert not dirty(app)
    CASE.phase(app, 'phase7')
    assert 'Pre Flush' in app.session_state['lab_qc_params']
    assert not dirty(app)
    next(w for w in app.text_input if w.label == '300 RPM - BHCT — Ramp-Down - Pre Flush').set_value('169')
    CASE.phase(app, 'phase1')
    assert app.session_state['centralizer_config']['aux_rheology'] == aux
    assert_replacement_guard(app)


def test_unknown_pending_checkpoint_requires_explicit_receipt_before_becoming_clean(downloads):
    app = CASE.app()
    app.session_state['_baseline_loaded_project'] = True
    app.session_state['synthetic_unserializable'] = float('inf')
    app.run()
    assert dirty(app) and app.session_state['_baseline_loaded_project'] is True
    del app.session_state['synthetic_unserializable']
    app.run()
    assert dirty(app) and app.session_state['_baseline_loaded_project'] is True
    assert '_saved_sig' not in app.session_state
    mark_saved(app, downloads)
    # Native callback completed the pending checkpoint deliberately.
    assert '_baseline_loaded_project' not in app.session_state
    app.run()
    assert not dirty(app)


def test_saved_date_changes_are_real_edits_and_comparison_is_calendar_independent(downloads):
    from datetime import date
    app = CASE.app()
    mark_saved(app, downloads)
    receipt = app.session_state['_saved_sig']
    app.date_input(key='_w_report_date').set_value(date(2025, 1, 2))
    CASE.phase(app, 'phase2_3')
    assert app.session_state['report_date'] == date(2025, 1, 2)
    assert app.session_state['_saved_sig'] == receipt
    assert_replacement_guard(app)
    import ast
    from types import SimpleNamespace
    namespace = {**audit.namespace, 'json': json, 'hashlib': hashlib,
                 'materials_db': audit.materials_db}
    from project_state import WELL_DATA_DEFAULTS
    from placement import EXCESS_FIELDS
    namespace.update(WELL_DATA_DEFAULTS=WELL_DATA_DEFAULTS, EXCESS_FIELDS=EXCESS_FIELDS)
    node = next(n for n in audit.tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_project_comparison_signature')
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), namespace)
    raw = json.dumps({'report_date': {'__type__': 'Date', 'val': '2025-01-02'}})
    before = namespace['_project_comparison_signature'](raw)
    namespace['date'] = SimpleNamespace(today=lambda: date(2027, 12, 31))
    assert namespace['_project_comparison_signature'](raw) == before


def test_explicit_lab_source_acknowledgment_is_not_an_initialization_default(downloads):
    app = CASE.app()
    CASE.phase(app, 'phase4')
    app.checkbox(key='chk_fluid_Main').check().run()
    app.number_input(key='vol_Main').set_value(10.).run()
    app.text_input(key='den_Main').set_value('118').run()
    app.text_input(key='rate_Main').set_value('4').run()
    CASE.phase(app, 'phase5')
    CASE.phase(app, 'phase7')
    app.session_state['lab_qc_params']['Main']['reviewed'] = False
    app.session_state['lab_source_signatures'].pop('Main')
    CASE.phase(app, 'phase1')
    mark_saved(app, downloads)
    assert not dirty(app)
    readings = deepcopy(app.session_state['lab_qc_params']['Main'])
    grid = app.session_state['lab_grid_dfs']['Main'].copy(deep=True)
    CASE.phase(app, 'phase7')
    next(b for b in app.button if b.label == 'Keep reviewed lab entries').click().run()
    assert app.session_state['lab_qc_params']['Main'] == readings
    assert app.session_state['lab_grid_dfs']['Main'].equals(grid)
    assert app.session_state['lab_source_signatures']['Main']
    CASE.phase(app, 'phase1')
    assert_replacement_guard(app)


@pytest.mark.parametrize('job', ['LNR 7"', 'TIE BACK LNR 7"', 'CMT PLUG', 'CMT PLUG WITH CT'])
def test_flat_legacy_job_only_checkpoint_keeps_initialized_metadata_clean(job):
    app = CASE.app()
    raw = json.dumps({'job_type': job}).encode()
    with upload(app, raw):
        app.run()
        CASE.healthy(app)
        assert app.session_state['job_type'] == job
        assert not dirty(app)
    with upload(app, INCOMING):
        app.run()
        assert app.session_state['well_name'] == 'Batch D incoming'
        assert not any(b.key == '_confirm_upload_replacement' for b in app.button)
