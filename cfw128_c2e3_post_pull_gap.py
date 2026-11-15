"""Disabled geometric post-pull capacity gap, not operational displacement.

Reads only the caller's frozen C2d nominal sections/captured provenance and the
App _capacity/fingerprint authorities. Writes, fluids/state, persistence, UI,
Word, schema and dependency changes: none. No CFW imports or callbacks, Hardware
parser, transport replay or solver. Published primitive bindings check copied
consistency; a coherent counterfeit/replay cannot prove live currentness.

Non-displacement Phase IV volumes remain entered intended pumped amounts.
ONLY Displacement Fluid needs a future derived-volume authority/approved endpoint;
today's entered Displacement can drive the old disabled what-if preview but is
not derived. The capacity gap below never supplies that operational amount.
"""
from dataclasses import dataclass, field, fields, is_dataclass
import math
import re
from typing import Literal

from cement_chart_model import _capacity
from project_state import fingerprint

_FLAGS=('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified')
_TAGS={
 'cfw128_adapter':('GeometrySnapshot','Section','InstalledString','SurveyStation','TVDPoint'),
 'cfw128_er03_contract':('TopologyPreview','ReturnSection'),
 'cfw128_er03_boundary':('BoundaryHold','PhysicalPort'),
 'cfw128_er03_volume':('FrozenCapacityAudit','CapacitySection'),
 'cfw128_c2d_geometry_view':('GeometryView','NominalSection'),
}


def _kind(v,module,name):
    if (type(v).__module__,type(v).__name__)!=(module,name):raise TypeError('Published frozen format required.')


def _tree(v):
    """Published C1/C2d v1 primitive identity encoding; no serialization hooks."""
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
    for f in fields(v):
        if f.name in _FLAGS and getattr(v,f.name) is not False:raise ValueError('Release flags must remain False.')
    return (c.__name__,tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v)))


def _number(v,positive=False):
    if type(v) not in (int,float):raise ValueError('Finite measured number required.')
    try:valid=math.isfinite(v)
    except OverflowError:valid=False
    if not valid or v<0 or positive and v==0:raise ValueError('Invalid/nonfinite measured number.')


def _rows(v,empty=False):
    if type(v) is not tuple or not v and not empty or any(type(i) is not int or i<0 for i in v) or len(set(v))!=len(v):
        raise ValueError('Missing/ambiguous positional source rows.')


def _bind(g,sha):
    _tree(g);_kind(g,'cfw128_c2d_geometry_view','GeometryView')
    if type(sha) is not str or not re.fullmatch('[0-9a-f]{40}',sha) or g.app_source_sha!=sha:raise ValueError('Expected independently verified App SHA mismatch.')
    if (g.status!='DISABLED_GEOMETRY_VIEW' or g.currentness!='NOT_CURRENTNESS_PROOF'
            or g.corridor_contract!='OWNER_SURFACE_CONNECTED_2026_11_11'
            or g.hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc!='NOT_EVALUATED'):
        raise ValueError('Only held surface-connected canonical geometry is supported.')
    s,a=g.captured_geometry,g.historical_capacity_audit
    _kind(s,'cfw128_adapter','GeometrySnapshot');_kind(a,'cfw128_er03_volume','FrozenCapacityAudit')
    _kind(a.boundary,'cfw128_er03_boundary','BoundaryHold');p=a.boundary.preview
    _kind(p,'cfw128_er03_contract','TopologyPreview')
    if (s.status not in ('GEOMETRY_REPRESENTABLE','ENGINE_INTERFACE_NOT_REPRESENTABLE')
            or s.kind not in ('casing','liner','tieback') or s.app_source_sha!=sha or p.app_source_sha!=sha
            or a.expected_app_source_sha!=sha or a.boundary.expected_app_source_sha!=sha
            or (s.source_identity,s.request_identity,s.status)!=(p.upstream_source_identity,p.upstream_request_identity,p.upstream_status)):
        raise ValueError('Captured proof/source metadata differs.')
    for name in ('job','kind','host_token','target_token','string_top_md','shoe_md'):
        if getattr(s,name)!=getattr(p,name):raise ValueError('Captured selection/boundary differs.')
    for x,y in (('active_sections','injection_sections'),('enclosing_sections','enclosing_sections'),('selected_host','selected_host'),('receiver','receiver'),('installed_strings','installed_strings')):
        if _tree(getattr(s,x))!=_tree(getattr(p,y)):raise ValueError('Paired source geometry/provenance differs.')
    if s.kind=='tieback':
        if (s.selected_host is None or s.receiver is None
                or s.selected_host.description not in ('Casing','Previous Casing','Liner Shoe','Previous Liner Shoe')
                or s.receiver.description not in ('Liner Shoe','Previous Liner Shoe')
                or not s.receiver.top_md<=s.shoe_md<s.receiver.shoe_md
                or not any(_tree(s.selected_host)==_tree(v) for v in s.installed_strings)
                or not any(_tree(s.receiver)==_tree(v) for v in s.installed_strings)):
            raise ValueError('Missing/incompatible captured explicit host or receiver.')
    for v in (s.source_identity,s.request_identity,g.source_identity,g.projection_identity):
        if type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v):raise ValueError('Invalid source identity.')
    source=fingerprint(['c2d1-captured-input/1',sha,_tree(s),_tree(a)])
    def token(v):
        if type(v).__module__=='cfw128_c2d_geometry_view' and type(v).__name__=='NominalSection':
            return tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v))
        if type(v) is tuple:return tuple(token(x) for x in v)
        return v
    values=(g.status,g.injection,g.lower_annulus,g.upper_pumping_annulus,g.upper_post_pull_bore)
    if g.source_identity!=source or g.projection_identity!=fingerprint(['c2d1-view/1',source,sha,token(values),g.corridor_contract,g.currentness]):
        raise ValueError('Captured geometry binding differs.')
    _number(s.string_top_md);_number(s.shoe_md,True)
    if not s.string_top_md<s.shoe_md or s.kind=='casing' and s.string_top_md!=0:raise ValueError('Invalid active Top/Shoe.')
    return s


