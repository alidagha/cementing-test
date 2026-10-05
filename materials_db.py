# materials_db.py
"""
Central Database and Configuration Module for Cementing App.
Contains all hardcoded lists, chemical databases, and dynamic mappings.
Formatted in Title Case (Capitalizing the first letter of each word) per engineering standard.
"""

JOB_TYPES = [
    'CSG 30"',
    'CSG 24"',
    'CSG 20"', 
    'CSG 18 5/8"',
    'CSG 13 3/8"', 
    'CSG 9 5/8"', 
    'CSG 7"', 
    'LNR 7"', 
    'LNR 5"', 
    "CMT PLUG", 
    "CMT SQUEEZE", 
    'TIE BACK LNR 7"', 
    'TIE BACK LNR 5"'
]

AVAILABLE_TANKS = [
    "Batch Mixer Tanks", 
    "Mud Reserve Tanks", 
    "Cement Unit Tanks"
]

# Lab "Solution Density" (Test Basic Data table) — observed as exactly 62.5 pcf
# across every real reference document regardless of job type or slurry. This
# is the standard fresh-water-basis reference density used for the API 600 mL
# lab solution calculation, not a value that varies per slurry — so it is a
# fixed constant here rather than a computed or manually-entered field.
SOLUTION_DENSITY_PCF = 62.5

DEFAULT_HOLE_SIZES = {
    'CSG 30"': '36"',
    'CSG 24"': '28"',
    'CSG 20"': '26"',
    'CSG 18 5/8"': '22"',
    'CSG 13 3/8"': '17 1/2"',
    'CSG 9 5/8"': '12 1/4"',
    'CSG 7"': '8 1/2"',
    'LNR 7"': '8 1/2"',
    'LNR 5"': '6"',
    "CMT PLUG": "Inside Casing / OH",
    "CMT SQUEEZE": "Perforations / Squeeze Zone",
    'TIE BACK LNR 7"': '8 1/2"',
    'TIE BACK LNR 5"': '6"'
}

FLUID_TYPES = [
    "Pre Flush", 
    "Spacer", 
    "Spacer Ahead", 
    "Spacer Behind", 
    "Main", 
    "Lead", 
    "Lead #1", 
    "Lead #2", 
    "Tail", 
    "Displacement Fluid"
]

DEFAULT_MATERIAL_NAMES = {
    "Pre Flush": "Salt Saturated Water",
    # BUG-20: the three spacer stages used to inherit the PRE-FLUSH name
    # "Salt Saturated Water" - a spacer is a weighted, viscous isolating
    # fluid, not a salt wash, and the exported fluids train table showed
    # the wrong description. Spacers get their own descriptive default.
    "Spacer": "Weighted Spacer",
    "Spacer Ahead": "Weighted Spacer",
    "Spacer Behind": "Weighted Spacer",
    "Main": "Cement Slurry",
    "Lead": "Cement Slurry",
    "Lead #1": "Cement Slurry",
    "Lead #2": "Cement Slurry",
    "Tail": "Cement Slurry",
    "Displacement Fluid": "Mud"
}

HARDWARE_DESCRIPTIONS = [
    "Previous Casing", 
    "Previous Liner", 
    "Casing", 
    "Liner", 
    "Liner Hanger", 
    "Tie Back", 
    "Drill Pipes", 
    "Tubing",
    "Open Hole Size"
]

