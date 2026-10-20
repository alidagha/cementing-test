"""Standalone Spacer source-input projection and fixed-20°C formulation.

Reads Phase IV Spacer volume/density and independent Phase VI inputs. Returns
recomputable quantities only; no session writes or persisted recipe. The lab
projection samples the target composition. Tank identities remain owned by materials_db.
"""
import math

import materials_db
from engineering_tools import normalize_digits, require_fluid_density, round_half_up

CONFIG_KEY = "standalone_spacer_config"
MODES = ("Limestone", "Barite", "Ferro Bar", "Limestone + Barite")
PENDING_INTEGRATION = (
    "Standalone Spacer: laboratory, Dynamic/Pumping and Word integrations are "
    "pending Gates A2–A4. Final Word export is blocked."
)
BBL_M3 = 0.158987294928
BBL_FT3 = 42 / 7.48051948051948
KG_LB = 2.2046226218487758
R = {name: density * BBL_M3 * KG_LB for name, density in (
    ("water", 998.20675), ("brine", 1201.13), ("O-Spacer", 1620.),
    ("Surfactant", 940.), ("Defoamer", 1000.),
    ("Limestone", 2700.), ("Barite", 4200.), ("Ferro Bar", 4800.))}
A = R["water"] + 126 + 10 + 2 / 42 * R["Surfactant"]
BV = (R["water"] + 126) / R["brine"] + 10 / R["O-Spacer"] + 2 / 42
CM = .5 / 42 * R["Defoamer"]
CV = .5 / 42


def _number(value, label, *, positive=False):
    try:
        number = float(normalize_digits(value)) if not isinstance(value, bool) else math.nan
    except (TypeError, ValueError, OverflowError):
        number = math.nan
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError(f"{label}: enter a finite {'positive' if positive else 'nonnegative'} number.")
    return number


def validate_config(config, job_type):
    """Validate saved input shape, allowing explicitly unfinished operator drafts."""
    fields = {"mode", "dead_vol", "tank_name", "limestone_available_lb", "barite_available_lb"}
    if not isinstance(config, dict) or set(config) - fields:
        raise ValueError("Standalone Spacer configuration must contain only formulation inputs.")
    if config.get("mode") is not None and config["mode"] not in MODES:
        raise ValueError("Standalone Spacer: select a supported Weighting Agent Mode.")
    if config.get("tank_name") is not None and config["tank_name"] not in materials_db.get_available_tanks(job_type):
        raise ValueError("Standalone Spacer: select a Mixing Tank available for this job.")
    for field in ("dead_vol", "limestone_available_lb", "barite_available_lb"):
        value = config.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Standalone Spacer {field}: must be a finite nonnegative number or null.")
            _number(value, f"Standalone Spacer {field}")


def _solo(volume, density, mode):
    denominator = BV - A / R[mode]
    if not math.isfinite(denominator) or denominator == 0:
        raise ValueError("Standalone Spacer: singular mass/volume balance.")
    water = volume * (1 - CV - (density * BBL_FT3 - CM) / R[mode]) / denominator
    mass = volume * (density * BBL_FT3 - CM) - A * water
    return water, mass


