"""Owner Rev3 disabled, lossless, order-preserving static reconstruction.

Reads fresh canonical composition and validated native EOD/port observations.
Consumes Gate7 placement, C2e3 geometry, existing native Channel coordinates
and App _capacity; no transport replay, solver, mixing or withdrawal transient.
Owns conditional inventory reconciliation only. Writes/persistence/App/Word/
renderer: none. Historical C2e6a/b nominal occupancy is not native evidence.
"""
from dataclasses import dataclass, field, fields
from fractions import Fraction
import math

from DOC58_SI_CANDIDATE_03_TF2R_ER03 import GeometrySpec, PipeSection, AnnSection
from cement_chart_model import _capacity
from materials_db import PLACEMENT_SLURRIES
from project_state import fingerprint
from cfw128_integration_abi import compose_nominal_tracking
from cfw128_er03_numeric_adapter import NumericEvidence, _primitive
from cfw128_c2e7_native_placement import assess_native_placement, _map_static
from cfw128_c2e3_post_pull_gap import audit_post_pull_gap

SCHEMA='CFW128_REV3_POST_PULL_NOMINAL_V1'


@dataclass(frozen=True,slots=True)
class PostPullConditions:
    """Explicit model conditions, never acquired field facts or App state."""
    surface_connected: bool
    lossless: bool
    full_dp_mud_recovery: bool

    def __post_init__(self):
        if any(type(getattr(self,f.name)) is not bool for f in fields(self)):
            raise TypeError('Explicit boolean nominal conditions required.')


@dataclass(frozen=True,slots=True)
class PostPullReview:
    app_source_sha: str
    composition_identity: str
    numeric_identity: str
    placement_identity: str
    basis: str
    conditions: PostPullConditions
    # Full native (fluid, initial, injection, mouth, head, pipe, annulus, residual).
    eod_balances: tuple
    # fluid, role, top MD, bottom MD, bbl, exact bbl ratio, terminal-25m flag.
    pipe_bands: tuple
    # top, bottom, native DP Mud, nominal ID, OD, metal, OD-ID-metal residual.
    withdrawn_sections: tuple
    # Native EOD identities available for idealized internal return, not an
    # observed withdrawal/port flow and never a second pumped injection.
    returned_dp_mud: tuple
    additional_mud_bbl: float | None
    # fluid, origin, top MD, bottom MD, bbl, exact ratio; deepest first.
    annular_bands: tuple
    # fluid, EOD pipe, EOD annulus, external makeup, after pipe, after annulus,
    # exact algebraic inventory residual (returned DP is an internal transfer).
    post_pull_balances: tuple
    # Native/canonical basis differences are observations, never corrections.
    capacity_residuals: tuple
    achieved_cement_top_md: float | None
    region: str
    surface_status: str
    prior_static_candidate_md: float | None
    case_holds: tuple[str,...]
    holds: tuple[str,...]
    projection_identity: str
    schema: str=field(default=SCHEMA,init=False)
    model: str=field(default='OWNER_REV3_LOSSLESS_NOMINAL_RECONCILIATION',init=False)
    evidence_class: str=field(default='SYNTHETIC_TEST_ONLY',init=False)
    status: str=field(default='DISABLED_NOMINAL_POST_PULL_REVIEW_HOLD',init=False)
    currentness: str=field(default='NOT_CURRENTNESS_PROOF',init=False)
    qualification: str=field(default='NOT_GRANTED',init=False)
    final_field_toc: str=field(default='FINAL_FIELD_TOC_NOT_EVALUATED',init=False)
    enabled: bool=field(default=False,init=False)
    ready_to_run: bool=field(default=False,init=False)
    hb_admissible: bool=field(default=False,init=False)
    hydraulic_admissible: bool=field(default=False,init=False)
    chart_admissible: bool=field(default=False,init=False)
    scientifically_qualified: bool=field(default=False,init=False)

    def __post_init__(self):
        _primitive(self)
        if type(self.conditions) is not PostPullConditions:
            raise TypeError('Typed nominal conditions required.')
        self.conditions.__post_init__()
        for f in fields(self):
            if not f.init and getattr(self,f.name)!=f.default:
                raise ValueError('Disabled model declarations must be preserved.')
        values=tuple(getattr(self,f.name) for f in fields(self) if f.init and f.name!='projection_identity')
        if self.projection_identity!=fingerprint([SCHEMA,_primitive(values)]):
            raise ValueError('Post-pull review identity differs.')


