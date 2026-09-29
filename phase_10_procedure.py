# phase_10_procedure.py
import streamlit as st
import pandas as pd
import io
import hashlib
import os
import re
from pathlib import Path
from placement import target_depth, host_label, top_label
from datetime import datetime
import materials_db
from engineering_tools import (round_half_up, clean_number, normalize_additive_mix,
                               resolve_physical_state, compute_phase_status, safe_float,
                               parse_effective_numeric)
try:
    from docxtpl import DocxTemplate
except ModuleNotFoundError as exc:
    if exc.name != "docxtpl":
        raise
    # A deployment without the root requirements.txt must still let the
    # operator open Phase X and read the missing-dependency instruction.
    DocxTemplate = None
from project_state import (fingerprint, prepare_calculations, sync_report_text,
                           accept_report_text, restore_previous_text, invalidate_document)

TEMPLATE_PATH = Path(__file__).resolve().parent / "master_template.docx"

SLURRY_ARCHETYPES = ["Main", "Lead", "Lead #1", "Lead #2", "Tail"]

def active_slurry_names(active_fluids):
    """Slurry members of the active fluid train (case/space-insensitive
    archetype match). Extracted so the F3 unreadable-volume gate at the top
    of build_master_context and the slurry payload section below share ONE
    matcher instead of two divergent copies."""
    return [f for f in active_fluids
            if any(f.replace(" ", "").lower() == s.replace(" ", "").lower()
                   for s in SLURRY_ARCHETYPES)]

class NoteCounter:
    """
    Assigns sequential NOTE numbers as notes are generated, in the exact order
    they will appear in the final Word document. NEVER hardcode a "NOTE N:"
    number anywhere else in this codebase or in the Word template — every
    number must come from calling .next() on an instance of this class, in
    document order. This is the fix for the numbering drift/collisions found
    in real NIDC reference documents (e.g. CSG 20" silently skips numbers 5-6;
    LNR 7" issues two different notes both labeled "NOTE 8", corrupting every
    note number after it). A single running counter makes both classes of
    error structurally impossible.
    """
    def __init__(self, reserved_numbers=()):
        self.n = 0
        self.reserved_numbers = set(reserved_numbers)

    def next(self, body_text: str) -> str:
        """Consumes the next sequence number and returns the full 'NOTE N: ...' string."""
        self.n += 1
        while self.n in self.reserved_numbers:
            self.n += 1
        return f"NOTE {self.n}: {body_text}"


class StepCounter:
    """
    Marks top-level procedure steps and numbers them in printed order.

    Why this exists: verified against all 8 real reference documents that 7
    of the 8 job-type families (everything except CMT SQUEEZE) number their
    steps using Word's own invisible list auto-numbering (no digit characters
    are actually present in the paragraph text — confirmed via each
    document's own <w:numPr> XML), while CMT SQUEEZE instead types the
    number as literal text ("1. Clean up..."). The exported Word document is
    built from ONE single template paragraph that gets cloned once per
    generated procedure line (see the {%p for line in procedure_steps %}
    construct in master_template.docx) — a single template paragraph can't
    switch numbering styles per job type, so every branch must now emit the
    same, unambiguous convention: a literal "N. " prefix on every real step,
    with numbering restarting at 1 for each new procedure. Multi-line blocks
    (the additive mixing instructions) and inline Notes are NOT steps and
    must never consume a number — insert them into the `lines` list as plain
    strings, without going through this counter at all, exactly as
    `mixing_proc_text`, `rot_note`, `shoe_track_note`, and `bumping_note` do
    in every branch below.
    """
    _MARKER = "\ue000CMT_STEP\ue001"

    def __init__(self):
        self.n = 0

    def next(self, body_text: str) -> str:
        """Defer numbering until pump steps are inserted in their final place."""
        return self._MARKER + body_text

    def finalize(self, procedure: str) -> str:
        """Number only marked lines, leaving explanatory notes unnumbered."""
        def replace(match):
            self.n += 1
            return f"{self.n}. "
        return re.sub(r"(?m)^" + re.escape(self._MARKER), replace, procedure)


def build_ordered_notes(
    job_type: str,
    well_data: dict,
    total_pump_time_min: float,
    slurries_payload: list,
    has_open_hole_notes: bool,
    freshwater_note_style: str = "total hardness"
) -> dict:
    """
    Generates every NOTE in this report, in the single validated order found
    consistently across the real reference documents (CSG 9 5/8", CSG 13 3/8",
    LNR 5", LNR 7", Tie Back, Squeeze, Plug):

        1        Geothermal (True Vertical Depth)
        2-4      Densities / Max Pumping Time / Displacement Volume  (always)
        5-6      Hydrostatic Pressure / Pore & Frac Pressure          (only if has_open_hole_notes)
        next..   One "Mix above Additives" note per active slurry, in slurry order
        next..   Per slurry (same order): Fresh Water composition, Rheology
                 (Bingham Model), measured Thickening Time endpoint

    Mutates and returns `slurries_payload` with a new "note_mix" string on each
    slurry dict, and "note_freshwater" / "note_rheology" / "note_thickening"
    added inside each slurry's "lab" sub-dict. Also returns the fixed/global
    notes and a flat "all_notes" list (document order) for convenience.
    """
    # Section IX, including its existing NOTE 20, is preserved by user request.
    counter = NoteCounter(reserved_numbers={20})
    notes = {}

    # --- Notes 1-4: always present ---
    notes["note_geothermal"] = counter.next("The Calculated Temperature is based on True Vertical Depth.")

    notes["note_densities"] = counter.next("Densities are Displayed at P=1 atmosphere and T=70 degF.")

    # NOTE: "Safety Factor" pumping-time text — real documents show a value that
    # does not cleanly derive from total_pump_time_min alone (e.g. 330 min for a
    # ~240 min pumping schedule). Until the exact safety-factor rule is confirmed
    # with the engineer, this uses the app's own already-computed total pumping
    # time directly rather than guessing an unverified multiplier.
    reported_pump_time = (
        f"{round_half_up(total_pump_time_min, 0):.0f} min."
        if total_pump_time_min is not None and total_pump_time_min > 0
        else ".... min. [PUMP TIME NOT SET IN PHASE IV]"
    )
    notes["note_maxpump"] = counter.next(
        # NOTE: plain "&" here is correct and intentional. It used to be
        # hand-escaped to "&amp;" as a one-off patch (docxtpl silently drops
        # a bare "&" from any rendered value), but that risk is now handled
        # once, globally, for the whole context — see _escape_xml_special_chars()
        # right before build_master_context()'s return. Escaping it again
        # here would double-escape it into "&amp;amp;".
        f"Pumping time for Slurry & Displacement from the Phase IV schedule is {reported_pump_time}"
    )

    notes["note_dispvol"] = counter.next("The Volume of Displacement Should Be Calculated at Rig Site.")

    # --- Notes 5-6: conditional on job type (CSG/LNR/Tie Back only, not Plug/Squeeze/CSG 20") ---
    if has_open_hole_notes:
        notes["note_hydrostatic"] = counter.next("The Hydrostatic Pressure is Based on Mud Weight Density.")
        notes["note_porefrac"] = counter.next("The Pore and Frac Pressure is Based on Mud Weight Density.")
    else:
        notes["note_hydrostatic"] = ""
        notes["note_porefrac"] = ""

    # --- One "Mix Additives" note per active slurry, in slurry order ---
    for s in slurries_payload:
        tank = s.get("mixing_tank") or "Mud Reserve Tanks"
        total_water = s.get("total_water_bbl", 0.0)
        mix_note = f"Mix above Additives in {total_water:.1f} bbl Fresh Water at {tank}."
        dry_blends = [str(row.get("Name", "")).strip() for row in s.get("blends", [])
                      if str(row.get("Material Type", "")).strip().casefold() != "cement"
                      and str(row.get("Name", "")).strip()]
        if dry_blends:
            mix_note += f" (Note: {', '.join(dry_blends)} pre-blended dry with bulk cement)."
        s["note_mix"] = counter.next(mix_note)

    # --- Per slurry (same order): Fresh Water / Rheology / Thickening Time ---
    fw_phrase = (
        "Fresh water means total hardness in the 400 ppm range and salt in the 3000 ppm range."
        if freshwater_note_style == "total hardness"
        else "Fresh water means calcium in the 400 ppm range and salt in the 3000 ppm range."
    )
    for s in slurries_payload:
        lab = s.setdefault("lab", {})
        lab["note_freshwater"] = counter.next(fw_phrase)
        lab["note_rheology"] = counter.next("The Result of Rheology Test is based on Bingham Model.")
        # Thickening time is not a surface-sample hardness observation.
        endpoint = lab.get("thickening_endpoint", "Not specified")
        endpoint_text = endpoint if endpoint in ("70 Bc", "100 Bc") else "not specified"
        lab["note_thickening"] = counter.next(f"Reported thickening time endpoint: {endpoint_text}.")

    notes["slurries"] = slurries_payload
    notes["all_notes"] = (
        [notes["note_geothermal"], notes["note_densities"], notes["note_maxpump"], notes["note_dispvol"]]
        + ([notes["note_hydrostatic"], notes["note_porefrac"]] if has_open_hole_notes else [])
        + [s["note_mix"] for s in slurries_payload]
        + [x for s in slurries_payload for x in (s["lab"]["note_freshwater"], s["lab"]["note_rheology"], s["lab"]["note_thickening"])]
    )
    return notes


def parse_shoe_depth_from_hardware(hw_df, default_md=None, job_type="", placement_config=None):
    """Resolve a selected job-specific target; never infer it from row order or geo-MD."""
    return target_depth(hw_df, job_type, placement_config or {})


def _attach_placement_fields(payload, slurry_params, hw_df, job_type, placement_config):
    """BUG-04: populate the four placement keys the Word template's per-slurry
    placement block reads via s.get('top'/'bottom'/'excess_oh'/'excess_csg',
    '....'). bottom comes from the placement config's selected target row,
    top from the Phase V slurry top (with the above-target sanity check), and
    the two excess cells share the placement volume basis (dedicated per-side
    excess fields remain future work once Phase II/III captures them).

    Owner critique round (2026-09-28): the Volume Basis input documents itself
    as optional ("Leave blank to show that it was not supplied"), so a blank
    basis renders the honest 'N/A' marker in the two excess cells and must NOT
    block Word export. top/bottom keep the '....' fallback, which stays
    export-blocking through the build_master_context guard because a report
    without a real target depth would be misleading, not merely incomplete."""
    bottom_depth = target_depth(hw_df, job_type, placement_config or {})
    _bottom = f"{bottom_depth:.1f} m MD" if bottom_depth is not None else "...."
    _top_text, _top_val = top_label(slurry_params)
    if bottom_depth is not None and _top_val is not None and _top_val >= bottom_depth:
        _top_text = "...."
    payload["top"] = (_top_text
                      if slurry_params.get("top_mode") in ("Depth (m MD)", "Surface")
                      else "....")
    payload["bottom"] = _bottom
    basis = (str(placement_config.get("volume_basis") or "").strip()
             if placement_config.get("job_type") == job_type else "")
    payload["excess_oh"] = basis or "N/A"
    payload["excess_csg"] = basis or "N/A"
    return payload

