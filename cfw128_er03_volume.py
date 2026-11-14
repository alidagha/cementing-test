"""C2b: disabled nominal geometric-capacity audit, not a hydraulic inventory.

Reads an exact immutable C2a hold and canonical App _capacity; writes nothing.
No fluids, stage transport, pressure, flow, conservation, solver, fit, UI, Word,
persistence or dependency change. MD lengths (not TVD) multiply bbl/m capacity.
Injection and return are disjoint fluid spaces; unequal capacities are NOT a
leak or Qout mismatch. No excess, compressibility or historical receiver volume.
Captured provenance cannot authenticate a coherent counterfeit or stale capture:
a future execution boundary must freshly resnapshot App sources independently.
"""
from dataclasses import dataclass, field, fields
import math
from typing import Literal

from cfw128_er03_boundary import BoundaryHold, PhysicalPort, assess_er03_boundary
from cement_chart_model import _capacity
from project_state import fingerprint

_METHOD = 'app._capacity.nominal-in2-ft-m-bbl/1'
_UNITS = ('MD:m', 'diameter:in', 'capacity:bbl/m', 'geometric_volume:bbl')
_FLAGS = ('enabled', 'ready_to_run', 'hb_admissible', 'hydraulic_admissible',
          'chart_admissible', 'scientifically_qualified')


def _finite(v):
    return type(v) in (int, float) and math.isfinite(v)


def _rows(values, optional=False):
    if (type(values) is not tuple or (not values and not optional)
            or any(type(v) is not int or v < 0 for v in values)
            or len(set(values)) != len(values)):
        raise ValueError('Section provenance requires exact positional source rows.')


@dataclass(frozen=True, slots=True)
class CapacitySection:
    leg: Literal['injection', 'annular_return']
    top_md: float
    bottom_md: float
    running_source_rows: tuple[int, ...]
    wall_source_rows: tuple[int, ...]
    inner_diameter_in: float
    outer_diameter_in: float
    nominal_capacity_bbl_per_m: float
    nominal_section_volume_bbl: float

    def __post_init__(self):
        if (type(self.leg) is not str or self.leg not in ('injection', 'annular_return')
                or not all(_finite(getattr(self, name)) for name in ('top_md', 'bottom_md',
                    'inner_diameter_in', 'outer_diameter_in', 'nominal_capacity_bbl_per_m',
                    'nominal_section_volume_bbl'))
                or not 0 <= self.top_md < self.bottom_md
                or not 0 <= self.inner_diameter_in < self.outer_diameter_in):
            raise ValueError('Capacity sections require finite nominal measured bounds/diameters.')
        _rows(self.running_source_rows)
        _rows(self.wall_source_rows, optional=self.leg == 'injection')
        if ((self.leg == 'injection' and (self.inner_diameter_in != 0 or self.wall_source_rows))
                or (self.leg == 'annular_return' and self.inner_diameter_in <= 0)):
            raise ValueError('Pipe bore and annular capacity roles must remain distinct.')
        capacity = _capacity(self.outer_diameter_in, self.inner_diameter_in)
        volume = capacity * (self.bottom_md-self.top_md)
        if (not math.isfinite(capacity) or capacity <= 0 or not math.isfinite(volume) or volume < 0
                or self.nominal_capacity_bbl_per_m != capacity
                or self.nominal_section_volume_bbl != volume):
            raise ValueError('Nominal capacity/volume differs from the canonical App geometry method.')


def _check_boundary(boundary, sha):
    if type(boundary) is not BoundaryHold:
        raise TypeError('Provide the exact captured C2a BoundaryHold.')
    if any(type(getattr(boundary, n)) is not str for n in
           ('status', 'projection_identity', 'expected_app_source_sha', 'instrument_provenance')):
        raise TypeError('Boundary metadata must be primitive strings.')
    for f in fields(boundary):
        if f.name in ('preview', 'physical_ports'):
            continue
        value = getattr(boundary, f.name)
        if type(value) not in (str, bool, tuple) or (type(value) is tuple
                and any(type(v) is not str for v in value)):
            raise TypeError('Boundary metadata must remain immutable primitives.')
    if (type(boundary.physical_ports) is not tuple
            or any(type(v) is not PhysicalPort for v in boundary.physical_ports)):
        raise TypeError('Boundary ports must be exact immutable typed tuples.')
    for port in boundary.physical_ports:
        if any(type(getattr(port, n)) is not str for n in ('name', 'leg', 'direction')):
            raise TypeError('Physical port roles must remain primitive strings.')
    BoundaryHold.__post_init__(boundary)
    rebuilt = assess_er03_boundary(boundary.preview, expected_app_source_sha=sha)
    if boundary != rebuilt:
        raise ValueError('C2a captured boundary/provenance differs from the verified hold.')
    return boundary.status != 'SOURCE_NOT_READY'


def _sections(boundary):
    p = boundary.preview
    result = []
    for run in p.injection_sections:
        cap = _capacity(run.id_in, 0.)
        result.append(CapacitySection('injection', run.top_md, run.bottom_md,
            run.source_rows, (), 0., run.id_in, cap, cap*(run.bottom_md-run.top_md)))
    for part in p.return_sections:
        wall, run = part.wall, part.running
        outer = wall.od_in if wall.description == 'Open Hole Size' else wall.id_in
        cap = _capacity(outer, run.od_in)
        result.append(CapacitySection('annular_return', part.top_md, part.bottom_md,
            run.source_rows, wall.source_rows, run.od_in, outer, cap,
            cap*(part.bottom_md-part.top_md)))
    # Check each exact envelope independently; never equate the two capacities.
    for leg, top in (('injection', 0.), ('annular_return', p.return_top_md)):
        cursor = top
        parts = [v for v in result if v.leg == leg]
        if not parts:
            raise ValueError('A structurally captured leg cannot have missing sections.')
        for part in parts:
            if part.top_md != cursor:
                raise ValueError('Capacity leg has a gap, overlap or wrong source order.')
            cursor = part.bottom_md
        if cursor != p.shoe_md:
            raise ValueError('Capacity leg differs from the current active Shoe.')
    return tuple(result)