def calculate_spacer(volume_bbl, density_pcf, mode, dead_vol_bbl,
                     limestone_available_lb=None, barite_available_lb=None):
    """One full-precision mass/volume solve; Dead Volume scales its composition."""
    volume = _number(volume_bbl, "Spacer volume", positive=True)
    density = require_fluid_density("Spacer", density_pcf)
    dead = _number(dead_vol_bbl, "Spacer Dead Volume")
    if mode not in MODES:
        raise ValueError("Standalone Spacer: select a Weighting Agent Mode.")
    low, high = (100, 125) if mode == MODES[3] else (75, {"Limestone": 100, "Barite": 125, "Ferro Bar": 160}[mode])
    if not low <= density <= high:
        raise ValueError(f"Standalone Spacer {mode}: target density must be {low}–{high} pcf.")
    solids = {}
    inventory = {}
    if mode != MODES[3]:
        water, mass = _solo(volume, density, mode)
        solids[mode] = mass
    else:
        available_l = _number(limestone_available_lb, "Available Limestone inventory", positive=True)
        available_b = _number(barite_available_lb, "Available Barite inventory", positive=True)
        _, cap = _solo(volume, 100., "Limestone")
        a = volume * (1 - CV - (density * BBL_FT3 - CM) / R["Barite"]) / (BV - A / R["Barite"])
        b = (1 / R["Barite"] - 1 / R["Limestone"]) / (BV - A / R["Barite"])

        def candidate(limestone):
            w = a + b * limestone
            if not math.isfinite(w) or w <= 0:
                raise ValueError("Standalone Spacer: nonpositive freshwater in Mix balance.")
            barite = volume * (density * BBL_FT3 - CM) - A * w - limestone
            return w, barite, 1 + dead / w

        # W=a+bL, b<0: gross L=L(1+Dead/W) increases strictly.
        # Gross Barite decreases on the approved 100–125 pcf band. Therefore
        # the largest Limestone allowed by cap/stock also minimizes Barite use.
        limestone = min(cap, available_l)
        if candidate(limestone)[2] * limestone > available_l:
            lo, hi = 0., limestone
            for _ in range(80):
                mid = (lo + hi) / 2
                if candidate(mid)[2] * mid <= available_l:
                    lo = mid
                else:
                    hi = mid
            limestone = lo
        water, barite, scale = candidate(limestone)
        if density == 100 and limestone == cap:
            raise ValueError("Standalone Spacer: zero-Barite result is not a true Mix; select Limestone-only.")
        if limestone <= 0 or barite <= 0:
            raise ValueError("Standalone Spacer: a true Mix requires positive Limestone and Barite.")
        if scale * barite > available_b:
            raise ValueError(f"Standalone Spacer: Barite inventory shortage; need {scale * barite:.6f} lb, "
                             f"available {available_b:g} lb, deficit {scale * barite - available_b:.6f} lb.")
        solids = {"Limestone": limestone, "Barite": barite}
        inventory = {name: {"available_lb": stock, "used_lb": scale * solids[name],
                            "remaining_lb": stock - scale * solids[name]}
                     for name, stock in (("Limestone", available_l), ("Barite", available_b))}

    if not math.isfinite(water) or water <= 0 or any(not math.isfinite(m) or m < 0 for m in solids.values()):
        raise ValueError("Standalone Spacer: invalid freshwater or weighting mass balance.")
    scale = (water + dead) / water
    mixed = scale * volume
    # Dissolved salt occupies the working-brine model, never crystalline SG.
    components = [
        {"name": "Working brine", "mass_lb": (R["water"] + 126) * water,
         "volume_bbl": (R["water"] + 126) * water / R["brine"]},
        {"name": "O-Spacer", "mass_lb": 10 * water, "volume_bbl": 10 * water / R["O-Spacer"]},
        {"name": "Surfactant", "mass_lb": 2 / 42 * water * R["Surfactant"], "volume_bbl": 2 / 42 * water},
        {"name": "Defoamer", "mass_lb": CM * volume, "volume_bbl": CV * volume},
        *[{"name": name, "mass_lb": mass, "volume_bbl": mass / R[name]} for name, mass in solids.items()],
    ]
    mass = math.fsum(c["mass_lb"] for c in components)
    actual_volume = math.fsum(c["volume_bbl"] for c in components)
    closure = {"mass_lb": mass - density * BBL_FT3 * volume,
               "volume_bbl": actual_volume - volume,
               "density_pcf": mass / (actual_volume * BBL_FT3) - density}
    if not all(math.isfinite(n) for n in (scale, mixed, mass, actual_volume, *closure.values())) or any((
        abs(closure["mass_lb"]) > 1e-9 * max(1, mass),
        abs(closure["volume_bbl"]) > 1e-9 * max(1, volume), abs(closure["density_pcf"]) > 1e-8)):
        raise ValueError("Standalone Spacer: mass/volume/density closure failed.")
    materials = [
        ("Salt", "NaCl", 126 * water, "lb", 126., "freshwater"),
        ("O-Spacer", "Spacer", 10 * water, "lb", 10., "freshwater"),
        ("Surfactant", "Surfactant", 2 * water, "gal", 2., "freshwater"),
        ("Defoamer", "Anti Foam", .5 * volume, "gal", .5, "finished Spacer"),
        *[(name, "Weighting Agent", mass, "lb", mass / water, "freshwater") for name, mass in solids.items()],
    ]
    return {"volume_bbl": volume, "density_pcf": density, "mode": mode,
            "water_base_bbl": water, "water_total_bbl": water + dead,
            "scale": scale, "mixed_volume_bbl": mixed, "pumped_volume_bbl": volume,
            "solids_lb": solids, "inventory": inventory, "components": components, "closure": closure,
            "weighting_pct": {name: 100 * mass / sum(solids.values()) for name, mass in solids.items()},
            "materials": [{"name": name, "material_type": kind, "base": base,
                           "gross": base * scale, "unit": unit, "dose": dose, "basis": basis}
                          for name, kind, base, unit, dose, basis in materials]}