def separate_lab_tables(lab_grid_df: pd.DataFrame):
    """
    Separates Phase VII lab grid into:
    1. lab_conventional: Cement (100% BWOB) + Dry Blend Powders + Total mass row
    2. lab_additives: Chemical Additives + Water (1.0 BWOW) + Total mass row
    """
    if lab_grid_df is None or not isinstance(lab_grid_df, pd.DataFrame) or lab_grid_df.empty:
        return [], []
    
    conv_rows = []
    adds_rows = []
    total_conv_mass = 0.0
    total_adds_mass = 0.0
    has_conv_mass = False
    has_adds_mass = False
    
    for _, r in lab_grid_df.iterrows():
        mat = str(r.get("Material", "")).strip()
        conc = str(r.get("Concentration", "")).strip()
        unit = str(r.get("Unit", "")).strip()
        mass_str = str(r.get("Mass", "")).strip()
        lot = str(r.get("Lot No", "")).strip()
        
        if not mat or mat in ["None", "nan"]:
            continue
            
        m_val = 0.0 if mass_str.lower() in ("", "-", "none", "nan") else clean_number(mass_str)
        mat_lower = mat.strip().lower()
        is_conventional = (
            "cement" in mat_lower or 
            "delijan" in mat_lower or 
            any(mat_lower == str(n).strip().lower() for n in materials_db.FORCED_DRY_BLEND_NAMES) or
            unit == "BWOB"
        )
        
        row_dict = {
            "Material Type": "Cement" if "cement" in mat.lower() or "delijan" in mat.lower() else mat,
            "Name": mat,
            "Code": mat,
            "Lot Number": lot if lot and lot != "-" else "-",
            "Concentration": conc,
            "Design Unit": unit,
            "Mass": mass_str if mass_str else "-"
        }
        
        if is_conventional:
            conv_rows.append(row_dict)
            if m_val > 0:
                total_conv_mass += m_val
                has_conv_mass = True
        else:
            adds_rows.append(row_dict)
            if m_val > 0:
                total_adds_mass += m_val
                has_adds_mass = True
                
    if has_conv_mass:
        conv_rows.append({
            "Material Type": "",
            "Name": "",
            "Code": "",
            "Lot Number": "",
            "Concentration": "",
            "Design Unit": "",
            "Mass": f"{total_conv_mass:.1f}"
        })
        
    if has_adds_mass:
        adds_rows.append({
            "Material Type": "",
            "Name": "",
            "Code": "",
            "Lot Number": "",
            "Concentration": "",
            "Design Unit": "",
            "Mass": f"{total_adds_mass:.1f}"
        })
        
    return conv_rows, adds_rows

def parse_tieback_host_label(hw_df, default_label=None, job_type="", placement_config=None):
    """Resolve the explicitly selected existing tubular; no nearest-depth guess."""
    return host_label(hw_df, job_type, placement_config or {})

def get_slurry_display_values(fluid_data: dict, slurry_name: str) -> tuple:
    """
    Returns (vol_str, den_str) for a slurry — plain, ready-to-embed display
    strings that already carry their unit (e.g. "41.0 bbl", "118 pcf").

    FIX: generate_executive_summary() previously read volume/density with
    Python dict.get() fallbacks like .get("volume", 41.0) or
    .get("density", "118"). Those numbers were only meant as function-default
    placeholders, but whenever the job type's expected slurry (almost always
    "Main") wasn't actually configured in Phase IV — wrong job type picked,
    slurry renamed, or simply not filled in yet — the exported Word document
    would silently print that fabricated number as if it were a real,
    deliberately entered design value, with no way for the reviewing engineer
    to tell the difference. This now returns an explicit "NOT SET IN PHASE IV"
    flag instead of inventing a plausible-looking number.
    """
    info = fluid_data.get(slurry_name)
    vol = info.get("volume") if info else None
    den = info.get("density") if info else None
    # F3 (P1-03): this display helper runs EARLY in build_master_context (via
    # synchronize_report_texts) for every fluid in the train — a malformed
    # volume (hostile project JSON) used to raise a raw float() ValueError
    # here, before the dedicated unreadable-volume gate further down ever got
    # a chance to speak. Junk now degrades to the honest ".... [NOT SET]"
    # marker (same convention as everywhere else); the real verdict comes
    # from the unreadable-volume gate, which blocks the export with a message
    # naming the offending fluid.
    vol_num = safe_float(vol, None)
    vol_str = f"{vol_num:.1f} bbl" if vol_num is not None and vol_num > 0 else ".... bbl [VOLUME NOT SET IN PHASE IV]"
    den_str = f"{den} pcf" if den not in (None, "") else ".... pcf [DENSITY NOT SET IN PHASE IV]"
    return vol_str, den_str

def generate_executive_summary(
    job_type: str, 
    fluid_data: dict, 
    active_fluids: list, 
    additives_dfs: dict, 
    hw_df: pd.DataFrame = None, 
    geo_md: float = 3000.0,
    cement_params: dict = None,
    placement_config: dict = None
) -> str:
    """
    Auto-generates authentic NIDC Executive Summary matching company standards:
    - Paragraph 1: Formal proposal preamble
    - Paragraph 2: Rig safety policy and pre-job safety meeting declaration
    - Paragraph 3: Dynamic operational summary (shoe depth, design type, slurry placement intervals, volumes & excess)
    """
    job_upper = str(job_type).upper()
    job_clean = job_type.replace('"', '').replace("CSG", "").replace("LNR", "").strip()
    
    p1 = ("Enclosed are our recommendations for NIDC Cement Engineering and Planning Department intervention "
          "on the referenced well. The proposal includes well data, materials and resources requirements.")
    
    p2 = ("NIDC has established a safety policy to which all NIDC personnel must adhere. A pre-job safety meeting "
          "will be held with client representatives and other on location personnel to familiarize everyone with existing "
          "hazards and safety procedures. We would appreciate close cooperation between the client representative and "
          "the NIDC representative to ensure a safe operation.")
    
    placement_config = placement_config or {}
    shoe_depth = parse_shoe_depth_from_hardware(hw_df, job_type=job_type, placement_config=placement_config)
    shoe_str = f"{shoe_depth:.1f} m MD" if shoe_depth is not None else ".... m MD [TARGET DEPTH NOT SELECTED IN PHASE II/III]"
    # Placement details belong to the job under which they were entered.
    # Phase X can be opened immediately after changing Job Type in Phase I,
    # before Phase II/III has had a chance to clear the previous job's basis.
    basis = (str(placement_config.get("volume_basis") or "").strip()
             if placement_config.get("job_type") == job_type else "")
    basis = basis or "[VOLUME BASIS NOT SET IN PHASE II/III]"

    def slurry_top(slurry):
        params = (cement_params or {}).get(slurry, {})
        if params.get("top_job_type") not in (None, job_type):
            return ".... m [TOP NOT SET IN PHASE V]", None
        text, value = top_label(params)
        if shoe_depth is not None and value is not None and value >= shoe_depth:
            # BUG-30: name the offending limit inside the token so the
            # operator sees the constraint without opening Phase II/III.
            return f".... m [TOP MUST BE ABOVE TARGET DEPTH {shoe_depth:.1f} m MD]", None
        return text, value
    
    slurry_archetypes = ["Main", "Lead", "Lead #1", "Lead #2", "Tail"]
    active_slurries = [
        f for f in active_fluids 
        if any(f.replace(" ", "").lower() == s.replace(" ", "").lower() for s in slurry_archetypes)
    ]
    
    has_dry_blend = False
    has_neat = False
    for s in active_slurries:
        df_adds = additives_dfs.get(s)
        if df_adds is not None and isinstance(df_adds, pd.DataFrame) and not df_adds.empty:
            for _, r in df_adds.iterrows():
                mat_type = str(r.get("Material Type", ""))
                r_name = str(r.get("Name", "") or "").strip()
                display_name = r_name if r_name and r_name != "Other (Custom)" else mat_type
                state = resolve_physical_state(mat_type, r.get("Physical State"))
                _, is_forced_dry = normalize_additive_mix(state, r.get("Mix Method"), display_name, mat_type)
                if is_forced_dry:
                    has_dry_blend = True
                else:
                    has_neat = True
        else:
            has_neat = True
            
    if has_dry_blend and has_neat and len(active_slurries) > 1:
        design_str = "Dry blend and neat cement design will be used"
    elif has_dry_blend:
        design_str = "Dry blend cement design will be used"
    else:
        design_str = "Neat cement design will be used"
        
    primary = "Main" if "Main" in active_slurries else (active_slurries[0] if active_slurries else "Main")
    primary_vol, primary_den = get_slurry_display_values(fluid_data, primary)
    # The placement sentence describes the primary slurry, but the rig will
    # pump every active slurry. List every volume when there is more than one.
    if len(active_slurries) > 1:
        volumes = "; ".join(
            f"{slurry}: {get_slurry_display_values(fluid_data, slurry)[0]}"
            for slurry in active_slurries
        )
        volume_statement = f"Planned slurry volumes: {volumes}"
    else:
        volume_statement = f"Planned slurry volume: {primary_vol}"
    if "PLUG" in job_upper:
        top, _ = slurry_top(primary)
        p3 = (f"Cement plug target depth is {shoe_str}. {design_str} for cement placement inside casing / open hole; "
              f"{primary_den} {primary.lower()} cement slurry is planned from {shoe_str} to {top}. "
              f"{volume_statement}; basis: {basis}.")
    elif "SQUEEZE" in job_upper:
        p3 = (f"{job_type} treatment depth is {shoe_str}. {design_str} for this zone; "
              f"{primary_den} {primary.lower()} cement slurry is planned at {shoe_str}. "
              f"{volume_statement}; basis: {basis}.")
    elif "TIE BACK" in job_upper:
        top, _ = slurry_top(primary)
        host = parse_tieback_host_label(hw_df, job_type=job_type, placement_config=placement_config)
        host = host or "[HOST NOT SELECTED IN PHASE II/III]"
        p3 = (f"{job_type} target depth is {shoe_str}. {design_str} for this tie back; "
              f"{primary_den} {primary.lower()} cement slurry is planned from {shoe_str} to {top} "
              f"inside {host}. {volume_statement}; basis: {basis}.")
    else:
        kind = "Liner" if "LNR" in job_upper else "Casing"
        placement_parts = []
        volume_parts = []
        bottom = shoe_str
        bottom_depth = shoe_depth
        # The last pumped slurry is deepest. Every top is an entered Phase-V
        # depth (or an explicit Surface choice); unknown intervals remain marked.
        for slurry in reversed(active_slurries):
            volume, density = get_slurry_display_values(fluid_data, slurry)
            top, top_depth_value = slurry_top(slurry)
            if bottom_depth is not None and top_depth_value is not None and top_depth_value >= bottom_depth:
                # BUG-30: same as the target-depth token — print the actual
                # limit value instead of an unquantified complaint.
                top, top_depth_value = f".... m [TOP MUST BE ABOVE PREVIOUS INTERVAL {bottom_depth:.1f} m MD]", None
            placement_parts.append(f"{density} {slurry.lower()} cement slurry from {bottom} to {top}")
            volume_parts.append(f"{slurry}: {volume}")
            bottom = top
            bottom_depth = top_depth_value
        intervals = "; ".join(placement_parts) if placement_parts else "[NO CEMENT SLURRY CONFIGURED IN PHASE IV]"
        volumes = "; ".join(volume_parts) if volume_parts else "[NO CEMENT SLURRY CONFIGURED IN PHASE IV]"
        p3 = (f"{job_type} {kind.lower()} target depth is {shoe_str}. {design_str} for this {kind.lower()}; "
              f"planned placement: {intervals}. Planned slurry volumes: {volumes}; basis: {basis}.")

    return f"{p1}\n\n{p2}\n\n{p3}"

