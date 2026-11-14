"""C2d-1: disabled surface-connected nominal geometry view, version 1.

Reads caller-supplied frozen App capture + historical C2b proof, canonical job
metadata/_capacity and App fingerprint. Writes nothing; no Hardware parsing,
fluid/TOC/transport/pressure, UI, persistence, report/template or dependency.
There are NO imports/callbacks into the locked CFW capture/proof modules. Their
published v1 primitive identity formats are checked, not re-issued or modified.
Structural dataclass tags discriminate formats, not authenticity. A coherent
counterfeit or replay cannot be authenticated: NOT_CURRENTNESS_PROOF always.
Historical partial-return ports are evidence only; the new Owner 2026-11-11
corridor reaches surface. Tank discharge intent does not set Lap/WHP pressure.
"""
from dataclasses import dataclass, field, fields, is_dataclass
import math
import re
from typing import Literal

from cement_chart_model import _capacity, chart_job_kind
from project_state import fingerprint

_FLAGS = ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified')
_UNKNOWN = ('return_outlet_pressure','pressure_datum','pressure_reference','inlet_outlet_pressure_closure',
            'fluid_inventory_transport','mass_volume_conservation','qout_rate','freefall_tail_interpretation',
            'shutin_bhsp_reference','three_chart_labels')
_TAGS = {
    'cfw128_adapter': ('GeometrySnapshot','Section','InstalledString','SurveyStation','TVDPoint'),
    'cfw128_er03_contract': ('TopologyPreview','ReturnSection'),
    'cfw128_er03_boundary': ('BoundaryHold','PhysicalPort'),
    'cfw128_er03_volume': ('FrozenCapacityAudit','CapacitySection'),
}
_METHOD = 'app._capacity.nominal-in2-ft-m-bbl/1'
_UNITS = ('MD:m','diameter:in','capacity:bbl/m','geometric_volume:bbl')


def _number(v): return type(v) in (int,float) and math.isfinite(v)


def _record(v, module, name):
    cls=type(v)
    if (cls.__module__!=module or cls.__name__!=name or not is_dataclass(v)
            or not cls.__dataclass_params__.frozen or not hasattr(cls,'__slots__')):
        raise TypeError('Provide the published frozen capture format, not state/dicts/callbacks.')


def _tree(v, mode='c1'):
    """Published v1 primitive encodings; never import a type or invoke a hook."""
    if v is None: return ('None',) if mode=='c1' else ('NoneType',None)
    if type(v) is str: return ('str',v)
    if type(v) is bool: return ('bool',str(v)) if mode=='c1' else ('bool',v)
    if type(v) is int: return ('int',hex(v)) if mode=='c1' else ('int',v)
    if type(v) is float:
        if not math.isfinite(v): raise ValueError('Nonfinite captured value.')
        return ('float',v.hex())
    if type(v) is tuple: return ('tuple',tuple(_tree(x,mode) for x in v))
    cls=type(v)
    if cls.__module__ in _TAGS and cls.__name__ in _TAGS[cls.__module__]:
        _record(v,cls.__module__,cls.__name__)
        for f in fields(v):
            if f.name in _FLAGS and getattr(v,f.name) is not False:
                raise ValueError('Captured release claims must remain literal False.')
        return (cls.__name__,tuple((f.name,_tree(getattr(v,f.name),mode)) for f in fields(v)))
    raise TypeError('Captured proof must be a deeply immutable primitive typed tree.')


def _same(a,b): return _tree(a)==_tree(b)


def _rows(v):
    if type(v) is not tuple or not v or any(type(i) is not int or i<0 for i in v) or len(set(v))!=len(v):
        raise ValueError('Missing/ambiguous positional source rows.')


def _section(s):
    _record(s,'cfw128_adapter','Section');_rows(s.source_rows)
    if (not all(_number(v) for v in (s.top_md,s.bottom_md,s.od_in,s.id_in))
            or not 0<=s.top_md<s.bottom_md or not 0<s.id_in<=s.od_in
            or (s.description=='Open Hole Size')!=(s.id_in==s.od_in)):
        raise ValueError('Invalid captured section dimensions/wall role.')


