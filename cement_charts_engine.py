#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cement_charts_engine.py — CemCADE Section IX High-Fidelity Chart & Reporting
Companion Engine (v1.2.9 COMPANION).

Consumes the dictionary output of
``centralizer_optimizer_engine.run_full_analysis(well_data)`` (or
``centralizer_optimizer_engine.compute_standoff_profile`` /
``optimize_placement``) and autonomously generates two coordinated
deliverables:

1. ``pipe_standoff.png``  — pixel-accurate visual replication of the
   CemCADE Section IX "Pipe Standoff" profile chart, with adaptive
   dynamic depth scaling and automatic gridding (NO hardcoded depth
   limits anywhere in this module).
2. ``section_ix_report.md`` — official CemCADE Section IX report tables
   ("Centralizer Data" and "Centralizer Placement") including the
   API 10D footnote:

       NOTE 20: Recommended Centralizer Performance Data is Based on
       API 10D Specifications.

VERSION LOCK
------------
This companion is bound to ``centralizer_optimizer_engine`` v1.2.9
(F5: VALIDATED & CLOSED; internal interface knot quadrature [D9]).
Engine sha256 (v1.2.9 delivery):
    b7c439d027a65345751c5baa612cd19ce7512f745659f1db9ca630ca48468bf9

PUBLIC CONTRACT (stable)
------------------------
::

    render_pipe_standoff_chart(analysis_result, output_png_path, dpi) -> str
    generate_section_ix_markdown(analysis_result, output_md_path)   -> str
    export_full_section_ix_report(well_data_or_result, output_dir,
                                  chart_name, report_name)          -> (str, str)

CLI::

    python cement_charts_engine.py payload.json --outdir ./output
    python cement_charts_engine.py --mock casing --png standoff.png --md report.md

ACCEPTED PAYLOADS (auto-detected)
---------------------------------
A. ``well_data`` input payload        -> has ``survey`` AND ``casing`` dicts;
   ``export_full_section_ix_report`` runs the full v1.2.9 analysis first.
B. ``run_full_analysis`` result dict  -> has ``profile`` / ``table`` /
   ``zones`` / ``centralizer_count``.
C. raw ``optimize_placement`` / ``compute_standoff_profile`` result dict
   -> has ``centralizer_md`` / ``stdf_at`` / ``between_md`` / ``between_stdf``.

KEY RESOLUTION (documented, deterministic)
------------------------------------------
* standoff curve      ``between_md`` / ``between_stdf`` (top level, else
                      ``profile`` sub-dict).  These arrays are the exact
                      legacy CENT_BETW_LOCAT_* trajectory: [string shoe
                      (with weight-cantilever stub sag), span mid-points
                      (shoe-first descending), annulus top (stdf = 1)].
* centralizer nodes   ``centralizer_md`` / ``stdf_at`` (raw result), else
                      ``table[i].md`` / ``table[i].standoff_at``
                      (run_full_analysis).  ``centralizer_md`` is DESCENDING
                      (shoe-first, like the .cfw tables), so
                      ``centralizer_md[-1]`` = shallowest = "Top Cent. MD"
                      and ``centralizer_md[0]`` = deepest = "Bottom Cent. MD".
* casing shoe         ``wellbore.string_shoe`` (if embedded), else
                      ``string_shoe`` / ``_shoe_md`` / ``shoe_md`` keys,
                      else the deepest plotted data extent.  The wrapper
                      injects ``_shoe_md`` when it runs the analysis.
* product kinds       zone ``product_name`` resolved against the products
                      catalogue (``products`` / ``_products`` key); fallback:
                      zone ``kind`` key; fallback: the single catalogue
                      entry when the catalogue holds exactly one product.
* zone min-standoff depth   raw result ``zones_min[i].min_depth``
                      (GetMinStandOff @0x5fc0 official value), else the
                      same rule re-applied over nodes + curve samples
                      inside [top_md - 1e-6, bottom_md + 1e-6] with the
                      engine scan order (descending at-CT, then curve
                      order, strict-less updates, zone bottom fallback).

