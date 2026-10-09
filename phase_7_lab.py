# phase_7_lab.py
import streamlit as st
import pandas as pd
import re
import materials_db
from rheology import RPM_ORDER, RHEOLOGY_DATASETS, new_rheology_dataset, build_rheology
from project_state import invalidate_document
from project_state import lab_source_signature
from engineering_tools import lab_review_signature, lab_temperature_valid, validate_thickening_test, validate_lab_collection_results, THICKENING_TEST_FIELDS, COMPRESSIVE_TEST_FIELDS, compressive_inputs, validate_compressive_test
from input_guard import repair_invalid_inputs
from editor_state import persistent_data_editor
# IH-15: i-Handbook / API 10B BHCT suggestion (standalone additive module).
# The read-only engine (engineering_tools.py / materials_db.py) is untouched;
# the manual BHCT entry and lab_temperature_valid remain the only authority.
from bhct_helper import M_TO_FT, suggest_bhct
from engineering_tools import (
    clean_number,
    require_positive_density,
    require_nonnegative_number,
    validate_lab_masses,
    calculate_slurry_from_components,
    resolve_additive_density,
    resolve_cement_sg,
    require_additive_identity,
    resolve_physical_state,
    normalize_additive_mix,
    is_salt_additive
)

LAB_GRID_COLUMNS = ["Material", "Concentration", "Unit", "Mass", "Lot No"]


def _commit_lab_qc(slurry: str, field: str, widget_key: str) -> None:
    """BUG-01 (same protection as Phase IV's _commit_fluid_widget): commit the
    last widget edit into lab_qc_params before a phase-switch rerun can
    garbage-collect this widget. Critical for the free-text Thickening Time
    input, whose blurred edit is otherwise silently lost on navigation."""
    value = st.session_state[widget_key]
    entry = st.session_state.get("lab_qc_params", {}).get(slurry)
    if isinstance(entry, dict):
        entry[field] = value
        if field in {key for key, _, _ in THICKENING_TEST_FIELDS}:
            invalidate_document(st.session_state)


def _render_thickening_test(slurry, qc, load_sig):
    st.markdown("#### Thickening Time Test")
    columns = st.columns(3)
    for i, (field, label, kind) in enumerate(THICKENING_TEST_FIELDS):
        key = f"_qc_{field}_{get_slurry_key(slurry, 'in')}_{load_sig}"
        if key not in st.session_state:
            value = qc.get(field)
            st.session_state[key] = (float(value) if value is not None else None) if kind == "number" else ("" if value is None else str(value))
        args = (slurry, field, key)
        if kind == "number":
            columns[i % 3].number_input(f"{label} - {slurry}", value=None, key=key,
                                       on_change=_commit_lab_qc, args=args,
                                       help="Finite numeric cell value; no integer-only or range restriction.")
        else:
            help_text = ("Wall-clock start, 00:00–23:59 or exactly 24:00." if kind == "clock" else
                         "Elapsed test time, 00:00–24:00." if kind == "elapsed" else
                         "Elapsed milestone time, greater than 00:00 and at most 24:00.")
            columns[i % 3].text_input(f"{label} (HH:MM) - {slurry}", key=key,
                                     on_change=_commit_lab_qc, args=args, help=help_text)
    try:
        validate_thickening_test(qc)
        return True
    except ValueError as exc:
        st.caption(f"{slurry}: {exc}. Unfinished values remain saved.")
        return False

def _commit_compressive(slurry, test, field, key):
    st.session_state["lab_qc_params"][slurry]["compressive"][test][field] = st.session_state[key]
    invalidate_document(st.session_state)


def _render_compressive(slurry, qc, load_sig, bhst, bhsp):
    st.markdown("#### Compressive Strength Test")
    data = compressive_inputs(qc)
    for test, title in (("uca", "UCA"), ("crush", "Crush Test")):
        row = data[test]
        prefix = f"_comp_{get_slurry_key(slurry, '').strip('_')}_{test}_"
        key = prefix + "selected_" + load_sig
        if key not in st.session_state:
            st.session_state[key] = row["selected"]
        st.checkbox(f"{title} - {slurry}", key=key, on_change=_commit_compressive,
                    args=(slurry, test, "selected", key))
        if not row["selected"]:
            continue
        st.caption(f"{title}: Temp = {bhst} °F (BHST); Pressure = {bhsp} psi (BHSP)")
        columns = st.columns(len(COMPRESSIVE_TEST_FIELDS[test]))
        for column, (field, label) in zip(columns, COMPRESSIVE_TEST_FIELDS[test]):
            key = prefix + field + "_" + load_sig
            if key not in st.session_state:
                value = row[field]
                st.session_state[key] = None if value in (None, "") else float(value)
            column.number_input(f"{label} - {slurry}", value=None, key=key, format="%.17g",
                                on_change=_commit_compressive, args=(slurry, test, field, key),
                                help="Measured finite nonnegative value; blank is an unfinished draft.")
    try:
        payload = validate_compressive_test(qc)
        for test, title in (("uca", "UCA"), ("crush", "Crush Test")):
            if payload[test]["selected"]:
                st.success(f"{title} result: {payload[test]['result']} psi")
        return payload, True
    except ValueError as exc:
        st.caption(f"{slurry}: {exc}. Unfinished values remain saved.")
        return {}, False