def _path(parts,top,shoe):
    if type(parts) is not tuple or not parts: raise ValueError('Missing captured path.')
    cursor=top
    for s in parts:
        _section(s)
        if s.top_md!=cursor: raise ValueError('Captured gap/overlap/order is not repairable.')
        cursor=s.bottom_md
    if cursor!=shoe: raise ValueError('Captured path must end at active Shoe.')


def _pairs(s,top,bottom):
    """Intersect ONLY already interpreted measured paths; no wall selection/parser."""
    left=top
    while left<bottom:
        run=[v for v in s.active_sections if v.top_md<=left<v.bottom_md]
        wall=[v for v in s.enclosing_sections if v.top_md<=left<v.bottom_md]
        if len(run)!=1 or len(wall)!=1: raise ValueError('Missing/ambiguous captured interval.')
        run,wall=run[0],wall[0];right=min(bottom,run.bottom_md,wall.bottom_md)
        if wall.id_in<=run.od_in: raise ValueError('Measured running clearance is invalid.')
        yield left,right,run,wall
        left=right


def _proof(s,a,sha):
    _record(s,'cfw128_adapter','GeometrySnapshot');_record(a,'cfw128_er03_volume','FrozenCapacityAudit')
    _tree(s);_tree(a)
    if type(sha) is not str or not re.fullmatch('[0-9a-f]{40}',sha): raise ValueError('Expected verified App SHA is required.')
    b=a.boundary;p=b.preview
    _record(b,'cfw128_er03_boundary','BoundaryHold');_record(p,'cfw128_er03_contract','TopologyPreview')
    for value in (s.app_source_sha,p.app_source_sha,b.expected_app_source_sha,a.expected_app_source_sha):
        if value!=sha: raise ValueError('Captured App SHA mismatch.')
    if (s.source_identity,s.request_identity,s.status,s.reason_codes)!=(p.upstream_source_identity,p.upstream_request_identity,p.upstream_status,p.upstream_reason_codes):
        raise ValueError('Capture and historical proof provenance differ.')
    for value in (s.source_identity,s.request_identity,p.source_identity,p.projection_identity,b.projection_identity,a.projection_identity):
        if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value): raise ValueError('Malformed captured identity.')
    if p.source_identity!=fingerprint(['cfw128-c1-source/1',sha,_tree(s)]): raise ValueError('C1 source binding differs.')
    valid=s.status in ('GEOMETRY_REPRESENTABLE','ENGINE_INTERFACE_NOT_REPRESENTABLE')
    if valid:
        for left,right in (('active_sections','injection_sections'),('enclosing_sections','enclosing_sections'),
            ('installed_strings','installed_strings'),('selected_host','selected_host'),('receiver','receiver'),
            ('survey','survey'),('trajectory','trajectory')):
            if not _same(getattr(s,left),getattr(p,right)): raise ValueError('Captured geometry and proof differ.')
        for name in ('job','kind','target_token','host_token','string_top_md','shoe_md'):
            if getattr(s,name)!=getattr(p,name): raise ValueError('Captured selection/boundary differs.')
        old_top=s.string_top_md if s.kind=='tieback' else 0.
        if (p.return_top_md,p.return_bottom_md)!=(old_top,s.shoe_md): raise ValueError('Historical return envelope changed.')
        old_id=fingerprint(['cfw128-c1-projection/1',p.source_identity,p.status,p.reason_codes,old_top,s.shoe_md,
                           tuple((_tree(v.wall),_tree(v.running)) for v in p.return_sections)])
    else:
        if a.status!='SOURCE_NOT_READY' or a.sections or p.injection_sections or p.return_sections:
            raise ValueError('Unavailable source cannot carry geometry.')
        old_id=fingerprint(['cfw128-c1-projection/1',p.source_identity,p.status,p.reason_codes])
    if p.projection_identity!=old_id: raise ValueError('C1 historical projection binding differs.')
    if any(getattr(b,n)!=('UNSPECIFIED' if n in _UNKNOWN[:3] else 'NOT_EVALUATED') for n in _UNKNOWN):
        raise ValueError('Historical boundary cannot carry solved quantities.')
    if valid:
        expected_ports=((0.,'injection','entry'),(s.shoe_md,'injection','exit'),(s.shoe_md,'annular_return','entry'),(old_top,'annular_return','exit'))
        if tuple((v.md_m,v.leg,v.direction) for v in b.physical_ports)!=expected_ports:raise ValueError('Historical ports differ.')
    elif b.physical_ports:raise ValueError('Unavailable source cannot carry ports.')
    if not set(s.reason_codes)<=set(p.reason_codes)<=set(b.reason_codes)<=set(a.reason_codes):raise ValueError('Historical holds were lost.')
    if b.instrument_provenance!='UNVERIFIED' or a.instrument_provenance!='UNVERIFIED': raise ValueError('Unverified instrument required.')
    if b.projection_identity!=fingerprint(['cfw128-c2a-boundary/1',sha,_tree(p,'c2a'),b.status,b.reason_codes,
                                         'ports-only-not-numerical-boundary',_UNKNOWN]):
        raise ValueError('C2a historical binding differs.')
    if a.boundary_projection_identity!=b.projection_identity or a.method_id!=_METHOD or a.units!=_UNITS:
        raise ValueError('C2b method/source differs.')
    def encoded(v):
        if v is None or type(v) is str:return (type(v).__name__,v)
        return _tree(v)
    projected=fingerprint(['cfw128-c2b-capacity/1',b.projection_identity,sha,_METHOD,_UNITS,a.status,a.reason_codes,
        tuple(tuple((f.name,encoded(getattr(v,f.name))) for f in fields(v)) for v in a.sections),
        encoded(a.nominal_injection_volume_bbl),encoded(a.nominal_annular_return_volume_bbl)])
    if a.projection_identity!=projected:raise ValueError('C2b capacity binding differs.')
    if not valid:return False
    if (a.status!='HOLD_GEOMETRIC_CAPACITY_ONLY' or b.status!='HOLD_ENGINE_BOUNDARY_UNVERIFIED'
            or chart_job_kind(s.job)!=s.kind or s.kind not in ('casing','liner','tieback')):
        raise ValueError('Not an applicable captured operation.')
    if not _number(s.string_top_md) or not _number(s.shoe_md) or not 0<=s.string_top_md<s.shoe_md:
        raise ValueError('Invalid active Top/Shoe.')
    _path(s.active_sections,0.,s.shoe_md);_path(s.enclosing_sections,0.,s.shoe_md)
    role={'casing':'Casing','liner':'Liner Shoe','tieback':'Tie Back Liner Shoe'}[s.kind]
    body=tuple(v for v in s.active_sections if v.description==role)
    dp=tuple(v for v in s.active_sections if v.description=='Drill Pipes')
    if not body or s.active_sections!=dp+body or body[0].top_md!=s.string_top_md:
        raise ValueError('Captured active roles/Top differ.')
    if (s.string_top_md==0. and dp) or (s.string_top_md>0. and (not dp or dp[-1].bottom_md!=s.string_top_md)):
        raise ValueError('Measured DP must cover exactly surface to Top, when needed.')
    if s.kind=='casing' and (dp or s.string_top_md!=0.):raise ValueError('Casing cannot acquire DP.')
    physical=[]
    for string in s.installed_strings:
        _rows(string.source_rows);_path(string.sections,string.top_md,string.shoe_md);physical.extend(string.sections)
        if tuple(i for part in string.sections for i in part.source_rows)!=string.source_rows:
            raise ValueError('Installed source-row identity differs.')
    if s.kind=='tieback':
        if (s.selected_host is None or not any(_same(s.selected_host,v) for v in s.installed_strings)
                or s.selected_host.description not in ('Casing','Previous Casing','Liner Shoe','Previous Liner Shoe')
                or s.receiver is None or not any(_same(s.receiver,v) for v in s.installed_strings)
                or not s.receiver.top_md<=s.shoe_md<s.receiver.shoe_md):
            raise ValueError('Captured selected host/receiver is missing or unrelated.')
        wall=next(v for v in s.enclosing_sections if v.top_md<=s.string_top_md<v.bottom_md)
        if (s.receiver.description not in ('Liner Shoe','Previous Liner Shoe')
                or not any(v.top_md<=s.string_top_md<v.bottom_md and (v.id_in,v.od_in)==(wall.id_in,wall.od_in)
                           and set(wall.source_rows)<=set(v.source_rows) for v in s.selected_host.sections)):
            raise ValueError('Selected host is not the captured immediate Top wall.')
    for left,right,run,wall in _pairs(s,0.,s.shoe_md):
        covered=[v for v in physical if v.top_md<=left and right<=v.bottom_md]
        if wall.description=='Open Hole Size':
            if covered:raise ValueError('Open Hole cannot replace an installed wall.')
        elif not any((v.id_in,v.od_in,v.description)==(wall.id_in,wall.od_in,wall.description)
                     and set(wall.source_rows)<=set(v.source_rows) for v in covered):
            raise ValueError('Enclosing wall has no captured installed provenance.')

    old_pairs=tuple(_pairs(s,old_top,s.shoe_md))
    if len(old_pairs)!=len(p.return_sections):raise ValueError('Historical return slices differ.')
    for (top,bottom,run,wall),part in zip(old_pairs,p.return_sections):
        for original,clipped in ((run,part.running),(wall,part.wall)):
            if (clipped.top_md,clipped.bottom_md,clipped.od_in,clipped.id_in,clipped.description,clipped.source_rows)!=(top,bottom,original.od_in,original.id_in,original.description,original.source_rows):
                raise ValueError('Historical slice is not from measured captured path.')
    expected=[('injection',v.top_md,v.bottom_md,v.source_rows,(),0.,v.id_in) for v in s.active_sections]
    expected += [('annular_return',t,z,run.source_rows,wall.source_rows,run.od_in,wall.id_in) for t,z,run,wall in old_pairs]
    if len(expected)!=len(a.sections):raise ValueError('Historical capacity sections differ.')
    for e,v in zip(expected,a.sections):
        if tuple(getattr(v,n) for n in ('leg','top_md','bottom_md','running_source_rows','wall_source_rows','inner_diameter_in','outer_diameter_in'))!=e:
            raise ValueError('Historical capacity source differs.')
        c=_capacity(e[-1],e[-2])
        if v.nominal_capacity_bbl_per_m!=c or v.nominal_section_volume_bbl!=c*(e[2]-e[1]):
            raise ValueError('Historical nominal quantity differs.')
    for leg,total in (('injection',a.nominal_injection_volume_bbl),('annular_return',a.nominal_annular_return_volume_bbl)):
        if total!=sum(v.nominal_section_volume_bbl for v in a.sections if v.leg==leg):raise ValueError('Historical total differs.')
    return True


