# phase_7_lab.py
import streamlit as st
import pandas as pd
import re
import materials_db
from project_state import lab_source_signature
from engineering_tools import lab_review_signature, lab_temperature_valid
from input_guard import repair_invalid_inputs
from editor_state import persistent_data_editor
from engineering_tools import (
    clean_number,
    require_nonnegative_number,
    parse_effective_numeric,
    calculate_slurry_from_components,
    resolve_additive_density,
    resolve_physical_state,
    normalize_additive_mix,
    is_salt_additive
)

LAB_GRID_COLUMNS = ["Material", "Concentration", "Unit", "Mass", "Lot No"]

def get_slurry_key(slurry_name: str, prefix: str) -> str:
    sanitized = "".join(c if c.isalnum() else "_" for c in str(slurry_name)).lower()
    return f"{prefix}_{sanitized}"


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
            mat_type = str(row.get("Material Type", "") or "").strip()
            name = str(row.get("Name", "") or "").strip()
            display_name = name if name and name.upper() != "OTHER (CUSTOM)" else mat_type
            
            if not display_name or display_name in ["None", "nan"]:
                continue
            if mat_type.upper() == "OTHER (CUSTOM)" and not name and clean_number(row.get("User Input")) == 0.0:
                continue
                
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
                                               require_measured=name.casefold() == "other (custom)")
                powders.append({
                    "name": display_name.upper(),
                    "percent": user_val,
                    "density_pcf": den,
                    "in_solution": not is_dry_blend
                })
            else:
                den_ppg, fac = resolve_additive_density(display_name, "Liquid", row.get("Density"),
                                                        require_measured=name.casefold() == "other (custom)")
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
            mat_type = str(row.get("Material Type", "") or "").strip()
            name = str(row.get("Name", "") or "").strip()
            display_name = name if name and name.upper() != "OTHER (CUSTOM)" else mat_type
            
            if not display_name or display_name in ["None", "nan"]:
                continue
            if mat_type.upper() == "OTHER (CUSTOM)" and not name and clean_number(row.get("User Input")) == 0.0:
                continue
                
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
        ):
            if field in qc:
                bounded.append((qc, field, f"{label} - {slurry}", low, high, integer))
    if repair_invalid_inputs(bounded, f"phase7_{load_sig}"):
        return
    tabs = st.tabs(active_slurries)
    
    for i, slurry in enumerate(active_slurries):
        with tabs[i]:
            st.subheader(f"{slurry} Lab Data")
            
            qc = st.session_state["lab_qc_params"].setdefault(
                slurry, {
                    "bhct": 150,
                    "api_fl": 0.0,
                    "free_water": 0.0,
                    "comp_test": "CRUSH",
                    "thickening_time": "03:30"
                }
            )
            
            # Fetch parameters from Phase V and Phase IV
            p_cement = st.session_state.get("cement_params", {}).get(slurry, {}).get("base_cement", "Cement G Delijan")
            try:
                p_cmt_sg = clean_number(st.session_state.get("cement_params", {}).get(slurry, {}).get("cmt_sg", 3.20)) or 3.20
                slurry_vol = clean_number(fluid_data.get(slurry, {}).get("volume", 50.0)) or 50.0
                slurry_den_str = str(fluid_data.get(slurry, {}).get("density", "118.0"))
                slurry_den = clean_number(fluid_data.get(slurry, {}).get("effective_density")) or parse_effective_numeric(slurry_den_str, 118.0)
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
                column_config={
                    "Material": st.column_config.TextColumn("Material", required=True),
                    "Concentration": st.column_config.TextColumn("Concentration (% or gal/sk)", required=True),
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
                qc["bhct"] = st.number_input(
                    f"BHCT (°F) - {slurry}",
                    min_value=60,
                    max_value=400,
                    value=int(qc.get("bhct", 150)),
                    step=5,
                    key=f"_qc_bhct_{get_slurry_key(slurry, 'in')}_{load_sig}"
                )
                st.caption(f"BHST Reference: **{bhst} °F**")
                # FIX (requested, Level 2 #8): BHCT (circulating temperature,
                # what the slurry actually experiences while being pumped)
                # can never physically exceed BHST (static temperature) —
                # nothing caught a mistyped or copy-pasted value that broke
                # this relationship before. A large gap the other direction
                # is unusual but not necessarily wrong (schedules vary), so
                # that case is a caption, not an error.
                if qc["bhct"] > bhst:
                    st.error(f"✕ BHCT ({qc['bhct']}°F) cannot exceed BHST ({bhst}°F).")
                elif bhst - qc["bhct"] > 80:
                    st.caption(f"ℹ️ BHCT is {bhst - qc['bhct']}°F below BHST — verify this matches the actual circulating temperature schedule.")
                
            with col2:
                qc["api_fl"] = st.number_input(
                    f"Filtrate @ 30 min (ml) - {slurry}",
                    min_value=0.0,
                    step=1.0,
                    value=float(qc.get("api_fl", 0.0)),
                    key=f"_qc_fl_{get_slurry_key(slurry, 'in')}_{load_sig}",
                    help="API standard 30-min filter press test volume"
                )
                calc_fl = qc["api_fl"] * 2.0
                st.success(f"**API FL (St. 2x):** {calc_fl:.1f} ml/30min")
                
            with col3:
                qc["free_water"] = st.number_input(
                    f"Free Water (ml) - {slurry}",
                    min_value=0.0,
                    step=0.1,
                    value=float(qc.get("free_water", 0.0)),
                    key=f"_qc_fw_{get_slurry_key(slurry, 'in')}_{load_sig}"
                )
                st.success(f"**FW:** {qc['free_water']:.1f} ml / 250ml")
                
            with col4:
                comp_opts = ["CRUSH", "UCA"]
                cur_comp = qc.get("comp_test", "CRUSH")
                comp_idx = comp_opts.index(cur_comp) if cur_comp in comp_opts else 0
                qc["comp_test"] = st.selectbox(
                    f"Compressive Test - {slurry}",
                    options=comp_opts,
                    index=comp_idx,
                    key=f"_qc_comp_{get_slurry_key(slurry, 'in')}_{load_sig}"
                )
                qc["thickening_time"] = st.text_input(
                    f"Thickening Time (HH:MM) - {slurry}",
                    value=str(qc.get("thickening_time", "03:30")),
                    key=f"_qc_tt_{get_slurry_key(slurry, 'in')}_{load_sig}",
                    help="Reported thickening time. Select its measured endpoint below."
                )
                endpoint_options = ["Not specified", "70 Bc", "100 Bc"]
                endpoint = qc.get("thickening_endpoint", "Not specified")
                qc["thickening_endpoint"] = st.selectbox(
                    f"Thickening Time Endpoint - {slurry}",
                    endpoint_options,
                    index=endpoint_options.index(endpoint) if endpoint in endpoint_options else 0,
                    key=f"_qc_tt_endpoint_{get_slurry_key(slurry, 'in')}_{load_sig}",
                    help="For an older project, leave Not specified unless the test endpoint is known."
                )
                # FIX (requested, Level 2 #8): this is free text with no
                # format enforcement (deliberately — see the design-decisions
                # note on why range/free-text fields in this app stay text
                # inputs), and it's printed into the Word report exactly as
                # typed. A caption-level nudge catches an obviously malformed
                # value (e.g. "3:3", "03.30") without blocking anything.
                if not re.match(r"^\d{1,2}:[0-5]\d$", qc["thickening_time"].strip()):
                    st.caption("⚠️ Format should be HH:MM (e.g. 03:30). This value is printed in the report exactly as typed.")

            temperature_valid = lab_temperature_valid(qc["bhct"], bhst)
            review_matches = (temperature_valid and qc.get("reviewed", False)
                              and qc.get("review_signature") == lab_review_signature(qc, edited_lab_df)
                              and signatures.get(slurry) == current_p5_sig)
            if review_matches:
                st.success("Lab readings and formulation reviewed for this slurry.")
            elif st.button("Confirm measured lab results", key=f"_confirm_lab_{get_slurry_key(slurry, 'btn')}_{load_sig}",
                           disabled=drifted or not temperature_valid,
                           help="Confirm the values above are measured and checked for the current well and formulation."):
                qc["reviewed"] = True
                qc["review_signature"] = lab_review_signature(qc, edited_lab_df)
                st.rerun()
            elif drifted:
                st.caption("Sync or keep reviewed lab entries before confirming their measured results.")
            elif not temperature_valid:
                st.caption("Correct BHCT/BHST before confirming the lab results.")
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
                "bhct": qc["bhct"],
                "bhst": bhst,
                "api_fl": qc["api_fl"] * 2.0,
                "api_fl_collected": qc["api_fl"],
                "free_water": qc["free_water"],
                "comp_test": qc["comp_test"],
                "thickening_time": qc["thickening_time"],
                "thickening_endpoint": qc["thickening_endpoint"],
                "bhsp": well_data.get("bhsp", ""),
                "base_fluid": slurry_cement_params.get("base_fluid_gal_sk", ""),
                "mix_fluid": slurry_cement_params.get("mix_fluid_gal_sk", ""),
                "solution_density": materials_db.SOLUTION_DENSITY_PCF
            }
