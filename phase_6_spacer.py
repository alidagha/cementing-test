# phase_6_spacer.py
import streamlit as st
import pandas as pd
import materials_db
from input_guard import repair_invalid_inputs
from engineering_tools import round_half_up, clean_number, safe_float, require_fluid_density
from editor_state import persistent_data_editor
from phase_4_fluids import render_preflush_material_name
from standalone_spacer import CONFIG_KEY, MODES, formulation_from_state, field_rows, FIELD_COLUMNS
from project_state import invalidate_document

REQUIRED_SPACER_COLS = ["Chemical", "User Input (% or gal)", "Weighting Agent Type"]

def _go_to_fluid_configuration():
    """Select the target phase before the sidebar navigation radio is mounted."""
    st.session_state["_app_mode_key"] = "phase4"


def _commit_preflush_param(field: str, widget_key: str) -> None:
    """BUG-01 (same protection as Phase IV's _commit_fluid_widget): commit the
    last widget edit into preflush_config before a phase-switch rerun can
    garbage-collect this widget."""
    st.session_state.setdefault("preflush_config", {})[field] = st.session_state[widget_key]


def _commit_standalone_spacer(field, widget_key):
    if "Spacer" in st.session_state.get("fluids_config", {}).get("active", []):
        config = st.session_state.setdefault(CONFIG_KEY, {})
        if config.get(field) != st.session_state[widget_key]:
            invalidate_document(st.session_state)
        config[field] = st.session_state[widget_key]


def _standalone_field_display(recipe):
    """Cement field presentation rules; keep the shared Word projection intact."""
    rows = field_rows(recipe)
    for row, material in zip(rows, recipe["materials"]):
        for source, column in (("base", FIELD_COLUMNS[3]), ("gross", FIELD_COLUMNS[5])):
            amount = round_half_up(material[source], 1 if material["unit"] == "lb" else 2)
            precision = 2 if material["unit"] == "gal" and round(amount, 1) != amount else 1
            row[column] = f"{amount:.{precision}f} {material['unit']}"
        row[FIELD_COLUMNS[4]] = f"{round_half_up(material['dose'], 3):.3f} {material['unit']}/bbl"
    return rows


def _render_standalone_spacer(load_sig):
    """Operator inputs only; quantities are a fresh projection of current sources."""
    config = st.session_state.setdefault(CONFIG_KEY, {})
    job = st.session_state.get("job_type", 'CSG 20"')
    config.setdefault("tank_name", materials_db.get_tank_name(job))
    specs = [(config, field, label, 0., None, False) for field, label in (
        ("dead_vol", "Spacer Dead Volume"), ("limestone_available_lb", "Available Limestone inventory"),
        ("barite_available_lb", "Available Barite inventory")) if config.get(field) is not None]
    if repair_invalid_inputs(specs, f"standalone_spacer_{load_sig}"):
        invalidate_document(st.session_state)
        return
    choices = {"mode": MODES, "tank_name": materials_db.get_available_tanks(job)}
    for field, label in (("mode", "Weighting Agent Mode"), ("tank_name", "Mixing Tank - Spacer")):
        key = f"_standalone_spacer_{field}_{load_sig}"
        if config.get(field) is not None and config[field] not in choices[field]:
            config[field] = None
            st.session_state[key] = None
            invalidate_document(st.session_state)
        if key not in st.session_state:
            st.session_state[key] = config.get(field)
        options = choices[field]
        config[field] = st.selectbox(label, options, index=None, key=key,
                                    on_change=_commit_standalone_spacer, args=(field, key))
    fields = [("dead_vol", "Dead Volume (bbl) - Spacer")]
    if config.get("mode") == "Limestone + Barite":
        fields += [("limestone_available_lb", "Available Limestone (lb)"),
                   ("barite_available_lb", "Available Barite (lb)")]
    for field, label in fields:
        key = f"_standalone_spacer_{field}_{load_sig}"
        if key not in st.session_state:
            st.session_state[key] = config.get(field)
        config[field] = st.number_input(label, min_value=0., value=None, step=1., key=key,
                                        on_change=_commit_standalone_spacer, args=(field, key))
    try:
        recipe = formulation_from_state(st.session_state)
    except ValueError as exc:
        invalidate_document(st.session_state)
        st.warning(str(exc))
        return
    st.markdown('<div style="background:#17365d;color:white;padding:8px;font-weight:bold">'
                'Spacer Additives Data</div>', unsafe_allow_html=True)
    st.write(f"Volume: {recipe['volume_bbl']:.1f} bbl | Weight: {recipe['density_pcf']:g} pcf")
    st.write(f"Fresh Water: {recipe['water_base_bbl']:.2f} bbl (target batch); "
             f"{recipe['water_total_bbl']:.2f} bbl (including Dead Volume).")
    st.table(pd.DataFrame(_standalone_field_display(recipe)))
    st.caption("Doses are per bbl fresh water, including Defoamer. "
               "The last column includes Dead Volume for every material.")
    if recipe["inventory"]:
        st.table(pd.DataFrame([{"Material": name, **{key: f"{round_half_up(value, 1):.1f}"
                             for key, value in values.items()}} for name, values in recipe["inventory"].items()]))
        st.caption("Weighting solids: " + "; ".join(f"{name}: {pct:.2f}%" for name, pct in recipe["weighting_pct"].items()))
    st.info(recipe["note"])
    st.caption(f"Operational mixed volume: {recipe['mixed_volume_bbl']:.1f} bbl; "
               f"programmed pumped volume: {recipe['pumped_volume_bbl']:.1f} bbl. "
               f"Closure residuals — mass: {recipe['closure']['mass_lb']:.3g} lb; "
               f"volume: {recipe['closure']['volume_bbl']:.3g} bbl; "
               f"density: {recipe['closure']['density_pcf']:.3g} pcf.")

