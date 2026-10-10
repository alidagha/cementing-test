"""Canonical project state, calculation refresh and review of edited report text."""
from datetime import date, datetime
from copy import deepcopy
import hashlib
import json
import math
import numpy as np
import pandas as pd
import materials_db
from rheology import validate_rheology_results
from engineering_tools import (require_positive_density, require_bhsp_density, require_positive_pump_rate,
                               require_preflush_material_name,
                               format_to_hr_mm, round_half_up, safe_float,
                               validate_lab_masses, validate_thickening_test, parse_effective_numeric,
                               validate_lab_collection_results, THICKENING_TEST_FIELDS, validate_compressive_test,
                               validate_lab_rheology, lab_temperature_valid, lab_review_signature,
                               MATERIAL_PROPERTY_SCHEMA, LEGACY_ADDITIVE_SG,
                               catalog_cement_sg, resolve_cement_sg, default_additive_density_gcm3,
                               is_salt_additive, SALT_MODEL_VERSION)

SLURRIES = materials_db.CEMENT_FORMULATION_FLUIDS


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


def request_description_for_job(job_type):
    """Format catalog job families; retain future job names unchanged."""
    if job_type in materials_db.JOB_TYPES:
        for prefix in ("TIE BACK LNR ", "CSG ", "LNR "):
            if job_type.startswith(prefix):
                return f"{job_type[len(prefix):]} {prefix.strip()} Cementing"
    return f"{job_type} Cementing"


DOC_CONTROL_DEFAULTS = {
    "job_type": "CSG 20\"",
    "hole_size": "26\"",
    "field": "",
    "well_location": "",
    "well_name": "",
    "rig_name": "",
    "client": "",
    "contract_number": "",
    "proposal_number": "",
    "cementing_method": "Primary Cementing",
    "district_phone": "061-341-43513",
    "made_by": "NIDC Cement Engineering and Planning Department",
    # FIX (requested): a formal engineering document needs an approval
    # chain and a revision marker, not just a single "Made By" line, to
    # go from "internal draft" to "citable record". Revision defaults to
    # "0" (the first issue of a document) rather than blank, since every
    # real document has *some* revision number from the start.
    "prepared_by": "",
    "checked_by": "M.Hasannezhad",
    "approved_by": "Sh.Jalili",
    "revision_no": "0"
}


DOC_CONTROL_DEFAULTS.update({key: "" for _, key in DOCUMENT_DETAIL_FIELDS})
DOC_CONTROL_DEFAULTS.update(checked_phone="+98-916-604-7042", approved_phone="+98-917-142-1265")
DOC_CONTROL_DEFAULTS["request_description"] = request_description_for_job(DOC_CONTROL_DEFAULTS["job_type"])
DOC_CONTROL_DEFAULTS["revision_description"] = DOC_CONTROL_DEFAULTS["request_description"]

WELL_DATA_DEFAULTS = {
    "mud_type": "WBM",
    "mud_density": "",
    "plastic_viscosity": "",
    "yield_point": "",
    "geo_md": None,
    "geo_tvd": None,
    "bhst": None,
    "bhct": None,
    "geo_gradient": None,
    "bhsp": ""
}


def refresh_well_derived(state):
    """Update only automatic values, using the same canonical/shadow pattern."""
    tvd, bhst = safe_float(state.get("geo_tvd"), None), safe_float(state.get("bhst"), None)
    gradient, pressure = None, ""
    if tvd is not None and math.isfinite(tvd) and tvd > 0:
        if bhst is not None and math.isfinite(bhst) and bhst >= 80:
            gradient = ((bhst - 80) / (tvd * 3.28084)) * 100
            if not math.isfinite(gradient):
                gradient = None
        try:
            mud_weight = require_bhsp_density(state.get("mud_density", ""))
            pressure_value = tvd * mud_weight * 0.02278
            pressure = str(pressure_value) if math.isfinite(pressure_value) else ""
        except (TypeError, ValueError, OverflowError):
            pass  # Invalid/unfinished sources stay empty and block readiness.
    for field, value in (("geo_gradient", gradient), ("bhsp", pressure)):
        if state.get("well_auto_fields", {}).get(field, False):
            state[field] = value
            if isinstance(state.get("well_data"), dict):
                state["well_data"][field] = value


