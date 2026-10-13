"""Official Centralizer catalog/product adapter only; no UI or calculations."""
import json
import math
from numbers import Real
from pathlib import Path

import materials_db
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


def filter_official_products(products, pipe_size_in):
    """Return candidates in catalog order; no Hole Size rule or automatic choice."""
    if isinstance(pipe_size_in, str) and pipe_size_in.replace('"', "").strip().startswith("-"):
        raise ValueError("Pipe size must be greater than zero.")
    size = parse_fractional_size(pipe_size_in) if isinstance(pipe_size_in, str) else pipe_size_in
    size = _number(size, "Pipe size")
    if size <= 0:
        raise ValueError("Pipe size must be greater than zero.")
    return [product for product in products if product["pipe_size_in"] == size]


def centralizer_applicable(job_type):
    """Exact current supported jobs only; no guessed future-job applicability."""
    return job_type in materials_db.JOB_TYPES and job_type not in ("CMT PLUG", "CMT SQUEEZE")
