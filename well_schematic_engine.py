#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
well_schematic_engine.py — Explicit-Authority CemCADE Well Schematic Engine (v3.2.1)
===========================================================================================
Standalone graphic engine reproducing the exact visual DNA of CemCADE printouts:
- Centered Column-3 typography with operation-neutral labels (no automatic highlight bands).
- Authentic rig banner with a clean mast silhouette, rose BOP stack, green pipe rack,
  yellow doghouse/tanks, balanced surface equipment, and realistic mud-system piping.
- Upward-sloping flush casing shoe triangles; seamless Tie-Back-to-Liner junctions
  with top & bottom hanger collars and zero false shoe flares.
- Single-polygon stepped (T-shaped) cement plugs when straddling a liner lap or shoe.
- Point-based squeeze cement patches behind the explicitly selected tubular or open-hole target.
- Explicit current-job depth authority with a 3-point ruler: 0, Final Axis/2, Final Axis.
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import math
import os
import re
import struct
import sys
import warnings
import zlib
from fractions import Fraction
from typing import Dict, List, Optional, Tuple, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Rectangle
from matplotlib.lines import Line2D
from PIL import Image

__version__ = "3.2.1"

# ----------------------------------------------------------------------------------------
# Authentic CemCADE Visual Constants
# ----------------------------------------------------------------------------------------
C_HEADER_BLUE = "#003D83"       # CemCADE header banner blue
C_TUBULAR_FILL = "#D6D6D6"      # Authentic hollow pipe-wall gray
C_TUBULAR_EDGE = "#000000"      # Sharp black pipe wall outline
C_COLLAR_FILL = "#8C8C8C"       # Liner hanger / lap collar gray
C_PLUG_FILL = "#7F7F7F"         # Cement plug solid mid-gray
C_SQUEEZE_CEM = "#9E9E9E"       # Squeezed cement behind casing perforations
C_HATCH = "#7A7A7A"             # Authentic diagonal open-hole formation hatching
C_GREEN_ARROW = "#1E9E46"       # CemCADE operational green arrow
C_GREEN_HIGHLIGHT = "#00A848"   # Full-width green highlight bar in Column 3
C_ROSE_BOP = "#D878A8"          # Pink/rose BOP stack under rotary
C_ORANGE_SHEAVE = "#E88850"     # Traveling block / crown sheaves
C_TANK_YELLOW = "#DCE664"       # Yellow-green mud tank & doghouse roofs
C_PIPE_RACK_GREEN = "#40A040"   # Stacked drill-pipe ends on left rack
C_DASH_GRAY = "#707070"

FONT_FAMILY = "DejaVu Sans"

COLUMN_FRACTIONS = (0.155, 0.495, 0.350)   # Depth(m) | Well Schematic | Casing Size/Depth(m)
FIG_SIZE_IN = (6.0, 7.6)
RIG_BAND_FRACTION = 0.280
LABEL_PT = 9.2
MIN_LABEL_PT = 7.6
LABEL_FIT_TOL_PX = 2.0  # raster measurement tolerance; prevents false 1–2 px overflow failures
DEPTH_LABEL_PT = 9.5
HEADER_PT = 9.2

_LABEL_MIN_GAP_FACTOR = 1.45
_LABEL_EDGE_PAD_FACTOR = 0.40
_DEPTH_TOL = 1e-6   # m: numeric equality tolerance only; geometry is never repaired within a 1 m band


# =========================================================================================
# 1. API FRACTIONAL PARSER & FORMATTER
# =========================================================================================
def parse_api_size(val: Union[int, float, str]) -> float:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        f = float(val)
        if not math.isfinite(f) or f <= 0:
            raise ValueError(f"size_in must be > 0, got {val!r}")
        return f
    if not isinstance(val, str):
        raise ValueError(f"cannot parse size {val!r}")
    s = val.strip()
    if s.startswith("-"):
        raise ValueError(f"size_in must be > 0, got {val!r}")
    s = s.replace('"', "").replace("in", "").replace("-", " ").strip()
    parts = s.split()
    try:
        if len(parts) == 1:
            f = float(parts[0].split("/")[0]) / float(parts[0].split("/")[1]) if "/" in parts[0] else float(parts[0])
        elif len(parts) == 2 and "/" in parts[1]:
            num, den = parts[1].split("/")
            f = float(parts[0]) + float(num) / float(den)
        else:
            f = float(s)
    except Exception as exc:
        raise ValueError(f"invalid API size string {val!r}") from exc
    if not math.isfinite(f) or f <= 0:
        raise ValueError(f"size_in must be > 0, got {val!r}")
    return f


def format_api_size(size_in: Union[int, float, str]) -> str:
    val = parse_api_size(size_in)
    whole = int(math.floor(val + 1e-6))
    rem = val - whole
    if rem < 1e-4:
        return f'{whole}"'
    frac = Fraction(rem).limit_denominator(16)
    if frac.numerator == frac.denominator:
        return f'{whole + 1}"'
    if whole == 0:
        return f'{frac.numerator}/{frac.denominator}"'
    return f'{whole} {frac.numerator}/{frac.denominator}"'


def _fmt_depth(d: float) -> str:
    """Human-readable metres: keep one decimal only when it is materially present."""
    return f"{float(d):.1f}".rstrip("0").rstrip(".")


# =========================================================================================
# 2. CURRENT-OPERATION DEPTH RULER (0, Middle, Bottom)
# =========================================================================================
def calculate_dynamic_depth_axis(max_depth: float, show_mid: bool = True) -> Tuple[float, List[float]]:
    """Contract axis: Final Axis is exactly Final Relevant Job Depth + 200 m.

    The legacy function name is retained as a public entry point, but percentage margins and
    clean-interval rounding are intentionally removed. ``max_depth`` is the already-resolved
    Final Relevant Job Depth, never an inferred deepest string.
    """
    if not isinstance(max_depth, (int, float)) or isinstance(max_depth, bool) \
            or not math.isfinite(max_depth) or max_depth <= 0:
        raise ValueError("max_depth must be a finite positive number (metres).")
    y_max = float(max_depth) + 200.0
    return (y_max, [0.0, y_max / 2.0, y_max]) if show_mid else (y_max, [0.0, y_max])


