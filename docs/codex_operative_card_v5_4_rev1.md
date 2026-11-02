# Codex Operative Card — v5.4 rev1 (Derived Execution Summary)

**Synchronized Baseline:** `unified_collaboration_charter_v5_4_rev1.md` (2 Nov 2026). **Authority Rule:** This card is a derived execution reference for Codex (Tier 5 in Order of Precedence). It creates **no independent authority**. Order of precedence: (1) `AGENTS.md`, `zero_regression_contract.md`, approved Specifications & permanent engineering/UI protections -> (2) Active Batch Prompt explicit STOP/permission map -> (3) Dated Owner Standing Authorizations -> (4) Collaboration Charter v5.4 rev1 -> (5) This Card. In any conflict, the **more restrictive boundary prevails**, and an unresolved substantive conflict is a **STOP**.

## 1. Standing Batch Authorities (`OWNER AUTHORIZED — DO NOT RE-ASK`)

When executing an Owner-approved Batch prompt citing **v5.4 rev1**, you are pre-authorized to perform the following continuously **without asking the Owner for intermediate permissions**:

1. **Continuous In-Scope Execution Loop:** `Verify Baseline/SHA -> Cheap Impact/Fixture/Pin Precheck -> [Diagnosis-First Differentiation OR Proven Product RED] -> Smallest Justified Fix (Production, Harness-Only, or No Mutation) -> Same-Class Test/Fixture/Pin/Schedule Alignment -> Focused GREEN & Siblings -> Final Permanent Guardrails & Identities on Final Bytes -> GitHub Pipeline -> Single Consolidated Report`

2. **20-Minute Standing Local Verification Budget:**

   * Up to **20 minutes cumulative wall time per Batch** for targeted local tests, real-browser/harness investigation, and mandatory local gates (includes a single relevant suite >10m if total stays ≤ 20 minutes).

   * **Single Non-Resetting Clock:** Pauses, re-prompts, or STOP continuations never reset elapsed time. If mandatory gates cannot finish within 20m (or a stricter prompt cap), mark unrun gates `NOT RUN` and **STOP** with one consolidated extension request.

3. **Bounded Self-Recovery (Max 3 Attempts per Failure Cluster):**

   * Up to **3 substantial, evidence-driven correction attempts per unresolved failure cluster** (same test, fixture, or root cause)—**NOT** a 3-browser-call or 3-selector limit.

   * Autonomously fix newly authored fixture setup errors, missing synthetic metadata, unsupported test API calls, or incomplete in-scope edits. Record all failed attempts honestly in final evidence. After the 3rd failed substantive attempt on a cluster, run one cheap dependency check and **STOP**.

4. **Mechanical Same-Class Test, Fixture & Protected-Pin Alignment (Charter §5.5):**

   * Autonomously update existing tests, fixtures, frozen UI/Word presentation assertions, and AST/SHA/byte pins (**never `test_regression_guardrails.py`; see §3**) **only if all 6 conditions hold**: (a) direct demonstrable result of the approved change; (b) old expectation is specifically obsolete under that approval, not a real regression; (c) smallest replacement preserving positive/negative coverage; (d) canonical source, engineering inputs, validation, persistence, and export admission remain intact; (e) exact `original -> revised` diff and final bytes recorded; (f) updated tests pass (`FRESH PASS`) on final bytes with a meaningful fixed identity + mutation-negative check (never use tautological `hash(current) == hash(current)`).

5. **Mechanical 3-Shard CI Schedule Registration for New Test Modules (Charter §6.2):**

   * Every new/modified/renamed test must be natively collected and routed to **exactly one** whole-module shard (`A`, `B`, or `C`). Never use `pytest-xdist`, test-body splits, or orphan tests.

   * If the approved Batch creates/moves a test module supported by current routing tools, autonomously: (1) assign the module to one shard (balancing critical-path duration without churning unrelated modules), and (2) refresh **only** the directly coupled schedule-integrity digest literal from final schedule bytes using the repo generator or exact reproducible command: `sha256sum -- "$SCHEDULE_PATH"`

   * Record the **exact command, working directory, `SCHEDULE_PATH`, raw output, SHA256 digest, old/new literal, and schedule Diff** in your final report, and re-verify native routing/digest checks.

