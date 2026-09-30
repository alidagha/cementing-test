#!/usr/bin/env python3
"""
bhct_helper.py — BHCT / Squeeze temperature helper for the Cementing Report Engine.
====================================================================================
IH-15 (owner-approved integration of the formerly-draft module
`bhct_helper_phase7_draft.py`). STANDALONE and ADDITIVE: imports nothing from
the project, mutates nothing, and the read-only engine (engineering_tools.py,
materials_db.py) plus test_regression_guardrails.py stay untouched.

Source: i-Handbook v0.4.6 (Schlumberger), page `Cementing/BHC and Squeeze Temperatures`,
function block @0x4AD7B0..0x4AD8E9, fully reconstructed in
`download/i-handbook_extracted/re/EXTRACTION_3ITEMS.md` (ITEM A), including the EXE's
own help-text variable legend:

    PHBCT    = Predicted BH Circulating Temperature, degF
    TVD      = True Vertical Depth, ft
    PsTG     = Pseudo temperature gradient, degF/100ft
    MaxRBHST = Maximum recorded BH Static Temp, degF
    PSqT     = Predicted BH Squeeze Temperature, degF

Closed forms (constants pinned to .rdata VAs):

    PsTG = (MaxRBHST - 80) * 100 / TVD                    [degF/100ft]

    BHCT  (TVD >= 10000 ft, API Spec 10B style):
        PHBCT = 80 + (0.006061   * TVD * PsTG - 10.0915) / (1 - 1.505e-05 * TVD)

    Squeeze (TVD <  10000 ft, CONTINUOUS PUMPING method only):
        PSqT  = 80 + (0.00764951 * TVD * PsTG - 8.2021 ) / (1 - 8.07e-06 * TVD)

Constructor defaults @0x4AD0F8: PsTG=1.8, MaxRBHST=260 degF, TVD=10000 ft,
surface-temp base 80.0 degF @0xDB4DF0.

INTEGRATION STATUS (IH-15, wired in upload/phase_7_lab.py):
    * `suggest_bhct` is imported by Phase VII; the well `geo_tvd` stored in
      METERS is converted to feet with the pinned factor M_TO_FT = 3.28084
      before entering these correlations.
    * The suggestion is advisory UI only: the manual BHCT entry and the
      lab_temperature_valid(bhct, bhst) check in engineering_tools.py:22 are
      untouched, and nothing here can hard-block a report.
"""

SURFACE_TEMP_F = 80.0          # 0xDB4DF0
BHCT_K1 = 0.006061             # 0xDB4DC8  (TVD >= 10000 ft)
BHCT_K2 = 1.505e-05            # 0xDB4DC0
BHCT_C = 10.0915               # 0xDB4DE8
SQZ_K1 = 0.00764951            # 0xDB4DD0  (TVD < 10000 ft)
SQZ_K2 = 8.07e-06              # 0xDB4DB8
SQZ_C = 8.2021                 # 0xDB4DE0
REGIME_SPLIT_FT = 10000.0      # 0xDB4E08
DEFAULT_PSTG = 1.8             # 0xDB4DD8
DEFAULT_MAXRBHST = 260.0       # constructor @0x4AD0F8
DEFAULT_TVD = 10000.0

# IH-15 wiring constant: the app's `geo_tvd` (Phase II/III) is stored in METERS;
# the i-Handbook correlations above take FEET. Pinned here as the single source
# of truth for the Phase VII conversion so UI code and self-test agree.
M_TO_FT = 3.28084


def pseudo_gradient(max_rbhest_f: float, tvd_ft: float) -> float:
    """PsTG (degF/100ft) from the maximum recorded BH static temperature.

    Mirrors 0x4AD810..0x4AD823:  PsTG = (MaxRBHST - 80) * 100 / TVD.
    """
    if tvd_ft <= 0:
        raise ValueError("TVD must be greater than 0 ft")
    return (float(max_rbhest_f) - SURFACE_TEMP_F) * 100.0 / float(tvd_ft)


def bhct(tvd_ft: float, pstg: float) -> float:
    """Predicted BH circulating temperature, degF. Valid for TVD >= 10,000 ft.

    The i-Handbook page validates: 'The TVD must be greater than 10,000.0 ft.'
    (below 10,000 ft its help says: use CemCADE).
    """
    tvd_ft = float(tvd_ft)
    if tvd_ft < REGIME_SPLIT_FT:
        raise ValueError("The TVD must be greater than 10,000.0 ft (use CemCADE below)")
    den = 1.0 - BHCT_K2 * tvd_ft
    if den <= 0:
        raise ValueError("TVD too large: BHCT correlation denominator is non-positive")
    return SURFACE_TEMP_F + (BHCT_K1 * tvd_ft * float(pstg) - BHCT_C) / den