def _sum(tokens,name):
    return sum((Fraction(v) for n,v in tokens if n==name),Fraction())


def _native_channels(c):
    """Reuse original measured-section coordinate authority; never simulate."""
    s=c.captured_geometry;g=c.geometry;deep=s.active_sections[-1]
    geo=GeometrySpec(td_m=s.shoe_md,track_depth_m=s.shoe_md,
        hole_id_in=g.lower_annulus[-1].outer_diameter_in,
        pipe_od_in=deep.od_in,pipe_id_in=deep.id_in,
        pipe_sections=[PipeSection(v.top_md,v.bottom_md,v.id_in,v.od_in) for v in s.active_sections],
        ann_sections=[AnnSection(v.top_md,v.bottom_md,v.outer_diameter_in,v.inner_diameter_in) for v in g.pumping_return])
    return geo.chan_pipe,geo.chan_ann


def _native_bands(tokens,channel,lap,terminal,boundaries=()):
    """Intersect captured tokens with the native Channel's actual windows.

    No stage replay or assumed terminal Cement. Unlocated roundoff is reported
    separately; no token is enlarged to make a column reach a desired depth.
    """
    rows=[];cursor=Fraction()
    for name,volume in tokens:
        end=cursor+Fraction(volume)
        for sec,lo,hi in channel._windows(True):
            cap=Fraction(sec.cap_bbl_per_m);cuts={Fraction(lo),Fraction(hi)}
            for cut in (terminal,*boundaries):
                if sec.z_top<cut<sec.z_bot:
                    point=Fraction(lo)+cap*(Fraction(sec.z_bot)-Fraction(cut))
                    if Fraction(lo)<point<Fraction(hi):cuts.add(point)
            cuts=sorted(cuts)
            for left,right in zip(cuts,cuts[1:]):
                a=max(cursor,left);b=min(end,right)
                if b<=a:continue
                # The native Channel's cumulative windows are rounded floats.
                # An exact window endpoint denotes its measured section end;
                # retain that source coordinate instead of a negative ULP MD.
                bottom=Fraction(sec.z_bot) if a==Fraction(lo) else Fraction(sec.z_bot)-(a-Fraction(lo))/cap
                top=Fraction(sec.z_top) if b==Fraction(hi) else Fraction(sec.z_bot)-(b-Fraction(lo))/cap
                value=b-a;role='WITHDRAWABLE_DP' if sec.z_bot<=lap else 'INSTALLED_BODY'
                rows.append((name,role,float(top),float(bottom),float(value),
                             (value.numerator,value.denominator),top>=Fraction(terminal)))
        cursor=end
    return tuple(rows)


