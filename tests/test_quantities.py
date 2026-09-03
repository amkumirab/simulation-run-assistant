import math
import unittest

from simulation_assistant.quantities import (
    common_quantity_dimension,
    numeric_quantity_value,
    parse_quantity,
    reference_unit,
)


class QuantityTests(unittest.TestCase):
    def test_normalizes_equivalent_lengths(self) -> None:
        meters = parse_quantity("0.15[m]")
        centimeters = parse_quantity("15[cm]")
        millimeters = parse_quantity("150 mm")

        self.assertIsNotNone(meters)
        self.assertEqual(meters.dimension, "length")
        self.assertAlmostEqual(meters.si_value, 0.15)
        self.assertAlmostEqual(centimeters.si_value, 0.15)
        self.assertAlmostEqual(millimeters.si_value, 0.15)

    def test_normalizes_wpt_electrical_and_angle_units(self) -> None:
        self.assertEqual(numeric_quantity_value("85[kHz]", dimension="frequency"), 85000)
        self.assertAlmostEqual(
            numeric_quantity_value("10[degree]", dimension="angle"),
            math.radians(10),
        )
        self.assertAlmostEqual(
            numeric_quantity_value("250[uH]", dimension="inductance"),
            250e-6,
        )
        self.assertAlmostEqual(
            numeric_quantity_value("12.5[mOhm]", dimension="resistance"),
            12.5e-3,
        )
        self.assertAlmostEqual(
            numeric_quantity_value("5.8e7[S/m]", dimension="conductivity"),
            5.8e7,
        )

    def test_rejects_unknown_units_expressions_and_nonfinite_values(self) -> None:
        self.assertIsNone(parse_quantity("15[parsec]"))
        self.assertIsNone(parse_quantity("1[mHz]"))
        self.assertIsNone(parse_quantity("2*pi*85[kHz]"))
        self.assertIsNone(parse_quantity(float("nan")))
        self.assertIsNone(parse_quantity("1e999[m]"))
        self.assertIsNone(parse_quantity(True))

    def test_detects_common_and_incompatible_dimensions(self) -> None:
        self.assertEqual(
            common_quantity_dimension(["0.15[m]", "15[cm]", "150[mm]"]),
            "length",
        )
        with self.assertRaisesRegex(ValueError, "incompatible"):
            common_quantity_dimension(["15[cm]", "85[kHz]"])
        with self.assertRaisesRegex(ValueError, "supported"):
            common_quantity_dimension(["15[cm]", "automatic"])

    def test_reports_reference_units(self) -> None:
        self.assertEqual(reference_unit("length"), "m")
        self.assertEqual(reference_unit("frequency"), "Hz")
        self.assertIsNone(reference_unit(None))


if __name__ == "__main__":
    unittest.main()