# =========================================================================================
# 3. VALIDATION & DEPTH RESOLUTION
# =========================================================================================
def _num(v, ctx: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{ctx}: expected finite number, got {v!r}")
    return float(v)


def _index(value, ctx: str, length: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{ctx}: expected integer index, got {value!r}")
    if value < 0 or value >= length:
        raise ValueError(f"{ctx}: index {value} is outside 0..{length - 1}")
    return value


def validate_schematic_data(data: dict) -> dict:
    """Validate the renderer payload without inventing or repairing well geometry.

    Explicit authority fields used by this standalone renderer:
      * current_job = {type, target_index}
      * liner/tieback strings: host_index
      * tieback strings: landing_liner_index (the receiving liner at the tie-in,
        independent of the geometric host; sizes and Lap depths need not match)
      * open holes below surface: host_index
      * squeezes: depth_m, one target_index/open_hole_index or an operation-only wall_diameter_in;
        target_kind = lap|shoe|point (operation-only walls use point)
      * plug_bores: explicit operation-only top_md/bottom_md/diameter_in, not structural strings

    The future Cementing-App adapter is expected to populate these fields from canonical state.
    """
    if not isinstance(data, dict):
        raise ValueError("payload root must be a JSON object")
    casings = data.get("casings", [])
    if not isinstance(casings, list) or not casings:
        raise ValueError("'casings' must be a non-empty list")

    for i, c in enumerate(casings):
        ctx = f"casings[{i}]"
        if not isinstance(c, dict):
            raise ValueError(f"{ctx}: must be an object")
        if "size_in" not in c or "shoe_md" not in c:
            raise ValueError(f"{ctx}: requires 'size_in' and 'shoe_md'")
        c["size_in"] = parse_api_size(c["size_in"])
        if c.get("id_in") is not None:
            c["id_in"] = parse_api_size(c["id_in"])
            if c["id_in"] >= c["size_in"]:
                raise ValueError(f"{ctx}: id_in ({c['id_in']}) must be < size_in ({c['size_in']})")
        top = _num(c.get("top_md", 0.0), f"{ctx}.top_md")
        shoe = _num(c["shoe_md"], f"{ctx}.shoe_md")
        c["top_md"] = top
        c["shoe_md"] = shoe
        if top < 0:
            raise ValueError(f"{ctx}.top_md must be >= 0")
        if shoe <= 0:
            raise ValueError(f"{ctx}.shoe_md must be > 0")
        if shoe <= top:
            raise ValueError(f"{ctx}: shoe_md ({shoe}) must be > top_md ({top})")
        stype = str(c.get("type", "")).lower()
        if stype not in ("casing", "liner", "tieback"):
            raise ValueError(f"{ctx}.type must be explicitly 'casing', 'liner' or 'tieback'")
        c["type"] = stype

    # Explicit host/landing authority: never select the nearest/deepest string.
    for i, c in enumerate(casings):
        ctx = f"casings[{i}]"
        if c["type"] in ("liner", "tieback"):
            hi = _index(c.get("host_index"), f"{ctx}.host_index", len(casings))
            if hi == i:
                raise ValueError(f"{ctx}.host_index cannot reference itself")
            host = casings[hi]
            if host["type"] not in ("casing", "liner"):
                raise ValueError(f"{ctx}: explicit host must be CSG or LNR, not TB LNR")
            if float(host["size_in"]) <= float(c["size_in"]):
                raise ValueError(f"{ctx}: explicit host must have a larger OD")
            if not (float(host["top_md"]) <= float(c["top_md"]) <= float(host["shoe_md"])):
                raise ValueError(f"{ctx}: explicit host does not cover the string top")
            c["host_index"] = hi
        if c["type"] == "tieback":
            li = _index(c.get("landing_liner_index"), f"{ctx}.landing_liner_index", len(casings))
            liner = casings[li]
            if liner.get("type") != "liner":
                raise ValueError(f"{ctx}.landing_liner_index must reference a liner")
            if not (float(liner["top_md"]) - _DEPTH_TOL <= float(c["shoe_md"]) <=
                    float(liner["shoe_md"]) + _DEPTH_TOL):
                raise ValueError(f"{ctx}: tie-back tie-in must lie inside the explicit receiving liner interval")
            c["landing_liner_index"] = li

    for key in ("open_holes", "cement_plugs", "squeezes", "annotations", "plug_bores"):
        v = data.get(key)
        if v is None:
            data[key] = []
        elif not isinstance(v, list) or not all(isinstance(e, dict) for e in v):
            raise ValueError(f"'{key}' must be a list of objects")

    if data["annotations"]:
        raise ValueError("operational arrows/annotations are disabled by the locked schematic contract")

    for i, oh in enumerate(data["open_holes"]):
        ctx = f"open_holes[{i}]"
        top = _num(oh.get("top_md"), f"{ctx}.top_md")
        bot = _num(oh.get("bottom_md"), f"{ctx}.bottom_md")
        if top < 0:
            raise ValueError(f"{ctx}.top_md must be >= 0")
        if bot <= 0:
            raise ValueError(f"{ctx}.bottom_md must be > 0")
        if bot <= top:
            raise ValueError(f"{ctx}: bottom_md ({bot}) must be > top_md ({top})")
        if "hole_size_in" not in oh:
            raise ValueError(f"{ctx}.hole_size_in is required; no default hole size is inferred")
        oh["top_md"], oh["bottom_md"] = top, bot
        oh["hole_size_in"] = parse_api_size(oh["hole_size_in"])
        if top > _DEPTH_TOL:
            hi = _index(oh.get("host_index"), f"{ctx}.host_index", len(casings))
            host = casings[hi]
            if host["type"] not in ("casing", "liner"):
                raise ValueError(f"{ctx}: open-hole host must be CSG or LNR")
            if abs(float(host["shoe_md"]) - top) > _DEPTH_TOL:
                raise ValueError(f"{ctx}: open-hole top must match the explicit host shoe")
            oh["host_index"] = hi
        elif oh.get("host_index") is not None:
            oh["host_index"] = _index(oh["host_index"], f"{ctx}.host_index", len(casings))
        # 'active' is tolerated only as inert legacy metadata; it never controls rendering.
        if "active" in oh and not isinstance(oh["active"], bool):
            raise ValueError(f"{ctx}.active must be true or false when supplied")

    for i, p in enumerate(data["cement_plugs"]):
        ctx = f"cement_plugs[{i}]"
        top = _num(p.get("top_md"), f"{ctx}.top_md")
        bot = _num(p.get("bottom_md"), f"{ctx}.bottom_md")
        if top < 0:
            raise ValueError(f"{ctx}.top_md must be >= 0")
        if bot <= 0:
            raise ValueError(f"{ctx}.bottom_md must be > 0")
        if bot <= top:
            raise ValueError(f"{ctx}: bottom_md ({bot}) must be > top_md ({top})")
        p["top_md"], p["bottom_md"] = top, bot

    # Explicit operation-only widths never create a casing or an Open Hole.
    for i, bore in enumerate(data["plug_bores"]):
        ctx = f"plug_bores[{i}]"
        top, bottom = _num(bore.get("top_md"), ctx), _num(bore.get("bottom_md"), ctx)
        diameter = _num(bore.get("diameter_in"), f"{ctx}.diameter_in")
        if top < 0 or bottom <= top or diameter <= 0:
            raise ValueError(f"{ctx}: require nonnegative Top, Bottom > Top and diameter > 0")
        bore.update(top_md=top, bottom_md=bottom, diameter_in=diameter)

    for i, sq in enumerate(data["squeezes"]):
        ctx = f"squeezes[{i}]"
        depth = _num(sq.get("depth_m"), f"{ctx}.depth_m")
        if depth < 0:
            raise ValueError(f"{ctx}.depth_m must be >= 0")
        tubular_supplied = sq.get("target_index") is not None
        open_hole_supplied = sq.get("open_hole_index") is not None
        wall_supplied = sq.get("wall_diameter_in") is not None
        if sum((tubular_supplied, open_hole_supplied, wall_supplied)) != 1:
            raise ValueError(f"{ctx}: supply exactly one physical target or an explicit operation-wall diameter")
        kind = str(sq.get("target_kind", "")).lower()
        if kind not in ("lap", "shoe", "point"):
            raise ValueError(f"{ctx}.target_kind must be explicitly 'lap', 'shoe' or 'point'")

        if wall_supplied:
            diameter = _num(sq["wall_diameter_in"], f"{ctx}.wall_diameter_in")
            if diameter <= 0 or kind != "point":
                raise ValueError(f"{ctx}: operation wall requires positive diameter and point marker")
            sq.update(depth_m=depth, wall_diameter_in=diameter)
            continue

        if open_hole_supplied:
            oi = _index(sq.get("open_hole_index"), f"{ctx}.open_hole_index", len(data["open_holes"]))
            target_oh = data["open_holes"][oi]
            if kind != "point":
                raise ValueError(f"{ctx}: open-hole squeeze target_kind must be 'point'")
            if not (float(target_oh["top_md"]) - _DEPTH_TOL <= depth <= float(target_oh["bottom_md"]) + _DEPTH_TOL):
                raise ValueError(f"{ctx}: open-hole squeeze depth must lie inside the explicit open hole")
            sq.pop("target_index", None)
            sq["depth_m"], sq["open_hole_index"], sq["target_kind"] = depth, oi, kind
            continue

        ti = _index(sq.get("target_index"), f"{ctx}.target_index", len(casings))
        target = casings[ti]
        if kind == "lap":
            if target["type"] not in ("liner", "tieback"):
                raise ValueError(f"{ctx}: lap squeeze target must be LNR or TB LNR")
            if abs(depth - float(target["top_md"])) > _DEPTH_TOL:
                raise ValueError(f"{ctx}: lap squeeze depth must match target top/lap depth")
        elif kind == "shoe":
            if abs(depth - float(target["shoe_md"])) > _DEPTH_TOL:
                raise ValueError(f"{ctx}: shoe squeeze depth must match target shoe depth")
        elif not (float(target["top_md"]) - _DEPTH_TOL <= depth <= float(target["shoe_md"]) + _DEPTH_TOL):
            raise ValueError(f"{ctx}: point squeeze depth must lie on the explicit target string")
        sq.pop("open_hole_index", None)
        sq["depth_m"], sq["target_index"], sq["target_kind"] = depth, ti, kind

    if "show_mid_depth" in data and not isinstance(data["show_mid_depth"], bool):
        raise ValueError("show_mid_depth must be true or false when supplied")

    current = data.get("current_job")
    if not isinstance(current, dict):
        raise ValueError("current_job must be explicitly supplied; the renderer never infers the current job")
    job_type = str(current.get("type", "")).lower()
    if job_type not in ("casing", "liner", "tieback", "cmt_plug", "cmt_squeeze"):
        raise ValueError("current_job.type must be casing, liner, tieback, cmt_plug or cmt_squeeze")
    pool_len = len(casings) if job_type in ("casing", "liner", "tieback") else \
        (len(data["cement_plugs"]) if job_type == "cmt_plug" else len(data["squeezes"]))
    target_index = _index(current.get("target_index"), "current_job.target_index", pool_len)
    if job_type in ("casing", "liner", "tieback") and casings[target_index]["type"] != job_type:
        raise ValueError("current_job.target_index does not reference the declared current job type")
    current["type"], current["target_index"] = job_type, target_index

    if data.get("final_relevant_depth_m") is not None:
        final = _num(data["final_relevant_depth_m"], "final_relevant_depth_m")
        if final <= 0:
            raise ValueError("final_relevant_depth_m must be > 0")
        data["final_relevant_depth_m"] = final
    if data.get("y_max") is not None:
        raise ValueError("y_max override is disabled; use final_relevant_depth_m and the fixed +200 m rule")
    return data


def check_well_design(data: dict) -> List[str]:
    """Consistency checks that use only explicit authority already present in the payload."""
    findings: List[str] = []
    cas = data.get("casings", [])
    holes = sorted(data.get("open_holes") or [], key=lambda o: float(o["top_md"]))

    def nm(c):
        return f'{format_api_size(c["size_in"])} {c.get("type")} {float(c["top_md"]):g}-{float(c["shoe_md"]):g} m'

    def passable(outer):
        return float(outer["id_in"]) if outer.get("id_in") else float(outer["size_in"])

    for c in cas:
        top = float(c["top_md"])
        if c["type"] == "casing" and top > _DEPTH_TOL:
            findings.append(f"{nm(c)}: casing must reach surface")
        if c["type"] == "liner" and top <= _DEPTH_TOL:
            findings.append(f"{nm(c)}: liner top cannot be surface")

    # Certified Hardware need not list casing shoes in installation order.
    csgs = sorted((c for c in cas if c["type"] == "casing"), key=lambda c: -float(c["size_in"]))
    for a, b in zip(csgs, csgs[1:]):
        if float(b["size_in"]) >= passable(a):
            findings.append(f"{nm(b)} cannot be run through {nm(a)}")

    for c in cas:
        if c["type"] not in ("liner", "tieback"):
            continue
        host = cas[c["host_index"]]
        if float(host["shoe_md"]) - float(c["top_md"]) <= _DEPTH_TOL:
            findings.append(f"{nm(c)}: zero lap inside explicit host {nm(host)}")
        if float(c["size_in"]) >= passable(host):
            findings.append(f"{nm(c)} does not fit through explicit host {nm(host)}")

    for a, b in zip(holes, holes[1:]):
        if float(b["top_md"]) < float(a["bottom_md"]) - _DEPTH_TOL:
            findings.append(f"open holes overlap: {float(a['top_md']):g}-{float(a['bottom_md']):g} m and "
                            f"{float(b['top_md']):g}-{float(b['bottom_md']):g} m")
    for oh in holes:
        if oh.get("host_index") is None:
            continue
        host = cas[oh["host_index"]]
        # Certified app geometry permits equality at the previous shoe.
        if float(oh["hole_size_in"]) > passable(host):
            findings.append(f"open hole {float(oh['top_md']):g}-{float(oh['bottom_md']):g} m "
                            f"cannot pass explicit host {nm(host)}")

    # A plug must occupy a real bore at every interval. Never invent a fallback width.
    for p in data.get("cement_plugs", []):
        top, bot = float(p["top_md"]), float(p["bottom_md"])
        boundaries = sorted({top, bot} |
                            {float(c["top_md"]) for c in cas if top < float(c["top_md"]) < bot} |
                            {float(c["shoe_md"]) for c in cas if top < float(c["shoe_md"]) < bot} |
                            {float(o["top_md"]) for o in holes if top < float(o["top_md"]) < bot} |
                            {float(o["bottom_md"]) for o in holes if top < float(o["bottom_md"]) < bot} |
                            {float(b[k]) for b in data.get("plug_bores", []) for k in ("top_md", "bottom_md") if top < float(b[k]) < bot})
        for a, b in zip(boundaries[:-1], boundaries[1:]):
            mid = 0.5 * (a + b)
            pipe = any(float(c["top_md"]) <= mid <= float(c["shoe_md"]) for c in cas)
            hole = any(float(o["top_md"]) <= mid <= float(o["bottom_md"]) for o in holes)
            supplemental = any(float(b["top_md"]) <= mid <= float(b["bottom_md"]) for b in data.get("plug_bores", []))
            if not pipe and not hole and not supplemental:
                findings.append(f"cement plug {top:g}-{bot:g} m has unresolved bore geometry at {mid:g} m")
                break
    return findings


def _current_job_depth(data: dict) -> float:
    current = data["current_job"]
    kind, idx = current["type"], current["target_index"]
    if kind in ("casing", "liner", "tieback"):
        return float(data["casings"][idx]["shoe_md"])
    if kind == "cmt_plug":
        return float(data["cement_plugs"][idx]["bottom_md"])
    return float(data["squeezes"][idx]["depth_m"])


def _final_relevant_depth(data: dict) -> float:
    """Resolve axis authority without guessing a current job or clipping open hole."""
    required = _current_job_depth(data)
    if data.get("open_holes"):
        required = max(required, max(float(o["bottom_md"]) for o in data["open_holes"]))
    explicit = data.get("final_relevant_depth_m")
    if explicit is not None:
        if explicit + _DEPTH_TOL < required:
            raise ValueError(f"final_relevant_depth_m ({explicit:g}) is shallower than required displayed depth ({required:g})")
        required = float(explicit)

    # Every rendered item must fit the authoritative axis. Do not silently stretch or clip
    # historical tubulars or non-current operation markers; require explicit owner/app authority.
    displayed_depths = [float(c["shoe_md"]) for c in data["casings"]]
    displayed_depths += [float(p["bottom_md"]) for p in data.get("cement_plugs", [])]
    displayed_depths += [float(sq["depth_m"]) for sq in data.get("squeezes", [])]
    deepest_displayed = max(displayed_depths)
    if deepest_displayed > required + _DEPTH_TOL:
        raise ValueError(
            f"displayed geometry extends to {deepest_displayed:g} m below the resolved current-operation depth "
            f"{required:g} m; supply final_relevant_depth_m explicitly so every rendered item can be shown"
        )
    return required


def compute_total_depth(data: dict) -> float:
    """Compatibility entry point: now returns Final Relevant Job Depth, not deepest inferred string."""
    return _final_relevant_depth(data)


def resolve_depth_axis(data: dict) -> Tuple[float, List[float]]:
    final_depth = _final_relevant_depth(data)
    return calculate_dynamic_depth_axis(final_depth, show_mid=bool(data.get("show_mid_depth", True)))



def _prepare_open_holes(open_holes: List[dict], casings: List[dict]) -> List[dict]:
    """Attach only explicitly supplied host geometry; never infer an open-hole host."""
    out = []
    for oh in open_holes:
        row = dict(oh)
        if row.get("host_index") is not None:
            row["_host_od"] = float(casings[row["host_index"]]["size_in"])
        out.append(row)
    return out


# =========================================================================================
# 4. TWO-STAGE RADIAL ENGINE
# =========================================================================================
def _build_radial_maps(data: dict, open_holes: List[dict], col_span: float) -> Tuple[Dict[float, float], Dict[float, float]]:
    pipe_sizes = sorted({round(float(c["size_in"]), 4) for c in data.get("casings", [])})
    operation_sizes = [b["diameter_in"] for b in data.get("plug_bores", [])]
    operation_sizes += [sq["wall_diameter_in"] for sq in data.get("squeezes", []) if "wall_diameter_in" in sq]
    oh_sizes = sorted({round(float(oh.get("hole_size_in", 8.5)), 4) for oh in open_holes} |
                      {round(float(size), 4) for size in operation_sizes})

    min_pipe_hw = 0.135
    max_pipe_hw = 0.385
    max_s = max(pipe_sizes + oh_sizes) if (pipe_sizes or oh_sizes) else 30.0

    n_p = len(pipe_sizes)
    pipe_map: Dict[float, float] = {}
    if n_p == 1:
        s0 = pipe_sizes[0]
        pipe_map[s0] = 0.25
    elif n_p > 1:
        s_min, s_max = pipe_sizes[0], pipe_sizes[-1]
        s_span = max(s_max - s_min, 1.0)
        raw_hw = []
        for idx, s in enumerate(pipe_sizes):
            phys_norm = (s - s_min) / s_span
            rank_norm = idx / (n_p - 1)
            blend = 0.50 * phys_norm + 0.50 * rank_norm
            raw_hw.append(min_pipe_hw + blend * (max_pipe_hw - min_pipe_hw))
        min_step = min(0.042, (max_pipe_hw - min_pipe_hw) / (n_p - 1))
        for i in range(1, n_p):
            if raw_hw[i] - raw_hw[i - 1] < min_step:
                raw_hw[i] = raw_hw[i - 1] + min_step
        if raw_hw[-1] > max_pipe_hw:
            sp = raw_hw[-1] - raw_hw[0]
            raw_hw = [min_pipe_hw + (h - raw_hw[0]) / sp * (max_pipe_hw - min_pipe_hw) for h in raw_hw]
        pipe_map = {s: h for s, h in zip(pipe_sizes, raw_hw)}

    oh_map: Dict[float, float] = {}
    shoe_flare_w = 0.028
    for ohs in oh_sizes:
        smaller_pipes = [s for s in pipe_sizes if s < ohs]
        larger_pipes = [s for s in pipe_sizes if s >= ohs]
        if smaller_pipes and larger_pipes:
            s_in = smaller_pipes[-1]
            s_out = larger_pipes[0]
            hw_in, hw_out = pipe_map[s_in], pipe_map[s_out]
            # CemCADE look: the hole wall aligns with the outer edge of the string above it.
            # Always strictly wider than the inner string and never wider than the outer one,
            # whatever the number of distinct sizes (the pipe steps may be very small).
            oh_map[ohs] = max(hw_out - 0.00675, 0.5 * (hw_in + hw_out))
        elif smaller_pipes:
            s_in = smaller_pipes[-1]
            oh_map[ohs] = min(0.435, pipe_map[s_in] + 0.028)
        else:
            # hole smaller than every string (e.g. open hole below the last shoe): it can only be
            # as wide as the narrowest string it was drilled through
            oh_map[ohs] = (pipe_map[pipe_sizes[0]] - 0.00675) if pipe_sizes else 0.35 * col_span

    return pipe_map, oh_map


def _explicit_host(data: dict, string: dict) -> dict:
    """Return the already-authoritative host selected outside the renderer."""
    idx = string.get("host_index")
    if idx is None:
        raise ValueError("liner/tieback host is not explicitly supplied")
    return data["casings"][idx]


def _explicit_landing_liner(data: dict, tieback: dict) -> dict:
    """Return the explicit receiving liner; this is not the geometric host."""
    idx = tieback.get("landing_liner_index")
    if idx is None:
        raise ValueError("tie-back landing liner is not explicitly supplied")
    return data["casings"][idx]


# =========================================================================================
# 5. AUTHENTIC CEMCADE RIG HEADER ILLUSTRATION
# =========================================================================================
def _draw_rig(ax, well_center_x: float = 40.25) -> None:
    """Draw a detailed, clean CemCADE-style land drilling rig header.

    The rig is a presentation-only header and is centered over the wellbore axis
    so the mast, hook, BOP stack and schematic centerline read as one logical
    drilling system.  No engineering geometry is inferred or modified here.
    """
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect("auto")
    ax.axis("off")

    C_STEEL = "#3E4348"
    C_STEEL_LIGHT = "#70777D"
    C_DECK = "#F6F6F4"
    C_DECK_SHADOW = "#D9DBDC"
    C_WINDOW = "#D9EEF5"
    C_DARK = "#151515"
    LW = 0.95

    # The older rig art used 41.9 as the mast / well center.  Everything that
    # belongs to the drilling unit is shifted from that reference so the mast is
    # now centered directly above the schematic wellbore.
    _ref_well_x = 41.9
    sh = float(well_center_x) - _ref_well_x
    sx = lambda x: x + sh

    def rect(x, y, w, h, fc="white", ec=C_DARK, lw=LW, z=3):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=fc, edgecolor=ec,
                               linewidth=lw, zorder=z))

    def line(xs, ys, lw=LW, color=C_DARK, z=3, ls="-"):
        ax.add_line(Line2D(xs, ys, color=color, linewidth=lw, zorder=z,
                           linestyle=ls, solid_capstyle="round"))

    def circle(x, y, r, fc="white", ec=C_DARK, lw=LW, z=3):
        ax.add_patch(Circle((x, y), r, facecolor=fc, edgecolor=ec,
                            linewidth=lw, zorder=z))

    def x_brace(x0, x1, y0, y1, lw=0.72, color=C_STEEL_LIGHT, z=2.8):
        line([x0, x1], [y0, y1], lw=lw, color=color, z=z)
        line([x0, x1], [y1, y0], lw=lw, color=color, z=z)

    # ------------------------------------------------------------------
    # Ground line + left pipe rack / catwalk / stairs
    # ------------------------------------------------------------------
    line([1.0, 96.0], [1.8, 1.8], lw=1.15, color="#707070", z=1.8)

    # Pipe rack trestles and stacked tubular ends
    rect(2.8, 2.0, 6.0, 13.5, fc="#EEEDE8", ec="#666666", lw=0.8, z=2.0)
    line([2.8, 8.8], [8.7, 8.7], lw=0.75, color="#777777", z=2.2)
    for row, count in enumerate((5, 4, 3)):
        for k in range(count):
            cx = 3.55 + row * 0.58 + k * 1.02
            cy = 17.2 + row * 2.05
            circle(cx, cy, 0.59, fc=C_PIPE_RACK_GREEN, ec="#222222", lw=0.58, z=3.5)
            circle(cx, cy, 0.18, fc="#BFDDBF", ec="none", lw=0, z=3.7)

    # Additional pipe-rack trestles and simple pipe stops for a more realistic V-door area
    for x in (3.4, 5.8, 8.2):
        line([x, x], [2.0, 15.5], lw=0.56, color="#8A8A8A", z=2.1)
    line([2.6, 8.9], [15.5, 15.5], lw=0.52, color="#777777", z=2.2)
    line([2.6, 8.9], [21.2, 21.2], lw=0.42, color="#8C8C8C", z=2.2)

    # Catwalk beam and supports
    rect(sx(7.8), 24.5, 14.2, 2.4, fc=C_DECK, ec=C_DARK, lw=0.95, z=2.6)
    for x in (10.0, 15.4, 20.5):
        line([sx(x), sx(x)], [2.0, 24.5], lw=0.8, color=C_STEEL_LIGHT, z=2.2)
    line([sx(8.0), sx(21.8)], [24.5, 24.5], lw=1.0, color=C_DARK, z=3)
    # Pipe ramp / V-door rollers leading from rack toward the catwalk
    line([sx(6.9), sx(10.3)], [15.1, 24.5], lw=0.85, color=C_DARK, z=2.7)
    line([sx(7.7), sx(11.1)], [15.1, 24.5], lw=0.85, color=C_DARK, z=2.7)
    for t in (0.18, 0.38, 0.58, 0.78):
        x0 = sx(6.9 + (10.3 - 6.9) * t)
        x1 = sx(7.7 + (11.1 - 7.7) * t)
        y = 15.1 + (24.5 - 15.1) * t
        line([x0, x1], [y, y], lw=0.45, color="#8C8F91", z=2.85)
    line([sx(6.6), sx(7.4)], [14.7, 14.7], lw=0.62, color="#777777", z=2.86)
    line([sx(10.7), sx(11.5)], [24.9, 24.9], lw=0.62, color="#777777", z=2.86)

    # Staircase with handrail
    stair_x0, stair_y0 = sx(8.7), 3.0
    step_dx, step_dy = 1.55, 3.0
    for i in range(7):
        x = stair_x0 + i * step_dx
        y = stair_y0 + i * step_dy
        line([x, x + step_dx], [y, y], lw=1.0, color=C_DARK, z=3)
        if i < 6:
            line([x + step_dx, x + step_dx], [y, y + step_dy], lw=1.0, color=C_DARK, z=3)
    line([sx(8.8), sx(18.2)], [8.0, 26.0], lw=0.75, color=C_STEEL_LIGHT, z=2.9)
    rect(sx(17.2), 24.9, 4.1, 1.3, fc="#ECECE9", ec=C_DARK, lw=0.52, z=2.95)

    # Shale-shaker skid with possum belly / return area.  These coordinates are
    # intentionally NOT shifted with the mast so the left equipment retains a
    # positive visual margin and can never be clipped by rig-centering changes.
    shaker_x0 = 1.05
    rect(shaker_x0, 2.2, 8.35, 6.4, fc="#E7E9EA", ec=C_DARK, lw=0.66, z=2.5)
    ax.add_patch(Polygon([(1.65, 8.6), (8.65, 8.6), (7.35, 13.0), (2.85, 13.0)],
                         closed=True, facecolor="#F5F5F2", edgecolor=C_DARK, lw=0.66, zorder=2.7))
    line([2.05, 7.75], [11.8, 9.7], lw=0.58, color="#666666", z=2.85)
    line([2.35, 8.05], [10.7, 8.7], lw=0.58, color="#666666", z=2.85)
    rect(8.75, 9.2, 2.25, 1.8, fc="#D4D7D8", ec=C_DARK, lw=0.46, z=2.75)
    # Return-flow line from the substructure to the possum belly.
    line([sx(21.0), sx(16.0)], [18.6, 18.6], lw=0.74, color=C_DARK, z=2.92)
    line([sx(16.0), 12.8], [18.6, 13.0], lw=0.74, color=C_DARK, z=2.92)
    line([12.8, 10.95], [13.0, 10.6], lw=0.74, color=C_DARK, z=2.92)
    line([10.95, 9.85], [10.6, 10.1], lw=0.74, color=C_DARK, z=2.92)

    # ------------------------------------------------------------------
    # Substructure / drill floor / handrails
    # ------------------------------------------------------------------
    sx0, sx1 = sx(21.0), sx(70.0)
    rect(sx0, 2.0, sx1 - sx0, 21.2, fc="white", ec=C_DARK, lw=1.15, z=2.3)
    rect(sx0, 23.2, sx1 - sx0, 4.7, fc=C_DECK, ec=C_DARK, lw=1.15, z=2.8)
    rect(sx0, 27.9, sx1 - sx0, 1.45, fc=C_DECK_SHADOW, ec=C_DARK, lw=0.9, z=2.9)

    bay_xs = [sx(x) for x in (21.0, 29.0, 37.0, 45.0, 54.0, 62.0, 70.0)]
    for x in bay_xs:
        line([x, x], [2.0, 23.2], lw=0.88, color=C_STEEL, z=2.6)
    for a, b in zip(bay_xs[:-1], bay_xs[1:]):
        x_brace(a, b, 2.5, 22.8, lw=0.68)

    # Rig-floor handrail
    line([sx(17.5), sx(70.0)], [37.3, 37.3], lw=0.72, color=C_STEEL, z=3.0)
    line([sx(17.5), sx(70.0)], [33.1, 33.1], lw=0.58, color=C_STEEL_LIGHT, z=2.9)
    for x in (18.0, 23.0, 28.5, 34.0, 50.0, 57.0, 64.0, 69.5):
        line([sx(x), sx(x)], [29.3, 37.3], lw=0.68, color=C_STEEL, z=3.0)

    # Rotary table / drill floor opening / well center on drill floor
    rect(sx(38.2), 27.9, 7.4, 1.4, fc="#B5B8BA", ec=C_DARK, lw=0.8, z=3.3)
    rect(sx(39.3), 29.3, 5.2, 1.3, fc="#E6E6E6", ec=C_DARK, lw=0.75, z=3.3)
    rect(sx(39.9), 23.4, 4.0, 4.5, fc="#F8F8F6", ec=C_DARK, lw=0.72, z=3.1)
    line([well_center_x, well_center_x], [23.4, 29.3], lw=0.8, color="#747474", z=3.2, ls=(0, (2, 2)))

    # ------------------------------------------------------------------
    # BOP / wellhead stack - centered exactly below the wellbore axis
    # ------------------------------------------------------------------
    cx = well_center_x

    # Casing head / wellhead base and lower spool
    rect(cx - 2.65, 2.05, 5.30, 1.10, fc="#B45B84", ec=C_DARK, lw=0.78, z=3.42)
    rect(cx - 3.15, 3.15, 6.30, 0.75, fc="#8F4168", ec=C_DARK, lw=0.72, z=3.46)
    rect(cx - 2.20, 3.90, 4.40, 1.15, fc="#D184A6", ec=C_DARK, lw=0.72, z=3.46)

    # Lower ram preventer: body, bonnet housings and flange bands
    rect(cx - 2.85, 5.05, 5.70, 3.35, fc=C_ROSE_BOP, ec=C_DARK, lw=0.86, z=3.50)
    rect(cx - 3.70, 5.95, 0.85, 1.55, fc="#B75D89", ec=C_DARK, lw=0.68, z=3.48)
    rect(cx + 2.85, 5.95, 0.85, 1.55, fc="#B75D89", ec=C_DARK, lw=0.68, z=3.48)
    rect(cx - 3.20, 4.85, 6.40, 0.45, fc="#93476B", ec=C_DARK, lw=0.60, z=3.53)
    rect(cx - 3.20, 8.15, 6.40, 0.45, fc="#93476B", ec=C_DARK, lw=0.60, z=3.53)

    # Drilling spool with choke / kill side outlets
    rect(cx - 2.10, 8.60, 4.20, 1.70, fc="#D98CAE", ec=C_DARK, lw=0.72, z=3.50)
    line([cx - 2.10, cx - 4.10], [9.45, 9.45], lw=0.85, color=C_DARK, z=3.62)
    line([cx + 2.10, cx + 4.10], [9.45, 9.45], lw=0.85, color=C_DARK, z=3.62)
    circle(cx - 4.25, 9.45, 0.38, fc="#C8CBCD", ec=C_DARK, lw=0.48, z=3.66)
    circle(cx + 4.25, 9.45, 0.38, fc="#C8CBCD", ec=C_DARK, lw=0.48, z=3.66)

    # Upper ram preventer
    rect(cx - 2.95, 10.30, 5.90, 3.75, fc=C_ROSE_BOP, ec=C_DARK, lw=0.86, z=3.52)
    rect(cx - 3.82, 11.15, 0.87, 1.95, fc="#B75D89", ec=C_DARK, lw=0.68, z=3.50)
    rect(cx + 2.95, 11.15, 0.87, 1.95, fc="#B75D89", ec=C_DARK, lw=0.68, z=3.50)
    rect(cx - 3.28, 10.08, 6.56, 0.45, fc="#93476B", ec=C_DARK, lw=0.60, z=3.54)
    rect(cx - 3.28, 13.82, 6.56, 0.45, fc="#93476B", ec=C_DARK, lw=0.60, z=3.54)

    # Annular preventer: tapered elastomer housing and top adapter
    ax.add_patch(Polygon([(cx - 2.60, 14.27), (cx + 2.60, 14.27),
                          (cx + 2.15, 16.75), (cx + 1.45, 18.55),
                          (cx - 1.45, 18.55), (cx - 2.15, 16.75)],
                         closed=True, facecolor="#C86F9A", edgecolor=C_DARK,
                         lw=0.86, zorder=3.56))
    rect(cx - 2.25, 18.55, 4.50, 0.85, fc="#A74F78", ec=C_DARK, lw=0.68, z=3.58)
    rect(cx - 1.25, 19.40, 2.50, 1.20, fc="#D6D9DB", ec=C_DARK, lw=0.56, z=3.58)
    rect(cx - 0.58, 20.60, 1.16, 1.30, fc="#B8BDC0", ec=C_DARK, lw=0.52, z=3.60)

    # Central bore from wellhead through rotary opening
    line([cx, cx], [2.05, 29.3], lw=0.78, color="#2A2A2A", z=3.72)

    # Choke manifold on the right side of the wellhead.  The choke line leaves
    # the drilling spool, drops to the manifold skid, then exits to the flare side.
    rect(cx + 6.2, 3.0, 6.0, 2.8, fc="#E6E7E7", ec=C_DARK, lw=0.58, z=3.22)
    line([cx + 4.63, cx + 5.35], [9.45, 9.45], lw=0.68, color=C_DARK, z=3.62)
    line([cx + 5.35, cx + 5.35], [9.45, 5.15], lw=0.68, color=C_DARK, z=3.62)
    line([cx + 5.35, cx + 6.2], [5.15, 5.15], lw=0.68, color=C_DARK, z=3.62)
    line([cx + 7.0, cx + 11.1], [4.35, 4.35], lw=0.68, color=C_DARK, z=3.35)
    for vx in (cx + 7.25, cx + 9.05, cx + 10.85):
        circle(vx, 4.35, 0.38, fc="#F2F2EF", ec=C_DARK, lw=0.40, z=3.42)
        line([vx, vx], [3.96, 4.76], lw=0.32, color=C_DARK, z=3.45)
    # pressure gauges
    for gx in (cx + 8.15, cx + 9.95):
        line([gx, gx], [4.75, 5.45], lw=0.30, color=C_DARK, z=3.45)
        circle(gx, 5.72, 0.28, fc="white", ec=C_DARK, lw=0.30, z=3.47)
    line([cx + 11.1, cx + 12.7], [4.35, 5.8], lw=0.58, color=C_DARK, z=3.38)
    line([cx + 12.7, cx + 15.0], [5.8, 5.8], lw=0.58, color=C_DARK, z=3.38)
    circle(cx + 15.25, 5.8, 0.30, fc="#F2F2EF", ec=C_DARK, lw=0.32, z=3.42)

    # Kill-line branch on the left side of the BOP stack with two isolation valves.
    line([cx - 4.63, cx - 5.45], [9.45, 9.45], lw=0.64, color=C_DARK, z=3.60)
    line([cx - 5.45, cx - 5.45], [9.45, 6.55], lw=0.64, color=C_DARK, z=3.60)
    line([cx - 5.45, cx - 8.35], [6.55, 6.55], lw=0.64, color=C_DARK, z=3.60)
    for vx in (cx - 6.35, cx - 7.55):
        circle(vx, 6.55, 0.34, fc="#F2F2EF", ec=C_DARK, lw=0.36, z=3.65)
        line([vx, vx], [6.18, 6.92], lw=0.28, color=C_DARK, z=3.67)

    # Accumulator unit on the left side of the wellhead
    rect(cx - 15.6, 2.3, 7.8, 2.3, fc="#E5E7E7", ec=C_DARK, lw=0.6, z=2.95)
    rect(cx - 15.0, 4.6, 1.6, 1.2, fc="#D7DADB", ec=C_DARK, lw=0.46, z=3.02)
    for bx in (cx - 12.4, cx - 11.2, cx - 10.0, cx - 8.8):
        rect(bx, 4.6, 0.72, 3.5, fc="#F1F1EE", ec=C_DARK, lw=0.42, z=3.02)
        circle(bx + 0.36, 8.3, 0.36, fc="#F1F1EE", ec=C_DARK, lw=0.42, z=3.02)
    line([cx - 7.9, cx - 4.6], [4.0, 8.6], lw=0.65, color=C_DARK, z=3.1)
    line([cx - 4.6, cx - 4.6], [8.6, 11.2], lw=0.65, color=C_DARK, z=3.1)
    line([cx - 4.6, cx - 3.9], [11.2, 11.2], lw=0.65, color=C_DARK, z=3.1)

    # ------------------------------------------------------------------
    # Derrick / mast - centered over the well axis with refined details
    # ------------------------------------------------------------------
    base_l, base_r = cx - 7.70, cx + 7.70
    top_l, top_r = cx - 3.80, cx + 3.80
    y_base, y_top = 29.3, 98.2

    def mast_x_at(y, left=True):
        t = (y - y_base) / (y_top - y_base)
        a, b = ((base_l, top_l) if left else (base_r, top_r))
        return a + t * (b - a)

    # Main tapered derrick legs and secondary inner chords
    for x0, x1, lw in ((base_l, top_l, 1.72), (base_r, top_r, 1.72),
                       (cx - 4.95, cx - 2.35, 0.90), (cx + 4.95, cx + 2.35, 0.90)):
        line([x0, x1], [y_base, y_top], lw=lw, color=C_STEEL, z=3.20)

    mast_levels = [29.3, 37.7, 46.1, 54.5, 62.9, 71.3, 79.7, 88.1, 98.2]
    for y in mast_levels:
        xl, xr = mast_x_at(y, True), mast_x_at(y, False)
        line([xl, xr], [y, y], lw=0.88, color=C_STEEL, z=3.10)
    for y0, y1 in zip(mast_levels[:-1], mast_levels[1:]):
        xl0, xr0 = mast_x_at(y0, True), mast_x_at(y0, False)
        xl1, xr1 = mast_x_at(y1, True), mast_x_at(y1, False)
        line([xl0, xr1], [y0, y1], lw=0.58, color=C_STEEL_LIGHT, z=2.95)
        line([xr0, xl1], [y0, y1], lw=0.58, color=C_STEEL_LIGHT, z=2.95)

    # Crown-block frame with multiple sheaves, closer to a real crown assembly
    rect(cx - 4.30, 97.15, 8.60, 2.05, fc="#EEEEEC", ec=C_DARK, lw=0.82, z=3.50)
    for x in (cx - 3.15, cx - 1.58, cx, cx + 1.58, cx + 3.15):
        circle(x, 98.18, 0.53, fc=C_ORANGE_SHEAVE, ec=C_DARK, lw=0.53, z=4.00)
    line([cx - 4.30, cx + 4.30], [96.72, 96.72], lw=0.52, color=C_STEEL_LIGHT, z=3.40)

    # Monkey board / fingerboard platform and safety rail
    mb_y = 66.2
    mb_l, mb_r = mast_x_at(mb_y, True) - 2.30, mast_x_at(mb_y, False) + 2.30
    rect(mb_l, mb_y - 0.62, mb_r - mb_l, 1.24, fc="#E7E7E4", ec=C_DARK, lw=0.62, z=3.35)
    line([mb_l, mb_r], [mb_y + 3.65, mb_y + 3.65], lw=0.52, color=C_STEEL, z=3.20)
    for x in (mb_l, mb_l + 3.75, mb_r - 3.75, mb_r):
        line([x, x], [mb_y + 0.62, mb_y + 3.65], lw=0.48, color=C_STEEL, z=3.20)
    # Fingerboard prongs
    for x in (cx - 2.8, cx - 1.4, cx + 1.4, cx + 2.8):
        line([x, x], [mb_y - 0.62, mb_y + 1.15], lw=0.38, color="#747474", z=3.38)

    # Internal access ladder along left chord
    ladder_x0, ladder_x1 = cx - 5.20, cx - 4.05
    line([ladder_x0, top_l - 0.20], [31.0, 95.0], lw=0.46, color="#666666", z=2.90)
    line([ladder_x1, top_l + 0.95], [31.0, 95.0], lw=0.46, color="#666666", z=2.90)
    for y in range(34, 95, 4):
        t = (y - 31.0) / (95.0 - 31.0)
        xa = ladder_x0 + t * ((top_l - 0.20) - ladder_x0)
        xb = ladder_x1 + t * ((top_l + 0.95) - ladder_x1)
        line([xa, xb], [y, y], lw=0.38, color="#777777", z=2.95)

    # Decorative backstay/deadline-route strokes are intentionally omitted.
    # In the compact report header they read as free-floating lines rather than
    # clearly connected rig equipment, so the mast silhouette remains clean.

    # ------------------------------------------------------------------
    # Hoisting system: drilling line, traveling block, hook, swivel & kelly
    # ------------------------------------------------------------------
    # Four visible falls of drilling line between crown and traveling block
    for x_top, x_bot in ((cx - 2.25, cx - 1.65), (cx - 0.75, cx - 0.55),
                         (cx + 0.75, cx + 0.55), (cx + 2.25, cx + 1.65)):
        line([x_top, x_bot], [97.2, 81.0], lw=0.50, color=C_DARK, z=3.78)

    # Traveling block with three visible sheaves and lower bail
    rect(cx - 2.65, 76.0, 5.30, 5.20, fc="#F2F2EF", ec=C_DARK, lw=0.72, z=3.82)
    for x in (cx - 1.55, cx, cx + 1.55):
        circle(x, 79.0, 0.73, fc=C_ORANGE_SHEAVE, ec=C_DARK, lw=0.56, z=4.02)
    line([cx - 1.65, cx + 1.65], [76.85, 76.85], lw=0.48, color="#777777", z=3.90)
    line([cx - 1.10, cx - 0.65, cx + 0.65, cx + 1.10], [76.0, 74.7, 74.7, 76.0],
         lw=0.82, color=C_DARK, z=4.00)

    # Hook block: neck, hook body and throat
    line([cx, cx], [74.7, 73.55], lw=0.88, color=C_DARK, z=4.00)
    ax.add_patch(Polygon([(cx - 0.80, 73.55), (cx + 0.80, 73.55),
                          (cx + 0.92, 72.75), (cx + 0.35, 71.85),
                          (cx - 0.45, 71.85), (cx - 0.88, 72.45)],
                         closed=True, facecolor=C_ORANGE_SHEAVE, edgecolor=C_DARK,
                         lw=0.62, zorder=4.03))

    # Swivel / gooseneck / kelly stem
    line([cx, cx], [71.85, 70.65], lw=0.76, color=C_DARK, z=4.00)
    rect(cx - 1.05, 68.65, 2.10, 2.00, fc="#D7D7D5", ec=C_DARK, lw=0.64, z=3.96)
    circle(cx, 69.65, 0.38, fc="#F5F5F3", ec="#6C6C6C", lw=0.42, z=4.00)
    rect(cx - 0.40, 67.25, 0.80, 1.40, fc="#B7BCBE", ec=C_DARK, lw=0.48, z=3.98)
    line([cx, cx], [67.25, 29.3], lw=1.28, color=C_DARK, z=3.92)

    # Standpipe and rotary hose.  Hose terminates at the swivel/gooseneck rather than the floor.
    stand_x = cx + 7.90
    line([stand_x, stand_x], [29.3, 69.0], lw=1.55, color=C_DARK, z=3.88)
    line([stand_x - 1.25, stand_x], [69.0, 69.0], lw=0.92, color=C_DARK, z=3.90)
    hose_pts = [
        (stand_x - 1.25, 69.0), (cx + 6.0, 69.2), (cx + 5.2, 69.0), (cx + 4.5, 68.4),
        (cx + 4.0, 67.4), (cx + 3.7, 66.0), (cx + 3.55, 64.3), (cx + 3.55, 62.6),
        (cx + 3.35, 61.0), (cx + 2.95, 59.7), (cx + 2.40, 58.9), (cx + 1.80, 58.5),
        (cx + 1.25, 58.7), (cx + 0.95, 59.4), (cx + 0.80, 60.4), (cx + 0.78, 62.0),
        (cx + 0.78, 64.0), (cx + 0.65, 66.0), (cx + 0.45, 67.7), (cx + 0.30, 68.8)
    ]
    line([p[0] for p in hose_pts], [p[1] for p in hose_pts], lw=1.92, color=C_DARK, z=4.14)

    # ------------------------------------------------------------------
    # Doghouse, mud tanks, shale-side equipment and pump skid
    # ------------------------------------------------------------------
    # Drawworks on the rig floor, positioned off-center so the well center remains clear
    rect(sx(27.2), 29.3, 7.8, 4.9, fc="#D9DBDC", ec=C_DARK, lw=0.68, z=3.25)
    circle(sx(30.0), 31.75, 1.55, fc="#ECECEA", ec=C_DARK, lw=0.58, z=3.40)
    circle(sx(30.0), 31.75, 0.68, fc="#C8CBCC", ec=C_DARK, lw=0.45, z=3.45)
    rect(sx(33.0), 30.1, 1.25, 3.2, fc="#BFC3C5", ec=C_DARK, lw=0.48, z=3.42)
    line([sx(27.7), sx(34.5)], [34.2, 34.2], lw=0.45, color="#777777", z=3.34)

    # Doghouse with sloped roof, door and window
    ax.add_patch(Polygon([(sx(50.2), 29.3), (sx(56.8), 29.3), (sx(56.8), 37.1),
                          (sx(55.2), 39.0), (sx(50.2), 39.0)], closed=True,
                         facecolor="#EEF0D3", edgecolor=C_DARK, lw=0.85, zorder=3.35))
    ax.add_patch(Polygon([(sx(49.8), 39.0), (sx(55.3), 39.0), (sx(57.2), 36.7), (sx(50.6), 36.7)],
                         closed=True, facecolor=C_TANK_YELLOW, edgecolor=C_DARK,
                         lw=0.75, zorder=3.45))
    rect(sx(51.0), 31.0, 1.65, 5.3, fc="#F3F3EE", ec=C_DARK, lw=0.55, z=3.5)
    rect(sx(53.5), 34.0, 2.0, 1.65, fc=C_WINDOW, ec=C_DARK, lw=0.5, z=3.55)

    # Trip tank positioned ahead of the main mud-system package
    rect(sx(56.6), 29.3, 1.5, 5.5, fc="#FAFAF8", ec=C_DARK, lw=0.62, z=3.28)
    rect(sx(56.45), 34.8, 1.8, 1.1, fc="#ECEFCD", ec=C_DARK, lw=0.52, z=3.38)
    line([sx(57.35), sx(57.35)], [29.6, 34.8], lw=0.38, color="#7B7B7B", z=3.45)
    # Three mud tanks with top lids, frames, agitators and sight windows
    tank_xs = [sx(x) for x in (58.7, 62.9, 67.1)]
    for tx0 in tank_xs:
        rect(tx0, 29.3, 3.4, 7.1, fc="#FAFAF8", ec=C_DARK, lw=0.72, z=3.3)
        rect(tx0 - 0.15, 36.4, 3.7, 2.1, fc=C_TANK_YELLOW, ec=C_DARK, lw=0.68, z=3.42)
        line([tx0 + 0.8, tx0 + 0.8], [29.3, 36.4], lw=0.42, color="#8A8A8A", z=3.5)
        line([tx0 + 2.6, tx0 + 2.6], [29.3, 36.4], lw=0.42, color="#8A8A8A", z=3.5)
        rect(tx0 + 1.25, 31.5, 0.9, 1.1, fc=C_WINDOW, ec="#666666", lw=0.38, z=3.55)
        line([tx0 + 1.7, tx0 + 1.7], [36.4, 38.25], lw=0.42, color="#666666", z=3.55)
        circle(tx0 + 1.7, 38.7, 0.34, fc="#C6C9CA", ec=C_DARK, lw=0.38, z=3.60)
    # Interconnecting mud-tank line
    line([sx(58.7), sx(70.5)], [30.2, 30.2], lw=0.58, color="#707070", z=3.56)

    # Mud manifold / flow lines under floor.  Use lighter line weights so the
    # piping reads as equipment detail rather than competing with the rig frame.
    line([sx(56.4), sx(71.4)], [28.4, 28.4], lw=0.72, color="#303030", z=3.62)
    # suction header from tanks to mud-pump skid
    line([sx(57.3), sx(72.5)], [21.5, 21.5], lw=1.10, color="#303030", z=3.62)
    line([sx(64.8), sx(64.8)], [21.5, 28.4], lw=0.88, color="#303030", z=3.62)
    for vx in (58.4, 62.4, 66.4, 70.0):
        circle(sx(vx), 21.5, 0.36, fc="#F2F2EF", ec=C_DARK, lw=0.34, z=3.88)
        line([sx(vx - 0.48), sx(vx + 0.48)], [21.5, 21.5], lw=0.28, color=C_DARK, z=3.92)
    # high-pressure discharge route: pump -> riser -> underside of rig floor -> standpipe
    discharge_riser_x = sx(88.2)
    route_y = 24.0
    line([discharge_riser_x, discharge_riser_x], [6.6, route_y], lw=0.90, color=C_DARK, z=3.64)
    line([discharge_riser_x, stand_x], [route_y, route_y], lw=0.90, color=C_DARK, z=3.64)
    line([stand_x, stand_x], [route_y, 29.3], lw=0.90, color=C_DARK, z=3.64)

    # Right mud-pump skid: base, motor, fluid end and discharge
    rect(sx(71.2), 2.3, 14.6, 8.5, fc="#E4E5E5", ec=C_DARK, lw=0.85, z=3.05)
    rect(sx(72.0), 3.4, 5.0, 5.5, fc="#D7D9DA", ec=C_DARK, lw=0.65, z=3.2)
    for xx in (72.8, 73.7, 74.6, 75.5, 76.4):
        line([sx(xx), sx(xx)], [3.7, 8.6], lw=0.35, color="#8C8F91", z=3.35)
    circle(sx(80.1), 6.55, 3.35, fc="#D9DADB", ec=C_DARK, lw=0.82, z=3.35)
    circle(sx(80.1), 6.55, 1.32, fc="white", ec=C_DARK, lw=0.62, z=3.45)
    rect(sx(83.25), 5.0, 1.65, 3.1, fc="#BABDBF", ec=C_DARK, lw=0.55, z=3.5)
    circle(sx(84.1), 9.0, 0.72, fc="#ECECEA", ec=C_DARK, lw=0.45, z=3.55)
    line([sx(84.9), sx(88.2)], [6.6, 6.6], lw=1.05, color=C_DARK, z=3.65)

    # Small equipment platform / discharge stand
    rect(sx(86.4), 2.3, 8.8, 2.0, fc=C_DECK, ec=C_DARK, lw=0.68, z=2.9)
    line([sx(87.4), sx(87.4)], [4.3, 13.0], lw=0.65, color=C_STEEL, z=3.0)
    line([sx(94.0), sx(94.0)], [4.3, 13.0], lw=0.65, color=C_STEEL, z=3.0)
    line([sx(87.4), sx(94.0)], [13.0, 13.0], lw=0.65, color=C_STEEL, z=3.0)
    x_brace(sx(87.4), sx(94.0), 4.3, 13.0, lw=0.48, color=C_STEEL_LIGHT, z=2.9)
    # Small utility / generator skid behind the pump package for realistic surface context
    rect(sx(89.4), 3.1, 5.2, 5.6, fc="#F0F1F0", ec=C_DARK, lw=0.52, z=3.05)
    rect(sx(89.9), 4.0, 2.4, 3.8, fc="#D7DADB", ec=C_DARK, lw=0.38, z=3.12)
    line([sx(92.7), sx(93.9)], [6.0, 6.0], lw=0.54, color=C_DARK, z=3.16)
    circle(sx(94.25), 6.0, 0.45, fc="#ECECEA", ec=C_DARK, lw=0.34, z=3.18)


