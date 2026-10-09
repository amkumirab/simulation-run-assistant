import csv
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.storage import JobStore
from simulation_assistant.types import JobStatus
from simulation_assistant.sweeps import comparison_rows, write_comparison_csv
from simulation_assistant.ranking import rank_sweep_results, write_ranking_csv


class SweepWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(Path(self.temp.name) / "jobs.db")
        self.store.initialize()

    def test_old_batch_is_visible_and_best_is_not_truncated(self):
        ids = self.store.enqueue_batch("old", "mock-em", [{"gap": i} for i in range(650)])
        # Synthetic database fixtures, not solved COMSOL results.
        with self.store._connect() as connection:
            connection.execute("UPDATE jobs SET status='succeeded', result=?", ('{"metrics":{"power":1}}',))
            connection.execute('UPDATE jobs SET result=? WHERE id=?',
                               ('{"metrics":{"power":999}}', ids[0]))
        self.store.enqueue_batch("recent", "mock-em", [{"gap": i} for i in range(2000)])
        self.assertIn("old", self.store.batch_names(status=JobStatus.SUCCEEDED))
        rows = comparison_rows(self.store.iter_jobs(batch_name="old"), "power")
        self.assertEqual(len(rows), 650)
        self.assertEqual(max(rows, key=lambda row: row["value"])["job_id"], ids[0])
        ranked = rank_sweep_results(self.store.iter_jobs(batch_name="old"), "power")
        self.assertEqual(ranked.rows[0].job_id, ids[0])
        self.assertEqual(len(ranked.rows), 650)

    def test_pages_filter_before_limit_and_do_not_overlap(self):
        ids = self.store.enqueue_batch("target", "mock-em", [{"gap": i} for i in range(121)])
        self.store.enqueue_batch("other", "mock-em", [{} for _ in range(600)])
        first = self.store.page_jobs(batch_name="target", limit=100)
        second = self.store.page_jobs(batch_name="target", limit=100, offset=100)
        self.assertEqual(first.total, 121)
        self.assertEqual(len(first.items), 100)
        self.assertEqual(len(second.items), 21)
        self.assertEqual({job.id for job in (*first.items, *second.items)}, set(ids))

    def test_literal_search_status_and_summary_counts(self):
        ids = self.store.enqueue_batch("Sweep_%'", "mock-em", [{"gap": i} for i in range(5)])
        with self.store._connect() as connection:
            for job_id, status in zip(ids, JobStatus):
                connection.execute("UPDATE jobs SET status=? WHERE id=?", (status.value, job_id))
        self.store.enqueue_batch("Sweep-other", "mock-em", [{}])
        page = self.store.page_batches(search="_%'")
        self.assertEqual(page.total, 1)
        summary = page.items[0]
        self.assertEqual(summary.total, 5)
        self.assertEqual(summary.counts, {status.value: 1 for status in JobStatus})
        self.assertEqual(self.store.page_jobs(search="_%'", status=JobStatus.FAILED).total, 1)
        self.assertEqual(self.store.page_jobs(search="' OR 1=1 --").total, 0)
        self.assertEqual(self.store.page_jobs(batch_name="Sweep_%'", search='"gap": 3').total, 1)

    def test_invalid_page_bounds(self):
        for method in (self.store.page_jobs, self.store.page_batches):
            for value in (-1, 0, 501, True, 1.5):
                with self.subTest(method=method.__name__, limit=value):
                    with self.assertRaises(ValueError):
                        method(limit=value)
            for value in (-1, True, 1.5):
                with self.assertRaises(ValueError):
                    method(offset=value)
        with self.assertRaises(ValueError):
            list(self.store.iter_jobs(fetch_size=0))

    def test_empty_exact_batch_and_refresh(self):
        self.store.enqueue_batch("", "mock-em", [{}])
        self.store.enqueue_batch("named", "mock-em", [{}])
        self.assertEqual(self.store.page_jobs(batch_name="").total, 1)
        self.assertEqual(len(list(self.store.iter_jobs(batch_name=""))), 1)
        self.assertEqual(self.store.page_batches(search="missing").items, ())
        self.assertEqual(self.store.page_jobs(offset=100).items, ())
        self.store.enqueue_batch("named", "mock-em", [{}])
        self.assertEqual(self.store.page_jobs(batch_name="named").total, 2)

    def test_csv_text_is_not_executable_and_negative_numbers_stay_numeric(self):
        ids = self.store.enqueue_batch("=DANGEROUS()", "mock-em", [{"x": " @danger", "=header": "text"}])
        self.store.claim(ids[0])
        self.store.mark_succeeded(ids[0], {"metrics": {"power": -3}}, "")
        jobs = list(self.store.iter_jobs())
        for name, writer, result in (
            ("comparison", write_comparison_csv, comparison_rows(jobs, "power")),
            ("ranking", write_ranking_csv, rank_sweep_results(jobs, "power")),
        ):
            path = Path(self.temp.name) / (name + ".csv")
            writer(path, result)
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertIn("'=DANGEROUS()", rows[1])
            self.assertIn("' @danger", rows[1])
            self.assertIn("-3.0", rows[1])
            self.assertFalse(any(value.startswith("=") for value in rows[0]))

    def test_chart_overview_is_bounded_and_keeps_extremes(self):
        from simulation_assistant.sweeps import sample_comparison_points
        points = [(float(i), float(i % 100), i) for i in range(10000)]
        points[123] = (123.0, 999.0, 123)
        points[321] = (321.0, -999.0, 321)
        sample = sample_comparison_points(points)
        self.assertLessEqual(len(sample), 1000)
        self.assertEqual(sample, sorted(sample))
        for point in (points[0], points[-1], points[123], points[321]):
            self.assertIn(point, sample)
        self.assertEqual(sample_comparison_points(points[:10]), points[:10])

    def test_batch_paging_and_stream_snapshot(self):
        for number in range(35):
            self.store.enqueue_batch(f"sweep-{number}", "mock-em", [{}])
        first = self.store.page_batches()
        second = self.store.page_batches(offset=30)
        self.assertEqual((first.total, len(first.items), len(second.items)), (35, 30, 5))
        self.assertFalse({item.batch_name for item in first.items} & {item.batch_name for item in second.items})
        iterator = self.store.iter_jobs(fetch_size=1)
        first_job = next(iterator)
        self.store.enqueue_batch("new", "mock-em", [{}])
        self.assertEqual(len(list(iterator)) + 1, 35)
        self.assertEqual(first_job.batch_name, "sweep-34")
        self.assertEqual(self.store.page_jobs().total, 36)

    def test_parameter_names_cannot_overwrite_comparison_fields(self):
        job_id = self.store.enqueue_batch("batch", "mock-em", [{"metric": "input-metric", "value": 17, "job_id": 999}])[0]
        self.store.claim(job_id)
        self.store.mark_succeeded(job_id, {"metrics": {"power": 42}}, "")
        target = Path(self.temp.name) / "collision.csv"
        write_comparison_csv(target, comparison_rows(self.store.iter_jobs(), "power"))
        with target.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            row = next(reader)
            self.assertEqual(len(reader.fieldnames), len(set(reader.fieldnames)))
        self.assertEqual(row["job_id"], str(job_id))
        self.assertEqual(row["value"], "42.0")
        self.assertEqual(row["input:metric"], "input-metric")
