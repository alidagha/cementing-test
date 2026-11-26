"""Whole-psi Word presentation without changing measured/automatic state."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

import test_audit_regressions as audit
from engineering_tools import lab_review_signature
from phase_10_procedure import _word_quantity_context
from project_state import prepare_calculations
from test_audit_regressions import legacy_word_fixture

pytestmark = pytest.mark.usefixtures("legacy_word_fixture")


@pytest.mark.parametrize("raw,expected", [
    (5467.200000000001, "5467"), (5467.5, "5468"),
    ("5467.200000000001", "5467"), ("5467.5", "5468"),
    (7300, "7300"), ("7300+1000", "7300+1000"), ("", ""), ("-", "-"),
    ("NaN", "NaN"), ("Infinity", "Infinity"),
])
def test_terminal_pressure_copy_preserves_raw_context(raw, expected):
    context = {"slurries": [{"lab": {"bhsp": raw, "uca_pressure": raw}}]}
    before = deepcopy(context)
    lab = _word_quantity_context(context)["slurries"][0]["lab"]
    assert lab["bhsp"] == expected
    assert lab["uca_pressure"] == expected
    assert context == before


def test_inactive_uca_placeholder_stays_dash():
    context = {"slurries": [{"lab": {"bhsp": "5467.5", "uca_pressure": "-"}}]}
    lab = _word_quantity_context(context)["slurries"][0]["lab"]
    assert lab == {"bhsp": "5468", "uca_pressure": "-"}


def pressure_cells(doc):
    basic = next(r.cells[-1].text for t in doc.tables for r in t.rows
                 if len(r.cells) == 4 and r.cells[2].text == "BHSP")
    thick = next(t for t in doc.tables if t.rows[0].cells[0].text == "Thickening Time Test")
    uca = next(r.cells[3].text for t in doc.tables for r in t.rows
               if len(r.cells) >= 4 and r.cells[0].text == "UCA" and r.cells[2].text == "Pressure")
    crush = next(r.cells[7].text for t in doc.tables for r in t.rows
                 if len(r.cells) == 9 and r.cells[4].text == "CRUSH TEST" and r.cells[6].text == "Pressure")
    return basic, thick.rows[3].cells[1].text, uca, crush


@pytest.mark.parametrize("manual,expected", [
    (None, "5467"), ("5467.5", "5468"), ("7300+1000", "7300+1000"),
    ("232.35600000000002", "232"),
])
def test_normal_review_fresh_restore_direct_export_all_pressure_consumers(manual, expected):
    case = audit.AuditRegressions()
    app = case.configured_app('CSG 9 5/8"')
    if manual is not None:
        case.phase(app, "phase2_3")
        app.text_input(key="_w_bhsp").set_value(manual).run()
        case.phase(app, "phase7")
        next(b for b in app.button if b.label == "Sync with Phase V").click().run()
    case.phase(app, "phase7")
    assert any(f"BHSP: {expected} psi" in caption.value for caption in app.caption)
    next(w for w in app.checkbox if w.label == "UCA - Main").check().run()
    for label in ("CS @ 08:00", "CS @ 12:00", "CS @ 24:00"):
        next(w for w in app.number_input if w.label == label + " - Main").set_value(100.0).run()
    next(b for b in app.button if b.label == "Confirm measured lab results").click().run()
    saved = audit.round_trip(app.session_state.to_dict())
    raw = saved["well_data"]["bhsp"]
    assert raw == (manual if manual is not None else "5467.200000000001")
    qc = deepcopy(saved["lab_qc_params"]["Main"])
    review = lab_review_signature(qc, saved["lab_grid_dfs"]["Main"])
    # Rebuild the payload without visiting Phase VII, through the real export gate.
    saved.pop("lab_payload_Main", None)
    assert prepare_calculations(saved) == []
    assert saved["lab_payload_Main"]["bhsp"] == raw
    restored = case.app(saved)
    case.export(restored)
    doc = Document(BytesIO(restored.session_state["_compiled_doc_bytes"]))
    label = "automatic" if manual is None else "half-up" if manual == "5467.5" else "manual"
    Path(f"/tmp/bhsp-{label}.docx").write_bytes(
        restored.session_state["_compiled_doc_bytes"])
    assert pressure_cells(doc) == (expected + " psi", expected, expected, expected)
    assert restored.session_state["well_data"]["bhsp"] == raw
    assert restored.session_state["lab_payload_Main"]["bhsp"] == raw
    assert restored.session_state["lab_qc_params"]["Main"] == qc
    assert lab_review_signature(qc, restored.session_state["lab_grid_dfs"]["Main"]) == review
    assert restored.session_state["well_auto_fields"]["bhsp"] == (manual is None)
    # A normal well edit still invalidates the compiled document via existing gates.
    case.phase(restored, "phase2_3")
    restored.text_input(key="_w_bhsp").set_value("8000+500").run()
    case.phase(restored, "phase10")
    assert "_compiled_doc_bytes" not in restored.session_state


@pytest.mark.parametrize("raw,expected", [
    (232.35600000000002, "232"), (232.5, "233"), (232.4999, "232"),
    (-232.5, "-233"), ("232.500", "233"), ("۲۳۲.۵", "233"),
    (None, None), ("", ""), ("-", "-"), ("7300+1000", "7300+1000"),
    ("NaN", "NaN"), ("Infinity", "Infinity"), ("bad", "bad"), (True, True),
])
def test_r15cd_bhsp_caption_is_only_a_whole_psi_projection(raw, expected):
    from phase_7_lab import _bhsp_display
    assert _bhsp_display(raw) == expected


@pytest.mark.parametrize("raw",[float("nan"),float("inf"),float("-inf")])
def test_r15cd_bhsp_nonfinite_marker_is_not_replaced_or_admitted(raw):
    from phase_7_lab import _bhsp_display
    assert _bhsp_display(raw) is raw


B1M_PHASE7_CHANGES = ((b'from project_state import lab_source_signature, phase7_lab_fluids, refresh_spacer_lab, space'
  b'r_lab_payload, mud_lab_source_signature, mud_lab_readings\n',
  b'from project_state import lab_source_signature, phase7_lab_fluids, refresh_spacer_lab, space'
  b'r_lab_payload\n'),
 (b'    if slurry == materials_db.MUD_LAB_FLUID:\n        row.setdefault("gel_10_sec", "-")\n     '
  b'   row.setdefault("gel_10_min", "-")\n        qc["reviewed"] = False\n    if slurry == "Spacer'
  b'":\n        st.session_state["lab_qc_params"][slurry]["reviewed"] = False\n',
  b'    if slurry == "Spacer":\n        st.session_state["lab_qc_params"][slurry]["reviewed"] = F'
  b'alse\n'),
 (b'def _render_mud_lab(load_sig):\n    """Measured source and ordinary Bingham display only; nev'
  b'er HB or Word admission."""\n    name = materials_db.MUD_LAB_FLUID\n    qc = st.session_state['
  b'"lab_qc_params"].setdefault(name, {})\n    data = qc.setdefault("rheology", {})\n    initial ='
  b' new_rheology_dataset()\n    initial.update(gel_10_sec="-", gel_10_min="-")\n    row = data.se'
  b'tdefault("bhct_down", initial)\n    if not isinstance(row, dict) or not isinstance(row.get("r'
  b'eadings"), dict):\n        st.warning("Mud requires a canonical BHCT Ramp-Down measurement re'
  b'cord; reload/correct the invalid draft.")\n        return\n    prefix = f"_rheo_displacement_f'
  b'luid_bhct_down_"\n    selected_key = prefix + "selected_" + load_sig\n    if selected_key not '
  b'in st.session_state:\n        st.session_state[selected_key] = row.get("selected", False)\n   '
  b' st.checkbox("BHCT \xe2\x80\x94 Ramp-Down - Displacement Fluid", key=selected_key,\n          '
  b'      on_change=_commit_rheology, args=(name, "bhct_down", "selected", selected_key))\n    if'
  b' row.get("selected") is True:\n        for rpm in RPM_ORDER:\n            key = prefix + str(r'
  b'pm) + "_" + load_sig\n            if key not in st.session_state:\n                value = row'
  b'["readings"].get(str(rpm), "")\n                st.session_state[key] = "" if value is None e'
  b'lse str(value)\n            st.text_input(f"{rpm} RPM - BHCT \xe2\x80\x94 Ramp-Down - Displace'
  b'ment Fluid", key=key,\n                          on_change=_commit_rheology, args=(name, "bhc'
  b't_down", "readings", key, rpm))\n'
  b'        for column, field, label in zip(st.columns(2), ("gel_10_sec", "gel_10_min"), ("10 Sec Gel", "10 Min Gel")):\n'
  b'            key = prefix + field + "_" + load_sig\n'
  b'            if key not in st.session_state:\n'
  b'                value = row.get(field, "")\n'
  b'                st.session_state[key] = "" if value is None else str(value)\n'
  b'            column.text_input(f"{label} - BHCT \xe2\x80\x94 Ramp-Down - Displacement Fluid", key=key,\n'
  b'                              on_change=_commit_rheology, args=(name, "bhct_down", field, key),\n'
  b'                              help="Measured lbf/100 ft\xc2\xb2. Missing Gel holds CFW128; ordinary Bingham display is unchanged.")\n'
  b'    try:\n        mud_lab_readings(st.session_state)\n        '
  b'current = mud_lab_source_signature(st.session_state)\n        display = {"selected": True, "r'
  b'eadings": row["readings"], "gel_10_sec": "-", "gel_10_min": "-"}\n        result, issues = bu'
  b'ild_lab_rheology({"rheology": {"bhct_down": display}}, name)\n        if issues:\n            '
  b'raise ValueError("; ".join(issues))\n        values = result["bhct_down"]\n    except (ValueEr'
  b'ror, TypeError, OverflowError) as exc:\n        st.warning(str(exc))\n        return\n    colum'
  b'ns = st.columns(2)\n    columns[0].metric("PV (cP)", f"{values[\'pv_cp\']:.3f}")\n    column'
  b's[1].metric("Ty (lbf/100ft\xc2\xb2)", f"{values[\'ty_lbf_100ft2\']:.2f}")\n    signatures = s'
  b't.session_state.setdefault("lab_source_signatures", {})\n    if (qc.get("reviewed") is True a'
  b'nd signatures.get(name) == current\n            and qc.get("review_signature") == lab_review_'
  b'signature(qc, None)):\n        st.success("Measured Mud BHCT Ramp-Down readings reviewed for '
  b'the current Mud context.")\n    elif st.button("Confirm measured Mud lab results", key="_conf'
  b'irm_mud_lab_" + load_sig,\n                   help="Confirm these seven actual measured dials'
  b'; physical instrument provenance remains unverified."):\n        signatures[name] = current\n '
  b'       qc["reviewed"] = True\n        qc["review_signature"] = lab_review_signature(qc, None)'
  b'\n        st.rerun()\n\n\ndef get_slurry_key(slurry_name: str, prefix: str) -> str:\n',
  b'def get_slurry_key(slurry_name: str, prefix: str) -> str:\n'),
 (b'active_slurries = phase7_lab_fluids(st.session_state, include_mud=True)',
  b'active_slurries = phase7_lab_fluids(st.session_state)'),
 (b'tabs = st.tabs(["Displacement Fluid (Mud)" if s == materials_db.MUD_LAB_FLUID else s for s i'
  b'n active_slurries])',
  b'tabs = st.tabs(active_slurries)'),
 (b'            if slurry == materials_db.MUD_LAB_FLUID:\n                _render_mud_lab(load_si'
  b'g)\n                continue\n            full_lab = slurry in materials_db.PLACEMENT_SLURRIES'
  b'\n',
  b'            full_lab = slurry in materials_db.PLACEMENT_SLURRIES\n'))