# ==============================================================================
# CEMENT SLURRY MATERIAL TAXONOMY (Phase V / Phase VII)
# Single source of truth, sourced directly from the master reference file
# "Blend_Data___Additives_Data.xlsx" (columns: Name / Material Type / type).
# Structure: Material Type -> { "names": [commercial/brand Names], "state": "Powder"/"Liquid" }.
# Every dependent module (phase_5_cement.py, phase_7_lab.py, phase_10_procedure.py,
# engineering_tools.py) must read from this table instead of hardcoding its own
# copy, so a future update to the master file only has to change this dict.
# ==============================================================================
MATERIAL_TAXONOMY = {
    "Cement": {
        "names": ["Cement G Delijan", "Cement D Delijan"],
        "state": "Powder"
    },
    "F.L. Controller": {
        "names": ["O-uniFLC5", "J-FLC 320", "PK-FL 8", "LOLOSS-169", "PHS-C32", "CFL-109", "PK-FL7", "SE-F04"],
        "state": "Powder"
    },
    "Accelerator": {
        "names": ["Cacl2"],
        "state": "Powder"
    },
    "Nacl": {
        "names": ["SALT"],
        "state": "Powder"
    },
    "Dispersant": {
        "names": ["O-CFR8", "O-CFR4", "O-CFR2", "O-CFR3", "JP-450", "PSH-C21", "JP-CF410S", "J-D 220", "SE-D01", "PK-DIS2"],
        "state": "Powder"
    },
    "L.T. Retarder": {
        "names": ["O-R5"],
        "state": "Powder"
    },
    "H.T. Retarder": {
        "names": ["O-R12", "J-R120", "SE-R02", "PK-RET 5"],
        "state": "Powder"
    },
    "Retarder Aid": {
        "names": ["Boric Acid"],
        "state": "Powder"
    },
    "Anti Settling": {
        "names": ["Anti Settling"],
        "state": "Powder"
    },
    "Extender": {
        "names": ["Bentonite", "Micro Silica"],
        "state": "Powder"
    },
    "CS Stabilizer": {
        "names": ["Silica Flour"],
        "state": "Powder"
    },
    "Weighting Agent": {
        "names": ["Hidense", "Micro Max"],
        "state": "Powder"
    },
    "Light Weight": {
        "names": ["Light Weight", "Cenosphere"],
        "state": "Powder"
    },
    "Anti Gas Migration": {
        "names": ["O-GAS BLOCK", "PK-GAS7", "JP-620L", "SE-G10", "PK-GAS8"],
        "state": "Liquid"
    },
    "Liquid Extender": {
        "names": ["Micro Block"],
        "state": "Liquid"
    },
    "Anti Foam": {
        "names": ["Anti Foam", "Defoamer", "TA-47"],
        "state": "Liquid"
    }
}

# Brand Names that are always physically pre-blended dry with the bulk cement
# (never dissolved in the mixing tank), regardless of whatever the Mix Method
# column says. Confirmed per material-list update; NOT a Material Type check
# (a Material Type can mix forced and non-forced brands, e.g. "Extender" =
# Micro Silica [forced] + Bentonite [user's choice], "Weighting Agent" =
# Hidense [forced] + Micro Max [user's choice, can go either way]).
FORCED_DRY_BLEND_NAMES = [
    "Cement G Delijan",
    "Cement D Delijan",
    "Micro Silica",
    "Silica Flour",
    "Hidense",
    "Light Weight",
    "Cenosphere"
]

# Confirmed SG for the two base cement brands (used as a quick on-screen
# reference next to the Cement SG input; not auto-applied).
CEMENT_SG_REFERENCE = {
    "Cement G Delijan": 3.20,
    "Cement D Delijan": 3.16
}

# Reverse lookup: brand Name -> (Material Type, Physical State). Selecting a
# recognized Name determines its Material Type and Physical State; those two
# fields are then locked/derived, matching the master file's intent that a
# commercial brand cannot be mis-classified under the wrong category.
NAME_TO_MATERIAL = {
    name: (mat_type, info["state"])
    for mat_type, info in MATERIAL_TAXONOMY.items()
    for name in info["names"]
}

# Case-insensitive version of the same lookup, keyed by lowercased Name ->
# (canonical Name, Material Type, Physical State). Needed so a project saved
# before this taxonomy update (e.g. Name="O-UNIFLC5") still self-heals to the
# canonical spelling ("O-uniFLC5") instead of being left as an orphaned value
# that no longer matches any dropdown option.
NAME_TO_MATERIAL_CI = {
    name.lower(): (name, mat_type, info["state"])
    for mat_type, info in MATERIAL_TAXONOMY.items()
    for name in info["names"]
}

# Old Material Type spellings (pre master-list update) that changed casing/
# spacing only, mapped to their new canonical label. Used as a fallback when
# a legacy row's Material Type is stale but its Name doesn't resolve to a
# known brand (so at least the category label heals to a valid option).
LEGACY_MATERIAL_TYPE_ALIASES = {
    "f.l.controller": "F.L. Controller",
    "l.t.retarder": "L.T. Retarder",
    "h.t.retarder": "H.T. Retarder",
    "nacl": "Nacl"
}

