from __future__ import annotations

import importlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from qcoder.engines.feature_extraction.features.compute_v0 import compute_features_v0
from qcoder.engines.feature_extraction.parsers import parse_circuit_file


def _pennylane_installed() -> bool:
    return importlib.util.find_spec("pennylane") is not None


@unittest.skipUnless(_pennylane_installed(), "pennylane not installed")
class TestPennyLaneIntakeWithPennyLane(unittest.TestCase):
    @staticmethod
    def _bell_qnode():
        import pennylane as qml

        # Analytic device (no device-level shots) avoids shots-on-device deprecation warnings.
        dev = qml.device("default.qubit", wires=2)

        @qml.qnode(dev)
        def circuit():
            qml.Hadamard(wires=0)
            qml.CNOT(wires=[0, 1])
            return qml.expval(qml.PauliZ(0))

        return circuit

    def _qasm_from_qnode(self, qnode) -> str:
        import pennylane as qml

        exported = qml.to_openqasm(qnode, measure_all=True)
        return exported() if callable(exported) else exported

    def test_bell_features_match_tempfile_from_qasm_export(self) -> None:
        from qcoder.engines.feature_extraction.adapters.pennylane_intake import (
            extract_features_from_pennylane_circuit,
        )

        qnode = self._bell_qnode()
        text = self._qasm_from_qnode(qnode)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".qasm", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            path = f.name
        try:
            ir_file = parse_circuit_file(path)
            fv_file = compute_features_v0(ir_file)
        finally:
            Path(path).unlink(missing_ok=True)

        fv_adapt = extract_features_from_pennylane_circuit(qnode)
        self.assertEqual(fv_adapt.schema_version, fv_file.schema_version)
        self.assertEqual(fv_adapt.feature_names, fv_file.feature_names)
        self.assertEqual(fv_adapt.features, fv_file.features)

    def test_circuit_ir_matches_parse_qasm2_text_of_export(self) -> None:
        from qcoder.engines.feature_extraction.adapters.pennylane_intake import (
            circuit_ir_from_pennylane,
        )
        from qcoder.engines.feature_extraction.qasm2_regex_parser import parse_qasm2_text

        qnode = self._bell_qnode()
        ir_adapt = circuit_ir_from_pennylane(qnode)
        ir_ref = parse_qasm2_text(self._qasm_from_qnode(qnode))
        self.assertEqual(ir_adapt, ir_ref)

    def test_wrong_type_raises_type_error(self) -> None:
        from qcoder.engines.feature_extraction.adapters.pennylane_intake import (
            circuit_ir_from_pennylane,
        )

        with self.assertRaises(TypeError):
            circuit_ir_from_pennylane("not a circuit")


class TestPennyLaneIntakeWithoutPennyLane(unittest.TestCase):
    """Runs when pennylane is absent; skipped assertions when pennylane is present."""

    def test_adapter_module_importable_without_calling_pennylane(self) -> None:
        importlib.import_module("qcoder.engines.feature_extraction.adapters.pennylane_intake")

    def test_missing_pennylane_raises_import_error_with_hint(self) -> None:
        if _pennylane_installed():
            self.skipTest("pennylane is installed")
        from qcoder.engines.feature_extraction.adapters.pennylane_intake import (
            circuit_ir_from_pennylane,
        )

        with self.assertRaises(ImportError) as ctx:
            circuit_ir_from_pennylane(None)
        self.assertIn("pennylane", str(ctx.exception).lower())
        self.assertIn("pip", str(ctx.exception).lower())
        self.assertIn("qcoder[pennylane]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

