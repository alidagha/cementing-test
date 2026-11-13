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
from cfw128_hb_intake import (snapshot_lab_intake, LabIntakeSnapshot, DialReading,
                              _dial, _duplicate_columns, _positional_source)
from cfw128_hb03t_frozen import fit_full_hb, to_engine_field, InstrumentConfig
from engineering_tools import require_positive_pump_rate, validate_lab_rheology, lab_temperature_valid
from centralizer_adapter import _dynamic_fann
from project_state import fingerprint, spacer_lab_payload, phase7_lab_fluids, lab_source_signature, available_fluid_types
from rheology import RPM_ORDER, RHEOLOGY_DATASETS
from fluids_charts_module_v1_4_2 import JobChartsSpec, autoscale_x, autoscale_y, render_three_charts

VERTICAL_SHA256='79d1a76962c706c305cf9a44ee58778d8ee2ca4231fd02f1a6d52f5b5f231e5f'
DIRECTIONAL_SHA256='2cd8896069327ba96fef4f22038bf70538dcc06b37e966b8bb58ad36ac39bd61'
EVENT_SHA256=('35452adbe71c0285baea95ea8e73464cfb47c721ec3a3c39cda7b48ee8230dbf', 'd944f5c5daf1356564f40ac7d2efc3289c0ccdc5a80c8501af2147756df7d24f')
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
class ValidatedStageIntake(LabIntakeSnapshot):
    """Owner-accepted App validation, explicitly NOT an operator review.

    Unknown auxiliary ramp is preserved separately from the approved synthetic
    fit declaration. The frozen intake's bhct_down label is never reused for it.
    """
    dataset: str | None=field(default=None,kw_only=True)
    source_origin: str=field(default='',kw_only=True)
    actual_ramp: str=field(default='UNKNOWN',kw_only=True)
    fit_ramp: Literal['bhct_down']=field(default='bhct_down',init=False)
    temperature_condition: str | None=field(default=None,kw_only=True)
    operator_review: Literal['NOT_ASSERTED']=field(default='NOT_ASSERTED',init=False)
    fit_reviewed: Literal[False]=field(default=False,init=False)
    qualification_hold: str=field(default='',kw_only=True)


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
    source_origin: str='PHASE_VII'
    actual_ramp: str='bhct_down'
    fit_ramp: str='bhct_down'
    temperature_condition: str | None='BHCT'
    operator_review: str='EXISTING_REVIEW_PROVED'
    fit_reviewed: bool=True
    qualification_hold: str='PHYSICAL_INSTRUMENT_UNVERIFIED'
    instrument_provenance: Literal['UNVERIFIED']=field(default='UNVERIFIED',init=False)


