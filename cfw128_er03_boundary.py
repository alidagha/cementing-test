"""C2a: disabled boundary-feasibility HOLD, not an ER03 pressure/flow design.

Reads only captured C1 immutable topology and App fingerprint provenance; writes
nothing. No state, persistence, UI, report, solver, fluid, fitter or dependency
change. Physical ports use m MD; no pressure/rate/volume values are invented.
C1's geometry metadata dependency does not execute frozen chart physics.
Replaying a stale capture (or a coherent counterfeit) cannot establish current
App authority: a future execution boundary must freshly resnapshot App state.
Cropping a return annulus does NOT qualify ER03's surface-referenced two-column
inventory, BP/WHP, freefall, Qout or shut-in BHSP laws for a deep outlet.
"""
from dataclasses import dataclass, field, fields
import math
import re
from typing import Literal

import cfw128_er03_contract as c1
from project_state import fingerprint

_FLAGS = ('enabled', 'ready_to_run', 'hb_admissible', 'hydraulic_admissible',
          'chart_admissible', 'scientifically_qualified')
_UNKNOWN = ('return_outlet_pressure', 'pressure_datum', 'pressure_reference',
            'inlet_outlet_pressure_closure', 'fluid_inventory_transport',
            'mass_volume_conservation', 'qout_rate', 'freefall_tail_interpretation',
            'shutin_bhsp_reference', 'three_chart_labels')
_TYPES = (c1.TopologyPreview, c1.ReturnSection, c1.Section, c1.InstalledString,
          c1.SurveyStation, c1.TVDPoint)


