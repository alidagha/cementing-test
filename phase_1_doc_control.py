# phase_1_doc_control.py
import streamlit as st
import materials_db
from datetime import date, datetime
from project_state import DOC_CONTROL_DEFAULTS, DOCUMENT_DETAIL_FIELDS

DOCUMENT_DATE_FIELDS = ("request_date", "prepared_date", "approved_date", "revision_date")

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
#
# Job Type's on_change callback additionally writes the DEPENDENT fields'
# widget keys directly (not just their shadows), because once a widget key
# already holds a value, Streamlit always shows that over anything computed
# from the shadow on the next render — the only way to make hole_size /
# cementing_method visibly jump to their new auto-filled value the instant
# Job Type changes is to set their widget keys in the same callback.

def _commit_doc_widget(field):
    """Commit metadata and its export snapshot before navigation unmounts it."""
    value = st.session_state[f"_w_{field}"]
    if field in DOCUMENT_DATE_FIELDS:
        value = value.isoformat() if isinstance(value, (date, datetime)) else ""
    st.session_state[field] = value
    if field == "report_date":
        value = value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    st.session_state.setdefault("doc_control", {})["date" if field == "report_date" else field] = value


def on_job_type_change():
    """Callback: Synchronously updates suggested hole size and method without UI lag."""
    new_job = st.session_state.get("_w_job_type", materials_db.JOB_TYPES[0])
    new_method = materials_db.get_cementing_method(new_job)
    # Legacy tops have no owner marker until their original job is changed.
    for params in st.session_state.get("cement_params", {}).values():
        if params.get("top_job_type") is None:
            params["top_job_type"] = st.session_state["job_type"]

    _commit_doc_widget("job_type")
    st.session_state["cementing_method"] = new_method
    st.session_state["_w_cementing_method"] = new_method
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
        st.session_state["_w_hole_size"] = new_hole
        _commit_doc_widget("hole_size")

def _mark_hole_size_customized():
    st.session_state["hole_size_customized"] = True
    _commit_doc_widget("hole_size")

def _seed(widget_key, shadow_key):
    """Seed a widget-only key from its shadow, only if the widget key is
    currently absent (first render, or just restored after navigation)."""
    if widget_key not in st.session_state:
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
    default_values = dict(DOC_CONTROL_DEFAULTS, report_date=date.today())
    for key, val in default_values.items():
        if key not in st.session_state:
            st.session_state[key] = val

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
        st.selectbox(
            "Job Type", 
            materials_db.JOB_TYPES, 
            key="_w_job_type",
            on_change=on_job_type_change
        )
        st.session_state["job_type"] = st.session_state["_w_job_type"]
        
        # Hole Size (Fully unconstrained free-text with helper guidance)
        _seed("_w_hole_size", "hole_size")
        st.text_input(
            "Hole Size (in)", 
            key="_w_hole_size",
            on_change=_mark_hole_size_customized,
            help="Enter hole diameter (e.g. 26\", 12 1/4\", 8 1/2\") or injection string context for plugs (e.g. Inside 9 5/8\" CSG)."
        )
        st.session_state["hole_size"] = st.session_state["_w_hole_size"]
        st.caption(f"↳ Default for {st.session_state['job_type']}: {materials_db.DEFAULT_HOLE_SIZES.get(st.session_state['job_type'], '—')} (your own value is kept once edited)")
        
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

        _seed("_w_report_date", "report_date")
        st.date_input("Date", key="_w_report_date", on_change=_commit_doc_widget, args=("report_date",))
        st.session_state["report_date"] = st.session_state["_w_report_date"]
        
        methods = ["Primary Cementing", "Remedial Cementing"]
        _seed("_w_cementing_method", "cementing_method")
        if st.session_state["_w_cementing_method"] not in methods:
            st.session_state["_w_cementing_method"] = (
                None if st.session_state["cementing_method"] == "Plug Cementing" else methods[0]
            )
        st.selectbox("Cementing Method", methods, key="_w_cementing_method", on_change=_commit_doc_widget, args=("cementing_method",))
        if st.session_state["_w_cementing_method"] is not None:
            st.session_state["cementing_method"] = st.session_state["_w_cementing_method"]
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
        st.caption("Leave unknown details blank. Select dates using the calendar.")
        detail_columns = st.columns(2)
        for index, (label, shadow_key) in enumerate(DOCUMENT_DETAIL_FIELDS):
            with detail_columns[index % 2]:
                widget_key = f"_w_{shadow_key}"
                _seed(widget_key, shadow_key)
                if shadow_key in DOCUMENT_DATE_FIELDS:
                    st.date_input(label, key=widget_key, on_change=_commit_doc_widget, args=(shadow_key,))
                    if st.session_state[widget_key] is not None:
                        st.session_state[shadow_key] = st.session_state[widget_key].isoformat()
                    elif st.session_state[shadow_key]:
                        st.caption(f"Saved {label}: {st.session_state[shadow_key]}. Select a calendar date to replace this legacy text.")
                else:
                    st.text_input(label, key=widget_key, on_change=_commit_doc_widget, args=(shadow_key,))
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
        "date": st.session_state["report_date"].isoformat() if isinstance(st.session_state["report_date"], (date, datetime)) else str(st.session_state["report_date"]),
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
