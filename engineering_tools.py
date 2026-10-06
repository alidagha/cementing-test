"""
Centralized Engineering Math, String Parsing, and Conversion Utilities.
Enforces the DRY (Don't Repeat Yourself) principle across all project phases.
Includes the validated mass-balance slurry engine from NIDC CMT Calculator 03-3.xls.
"""

import re
import math
from numbers import Real
from decimal import Decimal, ROUND_HALF_UP
import materials_db


CEMENT_SACK_LB = 110.0
WATER_DENSITY_PCF = 62.4
GAL_PER_CUFT = 7.48051945
BBL_GAL = 42.0
BBL_TO_CUFT = BBL_GAL / GAL_PER_CUFT
WATER_LB_PER_GAL = WATER_DENSITY_PCF / GAL_PER_CUFT
LAB_SCALE = 1058.0

LAB_THICKENING_ENDPOINT = "70 Bc"


def lab_review_signature(qc, grid):
    """Identify precisely the QC readings and lab rows confirmed by an operator."""
    from project_state import fingerprint
    return fingerprint({"qc": {key: value for key, value in qc.items()
                               if key not in ("reviewed", "review_signature", "thickening_endpoint")},
                        "grid": grid})


def lab_temperature_valid(bhct, bhst):
    """Reject nonfinite temperatures and a circulating value above static."""
    try:
        if isinstance(bhct, bool) or isinstance(bhst, bool):
            return False
        circulating, static = float(bhct), float(bhst)
        return math.isfinite(circulating) and math.isfinite(static) and circulating <= static
    except (TypeError, ValueError, OverflowError):
        return False


def thickening_time_valid(value) -> bool:
    """F2 (P1-02, owner-approved 2026-09-29): Thickening Time must be a
    well-formed HH:MM value INSIDE the measurable envelope. '00:00' is not a
    measurable thickening time and any value ABOVE 24 hours is outside
    lab-report plausibility — both must fail this gate exactly like a
    malformed format (BUG-09 only enforced the HH:MM shape, so '00:00' and
    '99:59' sailed through to the Word report verbatim). 24:00 itself is the
    inclusive upper bound; the owner spec rejects values above 24 hours.
    Deliberately NO digit normalization here: it mirrors the pre-existing
    format regex's strictness on what the operator literally typed."""
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,2}:[0-5]\d", text):
        return False
    hours, minutes = text.split(":")
    total_minutes = int(hours) * 60 + int(minutes)
    return 0 < total_minutes <= 24 * 60

# ==============================================================================
# 1. CORE NUMERIC, STRING & HYDRAULIC UTILITIES
# ==============================================================================

def round_half_up(val, decimals: int = 1) -> float:
    """Commercial half-up rounding; reject invalid/non-finite values."""
    if val is None:
        return 0.0
    try:
        d = Decimal(str(val))
        if not d.is_finite():
            raise ValueError("A finite number is required")
        fmt = '1' if decimals == 0 else ('0.' + '0' * decimals)
        return float(d.quantize(Decimal(fmt), rounding=ROUND_HALF_UP))
    except Exception as exc:
        raise ValueError(f"Invalid number for rounding: {val!r}") from exc

def clean_number(val) -> float:
    """Parse scalar finite numbers, Persian digits and unambiguous grouping."""
    if val is None:
        return 0.0
    if not isinstance(val, (str, Real)):
        raise ValueError("Expected a single numeric value")
    if isinstance(val, Real):
        result = float(val)
        if not math.isfinite(result):
            raise ValueError("A finite number is required")
        return result
    s = str(val).strip()
    s = normalize_digits(s)
    if re.fullmatch(r'[+-]?0,\d{3}', s):
        raise ValueError(f"Ambiguous comma in number {s!r}; use a decimal point")
    if re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d+)?', s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    s = s.replace("/", ".")
    try:
        result = float(s)
        if not math.isfinite(result):
            raise ValueError("A finite number is required")
        return result
    except ValueError as exc:
        if "finite" in str(exc):
            raise
        raise ValueError(f"Invalid numeric value: {val!r}") from exc


def normalize_digits(value: str) -> str:
    value = str(value).replace("٫", ".")
    for persian, arabic, ascii_digit in zip("۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩", "0123456789"):
        value = value.replace(persian, ascii_digit).replace(arabic, ascii_digit)
    return value


def require_nonnegative_number(value, label="Quantity") -> float:
    """Validate a dosage so malformed project text cannot become zero."""
    if value is None:
        raise ValueError(f"{label}: enter a numeric dosage")
    if isinstance(value, str):
        token = normalize_digits(value).strip()
        if not re.fullmatch(r'[+-]?(?:\d+(?:[.,]\d+)?|\.\d+|\d{1,3}(?:,\d{3})+(?:\.\d+)?)', token):
            raise ValueError(f"{label}: enter a valid numeric dosage")
    result = clean_number(value)
    if result < 0:
        raise ValueError(f"{label}: dosage cannot be negative")
    return result

def validate_cement_parameters(params):
    """Enforce the existing Phase V input bounds before status or calculation."""
    sg = require_nonnegative_number(params.get("cmt_sg", 3.20), "Cement SG")
    if not 2.5 <= sg <= 3.5:
        raise ValueError("Cement SG must be within 2.5–3.5")
    require_nonnegative_number(params.get("dead_vol"), "Dead volume")
    if not params.get("auto_calc", True):
        yield_value = require_nonnegative_number(params.get("yield"), "Manual yield")
        if yield_value < 0.001:
            raise ValueError("Manual yield must be at least 0.001 cuft/sk")
        require_nonnegative_number(params.get("mix_water"), "Manual mix water")


def validate_lab_collection_results(qc):
    """Require measured collection angles and independent surface-sample hours."""
    for field, label in (("free_water", "Free Water (90°)"),
                         ("free_water_45", "Free Water (45°)"),
                         ("surface_hardened_hours", "Surface Sample Hours")):
        if isinstance(qc.get(field), bool):
            raise ValueError(f"{label}: enter a finite nonnegative number")
        require_nonnegative_number(qc.get(field), label)


