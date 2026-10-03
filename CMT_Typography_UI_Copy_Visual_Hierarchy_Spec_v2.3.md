# Comprehensive Typography, UI-Copy & Visual Hierarchy Specification

**Target System:** Cementing Engineering Report Engine (`CMT` — Streamlit Web Application)  
**Document ID:** `CMT-QA-TYPO-2026-MASTER-SAFE`  
**Revision:** 2.3 (Pre-Publish-Gated, Production-Safe, Source-Verified & Schema-Guarded Engineering Specification)  
**Date:** October 2, 2026  
**Target Audience:** Autonomous AI Engineering Agent & Frontend Software Engineers  

---

## 1. Executive Summary & Purpose

The Cementing Report Engine is a specialized engineering software application developed in Python and Streamlit. While functionally and mathematically robust, its interface exhibits systemic typographic debt, inconsistent engineering nomenclature, uncontrolled text sprawl, and weak visual hierarchy.

This specification establishes an immutable blueprint for refactoring all user-facing copy, labels, captions, warnings, and hierarchy levels across Phases I through X without breaking backend logic, data serialization, or calculations.

### Core Engineering Objectives

* **Scannability & Cognitive Load:** Eliminate multiline instructional paragraphs from primary form canvases, allowing drilling and cementing engineers to scan and execute workflows rapidly.
* **Strict Visual Hierarchy:** Standardize component styling across exactly five defined typography tiers.
* **Nomenclature & Unit Uniformity:** Enforce mandatory domain glossaries and standard spacing across engineering units.
* **Action-Oriented Three-Part Messaging:** Restructure all alerts into concise, non-accusatory diagnostics specifying the condition, reason, and immediate remediation path.
* **Controlled String Centralization:** Move user-facing textual content toward a unified repository (`ui_strings.py`) incrementally, only inside the active implementation batch. Do not perform a whole-project string migration in one pass.
* **Phase-Gated Delivery & Regression Control:** Implement typography/UI-copy changes one phase (or one tightly coupled phase group) at a time, run targeted and full regression tests, inspect the diff, and only then proceed.
* **Minimal-Change Policy:** Reuse the current Streamlit structure, components, helpers, and dependencies. Do not introduce new dependencies or unrelated refactors for typography/UI-copy work.
* **Word Engine & Schema Protection (Hard Guardrail):** Strictly protect the generation logic, procedural text output, bracketed validation tokens, and backend dictionary/column schema.


---

## 1.1 Execution Trigger — Pre-Publish Only

This specification is a **pre-publish presentation pass**, not a general bug-fix or engineering-refactor instruction.

The AI Agent may begin implementation of this specification **only when all of the following are true**:

1. All currently approved functional bug-fix batches are complete.
2. The cumulative regression suite is green for the intended release baseline.
3. The working tree starts from the intended clean repository revision.
4. The owner explicitly authorizes the pre-publish typography/UI-copy pass.

If any of these conditions is not satisfied, do not begin presentation refactoring.

This specification may be reviewed earlier for planning, but implementation must remain deferred until the pre-publish gate is explicitly opened by the owner.

## 1.2 Functional Bug Discovery During the UI Pass

If a functional, calculation, state-management, persistence, export, or engineering bug is discovered while executing a typography/UI-copy batch:

1. **Do not fix the functional bug inside the presentation batch.**
2. Record the issue with the exact phase/file/behavior observed.
3. Stop the affected presentation path if continuing could hide, alter, or complicate the bug.
4. Return the issue to the normal bug-fix workflow governed by `AGENTS.md` and `zero_regression_contract.md`.
5. Resume the typography/UI-copy batch only after the functional issue is separately resolved, regression-verified, and committed.

Presentation work must never become an implicit authorization for functional changes.

## 1.3 Document Authority & Conflict Resolution

During this pre-publish pass, the following remain authoritative:

- `AGENTS.md` — implementation discipline, Ponytail/root-cause behavior, and project-specific engineering safety.
- `zero_regression_contract.md` — mutation scope, protected behavior, regression requirements, test integrity, acceptance, and truthful reporting.
- The active owner-approved engineering/bug specification — only where it explicitly governs the current work.

This typography/UI-copy specification governs **presentation-layer wording, hierarchy, spacing, labels, captions, tooltips, and visual consistency only**.

If this specification conflicts with:

- verified engineering behavior,
- regression guardrails,
- protected schema,
- protected Word/report behavior,
- owner-approved task scope,

then preserve the verified/protected behavior, make no conflicting change, and report the discrepancy.

Do not resolve such conflicts by silently modifying calculations, validation, persistence, schema, report generation, or engineering semantics.

---

## 2. Foundational Typography & Interaction Rules


### ⚠️ CRITICAL BOUNDARY: DISPLAY LAYER VS. DATA SCHEMA (HARD CONSTRAINT)

All typography rules, casing adjustments, and wording changes apply **STRICTLY to the presentation layer** (widget labels, button texts, `st.caption`, `help=` tooltips, and `st.column_config` headers).

**THE AI AGENT MUST NEVER RENAME OR MUTATE:**

1. **DataFrame column names:** `REQUIRED_ADDITIVE_COLUMNS` (`"User Input"`, `"Material Type"`, `"Name"`, etc.) and `HARDWARE_COLUMNS` (`"MD (m)"`, `"Size (in)"`, etc.) must remain byte-for-byte identical.
2. **Database constants & fluid keys:** Items in `materials_db.py` (e.g., `"Pre Flush"`, `"Spacer"`, `"Displacement Fluid"`, `"CEMENT G DELIJAN"`).
3. **Session & JSON dictionary keys:** Keys in `st.session_state` and JSON project persistence dictionaries (e.g., `p["dead_vol"]`, `qc["bhct"]`, `cfg["params"]`).

---

### 2.1 Five-Tier Visual Hierarchy

Every layout across the application must strictly adhere to the following five UI components:

| Level | Role | Streamlit Component | Formatting Rules |
|---|---|---|---|
| **H1** | Main Phase Title | `st.header` | Sentence case. No emojis. Bold by default. |
| **H2** | Major Section Headings | `st.subheader` | Sentence case. Used for major logical subdivisions. |
| **H3** | Table Titles & Group Headings | `st.markdown("### ...")` | Sentence case. Minimal margins. |
| **Body** | Primary Content & Direct Descriptions | `st.write` or `st.markdown` | Standard font weight. Bolding restricted strictly to critical metrics or mandatory actions. |
| **Caption** | Helper Text, Units, Short Explanations | `st.caption` | Maximum 2 lines. Subdued color, compact spacing. |

#### Styling & Layout Constraints

* **Emoji Policy & Functional Exceptions:**
  * Eliminate decorative, playful, or unneeded emojis from titles, form labels, and section headings to preserve an industrial, formal tool appearance.
  * **Protected Functional Icons:** Do **NOT** remove functional status indicators in the sidebar or page configuration: `page_icon="🛢️"` in `main.py` and navigation completion icons (`_PHASE_ICONS = {"ok": "✅", "warning": "⚠️", "empty": "⚪"}`) are core architectural navigation elements and must be preserved.
* **Bolding Discipline:** Never bold entire sentences or informational hints. Bolding (`**...**`) is restricted exclusively to critical engineering values (e.g., target depths, out-of-spec density) and mandatory user actions.

### 2.2 Capitalization & Unit Formatting Rules

* **Sentence Case Standard:** Apply Sentence case to all phase headers, section titles, field labels, visual table headers, button labels, and captions. Only the first letter of the first word is capitalized, with exceptions granted strictly for recognized proper nouns, well names, and standard oilfield acronyms (TVD, MD, API, pcf, bpm, BWOC, BWOW).
  * *Incorrect:* `Well Target Depth (M MD)`, `Mix Water Requirement (BBL)`
  * *Correct:* `Well target depth (m MD)`, `Mix water requirement (bbl)`