# =========================================================================================
# 6. RIGHT-COLUMN LABEL COLLECTOR & STACKER
# =========================================================================================
def _collect_labels(data: dict, open_holes: List[dict]) -> List[dict]:
    """Contract labels only; custom legacy highlight/arrow semantics are intentionally ignored."""
    reqs: List[dict] = []
    for c in data.get("casings", []):
        top, shoe = float(c["top_md"]), float(c["shoe_md"])
        stype = c["type"]
        size = format_api_size(c["size_in"])
        if stype == "casing":
            reqs.append({"depth": shoe, "text": f"{size} CSG @ {_fmt_depth(shoe)} m"})
        elif stype == "liner":
            reqs.append({"depth": top, "text": f"{size} LNR Lap @ {_fmt_depth(top)} m"})
            reqs.append({"depth": shoe, "text": f"{size} LNR Shoe @ {_fmt_depth(shoe)} m"})
        elif stype == "tieback":
            reqs.append({"depth": top, "text": f"{size} TB LNR Lap @ {_fmt_depth(top)} m"})
            reqs.append({"depth": shoe, "text": f"{size} TB LNR Shoe @ {_fmt_depth(shoe)} m"})

    for oh in open_holes:
        bot = float(oh["bottom_md"])
        size = format_api_size(oh["hole_size_in"])
        reqs.append({"depth": bot, "text": f"OPEN HOLE {size} @ {_fmt_depth(bot)} m"})

    for p in data.get("cement_plugs", []):
        top, bot = float(p["top_md"]), float(p["bottom_md"])
        reqs.append({"depth": 0.5 * (top + bot),
                     "text": f"CMT PLUG @ {_fmt_depth(top)}–{_fmt_depth(bot)} m"})

    for bore in data.get("plug_bores", []):
        top, bottom = float(bore["top_md"]), float(bore["bottom_md"])
        reqs.append({"depth": (top + bottom) / 2,
                     "text": f"Bore {format_api_size(bore['diameter_in'])} @ {_fmt_depth(top)}–{_fmt_depth(bottom)} m"})

    for sq in data.get("squeezes", []):
        d = float(sq["depth_m"])
        if sq.get("wall_diameter_in") is not None:
            reqs.append({"depth": d, "text": f"Wall {format_api_size(sq['wall_diameter_in'])}"})
            text = f"CMT SQUEEZE @ {_fmt_depth(d)} m"
        elif sq.get("open_hole_index") is not None:
            text = f"CMT SQUEEZE @ {_fmt_depth(d)} m"
        else:
            target = data["casings"][sq["target_index"]]
            size = format_api_size(target["size_in"])
            prefix = {"casing": "CSG", "liner": "LNR", "tieback": "TB LNR"}[target["type"]]
            if sq["target_kind"] == "lap":
                text = f"{size} {prefix} Lap Squeeze @ {_fmt_depth(d)} m"
            elif sq["target_kind"] == "shoe":
                text = f"{size} {prefix} Shoe Squeeze @ {_fmt_depth(d)} m"
            else:
                text = f"{size} {prefix} Squeeze @ {_fmt_depth(d)} m"
        reqs.append({"depth": d, "text": text})

    reqs.sort(key=lambda r: r["depth"])
    return reqs


