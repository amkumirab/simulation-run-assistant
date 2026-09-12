# Pareto Analysis

Single-objective ranking identifies the strongest run for one metric. WPT design
usually requires a trade-off: stronger coupling can increase resistance, field
leakage, material use, or sensitivity to alignment. Pareto analysis keeps every
design that cannot improve one selected objective without worsening another.

## Open the workspace

Start the native application:

```powershell
sim-assistant desktop
```

Open **Rank results**, select a completed batch, and choose **Pareto analysis**.
The analysis reads normalized result metrics from the local database and never
starts COMSOL.

## Configure objectives

Select between two and four objectives in the native dialog. The calculation
engine supports up to six objectives for programmatic use. Each objective has:

- a numeric result metric or computed output;
- a **Maximize** or **Minimize** direction;
- a positive weight for compromise scoring.

A useful WPT configuration is:

```text
coupling or k        maximize
Mavg                 maximize
R1 + R2              minimize
B_leak_max           minimize
```

Create `R1 + R2` as a computed output before running the sweep when it is not
already provided by the COMSOL result table.

## Pareto fronts

Job A dominates Job B when A is no worse in every selected objective and is
strictly better in at least one. Front 1 contains every non-dominated run. After
removing Front 1, the same rule produces Front 2, then later fronts.

The result table shows:

- front number;
- Job ID;
- weighted compromise score;
- raw objective values;
- the Job IDs that dominate the run;
- the complete input state.

Front 1 is highlighted in the table and trade-off chart. Double-click a row to
open the complete run details.

## Weighted compromise score

For each objective, eligible values are normalized from zero to one in the
requested direction. The displayed score is their weighted average. A larger
score represents a stronger compromise for the selected weights.

Weights do not affect Pareto front membership. They only order designs within
the same front, so changing a preference cannot incorrectly turn a dominated
design into a Pareto-optimal one.

## Feasibility and result quality

Enable **Use constraints configured in Rank results** to apply the existing
input and output limits before computing fronts. The Pareto dialog and ranking
workspace must select the same batch. Dimensional input thresholds keep their
unit-aware comparison behavior.

Only successful runs with every selected objective and a Valid or Warning
scientific-validation state are eligible. Rejected and unvalidated results are
excluded. The summary separately reports constraint rejection, validation
rejection, unvalidated runs, and missing objective values.

## Preserve and export designs

Select a result and choose **Pin / unpin** to protect its artifact directory from
retention cleanup. This is useful for keeping several trade-off candidates for
later reference-model validation.

**Export CSV** includes every eligible row, objective and normalized value,
constraints, input parameters, front number, score, and dominance Job IDs.
**Export HTML** creates a self-contained result table that can be opened without
the database, local server, or internet connection. Reports do not contain local
model or artifact paths.
