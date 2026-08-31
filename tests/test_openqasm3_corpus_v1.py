from __future__ import annotations

from pathlib import Path

from qcoder.engines.feature_extraction.openqasm3_bounded_parser import (
    MAX_BROADCAST_EXPANSION,
    MAX_CUSTOM_GATES,
    MAX_MODIFIER_DEPTH,
    MAX_NESTING_DEPTH,
    MAX_OPERATIONS,
    MAX_RECOVERY_EVENTS,
    MAX_SOURCE_BYTES,
    parse_openqasm3_bytes,
    parse_openqasm3_text,
)


CORPUS = Path(__file__).parent / "fixtures" / "openqasm3_v1"


def _result(path: Path):
    return parse_openqasm3_bytes(path.read_bytes(), artifact_label=path.name)


def test_corpus_inventory_and_expected_file_statuses() -> None:
    groups = {
        "supported": (6, "supported"),
        "partial": (8, "partial"),
        "recognized": (4, "partial"),
        "unrecognized": (2, "partial"),
        "malformed": (8, None),
        "limits": (1, "fatal"),
    }
    for directory, (minimum, status) in groups.items():
        paths = sorted((CORPUS / directory).glob("*.qasm3"))
        assert len(paths) >= minimum
        results = [_result(path) for path in paths]
        if status is not None:
            assert {result.sidecar["file_status"] for result in results} == {status}
    assert (CORPUS / "README.md").is_file()


def test_supported_corpus_has_only_supported_occurrences_and_complete_ir() -> None:
    for path in sorted((CORPUS / "supported").glob("*.qasm3")):
        result = _result(path)
        assert result.circuit_ir is not None, path.name
        assert all(
            row["classification"] == "supported" for row in result.sidecar["construct_ledger"]
        ), path.name
        assert result.sidecar["derived_facts"]["operation_count"]["exactness"] == "exact"


def test_partial_and_recognized_corpus_never_masquerades_as_complete() -> None:
    for directory in ("partial", "recognized", "unrecognized"):
        for path in sorted((CORPUS / directory).glob("*.qasm3")):
            result = _result(path)
            assert result.circuit_ir is None, path.name
            assert result.sidecar["file_status"] == "partial", path.name
            assert any(
                row["classification"] != "supported" for row in result.sidecar["construct_ledger"]
            ), path.name
            assert result.sidecar["derived_facts"]["depth"]["exactness"] == ("not_established")


def test_recognized_corpus_covers_required_families() -> None:
    names = set()
    families = set()
    for path in sorted((CORPUS / "recognized").glob("*.qasm3")):
        for row in _result(path).sidecar["construct_ledger"]:
            if row["classification"] == "recognized_but_unsupported":
                names.add(row["name"])
                families.add(row["family"])
    assert {
        "qreg",
        "creg",
        "int",
        "array",
        "let",
        "input",
        "output",
        "if",
        "else",
        "for",
        "while",
        "switch",
        "break",
        "continue",
        "end",
        "def",
        "return",
        "extern",
        "delay",
        "box",
        "duration",
        "stretch",
        "durationof",
        "cal",
        "defcal",
        "defcalgrammar",
        "pragma",
        "nop",
    } <= names
    assert {
        "compatibility_quantum_declaration",
        "compatibility_classical_declaration",
        "typed_classical_computation",
        "array",
        "alias",
        "input_declaration",
        "output_declaration",
        "general_assignment_or_concatenation",
        "calibration",
    } <= families


def test_partial_corpus_covers_classification_and_exactness() -> None:
    classifications = set()
    diagnostics = set()
    for path in sorted((CORPUS / "partial").glob("*.qasm3")):
        result = _result(path)
        classifications.update(row["classification"] for row in result.sidecar["construct_ledger"])
        diagnostics.update(row["category"] for row in result.sidecar["diagnostics"])
    assert {
        "supported",
        "partially_supported",
        "recognized_but_unsupported",
        "unrecognized",
        "malformed",
    } <= classifications
    assert {
        "unsupported_construct",
        "unsupported_expression",
        "unsupported_include",
        "unsupported_modifier",
        "unrecognized_construct",
        "malformed_syntax",
    } <= diagnostics


def test_malformed_corpus_has_bounded_fatal_or_recovery_outcomes() -> None:
    fatal = 0
    recovered = 0
    for path in sorted((CORPUS / "malformed").glob("*.qasm3")):
        result = _result(path)
        assert result.sidecar["file_status"] in {"fatal", "partial"}
        assert result.circuit_ir is None
        if result.sidecar["file_status"] == "fatal":
            fatal += 1
            assert result.sidecar["fatal_error"] is not None
        else:
            recovered += 1
            assert result.sidecar["recovery_ledger"] or result.sidecar["unsupported_region_ledger"]
    assert fatal >= 5
    assert recovered >= 2


