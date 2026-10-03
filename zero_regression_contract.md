# Zero-Regression Contract: Cementing Report App

**Target System:** Streamlit Cementing Engineering Application  
**Contract Type:** AI Bug-Fix Execution Guardrail  
**Revision:** 1.3 — Ponytail-Compatible Batch, Regression-Authority & Activation Update  
**Recommended Filename:** `zero_regression_contract.md`  
**Current Bug Specification:** the owner-designated active verified bug specification or explicitly approved work unit  
**Bug Specification Authority:** the latest owner-approved verified bug specification or task scope explicitly designated for the current work  
**Regression Authority:** permanent invariants in `test_regression_guardrails.py` plus relevant bug/batch regression tests in `tests/`

Applies to bug-fix tasks on the Streamlit cementing engineering app.

Keep this file in context through `AGENTS.md`, `CLAUDE.md`, Cursor rules, agent instructions, or the system prompt.  
The long Persian zero-regression protocol is intended as a human reference only and should not be pasted into routine bug-fix prompts.

When `AGENTS.md` contains Ponytail rules, the two documents are complementary: Ponytail governs implementation simplicity, reuse, and root-cause discipline; this contract governs mutation scope, protected behavior, verification, regression safety, and acceptance. If they appear to conflict, preserve engineering correctness and regression safety and use the smallest root-cause fix permitted by the active owner-approved scope.

If a separate typography/UI-copy specification is present, it governs presentation-only work. This contract remains authoritative for bug-fix execution, regression safety, protected engineering behavior, and test integrity. A typography/UI task must not be used as implicit authorization to change bug-fix protected items.

---

## 1. Rules

1. **One owner-approved implementation unit per cycle and per commit.**  
   The default implementation unit is one bug. The owner may explicitly define a **batch** that contains multiple confirmed issues. A batch is allowed only when its issue list and scope are explicitly approved before editing and the batch is verified as one bounded change set.

   A single Codex Cloud task/thread may process multiple implementation units **sequentially**, but never mix unrelated work inside one active unit. Each unit must complete its full `Restate → Red → Fix → Green → Regression → Diff → Commit → Report` cycle before the next unit begins.

   For an approved batch:
   - every included issue must be explicitly listed,
   - each issue must have a reproducible failure or confirmed baseline behavior,
   - fixes must remain inside the approved batch scope,
   - the full relevant regression suite must pass for the batch,
   - the batch receives one separate commit unless the owner explicitly requests finer-grained commits.

   If you notice an unrelated bug while working on the active unit, log it and leave it untouched until the current unit is fully completed and committed.

2. **Targeted anchors with minimum root-cause reach.**  
   Start from the file and function/class/symbol anchors named in the active bug specification or approved batch.

   The agent may also modify the **minimum directly related shared helper(s)** required for a demonstrated root-cause fix when all of the following are true:

   - the additional change is necessary to solve an issue already inside the active scope,
   - reusing or correcting shared logic is safer than duplicating a local workaround,
   - no unrelated behavior is intentionally changed,
   - every additional file/symbol is reported in the final diff summary,
   - relevant regression tests cover the shared change.

   Pure helper functions may be added to shared modules such as:

   - `engineering_tools.py`
   - `placement.py`

   when they are explicitly designated **or** demonstrably required by the approved root-cause fix. Do not create helpers merely to reorganize code.

   Examples may include:

   ```python
   density_range_error(...)
   casing_od_inches(...)
   is_valid_thickening_time(...)
   ```

   Locate code by:

   - symbol name
   - function name
   - class name
   - function signature
   - stable text anchor

   Never use line numbers as the primary patch anchor.

3. **No unsolicited changes.**  
   Do not perform unrelated:

   - refactoring
   - variable or function renaming
   - visual restyling
   - comment cleanup
   - type-hint cleanup
   - formatting-only rewrites
   - architectural restructuring
   - dead-code cleanup

   outside the designated bug anchors.

4. **Never make tests pass by weakening them.**  
   The following are prohibited:

   - changing expected values to match broken behavior
   - deleting tests
   - skipping tests
   - adding `xfail`
   - removing assertions
   - adding broad `except` blocks to hide failures
   - hardcoding outputs for specific test inputs
   - mocking or bypassing production logic solely to satisfy tests

