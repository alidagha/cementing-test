"""Disabled source-bound effective schedule, without transport or App mutation.

Reads frozen C2d/C2e4 records, selected Phase IV consumed fields and authoritative
Mud density; App capacity/job/eligibility/density/fingerprint remain authorities.
Writes, UI/persistence/schema/Word/dependency changes: none. No CFW imports or
callbacks, Hardware parser, tracking algorithm, rates/pressure/HB or TOC model.
Only selected Displacement volume is derived. Its entered display volume/record
is never read or fingerprinted; all other entered pumped amounts are preserved.
Published primitive bindings verify consistency, not coherent forgery/replay or
live currentness. Composition with older trackers belongs to TESTS ONLY.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from fractions import Fraction
import math
import re
from typing import Literal

from cement_chart_model import _capacity, chart_job_kind, _number as _fluid_number
from engineering_tools import require_fluid_density, require_positive_density
from materials_db import HYDRAULIC_EXECUTION_ORDER
from project_state import fingerprint, available_fluid_types

_FLAGS=('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified')
_TAGS={
 'cfw128_adapter':('GeometrySnapshot','Section','InstalledString','SurveyStation','TVDPoint'),
 'cfw128_er03_contract':('TopologyPreview','ReturnSection'),
 'cfw128_er03_boundary':('BoundaryHold','PhysicalPort'),
 'cfw128_er03_volume':('FrozenCapacityAudit','CapacitySection'),
 'cfw128_c2d_geometry_view':('GeometryView','NominalSection'),
 'cfw128_c2e4_derived_displacement':('DerivedDisplacement','DisplacementSection'),
}


def _kind(v,module,name):
    if (type(v).__module__,type(v).__name__)!=(module,name):raise TypeError('Published frozen format required.')


def _tree(v):
    """Published C1/C2d primitive binding format, without serialization hooks."""
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
        raise TypeError('Deeply immutable primitive capture required.')
    try:
        for f in fields(v):
            if f.name in _FLAGS and getattr(v,f.name) is not False:raise ValueError('Captured release flags must remain False.')
        return (c.__name__,tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v)))
    except AttributeError:raise TypeError('Incomplete frozen record.') from None


def _number(v,positive=False):
    if type(v) not in (float,int):raise ValueError('Finite measured number required.')
    try:valid=math.isfinite(v)
    except OverflowError:valid=False
    if not valid or v<0 or positive and v==0:raise ValueError('Invalid/nonfinite measured number.')


def _rows(v):
    if type(v) is not tuple or not v or any(type(i) is not int or i<0 for i in v) or len(set(v))!=len(v):
        raise ValueError('Missing/ambiguous positional source rows.')


def _bind(g,sha):
    _tree(g);_kind(g,'cfw128_c2d_geometry_view','GeometryView')
    if type(sha) is not str or not re.fullmatch('[0-9a-f]{40}',sha) or g.app_source_sha!=sha:raise ValueError('Expected verified App SHA mismatch.')
    if (g.status!='DISABLED_GEOMETRY_VIEW' or g.currentness!='NOT_CURRENTNESS_PROOF'
            or g.corridor_contract!='OWNER_SURFACE_CONNECTED_2026_11_11'
            or g.hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc!='NOT_EVALUATED'):
        raise ValueError('Only held canonical geometry is supported.')
    s,a=g.captured_geometry,g.historical_capacity_audit
    _kind(s,'cfw128_adapter','GeometrySnapshot');_kind(a,'cfw128_er03_volume','FrozenCapacityAudit')
    _kind(a.boundary,'cfw128_er03_boundary','BoundaryHold');p=a.boundary.preview
    _kind(p,'cfw128_er03_contract','TopologyPreview')
    if (s.kind not in ('casing','liner','tieback') or chart_job_kind(s.job)!=s.kind
            or s.status not in ('GEOMETRY_REPRESENTABLE','ENGINE_INTERFACE_NOT_REPRESENTABLE')
            or s.app_source_sha!=sha or p.app_source_sha!=sha or a.expected_app_source_sha!=sha
            or a.boundary.expected_app_source_sha!=sha
            or (s.source_identity,s.request_identity,s.status)!=(p.upstream_source_identity,p.upstream_request_identity,p.upstream_status)):
        raise ValueError('Captured source/proof metadata differs.')
    for name in ('job','kind','target_token','host_token','string_top_md','shoe_md'):
        if getattr(s,name)!=getattr(p,name):raise ValueError('Captured source topology/selection differs.')
    for x,y in (('active_sections','injection_sections'),('selected_host','selected_host'),('receiver','receiver')):
        if _tree(getattr(s,x))!=_tree(getattr(p,y)):raise ValueError('Paired captured source differs.')
    for identity in (s.source_identity,s.request_identity,p.source_identity,g.source_identity,g.projection_identity):
        if type(identity) is not str or not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('Invalid captured identity.')
    if p.source_identity!=fingerprint(['cfw128-c1-source/1',sha,_tree(s)]):raise ValueError('C1 captured source binding differs.')
    source=fingerprint(['c2d1-captured-input/1',sha,_tree(s),_tree(a)])
    def token(v):
        if type(v).__module__=='cfw128_c2d_geometry_view' and type(v).__name__=='NominalSection':
            return tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v))
        if type(v) is tuple:return tuple(token(x) for x in v)
        return v
    values=(g.status,g.injection,g.lower_annulus,g.upper_pumping_annulus,g.upper_post_pull_bore)
    if source!=g.source_identity or g.projection_identity!=fingerprint(['c2d1-view/1',source,sha,token(values),g.corridor_contract,g.currentness]):raise ValueError('Geometry projection/source binding differs.')
    _number(s.shoe_md,True);_number(s.string_top_md)
    if s.shoe_md<=25. or not s.string_top_md<s.shoe_md or s.kind=='casing' and s.string_top_md!=0:raise ValueError('Active Shoe must exceed 25 m; measured Top must be valid.')
    if s.kind=='tieback' and (s.selected_host is None or s.receiver is None or not s.receiver.top_md<=s.shoe_md<s.receiver.shoe_md):raise ValueError('Missing/incompatible explicit host/receiver.')
    return s


def _verify_derived(g,d,sha):
    s=_bind(g,sha);_tree(d);_kind(d,'cfw128_c2e4_derived_displacement','DerivedDisplacement')
    if (d.app_source_sha!=sha or d.geometry_source_identity!=g.source_identity or d.geometry_projection_identity!=g.projection_identity
            or (d.job,d.kind,d.active_shoe_md)!=(s.job,s.kind,s.shoe_md)
            or d.end_md!=s.shoe_md-25. or not 0<d.end_md<s.shoe_md or s.shoe_md-d.end_md!=25.
            or d.reserved_shoe_interval_m!=25. or d.endpoint_contract!='INJECTION_MD_0_TO_ACTIVE_SHOE_MINUS_25_M'
            or d.surface_line_volume!='NONE_ADDED' or d.volume_basis!='NOMINAL_INTERNAL_STRING_CAPACITY'
            or d.status!='DISABLED_DERIVED_DISPLACEMENT_PREVIEW' or d.currentness!='NOT_CURRENTNESS_PROOF'
            or d.hydraulics!='HYDRAULICS_NOT_EVALUATED' or d.final_post_pull_toc!='FINAL_POST_PULL_TOC_NOT_EVALUATED'):
        raise ValueError('C2e4 receipt does not bind to the same held geometry/endpoint.')
    if not s.active_sections or len(g.injection)!=len(s.active_sections):raise ValueError('Missing/ambiguous injection path.')
    expected=[];cursor=0.;end_cursor=0.;total=0.
    body={'casing':'Casing','liner':'Liner Shoe','tieback':'Tie Back Liner Shoe'}[s.kind]
    for index,(n,original) in enumerate(zip(g.injection,s.active_sections)):
        _kind(n,'cfw128_c2d_geometry_view','NominalSection');_kind(original,'cfw128_adapter','Section')
        _rows(original.source_rows);_rows(n.running_source_rows)
        for v in (original.top_md,original.bottom_md,original.od_in,original.id_in,n.top_md,n.bottom_md,n.inner_diameter_in,n.outer_diameter_in):_number(v)
        if original.top_md!=cursor or not original.top_md<original.bottom_md<=s.shoe_md or not 0<original.id_in<original.od_in:raise ValueError('Invalid injection interval/ID.')
        if original.top_md<s.string_top_md<original.bottom_md or original.description!=('Drill Pipes' if original.bottom_md<=s.string_top_md else body):raise ValueError('Unexpected injection role/Lap.')
        if tuple(getattr(n,f.name) for f in fields(n))!=('injection',original.top_md,original.bottom_md,0.,original.id_in,original.source_rows,()):raise ValueError('Injection source provenance differs.')
        cursor=original.bottom_md;bottom=min(n.bottom_md,d.end_md)
        if bottom<=n.top_md:continue
        if n.top_md!=end_cursor:raise ValueError('Clipped path gap/overlap.')
        try:cap=_capacity(n.outer_diameter_in,0.);volume=(bottom-n.top_md)*cap
        except OverflowError:raise ValueError('Nominal capacity overflow.') from None
        _number(cap,True);_number(volume,True);updated=total+volume;_number(updated,True)
        if updated<=total:raise ValueError('Clipped section lost at volume resolution.')
        expected.append((index,original.description,n.top_md,bottom,n.bottom_md,n.outer_diameter_in,n.running_source_rows,cap,volume))
        total=updated;end_cursor=bottom
    if cursor!=s.shoe_md or end_cursor!=d.end_md or len(d.sections)!=len(expected):raise ValueError('Incomplete C2e4 clipped proof.')
    names=('source_section_index','description','top_md','bottom_md','original_bottom_md','internal_id_in','source_rows','capacity_bbl_per_m','nominal_volume_bbl')
    for v,want in zip(d.sections,expected):
        _kind(v,'cfw128_c2e4_derived_displacement','DisplacementSection')
        if tuple(f.name for f in fields(v))!=names or tuple(getattr(v,n) for n in names)!=want:raise ValueError('C2e4 section/ID/rows/capacity differs.')
    _number(d.derived_displacement_bbl,True)
    if d.derived_displacement_bbl!=total:raise ValueError('C2e4 total is not proved by the same injection geometry.')
    identity=fingerprint(['cfw128-c2e4-derived-displacement/1',sha,g.source_identity,g.projection_identity,
        s.job,s.kind,s.shoe_md,d.end_md,25.,tuple(expected),total,'NOMINAL_INTERNAL_STRING_CAPACITY','NONE_ADDED'])
    if d.projection_identity!=identity:raise ValueError('C2e4 published projection fingerprint differs.')
    return s


@dataclass(frozen=True,slots=True)
class EffectiveStage:
    name: str
    volume_bbl: float
    density_pcf: float
    volume_authority: Literal['ENTERED_PHASE_IV','DERIVED_C2E4_INTERNAL_STRING_CAPACITY']
    record_source: Literal['fluids_config.params','fluid_data','C2E4']
    raw_entered_volume: int | float | None
    raw_density: str | int | float
    density_source: str
    source_identity: str


@dataclass(frozen=True,slots=True)
class EffectiveSchedule:
    app_source_sha: str
    geometry_source_identity: str
    geometry_projection_identity: str
    derived_projection_identity: str
    source_identity: str
    projection_identity: str
    job: str
    kind: Literal['casing','liner','tieback']
    stages: tuple[EffectiveStage,...]
    total_volume_bbl: float
    total_volume_exact_bbl: tuple[int,int]
    completion_basis: Literal['ALL_SELECTED_EFFECTIVE_STAGE_VOLUMES']=field(default='ALL_SELECTED_EFFECTIVE_STAGE_VOLUMES',init=False)
    status: Literal['DISABLED_EFFECTIVE_PUMPING_SCHEDULE']=field(default='DISABLED_EFFECTIVE_PUMPING_SCHEDULE',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['HYDRAULICS_NOT_EVALUATED']=field(default='HYDRAULICS_NOT_EVALUATED',init=False)
    final_post_pull_toc: Literal['FINAL_POST_PULL_TOC_NOT_EVALUATED']=field(default='FINAL_POST_PULL_TOC_NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def _raw(v):
    if type(v) not in (str,int,float):raise ValueError('Primitive entered measurement required; booleans are invalid.')
    if type(v) is float and not math.isfinite(v):raise ValueError('Nonfinite entered measurement.')
    return v


def build_effective_schedule(view: object, displacement: object, state: dict, *, expected_app_source_sha: str) -> EffectiveSchedule:
    """Select existing stages only; derive Mud volume solely from verified C2e4.

    Material/rate/rheology/unused record fields are not consumed or modified.
    total_volume_exact_bbl preserves the exact binary stage sum; rounded display
    total is not a bypass of C2e2 terminal precision/anchoring HOLDs.
    """
    g,d=view,displacement;s=_verify_derived(g,d,expected_app_source_sha)
    if type(state) is not dict or type(state.get('job_type')) is not str or state.get('job_type')!=s.job:raise ValueError('Phase IV job/captured source differs.')
    cfg=state.get('fluids_config',{});well=state.get('well_data',{})
    if type(cfg) is not dict or type(cfg.get('active')) not in (list,tuple) or type(cfg.get('params',{})) is not dict or type(well) is not dict:raise ValueError('Malformed canonical fluid selection/authority.')
    active=cfg['active'];params=cfg.get('params',{});old=state.get('fluid_data',{})
    if type(old) is not dict or any(type(n) is not str for n in active) or len(set(active))!=len(active):raise ValueError('Duplicate/malformed selected fluids.')
    mud_type=state.get('mud_type',well.get('mud_type','WBM'))
    if type(mud_type) is not str:raise ValueError('Primitive Mud Type required.')
    if any(n not in HYDRAULIC_EXECUTION_ORDER or n not in available_fluid_types(state) for n in active):raise ValueError('Unsupported/ineligible selected fluid.')
    if 'Displacement Fluid' not in active:raise ValueError('HOLD_DISPLACEMENT_NOT_SELECTED')
    mudraw=state.get('mud_density');mud_source='state.mud_density'
    if mudraw is None or type(mudraw) is str and mudraw=='':mudraw=well.get('mud_density');mud_source='well_data.mud_density'
    mudraw=_raw(mudraw);mud=require_positive_density(mudraw)
    stages=[];exact=Fraction(0)
    for name in HYDRAULIC_EXECUTION_ORDER:
        if name not in active:continue
        if name=='Displacement Fluid':
            volume=d.derived_displacement_bbl;raw_volume=None;raw_density=mudraw;density=mud
            origin='C2E4';authority='DERIVED_C2E4_INTERNAL_STRING_CAPACITY';density_source=mud_source
        else:
            row=params[name] if name in params else old.get(name)
            if type(row) is not dict:raise ValueError('Missing/invalid selected non-Mud source; no stale fallback.')
            raw_volume=_raw(row.get('volume'))
            try:volume=_fluid_number(raw_volume,name+' volume',positive=True)
            except OverflowError:raise ValueError('Entered volume overflow.') from None
            if type(raw_volume) is int and int(volume)!=raw_volume:raise ValueError('Nonrepresentable entered volume.')
            raw_density=_raw(row.get('density'));density=require_fluid_density(name,raw_density)
            origin='fluids_config.params' if name in params else 'fluid_data';authority='ENTERED_PHASE_IV'
            density_source=origin+'.'+name+'.density'
        identity=fingerprint(['cfw128-c2e5-stage/1',name,authority,origin,raw_volume,volume,raw_density,density,density_source,
                              d.projection_identity if name=='Displacement Fluid' else None])
        stages.append(EffectiveStage(name,volume,density,authority,origin,raw_volume,raw_density,density_source,identity))
        updated=exact+Fraction(volume)
        try:before,after=float(exact),float(updated)
        except OverflowError:raise ValueError('Effective schedule volume overflow.') from None
        if not math.isfinite(after) or after<=before:raise ValueError('Effective stage volume lost at total precision.')
        exact=updated
    stages=tuple(stages);total=float(exact);exact_pair=(exact.numerator,exact.denominator)
    source=fingerprint(['cfw128-c2e5-source/1',expected_app_source_sha,g.source_identity,g.projection_identity,d.projection_identity,
                        s.job,mud_type,tuple(v.source_identity for v in stages)])
    encoded=tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in stages)
    projection=fingerprint(['cfw128-c2e5-effective-schedule/1',source,encoded,total,exact_pair,'ALL_SELECTED_EFFECTIVE_STAGE_VOLUMES'])
    return EffectiveSchedule(expected_app_source_sha,g.source_identity,g.projection_identity,d.projection_identity,source,projection,s.job,s.kind,stages,total,exact_pair)