def _stack_label_positions(reqs: List[dict], y_max: float, col_h_in: float,
                           y_body_top: float, pt: float = LABEL_PT) -> List[float]:
    """Pack labels with minimum displacement while preserving exact depth anchors.

    Labels are grouped into collision clusters and spread symmetrically around their
    requested depth instead of being pushed progressively downward.  Displacement is a
    presentation-only collision-avoidance measure; no leader lines are drawn.
    """
    if not reqs:
        return []
    gap = _LABEL_MIN_GAP_FACTOR * (pt / 72.0) / col_h_in
    pad = gap * _LABEL_EDGE_PAD_FACTOR
    ceiling, floor = y_body_top - pad, pad
    ideal = [y_body_top * (1.0 - r["depth"] / y_max) for r in reqs]

    # Build and iteratively merge clusters until every neighboring cluster has >= gap.
    clusters = [[i] for i in range(len(ideal))]
    while True:
        placed = []
        for cluster in clusters:
            n = len(cluster)
            if (n - 1) * gap > (ceiling - floor) + 1e-12:
                raise ValueError("label density exceeds the available label-column height")
            center = sum(ideal[i] for i in cluster) / n
            top = center + 0.5 * (n - 1) * gap
            bottom = center - 0.5 * (n - 1) * gap
            shift = 0.0
            if top > ceiling:
                shift -= top - ceiling
            if bottom + shift < floor:
                shift += floor - (bottom + shift)
            placed.append([center + shift + (0.5 * (n - 1) - k) * gap
                           for k in range(n)])

        merge_at = None
        for j in range(len(clusters) - 1):
            if placed[j][-1] - placed[j + 1][0] < gap - 1e-12:
                merge_at = j
                break
        if merge_at is None:
            y = [0.0] * len(ideal)
            for cluster, values in zip(clusters, placed):
                for idx, value in zip(cluster, values):
                    y[idx] = value
            return y
        clusters[merge_at] = clusters[merge_at] + clusters[merge_at + 1]
        del clusters[merge_at + 1]