5. **Smallest root-cause fix.**  
   Solve the issue at its algorithmic root with the smallest justified change.

   Do not mutate public function signatures unless the bug specification explicitly requires it.

6. **Streamlit state and widget safety.**  
   Never mix `value=` with a keyed widget using `key=` when the repository's state pattern does not allow it.

   Follow the established application patterns:

   - **Pattern A — `on_change` commit dispatcher:** for number inputs and sliders.
   - **Pattern B — shadow key with `_seed()`:** for selectboxes and text inputs.

---

## 2. Protected Items

The following items are immune to modification unless an explicit exception applies.

### 2.1 Word Template

```text
master_template.docx
```

Must not be modified unless the active owner-approved bug/batch explicitly requires a template-level fix. Any authorized template change must preserve dimensions, fonts, styles, tables, layout, and unrelated placeholders/tags, and must be regression-verified.

---

### 2.2 Certified Engineering Wording in `phase_10_procedure.py`

Protected content includes:

- procedural steps
- NOTE wording
- headings
- legal wording
- NIDC-approved phrasing
- safety-critical wording
- engineering instruction text rendered into Word output

The **logic of `phase_10_procedure.py` is not globally protected**.

Bugs in its logic may be fixed normally when the file and anchor are authorized by the bug specification, but the substantive wording of certified text must remain unchanged unless the owner explicitly authorizes a wording change.

---

### 2.3 Forced Dry-Blend Catalog

```python
materials_db.FORCED_DRY_BLEND_NAMES
```

The contents and semantics of this catalog are protected.

---

### 2.4 Regression Guardrails

Permanent invariants:

```text
test_regression_guardrails.py
```

Bug/batch-specific regressions live in the relevant tests under `tests/`, including when applicable:

```text
tests/test_audit_regressions.py
```

`test_regression_guardrails.py` must not be modified during ordinary bug-fix work. Changing a permanent guardrail requires an explicit specification change authorized by the owner.

Bug/batch regression tests may be added or extended for confirmed issues, but existing tests must not be weakened, deleted, skipped, or rewritten merely to match broken behavior. Bug/batch regressions extend the permanent guardrails; they do not override them.

---

### 2.5 Core Data Schema

The following must remain byte-for-byte stable unless explicitly authorized.

#### DataFrame column names

Examples:

```text
"User Input"
"MD (m)"
"Material Type"
"Name"
```

#### Database constants

Examples:

```text
"Pre Flush"
"Spacer"
"Displacement Fluid"
"CEMENT G DELIJAN"
```

#### Session and JSON keys

Examples:

```python
p["dead_vol"]
qc["bhct"]
cfg["params"]
```

Changing presentation labels is permitted when required, but underlying schema keys must remain unchanged.

---

### 2.6 Protected-Item Exception

Changes explicitly described in the **active owner-approved verified bug specification or approved work unit** are considered pre-approved **only for the protected items and behavior that the owner explicitly authorizes**.

A valid work identifier may be a `BUG-xx`, an `Issue xx`, or an explicitly named batch, as long as the owner clearly designates the active scope.

If the owner later designates a newer verified specification, that newly designated file becomes the authority for subsequent work. Do not assume that the highest-numbered file is authoritative unless the owner or task explicitly designates it.

Anything else that touches a protected item requires human confirmation.

---

## 3. Workflow

Every implementation unit (single bug or explicitly approved batch) must follow this sequence.

### Step 1 — Restate the Bug

Before editing, restate:

```text
Active specification / approved work unit:
Work unit type: Single bug / Approved batch
Bug ID or Batch ID:
Included Issue IDs (if batch):
Primary target file(s):
Primary target anchor(s):
Observed behavior:
Expected behavior:
Reproduction input(s):
Associated test(s):
Owner decisions applied (if any):
```

If the active bug specification is ambiguous, missing, or conflicts with another bug document, **STOP before modifying production code** and request owner clarification.

---

### Step 2 — Red

