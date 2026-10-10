"""Round 7A inputs and v2.2 radius-of-curvature survey, without chart code."""
import math
from numbers import Real

import pandas as pd

SURVEY_COLUMNS = ("MD", "Deviation", "Azimuth")
EPS = 1e-9
M_TO_FT = 3.28084


def geometry_defaults():
    return {"version": 1, "type": None, "td_m": None,
            "survey": pd.DataFrame(columns=SURVEY_COLUMNS)}


def geothermal_defaults():
    return {"version": 1, "source": None, "surface_temp": 80.0, "value": None}


def _number(value, path):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number.")
    return float(value)


def _missing_cell(value):
    # A saved null in a numeric DataFrame becomes NaN; JSON NaN is rejected
    # before deserialization. An unfinished station remains a repairable draft.
    return value is None or value is pd.NA or isinstance(value, float) and math.isnan(value)


def validate_well_inputs(geometry, geothermal):
    """Trust-boundary shape/range validation; missing inputs are valid drafts."""
    for record, keys, path in ((geometry, geometry_defaults(), "well_geometry"),
                               (geothermal, geothermal_defaults(), "geothermal_config")):
        if not isinstance(record, dict) or any(key not in keys for key in record):
            raise ValueError(f"{path} must be a canonical input record.")
        version = record.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version != 1:
            raise ValueError(f"{path}.version is unsupported.")
    if geometry.get("type") not in (None, "Vertical", "Directional"):
        raise ValueError("well_geometry.type must be Vertical, Directional or unfinished.")
    if geothermal.get("source") not in (None, "BHST", "Temperature Gradient"):
        raise ValueError("geothermal_config.source must be BHST, Temperature Gradient or unfinished.")
    for record, fields, path in ((geometry, ("td_m",), "well_geometry"),
                                (geothermal, ("surface_temp", "value"), "geothermal_config")):
        for field in fields:
            if record.get(field) is not None:
                _number(record[field], f"{path}.{field}")
    if geometry.get("td_m") is not None and geometry["td_m"] < 0:
        raise ValueError("well_geometry.td_m cannot be negative.")
    frame = geometry.get("survey", pd.DataFrame(columns=SURVEY_COLUMNS))
    if not isinstance(frame, pd.DataFrame) or list(frame.columns) != list(SURVEY_COLUMNS):
        raise ValueError("well_geometry.survey needs only MD, Deviation and Azimuth columns.")
    previous = None
    for index, (_, row) in enumerate(frame.iterrows()):
        for field in SURVEY_COLUMNS:
            value = row[field]
            if _missing_cell(value):
                continue
            value = _number(value, f"well_geometry.survey[{index}].{field}")
            if field == "MD":
                if index == 0 and value != 0:
                    raise ValueError("First survey station MD must equal 0.")
                if value < 0 or previous is not None and value <= previous:
                    raise ValueError("Survey MD must be strictly increasing; station order is never repaired.")
                previous = value
            elif field == "Deviation" and not 0 <= value <= 180:
                raise ValueError("Deviation must be between 0 and 180 degrees.")
            elif field == "Azimuth" and not 0 <= value < 360:
                raise ValueError("Azimuth must be >= 0 and < 360 degrees.")


