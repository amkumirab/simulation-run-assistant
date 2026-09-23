# Reference Validation Campaigns

The campaign builder converts selected primary-model Jobs into the smallest
required higher-fidelity COMSOL campaign. It removes the manual work of copying
parameter states, finding duplicates, linking Jobs, and returning to validation
after the reference solves finish.

## Prepare the primary candidates

Complete the primary sweep and scientific validation first. Use ranking, Pareto,
or robust analysis to identify the designs worth validating. Pin those Jobs when
the reference campaign should include only the preserved candidates.

## Connect the reference model

Before opening the builder:

1. Select the higher-fidelity `.mph` model in the native workspace.
2. Select its versioned model contract.
3. Choose a COMSOL Job Sequence that solves and evaluates fresh outputs.
4. Run **Check connection** and resolve every blocked contract or pipeline finding.
5. Set fixed reference-model inputs and computed outputs in Run setup.

The builder requires an accepted contract and a Fresh Job Sequence pipeline. It
does not start a reference solve when either safety check is missing.

Production and reference models remain local and are never copied into reports or
the source repository.

## Build the campaign

Open **Rank results**, choose **Reference validation**, then:

1. Select the primary batch.
2. Enter an existing or new reference batch name.
3. Enable **Pinned primary jobs only** when appropriate.
4. Configure `primary=reference` input mappings.
5. Choose **Build campaign**.

The builder begins with the connected reference model's current input values and
replaces mapped values from each selected primary Job. Unmapped inputs therefore
remain fixed at the values visible in Run setup.

For example:

```text
gap=air_gap, xoff=receiver_offset, tilt=receiver_tilt
```

Every generated state passes through the reference model contract before it can be
queued.

## Preview and estimates

The campaign table shows:

- the source primary Job;
- the complete reference input state;
- the current campaign status;
- the linked reference Job when one exists.

Recent successful COMSOL runs provide approximate sequential runtime and
output-model storage estimates. An estimate is omitted when no suitable history is
available rather than presenting an invented value.

## Duplicate and resume behavior

Each state uses the same safe run identity as normal preflight checks. The identity
includes reference-model context, parameters, formulas, contract, and execution
target.

Within the selected reference batch:

- accepted states are reused;
- queued and running states are left unchanged;
- missing, failed, rejected, and unvalidated states are eligible for resubmission;
- repeated primary attempts that produce the same reference state collapse to the
  newest primary Job.

This makes **Refresh** and repeated campaign submission safe after interruption.

## Queue or run

Choose **Queue only** to create the missing reference Jobs without starting COMSOL.
Choose **Run campaign** to process the new Jobs sequentially immediately.

As each Job is queued, its relationship to the primary Job is stored in the local
database. After an immediate campaign finishes, Reference validation refreshes and
saves any comparisons that have valid metric mappings and tolerances.

Queued campaigns can be run later from the normal queue controls. Return to
Reference validation after completion to review and save the final comparison.

Double-click an existing reference Job in the campaign table to open its details.
CSV and HTML exports contain the plan, statuses, Job IDs, and reference inputs but
never absolute model or artifact paths.
