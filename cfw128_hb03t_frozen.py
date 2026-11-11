#!/usr/bin/env python3
"""
hb_full_fitter_standalone_v1_hb03t.py — CFW128 standalone Full Herschel–Bulkley fitter
=======================================================================================
Derivative versioned source. HB-03T public module-gate lock batch, 2026-11-08.
Executor: GLM. Work order: CFW128_GLM_HB03T_PUBLIC_GATE_LOCK (HB-03T).
Immediate parent: the SHA-pinned HB-03S derivative
SOURCE_OF_RECORD/hb_full_fitter_standalone_v1_hb03s_PINNED.py,
SHA-256 6802f2383e3c5566648f5d68f781142b6ee5ec634cefdbd3cddf6cc75a1ad351
(frozen evidence ZIP b03de6528124093c411344248ea81398ca9ef4da2be18ea0b5ff0c16ca3fda63).

LINEAGE (anchored derivative — the archived fitter is NOT modified in place)
  Immediate parent : "NLS-HB-generic-v2.1-standalone/typed-intake/2026-11-08",
                     hb_full_fitter_standalone_v1.py of the HB-03 evidence
                     archive of record, SHA-256
                     da5e2fc308795c4488f15564471ae64bd8c0d36e3ba7c8a8047fbaafb839d8da
  Grandparent      : hb_nls_fit_v2.py, method id
                     "NLS-HB-generic-v2/unweighted-tau-space/2026-11-03",
                     SHA-256 8b7f61049103931df26e29d0dc57a0c9d6ae86229dfb8218130f3b869639ce25
                     (byte-frozen archived baseline, HB-01 evidence).
  This derivative  : "NLS-HB-generic-v2.2-standalone/typed-intake-contract-repair/2026-11-08"
  HB-03R changes   : (1) consumer admission semantics repaired —
                     bhct_down_dataset_eligible (input routing/metadata) is
                     separated from scientifically_qualified_for_hydraulic_charts
                     (hard False while L1/L3 are missing; True is
                     UNREPRESENTABLE at the type level via __post_init__);
                     chart_lane_admissible is now the AND of the two and is
                     therefore always False on any scientific hold. The
                     original fail-open (chart_lane_admissible=True on a
                     reviewed bhct_down OK fit while the scientific hold is
                     active) is closed. No new fit_full_hb parameter exists —
                     no user flag can grant qualification.
                     (2) intake provenance repaired — entry_type is classified
                     from the PRE-conversion validated raw dials: genuine
                     Python ints -> "int"; float-valued integral entries ->
                     "float_integral"; mixed -> "float_integral"; fractional
                     -> NONINTEGER_DIAL_ENTRY. The float conversion feeding
                     the numerics is unchanged, so SI conversion and all fit
                     results are bit-identical to the parent (EQV-proven).
                     (3) report-only active-bound diagnostics —
                     bound_hit_diagnostics() and the active_bound_hit /
                     bound_hit_params / bound_hit_tolerances result fields
                     report ACTUAL hits against the frozen bounds (tau_y, K
                     in [0, 10*max_tau]; n in [0.01, 1.5]) with documented
                     scale-aware tolerances. At an active bound the interior
                     (J^T J)^-1 covariance/correlation is flagged
                     interior_assumption_valid=False. Diagnostics never
                     change status or gates. NOTE: the archived
                     1.999999999999999 value is tau_y (near the synthetic
                     true 2.0 Pa, ~243 Pa below its 245.3 Pa upper bound) —
                     NOT an n bound defect; bounds are NOT widened.
  HB-03S changes   : (4) final authorization lock (consumer-invariant repair
                     of the HB-03R post-construction mutation path) —
                     scientifically_qualified_for_hydraulic_charts and
                     chart_lane_admissible are NO LONGER instance state:
                     they are read-only properties derived from the
                     module-level hard gate SCIENTIFIC_QUALIFICATION_GATE
                     (False while L1/L3 are missing) and the eligibility
                     field. Ordinary attribute assignment, constructor
                     keywords, dataclasses.replace/clone, copy/pickle and
                     to_dict()/CLI JSON cannot represent or promote a True
                     authorization state; to_dict() serializes from the
                     authoritative gate with every archived key preserved in
                     the archived order. contract_version is bumped to
                     hb-fit-contract/1.2.0-hb03s. METHOD_ID is INTENTIONALLY
                     UNCHANGED: the numerical method is untouched, so
                     determinism_receipts stay bit-identical to HB-03R.
                     Scope: consumer authorization invariants only — NOT a
                     numeric fit change, and NOT a claim of security against
                     hostile same-process reflection or source monkeypatching.
  HB-03T changes   : (5) public module-gate lock (Owner-authorized final gate
                     correction of the residual HB-03S defect) — the
                     read-only authorization properties and every
                     to_dict()/CLI JSON serialization path now hold LITERAL
                     False while the L1/L3 scientific hold is active and
                     read NO module attribute: no public module variable, no
                     environment flag and no input parameter can promote
                     scientifically_qualified_for_hydraulic_charts or
                     chart_lane_admissible on any result, including results
                     created BEFORE an attempted reassignment of any exported
                     module variable (an ordinary module-level assignment
                     module.SCIENTIFIC_QUALIFICATION_GATE = True can no
                     longer change any authorization state or serialized
                     field). The former publicly assignable
                     SCIENTIFIC_QUALIFICATION_GATE constant is retained for
                     interface continuity ONLY: its value stays part of the
                     frozen unqualified-release state (False) and ordinary
                     module-level reassignment/deletion of it is refused
                     (AttributeError) by a module-class lock defined at the
                     end of this file. contract_version is bumped to
                     hb-fit-contract/1.3.0-hb03t. METHOD_ID is INTENTIONALLY
                     UNCHANGED: the numerical method is untouched, so
                     determinism_receipts stay bit-identical to HB-03R.
                     Scope: consumer authorization invariants only — NOT a
                     numeric fit change, and NOT a claim of security against
                     hostile same-process reflection, class-object tampering
                     or source monkeypatching.
  Inherited (v2.1) : typed fail-closed Owner-lab intake implementing the
                     frozen HB-02A integer-dial contract (integers only, no
                     rounding anywhere, NONINTEGER_DIAL_ENTRY for fractional
                     entries); strict instrument/ramp gate (Fann 35 R1B1
                     Spring-1.0 only; anything else fails closed pending a
                     validated conversion); honest diagnostics carried on
                     every OK result (Jacobian condition number, joint
                     parameter correlation from (J^T J)^-1, covariance per
                     UNIT relative stress sigma — sigma stays UNDECLARED,
                     no absolute confidence interval is ever produced);
                     preregistered decision policy for ambiguous fits;
                     single engine-boundary adapter (tau_y Pa ->
                     lbf/100ft^2, exactly once, K and n untouched);
                     L2 +/-1 integer-dial scenario runner (deterministic
                     mechanics only, never an executed HB-02A protocol, never
                     an uncertainty product).
  Numeric core     : IDENTICAL algorithm to the archived baseline —
                     scipy.optimize.least_squares (TRF), xtol=ftol=gtol=1e-15,
                     deterministic 4x3x5=60 multistart (erratum E-01: the
                     archived docstring's "24-point" label is wrong; 60 is
                     authoritative), identical loop order, bounds and
                     first-encountered tie-break. Behavior equivalence is
                     pinned bit-for-bit by the HB-03 BEQ test and re-pinned
                     by the HB-03R EQV lane. Sixty multistarts do NOT
                     mathematically guarantee a global minimum on every
                     nonlinear inverse problem.

NOT CLAIMED BY THIS MODULE
  * No scientific or production qualification. The HB-01 S3 noise
    identifiability FAIL (1% relative stress noise, 25 seeds x 6 triples,
    median tau_y error 8.3-94%) is a property of the 7-point/3-parameter
    inverse problem and is RETAINED verbatim; convergence does not resolve it.
  * No CemCADE native-method identity (METHOD_NOT_IDENTIFIABLE stands).
  * No App/GitHub/engine/UI/renderer/Word contact; this file is standalone.
  * No PV/YP-to-HB conversion, no Bingham fallback, no two-parameter model,
    no hydrostatic fallback, no gel-value fitting, no silent anything.
  * No chart-lane release: scientifically_qualified_for_hydraulic_charts is
    hard False while L1 metrology and an independent blinded L3 holdout are
    absent (HB-02A P1-P7 unfilled).
  * No defense against hostile same-process code: the HB-03S lock makes
    ordinary public assignment/construction/cloning/serialization fail-closed
    and the HB-03T lock additionally refuses ordinary module-level
    reassignment/deletion of the retained gate constant; authorization reads
    no module attribute at all. object.__setattr__, raw __dict__ tampering,
    class-object tampering and monkeypatching remain outside the supported
    consumer API scope (Python objects cannot securely defend against
    malicious code with equal in-process privileges).

Usage (library):
    res = fit_full_hb(dials=[48,40,29,24,18,10,8],
                      rpms=[300,200,100,60,30,6,3],
                      instrument=InstrumentConfig("Fann 35","R1B1","1.0"),
                      ramp_type="bhct_down", reviewed=True)
    res.status in {"OK","FAIL_CLOSED"}; res.to_dict() is machine-readable.
    Release authorization for hydraulic charts requires BOTH
    res.bhct_down_dataset_eligible AND
    res.scientifically_qualified_for_hydraulic_charts — the latter is False
    in this schema version by construction. (HB-03T: both authorization
    attributes are read-only properties holding literal False while the L1/L3
    scientific hold is active; they read no module attribute, so no public
    module variable, environment flag or input parameter can promote them —
    including on results created before such an attempt — and to_dict()/CLI
    JSON always serialize the safe state.)

Usage (CLI):
    python3 hb_full_fitter_standalone_v1.py --dials 48,40,29,24,18,10,8 \
        --ramp bhct_down [--reviewed] [--json-out result.json]
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import sys
import types
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import least_squares

# ---------------------------------------------------------------------------
# Frozen identity and constants
# ---------------------------------------------------------------------------
METHOD_ID = "NLS-HB-generic-v2.2-standalone/typed-intake-contract-repair/2026-11-08"
PARENT_METHOD_ID = "NLS-HB-generic-v2.1-standalone/typed-intake/2026-11-08"
PARENT_SHA256 = ("da5e2fc308795c4488f15564471ae64bd8c0d36e3ba7c8a8047fbaafb839d8da")
GRANDPARENT_METHOD_ID = "NLS-HB-generic-v2/unweighted-tau-space/2026-11-03"
GRANDPARENT_SHA256 = ("8b7f61049103931df26e29d0dc57a0c9d6ae86229dfb8218130f3b869639ce25")

RPM_ORDER: Tuple[int, ...] = (300, 200, 100, 60, 30, 6, 3)
RATE_PER_RPM = 1.7022951          # recorded Fann 35 R1B1 / Spring-1.0 constant
DIAL2PA = 0.51104                 # recorded Fann 35 R1B1 / Spring-1.0 constant
PA_PER_FIELD_TY = 0.47880259      # engine boundary: Pa per lbf/100ft^2

# Validated parameter envelope (erratum E-02 reconciliation is carried on
# every result; the archived draft interface's (0,2] is superseded HERE).
PARAMETER_ENVELOPE: Dict[str, Any] = {
    "tau_y": [0.0, "10*max_tau"],
    "K": [0.0, "10*max_tau"],
    "n": [0.01, 1.5],
    "reconciliation": ("validated solver envelope n in [0.01,1.5]; archived draft "
                       "interface (0,2] superseded by erratum E-02; widening "
                       "requires Owner-approved independent envelope evidence"),
}

# Fail-closed reason codes (contract 06 §3 starter set + NONINTEGER_DIAL_ENTRY
# refinement frozen in HB-02A 01_INTEGER_INPUT_CONTRACT.md §2.2).
REASON_CODES = {
    "INCOMPLETE_DIAL_SET", "NONFINITE_READING", "INVALID_READING_VALUE",
    "NONINTEGER_DIAL_ENTRY", "NONMONOTONE_READINGS",
    "INSTRUMENT_OR_RAMP_MISMATCH", "DATASET_NOT_AVAILABLE",
    "MISSING_MUD_HB_INPUT", "HB_FIT_UNVERIFIED", "NEAR_NONIDENTIFIABLE",
    "FITTING_OR_CONVERGENCE_DEFECT", "FREEZE_AUTHENTICATION_FAILED",
    "PV_YP_TO_HB_FORBIDDEN", "SILENT_FALLBACK_DETECTED",
}

CONDITIONING_FLAG_BAND = 1e4      # preregistered REPORTING flag (HB-02A §6)
RANK_TOL_RTMULT = 1e3             # structural rank check: rtol multiplier
CURVE_GRID_POINTS = 60            # frozen HB-02A §7 dense grid
CURVE_GRID_RPM = (3.0, 300.0)     # endpoints included; outside = extrapolation
NEAR_BINGHAM_TOL = 0.01
NEAR_ZERO_YIELD_PA = 1e-6
ABS_ONLY_TOL = 1e-12

# HB-03R: report-only active-bound detection tolerances (preregistration §7).
# Scale-aware: tau_y and K carry data-scaled Pa units, so their tolerance is
# proportional to max(tau); n is dimensionless with fixed numeric bounds, so
# its tolerance is a fixed absolute. These are DIAGNOSTIC tolerances only —
# they introduce no acceptance threshold and never change status or gates.
BOUND_HIT_REL_TOL = 1e-9
BOUND_HIT_ABS_FLOOR = 1e-12
BOUND_HIT_TOLERANCES: Dict[str, str] = {
    "tau_y": "max(1e-12, 1e-9*max_tau) Pa (scale-aware: data-scaled lower 0.0 / upper 10*max_tau)",
    "K": "max(1e-12, 1e-9*max_tau) Pa*s^n (scale-aware: data-scaled lower 0.0 / upper 10*max_tau)",
    "n": "1e-9 dimensionless (fixed numeric lower 0.01 / upper 1.5)",
}

# ---------------------------------------------------------------------------
# HB-03S/HB-03T authorization-lock constants (final contract repair)
# ---------------------------------------------------------------------------
# CONTRACT_VERSION identifies the result-class consumer contract. It is
# independent of METHOD_ID, which identifies the UNCHANGED numerical method
# (numerics, bounds, tolerances and multistarts are byte-identical to HB-03R;
# determinism_receipts therefore stay bit-identical).
CONTRACT_VERSION = "hb-fit-contract/1.3.0-hb03t"
# HB-03T public-gate lock: the former publicly assignable hard gate is
# retained for interface continuity ONLY. Its value stays part of the frozen
# unqualified-release state (False while L1 metrology and an independent
# blinded L3 holdout are missing — SCIENTIFIC_QUALIFICATION_HOLD_MISSING_L1_L3).
# NOTHING in this module reads it for authorization any more: both HBFitResult
# authorization attributes and every serialization path hold literal False,
# so no public module variable, environment flag or input parameter can
# promote a True state in this version. Ordinary module-level
# reassignment/deletion of this constant is refused (AttributeError) by the
# module-class lock at the end of this file.
SCIENTIFIC_QUALIFICATION_GATE: bool = False

VALID_RAMPS = ("surface", "bhct_up", "bhct_down")
_DATASET_KEY_BY_RAMP = {"surface": "surface_down", "bhct_up": "bhct_up",
                        "bhct_down": "bhct_down"}

CLASS_STATEMENT_L2 = (
    "±1 scenarios are hypothetical deterministic stress cases. They are NOT "
    "measured replicates, NOT an instrument repeatability or accuracy "
    "distribution, NOT a Gaussian error model, NOT evidence that any operator "
    "or device made an error, and NOT probabilities. (HB-02A §4 class "
    "statement, binding.)")


# ---------------------------------------------------------------------------
# Typed input/output objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InstrumentConfig:
    """Verified instrument identity. R1B1/Spring-1.0 is the ONLY configuration
    with an evidenced conversion; anything else fails closed."""
    family: str
    geometry: str
    spring: str

    def normalized(self) -> "InstrumentConfig":
        return InstrumentConfig(str(self.family).strip(),
                                str(self.geometry).strip(),
                                str(self.spring).strip())


@dataclass(frozen=True)
class EngineHBInput:
    """Engine-boundary projection of a fitted SI triple. Frozen (immutable):
    double conversion is unrepresentable through this type. K stays Pa·s^n,
    n stays dimensionless, mu_p_cp is fixed at 0 (no hidden viscosity term)."""
    tau_y_field_lbf_100ft2: float
    k_pa_s_n: float
    n_dimensionless: float
    mu_p_cp: float = 0.0


@dataclass
class HBFitResult:
    """Typed fit result per 06_HB_FIT_INTERFACE_CONTRACT (v1.3.0-hb03t —
    HB-03T public module-gate lock on the HB-03S v1.2.0 consumer-admission
    semantics). A FAIL_CLOSED result is a normal typed value downstream code
    must honor.

    HB-03T admission state machine (authorization is NOT instance state and
    reads NO module attribute):
      bhct_down_dataset_eligible                = ordinary field; status OK
                                                  AND ramp bhct_down AND
                                                  reviewed (routing metadata
                                                  only, never authority)
      scientifically_qualified_for_hydraulic_charts = read-only property;
                                                  literal False while L1/L3
                                                  are missing; True is
                                                  UNREPRESENTABLE
      chart_lane_admissible                     = read-only property;
                                                  literal False while the
                                                  scientific hold is active
                                                  -> always False on any
                                                  scientific hold
    """
    contract_version: str = CONTRACT_VERSION
    status: str = "FAIL_CLOSED"                     # OK | FAIL_CLOSED
    fail_reason_code: Optional[str] = None
    # fitted parameters (SI; meaningful only when status == OK)
    tau_y_pa: Optional[float] = None
    k_pa_s_n: Optional[float] = None
    n_dimensionless: Optional[float] = None
    # method + provenance
    fit_method_version: str = METHOD_ID
    parent_method_version: str = PARENT_METHOD_ID
    parent_sha256: str = PARENT_SHA256
    grandparent_method_version: str = GRANDPARENT_METHOD_ID
    grandparent_sha256: str = GRANDPARENT_SHA256
    instrument_config: Optional[Dict[str, str]] = None
    ramp_type: Optional[str] = None
    dataset_key: Optional[str] = None
    temperature_condition: Optional[str] = None
    source_hash: Optional[str] = None               # hash of consumed intake
    input_readings_rpm_to_dial: Optional[Dict[str, float]] = None
    # HB-03R: classified from PRE-conversion validated raw dials.
    #   "int"            all seven dials arrived as genuine Python ints
    #   "float_integral"  all dials integral, at least one arrived as a float
    #                     (mixed int/float-integral counts as float_integral)
    entry_type: Optional[str] = None
    gel_10_sec: Optional[float] = None              # passthrough, NOT fit points
    gel_10_min: Optional[float] = None              # passthrough, NOT fit points
    fluid_id: Optional[str] = None
    record_id: Optional[str] = None
    reviewed: bool = False
    # HB-03S/HB-03T authorization triad. ONLY bhct_down_dataset_eligible
    # remains a field (routing metadata; writable, never release authority).
    # The two authorization attributes are read-only properties (defined
    # below) holding LITERAL False while the L1/L3 scientific hold is active;
    # they hold no instance storage and, since HB-03T, read no module
    # attribute either, so ordinary assignment, construction, replace/clone,
    # copy/pickle, serialization and reassignment of any exported module
    # variable cannot promote them (the HB-03R post-construction mutation
    # path on @dataclass fields and the HB-03S module-gate dependency are
    # both closed).
    bhct_down_dataset_eligible: bool = False
    # diagnostics (OK)
    per_point: Optional[List[Dict[str, float]]] = None
    rmse_pa: Optional[float] = None
    sse: Optional[float] = None
    n_starts: Optional[int] = None
    converged: Optional[bool] = None
    jacobian_condition_number: Optional[float] = None
    jacobian_rank: Optional[int] = None
    near_nonidentifiable_flag: bool = False
    conditioning_flagged: bool = False
    parameter_correlation: Optional[Dict[str, Dict[str, float]]] = None
    covariance_per_unit_rel_sigma: Optional[Dict[str, Dict[str, float]]] = None
    sigma_declared: bool = False                    # always False: no noise model
    # HB-03R report-only active-bound diagnostics (never status-changing)
    active_bound_hit: bool = False
    bound_hit_params: Optional[Dict[str, str]] = None
    bound_hit_tolerances: Optional[Dict[str, str]] = None
    curve_grid: Optional[Dict[str, List[float]]] = None
    notes: List[str] = field(default_factory=list)
    parameter_envelope: Dict[str, Any] = field(
        default_factory=lambda: dict(PARAMETER_ENVELOPE))
    solver_versions: Dict[str, str] = field(default_factory=dict)
    determinism_receipt: Optional[str] = None
    qualifiers: List[str] = field(default_factory=list)

    def __post_init__(self):
        # HB-03S/HB-03T construction-time invariant verification. The
        # authorization attributes are class-level read-only properties
        # holding literal False while the L1/L3 hold is active (they read no
        # module attribute), so they are VERIFIED here, not stored:
        # construction fails closed if the invariant is ever violated.
        if SCIENTIFIC_QUALIFICATION_GATE is not False:
            raise TypeError(
                "SCIENTIFIC_QUALIFICATION_GATE must stay False while the L1/L3 "
                "scientific hold is active (hb-fit-contract/1.3.0-hb03t)")
        if self.scientifically_qualified_for_hydraulic_charts is not False:
            raise TypeError(
                "scientifically_qualified_for_hydraulic_charts is contract-held "
                "False while L1/L3 are absent; True is not representable in "
                "this schema version (hb-fit-contract/1.3.0-hb03t)")
        # belt-and-braces: the chart lane requires the AND, so it inherits the
        # same impossibility while the gate is False
        if self.chart_lane_admissible and not (
                self.bhct_down_dataset_eligible
                and self.scientifically_qualified_for_hydraulic_charts):
            raise TypeError(
                "chart_lane_admissible=True requires bhct_down_dataset_eligible "
                "AND scientifically_qualified_for_hydraulic_charts (the latter "
                "is unrepresentable while the L1/L3 scientific hold is active)")

    def to_dict(self) -> Dict[str, Any]:
        """HB-03T safe serialization. Every archived key is preserved with the
        archived order; the two authorization values are LITERAL False while
        the L1/L3 scientific hold is active. They are deliberately NOT read
        from any module attribute, so no reassignment of any exported module
        variable (including the retained SCIENTIFIC_QUALIFICATION_GATE), no
        environment flag and no input parameter can change them — including
        on results created before such an attempt."""
        gate = False   # literal hold state; never read from a module attribute
        out: Dict[str, Any] = {}
        for key, value in dataclasses.asdict(self).items():
            out[key] = value
            if key == "bhct_down_dataset_eligible":
                out["scientifically_qualified_for_hydraulic_charts"] = bool(gate)
                out["chart_lane_admissible"] = bool(value and gate)
        return out

    # -- HB-03S/HB-03T read-only authorization attributes --------------------
    # (no instance storage; NO module-attribute dependency since HB-03T)
    @property
    def scientifically_qualified_for_hydraulic_charts(self) -> bool:
        """AUTHORITATIVE scientific qualification: LITERAL False while the
        L1/L3 scientific hold is active. Read-only derived property with no
        module-attribute dependency — ordinary attribute assignment raises
        AttributeError, and no constructor keyword,
        dataclasses.replace/clone, copy/pickle, serialization path, public
        module variable, environment flag or input parameter can grant or
        serialize a True state in this schema version."""
        return False

    @property
    def chart_lane_admissible(self) -> bool:
        """Chart-lane admission. LITERAL False while the L1/L3 scientific
        hold is active. Derived read-only with no module-attribute
        dependency: False regardless of any ordinary assignment, clone,
        serialization or supported module use, including on results created
        before such an attempt."""
        return False


# ---------------------------------------------------------------------------
# Numeric core — algorithmically IDENTICAL to the archived baseline fit()
# ---------------------------------------------------------------------------
def hb_model(p: Sequence[float], g: np.ndarray) -> np.ndarray:
    """tau = tau_y + K * gamma_dot**n  (same float64 expression as parent)."""
    return p[0] + p[1] * np.power(g, p[2])


def _multistart_grid(tau: np.ndarray) -> Tuple[List[float], List[float], List[float]]:
    m = float(np.max(tau))
    ty0 = [0.01 * m, 0.1 * m, 0.3 * m, 0.6 * m]
    k0 = [0.1 * m, 0.5 * m, 1.0 * m]
    n0 = [0.2, 0.4, 0.6, 0.8, 1.0]
    return ty0, k0, n0


def fit_hb_core(g: np.ndarray, tau: np.ndarray) -> Dict[str, Any]:
    """Bounded deterministic 60-start NLS on unweighted stress-space residuals.

    Bit-identity anchor: same residual expression, bounds, tolerances, nested
    loop order and strict-`<` tie-break as the archived parent fit()."""
    ty0, k0, n0 = _multistart_grid(tau)

    def res(p):
        return hb_model(p, g) - tau

    lo = [0.0, 0.0, 0.01]
    hi = [10 * float(np.max(tau)), 10 * float(np.max(tau)), 1.5]
    best = None
    starts_tried = 0
    for a in ty0:
        for b in k0:
            for c in n0:
                starts_tried += 1
                try:
                    r = least_squares(res, [a, b, c], bounds=(lo, hi),
                                      xtol=1e-15, ftol=1e-15, gtol=1e-15)
                except Exception:
                    continue
                if best is None or r.cost < best.cost:
                    best = r
    out = {
        "n_starts": starts_tried,
        "best": best,
        "converged": bool(best.success) if best is not None else False,
    }
    if best is not None:
        ty, k, n = (float(v) for v in best.x)
        model = hb_model(best.x, g)
        resid = model - tau
        out.update({
            "tau_y_pa": ty, "k_pa_s_n": k, "n_dimensionless": n,
            "sse": float(2.0 * best.cost),
            "residuals": resid, "model": model,
        })
    return out


def analytic_jacobian(g: np.ndarray, tau_y: float, K: float, n: float) -> np.ndarray:
    """d tau / d (tau_y, K, n) at (tau_y, K, n): [1, g^n, K g^n ln g]."""
    g = np.asarray(g, float)
    gn = np.power(g, n)
    return np.column_stack([np.ones_like(g), gn, K * gn * np.log(g)])


def jacobian_diagnostics(g: np.ndarray, tau_model: np.ndarray,
                         tau_y: float, K: float, n: float) -> Dict[str, Any]:
    """cond(J), rank(J), joint correlation from (JᵀJ)⁻¹, covariance per UNIT
    relative stress sigma (sigma UNDECLARED — never an absolute CI)."""
    J = analytic_jacobian(g, tau_y, K, n)
    cond = float(np.linalg.cond(J))
    rank = int(np.linalg.matrix_rank(J))
    corr = cov = None
    if rank == 3 and np.isfinite(cond):
        jtj = J.T @ J
        try:
            jtj_inv = np.linalg.inv(jtj)
            d = np.sqrt(np.diag(jtj_inv))
            corr = {"labels": ["tau_y", "K", "n"],
                    "matrix": [[float(jtj_inv[i, j] / (d[i] * d[j]))
                                for j in range(3)] for i in range(3)]}
        except np.linalg.LinAlgError:
            corr = None
        jplus = np.linalg.pinv(J)
        covm = jplus @ np.diag(tau_model ** 2) @ jplus.T   # sigma_rel = 1
        cov = {"labels": ["tau_y", "K", "n"],
               "matrix": [[float(covm[i, j]) for j in range(3)]
                          for i in range(3)],
               "units": "per unit relative stress sigma (sigma UNDECLARED)"}
    return {"J": J, "cond": cond, "rank": rank,
            "correlation": corr, "covariance_per_unit_sigma": cov}


def bound_hit_diagnostics(tau_y: float, K: float, n: float,
                          max_tau: float) -> Dict[str, str]:
    """HB-03R report-only detection of ACTIVE box-bound hits at the frozen
    bounds: tau_y in [0, 10*max_tau], K in [0, 10*max_tau], n in [0.01, 1.5].

    Scale-aware tolerances (BOUND_HIT_TOLERANCES): tau_y and K are compared
    with max(1e-12, 1e-9*max_tau) in their Pa-scaled units; n (dimensionless,
    fixed numeric bounds) with a fixed 1e-9. A parameter is reported only
    against the single bound it touches (lower first, else upper). The result
    is a diagnostic echo for downstream consumers; it NEVER changes status,
    gates or acceptance thresholds, and it makes no optimality claim. Note
    the archived S1 value tau_y=1.999999999999999 Pa is ~243 Pa below its
    245.3 Pa upper bound and is NOT a bound hit."""
    tol_ty = max(BOUND_HIT_ABS_FLOOR, BOUND_HIT_REL_TOL * max_tau)
    tol_k = tol_ty
    tol_n = 1e-9
    lo_ty, hi_ty = 0.0, 10.0 * float(max_tau)
    lo_k, hi_k = 0.0, 10.0 * float(max_tau)
    lo_n, hi_n = 0.01, 1.5
    hits: Dict[str, str] = {}
    if (float(tau_y) - lo_ty) <= tol_ty:
        hits["tau_y"] = "lower"
    elif (hi_ty - float(tau_y)) <= tol_ty:
        hits["tau_y"] = "upper"
    if (float(K) - lo_k) <= tol_k:
        hits["K"] = "lower"
    elif (hi_k - float(K)) <= tol_k:
        hits["K"] = "upper"
    if (float(n) - lo_n) <= tol_n:
        hits["n"] = "lower"
    elif (hi_n - float(n)) <= tol_n:
        hits["n"] = "upper"
    return hits


def curve_grid(tau_y: float, K: float, n: float,
               n_points: int = CURVE_GRID_POINTS,
               rpm_range: Tuple[float, float] = CURVE_GRID_RPM
               ) -> Dict[str, List[float]]:
    """60 log-spaced RPM-equivalent points in [3, 300], endpoints included."""
    rpms = np.geomspace(rpm_range[0], rpm_range[1], n_points)
    g = RATE_PER_RPM * rpms
    tau = tau_y + K * np.power(g, n)
    return {"rpm": [float(r) for r in rpms],
            "gamma_dot_inv_s": [float(x) for x in g],
            "tau_model_pa": [float(t) for t in tau],
            "extrapolation": False,
            "note": ("3..300 RPM evidenced range only; evaluation outside this "
                     "range must be labelled extrapolation and carries no "
                     "acceptance meaning (HB-02A §7)")}


# ---------------------------------------------------------------------------
# Determinism / hashing helpers
# ---------------------------------------------------------------------------
def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def intake_hash(dials: Sequence[float], rpms: Sequence[float]) -> str:
    """Deterministic echo hash of the consumed intake. Non-finite entries are
    mapped to fixed string sentinels so fail-closed echoes remain hashable
    (the hash describes the intake, it is never a fit input)."""
    def _san(v: Any) -> Any:
        if isinstance(v, bool):
            return v
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        if math.isnan(f):
            return "NaN"
        if math.isinf(f):
            return "Infinity" if f > 0 else "-Infinity"
        return f
    return hashlib.sha256(_canonical_json(
        {"dials": [_san(v) for v in dials],
         "rpms": [_san(v) for v in rpms]}).encode()).hexdigest()


def _solver_versions() -> Dict[str, str]:
    import scipy
    return {"python": sys.version.split()[0],
            "numpy": np.__version__, "scipy": scipy.__version__,
            "optimizer": "scipy.optimize.least_squares/trf"}


# ---------------------------------------------------------------------------
# The standalone typed fitter
# ---------------------------------------------------------------------------
def fit_full_hb(dials: Sequence[Any], rpms: Sequence[Any], *,
                instrument: Any, ramp_type: str, reviewed: bool = False,
                gel_10_sec: Optional[float] = None,
                gel_10_min: Optional[float] = None,
                temperature_condition: Optional[str] = None,
                fluid_id: Optional[str] = None,
                record_id: Optional[str] = None) -> HBFitResult:
    """Strict typed Owner-laboratory seven-integer-dial Full-HB fitter.

    Fail-closed decision policy (HB-03 preregistration §4, frozen before any
    run). A data-driven rejection is a typed FAIL_CLOSED return value, never
    a raised exception and never a silently degraded fit; only programmer-type
    errors (wrong argument types/shapes) raise TypeError/ValueError.
    """
    if dataclasses.is_dataclass(instrument):
        inst = InstrumentConfig(**dataclasses.asdict(instrument)).normalized()
    elif isinstance(instrument, dict):
        inst = InstrumentConfig(**instrument).normalized()
    elif isinstance(instrument, InstrumentConfig):
        inst = instrument.normalized()
    else:
        raise TypeError("instrument must be InstrumentConfig or dict")

    dials_in = list(dials)
    rpms_in = list(rpms)

    # -- 1. intake completeness -------------------------------------------
    if len(dials_in) != 7 or len(rpms_in) != 7 or sorted(rpms_in) != sorted(RPM_ORDER):
        return _fail(dials_in, rpms_in, inst, None, "INCOMPLETE_DIAL_SET")

    # -- 2. finiteness ------------------------------------------------------
    clean_vals: List[float] = []
    for v in list(dials_in) + list(rpms_in):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TypeError("dials/rpms must be real numbers")
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return _fail(dials_in, rpms_in, inst, ramp_type, "NONFINITE_READING")
        clean_vals.append(f)
    dials_f = clean_vals[:7]
    rpms_f = clean_vals[7:]

    # pair positionally as given, then canonicalize to 300->3 descending
    pairs = sorted(zip(rpms_f, dials_f), key=lambda t: -t[0])
    rpms_c = [p[0] for p in pairs]
    dials_c = [p[1] for p in pairs]

    # -- 3. values: non-negative, integer ----------------------------------
    for v in dials_c:
        if v < 0:
            return _fail(dials_in, rpms_in, inst, ramp_type, "INVALID_READING_VALUE")
    # HB-03R provenance fix: classify from the PRE-conversion validated raw
    # dials (aligned to the same canonical RPM order), NOT from the float
    # copies — genuine ints are labelled "int", float-valued integral entries
    # "float_integral". The float conversion feeding the numerics below is
    # byte-identical to the parent, so fit results are unchanged.
    raw_pairs = sorted(zip(rpms_in, dials_in), key=lambda t: -float(t[0]))
    raw_dials_c = [p[1] for p in raw_pairs]
    entry_type = "int"
    for v in raw_dials_c:
        if isinstance(v, int) and not isinstance(v, bool):
            continue
        if isinstance(v, float) and v.is_integer():
            entry_type = "float_integral"
            continue
        return _fail(dials_in, rpms_in, inst, ramp_type, "NONINTEGER_DIAL_ENTRY")

    # -- 4. monotonicity (non-increasing 300 -> 3) --------------------------
    for i in range(len(dials_c) - 1):
        if dials_c[i + 1] > dials_c[i]:
            return _fail(dials_in, rpms_in, inst, ramp_type, "NONMONOTONE_READINGS")

    # -- 5. structural identifiability (exact input mathematics) ------------
    tau = np.asarray([v * DIAL2PA for v in dials_c], float)
    g = np.asarray([RATE_PER_RPM * r for r in rpms_c], float)
    if float(np.max(tau)) <= 0.0 or (max(dials_c) - min(dials_c)) == 0:
        r = _fail(dials_in, rpms_in, inst, ramp_type, "NEAR_NONIDENTIFIABLE")
        r.notes.append("STRUCTURAL: zero-variance dial profile carries no "
                       "curvature information; no numeric band was invented")
        return r

    # -- 6. instrument / ramp gate ------------------------------------------
    if not (inst.family == "Fann 35" and inst.geometry == "R1B1"
            and str(inst.spring) == "1.0"):
        return _fail(dials_in, rpms_in, inst, ramp_type,
                     "INSTRUMENT_OR_RAMP_MISMATCH")
    if ramp_type not in VALID_RAMPS:
        return _fail(dials_in, rpms_in, inst, ramp_type,
                     "INSTRUMENT_OR_RAMP_MISMATCH")

    # -- 7. fit (numeric core) ----------------------------------------------
    core = fit_hb_core(g, tau)
    if core["best"] is None or not core["converged"] \
            or not np.isfinite(core["sse"]):
        return _fail(dials_in, rpms_in, inst, ramp_type,
                     "FITTING_OR_CONVERGENCE_DEFECT")

    ty = core["tau_y_pa"]; K = core["k_pa_s_n"]; n = core["n_dimensionless"]
    resid = core["residuals"]; model = core["model"]
    rmse = float(np.sqrt(np.mean(resid ** 2)))

    # -- 8. post-fit identifiability / conditioning (preregistered) ---------
    diag = jacobian_diagnostics(g, model, ty, K, n)
    cond = diag["cond"]; rank = diag["rank"]
    near_nonid = (rank < 3) or (not np.isfinite(cond))
    if near_nonid:
        r = _fail(dials_in, rpms_in, inst, ramp_type, "NEAR_NONIDENTIFIABLE",
                  extra={"jacobian_condition_number": cond,
                         "jacobian_rank": rank})
        r.notes.append("STRUCTURAL: rank-deficient Jacobian at the optimum")
        return r
    conditioning_flagged = bool(cond > CONDITIONING_FLAG_BAND)

    # -- 8b. HB-03R report-only active-bound diagnostics ---------------------
    max_tau = float(np.max(tau))
    bound_hits = bound_hit_diagnostics(ty, K, n, max_tau)
    active_bound_hit = bool(bound_hits)

    # -- 9. honest notes / qualifiers ---------------------------------------
    notes: List[str] = []
    qualifiers: List[str] = []
    if abs(n - 1.0) <= NEAR_BINGHAM_TOL:
        notes.append("NEAR_BINGHAM (n within 0.01 of 1.0; three-parameter fit "
                     "retained; no two-parameter switch exists in this module)")
    if any(v == 0.0 for v in dials_c):
        notes.append("ZERO_DIAL_PRESENT (admissible per HB-02A V1/V3 "
                     "non-negative integer rule; recorded, not rounded away)")
    if ty <= NEAR_ZERO_YIELD_PA:
        notes.append("NEAR_ZERO_YIELD (tau_y <= 1e-6 Pa is legitimate; "
                     "unidentifiability is carried by the per-unit-sigma "
                     "covariance and correlation report, not hidden)")
        qualifiers.append("LOW_YIELD_IDENTIFIABILITY_LIMITED")
    if conditioning_flagged:
        notes.append(f"CONDITIONING_FLAGGED (cond(J) {cond:.6g} > {CONDITIONING_FLAG_BAND:g}; "
                     "reporting flag per HB-02A §6; never a waiver)")
        qualifiers.append("CONDITIONING_FLAGGED")
    if active_bound_hit:
        notes.append(
            "ACTIVE_BOUND(" + ", ".join(f"{p}:{side}" for p, side
                                        in bound_hits.items())
            + "; report-only diagnostic against the frozen envelope; interior "
              "(J^T J)^-1 covariance/correlation NOT authoritative at an active "
              "box constraint)")
        qualifiers.append("ACTIVE_BOUND_CONSTRAINED")
        if diag["correlation"] is not None:
            diag["correlation"]["interior_assumption_valid"] = False
        if diag["covariance_per_unit_sigma"] is not None:
            diag["covariance_per_unit_sigma"]["interior_assumption_valid"] = False
    qualifiers.append("S3_IDENTIFIABILITY_LIMITATION_RETAINED")
    qualifiers.append("SCIENTIFIC_QUALIFICATION_HOLD_MISSING_L1_L3")

    # -- 9b. HB-03S/HB-03T consumer admission (fail-closed authorization ------
    # lock). Eligibility = routing metadata only (ordinary writable field,
    # never release authority). Qualification and chart admission are NOT
    # instance state: they are read-only properties holding literal False
    # while the L1/L3 hold is active (HB-03T: no module-attribute dependency),
    # so no ordinary assignment, constructor keyword, replace/clone,
    # copy/pickle, serialization path or reassignment of any exported module
    # variable can promote them (HB-03S + HB-03T locks).
    bhct_down_dataset_eligible = bool(ramp_type == "bhct_down" and reviewed)
    notes.append(
        "CHART_LANE_HELD (scientific qualification hold active: "
        "chart_lane_admissible held False by contract hb-fit-contract/1.3.0-hb03t; "
        "release authorization requires genuine L1 metrology and an "
        "independently blinded L3 holdout)")
    notes.append(
        "HB03T_PUBLIC_GATE_LOCK_ACTIVE (admission attributes hold literal "
        "False while the L1/L3 scientific hold is active and read no module "
        "attribute; ordinary assignment, construction, replace/clone, "
        "serialization and module-level reassignment of any exported gate "
        "variable cannot grant qualification or the chart lane, including on "
        "results created before such an attempt)")

    result = HBFitResult(
        status="OK", fail_reason_code=None,
        tau_y_pa=ty, k_pa_s_n=K, n_dimensionless=n,
        instrument_config={"family": inst.family, "geometry": inst.geometry,
                           "spring": str(inst.spring),
                           "provenance": "validated_for_dataset"},
        ramp_type=ramp_type, dataset_key=_DATASET_KEY_BY_RAMP[ramp_type],
        temperature_condition=temperature_condition,
        source_hash=intake_hash(dials_c, rpms_c),
        input_readings_rpm_to_dial={str(int(r)): float(d)
                                    for r, d in zip(rpms_c, dials_c)},
        entry_type=entry_type,
        gel_10_sec=gel_10_sec, gel_10_min=gel_10_min,
        fluid_id=fluid_id, record_id=record_id, reviewed=bool(reviewed),
        bhct_down_dataset_eligible=bhct_down_dataset_eligible,
        per_point=[{"rpm": float(rpms_c[i]), "gamma_dot_inv_s": float(g[i]),
                    "dial": float(dials_c[i]),
                    "tau_observed_pa": float(tau[i]),
                    "tau_model_pa": float(model[i]),
                    "residual_pa": float(resid[i])} for i in range(7)],
        rmse_pa=rmse, sse=core["sse"], n_starts=int(core["n_starts"]),
        converged=True,
        jacobian_condition_number=cond, jacobian_rank=rank,
        near_nonidentifiable_flag=False,
        conditioning_flagged=conditioning_flagged,
        active_bound_hit=active_bound_hit,
        bound_hit_params=bound_hits if bound_hits else None,
        bound_hit_tolerances=dict(BOUND_HIT_TOLERANCES),
        parameter_correlation=diag["correlation"],
        covariance_per_unit_rel_sigma=diag["covariance_per_unit_sigma"],
        sigma_declared=False,
        curve_grid=curve_grid(ty, K, n),
        notes=notes, qualifiers=qualifiers,
        solver_versions=_solver_versions(),
    )
    result.determinism_receipt = hashlib.sha256(_canonical_json({
        "method": METHOD_ID, "g": [float(x) for x in g],
        "tau": [float(x) for x in tau],
        "tau_y_pa": ty, "k_pa_s_n": K, "n_dimensionless": n,
        "sse": core["sse"], "n_starts": int(core["n_starts"]),
    }).encode()).hexdigest()
    return result


def _fail(dials_in, rpms_in, inst: InstrumentConfig, ramp_type,
          code: str, extra: Optional[Dict[str, Any]] = None) -> HBFitResult:
    assert code in REASON_CODES, code
    r = HBFitResult(
        status="FAIL_CLOSED", fail_reason_code=code,
        instrument_config={"family": inst.family, "geometry": inst.geometry,
                           "spring": str(inst.spring)} if inst else None,
        ramp_type=ramp_type if ramp_type in VALID_RAMPS else None,
        dataset_key=_DATASET_KEY_BY_RAMP.get(ramp_type) if ramp_type else None,
        source_hash=intake_hash(dials_in, rpms_in) if dials_in else None,
        solver_versions=_solver_versions(),
        qualifiers=["FAIL_CLOSED_TYPED_RESULT"])
    if extra:
        for k, v in extra.items():
            setattr(r, k, v)
    return r


# ---------------------------------------------------------------------------
# Engine-boundary adapter (exactly one conversion; K, n untouched)
# ---------------------------------------------------------------------------
def to_engine_field(tau_y_pa: float, k_pa_s_n: float,
                    n_dimensionless: float) -> EngineHBInput:
    """Single SI -> engine-field projection:
    tau_y_field[lbf/100ft^2] = tau_y_pa / 0.47880259; K unchanged (Pa·s^n);
    n unchanged; mu_p_cp = 0. The frozen result type cannot be re-converted."""
    return EngineHBInput(
        tau_y_field_lbf_100ft2=float(tau_y_pa) / PA_PER_FIELD_TY,
        k_pa_s_n=float(k_pa_s_n),
        n_dimensionless=float(n_dimensionless),
        mu_p_cp=0.0)


# ---------------------------------------------------------------------------
# L2 ±1 integer-dial scenario runner (mechanics only — NOT an HB-02A run)
# ---------------------------------------------------------------------------
def integer_dial_envelope(dials: Sequence[int], rpms: Sequence[int], *,
                          instrument: Any, ramp_type: str, reviewed: bool,
                          fluid_id: Optional[str] = None) -> Dict[str, Any]:
    """Deterministic ±1 integer-dial scenario runner (HB-02A §4 mechanics).

    All 16 candidates (14 single-reading ±1 + 2 common-mode) are enumerated
    and listed; validity predicates V1/V2/V3 are applied in order; statistics
    are computed over valid+converged single-reading scenarios only, with the
    common-mode pair reported separately. The output carries the binding
    class statement: these are deterministic hypothetical cases, NOT
    uncertainty, NOT probabilities. This runner requires a synthetic or real
    L1 baseline supplied by the caller; it never fabricates dials and never
    claims the HB-02A protocol was executed."""
    base = fit_full_hb(dials, rpms, instrument=instrument,
                       ramp_type=ramp_type, reviewed=reviewed,
                       fluid_id=fluid_id)
    if base.status != "OK":
        return {"status": "BASELINE_FAIL_CLOSED",
                "fail_reason_code": base.fail_reason_code,
                "class_statement": CLASS_STATEMENT_L2}

    base_d = [int(v) for v in dials]
    candidates: List[Dict[str, Any]] = []

    def _predicate(v: List[int], perturbed_idx: Optional[int]) -> Tuple[bool, str]:
        # V1: seven finite non-negative integer dials
        if len(v) != 7 or any((not isinstance(x, int)) or x < 0 for x in v):
            return False, "V1"
        # V2: non-decreasing with increasing RPM == non-increasing 300->3
        for i in range(len(v) - 1):
            if v[i + 1] > v[i]:
                return False, "V2"
        # V3: the perturbed reading itself >= 0
        if perturbed_idx is not None and v[perturbed_idx] < 0:
            return False, "V3"
        return True, ""

    for pos in range(7):
        for delta in (-1, +1):
            v = list(base_d)
            v[pos] += delta
            ok, pred = _predicate(v, pos)
            label = f"single_rpm{int(rpms[pos])}_delta{delta:+d}"
            if not ok:
                candidates.append({"scenario": label, "vector": v,
                                   "status": f"INVALID({pred})"})
                continue
            r = fit_full_hb(v, list(rpms), instrument=instrument,
                            ramp_type=ramp_type, reviewed=reviewed,
                            fluid_id=fluid_id)
            candidates.append(_scenario_record(label, v, r))
    for delta in (-1, +1):
        v = [x + delta for x in base_d]
        ok, pred = _predicate(v, None)
        label = f"common_mode_{'plus' if delta > 0 else 'minus'}"
        if not ok:
            candidates.append({"scenario": label, "vector": v,
                               "status": f"INVALID({pred})"})
            continue
        r = fit_full_hb(v, list(rpms), instrument=instrument,
                        ramp_type=ramp_type, reviewed=reviewed,
                        fluid_id=fluid_id)
        candidates.append(_scenario_record(label, v, r))

    family = [c for c in candidates if c["scenario"].startswith("single")
              and c["status"] == "OK"]
    common = [c for c in candidates if c["scenario"].startswith("common_mode")]
    stats = None
    if len(family) >= 2:
        arr = np.array([[c["tau_y_pa"], c["k_pa_s_n"], c["n_dimensionless"]]
                        for c in family], float)
        cov = np.cov(arr, rowvar=False, ddof=1)
        sd = np.sqrt(np.diag(cov))
        corr = cov / np.outer(sd, sd)
        stats = {"n_valid_converged": len(family),
                 "n_single_candidates": 14,
                 "covariance_matrix": cov.tolist(),
                 "correlation_matrix": corr.tolist(),
                 "per_parameter_min": {"tau_y_pa": float(arr[:, 0].min()),
                                       "k_pa_s_n": float(arr[:, 1].min()),
                                       "n_dimensionless": float(arr[:, 2].min())},
                 "per_parameter_max": {"tau_y_pa": float(arr[:, 0].max()),
                                       "k_pa_s_n": float(arr[:, 1].max()),
                                       "n_dimensionless": float(arr[:, 2].max())}}
    return {
        "runner": "integer_dial_envelope/L2-mechanics-only/2026-11-08",
        "class_statement": CLASS_STATEMENT_L2,
        "not_an_hb02a_execution": True,
        "not_an_uncertainty_product": True,
        "baseline": {"dials": base_d, "tau_y_pa": base.tau_y_pa,
                     "k_pa_s_n": base.k_pa_s_n,
                     "n_dimensionless": base.n_dimensionless,
                     "source_hash": base.source_hash},
        "candidates_all_16_listed": candidates,
        "counts": {"total": len(candidates),
                   "valid_converged": sum(1 for c in candidates
                                          if c["status"] == "OK"),
                   "invalid": sum(1 for c in candidates
                                  if str(c["status"]).startswith("INVALID")),
                   "failed_convergence": sum(1 for c in candidates
                                             if c["status"] == "FAILED_CONVERGENCE")},
        "single_reading_family_stats": stats,
        "common_mode_scenarios": common,
    }


def _scenario_record(label: str, vector: List[int],
                     r: HBFitResult) -> Dict[str, Any]:
    if r.status != "OK":
        return {"scenario": label, "vector": vector,
                "status": ("FAILED_CONVERGENCE" if r.fail_reason_code in
                           ("FITTING_OR_CONVERGENCE_DEFECT",
                            "NEAR_NONIDENTIFIABLE") else r.fail_reason_code)}
    return {"scenario": label, "vector": vector, "status": "OK",
            "tau_y_pa": r.tau_y_pa, "k_pa_s_n": r.k_pa_s_n,
            "n_dimensionless": r.n_dimensionless,
            "rmse_pa": r.rmse_pa,
            "jacobian_condition_number": r.jacobian_condition_number}


# ---------------------------------------------------------------------------
# CLI (standalone; JSON on stdout)
# ---------------------------------------------------------------------------
def _main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="standalone Full-HB fitter (HB-03)")
    ap.add_argument("--dials", required=True,
                    help="7 integer dials, canonical order 300,200,100,60,30,6,3")
    ap.add_argument("--rpms", default="300,200,100,60,30,6,3")
    ap.add_argument("--family", default="Fann 35")
    ap.add_argument("--geometry", default="R1B1")
    ap.add_argument("--spring", default="1.0")
    ap.add_argument("--ramp", required=True, choices=list(VALID_RAMPS))
    ap.add_argument("--reviewed", action="store_true")
    ap.add_argument("--fluid-id", default=None)
    ap.add_argument("--temperature", default=None)
    ap.add_argument("--gel-10-sec", type=float, default=None)
    ap.add_argument("--gel-10-min", type=float, default=None)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args(argv)

    dials = [float(x) if "." in x else int(x) for x in a.dials.split(",")]
    rpms = [int(x) for x in a.rpms.split(",")]
    res = fit_full_hb(
        dials, rpms,
        instrument=InstrumentConfig(a.family, a.geometry, a.spring),
        ramp_type=a.ramp, reviewed=a.reviewed,
        gel_10_sec=a.gel_10_sec, gel_10_min=a.gel_10_min,
        temperature_condition=a.temperature, fluid_id=a.fluid_id)
    js = json.dumps(res.to_dict(), indent=1, allow_nan=False)
    if a.json_out:
        with open(a.json_out, "w") as fh:
            fh.write(js)
    print(js)
    return 0 if res.status == "OK" else 2


# ---------------------------------------------------------------------------
# HB-03T public module-gate lock (final gate correction; module-class guard)
# ---------------------------------------------------------------------------
# The retained SCIENTIFIC_QUALIFICATION_GATE constant is interface-continuity
# only and is locked at its frozen unqualified-release value: ORDINARY
# module-attribute reassignment or deletion of it raises AttributeError on
# this module object. This lock guards the ORDINARY consumer API surface
# only; it is NOT a defense against hostile same-process code (e.g.
# object.__setattr__ on the module, class-object tampering, source editing or
# import-system replacement), which remains out of scope. Authorization
# itself does not depend on this lock: the authorization properties and every
# serialization path hold literal False and read no module attribute, so even
# an out-of-band write could not promote authorization on any result,
# existing or future. Production scientific authorization requires a
# separately versioned, Owner-approved code change — never a toggle in this
# unqualified model.
class _HB03TPublicGateLockedModule(types.ModuleType):
    """Module class refusing ordinary reassignment/deletion of the retained
    public gate constant (HB-03T)."""

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "SCIENTIFIC_QUALIFICATION_GATE":
            raise AttributeError(
                "HB-03T public-gate lock: SCIENTIFIC_QUALIFICATION_GATE is "
                "held at its frozen unqualified-release value (False) while "
                "the L1/L3 scientific hold is active "
                "(hb-fit-contract/1.3.0-hb03t); module-level reassignment is "
                "refused. Production scientific authorization requires a "
                "separately versioned Owner-approved code change.")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name == "SCIENTIFIC_QUALIFICATION_GATE":
            raise AttributeError(
                "HB-03T public-gate lock: SCIENTIFIC_QUALIFICATION_GATE "
                "cannot be deleted (hb-fit-contract/1.3.0-hb03t).")
        super().__delattr__(name)


_module_object = sys.modules.get(__name__)
if _module_object is not None and isinstance(_module_object, types.ModuleType):
    _module_object.__class__ = _HB03TPublicGateLockedModule


if __name__ == "__main__":
    raise SystemExit(_main())