def build_additives_mixing_procedure(slurry_name: str, additives_df: pd.DataFrame) -> str:
    """
    Constructs company-standard additive mixing instructions for mix water solution.

    Timing rule (confirmed against all 8 real reference procedures): every
    additive mixes for 10 min. by default, EXCEPT Defoamer/Anti Foam (5 min.)
    and Salt/NaCl, Bentonite, or CaCl2 (45 min.) — regardless of that
    material's position in the list. Whichever additive is *last* in the row
    order always gets "until the cement operation will finish." instead of a
    timed duration, overriding any of the above. "to Fresh Water" is attached
    to whichever additive is *first* in the row order (the app's convention
    is to always place Defoamer first, but this is now a positional rule,
    not a name-based one, so it stays correct even if a slurry has no
    Defoamer at all, or the rows are ever reordered).
    """
    if additives_df is None or not isinstance(additives_df, pd.DataFrame) or additives_df.empty:
        return ""
    
    valid_adds = []
    for _, r in additives_df.iterrows():
        name = str(r.get("Name") or "").strip()
        mat_type = str(r.get("Material Type") or "").strip()
        display_name = name if name and name != "Other (Custom)" else mat_type
        if not display_name or display_name in ["None", "nan", "Other (Custom)"]:
            continue
        valid_adds.append(display_name)
            
    if not valid_adds:
        return f"{slurry_name} Cement Solution mixing procedure:\n           Mix neat cement slurry without chemical additives."
        
    lines = [f"{slurry_name} Cement Solution mixing procedure:"]
    for i, add_name in enumerate(valid_adds):
        is_first = (i == 0)
        is_last = (i == len(valid_adds) - 1)
        name_lower = add_name.lower()
        
        if "defoam" in name_lower or "anti foam" in name_lower or "antifoam" in name_lower:
            mix_time = "5 min."
        elif "cacl2" in name_lower or "salt" in name_lower or "nacl" in name_lower or "bentonite" in name_lower:
            mix_time = "45 min."
        else:
            mix_time = "10 min."

        to_water = "to Fresh Water " if is_first else ""
            
        if is_last:
            lines.append(f"           Add {add_name} {to_water}and allow mixing until the cement operation will finish.")
        else:
            lines.append(f"           Add {add_name} {to_water}and allow mixing for {mix_time}")
            
    return "\n".join(lines)