def _encoded(v):
    if v is None or type(v) is str:
        return (type(v).__name__, v)
    if type(v) is int:
        return ('int', hex(v))
    if type(v) is float and math.isfinite(v):
        return ('float', v.hex())
    if type(v) is tuple:
        return ('tuple', tuple(_encoded(x) for x in v))
    raise TypeError('Only immutable finite primitive capacity provenance is accepted.')


def _identity(boundary, sha, status, reasons, sections, injection, annular):
    return fingerprint(['cfw128-c2b-capacity/1', boundary.projection_identity, sha,
        _METHOD, _UNITS, status, reasons,
        tuple(tuple((f.name, _encoded(getattr(s, f.name))) for f in fields(s)) for s in sections),
        _encoded(injection), _encoded(annular)])


@dataclass(frozen=True, slots=True)
class FrozenCapacityAudit:
    status: Literal['HOLD_GEOMETRIC_CAPACITY_ONLY', 'SOURCE_NOT_READY']
    reason_codes: tuple[str, ...]
    boundary: BoundaryHold
    expected_app_source_sha: str
    boundary_projection_identity: str
    projection_identity: str
    sections: tuple[CapacitySection, ...]
    nominal_injection_volume_bbl: float | None
    nominal_annular_return_volume_bbl: float | None
    method_id: str = field(default=_METHOD, init=False)
    units: tuple[str, ...] = field(default=_UNITS, init=False)
    instrument_provenance: Literal['UNVERIFIED'] = field(default='UNVERIFIED', init=False)
    enabled: Literal[False] = field(default=False, init=False)
    ready_to_run: Literal[False] = field(default=False, init=False)
    hb_admissible: Literal[False] = field(default=False, init=False)
    hydraulic_admissible: Literal[False] = field(default=False, init=False)
    chart_admissible: Literal[False] = field(default=False, init=False)
    scientifically_qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self):
        if any(type(getattr(self, n)) is not str for n in ('status', 'expected_app_source_sha',
                'boundary_projection_identity', 'projection_identity', 'method_id', 'instrument_provenance')):
            raise TypeError('Capacity metadata must be primitive strings.')
        captured = _check_boundary(self.boundary, self.expected_app_source_sha)
        status, reasons, sections, injection, annular = _projection(self.boundary, captured)
        if type(self.sections) is not tuple or any(type(s) is not CapacitySection for s in self.sections):
            raise TypeError('Capacity payload must be an immutable tuple of exact sections.')
        for s in self.sections:
            CapacitySection.__post_init__(s)
        for v in (self.nominal_injection_volume_bbl, self.nominal_annular_return_volume_bbl):
            if v is not None and (not _finite(v) or v < 0):
                raise ValueError('Geometric totals must be finite nominal values, never booleans.')
        if (type(self.reason_codes) is not tuple or any(type(v) is not str for v in self.reason_codes)
                or type(self.units) is not tuple or any(type(v) is not str for v in self.units)):
            raise TypeError('Receipt reasons/units must be immutable primitive strings.')
        if (self.status != status or self.reason_codes != reasons
                or self.boundary_projection_identity != self.boundary.projection_identity
                or self.sections != sections or self.nominal_injection_volume_bbl != injection
                or self.nominal_annular_return_volume_bbl != annular
                or self.method_id != _METHOD or type(self.units) is not tuple or self.units != _UNITS
                or self.instrument_provenance != 'UNVERIFIED'
                or any(getattr(self, flag) is not False for flag in _FLAGS)
                or self.projection_identity != _identity(self.boundary, self.expected_app_source_sha,
                                                        status, reasons, sections, injection, annular)):
            raise ValueError('Capacity receipt differs from its held measured geometric source.')


def _projection(boundary, captured):
    reasons = (*boundary.reason_codes, 'NOMINAL_GEOMETRY_ONLY_NOT_FLUID_CONTENT')
    if not captured:
        return 'SOURCE_NOT_READY', reasons, (), None, None
    parts = _sections(boundary)
    injection = sum(s.nominal_section_volume_bbl for s in parts if s.leg == 'injection')
    annular = sum(s.nominal_section_volume_bbl for s in parts if s.leg == 'annular_return')
    return 'HOLD_GEOMETRIC_CAPACITY_ONLY', reasons, parts, injection, annular


def audit_geometric_capacity(boundary: BoundaryHold, *, expected_app_source_sha: str) -> FrozenCapacityAudit:
    """Nominal contained geometric capacities only; no dynamic fluid/pressure result."""
    captured = _check_boundary(boundary, expected_app_source_sha)
    status, reasons, sections, injection, annular = _projection(boundary, captured)
    return FrozenCapacityAudit(status, reasons, boundary, expected_app_source_sha,
        boundary.projection_identity, _identity(boundary, expected_app_source_sha,
            status, reasons, sections, injection, annular), sections, injection, annular)
