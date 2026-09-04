# COMSOL batch integration

Simulation Run Assistant can run COMSOL Multiphysics models through the official
`comsolbatch` executable. The integration has no Python runtime dependencies and
keeps solver-specific behavior behind the adapter interface.

## Requirements

- A local COMSOL Multiphysics installation
- A license for every product required by the MPH model
- One readable `.mph` source model
- A known study tag or COMSOL job-sequence tag
- JSON-compatible parameter values matching the model's global parameter names

Do not publish internship, customer, or proprietary MPH files, license data, or
generated results. Point to private models through environment variables.

## Configuration

```text
COMSOL_EXECUTABLE      Full path to comsolbatch.exe; auto-detected on Windows
COMSOL_MODEL_PATH      Full path to the private source MPH model
COMSOL_STUDY_TAG       Study to run, such as std1
COMSOL_JOB_TAG         Alternative job sequence; do not set with STUDY_TAG
COMSOL_TIMEOUT_SECONDS Maximum solve time; default 3600
COMSOL_CORES           Optional positive core count
COMSOL_CONTRACT_PATH   Optional versioned model contract JSON file
```

The adapter automatically selects the study when the model contains exactly one
study. An explicit tag is required when multiple studies exist.

Windows PowerShell example:

```powershell
$env:COMSOL_EXECUTABLE="C:\Program Files\COMSOL\COMSOL63\Multiphysics\bin\win64\comsolbatch.exe"
$env:COMSOL_MODEL_PATH="C:\private\model.mph"
$env:COMSOL_STUDY_TAG="std1"
$env:COMSOL_TIMEOUT_SECONDS="1800"
$env:COMSOL_CORES="4"
$env:COMSOL_CONTRACT_PATH="C:\private\model-contract.json"
```

## Validate before running

```powershell
sim-assistant comsol-check
```

The check reports:

- Installed and model COMSOL versions
- Model physics and required licensed products
- Global parameter names and default expressions
- Available studies and numerical features
- Selected study or job
- License products required by the MPH model
- Model-contract compatibility with Ready, Warning, or Blocked findings

See [COMSOL model contracts](MODEL_CONTRACT.md) for the schema, WPT example,
input-limit behavior, and stable output bindings.

The native desktop application also provides a duplicate-run preflight before
queueing. It compares the selected model revision, Study or Job Sequence, Plot
Groups, formulas, and parameter state with signed jobs already in the database.
See [Run Preflight](RUN_PREFLIGHT.md) for the matching rules and workflow.

Values can also be provided directly for one check:

```powershell
sim-assistant comsol-check `
  --model "C:\private\model.mph" `
  --study std1 `
  --timeout 1800 `
  --cores 4
```

## Guided dashboard workflow

Start the local assistant:

