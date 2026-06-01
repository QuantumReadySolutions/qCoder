from __future__ import annotations

import unittest

from qcoder.engines.review.counts_v0 import normalize_counts_v0


class TestReviewCountsV0(unittest.TestCase):
    def test_normalize_counts_v0(self) -> None:
        payload = {"schema": "qcoder.counts.v0", "counts": {"00": 3, "11": 1}}
        out = normalize_counts_v0(payload)
        self.assertEqual(out["schema"], "qcoder.counts.v0")
        self.assertEqual(out["shots_total"], 4)
        self.assertEqual(out["counts"]["00"], 3)
        self.assertEqual(out["counts"]["11"], 1)

    def test_reject_invalid_bitstring(self) -> None:
        with self.assertRaises(ValueError):
            normalize_counts_v0({"counts": {"0a": 1}})

    def test_preserves_declared_shots_total_when_mismatched(self) -> None:
        payload = {"schema": "qcoder.counts.v0", "counts": {"00": 3, "11": 1}, "shots_total": 100}
        out = normalize_counts_v0(payload)
        self.assertEqual(out["shots_total"], 100)
        self.assertEqual(sum(out["counts"].values()), 4)


if __name__ == "__main__":
    unittest.main()