def resolve_known_material(raw_value: str):
    """
    Case-insensitive brand lookup. Returns (canonical_name, material_type,
    physical_state) if raw_value matches a known brand Name (in any casing),
    else None. Used to self-heal both current and pre-update saved projects:
    a legacy row may have the brand typed in the old casing, or (in the old
    design) may have had the brand name typed directly into Material Type
    with no separate Name at all — callers should try both fields through
    this function.
    """
    return NAME_TO_MATERIAL_CI.get(str(raw_value).strip().lower())

MATERIAL_TYPES = list(MATERIAL_TAXONOMY.keys())

# Flat list of every commercial/brand Name across all Material Types, for the
# Name dropdown (plus an "Other (Custom)" escape hatch handled by callers).
ALL_MATERIAL_NAMES = [name for info in MATERIAL_TAXONOMY.values() for name in info["names"]]

def get_names_for_material_type(mat_type: str) -> list:
    """Returns the valid commercial Names for a given Material Type."""
    return MATERIAL_TAXONOMY.get(str(mat_type), {}).get("names", [])

def get_state_for_material_type(mat_type: str) -> str:
    """Returns the default Physical State ('Powder'/'Liquid') for a Material Type."""
    return MATERIAL_TAXONOMY.get(str(mat_type), {}).get("state", "Powder")

# Pre-flush & Spacer Database
PREFLUSH_CHEMICALS = ["NaCl", "Wash", "Water"]

# Descriptive Pre-flush fluid names, independent of formulation components.
PREFLUSH_MATERIAL_NAMES = [
    "Fresh Water", "Salt Saturated Water",
    "Fresh Water Mix with Chemical Wash",
    "Salt Saturated Water Mix with Chemical Wash", "Custom"
]

SPACER_CHEMICALS = [
    "NaCl", "Spacer", "Surfactant", "Anti Foam", "Weighting Agent", "Mud", "Magneset Thinner"
]

WEIGHTING_AGENTS = ["Barite", "Limestone", "Ferobar"]

TANK_OPTIONS_BY_JOB = {
    'CSG 20"':         ["Mud Reserve Tanks"],
    'CSG 13 3/8"':     ["Mud Reserve Tanks"],
    'CSG 9 5/8"':      ["Mud Reserve Tanks", "Batch Mixer Tanks"],
    'LNR 7"':          ["Mud Reserve Tanks", "Batch Mixer Tanks", "Cement Unit Tanks"],
    'LNR 5"':          ["Mud Reserve Tanks", "Batch Mixer Tanks", "Cement Unit Tanks"],
    "CMT PLUG":         ["Mud Reserve Tanks", "Cement Unit Tanks"],
    "CMT SQUEEZE":      ["Mud Reserve Tanks", "Batch Mixer Tanks", "Cement Unit Tanks"],
    'TIE BACK LNR 7"': ["Mud Reserve Tanks", "Batch Mixer Tanks", "Cement Unit Tanks"],
    'TIE BACK LNR 5"': ["Mud Reserve Tanks", "Batch Mixer Tanks", "Cement Unit Tanks"],
    'CSG 30"':         ["Mud Reserve Tanks"],
    'CSG 24"':         ["Mud Reserve Tanks"],
    'CSG 18 5/8"':     ["Mud Reserve Tanks"],
    'CSG 7"':          ["Mud Reserve Tanks", "Batch Mixer Tanks"],
}

def get_available_tanks(job_type: str) -> list:
    """Returns valid mixing tanks for the specified casing job type."""
    return TANK_OPTIONS_BY_JOB.get(str(job_type), AVAILABLE_TANKS)

def get_tank_name(job_type: str) -> str:
    """Returns default recommended mixing tank for this job type."""
    options = get_available_tanks(job_type)
    return options[0] if options else "Mud Reserve Tanks"

def get_cementing_method(job_type: str) -> str:
    """Auto-determines recommended cementing method."""
    job_upper = str(job_type).upper()
    if "PLUG" in job_upper or "SQUEEZE" in job_upper:
        return "Remedial Cementing"
    return "Primary Cementing"

def get_procedure_group(job_type: str) -> str:
    """Returns procedural group archetype for Phase 10."""
    job_upper = str(job_type).upper()
    if "PLUG" in job_upper:
        return "Group B"
    elif "SQUEEZE" in job_upper:
        return "Group C"
    elif "TIE BACK" in job_upper:
        return "Group D"
    else:
        return "Group A"