"""B2b: dormant, read-only handoff of already captured seven-RPM source.

Reads B1/B1-M types and exact dial validator, App fingerprint, canonical fluid/RPM
catalogs. Writes nothing: no state, review refresh, persistence, UI, Word, fitter,
unit conversion or hydraulic dependency. Source SHA is caller-verified; this
preview cannot prove snapshot authenticity/currentness or physical instrument
identity. Re-snapshot current App state before any separately authorized future
execution. Coherently edited source metadata changes identities, never authority.
"""
from dataclasses import dataclass, field
import math
import re
from typing import Literal

from cfw128_hb_intake import LabIntakeSnapshot, DialReading, _dial
from materials_db import CEMENT_FORMULATION_FLUIDS
from project_state import fingerprint
from rheology import RPM_ORDER

_HB03T_RPMS = (300, 200, 100, 60, 30, 6, 3)  # Frozen reference, tested without importing HB.
_FLAGS = ('enabled', 'fit_admissible', 'ready_to_run', 'hydraulic_admissible',
          'chart_admissible', 'scientifically_qualified')


def _reading_problem(row):
    if type(row.rpm) is not int or row.rpm not in _HB03T_RPMS:
        return 'RPM_INVALID'
    if type(row.raw) not in (str, int, float):
        return 'DIAL_TYPE_INVALID'
    if type(row.raw_type) is not str or row.raw_type != type(row.raw).__name__:
        return 'RAW_TYPE_MISMATCH'
    if type(row.dial) is not int:
        return 'DIAL_INTEGER_TYPE_INVALID'
    try:
        value, problem = _dial(row.raw)
    except (ValueError, OverflowError):
        return 'DIAL_INVALID'
    if problem:
        return problem
    if value != row.dial:
        return 'RAW_DIAL_MISMATCH'
    try:
        converted = float(value)
    except OverflowError:
        return 'FLOAT_REPRESENTATION_UNSAFE'
    if not math.isfinite(converted) or int(converted) != value:
        return 'FLOAT_REPRESENTATION_UNSAFE'
    return None


@dataclass(frozen=True, slots=True)
class HBReading:
    rpm: int
    raw: str | int | float
    raw_type: str
    dial: int

    def __post_init__(self):
        problem = _reading_problem(self)
        if problem:
            raise ValueError(problem)


@dataclass(frozen=True, slots=True)
class HBIntent:
    status: Literal['SOURCE_NOT_READY', 'INVALID_SNAPSHOT', 'HOLD_NUMERIC_REPRESENTATION',
                    'HOLD_INSTRUMENT_PROVENANCE_UNVERIFIED']
    reason_codes: tuple[str, ...]
    upstream_status: str
    upstream_reason_codes: tuple[str, ...]
    upstream_source_identity: str
    upstream_request_identity: str
    app_source_sha: str
    fluid_name: str
    source_identity: str
    request_identity: str
    projection_identity: str
    material_name: str | None
    captured_formulation_signature: str | None
    captured_review_signature: str | None
    readings: tuple[HBReading, ...] = ()
    instrument_provenance: Literal['UNVERIFIED'] = field(default='UNVERIFIED', init=False)
    enabled: Literal[False] = field(default=False, init=False)
    fit_admissible: Literal[False] = field(default=False, init=False)
    ready_to_run: Literal[False] = field(default=False, init=False)
    hydraulic_admissible: Literal[False] = field(default=False, init=False)
    chart_admissible: Literal[False] = field(default=False, init=False)
    scientifically_qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self):
        strings = ('status', 'upstream_status', 'upstream_source_identity',
                   'upstream_request_identity', 'app_source_sha', 'fluid_name',
                   'source_identity', 'request_identity', 'projection_identity')
        if any(type(getattr(self, name)) is not str for name in strings):
            raise TypeError('Intent provenance contains only primitive strings.')
        for values in (self.reason_codes, self.upstream_reason_codes):
            if type(values) is not tuple or any(type(v) is not str for v in values):
                raise TypeError('Intent reasons are immutable tuples of strings.')
        for value in (self.material_name, self.captured_formulation_signature, self.captured_review_signature):
            if value is not None and type(value) is not str:
                raise TypeError('Intent source metadata is primitive or missing.')
        if type(self.readings) is not tuple or any(type(r) is not HBReading for r in self.readings):
            raise TypeError('Intent readings are an immutable typed tuple.')
        if self.status not in ('SOURCE_NOT_READY', 'INVALID_SNAPSHOT', 'HOLD_NUMERIC_REPRESENTATION',
                               'HOLD_INSTRUMENT_PROVENANCE_UNVERIFIED'):
            raise ValueError('An HB intent is always a hold, never an executable result.')
        if self.status == 'HOLD_INSTRUMENT_PROVENANCE_UNVERIFIED':
            if self.rpm_order != _HB03T_RPMS:
                raise ValueError('Preview requires all seven canonical RPM associations.')
        elif self.readings:
            raise ValueError('Unready/invalid source cannot contain a prepared dial payload.')

    @property
    def rpm_order(self):
        return tuple(row.rpm for row in self.readings)

    @property
    def dials(self):
        return tuple(row.dial for row in self.readings)


def _token(value):
    """Primitive type-tagged identity, preserving raw spelling/type and large ints."""
    if value is None:
        return ('None',)
    if type(value) is int:
        return ('int', hex(value))
    if type(value) in (str, bool):
        return (type(value).__name__, str(value))
    if type(value) is float:
        return ('float', value.hex())
    if type(value) is tuple:
        return ('tuple', tuple(_token(v) for v in value))
    if type(value) is DialReading:
        return ('DialReading', _token(value.rpm), _token(value.raw),
                _token(value.raw_type), _token(value.dial))
    raise TypeError('Snapshot contains noncanonical mutable/counterfeit source values.')


