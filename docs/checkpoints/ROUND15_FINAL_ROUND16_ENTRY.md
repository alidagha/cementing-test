# Round 15 Final Integration Checkpoint and Round 16 Entry

**Repository:** `alidagha/cementing-test`  
**Integration date:** 2026-10-27 UTC  
**Status:** Round 15 merged; Round 16 kickoff baseline established (NO production implementation authorized by this document).

## Verified integration baseline

- **Merged PR:** [#14 — Round 15 nested well geometry / Tie Back C1–C3](https://github.com/alidagha/cementing-test/pull/14).
- **Old main:** `40b1398dfd35f6348102984b9b20a5ee8fe6a58c`.
- **Original feature commit:** `9b152bde8398a44fb52c311f915dba3215ddeded`.
- **Corrective feature commit:** `c854ef4418678ca0ba0da68a84453179e9c72425` (parent `9b152bd`).
- **Merge commit / Round 16 immutable baseline SHA:** `d500ffdd33b639683b844a15890b115d2577894b`, with parents `40b1398` and `c854ef4`.
- **Checkpoint ref:** `checkpoint/round15-final` created at that exact merge commit. Do not advance this ref in normal feature work.
- **Round 16 working ref:** `feat/round16-kickoff`, initially created at that exact merge commit.

## GitHub certification

- **Fresh required PR regression:** [run 40396295033](https://github.com/alidagha/cementing-test/actions/runs/40396295033).
- **Verified tested head:** `c854ef4418678ca0ba0da68a84453179e9c72425`.
- **Result:** exact checkout PASS; Fast gate PASS; Certification gate PASS; **4,762 tests passed, 0 failed, 0 errors, 18 warnings**, 9,821.68 seconds for the pytest suite.
- No skip/xfail claims are inferred from this summary. Some non-blocking warnings remain.
- **Post-merge separate main workflow:** NOT VERIFIED / NOT CLAIMED.
- **Native browser, native desktop Word/PDF and matched CemCADE numerical parity:** NOT VERIFIED / NOT CLAIMED.

## Round 15 engineering disposition

- Nested installed casing/liner/Tie Back geometry is now integrated.
- Actual receiving-liner geometry retained for Chart/Schematic/Pumping under their supported contracts.
- Frozen Centralizer remains a scalar-wall solver. Physically valid two-ID Tie Back is rejected *by that solver* rather than collapsed to a fictional single diameter; the separate scalar-supported reference is explicitly synthetic.
- Dynamic active-body validation preserves measured upstream workstring OD in volumes and source identity. No frozen physics engine changes.
- Diesel fixture seeding restored to actual piecewise OD measurements and original volume assertions.
- Original Guardrails, historical Identity controls, certification signature scope and Word template preserved under the reviewed PR.
- A previously observed report-only `Top of Cement` override versus calculated Executive Summary Top is intentional separation in current production logic. It was not changed by Round 15; an operator/report-consistency review may be considered only under separate approved scope.

## Round 16 kickoff governance / STOP boundary

1. Read the **owner's current Collaboration Charter v5.3 rev5** (it supersedes the repository's older v5.2 document), `AGENTS.md` and `zero_regression_contract.md` before an implementation batch.
2. Use current `main` and exact SHA at each new batch as source of truth. Begin Round 16 work from this integration baseline; do not reuse uncommitted pre-merge worktrees.
3. Keep the approved sequencing: Functional UAT → Manual Program Checker + Checker UAT → Typography/UI → Offline Standalone Production Build & Source Protection. Do not skip earlier gates or authorize UI/build on the basis of this checkpoint alone.
4. Round 16 **functional requirements / bug list are not designated by this checkpoint**. Scope discovery, evidence review and a compact two-stage execution prompt are allowed; production edits and broader engineering scope require the owner's specific approval.
5. Maintain 38 permanent guardrails and 5 protected identities, relevant same-domain regression/Word/JSON/hydraulic protections, and true local/CI status. Do not infer CemCADE parity.
6. No automatic merge, release, deployment, tag rewrite, code or template migration is authorized by kickoff.

## Start-state acceptance

- [x] PR #14 merged into `main`.
- [x] Exact `main` merge SHA independently verified.
- [x] Required PR CI completed successfully for exact corrective head.
- [x] Dedicated Round 15 checkpoint ref created.
- [x] Dedicated Round 16 branch created from the merged baseline.
- [ ] Round 16 implementation specification designated and approved by Owner.
- [ ] Round 16 functional/code changes implemented and tested.
- [ ] Round 16 PR regression, review, and merge.

**Record type:** project checkpoint and entry record; not a new engineering feature, implementation approval, production release certificate, or CemCADE certificate.
