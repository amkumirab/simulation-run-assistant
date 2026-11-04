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

## Saved-solution sensor sampling tasks

- [x] Catalog and extract explicit saved states from a private model copy.
  - Acceptance: complex Cartesian fields, no solve/save, strict source identity.
  - Verify: unit tests, compiler check and live saved-result extraction.
- [x] Preserve a portable source evidence bundle.
  - Acceptance: CSV/workspace hashes, exact solution parameters, no local paths.
  - Verify: round trip, invalid/incomplete output and corruption tests.
- [x] Connect a native saved-field panel to Sensor layout.
  - Acceptance: responsive work, cancellation, stale-result rejection, English UI.
  - Verify: isolated desktop workflow and minimum/normal size checks.
- [x] Document and review the complete increment.
  - Acceptance: usage, limits, genuine test evidence, unchanged source models.
  - Verify: full regression suite, compilation, wheel and publication scan.

Verification on 2026-10-15: all 292 tests passed, including 16 new sampling and
native-panel tests. The existing isolated offline UI check also passed. Real
saved WPT aligned and 30 mm RX-offset models were cataloged and sampled at nine
fixed +Z sensors, preserving complex Cartesian components. Both source hashes
matched after sampling. The source bundle reloaded exact fields/layout and
exported all nine comparison rows. Native minimum/normal sizes passed; actual
simulation-result screenshots were captured and inspected. Out-of-domain and
unsupported legacy-model cases failed closed without partial imports or solves.
The final strict line protocol was also verified against the real catalog.
Compilation, 0.34.0 wheel, whitespace and publication-text checks passed. No
runtime dependency or COMSOL security setting changed. Source models and the
production queue remained unchanged. No commit or push was performed.
Live coverage is the flat inner sweep documented in the guide, not arbitrary
solution structures, sensor calibration or loaded-vehicle detection.

## Saved-field example publication slice

- [x] Prepare the existing solved-model check and genuine native captures.
- [x] Include a portable, path-free saved WPT field example without MPH files.
- [x] Add offline replay with bounded integrity checks and isolated native UI.
- [x] Test damaged/inconsistent bundles, optimized Python and headless exports.

Verification on 2026-10-29: all 309 tests passed on the isolated third-slice
snapshot, including nine new replay/example tests. Compilation and the wheel
build passed; the package version remains 0.33.0 in this slice. A fresh read of
the existing aligned and 30 mm RX-offset models using COMSOL 6.3.0.290 produced
byte-identical CSV/workspace data to the checked example. Both source model
SHA-256 hashes remained unchanged. Nine current/reference readings, source
bundle round trips, full CSV export and native minimum/normal sizes passed.
The center +Z peak projection changed from 37.5295187133 uT to 36.4984380917 uT.
Three actual native captures were inspected. Offline replay, including clean
desktop closure, required no COMSOL process or production database. Text,
common-secret-pattern and whitespace checks passed. No solve, dependency
installation, original model modification, commit or push was performed.
Global documentation and the version bump remain in the fourth publication
slice. MTJ response and hardware/vehicle detection are not implemented here.

## Saved-field documentation and version-preparation slice

- [x] Expose the checked replay and direct sampling guide in README.
- [x] Complete setup, source selection, export distinctions and troubleshooting.
- [x] Correct the SavedState constructor example and add documentation checks.
- [x] Align project/package/changelog versions and verify the 0.34.0 wheel.

Verification on 2026-10-30: all 313 tests passed, including four documentation
checks. The corrected constructor example, relative documentation/image links,
replay discoverability and version consistency passed. Compilation and the
0.34.0 wheel build passed; wheel metadata declares no third-party runtime
dependencies, and packaged sampling modules/Java resources match source bytes.
The documented headless replay exported all nine comparison readings without
COMSOL or production database activity. The native CLI help and imported package
version were checked. English text, common secret/attribution patterns and
whitespace checks passed. Runtime behavior, source models and existing datasets
were not changed. No solve, dependency installation, commit, tag or push was
performed at that preparation checkpoint. The changelog was left Unreleased
until publication authorization.

## Model brief tasks

- [x] Strict model brief contract and atomic JSON persistence.
  - Acceptance: unknown remains unknown; sourced values, dated confirmation,
    finite quantities and bounded input with no executable expressions.
  - Verify: `test_model_briefs.py` red/green and round-trip/failure tests.
- [x] Native form and Runs entry point.
  - Acceptance: add/edit/remove and save/load without silent loss of pending
    edits; no COMSOL, results or queue mutation.
  - Verify: `test_model_brief_desktop.py` and actual native size/keyboard checks.
- [x] Usage documentation and final quality checks.
  - Acceptance: English usage and limits; no new dependencies or attribution.
  - Verify: full regressions, compilation, wheel, diff and publication scan.

