"""Manual UAT Round 1: document-control presentation and persistence."""
from datetime import date, datetime
import unittest

import test_audit_regressions as audit

round_trip = audit.round_trip

APPROVAL_DEFAULTS = {
    "checked_by": "M.Hasannezhad", "approved_by": "Sh.Jalili",
    "checked_phone": "+98-916-604-7042", "approved_phone": "+98-917-142-1265",
}
DATES = ("request_date", "prepared_date", "approved_date", "revision_date")


class Phase1UAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    healthy = audit.AuditRegressions.healthy
    phase = audit.AuditRegressions.phase

    def test_defaults_methods_and_optional_calendars(self):
        app = self.app()
        self.assertEqual(app.selectbox(key="_w_cementing_method").options,
                         ["Primary Cementing", "Remedial Cementing"])
        for field, value in APPROVAL_DEFAULTS.items():
            self.assertEqual(app.text_input(key="_w_" + field).value, value)
        for field in DATES:
            self.assertIsNone(app.date_input(key="_w_" + field).value)
        self.assertFalse(any("unsaved changes" in warning.value for warning in app.warning))

    def test_first_edits_navigation_and_json_restore(self):
        app = self.app()
        edits = {field: "UAT " + field for field in APPROVAL_DEFAULTS}
        for field, value in edits.items():
            app.text_input(key="_w_" + field).set_value(value)
            self.phase(app, "phase2_3")
            self.phase(app, "phase1")
            self.assertEqual(app.text_input(key="_w_" + field).value, value)
            self.assertEqual(app.session_state["doc_control"][field], value)
        for index, field in enumerate(DATES):
            selected = date(2026, 10, 3 + index)
            app.date_input(key="_w_" + field).set_value(selected)
            self.phase(app, "phase2_3")
            self.phase(app, "phase1")
            self.assertEqual(app.date_input(key="_w_" + field).value, selected)
            self.assertEqual(app.session_state[field], selected.isoformat())
            self.assertEqual(app.session_state["doc_control"][field], selected.isoformat())
        app.selectbox(key="_w_cementing_method").set_value("Remedial Cementing")
        self.phase(app, "phase2_3")
        saved = round_trip(app.session_state.to_dict())
        restored = self.app(saved)
        self.assertEqual(restored.selectbox(key="_w_cementing_method").value, "Remedial Cementing")
        for field, value in edits.items():
            self.assertEqual(restored.text_input(key="_w_" + field).value, value)
        for index, field in enumerate(DATES):
            self.assertEqual(restored.date_input(key="_w_" + field).value, date(2026, 10, 3 + index))

    def test_legacy_method_is_retained_until_explicit_replacement(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                project = {"job_type": "CMT PLUG"}
                project["doc_control" if nested else "cementing_method"] = (
                    {"cementing_method": "Plug Cementing"} if nested else "Plug Cementing")
                app = self.app(round_trip(project))
                self.assertIsNone(app.selectbox(key="_w_cementing_method").value)
                self.assertNotIn("Plug Cementing", app.selectbox(key="_w_cementing_method").options)
                self.assertTrue(any("Plug Cementing" in warning.value for warning in app.warning))
                self.phase(app, "phase2_3")
                self.phase(app, "phase1")
                saved = round_trip(app.session_state.to_dict())
                self.assertEqual(saved["cementing_method"], "Plug Cementing")
                self.assertEqual(saved["doc_control"]["cementing_method"], "Plug Cementing")
                app.selectbox(key="_w_cementing_method").set_value("Remedial Cementing").run()
                self.healthy(app)
                self.assertEqual(app.session_state["cementing_method"], "Remedial Cementing")
                self.assertEqual(app.session_state["doc_control"]["cementing_method"], "Remedial Cementing")

    def test_restored_dates_and_legacy_text_are_not_discarded(self):
        for saved_value, expected in (("2026-10-03", date(2026, 10, 3)),
                                      (date(2026, 10, 3), date(2026, 10, 3)),
                                      (datetime(2026, 10, 3, 12), date(2026, 10, 3)),
                                      ("", None), ("1405/07/11", None)):
            with self.subTest(value=saved_value):
                project = {"job_type": "CMT PLUG", "doc_control": {field: saved_value for field in DATES}}
                app = self.app(round_trip(project))
                for field in DATES:
                    self.assertEqual(app.date_input(key="_w_" + field).value, expected)
                if saved_value == "1405/07/11":
                    self.phase(app, "phase2_3")
                    saved = round_trip(app.session_state.to_dict())
                    for field in DATES:
                        self.assertEqual(saved[field], saved_value)
                        self.assertEqual(saved["doc_control"][field], saved_value)
                    self.phase(app, "phase1")
                    app.date_input(key="_w_request_date").set_value(date(2026, 10, 4)).run()
                    self.assertEqual(app.session_state["request_date"], "2026-10-04")
                else:
                    app.date_input(key="_w_request_date").set_value(date(2026, 10, 4)).run()
                    app.date_input(key="_w_request_date").set_value(None).run()
                    self.assertEqual(app.session_state["request_date"], "")
                    self.assertEqual(app.session_state["doc_control"]["request_date"], "")

    def test_explicit_approval_values_and_blank_overrides_survive_restore(self):
        for value in ("Owner override", ""):
            with self.subTest(value=value):
                project = {"job_type": "CMT PLUG", "doc_control": {field: value for field in APPROVAL_DEFAULTS}}
                app = self.app(round_trip(project))
                self.phase(app, "phase2_3")
                self.phase(app, "phase1")
                for field in APPROVAL_DEFAULTS:
                    self.assertEqual(app.text_input(key="_w_" + field).value, value)