* **Engineering Unit Spacing:** Always separate numeric magnitudes from unit symbols with exactly one space. Never concatenate units directly to numbers:
  * `118.0 pcf` (never `118pcf` or `118.0PCF`)
  * `4.0 bpm` (never `4bpm` or `4.0BPM`)
  * `% BWOC` (Percent By Weight Of Cement; never `%BWOC`)
  * `% BWOW` (Percent By Weight Of Water; never `%BWOW`)
  * `gal/sk` (Gallons per sack; never `gal/sack` or `gps`)
  * `bbl` (Barrels; lowercase, single space)
  * `psi` (Pounds per square inch; lowercase, single space)

### 2.3 Mandatory Terminology Glossary (Presentation Layer Only)

The AI Agent must apply uniform nomenclature exclusively to user-facing labels and data editor column configurations:

| Code/Database Term (Untouched) | UI Display Term | Safe Implementation Scope |
|---|---|---|
| `"Pre Flush"` | **Pre-flush** | UI labels, captions, and section titles only. Internal dictionary keys and `materials_db.FLUID_TYPES` stay `"Pre Flush"`. |
| `p["dead_vol"]` | **Dead Volume (bbl)** | Label parameter of `st.number_input`. Key stays `"dead_vol"`. |
| `"User Input"` (in DataFrames) | **Concentration** | Visual column header via `st.column_config.NumberColumn("Concentration", ...)`. Underlying column key stays `"User Input"`. |
| `p["cmt_sg"]` | **Cement specific gravity** | Label parameter of `st.number_input`. Key stays `"cmt_sg"`. |
| `"sync_btn"` / `"Sync with Phase 5"` | **Sync with Phase V** | Button text label on `st.button`. |

### 2.4 Three-Part Message Architecture

Every warning, validation failure, and instructional banner must follow a structured three-part anatomy:

1. **What happened:** Clear, factual statement of the detected condition.
2. **Why (Contextual):** Immediate operational or mathematical impact (include only if non-obvious).
3. **What the user should do:** Direct, actionable remediation step.

*Example:*

> `Slurry density (65.0 pcf) is outside the allowable range of 75.0–180.0 pcf. Review and correct the density in Phase IV before proceeding.`

### 2.5 Long Instructional Text Policy (`help=` and `st.expander`)

* Instructional or contextual text visible by default in the main UI canvas must not exceed two lines.
* Any technical explanation, operational standard, or background guideline exceeding two lines must be relocated to:
  1. The `help="..."` tooltip parameter of the corresponding Streamlit widget.
  2. A closed accordion component: `st.expander("Technical background: ...", expanded=False)`.

### 2.6 Engineering Content Authority & Source Verification (Hard Constraint)

This document governs **presentation, wording, and hierarchy**. It is **not** an independent engineering source of truth.

The AI Agent must therefore follow these rules:

1. **Do not introduce new engineering rules from this specification alone.** Numerical thresholds, chemical behavior, operational limits, contact-time requirements, safety language, and domain guidance may be rendered or shortened only when they are already supported by the existing application logic, approved project documentation, the protected Word output, or another user-approved engineering source.
2. **Do not change engineering meaning while improving copy.** A shorter UI sentence must preserve the same technical condition, threshold, unit, source phase, and required action as the existing verified behavior.
3. **Do not convert examples into new validation logic.** Example values in this document (including density ranges, NaCl behavior, contact-time statements, and similar domain examples) are presentation examples unless the same rule is independently verified in the project.
4. **When the specification conflicts with existing verified engineering behavior, preserve the verified behavior and report the discrepancy.** Do not silently “correct” the code, calculations, database, or Word output to match this document.
5. **Never alter calculations, defaults, validation ranges, pass/fail logic, eligibility rules, or safety gates as part of a typography/UI-copy task.**
6. **Preserve widget identity and state behavior.** Existing explicit Streamlit widget `key=` values must remain byte-for-byte unchanged. If a label-only change could affect a widget that has no explicit key, make the change only within the active batch and verify state persistence/regression behavior before proceeding. Do not invent or rename widget keys merely to satisfy this specification unless separately requested.

