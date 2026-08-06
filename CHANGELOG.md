# Changelog

All notable changes to this project are documented in this file.

## [0.5.0] - 2026-08-06

### Added

- Native Fixed/Sweep mode for COMSOL model parameters
- Comma-separated and inclusive `start:stop:step` sweep input syntax with units
- Cartesian job-count preview, 500-job safety limit, and sequential runtime estimates
- Targeted sequential execution for every job created by a desktop sweep
- Batch and X-axis filters, dependency-free comparison charts, highest-value
  highlighting, and UTF-8 CSV export
- Unit coverage for sweep parsing, expansion limits, runtime estimates,
  numeric values with units, comparison filtering, and CSV output

### Changed

- Native comparison history now loads up to 500 successful jobs
- Package version increased to 0.5.0

## [0.4.0] - 2026-08-05

### Added

- Native Tkinter desktop assistant started with `sim-assistant desktop`
- COMSOL model browsing, connection checks, parameter editing, queue actions,
  run details, artifact access, and cross-run comparison without a web server
- Safe computed-output formulas with arithmetic, engineering functions,
  formula dependencies, validation limits, and per-formula error reporting
- COMSOL saved-table output-symbol catalog for formula authoring
- Backward-compatible SQLite migration for stored output formulas
- Formula, migration, runner integration, and output-symbol tests

### Changed

- Result artifacts now record the formulas associated with each simulation
- Package version increased to 0.4.0

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