def generate_official_procedure(
    job_type: str, 
    fluid_data: dict, 
    active_fluids: list, 
    cement_params: dict, 
    additives_dfs: dict, 
    preflush_calc: dict, 
    geo_md: float = 3000.0,
    pump_time_min: float = 0.0,
    placement_config: dict = None
) -> str:
    """
    Constructs the 100% authentic, company-standard cementing procedure
    matching the exact template archetype for the selected job_type.
    """
    job_upper = str(job_type).upper()
    sc = StepCounter()

    def numbered_block(items):
        """Numbers each real line in a list individually, in order, via the
        shared step counter; joined back into one newline-separated block."""
        return "\n".join(sc.next(x) for x in items if x)
    
    slurry_archetypes = ["Main", "Lead", "Lead #1", "Lead #2", "Tail"]
    active_slurries = [
        f for f in active_fluids 
        if any(f.replace(" ", "").lower() == s.replace(" ", "").lower() for s in slurry_archetypes)
    ]
    
    first_slurry = active_slurries[0] if active_slurries else "Main"
    tank_name = cement_params.get(first_slurry, {}).get("tank_name") or "[MIXING TANK NOT SET IN PHASE V]"
        
    # FIX (confirmed against LNR_5_in.docx / LNR_7_in.docx): standalone LNR
    # jobs omit the "Main:" prefix on this single-slurry water line ("21.0
    # bbl", not "Main: 21.0 bbl"), unlike SQUEEZE/CSG-surface/TIE BACK LNR
    # which all keep it. Deliberately checks "TIE BACK" not in job_upper too
    # — job_type for a tie-back liner (e.g. 'TIE BACK LNR 7"') also contains
    # the substring "LNR", but TB_LNR_7_in.docx confirms it must KEEP
    # "Main: 110.0 bbl", so a bare `"LNR" in job_upper` check would have
    # wrongly stripped the prefix from tie-back jobs too.
    is_standalone_lnr = "LNR" in job_upper and "TIE BACK" not in job_upper

    water_parts = []
    for s in active_slurries:
        p_s = cement_params.get(s, {})
        mw = float(p_s.get("mix_water") or 0.0)
        water = f"{mw:.1f} bbl" if mw > 0 else ".... bbl [MIX WATER NOT SET IN PHASE V]"
        if len(active_slurries) > 1:
            water_parts.append(f"{s}: {water}")
        else:
            no_main_prefix = ("PLUG" in job_upper) or is_standalone_lnr
            water_parts.append(water if no_main_prefix else f"Main: {water}")
    water_vols_str = " & ".join(water_parts) if water_parts else ".... bbl [MIX WATER NOT SET IN PHASE V]"
    
    mixing_blocks = []
    for s in active_slurries:
        df_adds = st.session_state.get(f"cement_calc_{s}")
        block = (build_additives_mixing_procedure(s, df_adds) if isinstance(df_adds, pd.DataFrame)
                 else f"{s}: [ADDITIVES NOT CALCULATED IN PHASE V]")
        if block:
            mixing_blocks.append(block)
    mixing_proc_text = "\n".join(mixing_blocks)
    
    pf_line = ""
    if preflush_calc and float(preflush_calc.get("volume_bbl", 0.0)) > 0:
        pf_vol = float(preflush_calc.get("volume_bbl", 0.0))
        pf_den = str(preflush_calc.get("density_pcf") or ".... [DENSITY NOT SET IN PHASE IV]")
        pf_type = str(preflush_calc.get("type", "Combined (Water + NaCl + Wash)"))
        wash_amt = float(preflush_calc.get("wash_gal", 0.0))
        
        if pf_type == "Fresh Water Only":
            pf_line = f"Pump {pf_vol:.1f} bbl fresh water as pre flush."
        elif pf_type == "Brine (Water + NaCl)":
            pf_line = f"Pump {pf_vol:.1f} bbl Salt Saturated water as pre flush.({pf_den} pcf)"
        elif pf_type == "Water + Chemical Wash":
            pf_line = f"Pump {pf_vol:.1f} bbl fresh water mix with {wash_amt:.0f} gal chemical wash as preflush.({pf_den} pcf)"
        else:
            pf_line = f"Pump {pf_vol:.1f} bbl salt saturated water mix with {wash_amt:.0f} gal chemical wash as preflush." if "13" in job_upper else f"Pump {pf_vol:.1f} bbl salt saturated water mix {wash_amt:.0f} gal chemical wash as preflush.({pf_den} pcf)"
            
    spacer_lines = {}
    slurry_lines = {}
    for name in active_fluids:
        volume, density = get_slurry_display_values(fluid_data, name)
        if name in {"Spacer Ahead", "Spacer", "Spacer Behind"}:
            spacer_lines[name] = f"Pump {volume} as {name} ({density})."
        elif name in slurry_archetypes:
            slurry_lines[name] = f"Mix and pump {volume} {name} cement slurry ({density})."
    # Do not group spacers: a behind spacer must follow all preceding slurries.
    pump_lines = [(pf_line if name == "Pre Flush" else
                   spacer_lines.get(name) or slurry_lines.get(name))
                  for name in active_fluids]
    pump_lines = [line for line in pump_lines if line]
    pump_steps = numbered_block(pump_lines)

    if "PLUG" in job_upper:
        plug_depth = target_depth(st.session_state.get("hardware_table", pd.DataFrame()), job_type, placement_config or {})
        target_label = f"{plug_depth:.1f} m MD" if plug_depth is not None else ".... m MD [TARGET DEPTH NOT SELECTED IN PHASE II/III]"
        # FIX: p_time and min_r used to fall back to hardcoded literals (150 min,
        # 4.0 bbl/min) that were never derived from anything the user entered —
        # a field engineer reading the exported document couldn't tell these
        # apart from a real, deliberately calculated value. p_time now only
        # renders a real number when pump_time_min was actually computed from
        # Phase IV; min rate is now the minimum of the actually-configured
        # pump rates (Phase IV's own "min_rate" per fluid) instead of an
        # invented constant. Both fall back to an explicit "NOT SET" flag.
        p_time_str = f"{int(round(pump_time_min))} min." if pump_time_min > 0 else ".... min. [PUMP TIME NOT SET IN PHASE IV]"
        configured_rates = [
            clean_number(fluid_data[f].get("min_rate"))
            for f in active_fluids
            if f in fluid_data and fluid_data[f].get("min_rate") not in (None, "", 0.0)
        ]
        min_rate_str = f"{min(configured_rates):.0f} bbl/ min." if configured_rates else ".... bbl/ min. [PUMP RATE NOT SET IN PHASE IV]"
        lines = [
            "IX. Cementing Procedure",
            sc.next(f"Clean up {tank_name} and preparing chemicals for mixing fluid."),
            sc.next(f"Fill up {tank_name} with {water_vols_str} fresh water for mixing fluid."),
            sc.next('Before running 5" & 31/2" drill pipe finished; with Company man approval, start mixing cement additives and prepare mixing fluid according below cement mixing procedure:'),
            mixing_proc_text,
            sc.next(f"After running drill pipe to {target_label}, install circulating cement head (swage), start circulation at least one drill pipe cap volume."),
            sc.next("Pre job safety meeting with involved personnel and arrange with mud engineer to measure drilling fluid & cement loss/gain during cement job."),
            sc.next("Test cement line W/ 3000 psi"),
            pump_steps,
            sc.next("Displace cement with … bbl drilling fluid. (calculate at rig site)"),
            sc.next(f"Max time for Mix and pump slurry / displacement, {p_time_str}"),
            sc.next(f"Min rate for pump slurry / displacement, {min_rate_str}"),
            sc.next("POOH ... stand drill pipe. flush string, then 5 stand drill pipe , then close well and hold ... psi pressure on top of the cement until cement sets."),
            sc.next("wait for cement to get hard.(12 hours).")
        ]
        return sc.finalize("\n".join([l for l in lines if l.strip()]))

    elif "SQUEEZE" in job_upper:
        clean_mix = mixing_proc_text
        clean_mix = re.sub(r'(?im)^\s*[^\n:]+ Cement Solution mixing procedure:\s*', '', clean_mix).strip()
        lines = [
            "VIII. Cementing Procedure",
            sc.next(f"Clean up {tank_name} and preparing chemicals for mixing fluid."),
            sc.next(f"Fill up {tank_name} with Fresh water ({water_vols_str}) for mixing fluids."),
            sc.next('Before finished 5 & 3 1/2 in Drill Pipe with Co. man approval, start mixing cement additives and preparing mixing fluids according to below.'),
            "Squeeze Cement mixing procedure:",
            clean_mix,
            sc.next("After running drill pipe and RTTS packer , install circulating cement head (swage), start circulation at least one drill pipe cap volume."),
            sc.next("Pre job safety meeting with involved personnel and arrange with mud engineer to measure drilling fluid during cement job."),
            sc.next("Setting RTTS packer to …. m, and mud circulation by circulating valve."),
            sc.next("Test cements line W/ 4000 psi."),
            sc.next("Close circulating valve, if injectivity pressure up to 3000 psi, just monitor the annulus, for more than 3000 psi close pipe rams and apply 1000 psi in annulus.(on the packer)."),
            sc.next("Perform injectivity test with drilling fluid by pump truck."),
            sc.next("Maximum pressure is.… and maximum rate is …. ."),
            sc.next("Release string pressure and record volume of returned mud in the displace tank pump truck."),
            sc.next("Release pressure on the packer and open circulating valve and circulate mud."),
            pump_steps,
            sc.next("Displaced 70% of the internal volume of string(Calculate at rig), close circulating valve, continue displaced and inject cement with…. bbl drilling fluid with maximum rate and pressure. (displace cement to …. meters under RTTS packer). (Calculate at rig)."),
            sc.next("Close the cement line valve on top of the string and release cement line pressure."),
            sc.next("wait on Cement to get Hard.")
        ]
        return sc.finalize("\n".join(lines))

    elif "TIE BACK" in job_upper:
        tb_sz = '7"' if "7" in job_upper else '5"'
        lines = [
            "X. Cementing Procedure",
            sc.next(f"Clean up {tank_name} and preparing chemicals for mixing fluid."),
            sc.next(f"Fill up {tank_name} with Fresh water ({water_vols_str}) for mixing fluids."),
            sc.next(f'Before finished running {tb_sz} Tie Back with Co.man approval, start mixing cement additives and preparing mixing fluids according to below.'),
            mixing_proc_text,
            sc.next("Before running Liner, check Plug Dropping Head assembly Specially Pump down Plug release Handle."),
            sc.next(f'After Tie Back assembly reach {tb_sz} liner lap, prepare circulation at least one annular volume.'),
            sc.next(f'When the Tie back assembly reached {tb_sz} liner lap, connected plug dropping and arrange with mud engineer to measure drilling fluid & cement loss/gain during cement job.'),
            sc.next("prepare pre job safety meeting with involved personnel and arrange with mud engineer to measure drilling fluid & cement loss/gain during cement job."),
            sc.next("Stop circulation, connect cement line, set the data acquisition system and calibrate it with cement unit."),
            sc.next("Tests cement line W/ 3500 psi."),
            pump_steps,
            sc.next("Release pump down plug."),
            sc.next("Displace cement with .... bbl. drilling fluid, slow pump rate down to 3 bbl/ minute, last 10 bbl of displacement volume."),
            sc.next("Select down Tie back seal assembly into Tie Back sleeve."),
            sc.next("Bleed off pressure and monitor U-Tube return."),
            sc.next("Rig down cement line."),
            sc.next("Wait on cement.")
        ]
        return sc.finalize("\n".join([l for l in lines if l.strip()]))

    elif "LNR" in job_upper:
        lnr_sz = "7 in" if "7" in job_upper else "5 in"
        hold_psi = "100" if "7" in job_upper else "150"
        has_rot_note = "7" in job_upper
        # FIX (confirmed): these three notes must number sequentially as a
        # single run — for 7" (rotation note present) they are Note1/Note2/
        # Note3; for 5" (no rotation note) they are Note1/Note2. The rotation
        # note used to be hardcoded as "Note1" while the shoe-track note
        # below was ALSO always hardcoded as "Note1" regardless of whether
        # the rotation note was present, so the 7" case produced a document
        # with two different "Note1"s and no "Note3" at all — confirmed
        # against LNR_7_in.docx, which numbers all three sequentially.
        _n = 1
        rot_note = ""
        if has_rot_note:
            rot_note = f"Note{_n}: During cementing operation,the liner string should be raised and lowered with a 7 in liner, as well as the rotational movement of the string."
            _n += 1
        shoe_track_note = f"Note{_n}: If plug does not bump, do not displace more than %25 of the calculated shoe track."
        _n += 1
        bumping_note = f"Note{_n}: If observed bumping, increase pressure to 3000 psi and hold for 15 min due to liner integrity test.(Optional)"
        lines = [
            "X. Cementing Procedure",
            sc.next(f"Clean up {tank_name} and preparing chemicals for mixing fluid."),
            sc.next(f"Fill up {tank_name} with Fresh water ({water_vols_str}) for mixing fluids."),
            sc.next(f"Before finished running {lnr_sz} Liner with Co. man approval, start mixing cement additives and preparing mixing fluids according to below."),
            mixing_proc_text,
            sc.next("Before running Liner, check Plug Dropping Head Assembly Specially Pump down Plug Release Handle."),
            sc.next("Before Liner shoe reach open hole, prepare circulation at least one annular volume."),
            sc.next("When the Liner shoe reached the bottom, connected Plug dropping head assembly then start circulation at least one annular volume."),
            sc.next("pre job safety meeting with involved personnel and arrange with mud engineer to measure drilling fluid & cement loss/gain during cement job."),
            sc.next("Stop circulation, connect cement line, set the data acquisition system and calibrate it with cement unit."),
            sc.next("Test cement line W/ 3500 psi."),
            pump_steps,
            sc.next("Release pump down plug."),
            sc.next("Displace cement with…….bbl drilling fluid, If does not observe bumping pressure, you will pump additional displacement liquid (Drilling Fluid) Max 25% Shoe track volume.(calculate at rig site)"),
            rot_note,
            sc.next("Watch for indication of drill pipe plug latching into liner, wiper plug on pressure gauge."),
            sc.next("If this pressure indication is seen, recalculate total displacement volume. The new displacement volume will be the actual displacement volume for drill pipe plus the calculated liner volume."),
            sc.next("Slow  pump rate down to 3 bbl/ minute, last 10 bbl of displacement volume."),
            shoe_track_note,
            bumping_note,
            sc.next("Bleed off pressure and monitor U-Tube return."),
            sc.next("Monitoring return line for checking float collar and float shoe."),
            sc.next(f"Pull out .... drill pipe stands or above the top of the cement, flush string, then pull out .... drill pipe stands, shut off the well, and hold {hold_psi} psi pressure on top of the cement to prevent gas migration until cement sets."),
            sc.next("Rig down cement line and Wait on cement to get hard.")
        ]
        return sc.finalize("\n".join([l for l in lines if l.strip()]))

    elif any(s in job_upper for s in ["20", "24", "30", "18"]):
        # FIX (confirmed): this branch is shared by CSG 20"/24"/30"/18-5/8",
        # but the procedure text used to hardcode "20"" literally regardless
        # of which of the four was actually selected. The casing size is now
        # read straight from job_type itself (e.g. 'CSG 24"' -> '24"',
        # 'CSG 18 5/8"' -> '18 5/8"') instead of being a fixed string.
        csg_size = job_type.replace("CSG ", "").strip()
        lines = [
            "X. Cementing Procedure",
            sc.next(f"Clean up {tank_name} and preparing chemicals for mixing fluid."),
            sc.next(f"Fill up {tank_name} with Fresh water ({water_vols_str}) for mixing fluids."),
            sc.next("Before finished running casings with Co. man approval, start mixing cement additives and preparing mixing fluids according to below."),
            mixing_proc_text,
            sc.next(f'Before running {csg_size} casing, check the stinger and stab-in shoe & Install stab-in shoe to end of second casing.'),
            sc.next(f'After running {csg_size} casing install stinger to end of first 5 " drill pipe.'),
            sc.next('RIH to bottom with 5 " drill pipe, Circulate mud before setting the stinger.'),
            sc.next("Set the stinger & circulate mud again. If you observe mud flowing in casing, try again to set the stinger."),
            sc.next('Hang 5 " drill pipe.'),
            sc.next("Pre job safety meeting with involved personnel."),
            sc.next("Stop circulation, connect cement line, set the data acquisition system and calibrate it with cement unit."),
            sc.next("Tests cement line W/ 3500 psi."),
            # FIX (found during bug hunt): this fell back to a specific,
            # plausible-looking hardcoded volume ("60.0 bbl") whenever Pre
            # Flush wasn't actually configured in Phase IV — the exact same
            # "looks real but was never entered" issue already fixed
            # elsewhere in this file (see get_slurry_display_values and the
            # PLUG branch's min-rate/pump-time fallbacks). Standardized to
            # the same explicit "NOT CONFIGURED" convention.
            pump_steps,
            "Note: If cement slurry returns to surface during operation, stop pumping slurry and displace cement slurry with … bbl drilling fluid (3 bbl short of calculated displacement volume).",
            sc.next("Sting out and check for float valve working."),
            sc.next(f'Circulate to clean out {csg_size} casing & Inner string..'),
            sc.next("At the same time the cementer to wash pump truck and cement line & other things."),
            sc.next("Pull out inner string and lay down stinger."),
            sc.next("Wait on cement.")
        ]
        return sc.finalize("\n".join([l for l in lines if l.strip()]))

    else:
        bump_psi = 1500 if "13" in job_upper else 3000
        test_psi = 3000
        woc_str = "Wait on cement." if bump_psi == 1500 else "Wait on cement.(12 hours)"
        lines = [
            "X. Cementing Procedure",
            sc.next(f"Clean up {tank_name} and preparing chemicals for mixing fluid."),
            sc.next(f"Fill up {tank_name} with Fresh water ({water_vols_str}) for mixing fluids."),
            sc.next("Before finished running casings with Co. man approval, start mixing cement additives and preparing mixing fluids according to below."),
            mixing_proc_text,
            sc.next("Before running casing, check cement head specially plunger of released cement plug and put the Top & Bottom plug."),
            sc.next("After running Casing, install circulating swage, start circulation at least one casing cap volume."),
            sc.next("Pre job safety meeting with involved personnel and arrange with mud engineer to measure drilling fluid & cement loss/gain during cement job."),
            sc.next("Stop circulation, connect cement line, set the data acquisition system and calibrate it with cement unit."),
            sc.next(f"Test cement line W/ {test_psi} psi"),
            pump_steps,
            sc.next("Release Top plug while pump 2.0 bbl Water by cement unit."),
            sc.next("Displace cement with…….bbl drilling fluid, If does not observe bumping pressure, you will pump additional displacement liquid (Drilling Fluid) Max 25% Shoe track volume.(calculate at rig site)"),
            f"                    NOTE: If observed Bumping to {bump_psi} psi while displacing cement slurry,hold pressure for  ",
            "                                15 minute. and assume bumping pressure as Casing integrity test.",
            sc.next("Release Casing Pressure."),
            sc.next("Monitoring return line for checking Float Collar and Float Shoe."),
            sc.next("Rig down Cement Line."),
            sc.next(woc_str)
        ]
        return sc.finalize("\n".join([l for l in lines if l.strip()]))

