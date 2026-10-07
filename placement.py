"""Explicit source selection for operational depths and tie-back host."""
import math
import re
import pandas as pd
from project_state import fingerprint
from engineering_tools import require_nonnegative_number

_MD = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?)\s*)?$")
HOST_DESCRIPTIONS = {"Previous Casing", "Casing", "Previous Liner", "Liner"}
EXCESS_FIELDS = (("excess_csg_oh_pct", "Excess CSG-OH %", "excess_oh"),
                ("excess_csg_csg_pct", "Excess CSG-CSG %", "excess_csg"))


def excess_percentage(config, field):
    """Optional percentage points; zero is supplied, None is not supplied."""
    value = config.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"placement_config.{field} must be a finite nonnegative number or null.")
    return require_nonnegative_number(value, f"placement_config.{field}")


def measured_depth(value):
    """Return the deeper end of a valid MD interval, never a guessed number."""
    match = _MD.fullmatch(str(value))
    if not match:
        return None
    depth = max(float(x) for x in match.groups() if x is not None)
    return depth if math.isfinite(depth) and depth > 0 else None


def target_descriptions(job_type):
    name = str(job_type).upper()
    if "TIE BACK" in name:
        return {"Tie Back"}
    if "LNR" in name:
        return {"Liner"}
    if "PLUG" in name or "SQUEEZE" in name:
        return {"Casing", "Liner", "Tie Back", "Open Hole Size"}
    return {"Casing"}


def hardware_choices(table, descriptions):
    if not isinstance(table, pd.DataFrame) or table.empty:
        return {}
    choices = {}
    for _, row in table.iterrows():
        desc = str(row.get("Description", "")).strip()
        depth = measured_depth(row.get("MD (m)"))
        if desc not in descriptions or depth is None:
            continue
        size = str(row.get("Size (in)", "")).strip()
        token = fingerprint([desc, str(row.get("MD (m)")).strip(), size])
        choices[token] = {"description": desc, "depth": depth, "size": size,
                          "label": f"{desc} | {size or 'size not set'} in | {row.get('MD (m)')} m MD"}
    return choices


def target_depth(table, job_type, config):
    if config.get("job_type") != job_type:
        return None
    if config.get("target_row") == "__manual__":
        return measured_depth(config.get("manual_depth_m"))
    return hardware_choices(table, target_descriptions(job_type)).get(config.get("target_row"), {}).get("depth")


def host_label(table, job_type, config):
    if config.get("job_type") != job_type:
        return None
    row = hardware_choices(table, HOST_DESCRIPTIONS).get(config.get("host_row"))
    if not row or not row["size"]:
        return None
    kind = "Casing" if "Casing" in row["description"] else "Liner"
    return f'{row["size"]}" {kind}'


def top_label(params, job_type=None, target=None):
    if job_type is not None and params.get("top_job_type") not in (None, job_type):
        return ".... m [TOP NOT SET IN PHASE V]", None
    mode = params.get("top_mode")
    text, depth = ".... m [TOP NOT SET IN PHASE V]", None
    if mode == "Surface":
        text, depth = "surface", 0.0
    elif mode == "Depth (m MD)" or (mode is None and params.get("top_depth") not in (None, "", 0)):
        try:
            require_nonnegative_number(params.get("top_depth"), "Top depth")
        except ValueError:
            return text, None
        depth = measured_depth(params.get("top_depth"))
        if depth is not None:
            text = f"{depth:.1f} m"
    if target is not None and depth is not None and depth >= target:
        return f".... m [TOP MUST BE ABOVE TARGET DEPTH {target:.1f} m MD]", None
    return text, depth


def slurry_intervals(table, job_type, config, active_slurries, cement_params):
    """Share the summary's established deepest-first chain with readiness/Word."""
    target = target_depth(table, job_type, config)
    target_text = (f"{target:.1f} m MD" if target is not None
                   else ".... m MD [TARGET DEPTH NOT SELECTED IN PHASE II/III]")
    job = str(job_type).upper()
    chained = "CSG" in job or ("LNR" in job and "TIE BACK" not in job)
    bottom_text, bottom_depth = target_text, target
    intervals = {}
    for slurry in reversed(active_slurries) if chained else active_slurries:
        top, depth = top_label(cement_params.get(slurry, {}), job_type, target)
        if chained and bottom_depth is not None and depth is not None and depth >= bottom_depth:
            top, depth = f".... m [TOP MUST BE ABOVE PREVIOUS INTERVAL {bottom_depth:.1f} m MD]", None
        intervals[slurry] = {"top": top, "top_depth": depth,
                             "bottom": bottom_text, "bottom_depth": bottom_depth}
        if chained:
            bottom_text, bottom_depth = top, depth
    return intervals