def restore_canonical_fields(state):
    """Fill missing flat fields from legacy snapshots; explicit flat values win."""
    for name, defaults in (("doc_control", DOC_CONTROL_DEFAULTS), ("well_data", WELL_DATA_DEFAULTS)):
        nested = state.get(name)
        if not isinstance(nested, dict):
            continue
        for key in defaults:
            if key not in state and key in nested:
                state[key] = nested[key]
            if key in state:
                nested[key] = state[key]
    doc = state.get("doc_control", {})
    if isinstance(doc, dict):
        if "report_date" not in state and doc.get("date"):
            state["report_date"] = date.fromisoformat(str(doc["date"]))
        if "report_date" in state:
            value = state["report_date"]
            doc["date"] = value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    well = state.get("well_data", {})
    if isinstance(well, dict):
        for field, effective, default in (("mud_density", "effective_mud_density", None),
                                           ("plastic_viscosity", "effective_pv", None),
                                           ("yield_point", "effective_yp", None)):
            if field in state:
                state[effective] = parse_effective_numeric(state[field], default=default)
                well[effective] = state[effective]
    refresh_well_derived(state)


def _canonical(value):
    if isinstance(value, pd.DataFrame):
        return {"columns": list(value.columns), "rows": _canonical(value.to_dict("records"))}
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "items": _canonical(value.tolist())}
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is pd.NA:
        return {"missing": True}
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"nonfinite": str(value)}
        return value
    if isinstance(value, int):
        # BUG-16: fingerprint(150) and fingerprint(150.0) must be identical —
        # widget sources legitimately deliver the same quantity as int or
        # float, and a signature flip on int/float alone produced false
        # drift. Floats outside exact-int representation stay distinct.
        return float(value) if abs(value) <= 2 ** 53 else str(value)
    if hasattr(value, "item"):
        return _canonical(value.item())
    if value is None or isinstance(value, str):
        return value
    return str(value)


def fingerprint(value):
    encoded = json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def hardware_draft_pending(state):
    """A browser draft is not validated hardware until Phase II/III reviews it."""
    draft = state.get("hardware_editor_draft")
    return isinstance(draft, pd.DataFrame) and fingerprint(draft) != fingerprint(state.get("hardware_table"))


def is_project_key(key):
    """Exclude current and legacy widget keys at both save and load boundaries."""
    transient = ("_", "$$ID", "proj_uploader", "last_loaded_hash", "chk_fluid_",
                 "vol_", "den_", "rate_", "matname_", "fix_den_",
                 "cemb_", "sg_", "tank_choice_", "dv_", "override_", "yd_ov_", "mw_ov_")
    return isinstance(key, str) and key != "app_mode_key" and not key.startswith(transient)


def invalidate_document(state):
    for key in ("_compiled_doc_bytes", "_compiled_doc_filename", "_compiled_doc_signature"):
        state.pop(key, None)


def validate_material_properties(state):
    """Current property provenance is explicit; only version zero is historical."""
    version = state.get("material_property_schema", 0)
    if type(version) is not int or version not in (0, MATERIAL_PROPERTY_SCHEMA):
        raise ValueError("Unsupported material_property_schema")
    if version == MATERIAL_PROPERTY_SCHEMA:
        records = list(state.get("cement_params", {}).values())
        records += [draft["cement_params"] for draft in state.get("inactive_slurry_drafts", {}).values()
                    if "cement_params" in draft]
        for params in records:
            if params.get("cmt_sg_source") not in ("catalog", "manual"):
                raise ValueError("cmt_sg_source must be catalog or manual")
            if "cmt_sg" not in params:
                raise ValueError("Current cement parameters require cmt_sg")


