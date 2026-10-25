"""PRE14-SH Batch B: numeric sentinels and cached Pre Flush admission."""
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from docx import Document
import numpy as np
import pytest

import engineering_tools as eng
import phase_10_procedure as report
import project_state as ps
import test_audit_regressions as audit


CASE = audit.AuditRegressions()
DOC_KEYS = ("_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature")
INVALID = [None, True, False, "", "abc", [], {}, 10**400,
           "1e999", float("inf"), float("-inf"), float("nan"),
           Decimal("1e999"), np.float64("nan")]
BAD_CACHES = [
    {"volume_bbl": value, "wash_gal": 0.0} for value in ("abc", None, 10**400, "1e999", True)
] + [
    {"volume_bbl": 25.0, "wash_gal": value} for value in ("abc", None, 10**400, "nan", False)
] + [None, {}, [25.0], "invalid cache"]


@pytest.mark.parametrize("value", INVALID)
@pytest.mark.parametrize("default", [None, -7.0])
def test_safe_float_invalid_retains_exact_sentinel(value, default):
    assert eng.safe_float(value, default) is default


@pytest.mark.parametrize("value,expected", [
    (0, 0.0), (-12, -12.0), (25.5, 25.5), ("25.5", 25.5),
    (" ۱۲.۵ ", 12.5), ("١٢.٥", 12.5), (np.float64(2.5), 2.5),
    (Decimal("1.25"), 1.25), (1e308, 1e308),
])
def test_safe_float_valid_values_are_unchanged(value, expected):
    assert eng.safe_float(value, None) == expected


@pytest.fixture(scope="module")
def preflush_project():
    app = CASE.configured_app("CMT PLUG", optional_fluids=False)
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_Pre Flush").check().run()
    app.number_input(key="vol_Pre Flush").set_value(25.0).run()
    app.text_input(key="den_Pre Flush").set_value("80.0").run()
    app.text_input(key="rate_Pre Flush").set_value("4.0").run()
    CASE.phase(app, "phase6")
    state = deepcopy(app.session_state.to_dict())
    assert ps.prepare_calculations(state) == []
    return state


def procedure(state):
    with patch.object(report.st, "session_state", state):
        return report.generate_official_procedure(
            state["job_type"], state["fluid_data"], state["fluids_config"]["active"],
            state["cement_params"], state["cement_additives_dfs"], state.get("preflush_calc"),
            state["geo_md"], state["total_pump_time_min"], state["placement_config"])


def stale_document(state):
    for key, value in zip(DOC_KEYS, (b"old word", "old.docx", "old signature")):
        state[key] = value


@pytest.mark.parametrize("cache", BAD_CACHES)
def test_malformed_consumed_cache_is_marked_and_retires_document(preflush_project, cache):
    state = deepcopy(preflush_project)
    state.pop("preflush_config")  # Only a genuinely consumed legacy cache is authority.
    state["preflush_calc"] = deepcopy(cache)
    stale_document(state)
    text = procedure(state)
    assert "Pre Flush" in text
    assert report.UNRESOLVED_INPUT_TOKEN.search(text)
    assert not any(key in state for key in DOC_KEYS)
    assert state["preflush_calc"] == cache


@pytest.mark.parametrize("cache", BAD_CACHES)
def test_prepared_context_rejects_cache_without_fabricating_zero(preflush_project, cache):
    state = deepcopy(preflush_project)
    state.pop("preflush_config")
    state["preflush_calc"] = deepcopy(cache)
    stale_document(state)
    with patch.object(report.st, "session_state", state):
        with pytest.raises(ValueError, match="Complete the marked operational inputs.*Pre Flush"):
            report.build_master_context(calculations_prepared=True)
    assert not any(key in state for key in DOC_KEYS)
    assert state["fluids_config"] == preflush_project["fluids_config"]


