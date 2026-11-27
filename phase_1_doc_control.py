# phase_1_doc_control.py
import streamlit as st
import materials_db
from datetime import date, datetime
from uuid import uuid4
from project_state import DOC_CONTROL_DEFAULTS, DOCUMENT_DETAIL_FIELDS, request_description_for_job

DOCUMENT_DATE_FIELDS = ("request_date", "prepared_date", "checked_date", "approved_date", "revision_date")
_DESCRIPTION_FIELDS = ("request_description", "revision_description")
_REQUEST_EDITORS = "_doc_request_description_editors"
_OUTGOING_REQUEST_EDITOR = "_doc_outgoing_request_editor"

# FIX (real bug, confirmed pre-existing — not introduced by any earlier update):
# Streamlit deletes a widget's session_state entry whenever that widget is not
# instantiated on a given script rerun. This app renders only the currently-
# selected phase's module each rerun, so every widget on Phase I stopped being
# instantiated the moment the user switched to any other phase — its key got
# deleted, and the "if key not in st.session_state: set default" initializer
# at the top of render() then silently re-blanked it the next time Phase I
# was opened. Verified this was genuine Streamlit widget-lifecycle behavior
# (not something specific to this app) with a minimal reproduction under
# streamlit.testing.v1.AppTest before touching this file.
#
# The fix: every field has two keys now — a plain "shadow" key (e.g.
# "well_name") that is NEVER itself a widget's `key=`, so Streamlit's cleanup
# can't touch it and it survives navigation; and a private widget-only key
# (prefixed "_w_") that IS the widget's `key=` and is allowed to disappear.
# The widget-only key is seeded from the shadow ONLY when missing (first
# render, or just restored after navigating back) — never alongside a
# `value=`/`index=` argument, since Streamlit warns/conflicts when a widget's
# key already holds a session_state value AND a default is also passed. After
# the widget renders, its current value (unchanged, or just edited by the
# user) is mirrored back into the shadow. The "_w_" prefix also means these
# widget-only keys are automatically excluded from the saved project JSON
# (see main.py's get_serializable_state) — only the shadow keys are saved,
# which is correct. Callbacks also commit shadows and export snapshots before
# navigation can skip this render.
# Description editors compare browser drafts with their own published text.
#
# Job Type's on_change callback additionally writes the DEPENDENT fields'
# widget keys directly (not just their shadows), because once a widget key
# already holds a value, Streamlit always shows that over anything computed
# from the shadow on the next render — the only way to make hole_size /
# cementing_method visibly jump to their new auto-filled value the instant
# Job Type changes is to set their widget keys in the same callback.

def _doc_widget_key(field):
    key = f"_w_{field}"
    # Old browser frames must not address the new job's dependent controls.
    if field in ("hole_size", "cementing_method"):
        key += "_" + st.session_state["job_type"]
    return key


def _commit_doc_widget(field, widget_key=None):
    """Commit metadata and its export snapshot before navigation unmounts it."""
    widget_key = widget_key or _doc_widget_key(field)
    if widget_key != _doc_widget_key(field):
        return  # A late echo from a retired job's control is not a new edit.
    value = st.session_state[widget_key]
    if field in DOCUMENT_DATE_FIELDS:
        value = value.isoformat() if isinstance(value, (date, datetime)) else ""
    st.session_state[field] = value
    if field == "report_date":
        value = value.isoformat() if isinstance(value, (date, datetime)) else "" if value is None else str(value)
    st.session_state.setdefault("doc_control", {})["date" if field == "report_date" else field] = value


def _sync_document_descriptions():
    """Keep the project snapshots current even when navigation skips Phase I."""
    state = st.session_state
    if not state.get("request_description_customized", False):
        state["request_description"] = request_description_for_job(state["job_type"])
    if not state.get("revision_description_customized", False):
        state["revision_description"] = state["request_description"]
    snapshot = state.setdefault("doc_control", {})
    for field in _DESCRIPTION_FIELDS:
        snapshot[field] = state[field]