def migrate_material_properties(state):
    """Migrate active and archived catalog defaults once, before any consumer."""
    validate_material_properties(state)
    if state.get("material_property_schema", 0) == MATERIAL_PROPERTY_SCHEMA:
        return False
    params = deepcopy(state.get("cement_params", {}))
    additives = deepcopy(state.get("cement_additives_dfs", {}))
    drafts = deepcopy(state.get("inactive_slurry_drafts", {}))

    def migrate_record(p, df):
        if p is not None:
            name = p.get("base_cement", "Cement G Delijan")
            known = materials_db.resolve_known_material(name)
            name = known[0] if known is not None else name
            sg = p.get("cmt_sg", 3.20)
            catalog = ("cmt_sg" not in p or (name == "Cement G Delijan" and sg == 3.20)
                       or (name == "Cement D Delijan" and sg == 3.16))
            p["cmt_sg_source"] = "catalog" if catalog else "manual"
            p["cmt_sg"] = catalog_cement_sg(name) if catalog else sg
        if isinstance(df, pd.DataFrame):
            if "Density" not in df:
                df["Density"] = None
            for index, row in df.iterrows():
                match = materials_db.resolve_known_material(row.get("Name"))
                if match is None or match[0] not in LEGACY_ADDITIVE_SG:
                    continue
                name, _, physical = match
                value = row.get("Density")
                if pd.isna(value) or value == "" or value == LEGACY_ADDITIVE_SG[name]:
                    df.at[index, "Density"] = default_additive_density_gcm3(name, physical)

    for slurry in params.keys() | additives.keys():
        migrate_record(params.get(slurry), additives.get(slurry))
    for draft in drafts.values():
        migrate_record(draft.get("cement_params"), draft.get("cement_additives_dfs"))
    # Publish only after every record has migrated successfully.
    for key, value in (("cement_params", params), ("cement_additives_dfs", additives),
                       ("inactive_slurry_drafts", drafts)):
        if key in state:
            state[key] = value
    for slurry in params.keys() | additives.keys():
        token = "".join(c if c.isalnum() else "_" for c in slurry).lower()
        key = f"_editor_additives_slurry_{token}_revision"
        state[key] = state.get(key, 0) + 1
        key = f"_cmt_sg_revision_{token}"
        state[key] = state.get(key, 0) + 1
    state["material_property_schema"] = MATERIAL_PROPERTY_SCHEMA
    invalidate_document(state)
    return True


