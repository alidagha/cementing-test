"""Round 3 Batch 1: upper mud range for automatic BHSP; lower pump rate."""
from io import BytesIO
import unittest
from docx import Document
import materials_db
import engineering_tools as engineering
import test_audit_regressions as audit
from project_state import refresh_well_derived, refresh_fluids


class Round3WellUAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy

    def test_automatic_bhsp_uses_upper_density_and_tvd_without_changing_gradient(self):
        for mud, basis in (('80-82',82.),('80/82',82.),('81',81.),('82/80/79.5',82.)):
            for md in (3500.,4000.):
                with self.subTest(mud=mud, md=md):
                    state={'geo_md':md,'geo_tvd':3000.,'bhst':200,'mud_density':mud,
                           'well_auto_fields':{'bhsp':True,'geo_gradient':True},'well_data':{}}
                    refresh_well_derived(state)
                    self.assertAlmostEqual(float(state['bhsp']),3000*basis*.02278)
                    self.assertEqual(state['well_data']['bhsp'],state['bhsp'])
                    self.assertAlmostEqual(state['geo_gradient'],((200-80)/(3000*3.28084))*100)

    def test_strict_shared_density_components_reject_invalid_bhsp_sources(self):
        for raw in ('-80','-80-82','0','0-82','abc','NaN','Infinity','80--82','80/','/82',
                    '80abc82','80 82','80-NaN',None,True,float('inf'),float('nan'),'9'*400):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):engineering.require_positive_density(raw)
                with self.assertRaises(ValueError):engineering.require_bhsp_density(raw)
                state={'geo_tvd':3000.,'mud_density':raw,'bhsp':'stale',
                       'well_auto_fields':{'bhsp':True},'well_data':{'bhsp':'stale'}}
                refresh_well_derived(state)
                self.assertEqual(state['bhsp'],'')
                self.assertEqual(state['well_data']['bhsp'],'')

    def test_general_mean_and_digit_semantics_unchanged(self):
        for raw,mean,upper in (('80-82',81.,82.),('80/82',81.,82.),('81',81.,81.),
                              ('۸۰-۸۲',81.,82.),('٨٠/٨٢',81.,82.),('80-82/84',82.,84.),
                              (' 82.5 / 80.5 ',81.5,82.5)):
            with self.subTest(raw=raw):
                self.assertEqual(engineering.parse_effective_numeric(raw),mean)
                self.assertEqual(engineering.require_positive_density(raw),mean)
                self.assertEqual(engineering.require_bhsp_density(raw),upper)
        self.assertEqual(engineering.parse_effective_numeric('-118'),-118.)
        self.assertEqual(engineering.require_positive_pump_rate('3.5-5.0'),3.5)

    def test_first_edit_navigation_current_restore_and_manual_provenance(self):
        app=self.app();self.phase(app,'phase2_3')
        for field,value in (('geo_md',3500.),('geo_tvd',3000.),('bhst',200)):
            app.number_input(key='_w_'+field).set_value(value).run()
        app.text_input(key='_w_mud_density').set_value('80-82')
        self.phase(app,'phase1');self.phase(app,'phase2_3')
        self.assertEqual(app.text_input(key='_w_mud_density').value,'80-82')
        self.assertEqual(app.session_state['effective_mud_density'],81.)
        self.assertAlmostEqual(float(app.session_state['bhsp']),5603.88)
        restored=self.app(audit.round_trip(app.session_state.to_dict()));self.phase(restored,'phase2_3')
        self.assertTrue(restored.session_state['well_auto_fields']['bhsp'])
        self.assertAlmostEqual(float(restored.session_state['bhsp']),5603.88)
        restored.text_input(key='_w_bhsp').set_value('7000+500')
        self.phase(restored,'phase1');self.phase(restored,'phase2_3')
        manual=self.app(audit.round_trip(restored.session_state.to_dict()));self.phase(manual,'phase2_3')
        for field,value in (('geo_md',4000.),('geo_tvd',2800.)):
            manual.number_input(key='_w_'+field).set_value(value).run()
        manual.text_input(key='_w_mud_density').set_value('90-92').run()
        manual.run();self.phase(manual,'phase1');self.phase(manual,'phase2_3')
        self.assertFalse(manual.session_state['well_auto_fields']['bhsp'])
        self.assertEqual(manual.session_state['bhsp'],'7000+500')
        self.assertEqual(manual.session_state['well_data']['bhsp'],'7000+500')

    def test_caption_distinguishes_valid_range_and_omits_invalid_upper_basis(self):
        app=self.app({'geo_md':3500.,'geo_tvd':3000.,'bhst':200});self.phase(app,'phase2_3')
        for raw in ('80-82','80/82'):
            app.text_input(key='_w_mud_density').set_value(raw).run()
            text='\n'.join(c.value for c in app.caption)
            self.assertIn('General effective density: **81.0 pcf** (mean of range)',text)
            self.assertIn('BHSP density basis: **82.0 pcf** (upper end of range)',text)
        for raw in ('81','-80-82','0-82','80--82'):
            app.text_input(key='_w_mud_density').set_value(raw).run()
            self.assertFalse(any('BHSP density basis' in c.value for c in app.caption))
        app.text_input(key='_w_mud_density').set_value('80-82').run()
        for field,value in (('geo_md',3500.),('geo_tvd',3000.),('bhst',200)):
            self.assertEqual(app.number_input(key='_w_'+field).value,value)
        self.assertAlmostEqual(float(app.session_state['bhsp']),5603.88)

    def test_every_fluid_rate_minimum_and_cumulative_reconstruction(self):
        fluids=list(materials_db.FLUID_TYPES)
        state={'mud_density':'80-82','fluids_config':{'active':fluids,'params':{
            s:{'volume':30.,'density':'80-82','pump_rate':'3-5'} for s in fluids}}}
        refresh_fluids(state)
        self.assertEqual(list(state['fluid_data']),fluids)
        for i,s in enumerate(fluids):
            with self.subTest(fluid=s):
                record=state['fluid_data'][s]
                self.assertEqual(record['min_rate'],3.)
                self.assertEqual(record['duration_min'],10.)
                self.assertEqual(record['cumul_time_min'],10.*(i+1))
                self.assertEqual(record['effective_density'],81.)
        self.assertEqual(state['total_pump_time_min'],10.*len(fluids))

    def test_runtime_rate_minimum_representative_sequence_and_density_mean(self):
        fluids=['Pre Flush','Spacer','Main','Displacement Fluid']
        app=self.app({'mud_density':'80-82','effective_mud_density':81.,'fluids_config':{
            'active':fluids,'params':{s:{'volume':30.,'density':'80-82','pump_rate':'3-5'} for s in fluids}}})
        self.phase(app,'phase4')
        for i,s in enumerate(fluids):
            with self.subTest(fluid=s):
                record=app.session_state['fluid_data'][s]
                self.assertEqual(record['min_rate'],3.)
                self.assertEqual(record['duration_min'],10.)
                self.assertEqual(record['cumul_time_min'],10.*(i+1))
                self.assertEqual(record['effective_density'],81.)

    def test_normal_review_and_actual_word_use_corrected_bhsp_for_five_jobs(self):
        case=audit.AuditRegressions()
        for job in audit.BATCH1_JOBS:
            with self.subTest(job=job):
                app=case.configured_app(job);self.phase(app,'phase2_3')
                self.assertTrue(app.session_state['well_auto_fields']['bhsp'])
                app.number_input(key='_w_geo_md').set_value(3500.).run()
                app.text_input(key='_w_mud_density').set_value('80-82').run()
                self.assertAlmostEqual(float(app.session_state['bhsp']),5603.88)
                self.phase(app,'phase4');self.phase(app,'phase7')
                self.assertTrue(any('Formulation Drift' in w.value for w in app.warning))
                next(b for b in app.button if b.label=='Sync with Phase V').click().run()
                next(b for b in app.button if b.label=='Confirm measured lab results').click().run()
                case.export(app)
                self.assertAlmostEqual(float(app.session_state['lab_payload_Main']['bhsp']),5603.88)
                doc=Document(BytesIO(app.session_state['_compiled_doc_bytes']))
                table=next(t for t in doc.tables if t.rows[0].cells[0].text=='Thickening Time Test')
                self.assertAlmostEqual(float(table.rows[3].cells[1].text),5603.88)
                self.assertEqual(table.rows[2].cells[-1].text,'70 Bc\nhr:mm')
                self.assertEqual(table.rows[3].cells[-1].text,'03:30')


if __name__=='__main__':unittest.main()
