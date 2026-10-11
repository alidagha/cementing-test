"""Round 8A final static annulus and pressure model. No UI, renderer or cache.

Hardware supplies diameters/capacities; official Phase IV volumes supply cement
placement; well_profile supplies TVD. Derived results are rebuilt from current canonical inputs.
"""
import math
import re
from numbers import Real

import pandas as pd
import materials_db
from engineering_tools import BBL_TO_CUFT, parse_fractional_size, require_positive_density
from well_profile import tvd_at_md, trajectory_tvd_decreases

# Exact supported jobs, deliberately independent of future names/substrings.
CHART_JOBS = {
    'CSG 30"': "casing", 'CSG 24"': "casing", 'CSG 20"': "casing",
    'CSG 18 5/8"': "casing", 'CSG 13 3/8"': "casing", 'CSG 9 5/8"': "casing",
    'CSG 7"': "casing", 'LNR 7"': "liner", 'LNR 5"': "liner",
    'TIE BACK LNR 7"': "tieback", 'TIE BACK LNR 5"': "tieback",
    "CMT PLUG": None, "CMT SQUEEZE": None,
}
FLOAT_COLLAR_OFFSET_M = 12.2
LANDING_COLLAR_OFFSET_M = 24.4
PORE_FIELD = "pore_gradient_emw_pcf"
FRAC_FIELD = "frac_gradient_emw_pcf"
PCF_TO_KG_M3 = 0.45359237 / 0.3048**3
STANDARD_GRAVITY = 9.80665
PA_PER_PSI = 0.45359237 * STANDARD_GRAVITY / 0.0254**2
_MD_INTERVAL = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?)\s*)?$")


def chart_job_kind(job):
    if job not in CHART_JOBS:
        raise ValueError("Unsupported chart job; no inferred geometry is permitted.")
    return CHART_JOBS[job]


def _number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite numeric value.")
    if positive and value <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return float(value)


def validate_chart_inputs(well, placement):
    """Trust-boundary validation. Missing inputs are saveable unfinished drafts."""
    for field, label in ((PORE_FIELD, "Pore Gradient"), (FRAC_FIELD, "Fracture Gradient")):
        if well.get(field) is not None:
            _number(well[field], label, positive=True)
    if well.get(PORE_FIELD) is not None and well.get(FRAC_FIELD) is not None:
        if well[PORE_FIELD] >= well[FRAC_FIELD]:
            raise ValueError("Pore Gradient must be less than Fracture Gradient.")
    mode = placement.get("chart_excess_mode")
    if mode is not None and (not isinstance(mode, str) or mode not in ("apply", "ignore")):
        raise ValueError("Chart Capacity Excess Mode must be Apply Excess or Ignore Excess.")


def pressure_psi(density_pcf, tvd_m):
    """Explicit pcf -> kg/m³ -> hydrostatic Pa -> psi; no EMW autodetection."""
    pressure = density_pcf * PCF_TO_KG_M3 * STANDARD_GRAVITY * tvd_m / PA_PER_PSI
    return _number(pressure, "Resolved hydrostatic pressure")


def _ready_inputs(state):
    well = {**state.get("well_data", {}), **{k: state[k] for k in (PORE_FIELD, FRAC_FIELD) if k in state}}
    validate_chart_inputs(well, state.get("placement_config", {}))
    if any(well.get(key) is None for key in (PORE_FIELD, FRAC_FIELD)):
        raise ValueError("Enter Pore Gradient and Fracture Gradient (pcf EMW).")
    return well


def _segments(rows, start, end, label):
    """Retain Hardware row order; explicit intervals never get repaired."""
    segments, boundary = [], start
    for row in rows:
        match = _MD_INTERVAL.fullmatch(str(row.get("MD (m)")))
        if not match:
            raise ValueError(f"{label}: enter explicit valid Hardware MD bounds.")
        left, right = match.groups()
        top, bottom = (boundary, float(left)) if right is None else (float(left), float(right))
        if not math.isfinite(bottom) or not math.isfinite(top) or bottom <= top:
            raise ValueError(f"{label}: reversed/duplicate Hardware MD segment.")
        if top != boundary:
            raise ValueError(f"{label}: Hardware geometry gap or overlap at {boundary:g} m MD.")
        od = parse_fractional_size(row.get("Size (in)"))
        _number(od, f"{label} Hardware Size (in)", positive=True)
        # Hardware ID is numeric in the current schema; a hole diameter is Size.
        inner = _number(row.get("ID (in)"), f"{label} Hardware ID (in)", positive=True)
        if row["Description"] != "Open Hole Size" and inner > od:
            raise ValueError(f"{label}: Hardware ID cannot exceed OD.")
        segments.append({"top_md": top, "bottom_md": bottom, "od_in": od,
                         "id_in": inner, "description": row["Description"]})
        boundary = bottom
    if boundary < end or not segments:
        raise ValueError(f"{label}: missing explicit Hardware geometry to {end:g} m MD.")
    return [{**s, "bottom_md": min(s["bottom_md"], end)} for s in segments if s["top_md"] < end]