---

## 3. Strict Word Report & Validation Guardrail (Phase X)

```text
================================================================================

CRITICAL AGENT GUARDRAIL: WORD EXPORT & VALIDATION TOKEN IMMUTABILITY

The Executive Summary, Procedure sections, and validation tokens generated in Phase X represent certified, safety-critical engineering deliverables.

THE AI AGENT MUST NOT:

1. Modify, rewrite, reformat, or alter procedural generation algorithms in phase_10_procedure.py.
2. Alter the structural engineering wording, sequence steps, pump rates, pressure thresholds, or safety warnings embedded in the Word template context.
3. Change calculation outputs, annular velocity heuristics, or displacement logic.
4. Rewrite, rephrase, shorten, or restyle the literary wording of any NOTE template (NOTE 1 through NOTE N) rendered in the Word document.
5. Alter or shorten internal bracketed validation tokens such as `[VOLUME BASIS NOT SET IN PHASE II/III]`, `[TOP NOT SET IN PHASE V]`, or `[TARGET DEPTH NOT SELECTED IN PHASE II/III]`. These tokens are explicitly scanned by `unresolved_export_inputs()` regex to gate Word document generation.

THE AI AGENT MUST ONLY:

1. Refactor UI-level widget labels, captions, and readiness checklist items in Phase X.
2. Streamline manual edit notification banners to be clean and action-oriented.

================================================================================
```

---

## 4. Phase-by-Phase Typographic Refactoring Matrix

### 4.0 Mandatory Implementation Boundary

This matrix is a **target state**, not permission for a single whole-project refactor.

Implementation must proceed in isolated batches:

* Work on **one phase at a time**, or one tightly coupled group only when separation would be unsafe (for example, Phases II & III where shared well/geothermal state is intentionally coupled).
* Do not edit unrelated phases “for consistency” during the current batch.
* Shared files such as `ui_strings.py` may be touched only for constants required by the active batch.
* After each batch, run the relevant phase tests plus the full regression suite available in the repository.
* Review the resulting diff before moving to the next batch.
* If a regression appears outside the active phase, stop and fix or revert the current batch before continuing.
* Do not combine typography cleanup with calculation refactors, schema cleanup, dependency upgrades, or architecture redesign.

### 4.1 Phase I: Document Control

* **Header:** Convert to `Phase I: Document control`.
* **Field Labels:** Convert all input labels to Sentence case (`Well name`, `Field name`, `Contract number`, `Rig name`, `Job type`, `Cementing method`).
* **Hole Size Caption:** Replace sprawling multiline text with a concise caption and move dimensional guidance to `help`:
  * *Caption:* `Open-hole diameter for volumetric calculations.`
  * *Help Tooltip:* `Enter drilled diameter in inches (e.g., 26 or 17 1/2). Used to calculate annular slurry capacity.`
* **Approval & Revision Section:** Establish distinct visual hierarchy using `st.subheader("Approval and revision history")`. Convert tabular column labels (`Approved By`, `Checked By`, `Revision Date`) to Sentence case (`Approved by`, `Checked by`, `Revision date`).

### 4.2 Phases II & III: Well Data & Geothermal Profile

* **Fluid Property Captions:** Condense captions for `Mud weight`, `Plastic viscosity`, and `Yield point` to single-line descriptions with standard units (`pcf`, `cP`, `lb/100ft²`).
* **Physical Inconsistency Alert:** Restructure geometry warnings to follow the three-part format:
  * *Message:* `Casing inner diameter exceeds outer diameter. Correct the tubular dimensions in the hardware table.`
* **Thermal Alert:** Standardize geothermal gradient messaging:
  * *Message:* `Bottom-hole circulating temperature exceeds static temperature. Review temperature gradient inputs.`
