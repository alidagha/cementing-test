"""Native preparation gate; real browser blur/download proofs live outside Git."""
import hashlib
import json
from unittest.mock import patch

import pytest
import streamlit as st
import test_audit_regressions as audit


CASE = audit.AuditRegressions()


@pytest.fixture
def downloads(monkeypatch):
    """Observe the real native widget; AppTest cannot click a download."""
    calls = []
    native = st.download_button

    def observe(**kwargs):
        calls.append(kwargs)
        return native(**kwargs)

    monkeypatch.setattr(st, "download_button", observe)
    return calls


def prepare(app):
    next(b for b in app.button if b.label == "Prepare project download").click().run()
    CASE.healthy(app)


@pytest.mark.parametrize("job", [*audit.BATCH1_JOBS, 'LNR 4 1/2"'])
def test_prepare_offers_current_inputs_without_marking_them_saved(downloads, job):
    app = CASE.app({"job_type": job})
    app.text_input(key="_w_well_name").set_value("Latest well & چاه").run()
    assert not app.get("download_button")
    assert any("unsaved changes" in w.value for w in app.warning)

    prepare(app)
    offered = downloads[-1]
    saved = json.loads(offered["data"])
    assert saved["well_name"] == saved["doc_control"]["well_name"] == "Latest well & چاه"
    assert saved["job_type"] == job
    from phase_10_procedure import _word_download_filename
    assert offered["file_name"] == _word_download_filename(saved["doc_control"]).removesuffix(".docx") + ".json"
    assert offered["args"] == (offered["data"],)
    assert "_saved_sig" not in app.session_state
    assert any("unsaved changes" in w.value for w in app.warning)
    assert len(app.get("download_button")) == 1
    assert not any(key.startswith("_") for key in saved)
    restored = audit.decode_project(offered["data"].encode(), audit.namespace["deserialize_item"])
    assert restored["well_name"] == "Latest well & چاه"

    # A later ordinary rerun cannot leave an old prepared link on the page.
    app.run()
    CASE.healthy(app)
    assert not app.get("download_button")
    assert "_saved_sig" not in app.session_state


def test_download_receipt_fingerprints_offered_bytes_not_a_newer_snapshot(downloads):
    app = CASE.app({"well_name": "Offered well"})
    prepare(app)
    offered = downloads[-1]
    callback = offered["on_click"]
    receipt = {"_saved_from_upload": True}
    newer = json.dumps({"well_name": "Newer, unsaved well"})
    with patch.object(st, "session_state", receipt), patch.dict(
            callback.__globals__, {"current_project_json": newer}):
        callback(*offered["args"])
    assert receipt["_saved_sig"] == hashlib.md5(offered["data"].encode()).hexdigest()
    assert receipt["_saved_sig"] != hashlib.md5(newer.encode()).hexdigest()
    assert receipt["_saved_at"]
    assert "_saved_from_upload" not in receipt


@pytest.mark.parametrize("job,fields,stem", [
    ('CSG 9 5/8"', {
        "well_location": " South:Pars ",
        "well_name": 'SP/101\\West? چاه',
        "rig_name": '"Rig-28".',
        "proposal_number": "pr#PR #1457",
        "revision_no": "r#R #0",
    }, "CSG 9.625 - South Pars - SP 101 West چاه - Rig-28 - PR #1457 - R #0"),
    ('LNR 4 1/2"', {"well_name": " چاه ۱۰۱ ", "rig_name": "  Rig   9 "}, "LNR 4.5 - چاه ۱۰۱ - Rig 9 - R #0"),
    ('TIE BACK LNR 4 1/2"', {"well_location": " A | B ", "well_name": "  ", "revision_no": ""}, "TIE BACK LNR 4.5 - A B"),
    ('CMT PLUG WITH CT', {'revision_no': ''}, "CMT PLUG WITH CT"),
])
def test_uat20_project_name_matches_word_with_no_word_build(downloads, job, fields, stem, tmp_path):
    from phase_10_procedure import _word_download_filename

    app = CASE.app({"doc_control": {"job_type": job}})
    for key, value in fields.items():
        app.text_input(key="_w_" + key).set_value(value).run()
    prepare(app)
    offered = downloads[-1]
    saved = json.loads(offered["data"])
    word_name = _word_download_filename(saved["doc_control"])
    assert word_name == f"Cementing Program - {stem}.docx"
    print("JSON:", offered["file_name"], "| Word:", word_name)
    (tmp_path / "project.json").write_bytes(offered["data"].encode())
    assert "_compiled_doc_bytes" not in app.session_state
    assert "_saved_sig" not in app.session_state
    assert offered["file_name"] == word_name.removesuffix(".docx") + ".json"
    restored = audit.decode_project(offered["data"].encode(), audit.namespace["deserialize_item"])
    second = CASE.app(restored)
    prepare(second)
    assert downloads[-1]["file_name"] == offered["file_name"]
    assert downloads[-1]["data"] == offered["data"]
