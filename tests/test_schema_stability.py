import unittest

from qcoder.engines.feature_extraction.features.schema_v0 import FEATURE_NAMES_V0, SCHEMA_V0


class TestSchemaStability(unittest.TestCase):
    def test_schema_version(self):
        self.assertEqual(SCHEMA_V0.version, "0.4.0")

    def test_no_duplicates(self):
        self.assertEqual(len(FEATURE_NAMES_V0), len(set(FEATURE_NAMES_V0)))
        self.assertEqual(len(FEATURE_NAMES_V0), 54)

    def test_expected_prefix(self):
        # Guardrail: early features should not be reordered lightly.
        self.assertEqual(FEATURE_NAMES_V0[0], "n_qubits")
        self.assertEqual(FEATURE_NAMES_V0[1], "n_cbits")
        self.assertEqual(FEATURE_NAMES_V0[2], "n_ops")

    def test_expected_suffix_append_only(self):
        self.assertEqual(
            FEATURE_NAMES_V0[-6:],
            [
                "span_long_range_ratio_early",
                "span_long_range_ratio_late",
                "span_avg_early",
                "span_avg_late",
                "ig_pair_reuse_hhi",
                "ig_pair_reuse_top1_frac",
            ],
        )


if __name__ == "__main__":
    unittest.main()