* **Unit Standardization:** Ensure all inputs display standardized unit tags: `MD (m)`, `TVD (m)`, `BHST (°F)`, `BHCT (°F)`, `Gradient (°F/100ft)`.

### 4.3 Phase IV: Fluids Sequence

* **Standardized Metric Labels:** Enforce unified naming across all fluid sequence cards:
  * `Volume (bbl)`
  * `Density (pcf)`
  * `Pump rate (bpm)`
* **Calculation Annotations:** Shorten the redundant `Used in calculations as ...` string:
  * *Standard Annotation:* `Calculation basis: 118.0 pcf`
* **Plausibility Check Banner:**
  * *Standard Warning:* `Fluid density is outside the typical range of 75.0–180.0 pcf. Review the value before proceeding.`

### 4.4 Phase V: Cement Program (Highest Priority Refactoring)

Phase V exhibits the highest text density and requires the most substantial layout optimization.

* **Instructional Sprawl Compression:**
  * **Mix Method Guide:** Compress on-canvas text to: `Select dry-blend or liquid-mix based on additive phase.` Move the full guide into `help="Dry-blend additives are blended with dry cement before hydration. Liquid additives are dispersed directly into mix water tanks."`
  * **Name Guide:** Compress on-canvas text to: `Select standard NIDC chemicals from the verified library.` Move catalog rules into `help="..."`.
  * **NaCl Guidelines:** If NaCl guidance is already supported by verified project logic/documentation, compress the on-canvas text to: `Salt concentration alters slurry yield and hydration kinetics.` Move longer verified guidance into an `st.expander("Technical details: NaCl additive dynamics", expanded=False)`. **Do not introduce or modify concentration thresholds or chemical-behavior claims from this specification alone.**
* **Slurry Density Warning:** Standardize across all tabs:
  > `Slurry density is outside the typical range of 75–180 pcf. Please review the value in Phase IV.`
* **Auto-Correction Feedback:** Replace large, multi-row auto-correction diff tables with a compact info expander:
  > `ℹ️ Material classification auto-corrected per NIDC database standards.`
* **Data Editor Presentation Headers (via `st.column_config` only):**
  * `User Input` column → displayed as `"Concentration (% or gal/sk)"`.
  * `Mix Method` column → displayed as `"Mix method"`.
  * `Physical State` column → displayed as `"Physical state"`.

### 4.5 Phase VI: Pre-flush & Spacer

* **Titles & Headers:** Convert section headers to Sentence case: `Phase VI: Pre-flush and spacer program`.
* **Engineering Notes:** Shorten expansive fluid-displacement theory notes only when the underlying engineering requirement is already verified in the project:
  * *Presentation Example:* `Maintain 10-minute minimum annular contact time across the target interval for mud removal.`
  * **Source Guard:** The `10-minute` requirement must not be added, changed, or enforced solely because it appears in this specification.

### 4.6 Phase VII: Lab Report

* **Thermal Diagnostics:** Shorten captions for `BHCT` and `BHST` to standard single lines:
  * `BHCT caption:` `Bottom-hole circulating temperature during displacement.`
  * `BHST caption:` `Bottom-hole static equilibrium temperature.`
* **Formulation Drift Alert:** Replace ambiguous warnings with an action-oriented alert:
  * *Message:* `Slurry formulation in Phase V has changed. Click 'Sync with Phase V' to recalculate lab cup quantities.`
* **Synchronization Action:** Standardize the sync button label to exactly `Sync with Phase V`.

### 4.7 Phase X: Procedure & Export

* **Export Readiness Checklist:** Refactor verbose diagnostic rows into uniform, compact status cards:
  * *Format:* `Phase [Name]: [Complete / Needs review / Not applicable]`
* **Validation Tokens Protection:** Retain full bracketed tokens (`[VOLUME BASIS NOT SET IN PHASE II/III]`, `[TOP NOT SET IN PHASE V]`) to keep `unresolved_export_inputs()` validation guards intact.
* **Manual Edit Indicator:** Standardize the procedure override note:
  * `Manually modified procedure steps are preserved across recalculations.`