DEPTH AXIS ALGEBRA (STRICTLY DYNAMIC)
-------------------------------------
``Y_max = ceil_to_clean_interval(wellbore.string_shoe)``::

    ceil_to_clean_interval(x, step) = ceil((1.02 * x) / step) * step

* the 1.02 factor guarantees a clean headroom of at least 2 % of Y_max so
  the shoe never sits exactly on the bottom axis edge (an exactly-clean
  shoe is bumped one full step);
* major step class (adaptive, no hardcoded depth limits)::

      shoe <= 1500 m           -> 200 m   (fallback 250 m)
      1500 < shoe <= 3000 m    -> 500 m
      shoe > 3000 m            -> 500 m   (fallback 1000 m)

* the first step of the class whose major tick count (Y_max/step + 1)
  does not exceed 13 wins; if none qualifies, the last step of the class
  is used (bounded worst case: 14 major labels);
* worked examples: 800 m -> (1000 m, step 200);  1799 m -> (2000 m, 500);
  2566.4 m -> (3000 m, 500);  4197 m -> (4500 m, 500);  12000 m ->
  (13000 m, 1000);
* minor gridlines at major/4 (reference-probed CemCADE density),
  tick marks major+minor point INWARD (``direction='in'``), Y tick labels
  rotated 90 deg reading upwards, unit label ``m`` above the top-left
  corner of the Y axis.

STANDOFF AXIS ALGEBRA
---------------------
* X axis at the TOP of the chart (ticks + labels), unit label ``%``
  centered above it;
* default range [50 %, 150 %] with major ticks [50, 75, 100, 125, 150];
* dynamic expansion to round multiples of 25 %: low end
  ``floor(min/25)*25`` when min < 50, high end ``ceil(max/25)*25`` when
  max > 150 (clamped at 0 %);
* minor gridlines every 12.5 %, top ticks point INWARD.

VISUAL GROUND TRUTH (CemCADE Section IX printout)
--------------------------------------------------
* figure 3.2 x 6.0 inches, DPI >= 300 (default 300);
* plot background light gray  #EFEFEF
* outer spine  solid black    #000000, linewidth 0.8
* gridlines    solid          #C0C0C0, linewidth 0.75
* standoff curve deep red     #C80000, linewidth 1.4
* centralizer nodes dark blue plus markers
                              #000080, marker '+', size 40, linewidth 1.0
* centered bottom title        "Pipe Standoff" (sans-serif, 8.5 pt)
* deterministic fixed axes rectangle (no tight-bbox rescaling) so the
  pixel geometry is reproducible at any DPI.

