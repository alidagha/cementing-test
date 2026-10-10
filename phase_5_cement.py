# phase_5_cement.py
import streamlit as st
import pandas as pd
import materials_db
from engineering_tools import (
    round_half_up,
    clean_number,
    require_positive_density,
    require_nonnegative_number,
    validate_cement_parameters,
    calculate_slurry_from_components,
    resolve_additive_density,
    require_additive_identity,
    default_additive_density_gcm3,
    resolve_physical_state,
    normalize_additive_mix,
    is_salt_additive,
    calculate_salt_field_amounts,
    BBL_TO_CUFT, WATER_DENSITY_PCF, catalog_cement_sg, resolve_cement_sg
)
from project_state import fingerprint, migrate_material_properties
from input_guard import repair_invalid_inputs
from editor_state import persistent_data_editor
from placement import target_depth, top_label

REQUIRED_ADDITIVE_COLUMNS = ["Material Type", "Name", "Physical State", "Mix Method", "User Input"]


def _normalize_additive_rows(data: pd.DataFrame, previous=None) -> pd.DataFrame:
    """Use the existing Name auto-lock and seed/reset density in the same commit."""
    edited_df = data.copy(deep=True).reset_index(drop=True)
    for column in REQUIRED_ADDITIVE_COLUMNS + ["Density"]:
        if column not in edited_df.columns:
            edited_df[column] = 0.0 if column == "User Input" else None if column == "Density" else ""
    edited_df["User Input"] = pd.to_numeric(edited_df["User Input"], errors="coerce").astype(float)
    for idx in edited_df.index:
        name_val = str(edited_df.at[idx, "Name"]).strip()
        mat_val = str(edited_df.at[idx, "Material Type"]).strip()

        match = materials_db.resolve_known_material(name_val)

        if match:
            canonical_name, mat_type, state = match
            edited_df.at[idx, "Name"] = canonical_name
            edited_df.at[idx, "Material Type"] = mat_type
            edited_df.at[idx, "Physical State"] = state
            previous_name = (str(previous.at[idx, "Name"]).strip()
                             if previous is not None and idx in previous.index else canonical_name)
            density = edited_df.at[idx, "Density"]
            if pd.isna(density) or density == "" or previous_name.casefold() != canonical_name.casefold():
                edited_df.at[idx, "Density"] = default_additive_density_gcm3(canonical_name, state)
        else:
            alias = materials_db.LEGACY_MATERIAL_TYPE_ALIASES.get(mat_val.lower())
            if alias:
                edited_df.at[idx, "Material Type"] = alias

    return edited_df


def _commit_custom_identity(slurry: str, row_index: int, field: str, widget_key: str,
                            revision_key: str) -> None:
    table = st.session_state["cement_additives_dfs"][slurry].copy(deep=True)
    table.at[row_index, field] = st.session_state[widget_key].strip()
    st.session_state["cement_additives_dfs"][slurry] = _normalize_additive_rows(table)
    # Reuse the editor revision so its old source/deltas cannot undo this edit.
    st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1


def _go_to_fluid_configuration():
    """Button callbacks run before the navigation radio is instantiated."""
    st.session_state["_app_mode_key"] = "phase4"


def _commit_cement_param(slurry: str, field: str, widget_key: str) -> None:
    """BUG-01 (same protection as Phase IV's _commit_fluid_widget): commit the
    last widget edit into cement_params before a phase-switch rerun can
    garbage-collect this widget. Streamlit runs widget callbacks before
    rerouting, so an edit blurred by a navigation click still reaches the
    canonical dict even though this phase's render() never executes again."""
    value = st.session_state[widget_key]
    migrate_material_properties(st.session_state)
    entry = st.session_state.get("cement_params", {}).get(slurry)
    if isinstance(entry, dict):
        entry[field] = value
        if field == "cmt_sg":
            entry["cmt_sg_source"] = "manual"
        elif field == "base_cement" and entry.get("cmt_sg_source") == "catalog":
            entry["cmt_sg"] = catalog_cement_sg(value)


def _commit_manual_override(slurry: str, field: str, widget_key: str) -> None:
    """BUG-01 companion for the manual Yield/Mix Water inputs: commits both the
    live value and its manual_* mirror so the auto→manual reconciliation on the
    next Phase V visit restores the edited value, not a stale one."""
    value = st.session_state[widget_key]
    entry = st.session_state.get("cement_params", {}).get(slurry)
    if isinstance(entry, dict):
        entry[field] = value
        entry[f"manual_{field}"] = value


def build_salt_additive_row(item: int, name: str, material_type: str,
                            salt_pct_bwow: float, mix_water_bbl: float,
                            total_sacks: float, dead_vol_bbl: float) -> dict:
    """Keep the exported column units in lb, lb/sk and lb/bbl (not % BWOW)."""
    amounts = calculate_salt_field_amounts(
        salt_pct_bwow, mix_water_bbl, total_sacks, dead_vol_bbl
    )
    return {
        "Item": item,
        "Name": name,
        "Material Type": material_type,
        "lbs or gal": f"{round_half_up(amounts['base_lb'], 1):.1f}",
        "(lbs or gal)/sk": f"{round_half_up(amounts['lbs_per_sk'], 3):.3f}",
        "(lbs or gal)/bbl": f"{round_half_up(amounts['lbs_per_bbl'], 3):.3f}",
        "lbs or gal (with dead Vol.)": f"{round_half_up(amounts['with_dead_lb'], 1):.1f}",
    }