---

## 5. Controlled String Architecture (`ui_strings.py`)

`ui_strings.py` is the **target repository for reusable and standardized user-facing strings**, but migration must be incremental and phase-gated.

### 5.1 Migration Rules

* During a given implementation batch, migrate only the user-facing strings that are changed or standardized in the active phase.
* Do **not** sweep untouched phases merely to eliminate every hardcoded string.
* Existing hardcoded strings outside the active batch may remain until their own phase is intentionally refactored.
* Prefer centralization for repeated labels, shared actions, standardized warnings, phase titles, and unit strings.
* A one-off local string may remain local when moving it provides no reuse or consistency benefit and would unnecessarily expand the diff.
* Never move backend constants, persistence keys, schema names, Word-template tokens, or calculation text into `ui_strings.py`.
* Preserve all existing widget `key=` values exactly. String centralization must not change widget identity or state behavior.
* No new package/dependency may be added for string management.

### 5.2 Target Reference Structure

The following example shows the preferred **end-state pattern**. It is not an instruction to migrate every phase in one batch.

```python
# ui_strings.py
"""Centralized user-facing strings repository for the Cementing Report Engine."""

from typing import Final

# Global Navigation & Actions
BTN_NEXT_PHASE: Final[str] = "Next phase"
BTN_PREV_PHASE: Final[str] = "Previous phase"
BTN_SYNC_PHASE_V: Final[str] = "Sync with Phase V"
BTN_CONFIRM_LAB: Final[str] = "Confirm measured lab results"
BTN_BUILD_DOCX: Final[str] = "Build Word document (.docx)"

# Standardized Units
UNIT_PCF: Final[str] = "pcf"
UNIT_BPM: Final[str] = "bpm"
UNIT_BBL: Final[str] = "bbl"
UNIT_PSI: Final[str] = "psi"
UNIT_BWOC: Final[str] = "% BWOC"
UNIT_BWOW: Final[str] = "% BWOW"
UNIT_GPS: Final[str] = "gal/sk"

# Phase I: Document Control
P1_TITLE: Final[str] = "Phase I: Document control"
P1_HOLE_SIZE_LABEL: Final[str] = "Hole size"
P1_HOLE_SIZE_CAPTION: Final[str] = "Open-hole diameter for volumetric calculations."
P1_HOLE_SIZE_HELP: Final[str] = (
    "Enter drilled diameter in inches (e.g., 26 or 17 1/2). "
    "Used to calculate annular slurry capacity."
)
P1_APPROVAL_HEADER: Final[str] = "Approval and revision history"

# Phase II & III: Well Data
P2_TITLE: Final[str] = "Phase II & III: Well and geothermal data"
P2_HARDWARE_HEADER: Final[str] = "Tubular and casing hardware"
P2_GEOMETRY_ALERT: Final[str] = (
    "Casing inner diameter exceeds outer diameter. Correct the tubular dimensions in the hardware table."
)
P2_THERMAL_ALERT: Final[str] = (
    "Bottom-hole circulating temperature exceeds static temperature. Review temperature gradient inputs."
)

# Phase IV: Fluids Sequence
P4_TITLE: Final[str] = "Phase IV: Fluids sequence"
P4_VOL_LABEL: Final[str] = "Volume (bbl)"
P4_DENSITY_LABEL: Final[str] = "Density (pcf)"
P4_RATE_LABEL: Final[str] = "Pump rate (bpm)"
P4_CALC_BASIS: Final[str] = "Calculation basis: {value:.1f} {unit}"
P4_DENSITY_WARN: Final[str] = (
    "Fluid density is outside the typical range of 75.0–180.0 pcf. Review the value before proceeding."
)

# Phase V: Cement Program
P5_TITLE: Final[str] = "Phase V: Cementing program"
P5_MIX_METHOD_HELP: Final[str] = (
    "Dry-blend additives are blended with dry cement before hydration. "
    "Liquid additives are dispersed directly into mix water tanks."
)
P5_NAME_GUIDE_HELP: Final[str] = (
    "Select standard NIDC additives from the verified library. "
    "Custom chemicals require manual specific gravity entry."
)
P5_NACL_EXPANDER_TITLE: Final[str] = "Technical details: NaCl additive dynamics"

# IMPORTANT:
# Populate detailed NaCl engineering guidance only from verified existing
# project logic/documentation. Do not introduce concentration thresholds
# from this UI specification alone.
P5_NACL_EXPANDER_BODY: Final[str] = "<verified existing engineering guidance>"

P5_DENSITY_WARN: Final[str] = (
    "Slurry density is outside the typical range of 75–180 pcf. Please review the value in Phase IV."
)

# Phase VI: Pre-flush & Spacer
P6_TITLE: Final[str] = "Phase VI: Pre-flush and spacer program"
P6_CONTACT_TIME_NOTE: Final[str] = (
    "Maintain 10-minute minimum annular contact time across the target interval for mud removal."
)

# Phase VII: Lab Report
P7_TITLE: Final[str] = "Phase VII: Laboratory test report"
P7_FORMULATION_DRIFT_WARN: Final[str] = (
    "Slurry formulation in Phase V has changed. Click 'Sync with Phase V' to recalculate lab cup quantities."
)

# Phase X: Procedure & Export
P10_TITLE: Final[str] = "Phase X: Procedure and document export"
P10_MANUAL_EDIT_NOTE: Final[str] = (
    "Manually modified procedure steps are preserved across recalculations."
)
P10_READINESS_CARD: Final[str] = "{phase_name}: {status}"
```

