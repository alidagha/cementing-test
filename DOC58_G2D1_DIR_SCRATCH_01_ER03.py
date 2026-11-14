#!/usr/bin/env python3
# ============================================================================
# ER-01 DERIVATIVE (release-engineering candidate) — Owner-authorized repair
# batch 2026-11-08.  Derived from the FROZEN G3 research source
# DOC58_G2D1_DIR_SCRATCH_01.py (sha256
# 8e79f2b209ed458fa32d5d253e76db4e98b103afc07d9605346a40554e6b5249, preserved
# untouched).  Scope = ER01-F1 ONLY (Survey physical validity, datum and
# coverage contract) plus ER01-F2 mirrors (job-entry guard, raw-channel
# audit).  Hydrostatic physics stays rho*g*dTVD; friction stays MD-length;
# no DLS limit, no accuracy warning, no threshold change.
# ============================================================================
# ER-03 DERIVATIVE (2026-11-08, owner-authorized): D14/D15 BHSP
# shut-in increment corrected to the ABSOLUTE bottomhole target,
# dP = BHSP - (Hp_end + WHP0) — the same single-expression repair
# as the ER-03 vertical engine (ER02R two-path proof).  Survey
# contract, hydrostatics, friction and all ER-01 guards are
# byte-unchanged.
# ============================================================================
# =====================================================================
# DOC58_G2D1_DIR_SCRATCH_01 — G2-D1 §C scratch directional candidate.
# RESEARCH ONLY — REVERSIBLE — NOT PRODUCTION QUALIFIED — NOT A RELEASE.
#
# Derived programmatically from the sealed research engine
#   DOC58_SI_CANDIDATE_03_TF2R.py
#   sha256 0841ee338342a7d65054b563e68d8eaa3c2181017dfae382ad4c8917ee17b7f2
# (itself preserved untouched).  The sealed simulate() text is carried
# VERBATIM except THREE surgical substitutions that implement the §B
# directional contract, and nothing else:
#   (1) state_heads(): hydrostatic heads accumulated as rho*g*dTVD
#       through the explicit MD->TVD survey (was: rho*g*dMD);
#   (2) the DOC55 free-fall void-equilibrium kappa probe uses the same
#       directional head (consistency of the shared head operator);
#   (3) the recorded annular track-depth hydrostatic uses the same
#       directional above-track accumulation.
# FRICTION IS UNCHANGED (dMD flow length, sealed HB rules, sealed
# lam_alpha policy).  Yield/gel resistance unchanged.  Free-fall,
# ff-refill, reverse-exchange, tail branches, volume audit, inertial
# limiter, schedule/kinematics: sealed text.  Identity (vertical)
# surveys short-circuit to the SEALED head_pa / hydro_at_depth_pa
# function objects so vertical behaviour is BIT-IDENTICAL by
# construction (§D non-regression gate).
# No rheology, coefficient, unit, threshold, dt, or display change.
# No per-well constant exists anywhere.
# =====================================================================
"""
G2-D1 scratch directional candidate (research-only).
simulate(job) reads job.survey (attach with attach_survey(job, survey)).
survey=None raises ChartInputError — the candidate never guesses depth.
"""
import math

from DOC58_SI_CANDIDATE_03_TF2R_ER03 import (  # ER-03 derivative (frozen ER-01 parent hash-pinned by caller)
    AnnSection, BBL_TO_M3, ChartInputError, Channel,
    ChartResultIntegrityError, ER01_TOL_M, Fluid, FluidStageSpec,
    G0, GeometrySpec, JobDesign, KPSI_PER_PA, LAM_ALPHA, PA_TO_PSI,
    PipeSection, SimResult, SLURRY_TYPES, TOL_STATIC_PA,
    _er01_audit_channels, _er01_finite, _er01_validate_job,
    fric_above_pa, fric_col_pa, head_pa, hydro_at_depth_pa, put_bottom,
    rho_si, take_bottom, yield_resist_pa)

import numpy as np