def get_spacer_key(name: str, prefix: str) -> str:
    sanitized = "".join(c if c.isalnum() else "_" for c in str(name)).lower()
    return f"{prefix}_{sanitized}"

def compute_preflush_payload(preflush_config: dict, pf_info: dict) -> dict:
    """F1 (P0-01, owner-approved 2026-09-29): PURE recomputation of the Phase X
    preflush report payload from the source of truth (preflush_config + the
    Phase IV fluid row), with exactly the semantics render() below applies
    when it builds its transient preflush_calc byproduct.

    Why this exists: preflush_calc is a Phase-VI render byproduct and goes
    STALE when Phase IV volume/density edits are followed by direct sidebar
    navigation to Phase X — live-proven: the Word report printed 80 bbl while
    the fluid truth was 25 bbl, with the readiness checklist still saying
    'ok' (engineering_tools.compute_phase_status only checks that
    preflush_calc is non-empty, never that it agrees with fluid_data).
    Phase X now calls this at Word-build time, so the report can never publish
    an outdated snapshot. render() keeps writing preflush_calc as before — it
    remains the 'Phase VI was configured' readiness marker.

    Numeric reads use safe_float: garbage must surface through Phase X's
    unreadable-volume gate, not as a raw ValueError here (mirrors render()'s
    float() reads for every well-formed session).
    """
    config = preflush_config or {}
    info = pf_info or {}
    kind = str(config.get("type", "Combined (Water + NaCl + Wash)"))
    # Same type canonicalization render() applies before its branches.
    if kind in ("Chemical Wash", "Water + Chemical Wash"):
        kind = "Water + Chemical Wash"
    elif kind in ("Combined / Custom", "Combined (Water + NaCl + Wash)"):
        kind = "Combined (Water + NaCl + Wash)"

    pf_vol = safe_float(info.get("volume", 0.0))
    pf_density_str = str(info.get("density", "80.0"))
    pf_eff_density = safe_float(info.get("effective_density", 80.0), 80.0)

    water_amt = round_half_up(pf_vol, 1)
    nacl_amt = 0.0
    wash_amt = 0.0
    nacl_mult = 0.0
    wash_mult = 0.0
    if kind == "Water + Chemical Wash":
        wash_mult = safe_float(config.get("wash_multiplier", 3.0))
        wash_amt = round_half_up(pf_vol * wash_mult, 1)
    elif kind == "Brine (Water + NaCl)":
        nacl_mult = safe_float(config.get("nacl_multiplier", 126.0))
        nacl_amt = round_half_up(pf_vol * nacl_mult, 1)
    elif kind == "Fresh Water Only":
        pass
    else:  # Combined (Water + NaCl + Wash) — render()'s else branch
        nacl_mult = safe_float(config.get("nacl_multiplier", 126.0))
        wash_mult = safe_float(config.get("wash_multiplier", 3.0))
        nacl_amt = round_half_up(pf_vol * nacl_mult, 1)
        wash_amt = round_half_up(pf_vol * wash_mult, 1)

    return {
        "type": kind,
        "volume_bbl": pf_vol,
        "density_pcf": pf_density_str,
        "effective_density": pf_eff_density,
        "nacl_lbs": nacl_amt,
        "wash_gal": wash_amt,
        "water_bbl": water_amt,
        "nacl_multiplier": nacl_mult,
        "wash_multiplier": wash_mult,
    }