Everything is SI.  This module never mutates engine results and never
recomputes physics: it only resolves, formats and draws.
"""

import argparse
import json
import math
import os
import sys
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")                     # headless-safe, deterministic
import matplotlib.pyplot as plt           # noqa: E402

__version__ = "1.2.9"
COMPANION_OF = "centralizer_optimizer_engine v1.2.9"
ENGINE_SHA256_V129 = ("b7c439d027a65345751c5baa612cd19ce7512f745659f"
                      "1db9ca630ca48468bf9")

# ===========================================================================
# 1. CEMCADE SECTION IX VISUAL CONSTANTS (reference-probed, non-negotiable)
# ===========================================================================
C_PLOT_BG = "#EFEFEF"        # CemCADE characteristic light gray plot area
C_SPINE = "#000000"          # solid black outer border
C_GRID = "#C0C0C0"           # crisp solid gridlines
C_CURVE = "#C80000"          # deep red continuous standoff trajectory
C_NODE = "#000080"           # dark blue centralizer plus-markers

LW_SPINE = 0.8
LW_GRID = 0.75
LW_CURVE = 1.4
NODE_SIZE = 40               # scatter markersize (pt^2)
NODE_LW = 1.0

FIGSIZE = (3.2, 6.0)         # tall vertical Section IX aspect
AX_RECT = (0.175, 0.085, 0.785, 0.855)   # deterministic axes rectangle
FONT_TITLE = 8.5             # "Pipe Standoff" bottom title
FONT_AXIS = 8.0              # 'm' and '%' unit labels
FONT_TICK = 7.0              # tick labels
TICK_LEN_MAJOR = 3.2
TICK_LEN_MINOR = 1.8

_MAJOR_TICK_CAP = 13         # max major Y labels before step fallback

_TITLE_TEXT = "Pipe Standoff"
_NOTE20 = ("NOTE 20: Recommended Centralizer Performance Data is Based "
           "on API 10D Specifications.")


# ===========================================================================
# 2. AXIS ALGEBRA — strictly dynamic, zero hardcoded depth limits
# ===========================================================================
def ceil_to_clean_interval(x: float, step: float) -> float:
    """Smallest clean multiple of ``step`` >= ``x`` with >= 2 % headroom.

    ``ceil((1.02 * x) / step) * step`` — the 1.02 factor is the "clean
    headroom" contract: the shoe never sits exactly on the bottom edge,
    and an exactly-clean shoe value is bumped one full step.
    """
    return math.ceil((1.02 * float(x)) / float(step) - 1e-12) * float(step)


def depth_axis_spec(shoe: float) -> Tuple[float, float, float]:
    """Return ``(y_max, major_step, minor_step)`` for a string shoe depth.

    Adaptive major interval classes (mission 3.1)::

        shoe <= 1500           -> (200, 250)
        1500 < shoe <= 3000    -> (500,)
        shoe > 3000            -> (500, 1000)

    First step whose label count (Y_max/step + 1) <= 13 wins; otherwise
    the class' last step is accepted (bounded 14-label worst case).
    Minor step = major / 4 (CemCADE reference grid density).
    """
    shoe = float(shoe)
    if shoe <= 1500.0:
        steps: Tuple[float, ...] = (200.0, 250.0)
    elif shoe <= 3000.0:
        steps = (500.0,)
    else:
        steps = (500.0, 1000.0)
    y_max = major = None
    for st in steps:
        cand = ceil_to_clean_interval(shoe, st)
        n_labels = int(round(cand / st)) + 1
        if n_labels <= _MAJOR_TICK_CAP:
            y_max, major = cand, st
            break
    if y_max is None:
        major = steps[-1]
        y_max = ceil_to_clean_interval(shoe, major)
    return y_max, major, major / 4.0


def standoff_axis_spec(pcts: Optional[List[float]]) -> Tuple[float, float,
                                                              float, float]:
    """Return ``(x_min, x_max, major, minor)`` for standoff percentages.

    Default [50, 150]; expands to round multiples of 25 % when the data
    drops below 50 % or exceeds 150 %.  Minor gridlines every 12.5 %.
    """
    lo, hi = 50.0, 150.0
    if pcts:
        mn, mx = min(pcts), max(pcts)
        if mn < lo:
            lo = math.floor(mn / 25.0) * 25.0
        if mx > hi:
            hi = math.ceil(mx / 25.0) * 25.0
    lo = max(lo, 0.0)
    if hi <= lo:
        hi = lo + 25.0
    return lo, hi, 25.0, 12.5


# ===========================================================================
# 3. VIEW MODEL — resolve any accepted payload into one canonical dict
# ===========================================================================
def _is_well_data(payload: dict) -> bool:
    """True when ``payload`` is a well_data input (not an analysis result)."""
    return (isinstance(payload.get("survey"), dict)
            and isinstance(payload.get("casing"), dict))


def _resolve_curve(res: dict) -> Tuple[List[float], List[float]]:
    """between_md / between_stdf: top level, else ``profile`` sub-dict."""
    prof = res.get("profile") or {}
    md = res.get("between_md")
    sd = res.get("between_stdf")
    if md is None or sd is None:
        md = prof.get("between_md")
        sd = prof.get("between_stdf")
    md = list(md or [])
    sd = list(sd or [])
    if len(md) != len(sd):
        raise ValueError("between_md / between_stdf length mismatch: "
                         f"{len(md)} vs {len(sd)}")
    return md, sd


def _resolve_nodes(res: dict) -> Tuple[List[float], List[float]]:
    """centralizer_md / stdf_at, else table rows (md, standoff_at)."""
    md = res.get("centralizer_md")
    sd = res.get("stdf_at")
    if md is None or sd is None or len(md) != len(sd):
        rows = res.get("table") or []
        md = [float(r["md"]) for r in rows]
        sd = [float(r["standoff_at"]) for r in rows]
    return list(md), list(sd)


def _resolve_shoe(res: dict, curve_md: List[float],
                  node_md: List[float]) -> float:
    """wellbore.string_shoe -> embedded keys -> deepest plotted extent."""
    wb = res.get("wellbore")
    if isinstance(wb, dict) and wb.get("string_shoe") is not None:
        return float(wb["string_shoe"])
    for k in ("string_shoe", "_shoe_md", "shoe_md"):
        if res.get(k) is not None:
            return float(res[k])
    ext = [m for m in (curve_md + node_md) if m is not None]
    if not ext:
        raise ValueError("cannot resolve depth axis: no shoe and no data")
    return max(ext)


def _resolve_products(res: dict) -> List[dict]:
    for k in ("products", "_products"):
        v = res.get(k)
        if isinstance(v, list) and v:
            return v
    return []


_KIND_DISPLAY = {"rigid": "Rigid", "spring": "Spring"}


def _zone_kind(z: dict, name2kind: Dict[str, str]) -> Optional[str]:
    """Resolve a zone's centralizer kind ('rigid' | 'spring' | None)."""
    pn = z.get("product_name")
    if pn and pn in name2kind:
        return name2kind[pn]
    if z.get("kind"):
        return str(z["kind"]).strip().lower()
    if len(name2kind) == 1:
        return next(iter(name2kind.values()))
    return None


