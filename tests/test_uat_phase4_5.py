"""Manual UAT Round 1: scoped density defaults, Main dead volume and pump note."""
from copy import deepcopy
from io import BytesIO
import json
import re
import unittest
from unittest.mock import patch

import pandas as pd
from docx import Document
import test_audit_regressions as audit
from engineering_tools import compute_phase_status, validate_cement_parameters, round_half_up
from phase_5_cement import build_cement_tables, build_components, calculate_base_results
from project_io import decode_project
import phase_10_procedure as report


class Phase45UAT(unittest.TestCase):
    app = audit.AuditRegressions.app
    phase = audit.AuditRegressions.phase
    healthy = audit.AuditRegressions.healthy
    configured_app = audit.AuditRegressions.configured_app
    export = audit.AuditRegressions.export
    assert_export_blocked = audit.AuditRegressions.assert_export_blocked

    def test_scoped_density_defaults_and_missing_params(self):
        for seeded in (False, True):
            with self.subTest(missing_params=seeded):
                app = self.app({"fluids_config": {"active": ["Main", "Pre Flush"], "params": {}}} if seeded else None)
                self.phase(app, "phase4")
                if not seeded:
                    for name in ("Pre Flush", "Main", "Lead", "Tail", "Spacer"):
                        app.checkbox(key="chk_fluid_" + name).check().run()
                if not seeded:
                    for name, value in (("Lead", "80.0"), ("Tail", "118.0"), ("Spacer", "80.0")):
                        app.text_input(key="den_" + name).set_value(value).run()
                for name in ("Pre Flush", "Main"):
                    self.assertEqual(app.text_input(key="den_" + name).value, "")
                    self.assertEqual(app.session_state["fluids_config"]["params"][name]["density"], "")
                if not seeded:
                    for name, value in (("Lead", "80.0"), ("Tail", "118.0"), ("Spacer", "80.0")):
                        self.assertEqual(app.text_input(key="den_" + name).value, value)

    def test_density_first_entries_navigation_and_legacy_restore(self):
        app = self.app()
        self.phase(app, "phase4")
        for name, value in (("Pre Flush", "90"), ("Main", "120")):
            app.checkbox(key="chk_fluid_" + name).check().run()
            app.text_input(key="den_" + name).set_value(value)
            self.phase(app, "phase1")
            self.phase(app, "phase4")
            self.assertEqual(app.text_input(key="den_" + name).value, value)
        saved = audit.round_trip(app.session_state.to_dict())
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                project = deepcopy(saved)
                if legacy:
                    project["fluids_config"]["params"] = {}
                restored = self.app(project)
                self.phase(restored, "phase4")
                for name, value in (("Pre Flush", "90"), ("Main", "120")):
                    self.assertEqual(restored.text_input(key="den_" + name).value, value)
                    self.assertEqual(audit.round_trip(restored.session_state.to_dict())["fluid_data"][name]["density"], value)

    def test_blank_required_density_blocks_export_for_all_jobs(self):
        for job in audit.BATCH1_JOBS:
            valid = self.configured_app(job, optional_fluids=True)
            self.export(valid)
            saved = valid.session_state.to_dict()
            for name in ("Pre Flush", "Main"):
                with self.subTest(job=job, fluid=name):
                    project = deepcopy(saved)
                    project["fluids_config"]["params"][name]["density"] = ""
                    app = self.app(project)
                    self.phase(app, "phase4")
                    self.assertEqual(app.text_input(key="den_" + name).value, "")
                    self.assertNotEqual(compute_phase_status(app.session_state)["phase4"]["level"], "ok")
                    self.assert_export_blocked(app)

    def test_main_dead_volume_starts_unset_other_slurries_unchanged(self):
        app = self.app()
        self.phase(app, "phase4")
        for name in ("Main", "Lead", "Tail"):
            app.checkbox(key="chk_fluid_" + name).check().run()
        self.phase(app, "phase5")
        for name in ("Lead", "Tail"):
            next(w for w in app.number_input if w.label == "Dead Vol (bbl) - " + name).set_value(31.0).run()
        values = {w.label: w.value for w in app.number_input}
        self.assertIsNone(values["Dead Vol (bbl) - Main"])
        for name in ("Lead", "Tail"):
            self.assertEqual(values["Dead Vol (bbl) - " + name], 31.0)
        project = audit.round_trip(app.session_state.to_dict())
        project["cement_params"]["Main"].pop("dead_vol")
        app = self.app(project)
        self.phase(app, "phase5")
        self.assertIsNone(next(w for w in app.number_input if w.label == "Dead Vol (bbl) - Main").value)
        self.assertFalse(any("saved or calculated values" in e.value for e in app.error))

    def test_main_dead_volume_first_entry_and_restored_numeric_values(self):
        app = self.app()
        self.phase(app, "phase4")
        app.checkbox(key="chk_fluid_Main").check().run()
        self.phase(app, "phase5")
        next(w for w in app.number_input if w.label == "Dead Vol (bbl) - Main").set_value(20.0)
        self.phase(app, "phase1")
        self.phase(app, "phase5")
        self.assertEqual(app.session_state["cement_params"]["Main"]["dead_vol"], 20.0)
        saved = audit.round_trip(app.session_state.to_dict())
        next(w for w in app.number_input if w.label == "Dead Vol (bbl) - Main").set_value(None).run()
        self.phase(app, "phase1")
        self.phase(app, "phase5")
        self.assertIsNone(app.session_state["cement_params"]["Main"]["dead_vol"])
        for value in (0, 20.0, 31.0):
            with self.subTest(value=value):
                project = deepcopy(saved)
                project["cement_params"]["Main"]["dead_vol"] = value
                restored = self.app(audit.round_trip(project))
                self.phase(restored, "phase5")
                self.assertEqual(next(w for w in restored.number_input if w.label == "Dead Vol (bbl) - Main").value, value)
                self.phase(restored, "phase1")
                self.phase(restored, "phase5")
                self.assertEqual(audit.round_trip(restored.session_state.to_dict())["cement_params"]["Main"]["dead_vol"], value)

    def test_blank_dead_volume_is_safe_incomplete_and_invalidates_word(self):
        for job in audit.BATCH1_JOBS:
            with self.subTest(job=job):
                valid = self.configured_app(job)
                self.export(valid)
                project = valid.session_state.to_dict()
                project["cement_params"]["Main"]["dead_vol"] = None
                # Restore the draft, retaining old compiled bytes to test invalidation.
                restored = audit.round_trip(project)
                restored.update({k: project[k] for k in ("_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature")})
                app = self.app(restored)
                for phase in ("phase5", "phase7", "phase10", "phase5"):
                    self.phase(app, phase)
                    self.assertIsNone(app.session_state["cement_params"]["Main"]["dead_vol"])
                self.assertNotEqual(compute_phase_status(app.session_state)["phase5"]["level"], "ok")
                self.assert_export_blocked(app)
                with self.assertRaises(ValueError):
                    validate_cement_parameters({})

    def test_nullable_dead_volume_json_is_scoped_and_strict(self):
        for key in ("cement_params", "inactive_slurry_drafts"):
            with self.subTest(container=key):
                params = {"dead_vol": None}
                data = {key: {"Main": params if key == "cement_params" else {"cement_params": params}}, "job_type": 'CSG 20"'}
                self.assertIn(key, audit.round_trip(data))
        for slurry, value in (("Lead", "bad"), ("Main", ""), ("Main", "bad"), ("Main", True)):
            with self.subTest(slurry=slurry, value=value):
                with self.assertRaises(ValueError):
                    decode_project(json.dumps({"job_type": 'CSG 20"', "cement_params": {slurry: {"dead_vol": value}}}).encode(), audit.namespace["deserialize_item"])

    def test_max_pump_note_exact_body_rounding_and_invalid_sources(self):
        for time, expected in ((40.0, 50), (2.0, 3), (41.2, 52), (0.1, 0)):
            with self.subTest(time=time):
                notes = report.build_ordered_notes('CSG 20"', {}, time, [], False)
                self.assertEqual(notes["note_maxpump"], f"NOTE 3: Max Pumping Time for Slurry & Displacement with Safety Factor is {expected} min")
                self.assertEqual(notes["note_geothermal"], "NOTE 1: The Calculated Temperature is based on True Vertical Depth.")
                self.assertEqual(notes["note_densities"], "NOTE 2: Densities are Displayed at P=1 atmosphere and T=70 degF.")
                self.assertEqual(notes["note_dispvol"], "NOTE 4: The Volume of Displacement Should Be Calculated at Rig Site.")
        for time in (None, "bad", 0, -1, float("inf"), float("nan")):
            with self.subTest(invalid=time):
                self.assertIn("[PUMP TIME NOT SET IN PHASE IV]", report.build_ordered_notes('CSG 20"', {}, time, [], False)["note_maxpump"])

    def test_mix_water_dead_volume_and_additive_basis_unchanged(self):
        additives = pd.DataFrame([{"Material Type": "Anti Foam", "Name": "Anti Foam", "Physical State": "Liquid", "Mix Method": "In Mix Water", "User Input": .6}])
        for automatic in (False, True):
            with self.subTest(automatic=automatic):
                p = {"mix_water": 30.0, "dead_vol": 20.0, "total_sacks": 100.0, "auto_calc": automatic, "tank_name": "Test Tank"}
                result = calculate_base_results(p, 50.0, 118.0, *build_components(additives))
                if automatic:
                    p["mix_water"] = result["field_water_bbl"]
                    p["total_sacks"] = result["field_sacks"]
                original = deepcopy(p)
                _, rows, note = build_cement_tables(p, additives, result)
                self.assertEqual(p, original)
                self.assertEqual(p["dead_vol"], 20.0)
                if automatic:
                    self.assertEqual(p["mix_water"], result["field_water_bbl"])
                else:
                    self.assertEqual(p["mix_water"], 30.0)
                    self.assertEqual(rows.iloc[0]["(lbs or gal)/bbl"], "2.000 gal/bbl")
                    self.assertEqual(rows.iloc[0]["lbs or gal (with dead Vol.)"], "100.0 gal")
                concentration = .6 * p["total_sacks"] / p["mix_water"]
                self.assertEqual(float(rows.iloc[0]["(lbs or gal)/bbl"].split()[0]), round_half_up(concentration, 3))
                self.assertEqual(float(rows.iloc[0]["lbs or gal (with dead Vol.)"].split()[0]), round_half_up((p["mix_water"] + 20.0) * concentration, 2))
                self.assertIn(f"**{round_half_up(p['mix_water'] + 20, 1):.1f} bbl**", note)

    def test_valid_word_note_and_numeric_schedule_for_all_jobs(self):
        for job in audit.BATCH1_JOBS:
            with self.subTest(job=job):
                app = self.configured_app(job)
                self.phase(app, "phase4")
                app.number_input(key="vol_Main").set_value(50.0).run()
                app.text_input(key="rate_Main").set_value("5").run()
                app.number_input(key="vol_Displacement Fluid").set_value(60.0).run()
                app.text_input(key="rate_Displacement Fluid").set_value("6").run()
                self.assertEqual(app.session_state["total_pump_time_min"], 20.0)
                self.export(app)
                self.assertEqual(app.session_state["total_pump_time_min"], 20.0)
                with patch.object(report.st, "session_state", deepcopy(app.session_state.to_dict())):
                    ctx = report.build_master_context()
                doc = Document(BytesIO(app.session_state["_compiled_doc_bytes"]))
                # Use the underlying XML paragraphs so merged cells are not counted twice.
                paragraphs = [''.join(n.text or '' for n in p.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')) for p in doc.element.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')]
                pumping = [p for p in paragraphs if "Max Pumping Time" in p]
                self.assertEqual(pumping, ["NOTE 3: Max Pumping Time for Slurry & Displacement with Safety Factor is 25 min"])
                self.assertEqual(ctx["total_pump_time_min"], 20.0)
                note_numbers = [int(n) for p in paragraphs for n in re.findall(r"NOTE (\d+):", p) if n != "20"]
                self.assertEqual(note_numbers, list(range(1, len(note_numbers) + 1)))
                self.assertNotIn("min min", '\n'.join(pumping))
