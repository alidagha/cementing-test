# Pre-Round-14 — UI Bug Hunt 3 Closure and Engineering Evidence

**Project:** Cementing App / Cementing Report Engine  
**Repository:** `alidagha/cementing-test`  
**Decision date:** 2026-10-23  
**Owner decision:** Stop further speculative UI Bug Hunt 3 discovery; close confirmed defects and prepare the Round 14 entry checkpoint.  
**Governance:** Owner-approved Collaboration Charter v5.2, `AGENTS.md`, `zero_regression_contract.md`.  
**Status of this document:** Closure evidence for the integration PR. Main integration and checkpoint are **pending required PR regression and merge** until independently verified. This document is not a full-suite or native-desktop certification certificate.

## 1. Scope and commit chain

The following **five linear commits** are based on `main` at `f26e8926ffbff586459a358b626826235d835389` and are carried by the integration branch:

| Area | Commit | Verified purpose |
| --- | --- | --- |
| UI01 | `fdcfeb14a6246e59261c89775635ca9574674d42` | Preserve manual override mode across widget navigation |
| UI02-01 | `b610035815cd6c4ffa716909ac4b4d6a64ce3635` | Preserve unsaved inactive-fluid drafts during replacement |
| UI02-02 | `8353a7a2a81acecc5dc65b9ce319b5be1685d262` | Ignore lazy defaults in project loaded-baseline dirty checks |
| UI03-01 | `e4db7795135fc3039fe9ce281586ec80f42b75c5` | Reject stale Full Cement Lab review in report admission |
| UI03-02 | `5237c069a684a4b4ea76d30f050e4e6caa670ed2` | Reject stale Pre Flush identity in prepared report context and invalidate compiled document on genuine name changes |

The UI03-02 publication was independently observed on the remote feature branch, with exactly three modified files and one parent `e4db7795...`. The five-commit compare against the stated main baseline reported `ahead_by=5`, `behind_by=0`, with ten changed files. No engineering or Word template redesign is part of this documentation batch.

## 2. Confirmed issues and disposition

- **UI03-01 — resolved on feature branch.** Full cement `reviewed` and `review_signature` are enforced during calculation preparation and prepared report admission. Reject invalid or stale lab authority and retire previously compiled document authority. Preserve the malformed-fluid-volume F3 priority.
- **UI03-02 — resolved on feature branch.** Canonical Pre Flush identity is validated at the prepared report boundary. Blank/invalid names or stale canonical-versus-derived identity cannot be exported from prepared context; `fluid_data` fallback remains for legacy projects without canonical params. Meaningful Pre Flush name edits invalidate existing compiled Word outputs.
- **Additional issues:** No further **confirmed** outstanding UI Bug Hunt 3 defect was reported when the owner decided to stop discovery. This does not establish the absence of all latent bugs.

## 3. Verification: distinguish evidence from certification

| Gate | Observed evidence | Qualification |
| --- | --- | --- |
| UI03-01 permanent regression | 59 PASS | Reported by Codex, reused when dependencies were unchanged |
| UI03-01 permanent guardrails | 38 PASS | Reported by Codex; source and pin reviewed separately |
| UI03-02 combined UI03 regression | **89 PASS**, 92.94s | Includes original 59 plus 30 additional tests |
| UI03-02 F3 precedence | **1 PASS**, 7.05s | Permanent protected test unchanged |
| UI03-02 selected sibling regressions | **33 PASS** and 17 passing subtests | Separate earlier combined run contained one 120s Round 3 timeout |
| UI03-02 isolated Round 3 Word test | **1 fresh PASS**, 66.54s, original 120s limit | Both real DOCX builds and original assertions completed |
| UI03-02 final permanent guardrails | **38 fresh PASS**, 16.86s | Candidate unchanged |
| Round8B SHA/identity | PASS | Guardrail source SHA-256 `7eb9600298277a7665b751f807ddb5fb9b13974e91380bb73478cc442d112384` |
| Full Repository Regression | **NOT RUN on consolidated candidate** | Required PR `regression` must pass prior to main merge |
| GitHub Actions for integration | **PENDING** | Strict `main` ruleset requires PR + `regression` |
| Native browser / desktop Word/PDF visual certification | **NOT RUN** | Do not conflate AppTest/real DOCX creation with desktop certification |

An earlier combined regression hit a 120-second timeout in the Round 3 test's **initial CSG Word build**, before the Pre Flush edit. The identical test subsequently passed in isolation (66.54s); no timeout limit or assertion was changed. The original timeout cause remains **not verifiable**. Neither a proven application regression nor a permanent waiver was established.

Passing results are Codex execution evidence with independently inspected source/diff/remote SHA where noted. An unexecuted gate is not implied to have passed.

## 4. Permanent safeguards

- Never weaken `test_regression_guardrails.py` (38 tests), its original assertions or the Round8B whole-file SHA pin without new, specific owner authorization.
- Preserve canonical/session/draft data, Save/Load, calculations, F3 precedence, CT/Spacer/Rheology siblings, operational water and additives, and Word template/certified text.
- No PR #10 CI-duration modification should enter the Bug Hunt 3 integration; its separate feature branch is retained if its PR is closed.
- Avoid unnecessary follow-on Bug Hunt activity; prioritize confirmed calculation, persistence/data-loss, or report-integrity defects only.

## 5. Closure policy and next gate

**Discovery and approved feature-fix scope: CLOSED by owner decision.**  
**Integration into main: NOT COMPLETE until PR mandatory `regression` succeeds and GitHub confirms merge.**  
**Checkpoint: NOT FINAL until the merged main SHA is recorded and the checkpoint ref is verified.**

Round 14 may be planned, but implementation does not commence merely because this document exists. Follow the product's fixed sequencing and obtain explicit owner approval of the Round 14 scope. Do not silently infer Full Regression, production certification or new engineering requirements.
