import subprocess
import sys
import time
import unittest

from simulation_assistant.adapters.base import SimulationCancelled
from simulation_assistant.process_control import run_cancellable_process


class ProcessControlTests(unittest.TestCase):
    def test_returns_completed_process_output(self) -> None:
        completed = run_cancellable_process(
            [sys.executable, "-c", "print('ready')"],
            cwd=".",
            timeout=5,
            cancel_requested=lambda: False,
            poll_interval=0.05,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "ready")

    def test_stops_only_the_spawned_process_when_requested(self) -> None:
        started = time.monotonic()

        with self.assertRaisesRegex(SimulationCancelled, "Stop requested"):
            run_cancellable_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=".",
                timeout=35,
                cancel_requested=lambda: time.monotonic() - started > 0.15,
                poll_interval=0.05,
            )

        self.assertLess(time.monotonic() - started, 5)

    def test_enforces_the_process_timeout(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            run_cancellable_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=".",
                timeout=0.15,
                cancel_requested=lambda: False,
                poll_interval=0.05,
            )


if __name__ == "__main__":
    unittest.main()
