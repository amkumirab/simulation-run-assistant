# COMSOL model contracts

A model contract is a small, versioned JSON file that describes the parts of an
MPH model required by a repeatable workflow. It catches a moved tag, missing
parameter, incompatible unit, stale output path, or unsafe input value before a
long sweep starts.

The contract contains no MPH data and should use stable COMSOL tags rather than
local file paths. It can therefore be reviewed and committed separately from a
private model.

## Quick start

Copy [`examples/wpt_model_contract.json`](../examples/wpt_model_contract.json)
and replace its parameter names, target tag, dataset tag, table tags, and exact
column headers with values from your own model.

Validate from PowerShell:

```powershell
sim-assistant comsol-check `
  --model "C:\private\wireless-charger.mph" `
  --job job1 `
  --contract ".\model-contract.json"
```

Alternatively, set `COMSOL_CONTRACT_PATH` or choose the JSON file in the native
desktop workspace. The desktop status becomes one of:

- **Ready**: every requirement was satisfied.
- **Warning**: execution is allowed, but one or more optional or unverifiable
  requirements need review.
- **Blocked**: execution is disabled until the reported errors are fixed.

Use **View preflight** to see each finding. When no contract is selected, the
desktop app shows a warning but preserves the original unrestricted workflow.

## Schema

```json
{
  "schema_version": 1,
  "name": "wpt-2d-baseline",
  "version": "1.0.0",
  "require_runnable": true,
  "required_physics": ["Magnetic_fields"],
  "target": {"kind": "job", "tag": "job1"},
  "dataset_tag": "dset1",
  "inputs": [
    {
      "name": "gap",
      "unit": "mm",
      "min": "5[mm]",
      "max": "200[mm]",
      "required": true
    }
  ],
  "internal_parameters": ["coil_turns"],
  "outputs": [
    {
      "name": "efficiency",
      "table_tag": "tbl1",
      "column": "Efficiency (%)",
      "unit": "%",
      "required": true,
      "fresh": true
    }
  ]
}
```

### Identity and target fields

`schema_version` selects the parser format. `name` and `version` identify the
scientific interface independently of the MPH filename. `required_physics`
matches values stored in the MPH metadata. `require_runnable` rejects a model
explicitly marked as non-runnable.

`target.kind` is either `study` or `job`, and `target.tag` must match the target
selected for the run. `dataset_tag` is optional. When supplied, that dataset
must be discoverable in the MPH metadata.

### Design inputs and internal parameters

Only parameters listed in `inputs` are shown as editable model inputs in the
native application. Each input can declare a supported unit and inclusive
minimum and maximum limits. Equivalent units are accepted and compared after SI
normalization; for example, `150[mm]` and `0.15[m]` are equivalent.

Set `required` to `false` for an optional input. Required means the parameter
must exist in the model; a run may still rely on its model default. Values sent
by a run must be declared design inputs. Parameters listed in
`internal_parameters` are verified but cannot be overridden through a contracted
run.

### Required outputs

Each output binds a stable metric name to an exact saved single-row COMSOL table
and column. After a successful job-sequence run, both the generated table key and
the stable contract name are written to `result.json`. Computed formulas can use
the stable name even if the generated key is cumbersome.

The optional `unit` is checked against a trailing unit in the column header,
such as `(W)` or `[%]`. The table unit must exactly match the contract unit so a
stable metric never changes scale silently. Set `required` to `false` for a
non-blocking optional output.

`fresh` defaults to `true`. Fresh outputs require job-sequence mode because a
study-only batch command does not automatically reevaluate Derived Values. The
job sequence should include the solve, required evaluations, and any save step.

## What is checked

The connection preflight verifies:

- model runnable metadata and required physics;
- selected Study or Job Sequence and optional Dataset;
- required design and internal parameter names;
- model-default dimensions when the expression is directly parseable;
- required table columns and their declared units;
- fresh-output use of a job sequence.

Immediately before queueing and again inside the COMSOL adapter, the run values
are checked for undeclared overrides, supported units, compatible dimensions,
and inclusive limits. This second check protects CLI and queued workflows even
when the desktop interface is bypassed.

## Versioning guidance

Increase the contract version whenever a parameter role, limit, unit, target,
dataset, or output binding changes. Keep old contracts beside archived result
sets when exact reproducibility matters. Do not place local model paths,
licenses, customer identifiers, or result data in the contract.
