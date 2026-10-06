"""Manual UAT Round 1: measured BHCT, collection angles and surface hardening."""
from copy import deepcopy
from io import BytesIO
import re
import unittest
from unittest.mock import patch

from docx import Document
import test_audit_regressions as audit
from engineering_tools import (compute_phase_status, lab_review_signature,
                               validate_lab_collection_results)
from bhct_helper import suggest_bhct, M_TO_FT
import phase_10_procedure as report


class Phase7UAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export
    assert_export_blocked = audit.AuditRegressions.assert_export_blocked

    def input(self, app, label):
        return next(w for w in app.number_input if w.label == label)

    def lab(self, slurries=("Main",), qc=None, tvd=100.0, bhst=200):
        app = self.app({"geo_md": tvd, "geo_tvd": tvd, "bhst": bhst,
                        "fluids_config": {"active": list(slurries), "params": {
                            s: {"volume": 50.0, "density": "118", "pump_rate": "4"} for s in slurries}},
                        "lab_qc_params": qc or {}})
        self.phase(app, "phase4")
        self.phase(app, "phase7")
        return app

    def test_new_main_bhct_blank_other_archetypes_unchanged(self):
        app = self.lab(("Main", "Lead", "Lead #1", "Lead #2", "Tail"))
        self.assertIsNone(self.input(app, "BHCT (°F) - Main").value)
        for s in ("Lead", "Lead #1", "Lead #2", "Tail"):
            self.assertIsNone(self.input(app, "BHCT (°F) - " + s).value)
        self.phase(app, "phase1")
        self.phase(app, "phase7")
        self.assertIsNone(self.input(app, "BHCT (°F) - Main").value)
        self.assertNotEqual(compute_phase_status(app.session_state)["phase7"]["level"], "ok")
        self.assertTrue(next(b for b in app.button if b.label == "Confirm measured lab results").disabled)
        self.input(app, "BHCT (°F) - Lead").set_value(155).run()
        self.phase(app, "phase1")
        self.phase(app, "phase7")
        self.assertEqual(self.input(app, "BHCT (°F) - Lead").value, 155)

    def test_main_bhct_first_entry_clear_and_restore(self):
        app = self.lab()
        self.input(app, "BHCT (°F) - Main").set_value(140)
        self.phase(app, "phase1")
        self.phase(app, "phase7")
        self.assertEqual(self.input(app, "BHCT (°F) - Main").value, 140)
        saved = audit.round_trip(app.session_state.to_dict())
        restored = self.app(saved)
        self.phase(restored, "phase7")
        self.assertEqual(self.input(restored, "BHCT (°F) - Main").value, 140)
        self.input(restored, "BHCT (°F) - Main").set_value(None).run()
        self.phase(restored, "phase10")
        self.phase(restored, "phase7")
        self.assertIsNone(self.input(restored, "BHCT (°F) - Main").value)
        self.assertIsNone(audit.round_trip(restored.session_state.to_dict())["lab_qc_params"]["Main"]["bhct"])

    def test_legacy_main_150_and_90_angle_preserved(self):
        app = self.lab(qc={"Main": {"bhct": 150, "free_water": 1.5}})
        self.assertEqual(self.input(app, "BHCT (°F) - Main").value, 150)
        self.assertEqual(self.input(app, "Free Water Collected (90° angle) (ml) - Main").value, 1.5)
        self.assertIsNone(self.input(app, "Free Water Collected (45° angle) (ml) - Main").value)
        self.assertIsNone(self.input(app, "Surface Sample Hours - Main").value)
        self.phase(app, "phase10")
        self.phase(app, "phase7")
        saved = audit.round_trip(app.session_state.to_dict())["lab_qc_params"]["Main"]
        self.assertEqual(saved["bhct"], 150)
        self.assertEqual(saved["free_water"], 1.5)
        self.assertIsNone(saved["surface_hardened_hours"])
        self.assertNotEqual(compute_phase_status(app.session_state)["phase7"]["level"], "ok")

    def test_low_tvd_squeeze_is_not_bhct_guidance(self):
        for tvd in (100.0, 3000.0):
            with self.subTest(tvd=tvd):
                self.assertEqual(suggest_bhct(tvd * M_TO_FT, max_rbhest_f=200)["kind"], "SQUEEZE")
                app = self.lab(tvd=tvd)
                self.assertFalse(any("Suggested SQUEEZE" in c.value for c in app.caption))
                self.assertFalse(any(b.label.startswith("Apply ") and "°F" in b.label for b in app.button))
                self.assertIsNone(self.input(app, "BHCT (°F) - Main").value)

    def test_high_tvd_bhct_suggestion_only_applies_on_click(self):
        for tvd in (10000 / M_TO_FT, 3100.0):
            with self.subTest(tvd=tvd):
                app = self.lab(tvd=tvd)
                self.assertTrue(any("Suggested BHCT" in c.value for c in app.caption))
                self.assertIsNone(self.input(app, "BHCT (°F) - Main").value)
                self.input(app, "BHCT (°F) - Main").set_value(140).run()
                app.run()
                self.assertEqual(self.input(app, "BHCT (°F) - Main").value, 140)
                button = next(b for b in app.button if b.label.startswith("Apply ") and "°F" in b.label)
                button.click().run()
                expected = max(60, min(400, round(suggest_bhct(tvd * M_TO_FT, max_rbhest_f=200)["temp_degF"])))
                self.assertEqual(self.input(app, "BHCT (°F) - Main").value, expected)
                self.assertEqual(app.session_state["lab_qc_params"]["Main"]["bhct"], expected)

    def test_free_water_angles_first_edits_navigation_and_restore(self):
        app = self.lab()
        for angle, value in ((90, 1.5), (45, 2.5)):
            self.input(app, f"Free Water Collected ({angle}° angle) (ml) - Main").set_value(value)
            self.phase(app, "phase1")
            self.phase(app, "phase7")
            self.assertEqual(self.input(app, f"Free Water Collected ({angle}° angle) (ml) - Main").value, value)
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, "phase7")
        self.assertEqual(self.input(restored, "Free Water Collected (90° angle) (ml) - Main").value, 1.5)
        self.assertEqual(self.input(restored, "Free Water Collected (45° angle) (ml) - Main").value, 2.5)
        self.assertEqual(restored.session_state["lab_qc_params"]["Main"]["free_water"], 1.5)

    def test_surface_hours_independent_first_entry_and_restore(self):
        app = self.lab()
        self.assertIsNone(self.input(app, "Surface Sample Hours - Main").value)
        self.input(app, "Surface Sample Hours - Main").set_value(8.25)
        self.phase(app, "phase1")
        self.phase(app, "phase7")
        self.assertEqual(self.input(app, "Surface Sample Hours - Main").value, 8.25)
        tt = next(w for w in app.text_input if w.label == "Thickening Time (HH:MM) - Main")
        tt.set_value("03:30").run()  # Explicit measured setup, no implicit lab time.
        self.assertEqual(tt.value, "03:30")
        tt.set_value("04:45").run()
        self.assertEqual(self.input(app, "Surface Sample Hours - Main").value, 8.25)
        restored = self.app(audit.round_trip(app.session_state.to_dict()))
        self.phase(restored, "phase7")
        self.assertEqual(self.input(restored, "Surface Sample Hours - Main").value, 8.25)
        self.assertEqual(restored.session_state["lab_qc_params"]["Main"]["thickening_time"], "04:45")

    def test_collection_validation_finite_nonnegative_and_missing(self):
        good = {"free_water": 0.0, "free_water_45": 0.0, "surface_hardened_hours": 0.0}
        validate_lab_collection_results(good)
        for field in good:
            for bad in (None, -1, True, "bad", float("nan"), float("inf")):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(ValueError):
                        validate_lab_collection_results({**good, field: bad})

    def test_nullable_qc_drafts_restore_active_and_inactive(self):
        qc = {"bhct": None, "free_water": 1.5, "free_water_45": None, "surface_hardened_hours": None}
        for archived in (False, True):
            with self.subTest(archived=archived):
                project = ({"inactive_slurry_drafts": {"Main": {"lab_qc_params": qc}}} if archived
                           else {"lab_qc_params": {"Main": qc}})
                project["job_type"] = 'CSG 20"'
                project["material_property_schema"] = 1
                self.assertEqual(audit.round_trip(project), project)
        for field in ("bhct", "free_water_45", "surface_hardened_hours"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    audit.round_trip({"job_type": 'CSG 20"', "lab_qc_params": {"Main": {**qc, field: True}}})

    def test_qc_edits_invalidate_review_and_compiled_word(self):
        valid = self.configured_app(audit.BATCH1_JOBS[0])
        self.export(valid)
        saved = valid.session_state.to_dict()
        for field, label, value in (("free_water", "Free Water Collected (90° angle) (ml) - Main", 1.5),
                                    ("free_water_45", "Free Water Collected (45° angle) (ml) - Main", 2.5),
                                    ("surface_hardened_hours", "Surface Sample Hours - Main", 9.25)):
            with self.subTest(field=field):
                app = self.app(deepcopy(saved))
                self.phase(app, "phase7")
                self.input(app, label).set_value(value)
                self.phase(app, "phase1")
                qc = app.session_state["lab_qc_params"]["Main"]
                self.assertNotEqual(qc["review_signature"], lab_review_signature(qc, app.session_state["lab_grid_dfs"]["Main"]))
                self.assertNotEqual(compute_phase_status(app.session_state)["phase7"]["level"], "ok")
                self.assert_export_blocked(app)
                self.phase(app, "phase7")
                next(b for b in app.button if b.label == "Confirm measured lab results").click().run()
                self.assertEqual(compute_phase_status(app.session_state)["phase7"]["level"], "ok")

    def test_missing_new_values_block_even_forged_review_for_all_jobs(self):
        for job in audit.BATCH1_JOBS:
            valid = self.configured_app(job)
            saved = audit.round_trip(valid.session_state.to_dict())
            for field in ("bhct", "free_water_45", "surface_hardened_hours"):
                with self.subTest(job=job, field=field):
                    project = deepcopy(saved)
                    qc = project["lab_qc_params"]["Main"]
                    qc[field] = None
                    qc["review_signature"] = lab_review_signature(qc, project["lab_grid_dfs"]["Main"])
                    app = self.app(audit.round_trip(project))
                    self.phase(app, "phase7")
                    self.assertTrue(next(b for b in app.button if b.label == "Confirm measured lab results").disabled)
                    self.assertNotEqual(compute_phase_status(app.session_state)["phase7"]["level"], "ok")
                    self.assert_export_blocked(app)
                    self.phase(app, "phase7")
                    self.assertIsNone(app.session_state["lab_qc_params"]["Main"][field])

    def test_legacy_reviewed_without_hours_is_incomplete_draft(self):
        valid = self.configured_app(audit.BATCH1_JOBS[0])
        project = audit.round_trip(valid.session_state.to_dict())
        qc = project["lab_qc_params"]["Main"]
        qc.pop("free_water_45")
        qc.pop("surface_hardened_hours")
        qc["review_signature"] = lab_review_signature(qc, project["lab_grid_dfs"]["Main"])
        restored = self.app(project)
        self.phase(restored, "phase7")
        self.assertEqual(restored.session_state["lab_qc_params"]["Main"]["free_water"], 0.0)
        self.assertEqual(restored.session_state["lab_qc_params"]["Main"]["bhct"], 150)
        self.assertIsNone(restored.session_state["lab_qc_params"]["Main"]["surface_hardened_hours"])
        self.assert_export_blocked(restored)

    def test_exact_surface_note_compact_hours_and_sequential_numbers(self):
        values = (8.0, 8.25, 8.123456789, 0.0, 10.0)
        slurries = [{"name": str(i), "lab": {"surface_hardened_hours": v,
                     "thickening_time": "04:45", "thickening_endpoint": "100 Bc"}} for i, v in enumerate(values)]
        notes = report.build_ordered_notes('CSG 9 5/8"', {}, 40, slurries, True)
        for s, expected in zip(notes["slurries"], ("8", "8.25", "8.123456789", "0", "10")):
            body = s["lab"]["note_thickening"].split(": ", 1)[1]
            self.assertEqual(body, f"Surface Sample: Hardened Condition Observed After {expected} Hours")
            self.assertEqual(s["lab"]["thickening_time"], "04:45")
            self.assertEqual(s["lab"]["thickening_endpoint"], "100 Bc")
        numbers = [int(re.match(r"NOTE (\d+):", n)[1]) for n in notes["all_notes"]]
        self.assertEqual(numbers, [i for i in range(1, len(numbers) + 2) if i != 20])

    def test_actual_word_and_save_restore_navigation_for_all_jobs(self):
        for job in audit.BATCH1_JOBS:
            with self.subTest(job=job):
                app = self.configured_app(job)
                for label, value in (("Free Water Collected (90° angle) (ml) - Main", 1.5),
                                     ("Free Water Collected (45° angle) (ml) - Main", 2.5),
                                     ("Surface Sample Hours - Main", 8.0)):
                    self.input(app, label).set_value(value).run()
                app.session_state["lab_qc_params"]["Main"]["thickening_endpoint"] = "100 Bc"
                app.run()  # Obsolete state cannot choose the report endpoint.
                next(b for b in app.button if b.label == "Confirm measured lab results").click().run()
                restored = self.app(audit.round_trip(app.session_state.to_dict()))
                for phase in ("phase2_3", "phase4", "phase5", "phase7"):
                    self.phase(restored, phase)
                self.assertEqual(compute_phase_status(restored.session_state)["phase7"]["level"], "ok")
                self.export(restored)
                doc = Document(BytesIO(restored.session_state["_compiled_doc_bytes"]))
                paragraphs = [''.join(n.text or '' for n in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')) for p in doc.element.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')]
                text = '\n'.join(paragraphs)
                self.assertIn("Surface Sample: Hardened Condition Observed After 8 Hours", text)
                self.assertNotIn("Reported thickening time endpoint:", text)
                self.assertIn("03:30", text)
                self.assertIn("70 Bc", text)
                self.assertNotIn("100 Bc", text)
                found = {}
                for table in doc.tables:
                    for row in table.rows:
                        cells = [c.text for c in row.cells]
                        for angle in (90, 45):
                            if cells[0] == f"Collected ({angle}° angle)":
                                found[angle] = cells[1]
                self.assertEqual(found, {90: "1.5 ml in 250 ml @ 2hr", 45: "2.5 ml in 250 ml @ 2hr"})
                numbers = [int(n) for p in paragraphs for n in re.findall(r"NOTE (\d+):", p) if n != "20"]
                self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
                with patch.object(report.st, "session_state", deepcopy(restored.session_state.to_dict())):
                    ctx = report.build_master_context()
                self.assertEqual(ctx["slurries"][0]["lab"]["free_water"], 1.5)
                self.assertEqual(ctx["slurries"][0]["lab"]["free_water_45"], 2.5)