@dataclass(frozen=True,slots=True)
class NominalSection:
    domain: str
    top_md: float
    bottom_md: float
    inner_diameter_in: float
    outer_diameter_in: float
    running_source_rows: tuple[int,...]
    wall_source_rows: tuple[int,...]

    def __post_init__(self):
        if type(self.domain) is not str or self.domain not in ('injection','lower_annulus','upper_pumping_annulus','upper_post_pull_bore'):
            raise ValueError('Unknown projection domain.')
        if (not all(_number(v) for v in (self.top_md,self.bottom_md,self.inner_diameter_in,self.outer_diameter_in))
                or not 0<=self.top_md<self.bottom_md or not 0<=self.inner_diameter_in<self.outer_diameter_in):
            raise ValueError('Invalid nominal projected interval/diameters.')
        for rows in (self.running_source_rows,self.wall_source_rows):
            if rows:_rows(rows)
            elif type(rows) is not tuple:raise TypeError('Rows must remain immutable.')
        c=self.nominal_capacity_bbl_per_m
        if not math.isfinite(c) or c<=0 or not math.isfinite(self.nominal_volume_bbl):raise ValueError('Nonfinite capacity.')

    @property
    def nominal_capacity_bbl_per_m(self):return _capacity(self.outer_diameter_in,self.inner_diameter_in)

    @property
    def nominal_volume_bbl(self):return self.nominal_capacity_bbl_per_m*(self.bottom_md-self.top_md)


