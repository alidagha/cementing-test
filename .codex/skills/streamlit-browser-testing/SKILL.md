---
name: streamlit-browser-testing
description: Reproduce and verify real Streamlit UI, navigation, rerun, widget-state, persistence, dynamic-editor, completion-status, and browser-visible runtime bugs with headless Playwright using the existing Chromium installation. Use when the observed behavior depends on actual browser interaction; do not use for pure backend calculations or Word-only logic.
---

# Streamlit Browser Testing

Use this skill for browser-dependent behavior in the Cementing Engineering Report application.

This skill supplements the repository's existing engineering, regression, and mutation rules. It does not replace them.

Before doing anything, read and follow the repository root instructions that apply to the task, including:

- `AGENTS.md`
- `zero_regression_contract.md` when the task falls under that contract
- the active owner-approved task or bug specification

If those files are absent, report that fact before making any production change.

## When to use this skill

Use real browser testing for:

- Streamlit navigation or unexpected phase changes
- rerun-sensitive behavior
- widget value persistence
- first-entry or double-entry problems
- state lost after click, blur, Enter, navigation, or rerun
- callbacks versus render-time synchronization
- dynamic `st.data_editor` behavior
- draft-versus-canonical UI behavior
- save / restore / continue flows when browser interaction matters
- premature or missing completion indicators / green ticks
- disabled/enabled Build or Download controls
- browser-visible validation, warning, error, or recovery controls
- rendered UI layout or browser-visible runtime errors
- issues that reproduce in a real browser but are uncertain from code inspection or `AppTest`

Do not invoke this skill merely because a task involves Streamlit.

## When NOT to use this skill

Do not launch a browser for:

- pure calculation changes
- pure parsing helpers
- backend-only validation
- database/catalog constants
- static code review
- dependency cleanup
- Word-generation-only logic when the UI is not part of the reproduction
- tests already fully demonstrated by a direct unit test with no browser/state boundary

## Existing browser environment

Use the environment already available.

- Chromium executable: `/usr/bin/chromium`
- Python Playwright is available.
- Run Chromium headless.
- The Playwright-downloaded default browser may be absent.
- Launch Chromium explicitly with:

```python
browser = p.chromium.launch(
    headless=True,
    executable_path="/usr/bin/chromium",
)
```

Do not:

- run `playwright install`
- download another browser
- install Chromium
- add Selenium, Puppeteer, browser drivers, or another browser framework
- add a dependency to the project for browser testing
- modify `requirements.txt` merely to run this workflow

If local socket/process permissions block browser access to the locally running Streamlit app, use the environment's normal permission mechanism. Do not work around the restriction by changing application security or repository code.

## Local Streamlit app

Prefer an already-running local Streamlit instance.

If no instance is running, determine the repository's established launch command first. For this project, `main.py` is the expected entry point unless the current repository says otherwise.

Fallback:

```bash
python -m streamlit run main.py   --server.headless true   --server.port 8501   --browser.gatherUsageStats false
```

If port `8501` is occupied, choose an unused local port.

Keep temporary browser logs, screenshots, and diagnostic artifacts outside the repository unless the owner explicitly asks for them to be committed.

Stop any Streamlit process started only for the test when the test session is complete.

## Core rule: reproduce the user's path

A UI/state bug must be reproduced through the same interaction boundary that matters.

Do not prove a browser bug by directly mutating `st.session_state` unless the task is specifically about restored/session state and direct seeding is part of an approved setup.

Prefer interactions such as:

- fill the visible input
- select the visible option
- edit the visible table
- click the actual navigation control
- trigger the actual Streamlit rerun
- save through the actual UI when save behavior is under test
- upload through the actual uploader when restore behavior is under test

Use direct state seeding only to create a prerequisite fixture that would otherwise make the reproduction impractically long, and clearly report what was seeded versus what was tested through the browser.

## Browser workflow

### 1. Establish baseline

Before reproduction:

1. Confirm the intended repository revision.
2. Confirm the working tree status.
3. Identify the Streamlit entry point and local URL.
4. Identify the exact user scenario.
5. Record expected versus observed behavior.
6. Do not modify production code yet.

For a bug-fix task governed by `zero_regression_contract.md`, preserve its required Red/Green workflow.

### 2. Launch Playwright

Use Python Playwright.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path="/usr/bin/chromium",
    )
    page = browser.new_page()
    page.goto(APP_URL, wait_until="domcontentloaded")
    # reproduce / inspect / verify
    browser.close()
