# WPT Baseline Campaign

The native campaign workspace prepares and tracks a fixed 36-state alignment
sweep for a compatible wireless-power-transfer model. It is intended to produce
the first complete, scientifically accepted result set before multi-objective or
robust design analysis.

## Campaign definition

The preset uses:

```text
gap   = 100, 150, 200 mm
xoff  = 0, 25, 50, 75 mm
tilt  = 0, 5, 10 deg
yoff  = 0 mm
```

This creates `3 x 4 x 3 = 36` unique states. All other visible model inputs,
such as frequency and coil dimensions, keep their current fixed values from the
Workspace tab.

## Prerequisites

Before opening the campaign, configure and check a COMSOL connection with:

- a model that exposes `gap`, `xoff`, `tilt`, and `yoff` as design inputs;
- a selected model contract that declares those inputs and their safe limits;
- Job Sequence mode rather than Study mode;
- a Job Sequence that solves the model and reevaluates required Derived Values;
- a result pipeline reported as **Fresh**.

The campaign remains read-only and displays a corrective readiness message when
one of these requirements is not satisfied. It cannot bypass contract limits or
freshness checks.

## Open and review

Start the native application:

```powershell
sim-assistant desktop
```

Connect the production model, run **Check connection**, open **Runs**, and choose
**WPT campaign**. The table shows all 36 states with one of these statuses:

- **missing**: no matching run exists;
- **queued** or **running**: the state is already scheduled;
- **valid** or **warning**: an accepted result can be reused;
- **rejected**: the solver finished but scientific validation rejected the result;
- **unvalidated**: a result exists without a recorded validation decision;
- **failed**: the latest available attempt failed or was cancelled.

Double-click a row with a Job ID to open its full run details.

## Queue or run remaining states

Use **Queue remaining** to add eligible states without starting COMSOL. Use
**Run remaining** to add them and process them sequentially. Both actions require
confirmation.

Resume selection is conservative:

- accepted results are reused;
- queued and running states are not duplicated;
- missing, failed, rejected, and unvalidated states receive new jobs;
- earlier job records and diagnostic artifacts remain available.

The campaign identity includes the model fingerprint, target Job Sequence,
contract revision, selected Plot Groups, fixed inputs, and output formulas.
Changing any of these intentionally creates a new result identity rather than
silently reusing an incompatible run.

## Estimates

When recent COMSOL results are available, the summary estimates:

- sequential runtime from recent COMSOL wall-clock durations;
- output-model storage from recent `output_model_bytes` values.

These are planning estimates, not limits. Review free disk space with the
artifact storage manager before launching a large campaign.

## Reports

**Export CSV** writes one row per campaign state with its status, validation
state, Job ID, model inputs, and available metrics. Input columns use an
`input_` prefix and result columns use an `output_` prefix to avoid ambiguous
names.

**Export HTML** writes the same information as a self-contained, responsive
table that can be opened without the local database or an internet connection.
Neither report contains local model paths, artifact paths, or the model file
contents.
