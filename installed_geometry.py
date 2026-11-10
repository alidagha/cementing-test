"""Pure installed-string interpretation shared by engineering projections.

Reads measured Hardware only; owns physical grouping, fit and enclosing wall.
No project writes, persisted keys, UI, solver or report dependencies. Existing
Chart section parsing remains the authority for contiguous/tapered sections.
"""
import math
import re

from engineering_tools import parse_fractional_size

MD_INTERVAL = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?)\s*)?$")


def positive_size(value):
    # The catalog fraction parser accepts hyphens as mixed-number separators;
    # a leading minus must never become a positive physical diameter.
    if isinstance(value, bool) or str(value).replace('"', "").strip().startswith("-"):
        raise ValueError("Hardware Size must be greater than zero.")
    size = parse_fractional_size(value)
    if not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
        raise ValueError("Hardware Size must be positive and finite.")
    return size


def md_bounds(value):
    match = MD_INTERVAL.fullmatch(str(value))
    if not match:
        raise ValueError("Installed Hardware requires valid measured MD bounds.")
    left, right = match.groups()
    top, bottom = (None, float(left)) if right is None else (float(left), float(right))
    if not math.isfinite(bottom) or bottom <= (top if top is not None else 0.):
        raise ValueError("Installed Hardware has reversed/duplicate MD bounds.")
    return top, bottom


def point_depth(value, label):
    """A measured scalar Top may be zero; it is never an interval length."""
    match = MD_INTERVAL.fullmatch(str(value))
    if not match or match.group(2) is not None:
        raise ValueError(f"{label} requires one finite nonnegative scalar MD.")
    depth = float(match.group(1))
    if not math.isfinite(depth):
        raise ValueError(f"{label} requires one finite nonnegative scalar MD.")
    return depth


def _lap_top(lap, shoe, label):
    top = point_depth(lap.get("MD (m)"), label)
    size = lap.get("Size (in)")
    if size not in (None, "") and not (isinstance(size, float) and math.isnan(size)):
        if positive_size(size) != positive_size(shoe.get("Size (in)")):
            raise ValueError(f"{label} Size contradicts its measured Shoe string.")
    return top


def tieback_top(rows, config, *, hardware=None):
    if not rows:
        raise ValueError("Tie Back Top requires current Tie Back Hardware.")
    interval, _ = md_bounds(rows[0].get("MD (m)"))
    explicit = config.get("tie_back_liner_lap_m")
    if explicit is not None:
        if isinstance(explicit, bool) or not isinstance(explicit, (int, float)) or not math.isfinite(explicit) or explicit < 0:
            raise ValueError("Tie Back Top must be an explicit finite nonnegative MD.")
        if interval is not None and interval != explicit:
            raise ValueError("Tie Back interval Top contradicts tie_back_liner_lap_m.")
        interval = float(explicit)
    laps = [r for r in (hardware if hardware is not None else rows)
            if r.get("Description") == "Tie Back Liner Lap"]
    if len(laps) > 1:
        raise ValueError("Tie Back Top requires exactly one current Tie Back Liner Lap.")
    if laps:
        measured = _lap_top(laps[0], rows[0], "Tie Back Liner Lap")
        if interval is not None and measured != interval:
            raise ValueError("Tie Back Liner Lap Top contradicts the Shoe interval / explicit Top.")
        interval = measured
    if interval is None:
        raise ValueError("Tie Back Top is missing; a scalar endpoint does not establish a surface Top.")
    return interval


def previous_tieback(rows, segmenter):
    """At most one installed Tie Back, paired by its unique measured Lap."""
    laps = [(i, r) for i, r in enumerate(rows) if r.get("Description") == "Previous Tie Back Liner Lap"]
    shoes = [(i, r) for i, r in enumerate(rows) if r.get("Description") == "Previous Tie Back Liner Shoe"]
    if not laps and not shoes:
        return None
    if len(laps) != 1 or not shoes:
        raise ValueError("Previous Tie Back requires one measured Lap and one continuous Shoe string; multiple previous strings are unsupported.")
    top = _lap_top(laps[0][1], shoes[0][1], "Previous Tie Back Liner Lap")
    body = [r for _, r in shoes]
    end = md_bounds(body[-1].get("MD (m)"))[1]
    if top >= end:
        raise ValueError("Previous Tie Back requires measured Top < Shoe.")
    previous_od = positive_size(body[0].get("Size (in)"))
    for row in body[1:]:
        od = positive_size(row.get("Size (in)"))
        if od != previous_od and md_bounds(row.get("MD (m)"))[0] is None:
            raise ValueError("Previous Tie Back OD changes require an explicit continuous section boundary.")
        previous_od = od
    return {"description": "Previous Tie Back Liner Shoe", "top_md": top, "shoe_md": end,
            "last_od": previous_od, "rows": body, "indices": [i for i, _ in shoes],
            "sections": segmenter(body, top, end, "Previous Tie Back Liner Shoe")}