# =========================================================================================
# 7. GEOMETRY & HATCHING HELPERS
# =========================================================================================
def layout_geometry() -> dict:
    table_top = 1.0 - RIG_BAND_FRACTION
    return {
        "fig_size_in": FIG_SIZE_IN,
        "rig_rect": (0.025, table_top, 0.95, RIG_BAND_FRACTION - 0.005),
        "table_rect": (0.025, 0.012, 0.95, table_top - 0.012),
        "header_frac": 0.064,
        "col_frac": COLUMN_FRACTIONS,
    }


def _clip_segment(a, b, x0, x1, y0, y1):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    if t0 >= t1:
        return None
    return ((a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy))


def _hatch_band(ax, x0: float, x1: float, y0: float, y1: float, spacing: float,
                lw: float = 0.65):
    if x1 <= x0 or y1 <= y0:
        return
    span = (x1 - x0) + (y1 - y0)
    n = int(span / spacing) + 2
    for i in range(n):
        s = i * spacing
        pts = _clip_segment((x0 + s, y0), (x0, y0 + s), x0, x1, y0, y1)
        if pts:
            ax.add_line(Line2D([pts[0][0], pts[1][0]], [pts[0][1], pts[1][1]],
                               color=C_HATCH, lw=lw, solid_capstyle="butt", zorder=2.4))