def prepare_hb_intent(snapshot: LabIntakeSnapshot, *, expected_app_source_sha: str) -> HBIntent:
    """Prepare data only; never revalidate current App state or run a numerical fit."""
    if type(snapshot) is not LabIntakeSnapshot:
        raise TypeError('Provide the actual immutable B1/B1-M LabIntakeSnapshot.')
    if type(expected_app_source_sha) is not str or not re.fullmatch('[0-9a-f]{40}', expected_app_source_sha):
        raise ValueError('Expected App source SHA must be 40 lowercase hex characters.')
    if snapshot.app_source_sha != expected_app_source_sha:
        raise ValueError('Captured App source SHA does not match the caller-verified expected SHA.')
    # Validate primitive metadata before owning or fingerprinting it. No coercion.
    metadata = (snapshot.status, snapshot.source_identity, snapshot.request_identity,
                snapshot.app_source_sha, snapshot.fluid_name, snapshot.detail)
    if any(type(v) is not str for v in metadata):
        raise TypeError('Snapshot provenance must contain primitive strings.')
    if type(snapshot.reason_codes) is not tuple or any(type(r) is not str for r in snapshot.reason_codes):
        raise TypeError('Snapshot reasons must be a tuple of strings.')
    for value in (snapshot.material_name, snapshot.formulation_signature, snapshot.review_signature):
        if value is not None and type(value) is not str:
            raise TypeError('Snapshot material/review provenance must be primitive.')
    source_id = fingerprint(['cfw128-b2b-source/1', expected_app_source_sha, metadata,
        snapshot.reason_codes, snapshot.material_name, snapshot.formulation_signature,
        snapshot.review_signature, _token(snapshot.dataset), _token(snapshot.rpm_order),
        _token(snapshot.instrument_provenance), _token(tuple(getattr(snapshot, f) for f in _FLAGS)),
        _token(snapshot.readings)])
    request_id = fingerprint(['cfw128-b2b-request/1', source_id, expected_app_source_sha])

    def hold(status, reason, readings=()):
        projection = fingerprint(['cfw128-b2b-projection/1', source_id, request_id, status, reason,
                                  tuple((r.rpm, _token(r.raw), r.raw_type, str(r.dial)) for r in readings)])
        return HBIntent(status, (reason,), snapshot.status, snapshot.reason_codes,
            snapshot.source_identity, snapshot.request_identity, expected_app_source_sha,
            snapshot.fluid_name, source_id, request_id, projection, snapshot.material_name,
            snapshot.formulation_signature, snapshot.review_signature, readings)

    if snapshot.status != 'CAPTURED_FOR_FUTURE_REVIEW':
        return hold('SOURCE_NOT_READY', 'UPSTREAM_SOURCE_NOT_CAPTURED')
    if snapshot.instrument_provenance != 'UNVERIFIED' or any(getattr(snapshot, f) is not False for f in _FLAGS):
        return hold('INVALID_SNAPSHOT', 'UNSUPPORTED_AUTHORIZATION_CLAIM')
    if (snapshot.fluid_name not in (*CEMENT_FORMULATION_FLUIDS, 'Displacement Fluid')
            or snapshot.dataset != 'bhct_down'):
        return hold('INVALID_SNAPSHOT', 'FLUID_OR_DATASET_INVALID')
    if (snapshot.reason_codes != ('INTACT_REVIEWED_BHCT_DOWN_SOURCE', 'INSTRUMENT_PROVENANCE_UNVERIFIED')
            or not snapshot.material_name or any(type(v) is not str or not re.fullmatch('[0-9a-f]{64}', v)
                for v in (snapshot.source_identity, snapshot.request_identity,
                          snapshot.formulation_signature, snapshot.review_signature))
            or snapshot.request_identity != fingerprint([1, expected_app_source_sha,
                                                        snapshot.fluid_name, snapshot.source_identity])):
        return hold('INVALID_SNAPSHOT', 'CAPTURE_PROVENANCE_INVALID')
    if (type(snapshot.rpm_order) is not tuple or snapshot.rpm_order != _HB03T_RPMS
            or RPM_ORDER != _HB03T_RPMS or any(type(r) is not int for r in snapshot.rpm_order)):
        return hold('INVALID_SNAPSHOT', 'RPM_CONTRACT_MISMATCH')
    if type(snapshot.readings) is not tuple or len(snapshot.readings) != 7:
        return hold('INVALID_SNAPSHOT', 'SEVEN_READINGS_REQUIRED')
    if any(type(r) is not DialReading for r in snapshot.readings):
        return hold('INVALID_SNAPSHOT', 'READING_TYPE_INVALID')
    if tuple(r.rpm for r in snapshot.readings) != _HB03T_RPMS:
        return hold('INVALID_SNAPSHOT', 'RPM_ASSOCIATION_INVALID')
    for row in snapshot.readings:
        problem = _reading_problem(row)
        if problem:
            return hold('HOLD_NUMERIC_REPRESENTATION' if problem == 'FLOAT_REPRESENTATION_UNSAFE'
                        else 'INVALID_SNAPSHOT', problem)
    rows = tuple(HBReading(r.rpm, r.raw, r.raw_type, r.dial) for r in snapshot.readings)
    return hold('HOLD_INSTRUMENT_PROVENANCE_UNVERIFIED', 'PHYSICAL_INSTRUMENT_EVIDENCE_MISSING', rows)