def _escape_xml_special_chars(value):
    """
    Recursively walks a context value (dict/list/str/anything else) and
    escapes "&", "<", and ">" in every string found, leaving non-string
    values untouched. Order matters: "&" must be escaped first, or escaping
    "<"/">" first would corrupt the "&" inside the "&lt;"/"&gt;" entities
    just introduced (turning them into "&amp;lt;"/"&amp;gt;").

    Why: confirmed via an isolated minimal-template test that the installed
    docxtpl version silently DROPS a bare "&" or "<" from any rendered value
    rather than erroring or escaping it — e.g. "Slurry & Displacement" renders
    as "Slurry  Displacement" and "Depth < 3000m" renders as "Depth  3000m",
    both with the character simply gone. ">" alone was fine, but is escaped
    too here for symmetry — costs nothing and removes any doubt. This affects
    any free-text field anywhere in the app that could contain these
    characters (Well Name, Client, Rig Name, a custom Material Name, a
    manually-typed note, ...), not just the Cementing Procedure text. Applied
    once, here, to the whole context right before it reaches docxtpl, rather
    than patching individual f-strings throughout the codebase one at a time.
    (Previously named _escape_ampersands — renamed since it now also covers
    "<"/">", not just "&".)
    """
    if isinstance(value, str):
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if isinstance(value, dict):
        return {k: _escape_xml_special_chars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_escape_xml_special_chars(v) for v in value]
    return value


def synchronize_report_texts():
    state = st.session_state
    job = state.get("job_type", 'CSG 20"')
    active = state.get("fluids_config", {}).get("active", [])
    fluids = state.get("fluid_data", {})
    params = state.get("cement_params", {})
    additives = state.get("cement_additives_dfs", {})
    hardware = state.get("hardware_table", pd.DataFrame())
    depth = float(state.get("geo_md", 3000.0))
    preflush = state.get("preflush_calc")
    pump_time = state.get("total_pump_time_min", 0.0)
    placement = state.get("placement_config", {})
    summary_source = [job, active, fluids, params, additives, hardware, depth, placement]
    procedure_source = [job, active, fluids, params, additives, preflush, depth, pump_time, placement,
                        {name: state.get(f"cement_calc_{name}") for name in active}]
    specs = {
        "exec_summary_text": {
            "generated": generate_executive_summary(job, fluids, active, additives, hardware, depth, params, placement),
            "signature": fingerprint([1, summary_source]),
        },
        "procedure_text": {
            "generated": generate_official_procedure(job, fluids, active, params, additives, preflush, depth, pump_time, placement),
            "signature": fingerprint([1, procedure_source]),
        },
    }
    for key, spec in specs.items():
        spec["pending"] = sync_report_text(state, key, spec["generated"], spec["signature"])
    return specs


def validate_manual_numbering(state, specs, generated_notes):
    """Reject collisions in reviewed edits without rewriting the engineer's text."""
    reserved = {20}
    reserved.update(int(n) for note in generated_notes
                    for n in re.findall(r"(?mi)^\s*NOTE\s+(\d+)\s*:", note))
    added_notes = set()
    for key, label in (("exec_summary_text", "Executive summary"),
                       ("procedure_text", "Cementing procedure")):
        current = state.get(key, "")
        generated = specs[key]["generated"]
        if current == generated:
            continue
        if key == "procedure_text":
            steps = [int(n) for n in re.findall(r"(?m)^\s*(\d+)\.\s+", current)]
            if steps and steps != list(range(1, len(steps) + 1)):
                raise ValueError("Cementing procedure: manually numbered steps must run from 1 in order without duplicates")
        original = re.findall(r"(?mi)^\s*NOTE\s+(\d+)\s*:", generated)
        original_counts = {n: original.count(n) for n in set(original)}
        for token in re.findall(r"(?mi)^\s*NOTE\s+(\d+)\s*:", current):
            if original_counts.get(token, 0):
                original_counts[token] -= 1
                continue
            number = int(token)
            if number in reserved or number in added_notes:
                raise ValueError(f"{label}: NOTE {number} conflicts with another numbered note in the report")
            added_notes.add(number)


def _store_report_edit(text_key, widget_key):
    st.session_state[text_key] = st.session_state[widget_key]


def _render_report_editor(key, spec, label, height, widget_key, regenerate_label):
    if spec["pending"]:
        st.warning("Inputs changed, or this text came from an older project. Your text is preserved. Review it, then keep it or regenerate before export.")
        with st.expander("Preview text generated from current inputs"):
            st.text(spec["generated"])
    if st.button(regenerate_label, key=f"_regenerate_{key}",
                 help="Replace this text with the current generated version. A manual version is retained for Restore previous text."):
        accept_report_text(st.session_state, key, spec["generated"], spec["signature"], replace=True)
        st.session_state[widget_key] = st.session_state[key]
        st.rerun()
    if spec["pending"] and st.button("Keep reviewed text", key=f"_keep_{key}",
                                     help="Confirm that your current text applies to the changed inputs."):
        accept_report_text(st.session_state, key, spec["generated"], spec["signature"])
        st.rerun()
    if st.session_state.get("report_text_state", {}).get(key, {}).get("history"):
        if st.button("Restore previous manual text", key=f"_restore_{key}"):
            restore_previous_text(st.session_state, key)
            st.session_state[widget_key] = st.session_state[key]
            st.rerun()
    # Callback captures typing before synchronization; canonical text survives navigation.
    st.session_state[widget_key] = st.session_state[key]
    st.text_area(label, height=height, key=widget_key,
                 on_change=_store_report_edit, args=(key, widget_key))


@st.cache_data(show_spinner=False)
def _load_template_bytes(template_path: str, mtime: float) -> bytes:
    """BUG-28: master_template.docx used to be re-read and re-hashed on every
    Phase X rerun (and again on each Build). Cache the bytes keyed by
    path+mtime — replacing the template file changes its mtime and the cache
    invalidates naturally."""
    with open(template_path, "rb") as handle:
        return handle.read()


def document_signature(context, template_path):
    mtime = os.path.getmtime(template_path) if os.path.exists(template_path) else 0.0
    template_hash = hashlib.sha256(_load_template_bytes(str(template_path), mtime)).hexdigest()
    return fingerprint({"context": {k: v for k, v in context.items() if k != "generated_timestamp"},
                        "template": template_hash})


# BUG-32: the single source of truth for "which bracketed tokens mark an
# unresolved operational input". The optional VOLUME BASIS explanation is
# deliberately excluded (VOLUME(?! BASIS)) — both the export gate and the
# Phase X pre-render warning must consume THIS pattern so they can never
# contradict each other again.
UNRESOLVED_INPUT_TOKEN = re.compile(
    r"\[(?:TOP|TARGET DEPTH|HOST|VOLUME(?! BASIS)|MIX WATER|MIXING TANK|PUMP|ADDITIVES|DENSITY)[^\]]*\]",
    flags=re.IGNORECASE,
)


def unresolved_export_inputs(specs):
    """Find missing operational data in generated or manually reviewed text.

    A volume-basis explanation is optional when no excess was specified.
    Target depth, slurry top and the other marked operational inputs are
    required to issue a complete Word procedure.
    """
    found = {
        match.group(0)
        for key, spec in specs.items()
        for content in (spec["generated"], st.session_state.get(key, ""))
        for match in UNRESOLVED_INPUT_TOKEN.finditer(content)
    }
    return sorted(found)


