# main.py
import streamlit as st
import json
import hashlib
import math
import materials_db
import pandas as pd
from datetime import date, datetime
from engineering_tools import compute_phase_status, WORD_ADVISORY_PHASES
from project_state import (is_project_key, invalidate_document, restore_canonical_fields,
                           DOC_CONTROL_DEFAULTS, WELL_DATA_DEFAULTS, migrate_material_properties)
from project_io import content_signature, decode_project, replace_project_state
from placement import EXCESS_FIELDS

restore_canonical_fields(st.session_state)
migrate_material_properties(st.session_state)

st.set_page_config(page_title="Cementing Report Engine", layout="wide", page_icon="🛢️")

def serialize_item(obj, path="project"):
    """Recursively serializes objects including DataFrames and Dates for JSON export."""
    if isinstance(obj, pd.DataFrame):
        rows = []
        for index, record in enumerate(obj.to_dict(orient="records")):
            # Keep unfinished table cells as JSON null so a project can be
            # downloaded mid-entry. Official Word export validates completed
            # formulations separately.
            rows.append({key: (None if (value is pd.NA or isinstance(value, float) and math.isnan(value))
                               else serialize_item(value, f"{path}[{index}].{key}"))
                         for key, value in record.items()})
        return {
            "__type__": "DataFrame",
            "columns": list(obj.columns),
            "data": rows
        }
    elif obj is pd.NaT:
        # BUG-26: pd.NaT passes the datetime isinstance check below, and its
        # isoformat() is the literal string "NaT", so a saved project with a
        # NaT cell crashed every later reload on datetime.fromisoformat("NaT").
        # Serialize the missing timestamp as JSON null instead.
        return None
    elif isinstance(obj, datetime):
        return {"__type__": "DateTime", "val": obj.isoformat()}
    elif isinstance(obj, date):
        return {
            "__type__": "Date",
            "val": obj.isoformat()
        }
    elif isinstance(obj, dict):
        return {k: serialize_item(v, f"{path}.{k}") for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_item(item, f"{path}[{index}]") for index, item in enumerate(obj)]
    elif isinstance(obj, float) and not math.isfinite(obj):
        raise ValueError(f"Non-finite numeric value at {path}; correct it before saving.")
    elif hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        # BUG-25: numpy scalars (np.int64, np.bool_, ...) reached the str()
        # fallback and were saved as text ("42"), desyncing typed widgets and
        # numeric comparisons after a reload. .item() unwraps them to native
        # Python numbers/bools — the same treatment _canonical() applies for
        # fingerprints.
        return serialize_item(obj.item(), path)
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)

