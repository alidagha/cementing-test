"""Disabled dry-pipe nominal balance, never post-pull transport or Final TOC.

Reads caller-frozen C2d geometry, C2e3 gap, C2e6a closure, C2e1 occupancy
and C2e5 schedule. Schedule is needed to verify the opaque schedule parent
and stage fingerprints; occupancy is needed to prove actual DP Mud contents.
Tracking is required to prove actual DP contents are Mud before calling ID
capacity drained Mud. Writes/state/schema/UI/Word/dependencies/callers: none.
App capacity/fingerprint/taxonomy remain authorities. No CFW import/callback,
Hardware parser, transport replay, solver or cement transfer. Published receipt
binding checks consistency, not authenticity or live currentness.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from fractions import Fraction
import math
import re
from typing import Literal

from cement_chart_model import _capacity, chart_job_kind
from engineering_tools import require_fluid_density
from materials_db import HYDRAULIC_EXECUTION_ORDER, PLACEMENT_SLURRIES
from project_state import fingerprint

_FLAGS=('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified')
_TAGS={
 'cfw128_adapter':('GeometrySnapshot','Section','InstalledString','SurveyStation','TVDPoint'),
 'cfw128_er03_contract':('TopologyPreview','ReturnSection'),
 'cfw128_er03_boundary':('BoundaryHold','PhysicalPort'),
 'cfw128_er03_volume':('FrozenCapacityAudit','CapacitySection'),
 'cfw128_c2d_geometry_view':('GeometryView','NominalSection'),
 'cfw128_c2e3_post_pull_gap':('PostPullGapAudit','UpperCapacitySlice'),
 'cfw128_c2e5_effective_schedule':('EffectiveSchedule','EffectiveStage'),
 'cfw128_c2e_volume_tracking':('TrackingPreview','Stage','PathSection','Occupancy','StageLedger'),
 'cfw128_c2e6a_post_pull_closure':('ClosureAudit','FluidInventory'),
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
    for name in ('lap_md','shoe_md','unchanged_injection_bbl','unchanged_lower_annulus_bbl','upper_pumping_bbl','upper_post_pull_bbl','capacity_gap_bbl'):
        if getattr(b,name) is not None:_number(getattr(b,name))
    if len(g.upper_pumping_annulus)!=len(g.upper_post_pull_bore) or len(b.slices)!=len(g.upper_pumping_annulus):raise ValueError('Unpaired upper geometry/gap receipt.')
    for p,z,v in zip(g.upper_pumping_annulus,g.upper_post_pull_bore,b.slices):
        _kind(v,'cfw128_c2e3_post_pull_gap','UpperCapacitySlice')
        for name in ('top_md','bottom_md','host_id_in','drill_pipe_od_in','pumping_capacity_bbl_per_m','post_pull_capacity_bbl_per_m','pumping_volume_bbl','post_pull_volume_bbl','capacity_gap_bbl'):
            _number(getattr(v,name),positive=name!='top_md')
        _rows(v.running_source_rows);_rows(v.wall_source_rows)
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


def _tracking(g,t,s):
    if t.status!='DISABLED_VOLUME_TRACKING_PREVIEW' or t.toc!='TOC_NOT_EVALUATED' or _tree(t.trajectory)!=_tree(tuple((p.md,p.tvd) for p in s.trajectory)):raise ValueError('Tracking metadata/trajectory differs.')
    _number(t.initial_mud_density_pcf,True)
    for stage in t.stages:
        _kind(stage,'cfw128_c2e_volume_tracking','Stage');_number(stage.volume_bbl,True);_number(stage.density_pcf,True)
    for ledger in t.ledgers:_kind(ledger,'cfw128_c2e_volume_tracking','StageLedger')
    if t.projection_identity!=fingerprint(['cfw128-c2e-volume/1',t.source_identity,t.cumulative_injected_bbl,_plain(t.occupancy),_plain(t.ledgers),t.mud_remaining_bbl,t.mud_displaced_bbl]):raise ValueError('Tracking projection differs.')
    parts=g.injection+tuple(reversed(g.lower_annulus))+tuple(reversed(g.upper_pumping_annulus));volumes=[];start=0.;last_md=0.
    if len(parts)!=len(t.path):raise ValueError('Missing/duplicated path.')
    for n,p in zip(parts,t.path):
        _kind(p,'cfw128_c2e_volume_tracking','PathSection');volumes.append(_volume(n));end=math.fsum(volumes)
        for name in ('inlet_md','outlet_md','start_bbl','end_bbl','capacity_bbl_per_m'):_number(getattr(p,name))
        _rows(p.running_source_rows)
        if p.wall_source_rows:_rows(p.wall_source_rows)
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



def _derived_parent(g,s,c,parent,sha):
    """Check the published C2e4 fingerprint, not a replacement volume authority."""
    end=s.shoe_md-25.;parts=[];total=0.;cursor=0.
    for i,(n,r) in enumerate(zip(g.injection,s.active_sections)):
        if n.bottom_md<=n.top_md or n.top_md!=cursor:raise ValueError('Invalid injection continuity.')
        cursor=n.bottom_md;bottom=min(n.bottom_md,end)
        if bottom<=n.top_md:continue
        cap=_capacity(n.outer_diameter_in);volume=(bottom-n.top_md)*cap;_number(volume,True)
        updated=total+volume;_number(updated,True)
        if updated<=total:raise ValueError('Unprovable source displacement precision.')
        total=updated
        parts.append((i,r.description,n.top_md,bottom,n.bottom_md,n.outer_diameter_in,n.running_source_rows,cap,volume))
    identity=fingerprint(['cfw128-c2e4-derived-displacement/1',sha,g.source_identity,g.projection_identity,s.job,s.kind,s.shoe_md,end,25.,tuple(parts),total,'NOMINAL_INTERNAL_STRING_CAPACITY','NONE_ADDED'])
    if (parent['derived']!=identity or c.displacement_end_md!=end or c.derived_displacement_bbl!=total):raise ValueError('Original 25 m displacement parent/value differs.')


def _closure(g,b,c,t,r,s,sha,byfluid,exact):
    """Reconcile already-captured summaries; never replay stage displacement."""
    _kind(c,'cfw128_c2e6a_post_pull_closure','ClosureAudit')
    for name in ('active_lap_md','active_shoe_md','displacement_end_md','derived_displacement_bbl','initial_mud_remaining_bbl','ideal_initial_mud_returned_bbl','upper_pumping_capacity_bbl','upper_post_pull_capacity_bbl','nominal_capacity_gap_bbl'):
        if getattr(c,name) is not None:_number(getattr(c,name))
    if type(c.surface_cement_return_present) is not bool:raise ValueError('Boolean return-presence evidence required.')
    if (c.app_source_sha!=sha or (c.job,c.kind,c.active_lap_md,c.active_shoe_md)!=(s.job,s.kind,s.string_top_md,s.shoe_md)
            or c.status!='DISABLED_POST_PULL_CLOSURE_AUDIT' or c.currentness!='NOT_CURRENTNESS_PROOF'
            or c.hydraulics!='HYDRAULICS_NOT_EVALUATED' or c.final_post_pull_toc!='FINAL_POST_PULL_TOC_NOT_EVALUATED'
            or c.terminal_shoe_behavior!='HOLD_25M_TERMINAL_PLACEMENT_BEHAVIOR_UNDEFINED'):
        raise ValueError('Only the same held C2e6a closure is admissible.')
    parents=c.receipt_projection_identities
    if any(type(v) is not tuple or len(v)!=2 for v in parents) or tuple(v[0] for v in parents)!=('geometry','gap','derived','schedule','tracking','placement'):raise ValueError('Malformed closure parent records.')
    parent=dict(parents)
    for v in parent.values():_identity(v)
    if (parent['geometry'],parent['gap'],parent['tracking'],parent['schedule'])!=(g.projection_identity,b.projection_identity,t.projection_identity,r.projection_identity):raise ValueError('Mixed closure/geometry/gap/tracking/schedule parents.')
    _derived_parent(g,s,c,parent,sha)
    _identity(r.source_identity)
    _number(r.total_volume_bbl,True)
    if (r.job,r.kind,r.derived_projection_identity,r.status,r.completion_basis,r.final_post_pull_toc)!=(s.job,s.kind,parent['derived'],'DISABLED_EFFECTIVE_PUMPING_SCHEDULE','ALL_SELECTED_EFFECTIVE_STAGE_VOLUMES','FINAL_POST_PULL_TOC_NOT_EVALUATED'):raise ValueError('Schedule operation/source HOLD differs.')
    for stage in r.stages:_kind(stage,'cfw128_c2e5_effective_schedule','EffectiveStage')
    if len(r.stages)!=len(t.stages) or tuple(v.name for v in r.stages)!=tuple(v.name for v in t.stages):raise ValueError('Schedule stage identities differ.')
    total=Fraction()
    for v in r.stages:
        _kind(v,'cfw128_c2e5_effective_schedule','EffectiveStage');_number(v.volume_bbl,True)
        try:before,after=float(total),float(total+Fraction(v.volume_bbl))
        except OverflowError:raise ValueError('Unprovable schedule volume overflow.') from None
        _number(after,True)
        if after<=before:raise ValueError('Schedule stage lost at source precision.')
        total+=Fraction(v.volume_bbl)
    pair=r.total_volume_exact_bbl
    if type(pair) is not tuple or len(pair)!=2 or any(type(v) is not int for v in pair) or pair[1]<=0 or Fraction(*pair)!=total or r.total_volume_bbl!=float(total):raise ValueError('Schedule total differs.')
    if r.projection_identity!=fingerprint(['cfw128-c2e5-effective-schedule/1',r.source_identity,_plain(r.stages),r.total_volume_bbl,r.total_volume_exact_bbl,r.completion_basis]):raise ValueError('Schedule projection differs.')
    if (c.upper_pumping_capacity_bbl,c.upper_post_pull_capacity_bbl,c.nominal_capacity_gap_bbl,c.gap_status)!=(b.upper_pumping_bbl,b.upper_post_pull_bbl,b.capacity_gap_bbl,b.status):raise ValueError('Closure upper geometry differs.')
    casing=s.kind=='casing';physical='NOT_APPLICABLE' if casing else 'HOLD_POST_PULL_PHYSICAL_REMAP_UNDEFINED'
    decisions=() if casing else ('HOLD_POST_PULL_FILL_SOURCE_AND_VOLUME_UNDEFINED','HOLD_WITHDRAWN_STRING_TRANSFER_OR_RECOVERY_UNDEFINED','HOLD_PULL_DISPLACEMENT_RETURN_PATH_AND_ORDER_UNDEFINED','HOLD_POST_PULL_FLUID_MASS_VOLUME_CLOSURE_UNDEFINED')
    if (c.physical_remap_status,c.unresolved_decisions)!=(physical,decisions):raise ValueError('Existing physical closure HOLDs changed.')
    identity=fingerprint(['cfw128-c2e6a-closure/1',sha,parents,_plain(c.cement_inventory),_plain(c.noncement_inventory),c.initial_mud_remaining_bbl,c.ideal_initial_mud_returned_bbl,c.initial_mud_occupancy,c.preserved_placement_holds,c.inventory_evidence,c.capture_completeness,physical,decisions,'FINAL_POST_PULL_TOC_NOT_EVALUATED'])
    if c.projection_identity!=identity:raise ValueError('C2e6a projection differs.')
    inventory=c.cement_inventory+c.noncement_inventory;names=tuple(v.fluid for v in inventory)
    if len(set(names))!=len(names) or set(names)!={v.name for v in t.stages}:raise ValueError('Missing/duplicate closure stage.')
    if tuple(v.name for v in t.stages)!=tuple(n for n in HYDRAULIC_EXECUTION_ORDER if n in names) or 'Displacement Fluid' not in names:raise ValueError('Invalid source stage order/identity.')
    if any(v.fluid not in PLACEMENT_SLURRIES for v in c.cement_inventory) or any(v.fluid in PLACEMENT_SLURRIES for v in c.noncement_inventory):raise ValueError('Cement identities changed.')
    if tuple(v.fluid for v in c.cement_inventory)!=tuple(v.name for v in t.stages if v.name in PLACEMENT_SLURRIES) or tuple(v.fluid for v in c.noncement_inventory)!=tuple(v.name for v in t.stages if v.name not in PLACEMENT_SLURRIES):raise ValueError('Closure stage ordering differs.')
    consumed=[];stageparts=[];tracking_exact=exact
    for stage,ledger,record in zip(t.stages,t.ledgers,r.stages):
        v=next(x for x in inventory if x.fluid==stage.name);_kind(v,'cfw128_c2e6a_post_pull_closure','FluidInventory')
        for name in ('configured_bbl','actually_entered_bbl','injection_bbl','lower_annulus_bbl','upper_pumping_annulus_bbl','ideal_returned_bbl'):_number(getattr(v,name))
        _number(stage.volume_bbl,True);_number(stage.density_pcf,True)
        if type(stage.raw_density) not in (str,int,float) or stage.density_pcf!=require_fluid_density(stage.name,stage.raw_density) or stage.source not in ('fluids_config.params','fluid_data'):raise ValueError('Captured density/source differs.')
        amounts=tuple(math.fsum(o.volume_bbl for o in byfluid[stage.name] if t.path[o.section_index].domain==n) for n in ('injection','lower_annulus','upper_pumping_annulus'))
        if (v.configured_bbl,v.actually_entered_bbl,v.injection_bbl,v.lower_annulus_bbl,v.upper_pumping_annulus_bbl,v.ideal_returned_bbl)!=(stage.volume_bbl,ledger.entered_bbl,*amounts,ledger.ideal_returned_bbl):raise ValueError('Closure stage/compartment/ledger differs.')
        reconciled=_reconcile([v.actually_entered_bbl],[*amounts,v.ideal_returned_bbl])
        if v.fluid in PLACEMENT_SLURRIES:exact &= reconciled
        if _tree((record.volume_bbl,record.density_pcf,record.raw_density,record.raw_entered_volume,record.volume_authority))!=_tree((stage.volume_bbl,stage.density_pcf,stage.raw_density,v.raw_entered_volume,v.volume_authority)):raise ValueError('Effective schedule stage differs.')
        mud=stage.name=='Displacement Fluid'
        if mud:
            if v.volume_authority!='DERIVED_C2E4_INTERNAL_STRING_CAPACITY' or v.raw_entered_volume is not None or stage.volume_bbl!=c.derived_displacement_bbl or type(stage.raw_volume) not in (int,float) or stage.raw_volume!=stage.volume_bbl:raise ValueError('Derived Mud source was replaced.')
            if record.density_source not in ('state.mud_density','well_data.mud_density') or record.record_source!='C2E4':raise ValueError('Mud source authority differs.')
            origin='C2E4'
        else:
            _number(v.raw_entered_volume,True)
            if v.volume_authority!='ENTERED_PHASE_IV' or type(v.raw_entered_volume) is not type(stage.raw_volume) or v.raw_entered_volume!=stage.raw_volume or Fraction(v.raw_entered_volume)!=Fraction(stage.volume_bbl):raise ValueError('Entered stage volume was changed.')
            if record.density_source!=stage.source+'.'+stage.name+'.density' or record.record_source!=stage.source:raise ValueError('Entered source authority differs.')
            origin=stage.source
        stage_id=fingerprint(['cfw128-c2e5-stage/1',stage.name,v.volume_authority,origin,v.raw_entered_volume,stage.volume_bbl,stage.raw_density,stage.density_pcf,record.density_source,parent['derived'] if mud else None])
        if v.stage_source_identity!=stage_id or record.source_identity!=stage_id:raise ValueError('Stage source fingerprint differs.')
        consumed.append((stage.name,stage.source,stage.raw_volume,stage.raw_density))
        if v.fluid in PLACEMENT_SLURRIES:stageparts.append((v.fluid,v.configured_bbl,v.actually_entered_bbl,*amounts,v.ideal_returned_bbl))
    mud=next(v for v in t.stages if v.name=='Displacement Fluid')
    if t.initial_mud_density_pcf!=mud.density_pcf or t.source_identity!=fingerprint(['cfw128-c2e-source/1',g.source_identity,g.projection_identity,sha,s.job,tuple(consumed),mud.raw_density]):raise ValueError('Tracking does not bind the captured effective source.')
    mudparts=tuple((o.section_index,o.inlet_md,o.outlet_md,o.volume_bbl) for o in byfluid['Mud'])
    if (c.initial_mud_remaining_bbl,c.ideal_initial_mud_returned_bbl,c.initial_mud_occupancy)!=(t.mud_remaining_bbl,t.mud_displaced_bbl,mudparts):raise ValueError('Initial Mud ledger differs.')
    complete=all(a.entered_bbl==v.volume_bbl for a,v in zip(t.ledgers,t.stages))
    if c.capture_completeness!=('COMPLETE_CONFIGURED_VOLUME_CAPTURE' if complete else 'HOLD_SCHEDULE_INCOMPLETE'):raise ValueError('Capture completeness differs.')
    holds=c.preserved_placement_holds
    if type(holds) is not tuple or any(type(v) is not str for v in holds):raise ValueError('Malformed placement HOLDs.')
    if not tracking_exact and 'HOLD_VOLUME_RECONCILIATION_PRECISION' not in holds:raise ValueError('Source precision HOLD was removed.')
    if not complete and 'HOLD_SCHEDULE_INCOMPLETE' not in holds:raise ValueError('Schedule HOLD was removed.')
    if complete and Fraction(t.cumulative_injected_bbl)!=total and 'HOLD_TERMINAL_VOLUME_PRECISION_UNPROVEN' not in holds:raise ValueError('Terminal precision HOLD was removed.')
    if not c.cement_inventory and 'HOLD_NO_PLACED_CEMENT' not in holds:raise ValueError('Missing-cement HOLD was removed.')
    if any(v.injection_bbl>0 for v in c.cement_inventory) and 'HOLD_CEMENT_REMAINS_IN_INJECTION' not in holds:raise ValueError('Retained Cement HOLD was removed.')
    expected_evidence='CAPTURED_NOMINAL_LEDGER_RECONCILED' if exact and not any('PRECISION' in x for x in holds) else 'CAPTURED_ROUNDED_WITH_PRESERVED_UNCERTAINTY'
    if c.inventory_evidence!=expected_evidence:raise ValueError('Inventory certainty differs.')
    annular=[];others=[]
    for o in t.occupancy:
        part=t.path[o.section_index]
        if o.fluid not in PLACEMENT_SLURRIES:others.append((o.fluid,o.section_index,o.inlet_md,o.outlet_md,o.volume_bbl))
        elif part.domain!='injection':annular.append((o.fluid,part.domain,o.section_index,min(o.inlet_md,o.outlet_md),max(o.inlet_md,o.outlet_md),o.volume_bbl,part.running_source_rows,part.wall_source_rows))
    annular.sort(key=lambda v:v[3])
    if not annular and 'HOLD_NO_ANNULAR_CEMENT' not in holds:raise ValueError('Annular HOLD was removed.')
    if annular and annular[-1][4]!=s.shoe_md and 'HOLD_CEMENT_NOT_ANCHORED_AT_SHOE' not in holds:raise ValueError('Shoe HOLD was removed.')
    if any(a[4]!=b[3] for a,b in zip(annular,annular[1:])) and 'HOLD_DISCONNECTED_ANNULAR_CEMENT' not in holds:raise ValueError('Cement continuity HOLD was removed.')
    candidate=annular[0][3] if annular and not holds else None
    post='NOT_APPLICABLE' if casing else 'HOLD_POST_PULL_REMAP_UNDEFINED'
    placement=fingerprint(['cfw128-c2e2-placement/1',sha,g.source_identity,g.projection_identity,t.source_identity,t.projection_identity,tuple(stageparts),tuple(annular),tuple(others),candidate,holds,post])
    if parent['placement']!=placement or c.surface_cement_return_present!=any(v.ideal_returned_bbl>0 for v in c.cement_inventory):raise ValueError('Placement source/HOLD association differs.')
    return parent


def _product_bounds(outer,inner,length,volume):
    """Source rounding proof, not an engineering acceptance tolerance.

    The published App _capacity expression has eight binary64 operations,
    counting both squares. gamma_8 times the sum of the bore magnitudes bounds
    error even when squared diameters subtract. The denominator also bounds
    rounding of those source magnitudes. Products/sums are checked in exact
    rational arithmetic. Subnormal/overflow cases are not qualified here.
    """
    cap=_capacity(outer,inner)
    if min(cap,volume)<math.ldexp(1.,-1022):raise ValueError('HOLD_SOURCE_FLOATING_PRECISION_UNPROVEN')
    unit=Fraction(1,2**53);gamma=8*unit/(1-8*unit)
    scale=Fraction(_capacity(outer))+(Fraction(_capacity(inner)) if inner else 0)
    radius=gamma*scale/(1-gamma);a,b=Fraction(cap)-radius,Fraction(cap)+radius
    x,y=_range(volume);length=Fraction(length)
    return min(a*length,x),max(b*length,y)


def _intersect(a,b):
    if max(a[0],b[0])>min(a[1],b[1]):raise ValueError('HOLD_SOURCE_FLOATING_PRECISION_UNPROVEN')


@dataclass(frozen=True,slots=True)
class DryPipeInterval:
    top_md: float
    bottom_md: float
    source_rows: tuple[int,...]
    wall_source_rows: tuple[int,...]
    internal_id_in: float
    outer_od_in: float
    removed_pipe_outer_displacement_bbl: float
    drained_internal_mud_bbl: float
    new_mud_makeup_bbl: float
    independent_steel_volume_bbl: float
    steel_check_residual_bbl: float
    captured_mud_stages: tuple[str,...]


@dataclass(frozen=True,slots=True)
class DryPipeMakeupAudit:
    app_source_sha: str
    geometry_source_identity: str
    geometry_projection_identity: str
    gap_projection_identity: str
    closure_projection_identity: str
    tracking_projection_identity: str
    projection_identity: str
    job: str
    kind: str
    active_lap_md: float
    active_shoe_md: float
    intervals: tuple[DryPipeInterval,...]
    removed_pipe_outer_displacement_bbl: float | None
    drained_internal_mud_bbl: float | None
    new_mud_makeup_bbl: float | None
    independent_steel_volume_bbl: float | None
    original_pumping_displacement_bbl: float
    original_displacement_end_md: float
    preserved_placement_holds: tuple[str,...]
    preserved_closure_holds: tuple[str,...]
    status: Literal['DISABLED_DRY_PIPE_MUD_MAKEUP_AUDIT','NOT_APPLICABLE']
    evidence: Literal['NOMINAL_DRY_PIPE_BALANCE_ONLY']=field(default='NOMINAL_DRY_PIPE_BALANCE_ONLY',init=False)
    physical_remap_status: Literal['HOLD_POST_PULL_FLUID_BOUNDARY_AND_TRANSFER_UNPROVEN']=field(default='HOLD_POST_PULL_FLUID_BOUNDARY_AND_TRANSFER_UNPROVEN',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['NOT_EVALUATED']=field(default='NOT_EVALUATED',init=False)
    final_toc: Literal['NOT_EVALUATED']=field(default='NOT_EVALUATED',init=False)
    terminal_shoe_behavior: Literal['HOLD_25M_TERMINAL_PLACEMENT_BEHAVIOR_UNDEFINED']=field(default='HOLD_25M_TERMINAL_PLACEMENT_BEHAVIOR_UNDEFINED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def audit_dry_pipe_makeup(geometry: object,post_pull_gap: object,closure: object,tracking: object,schedule: object,*,expected_app_source_sha: str) -> DryPipeMakeupAudit:
    """Nominal fully-Mud DP withdrawal only; reject captured non-Mud DP contents.

    App source SHA is externally verified by the caller. Digests check capture
    consistency, never currentness/authenticity. No field pumping or remap law.
    """
    g,b,c,t,r=geometry,post_pull_gap,closure,tracking,schedule;sha=expected_app_source_sha;s=_bind(g,sha)
    for v,module,name in ((b,'cfw128_c2e3_post_pull_gap','PostPullGapAudit'),(c,'cfw128_c2e6a_post_pull_closure','ClosureAudit'),(t,'cfw128_c2e_volume_tracking','TrackingPreview'),(r,'cfw128_c2e5_effective_schedule','EffectiveSchedule')):
        _tree(v);_kind(v,module,name)
        if v.app_source_sha!=sha or v.currentness!='NOT_CURRENTNESS_PROOF':raise ValueError('Mismatched App/source-currentness contract.')
    for v in (b,t,r):
        if (v.geometry_source_identity,v.geometry_projection_identity)!=(g.source_identity,g.projection_identity):raise ValueError('Mismatched source geometry.')
    if b.hydraulics!='NOT_EVALUATED' or b.final_toc!='NOT_EVALUATED' or t.hydraulics!='HYDRAULICS_NOT_EVALUATED' or r.hydraulics!='HYDRAULICS_NOT_EVALUATED':raise ValueError('Inherited release HOLD missing.')
    if len(g.injection)!=len(s.active_sections):raise ValueError('Missing active source sections.')
    cursor=0.;body={'casing':'Casing','liner':'Liner Shoe','tieback':'Tie Back Liner Shoe'}[s.kind]
    for v in s.active_sections:
        for x in (v.top_md,v.bottom_md,v.id_in,v.od_in):_number(x)
        _rows(v.source_rows)
        if v.top_md!=cursor or not v.top_md<v.bottom_md<=s.shoe_md or not 0<v.id_in<v.od_in or v.top_md<s.string_top_md<v.bottom_md:raise ValueError('Invalid measured pipe path/wall.')
        if v.description!=('Drill Pipes' if v.bottom_md<=s.string_top_md else body):raise ValueError('Wrong active source role.')
        cursor=v.bottom_md
    if cursor!=s.shoe_md:raise ValueError('Active path cannot extend into historical receiver.')
    _nominal(g,s);_gap(g,b,s,sha);byfluid,exact=_tracking(g,t,s);_closure(g,b,c,t,r,s,sha,byfluid,exact)
    if c.capture_completeness!='COMPLETE_CONFIGURED_VOLUME_CAPTURE':raise ValueError('HOLD_SOURCE_PUMPING_NOT_COMPLETE')
    intervals=[];all_bounds=[]
    for pump,part in zip(g.upper_pumping_annulus,b.slices):
        run=next(v for v in s.active_sections if v.top_md<=part.top_md and part.bottom_md<=v.bottom_md)
        if run.description!='Drill Pipes' or part.running_source_rows!=run.source_rows or part.drill_pipe_od_in!=run.od_in:raise ValueError('Only actual upper DP is withdrawable.')
        length=part.bottom_md-part.top_md;cap=_capacity(run.id_in);drained=length*cap;outer=part.capacity_gap_bbl;makeup=outer-drained
        steelcap=_capacity(run.od_in,run.id_in);steel=length*steelcap
        for v in (drained,outer,makeup,steel):_number(v,True)
        post_bounds=_product_bounds(part.host_id_in,0.,length,part.post_pull_volume_bbl)
        pump_bounds=_product_bounds(part.host_id_in,run.od_in,length,part.pumping_volume_bbl)
        outer_bounds=(post_bounds[0]-pump_bounds[1],post_bounds[1]-pump_bounds[0])
        odcap=_capacity(run.od_in);_intersect(outer_bounds,_product_bounds(run.od_in,0.,length,odcap*length))
        inner_bounds=_product_bounds(run.id_in,0.,length,drained);makeup_bounds=(outer_bounds[0]-inner_bounds[1],outer_bounds[1]-inner_bounds[0])
        _intersect(makeup_bounds,_product_bounds(run.od_in,run.id_in,length,steel));all_bounds.append(makeup_bounds)
        _reconcile([outer],[drained,makeup])
        # Only check supplied occupancy; do not derive or move a fluid front.
        groups=[];labels=[]
        for index,path in enumerate(t.path):
            if path.domain!='injection' or path.outlet_md<=part.top_md or path.inlet_md>=part.bottom_md:continue
            for occupied in t.occupancy:
                if occupied.section_index!=index:continue
                left=max(part.top_md,occupied.inlet_md);right=min(part.bottom_md,occupied.outlet_md)
                if right<=left:continue
                if occupied.fluid not in ('Mud','Displacement Fluid'):raise ValueError('HOLD_DP_INTERNAL_MUD_NOT_PROVEN: captured non-Mud must not be drained as Mud.')
                groups.append((left,right));labels.append(occupied.fluid)
        groups.sort();end=part.top_md
        for left,right in groups:
            if left!=end:raise ValueError('Unproved/overlapping DP Mud occupancy.')
            end=right
        if end!=part.bottom_md:raise ValueError('Unproved complete DP Mud occupancy.')
        intervals.append(DryPipeInterval(part.top_md,part.bottom_md,run.source_rows,part.wall_source_rows,run.id_in,run.od_in,outer,drained,makeup,steel,makeup-steel,tuple(dict.fromkeys(labels))))
    if s.kind=='casing':totals=(None,None,None,None);status='NOT_APPLICABLE'
    else:
        totals=tuple(sum(getattr(v,name) for v in intervals) for name in ('removed_pipe_outer_displacement_bbl','drained_internal_mud_bbl','new_mud_makeup_bbl','independent_steel_volume_bbl'))
        if totals[0]!=b.capacity_gap_bbl:raise ValueError('Upper OD occupancy was double-counted or lost.')
        for v in totals:_number(v)
        _reconcile([totals[0]],[totals[1],totals[2]])
        _intersect((sum((v[0] for v in all_bounds),Fraction()),sum((v[1] for v in all_bounds),Fraction())),_range(totals[3]))
        status='DISABLED_DRY_PIPE_MUD_MAKEUP_AUDIT'
    identity=fingerprint(['cfw128-c2e6b-dry-pipe/1',sha,g.source_identity,g.projection_identity,b.projection_identity,c.projection_identity,t.projection_identity,s.job,s.kind,s.string_top_md,s.shoe_md,_plain(intervals),totals,c.derived_displacement_bbl,c.displacement_end_md,c.preserved_placement_holds,c.unresolved_decisions,status,'NOMINAL_DRY_PIPE_BALANCE_ONLY','HOLD_POST_PULL_FLUID_BOUNDARY_AND_TRANSFER_UNPROVEN','NOT_CURRENTNESS_PROOF'])
    return DryPipeMakeupAudit(sha,g.source_identity,g.projection_identity,b.projection_identity,c.projection_identity,t.projection_identity,identity,s.job,s.kind,s.string_top_md,s.shoe_md,tuple(intervals),*totals,c.derived_displacement_bbl,c.displacement_end_md,c.preserved_placement_holds,c.unresolved_decisions,status)
