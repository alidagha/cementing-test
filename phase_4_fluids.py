# phase_4_fluids.py
import streamlit as st
from typing import Dict, Any
import materials_db
from project_state import purge_inactive_slurries
from input_guard import repair_invalid_inputs
from engineering_tools import parse_effective_numeric, require_positive_density, require_positive_pump_rate, format_to_hr_mm

# Strict API & Well Execution Sequence for Fluid Train Sorting
HYDRAULIC_EXECUTION_ORDER = [
    "Pre Flush",
    "Spacer",
    "Spacer Ahead",
    "Lead",
    "Lead #1",
    "Lead #2",
    "Main",
    "Tail",
    "Spacer Behind",
    "Displacement Fluid"
]

def build_fluid_record(
    name: str,
    material_name: str,
    volume: float,
    density_str: str,
    effective_density: float,
    pump_rate_str: str,
    min_rate: float,
    duration_min: float,
    duration_str: str,
    cumul_time_min: float,
    cumul_time_str: str
) -> Dict[str, Any]:
    """Standardized factory ensuring strict type safety for downstream consumers (Phases 5, 6, 7, 10)."""
    return {
        "name": str(name),
        "material_name": str(material_name),
        "volume": float(volume),
        "density": str(density_str),
        "effective_density": float(effective_density),
        "pump_rate": str(pump_rate_str),
        "min_rate": float(min_rate),
        "duration_min": float(duration_min),
        "duration_str": str(duration_str),
        "cumul_time_min": float(cumul_time_min),
        "cumul_time_str": str(cumul_time_str)
    }


def _commit_fluid_widget(fluid: str, field: str, widget_key: str) -> None:
    """Commit the last edit before a phase switch skips this phase's render.

    Streamlit runs widget callbacks before rerouting. Without this callback a
    text field blurred by a navigation click is removed before render() can
    copy its new value from the widget into the project's fluid parameters.
    """
    value = st.session_state[widget_key]
    config = st.session_state.get("fluids_config", {})
    if fluid not in config.get("active", []):
        return
    config.setdefault("params", {}).setdefault(fluid, {})[field] = value

    # This is the already-rendered record used by the following phase. Phase
    # IV recalculates durations and cumulative time when it renders again.
    record = st.session_state.get("fluid_data", {}).get(fluid)
    if isinstance(record, dict):
        record[field] = value
        if field == "density":
            record["effective_density"] = parse_effective_numeric(value, default=0.0)

