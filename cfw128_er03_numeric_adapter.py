"""Isolated synthetic ER03 numerical ABI, disabled for every App/release lane.

Reads: fresh Gate2 composition, reviewed seven-RPM intakes, explicit test options.
Writes/schema/UI/persistence/Word: none. Frozen engines and HB math are unchanged.
Owns typed packaging/provenance only, not geometry, transport or pressure laws.
"""
from copy import deepcopy
from dataclasses import dataclass, field, fields
from fractions import Fraction
from typing import Literal
import math

import DOC58_SI_CANDIDATE_03_TF2R_ER03 as vertical
import DOC58_G2D1_DIR_SCRATCH_01_ER03 as directional
import cfw128_er03_event_aligned_vertical as event_vertical
import cfw128_er03_event_aligned_directional as event_directional
from cfw128_integration_abi import compose_nominal_tracking, CompositionReceipt
from cfw128_hb_intake import snapshot_lab_intake
from cfw128_hb03t_frozen import fit_full_hb, to_engine_field, InstrumentConfig
from engineering_tools import require_positive_pump_rate
from project_state import fingerprint

VERTICAL_SHA256='79d1a76962c706c305cf9a44ee58778d8ee2ca4231fd02f1a6d52f5b5f231e5f'
DIRECTIONAL_SHA256='2cd8896069327ba96fef4f22038bf70538dcc06b37e966b8bb58ad36ac39bd61'
EVENT_SHA256=('1bde2f810055479bba424bacb8b65549e27465ccc28fd9863c355f283de76485', '7bb5596bb7d78d1e7e20c42d9534c5648126c6b417426d8a3f99978911370976')
HB_SHA256='e62678f87867a1b34261a31114e6c692384f0f753c7cbcc92510dd8a5171194f'


@dataclass(frozen=True,slots=True)
class NumericBoundary:
    evidence_class: str
    back_pressure_psi: float
    bhsp_target_psi: float | None
    surface_line_kpsi_at_8bpm: float
    float_equipment: bool
    dt_min: float
    tail_cap_min: float
    shutin_ramp_min: float
    pressure_datum: str
    bhsp_semantics: str
    instrument_declaration: str
    gel_pa_by_fluid: tuple[tuple[str,float],...]


@dataclass(frozen=True,slots=True)
class FluidProof:
    name: str
    intake_identity: str
    raw_readings: tuple[tuple[int,str | int | float],...]
    tau_y_pa: float
    tau_y_field_lbf_100ft2: float
    k_pa_s_n: float
    n_dimensionless: float
    density_ppg: float
    gel_pa: float
    instrument_provenance: Literal['UNVERIFIED']=field(default='UNVERIFIED',init=False)