B1M_PHASE7_CHANGES += ((b'all(f in (*materials_db.RHEOLOGY_ONLY_FLUIDS, materials_db.MUD_LAB_FLUID) for f in active_slurries)', b'all(f in materials_db.RHEOLOGY_ONLY_FLUIDS for f in active_slurries)'),)

UAT20_CEMENT_WATER_CHANGES = (
    (
        b'\n'
        b'    return pd.DataFrame(lab_rows)\n'
        b'\n'
        b'def _cement_lab_display(grid):\n'
        b'    view = grid.copy()\n'
        b'    water = pd.Series(False, index=view.index, dtype="boolean")\n'
        b'    if {"Material", "Unit"}.issubset(view.columns):\n'
        b'        water = (view["Material"].eq("Base Water") & view["Unit"].eq("BWOW")).astype("boolean")\n'
        b'        view.loc[water, "Material"] = "Fresh Water"\n'
        b'    view["_cement_base_water"] = water\n'
        b'    return view\n'
        b'\n'
        b'\n'
        b'def _canonical_cement_lab_grid(edited, previous):\n'
        b'    # Only the original water row has a presentation alias. New rows and\n'
        b'    # edits to other materials keep the exact names entered by the operator.\n'
        b'    water = previous["_cement_base_water"].reindex(edited.index).fillna(False)\n'
        b'    grid = edited.drop(columns="_cement_base_water")\n'
        b'    if water.any():\n'
        b'        grid.loc[water & grid["Material"].eq("Fresh Water"), "Material"] = "Base Water"\n'
        b'    return grid\n'
        b'\n'
        b'\n'
        b'def _spacer_lab_display(grid):\n'
        b'    """A view only: Cement lab precision, with the original Spacer units."""\n',
        b'\n'
        b'    return pd.DataFrame(lab_rows)\n'
        b'\n'
        b'def _spacer_lab_display(grid):\n'
        b'    """A view only: Cement lab precision, with the original Spacer units."""\n',
    ),
    (
        b'            edited_lab_df = persistent_data_editor(\n'
        b'                _cement_lab_display(current_lab_df) if full_lab else current_lab_df,\n'
        b'                persist_to=("lab_grid_dfs", slurry),\n'
        b'                normalize=_canonical_cement_lab_grid if full_lab else None,\n'
        b'                column_config={\n'
        b'                    "_cement_base_water": None,\n'
        b'                    # Allow an unfinished row',
        b'            edited_lab_df = persistent_data_editor(\n'
        b'                current_lab_df,\n'
        b'                persist_to=("lab_grid_dfs", slurry),\n'
        b'                column_config={\n'
        b'                    # Allow an unfinished row',
    ),
    (
        b"                width='stretch'\n"
        b'            )\n'
        b'            \n'
        b'            if full_lab:\n'
        b'                edited_lab_df = st.session_state["lab_grid_dfs"][slurry]\n'
        b'\n'
        b'            # Defensive validation against deleted rows\n'
        b'            if edited_lab_df is None:\n',
        b"                width='stretch'\n"
        b'            )\n'
        b'            \n'
        b'            # Defensive validation against deleted rows\n'
        b'            if edited_lab_df is None:\n',
    ),
)