Run or write the reproduction test.

The test must fail on the baseline before the fix.

Expected state:

```text
RED = FAIL
```

If the reproduction test already passes on the baseline, **STOP**.

Possible causes include:

- incorrect anchor
- incorrect reproduction test
- environment mismatch
- bug already fixed
- stale bug specification

Do not modify production code until the mismatch is understood.

For UI-state or Word-visual bugs, use when feasible:

```python
streamlit.testing.v1.AppTest
```

or direct `.docx` XML inspection.

---

### Step 3 — Fix

Apply the minimal surgical root-cause fix.

Use the smallest surgical root-cause fix. A directly related shared helper may be reused, corrected, or added only when it is demonstrably necessary for the approved scope and is covered by relevant regression tests.

---

### Step 4 — Green

Run the bug-specific reproduction test again.

Required result:

```text
GREEN = PASS
```

---

### Step 5 — Regression Guardrails

Always run the permanent guardrails:

```bash
pytest test_regression_guardrails.py -v
```

Also run the relevant bug/batch regression tests for the active work unit, including `tests/test_audit_regressions.py` when it contains coverage for the affected behavior.

Required result:

```text
100% PASS
```

No permanent guardrail or relevant active regression may fail.

---

### Step 6 — Review `git diff`

Run:

```bash
git diff
```

Verify all of the following:

- only files within the approved bug/batch scope changed
- only primary anchors and minimum directly related root-cause helpers changed
- no unrelated refactoring occurred
- no whitespace pollution exists
- no certified wording changed
- no data schema changed
- no debug code remains
- no temporary instrumentation remains
- no test weakening occurred

---

### Step 7 — Commit

Use one commit per owner-approved implementation unit. For an explicitly approved batch, one batch commit is allowed.

Recommended format:

```text
fix(<module>): <short description>
```

Example:

```text
fix(engineering_tools): preserve negative scalar parsing
```

### Step 8 — Close the Bug Cycle Before Continuing

After the commit and report for the active implementation unit are complete:

- verify the workspace is clean or contains only explicitly known non-bug artifacts
- do not carry uncommitted changes from the completed unit into the next unit
- if continuing in the same Codex Cloud task, explicitly restate the next Bug ID or Batch ID and restart at Step 1
- if the repository was externally changed between bugs, refresh/rebase/restart from the intended repository state before editing

A Cloud task/thread is a conversation/work context, **not** the atomic safety boundary. The atomic safety boundary is the owner-approved implementation unit (single bug or explicit batch) and its commit.

---

## 4. Honest Reporting

Test results may only be reported as executed if they were actually run during the current session.

### Required Reporting Rules

If a test was executed, report:

- exact command
- pass/fail result
- concise terminal summary

Example:

```text
Tests run:
pytest test_regression_guardrails.py -v

Result:
14 passed in 2.31s
```

If execution capability is unavailable, write:

```text
NOT RUN
```

and provide the exact commands the human developer should execute.

Never claim:

- Red
- Green
- PASS
- regression safety
- successful deployment

based only on code inspection or reasoning.

Cloud deployment cannot be verified solely from local execution.

Treat deployment and hosted-environment validation as separate external steps.

---

## 5. Invariants

The authoritative executable source for **permanent regression invariants** is:

```text
test_regression_guardrails.py
```

Relevant bug/batch regressions under `tests/` provide additional executable coverage for confirmed fixes but may not weaken or override these permanent invariants.

The table below is a human-readable summary of behaviors that must never break.

