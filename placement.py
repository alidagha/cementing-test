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