UI_PERSISTENCE_A_LAB_CHANGES = (
    (
        b'from project_state import invalidate_document\n'
        b'from project_state import mud_lab_source\n'
        b'from project_state import lab_source_signature, phase7_lab_fluids, refresh_spacer_lab, spacer_lab_payload, mud_lab_source_signature, mud_lab_readings\n'
        b'from engineering_tools import round_half_up',
        b'from project_state import invalidate_document\n'
        b'from project_state import lab_source_signature, phase7_lab_fluids, refresh_spacer_lab, spacer_lab_payload, mud_lab_source_signature, mud_lab_readings\n'
        b'from engineering_tools import round_half_up',
    ),
    (
        b'        return {}, False\n'
        b'\n'
        b'\n'
        b'def _mud_rpm_context(state):\n'
        b'    try:\n'
        b'        source = mud_lab_source(state)\n'
        b'    except ValueError:\n'
        b'        return None\n'
        b'    return state.get("last_loaded_hash", "default_project"), state.get("job_type"), source\n'
        b'\n'
        b'\n'
        b'def _owned_mud_rpm_row(state):\n'
        b'    name = materials_db.MUD_LAB_FLUID\n'
        b'    owner = state.get("_mud_rpm_owner")\n'
        b'    if owner is None or name not in phase7_lab_fluids(state, include_mud=True):\n'
        b'        return None\n'
        b'    if owner != _mud_rpm_context(state):\n'
        b'        return None\n'
        b'    row = state.get("lab_qc_params", {}).get(name, {}).get("rheology", {}).get("bhct_down", {})\n'
        b'    if (isinstance(row, dict) and isinstance(row.get("readings"), dict)\n'
        b'            and row.get("selected") is True):\n'
        b'        return row\n'
        b'    return None\n'
        b'\n'
        b'\n'
        b'def commit_pending_mud_rpm():\n'
        b'    """Save received readings after the dataset selection callback has run."""\n'
        b'    state = st.session_state\n'
        b'    row = _owned_mud_rpm_row(state)\n'
        b'    if row is not None:\n'
        b'        load_sig = state["_mud_rpm_owner"][0]\n'
        b'        for rpm in RPM_ORDER:\n'
        b'            key = f"_rheo_displacement_fluid_bhct_down_{rpm}_{load_sig}"\n'
        b'            raw = row["readings"].get(str(rpm))\n'
        b'            if key in state and state[key] != ("" if raw is None else str(raw)):\n'
        b'                _commit_rheology(materials_db.MUD_LAB_FLUID, "bhct_down", "readings", key, rpm)\n'
        b'    if state.get("_app_mode_key") != "phase7":\n'
        b'        state.pop("_mud_rpm_owner", None)\n'
        b'\n'
        b'\n'
        b'def _commit_rheology(slurry, dataset, field, widget_key, rpm=None):\n'
        b'    if slurry == materials_db.MUD_LAB_FLUID and rpm is not None:\n'
        b'        state = st.session_state\n'
        b'        row = _owned_mud_rpm_row(state)\n'
        b'        if row is None:\n'
        b'            return\n'
        b'        load_sig = state["_mud_rpm_owner"][0]\n'
        b'        if widget_key != f"_rheo_displacement_fluid_bhct_down_{rpm}_{load_sig}":\n'
        b'            return\n'
        b'        raw = row["readings"].get(str(rpm))\n'
        b'        value = state[widget_key]\n'
        b'        if value == ("" if raw is None else str(raw)):\n'
        b'            return\n'
        b'        state["lab_qc_params"][slurry]["reviewed"] = False\n'
        b'        invalidate_document(state)\n'
        b'        row.setdefault("gel_10_sec", "-")\n'
        b'        row.setdefault("gel_10_min", "-")\n'
        b'        row["readings"][str(rpm)] = value\n'
        b'        return\n'
        b'    qc = st.session_state["lab_qc_params"].setdefault(slurry, {})',
        b'        return {}, False\n'
        b'\n'
        b'\n'
        b'def _commit_rheology(slurry, dataset, field, widget_key, rpm=None):\n'
        b'    qc = st.session_state["lab_qc_params"].setdefault(slurry, {})',
    ),
    (
        b'            st.text_input(f"{rpm} RPM - BHCT \xe2\x80\x94 Ramp-Down - Displacement Fluid", key=key)\n'
        b'        for column, field, label in zip(st.columns(2), ("gel_10_sec", "gel_10_min"), ("10 Sec Gel", "10 Min Gel")):',
        b'            st.text_input(f"{rpm} RPM - BHCT \xe2\x80\x94 Ramp-Down - Displacement Fluid", key=key,\n'
        b'                          on_change=_commit_rheology, args=(name, "bhct_down", "readings", key, rpm))\n'
        b'        for column, field, label in zip(st.columns(2), ("gel_10_sec", "gel_10_min"), ("10 Sec Gel", "10 Min Gel")):',
    ),
    (
        b'            if slurry == materials_db.MUD_LAB_FLUID:\n'
        b'                st.session_state["_mud_rpm_owner"] = _mud_rpm_context(st.session_state)\n'
        b'                _render_mud_lab(load_sig)\n'
        b'                continue\n'
        b'            full_lab = slurry in materials_db.PLACEMENT_SLURRIES',
        b'            if slurry == materials_db.MUD_LAB_FLUID:\n'
        b'                _render_mud_lab(load_sig)\n'
        b'                continue\n'
        b'            full_lab = slurry in materials_db.PLACEMENT_SLURRIES',
    ),
)


