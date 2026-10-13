"""Pure Centralizer product, geometry and displacement projections; no UI or solver execution."""
import json
import math
from collections.abc import Sequence
from copy import deepcopy
from numbers import Real
from pathlib import Path

import materials_db
import cement_chart_model
import well_profile
from centralizer_optimizer_engine import Gravity
from engineering_tools import parse_fractional_size, require_positive_density


# Exact international inch/pound definitions, also used by the existing
# cement_chart_model pressure conversion; gravity comes from the frozen engine.
INCH_TO_M = 0.0254
LBF_TO_N = 0.45359237 * Gravity
CATALOG_PATH = Path(__file__).with_name("ds_cent_products.json")


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number.")
    return float(value)


def _nr(product):
    nr = product.get("nr")
    if not isinstance(nr, int) or isinstance(nr, bool):
        raise ValueError("Official product nr must be an integer.")
    return nr


def official_product_kind(product):
    """Owner Rule R*: official force fields only, including missing/None/zero."""
    forces = [product.get(field) for field in ("restoring_force_lbf", "api_rf_lbf")]
    for field, force in zip(("restoring_force_lbf", "api_rf_lbf"), forces):
        if force is not None:
            _number(force, field)
    return "rigid" if all(force is None or force == 0 for force in forces) else "spring"


def to_engine_product(product):
    """New SI dictionary matching the frozen CentralizerProduct contract."""
    nr = _nr(product)
    kind = official_product_kind(product)
    if product.get("kind") != kind:
        raise ValueError(f"Official product nr {nr}: kind does not match Rule R*.")
    bows = product.get("bows")
    if not isinstance(bows, int) or isinstance(bows, bool):
        raise ValueError(f"Official product nr {nr}: bows must be an integer.")
    for field in ("manufacturer", "description"):
        if not isinstance(product.get(field), str):
            raise ValueError(f"Official product nr {nr}: {field} must be text.")
    return {
        "name": f"OFFICIAL-CENT-{nr}", "code": str(nr), "kind": kind, "bows": bows,
        "max_od": _number(product.get("max_od_in"), "max_od_in") * INCH_TO_M,
        "min_od": _number(product.get("min_od_in"), "min_od_in") * INCH_TO_M,
        "starting_force": _number(product.get("starting_force_lbf"), "starting_force_lbf") * LBF_TO_N,
        "running_force": _number(product.get("running_force_lbf"), "running_force_lbf") * LBF_TO_N,
        "restoring_force": _number(product.get("restoring_force_lbf") if product.get("restoring_force_lbf") is not None else 0.0,
                                    "restoring_force_lbf") * LBF_TO_N,
        "rated_hole": _number(product.get("hole_size_in"), "hole_size_in") * INCH_TO_M,
        "manufacturer": product["manufacturer"], "description": product["description"],
    }


