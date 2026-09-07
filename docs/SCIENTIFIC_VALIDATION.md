# Scientific result validation

A completed solver process does not necessarily produce an acceptable
engineering result. Simulation Run Assistant therefore records two independent
outcomes:

- the operational job state, such as `succeeded` or `failed`;
- the scientific result state: `valid`, `warning`, or `rejected`.

A rejected result remains in the run history with its artifacts and diagnostics.
It is excluded from ranking so an unphysical value cannot become the selected
design merely because its objective is numerically large.

## Validation order

The gate runs after the adapter returns and after computed-output formulas are
evaluated. It checks:

1. Every stored metric is a finite number.
2. Required metrics are present.
3. The result pipeline is Fresh when required.
4. Configured physical bounds are satisfied.
5. Configured reciprocal quantities agree within tolerance.
6. Solver errors, convergence indicators, and warnings are classified.
7. Computed-output failures are reported as warnings.

The complete report is stored under
`result.metadata.scientific_validation` in the database and `result.json`.

## Result states

| State | Meaning | Ranking behavior |
|---|---|---|
| **Valid** | Every configured rule passed. | Included |
| **Warning** | Review is recommended, but no rejecting rule failed. | Included |
| **Rejected** | At least one error-level rule failed. | Excluded |

Solver completion is intentionally preserved. Scientific rejection does not
convert a successful COMSOL process into a failed queue job.

## Contract configuration

Add a `validation` object to a versioned model contract:

```json
{
  "validation": {
    "require_fresh_pipeline": true,
    "solver_warnings": "warning",
    "convergence_issues": "error",
    "required_metrics": ["coupling"],
    "bounds": [
      {"metric": "primary_inductance", "min": 0, "unit": "H", "exclusive_min": true},
      {"metric": "secondary_inductance", "min": 0, "unit": "H", "exclusive_min": true},
      {"metric": "coupling", "min": 0, "max": 1},
      {"metric": "efficiency", "min": 0, "max": 100, "unit": "%"},
      {"metric": "minimum_mesh_quality", "min": 0.02, "severity": "warning"}
    ],
    "reciprocity": [
      {
        "left": "mutual_inductance_12",
        "right": "mutual_inductance_21",
        "relative_tolerance": 0.02,
        "severity": "error"
      }
    ]
  }
}
```

Required contract outputs are added to `required_metrics` automatically. Bound
limits are expressed in the metric's declared output scale. For example, an
efficiency stored in percent uses limits from 0 to 100 with unit `%`.

`exclusive_min` and `exclusive_max` default to false. Rule severity defaults to
`error`; use `warning` for a review threshold that should not reject the run.

## WPT recommendations

Useful wireless-power checks include:

- positive self-inductance and resistance;
- coupling coefficient between zero and one;
- efficiency within its declared fraction or percentage scale;
- non-negative input and output power where the selected sign convention
  requires it;
- agreement between directional mutual-inductance evaluations;
- a model-specific minimum element-quality threshold;
- rejection of convergence indicators and review of every solver warning.

Mutual inductance can be negative when coil orientation or sign convention is
reversed. Do not impose a positive bound on mutual inductance unless the model's
orientation convention guarantees it.

## Solver diagnostics

The COMSOL adapter records bounded, deduplicated warning, error, and convergence
messages from `comsol.log`. It also extracts `minimum_mesh_quality` when COMSOL
reports a minimum element-quality line. The contract decides whether warnings
and convergence findings are ignored, reported, or rejecting. Detected solver
error indicators are always rejecting.

## Using the native workspace

After a run finishes, double-click it in **Run queue** and open the
**Validation** tab. The tab lists the state, checked metrics, each finding,
observed value when available, and a corrective action. Queue rows also mark
succeeded runs that have Warning or Rejected scientific states.

The **Rank results** workspace excludes Rejected runs automatically and reports
their count separately from runs rejected by user-defined ranking constraints.
Ranked rows and exported ranking CSV files retain the validation state of every
included result.
Older runs created before validation reports existed remain rankable for backward
compatibility; rerun them when validated comparison is required.

## Limits

- Validation confirms configured invariants, not full physical correctness.
- Bounds must match the numerical scale emitted by their output table.
- Reciprocity requires two separately evaluated directional quantities.
- Mesh-quality thresholds are model and element-order dependent; select them
  from convergence evidence rather than using a universal value.
- Custom solver messages may not match the standard diagnostic patterns and
  should still be reviewed in the full log.
