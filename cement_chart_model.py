"""Round 8A final static annulus and pressure model. No UI, renderer or cache.

Hardware supplies diameters/capacities; official Phase IV volumes supply cement
placement; well_profile supplies TVD. Derived results are rebuilt from current canonical inputs.
"""
import math
import re
from numbers import Real

import pandas as pd
import materials_db
from engineering_tools import BBL_TO_CUFT, parse_fractional_size, require_positive_density, require_fluid_density
from well_profile import tvd_at_md, trajectory_tvd_decreases

# Exact supported jobs, deliberately independent of future names/substrings.
CHART_JOBS = {
    'CSG 30"': "casing", 'CSG 24"': "casing", 'CSG 20"': "casing",
    'CSG 18 5/8"': "casing", 'CSG 13 3/8"': "casing", 'CSG 9 5/8"': "casing",
    'CSG 7"': "casing", 'LNR 7"': "liner", 'LNR 5"': "liner",
    'LNR 4 1/2"': "liner",
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


def validate_formation_pressure_config(config):
    """Source-only schema; None is an unfinished cell, not a pressure fallback."""
    if not isinstance(config, dict) or set(config) != {"mode", "profile"}:
        raise ValueError("Formation Pressure configuration requires only mode and profile.")
    if config["mode"] not in ("basic", "advanced") or not isinstance(config["profile"], list):
        raise ValueError("Formation Pressure requires basic/advanced mode and a profile list.")
    previous = None
    for row in config["profile"]:
        if not isinstance(row, dict) or set(row) != {"md_m", "pore_psi", "frac_psi"}:
            raise ValueError("Formation profile rows require only MD, Pore and Fracture pressure.")
        for key, value in row.items():
            if value is not None:
                value = _number(value, f"Formation {key}", positive=key != "md_m")
                if key == "md_m" and value < 0:
                    raise ValueError("Formation MD must be nonnegative.")
        md = row["md_m"]
        if md is not None:
            if previous is not None and md <= previous:
                raise ValueError("Formation MD stations must be strictly increasing, without duplicates.")
            previous = md
        if row["pore_psi"] is not None and row["frac_psi"] is not None and row["pore_psi"] >= row["frac_psi"]:
            raise ValueError("Formation Pore pressure must be less than Fracture pressure.")


def formation_source(state):
    """Active pressure sources only, for the existing chart fingerprint authority."""
    config = state.get("formation_pressure_config", {"mode": "basic", "profile": []})
    if not isinstance(config, dict):
        return {"invalid_config": config}
    if config.get("mode") == "basic":
        well = state.get("well_data", {})
        return {"mode": "basic", **{key: state.get(key, well.get(key)) for key in (PORE_FIELD, FRAC_FIELD)}}
    return {"mode": config.get("mode"), "profile": config.get("profile")}


def _security_domain(geometry, trajectory):
    parts = []
    for segment in geometry["capacity_segments"]:
        if segment["kind"] != "open_hole":
            continue
        top, bottom = segment["top_md"], segment["bottom_md"]
        if parts and parts[-1]["bottom_md"] == top:
            parts[-1]["bottom_md"] = bottom
        else:
            parts.append({"top_md": top, "bottom_md": bottom})
    if not parts:
        return None
    for part in parts:
        part["top_tvd"], part["bottom_tvd"] = tvd_at_md(trajectory, [part["top_md"], part["bottom_md"]])
    return {"top_md": parts[0]["top_md"], "bottom_md": parts[-1]["bottom_md"],
            "top_tvd": parts[0]["top_tvd"], "bottom_tvd": parts[-1]["bottom_tvd"], "segments": parts}


def current_open_hole_domain(state):
    """Read-only public access to the B-1 resolved capacity/security domain."""
    geometry = resolve_chart_geometry(state)
    return None if geometry is None else _security_domain(geometry, state["well_geometry"])


def resolve_formation_profile(state, geometry, depths=None, tvds=None):
    """Normalize EMW or entered psig without extrapolation or trajectory arithmetic."""
    well = _ready_inputs(state)
    domain = _security_domain(geometry, state["well_geometry"])
    mode = formation_source(state)["mode"]
    if mode == "advanced":
        if domain is None:
            raise ValueError("Advanced Formation Profile is not applicable: no Current Open Hole is exposed.")
        rows = state["formation_pressure_config"]["profile"]
        if len(rows) < 2 or any(value is None for row in rows for value in row.values()):
            raise ValueError("Complete all Advanced Formation MD/Pore/Fracture stations, including both endpoints.")
        depths = [row["md_m"] for row in rows]
        if depths[0] != domain["top_md"] or depths[-1] != domain["bottom_md"]:
            raise ValueError("Advanced Formation profile must cover both exact Current Open Hole endpoints; no extrapolation.")
        if any(not any(part["top_md"] <= md <= part["bottom_md"] for part in domain["segments"]) for md in depths):
            raise ValueError("Every Formation MD station must lie inside Current Open Hole.")
        tvds = tvd_at_md(state["well_geometry"], depths)
        if trajectory_tvd_decreases(state["well_geometry"], geometry["shoe_md"]):
            raise ValueError("Static Well Security is unsupported: TVD decreases along the continuous trajectory.")
        for a, b, ta, tb in zip(rows, rows[1:], tvds, tvds[1:]):
            if ta == tb and (a["pore_psi"] != b["pore_psi"] or a["frac_psi"] != b["frac_psi"]):
                raise ValueError("Formation pressures at identical TVD must agree for TVD-linear interpolation.")
        pressure = {key: [row[key] for row in rows] for key in ("pore_psi", "frac_psi")}
        kind = "curves"
    else:
        depths = [0., geometry["shoe_md"]] if depths is None else depths
        tvds = tvd_at_md(state["well_geometry"], depths) if tvds is None else tvds
        indices = [-1] if geometry["kind"] == "tieback" else range(len(depths))
        depths, tvds = [depths[i] for i in indices], [tvds[i] for i in indices]
        pressure = {label: [pressure_psi(well[field], tvd) for tvd in tvds]
                    for field, label in ((PORE_FIELD, "pore_psi"), (FRAC_FIELD, "frac_psi"))}
        kind = "markers" if geometry["kind"] == "tieback" else "curves"
    return {"mode": mode, "kind": kind, "domain": domain, "md_m": depths, "tvd_m": tvds, **pressure}


def _linear_pressure(tvds, pressures, tvd):
    from bisect import bisect_right
    if not tvds[0] <= tvd <= tvds[-1]:
        raise ValueError("Pressure interpolation cannot extrapolate outside its source profile.")
    index = bisect_right(tvds, tvd)-1
    if tvds[index] == tvd:
        return pressures[index]
    fraction = (tvd-tvds[index])/(tvds[index+1]-tvds[index])
    return pressures[index]+fraction*(pressures[index+1]-pressures[index])


def _crossing_md(trajectory, top, bottom, tvd):
    """Bounded inversion of the existing MD->TVD authority, only in a known interval."""
    a, b = tvd_at_md(trajectory, [top, bottom])
    if tvd == a:
        return top
    if tvd == b:
        return bottom
    for _ in range(64):
        middle = (top+bottom)/2
        value = tvd_at_md(trajectory, [middle])[0]
        if value == tvd or middle in (top, bottom):
            return middle
        if value < tvd:
            top = middle
        else:
            bottom = middle
    return (top+bottom)/2


def analyze_static_security(trajectory, hydrostatic, formation):
    """One exact TVD-linear comparison path, independent of Formation input mode."""
    domain = formation["domain"]
    result = {"status": "safe", "domain": domain, "crossings": [], "frac_violations": [], "pore_violations": [],
              "plot_regions": {"frac": [], "pore": []}}
    if domain is None:
        return result
    if trajectory_tvd_decreases(trajectory, domain["bottom_md"]):
        raise ValueError("Static Well Security is unsupported: TVD decreases along the continuous trajectory.")
    seen = set()
    for part in domain["segments"]:
        mesh = sorted({part["top_md"], part["bottom_md"], *(md for md in hydrostatic["md_m"]+formation["md_m"]
                       if part["top_md"] < md < part["bottom_md"])})
        tvds = tvd_at_md(trajectory, mesh)
        for top, bottom, ta, tb in zip(mesh, mesh[1:], tvds, tvds[1:]):
            h = [_linear_pressure(hydrostatic["tvd_m"], hydrostatic["pressure_psi"], t) for t in (ta, tb)]
            limits = {boundary: [_linear_pressure(formation["tvd_m"], formation[boundary+"_psi"], t) for t in (ta, tb)]
                      for boundary in ("frac", "pore")}
            roots, cuts = {}, {0., 1.}
            for boundary, limit in limits.items():
                d0, d1 = h[0]-limit[0], h[1]-limit[1]
                contacts = [f for f, d in ((0., d0), (1., d1)) if d == 0]
                if (d0 < 0 < d1) or (d1 < 0 < d0):
                    roots[boundary] = -d0/(d1-d0)
                    cuts.add(roots[boundary]); contacts.append(roots[boundary])
                for f in contacts:
                    tvd = ta+(tb-ta)*f
                    md = top if f == 0 else bottom if f == 1 else _crossing_md(trajectory, top, bottom, tvd)
                    key = (boundary, md)
                    if key not in seen:
                        seen.add(key)
                        result["crossings"].append({"boundary": boundary, "md_m": md, "tvd_m": tvd,
                                                    "pressure_psi": h[0]+(h[1]-h[0])*f})
            ordered = sorted(cuts)
            for boundary, limit in limits.items():
                sign = 1 if boundary == "frac" else -1
                d0, d1 = sign*(h[0]-limit[0]), sign*(h[1]-limit[1])
                def delta(f):
                    if f == roots.get(boundary):
                        return 0.
                    return d0 if f == 0 else d1 if f == 1 else d0+(d1-d0)*f
                rows = result[boundary+"_violations"]
                for left, right in zip(ordered, ordered[1:]):
                    if delta((left+right)/2) <= 0:
                        continue
                    dl, dr = delta(left), delta(right)
                    maximum = left if dl >= dr else right
                    points = []
                    for fraction in (left, right, maximum):
                        t = ta+(tb-ta)*fraction
                        md = top if fraction == 0 else bottom if fraction == 1 else _crossing_md(trajectory, top, bottom, t)
                        points.append((md, t))
                    start, end, peak = points
                    row = {"kind": "over_frac" if boundary == "frac" else "under_pore",
                           "start_md_m": start[0], "start_tvd_m": start[1], "end_md_m": end[0], "end_tvd_m": end[1],
                           "max_delta_psi": delta(maximum), "max_at_md_m": peak[0], "max_at_tvd_m": peak[1],
                           "hydro_psi_at_max": h[0]+(h[1]-h[0])*maximum,
                           "limit_psi_at_max": limit[0]+(limit[1]-limit[0])*maximum}
                    # Retain this same classified cell's exact curve edges for
                    # passive rendering; no second interpolation/analysis path.
                    plot = {"tvd_m": [start[1], end[1]],
                            "hydro_psi": [h[0]+(h[1]-h[0])*f for f in (left, right)],
                            "limit_psi": [limit[0]+(limit[1]-limit[0])*f for f in (left, right)]}
                    if rows and rows[-1]["end_md_m"] == start[0] and dl > 0:
                        previous = rows[-1]
                        previous.update(end_md_m=end[0], end_tvd_m=end[1])
                        if row["max_delta_psi"] > previous["max_delta_psi"]:
                            previous.update({key: value for key, value in row.items() if key not in
                                             ("kind", "start_md_m", "start_tvd_m", "end_md_m", "end_tvd_m")})
                        for key, values in plot.items():
                            result["plot_regions"][boundary][-1][key].extend(values[1:])
                    else:
                        rows.append(row)
                        result["plot_regions"][boundary].append(plot)
    result["crossings"].sort(key=lambda row: (row["md_m"], row["boundary"]))
    if result["frac_violations"] or result["pore_violations"]:
        result["status"] = "warning"
    return result


def _ready_inputs(state):
    well = {**state.get("well_data", {}), **{k: state[k] for k in (PORE_FIELD, FRAC_FIELD) if k in state}}
    config = state.get("formation_pressure_config", {"mode": "basic", "profile": []})
    active_config = config
    if isinstance(config, dict) and config.get("mode") == "basic" and isinstance(config.get("profile"), list):
        active_config = {**config, "profile": []}  # Inactive drafts are not calculation authority.
    validate_formation_pressure_config(active_config)
    validate_chart_inputs(well if config["mode"] == "basic" else {}, state.get("placement_config", {}))
    if config["mode"] == "basic" and any(well.get(key) is None for key in (PORE_FIELD, FRAC_FIELD)):
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
    validate_chart_inputs(state if formation_source(state).get("mode") == "basic" else {}, config)
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
            "active_string": active, "enclosing_string": outer,
            "capacity_segments": capacities, "shoe_track_bbl": track}