def _zone_min_depth(res: dict, z: dict, node_md: List[float],
                    node_stdf: List[float], curve_md: List[float],
                    curve_stdf: List[float]) -> float:
    """Depth of the zone minimum standoff (GetMinStandOff @0x5fc0 rule).

    Prefers the official ``zones_min[i].min_depth``; otherwise re-applies
    the engine scan: at-CT samples in stored (descending) order, then
    curve samples in stored order, strict-less updates, start
    best_s = 2.0 / best_d = zone bottom, window [top-1e-6, bottom+1e-6].
    """
    zt, zb = float(z["top_md"]), float(z["bottom_md"])
    zmins = res.get("zones_min") or []
    for zm in zmins:
        if (abs(float(zm.get("top_md", -1e18)) - zt) < 1e-9
                and abs(float(zm.get("bottom_md", -1e18)) - zb) < 1e-9):
            d = zm.get("min_depth")
            if d is not None:
                return float(d)
    best_s, best_d = 2.0, zb
    for md, s in zip(node_md, node_stdf):
        if zt - 1e-6 <= md <= zb + 1e-6 and s < best_s:
            best_s, best_d = s, md
    for md, s in zip(curve_md, curve_stdf):
        if zt - 1e-6 <= md <= zb + 1e-6 and s < best_s:
            best_s, best_d = s, md
    return best_d