@dataclass(frozen=True,slots=True)
class NumericEvidence:
    app_source_sha: str
    composition_projection_identity: str
    source_identity: str
    projection_identity: str
    status: str
    holds: tuple[str,...]
    engine: str
    pressure_station_md: float
    stages: tuple[tuple[str,str,float,float,float],...]
    fluids: tuple[FluidProof,...]
    engine_injection_capacity_bbl: float | None
    app_nominal_injection_capacity_bbl: float
    time_min: tuple[float,...]=()
    whp_kpsi: tuple[float,...]=()
    pump_kpsi: tuple[float,...]=()
    hydrostatic_kpsi: tuple[float,...]=()
    total_pressure_kpsi: tuple[float,...]=()
    q_in_bpm: tuple[float,...]=()
    q_out_bpm: tuple[float,...]=()
    events: tuple[tuple[str,float | None],...]=()
    tvd_comparison: tuple[tuple[float,float,float],...]=()
    stage_volume_audit: tuple[tuple[str,float,float,tuple[int,int]],...]=()
    source_hashes: tuple[str,...]=field(default=(VERTICAL_SHA256,DIRECTIONAL_SHA256,HB_SHA256),kw_only=True)
    evidence_class: Literal['SYNTHETIC_TEST_ONLY']=field(default='SYNTHETIC_TEST_ONLY',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    final_post_pull_toc: Literal['NOT_EVALUATED']=field(default='NOT_EVALUATED',init=False)
    qualification: Literal['NOT_GRANTED']=field(default='NOT_GRANTED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def _number(v,positive=False):
    if type(v) not in (int,float):raise ValueError('Explicit real model input required.')
    try:finite=math.isfinite(v)
    except OverflowError:finite=False
    if not finite or v<0 or positive and v==0:
        raise ValueError('Explicit finite nonnegative synthetic model input required.')


def _primitive(v):
    """Exact immutable capture tokens; bools cannot impersonate numbers/flags."""
    if v is None:return ('None',)
    if type(v) in (str,int,bool):return (type(v).__name__,v)
    if type(v) is float:
        if not math.isfinite(v):raise ValueError('Nonfinite supplied capture.')
        return ('float',v.hex())
    if type(v) is tuple:return ('tuple',tuple(_primitive(x) for x in v))
    cls=type(v)
    if (not cls.__module__.startswith('cfw128') or not hasattr(cls,'__dataclass_params__')
            or not cls.__dataclass_params__.frozen or not hasattr(cls,'__slots__')):
        raise TypeError('Published frozen primitive capture required.')
    values=[]
    for f in fields(v):
        value=getattr(v,f.name)
        if f.name in ('enabled','ready_to_run','hb_admissible','hydraulic_admissible','chart_admissible','scientifically_qualified') and value is not False:
            raise ValueError('Captured release gates must be literal False.')
        values.append((f.name,_primitive(value)))
    return (cls.__module__,cls.__name__,tuple(values))


def run_numeric_test_case(state: dict, *, expected_app_source_sha: str, boundary: NumericBoundary,
                          engine: str='vertical', stepping: str='frozen', composition: CompositionReceipt | None=None) -> NumericEvidence:
    """Run original simulate only for admitted, explicitly synthetic inputs.

    PSIA conversion/field pressure qualification is unsupported. BHSP is a total
    bottom target in the same declared surface reference, never an increment.
    Nonvertical App TVD cannot be silently replaced by ER03 interpolation.
    """
    if type(boundary) is not NumericBoundary or type(state) is not dict:raise TypeError('Typed synthetic boundary/project required.')
    if any(type(getattr(boundary,n)) is not str for n in ('evidence_class','pressure_datum','bhsp_semantics','instrument_declaration')):
        raise TypeError('Literal string model declarations required.')
    if (boundary.evidence_class!='SYNTHETIC_TEST_ONLY' or boundary.pressure_datum!='SURFACE_REFERENCE_PSI'
            or boundary.bhsp_semantics!='TARGET_NOT_INCREMENT'
            or boundary.instrument_declaration!='FANN35_R1B1_SPRING1_SOFTWARE_CONVENTION_ONLY'):
        raise ValueError('Unqualified pressure/instrument/authorization declaration.')
    for name in ('back_pressure_psi','surface_line_kpsi_at_8bpm','dt_min','tail_cap_min','shutin_ramp_min'):
        _number(getattr(boundary,name),positive=name in ('dt_min','shutin_ramp_min'))
    if boundary.bhsp_target_psi is not None:_number(boundary.bhsp_target_psi)
    if type(boundary.float_equipment) is not bool or type(engine) is not str or engine not in ('vertical','directional'):raise ValueError('Unknown engine/model option.')
    if type(stepping) is not str or stepping not in ('frozen','event_aligned_test_only'):
        raise ValueError('Explicit frozen or event_aligned_test_only stepping required.')
    v,d=(vertical,directional) if stepping=='frozen' else (event_vertical,event_directional)
    source_hashes=(VERTICAL_SHA256,DIRECTIONAL_SHA256,HB_SHA256)+(EVENT_SHA256 if stepping!='frozen' else ())
    engine_label=engine if stepping=='frozen' else 'event_aligned_'+engine
    source=deepcopy(state)
    fresh=compose_nominal_tracking(source,expected_app_source_sha=expected_app_source_sha)
    if composition is not None and (type(composition) is not CompositionReceipt or _primitive(composition)!=_primitive(fresh)):
        raise ValueError('Receipt differs from freshly supplied project source.')
    c=fresh;g=c.geometry;s=c.captured_geometry;sha=expected_app_source_sha
    gel_items=boundary.gel_pa_by_fluid
    if type(gel_items) is not tuple or any(type(v) is not tuple or len(v)!=2 or type(v[0]) is not str for v in gel_items):raise ValueError('Explicit synthetic gel inputs required.')
    for name,value in gel_items:_number(value)
    gels=dict(gel_items)
    if len(gels)!=len(gel_items) or set(gels)!={'Mud',*(v.name for v in c.schedule.stages)}:raise ValueError('One explicit gel strength per selected/initial fluid required.')
    options=tuple(getattr(boundary,f.name) for f in fields(boundary))
    base=fingerprint(['cfw128-gate3-input/1',sha,c.projection_identity,options,engine,VERTICAL_SHA256,DIRECTIONAL_SHA256,HB_SHA256])
    if stepping!='frozen':base=fingerprint(['cfw128-gate4b-event-input/1',base,source_hashes])
    holds=('PHYSICAL_INSTRUMENT_UNVERIFIED','FIELD_PRESSURE_DATUM_NOT_CERTIFIED','FINAL_POST_PULL_TOC_NOT_EVALUATED',
           'INV014_FAIL_WITH_OWNER_EXCEPTION','DOWNSTREAM_PLACEMENT_AND_CLOSURE_NOT_COMPOSED')
    if stepping!='frozen':holds=(*holds,'EVENT_ALIGNED_TEST_ONLY','BHSP_AND_DIRECTIONAL_SEMANTICS_NOT_QUALIFIED')
    compare=();lab_bindings=[]
    def held(reason):
        held_source=fingerprint(['cfw128-gate3-held-source/1',base,tuple(lab_bindings)])
        identity=fingerprint(['cfw128-gate3-hold/1',held_source,reason,compare])
        return NumericEvidence(sha,c.projection_identity,held_source,identity,'HOLD',(*holds,reason),engine_label,s.shoe_md,(),(),None,g.nominal_injection_bbl,tvd_comparison=compare,source_hashes=source_hashes)
    if source['well_geometry']['type']=='Directional':
        stations=s.survey
        knots=[p for p in s.trajectory if p.md in tuple(v.md for v in stations)]
        survey=d.Survey([p.md for p in knots],[p.tvd for p in knots],inc=[p.deviation_deg for p in stations],azi=[p.azimuth_deg for p in stations],source='captured App canonical survey')
        # Fresh App query captures supply the actual partial-inclination integral.
        queries=tuple((a.md+b.md)/2 for a,b in zip(stations,stations[1:]))
        interior=compose_nominal_tracking(source,expected_app_source_sha=sha,query_md=queries)
        actual={p.md:p.tvd for p in interior.captured_geometry.trajectory}
        compare=tuple((md,actual[md],survey.tvd_at(md)) for md in queries)
        if not survey.identity:return held('DIRECTIONAL_INTERIOR_TVD_CONVENTION_HOLD')
        if engine=='vertical':return held('DIRECTIONAL_SOURCE_REQUIRES_DIRECTIONAL_ENGINE')
    elif engine=='directional':
        survey=d.Survey.vertical(s.shoe_md)
    stages=[];fluids={};proofs=[];params=source['fluids_config'].get('params',{});old=source.get('fluid_data',{})
    for stage in c.schedule.stages:
        row=params[stage.name] if stage.name in params else old.get(stage.name)
        if type(row) is not dict or type(row.get('material_name')) is not str or not row['material_name'].strip():
            return held('MATERIAL_SOURCE_MISSING:'+stage.name)
        rate_raw=row.get('pump_rate')
        if type(rate_raw) not in (int,float,str) or type(rate_raw) is float and not math.isfinite(rate_raw):return held('RATE_SOURCE_INVALID:'+stage.name)
        try:rate=require_positive_pump_rate(rate_raw)
        except (ValueError,TypeError,OverflowError):return held('RATE_SOURCE_INVALID:'+stage.name)
        intake=snapshot_lab_intake(source,stage.name,app_source_sha=sha)
        lab_bindings.append((intake.source_identity,intake.request_identity,intake.status))
        if intake.status!='CAPTURED_FOR_FUTURE_REVIEW':return held('LAB_SOURCE_HOLD:'+stage.name+':'+','.join(intake.reason_codes))
        if intake.instrument_provenance!='UNVERIFIED':raise ValueError('Unsupported instrument provenance claim.')
        fit=fit_full_hb(tuple(v.dial for v in intake.readings),intake.rpm_order,
            instrument=InstrumentConfig('Fann 35','R1B1','1.0'),ramp_type='bhct_down',reviewed=True,
            temperature_condition='BHCT',fluid_id=stage.name,record_id=intake.source_identity)
        if fit.status!='OK' or fit.tau_y_pa is None or fit.tau_y_pa<=0:return held('FULL_HB_NONZERO_YIELD_NOT_PROVED:'+stage.name)
        hb=to_engine_field(fit.tau_y_pa,fit.k_pa_s_n,fit.n_dimensionless)
        fluid=v.Fluid(name=stage.name,rho_ppg=v.pcf_to_ppg(stage.density_pcf),mu_p_cp=hb.mu_p_cp,
            tau_y=hb.tau_y_field_lbf_100ft2,n_pl=hb.n_dimensionless,K_pl=hb.k_pa_s_n,gel_pa=gels[stage.name],frictionless_fluid=False)
        if (fluid.tau_y,fluid.K_pl,fluid.n_pl)!=(hb.tau_y_field_lbf_100ft2,hb.k_pa_s_n,hb.n_dimensionless):raise ValueError('HB transfer differs.')
        fluids[stage.name]=fluid
        proofs.append(FluidProof(stage.name,intake.source_identity,tuple((v.rpm,v.raw) for v in intake.readings),fit.tau_y_pa,fluid.tau_y,fluid.K_pl,fluid.n_pl,fluid.rho_ppg,fluid.gel_pa))
        stages.append(v.FluidStageSpec(fluid_type=stage.name,material_name=row['material_name'],volume_bbl=stage.volume_bbl,density_pcf=stage.density_pcf,rate_bpm=rate))
    # Distinct chronological keys even when initial/injected Mud properties match.
    mud=fluids['Displacement Fluid'];fluids['Mud']=v.Fluid(name='Mud',rho_ppg=mud.rho_ppg,mu_p_cp=0.,tau_y=mud.tau_y,n_pl=mud.n_pl,K_pl=mud.K_pl,gel_pa=gels['Mud'],frictionless_fluid=False)
    active=s.active_sections;ann=g.upper_pumping_annulus+g.lower_annulus;deep=active[-1]
    geo=v.GeometrySpec(td_m=s.shoe_md,track_depth_m=s.shoe_md,hole_id_in=ann[-1].outer_diameter_in,
        pipe_od_in=deep.od_in,pipe_id_in=deep.id_in,depth_unit='m',operation_identity={'casing':'CSG','liner':'LNR','tieback':'TIE BACK'}[s.kind],
        pipe_sections=[v.PipeSection(z_top=p.top_md,z_bot=p.bottom_md,id_in=p.id_in,od_in=p.od_in) for p in active],
        ann_sections=[v.AnnSection(z_top=p.top_md,z_bot=p.bottom_md,do_in=p.outer_diameter_in,di_in=p.inner_diameter_in) for p in ann])
    job=v.JobDesign(geo=geo,fluids=fluids,displacement_fluid='Mud',placement=stages,
        back_pressure_psi=boundary.back_pressure_psi,float_equipment=boundary.float_equipment,
        surface_line_kpsi_at_8bpm=boundary.surface_line_kpsi_at_8bpm,dt_min=boundary.dt_min,tail_cap_min=boundary.tail_cap_min,
        frictionless=False,bhsp_psi=boundary.bhsp_target_psi,shutin_ramp_min=boundary.shutin_ramp_min)
    result=v.simulate(job) if engine=='vertical' else d.simulate(d.attach_survey(job,survey))
    v._er01_audit_channels(result)
    channels=tuple(tuple(float(v) for v in getattr(result,name)) if getattr(result,name) is not None else () for name in ('t','whp','pump','hydro','dyn','q_in','q_out'))
    events=tuple((name,None if getattr(result,name) is None else float(getattr(result,name))) for name in ('t_atcp','t_eod','t_marker','t_freefall_start','t_freefall_end','t_shutin','whp_final_psi','bottom_shutin_psi'))
    if any(value is not None and not math.isfinite(value) for name,value in events):raise ValueError('Nonfinite engine event.')
    encoded=tuple((v.fluid_type,v.material_name,v.volume_bbl,v.density_pcf,v.rate_bpm) for v in stages)
    proof_tokens=tuple(tuple(getattr(v,f.name) for f in fields(v)) for v in proofs)
    numeric_source=fingerprint(['cfw128-gate3-numeric-source/1',base,encoded,proof_tokens,tuple(lab_bindings)])
    status='NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED'
    # Original audit is unchanged. Derivative audit uses actual executed intervals.
    # Requested volumes stay authoritative; never adjust them or their rates.
    audit=[];cursor=0.
    intervals=result.diag.get('event_intervals',()) if stepping!='frozen' else ()
    if stepping!='frozen':
        if not intervals or len(intervals)>len(channels[0]):raise ValueError('Missing event interval audit.')
        for i,(start,end,duration,name,qi,qo,branch) in enumerate(intervals):
            if (start!=channels[0][i] or qi!=channels[5][i] or qo!=channels[6][i]
                    or duration!=end-start or duration<0 or duration>boundary.dt_min
                    or i and start!=intervals[i-1][1]):raise ValueError('Inconsistent executed interval audit.')
    for stage in stages:
        end=cursor+stage.volume_bbl/stage.rate_bpm
        if stepping=='frozen':
            observed=sum((Fraction(q)*Fraction(boundary.dt_min) for t,q in zip(channels[0],channels[5]) if cursor<=t<end),Fraction(0))
            proved=observed==Fraction(stage.volume_bbl)
        else:
            rows=[row for row in intervals if cursor<=row[0]<end]
            if any(row[1]>end or row[3]!=stage.fluid_type or row[4]!=stage.rate_bpm for row in rows):
                raise ValueError('Executed interval crossed its authoritative stage.')
            observed=sum((Fraction(row[4])*Fraction(row[2]) for row in rows),Fraction(0))
            # Bound binary endpoint/product rounding explicitly; no physical
            # volume tolerance or requested rate/volume adjustment is applied.
            error=math.fsum(abs(row[4])*(math.ulp(row[0])+math.ulp(row[1]))+math.ulp(row[4]*row[2]) for row in rows)+math.ulp(stage.volume_bbl)
            proved=abs(observed-Fraction(stage.volume_bbl))<=Fraction(error)
        audit.append((stage.fluid_type,stage.volume_bbl,float(observed),(observed.numerator,observed.denominator)))
        if not proved:
            status='HOLD'
            code='FROZEN_TIMESTEP_STAGE_VOLUME_NOT_PROVED' if stepping=='frozen' else 'EVENT_INTERVAL_STAGE_VOLUME_NOT_PROVED'
            if code not in holds:holds=(*holds,code)
        cursor=end
    if boundary.bhsp_target_psi is not None:
        # A declared target is not evidence that the measured output station
        # reached it. Preserve raw diagnostic series and hold the candidate.
        if result.bottom_shutin_psi is None or result.dyn is None or not math.isclose(float(result.dyn[-1])*1000.,boundary.bhsp_target_psi,rel_tol=1e-12,abs_tol=0.):
            status='HOLD';holds=(*holds,'BHSP_TARGET_STATION_NOT_PROVED')
    audit=tuple(audit)
    identity=fingerprint(['cfw128-gate3-result/1',numeric_source,channels,events,geo.total_pipe_bbl,compare,audit,status,holds])
    return NumericEvidence(sha,c.projection_identity,numeric_source,identity,status,holds,engine_label,s.shoe_md,encoded,tuple(proofs),geo.total_pipe_bbl,g.nominal_injection_bbl,*channels,events,compare,stage_volume_audit=audit,source_hashes=source_hashes)
