"""Disabled nominal volume-coordinate preview; never an App execution path.

Reads a caller-captured C2d-1 frozen view and selected Phase IV source fields.
Writes/persistence/schema/UI/report/dependency impact: none. Existing authorities:
App nominal _capacity, Phase IV density/eligibility and hydraulic stage ordering.
No imports/callbacks into CFW captures/proofs, numerical engines or renderers.
Published primitive bindings detect inconsistent copies, NOT authenticity or fresh
Hardware. A coherent counterfeit/replayed capture is NOT_CURRENTNESS_PROOF.
Float fsum prefix coordinates define nominal section boundaries; rational
bookkeeping within those coordinates avoids swallowed stages;
MD/capacity are nominal, with no rate, pressure or TOC prediction.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from fractions import Fraction
import math
import re
from typing import Literal, Protocol

from cement_chart_model import _capacity, _number
from engineering_tools import require_fluid_density, require_positive_density
from materials_db import HYDRAULIC_EXECUTION_ORDER
from project_state import available_fluid_types, fingerprint

_FLAGS = ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified')
_TAGS = {
    'cfw128_adapter': ('GeometrySnapshot','Section','InstalledString','SurveyStation','TVDPoint'),
    'cfw128_er03_contract': ('TopologyPreview','ReturnSection'),
    'cfw128_er03_boundary': ('BoundaryHold','PhysicalPort'),
    'cfw128_er03_volume': ('FrozenCapacityAudit','CapacitySection'),
    'cfw128_c2d_geometry_view': ('GeometryView','NominalSection'),
}


def _tree(v):
    """Exact published C1/C2d primitive format; no object serialization hooks."""
    if v is None:return ('None',)
    if type(v) is str:return ('str',v)
    if type(v) is bool:return ('bool',str(v))
    if type(v) is int:return ('int',hex(v))
    if type(v) is float:
        if not math.isfinite(v):raise ValueError('Nonfinite captured value.')
        return ('float',v.hex())
    if type(v) is tuple:return ('tuple',tuple(_tree(x) for x in v))
    c=type(v)
    if (c.__name__ not in _TAGS.get(c.__module__,()) or not is_dataclass(v)
            or not c.__dataclass_params__.frozen or not hasattr(c,'__slots__')):
        raise TypeError('Published frozen primitive capture format required.')
    for f in fields(v):
        if f.name in _FLAGS and getattr(v,f.name) is not False:raise ValueError('Release gate must remain False.')
    return (c.__name__,tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v)))


def _rows(v,empty=False):
    if type(v) is not tuple or (not v and not empty) or any(type(i) is not int or i<0 for i in v) or len(set(v))!=len(v):
        raise ValueError('Invalid positional source rows.')


def _view(view,sha):
    _tree(view)
    if (type(view).__module__,type(view).__name__)!=('cfw128_c2d_geometry_view','GeometryView'):
        raise TypeError('C2d-1 GeometryView required.')
    if type(sha) is not str or not re.fullmatch('[0-9a-f]{40}',sha) or view.app_source_sha!=sha:
        raise ValueError('Expected independently verified App SHA mismatch.')
    if (view.status!='DISABLED_GEOMETRY_VIEW' or view.currentness!='NOT_CURRENTNESS_PROOF'
            or view.corridor_contract!='OWNER_SURFACE_CONNECTED_2026_11_11'
            or view.hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc!='NOT_EVALUATED'):
        raise ValueError('Held surface-connected geometry required.')
    s,a=view.captured_geometry,view.historical_capacity_audit;p=a.boundary.preview
    if (s.app_source_sha!=sha or a.expected_app_source_sha!=sha or p.app_source_sha!=sha
            or (s.source_identity,s.request_identity)!=(p.upstream_source_identity,p.upstream_request_identity)
            or s.status not in ('GEOMETRY_REPRESENTABLE','ENGINE_INTERFACE_NOT_REPRESENTABLE')
            or s.kind not in ('casing','liner','tieback') or s.job!=p.job or s.host_token!=p.host_token or s.target_token!=p.target_token
            or _tree(s.active_sections)!=_tree(p.injection_sections)
            or _tree(s.enclosing_sections)!=_tree(p.enclosing_sections)
            or _tree(s.selected_host)!=_tree(p.selected_host) or _tree(s.receiver)!=_tree(p.receiver)):
        raise ValueError('Paired source metadata/geometry differs.')
    source=fingerprint(['c2d1-captured-input/1',sha,_tree(s),_tree(a)])
    def token(v):
        if type(v).__module__=='cfw128_c2d_geometry_view' and type(v).__name__=='NominalSection':
            return tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v))
        if type(v) is tuple:return tuple(token(x) for x in v)
        return v
    values=(view.status,view.injection,view.lower_annulus,view.upper_pumping_annulus,view.upper_post_pull_bore)
    expected=fingerprint(['c2d1-view/1',source,sha,token(values),view.corridor_contract,view.currentness])
    if view.source_identity!=source or view.projection_identity!=expected:raise ValueError('Captured view binding differs.')
    for identity in (s.source_identity,s.request_identity,source,expected):
        if type(identity) is not str or not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('Invalid identity.')
    top,shoe=s.string_top_md,s.shoe_md
    if any(type(x) not in (float,int) or not math.isfinite(x) for x in (top,shoe)) or not 0<=top<shoe:
        raise ValueError('Invalid measured Top/Shoe.')
    # Check projection against measured interpreted sections, not Hardware parsing
    # or a new enclosing-wall selection. Every slice needs exactly one source.
    for name,start,end in (('injection',0.,shoe),('lower_annulus',top,shoe),
                           ('upper_pumping_annulus',0.,top),('upper_post_pull_bore',0.,top)):
        parts=getattr(view,name);cursor=start
        if type(parts) is not tuple:raise TypeError('Immutable sections required.')
        for v in parts:
            if type(v).__name__!='NominalSection' or v.domain!=name or v.top_md!=cursor or not v.top_md<v.bottom_md<=end:
                raise ValueError('Section gap/overlap/domain differs.')
            for x in (v.top_md,v.bottom_md,v.inner_diameter_in,v.outer_diameter_in):_number(x,'Nominal section')
            if not 0<=v.inner_diameter_in<v.outer_diameter_in:raise ValueError('Invalid diameter/clearance.')
            _rows(v.running_source_rows,empty=name=='upper_post_pull_bore');_rows(v.wall_source_rows,empty=name=='injection')
            run=[r for r in s.active_sections if r.top_md<=v.top_md and v.bottom_md<=r.bottom_md]
            wall=[r for r in s.enclosing_sections if r.top_md<=v.top_md and v.bottom_md<=r.bottom_md]
            if len(run)!=1 or (name!='injection' and len(wall)!=1):raise ValueError('Ambiguous captured section.')
            r=run[0]
            if name=='injection':want=(0.,r.id_in,r.source_rows,())
            elif name=='upper_post_pull_bore':want=(0.,wall[0].id_in,(),wall[0].source_rows)
            else:want=(r.od_in,wall[0].id_in,r.source_rows,wall[0].source_rows)
            if (v.inner_diameter_in,v.outer_diameter_in,v.running_source_rows,v.wall_source_rows)!=want:
                raise ValueError('Measured section provenance/dimensions differ.')
            cursor=v.bottom_md
        if cursor!=end:raise ValueError('Incomplete measured leg.')
    if s.kind=='casing' and (top!=0 or view.upper_post_pull_bore):raise ValueError('Casing cannot acquire post-pull/DP.')
    return s


@dataclass(frozen=True,slots=True)
class Stage:
    name: str
    volume_bbl: float
    density_pcf: float
    source: Literal['fluids_config.params','fluid_data']
    raw_volume: str | int | float
    raw_density: str | int | float


@dataclass(frozen=True,slots=True)
class PathSection:
    domain: str
    inlet_md: float
    outlet_md: float
    start_bbl: float
    end_bbl: float
    capacity_bbl_per_m: float
    running_source_rows: tuple[int,...]
    wall_source_rows: tuple[int,...]


@dataclass(frozen=True,slots=True)
class Occupancy:
    fluid: str
    density_pcf: float
    section_index: int
    inlet_md: float
    outlet_md: float
    volume_bbl: float


@dataclass(frozen=True,slots=True)
class StageLedger:
    fluid: str
    entered_bbl: float
    in_path_bbl: float
    ideal_returned_bbl: float


class EffectiveStageRecord(Protocol):
    """Read-only structural stage interface; no CFW runtime import."""
    name: str
    volume_bbl: float
    density_pcf: float
    volume_authority: str
    source_identity: str


@dataclass(frozen=True,slots=True)
class TrackingPreview:
    app_source_sha: str
    geometry_source_identity: str
    geometry_projection_identity: str
    source_identity: str
    projection_identity: str
    cumulative_injected_bbl: float
    total_nominal_capacity_bbl: float
    initial_mud_density_pcf: float
    stages: tuple[Stage | EffectiveStageRecord,...]
    path: tuple[PathSection,...]
    occupancy: tuple[Occupancy,...]
    ledgers: tuple[StageLedger,...]
    mud_remaining_bbl: float
    mud_displaced_bbl: float
    trajectory: tuple[tuple[float,float],...]
    status: Literal['DISABLED_VOLUME_TRACKING_PREVIEW']=field(default='DISABLED_VOLUME_TRACKING_PREVIEW',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['HYDRAULICS_NOT_EVALUATED']=field(default='HYDRAULICS_NOT_EVALUATED',init=False)
    toc: Literal['TOC_NOT_EVALUATED']=field(default='TOC_NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def _raw(v):
    if type(v) not in (str,int,float):raise ValueError('Primitive Phase IV input required; booleans are not measurements.')
    if type(v) is float and not math.isfinite(v):raise ValueError('Nonfinite input.')
    return v


def _volume(raw,label,positive=False):
    _raw(raw)
    try:value=_number(raw,label,positive=positive)
    except OverflowError:raise ValueError('Volume overflow.') from None
    if type(raw) is int and int(value)!=raw:raise ValueError('Nonrepresentable source volume.')
    return value


def _float(q):
    try:v=float(q)
    except OverflowError:raise ValueError('Volume overflow.') from None
    if not math.isfinite(v) or (q and v==0):raise ValueError('Unrepresentable volume.')
    return v


def preview_fluid_tracking(view: object, state: dict, *, expected_app_source_sha: str,
                           cumulative_injected_bbl: float=0., stage_end: int | None=None) -> TrackingPreview:
    """Pure ideal incompressible bookkeeping, not Qout(t), TOC or currentness.

    Volumes are finite numeric bbl; exact rational arithmetic preserves each
    binary source quantity internally. Returned float sections must have distinct
    endpoints; a sub-resolution stage/cumulative coordinate fails closed.
    Displacement uses authoritative Mud density, as in Phase IV refresh, without
    changing any state. stage_end selects an exact zero-based count of completed
    stages, avoiding a caller-rounded fractional schedule sum. It is mutually
    exclusive with a nonzero cumulative input. Rate/rheology are never consumed.
    """
    s=_view(view,expected_app_source_sha)
    if type(state) is not dict or state.get('job_type')!=s.job:raise ValueError('Fluid job/captured geometry mismatch.')
    cfg=state.get('fluids_config',{})
    if type(cfg) is not dict or type(cfg.get('active')) not in (list,tuple) or type(cfg.get('params',{})) is not dict:
        raise ValueError('Malformed canonical Phase IV selection.')
    active=cfg['active'];params=cfg.get('params',{});old=state.get('fluid_data',{})
    if type(old) is not dict or any(type(n) is not str for n in active) or len(set(active))!=len(active):raise ValueError('Duplicate/malformed stages.')
    if any(n not in HYDRAULIC_EXECUTION_ORDER or n not in available_fluid_types(state) for n in active):raise ValueError('Unsupported/ineligible stage.')
    well=state.get('well_data',{})
    if type(well) is not dict:raise ValueError('Malformed Mud authority.')
    mudraw=state.get('mud_density')
    if mudraw is None or mudraw=='':mudraw=well.get('mud_density')
    mudraw=_raw(mudraw);mud=require_positive_density(mudraw)
    stages=[];consumed=[]
    for name in HYDRAULIC_EXECUTION_ORDER:
        if name not in active:continue
        row=params[name] if name in params else old.get(name)
        if type(row) is not dict:raise ValueError('Missing/malformed selected stage; no stale fallback.')
        rawv=_raw(row.get('volume'));volume=_volume(rawv,name+' volume',positive=True)
        rawd=mudraw if name=='Displacement Fluid' else _raw(row.get('density'))
        density=require_fluid_density(name,rawd)
        origin='fluids_config.params' if name in params else 'fluid_data'
        stages.append(Stage(name,volume,density,origin,rawv,rawd));consumed.append((name,origin,rawv,rawd))
    stages=tuple(stages)
    source=fingerprint(['cfw128-c2e-source/1',view.source_identity,view.projection_identity,expected_app_source_sha,
                        s.job,tuple(consumed),mudraw])
    return _track(view,s,stages,mud,source,expected_app_source_sha,cumulative_injected_bbl,stage_end)


def _track(view,s,stages,mud,source,expected_app_source_sha,cumulative_injected_bbl,stage_end):
    """One unchanged nominal occupancy kernel for both input authorities."""
    V=_volume(cumulative_injected_bbl,'Cumulative injected volume')
    if V<0:raise ValueError('Injected volume cannot be negative.')
    F=Fraction;intervals=[];cursor=F(0)
    for stage in stages:
        end=cursor+F(stage.volume_bbl)
        if _float(end)<=_float(cursor):raise ValueError('Stage lost at cumulative volume resolution.')
        intervals.append((stage,cursor,end));cursor=end
    if stage_end is not None:
        if type(stage_end) is not int or not 0<=stage_end<=len(intervals) or V!=0.:
            raise ValueError('Invalid/conflicting stage-end milestone.')
        injected=intervals[stage_end-1][2] if stage_end else F(0)
        V=_float(injected)
    else:
        injected=F(V)
    if injected>cursor:raise ValueError('Injected volume exceeds configured schedule.')
    path=[];bounds=[];cursor=F(0);nominal_volumes=[]
    for part in view.injection+tuple(reversed(view.lower_annulus))+tuple(reversed(view.upper_pumping_annulus)):
        cap=_capacity(part.outer_diameter_in,part.inner_diameter_in)
        volume=cap*(part.bottom_md-part.top_md)
        if not math.isfinite(volume) or volume<=0:raise ValueError('Invalid nominal capacity.')
        nominal_volumes.append(volume)
        try:end=F(math.fsum(nominal_volumes))
        except (OverflowError,ValueError):raise ValueError('Path capacity overflow.') from None
        if _float(end)<=_float(cursor):raise ValueError('Path section lost at volume resolution.')
        down=part.domain=='injection'
        path.append(PathSection(part.domain,part.top_md if down else part.bottom_md,part.bottom_md if down else part.top_md,
                                _float(cursor),_float(end),cap,part.running_source_rows,part.wall_source_rows))
        bounds.append((cursor,end));cursor=end
    total=cursor;v=injected;occupancy=[];ledgers=[]
    def occupy(name,density,left,right):
        if right<=left:return
        for i,(part,(a,b)) in enumerate(zip(path,bounds)):
            lo,hi=max(left,a),min(right,b)
            if hi<=lo:continue
            def md(x):
                if x==a:return part.inlet_md
                if x==b:return part.outlet_md
                return part.inlet_md+float((x-a)/(b-a))*(part.outlet_md-part.inlet_md)
            m0,m1=md(lo),md(hi)
            if m0==m1:raise ValueError('Occupied interval below representable MD resolution.')
            occupancy.append(Occupancy(name,density,i,m0,m1,_float(hi-lo)))
    for stage,a,b in intervals:
        entered=max(F(0),min(v,b)-a)
        left=max(F(0),v-b);right=min(total,v-a)
        retained=max(F(0),right-left)
        occupy(stage.name,stage.density_pcf,left,right)
        ledgers.append(StageLedger(stage.name,_float(entered),_float(retained),_float(entered-retained)))
    remain=max(F(0),total-v);occupy('Mud',mud,min(v,total),total)
    projection=fingerprint(['cfw128-c2e-volume/1',source,V,tuple(tuple(getattr(x,f.name) for f in fields(x)) for x in occupancy),
                            tuple(tuple(getattr(x,f.name) for f in fields(x)) for x in ledgers),_float(remain),_float(total-remain)])
    return TrackingPreview(expected_app_source_sha,view.source_identity,view.projection_identity,source,projection,V,_float(total),mud,
                           stages,tuple(path),tuple(occupancy),tuple(ledgers),_float(remain),_float(total-remain),
                           tuple((p.md,p.tvd) for p in s.trajectory))


def preview_effective_schedule(view: object, schedule: object, *, expected_app_source_sha: str,
                               mud_type: str, cumulative_injected_bbl: float=0.,
                               stage_end: int | None=None) -> TrackingPreview:
    """Receipt-native C2e5 authority; consistency checks are NOT currentness proof.

    No App state or stage overlay is accepted. The caller must freshly build the
    schedule from the same project; coherent forged/replayed receipts cannot
    authenticate it. C2e2/closure source contracts are deliberately not composed.
    """
    s=_view(view,expected_app_source_sha)
    tags={**_TAGS,'cfw128_c2e5_effective_schedule':('EffectiveSchedule','EffectiveStage')}
    # Reuse the primitive walker with an explicit additional schema, never hooks.
    _schedule_tree(schedule,tags)
    if (type(schedule).__module__,type(schedule).__name__)!=('cfw128_c2e5_effective_schedule','EffectiveSchedule'):
        raise TypeError('Frozen EffectiveSchedule required.')
    if type(mud_type) is not str:raise TypeError('Canonical Mud Type required.')
    if (schedule.app_source_sha,schedule.geometry_source_identity,schedule.geometry_projection_identity,schedule.job,schedule.kind)!=(expected_app_source_sha,view.source_identity,view.projection_identity,s.job,s.kind):
        raise ValueError('Schedule/geometry source differs.')
    if (schedule.status!='DISABLED_EFFECTIVE_PUMPING_SCHEDULE' or schedule.currentness!='NOT_CURRENTNESS_PROOF'
            or schedule.hydraulics!='HYDRAULICS_NOT_EVALUATED' or schedule.final_post_pull_toc!='FINAL_POST_PULL_TOC_NOT_EVALUATED'
            or schedule.completion_basis!='ALL_SELECTED_EFFECTIVE_STAGE_VOLUMES'):
        raise ValueError('Schedule HOLD/authority differs.')
    for identity in (schedule.source_identity,schedule.projection_identity,schedule.derived_projection_identity):
        if type(identity) is not str or not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('Invalid schedule identity.')
    if type(schedule.total_volume_bbl) not in (int,float) or type(schedule.total_volume_exact_bbl) is not tuple or len(schedule.total_volume_exact_bbl)!=2 or any(type(x) is not int for x in schedule.total_volume_exact_bbl):
        raise ValueError('Exact schedule total format differs.')
    stages=schedule.stages;names=tuple(v.name for v in stages)
    if not stages or len(set(names))!=len(names) or any(n not in HYDRAULIC_EXECUTION_ORDER for n in names) or names!=tuple(n for n in HYDRAULIC_EXECUTION_ORDER if n in names) or 'Displacement Fluid' not in names:
        raise ValueError('Invalid effective stage order/selection.')
    exact=Fraction(0);mud=None
    for v in stages:
        if (type(v).__module__,type(v).__name__)!=('cfw128_c2e5_effective_schedule','EffectiveStage'):raise TypeError('EffectiveStage required.')
        if type(v.volume_bbl) not in (int,float) or type(v.density_pcf) not in (int,float):raise ValueError('Numeric stage values required.')
        volume=_volume(v.volume_bbl,v.name,positive=True)
        if require_fluid_density(v.name,_raw(v.raw_density))!=v.density_pcf:raise ValueError('Density proof differs.')
        derived=v.name=='Displacement Fluid'
        if derived:
            if (v.volume_authority,v.record_source,v.raw_entered_volume)!=('DERIVED_C2E4_INTERNAL_STRING_CAPACITY','C2E4',None) or v.density_source not in ('state.mud_density','well_data.mud_density'):raise ValueError('Derived Mud authority differs.')
            mud=require_positive_density(v.raw_density)
        elif (v.volume_authority!='ENTERED_PHASE_IV' or v.record_source not in ('fluids_config.params','fluid_data')
              or v.density_source!=v.record_source+'.'+v.name+'.density' or _volume(v.raw_entered_volume,v.name,positive=True)!=volume):
            raise ValueError('Entered stage authority differs.')
        identity=fingerprint(['cfw128-c2e5-stage/1',v.name,v.volume_authority,v.record_source,v.raw_entered_volume,volume,v.raw_density,v.density_pcf,v.density_source,
                              schedule.derived_projection_identity if derived else None])
        if v.source_identity!=identity:raise ValueError('Stage source binding differs.')
        updated=exact+Fraction(volume)
        if _float(updated)<=_float(exact):raise ValueError('Stage lost at total precision.')
        exact=updated
    source=fingerprint(['cfw128-c2e5-source/1',expected_app_source_sha,view.source_identity,view.projection_identity,schedule.derived_projection_identity,s.job,mud_type,tuple(v.source_identity for v in stages)])
    encoded=tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in stages)
    if (schedule.source_identity!=source or schedule.total_volume_bbl!=_float(exact)
            or schedule.total_volume_exact_bbl!=(exact.numerator,exact.denominator)
            or schedule.projection_identity!=fingerprint(['cfw128-c2e5-effective-schedule/1',source,encoded,_float(exact),schedule.total_volume_exact_bbl,schedule.completion_basis])):
        raise ValueError('Effective schedule fingerprint/total differs.')
    source=fingerprint(['cfw128-gate2-effective-tracking/1',source,schedule.projection_identity,view.projection_identity])
    return _track(view,s,stages,mud,source,expected_app_source_sha,cumulative_injected_bbl,stage_end)


def _schedule_tree(v,tags):
    """Validate only published immutable primitives before accessing a receipt."""
    if type(v) in (str,int,bool,float,tuple) or v is None:
        if type(v) is tuple:
            for x in v:_schedule_tree(x,tags)
        else:_tree(v)
        return
    c=type(v)
    if c.__name__ not in tags.get(c.__module__,()) or not is_dataclass(v) or not c.__dataclass_params__.frozen or not hasattr(c,'__slots__'):
        raise TypeError('Published immutable receipt required.')
    for f in fields(v):
        value=getattr(v,f.name)
        if f.name in _FLAGS and value is not False:raise ValueError('Release gate must remain False.')
        _schedule_tree(value,tags)