```

### 3. Use stable selectors

Prefer, in order:

1. accessible role + visible name
2. associated label
3. visible text with a narrow scope
4. stable application-specific attributes already present

Avoid brittle selectors based on generated CSS class names, deep DOM ancestry, element order alone, Streamlit implementation details, or arbitrary XPath chains.

When duplicate labels exist, scope the locator to the relevant phase, form, tab, container, or editor.

### 4. Respect Streamlit reruns

After an action that can cause a rerun:

- reacquire locators when needed
- wait for a deterministic post-rerun condition
- assert the state the user should actually observe

Prefer deterministic waits such as:

- `expect(locator).to_be_visible()`
- `expect(locator).to_have_value(...)`
- waiting for a known phase heading
- waiting for a warning/status to appear or disappear

Avoid arbitrary `time.sleep()` unless there is no stable observable condition. If a short sleep is unavoidable, explain why.

### 5. Inspect only what helps

Relevant evidence can include:

- visible widget values
- enabled/disabled state
- phase title after navigation
- completion/green-tick status
- visible warnings/errors
- actual table cell values
- browser console errors
- page exceptions
- computed style when the issue is visual
- screenshots when they materially help demonstrate a state or visual defect

Do not capture screenshots for every test by default.

Do not infer engineering correctness from appearance alone. A green tick proves only the UI status that was rendered.

### 6. Console and runtime inspection

When relevant, collect browser console messages during reproduction.

Treat a browser console error or Streamlit exception block as evidence, not automatically as the root cause.

Trace the actual application flow before choosing a fix.

### 7. Fix only when authorized

If the active task is audit/reproduction-only:

- do not modify files
- report the reproduced behavior and evidence
- stop at the requested boundary

If the task authorizes a fix:

- follow Ponytail/root-cause discipline
- make the smallest justified fix
- reuse existing state/callback/validation patterns
- do not create a parallel state-management system
- do not weaken validation or tests
- do not make unrelated UI cleanup changes

### 8. Green verification

After an authorized fix:

1. Repeat the same real-browser reproduction path.
2. Verify the original failure no longer occurs.
3. Verify the expected value/state survives the same rerun/navigation boundary.
4. Check relevant sibling workflows if shared code changed.
5. Check browser console/runtime errors when relevant.

### 9. Regression verification

Browser testing is supplemental. It never replaces:

```bash
pytest test_regression_guardrails.py -v
pytest tests/test_audit_regressions.py -v
```

Run the permanent guardrails and relevant repository regression suites when required by `AGENTS.md`, `zero_regression_contract.md`, or the active task.

If the browser scenario passes but a required regression suite fails, the task is not accepted.

If the regression suites pass but the browser reproduction still fails, the task is not accepted.

## AppTest relationship

`streamlit.testing.v1.AppTest` may supplement this skill.

Use real Playwright browser interaction when the bug depends on:

- actual browser/widget interaction
- navigation click timing
- rerun behavior visible to the user
- dynamic editor behavior
- actual uploader interaction
- focus/commit behavior
- rendered enabled/disabled controls
- browser-visible runtime behavior

Do not claim a real-browser issue is verified solely because an `AppTest` passes when the browser interaction itself is the disputed boundary.

## Recommended evidence for common Cementing bugs

### Unexpected return to Phase I

Verify current phase, exact edit, navigation action, phase after rerun, and whether the entered value persisted.

### First entry disappears / requires double entry

Verify initial visible value, first entry, commit action (`Enter`, blur, or another control), post-rerun visible value, and only attempt a second entry if the first fails.

The expected result is that the first valid entry persists.

### Dynamic table value clears

Verify the exact cell through edit -> commit -> rerun/navigation if relevant -> return to the table -> visible persisted cell value.

### Premature green tick

Keep a required field intentionally incomplete/invalid and verify visible phase status, sidebar status if present, and Build/Download readiness when relevant. Then verify the status changes correctly after valid completion.

### Save / restore

When browser interaction matters:

1. enter representative data through the UI
2. save through the intended UI path
3. restore through the actual uploader
4. navigate through affected phases
5. verify visible values, completion state, and export readiness

## Definition of done

For a browser-dependent bug, do not report completion unless all applicable items are true:

- The original user path was reproduced or inability to reproduce is explicitly reported.
- The pre-fix observed state was recorded.
- The root cause was identified before modification.
- Only authorized files/scope were changed.
- The same browser path passes after the fix.
- No relevant console/Streamlit exception remains.
- Relevant sibling workflow checks pass when shared code changed.
- Required permanent guardrails pass.
- Required batch/audit regressions pass.
- The final diff contains no unrelated browser-test artifacts.
- Test results are reported exactly as executed.

## Reporting format

Report:

```text
Browser scenario:
Repository revision:
Local app URL:
Chromium:
Reproduction:
Observed before:
Root cause:
Files changed:
Observed after:
Browser/console result:
Regression commands:
Regression results:
Screenshots/evidence:
Working tree:
```

If no production edit was authorized, report `Files changed: None`.

Do not claim deployment or hosted-environment verification based only on local browser execution.