def render():
    st.header("Phase IV: Fluids Sequence")
    st.markdown("Configure fluid train parameters. **Displacement Fluid density is dynamically referenced from Phase II.**")

    # 1. Dynamic Reference to Phase II Drilling Fluid Data (Live Sync)
    # BUG-31 (residual): an unset Phase II mud density used to DISPLAY here
    # as "80.0 pcf" — a fabricated number that looked like entered data. The
    # export path already rejects an empty mud density (phase status +
    # require_positive_density); the screen no longer pretends one exists.
    _raw_mud_density = st.session_state.get("mud_density")
    _mud_density_set = _raw_mud_density is not None and str(_raw_mud_density).strip() not in ("", "nan", "None")
    live_mud_density_display = str(_raw_mud_density).strip() if _mud_density_set else ""
    live_effective_mud_density = (float(st.session_state.get("effective_mud_density") or 0.0)
                                  if _mud_density_set else 0.0)

    # 2. Canonical State Initialization
    if "fluids_config" not in st.session_state:
        st.session_state["fluids_config"] = {
            "active": ["Displacement Fluid"],
            "params": {
                f: {
                    "volume": 0.0,
                    "density": "" if f in {"Pre Flush", "Main"} else "118.0" if "Tail" in f else "80.0",
                    "pump_rate": "4.0"
                } for f in materials_db.FLUID_TYPES if f != "Displacement Fluid"
            }
        }
    
    cfg = st.session_state["fluids_config"]
    if "params" not in cfg:
        cfg["params"] = {}
    # Earlier project files kept the fluid train in fluid_data and did not
    # always include a params entry for every active fluid. Restore only the
    # missing fields before bounded widgets or defaults can overwrite them.
    legacy_fluids = st.session_state.get("fluid_data", {})
    if isinstance(legacy_fluids, dict):
        for fluid in cfg.get("active", []):
            legacy = legacy_fluids.get(fluid)
            if not isinstance(legacy, dict):
                continue
            params = cfg["params"].setdefault(fluid, {})
            if isinstance(params, dict):
                for field in ("volume", "density", "pump_rate", "material_name"):
                    if field not in params and field in legacy:
                        params[field] = legacy[field]
    bounded = []
    for fluid in cfg.get("active", []):
        params = cfg["params"].get(fluid, {})
        if isinstance(params, dict) and "volume" in params:
            bounded.append((params, "volume", f"Volume (bbl) - {fluid}", 0.0, None, False))
    if repair_invalid_inputs(bounded, f"phase4_{st.session_state.get('last_loaded_hash', 'new')}"):
        return

    # 3. Fluid Selection Checklist with SSOT Reconcile
    st.subheader("1. Fluid Selection Checklist")
    cols = st.columns(5)
    selected_fluids = []
    active_set = set(cfg.get("active", []))
    
    for i, fluid in enumerate(materials_db.FLUID_TYPES):
        col = cols[i % 5]
        chk_key = f"chk_fluid_{fluid}"
        
        # Automatically initialized from SSOT (cfg['active']) upon first load or clean-slate restore
        if chk_key not in st.session_state:
            st.session_state[chk_key] = fluid in active_set
            
        checked = col.checkbox(fluid, key=chk_key)
        if checked:
            selected_fluids.append(fluid)
            
    # Strict Hydraulic Sort: Order selected fluids according to well physics
    active_fluids_list = sorted(
        selected_fluids,
        key=lambda x: HYDRAULIC_EXECUTION_ORDER.index(x) if x in HYDRAULIC_EXECUTION_ORDER else 999
    )
    
    cfg["active"] = active_fluids_list
    purge_inactive_slurries(st.session_state, active_fluids_list)
    st.session_state["active_fluids"] = {f: (f in active_fluids_list) for f in materials_db.FLUID_TYPES}
    inactive_drafts = st.session_state.get("inactive_slurry_drafts", {})
    if inactive_drafts:
        names = ", ".join(sorted(inactive_drafts))
        st.info(f"Saved inactive slurry drafts: {names}. Re-select a slurry to restore its formulation; "
                "review its Phase VII lab results before Word export.")

    st.markdown("---")
    
    # 4. Operational Parameters
    st.subheader("2. Operational Parameters (Volume, Density, Rate)")
    
    if not active_fluids_list:
        st.warning("⚠ Select at least one fluid to continue.")
        st.session_state["total_pump_time_min"] = 0.0
        st.session_state["total_pump_time_hhmm"] = "00:00"
        st.session_state["fluid_data"] = {}
        
        # Clean-up all downstream caches if fluid train is empty
        # FIX (requested): the same orphaned-state class this whole block
        # exists to prevent was still open for Spacer — spacer_dfs[name] and
        # its entry in spacer_initialized_names (both owned by
        # phase_6_spacer.py) were never cleared when a spacer type was
        # deselected here, unlike the slurry keys above.
        all_spacers = ["Spacer", "Spacer Ahead", "Spacer Behind"]
        for sp in all_spacers:
            st.session_state.get("spacer_dfs", {}).pop(sp, None)
            if sp in st.session_state.get("spacer_initialized_names", []):
                st.session_state["spacer_initialized_names"].remove(sp)

        # FIX (requested): same class of bug again, for Pre Flush specifically
        # this time — preflush_calc (the dict build_master_context() reads
        # straight into the exported Word doc's "Pre Flush Data" section) was
        # only ever reset to None inside phase_6_spacer.py's own render(), so
        # deselecting "Pre Flush" here had no effect on it unless the user
        # happened to revisit Phase VI afterward. Since the template has no
        # {% if %} gating this section on has_preflush, a stale preflush_calc
        # left over from before a deselect would keep silently appearing in
        # every exported document. Resetting it here the moment "Pre Flush"
        # leaves active_fluids_list closes that gap regardless of navigation.
        st.session_state["preflush_calc"] = None
        return

    cumulative_time_min = 0.0
    cumulative_time_valid = True
    fluid_data_payload = {}

    # Iterates strictly in sorted hydraulic execution order
    for fluid in active_fluids_list:
        st.markdown(f"**{fluid}**")
        
        if fluid == "Displacement Fluid":
            p = cfg["params"].setdefault(fluid, {"volume": 0.0, "pump_rate": "4.0"})
            disp_density_text = live_mud_density_display
            disp_effective_density = live_effective_mud_density
        else:
            # Match the initial configuration, including 80 pcf spacers.
            _default_density = (
                "" if fluid in {"Pre Flush", "Main"}
                else "118.0" if "Tail" in fluid
                else "80.0"
            )
            p = cfg["params"].setdefault(
                fluid,
                {
                    "volume": 0.0,
                    "density": _default_density,
                    "pump_rate": "4.0"
                }
            )
            disp_density_text = str(p.get("density", ""))

        # Material Name — the Fluids Sequence table's "Name" column (e.g. "Cement
        # Slurry", "Salt Saturated Water", "Mud"), distinct from the "Type" column
        # (the stage label, e.g. "Lead #1"). Prefilled from materials_db defaults,
        # editable since a rig may use a different base fluid for a given stage.
        p["material_name"] = st.text_input(
            f"Material Name - {fluid}",
            value=str(p.get("material_name", materials_db.DEFAULT_MATERIAL_NAMES.get(fluid, ""))),
            help="Descriptive fluid name shown in the 'Name' column (e.g. 'Cement Slurry', 'Salt Saturated Water', 'Mud').",
            key=f"matname_{fluid}",
            on_change=_commit_fluid_widget,
            args=(fluid, "material_name", f"matname_{fluid}")
        )

        col1, col2, col3, col4, col5 = st.columns([1.2, 1.2, 1.2, 1.2, 1.2])
        
        # Volume Input
        with col1:
            p["volume"] = st.number_input(
                f"Volume (bbl) - {fluid}",
                min_value=0.0,
                step=1.0,
                value=float(p.get("volume", 0.0)),
                key=f"vol_{fluid}",
                on_change=_commit_fluid_widget,
                args=(fluid, "volume", f"vol_{fluid}")
            )
            
        # Density Input
        with col2:
            if fluid == "Displacement Fluid":
                st.text_input(
                    f"Density (pcf) - {fluid}",
                    value=disp_density_text if _mud_density_set else "Not set in Phase II & III",
                    disabled=True,
                    help=(f"Dynamic reference to Phase II (Effective: {disp_effective_density:.2f} pcf)"
                          if _mud_density_set
                          else "Dynamic reference to Phase II — set Mud Weight there first."),
                    key="den_disp_live"
                )
            else:
                p["density"] = st.text_input(
                    f"Density (pcf) - {fluid}",
                    value=disp_density_text,
                    help="Enter density in pcf (e.g. 118.0 or range 115-118)",
                    key=f"den_{fluid}",
                    on_change=_commit_fluid_widget,
                    args=(fluid, "density", f"den_{fluid}")
                )
                try:
                    disp_effective_density = require_positive_density(p["density"])
                except ValueError as exc:
                    st.error(f"{fluid}: {exc}. Correct the density before exporting the report.")
                    # Keep the invalid input visible without presenting a
                    # fabricated 80 pcf value as an actual calculation.
                    disp_effective_density = 0.0
                else:
                    # FIX (requested, Level 1 #4): same transparency caption as
                    # Phase II's range fields — shows the single number this
                    # text actually resolves to for every downstream calculation,
                    # without changing the free-text range-input behavior itself.
                    st.caption(f"↳ Used in calculations as: **{disp_effective_density:.1f} pcf**" + (" (mean of range)" if any(c in p["density"] for c in "-/") else ""))

                # FIX (found by testing): the Mass Balance formula (Phase V)
                # has a denominator that approaches zero as slurry weight
                # approaches fresh-water density (~62.4 pcf), which is not
                # obviously wrong-looking on its own — an implausible density
                # here (typo'd digit, wrong field) can silently produce a
                # wildly wrong or a deceptively "0 sacks needed" result two
                # phases later with no warning anywhere. This field is free
                # text with no min/max (unlike Volume), so catch it here at
                # the source instead.
                # FIX (requested): range aligned to 75-180 pcf to match Phase
                # V's own plausibility check on the same slurries (Main/Lead/
                # Tail) — previously this used 80-300, so the exact same
                # density (e.g. 200 pcf) could pass silently here yet trigger
                # a warning one phase later, which read as contradictory/
                # confusing rather than as two independent checks.
                if disp_effective_density > 0 and fluid in {"Main", "Lead", "Lead #1", "Lead #2", "Tail"} and not (75.0 <= disp_effective_density <= 180.0):
                    st.warning(
                        f"⚠ **Plausibility Check:** {fluid} density is {disp_effective_density:.1f} pcf — outside the "
                        "typical range for a cement slurry (~75-180 pcf). Please verify this isn't a typo; an implausible "
                        "value here can make the Phase V yield/sack calculation silently wrong or zero."
                    )
                
        # Pump Rate Input
        with col3:
            p["pump_rate"] = st.text_input(
                f"Rate (bpm) - {fluid}",
                value=str(p.get("pump_rate", "4.0")),
                help="Single value (e.g. 4.0) or range (e.g. 3-5). Calculations use minimum value.",
                key=f"rate_{fluid}",
                on_change=_commit_fluid_widget,
                args=(fluid, "pump_rate", f"rate_{fluid}")
            )

        try:
            min_rate = require_positive_pump_rate(p["pump_rate"])
            duration_min = float(p["volume"]) / min_rate
            duration_str = format_to_hr_mm(duration_min)
        except (ValueError, OverflowError) as exc:
            st.error(f"{fluid}: {exc}. Correct the rate before exporting the report.")
            min_rate = 0.0
            duration_min = 0.0
            duration_str = "INVALID RATE"
            cumulative_time_valid = False
        cumulative_time_min += duration_min

        cumul_str = format_to_hr_mm(cumulative_time_min) if cumulative_time_valid else "INVALID RATE"

        with col4:
            st.info(f"Duration:\n\n**{duration_str}** (hr:mm)")
        with col5:
            st.success(f"Cumul. Time:\n\n**{cumul_str}** (hr:mm)")

        fluid_data_payload[fluid] = build_fluid_record(
            name=fluid,
            material_name=str(p.get("material_name", materials_db.DEFAULT_MATERIAL_NAMES.get(fluid, ""))),
            volume=float(p["volume"]),
            density_str=disp_density_text if fluid == "Displacement Fluid" else str(p["density"]),
            effective_density=disp_effective_density,
            pump_rate_str=str(p["pump_rate"]),
            min_rate=min_rate,
            duration_min=duration_min,
            duration_str=duration_str,
            cumul_time_min=cumulative_time_min,
            cumul_time_str=cumul_str
        )
            
        st.divider()

    st.session_state["fluid_data"] = fluid_data_payload
    st.session_state["total_pump_time_min"] = cumulative_time_min
    st.session_state["total_pump_time_hhmm"] = format_to_hr_mm(cumulative_time_min) if cumulative_time_valid else "INVALID RATE"

    # FIX (requested): mirror the same cleanup for Spacer, which previously
    # had none at all — spacer_dfs[name] and spacer_initialized_names kept
    # a deselected spacer's formulation forever, so re-checking the same
    # spacer type later would silently show the old leftover table instead
    # of starting fresh (unlike slurries, which now reset correctly above).
    all_spacer_keys = ["Spacer", "Spacer Ahead", "Spacer Behind"]
    for sp in all_spacer_keys:
        if sp not in active_fluids_list:
            st.session_state.get("spacer_dfs", {}).pop(sp, None)
            if sp in st.session_state.get("spacer_initialized_names", []):
                st.session_state["spacer_initialized_names"].remove(sp)

    # FIX (requested): reset preflush_calc the moment "Pre Flush" leaves
    # active_fluids_list — see the matching comment in the empty-fluid-train
    # branch above for why this can't be left to phase_6_spacer.py alone.
    if "Pre Flush" not in active_fluids_list:
        st.session_state["preflush_calc"] = None
