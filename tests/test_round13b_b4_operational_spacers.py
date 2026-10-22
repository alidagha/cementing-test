"""All fifteen jobs use Ahead/Behind as Phase-IV operational fluids."""
from copy import deepcopy
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile
import pickle
import pandas as pd
import pytest
from docxtpl import DocxTemplate
import materials_db as db
import engineering_tools as eng
import project_state as ps
import phase_10_procedure as report
import test_audit_regressions as audit
from test_round13b_b3_ct_schematic import state as ct_state

CASE=audit.AuditRegressions()


def operational(job):
    s=ct_state()
    if job!=db.CT_JOB:
        s.update(job_type=job,**audit.valid_export_chart_fixture(job))
        s['cement_params']['Main']['top_job_type']=job
        s['cement_params']['Main']['top_depth']=2000.
    cfg=s['fluids_config'];cfg['active']=['Spacer Ahead','Main','Spacer Behind','Displacement Fluid']
    for name,volume in [('Spacer Ahead',7.),('Spacer Behind',3.)]:
        cfg['params'][name]={'volume':volume,'density':'80','pump_rate':'0.7-1.2','material_name':name+' operational material'}
    ps.refresh_fluids(s)
    return s


@pytest.mark.parametrize('job',db.JOB_TYPES)
def test_all_jobs_operational_ahead_behind_need_no_chemical_rows(job):
    s=operational(job)
    status=eng.compute_phase_status(s)['phase6']
    assert status['level']!='warning',status


@pytest.mark.parametrize('job',['CMT PLUG',db.CT_JOB])
def test_phase6_does_not_mount_ahead_behind_chemical_editors(job):
    app=CASE.app(operational(job));CASE.phase(app,'phase6')
    editors=[x.proto.id for x in app.dataframe if '_editor_spacer_' in x.proto.id]
    assert editors==[],editors


def test_phase4_preserves_inactive_historical_ahead_behind_drafts():
    s=ct_state();s['spacer_dfs']={name:pd.DataFrame([{'Chemical':'Hematite','User Input (% or gal)':5.,'Weighting Agent Type':'Hematite'}]) for name in ['Spacer Ahead','Spacer Behind']}
    s['spacer_initialized_names']=['Spacer Ahead','Spacer Behind']
    before=pickle.dumps(s['spacer_dfs'])
    app=CASE.app(s);CASE.phase(app,'phase4')
    assert pickle.dumps(app.session_state['spacer_dfs'])==before


@pytest.fixture(scope='module')
def existing_guard_context():
    import test_regression_guardrails as guard
    with patch.object(report.st,'session_state',{}):
        state=guard._seed_session()
        ctx=report.build_master_context(calculations_prepared=True)
        return deepcopy(state),ctx


def test_historical_behind_chemical_is_absent_from_active_report_context(existing_guard_context):
    state,ctx=existing_guard_context
    assert state['spacer_dfs']['Spacer Behind'].iloc[0]['Chemical']=='Hematite'
    assert not any(r.get('Name')=='Hematite' for r in ctx.get('spacers',[])),ctx['spacers']


def test_existing_template_already_hides_sibling_chemical_tables(existing_guard_context):
    _,ctx=existing_guard_context
    template=DocxTemplate('master_template.docx');template.render(ctx)
    out=BytesIO();template.save(out)
    with ZipFile(BytesIO(out.getvalue())) as z:xml=z.read('word/document.xml').decode()
    assert 'Hematite' not in xml
    assert 'Spacer Formulation Data' not in xml and 'Spacer Additives Data' not in xml
    assert 'Spacer Behind' in xml and 'Pre Flush Data' in xml

@pytest.mark.parametrize('fluid',['Spacer Ahead','Spacer Behind'])
@pytest.mark.parametrize('value',['', '   ', None])
def test_active_operational_spacer_requires_actual_phase_iv_name(fluid,value):
    s=operational('CMT PLUG');s['fluids_config']['params'][fluid]['material_name']=value
    with pytest.raises(ValueError,match='material name'):
        ps.refresh_fluids(s)
    assert eng.compute_phase_status(s)['phase4']['level']!='ok'

@pytest.mark.parametrize('fluid',['Spacer Ahead','Spacer Behind'])
def test_missing_operational_name_remains_unfinished_until_real_ui_edit(fluid):
    s=operational('CMT PLUG');s['fluids_config']['params'][fluid]['material_name']=None
    app=CASE.app(s);CASE.phase(app,'phase4')
    assert eng.compute_phase_status(app.session_state)['phase4']['level']=='warning'
    app.text_input(key='matname_'+fluid).set_value('Actual field & material').run()
    assert eng.compute_phase_status(app.session_state)['phase4']['level']=='ok'

@pytest.mark.parametrize('fluid',['Spacer Ahead','Spacer Behind'])
def test_operational_material_keeps_existing_catalog_default_if_unentered(fluid):
    s=operational('CMT PLUG');s['fluids_config']['params'][fluid].pop('material_name')
    s['fluid_data'].pop(fluid)
    app=CASE.app(s);CASE.phase(app,'phase4')
    assert app.text_input(key='matname_'+fluid).value==db.DEFAULT_MATERIAL_NAMES[fluid]
    assert eng.compute_phase_status(app.session_state)['phase4']['level']=='ok'
