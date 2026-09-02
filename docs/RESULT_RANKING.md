# Constrained Result Ranking

The Rank results workspace identifies the best feasible state in a completed
parameter sweep. It uses successful jobs already stored in the local database and
does not rerun COMSOL or change result artifacts.

## Basic workflow

1. Start the native application with `sim-assistant desktop`.
2. Open **Rank results** after at least one batch has completed successfully.
3. Select one batch and a numeric result output or computed formula.
4. Choose **Maximize** or **Minimize**.
5. Optionally add one or more input or output constraints.
6. Select **Apply ranking**.
7. Double-click a row to inspect the complete job or select **Export CSV**.

The batch selector defaults to the batch containing the most recent successful
job. Only successful jobs from the selected batch are considered.

## Example

For a wireless power-transfer sweep, a useful configuration could be:

```text
Objective: coupling
Direction: Maximize
Input gap <= 15
Output losses < 10
```

Every constraint must pass for a run to qualify. The table is sorted from the
strongest objective value to the weakest. Ties are resolved by job ID so repeated
ranking produces the same order. A ranking can contain up to eight constraints.

## Values and units

Objectives must be finite numeric outputs. Constraints may use:

- **Input** fields from the parameter state recorded for each job.
- **Output** fields from COMSOL metrics or computed-output formulas.

Parameter strings such as `15[cm]` are compared using their numeric part. Enter a
threshold in the same unit and scale used by the selected model field. The ranking
engine does not convert between unit systems.

## Result totals

- **Qualified** runs contain the objective and satisfy every constraint.
- **Rejected** runs contain the required values but fail at least one constraint.
- **Missing** runs lack a numeric objective or one of the required constraint
  values.

Failed, cancelled, queued, and running jobs are not considered.

## CSV export and privacy

The exported CSV contains rank, job ID, batch, objective value, recorded inputs,
evaluated constraint values, and completion time. It deliberately excludes model,
executable, artifact, and solver-log paths. Review parameter and output names
before sharing a report when the model contract is confidential.
