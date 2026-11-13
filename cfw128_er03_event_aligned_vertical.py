# Gate 4B event-stepping derivative; disabled/test-only.
# Frozen parent SHA-256: 79d1a76962c706c305cf9a44ee58778d8ee2ca4231fd02f1a6d52f5b5f231e5f
# Only schedule/event durations, terminal observations and interval audit differ.
#!/usr/bin/env python3
# ============================================================================
# ER-01 DERIVATIVE (release-engineering candidate) — Owner-authorized repair
# batch 2026-11-08.  Derived from the FROZEN G3 research source
# DOC58_SI_CANDIDATE_03_TF2R.py (sha256
# 0841ee338342a7d65054b563e68d8eaa3c2181017dfae382ad4c8917ee17b7f2, preserved
# untouched).  Scope = ER01-F1/F2 ONLY: input validation guards (non-finite
# scalars, physical domain checks) and a post-simulation raw-channel
# integrity audit.  NO physics, coefficient, unit, threshold, stage,
# schedule, scoring or display change.  Vertical lane: no Survey object
# exists here (TVD=MD identity is the vertical contract).
# ============================================================================
# -*- coding: utf-8 -*-
# =====================================================================
# DOC58_SI_CANDIDATE_03_TF2R — 2026-11-04, Owner order 'CFW128 — TF-02R:
# One Bounded Candidate Integrity and Regression Check' (APPROVED
# 2026-11-04, trace 1a1a722a538228bd; resolves the TF-03 Gemini review
# findings that affect engineering acceptance).  Derived byte-faithfully
# from DOC58_SI_CANDIDATE_02_TF1.py (sha256
# c836f4c84f1aa4f1fca0f58b27801446894a873abc29cf71162bf63187f29a64),
# itself derived from DOC58_SI_CANDIDATE_01.py (sha256
# 2a2ab60b2cf4eca7de2daa173786319b3d69be7e56fe6c0454c20861bed64edb,
# itself a byte-distinct research copy of
# fluids_charts_module_v1_4_8_DOC58_frozen.py, sha256
# 4a77114f553189eb64f98cd38731215d1df9bc5ee8b1c509ef7487e7fdd4b91b;
# all ancestors frozen, never modified).  THREE AUTHORIZED CORRECTIONS
# (TF-02R scope 1-2), Herschel-Bulkley paths ONLY:
# (1) Re_MR dimensionality (TF-03 MAJOR-01): _seg_remr now uses the
#     PHYSICAL fluid pair (n, K [Pa*s^n]); the empirical exponent clamp
#     n_eff is applied ONLY inside the Dodge-Metzner correlation
#     (_seg_fdm).  TF-02 passed clamped n_eff with unchanged K, which is
#     dimensionally inconsistent whenever n != n_eff.
# (2) Correlation-domain policy (explicit, untuned): the DM map is used
#     only for N_DM_MIN <= n <= N_DM_MAX (its fitted range).  Out-of-
#     domain fluids keep the ORIGINAL SIx1 turbulent branch (Blasius on
#     Re_gen with its own window anchors and crossing) -- the frozen
#     parent behavior on those spans, bit-exact; no extrapolation of
#     empirical coefficients, no new constants.
# (3) Inverted-edge transition (TF-03 MINOR-01 item 1 / scope 2): when
#     the laminar curve is still above the turbulent map at hi (g_lo2 >=
#     g_hi), the branch switch now occurs at the TRUE crossing of the
#     two monotone curves (at or above hi, found by geometric expansion
#     + the same 60-step bisection).  TF-02 returned hi there, which
#     steps from lam2(hi) down to dm(hi) -- a non-C0 value jump,
#     demonstrated synthetically; the fix is C0 and monotone by
#     construction.  The documented C1 slope corners at the window edges
#     are unchanged (piecewise-smooth; no pressure jumps).
# Applicability, disclosed: DM fitted range 0.36 <= n' <= 1.0 (Dodge &
# Metzner 1959); the engine's frozen fric_pipe_pl path applies DM to all
# turbulent Re_MR (inherited convention, unchanged); the slot application
# inherits the engine's existing Blasius-on-Dh geometric convention (DM
# is pipe-fitted data) and the TF-01 no-slot sensitivity bounds that
# contribution.  Everything else is bit-frozen: laminar/extension/psi-
# schedule physics, RE_LAM and window-edge formulas and their lower
# anchor, Bingham paths, declared-PL paths, solver, schedule/kinematics,
# unit adapter, scorer, thresholds.  No per-well or per-fluid constant
# exists anywhere.
# =====================================================================
"""
fluids_charts_module.py — Three-chart job-simulation page fed by the
Phase IV (phase_4_fluids.py) fluid train.  v1.4.9-ER03 LOCAL
CANDIDATE.  ER-03 (2026-11-08, owner-authorized): D14/D15 BHSP
shut-in law repair — the documented convention (module docstring,
D14 comment, B7 selftest comment) is the ABSOLUTE bottomhole
target pressure at the tracked shoe station; the increment now
acts on the actual pre-shut-in bottom pressure
dP = BHSP - (Hp_end + WHP0), so the endpoint lands at BHSP
exactly and WHP_final = BHSP - string-column head.  Root cause
and two-path proof: ER02R_FINDINGS.md (ER-02R evidence ZIP).
Underlying ER-02 (2026-11-08, owner-authorized): (1) B13
stale-fixture re-adjudication — the D13/D15 laws, the solver and
all ER-01 guards are byte-unchanged; only the selftest fixture
and stale docstrings are repaired with dated disclosure (the
legacy 1256.7 anchor is retained as a dated legacy datum; the
original failing log is preserved in the evidence ZIP).
(2) typed engine-side Tie Back geometry input (DP above Point A):
TieBackInput + build_tieback_geometry +
GeometrySpec.operation_identity — no legacy parser or physics is
touched; the native TIE BACK family stays unsupported-as-is
(TB-01 E1).  Underlying v1.4.8 LOCAL CANDIDATE
(v1.4.7 lineage + F4 free-fall/void equilibrium + F5 zero-yield
PL->HB routing — one additive successor, DOC55 FFX + DOC54B PLHB)
(LOCAL ONLY, not a release; DOC 51R v2 lineage = byte-exact v1.4.3 engine
+ DOC 50 accepted AZNS-179 p4 presentation + D1-D6 display corrections.
The prior v1.4.4 candidate bytes were NOT recoverable (sandbox recycling);
this candidate is rebuilt ONLY from verified parents and never claimed to
be those bytes.  Engine/base additive on the byte-frozen v1.4.2:
owner decisions
D7-D18 + audit patches P1-P3 + Stage-1 volume conservation + Stage-2
free-fall trigger + Stage-3 direct Herschel-Bulkley + Stage-5 G-cache
key fix + Stage-6 laminar calibration factor 2.00 + v1.3.0 DYNAMIC
SEGMENT-LEVEL CORRECTION + v1.4.2 CONTINUOUS ANNULAR PSI-LAW -- the
annular laminar gradient is a C1-continuous local function of the
dimensionless wall-yield ratio psi = tau_y/tau_w; no well names, no
per-well tables, no mode flags anywhere in the system).

--------------------------------------------------------------------------------
WHAT IT DOES
--------------------------------------------------------------------------------
The user enters the fluid train in Phase IV (volumes bbl, densities pcf,
pump rates bpm).  This module turns that exact data contract into the three
report charts of the CEMCADE 2002 job-simulation page:

  Chart 1  (no title — identity = left axis title "Press. (psi) (x 1000)")
           Calc. CemHP        = U-tube wellhead pressure   (UTUBE_WHP)
           Calc. Pump Press.  = CemHP + surface-line loss  (UTUBE_PUMP_WHP)
           Back Pressure / Acquired Pressure = legend-only (source state)
  Chart 2  "Depth =%6.f m"    Hydrostatic + Dynamic annular pressure at depth
  Chart 3  "Fluids at %6.f m" Q In / Q Out (+ legend-only Acquired channels)

Evidence chain: Doc 16 (pixel forensics) -> Doc 17 (documented placement
physics) -> Doc 18 v1.1 (integration with the Phase IV data contract + the
owner-supplied SSOT files engineering_tools.py / rheology.py /
phase_2_3_well_data.py / phase_7_lab.py / materials_db.py, bucket
n8648eao54a7ny8v, sha256-verified 2026-10-10).

--------------------------------------------------------------------------------
DYNAMIC SEGMENT-LEVEL CORRECTION v1.3.0 (2026-10-12 — work order #25)
--------------------------------------------------------------------------------
V1  The t0-frozen regime guard (lam_alpha_policy / L_EFF_GUARD = 0.55)
    is REMOVED.  The laminar factor LAM_ALPHA = 2.00 is now applied
    INSIDE fric_pipe_hb / fric_slot_hb, per segment, at every call:
    every laminar segment (Re_gen <= RE_LAM) carries the correction at
    every time step; turbulent segments use the turbulent branch
    directly (the factor-2 logic transferred into the time/space loop).
V2  The laminar<->turbulent boundary follows the CEMCADE 2002 engine's
    own n-dependent regime window, reverse-engineered from the
    sha-verified frpressc.dll (lower = 3250-1150*n; the DLL upper
    formula; n=1 -> [2100, 3000] == the Newtonian RE_LAM anchor).
    Inside the window the gradient follows a CONTINUOUS log-log blend
    anchored at the segment's own laminar-x2 edge (Re=lower) and
    Blasius edge (Re=upper); where the edges are inverted (the blend
    undefined) the transition is the segment's own laminar-x2/Blasius
    crossing (the DLL's implicit psi-root reduced to module curves).
V3  Evidence: DEHLORAN26-TB whp0 -38.45% -> -2.33% (the tie-back
    annulus is LAMINAR at t0 in the CEMCADE window -- the narrow fully-
    cased annulus deficit of doc 24 was a regime-misclassification, not
    a roughness effect); AZNS-138 -18.18% -> -1.80%; W-MANSURI-1 whp0
    -9.08% -> +5.02% and EOD final -46.0% -> -18.2%; 10 of 12
    reference-valid wells inside the 10% window.  Well C (+43%) and
    AZNS-166 (+63%) are documented reference-side inconsistencies
    (see report 25): C's reference implies laminar x1.22 vs the
    x2.03-2.11 family (the Stage-6 non-monotonic anomaly); AZNS-166's
    reference whp0 sits BELOW its own all-Blasius value -- unreachable
    by any laminar-positive rule.
V6  v1.4.2 (work order #35 / Task 51) CONTINUOUS ANNULAR PSI-LAW:
    the ANNULAR (slot) laminar gradient's static anchors -- the constant
    LAM_ALPHA multiplier and the hard PHI_EXT_GATE switch -- are replaced
    by C1-continuous local schedules keyed on the dimensionless ratio
        psi = tau_y / tau_w
    of the SAME segment (tau_w from the segment's own exact-HB wall
    shear stress tau_w = G*h/2 with the local gap h = (Do-Di)/2; Re_gen
    zone boundaries stay the frpressc.dll algebra):
        m_ann = 1 + (LAM_ALPHA - 1) * s(psi),   s in [0,1] smootherstep
      deep-laminar (Re<=2100):   s = s_lam(psi): 1 below PSI_LAM_KEEP
        (yield-stabilised family: A/W-MANSURI-1-class near-zero-yield
        muds), 0 on [PSI_LAM_PLAIN, PSI_LAM_ASC0] (de-facto power-law
        band: C/B5W2-class), 1 above PSI_LAM_ASC1 (casing band: D/F/B-
        class states 0.027-0.46).
--------------------------------------------------------------------------------
V10 v1.4.7 LOCAL CANDIDATE (work order DOC 52 FINAL ARCHITECT REVIEW
    ADDENDUM — LOCAL ONLY, PRESENTATION ONLY, one bounded correction on the
    authenticated v1.4.6 bytes): the display-axis recomputation now measures
    the Y extent from the portions of each present curve that are actually
    VISIBLE in the current axis_x window — in-window samples plus the
    linearly interpolated values of segments crossing a window edge
    (measurement only; no hydraulic array is mutated, resampled or
    rescaled).  A series lying entirely outside the visible pumping time
    can no longer inflate or distort the presented Y scale; its exclusion
    is disclosed in fig._doc51r_axis_audit as per-panel
    'out_of_window_samples' plus the figure-level 'time_window', distinct
    from the Y-clipping/recomputation disclosure ('above_axis' /
    'recomputed' / 'original_lim').  All previously accepted v1.4.6
    behavior is preserved: fully visible data measures exactly as before,
    healthy caller axes stay byte-identical no-ops, the AZNS-179 p4
    grammar (canvas/panels/colors/units/ticks/legend/events) is untouched,
    and raw physics/numeric outputs are bit-identical under equal inputs.
V9  v1.4.6 LOCAL CANDIDATE (work order DOC 52 — LOCAL ONLY, PRESENTATION
    ONLY, on the v1.4.5 parent):  (B) renderer demo-number defaults removed
    from JobChartsSpec (depth_m/axis_x -> None) with fail-closed
    display-input validation before any drawing — a real chart MUST carry
    the current well depth and current-job axes, and the renderer can no
    longer substitute 3293 m / 270 min.  (D) deterministic, generic,
    DISPLAY-ONLY axis recomputation when a present, validated series
    extends beyond its panel axis (same autoscale grammar, disclosed in
    fig._doc51r_axis_audit; no-clipping audit extended to all three panels
    including optional Q and out-of-window events).  (E) post-job-only
    markers excluded from the pumping_only presentation (raw record and
    event record untouched; genuine in-window markers stay).  Zero physics,
    solver, window-rule or style-constant changes; pumping_only/full_record
    behavior byte-identical to v1.4.5 at like-for-like options.
V7  v1.4.3 LOCAL CANDIDATE (work order DOC 49 — LOCAL ONLY, additive):
    three chart-OUTPUT changes, zero physics/stepping/solver edits:
    (a) ChartOptions.float_equipment (default False) forwarded to
        JobDesign — the App orchestrator seam may now request the owner-
        confirmed Float-ON pumping presentation for chart-applicable
        Casing/Liner/Tieback jobs; the frozen default stays legacy.
    (b) ChartOptions.plot_window: 'full_record' (default = the v1.4.2
        bytes exactly) or 'pumping_only': the RENDERED series/axes use
        only samples the engine itself recorded on the PUMPING branch
        (t < t_eod - 1e-9, the simulate() branch split); post-EOD
        samples (the single tail-cap/balance sample a zero tail guard
        still records at EOD, tail samples, and the D14 ramp) stay in
        the raw SimResult untouched and are excluded from the PLOT
        only.  Fixes the artificial terminal Q plunge, the terminal
        WHP jump and the terminal dynamic->hydrostatic drop that the
        six CemCADE reference PDFs never show.  An additive
        res.diag['plot_window_audit'] key documents rule + counts.
    (c) tail_capped warning classification: with tail_cap_min == 0 the
        deliberate tail disable is reported as an intentional pumping
        presentation, not as a failed equalization; a REAL nonzero-cap
        guard failure keeps the original v1.4.2 warning verbatim.
    No equation, friction law, root selection, mass balance, source
    value, schedule, state, schema or export semantics is changed.
--------------------------------------------------------------------------------
      extension (2100<Re<lower): the hard phi-gate becomes the same C1
        ramp s_ext(psi) (0 below PSI_EXT_0 -> 1 above PSI_EXT_1); A's
        psi=0.00049 section stays plain, DEH/138's 0.12-0.28 stay x2.
      window (lower<=Re<upper): the blend edge is scheduled by s_win at
        the segment's LIVE state (1 below PSI_WIN_KEEP -- W-MANSURI-1-
        class; 0 above PSI_WIN_PLAIN -- AZNS-166-class liner window
        states; 1 above PSI_WIN_ASC1 -- RW1-class deep-liner states).
    The STRING (pipe) law is FROZEN v1.3.1 (LAM_ALPHA=2.00 family,
    bit-identical); Bingham/PL paths, volumes, float/free-fall, audit
    and the selftest corpus are bit-identical.  Evidence (doc 35):
    23-well annular-only counterfactual (LAM_ALPHA=1 in the annular
    space) + per-segment psi census; two disclosed razor pairs
    (AZNS-166@0.0466 vs RW1@0.0537 window; 166-seg0@0.0922 vs 172@0.0915
    deep-laminar) resolved by the mission priority order (W-MANSURI-1
    hard gate > casing zero-loss > C/W2/166 containment).  The regime
    boundaries (RE_LAM / lower(n) / upper(n)) remain the DLL's own map;
    the schedules are C1 WITHIN each band (the v1.3.1 low-psi LAM/EXT
    split is the A-well evidence and is preserved).
V5  v1.3.1 (work order #26) REGIME-MAP REFINEMENT: the n-window
    EXTENSION zone (2100 < Re_gen < lower(n)) now carries the PLAIN
    exact-HB laminar gradient; LAM_ALPHA=2.00 stays confined to the
    deep-laminar branch (Re_gen <= 2100, the v1.2.7 guard domain) and to
    the CEMCADE window blend (lower <= Re_gen < upper, unchanged -- it
    carries DEHLORAN26-TB / AZNS-138 / W-MANSURI-1).  Rationale (work
    order #26 item 3): well A's +32.18 psi whp0 regression was ONE 140 m
    annulus section (Re_gen = 2164.4, n = 0.3944) flipped from Blasius
    (211,080 Pa) to x2-laminar (432,982 Pa) at t0 -- the extension-zone
    x2 sits 2x above the reference exactly where the module's own
    a1-laminar crosses Blasius.  The deep-laminar x2 and the window
    blend are UNTOUCHED; the turbulent branch is bit-identical.
    Evidence: fr26_diff.py instrumented bucket diff (A: +221,902 Pa at
    the whp0 point = the whole regression); fr26_hyprun.py t0 convention
    scan; 18-combination reference search (no single state-function can
    satisfy A@2164 turbulent AND DEH-pipe@2345 x2-laminar -- the
    reference is state-inconsistent between those wells; documented in
    doc 26).  selftest 38/38 PASS; Leak = 0.000 bbl preserved.

V4  Bit-preservation: RE_LAM, LAM_ALPHA, the turbulent Blasius branch
    (Re >= upper), Bingham/PL paths, volumes/float/free-fall/audit --
    unchanged; selftest 38/38 PASS; Leak = 0.000 bbl on all runs.

--------------------------------------------------------------------------------
LAMINAR CALIBRATION FACTOR + REGIME GUARD v1.2.7 (2026-10-11 — Stage 6)
[archive: the guard below was REMOVED in v1.3.0 — see V1 above]
--------------------------------------------------------------------------------
Owner decisions (Stage-6 work order): the calibrated laminar factor is
EXACTLY 2.00 (the Fanning/Darcy -- or slot-Dh -- convention collision
proved by the Stage-5 alpha scan, doc 21), applied to the laminar
gradient of BOTH columns, gated by a regime guard so wells whose t0
wellhead pressure is NOT laminar-supported stay untouched.
L1  Factor: LAM_ALPHA = 2.00 multiplies the laminar return L*G of the
    direct-HB friction functions only (fric_pipe_hb / fric_slot_hb).
    Turbulent Blasius, Bingham and power-law paths are BIT-UNCHANGED
    (the Stage-5 evidence scope is the direct-HB engine; the Bingham
    path carries its own Stage-1/2 calibration).
L2  Regime guard (lam_alpha_policy, a pure function of the job): at the
    t=0 state (both columns full of the displacement fluid, pumped rate
    r_in(0) -- the exact state whp0 is evaluated on) it measures
        F1 = total raw circulating friction (sum of section dP)
        F2 = the same with the laminar-factor probe (alpha = LAM_ALPHA)
        L_eff = (F2 - F1) / F1
    (F2 - F1) isolates the laminar-gradient share EXACTLY: a laminar
    direct-HB section contributes L*G*(alpha-1); every alpha-
    insensitive section (turbulent Blasius, Bingham/PL paths, zero
    length/rate) contributes 0.  whp0(alpha) = alpha*F_lam + F_turb is
    exactly linear (Stage-6 audit), so L_eff is the laminar-supported
    share of whp0.  GUARD: L_eff >= L_EFF_GUARD (0.55) -> alpha =
    LAM_ALPHA for the whole run; else alpha = 1.0 (bit-identical to
    v1.2.6).  Evidence (cfw7_st6_caudit.json): family L_eff = A 0.806,
    B 0.637, D/E/F 1.000 (guard ON) vs C 0.467, G 0.006 (guard OFF;
    C alpha* ~ 1.224, G has no laminar leverage) -> the 0.55 threshold
    splits the families with ~8.5 pp margin on both sides.  Blind
    alpha = 2.00 on C would jump the error to +32.8%.
L3  Acceptance (Stage 6): selftest 38/38 unchanged (demo job = Bingham
    mud at t0 -> guard OFF -> demo bit-identical); wells A/B/D/F errors
    < 5%, C and G kept inside +/-10% (guard exemption, owner decision);
    Leak = 0; state-leak False->True->False bit-identical.

--------------------------------------------------------------------------------
v1.2.7 HARDENING (2026-10-11 — owner-ordered post-approval, numerically inert)
--------------------------------------------------------------------------------
H1  Guard logging status: the lam_alpha_policy diag now carries an
    explicit status field in {'OK_ON', 'OK_OFF', 'ERROR'}:
      OK_ON   = guard computed, L_eff >= L_EFF_GUARD, alpha = LAM_ALPHA;
      OK_OFF  = normal alpha = 1.0 path -- guard computed below the
                threshold, or a deterministic degenerate t0 state
                (frictionless job / no pumpable stage / zero t0 rate /
                zero t0 friction); the exact reason is in diag['reason'];
      ERROR   = exception during the L_eff probe -> the fail-safe
                alpha = 1.0 result is FLAGGED so it can never be
                mistaken for the normal OFF state.
    simulate() exports the status BOTH inside diag['lam_alpha_policy']
    AND as a separated top-level key diag['lam_alpha_policy_status'] so
    diagnostics dumps in the diagnostics directory can be triaged
    directly (grep/filter on the status, no nested-key digging).
H2  L_EFF_GUARD = 0.55 is explicitly documented as a DATA-DRIVEN
    HEURISTIC calibrated on Batch-7 only (falsifiability +
    re-calibration rule stated at the constant definition).
H3  Numerics untouched: the hardening diff is add-only on diag
    metadata + comments/docstrings.  Regression on the hardened build
    (doc 23): selftest 38/38; final 7-well table whp0 bit-equal to the
    v127_bit_targets; state-leak 4/4 with Stage-3 fingerprint match;
    C/G trajectories bit-identical to v1.2.6.

--------------------------------------------------------------------------------
AUDIT PATCHES v1.2.2 (2026-10-10 — formal owner-ordered audit of v1.2.1)
--------------------------------------------------------------------------------
P1  put_bottom() keeps the multi-chunk slug order: the chunk deepest in
    the source column stays deepest in the destination (the old
    sequential insert(0) reversed it within one dt step).  take_bottom /
    put_bottom moved to module level so selftest B16 exercises them.
P2  The host walk refuses string-family rows by DESCRIPTION (Drill Pipes
    / Drill Pipe / Tubing / Liner Hanger), not only by row identity — a
    content-different duplicate can no longer leak into host_spans.
P3  Doc-only: the ATCP event wording states what the code actually
    watches — the annulus bottom (shoe depth), not a query at the track
    depth.  Audit verdict on v1.2.1: CONFORMS to D7-D18 + Doc 18
    (R1/R2/R4/R6/B1/B4/B13/I1-I3 traced; anchors unaffected; the P1
    effect is bounded by one dt-step volume).

--------------------------------------------------------------------------------
G-CACHE KEY FIX v1.2.6 (2026-10-11 — owner-ordered Stage 5, item 3)
--------------------------------------------------------------------------------
Defect (found in the Stage-4 side-effect hunt, cfw7_st4_keyaudit.json):
the v1.2.5 memoization key rounded the flow rate to 3 decimals on
m3/s (_hb_G_cached: round(q, 3)).  All field-rate buckets collapse to
~0.19 bpm wide bins, so the FIRST call filled the bucket with its own
exact-q G and every later q inside the same bin REUSED that G
(first-come reuse).  Consequences: whp0 immune (first call per bucket
carries the exact rate G), but free-fall trajectories became
call-order dependent — well A's final wobbled 3.26 psi (0.45%) when
extra fric_pair diagnostics shifted the call order.
Fix (owner work order, no physics touched):
K1  EXACT key: the flow rate enters the key as the full-precision
    float (no rounding).  dict lookup on an identical float is exact;
    a different q now always solves its own G.
K2  CLEANABLE structure: the per-Fluid cache is a bounded LRU
    (collections.OrderedDict, capacity _HB_CACHE_MAX = 4096 entries,
    oldest evicted on overflow, move_to_end on hit).  Eviction cannot
    change results: _hb_solve_G is a pure deterministic function of
    the key, so recompute-after-evict is bit-identical.  The cache
    still lives and dies with the Fluid instance (no cross-job
    state), and its footprint is now capped.
K3  Bingham / power-law / turbulent paths, the solver itself, and
    every rheology constant are BIT-UNCHANGED.  Regression contract:
    selftest 38/38 PASS; state-leak False->True->False bit-identical
    (legacy fingerprints unchanged); whp0 of all 7 batch wells
    unchanged; free-fall finals now call-order independent.

--------------------------------------------------------------------------------
DIRECT HERSCHEL-BULKLEY CORE v1.2.5 (2026-10-10 — owner-ordered Stage 3 of 4)
--------------------------------------------------------------------------------
Field evidence (cfw7_st3_diag.json, v1.2.4 locked, 7 batch wells):
H1  the Bingham-equivalent mapping (th600/th300 -> PV/YP) is exact by
    construction at 511/1022 1/s but its stress error at the OPERATIVE
    annular shear rates (5-500 1/s measured at t0 across all wells) is
    2.4x-9.2x; in the near-plug deep-laminar slot the fixed-point cap
    phi <= 0.98 collapses the gradient (F hb/bing 24-41x, A 10.5x,
    G-ann 9.2x at q0) while inside large-ID pipe the same mapping
    OVER-predicts (D-pipe 0.33x, C 0.22x, E 0.21x).
H2  narrow-slot vs exact concentric annulus (Newtonian-validated exact
    solver): conc/slot = 0.982-0.999 on every t0 section (h/w <= 0.184)
    -> the slot form is NOT the deficit driver.  CEMCADE help documents
    De = Do - Di explicitly for the STATIC yield term only (dP = 4 L ty
    / De, image bm9); no dynamic-friction formula exists in the help
    text or in images bm0-bm9 -> the dynamic side is NOT VERIFIABLE
    from documentation.
H3  regime: EVERY section of every well is LAMINAR at t0 under both the
    module Bingham Re (mu_p only) and the HB generalized Re (effective
    viscosity incl. tau0; Re_gen <= 261, q_crit 45-1950 bpm vs stage
    rates 3-10 bpm) -> the 8-37x whp0 error narrative is NOT a
    turbulent-f issue at field rates.
Fix (owner-approved: port the TEST-1-validated exact HB solver):
HB1 new core: _hb_q_slot/_hb_q_pipe (exact HB laminar profile
    integration: plug band where wall shear <= tau0, trapezoid N=800)
    + _hb_solve_G (bisection on the wall shear-stress gradient, N=120)
    + fric_pipe_hb/fric_slot_hb with the TEST-1 turbulent branch
    (Re_gen > 2100 -> Blasius f = 0.0791/Re^0.25 on Dh = 2wh/(w+h)
    annulus / D pipe).
HB2 dispatch: a fluid with mu_p_cp == 0 AND n_pl > 0 AND K_pl > 0 AND
    tau_y > 0 now flows through the DIRECT HB core (the file fields
    CEM_FLU_HB_N/K/TY enter as-is, no mapping).  Bingham fluids
    (mu_p_cp > 0) keep the legacy path bit-for-bit; pure power-law
    fluids (tau_y == 0) keep the legacy PL path bit-for-bit.  The
    Gel/static-exchange logic (D13) still uses tau_y/gel and is
    untouched.
HB3 the G-solve cache lives ON the Fluid instance (fl._hb_cache),
    keyed by (kind, dims, q, n, K, tau0, rho) -> pure memoization,
    dies with the fluid object: no cross-job state can leak, and a
    False->True->False job sequence is bit-identical (regression
    tested).
No rheology constant was touched.  The turbulent-f audit (Stage 4)
and any annular-geometry revisit remain owner-gated next stages.

--------------------------------------------------------------------------------
FREE-FALL TRIGGER FIX v1.2.4 (2026-10-10 — owner-ordered Stage 2 of 4)
--------------------------------------------------------------------------------
Field evidence (instrumented 7-well trigger log vs stored CEMCADE curves):
M1  forward free-fall: trigger sign discipline is EXACT (0 violations in
    ~2,900 logged branch decisions; algebraic static = Hp - BP - Ha, no
    abs(), no latch).  CEMCADE free-falls on the same wells (A/C/E/F:
    WHP <= 0.5 psi windows with Q Out > Q In excess returns).
M2  false collapse: the reverse branches (gapclose/freeex) hardcoded
    WHP = 0 whenever the annulus side is heavier — an OPEN pipe head.
    The module has NO float equipment anywhere (0 hits); CEMCADE instead
    HOLDS differential + friction (B/D/F held ~2452-2550 / 896-1032 /
    86-130 psi while the module showed 0).
Exit condition pinned from data (single closed form, no ambiguity):
    free fall persists until the pipe-top void is EMPTY.  Stored-curve
    signature: a deficit phase Q Out < Q In (pump excess refills the
    void) ending with Q Out snapping to Q In EXACTLY at the WHP re-
    pressurization sample (A/C/E/F).  Deficit integral == void volume
    (27.9/36.1/90.3/34.0 bbl vs the module gap 37.9/25.1/87.3/66.9 bbl).
Fix (pumping phase only; the post-job tail D13/D14 is untouched):
F1  new 'ffrefill' branch: void open -> free-fall state persists
    (WHP = 0) while the pump excess (r_in - natural fall) refills the
    void; Q Out = natural fall < Q In (CEMCADE deficit signature);
    re-pressurization exactly when gap -> 0.
F2  float equipment: while pumping, the annulus can no longer push back
    out of the open head — the reverse branches are retired for the
    pumping phase; an annulus-heavy well pumps against the locked
    differential: WHP = max(0, BP + Ha + Fa - Hp + Fp) (never 0 by
    construction).  Books stay exact: Q In - Q Out == -d(gap) in
    ffrefill; the annulus is untouched by the refill.
F3  the float state is an EXPLICIT job input — JobDesign.float_equipment
    (default False = the documented open-head legacy path, kept for the
    demo/selftest anchors: A9's gel tail expects the slurry slumped INTO
    the string with WHP -> 0 and B13's owner hand cross-check (~25 m)
    assumes the same open-shoe equalization — both impossible with a
    float, so the demo scenario is open-shoe by the owner's own
    validated anchors).  Casing/liner jobs with float collar + plugs
    (all 7 .cfw batch wells) run with float_equipment=True — the
    field-evidenced configuration.  The host decides the wiring; nothing
    is invented silently.
F4  (DOC55) free-fall/void equilibrium: the freefall and ffrefill void
    moves are clamped at the closed-form void equilibrium gap* where the
    fall drive exactly equals the pump rate (Hp(gap*) - Fp(r_in) - BP -
    Ha - Fa(r_in) = 0; Hp linear in the open top void).  The event is
    resolved INSIDE the step instead of being overshot and re-crossed
    every other step — removes the dt-independent freefall<->ffrefill
    two-cycle without any new constant, per-well data, or friction
    change; the booked move IS the flow, so the mass books stay exact;
    far from the equilibrium the update is bit-identical to v1.4.7.
F5  (DOC56) zero-yield PL->HB routing: power-law fluids with
    n_pl > 0, K_pl > 0 and tau_y == 0 route through the direct-HB path
    (the CEMCADE DLL laminar convention + regime map) instead of the
    legacy plain-PL path.  Accepted after the four Gemini controls
    (tau_y-continuity 3.2e-5 psi << 0.01 psi gate at 1e-6 lbf/100ft2;
    BRW1 dt 0.25/0.05/0.02 stable; corpus-wide all-fluid-stage census:
    exactly ONE zero-yield pumped stage in 21 wells / 90 stages; the
    real-App Bingham lane proven bit-identical).  Bingham fluids
    (mu_p > 0), tau_y > 0 fluids and the frictionless fallback are
    untouched by construction.

--------------------------------------------------------------------------------
VOLUME CONSERVATION FIX v1.2.3 (2026-10-10 — owner-ordered Stage 1 of 4)
--------------------------------------------------------------------------------
Instrumented field evidence on the 7 batch wells (bin 3r2izaizldt7kqdi)
showed three bookkeeping defects; every recorded imbalance reconciles
exactly (|residual| <= 0.2 bbl) as  GC_over - freeex_backflow + FX_draw:
V1  free-exchange (void closed): the head backflow q_rev left the well
    WITHOUT being booked in Q Out  (E -643.8, F -825.5 bbl); and when
    q_rev > r_in the net reverse draw was taken from the PIPE instead of
    the annulus (E -20.6, F -39.9 bbl).
V2  gap-close (void open): the void shrank by q_rev*dt with NO fluid
    entering the pipe (Cp + gap == V_pipe0 broken, res_pipe down to
    -107.9 bbl) AND Q Out booked the full pump rate although the void
    swallowed part of it (over-report up to +87.3 bbl).
V3  post-job tail reverse: head overflow left the well unrecorded
    (latent: 0.0 bbl on all 7 wells this batch).
Fix = port-wise incompressible continuity at every step:
  freeex  : backflow BOOKED in Q Out; net reverse draw taken from the
            annulus (its level falls); Q Out = mouth + head out.
  gapclose: the void closes at min(q_rev, r_in, gap/dt) — the SAME cap
            as v1.2.2 — but the fill now COMES FROM THE PUMP LANDING:
            the returns dip by exactly the fill rate, the void fill is
            pipe content (Cp + gap == V_pipe0 invariant holds), the
            annulus stays full and nothing exits at the head while the
            void is open.
  tail    : head overflow booked in Q Out.
  Q Out now = total physical surface outflow (mouth + head), so
  (Q In - Q Out) == d(inventory) holds EXACTLY; the annulus-top rate
  (mouth) drives the annular friction above the track depth.
A volume audit (branch minutes / leak / pipe-invariant drift) is
accumulated unconditionally and exported in SimResult.diag['vol_audit'].

--------------------------------------------------------------------------------
OWNER DECISIONS D7-D14 (2026-10-10 — all confirmed, nothing guessed)
--------------------------------------------------------------------------------
D7  Spacer / Pre Flush rheology: the HOST APP will provide PV/YP per fluid
    (Bingham model).  This module reads the fluid-record fields "pv_cp" and
    "yp_lbf100ft2".  *** NOTE FOR THE HOST ***: these data are entered by the
    operator; wire them into the Phase IV/VI records.  Until a fluid carries
    them, that ONE fluid contributes hydrostatic pressure only (zero
    friction) and a named warning is returned — nothing is invented.
D8  Cement-slurry friction uses the Bingham fit of the lab dataset
    "bhct_down" (BHCT — Ramp-Down) from Phase VII (rheology.py engine).
D9  Mud PV/YP: if effective_pv/effective_yp (Phase II/III) are NOT supplied,
    the WHOLE chart set is computed hydrostatic-only with a warning; if
    supplied, their values are used as-is for mud / Displacement Fluid.
D10 Hardware MD intervals ("1200.0-2816.0"): the BOTTOM (larger) end is the
    shoe / TD end (owner: "پایین دیگه ته چاه").
D11 U-tube geometry from hardware_table — CONFIRMED by the owner
    (2026-10-10) for casing jobs:  string leg = the placement TARGET row
    (ID inside, Size outside, bottom of the MD cell = shoe); return leg =
    annulus between the string OD and the PREVIOUS CASING ID inside the
    covered hole, and the OPEN-HOLE bit size below the previous-casing
    shoe.  Implemented as TWO annulus sections (v1.1 used the bit size
    everywhere — documented limitation now removed).
D11b Liner / Tie-Back jobs (owner addendum, verbatim semantics):
    LNR 7" / TIE BACK LNR 7"  -> the flow goes down INSIDE the liner and
         returns "از توی لاینر می‌ره توی ID 9 5/8 روی لبه": at the liner
         top (the hanger edge) the return crosses into the 9 5/8" ID.
    LNR 5" / TIE BACK LNR 5"  -> same, crossing into the 7" LINER ID.
    Implemented: above the hanger the annulus inner wall is the work-
    string (Drill Pipes / Tubing) OD and the outer wall is the host ID;
    below it the inner wall is the liner OD.  For a tie-back the string
    leg continues INSIDE the old liner from the tie-in depth to the old
    liner shoe (the flow passes "از توی لاینر").
D11c CMT PLUG / CMT SQUEEZE jobs: "این ۳ نمودار رو نداریم" — the three
    job-simulation charts are NOT produced for plug / squeeze jobs;
    geometry_from_hardware() refuses them with a named error.
D16 LNR running string CONFIRMED by the owner (2026-10-10, Q12): from
    surface to the hanger the Running String is modeled as Drill Pipe
    ("برای لاینر ما همیشه drill pipe پر می کنیم در جدول").  Owner size
    convention: 7" liner -> 5" DP (ID 4.276); 5" liner hung in 7" ->
    5" DP (ID 4.276); 5" liner hung in 5" -> 3.5" DP (ID 2.764).  The
    module NEVER infers the DP size from the liner size — ID/Size are
    read from the Drill Pipes row (Tubing fallback kept: the owner
    confirmed the quoted rule text as-is).
D17 DP / Tie-Back MD cells are POINT depths (owner, Q13: "به صورت نقطه
    مثلا ۲۸۱۶.۰"; Top Depth = surface implicit, Bottom Depth = hanger /
    tie-in).  A point cell is the NORMAL owner form — accepted silently;
    only an interval whose top is not 0 warns "assumed run from surface".
D18 TIE BACK chart bottom = the tie-in / "Tie Back Sleeve" depth (owner,
    Q14: "کف تای‌بک در نمودار ۲۷۰۰ است، سپس مسیر داخل لاینر تا ۳۲۹۳.
    همین درسته") — then INSIDE the old liner to its shoe.  The
    tie_back_origin summary field is report metadata only and does not
    change the charts.
D12 Validators are IMPORTED from engineering_tools.py (app-wide DRY rule) —
    no local copies: clean_number, format_to_hr_mm, parse_fractional_size.
D13 Gel: the measured 10-min gel of the SAME dataset (bhct_down) per slurry
    holds the column in the post-job exchange (static gel governs after the
    pump stops; the fitted YP governs while pumping).
D14 BHSP: free text "xxxx+xxxx" -> the LARGER number is used (owner).  The
    post-job shut-in segment anchors the bottomhole pressure to BHSP:
    WHP_final = BHSP - string-column head; the annular lines rise with it.
D15 Shut-in balance CONFIRMED by the owner (2026-10-10, honest note):
    "در توازن پس از کار، کمی دوغاب در رشته رانده شده ... همیشه مقداری
    دوغاب حدود ۲۵ متر می‌مونه" — in the post-job equilibrium a small
    slurry column is driven INTO the string and stays there, so the
    shut-in formula sees the REAL string column (mud + remnant slurry),
    not a pure mud column.  The engine computes the remnant; it is NEVER
    hard-coded.  The shut-in string slurry length is reported in
    res.diag["shutin_string_slurry_m"] for cross-checking against the
    owner's well (the owner's ~25 m figure is HIS string cross-check —
    never a fixture here).
    ER-02 (2026-11-08) stale-claim correction, owner-authorized: the
    earlier text asserted "the demo lands on WHP_final = 1256.7 psi —
    the SAME value the owner's reference CEMCADE demo shows (vs 1434 psi
    for a naive mud-only column)".  Adjudicated with an independent
    oracle (agreement 6.8e-13 psi; ER02_B13_ADJUDICATION_LEDGER.md in
    the evidence ZIP): on the frozen-era demo (78.1 pcf mud) the
    documented D13/D15 law lands on WHP_final = 1378.6240549319057 psi
    with a 518.26 m remnant; 1256.7 +/- 1.5 psi reproduces only with an
    older ~80.0 pcf demo mud weight.  1256.7 is retained as a DATED
    LEGACY DATUM (stale fixture), not a live anchor; the naive mud-only
    reference on today's demo computes to 1440.4 psi (owner quoted
    ~1434 on his figures).
    ER-03 (2026-11-08, owner-authorized) law correction: the 1378.62
    psi value quoted above was the DEFECTIVE increment-over-residual
    endpoint (BHSP + WHP0 — ER02R two-path proof).  Under the absolute
    BHSP target (dP = BHSP - (Hp_end + WHP0)) the SAME frozen-era demo
    lands at WHP_final = 1244.8879731453767 psi with the SAME
    computed remnant — the documented identity WHP_final = BHSP -
    string-column head now holds exactly.  The ER-02 endpoint value is
    retained above as a dated record of the superseded implementation.

--------------------------------------------------------------------------------
RHEOLOGY MAP (per active fluid)
--------------------------------------------------------------------------------
    Displacement Fluid / mud : mud_pv_yp = (PV[cP], YP[lbf/100ft2]) from
                               Phase II/III effective_pv / effective_yp.
                               Missing -> hydrostatic-only mode (D9).
    Main/Lead/Lead #1/Lead #2/Tail : slurry_rheology entry, normally built
                               by rheology_from_lab() from the Phase VII
                               lab payload (dataset bhct_down, D8):
                               {"pv_cp":…, "yp_lbf100ft2":…, "gel_10_min":…}.
                               Missing -> that slurry is hydro-only + warning.
    Pre Flush / Spacer / Spacer Ahead / Spacer Behind :
                               the record's own "pv_cp"/"yp_lbf100ft2"
                               fields (D7).  Missing -> hydro-only + warning.
    Explicit override        : rheology={name: {"pv_cp":…, "yp_lbf100ft2":…}
                               | {"n":…, "K_pas":…}} wins over everything
                               (diagnostic / legacy path).
    rheology="hydrostatic"   : frictionless diagnostic mode (Q Out = Q In).

Unit conversions (exact, no approximations):
    ppg = pcf / 7.48052          (1 ft3 = 7.48052 US gal)
    gradient[psi/ft] = pcf / 144
    head[psi] = 0.052 * ppg * H[ft] = pcf/144 * H[ft]
    tau[lbf/100ft2] -> Pa: * 0.47880259  (1 Pa = 2.088543 lbf/100ft2, the
    exact inverse of rheology.py's own factor)

--------------------------------------------------------------------------------
EVENTS (user-confirmed semantics)
--------------------------------------------------------------------------------
    ATCP green line : first slurry reaches the annulus bottom (the
                      track depth — P3 wording, semantics unchanged)
    EOD  green line : end of displacement = max(cumul_time_min)
    post-job tail   : U-tube equalization after the pump stops ("WHP -> 0"
                      open-system principle), resisted by the static gel of
                      every column segment (D13) until balance (~1 psi) or
                      the 60-min guard (warned).
    gray marker     : end of the cementing operation.  With a BHSP shut-in
                      segment (D14) the marker is the START of that segment
                      (the equalized well closes; the final rise follows —
                      the source page shows marker 244 then rise to 254).
                      Without BHSP the marker coincides with EOD and is
                      suppressed (no duplicate line).

--------------------------------------------------------------------------------
USAGE (Streamlit host)
--------------------------------------------------------------------------------
    from fluids_charts_module import (build_three_charts, geometry_from_hardware,
                                      rheology_from_lab)
    geo = geometry_from_hardware(st.session_state["hardware_table"],
                                 target_row=<placement target row dict>,
                                 job_type=<JOB_TYPES entry, e.g. 'CSG 9 5/8"'
                                 | 'LNR 7"' | 'TIE BACK LNR 5"'>,   # D11b/D11c
                                 td_m=st.session_state["geo_md"])
    slurry_rheo = rheology_from_lab(
        {s: st.session_state.get("lab_payload_" + s)
         for s in ("Main", "Lead", "Tail") if ...})       # dataset bhct_down
    mud = st.session_state.get("effective_pv"), st.session_state.get("effective_yp")
    fig, res, warns = build_three_charts(
        st.session_state["fluid_data"], geo,
        mud_pv_yp=mud, slurry_rheology=slurry_rheo,
        bhsp=st.session_state.get("well_data", {}).get("bhsp"))
    st.pyplot(fig)

Command line:
    python3 fluids_charts_module.py             # demo PNG
    python3 fluids_charts_module.py --selftest  # A1-A16 + B1-B16 + R1-R4
"""