# ----------------------------------------------------------------------
# Survey (recorded trajectory; piecewise-linear TVD(MD); explicit
# MD->TVD mapping) — same convention as the §B independent oracle.
# ----------------------------------------------------------------------
class Survey:
    def __init__(self, md, tvd, inc=None, azi=None, source='recorded'):
        if len(md) != len(tvd) or len(md) < 2:
            raise ChartInputError('Survey needs >=2 matching MD/TVD knots.')
        self.md = [float(x) for x in md]
        self.tvd = [float(x) for x in tvd]
        self.inc = None if inc is None else [float(x) for x in inc]
        self.azi = None if azi is None else [float(x) for x in azi]
        self.source = source
        # --- ER01-F1: physical validity guards (fail-closed, pre-physics) ---
        # (a) every knot finite
        for _label, _seq in (('MD', self.md), ('TVD', self.tvd)):
            for i, x in enumerate(_seq):
                if not math.isfinite(x):
                    raise ChartInputError(
                        'Survey %s[%d] must be finite; got %r.'
                        % (_label, i, x))
        for _label, _seq in (('inc', self.inc), ('azi', self.azi)):
            if _seq is not None:
                for i, x in enumerate(_seq):
                    if not math.isfinite(x):
                        raise ChartInputError(
                            'Survey %s[%d] must be finite; got %r.'
                            % (_label, i, x))
        # (b) datum convention: TVD is measured downward from the surface
        # datum (0 m) and is non-negative (float dust within ER01_TOL_M
        # tolerated).  A hung survey with its own datum is a separate,
        # explicitly documented extension — not silently inferred here.
        for i, x in enumerate(self.tvd):
            if x < -ER01_TOL_M:
                raise ChartInputError(
                    'Survey TVD[%d]=%r is negative under the surface-datum '
                    'convention (TVD measured downward from 0 m).'
                    % (i, x))
        # (c) existing contract (message preserved): strictly increasing MD
        for i in range(1, len(self.md)):
            if not self.md[i] > self.md[i - 1]:
                raise ChartInputError('Survey MD not strictly increasing.')
        # (d) per-interval physical slope bound: |dTVD| <= dMD + tol.  A TVD
        # change can never exceed the measured-depth change of the same
        # interval.  Legitimate high-dogleg / near-horizontal trajectories
        # (|dTVD| << |dMD|) pass unchanged; NO DLS cutoff is introduced and
        # the tolerance is float dust (1e-6 m), not an engineering bound.
        for i in range(len(self.md) - 1):
            dmd = self.md[i + 1] - self.md[i]
            dtvd = abs(self.tvd[i + 1] - self.tvd[i])
            if dtvd > dmd + ER01_TOL_M:
                raise ChartInputError(
                    'Survey segment %d->%d is physically impossible: '
                    '|dTVD|=%.6f m exceeds dMD=%.6f m (+ float-dust tol '
                    '%g m).  TVD change along an interval can never exceed '
                    'its MD change.' % (i, i + 1, dtvd, dmd, ER01_TOL_M))

    @property
    def identity(self):
        """True only for the exact vertical lane (tvd knots == md knots);
        routes to the sealed engine functions for bit-exact behaviour."""
        return (len(self.md) == 2 and self.md[0] == 0.0
                and self.tvd[0] == 0.0 and self.tvd[1] == self.md[1])

    def _slope(self, i):
        dmd = self.md[i + 1] - self.md[i]
        return (self.tvd[i + 1] - self.tvd[i]) / dmd if dmd > 0 else 1.0

    def tvd_at(self, md):
        mds, tvs = self.md, self.tvd
        if md <= mds[0]:
            return tvs[0] + (md - mds[0]) * self._slope(0)
        if md >= mds[-1]:
            return tvs[-1] + (md - mds[-1]) * self._slope(len(mds) - 2)
        lo, hi = 0, len(mds) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if mds[mid] <= md:
                lo = mid
            else:
                hi = mid
        return tvs[lo] + (md - mds[lo]) * self._slope(lo)

    @classmethod
    def vertical(cls, td_m):
        return cls([0.0, float(td_m)], [0.0, float(td_m)],
                   inc=[0.0, 0.0], azi=[0.0, 0.0],
                   source='identity_vertical')

    @classmethod
    def constant_incl(cls, td_m, inc_rad):
        return cls([0.0, float(td_m)],
                   [0.0, float(td_m) * math.cos(inc_rad)],
                   inc=[inc_rad, inc_rad], azi=[0.0, 0.0],
                   source='constant_inclination')


def _chan_secs(chan):
    return [(s.z_top, s.z_bot, s.cap_bbl_per_m) for s in chan.sections]


def _walk_spans(col, chan):
    """Volume->MD mapping of a bottom(TD)->top column (deep-first)."""
    secs = _chan_secs(chan)
    wins = []
    c = 0.0
    for i, (zt, zb, cap) in enumerate(secs):
        w = cap * (zb - zt)
        wins.append((i, c, c + w, zt, zb, cap))
        c += w
    out = []
    cursor = 0.0
    for name, vol in col:
        x0, x1 = cursor, cursor + vol
        for (i, lo, hi, zt, zb, cap) in wins:
            p, q = max(x0, lo), min(x1, hi)
            if q <= p:
                continue
            md_deep = zb - (p - lo) / cap
            md_shallow = zb - (q - lo) / cap
            out.append((name, i, md_deep, md_shallow))
        cursor += vol
    return out