def _commit_rheology(slurry, dataset, field, widget_key, rpm=None):
    row = st.session_state["lab_qc_params"][slurry]["rheology"][dataset]
    if rpm is None:
        row[field] = st.session_state[widget_key]
    else:
        row["readings"][str(rpm)] = st.session_state[widget_key]
    invalidate_document(st.session_state)


def _render_rheology(slurry, qc, load_sig):
    st.markdown("#### Rheology Test — Fann 35 / R1B1 / Spring 1.0")
    data = qc.setdefault("rheology", {})
    token = get_slurry_key(slurry, "").strip("_")
    for dataset, label in RHEOLOGY_DATASETS:
        row = data.setdefault(dataset, new_rheology_dataset())
        prefix = f"_rheo_{token}_{dataset}_"
        key = prefix + "selected_" + load_sig
        if key not in st.session_state:
            st.session_state[key] = row.get("selected", False)
        st.checkbox(f"{label} - {slurry}", key=key, on_change=_commit_rheology,
                    args=(slurry, dataset, "selected", key))
        if not row.get("selected", False):
            continue
        condition = "Surface" if dataset == "surface_down" else f"{qc.get('bhct')} °F (BHCT)"
        st.caption(f"{label}: {condition}")
        readings = row.setdefault("readings", {})
        columns = st.columns(7)
        for column, rpm in zip(columns, RPM_ORDER):
            key = prefix + str(rpm) + "_" + load_sig
            if key not in st.session_state:
                value = readings.get(str(rpm), "")
                st.session_state[key] = "" if value is None else str(value)
            column.text_input(f"{rpm} RPM - {label} - {slurry}", key=key,
                              on_change=_commit_rheology,
                              args=(slurry, dataset, "readings", key, rpm))
        columns = st.columns(2)
        for column, field, gel_label in zip(columns, ("gel_10_sec", "gel_10_min"), ("10 Sec Gel", "10 Min Gel")):
            key = prefix + field + "_" + load_sig
            if key not in st.session_state:
                value = row.get(field, "")
                st.session_state[key] = "" if value is None else str(value)
            column.text_input(f"{gel_label} - {label} - {slurry}", key=key,
                              on_change=_commit_rheology,
                              args=(slurry, dataset, field, key),
                              help="Enter a finite measured number or '-'. Blank is unfinished.")
    try:
        result, issues = build_rheology(qc)
    except ValueError as exc:
        st.warning(str(exc))
        return {}, [str(exc)]
    for dataset, label in RHEOLOGY_DATASETS:
        row = result[dataset]
        if row["selected"] and row["pv_cp"] is not None:
            st.caption(label)
            columns = st.columns(3)
            for column, title, field, decimals in zip(columns, ("PV (cP)", "Ty (lbf/100ft²)", "IOD"),
                                                       ("pv_cp", "ty_lbf_100ft2", "iod"), (3, 2, 3)):
                column.metric(title, f"{row[field]:.{decimals}f}")
    for issue in issues:
        st.warning(issue)
    return result, issues


def get_slurry_key(slurry_name: str, prefix: str) -> str:
    sanitized = "".join(c if c.isalnum() else "_" for c in str(slurry_name)).lower()
    return f"{prefix}_{sanitized}"

def _bhct_suggestion():
    """IH-15: resolve the i-Handbook / API 10B BHCT suggestion from the current
    well data, or return None when the inputs don't support the correlation.

    CRITICAL unit note: `geo_tvd` (Phase II/III) is stored in METERS while the
    decompiled correlations take FEET, so it is converted with the pinned
    factor M_TO_FT = 3.28084 before entering suggest_bhct. The lookup mirrors
    the established well-data pattern (well_data snapshot first, top-level
    shadow key as fallback) so the suggestion and the BHST Reference caption
    always come from the same data vintage. The suggestion stays hidden when
    TVD is non-positive or BHST <= 80 degF: the i-Handbook pseudo gradient
    PsTG = (MaxRBHST - 80) * 100 / TVD only makes physical sense above the
    80 degF surface-temperature base of the correlation.

    Returns (tvd_m, tvd_ft, suggestion_dict) or None.
    """
    tvd_m = st.session_state.get("well_data", {}).get(
        "geo_tvd", st.session_state.get("geo_tvd", 3000.0))
    bhst_v = st.session_state.get("well_data", {}).get(
        "bhst", st.session_state.get("bhst", 200))
    try:
        tvd_ft = float(tvd_m) * M_TO_FT
        bhst_f = float(bhst_v)
    except (TypeError, ValueError):
        return None
    if tvd_ft <= 0 or bhst_f <= 80:
        return None
    try:
        suggestion = suggest_bhct(tvd_ft=tvd_ft, max_rbhest_f=bhst_f)
        return (float(tvd_m), tvd_ft, suggestion) if suggestion["kind"] == "BHCT" else None
    except ValueError:
        return None

