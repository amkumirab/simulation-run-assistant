# COMSOL integration milestone

The MVP deliberately separates orchestration from solver-specific code. A real
COMSOL integration should implement `SimulationAdapter` in
`src/simulation_assistant/adapters/comsol.py`; the queue, retry behavior,
artifacts, notifications, and dashboard do not need to change.

## Proposed contract

The adapter receives one JSON-compatible parameter dictionary and returns a
normalized `SimulationResult`:

```python
class ComsolAdapter(SimulationAdapter):
    name = "comsol"

    def run(self, parameters: dict[str, Any]) -> SimulationResult:
        # 1. Open a clean copy of the model.
        # 2. Apply parameters with units.
        # 3. Run the named study.
        # 4. Export scalar metrics and a response series.
        # 5. Close the model even if the solver fails.
        return SimulationResult(metrics=metrics, series=series, metadata=metadata)
```

## Recommended implementation path

1. Decide on one supported bridge: COMSOL Java API, LiveLink for MATLAB, or a
   controlled command-line export workflow.
2. Add configuration for the executable/model path through environment
   variables. Do not hard-code machine-specific locations.
3. Copy the source `.mph` model to a per-job working directory before applying
   parameters. This avoids concurrent writes to the original model.
4. Add explicit units to every COMSOL parameter value.
5. Export a small, documented result schema rather than committing large solver
   output files.
6. Add a fake COMSOL client to unit-test parameter mapping without a license.
7. Add one opt-in integration test that only runs when COMSOL is available.

## Suggested next commits

- `feat: add COMSOL process configuration`
- `feat: map manifest parameters to COMSOL model parameters`
- `feat: export convergence status and S-parameters`
- `test: add fake COMSOL client contract tests`
- `feat: attach result plot to Telegram notifications`
- `feat: add parallel workers with a configurable license limit`

## Repository safety

Do not publish internship models, customer geometries, proprietary materials,
license files, or confidential result data. Build the public demo from a model
you own and document its assumptions.