import math
import os
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import matplotlib
if os.environ.get("FLUIDS_CHARTS_AGG", "0") == "1":
    matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.lines import Line2D                  # noqa: E402

# ----------------------------------------------------------------------------
# D12 (owner decision): validators come from the app-wide single source of
# truth engineering_tools.py — the same imports every other phase uses (DRY).
# No local copies are kept.  The host repo ships engineering_tools.py
# (which imports materials_db + rheology, both owner files).
# ----------------------------------------------------------------------------
from engineering_tools import (clean_number,            # noqa: E402  F401 used below
                               format_to_hr_mm,         # noqa: E402  F401 used below
                               parse_fractional_size)   # noqa: E402

# ----------------------------------------------------------------------------
# Style locks — Doc 16 section 3 (pixel forensics, accepted, unchanged)
# ----------------------------------------------------------------------------
# DOC 50 accepted AZNS-179 p4 presentation constants (byte-accepted in
# DOC 50; measured on the reference page bitmaps).  These are FIXED approved
# presentation specifications — not job-derived data.
PANEL_BG    = '#F0F0F0'      # measured 240,240,240 (engine value already exact)
GRID_GRAY   = '#C0C0C0'      # measured 192,192,192  (v1.4.3 had #C9C9C9)
FRAME       = '#000000'      # measured black (v1.4.3 had #222222)
TICK_COLOR  = '#000000'
TEXT_COLOR  = '#000000'
LEGEND_BG   = '#FFFFFF'
LEGEND_EDGE = '#000000'

RED    = '#FF0000'           # measured exact
NAVY   = '#000080'           # measured exact
GREEN  = '#008000'           # measured exact
ORANGE = '#FF8000'           # measured exact
BLUE   = '#0000FF'           # measured (v1.4.3 had #0000CD)
EVENT_GREEN = '#00FF40'      # measured exact 0,255,64 (v1.4.3 had #00D200)
MARKER_GRAY = '#808080'

LW_THICK  = 4.1              # ref 5px @137dpi = 2.62pt x1.553
LW_THIN   = 0.9              # ref ~1px = 0.6pt x1.553
LW_EVENT  = 0.8              # ref 1px = 0.52pt x1.553
CEMHP_DASH = (0, (2.4, 5.7))  # round-cap dash; visual on~6.5pt off~1.6pt

T_TITLE, T_LEGEND = 19.0, 12.5
T_AXIS_Y, T_AXIS_X = 20.0, 17.0
T_TICK_X, T_TICK_Y = 17.0, 10.5   # reference asymmetry: x ~11pt em vs y ~7pt em
T_AXIS, T_TICK = T_AXIS_Y, T_TICK_Y   # legacy names at shared call sites

YLABEL_C1 = 'Press. (psi)'            # direct psi on the reference (no x1000)
YLABEL_C2 = 'Ann. Pressure (psi)'
YLABEL_C3 = 'Flow Rate (bbl/min)'
X_LABEL   = 'Time (min)'

#: D1: presentation font policy — applied PER FIGURE via plt.rc_context in
#: render_three_charts/save_png.  Nothing is registered or mutated at import
#: time (the doc50 merge leaked here — DOC51R D1); no private font file is
#: imported or shared: the host's installed sans stack is used, with
#: matplotlib's built-in fallback when Liberation Sans is absent.
_FONT_RC = {'font.sans-serif': ['Liberation Sans', 'DejaVu Sans'],
            'font.family': 'sans-serif',
            'axes.unicode_minus': False}

# ----------------------------------------------------------------------------
# Unit constants (documented field units <-> SI) — Doc 17 section 2
# ----------------------------------------------------------------------------
PPG_TO_KGM3     = 119.826427
LBF100FT2_TO_PA = 0.47880259
CP_TO_PAS       = 1.0e-3
BBL_TO_M3       = 0.15898730
BBL_PER_M3      = 1.0 / BBL_TO_M3
M_TO_FT         = 3.28083990
G0              = 9.80665
PA_TO_PSI       = 1.45037738e-4
KPSI_PER_PA     = PA_TO_PSI / 1000.0
GAL_PER_FT3     = 7.48052          # exact conversion basis
PPG_PER_PCF     = 1.0 / GAL_PER_FT3

#: Post-job equalization: U-tube balance tolerance (~1 psi) and the documented
#: "WHP -> 0" open-system principle (cem_Placementh.hlp, Principles).
TOL_STATIC_PA = 7000.0

PCF_PER_PPG = GAL_PER_FT3


def pcf_to_ppg(pcf: float) -> float:
    return pcf * PPG_PER_PCF


def ppg_to_pcf(ppg: float) -> float:
    return ppg * PCF_PER_PPG


def rho_si(rho_ppg: float) -> float:
    return rho_ppg * PPG_TO_KGM3


# ----------------------------------------------------------------------------
# Input contracts
# ----------------------------------------------------------------------------
class ChartInputError(ValueError):
    """Raised for Phase-IV data that cannot produce honest charts."""


class ChartResultIntegrityError(RuntimeError):
    """ER01-F2: post-simulation raw-channel integrity failure (fail-closed).

    Raised inside simulate() before any renderer/scorer can consume a
    SimResult whose required raw channels are non-finite, misaligned or
    inconsistently sized.  This is a sanity gate, never a repair hook: no
    clipping, coercion-to-zero, sample dropping or smoothing is performed
    or permitted on raw data."""


#: ER01-F1/F2 documented float-dust tolerance, metres.  Slack for segment
#: slope and datum checks only; it is NOT an engineering tolerance and
#: introduces no new bound on any legitimate trajectory.
ER01_TOL_M = 1e-6


