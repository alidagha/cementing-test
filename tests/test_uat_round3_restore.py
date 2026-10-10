"""Round 3 Batch 1A: restored well drafts survive Mud Weight correction."""
import json
import unittest

import pandas as pd
import test_audit_regressions as audit
from project_io import content_signature, decode_project, replace_project_state
from project_state import is_project_key
from placement import hardware_choices, HOST_DESCRIPTIONS
from streamlit.testing.v1 import AppTest


class RestoredWellUAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy

    def project(self, job=audit.BATCH1_JOBS[0], gradient_auto=True, bhsp_auto=True):
        columns = ["Description", "MD (m)", "Size (in)", "ID (in)", "Joint (m)",
                   "Weight (ppf)", "Grade", "Collapse (psi)", "Burst (psi)"]
        well = {"geo_md": 3500., "geo_tvd": 3000., "bhst": 200 if gradient_auto else 80.+1.7*(3000.*3.28084/100.),
                "geo_gradient": ((200-80)/(3000*3.28084))*100 if gradient_auto else 1.7,
                "bhsp": "" if bhsp_auto else "7000+500", "mud_density": "-80-82",
                "mud_type": "OBM", "plastic_viscosity": "45-50", "yield_point": "15-20"}
        project = {**audit.well_profile_fixture(3500.,3000., gradient=None if gradient_auto else 1.7), "job_type": job, **well, "well_data": well.copy(),
                "well_auto_fields": {"bhsp": bhsp_auto},
                "hardware_table": pd.DataFrame([["Previous Casing", "3000", "20", 18.,
                    12.2, 100., "K-55", 1000., 2000.]], columns=columns),
                "placement_config": {"job_type": job, "target_row": "__manual__",
                    "manual_depth_m": 3000., "excess_csg_oh_pct": 25.,
                    "excess_csg_csg_pct": 10.5}}
        if "TIE BACK" in job:
            project["placement_config"]["host_row"] = next(iter(hardware_choices(project["hardware_table"], HOST_DESCRIPTIONS)))
        return project

    def restore(self, project):
        # Exercise the current decoder and the same replacement used by the uploader.
        raw = json.dumps({k: audit.namespace["serialize_item"](v)
                          for k, v in project.items() if is_project_key(k)}, allow_nan=False).encode()
        restored = AppTest.from_file(str(audit.ROOT / "main.py"), default_timeout=30)
        replace_project_state(restored.session_state, decode_project(raw, audit.namespace["deserialize_item"]),
                              content_signature(raw))
        restored.run()
        self.healthy(restored)
        self.phase(restored, "phase2_3")
        return restored

    def preserved(self, app, original):
        for field in ("geo_md", "geo_tvd", "bhst", "mud_type", "plastic_viscosity", "yield_point"):
            self.assertEqual(app.session_state[field], original[field])
            self.assertEqual(app.session_state["well_data"][field], original[field])
        self.assertEqual(app.session_state["placement_config"], original["placement_config"])
        pd.testing.assert_frame_equal(app.session_state["hardware_table"], original["hardware_table"])
        for field in ("geo_md", "geo_tvd", "bhst"):
            self.assertEqual(app.session_state[field], original[field])

    def test_correction_rerun_delivers_restored_sources_to_browser_remount(self):
        project = self.project()
        app = self.restore(project)
        app.text_input(key="_w_mud_density").set_value("80-82").run()
        self.preserved(app, project)
        # A nullable control remount must receive its committed value, not a
        # blank constructor default. AppTest otherwise reads server state and
        # misses the browser's null callback observed on a correction rerun.
        proto = app.number_input(key="_w_geothermal_bhst").proto
        visible = proto.value if proto.set_value and proto.HasField("value") else (
            proto.default if proto.HasField("default") else None)
        self.assertEqual(visible, app.session_state["bhst"])
        self.assertEqual(app.session_state["well_geometry"]["survey"].iloc[-1]["MD"], 3500.)

    def test_automatic_correction_navigation_and_fresh_current_restore_for_five_jobs(self):
        for job in audit.BATCH1_JOBS:
            with self.subTest(job=job):
                project = self.project(job)
                app = self.restore(project)
                self.assertEqual(app.text_input(key="_w_mud_density").value, "-80-82")
                self.assertEqual(app.session_state["bhsp"], "")
                self.preserved(app, project)
                for mud, basis in (("80-82", 82.), ("-80-82", None), ("80/84", 84.)):
                    app.text_input(key="_w_mud_density").set_value(mud).run()
                    app.run()
                    self.preserved(app, project)
                    self.assertAlmostEqual(app.session_state["geo_gradient"], project["geo_gradient"])
                    if basis is None:
                        self.assertEqual(app.session_state["bhsp"], "")
                    else:
                        self.assertAlmostEqual(float(app.session_state["bhsp"]), 3000*basis*.02278)
                        self.assertEqual(app.session_state["effective_mud_density"], 81. if basis == 82. else 82.)
                self.phase(app, "phase4")
                self.phase(app, "phase2_3")
                self.preserved(app, project)
                restored = self.restore(app.session_state.to_dict())
                self.preserved(restored, project)
                self.assertEqual(restored.session_state["well_auto_fields"], {"bhsp": True})
                self.assertAlmostEqual(float(restored.session_state["bhsp"]), 3000*84*.02278)

    def test_manual_derived_values_remain_manual_through_correction_navigation_restore(self):
        for gradient_auto, bhsp_auto in ((False, True), (True, False), (False, False)):
            with self.subTest(gradient_auto=gradient_auto, bhsp_auto=bhsp_auto):
                project = self.project(gradient_auto=gradient_auto, bhsp_auto=bhsp_auto)
                app = self.restore(project)
                app.text_input(key="_w_mud_density").set_value("80-82")
                self.phase(app, "phase1")
                self.phase(app, "phase2_3")
                app.text_input(key="_w_mud_density").set_value("90-92").run()
                restored = self.restore(app.session_state.to_dict())
                self.preserved(restored, project)
                self.assertEqual(restored.session_state["well_auto_fields"], project["well_auto_fields"])
                self.assertEqual(restored.session_state["geo_gradient"], project["geo_gradient"])
                self.assertEqual(restored.session_state["bhsp"], str(3000*92*.02278) if bhsp_auto else "7000+500")

    def test_real_source_edits_and_explicit_clears_are_not_replaced_by_reseeding(self):
        app = self.restore(self.project())
        app.selectbox(key="_w_geometry_type").set_value("Vertical").run()
        app.number_input(key="_w_vertical_td").set_value(4000.)
        self.phase(app, "phase1")
        self.phase(app, "phase2_3")
        self.assertEqual(app.number_input(key="_w_vertical_td").value, 4000.)
        app.number_input(key="_w_geothermal_bhst").set_value(None).run()
        self.phase(app, "phase1")
        self.phase(app, "phase2_3")
        self.assertIsNone(app.number_input(key="_w_geothermal_bhst").value)
        restored = self.restore(app.session_state.to_dict())
        self.assertIsNone(restored.session_state["bhst"])
        self.assertIsNone(restored.session_state["geo_gradient"])
        app.number_input(key="_w_vertical_td").set_value(None).run()
        self.assertIsNone(app.session_state["geo_tvd"])
        self.assertEqual(app.session_state["bhsp"], "")


if __name__ == "__main__":
    unittest.main()
