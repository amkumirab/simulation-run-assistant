# Changelog

All notable changes to this project are documented in this file.

## [0.3.0] - 2026-08-04

### Added

- Clean, responsive assistant workspace for connecting COMSOL and configuring runs
- Local COMSOL discovery, model inspection, license checks, and parameter import
- Dashboard actions for targeted runs, queue-only submissions, next-job processing,
  job details, filtering, and failed-job retries
- Per-session write token, request limits, security headers, and loopback-only binding
- Dashboard API and selected-job runner tests

### Changed

- The dashboard is now an interactive workflow instead of a read-only status table
- Package version increased to 0.3.0

## [0.2.0] - 2026-08-03

### Added

- Official COMSOL batch adapter with automatic Windows executable discovery
- `sim-assistant comsol-check` for installation, model, study, and license validation
- Job-specific MPH copies, output models, batch logs, timeouts, and core limits
- COMSOL model inspection for parameters, physics, studies, and numerical features
- Saved table extraction and solver-log metrics
- Tests with a fake COMSOL process and synthetic MPH models

### Changed

- Solver adapters now receive an optional job-specific working directory
- COMSOL study-only runs exclude potentially stale saved tables from metrics and plots
- Package version increased to 0.2.0

## [0.1.0] - 2026-08-01

### Added

- SQLite simulation queue, retry workflow, local dashboard, and JSON/SVG artifacts
- Deterministic electromagnetic mock adapter
- Authorized Telegram command bot and run notifications