def validate_lab_masses(grid):
    """Keep unfinished lab masses as drafts; only finite nonnegative masses pass."""
    for number, (_, row) in enumerate(grid.iterrows(), start=1):
        require_nonnegative_number(row.get("Mass"), f"Lab row {number} mass")


def parse_effective_numeric(val_str: str, default: float = 0.0) -> float:
    """
    Extracts the operational arithmetic mean from text ranges (e.g. '80-82' -> 81.0, '115/118' -> 116.5).
    Guarantees crash-free execution for hydraulic calculations.

    FIX: Splits on '-' first to treat it strictly as a range separator,
    then extracts a non-negative number from each segment independently.

    FIX (confirmed via test): a single leading "-" (e.g. "-118", a plausible
    typo for "118" on a field like Mud Weight that can never legitimately be
    negative) used to be silently parsed as an empty-to-118 range, returning
    +118.0 with no sign of anything wrong — the text field still visibly
    shows "-118" while every calculation silently uses +118.0. Now detects
    "starts with exactly one '-' and has no other '-' " as a genuine signed
    number and returns it AS NEGATIVE, so a physically-impossible value stays
    visibly wrong (e.g. propagates into an obviously-broken negative
    pressure) instead of silently becoming a plausible positive one. A real
    range ("80-82") is unaffected — it does not start with "-".
    """
    if val_str is None:
        return default
    s = normalize_digits(val_str).strip().replace("/", "-")
    if not s:
        return default
    if s.startswith("-"):
        # BUG-22 (runtime-confirmed): "-80-82" (a leading negative PLUS a
        # range) used to fall through to the unsigned range branch and
        # silently return +81.0 - the visible minus sign was stripped and
        # every downstream calculation happily used a plausible positive
        # value. Keep the documented "stay visibly wrong" convention:
        # parse the number(s) after the sign and return the NEGATED result,
        # so a physically impossible input propagates as obviously broken.
        m = re.findall(r"\d*\.\d+|\d+", s)
        if not m:
            return default
        if len(m) == 1:
            return -float(m[0])
        return -sum(float(x) for x in m) / len(m)
    segments = [seg for seg in s.split("-") if seg.strip()]
    nums = []
    for seg in segments:
        m = re.findall(r"\d*\.\d+|\d+", seg)
        if m:
            nums.append(float(m[0]))
    if not nums:
        return default
    return sum(nums) / len(nums)




