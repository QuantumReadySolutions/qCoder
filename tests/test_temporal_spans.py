import unittest

from qcoder.engines.feature_extraction.ir import CircuitIR, Operation
from qcoder.engines.feature_extraction.reps.spans import compute_span_stats


class TestTemporalSpans(unittest.TestCase):
    def test_early_late_long_range_and_avg(self):
        # Gate-op order (eligible gate ops only) split into first half / second half.
        # Ops:
        #   early half: cx q0,q1 (span 1), cx q0,q3 (span 3)
        #   late half : h q0 (ignored by 2Q span), cx q1,q2 (span 1), cx q0,q2 (span 2)
        ops = (
            Operation("cx", (0, 1), (), 0, 0),
            Operation("cx", (0, 3), (), 1, 1),
            Operation("h", (0,), (), 2, 2),
            Operation("cx", (1, 2), (), 3, 3),
            Operation("cx", (0, 2), (), 4, 4),
        )
        ir = CircuitIR(n_qubits=4, n_cbits=0, operations=ops, qasm_format="qasm2")
        s = compute_span_stats(ir)

        # early spans = [1,3] -> long-range ratio 1/2, avg 2.0
        self.assertAlmostEqual(s.long_range_ratio_early, 0.5)
        self.assertAlmostEqual(s.avg_span_early, 2.0)
        # late 2Q spans = [1,2] -> long-range ratio 1/2, avg 1.5
        self.assertAlmostEqual(s.long_range_ratio_late, 0.5)
        self.assertAlmostEqual(s.avg_span_late, 1.5)


if __name__ == "__main__":
    unittest.main()