def _png_force_phys_unit(blob: bytes, dpi: float) -> bytes:
    ppm = int(round(dpi / 0.0254))
    payload = struct.pack(">IIB", ppm, ppm, 1)
    crc = zlib.crc32(b"pHYs" + payload) & 0xFFFFFFFF
    phys_chunk = struct.pack(">I", 9) + b"pHYs" + payload + struct.pack(">I", crc)
    has_phys = False
    off = 8
    while off + 8 <= len(blob):
        ln = struct.unpack(">I", blob[off:off + 4])[0]
        if blob[off + 4:off + 8] == b"pHYs":
            has_phys = True
            break
        off += 12 + ln
    out = bytearray(blob[:8])
    off = 8
    done = False
    while off + 8 <= len(blob):
        ln = struct.unpack(">I", blob[off:off + 4])[0]
        ct = blob[off + 4:off + 8]
        total = 12 + ln
        if ct == b"pHYs":
            out += phys_chunk
            done = True
        else:
            out += blob[off:off + total]
            if ct == b"IHDR" and not done and not has_phys:
                out += phys_chunk
                done = True
        off += total
    return bytes(out)


# =========================================================================================
# 8. MAIN RENDERER
# =========================================================================================
def render_well_schematic(schematic_data: dict,
                          output_png_path: str = "well_schematic.png",
                          dpi: int = 300,
                          strict: bool = True) -> str:
    """Render the schematic.

    Every explicitly supplied well-geometry hardware item is drawn. Open holes are never clipped
    to the current shoe and the legacy ``active`` flag does not control rendering. Current job,
    hosts, tie-back landing, plug bounds and squeeze target/depth must be explicit.

    strict=True (default): inconsistent or unresolved geometry raises ValueError. strict=False
    only downgrades consistency findings; missing authority still fails validation."""
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not math.isfinite(float(dpi)) or float(dpi) <= 0:
        raise ValueError("dpi must be a finite positive number")
    if not isinstance(strict, bool):
        raise ValueError("strict must be true or false")
    data = copy.deepcopy(schematic_data)
    validate_schematic_data(data)
    for i, c in enumerate(data.get("casings", [])):
        c.setdefault("top_md", 0.0)
        c.setdefault("name", f"{format_api_size(c['size_in'])} {c['type'].upper()}")
    for i, p in enumerate(data.get("cement_plugs", []), 1):
        p.setdefault("name", "CMT PLUG")

    findings = check_well_design(data)
    if strict and findings:
        raise ValueError("well design is not physically consistent:\n  - " + "\n  - ".join(findings))
    for msg in findings:
        warnings.warn("well design: " + msg, stacklevel=2)
    open_holes = _prepare_open_holes(data["open_holes"], data["casings"])
    data["open_holes"] = open_holes

    y_max, milestones = resolve_depth_axis(data)
    geo = layout_geometry()
    fig_w, fig_h = geo["fig_size_in"]

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor="white")
    try:

        # 1. Authentic CemCADE Rig Header
        rx, ry, rw, rh = geo["rig_rect"]
        ax_rig = fig.add_axes([rx, ry, rw, rh])
        _draw_rig(ax_rig)

        # 2. Three-Column CemCADE Table
        tx, ty, tw, th = geo["table_rect"]
        ax = fig.add_axes([tx, ty, tw, th])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        hf = geo["header_frac"]
        c1, c2, c3 = geo["col_frac"]
        schematic_right = data.get("column_layout") == "schematic_right"

        ax.add_patch(Rectangle((0, 1 - hf), 1, hf, facecolor=C_HEADER_BLUE,
                               edgecolor="none", zorder=2))
        xs = [c1, c1 + c2]
        for x in xs:
            ax.add_line(Line2D([x, x], [0, 1], color="#1A1A1A", lw=0.95, zorder=3.7))
        ax.add_patch(Rectangle((0, 0), 1, 1, facecolor="none", edgecolor="black",
                               linewidth=1.1, zorder=4))
        ax.add_line(Line2D([0, 1], [1 - hf, 1 - hf], color="black", lw=1.0, zorder=3.8))

        titles = ([("Depth(m)", c1 * 0.5),
                   ("Casing Size/Depth(m)", c1 + c2 * 0.5),
                   ("Well Schematic", c1 + c2 + c3 * 0.5)] if schematic_right else
                  [("Depth(m)", c1 * 0.5),
                   ("Well Schematic", c1 + c2 * 0.5),
                   ("Casing Size/Depth(m)", c1 + c2 + c3 * 0.5)])
        for text, xc in titles:
            ax.text(xc, 1 - hf * 0.5, text, ha="center", va="center",
                    fontsize=HEADER_PT, fontweight="bold", color="white",
                    family=FONT_FAMILY, zorder=3.9)

        if schematic_right:
            sch_x0, sch_w = c1 + c2, c3
            lbl_x0, lbl_w = c1, c2
        else:
            sch_x0, sch_w = c1, c2
            lbl_x0, lbl_w = c1 + c2, c3
        col_span = sch_w
        body_y0, body_h = 0.0, 1.0 - hf

        pipe_map, oh_map = _build_radial_maps(data, open_holes, col_span)

        def hw_pipe(sz: float) -> float:
            return pipe_map.get(round(float(sz), 4), 0.15 * col_span)

        def hw_oh(sz: float) -> float:
            return oh_map.get(round(float(sz), 4), 0.22 * col_span)

        def dx(x_col):
            return sch_x0 + x_col * sch_w

        def yd(depth):
            return body_y0 + body_h * (1.0 - float(depth) / y_max)

        # 3. Open Holes + 45-degree Rock Hatching
        deepest_oh_bot = max((float(oh["bottom_md"]) for oh in open_holes), default=-1.0)
        for oh in sorted(open_holes, key=lambda o: -float(o.get("hole_size_in", 8.5))):
            top, bot = float(oh["top_md"]), float(oh["bottom_md"])
            hw = (hw_pipe(float(oh["_host_od"])) - 0.00675) if oh.get("_host_od") is not None else hw_oh(float(oh.get("hole_size_in", 8.5)))
            y_top, y_bot = yd(top), yd(bot)
            bw = 0.042
            bh = 0.011 * body_h
            spacing = 0.010 * col_span
            for sgn in (-1, 1):
                x_wall = dx(0.5 + sgn * hw)
                x_out = dx(0.5 + sgn * (hw + bw))
                xa, xb = min(x_wall, x_out), max(x_wall, x_out)
                _hatch_band(ax, xa, xb, y_bot, y_top, spacing)
                ax.add_line(Line2D([x_wall, x_wall], [y_bot, y_top], color=C_HATCH,
                                   lw=0.85, zorder=2.5))
            if abs(bot - deepest_oh_bot) < 1e-6:
                fh0 = max(0.0, y_bot - bh) if y_bot > bh else 0.0
                fh1 = y_bot if y_bot > bh else min(bh, y_bot)
                if fh1 > fh0:
                    _hatch_band(ax, dx(0.5 - hw), dx(0.5 + hw), fh0, fh1, spacing)
                ax.add_line(Line2D([dx(0.5 - hw), dx(0.5 + hw)], [y_bot, y_bot],
                                   color=C_HATCH, lw=0.85, zorder=2.5))

        # 4. Casing, Liner & Tie-back Strings
        strings = sorted(data.get("casings", []),
                         key=lambda c: (-float(c["size_in"]), 0 if c.get("type") != "tieback" else 1))
        bar_w = 0.0135 * col_span
        fw, fh = 0.020 * col_span, 0.014 * body_h

        for c in strings:
            top, shoe = float(c["top_md"]), float(c["shoe_md"])
            stype = c.get("type", "casing")
            hw = hw_pipe(float(c["size_in"]))

            for sgn in (-1, 1):
                xw = dx(0.5 + sgn * hw)
                ax.add_patch(Rectangle((xw - bar_w / 2, yd(shoe)), bar_w,
                                       yd(top) - yd(shoe), facecolor=C_TUBULAR_FILL,
                                       edgecolor=C_TUBULAR_EDGE, linewidth=0.9, zorder=3.0))

            # Tie-back connection is explicit; CSG/LNR keep the shoe flare.
            if stype != "tieback":
                for sgn in (-1, 1):
                    xw_outer = dx(0.5 + sgn * hw) + sgn * (bar_w / 2)
                    tri = Polygon([(xw_outer, yd(shoe)),
                                   (xw_outer + sgn * fw, yd(shoe)),
                                   (xw_outer, yd(shoe) + fh)], closed=True,
                                  facecolor="black", edgecolor="black", lw=0.5, zorder=3.2)
                    ax.add_patch(tri)
            else:
                _explicit_landing_liner(data, c)  # validation/authority guard; no false shoe flare

            # LNR / TB LNR lap collar is part of the string, using only the explicit host.
            if stype in ("liner", "tieback") and top > 0.0:
                host = _explicit_host(data, c)
                host_hw = hw_pipe(float(host["size_in"]))
                hh = 0.0085 * body_h
                for sgn in (-1, 1):
                    xa = dx(0.5 + sgn * hw) + sgn * (bar_w / 2)
                    xb = dx(0.5 + sgn * host_hw) - sgn * (bar_w / 2)
                    rx0, rw0 = min(xa, xb), abs(xb - xa)
                    ax.add_patch(Rectangle((rx0, yd(top) - hh), rw0, hh,
                                           facecolor=C_COLLAR_FILL, edgecolor="none", zorder=3.15))

        # 5. Seamless Stepped (T-Shaped) or Rectangular Cement Plugs at ANY Depth
        def _bore_half_span_axes(d_mid: float) -> float:
            covering_pipes = [c for c in data.get("casings", [])
                              if float(c["top_md"]) <= d_mid <= float(c["shoe_md"])]
            if covering_pipes:
                innermost = min(covering_pipes, key=lambda c: float(c["size_in"]))
                return (dx(0.5 + hw_pipe(float(innermost["size_in"]))) - bar_w * 0.5) - dx(0.5)
            covering_ohs = [oh for oh in open_holes
                            if float(oh["top_md"]) <= d_mid <= float(oh["bottom_md"])]
            if covering_ohs:
                innermost_oh = min(covering_ohs, key=lambda o: float(o.get("hole_size_in", 8.5)))
                return dx(0.5 + hw_oh(float(innermost_oh.get("hole_size_in", 8.5)))) - dx(0.5)
            bores = [b for b in data.get("plug_bores", []) if b["top_md"] <= d_mid <= b["bottom_md"]]
            if len(bores) == 1:
                return dx(0.5 + hw_oh(bores[0]["diameter_in"])) - dx(0.5)
            raise ValueError(f"cement plug bore geometry is unresolved at {d_mid:g} m")

        for p in data.get("cement_plugs", []):
            top, bot = float(p["top_md"]), float(p["bottom_md"])
            # Split at any liner top OR casing shoe inside (top, bot) to build a single unified polygon
            transitions = sorted({top, bot} | {
                float(c["shoe_md"]) for c in data.get("casings", []) if top < float(c["shoe_md"]) < bot
            } | {
                float(c["top_md"]) for c in data.get("casings", []) if top < float(c["top_md"]) < bot
            } | {
                float(o["top_md"]) for o in open_holes if top < float(o["top_md"]) < bot
            } | {
                float(o["bottom_md"]) for o in open_holes if top < float(o["bottom_md"]) < bot
            } | {
                float(b[k]) for b in data.get("plug_bores", []) for k in ("top_md", "bottom_md") if top < float(b[k]) < bot
            })
            cx = dx(0.5)
            right_pts = []
            left_pts = []
            for s0, s1 in zip(transitions[:-1], transitions[1:]):
                w_half = _bore_half_span_axes(0.5 * (s0 + s1))
                y0, y1 = yd(s0), yd(s1)
                right_pts.extend([(cx + w_half, y0), (cx + w_half, y1)])
                left_pts.extend([(cx - w_half, y0), (cx - w_half, y1)])
            poly_pts = right_pts + list(reversed(left_pts))
            ax.add_patch(Polygon(poly_pts, closed=True, facecolor=C_PLUG_FILL,
                                 edgecolor="#4A4A4A", linewidth=0.55, zorder=3.28))

        # 6. Point-Based CMT SQUEEZE — cement behind the explicitly selected string/open-hole wall
        squeeze_h = 0.018 * body_h
        squeeze_w = 0.020 * col_span
        for sq in data.get("squeezes", []):
            d = float(sq["depth_m"])
            y0 = yd(d) - squeeze_h * 0.5
            kind = sq["target_kind"]

            if sq.get("wall_diameter_in") is not None:
                # A location-only operation marker asserts no unknown structural wall type.
                wall_hw = hw_oh(sq["wall_diameter_in"])
                for sgn in (-1, 1):
                    x_wall = dx(0.5 + sgn * wall_hw)
                    x0 = x_wall if sgn > 0 else x_wall - squeeze_w
                    ax.add_patch(Rectangle((x0, y0), squeeze_w, squeeze_h,
                                           facecolor=C_SQUEEZE_CEM, edgecolor="black", lw=0.7, zorder=3.25))
                continue

            if sq.get("open_hole_index") is not None:
                target_oh = open_holes[sq["open_hole_index"]]
                oh_hw = ((hw_pipe(float(target_oh["_host_od"])) - 0.00675)
                         if target_oh.get("_host_od") is not None
                         else hw_oh(float(target_oh["hole_size_in"])))
                for sgn in (-1, 1):
                    x_wall = dx(0.5 + sgn * oh_hw)
                    x0 = x_wall if sgn > 0 else x_wall - squeeze_w
                    ax.add_patch(Rectangle((x0, y0), squeeze_w, squeeze_h,
                                           facecolor=C_SQUEEZE_CEM, edgecolor="black", lw=0.7, zorder=3.25))
                continue

            target = data["casings"][sq["target_index"]]
            target_hw = hw_pipe(float(target["size_in"]))
            if kind == "lap":
                host = _explicit_host(data, target)
                host_hw = hw_pipe(float(host["size_in"]))
                for sgn in (-1, 1):
                    inner_edge = dx(0.5 + sgn * target_hw) + sgn * (bar_w / 2)
                    outer_edge = dx(0.5 + sgn * host_hw) - sgn * (bar_w / 2)
                    x0, width = min(inner_edge, outer_edge), abs(outer_edge - inner_edge)
                    if width <= 0:
                        raise ValueError(f"squeeze annulus is unresolved at {d:g} m")
                    ax.add_patch(Rectangle((x0, y0), width, squeeze_h,
                                           facecolor=C_SQUEEZE_CEM, edgecolor="black", lw=0.7, zorder=3.25))
            else:
                # Shoe or arbitrary point on a string: a short symmetric patch immediately behind pipe.
                for sgn in (-1, 1):
                    x_outer = dx(0.5 + sgn * target_hw) + sgn * (bar_w / 2)
                    x0 = x_outer if sgn > 0 else x_outer - squeeze_w
                    ax.add_patch(Rectangle((x0, y0), squeeze_w, squeeze_h,
                                           facecolor=C_SQUEEZE_CEM, edgecolor="black", lw=0.7, zorder=3.25))

        # 7. Column 1: Automatic Depth Scale (0, Middle, Bottom)
        for m in milestones:
            first = m == milestones[0]
            last = m == milestones[-1]
            va = "top" if first else ("bottom" if last else "center")
            off = -0.010 if first else (0.008 if last else 0.0)
            ax.text(c1 * 0.5, yd(m) + off, f"{m:g}", ha="center", va=va,
                    fontsize=DEPTH_LABEL_PT, color="black", family=FONT_FAMILY, zorder=3.6)

        # 8. Column 3 (or Column 2 in schematic_right): operation-neutral labels.
        # Collision shifts are visual only. No leader lines are drawn.
        reqs = _collect_labels(data, open_holes)
        pos = _stack_label_positions(reqs, y_max, fig_h * th * body_h, body_h)
        text_x0, text_x1 = lbl_x0 + 0.006, lbl_x0 + lbl_w - 0.006
        lbl_center_x = 0.5 * (text_x0 + text_x1)
        renderer = fig.canvas.get_renderer()
        max_w_px = (text_x1 - text_x0) * tw * fig_w * dpi

        for r, y in zip(reqs, pos):
            t = ax.text(lbl_center_x, y, r["text"], ha="center", va="center", fontsize=LABEL_PT,
                        color="black", family=FONT_FAMILY, zorder=3.6)
            w_px = t.get_window_extent(renderer=renderer).width
            if w_px > max_w_px:
                scaled = LABEL_PT * max_w_px / w_px
                t.set_fontsize(max(MIN_LABEL_PT, scaled))
                if scaled < MIN_LABEL_PT and w_px * (MIN_LABEL_PT / LABEL_PT) > max_w_px + LABEL_FIT_TOL_PX:
                    raise ValueError(
                        f'label text does not fit the available column at minimum font size: {r["text"]!r}'
                    )

        out = os.path.abspath(output_png_path)
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        b2 = io.BytesIO()
        with Image.open(buf) as image:
            image.save(b2, format="PNG", dpi=(dpi, dpi))
        with open(out, "wb") as fh:
            fh.write(_png_force_phys_unit(b2.getvalue(), float(dpi)))
        return out
    finally:
        plt.close(fig)