def _apply_bhct_suggestion(slurry: str, suggested: int, widget_key: str) -> None:
    """IH-15 on_click callback for the 'Apply' button under the BHCT field.

    Commits the suggested value into st.session_state["lab_qc_params"][slurry]
    ["bhct"] AND into the live number_input widget key. Callbacks run BEFORE
    the script re-executes, so assigning a widget-backed key here is legal —
    this is the only way the visible field actually follows the suggestion
    (setting it after instantiation raises StreamlitAPIException). The click
    itself triggers the rerun that re-renders the field with the new value;
    no explicit st.rerun() is needed (and one inside would be redundant).
    """
    st.session_state.setdefault("lab_qc_params", {}).setdefault(slurry, {})["bhct"] = suggested
    st.session_state[widget_key] = suggested


def has_legacy_salt_basis(phase5_df: pd.DataFrame, lab_df: pd.DataFrame) -> bool:
    """Flag old salt lab rows on load even when the transient sync hash is absent."""
    if not isinstance(lab_df, pd.DataFrame):
        return False
    salt_names = set()
    if isinstance(phase5_df, pd.DataFrame):
        for _, row in phase5_df.iterrows():
            material_type = str(row.get("Material Type", "")).strip()
            name = str(row.get("Name", "")).strip()
            if is_salt_additive(material_type, name):
                display_name = name if name and name.upper() != "OTHER (CUSTOM)" else material_type
                salt_names.add(display_name.casefold())
    return any(
        (str(row.get("Material", "")).strip().casefold() in salt_names
         or is_salt_additive(material_name=row.get("Material", "")))
        and str(row.get("Unit", "")).strip() != "% BWOW"
        for _, row in lab_df.iterrows()
    )

