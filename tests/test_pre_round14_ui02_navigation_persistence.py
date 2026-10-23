"""Retained Phase IV drafts must participate in project replacement safety."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from unittest.mock import patch

import pytest

import test_audit_regressions as audit
from test_uat_round10c_integration import save_project


CASE = audit.AuditRegressions()
VALUES = {"volume": 11.25, "density": "82.0", "pump_rate": "0.7-1.2",
          "material_name": "UI02 & <weighted spacer>"}


def dirty(app):
    return any("unsaved changes" in warning.value for warning in app.warning)


def upload(app, raw):
    incoming = BytesIO(raw)
    incoming.name = "ui02-project.json"
    incoming.size = len(raw)
    key = f"proj_uploader_{app.session_state.to_dict().get('_uploader_revision', 0)}"
    return patch("streamlit.delta_generator.DeltaGenerator.file_uploader",
                 side_effect=lambda *args, **kwargs: incoming if kwargs.get("key") == key else None)


def draft_app(fluid, edits=None):
    app = CASE.app()
    CASE.phase(app, "phase4")
    app.checkbox(key="chk_fluid_" + fluid).check().run()
    for field, value in (VALUES if edits is None else edits).items():
        kind, prefix = {"volume": ("number_input", "vol_"), "density": ("text_input", "den_"),
                        "pump_rate": ("text_input", "rate_"),
                        "material_name": ("text_input", "matname_")}[field]
        getattr(app, kind)(key=prefix + fluid).set_value(value).run()
    app.checkbox(key="chk_fluid_" + fluid).uncheck().run()
    CASE.phase(app, "phase1")
    return app


@pytest.mark.parametrize("fluid", ["Spacer Ahead", "Spacer Behind"])
def test_inactive_draft_requires_confirmation_and_survives_cancel(fluid):
    app = draft_app(fluid)
    expected = deepcopy(app.session_state["fluids_config"]["params"][fluid])
    assert expected == VALUES
    assert fluid not in app.session_state["fluid_data"]
    before = save_project(app)
    decoded = audit.decode_project(before, audit.namespace["deserialize_item"])
    assert decoded["fluids_config"]["params"][fluid] == expected
    warning = dirty(app)
    incoming = json.dumps({"well_name": "UI02 Incoming", "client": "Synthetic Client"}).encode()
    revision = app.session_state.to_dict().get("_uploader_revision", 0)
    with upload(app, incoming):
        app.run()
        CASE.healthy(app)
        confirmation = any(b.key == "_confirm_upload_replacement" for b in app.button)
        assert (warning, confirmation) == (True, True)
        assert save_project(app) == before
        app.button(key="_cancel_upload_replacement").click().run()
        CASE.healthy(app)
        assert app.session_state["_uploader_revision"] == revision + 1
        assert not any(b.key == "_confirm_upload_replacement" for b in app.button)
        assert save_project(app) == before
        assert dirty(app)
    with upload(app, incoming):
        app.run()
        app.button(key="_confirm_upload_replacement").click().run()
        CASE.healthy(app)
        assert app.session_state["well_name"] == "UI02 Incoming"
        assert app.session_state["client"] == "Synthetic Client"
        assert fluid not in app.session_state.get("fluids_config", {}).get("params", {})
        assert app.radio(key="_app_mode_key").value == "phase1"
        assert not dirty(app)


@pytest.mark.parametrize("field", list(VALUES))
def test_each_operational_input_protects_an_otherwise_empty_draft(field):
    app = draft_app("Spacer Ahead", {field: VALUES[field]})
    assert app.session_state["fluids_config"]["params"]["Spacer Ahead"][field] == VALUES[field]
    assert dirty(app)


def test_default_parameter_records_do_not_require_confirmation():
    app = CASE.app()
    CASE.phase(app, "phase4")
    assert app.session_state["fluids_config"]["params"]
    # Merely mounting a sibling's default controls must not manufacture edits.
    for fluid in ("Spacer Ahead", "Spacer Behind"):
        app.checkbox(key="chk_fluid_" + fluid).check().run()
        app.checkbox(key="chk_fluid_" + fluid).uncheck().run()
    CASE.phase(app, "phase1")
    assert not dirty(app)
    with upload(app, b'{"well_name":"Unmodified replacement"}'):
        app.run()
        CASE.healthy(app)
        assert app.session_state["well_name"] == "Unmodified replacement"
        assert not any(b.key == "_confirm_upload_replacement" for b in app.button)


def test_loaded_draft_baseline_new_edit_and_explicit_same_file_reload():
    fluid = "Spacer Ahead"
    app = draft_app(fluid)
    raw = save_project(app)
    expected = deepcopy(app.session_state["fluids_config"]["params"][fluid])
    with upload(app, raw):
        app.run()
        app.button(key="_confirm_upload_replacement").click().run()
        CASE.healthy(app)
        assert not dirty(app)
        signature = app.session_state["_saved_sig"]
        current = json.dumps(json.loads(save_project(app)), indent=4, ensure_ascii=False,
                             sort_keys=True, allow_nan=False)
        assert signature == hashlib.md5(current.encode()).hexdigest()
        for phase in ("phase4", "phase1"):
            CASE.phase(app, phase)
            assert not dirty(app)
        assert app.session_state["_saved_sig"] == signature
        CASE.phase(app, "phase4")
        app.checkbox(key="chk_fluid_" + fluid).check().run()
        app.number_input(key="vol_" + fluid).set_value(12.75).run()
        app.checkbox(key="chk_fluid_" + fluid).uncheck().run()
        CASE.phase(app, "phase1")
        assert app.session_state["fluids_config"]["params"][fluid]["volume"] == 12.75
        assert app.session_state["_saved_sig"] == signature
        assert dirty(app)
        app.run()  # The attached file must not silently undo a later edit.
        CASE.healthy(app)
        assert app.session_state["fluids_config"]["params"][fluid]["volume"] == 12.75
        app.button(key="_reload_uploaded_project").click().run()
        CASE.healthy(app)
        assert app.session_state["fluids_config"]["params"][fluid] == expected
        assert not dirty(app)
