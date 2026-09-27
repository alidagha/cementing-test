# phase_6_spacer.py
import streamlit as st
import pandas as pd
import materials_db
from input_guard import repair_invalid_inputs
from engineering_tools import round_half_up, clean_number
from editor_state import persistent_data_editor

REQUIRED_SPACER_COLS = ["Chemical", "User Input (% or gal)", "Weighting Agent Type"]

def _go_to_fluid_configuration():
    """Select the target phase before the sidebar navigation radio is mounted."""
    st.session_state["_app_mode_key"] = "phase4"

def get_spacer_key(name: str, prefix: str) -> str:
    sanitized = "".join(c if c.isalnum() else "_" for c in str(name)).lower()
    return f"{prefix}_{sanitized}"

def render():
    st.header("Phase VI: Pre-flush & Spacer")
    st.markdown("Configure Pre-flush wash systems and Spacer chemical formulations.")

    load_sig = str(st.session_state.get("last_loaded_hash", "default_project"))
    
    # 1. Strict SSOT Derivation from Phase IV
    active_pipeline = st.session_state.get("fluids_config", {}).get("active", [])
    fluid_data = st.session_state.get("fluid_data", {})
    
    has_preflush = "Pre Flush" in active_pipeline
    spacer_archetypes = ["Spacer", "Spacer Ahead", "Spacer Behind"]
    active_spacers = [f for f in active_pipeline if f in spacer_archetypes]
    
    # Invalidate stale Pre-flush state if deselected upstream
    if not has_preflush:
        st.session_state["preflush_calc"] = None

    if not has_preflush and not active_spacers:
        st.warning("⚠ Neither Pre-flush nor Spacer was selected in Phase IV.")
        st.button("→ Go to Phase IV to select fluids", type="primary",
                  on_click=_go_to_fluid_configuration)
        return

    # Canonical State Initializations
    if "preflush_config" not in st.session_state:
        st.session_state["preflush_config"] = {
            "type": "Combined (Water + NaCl + Wash)",
            "nacl_multiplier": 126.0,
            "wash_multiplier": 3.0
        }
    if "spacer_dfs" not in st.session_state:
        st.session_state["spacer_dfs"] = {}
    if "spacer_initialized_names" not in st.session_state:
        st.session_state["spacer_initialized_names"] = []
    if has_preflush:
        config = st.session_state["preflush_config"]
        kind = config.get("type", "Combined (Water + NaCl + Wash)")
        bounded = []
        if kind in ("Brine (Water + NaCl)", "Combined (Water + NaCl + Wash)", "Combined / Custom") and "nacl_multiplier" in config:
            bounded.append((config, "nacl_multiplier", "Preflush salt ratio", 0.0, None, False))
        if kind in ("Water + Chemical Wash", "Chemical Wash", "Combined (Water + NaCl + Wash)", "Combined / Custom") and "wash_multiplier" in config:
            bounded.append((config, "wash_multiplier", "Preflush wash ratio", 0.0, None, False))
        if repair_invalid_inputs(bounded, f"phase6_{load_sig}"):
            return

    # -------------------------------------------------------------
    # 1. PRE-FLUSH CONFIGURATION
    # -------------------------------------------------------------
    if has_preflush:
        st.subheader("Pre-flush Formulation")
        pf_info = fluid_data.get("Pre Flush", {})
        pf_vol = float(pf_info.get("volume", 0.0))
        pf_density_str = str(pf_info.get("density", "80.0"))
        pf_eff_density = float(pf_info.get("effective_density", 80.0))

        st.info(
            f"**Pre-flush Total Volume (From Phase IV):** {pf_vol:.1f} bbl | "
            f"**Target Density (From Phase IV):** {pf_density_str} pcf"
        )

        pf_cfg = st.session_state["preflush_config"]
        pf_types = [
            "Fresh Water Only",
            "Water + Chemical Wash",
            "Brine (Water + NaCl)",
            "Combined (Water + NaCl + Wash)"
        ]
        
        cur_type = pf_cfg.get("type", "Combined (Water + NaCl + Wash)")
        if cur_type in ["Chemical Wash", "Water + Chemical Wash"]:
            cur_type = "Water + Chemical Wash"
        elif cur_type in ["Combined / Custom", "Combined (Water + NaCl + Wash)"]:
            cur_type = "Combined (Water + NaCl + Wash)"

        type_idx = pf_types.index(cur_type) if cur_type in pf_types else 3
        
        # Transient key starts with '_' to avoid JSON bloat
        selected_type = st.selectbox(
            "Pre-flush Fluid Type",
            options=pf_types,
            index=type_idx,
            key=f"_pf_type_select_{load_sig}"
        )
        pf_cfg["type"] = selected_type

        # Engineering Physical Guardrail
        if selected_type == "Fresh Water Only" and pf_eff_density > 65.0:
            st.warning(
                f"**Engineering Note:** Pure fresh water has a physical density of ~62.4 pcf. "
                f"Your Phase IV design density is **{pf_eff_density:.1f} pcf**. "
                "Consider using Brine (Water + NaCl) if density maintenance is required."
            )

        nacl_mult = 0.0
        wash_mult = 0.0
        nacl_amt = 0.0
        wash_amt = 0.0
        water_amt = round_half_up(pf_vol, 1)

        if selected_type == "Fresh Water Only":
            st.success(f"**Water Volume Required:** {water_amt:.1f} bbl (Pure Fresh Water - No Additives)")
            st.info(f"**Generated Note:** Pump **{water_amt:.1f} bbl** Fresh Water ahead as mechanical wash.")

        elif selected_type == "Water + Chemical Wash":
            col1, col2, col3 = st.columns(3)
            with col1:
                st.info(f"**Base Water:**\n\n**{water_amt:.1f}** bbl")
            with col2:
                wash_mult = st.number_input(
                    "Wash Ratio (gal/bbl water)",
                    min_value=0.0,
                    step=0.5,
                    value=float(pf_cfg.get("wash_multiplier", 3.0)),
                    key=f"_pf_wash_m_{load_sig}"
                )
                pf_cfg["wash_multiplier"] = wash_mult
            with col3:
                wash_amt = round_half_up(pf_vol * wash_mult, 1)
                st.success(f"**Chemical Wash Amount:**\n\n**{wash_amt:.1f}** gal")
            st.info(f"**Generated Note:** Mix **{wash_amt:.1f} gal** Chemical Wash in **{water_amt:.1f} bbl** Fresh Water.")

        elif selected_type == "Brine (Water + NaCl)":
            col1, col2, col3 = st.columns(3)
            with col1:
                st.info(f"**Base Water:**\n\n**{water_amt:.1f}** bbl")
            with col2:
                nacl_mult = st.number_input(
                    "NaCl Ratio (lbs/bbl water)",
                    min_value=0.0,
                    step=1.0,
                    value=float(pf_cfg.get("nacl_multiplier", 126.0)),
                    key=f"_pf_nacl_m_{load_sig}"
                )
                pf_cfg["nacl_multiplier"] = nacl_mult
            with col3:
                nacl_amt = round_half_up(pf_vol * nacl_mult, 1)
                st.success(f"**NaCl Amount:**\n\n**{nacl_amt:.1f}** lbs")
            st.info(f"**Generated Note:** Dissolve **{nacl_amt:.1f} lbs** NaCl in **{water_amt:.1f} bbl** Fresh Water.")

        else:  # Combined (Water + NaCl + Wash)
            col1, col2, col3, col4 = st.columns([1.2, 1.2, 1.2, 1.2])
            with col1:
                st.info(f"**Base Water:**\n\n**{water_amt:.1f}** bbl")
            with col2:
                nacl_mult = st.number_input(
                    "NaCl (lbs/bbl)",
                    min_value=0.0,
                    step=1.0,
                    value=float(pf_cfg.get("nacl_multiplier", 126.0)),
                    key=f"_pf_nacl_m_{load_sig}"
                )
                pf_cfg["nacl_multiplier"] = nacl_mult
                nacl_amt = round_half_up(pf_vol * nacl_mult, 1)
                st.success(f"**NaCl:** {nacl_amt:.1f} lbs")
            with col3:
                wash_mult = st.number_input(
                    "Wash (gal/bbl)",
                    min_value=0.0,
                    step=0.5,
                    value=float(pf_cfg.get("wash_multiplier", 3.0)),
                    key=f"_pf_wash_m_{load_sig}"
                )
                pf_cfg["wash_multiplier"] = wash_mult
                wash_amt = round_half_up(pf_vol * wash_mult, 1)
                st.success(f"**Wash:** {wash_amt:.1f} gal")
            with col4:
                st.metric("Total Fluid", f"{water_amt:.1f} bbl")
            st.info(f"**Generated Note:** Dissolve **{nacl_amt:.1f} lbs** NaCl and mix **{wash_amt:.1f} gal** Chemical Wash in **{water_amt:.1f} bbl** Fresh Water.")

        # Expose payload for Phase X report automation
        st.session_state["preflush_calc"] = {
            "type": selected_type,
            "volume_bbl": pf_vol,
            "density_pcf": pf_density_str,
            "effective_density": pf_eff_density,
            "nacl_lbs": nacl_amt,
            "wash_gal": wash_amt,
            "water_bbl": water_amt,
            "nacl_multiplier": nacl_mult,
            "wash_multiplier": wash_mult
        }

        st.markdown("---")

    # -------------------------------------------------------------
    # 2. SPACER CONFIGURATION
    # -------------------------------------------------------------
    if active_spacers:
        st.subheader("Spacer Formulation")
        tabs = st.tabs(active_spacers)

        for i, spacer_name in enumerate(active_spacers):
            with tabs[i]:
                sp_info = fluid_data.get(spacer_name, {})
                sp_vol = float(sp_info.get("volume", 0.0))
                sp_density_str = str(sp_info.get("density", "80.0"))

                st.info(
                    f"**Total Volume (From Phase IV):** {sp_vol:.1f} bbl | "
                    f"**Design Density (From Phase IV):** {sp_density_str} pcf"
                )

                # Keep saved formulations even if an old project lacks the
                # initialized-names marker; empty tables also stay empty.
                if spacer_name not in st.session_state["spacer_dfs"]:
                    st.session_state["spacer_dfs"][spacer_name] = pd.DataFrame(columns=REQUIRED_SPACER_COLS)
                if spacer_name not in st.session_state["spacer_initialized_names"]:
                    st.session_state["spacer_initialized_names"].append(spacer_name)

                current_sp_df = st.session_state["spacer_dfs"].get(spacer_name, pd.DataFrame(columns=REQUIRED_SPACER_COLS))
                editor_key = f"_editor_spacer_{get_spacer_key(spacer_name, 'tbl')}_{load_sig}"
                
                edited_df = persistent_data_editor(
                    current_sp_df,
                    persist_to=("spacer_dfs", spacer_name),
                    column_config={
                        "Chemical": st.column_config.SelectboxColumn(
                            "Chemical",
                            options=materials_db.SPACER_CHEMICALS,
                            required=True
                        ),
                        "User Input (% or gal)": st.column_config.NumberColumn(
                            "Input",
                            help="Cannot be negative.",
                            default=0.0,
                            min_value=0.0,
                            format="%.3f",
                            step=0.001
                        ),
                        "Weighting Agent Type": st.column_config.SelectboxColumn(
                            "Agent (if applicable)",
                            options=["-"] + materials_db.WEIGHTING_AGENTS,
                            default="-"
                        )
                    },
                    num_rows="dynamic",
                    key=editor_key,
                    width='stretch'
                )

                # Defensive Column Verification
                if edited_df is None:
                    edited_df = pd.DataFrame(columns=REQUIRED_SPACER_COLS)
                else:
                    for c in REQUIRED_SPACER_COLS:
                        if c not in edited_df.columns:
                            edited_df[c] = 0.0 if c == "User Input (% or gal)" else "-"

                # Keep an intentionally cleared dosage empty. Converting it
                # to zero would silently change the formulation and mark an
                # unfinished chemical row as complete after navigation.
                edited_df["User Input (% or gal)"] = pd.to_numeric(
                    edited_df["User Input (% or gal)"], errors="coerce"
                ).astype(float)

                st.session_state["spacer_dfs"][spacer_name] = edited_df
                if edited_df["User Input (% or gal)"].isna().any():
                    st.info(f"Complete the missing dosage in each {spacer_name} chemical row before using this formulation.")