def integrate_survey(frame):
    """Exact v2.2 simultaneous 3-D integration; DLS is deg/100 m.

    Portable shortest-wrap routing does not reproduce CemCADE's hidden branch
    state in rare 180-degree 3-D cases (v2.2 FINAL's documented limitation).
    """
    validate_well_inputs({"survey": frame}, {})
    if len(frame) < 2 or any(_missing_cell(v) for v in frame.to_numpy().flat):
        raise ValueError("Enter at least two complete survey stations, starting at MD 0.")
    results = []
    tvd = north = east = 0.0
    for index, (_, row) in enumerate(frame.iterrows()):
        md, inc, azi = (float(row[c]) for c in SURVEY_COLUMNS)
        dls = 0.0
        if index:
            previous = frame.iloc[index-1]
            dm = md - float(previous["MD"])
            a1, a2 = math.radians(float(previous["Deviation"])), math.radians(inc)
            p1, p2 = math.radians(float(previous["Azimuth"])), math.radians(azi)
            tvd += (dm*(math.sin(a2)-math.sin(a1))/(a2-a1)
                    if abs(a2-a1) > EPS else dm*math.cos(a1))
            dpsi = (p2-p1+math.pi) % (2*math.pi)-math.pi
            ki = (a2-a1)/dm if dm > EPS else 0.0
            kp = dpsi/dm if dm > EPS else 0.0

            def int_sin(theta, k):
                return dm*math.sin(theta) if abs(k) <= EPS else (math.cos(theta)-math.cos(theta+k*dm))/k

            def int_cos(theta, k):
                return dm*math.cos(theta) if abs(k) <= EPS else (math.sin(theta+k*dm)-math.sin(theta))/k

            north += 0.5*(int_sin(a1+p1, ki+kp)+int_sin(a1-p1, ki-kp))
            east += 0.5*(int_cos(a1-p1, ki-kp)-int_cos(a1+p1, ki+kp))
            cb = max(-1.0, min(1.0, math.cos(a1)*math.cos(a2)+math.sin(a1)*math.sin(a2)*math.cos(dpsi)))
            dls = math.degrees(math.acos(cb))/dm*100 if dm > EPS else 0.0
        results.append({"MD": md, "TVD": tvd, "DLS (deg/100 m)": dls,
                        "North": north, "East": east, "Horizontal Departure": math.hypot(north, east)})
    return pd.DataFrame(results)


def resolve_well_profile(geometry, geothermal):
    """Pure completion/resolution shared by live state, status and export."""
    projections = dict.fromkeys(("geo_md", "geo_tvd", "bhst", "geo_gradient"))
    survey = pd.DataFrame()
    issues = []
    try:
        validate_well_inputs({}, geothermal)
    except (ValueError, OverflowError) as exc:
        return projections, survey, [str(exc)]
    source, value = geothermal.get("source"), geothermal.get("value")
    surface = geothermal.get("surface_temp", 80.0)
    try:
        validate_well_inputs(geometry, {})
        if geometry.get("type") == "Vertical":
            td = geometry.get("td_m")
            if td is None or td <= 0:
                issues.append("Enter positive Vertical TD/MD.")
            else:
                projections.update(geo_md=float(td), geo_tvd=float(td))
        elif geometry.get("type") == "Directional":
            survey = integrate_survey(geometry.get("survey", pd.DataFrame(columns=SURVEY_COLUMNS)))
            projections.update(geo_md=float(survey.iloc[-1]["MD"]), geo_tvd=float(survey.iloc[-1]["TVD"]))
            if projections["geo_tvd"] <= 0:
                issues.append("Bottom-hole TVD must be positive for Geothermal/BHSP calculation.")
        else:
            issues.append("Choose Well Geometry explicitly.")
    except (ValueError, OverflowError) as exc:
        issues.append(str(exc))
    # The selected measured source stays authoritative while independent
    # geometry/surface inputs are unfinished; only its counterpart is derived.
    if source is not None and value is not None:
        projections["bhst" if source == "BHST" else "geo_gradient"] = float(value)
    try:
        if source is None:
            issues.append("Choose Temperature Source explicitly.")
        elif value is None or surface is None:
            issues.append("Enter Surface Temperature and the selected temperature source value.")
        elif projections["geo_tvd"] is not None and projections["geo_tvd"] > 0:
            tvd_ft = projections["geo_tvd"]*M_TO_FT
            if source == "BHST":
                projections.update(bhst=float(value), geo_gradient=(value-surface)/tvd_ft*100)
            else:
                projections.update(geo_gradient=float(value), bhst=surface+value*(tvd_ft/100))
            if any(v is not None and not math.isfinite(v) for v in projections.values()):
                projections["geo_gradient" if source == "BHST" else "bhst"] = None
                issues.append("Geothermal result must be finite; review the inputs.")
    except (ValueError, OverflowError) as exc:
        issues.append(str(exc))
    return projections, survey, issues