def _project(s,a,sha):
    valid=_proof(s,a,sha)
    if not valid:return 'SOURCE_NOT_READY',(),(),(),()
    injection=tuple(NominalSection('injection',v.top_md,v.bottom_md,0.,v.id_in,v.source_rows,()) for v in s.active_sections)
    lower=[];upper=[];post=[]
    top=s.string_top_md if s.kind!='casing' else 0.
    for left,right,run,wall in _pairs(s,0.,s.shoe_md):
        cut=min(right,top) if left<top else right
        if left<top:
            upper.append(NominalSection('upper_pumping_annulus',left,cut,run.od_in,wall.id_in,run.source_rows,wall.source_rows))
            post.append(NominalSection('upper_post_pull_bore',left,cut,0.,wall.id_in,(),wall.source_rows))
        if right>top:
            lower.append(NominalSection('lower_annulus',max(left,top),right,run.od_in,wall.id_in,run.source_rows,wall.source_rows))
    return 'DISABLED_GEOMETRY_VIEW',injection,tuple(lower),tuple(upper),tuple(post)


def _view_id(source,sha,values):
    def token(v):
        if type(v) is NominalSection:return tuple((f.name,_tree(getattr(v,f.name))) for f in fields(v))
        if type(v) is tuple:return tuple(token(x) for x in v)
        return v
    return fingerprint(['c2d1-view/1',source,sha,token(values),'OWNER_SURFACE_CONNECTED_2026_11_11','NOT_CURRENTNESS_PROOF'])