def physical_strings(rows, segmenter, descriptions):
    """Different scalar casing sizes are nested strings, not consecutive slices.

    Within a role/size, increasing endpoints retain their established section
    semantics. An explicit continuation can change OD only when its preceding
    boundary identifies exactly one string. Never sort or repair section rows.
    Existing Casing/Liner role filters cannot discard a measured previous Tie Back.
    """
    strings = []
    previous = previous_tieback(rows, segmenter)
    for index, row in enumerate(rows):
        desc = row.get("Description")
        if desc == "Previous Tie Back Liner Shoe":
            if index == previous["indices"][0]:
                strings.append(previous)
            continue
        if desc not in descriptions:
            continue
        size = positive_size(row.get("Size (in)"))
        top, bottom = md_bounds(row.get("MD (m)"))
        candidates = [s for s in strings if s["description"] == desc and
                      (s["shoe_md"] == top if top is not None else s["last_od"] == size)]
        if len(candidates) > 1:
            raise ValueError("Installed physical string identity is ambiguous at a section boundary.")
        if candidates:
            string = candidates[0]
            string["rows"].append(row)
            string["indices"].append(index)
            string["shoe_md"], string["last_od"] = bottom, size
        else:
            if "Casing" in desc:
                if top not in (None, 0.):
                    raise ValueError("Installed Casing sections must continue one known surface-origin string.")
                top = 0.
            else:
                hangers = [md_bounds(r.get("MD (m)"))[1] for r in rows
                           if r.get("Description") == ("Previous Liner Lap" if desc == "Previous Liner Shoe" else "Liner Lap")
                           and parse_fractional_size(r.get("Size (in)")) == size]
                if len(hangers) > 1 or (hangers and top is not None and hangers[0] != top):
                    raise ValueError("Historical Liner Top / Hanger is ambiguous or contradictory.")
                top = hangers[0] if hangers else top
                if top is None or top <= 0:
                    raise ValueError("Historical Liner requires an explicit nonzero Top / Hanger.")
            strings.append({"description": desc, "top_md": top, "shoe_md": bottom,
                            "last_od": size, "rows": [row], "indices": [index]})
    for string in strings:
        string["sections"] = segmenter(string["rows"], string["top_md"], string["shoe_md"], string["description"])
    # Running passage and nested installation fit are independent of the final
    # annular wall. Check all overlapping measured sections, including shells.
    for i, left in enumerate(strings):
        for right in strings[i+1:]:
            for a in left["sections"]:
                for b in right["sections"]:
                    if min(a["bottom_md"], b["bottom_md"]) <= max(a["top_md"], b["top_md"]):
                        continue
                    outer, inner = (a, b) if a["od_in"] > b["od_in"] else (b, a)
                    if outer["id_in"] <= inner["od_in"]:
                        raise ValueError("Installed strings overlap without physical ID/OD clearance or have duplicate identity.")
    for child in strings:
        if child["description"] not in ("Previous Liner Shoe", "Liner Shoe"):
            continue
        first = child["sections"][0]
        hosts = [s for s in strings if s is not child and any(
            sec["top_md"] <= child["top_md"] < sec["bottom_md"] and sec["id_in"] > first["od_in"]
            for sec in s["sections"])]
        if not hosts:
            raise ValueError("Historical Liner requires an applicable measured host with positive lap.")
    if previous is not None:
        hosts = [sec for string in strings if string is not previous for sec in string["sections"]]
        # Enclosing strings restrict installation; an inner historical string
        # is not an enclosing host for this already installed outer body.
        largest = max(sec["od_in"] for sec in previous["sections"])
        require_running_fit([sec for sec in hosts if sec["od_in"] > largest], previous["sections"])
        for section in previous["sections"]:
            a, b = section["top_md"], section["bottom_md"]
            bounds = sorted({a, b, *(max(a, min(b, sec[key])) for sec in hosts
                                    for key in ("top_md", "bottom_md"))})
            for left, right in zip(bounds, bounds[1:]):
                md = (left+right)/2
                if not any(sec["top_md"] <= md < sec["bottom_md"] and sec["id_in"] > section["od_in"] for sec in hosts):
                    raise ValueError("Previous Tie Back requires measured cased host coverage throughout its body.")
    return strings