def _commit_description(field, widget_key):
    state = st.session_state
    editors_key = f"_doc_{field}_editors"
    editors = state.get(editors_key, {})
    if widget_key not in editors:
        return
    outgoing = state.get(_OUTGOING_REQUEST_EDITOR)
    if widget_key == outgoing and state.get("_w_job_type") != state["job_type"]:
        return  # The draft belongs to the previous transition, not another job change.
    draft = state.get(widget_key)
    if draft is None or draft == editors[widget_key]:
        return  # An unchanged old browser snapshot does not make a description manual.

    # Once an edit has arrived, an older editor cannot replace it. Newer editors
    # can still carry a real edit that was submitted before their next render.
    ordered_keys = list(editors)
    current_and_later = {key: editors[key] for key in ordered_keys[ordered_keys.index(widget_key):]}
    current_and_later[widget_key] = draft
    state[field + "_customized"] = True
    state[field] = draft
    state[editors_key] = current_and_later
    if field == "request_description" and widget_key != outgoing:
        _retire_outgoing_request_editor()
    _sync_document_descriptions()


def _commit_pending_descriptions():
    """Recover browser drafts when a rerun interrupted their callbacks."""
    state = st.session_state
    for field in _DESCRIPTION_FIELDS:
        for key, shown in reversed(state.get(f"_doc_{field}_editors", {}).items()):
            draft = state.get(key)
            if draft is not None and draft != shown:
                _commit_description(field, key)
                break


def _retire_outgoing_request_editor():
    state = st.session_state
    outgoing = state.pop(_OUTGOING_REQUEST_EDITOR, None)
    if outgoing is not None:
        state.get(_REQUEST_EDITORS, {}).pop(outgoing, None)


def leave_document_control():
    _commit_pending_descriptions()
    _retire_outgoing_request_editor()
    st.session_state["_doc_control_remount"] = True


def _render_description(label, field):
    state = st.session_state
    editors_key = f"_doc_{field}_editors"
    editors = state.get(editors_key, {})
    widget_key = next(reversed(editors), None)
    if (widget_key is None or widget_key == state.get(_OUTGOING_REQUEST_EDITOR)
            or editors[widget_key] != state[field]):
        # Streamlit sends whole widget snapshots. A new suggestion gets a new
        # editor so an in-flight frame still refers to the text it was shown.
        widget_key = f"_w_{field}_{uuid4().hex}"
        state[editors_key] = {**editors, widget_key: state[field]}
    # A new Job Type or inherited Request can replace an automatic suggestion
    # before blur. Send edits to suggestions immediately. Manual editors keep Enter/blur.
    live = "0ms" if not state[field + "_customized"] else False
    st.text_input(label, value=state[field], key=widget_key,
                  on_change=_commit_description, args=(field, widget_key), live=live)


