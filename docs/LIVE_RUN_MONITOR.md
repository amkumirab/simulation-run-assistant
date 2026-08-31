# Live COMSOL Run Monitor

The live monitor makes a long COMSOL batch solve observable without opening the
solver log manually. It reads a bounded tail of the current job's `comsol.log`
and never loads the entire file into memory.

## Native desktop workflow

1. Start the application with `sim-assistant desktop`.
2. Check the COMSOL connection and start or queue a run.
3. Open the **Runs** tab. Active COMSOL rows show their latest percentage and
   solver stage under **Live progress**.
4. Double-click the active row and select **Live monitor**.
5. Use **Open live log** to open the source log in the system application, or
   **Stop job** to request a controlled solver shutdown.

The monitor refreshes once per second while the job is active. The main queue
also refreshes jobs started by another local worker.

## Local dashboard workflow

Start the dashboard with `sim-assistant serve`, open the displayed localhost
address, and select an active run. The details dialog updates on every dashboard
refresh and includes the recent COMSOL log output. The queue shows a compact
progress summary for each active run.

## Progress interpretation

- **Percentage** is read from COMSOL `Current Progress` messages. It describes
  the current solver activity and may restart when COMSOL enters another stage.
- **Stage** is the latest solver, loading, or saving label found in the log.
- **Elapsed** is wall-clock time since the queue marked the attempt as running.
- **Last activity** is time since the log file was last modified.
- **No recent activity** appears after five minutes without a log update. Some
  expensive solver operations can be quiet for several minutes, so the warning
  does not stop or fail the run automatically.

Before each adapter run, the runner records `artifacts/job-NNNNNN` as the active
work directory. This keeps a failed attempt's `comsol.log` available for
diagnosis. Requeueing a failed or stopped job clears the old directory reference;
the next attempt receives fresh progress information.

## Limits and safety

The monitor reads at most 64 KiB and displays the most recent 80 lines. Invalid
UTF-8 bytes are replaced and terminal control characters are removed before the
text reaches either interface. Progress inspection is read-only and does not
change the model, solver process, or result files.