def _at(segments, md):
    matches = [s for s in segments if s["top_md"] <= md < s["bottom_md"]]
    if len(matches) != 1:
        raise ValueError(f"Hardware geometry is unresolved or ambiguous at {md:g} m MD.")
    return matches[0]


def _capacity(outer_in, inner_in=0.0):
    if outer_in <= inner_in:
        raise ValueError("Enclosing Hardware diameter must exceed the active string OD.")
    return math.pi/4 * (outer_in**2-inner_in**2) / 144 / 0.3048 / BBL_TO_CUFT


def resolve_chart_geometry(state):
    """Continuous active-string and enclosing paths from explicit Hardware only."""
    from placement import target_depth, hardware_choices, HOST_DESCRIPTIONS, measured_depth, excess_percentage
    job, config = state.get("job_type"), state.get("placement_config", {})
    kind = chart_job_kind(job)
    if kind is None:
        return None
    validate_chart_inputs(state, config)
    mode = config.get("chart_excess_mode") if config.get("job_type") == job else None
    if mode is None:
        raise ValueError("Choose Chart Capacity Excess Mode explicitly.")
    table = state.get("hardware_table")
    if not isinstance(table, pd.DataFrame) or table.empty:
        raise ValueError("Chart geometry requires explicit Tubular and Casing Hardware.")
    rows = table.to_dict("records")
    shoe = target_depth(table, job, config)
    if shoe is None:
        raise ValueError("Select the placement target before chart geometry can be resolved.")
    if shoe <= LANDING_COLLAR_OFFSET_M:
        raise ValueError("String shoe is too shallow for the project collar offsets.")
    description = {"casing": "Casing", "liner": "Liner", "tieback": "Tie Back"}[kind]
    active_rows = [r for r in rows if r.get("Description") == description]
    if kind == "liner":
        hangers = [measured_depth(r.get("MD (m)")) for r in rows if r.get("Description") == "Liner Hanger"]
        if len(hangers) != 1 or hangers[0] is None or not 0 < hangers[0] < shoe-FLOAT_COLLAR_OFFSET_M:
            raise ValueError("Liner geometry requires one valid Liner Hanger above the float collar.")
        hanger = hangers[0]
        active = _segments([r for r in rows if r.get("Description") == "Drill Pipes"], 0., hanger,
                           "Drill Pipes above Liner Hanger")
        active += _segments(active_rows, hanger, shoe, "Liner")
    else:
        active = _segments(active_rows, 0., shoe, description)
    if kind == "tieback":
        choices = hardware_choices(table, HOST_DESCRIPTIONS)
        host = choices.get(config.get("host_row"))
        if host is None:
            raise ValueError("Tie Back requires the explicitly selected Hardware host.")
        host_rows = [r for r in rows if r.get("Description") == host["description"]]
        # A duplicated token must not silently overwrite a possible host.
        selected = [r for r in host_rows if config.get("host_row") in
                    hardware_choices(pd.DataFrame([r]), HOST_DESCRIPTIONS)]
        if len(selected) != 1:
            raise ValueError("Tie Back host Hardware is ambiguous.")
        outer = _segments(host_rows, 0., shoe, "Tie Back host")
    else:
        previous = [r for r in rows if r.get("Description") in ("Previous Casing", "Previous Liner")]
        if not previous:
            raise ValueError("Resolve the Previous Casing / Previous Liner shoe from explicit Hardware.")
        previous_shoe = measured_depth(previous[-1].get("MD (m)"))
        if previous_shoe is None or previous_shoe >= shoe:
            raise ValueError("Previous shoe must lie above the active string shoe.")
        outer = _segments(previous, 0., previous_shoe, "Previous Casing / Previous Liner")
        outer += _segments([r for r in rows if r.get("Description") == "Open Hole Size"],
                           previous_shoe, shoe, "Open Hole Size")
    boundaries = sorted({0., shoe, *(s[k] for s in active+outer for k in ("top_md", "bottom_md"))})
    capacities = []
    for top, bottom in zip(boundaries, boundaries[1:]):
        inside, outside = _at(active, (top+bottom)/2), _at(outer, (top+bottom)/2)
        is_open = outside["description"] == "Open Hole Size"
        nominal = _capacity(outside["od_in"] if is_open else outside["id_in"], inside["od_in"])
        multiplier = 1.0
        if mode == "apply":
            field = "excess_csg_oh_pct" if is_open else "excess_csg_csg_pct"
            excess = excess_percentage(config, field)
            if excess is None:
                raise ValueError(f"Apply Excess requires {field} for the resolved annular geometry.")
            multiplier += excess/100
        capacities.append({"top_md": top, "bottom_md": bottom,
                           "nominal_bbl_per_m": nominal, "bbl_per_m": nominal*multiplier,
                           "kind": "open_hole" if is_open else "cased"})
    collar = shoe-FLOAT_COLLAR_OFFSET_M
    track = sum((min(s["bottom_md"], shoe)-max(s["top_md"], collar))*_capacity(s["id_in"])
                for s in active if s["bottom_md"] > collar)
    return {"kind": kind, "shoe_md": shoe, "float_collar_md": collar,
            "landing_collar_md": shoe-LANDING_COLLAR_OFFSET_M,
            "active_string": active, "capacity_segments": capacities, "shoe_track_bbl": track}


