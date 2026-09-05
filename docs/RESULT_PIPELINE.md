# COMSOL result-pipeline inspector

The result-pipeline inspector verifies where a saved COMSOL value comes from
before the application treats that value as a fresh simulation output. It reads
model metadata without starting a solve and reconstructs this lineage:

```text
Study -> Dataset -> Derived Values -> Table
```

When a Job Sequence is selected, it also inspects the sequence for a solve step
and a Derived Values evaluation step. This prevents a table left in an MPH file
by an older solve from being mistaken for the result of the next parameter run.

## Using the inspector

1. Start the native workspace with `sim-assistant desktop`.
2. Select the COMSOL batch executable and MPH model.
3. Select a Study or Job Sequence target.
4. Choose **Check connection**.
5. Read the **Result pipeline** state in the connection card.
6. Choose **View pipeline** for the complete feature tree and findings.

The viewer shows each discovered Study, Dataset, Derived Values feature, and
Table tag. It also includes numerical expressions, declared units, saved table
columns, and categorized Job Sequence steps when those details are available in
the MPH metadata.

The local web dashboard includes the pipeline state and the first corrective
finding in its connection summary. A completed COMSOL run also records the full
report under `metadata.result_pipeline` in its `result.json` artifact.

## Pipeline states

| State | Meaning | Recommended response |
|---|---|---|
| **Fresh** | A complete output chain and a Job Sequence with solve and evaluation steps were verified. | Run the selected Job Sequence. |
| **Stale** | The chain is linked, but only a Study is selected. Saved tables may belong to an earlier solution. | Create or select a Job Sequence that solves and reevaluates Derived Values. |
| **Incomplete** | A required link or Job Sequence step is missing or points to another Study. | Open the finding and repair the named feature or step in COMSOL. |
| **Unknown** | The selected target or its sequence steps cannot be verified from model metadata. | Inspect the target in COMSOL and select a discoverable Study or Job Sequence. |

The inspector is intentionally conservative. It reports **Fresh** only when the
complete route and required Job Sequence operations can be verified. It never
infers freshness merely because a table currently contains numeric data.

## Correct Job Sequence structure

For results that must change with every parameter state, create a COMSOL Job
Sequence containing at least:

1. A Solution step for the required Study.
2. An **Evaluate Derived Values** step for the required numerical features.
3. A Save step if the solved model must be preserved as `output.mph`.

Select the Job Sequence tag in the native workspace and check the connection
again. The viewer should show the solve and evaluation categories and report a
Fresh state when all feature links are complete.

## Common findings

- **Incomplete result chain:** a Dataset, Derived Values feature, or Table
  reference is missing. Set the missing source or destination in COMSOL.
- **Study/Dataset mismatch:** the Dataset resolves to a different Study than the
  selected target. Point it to the selected Study's solution or select the
  intended Study.
- **Orphan saved table:** a saved Table contains data but no discovered Derived
  Values feature references it. Reconnect it or remove it if it is obsolete.
- **Missing solve step:** the Job Sequence evaluates or saves results without a
  discovered solve operation. Add the required Solution step.
- **Missing evaluation step:** the Job Sequence solves the model but does not
  refresh Derived Values. Add **Evaluate Derived Values** for the output nodes.
- **Invalid step order:** result evaluation occurs before the discovered solve
  step. Move **Evaluate Derived Values** after the solve step.

## Model contracts

A model contract can bind a stable output name to an exact Table and column.
Required output bindings are ready only when the selected Job Sequence pipeline
is Fresh. A present saved value is not enough. This makes contract checks protect
both interface compatibility and result freshness before a run is queued.

See [`MODEL_CONTRACT.md`](MODEL_CONTRACT.md) for the contract schema and output
binding rules.

## Limits

- MPH metadata differs between COMSOL versions and model authoring patterns.
- Custom Java or application logic may perform operations that are not visible
  as standard Job Sequence features.
- The inspector validates configuration and lineage; it does not validate the
  physical correctness, mesh convergence, or numerical accuracy of a solution.
- Source MPH files are opened read-only and are never modified by inspection.
