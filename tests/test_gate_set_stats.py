import unittest

from qcoder.engines.feature_extraction.ir import CircuitIR, Operation
from qcoder.engines.feature_extraction.reps.gate_set_stats import compute_gate_set_stats


def _op(name: str, qubits: tuple[int, ...], params: tuple[str, ...] = (), line: int = 0, idx: int = 0) -> Operation:
    return Operation(
        name=name,
        qubits=qubits,
        params=params,
        line_index=line,
        op_index=idx,
        is_measure=False,
        is_barrier=False,
        is_reset=False,
        is_custom=False,
    )


class TestGateSetStats(unittest.TestCase):
    def test_pure_diagonal(self):
        # A) Pure diagonal: rz(pi/4) q[0]; cz q[0],q[1];
        ir = CircuitIR(
            n_qubits=2,
            n_cbits=0,
            operations=(
                _op("rz", (0,), ("pi/4",), 0, 0),
                _op("cz", (0, 1), (), 1, 1),
            ),
            qasm_format="qasm2",
        )
        s = compute_gate_set_stats(ir)
        self.assertEqual(s.is_certified_diagonal_only, 1)
        self.assertAlmostEqual(s.diagonal_gate_fraction, 1.0)
        self.assertEqual(s.n_basis_change_ops, 0)

    def test_basis_change_coverage(self):
        # B) 3 qubits: h on q0, rx(pi/2) on q2, cx q0,q1
        ir = CircuitIR(
            n_qubits=3,
            n_cbits=0,
            operations=(
                _op("h", (0,), (), 0, 0),
                _op("rx", (2,), ("pi/2",), 1, 1),
                _op("cx", (0, 1), (), 2, 2),
            ),
            qasm_format="qasm2",
        )
        s = compute_gate_set_stats(ir)
        self.assertEqual(s.n_basis_change_ops, 2)
        self.assertAlmostEqual(s.basis_change_qubit_coverage, 2 / 3)

    def test_angle_genericity(self):
        # C) rz(pi/2), rz(0.123), rz(pi/2) => distinct: pi/2, 0.123 => ratio 1/2
        ir = CircuitIR(
            n_qubits=1,
            n_cbits=0,
            operations=(
                _op("rz", (0,), ("pi/2",), 0, 0),
                _op("rz", (0,), ("0.123",), 1, 1),
                _op("rz", (0,), ("pi/2",), 2, 2),
            ),
            qasm_format="qasm2",
        )
        s = compute_gate_set_stats(ir)
        self.assertEqual(s.n_distinct_angles, 2)
        self.assertAlmostEqual(s.angle_genericity_ratio, 0.5)


if __name__ == "__main__":
    unittest.main()
