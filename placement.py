"""Explicit source selection for operational depths and tie-back host."""
import math
import re
import pandas as pd
from project_state import fingerprint

_MD = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?)\s*)?$")
HOST_DESCRIPTIONS = {"Previous Casing", "Casing", "Previous Liner", "Liner"}


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


def top_label(params):
    mode = params.get("top_mode")
    if mode == "Surface":
        return "surface", 0.0
    if mode == "Depth (m MD)" or (mode is None and params.get("top_depth") not in (None, "", 0)):
        depth = measured_depth(params.get("top_depth"))
        if depth is not None:
            return f"{depth:.1f} m", depth
    return ".... m [TOP NOT SET IN PHASE V]", None
