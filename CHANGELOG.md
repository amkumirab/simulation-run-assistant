# Changelog

All notable changes to this project are documented in this file.

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