@pytest.mark.parametrize("cache", BAD_CACHES + [
    {"volume_bbl": 80.0, "wash_gal": 240.0, "density_pcf": "75.0"},
    {"volume_bbl": "abc", "wash_gal": "abc"},
])
@pytest.mark.parametrize("prepared", [False, True])
def test_canonical_sources_repair_malformed_cache_in_both_context_modes(preflush_project, cache, prepared):
    state = deepcopy(preflush_project)
    state["preflush_calc"] = deepcopy(cache)
    # A current edit must win over both malformed and numerically valid stale caches.
    state["fluids_config"]["params"]["Pre Flush"].update(volume=31.0, density="82.0")
    ps.refresh_fluids(state)
    assert state["fluid_data"]["Pre Flush"]["volume"] == 31.0
    state["preflush_config"].update(type="Combined (Water + NaCl + Wash)", wash_multiplier=4.0)
    with patch.object(report.st, "session_state", state):
        context = report.build_master_context(calculations_prepared=prepared)
    assert context["preflush"]["volume"] == 31.0
    assert context["preflush"]["weight"] == "82.0"
    assert any(row["Name"] == "Chemical Wash" and row["amount"] == "124.0 gal"
               for row in context["preflush"]["rows"])
    assert "Pump 31.0 bbl salt saturated water mix 124 gal chemical wash as preflush.(82.0 pcf)" in context["procedure_text"]
    assert not report.UNRESOLVED_INPUT_TOKEN.search(context["procedure_text"])
    if not prepared:
        assert state["preflush_calc"]["volume_bbl"] == 31.0
        assert state["preflush_calc"]["wash_gal"] == 124.0


def test_inactive_malformed_cache_is_not_consumed(preflush_project):
    state = deepcopy(preflush_project)
    state["fluids_config"]["active"].remove("Pre Flush")
    state["preflush_calc"] = "dormant invalid cache"
    stale_document(state)
    assert "as preflush" not in procedure(state)
    assert all(key in state for key in DOC_KEYS)


def test_phase_x_incomplete_config_remains_repairable_without_crash(preflush_project):
    app = CASE.app(deepcopy(preflush_project))
    del app.session_state["preflush_config"]
    app.session_state["preflush_calc"] = {"volume_bbl": "abc", "wash_gal": "abc"}
    stale_document(app.session_state)
    CASE.phase(app, "phase10")
    CASE.healthy(app)
    assert app.error
    assert next(b for b in app.button if b.label == "Build Word Document").disabled
    assert not any(key in app.session_state for key in DOC_KEYS)
    assert report.UNRESOLVED_INPUT_TOKEN.search(app.session_state["procedure_text"])
    CASE.phase(app, "phase6")
    CASE.healthy(app)
    assert ps.prepare_calculations(app.session_state.to_dict()) == []


@pytest.mark.parametrize("value", [10**400, "1e999", float("nan"), True])
def test_unreadable_volume_keeps_f3_precedence_and_none_sentinel(preflush_project, value):
    state = deepcopy(preflush_project)
    state["fluid_data"]["Pre Flush"]["volume"] = value
    state["preflush_calc"] = "also invalid"
    stale_document(state)
    with patch.object(report.st, "session_state", state):
        with pytest.raises(ValueError, match="Unreadable numeric volume.*Phase IV.*Pre Flush"):
            report.build_master_context(calculations_prepared=True)
    assert not any(key in state for key in DOC_KEYS)


@pytest.mark.parametrize("kind,expected", [
    ("Fresh Water Only", "Pump 25.0 bbl fresh water as pre flush."),
    ("Brine (Water + NaCl)", "Pump 25.0 bbl Salt Saturated water as pre flush.(80.0 pcf)"),
    ("Water + Chemical Wash", "Pump 25.0 bbl fresh water mix with 75 gal chemical wash as preflush.(80.0 pcf)"),
    ("Combined (Water + NaCl + Wash)", "Pump 25.0 bbl salt saturated water mix 75 gal chemical wash as preflush.(80.0 pcf)"),
])
def test_valid_cached_numeric_strings_keep_exact_procedure_wording(preflush_project, kind, expected):
    state = deepcopy(preflush_project)
    state.pop("preflush_config")
    state["preflush_calc"] = {"type": kind, "volume_bbl": "25.0", "wash_gal": "75.0", "density_pcf": "80.0"}
    assert expected in procedure(state)