def _validate_sections(g,s):
    body={'casing':'Casing','liner':'Liner Shoe','tieback':'Tie Back Liner Shoe'}[s.kind]
    for parts in (s.active_sections,s.enclosing_sections):
        cursor=0.
        if not parts:raise ValueError('Missing canonical measured path.')
        for v in parts:
            _kind(v,'cfw128_adapter','Section');_rows(v.source_rows)
            for x in (v.top_md,v.bottom_md,v.od_in,v.id_in):_number(x)
            if v.top_md!=cursor or not v.top_md<v.bottom_md<=s.shoe_md or not 0<v.id_in<=v.od_in or (v.description=='Open Hole Size')!=(v.id_in==v.od_in):raise ValueError('Invalid measured interval/diameter/role.')
            cursor=v.bottom_md
        if cursor!=s.shoe_md:raise ValueError('Canonical path must end at active Shoe.')
    for name,top,bottom in (('injection',0.,s.shoe_md),('lower_annulus',s.string_top_md,s.shoe_md),
                            ('upper_pumping_annulus',0.,s.string_top_md),('upper_post_pull_bore',0.,s.string_top_md)):
        cursor=top
        for n in getattr(g,name):
            _kind(n,'cfw128_c2d_geometry_view','NominalSection')
            for x in (n.top_md,n.bottom_md,n.inner_diameter_in,n.outer_diameter_in):_number(x)
            if n.domain!=name or n.top_md!=cursor or not n.top_md<n.bottom_md<=bottom or not n.inner_diameter_in<n.outer_diameter_in:raise ValueError('Invalid/gapped/overlapping nominal section.')
            _rows(n.running_source_rows,empty=name=='upper_post_pull_bore');_rows(n.wall_source_rows,empty=name=='injection')
            run=[v for v in s.active_sections if v.top_md<=n.top_md and n.bottom_md<=v.bottom_md]
            wall=[v for v in s.enclosing_sections if v.top_md<=n.top_md and n.bottom_md<=v.bottom_md]
            if len(run)!=1 or name!='injection' and len(wall)!=1:raise ValueError('Missing/ambiguous measured section provenance.')
            run=run[0]
            role='Drill Pipes' if n.bottom_md<=s.string_top_md else body
            if run.description!=role:raise ValueError('Captured active role differs.')
            if name=='injection':want=(0.,run.id_in,run.source_rows,())
            elif name=='upper_post_pull_bore':want=(0.,wall[0].id_in,(),wall[0].source_rows)
            else:want=(run.od_in,wall[0].id_in,run.source_rows,wall[0].source_rows)
            if (n.inner_diameter_in,n.outer_diameter_in,n.running_source_rows,n.wall_source_rows)!=want:raise ValueError('Measured source dimensions/rows differ.')
            cursor=n.bottom_md
        if cursor!=bottom:raise ValueError('Incomplete nominal leg; no inferred wall or interval.')


def _volume(n):
    try:value=_capacity(n.outer_diameter_in,n.inner_diameter_in)*(n.bottom_md-n.top_md)
    except OverflowError:raise ValueError('Nominal capacity overflow.') from None
    _number(value,True)
    return value


def _total(values):
    value=sum(values);_number(value)
    return value