def interval_volume(segments, top, bottom):
    return math.fsum(max(0.0, min(bottom, s["bottom_md"])-max(top, s["top_md"]))*s["bbl_per_m"]
                     for s in segments)


def _fluid(state, name):
    row = state.get("fluids_config", {}).get("params", {}).get(name,
                state.get("fluid_data", {}).get(name, {}))
    volume = _number(row.get("volume"), f"Phase IV {name} volume", positive=True)
    density = require_positive_density(row.get("density"))
    return volume, density


def _allocate_upward(segments, bottom, volume):
    """Allocate an official volume once through piecewise MD capacities."""
    parts, remaining = [], volume
    while bottom > 0 and remaining > 0:
        segment = next(s for s in segments if s["top_md"] < bottom <= s["bottom_md"])
        available = (bottom-segment["top_md"])*segment["bbl_per_m"]
        amount = min(remaining, available)
        top = segment["top_md"] if amount == available else bottom-amount/segment["bbl_per_m"]
        if not top < bottom:
            raise ValueError("The fluid volume cannot be resolved at floating-point depth precision.")
        parts.append({"top_md": top, "bottom_md": bottom, "in_well_bbl": amount})
        remaining -= amount
        bottom = top
    return parts, bottom, remaining


def resolve_cement_placement(state, geometry=None):
    """Volume-driven final cement authority; report metadata never enters the model."""
    geometry = resolve_chart_geometry(state) if geometry is None else geometry
    active = state.get("fluids_config", {}).get("active", [])
    names = [name for name in materials_db.PLACEMENT_SLURRIES if name in active]
    if not names:
        raise ValueError("Phase IV: select at least one cement slurry for placement.")
    cement, bottom = [], geometry["shoe_md"]
    for index, name in enumerate(reversed(names)):
        volume, density = _fluid(state, name)
        track = geometry["shoe_track_bbl"] if index == 0 else 0.0
        if volume < track:
            raise ValueError(f"Phase IV {name}: volume {volume:g} bbl is below Shoe Track "
                             f"requirement {track:g} bbl; the track cannot be split between slurries.")
        parts, top, returned = _allocate_upward(geometry["capacity_segments"], bottom, volume-track)
        cement.append({"fluid": name, "top_md": top, "bottom_md": bottom,
                       "density_pcf": density, "entered_bbl": volume,
                       "in_well_bbl": math.fsum(part["in_well_bbl"] for part in parts),
                       "shoe_track_bbl": track, "returned_bbl": returned})
        bottom = top
    return cement


