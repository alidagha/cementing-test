#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure Cementing-App -> well_schematic_engine projection and validation boundary.

Production projection of the owner-supplied schematic contract.

This module does not import Streamlit. It consumes the shared project fingerprint and accepts a
mapping shaped like the app's canonical state, validates the owner-locked schematic contract,
and returns a renderer payload.  It never mutates the supplied state, never repairs geometry,
and never infers the current/deepest job.

Canonical placement fields:
    placement_config["tie_back_liner_lap_m"]  # explicit top of Tie Back
    placement_config["squeeze_depth_m"]       # independent squeeze depth
    placement_config["target_string_id"]      # string-level target, preferred for Squeeze

Existing placement_config["target_row"] fingerprints identify canonical Hardware rows.
The adapter resolves their whole physical strings without changing the row-level calculation
target. Explicit schematic metadata is used only where the existing state does not resolve it.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from project_state import fingerprint
from engineering_tools import parse_fractional_size

try:
    import pandas as pd
except Exception:  # pragma: no cover - adapter can still consume list[dict]
    pd = None


__version__ = "0.1.0-local"

DEPTH_TOL = 1e-6
SIZE_TOL = 1e-6

STRUCTURAL_DESCRIPTIONS = {
    "Previous Casing",
    "Casing",
    "Previous Liner",
    "Liner",
    "Tie Back",
}
AUX_DESCRIPTIONS = {
    "Liner Hanger",
    "Previous Liner Hanger",
    "Drill Pipes",
    "Tubing",
    "Open Hole Size",
}
SUPPORTED_DESCRIPTIONS = STRUCTURAL_DESCRIPTIONS | AUX_DESCRIPTIONS

_MD_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?)\s*)?$")
_JOB_SIZE_RE = re.compile(r"(?:CSG|LNR)\s+(.+?)\"\s*$", re.IGNORECASE)


@dataclass
class Section:
    row_index: int
    description: str
    size_in: float
    start_md: float
    end_md: float
    id_in: Optional[float]
    token: str


@dataclass
class WellString:
    string_id: str
    description: str
    renderer_type: str
    size_in: float
    top_md: float
    shoe_md: float
    sections: List[Section] = field(default_factory=list)
    host_id: Optional[str] = None
    landing_liner_id: Optional[str] = None

    @property
    def display_kind(self) -> str:
        return {"casing": "CSG", "liner": "LNR", "tieback": "TB LNR"}[self.renderer_type]

    @property
    def label(self) -> str:
        return f'{format_size(self.size_in)} {self.display_kind}'


