# phase_2_3_well_data.py
import streamlit as st
import pandas as pd
import math
import materials_db
from placement import hardware_choices, target_descriptions, HOST_DESCRIPTIONS, measured_depth, EXCESS_FIELDS
from bhct_helper import M_TO_FT, suggest_bhct
from project_state import fingerprint, WELL_DATA_DEFAULTS, refresh_well_derived, invalidate_document
from project_io import normalize_hardware_text_columns
from input_guard import repair_invalid_inputs
from editor_state import persistent_data_editor
from engineering_tools import parse_effective_numeric, parse_fractional_size, require_bhsp_density

HARDWARE_COLUMNS = ["Description", "MD (m)", "Size (in)", "ID (in)", "Joint (m)", "Weight (ppf)", "Grade", "Collapse (psi)", "Burst (psi)"]
MUD_TYPES = ["WBM", "OBM"]

def _seed(widget_key, shadow_key):
    """Send the committed value on every mount, including correction reruns.

    Callbacks commit edits before render. Seeding only an absent key leaves
    nullable controls with a blank frontend default on subsequent remounts.
    """
    st.session_state[widget_key] = st.session_state[shadow_key]

def get_well_data() -> dict:
    """
    Clean Helper/Getter function for Phase X export and external consumers.
    Eliminates redundant state duplication while maintaining full backwards compatibility.
    """
    return {**{field: st.session_state.get(field, default)
               for field, default in WELL_DATA_DEFAULTS.items()},
            **{field: st.session_state.get(field)
               for field in ("effective_mud_density", "effective_pv", "effective_yp")}}


def _commit_well_widget(field):
    """Keep the flat input and export-facing well snapshot in step on blur."""
    st.session_state[field] = st.session_state[f"_w_{field}"]
    if field in ("geo_gradient", "bhsp"):
        st.session_state["well_auto_fields"][field] = False
    for source, effective, default in (("mud_density", "effective_mud_density", None),
                                       ("plastic_viscosity", "effective_pv", None),
                                       ("yield_point", "effective_yp", None)):
        if field == source:
            st.session_state[effective] = parse_effective_numeric(st.session_state[field], default=default)
    st.session_state["well_data"] = get_well_data()
    invalidate_document(st.session_state)


def _bhct_suggestion():
    """Advisory correlation in feet; only a BHCT regime may be applied."""
    try:
        tvd_m = float(st.session_state.get("geo_tvd"))
        bhst = float(st.session_state.get("bhst"))
        if tvd_m <= 0 or bhst <= 80:
            return None
        suggestion = suggest_bhct(tvd_ft=tvd_m * M_TO_FT, max_rbhest_f=bhst)
        return (tvd_m, suggestion) if suggestion["kind"] == "BHCT" else None
    except (TypeError, ValueError, OverflowError):
        return None


def _apply_bhct_suggestion():
    suggestion = _bhct_suggestion()
    if suggestion is None:
        return
    value = float(max(60, min(400, round(suggestion[1]["temp_degF"]))))
    st.session_state["_w_bhct"] = st.session_state["bhct"] = value
    st.session_state["well_data"] = get_well_data()
    invalidate_document(st.session_state)


def _commit_placement(field, widget_key):
    placement = st.session_state.setdefault("placement_config", {})
    placement.update(job_type=st.session_state.get("job_type", ""), **{field: st.session_state[widget_key]})
    if field == "target_row" and placement[field] == "__manual__":
        placement.setdefault("manual_depth_m", 0.0)  # Existing "not entered" value.