def safe_float(value, default: float = 0.0):
    """F3 (P1-03, owner-approved 2026-09-29): crash-proof float coercion for
    the report payload layer. float() raises ValueError on junk like 'abc'
    and float('') on blanks — deep inside Word-report construction that means
    an uncaught crash screen. safe_float returns `default` instead; pass
    default=None at the call site when 'unreadable' must stay distinguishable
    from a real 0.0 (phase_10's unreadable-volume gate does exactly that).
    Handles Persian/Arabic digits like every other numeric reader in this app
    (Section 5 digit invariant), blank/whitespace strings, numpy scalars;
    bools are rejected as junk rather than coerced to 1.0/0.0."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = normalize_digits(value).strip()
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _positive_density_values(value):
    """Validate every density component before choosing a calculation basis."""
    raw = normalize_digits(value).strip()
    pattern = r'(?:\d+(?:\.\d*)?|\.\d+)(?:\s*[-/]\s*(?:\d+(?:\.\d*)?|\.\d+))*'
    if not re.fullmatch(pattern, raw):
        raise ValueError(f"Invalid density {value!r}; enter a positive pcf value or range")
    numbers = [float(part.strip()) for part in re.split(r'[-/]', raw)]
    if not all(math.isfinite(n) and n > 0 for n in numbers):
        raise ValueError(f"Invalid density {value!r}; every density must be positive and finite")
    return numbers


def require_preflush_material_name(value) -> str:
    """A Custom selector is unfinished until an actual fluid name is entered."""
    if not isinstance(value, str) or not value.strip() or value.strip() == "Custom":
        raise ValueError("Phase IV: Pre Flush: enter a material name in Phase IV or Phase VI before export")
    return value


def require_positive_density(value) -> float:
    """Reject a malformed or negative density rather than substituting 80 pcf."""
    numbers = _positive_density_values(value)
    return sum(numbers) / len(numbers)


def require_bhsp_density(value) -> float:
    """Use the upper density only for automatic hydrostatic pressure."""
    return max(_positive_density_values(value))

def parse_fractional_size(size_str: str) -> float:
    """Converts API tubular sizes like '9 5/8' or '13 3/8' to decimal float for geometric checks."""
    if not size_str:
        return 0.0
    s = str(size_str).strip().replace('"', '').replace('-', ' ')
    parts = s.split()
    try:
        if len(parts) == 1:
            if "/" in parts[0]:
                num, den = parts[0].split("/")
                return float(num) / float(den)
            return float(parts[0])
        elif len(parts) == 2 and "/" in parts[1]:
            whole = float(parts[0])
            num, den = parts[1].split("/")
            return whole + (float(num) / float(den))
    except Exception:
        return 0.0
    return 0.0

def require_positive_pump_rate(rate_str) -> float:
    """Validate the whole entered value/range before using its minimum."""
    value = normalize_digits(rate_str).strip()
    if not re.fullmatch(r'\+?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*-\s*\+?(?:\d+(?:\.\d*)?|\.\d+))?', value):
        raise ValueError(f"Invalid pump rate {rate_str!r}; enter a positive number or range such as 3-5 bpm")
    numbers = [float(part.strip()) for part in value.split("-")]
    if not all(math.isfinite(number) and number > 0 for number in numbers):
        raise ValueError(f"Invalid pump rate {rate_str!r}; both rates must be positive and finite")
    return min(numbers)

def format_to_hr_mm(total_minutes: float) -> str:
    """Convert a finite, nonnegative duration to HH:MM."""
    total_minutes = clean_number(total_minutes)
    if total_minutes < 0:
        raise ValueError("Duration cannot be negative")
    total_seconds = int(round(total_minutes * 60))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


# ==============================================================================
# 2. PHYSICAL CONSTANTS & ADDITIVE PROPERTY LOOKUPS (CUSTOM SG DATABASE)
# ==============================================================================

# Standard additive powder densities in lb/ft3 (pcf) calculated from SG * 62.4.
# Keys are lowercased Material Type / brand Name strings from the master
# taxonomy (materials_db.MATERIAL_TAXONOMY). Every brand under the same
# Material Type shares that category's generic SG UNLESS called out below as
# an exception (Extender: Bentonite vs Micro Silica; Weighting Agent: Hidense
# vs Micro Max) — per confirmed material-list update.
DEFAULT_POWDER_DENSITIES_PCF = {
    # Cement (brand-specific SG, per confirmed material-list update)
    "cement g delijan": 3.20 * 62.4,   # 199.680 pcf
    "cement d delijan": 3.16 * 62.4,   # 197.184 pcf
    "cement": 3.20 * 62.4,

    # F.L. Controller (SG = 1.36, generic for all brands)
    "flc": 1.36 * 62.4,             # 84.864 pcf
    "f.l. controller": 1.36 * 62.4,
    "f.l.controller": 1.36 * 62.4,  # legacy spelling (pre master-list update), kept for old saved projects
    "o-uniflc5": 1.36 * 62.4,
    "j-flc 320": 1.36 * 62.4,
    "pk-fl 8": 1.36 * 62.4,
    "loloss-169": 1.36 * 62.4,
    "phs-c32": 1.36 * 62.4,
    "cfl-109": 1.36 * 62.4,
    "pk-fl7": 1.36 * 62.4,
    "se-f04": 1.36 * 62.4,

    # Dispersant (SG = 1.43, generic for all brands)
    "dispersant": 1.43 * 62.4,       # 89.232 pcf
    "o-cfr2": 1.43 * 62.4,
    "o-cfr4": 1.43 * 62.4,
    "o-cfr8": 1.43 * 62.4,
    "o-cfr3": 1.43 * 62.4,
    "jp-450": 1.43 * 62.4,
    "psh-c21": 1.43 * 62.4,
    "jp-cf410s": 1.43 * 62.4,
    "j-d 220": 1.43 * 62.4,
    "se-d01": 1.43 * 62.4,
    "pk-dis2": 1.43 * 62.4,

    # L.T. / H.T. Retarder (SG = 1.23, generic for all brands)
    "retarder": 1.23 * 62.4,         # 76.752 pcf
    "l.t. retarder": 1.23 * 62.4,
    "h.t. retarder": 1.23 * 62.4,
    "l.t.retarder": 1.23 * 62.4,     # legacy spelling (pre master-list update), kept for old saved projects
    "h.t.retarder": 1.23 * 62.4,     # legacy spelling (pre master-list update), kept for old saved projects
    "o-r12": 1.23 * 62.4,
    "o-r5": 1.23 * 62.4,
    "j-r120": 1.23 * 62.4,
    "se-r02": 1.23 * 62.4,
    "pk-ret 5": 1.23 * 62.4,

    # Boric Acid / Retarder Aid (SG = 1.43)
    "boric acid": 1.43 * 62.4,       # 89.232 pcf
    "retarder aid": 1.43 * 62.4,

    # Accelerator / Cacl2 (SG = 1.75)
    "cacl2": 1.75 * 62.4,            # 109.200 pcf
    "cacl": 1.75 * 62.4,
    "accelerator": 1.75 * 62.4,

    # Anti Settling (SG = 2.53)
    "anti settling": 2.53 * 62.4,    # 157.872 pcf
    "anti-settling": 2.53 * 62.4,
    "sas": 2.53 * 62.4,

    # CS Stabilizer / Silica Flour (SG = 2.65)
    "silica flour": 2.65 * 62.4,     # 165.360 pcf
    "cs stabilizer": 2.65 * 62.4,

    # Extender: Bentonite (SG = 2.65) vs Micro Silica (SG = 2.20) — distinct, confirmed exception
    "bentonite": 2.65 * 62.4,        # 165.360 pcf
    "bentonite (wet)": 2.65 * 62.4,
    "micro silica": 2.20 * 62.4,     # 137.280 pcf

    # Weighting Agent: Hidense (SG = 5.20) vs Micro Max (SG = 4.80) — distinct, confirmed exception
    "hidense": 5.20 * 62.4,          # 324.480 pcf
    "micro max": 4.80 * 62.4,        # 299.520 pcf
    "micromax": 4.80 * 62.4,

    # Light Weight (SG = 0.75, generic for Light Weight & Cenosphere)
    "light weight": 0.75 * 62.4,     # 46.800 pcf
    "lightweight": 0.75 * 62.4,
    "cenosphere": 0.75 * 62.4,

    # Nacl / Salt (SG = 2.16)
    "nacl": 2.16 * 62.4,             # 134.784 pcf
    "salt": 2.16 * 62.4,

    # Historical reference densities (not part of the active Phase V/VII material list)
    "diacel d": 131.0,               # 131.0 pcf
    "pcf (wet)": 87.0,               # 87.0 pcf
    "pcf (dry)": 155.0,              # 155.0 pcf
    "barite": 4.20 * 62.4,           # 262.080 pcf
    "limestone": 2.69 * 62.4,        # 167.856 pcf
    "ferobar": 5.00 * 62.4           # 312.000 pcf
}

# Liquid density and lab mass factor share the water-density/unit basis.
DEFAULT_LIQUID_PROPERTIES = {
    # Anti Foam (SG = 1.00, generic for all brands)
    "anti foam": {"density_ppg": 1.00 * WATER_LB_PER_GAL, "lab_factor": 1.00 * WATER_LB_PER_GAL / CEMENT_SACK_LB},
    "defoamer": {"density_ppg": 1.00 * WATER_LB_PER_GAL, "lab_factor": 1.00 * WATER_LB_PER_GAL / CEMENT_SACK_LB},
    "ta-47": {"density_ppg": 1.00 * WATER_LB_PER_GAL, "lab_factor": 1.00 * WATER_LB_PER_GAL / CEMENT_SACK_LB},

    # Anti Gas Migration (SG = 1.05, generic for all brands)
    "anti gas migration": {"density_ppg": 1.05 * WATER_LB_PER_GAL, "lab_factor": 1.05 * WATER_LB_PER_GAL / CEMENT_SACK_LB}, # 8.759 ppg
    "anti gas mig.": {"density_ppg": 1.05 * WATER_LB_PER_GAL, "lab_factor": 1.05 * WATER_LB_PER_GAL / CEMENT_SACK_LB},
    "o-gas block": {"density_ppg": 1.05 * WATER_LB_PER_GAL, "lab_factor": 1.05 * WATER_LB_PER_GAL / CEMENT_SACK_LB},
    "pk-gas7": {"density_ppg": 1.05 * WATER_LB_PER_GAL, "lab_factor": 1.05 * WATER_LB_PER_GAL / CEMENT_SACK_LB},
    "jp-620l": {"density_ppg": 1.05 * WATER_LB_PER_GAL, "lab_factor": 1.05 * WATER_LB_PER_GAL / CEMENT_SACK_LB},
    "se-g10": {"density_ppg": 1.05 * WATER_LB_PER_GAL, "lab_factor": 1.05 * WATER_LB_PER_GAL / CEMENT_SACK_LB},
    "pk-gas8": {"density_ppg": 1.05 * WATER_LB_PER_GAL, "lab_factor": 1.05 * WATER_LB_PER_GAL / CEMENT_SACK_LB},

    # Micro Block / Liquid Extender (SG = 1.32)
    "micro block": {"density_ppg": 1.32 * WATER_LB_PER_GAL, "lab_factor": 1.32 * WATER_LB_PER_GAL / CEMENT_SACK_LB},         # 11.011 ppg
    "liquid extender": {"density_ppg": 1.32 * WATER_LB_PER_GAL, "lab_factor": 1.32 * WATER_LB_PER_GAL / CEMENT_SACK_LB}
}

def is_salt_additive(material_type: str = "", material_name: str = "") -> bool:
    """Recognize the app's NaCl/SALT entries, without substring guesses.

    Both fields are accepted for legacy/custom rows whose type is Nacl but
    whose display name is different. Other salts are not assumed to be NaCl.
    """
    return any(str(value).strip().casefold() in {"nacl", "salt"}
               for value in (material_type, material_name))


def resolve_physical_state(material_type: str, user_state) -> str:
    """Use the same legacy/custom-material fallback in formulation and lab."""
    state = str(user_state).strip().title() if isinstance(user_state, str) else ""
    if state in ("Powder", "Liquid"):
        return state
    return materials_db.get_state_for_material_type(material_type)


# Nelson & Guillot, Well Cementing: dissolved NaCl absolute volume at
# reference conditions. Concentration is % BWOW, not weight % of brine.
DISSOLVED_NACL_GAL_PER_LB = (
    (2.0, 0.0371), (4.0, 0.0378), (6.0, 0.0384), (8.0, 0.0390),
    (10.0, 0.0394), (12.0, 0.0399), (14.0, 0.0403), (16.0, 0.0407),
    (18.0, 0.0412), (20.0, 0.0416), (22.0, 0.0420), (24.0, 0.0424),
    (26.0, 0.0428), (28.0, 0.0430), (30.0, 0.0433), (32.0, 0.0436),
    (34.0, 0.0439), (37.2, 0.0442),
)


def dissolved_nacl_gal_per_lb(salt_pct_bwow: float) -> float:
    """Validate the supported BWOW domain and interpolate published nodes."""
    pct = clean_number(salt_pct_bwow)
    if pct == 0.0:
        return 0.0
    if pct < 2.0:
        raise ValueError("NaCl must be 0% or at least 2% BWOW; no dissolved-salt data is supported below 2%")
    if pct > 37.2:
        raise ValueError("NaCl exceeds the supported saturation limit of 37.2% BWOW")
    for index, (upper, volume) in enumerate(DISSOLVED_NACL_GAL_PER_LB):
        if pct == upper:
            return volume
        if pct < upper:
            lower, previous = DISSOLVED_NACL_GAL_PER_LB[index - 1]
            return previous + (volume - previous) * (pct - lower) / (upper - lower)
    raise ValueError("Unsupported NaCl concentration")


def calculate_salt_field_amounts(salt_pct_bwow: float, mix_water_bbl: float,
                                 total_sacks: float, dead_vol_bbl: float = 0.0) -> dict:
    """Salt is BWOW of pure Fresh Water; dead volume is operational water."""
    dissolved_nacl_gal_per_lb(salt_pct_bwow)
    lbs_per_bbl = WATER_DENSITY_PCF * BBL_TO_CUFT * clean_number(salt_pct_bwow) / 100.0
    base_lb = mix_water_bbl * lbs_per_bbl
    return {
        "base_lb": base_lb,
        "lbs_per_sk": base_lb / total_sacks if total_sacks > 0 else 0.0,
        "lbs_per_bbl": lbs_per_bbl,
        "with_dead_lb": (mix_water_bbl + dead_vol_bbl) * lbs_per_bbl,
    }


def normalize_additive_mix(physical_state: str, mix_method: str, material_name: str = "",
                           material_type: str = "") -> tuple:
    """
    Normalizes the (Physical State, Mix Method) pair for a slurry additive row
    into a single authoritative classification. This MUST be the only place
    that decides "is this row dry-blended or dissolved in mix water" — every
    call site (the mass-balance engine's powder/liquid split, the formulation
    table shown to the user, and Phase VII's lab-quantity translation) needs
    to import and use this function instead of re-deriving the same decision
    locally.

    FIX (materials taxonomy update): a fixed set of brand Names
    (materials_db.FORCED_DRY_BLEND_NAMES — base cement products, Silica
    Flour, Micro Silica, Hidense, Light Weight, Cenosphere) are always
    physically pre-blended dry with the bulk cement, never dissolved in the
    mixing tank, regardless of what the Mix Method column says. This check is
    done here by Name (not by Material Type), because the same Material Type
    can contain both forced and non-forced brands — e.g. "Extender" =
    Micro Silica (forced) + Bentonite (user's choice), "Weighting Agent" =
    Hidense (forced) + Micro Max (user's choice, can be either). Previously
    Phase V applied a similar override locally (checked against Material
    Type) while Phase VII's lab-quantity translation did not apply it at
    all — the same row could disagree between the two phases. Centralizing
    it here, keyed by Name, makes both phases agree by construction.

    FIX: A liquid chemical cannot be physically pre-blended dry with bulk
    cement powder — "Dry Blend" only makes physical sense for powders. Before
    this fix, different call sites disagreed on how to resolve a
    Physical State="Liquid" + Mix Method="Dry Blend" row (nothing in the UI
    prevents a user from picking that combination): some let "Dry Blend" win
    over "Liquid", others forced "Liquid" to override "Dry Blend". The result
    was that the same additive row could be computed as a dry powder (no
    dead-volume penalty, powder density used) in the yield/mix-water formula
    while simultaneously being displayed as a chemical dissolved in the tank
    in the additives table — two different, disagreeing numbers for the same
    input. Liquids are now always forced to "In Mix Water" here, consistently.

    Returns (effective_mix_method, is_dry_blend).
    """
    # NaCl is represented as dissolved salt (% BWOW) by this app's engine.
    if is_salt_additive(material_type, material_name):
        return "In Mix Water", False
    state_clean = str(physical_state).strip().title()
    method_clean = str(mix_method or "In Mix Water").strip()
    if state_clean == "Liquid":
        method_clean = "In Mix Water"
    else:
        name_clean = str(material_name or "").strip().lower()
        is_forced = any(name_clean == str(n).strip().lower() for n in getattr(materials_db, "FORCED_DRY_BLEND_NAMES", []))
        if is_forced:
            method_clean = "Dry Blend"
    return method_clean, (method_clean == "Dry Blend")


def require_additive_identity(row) -> tuple:
    """A selected formulation row needs its actual type and commercial name."""
    values = tuple(str(row.get(field) or "").strip() for field in ("Material Type", "Name"))
    if any(value.casefold() in ("", "none", "nan", "<na>", "other (custom)") for value in values):
        raise ValueError("Enter the actual Material Type and Name for each additive row in Phase V")
    return values


def default_additive_density_gcm3(mat_name: str, physical_state: str = "Powder") -> float:
    """Expose the existing catalog property in the formulation editor's unit."""
    density = resolve_additive_density(mat_name, physical_state)
    return density[0] / WATER_LB_PER_GAL if str(physical_state).strip().lower() == "liquid" else density / 62.4


def resolve_additive_density(mat_name: str, physical_state: str = "Powder", explicit_density=None,
                             require_measured: bool = False):
    """Resolve a g/cm³ cell to exact catalog properties or converted overrides."""
    liquid = str(physical_state).strip().lower() == "liquid"
    table = DEFAULT_LIQUID_PROPERTIES if liquid else DEFAULT_POWDER_DENSITIES_PCF
    match = table.get(str(mat_name).strip().lower())
    if isinstance(explicit_density, Real) and math.isnan(float(explicit_density)):
        explicit_density = None
    missing = explicit_density is None or not str(explicit_density).strip()
    if require_measured and missing:
        raise ValueError(f"{mat_name}: enter the measured density (g/cm³) for the custom material in Phase V")
    if not missing:
        density = clean_number(explicit_density)
        if density <= 0:
            raise ValueError(f"{mat_name}: density must be positive")
        factor = WATER_LB_PER_GAL if liquid else 62.4
        catalog_density = match["density_ppg"] if liquid and match is not None else match
        # Display precision must not round-trip untouched catalog properties.
        if require_measured or match is None or density != catalog_density / factor:
            internal = density * factor
            if not math.isfinite(internal):
                raise ValueError(f"{mat_name}: density must be finite")
            return (internal, internal / CEMENT_SACK_LB) if liquid else internal
    if match is None:
        raise ValueError(f"{mat_name}: no exact material density found. Enter its measured density (g/cm³) in Phase V.")
    return (match["density_ppg"], match["lab_factor"]) if liquid else match


# ==============================================================================
# UNIVERSAL SLURRY MASS-BALANCE ENGINE (FOR STREAMLIT & DYNAMIC DATAFRAMES)
# ==============================================================================

def calculate_slurry_from_components(
    slurry_weight_pcf: float,
    slurry_volume_bbl: float,
    cmt_sg: float = 3.2,
    water_density_pcf: float = WATER_DENSITY_PCF,
    salt_pct: float = 0.0,
    powders: list = None,
    liquids: list = None
) -> dict:
    """Unrounded per-sack mass balance shared by field and lab calculations."""
    slurry_weight_pcf = clean_number(slurry_weight_pcf)
    slurry_volume_bbl = clean_number(slurry_volume_bbl)
    cmt_sg = max(clean_number(cmt_sg), 0.1)
    water_density_pcf = max(clean_number(water_density_pcf), 1.0)
    salt_pct = clean_number(salt_pct)
    salt_av_gal_lb = dissolved_nacl_gal_per_lb(salt_pct)
    if not (75.0 <= slurry_weight_pcf <= 180.0):
        raise ValueError(
            f"Slurry weight {slurry_weight_pcf:.1f} pcf is outside the realistic "
            "75-180 pcf range for a cement slurry; review the slurry density "
            "before building quantities")
    powders = powders or []
    liquids = liquids or []
    powder_masses = [clean_number(p.get("percent", 0.0)) * CEMENT_SACK_LB / 100.0 for p in powders]
    powder_densities = [max(clean_number(p.get("density_pcf", 84.864)), 1.0) for p in powders]
    powder_volumes = [mass / density for mass, density in zip(powder_masses, powder_densities)]
    liquid_gallons = [clean_number(l.get("gal_per_sk", 0.0)) for l in liquids]
    liquid_masses = [gallons * clean_number(l.get("density_ppg", WATER_LB_PER_GAL))
                     for gallons, l in zip(liquid_gallons, liquids)]
    ma_additives = sum(powder_masses) + sum(liquid_masses)
    va_additives = sum(powder_volumes) + sum(liquid_gallons) / GAL_PER_CUFT
    cement_volume = CEMENT_SACK_LB / (cmt_sg * water_density_pcf)
    salt_mass_per_water_ft3 = water_density_pcf * salt_pct / 100.0
    salt_volume_per_water_ft3 = salt_mass_per_water_ft3 * salt_av_gal_lb / GAL_PER_CUFT
    numerator = CEMENT_SACK_LB + ma_additives - slurry_weight_pcf * (cement_volume + va_additives)
    denominator = slurry_weight_pcf * (1.0 + salt_volume_per_water_ft3) - water_density_pcf - salt_mass_per_water_ft3
    if not math.isfinite(denominator) or abs(denominator) < 1e-6:
        raise ValueError("Slurry mass balance is undefined near mix-water density; review slurry density and formulation")
    water_vol_per_sack = numerator / denominator
    if not math.isfinite(water_vol_per_sack):
        raise ValueError("Slurry mass balance produced invalid mix water; review slurry density and formulation")
    if water_vol_per_sack > 20.0:
        raise ValueError("Slurry mass balance requires more than 20 ft3/sk of mix water; review slurry density and formulation")
    water_mass = water_vol_per_sack * water_density_pcf
    salt_mass = water_mass * salt_pct / 100.0
    salt_volume = salt_mass * salt_av_gal_lb / GAL_PER_CUFT
    yield_ft3_per_sk = cement_volume + va_additives + water_vol_per_sack + salt_volume
    if not math.isfinite(yield_ft3_per_sk):
        raise ValueError("Slurry mass balance produced an invalid yield; review slurry density and formulation")
    field_sacks = slurry_volume_bbl * BBL_TO_CUFT / yield_ft3_per_sk if yield_ft3_per_sk > 0 else 0.0
    field_water_bbl = water_vol_per_sack * field_sacks / BBL_TO_CUFT
    base_fluid_gal_sk = water_vol_per_sack * GAL_PER_CUFT
    mix_water_gal_sk = base_fluid_gal_sk + salt_volume * GAL_PER_CUFT
    wet_powder_volume = sum(volume for p, volume in zip(powders, powder_volumes) if p.get("in_solution", True))
    mix_fluid_gal_sk = mix_water_gal_sk + wet_powder_volume * GAL_PER_CUFT + sum(liquid_gallons)
    field_solution_bbl = mix_fluid_gal_sk * field_sacks / BBL_GAL
    if not all(math.isfinite(value) for value in (field_sacks, field_water_bbl, field_solution_bbl)):
        raise ValueError("Slurry mass balance produced nonfinite field quantities; review the formulation")
    field_powders = [{"name": p.get("name", ""), "percent": clean_number(p.get("percent", 0.0)),
                      "density_pcf": density, "field_lb": mass * field_sacks, "lbs_per_sk": mass}
                     for p, mass, density in zip(powders, powder_masses, powder_densities)]
    field_liquids = [{"name": l.get("name", ""), "gal_per_sk": gallons, "field_gal": gallons * field_sacks}
                    for l, gallons in zip(liquids, liquid_gallons)]
    lab_cmt_gr = LAB_SCALE / yield_ft3_per_sk if yield_ft3_per_sk > 0 else 0.0
    lab_water_gr = lab_cmt_gr * water_mass / CEMENT_SACK_LB
    lab_powders = [{"name": p.get("name", ""), "percent": clean_number(p.get("percent", 0.0)),
                    "lab_gr": lab_cmt_gr * mass / CEMENT_SACK_LB} for p, mass in zip(powders, powder_masses)]
    lab_liquids = [{"name": l.get("name", ""), "gal_per_sk": gallons,
                    "lab_gr": lab_cmt_gr * mass / CEMENT_SACK_LB}
                   for l, gallons, mass in zip(liquids, liquid_gallons, liquid_masses)]
    salt_lab_gr = lab_water_gr * salt_pct / 100.0
    lab_solution_gr = (lab_water_gr + salt_lab_gr
                       + sum(lab["lab_gr"] for p, lab in zip(powders, lab_powders) if p.get("in_solution", True))
                       + sum(lab["lab_gr"] for lab in lab_liquids))
    return {
        "ma_additives": ma_additives, "va_additives": va_additives,
        "water_vol_per_sack": water_vol_per_sack, "yield_ft3_per_sk": yield_ft3_per_sk,
        "base_fluid_gal_sk": base_fluid_gal_sk, "mix_water_gal_sk": mix_water_gal_sk,
        "mix_fluid_gal_sk": mix_fluid_gal_sk, "field_sacks": field_sacks,
        "field_water_bbl": field_water_bbl, "field_solution_bbl": field_solution_bbl,
        "field_powders": field_powders, "field_liquids": field_liquids,
        "salt_field_lb": salt_mass * field_sacks, "salt_lab_gr": salt_lab_gr,
        "lab_cmt_gr": lab_cmt_gr, "lab_water_gr": lab_water_gr, "lab_solution_gr": lab_solution_gr,
        "lab_powders": lab_powders, "lab_liquids": lab_liquids,
    }


def compute_phase_status(ss) -> dict:
    """
    Read-only snapshot of how "filled in" each phase currently is, based
    purely on what's already in session_state (ss) — this function adds no
    state of its own and has no side effects. Each entry is
    {"level": "ok" | "warning" | "empty", "message": str}.

    Shared by the sidebar phase markers (main.py) and the Phase X pre-export
    checklist (phase_10_procedure.py) so the two can never silently disagree
    about what "complete" means for a given phase — both call this one
    function instead of each keeping their own copy of the rules.
    """
    slurry_names = ["Main", "Lead", "Lead #1", "Lead #2", "Tail"]
    active = ss.get("fluids_config", {}).get("active", [])
    active_slurries = [s for s in active if s in slurry_names]
    status = {}

    def filled(value):
        return str(value).strip().lower() not in ("", "none", "nan", "<na>")

    def _positive_number(value):
        try:
            number = float(value)
            return math.isfinite(number) and number > 0
        except (TypeError, ValueError, OverflowError):
            return False

    # BUG-12: hardware "MD (m)" legitimately accepts interval strings
    # ("1200.0-2816.0") — Phase II/III documents shoe intervals that way and
    # the placement resolver (placement.measured_depth) parses them. The old
    # float() check tripped on every interval row and flagged the phase with
    # "Complete hardware description, depth, size and ID." forever, which
    # disabled the Phase X Build button. Use the same parser here.
    from placement import measured_depth, EXCESS_FIELDS, excess_percentage

    def _positive_md(value):
        try:
            depth = measured_depth(value)
        except Exception:
            return False
        return depth is not None and math.isfinite(depth) and depth > 0

    # Phase I: Document Control
    well_name = str(ss.get("well_name", "")).strip()
    client = str(ss.get("client", "")).strip()
    if not well_name:
        status["phase1"] = {"level": "empty", "message": "Well Name not entered yet."}
    elif not client:
        status["phase1"] = {"level": "warning", "message": f"Well: {well_name} — Client not entered yet."}
    else:
        status["phase1"] = {"level": "ok", "message": f"Well: {well_name} | Client: {client}"}

    # Phase II & III: Well Data
    hw = ss.get("hardware_table")
    hw_rows = len(hw) if hw is not None else 0
    def depth_or_none(field):
        try:
            value = float(ss.get(field, 0.0) or 0.0)
            return value if math.isfinite(value) else None
        except (TypeError, ValueError, OverflowError):
            return None

    geo_md = depth_or_none("geo_md")
    geo_tvd = depth_or_none("geo_tvd")
    from project_state import hardware_draft_pending
    if hardware_draft_pending(ss):
        status["phase2_3"] = {"level": "warning", "message": "Review pending hardware edits in Phase II & III before export."}
    elif geo_md is None or geo_tvd is None:
        status["phase2_3"] = {"level": "warning", "message": "MD/TVD is invalid; review Phase II & III."}
    elif hw_rows == 0:
        status["phase2_3"] = {"level": "empty", "message": "Tubular/Casing Hardware table is empty."}
    elif geo_md <= 0 or geo_tvd <= 0:
        status["phase2_3"] = {"level": "warning", "message": "Enter positive MD and TVD in Phase II & III."}
    elif geo_tvd > geo_md:
        status["phase2_3"] = {"level": "warning", "message": f"TVD ({geo_tvd:.1f} m) exceeds MD ({geo_md:.1f} m) — physically inconsistent."}
    elif any(not filled(row.get("Description")) or not filled(row.get("Size (in)"))
             or not _positive_md(row.get("MD (m)")) or not _positive_number(row.get("ID (in)"))
             for _, row in hw.iterrows()):
        status["phase2_3"] = {"level": "warning", "message": "Complete hardware description, depth, size and ID."}
    else:
        # Use the same resolved placement source as the procedure generator.
        # A valid hardware row alone does not identify the target shoe, and a
        # former selection must cease to count after that row or job changes.
        from placement import target_depth, host_label
        job_type = ss.get("job_type", "")
        placement = ss.get("placement_config", {})
        if target_depth(hw, job_type, placement) is None:
            status["phase2_3"] = {"level": "warning", "message": "Select the target shoe or enter a measured treatment depth in Phase II & III."}
        elif "TIE BACK" in str(job_type).upper() and host_label(hw, job_type, placement) is None:
            status["phase2_3"] = {"level": "warning", "message": "Select the existing casing or liner host for tie-back."}
        else:
            status["phase2_3"] = {"level": "ok", "message": f"{hw_rows} hardware row(s); placement target selected."}

    placement = ss.get("placement_config", {})
    if placement.get("job_type") == ss.get("job_type"):
        try:
            for field, _, _ in EXCESS_FIELDS:
                excess_percentage(placement, field)
        except ValueError as exc:
            status["phase2_3"] = {"level": "warning", "message": str(exc)}

    # Phase IV: Fluids Sequence
    if len(active) <= 1:
        status["phase4"] = {"level": "empty", "message": "No fluids selected beyond Displacement Fluid."}
    else:
        config = ss.get("fluids_config", {}).get("params", {})
        fluid_data = ss.get("fluid_data", {})
        incomplete = []
        for fluid in active:
            source = config.get(fluid, fluid_data.get(fluid, {}))
            if not isinstance(source, dict) or not _positive_number(source.get("volume")):
                incomplete.append(fluid)
                continue
            density = (ss.get("mud_density") or ss.get("well_data", {}).get("mud_density")
                       if fluid == "Displacement Fluid" else source.get("density"))
            try:
                if fluid == "Pre Flush":
                    require_preflush_material_name(source.get("material_name", materials_db.DEFAULT_MATERIAL_NAMES[fluid]))
                require_positive_density(density)
                require_positive_pump_rate(source.get("pump_rate"))
            except (TypeError, ValueError, OverflowError):
                incomplete.append(fluid)
        status["phase4"] = (
            {"level": "warning", "message": f"Review volume, density and pump rate for: {', '.join(incomplete)}."} if incomplete
            else {"level": "ok", "message": f"{len(active)} fluid(s) configured."}
        )

    # Phase V: Cement Program
    if not active_slurries:
        status["phase5"] = {"level": "empty", "message": "No cement slurry selected in Phase IV."}
    else:
        adds = ss.get("cement_additives_dfs", {})
        def rows_complete(table):
            if table is None or not hasattr(table, "iterrows"):
                return False
            # An initialized empty table is a neat cement design. Missing
            # tables remain incomplete; placement and mass balance are
            # still validated below for every slurry.
            for _, row in table.iterrows():
                material = str(row.get("Material Type")).strip()
                if material in ("", "None", "nan", "<NA>"):
                    return False
                try:
                    concentration = float(row.get("User Input"))
                except (TypeError, ValueError, OverflowError):
                    return False
                if not math.isfinite(concentration) or concentration < 0:
                    return False
                # The same density resolution as Phase V's mass-balance engine
                # must succeed before the sidebar can show a completed slurry.
                # In particular, a custom material requires its measured value.
                try:
                    material, display_name = require_additive_identity(row)
                except ValueError:
                    return False
                if material.casefold() == "cement":
                    return False
                if not is_salt_additive(material, display_name):
                    state = resolve_physical_state(material, row.get("Physical State"))
                    try:
                        resolve_additive_density(
                            display_name, state, row.get("Density"),
                            require_measured=materials_db.resolve_known_material(display_name) is None
                        )
                    except (TypeError, ValueError, OverflowError):
                        return False
            return True

        missing = [s for s in active_slurries if not rows_complete(adds.get(s))]
        from placement import slurry_intervals
        intervals = slurry_intervals(ss.get("hardware_table"), ss.get("job_type", ""),
                                     ss.get("placement_config", {}), active_slurries,
                                     ss.get("cement_params", {}))
        missing_tops = [slurry for slurry, interval in intervals.items()
                        if interval["top_depth"] is None or interval["bottom_depth"] is None]
        invalid_calculations = []
        if not missing and not missing_tops:
            from phase_5_cement import build_components
            for slurry in active_slurries:
                fluid = ss.get("fluid_data", {}).get(slurry, {})
                try:
                    validate_cement_parameters(ss.get("cement_params", {}).get(slurry, {}))
                    if not _positive_number(fluid.get("volume")):
                        raise ValueError("Phase IV volume is missing")
                    density = require_positive_density(fluid.get("density"))
                    if not 75.0 <= density <= 180.0:
                        raise ValueError("Phase IV slurry density is invalid")
                    powders, liquids, salt = build_components(adds[slurry])
                    result = calculate_slurry_from_components(
                        slurry_weight_pcf=density,
                        slurry_volume_bbl=fluid["volume"],
                        cmt_sg=ss.get("cement_params", {}).get(slurry, {}).get("cmt_sg", 3.20),
                        water_density_pcf=62.4, salt_pct=salt,
                        powders=powders, liquids=liquids,
                    )
                    if result["field_sacks"] <= 0 or result["water_vol_per_sack"] < 0:
                        raise ValueError("Mass balance has no valid cement or mix water")
                except (TypeError, ValueError, OverflowError, ZeroDivisionError, KeyError):
                    invalid_calculations.append(slurry)
        if missing:
            status["phase5"] = {"level": "warning", "message": f"Additive rows incomplete for: {', '.join(missing)}."}
        elif missing_tops:
            status["phase5"] = {"level": "warning", "message": f"Top of cement missing or invalid for: {', '.join(missing_tops)}."}
        elif invalid_calculations:
            status["phase5"] = {"level": "warning", "message": f"Review Phase IV fluid data or Phase V mass balance for: {', '.join(invalid_calculations)}."}
        else:
            status["phase5"] = {"level": "ok", "message": f"{len(active_slurries)} slurry(ies) formulated and placed."}

    # Phase VI: Pre-flush & Spacer
    has_preflush = "Pre Flush" in active
    spacer_types = [f for f in active if f in ("Spacer", "Spacer Ahead", "Spacer Behind")]
    if not has_preflush and not spacer_types:
        status["phase6"] = {"level": "empty", "message": "Not applicable (no Pre Flush/Spacer selected)."}
    else:
        problems = []
        if has_preflush and not ss.get("preflush_calc"):
            problems.append("Pre Flush not configured")
        sdfs = ss.get("spacer_dfs", {})
        empty_spacers = [s for s in spacer_types if len(sdfs.get(s, [])) == 0]
        if empty_spacers:
            problems.append(f"no chemicals for: {', '.join(empty_spacers)}")
        incomplete_spacers = []
        for spacer in spacer_types:
            table = sdfs.get(spacer)
            if table is None or not hasattr(table, "iterrows"):
                continue
            for _, row in table.iterrows():
                try:
                    amount = float(row.get("User Input (% or gal)"))
                except (TypeError, ValueError, OverflowError):
                    amount = float("nan")
                if not filled(row.get("Chemical")) or not math.isfinite(amount) or amount < 0:
                    incomplete_spacers.append(spacer)
                    break
        if incomplete_spacers:
            problems.append(f"incomplete chemical rows for: {', '.join(incomplete_spacers)}")
        status["phase6"] = (
            {"level": "warning", "message": "; ".join(problems) + "."} if problems
            else {"level": "ok", "message": "Pre-flush/Spacer configured."}
        )

    # Phase VII: Lab Report
    if not active_slurries:
        status["phase7"] = {"level": "empty", "message": "No cement slurry to report on."}
    else:
        qc = ss.get("lab_qc_params", {})
        grids = ss.get("lab_grid_dfs", {})
        missing = []
        for slurry in active_slurries:
            grid = grids.get(slurry)
            if slurry not in qc or grid is None or not hasattr(grid, "iterrows") or grid.empty:
                missing.append(slurry)
                continue
            if any(not all(filled(row.get(field)) for field in ("Material", "Concentration", "Unit", "Mass"))
                   for _, row in grid.iterrows()):
                missing.append(slurry)
                continue
            try:
                validate_lab_masses(grid)
            except ValueError:
                missing.append(slurry)
                continue
            try:
                validate_lab_collection_results(qc[slurry])
            except ValueError:
                missing.append(slurry)
                continue
            if not thickening_time_valid(qc[slurry].get("thickening_time")):
                missing.append(slurry)
                continue
            bhst = ss.get("well_data", {}).get("bhst", ss.get("bhst", 200))
            if not lab_temperature_valid(qc[slurry].get("bhct"), bhst):
                missing.append(slurry)
                continue
            if (not qc[slurry].get("reviewed", False)
                    or qc[slurry].get("review_signature") != lab_review_signature(qc[slurry], grid)):
                missing.append(slurry)
                continue
            from project_state import lab_source_signature
            if ss.get("lab_source_signatures", {}).get(slurry) != lab_source_signature(ss, slurry):
                missing.append(slurry)
        status["phase7"] = (
            {"level": "warning", "message": f"Lab QC or formulation rows incomplete for: {', '.join(missing)}."} if missing
            else {"level": "ok", "message": f"Lab QC and formulation entered for {len(active_slurries)} slurry(ies)."}
        )

    return status