# =========================================================================================
# 9. CONTRACT-VALID STANDALONE PRESETS + FULL MASTER HIERARCHY
# =========================================================================================
_PRESETS: Dict[str, dict] = {
    "casing_20in": {
        "well_name": '20" SURFACE CASING', "show_mid_depth": True,
        "casings": [{"size_in": 20.0, "top_md": 0.0, "shoe_md": 100.0, "type": "casing"}],
        "open_holes": [{"top_md": 0.0, "bottom_md": 100.0, "hole_size_in": 26.0}],
        "current_job": {"type": "casing", "target_index": 0},
    },
    "casing_13_38": {
        "well_name": '13 3/8" INTERMEDIATE CASING', "show_mid_depth": True,
        "casings": [
            {"size_in": 20.0, "top_md": 0.0, "shoe_md": 106.0, "type": "casing"},
            {"size_in": 13.375, "top_md": 0.0, "shoe_md": 1520.0, "type": "casing"},
        ],
        "open_holes": [{"top_md": 106.0, "bottom_md": 1520.0, "hole_size_in": 17.5, "host_index": 0}],
        "current_job": {"type": "casing", "target_index": 1},
    },
    "casing_9_58": {
        "well_name": '9 5/8" PRODUCTION CASING', "show_mid_depth": True,
        "casings": [
            {"size_in": 20.0, "top_md": 0.0, "shoe_md": 106.0, "type": "casing"},
            {"size_in": 13.375, "top_md": 0.0, "shoe_md": 1505.0, "type": "casing"},
            {"size_in": 9.625, "top_md": 0.0, "shoe_md": 3293.0, "type": "casing"},
        ],
        "open_holes": [{"top_md": 1505.0, "bottom_md": 3500.0, "hole_size_in": 12.25, "host_index": 1}],
        "current_job": {"type": "casing", "target_index": 2},
    },
    "liner_4_5in": {
        "well_name": '4 1/2" DUAL LINER', "show_mid_depth": True,
        "casings": [
            {"size_in": 20.0, "top_md": 0.0, "shoe_md": 106.0, "type": "casing"},
            {"size_in": 13.375, "top_md": 0.0, "shoe_md": 1505.0, "type": "casing"},
            {"size_in": 9.625, "top_md": 0.0, "shoe_md": 3282.0, "type": "casing"},
            {"size_in": 7.0, "top_md": 3182.0, "shoe_md": 3841.0, "type": "liner", "host_index": 2},
            {"size_in": 4.5, "top_md": 3741.0, "shoe_md": 4500.0, "type": "liner", "host_index": 3},
        ],
        "open_holes": [{"top_md": 3841.0, "bottom_md": 4500.0, "hole_size_in": 6.0, "host_index": 3}],
        "current_job": {"type": "liner", "target_index": 4},
    },
    "liner_5in": {
        "well_name": '5" LINER INSIDE 7" STRING', "show_mid_depth": True,
        "casings": [
            {"size_in": 7.0, "top_md": 0.0, "shoe_md": 3889.0, "type": "casing"},
            {"size_in": 5.0, "top_md": 3265.0, "shoe_md": 3510.0, "type": "liner", "host_index": 0},
        ],
        "open_holes": [],
        "current_job": {"type": "liner", "target_index": 1},
        "final_relevant_depth_m": 3889.0,
    },
    "squeeze_7in": {
        "well_name": '7" LNR LAP SQUEEZE', "show_mid_depth": True,
        "casings": [
            {"size_in": 20.0, "top_md": 0.0, "shoe_md": 366.0, "type": "casing"},
            {"size_in": 13.375, "top_md": 0.0, "shoe_md": 1677.5, "type": "casing"},
            {"size_in": 9.625, "top_md": 0.0, "shoe_md": 2260.0, "type": "casing"},
            {"size_in": 7.0, "top_md": 2140.0, "shoe_md": 3128.0, "type": "liner", "host_index": 2},
        ],
        "squeezes": [{"depth_m": 2140.0, "target_index": 3, "target_kind": "lap"}],
        "current_job": {"type": "cmt_squeeze", "target_index": 0},
        "final_relevant_depth_m": 3128.0,
    },
    "cmt_plug_lap": {
        "well_name": "CEMENT PLUG ACROSS LNR LAP", "show_mid_depth": True,
        "casings": [
            {"size_in": 20.0, "top_md": 0.0, "shoe_md": 106.0, "type": "casing"},
            {"size_in": 13.375, "top_md": 0.0, "shoe_md": 1505.0, "type": "casing"},
            {"size_in": 9.625, "top_md": 0.0, "shoe_md": 3282.0, "type": "casing"},
            {"size_in": 7.0, "top_md": 3150.0, "shoe_md": 3841.0, "type": "liner", "host_index": 2},
        ],
        "cement_plugs": [{"top_md": 2800.0, "bottom_md": 3350.0}],
        "current_job": {"type": "cmt_plug", "target_index": 0},
        "final_relevant_depth_m": 3841.0,
    },
    "tieback_7in": {
        "well_name": '7" TIE BACK LINER', "show_mid_depth": True,
        "casings": [
            {"size_in": 20.0, "top_md": 0.0, "shoe_md": 159.0, "type": "casing"},
            {"size_in": 13.375, "top_md": 0.0, "shoe_md": 1534.0, "type": "casing"},
            {"size_in": 9.625, "top_md": 0.0, "shoe_md": 2937.0, "type": "casing"},
            {"size_in": 7.0, "top_md": 2816.0, "shoe_md": 3278.0, "type": "liner", "host_index": 2},
            {"size_in": 7.0, "top_md": 1200.0, "shoe_md": 2816.0, "type": "tieback",
             "host_index": 2, "landing_liner_index": 3},
        ],
        "current_job": {"type": "tieback", "target_index": 4},
        "final_relevant_depth_m": 3278.0,
    },
    "tieback_5in": {
        "well_name": '5" TIE BACK LINER', "show_mid_depth": True,
        "casings": [
            {"size_in": 20.0, "top_md": 0.0, "shoe_md": 400.0, "type": "casing"},
            {"size_in": 13.375, "top_md": 0.0, "shoe_md": 1500.0, "type": "casing"},
            {"size_in": 9.625, "top_md": 0.0, "shoe_md": 3316.0, "type": "casing"},
            {"size_in": 7.0, "top_md": 3192.0, "shoe_md": 4047.0, "type": "liner", "host_index": 2},
            {"size_in": 5.0, "top_md": 3846.0, "shoe_md": 4411.0, "type": "liner", "host_index": 3},
            {"size_in": 5.0, "top_md": 3696.0, "shoe_md": 3846.0, "type": "tieback",
             "host_index": 3, "landing_liner_index": 4},
        ],
        "current_job": {"type": "tieback", "target_index": 5},
        "final_relevant_depth_m": 4411.0,
    },
    "full_master_well": {
        "well_name": "FULL HIERARCHY MASTER WELL", "show_mid_depth": True,
        "casings": [
            {"size_in": "30", "top_md": 0.0, "shoe_md": 60.0, "type": "casing"},
            {"size_in": "20", "top_md": 0.0, "shoe_md": 320.0, "type": "casing"},
            {"size_in": "18 5/8", "top_md": 0.0, "shoe_md": 850.0, "type": "casing"},
            {"size_in": "13 3/8", "top_md": 0.0, "shoe_md": 1850.0, "type": "casing"},
            {"size_in": "9 5/8", "top_md": 0.0, "shoe_md": 3100.0, "type": "casing"},
            {"size_in": "7", "top_md": 2980.0, "shoe_md": 3850.0, "type": "liner", "host_index": 4},
            {"size_in": "7", "top_md": 1500.0, "shoe_md": 2980.0, "type": "tieback",
             "host_index": 4, "landing_liner_index": 5},
            {"size_in": "5", "top_md": 3730.0, "shoe_md": 4380.0, "type": "liner", "host_index": 5},
            {"size_in": "3 1/2", "top_md": 4280.0, "shoe_md": 4850.0, "type": "liner", "host_index": 7},
        ],
        "open_holes": [
            {"top_md": 3100.0, "bottom_md": 3850.0, "hole_size_in": "8 1/2", "host_index": 4},
            {"top_md": 3850.0, "bottom_md": 4380.0, "hole_size_in": "6 1/8", "host_index": 5},
            {"top_md": 4380.0, "bottom_md": 4950.0, "hole_size_in": "4 1/8", "host_index": 7},
        ],
        "cement_plugs": [{"top_md": 3650.0, "bottom_md": 3800.0}],
        "squeezes": [{"depth_m": 4280.0, "target_index": 8, "target_kind": "lap"}],
        "current_job": {"type": "cmt_squeeze", "target_index": 0},
    },
}

