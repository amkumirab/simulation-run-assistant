# Reference Model Validation

Reference validation measures how closely a fast production model agrees with a
higher-fidelity model at equivalent input states. It is intended for validating a
small set of selected designs instead of repeating an expensive reference solve for
an entire exploratory sweep.

## Prepare the two batches

Run the selected states through both models using the existing desktop workflow:

1. Keep the strongest primary candidates from ranking, Pareto, or robust analysis.
2. Pin those primary Jobs when only selected candidates should be compared.
3. Connect the higher-fidelity COMSOL model and run the same physical states under
   a different batch name.
4. Wait for both batches to finish scientific validation.

The `.mph` files and their absolute paths remain local. A reference-validation
report uses Job IDs, input states, metrics, and batch names only.

## Open reference validation

Start the native application:

```powershell
sim-assistant desktop
```

Open **Rank results**, then choose **Reference validation**. Select the fast-model
batch as **Primary batch** and the higher-fidelity run as **Reference batch**.

If the reference batch does not exist yet, enter its new name and choose
**Build campaign**. The campaign builder maps selected primary states into the
currently connected reference model. See
[`REFERENCE_VALIDATION_CAMPAIGNS.md`](REFERENCE_VALIDATION_CAMPAIGNS.md).

Enable **Pinned primary jobs only** to restrict the comparison to deliberately
preserved candidates.

## Map equivalent inputs

Use comma-separated mappings in **Input mappings**. Equal parameter names need to
be entered only once:

```text
gap, xoff, yoff, tilt
```

When the models use different names, write `primary=reference`:

```text
gap=air_gap, xoff=receiver_offset, tilt=receiver_tilt
```

Input matching is unit-aware. Values such as `100[mm]` and `10[cm]` identify the
same physical state. Categorical values must match exactly. For repeated attempts
at the same state, the greatest Job ID is used.

The summary separately reports primary or reference states that could not be
paired and Jobs with missing mapped inputs.

## Configure metric tolerances

Each metric row maps a primary output to its reference-model equivalent. Names can
be identical or different. Set one or both tolerance types:

- **Max relative error %** limits percentage error relative to the reference value;
- **Max absolute error** provides a direct limit and is useful near a zero reference.

When both limits are present, satisfying either limit accepts the metric. This
prevents an insignificant absolute difference near zero from producing a misleading
percentage failure.

A metric becomes Warning at 80 percent of its allowed error and Failed above the
limit. The overall pair uses its most severe metric state. A scientific Warning on
either source also keeps the pair in Warning for review.

## Quality gates

Both Jobs must be successful and have a Valid or Warning scientific-validation
state. A rejected, unvalidated, failed, or incomplete result cannot validate the
primary model. Missing mapped metrics are reported as unavailable instead of being
treated as zero.

## Review and preserve results

The agreement chart plots the first primary metric against its reference value.
Points on the diagonal agree exactly; color indicates the pair status.

Select a table row and use **Open primary** or **Open reference** to inspect its
complete Job details. **Save links** stores the pair status and metric comparison in
the local workspace database. Revalidating the same pair updates its existing link.

**Export CSV** writes detailed values, differences, errors, and statuses for data
processing. **Export HTML** creates a self-contained report that opens without the
application, database, internet connection, or local model paths.