def build_lab_df_from_phase5(
    phase5_df: pd.DataFrame, 
    base_cement: str = "CEMENT G DELIJAN", 
    slurry_weight_pcf: float = 118.0,
    slurry_volume_bbl: float = 50.0,
    cmt_sg: float = 3.2,
    water_density_pcf: float = 62.4,
    existing_df: pd.DataFrame = None,
    recalculate_mass: bool = False
) -> pd.DataFrame:
    """
    Translates Phase V slurry formulation into pure API Lab specifications (600 mL cup).
    Uses the exact NIDC CMT Calculator mass-balance engine (Cell O7, O8, O9 and P formulas).
    When recalculate_mass=True, it refreshes all Mass fields with live calculated values.
    """
    existing_meta = {}
    existing_by_name = {}
    if existing_df is not None and isinstance(existing_df, pd.DataFrame) and not existing_df.empty:
        for _, r in existing_df.iterrows():
            mat = str(r.get("Material", "")).strip().upper()
            if mat:
                meta = {
                    "Mass": str(r.get("Mass", "") or "").strip(),
                    "Lot No": str(r.get("Lot No", "") or "").strip(),
                    "Unit": str(r.get("Unit", "") or "").strip()
                }
                existing_meta[mat] = meta
                existing_by_name.setdefault(mat, []).append(meta)
    
    # Parse Phase V items into powders and liquids for calculation engine
    powders = []
    liquids = []
    salt_pct = 0.0

    if phase5_df is not None and isinstance(phase5_df, pd.DataFrame) and not phase5_df.empty:
        for _, row in phase5_df.iterrows():
            mat_type, display_name = require_additive_identity(row)
                
            state = resolve_physical_state(mat_type, row.get("Physical State"))
            # FIX: resolved through normalize_additive_mix (engineering_tools.py) —
            # the same single source of truth Phase V uses for this row. Previously
            # this loop re-derived the Dry Blend/In Mix Water decision on its own,
            # so a Liquid+"Dry Blend" row (nothing prevents that combination in the
            # Phase V editor) could be classified as a dry powder here for the lab
            # gram-mass calculation while Phase V's own table showed it dissolved in
            # water — same input, two disagreeing numbers across the two phases.
            mix_m, is_dry_blend = normalize_additive_mix(state, row.get("Mix Method"), display_name, mat_type)
            user_val = require_nonnegative_number(row.get("User Input"), display_name)
            if mat_type.casefold() == "cement":
                raise ValueError(f"{display_name}: cement added as a separate additive requires a reviewed blend design")
            
            if is_salt_additive(mat_type, display_name):
                salt_pct += user_val
            elif state.lower() == "powder" or is_dry_blend:
                den = resolve_additive_density(display_name, "Powder", row.get("Density"),
                                               require_measured=materials_db.resolve_known_material(display_name) is None)
                powders.append({
                    "name": display_name.upper(),
                    "percent": user_val,
                    "density_pcf": den,
                    "in_solution": not is_dry_blend
                })
            else:
                den_ppg, fac = resolve_additive_density(display_name, "Liquid", row.get("Density"),
                                                        require_measured=materials_db.resolve_known_material(display_name) is None)
                liquids.append({
                    "name": display_name.upper(),
                    "gal_per_sk": user_val,
                    "density_ppg": den_ppg,
                    "lab_factor": fac
                })

    # Run authentic CMT Calculator mass balance
    calc = calculate_slurry_from_components(
        slurry_weight_pcf=slurry_weight_pcf,
        slurry_volume_bbl=slurry_volume_bbl,
        cmt_sg=cmt_sg,
        water_density_pcf=water_density_pcf,
        salt_pct=salt_pct,
        powders=powders,
        liquids=liquids
    )

    powder_masses = iter(p["lab_gr"] for p in calc["lab_powders"])
    liquid_masses = iter(l["lab_gr"] for l in calc["lab_liquids"])
    additive_occurrences = {}

    lab_rows = []

    # 1. Base Cement Row (100% BWOB, mass = lab_cmt_gr)
    c_name = str(base_cement).strip().upper() or "CEMENT G DELIJAN"
    cement_prev = existing_meta.get(c_name, existing_meta.get("CEMENT G DELIJAN", {}))
    calc_cmt_mass = f"{calc['lab_cmt_gr']:.1f}"
    
    prev_c_mass = cement_prev.get("Mass", "")
    if recalculate_mass or not prev_c_mass or prev_c_mass == "-":
        final_c_mass = calc_cmt_mass
    else:
        final_c_mass = prev_c_mass

    lab_rows.append({
        "Material": c_name,
        "Concentration": "100.0%",
        "Unit": "BWOB",
        "Mass": final_c_mass,
        "Lot No": cement_prev.get("Lot No", "")
    })
    
    # 2. Additives from Phase V formulation
    if phase5_df is not None and isinstance(phase5_df, pd.DataFrame) and not phase5_df.empty:
        for _, row in phase5_df.iterrows():
            mat_type, display_name = require_additive_identity(row)
                
            state = resolve_physical_state(mat_type, row.get("Physical State"))
            # FIX: same shared classifier as above, so the "% BWOC vs gal/sk" unit
            # shown here always agrees with which bucket (powder vs liquid) the
            # mass-balance engine actually placed this row into.
            mix_m, is_dry_blend = normalize_additive_mix(state, row.get("Mix Method"), display_name, mat_type)
            user_val = require_nonnegative_number(row.get("User Input"), display_name)
            
            is_salt = is_salt_additive(mat_type, display_name)
            unit = "% BWOW" if is_salt else ("% BWOC" if (state.lower() == "powder" or is_dry_blend) else "gal/sk")
            conc_str = f"{user_val:.3f}" if round(user_val, 2) != user_val else f"{user_val:.2f}"
            
            d_upper = display_name.upper()
            if is_salt:
                # Same water basis as calc['salt_lab_gr']; using this row's
                # percentage also supports separate NaCl rows without duplication.
                m_val = calc['lab_water_gr'] * user_val / 100.0
            elif state.lower() == "powder" or is_dry_blend:
                m_val = next(powder_masses)
            else:
                m_val = next(liquid_masses)

            mass_str = f"{m_val:.2f}" if m_val < 10 else f"{m_val:.1f}"
            occurrence = additive_occurrences.get(d_upper, 0)
            additive_occurrences[d_upper] = occurrence + 1
            previous_rows = existing_by_name.get(d_upper, [])
            prev = previous_rows[occurrence] if occurrence < len(previous_rows) else {}
            prev_m = prev.get("Mass", "")
            
            legacy_salt_basis = is_salt and prev.get("Unit") != "% BWOW"
            if recalculate_mass or legacy_salt_basis or not prev_m or prev_m == "-":
                final_add_mass = mass_str
            else:
                final_add_mass = prev_m

            lab_rows.append({
                "Material": display_name,
                "Concentration": conc_str,
                "Unit": unit,
                "Mass": final_add_mass,
                "Lot No": prev.get("Lot No", "")
            })
            
    # 3. Base Water Row (1.0 BWOW, mass = lab_water_gr)
    water_prev = existing_meta.get("BASE WATER", {})
    calc_water_mass = f"{calc['lab_water_gr']:.1f}"
    prev_w_mass = water_prev.get("Mass", "")
    
    if recalculate_mass or not prev_w_mass or prev_w_mass == "-":
        final_w_mass = calc_water_mass
    else:
        final_w_mass = prev_w_mass

    lab_rows.append({
        "Material": "Base Water",
        "Concentration": "1.0",
        "Unit": "BWOW",
        "Mass": final_w_mass,
        "Lot No": water_prev.get("Lot No", "Lab Sample")
    })
    
    return pd.DataFrame(lab_rows)