PRESET_NAMES = tuple(_PRESETS.keys())


def get_preset_schematic_data(preset_name: str) -> dict:
    if preset_name == "all":
        return {k: copy.deepcopy(v) for k, v in _PRESETS.items()}
    if preset_name not in _PRESETS:
        raise ValueError(f"unknown preset {preset_name!r}; valid: {', '.join(PRESET_NAMES)}, 'all'")
    return copy.deepcopy(_PRESETS[preset_name])


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="well_schematic_engine.py",
        description="Pixel-Faithful Standalone CemCADE Well Schematic Renderer (v%s)." % __version__)
    ap.add_argument("payload", nargs="?", help="well_schematic_data.json path")
    ap.add_argument("--preset", help="preset name or 'all' (%s)" % ", ".join(PRESET_NAMES))
    ap.add_argument("--out", help="output PNG path")
    ap.add_argument("--outdir", help="output directory (--preset all)")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--lenient", action="store_true",
                    help="only warn (instead of failing) when the well design is physically inconsistent")
    args = ap.parse_args(argv)

    if (args.payload is None) == (args.preset is None):
        ap.error("provide exactly one of: payload.json | --preset NAME")

    if args.preset:
        names = list(PRESET_NAMES) if args.preset == "all" else [args.preset]
        for name in names:
            data = get_preset_schematic_data(name)
            if args.out and len(names) == 1:
                out = args.out
            elif args.outdir:
                out = os.path.join(args.outdir, f"{name}.png")
            else:
                out = f"{name}.png"
            try:
                print(f"rendered {name:<18} -> {render_well_schematic(data, out, dpi=args.dpi, strict=not args.lenient)}")
            except ValueError as exc:
                print(f"error [{name}]: {exc}", file=sys.stderr)
                return 1
        return 0

    try:
        with open(args.payload, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        out = args.out or os.path.splitext(args.payload)[0] + "_schematic.png"
        print(render_well_schematic(raw, out, dpi=args.dpi, strict=not args.lenient))
    except (OSError, ValueError) as exc:   # JSONDecodeError is a ValueError
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
