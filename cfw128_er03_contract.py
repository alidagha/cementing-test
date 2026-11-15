"""C1: disabled structural topology preview of an already captured App snapshot.

Reads immutable A/A-C1 geometry and canonical job/role metadata; writes nothing.
No state refresh, solver, capacity, pressure, fluid, fit, UI, Word or persistence.
The geometry-model metadata import is already a dependency of GeometrySnapshot;
no chart physics/renderer is imported or executed. ER-03 sources are not loaded.
Intervals are stored in ascending MD, [top,bottom), final endpoint closed;
return travel is bottom→top. Nominal ID/OD inches, MD/TVD metres, no excess.
Captured IDs and tokens are opaque provenance, not authentication/currentness:
coherent forgery or stale replay cannot be disproved without a fresh App capture.
"""
from copy import deepcopy
from dataclasses import dataclass, field, fields, replace
import math
import re
from typing import Literal

from cfw128_adapter import (GeometrySnapshot, Section, InstalledString, SurveyStation,
                            TVDPoint, CANONICAL_DESCRIPTIONS)
from cement_chart_model import CHART_JOBS
from placement import HOST_DESCRIPTIONS
from project_state import fingerprint


@dataclass(frozen=True, slots=True)
class ReturnSection:
    wall: Section
    running: Section

    def __post_init__(self):
        _section(self.wall); _section(self.running)
        if ((self.wall.top_md,self.wall.bottom_md)!=(self.running.top_md,self.running.bottom_md)
                or self.wall.id_in <= self.running.od_in):
            raise ValueError('Return wall/body bounds or clearance are inconsistent.')

    @property
    def top_md(self): return self.wall.top_md

    @property
    def bottom_md(self): return self.wall.bottom_md


@dataclass(frozen=True, slots=True)
class TopologyPreview:
    status: str
    reason_codes: tuple[str, ...]
    upstream_status: str
    upstream_reason_codes: tuple[str, ...]
    upstream_source_identity: str
    upstream_request_identity: str
    source_identity: str
    projection_identity: str
    app_source_sha: str
    job: str
    kind: str | None
    target_token: str | None
    host_token: str | None
    string_top_md: float | None = None
    shoe_md: float | None = None
    return_top_md: float | None = None
    return_bottom_md: float | None = None
    injection_sections: tuple[Section, ...] = ()
    enclosing_sections: tuple[Section, ...] = ()
    return_sections: tuple[ReturnSection, ...] = ()
    installed_strings: tuple[InstalledString, ...] = ()
    selected_host: InstalledString | None = None
    receiver: InstalledString | None = None
    survey: tuple[SurveyStation, ...] = ()
    trajectory: tuple[TVDPoint, ...] = ()
    future_gates: tuple[str, ...] = ()
    enabled: Literal[False] = field(default=False, init=False)
    ready_to_run: Literal[False] = field(default=False, init=False)
    hb_admissible: Literal[False] = field(default=False, init=False)
    hydraulic_admissible: Literal[False] = field(default=False, init=False)
    chart_admissible: Literal[False] = field(default=False, init=False)
    scientifically_qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self):
        if self.status not in ('SOURCE_INVALID','NOT_APPLICABLE','INVALID_SNAPSHOT',
                               'STRUCTURAL_PREVIEW_ONLY','HOLD_ENGINE_CONTRACT'):
            raise ValueError('Only structural previews/holds are representable.')
        for name in ('status','upstream_status','upstream_source_identity','upstream_request_identity',
                     'source_identity','projection_identity','app_source_sha','job'):
            if type(getattr(self,name)) is not str:
                raise TypeError('Preview identities must be primitive strings.')
        for value in (self.kind,self.target_token,self.host_token):
            if value is not None and type(value) is not str:
                raise TypeError('Preview selection metadata must be primitive.')
        for value in (self.string_top_md,self.shoe_md,self.return_top_md,self.return_bottom_md):
            if value is not None and not _number(value):
                raise TypeError('Preview boundaries must be finite primitive numbers.')
        for value in (self.selected_host,self.receiver):
            if value is not None: _string(value)
        for values in (self.reason_codes,self.upstream_reason_codes,self.future_gates):
            if type(values) is not tuple or any(type(v) is not str for v in values):
                raise TypeError('Preview reasons/gates must be immutable strings.')
        for values,cls in ((self.injection_sections,Section),(self.enclosing_sections,Section),
                (self.return_sections,ReturnSection),(self.installed_strings,InstalledString),
                (self.survey,SurveyStation),(self.trajectory,TVDPoint)):
            if type(values) is not tuple or any(type(v) is not cls for v in values):
                raise TypeError('Preview geometry must be immutable typed tuples.')
        if self.injection_sections:
            _path(self.injection_sections,0.,self.shoe_md)
            _path(self.enclosing_sections,0.,self.shoe_md)
            start=self.string_top_md if self.kind=='tieback' else 0.
            if (self.return_top_md,self.return_bottom_md)!=(start,self.shoe_md):
                raise ValueError('Return boundary differs from the approved active domain.')
            if not self.return_sections or (self.return_sections[0].top_md,self.return_sections[-1].bottom_md)!=(start,self.shoe_md):
                raise ValueError('Return envelope must cover precisely its approved domain.')
            cursor=start
            for part in self.return_sections:
                if part.top_md!=cursor: raise ValueError('Return gap/overlap is not repairable.')
                cursor=part.bottom_md
        elif self.return_sections:
            raise ValueError('Invalid/unavailable source cannot carry return geometry.')

    @property
    def return_travel_md(self):
        return () if self.return_bottom_md is None else (self.return_bottom_md,self.return_top_md)