def purge_inactive_slurries(state, active):
    saved_fields = ("cement_additives_dfs", "cement_params", "lab_grid_dfs", "lab_qc_params")
    for key in (*saved_fields, "lab_source_signatures"):
        if not isinstance(state.get(key, {}), dict):
            raise ValueError(f"{key} must be a dictionary; review or reload the project")
    for key in ("cement_initialized_slurries", "lab_initialized_slurries"):
        if not isinstance(state.get(key, []), list):
            raise ValueError(f"{key} must be a list; review or reload the project")
    drafts = state.setdefault("inactive_slurry_drafts", {})
    if not isinstance(drafts, dict):
        raise ValueError("inactive_slurry_drafts must be a dictionary; review or reload the project")
    for slurry in SLURRIES:
        if slurry in active:
            draft = drafts.get(slurry)
            if draft is not None:
                if not isinstance(draft, dict):
                    raise ValueError(f"{slurry}: inactive draft is invalid; review or reload the project")
                restored_lab = False
                for key in saved_fields:
                    if key in draft and slurry not in state.setdefault(key, {}):
                        state[key][slurry] = deepcopy(draft[key])
                        restored_lab |= key in ("lab_grid_dfs", "lab_qc_params")
                # The restored lab values remain visible, but must be reviewed
                # before export even if the engineer toggled the fluid back on
                # without changing density, additives or well conditions.
                if restored_lab:
                    state.setdefault("lab_source_signatures", {}).pop(slurry, None)
                drafts.pop(slurry)
            continue
        snapshot = {key: deepcopy(state[key][slurry]) for key in saved_fields
                    if slurry in state.get(key, {})}
        if snapshot:
            drafts[slurry] = snapshot
        for prefix in ("cement_calc_", "cement_raw_calc_", "cement_blend_", "cement_note_", "lab_payload_", "_p7_synced_sig_", "_lab_grid_revision_"):
            state.pop(prefix + slurry, None)
        for key in ("cement_additives_dfs", "cement_params", "lab_grid_dfs", "lab_qc_params", "lab_source_signatures"):
            state.get(key, {}).pop(slurry, None)
        for key in ("cement_initialized_slurries", "lab_initialized_slurries"):
            if slurry in state.get(key, []):
                state[key].remove(slurry)
        token = "".join(c if c.isalnum() else "_" for c in slurry).lower()
        stems = [f"{p}_{token}_" for p in ("cemb", "sg", "tank_choice", "dv", "override", "yd_ov", "mw_ov")]
        stems += ["_" + p for p in stems]
        stems += [f"_editor_additives_{token}_", f"_editor_lab_tbl_{token}_", f"_sync_btn_{token}_"]
        stems += [f"_rheo_{token}_", f"_comp_{token}_"]
        stems += [f"_qc_{p}_in_{token}_" for p in ("bhct", "fl", "fw", "fw45", "surface_hours", "comp", "tt", "tt_endpoint")]
        stems += [f"_qc_{field}_in_{token}_" for field, _, _ in THICKENING_TEST_FIELDS]
        # BUG-15: the phase V/VI editors additionally keep a revision counter
        # and editor_state keeps a "_editor_source_" mirror of every editor
        # key; none of these matched the stems above and survived the purge.
        stems += [f"_editor_additives_slurry_{token}_revision",
                  f"_editor_source__editor_additives_{token}_",
                  f"_editor_source__editor_lab_tbl_{token}_"]
        for key in list(state):
            k = str(key)
            for stem in stems:
                if k.startswith(stem):
                    remainder = k[len(stem):]
                    # BUG-24: slugified tokens collide as literal prefixes —
                    # "Lead #1" becomes "lead__1", so the stem "..._lead_"
                    # also prefix-matches "..._lead__1_...". A remainder that
                    # continues with "_" is a DIFFERENT slurry's key and must
                    # survive. (Exact revision keys leave an empty remainder.)
                    if remainder.startswith("_"):
                        continue
                    state.pop(key, None)
                    break