def render():
    st.header("Phase II & III: Well Data")
    st.markdown("Configure tubular hardware, drilling fluid properties, and geothermal temperature profile.")
    
    # 1. Canonical State Initialization (shadow keys — survive navigation)
    auto_fields = st.session_state.setdefault("well_auto_fields", {})
    for field in ("geo_gradient", "bhsp"):
        # Restored explicit values are manual unless saved provenance says auto.
        auto_fields.setdefault(field, field not in st.session_state)
    defaults = WELL_DATA_DEFAULTS
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    bounded = [(st.session_state, field, label, minimum, None, integer)
               for field, label, minimum, integer in (
                   ("geo_md", "MD (m)", 0.0, False),
                   ("geo_tvd", "TVD (m)", 0.0, False),
                   ("bhst", "BHST (°F)", 0, True),
                   ("geo_gradient", "Temperature gradient", 0.0, False))
               if st.session_state.get(field) is not None]
    if st.session_state.get("bhct") is not None:
        bounded.append((st.session_state, "bhct", "BHCT (°F)", 60.0, 400.0, False))
    placement = st.session_state.get("placement_config", {})
    if (placement.get("job_type") == st.session_state.get("job_type")
            and placement.get("target_row") == "__manual__"):
        bounded.append((placement, "manual_depth_m", "Measured target depth (m MD)", 0.0, None, False))
    if placement.get("job_type") == st.session_state.get("job_type"):
        bounded.extend((placement, field, label, 0.0, None, False)
                       for field, label, _ in EXCESS_FIELDS if placement.get(field) is not None)
    if repair_invalid_inputs(bounded, f"phase2_{st.session_state.get('last_loaded_hash', 'new')}"):
        return
    refresh_well_derived(st.session_state)
    for field in ("geo_gradient", "bhsp"):
        if auto_fields[field]:
            st.session_state[f"_w_{field}"] = st.session_state[field]
        
    # 2. Hardware Table Initialization
    # FIX (requested, round 2): the previous fix (below-still-applies) stopped
    # the table from refilling itself when the operator cleared it *during* a
    # session. But the very first time a truly new session starts (server
    # process just launched — key not in st.session_state at all yet), this
    # block still ran and seeded the same hardcoded "Previous Casing / 9 5/8 /
    # L-80 / ..." example row every single time. Since a full close-and-restart
    # of the browser/terminal always produces exactly that same fresh session,
    # this literal row reappeared and looked identical to "old data surviving
    # a restart" even though nothing was ever actually persisted to disk (no
    # file I/O exists anywhere in this app — verified). It was simply a
    # built-in starter/example row, recreated identically every fresh launch.
    # Removed: a brand-new session (or a fresh "Start New / Clear All Data")
    # now starts with a genuinely empty table. Loading a saved project is
    # unaffected — this initializer only runs when the key is fully absent,
    # and the project-load path in main.py restores hardware_table directly
    # from the JSON before this ever gets a chance to run.
    if "hardware_table" not in st.session_state or not isinstance(st.session_state["hardware_table"], pd.DataFrame):
        st.session_state["hardware_table"] = pd.DataFrame(columns=HARDWARE_COLUMNS)
    
    # TextColumn input must be normalized before the editor is mounted.
    normalize_hardware_text_columns(st.session_state["hardware_table"])
    normalize_hardware_text_columns(st.session_state.get("hardware_editor_draft"))

    # Ensure float typing for numeric columns
    for col in ["ID (in)", "Joint (m)", "Weight (ppf)", "Collapse (psi)", "Burst (psi)"]:
        st.session_state["hardware_table"][col] = pd.to_numeric(
            st.session_state["hardware_table"][col], errors="coerce"
        ).fillna(0.0).astype(float)

    # --- SECTION 1: TUBULAR AND CASING HARDWARE ---
    st.subheader("1. Tubular and Casing Hardware")
    st.caption("**Guide:** Double-click any cell to edit. For **Open Hole Size**, Weight is automatically zeroed and ID serves as Bit Size.")
    
    # Hold unfinished grid rows separately: an MD entered before Description
    # is a real operator edit, but must not become a hardware/export row yet.
    hardware_draft = st.session_state.get("hardware_editor_draft")
    editor_data = (hardware_draft if isinstance(hardware_draft, pd.DataFrame)
                   else st.session_state["hardware_table"])
    hardware_revision_key = "_editor_hardware_revision"
    edited_df = persistent_data_editor(
        editor_data,
        persist_to=("hardware_editor_draft", None),
        column_config={
            "Description": st.column_config.SelectboxColumn(
                "Description",
                options=materials_db.HARDWARE_DESCRIPTIONS,
                default="Casing",
                required=True,
                width="medium"
            ),
            "MD (m)": st.column_config.TextColumn(
                "MD (m)",
                help="Single depth (e.g. 3927.0) or interval (e.g. 1200.0-2816.0)",
                default="0.0",
                required=True
            ),
            "Size (in)": st.column_config.TextColumn(
                "Size (in)",
                help="e.g. 20, 13 3/8, 9 5/8, 7, 5",
                default="",
                required=False
            ),
            "ID (in)": st.column_config.NumberColumn(
                "ID (in)",
                help="Inner Diameter with 3 decimal places (e.g. 8.535)",
                format="%.3f",
                step=0.001,
                default=0.000,
                required=False
            ),
            "Joint (m)": st.column_config.NumberColumn(
                "Joint (m)",
                help="Joint / single-pipe length in meters (e.g. 12.2). 0 for Open Hole.",
                format="%.1f",
                step=0.1,
                default=12.2,
                required=False
            ),
            "Weight (ppf)": st.column_config.NumberColumn(
                "Weight (ppf)",
                help="Linear weight in lb/ft (0 for Open Hole)",
                format="%.1f",
                step=0.5,
                default=0.0,
                required=False
            ),
            "Grade": st.column_config.SelectboxColumn(
                "Grade",
                options=["-", "J-55", "K-55", "N-80", "L-80", "C-90", "T-95", "P-110", "Q-125", "HSM-1"],
                default="-",
                required=False
            ),
            "Collapse (psi)": st.column_config.NumberColumn(
                "Collapse (psi)",
                help="Collapse rating in psi (0 / blank for Open Hole)",
                format="%.0f",
                step=10.0,
                default=0.0,
                required=False
            ),
            "Burst (psi)": st.column_config.NumberColumn(
                "Burst (psi)",
                help="Burst rating in psi (0 / blank for Open Hole)",
                format="%.0f",
                step=10.0,
                default=0.0,
                required=False
            )
        },
        num_rows="dynamic",
        key=f"_editor_hardware_{st.session_state.get(hardware_revision_key, 0)}",
        width='stretch'
    )

    pending_rows = edited_df.copy(deep=True)
    cleaned_rows = []
    dimension_warnings = []
    corrected_hardware = False
    incomplete_hardware = False
    
    for idx, row in edited_df.iterrows():
        desc = str(row.get("Description") or "").strip()
        if not desc or desc in ["None", "nan"]:
            incomplete_hardware = True
            continue

        def hardware_number(field):
            raw = row.get(field)
            numeric = pd.to_numeric(raw, errors="coerce")
            if pd.isna(numeric) or not math.isfinite(float(numeric)):
                if raw is not None and str(raw).strip() not in ("", "nan", "None"):
                    dimension_warnings.append(f"Row {idx+1} ({desc}): {field} is not a finite number; correct the cell.")
                return 0.0
            return float(numeric)

        id_val = hardware_number("ID (in)")
        joint_val = hardware_number("Joint (m)")
        wt_val = hardware_number("Weight (ppf)")
        grade_clean = str(row.get("Grade") or "-").strip()
        collapse_val = hardware_number("Collapse (psi)")
        burst_val = hardware_number("Burst (psi)")
        size_str = str(row.get("Size (in)") or "").strip()
        
        # Guardrail: Check ID vs OD
        if desc != "Open Hole Size" and size_str:
            od_val = parse_fractional_size(size_str)
            if od_val > 0.0 and id_val >= od_val:
                dimension_warnings.append(f"Row {idx+1} ({desc}): ID ({id_val}\") is equal to or larger than Size ({size_str}\").")
        
        # Open hole specific rules
        if desc == "Open Hole Size":
            if (joint_val != 0.0 or wt_val != 0.0 or grade_clean != "-"
                    or collapse_val != 0.0 or burst_val != 0.0):
                corrected_hardware = True
                for column in ("Joint (m)", "Weight (ppf)", "Collapse (psi)", "Burst (psi)"):
                    pending_rows.at[idx, column] = 0.0
                pending_rows.at[idx, "Grade"] = "-"
            wt_val = 0.0
            grade_clean = "-"
            joint_val = 0.0
            collapse_val = 0.0
            burst_val = 0.0
            
        raw_depth = row.get("MD (m)")
        cleaned_rows.append({
            "Description": desc,
            # A blank depth in an older, unfinished row is still blank. It
            # must not turn into an invented zero when this phase first opens.
            "MD (m)": "" if raw_depth is None or pd.isna(raw_depth) else str(raw_depth),
            "Size (in)": size_str,
            "ID (in)": id_val,
            "Joint (m)": joint_val,
            "Weight (ppf)": wt_val,
            "Grade": grade_clean,
            "Collapse (psi)": collapse_val,
            "Burst (psi)": burst_val
        })
        
    st.session_state["hardware_table"] = pd.DataFrame(cleaned_rows, columns=HARDWARE_COLUMNS)
    if incomplete_hardware:
        st.session_state["hardware_editor_draft"] = pending_rows
    else:
        st.session_state.pop("hardware_editor_draft", None)
    if corrected_hardware:
        # Reflect enforced Open Hole zeroes in the editor itself. Ordinary
        # edits retain the same widget identity and remain visible immediately.
        st.session_state[hardware_revision_key] = st.session_state.get(hardware_revision_key, 0) + 1
        st.rerun()

    for warn in dimension_warnings:
        st.warning(f"⚠ **Tubular Geometry Alert:** {warn}")

    st.subheader("Cement Placement Reference")
    job_type = st.session_state.get("job_type", "")
    placement = st.session_state.setdefault("placement_config", {})
    if placement.get("job_type") != job_type:
        placement.clear()
        placement["job_type"] = job_type
    load_sig = str(st.session_state.get("last_loaded_hash", "default_project"))
    choice_key = f"_placement_target_{fingerprint(job_type)[:10]}_{load_sig}"
    targets = hardware_choices(st.session_state["hardware_table"], target_descriptions(job_type))
    options = ["", *targets, "__manual__"]
    selected = placement.get("target_row", "")
    selected = selected if selected in options else ""
    placement["target_row"] = st.selectbox(
        "Target shoe / treatment depth source",
        options,
        index=options.index(selected),
        format_func=lambda token: ("Select a hardware row or enter a measured depth" if not token
                                   else "Enter measured depth manually" if token == "__manual__"
                                   else targets[token]["label"]),
        key=choice_key,
        on_change=_commit_placement, args=("target_row", choice_key),
        help="Choose the actual target row for this job. Changing its MD invalidates the previous selection."
    )
    if placement["target_row"] == "__manual__":
        placement["manual_depth_m"] = st.number_input(
            "Measured target depth (m MD)", min_value=0.0, step=1.0,
            value=float(placement.get("manual_depth_m") or 0.0),
            key=f"_placement_manual_depth_{load_sig}",
            on_change=_commit_placement, args=("manual_depth_m", f"_placement_manual_depth_{load_sig}"),
            help="0 means not entered; only a measured job-specific depth is printed."
        )
    if "TIE BACK" in job_type.upper():
        hosts = hardware_choices(st.session_state["hardware_table"], HOST_DESCRIPTIONS)
        host_options = ["", *hosts]
        host = placement.get("host_row", "")
        host = host if host in host_options else ""
        placement["host_row"] = st.selectbox(
            "Tie-back host (the existing casing / liner)", host_options,
            index=host_options.index(host),
            format_func=lambda token: hosts[token]["label"] if token else "Select the actual host",
            key=f"_placement_host_{fingerprint(job_type)[:10]}_{load_sig}",
            on_change=_commit_placement, args=("host_row", f"_placement_host_{fingerprint(job_type)[:10]}_{load_sig}")
        )
    for field, label, _ in EXCESS_FIELDS:
        widget_key = f"_placement_{field}_{load_sig}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = placement.get(field)
        placement[field] = st.number_input(
            label, min_value=0.0, step=0.1, value=None,
            key=widget_key, on_change=_commit_placement, args=(field, widget_key),
            help="Enter percentage points (25 means 25%). Leave blank if not supplied."
        )
    if placement["target_row"] == "__manual__" and measured_depth(placement.get("manual_depth_m")) is None:
        st.warning("Enter the actual target depth before citing it in the executive summary.")

    st.markdown("---")
    
    # --- SECTION 2: DRILLING FLUID DATA ---
    st.subheader("2. Drilling Fluid Data")
    
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        _seed("_w_mud_type", "mud_type")
        if st.session_state["_w_mud_type"] not in MUD_TYPES:
            st.session_state["_w_mud_type"] = MUD_TYPES[0]
        st.selectbox("Mud Type", MUD_TYPES, key="_w_mud_type", on_change=_commit_well_widget, args=("mud_type",))
        st.session_state["mud_type"] = st.session_state["_w_mud_type"]
        
    with col_m2:
        _seed("_w_mud_density", "mud_density")
        st.text_input(
            "Mud Weight (pcf)", 
            key="_w_mud_density", on_change=_commit_well_widget, args=("mud_density",),
            help="Single density (e.g. 82.0) or range (e.g. 80-82)"
        )
        st.session_state["mud_density"] = st.session_state["_w_mud_density"]
        # General density keeps its mean; only automatic BHSP uses the upper end.
        _eff_md = parse_effective_numeric(st.session_state["mud_density"], default=None)
        if _eff_md is not None:
            is_range = any(c in st.session_state["mud_density"] for c in "-/")
            density_caption = f"↳ General effective density: **{_eff_md:.1f} pcf**" + (" (mean of range)" if is_range else "")
            if is_range:
                try:
                    bhsp_density = require_bhsp_density(st.session_state["mud_density"])
                except ValueError:
                    pass  # Invalid ranges have no valid BHSP basis to display.
                else:
                    density_caption += f"; ↳ BHSP density basis: **{bhsp_density:.1f} pcf** (upper end of range)"
            st.caption(density_caption)
        
    with col_m3:
        _seed("_w_plastic_viscosity", "plastic_viscosity")
        st.text_input(
            "Plastic Viscosity (cp)", 
            key="_w_plastic_viscosity", on_change=_commit_well_widget, args=("plastic_viscosity",),
            help="e.g. 45 or 45-50"
        )
        st.session_state["plastic_viscosity"] = st.session_state["_w_plastic_viscosity"]
        _eff_pv = parse_effective_numeric(st.session_state["plastic_viscosity"], default=None)
        if _eff_pv is not None:
            st.caption(f"↳ Used in calculations as: **{_eff_pv:.1f} cp**" + (" (mean of range)" if any(c in st.session_state["plastic_viscosity"] for c in "-/") else ""))
        
    with col_m4:
        _seed("_w_yield_point", "yield_point")
        st.text_input(
            "Yield Point (lb/100ft²)", 
            key="_w_yield_point", on_change=_commit_well_widget, args=("yield_point",),
            help="e.g. 15 or 10-20"
        )
        st.session_state["yield_point"] = st.session_state["_w_yield_point"]
        _eff_yp = parse_effective_numeric(st.session_state["yield_point"], default=None)
        if _eff_yp is not None:
            st.caption(f"↳ Used in calculations as: **{_eff_yp:.1f} lb/100ft²**" + (" (mean of range)" if any(c in st.session_state["yield_point"] for c in "-/") else ""))

    # Clean bridge for mathematical models downstream
    st.session_state["effective_mud_density"] = parse_effective_numeric(st.session_state["mud_density"], default=None)
    st.session_state["effective_pv"] = parse_effective_numeric(st.session_state["plastic_viscosity"], default=None)
    st.session_state["effective_yp"] = parse_effective_numeric(st.session_state["yield_point"], default=None)

    st.markdown("---")
    
    # --- SECTION 3: GEOTHERMAL TEMPERATURE PROFILE ---
    st.subheader("3. Geothermal Temperature Profile")
    st.caption("NOTE 1: The Calculated Temperature is based on True Vertical Depth.")
    
    col_g1, col_g2, col_g3, col_bhct, col_g4, col_g5 = st.columns(6)
    with col_g1:
        _seed("_w_geo_md", "geo_md")
        st.number_input("MD (m)", value=None, min_value=0.0, step=10.0, format="%.1f", key="_w_geo_md", on_change=_commit_well_widget, args=("geo_md",))
        st.session_state["geo_md"] = st.session_state["_w_geo_md"]
    with col_g2:
        _seed("_w_geo_tvd", "geo_tvd")
        st.number_input("TVD (m)", value=None, min_value=0.0, step=10.0, format="%.1f", key="_w_geo_tvd", on_change=_commit_well_widget, args=("geo_tvd",))
        st.session_state["geo_tvd"] = st.session_state["_w_geo_tvd"]
    with col_g3:
        _seed("_w_bhst", "bhst")
        st.number_input("BHST (degF)", value=None, min_value=0, step=1, key="_w_bhst", on_change=_commit_well_widget, args=("bhst",))
        st.session_state["bhst"] = st.session_state["_w_bhst"]
    with col_bhct:
        _seed("_w_bhct", "bhct")
        st.number_input("BHCT (degF)", value=None, min_value=60.0, max_value=400.0,
                        step=5.0, key="_w_bhct", on_change=_commit_well_widget, args=("bhct",),
                        help="Shared well circulating temperature for every fluid and slurry.")
        suggestion = _bhct_suggestion()
        if suggestion is not None:
            tvd_m, result = suggestion
            raw = round(result["temp_degF"])
            applied = max(60, min(400, raw))
            clamp = " (clamped to 60–400 °F)" if raw != applied else ""
            st.caption(f"Suggested BHCT ≈ {raw} °F{clamp} — i-Handbook/API 10B, TVD {tvd_m * M_TO_FT:,.0f} ft.")
            st.button(f"Apply {applied} °F", key="_apply_well_bhct", on_click=_apply_bhct_suggestion,
                      help="Explicitly apply the advisory estimate to the single well BHCT input.")
        if (st.session_state["bhct"] is not None and st.session_state["bhst"] is not None
                and st.session_state["bhct"] > st.session_state["bhst"]):
            st.error("BHCT cannot exceed BHST; correct the well temperature before Lab review.")
    with col_g4:
        _seed("_w_geo_gradient", "geo_gradient")
        st.number_input("Gradient (degF/100ft)", value=None, min_value=0.0, step=0.01, format="%.2f", key="_w_geo_gradient", on_change=_commit_well_widget, args=("geo_gradient",))
        st.session_state["geo_gradient"] = st.session_state["_w_geo_gradient"]
    with col_g5:
        _seed("_w_bhsp", "bhsp")
        st.text_input(
            "BHSP (psi)", key="_w_bhsp", on_change=_commit_well_widget, args=("bhsp",),
            help="Bottom Hole Static/Shut-in Pressure. Free text — supports compound values as shown in real reports (e.g. '7300+1000')."
        )
        st.session_state["bhsp"] = st.session_state["_w_bhsp"]

    # Geothermal & Well Path Guardrails
    if (st.session_state["geo_tvd"] is not None and st.session_state["geo_md"] is not None
            and st.session_state["geo_tvd"] > st.session_state["geo_md"]):
        st.error(f"✕ **Physical Inconsistency:** TVD ({st.session_state['geo_tvd']:.1f} m) cannot exceed MD ({st.session_state['geo_md']:.1f} m).")
        
    if st.session_state["bhst"] is not None and st.session_state["bhst"] < 80:
        st.warning("⚠ **Thermal Alert:** BHST appears unusually low for deep well operations.")

    st.session_state["well_data"] = get_well_data()