def on_job_type_change():
    """Callback: Synchronously updates suggested hole size and method without UI lag."""
    new_job = st.session_state.get("_w_job_type", materials_db.JOB_TYPES[0])
    # A blur and selection can share a frame. Take drafts before retiring the
    # current job's editors, including drafts from an earlier suggestion.
    _commit_pending_descriptions()
    hole_widget_key = _doc_widget_key("hole_size")
    hole_size = st.session_state["hole_size"]
    if st.session_state.get(hole_widget_key, hole_size) != hole_size:
        _mark_hole_size_customized(hole_widget_key)
    if new_job == st.session_state.get("job_type"):
        return
    # Legacy tops have no owner marker until their original job is changed.
    for params in st.session_state.get("cement_params", {}).values():
        if params.get("top_job_type") is None:
            params["top_job_type"] = st.session_state["job_type"]

    from placement import EXCESS_FIELDS
    from project_state import invalidate_document
    from centralizer_adapter import SHALLOW_CASING_JOBS
    if new_job in SHALLOW_CASING_JOBS or st.session_state.get("job_type") in SHALLOW_CASING_JOBS:
        for key in ("_centralizer_result", "_centralizer_signature", "_centralizer_error"):
            st.session_state.pop(key, None)
    placement = st.session_state.get("placement_config", {})
    for field, _, _ in EXCESS_FIELDS:
        placement.pop(field, None)
        for key in list(st.session_state):
            if key.startswith(f"_placement_{field}_"):
                st.session_state.pop(key, None)
    st.session_state["_placement_excess_revision"] = st.session_state.get("_placement_excess_revision", 0) + 1
    invalidate_document(st.session_state)
    _commit_doc_widget("job_type")
    if new_job == materials_db.CT_JOB:
        from project_state import reconcile_fluid_applicability
        reconcile_fluid_applicability(st.session_state)
        invalidate_document(st.session_state)
    new_method = materials_db.get_cementing_method(new_job)
    st.session_state["cementing_method"] = new_method
    st.session_state[_doc_widget_key("cementing_method")] = new_method
    _commit_doc_widget("cementing_method")

    # FIX (requested, Level 1 #2): this used to unconditionally overwrite
    # Hole Size with the new Job Type's default, silently discarding
    # anything the operator had typed by hand — e.g. a real injection-string
    # note for a Plug job like "Inside 9 5/8" CSG" (see the field's own help
    # text, which explicitly invites exactly that kind of custom value).
    # The customization marker is project data so save/load preserves it.
    # Older projects infer it from the saved value during initialization.
    if not st.session_state.get("hole_size_customized", False):
        new_hole = materials_db.DEFAULT_HOLE_SIZES.get(new_job, "12 1/4\"")
        st.session_state["hole_size"] = new_hole
    st.session_state[_doc_widget_key("hole_size")] = st.session_state["hole_size"]
    _commit_doc_widget("hole_size")
    _sync_document_descriptions()
    _retire_outgoing_request_editor()
    editors = st.session_state.pop(_REQUEST_EDITORS, {})
    if editors:
        # A first Request edit can arrive from the editor still visible while
        # the new Job Type renders. Only that last editor may finish the edit.
        outgoing = next(reversed(editors))
        st.session_state[_REQUEST_EDITORS] = {outgoing: editors[outgoing]}
        st.session_state[_OUTGOING_REQUEST_EDITOR] = outgoing
    st.session_state.pop("_doc_revision_description_editors", None)

def _mark_hole_size_customized(widget_key):
    if widget_key != _doc_widget_key("hole_size"):
        return
    st.session_state["hole_size_customized"] = True
    _commit_doc_widget("hole_size", widget_key)

def _seed(widget_key, shadow_key):
    """Restore controls whose browser state can be discarded on phase changes."""
    # An incoming snapshot may contain the old key even when the browser is
    # about to mount a new control with no widget state of its own.
    if widget_key not in st.session_state or st.session_state.get("_doc_control_remount"):
        value = st.session_state[shadow_key]
        if shadow_key in DOCUMENT_DATE_FIELDS:
            if isinstance(value, datetime):
                value = value.date()
            elif not isinstance(value, date):
                try:
                    value = date.fromisoformat(value) if value else None
                except (TypeError, ValueError):
                    # Keep legacy free-text dates canonical until explicitly replaced.
                    value = None
        st.session_state[widget_key] = value