@dataclass(frozen=True,slots=True)
class UpperCapacitySlice:
    top_md: float
    bottom_md: float
    host_id_in: float
    drill_pipe_od_in: float
    running_source_rows: tuple[int,...]
    wall_source_rows: tuple[int,...]
    pumping_capacity_bbl_per_m: float
    post_pull_capacity_bbl_per_m: float
    pumping_volume_bbl: float
    post_pull_volume_bbl: float
    capacity_gap_bbl: float
    pumping_role: Literal['PUMPING_DP_PRESENT']=field(default='PUMPING_DP_PRESENT',init=False)
    post_pull_role: Literal['POST_PULL_DP_REMOVED']=field(default='POST_PULL_DP_REMOVED',init=False)


@dataclass(frozen=True,slots=True)
class PostPullGapAudit:
    app_source_sha: str
    geometry_source_identity: str
    geometry_projection_identity: str
    projection_identity: str
    job: str
    kind: Literal['casing','liner','tieback']
    lap_md: float
    shoe_md: float
    status: Literal['DISABLED_POST_PULL_CAPACITY_GAP_AUDIT','NOT_APPLICABLE']
    slices: tuple[UpperCapacitySlice,...]
    unchanged_injection_bbl: float
    unchanged_lower_annulus_bbl: float
    upper_pumping_bbl: float | None
    upper_post_pull_bbl: float | None
    capacity_gap_bbl: float | None
    post_pull_fluid_boundary: Literal['HOLD_POST_PULL_FLUID_BOUNDARY_UNDEFINED','NOT_APPLICABLE']
    displacement_volume_authority: Literal['HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED']=field(default='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED',init=False)
    other_pumped_volume_authority: Literal['ENTERED_PHASE_IV_STAGE_VOLUMES']=field(default='ENTERED_PHASE_IV_STAGE_VOLUMES',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['NOT_EVALUATED']=field(default='NOT_EVALUATED',init=False)
    final_toc: Literal['NOT_EVALUATED']=field(default='NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def audit_post_pull_gap(view: object, *, expected_app_source_sha: str) -> PostPullGapAudit:
    """Nominal paired capacities only; consumes no stage volume or App state."""
    g=view;s=_bind(g,expected_app_source_sha);_validate_sections(g,s)
    injection=_total(_volume(v) for v in g.injection);lower=_total(_volume(v) for v in g.lower_annulus)
    if len(g.upper_pumping_annulus)!=len(g.upper_post_pull_bore):raise ValueError('Unpaired upper sections.')
    slices=[]
    for pump,post in zip(g.upper_pumping_annulus,g.upper_post_pull_bore):
        if (pump.top_md,pump.bottom_md,pump.outer_diameter_in,pump.wall_source_rows)!=(post.top_md,post.bottom_md,post.outer_diameter_in,post.wall_source_rows):raise ValueError('Upper pumping/post-pull slices do not pair exactly.')
        a,b=_volume(pump),_volume(post);gap=b-a
        _number(gap,True)
        slices.append(UpperCapacitySlice(pump.top_md,pump.bottom_md,pump.outer_diameter_in,pump.inner_diameter_in,
            pump.running_source_rows,pump.wall_source_rows,_capacity(pump.outer_diameter_in,pump.inner_diameter_in),
            _capacity(post.outer_diameter_in),a,b,gap))
    casing=s.kind=='casing'
    if casing and slices:raise ValueError('Casing cannot acquire a fictitious post-pull.')
    pump=None if casing else _total(v.pumping_volume_bbl for v in slices)
    post=None if casing else _total(v.post_pull_volume_bbl for v in slices)
    gap=None if casing else _total(v.capacity_gap_bbl for v in slices)
    status='NOT_APPLICABLE' if casing else 'DISABLED_POST_PULL_CAPACITY_GAP_AUDIT'
    boundary='NOT_APPLICABLE' if casing else 'HOLD_POST_PULL_FLUID_BOUNDARY_UNDEFINED'
    encoded=tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in slices)
    identity=fingerprint(['cfw128-c2e3-geometric-gap/1',expected_app_source_sha,g.source_identity,g.projection_identity,
        s.job,s.kind,s.string_top_md,s.shoe_md,status,encoded,injection,lower,pump,post,gap,boundary,
        'HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED','ENTERED_PHASE_IV_STAGE_VOLUMES','NOT_CURRENTNESS_PROOF'])
    return PostPullGapAudit(expected_app_source_sha,g.source_identity,g.projection_identity,identity,s.job,s.kind,
        s.string_top_md,s.shoe_md,status,tuple(slices),injection,lower,pump,post,gap,boundary)
