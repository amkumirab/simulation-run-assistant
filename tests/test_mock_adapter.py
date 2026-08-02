import unittest

from simulation_assistant.adapters.mock import MockElectromagneticAdapter


class MockAdapterTests(unittest.TestCase):
    def test_returns_metrics_and_frequency_series(self) -> None:
        result = MockElectromagneticAdapter().run(
            {
                "frequency_ghz": 10,
                "width_mm": 20,
                "length_mm": 50,
                "relative_permittivity": 1,
            }
        )
        self.assertIn("s21_db", result.metrics)
        self.assertEqual(len(result.series), 61)
        self.assertLess(result.series[0]["frequency_ghz"], result.series[-1]["frequency_ghz"])

    def test_rejects_non_positive_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "width_mm"):
            MockElectromagneticAdapter().run({"width_mm": 0})


if __name__ == "__main__":
    unittest.main()