Verification on 2026-11-02: all 331 tests passed, including 18 new model brief
and native-editor tests. Contract tests first failed for the missing module,
then passed; native tests followed the same red/green sequence. The isolated
native check passed at 920x700 and 1160x780, including Enter/Tab focus,
pending-edit rejection, save/load round trips and empty queue/connection state.
The actual application capture uses explicitly illustrative metadata, not a
solved or inspected COMSOL model. Optional capture initially lacked Pillow in
the project venv; the already-bundled runtime supplied it without installation.
Ordinary native checks passed in the project venv without Pillow.
Compilation and the wheel build passed; packaged brief modules match source
bytes, with no new runtime dependencies. Local README/guide links and image,
English text, common secret/attribution patterns and diff whitespace passed.
Five-axis review found no blocking issue within the declared scope. Free-text
source privacy remains the user's responsibility; stored confirmation and model
hashes are declarations, not authentication or engineering certification.
No original model, production database, queue schema or existing result format
was changed. No solve, dependency installation, version bump, commit, tag or
push was performed at that preparation checkpoint. Automatic result association and revision comparison reports
remain outside this increment.

Publication verification on 2026-11-02: the separately exported staged data
snapshot passed all 324 tests; the native-editor snapshot passed all 331 tests;
the illustrative-example snapshot passed all 331 tests and its actual native
workflow check. Each snapshot imported its own source tree, not the unpublished
working tree, and passed compilation and staged publication/whitespace checks.
Those three focused commits were pushed without changing existing history.
The fourth publication slice completes the guide, README, changelog and 0.35.0
package metadata, with full snapshot regression/build verification required
before its commit and push. No model or production result is part of these files.

## Saved geometry inspector tasks

- [x] Read-only engine, geometry protocol and SI envelope validation.
  - Verify: focused field/geometry regressions and live saved-model measurement.
- [x] Portable snapshot/CSV and explicit proposed brief generation.
  - Verify: strict round trips, corrupt input, no inferred confirmation/clearance.
- [x] Native table, schematic envelopes, cancellable inspection and stale guards.
  - Verify: isolated actual UI, keyboard, minimum/normal sizes, no queue changes.
- [x] Real model/replay examples, captures and docs; staged publication gates below.
  - Verify: unchanged source hashes, all tests, package resources and remote CI.

### Geometry inspection verification record (2026-11-04)

Three existing 3RX MPH models (original, overlap, height-matched control) each
returned 13 saved domains through the packaged COMSOL 6.3.0.290 helper. Original
SHA-256 values matched before/after. Center TX/RX Z envelopes differed by about
150 mm. Side layers were 20 mm higher in overlap/control, and only overlap
reduced side-center offsets from 280 to 140 mm. These are approximate geometry
measurements, not solved performance or clearance claims.

An actual native background inspection matched the original portable fixture
exactly, with no callback errors or queued jobs. All three isolated native
replays passed keyboard and 1000x760/1240x850 bounds checks. Four unretouched
RGB window captures were visually reviewed; each is 1240x850, labels offline
replay and contains no source path or embedded personal image metadata.

The legacy wireless-transfer model was rejected for multiple geometries; it
was not rebuilt and its source hash matched. A separate disposable synthetic
2D model failed the 3D requirement. A disposable 200x100x5 mm block verified
the measurement API returns geometry-unit bounds before SI conversion. Those
diagnostic fixtures are not research results and are not published as examples.

Regression checks include malformed units/large integers, frame/source identity,
cancellation/failure, strict corrupt/oversized JSON, CSV formula protection,
explicit proposal statuses, late-worker rejection and independent draft lifetime.
Review found and fixed unsaved drafts closing with their inspector; the new
regression demonstrates drafts survive inspector close. Existing field sampling
and model brief workflows remain covered. No dependency, schema, source-model
or production database change was made.

Publication is split into engine, portable exports, native workspace and worked
examples/documentation. Each exact staged source snapshot is tested separately,
not against later unpublished code. The engine snapshot passed 337 tests and
the portable-export snapshot passed 341. The native snapshot passed 349 tests.
Combined native checks also exposed idle theme callbacks and queue-poll timers
left by older test workspaces. A shared test-only teardown now flushes idle
theme work, destroys dialogs before cancelling root jobs and destroys the
interpreter last. Module teardown collects released Tk objects on the UI thread
before subsequent worker tests can trigger garbage collection. A focused
regression asserts no pending callback remains;
no test assertion, skip policy or quality threshold was removed.
Final gates include the complete example suite, compilation, wheel resource checks, exact staged
English/private-path/credential/attribution scans and remote CI. Live COMSOL and
native-window checks run locally; headless CI does not replace them.