def squeeze_temperature(tvd_ft: float, pstg: float) -> float:
    """Predicted BH squeeze temperature, degF. Valid for TVD < 10,000 ft and
    ONLY for the Continuous Pumping Squeeze method (per the EXE help text).
    """
    tvd_ft = float(tvd_ft)
    if tvd_ft >= REGIME_SPLIT_FT:
        raise ValueError("The TVD must be less than 10,000.0 ft (squeeze page)")
    den = 1.0 - SQZ_K2 * tvd_ft
    if den <= 0:
        raise ValueError("TVD out of range: squeeze correlation denominator is non-positive")
    return SURFACE_TEMP_F + (SQZ_K1 * tvd_ft * float(pstg) - SQZ_C) / den


def suggest_bhct(tvd_ft: float, max_rbhest_f: float = None, pstg: float = None) -> dict:
    """One-call helper: derive PsTG from MaxRBHST (or accept a known gradient),
    then return the regime-appropriate predicted temperature.

    Returns {'pstg_degF_per_100ft', 'tvd_ft', 'kind', 'temp_degF'}.
    kind = 'BHCT' for TVD >= 10,000 ft, 'SQUEEZE' below (as the i-Handbook
    pages split the two correlations at exactly 10,000 ft).
    """
    tvd_ft = float(tvd_ft)
    if tvd_ft <= 0:
        raise ValueError("TVD must be greater than 0 ft")
    if pstg is None:
        if max_rbhest_f is None:
            raise ValueError("provide either max_rbhest_f or pstg")
        pstg = pseudo_gradient(max_rbhest_f, tvd_ft)
    if tvd_ft >= REGIME_SPLIT_FT:
        return {"pstg_degF_per_100ft": pstg, "tvd_ft": tvd_ft,
                "kind": "BHCT", "temp_degF": bhct(tvd_ft, pstg)}
    return {"pstg_degF_per_100ft": pstg, "tvd_ft": tvd_ft,
            "kind": "SQUEEZE", "temp_degF": squeeze_temperature(tvd_ft, pstg)}


def _self_test() -> None:
    """Reproduce EXTRACTION_3ITEMS.md table A.3 (reconstructed-code validation),
    plus the IH-15 wiring checks (regime guards and the meters->feet factor)."""
    cases = [
        # (tvd, pstg, kind, expected_degF)
        (10_000, 1.80, "BHCT", 196.5),
        (12_000, 1.50, "BHCT", 200.8),
        (15_000, 1.60, "BHCT", 254.8),
        (18_000, 1.50, "BHCT", 290.6),
        (20_000, 1.80, "BHCT", 377.7),
        (5_000, 1.80, "SQUEEZE", 143.2),
        (8_000, 1.80, "SQUEEZE", 189.0),
    ]
    for tvd, pstg, kind, expected in cases:
        got = suggest_bhct(tvd, pstg=pstg)
        assert got["kind"] == kind, (tvd, got)
        assert abs(got["temp_degF"] - expected) < 0.15, (tvd, got, expected)
        print(f"  TVD {tvd:>6,} ft  PsTG {pstg:.2f}  {kind:<7} "
              f"{got['temp_degF']:7.1f} degF  (expect {expected})")
    # regime guards
    for bad in (lambda: bhct(9_999, 1.8), lambda: squeeze_temperature(10_001, 1.8)):
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("regime guard failed")
    # default pair sanity: 260 degF @ 10,000 ft -> PsTG 1.8 (constructor defaults)
    assert abs(pseudo_gradient(DEFAULT_MAXRBHST, DEFAULT_TVD) - DEFAULT_PSTG) < 1e-9
    # IH-15 wiring sanity: the app's geo_tvd is meters -> regime must flip
    # across the 10,000 ft split exactly as the converted depth dictates
    # (3000 m is the Phase II/III default -> below the split -> SQUEEZE;
    # 3100 m (the guardrail drift vector) -> just above it -> BHCT).
    tvd_ft_3000m = 3000.0 * M_TO_FT
    tvd_ft_3100m = 3100.0 * M_TO_FT
    got_3000 = suggest_bhct(tvd_ft_3000m, max_rbhest_f=200.0)
    got_3100 = suggest_bhct(tvd_ft_3100m, max_rbhest_f=200.0)
    assert got_3000["kind"] == "SQUEEZE", got_3000
    assert got_3100["kind"] == "BHCT", got_3100
    assert abs(tvd_ft_3000m - 9842.52) < 0.01, tvd_ft_3000m
    print(f"  meters->feet wiring: 3000 m = {tvd_ft_3000m:,.2f} ft -> {got_3000['kind']} "
          f"{got_3000['temp_degF']:.1f} degF; 3100 m = {tvd_ft_3100m:,.2f} ft -> "
          f"{got_3100['kind']} {got_3100['temp_degF']:.1f} degF")
    print("  all BHCT self-tests passed")


if __name__ == "__main__":
    print("bhct_helper.py — self test against EXTRACTION_3ITEMS.md table A.3:")
    _self_test()
