"""Disabled nominal injection-string capacity to active Shoe MD minus 25 m.

Reads caller-captured frozen C2d geometry and App _capacity/job/fingerprint
support only. Writes, fluids/state/UI/Word/schema/persistence/dependencies: none.
No CFW imports/callbacks, Hardware parser, geometry selection or tracking replay.
Annular/post-pull records participate ONLY in their original provenance binding,
never in the volume formula. No surface-line volume or other allowance is added.

This is the specified internal-string capacity, not a licensed pump program or
proof of efficiency/freefall/plugs/fluid distribution, Mud/Cement return or final
TOC/post-pull placement. Existing entered Displacement remains legacy/what-if
until separately approved integration. All other entered pumped volumes remain
authoritative and unchanged. A coherent forged/replayed capture cannot prove
live App currentness/authenticity; external expected SHA is caller-verified.
"""
from dataclasses import dataclass, field, fields, is_dataclass
import math
import re
from typing import Literal

from cement_chart_model import _capacity, chart_job_kind
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


@dataclass(frozen=True,slots=True)
class DisplacementSection:
    source_section_index: int
    description: str
    top_md: float
    bottom_md: float
    original_bottom_md: float
    internal_id_in: float
    source_rows: tuple[int,...]
    capacity_bbl_per_m: float
    nominal_volume_bbl: float


@dataclass(frozen=True,slots=True)
class DerivedDisplacement:
    app_source_sha: str
    geometry_source_identity: str
    geometry_projection_identity: str
    projection_identity: str
    job: str
    kind: Literal['casing','liner','tieback']
    active_shoe_md: float
    end_md: float
    sections: tuple[DisplacementSection,...]
    derived_displacement_bbl: float
    reserved_shoe_interval_m: Literal[25.0]=field(default=25.0,init=False)
    endpoint_contract: Literal['INJECTION_MD_0_TO_ACTIVE_SHOE_MINUS_25_M']=field(default='INJECTION_MD_0_TO_ACTIVE_SHOE_MINUS_25_M',init=False)
    surface_line_volume: Literal['NONE_ADDED']=field(default='NONE_ADDED',init=False)
    volume_basis: Literal['NOMINAL_INTERNAL_STRING_CAPACITY']=field(default='NOMINAL_INTERNAL_STRING_CAPACITY',init=False)
    status: Literal['DISABLED_DERIVED_DISPLACEMENT_PREVIEW']=field(default='DISABLED_DERIVED_DISPLACEMENT_PREVIEW',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['HYDRAULICS_NOT_EVALUATED']=field(default='HYDRAULICS_NOT_EVALUATED',init=False)
    final_post_pull_toc: Literal['FINAL_POST_PULL_TOC_NOT_EVALUATED']=field(default='FINAL_POST_PULL_TOC_NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def derive_displacement(view: object, *, expected_app_source_sha: str) -> DerivedDisplacement:
    """Read nominal injection ID/MD only; no entered volume or operational model."""
    g=view;s=_bind(g,expected_app_source_sha);end=s.shoe_md-25.
    if not 0<end<s.shoe_md or s.shoe_md-end!=25.:raise ValueError('Reserved 25 m endpoint is not representable exactly.')
    if not s.active_sections or len(g.injection)!=len(s.active_sections):raise ValueError('Missing/ambiguous injection sections.')
    cursor=0.;clipped_cursor=0.;total=0.;parts=[]
    body={'casing':'Casing','liner':'Liner Shoe','tieback':'Tie Back Liner Shoe'}[s.kind]
    for index,(n,original) in enumerate(zip(g.injection,s.active_sections)):
        _kind(n,'cfw128_c2d_geometry_view','NominalSection');_kind(original,'cfw128_adapter','Section');_rows(original.source_rows);_rows(n.running_source_rows)
        for v in (original.top_md,original.bottom_md,original.id_in,original.od_in,n.top_md,n.bottom_md,n.inner_diameter_in,n.outer_diameter_in):_number(v)
        if original.top_md!=cursor or not original.top_md<original.bottom_md<=s.shoe_md or not 0<original.id_in<original.od_in:raise ValueError('Invalid/gapped/overlapping measured injection section.')
        before=original.bottom_md<=s.string_top_md
        if original.top_md<s.string_top_md<original.bottom_md or original.description!=('Drill Pipes' if before else body):raise ValueError('Unexpected active role/Lap partition.')
        expected=('injection',original.top_md,original.bottom_md,0.,original.id_in,original.source_rows,())
        if tuple(getattr(n,f.name) for f in fields(n))!=expected:raise ValueError('Nominal injection ID/MD/source rows differ from measured capture.')
        cursor=original.bottom_md
        bottom=min(n.bottom_md,end)
        if bottom<=n.top_md:continue
        if n.top_md!=clipped_cursor:raise ValueError('Clipped path gap/overlap.')
        try:cap=_capacity(n.outer_diameter_in,0.);volume=(bottom-n.top_md)*cap
        except OverflowError:raise ValueError('Nominal internal capacity overflow.') from None
        _number(cap,True);_number(volume,True);updated=total+volume;_number(updated,True)
        if updated<=total:raise ValueError('Section volume lost at total precision.')
        parts.append(DisplacementSection(index,original.description,n.top_md,bottom,n.bottom_md,n.outer_diameter_in,n.running_source_rows,cap,volume))
        total=updated;clipped_cursor=bottom
    if cursor!=s.shoe_md or clipped_cursor!=end or not parts:raise ValueError('Incomplete original/clipped injection path.')
    encoded=tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in parts)
    identity=fingerprint(['cfw128-c2e4-derived-displacement/1',expected_app_source_sha,g.source_identity,g.projection_identity,
        s.job,s.kind,s.shoe_md,end,25.,encoded,total,'NOMINAL_INTERNAL_STRING_CAPACITY','NONE_ADDED'])
    return DerivedDisplacement(expected_app_source_sha,g.source_identity,g.projection_identity,identity,s.job,s.kind,s.shoe_md,end,tuple(parts),total)