def refresh_fluids(state):
    """Same phase-IV calculation, fed by its canonical inputs rather than caches.

    F-02 (system audit 2026-09-29, owner-approved): every ValueError raised
    here is prefixed 'Phase IV:' so that when prepare_calculations wraps it,
    the Phase X issue still carries the phase token and _phase_for_issue can
    resolve the deep-link rescue button. Before this, messages like
    '{name}: active fluid volume must be positive ...' surfaced as
    'Review the current calculation inputs before export (...)': the operator
    was told WHAT was wrong but never WHERE to go (audit L8-03)."""
    cfg = state.get("fluids_config", {})
    active = sorted(cfg.get("active", []), key=materials_db.HYDRAULIC_EXECUTION_ORDER.index)
    cfg["active"] = active
    if not active:
        raise ValueError("Phase IV: select and configure the fluid train before export")
    old = state.get("fluid_data", {})
    result = {}
    cumulative = 0.0
    for name in active:
        # Old projects may have fluid_data but no params entry; preserve those inputs.
        source = cfg.get("params", {}).get(name, old.get(name, {}))
        if not isinstance(source, dict):
            raise ValueError(f"Phase IV: {name}: review the fluid inputs before export")
        if source.get("volume") in (None, ""):
            raise ValueError(f"Phase IV: {name}: enter the fluid volume before export")
        # F-02: a textual volume (malformed JSON stranded in fluid_data) used
        # to escape here as a RAW float() ValueError — an uncontrolled
        # message with no phase token, killing the deep-link rescue path.
        # Give it the same controlled, prefixed treatment as every other
        # gate in this function (offender named, repair location stated).
        volume = safe_float(source["volume"], None)
        if volume is None:
            raise ValueError(f"Phase IV: {name}: unreadable fluid volume "
                             f"({source['volume']!r}) — open Phase IV to repair it")
        density = source.get("density")
        if name == "Displacement Fluid":
            density = state.get("mud_density") or state.get("well_data", {}).get("mud_density")
        if density is None or not str(density).strip():
            raise ValueError(f"Phase IV: {name}: enter the fluid density before export")
        density = str(density)
        effective = require_positive_density(density)
        if source.get("pump_rate") is None or not str(source["pump_rate"]).strip():
            raise ValueError(f"Phase IV: {name}: enter the pump rate before export")
        rate = str(source["pump_rate"])
        minimum = require_positive_pump_rate(rate)
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError(f"Phase IV: {name}: active fluid volume must be positive; "
                             "enter a volume or deselect the fluid")
        material_name = source.get("material_name", materials_db.DEFAULT_MATERIAL_NAMES.get(name, ""))
        if name == "Pre Flush":
            require_preflush_material_name(material_name)
        duration = volume / minimum
        cumulative += duration
        result[name] = {
            "name": name, "material_name": str(material_name),
            "volume": volume, "density": density, "effective_density": effective,
            "pump_rate": rate, "min_rate": minimum, "duration_min": duration,
            "duration_str": format_to_hr_mm(duration), "cumul_time_min": cumulative,
            "cumul_time_str": format_to_hr_mm(cumulative),
        }
    state["fluid_data"] = result
    state["total_pump_time_min"] = cumulative
    state["total_pump_time_hhmm"] = format_to_hr_mm(cumulative)


def refresh_preflush(state):
    if "Pre Flush" not in state.get("fluids_config", {}).get("active", []):
        state["preflush_calc"] = None
        return []
    cfg = state.get("preflush_config")
    if not isinstance(cfg, dict):
        return ["Pre Flush: open Phase VI to review the formulation before export."]
    kind = cfg.get("type")
    kind = {"Chemical Wash": "Water + Chemical Wash", "Combined / Custom": "Combined (Water + NaCl + Wash)"}.get(kind, kind)
    if kind not in {"Fresh Water Only", "Water + Chemical Wash", "Brine (Water + NaCl)", "Combined (Water + NaCl + Wash)"}:
        return ["Pre Flush: review the fluid type in Phase VI before export."]
    info = state["fluid_data"]["Pre Flush"]
    volume = float(info["volume"])
    salt = float(cfg.get("nacl_multiplier", 126.0)) if kind in {"Brine (Water + NaCl)", "Combined (Water + NaCl + Wash)"} else 0.0
    wash = float(cfg.get("wash_multiplier", 3.0)) if kind in {"Water + Chemical Wash", "Combined (Water + NaCl + Wash)"} else 0.0
    state["preflush_calc"] = {
        "type": kind, "volume_bbl": volume, "density_pcf": info["density"],
        "effective_density": info["effective_density"], "water_bbl": round_half_up(volume, 1),
        "nacl_multiplier": salt, "wash_multiplier": wash,
        "nacl_lbs": round_half_up(volume * salt, 1), "wash_gal": round_half_up(volume * wash, 1),
    }
    return []


