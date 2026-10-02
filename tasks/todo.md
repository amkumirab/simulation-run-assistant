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