def render():
    """Main render entrypoint called by main.py."""
    st.header("Phase VII: Lab Report")
    st.markdown("Enter Lab QC parameters and inspect auto-calculated API lab test quantities (600 mL cup basis).")
    
    load_sig = str(st.session_state.get("last_loaded_hash", "default_project"))
    
    # 1. Strict SSOT Tab Derivation from Phase IV sequence
    active_pipeline = st.session_state.get("fluids_config", {}).get("active", [])
    slurry_archetypes = {"Main", "Lead", "Lead #1", "Lead #2", "Tail"}
    active_slurries = [f for f in active_pipeline if f in slurry_archetypes]
    
    if not active_slurries:
        st.warning("⚠ No cement slurries were selected in Phase IV.")
        return
        
    bhst = st.session_state.get("well_data", {}).get("bhst", st.session_state.get("bhst", 200))
    fluid_data = st.session_state.get("fluid_data", {})
    # IH-15: i-Handbook/API 10B suggestion, resolved once per render from the
    # well-level TVD/BHST (same data vintage as `bhst` above); None when the
    # inputs don't support the correlation. Pure math — no side effects.
    bhct_suggestion = _bhct_suggestion()
    
    # Canonical State Initializations
    if "lab_qc_params" not in st.session_state:
        st.session_state["lab_qc_params"] = {}
    if "lab_grid_dfs" not in st.session_state:
        st.session_state["lab_grid_dfs"] = {}
    if "lab_initialized_slurries" not in st.session_state:
        st.session_state["lab_initialized_slurries"] = []

    bounded = []
    for slurry in active_slurries:
        qc = st.session_state["lab_qc_params"].get(slurry, {})
        for field, label, low, high, integer in (
            ("bhct", "BHCT (°F)", 60, 400, True),
            ("api_fl", "Filtrate @ 30 min (ml)", 0.0, None, False),
            ("free_water", "Free water (ml)", 0.0, None, False),
            ("free_water_45", "Free Water Collected (45° angle) (ml)", 0.0, None, False),
            ("surface_hardened_hours", "Surface Sample Hours", 0.0, None, False),
        ):
            if field in qc and not (qc[field] is None and
                    field in ("free_water_45", "surface_hardened_hours", "bhct")):
                bounded.append((qc, field, f"{label} - {slurry}", low, high, integer))
    if repair_invalid_inputs(bounded, f"phase7_{load_sig}"):
        return
    tabs = st.tabs(active_slurries)
    
    for i, slurry in enumerate(active_slurries):
        with tabs[i]:
            st.subheader(f"{slurry} Lab Data")
            
            qc = st.session_state["lab_qc_params"].setdefault(
                slurry, {
                    "bhct": None,
                    "api_fl": 0.0,
                    "free_water": 0.0,
                    "thickening_time": ""
                }
            )
            
            qc.setdefault("bhct", None)
            qc.setdefault("free_water_45", None)
            qc.setdefault("surface_hardened_hours", None)
            for field, _, kind in THICKENING_TEST_FIELDS:
                qc.setdefault(field, None if kind == "number" else "")

            # Fetch parameters from Phase V and Phase IV
            p_cement = st.session_state.get("cement_params", {}).get(slurry, {}).get("base_cement", "Cement G Delijan")
            try:
                p_cmt_sg = clean_number(resolve_cement_sg(st.session_state.get("cement_params", {}).get(slurry, {})))
                slurry_vol = clean_number(fluid_data.get(slurry, {}).get("volume"))
                if slurry_vol <= 0:
                    raise ValueError("Phase IV slurry volume must be positive")
                slurry_den = require_positive_density(fluid_data.get(slurry, {}).get("density"))
                # BUG-13: the Phase VII-side gate. An implausible density must be
                # rejected here — before lab quantities are built — with a message
                # that names the problem instead of showing negative gram rows.
                if not (75.0 <= slurry_den <= 180.0):
                    raise ValueError(
                        f"slurry density {slurry_den:.1f} pcf is outside the realistic "
                        "75-180 pcf range for a cement slurry")
            except ValueError as exc:
                st.error(f"{slurry}: invalid Phase IV/V input ({exc}). Correct it before syncing lab quantities.")
                continue
            
            phase5_df = st.session_state.get("cement_additives_dfs", {}).get(slurry, pd.DataFrame())
            
            current_p5_sig = lab_source_signature(st.session_state, slurry)
            signatures = st.session_state.setdefault("lab_source_signatures", {})

            # Initial generation guard
            if slurry not in st.session_state["lab_grid_dfs"]:
                try:
                    st.session_state["lab_grid_dfs"][slurry] = build_lab_df_from_phase5(
                        phase5_df, base_cement=p_cement,
                        slurry_weight_pcf=slurry_den, slurry_volume_bbl=slurry_vol,
                        cmt_sg=p_cmt_sg, recalculate_mass=True
                    )
                except ValueError as exc:
                    st.error(f"{slurry}: {exc}. Correct the formulation in Phase V before syncing lab quantities.")
                    continue
                st.session_state["lab_initialized_slurries"].append(slurry)
                signatures[slurry] = current_p5_sig
            
            if slurry not in st.session_state["lab_initialized_slurries"]:
                st.session_state["lab_initialized_slurries"].append(slurry)
            last_synced_sig = signatures.get(slurry)
            # FIX (requested, Level 1 #3): computed once here (rather than
            # inline at each of the two use sites below) so the warning
            # text and the button styling can never disagree about whether
            # drift is actually active.
            current_lab_df = st.session_state["lab_grid_dfs"].get(slurry, pd.DataFrame(columns=LAB_GRID_COLUMNS))
            legacy_salt_basis = has_legacy_salt_basis(phase5_df, current_lab_df)
            drifted = (last_synced_sig != current_p5_sig) or legacy_salt_basis
            
            # 1. Additives Section with Reactive Drift Warning
            col_h1, col_h2 = st.columns([3, 1])
            with col_h1:
                st.markdown("#### 1. Blend & Additives (API Lab Basis - 600 mL Cup)")
                if legacy_salt_basis:
                    st.warning("⚠ Salt lab rows use the old concentration basis. Click 'Sync with Phase V' to recalculate on % BWOW; Lot No. is preserved.")
                elif drifted:
                    st.warning("⚠ **Formulation Drift:** Lab data is unverified for the current formulation or BHST/BHSP (including older projects). Sync quantities, or review and keep your existing lab entries.")
            with col_h2:
                sync_key = f"_sync_{get_slurry_key(slurry, 'btn')}_{load_sig}"
                # FIX (requested, Level 1 #3): when the values on screen are
                # known-stale (drifted), Sync is the one action that matters
                # on this tab — primary styling reflects that instead of
                # looking identical to every other secondary button here.
                if st.button("Sync with Phase V", key=sync_key, type="primary" if drifted else "secondary", help="Re-calculates lab gram quantities using CMT Calculator engine while preserving Lot No."):
                    current_df = st.session_state["lab_grid_dfs"].get(slurry, pd.DataFrame())
                    try:
                        st.session_state["lab_grid_dfs"][slurry] = build_lab_df_from_phase5(
                            phase5_df, base_cement=p_cement,
                            slurry_weight_pcf=slurry_den, slurry_volume_bbl=slurry_vol,
                            cmt_sg=p_cmt_sg, existing_df=current_df,
                            recalculate_mass=True
                        )
                    except ValueError as exc:
                        st.error(f"{slurry}: {exc}. Correct the formulation in Phase V before syncing.")
                        continue
                    signatures[slurry] = current_p5_sig
                    qc["reviewed"] = False
                    revision_key = f"_lab_grid_revision_{slurry}"
                    st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
                    st.rerun()

            if drifted and not legacy_salt_basis:
                if st.button("Keep reviewed lab entries", key=f"_keep_lab_{slurry}_{load_sig}",
                             help="Confirm that the existing quantities and QC results apply to the current formulation; keep all manual entries."):
                    signatures[slurry] = current_p5_sig
                    qc["reviewed"] = False
                    st.rerun()

            current_lab_df = st.session_state["lab_grid_dfs"].get(slurry, pd.DataFrame(columns=LAB_GRID_COLUMNS))
            editor_key = f"_editor_lab_{get_slurry_key(slurry, 'tbl')}_{load_sig}_{st.session_state.get(f'_lab_grid_revision_{slurry}', 0)}"
            
            edited_lab_df = persistent_data_editor(
                current_lab_df,
                persist_to=("lab_grid_dfs", slurry),
                column_config={
                    # Allow an unfinished row to reach session state as soon as
                    # its first cell is edited. Completeness is checked by the
                    # phase status and export guard when the user is done.
                    "Material": st.column_config.TextColumn("Material"),
                    "Concentration": st.column_config.TextColumn("Concentration (% or gal/sk)"),
                    "Unit": st.column_config.SelectboxColumn("Unit", options=["BWOW", "% BWOW", "BWOB", "% BWOC", "gal/sk", "VBWOC"], default="% BWOC"),
                    "Mass": st.column_config.TextColumn("Mass (grams)", default=""),
                    "Lot No": st.column_config.TextColumn("Lot No", default="")
                },
                num_rows="dynamic",
                key=editor_key,
                width='stretch'
            )
            
            # Defensive validation against deleted rows
            if edited_lab_df is None:
                edited_lab_df = pd.DataFrame(columns=LAB_GRID_COLUMNS)
            else:
                for c in LAB_GRID_COLUMNS:
                    if c not in edited_lab_df.columns:
                        edited_lab_df[c] = ""
                        
            st.session_state["lab_grid_dfs"][slurry] = edited_lab_df
            
            st.markdown("---")
            
            # 2. QC & Core Physical Properties
            st.markdown("#### 2. QC & Core Lab Results")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                bhct_key = f"_qc_bhct_{get_slurry_key(slurry, 'in')}_{load_sig}"
                if bhct_key not in st.session_state:
                    st.session_state[bhct_key] = int(qc["bhct"]) if qc["bhct"] is not None else None
                qc["bhct"] = st.number_input(
                    f"BHCT (°F) - {slurry}",
                    min_value=60,
                    max_value=400,
                    value=None,
                    step=5,
                    key=bhct_key,
                    on_change=_commit_lab_qc,
                    args=(slurry, "bhct", bhct_key)
                )
                st.caption(f"BHST Reference: **{bhst} °F**")
                # IH-15: advisory i-Handbook/API 10B suggestion, shown only
                # when TVD + BHST support the correlation. Display-only caption
                # plus an explicit 'Apply' button — it never overwrites anything
                # by itself and can never hard-block the phase (the manual entry
                # and the lab_temperature_valid check stay authoritative).
                # The suggested value is clamped to the widget's 60-400 °F range
                # before applying so the number_input can never receive an
                # out-of-bounds state; any clamping is disclosed in the caption.
                if bhct_suggestion is not None:
                    sug_m, sug_ft, sug = bhct_suggestion
                    sug_raw = int(round(sug["temp_degF"]))
                    sug_apply = max(60, min(400, sug_raw))
                    clamp_note = (f" (clamped to the 60-400 °F field range)"
                                  if sug_apply != sug_raw else "")
                    st.caption(
                        f"💡 Suggested {sug['kind']} ≈ **{sug_raw} °F**{clamp_note} — "
                        f"i-Handbook: TVD {sug_ft:,.0f} ft ({sug_m:,.0f} m), "
                        f"BHST {bhst} °F, PsTG {sug['pstg_degF_per_100ft']:.2f} °F/100ft"
                    )
                    st.button(
                        f"Apply {sug_apply} °F",
                        key=f"_qc_bhct_apply_{get_slurry_key(slurry, 'btn')}_{load_sig}",
                        on_click=_apply_bhct_suggestion,
                        args=(slurry, sug_apply, bhct_key),
                        help="Overwrite the manual BHCT entry with the i-Handbook/API 10B "
                             "estimate computed from well TVD and BHST.",
                    )
                # FIX (requested, Level 2 #8): BHCT (circulating temperature,
                # what the slurry actually experiences while being pumped)
                # can never physically exceed BHST (static temperature) —
                # nothing caught a mistyped or copy-pasted value that broke
                # this relationship before. A large gap the other direction
                # is unusual but not necessarily wrong (schedules vary), so
                # that case is a caption, not an error.
                if qc["bhct"] is not None and bhst is not None and qc["bhct"] > bhst:
                    st.error(f"✕ BHCT ({qc['bhct']}°F) cannot exceed BHST ({bhst}°F).")
                elif qc["bhct"] is not None and bhst is not None and bhst - qc["bhct"] > 80:
                    st.caption(f"ℹ️ BHCT is {bhst - qc['bhct']}°F below BHST — verify this matches the actual circulating temperature schedule.")
                
            with col2:
                fl_key = f"_qc_fl_{get_slurry_key(slurry, 'in')}_{load_sig}"
                qc["api_fl"] = st.number_input(
                    f"Filtrate @ 30 min (ml) - {slurry}",
                    min_value=0.0,
                    step=1.0,
                    value=float(qc.get("api_fl", 0.0)),
                    key=fl_key,
                    on_change=_commit_lab_qc,
                    args=(slurry, "api_fl", fl_key),
                    help="API standard 30-min filter press test volume"
                )
                calc_fl = qc["api_fl"] * 2.0
                st.success(f"**API FL (St. 2x):** {calc_fl:.1f} ml/30min")
                
            with col3:
                fw_key = f"_qc_fw_{get_slurry_key(slurry, 'in')}_{load_sig}"
                qc["free_water"] = st.number_input(
                    f"Free Water Collected (90° angle) (ml) - {slurry}",
                    min_value=0.0,
                    step=0.1,
                    value=float(qc.get("free_water", 0.0)),
                    key=fw_key,
                    on_change=_commit_lab_qc,
                    args=(slurry, "free_water", fw_key)
                )
                st.success(f"**FW:** {qc['free_water']:.1f} ml / 250ml")
                fw45_key = f"_qc_fw45_{get_slurry_key(slurry, 'in')}_{load_sig}"
                if fw45_key not in st.session_state:
                    st.session_state[fw45_key] = float(qc["free_water_45"]) if qc["free_water_45"] is not None else None
                qc["free_water_45"] = st.number_input(
                    f"Free Water Collected (45° angle) (ml) - {slurry}",
                    min_value=0.0, step=0.1, value=None, key=fw45_key,
                    on_change=_commit_lab_qc, args=(slurry, "free_water_45", fw45_key)
                )
                hours_key = f"_qc_surface_hours_{get_slurry_key(slurry, 'in')}_{load_sig}"
                if hours_key not in st.session_state:
                    st.session_state[hours_key] = float(qc["surface_hardened_hours"]) if qc["surface_hardened_hours"] is not None else None
                qc["surface_hardened_hours"] = st.number_input(
                    f"Surface Sample Hours - {slurry}",
                    min_value=0.0, step=0.25, value=None, key=hours_key,
                    on_change=_commit_lab_qc, args=(slurry, "surface_hardened_hours", hours_key),
                    help="Hours until the surface sample's hardened condition was observed; independent of Thickening Time."
                )
                
            compressive, comp_valid = _render_compressive(slurry, qc, load_sig, bhst, st.session_state.get("well_data", {}).get("bhsp", ""))
            tt_valid = _render_thickening_test(slurry, qc, load_sig)

            try:
                validate_lab_masses(edited_lab_df)
                masses_valid = True
            except ValueError as exc:
                masses_valid = False
                st.error(f"{slurry}: {exc}. Correct the lab mass before confirming or exporting.")
            try:
                validate_lab_collection_results(qc)
                collection_valid = True
            except ValueError as exc:
                collection_valid = False
                st.caption(f"{slurry}: {exc}. Enter both Free Water measurements and Surface Sample Hours before confirming.")
            rheology, rheology_issues = _render_rheology(slurry, qc, load_sig)
            temperature_valid = lab_temperature_valid(qc["bhct"], bhst)
            review_matches = (comp_valid and temperature_valid and tt_valid and masses_valid and collection_valid and not rheology_issues
                              and qc.get("reviewed", False)
                              and qc.get("review_signature") == lab_review_signature(qc, edited_lab_df)
                              and signatures.get(slurry) == current_p5_sig)
            if review_matches:
                st.success("Lab readings and formulation reviewed for this slurry.")
            elif st.button("Confirm measured lab results", key=f"_confirm_lab_{get_slurry_key(slurry, 'btn')}_{load_sig}",
                           disabled=not comp_valid or bool(rheology_issues) or drifted or not temperature_valid or not tt_valid or not masses_valid or not collection_valid,
                           help="Confirm the values above are measured and checked for the current well and formulation."):
                qc["reviewed"] = True
                qc["review_signature"] = lab_review_signature(qc, edited_lab_df)
                st.rerun()
            elif not masses_valid:
                st.caption("Correct the lab masses before confirming the lab results; unfinished entries remain saved.")
            elif drifted:
                st.caption("Sync or keep reviewed lab entries before confirming their measured results.")
            elif not temperature_valid:
                st.caption("Correct BHCT/BHST before confirming the lab results.")
            elif not tt_valid:
                st.caption("Complete the Thickening Time Test fields before confirming the lab results.")
            else:
                st.warning("Lab QC has not been confirmed for this slurry; defaults are not measured results.")

            # Pull Lab Test Basic Data fields that don't have their own Phase VII
            # widget: BHSP comes from Phase III (shared well property, same as
            # BHST); Base Fluid / Mix Fluid come from Phase V's mass-balance
            # engine (same slurry, lab-basis water requirement); Solution
            # Density is a fixed reference constant (see materials_db.py).
            well_data = st.session_state.get("well_data", {})
            slurry_cement_params = st.session_state.get("cement_params", {}).get(slurry, {})

            # Expose consolidated clean lab payload for Phase X Word export
            st.session_state[f"lab_payload_{slurry}"] = {
                "grid": edited_lab_df,
                "rheology": rheology,
                "bhct": qc["bhct"],
                "bhst": bhst,
                "api_fl": qc["api_fl"] * 2.0,
                "api_fl_collected": qc["api_fl"],
                "free_water": qc["free_water"],
                "free_water_45": qc["free_water_45"],
                "surface_hardened_hours": qc["surface_hardened_hours"],
                "compressive": compressive,
                **{field: qc[field] for field, _, _ in THICKENING_TEST_FIELDS},
                "bhsp": well_data.get("bhsp", ""),
                "base_fluid": slurry_cement_params.get("base_fluid_gal_sk", ""),
                "mix_water": slurry_cement_params.get("mix_water_gal_sk", ""),
                "mix_fluid": slurry_cement_params.get("mix_fluid_gal_sk", ""),
                "solution_density": materials_db.SOLUTION_DENSITY_PCF
            }
