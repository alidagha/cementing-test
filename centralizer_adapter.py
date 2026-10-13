"""Pure Centralizer product/geometry projections; no UI or solver execution."""
import json
import math
from numbers import Real
from pathlib import Path

import materials_db
import cement_chart_model
import well_profile
from centralizer_optimizer_engine import Gravity
from engineering_tools import parse_fractional_size


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