@pytest.mark.parametrize("field,value", [
    ("volume", "abc"), ("volume", None), ("volume", True), ("volume", 10**400),
    ("density", "abc"), ("effective_density", "abc"),
    ("wash_multiplier", "abc"), ("wash_multiplier", None), ("wash_multiplier", True),
    ("nacl_multiplier", "1e999"), ("type", "unknown formulation"),
    ("type", []), ("type", {}),
])
@pytest.mark.parametrize("prepared", [False, True])
def test_invalid_canonical_source_never_falls_back_to_valid_cache(preflush_project, field, value, prepared):
    state = deepcopy(preflush_project)
    cache = deepcopy(state["preflush_calc"])
    if field in ("volume", "density", "effective_density"):
        state["fluid_data"]["Pre Flush"][field] = value
        if field != "effective_density":
            state["fluids_config"]["params"]["Pre Flush"][field] = value
    else:
        state["preflush_config"][field] = value
    assert report.UNRESOLVED_INPUT_TOKEN.search(procedure(state))
    assert state["preflush_calc"] == cache
    stale_document(state)
    with patch.object(report.st, "session_state", state):
        if field == "effective_density" and not prepared:
            # Effective density is derived: normal preparation must repair it
            # from valid canonical density, rather than reject that source.
            context = report.build_master_context(calculations_prepared=False)
            assert context["preflush"]["effective_density"] == 80.0
            assert state["fluid_data"]["Pre Flush"]["effective_density"] == 80.0
            assert not report.UNRESOLVED_INPUT_TOKEN.search(context["procedure_text"])
        else:
            with pytest.raises(ValueError):
                report.build_master_context(calculations_prepared=prepared)
            assert not any(key in state for key in DOC_KEYS)


def test_prepared_context_preserves_valid_legacy_fallback(preflush_project):
    state = deepcopy(preflush_project)
    state.pop("preflush_config")
    with patch.object(report.st, "session_state", state):
        context = report.build_master_context(calculations_prepared=True)
    assert context["preflush"]["volume"] == 25.0
    assert "Pump 25.0 bbl" in context["procedure_text"]
    assert context["preflush"]["wash_gal"] == preflush_project["preflush_calc"]["wash_gal"]


@pytest.mark.parametrize("field", ["water_bbl", "nacl_lbs", "nacl_multiplier", "wash_multiplier"])
@pytest.mark.parametrize("value", ["abc", None, True, 10**400, "1e999"])
def test_unreadable_consumed_legacy_word_quantities_cannot_become_zero(preflush_project, field, value):
    state = deepcopy(preflush_project)
    state.pop("preflush_config")
    state["preflush_calc"][field] = value
    stale_document(state)
    with patch.object(report.st, "session_state", state):
        with pytest.raises(ValueError, match="Complete the marked operational inputs.*Pre Flush"):
            report.build_master_context(calculations_prepared=True)
    assert not any(key in state for key in DOC_KEYS)
    assert state["preflush_calc"][field] == value


@pytest.mark.parametrize("manual", [False, True])
def test_canonical_wash_edit_stales_procedure_source_but_ignored_cache_does_not(preflush_project, manual):
    state = deepcopy(preflush_project)
    with patch.object(report.st, "session_state", state):
        before = report.synchronize_report_texts()["procedure_text"]
        state["preflush_calc"] = "ignored malformed cache"
        unchanged = report.synchronize_report_texts()["procedure_text"]
        assert unchanged == before
        if manual:
            state["procedure_text"] += "\nOwner reviewed instruction."
        original = state["procedure_text"]
        state["preflush_config"]["wash_multiplier"] = 4.0
        after = report.synchronize_report_texts()["procedure_text"]
    assert after["signature"] != before["signature"]
    assert "100 gal chemical wash" in after["generated"]
    assert after["pending"] is manual
    assert state["procedure_text"] == (original if manual else after["generated"])


def test_valid_preflush_still_builds_real_word(preflush_project):
    app = CASE.app(deepcopy(preflush_project))
    CASE.export(app)
    doc = Document(BytesIO(app.session_state["_compiled_doc_bytes"]))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "preflush" in text.lower() or "pre flush" in text.lower()
    assert "[VOLUME" not in text
    assert app.session_state["preflush_calc"] == preflush_project["preflush_calc"]