def head_dir_pa(col, chan, fluids, survey):
    """Directional hydrostatic head (Pa): rho*g*dTVD per fluid sub-span.
    Identity surveys delegate to the SEALED head_pa (bit-exact)."""
    if survey.identity:
        return head_pa(col, chan, fluids)
    H = 0.0
    for name, _i, md_deep, md_shallow in _walk_spans(col, chan):
        H += rho_si(fluids[name].rho_ppg) * G0 * \
            (survey.tvd_at(md_deep) - survey.tvd_at(md_shallow))
    return H


def hydro_above_track_pa(col, chan, fluids, survey, track_md):
    """Directional weight of the column ABOVE track_md (Pa); mirrors the
    sealed hydro_at_depth_pa volume bookkeeping.  Identity surveys
    delegate to the SEALED function (bit-exact)."""
    if survey.identity:
        return hydro_at_depth_pa(col, chan, fluids, track_md)
    need = chan.volume_above(track_md)
    if need <= 0.0:
        return 0.0
    secs = _chan_secs(chan)
    # from-top windows (shallow-first) for the top-down walk
    wins = []
    c = 0.0
    for i, (zt, zb, cap) in reversed(list(enumerate(secs))):
        w = cap * (zb - zt)
        wins.append((i, c, c + w, zt, zb, cap))
        c += w
    H = 0.0
    cursor = 0.0
    for name, vol in reversed(col):
        x0, x1 = cursor, cursor + vol
        for (i, lo, hi, zt, zb, cap) in wins:
            p, q = max(x0, lo), min(x1, hi)
            if q <= p:
                continue
            take = min(q - p, need)
            if take <= 0.0:
                break
            md_shallow = zt + (p - lo) / cap
            md_deep = zt + (p + take - lo) / cap
            H += rho_si(fluids[name].rho_ppg) * G0 * \
                (survey.tvd_at(md_deep) - survey.tvd_at(md_shallow))
            need -= take
            if need <= 1e-15:
                break
        cursor += vol
        if need <= 1e-15:
            break
    return H


def attach_survey(job, survey):
    """Attach an explicit MD->TVD survey to a JobDesign (returns job)."""
    if not isinstance(survey, Survey):
        raise ChartInputError('attach_survey expects a Survey.')
    job.survey = survey
    return job


def _er01_validate_coverage(survey, geo):
    """ER01-F1 datum/coverage contract: the simulated hydraulic MD range
    is [0, td_m] (the flow channels span surface..TD).  Every requested
    hydraulic MD station must lie INSIDE the declared survey — end-segment
    extrapolation outside the recorded knots is not approved.  This is a
    coverage requirement, not a formal 'first station must be exactly 0'
    rule: a survey anchored at a non-zero datum is acceptable only when it
    genuinely covers the simulated range (i.e. it starts at the surface
    datum); hung-survey datum anchoring would be a separate documented
    extension and is not silently inferred."""
    td = geo.td_m
    if not math.isfinite(td) or td <= 0:
        raise ChartInputError(
            'Survey coverage check needs a finite positive TD; got %r.'
            % (td,))
    lo, hi = survey.md[0], survey.md[-1]
    if lo > ER01_TOL_M:
        raise ChartInputError(
            'Survey coverage starts at MD=%.3f m — hydraulic stations in '
            '[0, %.3f) m lie outside the declared survey and TVD there '
            'would be extrapolated, which the ER01-F1 contract forbids. '
            'Extend the survey to the surface datum (0 m) with documented '
            'knots.' % (lo, lo))
    if hi < td - ER01_TOL_M:
        raise ChartInputError(
            'Survey coverage ends at MD=%.3f m but the simulated well TD '
            'is %.3f m — hydraulic stations below lie outside the declared '
            'survey (extrapolation forbidden). Extend the survey to TD.'
            % (hi, td))


