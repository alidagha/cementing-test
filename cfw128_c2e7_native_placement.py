"""Held native EOD placement and Owner-approved conserved-volume static candidate.

Reads fresh canonical composition/geometry and Gate6C native observations.
Owns diagnostic static composition only; no transport replay, pressure or TOC
qualification. Writes/persistence/UI/Word: none. Existing capacity, taxonomy,
source intake and numeric validation authorities are consumed unchanged.
"""
from dataclasses import dataclass, field
from fractions import Fraction
import math
from materials_db import PLACEMENT_SLURRIES
from cement_chart_model import _capacity
from engineering_tools import require_positive_pump_rate
from project_state import fingerprint
from cfw128_integration_abi import CompositionReceipt, compose_nominal_tracking
from cfw128_er03_numeric_adapter import NumericEvidence, _primitive, _stage_lab_intake, validate_numeric_evidence


@dataclass(frozen=True,slots=True)
class NativePlacementAssessment:
    app_source_sha: str
    composition_identity: str
    geometry_identity: str
    numeric_identity: str
    projection_identity: str
    kind: str
    basis: str
    pump_end_min: float | None
    # fluid, initial, injected, mouth, head, pipe, annulus, balance residual
    fluid_balances: tuple
    annular_cement_bbl: float | None
    pipe_cement_bbl: float | None
    annular_mouth_cement_bbl: float | None
    pipe_head_cement_bbl: float | None
    pipe_gap_bbl: float | None
    mapped_intervals: tuple
    static_candidate_md: float | None
    region: str
    case_holds: tuple[str,...]
    holds: tuple[str,...]
    evidence_class: str=field(default='SYNTHETIC_TEST_ONLY',init=False)
    status: str=field(default='DISABLED_NATIVE_STATIC_CANDIDATE_HOLD',init=False)
    currentness: str=field(default='NOT_CURRENTNESS_PROOF',init=False)
    qualification: str=field(default='NOT_GRANTED',init=False)
    final_post_pull_toc: str=field(default='FINAL_POST_PULL_TOC_NOT_EVALUATED',init=False)
    enabled: bool=field(default=False,init=False)
    ready_to_run: bool=field(default=False,init=False)
    hb_admissible: bool=field(default=False,init=False)
    hydraulic_admissible: bool=field(default=False,init=False)
    chart_admissible: bool=field(default=False,init=False)
    scientifically_qualified: bool=field(default=False,init=False)

    def __post_init__(self):
        _primitive(self)
        if (self.evidence_class!='SYNTHETIC_TEST_ONLY' or self.status!='DISABLED_NATIVE_STATIC_CANDIDATE_HOLD'
                or self.currentness!='NOT_CURRENTNESS_PROOF' or self.qualification!='NOT_GRANTED'
                or self.final_post_pull_toc!='FINAL_POST_PULL_TOC_NOT_EVALUATED'):
            raise ValueError('Held synthetic placement declarations required.')
        values=(self.kind,self.basis,self.pump_end_min,self.fluid_balances,self.annular_cement_bbl,
                self.pipe_cement_bbl,self.annular_mouth_cement_bbl,self.pipe_head_cement_bbl,
                self.pipe_gap_bbl,self.mapped_intervals,self.static_candidate_md,self.region,self.case_holds,self.holds)
        want=fingerprint(['cfw128-gate7-native-placement/1',self.app_source_sha,self.composition_identity,
                          self.geometry_identity,self.numeric_identity,values])
        if want!=self.projection_identity:raise ValueError('Placement projection identity differs.')