def _immutable(value):
    """Exact typed primitive tree; no mutable or user-defined serializer hooks."""
    if value is None or type(value) in (str, bool, int):
        return (type(value).__name__, value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('NONFINITE_CAPTURE')
        return ('float', value.hex())
    if type(value) is tuple:
        return ('tuple', tuple(_immutable(v) for v in value))
    if type(value) in _TYPES:
        return (type(value).__name__, tuple((f.name, _immutable(getattr(value, f.name)))
                                          for f in fields(value)))
    raise TypeError('Only exact immutable captured C1 types are accepted.')


def _check_preview(p, expected_sha):
    if type(p) is not c1.TopologyPreview:
        raise TypeError('Provide an actual captured TopologyPreview, not a design/state.')
    if type(expected_sha) is not str or not re.fullmatch('[0-9a-f]{40}', expected_sha):
        raise ValueError('Expected App SHA must be externally verified lowercase hex.')
    if p.app_source_sha != expected_sha:
        raise ValueError('APP_SOURCE_SHA_MISMATCH')
    _immutable(p)
    c1.TopologyPreview.__post_init__(p)  # Revalidate even an object.__setattr__ forgery.
    if any(getattr(p, flag) is not False for flag in _FLAGS):
        raise ValueError('UNAUTHORIZED_RELEASE_CLAIM')
    for name in ('source_identity', 'projection_identity', 'upstream_source_identity',
                 'upstream_request_identity'):
        if not re.fullmatch('[0-9a-f]{64}', getattr(p, name)):
            raise ValueError('C1_IDENTITY_INVALID')
    if len(set(p.reason_codes)) != len(p.reason_codes):
        raise ValueError('C1_REASON_IDENTITY_INVALID')
    if p.status in ('SOURCE_INVALID', 'NOT_APPLICABLE', 'INVALID_SNAPSHOT'):
        if (any(getattr(p, name) for name in ('injection_sections', 'enclosing_sections',
                'return_sections', 'installed_strings', 'survey', 'trajectory', 'future_gates'))
                or any(getattr(p, name) is not None for name in ('selected_host', 'receiver',
                'string_top_md', 'shoe_md', 'return_top_md', 'return_bottom_md'))):
            raise ValueError('UNAVAILABLE_SOURCE_CARRIES_GEOMETRY')
        wanted = fingerprint(['cfw128-c1-projection/1', p.source_identity, p.status, p.reason_codes])
        if p.projection_identity != wanted:
            raise ValueError('C1_PROJECTION_IDENTITY_MISMATCH')
        return False
    # Reuse the locked C1 admission/section/host/receiver/trajectory authority.
    # Exact v1 App producer detail is source-proven in the locked adapter.
    # Rebuild its entire C1 identity, not just the return-envelope hash. A
    # changed producer contract must fail closed; this is not authentication.
    detail = 'Source geometry only; all runtime/HB/hydraulic authorizations remain false.'
    source = c1.GeometrySnapshot(p.upstream_status, p.upstream_reason_codes, detail,
        p.app_source_sha, p.upstream_source_identity, p.upstream_request_identity,
        p.job, p.kind, p.target_token, p.host_token, p.string_top_md, p.shoe_md,
        p.injection_sections, p.enclosing_sections, p.installed_strings,
        p.selected_host, p.receiver, p.survey, p.trajectory, p.future_gates)
    rebuilt = c1.prepare_er03_preview(source, expected_app_source_sha=expected_sha)
    if (rebuilt.status not in ('STRUCTURAL_PREVIEW_ONLY', 'HOLD_ENGINE_CONTRACT')
            or p != rebuilt):
        raise ValueError('C1_CAPTURE_STRUCTURE_OR_HOLDS_MISMATCH')
    return True


@dataclass(frozen=True, slots=True)
class PhysicalPort:
    """Location and travel role only; no measured/simulated pressure or flow."""
    name: str
    md_m: float
    leg: Literal['injection', 'annular_return']
    direction: Literal['entry', 'exit']

    def __post_init__(self):
        if (type(self.name) is not str or type(self.md_m) not in (int, float)
                or not math.isfinite(self.md_m) or self.md_m < 0
                or self.leg not in ('injection', 'annular_return')
                or self.direction not in ('entry', 'exit')):
            raise ValueError('Physical ports require finite measured MD and exact roles.')


def _ports(p):
    return (PhysicalPort('Surface injection entry', 0., 'injection', 'entry'),
        PhysicalPort('Active shoe injection exit', p.shoe_md, 'injection', 'exit'),
        PhysicalPort('Active shoe annular return entry', p.shoe_md, 'annular_return', 'entry'),
        PhysicalPort('Tie Back Lap (MD=A)' if p.kind == 'tieback' else 'Surface return exit',
                     p.return_top_md, 'annular_return', 'exit'))


def _reasons(p, captured):
    codes = [*p.reason_codes, 'CAPTURE_ONLY_REQUIRES_FRESH_APP_RESNAPSHOT']
    if not captured:
        codes.append('C1_SOURCE_NOT_READY')
    else:
        codes.extend(('HOLD_PRESSURE_REFERENCE_UNSPECIFIED',
            'HOLD_RETURN_FLOW_AND_INVENTORY_LAW', 'HOLD_SHUTIN_BHSP_REFERENCE'))
        if p.kind == 'tieback':
            codes.extend(('HOLD_PARTIAL_RETURN_PRESSURE_BC', 'HOLD_ER03_SURFACE_UTUBE_MODEL'))
            if p.string_top_md == 0.:
                codes.append('HOLD_TIEBACK_POINT_A_ZERO_TYPED_INTERFACE')
        if p.survey:
            codes.append('HOLD_DIRECTIONAL_INTERIOR_TVD')
        if (set(p.reason_codes) & {'SEGMENTED_ENCLOSURE', 'HOST_NOT_FULL_PATH',
                'SEGMENTED_DRILL_PIPE', 'SEGMENTED_TIEBACK_BODY'}
                or any(len(v) > 1 for v in (p.injection_sections, p.enclosing_sections))
                or any(len(s.sections) > 1 for s in p.installed_strings)):
            codes.append('HOLD_SEGMENTED_GEOMETRY_INTERFACE')
    return tuple(dict.fromkeys(codes))


def _identity(p, sha, status, codes):
    return fingerprint(['cfw128-c2a-boundary/1', sha, _immutable(p), status, codes,
                        'ports-only-not-numerical-boundary', _UNKNOWN])


@dataclass(frozen=True, slots=True)
class BoundaryHold:
    status: Literal['SOURCE_NOT_READY', 'HOLD_ENGINE_BOUNDARY_UNVERIFIED']
    reason_codes: tuple[str, ...]
    preview: c1.TopologyPreview
    expected_app_source_sha: str
    projection_identity: str
    physical_ports: tuple[PhysicalPort, ...]
    return_outlet_pressure: Literal['UNSPECIFIED'] = field(default='UNSPECIFIED', init=False)
    pressure_datum: Literal['UNSPECIFIED'] = field(default='UNSPECIFIED', init=False)
    pressure_reference: Literal['UNSPECIFIED'] = field(default='UNSPECIFIED', init=False)
    inlet_outlet_pressure_closure: Literal['NOT_EVALUATED'] = field(default='NOT_EVALUATED', init=False)
    fluid_inventory_transport: Literal['NOT_EVALUATED'] = field(default='NOT_EVALUATED', init=False)
    mass_volume_conservation: Literal['NOT_EVALUATED'] = field(default='NOT_EVALUATED', init=False)
    qout_rate: Literal['NOT_EVALUATED'] = field(default='NOT_EVALUATED', init=False)
    freefall_tail_interpretation: Literal['NOT_EVALUATED'] = field(default='NOT_EVALUATED', init=False)
    shutin_bhsp_reference: Literal['NOT_EVALUATED'] = field(default='NOT_EVALUATED', init=False)
    three_chart_labels: Literal['NOT_EVALUATED'] = field(default='NOT_EVALUATED', init=False)
    instrument_provenance: Literal['UNVERIFIED'] = field(default='UNVERIFIED', init=False)
    enabled: Literal[False] = field(default=False, init=False)
    ready_to_run: Literal[False] = field(default=False, init=False)
    hb_admissible: Literal[False] = field(default=False, init=False)
    hydraulic_admissible: Literal[False] = field(default=False, init=False)
    chart_admissible: Literal[False] = field(default=False, init=False)
    scientifically_qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self):
        captured = _check_preview(self.preview, self.expected_app_source_sha)
        status = 'HOLD_ENGINE_BOUNDARY_UNVERIFIED' if captured else 'SOURCE_NOT_READY'
        codes = _reasons(self.preview, captured)
        ports = _ports(self.preview) if captured else ()
        if (self.status != status or type(self.reason_codes) is not tuple or self.reason_codes != codes
                or type(self.physical_ports) is not tuple
                or any(type(v) is not PhysicalPort for v in self.physical_ports)
                or self.physical_ports != ports
                or self.projection_identity != _identity(self.preview, self.expected_app_source_sha, status, codes)):
            raise ValueError('Boundary hold provenance, ports or mandatory holds differ.')
        for port in self.physical_ports:
            PhysicalPort.__post_init__(port)
        if (any(getattr(self, flag) is not False for flag in _FLAGS)
                or self.instrument_provenance != 'UNVERIFIED'
                or any(getattr(self, name) != ('UNSPECIFIED' if name in _UNKNOWN[:3]
                                              else 'NOT_EVALUATED') for name in _UNKNOWN)):
            raise ValueError('Numerical/release authority cannot be assigned by this hold.')

    @property
    def qout_location_only(self):
        return self.physical_ports[-1] if self.physical_ports else None


def assess_er03_boundary(preview: c1.TopologyPreview, *, expected_app_source_sha: str) -> BoundaryHold:
    """Capture physical ports and unresolved laws; never qualify physics/currentness."""
    captured = _check_preview(preview, expected_app_source_sha)
    status = 'HOLD_ENGINE_BOUNDARY_UNVERIFIED' if captured else 'SOURCE_NOT_READY'
    codes = _reasons(preview, captured)
    return BoundaryHold(status, codes, preview, expected_app_source_sha,
        _identity(preview, expected_app_source_sha, status, codes), _ports(preview) if captured else ())
