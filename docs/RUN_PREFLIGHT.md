# Duplicate-Run Preflight

COMSOL sweeps can take hours, so the native desktop application checks whether a
requested state is already covered before adding it to the queue.

## Review a plan

Connect and validate a COMSOL model, configure fixed or sweep inputs, and choose
**Review plan**. The summary reports:

- requested states;
- new jobs;
- reusable successful results;
- states already queued or running;
- repeated states inside the current request; and
- estimated sequential time for new jobs only.

The same check runs automatically when **Run now** or **Queue only** is selected.
When duplicates exist, the confirmation provides three choices:

- **Yes** skips duplicates and keeps existing successful results available;
- **No** creates every requested state again; and
- **Cancel** returns to the workspace without changing the queue.

If every state is already covered, no new job is created. Reusable and scheduled
job IDs appear in the preflight summary and remain available in the **Runs** tab.

## Run identity

Each signed job uses a SHA-256 digest built from:

- adapter name;
- model filename, byte size, and nanosecond modification time;
- Study or Job Sequence target;
- selected Plot Group tags;
- the complete parameter state; and
- computed-output formula names and expressions.

Changing any of these values produces a different signature. Core count and
timeout are excluded because they control execution rather than the requested
simulation result.

## Privacy

Run identity stores the model filename and file metadata but never its directory
or absolute path. The combined identity is hashed; job details and result JSON
artifacts contain only the path-free context, the normal recorded inputs and
formulas, and the final digest.

Workspace profiles remain local and continue to hold the model path separately.
Repository exclusions for profiles, databases, MPH models, and run artifacts are
unchanged.

## Existing jobs

Jobs created before version 0.13.0 do not have a run signature and are ignored by
duplicate matching. They remain fully visible and usable. New desktop and local
dashboard submissions record signatures automatically, so the matching history
builds without modifying previous results.

Failed and cancelled jobs do not block a new state. A matching queued or running
job takes priority over an older successful match because the state is already
scheduled for processing.

Matching is intentionally exact and conservative. Differences in parameter text,
formula text, model metadata, target, or selected plots produce a new job instead
of risking reuse of a result from a different request.
