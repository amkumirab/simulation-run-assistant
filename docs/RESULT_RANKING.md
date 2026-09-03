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

Dimensional input values are converted to their SI reference unit before
comparison. For example, `0.15[m]`, `15[cm]`, and `150[mm]` are equal. A
dimensional input constraint must include an explicit compatible unit. A length
field therefore accepts `15[cm]` or `0.15[m]`, but rejects a bare `15` or a
frequency threshold.

Output metrics do not yet carry separate unit metadata. Until a model contract
defines those units, output thresholds use the numeric scale stored under the
metric name and must not include a physical unit.

## Result totals

- **Qualified** runs contain the objective and satisfy every constraint.
- **Rejected** runs contain the required values but fail at least one constraint.
- **Missing** runs lack a numeric objective or one of the required constraint
  values.

Failed, cancelled, queued, and running jobs are not considered.

## CSV export and privacy

The exported CSV contains rank, job ID, batch, objective value, recorded inputs,
evaluated constraint values, and completion time. Constraint columns include the
SI unit used for normalized values. The file deliberately excludes model,
executable, artifact, and solver-log paths. Review parameter and output names
before sharing a report when the model contract is confidential.
