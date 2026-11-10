"""Disabled App-source geometry snapshot, version 1; no engine request or integration.

Reads only a caller's measured Hardware/selection/trajectory records. Writes
nothing. Chart, installed_geometry, placement and well_profile remain the
geometry/fit/MD→TVD authorities. There is no persistence, UI, report, template,
fluid, rheology, hydraulic or dependency change. No production caller imports
this module. ``app_source_sha`` is caller-supplied provenance, verified outside
this pure API; it is not an assertion that this function fetched GitHub.

Lengths: m MD/TVD; diameters: inches, nominal measured (never excess-adjusted).
Sections are [top_md, bottom_md); the final bottom is the closed path endpoint.
Source row numbers are zero-based positional indices, independent of DF labels.
The active path is surface→selected Shoe (DP included); the complete measured
receiving liner is retained separately, never substituted for an ER-03 Shoe.
GEOMETRY_REPRESENTABLE certifies only the source geometry shape, not readiness,
physics, directional pressure parity, HB, production, or a constructed solver.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Literal

import pandas as pd
import cement_chart_model as chart
import installed_geometry as installed
from placement import HOST_DESCRIPTIONS, hardware_choices, target_descriptions, target_depth
from project_state import fingerprint, hardware_draft_pending
from well_profile import integrate_survey, tvd_at_md, validate_well_inputs

Status = Literal['INVALID_INPUT', 'ENGINE_INTERFACE_NOT_REPRESENTABLE',
                 'GEOMETRY_REPRESENTABLE', 'NOT_APPLICABLE']
CANONICAL_DESCRIPTIONS = frozenset({
    'Casing', 'Previous Casing', 'Liner Shoe', 'Liner Lap', 'Previous Liner Shoe',
    'Previous Liner Lap', 'Tie Back Liner Shoe', 'Tie Back Liner Lap',
    'Previous Tie Back Liner Shoe', 'Previous Tie Back Liner Lap',
    'Drill Pipes', 'Open Hole Size'})
FUTURE_GATES = ('HB_YIELD_TRANSFER', 'HB_SLURRY_ROUTING', 'SCIPY_PIN',
                'SEGMENTED_TIEBACK_BOUNDARY', 'DIRECTIONAL_TVD_CONVENTION',
                'GENUINE_FANN_SOURCE', 'RENDERER_INV014')


@dataclass(frozen=True, slots=True)
class Section:
    top_md: float
    bottom_md: float
    od_in: float
    id_in: float
    description: str
    source_rows: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class InstalledString:
    description: str
    top_md: float
    shoe_md: float
    source_rows: tuple[int, ...]
    sections: tuple[Section, ...]


@dataclass(frozen=True, slots=True)
class SurveyStation:
    md: float
    deviation_deg: float
    azimuth_deg: float


@dataclass(frozen=True, slots=True)
class TVDPoint:
    md: float
    tvd: float


@dataclass(frozen=True, slots=True)
class GeometrySnapshot:
    status: Status
    reason_codes: tuple[str, ...]
    detail: str
    app_source_sha: str
    source_identity: str
    request_identity: str
    job: str
    kind: str | None = None
    target_token: str | None = None
    host_token: str | None = None
    string_top_md: float | None = None
    shoe_md: float | None = None
    active_sections: tuple[Section, ...] = ()
    enclosing_sections: tuple[Section, ...] = ()
    installed_strings: tuple[InstalledString, ...] = ()
    selected_host: InstalledString | None = None
    receiver: InstalledString | None = None
    survey: tuple[SurveyStation, ...] = ()
    trajectory: tuple[TVDPoint, ...] = ()
    future_gates: tuple[str, ...] = FUTURE_GATES
    enabled: Literal[False] = field(default=False, init=False)
    ready_to_run: Literal[False] = field(default=False, init=False)
    hb_admissible: Literal[False] = field(default=False, init=False)
    hydraulic_admissible: Literal[False] = field(default=False, init=False)


def _sections(sections, indices):
    if len(indices) < len(sections):
        raise ValueError('Every projected section requires an actual Hardware source row.')
    return tuple(Section(float(s['top_md']), float(s['bottom_md']),
                         float(s['od_in']), float(s['id_in']), s['description'], (int(i),))
                 for s, i in zip(sections, indices))


def _string(source):
    return InstalledString(source['description'], float(source['top_md']), float(source['shoe_md']),
                           tuple(source['indices']), _sections(source['sections'], source['indices']))


def snapshot_geometry(state: Mapping, *, app_source_sha: str,
                      query_md: tuple[float, ...] = ()) -> GeometrySnapshot:
    """Copy canonical geometry and classify against the pinned ER-03 interface.

    Additional query MDs use App's inclination integral, not a new survey or
    ER-03 knot interpolation. Incomplete browser drafts have their own reason;
    all invalid results contain no pretend validated geometry. No solver runs.
    """
    if not isinstance(app_source_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', app_source_sha):
        raise ValueError('app_source_sha must be the externally verified 40-character Git SHA.')
    if not isinstance(state, Mapping):
        raise ValueError('state must be an App input mapping.')
    # Copy only consumed sources; no unrelated cache, review, fluid or session mutation.
    source = deepcopy({k: state[k] for k in ('job_type', 'hardware_table', 'hardware_editor_draft',
        'placement_config', 'well_geometry', 'formation_pressure_config', 'well_data',
        chart.PORE_FIELD, chart.FRAC_FIELD) if k in state})
    source_id = fingerprint(source)
    request_id = fingerprint([1, app_source_sha, source_id, query_md])
    job = source.get('job_type')

    def invalid(code, message):
        return GeometrySnapshot('INVALID_INPUT', (code,), message, app_source_sha,
                                source_id, request_id, job if isinstance(job, str) else '')

    if job is None or job == '':
        return invalid('JOB_NOT_SELECTED', 'Select the current App job before snapshotting geometry.')
    if not isinstance(job, str):
        return invalid('JOB_INVALID', 'Job must be a canonical App string identity.')
    try:
        kind = chart.chart_job_kind(job)
    except ValueError as exc:
        return invalid('JOB_INVALID', str(exc))
    if kind is None:
        return GeometrySnapshot('NOT_APPLICABLE', ('NON_CHART_OPERATION',),
                                'This operation has no CFW128 chart geometry mapping.',
                                app_source_sha, source_id, request_id, job)
    table, config, geometry = (source.get(k) for k in ('hardware_table','placement_config','well_geometry'))
    if not isinstance(table, pd.DataFrame) or table.empty:
        return invalid('HARDWARE_MISSING', 'Committed Hardware is missing or incomplete.')
    if hardware_draft_pending(source):
        return invalid('HARDWARE_DRAFT_PENDING', 'An uncommitted Hardware draft is not an engineering contradiction.')
    if not isinstance(config, dict) or config.get('job_type') != job:
        return invalid('PLACEMENT_INCOMPLETE', 'Placement selection is missing or belongs to another job.')
    required = {'Description','MD (m)','Size (in)','ID (in)'}
    if not table.columns.is_unique or not required <= set(table.columns):
        return invalid('HARDWARE_INCOMPLETE', 'Hardware needs unique canonical geometry columns.')
    rows = table.to_dict('records')
    if any(not isinstance(r['Description'], str) or r['Description'] not in CANONICAL_DESCRIPTIONS for r in rows):
        return invalid('NONCANONICAL_HARDWARE', 'Unknown/obsolete Hardware role; no legacy aliases are admitted.')
    token = config.get('target_row')
    if not isinstance(token, str):
        return invalid('TARGET_NOT_SELECTED', 'A committed Hardware target token is missing or malformed.')
    targets = [i for i, row in enumerate(rows) if token in
               hardware_choices(pd.DataFrame([row]), target_descriptions(job))]
    if not isinstance(token, str) or len(targets) != 1 or target_depth(table, job, config) is None:
        return invalid('TARGET_NOT_SELECTED', 'Select one current unambiguous Hardware target, not a guessed depth.')
    host_token = config.get('host_row')
    if kind == 'tieback' and not isinstance(host_token, str):
        return invalid('HOST_NOT_SELECTED', 'A committed eligible Host token is missing or malformed.')
    hosts = [i for i, row in enumerate(rows) if host_token in
             hardware_choices(pd.DataFrame([row]), HOST_DESCRIPTIONS)] if kind == 'tieback' else []
    if kind == 'tieback' and (not isinstance(host_token, str) or len(hosts) != 1):
        return invalid('HOST_NOT_SELECTED', 'Select one current eligible Host; Previous Tie Back is not a Host choice.')
    if source.get('well_data') is not None and not isinstance(source['well_data'], dict):
        return invalid('APP_GEOMETRY_INVALID', 'well_data must be an App record.')
    if not isinstance(geometry, dict):
        return invalid('TRAJECTORY_INVALID', 'Canonical well_geometry is missing.')
    try:
        validate_well_inputs(geometry, {})
        if geometry.get('type') == 'Directional':
            integrated = integrate_survey(geometry.get('survey'))
            survey = tuple(SurveyStation(float(r['MD']), float(r['Deviation']), float(r['Azimuth']))
                           for r in geometry['survey'].to_dict('records'))
            knots = tuple(float(v) for v in integrated['MD'])
        else:
            survey = ()
            knots = (0., geometry.get('td_m'))
        tvd_at_md(geometry, knots)
    except (ValueError, TypeError) as exc:
        return invalid('TRAJECTORY_INVALID', str(exc))
    try:
        resolved = chart.resolve_chart_geometry(source)
        description = {'casing':'Casing','liner':'Liner Shoe','tieback':'Tie Back Liner Shoe'}[kind]
        strings = installed.physical_strings(rows, chart._segments,
                    {'Previous Casing','Casing','Previous Liner Shoe','Liner Shoe'} - {description})
        physical = tuple(_string(s) for s in strings)
        selected_host = next((s for s in physical if kind == 'tieback' and hosts[0] in s.source_rows), None)
        receiver = _string(installed.receiving_liner(strings, resolved['shoe_md'])) if kind == 'tieback' else None
        active = []
        for role in dict.fromkeys(s['description'] for s in resolved['active_string']):
            pieces = [s for s in resolved['active_string'] if s['description'] == role]
            active.extend(_sections(pieces, [i for i,r in enumerate(rows) if r['Description'] == role]))
        # Chart's path order is authoritative (DP then body); no source row sorting/repair.
        active = tuple(active)
        provenance = [sec for s in physical for sec in s.sections]
        last_shoe = max((s.shoe_md for s in physical), default=0.)
        if last_shoe < resolved['shoe_md']:
            holes = [i for i,r in enumerate(rows) if r['Description'] == 'Open Hole Size']
            provenance.extend(_sections(chart._segments([rows[i] for i in holes],last_shoe,
                                      resolved['shoe_md'],'Open Hole Size'), holes))
        outer = []
        for s in resolved['enclosing_string']:
            indices = tuple(dict.fromkeys(i for sec in provenance if sec.description == s['description']
                and (sec.od_in,sec.id_in) == (s['od_in'],s['id_in'])
                and max(sec.top_md,s['top_md']) < min(sec.bottom_md,s['bottom_md']) for i in sec.source_rows))
            if not indices:
                raise ValueError('Enclosing section has no measured source-row provenance.')
            outer.append(Section(float(s['top_md']),float(s['bottom_md']),float(s['od_in']),
                                 float(s['id_in']),s['description'],indices))
        outer = tuple(outer)
    except (ValueError, TypeError) as exc:
        return invalid('APP_GEOMETRY_INVALID', str(exc))
    try:
        tvd_at_md(geometry, query_md)  # Validate each request before set de-duplication (including bool/zero).
        boundaries = {0.,resolved['shoe_md'],*knots,*query_md,
                      *(v for s in active+outer for v in (s.top_md,s.bottom_md))}
        if receiver is not None:
            boundaries.update(v for s in receiver.sections for v in (s.top_md,s.bottom_md))
        md = sorted(boundaries)
        trajectory = tuple(TVDPoint(float(m),float(t)) for m,t in zip(md,tvd_at_md(geometry,md)))
    except (ValueError, TypeError) as exc:
        return invalid('TRAJECTORY_INVALID', str(exc))
    body = tuple(s for s in active if s.description != 'Drill Pipes')
    top = body[0].top_md
    reasons = []
    if kind == 'tieback':
        if top == 0.:
            reasons.append('POINT_A_ZERO')
        if len({s.id_in for s in outer}) != 1 or any(s.description == 'Open Hole Size' for s in outer):
            reasons.append('SEGMENTED_ENCLOSURE')
        if selected_host is None or selected_host.top_md != 0. or selected_host.shoe_md < resolved['shoe_md'] or any(
                not set(s.source_rows) <= set(selected_host.source_rows) for s in outer):
            reasons.append('HOST_NOT_FULL_PATH')
        dp = tuple(s for s in active if s.description == 'Drill Pipes')
        if top > 0. and (not dp or len({(s.id_in,s.od_in) for s in dp}) != 1):
            reasons.append('SEGMENTED_DRILL_PIPE')
        if len({(s.id_in,s.od_in) for s in body}) != 1:
            reasons.append('SEGMENTED_TIEBACK_BODY')
    status = 'ENGINE_INTERFACE_NOT_REPRESENTABLE' if reasons else 'GEOMETRY_REPRESENTABLE'
    return GeometrySnapshot(status, tuple(reasons) or (
        'SCALAR_TIEBACK_SOURCE_PROVED' if kind == 'tieback' else 'SECTION_GEOMETRY_ONLY',),
        'Source geometry only; all runtime/HB/hydraulic authorizations remain false.',
        app_source_sha, source_id, request_id, job, kind, token,
        host_token if kind == 'tieback' else None, top, float(resolved['shoe_md']),
        active, outer, physical, selected_host, receiver, survey, trajectory)