---

## 6. Ready-to-Use Standardized Message Templates

All diagnostic messages generated dynamically by validation routines must be formatted using the following immutable string structures.

### 6.1 Warning Message Template

```text
{Parameter} is outside the allowable range ({min_val}–{max_val} {unit}). Please correct it in {source_phase}.
```

*Production Instance:*

> `Slurry density is outside the typical range of 75–180 pcf. Please review the value in Phase IV.`

### 6.2 Validation Error Message Template

```text
{Field_name} cannot be empty. Please enter a valid value to continue.
```

*Production Instance:*

> `Well name cannot be empty. Please enter a valid value to continue.`

### 6.3 Informational Action Template

```text
Formulation in Phase V was updated. Click 'Sync with Phase V' to recalculate lab cup quantities.
```

---

## 7. Agent Execution Protocol

### 7.1 Pre-Change Baseline

Before editing the active phase:

1. Confirm the working tree/workspace starts from the intended repository revision.
2. Identify the exact files used by the active phase.
3. Identify any shared UI helpers or shared strings that the phase depends on.
4. Run the currently available relevant tests to establish a baseline.
5. Record any pre-existing failures; do not attribute them to the new batch.

### 7.2 Per-Batch Workflow

For each phase (or explicitly approved coupled phase group):

1. **Inspect first:** Locate every user-facing string and visual hierarchy issue in scope.
2. **Plan minimal edits:** Reuse existing components and helpers. Avoid new abstractions unless necessary.
3. **Implement presentation-only changes:** Do not alter calculations, schemas, persistence, engineering rules, or Word generation.
4. **Run targeted tests:** Exercise the active phase and its direct dependencies.
5. **Run regression tests:** Run the full automated test suite available in the repository.
6. **Inspect diff:** Confirm that only intended files and lines changed.
7. **Verify state behavior:** Confirm first-entry persistence, navigation status, widget state, and saved-project reload behavior where the edited labels/widgets participate in Streamlit state.
8. **Stop on unexpected impact:** If unrelated behavior changes, fix or revert before proceeding.
9. **Complete the batch before starting another phase.**

### 7.3 Minimal-Change / Ponytail-Compatible Rules

