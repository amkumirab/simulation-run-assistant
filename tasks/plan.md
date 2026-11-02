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

## Saved-solution sensor sampling

Implement the approved first research-roadmap increment in
`docs/COMSOL_FIELD_SAMPLING.md`: catalog exact saved frequency-domain states,
evaluate fixed Cartesian sensor locations, and connect results to Field Samples.
Use the installed compiler/batch engine and a private model copy. Never solve,
save the source, substitute nearest nodes, or infer MTJ suitability. Initially
reject non-3D/multiple-geometry models with an explicit explanation.
Build catalog/extraction tests first, then source bundles, then a native
background panel with cancellation and edit invalidation. Verify real saved WPT
states and unchanged source hashes, followed by native and full regression checks.
Keep future MTJ, ground-truth-separated datasets, multi-coil selection and static
replay work in that order. No remote publication in this implementation step.

## Saved-field documentation and version preparation

Finish the fourth publication slice without adding solver behavior. Expose the
checked offline replay in README, complete setup/selection/export/troubleshooting
instructions, and align package/version metadata at 0.34.0. Keep the changelog
entry Unreleased until publication is authorized; set the actual publication
date then, rather than retaining an old implementation date.
Verify constructor examples and local documentation links with focused tests,
then run full regressions, compile and build the wheel. Inspect wheel metadata
and packaged Java resources, and exercise the documented headless replay.
No model modification, new solve, dependency installation, tag or publication
is included in this preparation step.

## Model brief: specifications and assumptions

Implement the approved first Model Brief increment in `docs/MODEL_BRIEFS.md`.
First verify a bounded, strict JSON contract and provenance/quantity rules with
failing tests; then implement persistence. Connect a focused native editor to
Runs using existing styles, with pending-edit and unsaved-document protection.
Test UI workflows in an isolated temporary app database, inspect small/normal
windows, run full regressions and build the package. No new solver work,
dependencies, database changes, result association, report generation or remote
publication. Keep data/persistence tests together and UI/integration tests
together for later focused commits; do not commit before user finalization.

Publication authorized on 2026-11-02 in four focused commits: data contract and
tests, native editor and integration tests, illustrative example/native checks
and actual capture, then guide/README/changelog and 0.35.0 metadata. Test each
exact staged snapshot separately, push without rewriting history, and check the
remote commit identities and Python 3.10/3.12 workflow results. Original models,
production data, dependencies, tags and separate package releases stay outside
this publication workflow.