def get_slurry_key(slurry_name: str, prefix: str) -> str:
    sanitized = "".join(c if c.isalnum() else "_" for c in str(slurry_name)).lower()
    return f"{prefix}_{sanitized}"

def build_components(edited_df):
    powders_for_calc = []
    liquids_for_calc = []
    salt_pct_for_calc = 0.0

    for _, row in edited_df.iterrows():
        m_type, d_name = require_additive_identity(row)
        u_val = require_nonnegative_number(row.get("User Input"), d_name)
        if m_type.strip().casefold() == "cement":
            raise ValueError(f"{d_name}: cement entered as an additive needs an explicit blend design; remove this row and review the base cement")

        p_state = resolve_physical_state(m_type, row.get("Physical State"))
        # FIX: m_method is now resolved through normalize_additive_mix, the
        # single shared classifier also used by the table-building loop below
        # and by Phase VII. This guarantees a Liquid row can never be treated
        # as "Dry Blend" here (which is physically impossible) while being
        # shown as dissolved-in-water in the table — both now always agree.
        # d_name is passed so the forced-dry-blend brand list (Silica Flour,
        # Micro Silica, Hidense, Light Weight, Cenosphere, base cements) is
        # applied here too, not just in the table-building loop below.
        m_method, is_dry_blend = normalize_additive_mix(p_state, row.get("Mix Method"), d_name, m_type)

        if is_salt_additive(m_type, d_name):
            salt_pct_for_calc += u_val
        elif p_state == "Powder" or is_dry_blend:
            den_pcf = resolve_additive_density(d_name, "Powder", row.get("Density"),
                                               require_measured=materials_db.resolve_known_material(d_name) is None)
            powders_for_calc.append({
                "name": d_name,
                "percent": u_val,
                "density_pcf": den_pcf,
                "in_solution": not is_dry_blend
            })
        else:
            den_ppg, l_fac = resolve_additive_density(d_name, "Liquid", row.get("Density"),
                                                      require_measured=materials_db.resolve_known_material(d_name) is None)
            liquids_for_calc.append({
                "name": d_name,
                "gal_per_sk": u_val,
                "density_ppg": den_ppg,
                "lab_factor": l_fac
            })
    return powders_for_calc, liquids_for_calc, salt_pct_for_calc


def calculate_base_results(p, vol, effective_density, powders_for_calc, liquids_for_calc, salt_pct_for_calc):
    # Execute authentic mass balance calculation
    calc_res = calculate_slurry_from_components(
        slurry_weight_pcf=effective_density,
        slurry_volume_bbl=vol,
        cmt_sg=float(resolve_cement_sg(p)),
        water_density_pcf=WATER_DENSITY_PCF,
        salt_pct=salt_pct_for_calc,
        powders=powders_for_calc,
        liquids=liquids_for_calc
    )

    if p.get("cmt_sg_source") == "catalog":
        p["cmt_sg"] = resolve_cement_sg(p)
    # Derived formulation metrics do not change manual field Yield/Fresh Water.
    p["solution"] = calc_res["field_solution_bbl"]
    for metric in ("base_fluid_gal_sk", "mix_water_gal_sk", "mix_fluid_gal_sk"):
        p[metric] = calc_res[metric]
    return calc_res


