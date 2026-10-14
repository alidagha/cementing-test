"""Pure current-project boundary for the byte-frozen v1.4.2 pumping engine."""
from copy import deepcopy
import math

import pandas as pd

import cement_chart_model as chart_model
import fluids_charts_module_v1_4_2 as fcm
import materials_db
from engineering_tools import parse_effective_numeric
from placement import HOST_DESCRIPTIONS, hardware_choices, measured_depth, target_depth, target_descriptions
from project_state import refresh_fluids
import rheology


def _record(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a canonical record.")
    return value


def _mud_rheology(state):
    message = "Phase II Mud rheology: Pumping Simulation requires finite PV > 0 cP and YP > 0 lbf/100ft²."
    try:
        well = _record(state.get("well_data", {}), "Phase II Well Data")
        values = [state.get(field, well.get(field)) for field in ("plastic_viscosity", "yield_point")]
        if any(isinstance(value, bool) for value in values):
            raise ValueError(message)
        pv, yp = (parse_effective_numeric(value, default=None) for value in values)
        if any(value is None or not math.isfinite(value) or value <= 0 for value in (pv, yp)):
            raise ValueError(message)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    return pv, yp


def _tieback_paths(rows, table, config, resolved):
    """Selected-host annulus plus the certified old-liner continuation; no host inference."""
    tie_in = resolved["shoe_md"]
    candidates = []
    for row in rows:
        if row.get("Description") not in ("Previous Liner", "Liner"):
            continue
        top, bottom = fcm.parse_md_interval(row.get("MD (m)"))
        if top is not None and bottom is not None and top <= tie_in < bottom:
            candidates.append((top, bottom, row))
    if not candidates:
        raise ValueError("Tie Back Pumping Simulation requires an explicit old-liner interval containing the tie-in and continuing to its shoe.")
    # Same deepest-top connection criterion as frozen D11b; equal-ranked
    # candidates are unresolved, rather than silently choosing list order.
    deepest = max(top for top, _, _ in candidates)
    connection = [entry for entry in candidates if entry[0] == deepest]
    if len(connection) != 1:
        raise ValueError("Tie Back Pumping Simulation old-liner continuation is ambiguous.")
    top, shoe, row = connection[0]
    old_liner = chart_model._segments([row], top, shoe, "Pumping Simulation old liner")[0]
    active = [*resolved["active_string"], {**old_liner, "top_md": tie_in}]
    host = hardware_choices(table, HOST_DESCRIPTIONS)[config["host_row"]]
    host_rows = [r for r in rows if r.get("Description") == host["description"]]
    host_end = measured_depth(host_rows[-1].get("MD (m)"))
    outer = chart_model._segments(host_rows, 0., min(host_end, shoe), "Pumping Simulation selected host")
    if host_end < shoe:
        outer += chart_model._segments([r for r in rows if r.get("Description") == "Open Hole Size"],
                                      host_end, shoe, "Pumping Simulation Open Hole Size")
    return active, outer, shoe


def _geometry(state, kind):
    table = state.get("hardware_table")
    config = _record(state.get("placement_config", {}), "placement_config")
    job = state.get("job_type")
    if not isinstance(table, pd.DataFrame) or config.get("job_type") != job:
        raise ValueError("Pumping Simulation requires current Hardware and placement target selection.")
    rows = table.to_dict("records")
    selected = [i for i, row in enumerate(rows) if config.get("target_row") in
                hardware_choices(pd.DataFrame([row]), target_descriptions(job))]
    if len(selected) != 1 or target_depth(table, job, config) is None:
        raise ValueError("Pumping Simulation requires one explicitly selected Hardware target row; do not guess a string from manual depth.")
    resolved = chart_model.resolve_chart_geometry(state)
    active, outer = resolved["active_string"], resolved["enclosing_string"]
    flow_shoe = resolved["shoe_md"]
    intervals = [(s["top_md"], s["bottom_md"]) for s in resolved["capacity_segments"]]
    if kind == "tieback":
        active, outer, flow_shoe = _tieback_paths(rows, table, config, resolved)
        bounds = sorted({s[key] for s in active+outer for key in ("top_md", "bottom_md")})
        intervals = list(zip(bounds, bounds[1:]))
    pipes = [fcm.PipeSection(s["top_md"], s["bottom_md"], s["id_in"], s["od_in"])
             for s in active]
    annulus = []
    for top, bottom in intervals:
        inside = chart_model._at(active, (top+bottom)/2)
        outside = chart_model._at(outer, (top+bottom)/2)
        diameter = outside["od_in"] if outside["description"] == "Open Hole Size" else outside["id_in"]
        if kind == "tieback" and annulus and (annulus[-1].do_in, annulus[-1].di_in) == (diameter, inside["od_in"]):
            annulus[-1].z_bot = bottom
        else:
            annulus.append(fcm.AnnSection(top, bottom, diameter, inside["od_in"]))
    return fcm.GeometrySpec(td_m=flow_shoe, track_depth_m=resolved["shoe_md"],
        hole_id_in=annulus[-1].do_in, pipe_od_in=pipes[-1].od_in, pipe_id_in=pipes[-1].id_in,
        ann_sections=annulus, pipe_sections=pipes), []


def prepare_pumping_simulation(state):
    """Validate/rebuild consumed inputs only; no simulation or project writes.

    Nominal Hardware dimensions feed the frozen GeometrySpec. Round-8 adjusted
    capacities/final-static placement are neither reused as simulation physics
    nor altered. Report-only placement overrides never enter this projection.
    """
    kind = chart_model.chart_job_kind(state.get("job_type"))
    if kind is None:
        return {"applicable": False, "message": "Not applicable (Plug/Squeeze).", "inputs": None, "warnings": []}
    mud = _mud_rheology(state)
    geometry, warnings = _geometry(state, kind)
    projected = deepcopy({key: state[key] for key in ("fluids_config", "fluid_data", "mud_density", "well_data") if key in state})
    refresh_fluids(projected)
    fluid_data = projected["fluid_data"]
    lab_results = {}
    for name in fluid_data:
        if name in materials_db.RHEOLOGY_LAB_FLUIDS:
            try:
                lab = _record(state.get("lab_qc_params", {}), "Phase VII Lab")
                qc = _record(lab.get(name, {}), f"Phase VII {name}")
                data = _record(qc.get("rheology", {}), f"Phase VII {name} rheology")
                source = data.get("bhct_down", {})
                result, issues = rheology.build_rheology({"rheology": {"bhct_down": source}})
                if issues or not result["bhct_down"]["selected"] or not result["bhct_down"]["is_valid_bingham"]:
                    raise ValueError("; ".join(issues) or "Select a valid Bingham dataset.")
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Phase VII {name}: Pumping Simulation requires valid bhct_down Bingham rheology. {exc}") from None
            lab_results[name] = result
        elif name in fcm.SPACER_TYPES:
            try:
                config = _record(state.get("centralizer_config", {}), "Phase IX inputs")
                auxiliaries = _record(config.get("aux_rheology", {}), "Phase IX auxiliary rheology")
                source = auxiliaries.get(name)
                if not isinstance(source, dict) or set(source) != {str(rpm) for rpm in rheology.RPM_ORDER}:
                    raise ValueError("Complete exactly all seven RPM readings.")
                points = [(rpm, rheology._numeric(source[str(rpm)])) for rpm in rheology.RPM_ORDER]
                if any(value is None or value <= 0 for _, value in points):
                    raise ValueError("All seven readings must be finite and positive.")
                fit = rheology.calculate_cemcade_bingham(points)
                if fit["is_valid_bingham"] is not True:
                    raise ValueError(fit["validation_message"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Phase IX {name}: Pumping Simulation requires complete valid seven-RPM auxiliary rheology. {exc}") from None
            fluid_data[name].update(pv_cp=fit["pv_cp"], yp_lbf100ft2=fit["ty_lbf_100ft2"])
    fitted = fcm.rheology_from_lab(lab_results)
    explicit = {"Scavenger": fitted["Scavenger"]} if "Scavenger" in fitted else {}
    slurries = {name: fitted[name] for name in fcm.SLURRY_TYPES if name in fitted}
    stages, stage_warnings = fcm.stages_from_fluid_data(fluid_data)
    _, rheology_warnings, frictionless = fcm._build_fluids(stages,
        fluid_data["Displacement Fluid"]["effective_density"],
        mud_pv_yp=mud, slurry_rheology=slurries, rheology=explicit)
    if frictionless or rheology_warnings:
        raise ValueError("Pumping Simulation requires complete rheology; hydrostatic-only fallback is not permitted.")
    well = state.get("well_data", {})
    bhsp = state.get("bhsp", well.get("bhsp"))
    fcm.parse_bhsp_psi(bhsp)
    return {"applicable": True, "inputs": dict(fluid_data=fluid_data, geometry=geometry,
        mud_pv_yp=mud, slurry_rheology=slurries, rheology=explicit, bhsp=bhsp, options=fcm.ChartOptions()),
        "warnings": [*warnings, *stage_warnings]}


def run_pumping_simulation(state):
    """Execute once from freshly prepared inputs; caller owns the returned figure."""
    prepared = prepare_pumping_simulation(state)
    if not prepared["applicable"]:
        return {**prepared, "figure": None, "result": None}
    figure, result, warnings = fcm.build_three_charts(**prepared["inputs"])
    return {"applicable": True, "figure": figure, "result": result,
            "warnings": [*prepared["warnings"], *warnings]}