def _finite(value: Any, ctx: str, *, nonnegative: bool = False, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{ctx} must be a finite number")
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{ctx} must be a finite number") from None
    if not math.isfinite(out):
        raise ValueError(f"{ctx} must be a finite number")
    if positive and out <= 0:
        raise ValueError(f"{ctx} must be > 0")
    if nonnegative and out < 0:
        raise ValueError(f"{ctx} must be >= 0")
    return out


def validate_schematic_config(config):
    """Validate only explicit presentation inputs at the project trust boundary."""
    allowed = {"version", "squeeze_target_id", "plug_bore_sections", "squeeze_wall"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("schematic_config must contain only supported drawing inputs")
    if type(config.get("version", 1)) is not int or config.get("version", 1) != 1:
        raise ValueError("schematic_config.version must be 1")
    identity = config.get("squeeze_target_id", "")
    if not isinstance(identity, str):
        raise ValueError("schematic_config.squeeze_target_id must be a string identity")
    sections = config.get("plug_bore_sections", [])
    if not isinstance(sections, list):
        raise ValueError("schematic_config.plug_bore_sections must be a list")
    records = [(section, {"top_md", "bottom_md", "diameter_in"}) for section in sections]
    if "squeeze_wall" in config:
        records.append((config["squeeze_wall"], {"depth_m", "diameter_in"}))
    for record, fields in records:
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError("schematic_config requires exact depth/dimension fields")
        for field, value in record.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"schematic_config.{field} must be a finite numeric value")
            _finite(value, f"schematic_config.{field}", positive=field == "diameter_in", nonnegative=True)
        if "top_md" in record and record["top_md"] >= record["bottom_md"]:
            raise ValueError("schematic_config bore Top must be above Bottom")
    ordered = sorted(sections, key=lambda section: section["top_md"])
    if any(a["bottom_md"] > b["top_md"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("schematic_config bore intervals must not overlap")
    return config


class DrawingInputRequired(ValueError):
    """Known geometry is preserved while explicit operation drawing facts are absent."""


def parse_size(value: Any, ctx: str = "size") -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{ctx} is required")
    return _finite(parse_fractional_size(value), ctx, positive=True)


def format_size(value: float) -> str:
    value = float(value)
    whole = int(math.floor(value + 1e-9))
    frac = Fraction(value - whole).limit_denominator(64)
    if abs(value - round(value)) <= 1e-8:
        return f'{int(round(value))}"'
    if whole and frac.numerator:
        return f'{whole} {frac.numerator}/{frac.denominator}"'
    if frac.numerator:
        return f'{frac.numerator}/{frac.denominator}"'
    return f'{value:g}"'


def _parse_md(value: Any, ctx: str) -> Tuple[Optional[float], float]:
    match = _MD_RE.fullmatch(str(value))
    if not match:
        raise ValueError(f"{ctx}: expected a positive MD endpoint or interval such as 3927 or 1200-2816")
    a = _finite(match.group(1), ctx, nonnegative=True)
    if match.group(2) is None:
        if a <= 0:
            raise ValueError(f"{ctx}: MD endpoint must be positive")
        return None, a
    b = _finite(match.group(2), ctx, positive=True)
    if b <= a + DEPTH_TOL:
        raise ValueError(f"{ctx}: interval end must be deeper than interval start")
    return a, b


def hardware_row_token(row: Mapping[str, Any]) -> str:
    desc = str(row.get("Description", "")).strip()
    md = str(row.get("MD (m)", "")).strip()
    size = str(row.get("Size (in)", "")).strip()
    return fingerprint([desc, md, size])


def _rows_from_table(table: Any) -> List[Dict[str, Any]]:
    if pd is not None and isinstance(table, pd.DataFrame):
        return deepcopy(table.to_dict("records"))
    if isinstance(table, list) and all(isinstance(row, Mapping) for row in table):
        return [deepcopy(dict(row)) for row in table]
    raise ValueError("hardware_table must be a pandas DataFrame or list of row mappings")


def _size_key(value: float) -> str:
    return f"{float(value):.8f}".rstrip("0").rstrip(".")


def _desc_slug(desc: str) -> str:
    return desc.lower().replace(" ", "-")


def _string_id(desc: str, size: float) -> str:
    return f"{_desc_slug(desc)}:{_size_key(size)}"


def _renderer_type(desc: str) -> str:
    if "Casing" in desc:
        return "casing"
    if desc in ("Previous Liner", "Liner"):
        return "liner"
    if desc == "Tie Back":
        return "tieback"
    raise ValueError(f"unsupported structural description {desc!r}")


def _optional_id(row: Mapping[str, Any], size: float, ctx: str) -> Optional[float]:
    raw = row.get("ID (in)")
    if raw is None or raw == "":
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{ctx}.ID (in) must be numeric when supplied") from None
    if not math.isfinite(val) or val <= 0:
        return None
    if val >= size - SIZE_TOL:
        raise ValueError(f"{ctx}: ID ({val:g} in) must be smaller than OD/Size ({size:g} in)")
    return val


def _job_kind(job_type: str) -> str:
    from cement_chart_model import chart_job_kind
    kind = chart_job_kind(job_type)
    return {"CMT PLUG": "cmt_plug", "CMT SQUEEZE": "cmt_squeeze"}.get(job_type, kind)


def _job_size(job_type: str) -> Optional[float]:
    kind = _job_kind(job_type)
    if kind in ("cmt_plug", "cmt_squeeze"):
        return None
    match = _JOB_SIZE_RE.search(str(job_type))
    if not match:
        raise ValueError(f"cannot resolve nominal size from job_type {job_type!r}")
    return parse_size(match.group(1), "job_type size")


def _aux_rows(rows: Sequence[Mapping[str, Any]], desc: str, size: Optional[float] = None) -> List[Tuple[int, Mapping[str, Any]]]:
    out = []
    for i, row in enumerate(rows):
        if str(row.get("Description", "")).strip() != desc:
            continue
        if size is not None:
            raw = str(row.get("Size (in)", "")).strip()
            if raw:
                try:
                    if abs(parse_size(raw, f"hardware[{i}].Size (in)") - size) > SIZE_TOL:
                        continue
                except ValueError:
                    continue
        out.append((i, row))
    return out


def _single_aux_depth(rows: Sequence[Mapping[str, Any]], desc: str, size: Optional[float], ctx: str) -> Optional[float]:
    matches = _aux_rows(rows, desc, size)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"{ctx}: expected exactly one {desc} authority row, found {len(matches)}")
    i, row = matches[0]
    start, end = _parse_md(row.get("MD (m)"), f"hardware[{i}].MD (m)")
    if start is not None:
        raise ValueError(f"{ctx}: {desc} MD must be a single endpoint, not an interval")
    return end


def _drill_pipe_end(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    matches = _aux_rows(rows, "Drill Pipes", None)
    if not matches:
        return None
    previous = 0.0
    last = None
    for i, row in matches:
        start, end = _parse_md(row.get("MD (m)"), f"hardware[{i}].MD (m)")
        if start is not None and abs(start - previous) > DEPTH_TOL:
            raise ValueError("Drill Pipes sections contain a gap/overlap; their end cannot define LNR Lap")
        if end <= previous + DEPTH_TOL:
            raise ValueError("Drill Pipes MD endpoints must be strictly increasing")
        previous = end
        last = end
    return last


def _explicit_placement_depth(state: Mapping[str, Any], key: str, ctx: str) -> float:
    placement = state.get("placement_config")
    value = placement.get(key) if isinstance(placement, Mapping) else None
    return _finite(value, ctx, nonnegative=True)


def _squeeze_depth(state):
    """Independent schematic depth when supplied, otherwise current treatment authority."""
    from placement import target_depth
    placement = state.get("placement_config") or {}
    if placement.get("squeeze_depth_m") is not None:
        return _finite(placement["squeeze_depth_m"], "Squeeze Depth", nonnegative=True)
    table = state.get("hardware_table")
    if isinstance(table, list):
        table = pd.DataFrame(table)
    return _finite(target_depth(table, state.get("job_type"), placement),
                   "Squeeze Depth / current Placement treatment depth", nonnegative=True)


def _resolve_liner_top(rows: Sequence[Mapping[str, Any]], desc: str, size: float,
                       *, current_liner: bool) -> float:
    hanger_desc = "Previous Liner Hanger" if desc == "Previous Liner" else "Liner Hanger"
    hanger = _single_aux_depth(rows, hanger_desc, None if current_liner else size,
                                f'{format_size(size)} {desc}')
    drill = _drill_pipe_end(rows) if current_liner else None
    if hanger is not None and drill is not None and abs(hanger - drill) > DEPTH_TOL:
        raise ValueError(
            f'{format_size(size)} current LNR: Liner Hanger ({hanger:g} m) and Drill Pipes end ({drill:g} m) must match exactly'
        )
    top = hanger if hanger is not None else drill
    first = next((row for row in rows if str(row.get("Description", "")).strip() == desc
                  and parse_size(row.get("Size (in)")) == size), None)
    interval_top = _parse_md(first.get("MD (m)"), f"{desc} first section")[0] if first else None
    if interval_top is not None:
        if top is not None and interval_top != top:
            raise ValueError(f"{desc}: explicit interval Top contradicts the Hanger / Drill Pipes authority")
        top = interval_top
    if top is None:
        if desc == "Previous Liner":
            raise ValueError(f'{format_size(size)} Previous Liner Lap is missing: supply an explicit interval or Previous Liner Hanger')
        raise ValueError(f'{format_size(size)} Liner requires Liner Hanger or current Drill Pipes end to define LNR Lap')
    return top


def _build_strings(state: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> Tuple[List[WellString], Dict[int, str], Dict[str, WellString]]:
    job = str(state.get("job_type", ""))
    kind = _job_kind(job)
    job_size = _job_size(job)

    grouped: Dict[Tuple[str, float], List[Tuple[int, Mapping[str, Any]]]] = {}
    row_to_group: Dict[int, Tuple[str, float]] = {}
    for i, row in enumerate(rows):
        desc = str(row.get("Description", "")).strip()
        if not desc:
            continue
        if desc not in SUPPORTED_DESCRIPTIONS:
            raise ValueError(f"hardware[{i}].Description {desc!r} is not supported by the local schematic contract")
        if desc not in STRUCTURAL_DESCRIPTIONS:
            continue
        size = parse_size(row.get("Size (in)"), f"hardware[{i}].Size (in)")
        key = (desc, size)
        grouped.setdefault(key, []).append((i, row))
        row_to_group[i] = key

    strings: List[WellString] = []
    row_to_string: Dict[int, str] = {}

    tieback_groups = [key for key in grouped if key[0] == "Tie Back"]
    if len(tieback_groups) > 1:
        raise ValueError("multiple Tie Back strings require separate explicit Tie Back Liner Lap authorities; local adapter does not guess them")

    for (desc, size), entries in grouped.items():
        if desc in ("Previous Casing", "Casing"):
            top = 0.0
        elif desc in ("Previous Liner", "Liner"):
            current_liner = kind == "liner" and desc == "Liner" and job_size is not None and abs(size - job_size) <= SIZE_TOL
            top = _resolve_liner_top(rows, desc, size, current_liner=current_liner)
        else:  # Tie Back
            if kind == "tieback":
                from cement_chart_model import resolve_chart_geometry
                top = resolve_chart_geometry(state)["active_string"][0]["top_md"]
                explicit = (state.get("placement_config") or {}).get("tie_back_liner_lap_m")
                if explicit is not None and _finite(explicit, "Tie Back Top", nonnegative=True) != top:
                    raise ValueError("Schematic Tie Back Top contradicts the certified active-string geometry")
            else:
                interval_top, _ = _parse_md(entries[0][1].get("MD (m)"), "Historical Tie Back section")
                if interval_top is None:
                    top = _explicit_placement_depth(state, "tie_back_liner_lap_m", "Historical Tie Back Top")
                else:
                    top = interval_top
                    explicit = (state.get("placement_config") or {}).get("tie_back_liner_lap_m")
                    if explicit is not None and _finite(explicit, "Historical Tie Back Top", nonnegative=True) != top:
                        raise ValueError("Historical Tie Back interval Top contradicts explicit schematic metadata")

        previous_end = top
        sections: List[Section] = []
        for row_index, row in entries:  # row order is authority; never sort/repair
            explicit_start, end = _parse_md(row.get("MD (m)"), f"hardware[{row_index}].MD (m)")
            if explicit_start is not None and abs(explicit_start - previous_end) > DEPTH_TOL:
                raise ValueError(
                    f'{format_size(size)} {desc}: section at hardware row {row_index} starts at {explicit_start:g} m '
                    f'but the authoritative previous boundary is {previous_end:g} m'
                )
            if end <= previous_end + DEPTH_TOL:
                raise ValueError(f'{format_size(size)} {desc}: section endpoints must be strictly increasing')
            sec = Section(
                row_index=row_index,
                description=desc,
                size_in=size,
                start_md=previous_end,
                end_md=end,
                id_in=_optional_id(row, size, f"hardware[{row_index}]"),
                token=hardware_row_token(row),
            )
            sections.append(sec)
            previous_end = end
            row_to_string[row_index] = _string_id(desc, size)

        if not sections:
            continue
        sid = _string_id(desc, size)
        strings.append(WellString(
            string_id=sid,
            description=desc,
            renderer_type=_renderer_type(desc),
            size_in=size,
            top_md=top,
            shoe_md=sections[-1].end_md,
            sections=sections,
        ))

    by_id = {s.string_id: s for s in strings}
    if len(by_id) != len(strings):
        raise ValueError("duplicate same-role/same-size strings are not allowed; hardware rows must describe sections of one string")
    return strings, row_to_string, by_id


def _section_id_at(string: WellString, depth: float) -> Optional[float]:
    for sec in string.sections:
        if sec.start_md - DEPTH_TOL <= depth <= sec.end_md + DEPTH_TOL:
            return sec.id_in
    return None


def _validate_fit(child: WellString, host: WellString, overlap_top: float, overlap_bottom: float) -> None:
    if child.size_in >= host.size_in - SIZE_TOL:
        raise ValueError(f"{child.label} does not have a smaller OD than host {host.label}")
    for sec in host.sections:
        a = max(overlap_top, sec.start_md)
        b = min(overlap_bottom, sec.end_md)
        if b <= a + DEPTH_TOL:
            continue
        if sec.id_in is not None and child.size_in >= sec.id_in - SIZE_TOL:
            raise ValueError(
                f"{child.label} OD {child.size_in:g} in cannot pass host {host.label} ID {sec.id_in:g} in "
                f"over {a:g}-{b:g} m"
            )


def _resolve_hosts(strings: List[WellString]) -> None:
    candidates_pool = [s for s in strings if s.renderer_type in ("casing", "liner")]
    for child in strings:
        if child.renderer_type not in ("liner", "tieback"):
            continue
        candidates = [
            host for host in candidates_pool
            if host.string_id != child.string_id
            and host.size_in > child.size_in + SIZE_TOL
            and host.top_md - DEPTH_TOL <= child.top_md <= host.shoe_md + DEPTH_TOL
        ]
        if not candidates:
            raise ValueError(f"{child.label}: no explicit geometric host covers its Lap/Top at {child.top_md:g} m")
        min_size = min(host.size_in for host in candidates)
        immediate = [host for host in candidates if abs(host.size_in - min_size) <= SIZE_TOL]
        if len(immediate) != 1:
            raise ValueError(f"{child.label}: geometric host is ambiguous at {child.top_md:g} m")
        host = immediate[0]
        child.host_id = host.string_id
        _validate_fit(child, host, child.top_md, min(child.shoe_md, host.shoe_md))
        if host.shoe_md - child.top_md <= DEPTH_TOL:
            raise ValueError(f"{child.label}: zero lap inside host {host.label}")


def _validate_casing_nesting(strings: Sequence[WellString]) -> None:
    # Nesting follows actual diameters; shoe order is not installation history.
    casings = sorted((s for s in strings if s.renderer_type == "casing"), key=lambda s: -s.size_in)
    for outer, inner in zip(casings, casings[1:]):
        _validate_fit(inner, outer, 0.0, min(outer.shoe_md, inner.shoe_md))


def _resolve_tieback_landings(strings: Sequence[WellString], state=None) -> None:
    liners = [s for s in strings if s.renderer_type == "liner"]
    for tb in (s for s in strings if s.renderer_type == "tieback"):
        candidates = [
            ln for ln in liners
            if ln.top_md - DEPTH_TOL <= tb.shoe_md <= ln.shoe_md + DEPTH_TOL
        ]
        if len(candidates) > 1 and state is not None and _job_kind(state.get("job_type")) == "tieback":
            # Consume the frozen app's selected continuation, not a second
            # nearest/deepest-host walk in the schematic adapter.
            from pumping_simulation import _geometry
            geometry, _ = _geometry(state, "tieback")
            continuation = [section for section in geometry.pipe_sections
                            if section.z_top == tb.shoe_md and section.z_bot > tb.shoe_md]
            if len(continuation) == 1:
                section = continuation[0]
                candidates = [ln for ln in candidates if ln.size_in == section.od_in and any(
                    sec.start_md <= tb.shoe_md < sec.end_md and sec.end_md == section.z_bot
                    and sec.id_in == section.id_in for sec in ln.sections)]
        if len(candidates) != 1:
            raise ValueError(
                f"{tb.label}: tie-in {tb.shoe_md:g} m requires exactly one resolved receiving historical Liner interval"
            )
        liner = candidates[0]
        tb.landing_liner_id = liner.string_id


def _selected_row(rows: Sequence[Mapping[str, Any]], placement: Mapping[str, Any]) -> Optional[int]:
    token = placement.get("target_row")
    if not isinstance(token, str) or token in ("", "__manual__"):
        return None
    matches = [i for i, row in enumerate(rows) if hardware_row_token(row) == token]
    if len(matches) != 1:
        raise ValueError("placement_config.target_row does not resolve to exactly one current Hardware row")
    return matches[0]


def list_schematic_targets(state: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return string-level choices suitable for the future UI integration."""
    rows = _rows_from_table(state.get("hardware_table"))
    strings, _, _ = _build_strings(state, rows)
    _resolve_hosts(strings)
    _resolve_tieback_landings(strings, state)
    out: Dict[str, Dict[str, Any]] = {}
    for s in strings:
        out[s.string_id] = {
            "label": s.label,
            "kind": s.renderer_type,
            "size_in": s.size_in,
            "top_md": s.top_md,
            "shoe_md": s.shoe_md,
            "section_count": len(s.sections),
        }
    oh_rows = _aux_rows(rows, "Open Hole Size")
    if len(oh_rows) == 1:
        i, row = oh_rows[0]
        size = parse_size(row.get("Size (in)"), f"hardware[{i}].Size (in)")
        out["open-hole"] = {"label": f"{format_size(size)} Open Hole", "kind": "open_hole", "size_in": size}
    return out


def _resolve_current_structural_target(state: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                                       strings: Sequence[WellString], row_to_string: Mapping[int, str]) -> WellString:
    job = str(state.get("job_type", ""))
    kind = _job_kind(job)
    expected_size = _job_size(job)
    placement = state.get("placement_config")
    if not isinstance(placement, Mapping) or placement.get("job_type") != job:
        raise ValueError("placement_config must belong to the current job_type")

    target_sid = placement.get("target_string_id")
    selected: Optional[WellString] = None
    if isinstance(target_sid, str) and target_sid:
        selected = next((s for s in strings if s.string_id == target_sid), None)
        if selected is None:
            raise ValueError("placement_config.target_string_id does not resolve to a current schematic string")
    else:
        row_index = _selected_row(rows, placement)
        if row_index is None:
            raise ValueError("current CSG/LNR/TB job requires an explicit Hardware target; manual depth is not sufficient")
        sid = row_to_string.get(row_index)
        if sid is None:
            raise ValueError("selected target row is not a structural CSG/LNR/TB row")
        selected = next(s for s in strings if s.string_id == sid)
        # Existing app UI is row-based.  For a structural current job the selected row must still
        # be the final section, because that row is the explicit operation Shoe authority.
        if selected.sections[-1].row_index != row_index:
            raise ValueError(f"{selected.label}: Placement target must select the final section/Shoe row")

    if selected.renderer_type != kind:
        raise ValueError(f"current job {job} target resolves to {selected.renderer_type}, not {kind}")
    if expected_size is None or abs(selected.size_in - expected_size) > SIZE_TOL:
        raise ValueError(f"current job {job} target size does not match the job nominal size")
    return selected


def _squeeze_choices(state, strings, open_hole, depth):
    choices = {}
    for string in strings:
        if not string.top_md - DEPTH_TOL <= depth <= string.shoe_md + DEPTH_TOL:
            continue
        location = "Shoe" if abs(depth - string.shoe_md) <= DEPTH_TOL else "Lap" if abs(depth - string.top_md) <= DEPTH_TOL else "Point"
        token = string.string_id
        choices[token] = {"target_id": string.string_id, "label": f"{string.label} — {location} @ {depth:g} m"}
    if open_hole and open_hole["top_md"] - DEPTH_TOL <= depth <= open_hole["bottom_md"] + DEPTH_TOL:
        token = "open-hole"
        choices[token] = {"target_id": "open-hole", "label":
            f"{format_size(open_hole['hole_size_in'])} Open Hole — starts @ {open_hole['top_md']:g} m"}
    return choices


def _resolve_squeeze_target(state, rows, strings, row_to_string, open_hole, inputs):
    job = state.get("job_type")
    placement = state.get("placement_config") or {}
    if placement.get("job_type") != job:
        raise ValueError("placement_config must belong to the current CMT SQUEEZE job")
    depth = _squeeze_depth(state)
    choices = _squeeze_choices(state, strings, open_hole, depth)
    selected = (state.get("schematic_config") or {}).get("squeeze_target_id")
    canonical = placement.get("target_string_id")
    if not canonical:
        index = _selected_row(rows, placement)
        if index is not None:
            canonical = "open-hole" if rows[index].get("Description") == "Open Hole Size" else row_to_string.get(index)
            if not canonical:
                raise ValueError("Selected Squeeze Hardware does not identify a whole physical string")
    if canonical:
        if canonical == "open-hole":
            if not open_hole:
                raise ValueError("Selected Open Hole target is not available")
            target = None
        else:
            target = next((string for string in strings if string.string_id == canonical), None)
            if target is None:
                raise ValueError("placement_config.target_string_id does not resolve to a current schematic string")
        if selected in choices and choices[selected]["target_id"] != canonical:
            raise ValueError("Schematic Squeeze target contradicts the canonical App target")
        # An obsolete supplemental choice never replaces a new explicit App target.
        return canonical, target
    if len(choices) == 1 and not selected:
        target_id = next(iter(choices.values()))["target_id"]
    elif selected in choices:
        target_id = choices[selected]["target_id"]
    else:
        if len(choices) > 1:
            inputs["squeeze_targets"] = choices
        elif selected:
            inputs["obsolete_squeeze_target"] = True
        if choices or selected:
            raise DrawingInputRequired("Squeeze Target for Well Schematic is unresolved or ambiguous; select a current physical target")
        inputs["squeeze_wall_depth"] = depth
        wall = (state.get("schematic_config") or {}).get("squeeze_wall")
        if not wall or wall["depth_m"] != depth:
            raise DrawingInputRequired(f"Well schematic requires the operation-wall diameter at Squeeze depth {depth:g} m")
        return "operation-wall", None
    if len(choices) > 1:
        inputs["squeeze_targets"] = choices
    return target_id, next((string for string in strings if string.string_id == target_id), None)


def _resolve_open_hole(state: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], strings: Sequence[WellString],
                       current_structural: Optional[WellString]) -> Optional[Dict[str, Any]]:
    matches = _aux_rows(rows, "Open Hole Size")
    if not matches:
        return None
    row_index, row = matches[0]
    size = parse_size(row.get("Size (in)"), f"hardware[{row_index}].Size (in)")
    raw_id = row.get("ID (in)")
    if raw_id not in (None, ""):
        try:
            id_value = float(raw_id)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Open Hole ID must be numeric when supplied") from None
        if math.isfinite(id_value) and id_value > 0 and abs(id_value - size) > SIZE_TOL:
            raise ValueError(f"Open Hole Size ({size:g} in) and ID/Bit Size ({id_value:g} in) must be identical")
    _, bottom = _parse_md(matches[-1][1].get("MD (m)"), "current Open Hole last section")

    kind = _job_kind(str(state.get("job_type", "")))
    host: Optional[WellString] = None
    if kind == "liner" and current_structural is not None:
        host = next((s for s in strings if s.string_id == current_structural.host_id), None)
    elif kind == "casing" and current_structural is not None:
        prior = [s for s in strings if s.renderer_type == "casing" and s.string_id != current_structural.string_id
                 and s.shoe_md < current_structural.shoe_md - DEPTH_TOL]
        if prior:
            deepest = max(s.shoe_md for s in prior)
            candidates = [s for s in prior if abs(s.shoe_md - deepest) <= DEPTH_TOL]
            if len(candidates) != 1:
                raise ValueError("current CSG Open Hole top is ambiguous between previous casing Shoes")
            host = candidates[0]
    elif kind == "tieback" and any(
            _parse_md(row.get("MD (m)"), "Historical liner section")[0] is not None
            for row in rows if row.get("Description") in ("Previous Liner", "Liner")):
        # The certified flow path already owns this cased-to-OH transition.
        # This does not choose the TB geometric host or its receiving liner.
        from cement_chart_model import resolve_chart_geometry
        from pumping_simulation import _tieback_paths
        table = state.get("hardware_table")
        if isinstance(table, list):
            table = pd.DataFrame(table)
        _, enclosing, _ = _tieback_paths(rows, table, state["placement_config"], resolve_chart_geometry(state))
        for index, section in enumerate(enclosing):
            if section["description"] != "Open Hole Size":
                continue
            if index == 0:
                raise ValueError("The certified Open Hole path has no enclosing string at its Top")
            parent = enclosing[index - 1]
            candidates = [s for s in strings if s.description == parent["description"]
                          and s.size_in == parent["od_in"] and s.shoe_md == section["top_md"]]
            if len(candidates) != 1:
                raise ValueError("The certified Open Hole transition does not identify one physical host string")
            host = candidates[0]
            break
    if kind not in ("casing", "liner") and host is None:
        # Geometry-only resolution: prefer a host Shoe crossed by an explicitly hosted child
        # that is smaller than this hole.  If geometry does not make that unique, block.
        eligible = [s for s in strings if s.renderer_type in ("casing", "liner")
                    and s.shoe_md < bottom - DEPTH_TOL
                    and size <= (_section_id_at(s, s.shoe_md) or s.size_in)]
        crossing: List[WellString] = []
        for child in strings:
            if child.renderer_type != "liner" or child.host_id is None:
                continue
            candidate = next((s for s in strings if s.string_id == child.host_id), None)
            if candidate is None or candidate not in eligible:
                continue
            if (child.top_md + DEPTH_TOL < candidate.shoe_md < child.shoe_md - DEPTH_TOL
                    and child.size_in < size - SIZE_TOL and candidate.shoe_md < bottom - DEPTH_TOL):
                crossing.append(candidate)
        unique = {s.string_id: s for s in crossing}
        if len(unique) == 1:
            host = next(iter(unique.values()))
        elif len(unique) > 1:
            raise ValueError("current Open Hole Top is geometrically ambiguous; review canonical Hardware")
        else:
            prior = eligible
            if prior:
                deepest = max(s.shoe_md for s in prior)
                candidates = [s for s in prior if abs(s.shoe_md - deepest) <= DEPTH_TOL]
                if len(candidates) == 1:
                    host = candidates[0]
                else:
                    raise ValueError("current Open Hole Top is ambiguous; review canonical Hardware")

    top = 0.0 if host is None else host.shoe_md
    if bottom <= top + DEPTH_TOL:
        raise ValueError(f"Open Hole Bottom/TD {bottom:g} m must be deeper than its resolved Top {top:g} m")
    from cement_chart_model import _segments
    hole_rows = []
    for _, entry in matches:
        diameter = parse_size(entry.get("Size (in)"), "Open Hole Size")
        raw = entry.get("ID (in)")
        if raw not in (None, "") and _finite(raw, "Open Hole ID") > 0 and float(raw) != diameter:
            raise ValueError("Open Hole Size and ID/Bit Size must be identical")
        # A hole's diameter is its Size; an absent tubular ID is not another drawing fact.
        hole_rows.append({**entry, "ID (in)": diameter})
    segments = _segments(hole_rows, top, bottom, "Schematic current Open Hole")
    if any(segment["od_in"] != size or segment["id_in"] != size for segment in segments):
        raise ValueError("Current Open Hole sections must have one compatible Size/ID; conflicting diameters cannot be merged")
    return {
        "top_md": top,
        "bottom_md": bottom,
        "hole_size_in": size,
        "host_id": None if host is None else host.string_id,
        "source_row": row_index,
    }


def _resolve_plugs(state: Mapping[str, Any]) -> List[Dict[str, float]]:
    """Project each certified independent Plug interval; never require Main."""
    import materials_db
    from placement import slurry_intervals
    job = state.get("job_type")
    params = state.get("cement_params") or {}
    config = state.get("fluids_config") or {}
    # Owner handoff payloads can supply a Main top without a Phase-IV program.
    active = config.get("active", ["Main"] if "Main" in params else [])
    active = [name for name in materials_db.PLACEMENT_SLURRIES if name in active]
    table = state.get("hardware_table")
    if isinstance(table, list):
        table = pd.DataFrame(table)
    intervals = slurry_intervals(table, job, state.get("placement_config") or {}, active, params)
    if not intervals:
        raise ValueError("CMT PLUG requires an active slurry with a Phase-V Top and Placement Bottom")
    plugs = []
    for name, row in intervals.items():
        top = _finite(row["top_depth"], f"{name} Plug Top", nonnegative=True)
        bottom = _finite(row["bottom_depth"], f"{name} Plug Bottom", positive=True)
        if top >= bottom:
            raise ValueError(f"{name} Plug Top must be above Plug Bottom")
        plugs.append({"top_md": top, "bottom_md": bottom})
    return plugs


def _bore_exists(depth: float, strings: Sequence[WellString], open_hole: Optional[Mapping[str, Any]]) -> bool:
    if any(s.top_md - DEPTH_TOL <= depth <= s.shoe_md + DEPTH_TOL for s in strings):
        return True
    return bool(open_hole and open_hole["top_md"] - DEPTH_TOL <= depth <= open_hole["bottom_md"] + DEPTH_TOL)


def _plug_bore_inputs(state, plugs, strings, open_hole, inputs):
    boundaries = {value for plug in plugs for value in (plug["top_md"], plug["bottom_md"])}
    boundaries.update(value for string in strings for value in (string.top_md, string.shoe_md))
    if open_hole:
        boundaries.update((open_hole["top_md"], open_hole["bottom_md"]))
    supplied = (state.get("schematic_config") or {}).get("plug_bore_sections", [])
    boundaries.update(value for section in supplied for value in (section["top_md"], section["bottom_md"]))
    ordered = sorted(boundaries)
    missing, accepted = [], []
    for top, bottom in zip(ordered, ordered[1:]):
        mid = (top + bottom) / 2
        if not any(plug["top_md"] <= mid <= plug["bottom_md"] for plug in plugs):
            continue
        explicit = next((section for section in supplied if section["top_md"] <= mid <= section["bottom_md"]), None)
        pipes = [string for string in strings if string.top_md <= mid <= string.shoe_md]
        if _bore_exists(mid, strings, open_hole):
            if explicit:
                diameter = _section_id_at(min(pipes, key=lambda string: string.size_in), mid) if pipes else open_hole["hole_size_in"]
                if diameter is None or explicit["diameter_in"] != diameter:
                    raise ValueError("Supplemental Plug diameter contradicts the canonical bore; remove conflicting drawing data")
            continue
        missing.append({"top_md": top, "bottom_md": bottom})
        if explicit:
            accepted.append({"top_md": top, "bottom_md": bottom, "diameter_in": explicit["diameter_in"]})
    if missing:
        inputs["plug_bores"] = missing
    if len(accepted) != len(missing):
        raise DrawingInputRequired("Well schematic: Plug bore geometry is unresolved; enter the bore diameter for each missing interval")
    return accepted


def _order_strings(strings: Sequence[WellString]) -> List[WellString]:
    casings = sorted((s for s in strings if s.renderer_type == "casing"), key=lambda s: (s.shoe_md, -s.size_in))
    liners = sorted((s for s in strings if s.renderer_type == "liner"), key=lambda s: (s.top_md, -s.size_in, s.shoe_md))
    tiebacks = sorted((s for s in strings if s.renderer_type == "tieback"), key=lambda s: (s.top_md, -s.size_in))
    return [*casings, *liners, *tiebacks]


def _payload_string(s: WellString, index_by_id: Mapping[str, int]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "size_in": s.size_in,
        "top_md": s.top_md,
        "shoe_md": s.shoe_md,
        "type": s.renderer_type,
    }
    ids = {sec.id_in for sec in s.sections if sec.id_in is not None}
    # Never fabricate one ID for a multi-ID string.  If all supplied section IDs are identical,
    # it is safe to expose that exact value to the renderer's secondary guardrail.
    if len(ids) == 1 and all(sec.id_in is not None for sec in s.sections):
        row["id_in"] = next(iter(ids))
    if s.host_id is not None:
        row["host_index"] = index_by_id[s.host_id]
    if s.landing_liner_id is not None:
        row["landing_liner_index"] = index_by_id[s.landing_liner_id]
    return row


def build_schematic_payload(state: Mapping[str, Any], *, _drawing_inputs=None) -> Dict[str, Any]:
    """Build a renderer payload from canonical app-like state without mutating it."""
    if not isinstance(state, Mapping):
        raise ValueError("state must be a mapping")
    validate_schematic_config(state.get("schematic_config", {}))
    inputs = {} if _drawing_inputs is None else _drawing_inputs
    rows = _rows_from_table(state.get("hardware_table"))
    job = str(state.get("job_type", ""))
    kind = _job_kind(job)
    strings, row_to_string, _ = _build_strings(state, rows)
    if not strings:
        raise ValueError("schematic requires at least one CSG/LNR/TB string in Hardware")
    _validate_casing_nesting(strings)
    _resolve_hosts(strings)
    _resolve_tieback_landings(strings, state)

    current_structural = None
    if kind in ("casing", "liner", "tieback"):
        current_structural = _resolve_current_structural_target(state, rows, strings, row_to_string)

    open_hole = _resolve_open_hole(state, rows, strings, current_structural)

    ordered = _order_strings(strings)
    index_by_id = {s.string_id: i for i, s in enumerate(ordered)}
    payload_strings = [_payload_string(s, index_by_id) for s in ordered]
    payload: Dict[str, Any] = {
        "well_name": str(state.get("well_name") or (state.get("doc_control") or {}).get("well_name") or job),
        "show_mid_depth": True,
        "casings": payload_strings,
        "open_holes": [],
        "cement_plugs": [],
        "squeezes": [],
    }
    if open_hole:
        oh = {
            "top_md": open_hole["top_md"],
            "bottom_md": open_hole["bottom_md"],
            "hole_size_in": open_hole["hole_size_in"],
        }
        if open_hole["host_id"] is not None:
            oh["host_index"] = index_by_id[open_hole["host_id"]]
        payload["open_holes"] = [oh]

    if kind in ("casing", "liner", "tieback"):
        assert current_structural is not None
        payload["current_job"] = {"type": kind, "target_index": index_by_id[current_structural.string_id]}
    elif kind == "cmt_plug":
        payload["cement_plugs"] = _resolve_plugs(state)
        extra_bores = _plug_bore_inputs(state, payload["cement_plugs"], strings, open_hole, inputs)
        if extra_bores:
            payload["plug_bores"] = extra_bores
        payload["current_job"] = {"type": "cmt_plug", "target_index": 0}
    else:
        depth = _squeeze_depth(state)
        target_id, target = _resolve_squeeze_target(state, rows, strings, row_to_string, open_hole, inputs)
        wall = (state.get("schematic_config") or {}).get("squeeze_wall")
        if wall and wall["depth_m"] == depth and target_id != "operation-wall":
            diameter = open_hole["hole_size_in"] if target_id == "open-hole" else target.size_in
            if wall["diameter_in"] != diameter:
                raise ValueError("Supplemental Squeeze wall contradicts canonical resolved target geometry; remove it")
        if target_id == "operation-wall":
            sq = {"depth_m": depth, "wall_diameter_in": state["schematic_config"]["squeeze_wall"]["diameter_in"], "target_kind": "point"}
        elif target_id == "open-hole":
            if open_hole is None or not (open_hole["top_md"] - DEPTH_TOL <= depth <= open_hole["bottom_md"] + DEPTH_TOL):
                raise ValueError("Squeeze Depth must lie inside the selected current Open Hole")
            sq = {"depth_m": depth, "open_hole_index": 0, "target_kind": "point"}
        else:
            assert target is not None
            if not (target.top_md - DEPTH_TOL <= depth <= target.shoe_md + DEPTH_TOL):
                raise ValueError(f"Squeeze Depth {depth:g} m does not lie on selected target {target.label}")
            if target.renderer_type in ("liner", "tieback") and abs(depth - target.top_md) <= DEPTH_TOL:
                target_kind = "lap"
            elif abs(depth - target.shoe_md) <= DEPTH_TOL:
                target_kind = "shoe"
            else:
                target_kind = "point"
            sq = {"depth_m": depth, "target_index": index_by_id[target.string_id], "target_kind": target_kind}
        payload["squeezes"] = [sq]
        payload["current_job"] = {"type": "cmt_squeeze", "target_index": 0}

    deepest = max(s.shoe_md for s in strings)
    if open_hole:
        deepest = max(deepest, open_hole["bottom_md"])
    if payload["cement_plugs"]:
        deepest = max(deepest, *(plug["bottom_md"] for plug in payload["cement_plugs"]))
    if payload["squeezes"]:
        deepest = max(deepest, payload["squeezes"][0]["depth_m"])
    payload["final_relevant_depth_m"] = deepest
    return payload


def validate_with_renderer(state: Mapping[str, Any], engine_module: Any) -> Dict[str, Any]:
    """Convenience hook for local certification without introducing an engine import dependency."""
    payload = build_schematic_payload(state)
    checked = deepcopy(payload)
    engine_module.validate_schematic_data(checked)
    findings = engine_module.check_well_design(checked)
    if findings:
        raise ValueError("renderer rejected adapter geometry:\n  - " + "\n  - ".join(findings))
    return payload


__all__ = [
    "prepare_schematic",
    "additional_drawing_inputs",
    "validate_schematic_config",
    "source_signature",
    "build_schematic_payload",
    "list_schematic_targets",
    "validate_with_renderer",
    "hardware_row_token",
    "parse_size",
    "format_size",
]


def prepare_schematic(state):
    """Validate current canonical construction without rendering or state writes."""
    import materials_db
    import well_schematic_engine as engine
    if hasattr(state, "to_dict"):
        state = state.to_dict()
    if state.get("job_type") not in materials_db.JOB_TYPES:
        raise ValueError("Well schematic requires a supported current job type.")
    return validate_with_renderer(state, engine)


def source_signature(state):
    """Fingerprint drawing sources only; no geometry validation or rendering."""
    if hasattr(state, "to_dict"):
        state = state.to_dict()
    table = state.get("hardware_table")
    columns = ["Description", "MD (m)", "Size (in)", "ID (in)"]
    hardware = table.reindex(columns=columns) if isinstance(table, pd.DataFrame) else table
    placement = state.get("placement_config") or {}
    fields = ["job_type", "target_row", "manual_depth_m", "target_string_id", "host_row", "tie_back_liner_lap_m"]
    job = state.get("job_type")
    if job == "CMT SQUEEZE":
        fields.append("squeeze_depth_m")
    params = state.get("cement_params") or {}
    active = (state.get("fluids_config") or {}).get("active", ["Main"])
    tops = {name: {key: record.get(key) for key in ("top_mode", "top_depth", "top_job_type")}
            for name, record in params.items() if job == "CMT PLUG" and name in active}
    config = state.get("schematic_config") or {}
    drawing_fields = ("plug_bore_sections",) if job == "CMT PLUG" else ("squeeze_target_id", "squeeze_wall") if job == "CMT SQUEEZE" else ()
    return fingerprint({"job": job, "hardware": hardware,
        "placement": {key: placement.get(key) for key in fields},
        "plug_tops": tops, "schematic_config": {key: config.get(key) for key in drawing_fields},
        "well_name": state.get("well_name") or (state.get("doc_control") or {}).get("well_name") or job})


def additional_drawing_inputs(state):
    """Return only facts absent from App/derived geometry, including saved values needing edit."""
    if hasattr(state, "to_dict"):
        state = state.to_dict()
    inputs = {}
    try:
        build_schematic_payload(state, _drawing_inputs=inputs)
    except DrawingInputRequired:
        pass
    return inputs