* Prefer deletion of redundant UI copy over adding new explanatory layers.
* Reuse existing Streamlit primitives and existing project helpers.
* Do not add dependencies for typography, icons, copy management, or styling.
* Do not perform unrelated renaming, cleanup, reformatting, or architecture work.
* Do not modify tests merely to make a failing implementation pass unless the test is demonstrably obsolete and the user explicitly approves that change.
* Keep each batch reviewable and independently reversible.

### 7.4 Completion Report Required From the AI Agent

At the end of every batch, report:

* Active phase/batch name.
* Exact files changed.
* Short reason for each changed file.
* Tests run and their result.
* Any pre-existing failures observed.
* Confirmation that protected schemas, keys, Word generation, calculations, and validation tokens were untouched.
* Any engineering-copy item that was **not** changed because its source/authority could not be verified.

---

## 8. Agent Implementation & Acceptance Checklist

Before completing typographic remediation, verify the following acceptance criteria:

- [ ] **Data Schema Untouched:** No DataFrame column name (`"User Input"`, `"MD (m)"`, etc.) or dictionary key was altered.
- [ ] **Database Constants Preserved:** `materials_db.py` keys (`"Pre Flush"`, etc.) remain identical.
- [ ] **Validation Tokens Intact:** All bracketed tokens in `phase_10_procedure.py` are preserved.
- [ ] **Scoped String Centralization:** Reusable/standardized strings changed in the active batch are centralized where safe; untouched phases are not mass-migrated.
- [ ] **Functional Emojis Preserved:** `main.py` page icon (`🛢️`) and status icons (`✅`, `⚠️`, `⚪`) remain intact.
- [ ] **No Visual Sprawl:** No instructional text or caption longer than two lines is rendered visible by default.
- [ ] **Expander & Tooltip Migration:** Technical documentation is relocated to `help=` tooltips or closed `st.expander` components.
- [ ] **Unit Spacing Enforced:** Every numeric metric has a space before its unit symbol (`118.0 pcf`, `4.0 bpm`, `% BWOC`, `% BWOW`, `gal/sk`).
- [ ] **Sentence Case Normalized:** All page titles, form labels, and table headers are written in Sentence case.
- [ ] **Three-Part Messages Verified:** All warning and validation banners follow the condition-reason-action structure.
- [ ] **Word Guardrail Untouched:** The generation logic, procedural step wording, and engineering calculations in `phase_10_procedure.py` and `master_template.docx` remain completely unmodified.
- [ ] **Engineering Copy Source-Verified:** No new technical threshold, chemical-behavior rule, operational requirement, safety rule, or engineering claim was introduced from this UI specification alone.
- [ ] **Widget Identity Preserved:** Existing explicit Streamlit widget `key=` values remain unchanged; edited label-only widgets were regression-tested for state persistence.
- [ ] **Batch Scope Respected:** No unrelated phase or architecture cleanup was included in the current batch.
- [ ] **No New Dependencies:** No new package/dependency was added for UI-copy or typography work.
- [ ] **Targeted Tests Passed:** Tests relevant to the active phase passed or any pre-existing failure was clearly documented.
- [ ] **Full Regression Suite Checked:** The available full test suite was run after the batch, and unexpected regressions were resolved before proceeding.
- [ ] **Diff Reviewed:** The final diff contains only intended presentation-layer changes plus the minimal shared-string edits required by the active batch.
- [ ] **Pre-Publish Gate Confirmed:** All approved functional bug-fix batches were complete, cumulative regressions were green, and the owner explicitly authorized this UI pass before implementation began.
- [ ] **Functional Bugs Kept Separate:** Any functional/state/calculation/export bug discovered during presentation work was logged and routed back to the normal bug-fix workflow rather than fixed inside the UI batch.
- [ ] **Authority Conflicts Resolved Safely:** `AGENTS.md`, `zero_regression_contract.md`, verified engineering behavior, and protected report/schema rules were preserved wherever they took precedence over this presentation specification.
