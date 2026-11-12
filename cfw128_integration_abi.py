"""Disabled canonical composition only; no App caller or numerical execution.

Reads: fresh caller-supplied project source and externally verified App SHA.
Writes/schema/persistence/report/template/dependency impact: none.
Authorities: existing capture, C1/C2a/C2b, C2d, C2e4/C2e5 and C2e1 kernel.
Owned behavior: receipt orchestration/provenance; no geometry or transport model.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal
import math

from cfw128_adapter import snapshot_geometry, GeometrySnapshot
from cfw128_er03_contract import prepare_er03_preview
from cfw128_er03_boundary import assess_er03_boundary
from cfw128_er03_volume import audit_geometric_capacity
from cfw128_c2d_geometry_view import build_geometry_view, GeometryView
from cfw128_c2e4_derived_displacement import derive_displacement, DerivedDisplacement
from cfw128_c2e5_effective_schedule import build_effective_schedule, EffectiveSchedule
from cfw128_c2e_volume_tracking import preview_effective_schedule, TrackingPreview
from project_state import fingerprint


@dataclass(frozen=True, slots=True)
class CompositionReceipt:
    app_source_sha: str
    source_identity: str
    projection_identity: str
    captured_geometry: GeometrySnapshot
    geometry: GeometryView
    displacement: DerivedDisplacement
    schedule: EffectiveSchedule
    tracking: TrackingPreview
    numerical_source_fields: tuple[tuple[str,str,str | int | float | None],...]
    holds: tuple[str,...]
    status: Literal['DISABLED_COMPOSITION_ONLY']=field(default='DISABLED_COMPOSITION_ONLY',init=False)
    currentness: Literal['NOT_CURRENTNESS_PROOF']=field(default='NOT_CURRENTNESS_PROOF',init=False)
    hydraulics: Literal['HYDRAULICS_NOT_EVALUATED']=field(default='HYDRAULICS_NOT_EVALUATED',init=False)
    final_post_pull_toc: Literal['FINAL_POST_PULL_TOC_NOT_EVALUATED']=field(default='FINAL_POST_PULL_TOC_NOT_EVALUATED',init=False)
    enabled: Literal[False]=field(default=False,init=False)
    ready_to_run: Literal[False]=field(default=False,init=False)
    hb_admissible: Literal[False]=field(default=False,init=False)
    hydraulic_admissible: Literal[False]=field(default=False,init=False)
    chart_admissible: Literal[False]=field(default=False,init=False)
    scientifically_qualified: Literal[False]=field(default=False,init=False)


def compose_nominal_tracking(state: dict, *, expected_app_source_sha: str,
                            query_md: tuple[float,...]=(), stage_end: int | None=None) -> CompositionReceipt:
    """Fresh source capture, derived schedule and receipt-native nominal tracking.

    The caller verifies SHA externally. A copied old project remains replayable,
    NOT proof of current App state. Missing numerical fields are held, not filled.
    No reviewed lab source or fitter is consumed/claimed by this geometry seam.
    """
    if type(state) is not dict:raise TypeError('Canonical project dictionary required.')
    source=deepcopy(state)
    captured=snapshot_geometry(source,app_source_sha=expected_app_source_sha,query_md=query_md)
    if captured.status not in ('GEOMETRY_REPRESENTABLE','ENGINE_INTERFACE_NOT_REPRESENTABLE'):
        raise ValueError('SOURCE_NOT_READY: '+','.join(captured.reason_codes))
    preview=prepare_er03_preview(captured,expected_app_source_sha=expected_app_source_sha)
    boundary=assess_er03_boundary(preview,expected_app_source_sha=expected_app_source_sha)
    capacity=audit_geometric_capacity(boundary,expected_app_source_sha=expected_app_source_sha)
    geometry=build_geometry_view(captured,capacity,expected_app_source_sha=expected_app_source_sha)
    derived=derive_displacement(geometry,expected_app_source_sha=expected_app_source_sha)
    schedule=build_effective_schedule(geometry,derived,source,expected_app_source_sha=expected_app_source_sha)
    mud_type=source.get('mud_type',source.get('well_data',{}).get('mud_type','WBM'))
    tracking=preview_effective_schedule(geometry,schedule,expected_app_source_sha=expected_app_source_sha,
                                      mud_type=mud_type,stage_end=len(schedule.stages) if stage_end is None else stage_end)
    metadata=[];missing=[];params=source['fluids_config'].get('params',{});old=source.get('fluid_data',{})
    for stage in schedule.stages:
        row=params[stage.name] if stage.name in params else old.get(stage.name,{})
        for key in ('material_name','pump_rate'):
            value=row.get(key) if type(row) is dict else None
            if value is not None and (type(value) not in (str,int,float) or type(value) is float and not math.isfinite(value)):
                raise ValueError('Primitive finite numerical source metadata required.')
            metadata.append((stage.name,key,value))
            if value is None or value=='':missing.append('GATE3_MISSING_'+key.upper()+':'+stage.name)
    metadata=tuple(metadata)
    holds=tuple(dict.fromkeys((*captured.future_gates,*preview.reason_codes,
        'GATE3_NUMERICAL_RATE_MATERIAL_AND_RHEOLOGY_NOT_VALIDATED','LAB_REVIEW_AND_INSTRUMENT_NOT_ASSESSED',
        'DOWNSTREAM_C2E2_AND_POST_PULL_CLOSURE_NOT_COMPOSED','HOLD_25M_TERMINAL_PLACEMENT_BEHAVIOR_UNDEFINED',
        'HOLD_POST_PULL_PHYSICAL_REMAP_UNDEFINED',*missing)))
    identity=fingerprint(['cfw128-gate2-source/1',expected_app_source_sha,captured.source_identity,captured.request_identity,
                          geometry.source_identity,geometry.projection_identity,derived.projection_identity,schedule.source_identity,schedule.projection_identity,metadata])
    projection=fingerprint(['cfw128-gate2-composition/1',identity,tracking.source_identity,tracking.projection_identity,holds])
    return CompositionReceipt(expected_app_source_sha,identity,projection,captured,geometry,derived,schedule,tracking,metadata,holds)