def _before_mud_rpm_recovery(source):
    for after, before in UI_PERSISTENCE_A_LAB_CHANGES:
        assert source.count(after) == 1
        source = source.replace(after, before, 1)
    return source


def r15cd_original_lab_source(source):
    """Undo exact approved changes while preserving the original historical file pin."""
    return _original_lab_source(_before_mud_rpm_recovery(source))


def _original_lab_source(source):
    for after, before in UAT20_CEMENT_WATER_CHANGES + B1M_PHASE7_CHANGES:
        assert source.count(after) == 1
        source = source.replace(after, before, 1)
    helper = b'''def _bhsp_display(value):
    """Whole-psi caption only; preserve missing/manual-expression markers."""
    if value is None:
        return value
    try:
        return f"{round_half_up(value, 0):.0f}"
    except (ValueError, TypeError, OverflowError):
        return value


'''
    changes = (
        (b'\n    if slurry in ("Pre Flush", "Diesel"):', b'\n    if slurry == "Pre Flush":'),
        (b'\n        if slurry in ("Pre Flush", "Diesel"):', b'\n        if slurry == "Pre Flush":'),
        (b'        if slurry == "Diesel":\n            for field in ("gel_10_sec", "gel_10_min"):\n                row.setdefault(field, "-")\n', b''),
        (b"from engineering_tools import round_half_up, build_lab_rheology", b"from engineering_tools import build_lab_rheology"),
        (helper, b""),
        (b"Pressure = {_bhsp_display(bhsp)} psi", b"Pressure = {bhsp} psi"),
        (b"{_bhsp_display(st.session_state.get('well_data', {}).get('bhsp', ''))}",
         b"{st.session_state.get('well_data', {}).get('bhsp', '')}"),
    )
    for after,before in changes:
        assert source.count(after)==1
        source=source.replace(after,before,1)
    return source


