from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qcoder.engines.feature_extraction.extractor import extract_example
from qcoder.engines.feature_extraction.features.compute_v0 import compute_features_v0
from qcoder.engines.feature_extraction.parsers import parse_circuit_file, parse_qasm2_text
from qcoder.engines.feature_extraction.qasm2_regex_parser import parse_qasm2_file

_SAMPLE_QASM = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""


class TestParseQasm2Text(unittest.TestCase):
    def test_file_and_text_same_ir(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".qasm", delete=False, encoding="utf-8"
        ) as f:
            f.write(_SAMPLE_QASM)
            path = f.name
        try:
            ir_f = parse_qasm2_file(path)
            ir_t = parse_qasm2_text(_SAMPLE_QASM)
            self.assertEqual(ir_f, ir_t)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_file_and_text_same_features(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".qasm", delete=False, encoding="utf-8"
        ) as f:
            f.write(_SAMPLE_QASM)
            path = f.name
        try:
            fv_f = compute_features_v0(parse_qasm2_file(path))
            fv_t = compute_features_v0(parse_qasm2_text(_SAMPLE_QASM))
            self.assertEqual(fv_f.schema_version, fv_t.schema_version)
            self.assertEqual(fv_f.feature_names, fv_t.feature_names)
            self.assertEqual(fv_f.features, fv_t.features)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_extract_example_via_parse_circuit_file_unchanged(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".qasm", delete=False, encoding="utf-8"
        ) as f:
            f.write(_SAMPLE_QASM)
            path = f.name
        try:
            ex = extract_example(path)
            self.assertEqual(ex.ir.n_qubits, 2)
            self.assertEqual(ex.global_features.feature_names[0], "n_qubits")
            self.assertEqual(ex.global_features.features[0], 2.0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_qasm3_text_sets_format_string(self) -> None:
        oq3 = "OPENQASM 3.0;\nqreg q[1];\n"
        ir = parse_qasm2_text(oq3)
        self.assertEqual(ir.qasm_format, "qasm3")

    def test_partial_qasm3_routed_through_parse_circuit_file_fails_closed(self) -> None:
        oq3 = "OPENQASM 3.0;\nqreg q[1];\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".qasm", delete=False, encoding="utf-8"
        ) as f:
            f.write(oq3)
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                parse_circuit_file(path)
            self.assertEqual(str(ctx.exception), "openqasm3_complete_circuit_ir_not_established")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_supported_qasm3_routed_through_parse_circuit_file(self) -> None:
        oq3 = "OPENQASM 3.0;\nqubit q;\nU(0, 0, 0) q;\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".qasm3", delete=False, encoding="utf-8"
        ) as f:
            f.write(oq3)
            path = f.name
        try:
            ir = parse_circuit_file(path)
            self.assertEqual(ir.qasm_format, "qasm3")
            self.assertEqual(ir.n_qubits, 1)
            self.assertEqual([operation.name for operation in ir.operations], ["U"])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_source_label_does_not_change_ir(self) -> None:
        ir = parse_qasm2_text(_SAMPLE_QASM, source_label="inline")
        ir2 = parse_qasm2_text(_SAMPLE_QASM)
        self.assertEqual(ir, ir2)


if __name__ == "__main__":
    unittest.main()
