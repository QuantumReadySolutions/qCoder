from __future__ import annotations

import importlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from qcoder.engines.feature_extraction.features.compute_v0 import compute_features_v0
from qcoder.engines.feature_extraction.parsers import parse_circuit_file


def _cirq_installed() -> bool:
    return importlib.util.find_spec("cirq") is not None


@unittest.skipUnless(_cirq_installed(), "cirq not installed")
class TestCirqIntakeWithCirq(unittest.TestCase):
    def test_bell_features_match_tempfile_from_qasm_export(self) -> None:
        import cirq

        from qcoder.engines.feature_extraction.adapters.cirq_intake import (
            extract_features_from_cirq_circuit,
        )

        q0, q1 = cirq.LineQubit.range(2)
        circuit = cirq.Circuit(
            cirq.H(q0),
            cirq.CNOT(q0, q1),
            cirq.measure(q0, q1, key="m"),
        )
        text = cirq.qasm(circuit)
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

        fv_adapt = extract_features_from_cirq_circuit(circuit)
        self.assertEqual(fv_adapt.schema_version, fv_file.schema_version)
        self.assertEqual(fv_adapt.feature_names, fv_file.feature_names)
        self.assertEqual(fv_adapt.features, fv_file.features)

    def test_circuit_ir_matches_parse_qasm2_text_of_export(self) -> None:
        import cirq

        from qcoder.engines.feature_extraction.adapters.cirq_intake import (
            circuit_ir_from_cirq,
        )
        from qcoder.engines.feature_extraction.qasm2_regex_parser import parse_qasm2_text

        q0, q1 = cirq.LineQubit.range(2)
        circuit = cirq.Circuit(
            cirq.H(q0),
            cirq.CNOT(q0, q1),
            cirq.measure(q0, q1, key="m"),
        )
        ir_adapt = circuit_ir_from_cirq(circuit)
        ir_ref = parse_qasm2_text(cirq.qasm(circuit))
        self.assertEqual(ir_adapt, ir_ref)

    def test_wrong_type_raises_type_error(self) -> None:
        from qcoder.engines.feature_extraction.adapters.cirq_intake import (
            circuit_ir_from_cirq,
        )

        with self.assertRaises(TypeError):
            circuit_ir_from_cirq("not a circuit")


class TestCirqIntakeWithoutCirq(unittest.TestCase):
    """Runs when cirq is absent; skipped assertions when cirq is present."""

    def test_adapter_module_importable_without_calling_cirq(self) -> None:
        importlib.import_module("qcoder.engines.feature_extraction.adapters.cirq_intake")

    def test_missing_cirq_raises_import_error_with_hint(self) -> None:
        if _cirq_installed():
            self.skipTest("cirq is installed")
        from qcoder.engines.feature_extraction.adapters.cirq_intake import (
            circuit_ir_from_cirq,
        )

        with self.assertRaises(ImportError) as ctx:
            circuit_ir_from_cirq(None)
        self.assertIn("Cirq", str(ctx.exception))
        self.assertIn("pip", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()