def _number(value):
    return type(value) in (int,float) and math.isfinite(value)


def _rows(values):
    if (type(values) is not tuple or not values or any(type(i) is not int or i<0 for i in values)
            or len(set(values))!=len(values)):
        raise ValueError('SOURCE_ROWS_INVALID')


def _section(s):
    if type(s) is not Section:
        raise ValueError('SECTION_TYPE_INVALID')
    if (not all(_number(v) for v in (s.top_md,s.bottom_md,s.od_in,s.id_in))
            or not 0<=s.top_md<s.bottom_md or not 0<s.id_in<=s.od_in
            or type(s.description) is not str or s.description not in CANONICAL_DESCRIPTIONS):
        raise ValueError('SECTION_DIMENSIONS_OR_ROLE_INVALID')
    if (s.description=='Open Hole Size') != (s.od_in==s.id_in):
        raise ValueError('SECTION_WALL_TYPE_INVALID')
    _rows(s.source_rows)


def _path(parts,top,bottom):
    if type(parts) is not tuple or not parts:
        raise ValueError('PATH_MISSING')
    cursor=top
    for s in parts:
        _section(s)
        if s.top_md!=cursor:
            raise ValueError('PATH_GAP_OVERLAP_OR_ORDER')
        cursor=s.bottom_md
    if cursor!=bottom:
        raise ValueError('PATH_ENDPOINT_MISMATCH')


def _string(s):
    if type(s) is not InstalledString or s.description not in (
            'Previous Casing','Casing','Previous Liner Shoe','Liner Shoe','Previous Tie Back Liner Shoe'):
        raise ValueError('INSTALLED_ROLE_INVALID')
    if not _number(s.top_md) or not _number(s.shoe_md) or not 0<=s.top_md<s.shoe_md:
        raise ValueError('INSTALLED_BOUNDS_INVALID')
    if (s.description in ('Casing','Previous Casing') and s.top_md!=0.
            or s.description in ('Liner Shoe','Previous Liner Shoe') and s.top_md<=0.):
        raise ValueError('INSTALLED_ORIGIN_INVALID')
    _rows(s.source_rows); _path(s.sections,s.top_md,s.shoe_md)
    if (any(sec.description!=s.description for sec in s.sections)
            or tuple(i for sec in s.sections for i in sec.source_rows)!=s.source_rows):
        raise ValueError('INSTALLED_PROVENANCE_INVALID')