def _map_static(chunks, sections, shoe):
    """Invert only canonical section capacities; exact float-rational accounting.

    No state transport: caller has already proved a bottom-connected Cement band.
    Output volumes carry exact ratios; MD is the representable rounded coordinate.
    """
    parts=tuple(reversed(sections));cursor=0.
    for p in sections:
        if p.top_md!=cursor or p.bottom_md<=p.top_md:raise ValueError('Ambiguous static annular path.')
        cursor=p.bottom_md
    if not parts or cursor!=shoe:raise ValueError('Missing surface-connected annulus.')
    capacities=tuple(Fraction(_capacity(p.outer_diameter_in,p.inner_diameter_in)) for p in parts)
    total=sum((cap*Fraction(p.bottom_md-p.top_md) for p,cap in zip(parts,capacities)),Fraction())
    volume=sum((Fraction(v) for n,v in chunks),Fraction())
    if volume>total:return (),None,'STATIC_CEMENT_EXCEEDS_CANONICAL_CAPACITY'
    rows=[];index=0;depth=Fraction(shoe)
    for name,value in chunks:
        left=Fraction(value)
        while left:
            if index>=len(parts):return (),None,'STATIC_CEMENT_EXCEEDS_CANONICAL_CAPACITY'
            p=parts[index];cap=capacities[index];available=cap*(depth-Fraction(p.top_md))
            take=min(left,available);top=depth-take/cap
            if take<=0 or float(top)==float(depth):return (),None,'STATIC_MD_NOT_REPRESENTABLE'
            rows.append((name,float(top),float(depth),float(take),(take.numerator,take.denominator)))
            left-=take;depth=top
            if take==available:index+=1
    return tuple(rows),float(depth),None


