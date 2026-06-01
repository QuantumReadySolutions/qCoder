import unittest

from qcoder.engines.feature_extraction.ir import CircuitIR, Operation
from qcoder.engines.feature_extraction.reps.entangling_layers import compute_entangling_layer_stats


def _op(
    name: str,
    qubits: tuple[int, ...],
    params: tuple[str, ...] = (),
    line: int = 0,
    idx: int = 0,
) -> Operation:
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


class TestEntanglingLayers(unittest.TestCase):
    def test_no_entangling_ops(self):
        # A) Only 1Q gates
        ir = CircuitIR(
            n_qubits=2,
            n_cbits=0,
            operations=(
                _op("h", (0,), (), 0, 0),
                _op("rz", (0,), ("0",), 1, 1),
                _op("rx", (1,), ("pi/2",), 2, 2),
            ),
            qasm_format="qasm2",
        )
        s = compute_entangling_layer_stats(ir)
        self.assertEqual(s.entangling_depth, 0)
        self.assertEqual(s.n_entangling_layers, 0)
        self.assertAlmostEqual(s.avg_2q_per_entangling_layer, 0.0)
        self.assertEqual(s.max_2q_per_entangling_layer, 0)

    def test_bell(self):
        # B) 2 qubits: h q0 (ignored for entangling), cx q0,q1
        ir = CircuitIR(
            n_qubits=2,
            n_cbits=0,
            operations=(
                _op("h", (0,), (), 0, 0),
                _op("cx", (0, 1), (), 1, 1),
            ),
            qasm_format="qasm2",
        )
        s = compute_entangling_layer_stats(ir)
        self.assertEqual(s.entangling_depth, 1)
        self.assertEqual(s.n_entangling_layers, 1)
        self.assertAlmostEqual(s.avg_2q_per_entangling_layer, 1.0)
        self.assertEqual(s.max_2q_per_entangling_layer, 1)

    def test_parallel_then_dependent(self):
        # C) 4 qubits: cx q0,q1 and cx q2,q3 (same layer), then cx q1,q2 (next layer)
        ir = CircuitIR(
            n_qubits=4,
            n_cbits=0,
            operations=(
                _op("cx", (0, 1), (), 0, 0),
                _op("cx", (2, 3), (), 1, 1),
                _op("cx", (1, 2), (), 2, 2),
            ),
            qasm_format="qasm2",
        )
        s = compute_entangling_layer_stats(ir)
        self.assertEqual(s.entangling_depth, 2)
        self.assertEqual(s.n_entangling_layers, 2)
        self.assertAlmostEqual(s.avg_2q_per_entangling_layer, 3 / 2)
        self.assertEqual(s.max_2q_per_entangling_layer, 2)


if __name__ == "__main__":
    unittest.main()
