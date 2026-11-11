"""Disabled pump-end occupancy assessment, never static/final/post-pull TOC.

Reads caller's frozen C2e-1/C2d-1 captures and published primitive bindings;
uses existing App nominal capacity, slurry taxonomy and fingerprint authorities.
Writes/state/schema/UI/report/dependency changes: none. No CFW import/callback,
Hardware parsing, fluid tracking replay, pressure or post-pull remapping.
Bindings/consistency are NOT authenticity or currentness proof. A coherent
forgery/replay cannot authenticate live App state. IEEE rounding intervals below
validate already-rounded summaries, never grant approximate terminal acceptance:
any unresolved exact volume reconciliation holds the TOC candidate.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from fractions import Fraction
import math
import re
from typing import Literal

from cement_chart_model import _capacity
from engineering_tools import require_fluid_density
from materials_db import PLACEMENT_SLURRIES, HYDRAULIC_EXECUTION_ORDER
from project_state import fingerprint

_FLAGS=('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified')
_TAGS={
 'cfw128_adapter':('GeometrySnapshot','Section','InstalledString','SurveyStation','TVDPoint'),
 'cfw128_er03_contract':('TopologyPreview','ReturnSection'),
 'cfw128_er03_boundary':('BoundaryHold','PhysicalPort'),
 'cfw128_er03_volume':('FrozenCapacityAudit','CapacitySection'),
 'cfw128_c2d_geometry_view':('GeometryView','NominalSection'),
 'cfw128_c2e_volume_tracking':('TrackingPreview','Stage','PathSection','Occupancy','StageLedger'),
}


def _tree(v):
    if v is None:return ('None',)
    if type(v) is str:return ('str',v)
    if type(v) is bool:return ('bool',str(v))
    if type(v) is int:return ('int',hex(v))
    if type(v) is float:
        if not math.isfinite(v):raise ValueError('Nonfinite captured value.')
        return ('float',v.hex())
    if type(v) is tuple:return ('tuple',tuple(_tree(x) for x in v))
    c=type(v)
    if c.__name__ not in _TAGS.get(c.__module__,()) or not is_dataclass(v) or not c.__dataclass_params__.frozen or not hasattr(c,'__slots__'):
        raise TypeError('Published deeply frozen primitive format required.')
    for f in fields(v):
        if f.name in _FLAGS and getattr(v,f.name) is not False:raise ValueError('Release gate must remain False.')
    return (c.__name__,tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v)))


def _kind(v,module,name):
    if (type(v).__module__,type(v).__name__)!=(module,name):raise TypeError('Unexpected captured format.')


def _q(v,positive=False):
    if type(v) not in (float,int):raise ValueError('Finite numeric measurement required.')
    try:valid=math.isfinite(v)
    except OverflowError:valid=False
    if not valid or v<0 or positive and v==0:raise ValueError('Invalid/nonfinite measurement.')
    return Fraction(v)


def _round_range(v):
    """Exact half-ULP bounds of an existing finite float, not a tolerance."""
    x=_q(v)
    if type(v) is int or v==0:return x,x
    lo,hi=math.nextafter(v,-math.inf),math.nextafter(v,math.inf)
    if not math.isfinite(hi):raise ValueError('Overflow boundary is not qualified.')
    return (Fraction(lo)+x)/2,(Fraction(hi)+x)/2


def _sum_range(values):
    bounds=tuple(_round_range(x) for x in values)
    return sum((a for a,b in bounds),Fraction(0)),sum((b for a,b in bounds),Fraction(0))


def _reconciles(left,right):
    a,b=_sum_range(left);c,d=_sum_range(right)
    if max(a,c)>min(b,d):raise ValueError('Impossible volume ledger/occupancy claim.')
    return sum(map(Fraction,left),Fraction(0))==sum(map(Fraction,right),Fraction(0))


def _identity(v):
    if type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v):raise ValueError('Invalid captured identity.')


def _bind(t,g,sha):
    _tree(t);_tree(g);_kind(t,'cfw128_c2e_volume_tracking','TrackingPreview');_kind(g,'cfw128_c2d_geometry_view','GeometryView')
    if type(sha) is not str or not re.fullmatch('[0-9a-f]{40}',sha) or t.app_source_sha!=sha or g.app_source_sha!=sha:
        raise ValueError('Expected verified App SHA differs.')
    if (t.status!='DISABLED_VOLUME_TRACKING_PREVIEW' or t.currentness!='NOT_CURRENTNESS_PROOF'
            or t.hydraulics!='HYDRAULICS_NOT_EVALUATED' or t.toc!='TOC_NOT_EVALUATED'
            or g.status!='DISABLED_GEOMETRY_VIEW' or g.currentness!='NOT_CURRENTNESS_PROOF'
            or g.corridor_contract!='OWNER_SURFACE_CONNECTED_2026_11_11'
            or g.hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc!='NOT_EVALUATED'):
        raise ValueError('Only held, surface-connected captured previews are supported.')
    for v in (t.source_identity,t.projection_identity,g.source_identity,g.projection_identity):_identity(v)
    if (t.geometry_source_identity,t.geometry_projection_identity)!=(g.source_identity,g.projection_identity):
        raise ValueError('Tracking/geometry source mismatch; fresh paired captures required.')
    s,a=g.captured_geometry,g.historical_capacity_audit
    _kind(s,'cfw128_adapter','GeometrySnapshot');_kind(a,'cfw128_er03_volume','FrozenCapacityAudit')
    _kind(a.boundary,'cfw128_er03_boundary','BoundaryHold');p=a.boundary.preview
    _kind(p,'cfw128_er03_contract','TopologyPreview')
    if (s.app_source_sha!=sha or a.expected_app_source_sha!=sha or p.app_source_sha!=sha
            or s.status not in ('GEOMETRY_REPRESENTABLE','ENGINE_INTERFACE_NOT_REPRESENTABLE')
            or s.kind not in ('casing','liner','tieback') or s.job!=p.job
            or (s.source_identity,s.request_identity)!=(p.upstream_source_identity,p.upstream_request_identity)
            or (s.target_token,s.host_token)!=(p.target_token,p.host_token)
            or _tree(s.selected_host)!=_tree(p.selected_host) or _tree(s.receiver)!=_tree(p.receiver)):
        raise ValueError('Paired captured source/provenance differs.')
    source=fingerprint(['c2d1-captured-input/1',sha,_tree(s),_tree(a)])
    def token(v):
        if type(v).__module__=='cfw128_c2d_geometry_view' and type(v).__name__=='NominalSection':
            return tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v))
        if type(v) is tuple:return tuple(token(x) for x in v)
        return v
    values=(g.status,g.injection,g.lower_annulus,g.upper_pumping_annulus,g.upper_post_pull_bore)
    if source!=g.source_identity or g.projection_identity!=fingerprint(['c2d1-view/1',source,sha,token(values),g.corridor_contract,g.currentness]):
        raise ValueError('Captured geometry binding differs.')
    plain=lambda rows:tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)
    if t.projection_identity!=fingerprint(['cfw128-c2e-volume/1',t.source_identity,t.cumulative_injected_bbl,
            plain(t.occupancy),plain(t.ledgers),t.mud_remaining_bbl,t.mud_displaced_bbl]):
        raise ValueError('Captured tracking projection differs.')
    if t.trajectory!=tuple((v.md,v.tvd) for v in s.trajectory):raise ValueError('Trajectory provenance differs.')
    _q(s.string_top_md);_q(s.shoe_md,True)
    if not s.string_top_md<s.shoe_md or s.kind=='casing' and s.string_top_md!=0:raise ValueError('Invalid active Top/Shoe.')
    return s


def _path(t,g,s):
    for name,start,end in (('injection',0.,s.shoe_md),('lower_annulus',s.string_top_md,s.shoe_md),('upper_pumping_annulus',0.,s.string_top_md)):
        cursor=start
        for n in getattr(g,name):
            if n.domain!=name or n.top_md!=cursor or not n.top_md<n.bottom_md<=end:raise ValueError('Canonical leg partition differs.')
            run=[r for r in s.active_sections if r.top_md<=n.top_md and n.bottom_md<=r.bottom_md]
            wall=[r for r in s.enclosing_sections if r.top_md<=n.top_md and n.bottom_md<=r.bottom_md]
            if len(run)!=1 or name!='injection' and len(wall)!=1:raise ValueError('Ambiguous captured section source.')
            want=(0.,run[0].id_in,run[0].source_rows,()) if name=='injection' else (run[0].od_in,wall[0].id_in,run[0].source_rows,wall[0].source_rows)
            if (n.inner_diameter_in,n.outer_diameter_in,n.running_source_rows,n.wall_source_rows)!=want:raise ValueError('Captured source section differs.')
            cursor=n.bottom_md
        if cursor!=end:raise ValueError('Missing canonical leg.')
    parts=g.injection+tuple(reversed(g.lower_annulus))+tuple(reversed(g.upper_pumping_annulus))
    if not parts or len(t.path)!=len(parts):raise ValueError('Missing/duplicated pumping section.')
    volumes=[];cursor=0.;last_md=0.
    for p,n in zip(t.path,parts):
        _kind(p,'cfw128_c2e_volume_tracking','PathSection');_kind(n,'cfw128_c2d_geometry_view','NominalSection')
        _q(n.top_md);_q(n.bottom_md,True);_q(n.inner_diameter_in);_q(n.outer_diameter_in,True)
        if not n.top_md<n.bottom_md<=s.shoe_md or not n.inner_diameter_in<n.outer_diameter_in:raise ValueError('Invalid nominal section.')
        if not n.running_source_rows or n.domain!='injection' and not n.wall_source_rows:raise ValueError('Missing source rows.')
        for rows in (n.running_source_rows,n.wall_source_rows):
            if type(rows) is not tuple or any(type(i) is not int or i<0 for i in rows) or len(set(rows))!=len(rows):raise ValueError('Invalid source rows.')
        down=n.domain=='injection';inlet,outlet=(n.top_md,n.bottom_md) if down else (n.bottom_md,n.top_md)
        if n.domain not in ('injection','lower_annulus','upper_pumping_annulus'):raise ValueError('Post-pull/history cannot enter pumping.')
        cap=_capacity(n.outer_diameter_in,n.inner_diameter_in);volumes.append(cap*(n.bottom_md-n.top_md))
        try:end=math.fsum(volumes)
        except OverflowError:raise ValueError('Nominal capacity overflow.') from None
        _q(end,True)
        if end<=cursor or inlet!=last_md:raise ValueError('Pumping gap/overlap or precision loss.')
        want=(n.domain,inlet,outlet,cursor,end,cap,n.running_source_rows,n.wall_source_rows)
        if tuple(getattr(p,f.name) for f in fields(p))!=want:raise ValueError('Pumping path/source differs from supplied canonical view.')
        cursor=end;last_md=outlet
    if last_md!=0. or t.total_nominal_capacity_bbl!=cursor:raise ValueError('Invalid surface-connected nominal total.')


@dataclass(frozen=True,slots=True)
class CementInterval:
    fluid: str
    domain: str
    section_index: int
    top_md: float
    bottom_md: float
    retained_bbl: float
    running_source_rows: tuple[int,...]
    wall_source_rows: tuple[int,...]


@dataclass(frozen=True,slots=True)
class CementStagePlacement:
    fluid: str
    configured_bbl: float
    entered_bbl: float
    retained_injection_bbl: float
    retained_lower_annulus_bbl: float
    retained_upper_annulus_bbl: float
    ideal_surface_returned_bbl: float


@dataclass(frozen=True,slots=True)
class PlacementAssessment:
    app_source_sha: str
    geometry_source_identity: str
    geometry_projection_identity: str
    tracking_source_identity: str
    tracking_projection_identity: str
    projection_identity: str
    stages: tuple[CementStagePlacement,...]
    annular_intervals: tuple[CementInterval,...]
    other_fluid_occupancy: tuple[tuple[str,int,float,float,float],...]
    surface_cement_return_present: bool
    pumping_state_toc_candidate_md: float | None
    reason_codes: tuple[str,...]
    post_pull_reason: Literal['NOT_APPLICABLE','HOLD_POST_PULL_REMAP_UNDEFINED']
    status: Literal['DISABLED_PUMP_END_PLACEMENT_PREVIEW']=field(default='DISABLED_PUMP_END_PLACEMENT_PREVIEW',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['HYDRAULICS_NOT_EVALUATED']=field(default='HYDRAULICS_NOT_EVALUATED',init=False)
    final_post_pull_toc: Literal['FINAL_POST_PULL_TOC_NOT_EVALUATED']=field(default='FINAL_POST_PULL_TOC_NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def assess_cement_placement(tracking: object, geometry: object, *, expected_app_source_sha: str) -> PlacementAssessment:
    """Summarize captured occupancy only; never replay stage displacement.

    Raises ValueError/TypeError for inconsistent/unsupported input. Valid but
    nonterminal, disconnected or not exactly reconcilable records receive HOLDs.
    """
    t,g=tracking,geometry;s=_bind(t,g,expected_app_source_sha);_path(t,g,s)
    V=_q(t.cumulative_injected_bbl);capacity=_q(t.total_nominal_capacity_bbl,True);_q(t.initial_mud_density_pcf,True)
    names=tuple(v.name for v in t.stages)
    if len(set(names))!=len(names) or names!=tuple(n for n in HYDRAULIC_EXECUTION_ORDER if n in names):raise ValueError('Invalid stage order/identity.')
    densities={'Mud':t.initial_mud_density_pcf};total=Fraction(0)
    for v in t.stages:
        _kind(v,'cfw128_c2e_volume_tracking','Stage');vol=_q(v.volume_bbl,True);raw=_q(v.raw_volume,True)
        if type(v.raw_density) not in (str,int,float):raise ValueError('Invalid raw density source.')
        if vol!=raw or v.source not in ('fluids_config.params','fluid_data') or v.density_pcf!=require_fluid_density(v.name,v.raw_density):raise ValueError('Invalid stage source/value.')
        _q(v.density_pcf,True)
        if v.name=='Displacement Fluid' and v.density_pcf!=t.initial_mud_density_pcf:raise ValueError('Mud/displacement source density differs.')
        total+=vol;densities[v.name]=v.density_pcf
    try:finite=math.isfinite(float(total))
    except OverflowError:finite=False
    if not finite:raise ValueError('Schedule overflow.')
    if V>total and not _round_range(t.cumulative_injected_bbl)[0]<=total<=_round_range(t.cumulative_injected_bbl)[1]:raise ValueError('Injected volume exceeds schedule.')
    if tuple(v.fluid for v in t.ledgers)!=names:raise ValueError('Missing/duplicate/unmatched stage ledgers.')
    groups=[[] for _ in t.path];seen=set();byfluid={n:[] for n in densities}
    for o in t.occupancy:
        _kind(o,'cfw128_c2e_volume_tracking','Occupancy')
        if o.fluid not in densities or o.density_pcf!=densities[o.fluid] or type(o.section_index) is not int or not 0<=o.section_index<len(t.path):raise ValueError('Unknown occupancy identity/section.')
        key=o.fluid,o.section_index
        if key in seen:raise ValueError('Duplicate occupancy partition.')
        seen.add(key);_q(o.volume_bbl,True);_q(o.inlet_md);_q(o.outlet_md)
        p=t.path[o.section_index];down=p.outlet_md>p.inlet_md
        if not (p.inlet_md<=o.inlet_md<o.outlet_md<=p.outlet_md if down else p.outlet_md<=o.outlet_md<o.inlet_md<=p.inlet_md):raise ValueError('Invalid occupied MD interval.')
        groups[o.section_index].append(o);byfluid[o.fluid].append(o)
    exact=True
    for p,rows in zip(t.path,groups):
        rows.sort(key=lambda o:o.inlet_md,reverse=p.outlet_md<p.inlet_md)
        cursor=p.inlet_md;width=Fraction(p.end_bbl)-Fraction(p.start_bbl);lo=hi=Fraction(0)
        def md(x):
            if x<=0:return p.inlet_md
            if x>=width:return p.outlet_md
            return p.inlet_md+float(x/width)*(p.outlet_md-p.inlet_md)
        for o in rows:
            if o.inlet_md!=cursor:raise ValueError('Occupied section gap/overlap.')
            a,b=_round_range(o.volume_bbl);lo+=a;hi+=b
            bounds=sorted((md(lo),md(hi)))
            if not bounds[0]<=o.outlet_md<=bounds[1]:raise ValueError('Occupied volume/MD mapping differs.')
            cursor=o.outlet_md
        if cursor!=p.outlet_md or not lo<=width<=hi:raise ValueError('Incomplete occupied nominal section.')
        exact &= sum((Fraction(o.volume_bbl) for o in rows),Fraction(0))==width
    for stage,ledger in zip(t.stages,t.ledgers):
        _kind(ledger,'cfw128_c2e_volume_tracking','StageLedger')
        entered=_q(ledger.entered_bbl);_q(ledger.in_path_bbl);_q(ledger.ideal_returned_bbl)
        if entered>Fraction(stage.volume_bbl):raise ValueError('Stage entered beyond configured source.')
        exact &= _reconciles([ledger.entered_bbl],[ledger.in_path_bbl,ledger.ideal_returned_bbl])
        exact &= _reconciles([ledger.in_path_bbl],[o.volume_bbl for o in byfluid[stage.name]])
    _q(t.mud_remaining_bbl);_q(t.mud_displaced_bbl)
    exact &= _reconciles([t.mud_remaining_bbl],[o.volume_bbl for o in byfluid['Mud']])
    exact &= _reconciles([t.total_nominal_capacity_bbl],[t.mud_remaining_bbl,t.mud_displaced_bbl])
    exact &= _reconciles([t.total_nominal_capacity_bbl],[t.mud_remaining_bbl]+[v.in_path_bbl for v in t.ledgers])
    exact &= _reconciles([t.cumulative_injected_bbl],[v.entered_bbl for v in t.ledgers])
    holds=[];complete=V==total and all(v.entered_bbl==w.volume_bbl for v,w in zip(t.ledgers,t.stages))
    if not complete:
        holds.append('HOLD_TERMINAL_VOLUME_PRECISION_UNPROVEN' if all(v.entered_bbl==w.volume_bbl for v,w in zip(t.ledgers,t.stages)) else 'HOLD_SCHEDULE_INCOMPLETE')
    if not exact:holds.append('HOLD_VOLUME_RECONCILIATION_PRECISION')
    intervals=[];placements=[];others=[]
    for stage,ledger in zip(t.stages,t.ledgers):
        if stage.name not in PLACEMENT_SLURRIES:continue
        amounts={n:math.fsum(o.volume_bbl for o in byfluid[stage.name] if t.path[o.section_index].domain==n) for n in ('injection','lower_annulus','upper_pumping_annulus')}
        placements.append(CementStagePlacement(stage.name,stage.volume_bbl,ledger.entered_bbl,amounts['injection'],amounts['lower_annulus'],amounts['upper_pumping_annulus'],ledger.ideal_returned_bbl))
    for o in t.occupancy:
        p=t.path[o.section_index]
        if o.fluid not in PLACEMENT_SLURRIES:others.append((o.fluid,o.section_index,o.inlet_md,o.outlet_md,o.volume_bbl))
        elif p.domain!='injection':intervals.append(CementInterval(o.fluid,p.domain,o.section_index,min(o.inlet_md,o.outlet_md),max(o.inlet_md,o.outlet_md),o.volume_bbl,p.running_source_rows,p.wall_source_rows))
    intervals.sort(key=lambda o:o.top_md)
    if not placements:holds.append('HOLD_NO_PLACED_CEMENT')
    if any(v.retained_injection_bbl>0 for v in placements):holds.append('HOLD_CEMENT_REMAINS_IN_INJECTION')
    if not intervals:holds.append('HOLD_NO_ANNULAR_CEMENT')
    else:
        if intervals[-1].bottom_md!=s.shoe_md:holds.append('HOLD_CEMENT_NOT_ANCHORED_AT_SHOE')
        if any(a.bottom_md!=b.top_md for a,b in zip(intervals,intervals[1:])):holds.append('HOLD_DISCONNECTED_ANNULAR_CEMENT')
    candidate=intervals[0].top_md if intervals and not holds else None
    post='NOT_APPLICABLE' if s.kind=='casing' else 'HOLD_POST_PULL_REMAP_UNDEFINED'
    encode=lambda rows:tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)
    identity=fingerprint(['cfw128-c2e2-placement/1',expected_app_source_sha,g.source_identity,g.projection_identity,t.source_identity,t.projection_identity,
                          encode(placements),encode(intervals),tuple(others),candidate,tuple(holds),post])
    return PlacementAssessment(expected_app_source_sha,g.source_identity,g.projection_identity,t.source_identity,t.projection_identity,identity,
                               tuple(placements),tuple(intervals),tuple(others),any(v.ideal_surface_returned_bbl>0 for v in placements),candidate,tuple(holds),post)