def _validate(s):
    if s.job not in CHART_JOBS or CHART_JOBS[s.job]!=s.kind or s.kind not in ('casing','liner','tieback'):
        raise ValueError('OPERATION_METADATA_INVALID')
    if (not _number(s.string_top_md) or not _number(s.shoe_md)
            or not 0<=s.string_top_md<s.shoe_md):
        raise ValueError('ACTIVE_BOUNDS_INVALID')
    if not isinstance(s.target_token,str) or not re.fullmatch('[0-9a-f]{64}',s.target_token):
        raise ValueError('TARGET_IDENTITY_INVALID')
    _path(s.active_sections,0.,s.shoe_md); _path(s.enclosing_sections,0.,s.shoe_md)
    body_role={'casing':'Casing','liner':'Liner Shoe','tieback':'Tie Back Liner Shoe'}[s.kind]
    body=tuple(v for v in s.active_sections if v.description==body_role)
    dp=tuple(v for v in s.active_sections if v.description=='Drill Pipes')
    if not body or s.active_sections!=dp+body or body[0].top_md!=s.string_top_md:
        raise ValueError('ACTIVE_ROLE_OR_TOP_MISMATCH')
    if s.kind=='casing' and (dp or s.string_top_md!=0.):
        raise ValueError('CASING_TOP_INVALID')
    if type(s.installed_strings) is not tuple:
        raise ValueError('INSTALLED_TYPE_INVALID')
    physical=[];used=[]
    for string in s.installed_strings:
        _string(string);physical.extend(string.sections);used.extend(string.source_rows)
    active_rows=tuple(i for sec in s.active_sections for i in sec.source_rows)
    if (len(set(active_rows))!=len(active_rows)
            or sum(v.description=='Previous Tie Back Liner Shoe' for v in s.installed_strings)>1):
        raise ValueError('DUPLICATE_ACTIVE_OR_PREVIOUS_STRING')
    for i,a in enumerate(physical):
        for b in physical[i+1:]:
            if max(a.top_md,b.top_md)<min(a.bottom_md,b.bottom_md):
                outer,inner=(a,b) if a.od_in>b.od_in else (b,a)
                if outer.id_in<=inner.od_in:
                    raise ValueError('INSTALLED_NESTING_CLEARANCE_INVALID')
    if len(set(used))!=len(used) or set(used)&set(active_rows):
        raise ValueError('DUPLICATE_PHYSICAL_SOURCE_ROWS')
    # Independently retain the App's full upstream running-fit restriction.
    for wall in physical:
        if any(run.bottom_md>wall.top_md and run.od_in>=wall.id_in for run in s.active_sections):
            raise ValueError('RUNNING_CLEARANCE_INVALID')
    if s.kind=='tieback':
        if (type(s.selected_host) is not InstalledString or s.selected_host not in s.installed_strings
                or s.selected_host.description not in HOST_DESCRIPTIONS
                or not isinstance(s.host_token,str) or not re.fullmatch('[0-9a-f]{64}',s.host_token)):
            raise ValueError('SELECTED_HOST_IDENTITY_INVALID')
        if (type(s.receiver) is not InstalledString or s.receiver not in s.installed_strings
                or s.receiver.description not in ('Previous Liner Shoe','Liner Shoe')
                or not s.receiver.top_md<=s.shoe_md<s.receiver.shoe_md):
            raise ValueError('RECEIVER_CONNECTION_INVALID')
        wall=next(v for v in s.enclosing_sections if v.top_md<=s.string_top_md<v.bottom_md)
        if not any(v.top_md<=s.string_top_md<v.bottom_md and (v.od_in,v.id_in)==(wall.od_in,wall.id_in)
                   and set(wall.source_rows)<=set(v.source_rows) for v in s.selected_host.sections):
            raise ValueError('SELECTED_HOST_NOT_IMMEDIATE_AT_TOP')
    elif s.selected_host is not None or s.receiver is not None or s.host_token is not None:
        raise ValueError('UNRELATED_CONNECTION_METADATA')
    # Validation sweep only; never sort/repair input or choose/build a substitute wall.
    left=0.
    while left<s.shoe_md:
        edges=[v for sec in (*s.active_sections,*s.enclosing_sections,*physical)
               for v in (sec.top_md,sec.bottom_md) if left<v<=s.shoe_md]
        right=min(edges)
        run=next(v for v in s.active_sections if v.top_md<=left and right<=v.bottom_md)
        wall=next(v for v in s.enclosing_sections if v.top_md<=left and right<=v.bottom_md)
        if wall.id_in<=run.od_in:
            raise ValueError('ANNULAR_CLEARANCE_INVALID')
        covered=[v for v in physical if v.top_md<=left and right<=v.bottom_md]
        matches=[v for v in covered if (v.od_in,v.id_in,v.description)==(wall.od_in,wall.id_in,wall.description)
                 and set(wall.source_rows)<=set(v.source_rows)]
        if wall.description=='Open Hole Size':
            if covered or set(wall.source_rows)&(set(used)|{i for v in s.active_sections for i in v.source_rows}):
                raise ValueError('OPEN_HOLE_SUBSTITUTES_INSTALLED_WALL')
        elif not matches or any(v.od_in<wall.od_in for v in covered):
            raise ValueError('ENCLOSING_PROVENANCE_OR_IMMEDIACY_INVALID')
        left=right
    if type(s.survey) is not tuple or type(s.trajectory) is not tuple or not s.trajectory:
        raise ValueError('TRAJECTORY_MISSING')
    previous=-1.
    for point in s.trajectory:
        if (type(point) is not TVDPoint or not _number(point.md) or not _number(point.tvd)
                or point.md<0 or point.md<=previous):
            raise ValueError('TRAJECTORY_ORDER_OR_VALUE_INVALID')
        previous=point.md
    md={p.md for p in s.trajectory}
    if not {0.,s.shoe_md,s.string_top_md,*(v for sec in s.active_sections+s.enclosing_sections
                                          for v in (sec.top_md,sec.bottom_md))}<=md:
        raise ValueError('TRAJECTORY_BOUNDARY_MISSING')
    previous=-1.
    for p in s.survey:
        if (type(p) is not SurveyStation or not all(_number(v) for v in (p.md,p.deviation_deg,p.azimuth_deg))
                or p.md<=previous or p.md<0 or not 0<=p.deviation_deg<=180 or not 0<=p.azimuth_deg<360 or p.md not in md):
            raise ValueError('SURVEY_ORDER_OR_VALUE_INVALID')
        previous=p.md
    if s.survey:
        if s.survey[0].md!=0. or s.survey[-1].md<s.trajectory[-1].md:
            raise ValueError('SURVEY_COVERAGE_INVALID')
    elif any(p.tvd!=p.md for p in s.trajectory):
        raise ValueError('VERTICAL_TVD_INVALID')


