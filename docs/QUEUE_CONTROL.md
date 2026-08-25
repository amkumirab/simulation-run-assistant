# Queue Control and Interrupted-Run Recovery

Simulation Run Assistant stores queue controls in the same SQLite database as
the jobs. This keeps the queue state consistent across the desktop application,
CLI, local dashboard, and Telegram worker.

## Pause and resume

Use **Pause queue** in the desktop **Runs** tab or run:

```powershell
sim-assistant pause
sim-assistant resume
```

Pausing prevents new jobs from being claimed. A simulation that is already
running is not terminated and can finish normally. The pause state persists
after the application closes and is checked inside the same database transaction
that claims a queued job.

Jobs can still be added while the queue is paused. Use this to prepare a sweep,
review its inputs, and resume processing when the workstation is ready.

## Cancel a queued job

Select a queued job in the desktop **Runs** tab and choose **Cancel selected**, or
run:

```powershell
sim-assistant cancel JOB_ID
```

Cancellation is only allowed before execution. The job remains in history with
the `cancelled` status, its cancellation time, and its original parameters. Open
the job and choose **Requeue**, or use `sim-assistant retry JOB_ID`, to return it
to the queue later.

## Recover interrupted jobs

A forced shutdown can leave a claimed job with the `running` status even though
its worker process no longer exists. The desktop application shows the number of
running jobs and enables **Recover interrupted** when it is not processing a
local simulation.

Before recovery, confirm that no CLI, dashboard, Telegram, or other desktop
worker is still active. The application intentionally does not recover jobs
automatically because another process may be running them legitimately.

The desktop recovery dialog provides three choices:

- **Yes** returns all interrupted jobs to the queue.
- **No** marks them as failed and records the recovery reason.
- **Cancel** leaves every running job unchanged.

The equivalent CLI commands are:

```powershell
sim-assistant recover
sim-assistant recover --fail
```

Requeueing preserves the attempt count so the run history remains accurate.
Both recovery paths keep existing job records instead of deleting them.

## Active COMSOL runs

Pause and cancel controls do not terminate an active COMSOL process. Avoid using
interrupted-run recovery while COMSOL or another queue worker is still running.
If an active process must be stopped, close it using COMSOL or the operating
system first, verify that it has exited, and then use the recovery workflow.