def build_cement_tables(p, edited_df, calc_res):
    mix_w = calc_res["field_water_bbl"] if p["auto_calc"] else float(p["mix_water"])
    dead_v = float(p["dead_vol"])
    total_tank_water = mix_w + dead_v
    total_sacks = calc_res["field_sacks"] if p["auto_calc"] else float(p["total_sacks"])
    # Automatic salt quantities use full precision, like the engine.
    # Manual Override deliberately uses the selected field water volume.
    salt_water_bbl = calc_res["field_water_bbl"] if p["auto_calc"] else mix_w
    salt_sacks = calc_res["field_sacks"] if p["auto_calc"] else total_sacks
    base_cemb = str(p.get("base_cement", "Cement G Delijan")).strip() or "Cement G Delijan"

    # Table 1: Cement Slurry Blend Data
    blend_rows = [{
        "Item": 1,
        "Name": base_cemb,
        "Material Type": "Cement",
        "sks or lbs": f"{total_sacks:.1f} sks",
        "lbs / sk": "110.0"
    }]

    # Table 2: Cement Slurry Additives Data
    adds_rows = []

    for _, row in edited_df.iterrows():
        mat_type, display_name = require_additive_identity(row)
        user_val = require_nonnegative_number(row.get("User Input"), display_name)

        state = resolve_physical_state(mat_type, row.get("Physical State"))
        # FIX: same shared classifier as the mass-balance loop above, instead
        # of a locally re-derived Liquid-overrides-Dry-Blend rule. See
        # normalize_additive_mix() in engineering_tools.py for why this must
        # be the single source of truth for this decision (including the
        # forced-dry-blend brand list, now applied inside that function).
        mix_method, is_dry_blend = normalize_additive_mix(state, row.get("Mix Method"), display_name, mat_type)

        if is_salt_additive(mat_type, display_name):
            adds_rows.append(build_salt_additive_row(
                len(adds_rows) + 1, display_name, mat_type, user_val,
                salt_water_bbl, salt_sacks, dead_v
            ))
            continue

        if is_dry_blend:
            conc_lbs_sk = user_val * 1.1
            tot_lbs = conc_lbs_sk * total_sacks

            conc_display = round_half_up(conc_lbs_sk, 3)
            sk_disp = f"{conc_display:.2f}" if round(conc_display, 2) == conc_display else f"{conc_display:.3f}"
            if round(conc_display, 1) == conc_display:
                sk_disp = f"{conc_display:.1f}"

            blend_rows.append({
                "Item": len(blend_rows) + 1,
                "Name": display_name,
                "Material Type": mat_type,
                "sks or lbs": f"{round_half_up(tot_lbs, 1):.1f} lb",
                "lbs / sk": sk_disp
            })
        else:
            if state == "Powder":
                conc = user_val * 1.1
                base_amt = conc * total_sacks
                conc_per_bbl = base_amt / mix_w if mix_w > 0 else 0.0
                amt_dead_vol = conc_per_bbl * total_tank_water

                col_base = f"{round_half_up(base_amt, 1):.1f}"
                conc_display = round_half_up(conc, 3)
                col_sk = f"{conc_display:.3f}" if round(conc_display, 2) != conc_display else f"{conc_display:.2f}"
                col_bbl = f"{round_half_up(conc_per_bbl, 3):.3f}"
                col_dead = f"{round_half_up(amt_dead_vol, 1):.1f}"
            else:
                conc = user_val
                base_amt = conc * total_sacks
                conc_per_bbl = base_amt / mix_w if mix_w > 0 else 0.0
                amt_dead_vol = conc_per_bbl * total_tank_water

                base_display = round_half_up(base_amt, 2)
                dead_display = round_half_up(amt_dead_vol, 2)
                base_disp = f"{base_display:.2f}" if round(base_display, 1) != base_display else f"{base_display:.1f}"
                dead_disp = f"{dead_display:.2f}" if round(dead_display, 1) != dead_display else f"{dead_display:.1f}"
                sk_disp = f"{conc:.3f}" if round(conc, 2) != conc else f"{conc:.2f}"

                col_base = f"{base_disp} gal"
                col_sk = f"{sk_disp} gal/sk"
                col_bbl = f"{round_half_up(conc_per_bbl, 3):.3f} gal/bbl"
                col_dead = f"{dead_disp} gal"

            adds_rows.append({
                "Item": len(adds_rows) + 1,
                "Name": display_name,
                "Material Type": mat_type,
                "lbs or gal": col_base,
                "(lbs or gal)/sk": col_sk,
                "(lbs or gal)/bbl": col_bbl,
                "lbs or gal (with dead Vol.)": col_dead
            })

    blend_df = pd.DataFrame(blend_rows)
    adds_df = pd.DataFrame(adds_rows)
    total_water_note = round_half_up(total_tank_water, 1)
    note_text = f"Mix above Additives in **{total_water_note:.1f} bbl** Fresh Water at **{p['tank_name']}**."
    return blend_df, adds_df, note_text


def refresh_cement_calculations(state):
    """Rebuild derived tables from saved inputs; retain manual Yield/Water."""
    issues = []
    for slurry in state.get("fluids_config", {}).get("active", []):
        if slurry not in materials_db.CEMENT_FORMULATION_FLUIDS:
            continue
        p = state.get("cement_params", {}).get(slurry)
        df = state.get("cement_additives_dfs", {}).get(slurry)
        if not isinstance(p, dict) or not isinstance(df, pd.DataFrame):
            issues.append(f"{slurry}: open Phase V to configure the cement formulation.")
            continue
        try:
            p = dict(p)  # Commit only after the calculation and tables succeed.
            validate_cement_parameters(p)
            info = state.get("fluid_data", {}).get(slurry, {})
            volume = clean_number(info.get("volume"))
            if volume <= 0:
                raise ValueError("Phase IV slurry volume must be positive")
            density = require_positive_density(info.get("density"))
            if not 75.0 <= density <= 180.0:
                issues.append(f"{slurry}: slurry density {density:.1f} pcf is outside 75–180 pcf; correct Phase IV before export.")
                continue
            components = build_components(df)
            result = calculate_base_results(p, volume, density, *components)
            if p.get("auto_calc", True):
                p["yield"] = result["yield_ft3_per_sk"]
                p["mix_water"] = result["field_water_bbl"]
                p["total_sacks"] = result["field_sacks"]
            else:
                p["total_sacks"] = volume * BBL_TO_CUFT / p["yield"] if p["yield"] > 0 else 0.0
            blend, adds, note = build_cement_tables(p, df, result)
            state["cement_params"][slurry] = p
            state[f"cement_blend_{slurry}"] = blend
            state[f"cement_calc_{slurry}"] = adds
            state[f"cement_note_{slurry}"] = note
        except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
            issues.append(f"{slurry}: review Phase V inputs before export ({exc}).")
    return issues


