# Robust Misalignment Analysis

A design that performs well only in perfect alignment may be a poor wireless-power
design. Robust analysis compares each fixed design over the same offset and tilt
conditions, then ranks complete groups by their worst-case, average, or balanced
performance.

## Open the workspace

Start the native application:

```powershell
sim-assistant desktop
```

Open **Rank results** and choose **Robust analysis**. Select the completed batch
that contains the alignment sweep. The analysis reads existing local results and
does not start COMSOL.

## Define conditions and designs

The default condition fields are:

```text
xoff, yoff, tilt
```

These values describe the misalignment state. Every other input is treated as a
fixed design input. For the standard 36-state baseline campaign, `gap` therefore
creates three design groups and each group contains 12 offset/tilt states.

Condition values are unit-aware. For example, `50[mm]` and `5[cm]` identify the
same state. If a state has several attempts, the run with the greatest Job ID is
used so that a successful retry can replace an older rejected result.

Edit **Condition fields** when a custom sweep uses different names. All listed
fields must exist in every analyzed job.

## Choose a metric and ranking mode

Select a numeric result metric or computed output and its direction:

- **Maximize** for coupling, mutual inductance, efficiency, or transferred power;
- **Minimize** for resistance, leakage field, loss, temperature, or error.

Three ranking modes are available:

- **Worst case** compares the weakest state of each complete design;
- **Average** compares mean performance over all conditions;
- **Balanced** gives equal influence to normalized worst-case and mean performance.

The calculation engine also accepts up to six weighted objectives and assigns
group-level Pareto fronts from their worst-case values. CSV and HTML reports expose
these aggregate values for later trade-off review.

## Coverage and quality gates

The expected condition set is the Cartesian product of the selected batch's
observed condition values. A design receives a rank only when every expected state:

- has a successful run;
- contains the selected metric;
- has a Valid or Warning scientific-validation result.

Missing, failed, unvalidated, and scientifically rejected states keep the entire
design group out of the ranking. The group remains in the table with its coverage
and exclusion reason, preventing a partially tested design from appearing better
than a fully tested one.

## Interpret the results

For each design, the table displays:

- robust rank and normalized score;
- covered and expected condition counts;
- worst-case and mean metric values;
- percentage change from the aligned state where every condition value is zero;
- the fixed input values that define the design.

Select a row to view the `xoff` by `tilt` heatmap. Use **Group jobs** to inspect
every contributing run and double-click a Job ID for its complete result details.

Use **Pin / unpin group** to protect every contributing artifact from retention
cleanup. **Export CSV** produces a machine-readable aggregate table, while
**Export HTML** creates a self-contained report without local model or artifact
paths.