def assess_native_placement(state: dict, numeric: NumericEvidence, *, expected_app_source_sha: str,
                            composition: CompositionReceipt | None=None) -> NativePlacementAssessment:
    """Fresh supplied-source consistency only; never authenticate live field data."""
    fresh=compose_nominal_tracking(state,expected_app_source_sha=expected_app_source_sha)
    if composition is not None and (type(composition) is not CompositionReceipt or _primitive(composition)!=_primitive(fresh)):
        raise ValueError('Supplied composition differs from freshly captured source.')
    c=fresh;g=c.geometry;s=c.captured_geometry
    validate_numeric_evidence(numeric)
    r=numeric
    if (r.app_source_sha!=expected_app_source_sha or r.composition_projection_identity!=c.projection_identity
            or r.pressure_station_md!=s.shoe_md or r.app_nominal_injection_capacity_bbl!=g.nominal_injection_bbl):
        raise ValueError('Native numeric receipt and canonical geometry/source differ.')
    params=state['fluids_config'].get('params',{});old=state.get('fluid_data',{})
    stages=tuple((v.name,(params[v.name] if v.name in params else old[v.name])['material_name'],
                  v.volume_bbl,v.density_pcf,
                  require_positive_pump_rate((params[v.name] if v.name in params else old[v.name])['pump_rate'])) for v in c.schedule.stages)
    if r.stages!=stages or tuple(p.name for p in r.fluids)!=tuple(v.name for v in c.schedule.stages):
        raise ValueError('Native stages differ from supplied effective schedule.')
    for proof in r.fluids:
        intake=_stage_lab_intake(state,proof.name,expected_app_source_sha)
        if (intake.status!='CAPTURED_FOR_FUTURE_REVIEW' or intake.source_identity!=proof.intake_identity
                or proof.raw_readings!=tuple((v.rpm,v.raw) for v in intake.readings)):
            raise ValueError('Native fluid intake differs from supplied current source.')
    basis='CASING_NATIVE_PUMP_END_NO_DP_PULL' if s.kind=='casing' else 'OWNER_STATIC_CONSERVED_ANNULAR_CEMENT_POST_DP_PULL'
    balances=();ann_cement=pipe_cement=mouth_cement=head_cement=gap=None
    rows=();candidate=None;region='UNDEFINED';reasons=[];eod_time=None
    o=r.native_observation
    if o is None:reasons.append('NATIVE_EOD_OBSERVATION_ABSENT')
    else:
        initial,intervals,eod,tail=o.payload[1:];eod_time=eod[0];gap=eod[3]
        names=tuple(sorted({n for col in initial[1:3] for n,v in col}|{v.name for v in r.fluids}))
        def total(tokens,name):return math.fsum(v for n,v in tokens if n==name)
        records=[]
        for name in names:
            a=math.fsum(total(col,name) for col in initial[1:3])
            injected=math.fsum(v for row in intervals if row[1]<=eod_time for n,v in row[5] if n==name)
            ports=tuple(math.fsum(v for row in intervals if row[1]<=eod_time for p,chunks in row[6] if p==port for n,v in chunks if n==name) for port in ('ANNULAR_MOUTH','PIPE_HEAD'))
            pipe=total(eod[1],name);ann=total(eod[2],name)
            residual=math.fsum((a,injected,-ports[0],-ports[1],-pipe,-ann))
            records.append((name,a,injected,*ports,pipe,ann,residual))
        balances=tuple(records)
        ann_cement=math.fsum(x[6] for x in balances if x[0] in PLACEMENT_SLURRIES)
        pipe_cement=math.fsum(x[5] for x in balances if x[0] in PLACEMENT_SLURRIES)
        mouth_cement=math.fsum(x[3] for x in balances if x[0] in PLACEMENT_SLURRIES)
        head_cement=math.fsum(x[4] for x in balances if x[0] in PLACEMENT_SLURRIES)
        # Same native inventory-audit bound already used by Gate6C, not a
        # canonical geometry tolerance or an amount/curve adjustment.
        full=math.isclose(math.fsum(v for n,v in eod[2]),math.fsum(v for n,v in initial[2]),rel_tol=0.,abs_tol=1e-9)
        if ann_cement==0:reasons.append('NO_NATIVE_ANNULAR_CEMENT');region='NO_ANNULAR_CEMENT'
        elif not full:reasons.append('NATIVE_ANNULAR_VOID_OR_INVENTORY_UNRESOLVED')
        elif s.kind=='casing' and all(n in PLACEMENT_SLURRIES for n,v in eod[2]) and (
                sum((Fraction(v) for n,v in eod[2]),Fraction())!=sum((
                    Fraction(_capacity(p.outer_diameter_in,p.inner_diameter_in))*Fraction(p.bottom_md-p.top_md)
                    for p in g.pumping_return),Fraction())):
            # A native surface-filled column is not a licence to absorb the
            # engine/App conversion difference into a fictitious near-surface TOC.
            reasons.append('CASING_SURFACE_VOLUME_CANONICAL_CAPACITY_NOT_PROVED')
        else:
            slugs=eod[2];seen_other=False
            for name,value in slugs:
                if name not in PLACEMENT_SLURRIES:seen_other=True
                elif seen_other:reasons.append('NONCEMENT_BELOW_OR_BETWEEN_CEMENT_SLUGS');break
            if not reasons:
                cement=tuple((n,v) for n,v in slugs if n in PLACEMENT_SLURRIES)
                sections=g.pumping_return if s.kind=='casing' else g.post_pull_return
                rows,candidate,reason=_map_static(cement,sections,s.shoe_md)
                if reason:reasons.append(reason)
                elif candidate==0.:region='SURFACE'
                elif s.kind=='casing':region='CASING_PUMP_END'
                elif candidate==s.string_top_md:region='AT_LAP'
                else:region='BELOW_LAP' if candidate>s.string_top_md else 'ABOVE_LAP'
    science=('NATIVE_SNAPSHOT_NOT_FIELD_METER','WITHIN_STEP_SHOE_CROSSING_NOT_OBSERVED',
             'TERMINAL_25M_PHYSICAL_CONDITION_NOT_CERTIFIED','FINAL_PRODUCTION_TOC_NOT_GRANTED')
    if s.kind=='casing':science+=('CASING_PLUG_BUMP_NOT_PROVED',)
    holds=tuple(dict.fromkeys((*r.holds,*c.holds,*science,*reasons)))
    values=(s.kind,basis,eod_time,balances,ann_cement,pipe_cement,mouth_cement,head_cement,gap,rows,candidate,region,tuple(reasons),holds)
    identity=fingerprint(['cfw128-gate7-native-placement/1',expected_app_source_sha,c.projection_identity,g.projection_identity,r.projection_identity,values])
    return NativePlacementAssessment(expected_app_source_sha,c.projection_identity,g.projection_identity,r.projection_identity,identity,*values)
