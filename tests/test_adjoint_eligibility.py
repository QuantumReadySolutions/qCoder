import unittest
from qcoder.core.qasm2.adjoint_eligibility import (
    AdjointEligibility,
    classify_mirror_eligibility,
    check_adjoint_eligibility,
)


class TestAdjointEligibility(unittest.TestCase):
    def test_unitary_no_measure_supported(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncx q[0], q[1];\nu1(0.5) q[0];\n"
        e = check_adjoint_eligibility(qasm, include_mirror_qasm=True)
        self.assertTrue(e.adjoint_supported)
        self.assertEqual(e.adjoint_reason, "")
        self.assertIsNotNone(e.mirror_qasm)
        self.assertIn("u1(-0.5)", e.mirror_qasm)

    def test_terminal_measurement_block_is_supported(self):
        qasm = "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];\n"
        e = check_adjoint_eligibility(qasm)
        self.assertTrue(e.adjoint_supported)
        self.assertEqual(e.adjoint_reason, "")
        self.assertIsNotNone(e.mirror_qasm)

    def test_reset_not_supported(self):
        qasm = "OPENQASM 2.0;\nqreg q[1];\nreset q[0];\n"
        cls, reason = classify_mirror_eligibility(qasm)
        self.assertEqual(cls, "non_unitary")
        self.assertIn("reset", reason)
        e = check_adjoint_eligibility(qasm)
        self.assertFalse(e.adjoint_supported)
        self.assertIn("reset", e.adjoint_reason)

    def test_mid_circuit_measure_not_supported(self):
        qasm = (
            "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\n"
            "h q[0];\nmeasure q[0] -> c[0];\nh q[0];\n"
        )
        cls, reason = classify_mirror_eligibility(qasm)
        self.assertEqual(cls, "non_unitary")
        self.assertIn("measurement before terminal", reason)
        e = check_adjoint_eligibility(qasm)
        self.assertFalse(e.adjoint_supported)
        self.assertIn("measurement before terminal", e.adjoint_reason)

    def test_unsupported_include_reason(self):
        qasm = 'OPENQASM 2.0;\ninclude "stdgates.inc";\nqreg q[1];\nh q[0];\n'
        e = check_adjoint_eligibility(qasm)
        self.assertFalse(e.adjoint_supported)
        self.assertTrue(len(e.adjoint_reason) > 0)
        self.assertIsNone(e.mirror_qasm)

    def test_to_metadata_dict(self):
        e = AdjointEligibility(adjoint_supported=True, adjoint_reason="")
        d = e.to_metadata_dict()
        self.assertEqual(d["adjoint_supported"], True)
        self.assertEqual(d["adjoint_reason"], "")


if __name__ == "__main__":
    unittest.main()
