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