def render():
    st.header("Phase V: Cement Program")
    st.markdown("Configure slurry materials, bulk blends, chemical additives, and operational mixing parameters.")
    
    # 1. Strict SSOT Tab Derivation: Directly from Phase IV ordered active sequence
    active_pipeline = st.session_state.get("fluids_config", {}).get("active", [])
    slurry_archetypes = materials_db.CEMENT_FORMULATION_FLUIDS
    active_slurries = [f for f in active_pipeline if f in slurry_archetypes]
    
    fluid_data = st.session_state.get("fluid_data", {})
    
    if not active_slurries:
        st.warning("⚠ No cement slurries were selected in Phase IV.")
        # Set the radio's value in the click callback, before main.py creates
        # the navigation widget on the next run. Mutating it here in render()
        # raises StreamlitAPIException because the radio already exists.
        st.button("→ Go to Phase IV to select slurries", type="primary",
                  on_click=_go_to_fluid_configuration)
        return
        
    job_type = st.session_state.get("job_type", 'CSG 20"')
    default_tank = materials_db.get_tank_name(job_type)

    # State Initializations
    if "cement_params" not in st.session_state:
        st.session_state["cement_params"] = {}
    if "cement_additives_dfs" not in st.session_state:
        st.session_state["cement_additives_dfs"] = {}
    if "cement_initialized_slurries" not in st.session_state:
        st.session_state["cement_initialized_slurries"] = []

    load_sig = str(st.session_state.get("last_loaded_hash", "default_project"))
    bounded = []
    for slurry in active_slurries:
        params = st.session_state["cement_params"].get(slurry, {})
        if not isinstance(params, dict):
            st.error(f"{slurry}: saved cement parameters are invalid. Restore a valid project file.")
            return
        for field, label, low, high in (
            ("cmt_sg", "Cement SG", 2.5, 3.5),
            ("dead_vol", "Dead volume (bbl)", 0.0, None),
        ):
            if field in params and not (field == "dead_vol" and params[field] is None):
                bounded.append((params, field, f"{label} - {slurry}", low, high, False))
        if not params.get("auto_calc", True):
            for field, label, low in (("yield", "Manual yield", 0.001),
                                      ("mix_water", "Manual mix water", 0.0)):
                if field in params:
                    bounded.append((params, field, f"{label} - {slurry}", low, None, False))
        if slurry in materials_db.PLACEMENT_SLURRIES and params.get("top_mode") == "Depth (m MD)" and params.get("top_depth") is not None:
            bounded.append((params, "top_depth", f"Top depth - {slurry}", 0.0, None, False))
    if repair_invalid_inputs(bounded, f"phase5_{load_sig}"):
        return
    tabs = st.tabs(active_slurries)
    
    # Material Type options (16 canonical categories from the master taxonomy)
    all_mats = list(dict.fromkeys(materials_db.MATERIAL_TYPES + ["Other (Custom)"]))
    # Name options: every commercial/brand Name across all Material Types, flat
    # (st.data_editor cannot show a Name list that depends on another column's
    # value in the same row) — picking a recognized Name auto-locks Material
    # Type + Physical State to the correct pair right after the edit below.
    all_names = list(dict.fromkeys(materials_db.ALL_MATERIAL_NAMES + ["Other (Custom)"]))
    
    for i, slurry in enumerate(active_slurries):
        with tabs[i]:
            st.subheader(f"{slurry} Slurry Formulation")
            
            # Fluid data from Phase IV
            f_info = fluid_data.get(slurry, {})
            fluid_issue = None
            try:
                vol = clean_number(f_info.get("volume"))
                if vol <= 0:
                    raise ValueError("Phase IV slurry volume must be positive")
                effective_density = require_positive_density(f_info.get("density"))
            except ValueError as exc:
                fluid_issue = exc
                vol = 0.0
                effective_density = 0.0
                st.error(f"{slurry}: invalid Phase IV fluid value ({exc}). Review Phase IV before calculating.")
                # Keep the formulation editor available while Phase IV is
                # incomplete. Only the calculation depends on its fluid data.

            # FIX (confirmed via direct numerical test of calculate_slurry_from_
            # components): the mass-balance formula's denominator is
            # (slurry_weight_pcf - water_density_pcf) at zero salt, so as the
            # entered Slurry Weight approaches fresh water's ~62.4 pcf, the
            # water-per-sack result explodes toward +/-infinity and flips sign
            # right at that point; below ~62.4 pcf it goes strongly negative,
            # which the existing `if yield_ft3_per_sk > 0` guard then silently
            # collapses to a bland 0.0 sacks — indistinguishable from a normal
            # "nothing entered yet" result, not an obvious error. Nothing
            # constrains this Density field (a free-text field carried over
            # from Phase IV) to a physically sane cement-slurry range, so a
            # single dropped digit (126 -> 26) or pasting mud density instead
            # of slurry density silently reaches this formula. Warn the same
            # way Phase II/III already does for TVD>MD / BHST<80.
            if effective_density and not (75.0 <= effective_density <= 180.0):
                st.error(
                    f"✕ **Physically Implausible Slurry Weight:** {effective_density:.1f} pcf for {slurry} is outside the "
                    "realistic range for a cement slurry (~75-180 pcf). Near fresh water's density (~62.4 pcf) the "
                    "mass-balance formula becomes numerically unstable and can silently produce 0 sacks or a nonsensical "
                    "water volume. Please verify this is the intended Slurry Weight, not a mud density or a typo."
                )
                st.button(f"→ Fix {slurry} density in Phase IV", key=f"fix_den_{slurry}",
                          on_click=_go_to_fluid_configuration)
            
            p = st.session_state["cement_params"].setdefault(
                slurry, {
                    "yield": 1.180, 
                    "mix_water": 119.0, 
                    "dead_vol": None,
                    "tank_name": default_tank,
                    "last_job_type": job_type,
                    "base_cement": "Cement G Delijan",
                    "cmt_sg": catalog_cement_sg(),
                    "cmt_sg_source": "catalog",
                    "total_sacks": 0.0,
                    "auto_calc": True
                }
            )
            p.setdefault("dead_vol", None)
            p.setdefault("tank_name", default_tank)
            p.setdefault("base_cement", "Cement G Delijan")
            p.setdefault("cmt_sg", catalog_cement_sg(p["base_cement"]))
            p.setdefault("cmt_sg_source", "catalog")
            p["cmt_sg"] = resolve_cement_sg(p)
            p.setdefault("auto_calc", True)

            # --- TOP LEVEL PARAMETERS: Cement, Tank, Dead Vol ---
            col_t1, col_t2, col_t3, col_t4 = st.columns([1.5, 1.2, 1.8, 1.2])
            with col_t1:
                cement_options = materials_db.get_names_for_material_type("Cement")
                cur_cement = str(p.get("base_cement", "Cement G Delijan")).strip()
                if cur_cement not in cement_options:
                    # Legacy project (pre master-list update): heal old short
                    # forms ("G Delijan" / "D Delijan" / bare "G" or "D") to
                    # the matching new class instead of always defaulting to G.
                    legacy_lower = cur_cement.lower()
                    if legacy_lower.startswith("d") or " d " in f" {legacy_lower} ":
                        cur_cement = "Cement D Delijan"
                    else:
                        cur_cement = "Cement G Delijan"
                cement_idx = cement_options.index(cur_cement) if cur_cement in cement_options else 0
                cemb_key = f"_{get_slurry_key(slurry, 'cemb')}_{load_sig}"
                p["base_cement"] = st.selectbox(
                    f"Base Cement - {slurry}",
                    options=cement_options,
                    index=cement_idx,
                    key=cemb_key,
                    on_change=_commit_cement_param,
                    args=(slurry, "base_cement", cemb_key)
                )
            with col_t2:
                sg_ref = materials_db.CEMENT_SG_REFERENCE
                sg_ref_text = " | ".join(f"{k}: {v:.2f}" for k, v in sg_ref.items())
                sg_key = (f"_{get_slurry_key(slurry, 'sg')}_{load_sig}_"
                          f"{st.session_state['material_property_schema']}_{fingerprint(p['base_cement'])[:10]}_"
                          f"{st.session_state.get('_' + get_slurry_key(slurry, 'cmt_sg_revision'), 0)}")
                p["cmt_sg"] = st.number_input(
                    f"Cement SG - {slurry}",
                    min_value=2.5,
                    max_value=3.5,
                    step=0.01,
                    value=float(p.get("cmt_sg", 3.20)),
                    format="%.2f",
                    key=sg_key,
                    on_change=_commit_cement_param,
                    args=(slurry, "cmt_sg", sg_key),
                    help=f"Specific Gravity of base dry cement. Reference: {sg_ref_text}."
                )
            with col_t3:
                job_tank_options = materials_db.get_available_tanks(job_type)
                if not job_tank_options:
                    job_tank_options = [default_tank]
                cur_tank = p.get("tank_name", default_tank)
                tank_idx = job_tank_options.index(cur_tank) if cur_tank in job_tank_options else 0
                tank_key = f"_{get_slurry_key(slurry, 'tank_choice')}_{load_sig}"
                selected_tank = st.selectbox(
                    f"Mixing Tank - {slurry}",
                    options=job_tank_options,
                    index=tank_idx,
                    key=tank_key,
                    on_change=_commit_cement_param,
                    args=(slurry, "tank_name", tank_key)
                )
                p["tank_name"] = selected_tank
            with col_t4:
                dv_key = f"_{get_slurry_key(slurry, 'dv')}_{load_sig}"
                if dv_key not in st.session_state:
                    st.session_state[dv_key] = p["dead_vol"]
                p["dead_vol"] = st.number_input(
                    f"Dead Vol (bbl) - {slurry}",
                    min_value=0.0,
                    step=1.0,
                    value=None,
                    key=dv_key,
                    on_change=_commit_cement_param,
                    args=(slurry, "dead_vol", dv_key),
                    help="Unpumpable liquid volume retained in the mixing tank."
                )

            if slurry in materials_db.PLACEMENT_SLURRIES:
                st.markdown("#### Slurry Placement")
                st.caption("Enter the approved top of cement for this slurry. Select Surface only when the planned top is the surface; an unknown top remains explicitly unreported.")
                top_options = ["Not entered", "Depth (m MD)"]
                if slurry != "Tail":
                    top_options.append("Surface")
                top_mode = p.get("top_mode")
                if slurry == "Tail" and top_mode == "Surface":
                    top_mode = "Not entered"
                if top_mode not in top_options:
                    top_mode = "Depth (m MD)" if p.get("top_depth") not in (None, "", 0) else "Not entered"
                if p.get("top_job_type") not in (None, job_type):
                    top_mode = "Not entered"
                    p.pop("draft_top_depth", None)
                if p.get("draft_top_job_type") not in (None, job_type):
                    p.pop("draft_top_depth", None)
                mode_key = f"_top_mode_{get_slurry_key(slurry, 'slurry')}_{fingerprint(job_type)[:10]}_{load_sig}"
                p["top_mode"] = st.selectbox(f"Top of cement - {slurry}", top_options,
                                             index=top_options.index(top_mode), key=mode_key,
                                             on_change=_commit_cement_param,
                                             args=(slurry, "top_mode", mode_key))
                if p["top_mode"] == "Depth (m MD)":
                    initial_depth = p.get("top_depth") or p.get("draft_top_depth") or 0.0
                    if slurry == "Tail":
                        initial_depth = None
                        for value in (p.get("top_depth"), p.get("draft_top_depth")):
                            _, depth = top_label({"top_mode": "Depth (m MD)", "top_depth": value})
                            if depth is not None:
                                initial_depth = depth
                                break
                        else:
                            target = target_depth(st.session_state.get("hardware_table"), job_type,
                                                  st.session_state.get("placement_config", {}))
                            if target is not None and target > 150.0:
                                initial_depth = target - 150.0
                    topd_key = f"_top_depth_{get_slurry_key(slurry, 'slurry')}_{fingerprint(job_type)[:10]}_{load_sig}"
                    p["top_depth"] = st.number_input(
                        f"Top of cement depth (m MD) - {slurry}",
                        min_value=0.0, step=1.0, value=float(initial_depth) if initial_depth is not None else None,
                        key=topd_key,
                        on_change=_commit_cement_param,
                        args=(slurry, "top_depth", topd_key),
                        help="0 means the depth has not yet been entered."
                    )
                    if p["top_depth"] is not None and p["top_depth"] > 0.0:
                        p["draft_top_depth"] = p["top_depth"]
                        p["draft_top_job_type"] = job_type
                    else:
                        p.pop("draft_top_depth", None)
                else:
                    p["top_depth"] = 0.0 if p["top_mode"] == "Surface" else None
                p["top_job_type"] = job_type

            st.markdown("---")
            st.markdown("#### Materials & Additives Formulation")
            st.caption("**Mix Method Guide:** Choose **'Dry Blend'** for powders pre-blended dry with bulk cement (no dead volume penalty). Choose **'In Mix Water'** for chemicals dissolved in the mixing tank.")
            st.caption("**NaCl / Salt:** Enter % BWOW (weight of water). Salt is always included in mix water; its totals include the selected water volume and, in the last column, dead volume.")
            st.caption("**Name Guide:** Pick a listed commercial brand to auto-set its Material Type & Physical State. Pick **'Other (Custom)'** to enter a material not on the master list, then set Material Type/Physical State yourself.")
            st.caption("ℹ️ For a row with a *recognized brand* in Name, Material Type/Physical State are locked to that brand's correct values — if you edit them by hand on such a row, they'll snap back on the next edit. This is intentional (a known brand can't be miscategorized), not a bug. To set Material Type/Physical State freely, change Name to **'Other (Custom)'** first.")
            
            # Initialize only when the key is absent: old projects can contain
            # a full table without the newer initialized-slurries marker.
            # A deliberately emptied table still has a key and stays empty.
            if slurry not in st.session_state["cement_additives_dfs"]:
                st.session_state["cement_additives_dfs"][slurry] = pd.DataFrame(columns=REQUIRED_ADDITIVE_COLUMNS)
            if slurry not in st.session_state["cement_initialized_slurries"]:
                st.session_state["cement_initialized_slurries"].append(slurry)

            current_df = st.session_state["cement_additives_dfs"].get(slurry, pd.DataFrame(columns=REQUIRED_ADDITIVE_COLUMNS))
            current_df = _normalize_additive_rows(current_df)
            st.session_state["cement_additives_dfs"][slurry] = current_df
            revision_key = f"_editor_additives_{get_slurry_key(slurry, 'slurry')}_revision"
            editor_key = f"_editor_{get_slurry_key(slurry, 'additives')}_{load_sig}_{st.session_state.get(revision_key, 0)}"
            # Keep options stable with the mounted editor's source frame.
            option_df = (st.session_state.get(f"_editor_source_{editor_key}", current_df)
                         if editor_key in st.session_state else current_df)
            
            edited_df = persistent_data_editor(
                current_df,
                persist_to=("cement_additives_dfs", slurry),
                normalize=_normalize_additive_rows,
                column_order=REQUIRED_ADDITIVE_COLUMNS + ["Density"],
                column_config={
                    "Material Type": st.column_config.SelectboxColumn(
                        "Material Type",
                        options=list(dict.fromkeys(all_mats + option_df["Material Type"].dropna().tolist())),
                        default="Other (Custom)",
                        help="Auto-set from Name for recognized brands. Only meaningful on its own for 'Other (Custom)' rows.",
                        required=True
                    ),
                    "Name": st.column_config.SelectboxColumn(
                        "Name / Commercial Brand",
                        options=list(dict.fromkeys(all_names + option_df["Name"].dropna().tolist())),
                        default="Other (Custom)",
                        help="Pick a listed brand to auto-lock Material Type & Physical State, or 'Other (Custom)' for a material not on the master list.",
                        required=True
                    ),
                    "Physical State": st.column_config.SelectboxColumn(
                        "Physical State",
                        options=["Powder", "Liquid"],
                        default="Powder",
                        required=True
                    ),
                    "Mix Method": st.column_config.SelectboxColumn(
                        "Mix Method",
                        options=["In Mix Water", "Dry Blend"],
                        default="In Mix Water",
                        help="'Dry Blend' = Bulk powders. 'In Mix Water' = Tank chemicals. Some brands force Dry Blend regardless of this choice.",
                        required=True
                    ),
                    "User Input": st.column_config.NumberColumn(
                        "Concentration (% or gal/sk)",
                        help="Concentration (% BWOC for powders, gal/sk for liquids, % BWOW for salt). Cannot be negative.",
                        default=0.000,
                        min_value=0.0,
                        format="%.3f",
                        step=0.001,
                        required=True
                    ),
                    "Density": st.column_config.NumberColumn(
                        "Measured Density (g/cm³)",
                        help="Catalog density fills automatically. Edit to use a measured override; required for every custom material. This is the material SG input.",
                        min_value=0.0, format="%.2f"
                    ),
                },
                num_rows="dynamic",
                key=editor_key,
                width='stretch'
            )
            
            normalized = st.session_state["cement_additives_dfs"][slurry]
            if not normalized.equals(edited_df):
                # Show the corrected Name/classification/default in the same row.
                st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
                st.rerun()
            edited_df = normalized
            for idx, row in edited_df.iterrows():
                for field, catalog in (("Material Type", all_mats), ("Name", all_names)):
                    value = str(row.get(field) or "").strip()
                    if value == "Other (Custom)" or value not in catalog:
                        key = f"_custom_{get_slurry_key(slurry, 'additives')}_{field}_{idx}_{load_sig}_{st.session_state.get(revision_key, 0)}_{fingerprint(value)}"
                        if key not in st.session_state:
                            st.session_state[key] = "" if value == "Other (Custom)" else value
                        st.text_input(f"Custom {field} - {slurry} row {idx + 1}", key=key,
                                      on_change=_commit_custom_identity,
                                      args=(slurry, idx, field, key, revision_key))

            # FIX (requested, Level 2 #6): normalize_additive_mix() (used
            # both here and by the mass-balance engine right below) silently
            # reclassifies a row's Mix Method whenever the operator's own
            # selection is physically impossible for that material — a
            # Liquid can't be "Dry Blend"; certain brands (base cements,
            # Silica Flour, Micro Silica, Hidense, Light Weight, Cenosphere)
            # are always forced dry-blend regardless of what's picked. That
            # correction is the right engineering call, but it used to be
            # invisible: every downstream number already used the corrected
            # classification while the table on screen kept showing the
            # operator's original selection, with nothing anywhere
            # explaining a mismatch if one went looking for why a number
            # didn't match what they'd picked. This makes every such
            # correction explicit instead of silent, without changing which
            # classification actually gets used (still normalize_additive_mix,
            # same as before — this block only reports its result).
            _override_rows = []
            for _, _row in edited_df.iterrows():
                _mat_type = str(_row.get("Material Type") or "").strip()
                _name = str(_row.get("Name") or "").strip()
                _display_name = _name if _name and _name != "Other (Custom)" else _mat_type
                if not _display_name or _display_name in ["None", "nan", "Other (Custom)"]:
                    continue
                _state = resolve_physical_state(_mat_type, _row.get("Physical State"))
                _user_mm = str(_row.get("Mix Method") or "").strip()
                _eff_mm, _ = normalize_additive_mix(_state, _user_mm, _display_name, _mat_type)
                if _user_mm and _user_mm != _eff_mm:
                    _override_rows.append({
                        "Material": _display_name,
                        "You selected": _user_mm,
                        "System uses": _eff_mm,
                        "Why": ("NaCl uses % BWOW and is dissolved in mix water"
                                if is_salt_additive(_mat_type, _display_name)
                                else "Liquid additives are always mixed in water" if _state == "Liquid"
                                else "Forced dry-blend per material database")
                    })
            if _override_rows:
                with st.expander(f"ℹ️ {len(_override_rows)} row(s) auto-corrected by the material database", expanded=True):
                    st.table(pd.DataFrame(_override_rows))

            # -------------------------------------------------------------
            # MASS BALANCE ENGINE (FROM CMT CALCULATOR 03-3.XLS)
            # -------------------------------------------------------------
            if p["dead_vol"] is None:
                st.info(f"Enter Dead Vol (bbl) - {slurry} to calculate the cement program; enter 0 if none.")
                continue
            if edited_df["User Input"].isna().any():
                st.info(f"Complete the concentration for each new {slurry} additive row to calculate the slurry.")
                continue
            if fluid_issue is not None:
                continue
            try:
                powders_for_calc, liquids_for_calc, salt_pct_for_calc = build_components(edited_df)
            except ValueError as exc:
                st.error(f"Cannot calculate {slurry}: {exc}")
                continue

            # Plausibility guardrails (warn only, never block — a real design
            # may occasionally need an unusual value, and Streamlit's
            # min_value=0.0 on the table column already blocks fresh negative
            # entry; these catch the other error class found by testing: a
            # digit/decimal-point typo that lands on a number which is still
            # numerically valid and produces a normal-looking-but-wrong
            # result with no other warning anywhere (e.g. "350" typed instead
            # of "35" for % BWOC). Thresholds are deliberately generous
            # (no legitimate single powder additive is known to exceed 100%
            # BWOC and no legitimate liquid additive exceeds ~10 gal/sk),
            # so this only fires
            # on values that are implausible for ANY additive category, not
            # just unusual for one.
            for pw in powders_for_calc:
                if pw["percent"] < 0:
                    st.warning(f"⚠ **Data Check:** {pw['name']} has a negative concentration ({pw['percent']:.3f}% BWOC) — likely from a loaded project file bypassing normal entry limits.")
                elif pw["percent"] > 100.0:
                    st.warning(f"⚠ **Plausibility Check:** {pw['name']} is set to {pw['percent']:.1f}% BWOC — this is unusually high for any single additive. Please verify this isn't a typo (e.g. an extra digit).")
            for lq in liquids_for_calc:
                if lq["gal_per_sk"] < 0:
                    st.warning(f"⚠ **Data Check:** {lq['name']} has a negative dosage ({lq['gal_per_sk']:.3f} gal/sk) — likely from a loaded project file bypassing normal entry limits.")
                elif lq["gal_per_sk"] > 10.0:
                    st.warning(f"⚠ **Plausibility Check:** {lq['name']} is set to {lq['gal_per_sk']:.2f} gal/sk — this is unusually high for a liquid additive. Please verify this isn't a typo.")

            try:
                calc_res = calculate_base_results(p, vol, effective_density, powders_for_calc, liquids_for_calc, salt_pct_for_calc)
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                st.error(f"Cannot calculate {slurry}: {exc}. Review the Phase IV density and Phase V formulation.")
                continue

            # Auto-calculation vs Manual Override option
            st.markdown("---")
            col_m1, col_m2 = st.columns([2.5, 1.5])
            with col_m1:
                st.markdown("#### Slurry Yield & Hydraulic Results")
            with col_m2:
                manual_override = st.checkbox(
                    "Manual Override (Custom Yield/Water)",
                    value=not p.get("auto_calc", True),
                    key=f"_{get_slurry_key(slurry, 'override')}_{load_sig}",
                    help="Check to manually type custom Yield and Fresh Water (bbl) instead of the CMT Calculator engine."
                )
                was_auto = p.get("auto_calc", True)
                p["auto_calc"] = not manual_override
                if (was_auto and manual_override
                        and p.get("manual_job_type") == job_type
                        and "manual_yield" in p and "manual_mix_water" in p):
                    p["yield"] = p["manual_yield"]
                    p["mix_water"] = p["manual_mix_water"]

            # The engineer can switch to manual immediately after an auto
            # calculation produced a negative Yield/Water. Guard this same
            # run before Streamlit sees an out-of-range number_input value.
            if not p["auto_calc"]:
                manual_fields = [(p, "yield", f"Manual yield - {slurry}", 0.001, None, False),
                                 (p, "mix_water", f"Manual mix water - {slurry}", 0.0, None, False)]
                if repair_invalid_inputs(manual_fields, f"phase5_{load_sig}"):
                    return

            if p["auto_calc"]:
                # Synchronize automatically calculated results
                p["yield"] = calc_res["yield_ft3_per_sk"]
                p["mix_water"] = calc_res["field_water_bbl"]
                p["total_sacks"] = calc_res["field_sacks"]
                
                # Display Live Metrics Cards
                c_met1, c_met2, c_met3, c_met4 = st.columns(4)
                c_met1.metric("Calculated Yield", f"{p['yield']:.3f} cuft/sk", help="From CMT Calculator equation (Cell O3)")
                c_met2.metric("Total Sacks", f"{p['total_sacks']:.1f} sks", f"~{p['total_sacks']*0.05:.1f} MT")
                c_met3.metric("Fresh Water", f"{p['mix_water']:.2f} bbl", help="Pure Fresh Water required for the field slurry, bbl; excludes Dead Volume")
                c_met4.metric("Total Solution", f"{calc_res['field_solution_bbl']:.1f} bbl", help="Total fluid volume including dissolved chemicals (Cell O6)")
                c_base, c_water, c_fluid = st.columns(3)
                c_base.metric("Base Fluid", f"{p['base_fluid_gal_sk']:.3f} gal/sk", help="Pure Fresh Water per sack")
                c_water.metric("Mix Water", f"{p['mix_water_gal_sk']:.3f} gal/sk", help="Base Fluid plus dissolved NaCl absolute volume per sack")
                c_fluid.metric("Mix. Fluid", f"{p['mix_fluid_gal_sk']:.3f} gal/sk", help="Mix Water plus In-Mix-Water powder absolute volume and liquid additives per sack; excludes Dead Volume")
            else:
                # Manual entry fields if user overrides
                col_ov1, col_ov2, col_ov3 = st.columns(3)
                with col_ov1:
                    yd_ov_key = f"_{get_slurry_key(slurry, 'yd_ov')}_{load_sig}"
                    p["yield"] = st.number_input(
                        f"Custom Yield (cuft/sk)",
                        min_value=0.001,
                        step=0.001,
                        value=float(p.get("yield", 1.18)),
                        format="%.3f",
                        key=yd_ov_key,
                        on_change=_commit_manual_override,
                        args=(slurry, "yield", yd_ov_key)
                    )
                with col_ov2:
                    mw_ov_key = f"_{get_slurry_key(slurry, 'mw_ov')}_{load_sig}"
                    p["mix_water"] = st.number_input(
                        f"Custom Fresh Water (bbl)",
                        min_value=0.0,
                        step=1.0,
                        value=float(p.get("mix_water", 119.0)),
                        help="Operational Fresh Water override in bbl; excludes Dead Volume and preserves the entered value",
                        key=mw_ov_key,
                        on_change=_commit_manual_override,
                        args=(slurry, "mix_water", mw_ov_key)
                    )
                with col_ov3:
                    total_sacks_manual = (vol * BBL_TO_CUFT) / p["yield"] if p["yield"] > 0 else 0.0
                    p["total_sacks"] = total_sacks_manual
                    st.metric("Total Sacks", f"{p['total_sacks']:.1f} sks", f"~{p['total_sacks']*0.05:.1f} MT")
                p["manual_yield"] = p["yield"]
                p["manual_mix_water"] = p["mix_water"]
                p["manual_job_type"] = job_type

            # -------------------------------------------------------------
            # SEPARATE TABLES: BLEND DATA vs ADDITIVES DATA
            # -------------------------------------------------------------
            blend_df, adds_df, note_text = build_cement_tables(p, edited_df, calc_res)

            # Persistent session sync for Phase VII and Phase X
            st.session_state[f"cement_blend_{slurry}"] = blend_df
            st.session_state[f"cement_calc_{slurry}"] = adds_df

            # UI Display
            st.markdown(f"##### 1. {slurry} Cement Slurry Blend Data (Bulk & Dry Powders)")
            st.table(blend_df)
            
            st.markdown(f"##### 2. {slurry} Cement Slurry Additives Data (Mix Water Solution)")
            if not adds_df.empty:
                st.table(adds_df)
            else:
                st.info("No chemical additives configured in mix water.")

            st.session_state[f"cement_note_{slurry}"] = note_text
            st.info(f"**Generated Note:** {note_text}")