def _token(v):
    if v is None: return ('None',)
    if type(v) is int: return ('int',hex(v))
    if type(v) is float: return ('float',v.hex())
    if type(v) in (str,bool): return (type(v).__name__,str(v))
    if type(v) in (tuple,list): return (type(v).__name__,tuple(_token(x) for x in v))
    if type(v) in (GeometrySnapshot,Section,InstalledString,SurveyStation,TVDPoint):
        return (type(v).__name__,tuple((f.name,_token(getattr(v,f.name))) for f in fields(v)))
    raise TypeError('Only captured geometry dataclasses and primitive source fields are accepted.')


def prepare_er03_preview(snapshot: GeometrySnapshot, *, expected_app_source_sha: str) -> TopologyPreview:
    """Capture-time structural preview only; never a solver design/currentness proof."""
    if type(snapshot) is not GeometrySnapshot:
        raise TypeError('Provide the actual immutable GeometrySnapshot.')
    if type(expected_app_source_sha) is not str or not re.fullmatch('[0-9a-f]{40}',expected_app_source_sha):
        raise ValueError('Expected App SHA must be 40 lowercase hex characters.')
    if snapshot.app_source_sha!=expected_app_source_sha:
        raise ValueError('Captured App SHA differs from caller-verified expected SHA.')
    if any(type(v) is not str for v in (snapshot.status,snapshot.source_identity,snapshot.request_identity,snapshot.job)):
        raise TypeError('Snapshot identity/status/job must be primitive strings.')
    if any(v is not None and type(v) is not str for v in (snapshot.kind,snapshot.target_token,snapshot.host_token)):
        raise TypeError('Snapshot selection metadata must be primitive.')
    if type(snapshot.reason_codes) is not tuple or any(type(v) is not str for v in snapshot.reason_codes):
        raise TypeError('Snapshot reasons must be immutable strings.')
    source_id=fingerprint(['cfw128-c1-source/1',expected_app_source_sha,_token(snapshot)])
    def result(status,codes,valid=False):
        reasons=tuple(dict.fromkeys((*snapshot.reason_codes,*codes)))
        if not valid:
            return TopologyPreview(status,reasons,snapshot.status,snapshot.reason_codes,
                snapshot.source_identity,snapshot.request_identity,source_id,
                fingerprint(['cfw128-c1-projection/1',source_id,status,reasons]),
                expected_app_source_sha,snapshot.job,snapshot.kind,snapshot.target_token,snapshot.host_token)
        source=deepcopy(snapshot);top=source.string_top_md if source.kind=='tieback' else 0.
        returns=[];left=top
        while left<source.shoe_md:
            wall=next(v for v in source.enclosing_sections if v.top_md<=left<v.bottom_md)
            run=next(v for v in source.active_sections if v.top_md<=left<v.bottom_md)
            right=min(wall.bottom_md,run.bottom_md,source.shoe_md)
            returns.append(ReturnSection(replace(wall,top_md=left,bottom_md=right),
                                         replace(run,top_md=left,bottom_md=right)));left=right
        projected=fingerprint(['cfw128-c1-projection/1',source_id,status,reasons,top,source.shoe_md,
                               tuple((_token(v.wall),_token(v.running)) for v in returns)])
        return TopologyPreview(status,reasons,source.status,source.reason_codes,
            source.source_identity,source.request_identity,source_id,projected,expected_app_source_sha,
            source.job,source.kind,source.target_token,source.host_token,source.string_top_md,source.shoe_md,
            top,source.shoe_md,source.active_sections,source.enclosing_sections,tuple(returns),
            source.installed_strings,source.selected_host,source.receiver,source.survey,source.trajectory,source.future_gates)
    if snapshot.status=='INVALID_INPUT': return result('SOURCE_INVALID',())
    if snapshot.status=='NOT_APPLICABLE': return result('NOT_APPLICABLE',())
    if snapshot.status not in ('GEOMETRY_REPRESENTABLE','ENGINE_INTERFACE_NOT_REPRESENTABLE'):
        return result('INVALID_SNAPSHOT',('UPSTREAM_STATUS_INVALID',))
    try:
        if any(not re.fullmatch('[0-9a-f]{64}',v) for v in (snapshot.source_identity,snapshot.request_identity)):
            raise ValueError('SOURCE_IDENTITY_INVALID')
        if any(getattr(snapshot,f) is not False for f in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible')):
            raise ValueError('UNSUPPORTED_AUTHORIZATION_CLAIM')
        _validate(snapshot)
    except ValueError as exc:
        return result('INVALID_SNAPSHOT',(str(exc),))
    codes=['CAPTURED_SOURCE_ONLY_NOT_CURRENTNESS_PROOF']
    if snapshot.kind=='tieback':
        codes.extend(('TIEBACK_RETURN_TERMINATES_AT_TOP','ER03_SCALAR_PATH_MISMATCH',
            'UAT19_TIEBACK_PARTIAL_RETURN_ENGINE_NOT_VALIDATED','TIEBACK_OUTLET_PRESSURE_BC_UNDEFINED'))
        if snapshot.string_top_md==0.: codes.append('POINT_A_ZERO')
    if snapshot.survey: codes.append('DIRECTIONAL_INTERIOR_TVD_CONVENTION_HOLD')
    return result('HOLD_ENGINE_CONTRACT' if snapshot.kind=='tieback' or snapshot.survey
                  or snapshot.status=='ENGINE_INTERFACE_NOT_REPRESENTABLE' else 'STRUCTURAL_PREVIEW_ONLY',codes,True)