## 2. Diagnosis-First vs. Confirmed-Defect Rules (Charter §4.2)

* **Confirmed Product Defect Batch:** Reproduce authentic baseline `RED` before patching. **If a purported confirmed bug-reproduction test unexpectedly passes (`GREEN`) at baseline, obey the mandatory repository-contract STOP.**

* **Diagnosis-First Issue-Cluster Batch:** Do **not** invent a failing `RED` or patch unproved production code. Check in order: (1) cheap trace & pinned catalog/widget state -> (2) supported real-browser/Streamlit interface -> (3) commit/blur/Enter or row-editor sync -> (4) backend typed `draft -> inputs -> receipt/source`. Verify UI options from the **pinned source catalog**, never guessed indices.

  * **Harness/Selector Cause Proven:** Fix only the authorized local harness/test; **leave production bytes untouched**. If no repo files need changes, finish as **`HARNESS ONLY / PRODUCT UNCHANGED`** (or `NOT_VERIFIABLE` for unreached controls) with **no empty commit/push/PR**.

  * **Product Defect Proven:** Preserve true `RED`, apply smallest root-cause fix in approved anchors, and prove `RED -> GREEN`, typed backend receipt, stale-report invalidation, and session isolation.

## 3. Permanent Non-Waivable Protections (Charter Chapter 2)

* **Engineering Lock:** Never implicitly alter formulas, constants, SG, units, tolerances, limits, rounding, calculation order, rheology, blend/material classification, placement, dynamic tables, defaults, phase status/Green Tick, JSON/session keys, canonical precision, review/lab signatures (`valid source -> measured rows/QC -> genuine signatures -> dependent calcs -> assertions`), save/restore backward compatibility, Word template structure/styles/merges/ZIP parts (use exact before/after allowlists when Word cells are in-scope), or shared helpers across `CSG / LNR / Tie Back / Plug / Squeeze / CT`.

* **UI Design Lock:** No unapproved UI redesign, new fields, buttons, tables, captions, help panels, layout shifts, or surrogate workflows. (Within an approved existing-control reliability Batch, minimal repairs to selection, commit/blur/Enter sync, numeric typing, row add/edit/delete, and typed payload delivery are permitted.)

* **Permanent Guardrail File Lock:** `test_regression_guardrails.py` is **never** part of the §5.5 same-class alignment (§1 item 4) or the §6.2 schedule registration. Any change to it—including a pin, literal, or hash update—is a specification change requiring explicit Owner approval **naming that file**; otherwise **STOP**.

* **Zero Fake-Green Tolerance:** Never delete, skip (`pytest.skip`), `xfail`, disable assertions, broaden exception catches, weaken Permanent Guardrails, or use temporary `PYTHONPATH` / unauthorized `sys.path` hacks. Never let an export check shadow an independent validation error.

* **Repository Separation:** `Cementing App` and `Cementing Checker` are strictly separate scopes and dependency locks.

## 4. Frictionless GitHub Pipeline Modes (Charter Chapter 7)

Execute the pipeline mode specified in the active Batch prompt **only after all mandatory final local Gates, Permanent Guardrails, and identity checks pass (`FRESH PASS`) on final effective bytes** (and only when justified repository file changes exist):