| Area | Behavior that must hold |
|---|---|
| **Yield** | Lead slurry at `104 pcf`, SG `3.20`, no additives → `1.818 ft³/sk`. Tail slurry at `118 pcf` → `1.360 ft³/sk`. |
| **Lab cup** | `lab_cmt_gr = 1058.0 / yield`. Lead reference → `582.0 g`. |
| **Mix water** | More than `20 ft³/sk` raises `ValueError`. |
| **Temperature** | `BHCT ≤ BHST` through `lab_temperature_valid`. |
| **Depth** | `TVD ≤ MD` through `test_tvd_must_not_exceed_md`. |
| **Parsing** | `parse_effective_numeric("-118") == -118.0`; `parse_effective_numeric("80-82") == 81.0`. |
| **Digits** | Persian and Arabic digits normalize to Latin before numeric parsing. |
| **Density / rate** | Density > 0 and pump rate > 0. Range `"3.5-5.0"` returns `3.5`. |
| **Time** | `format_to_hr_mm(75.0) == "01:15"`; negative time raises `ValueError`. |
| **JSON I/O** | Reject `NaN`, `Infinity`, and duplicate keys. `replace_project_state` must fully roll back on failure. |
| **Additives** | Liquid additives are always forced to `In Mix Water`. `FORCED_DRY_BLEND_NAMES` are always forced to `Dry Blend`. |
| **Word notes** | `NoteCounter` remains sequential and preserves reserved `NOTE 20`. XML entities `&`, `<`, `>` are escaped. |
| **Placement** | `measured_depth` and `target_descriptions` mappings remain stable. |

Changing any invariant is a:

```text
SPECIFICATION CHANGE
```

—not an ordinary bug fix.

It requires explicit owner authorization.

---

## 6. Setup & Execution Checklist

- [ ] Confirm `test_regression_guardrails.py` exists at the repository root.
- [ ] Run `pytest test_regression_guardrails.py -v` against the intended baseline and confirm 100% PASS before treating it as the active permanent regression authority.
- [x] The guardrail source includes an explicit `TVD ≤ MD` invariant.
- [x] The guardrail source includes a Word-template/rendering smoke test.
- [ ] Run all relevant bug/batch regression suites in addition to the permanent guardrails.
- [ ] Execute implementation units strictly in the order explicitly designated by the owner, completing one full bug/batch cycle and separate commit before starting the next.

---

## 7. Bug Spec Template
### Provided by Human

```text
Active specification / approved work unit:
Work unit type: Single bug / Approved batch
Bug ID or Batch ID:
Included Issue IDs (if batch):
Target file(s):
Primary anchor(s) (function/class/symbol):
Observed behavior:
Expected behavior:
Reproduction input / Associated test:
Owner decisions applied (if any):
Known shared helpers/modules:
Protected items explicitly authorized for change (if any):
```

`Known shared helpers/modules` may list expected shared code, but it is not an exhaustive mutation whitelist. If the root-cause fix demonstrably requires a minimum directly related shared helper inside the approved scope, the agent may modify it and must report and regression-test that additional change.

Example:

```text
Authorized helper functions/modules:
- engineering_tools.py::density_range_error
- placement.py::casing_od_inches
```

---

## 8. Report Template
### Returned by AI Agent

```text
Active specification / approved work unit:
Bug ID or Batch ID:
Included Issue IDs (if batch):
Root cause(s):
Files changed:
Anchors/helpers changed:
Tests run: <command + terminal result summary, or NOT RUN>
Bug/batch-specific test result:
Permanent regression guardrail result:
Relevant regression-suite result:
Diff summary:
Protected text/schema changed: No / Explicitly authorized
Unrelated changes: None
Deployment verification: NOT RUN / external
```

---

## 9. Frontier-Model Freedom Within the Contract

This contract is intentionally designed to preserve a strict zero-regression boundary without unnecessarily constraining high-capability engineering models.

The model may reason broadly and investigate dependencies, but code modifications remain bounded by the authorized scope.

### 9.1 Root-Cause Freedom

The model is expected to solve the actual cause of the bug rather than patching symptoms.

This includes permission to reuse, correct, or introduce a pure shared helper when explicitly designated or when it is demonstrably necessary for the minimum root-cause fix inside the approved scope.

Example:

```python
def density_range_error(...):
    ...
```

or:

```python
def casing_od_inches(...):
    ...
```

The presence of multiple function changes is therefore not automatically a violation when they are the minimum directly related changes required by the approved root-cause fix and are fully reported and regression-tested.

---

### 9.2 No Artificial Single-Function Restriction

The contract does **not** require every bug to be solved entirely inside one existing function.

The correct restriction is:

```text
Modify the approved primary anchors plus only the minimum directly related shared helpers required for the demonstrated root-cause fix.
```

