"""I1: explicit read-only App-source preflight, never engine admission.

Reads caller-owned canonical input and existing geometry/composition/lab
authorities. Owns only a consolidated immutable readiness diagnostic. No App
caller, state writes, persistence/schema, UI, Word, fit or simulation authority.
Composition is reused for source validation; no nominal placement is exported.
"""
from copy import deepcopy
from dataclasses import dataclass, field, fields

from cfw128_adapter import snapshot_geometry, _positional_source
from cfw128_er03_contract import prepare_er03_preview
from cfw128_er03_boundary import assess_er03_boundary
from cfw128_integration_abi import compose_nominal_tracking
from cfw128_er03_numeric_adapter import _stage_lab_intake, _primitive
from cfw128_hb_intake import LabIntakeSnapshot
from engineering_tools import require_positive_pump_rate
from project_state import fingerprint

SCHEMA = 'CFW128_REAL_SOURCE_PREFLIGHT_V1'
HOLDS = ('NO_NATIVE_EXECUTION', 'PHYSICAL_INSTRUMENT_UNVERIFIED',
         'FIELD_PRESSURE_DATUM_NOT_CERTIFIED', 'BHSP_TARGET_STATION_NOT_PROVED',
         'INV014_FAIL_WITH_OWNER_EXCEPTION', 'FINAL_POST_PULL_TOC_NOT_EVALUATED',
         'FINAL_FIELD_TOC_NOT_GRANTED')


@dataclass(frozen=True, slots=True)
class FluidPreflight:
    name: str
    effective_stage_identity: str | None
    input_status: str
    intake: LabIntakeSnapshot | None

    @property
    def lab_status(self):
        return 'NOT_EVALUATED' if self.intake is None else self.intake.status


@dataclass(frozen=True, slots=True)
class SourcePreflight:
    app_source_sha: str
    source_identity: str
    job: str
    geometry_identity: str
    geometry_status: str
    topology_identity: str
    topology_status: str
    boundary_identity: str
    composition_identity: str | None
    composition_status: str
    injection_intervals: tuple[tuple[float, float], ...]
    structural_return_md: tuple[float, ...]
    receiver_shoe_md: float | None
    composition_return_md: tuple[float, ...]
    fluids: tuple[FluidPreflight, ...]
    # authority/fluid, reason code, existing validator detail
    issues: tuple[tuple[str, str, str], ...]
    inputs_complete: bool
    holds: tuple[str, ...]
    projection_identity: str
    schema: str = field(default=SCHEMA, init=False)
    status: str = field(default='DISABLED_REAL_SOURCE_PREFLIGHT_HOLD', init=False)
    evidence_class: str = field(default='SYNTHETIC_TEST_ONLY', init=False)
    currentness: str = field(default='NOT_CURRENTNESS_PROOF', init=False)
    qualification: str = field(default='NOT_GRANTED', init=False)
    enabled: bool = field(default=False, init=False)
    ready_to_run: bool = field(default=False, init=False)
    hb_admissible: bool = field(default=False, init=False)
    hydraulic_admissible: bool = field(default=False, init=False)
    chart_admissible: bool = field(default=False, init=False)
    scientifically_qualified: bool = field(default=False, init=False)

    def __post_init__(self):
        _primitive(self)
        if any(getattr(self, f.name) != f.default for f in fields(self) if not f.init):
            raise ValueError('Disabled preflight declarations required.')
        values = tuple(getattr(self, f.name) for f in fields(self) if f.init and f.name != 'projection_identity')
        if self.projection_identity != fingerprint([SCHEMA, _primitive(values)]):
            raise ValueError('Preflight projection differs.')

    def validate_source(self, state, *, expected_app_source_sha):
        """Compare fresh supplied input, never certify external live currentness."""
        self.__post_init__()
        if self != preflight_project(state, expected_app_source_sha=expected_app_source_sha):
            raise ValueError('Stale or mixed preflight source.')


