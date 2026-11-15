"""Disabled captured-inventory/physical-closure HOLD audit; no remapping law.

Reads only six caller-supplied frozen receipts; writes/state/schema/UI/Word and
new dependencies: none. App nominal capacity, density/taxonomy and fingerprint
primitives verify local captured consistency. No CFW import/callback, Hardware
parser, transport replay/composite executor, hydraulics or final TOC computation.
Published bindings are not authenticity/live currentness proof. Schedule source
ID contains uncaptured original MudType; its projection/stage bindings can be
checked, not original live state. Rounded captured volume consistency never
upgrades inherited precision HOLDs or proves physical post-pull conservation.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from fractions import Fraction
import math
import re
from typing import Literal

from cement_chart_model import _capacity, chart_job_kind, _number as _fluid_number
from engineering_tools import require_fluid_density, require_positive_density
from materials_db import HYDRAULIC_EXECUTION_ORDER, PLACEMENT_SLURRIES
from project_state import fingerprint

_FLAGS=('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified')
_TAGS={
 'cfw128_adapter':('GeometrySnapshot','Section','InstalledString','SurveyStation','TVDPoint'),
 'cfw128_er03_contract':('TopologyPreview','ReturnSection'),
 'cfw128_er03_boundary':('BoundaryHold','PhysicalPort'),
 'cfw128_er03_volume':('FrozenCapacityAudit','CapacitySection'),
 'cfw128_c2d_geometry_view':('GeometryView','NominalSection'),
 'cfw128_c2e4_derived_displacement':('DerivedDisplacement','DisplacementSection'),
 'cfw128_c2e3_post_pull_gap':('PostPullGapAudit','UpperCapacitySlice'),
 'cfw128_c2e5_effective_schedule':('EffectiveSchedule','EffectiveStage'),
 'cfw128_c2e_volume_tracking':('TrackingPreview','Stage','PathSection','Occupancy','StageLedger'),
 'cfw128_c2e2_cement_placement':('PlacementAssessment','CementStagePlacement','CementInterval'),
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
        if type(v.source_section_index) is not int:raise ValueError('Integer positional section index required.')
        for name in ('top_md','bottom_md','original_bottom_md','internal_id_in','capacity_bbl_per_m','nominal_volume_bbl'):
            _number(getattr(v,name),positive=name!='top_md')
        if tuple(f.name for f in fields(v))!=names or tuple(getattr(v,n) for n in names)!=want:raise ValueError('C2e4 section/ID/rows/capacity differs.')
    _number(d.derived_displacement_bbl,True)
    if d.derived_displacement_bbl!=total:raise ValueError('C2e4 total is not proved by the same injection geometry.')
    identity=fingerprint(['cfw128-c2e4-derived-displacement/1',sha,g.source_identity,g.projection_identity,
        s.job,s.kind,s.shoe_md,d.end_md,25.,tuple(expected),total,'NOMINAL_INTERNAL_STRING_CAPACITY','NONE_ADDED'])
    if d.projection_identity!=identity:raise ValueError('C2e4 published projection fingerprint differs.')
    return s


def _plain(rows):return tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in rows)


def _identity(v):
    if type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v):raise ValueError('Malformed capture identity.')


def _q(v):_number(v);return Fraction(v)


def _range(v):
    x=_q(v)
    if type(v) is int or v==0:return x,x
    a,b=math.nextafter(v,-math.inf),math.nextafter(v,math.inf)
    if not math.isfinite(b):raise ValueError('Overflow-boundary capture unsupported.')
    return (Fraction(a)+x)/2,(Fraction(b)+x)/2


def _reconcile(a,b):
    def bounds(values):
        pairs=tuple(_range(v) for v in values)
        return sum((x for x,y in pairs),Fraction()),sum((y for x,y in pairs),Fraction())
    x,y=bounds(a);u,v=bounds(b)
    if max(x,u)>min(y,v):raise ValueError('Captured volume partition does not reconcile.')
    return sum(map(Fraction,a),Fraction())==sum(map(Fraction,b),Fraction())


def _nominal(g,s):
    for name,top,bottom in (('injection',0.,s.shoe_md),('lower_annulus',s.string_top_md,s.shoe_md),('upper_pumping_annulus',0.,s.string_top_md),('upper_post_pull_bore',0.,s.string_top_md)):
        cursor=top
        for n in getattr(g,name):
            _kind(n,'cfw128_c2d_geometry_view','NominalSection')
            for x in (n.top_md,n.bottom_md,n.inner_diameter_in,n.outer_diameter_in):_number(x)
            if n.domain!=name or n.top_md!=cursor or not n.top_md<n.bottom_md<=bottom or not n.inner_diameter_in<n.outer_diameter_in:raise ValueError('Invalid/gapped canonical section.')
            run=[r for r in s.active_sections if r.top_md<=n.top_md and n.bottom_md<=r.bottom_md]
            wall=[r for r in s.enclosing_sections if r.top_md<=n.top_md and n.bottom_md<=r.bottom_md]
            if len(run)!=1 or name!='injection' and len(wall)!=1:raise ValueError('Missing/ambiguous captured section source.')
            if name=='injection':want=(0.,run[0].id_in,run[0].source_rows,())
            elif name=='upper_post_pull_bore':want=(0.,wall[0].id_in,(),wall[0].source_rows)
            else:want=(run[0].od_in,wall[0].id_in,run[0].source_rows,wall[0].source_rows)
            if (n.inner_diameter_in,n.outer_diameter_in,n.running_source_rows,n.wall_source_rows)!=want:raise ValueError('Captured ID/OD/source rows differ.')
            for rows in (n.running_source_rows,n.wall_source_rows):
                if rows:_rows(rows)
                elif type(rows) is not tuple:raise ValueError('Mutable source rows.')
            if name!='upper_post_pull_bore' and not n.running_source_rows or name!='injection' and not n.wall_source_rows:raise ValueError('Missing nominal source rows.')
            cursor=n.bottom_md
        if cursor!=bottom:raise ValueError('Incomplete canonical leg.')


def _volume(n):
    try:v=(n.bottom_md-n.top_md)*_capacity(n.outer_diameter_in,n.inner_diameter_in)
    except OverflowError:raise ValueError('Nominal capacity overflow.') from None
    _number(v,True);return v


def _gap(g,b,s,sha):
    if len(g.upper_pumping_annulus)!=len(g.upper_post_pull_bore) or len(b.slices)!=len(g.upper_pumping_annulus):raise ValueError('Unpaired upper geometry/gap receipt.')
    for p,z,v in zip(g.upper_pumping_annulus,g.upper_post_pull_bore,b.slices):
        _kind(v,'cfw128_c2e3_post_pull_gap','UpperCapacitySlice')
        if (p.top_md,p.bottom_md,p.outer_diameter_in,p.wall_source_rows)!=(z.top_md,z.bottom_md,z.outer_diameter_in,z.wall_source_rows):raise ValueError('Post-pull upper pairing differs.')
        a,c=_volume(p),_volume(z)
        expected=(p.top_md,p.bottom_md,p.outer_diameter_in,p.inner_diameter_in,p.running_source_rows,p.wall_source_rows,
                  _capacity(p.outer_diameter_in,p.inner_diameter_in),_capacity(z.outer_diameter_in),a,c,c-a,'PUMPING_DP_PRESENT','POST_PULL_DP_REMOVED')
        if _plain((v,))[0]!=expected or c<=a:raise ValueError('Gap slice is not the captured geometric capacity difference.')
    casing=s.kind=='casing';status='NOT_APPLICABLE' if casing else 'DISABLED_POST_PULL_CAPACITY_GAP_AUDIT'
    boundary='NOT_APPLICABLE' if casing else 'HOLD_POST_PULL_FLUID_BOUNDARY_UNDEFINED'
    totals=(sum(_volume(v) for v in g.injection),sum(_volume(v) for v in g.lower_annulus),
        None if casing else sum(v.pumping_volume_bbl for v in b.slices),None if casing else sum(v.post_pull_volume_bbl for v in b.slices),None if casing else sum(v.capacity_gap_bbl for v in b.slices))
    if casing and b.slices or (b.job,b.kind,b.lap_md,b.shoe_md,b.status,b.post_pull_fluid_boundary)!=(s.job,s.kind,s.string_top_md,s.shoe_md,status,boundary):raise ValueError('Gap operation/boundary differs.')
    if (b.unchanged_injection_bbl,b.unchanged_lower_annulus_bbl,b.upper_pumping_bbl,b.upper_post_pull_bbl,b.capacity_gap_bbl)!=totals:raise ValueError('Gap totals differ.')
    if b.displacement_volume_authority!='HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED' or b.other_pumped_volume_authority!='ENTERED_PHASE_IV_STAGE_VOLUMES':raise ValueError('Historical gap authority changed.')
    expected=fingerprint(['cfw128-c2e3-geometric-gap/1',sha,g.source_identity,g.projection_identity,s.job,s.kind,s.string_top_md,s.shoe_md,status,_plain(b.slices),*totals,boundary,'HOLD_DERIVED_DISPLACEMENT_NOT_IMPLEMENTED','ENTERED_PHASE_IV_STAGE_VOLUMES','NOT_CURRENTNESS_PROOF'])
    if b.projection_identity!=expected:raise ValueError('Gap fingerprint differs.')


def _schedule(g,d,r,t,s,sha):
    _identity(r.source_identity)
    if r.derived_projection_identity!=d.projection_identity or (r.job,r.kind)!=(s.job,s.kind) or r.status!='DISABLED_EFFECTIVE_PUMPING_SCHEDULE' or r.completion_basis!='ALL_SELECTED_EFFECTIVE_STAGE_VOLUMES':raise ValueError('Schedule parent/operation differs.')
    names=tuple(v.name for v in r.stages)
    if len(set(names))!=len(names) or names!=tuple(n for n in HYDRAULIC_EXECUTION_ORDER if n in names) or 'Displacement Fluid' not in names:raise ValueError('Invalid effective stage selection/order.')
    if len(t.stages)!=len(r.stages):raise ValueError('Tracking/effective stage count differs.')
    exact=Fraction();consumed=[]
    for v,a in zip(r.stages,t.stages):
        _kind(v,'cfw128_c2e5_effective_schedule','EffectiveStage');_kind(a,'cfw128_c2e_volume_tracking','Stage')
        _number(v.volume_bbl,True);_number(v.density_pcf,True)
        if type(v.raw_density) not in (str,int,float) or v.density_pcf!=require_fluid_density(v.name,v.raw_density):raise ValueError('Captured density source differs.')
        mud=v.name=='Displacement Fluid'
        if mud:
            if v.volume_authority!='DERIVED_C2E4_INTERNAL_STRING_CAPACITY' or v.record_source!='C2E4' or v.raw_entered_volume is not None or v.volume_bbl!=d.derived_displacement_bbl or v.density_source not in ('state.mud_density','well_data.mud_density'):raise ValueError('Derived Mud authority differs.')
            if a.source not in ('fluids_config.params','fluid_data') or a.raw_volume!=v.volume_bbl:raise ValueError('Tracking overlay did not use verified derived Mud.')
        else:
            _number(v.raw_entered_volume,True)
            if Fraction(v.raw_entered_volume)!=Fraction(v.volume_bbl) or v.volume_authority!='ENTERED_PHASE_IV' or v.record_source not in ('fluids_config.params','fluid_data') or a.source!=v.record_source or type(a.raw_volume) is not type(v.raw_entered_volume) or a.raw_volume!=v.raw_entered_volume or v.density_source!=v.record_source+'.'+v.name+'.density':raise ValueError('Entered-stage provenance differs.')
        if (a.name,a.volume_bbl,a.density_pcf,a.raw_density)!=(v.name,v.volume_bbl,v.density_pcf,v.raw_density):raise ValueError('Tracking stage differs from effective schedule.')
        identity=fingerprint(['cfw128-c2e5-stage/1',v.name,v.volume_authority,v.record_source,v.raw_entered_volume,v.volume_bbl,v.raw_density,v.density_pcf,v.density_source,d.projection_identity if mud else None])
        if v.source_identity!=identity:raise ValueError('Effective stage source fingerprint differs.')
        consumed.append((a.name,a.source,a.raw_volume,a.raw_density));exact+=Fraction(v.volume_bbl)
    mud=r.stages[-1]
    if t.initial_mud_density_pcf!=mud.density_pcf:raise ValueError('Initial Mud density source differs.')
    if type(r.total_volume_exact_bbl) is not tuple or len(r.total_volume_exact_bbl)!=2 or any(type(x) is not int for x in r.total_volume_exact_bbl) or r.total_volume_exact_bbl[1]<=0 or Fraction(*r.total_volume_exact_bbl)!=exact or r.total_volume_bbl!=float(exact):raise ValueError('Effective total differs.')
    if r.projection_identity!=fingerprint(['cfw128-c2e5-effective-schedule/1',r.source_identity,_plain(r.stages),r.total_volume_bbl,r.total_volume_exact_bbl,'ALL_SELECTED_EFFECTIVE_STAGE_VOLUMES']):raise ValueError('Schedule projection differs.')
    if t.source_identity!=fingerprint(['cfw128-c2e-source/1',g.source_identity,g.projection_identity,sha,s.job,tuple(consumed),mud.raw_density]):raise ValueError('Tracking source is not the captured effective composition.')


def _tracking(g,t,s):
    if t.status!='DISABLED_VOLUME_TRACKING_PREVIEW' or t.toc!='TOC_NOT_EVALUATED' or t.trajectory!=tuple((p.md,p.tvd) for p in s.trajectory):raise ValueError('Tracking metadata/trajectory differs.')
    if t.projection_identity!=fingerprint(['cfw128-c2e-volume/1',t.source_identity,t.cumulative_injected_bbl,_plain(t.occupancy),_plain(t.ledgers),t.mud_remaining_bbl,t.mud_displaced_bbl]):raise ValueError('Tracking projection differs.')
    parts=g.injection+tuple(reversed(g.lower_annulus))+tuple(reversed(g.upper_pumping_annulus));volumes=[];start=0.;last_md=0.
    if len(parts)!=len(t.path):raise ValueError('Missing/duplicated path.')
    for n,p in zip(parts,t.path):
        _kind(p,'cfw128_c2e_volume_tracking','PathSection');volumes.append(_volume(n));end=math.fsum(volumes)
        a,b=(n.top_md,n.bottom_md) if n.domain=='injection' else (n.bottom_md,n.top_md)
        if _plain((p,))[0]!=(n.domain,a,b,start,end,_capacity(n.outer_diameter_in,n.inner_diameter_in),n.running_source_rows,n.wall_source_rows) or a!=last_md or end<=start:raise ValueError('Path/capacity/source differs.')
        start=end;last_md=b
    if last_md!=0. or t.total_nominal_capacity_bbl!=start:raise ValueError('Invalid pumping domain; no receiver extension.')
    densities={a.name:a.density_pcf for a in t.stages};densities['Mud']=t.initial_mud_density_pcf
    byfluid={n:[] for n in densities};groups=[[] for p in t.path];seen=set();exact=True
    for o in t.occupancy:
        _kind(o,'cfw128_c2e_volume_tracking','Occupancy');_number(o.volume_bbl,True);_number(o.inlet_md);_number(o.outlet_md)
        if type(o.section_index) is not int or not 0<=o.section_index<len(groups) or o.fluid not in densities or o.density_pcf!=densities[o.fluid] or (o.fluid,o.section_index) in seen:raise ValueError('Invalid/duplicate occupancy identity.')
        seen.add((o.fluid,o.section_index));p=t.path[o.section_index];down=p.outlet_md>p.inlet_md
        if not (p.inlet_md<=o.inlet_md<o.outlet_md<=p.outlet_md if down else p.outlet_md<=o.outlet_md<o.inlet_md<=p.inlet_md):raise ValueError('Invalid occupied MD.')
        groups[o.section_index].append(o);byfluid[o.fluid].append(o)
    for p,rows in zip(t.path,groups):
        rows.sort(key=lambda x:x.inlet_md,reverse=p.outlet_md<p.inlet_md);cursor=p.inlet_md;lo=hi=Fraction();width=Fraction(p.end_bbl)-Fraction(p.start_bbl)
        def md(x):
            if x<=0:return p.inlet_md
            if x>=width:return p.outlet_md
            return p.inlet_md+float(x/width)*(p.outlet_md-p.inlet_md)
        for o in rows:
            if o.inlet_md!=cursor:raise ValueError('Occupied gap/overlap.')
            a,b=_range(o.volume_bbl);lo+=a;hi+=b;bounds=sorted((md(lo),md(hi)))
            if not bounds[0]<=o.outlet_md<=bounds[1]:raise ValueError('Occupied volume/MD differs.')
            cursor=o.outlet_md
        if cursor!=p.outlet_md or not lo<=width<=hi:raise ValueError('Incomplete occupied partition.')
        exact &= sum((Fraction(o.volume_bbl) for o in rows),Fraction())==width
    if tuple(v.fluid for v in t.ledgers)!=tuple(v.name for v in t.stages):raise ValueError('Unmatched stage ledgers.')
    for a,b in zip(t.stages,t.ledgers):
        _kind(b,'cfw128_c2e_volume_tracking','StageLedger')
        for x in (b.entered_bbl,b.in_path_bbl,b.ideal_returned_bbl):_number(x)
        if b.entered_bbl>a.volume_bbl:raise ValueError('Entered amount exceeds source.')
        exact &= _reconcile([b.entered_bbl],[b.in_path_bbl,b.ideal_returned_bbl])
        exact &= _reconcile([b.in_path_bbl],[v.volume_bbl for v in byfluid[a.name]])
    exact &= _reconcile([t.mud_remaining_bbl],[v.volume_bbl for v in byfluid['Mud']])
    exact &= _reconcile([t.total_nominal_capacity_bbl],[t.mud_remaining_bbl,t.mud_displaced_bbl])
    exact &= _reconcile([t.total_nominal_capacity_bbl],[t.mud_remaining_bbl]+[v.in_path_bbl for v in t.ledgers])
    exact &= _reconcile([t.cumulative_injected_bbl],[v.entered_bbl for v in t.ledgers])
    return byfluid,exact


def _placement(g,t,p,r,s,byfluid,exact,sha):
    if not exact and 'HOLD_VOLUME_RECONCILIATION_PRECISION' not in p.reason_codes:raise ValueError('Lost captured precision HOLD.')
    if (p.tracking_source_identity,p.tracking_projection_identity)!=(t.source_identity,t.projection_identity) or p.status!='DISABLED_PUMP_END_PLACEMENT_PREVIEW':raise ValueError('Placement source association differs.')
    post='NOT_APPLICABLE' if s.kind=='casing' else 'HOLD_POST_PULL_REMAP_UNDEFINED'
    if p.post_pull_reason!=post:raise ValueError('Prior post-pull HOLD changed.')
    if p.projection_identity!=fingerprint(['cfw128-c2e2-placement/1',sha,g.source_identity,g.projection_identity,t.source_identity,t.projection_identity,_plain(p.stages),_plain(p.annular_intervals),p.other_fluid_occupancy,p.pumping_state_toc_candidate_md,p.reason_codes,post]):raise ValueError('Placement projection differs.')
    cements=[v for v in r.stages if v.name in PLACEMENT_SLURRIES]
    if tuple(v.fluid for v in p.stages)!=tuple(v.name for v in cements):raise ValueError('Cement identities differ.')
    for stage,part in zip(cements,p.stages):
        _kind(part,'cfw128_c2e2_cement_placement','CementStagePlacement');ledger=next(v for v in t.ledgers if v.fluid==stage.name)
        amounts=tuple(math.fsum(v.volume_bbl for v in byfluid[stage.name] if t.path[v.section_index].domain==domain) for domain in ('injection','lower_annulus','upper_pumping_annulus'))
        if _plain((part,))[0]!=(stage.name,stage.volume_bbl,ledger.entered_bbl,*amounts,ledger.ideal_returned_bbl):raise ValueError('Placement compartment partition differs.')
        exact &= _reconcile([part.entered_bbl],[*amounts,part.ideal_surface_returned_bbl])
    annular=[];others=[]
    for o in t.occupancy:
        path=t.path[o.section_index]
        if o.fluid not in PLACEMENT_SLURRIES:others.append((o.fluid,o.section_index,o.inlet_md,o.outlet_md,o.volume_bbl))
        elif path.domain!='injection':annular.append((o.fluid,path.domain,o.section_index,min(o.inlet_md,o.outlet_md),max(o.inlet_md,o.outlet_md),o.volume_bbl,path.running_source_rows,path.wall_source_rows))
    annular.sort(key=lambda x:x[3])
    if _plain(p.annular_intervals)!=tuple(annular) or p.other_fluid_occupancy!=tuple(others) or p.surface_cement_return_present!=any(v.ideal_surface_returned_bbl>0 for v in p.stages):raise ValueError('Placement intervals/returns differ.')
    complete=all(v.entered_bbl==a.volume_bbl for v,a in zip(t.ledgers,r.stages))
    if not complete and 'HOLD_SCHEDULE_INCOMPLETE' not in p.reason_codes:raise ValueError('Lost schedule HOLD.')
    if not cements and 'HOLD_NO_PLACED_CEMENT' not in p.reason_codes:raise ValueError('Lost no-placed-cement HOLD.')
    if Fraction(t.cumulative_injected_bbl)!=Fraction(*r.total_volume_exact_bbl) and complete and 'HOLD_TERMINAL_VOLUME_PRECISION_UNPROVEN' not in p.reason_codes:raise ValueError('Lost terminal precision HOLD.')
    if any(v.retained_injection_bbl>0 for v in p.stages) and 'HOLD_CEMENT_REMAINS_IN_INJECTION' not in p.reason_codes:raise ValueError('Lost injection-cement HOLD.')
    if not annular and 'HOLD_NO_ANNULAR_CEMENT' not in p.reason_codes:raise ValueError('Lost missing-annulus HOLD.')
    if annular and annular[-1][4]!=s.shoe_md and 'HOLD_CEMENT_NOT_ANCHORED_AT_SHOE' not in p.reason_codes:raise ValueError('Lost shoe-anchoring HOLD.')
    if any(a[4]!=b[3] for a,b in zip(annular,annular[1:])) and 'HOLD_DISCONNECTED_ANNULAR_CEMENT' not in p.reason_codes:raise ValueError('Lost disconnected-cement HOLD.')
    candidate=p.pumping_state_toc_candidate_md
    if candidate is not None and (p.reason_codes or not annular or candidate!=annular[0][3]):raise ValueError('Unproved pump-state candidate.')
    if candidate is None and not p.reason_codes:raise ValueError('Missing placement HOLD.')
    return exact,complete


@dataclass(frozen=True,slots=True)
class FluidInventory:
    fluid: str
    volume_authority: str
    raw_entered_volume: int | float | None
    configured_bbl: float
    actually_entered_bbl: float
    injection_bbl: float
    lower_annulus_bbl: float
    upper_pumping_annulus_bbl: float
    ideal_returned_bbl: float
    stage_source_identity: str


@dataclass(frozen=True,slots=True)
class ClosureAudit:
    app_source_sha: str
    receipt_projection_identities: tuple[tuple[str,str],...]
    projection_identity: str
    job: str
    kind: str
    active_lap_md: float
    active_shoe_md: float
    displacement_end_md: float
    derived_displacement_bbl: float
    upper_pumping_capacity_bbl: float | None
    upper_post_pull_capacity_bbl: float | None
    nominal_capacity_gap_bbl: float | None
    gap_status: str
    cement_inventory: tuple[FluidInventory,...]
    noncement_inventory: tuple[FluidInventory,...]
    initial_mud_remaining_bbl: float
    ideal_initial_mud_returned_bbl: float
    initial_mud_occupancy: tuple[tuple[int,float,float,float],...]
    surface_cement_return_present: bool
    preserved_placement_holds: tuple[str,...]
    inventory_evidence: str
    capture_completeness: str
    physical_remap_status: str
    unresolved_decisions: tuple[str,...]
    terminal_shoe_behavior: Literal['HOLD_25M_TERMINAL_PLACEMENT_BEHAVIOR_UNDEFINED']=field(default='HOLD_25M_TERMINAL_PLACEMENT_BEHAVIOR_UNDEFINED',init=False)
    status: Literal['DISABLED_POST_PULL_CLOSURE_AUDIT']=field(default='DISABLED_POST_PULL_CLOSURE_AUDIT',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['HYDRAULICS_NOT_EVALUATED']=field(default='HYDRAULICS_NOT_EVALUATED',init=False)
    final_post_pull_toc: Literal['FINAL_POST_PULL_TOC_NOT_EVALUATED']=field(default='FINAL_POST_PULL_TOC_NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def audit_post_pull_closure(geometry: object,gap: object,derived: object,schedule: object,tracking: object,placement: object,*,expected_app_source_sha: str) -> ClosureAudit:
    """Validate copied nominal receipts and expose unknown closure; no remap."""
    g,b,d,r,t,p=geometry,gap,derived,schedule,tracking,placement;sha=expected_app_source_sha
    s=_verify_derived(g,d,sha)
    for v,module,name in ((b,'cfw128_c2e3_post_pull_gap','PostPullGapAudit'),(r,'cfw128_c2e5_effective_schedule','EffectiveSchedule'),(t,'cfw128_c2e_volume_tracking','TrackingPreview'),(p,'cfw128_c2e2_cement_placement','PlacementAssessment')):
        _tree(v);_kind(v,module,name)
        if v.app_source_sha!=sha or (v.geometry_source_identity,v.geometry_projection_identity)!=(g.source_identity,g.projection_identity) or v.currentness!='NOT_CURRENTNESS_PROOF':raise ValueError('Cross-receipt SHA/geometry binding differs.')
        _identity(v.projection_identity)
        if v.hydraulics!=('NOT_EVALUATED' if v is b else 'HYDRAULICS_NOT_EVALUATED'):raise ValueError('Hydraulic HOLD missing.')
    if p.final_post_pull_toc!='FINAL_POST_PULL_TOC_NOT_EVALUATED' or r.final_post_pull_toc!='FINAL_POST_PULL_TOC_NOT_EVALUATED' or b.final_toc!='NOT_EVALUATED':raise ValueError('Final placement HOLD missing.')
    _nominal(g,s);_gap(g,b,s,sha);_schedule(g,d,r,t,s,sha);byfluid,exact=_tracking(g,t,s);exact,complete=_placement(g,t,p,r,s,byfluid,exact,sha)
    inventory=[]
    for stage,ledger in zip(r.stages,t.ledgers):
        amounts=tuple(math.fsum(o.volume_bbl for o in byfluid[stage.name] if t.path[o.section_index].domain==domain) for domain in ('injection','lower_annulus','upper_pumping_annulus'))
        inventory.append(FluidInventory(stage.name,stage.volume_authority,stage.raw_entered_volume,stage.volume_bbl,ledger.entered_bbl,*amounts,ledger.ideal_returned_bbl,stage.source_identity))
    cements=tuple(v for v in inventory if v.fluid in PLACEMENT_SLURRIES);others=tuple(v for v in inventory if v.fluid not in PLACEMENT_SLURRIES)
    casing=s.kind=='casing';physical='NOT_APPLICABLE' if casing else 'HOLD_POST_PULL_PHYSICAL_REMAP_UNDEFINED'
    decisions=() if casing else ('HOLD_POST_PULL_FILL_SOURCE_AND_VOLUME_UNDEFINED','HOLD_WITHDRAWN_STRING_TRANSFER_OR_RECOVERY_UNDEFINED','HOLD_PULL_DISPLACEMENT_RETURN_PATH_AND_ORDER_UNDEFINED','HOLD_POST_PULL_FLUID_MASS_VOLUME_CLOSURE_UNDEFINED')
    evidence='CAPTURED_NOMINAL_LEDGER_RECONCILED' if exact and not any('PRECISION' in x for x in p.reason_codes) else 'CAPTURED_ROUNDED_WITH_PRESERVED_UNCERTAINTY'
    completion='COMPLETE_CONFIGURED_VOLUME_CAPTURE' if complete else 'HOLD_SCHEDULE_INCOMPLETE'
    mud=tuple((o.section_index,o.inlet_md,o.outlet_md,o.volume_bbl) for o in byfluid['Mud'])
    parents=tuple((name,v.projection_identity) for name,v in (('geometry',g),('gap',b),('derived',d),('schedule',r),('tracking',t),('placement',p)))
    identity=fingerprint(['cfw128-c2e6a-closure/1',sha,parents,_plain(cements),_plain(others),t.mud_remaining_bbl,t.mud_displaced_bbl,mud,p.reason_codes,evidence,completion,physical,decisions,'FINAL_POST_PULL_TOC_NOT_EVALUATED'])
    return ClosureAudit(sha,parents,identity,s.job,s.kind,s.string_top_md,s.shoe_md,d.end_md,d.derived_displacement_bbl,b.upper_pumping_bbl,b.upper_post_pull_bbl,b.capacity_gap_bbl,b.status,cements,others,t.mud_remaining_bbl,t.mud_displaced_bbl,mud,p.surface_cement_return_present,p.reason_codes,evidence,completion,physical,decisions)
