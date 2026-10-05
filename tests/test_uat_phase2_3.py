"""Manual UAT Round 1: blank well inputs, hardware defaults and derived values."""
import json
import unittest
from unittest.mock import patch

import pandas as pd
import test_audit_regressions as audit
from engineering_tools import compute_phase_status
from phase_2_3_well_data import HARDWARE_COLUMNS
from project_io import decode_project


class Phase23UAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    healthy = audit.AuditRegressions.healthy
    phase = audit.AuditRegressions.phase
    hardware_event = audit.AuditRegressions.hardware_event

    def test_blank_defaults_draft_restore_and_navigation(self):
        app = self.app()
        self.phase(app, "phase2_3")
        for field in ("mud_density", "plastic_viscosity", "yield_point", "bhsp"):
            self.assertEqual(app.text_input(key="_w_" + field).value, "")
        for field in ("geo_md", "geo_tvd", "bhst", "geo_gradient"):
            self.assertIsNone(app.number_input(key="_w_" + field).value)
        for field in ("effective_mud_density", "effective_pv", "effective_yp"):
            self.assertIsNone(app.session_state[field])
        saved = audit.round_trip(app.session_state.to_dict())
        restored = self.app(saved)
        for phase in ("phase10", "phase2_3"):
            self.phase(restored, phase)
        self.assertIsNone(restored.number_input(key="_w_geo_tvd").value)
        self.assertFalse(any("saved or calculated" in e.value for e in restored.error))
        self.assertNotEqual(compute_phase_status(restored.session_state)["phase2_3"]["level"], "ok")

    def test_first_entries_autocalculate_from_tvd_and_follow_sources(self):
        app = self.app()
        self.phase(app, "phase2_3")
        for field, value in (("geo_md", 3500.0), ("geo_tvd", 3000.0), ("bhst", 200)):
            app.number_input(key="_w_" + field).set_value(value)
            self.phase(app, "phase1")
            self.phase(app, "phase2_3")
            self.assertEqual(app.number_input(key="_w_" + field).value, value)
        app.text_input(key="_w_mud_density").set_value("80-82")
        self.phase(app, "phase1")
        self.phase(app, "phase2_3")
        self.assertAlmostEqual(app.number_input(key="_w_geo_gradient").value, ((200-80)/(3000*3.28084))*100)
        self.assertAlmostEqual(float(app.text_input(key="_w_bhsp").value), 3000*82*0.02278)
        app.number_input(key="_w_geo_tvd").set_value(2500.0).run()
        self.assertAlmostEqual(app.session_state["geo_gradient"], ((200-80)/(2500*3.28084))*100)
        self.assertAlmostEqual(float(app.session_state["bhsp"]), 2500*82*0.02278)
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, "phase2_3")
        restored.number_input(key="_w_bhst").set_value(180).run()
        self.assertAlmostEqual(restored.session_state["geo_gradient"], ((180-80)/(2500*3.28084))*100)
        restored.number_input(key="_w_geo_tvd").set_value(None).run()
        self.assertIsNone(restored.session_state["geo_gradient"])
        self.assertEqual(restored.session_state["bhsp"], "")

    def test_manual_overrides_survive_first_edit_navigation_and_restore(self):
        app = self.app({"geo_md": 3500.0, "geo_tvd": 3000.0, "bhst": 200, "mud_density": "81"})
        self.phase(app, "phase2_3")
        app.number_input(key="_w_geo_gradient").set_value(1.7)
        app.text_input(key="_w_bhsp").set_value("7300+1000")
        app.text_input(key="_w_plastic_viscosity").set_value("45-50")
        app.text_input(key="_w_yield_point").set_value("15")
        self.phase(app, "phase1")
        self.phase(app, "phase2_3")
        app.number_input(key="_w_geo_tvd").set_value(2500.0).run()
        app.number_input(key="_w_bhst").set_value(180).run()
        app.text_input(key="_w_mud_density").set_value("90").run()
        saved = audit.round_trip(app.session_state.to_dict())
        restored = self.app(saved)
        self.phase(restored, "phase2_3")
        for field, value in (("geo_gradient", 1.7), ("bhsp", "7300+1000"),
                             ("plastic_viscosity", "45-50"), ("yield_point", "15")):
            self.assertEqual(restored.session_state[field], value)
            self.assertEqual(restored.session_state["well_data"][field], value)
        restored.number_input(key="_w_geo_gradient").set_value(None).run()
        restored.text_input(key="_w_bhsp").set_value("").run()
        self.phase(restored, "phase1")
        self.phase(restored, "phase2_3")
        self.assertIsNone(restored.number_input(key="_w_geo_gradient").value)
        self.assertEqual(restored.text_input(key="_w_bhsp").value, "")

    def test_restored_explicit_values_take_precedence(self):
        well = {"geo_md": 3500.0, "geo_tvd": 3000.0, "bhst": 200, "mud_density": "90",
                "geo_gradient": 1.4, "bhsp": "6000+500"}
        for nested in (False, True):
            with self.subTest(nested=nested):
                app = self.app(audit.round_trip({"job_type": "CMT PLUG", **({"well_data": well.copy()} if nested else well)}))
                self.phase(app, "phase2_3")
                app.number_input(key="_w_geo_tvd").set_value(2500.0).run()
                self.assertEqual(app.number_input(key="_w_geo_gradient").value, 1.4)
                self.assertEqual(app.text_input(key="_w_bhsp").value, "6000+500")

    def test_hardware_native_defaults_and_joint_override(self):
        import phase_2_3_well_data as phase23
        with patch.object(phase23, "persistent_data_editor", wraps=phase23.persistent_data_editor) as editor:
            app = self.app()
            self.phase(app, "phase2_3")
            self.assertEqual(editor.call_args.kwargs["num_rows"], "dynamic")
            self.assertEqual(editor.call_args.kwargs["column_config"]["Joint (m)"]["default"], 12.2)
            self.assertFalse(any("Add Row" in b.label or "Delete Row" in b.label for b in app.button))
            self.assertFalse(any("to delete" in w.label for w in app.number_input))
        row = {"Description": "Casing", "MD (m)": "3000", "Size (in)": "9.625", "ID (in)": 8.535,
               "Joint (m)": 12.2, "Weight (ppf)": 47., "Grade": "K-55", "Collapse (psi)": 1000., "Burst (psi)": 2000.}
        self.hardware_event(app, {"added_rows": [row]})
        self.healthy(app)
        self.hardware_event(app, {"added_rows": [{**row, "Joint (m)": 11.7}]}, navigate="phase1")
        self.phase(app, "phase2_3")
        self.assertEqual(app.session_state["hardware_table"].iloc[0]["Joint (m)"], 11.7)
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, "phase2_3")
        self.assertEqual(restored.session_state["hardware_table"].iloc[0]["Joint (m)"], 11.7)
        self.hardware_event(restored, {"deleted_rows": [0]})
        self.assertTrue(restored.session_state["hardware_table"].empty)

    def test_open_hole_numeric_semantics_remain_intact(self):
        row = ["Open Hole Size", "3000", "12.25", 12.25, 12.2, 30., "L-80", 100., 200.]
        app = self.app({"hardware_table": pd.DataFrame([row], columns=HARDWARE_COLUMNS)})
        self.phase(app, "phase2_3")
        saved = audit.round_trip(app.session_state.to_dict())
        for field in ("Joint (m)", "Weight (ppf)", "Collapse (psi)", "Burst (psi)"):
            self.assertEqual(saved["hardware_table"].iloc[0][field], 0.0)
        self.assertEqual(saved["hardware_table"].iloc[0]["Grade"], "-")

    def test_blank_required_fields_block_status_and_export_for_all_jobs(self):
        case = audit.AuditRegressions()
        for job in audit.BATCH1_JOBS:
            app = case.configured_app(job)
            case.export(app)
            valid = app.session_state.to_dict()
            for field, phase in (("geo_md", "phase2_3"), ("geo_tvd", "phase2_3"),
                                 ("mud_density", "phase4"), ("bhst", "phase7")):
                with self.subTest(job=job, field=field):
                    project = audit.round_trip(valid)
                    project[field] = None if field in ("geo_md", "geo_tvd", "bhst", "geo_gradient") else ""
                    project["well_data"][field] = project[field]
                    project["well_auto_fields"] = {"geo_gradient": False, "bhsp": False}
                    restored = self.app(project)
                    self.phase(restored, phase)
                    self.assertNotEqual(compute_phase_status(restored.session_state)[phase]["level"], "ok")
                    case.assert_export_blocked(restored)

    def test_incomplete_numeric_drafts_still_reject_malformed_json(self):
        for value in ("invalid", True, "", "NaN"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    decode_project(json.dumps({"well_data": {"geo_tvd": value}}).encode(), audit.namespace["deserialize_item"])
        for provenance in ([], {"geo_gradient": "auto"}, {"unknown": True}):
            with self.subTest(provenance=provenance):
                with self.assertRaises(ValueError):
                    decode_project(json.dumps({"job_type": "CMT PLUG", "well_auto_fields": provenance}).encode(),
                                   audit.namespace["deserialize_item"])
        self.assertIsNone(audit.round_trip({"job_type": "CMT PLUG", "geo_tvd": None})["geo_tvd"])