def _er01_finite(value, label):
    """ER01-F2 shared validator: value must be a finite float.

    Physical bounds (>0, >=0) stay at the existing documented check sites
    so their exact, actionable messages are preserved; this helper only
    rejects NaN/+-Inf (which silently bypass every comparison-based guard
    because NaN comparisons are False)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ChartInputError("%s must be a finite number; got %r."
                              % (label, value))
    if not math.isfinite(v):
        raise ChartInputError("%s must be a finite number; got %r."
                              % (label, value))
    return v


def _er01_audit_channels(res):
    """ER01-F2 post-simulation raw-channel integrity gate (fail-closed).

    Runs at the end of simulate(), before the SimResult is returned, so no
    renderer/scorer can ever receive a non-finite or misaligned raw
    channel.  res.dyn is None remains the DOCUMENTED frictionless
    diagnostic labeling (D9) and passes through unchanged."""
    chans = (("t", res.t), ("whp", res.whp), ("pump", res.pump),
             ("hydro", res.hydro), ("q_in", res.q_in), ("q_out", res.q_out))
    n = None
    for name, arr in chans:
        if arr is None or getattr(arr, "ndim", None) != 1 or arr.size == 0:
            raise ChartResultIntegrityError(
                "raw channel %r is missing/empty/not 1-D — refusing to "
                "return an unusable SimResult." % (name,))
        if n is None:
            n = arr.size
        elif arr.size != n:
            raise ChartResultIntegrityError(
                "raw channel %r has %d samples != %d — misaligned raw "
                "series are never presented." % (name, arr.size, n))
    for name, arr in chans:
        bad = int(np.count_nonzero(~np.isfinite(arr)))
        if bad:
            raise ChartResultIntegrityError(
                "raw channel %r contains %d non-finite sample(s) — invalid "
                "raw data is never clipped, zeroed, interpolated or "
                "masked; correct the inputs." % (name, bad))
    if res.dyn is not None:
        if res.dyn.ndim != 1 or res.dyn.size != n:
            raise ChartResultIntegrityError(
                "raw channel 'dyn' is misaligned (%r vs %d samples)."
                % (res.dyn.shape, n))
        bad = int(np.count_nonzero(~np.isfinite(res.dyn)))
        if bad:
            raise ChartResultIntegrityError(
                "raw channel 'dyn' contains %d non-finite sample(s) — "
                "never masked; correct the inputs." % (bad,))
    if res.t_eod is None or not math.isfinite(float(res.t_eod)):
        raise ChartResultIntegrityError("t_eod is missing or non-finite.")


#: Cement-slurry stage types — the exact set Phase IV's plausibility check
#: (phase_4_fluids.py line ~326) guards with the 75-180 pcf window.
SLURRY_TYPES = ("Main", "Tail", "Lead", "Lead #1", "Lead #2")

#: Non-slurry stage types whose rheology arrives on the Phase IV/VI record
#: itself (owner decision D7 — the host app will provide PV/YP per fluid,
#: Bingham model; see the NOTE in the module docstring).
SPACER_TYPES = ("Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind")

#: Lab dataset feeding slurry friction (owner decision D8).
RHEOLOGY_DATASET = "bhct_down"          # BHCT — Ramp-Down

#: v1.0's declared DEFAULT_RHEOLOGY table is RETIRED (owner decisions D7/D9):
#: rheology is either real (Phase II/III PV-YP, Phase VII Bingham fit, or the
#: record's own pv/yp fields) or the affected fluid runs hydrostatic-only with
#: a named warning.  Nothing is invented.


@dataclass
class FluidStageSpec:
    """One pumpable stage (already validated)."""
    fluid_type: str            # Phase IV stage label ("Main", "Spacer", ...)
    material_name: str         # Phase IV "Name" column entry
    volume_bbl: float
    density_pcf: float         # Phase IV effective_density
    rate_bpm: float            # Phase IV min_rate (constant during stage)
    pv_cp: Optional[float] = None          # D7: record's own PV (Bingham)
    yp_lbf100ft2: Optional[float] = None   # D7: record's own YP


@dataclass
class AnnSection:
    """One depth interval of the RETURN leg (owner rule D11/D11b).

    do_in : annulus OUTSIDE diameter — the HOST casing/liner ID inside the
            covered hole, the open-hole bit size below the host shoe.
    di_in : annulus INSIDE diameter — the OD of the string occupying the
            interval (target OD; above a liner hanger the work-string OD).
    """
    z_top: float            # m (shallow end)
    z_bot: float            # m (deep end)
    do_in: float
    di_in: float


@dataclass
class PipeSection:
    """One depth interval of the STRING (injection) leg (D11/D11b).

    Casing job : one section 0..shoe with the target row ID.
    Liner job  : work-string (Drill Pipes/Tubing) section above the hanger
                 + the liner section below it (flow goes down INSIDE the
                 liner — owner rule).
    Tie-back   : tie-back section from surface to the tie-in depth + the
                 OLD liner section from the tie-in to the old liner shoe.
    """
    z_top: float
    z_bot: float
    id_in: float            # flow ID (string leg)
    od_in: float            # OD (annulus inner wall at this depth)


@dataclass(frozen=True)
class _Sec:
    """Internal per-section capacity bundle (deep->shallow order kept by
    the Channel)."""
    z_top: float
    z_bot: float
    cap_bbl_per_m: float
    dims: Tuple[float, ...]   # pipe: (id_in,); annulus: (do_in, di_in)


class Channel:
    """A flow path with piecewise-uniform sections (D11 v1.2).

    Columns are stored bottom(TD)->top, so volumes accumulate from the
    DEEP end.  A Channel converts volumes <-> per-section slices with the
    confirmed two-section geometry; a bare float (bbl/m) is accepted
    everywhere for the single-section demo path and old call sites.
    """

    def __init__(self, sections: List[_Sec], kind: str):
        self.sections = sections          # ANY order; sorted deep->shallow here
        self.kind = kind                  # 'pipe' | 'annulus'
        self.sections.sort(key=lambda s: -s.z_bot)
        if not self.sections:
            raise ChartInputError("Channel needs at least one section.")
        for s in self.sections:
            if not (math.isfinite(s.z_top) and math.isfinite(s.z_bot)
                    and math.isfinite(s.cap_bbl_per_m)):
                raise ChartInputError(
                    "Channel section %s has non-finite bounds/capacity."
                    % (s,))
            if s.z_bot <= s.z_top:
                raise ChartInputError(
                    "Channel section %s has non-positive length." % (s,))
            if s.cap_bbl_per_m <= 0.0:
                raise ChartInputError(
                    "Channel section %s has non-positive capacity." % (s,))

    # -- capacity -----------------------------------------------------------
    def total_volume(self) -> float:
        return sum(s.cap_bbl_per_m * (s.z_bot - s.z_top) for s in self.sections)

    def volume_above(self, depth_m: float) -> float:
        """Channel volume between the SURFACE and depth_m — the column head
        lying above a point at depth_m (at depth = TD this is the full
        channel, matching the scalar legacy formula)."""
        v = 0.0
        for s in self.sections:
            if s.z_top < depth_m:
                v += s.cap_bbl_per_m * (min(s.z_bot, depth_m) - s.z_top)
        return v

    # -- volume <-> section slices -------------------------------------------
    def _windows(self, from_bottom: bool):
        """Yield (sec, v_lo, v_hi) volume windows, cumulative from the
        measurement end (bottom=deep / top=shallow)."""
        c = 0.0
        order = self.sections if from_bottom else reversed(self.sections)
        for s in order:
            w = s.cap_bbl_per_m * (s.z_bot - s.z_top)
            yield s, c, c + w
            c += w

    def spans(self, v0: float, v1: float, from_bottom: bool = True):
        """Intersect the cumulative volume interval [v0, v1] with the
        section windows -> ((sec, vol_in_sec), ...) in measurement order."""
        if v1 <= v0:
            return []
        out = []
        for s, lo, hi in self._windows(from_bottom):
            a, b = max(v0, lo), min(v1, hi)
            if b > a:
                out.append((s, b - a))
        return out

    @staticmethod
    def coerce(v_or_chan, kind: str) -> 'Channel':
        if isinstance(v_or_chan, Channel):
            return v_or_chan
        if isinstance(v_or_chan, (int, float)) and v_or_chan > 0:
            # single-section fallback (demo path / legacy scalar call sites)
            return Channel([_Sec(0.0, 1.0, float(v_or_chan), (0.0, 0.0))], kind)
        raise ChartInputError(
            "column function needs a positive capacity or a Channel; got %r."
            % (v_or_chan,))


@dataclass
class GeometrySpec:
    """Wellbore geometry — supplied from Phase II/III session state.

    Reference values below are the SOURCE-CONFIRMED demo well only
    (3293 m, 8.5" hole x 5" DP 4.276" ID, Doc 17).  A real run MUST pass
    its own values; build_three_charts() refuses None geometry.

    v1.2 (D11 confirmed): geometry_from_hardware() fills ann_sections /
    pipe_sections from the hardware table.  When they are left None the
    scalar fields build the single-section demo geometry exactly as before
    (byte-stable anchors: EOD 43.6, ATCP; the shut-in WHP anchor
    was re-adjudicated in ER-02, 2026-11-08 and the D14 law was
    corrected to the absolute BHSP target in ER-03, 2026-11-08 —
    see the D15 note and ER02_B13_ADJUDICATION_LEDGER.md in the
    evidence ZIP).
    """
    td_m: float = 3293.0
    track_depth_m: float = 3293.0     # chart-2/3 depth point & header
    hole_id_in: float = 8.5
    pipe_od_in: float = 5.0
    pipe_id_in: float = 4.276
    depth_unit: str = 'm'
    ann_sections: Optional[List[AnnSection]] = None    # D11 v1.2
    pipe_sections: Optional[List[PipeSection]] = None  # D11b v1.2
    # ER-02 (2026-11-08): public operation identity of this
    # geometry.  The default preserves every legacy construction
    # path bit-exactly; the typed Tie Back constructor stamps
    # 'TIE BACK' (Owner DP-above-Point-A topology) so the public
    # identity is never disguised as a Liner operation.
    operation_identity: str = 'CSG'

    def __post_init__(self):
        if not math.isfinite(self.td_m):
            raise ChartInputError(
                "GeometrySpec.td_m must be a finite depth.")
        if not math.isfinite(self.track_depth_m):
            raise ChartInputError(
                "GeometrySpec.track_depth_m must be a finite depth.")
        if self.td_m <= 0:
            raise ChartInputError("GeometrySpec.td_m must be positive.")
        if not (0.0 < self.pipe_id_in < self.pipe_od_in < self.hole_id_in):
            raise ChartInputError(
                "GeometrySpec requires 0 < pipe_id_in < pipe_od_in < hole_id_in; "
                "got pipe_id_in=%r pipe_od_in=%r hole_id_in=%r"
                % (self.pipe_id_in, self.pipe_od_in, self.hole_id_in))
        if not (0.0 < self.track_depth_m <= self.td_m):
            raise ChartInputError(
                "GeometrySpec.track_depth_m must satisfy 0 < track_depth_m <= td_m.")
        if self.ann_sections is None:
            self.ann_sections = [AnnSection(0.0, self.td_m,
                                            self.hole_id_in, self.pipe_od_in)]
        if self.pipe_sections is None:
            self.pipe_sections = [PipeSection(0.0, self.td_m,
                                              self.pipe_id_in, self.pipe_od_in)]
        for s in self.ann_sections:
            if not (math.isfinite(s.z_top) and math.isfinite(s.z_bot)
                    and math.isfinite(s.do_in) and math.isfinite(s.di_in)):
                raise ChartInputError(
                    "AnnSection fields must be finite; got %r." % (s,))
            if not (0.0 < s.di_in < s.do_in):
                raise ChartInputError(
                    "AnnSection needs 0 < di < do; got do=%r di=%r."
                    % (s.do_in, s.di_in))
        for s in self.pipe_sections:
            if not (math.isfinite(s.z_top) and math.isfinite(s.z_bot)
                    and math.isfinite(s.id_in) and math.isfinite(s.od_in)):
                raise ChartInputError(
                    "PipeSection fields must be finite; got %r." % (s,))
            if not (0.0 < s.id_in < s.od_in):
                raise ChartInputError(
                    "PipeSection needs 0 < id < od; got id=%r od=%r."
                    % (s.id_in, s.od_in))
        tops = [s.z_top for s in self.ann_sections + self.pipe_sections]
        bots = [s.z_bot for s in self.ann_sections + self.pipe_sections]
        if min(tops) < -1e-9 or max(bots) > self.td_m + 1e-6:
            raise ChartInputError(
                "GeometrySpec sections must lie inside [0, td_m=%.1f]." % self.td_m)

    # -- deep-section scalars (backward-compatible anchors) ------------------
    @property
    def _deep_ann(self) -> AnnSection:
        return max(self.ann_sections, key=lambda s: s.z_bot)

    @property
    def _deep_pipe(self) -> PipeSection:
        return max(self.pipe_sections, key=lambda s: s.z_bot)

    @property
    def a_pipe(self) -> float:            # m2 (deep section)
        d = self._deep_pipe.id_in * 0.0254
        return math.pi * d * d / 4.0

    @property
    def a_ann(self) -> float:             # m2 (deep section)
        do = self._deep_ann.do_in * 0.0254
        di = self._deep_ann.di_in * 0.0254
        return math.pi * (do * do - di * di) / 4.0

    @property
    def v_pipe_bbl_per_m(self) -> float:
        return self.a_pipe * BBL_PER_M3

    @property
    def v_ann_bbl_per_m(self) -> float:
        return self.a_ann * BBL_PER_M3

    # -- v1.2 totals + channels ----------------------------------------------
    @property
    def total_pipe_bbl(self) -> float:
        return self.chan_pipe.total_volume()

    @property
    def total_ann_bbl(self) -> float:
        return self.chan_ann.total_volume()

    def _chan(self, kind: str) -> Channel:
        if kind == 'pipe':
            return Channel([_Sec(s.z_top, s.z_bot,
                                 math.pi * (s.id_in * 0.0254) ** 2 / 4.0
                                 * BBL_PER_M3, (s.id_in,))
                            for s in self.pipe_sections], kind)
        return Channel([_Sec(s.z_top, s.z_bot,
                             (math.pi * ((s.do_in * 0.0254) ** 2
                                         - (s.di_in * 0.0254) ** 2) / 4.0
                              * BBL_PER_M3),
                             (s.do_in, s.di_in))
                        for s in self.ann_sections], kind)

    @property
    def chan_pipe(self) -> Channel:
        return self._chan('pipe')

    @property
    def chan_ann(self) -> Channel:
        return self._chan('annulus')

    def describe(self) -> str:
        """Human-readable D11 layout for logs/warnings (m / inch)."""
        def fmt_pipe(s):
            return '%.0f-%.0f ID %.3f"' % (s.z_top, s.z_bot, s.id_in)

        def fmt_ann(s):
            return '%.0f-%.0f OD %.3f" x ID %.3f"' % (s.z_top, s.z_bot,
                                                      s.do_in, s.di_in)
        return ('D11 string: %s | D11 annulus: %s'
                % (' + '.join(fmt_pipe(s) for s in self.pipe_sections),
                   ' + '.join(fmt_ann(s) for s in self.ann_sections)))


#: JOB_TYPES families (materials_db.py).  D11c: plug / squeeze jobs have
#: NO three-chart page — the module refuses them with a named error.
JOB_NO_CHARTS = ('CMT PLUG', 'CMT SQUEEZE')
_FAM_CSG, _FAM_LNR, _FAM_TB = 'CSG', 'LNR', 'TIE BACK'

# P2: rows with these Descriptions are STRING hardware (their bore is the
# string leg) — they can never act as an annulus host, regardless of
# content.  The host walk previously excluded them by row identity only,
# so a content-different duplicate Drill Pipes / Tubing / Liner Hanger
# row would have leaked into host_spans.
_STRING_DESCRIPTIONS = ('Drill Pipes', 'Drill Pipe', 'Tubing',
                        'Liner Hanger')


def _job_family(job_type: str) -> str:
    t = str(job_type or '').strip().upper()
    if t in JOB_NO_CHARTS:
        raise ChartInputError(
            "geometry_from_hardware: %r jobs have no job-simulation charts "
            "(owner 2026-10-10: 'این ۳ نمودار رو نداریم') — the three-chart "
            "page is produced for CSG / LNR / TIE BACK jobs only." % job_type)
    if t.startswith('CSG'):
        return _FAM_CSG
    if t.startswith('LNR'):
        return _FAM_LNR
    if t.startswith('TIE BACK'):
        return _FAM_TB
    raise ChartInputError(
        "geometry_from_hardware: job_type %r is not a JOB_TYPES entry "
        "(materials_db.py: CSG .. / LNR 7\" / LNR 5\" / TIE BACK LNR .. / "
        "CMT PLUG / CMT SQUEEZE)." % (job_type,))


def geometry_from_hardware(hardware_rows, target_row=None, td_m=None,
                           track_depth_m=None, job_type=None
                           ) -> Tuple[GeometrySpec, List[str]]:
    """hardware_table (Phase II/III) -> (GeometrySpec, warnings).

    Owner rule D11 — CONFIRMED 2026-10-10 ("برای csg ها درسته") and
    extended by the owner's liner/tie-back addendum (D11b):

      * STRING leg (injection): the placement TARGET row (required — the
        module never guesses which string carries the cement).
            CSG      : target ID 0..shoe (bottom of the MD cell, D10).
            LNR      : Drill Pipes/Tubing ID 0..hanger, then the LINER ID
                       down to the liner shoe (flow goes down INSIDE the
                       liner).  The hanger = the 'Liner Hanger' row MD or
                       the liner interval TOP.
            TIE BACK : Tie-Back ID 0..tie-in depth, then the OLD LINER ID
                       down to the old liner shoe (the flow passes through
                       inside the old liner — "از توی لاینر").
      * RETURN leg (annulus): between the string OD at depth and
            the innermost HOST row ID  (Previous Casing / Previous Liner /
            another Casing/Liner row) inside the covered hole,
            the open-hole BIT SIZE below the deepest host shoe.
        D11b crossing: at the liner top the return passes INTO the host ID
            ("لاینر ۷ -> ID 9 5/8 روی لبه", "لاینر ۵ -> ID لاینر ۷") —
            modeled by the inner-wall change at the hanger (work-string OD
            above, liner OD below) and the host ID outer wall.
      * 'Open Hole Size' row: supplies the bit size (its MD interval is
        cross-checked against the deepest host shoe).
      * D11c: job_type 'CMT PLUG' / 'CMT SQUEEZE' is REFUSED — those jobs
        have no three-chart page.

    td_m / track_depth_m: optional overrides (Phase II/III geo_md and the
    chart track point).  Default td_m = the deepest parsed bottom among the
    string rows and the open-hole row; track_depth_m = td_m.
    """
    warnings: List[str] = []
    rows = [r for r in (hardware_rows or []) if isinstance(r, dict)
            or hasattr(r, "get")]
    if target_row is None:
        raise ChartInputError(
            "geometry_from_hardware: pass the placement TARGET row (the "
            "string being cemented) resolved from placement_config — the "
            "module never guesses the cementing string.")

    def row_get(row, key):
        try:
            return row.get(key)
        except AttributeError:
            return None

    def desc(row):
        return str(row_get(row, "Description") or "").strip()

    def num(row, key, label, who="the target row"):
        v = row_get(row, key)
        try:
            n = clean_number(v) if v not in (None, "") else None
        except ValueError:
            n = None
        if n is not None and not math.isfinite(n):
            raise ChartInputError(
                "geometry_from_hardware: %s needs a finite %s (got %r)."
                % (who, label, v))
        if n is None or n <= 0:
            raise ChartInputError(
                "geometry_from_hardware: %s needs a positive %s (got %r)."
                % (who, label, v))
        return n

    def num_opt(row, key):
        v = row_get(row, key)
        try:
            n = clean_number(v) if v not in (None, "") else None
        except ValueError:
            n = None
        if n is not None and not math.isfinite(n):
            n = None      # ER01-F2: non-finite host ID = unreadable cell
        return n if (n is not None and n > 0) else None

    def find(name):
        return next((r for r in rows if desc(r) == name), None)

    # -- D11c: plug / squeeze jobs have no three-chart page ------------------
    fam = _job_family(job_type) if job_type is not None else None
    tgt_desc = desc(target_row)
    inferred = ({'Casing': _FAM_CSG, 'Liner': _FAM_LNR,
                 'Tie Back': _FAM_TB}.get(tgt_desc))
    if fam is None:
        if inferred is None:
            raise ChartInputError(
                "geometry_from_hardware: the target row Description %r is "
                "not a cementing string (Casing / Liner / Tie Back) — pass "
                "job_type (JOB_TYPES) explicitly." % tgt_desc)
        fam = inferred
    elif inferred is not None and inferred != fam:
        raise ChartInputError(
            "geometry_from_hardware: job_type %r does not match the target "
            "row Description %r." % (job_type, tgt_desc))

    # -- target row (string of the placement) --------------------------------
    pipe_id = num(target_row, "ID (in)", 'ID (in)')
    size_raw = row_get(target_row, "Size (in)")
    pipe_od = parse_fractional_size(str(size_raw or ""))
    if pipe_od <= 0:
        raise ChartInputError(
            "geometry_from_hardware: the target row needs a readable "
            "Size (in) like '9 5/8' (got %r)." % size_raw)
    shoe_top, shoe_bottom = parse_md_interval(row_get(target_row, "MD (m)"))
    if shoe_bottom is None:
        raise ChartInputError(
            "geometry_from_hardware: the target row needs an MD cell "
            "(single depth or interval).")

    open_hole = find("Open Hole Size")
    bit = None
    oh_top = oh_bottom = None
    if open_hole is not None:
        bit = num(open_hole, "ID (in)", 'Open Hole bit size (ID)',
                  "the 'Open Hole Size' row")
        oh_top, oh_bottom = parse_md_interval(row_get(open_hole, "MD (m)"))
    else:
        oh_bottom = None

    # -- flow path per family (D11 / D11b) ------------------------------------
    hanger_row = find("Liner Hanger")
    dp_row = find("Drill Pipes") or find("Tubing")
    tb_bottom = shoe_bottom
    pipe_secs: List[PipeSection] = []
    string_rows = [target_row]

    if fam == _FAM_CSG:
        pipe_secs.append(PipeSection(0.0, shoe_bottom, pipe_id, pipe_od))

    elif fam == _FAM_LNR:
        # hanger depth: 'Liner Hanger' row MD, else the liner interval TOP
        if shoe_top is None or shoe_top >= shoe_bottom:
            raise ChartInputError(
                "geometry_from_hardware: the Liner row needs an MD INTERVAL "
                "'top-bottom' so the hanger (liner top) is known — a liner "
                "job cannot be built from a single depth.")
        hanger = shoe_top
        if hanger_row is not None:
            _, hz = parse_md_interval(row_get(hanger_row, "MD (m)"))
            if hz is not None:
                if abs(hz - hanger) > 1.0:
                    warnings.append(
                        "Liner Hanger row MD (%.1f m) disagrees with the "
                        "liner interval top (%.1f m) — the liner top is "
                        "used as the D11b crossing depth." % (hz, hanger))
                else:
                    hanger = hz
            else:
                warnings.append(
                    "Liner Hanger row has no readable MD cell — the liner "
                    "interval top (%.1f m) is used." % hanger)
        else:
            warnings.append(
                "No 'Liner Hanger' row — the liner interval top (%.1f m) is "
                "used as the hanger." % hanger)
        if dp_row is None:
            raise ChartInputError(
                "geometry_from_hardware: LNR job needs the work string — "
                "add a 'Drill Pipes' (or 'Tubing') row to hardware_table.  "
                "Above the hanger the return crosses into the host ID with "
                "the work-string OD as the inner wall (owner rule D11b); "
                "without that row the string leg cannot be built.")
        dp_id = num(dp_row, "ID (in)", 'ID (in)', "the work-string row")
        dp_od = parse_fractional_size(str(row_get(dp_row, "Size (in)") or ""))
        if dp_od <= 0:
            raise ChartInputError(
                "geometry_from_hardware: the work-string row needs a "
                "readable Size (in) (got %r)." % row_get(dp_row, "Size (in)"))
        dp_top, dp_bot = parse_md_interval(row_get(dp_row, "MD (m)"))
        if dp_bot is None:
            raise ChartInputError(
                "geometry_from_hardware: the work-string row needs an MD "
                "cell (interval '0.0-<hanger>' or the hanger depth).")
        # D17 (owner): the DP row is a POINT depth = hanger depth (Top =
        # surface implicit) — the NORMAL form, accepted silently; only an
        # interval whose top is not 0 warns.
        if dp_top is not None and abs(dp_top - dp_bot) > 1e-9 \
                and abs(dp_top) > 1e-9:
            warnings.append(
                "Work-string MD interval starts at %.1f m — owner "
                "convention is Top = surface, Bottom = hanger; assumed "
                "run from surface (0 m)." % dp_top)
        if abs(dp_bot - hanger) > 1.0:
            raise ChartInputError(
                "geometry_from_hardware: the work-string bottom (%.1f m) "
                "does not reach the hanger (%.1f m) — correct the rows; "
                "the module does not guess the string layout." % (dp_bot,
                                                                  hanger))
        pipe_secs.append(PipeSection(0.0, hanger, dp_id, dp_od))
        pipe_secs.append(PipeSection(hanger, shoe_bottom, pipe_id, pipe_od))
        string_rows.append(dp_row)
        warnings.append(
            "D11b liner flow path: down the work string + INSIDE the liner; "
            "at the hanger (%.1f m) the return crosses into the host ID "
            "(owner rule)." % hanger)

    else:  # _FAM_TB
        tb_top, tb_bottom = shoe_top, shoe_bottom
        # D17: a point-depth tie-back cell = the tie-in depth (surface top
        # implicit) — silent; only an interval whose top is not 0 warns.
        if tb_top is not None and abs(tb_top - tb_bottom) > 1e-9 \
                and abs(tb_top) > 1e-9:
            warnings.append(
                "Tie-Back MD interval starts at %.1f m — assumed run "
                "from surface (0 m)." % tb_top)
        pipe_secs.append(PipeSection(0.0, tb_bottom, pipe_id, pipe_od))

    # -- host rows (outer wall of the return leg) -----------------------------
    # String rows are never hosts.  For a tie-back the OLD liner (the row
    # the tieback connects to) is the string below the tie-in, so it is
    # excluded from the host walk too.
    host_spans: List[Tuple[float, float, float, str]] = []
    tie_row = None
    if fam == _FAM_TB:
        cands = []
        for r in rows:
            if r is target_row or r in string_rows or desc(r) == 'Open Hole Size':
                continue
            it, ib = parse_md_interval(row_get(r, "MD (m)"))
            hid = num_opt(r, "ID (in)")
            if it is None or ib is None or hid is None:
                continue
            if it - 1.0 <= tb_bottom <= ib + 1.0:
                cands.append((it, ib, hid, r))
        if not cands:
            raise ChartInputError(
                "geometry_from_hardware: TIE BACK job — no hardware row the "
                "tieback connects to at %.1f m.  Add the old liner row "
                "('Previous Liner') with its MD interval and ID."
                % tb_bottom)
        cands.sort(key=lambda c: -c[0])          # innermost (deepest top)
        it, ib, hid, tie_row = cands[0]
        old_id, old_od = hid, parse_fractional_size(
            str(row_get(tie_row, "Size (in)") or ""))
        if old_od <= 0:
            raise ChartInputError(
                "geometry_from_hardware: the tie-in row (%s) needs a "
                "readable Size (in)." % desc(tie_row))
        if ib <= tb_bottom:
            raise ChartInputError(
                "geometry_from_hardware: the tie-in row (%s, %.1f-%.1f m) "
                "has no depth below the tieback bottom %.1f m."
                % (desc(tie_row), it, ib, tb_bottom))
        pipe_secs.append(PipeSection(tb_bottom, ib, old_id, old_od))
        string_rows.append(tie_row)
        if abs(it - tb_bottom) > 1.0:
            warnings.append(
                "Tie-back bottom (%.1f m) sits inside the tie-in string "
                "(%s top %.1f m) — the string leg continues INSIDE it from "
                "the tie-in depth (owner rule: the flow passes through "
                "inside the liner)." % (tb_bottom, desc(tie_row), it))
        warnings.append(
            "D11b tie-back flow path: down the tie-back + INSIDE the old "
            "%s to %.1f m; the return crosses into the host ID at the "
            "tie-in (owner rule)." % (desc(tie_row), ib))

    for r in rows:
        if r is target_row or r in string_rows or r is dp_row \
                or desc(r) == 'Open Hole Size':
            continue
        if desc(r) in _STRING_DESCRIPTIONS:      # P2: never a host
            continue
        it, ib = parse_md_interval(row_get(r, "MD (m)"))
        hid = num_opt(r, "ID (in)")
        if it is None or ib is None:
            warnings.append(
                "Hardware row %r has no readable MD cell — it cannot act "
                "as an annulus host." % desc(r))
            continue
        if hid is None:
            warnings.append(
                "Hardware row %r has no readable ID (in) — it cannot act "
                "as an annulus host." % desc(r))
            continue
        host_spans.append((it, ib, hid, desc(r)))

    # -- open-hole start = deepest host shoe ----------------------------------
    if host_spans:
        oh_start = max(ib for _, ib, _, _ in host_spans)
        if open_hole is not None and oh_top is not None \
                and abs(oh_top - oh_start) > 1.0:
            warnings.append(
                "Open Hole Size row top (%.1f m) differs from the deepest "
                "host shoe (%.1f m) — the bit size governs below the host "
                "shoe (D11 rule)." % (oh_top, oh_start))
    else:
        oh_start = 0.0
        if bit is None:
            raise ChartInputError(
                "geometry_from_hardware: add an 'Open Hole Size' row (bit "
                "size) or a 'Previous Casing' row to hardware_table so the "
                "annulus can be built.")
        warnings.append(
            "No previous casing/liner row — the bit size %.3f in is used as "
            "the annulus outside diameter over the whole depth." % bit)
    if bit is None:
        bit = max(host_spans, key=lambda h: h[1])[2]
        warnings.append(
            "No 'Open Hole Size' row — the deepest host ID (%.3f in) fills "
            "the open-hole interval as well." % bit)

    # -- td / track -----------------------------------------------------------
    if td_m is None:
        bottoms = [max(s.z_bot for s in pipe_secs)]
        if oh_bottom is not None:
            bottoms.append(oh_bottom)
        td_m = max(bottoms)
    if track_depth_m is None:
        track_depth_m = td_m
    if track_depth_m > td_m:
        raise ChartInputError(
            "geometry_from_hardware: track depth %.1f m exceeds TD %.1f m."
            % (track_depth_m, td_m))

    pipe_bot = max(s.z_bot for s in pipe_secs)
    if pipe_bot < td_m - 1e-6:
        warnings.append(
            "The string shoe (%.1f m) is above TD (%.1f m) — the deepest "
            "string section is extended to TD for the U-tube model "
            "(v1.1-equivalent behavior)." % (pipe_bot, td_m))
        deep = max(pipe_secs, key=lambda s: s.z_bot)
        deep.z_bot = float(td_m)

    # -- annulus walk (D11 confirmed rule) ------------------------------------
    bounds = {0.0, float(td_m)}
    for it, ib, _, _ in host_spans:
        for v in (it, ib):
            if 0.0 < v < td_m:
                bounds.add(v)
    for s in pipe_secs:
        for v in (s.z_top, s.z_bot):
            if 0.0 < v < td_m:
                bounds.add(v)
    if 0.0 < oh_start < td_m:
        bounds.add(oh_start)
    bnd = sorted(bounds)

    def pipe_od_at(z):
        for s in pipe_secs:
            if s.z_top - 1e-9 <= z <= s.z_bot + 1e-9:
                return s.od_in
        return max(pipe_secs, key=lambda s: s.z_bot).od_in

    def host_id_at(z):
        best = None
        for it, ib, hid, _lab in host_spans:
            if it - 1e-9 <= z <= ib + 1e-9:
                if best is None or ib > best[1]:
                    best = (it, ib, hid)
        return None if best is None else best[2]

    raw_ann: List[AnnSection] = []
    for a, b in zip(bnd, bnd[1:]):
        if b - a < 1e-9:
            continue
        mid = 0.5 * (a + b)
        di = pipe_od_at(mid)
        if mid > oh_start + 1e-9:
            do = bit                                  # open hole: bit size
        else:
            do = host_id_at(mid)
            if do is None:
                # uncovered top interval — extend the shallowest host ID
                do = min(host_spans, key=lambda h: h[0])[2]
                warnings.append(
                    "No host row covers %.0f-%.0f m — the shallowest host "
                    "ID (%.3f in) is extended upward (add the covering "
                    "casing row for an exact model)." % (a, b, do))
        if do <= di + 1e-12:
            raise ChartInputError(
                "geometry_from_hardware: no annulus at %.0f-%.0f m — "
                "host/bit %.3f in is not larger than the string OD "
                "%.3f in." % (a, b, do, di))
        raw_ann.append(AnnSection(a, b, float(do), float(di)))
    ann_secs: List[AnnSection] = []
    for s in raw_ann:
        if ann_secs and abs(ann_secs[-1].do_in - s.do_in) < 1e-12 \
                and abs(ann_secs[-1].di_in - s.di_in) < 1e-12:
            ann_secs[-1].z_bot = s.z_bot              # merge equal walls
        else:
            ann_secs.append(s)

    deep_ann = max(ann_secs, key=lambda s: s.z_bot)
    deep_pipe = max(pipe_secs, key=lambda s: s.z_bot)
    geo = GeometrySpec(td_m=float(td_m), track_depth_m=float(track_depth_m),
                       hole_id_in=deep_ann.do_in, pipe_od_in=deep_pipe.od_in,
                       pipe_id_in=deep_pipe.id_in,
                       ann_sections=ann_secs, pipe_sections=pipe_secs)
    if fam != _FAM_CSG:
        warnings.append("D11 flow path built: " + geo.describe())
    return geo, warnings


# ----------------------------------------------------------------------------
# ER-02 (2026-11-08, owner-authorized): typed engine-side Tie Back geometry
# input — Owner topology "Drill Pipe above Point A".
#
#   DP (pumped conduit) : surface (MD 0) -> Point A (liner lap)
#   Tie Back string     : Point A -> tie-back shoe (= U-tube bottom = td)
#   Return annulus      : ONE documented host ID over the whole tested
#                         span; inner wall = DP OD above A, TB OD below A
#
# The returned GeometrySpec is numerically IDENTICAL to the TB-01-validated
# D11b work-string route (the disclosed 'Liner'-row mapping) for the same
# dimensions — proven section- and bit-identical in the ER-02 receipts —
# but carries the public operation identity 'TIE BACK' instead of
# disguising the tie-back row as a Liner operation.  The legacy native
# TIE BACK family (old-liner-through-shoe, TB-01 E1) is NOT repaired and
# stays unsupported for this topology; this constructor never routes
# through it.  NOTHING is inferred: every dimension is explicit, an
# uncovered span is REJECTED (no upward host extension on this
# production-bound typed path), and every violation raises
# ChartInputError before any physics.  Resolving the user's Hardware into
# this typed input (the specific host row) remains the Codex-owned App
# obligation (PR-A).
# ----------------------------------------------------------------------------

TIEBACK_OPERATION_IDENTITY = 'TIE BACK'


@dataclass(frozen=True)
class TieBackInput:
    """Typed, fully explicit Owner Tie Back topology (ER-02).

    Depths in m (MD), diameters in inch.  Nothing is inferred; the only
    default is track_depth_m (= the tie-back shoe, the documented chart
    depth point for a tie-back bottom, D18).
    """
    dp_id_in: float                        # Drill Pipe flow ID (above A)
    dp_od_in: float                        # Drill Pipe OD (annulus inner wall, 0..A)
    point_a_md: float                      # Point A / liner lap depth
    tb_id_in: float                        # Tie Back flow ID (below A)
    tb_od_in: float                        # Tie Back OD (annulus inner wall, A..shoe)
    tb_shoe_md: float                      # tie-back shoe = U-tube bottom = td
    host_id_in: float                      # the ONE documented host ID
    host_top_md: float = 0.0               # host coverage top (must cover 0)
    host_bot_md: Optional[float] = None    # host coverage bottom (>= shoe)
    track_depth_m: Optional[float] = None  # chart-2/3 depth point (explicit)
    host_label: str = 'documented host'    # identity label for logs only


def build_tieback_geometry(spec: TieBackInput) -> GeometrySpec:
    """Validate + build the DP-above-Point-A Tie Back GeometrySpec.

    Engine-owned structural checks (fail-closed ChartInputError, always
    before any physics): finite fields; 0 < ID < OD for the Drill Pipe
    and the Tie Back (the flow ID is never taken from the OD); strict
    string continuity 0 -> Point A -> shoe; host coverage of the WHOLE
    tested span (host_top <= 0 and host_bot >= shoe — partial hosts are
    rejected, never extended upward); host ID > both string ODs; track
    depth within (0, td].  Capacities, volumes and pump flow all use the
    actual IDs/ODs via the shared GeometrySpec/Channel machinery.
    """
    def _finite(x, label):
        if isinstance(x, bool) or not isinstance(x, (int, float))                 or not math.isfinite(float(x)):
            raise ChartInputError(
                "build_tieback_geometry: %s must be a finite number "
                "(got %r)." % (label, x))
        return float(x)

    dp_id = _finite(spec.dp_id_in, "dp_id_in")
    dp_od = _finite(spec.dp_od_in, "dp_od_in")
    pa = _finite(spec.point_a_md, "point_a_md")
    tb_id = _finite(spec.tb_id_in, "tb_id_in")
    tb_od = _finite(spec.tb_od_in, "tb_od_in")
    shoe = _finite(spec.tb_shoe_md, "tb_shoe_md")
    host_id = _finite(spec.host_id_in, "host_id_in")
    host_top = _finite(spec.host_top_md, "host_top_md")
    if spec.host_bot_md is None:
        raise ChartInputError(
            "build_tieback_geometry: host_bot_md is required — the host "
            "must explicitly cover the whole tested span (nothing is "
            "inferred and no host is invented or extended upward).")
    host_bot = _finite(spec.host_bot_md, "host_bot_md")
    track = (_finite(spec.track_depth_m, "track_depth_m")
             if spec.track_depth_m is not None else shoe)

    # -- string segments (fail-closed) ---------------------------------------
    for _label, _i, _o in (("Drill Pipe", dp_id, dp_od),
                           ("Tie Back", tb_id, tb_od)):
        if not (0.0 < _i < _o):
            raise ChartInputError(
                "build_tieback_geometry: %s requires 0 < ID < OD "
                "(got ID=%r OD=%r) — the flow ID is never taken from the "
                "OD and non-positive IDs are rejected." % (_label, _i, _o))
    if not (0.0 < pa < shoe):
        raise ChartInputError(
            "build_tieback_geometry: Point A (%r m) must lie strictly "
            "between the surface and the tie-back shoe (%r m) — the DP/"
            "Tie Back string continuity 0 -> A -> shoe is mandatory and a "
            "missing or invalid Point A is rejected." % (pa, shoe))
    # -- host coverage + clearance (fail-closed, no fallback) -----------------
    if host_top > 1e-9 or host_bot < shoe - 1e-9:
        raise ChartInputError(
            "build_tieback_geometry: host %.3f in (%s) covers %.1f-%.1f m "
            "but the tested span is 0-%.1f m — uncovered spans are "
            "rejected on this typed path (no upward extension, no second "
            "invented host)." % (host_id, spec.host_label, host_top,
                                 host_bot, shoe))
    if host_id <= dp_od + 1e-12 or host_id <= tb_od + 1e-12:
        raise ChartInputError(
            "build_tieback_geometry: host ID %.3f in must exceed both "
            "string ODs (DP %.3f in, Tie Back %.3f in) or there is no "
            "return annulus." % (host_id, dp_od, tb_od))
    if not (0.0 < track <= shoe):
        raise ChartInputError(
            "build_tieback_geometry: track_depth_m %r must satisfy "
            "0 < track <= tb_shoe_md (%.1f)." % (track, shoe))

    pipe_secs = [PipeSection(0.0, pa, dp_id, dp_od),
                 PipeSection(pa, shoe, tb_id, tb_od)]
    if abs(dp_od - tb_od) < 1e-12:       # uniform annulus across the lap
        ann_secs = [AnnSection(0.0, shoe, host_id, dp_od)]
    else:
        ann_secs = [AnnSection(0.0, pa, host_id, dp_od),
                    AnnSection(pa, shoe, host_id, tb_od)]
    return GeometrySpec(
        td_m=shoe, track_depth_m=track, hole_id_in=host_id,
        pipe_od_in=tb_od, pipe_id_in=tb_id,
        ann_sections=ann_secs, pipe_sections=pipe_secs,
        operation_identity=TIEBACK_OPERATION_IDENTITY)


@dataclass
class ChartOptions:
    """Documented parameters, all overridable, none hidden."""
    surface_line_kpsi_at_8bpm: float = 0.010   # Doc 17 source anchor
    back_pressure_psi: float = 0.0
    dt_min: float = 0.02
    tail_cap_min: float = 60.0    # post-job equalization tail guard
    shutin_ramp_min: float = 10.0 # D14 shut-in ramp (source anchor 244 -> 254)
    axis_x: Optional[Tuple[float, float, float, float]] = None   # (lo,hi,minor,major)
    axis_y1: Optional[Tuple[float, float, float, float]] = None
    axis_y2: Optional[Tuple[float, float, float, float]] = None
    axis_y3: Optional[Tuple[float, float, float, float]] = None
    marker_time_override: Optional[float] = None
    # ---- v1.4.3 LOCAL CANDIDATE: additive, frozen defaults preserved ----
    float_equipment: bool = False   # forwarded to JobDesign (v1.2.4 F3 flag)
    plot_window: str = 'full_record'  # 'full_record' = v1.4.2 bytes exactly;
                                      # 'pumping_only' = render the pumping
                                      # branch only (t < t_eod - 1e-9)


def _rec_get(rec: Dict[str, Any], key: str) -> Any:
    if key not in rec:
        raise ChartInputError(
            "fluid_data record is missing the Phase IV key %r "
            "(expected the build_fluid_record contract)." % key)
    return rec[key]


def stages_from_fluid_data(fluid_data: Dict[str, Dict[str, Any]]
                           ) -> Tuple[List[FluidStageSpec], List[str]]:
    """Phase IV `fluid_data` -> validated stage list + warnings.

    Mirrors Phase IV's own validation semantics (fail-loud on the same
    conditions its export path rejects) and never invents numbers.
    """
    if not isinstance(fluid_data, dict) or not fluid_data:
        raise ChartInputError(
            "fluid_data is empty — select and configure fluids in Phase IV first.")

    warnings: List[str] = []

    # -- displacement fluid is the initial wellbore fluid (Phase II mud) -----
    disp = fluid_data.get("Displacement Fluid")
    if not isinstance(disp, dict):
        raise ChartInputError(
            "'Displacement Fluid' record is required: it defines the initial "
            "wellbore fluid density (live Phase II mud reference in Phase IV). "
            "Re-select it in Phase IV and set the Phase II mud weight.")
    disp_rho = _er01_finite(_rec_get(disp, "effective_density"),
                            "Displacement Fluid density")
    if disp_rho <= 0.0:
        raise ChartInputError(
            "Displacement Fluid density is not set (Phase II mud weight missing "
            "or invalid) — pressures cannot be computed. Phase IV shows this "
            "as 'Not set in Phase II & III'.")

    # -- sort by the Phase IV cumulative-time chain (order-robust) -----------
    records = [(k, v) for k, v in fluid_data.items() if isinstance(v, dict)]
    # ER01-F2: stage times must be finite and non-negative (NaN would make
    # the sort order undefined; negative cumulative time is disallowed).
    for _ft, _rec in records:
        _tv = _rec.get("cumul_time_min", _rec.get("duration_min", 0.0))
        if _tv not in (None, ""):
            _t = _er01_finite(_tv, "%s: stage time (cumul_time_min/"
                                    "duration_min)" % _ft)
            if _t < 0.0:
                raise ChartInputError(
                    "%s: stage time must be >= 0; got %r." % (_ft, _tv))
    records.sort(key=lambda kv: (float(kv[1].get("cumul_time_min",
                                                 kv[1].get("duration_min", 0.0)) or 0.0),
                                 kv[0]))

    stages: List[FluidStageSpec] = []
    for ftype, rec in records:
        volume = _er01_finite(_rec_get(rec, "volume"),
                              "%s: stage volume [bbl]" % ftype)
        rate = _er01_finite(_rec_get(rec, "min_rate"),
                            "%s: pump rate [bbl/min]" % ftype)
        rho = _er01_finite(_rec_get(rec, "effective_density"),
                           "%s: density [pcf]" % ftype)
        if volume < 0.0:
            raise ChartInputError(
                "%s: volume must be >= 0 (0 = documented skip); got %r."
                % (ftype, rec.get("volume")))
        material = str(rec.get("material_name", ftype))

        # D7: the record MAY carry its own Bingham PV/YP (the host app will
        # provide them for Spacer/Pre Flush).  Accepted keys: pv_cp / pv and
        # yp_lbf100ft2 / yp.  Invalid text = missing (the rheology layer
        # then warns per fluid — nothing silently zeroed).
        pv_v = yp_v = None
        for key in ("pv_cp", "pv"):
            if rec.get(key) not in (None, ""):
                try:
                    pv_v = clean_number(rec[key])
                except ValueError:
                    pv_v = None
                if pv_v is not None and not math.isfinite(pv_v):
                    raise ChartInputError(
                        "%s: %s must be a finite number; got %r."
                        % (ftype, key, rec[key]))
                break
        for key in ("yp_lbf100ft2", "yp"):
            if rec.get(key) not in (None, ""):
                try:
                    yp_v = clean_number(rec[key])
                except ValueError:
                    yp_v = None
                if yp_v is not None and not math.isfinite(yp_v):
                    raise ChartInputError(
                        "%s: %s must be a finite number; got %r."
                        % (ftype, key, rec[key]))
                break

        if ftype == "Displacement Fluid":
            if volume <= 0.0:
                warnings.append(
                    "Displacement Fluid volume is 0 — no displacement stage is "
                    "drawn; the job ends at the end of the last slurry stage.")
            elif rate <= 0.0:
                raise ChartInputError(
                    "Displacement Fluid: pump rate invalid ('INVALID RATE' in "
                    "Phase IV). Correct the rate before charts can be produced.")
            else:
                stages.append(FluidStageSpec(ftype, material, volume, rho, rate,
                                             pv_cp=pv_v, yp_lbf100ft2=yp_v))
            continue

        if rho <= 0.0:
            raise ChartInputError(
                "%s: density resolves to %r pcf (Phase IV shows an error for "
                "this field). Correct the density before charts can be produced."
                % (ftype, rec.get("density")))
        if rate <= 0.0:
            raise ChartInputError(
                "%s: pump rate is invalid ('INVALID RATE' chain in Phase IV). "
                "Correct the rate before charts can be produced." % ftype)
        if volume <= 0.0:
            warnings.append("%s: volume is 0 — stage skipped." % ftype)
            continue

        stages.append(FluidStageSpec(ftype, material, volume, rho, rate,
                                     pv_cp=pv_v, yp_lbf100ft2=yp_v))

    if not stages:
        raise ChartInputError(
            "No pumpable stage found (all volumes are 0) — nothing to draw.")
    return stages, warnings


# ----------------------------------------------------------------------------
# Rheology + documented friction models (frpressc.dll basis, Doc 17 §3)
# ----------------------------------------------------------------------------
RE_LAM = 2100.0

# ---- v1.2.7 (Stage 6): laminar calibration factor + regime guard ------
# See the changelog block "LAMINAR CALIBRATION FACTOR + REGIME GUARD
# v1.2.7" and lam_alpha_policy() below.  Evidence: doc 21 (Stage-5
# alpha scan) + doc 22 (Stage-6 C audit & guard design).
LAM_ALPHA = 1.00         # DOC58_SI_CANDIDATE_01 (2026-11-03): nonphysical
                         # laminar excess REMOVED per owner gate — the exact-HB
                         # laminar gradient is returned unscaled in pipe and
                         # annular paths (deep-laminar, PHI_EXT extension,
                         # s_lam/s_ext/s_win scheduled bands, window anchor and
                         # crossing all read this constant); continuity of the
                         # laminar->transition boundary is preserved by the
                         # unchanged C0 log-log window blend.  No new empirical
                         # coefficient is introduced.
# ---- v1.4.2 CONTINUOUS ANNULAR PSI-SCHEDULE (work order #35) ----------
# The annular laminar multiplier m_ann = 1 + (LAM_ALPHA-1)*s(psi) with
# C1 smootherstep schedules of the LOCAL psi = tau_y/tau_w.  No well
# names, no per-well tables, no mode flags (work order #35).  The edges
# below are the doc-35 repository-wide fit (23-well counterfactual +
# psi census); they are module constants, not configuration.
PSI_LAM_KEEP = 0.002     # s_lam = 1 below (yield-stabilised laminar family)
PSI_LAM_PLAIN = 0.011    # s_lam = 0 from here (de-facto power-law band)
PSI_LAM_ASC0 = 0.016     # casing-band ascent opens (D/F-class states)
PSI_LAM_ASC1 = 0.022     # s_lam = 1 above (casing band closed)
PSI_EXT_0 = 0.002        # s_ext: 0 below (A-class plain extension state)
PSI_EXT_1 = 0.010        # s_ext: 1 above (= frozen PHI_EXT_GATE edge)
PSI_WIN_KEEP = 0.002     # s_win = 1 below (W-MANSURI-1-class muds)
PSI_WIN_PLAIN = 0.0470   # s_win = 0 above (AZNS-166-class window states)
PSI_WIN_ASC0 = 0.0475    # deep-liner window ascent opens (RW1-class)
PSI_WIN_ASC1 = 0.0540    # s_win = 1 above


def _psi_ramp(x, lo, hi):
    """C1 smootherstep ramp: 0 at x<=lo, 1 at x>=hi, t^2(3-2t) inside."""
    if hi <= lo:
        return 0.0 if x < hi else 1.0
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    t = (x - lo) / (hi - lo)
    return t * t * (3.0 - 2.0 * t)


def _s_lam(psi):
    """Deep-laminar schedule: keep-band -> plain-band -> casing-band."""
    return _psi_ramp(psi, PSI_LAM_ASC0, PSI_LAM_ASC1) \
        + (1.0 - _psi_ramp(psi, PSI_LAM_KEEP, PSI_LAM_PLAIN))


def _s_ext(psi):
    """Extension-zone schedule (replaces the hard PHI_EXT_GATE switch)."""
    return _psi_ramp(psi, PSI_EXT_0, PSI_EXT_1)


def _s_win(psi):
    """Window-anchor schedule: keep-band -> plain-band -> liner window."""
    return _psi_ramp(psi, PSI_WIN_ASC0, PSI_WIN_ASC1) \
        + (1.0 - _psi_ramp(psi, PSI_WIN_KEEP, PSI_WIN_PLAIN))
# ---- v1.3.0 DYNAMIC SEGMENT-LEVEL CORRECTION (work order #25) ---------
# The t0-frozen global guard (lam_alpha_policy / L_EFF_GUARD = 0.55) is
# REMOVED.  The laminar factor LAM_ALPHA is applied per segment at every
# time step by the friction functions themselves, and the laminar<->turbulent
# boundary follows the CEMCADE 2002 engine's own n-dependent regime window,
# reverse-engineered from frpressc.dll (sha-verified 2002 build):
#   fr_reynoldsLowerUpperOfPipePowerLaw / ...OfSlotPowerLaw:
#     lower(n) = 3250 - 1150*n            (n=1 -> 2100 = RE_LAM, Newtonian)
#     upper(n) = (F1/off(n))^(1/(1+slope(n))) - (F1/off(1))^(1/(1+slope(1)))
#                + 3000      with F1 = 16 (pipe) / 24 (slot), and for
#     extreme shear-thinning (n < 0.31 pipe / 0.28 slot) the DLL's
#     power-law branch 10^(-k*n)*C.  The turbulent fit constants
#     (off = c1 + k1*ln n, slope = c2 + k2*ln n) are the DLL's own.
# Inside the window the gradient follows a CONTINUOUS log-log blend
# anchored at THIS segment's own edges: the exact-HB x LAM_ALPHA gradient
# at Re = lower and the Blasius gradient at Re = upper (module-anchored,
# no per-well or per-fluid constants).  Turbulent branch (Re >= upper)
# stays the TEST-1-validated Blasius, bit-identical to v1.2.7.
WIN_LOWER_C = 3250.0     # frpressc.dll 0x1080a254
WIN_LOWER_K = 1150.0     # frpressc.dll 0x1080a258
WIN_UP_ADD = 3000.0      # frpressc.dll 0x1080a24c
PHI_EXT_GATE = 0.01      # v1.3.1: extension-zone yield-significance
                         # gate phi = tau_y/tau_w (plug carries >= 1% of
                         # the wall shear stress); the repository fluids
                         # show a 48x data void across the gate:
                         # phi = 0.0005 (A/WM displacement muds, reference
                         # = Blasius-like) vs phi >= 0.024 (D mud) and
                         # 0.12-0.28 (166/DEH/138, reference = x2-laminar).
                         # Single disclosed regime-classification
                         # threshold alongside RE_LAM = 2100 -- doc 26 s.4.
N_MIN_PIPE = 0.31        # frpressc.dll 0x1080a250
N_MIN_SLOT = 0.28        # frpressc.dll 0x1080a264
PIPE_OFF_C = 0.07850400358   # DLL pipe turbulent fit (n=1 -> Blasius)
PIPE_OFF_K = 0.009808500297
PIPE_SLO_C = -0.2498400062
PIPE_SLO_K = 0.05964599922
SLOT_OFF_C = 0.09604500234
SLOT_OFF_K = 0.0082711
SLOT_SLO_C = -0.2710300088
SLOT_SLO_K = 0.06398499757
PIPE_UP_BASE = (16.0 / (PIPE_OFF_C + PIPE_OFF_K * 0.0))     ** (1.0 / (1.0 + PIPE_SLO_C))     # n=1 reference term (subtracted)
SLOT_UP_BASE = (24.0 / SLOT_OFF_C) ** (1.0 / (1.0 + SLOT_SLO_C))

#: TF-02R (CFW128 TF-02R scope 1): Dodge-Metzner (1959) fitted
#: flow-behavior-index domain.  The empirical exponent clamp (n_eff)
#: lives ONLY inside the DM correlation (_seg_fdm); Re_MR (_seg_remr)
#: and every regime key (RE_LAM, window edges), Re_gen, laminar physics
#: and all other paths stay on the true n.  Fluids outside the fitted
#: range keep the original SIx1 turbulent branch (see
#: _seg_n_in_dm_domain) -- explicit, untuned, no new constants.
N_DM_MIN = 0.36
N_DM_MAX = 1.0


def _seg_n_in_dm_domain(n):
    """TF-02R scope 1 correlation-domain policy (explicit, untuned): the
    Dodge-Metzner empirical map is applied only inside its fitted range
    N_DM_MIN <= n <= N_DM_MAX (Dodge & Metzner 1959).  For fluids outside
    that range the segment keeps the ORIGINAL SIx1 turbulent branch
    (Blasius f = 0.0791/Re_gen^0.25 with the parent's own window anchors
    and crossing) -- the frozen parent behavior on those spans, bit-exact:
    no extrapolation of fitted coefficients, no per-well or per-fluid
    constants, no threshold changes."""
    return N_DM_MIN <= n <= N_DM_MAX


@dataclass
class Fluid:
    """Placement fluid: density (ppg) + one rheology model.

    mu_p_cp > 0  -> Bingham plastic (mu_p, tau_y)   [the CEMCADE default]
    mu_p_cp == 0 -> power law (n_pl, K_pl)
    frictionless_fluid -> D7/D9 fallback: the density still weighs on the
    columns but this fluid contributes ZERO friction/yield (a named warning
    was returned to the caller).
    gel_pa -> D13: measured static gel (10-min, Pa).  After the pump stops
    the column exchange must overcome max(tau_y, gel) per segment.
    """
    name: str
    rho_ppg: float
    mu_p_cp: float = 0.0
    tau_y: float = 0.0        # yield point, lbf/100ft2
    n_pl: float = 0.5
    K_pl: float = 1.0         # Pa*s^n
    gel_pa: float = 0.0       # D13: measured 10-min gel, Pa
    frictionless_fluid: bool = False

    @property
    def _rho(self) -> float:
        return rho_si(self.rho_ppg)

    @property
    def _mu(self) -> float:
        return self.mu_p_cp * CP_TO_PAS

    @property
    def _ty(self) -> float:
        return self.tau_y * LBF100FT2_TO_PA

    @property
    def _ty_tail(self) -> float:
        """Yield that resists the post-job static exchange (D13):
        while pumping the fitted YP governs; at rest the measured 10-min
        gel (if any) is the stronger resistance."""
        return max(self._ty, self.gel_pa)


def _seg_window(n, slot):
    """v1.3.0 CEMCADE regime window (lower, upper) on Re_gen -- the exact
    algebra of frpressc.dll fr_reynoldsLowerUpperOf{Pipe,Slot}PowerLaw."""
    lower = WIN_LOWER_C - WIN_LOWER_K * n
    if slot:
        if n >= N_MIN_SLOT:
            off = SLOT_OFF_C + SLOT_OFF_K * math.log(n)
            slo = SLOT_SLO_C + SLOT_SLO_K * math.log(n)
            upper = (24.0 / off) ** (1.0 / (1.0 + slo)) - SLOT_UP_BASE \
                + WIN_UP_ADD
        else:
            upper = (10.0 ** (-8.19 * n)) * 1106969.0
    else:
        if n >= N_MIN_PIPE:
            off = PIPE_OFF_C + PIPE_OFF_K * math.log(n)
            slo = PIPE_SLO_C + PIPE_SLO_K * math.log(n)
            upper = (16.0 / off) ** (1.0 / (1.0 + slo)) - PIPE_UP_BASE \
                + WIN_UP_ADD
        else:
            upper = (10.0 ** (-7.84 * n)) * 1328529.0
    return lower, upper


def _seg_regen(fl, kind, dims, q, n, K, ty):
    """Re_gen at rate q for the segment geometry (mirrors the fric_*_hb
    conventions exactly: pipe uses D, slot uses Dh = 2wh/(w+h))."""
    if q <= 0.0:
        return 0.0
    if kind == 'pipe':
        D = dims[0] * 2.0                       # dims = (R,)
        A = math.pi * D * D / 4.0
        V = q / A
        Dh = D
    else:
        h, w = dims
        A = w * h
        V = q / A
        Dh = 2.0 * w * h / (w + h)
    geff = 8.0 * V / Dh * (3.0 * n + 1.0) / (4.0 * n)
    mu_e2 = K * geff ** (n - 1.0) + ty / geff
    return fl._rho * V * Dh / mu_e2


def _seg_rate_for_re(fl, kind, dims, n, K, ty, target, q_hint):
    """Bisection: the rate q at which Re_gen(q) == target (Re_gen is
    strictly increasing in q for HB fluids)."""
    lo_q = 1e-15
    hi_q = max(q_hint, 1e-9)
    for _ in range(60):
        if _seg_regen(fl, kind, dims, hi_q, n, K, ty) >= target:
            break
        hi_q *= 4.0
    for _ in range(80):
        mid = 0.5 * (lo_q + hi_q)
        if _seg_regen(fl, kind, dims, mid, n, K, ty) < target:
            lo_q = mid
        else:
            hi_q = mid
    return 0.5 * (lo_q + hi_q)


def _seg_rate_for_re_exact(fl, kind, dims, n, K, ty, target, lo_q, hi_q):
    """Bisection on a BRACKETED rate interval (Re_gen monotone up)."""
    for _ in range(80):
        mid = 0.5 * (lo_q + hi_q)
        if _seg_regen(fl, kind, dims, mid, n, K, ty) < target:
            lo_q = mid
        else:
            hi_q = mid
    return 0.5 * (lo_q + hi_q)


def _seg_lam2_at_re(fl, kind, dims, n, K, ty, Re, q_hint):
    """exact-HB x LAM_ALPHA gradient (Pa/m) at the rate where Re_gen=Re."""
    q = _seg_rate_for_re(fl, kind, dims, n, K, ty, Re, q_hint)
    if kind == 'pipe':
        return _hb_G_cached(fl, 'pipe', dims, q, n, K, ty) * LAM_ALPHA
    return _hb_G_cached(fl, 'slot', dims, q, n, K, ty) * LAM_ALPHA


def _seg_blas_at_re(fl, kind, dims, n, K, ty, Re, q_hint):
    """Blasius gradient (Pa/m) at the rate where Re_gen=Re.
    TF-02: retained for audit/diff-minimality; the HB window machinery
    (crossing roots and blend upper anchor) now calls _seg_dm_at_re."""
    q = _seg_rate_for_re(fl, kind, dims, n, K, ty, Re, q_hint)
    if kind == 'pipe':
        D = dims[0] * 2.0
        A = math.pi * D * D / 4.0
        V = q / A
        return 2.0 * (0.0791 / Re ** 0.25) * fl._rho * V * V / D
    h, w = dims
    A = w * h
    V = q / A
    Dh = 2.0 * w * h / (w + h)
    return 2.0 * (0.0791 / Re ** 0.25) * fl._rho * V * V / Dh


def _seg_fdm(remr, n_eff):
    """TF-02: Dodge-Metzner (1959) Fanning friction factor from the implicit
    correlation  1/sqrt(f) = (4/n^0.75) log10(Re_MR f^(1-n/2)) - 0.4/n^1.2,
    solved with the engine's own frozen damped fixed-point schedule (the
    fric_pipe_pl iterator: 80 iterations, 50/50 damping, 1e-12 log floor).
    TF-01 evidence: contractive (4.6e-16 vs independent bisection) and
    strictly decreasing in Re_MR over 2500-1e5 for all archived fluids."""
    f = 0.005
    for _ in range(80):
        rhs = (4.0 / n_eff ** 0.75) \
            * math.log10(max(remr * f ** (1.0 - n_eff / 2.0), 1e-12)) \
            - 0.4 / n_eff ** 1.2
        f_new = 1.0 / (rhs * rhs)
        f = 0.5 * f + 0.5 * f_new
    return f


def _seg_remr(v, dh, n, K, rho):
    """TF-02R (scope 1, TF-03 MAJOR-01): Metzner-Reed Reynolds of THIS
    segment state, bit-identical to the frozen fric_pipe_pl form with the
    segment's own hydraulic-diameter convention (pipe D, slot
    Dh = 2wh/(w+h)) and Fanning definition.  Uses the PHYSICAL fluid pair
    (n, K [Pa*s^n]): TF-02 inserted the clamped n_eff here alongside the
    unclamped K, which is dimensionally inconsistent whenever n != n_eff
    (a spurious (8V/Dh)^(n_eff-n) shear-rate scaling).  The empirical
    exponent clamp now applies ONLY inside _seg_fdm."""
    return rho * v ** (2.0 - n) * dh ** n \
        / (8.0 ** (n - 1.0) * K
           * ((3.0 * n + 1.0) / (4.0 * n)) ** n)


def _seg_dm_at_re(fl, kind, dims, n, K, ty, Re, q_hint):
    """TF-02: Dodge-Metzner turbulent gradient (Pa/m) at the rate where
    Re_gen=Re -- the re-anchored replacement of _seg_blas_at_re inside the
    HB window machinery (same segment states, same Dh convention, same
    Fanning definition; window keys and lower anchor untouched).
    TF-02R: Re_MR is built from the physical (n, K) pair and out-of-domain
    fluids delegate to the original SIx1 Blasius map (scope-1 policy)."""
    if not _seg_n_in_dm_domain(n):
        # TF-02R scope 1: out-of-domain fluid -> the ORIGINAL SIx1
        # turbulent map (Blasius on Re_gen; body unchanged from parent).
        return _seg_blas_at_re(fl, kind, dims, n, K, ty, Re, q_hint)
    q = _seg_rate_for_re(fl, kind, dims, n, K, ty, Re, q_hint)
    n_eff = min(max(n, N_DM_MIN), N_DM_MAX)
    if kind == 'pipe':
        D = dims[0] * 2.0
        A = math.pi * D * D / 4.0
        V = q / A
        f = _seg_fdm(_seg_remr(V, D, n, K, fl._rho), n_eff)
        return 2.0 * f * fl._rho * V * V / D
    h, w = dims
    A = w * h
    V = q / A
    Dh = 2.0 * w * h / (w + h)
    f = _seg_fdm(_seg_remr(V, Dh, n, K, fl._rho), n_eff)
    return 2.0 * f * fl._rho * V * V / Dh


def _seg_cross_re(fl, kind, dims, n, K, ty, lo, hi, q_hint):
    """The laminar(x LAM_ALPHA)/Dodge-Metzner turbulent crossing inside the
    window (the DLL's implicit psi-root reduced to the module's own
    curves; TF-02: re-anchored to the same DM map as the upper edge)."""
    flo = _seg_lam2_at_re(fl, kind, dims, n, K, ty, lo, q_hint) - \
        _seg_dm_at_re(fl, kind, dims, n, K, ty, lo, q_hint)
    fhi = _seg_lam2_at_re(fl, kind, dims, n, K, ty, hi, q_hint) - \
        _seg_dm_at_re(fl, kind, dims, n, K, ty, hi, q_hint)
    if flo <= 0.0:
        return lo
    if fhi >= 0.0:
        # TF-02R scope 2 (TF-03 MINOR-01 item 1): the inverted case --
        # laminar still above the turbulent map at hi.  TF-02 returned hi,
        # switching from the laminar branch to the turbulent map with a
        # VALUE STEP of lam2(hi)-dm(hi) (non-C0; demonstrated by the
        # synthetic T9 test).  Both curves are monotone increasing and the
        # turbulent map ultimately grows faster than the laminar line, so
        # the true crossing lies at or above hi: expand geometrically,
        # then bisect with the same 60-step schedule.  C0 and monotone by
        # construction; no new constants.  Out-of-domain fluids keep the
        # parent's exact fallback (scope-1 policy: whole original branch).
        if not _seg_n_in_dm_domain(n):
            return hi
        a = hi
        b = hi
        found = False
        for _ in range(200):
            b *= 2.0
            if _seg_lam2_at_re(fl, kind, dims, n, K, ty, b, q_hint) - \
                    _seg_dm_at_re(fl, kind, dims, n, K, ty, b, q_hint) < 0.0:
                found = True
                break
            a = b
        if not found:
            return hi
        for _ in range(60):
            m = 0.5 * (a + b)
            fm = _seg_lam2_at_re(fl, kind, dims, n, K, ty, m, q_hint) - \
                _seg_dm_at_re(fl, kind, dims, n, K, ty, m, q_hint)
            if fm > 0.0:
                a = m
            else:
                b = m
        return 0.5 * (a + b)
    a, b = lo, hi
    for _ in range(60):
        m = 0.5 * (a + b)
        fm = _seg_lam2_at_re(fl, kind, dims, n, K, ty, m, q_hint) - \
            _seg_dm_at_re(fl, kind, dims, n, K, ty, m, q_hint)
        if fm > 0.0:
            a = m
        else:
            b = m
    return 0.5 * (a + b)


def _seg_edges(fl, kind, dims, n, K, ty, q_hint):
    """(G_lam2_at_lower, G_dm_at_upper) for one segment -- cached on the
    Fluid instance (dies with the fluid: no cross-job state, HB3 rule).

    G_lam2_at_lower: exact-HB laminar gradient (Pa/m) x LAM_ALPHA at the
    rate where Re_gen = lower(n).  G_dm_at_upper: Dodge-Metzner turbulent
    (Pa/m) at the rate where Re_gen = upper(n) (TF-02 re-anchor: the
    blend's upper edge and the turbulent branch now share one map, so
    gradient continuity at Re_gen = upper(n) holds by construction)."""
    lo, hi = _seg_window(n, kind == 'slot')
    key = ('v13seg', kind, dims[0], dims[1] if len(dims) > 1 else 0.0,
           n, K, ty, fl._rho)
    try:
        cache = fl._seg_cache
    except AttributeError:
        cache = OrderedDict()
        try:
            fl._seg_cache = cache
        except Exception:
            pass
    hit = cache.get(key)
    if hit is not None:
        try:
            cache.move_to_end(key)
        except Exception:
            pass
        return (hit, lo, hi)
    q_lo = _seg_rate_for_re(fl, kind, dims, n, K, ty, lo, q_hint)
    q_hi = _seg_rate_for_re(fl, kind, dims, n, K, ty, hi, q_hint)
    if kind == 'pipe':
        g_lo = _hb_G_cached(fl, 'pipe', dims, q_lo, n, K, ty) * LAM_ALPHA
        D = dims[0] * 2.0
        A = math.pi * D * D / 4.0
        V_hi = q_hi / A
        Re_hi = _seg_regen(fl, kind, dims, q_hi, n, K, ty)
        n_eff = min(max(n, N_DM_MIN), N_DM_MAX)
        if _seg_n_in_dm_domain(n):
            f_hi = _seg_fdm(_seg_remr(V_hi, D, n, K, fl._rho), n_eff) \
                if Re_hi > 0 else 0.0
        else:
            # TF-02R scope 1: original SIx1 Blasius upper anchor (parent
            # line, bit-exact) for out-of-domain fluids.
            f_hi = 0.0791 / Re_hi ** 0.25 if Re_hi > 0 else 0.0
        g_hi = 2.0 * f_hi * fl._rho * V_hi * V_hi / D
    else:
        # v1.4.2: the slot edge is cached RAW; the psi-schedule multiplier
        # is applied per call in fric_slot_hb (the schedule keys on the
        # segment's live state, which is not part of the cache key).
        g_lo = _hb_G_cached(fl, 'slot', dims, q_lo, n, K, ty)
        h, w = dims
        A = w * h
        V_hi = q_hi / A
        Dh = 2.0 * w * h / (w + h)
        Re_hi = _seg_regen(fl, kind, dims, q_hi, n, K, ty)
        n_eff = min(max(n, N_DM_MIN), N_DM_MAX)
        if _seg_n_in_dm_domain(n):
            f_hi = _seg_fdm(_seg_remr(V_hi, Dh, n, K, fl._rho), n_eff) \
                if Re_hi > 0 else 0.0
        else:
            # TF-02R scope 1: original SIx1 Blasius upper anchor (parent
            # line, bit-exact) for out-of-domain fluids.
            f_hi = 0.0791 / Re_hi ** 0.25 if Re_hi > 0 else 0.0
        g_hi = 2.0 * f_hi * fl._rho * V_hi * V_hi / Dh
    val = (g_lo, g_hi) if (g_lo > 0.0 and g_hi > 0.0) else None
    if val is not None:
        try:
            cache[key] = val
            if len(cache) > _HB_CACHE_MAX:
                cache.popitem(last=False)
        except Exception:
            pass
        return (val, lo, hi)
    return (None, lo, hi)


def fric_pipe_bingham(q, L, D, rho, mu, ty):
    """Buckingham-Reiner laminar / Blasius-Fanning turbulent.  Returns Pa."""
    if q <= 0.0 or L <= 0.0:
        return 0.0
    A = math.pi * D * D / 4.0
    V = q / A
    Re = rho * V * D / mu
    if Re < RE_LAM:
        return L * (32.0 * mu * V / (D * D) + (16.0 / 3.0) * ty / D)
    f = 0.0791 / Re ** 0.25
    return L * 2.0 * f * rho * V * V / D


def fric_pipe_pl(q, L, D, rho, n, K):
    """Power-law pipe: exact laminar, Dodge-Metzner turbulent (Fanning f)."""
    if q <= 0.0 or L <= 0.0:
        return 0.0
    A = math.pi * D * D / 4.0
    V = q / A
    ReMR = rho * V ** (2.0 - n) * D ** n / (8.0 ** (n - 1.0) * K
                                            * ((3.0 * n + 1.0) / (4.0 * n)) ** n)
    if ReMR < RE_LAM:
        gw = 8.0 * V * (3.0 * n + 1.0) / (4.0 * n * D)
        return 4.0 * K * gw ** n * L / D
    f = 0.005
    for _ in range(80):
        rhs = (4.0 / n ** 0.75) * math.log10(max(ReMR * f ** (1.0 - n / 2.0), 1e-12)) \
              - 0.4 / n ** 1.2
        f_new = 1.0 / (rhs * rhs)
        f = 0.5 * f + 0.5 * f_new
    return L * 2.0 * f * rho * V * V / D


def fric_slot_bingham(q, L, Do, Di, rho, mu, ty):
    """Concentric annulus via the documented slot approximation:
    w = pi(Do+Di)/2, h = (Do-Di)/2 (exact area match).
    Laminar: exact Bingham slot, plug-correction fixed point on the wall
    shear stress:  dP/dL = 12 mu V / h^2 / (1 - 1.5 phi + 0.5 phi^3),
    phi = ty/tau_w,  tau_w = h (dP/dL) / 2.
    Turbulent: Fanning-Blasius on Dh = 2wh/(w+h).
    """
    if q <= 0.0 or L <= 0.0:
        return 0.0
    h = (Do - Di) / 2.0
    w = math.pi * (Do + Di) / 2.0
    A = w * h
    V = q / A
    Dh = 2.0 * w * h / (w + h)
    Re = rho * V * Dh / mu
    if Re < RE_LAM:
        base = 12.0 * mu * V / (h * h)
        tau_w = 6.0 * mu * V / h + 1.5 * ty
        grad = base
        for _ in range(60):
            phi = min(ty / tau_w, 0.98)
            grad = base / (1.0 - 1.5 * phi + 0.5 * phi ** 3)
            tau_w_new = h * grad / 2.0
            if abs(tau_w_new - tau_w) <= 1e-9 * max(tau_w, 1.0):
                break
            tau_w = 0.5 * (tau_w + tau_w_new)
        return L * grad
    f = 0.0791 / Re ** 0.25
    return L * 2.0 * f * rho * V * V / Dh


def _hb_q_slot(G, h, w, n, K, ty, N=800):
    """Exact HB laminar slot flow (2*half-gap integration, plug band
    where tau_w <= tau0).  Port of the TEST-1-validated solver."""
    tw = G * h / 2.0
    if tw <= ty:
        return 0.0
    A = tw - ty
    p1 = (n + 1.0) / n
    ye = A / G
    c = n / (G * (n + 1.0) * K ** (1.0 / n))
    ys = np.linspace(0.0, ye, N)
    us = c * (A ** p1 - np.maximum(A - G * ys, 0.0) ** p1)
    ue = c * A ** p1
    Q_half = float(np.trapezoid(us, ys)) + ue * (h / 2.0 - ye)
    return 2.0 * w * Q_half


def _hb_q_pipe(G, R, n, K, ty, N=800):
    """Exact HB laminar pipe flow (axisymmetric, plug core)."""
    tw = G * R / 2.0
    if tw <= ty:
        return 0.0
    A = tw - ty
    p1 = (n + 1.0) / n
    c = 2.0 * n / (G * (n + 1.0) * K ** (1.0 / n))
    rp = 2.0 * ty / G
    up = c * A ** p1
    rs = np.linspace(rp, R, N)
    us = c * (A ** p1 - np.maximum(G * rs / 2.0 - ty, 0.0) ** p1)
    return 2 * math.pi * (float(np.trapezoid(rs * us, rs))
                          + up * rp ** 2 / 2.0)


def _hb_solve_G(kind, q, dims, n, K, ty, N=120):
    """Invert q(G) by bisection (TEST-1 schedule, N=120)."""
    glo = (2.0 * ty / (dims[0] if kind == 'slot' else 2.0 * dims[0])) \
        if ty > 0 else 1e-9
    f = (lambda G: _hb_q_slot(G, dims[0], dims[1], n, K, ty, N)) \
        if kind == 'slot' else (lambda G: _hb_q_pipe(G, dims[0], n, K, ty, N))
    ghi = max(glo * 2.0 + 1.0, 1.0)
    for _ in range(80):
        if f(ghi) > q:
            break
        ghi *= 2.0
    for _ in range(50):
        gm = 0.5 * (glo + ghi)
        if f(gm) < q:
            glo = gm
        else:
            ghi = gm
    return 0.5 * (glo + ghi)


_HB_CACHE_MAX = 4096    # v1.2.6 K2: bounded LRU capacity (per Fluid)


def _hb_G_cached(fl, kind, dims, q, n, K, ty):
    """Per-Fluid-instance memoization.
    v1.2.6 K1: EXACT full-precision q in the key (the v1.2.5
    round(q, 3) bucket key let later rates reuse the first-come G
    inside ~0.19 bpm bins -> order-dependent free-fall finals).
    v1.2.6 K2: bounded LRU (OrderedDict) -> cleanable structure,
    capped memory; eviction is result-neutral because _hb_solve_G is
    a pure function of the key.  The cache lives and dies with the
    fluid -> no cross-job state can leak (v1.2.5 HB3 retained)."""
    key = (kind, q, dims[0], dims[1] if len(dims) > 1 else 0.0,
           n, K, ty, fl._rho)
    try:
        cache = fl._hb_cache
    except AttributeError:
        cache = OrderedDict()
        try:
            fl._hb_cache = cache
        except Exception:
            pass
    G = cache.get(key)
    if G is not None:
        try:
            cache.move_to_end(key)
        except Exception:
            pass
        return G
    G = _hb_solve_G(kind, q, dims, n, K, ty)
    try:
        cache[key] = G
        if len(cache) > _HB_CACHE_MAX:
            cache.popitem(last=False)
    except Exception:
        pass
    return G


def fric_pipe_hb(q, L, D, fl: Fluid, lam_alpha=None):
    """Direct Herschel-Bulkley: exact laminar G, turbulent branch
    (Re_gen from the HB effective viscosity incl. tau0; TF-02:
    Dodge-Metzner map on the Metzner-Reed Reynolds, Fanning f on D --
    the single authorized change of this candidate; the blend upper
    edge is re-anchored to the same map).
    v1.3.0 DYNAMIC SEGMENT-LEVEL CORRECTION (work order #25): the
    lam_alpha kwarg is DEPRECATED/IGNORED -- the laminar calibration is
    applied HERE, per segment at every call: laminar segments
    (Re_gen <= RE_LAM) carry LAM_ALPHA; the CEMCADE n-dependent window
    (lower = 3250-1150n .. upper) blends CONTINUOUSLY (log-log) between
    this segment's laminar-x2 edge and its turbulent edge; turbulent
    segments (Re_gen >= upper) use the turbulent branch directly.
    Returns Pa."""
    if q <= 0.0 or L <= 0.0:
        return 0.0
    n, K, ty = fl.n_pl, fl.K_pl, fl._ty
    A = math.pi * D * D / 4.0
    V = q / A
    G = _hb_G_cached(fl, 'pipe', (D / 2.0,), q, n, K, ty)
    geff = 8.0 * V / D * (3.0 * n + 1.0) / (4.0 * n)
    mu_e2 = K * geff ** (n - 1.0) + ty / geff
    Re = fl._rho * V * D / mu_e2
    if Re > RE_LAM:
        edges, lo, hi = _seg_edges(fl, 'pipe', (D / 2.0,), n, K, ty, q)
        if Re < lo:
            # v1.3.1 PHI-GATED extension zone (2100, lower(n)): the x2
            # family gradient applies only to yield-significant states --
            # phi = tau_y / tau_w >= PHI_EXT_GATE (plug spans >= 5%% of the
            # wall stress: the yield-stabilised laminar regime); de-facto
            # power-law states (phi < gate) take the PLAIN exact-HB
            # laminar, which crosses Blasius at the natural Newtonian-
            # anchored transition.  Evidence (work order #26): well A's
            # 140 m annulus at Re_gen=2164 has phi=0.0002 (tau_y=0.026 Pa)
            # and the reference is Blasius-like there (x2 would add
            # +32.18 psi); DEH/138 extension sections have phi=0.28
            # (tau_y 1.29-3.14 Pa) and the reference carries the x2
            # gradient.  Gate disclosed in doc 26 (single regime-
            # classification threshold alongside RE_LAM=2100).
            tw = G * D / 4.0
            if fl._ty >= PHI_EXT_GATE * tw:
                return L * G * LAM_ALPHA
            return L * G
        if edges is not None:
            g_lo2, g_hi = edges
            if g_lo2 < g_hi:
                if Re < hi:
                    # continuous log-log blend between this segment's own
                    # laminar-x2 edge and its turbulent edge (no hard
                    # switch); C0 at hi by the shared-map re-anchor
                    beta = math.log(g_hi / g_lo2) / math.log(hi / lo)
                    return L * g_lo2 * (Re / lo) ** beta
            else:
                # inverted edges: the physical transition is the laminar-x2
                # / Dodge-Metzner crossing (TF-02R: resolved at the TRUE
                # crossing, at or above hi, so the branch switch is C0)
                re_cross = _seg_cross_re(fl, 'pipe', (D / 2.0,), n, K, ty,
                                         lo, hi, q)
                if Re <= re_cross:
                    return L * G * LAM_ALPHA
        n_eff = min(max(n, N_DM_MIN), N_DM_MAX)
        if _seg_n_in_dm_domain(n):
            f = _seg_fdm(_seg_remr(V, D, n, K, fl._rho), n_eff)
        else:
            # TF-02R scope 1: original SIx1 turbulent branch (parent line).
            f = 0.0791 / Re ** 0.25
        return L * 2.0 * f * fl._rho * V * V / D
    return L * G * LAM_ALPHA


def _seg_cross_re_scheduled(fl, dims, n, K, ty, lo, hi, q_hint):
    """v1.4.2 slot window fallback: the scheduled-laminar / Dodge-Metzner
    crossing root inside the window (inverted-edges case; TF-02: the
    turbulent side carries the same re-anchored DM map).  The laminar
    curve carries the live-state psi schedule of fric_slot_hb."""
    h, w = dims
    Dh = 2.0 * w * h / (w + h)

    def lam_s(re_):
        q_ = _seg_rate_for_re(fl, 'slot', dims, n, K, ty, re_, q_hint)
        G_ = _hb_G_cached(fl, 'slot', dims, q_, n, K, ty)
        tw_ = G_ * h / 2.0
        psi_ = (ty / tw_) if tw_ > 0.0 else float('inf')
        return G_ * (1.0 + (LAM_ALPHA - 1.0) * _s_win(psi_))

    def dm(re_):
        q_ = _seg_rate_for_re(fl, 'slot', dims, n, K, ty, re_, q_hint)
        V_ = q_ / (w * h)
        if not _seg_n_in_dm_domain(n):
            # TF-02R scope 1: original SIx1 Blasius map (parent line).
            f_ = 0.0791 / re_ ** 0.25
        else:
            n_eff = min(max(n, N_DM_MIN), N_DM_MAX)
            f_ = _seg_fdm(_seg_remr(V_, Dh, n, K, fl._rho), n_eff)
        return 2.0 * f_ * fl._rho * V_ * V_ / Dh

    flo = lam_s(lo) - dm(lo)
    if flo <= 0.0:
        return lo
    fhi = lam_s(hi) - dm(hi)
    if fhi >= 0.0:
        # TF-02R scope 2: inverted case resolved at the TRUE crossing at
        # or above hi (same construction as _seg_cross_re; C0, monotone).
        # Out-of-domain fluids keep the parent's exact fallback
        # (scope-1 policy: whole original branch).
        if not _seg_n_in_dm_domain(n):
            return hi
        a = hi
        b = hi
        found = False
        for _ in range(200):
            b *= 2.0
            if lam_s(b) - dm(b) < 0.0:
                found = True
                break
            a = b
        if not found:
            return hi
        for _ in range(60):
            m = 0.5 * (a + b)
            if lam_s(m) - dm(m) > 0.0:
                a = m
            else:
                b = m
        return 0.5 * (a + b)
    a, b = lo, hi
    for _ in range(60):
        m = 0.5 * (a + b)
        if lam_s(m) - dm(m) > 0.0:
            a = m
        else:
            b = m
    return 0.5 * (a + b)


def fric_slot_hb(q, L, Do, Di, fl: Fluid, lam_alpha=None):
    """Direct Herschel-Bulkley on the exact-area slot (w = pi(Do+Di)/2,
    h = (Do-Di)/2): exact laminar G, turbulent branch on
    Dh = 2wh/(w+h) (TF-02: Dodge-Metzner map on the Metzner-Reed
    Reynolds -- the single authorized change of this candidate; the
    blend upper edge is re-anchored to the same map; slot application
    inherits the engine's existing Blasius-on-Dh geometric convention,
    disclosed in the candidate header).
    v1.4.2 CONTINUOUS ANNULAR PSI-LAW: the laminar
    multiplier is 1 + (LAM_ALPHA-1)*s(psi) with psi = tau_y/tau_w the
    LOCAL dimensionless yield ratio of THIS segment (tau_w = G*h/2),
    scheduled per regime band by the v1.4.2 constants (s_lam / s_ext /
    s_win).  The string twin fric_pipe_hb keeps the frozen v1.3.1 law.
    Returns Pa."""
    if q <= 0.0 or L <= 0.0:
        return 0.0
    n, K, ty = fl.n_pl, fl.K_pl, fl._ty
    h = (Do - Di) / 2.0
    w = math.pi * (Do + Di) / 2.0
    V = q / (w * h)
    Dh = 2.0 * w * h / (w + h)
    G = _hb_G_cached(fl, 'slot', (h, w), q, n, K, ty)
    geff = 8.0 * V / Dh * (3.0 * n + 1.0) / (4.0 * n)
    mu_e2 = K * geff ** (n - 1.0) + ty / geff
    Re = fl._rho * V * Dh / mu_e2
    if Re > RE_LAM:
        # v1.4.2: the local dimensionless yield ratio of THIS segment
        tw = G * h / 2.0
        psi = (ty / tw) if tw > 0.0 else float('inf')
        lo, hi = _seg_window(n, True)
        if Re < lo:
            # extension zone: the v1.3.1 hard phi-gate becomes the same
            # C1 psi-ramp (psi -> 0: plain exact-HB; psi high: x2 family)
            return L * G * (1.0 + (LAM_ALPHA - 1.0) * _s_ext(psi))
        edges, lo, hi = _seg_edges(fl, 'slot', (h, w), n, K, ty, q)
        if edges is not None:
            g_lo_raw, g_hi = edges
            m_edge = 1.0 + (LAM_ALPHA - 1.0) * _s_win(psi)
            g_lo2 = g_lo_raw * m_edge
            if g_lo2 < g_hi:
                if Re < hi:
                    # continuous log-log blend between this segment's own
                    # scheduled laminar edge and its turbulent edge; C0 at
                    # hi by the shared-map re-anchor
                    beta = math.log(g_hi / g_lo2) / math.log(hi / lo)
                    return L * g_lo2 * (Re / lo) ** beta
            else:
                # inverted edges: the physical transition is the scheduled-
                # laminar / Dodge-Metzner crossing (TF-02R: resolved at the
                # TRUE crossing, at or above hi, so the switch is C0)
                re_cross = _seg_cross_re_scheduled(fl, (h, w), n, K, ty,
                                                   lo, hi, q)
                if Re <= re_cross:
                    return L * G * m_edge
        n_eff = min(max(n, N_DM_MIN), N_DM_MAX)
        if _seg_n_in_dm_domain(n):
            f = _seg_fdm(_seg_remr(V, Dh, n, K, fl._rho), n_eff)
        else:
            # TF-02R scope 1: original SIx1 turbulent branch (parent line).
            f = 0.0791 / Re ** 0.25
        return L * 2.0 * f * fl._rho * V * V / Dh
    # deep laminar (Re_gen <= RE_LAM): scheduled x2 family
    tw = G * h / 2.0
    psi = (ty / tw) if tw > 0.0 else float('inf')
    return L * G * (1.0 + (LAM_ALPHA - 1.0) * _s_lam(psi))


def fric_pipe(q, L, D, fl: Fluid, lam_alpha=1.0):
    if fl.frictionless_fluid:            # D7/D9: hydro-only fluid
        return 0.0
    if fl.mu_p_cp > 0.0:
        return fric_pipe_bingham(q, L, D, fl._rho, fl._mu, fl._ty)
    if fl.n_pl > 0.0 and fl.K_pl > 0.0:
        return fric_pipe_hb(q, L, D, fl, lam_alpha)  # v1.2.5: direct HB
    return fric_pipe_pl(q, L, D, fl._rho, fl.n_pl, fl.K_pl)


def fric_slot(q, L, Do, Di, fl: Fluid, lam_alpha=1.0):
    if fl.frictionless_fluid:            # D7/D9: hydro-only fluid
        return 0.0
    if fl.mu_p_cp > 0.0:
        return fric_slot_bingham(q, L, Do, Di, fl._rho, fl._mu, fl._ty)
    if fl.n_pl > 0.0 and fl.K_pl > 0.0:
        return fric_slot_hb(q, L, Do, Di, fl, lam_alpha)  # v1.2.5: HB
    if q <= 0.0 or L <= 0.0:
        return 0.0
    h = (Do - Di) / 2.0
    w = math.pi * (Do + Di) / 2.0
    V = q / (w * h)
    gw = (2.0 + 1.0 / fl.n_pl) * 2.0 * V / h        # slot wall shear rate
    tw = fl.K_pl * gw ** fl.n_pl
    return 2.0 * tw * L / h


def yield_pipe_pa(L, D, fl: Fluid):
    """Static yield resistance of a PIPE segment (D13): the pressure that
    must be exceeded before the segment moves at rest.  Pipe Bingham
    force balance: dP = 4 tau L / D (Placement bm9 with tau = tau_y)."""
    tau = fl._ty_tail
    if L <= 0.0 or D <= 0.0 or tau <= 0.0:
        return 0.0
    return 4.0 * tau * L / D


def yield_slot_pa(L, Do, Di, fl: Fluid):
    """Static yield resistance of an ANNULUS segment (D13): plane-slot
    force balance tau_w = h dP/(2L) > tau_y  =>  dP = 2 tau L / h."""
    tau = fl._ty_tail
    h = (Do - Di) / 2.0
    if L <= 0.0 or h <= 0.0 or tau <= 0.0:
        return 0.0
    return 2.0 * tau * L / h


def yield_resist_pa(col, v_or_chan, fluids, geom, is_pipe):
    """Total static yield resistance of a whole column (D13).
    During the post-job exchange every segment of BOTH columns must move,
    so both columns contribute.  v_or_chan: capacity scalar (bbl/m, single
    section, dims from geom) or a D11 Channel (per-section dims)."""
    Y = 0.0
    if isinstance(v_or_chan, Channel):
        cursor = 0.0
        for name, vol in col:
            for sec, v_seg in v_or_chan.spans(cursor, cursor + vol, True):
                L = v_seg / sec.cap_bbl_per_m
                if is_pipe:
                    Y += yield_pipe_pa(L, sec.dims[0] * 0.0254, fluids[name])
                else:
                    Y += yield_slot_pa(L, sec.dims[0] * 0.0254,
                                       sec.dims[1] * 0.0254, fluids[name])
            cursor += vol
        return Y
    v_per_m = v_or_chan
    for name, vol in col:
        L = vol / v_per_m
        if is_pipe:
            Y += yield_pipe_pa(L, geom.pipe_id_in * 0.0254, fluids[name])
        else:
            Y += yield_slot_pa(L, geom.hole_id_in * 0.0254,
                               geom.pipe_od_in * 0.0254, fluids[name])
    return Y


# ----------------------------------------------------------------------------
# Column helpers (Doc 17 §5 — bottom(TD) -> top ordering)
# ----------------------------------------------------------------------------
def _merge(col):
    out = []
    for name, vol in col:
        if out and out[-1][0] == name:
            out[-1][1] += vol
        else:
            out.append([name, vol])
    return out


def take_bottom(col, x):
    """Pop the bottom `x` bbl of a bottom(TD)->top column.  Returns the
    taken chunks in bottom->top take order (Doc 17 §5)."""
    got = []
    while x > 1e-12 and col:
        name, vol = col[0]
        take = min(vol, x)
        got.append([name, take])
        col[0][1] -= take
        x -= take
        if col[0][1] <= 1e-12:
            col.pop(0)
    return got


def put_bottom(col, chunks):
    """Place taken chunks at the column bottom PRESERVING the take order:
    the chunk that was deepest in the source stays deepest in the
    destination (P1 — the old sequential insert(0) reversed multi-chunk
    slugs within one dt step)."""
    col[0:0] = [[name, vol] for name, vol in chunks]
    col[:] = _merge(col)


def head_pa(col, v_or_chan, fluids):
    """Hydrostatic head of a bottom(TD)->top column (Pa).
    v_or_chan: capacity scalar (bbl/m) or a D11 Channel — with sections the
    volume/length conversion follows the per-section capacity."""
    if isinstance(v_or_chan, Channel):
        H = 0.0
        cursor = 0.0
        for name, vol in col:
            for sec, v_seg in v_or_chan.spans(cursor, cursor + vol, True):
                H += rho_si(fluids[name].rho_ppg) * G0 \
                    * (v_seg / sec.cap_bbl_per_m)
            cursor += vol
        return H
    v_per_m = v_or_chan
    H = 0.0
    for name, vol in col:
        H += rho_si(fluids[name].rho_ppg) * G0 * (vol / v_per_m)
    return H


def fric_col_pa(col, v_or_chan, q_m3s, fluids, geom, is_pipe,
                lam_alpha=1.0):
    """Column friction (Pa) — capacity scalar (legacy, geom dims) or a
    D11 Channel (per-section dims).  lam_alpha: v1.2.7 laminar
    calibration factor (gated upstream by lam_alpha_policy)."""
    if isinstance(v_or_chan, Channel):
        F = 0.0
        cursor = 0.0
        for name, vol in col:
            for sec, v_seg in v_or_chan.spans(cursor, cursor + vol, True):
                L = v_seg / sec.cap_bbl_per_m
                if is_pipe:
                    F += fric_pipe(q_m3s, L, sec.dims[0] * 0.0254,
                                   fluids[name], lam_alpha)
                else:
                    F += fric_slot(q_m3s, L, sec.dims[0] * 0.0254,
                                   sec.dims[1] * 0.0254, fluids[name],
                                   lam_alpha)
            cursor += vol
        return F
    v_per_m = v_or_chan
    F = 0.0
    for name, vol in col:
        L = vol / v_per_m
        if is_pipe:
            F += fric_pipe(q_m3s, L, geom.pipe_id_in * 0.0254, fluids[name],
                           lam_alpha)
        else:
            F += fric_slot(q_m3s, L, geom.hole_id_in * 0.0254,
                           geom.pipe_od_in * 0.0254, fluids[name], lam_alpha)
    return F


# ----------------------------------------------------------------------------
# Owner-decision input parsers (D10 / D14)
# ----------------------------------------------------------------------------
def parse_md_interval(md_value) -> Tuple[Optional[float], Optional[float]]:
    """Hardware 'MD (m)' cell -> (top_m, bottom_m).

    D10 (owner): an interval like '1200.0-2816.0' resolves to its BOTTOM
    (larger) end as the shoe/TD depth ("پایین دیگه ته چاه").  A single
    number means a point depth (top = bottom).  Returns (None, None) for
    blank cells — the caller decides whether that is fatal.
    """
    if md_value is None:
        return None, None
    text = str(md_value).strip()
    if not text:
        return None, None
    try:
        parts = [clean_number(p) for p in text.replace("،", "-").split("-")
                 if p.strip()]
    except ValueError:
        return None, None
    parts = [p for p in parts if p is not None]
    if any(not math.isfinite(p) for p in parts):
        return None, None        # ER01-F2: non-finite MD = unreadable cell
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], parts[0]
    return min(parts), max(parts)          # bottom = larger end (D10)


def parse_bhsp_psi(value) -> Optional[float]:
    """Phase II/III BHSP free text -> one pressure (psi).

    D14 (owner): a compound value such as '7300+1000' uses the LARGER
    number, not the smaller.  Numbers are read with the app-wide
    clean_number (Persian digits supported).  Returns None for blank/
    unreadable input; raises ChartInputError for text with no number.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if not math.isfinite(v):
            raise ChartInputError("BHSP must be a finite pressure (psi).")
        return v
    text = str(value).strip()
    if not text:
        return None
    tokens = [t for t in text.replace("،", "+").replace("-", "+").split("+")
              if t.strip()]
    nums = []
    for t in tokens:
        try:
            n = clean_number(t)
        except ValueError:
            continue
        if math.isfinite(n):
            nums.append(n)
    if not nums:
        raise ChartInputError(
            "BHSP %r is not readable: enter a number or a compound value "
            "such as '7300+1000' (the larger number is used)." % value)
    return max(nums)                       # D14: the larger xxxx


def rheology_from_lab(lab_payloads: Dict[str, Any],
                      dataset: str = RHEOLOGY_DATASET
                      ) -> Dict[str, Dict[str, Optional[float]]]:
    """Phase VII lab payloads -> per-slurry Bingham entries (D8/D13).

    Accepts the dict the host already builds as lab_payload_{slurry} (see
    phase_7_lab.py) or the bare rheology result of build_rheology().  Only
    the SELECTED + VALID Bingham rows are used; everything else is absent
    from the result so build_three_charts() can warn per fluid (nothing
    invented).

    dataset: owner decision D8 = 'bhct_down' (BHCT — Ramp-Down).
    Entry: {"pv_cp": float, "yp_lbf100ft2": float,
            "gel_10_min": float|None, "iod": float, "source": str}
    """
    out: Dict[str, Dict[str, Optional[float]]] = {}
    if not isinstance(lab_payloads, dict):
        return out
    for slurry, payload in lab_payloads.items():
        if not isinstance(payload, dict):
            continue
        rheo = payload.get("rheology", payload)      # bare result also accepted
        if not isinstance(rheo, dict) or dataset not in rheo:
            continue
        row = rheo[dataset]
        if not isinstance(row, dict) or not row.get("selected"):
            continue
        if not row.get("is_valid_bingham") or row.get("pv_cp") is None:
            continue
        gel = row.get("gel_10_min")
        try:
            gel_v = clean_number(gel) if gel not in (None, "", "-") else None
        except ValueError:
            gel_v = None
        out[str(slurry)] = {
            "pv_cp": float(row["pv_cp"]),
            "yp_lbf100ft2": float(row.get("ty_lbf_100ft2") or 0.0),
            "gel_10_min": gel_v,
            "iod": float(row["iod"]) if row.get("iod") is not None else None,
            "source": "phase7:%s" % dataset,
        }
    return out


def hydro_at_depth_pa(col, v_or_chan, fluids, depth_m, td_m=None):
    """Weight of the column ABOVE depth_m.  col is bottom(TD)->top.
    v_or_chan: capacity scalar (bbl/m; td_m required) or a D11 Channel
    (the channel supplies the volume-above-depth mapping)."""
    if isinstance(v_or_chan, Channel):
        chan = v_or_chan
        need = chan.volume_above(depth_m)
        H = 0.0
        toppos = 0.0
        for name, vol in reversed(col):
            take = min(vol, need)
            if take > 0:
                for sec, v_seg in chan.spans(toppos, toppos + take, False):
                    H += rho_si(fluids[name].rho_ppg) * G0 \
                        * (v_seg / sec.cap_bbl_per_m)
                toppos += take
                need -= take
            if need <= 1e-15:
                break
        return H
    v_per_m = v_or_chan
    above = 0.0
    remaining = (td_m - depth_m) * v_per_m
    H = 0.0
    for name, vol in col:
        if remaining >= vol:
            remaining -= vol
        else:
            above_vol = vol - remaining
            remaining = 0.0
            above += above_vol
    vol_acc = 0.0
    for name, vol in reversed(col):
        take = min(vol, max(above - vol_acc, 0.0))
        if take > 0:
            H += rho_si(fluids[name].rho_ppg) * G0 * (take / v_per_m)
            vol_acc += take
        if vol_acc >= above:
            break
    return H


def fric_above_pa(col, v_or_chan, fluids, geom, q_m3s, depth_m, td_m=None,
                  lam_alpha=1.0):
    """Annular friction of the segments ABOVE depth_m (flow continues up).
    v_or_chan: capacity scalar (legacy) or a D11 Channel.  lam_alpha:
    v1.2.7 laminar calibration factor (chart-2 dynamic series carries
    the same gated factor as the trajectory)."""
    if isinstance(v_or_chan, Channel):
        chan = v_or_chan
        need = chan.volume_above(depth_m)
        F = 0.0
        toppos = 0.0
        for name, vol in reversed(col):
            take = min(vol, need)
            if take > 0:
                for sec, v_seg in chan.spans(toppos, toppos + take, False):
                    L = v_seg / sec.cap_bbl_per_m
                    F += fric_slot(q_m3s, L, sec.dims[0] * 0.0254,
                                   sec.dims[1] * 0.0254, fluids[name],
                                   lam_alpha)
                toppos += take
                need -= take
            if need <= 1e-15:
                break
        return F
    v_per_m = v_or_chan
    remaining = (td_m - depth_m) * v_per_m
    F = 0.0
    for name, vol in col:
        if remaining >= vol:
            remaining -= vol
        else:
            above_vol = vol - remaining
            L = above_vol / v_per_m
            F += fric_slot(q_m3s, L, geom.hole_id_in * 0.0254,
                           geom.pipe_od_in * 0.0254, fluids[name], lam_alpha)
            remaining = 0.0
    return F


# ----------------------------------------------------------------------------
# The simulation (Doc 17 §5-6; PPC/shut-in branches removed per the user's
# 2026-10-10 decision: the job ends at the end of displacement)
# ----------------------------------------------------------------------------
# v1.3.0 (work order #25): lam_alpha_policy() and L_EFF_GUARD are
# REMOVED.  The frozen t=0 global guard could not generalize beyond its
# Batch-7 calibration domain (doc 24: DEHLORAN26-TB -38.45%, AZNS-138
# -18.18%).  The laminar correction now runs per segment at every time
# step inside fric_pipe_hb / fric_slot_hb (DYNAMIC SEGMENT-LEVEL
# CORRECTION) with the CEMCADE n-dependent regime window and a
# continuous log-log blend -- see the v1.3.0 block in the module header.


@dataclass
class JobDesign:
    geo: GeometrySpec
    fluids: Dict[str, Fluid]
    displacement_fluid: str = 'Displacement Fluid'
    placement: List[FluidStageSpec] = field(default_factory=list)
    back_pressure_psi: float = 0.0
    float_equipment: bool = False        # v1.2.4 (F3): one-way float collar
                                         # blocks ann -> pipe while pumping;
                                         # False = legacy open-head path
    surface_line_kpsi_at_8bpm: float = 0.010
    dt_min: float = 0.02
    tail_cap_min: float = 60.0
    frictionless: bool = False
    bhsp_psi: Optional[float] = None      # D14: shut-in anchor (None = no segment)
    shutin_ramp_min: float = 10.0         # D14: source anchor 244 -> 254 min


@dataclass
class SimResult:
    t: np.ndarray = None
    whp: np.ndarray = None          # kpsi  (UTUBE_WHP)
    pump: np.ndarray = None         # kpsi  (UTUBE_PUMP_WHP)
    hydro: np.ndarray = None        # kpsi  (HYDROSTATIC PRESSURE AT DEPTH)
    dyn: Optional[np.ndarray] = None    # kpsi (TOTAL PRESSURE AT DEPTH); None = frictionless mode
    q_in: np.ndarray = None         # bbl/min
    q_out: np.ndarray = None        # bbl/min
    t_atcp: Optional[float] = None      # first slurry at the annulus
                                        # bottom (shoe = track depth, P3)
    t_eod: float = None             # end of displacement
    t_marker: Optional[float] = None    # job-end marker (None: coincides with EOD)
    t_freefall_start: Optional[float] = None
    t_freefall_end: Optional[float] = None
    final_hydro_kpsi: float = None
    hydro0_kpsi: float = None
    t_shutin: Optional[float] = None    # D14: start of the BHSP shut-in segment
    whp_final_psi: Optional[float] = None   # D14: final wellhead pressure (psi)
    bottom_shutin_psi: Optional[float] = None   # D14: BHSP used (psi)
    diag: dict = field(default_factory=dict)


def _er01_validate_job(job):
    """ER01-F2 engine-entry guard: a directly-constructed JobDesign with
    non-finite or physically disallowed scalars fails closed before any
    physics.  (The build_three_charts path is already guarded at its own
    seams; this covers the direct API.)  Documented zeros stay legal:
    volume 0 = skip, tail_cap_min 0 = disable, tau_y/n/K 0 = dispatch
    rules, YP 0 = allowed."""
    if not isinstance(job.geo, GeometrySpec):
        raise ChartInputError("JobDesign.geo must be a GeometrySpec.")
    for name, fl in (job.fluids or {}).items():
        if not isinstance(fl, Fluid):
            raise ChartInputError("fluids[%r] must be a Fluid." % name)
        _er01_finite(fl.rho_ppg, "fluids[%s].rho_ppg" % name)
        if fl.rho_ppg <= 0.0:
            raise ChartInputError("fluids[%s].rho_ppg must be > 0." % name)
        for attr in ("mu_p_cp", "tau_y", "n_pl", "K_pl", "gel_pa"):
            v = _er01_finite(getattr(fl, attr), "fluids[%s].%s"
                             % (name, attr))
            if v < 0.0:
                raise ChartInputError(
                    "fluids[%s].%s must be >= 0; got %r." % (name, attr, v))
    for i, st in enumerate(job.placement):
        _er01_finite(st.volume_bbl, "placement[%d].volume_bbl" % i)
        _er01_finite(st.rate_bpm, "placement[%d].rate_bpm" % i)
        _er01_finite(st.density_pcf, "placement[%d].density_pcf" % i)
        if st.volume_bbl < 0.0:
            raise ChartInputError(
                "placement[%d].volume_bbl must be >= 0." % i)
        if st.volume_bbl > 0.0 and st.rate_bpm <= 0.0:
            raise ChartInputError(
                "placement[%d] pumps %g bbl at invalid rate %r — a pumped "
                "stage needs rate > 0." % (i, st.volume_bbl, st.rate_bpm))
        if st.density_pcf <= 0.0:
            raise ChartInputError(
                "placement[%d].density_pcf must be > 0." % i)
    _er01_finite(job.back_pressure_psi, "back_pressure_psi")
    _er01_finite(job.surface_line_kpsi_at_8bpm,
                 "surface_line_kpsi_at_8bpm")
    _er01_finite(job.dt_min, "dt_min")
    if job.dt_min <= 0.0:
        raise ChartInputError(
            "dt_min must be > 0 (a non-positive time step cannot "
            "integrate the schedule).")
    _er01_finite(job.tail_cap_min, "tail_cap_min")
    if job.tail_cap_min < 0.0:
        raise ChartInputError(
            "tail_cap_min must be >= 0 (0 = documented disable).")
    _er01_finite(job.shutin_ramp_min, "shutin_ramp_min")
    if job.shutin_ramp_min < 0.0:
        raise ChartInputError("shutin_ramp_min must be >= 0.")
    if job.bhsp_psi is not None:
        _er01_finite(job.bhsp_psi, "bhsp_psi")
        if job.bhsp_psi < 0.0:
            raise ChartInputError("bhsp_psi must be >= 0.")
    return job


def simulate(job: JobDesign) -> SimResult:
    _er01_validate_job(job)            # ER01-F2: fail closed before physics
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
        if st.volume_bbl == 0.0:  # documented skip; no zero-duration event
            continue
        end = t0 + st.volume_bbl / st.rate_bpm
        if not math.isfinite(end) or end <= t0:
            raise ChartInputError("Stage duration is not representable.")
        blocks.append([t0, end, st.rate_bpm, st.fluid_type])
        t0 = end
    t_eod = t0
    t_end = t_eod + job.tail_cap_min   # equalization tail (breaks at balance)
    if not math.isfinite(t_end):
        raise ChartInputError("Tail endpoint is not finite.")

    def rate_at(t):
        for a, b, r, f in blocks:
            if a <= t < b and t < t_eod:
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
        return head_pa(pipe, chan_pipe, fluids), head_pa(ann, chan_ann, fluids)

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

    # Observation-only native tokens; never consulted by simulation decisions.
    port_rows = []
    injected_tokens = []
    mouth_tokens = []
    head_tokens = []

    def port_snapshot(when):
        return (when, tuple((n, v) for n, v in pipe),
                tuple((n, v) for n, v in ann), gap)

    initial_ports = port_snapshot(0.0)
    pump_end_ports = initial_ports if t_eod == 0.0 else None

    def put_top(col, name, vol):
        if col is pipe:
            injected_tokens.append((name, vol))
        if col and col[-1][0] == name:
            col[-1][1] += vol
        else:
            col.append([name, vol])

    def drop_top(col, x):
        while x > 1e-12 and col:
            name, vol = col[-1]
            take = min(vol, x)
            # Exclude the hypothetical gap_star probe (a copied column).
            if col is ann:
                mouth_tokens.append((name, take))
            elif col is pipe:
                head_tokens.append((name, take))
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

    # Gate 4B: interval-start sample labels are retained from frozen ER03.
    # Every transfer/slew/ledger uses the same actual interval; the terminal
    # observation has duration zero and cannot inject or exchange fluid.
    event_intervals = []
    t = 0.0
    while t <= t_end:
        boundary = next((b for a, b, r, f in blocks if b > t), t_end)
        step_end = min(t + dt, boundary, t_end)
        # Subtraction may round a nominal dt upward; choose the preceding
        # representable endpoint so the actual duration never exceeds dt.
        if step_end - t > dt:
            step_end = math.nextafter(step_end, t)
        step_dt = step_end - t
        terminal = t == t_end
        if not terminal and step_dt <= 0.0:
            raise ChartInputError("Integration interval is not representable.")
        r_in, fl_in = rate_at(t)
        injected_tokens.clear(); mouth_tokens.clear(); head_tokens.clear()
        tail_active = False
        backflow = 0.0            # reverse flow leaving at the pipe TOP
        rev_draw = 0.0            # v1.2.3: reverse draw ann -> pipe (bbl/min)
        q_mouth = None            # v1.2.3: annulus-top returns rate (bbl/min)
        branch = 'normal'
        if t < t_eod:
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
                    _kappa = ((Hp - head_pa(_probe, chan_pipe, fluids))
                              / _eps)
                    if _kappa > 0.0:
                        _gap_star = max(gap + _drive / _kappa, 0.0)
                if q_ff > r_in + 1e-9:
                    branch = 'freefall'
                    exc = q_ff - r_in
                    # DOC55 (F4): the void may not step past equilibrium
                    _dg = min(exc * step_dt, max(_gap_star - gap, 0.0))
                    q_ff = r_in + _dg / step_dt
                    # free fall: gap at the pipe top, WHP -> 0 (documented)
                    q_net, q_out, whp = q_ff, q_ff, 0.0
                    gap += _dg
                    q_ff_state[0] = _dg / step_dt
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
                    fill = min(r_in - q_ff, gap / step_dt,
                               max(gap - _gap_star, 0.0) / step_dt)
                    if fill < 0.0:
                        fill = 0.0
                    gap -= fill * step_dt
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
                    fill = min(r_in, gap / step_dt)
                    gap -= fill * step_dt
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
                q_rev_state[0] = max(0.0, q_rev_state[0] - SLEW_Q * step_dt)
            else:                                     # legacy open-head path
                q_rev = solve_reverse() if static < -1e-6 else 0.0
                q_rev = min(max(q_rev,
                                q_rev_state[0] - SLEW_Q * step_dt),
                            q_rev_state[0] + SLEW_Q * step_dt)
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
                    fill = min(q_rev, gap / step_dt)          # bbl/min
                    gap -= fill * step_dt
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
            x = q_net * step_dt
            if x > 0:
                chunks = take_bottom(pipe, x)
                put_bottom(ann, chunks)
            if rev_draw > 0:
                # v1.2.3: exchange draw enters the pipe at the shoe
                put_bottom(pipe, take_bottom(ann, rev_draw * step_dt))
            if r_in > 0:
                put_top(pipe, fl_in, r_in * step_dt)
            if backflow > 0:
                drop_top(pipe, backflow * step_dt)   # head backflow (free exchange)
            if q_mouth is None:
                q_mouth = q_out
            if q_mouth > 0:
                # returns at the annulus top only (v1.2.3: the head outflow
                # is booked in Q Out but does NOT leave through the mouth);
                # slurry leaving = over-displacement (reported in diag)
                drop_top(ann, q_mouth * step_dt)
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
            elif t >= t_end:
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
                q_ff = min(max(q_ff, q_ff_state[0] - SLEW_Q * step_dt),
                           q_ff_state[0] + SLEW_Q * step_dt)
                q_ff_state[0] = max(q_ff, 0.0)
                q_net = 0.0
                q_out = q_ff
                whp = 0.0
                gap += q_ff * step_dt
                x = q_ff * step_dt
                if x > 0:
                    put_bottom(ann, take_bottom(pipe, x))
                    drop_top(ann, x)
            else:
                branch = 'tail_rev'
                tail_active = True
                q_rev = solve_reverse(yield_pa=Y)
                q_rev = min(max(q_rev, q_rev_state[0] - SLEW_Q * step_dt),
                            q_rev_state[0] + SLEW_Q * step_dt)
                q_rev_state[0] = max(q_rev, 0.0)
                q_net = 0.0
                q_out = 0.0
                whp = 0.0
                x = q_rev * step_dt
                if x > 0:
                    put_bottom(pipe, take_bottom(ann, x))
                    if gap > 1e-9:
                        closed = min(gap, x)
                        gap -= closed
                        x -= closed
                    if x > 0:      # pipe full: overflows at the head
                        drop_top(pipe, x)
                        head_overflow[0] += x
                        q_out = x / step_dt   # v1.2.3 (V3): overflow is BOOKED

        # --- record -----------------------------------------------------------
        Hp, Ha = state_heads()
        hydro = (BP + hydro_at_depth_pa(ann, chan_ann, fluids,
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
        event_intervals.append((t, step_end, step_dt, fl_in, r_in, q_out, branch))
        CUM[0] += r_in * step_dt
        CUM[1] += q_out * step_dt
        _dacc(BR, branch, step_dt)
        _dacc(LEAK, branch, (Cp_a + Ca_a - _pc[0] - _pc[1])
              - (r_in - q_out) * step_dt)
        _dacc(DRES, branch, (Cp_a + gap - V_pipe0)
              - (_pc[0] + _pc[2] - V_pipe0))
        _pc[:] = [Cp_a, Ca_a, gap]
        port_rows.append((t, step_end, step_dt, branch, fl_in,
                          tuple(injected_tokens),
                          (('ANNULAR_MOUTH', tuple(mouth_tokens)),
                           ('PIPE_HEAD', tuple(head_tokens))), gap))
        if step_end == t_eod and pump_end_ports is None:
            pump_end_ports = port_snapshot(t_eod)
        # events: first slurry arriving at the annulus bottom (track depth)
        if t_slurry is None and ann and ann[0][0] in slurry_set:
            t_slurry = t
        if terminal:
            break
        t = step_end
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
    res_diag['event_intervals'] = tuple(event_intervals)
    res_diag['native_port_inventory_v1'] = (
        'CFW128_NATIVE_PORT_INVENTORY_V1', initial_ports, tuple(port_rows),
        pump_end_ports, port_snapshot(event_intervals[-1][1]))
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


def _fmt_for_step(minor: float) -> str:
    if minor >= 1.0 - 1e-9:
        return '%g'
    if minor >= 0.1 - 1e-9:
        return '%.1f'
    return '%.2f'


def autoscale_x(t_end: float) -> Tuple[float, float, float, float]:
    """0 .. ceil(1.06*t_end to the MAJOR step) with step >= 1.06*t_end/18.

    On the source page: data ends 254 -> axis 270 with 15-min minors and
    30-min majors (254*1.06 = 269.2 -> 270 = 18 minors = 9 majors).
    major = 2x minor (source rule).

    D4 fix (DOC 51R v2): the headroom is snapped OUT to the MAJOR grid, so
    every axis extent lands on both the minor AND the major tick ladder.
    v1.4.3 snapped to the minor grid only, which left orphan majors (e.g.
    t_end=3 -> (0,5,5,10): the only major inside the plot was 0 and no
    minor gridline fit; t_end=100 -> 110 with majors 0,20,...,100 and a
    dangling 10-min tail).  Ladder extended downward for short jobs; the
    demo and reference results are unchanged.
    """
    target = max(t_end, 1.0) * 1.06 / 18.0
    step = next((c for c in X_CANDIDATES if c >= target - 1e-12), None)
    if step is None:
        step = 240.0 * math.ceil(target / 240.0)
    major = 2.0 * step
    x_max = math.ceil((max(t_end, 1.0) * 1.06 - 1e-9) / major) * major
    return 0.0, x_max, step, major


def autoscale_y(lo: float, hi: float, zero_based: bool,
                pad: float = 0.08) -> Tuple[float, float, float, float, str]:
    """(ymin, ymax, minor, major, fmt) — window snapped to the MAJOR grid.

    minor = smallest candidate >= span/8;  major = 2x minor (source rule);
    margins ~8% of span each side, snapped OUT to the major grid so the
    tick labels land exactly on ymin/ymax (source: 0..1.2, 5.6..7.2, 4..10).
    Chart 1 is zero-based (source ymin=0); charts 2/3 use the floor rule
    (source chart 3 ymin=4.0 with data min 5.0).
    """
    lo = float(min(lo, hi))
    hi = float(max(lo + 1e-12, hi))
    span = hi - lo
    if span < 1e-9:
        span = max(abs(hi) * 0.1, 0.5)
        lo, hi = hi - span, hi
    minor = next((c for c in Y_CANDIDATES if c >= span / 8.0), span)
    major = 2.0 * minor
    if zero_based:
        ymin = 0.0
        ymax = math.ceil((hi + pad * span) / major - 1e-9) * major
    else:
        ymin = math.floor((lo - pad * span) / major + 1e-9) * major
        ymax = math.ceil((hi + pad * span) / major - 1e-9) * major
        if ymin < 0.0 and lo >= 0.0:
            ymin = 0.0
    return ymin, ymax, minor, major, _fmt_for_step(minor)


# ----------------------------------------------------------------------------
# Spec + renderer (Doc 16 grammar, byte-identical style locks)
# ----------------------------------------------------------------------------
@dataclass
class JobChartsSpec:
    """Renderer input: series in kpsi / bbl/min / min.  A series set to
    None is LEGEND-ONLY (declared, nothing drawn) — the state of the
    Acquired/Back channels in the source report instance and of Dynamic
    in the frictionless diagnostic mode."""
    calc_cem_hp: Tuple[np.ndarray, np.ndarray] = None
    calc_pump_press: Tuple[np.ndarray, np.ndarray] = None
    acquired_pressure: Optional[Tuple[np.ndarray, np.ndarray]] = None
    back_pressure: Optional[Tuple[np.ndarray, np.ndarray]] = None
    hydrostatic: Tuple[np.ndarray, np.ndarray] = None
    dynamic: Optional[Tuple[np.ndarray, np.ndarray]] = None
    q_in: Tuple[np.ndarray, np.ndarray] = None
    q_out: Tuple[np.ndarray, np.ndarray] = None
    acquired_q_in: Optional[Tuple[np.ndarray, np.ndarray]] = None
    acquired_q_out: Optional[Tuple[np.ndarray, np.ndarray]] = None
    #: DOC 52 (B): demo-number defaults REMOVED from the renderer schema.
    #: A real chart MUST carry the current well's depth (finite, > 0) and
    #: current-job-derived axes; render_three_charts fails closed otherwise
    #: and never substitutes an example value (no 3293 m / 270 min path).
    #: Demo/test fixtures pass explicit values (fenced demo_geometry()).
    depth_m: Optional[float] = None
    depth_unit: str = 'm'
    event_times: Tuple[float, ...] = ()
    marker_time: Optional[float] = None
    axis_x: Optional[Tuple[float, float, float, float]] = None
    axis_y1: Tuple[float, float, float, float, str] = None
    axis_y2: Tuple[float, float, float, float, str] = None
    axis_y3: Tuple[float, float, float, float, str] = None

    @property
    def title_depth(self) -> str:
        # DLL byte template: "Depth =%6.f %s"  (mtks_edt.dll)
        return 'Depth =%6.0f %s' % (self.depth_m, self.depth_unit)

    @property
    def title_fluids(self) -> str:
        # DLL byte template: "Fluids at %6.f %s" (mtks_edt.dll)
        return 'Fluids at %6.0f %s' % (self.depth_m, self.depth_unit)


def _grid_and_ticks(ax, lo, hi, minor, major, fmt, rotate_y=True):
    """Olectra grammar: gridlines on minors, tick marks + labels on majors.
    DOC 50 presentation: y numerals rotated 90 deg, asymmetric fonts."""
    n_y = int(round((hi - lo) / minor))
    for k in range(1, n_y):
        ax.axhline(lo + k * minor, color=GRID_GRAY, lw=1.0, zorder=1)
    n_ym = int(round((hi - lo) / major))
    ymaj = [lo + k * major for k in range(n_ym + 1)]
    ax.set_yticks(ymaj)
    ax.set_yticklabels([(fmt % round(v, 6)) for v in ymaj],
                       rotation=90 if rotate_y else 0,
                       fontsize=T_TICK_Y)
    ax.tick_params(direction='out', length=3.5, width=0.8,
                   color=TICK_COLOR,
                   labelcolor=TEXT_COLOR, colors=TICK_COLOR)
    ax.tick_params(which='minor', bottom=False, left=False)


def _grid_x(ax, xlo, xhi, xminor, xmajor):
    n_x = int(round((xhi - xlo) / xminor))
    for k in range(1, n_x):
        ax.axvline(xlo + k * xminor, color=GRID_GRAY, lw=1.0, zorder=1)
    n_xm = int(round((xhi - xlo) / xmajor))
    xmaj = [xlo + k * xmajor for k in range(n_xm + 1)]
    ax.set_xticks(xmaj)
    ax.set_xticklabels(['%g' % v for v in xmaj], fontsize=T_TICK_X)


def _style_panel(ax, xlo, xhi):
    ax.set_facecolor(PANEL_BG)
    for side in ('left', 'right', 'top', 'bottom'):
        ax.spines[side].set_color(FRAME)
        ax.spines[side].set_linewidth(1.1)
    ax.set_xlim(xlo, xhi)
    ax.set_xlabel(X_LABEL, fontsize=T_AXIS_X, color=TEXT_COLOR, labelpad=6)


def _legend(ax, handles, labels):
    leg = ax.legend(handles, labels, loc='upper left', frameon=True,
                    fontsize=T_LEGEND, labelcolor=TEXT_COLOR,
                    framealpha=1.0, fancybox=False,
                    edgecolor=LEGEND_EDGE, facecolor=LEGEND_BG,
                    borderpad=0.45, labelspacing=0.45,
                    handlelength=2.2, handletextpad=0.55,
                    handleheight=1.4, borderaxespad=0.8)
    leg.get_frame().set_linewidth(1.0)
    leg.set_zorder(20)
    return leg


def _event_lines(ax, spec):
    # drawn OVER the series (the source page shows full-height overlay lines)
    for tv in spec.event_times:
        ax.axvline(tv, color=EVENT_GREEN, lw=LW_EVENT, zorder=4.5)
    if spec.marker_time is not None:
        ax.axvline(spec.marker_time, color=MARKER_GRAY, lw=LW_EVENT, zorder=4.5)


def _xy(series):
    return np.asarray(series[0], float), np.asarray(series[1], float)


def _psi(axis):
    """engine autoscale tuple in kpsi -> presentation tuple in psi (D2).

    The single kpsi->psi conversion point of the direct-psi presentation:
    axis limits/steps are converted here; the series are converted exactly
    once at their plot sites in render_three_charts.  JobChartsSpec keeps
    canonical kpsi values (contract preserved).
    """
    lo, hi, minor, major = axis[:4]
    fmt = axis[4] if len(axis) > 4 else '%g'
    f = 1000.0
    r = lambda v: round(v * f, 6)
    return r(lo), r(hi), r(minor), r(major), '%g'


def _xy_psi(series):
    """D2: kpsi series -> plot coordinates in psi.  EXACTLY ONE conversion,
    applied at the plot site; the canonical JobChartsSpec arrays stay kpsi."""
    x, y = _xy(series)
    return x, y * 1000.0


def _finite_series(series, name):
    """DOC 52 (B/D): a present series must be non-empty, 1-D, pairwise
    finite and aligned; otherwise the chart is refused (fail-closed) —
    a user-visible engineering chart must never carry a silent hole."""
    x = np.asarray(series[0], float)
    y = np.asarray(series[1], float)
    if x.ndim != 1 or y.ndim != 1 or x.size == 0 or y.size == 0:
        raise ChartInputError(
            '%s: series arrays must be non-empty 1-D numeric arrays '
            '(got x.shape=%r, y.shape=%r).'
            % (name, x.shape, y.shape))
    if x.size != y.size:
        raise ChartInputError(
            '%s: x/y length mismatch (%d vs %d).' % (name, x.size, y.size))
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ChartInputError(
            '%s: series contains non-finite (NaN/Inf) samples — refusing to '
            'present an untrustworthy channel; clean the input series first '
            '(DOC 52 fail-closed, no silent data hole).' % name)
    return x, y


def _validate_display_inputs(spec):
    """DOC 52 (B): fail-closed validation of the renderer display inputs.

    Runs BEFORE any drawing.  A real chart must carry (1) the current
    well's depth — finite and positive, taken from the job geometry —
    (2) current-job-derived finite axes whose spans are whole multiples of
    their minor/major steps (the tick-label grammar), and (3) finite,
    aligned series.  Missing or invalid inputs raise ChartInputError with
    an actionable message; the renderer NEVER substitutes an example value
    (no 3293 m depth, no 270 min axis, no fabricated fallback).
    """
    if spec.depth_m is None:
        raise ChartInputError(
            'JobChartsSpec.depth_m is required: pass the CURRENT well depth '
            'from the job geometry (the renderer no longer carries a demo '
            'default — DOC 52 B).')
    depth = float(spec.depth_m)
    if not math.isfinite(depth) or depth <= 0.0:
        raise ChartInputError(
            'JobChartsSpec.depth_m must be finite and positive for a real '
            'chart, got %r.' % (spec.depth_m,))
    axes = (('axis_x', spec.axis_x), ('axis_y1', spec.axis_y1),
            ('axis_y2', spec.axis_y2), ('axis_y3', spec.axis_y3))
    for ax_name, ax_val in axes:
        if ax_val is None:
            raise ChartInputError(
                '%s is required: axes must be derived from the current job '
                '(autoscale_x/autoscale_y or caller-computed) — the renderer '
                'no longer carries demo axis defaults (DOC 52 B).' % ax_name)
        vals = tuple(float(v) for v in tuple(ax_val)[:4])
        if len(vals) != 4 or not all(math.isfinite(v) for v in vals):
            raise ChartInputError(
                '%s must be 4 finite numbers (lo, hi, minor, major), got %r.'
                % (ax_name, ax_val))
        lo, hi, minor, major = vals
        span = hi - lo
        if not span > 0.0 or minor <= 0.0 or major < minor:
            raise ChartInputError(
                '%s must satisfy hi > lo and 0 < minor <= major, got '
                '(lo=%r, hi=%r, minor=%r, major=%r).'
                % (ax_name, lo, hi, minor, major))
        for step, kind in ((minor, 'minor'), (major, 'major')):
            k = span / step
            if abs(k - round(k)) > 1e-6:
                raise ChartInputError(
                    '%s span %r is not a whole multiple of its %s step %r — '
                    'tick labels would not land on the axis ends; re-derive '
                    'the axis with autoscale rules.' % (ax_name, span, kind,
                                                        step))
    for name in ('calc_cem_hp', 'calc_pump_press', 'hydrostatic', 'q_in',
                 'q_out'):
        series = getattr(spec, name)
        if series is None:
            raise ChartInputError(
                '%s is mandatory on a real chart (legend-only is reserved '
                'for the optional Acquired/Back/Dynamic channels).' % name)
        _finite_series(series, name)
    for name in ('acquired_pressure', 'back_pressure', 'dynamic',
                 'acquired_q_in', 'acquired_q_out'):
        series = getattr(spec, name)
        if series is not None:
            _finite_series(series, name)
    times = tuple(spec.event_times) + (
        () if spec.marker_time is None else (float(spec.marker_time),))
    for tv in times:
        if not math.isfinite(tv):
            raise ChartInputError(
                'event/marker times must be finite, got %r.' % (tv,))


def _union_extent(series_list):
    """(lo, hi) over the y-arrays of the PRESENT series (one unit per
    panel); None when nothing is present."""
    los, his = [], []
    for s in series_list:
        if s is None:
            continue
        y = np.asarray(s[1], float)
        if y.size:
            los.append(float(y.min()))
            his.append(float(y.max()))
    if not los:
        return None
    return min(los), max(his)


def _visible_extent(series_list, xlo, xhi):
    """DOC 52 R1 (V10): (lo, hi) over the y-values of the PRESENT series
    that are actually VISIBLE in the [xlo, xhi] time window.

    Measurement basis, per panel, per present series:
      * every finite sample with xlo - 1e-9 <= x <= xhi + 1e-9 (the same
        1e-9 edge tolerance as the out-of-window-events audit), and
      * for each segment whose x-span strictly crosses a window edge, the
        linearly interpolated y at that edge — so a boundary-crossing
        segment contributes its true visible extremum (no last-segment
        clipping) without resampling the curve.

    Purely a MEASUREMENT: no series, array or sample is mutated,
    reordered, resampled or re-derived; hydraulic arrays are untouched.
    A wholly out-of-window series contributes nothing.  Returns None when
    nothing is visible in the window.
    """
    los, his = [], []
    for s in series_list:
        if s is None:
            continue
        x = np.asarray(s[0], float)
        y = np.asarray(s[1], float)
        if x.size == 0 or y.size != x.size:
            continue
        eps = 1e-9
        m = (x >= xlo - eps) & (x <= xhi + eps) & np.isfinite(y)
        if m.any():
            los.append(float(y[m].min()))
            his.append(float(y[m].max()))
        if x.size >= 2:
            xa, xb = x[:-1], x[1:]
            for edge in (float(xlo), float(xhi)):
                crosses = ((xa < edge - eps) & (xb > edge + eps)) | \
                          ((xb < edge - eps) & (xa > edge + eps))
                j = np.nonzero(crosses & np.isfinite(y[:-1])
                               & np.isfinite(y[1:]) & (xb != xa))[0]
                if j.size:
                    t = (edge - xa[j]) / (xb[j] - xa[j])
                    yb = y[j] + t * (y[j + 1] - y[j])
                    los.append(float(yb.min()))
                    his.append(float(yb.max()))
    if not los:
        return None
    return min(los), max(his)


def _display_axis(axis4, series_list, zero_based, window=None):
    """DOC 52 (D): deterministic, generic, DISPLAY-ONLY panel-axis
    recomputation.

    The panel axis is caller-owned — but a user-visible engineering chart
    must never silently crop a present, validated series (audit-only is not
    a remedy).  When any present series extends beyond the incoming axis by
    more than a 1e-6*span tolerance (float dust never triggers), the axis
    is re-derived with the SAME autoscale_y grammar over the union extent
    of everything that will be drawn on that panel.  Chart 1 keeps its
    approved zero-based grammar unless the union is genuinely negative.
    Same inputs always yield the same axis.  Returns (axis4, changed).

    DOC 52 R1 (V10): with `window=(xlo, xhi)` — the renderer passes the
    visible axis_x span — that extent is the VISIBLE extent
    (`_visible_extent`): in-window samples plus the interpolated values of
    segments crossing a window edge.  A curve lying entirely outside the
    visible pumping time can no longer inflate the presented Y scale (its
    time-window exclusion is disclosed in the axis audit, distinct from
    Y-clipping).  `window=None` keeps the historical whole-array extent
    for direct helper use; the renderer always passes the real window.
    """
    if window is None:
        ext = _union_extent(series_list)
    else:
        ext = _visible_extent(series_list, float(window[0]),
                              float(window[1]))
    if ext is None:
        return axis4, False
    lo, hi = float(axis4[0]), float(axis4[1])
    tol = 1e-6 * max(hi - lo, 1e-12)
    if ext[0] >= lo - tol and ext[1] <= hi + tol:
        return axis4, False
    zb = bool(zero_based and ext[0] >= -tol)
    return autoscale_y(ext[0], ext[1], zero_based=zb), True


def render_three_charts(spec: JobChartsSpec):
    """Build the three-chart figure and RETURN it (st.pyplot-ready).

    DOC 51 presentation: AZNS-179 page-4 grammar (DOC 50, byte-accepted) on
    the preserved 10x12 in / 3-panel engine canvas.
    D2: every pressure series is converted kpsi -> psi EXACTLY ONCE here,
    at the plot site; JobChartsSpec keeps canonical kpsi.  Optional
    Back/Acquired channels draw at psi scale when a caller feeds them;
    absent channels stay legend-only.
    DOC 52 (B): fail-closed display-input validation runs BEFORE any
    drawing — missing depth/axes or non-finite series raise ChartInputError
    (never an example-value chart).
    DOC 52 (D): a present series extending beyond its panel axis triggers a
    deterministic display-only axis recomputation (same autoscale grammar,
    union extent of the panel) so nothing visible is silently cropped; the
    change is disclosed in fig._doc51r_axis_audit ('recomputed' +
    'original_lim' + 'above_axis', and 'out_of_window_events' at figure
    level).  Healthy caller axes are byte-identical no-ops.
    DOC 52 R1 (V10): that extent is measured over the VISIBLE axis_x
    window (in-window samples + interpolated boundary-crossing values), so
    a series lying entirely outside the pumping window can no longer
    distort the presented Y scale; its exclusion is disclosed per panel as
    'out_of_window_samples' (distinct from Y-clipping/recomputation).
    D1: the font policy is applied per figure via rc_context — process
    state is untouched on success AND on exception.
    """
    _validate_display_inputs(spec)
    with plt.rc_context(dict(_FONT_RC)):
        fig = plt.figure(figsize=(10.0, 12.0), constrained_layout=True)
        fig.get_layout_engine().set(h_pad=0.02, hspace=0.045)
        gs = fig.add_gridspec(3, 1)
        axes = [fig.add_subplot(gs[i, 0]) for i in range(3)]
        xlo, xhi, xminor, xmajor = spec.axis_x
        y1_caller = tuple(float(v) for v in tuple(spec.axis_y1)[:4])
        y2_caller = tuple(float(v) for v in tuple(spec.axis_y2)[:4])
        y3_caller = tuple(float(v) for v in tuple(spec.axis_y3)[:4])

        # ---------------- Chart 1: well head pressures (NO title: Q1
        # resolved — the DLL CPlotWellHeadPressure class has no title
        # template) ------------------------------------------------------
        ax = axes[0]
        _style_panel(ax, xlo, xhi)
        _grid_x(ax, xlo, xhi, xminor, xmajor)
        # DOC 52 (D): include every PRESENT pressure channel in the visible
        # range (display-only recompute; caller axis kept when it already
        # contains everything).  DOC 52 R1: the extent is measured over the
        # VISIBLE axis_x window only — an out-of-window optional channel
        # cannot inflate the presented Y scale.
        y1_raw, y1_changed = _display_axis(
            y1_caller,
            (spec.back_pressure, spec.acquired_pressure,
             spec.calc_pump_press, spec.calc_cem_hp),
            zero_based=True, window=(xlo, xhi))
        y1 = _psi(y1_raw)
        _grid_and_ticks(ax, y1[0], y1[1], y1[2], y1[3], y1[4], rotate_y=True)
        ax.set_ylim(y1[0], y1[1])
        ax.set_ylabel(YLABEL_C1, fontsize=T_AXIS_Y, color=TEXT_COLOR,
                      labelpad=8)
        handles, labels = [], []
        if spec.back_pressure is not None:
            h, = ax.plot(*_xy_psi(spec.back_pressure),
                         color=RED, lw=LW_THICK, zorder=2.6,
                         solid_capstyle='round')
        else:
            h = Line2D([], [], color=RED, lw=LW_THICK)
        handles.append(h); labels.append('Back Pressure')
        if spec.acquired_pressure is not None:
            h, = ax.plot(*_xy_psi(spec.acquired_pressure),
                         color=RED, lw=LW_THIN, zorder=2.7)
        else:
            h = Line2D([], [], color=RED, lw=LW_THIN)
        handles.append(h); labels.append('Acquired Pressure')
        h, = ax.plot(*_xy_psi(spec.calc_pump_press),
                     color=BLUE, lw=LW_THICK, zorder=3,
                     solid_capstyle='round')
        handles.append(h); labels.append('Calc. Pump Press.')
        h, = ax.plot(*_xy_psi(spec.calc_cem_hp),
                     color=GREEN, lw=LW_THICK, zorder=4,
                     linestyle=CEMHP_DASH, dash_capstyle='round')
        handles.append(h); labels.append('Calc. CemHP')
        order = [3, 1, 0, 2]
        _legend(ax, [handles[i] for i in order], [labels[i] for i in order])

        # ---------------- Chart 2: annular pressure at depth ----------------
        ax = axes[1]
        _style_panel(ax, xlo, xhi)
        _grid_x(ax, xlo, xhi, xminor, xmajor)
        y2_raw, y2_changed = _display_axis(
            y2_caller, (spec.hydrostatic, spec.dynamic), zero_based=False,
            window=(xlo, xhi))
        y2 = _psi(y2_raw)
        _grid_and_ticks(ax, y2[0], y2[1], y2[2], y2[3], y2[4], rotate_y=True)
        ax.set_ylim(y2[0], y2[1])
        ax.set_ylabel(YLABEL_C2, fontsize=T_AXIS_Y, color=TEXT_COLOR,
                      labelpad=8)
        ax.set_title(spec.title_depth, fontsize=T_TITLE, color=TEXT_COLOR,
                     pad=5)
        _event_lines(ax, spec)
        h, = ax.plot(*_xy_psi(spec.hydrostatic),
                     color=RED, lw=LW_THICK, zorder=3,
                     solid_capstyle='round')
        handles2, labels2 = [h], ['Hydrostatic']
        if spec.dynamic is not None:
            h2, = ax.plot(*_xy_psi(spec.dynamic),
                          color=NAVY, lw=LW_THICK, zorder=3,
                          solid_capstyle='round')
            handles2.append(h2)
        else:
            handles2.append(Line2D([], [], color=NAVY, lw=LW_THICK))
        labels2.append('Dynamic')
        _legend(ax, handles2, labels2)

        # ---------------- Chart 3: flow rates at depth ----------------------
        ax = axes[2]
        _style_panel(ax, xlo, xhi)
        _grid_x(ax, xlo, xhi, xminor, xmajor)
        y3_raw, y3_changed = _display_axis(
            y3_caller,
            (spec.acquired_q_out, spec.acquired_q_in, spec.q_in, spec.q_out),
            zero_based=False, window=(xlo, xhi))
        y3 = tuple(y3_raw[:4]) + ('%g',)  # bbl/min: no unit conversion
        _grid_and_ticks(ax, y3[0], y3[1], y3[2], y3[3], y3[4], rotate_y=True)
        ax.set_ylim(y3[0], y3[1])
        ax.set_ylabel(YLABEL_C3, fontsize=T_AXIS_Y, color=TEXT_COLOR,
                      labelpad=8)
        ax.set_title(spec.title_fluids, fontsize=T_TITLE, color=TEXT_COLOR,
                     pad=5)
        _event_lines(ax, spec)
        handles, labels = [], []
        if spec.acquired_q_out is not None:
            h, = ax.plot(*_xy(spec.acquired_q_out),
                         color=RED, lw=LW_THICK, zorder=2.6,
                         solid_capstyle='round')
        else:
            h = Line2D([], [], color=RED, lw=LW_THICK)
        handles.append(h); labels.append('Acquired Q Out')
        if spec.acquired_q_in is not None:
            h, = ax.plot(*_xy(spec.acquired_q_in),
                         color=NAVY, lw=LW_THICK, zorder=2.7,
                         solid_capstyle='round')
        else:
            h = Line2D([], [], color=NAVY, lw=LW_THICK)
        handles.append(h); labels.append('Acquired Q In')
        h, = ax.plot(*_xy(spec.q_in), color=ORANGE, lw=LW_THICK,
                     zorder=3, solid_capstyle='round')
        handles.append(h); labels.append('Q In')
        h, = ax.plot(*_xy(spec.q_out), color=GREEN, lw=LW_THICK,
                     zorder=4, solid_capstyle='round')
        handles.append(h); labels.append('Q Out')
        _legend(ax, handles, labels)

        # D2 (additive) + DOC 52 (D): machine-readable axis audit.  The
        # audit records the PRESENTED limits, whether a display-only
        # recomputation expanded a caller axis (and what the caller asked
        # for), which present series exceed the CALLER's original axis, and
        # any event/marker times outside the visible window — a no-silent-
        # clipping ledger for all three panels (pressure AND flow).
        def _above(axis_lo_hi, series, factor):
            """Series (already in `axis` units via `factor`) vs that axis.
            Pressure panels pass the caller axis converted to psi; the flow
            panel passes bbl/min unchanged."""
            lo, hi = axis_lo_hi[0], axis_lo_hi[1]
            tol = 1e-6 * max(hi - lo, 1e-12)
            y = np.asarray(series[1], float) * factor
            return bool(y.size and (y.max() > hi + tol
                                    or y.min() < lo - tol))

        y1_caller_psi = (y1_caller[0] * 1000.0, y1_caller[1] * 1000.0)
        y2_caller_psi = (y2_caller[0] * 1000.0, y2_caller[1] * 1000.0)

        # DOC 52 R1: per-panel machine-readable record of PRESENT channels
        # with samples outside the visible time window (channel -> count).
        # This is the TIME-EXCLUSION disclosure (intentional, like
        # 'out_of_window_events'); it is deliberately distinct from the
        # Y-AXIS disclosures ('above_axis' / 'recomputed' /
        # 'original_lim').
        def _oow_samples(series):
            x = np.asarray(series[0], float)
            return int(((x < xlo - 1e-9) | (x > xhi + 1e-9)).sum())

        def _oow_map(names_series):
            return {name: _oow_samples(s) for name, s in names_series
                    if s is not None and _oow_samples(s) > 0}

        fig._doc51r_axis_audit = {
            'presentation': 'direct-psi (AZNS-179 p4 / DOC 50)',
            'time_window': (float(xlo), float(xhi)),
            'axis_y1': {'unit': 'psi', 'lim': (y1[0], y1[1]),
                        'recomputed': bool(y1_changed),
                        'original_lim': (round(y1_caller_psi[0], 6),
                                         round(y1_caller_psi[1], 6)),
                        'above_axis': sorted(
                            name for name, s in (
                                ('back_pressure', spec.back_pressure),
                                ('acquired_pressure', spec.acquired_pressure),
                                ('calc_pump_press', spec.calc_pump_press),
                                ('calc_cem_hp', spec.calc_cem_hp))
                            if s is not None
                            and _above(y1_caller_psi, s, 1000.0)),
                        'out_of_window_samples': _oow_map((
                            ('back_pressure', spec.back_pressure),
                            ('acquired_pressure', spec.acquired_pressure),
                            ('calc_pump_press', spec.calc_pump_press),
                            ('calc_cem_hp', spec.calc_cem_hp)))},
            'axis_y2': {'unit': 'psi', 'lim': (y2[0], y2[1]),
                        'recomputed': bool(y2_changed),
                        'original_lim': (round(y2_caller_psi[0], 6),
                                         round(y2_caller_psi[1], 6)),
                        'above_axis': sorted(
                            name for name, s in (
                                ('hydrostatic', spec.hydrostatic),
                                ('dynamic', spec.dynamic))
                            if s is not None
                            and _above(y2_caller_psi, s, 1000.0)),
                        'out_of_window_samples': _oow_map((
                            ('hydrostatic', spec.hydrostatic),
                            ('dynamic', spec.dynamic)))},
            'axis_y3': {'unit': 'bbl/min', 'lim': (y3[0], y3[1]),
                        'recomputed': bool(y3_changed),
                        'original_lim': (round(y3_caller[0], 6),
                                         round(y3_caller[1], 6)),
                        'above_axis': sorted(
                            name for name, s in (
                                ('acquired_q_out', spec.acquired_q_out),
                                ('acquired_q_in', spec.acquired_q_in),
                                ('q_in', spec.q_in), ('q_out', spec.q_out))
                            if s is not None
                            and _above(y3_caller[:2], s, 1.0)),
                        'out_of_window_samples': _oow_map((
                            ('acquired_q_out', spec.acquired_q_out),
                            ('acquired_q_in', spec.acquired_q_in),
                            ('q_in', spec.q_in), ('q_out', spec.q_out)))},
            'out_of_window_events': sorted(
                float(tv) for tv in
                tuple(spec.event_times)
                + (() if spec.marker_time is None
                   else (float(spec.marker_time),))
                if tv < xlo - 1e-9 or tv > xhi + 1e-9)}
        return fig


def save_png(fig, png_path: str) -> str:
    # D1: same per-figure font policy as the renderer (draw-time text
    # creation must not read process-global state either).
    with plt.rc_context(dict(_FONT_RC)):
        fig.savefig(png_path, dpi=200, facecolor='white')
    plt.close(fig)
    return png_path


# ----------------------------------------------------------------------------
# ONE-CALL API — Phase IV fluid_data + geometry -> figure + result + warnings
# ----------------------------------------------------------------------------
def _build_fluids(stages: List[FluidStageSpec], disp_pcf: float,
                  rheology=None, mud_pv_yp=None,
                  slurry_rheology=None
                  ) -> Tuple[Dict[str, Fluid], List[str], bool]:
    """Fluid table for the engine  ->  (fluids, warnings, frictionless_mode).

    Resolution order per fluid (owner decisions D7/D8/D9 — nothing invented):
      1. rheology={name: entry} explicit override (diagnostic / legacy path);
      2. Displacement Fluid <- mud_pv_yp (Phase II/III effective_pv/yp);
         missing mud_pv_yp  -> the WHOLE chart set runs hydrostatic-only (D9);
      3. slurries  <- slurry_rheology[name] (normally rheology_from_lab(),
         dataset bhct_down, D8) incl. the measured gel_10_min (D13);
         missing entry -> that slurry is frictionless + named warning;
      4. Spacer family <- the record's own pv_cp/yp_lbf100ft2 fields (D7);
         missing -> that fluid is frictionless + named warning.
    rheology='hydrostatic' forces the frictionless diagnostic mode.
    """
    names = [st.fluid_type for st in stages]
    if 'Displacement Fluid' not in names:
        names.append('Displacement Fluid')
    warnings: List[str] = []
    fluids: Dict[str, Fluid] = {}

    forced_hydro = isinstance(rheology, str) and rheology == 'hydrostatic'
    user = rheology if isinstance(rheology, dict) else {}

    # --- D9: mud PV/YP gate -------------------------------------------------
    mud_entry = None
    if mud_pv_yp is not None:
        try:
            pv_m, yp_m = float(mud_pv_yp[0]), float(mud_pv_yp[1])
        except (TypeError, ValueError, IndexError):
            raise ChartInputError(
                'mud_pv_yp must be (PV[cP], YP[lbf/100ft2]) from Phase '
                'II/III effective_pv/effective_yp; got %r.' % (mud_pv_yp,))
        if not (math.isfinite(pv_m) and math.isfinite(yp_m)) or pv_m <= 0 or yp_m < 0:
            raise ChartInputError(
                'mud_pv_yp is degenerate (need PV>0, YP>=0); got %r.'
                % (mud_pv_yp,))
        mud_entry = {'pv_cp': pv_m, 'yp_lbf100ft2': yp_m,
                     'gel_10_min': None, 'source': 'phase2_3:effective_pv_yp'}
    elif not forced_hydro:
        forced_hydro = True
        warnings.append(
            'Mud PV/YP not supplied (Phase II/III effective_pv/effective_yp '
            'missing) — the WHOLE chart set is computed HYDROSTATIC-ONLY '
            '(owner decision D9).')

    def rho_of(n: str) -> float:
        return disp_pcf if n == 'Displacement Fluid' else \
            next(s.density_pcf for s in stages if s.fluid_type == n)

    def entry_fluid(n, rho, entry, note):
        if 'pv_cp' in entry:
            mu = _er01_finite(entry['pv_cp'], '%s: PV [cP]' % n)
            ty = _er01_finite(entry.get('yp_lbf100ft2') or 0.0,
                              '%s: YP [lbf/100ft2]' % n)
            gel = entry.get('gel_10_min')
            gel_pa = (_er01_finite(gel, '%s: gel_10_min' % n)
                      * LBF100FT2_TO_PA) if gel else 0.0
            if mu <= 0 or (ty <= 0 and gel_pa <= 0):
                raise ChartInputError(
                    '%s: rheology entry is degenerate (need PV>0 and '
                    'YP>0 or gel>0); got %r.' % (n, entry))
            if note:
                warnings.append(note)
            return Fluid(n, pcf_to_ppg(rho), mu_p_cp=mu, tau_y=ty,
                         gel_pa=gel_pa)
        n_v = _er01_finite(entry['n'], '%s: n [-]' % n)
        K_v = _er01_finite(entry['K_pas'], '%s: K [Pa*s^n]' % n)
        if n_v <= 0.0 or K_v <= 0.0:
            raise ChartInputError(
                '%s: HB rheology must have n > 0 and K > 0; got n=%r K=%r.'
                % (n, entry['n'], entry['K_pas']))
        return Fluid(n, pcf_to_ppg(rho), n_pl=n_v, K_pl=K_v)

    for n in names:
        rho = rho_of(n)
        if forced_hydro:
            # D9/D7 fallback: density-only fluid (friction comes from
            # job.frictionless for the WHOLE run in D9; for a single D7/D8
            # fluid the per-fluid flag zeroes just its own friction).
            fluids[n] = Fluid(n, pcf_to_ppg(rho))
            continue
        if n in user:
            fluids[n] = entry_fluid(n, rho, user[n], None)
        elif n == 'Displacement Fluid':
            fluids[n] = entry_fluid(n, rho, mud_entry, None)
        elif n in SLURRY_TYPES:
            entry = (slurry_rheology or {}).get(n)
            if entry and entry.get('pv_cp'):
                fluids[n] = entry_fluid(n, rho, entry, None)
            else:
                fluids[n] = Fluid(n, pcf_to_ppg(rho), frictionless_fluid=True)
                warnings.append(
                    '%s: no valid Bingham fit for the lab dataset %r '
                    '(owner decision D8) — hydrostatic contribution only; '
                    'select and fit the dataset in Phase VII.'
                    % (n, RHEOLOGY_DATASET))
        elif n in SPACER_TYPES:
            st = next(s for s in stages if s.fluid_type == n)
            if st.pv_cp and st.pv_cp > 0:
                fluids[n] = Fluid(n, pcf_to_ppg(rho), mu_p_cp=st.pv_cp,
                                  tau_y=st.yp_lbf100ft2 or 0.0)
            else:
                # D7 NOTE: the host app will provide PV/YP per fluid
                # (operator-entered, Bingham model).  Until then this fluid
                # weighs on the columns but contributes no friction.
                fluids[n] = Fluid(n, pcf_to_ppg(rho), frictionless_fluid=True)
                warnings.append(
                    '%s: no PV/YP on the Phase IV record (owner decision '
                    'D7 — the host will provide them) — hydrostatic '
                    'contribution only.' % n)
        else:
            raise ChartInputError(
                '%s is active but has no rheology rule (not a slurry, not '
                'the displacement fluid, not a spacer family member).'
                % n)
    return fluids, warnings, forced_hydro


def build_three_charts(fluid_data: Dict[str, Dict[str, Any]],
                       geometry: GeometrySpec,
                       rheology=None,
                       mud_pv_yp=None,
                       slurry_rheology=None,
                       bhsp=None,
                       options: Optional[ChartOptions] = None
                       ) -> Tuple[Any, SimResult, List[str]]:
    """Phase IV `fluid_data` -> (figure, SimResult, warnings).

    geometry is REQUIRED.  Rheology resolution and the BHSP shut-in anchor
    follow owner decisions D7-D14 (module docstring).  bhsp accepts the
    Phase II/III free text ('7300+1000' -> the larger number, D14), a
    number, or None (no shut-in segment).
    """
    if geometry is None:
        raise ChartInputError(
            "geometry is required: use geometry_from_hardware(hardware_table, "
            "target_row=...) or GeometrySpec(td_m=..., hole_id_in=..., "
            "pipe_od_in=..., pipe_id_in=...).")
    opt = options or ChartOptions()
    stages, warnings = stages_from_fluid_data(fluid_data)

    bhsp_psi = parse_bhsp_psi(bhsp)

    # geometry cross-checks (warnings only — never silent, never blocking)
    V_pipe = geometry.total_pipe_bbl          # D11 v1.2: section-aware totals
    disp = next((s for s in stages if s.fluid_type == 'Displacement Fluid'), None)
    if disp is not None and disp.volume_bbl > V_pipe * 1.01:
        warnings.append(
            'Displacement volume %.1f bbl exceeds the string capacity '
            '%.1f bbl — check the entered volume.' % (disp.volume_bbl, V_pipe))
    total = sum(s.volume_bbl for s in stages)
    if total > (V_pipe + geometry.total_ann_bbl) * 1.01:
        warnings.append(
            'Total pumped volume %.1f bbl exceeds the wellbore capacity — '
            'returns exceed what the annulus can hold.' % total)

    disp_pcf = float(fluid_data['Displacement Fluid']['effective_density'])
    fluids, rheo_warnings, frictionless = _build_fluids(
        stages, disp_pcf, rheology=rheology, mud_pv_yp=mud_pv_yp,
        slurry_rheology=slurry_rheology)
    warnings.extend(rheo_warnings)

    job = JobDesign(geo=geometry, fluids=fluids,
                    displacement_fluid='Displacement Fluid',
                    placement=stages,
                    back_pressure_psi=opt.back_pressure_psi,
                    surface_line_kpsi_at_8bpm=opt.surface_line_kpsi_at_8bpm,
                    dt_min=opt.dt_min,
                    tail_cap_min=opt.tail_cap_min,
                    float_equipment=opt.float_equipment,   # v1.4.3 passthrough
                    frictionless=frictionless,
                    bhsp_psi=bhsp_psi,
                    shutin_ramp_min=opt.shutin_ramp_min)
    res = simulate(job)

    if res.diag.get('shutin_note'):
        warnings.append(res.diag['shutin_note'])
    if res.diag.get('tail_capped') and opt.tail_cap_min > 0:
        warnings.append(
            'U-tube equalization tail reached its %.0f min guard without full '
            'balance — check the entered volumes against the well capacity.'
            % opt.tail_cap_min)
    if opt.tail_cap_min == 0 and opt.plot_window == 'pumping_only':
        # v1.4.3: the tail disable is an INTENTIONAL pumping presentation,
        # not a failed equalization (tail_capped from a 0-min guard is not
        # a physical guard failure; a real cap>0 failure keeps the v1.4.2
        # message verbatim above).
        warnings.append(
            'Pumping presentation (tail_cap_min=0, plot_window=pumping_only): '
            'the plotted record ends at the last pumping sample before EOD; '
            'post-job equalization and the D14 shut-in ramp are not drawn.')
    if res.diag.get('head_overflow_bbl', 0.0) > 0.1:
        warnings.append(
            '%.1f bbl overflowed through the cement head during equalization '
            '(annulus side over-heavy) — review the displacement volume.'
            % res.diag['head_overflow_bbl'])

    if res.t_atcp is None:
        warnings.append(
            'No slurry reaches the track depth within the entered volumes '
            '(ATCP line omitted) — check slurry/displacement volumes or use '
            'the friction mode (free fall moves slurry out faster).')

    events = tuple(e for e in (res.t_atcp, res.t_eod) if e is not None)
    marker = opt.marker_time_override
    if marker is None:
        marker = res.t_marker            # D14: start of the shut-in segment
    if marker is not None and any(abs(marker - e) < 1e-9 for e in events):
        marker = None                       # suppression rule (no duplicate)
    post_job_marker = None
    if (marker is not None and opt.plot_window == 'pumping_only'
            and float(marker) > float(res.t_eod) - 1e-9):
        # DOC 52 (E): a post-job-only marker (shut-in start / D14) must not
        # be presented inside a pumping-only chart's axis headroom.  This is
        # presentation-only: the raw SimResult (res.t_marker) and the event
        # record are NEVER mutated, and genuine in-window markers stay.
        post_job_marker = float(marker)
        marker = None

    # axis covers the FULL record (pumping + equalization tail + D14
    # shut-in segment) — v1.0 scaled from t_eod only and could clip the
    # post-job segments on short jobs; fixed in v1.1.
    # v1.4.3: plot_window='pumping_only' renders the PUMPING branch only
    # (t < t_eod - 1e-9 — the simulate() pumping/post-job split).  The raw
    # SimResult arrays are NEVER rewritten; the window applies to the
    # plotted spec arrays and the axis selection only, and is audited in
    # res.diag['plot_window_audit'].
    if opt.plot_window not in ('full_record', 'pumping_only'):
        raise ChartInputError(
            "plot_window must be 'full_record' or 'pumping_only', got %r."
            % (opt.plot_window,))
    vis = None
    if opt.plot_window == 'pumping_only':
        vis = res.t < (res.t_eod - 1e-9)
        if not vis.any():
            # D6 (DOC 51R v2): fail closed.  v1.4.3 silently reverted to the
            # full record here, presenting post-EOD samples (EOD artifact /
            # D14) under a pumping_only chart.  No endpoint is invented; the
            # caller sees the precise reason instead of a wrong chart.
            raise ChartInputError(
                "plot_window='pumping_only' but the record contains no "
                'pre-EOD sample (t >= t_eod - 1e-9 everywhere); there is no '
                'pumping segment to present — not falling back to the full '
                'record (D6 fail-closed).')
    t_plot = res.t if vis is None else res.t[vis]
    res.diag['plot_window_audit'] = {
        'plot_window': opt.plot_window,
        'rule': 'visible = t < t_eod - 1e-9 (simulate() pumping/post-job branch split)',
        'n_raw': int(res.t.size),
        'n_visible': int(res.t.size if vis is None else vis.sum()),
        'n_excluded': int(0 if vis is None else int((~vis).sum())),
        't_visible_last': float(t_plot[-1]),
        't_eod': float(res.t_eod),
        'tail_cap_min': float(opt.tail_cap_min),
        'float_equipment': bool(opt.float_equipment),
        'post_job_marker_excluded': post_job_marker}
    ax_x = opt.axis_x or autoscale_x(float(t_plot[-1]))
    if vis is None:
        c1_hi = float(max(res.whp.max(), res.pump.max()))
        y2_lo = float(res.hydro.min())
        y2_hi = float(res.hydro.max())
        if res.dyn is not None:
            y2_lo = min(y2_lo, float(res.dyn.min()))
            y2_hi = max(y2_hi, float(res.dyn.max()))
        q_lo = float(min(res.q_in.min(), res.q_out.min()))
        q_hi = float(max(res.q_in.max(), res.q_out.max()))
    else:
        c1_hi = float(max(res.whp[vis].max(), res.pump[vis].max()))
        y2_lo = float(res.hydro[vis].min())
        y2_hi = float(res.hydro[vis].max())
        if res.dyn is not None:
            y2_lo = min(y2_lo, float(res.dyn[vis].min()))
            y2_hi = max(y2_hi, float(res.dyn[vis].max()))
        q_lo = float(min(res.q_in[vis].min(), res.q_out[vis].min()))
        q_hi = float(max(res.q_in[vis].max(), res.q_out[vis].max()))
    c1_lo = 0.0
    ax_y1 = opt.axis_y1 or autoscale_y(c1_lo, max(c1_hi, 0.1), zero_based=True)
    ax_y2 = opt.axis_y2 or autoscale_y(y2_lo, y2_hi, zero_based=False)
    ax_y3 = opt.axis_y3 or autoscale_y(q_lo, q_hi, zero_based=False)

    spec = JobChartsSpec(
        calc_cem_hp=(t_plot, res.whp if vis is None else res.whp[vis]),
        calc_pump_press=(t_plot, res.pump if vis is None else res.pump[vis]),
        acquired_pressure=None,
        back_pressure=None,
        hydrostatic=(t_plot, res.hydro if vis is None else res.hydro[vis]),
        dynamic=((t_plot, res.dyn) if res.dyn is not None else None) if vis is None
            else ((t_plot, res.dyn[vis]) if res.dyn is not None else None),
        q_in=(t_plot, res.q_in if vis is None else res.q_in[vis]),
        q_out=(t_plot, res.q_out if vis is None else res.q_out[vis]),
        acquired_q_in=None,
        acquired_q_out=None,
        depth_m=geometry.track_depth_m,
        depth_unit=geometry.depth_unit,
        event_times=events,
        marker_time=marker,
        axis_x=ax_x, axis_y1=ax_y1, axis_y2=ax_y2, axis_y3=ax_y3)

    fig = render_three_charts(spec)
    return fig, res, warnings


# ----------------------------------------------------------------------------
# DEMO — a Phase-IV-style user-entered fluid train on the source-confirmed
# reference well (3293 m, 8.5"x5"x4.276").  These are DEMO inputs, typed
# exactly as Phase IV would store them (build_fluid_record contract) plus
# the D7 PV/YP fields and the Phase VII lab payload shape (lab_payload_*).
# ----------------------------------------------------------------------------
DEMO_MUD_PV_YP = (45.0, 5.0)     # demo Phase II/III effective_pv / effective_yp
DEMO_BHSP = '7300+1000'          # demo Phase II/III BHSP free text (D14)


def demo_fluid_data() -> Dict[str, Dict[str, Any]]:
    rec = dict  # shorthand
    return {
        # D7 NOTE: the Spacer carries its own PV/YP (the host app will
        # provide them); Pre Flush deliberately has none, so the demo
        # warnings list shows the documented D7 fallback message.
        'Pre Flush': rec(name='Pre Flush', material_name='Fresh Water',
                         volume=25.0, density='62.4', effective_density=62.4,
                         pump_rate='8.0', min_rate=8.0,
                         duration_min=3.125,
                         duration_str=format_to_hr_mm(3.125),
                         cumul_time_min=3.125,
                         cumul_time_str=format_to_hr_mm(3.125)),
        'Spacer': rec(name='Spacer', material_name='High-Vis Spacer',
                      volume=30.0, density='77.4', effective_density=77.4,
                      pump_rate='8.0', min_rate=8.0,
                      pv_cp=40.0, yp_lbf100ft2=8.0,
                      duration_min=3.75,
                      duration_str=format_to_hr_mm(3.75),
                      cumul_time_min=6.875,
                      cumul_time_str=format_to_hr_mm(6.875)),
        'Main': rec(name='Main', material_name='Cement Slurry',
                    volume=141.4, density='118.9', effective_density=118.9,
                    pump_rate='8.0', min_rate=8.0,
                    duration_min=17.675,
                    duration_str=format_to_hr_mm(17.675),
                    cumul_time_min=24.55,
                    cumul_time_str=format_to_hr_mm(24.55)),
        'Displacement Fluid': rec(
            name='Displacement Fluid', material_name='Drilling Mud',
            volume=152.4, density='78.1', effective_density=78.1,
            pump_rate='8.0', min_rate=8.0,
            duration_min=19.05,
            duration_str=format_to_hr_mm(19.05),
            cumul_time_min=43.6,
            cumul_time_str=format_to_hr_mm(43.6)),
    }


def demo_lab_payloads() -> Dict[str, Dict[str, Any]]:
    """DEMO Phase VII payloads shaped EXACTLY like lab_payload_{slurry}
    (phase_7_lab.py) — only the keys rheology_from_lab() reads are filled.
    Owner decision D8: the bhct_down (BHCT — Ramp-Down) Bingham fit feeds
    the friction; D13: its measured 10-min gel holds the post-job column.
    surface_down is present but NOT selected (must be ignored)."""
    def row(selected, pv, ty, iod, gel10):
        return {'selected': selected, 'is_valid_bingham': selected,
                'pv_cp': pv, 'ty_lbf_100ft2': ty, 'iod': iod,
                'gel_10_sec': 5.0 if selected else None,
                'gel_10_min': gel10 if selected else '-',
                'validation_message': '' if selected else 'not selected'}

    def payload(pv, ty, iod, gel10):
        return {'rheology': {
            'surface_down': row(False, None, None, None, None),
            'bhct_up': row(False, None, None, None, None),
            'bhct_down': row(True, pv, ty, iod, gel10),
        }, 'bhct': 250, 'bhst': 280}

    return {
        'Main': payload(120.0, 18.0, 0.982, 8.0),
        'Tail': payload(135.0, 22.0, 0.971, 10.0),
        # Lead: valid fit but the operator left the gel fields as '-' —
        # rheology_from_lab must return gel_10_min=None for it (D13).
        'Lead': payload(110.0, 15.0, 0.965, '-'),
    }


def demo_slurry_rheology() -> Dict[str, Dict[str, Any]]:
    """The D8/D13 entries the demo feeds build_three_charts — produced by
    the SAME adapter the host uses on the real payloads."""
    return rheology_from_lab(demo_lab_payloads())


def demo_geometry() -> GeometrySpec:
    """SOURCE-CONFIRMED reference well ONLY (Doc 17); a real run passes its
    own Phase II/III geometry (geometry_from_hardware)."""
    return GeometrySpec(td_m=3293.0, track_depth_m=3293.0,
                        hole_id_in=8.5, pipe_od_in=5.0, pipe_id_in=4.276)


def demo_hardware_rows() -> List[Dict[str, Any]]:
    """DEMO Phase II/III hardware_table rows for geometry_from_hardware —
    a CSG 9 5/8 job on the reference well (12 1/4\" open hole below a
    13 3/8\" previous casing)."""
    return [
        {'Description': 'Previous Casing', 'MD (m)': '0.0-2816.0',
         'Size (in)': '13 3/8', 'ID (in)': 12.415, 'Joint (m)': 0.0,
         'Weight (ppf)': 61.0, 'Grade': 'J-55'},
        {'Description': 'Casing', 'MD (m)': '2816.0-3293.0',
         'Size (in)': '9 5/8', 'ID (in)': 8.681, 'Joint (m)': 0.0,
         'Weight (ppf)': 40.0, 'Grade': 'L-80'},
        {'Description': 'Open Hole Size', 'MD (m)': '2816.0-3293.0',
         'Size (in)': '12 1/4', 'ID (in)': 12.25, 'Joint (m)': 0.0,
         'Weight (ppf)': 0.0, 'Grade': '-'},
    ]


def demo_hardware_rows_liner() -> List[Dict[str, Any]]:
    """DEMO LNR 7\" rows (owner rule D11b): the 7\" liner hangs inside the
    9 5/8\" casing; above the hanger the Drill Pipes occupy the 9 5/8\" ID
    (the return crosses INTO the 9 5/8\" ID at the liner top), below the
    9 5/8\" shoe the annulus is the 8 1/2\" open hole."""
    return [
        {'Description': 'Previous Casing', 'MD (m)': '0.0-2816.0',
         'Size (in)': '9 5/8', 'ID (in)': 8.681, 'Joint (m)': 0.0,
         'Weight (ppf)': 40.0, 'Grade': 'L-80'},
        {'Description': 'Drill Pipes', 'MD (m)': '0.0-2816.0',
         'Size (in)': '5', 'ID (in)': 4.276, 'Joint (m)': 0.0,
         'Weight (ppf)': 19.5, 'Grade': 'S-135'},
        {'Description': 'Liner', 'MD (m)': '2816.0-3293.0',
         'Size (in)': '7', 'ID (in)': 6.184, 'Joint (m)': 0.0,
         'Weight (ppf)': 29.0, 'Grade': 'L-80'},
        {'Description': 'Open Hole Size', 'MD (m)': '2816.0-3293.0',
         'Size (in)': '8 1/2', 'ID (in)': 8.5, 'Joint (m)': 0.0,
         'Weight (ppf)': 0.0, 'Grade': '-'},
    ]


def demo_hardware_rows_tieback() -> List[Dict[str, Any]]:
    """DEMO TIE BACK LNR 7\" rows (owner rule D11b): the tie-back runs from
    surface to the old 7\" liner top at 2700 m and the flow continues INSIDE
    the old liner to its shoe at 3293 m ("از توی لاینر"); the return crosses
    into the 9 5/8\" ID at the tie-in."""
    return [
        {'Description': 'Previous Casing', 'MD (m)': '0.0-2816.0',
         'Size (in)': '9 5/8', 'ID (in)': 8.681, 'Joint (m)': 0.0,
         'Weight (ppf)': 40.0, 'Grade': 'L-80'},
        {'Description': 'Previous Liner', 'MD (m)': '2700.0-3293.0',
         'Size (in)': '7', 'ID (in)': 6.184, 'Joint (m)': 0.0,
         'Weight (ppf)': 29.0, 'Grade': 'L-80'},
        {'Description': 'Tie Back', 'MD (m)': '0.0-2700.0',
         'Size (in)': '7', 'ID (in)': 6.184, 'Joint (m)': 0.0,
         'Weight (ppf)': 29.0, 'Grade': 'L-80'},
        {'Description': 'Open Hole Size', 'MD (m)': '2816.0-3293.0',
         'Size (in)': '8 1/2', 'ID (in)': 8.5, 'Joint (m)': 0.0,
         'Weight (ppf)': 0.0, 'Grade': '-'},
    ]


# ----------------------------------------------------------------------------
# Acceptance tests — A1-A16 (data contract + engine) + B1-B16 (owner
# decisions D7-D18 + audit patches P1/P2) + R1-R4 (render)
# ----------------------------------------------------------------------------
def run_selftest(verbose: bool = True) -> bool:
    results = []

    def rec(name, ok, detail=''):
        results.append((name, bool(ok), detail))

    MUD = DEMO_MUD_PV_YP
    SLURRY = demo_slurry_rheology()

    def build(fluid_data=None, geo=None, rheology=None, opt=None,
              mud=True, slurry=True, bhsp=None):
        return build_three_charts(
            fluid_data or demo_fluid_data(),
            geo or demo_geometry(),
            rheology=rheology,
            mud_pv_yp=mud if isinstance(mud, tuple) else (MUD if mud else None),
            slurry_rheology=(slurry if isinstance(slurry, dict)
                             else (SLURRY if slurry else None)),
            bhsp=bhsp, options=opt)

    # ---------- A1: adapter re-sorts by the Phase IV cumulative chain -------
    fd = demo_fluid_data()
    shuffled = {'Main': fd['Main'], 'Displacement Fluid': fd['Displacement Fluid'],
                'Spacer': fd['Spacer'], 'Pre Flush': fd['Pre Flush']}
    fig, res, warn = build(shuffled)
    rec('A1 adapter order by cumul',
        abs(res.t_eod - 43.6) < 1e-6 and res.t_atcp is not None,
        'EOD=%.4f' % res.t_eod)
    plt.close(fig)

    # ---------- A2: INVALID RATE chain refuses ------------------------------
    fd2 = demo_fluid_data()
    fd2['Main'] = dict(fd2['Main'], min_rate=0.0)
    try:
        build(fd2)
        rec('A2 invalid rate refuses', False, 'no exception')
    except ChartInputError as exc:
        rec('A2 invalid rate refuses', 'rate' in str(exc).lower(), str(exc)[:60])

    # ---------- A3: invalid density refuses ---------------------------------
    fd3 = demo_fluid_data()
    fd3['Spacer'] = dict(fd3['Spacer'], effective_density=0.0)
    try:
        build(fd3)
        rec('A3 invalid density refuses', False, 'no exception')
    except ChartInputError as exc:
        rec('A3 invalid density refuses', 'density' in str(exc).lower(),
            str(exc)[:60])

    # ---------- A4: zero-volume stage skipped + displacement-0 warning ------
    fd4 = demo_fluid_data()
    fd4['Spacer'] = dict(fd4['Spacer'], volume=0.0)
    fd4['Displacement Fluid'] = dict(fd4['Displacement Fluid'], volume=0.0,
                                     cumul_time_min=24.55,
                                     cumul_time_str='00:25')
    fig, res4, warn4 = build(fd4)
    rec('A4 zero-volume handled',
        abs(res4.t_eod - (3.125 + 17.675)) < 1e-6
        and any('Displacement Fluid volume is 0' in w for w in warn4)
        and any('Spacer' in w and 'skipped' in w for w in warn4),
        'EOD=%.3f (skipped stages free their time)' % res4.t_eod)
    plt.close(fig)

    # ---------- A5: V/Q identity — engine EOD == Phase IV cumul -------------
    fig, res, warn = build()
    rec('A5 EOD = max cumul_time_min', abs(res.t_eod - 43.6) < 1e-6,
        'engine=%.6f phase4=43.6' % res.t_eod)
    plt.close(fig)

    # ---------- A6: pcf <-> ppg conversion anchors --------------------------
    ppg = pcf_to_ppg(78.0966)
    back = ppg_to_pcf(10.44)
    rec('A6 pcf/ppg conversion',
        abs(ppg - 10.44) < 1e-4 and abs(back - 78.0966) < 1e-4,
        '78.0966 pcf -> %.4f ppg, 10.44 ppg -> %.4f pcf' % (ppg, back))

    # ---------- A7: mud head anchor (Placement bm8: 0.052*ppg*H_ft) ---------
    geo = demo_geometry()
    p_ref = 0.052 * pcf_to_ppg(78.1) * geo.td_m * M_TO_FT / 1000.0
    rec('A7 mud head anchor',
        abs(res.hydro0_kpsi - p_ref) < 0.02,
        'engine=%.4f formula=%.4f kpsi' % (res.hydro0_kpsi, p_ref))

    # ---------- A8: WHP(0) = mud circulation friction at 8 bpm --------------
    q_m3s = 8.0 * BBL_TO_M3 / 60.0
    mu0, ty0 = MUD
    mud_t = Fluid('m', pcf_to_ppg(78.1), mu_p_cp=mu0, tau_y=ty0)
    fl_t = {'Displacement Fluid': mud_t}
    vp_t, va_t = geo.v_pipe_bbl_per_m, geo.v_ann_bbl_per_m
    Fp0 = fric_col_pa([['Displacement Fluid', geo.td_m * vp_t]], vp_t, q_m3s,
                      fl_t, geo, True)
    Fa0 = fric_col_pa([['Displacement Fluid', geo.td_m * va_t]], va_t, q_m3s,
                      fl_t, geo, False)
    rec('A8 WHP(0) = circulation friction',
        abs(float(res.whp[0]) - (Fp0 + Fa0) * KPSI_PER_PA) < 1e-6,
        'whp0=%.4f expected=%.4f' % (res.whp[0], (Fp0 + Fa0) * KPSI_PER_PA))

    # ---------- A9: post-job tail WITH measured gel (D13) --------------------
    # The exchange now stops at the gel-held balance: |imbalance| <= Y
    # (static yield of both columns).  WHP keeps the residual, the slurry
    # has slumped into the string, the guard never fires.
    i_eod = int(np.searchsorted(res.t, res.t_eod))
    rec('A9 gel-held tail (D13)',
        res.whp[-1] <= 0.30 and res.whp[-1] >= -1e-9
        and res.final_hydro_kpsi <= res.hydro[min(i_eod, len(res.hydro) - 1)] - 0.05
        and len(res.t) > i_eod + 2
        and not res.diag.get('tail_capped')
        and res.diag.get('head_overflow_bbl', 0.0) < 0.1,
        'WHP_end=%.4f (gel residual) hydro: %.4f@EOD -> %.4f@end (tail %.1f min)'
        % (res.whp[-1], res.hydro[min(i_eod, len(res.hydro) - 1)],
           res.final_hydro_kpsi, res.t[-1] - res.t_eod))

    # ---------- A10: ATCP present (friction) / absent + warned (hydro D9) ----
    rec('A10a ATCP friction mode',
        res.t_atcp is not None and 6.875 < res.t_atcp < res.t_eod,
        'ATCP=%.3f' % (res.t_atcp or -1))
    fig_h, res_h, warn_h = build(mud=False)
    vp_h = demo_geometry().v_pipe_bbl_per_m
    t_expect = (25.0 + 30.0 + demo_geometry().td_m * vp_h) / 8.0
    rec('A10b ATCP hydro mode = (V_pre+V_pipe)/Q (D9)',
        res_h.t_atcp is not None
        and abs(res_h.t_atcp - t_expect) < 0.1
        and res.t_atcp is not None and res_h.t_atcp > res.t_atcp
        and any('HYDROSTATIC-ONLY' in w for w in warn_h),
        'ATCP=%.3f closed-form=%.3f (friction=%.3f)'
        % (res_h.t_atcp or -1, t_expect, res.t_atcp or -1))
    plt.close(fig_h)

    # ---------- A11: marker without BHSP (no shut-in segment) ---------------
    fig2, res2, warn2 = build()
    rec('A11 marker suppressed without BHSP', res2.t_marker is None,
        'marker=%r (EOD=%.3f)' % (res2.t_marker, res2.t_eod))

    # ---------- A12: Dynamic series both modes ------------------------------
    rec('A12 Dynamic: computed >= hydro (friction) / legend-only (hydro)',
        res2.dyn is not None
        and float((res2.dyn - res2.hydro).min()) >= -1e-9
        and res_h.dyn is None,
        'min(Dyn-Hydro)=%.5f' % float((res2.dyn - res2.hydro).min()))

    # ---------- A13: free-fall exchange (friction mode) ---------------------
    m_ff = (res2.q_out > res2.q_in + 0.05) & (res2.t > 1.0)
    rec('A13 free-fall QOut>QIn',
        bool(m_ff.any()) and res2.t_freefall_start is not None,
        'steps=%d start=%s' % (int(m_ff.sum()), res2.t_freefall_start))

    # ---------- A14: auto-scale rules ---------------------------------------
    spec_ok = True
    detail = []
    figs = fig2
    # A14 (DOC 51R v2): the pressure axes present DIRECT PSI (DOC 50/51
    # approved grammar), so the raw kpsi series are compared in presentation
    # units — x1000 exactly once, the same conversion the renderer applies.
    # Flows stay bbl/min.
    for name, ax_y, series in (
            ('C1', fig2.get_axes()[0],
             tuple(s * 1000.0 for s in (res2.whp, res2.pump))),
            ('C2', fig2.get_axes()[1],
             tuple(s * 1000.0 for s in (res2.hydro, res2.dyn))),
            ('C3', fig2.get_axes()[2], (res2.q_in, res2.q_out))):
        ymin, ymax = ax_y.get_ylim()
        yticks = ax_y.get_yticks()          # major ticks only (labels)
        major = yticks[1] - yticks[0] if len(yticks) > 1 else 0.0
        n_major = (ymax - ymin) / major if major else 0.0
        ok = (3 <= n_major <= 12
              and abs((ymax - ymin) - round(n_major) * major) < 1e-9
              and ymin <= min(s.min() for s in series)
              and ymax >= max(s.max() for s in series))
        spec_ok &= ok
        detail.append('%s[%.2g..%.2g/%.2g nMaj=%.1f]'
                      % (name, ymin, ymax, major, n_major))
    rec('A14 auto-scale windows', spec_ok, ' '.join(detail))

    # ---------- A15: events inside axis and off the minor grid --------------
    _, xhi_s, xminor_s, _ = autoscale_x(float(res2.t[-1]))
    ev_ok = all(0 < e < xhi_s
                and abs((e / xminor_s) - round(e / xminor_s)) > 1e-6
                for e in (res2.t_atcp, res2.t_eod) if e is not None)
    rec('A15 events in-axis, off-grid', ev_ok,
        'events=%s step=%g' % (tuple(round(e, 3) for e in
                                     (res2.t_atcp, res2.t_eod)
                                     if e is not None), xminor_s))

    # ---------- A16: over-displacement warning ------------------------------
    fd5 = demo_fluid_data()
    fd5['Displacement Fluid'] = dict(
        fd5['Displacement Fluid'], volume=250.0, cumul_time_min=74.8,
        cumul_time_str='01:15')
    fig5, res5, warn5 = build(fd5)
    rec('A16 over-displacement warning',
        any('string capacity' in w for w in warn5),
        '; '.join(w for w in warn5 if 'capacity' in w)[:70])
    plt.close(fig5)
    plt.close(fig)

    # ---------- B1: D14 BHSP parser — the LARGER number ---------------------
    b1 = (parse_bhsp_psi('7300+1000') == 7300.0
          and parse_bhsp_psi('1000+7300') == 7300.0
          and parse_bhsp_psi('7000') == 7000.0
          and parse_bhsp_psi(8200.5) == 8200.5
          and parse_bhsp_psi('') is None and parse_bhsp_psi(None) is None
          and abs(parse_bhsp_psi('۷۳۰۰+۱۰۰۰') - 7300.0) < 1e-9)
    try:
        parse_bhsp_psi('abc')
        b1 = False
    except ChartInputError:
        pass
    rec('B1 D14 parse_bhsp_psi larger number', b1,
        '7300+1000 -> %r' % parse_bhsp_psi('7300+1000'))

    # ---------- B2: D10 MD interval -> BOTTOM end ---------------------------
    b2 = (parse_md_interval('1200.0-2816.0') == (1200.0, 2816.0)
          and parse_md_interval('3293.0') == (3293.0, 3293.0)
          and parse_md_interval('') == (None, None)
          and parse_md_interval(None) == (None, None))
    rec('B2 D10 parse_md_interval bottom end', b2,
        '1200.0-2816.0 -> %r' % (parse_md_interval('1200.0-2816.0'),))

    # ---------- B3: D8/D13 rheology_from_lab (bhct_down only) ---------------
    entries = rheology_from_lab(demo_lab_payloads())
    b3 = (set(entries) == {'Main', 'Tail', 'Lead'}
          and abs(entries['Main']['pv_cp'] - 120.0) < 1e-9
          and abs(entries['Main']['yp_lbf100ft2'] - 18.0) < 1e-9
          and abs(entries['Main']['gel_10_min'] - 8.0) < 1e-9
          and entries['Lead']['gel_10_min'] is None
          and all(e['source'] == 'phase7:bhct_down' for e in entries.values()))
    rec('B3 D8 rheology_from_lab bhct_down', b3,
        'slurries=%s Main=%s' % (sorted(entries),
                                 {k: entries['Main'][k]
                                  for k in ('pv_cp', 'yp_lbf100ft2',
                                            'gel_10_min')}))

    # ---------- B4: D9 mud PV/YP missing -> whole-set hydrostatic -----------
    figb, resb, warnb = build(mud=False)
    rec('B4 D9 hydro-only when mud PV/YP missing',
        resb.dyn is None
        and float(np.abs(resb.q_in - resb.q_out).max()) < 1e-9
        and any('HYDROSTATIC-ONLY' in w for w in warnb),
        'dyn=%s q-closure=%.2e (pumped-transit: WHP = hydrostatic imbalance)'
        % (resb.dyn, float(np.abs(resb.q_in - resb.q_out).max())))
    plt.close(figb)

    # ---------- B5: D8 slurry without fit -> frictionless + warning ---------
    partial = {k: v for k, v in SLURRY.items() if k != 'Main'}
    figc, resc, warnc = build(slurry=partial)
    rec('B5 D8 missing slurry fit warns',
        any(w.startswith('Main: no valid Bingham fit') for w in warnc)
        and resc.t_atcp is not None,
        '; '.join(w for w in warnc if w.startswith('Main'))[:70])
    plt.close(figc)

    # ---------- B6: D7 spacer PV/YP honored / missing warned ----------------
    fd_no_pv = demo_fluid_data()
    fd_no_pv['Spacer'] = dict(fd_no_pv['Spacer'],
                              **{'pv_cp': None, 'yp_lbf100ft2': None})
    figd, resd, warnd = build(fd_no_pv)
    fige, rese, warne = build()          # spacer WITH pv (demo)
    i_e = min(int(np.searchsorted(resd.t, resd.t_eod)),
              int(np.searchsorted(rese.t, rese.t_eod)))
    rec('B6 D7 spacer PV/YP honored',
        any('Spacer: no PV/YP' in w for w in warnd)
        and any('Pre Flush: no PV/YP' in w for w in warne)
        and not any('Spacer: no PV/YP' in w for w in warne)
        and float(np.abs(resd.whp[:i_e] - rese.whp[:i_e]).max()) > 1e-6,
        'dWHP=%.4f kpsi' % float(np.abs(resd.whp[:i_e] - rese.whp[:i_e]).max()))
    plt.close(figd)
    plt.close(fige)

    # ---------- B7: D14 BHSP shut-in segment anchors ------------------------
    # Documented balance: the well closes with the bottomhole pressure
    # anchored to BHSP; the SAME rise dP = BHSP - P_bottom appears on both
    # channels (string top and annulus at depth).  The final WHP is
    # BHSP minus the STRING COLUMN HEAD AT SHUT-IN — the string contains
    # the post-equalization fluids (some cement slumped in during the
    # tail), so it is below the mud-only value; that is the documented
    # physical balance, not a bug.
    figf, resf, warnf = build(bhsp=DEMO_BHSP)
    i_si = int(np.searchsorted(resf.t, resf.t_shutin))
    b7 = (resf.t_shutin is not None
          and resf.bottom_shutin_psi == 7300.0
          and resf.whp_final_psi > 0
          and resf.whp_final_psi <= 7300.0
          and abs((resf.whp[-1] - resf.whp[i_si])
                  - (resf.hydro[-1] - resf.hydro[i_si])) < 1e-6
          and resf.hydro[-1] <= 7.30 + 0.20
          and bool((np.abs(resf.q_in[i_si:]) < 1e-12).all())
          and bool((np.abs(resf.q_out[i_si:]) < 1e-12).all())
          and resf.t_marker == resf.t_shutin
          and resf.t_marker > resf.t_eod)
    rec('B7 D14 BHSP shut-in segment', b7,
        'BHSP=7300 WHP_final=%.1f psi (BHSP - string head at shut-in) '
        'uniform rise=%.3f kpsi marker=%.2f'
        % (resf.whp_final_psi or -1,
           resf.hydro[-1] - resf.hydro[i_si], resf.t_marker or -1))

    # ---------- B8: D11 geometry_from_hardware (CONFIRMED rule) -------------
    rows = demo_hardware_rows()
    geog, warng = geometry_from_hardware(rows, target_row=rows[1])
    b8 = (abs(geog.td_m - 3293.0) < 1e-9
          and abs(geog.pipe_id_in - 8.681) < 1e-9
          and abs(geog.pipe_od_in - 9.625) < 1e-9
          and abs(geog.hole_id_in - 12.25) < 1e-9
          and len(geog.ann_sections) == 2
          and abs(geog.ann_sections[0].z_top) < 1e-9
          and abs(geog.ann_sections[0].z_bot - 2816.0) < 1e-9
          and abs(geog.ann_sections[0].do_in - 12.415) < 1e-9
          and abs(geog.ann_sections[0].di_in - 9.625) < 1e-9
          and abs(geog.ann_sections[1].z_bot - 3293.0) < 1e-9
          and abs(geog.ann_sections[1].do_in - 12.25) < 1e-9
          and len(geog.pipe_sections) == 1
          and abs(geog.pipe_sections[0].id_in - 8.681) < 1e-9)
    rec('B8 D11 two-section annulus (owner-confirmed)', b8,
        geog.describe())

    # ---------- B10: D11 section-aware capacities ---------------------------
    chan_a = geog.chan_ann
    v_two = chan_a.total_volume()
    v_one = geog.td_m * math.pi * ((12.25 * 0.0254) ** 2
                                   - (9.625 * 0.0254) ** 2) / 4.0 * BBL_PER_M3
    deep_cap = chan_a.sections[0].cap_bbl_per_m      # deep section = bit size
    rec('B10 D11 section-aware capacity',
        abs(geog.total_ann_bbl - v_two) < 1e-9 and v_two > v_one * 1.001
        and abs(deep_cap - geog.v_ann_bbl_per_m) < 1e-12
        and abs(geog.total_pipe_bbl
                - geog.td_m * geog.v_pipe_bbl_per_m) < 1e-9,
        'two-section %.2f bbl > bit-only %.2f bbl (+%.1f%%)'
        % (v_two, v_one, 100.0 * (v_two / v_one - 1.0)))

    # ---------- B9: axis covers the full record incl. shut-in ---------------
    rec('B9 axis covers shut-in segment',
        figf.get_axes()[0].get_xlim()[1] >= resf.t[-1] - 1e-9,
        'xhi=%.2f record_end=%.2f' % (figf.get_axes()[0].get_xlim()[1],
                                      resf.t[-1]))
    plt.close(figf)

    # ---------- B13: absolute-BHSP shut-in endpoint + slurry remnant --------
    # ER-03 (2026-11-08, owner-authorized physics repair; root cause and
    # two-path proof: ER02R_FINDINGS.md in the ER-02R evidence ZIP).  The
    # D14/D15 shut-in law anchors the ABSOLUTE bottomhole pressure to BHSP
    # at the tracked shoe station.  ER-02 applied dP = BHSP - Hp_end on
    # top of the gel-held wellhead residual WHP0 and landed the endpoint
    # at BHSP + WHP0 (1378.62 psi on this demo); the original ER-02
    # fixture, its 1378.624 as-is selftest record and the original
    # failing 1256.7 assertion are preserved verbatim in the ER-02 /
    # ER-02R evidence ZIPs.  The check below is INDEPENDENT of the D14
    # implementation: the string-column head is recomputed from THIS
    # run's own reported state (slurry remnant + filled length + demo
    # composition) with own head math, and the endpoint must satisfy
    #   bottom = Hp_end + WHP_final == BHSP      (primary oracle)
    #   WHP_final == BHSP - Hp_end               (docstring identity)
    #   HYD_final == BHSP                        (annulus channel)
    # The legacy anchor 1256.7 +/- 1.5 psi belongs to an older demo
    # parameterization (~80.0 pcf demo mud weight; the frozen-era demo
    # ships 78.1 pcf): DATED LEGACY DATUM, preserved here — never a live
    # anchor.  The remnant is COMPUTED from the equalization (never
    # hard-coded) and reported for per-well cross-check.
    rem = resf.diag.get('shutin_string_slurry_m')
    i_si13 = int(np.searchsorted(resf.t, resf.t_shutin))
    whp0_kpsi = float(resf.whp[i_si13])
    b13_bhsp_psi = parse_bhsp_psi(DEMO_BHSP)
    b13_pipe_cap = math.pi / 4.0 * (4.276 * 0.0254) ** 2 / 0.15898730
    b13_va = resf.diag.get('vol_audit', {})
    b13_L_m = float(b13_va.get('Cp_end', 0.0)) / b13_pipe_cap
    b13_rho_sl = (float(demo_fluid_data()['Main']['effective_density'])
                  / 7.48052) * 119.826427
    b13_rho_md = (float(demo_fluid_data()['Displacement Fluid']
                        ['effective_density']) / 7.48052) * 119.826427
    b13_hp_psi = (b13_rho_sl * rem + b13_rho_md * (b13_L_m - rem)) \
        * 9.80665 * PA_TO_PSI
    b13_bottom_psi = b13_hp_psi + float(resf.whp_final_psi)
    b13_hydf_psi = float(resf.hydro[-1]) * 1000.0
    b13_tol = 1e-6 * max(1.0, abs(b13_bhsp_psi))
    b13 = (rem is not None and 400.0 <= rem <= 700.0
           and resf.whp_final_psi is not None
           and whp0_kpsi >= 0.0
           and abs(b13_bottom_psi - b13_bhsp_psi) < b13_tol
           and abs(float(resf.whp_final_psi)
                   - (b13_bhsp_psi - b13_hp_psi)) < b13_tol
           and abs(b13_hydf_psi - b13_bhsp_psi) < b13_tol
           and rem * b13_pipe_cap <= 141.4 + 1e-9
           and abs(resf.whp_final_psi - 1256.7) >= 1.5)
    rec('B13 absolute-BHSP shut-in endpoint + slurry remnant (ER03 repair)',
        b13,
        'independent bottom=Hp_end+WHP_final=%.6f psi == BHSP %.6f psi; '
        'WHP_final=%.6f == BHSP-Hp_end; HYD_final=%.6f == BHSP; '
        'remnant=%.1f m within [400,700] and <= slurry pumped; DATED '
        'LEGACY DATUM 1256.7 +/- 1.5 psi (older ~80.0 pcf demo mud '
        'weight) stays INVALID on the 78.1 pcf frozen-era demo — '
        're-adjudicate if it ever matches'
        % (b13_bottom_psi, b13_bhsp_psi, resf.whp_final_psi or -1,
           b13_hydf_psi, rem if rem else -1))

    # ---------- B11: D11b liner flow path (7" liner in 9 5/8") --------------
    rows_l = demo_hardware_rows_liner()
    geol, warnl = geometry_from_hardware(rows_l, target_row=rows_l[2],
                                         job_type='LNR 7"')
    b11 = (len(geol.pipe_sections) == 2
           and abs(geol.pipe_sections[0].z_bot - 2816.0) < 1e-9
           and abs(geol.pipe_sections[0].id_in - 4.276) < 1e-9
           and abs(geol.pipe_sections[1].id_in - 6.184) < 1e-9
           and len(geol.ann_sections) == 2
           and abs(geol.ann_sections[0].do_in - 8.681) < 1e-9
           and abs(geol.ann_sections[0].di_in - 5.0) < 1e-9
           and abs(geol.ann_sections[1].do_in - 8.5) < 1e-9
           and abs(geol.ann_sections[1].di_in - 7.0) < 1e-9
           and any('D11b liner flow path' in w for w in warnl))
    rec('B11 D11b LNR 7" path (return crosses into the 9 5/8" ID)', b11,
        geol.describe())

    # ---------- B11b: D11b tie-back path (through the old liner) ------------
    rows_t = demo_hardware_rows_tieback()
    geot, warnt = geometry_from_hardware(rows_t, target_row=rows_t[2],
                                         job_type='TIE BACK LNR 7"')
    b11b = (len(geot.pipe_sections) == 2
            and abs(geot.pipe_sections[0].z_bot - 2700.0) < 1e-9
            and abs(geot.pipe_sections[1].z_bot - 3293.0) < 1e-9
            and abs(geot.pipe_sections[1].id_in - 6.184) < 1e-9
            and len(geot.ann_sections) == 2
            and abs(geot.ann_sections[0].z_bot - 2816.0) < 1e-9
            and abs(geot.ann_sections[0].do_in - 8.681) < 1e-9
            and abs(geot.ann_sections[1].do_in - 8.5) < 1e-9
            and any('INSIDE the old' in w for w in warnt))
    rec('B11b D11b TIE BACK path (down inside the old liner)', b11b,
        geot.describe())

    # ---------- B12: D11c plug / squeeze jobs refused ------------------------
    b12 = True
    detail12 = []
    for jt in ('CMT PLUG', 'CMT SQUEEZE'):
        try:
            geometry_from_hardware(rows, target_row=rows[1], job_type=jt)
            b12 = False
            detail12.append('%s: NOT refused' % jt)
        except ChartInputError as exc:
            detail12.append('%s: refused' % jt)
    rec('B12 D11c plug/squeeze have no charts', b12, '; '.join(detail12))

    # ---------- B14/B15: D17 point-depth MD convention (owner Q13) ----------
    # The owner enters the DP row (and the Tie Back row) as a POINT depth
    # ("به صورت نقطه مثلا ۲۸۱۶.۰"): Top = surface implicit, Bottom = the
    # hanger / tie-in depth.  A point cell must yield the SAME geometry as
    # the '0.0-<depth>' interval and NO "assumed run from surface" warning.
    rows_p = demo_hardware_rows_liner()
    rows_p[1]['MD (m)'] = '2816.0'          # Drill Pipes: point = hanger
    geop, warnp = geometry_from_hardware(rows_p, target_row=rows_p[2],
                                         job_type='LNR 7"')
    b14 = (len(geop.pipe_sections) == 2
           and abs(geop.pipe_sections[0].z_bot - 2816.0) < 1e-9
           and abs(geop.pipe_sections[0].id_in - 4.276) < 1e-9
           and abs(geop.pipe_sections[1].z_bot - 3293.0) < 1e-9
           and abs(geop.pipe_sections[1].id_in - 6.184) < 1e-9
           and not any('assumed run from surface' in w for w in warnp))
    rec('B14 D17 DP point-depth row (silent, same LNR path)', b14,
        geop.describe())

    rows_tp = demo_hardware_rows_tieback()
    rows_tp[2]['MD (m)'] = '2700.0'         # Tie Back: point = tie-in
    geotp, warntp = geometry_from_hardware(rows_tp, target_row=rows_tp[2],
                                           job_type='TIE BACK LNR 7"')
    b15 = (len(geotp.pipe_sections) == 2
           and abs(geotp.pipe_sections[0].z_bot - 2700.0) < 1e-9
           and abs(geotp.pipe_sections[1].z_bot - 3293.0) < 1e-9
           and not any('assumed run from surface' in w for w in warntp))
    rec('B15 D17 Tie-Back point-depth row (silent, same path)', b15,
        geotp.describe())

    # ---------- B16: P1 put_bottom preserves the multi-chunk slug order -----
    # take_bottom returns chunks bottom->top; put_bottom must keep the
    # deepest-source chunk deepest in the destination (the pre-v1.2.2
    # sequential insert(0) reversed it).
    src = [['Mud', 1.0], ['Lead', 1.0]]      # bottom(TD) -> top column
    got = take_bottom(src, 1.5)              # takes Mud 1.0 then Lead 0.5
    dst = [['Disp', 5.0]]
    put_bottom(dst, got)                     # P1: Mud must stay deepest
    b16 = (len(dst) == 3
           and dst[0][0] == 'Mud' and abs(dst[0][1] - 1.0) < 1e-12
           and dst[1][0] == 'Lead' and abs(dst[1][1] - 0.5) < 1e-12
           and dst[2][0] == 'Disp' and abs(dst[2][1] - 5.0) < 1e-12
           and len(src) == 1 and abs(src[0][1] - 0.5) < 1e-12)
    rec('B16 P1 put_bottom keeps slug order (no reversal)', b16,
        'dst=' + str([[n, round(v, 3)] for n, v in dst]))

    # ---------- R1-R4: render-level checks ----------------------------------
    try:
        import tempfile
        from PIL import Image
        png = os.path.join(tempfile.mkdtemp(), 'r.png')
        save_png(figs, png)
        im = np.asarray(Image.open(png).convert('RGB')).astype(int)

        def hx(hexcol):
            return np.array([int(hexcol[i:i + 2], 16) for i in (1, 3, 5)])

        def count(col, tol=6):
            return int((np.abs(im - hx(col)).max(axis=2) <= tol).sum())

        rec('R1 render palette',
            count(PANEL_BG) > 40000 and count(GRID_GRAY) > 3000
            and count(ORANGE) > 300 and count(BLUE) > 30
            and count(GREEN) > 300 and count(RED) > 300 and count(NAVY) > 100,
            {c: count(c) for c in (PANEL_BG, GRID_GRAY, ORANGE, BLUE,
                                   GREEN, RED, NAVY)})

        spec_probe = JobChartsSpec(depth_m=3293.0, depth_unit='m')
        rec('R2 titles byte-exact',
            spec_probe.title_depth == 'Depth =  3293 m'
            and spec_probe.title_fluids == 'Fluids at   3293 m',
            '%r | %r' % (spec_probe.title_depth, spec_probe.title_fluids))

        # ---- D3 (DOC 51R v2): R3/R4 replaced by SEMANTICALLY LOCATED
        # checks.  The v1.4.3 checks were brittle pixel heuristics (a fixed
        # 80-row threshold that cannot tell a short spurious red line from
        # a legitimate one, and a bare "2 columns" count that never checks
        # WHERE the event verticals stand).  Located replacements:
        ax1 = figs.get_axes()[0]
        red_lines_c1 = [ln for ln in ax1.get_lines()
                        if len(ln.get_xdata()) > 1
                        and str(ln.get_color()).lower() == RED.lower()]
        rec('R3 C1 red legend-only (located)', not red_lines_c1,
            'red data lines on C1: %d' % len(red_lines_c1))

        # located pixel control: zero red pixels inside the C1 axes box
        # minus the legend area (png at save dpi; artist bbox scaled).
        try:
            bb = ax1.get_window_extent()
            sc = im.shape[0] / float(figs.get_size_inches()[1] * figs.dpi)
            top = int(round(im.shape[0] - bb.y1 * sc))
            bot = int(round(im.shape[0] - bb.y0 * sc))
            left = int(round(bb.x0 * sc))
            right = int(round(bb.x1 * sc))
            leg = ax1.get_legend()
            lb = leg.get_window_extent()
            ltop = int(round(im.shape[0] - lb.y1 * sc))
            lbot = int(round(im.shape[0] - lb.y0 * sc))
            lleft = int(round(lb.x0 * sc))
            lright = int(round(lb.x1 * sc))
            sub = im[top:bot, left:right]
            redmask = np.abs(sub - hx(RED)).max(axis=2) <= 6
            redmask[max(0, ltop - top):max(0, lbot - top),
                    max(0, lleft - left):max(0, lright - left)] = False
            rec('R3b C1 red pixels outside legend (located)',
                int(redmask.sum()) == 0,
                'red px in C1 minus legend: %d' % int(redmask.sum()))
        except Exception as exc:                      # noqa: BLE001
            rec('R3b C1 red pixels outside legend (located)', False,
                'bbox control failed: %r' % (exc,))

        ev_expected = sorted(float(e) for e in (res2.t_atcp, res2.t_eod)
                             if e is not None)
        mk_expected = ([] if res2.t_marker is None
                       else [float(res2.t_marker)])

        def vtimes(ax, color):
            out = []
            for ln in ax.get_lines():
                xd = np.asarray(ln.get_xdata(), float)
                if (xd.size == 2 and xd[0] == xd[1]
                        and str(ln.get_color()).lower() == color.lower()):
                    out.append(float(xd[0]))
            return sorted(out)

        ok4, detail4 = True, []
        for i, ax in enumerate(figs.get_axes()):
            g, m = vtimes(ax, EVENT_GREEN), vtimes(ax, MARKER_GRAY)
            if i == 0:
                if g or m:
                    ok4 = False
                    detail4.append('C1 carries event verticals %r/%r' % (g, m))
            else:
                if g != ev_expected:
                    ok4 = False
                    detail4.append('ax%d green %r != %r' % (i, g, ev_expected))
                if m != mk_expected:
                    ok4 = False
                    detail4.append('ax%d gray %r != %r' % (i, m, mk_expected))
        rec('R4 event verticals located at engine events', ok4,
            '; '.join(detail4) or ('events=%r marker=%r'
                                   % (ev_expected, mk_expected)))
    except ImportError:
        rec('R1-R4 render checks', True, 'SKIPPED — PIL not available')

    ok_all = all(r[1] for r in results)
    if verbose:
        for name, ok, detail in results:
            print('%-38s %s  %s' % (name, 'PASS' if ok else 'FAIL', detail))
        print('%d/%d PASS' % (sum(r[1] for r in results), len(results)))
    return ok_all


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        matplotlib.use('Agg', force=True)
        if not run_selftest():
            raise SystemExit(1)
        raise SystemExit(0)
    matplotlib.use('Agg', force=True)
    fig, res, warn = build_three_charts(
        demo_fluid_data(), demo_geometry(),
        mud_pv_yp=DEMO_MUD_PV_YP,
        slurry_rheology=demo_slurry_rheology(),
        bhsp=DEMO_BHSP)
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, 'job_charts_from_fluid_data.png')
    save_png(fig, out)
    print('wrote', out)
    print('EOD=%.3f min  ATCP=%s  hydro: %.3f -> %.3f kpsi'
          % (res.t_eod,
             'NA' if res.t_atcp is None else '%.3f' % res.t_atcp,
             res.hydro0_kpsi, res.final_hydro_kpsi))
    print('shut-in: t=%s  BHSP=%s psi  WHP_final=%s psi'
          % ('NA' if res.t_shutin is None else '%.2f' % res.t_shutin,
             'NA' if res.bottom_shutin_psi is None else '%.0f'
             % res.bottom_shutin_psi,
             'NA' if res.whp_final_psi is None else '%.1f'
             % res.whp_final_psi))
    print('warnings:')
    for w in warn:
        print('  -', w)
