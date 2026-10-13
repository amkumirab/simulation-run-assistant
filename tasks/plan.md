# Implementation plan: Design Scenario Campaigns

Build the workflow described in `docs/DESIGN_SCENARIO_CAMPAIGNS.md` in three slices.
Reuse campaign signatures and the Series-Series solver, with a separate native
dialog to avoid expanding the main desktop module's analysis implementation.

1. Expansion, reuse and independent circuit grouping. Verify focused behavioral tests.
2. Saved configuration, evidence reports and desktop workflow. Verify restart and queue behavior.
3. Stored real-data replay, UI smoke checks, documentation and package verification.

Risks: cross-model reuse (exact identity check), false robustness claims (coverage
gate), shared nominal controls (one study per design), duplicate solves (canonical
classifier), accidental expensive solves (test only isolated databases).

No model changes, new dependencies, remote publication or actual COMSOL solves
are included. Tasks are tracked in `tasks/todo.md`.

## Next increment: operating envelopes

Implement `docs/OPERATING_ENVELOPES.md` without changing the completed campaign
workflow. First verify source-amplitude ceilings and failure isolation, then
portable evidence reports, then the native offline dialog and stored-data replay.
Retain separate scientific coverage and electrical feasibility. Rebuild identity
and acceptance from current jobs; incomplete coverage must not yield a global
power claim. No live COMSOL solves, new dependencies or remote publication.

## Scalable sweep workspace (0.31.0)

Approved scope: complete batch-scoped numeric comparison and ranking, paginated
native history and status summaries. No model mutation or new solver scheduling.
See `docs/SCALABLE_SWEEP_WORKSPACE.md` for acceptance and limits.

1. Prove full-history reads and bounded pages with isolated database tests.
2. Add a native sweep workspace and bounded analysis table navigation.
3. Verify large-history exports and stored/live COMSOL evidence separately.
4. Document, review, test and build; leave changes uncommitted for review.

## Budgeted experiment planner

Approved scope is documented in `docs/EXPERIMENT_PLANNER.md`.
Build generator and validation first; prove persistence and current-job reuse
next; integrate a separate native dialog last. Reuse existing signatures,
contract checks and sequential execution rather than introducing a scheduler.
Verify each slice with focused tests, then full regressions and a wheel build.
Risks: false sampling/optimality claims, discrete duplicate points, stale
identity and accidental solves. Mitigate with explicit shortfalls, persisted
points, current-identity checks and user-confirmed execution. Leave changes
available for review before remote publication.

## Field samples and sensor layout

Implement the approved offline scope in `docs/FIELD_SAMPLES.md`. First prove
typed phasor projection and unavailable-state handling, then bounded CSV/JSON
round trips and evidence exports, then the native editor and comparison view.
Reuse existing desktop styles and CSV escaping. Keep solver, queue and model
code unchanged. Verify native minimum/normal sizes and edit invalidation with
isolated data. Use labeled synthetic evidence; leave changes uncommitted.