If the active scope begins at:

```text
Primary anchor:
phase_5_cement.py::render_cement_program
```

and investigation demonstrates that shared validation in:

```text
engineering_tools.py::density_range_error
```

must be corrected to avoid duplicated local workarounds, both changes may be valid. The additional shared change must stay inside the approved issue/batch behavior, be reported, and be covered by regression tests.

---

### 9.3 Investigation Is Broader Than Mutation

The model may inspect:

- call sites
- tests
- dependent modules
- schema definitions
- constants
- serialization flow
- Streamlit state flow
- Word output logic

to understand the bug.

Inspection does not grant permission to modify those locations.

Modification authority comes from the owner-approved bug/batch scope and this contract. Investigation may reveal the minimum directly related shared helper required for the root-cause fix, but it does not authorize unrelated cleanup.

---

## 10. Four Key Advantages of This Contract

### 10.1 Freedom to Reuse or Create Necessary Root-Cause Helpers

Rule 2 allows the model to reuse, correct, or add a pure shared helper when the approved root-cause fix demonstrably requires it.

This prevents the agent from being artificially trapped inside a single existing function body while still prohibiting unrelated refactoring.

Examples include:

```text
engineering_tools.py::is_valid_thickening_time
engineering_tools.py::density_range_error
placement.py::casing_od_inches
```

---

### 10.2 Consistent Active-Spec References

The authority is the **latest owner-approved verified bug specification or explicitly approved work unit designated for the current work**.

Do not hard-code a revision filename into the contract. A newer specification supersedes an older one only when the owner explicitly designates it.

Work identifiers may use:

```text
BUG-xx
Issue xx
Batch N
```

or another unambiguous owner-designated identifier.

This prevents stale references while keeping agent instructions, bug definitions, test cases, and owner decisions aligned.

---

### 10.3 Database Guard Alongside Word Guard

The contract protects both:

- certified Word/report content
- underlying project data schema

DataFrame columns such as:

```text
"User Input"
```

must not be renamed simply to improve presentation.

UI display names may be changed through presentation-layer configuration while preserving the actual schema.

---

### 10.4 Depth Guardrail Is Explicitly Stabilized

The physical invariant:

\[
TVD \le MD
\]

is explicitly represented both in the invariant table and the setup checklist.

This ensures the depth relationship remains part of the permanent regression contract.

---

## 11. Explicit Batch Mode

Batch mode is an owner-controlled exception to the default one-bug work unit.

A batch is valid only when the owner explicitly defines:

- the Batch ID
- the included confirmed Issue IDs
- the intended scope
- any owner engineering decisions needed for those issues

Batch mode does **not** authorize unrelated cleanup or broad refactoring.

Within an approved batch:

- the agent may investigate shared root causes across included issues,
- shared fixes should be preferred over duplicated per-issue workarounds,
- every included issue must have a regression check,
- permanent guardrails and all relevant batch regressions must pass,
- one separate batch commit is allowed,
- the next batch must not begin until the current batch is committed and reported.

If an issue discovered during the batch is outside the approved list, record it and leave it untouched unless the owner explicitly adds it to the active batch.


---

## 12. Final Acceptance Rule

An implementation unit is acceptable only when all of the following are true:

```text
Every included bug/issue reproduction is resolved
AND
Root cause(s) are addressed
AND
Only the approved scope plus minimum directly related root-cause helpers were modified
AND
Every additional shared change is reported and regression-tested
AND
Protected text/schema remains intact except where explicitly authorized
AND
test_regression_guardrails.py = 100% PASS
AND
all relevant active bug/batch regression tests = 100% PASS
AND
git diff contains no unrelated changes
AND
Reported test results are truthful
```

If any one of these conditions is false, the patch is not ready for acceptance.

For sequential work in a single Codex Cloud task, this acceptance rule applies independently to **each owner-approved implementation unit**. For an approved batch, every included issue must satisfy its expected behavior and the batch must satisfy the cumulative regression gate before commit. The next unit must not begin until the current unit has satisfied the acceptance rule, been committed separately, and its results have been reported.