def simulate(job: JobDesign) -> SimResult:
    survey = getattr(job, 'survey', None)
    if survey is None:
        raise ChartInputError(
            'G2D1 scratch candidate requires an explicit MD->TVD survey '
            '(attach_survey). It never guesses depth.')
    _er01_validate_coverage(survey, job.geo)   # ER01-F1: datum/coverage
    _er01_validate_job(job)                    # ER01-F2 mirror

    geo = job.geo
    fluids = job.fluids
    chan_pipe = geo.chan_pipe            # D11 v1.2: per-section channels
    chan_ann = geo.chan_ann
    BP = job.back_pressure_psi / PA_TO_PSI
    float_on = bool(job.float_equipment)   # v1.2.4 (F3)
    dt = job.dt_min
    frictionless = job.frictionless
    V_pipe0 = chan_pipe.total_volume()
    V_ann0 = chan_ann.total_volume()

    pipe = [[job.displacement_fluid, V_pipe0]]
    ann = [[job.displacement_fluid, V_ann0]]
    gap = 0.0                       # bbl of empty pipe at the top (free fall)

    # schedule: stage boundaries strictly from the Phase IV V/Q contract
    blocks = []
    t0 = 0.0
    for st in job.placement:
        blocks.append([t0, t0 + st.volume_bbl / st.rate_bpm, st.rate_bpm, st.fluid_type])
        t0 = blocks[-1][1]
    t_eod = t0
    t_end = t_eod + job.tail_cap_min   # equalization tail (breaks at balance)

    def rate_at(t):
        for a, b, r, f in blocks:
            if a <= t < b and t < t_eod - 1e-9:
                return r, f
        return 0.0, job.displacement_fluid

    # ---- v1.3.0: DYNAMIC SEGMENT-LEVEL CORRECTION ----------------------
    # The laminar calibration is applied inside the friction functions,
    # per segment, at every call (no run-level decision, no t0 probe).
    # The diag block below is a static descriptor for harness continuity.
    lam_diag = dict(alpha=LAM_ALPHA, L_eff=None, F1_pa=None, F2_pa=None,
                    gated=False, status='V142_PSI_SCHEDULE',
                    reason=('v1.4.2 continuous annular psi-schedule '
                            '(annular laminar multiplier 1+(LAM_ALPHA-1)'
                            '*s(psi), C1 smootherstep bands; string law '
                            'frozen v1.3.1; no well names, no modes)'))

    def state_heads():
        return head_dir_pa(pipe, chan_pipe, fluids, survey), \
            head_dir_pa(ann, chan_ann, fluids, survey)

    def fric_pair(q_bpm):
        if frictionless:
            return 0.0, 0.0
        q = q_bpm * BBL_TO_M3 / 60.0
        return (fric_col_pa(pipe, chan_pipe, q, fluids, geo, True),
                fric_col_pa(ann, chan_ann, q, fluids, geo, False))

    def solve_freefall(yield_pa=0.0):
        """Pipe-heavy branch: Q with Hp - Fp(Q) - BP - Ha - Fa(Q) - Y = 0.
        yield_pa > 0 only in the post-job tail (D13 static gel)."""
        Hp, Ha = state_heads()

        def phi(qb):
            Fp, Fa = fric_pair(qb)
            return Hp - Fp - BP - Ha - Fa - yield_pa
        lo, hi = 0.0, 80.0
        if phi(lo) <= 0.0:
            return 0.0
        if frictionless:            # unresisted U-tube: no finite rate exists
            return 0.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if phi(mid) > 0.0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def solve_reverse(yield_pa=0.0):
        """Annulus-heavy branch: Q with Ha - Fa(Q) - Hp - Fp(Q) - Y = 0."""
        Hp, Ha = state_heads()

        def psi(qb):
            Fp, Fa = fric_pair(qb)
            return Ha - Fa - Hp - Fp - yield_pa
        lo, hi = 0.0, 80.0
        if psi(lo) <= 0.0:
            return 0.0
        if frictionless:
            return 0.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if psi(mid) > 0.0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def put_top(col, name, vol):
        if col and col[-1][0] == name:
            col[-1][1] += vol
        else:
            col.append([name, vol])

    def drop_top(col, x):
        while x > 1e-12 and col:
            name, vol = col[-1]
            take = min(vol, x)
            col[-1][1] -= take
            x -= take
            if col[-1][1] <= 1e-12:
                col.pop()

    T, WHP, PUMP, HYD, DYN, QI, QO = [], [], [], [], [], [], []
    t_slurry = None
    t_ff0 = t_ff1 = None
    slurry_set = set(SLURRY_TYPES)
    prev_ff = False
    q_ff_state = [0.0]     # free-fall EXCESS rate state (inertial limiter)
    q_rev_state = [0.0]    # reverse-exchange rate state (inertial limiter)
    SLEW_Q = 0.10          # bbl/min per minute: exchange acceleration limit
    head_overflow = [0.0]
    tail_capped = [False]
    tail_samples = [0]

    # ---- v1.2.3 volume audit (pure bookkeeping; exported in diag) --------
    BR = {}     # branch -> active minutes
    LEAK = {}   # branch -> (QI - QO)*dt - d(content)  [>0 = unrecorded out]
    DRES = {}   # branch -> d(Cp + gap - V_pipe0)       [pipe invariant]
    CUM = [0.0, 0.0]                   # pumped in / returned out, bbl
    _pc = [V_pipe0, V_ann0, 0.0]       # previous step (Cp, Ca, gap)

    def _dacc(D, k, dv):
        D[k] = D.get(k, 0.0) + dv

    t = 0.0
    while t <= t_end + 1e-9:
        r_in, fl_in = rate_at(t)
        tail_active = False
        backflow = 0.0            # reverse flow leaving at the pipe TOP
        rev_draw = 0.0            # v1.2.3: reverse draw ann -> pipe (bbl/min)
        q_mouth = None            # v1.2.3: annulus-top returns rate (bbl/min)
        branch = 'normal'
        if t < t_eod - 1e-9:
            Hp, Ha = state_heads()
            static = Hp - BP - Ha
            if frictionless:
                # ---- pumped-transit closure (documented limitation) ------
                branch = 'frictionless'
                q_net, q_out = r_in, r_in
                whp = max(0.0, (BP + Ha - Hp) * KPSI_PER_PA)
            elif static > 1e-6:                       # pipe side heavier
                q_ff = solve_freefall()
                # ---- DOC55 (F4): closed-form free-fall/void equilibrium --
                # Void volume gap* at which the fall drive exactly equals
                # the pump rate: Hp(gap*) - Fp(r_in) - BP - Ha - Fa(r_in)
                # = 0, with Hp linear in the open pipe-top void (local
                # gradient kappa from the engine's own top-drop operator).
                # Clamping BOTH branch moves at gap* resolves the
                # freefall<->ffrefill event inside the step: no overshoot,
                # no new constant, no friction change; the booked move IS
                # the flow, so the volume books stay exact.
                _fr_p, _fr_a = fric_pair(r_in)
                _drive = static - _fr_p - _fr_a
                _gap_star = 0.0
                _probe = [list(_seg) for _seg in pipe]
                _vol = sum(v for _n, v in _probe)
                _eps = min(0.01, _vol)
                if _eps > 0.0:
                    drop_top(_probe, _eps)
                    _kappa = ((Hp - head_dir_pa(_probe, chan_pipe, fluids,
                                               survey))
                              / _eps)
                    if _kappa > 0.0:
                        _gap_star = max(gap + _drive / _kappa, 0.0)
                if q_ff > r_in + 1e-9:
                    branch = 'freefall'
                    exc = q_ff - r_in
                    # DOC55 (F4): the void may not step past equilibrium
                    _dg = min(exc * dt, max(_gap_star - gap, 0.0))
                    q_ff = r_in + _dg / dt
                    # free fall: gap at the pipe top, WHP -> 0 (documented)
                    q_net, q_out, whp = q_ff, q_ff, 0.0
                    gap += _dg
                    q_ff_state[0] = _dg / dt
                    if not prev_ff and t_ff0 is None:
                        t_ff0 = t
                    prev_ff = True
                elif float_on and gap > 1e-9:
                    # ---- v1.2.4 (F1): pump-refill of the pipe-top void ---
                    # Free-fall persists (WHP = 0) while the pump excess
                    # refills the void; returns = natural fall < pump rate
                    # (the CEMCADE deficit signature); the well re-
                    # pressurizes exactly when the void closes.
                    # DOC55 (F4): the refill also stops at the shared void
                    # equilibrium (no crossing back into freefall inside
                    # one step; same closed-form event as the freefall).
                    fill = min(r_in - q_ff, gap / dt,
                               max(gap - _gap_star, 0.0) / dt)
                    if fill < 0.0:
                        fill = 0.0
                    gap -= fill * dt
                    branch = 'ffrefill'
                    q_net, q_out, whp = r_in - fill, r_in - fill, 0.0
                    if prev_ff and t_ff1 is None:
                        t_ff1 = t
                    prev_ff = False
                    q_ff_state[0] = 0.0
                else:
                    q_net, q_out = r_in, r_in
                    Fp, Fa = fric_pair(r_in)
                    whp = max(0.0, (BP + Ha + Fa - Hp + Fp) * KPSI_PER_PA)
                    if prev_ff and t_ff1 is None:
                        t_ff1 = t
                    prev_ff = False
                    q_ff_state[0] = 0.0
            elif float_on:                            # ann heavy + float (F1/F2)
                if gap > 1e-9:
                    # ---- v1.2.4 (F1): annulus-heavy with an open void ---
                    # Float blocks the ann -> pipe push, so the void is
                    # refilled by the pump (through-flow capped by the
                    # void volume); WHP stays 0 until the void closes.
                    fill = min(r_in, gap / dt)
                    gap -= fill * dt
                    branch = 'ffrefill'
                    q_net, q_out, whp = r_in - fill, r_in - fill, 0.0
                else:
                    # ---- v1.2.4 (F2): float-locked pumping --------------
                    # No reverse exchange out of an open head while
                    # pumping: an annulus-heavy well pumps against the
                    # locked differential (WHP = differential + friction;
                    # never 0 by construction).  The v1.2.2/v1.2.3
                    # gapclose/freeex branches remain ONLY on the legacy
                    # open-head path below; the post-job tail (D13/D14)
                    # is untouched.
                    q_net, q_out = r_in, r_in
                    Fp, Fa = fric_pair(r_in)
                    whp = max(0.0, (BP + Ha + Fa - Hp + Fp) * KPSI_PER_PA)
                q_rev_state[0] = max(0.0, q_rev_state[0] - SLEW_Q * dt)
            else:                                     # legacy open-head path
                q_rev = solve_reverse() if static < -1e-6 else 0.0
                q_rev = min(max(q_rev,
                                q_rev_state[0] - SLEW_Q * dt),
                            q_rev_state[0] + SLEW_Q * dt)
                q_rev_state[0] = max(q_rev, 0.0)
                if q_rev > 1e-9 and gap > 1e-9:
                    branch = 'gapclose'
                    # v1.2.3 (V2): reverse exchange against an open void.
                    # The void closes at the exchange demand capped by the
                    # void volume (the SAME cap as v1.2.2); the fill is
                    # DRAWN from the annulus bottom (the annulus is the
                    # heavy side pushing into the shoe) while the pump
                    # through-flow and the returns stay at the full pump
                    # rate (CEMCADE volume signature).  Books: pipe +fill,
                    # annulus -fill, (QI - QO) == 0 == d(content), and
                    # Cp + gap == V_pipe0 hold EXACTLY.  Nothing leaves at
                    # the head while the void is open (the head port opens
                    # only when the void is closed -> freeex).
                    fill = min(q_rev, gap / dt)          # bbl/min
                    gap -= fill * dt
                    rev_draw = fill
                    q_mouth = r_in
                    q_net = r_in
                    q_out, whp = r_in, 0.0
                elif q_rev > 1e-9:
                    branch = 'freeex'
                    # v1.2.3 (V1): free exchange with the void closed.  The
                    # U-tube returns circulate up the pipe and out the open
                    # head; the backflow is BOOKED in Q Out and the net
                    # reverse draw comes from the annulus (level falls).
                    q_net = max(r_in - q_rev, 0.0)
                    backflow = q_rev
                    rev_draw = max(q_rev - r_in, 0.0)
                    q_mouth = q_net
                    q_out, whp = q_net + backflow, 0.0
                else:
                    q_net, q_out = r_in, r_in
                    Fp, Fa = fric_pair(r_in)
                    whp = max(0.0, (BP + Ha + Fa - Hp + Fp) * KPSI_PER_PA)
            # advance: pump at the pipe top, shoe crossing at the bottom
            x = q_net * dt
            if x > 0:
                chunks = take_bottom(pipe, x)
                put_bottom(ann, chunks)
            if rev_draw > 0:
                # v1.2.3: exchange draw enters the pipe at the shoe
                put_bottom(pipe, take_bottom(ann, rev_draw * dt))
            if r_in > 0:
                put_top(pipe, fl_in, r_in * dt)
            if backflow > 0:
                drop_top(pipe, backflow * dt)   # head backflow (free exchange)
            if q_mouth is None:
                q_mouth = q_out
            if q_mouth > 0:
                # returns at the annulus top only (v1.2.3: the head outflow
                # is booked in Q Out but does NOT leave through the mouth);
                # slurry leaving = over-displacement (reported in diag)
                drop_top(ann, q_mouth * dt)
        else:
            # ---- post-job U-tube equalization tail (documented "WHP -> 0"
            # open-system principle): with the pump off, the imbalance keeps
            # exchanging the columns until they balance.  Static gel (D13):
            # every segment of BOTH columns must yield (tau_tail = max(YP,
            # measured 10-min gel)) before it moves — the exchange starts
            # only above that threshold and is damped by it.  Surface
            # channels: Q In = 0; Q Out = returns only while the pipe side
            # is heavier; an annulus-heavy exchange is absorbed by the
            # pipe-top gap, then overflows through the open cement head.
            Y = 0.0 if frictionless else (
                yield_resist_pa(pipe, chan_pipe, fluids, geo, True)
                + yield_resist_pa(ann, chan_ann, fluids, geo, False))
            Hp, Ha = state_heads()
            static = Hp - BP - Ha
            tail_samples[0] += 1
            if abs(static) <= max(TOL_STATIC_PA, Y):   # D13: gel-held balance
                branch = 'tail_bal'
                q_net = 0.0
                q_out = 0.0
                whp = max(0.0, (BP + Ha - Hp) * KPSI_PER_PA)
                tail_active = False
            elif t > t_eod + job.tail_cap_min:
                branch = 'tail_cap'
                tail_capped[0] = True
                q_net = 0.0
                q_out = 0.0
                whp = max(0.0, (BP + Ha - Hp) * KPSI_PER_PA)
                tail_active = False
            elif static > 0.0:
                branch = 'tail_ff'
                tail_active = True
                q_ff = solve_freefall(yield_pa=Y)
                q_ff = min(max(q_ff, q_ff_state[0] - SLEW_Q * dt),
                           q_ff_state[0] + SLEW_Q * dt)
                q_ff_state[0] = max(q_ff, 0.0)
                q_net = 0.0
                q_out = q_ff
                whp = 0.0
                gap += q_ff * dt
                x = q_ff * dt
                if x > 0:
                    put_bottom(ann, take_bottom(pipe, x))
                    drop_top(ann, x)
            else:
                branch = 'tail_rev'
                tail_active = True
                q_rev = solve_reverse(yield_pa=Y)
                q_rev = min(max(q_rev, q_rev_state[0] - SLEW_Q * dt),
                            q_rev_state[0] + SLEW_Q * dt)
                q_rev_state[0] = max(q_rev, 0.0)
                q_net = 0.0
                q_out = 0.0
                whp = 0.0
                x = q_rev * dt
                if x > 0:
                    put_bottom(pipe, take_bottom(ann, x))
                    if gap > 1e-9:
                        closed = min(gap, x)
                        gap -= closed
                        x -= closed
                    if x > 0:      # pipe full: overflows at the head
                        drop_top(pipe, x)
                        head_overflow[0] += x
                        q_out = x / dt   # v1.2.3 (V3): overflow is BOOKED

        # --- record -----------------------------------------------------------
        Hp, Ha = state_heads()
        hydro = (BP + hydro_above_track_pa(ann, chan_ann, fluids,
                                           survey,
                                           geo.track_depth_m)) * KPSI_PER_PA
        if frictionless:
            dyn = None
        else:
            Fpa = fric_above_pa(ann, chan_ann, fluids, geo,
                                max((q_out if q_mouth is None else q_mouth),
                                    0.0) * BBL_TO_M3 / 60.0,
                                geo.track_depth_m)
            dyn = hydro + Fpa * KPSI_PER_PA
        pump = whp + job.surface_line_kpsi_at_8bpm * (r_in / 8.0) ** 2
        T.append(t); WHP.append(whp); PUMP.append(pump)
        HYD.append(hydro)
        if dyn is not None:
            DYN.append(dyn)
        QI.append(r_in); QO.append(q_out)
        # ---- v1.2.3 volume audit (pure bookkeeping, no effect on results) -
        Cp_a = sum(v for _n, v in pipe)
        Ca_a = sum(v for _n, v in ann)
        CUM[0] += r_in * dt
        CUM[1] += q_out * dt
        _dacc(BR, branch, dt)
        _dacc(LEAK, branch, (Cp_a + Ca_a - _pc[0] - _pc[1])
              - (r_in - q_out) * dt)
        _dacc(DRES, branch, (Cp_a + gap - V_pipe0)
              - (_pc[0] + _pc[2] - V_pipe0))
        _pc[:] = [Cp_a, Ca_a, gap]
        # events: first slurry arriving at the annulus bottom (track depth)
        if t_slurry is None and ann and ann[0][0] in slurry_set:
            t_slurry = t
        t += dt
        # break only AFTER at least one tail sample exists (float-drift safe:
        # accumulated t may cross t_eod inside the last placement step)
        if t > t_eod and tail_samples[0] >= 1 and not tail_active:
            break                 # equalized (or capped) — stop the record

    res_diag = dict(gap_bbl=gap, head_overflow_bbl=head_overflow[0],
                    tail_capped=tail_capped[0],
                    lam_alpha_policy=lam_diag,
                    # v1.2.7 hardening: the guard status is exported as a
                    # SEPARATED top-level diag key so diagnostics dumps
                    # distinguish OK_ON / OK_OFF / ERROR directly.
                    lam_alpha_policy_status=lam_diag.get('status',
                                                         'ERROR'))
    res_diag['vol_audit'] = dict(
        branch_min=dict(BR), leak_bbl=dict(LEAK), dres_pipe_bbl=dict(DRES),
        qi_tot=CUM[0], qo_tot=CUM[1], gap_end=gap,
        head_overflow_bbl=head_overflow[0],
        Cp_end=sum(v for _n, v in pipe), Ca_end=sum(v for _n, v in ann),
        V_pipe0=V_pipe0, V_ann0=V_ann0)

    # ---- D14: post-job BHSP shut-in segment --------------------------------
    # The equalized well is closed and the bottomhole pressure is anchored
    # to BHSP (the LARGER number of a compound 'xxxx+xxxx' entry).  The
    # whole system rises by dP = BHSP - bottom_static (documented shut-in
    # balance): WHP_final = BHSP - string-column head; the annular lines at
    # the track depth rise by the same dP; Q In = Q Out = 0.  The gray
    # job-end marker sits at the START of this segment (the source page
    # shows marker 244 then the rise to 254).
    t_shutin = None
    whp_final = None
    bhsp_used = None
    shutin_note = None
    BHSP_Pa = (job.bhsp_psi / PA_TO_PSI) if job.bhsp_psi is not None else None
    if BHSP_Pa is not None and not frictionless and not tail_capped[0]:
        Hp_end, _ = state_heads()          # balanced: pipe bottom == annulus bottom
        # D15 evidence: the slurry column the string holds AT shut-in — the
        # owner's "همیشه مقداری دوغاب حدود ۲۵ متر می‌مونه" remnant.  It is
        # the contiguous slurry run at the BOTTOM of the equalized string
        # (slumped back through the shoe), never a hard-coded constant.
        rem_vol = 0.0
        for _nm, _v in pipe:
            if _nm in slurry_set:
                rem_vol += _v
            else:
                break
        rem_len = sum(v_seg / sec.cap_bbl_per_m
                      for sec, v_seg in chan_pipe.spans(0.0, rem_vol, True))
        res_diag['shutin_string_slurry_m'] = rem_len
        # ER-03 (2026-11-08, owner-authorized): bottom_static is
        # the ACTUAL pre-shut-in ABSOLUTE bottom pressure
        # Hp_end + WHP0 (the surface backpressure is already
        # inside both terms).  The ER-02 increment
        # dP = BHSP - Hp_end alone added the gel-held wellhead
        # residual twice and landed the endpoint at BHSP + WHP0
        # (ER02R two-path proof, ER02R_FINDINGS.md).
        whp0 = float(WHP[-1])
        dP = BHSP_Pa - (Hp_end + whp0 / KPSI_PER_PA)
        if dP <= 0.0:
            shutin_note = (
                'BHSP %.0f psi is at or below the equalized bottom pressure — '
                'no shut-in rise is drawn.' % job.bhsp_psi)
        else:
            whp0 = float(WHP[-1])
            hyd0 = float(HYD[-1])
            whp_f = max(0.0, whp0 + dP * KPSI_PER_PA)
            hyd_f = hyd0 + dP * KPSI_PER_PA
            t0 = float(T[-1])
            n = max(2, int(round(job.shutin_ramp_min / dt)))
            for k in range(1, n + 1):
                frac = k / float(n)
                T.append(t0 + frac * job.shutin_ramp_min)
                WHP.append(whp0 + (whp_f - whp0) * frac)
                PUMP.append(whp0 + (whp_f - whp0) * frac)   # no flow: no line loss
                HYD.append(hyd0 + (hyd_f - hyd0) * frac)
                DYN.append(hyd0 + (hyd_f - hyd0) * frac)    # static: dyn == hydro
                QI.append(0.0)
                QO.append(0.0)
            t_shutin = t0
            whp_final = whp_f * 1000.0        # psi
            bhsp_used = job.bhsp_psi
    elif BHSP_Pa is not None and frictionless:
        shutin_note = ('BHSP shut-in segment skipped in the hydrostatic-only '
                       'mode (D9: mud PV/YP not supplied).')
    elif BHSP_Pa is not None and tail_capped[0]:
        shutin_note = ('BHSP shut-in segment skipped: the post-job exchange '
                       'did not balance within its guard.')

    res = SimResult(
        t=np.array(T), whp=np.array(WHP), pump=np.array(PUMP),
        hydro=np.array(HYD),
        dyn=np.array(DYN) if DYN else None,
        q_in=np.array(QI), q_out=np.array(QO),
        t_atcp=t_slurry, t_eod=t_eod,
        t_marker=t_shutin,                  # D14: marker = start of shut-in
        t_freefall_start=t_ff0, t_freefall_end=t_ff1,
        final_hydro_kpsi=HYD[-1], hydro0_kpsi=HYD[0],
        t_shutin=t_shutin,
        whp_final_psi=whp_final,
        bottom_shutin_psi=bhsp_used,
        diag=res_diag)
    if shutin_note:
        res.diag['shutin_note'] = shutin_note
    _er01_audit_channels(res)          # ER01-F2: fail-closed raw integrity
    return res


# ----------------------------------------------------------------------------
# Auto-scale rules (documented; source-anchored where the reference job matches)
# ----------------------------------------------------------------------------
# D4: ladder extended below 5 min (1-2-2.5-5 decades) so short jobs get
# meaningful major labels; large-job results are unmoved (43.6 -> (0,50,5,10),
# 254 -> (0,270,15,30) — verified by test).
X_CANDIDATES = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5,
                5.0, 10.0, 15.0, 20.0, 30.0, 60.0, 120.0, 240.0)
Y_CANDIDATES = (0.05, 0.1, 0.15, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0,
                10.0, 20.0, 25.0, 50.0, 100.0)



def run_selftest(verbose: bool = True) -> bool:  # pragma: no cover
    raise NotImplementedError('research-only candidate: no selftest')
