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
    assert offered["file_name"] == "Cementing_Project_Latestwellچاه.json"
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