def receiving_liner(strings, tie_in):
    candidates = [s for s in strings if s["description"] in ("Previous Liner Shoe", "Liner Shoe") and s["top_md"] <= tie_in < s["shoe_md"]]
    if not candidates:
        raise ValueError("Tie Back tie-in requires one unambiguous receiving Liner interval continuing to its shoe.")
    # Retain the existing certified deepest-explicit-top connection criterion,
    # but prove it also identifies the actual innermost physical continuation.
    # Equal-ranked landings or a conflicting inner bore remain unresolved.
    deepest = max(s["top_md"] for s in candidates)
    connection = [s for s in candidates if s["top_md"] == deepest]
    diameters = {id(s): next(sec["od_in"] for sec in s["sections"]
                            if sec["top_md"] <= tie_in < sec["bottom_md"]) for s in candidates}
    smallest = min(diameters.values())
    inner = [s for s in candidates if diameters[id(s)] == smallest]
    if len(connection) != 1 or len(inner) != 1 or connection[0] is not inner[0]:
        raise ValueError("Tie Back receiving Liner connection is ambiguous or contradicts the innermost installed bore.")
    return connection[0]


def require_running_fit(sections, running):
    """The deeper running body must pass each shallower installed restriction."""
    for section in sections:
        passing = [s["od_in"] for s in running if s["bottom_md"] > section["top_md"]]
        if passing and section["id_in"] <= max(passing):
            raise ValueError("Running string cannot pass an installed Hardware ID restriction. Installed host internal diameter must exceed running OD (ID > OD); otherwise the running string cannot pass host.")


def enclosing_path(rows, strings, active, end, segmenter, *, excluded=(), excluded_below=None, running=None):
    running = active if running is None else running
    installed = [s for s in strings if not any(i in excluded for i in s["indices"])]
    if not installed and (strings or not active or any(s["description"] != "Casing" for s in active)):
        raise ValueError("Resolve Previous Casing / Previous Liner Shoe from explicit installed Hardware.")
    # A first surface-origin Casing still needs a complete measured open-hole wall.
    last_shoe = max((s["shoe_md"] for s in installed), default=0.)
    holes = []
    if last_shoe < end:
        holes = segmenter([r for r in rows if r.get("Description") == "Open Hole Size"],
                          last_shoe, end, "Open Hole Size")
    sections = [sec for s in installed for sec in s["sections"]]
    if excluded_below is not None:
        sections += [{**sec, "bottom_md": min(sec["bottom_md"], excluded_below)}
                     for s in strings if any(i in excluded for i in s["indices"])
                     for sec in s["sections"] if sec["top_md"] < excluded_below]
    require_running_fit(sections + [{**s, "id_in": s["od_in"]} for s in holes], running)
    bounds = sorted({0., end, *(min(end, sec[k]) for sec in sections+holes+active
                                for k in ("top_md", "bottom_md"))})
    result = []
    for top, bottom in zip(bounds, bounds[1:]):
        md = (top+bottom)/2
        inside = [s for s in active if s["top_md"] <= md < s["bottom_md"]]
        candidates = [s for s in sections if s["top_md"] <= md < s["bottom_md"]]
        if len(inside) != 1:
            raise ValueError("Running path requires explicit continuous Hardware, including upstream workstring.")
        if any(s["id_in"] <= inside[0]["od_in"] for s in candidates):
            raise ValueError("Running string cannot pass an installed Hardware ID restriction.")
        if candidates:
            diameter = min(s["od_in"] for s in candidates)
            wall = [s for s in candidates if s["od_in"] == diameter]
        else:
            wall = [s for s in holes if s["top_md"] <= md < s["bottom_md"]]
        if len(wall) != 1:
            raise ValueError("Effective enclosing Hardware is missing or ambiguous.")
        piece = {**wall[0], "top_md": top, "bottom_md": bottom}
        if result and result[-1]["bottom_md"] == top and all(result[-1][key] == piece[key]
                for key in ("od_in", "id_in", "description")):
            result[-1]["bottom_md"] = bottom
        else:
            result.append(piece)
    return result
