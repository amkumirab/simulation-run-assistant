# Mesh convergence studies

The native desktop workspace can run an ordered set of mesh refinements for an
accepted COMSOL design and determine whether selected physical outputs have
stabilized. The workflow keeps numerical accuracy separate from solver success
and scientific result validation.

## Model preparation

The COMSOL model must expose a global parameter that controls mesh size or a
dimensionless mesh scale. Add that parameter to the model contract as a design
input. The selected Job Sequence must use it when rebuilding the mesh before
each solve.

For example, a model may expose `mesh_scale` and use it in its mesh-size
expressions:

```text
Coarse=1.5, Normal=1.0, Fine=0.7, Extra fine=0.5
```

The meaning and direction of the values belong to the COMSOL model. Enter the
levels in the desktop workspace from coarse to fine. The assistant does not
modify mesh features inside an MPH file.

The Job Sequence should perform these steps for every level:

```text
Apply parameters
Rebuild geometry when required
Rebuild mesh from the mesh-control parameter
Solve all required excitations
Evaluate Derived Values
Update the contracted result table
Save the output model
```

Use **Check connection** before opening the study. The workspace requires:

- an accepted model contract;
- a COMSOL Job Sequence rather than a Study-only target;
- a Fresh result pipeline;
- at least one completed COMSOL Job with Valid or Warning scientific status.

## Running a study

1. Open the **Runs** tab and select **Mesh study**.
2. Choose the source batch and an accepted base Job.
3. Select the model input that controls the mesh.
4. Enter at least two unique `label=value` levels from coarse to fine.
5. Select one to three physical outputs and set the maximum allowed relative
   change for each output.
6. Select **Refresh** to review the plan.
7. Choose **Queue remaining** or **Run remaining**.

All non-mesh parameters are copied from the base Job. The workspace uses the
base Job's computed-output formulas and the currently connected model, contract,
Job Sequence, and plot selection. Existing accepted or active simulation states
are reused by their reproducible run signatures. Missing, failed, rejected, and
unvalidated states can be submitted again.

## Convergence calculation

For every selected metric, the relative change between a coarse result `c` and
the next finer result `f` is:

```text
abs(f - c) / max(abs(f), 1e-30) * 100
```

A transition is Converged only when every selected metric is numeric and within
its configured tolerance. It is Not converged when at least one metric exceeds
its tolerance. Missing outputs or an unaccepted adjacent result make the
transition Incomplete.

The recommended level is the lightest level for which that transition and every
remaining refinement through the finest level pass. A single passing transition
followed by an unstable finer result is therefore never recommended.

## Cost evidence

When COMSOL reports them, the study records:

- `degrees_of_freedom`;
- `comsol_duration_seconds`, with reported COMSOL durations as fallbacks;
- every selected physical output;
- the relative change from the preceding mesh level.

The native chart shows the first selected output's relative change against
degrees of freedom. If degrees of freedom are unavailable, it uses the ordered
mesh level instead. The tolerance is drawn as a dashed line.

## Reports

The workspace exports:

- CSV data for further analysis;
- a self-contained HTML study report.

Reports contain only portable Job identifiers, mesh settings, convergence
results, outputs, and cost metrics. Local model and artifact paths are not
included.

## Interpretation

A Converged result shows numerical stability only for the selected outputs and
tested levels. It does not replace experimental validation, reference-model
comparison, material-property checks, boundary-condition review, or the
scientific validation gate.
