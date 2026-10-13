# Design Scenario Campaign tasks

- [x] Expand selected nominal designs into named scenarios and reuse eligible states.
  - Verify: focused unit tests including duplicate and identity boundaries.
- [x] Analyze each geometry with independent nominal controls and coverage gating.
  - Verify: two-design regression and stored WPT result replay.
- [x] Save/load configuration and export portable CSV/HTML evidence.
  - Verify: round trip, malformed input, escaped report text, no private paths.
- [x] Integrate native dialog with contract/Fresh pipeline checks and sequential queue.
  - Verify: isolated UI smoke tests, restart, pause/resume and model mismatch.
- [x] Document workflow and verify complete suite, package build and final diff.
  - Verify: unittest discovery, wheel build, content/secret review.

Verification on 2026-10-01: all 203 unit/integration tests passed. The isolated
native UI workflow check and 0.29.0 wheel build passed. Stored-result replay
retained 5/5 accepted states, 3 electrical passes and 2 failures. Two native
screenshots were reviewed. No live COMSOL solve, model modification, commit or
remote publication was performed.

## Operating envelope tasks

- [x] Calculate per-scenario RMS source ceilings and constrained power.
  - Verify: focused tests for every limiting component, target/derating and invalid data.
- [x] Recheck identity/acceptance and gate complete per-design summaries.
  - Verify: stale status, missing nominal, partial coverage and independent tuning tests.
- [x] Export escaped, path-free CSV/HTML with categorical power chart and evidence.
  - Verify: export parsing, formula injection, unavailable rows and suffix validation.
- [x] Add native offline dialog and isolated stored-result replay.
  - Verify: editing, invalid inputs, exports, keyboard and minimum-window layout.
- [x] Document use, capture genuine replay screenshots, run full tests and build.
  - Verify: complete unittest discovery, wheel content, diff and content review.

Verification on 2026-10-02: all 222 unit/integration tests passed, including
19 new operating-envelope tests. Both native workflow scripts passed; the
envelope check exercised editing, stale-result clearing, exports, keyboard
evidence windows and 960x700/1440x900 layouts in an isolated replay database.
Two genuine native screenshots were reviewed. Stored COMSOL replay gave three
target-met samples and two derated samples (3,222.212 W and 2,294.143 W capacity).
The final HTML report rendered five rows and twelve readable headings, with no
browser console warnings/errors; its 320-pixel layout contained horizontal table
scrolling without document overflow. The 0.30.0 wheel built successfully and
contained all six campaign/envelope modules. Compilation and diff checks passed.
No live COMSOL solve, production queue/model mutation, commit or push was performed.

## Scalable sweep workspace tasks

- [x] Add tested full-scope queries, batch summaries and paginated history.
- [x] Add native workspace and complete comparison/ranking with table paging.
- [x] Verify exports, keyboard navigation and large isolated history.
- [x] Inspect user models read-only and record honest COMSOL test evidence.
- [x] Update English documentation, review regressions and build the package.

Verification on 2026-10-08: all 237 tests passed on Python 3.12, including
15 new full-history, export and native UI checks. The native workflow passed
with five stored WPT results and separately with two new copied-model COMSOL
gap solves, each behind 10,000 newer synthetic records. Exports retained every
matching result; minimum and normal layouts and Enter-to-open details passed.
Four genuine native captures were recorded and reviewed. The 0.31.0 wheel
built and contained the new paging, sweep workspace and CSV helper modules.
Compilation, diff and changed-file language/attribution/token-pattern checks
passed. Source-model SHA-256 remained unchanged. No production queue mutation,
commit or push was performed. Tk tests skip only when no desktop is available;
the database and logic tests do not need a display or COMSOL license.

## Budgeted experiment planner tasks

- [x] Generate deterministic bounded continuous/integer experiments.
  - Verify: unique points, dimensions, counts, constraints and exhaustion tests.
- [x] Save exact points and rebuild evidence-aware campaign status.
  - Verify: JSON round trip, malformed files, accepted/active reuse and retry.
- [x] Add native preview, edit invalidation and guarded queue/resume workflow.
  - Verify: isolated desktop tests, no implicit queue changes, identity/pause gates.
- [x] Document usage, verify examples, review and build.
  - Verify: complete unittest suite, compilation, wheel, language/secret scan.

Verification on 2026-10-11: all 255 unit/integration tests passed, including
18 new planner tests. The isolated native check verified 30 unsolved samples,
five stored COMSOL records, full CSV exports, minimum/normal layouts, Enter
navigation and stale-preview clearing. Two genuine native screenshots were
captured and reviewed; stored evidence is explicitly separate from generated
unsolved samples. The 0.32.0 wheel built successfully; compilation and diff
checks passed. Publication text had no Persian, attribution or common secret
patterns. Original wireless_transfer.mph SHA-256 matched the prior recorded
hash. No new COMSOL solve, original-model/production-queue mutation, commit or
push was performed. Changes remain available for review.

## Field samples and sensor layout tasks

- [x] Validate typed datasets/layouts and project complex fields.
  - Verify: finite values, units, missing points, coordinates and phase tests.
- [x] Import bounded CSV, save/load exact workspace and export evidence.
  - Verify: round trip, malformed/oversized files, source digest and CSV escaping.
- [x] Add native metadata, layout editor and scenario comparison.
  - Verify: isolated import/edit/save/restart, keyboard and layout checks.
- [x] Add honest examples/screenshots, docs, review and full regression checks.
  - Verify: complete suite, compilation, wheel and publication checks.

Verification on 2026-10-13: all 276 tests passed, including 21 new field-sample
tests and native checks on Windows. The isolated application workflow verified
the Runs entry point, normalized complex samples, a 3x3 grid, eight available
readings plus one explicitly missing sample, full CSV export, minimum/normal
sizes, keyboard evidence and edit invalidation. Two actual native captures show
synthetic data only; no new COMSOL or real MTJ evidence is claimed. A visual
review corrected overlapping chart labels. The 0.33.0 wheel built successfully
and its four field modules matched current source bytes. Compilation and diff
checks passed. The original wireless_transfer.mph SHA-256 remained unchanged.
No production queue/model mutation, solve, dependency installation, commit or
push was performed. Direct saved-solution COMSOL extraction remains future work.