def lab_source_signature(state, slurry):
    p = state.get("cement_params", {}).get(slurry, {})
    fluid = state.get("fluid_data", {}).get(slurry, {})
    # Cup masses do not depend on field volume, tank or manual field water.
    well = state.get("well_data", {})
    source = {"schema": 3, "material_property_schema": state.get("material_property_schema", 0),
                        "base_cement": p.get("base_cement", "Cement G Delijan"),
                        "cmt_sg": resolve_cement_sg(p),
                        "density": fluid.get("density", "118.0"),
                        "effective_density": fluid.get("effective_density"),
                        "bhst": well.get("bhst", state.get("bhst", "-")), "bhsp": well.get("bhsp", ""),
                        "bhct": well.get("bhct", state.get("bhct")),
                        "additives": state.get("cement_additives_dfs", {}).get(slurry, pd.DataFrame())}
    additives = source["additives"]
    if isinstance(additives, pd.DataFrame) and any(
            is_salt_additive(row.get("Material Type", ""), row.get("Name", ""))
            and safe_float(row.get("User Input"), 0.0) > 0.0
            for _, row in additives.iterrows()):
        source["salt_model_version"] = SALT_MODEL_VERSION
    return fingerprint(source)


def refresh_lab_payloads(state):
    issues = []
    for slurry in state.get("fluids_config", {}).get("active", []):
        if slurry not in materials_db.RHEOLOGY_LAB_FLUIDS:
            continue
        full_lab = slurry in materials_db.PLACEMENT_SLURRIES
        grid = state.get("lab_grid_dfs", {}).get(slurry)
        qc = state.get("lab_qc_params", {}).get(slurry)
        has_old_data = grid is not None or f"lab_payload_{slurry}" in state
        if not has_old_data:
            if not full_lab:
                issues.append(f"{slurry}: open Phase VII to enter and review the internal Lab/Rheology data.")
            continue
        if (not isinstance(grid, pd.DataFrame) or not isinstance(qc, dict)
                or state.get("lab_source_signatures", {}).get(slurry) != lab_source_signature(state, slurry)):
            state.pop(f"lab_payload_{slurry}", None)
            issues.append(f"{slurry}: review Phase VII; the lab data has not been checked against the current formulation and well conditions.")
            continue
        required = ("Material", "Concentration", "Unit", "Mass")
        incomplete_row = False
        for row_number, (_, row) in enumerate(grid.iterrows(), start=1):
            def missing(field):
                value = row.get(field)
                return pd.isna(value) or str(value).strip().lower() in {"", "none", "nan", "<na>"}
            if any(not missing(field) for field in (*required, "Lot No")) and any(missing(field) for field in required):
                issues.append(f"{slurry}: Phase VII lab row {row_number} is incomplete; enter Material, Concentration, Unit and Mass, or delete the row before Word export.")
                incomplete_row = True
                break
        if incomplete_row:
            state.pop(f"lab_payload_{slurry}", None)
            continue
        try:
            validate_lab_masses(grid)
            rheology = validate_lab_rheology(qc, slurry)
        except ValueError as exc:
            state.pop(f"lab_payload_{slurry}", None)
            issues.append(f"{slurry}: Phase VII {exc}; correct the Lab/Rheology data before Word export.")
            continue
        extra = {}
        if full_lab:
            try:
                validate_lab_collection_results(qc)
            except ValueError as exc:
                state.pop(f"lab_payload_{slurry}", None)
                issues.append(f"{slurry}: Phase VII {exc}; review both Free Water measurements and Surface Sample Hours before Word export.")
                continue
            try:
                thickening = validate_thickening_test(qc)
            except ValueError as exc:
                state.pop(f"lab_payload_{slurry}", None)
                issues.append(f"{slurry}: Phase VII Thickening Time Test: {exc}.")
                continue
            try:
                compressive = validate_compressive_test(qc)
            except ValueError as exc:
                state.pop(f"lab_payload_{slurry}", None)
                issues.append(f"{slurry}: Phase VII {exc}.")
                continue
            api_fl = qc.get("api_fl", 0.0)
            if isinstance(api_fl, bool) or not isinstance(api_fl, (int, float)) or not math.isfinite(api_fl):
                issues.append(f"{slurry}: Phase VII api_fl must be a finite numeric value; review the lab QC input.")
                continue
            extra = {"api_fl": api_fl * 2.0, "api_fl_collected": api_fl,
                     "free_water": qc.get("free_water", "-"), "compressive": compressive,
                     "free_water_45": qc["free_water_45"], "surface_hardened_hours": qc["surface_hardened_hours"],
                     **thickening}
        elif (not qc.get("reviewed", False)
              or qc.get("review_signature") != lab_review_signature(qc, grid)):
            state.pop(f"lab_payload_{slurry}", None)
            issues.append(f"{slurry}: Phase VII internal lab results must be confirmed before Word export.")
            continue
        p = state.get("cement_params", {}).get(slurry, {})
        well = state.get("well_data", {})
        bhct = well.get("bhct", state.get("bhct"))
        bhst = well.get("bhst", state.get("bhst"))
        if not lab_temperature_valid(bhct, bhst):
            state.pop(f"lab_payload_{slurry}", None)
            issues.append(f"{slurry}: Phase II & III BHCT and BHST must be finite, with BHCT <= BHST, before Lab review/export.")
            continue
        state[f"lab_payload_{slurry}"] = {
            "grid": grid, "rheology": rheology, "bhct": bhct, "bhst": bhst,
            "bhsp": well.get("bhsp", ""), "base_fluid": p.get("base_fluid_gal_sk", ""),
            "mix_water": p.get("mix_water_gal_sk", ""), "mix_fluid": p.get("mix_fluid_gal_sk", ""),
            "solution_density": materials_db.SOLUTION_DENSITY_PCF, **extra,
        }
    return issues