def assess_post_pull(state: dict,numeric: NumericEvidence,*,expected_app_source_sha: str,
                     conditions: PostPullConditions) -> PostPullReview:
    """Conditional nominal reconstruction, never a field-final TOC decision.

    Surface connection is not a claim that the pumped fluid front is at surface.
    Returned DP Mud and external Mud are added at the model's top boundary;
    actual withdrawal/return order and isolation remain unqualified HOLDs.
    This order-preserving bottom-anchored construction is an idealized static
    candidate, never a simulation or observation of that withdrawal operation.
    """
    if type(conditions) is not PostPullConditions:raise TypeError('Explicit nominal conditions required.')
    conditions.__post_init__()
    c=compose_nominal_tracking(state,expected_app_source_sha=expected_app_source_sha)
    a=assess_native_placement(state,numeric,expected_app_source_sha=expected_app_source_sha,composition=c)
    s=c.captured_geometry;g=c.geometry;reasons=[];capacity=[]
    pipe=sections=returned=bands=balances=();additional=None;top=None;region='UNDEFINED'
    surface='NOT_APPLICABLE';o=numeric.native_observation
    if not conditions.surface_connected:reasons.append('HOLD_CONNECTED_RETURN_NOT_PROVED')
    if not conditions.lossless:reasons.append('HOLD_LOSS_OR_UNRECORDED_RETURN')
    if o is None:reasons.append('HOLD_NATIVE_EOD_ABSENT')
    else:
        initial,intervals,eod,tail=o.payload[1:];cp,ca=_native_channels(c)
        pipe=_native_bands(eod[1],cp,0. if s.kind=='casing' else s.string_top_md,c.displacement.end_md,
            tuple(v.bottom_md for v in g.upper_pumping_annulus))
        if eod[3]!=0.:reasons.append('HOLD_PIPE_UNDERFILLED')
        for col,begin,label in ((eod[1],initial[1],'PIPE'),(eod[2],initial[2],'ANNULUS')):
            residual=math.fsum(v for n,v in begin)-math.fsum(v for n,v in col)
            capacity.append(('NATIVE_'+label+'_VOID_BBL',residual))
            # Existing Gate6C/Gate7 audit bound, not a geometry tolerance.
            if not math.isclose(residual,0.,rel_tol=0.,abs_tol=1e-9):reasons.append('HOLD_NATIVE_'+label+'_OCCUPANCY')
        names=tuple(row[0] for row in a.fluid_balances)
        for name in names:
            value=_sum(eod[1],name)-sum((Fraction(*r[5]) for r in pipe if r[0]==name),Fraction())
            capacity.append(('PIPE_COORDINATE_RESIDUAL:'+name,float(value)))
            if abs(value)>Fraction(1e-9):reasons.append('HOLD_PIPE_COORDINATES_UNRESOLVED')
        if s.kind=='casing':
            # Native channel/ports prove the simulated surface condition, not
            # the different canonical conversion nor a field plug-bump event.
            native=_native_bands(eod[2],ca,0.,s.shoe_md)
            bands=tuple((r[0],'NATIVE_EOD_ANNULUS',r[2],r[3],r[4],r[5]) for r in native)
            cement=tuple(r for r in bands if r[0] in PLACEMENT_SLURRIES)
            if cement:top=min(r[2] for r in cement)
            full=all(n in PLACEMENT_SLURRIES for n,v in eod[2])
            # The numerical bookkeeping bound cannot establish surface fill.
            # Require exact captured native inventory and actual mouth support;
            # retain a HOLD even for a tiny deficit, without adjusting volume.
            exact=sum((Fraction(v) for n,v in eod[2]),Fraction())==sum((Fraction(v) for n,v in initial[2]),Fraction())
            supported=not reasons and full and exact and a.annular_mouth_cement_bbl>0.
            surface='CEMENT_TO_SURFACE_PROVED_IN_NATIVE_MODEL' if supported else 'HOLD_SURFACE_NOT_PROVED'
            if supported:top=0.;region='SURFACE'
            elif cement:region='CSG_NATIVE_ACHIEVED_TOP'
            if not supported:reasons.append('HOLD_SURFACE_NOT_PROVED')
            if full and not exact:reasons.append('HOLD_NATIVE_SURFACE_CAPACITY_NOT_EXACT')
            if not cement:reasons.append('NO_NATIVE_ANNULAR_CEMENT')
            if a.case_holds:reasons.extend(a.case_holds)
        else:
            gap=audit_post_pull_gap(g,expected_app_source_sha=expected_app_source_sha)
            if c.displacement.end_md<s.string_top_md:reasons.append('HOLD_TERMINAL_INTERVAL_CROSSES_WITHDRAWABLE_DP')
            if not conditions.full_dp_mud_recovery:reasons.append('HOLD_DP_MUD_RECOVERY_UNPROVED')
            dp=tuple(r for r in pipe if r[1]=='WITHDRAWABLE_DP')
            if any(r[0] not in ('Mud','Displacement Fluid') for r in dp):reasons.append('HOLD_DP_CONTAINS_NONMUD')
            if len({r[0] for r in dp})>1:reasons.append('HOLD_RETURNED_MUD_IDENTITY_ORDER_UNPROVED')
            details=[]
            for part in gap.slices:
                run=next(v for v in s.active_sections if v.top_md<=part.top_md and part.bottom_md<=v.bottom_md)
                if run.description!='Drill Pipes':reasons.append('HOLD_WITHDRAWABLE_ROLE_UNPROVED')
                length=part.bottom_md-part.top_md
                internal=_capacity(run.id_in)*length;outer=_capacity(run.od_in)*length
                metal=_capacity(run.od_in,run.id_in)*length
                # Bands already split at every measured upper-wall boundary;
                # use their interior to assign the paired source interval.
                actual=math.fsum(r[4] for r in dp if part.top_md<=(r[2]+r[3])/2.<part.bottom_md)
                native_capacity=cp.volume_above(part.bottom_md)-cp.volume_above(part.top_md)
                if not math.isclose(actual,native_capacity,rel_tol=0.,abs_tol=1e-9):reasons.append('HOLD_DP_OCCUPANCY_INCOMPLETE')
                details.append((part.top_md,part.bottom_md,actual,internal,outer,metal,math.fsum((outer,-internal,-metal))))
            sections=tuple(details)
            if not reasons:
                returned=tuple((r[0],r[4]) for r in dp)
                additional=math.fsum(r[5] for r in sections)
                chunks=tuple((('NATIVE_EOD_ANNULUS',n),v) for n,v in eod[2])+tuple((('RETURNED_DP_INTERNAL',n),v) for n,v in returned)
                if additional:chunks+=((('EXTERNAL_MAKEUP_MUD','Displacement Fluid'),additional),)
                mapped,ceiling,error=_map_static(chunks,g.post_pull_return,s.shoe_md)
                if error:reasons.append('HOLD_'+error)
                else:
                    bands=tuple((key[1],key[0],t,b,v,ratio) for key,t,b,v,ratio in mapped)
                    cement=tuple(r for r in bands if r[0] in PLACEMENT_SLURRIES)
                    if cement:
                        top=min(r[2] for r in cement)
                        region='SURFACE' if top==0. else 'AT_LAP' if top==s.string_top_md else 'BELOW_LAP' if top>s.string_top_md else 'ABOVE_LAP'
                    else:region='NO_ANNULAR_CEMENT';reasons.append('NO_NATIVE_ANNULAR_CEMENT')
                    target=sum((Fraction(_capacity(v.outer_diameter_in,v.inner_diameter_in))*Fraction(v.bottom_md-v.top_md) for v in g.post_pull_return),Fraction())
                    observed=sum((Fraction(v) for key,v in chunks),Fraction())
                    capacity.append(('POST_PULL_CANONICAL_UNFILLED_BBL',float(target-observed)))
                    if target!=observed:reasons.append('HOLD_NATIVE_CANONICAL_VOLUME_BASIS')
                    rows=[]
                    for name in names:
                        before_pipe=_sum(eod[1],name);ann=_sum(eod[2],name);transfer=_sum(returned,name)
                        makeup=Fraction(additional) if name=='Displacement Fluid' else Fraction()
                        after_pipe=before_pipe-transfer
                        after_ann=sum((Fraction(*r[5]) for r in bands if r[0]==name),Fraction())
                        residual=before_pipe+ann+makeup-after_pipe-after_ann
                        rows.append((name,float(before_pipe),float(ann),float(makeup),float(after_pipe),float(after_ann),float(residual)))
                    balances=tuple(rows)
    science=('CASING_SURFACE_PROOF_SYNTHETIC_ONLY',) if s.kind=='casing' else (
        'POST_PULL_IDEALIZED_STATIC_CANDIDATE','WITHDRAWAL_RETURN_ORDER_NOT_OBSERVED',
        'ISOLATION_MIXING_SWABBING_NOT_QUALIFIED')
    inherited=(*a.holds,*science,'FINAL_FIELD_TOC_NOT_GRANTED')
    holds=tuple(dict.fromkeys((*inherited,*reasons)))
    basis='CASING_NATIVE_PUMP_END_NO_DP_PULL' if s.kind=='casing' else 'POST_PULL_IDEALIZED_STATIC_CANDIDATE'
    values=(expected_app_source_sha,c.projection_identity,numeric.projection_identity,a.projection_identity,basis,conditions,
        a.fluid_balances,pipe,sections,returned,additional,bands,balances,tuple(capacity),top,region,surface,
        a.static_candidate_md,tuple(dict.fromkeys(reasons)),holds)
    return PostPullReview(*values,fingerprint([SCHEMA,_primitive(values)]))


def validate_post_pull_review(state,numeric,review,*,expected_app_source_sha,conditions):
    """Fresh recomposition rejects re-signed, stale or cross-source diagnostics.

    Unkeyed consistency IDs never authenticate an unseen project or field data.
    """
    if type(review) is not PostPullReview:raise TypeError('Typed post-pull review required.')
    review.__post_init__()
    fresh=assess_post_pull(state,numeric,expected_app_source_sha=expected_app_source_sha,conditions=conditions)
    if _primitive(review)!=_primitive(fresh):raise ValueError('Post-pull review differs from fresh native/source evidence.')