def _padded_source(size: int) -> bytes:
    prefix = b"OPENQASM 3;\n"
    if size < len(prefix) + 4:
        raise AssertionError("test size too small")
    return prefix + b"/*" + b" " * (size - len(prefix) - 4) + b"*/"


def test_source_size_limit_below_at_and_above() -> None:
    below = parse_openqasm3_bytes(_padded_source(MAX_SOURCE_BYTES - 1))
    at = parse_openqasm3_bytes(_padded_source(MAX_SOURCE_BYTES))
    above = parse_openqasm3_bytes(_padded_source(MAX_SOURCE_BYTES + 1))
    assert below.sidecar["file_status"] == "supported"
    assert at.sidecar["file_status"] == "supported"
    assert above.sidecar["file_status"] == "fatal"
    assert above.sidecar["fatal_error"]["category"] == "input_size_exceeded"


def test_broadcast_limit_below_at_and_above() -> None:
    def source(width: int) -> str:
        return f'OPENQASM 3; include "stdgates.inc"; qubit[{width}] q; x q;'

    below = parse_openqasm3_text(source(MAX_BROADCAST_EXPANSION - 1))
    at = parse_openqasm3_text(source(MAX_BROADCAST_EXPANSION))
    above = parse_openqasm3_text(source(MAX_BROADCAST_EXPANSION + 1))
    assert below.sidecar["file_status"] == "supported"
    assert at.sidecar["file_status"] == "supported"
    assert len(at.circuit_ir.operations) == MAX_BROADCAST_EXPANSION
    assert above.sidecar["file_status"] == "fatal"


def test_modifier_limit_at_and_above() -> None:
    def source(count: int) -> str:
        chain = " @ ".join(["inv"] * count + ["x q"])
        return f'OPENQASM 3; include "stdgates.inc"; qubit q; {chain};'

    at = parse_openqasm3_text(source(MAX_MODIFIER_DEPTH))
    above = parse_openqasm3_text(source(MAX_MODIFIER_DEPTH + 1))
    assert at.sidecar["file_status"] == "supported"
    assert above.sidecar["file_status"] == "partial"
    assert above.circuit_ir is None


def test_nesting_limit_at_and_above() -> None:
    def source(count: int) -> str:
        value = "(" * count + "1" + ")" * count
        return f"OPENQASM 3; qubit q; U({value},0,0) q;"

    below = parse_openqasm3_text(source(MAX_NESTING_DEPTH - 2))
    above = parse_openqasm3_text(source(MAX_NESTING_DEPTH + 1))
    assert below.sidecar["file_status"] == "supported"
    assert above.sidecar["file_status"] == "fatal"
    assert above.sidecar["fatal_error"]["category"] == "parser_limit_exceeded"


def test_operation_limit_at_and_above() -> None:
    def source(count: int) -> str:
        return 'OPENQASM 3; include "stdgates.inc"; qubit q; ' + "x q;" * count

    at = parse_openqasm3_text(source(MAX_OPERATIONS))
    above = parse_openqasm3_text(source(MAX_OPERATIONS + 1))
    assert at.sidecar["file_status"] == "supported"
    assert len(at.circuit_ir.operations) == MAX_OPERATIONS
    assert above.sidecar["file_status"] == "fatal"
    assert above.sidecar["parser_limits"]["operations"]["status"] == "exceeded"


def test_custom_gate_limit_at_and_above() -> None:
    def source(count: int) -> str:
        definitions = " ".join(f"gate g{index} q {{ U(0,0,0) q; }}" for index in range(count))
        return f"OPENQASM 3; {definitions}"

    at = parse_openqasm3_text(source(MAX_CUSTOM_GATES))
    above = parse_openqasm3_text(source(MAX_CUSTOM_GATES + 1))
    assert at.sidecar["file_status"] == "supported"
    assert above.sidecar["file_status"] == "fatal"


def test_recovery_limit_at_and_above() -> None:
    def source(count: int) -> str:
        return "OPENQASM 3; " + " ".join(f"qubit[0] q{index};" for index in range(count))

    at = parse_openqasm3_text(source(MAX_RECOVERY_EVENTS))
    above = parse_openqasm3_text(source(MAX_RECOVERY_EVENTS + 1))
    assert at.sidecar["file_status"] == "partial"
    assert len(at.sidecar["recovery_ledger"]) == MAX_RECOVERY_EVENTS
    assert above.sidecar["file_status"] == "fatal"