def load_official_catalog(path=CATALOG_PATH):
    """Load the certified official catalog and validate count, identity and fields."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("products"), list):
        raise ValueError("Official catalog must contain a products list.")
    products = document["products"]
    if type(document.get("n_products")) is not int or document["n_products"] != len(products) or len(products) != 4692:
        raise ValueError("Official catalog product count must be 4692.")
    seen = set()
    for product in products:
        if not isinstance(product, dict):
            raise ValueError("Official catalog products must be objects.")
        nr = _nr(product)
        if nr in seen:
            raise ValueError(f"Duplicate official product nr {nr}.")
        seen.add(nr)
        to_engine_product(product)
    return products


def resolve_official_product(products, nr):
    """Resolve one stable nr; Identification is display metadata, never identity."""
    _nr({"nr": nr})
    matches = [product for product in products if product["nr"] == nr]
    if len(matches) != 1:
        raise ValueError(f"Official product nr {nr} is missing or ambiguous.")
    return matches[0]


def _positive_pipe_size(pipe_size_in):
    if isinstance(pipe_size_in, str) and pipe_size_in.replace('"', "").strip().startswith("-"):
        raise ValueError("Pipe size must be greater than zero.")
    size = parse_fractional_size(pipe_size_in) if isinstance(pipe_size_in, str) else pipe_size_in
    size = _number(size, "Pipe size")
    if size <= 0:
        raise ValueError("Pipe size must be greater than zero.")
    return size


def filter_official_products(products, pipe_size_in):
    """Return candidates in catalog order; no Hole Size rule or automatic choice."""
    size = _positive_pipe_size(pipe_size_in)
    return [product for product in products if product["pipe_size_in"] == size]


def centralizer_applicable(job_type):
    """Exact current supported jobs only; no guessed future-job applicability."""
    return job_type in materials_db.JOB_TYPES and job_type not in ("CMT PLUG", "CMT SQUEEZE")


def to_engine_geometry(state):
    """Project canonical geometry/survey to v1.2.9, or None for an N/A job.

    The frozen engine supports one uniform active string and one scalar
    diameter on each side of the previous shoe. Reject richer geometry;
    never approximate it or calculate a replacement trajectory.
    """
    job = state.get("job_type")
    kind = cement_chart_model.chart_job_kind(job)  # Reject unknown/future jobs.
    if not centralizer_applicable(job):
        return None
    geometry = cement_chart_model.resolve_chart_geometry(state)
    shoe = geometry["shoe_md"]
    trajectory = state.get("well_geometry", {})
    # Reuse the trajectory completion/bounds authority; its TVD is not output.
    well_profile.tvd_at_md(trajectory, [shoe])
    if trajectory["type"] == "Vertical":
        survey = {"md": [0.0, float(trajectory["td_m"])],
                  "inc_deg": [0.0, 0.0], "azi_deg": [0.0, 0.0]}
    else:
        frame = trajectory["survey"]
        survey = {output: frame[column].tolist() for output, column in
                  zip(("md", "inc_deg", "azi_deg"), well_profile.SURVEY_COLUMNS)}

    description = {"casing": "Casing", "liner": "Liner", "tieback": "Tie Back"}[kind]
    active = [s for s in geometry["active_string"] if s["description"] == description]
    rows = [r for r in state["hardware_table"].to_dict("records") if r["Description"] == description]
    # resolve_chart_geometry preserves source row order and clips a prefix at
    # the shoe. Pair that prefix with its source Weight/Joint fields only.
    properties = []
    for segment, row in zip(active, rows):
        _positive_pipe_size(row.get("Size (in)"))
        values = (segment["od_in"], segment["id_in"],
                  _number(row.get("Weight (ppf)"), "Active string Weight (ppf)"),
                  _number(row.get("Joint (m)"), "Active string Joint (m)"))
        if any(value <= 0 for value in values) or values[1] >= values[0]:
            raise ValueError("Active string requires OD > ID > 0, Weight > 0 and Joint Length > 0.")
        properties.append(values)
    if not properties or len(properties) != len(active):
        raise ValueError("Active Centralizer string Hardware is unresolved.")
    if any(values != properties[0] for values in properties[1:]):
        raise ValueError("Tapered Centralizer string unsupported: OD, ID, Weight and Joint Length must be uniform.")
    od, inner, weight, joint = properties[0]
    casing = {"od": od * INCH_TO_M, "id": inner * INCH_TO_M,
              "weight_kg_m": weight * 0.45359237 / 0.3048, "joint_length": joint}
    for field, value in casing.items():
        if _number(value, f"casing.{field}") <= 0:
            raise ValueError(f"casing.{field} must be greater than zero after SI conversion.")

    outer = geometry["enclosing_string"]
    cased = [s for s in outer if s["description"] != "Open Hole Size"]
    holes = [s for s in outer if s["description"] == "Open Hole Size"]
    if not cased or len({s["id_in"] for s in cased}) != 1:
        raise ValueError("Centralizer enclosing cased geometry requires one identical scalar ID.")
    previous_id = cased[0]["id_in"]
    if kind == "tieback":
        previous_shoe, hole = shoe, previous_id
    else:
        if outer != cased + holes or not holes or len({s["od_in"] for s in holes}) != 1:
            raise ValueError("Centralizer requires one cased to open-hole transition and one scalar open-hole diameter.")
        previous_shoe, hole = cased[-1]["bottom_md"], holes[0]["od_in"]

    return {
        "job_type": kind, "survey": survey,
        "casing": casing,
        "wellbore": {"prev_casing_id": previous_id * INCH_TO_M, "hole_size": hole * INCH_TO_M,
                     "prev_shoe_depth": previous_shoe, "open_hole_top": previous_shoe,
                     "open_hole_bottom": shoe, "string_top": active[0]["top_md"], "string_shoe": shoe},
    }


def _fluid_columns_override(override, shoe):
    fields = {"inside_fluids", "annulus_fluids"}
    if not isinstance(override, dict) or set(override) != fields:
        raise ValueError("Tier-2 requires both inside_fluids and annulus_fluids only.")
    for field, table in override.items():
        if not isinstance(table, Sequence) or isinstance(table, (str, bytes)):
            raise ValueError(f"{field} must be a sequence of [top_md, density] pairs.")
        seen = set()
        for pair in table:
            if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
                raise ValueError(f"{field} needs exact [top_md, density] pairs.")
            top, rho = (_number(value, field) for value in pair)
            if not 0 <= top <= shoe or rho <= 0 or top in seen:
                raise ValueError(f"{field}: depths must be unique and within 0–Shoe; density must be positive.")
            seen.add(top)
    return deepcopy(override)


def _displacement_path(geometry):
    """Volume coordinates along inside-down, then annulus-up; no capacity formula here."""
    inside = [{**s, "bbl_per_m": cement_chart_model._capacity(s["id_in"])}
              for s in geometry["active_string"]]
    columns = {"inside": inside, "annulus": geometry["capacity_segments"]}
    capacities = {name: cement_chart_model.interval_volume(rows, 0., geometry["shoe_md"])
                  for name, rows in columns.items()}
    path, volumes = [], []
    for column, rows in columns.items():
        for row in rows if column == "inside" else reversed(rows):
            volume = _number(cement_chart_model.interval_volume([row], row["top_md"], row["bottom_md"]),
                             "Displacement segment capacity")
            if volume <= 0:
                raise ValueError("Displacement segment capacity must be positive.")
            # ponytail: Hardware paths are small; full-prefix fsum avoids cumulative
            # drift at interfaces. A large-path implementation can use compensated sums.
            start = math.fsum(volumes)
            volumes.append(volume)
            end = _number(math.fsum(volumes), "Displacement path capacity")
            if end <= start:
                raise ValueError("Displacement capacity cannot be resolved at floating-point precision.")
            path.append({**row, "column": column, "start_bbl": start, "end_bbl": end})
    capacities["total"] = math.fsum(volumes)
    return path, capacities


def build_fluid_snapshot(state, *, override=None):
    """Transient Round-9 plug flow; never calls Round-8 final placement or a solver.

    Tier-2 forwards explicit columns unchanged and has no named/volume diagnostics.
    Tier-1 occupies one cumulative-volume path, newest fluid first. Geometry
    boundaries partition capacity, but do not create fluid interfaces.
    """
    engine_geometry = to_engine_geometry(state)
    if engine_geometry is None:
        return None
    shoe = engine_geometry["wellbore"]["string_shoe"]
    mud = require_positive_density(state.get("mud_density") or state.get("well_data", {}).get("mud_density"))
    mud_rho = _number(mud * cement_chart_model.PCF_TO_KG_M3, "Mud density kg/m³")
    result = {"fluids": {"mud_density": mud_rho}, "diagnostics_available": False,
              **dict.fromkeys(("inside_intervals", "annulus_intervals", "per_fluid", "capacity_bbl",
                               "totals", "original_mud", "overflow_kind"))}
    if override is not None:
        result["fluids"].update(_fluid_columns_override(override, shoe))
        return result

    config = state.get("fluids_config", {})
    if not isinstance(config, dict):
        raise ValueError("Phase IV fluid inputs must be a canonical record.")
    active, params = config.get("active", []), config.get("params", {})
    old = state.get("fluid_data", {})
    order = ("Displacement Fluid", "Tail", "Lead #2", "Lead #1", "Lead", "Main",
             "Scavenger", "Spacer", "Spacer Ahead", "Pre Flush")
    if (not isinstance(active, list) or any(not isinstance(name, str) for name in active)
            or len(set(active)) != len(active) or any(name not in (*order, "Spacer Behind") for name in active)):
        raise ValueError("Phase IV active fluids are missing, duplicate or unsupported.")
    if not isinstance(params, dict) or not isinstance(old, dict):
        raise ValueError("Phase IV fluid sources must be canonical records.")
    stages = []
    for name in order:
        if name not in active:
            continue
        source = params.get(name, old.get(name, {}))
        if not isinstance(source, dict):
            raise ValueError(f"Phase IV {name}: review the fluid inputs.")
        if name == "Displacement Fluid":
            volume = cement_chart_model._number(source.get("volume"), f"Phase IV {name} volume", positive=True)
            density = mud
        else:
            volume, density = cement_chart_model._fluid(state, name)
        _number(density * cement_chart_model.PCF_TO_KG_M3, f"{name} density kg/m³")
        stages.append((name, volume, density))
    try:
        path, capacities = _displacement_path(cement_chart_model.resolve_chart_geometry(state))
        entered = _number(math.fsum(v for _, v, _ in stages), "Total entered volume")
    except OverflowError as exc:
        raise ValueError("Displacement volumes/capacities exceed finite arithmetic.") from exc
    columns, per_fluid, cumulative = {"inside": [], "annulus": []}, {}, []
    for name, volume, density in [*stages, ("Mud", max(0., capacities["total"] - entered), mud)]:
        start = math.fsum(cumulative)
        cumulative.append(volume)
        end = capacities["total"] if name == "Mud" else min(math.fsum(cumulative), capacities["total"])
        contributions = []
        for segment in path:
            left, right = max(start, segment["start_bbl"]), min(end, segment["end_bbl"])
            if right <= left:
                continue
            down = segment["column"] == "inside"
            inlet = segment["top_md"] if down else segment["bottom_md"]
            outlet = segment["bottom_md"] if down else segment["top_md"]
            def depth(at):
                if at == segment["start_bbl"]:
                    return inlet
                if at == segment["end_bbl"]:
                    return outlet
                return inlet + (1 if down else -1) * (at - segment["start_bbl"]) / segment["bbl_per_m"]
            top, bottom = sorted((depth(left), depth(right)))
            if not top < bottom:
                raise ValueError("Fluid volume cannot be resolved at floating-point depth precision.")
            contribution = right - left
            contributions.append(contribution)
            columns[segment["column"]].append({"fluid": name, "top_md": top, "bottom_md": bottom,
                "density_pcf": density, "in_path_bbl": contribution})
        if name != "Mud":
            in_path = min(volume, max(0., capacities["total"] - start))
            # Global volume-coordinate subtraction can lose a few ULPs for a
            # small stage after a large one; this is arithmetic noise, not a bbl tolerance.
            if (in_path > 0 and not contributions or not math.isclose(math.fsum(contributions), in_path,
                    rel_tol=1e-12, abs_tol=4 * math.ulp(capacities["total"]))):
                raise ValueError(f"{name}: displacement volume conservation failed at floating-point precision.")
            per_fluid[name] = {"entered_bbl": volume, "in_path_bbl": in_path, "returned_bbl": volume - in_path}
    for column, parts in columns.items():
        rows = []
        for part in sorted(parts, key=lambda p: p["top_md"]):
            if rows and rows[-1]["fluid"] == part["fluid"] and rows[-1]["bottom_md"] == part["top_md"]:
                rows[-1]["bottom_md"] = part["bottom_md"]
                rows[-1]["in_path_bbl"] = math.fsum((rows[-1]["in_path_bbl"], part["in_path_bbl"]))
            else:
                rows.append(dict(part))
        if (not rows or rows[0]["top_md"] != 0. or rows[-1]["bottom_md"] != shoe
                or any(a["bottom_md"] != b["top_md"] for a, b in zip(rows, rows[1:]))):
            raise ValueError("Displacement column has an unexplained gap or overlap.")
        result[f"{column}_intervals"] = rows
        result["fluids"][f"{column}_fluids"] = [[p["top_md"], p["density_pcf"] * cement_chart_model.PCF_TO_KG_M3] for p in rows]
    in_path = math.fsum(row["in_path_bbl"] for row in per_fluid.values())
    returned = math.fsum(row["returned_bbl"] for row in per_fluid.values())
    result.update(diagnostics_available=True, per_fluid=per_fluid, capacity_bbl=capacities,
        totals={"entered_bbl": entered, "in_path_bbl": in_path, "returned_bbl": returned},
        original_mud={"initial_bbl": capacities["total"], "in_path_bbl": max(0., capacities["total"] - entered),
                      "displaced_bbl": min(entered, capacities["total"])},
        overflow_kind="surface_dump" if engine_geometry["job_type"] == "casing" else "overlap_excess")
    return result