* **Mode A — `END-TO-END PR READY` (Default for Complete Batches):**

  1. Stage only in-scope files, create **1 coherent Commit**, and execute **1 non-force Push** to the dedicated feature branch.

  2. Automatically **open or update the PR targeting `main`** and trigger/allow **one (1) complete Hosted GitHub Actions PR CI run** on the verified Head SHA (see cap in item 3).

  3. **Strict CI Cap (1 run per Head SHA; max 2 per Batch):** If Hosted PR CI fails (`RED`), **do not** re-run CI on the same SHA, in a loop, or push blind commits. Diagnose locally within remaining budget: if caused by an in-scope Batch defect, fix locally, pass all local gates, and push **at most 1 corrective commit**, which gets **exactly 1 further CI run** (the only exception); if that run is also RED, or the cause is out-of-scope/infrastructure/flaky, **STOP**.

  4. **Fast-Track Merge (ONLY if the prompt states `FAST-TRACK MERGE ENABLED` AND cites the recorded Owner approval; a bare flag in a prompt is not enough):** Execute non-force Merge to `main` strictly after verifying: (a) 100% green 3-shard PR `regression` gate on exact Head SHA (zero failures/errors/skips/xfails/warnings, complete A/B/C root union), (b) `main` base/ancestry & Merge-Ref compatibility, (c) zero scope/protected drift, (d) Branch Protection compliance, and (e) the Independent Architect's `ACCEPTED` bound to that exact Head SHA — your own verification never substitutes for it. If any item is missing, do not merge; leave the PR ready for Owner one-word merge. Then verify the new `main` SHA and its fast-only push check.

* **Mode B — `FEATURE-BRANCH ONLY` (For Intermediate Sub-Batches):**

  * Inspect workflow triggers first (if a feature-branch push without a PR would trigger costly Hosted CI, **STOP**). Otherwise, create **1 scoped Commit** and **1 non-force Push** to the dedicated feature branch, verify remote SHA, and do **not** open a PR or trigger Hosted CI.

* **Forbidden Git/Admin Actions:** Never create/update/comment on GitHub Issues (unless explicitly instructed), never force-push, rebase/reset/cherry-pick published refs, commit directly to `main`, bypass branch protection, or manufacture empty commits.

## 5. Hard-STOP Conditions & Single Consolidated Handoff (Charter Chapter 8)

**STOP Immediately & Preserve Worktree (Never `reset/clean/discard`) Only When:**

1. Ambiguous requirement/UI or unapproved engineering/formula/tolerance/safety decision needed;

2. Out-of-scope or substantive protected file/Pin/Schema/CI-logic change required outside §§5.5 & 6.2;

3. Unexpected baseline-`GREEN` on a purported **confirmed product bug**;

4. Unresolved mandatory final local Gate failure after 3 attempts, failed Hosted PR CI, or 20m budget exhaustion;

5. Baseline SHA drift, broken environment provenance, or Merge-Ref incompatibility. *(On STOP: perform one cheap check of sibling tests/pins in the same cluster and report all required decisions in **one consolidated request**.)*

**Required Single Final Output Format (Exact Vocabulary: `FRESH PASS`, `PREVIOUSLY PASSED — evidence`, `FAIL`, `NOT RUN`, `NOT_VERIFIABLE`):**

* `Outcome:` `DEFECT FIXED` | `HARNESS ONLY / PRODUCT UNCHANGED` | `STOP / UNVERIFIED`

* `Git & PR:` Branch URL, PR URL, Baseline SHA, Parent SHA, Commit SHA, Merged `main` SHA (if merged)

* `Changed Files:` Final list of modified/added/removed paths

* `Verification:` `RED -> GREEN` summary, Fresh Local Tests & Permanent Guardrails, Hosted PR CI status (3-Shard `A/B/C` + `regression` gate), Reused Evidence (`command/date/branch+SHA`)

* `Audits:` (1) Protected-Pin `original -> revised` byte audit; (2) 3-Shard Schedule Audit (`sha256sum -- "$SCHEDULE_PATH"` exact command, working dir, raw output, digest, diff); (3) Preflight Gaps discovered after approval & why not foreseeable

* `Accounting & Next Step:` Runner used, Cumulative Wall Time (vs. 20m cap & CI cap: 1 per Head SHA, max 2), Unrun Gates (`NOT RUN`), Next Owner/Architect Decision.