# Report metadata only: none of these values participates in placement calculations.
SUMMARY_VERSION = 1
VOLUME_BASES = ("auto", "unspecified", "excess", "client_request", "direct")
TIE_BACK_ORIGINS = ("Target depth", "Tie Back Sleeve", "Shoe")
SQUEEZE_SCOPES = ("", "Liner", "Liner Lap", "Casing Region")
SUMMARY_SLURRIES = ("Lead", "Lead #1", "Lead #2", "Main", "Tail")
SUMMARY_NUMBERS = ("excess_csg_oh_pct", "excess_csg_csg_pct", "wet_stands", "liner_lap_m")
SUMMARY_TOKENS = ("wet_inside_host_row", "liner_lap_host_row")


def validate_executive_summary_config(config):
    """Validate report drafts without requiring optional facts to be supplied."""
    import materials_db
    if not isinstance(config, dict):
        raise ValueError("executive_summary_config must be a record.")
    allowed = {"version", "job_type", "placement_context_rows", "squeeze_scope",
               "squeeze_context_row", "tie_back_origin", "per_slurry"}
    if set(config) - allowed:
        raise ValueError("executive_summary_config contains unsupported fields.")
    if type(config.get("version")) is not int or config["version"] != SUMMARY_VERSION:
        raise ValueError("executive_summary_config has an unsupported version.")
    if config.get("job_type") not in materials_db.JOB_TYPES:
        raise ValueError("executive_summary_config.job_type is not supported.")
    for field, options in (("squeeze_scope", SQUEEZE_SCOPES), ("tie_back_origin", TIE_BACK_ORIGINS)):
        if field in config and (not isinstance(config[field], str) or config[field] not in options):
            raise ValueError(f"executive_summary_config.{field} is not supported.")
    contexts = config.get("placement_context_rows", [])
    if not isinstance(contexts, list) or any(not isinstance(token, str) for token in contexts):
        raise ValueError("executive_summary_config.placement_context_rows must contain string tokens.")
    if "squeeze_context_row" in config and not isinstance(config["squeeze_context_row"], str):
        raise ValueError("executive_summary_config.squeeze_context_row must be a string token.")
    per_slurry = config.get("per_slurry", {})
    if not isinstance(per_slurry, dict):
        raise ValueError("executive_summary_config.per_slurry must be a record.")
    for slurry, record in per_slurry.items():
        if slurry not in SUMMARY_SLURRIES or not isinstance(record, dict):
            raise ValueError("executive_summary_config.per_slurry contains an invalid slurry record.")
        if set(record) - {"volume_basis", *SUMMARY_NUMBERS, *SUMMARY_TOKENS}:
            raise ValueError(f"executive_summary_config.per_slurry.{slurry} contains unsupported fields.")
        if "volume_basis" in record and (not isinstance(record["volume_basis"], str)
                                        or record["volume_basis"] not in VOLUME_BASES):
            raise ValueError(f"executive_summary_config.per_slurry.{slurry}.volume_basis is not supported.")
        for field in SUMMARY_NUMBERS:
            excess_percentage(record, field)
        for field in SUMMARY_TOKENS:
            if field in record and not isinstance(record[field], str):
                raise ValueError(f"executive_summary_config.per_slurry.{slurry}.{field} must be a string token.")
    return config


def summary_config_for_job(config, job_type, active_slurries):
    """Ignore another job's metadata and inactive drafts in generation/signatures."""
    if config is None:
        return {}
    validate_executive_summary_config(config)
    if config["job_type"] != job_type:
        return {}
    records = {name: record for name, record in config.get("per_slurry", {}).items()
               if name in active_slurries}
    effective = {key: value for key, value in config.items() if key != "per_slurry"}
    if records:
        effective["per_slurry"] = records
    return effective if set(effective) - {"version", "job_type"} else {}


def resolve_report_excess(job_type, placement_config, summary_config, slurry):
    """One report-only override/global/absent authority for Summary and Word."""
    config = summary_config_for_job(summary_config, job_type, [slurry])
    overrides = config.get("per_slurry", {}).get(slurry, {})
    global_values = placement_config if placement_config.get("job_type") == job_type else {}
    return {report_key: (excess_percentage(overrides, field)
                         if overrides.get(field) is not None else excess_percentage(global_values, field))
            for field, _, report_key in EXCESS_FIELDS}


def hardware_row_metadata(table, token):
    """Resolve current labels through the existing stable hardware token model."""
    return hardware_choices(table, HOST_DESCRIPTIONS | {"Open Hole Size", "Tie Back"}).get(token)


def target_row_metadata(table, job_type, config):
    if config.get("job_type") != job_type:
        return None
    return hardware_choices(table, target_descriptions(job_type)).get(config.get("target_row"))


def hardware_context_label(table, token):
    row = hardware_row_metadata(table, token)
    if not row:
        return None
    kind = ("Open Hole" if row["description"] == "Open Hole Size" else
            "Casing" if "Casing" in row["description"] else
            "Liner" if "Liner" in row["description"] else "Tie Back")
    return f'{row["size"]}" {kind}' if row["size"] else kind