def build_view(analysis_result: dict) -> dict:
    """Canonical Section IX view model from any accepted payload.

    Returned keys::

        well_name, job_type, shoe,
        curve_md, curve_pct, node_md, node_pct,
        n_cent, top_cent_md, bottom_cent_md,
        n_rigid, n_spring, kinds_known,
        zone_rows   : [{bottom_md, number, cent_per_joint, kind_display,
                        min_stdf_pct, min_depth}],
        y_max, y_major, y_minor, x_min, x_max, x_major, x_minor
    """
    res = analysis_result or {}
    curve_md, curve_stdf = _resolve_curve(res)
    node_md, node_stdf = _resolve_nodes(res)
    if not curve_md and not node_md:
        raise ValueError("payload carries no standoff curve and no "
                         "centralizer nodes; nothing to render")

    shoe = _resolve_shoe(res, curve_md, node_md)
    curve_pct = [100.0 * float(s) for s in curve_stdf]
    node_pct = [100.0 * float(s) for s in node_stdf]

    name2kind = {}
    for p in _resolve_products(res):
        nm = p.get("name")
        kd = p.get("kind")
        if nm and kd:
            name2kind[str(nm)] = str(kd).strip().lower()

    zones = [z for z in (res.get("zones") or [])
             if isinstance(z, dict) and z.get("bottom_md") is not None]
    zone_rows = []
    n_rigid = n_spring = 0
    kinds_known = bool(name2kind)
    for z in sorted(zones, key=lambda zz: float(zz["bottom_md"])):
        cnt = int(z.get("count") or 0)
        kind = _zone_kind(z, name2kind)
        if cnt:
            if kind == "rigid":
                n_rigid += cnt
            elif kind == "spring":
                n_spring += cnt
            else:
                kinds_known = False
        dens = z.get("density_computed") or z.get("density_design") \
            or z.get("density") or ""
        zone_rows.append({
            "bottom_md": float(z["bottom_md"]),
            "number": cnt,
            "cent_per_joint": str(dens),
            "kind_display": _KIND_DISPLAY.get(kind, "n/a"),
            "min_stdf_pct": 100.0 * float(z.get("min_stdf") or 0.0),
            "min_depth": _zone_min_depth(res, z, node_md, node_stdf,
                                         curve_md, curve_stdf),
        })

    n_cent = len(node_md) or int(res.get("centralizer_count") or 0)
    y_max, y_major, y_minor = depth_axis_spec(shoe)
    x_min, x_max, x_major, x_minor = standoff_axis_spec(curve_pct + node_pct)

    return {
        "well_name": str(res.get("well_name", "")),
        "job_type": str(res.get("job_type", "")),
        "shoe": shoe,
        "curve_md": curve_md,
        "curve_pct": curve_pct,
        "node_md": node_md,
        "node_pct": node_pct,
        "n_cent": n_cent,
        "top_cent_md": min(node_md) if node_md else None,
        "bottom_cent_md": max(node_md) if node_md else None,
        "n_rigid": n_rigid if kinds_known else None,
        "n_spring": n_spring if kinds_known else None,
        "kinds_known": kinds_known,
        "zone_rows": zone_rows,
        "y_max": y_max, "y_major": y_major, "y_minor": y_minor,
        "x_min": x_min, "x_max": x_max,
        "x_major": x_major, "x_minor": x_minor,
    }


