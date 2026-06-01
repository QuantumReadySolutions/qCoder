from __future__ import annotations

import importlib.util
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from qcoder.engines.feature_extraction.features.compute_v0 import compute_features_v0
from qcoder.engines.feature_extraction.parsers import parse_circuit_file


def _qiskit_installed() -> bool:
    return importlib.util.find_spec("qiskit") is not None


@unittest.skipUnless(_qiskit_installed(), "qiskit not installed")
class TestQiskitIntakeWithQiskit(unittest.TestCase):
    def test_bell_features_match_tempfile_from_dumps(self) -> None:
        from qiskit import QuantumCircuit
        from qiskit.qasm2 import dumps

        from qcoder.engines.feature_extraction.adapters.qiskit_intake import (
            extract_features_from_qiskit_circuit,
        )

        qc = QuantumCircuit(2, 2)
        qc.h(0)
        qc.cx(0, 1)
        qc.measure_all()
        text = dumps(qc)
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

        fv_adapt = extract_features_from_qiskit_circuit(qc)
        self.assertEqual(fv_adapt.schema_version, fv_file.schema_version)
        self.assertEqual(fv_adapt.feature_names, fv_file.feature_names)
        self.assertEqual(fv_adapt.features, fv_file.features)

    def test_circuit_ir_matches_parse_qasm2_text_of_dumps(self) -> None:
        from qiskit import QuantumCircuit
        from qiskit.qasm2 import dumps

        from qcoder.engines.feature_extraction.adapters.qiskit_intake import (
            circuit_ir_from_qiskit,
        )
        from qcoder.engines.feature_extraction.qasm2_regex_parser import parse_qasm2_text

        qc = QuantumCircuit(2, 2)
        qc.h(0)
        qc.cx(0, 1)
        qc.measure_all()
        ir_adapt = circuit_ir_from_qiskit(qc)
        ir_ref = parse_qasm2_text(dumps(qc))
        self.assertEqual(ir_adapt, ir_ref)

    def test_export_failure_raises_runtime_error_with_guidance(self) -> None:
        from qiskit import QuantumCircuit

        import qcoder.engines.feature_extraction.adapters.qiskit_intake as qi

        qc = QuantumCircuit(1)
        qc.x(0)

        def bad_dumps(_qc: object) -> str:
            raise OSError("simulated export failure")

        with unittest.mock.patch.object(
            qi,
            "_load_qiskit",
            return_value=(QuantumCircuit, bad_dumps),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                qi.circuit_ir_from_qiskit(qc)
        msg = str(ctx.exception)
        self.assertIn("qcoder", msg.lower())
        self.assertIn("qiskit.qasm2.dumps", msg.lower())

    def test_parse_failure_raises_runtime_error_with_guidance(self) -> None:
        from qiskit import QuantumCircuit

        import qcoder.engines.feature_extraction.adapters.qiskit_intake as qi

        qc = QuantumCircuit(1)
        qc.x(0)
        with unittest.mock.patch.object(
            qi,
            "parse_qasm2_text",
            side_effect=ValueError("simulated parse failure"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                qi.circuit_ir_from_qiskit(qc)
        msg = str(ctx.exception)
        self.assertIn("qcoder", msg.lower())
        self.assertIn("could not parse", msg.lower())


class TestQiskitIntakeWithoutQiskit(unittest.TestCase):
    """Runs when qiskit is absent; skipped assertions when qiskit is present."""

    def test_adapter_module_importable_without_calling_qiskit(self) -> None:
        importlib.import_module("qcoder.engines.feature_extraction.adapters.qiskit_intake")

    def test_missing_qiskit_raises_import_error_with_hint(self) -> None:
        if _qiskit_installed():
            self.skipTest("qiskit is installed")
        from qcoder.engines.feature_extraction.adapters.qiskit_intake import (
            circuit_ir_from_qiskit,
        )

        with self.assertRaises(ImportError) as ctx:
            circuit_ir_from_qiskit(None)
        self.assertIn("Qiskit", str(ctx.exception))
        self.assertIn("pip", str(ctx.exception).lower())

    def test_wrong_type_raises_type_error_when_qiskit_installed(self) -> None:
        if not _qiskit_installed():
            self.skipTest("qiskit not installed")
        from qcoder.engines.feature_extraction.adapters.qiskit_intake import (
            circuit_ir_from_qiskit,
        )

        with self.assertRaises(TypeError):
            circuit_ir_from_qiskit("not a circuit")


if __name__ == "__main__":
    unittest.main()