```powershell
sim-assistant serve
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080), then:

1. Confirm the auto-detected `comsolbatch.exe` path and select an MPH model.
2. Choose a study or job-sequence tag, timeout, and optional core count.
3. Select **Check connection** to inspect the model and validate licenses.
4. Review the imported global parameters and edit the values for this run.
5. Select **Run now** for a targeted foreground run or **Queue only** to leave
   it for the worker.
6. Open any row in the run queue to inspect its parameters, results, artifact
   directory, or error. Failed runs can be returned to the queue from here.

The dashboard is intentionally local-only. The model path is sent to the local
Python process for the requested check or run but is not written to a settings
file. A random in-memory token protects write actions for the lifetime of each
dashboard session.

## Native desktop workflow

The native assistant provides the same local COMSOL workflow without starting
the dashboard server:

```powershell
sim-assistant desktop
```

Use the native file picker to select `comsolbatch.exe`, an MPH model, and an
optional versioned JSON contract. After a successful connection check, the app
loads declared design inputs into editable fields and catalogs numeric symbols
from saved single-row COMSOL tables. Define optional computed outputs, run or
queue the model, and use **Compare runs** to inspect one metric across different
input states.

To build a sweep directly in the desktop app, change a parameter mode from
**Fixed** to **Sweep** and enter either comma-separated COMSOL values such as
`70[kHz], 80[kHz], 90[kHz]` or an inclusive `start:stop:step` range such as
`70:100:10[kHz]`. Multiple swept parameters create a Cartesian product. The app
previews the number of states, estimates sequential runtime from recent COMSOL
runs, asks for confirmation before large submissions, and enforces a 500-job
desktop safety limit.

Sweep execution is sequential. In **Compare runs**, select the batch, a numeric
input for the X axis, and an output metric. The highest value is highlighted;
the visible comparison can be exported as a UTF-8 CSV file.

### Local workspace profiles

The native app can save the complete repeatable workspace under a profile name:

- Local COMSOL executable and MPH model paths
- Local model-contract path
- Study or Job Sequence selection
- Timeout, core count, and run label
- Parameter values and Fixed/Sweep modes
- Computed-output formulas
- Selected 1D, 2D, and 3D Plot Group tags

Profiles are stored only in `.sim-assistant/profiles.json`. This directory is
ignored by Git, and profile paths are never copied into job result artifacts.
The most recently saved profile is restored on the next desktop launch. The app
reports moved or unavailable local files and keeps execution disabled until the
COMSOL connection is checked again.

Use **Duplicate** to create a model variant without changing the original
profile. Use **Export template** to create a JSON file without either local path;
the exported file retains target tags, run settings, parameter presets, and
formulas so the non-path parts of a workflow can be reviewed or shared.

### Plot Group discovery

The connection check reads Plot Group metadata directly from the MPH model and
lists each feature tag, dimension, and label in the native workspace. Multiple
plots can be selected, with a limit of 12 per profile. Selection is validated
against the currently inspected model before a COMSOL run; missing, duplicated,
or malformed tags are rejected instead of silently referring to another result.

After a successful solve, the adapter opens `output.mph` through the official
COMSOL Java API and exports every selected Plot Group as a PNG. All selected
plots are handled in one COMSOL process so the solved model is loaded only once.
Stable filenames combine the feature tag and label, and each exported image is
recorded in result metadata with its dimension, absolute artifact path, and file
size.

The exporter uses COMSOL software rendering and therefore does not require an
open COMSOL Desktop window. It does require `comsolcompile` beside the configured
batch executable; this compiler is included with a standard COMSOL installation.

### Native Results viewer

Double-click a completed job in the run queue and select the **Results** tab to
preview its exported Plot Groups inside the desktop application. The viewer uses
Tk's built-in PNG support, scales large images to the available preview area,
and provides Previous, Next, and Open PNG actions. The caption reports the Plot
Group label, dimension, original image dimensions, and artifact size.

The viewer resolves images from the current job's `plots` directory by stable
filename, so an artifact directory can be moved with its database record updated.
Recorded paths outside that job directory, non-PNG files, and path traversal are
rejected before an image is loaded or opened.

### Comparing sweep plots

Select a Plot Group in the native **Results** tab and choose **Compare runs**.
The application finds successful jobs with the same batch name and COMSOL Plot
Group tag, then displays their PNG artifacts side by side in job-number order.
Each card includes the recorded parameter state, artifact size, an Open PNG
action, and a marker for the job where the comparison was opened.

The gallery loads no more than 12 states at once to bound image memory. It keeps
the selected job in the gallery even when that job is older than the most recent
12 results. Failed jobs, other batches, unmatched Plot Group tags, missing PNGs,
and files outside their job artifact directories are excluded automatically.

Choose **Export report** in the comparison window to save the displayed states
as a self-contained HTML file. PNG bytes are embedded directly in the document,
and every job card contains its complete recorded parameter table. The report
uses a responsive card layout on screen and a two-column layout when printed.

Exported reports do not contain source-model paths, artifact-directory paths, or
external resources. Text values are escaped before writing, the target must use
an `.html` extension, and the completed document replaces its temporary file
atomically. After saving, the application can open the report in the system
browser for immediate review.

Supported formula operations are `+`, `-`, `*`, `/`, `%`, and `**`. Supported
functions include `abs`, `sqrt`, `log`, `log10`, `exp`, `sin`, `cos`, `tan`,
`min`, and `max`; constants `pi` and `e` are also available. Formulas are parsed
by a restricted evaluator and cannot import modules, access attributes, execute
statements, or call arbitrary code.

Formula errors do not discard a successful COMSOL solution. Successfully
computed values are added to result metrics, while individual formula errors
are stored in result metadata and shown in the run-details window.

### Fresh physical outputs

The symbols shown from an MPH model initially describe saved table columns and
may represent an older solution. A `-study` run computes the selected Study but
does not automatically reevaluate every Derived Values node. The adapter
therefore keeps those saved values out of fresh metrics.

For formulas based on inductance, coupling, power, efficiency, or other physical
results, create a COMSOL job sequence containing:

1. The required Solution step.
2. **Evaluate Derived Values** for the numerical result nodes.
3. A Save step when needed by the model contract.

Select **Job sequence** in the native app and enter that job tag. Metrics
extracted from the reevaluated tables can then be used by computed-output
formulas and compared across runs.

## Enqueue a COMSOL job

Create a manifest whose parameter names exactly match COMSOL global parameters.
Include units in string values when the model requires them:

```json
{
  "name": "comsol-frequency-sweep",
  "adapter": "comsol",
  "fixed": {
    "gap": "15[cm]",
    "drive_current": "2[A]"
  },
  "sweep": {
    "frequency": ["80[kHz]", "85[kHz]", "90[kHz]"]
  }
}
```

Then run:

```powershell
sim-assistant enqueue examples\your-comsol-manifest.json
sim-assistant run --limit 1
```

The adapter passes parameters with COMSOL's `-pname` and `-plist` options. A
parameter value cannot contain commas or newlines. Parameter names are limited
to letters, digits, underscores, and dots, and must begin with a letter or
underscore.

## Artifact layout

```text
artifacts/job-000001/
|-- input.mph
|-- output.mph
|-- comsol.log
|-- plot-export.log       Present when one or more Plot Groups are selected
|-- plots/
|   `-- pg1-magnetic-flux-density.png
|-- result.json
`-- response.svg       Present only when a multi-row numeric table is found
```

The original source model is never modified. Every job runs against its own
copy, which also prevents concurrent jobs from writing to the same MPH file.

## Result extraction

The adapter reads saved COMSOL table data from `output.mph`:

- Single-row numeric tables become scalar metrics.
- The first multi-row table with at least two columns becomes the response
  series and SVG plot.
- Table columns and rows are preserved in result metadata, capped at 1,000 rows
  per table.

Running a study does not reevaluate every Derived Values node. For study-only
runs, saved tables are retained in metadata for inspection but are deliberately
excluded from scalar metrics and response plots so stale values cannot be
presented as fresh results. Solver-log metrics and output model parameters are
still reported.

If fresh postprocessing tables are required after each solve, configure a COMSOL
job sequence containing the solution and numerical evaluation tasks, set
`COMSOL_JOB_TAG`, and leave `COMSOL_STUDY_TAG` unset. Tables produced by that job
contract are included in metrics and plots.

## Failure behavior

- COMSOL runs with `-error on` and an internal `-stoptime` limit.
- A Python-side timeout provides an additional 60-second shutdown allowance.
- A missing output model, nonzero exit code, invalid parameter, or license error
  marks only that queue job as failed.
- A plot compilation or image-export error is recorded per selected Plot Group
  but does not discard a successfully solved model or its numerical results.
- A missing or moved PNG is reported only in the native preview; it does not
  change the stored simulation status.
- The final COMSOL log lines are included in the stored job error for diagnosis.
- Telegram notification failures never alter the COMSOL job status.

## Security and repository safety

- Keep private MPH models outside the repository.
- Never commit license files or server credentials.
- Review generated artifacts before sharing them.
- Prefer a dedicated worker account for shared or production systems.
- Apply license-seat limits before enabling parallel COMSOL workers.
