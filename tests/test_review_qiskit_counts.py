from __future__ import annotations

import unittest

from qcoder.engines.review.qiskit_counts import normalize_qiskit_counts_payload


class TestReviewQiskitCounts(unittest.TestCase):
    def test_normalize_plain_qiskit_counts(self) -> None:
        out = normalize_qiskit_counts_payload({"00": 5, "11": 3})
        self.assertEqual(out["schema"], "qcoder.counts.v0")
        self.assertEqual(out["shots_total"], 8)
        self.assertEqual(out["counts"], {"00": 5, "11": 3})

    def test_normalize_nested_counts_key(self) -> None:
        out = normalize_qiskit_counts_payload({"counts": {"0 0": 2, "1 1": 6}})
        self.assertEqual(out["counts"], {"00": 2, "11": 6})

    def test_preserves_declared_shots_total_when_mismatched(self) -> None:
        out = normalize_qiskit_counts_payload({"counts": {"00": 5, "11": 3}, "shots_total": 20})
        self.assertEqual(out["shots_total"], 20)
        self.assertEqual(sum(out["counts"].values()), 8)

    def test_allows_mixed_bitstring_widths(self) -> None:
        out = normalize_qiskit_counts_payload({"counts": {"0": 3, "11": 5}})
        self.assertEqual(out["counts"], {"0": 3, "11": 5})
        self.assertEqual(out["shots_total"], 8)


if __name__ == "__main__":
    unittest.main()