@dataclass(frozen=True,slots=True)
class GeometryView:
    captured_geometry: object
    historical_capacity_audit: object
    app_source_sha: str
    source_identity: str
    projection_identity: str
    status: str
    injection: tuple[NominalSection,...]
    lower_annulus: tuple[NominalSection,...]
    upper_pumping_annulus: tuple[NominalSection,...]
    upper_post_pull_bore: tuple[NominalSection,...]
    corridor_contract: Literal['OWNER_SURFACE_CONNECTED_2026_11_11']=field(default='OWNER_SURFACE_CONNECTED_2026_11_11',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc: Literal['NOT_EVALUATED']=field(default='NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)

    def __post_init__(self):
        if any(type(getattr(self,n)) is not str for n in ('app_source_sha','source_identity','projection_identity','status','currentness','corridor_contract','hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc')):
            raise TypeError('View metadata must remain primitive immutable strings.')
        expected=_project(self.captured_geometry,self.historical_capacity_audit,self.app_source_sha)
        actual=(self.status,self.injection,self.lower_annulus,self.upper_pumping_annulus,self.upper_post_pull_bore)
        if any(type(parts) is not tuple or any(type(v) is not NominalSection for v in parts) for parts in actual[1:]):raise TypeError('Immutable typed sections required.')
        for parts in actual[1:]:
            for v in parts:NominalSection.__post_init__(v)
        for parts in (self.injection,self.upper_pumping_annulus+self.lower_annulus,self.upper_post_pull_bore+self.lower_annulus):
            if not math.isfinite(sum(v.nominal_volume_bbl for v in parts)):raise ValueError('Nonfinite nominal total.')
        source=fingerprint(['c2d1-captured-input/1',self.app_source_sha,_tree(self.captured_geometry),_tree(self.historical_capacity_audit)])
        if (actual!=expected or self.source_identity!=source or self.projection_identity!=_view_id(source,self.app_source_sha,actual)
                or self.corridor_contract!='OWNER_SURFACE_CONNECTED_2026_11_11' or self.currentness!='NOT_CURRENTNESS_PROOF' or self.hydraulic_inventory_transport_qout_freefall_bhsp_charts_toc!='NOT_EVALUATED'
                or any(getattr(self,n) is not False for n in _FLAGS)):
            raise ValueError('View must match its disabled source-only projection.')

    @property
    def pumping_return(self):return self.upper_pumping_annulus+self.lower_annulus

    @property
    def post_pull_return(self):
        return None if self.captured_geometry.kind=='casing' or self.status=='SOURCE_NOT_READY' else self.upper_post_pull_bore+self.lower_annulus

    @property
    def nominal_injection_bbl(self):return sum(v.nominal_volume_bbl for v in self.injection) if self.injection else None

    @property
    def nominal_pumping_return_bbl(self):return sum(v.nominal_volume_bbl for v in self.pumping_return) if self.pumping_return else None


def build_geometry_view(snapshot: object, capacity_proof: object, *, expected_app_source_sha: str) -> GeometryView:
    """Read caller's canonical captures; no imports, callbacks or state refresh."""
    values=_project(snapshot,capacity_proof,expected_app_source_sha)
    source=fingerprint(['c2d1-captured-input/1',expected_app_source_sha,_tree(snapshot),_tree(capacity_proof)])
    return GeometryView(snapshot,capacity_proof,expected_app_source_sha,source,
                        _view_id(source,expected_app_source_sha,values),*values)
