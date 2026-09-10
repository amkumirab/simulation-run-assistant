# Artifact Retention

COMSOL runs can consume substantial disk space because every job receives its
own working directory and may contain a copied `output.mph` model. The native
artifact storage manager provides an explicit, reviewable way to reclaim that
space while preserving the simulation history stored in SQLite.

## Open the manager

Start the native application:

```powershell
sim-assistant desktop
```

Open the **Runs** tab and choose **Storage manager**. The first scan inventories
job folders directly inside the configured artifact directory. It does not
change files.

## Retention controls

- **Keep days** removes eligible completed artifacts older than the specified
  number of days. Clear the field to disable the age rule.
- **Latest per batch** preserves the newest number of jobs in each batch and
  makes older eligible artifacts reclaimable. Clear the field to disable this
  rule; use `0` to keep no jobs through this rule.
- **Maximum total GB** adds oldest eligible artifacts to the plan until the
  projected storage is within the limit. Clear the field to disable the limit.
- **Remove output.mph from eligible runs** removes only copied output models
  from otherwise retained job folders. Smaller result files, plots, and logs
  remain available.
- **Include orphan job folders** includes safely named `job-*` folders that are
  not referenced by the database. This is disabled by default.

Rules are combined. A completed artifact becomes reclaimable when an enabled
age or per-batch rule selects it, or when it must be removed to meet the size
limit.

## Automatic protection

The manager never plans removal for:

- queued or running jobs;
- runs pinned in the storage manager;
- the best result in the current ranking view;
- the latest successful, scientifically accepted result in each batch;
- artifact paths outside the configured artifact root;
- directories referenced by more than one job.

Use **Pin / unpin selected** to keep an important run independent of policy
changes. Pins are stored in the local database.

## Preview and apply

Choose **Scan** after changing a policy. The table explains whether every item
will be kept, protected, considered missing, or removed. The summary shows the
current stored size, action count, and maximum reclaimable size.

Choose **Apply cleanup** only after reviewing the table. A second confirmation
shows the planned action count and size. Immediately before each removal, the
application checks that the path is still safe, the job is still completed and
unpinned, the database path is unchanged, and the item size still matches the
preview. Changed items are skipped instead of removed.

Whole-folder cleanup clears only the job's artifact path. The job status,
parameters, results, validation, and metrics remain in SQLite. Every completed
cleanup action is recorded in the history table with its time, action, item,
and reclaimed size.

## Recommended production workflow

1. Finish and validate a sweep.
2. Rank the results and pin any additional reference runs worth preserving.
3. Open the storage manager and scan with conservative limits.
4. Review every planned action and the protected reference runs.
5. Apply the cleanup and confirm the reclaimed size in cleanup history.

Keep independent backups of irreplaceable MPH models. Artifact retention is a
local storage tool, not a backup system.