def deserialize_item(obj):
    """Recursively restores objects from serialized JSON representations."""
    if isinstance(obj, dict):
        if obj.get("__type__") == "DataFrame":
            return pd.DataFrame(deserialize_item(obj.get("data", [])), columns=obj.get("columns", []))
        elif obj.get("__type__") == "Date":
            return date.fromisoformat(obj["val"])
        elif obj.get("__type__") == "DateTime":
            return datetime.fromisoformat(obj["val"])
        return {k: deserialize_item(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deserialize_item(item) for item in obj]
    return obj

def get_serializable_state():
    """
    Extracts valid state variables while ignoring transient widget keys
    to prevent file bloat and widget desynchronization.
    """
    cache_data = {}
    for key, val in st.session_state.items():
        if is_project_key(key):
            cache_data[key] = serialize_item(val, key)
    return cache_data

# FIX (requested): the app used to silently persist every session to a local
# session_cache.json file and auto-restore it on the next launch, so opening
# the app "fresh" actually meant reopening whatever was last left in memory —
# including old test/leftover slurry data — which is what made Phase V (and
# the growing project file) look pre-filled/cluttered for no visible reason.
# That disk-cache save/load has been removed entirely. The app now always
# starts from a truly blank session. The only way to bring back a previous
# well's data is the explicit "Load Project (.json)" uploader below —
# which does not depend on this removed mechanism at all, since it already
# worked purely through get_serializable_state()/deserialize_item() on the
# in-memory session. If a stale session_cache.json / session_cache.json.tmp
# file exists from before this fix, it is now inert and safe to delete.

# Reserve sidebar space for the project manager, then register navigation
# before rendering the selected phase. A phase error must not prevent the
# radio widget from being registered: Streamlit otherwise cleans up its key
# and the next rerun opens Phase I. The project download and dirty flag still
# render after the phase so they see its latest canonical inputs.
_project_manager_slot = st.sidebar.container()
_navigation_slot = st.sidebar.container()
_PHASE_ORDER = ["phase1", "phase2_3", "phase4", "phase5", "phase6", "phase7", "phase9", "phase10"]
_PHASE_LABELS = {
    "phase1": "Phase I: Document Control",
    "phase2_3": "Phase II & III: Well Data",
    "phase4": "Phase IV: Fluids Sequence",
    "phase5": "Phase V: Cement Program",
    "phase6": "Phase VI: Pre-flush & Spacer",
    "phase7": "Phase VII: Lab Report",
    "phase9": "Phase IX: Centralizer",
    "phase10": "Phase X: Procedure & Export",
}
_PHASE_ICONS = {"ok": "✅", "warning": "⚠️", "empty": "⚪"}

# Phase status labels describe the last committed state. Project data and
# download signatures below are computed after the selected phase is rendered.
_phase_status = compute_phase_status(st.session_state)

def _format_phase(key):
    # The browser stores the formatted radio string, not just its Python key.
    # Keep it constant: changing a status icon here clears the selection in
    # Streamlit 1.64 and the next edit can route to Phase I before being saved.
    return _PHASE_LABELS[key]

def _navigation_sources_not_started(state):
    """Recognize untouched input defaults for captions, never for admission."""
    from well_profile import geometry_defaults, geothermal_defaults
    from phase_2_3_well_data import HARDWARE_COLUMNS
    from phase_9_centralizer import new_config

    if state.get("last_loaded_hash"):
        return False
    effective = {key: None for key in ("effective_mud_density", "effective_pv", "effective_yp")}
    defaults = {
        **DOC_CONTROL_DEFAULTS, **WELL_DATA_DEFAULTS, **effective,
        "doc_control": DOC_CONTROL_DEFAULTS, "well_data": {**WELL_DATA_DEFAULTS, **effective},
        "hole_size_customized": False, "request_description_customized": False,
        "revision_description_customized": False, "well_auto_fields": {"bhsp": True},
        "well_geometry": geometry_defaults(), "geothermal_config": geothermal_defaults(),
        "hardware_table": pd.DataFrame(columns=HARDWARE_COLUMNS),
        "hardware_editor_draft": pd.DataFrame(columns=HARDWARE_COLUMNS),
        "placement_config": {"job_type": DOC_CONTROL_DEFAULTS["job_type"], "target_row": "", "host_row": "",
                             **{field: None for field, _, _ in EXCESS_FIELDS}},
        "centralizer_config": new_config(),
        "fluids_config": {"active": ["Displacement Fluid"], "params": {
            name: {"volume": 0., "density": "", "pump_rate": "",
                   "material_name": materials_db.DEFAULT_MATERIAL_NAMES.get(name, "")}
            for name in materials_db.FLUID_TYPES}},
        "preflush_config": {"type": "Combined (Water + NaCl + Wash)", "nacl_multiplier": 126., "wash_multiplier": 3.},
        "standalone_spacer_config": {"mode": None, "dead_vol": None,
                                     "tank_name": materials_db.get_tank_name(DOC_CONTROL_DEFAULTS["job_type"])},
        "formation_pressure_config": {"mode": "basic", "profile": []},
        **{key: {} for key in ("cement_params", "cement_additives_dfs", "spacer_dfs", "lab_grid_dfs",
                              "lab_qc_params", "inactive_slurry_drafts", "schematic_config", "ct_stage_config")},
    }
    # The calendar is automatically mounted by Phase I; its date is not a
    # Well/Centralizer input. All other document inputs must still be defaults.
    sources = {key: state[key] for key in defaults if key in state}
    if isinstance(sources.get("doc_control"), dict):
        sources["doc_control"] = {key: value for key, value in sources["doc_control"].items() if key != "date"}
    if "fluids_config" not in state and state.get("fluid_data"):
        return False

    def unchanged(value, expected):
        if isinstance(value, dict) and isinstance(expected, dict):
            return all(key in expected and unchanged(item, expected[key]) for key, item in value.items())
        return isinstance(value, bool) == isinstance(expected, bool) and value == expected

    return unchanged(serialize_item(sources), serialize_item(defaults))

def _phase_caption(key):
    if key == "phase10":
        return ""
    level = _phase_status.get(key, {}).get("level", "empty")
    if level == "warning" and key in ("phase2_3", "phase9") and _navigation_sources_not_started(st.session_state):
        level = "empty"
    description = {"ok": "Complete", "warning": "Needs review", "empty": "Not started"}
    return f"{_PHASE_ICONS.get(level, '⚪')} {description.get(level, 'Not started')}"

def _reset_navigation_after_project_replace(state):
    """Reset the radio before mounting it after Start New or project load.

    Both paths replace widget state after navigation is already mounted. The
    next run renders Phase I, but the browser can keep an old phase checked.
    """
    if state.pop("_reset_navigation_to_phase1", False):
        state["_app_mode_key"] = "phase1"

_reset_navigation_after_project_replace(st.session_state)

with _navigation_slot:
    st.title("Navigation")
    app_mode_key = st.radio("Select Phase", _PHASE_ORDER, format_func=_format_phase,
                            captions=[_phase_caption(key) for key in _PHASE_ORDER],
                            key="_app_mode_key")
app_mode = _PHASE_LABELS[app_mode_key]

if app_mode == "Phase I: Document Control":
    import phase_1_doc_control
    phase_1_doc_control.render()
elif app_mode == "Phase II & III: Well Data":
    import phase_2_3_well_data
    phase_2_3_well_data.render()
elif app_mode == "Phase IV: Fluids Sequence":
    import phase_4_fluids
    phase_4_fluids.render()
elif app_mode == "Phase V: Cement Program":
    import phase_5_cement
    phase_5_cement.render()
elif app_mode == "Phase VI: Pre-flush & Spacer":
    import phase_6_spacer
    phase_6_spacer.render()
elif app_mode == "Phase VII: Lab Report":
    import phase_7_lab
    phase_7_lab.render()
elif app_mode == "Phase IX: Centralizer":
    import phase_9_centralizer
    phase_9_centralizer.render()
elif app_mode == "Phase X: Procedure & Export":
    import phase_10_procedure
    phase_10_procedure.render()

# Widget values are mirrored to the project during render(). When that changes
# a phase's completion icon, refresh the sidebar in the same user interaction
# instead of leaving its label one edit behind. Navigation is already mounted,
# and its formatted options remain constant, so this rerun preserves the
# browser's selected phase while refreshing the separate status captions.
_current_phase_status = compute_phase_status(st.session_state)
# Round 9F: Phase IX is advisory until the Centralizer Word/Export batch.
# That batch must require current successful execution (target misses remain valid),
# and block never-executed/stale/failed designs; Plug/Squeeze stay N/A.
if (any(v["level"] != "ok" for key, v in _current_phase_status.items()
        if key != "phase6" and key not in WORD_ADVISORY_PHASES)
        or _current_phase_status["phase6"]["level"] == "warning"):
    invalidate_document(st.session_state)
if _current_phase_status != _phase_status:
    st.rerun()

# ==========================================
# SIDEBAR: PROJECT MANAGEMENT & NAVIGATION
# (everything below reads post-routing state, so it's always current)
# ==========================================
st.title("Cementing Engineering Report Automation")

# FIX (requested): persistent summary bar — visible from every phase, not
# just Phase I — so it's always obvious which well/job the open session
# belongs to. Most useful when working through several wells back-to-back
# in the same browser tab, where it's otherwise easy to lose track of
# whether you're still looking at the well you think you are.
_summary_well = str(st.session_state.get("well_name", "")).strip() or "Untitled Well"
_summary_job = str(st.session_state.get("job_type", "")).strip() or "Job Type not set"
st.caption(f"📍 **{_summary_well}** — {_summary_job}")

st.markdown("---")

_project_manager_slot.title("Project Manager")

# 1. Export / Download Project
well_label = str(st.session_state.get("well_name", "")).strip()
safe_well_name = "".join(c for c in well_label if c.isalnum() or c in ("-", "_")).strip()
project_filename = f"Cementing_Project_{safe_well_name or 'Untitled'}.json"

# sort_keys=True makes this deterministic across reruns regardless of any
# incidental dict-ordering differences, which matters here specifically
# because the same string is now also hashed below to detect real changes
# (an order-only difference must never look like a data change).
try:
    current_project_json = json.dumps(get_serializable_state(), indent=4, ensure_ascii=False, sort_keys=True, allow_nan=False)
except (ValueError, TypeError) as exc:
    current_project_json = ""
    _project_manager_slot.error(f"Project contains an invalid value; correct it before downloading: {exc}")

# FIX (requested, Level 2 #5): upgraded from an unconditional static
# reminder to a real dirty-flag. _saved_sig/_saved_at (both "_"-prefixed, so
# excluded from the project JSON like every other transient UI-only key —
# they describe THIS browser session's save history, not project data) are
# stamped at the moment of an actual download via download_button's
# on_click, then compared against the current state's hash on every rerun.
# The reminder now only fires when something has genuinely changed since
# the last download, rather than always being present regardless of state —
# and confirms the opposite ("saved at HH:MM") once it's actually current.
def _project_comparison_signature(project_json):
    """Compare checkpoints without exact, known lazy initialization defaults.

    This projection never changes saved JSON or canonical state. Unknown keys
    and nondefault values remain significant, including explicit zero excess.
    """
    from phase_2_3_well_data import HARDWARE_COLUMNS
    from well_profile import geometry_defaults, geothermal_defaults
    from project_state import DOC_CONTROL_DEFAULTS, lab_source_signature, request_description_for_job
    from phase_9_centralizer import new_config
    from phase_5_cement import REQUIRED_ADDITIVE_COLUMNS
    from engineering_tools import (catalog_cement_sg, THICKENING_TEST_FIELDS, MATERIAL_PROPERTY_SCHEMA,
                                   compressive_inputs, require_positive_density, clean_number, resolve_cement_sg)
    from rheology import new_rheology_dataset, RHEOLOGY_DATASETS, build_rheology
    from phase_7_lab import build_lab_df_from_phase5

    project = json.loads(project_json)
    # Model only absent legacy metadata using Phase I's existing initializer.
    # Explicit values/ownership flags always win and remain comparable.
    job = project.get("job_type", DOC_CONTROL_DEFAULTS["job_type"])
    project.setdefault("hole_size_customized", project.get("hole_size", DOC_CONTROL_DEFAULTS["hole_size"])
                       != materials_db.DEFAULT_HOLE_SIZES.get(job, "12 1/4\""))
    project.setdefault("request_description", DOC_CONTROL_DEFAULTS["request_description"]
                       if project.get("request_description_customized") else request_description_for_job(job))
    project.setdefault("revision_description", DOC_CONTROL_DEFAULTS["revision_description"]
                       if project.get("revision_description_customized") else project["request_description"])
    source = {**project, "well_data": dict(project.get("well_data", {})),
              "cement_additives_dfs": {name: (pd.DataFrame(table["data"], columns=table["columns"])
                  if isinstance(table, dict) and table.get("__type__") == "DataFrame" else table)
                  for name, table in project.get("cement_additives_dfs", {}).items()}}
    if ("bhsp" in project or "bhsp" in project.get("well_data", {})) and "well_auto_fields" not in project:
        # The established Phase-II restoration rule treats an explicitly
        # saved pressure as manual, even when the legacy value is blank.
        project["well_auto_fields"] = {"bhsp": False}
    effective = {key: None for key in ("effective_mud_density", "effective_pv", "effective_yp")}
    # Flat sources win on restore; an identical nested mirror is the same
    # input, not a new edit when a historical flat-only file is first mounted.
    for name, fields in (("doc_control", DOC_CONTROL_DEFAULTS),
                         ("well_data", {**WELL_DATA_DEFAULTS, **effective})):
        nested = project.get(name, {})
        for key in fields:
            if (key in nested and key in project
                    and isinstance(nested[key], bool) == isinstance(project[key], bool)
                    and nested[key] == project[key]):
                nested.pop(key)
    calendar = project.get("report_date")
    calendar = calendar.get("val") if isinstance(calendar, dict) else calendar
    if calendar is not None and project.get("doc_control", {}).get("date") == calendar:
        project["doc_control"].pop("date")
    doc_defaults = dict(DOC_CONTROL_DEFAULTS,
                        hole_size_customized=False, request_description_customized=False,
                        revision_description_customized=False)
    defaults = {
        **doc_defaults, **WELL_DATA_DEFAULTS, **effective,
        "material_property_schema": MATERIAL_PROPERTY_SCHEMA,
        "doc_control": dict(DOC_CONTROL_DEFAULTS),
        "well_data": {**WELL_DATA_DEFAULTS, **effective},
        "well_auto_fields": {"bhsp": True},
        "well_geometry": geometry_defaults(), "geothermal_config": geothermal_defaults(),
        "hardware_table": pd.DataFrame(columns=HARDWARE_COLUMNS),
        "placement_config": {"job_type": project.get("job_type"), "target_row": "", "host_row": "",
                             **{field: None for field, _, _ in EXCESS_FIELDS}},
        "fluids_config": {"active": ["Displacement Fluid"], "params": {
            name: {"volume": 0., "density": "", "pump_rate": "",
                   "material_name": materials_db.DEFAULT_MATERIAL_NAMES.get(name, "")}
            for name in materials_db.FLUID_TYPES}},
        "active_fluids": {name: name == "Displacement Fluid" for name in materials_db.FLUID_TYPES},
        "fluid_data": {"Displacement Fluid": {
            "name": "Displacement Fluid", "material_name": materials_db.DEFAULT_MATERIAL_NAMES["Displacement Fluid"],
            "volume": 0., "density": "", "effective_density": 0., "pump_rate": "", "min_rate": 0.,
            "duration_min": 0., "duration_str": "INVALID RATE", "cumul_time_min": 0.,
            "cumul_time_str": "INVALID RATE"}},
        "total_pump_time_min": 0., "total_pump_time_hhmm": "INVALID RATE",
        "inactive_slurry_drafts": {}, "preflush_calc": None,
        "centralizer_config": new_config(),
        "cement_params": {}, "cement_additives_dfs": {}, "cement_initialized_slurries": [],
        "spacer_dfs": {}, "spacer_initialized_names": [],
        "lab_grid_dfs": {}, "lab_qc_params": {}, "lab_initialized_slurries": [],
        "lab_source_signatures": {},
    }
    def without_defaults(record, expected):
        result = {}
        for key, value in record.items():
            if key in expected:
                if isinstance(value, dict) and isinstance(expected[key], dict):
                    value = without_defaults(value, expected[key])
                    if not value:
                        continue
                elif (isinstance(value, bool) == isinstance(expected[key], bool)
                      and value == expected[key]):
                    continue
            result[key] = value
        return result

    active = project.get("fluids_config", {}).get("active", [])
    job = project.get("job_type", DOC_CONTROL_DEFAULTS["job_type"])
    for slurry in (name for name in active if name in materials_db.CEMENT_FORMULATION_FLUIDS):
        defaults["cement_params"][slurry] = {
            "yield": 1.180, "mix_water": 119.0, "dead_vol": None,
            "tank_name": materials_db.get_tank_name(job), "last_job_type": job,
            "base_cement": "Cement G Delijan", "cmt_sg": catalog_cement_sg(),
            "cmt_sg_source": "catalog", "total_sacks": 0.0, "auto_calc": True,
            "top_mode": "Not entered", "top_depth": None, "top_job_type": job,
        }
        defaults["cement_additives_dfs"][slurry] = pd.DataFrame(columns=[*REQUIRED_ADDITIVE_COLUMNS, "Density"])
        defaults["cement_initialized_slurries"].append(slurry)
        # These are the empty controls mounted before any valid lab source
        # exists, not measured results, grids or review/source signatures.
        defaults["lab_qc_params"][slurry] = {
            "api_fl": 0.0, "free_water": 0.0, "free_water_45": None,
            "surface_hardened_hours": None,
            **{field: None if kind == "number" else "" for field, _, kind in THICKENING_TEST_FIELDS},
        }
        defaults["lab_qc_params"][slurry].update(
            rheology={key: new_rheology_dataset() for key, _ in RHEOLOGY_DATASETS},
            compressive=compressive_inputs({}))
        if slurry not in project.get("lab_grid_dfs", {}):
            continue
        # Reuse the real cup authority only to recognize its exact untouched
        # initialization. Any edited row/lot/QC or unknown field survives.
        params = source.get("cement_params", {}).get(slurry, {})
        fluid = source.get("fluids_config", {}).get("params", {}).get(
            slurry, source.get("fluid_data", {}).get(slurry, {}))
        try:
            volume = clean_number(fluid.get("volume"))
            density = require_positive_density(fluid.get("density"))
            if volume <= 0 or not 75 <= density <= 180:
                continue
            grid = build_lab_df_from_phase5(
                source["cement_additives_dfs"].get(slurry, pd.DataFrame()),
                base_cement=params.get("base_cement", "Cement G Delijan"),
                slurry_weight_pcf=density, slurry_volume_bbl=volume,
                cmt_sg=resolve_cement_sg(params), recalculate_mass=True)
            signature = lab_source_signature(source, slurry)
        except (ValueError, TypeError):
            continue  # Unreconstructable persisted content is never ignored.
        defaults["lab_grid_dfs"][slurry] = grid
        if (project["lab_grid_dfs"][slurry] == serialize_item(grid)
                and not without_defaults(project.get("lab_qc_params", {}).get(slurry, {}),
                                         serialize_item(defaults["lab_qc_params"][slurry]))):
            defaults["lab_source_signatures"][slurry] = signature
        defaults["lab_initialized_slurries"].append(slurry)
        empty_qc = defaults["lab_qc_params"][slurry]
        defaults[f"lab_payload_{slurry}"] = {
            "grid": grid, "rheology": build_rheology(empty_qc)[0],
            "bhct": source.get("well_data", {}).get("bhct", source.get("bhct")),
            "bhst": source.get("well_data", {}).get("bhst", source.get("bhst")),
            "bhsp": source.get("well_data", {}).get("bhsp", ""),
            **{key: params.get(field, "") for key, field in (
                ("base_fluid", "base_fluid_gal_sk"), ("mix_water", "mix_water_gal_sk"),
                ("mix_fluid", "mix_fluid_gal_sk"))},
            "solution_density": materials_db.SOLUTION_DENSITY_PCF,
        }
        if slurry in materials_db.PLACEMENT_SLURRIES:
            defaults[f"lab_payload_{slurry}"].update(
                api_fl=0., api_fl_collected=0., free_water=0., free_water_45=None,
                surface_hardened_hours=None, compressive={},
                **{field: empty_qc[field] for field, _, _ in THICKENING_TEST_FIELDS})
    for name in active:
        if name in materials_db.RHEOLOGY_ONLY_FLUIDS and name != "Pre Flush":
            defaults["lab_qc_params"][name] = {"rheology": {
                key: new_rheology_dataset() for key, _ in RHEOLOGY_DATASETS}}
        elif name == "Pre Flush" and name in project.get("lab_qc_params", {}):
            from centralizer_adapter import _dynamic_fann
            legacy = source.get("centralizer_config", {}).get("aux_rheology", {}).get(name)
            try:
                _dynamic_fann(legacy, name)
            except ValueError:
                continue
            data = {key: {**new_rheology_dataset(), "gel_10_sec": "-", "gel_10_min": "-"}
                    for key, _ in RHEOLOGY_DATASETS}
            data["bhct_down"].update(selected=True, readings=legacy)
            defaults["lab_qc_params"][name] = {"rheology": data}
    defaults["standalone_spacer_config"] = {
        "mode": None, "dead_vol": None, "tank_name": materials_db.get_tank_name(job)}
    defaults["formation_pressure_config"] = {"mode": "basic", "profile": []}
    defaults["preflush_config"] = {
        "type": "Combined (Water + NaCl + Wash)", "nacl_multiplier": 126.0, "wash_multiplier": 3.0,
    }

    reports = project.get("report_text_state", {})
    for key in ("exec_summary_text", "procedure_text"):
        meta = reports.get(key)
        if (isinstance(meta, dict) and set(meta) == {"generated", "source_signature", "history"}
                and isinstance(meta["generated"], str) and project.get(key) == meta["generated"]
                and meta["history"] == [] and isinstance(meta["source_signature"], str)):
            project.pop(key)
            reports.pop(key)
    if reports == {}:
        project.pop("report_text_state", None)

    comparison = without_defaults(project, serialize_item(defaults))
    return hashlib.md5(json.dumps(comparison, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _mark_project_saved(project_json):
    st.session_state["_saved_sig"] = hashlib.md5(project_json.encode()).hexdigest()
    st.session_state["_saved_comparison_sig"] = _project_comparison_signature(project_json)
    st.session_state["_saved_at"] = datetime.now().strftime("%H:%M")
    st.session_state.pop("_saved_from_upload", None)
    st.session_state.pop("_baseline_loaded_project", None)

# Loading a project is itself a saved checkpoint. Capture the normalized
# project after the first complete render so old files that need in-memory
# defaults do not immediately show a false unsaved-changes warning.
if (st.session_state.get("_baseline_loaded_project", False) and current_project_json
        and "_saved_comparison_sig" in st.session_state):
    loaded_signature = st.session_state.get("_saved_comparison_sig")
    current_signature = _project_comparison_signature(current_project_json)
    # A failed first render may have been repaired alongside a genuine edit.
    # Keep the validated incoming checkpoint as authority in that case.
    if loaded_signature == current_signature:
        st.session_state["_saved_sig"] = hashlib.md5(current_project_json.encode()).hexdigest()
        st.session_state["_saved_comparison_sig"] = current_signature
    st.session_state["_saved_from_upload"] = True
    st.session_state.pop("_baseline_loaded_project", None)

# JSON is a work-in-progress checkpoint; keep incomplete additive rows, but
# show their location so they cannot be mistaken for export-ready values.
# BUG-27: every empty cell used to render its own warning card on every
# rerun, flooding the sidebar on a draft with several unfinished rows.
# Aggregate them into a single card that lists all affected slurries/rows.
_incomplete_additive_rows = []
for _slurry in st.session_state.get("fluids_config", {}).get("active", []):
    _additives = st.session_state.get("cement_additives_dfs", {}).get(_slurry)
    if isinstance(_additives, pd.DataFrame) and "User Input" in _additives.columns:
        _empty_rows = [str(_row_number)
                       for _row_number, _value in enumerate(_additives["User Input"], start=1)
                       if pd.isna(_value) or str(_value).strip() == ""]
        if _empty_rows:
            _incomplete_additive_rows.append(f"{_slurry}: row {', '.join(_empty_rows)}")
if _incomplete_additive_rows:
    _project_manager_slot.warning(
        "Phase V additive rows with an empty User Input (concentration) — "
        + "; ".join(_incomplete_additive_rows)
        + ". You can save this draft; complete the cells before Word export."
    )

@st.dialog("Download current project", on_dismiss="rerun")
def _download_project(project_json, filename):
    # A download starts before a pending editor blur/rerun can finish. Prepare
    # with a regular button first; the modal prevents further source edits
    # while these exact bytes are offered, without another saved-state cache.
    st.caption("Your current inputs are ready. Download below, or close to continue editing.")
    if st.download_button(
        label="Download Project (.json)",
        data=project_json,
        file_name=filename,
        mime="application/json",
        on_click=_mark_project_saved,
        args=(project_json,),
    ):
        st.rerun()

if _project_manager_slot.button(
    "Prepare project download",
    help="Commit current inputs, then download the prepared JSON file in the dialog.",
    disabled=not bool(current_project_json)
):
    _download_project(current_project_json, project_filename)

# The same serialized comparison protects every current/future project key.
# Failure to serialize is uncertainty, never permission to discard the well.
_current_sig = hashlib.md5(current_project_json.encode()).hexdigest()
if (not current_project_json or (st.session_state.get("_baseline_loaded_project")
                                 and "_saved_comparison_sig" not in st.session_state)):
    _has_unsaved_changes = True
elif "_saved_comparison_sig" in st.session_state:
    _has_unsaved_changes = (st.session_state["_saved_comparison_sig"]
                            != _project_comparison_signature(current_project_json))
elif "_saved_sig" in st.session_state:
    _has_unsaved_changes = st.session_state["_saved_sig"] != _current_sig
else:
    _has_unsaved_changes = (_project_comparison_signature(current_project_json)
                            != _project_comparison_signature(json.dumps(
                                serialize_item({"report_date": date.today()}))))
if _has_unsaved_changes:
    _project_manager_slot.warning("⚠️ You have unsaved changes.")
    _project_manager_slot.caption("Prepare a download above, then save the file to keep them safe.")
elif st.session_state.get("_saved_from_upload"):
    _project_manager_slot.caption("💾 Project loaded. Download again after editing to save changes.")
elif st.session_state.get("_saved_at"):
    _project_manager_slot.caption(f"💾 All changes saved at {st.session_state['_saved_at']}.")
else:
    _project_manager_slot.caption("💾 Nothing is saved automatically. Download your project (above) before closing this tab.")

def _clear_all_session_data(preserved_keys=None):
    """Wipes all well/project data from session_state, keeping only the
    given system keys (widget keys used by the sidebar controls themselves)."""
    preserved_keys = preserved_keys or set()
    for key in list(st.session_state.keys()):
        if key not in preserved_keys:
            del st.session_state[key]

# 2. Import / Load Project (Clean-Slate Architecture)
uploader_revision = st.session_state.get("_uploader_revision", 0)
uploader_key = f"proj_uploader_{uploader_revision}"
uploaded_project = _project_manager_slot.file_uploader(
    "Load Project (.json)",
    type=["json"],
    key=uploader_key,
    help="Upload an existing well cementing project file to restore all inputs and tables."
)
if uploaded_project is not None and uploaded_project.size > 10_000_000:
    _project_manager_slot.error("Project file exceeds 10 MB; upload a smaller JSON project.")
    uploaded_project = None
if uploaded_project is not None:
    file_bytes = uploaded_project.getvalue()
    upload_sig = content_signature(file_bytes)
    already_loaded = st.session_state.get("last_loaded_hash") == upload_sig
    reload_requested = already_loaded and _project_manager_slot.button(
        "Reload uploaded project and discard current changes", key="_reload_uploaded_project",
        help="Replace current edits with the data in the attached JSON file."
    )
    pending_changes = _has_unsaved_changes
    if not already_loaded or reload_requested:
        try:
            # Parse and validate the entire project before touching the open well.
            prepared = decode_project(file_bytes, deserialize_item)
            replace_confirmed = False
            if not already_loaded and pending_changes:
                _project_manager_slot.warning(
                    "The open project has unsaved changes. Loading another file will discard those edits."
                )
                replace_confirmed = _project_manager_slot.button(
                    "Replace current project and discard unsaved changes", key="_confirm_upload_replacement"
                )
                if not replace_confirmed and _project_manager_slot.button("Cancel loading project", key="_cancel_upload_replacement"):
                    st.session_state["_uploader_revision"] = uploader_revision + 1
                    st.rerun()
            if reload_requested or not pending_changes or replace_confirmed:
                # Compute before publication: failed baseline serialization
                # must leave the currently open project untouched.
                checkpoint = serialize_item(prepared)
                # Match Phase I's first mount on the comparison copy only:
                # explicit null is blank; a missing/legacy-empty date defaults.
                if "report_date" not in checkpoint:
                    checkpoint["report_date"] = (None if "date" in checkpoint.get("doc_control", {})
                        and checkpoint["doc_control"]["date"] is None else serialize_item(date.today()))
                calendar = checkpoint["report_date"]
                calendar = calendar.get("val") if isinstance(calendar, dict) else calendar
                checkpoint.setdefault("doc_control", {})["date"] = "" if calendar is None else calendar
                loaded_signature = _project_comparison_signature(json.dumps(checkpoint, allow_nan=False))
                replace_project_state(st.session_state, prepared, upload_sig,
                                      preserved_keys=(uploader_key, "_uploader_revision"))
                st.session_state["_saved_comparison_sig"] = loaded_signature
                st.session_state["_baseline_loaded_project"] = True
                # FIX (requested, Level 1 #1): st.sidebar.success(...) here used
                # to be silently lost — st.rerun() immediately discards this
                # run's rendered element tree, including the success message
                # that was just drawn, so the operator never actually saw
                # confirmation that the project loaded (just a page flicker).
                # st.toast() is specifically designed to survive across the very
                # next rerun, unlike a normal element, so it's the correct
                # widget for a "confirm, then rerun" pattern like this one.
                st.toast(f"Project loaded: {uploaded_project.name}", icon="✅")
                st.rerun()
        except Exception as e:
            _project_manager_slot.error(f"Error loading project: {e}")

# 3. Start New / Clear All Data
# FIX (requested): this used to wipe everything on a single click, with no
# way back — no disk cache exists anymore (see the FIX note above), so a
# misclick here was genuinely unrecoverable, not just annoying. Now it's a
# two-step confirmation: the first click only arms a pending-confirmation
# flag and shows an explicit warning + Yes/Cancel; the actual wipe only
# happens on the second, explicit "Yes, clear everything" click. The pending
# flag is prefixed "_" so it's excluded from the saved project JSON like
# every other transient UI-only key in this app (see ignored_prefixes in
# get_serializable_state above) — it's not project data.
if "_confirm_clear_pending" not in st.session_state:
    st.session_state["_confirm_clear_pending"] = False

if not st.session_state["_confirm_clear_pending"]:
    if _project_manager_slot.button("🗑️ Start New / Clear All Data", help="Wipes all current well data from this session. Download your project first if you want to keep it."):
        st.session_state["_confirm_clear_pending"] = True
        st.rerun()
else:
    _project_manager_slot.error("⚠️ This permanently erases all current well data and cannot be undone. Download your project first if you want to keep it.")
    col_confirm_yes, col_confirm_no = _project_manager_slot.columns(2)
    with col_confirm_yes:
        if st.button("Yes, clear everything", key="_confirm_clear_yes", type="primary"):
            # Retire the uploader widget itself. A fresh key on the next run
            # prevents the still-attached file from silently reloading later.
            next_revision = uploader_revision + 1
            _clear_all_session_data(preserved_keys={uploader_key})
            st.session_state["_uploader_revision"] = next_revision
            st.session_state["_reset_navigation_to_phase1"] = True
            st.session_state["_confirm_clear_pending"] = False
            st.rerun()
    with col_confirm_no:
        if st.button("Cancel", key="_confirm_clear_cancel"):
            st.session_state["_confirm_clear_pending"] = False
            st.rerun()

_project_manager_slot.markdown("---")