# ===========================================================================
# 4. RENDERER — pixel-accurate CemCADE "Pipe Standoff" chart
# ===========================================================================
def render_pipe_standoff_chart(analysis_result: dict,
                               output_png_path: str = "pipe_standoff.png",
                               dpi: int = 300) -> str:
    """Render the CemCADE Section IX Pipe Standoff chart to PNG.

    Pixel-accurate replication of the official printout with dynamic
    depth scaling and adaptive auto-gridding (mission section 3):

    * inverted Y axis: top = 0.0 m, bottom = ceil_to_clean_interval(shoe);
      major ticks per ``depth_axis_spec``, minors at major/4, both
      pointing INWARD, labels rotated 90 deg reading upwards;
    * X axis at the TOP: '%' centered above, default [50, 150] with
      majors [50, 75, 100, 125, 150], dynamic 25 % expansion, inward
      ticks;
    * #EFEFEF plot area, #000000 spines (0.8), #C0C0C0 gridlines (0.75),
      #C80000 standoff curve (1.4), #000080 '+' centralizer nodes
      (size 40, lw 1.0), bottom title "Pipe Standoff" (8.5 pt);
    * fixed axes rectangle (no tight bbox) -> reproducible pixel geometry.

    Returns the absolute path of the written PNG.
    """
    view = build_view(analysis_result)

    fig = plt.figure(figsize=FIGSIZE, dpi=dpi, facecolor="white")
    ax = fig.add_axes(list(AX_RECT))
    ax.set_facecolor(C_PLOT_BG)

    # ---- axis ranges (dynamic; inverted depth) ---------------------------
    ax.set_xlim(view["x_min"], view["x_max"])
    ax.set_ylim(view["y_max"], 0.0)          # top of axis = 0.0 m

    # ---- ticks & grid -----------------------------------------------------
    y_majors = _arange_ticks(0.0, view["y_max"], view["y_major"])
    y_minors = _arange_ticks(0.0, view["y_max"], view["y_minor"])
    x_majors = _arange_ticks(view["x_min"], view["x_max"], view["x_major"])
    x_minors = _arange_ticks(view["x_min"], view["x_max"], view["x_minor"])
    ax.set_xticks(x_majors, minor=False)
    ax.set_xticks(x_minors, minor=True)
    ax.set_yticks(y_majors, minor=False)
    ax.set_yticks(y_minors, minor=True)

    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")
    ax.tick_params(which="major", direction="in",
                   length=TICK_LEN_MAJOR, width=LW_SPINE,
                   top=True, bottom=False, left=True, right=False,
                   labeltop=True, labelbottom=False,
                   labelleft=True, labelright=False,
                   labelsize=FONT_TICK, pad=2.0)
    ax.tick_params(which="minor", direction="in",
                   length=TICK_LEN_MINOR, width=0.6,
                   top=True, bottom=False, left=True, right=False)
    for lbl in ax.get_yticklabels():
        lbl.set_rotation(90)
        lbl.set_rotation_mode("anchor")
        lbl.set_ha("center")
        lbl.set_va("center")

    ax.grid(True, which="major", color=C_GRID, linewidth=LW_GRID,
            linestyle="-")
    ax.grid(True, which="minor", color=C_GRID, linewidth=LW_GRID,
            linestyle="-")
    ax.set_axisbelow(True)

    # ---- spines ------------------------------------------------------------
    for spine in ax.spines.values():
        spine.set_linewidth(LW_SPINE)
        spine.set_edgecolor(C_SPINE)
        spine.set_visible(True)

    # ---- data --------------------------------------------------------------
    if view["curve_md"]:
        ax.plot(view["curve_pct"], view["curve_md"],
                color=C_CURVE, linewidth=LW_CURVE, zorder=3)
    if view["node_md"]:
        ax.scatter(view["node_pct"], view["node_md"], s=NODE_SIZE,
                   c=C_NODE, marker="+", linewidths=NODE_LW, zorder=4)

    # ---- unit labels & title ----------------------------------------------
    ax.set_xlabel("%", fontsize=FONT_AXIS, labelpad=1.5)
    # 'm' above the top-left corner of the Y axis (CemCADE placement)
    ax.text(-0.02, 1.032, "m", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=FONT_AXIS, color="#000000")
    ax.text(0.5, -0.022, _TITLE_TEXT, transform=ax.transAxes,
            ha="center", va="top", fontsize=FONT_TITLE, color="#000000")

    fig.savefig(output_png_path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return os.path.abspath(output_png_path)


def _arange_ticks(lo: float, hi: float, step: float) -> List[float]:
    """Inclusive clean tick lattice [lo, hi] (float-stable)."""
    if step <= 0 or hi < lo:
        return [lo, hi]
    n = int(round((hi - lo) / step))
    return [lo + k * step for k in range(n + 1)]


# ===========================================================================
# 5. SECTION IX MARKDOWN REPORT (official CemCADE tables + NOTE 20)
# ===========================================================================
def _fmt_md_val(v: Optional[float]) -> str:
    """Section IX depth/standoff formatting: one decimal (CemCADE printout)."""
    return "n/a" if v is None else f"{v:.1f}"


def generate_section_ix_markdown(analysis_result: dict,
                                 output_md_path: Optional[str] =
                                 "section_ix_report.md") -> str:
    """Generate the Section IX Markdown report and return its full text.

    Layout replicates the official CemCADE printout (visual ground
    truth, Table.docx + Note 20):

    * **Centralizer Data** — 4-column summary: Top Cent. MD /
      Bottom Cent. MD / Casing Shoe paired with NB of Cent. Used /
      NB of Rigid Cent. Used / NB of Spring Cent. Used;
    * **Centralizer Placement** — 6-column zone table: Bottom MD (m),
      Number, Cent. / Joint, Centralizer Type, Min. Standoff (%),
      Depth (m) — rows sorted by increasing Bottom MD, ``Depth (m)`` is
      the depth of the zone minimum standoff (NOT necessarily the zone
      bottom);
    * the API 10D footnote (NOTE 20) and the chart embed link.

    Every number is rendered from the engine floats through the
    documented formatters (``%.1f`` for MD / standoff %, integer for
    counts) so third-party tooling can verify bit-identical fidelity.
    """
    view = build_view(analysis_result)

    def kv(label: str, val: str) -> str:
        return f"| {label} | {val} |"

    top_md = _fmt_md_val(view["top_cent_md"])
    bot_md = _fmt_md_val(view["bottom_cent_md"])
    shoe = _fmt_md_val(view["shoe"])
    n_tot = str(view["n_cent"]) if view["n_cent"] else "0"
    n_rig = str(view["n_rigid"]) if view["n_rigid"] is not None else "n/a"
    n_spr = str(view["n_spring"]) if view["n_spring"] is not None else "n/a"

    lines: List[str] = []
    lines.append("<!-- CemCADE Section IX report — generated by "
                 f"cement_charts_engine v{__version__} "
                 f"(companion of {COMPANION_OF}) -->")
    lines.append("")
    lines.append("# Section IX — Centralizer Report")
    lines.append("")
    meta = [f"**Well:** {view['well_name'] or 'n/a'}",
            f"**Job Type:** {view['job_type'] or 'n/a'}"]
    lines.append("  ".join(meta))
    lines.append("")
    lines.append("## Centralizer Data")
    lines.append("")
    lines.append("| | | | |")
    lines.append("|---|---|---|---|")
    lines.append(kv("Top Cent. MD", f"{top_md} m")[:-1]
                 + f"| NB of Cent. Used | {n_tot} |")
    lines.append(kv("Bottom Cent. MD", f"{bot_md} m")[:-1]
                 + f"| NB of Rigid Cent. Used | {n_rig} |")
    lines.append(kv("Casing Shoe", f"{shoe} m")[:-1]
                 + f"| NB of Spring Cent. Used | {n_spr} |")
    lines.append("")
    lines.append("## Centralizer Placement")
    lines.append("")
    lines.append("| Bottom MD (m) | Number | Cent. / Joint | Centralizer Type"
                 " | Min. Standoff (%) | Depth (m) |")
    lines.append("|---|---|---|---|---|---|")
    for zr in view["zone_rows"]:
        lines.append(
            f"| {_fmt_md_val(zr['bottom_md'])} | {zr['number']} "
            f"| {zr['cent_per_joint']} | {zr['kind_display']} "
            f"| {_fmt_md_val(zr['min_stdf_pct'])} "
            f"| {_fmt_md_val(zr['min_depth'])} |")
    lines.append("")
    lines.append(_NOTE20)
    lines.append("")
    lines.append("![Pipe Standoff](pipe_standoff.png)")
    lines.append("")

    text = "\n".join(lines)
    if output_md_path:
        with open(output_md_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return text


# ===========================================================================
# 6. END-TO-END WRAPPER
# ===========================================================================
def _import_optimizer_engine():
    """Locate and import centralizer_optimizer_engine (same dir first)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (here, os.getcwd()):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import centralizer_optimizer_engine as eng  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - defensive
        raise ImportError(
            "centralizer_optimizer_engine.py (v1.2.9) must be importable "
            "next to cement_charts_engine.py or on PYTHONPATH") from exc
    if getattr(eng, "__version__", "") != __version__:
        sys.stderr.write(
            f"[cement_charts_engine] WARNING: engine version "
            f"{getattr(eng, '__version__', '?')} != companion {__version__}"
            "\n")
    return eng


def export_full_section_ix_report(well_data_or_result: dict,
                                  output_dir: str = ".",
                                  chart_name: str = "pipe_standoff.png",
                                  report_name: str = "section_ix_report.md"
                                  ) -> Tuple[str, str]:
    """End-to-end Section IX export: (png_path, md_path).

    If a ``well_data`` payload is provided (``survey`` + ``casing``
    dicts present), the v1.2.9 ``run_full_analysis`` is executed first
    and the result is enriched with the private ``_shoe_md`` /
    ``_products`` keys so the chart and tables are fully self-sufficient.
    Otherwise the pre-calculated result is consumed as-is
    (run_full_analysis dict, raw optimize_placement result, or
    compute_standoff_profile result — all auto-detected).
    """
    payload = well_data_or_result
    if _is_well_data(payload):
        eng = _import_optimizer_engine()
        res = eng.run_full_analysis(payload)
        wb = payload.get("wellbore") or {}
        if wb.get("string_shoe") is not None:
            res["_shoe_md"] = float(wb["string_shoe"])
        res["_products"] = payload.get("products") or []
        # run_full_analysis zone tables drop product_name; restore the
        # zone -> product association (matched by exact top_md/bottom_md)
        # so kind classification (Rigid/Spring) stays self-sufficient.
        for z in res.get("zones") or []:
            if z.get("product_name"):
                continue
            for zd in (payload.get("zones") or []):
                if (abs(float(zd.get("top_md", -1e18))
                        - float(z["top_md"])) < 1e-9
                        and abs(float(zd.get("bottom_md", 1e18))
                                - float(z["bottom_md"])) < 1e-9):
                    if zd.get("product_name"):
                        z["product_name"] = zd["product_name"]
                    break
    else:
        res = payload

    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(output_dir, chart_name)
    md_path = os.path.join(output_dir, report_name)
    render_pipe_standoff_chart(res, png_path)
    generate_section_ix_markdown(res, md_path)
    return os.path.abspath(png_path), os.path.abspath(md_path)


# ===========================================================================
# 7. CLI
# ===========================================================================
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="cement_charts_engine.py",
        description="CemCADE Section IX chart & reporting companion "
                    f"engine v{__version__} (of {COMPANION_OF})")
    ap.add_argument("payload", nargs="?",
                    help="JSON file: well_data payload OR pre-calculated "
                         "analysis result (auto-detected)")
    ap.add_argument("--mock", choices=("casing", "liner", "tieback"),
                    default=None,
                    help="run on a self-consistent mock project instead "
                         "of a payload file")
    ap.add_argument("--outdir", default=".", help="output directory")
    ap.add_argument("--png", default="pipe_standoff.png",
                    help="output PNG file name")
    ap.add_argument("--md", default="section_ix_report.md",
                    help="output Markdown file name")
    args = ap.parse_args(argv)

    if bool(args.payload) == bool(args.mock):
        ap.error("provide exactly one of: payload.json | --mock KIND")

    if args.mock:
        eng = _import_optimizer_engine()
        payload = eng.create_mock_project(args.mock)
        payload["well_name"] = f"MOCK-{args.mock.upper()}"
    else:
        with open(args.payload, "r", encoding="utf-8") as fh:
            payload = json.load(fh)

    png_path, md_path = export_full_section_ix_report(
        payload, output_dir=args.outdir, chart_name=args.png,
        report_name=args.md)
    print(f"cement_charts_engine v{__version__} "
          f"(companion of {COMPANION_OF})")
    print(f"  chart    : {png_path}")
    print(f"  report   : {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