def build_master_context(*, calculations_prepared=False) -> dict:
    """
    Consolidates state from Phases I through VII into a unified dictionary
    ready for template rendering via docxtpl with full separation of
    Blend Data vs Additives Data, Conventional vs Additives Lab, and Pre-flush rows.
    """
    # The export screen has already refreshed calculations this rerun; direct
    # callers still get a fresh validation by default.
    issues = [] if calculations_prepared else prepare_calculations(st.session_state)
    if issues:
        raise ValueError(" | ".join(issues))
    if not any(name in {"Main", "Lead", "Lead #1", "Lead #2", "Tail"}
               for name in st.session_state.get("fluids_config", {}).get("active", [])):
        invalidate_document(st.session_state)
        raise ValueError("Phase IV: select at least one cement slurry before Word export.")
    # Read the two state sources the F3 gate needs BEFORE any report-text
    # synchronization consumes the volumes — the gate must be the first to
    # speak so its message can name the offending fluid.
    fluid_data = st.session_state.get("fluid_data", {})
    active_fluids = st.session_state.get("fluids_config", {}).get("active", [])
    active_slurries = active_slurry_names(active_fluids)
    # F3 (P1-03, owner-approved 2026-09-29): one unreadable numeric volume in
    # any fluid that feeds this report must surface as a CONTROLLED
    # export-block naming the offender — never as a raw float() ValueError
    # from inside the payload layer (uncaught crash screen) and never as a
    # silent 0.0 bbl row (fabricated report). Reachable only via a malformed
    # project JSON (Phase IV's own widgets always emit floats); same
    # philosophy as the placement '....' gate further below.
    _volume_sources = list(active_slurries) + [
        n for n in ("Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind")
        if n in active_fluids]
    unreadable_volumes = sorted(
        f"{name} → volume ({fluid_data[name].get('volume')!r})"
        for name in dict.fromkeys(_volume_sources)
        if isinstance(fluid_data.get(name), dict)
        and fluid_data[name].get("volume") is not None
        and safe_float(fluid_data[name].get("volume"), None) is None)
    if unreadable_volumes:
        invalidate_document(st.session_state)
        raise ValueError("Unreadable numeric volume in Phase IV fluid data — "
                         "open Phase IV to repair it: "
                         + ", ".join(unreadable_volumes))
    specs = synchronize_report_texts()
    if any(spec["pending"] for spec in specs.values()):
        invalidate_document(st.session_state)
        raise ValueError("Review the preserved manual report text before export.")
    missing = unresolved_export_inputs(specs)
    if missing:
        invalidate_document(st.session_state)
        raise ValueError("Complete the marked operational inputs before Word export: "
                         + ", ".join(missing))
    doc_ctrl = st.session_state.get("doc_control", {})
    well_data = st.session_state.get("well_data", {})
    # fluid_data / active_fluids / active_slurries were already read above the
    # F3 unreadable-volume gate.
    job_type = st.session_state.get("job_type", "CSG 20\"")
    
    # 1. Hardware Table Serialization
    hw_df = st.session_state.get("hardware_table", pd.DataFrame())
    hardware_list = hw_df.to_dict(orient="records") if not hw_df.empty else []
    
    # 2. Fluids Train Sequence Serialization
    fluids_train = [fluid_data[f] for f in active_fluids if f in fluid_data]
            
    # 3. Cement Slurry Payloads (Segregated Blend Data & Additives Data)
    # active_slurries comes from active_slurry_names() above the F3 gate.
    slurries_payload = []
    
    for s in active_slurries:
        p = st.session_state.get("cement_params", {}).get(s, {})
        vol = float(fluid_data.get(s, {}).get("volume", 0.0))
        yd = float(p.get("yield", 1.18))
        total_sacks = float(p.get("total_sacks") or (round_half_up((vol * 5.6146) / yd, 1) if yd > 0 else 0.0))

        # A) Blend Data (سیمان پایه G Delijan + پودرهای خشک بلِند)
        blend_df = st.session_state.get(f"cement_blend_{s}", pd.DataFrame())
        blend_rows = blend_df.to_dict(orient="records") if not blend_df.empty else []
        
        # B) Additives Data (فقط مواد محلول در آب اختلاط)
        adds_df = st.session_state.get(f"cement_calc_{s}", pd.DataFrame())
        adds_rows = adds_df.to_dict(orient="records") if not adds_df.empty else []
        
        # C) Lab Data (تفکیک دقیق Conventional از Additives)
        lab_info = st.session_state.get(f"lab_payload_{s}", {})
        lab_grid_df = lab_info.get("grid", pd.DataFrame())
        lab_rows = lab_grid_df.to_dict(orient="records") if isinstance(lab_grid_df, pd.DataFrame) and not lab_grid_df.empty else []
        conv_rows, lab_adds_rows = separate_lab_tables(lab_grid_df)

        # Compressive Strength: pre-resolve which test (UCA vs CRUSH) is active
        # here in Python rather than with a Jinja {% if %} in the Word template.
        # UCA uses the well's own BHST/BHSP (we have both); CRUSH TEST uses a
        # separate curing-bath condition that has no computed or input source
        # yet in this app, so it is left as "-" pending a dedicated field —
        # same placeholder convention used elsewhere for not-yet-built inputs.
        #
        # FIX (real bug, confirmed): uca_pressure used to read live
        # well_data.get("bhsp") while uca_temp read the cached
        # lab_info.get("bhst") right next to it on the same line — two
        # different sources for what's documented as "the same shared well
        # property" (see phase_7_lab.py's comment on bhsp). If BHSP is
        # changed in Phase II/III after the last Phase VII visit for this
        # slurry, the exported report could show one BHSP value in the
        # "Test Basic Data" table (from the cached lab snapshot) and a
        # different one in the "Compressive Strength / UCA" table (from the
        # live value) — same physical quantity, two numbers, one report.
        # Both now consistently read the same cached lab_info snapshot.
        comp_test_val = str(lab_info.get("comp_test", "-")).strip().upper()
        if comp_test_val == "UCA":
            uca_temp, uca_pressure = lab_info.get("bhst", "-"), lab_info.get("bhsp", "-")
            crush_temp, crush_pressure = "-", "-"
        elif comp_test_val == "CRUSH":
            uca_temp, uca_pressure = "-", "-"
            crush_temp, crush_pressure = "-", "-"
        else:
            uca_temp = uca_pressure = crush_temp = crush_pressure = "-"

        slurries_payload.append({
            "name": s,
            "volume_bbl": vol,
            "density_pcf": fluid_data.get(s, {}).get("density", ""),
            "yield_cuft_sk": yd,
            "mix_water_bbl": float(p.get("mix_water", 0.0)),
            "dead_vol_bbl": float(p.get("dead_vol", 0.0)),
            "total_water_bbl": round_half_up(float(p.get("mix_water", 0.0)) + float(p.get("dead_vol", 0.0)), 1),
            "mixing_tank": p.get("tank_name", ""),
            "base_cement": p.get("base_cement", "Cement G Delijan"),
            "total_sacks": total_sacks,
            "solution": p.get("solution", ""),
            "blends": blend_rows,
            "additives": adds_rows,
            "lab_conventional": conv_rows,
            "lab_additives": lab_adds_rows,
            "lab": {
                "bhct": lab_info.get("bhct", "-"),
                "bhst": lab_info.get("bhst", "-"),
                "thickening_time": lab_info.get("thickening_time", "-"),
                "thickening_endpoint": lab_info.get("thickening_endpoint", "Not specified"),
                "thickening_endpoint_label": (
                    lab_info.get("thickening_endpoint")
                    if lab_info.get("thickening_endpoint") in ("70 Bc", "100 Bc") else "Reported"
                ),
                "fluid_loss": lab_info.get("api_fl", "-"),
                "api_fl_collected": lab_info.get("api_fl_collected", "-"),
                "free_water": lab_info.get("free_water", "-"),
                "comp_test": lab_info.get("comp_test", "-"),
                "grid": lab_rows,
                "conventional": conv_rows,
                "additives": lab_adds_rows,
                "bhsp": lab_info.get("bhsp", ""),
                "mix_fluid": lab_info.get("mix_fluid", ""),
                "base_fluid": lab_info.get("base_fluid", ""),
                "solution_density": lab_info.get("solution_density", ""),
                "uca_temp": uca_temp,
                "uca_pressure": uca_pressure,
                "crush_temp": crush_temp,
                "crush_pressure": crush_pressure
            }
        })
        # BUG-04: populate the four placement keys the template's per-slurry
        # placement block consumes (top/bottom/excess_oh/excess_csg).
        _attach_placement_fields(slurries_payload[-1], p, hw_df, job_type,
                                 st.session_state.get("placement_config", {}))

    # BUG-19 (merged BUG-04 scope): a bare standardized '....' in any of the
    # four placement cells is now an explicit export blocker instead of
    # silently printing into the Word placement table.
    unresolved_placement = sorted({
        f"{payload['name']} → {field}"
        for payload in slurries_payload
        for field in ("top", "bottom", "excess_oh", "excess_csg")
        if payload.get(field) == "...."
    })
    if unresolved_placement:
        invalidate_document(st.session_state)
        raise ValueError("Complete the placement table inputs before Word export: "
                         + ", ".join(unresolved_placement))

    # 4. Pre-flush Data Serialization with Structured Rows (جدول سطری Pre-flush)
    # F1 (P0-01, owner-approved 2026-09-29): preflush_calc is a Phase-VI render
    # byproduct and goes STALE when Phase IV volume/density edits are followed
    # by direct sidebar navigation to Phase X (live-proven: the report printed
    # 80 bbl while the fluid truth was 25 bbl, readiness checklist still 'ok').
    # The report payload is therefore RECOMPUTED here, at consumption time,
    # from the source of truth (preflush_config + fluid_data) via the same
    # pure semantics Phase VI applies. The cached preflush_calc remains only
    # as a fallback for projects saved before preflush_config existed.
    preflush_data = {}
    if "Pre Flush" in active_fluids:
        _pf_config = st.session_state.get("preflush_config")
        if _pf_config:
            from phase_6_spacer import compute_preflush_payload
            preflush_data = dict(compute_preflush_payload(
                _pf_config, fluid_data.get("Pre Flush", {})))
        else:
            preflush_data = dict(st.session_state.get("preflush_calc") or {})
    preflush_rows = []
    if preflush_data and safe_float(preflush_data.get("volume_bbl", 0.0)) > 0:
        w_bbl = safe_float(preflush_data.get("water_bbl", 0.0))
        nacl_lbs = safe_float(preflush_data.get("nacl_lbs", 0.0))
        nacl_m = safe_float(preflush_data.get("nacl_multiplier", 0.0))
        wash_gal = safe_float(preflush_data.get("wash_gal", 0.0))
        wash_m = safe_float(preflush_data.get("wash_multiplier", 0.0))
        
        preflush_rows.append({
            "Item": 1,
            "Name": "Fresh Water",
            "Material Type": "Water",
            "amount": f"{w_bbl:.1f} bbl",
            "ratio": "-"
        })
        if nacl_lbs > 0:
            preflush_rows.append({
                "Item": len(preflush_rows) + 1,
                "Name": "Salt",
                "Material Type": "NaCl",
                "amount": f"{nacl_lbs:.1f} lb",
                "ratio": f"{nacl_m:.1f}"
            })
        if wash_gal > 0:
            preflush_rows.append({
                "Item": len(preflush_rows) + 1,
                "Name": "Chemical Wash",
                "Material Type": "Wash",
                "amount": f"{wash_gal:.1f} gal",
                "ratio": f"{wash_m:.1f}"
            })
    preflush_data["rows"] = preflush_rows
    # FIX (confirmed via live docxtpl render test): the Word template's
    # "Pre Flush Data" header expects {{ preflush.volume }} and
    # {{ preflush.weight }}, but this dict only ever carried "volume_bbl"
    # and "density_pcf" (the names used consistently everywhere else in the
    # codebase — generate_official_procedure, phase_6_spacer.py, etc.). Since
    # those two other keys are relied on elsewhere and shouldn't be renamed,
    # add "volume"/"weight" here as plain aliases just for the template, at
    # the one place this dict is actually handed to docxtpl.
    preflush_data["volume"] = preflush_data.get("volume_bbl", 0.0)
    preflush_data["weight"] = preflush_data.get("density_pcf", "")

    # 5. Spacers Serialization — BUG-05: the Word template now consumes this
    # payload through a cloned "Spacer Formulation Data" table. The rows are
    # FLATTENED to the exact same schema the Pre-flush table loops over
    # (Item via loop.index, Name, Material Type, amount, ratio) so the
    # template needs a single {%tr for r in spacers %} loop instead of
    # fragile nested {%tr %} loops: one summary row per spacer followed by
    # its chemical rows.
    spacers_payload = []
    for sp_name in ["Spacer", "Spacer Ahead", "Spacer Behind"]:
        if sp_name in active_fluids and sp_name in st.session_state.get("spacer_dfs", {}):
            sp_df = st.session_state["spacer_dfs"][sp_name]
            spacers_payload.append({
                "name": sp_name,
                "volume_bbl": fluid_data.get(sp_name, {}).get("volume", 0.0),
                "density_pcf": fluid_data.get(sp_name, {}).get("density", ""),
                "chemicals": sp_df.to_dict(orient="records") if not sp_df.empty else []
            })
    spacer_rows = []
    for sp in spacers_payload:
        spacer_rows.append({
            "Name": str(sp.get("name", "") or ""),
            "Material Type": "Spacer",
            "amount": f"{safe_float(sp.get('volume_bbl', 0.0)):.1f} bbl @ {sp.get('density_pcf', '')} pcf",
            "ratio": "-"
        })
        for c in (sp.get("chemicals") or []):
            spacer_rows.append({
                "Name": str(c.get("Chemical", "") or ""),
                "Material Type": str(c.get("Weighting Agent Type", "") or ""),
                "amount": str(c.get("User Input (% or gal)", "") or ""),
                "ratio": "-"
            })
    spacer_volume_bbl = round_half_up(
        sum(safe_float(sp.get("volume_bbl", 0.0)) for sp in spacers_payload), 1)
    # F4 (P2-01, owner-approved 2026-09-29): densities are free-text ('115-118'
    # is a legal Phase IV entry — the field's own help example), so the note
    # must order them NUMERICALLY. Plain sorted() ordered them lexically
    # ('100.0, 95.0'); the critique's raw key=float would have crashed on
    # '115-118'. parse_effective_numeric handles ranges (mean 116.5) and
    # returns the +inf default for non-numeric junk, which sorts last and
    # never raises; the string itself breaks ties deterministically.
    spacer_densities = ", ".join(sorted(
        {str(sp.get("density_pcf", "") or "").strip()
         for sp in spacers_payload if str(sp.get("density_pcf", "") or "").strip()},
        key=lambda s: (parse_effective_numeric(s, default=float("inf")), s)))
    spacer_density_note = (f"{spacer_densities} pcf" if spacer_densities else "-")

    # فلگ‌های شرطی برای تمپلیت ورد — has_spacer reflects whether actual
    # spacer rows were built (a Spacer selected in Phase IV without any
    # formulation data prints nothing rather than an empty table).
    has_spacer = bool(spacer_rows)
    has_preflush = "Pre Flush" in active_fluids
    # BUG-14 (confirmed): 'CSG 18 5/8"' takes the surface stab-in inner-string
    # procedure branch above (grouped with 20"/24"/30"), so it must also be
    # excluded from centralizer and open-hole content — previously it got
    # stab-in steps AND centralizer/open-hole notes in the same document.
    has_centralizer = not any(x in job_type.upper() for x in ["PLUG", "SQUEEZE", "20", "24", "30", "18"])
    # Notes 5-6 (Hydrostatic / Pore & Frac) follow the exact same job-type
    # grouping as has_centralizer — validated against all 8 real reference
    # documents: present for CSG 13-3/8"/9-5/8"/7", LNR, and Tie Back; absent
    # for Plug, Squeeze, and the shallow surface strings (18-5/8"/20"/24"/30").
    has_open_hole_notes = has_centralizer

    # 5.5 Sequential NOTE numbering (never hardcode "NOTE N:" anywhere else)
    note_ctx = build_ordered_notes(
        job_type=job_type,
        well_data=well_data,
        total_pump_time_min=st.session_state.get("total_pump_time_min", 0.0),
        slurries_payload=slurries_payload,
        has_open_hole_notes=has_open_hole_notes
    )

    proc_text = st.session_state.get("procedure_text", "")
    exec_summary_text = st.session_state.get("exec_summary_text", "")
    validate_manual_numbering(st.session_state, specs, note_ctx["all_notes"])

    # Splits proc_text into individual lines for the Word template's
    # {%p for line in procedure_steps %} paragraph loop (see master_template.docx),
    # dropping only a recognized heading: manually reviewed procedure text
    # may start directly with an instruction, which must remain in Word.
    # &/</>-escaping is handled once, globally, by _escape_xml_special_chars() below.
    _proc_all_lines = [l for l in proc_text.split("\n") if l.strip()]
    if _proc_all_lines and re.fullmatch(
        r"\s*(?:(?:VIII|IX|X)\.\s*)?Cementing Procedure\s*:?\s*",
        _proc_all_lines[0], flags=re.IGNORECASE
    ):
        _proc_all_lines = _proc_all_lines[1:]
    procedure_steps = _proc_all_lines

    context = {
        "job_type": doc_ctrl.get("job_type", ""),
        "hole_size": doc_ctrl.get("hole_size", ""),
        "field": doc_ctrl.get("field", ""),
        "well_location": doc_ctrl.get("well_location", ""),
        "well_name": doc_ctrl.get("well_name", ""),
        "rig_name": doc_ctrl.get("rig_name", ""),
        "client": doc_ctrl.get("client", ""),
        "contract_number": doc_ctrl.get("contract_number", ""),
        "proposal_number": doc_ctrl.get("proposal_number", ""),
        "cementing_method": doc_ctrl.get("cementing_method", "Primary Cementing"),
        "date": doc_ctrl.get("date", datetime.today().strftime("%Y-%m-%d")),
        "district_phone": doc_ctrl.get("district_phone", ""),
        "made_by": doc_ctrl.get("made_by", ""),
        # FIX (requested): approval chain + revision marker, threaded through
        # so the data is available to the template as soon as it gets
        # matching tags (not done here — see the note on this in chat: the
        # current master_template.docx wasn't part of this turn's upload,
        # so it isn't touched blindly without being able to verify it first).
        "prepared_by": doc_ctrl.get("prepared_by", ""),
        "checked_by": doc_ctrl.get("checked_by", ""),
        "approved_by": doc_ctrl.get("approved_by", ""),
        "revision_no": doc_ctrl.get("revision_no", "0"),

        "hardware": hardware_list,
        "well_data": well_data,
        
        "fluids_train": fluids_train,
        "total_pump_time_min": st.session_state.get("total_pump_time_min", 0.0),
        "total_pump_time_hhmm": st.session_state.get("total_pump_time_hhmm", "00:00"),
        
        "slurries": note_ctx["slurries"],
        "preflush": preflush_data,
        "spacers": spacer_rows,
        "spacer_volume_bbl": spacer_volume_bbl,
        "spacer_density_note": spacer_density_note,
        
        "has_spacer": has_spacer,
        "has_preflush": has_preflush,
        "has_centralizer": has_centralizer,
        "has_open_hole_notes": has_open_hole_notes,

        # Global sequentially-numbered notes — reference these directly in the
        # Word template (e.g. {{ note_geothermal }}) instead of typing "NOTE 1:" etc.
        "note_geothermal": note_ctx["note_geothermal"],
        "note_densities": note_ctx["note_densities"],
        "note_maxpump": note_ctx["note_maxpump"],
        "note_dispvol": note_ctx["note_dispvol"],
        "note_hydrostatic": note_ctx["note_hydrostatic"],
        "note_porefrac": note_ctx["note_porefrac"],
        "all_notes": note_ctx["all_notes"],
        
        "executive_summary": exec_summary_text,
        "exec_summary": exec_summary_text,
        "procedure": proc_text,
        "procedure_text": proc_text,
        "procedure_steps": procedure_steps,
        "generated_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    # Optional fields must never inherit another well's sample details.
    for key in (
        "prepared_by", "checked_by", "approved_by", "revision_no",
        "request_date", "request_number", "request_description",
        "prepared_date", "prepared_phone", "checked_date", "checked_phone",
        "approved_date", "approved_phone", "revision_date", "revision_description"
    ):
        value = doc_ctrl.get(key, "")
        context[key] = str(value).strip() if value is not None and str(value).strip() else "-"
    return _escape_xml_special_chars(context)

def _go_to_phase(phase_key):
    """BUG-02 deep-link callback: retarget the sidebar navigation radio
    before it remounts (same mechanism as _go_to_fluid_configuration)."""
    st.session_state["_app_mode_key"] = phase_key


# Longest/most-specific tokens first: "Phase VI" is a substring of
# "Phase VII", and "Phase V" of both.
_PHASE_DEEP_LINK_ORDER = (
    ("Phase II & III", "phase2_3"), ("Phase VII", "phase7"),
    ("Phase VI", "phase6"), ("Phase IV", "phase4"), ("Phase V", "phase5"),
    ("Phase II", "phase2_3"), ("Phase III", "phase2_3"), ("Phase I:", "phase1"),
)


def _phase_for_issue(issue):
    """Map a prepare_calculations issue message to the phase that owns it."""
    text = str(issue)
    for token, key in _PHASE_DEEP_LINK_ORDER:
        if token in text:
            return key
    return None


def render():
    st.header("Phase X: Procedure & Export")
    st.markdown("Review official executive summary and execution instructions, then export the complete engineering dossier to Word.")

    # FIX (requested): before this, the first sign of an incomplete project
    # (e.g. a slurry picked in Phase IV with no additives ever set in Phase
    # V) was an incomplete-looking Word document after export — nothing
    # warned the operator beforehand. This reuses the exact same
    # compute_phase_status() the sidebar markers use (see main.py), so the
    # two can never disagree about what "ready" means; shown collapsed by
    # default once required phases are complete. An unselected optional
    # Pre-flush/Spacer phase is neutral, not an export-readiness problem.
    _status = compute_phase_status(st.session_state)
    _phase_names = {
        "phase1": "I: Document Control", "phase2_3": "II & III: Well Data",
        "phase4": "IV: Fluids Sequence", "phase5": "V: Cement Program",
        "phase6": "VI: Pre-flush & Spacer", "phase7": "VII: Lab Report",
    }
    _selected_fluids = st.session_state.get("fluids_config", {}).get("active", [])
    _phase6_optional = not any(name in _selected_fluids
                               for name in ("Pre Flush", "Spacer", "Spacer Ahead", "Spacer Behind"))
    _not_ok = [(k, v) for k, v in _status.items()
               if v["level"] != "ok" and not (k == "phase6" and _phase6_optional)]
    _icon = "✅" if not _not_ok else ("⚠️" if any(v["level"] == "warning" for _, v in _not_ok) else "⚪")
    with st.expander(f"{_icon} Export readiness checklist", expanded=bool(_not_ok)):
        for key, name in _phase_names.items():
            v = _status[key]
            line = f"{'✅' if v['level'] == 'ok' else ('⚠️' if v['level'] == 'warning' else '⚪')} **Phase {name}** — {v['message']}"
            if v["level"] == "ok":
                st.markdown(line)
            elif v["level"] == "warning":
                st.warning(line)
            else:
                st.markdown(line)

    issues = prepare_calculations(st.session_state)
    if issues:
        # BUG-02 (confirmed): the early return here used to hide the whole
        # Phase X UI on the first validation failure, stranding the operator
        # on a near-empty screen with no way to reach the editors or the
        # checklist. Render each issue with a deep-link button to the
        # responsible phase instead, and keep rendering — the controls below
        # still reflect the last refresh and remain editable while the
        # problems are being fixed.
        for issue in issues:
            st.error(issue)
        _rescue_phases = sorted({_phase_for_issue(issue) for issue in issues} - {None})
        if _rescue_phases:
            st.caption("Jump to the responsible phase to fix the problem — the controls below stay available in the meantime.")
            _rescue_cols = st.columns(len(_rescue_phases))
            for _col, _phase_key in zip(_rescue_cols, _rescue_phases):
                with _col:
                    st.button(f"→ Phase {_phase_names[_phase_key].split(':')[0]}",
                              on_click=_go_to_phase, args=(_phase_key,),
                              key=f"_rescue_{_phase_key}")

    load_sig = str(st.session_state.get("last_loaded_hash", "default_project"))
    job_type = st.session_state.get("job_type", "CSG 20\"")
    active_fluids = st.session_state.get("fluids_config", {}).get("active", [])
    fluid_data = st.session_state.get("fluid_data", {})
    pump_time = st.session_state.get("total_pump_time_min", 0.0)
    cement_params = st.session_state.get("cement_params", {})
    additives_dfs = st.session_state.get("cement_additives_dfs", {})
    preflush_calc = st.session_state.get("preflush_calc", {})
    geo_md = float(st.session_state.get("geo_md", 3000.0))
    hw_df = st.session_state.get("hardware_table", pd.DataFrame())

    specs = synchronize_report_texts()
    # BUG-32 (new finding, this audit): this pre-render warning regex used to
    # omit the "(?! BASIS)" lookahead that unresolved_export_inputs() carries,
    # so the OPTIONAL VOLUME BASIS token was flagged here as a problem while
    # the export gate itself correctly treats it as optional — the two
    # warnings contradicted each other on the same screen. Reuse the export
    # gate's own pattern so they can never disagree again.
    if any(UNRESOLVED_INPUT_TOKEN.search(spec["generated"]) for spec in specs.values()):
        st.warning("Some operational inputs are missing or inconsistent. Review the marked fields in the generated text, especially the target and tie-back host in Phase II/III and the slurry tops in Phase V.")
    st.subheader("1. Executive Summary (Proposal Preamble)")
    _render_report_editor("exec_summary_text", specs["exec_summary_text"],
                          "Executive Summary Text (Official NIDC Format):", 240,
                          f"_exec_summary_editor_area_{load_sig}", "Auto-Regenerate Executive Summary")
    st.markdown("---")
    st.subheader("2. Rig Execution Procedure")
    _render_report_editor("procedure_text", specs["procedure_text"],
                          "Execution Instructions (Official Company Format):", 380,
                          f"_proc_editor_area_{load_sig}", "Auto-Regenerate Procedure")
    st.markdown("---")

    # 3. Executive Logistics & Material Summary
    st.subheader("3. Logistics & Material Summary")
    
    slurry_archetypes = ["Main", "Lead", "Lead #1", "Lead #2", "Tail"]
    active_slurries = [
        f for f in active_fluids 
        if any(f.replace(" ", "").lower() == s.replace(" ", "").lower() for s in slurry_archetypes)
    ]
    
    summary_cards = []
    total_well_sacks = 0.0
    total_slurry_vol = 0.0
    # F-01 (system audit 2026-09-29, owner-approved): these cards used to read
    # fluid volumes with a raw float() — OUTSIDE the F3 unreadable-volume gate
    # in build_master_context. A malformed project JSON can carry a textual
    # fluid_data volume (the loader number-checks only fluids_config.params,
    # not fluid_data), and whenever refresh_fluids aborts on the same junk the
    # stale payload survives into this render: the page died with a raw
    # ValueError crash screen. Same philosophy as F3: a controlled,
    # offender-naming gate — never a crash, never a fabricated 0.0 bbl row;
    # unreadable cells render as honest N/A (same convention as the blank
    # volume-basis fix) and Build stays blocked via invalidate_document.
    unreadable_card_volumes = []
    for s in active_slurries:
        p = cement_params.get(s, {})
        vol_raw = fluid_data.get(s, {}).get("volume", 0.0)
        vol = safe_float(vol_raw, None)
        if vol is None:
            unreadable_card_volumes.append(f"{s} → volume ({vol_raw!r})")
        yd = float(p.get("yield", 1.18))
        sacks = safe_float(p["total_sacks"], None) if p.get("total_sacks") else None
        if sacks is None and vol is not None:
            sacks = round_half_up((vol * 5.6146) / yd, 1) if yd > 0 else 0.0
        if vol is not None:
            total_slurry_vol += vol
        if sacks is not None:
            total_well_sacks += sacks
        summary_cards.append({
            "Slurry": s,
            "Volume (bbl)": f"{vol:.1f}" if vol is not None else "N/A",
            "Sacks": f"{sacks:.1f}" if sacks is not None else "N/A",
            "Mix Water (bbl)": f"{float(p.get('mix_water', 0.0)):.1f}",
            "Dead Vol (bbl)": f"{float(p.get('dead_vol', 0.0)):.1f}",
            "Tank": p.get("tank_name", "-")
        })

    if unreadable_card_volumes:
        # Controlled F3-style gate naming the offender, so the operator sees
        # exactly which fluid record is broken; the compiled document is
        # invalidated so a stale download can never outlive the broken input.
        invalidate_document(st.session_state)
        st.error("Unreadable numeric volume in Phase IV fluid data — open Phase IV to repair it: "
                 + ", ".join(unreadable_card_volumes))
        
    if summary_cards:
        st.table(pd.DataFrame(summary_cards))
        st.info(f"**Total Slurry Volume:** {total_slurry_vol:.1f} bbl | **Total Cement Sacks:** {total_well_sacks:.1f} sacks (~{total_well_sacks * 0.05:.1f} Metric Tons)")
    else:
        st.warning("⚠ No cement slurries are active in the fluid train.")

    st.markdown("---")

    # FIX (requested): the full checklist expander lives at the top of this
    # page, which can be scrolled past by the time the operator reaches the
    # Build button further down. A compact restatement right here — at the
    # actual point of action — catches it either way, without repeating the
    # full expander a second time.
    _status_pre_build = compute_phase_status(st.session_state)
    _unresolved = [v["message"] for k, v in _status_pre_build.items()
                   if v["level"] != "ok" and not (k == "phase6" and _phase6_optional)]
    if _unresolved:
        st.warning("⚠️ **Before building:** " + " | ".join(_unresolved))
        # Do not leave a previously compiled document downloadable when the
        # operator has made a required phase incomplete.
        invalidate_document(st.session_state)

    # 4. Document Generation & In-Memory Streaming
    st.subheader("4. Document Generation (.docx)")
    st.caption("Injects all project phases, tables, executive summary, and notes into `master_template.docx` via DocxTemplate engine.")
    if DocxTemplate is None:
        invalidate_document(st.session_state)
        st.error("Word export requires docxtpl. Deploy requirements.txt beside main.py, then reboot the Streamlit app.")
        return

    template_path = str(TEMPLATE_PATH)
    template_exists = os.path.exists(template_path)

    if not template_exists:
        invalidate_document(st.session_state)
        st.error(f"✕ Template file `{template_path}` not found in the application root. Place `master_template.docx` in the project directory.")
    else:
        master_context = None
        current_doc_signature = None
        if any(spec["pending"] for spec in specs.values()):
            st.warning("Review the preserved report text above before building the document.")
        else:
            try:
                master_context = build_master_context(calculations_prepared=True)
                current_doc_signature = document_signature(master_context, template_path)
            except Exception as exc:
                st.error(f"Cannot prepare a current report: {exc}")
        if current_doc_signature is None or st.session_state.get("_compiled_doc_signature") != current_doc_signature:
            invalidate_document(st.session_state)
        col_gen, col_down = st.columns([1.5, 2.5])
        with col_gen:
            if st.button("Build Word Document", type="primary",
                         disabled=master_context is None or bool(_unresolved)):
                invalidate_document(st.session_state)
                try:
                    with st.spinner("Compiling full engineering dossier..."):
                        # BUG-28: render from the cached template bytes instead
                        # of re-reading the 650 KB file on every Build.
                        _tpl_mtime = os.path.getmtime(template_path) if os.path.exists(template_path) else 0.0
                        doc = DocxTemplate(io.BytesIO(_load_template_bytes(str(template_path), _tpl_mtime)))
                        doc.render(master_context)
                        
                        doc_io = io.BytesIO()
                        doc.save(doc_io)
                        doc_io.seek(0)
                        
                        well_label = str(st.session_state.get("well_name", "Well")).strip()
                        safe_label = "".join(c for c in well_label if c.isalnum() or c in ("-", "_")).strip() or "Untitled"
                        filename = f"Cementing_Program_{safe_label}_{datetime.today().strftime('%Y%m%d_%H%M')}.docx"
                        
                        st.session_state["_compiled_doc_bytes"] = doc_io.getvalue()
                        st.session_state["_compiled_doc_filename"] = filename
                        st.session_state["_compiled_doc_signature"] = current_doc_signature
                        st.success("✓ Document generated.")
                except Exception as e:
                    st.error(f"✕ Template rendering error: {e}")

        with col_down:
            if "_compiled_doc_bytes" in st.session_state:
                st.download_button(
                    label="Download Final Document (.docx)",
                    data=st.session_state["_compiled_doc_bytes"],
                    file_name=st.session_state["_compiled_doc_filename"],
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"_btn_download_doc_{load_sig}"
                )