def interval_volume(segments, top, bottom):
    return math.fsum(max(0.0, min(bottom, s["bottom_md"])-max(top, s["top_md"]))*s["bbl_per_m"]
                     for s in segments)


def _fluid(state, name):
    row = state.get("fluids_config", {}).get("params", {}).get(name,
                state.get("fluid_data", {}).get(name, {}))
    volume = _number(row.get("volume"), f"Phase IV {name} volume", positive=True)
    density = require_fluid_density(name, row.get("density"))
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
    for name in ("Scavenger", "Spacer Ahead", "Spacer", "Pre Flush", "Diesel"):
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
    formation = resolve_formation_profile(state, geometry, depths, tvds)
    hydrostatic = {"md_m": depths if hydro else [], "tvd_m": tvds if hydro else [], "pressure_psi": hydro}
    security = None if security_issues else analyze_static_security(state["well_geometry"], hydrostatic, formation)
    pressure = {key: formation[key] for key in ("kind", "md_m", "tvd_m", "pore_psi", "frac_psi")}
    return {**geometry, **final, "hydrostatic": {"md_m": depths if hydro else [], "tvd_m": tvds if hydro else [],
                                                "pressure_psi": hydro},
            "pore_frac": pressure, "formation_pressure": formation, "static_security": security,
            "static_security_issues": security_issues,
            "fluid_sequence_ready": True, "static_security_ready": not security_issues}


def chart_readiness(state, include_fluids=False):
    """One shared completion authority for Phase II/III, direct export and model builds."""
    result = {"issues": [], "warnings": [], "model": None}
    try:
        if chart_job_kind(state.get("job_type")) is None:
            return result
        well = _ready_inputs(state)
        geometry = resolve_chart_geometry(state)
        resolve_formation_profile(state, geometry)
        try:
            mud = require_positive_density(state.get("mud_density", state.get("well_data", {}).get("mud_density")))
            if formation_source(state)["mode"] == "basic" and not well[PORE_FIELD] <= mud <= well[FRAC_FIELD]:
                result["warnings"].append("Mud Weight is outside the Pore–Fracture window (warning only).")
        except ValueError:
            pass  # Existing Mud input validation remains its own authority.
        if include_fluids:
            result["model"] = build_chart_model(state, geometry)
            result["issues"] += result["model"]["static_security_issues"]
            security = result["model"]["static_security"]
            if security:
                for key, label in (("frac_violations", "Fracture window exceeded"), ("pore_violations", "Underbalance")):
                    if security[key]:
                        result["warnings"].append(f"Static Well Security: {label} in {len(security[key])} Current Open Hole interval(s).")
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        result["issues"].append(str(exc))
    return result
