# phase_1_doc_control.py
import streamlit as st
import materials_db
from datetime import date, datetime

DOCUMENT_DETAIL_FIELDS = (
    ("Request Date Received", "request_date"),
    ("Request Number", "request_number"),
    ("Request Description", "request_description"),
    ("Prepared Date", "prepared_date"),
    ("Prepared Phone", "prepared_phone"),
    ("Checked Date", "checked_date"),
    ("Checked Phone", "checked_phone"),
    ("Approved Date", "approved_date"),
    ("Approved Phone", "approved_phone"),
    ("Revision Date", "revision_date"),
    ("Revision Description", "revision_description"),
)

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
# which is correct.
#
# Job Type's on_change callback additionally writes the DEPENDENT fields'
# widget keys directly (not just their shadows), because once a widget key
# already holds a value, Streamlit always shows that over anything computed
# from the shadow on the next render — the only way to make hole_size /
# cementing_method visibly jump to their new auto-filled value the instant
# Job Type changes is to set their widget keys in the same callback.

def on_job_type_change():
    """Callback: Synchronously updates suggested hole size and method without UI lag."""
    new_job = st.session_state.get("_w_job_type", materials_db.JOB_TYPES[0])
    new_method = materials_db.get_cementing_method(new_job)

    st.session_state["job_type"] = new_job
    st.session_state["cementing_method"] = new_method
    st.session_state["_w_cementing_method"] = new_method

    # FIX (requested, Level 1 #2): this used to unconditionally overwrite
    # Hole Size with the new Job Type's default, silently discarding
    # anything the operator had typed by hand — e.g. a real injection-string
    # note for a Plug job like "Inside 9 5/8" CSG" (see the field's own help
    # text, which explicitly invites exactly that kind of custom value).
    # Losing it isn't visible until the exported report is reviewed. Now the
    # auto-fill only applies until the operator's first manual edit to this
    # field THIS session (tracked by _hole_size_customized, set by the
    # field's own on_change below — never by this callback, so the auto-fill
    # here can never itself be mistaken for a manual edit).
    if not st.session_state.get("_hole_size_customized", False):
        new_hole = materials_db.DEFAULT_HOLE_SIZES.get(new_job, "12 1/4\"")
        st.session_state["hole_size"] = new_hole
        st.session_state["_w_hole_size"] = new_hole

def _mark_hole_size_customized():
    st.session_state["_hole_size_customized"] = True

def _seed(widget_key, shadow_key):
    """Seed a widget-only key from its shadow, only if the widget key is
    currently absent (first render, or just restored after navigation)."""
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state[shadow_key]

def render():
    st.header("Phase I: Document Control")
    st.markdown("Enter primary operational metadata for the cementing program compliant with NIDC standards.")
    
    # 1. Initialize Flat Canonical State (shadow keys — survive navigation)
    default_values = {
        "job_type": "CSG 20\"",
        "hole_size": "26\"",
        "field": "",
        "well_location": "",
        "well_name": "",
        "rig_name": "",
        "client": "",
        "contract_number": "",
        "proposal_number": "",
        "report_date": date.today(),
        "cementing_method": "Primary Cementing",
        "district_phone": "061-341-43513",
        "made_by": "NIDC Cement Engineering and Planning Department",
        # FIX (requested): a formal engineering document needs an approval
        # chain and a revision marker, not just a single "Made By" line, to
        # go from "internal draft" to "citable record". Revision defaults to
        # "0" (the first issue of a document) rather than blank, since every
        # real document has *some* revision number from the start.
        "prepared_by": "",
        "checked_by": "",
        "approved_by": "",
        "revision_no": "0"
    }
    
    default_values.update({key: "" for _, key in DOCUMENT_DETAIL_FIELDS})
    for key, val in default_values.items():
        if key not in st.session_state:
            st.session_state[key] = val

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
            st.text_input(label, key=widget_key)
            st.session_state[shadow_key] = st.session_state[widget_key]
        
    with col2:
        for label, shadow_key in [("Client", "client"), ("Contract Number", "contract_number"),
                                   ("Proposal Number", "proposal_number")]:
            widget_key = f"_w_{shadow_key}"
            _seed(widget_key, shadow_key)
            st.text_input(label, key=widget_key)
            st.session_state[shadow_key] = st.session_state[widget_key]

        _seed("_w_report_date", "report_date")
        st.date_input("Date", key="_w_report_date")
        st.session_state["report_date"] = st.session_state["_w_report_date"]
        
        methods = ["Primary Cementing", "Remedial Cementing", "Plug Cementing"]
        _seed("_w_cementing_method", "cementing_method")
        if st.session_state["_w_cementing_method"] not in methods:
            st.session_state["_w_cementing_method"] = methods[0]
        st.selectbox("Cementing Method", methods, key="_w_cementing_method")
        st.session_state["cementing_method"] = st.session_state["_w_cementing_method"]
        
        for label, shadow_key in [("District Phone", "district_phone"), ("Made By", "made_by")]:
            widget_key = f"_w_{shadow_key}"
            _seed(widget_key, shadow_key)
            st.text_input(label, key=widget_key)
            st.session_state[shadow_key] = st.session_state[widget_key]

    # FIX (requested): approval chain + revision marker for a citable formal
    # document, distinct from "Made By" (which names the department/preparer
    # generically, not a specific reviewer chain with accountability).
    st.markdown("---")
    st.subheader("Approval & Revision")
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        _seed("_w_prepared_by", "prepared_by")
        st.text_input("Prepared By", key="_w_prepared_by")
        st.session_state["prepared_by"] = st.session_state["_w_prepared_by"]
    with col_a2:
        _seed("_w_checked_by", "checked_by")
        st.text_input("Checked By", key="_w_checked_by")
        st.session_state["checked_by"] = st.session_state["_w_checked_by"]
    with col_a3:
        _seed("_w_approved_by", "approved_by")
        st.text_input("Approved By", key="_w_approved_by")
        st.session_state["approved_by"] = st.session_state["_w_approved_by"]
    with col_a4:
        _seed("_w_revision_no", "revision_no")
        st.text_input("Revision No.", key="_w_revision_no", help="e.g. '0' for the first issue, '1', '2', ... for later revisions, or 'A'/'B' if your convention uses letters.")
        st.session_state["revision_no"] = st.session_state["_w_revision_no"]

    with st.expander("Request and approval details (optional)"):
        st.caption("Leave unknown details blank. Dates may use your project's calendar and format.")
        detail_columns = st.columns(2)
        for index, (label, shadow_key) in enumerate(DOCUMENT_DETAIL_FIELDS):
            with detail_columns[index % 2]:
                widget_key = f"_w_{shadow_key}"
                _seed(widget_key, shadow_key)
                st.text_input(label, key=widget_key)
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