def render():
    st.header("Phase I: Document Control")
    st.markdown("Enter primary operational metadata for the cementing program compliant with NIDC standards.")
    
    # 1. Initialize Flat Canonical State (shadow keys — survive navigation)
    doc = st.session_state.get("doc_control", {})
    default_date = None if "date" in doc and doc["date"] is None else date.today()
    default_values = dict(DOC_CONTROL_DEFAULTS, report_date=default_date)
    for key, val in default_values.items():
        if key not in st.session_state:
            st.session_state[key] = val

    for field in _DESCRIPTION_FIELDS:
        st.session_state.setdefault(field + "_customized", False)
    _commit_pending_descriptions()
    _sync_document_descriptions()

    if "hole_size_customized" not in st.session_state:
        st.session_state["hole_size_customized"] = (
            st.session_state.get("_hole_size_customized", False)
            or st.session_state["hole_size"] != materials_db.DEFAULT_HOLE_SIZES.get(
                st.session_state["job_type"], "12 1/4\"")
        )

    col1, col2 = st.columns(2)
    
    with col1:
        # Job Type with instant callback
        _seed("_w_job_type", "job_type")
        job_choices = [job for job in materials_db.JOB_TYPES
                       if job != 'CSG 7"' or job == st.session_state["job_type"]]
        st.selectbox(
            "Job Type", 
            job_choices,
            key="_w_job_type",
            on_change=on_job_type_change
        )
        st.session_state["job_type"] = st.session_state["_w_job_type"]
        
        # Hole Size (Fully unconstrained free-text with helper guidance)
        hole_widget_key = _doc_widget_key("hole_size")
        _seed(hole_widget_key, "hole_size")
        if st.session_state[hole_widget_key] != st.session_state["hole_size"]:
            _mark_hole_size_customized(hole_widget_key)
        st.text_input(
            "Hole Size (in)", 
            key=hole_widget_key,
            on_change=_mark_hole_size_customized,
            args=(hole_widget_key,),
            help="Enter hole diameter (e.g. 26\", 12 1/4\", 8 1/2\") or injection string context for plugs (e.g. Inside 9 5/8\" CSG)."
        )
        st.session_state["hole_size"] = st.session_state[hole_widget_key]
        st.markdown(f"↳ Default for {st.session_state['job_type']}: {materials_db.DEFAULT_HOLE_SIZES.get(st.session_state['job_type'], '—')} (your own value is kept once edited)")
        
        # Well Location & Names
        for label, shadow_key in [("Field", "field"), ("Well Location", "well_location"),
                                   ("Well Name", "well_name"), ("Rig Name", "rig_name")]:
            widget_key = f"_w_{shadow_key}"
            _seed(widget_key, shadow_key)
            st.text_input(label, key=widget_key, on_change=_commit_doc_widget, args=(shadow_key,))
            st.session_state[shadow_key] = st.session_state[widget_key]
        
    with col2:
        for label, shadow_key in [("Client", "client"), ("Contract Number", "contract_number"),
                                   ("Proposal Number", "proposal_number")]:
            widget_key = f"_w_{shadow_key}"
            _seed(widget_key, shadow_key)
            st.text_input(label, key=widget_key, on_change=_commit_doc_widget, args=(shadow_key,))
            st.session_state[shadow_key] = st.session_state[widget_key]

        if "_w_report_date" not in st.session_state or st.session_state.get("_doc_control_remount"):
            value = st.session_state["report_date"]
            st.session_state["_w_report_date"] = date.fromisoformat(value) if isinstance(value, str) else value
        st.date_input("Date", key="_w_report_date", on_change=_commit_doc_widget, args=("report_date",))
        
        methods = ["Primary Cementing", "Remedial Cementing"]
        method_widget_key = _doc_widget_key("cementing_method")
        _seed(method_widget_key, "cementing_method")
        if st.session_state[method_widget_key] not in methods:
            st.session_state[method_widget_key] = (
                None if st.session_state["cementing_method"] == "Plug Cementing" else methods[0]
            )
        st.selectbox("Cementing Method", methods, key=method_widget_key, on_change=_commit_doc_widget, args=("cementing_method", method_widget_key))
        if st.session_state[method_widget_key] is not None:
            st.session_state["cementing_method"] = st.session_state[method_widget_key]
        else:
            st.warning('Saved Cementing Method "Plug Cementing" is retained. Select a supported method to replace it.')
        
        for label, shadow_key in [("District Phone", "district_phone"), ("Made By", "made_by")]:
            widget_key = f"_w_{shadow_key}"
            _seed(widget_key, shadow_key)
            st.text_input(label, key=widget_key, on_change=_commit_doc_widget, args=(shadow_key,))
            st.session_state[shadow_key] = st.session_state[widget_key]

    # FIX (requested): approval chain + revision marker for a citable formal
    # document, distinct from "Made By" (which names the department/preparer
    # generically, not a specific reviewer chain with accountability).
    st.markdown("---")
    st.subheader("Approval & Revision")
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        _seed("_w_prepared_by", "prepared_by")
        st.text_input("Prepared By", key="_w_prepared_by", on_change=_commit_doc_widget, args=("prepared_by",))
        st.session_state["prepared_by"] = st.session_state["_w_prepared_by"]
    with col_a2:
        _seed("_w_checked_by", "checked_by")
        st.text_input("Checked By", key="_w_checked_by", on_change=_commit_doc_widget, args=("checked_by",))
        st.session_state["checked_by"] = st.session_state["_w_checked_by"]
    with col_a3:
        _seed("_w_approved_by", "approved_by")
        st.text_input("Approved By", key="_w_approved_by", on_change=_commit_doc_widget, args=("approved_by",))
        st.session_state["approved_by"] = st.session_state["_w_approved_by"]
    with col_a4:
        _seed("_w_revision_no", "revision_no")
        st.text_input("Revision No.", key="_w_revision_no", on_change=_commit_doc_widget, args=("revision_no",), help="e.g. '0' for the first issue, '1', '2', ... for later revisions, or 'A'/'B' if your convention uses letters.")
        st.session_state["revision_no"] = st.session_state["_w_revision_no"]

    with st.expander("Request and approval details (optional)"):
        st.markdown("Leave unknown details blank. Select dates using the calendar.")
        detail_columns = st.columns(2)
        for index, (label, shadow_key) in enumerate(DOCUMENT_DETAIL_FIELDS):
            with detail_columns[index % 2]:
                if shadow_key in _DESCRIPTION_FIELDS:
                    _render_description(label, shadow_key)
                    continue
                widget_key = _doc_widget_key(shadow_key)
                _seed(widget_key, shadow_key)
                if shadow_key in DOCUMENT_DATE_FIELDS:
                    st.date_input(label, key=widget_key, on_change=_commit_doc_widget, args=(shadow_key,))
                    if st.session_state[widget_key] is not None:
                        st.session_state[shadow_key] = st.session_state[widget_key].isoformat()
                    elif st.session_state[shadow_key]:
                        st.markdown(f"Saved {label}: {st.session_state[shadow_key]}. Select a calendar date to replace this legacy text.")
                else:
                    st.text_input(label, key=widget_key, on_change=_commit_doc_widget, args=(shadow_key, widget_key))
                    st.session_state[shadow_key] = st.session_state[widget_key]

    # 2. Harmonize backwards-compatible dictionary for export modules
    st.session_state["doc_control"] = {
        "job_type": st.session_state["job_type"],
        "hole_size": st.session_state["hole_size"],
        "field": st.session_state["field"],
        "well_location": st.session_state["well_location"],
        "well_name": st.session_state["well_name"],
        "rig_name": st.session_state["rig_name"],
        "client": st.session_state["client"],
        "contract_number": st.session_state["contract_number"],
        "proposal_number": st.session_state["proposal_number"],
        "date": (st.session_state["report_date"].isoformat() if isinstance(st.session_state["report_date"], (date, datetime))
                 else "" if st.session_state["report_date"] is None else str(st.session_state["report_date"])),
        "cementing_method": st.session_state["cementing_method"],
        "district_phone": st.session_state["district_phone"],
        "made_by": st.session_state["made_by"],
        "prepared_by": st.session_state["prepared_by"],
        "checked_by": st.session_state["checked_by"],
        "approved_by": st.session_state["approved_by"],
        "revision_no": st.session_state["revision_no"]
    }
    st.session_state["doc_control"].update(
        {key: st.session_state[key] for _, key in DOCUMENT_DETAIL_FIELDS}
    )

    st.markdown("---")
    st.info(
        f"**Summary:** {st.session_state['job_type']} (Hole: {st.session_state['hole_size']}) | "
        f"Well: {st.session_state['well_name']} | Rig: {st.session_state['rig_name']} | "
        f"Method: **{st.session_state['cementing_method']}**"
    )
    st.session_state.pop("_doc_control_remount", None)