def prepare_calculations(state):
    from phase_5_cement import refresh_cement_calculations
    try:
        migrate_material_properties(state)
        purge_inactive_slurries(state, state.get("fluids_config", {}).get("active", []))
        refresh_fluids(state)
        issues = (["Phase II & III: review pending hardware edits before Word export."]
                  if hardware_draft_pending(state) else [])
        issues += refresh_cement_calculations(state)
        issues += refresh_preflush(state)
        issues += refresh_lab_payloads(state)
        md, tvd = safe_float(state.get("geo_md"), None), safe_float(state.get("geo_tvd"), None)
        if md is None or tvd is None or not math.isfinite(md) or not math.isfinite(tvd):
            issues.append("Phase II & III: MD and TVD must be valid depths before Word export.")
        elif tvd > md:
            issues.append(f"Phase II & III: TVD ({tvd:g} m) cannot exceed MD ({md:g} m); correct the depth before Word export.")
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        issues = [f"Review the current calculation inputs before export ({exc})."]
    if issues:
        invalidate_document(state)
    return issues


def sync_report_text(state, key, generated, signature):
    """Update untouched auto text; hold manual/legacy text for explicit review."""
    records = state.setdefault("report_text_state", {})
    meta = records.get(key)
    current = state.get(key)
    if current is None or (meta is None and current == generated):
        state[key] = generated
        records[key] = {"generated": generated, "source_signature": signature, "history": []}
        return False
    if meta is None:
        # Existing text from older JSON files may be manually edited.
        meta = {"generated": None, "source_signature": None, "history": []}
        records[key] = meta
    if meta.get("source_signature") != signature:
        if current == meta.get("generated"):
            state[key] = generated
            meta.update(generated=generated, source_signature=signature)
        else:
            return True
    return False


def accept_report_text(state, key, generated, signature, replace=False):
    meta = state.setdefault("report_text_state", {}).setdefault(key, {"history": []})
    if replace:
        current = state.get(key, "")
        if current and current != generated and current != meta.get("generated"):
            history = meta.setdefault("history", [])
            if not history or history[-1] != current:
                history.append(current)
            meta["history"] = history[-5:]
        state[key] = generated
    meta.update(generated=generated, source_signature=signature)


def restore_previous_text(state, key):
    meta = state.get("report_text_state", {}).get(key, {})
    history = meta.get("history", [])
    if history:
        state[key] = history.pop()
        meta["source_signature"] = None