def resolve_final_fluid_intervals(state, geometry):
    """Final static B+ state from the same volume-driven cement placement."""
    cement = resolve_cement_placement(state, geometry)
    capacity = geometry["capacity_segments"]
    returned = {row["fluid"]: row["returned_bbl"] for row in cement}
    intervals = [dict(row) for row in cement if row["top_md"] < row["bottom_md"]]
    bottom = cement[-1]["top_md"]
    active = state.get("fluids_config", {}).get("active", [])
    for name in ("Scavenger", "Spacer Ahead", "Spacer", "Pre Flush"):
        volume, density = _fluid(state, name) if name in active else (None, None)
        if volume is None:
            continue
        parts, bottom, remaining = _allocate_upward(capacity, bottom, volume)
        intervals += [{**part, "fluid": name, "density_pcf": density} for part in parts]
        returned[name] = remaining
    if bottom > 0:
        density = require_positive_density(state.get("mud_density", state.get("well_data", {}).get("mud_density")))
        intervals.append({"fluid": "Mud", "top_md": 0.0, "bottom_md": bottom, "density_pcf": density,
                          "in_well_bbl": interval_volume(capacity, 0., bottom)})
    intervals.sort(key=lambda row: row["top_md"])
    if intervals[0]["top_md"] != 0 or intervals[-1]["bottom_md"] != geometry["shoe_md"] or any(
            a["bottom_md"] != b["top_md"] for a, b in zip(intervals, intervals[1:])):
        raise ValueError("Final annulus has an unexplained gap/overlap.")
    total = interval_volume(capacity, 0., geometry["shoe_md"])
    if not math.isclose(math.fsum(row["in_well_bbl"] for row in intervals), total, rel_tol=1e-12):
        raise ValueError("Final annular volume conservation failed.")
    for row in cement:
        if not math.isclose(row["in_well_bbl"]+row["shoe_track_bbl"]+row["returned_bbl"],
                            row["entered_bbl"], rel_tol=1e-12):
            raise ValueError("Cement volume conservation failed.")
    return {"annular_intervals": intervals, "cement_placement": cement, "returned_bbl": returned,
            "original_annular_bbl": total, "shoe_track_fluid": cement[0]["fluid"]}


def build_chart_model(state, geometry=None):
    kind = chart_job_kind(state.get("job_type"))
    if kind is None:
        return None
    geometry = resolve_chart_geometry(state) if geometry is None else geometry
    well = _ready_inputs(state)
    final = resolve_final_fluid_intervals(state, geometry)
    intervals = final["annular_intervals"]
    survey = state["well_geometry"].get("survey", pd.DataFrame())
    depths = sorted({0., geometry["shoe_md"], *(s[k] for s in intervals+geometry["capacity_segments"]
                     for k in ("top_md", "bottom_md")),
                     *(float(md) for md in survey.get("MD", []) if 0 <= float(md) <= geometry["shoe_md"])})
    tvds = tvd_at_md(state["well_geometry"], depths)
    security_issues = (["Static Well Security is unsupported: TVD decreases along the continuous trajectory."]
                       if trajectory_tvd_decreases(state["well_geometry"], geometry["shoe_md"]) else [])
    hydro = [] if security_issues else [0.0]
    if not security_issues:
        for top, bottom, tvd_top, tvd_bottom in zip(depths, depths[1:], tvds, tvds[1:]):
            fluid = _at(intervals, (top+bottom)/2)
            hydro.append(_number(hydro[-1]+pressure_psi(fluid["density_pcf"], tvd_bottom-tvd_top),
                                 "Cumulative hydrostatic pressure"))
    pressure = {"kind": "markers" if kind == "tieback" else "curves"}
    indices = [-1] if kind == "tieback" else range(len(depths))
    pressure["md_m"] = [depths[i] for i in indices]
    pressure["tvd_m"] = [tvds[i] for i in indices]
    for field, label in ((PORE_FIELD, "pore_psi"), (FRAC_FIELD, "frac_psi")):
        pressure[label] = [pressure_psi(well[field], v) for v in pressure["tvd_m"]]
    return {**geometry, **final, "hydrostatic": {"md_m": depths if hydro else [], "tvd_m": tvds if hydro else [],
                                                "pressure_psi": hydro},
            "pore_frac": pressure, "static_security_issues": security_issues,
            "fluid_sequence_ready": True, "static_security_ready": not security_issues}


def chart_readiness(state, include_fluids=False):
    """One shared completion authority for Phase II/III, direct export and model builds."""
    result = {"issues": [], "warnings": [], "model": None}
    try:
        if chart_job_kind(state.get("job_type")) is None:
            return result
        well = _ready_inputs(state)
        geometry = resolve_chart_geometry(state)
        try:
            mud = require_positive_density(state.get("mud_density", state.get("well_data", {}).get("mud_density")))
            if not well[PORE_FIELD] <= mud <= well[FRAC_FIELD]:
                result["warnings"].append("Mud Weight is outside the Pore–Fracture window (warning only).")
        except ValueError:
            pass  # Existing Mud input validation remains its own authority.
        if include_fluids:
            result["model"] = build_chart_model(state, geometry)
            result["issues"] += result["model"]["static_security_issues"]
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        result["issues"].append(str(exc))
    return result
