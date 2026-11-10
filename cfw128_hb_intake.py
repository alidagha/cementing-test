"""B1: disabled, read-only intake of current Phase VII bhct_down source.

Reads selected cement-formulation QC/grid/formulation/signatures and eligibility;
Writes: none. Authorities: materials_db, project_state lab_source_signature /
phase7_lab_fluids / fingerprint, engineering_tools lab_review_signature and mass
validation, rheology.RPM_ORDER. No persisted schema, UI, Word, dependency, HB,
Bingham fit, physics or production caller. Instrument identity is UNVERIFIED.

Dials accept built-in int/finite integer-valued float, or stripped decimal text
matching -?[0-9]+(.[0-9]+)? with nonnegative integer value. Raw text/type remain
unchanged; exponent/expressions/bools/fractions are rejected, never rounded.
RPMs are exact canonical string keys; their insertion order is NOT measurement
order (App JSON sorts keys). Output uses RPM_ORDER by key association. Duplicate
raw JSON keys belong to project_io's existing rejection boundary; sequences or
colliding/noncanonical RPM keys are not repaired here. No instrument is inferred
from workflow review or from the software's Fann35/R1B1/Spring1.0 convention.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
import math
import re
from typing import Literal

import pandas as pd
import materials_db
from engineering_tools import lab_review_signature, validate_lab_masses
from project_state import fingerprint, lab_source_signature, phase7_lab_fluids
from rheology import RPM_ORDER, RHEOLOGY_DATASETS


@dataclass(frozen=True, slots=True)
class DialReading:
    rpm: int
    raw: str | int | float
    raw_type: str
    dial: int


@dataclass(frozen=True, slots=True)
class LabIntakeSnapshot:
    status: Literal['NOT_AVAILABLE', 'NOT_APPLICABLE', 'NOT_SELECTED', 'INCOMPLETE_INPUT',
                    'INVALID_INPUT', 'REVIEW_REQUIRED', 'STALE_REVIEW', 'CAPTURED_FOR_FUTURE_REVIEW']
    reason_codes: tuple[str, ...]
    detail: str
    fluid_name: str
    app_source_sha: str
    source_identity: str
    request_identity: str
    readings: tuple[DialReading, ...] = ()
    material_name: str | None = None
    formulation_signature: str | None = None
    review_signature: str | None = None
    dataset: Literal['bhct_down'] = field(default='bhct_down', init=False)
    rpm_order: tuple[int, ...] = field(default=RPM_ORDER, init=False)
    instrument_provenance: Literal['UNVERIFIED'] = field(default='UNVERIFIED', init=False)
    enabled: Literal[False] = field(default=False, init=False)
    fit_admissible: Literal[False] = field(default=False, init=False)
    ready_to_run: Literal[False] = field(default=False, init=False)
    chart_admissible: Literal[False] = field(default=False, init=False)
    hydraulic_admissible: Literal[False] = field(default=False, init=False)
    scientifically_qualified: Literal[False] = field(default=False, init=False)


def _positional_source(value):
    """A-C1-identical positional encoding for ambiguous frames/raw-type annotations.

    The existing geometry isolation contract forbids importing its module here.
    AST parity tests retain that encoding; fingerprint itself remains App-owned.
    """
    if isinstance(value, pd.DataFrame):
        return ('frame', _positional_source(tuple(value.columns)),
                _positional_source(tuple(value.index)),
                tuple(str(dtype) for dtype in value.dtypes),
                tuple(tuple(_positional_source(cell) for cell in row)
                      for row in value.itertuples(index=False, name=None)))
    if (hasattr(value, 'shape') and hasattr(value, 'tolist')
            and (value.shape or type(value).__name__ == 'ndarray')):
        # Avoid truncated NumPy array repr hiding positional values in malformed cells.
        return ('array', type(value).__module__ + '.' + type(value).__qualname__,
                str(value.dtype), _positional_source(value.shape), _positional_source(value.tolist()))
    if isinstance(value, Mapping):
        return ('mapping', tuple(sorted(((_positional_source(k), _positional_source(v))
                                        for k, v in value.items()), key=repr)))
    if isinstance(value, (tuple, list)):
        return (type(value).__name__, tuple(_positional_source(v) for v in value))
    return (type(value).__module__ + '.' + type(value).__qualname__, repr(value))




def _duplicate_columns(value):
    if isinstance(value, pd.DataFrame):
        return not value.columns.is_unique
    if isinstance(value, Mapping):
        return any(_duplicate_columns(v) for v in value.values())
    if isinstance(value, (tuple, list)):
        return any(_duplicate_columns(v) for v in value)
    return False


def _dial(raw):
    if raw is None or isinstance(raw, str) and not raw.strip():
        return None, 'DIAL_MISSING'
    if isinstance(raw, bool):
        return None, 'DIAL_BOOLEAN'
    if type(raw) not in (str, int, float):
        return None, 'DIAL_TYPE'
    if isinstance(raw, str):
        text = raw.strip()
        if text.lower() in ('nan', 'inf', '+inf', '-inf', 'infinity', '+infinity', '-infinity'):
            return None, 'DIAL_NONFINITE'
        if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', text):
            return None, 'DIAL_SYNTAX'
        value = Decimal(text)  # Exact decimal check; no float truncation or fractional rounding.
    else:
        if isinstance(raw, float) and not math.isfinite(raw):
            return None, 'DIAL_NONFINITE'
        value = raw
    if value < 0:
        return None, 'DIAL_NEGATIVE'
    if value != int(value):
        return None, 'DIAL_FRACTIONAL'
    return int(value), None


def snapshot_lab_intake(state: Mapping, fluid_name: str, *, app_source_sha: str) -> LabIntakeSnapshot:
    """Capture current reviewed source only; every numerical/release gate is false.

    Caller verifies app_source_sha externally. No state refresh/review repair is
    permitted. Existing fingerprint remains the identity authority; an explicit
    raw-type annotation preserves source text/type despite canonical int/float
    equivalence. Duplicate frames use A-C1's positional invalid-input projection.
    """
    if not isinstance(state, Mapping) or not isinstance(fluid_name, str):
        raise ValueError('Provide an App state mapping and exact fluid-name string.')
    if not isinstance(app_source_sha, str) or not re.fullmatch('[0-9a-f]{40}', app_source_sha):
        raise ValueError('app_source_sha must be an externally verified 40-character Git SHA.')
    source = deepcopy({k: state[k] for k in ('job_type','well_data','mud_type',
                      'material_property_schema','bhct','bhst') if k in state})
    config = state.get('fluids_config', {})
    source['fluids_config'] = deepcopy({'active':config.get('active', [])} if isinstance(config, dict) else config)
    for key in ('cement_params','fluid_data','cement_additives_dfs','lab_qc_params','lab_grid_dfs','lab_source_signatures'):
        record = state.get(key, {})
        source[key] = deepcopy({fluid_name:record[fluid_name]} if isinstance(record, dict) and fluid_name in record
                               else {} if isinstance(record, dict) else record)
    qc_record = source['lab_qc_params']
    qc = qc_record.get(fluid_name) if isinstance(qc_record, dict) else None
    rheology = qc.get('rheology') if isinstance(qc, dict) else None
    row = rheology.get('bhct_down') if isinstance(rheology, dict) else None
    readings = row.get('readings') if isinstance(row, dict) else None
    duplicate = _duplicate_columns(source)
    source_id = fingerprint([1, 'cfw128-b1-source', _positional_source(source) if duplicate else source,
                             _positional_source(readings)])
    request_id = fingerprint([1, app_source_sha, fluid_name, source_id])

    def hold(status, code, detail):
        return LabIntakeSnapshot(status, (code,), detail, fluid_name, app_source_sha, source_id, request_id)

    if duplicate:
        return hold('INVALID_INPUT','DUPLICATE_SOURCE_COLUMNS','Ambiguous source columns; every positional value is retained in invalid identity.')
    if fluid_name in ('Mud','Displacement Fluid'):
        return hold('NOT_AVAILABLE','NO_NATIVE_PHASE7_SEVEN_RPM_SOURCE','Mud/Displacement has no native Phase VII seven-Fann source; PV/YP is not a substitute.')
    if fluid_name in materials_db.RHEOLOGY_ONLY_FLUIDS:
        return hold('NOT_AVAILABLE','UNSUPPORTED_RHEOLOGY_ONLY_FLUID','B1 does not admit Diesel/Pre Flush as reviewed formulation sources.')
    if fluid_name == 'Spacer':
        return hold('NOT_AVAILABLE','UNSUPPORTED_SPACER_SOURCE','Standalone Spacer coverage needs a separate approved source contract.')
    if fluid_name not in materials_db.CEMENT_FORMULATION_FLUIDS:
        return hold('NOT_AVAILABLE','UNSUPPORTED_FLUID_STAGE' if fluid_name in materials_db.FLUID_TYPES else 'UNSUPPORTED_FLUID',
                    'No B1 cement-formulation intake authority for this fluid.')
    config = source['fluids_config']
    if not isinstance(config, dict) or not isinstance(config.get('active'), list) or any(not isinstance(v,str) for v in config['active']):
        return hold('INVALID_INPUT','ACTIVE_FLUIDS_INVALID','Active-fluid selection must be a canonical list.')
    if fluid_name not in config['active']:
        return hold('NOT_APPLICABLE','FLUID_NOT_ACTIVE','No active selection for this formulation fluid.')
    if config['active'].count(fluid_name) != 1:
        return hold('INVALID_INPUT','ACTIVE_FLUIDS_INVALID','Repeated fluid selection is ambiguous.')
    if source.get('well_data') is not None and not isinstance(source['well_data'], dict):
        return hold('INVALID_INPUT','LAB_SOURCE_INVALID','well_data must be a canonical record.')
    if fluid_name not in phase7_lab_fluids(source):
        return hold('NOT_APPLICABLE','FLUID_NOT_ELIGIBLE','Fluid is not eligible for the current job/Mud selection.')
    if qc is None:
        return hold('INCOMPLETE_INPUT','LAB_SOURCE_MISSING','Open Phase VII and provide measured lab source.')
    if isinstance(qc, dict) and rheology is None:
        return hold('INCOMPLETE_INPUT','RHEOLOGY_SOURCE_MISSING','No committed rheology source exists in this lab draft.')
    if isinstance(rheology, dict) and set(rheology) - {key for key, _ in RHEOLOGY_DATASETS}:
        return hold('INVALID_INPUT','RHEOLOGY_KEYS_INVALID','Unknown ramp keys are not BHCT Ramp-Down source.')
    if not isinstance(qc, dict) or not isinstance(rheology, dict) or row is not None and not isinstance(row, dict):
        return hold('INVALID_INPUT','RHEOLOGY_RECORD_INVALID','Canonical QC/rheology/dataset records are required.')
    if row is None or row.get('selected') is False:
        return hold('NOT_SELECTED','BHCT_DOWN_NOT_SELECTED','Only explicitly selected BHCT Ramp-Down is admitted; other ramps are not substitutes.')
    if row.get('selected') is not True:
        return hold('INVALID_INPUT','SELECTION_INVALID','Rheology selection must be literal True/False.')
    if set(row) - {'selected','readings','gel_10_sec','gel_10_min'}:
        return hold('INVALID_INPUT','DATASET_KEYS_INVALID','Unexpected dataset keys are not an instrument/source authority.')
    if not isinstance(readings, dict):
        return hold('INVALID_INPUT','RPM_RECORD_INVALID','Seven values must be an exact canonical RPM-keyed mapping, not positional pairs.')
    keys = tuple(readings)
    if len(tuple(readings.items())) != len(keys):
        return hold('INVALID_INPUT','RPM_KEYS_INVALID','Duplicated RPM entries are ambiguous.')
    expected = {str(r) for r in RPM_ORDER}
    if any(type(k) is not str or k not in expected for k in keys):
        return hold('INVALID_INPUT','RPM_KEYS_INVALID','Unexpected/colliding RPM keys are not normalized or silently selected.')
    if set(keys) != expected:
        return hold('INCOMPLETE_INPUT','RPM_MISSING','All seven actual RPM entries are required.')
    captured = []
    for rpm in RPM_ORDER:
        raw = readings[str(rpm)]
        try:
            dial, problem = _dial(raw)
        except (ValueError, OverflowError):
            dial, problem = None, 'DIAL_INVALID'
        if problem:
            return hold('INCOMPLETE_INPUT' if problem == 'DIAL_MISSING' else 'INVALID_INPUT',problem,f'{rpm} RPM source is not an intact nonnegative integer dial.')
        captured.append(DialReading(rpm, raw, type(raw).__name__, dial))
    grids = source['lab_grid_dfs']
    grid = grids.get(fluid_name) if isinstance(grids, dict) else None
    if not isinstance(grid, pd.DataFrame) or grid.empty:
        return hold('INCOMPLETE_INPUT','LAB_GRID_MISSING','Committed lab formulation rows are required.')
    if list(grid.columns) != ['Material','Concentration','Unit','Mass','Lot No']:
        return hold('INVALID_INPUT','LAB_GRID_INVALID','Lab grid must retain canonical fields and order.')
    try:
        for _, grid_row in grid.iterrows():
            if any(pd.isna(grid_row[k]) or not str(grid_row[k]).strip() for k in ('Material','Concentration','Unit','Mass')):
                return hold('INCOMPLETE_INPUT','LAB_GRID_INCOMPLETE','Incomplete measured lab formulation rows.')
        validate_lab_masses(grid)
        if any(not isinstance(source[k],dict) for k in ('cement_params','fluid_data','cement_additives_dfs','lab_source_signatures')):
            raise ValueError('Canonical formulation/signature records are required.')
        current = lab_source_signature(source,fluid_name)
    except (ValueError, TypeError, AttributeError):
        return hold('INVALID_INPUT','LAB_SOURCE_INVALID','Invalid committed formulation/grid source; it was not refreshed.')
    if source['lab_source_signatures'].get(fluid_name) != current:
        return hold('STALE_REVIEW','FORMULATION_SIGNATURE_MISMATCH','Stored lab source no longer matches current formulation/well inputs.')
    if qc.get('reviewed') is not True:
        return hold('REVIEW_REQUIRED','LAB_NOT_REVIEWED','An operator must confirm actual measured lab values.')
    try:
        review = lab_review_signature(qc,grid)
    except (ValueError, TypeError):
        return hold('INVALID_INPUT','LAB_REVIEW_INVALID','QC/grid cannot establish an intact operator review.')
    if qc.get('review_signature') != review:
        return hold('STALE_REVIEW','REVIEW_SIGNATURE_MISMATCH','QC/readings/grid were edited after the operator review.')
    params = source['cement_params'].get(fluid_name, {})
    material = params.get('base_cement') if isinstance(params, dict) else None
    return LabIntakeSnapshot('CAPTURED_FOR_FUTURE_REVIEW',
        ('INTACT_REVIEWED_BHCT_DOWN_SOURCE','INSTRUMENT_PROVENANCE_UNVERIFIED'),
        'Source captured only; physical instrument evidence and all fitting/release gates remain unresolved.',
        fluid_name, app_source_sha, source_id, request_id, tuple(captured),
        material if isinstance(material,str) else None, current, review)