def preflight_project(state: dict, *, expected_app_source_sha: str) -> SourcePreflight:
    """Consolidate existing validators without fitting or running numerics.

    Historical Tie Back Shoe-to-Lap preview is separately labeled from C2d's
    current surface corridor. Neither geometry label proves an outlet pressure.
    Missing field measurements remain missing; no synthetic values are supplied.
    """
    if type(state) is not dict:
        raise TypeError('Caller-supplied canonical project dictionary required.')
    source = deepcopy(state)
    geometry = snapshot_geometry(source, app_source_sha=expected_app_source_sha)
    identity = fingerprint([SCHEMA, expected_app_source_sha, _positional_source(source)])
    topology = prepare_er03_preview(geometry, expected_app_source_sha=expected_app_source_sha)
    boundary = assess_er03_boundary(topology, expected_app_source_sha=expected_app_source_sha)
    issues = []
    holds = [*HOLDS, *geometry.future_gates, *boundary.reason_codes]
    valid_geometry = geometry.status in ('GEOMETRY_REPRESENTABLE', 'ENGINE_INTERFACE_NOT_REPRESENTABLE')
    if not valid_geometry:
        issues.extend(('geometry', code, geometry.detail) for code in geometry.reason_codes)
    composition = None
    if valid_geometry:
        try:
            composition = compose_nominal_tracking(source, expected_app_source_sha=expected_app_source_sha)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            issues.append(('composition', 'COMPOSITION_SOURCE_NOT_READY', str(exc)))
    if composition is not None:
        holds.extend(composition.holds)
    if geometry.kind == 'tieback':
        holds.append('HISTORICAL_PARTIAL_PREVIEW_NOT_HYDRAULIC_OUTLET')
    config = source.get('fluids_config')
    active = config.get('active') if type(config) is dict else None
    if type(active) is not list or not active:
        issues.append(('stages', 'FLUID_SELECTION_MISSING_OR_INVALID', 'Canonical active-fluid list required.'))
        active = []
    metadata = {} if composition is None else {(name, key): value for name, key, value in composition.numerical_source_fields}
    effective = {} if composition is None else {s.name: s for s in composition.schedule.stages}
    fluids = []
    for name in active:
        if type(name) is not str:
            issues.append(('stages', 'NONCANONICAL_FLUID_IDENTITY', 'Exact canonical fluid names required.'))
            continue
        start = len(issues)
        if name not in effective:
            issues.append((name, 'EFFECTIVE_STAGE_NOT_EVALUATED', 'Existing composition has no validated effective stage.'))
        else:
            material = metadata.get((name, 'material_name'))
            if type(material) is not str or not material.strip():
                issues.append((name, 'MATERIAL_SOURCE_MISSING', 'Current stage material identity required.'))
            rate = metadata.get((name, 'pump_rate'))
            try:
                if type(rate) not in (str, int, float):
                    raise ValueError('Primitive actual pump-rate source required.')
                require_positive_pump_rate(rate)
            except (ValueError, TypeError, OverflowError) as exc:
                issues.append((name, 'RATE_SOURCE_INVALID', str(exc)))
        intake = None
        try:
            intake = _stage_lab_intake(source, name, expected_app_source_sha)
            holds.extend(intake.reason_codes)
            if intake.status != 'CAPTURED_FOR_FUTURE_REVIEW':
                issues.extend((name, code, intake.detail) for code in intake.reason_codes)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            issues.append((name, 'LAB_SOURCE_INVALID', str(exc)))
        fluids.append(FluidPreflight(name, effective[name].source_identity if name in effective else None,
            'SOURCE_VALIDATED' if len(issues) == start else 'SOURCE_HOLD', intake))
    if fingerprint([SCHEMA, expected_app_source_sha, _positional_source(state)]) != identity:
        raise ValueError('Source changed during preflight.')
    path = () if composition is None else composition.geometry.pumping_return
    values = (expected_app_source_sha, identity, geometry.job, geometry.source_identity, geometry.status,
        topology.projection_identity, topology.status, boundary.projection_identity,
        None if composition is None else composition.projection_identity,
        'NOT_EVALUATED' if composition is None else composition.status,
        tuple((s.top_md, s.bottom_md) for s in topology.injection_sections), topology.return_travel_md,
        None if geometry.receiver is None else geometry.receiver.shoe_md,
        () if not path else (path[-1].bottom_md, path[0].top_md), tuple(fluids), tuple(issues),
        not issues and composition is not None, tuple(dict.fromkeys(holds)))
    return SourcePreflight(*values, fingerprint([SCHEMA, _primitive(values)]))