def formulation_from_state(state):
    """Read current sources only; never trust legacy generic Spacer or a recipe cache."""
    cfg = state.get("fluids_config", {})
    if "Spacer" not in cfg.get("active", []):
        raise ValueError("Standalone Spacer is inactive.")
    source = cfg.get("params", {}).get("Spacer", state.get("fluid_data", {}).get("Spacer", {}))
    config = state.get(CONFIG_KEY, {})
    job = state.get("job_type", 'CSG 20"')
    validate_config(config, job)
    if config.get("tank_name") not in materials_db.get_available_tanks(job):
        raise ValueError("Standalone Spacer: select a Mixing Tank.")
    result = calculate_spacer(source.get("volume"), source.get("density"), config.get("mode"),
                              config.get("dead_vol"), config.get("limestone_available_lb"),
                              config.get("barite_available_lb"))
    result["note"] = (f"Mix above Additives in {round_half_up(result['water_total_bbl'], 1):.1f} bbl "
                      f"Fresh Water at {config['tank_name']}.")
    return result


FIELD_COLUMNS = ["Item", "Name", "Material Type", "lbs or gal", "lbs / bbl or gal / bbl",
                 "lbs or gal\n(with dead Vol.)"]


def field_rows(recipe):
    """Display-only rounding; values never feed back into the calculation."""
    return [dict(zip(FIELD_COLUMNS, (index, row["name"], row["material_type"],
                f"{round_half_up(row['base'], 1):.1f} {row['unit']}",
                f"{round_half_up(row['dose'], 1):.1f} {row['unit']}/bbl",
                f"{round_half_up(row['gross'], 1):.1f} {row['unit']}")))
            for index, row in enumerate(recipe["materials"], 1)]


def lab_sample(recipe):
    """600 mL of finished target Spacer, never the Dead-Volume field extension.

    Read the canonical target-batch masses/volumes; only unit conversion and
    sample scaling belong here. Dissolved salt volume stays in working brine.
    """
    factor = 600. / (recipe["volume_bbl"] * BBL_M3 * 1e6)
    components = {row["name"]: row for row in recipe["components"]}
    water_mass = R["water"] * recipe["water_base_bbl"]
    rows = [{"Material": "Fresh Water", "Concentration": recipe["water_base_bbl"] * BBL_M3 * 1e6 * factor,
             "Unit": "mL/600 mL finished Spacer", "Mass": water_mass * 453.59237 * factor, "Lot No": ""}]
    for material in recipe["materials"]:
        mass = material["base"] if material["unit"] == "lb" else components[material["name"]]["mass_lb"]
        rows.append({"Material": material["name"], "Concentration": material["dose"],
                     "Unit": f"{material['unit']}/bbl {material['basis']}",
                     "Mass": mass * 453.59237 * factor, "Lot No": ""})
    mass_g = math.fsum(row["Mass"] for row in rows)
    volume_ml = math.fsum(row["volume_bbl"] for row in components.values()) * BBL_M3 * 1e6 * factor
    return {"rows": rows, "mass_g": mass_g, "volume_ml": volume_ml,
            "density_pcf": (mass_g / 453.59237) / (volume_ml / (BBL_M3 * 1e6) * BBL_FT3)}
