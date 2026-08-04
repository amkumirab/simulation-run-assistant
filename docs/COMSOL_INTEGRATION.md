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
- The final COMSOL log lines are included in the stored job error for diagnosis.
- Telegram notification failures never alter the COMSOL job status.

## Security and repository safety

- Keep private MPH models outside the repository.
- Never commit license files or server credentials.
- Review generated artifacts before sharing them.
- Prefer a dedicated worker account for shared or production systems.
- Apply license-seat limits before enabling parallel COMSOL workers.
