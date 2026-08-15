# Changelog

All notable changes to this project are documented in this file.

## [0.9.0] - 2026-08-15

### Added

- Native Results tab for previewing exported COMSOL PNG artifacts
- Plot list with Previous and Next navigation and original-file access
- Automatic preview scaling using built-in Tk image support
- Relocation-aware artifact lookup using stable exported filenames
- Tests for artifact confinement, missing files, preview scaling, and size labels

### Changed

- Job details now open in a larger resizable window for simulation images
- Plot previews are restricted to PNG files inside the selected job directory
- Package version increased to 0.9.0

## [0.8.0] - 2026-08-14

### Added

- Automatic PNG export for selected COMSOL Plot Groups after a successful solve
- One-pass COMSOL image exporter for multiple selected 1D, 2D, and 3D plots
- Stable plot filenames and per-image artifact metadata with file size and path
- Plot export status and errors in the native job-details window
- Unit coverage for successful, skipped, and isolated plot-export failures

### Changed

- Optional plot failures no longer discard a successfully solved COMSOL model
- COMSOL plot rendering uses software graphics for unattended desktop runs
- Package version increased to 0.8.0

## [0.7.0] - 2026-08-13

### Added

- MPH Plot Group discovery with tags, labels, plot types, and dimensions
- Native multi-select Plot Outputs control with Select all and Clear actions
- Validated Plot Group selection with duplicate, syntax, model-contract, and
  12-plot limit checks
- Plot selections in local workspace profiles and sanitized profile templates
- Selected Plot Group metadata in COMSOL connection and simulation results
- Plot discovery, ordering, validation, and profile-persistence tests

### Changed

- Native connection summaries now show the number of detected Plot Groups
- Package version increased to 0.7.0

## [0.6.0] - 2026-08-08

### Added

- Local native workspace profiles for COMSOL paths, targets, run settings,
  parameter presets, Fixed/Sweep modes, and computed-output formulas
- Recent-profile ordering and automatic restoration of the last saved workspace
- Profile creation, update, duplication, deletion, and missing-path warnings
- Sanitized JSON template export that excludes executable and MPH model paths
- Atomic profile-file updates and validation for profile names, targets, sweep
  definitions, core counts, timeouts, and formulas
- Profile storage, lifecycle, validation, path-warning, and privacy tests

### Changed

- Native model inputs and formulas are reapplied after a saved model is inspected
- Package version increased to 0.6.0

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