@pytest.mark.parametrize("after,before", UI_PERSISTENCE_A_LAB_CHANGES,
                         ids=("import", "recovery", "rpm-widget", "owner"))
def test_mud_rpm_recovery_inverse_preserves_fixed_history(after, before):
    import hashlib

    source = Path("phase_7_lab.py").read_bytes()
    expected = "f95e337cc8445a5b6cf8c582bb09c982a36e9d638608582d41fb50922f56903f"
    assert source.count(after) == 1
    assert hashlib.sha256(r15cd_original_lab_source(source)).hexdigest() == expected
    for mutation in (source.replace(after, b"!" + after[1:], 1), source + after,
                     source.replace(after, before, 1), source.replace(after, before, 1) + after):
        with pytest.raises(AssertionError):
            assert hashlib.sha256(r15cd_original_lab_source(mutation)).hexdigest() == expected


@pytest.mark.parametrize("old,new", [
    (b'row.setdefault(field, "-")', b'row.setdefault(field, "0")'),
    (b'\n    if slurry in ("Pre Flush", "Diesel"):', b'\n    if slurry in ("Pre Flush", "Scavenger"):'),
    (b"round_half_up(value, 0)",b"round_half_up(value, 1)"),
    (b"Pressure = {_bhsp_display(bhsp)} psi",b"Pressure = {bhsp} psi"),
    (b'"bhsp": well_data.get("bhsp", ""),',b'"bhsp": 0.,'),
])
def test_r15cd_caption_source_compatibility_rejects_other_changes(old,new):
    import hashlib
    source=Path("phase_7_lab.py").read_bytes()
    expected="f95e337cc8445a5b6cf8c582bb09c982a36e9d638608582d41fb50922f56903f"
    assert hashlib.sha256(r15cd_original_lab_source(source)).hexdigest()==expected
    assert source.count(old)==1
    with pytest.raises(AssertionError):
        assert hashlib.sha256(r15cd_original_lab_source(source.replace(old,new))).hexdigest()==expected