def render():
    st.header("Phase VI: Pre-flush & Spacer")
    st.markdown("Configure Pre-flush wash systems and Spacer chemical formulations.")

    load_sig = str(st.session_state.get("last_loaded_hash", "default_project"))
    
    # 1. Strict SSOT Derivation from Phase IV
    active_pipeline = st.session_state.get("fluids_config", {}).get("active", [])
    fluid_data = st.session_state.get("fluid_data", {})
    
    has_preflush = "Pre Flush" in active_pipeline
    spacer_archetypes = ["Spacer"]
    active_spacers = [f for f in active_pipeline if f in spacer_archetypes]
    
    # Invalidate stale Pre-flush state if deselected upstream
    if not has_preflush:
        st.session_state["preflush_calc"] = None

    if not has_preflush and not active_spacers:
        st.info("Spacer Ahead/Behind are operational fluids configured in Phase IV; no chemical formulation is required.")
        if any(name in active_pipeline for name in ("Spacer Ahead", "Spacer Behind")):
            return
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
        pf_vol = safe_float(pf_info.get("volume"), None) if isinstance(pf_info, dict) else None
        try:
            if pf_vol is None or pf_vol < 0:
                raise ValueError("Pre Flush volume must be a finite nonnegative number.")
            pf_eff_density = require_fluid_density("Pre Flush", pf_info.get("density"))
        except (TypeError, ValueError, OverflowError) as exc:
            invalidate_document(st.session_state)
            st.error(f"Phase IV: {exc} Review the Pre Flush source before formulation.")
            st.button("→ Go to Phase IV to repair Pre Flush", on_click=_go_to_fluid_configuration)
            return
        # Effective density is a projection, never a second measured source.
        pf_info["effective_density"] = pf_eff_density
        pf_density_str = str(pf_info["density"])
        render_preflush_material_name()

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
            key=f"_pf_type_select_{load_sig}",
            on_change=_commit_preflush_param,
            args=("type", f"_pf_type_select_{load_sig}")
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
                    key=f"_pf_wash_m_{load_sig}",
                    on_change=_commit_preflush_param,
                    args=("wash_multiplier", f"_pf_wash_m_{load_sig}")
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
                    key=f"_pf_nacl_m_{load_sig}",
                    on_change=_commit_preflush_param,
                    args=("nacl_multiplier", f"_pf_nacl_m_{load_sig}")
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
                    key=f"_pf_nacl_m_{load_sig}",
                    on_change=_commit_preflush_param,
                    args=("nacl_multiplier", f"_pf_nacl_m_{load_sig}")
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
                    key=f"_pf_wash_m_{load_sig}",
                    on_change=_commit_preflush_param,
                    args=("wash_multiplier", f"_pf_wash_m_{load_sig}")
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
                if spacer_name == "Spacer":
                    _render_standalone_spacer(load_sig)
                    continue