@dataclass(frozen=True,slots=True)
class NativePortObservation:
    """Held native simulated tokens, never a meter/currentness/TOC certificate."""
    source_identity: str
    source_hashes: tuple[str,...]
    payload: tuple
    status: Literal['OBSERVATION_ONLY_HOLD']=field(default='OBSERVATION_ONLY_HOLD',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    qualification: Literal['NOT_GRANTED']=field(default='NOT_GRANTED',init=False)
    qout_semantics: Literal['ANNULAR_MOUTH_PLUS_PIPE_HEAD']=field(default='ANNULAR_MOUTH_PLUS_PIPE_HEAD',init=False)
    shoe_crossing_time: Literal['WITHIN_INTERVAL_NOT_OBSERVED']=field(default='WITHIN_INTERVAL_NOT_OBSERVED',init=False)

    @property
    def cumulative_returns(self):
        return tuple((port,tuple((name,math.fsum(v for row in self.payload[2]
            for p,chunks in row[6] if p==port for n,v in chunks if n==name))
            for name in sorted({n for row in self.payload[2] for p,chunks in row[6]
                                if p==port for n,v in chunks})))
            for port in ('ANNULAR_MOUTH','PIPE_HEAD'))


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
    directional_tvd_proof: tuple=field(default=(),kw_only=True)
    trajectory_source: Literal['VERTICAL_SOURCE_V1','APP_DIRECTIONAL_STATION_TVD_V1']=field(default='VERTICAL_SOURCE_V1',kw_only=True)
    native_observation: NativePortObservation | None=field(default=None,kw_only=True)
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

    @property
    def native_observation_status(self):
        return 'ABSENT_UNQUALIFIED' if self.native_observation is None else 'OBSERVATION_ONLY_HOLD'


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


def _stage_lab_intake(state, name, sha):
    """Route only existing source/review authorities; never create a review.

    Cement/Mud retain their byte-compatible intake. Spacer has a reviewed cup.
    Gate 4D accepts App-validated operational sources without inventing review.
    Phase-IX ramp is UNKNOWN; bhct_down is a declared computational assumption.
    """
    if name not in ('Spacer','Pre Flush','Diesel','Spacer Ahead','Spacer Behind'):
        return snapshot_lab_intake(state,name,app_source_sha=sha)
    lab=state.get('lab_qc_params',{});config=state.get('fluids_config',{})
    if type(lab) is not dict or type(config) is not dict or type(config.get('active')) is not list:
        raise ValueError('Canonical lab/fluid source records required.')
    active=config['active'];auxiliary=name in ('Spacer Ahead','Spacer Behind')
    current=name in lab
    qc=lab.get(name);data=qc.get('rheology',{}) if type(qc) is dict else None
    row=data.get('bhct_down') if type(data) is dict else None
    legacy=name=='Pre Flush' and not current
    aux={}
    if auxiliary or legacy:
        config_ix=state.get('centralizer_config',{})
        if type(config_ix) is not dict or type(config_ix.get('aux_rheology',{})) is not dict:raise ValueError('Canonical auxiliary record required.')
        aux=config_ix.get('aux_rheology',{})
    raw=aux.get(name) if (auxiliary or legacy) and type(aux) is dict else row.get('readings') if type(row) is dict else None
    # Only this exact stage's source enters its identity. A present current Lab
    # record excludes historical auxiliary data even when empty or unselected.
    projection={'fluid':name,'selected_count':active.count(name),'origin':'PHASE_IX' if auxiliary or legacy else 'PHASE_VII',
                'qc':None if auxiliary or legacy else qc,'readings':raw}
    if name=='Spacer':
        for key in ('lab_grid_dfs','lab_source_signatures','well_data','fluid_data'):
            if type(state.get(key,{})) is not dict:raise ValueError('Canonical Spacer source records required.')
        if type(config.get('params',{})) is not dict:raise ValueError('Canonical Phase IV parameters required.')
        projection.update(grid=state.get('lab_grid_dfs',{}).get(name),
            stored_source=state.get('lab_source_signatures',{}).get(name),
            composition=state.get('standalone_spacer_config'),
            params=config.get('params',{}).get(name,state.get('fluid_data',{}).get(name)),
            bhct=state.get('well_data',{}).get('bhct',state.get('bhct')),
            bhst=state.get('well_data',{}).get('bhst',state.get('bhst')))
    identity=fingerprint(['cfw128-gate4c-lab/1',_positional_source(projection)])
    def hold(status,code,detail):
        return LabIntakeSnapshot(status,(code,),detail,name,sha,identity,fingerprint([sha,name,identity]))
    if active.count(name)==0:return hold('NOT_APPLICABLE','FLUID_NOT_ACTIVE','An actual selected stage is required.')
    if active.count(name)!=1:return hold('INVALID_INPUT','ACTIVE_FLUIDS_INVALID','Duplicate selection is ambiguous.')
    if name not in available_fluid_types(state):return hold('NOT_APPLICABLE','FLUID_NOT_ELIGIBLE','Existing job/Mud eligibility is required.')
    if not auxiliary and name not in phase7_lab_fluids(state):
        return hold('NOT_APPLICABLE','FLUID_NOT_ELIGIBLE','Current job/Mud selection does not admit this Phase VII fluid.')
    if _duplicate_columns(projection):return hold('INVALID_INPUT','DUPLICATE_SOURCE_COLUMNS','Ambiguous positional values retained in invalid identity.')
    if not auxiliary and not legacy:
        if qc is None:return hold('INCOMPLETE_INPUT','LAB_SOURCE_MISSING','Actual measured Phase VII record is missing.')
        if type(qc) is not dict or type(data) is not dict:return hold('INVALID_INPUT','RHEOLOGY_RECORD_INVALID','Canonical lab/ramp records required.')
        if set(data)-{key for key,label in RHEOLOGY_DATASETS}:return hold('INVALID_INPUT','RHEOLOGY_KEYS_INVALID','Unknown ramp keys are not source authority.')
        if row is None or type(row) is dict and row.get('selected') is False:
            return hold('NOT_SELECTED','BHCT_DOWN_NOT_SELECTED','Current Lab has precedence; other ramps/legacy are not substitutes.')
        if type(row) is not dict or row.get('selected') is not True:
            return hold('INVALID_INPUT','SELECTION_INVALID','Explicit boolean BHCT-down selection required.')
        if set(row)-{'selected','readings','gel_10_sec','gel_10_min'}:
            return hold('INVALID_INPUT','DATASET_KEYS_INVALID','No inferred instrument or foreign dataset metadata.')
    if raw is None:return hold('INCOMPLETE_INPUT','AUXILIARY_SOURCE_MISSING' if auxiliary or legacy else 'RPM_MISSING','No own measured seven-RPM source.')
    if type(raw) is not dict:return hold('INVALID_INPUT','RPM_RECORD_INVALID','Exact canonical RPM mapping required.')
    if any(type(k) is not str or k not in {str(r) for r in RPM_ORDER} for k in raw):
        return hold('INVALID_INPUT','RPM_KEYS_INVALID','Duplicate/colliding/unexpected keys cannot be repaired.')
    if set(raw)!={str(r) for r in RPM_ORDER}:return hold('INCOMPLETE_INPUT','RPM_MISSING','Seven actual dials required.')
    readings=[]
    for rpm in RPM_ORDER:
        value=raw[str(rpm)]
        try:dial,problem=_dial(value)
        except (ValueError,OverflowError):dial,problem=None,'DIAL_INVALID'
        if problem:return hold('INVALID_INPUT',problem,'Finite nonnegative integer dial required without rounding.')
        readings.append(DialReading(rpm,value,type(value).__name__,dial))
    if auxiliary or legacy or name in ('Pre Flush','Diesel'):
        assumed=auxiliary or legacy
        # Validation is reused, never PV/YP reconstruction or a review ceremony.
        if not assumed and set(qc)-{'rheology'}:
            return hold('INVALID_INPUT','UNSUPPORTED_REVIEW_OR_PROVENANCE_METADATA','Foreign review/instrument claims cannot grant authority.')
        try:
            if assumed:_dynamic_fann(raw,name)
            else:
                validate_lab_rheology(qc,name)
                well=state.get('well_data',{})
                if type(well) is not dict or not lab_temperature_valid(well.get('bhct',state.get('bhct')),well.get('bhst',state.get('bhst'))):
                    raise ValueError('Invalid existing BHCT/BHST context.')
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            return hold('INVALID_INPUT','APP_RHEOLOGY_VALIDATION_FAILED',str(exc))
        origin='PHASE_IX_AUXILIARY' if assumed else 'PHASE_VII_BHCT_DOWN'
        actual='UNKNOWN' if assumed else 'bhct_down'
        temperature=None if assumed else 'BHCT_CONTEXT_ONLY'
        qualifier='ASSUMED_BHCT_DOWN_TEMPERATURE_UNRECORDED' if assumed else 'APP_VALIDATED_OPERATOR_REVIEW_NOT_ASSERTED'
        context=None if assumed else (well.get('bhct',state.get('bhct')),well.get('bhst',state.get('bhst')))
        params=config.get('params',{});old=state.get('fluid_data',{})
        if type(params) is not dict or type(old) is not dict:return hold('INVALID_INPUT','FLUID_CONTEXT_INVALID','Canonical fluid context required.')
        record=params.get(name,old.get(name,{}))
        if type(record) is not dict:return hold('INVALID_INPUT','FLUID_CONTEXT_INVALID','Canonical selected fluid record required.')
        identity=fingerprint(['cfw128-gate4d-validated-source/1',identity,origin,actual,'ASSUMED_BHCT_DOWN' if assumed else 'bhct_down',temperature,'NOT_ASSERTED',context,
                              _positional_source((state.get('mud_type',state.get('well_data',{}).get('mud_type','WBM')),record.get('density'),record.get('material_name')))])
        return ValidatedStageIntake('CAPTURED_FOR_FUTURE_REVIEW',('APP_VALIDATED_SEVEN_RPM_SOURCE',qualifier,'INSTRUMENT_PROVENANCE_UNVERIFIED'),
            'Engineering input only; no operator review or physical qualification asserted.',name,sha,identity,fingerprint([sha,name,identity]),tuple(readings),
            dataset=None if assumed else 'bhct_down',source_origin=origin,actual_ramp=actual,temperature_condition=temperature,qualification_hold=qualifier)
    if set(qc)-{'rheology','reviewed','review_signature'}:
        return hold('INVALID_INPUT','LAB_METADATA_UNSUPPORTED','Spacer source cannot assert foreign instrument/review authority.')
    if qc.get('reviewed') is not True:return hold('REVIEW_REQUIRED','LAB_NOT_REVIEWED','Actual operator confirmation is required.')
    try:
        payload=spacer_lab_payload(state,rebuild=False)
        current_signature=lab_source_signature(state,name)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as exc:
        return hold('STALE_REVIEW','SPACER_SOURCE_OR_REVIEW_INVALID',str(exc))
    identity=fingerprint(['cfw128-gate4c-reviewed-spacer/1',identity,current_signature,payload['bhct'],payload['bhst']])
    return LabIntakeSnapshot('CAPTURED_FOR_FUTURE_REVIEW',
        ('INTACT_REVIEWED_BHCT_DOWN_SOURCE','INSTRUMENT_PROVENANCE_UNVERIFIED'),
        'Existing current Spacer cup/review proved; no physical instrument qualification.',name,sha,identity,
        fingerprint([sha,name,identity]),tuple(readings),None,current_signature,qc['review_signature'])


def _validate_native_observation(o, source, hashes, channels, events, stages, names, capacity):
    if type(o) is not NativePortObservation:
        raise ValueError('Missing typed native port observation.')
    _primitive(o)
    _number(capacity,True)
    if (o.source_identity!=source or o.source_hashes!=hashes
            or o.status!='OBSERVATION_ONLY_HOLD' or o.currentness!='NOT_CURRENTNESS_PROOF'
            or o.qualification!='NOT_GRANTED' or o.qout_semantics!='ANNULAR_MOUTH_PLUS_PIPE_HEAD'
            or o.shoe_crossing_time!='WITHIN_INTERVAL_NOT_OBSERVED'):
        raise ValueError('Native observation source/declaration mismatch.')
    def shape(v,n):
        if type(v) is not tuple or len(v)!=n:raise ValueError('Malformed native observation tuple.')
    def number(v,signed=False):
        if type(v) not in (float,int):raise ValueError('Real observation scalar required.')
        _number(abs(v) if signed else v)
    def close(a,b):
        # Existing Gate4B volume-audit bound, never a pressure/physics tolerance.
        if not math.isclose(a,b,rel_tol=0.,abs_tol=1e-9):raise ValueError('Native observation conservation differs.')
    def tokens(rows):
        if type(rows) is not tuple:raise ValueError('Immutable native tokens required.')
        for token in rows:
            shape(token,2);name,value=token
            if type(name) is not str or name not in names:raise ValueError('Unknown native fluid identity.')
            number(value)
            if value<=0:raise ValueError('Positive actual token removal/injection required.')
        return {n:math.fsum(v for name,v in rows if name==n) for n in names}
    def snapshot(v):
        shape(v,4);number(v[0]);number(v[3],signed=True);pipe=tokens(v[1]);ann=tokens(v[2])
        close(math.fsum(pipe.values())+v[3],capacity)
        return {n:pipe[n]+ann[n] for n in names}
    shape(o.payload,5);version,initial,rows,eod,tail=o.payload
    if version!='CFW128_NATIVE_PORT_INVENTORY_V1' or type(rows) is not tuple or not rows:
        raise ValueError('Unsupported/missing native observation version/intervals.')
    initial_inventory=snapshot(initial)
    if initial[0]!=0. or initial[3]!=0.:raise ValueError('Native initial time/gap differs.')
    if len(initial[1])!=1 or len(initial[2])!=1 or initial[1][0][0]!='Mud' or initial[2][0][0]!='Mud':
        raise ValueError('Native initial columns must match the initial Mud source.')
    end_inventory=snapshot(eod);tail_inventory=snapshot(tail)
    event=dict(events);t=channels[0]
    if eod[0]!=event['t_eod'] or tail[0]<eod[0] or len(rows)>len(t):
        raise ValueError('Native observation EOD/tail chronology differs.')
    if event['t_eod']==0. and eod!=initial:raise ValueError('Zero-job pump-end differs from initial state.')
    balance=dict(initial_inventory);pump_seen=event['t_eod']==0.
    cursor=0.;blocks=[]
    for name,volume,rate in stages:
        if volume==0:continue
        end=cursor+volume/rate;blocks.append((cursor,end,name));cursor=end
    if cursor!=event['t_eod']:raise ValueError('Native stage/EOD source differs.')
    previous=0.
    branches=('normal','frictionless','freefall','ffrefill','gapclose','freeex','tail_ff','tail_rev','tail_bal','tail_cap')
    for i,row in enumerate(rows):
        shape(row,8);start,end,duration,branch,fluid,injected,ports,gap=row
        for value in (start,end,duration):number(value)
        number(gap,signed=True)
        if (start!=previous or end<start or duration!=end-start or start!=t[i]
                or duration==0. and i!=len(rows)-1 or branch not in branches):
            raise ValueError('Native observation interval differs.')
        wanted=next((name for a,b,name in blocks if a<=start<b),'Mud')
        if type(fluid) is not str or fluid!=wanted:raise ValueError('Injected stage identity differs.')
        if len(injected)>1:raise ValueError('Duplicate native injection event.')
        if duration==0. and (injected or any(pair[1] for pair in ports)):
            raise ValueError('Zero-duration observation cannot move fluid.')
        inc=tokens(injected)
        if any(n!=fluid and v!=0 for n,v in inc.items()):raise ValueError('Injected token is not the source stage.')
        close(math.fsum(inc.values()),channels[5][i]*duration)
        shape(ports,2)
        returned={n:0. for n in names}
        for expected,pair in zip(('ANNULAR_MOUTH','PIPE_HEAD'),ports):
            shape(pair,2)
            if pair[0]!=expected:raise ValueError('Changed/duplicate native surface port.')
            actual=tokens(pair[1])
            for n,v in actual.items():returned[n]+=v
        close(math.fsum(returned.values()),channels[6][i]*duration)
        for n in names:balance[n]+=inc[n]-returned[n]
        if end==eod[0] and not pump_seen:
            for n in names:close(balance[n],end_inventory[n])
            if gap!=eod[3]:raise ValueError('Pump-end gap differs.')
            pump_seen=True
        previous=end
    if not pump_seen or tail[0]!=previous or tail[3]!=rows[-1][7]:raise ValueError('Missing native pump-end/tail snapshot.')
    for n in names:close(balance[n],tail_inventory[n])
    if len(rows)<len(t):
        if event['t_shutin']!=rows[-1][0] or any(q!=0 for q in channels[5][len(rows):]+channels[6][len(rows):]):
            raise ValueError('Unaccounted native flow after transport intervals.')
    return o


def run_numeric_test_case(state: dict, *, expected_app_source_sha: str, boundary: NumericBoundary,
                          engine: str='vertical', stepping: str='frozen', composition: CompositionReceipt | None=None) -> NumericEvidence:
    """Run original simulate only for admitted, explicitly synthetic inputs.

    PSIA conversion/field pressure qualification is unsupported. BHSP is a total
    bottom target in the same declared surface reference, never an increment.
    App station TVD is an explicit geometric input exception; research interior
    interpolation remains piecewise linear, never App-interior parity.
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
    compare=();lab_bindings=[];tvd_proof=()
    trajectory_source='APP_DIRECTIONAL_STATION_TVD_V1' if source['well_geometry']['type']=='Directional' else 'VERTICAL_SOURCE_V1'
    def held(reason):
        held_source=fingerprint(['cfw128-gate3-held-source/1',base,tuple(lab_bindings)])
        identity=fingerprint(['cfw128-gate3-hold/1',held_source,reason,compare])
        identity=fingerprint(['cfw128-gate5bp1-result/1',identity,trajectory_source,tvd_proof])
        return NumericEvidence(sha,c.projection_identity,held_source,identity,'HOLD',(*holds,reason),engine_label,s.shoe_md,(),(),None,g.nominal_injection_bbl,tvd_comparison=compare,source_hashes=source_hashes,trajectory_source=trajectory_source,directional_tvd_proof=tvd_proof)
    if source['well_geometry']['type']=='Directional':
        stations=s.survey
        knots=[p for p in s.trajectory if p.md in tuple(v.md for v in stations)]
        if tuple(p.md for p in knots)!=tuple(p.md for p in stations):raise ValueError('Captured survey/TVD station mismatch.')
        survey=d.Survey([p.md for p in knots],[p.tvd for p in knots],inc=[p.deviation_deg for p in stations],azi=[p.azimuth_deg for p in stations],source='captured App canonical survey')
        # Fresh App query captures supply the actual partial-inclination integral.
        queries=tuple((a.md+b.md)/2 for a,b in zip(stations,stations[1:]))
        interior=compose_nominal_tracking(source,expected_app_source_sha=sha,query_md=queries)
        actual={p.md:p.tvd for p in interior.captured_geometry.trajectory}
        compare=tuple((md,actual[md],survey.tvd_at(md)) for md in queries)
        if engine=='vertical':return held('DIRECTIONAL_SOURCE_REQUIRES_DIRECTIONAL_ENGINE')
        tvd_proof=('APP_WELL_PROFILE_DERIVED_STATION_KNOTS','ER03_PIECEWISE_LINEAR_INTERIOR',
                   tuple((p.md,p.deviation_deg,p.azimuth_deg) for p in stations),
                   tuple((p.md,p.tvd) for p in knots),s.source_identity,s.request_identity)
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
        intake=_stage_lab_intake(source,stage.name,sha)
        lab_bindings.append((intake.source_identity,intake.request_identity,intake.status))
        if intake.status!='CAPTURED_FOR_FUTURE_REVIEW':return held('LAB_SOURCE_HOLD:'+stage.name+':'+','.join(intake.reason_codes))
        if intake.instrument_provenance!='UNVERIFIED':raise ValueError('Unsupported instrument provenance claim.')
        validated=type(intake) is ValidatedStageIntake
        ramp=intake.fit_ramp if validated else intake.dataset
        reviewed=intake.fit_reviewed if validated else True
        temperature=intake.temperature_condition if validated else 'BHCT'
        origin=intake.source_origin if validated else 'PHASE_VII'
        actual=intake.actual_ramp if validated else intake.dataset
        operator=intake.operator_review if validated else 'EXISTING_REVIEW_PROVED'
        qualifier=intake.qualification_hold if validated else 'PHYSICAL_INSTRUMENT_UNVERIFIED'
        if validated:holds=(*holds,stage.name+':'+qualifier)
        fit=fit_full_hb(tuple(v.dial for v in intake.readings),intake.rpm_order,
            instrument=InstrumentConfig('Fann 35','R1B1','1.0'),ramp_type=ramp,reviewed=reviewed,
            temperature_condition=temperature,fluid_id=stage.name,record_id=intake.source_identity)
        if fit.status!='OK' or fit.tau_y_pa is None or fit.tau_y_pa<=0:return held('FULL_HB_NONZERO_YIELD_NOT_PROVED:'+stage.name)
        hb=to_engine_field(fit.tau_y_pa,fit.k_pa_s_n,fit.n_dimensionless)
        fluid=v.Fluid(name=stage.name,rho_ppg=v.pcf_to_ppg(stage.density_pcf),mu_p_cp=hb.mu_p_cp,
            tau_y=hb.tau_y_field_lbf_100ft2,n_pl=hb.n_dimensionless,K_pl=hb.k_pa_s_n,gel_pa=gels[stage.name],frictionless_fluid=False)
        if (fluid.tau_y,fluid.K_pl,fluid.n_pl)!=(hb.tau_y_field_lbf_100ft2,hb.k_pa_s_n,hb.n_dimensionless):raise ValueError('HB transfer differs.')
        fluids[stage.name]=fluid
        proofs.append(FluidProof(stage.name,intake.source_identity,tuple((v.rpm,v.raw) for v in intake.readings),fit.tau_y_pa,fluid.tau_y,fluid.K_pl,fluid.n_pl,fluid.rho_ppg,fluid.gel_pa,origin,actual,'ASSUMED_BHCT_DOWN' if actual=='UNKNOWN' else ramp,temperature,operator,reviewed,qualifier))
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
    numeric_source=fingerprint(['cfw128-gate5bp1-source/1',numeric_source,trajectory_source,tvd_proof])
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
        # bottom_shutin_psi echoes the target; endpoint equality establishes
        # neither its station nor its datum. No independent certificate enters
        # this synthetic boundary. Preserve raw diagnostic series and fail closed.
        status='HOLD';holds=(*holds,'BHSP_TARGET_STATION_NOT_PROVED')
    audit=tuple(audit)
    observation=None
    if stepping!='frozen':
        observation=NativePortObservation(numeric_source,source_hashes,result.diag.get('native_port_inventory_v1'))
        _validate_native_observation(observation,numeric_source,source_hashes,channels,events,
            tuple((v.fluid_type,v.volume_bbl,v.rate_bpm) for v in stages),tuple(fluids),geo.total_pipe_bbl)
        if tuple((row[0],row[1],row[2],row[4],channels[5][i],channels[6][i],row[3])
                 for i,row in enumerate(observation.payload[2]))!=tuple(intervals):
            raise ValueError('Native observation and original interval audit differ.')
    identity=fingerprint(['cfw128-gate3-result/1',numeric_source,channels,events,geo.total_pipe_bbl,compare,audit,status,holds])
    identity=fingerprint(['cfw128-gate5bp1-result/1',identity,trajectory_source,tvd_proof])
    if observation is not None:identity=fingerprint(['cfw128-gate6c-observation/1',identity,_primitive(observation)])
    return NumericEvidence(sha,c.projection_identity,numeric_source,identity,status,holds,engine_label,s.shoe_md,encoded,tuple(proofs),geo.total_pipe_bbl,g.nominal_injection_bbl,*channels,events,compare,stage_volume_audit=audit,source_hashes=source_hashes,directional_tvd_proof=tvd_proof,trajectory_source=trajectory_source,native_observation=observation)


def render_numeric_test_charts(evidence: NumericEvidence):
    """Disabled presentation only; return a caller-owned figure, never admission.

    Reads already-produced synthetic evidence. No capture, fit, simulation,
    state, persistence or Word access. Hash consistency is NOT_CURRENTNESS_PROOF;
    all source holds survive unchanged. Labels do not certify a pressure datum.
    """
    if type(evidence) is not NumericEvidence:raise TypeError('NumericEvidence required.')
    r=evidence
    _primitive(r)
    if (r.evidence_class!='SYNTHETIC_TEST_ONLY' or r.currentness!='NOT_CURRENTNESS_PROOF'
            or r.final_post_pull_toc!='NOT_EVALUATED' or r.qualification!='NOT_GRANTED'):
        raise ValueError('Disabled evidence declarations required.')
    if r.status not in ('NUMERIC_ABI_CANDIDATE_ENGINE_DISABLED','HOLD'):
        raise ValueError('Unsupported numerical evidence status.')
    expected_hashes=(VERTICAL_SHA256,DIRECTIONAL_SHA256,HB_SHA256)
    if r.engine in ('event_aligned_vertical','event_aligned_directional'):expected_hashes+=EVENT_SHA256
    elif r.engine not in ('vertical','directional'):raise ValueError('Unsupported numerical engine.')
    if r.source_hashes!=expected_hashes:raise ValueError('Numerical source locks differ.')
    for value,size in ((r.app_source_sha,40),(r.composition_projection_identity,64),(r.source_identity,64),(r.projection_identity,64)):
        if type(value) is not str or len(value)!=size or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Malformed source identity.')
    _number(r.pressure_station_md,True)
    names=('time_min','whp_kpsi','pump_kpsi','hydrostatic_kpsi','total_pressure_kpsi','q_in_bpm','q_out_bpm')
    channels=tuple(getattr(r,name) for name in names);t=channels[0]
    if len(t)<2:raise ValueError('Finished numerical series required, including for a HOLD.')
    for name,values in zip(names,channels):
        if type(values) is not tuple or (len(values)!=len(t) and not (name=='total_pressure_kpsi' and values==())):
            raise ValueError('Missing or misaligned numerical channel.')
        for value in values:
            if type(value) not in (int,float):raise ValueError('Finite real samples required.')
            _number(abs(value))
    if t[0]<0 or any(b<=a for a,b in zip(t,t[1:])):raise ValueError('Strictly increasing nonnegative time required.')
    keys=('t_atcp','t_eod','t_marker','t_freefall_start','t_freefall_end','t_shutin','whp_final_psi','bottom_shutin_psi')
    if type(r.events) is not tuple or any(type(row) is not tuple or len(row)!=2 for row in r.events):
        raise ValueError('Malformed engine events.')
    if tuple(row[0] for row in r.events)!=keys:raise ValueError('Missing, duplicate or unknown engine event key/order.')
    events=dict(r.events)
    for name,value in r.events:
        if value is None:continue
        _number(value)
        if name.startswith('t_') and not t[0]<=value<=t[-1]:raise ValueError('Event outside recorded series.')
    if events['t_eod'] is None:raise ValueError('Finished record requires EOD.')
    start,end=events['t_freefall_start'],events['t_freefall_end']
    if end is not None and (start is None or end<start):raise ValueError('Inconsistent freefall events.')
    if events['t_marker']!=events['t_shutin']:raise ValueError('Shut-in marker differs from its declared event.')
    if events['t_shutin'] is not None and events['t_shutin']<events['t_eod']:raise ValueError('Shut-in precedes EOD.')
    identity=fingerprint(['cfw128-gate3-result/1',r.source_identity,channels,r.events,r.engine_injection_capacity_bbl,r.tvd_comparison,r.stage_volume_audit,r.status,r.holds])
    if type(r.trajectory_source) is not str or r.trajectory_source not in ('VERTICAL_SOURCE_V1','APP_DIRECTIONAL_STATION_TVD_V1'):
        raise ValueError('Unknown source trajectory version.')
    if type(r.directional_tvd_proof) is not tuple:raise TypeError('Immutable trajectory proof required.')
    if r.trajectory_source=='VERTICAL_SOURCE_V1':
        if r.directional_tvd_proof:raise ValueError('Vertical source cannot carry directional proof.')
    else:
        proof=r.directional_tvd_proof
        if (len(proof)!=6 or proof[:2]!=('APP_WELL_PROFILE_DERIVED_STATION_KNOTS','ER03_PIECEWISE_LINEAR_INTERIOR')
                or type(proof[2]) is not tuple or type(proof[3]) is not tuple
                or len(proof[2])!=len(proof[3]) or len(proof[2])<2
                or any(type(v) is not tuple or len(v)!=3 for v in proof[2]) or any(type(v) is not tuple or len(v)!=2 for v in proof[3])
                or tuple(v[0] for v in proof[2])!=tuple(v[0] for v in proof[3])):
            raise ValueError('Invalid directional TVD provenance.')
        if r.engine not in ('directional','event_aligned_directional'):raise ValueError('Directional source requires directional engine.')
        for ref in proof[4:]:
            if type(ref) is not str or len(ref)!=64 or any(c not in '0123456789abcdef' for c in ref):raise ValueError('Malformed trajectory source reference.')
        # Consistency with snapshot_geometry's published default-query request;
        # unkeyed fingerprints still prove neither authenticity nor currentness.
        if proof[5]!=fingerprint([1,r.app_source_sha,proof[4],()]):raise ValueError('Trajectory request/source reference mismatch.')
        tol=directional.ER01_TOL_M
        previous=None
        for station,knot in zip(proof[2],proof[3]):
            for value in (*station,*knot):
                if type(value) not in (int,float):raise TypeError('Real trajectory coordinates required.')
                _number(abs(value))
            md,inc,azi=station;tvd=knot[1]
            if md<0 or not 0<=inc<=180 or not 0<=azi<360 or tvd < -tol:raise ValueError('Invalid trajectory coordinate range.')
            if previous is None:
                if md!=0 or abs(tvd)>tol:raise ValueError('Trajectory surface datum required.')
            elif md<=previous[0] or abs(tvd-previous[1])>md-previous[0]+tol:
                raise ValueError('Invalid trajectory order or TVD slope.')
            previous=(md,tvd)
        if previous[0]<r.pressure_station_md-tol:raise ValueError('Trajectory does not cover pressure station.')
    identity=fingerprint(['cfw128-gate5bp1-result/1',identity,r.trajectory_source,r.directional_tvd_proof])
    if r.engine.startswith('event_aligned_'):
        _validate_native_observation(r.native_observation,r.source_identity,r.source_hashes,channels,r.events,
            tuple((v[0],v[2],v[4]) for v in r.stages),('Mud',*(v.name for v in r.fluids)),r.engine_injection_capacity_bbl)
        identity=fingerprint(['cfw128-gate6c-observation/1',identity,_primitive(r.native_observation)])
    elif r.native_observation is not None:raise ValueError('Frozen source cannot assert native port evidence.')
    if identity!=r.projection_identity:raise ValueError('Numerical evidence projection differs.')
    green=tuple(events[name] for name in ('t_atcp','t_eod') if events[name] is not None)
    marker=events['t_marker']
    if marker is not None and any(abs(marker-e)<1e-9 for e in green):marker=None
    hydro=r.hydrostatic_kpsi;dynamic=r.total_pressure_kpsi
    try:
        axes=(autoscale_x(t[-1]),autoscale_y(0.,max(*r.whp_kpsi,*r.pump_kpsi,.1),zero_based=True),
              autoscale_y(min(*hydro,*dynamic),max(*hydro,*dynamic),zero_based=False),
              autoscale_y(min(*r.q_in_bpm,*r.q_out_bpm),max(*r.q_in_bpm,*r.q_out_bpm),zero_based=False))
        if any(not math.isfinite(v) for axis in axes for v in axis if type(v) in (int,float)):
            raise ValueError('Unrepresentable presentation axes.')
    except (OverflowError,ZeroDivisionError) as exc:raise ValueError('Unrepresentable presentation axes.') from exc
    spec=JobChartsSpec(calc_cem_hp=(t,r.whp_kpsi),calc_pump_press=(t,r.pump_kpsi),
        hydrostatic=(t,hydro),dynamic=(t,dynamic) if dynamic else None,q_in=(t,r.q_in_bpm),q_out=(t,r.q_out_bpm),
        acquired_pressure=None,back_pressure=None,acquired_q_in=None,acquired_q_out=None,
        depth_m=r.pressure_station_md,depth_unit='m',event_times=green,marker_time=marker,
        axis_x=axes[0],axis_y1=axes[1],axis_y2=axes[2],axis_y3=axes[3])
    return render_three_charts(spec)