@pytest.mark.parametrize("after,before", UAT20_CEMENT_WATER_CHANGES, ids=("helpers", "projection", "canonical"))
@pytest.mark.parametrize("mutation", ("changed", "missing", "duplicated", "relocated"))
def test_uat20_water_inverse_preserves_the_historical_pin(after, before, mutation):
    import hashlib

    source = Path("phase_7_lab.py").read_bytes()
    expected = "f95e337cc8445a5b6cf8c582bb09c982a36e9d638608582d41fb50922f56903f"
    assert source.count(after) == 1
    assert hashlib.sha256(r15cd_original_lab_source(source)).hexdigest() == expected
    mutations = {
        "changed": source.replace(after, after[:-1] + b"!", 1),
        "missing": source.replace(after, before, 1),
        "duplicated": source + after,
        "relocated": source.replace(after, before, 1) + after,
    }
    with pytest.raises(AssertionError):
        assert hashlib.sha256(r15cd_original_lab_source(mutations[mutation])).hexdigest() == expected


@pytest.mark.parametrize('fragment', range(len(B1M_PHASE7_CHANGES)))
@pytest.mark.parametrize('mutation', ['changed','missing','duplicated','relocated'])
def test_b1m_exact_mud_inverse_rejects_changed_missing_duplicate_or_relocated_fragment(fragment,mutation):
    import hashlib
    source=Path('phase_7_lab.py').read_bytes();after,before=B1M_PHASE7_CHANGES[fragment]
    expected='f95e337cc8445a5b6cf8c582bb09c982a36e9d638608582d41fb50922f56903f'
    assert hashlib.sha256(r15cd_original_lab_source(source)).hexdigest()==expected
    source = _before_mud_rpm_recovery(source)
    assert source.count(after)==1
    if mutation=='changed':bad=source.replace(after,bytes([after[0]^1])+after[1:],1)
    elif mutation=='missing':bad=source.replace(after,before,1)
    elif mutation=='duplicated':bad=source+after
    else:bad=source.replace(after,before,1)+after
    with pytest.raises(AssertionError):
        assert hashlib.sha256(_original_lab_source(bad)).hexdigest()==expected


@pytest.mark.parametrize('old,new',[(b'columns = st.columns(2)',b'columns = st.columns(3)'),
    (b'calculate_slurry_from_components,',b'calculate_slurry_from_components_changed,'),
    (b'"PV (cP)"',b'"PV (wrong units)"'),
    (b'"bhsp": well_data.get("bhsp", ""),',b'"bhsp": 99.,')])
def test_b1m_mud_normalizer_never_hides_unrelated_source_or_bingham_display_changes(old,new):
    import hashlib
    source=Path('phase_7_lab.py').read_bytes()
    assert old in source
    with pytest.raises(AssertionError):
        assert hashlib.sha256(r15cd_original_lab_source(source.replace(old,new,1))).hexdigest()=='f95e337cc8445a5b6cf8c582bb09c982a36e9d638608582d41fb50922f56903f'


@pytest.mark.parametrize('mutation', ['unchanged', 'label', 'unit', 'callback', 'missing',
                                      'duplicated', 'relocated', 'inserted'])
def test_b2_gel_inverse_preserves_fixed_history_and_rejects_widget_mutations(mutation):
    import hashlib
    live_source = Path('phase_7_lab.py').read_bytes()
    source = _before_mud_rpm_recovery(live_source)
    mud_editor = B1M_PHASE7_CHANGES[2][0]
    # Accepted B2 editor, including its following function boundary; never pin arbitrary current bytes.
    assert len(mud_editor) == 3548
    assert hashlib.sha256(mud_editor).hexdigest() == '8d70b3d5d2893aa4d1d80af936d8e394a844b7f72612025aeb50886782863218'
    assert source.count(mud_editor) == 1
    expected = 'f95e337cc8445a5b6cf8c582bb09c982a36e9d638608582d41fb50922f56903f'
    assert hashlib.sha256(r15cd_original_lab_source(live_source)).hexdigest() == expected
    start = mud_editor.index(b'        for column, field, label in zip(')
    end = mud_editor.index(b'    try:\n', start)
    gel = mud_editor[start:end]
    assert len(gel) == 644 and source.count(gel) == 1
    if mutation == 'unchanged':
        return
    if mutation == 'label':
        bad = source.replace(gel, gel.replace(b'10 Min Gel', b'10 Min Changed Gel'), 1)
    elif mutation == 'unit':
        bad = source.replace(gel, gel.replace(b'lbf/100 ft', b'Pa/100 ft'), 1)
    elif mutation == 'callback':
        bad = source.replace(gel, gel.replace(b'on_change=_commit_rheology', b'on_change=None'), 1)
    elif mutation == 'missing':
        bad = source.replace(gel, b'', 1)
    elif mutation == 'duplicated':
        bad = source.replace(gel, gel + gel, 1)
    elif mutation == 'relocated':
        bad = source.replace(gel, b'', 1) + gel
    else:
        bad = source.replace(gel, gel + b'        qc["unapproved"] = True\n', 1)
    with pytest.raises(AssertionError):
        assert hashlib.sha256(_original_lab_source(bad)).hexdigest() == expected
