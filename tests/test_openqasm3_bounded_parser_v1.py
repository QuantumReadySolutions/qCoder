from __future__ import annotations

import hashlib
import re
from copy import deepcopy

import pytest

from qcoder.engines.feature_extraction.openqasm3_bounded_parser import (
    MAX_MODIFIER_DEPTH,
    MAX_NESTING_DEPTH,
    MAX_SOURCE_BYTES,
    parse_openqasm3_bytes,
    parse_openqasm3_text,
)
from qcoder.engines.feature_extraction.openqasm3_static_evidence import (
    LANGUAGE_BUILTINS,
    OPENQASM3_PARSER_ID,
    OPENQASM3_STANDARD_GATE_VOCABULARY_ID,
    OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID,
    STANDARD_GATES,
    OpenQASM3EvidenceError,
    canonical_openqasm3_json,
    render_openqasm3_static_evidence_markdown,
    validate_openqasm3_static_evidence,
)
from qcoder.engines.feature_extraction.parsers import parse_circuit_file


def _parse(body: str, *, header: str = "OPENQASM 3.0;"):
    return parse_openqasm3_text(f"{header}\n{body}\n", artifact_label="selected.qasm3")


def _classifications(result) -> list[str]:
    return [row["classification"] for row in result.sidecar["construct_ledger"]]


def test_bell_is_complete_deterministic_sidecar_and_ir() -> None:
    source = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cx q[0], q[1];
c = measure q;
"""
    first = parse_openqasm3_text(source, artifact_label="bell.qasm3")
    second = parse_openqasm3_text(source, artifact_label="bell.qasm3")
    assert first == second
    assert first.sidecar["schema_id"] == OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID
    assert first.sidecar["parser_identity"] == OPENQASM3_PARSER_ID
    assert (
        first.sidecar["standard_gate_vocabulary_identity"] == OPENQASM3_STANDARD_GATE_VOCABULARY_ID
    )
    assert first.sidecar["file_status"] == "supported"
    assert first.circuit_ir is not None
    assert first.circuit_ir.qasm_format == "qasm3"
    assert first.circuit_ir.n_qubits == 2
    assert first.circuit_ir.n_cbits == 2
    assert first.sidecar["derived_facts"]["operation_count"] == {
        "value": 4,
        "exactness": "exact",
    }
    assert first.sidecar["derived_facts"]["measurement_count"] == {
        "value": 2,
        "exactness": "exact",
    }
    assert first.sidecar["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert canonical_openqasm3_json(first.sidecar) == canonical_openqasm3_json(second.sidecar)
    assert render_openqasm3_static_evidence_markdown(
        first.sidecar
    ) == render_openqasm3_static_evidence_markdown(second.sidecar)


@pytest.mark.parametrize("header", ["OPENQASM 3;", "OPENQASM 3.0;"])
def test_exact_supported_headers(header: str) -> None:
    result = _parse("qubit q; U(0, pi/2, -tau) q;", header=header)
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["declared_language_version"] == "3.0"


@pytest.mark.parametrize(
    ("source", "category"),
    [
        ("qubit q;", "missing_header"),
        ("openqasm 3.0; qubit q;", "missing_header"),
        ("OPENQASM; qubit q;", "invalid_header"),
        ("OPENQASM 3.1; qubit q;", "unsupported_openqasm_version"),
        ("OPENQASM 4; qubit q;", "unsupported_openqasm_version"),
        ("OPENQASM 3; OPENQASM 3; qubit q;", "malformed_syntax"),
        ("OPENQASM 3; qubit q; OPENQASM 3;", "malformed_syntax"),
    ],
)
def test_header_failures_are_bounded(source: str, category: str) -> None:
    result = parse_openqasm3_text(source)
    assert result.sidecar["file_status"] == "fatal"
    assert result.sidecar["fatal_error"]["category"] == category
    assert result.circuit_ir is None


def test_comments_and_whitespace_are_lexical_trivia() -> None:
    source = """/* before */ OPENQASM 3.0; // header
/* include */ include "stdgates.inc";
qubit /* size */ [2] q;
// operation
h q[0]; /* final */
"""
    result = parse_openqasm3_text(source)
    assert result.sidecar["file_status"] == "supported"
    assert [operation.name for operation in result.circuit_ir.operations] == ["h"]


def test_exact_include_policy_never_opens_a_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "stdgates.inc").write_text("this file must not be opened", encoding="utf-8")
    supported = _parse('include "stdgates.inc"; qubit q; x q;')
    unsupported = _parse('include "neighbor.inc"; qubit q; x q;')
    assert supported.sidecar["include_ledger"] == [
        {
            "target": "stdgates.inc",
            "support": "supported",
            "span": supported.sidecar["include_ledger"][0]["span"],
            "opened": False,
        }
    ]
    assert supported.sidecar["file_status"] == "supported"
    assert unsupported.sidecar["file_status"] == "partial"
    assert unsupported.sidecar["include_ledger"][0]["target"] == "neighbor.inc"
    assert unsupported.sidecar["include_ledger"][0]["opened"] is False
    assert unsupported.circuit_ir is None


def test_language_builtins_are_available_without_include_and_case_is_exact() -> None:
    supported = _parse("qubit q; U(0,0,0) q; gphase(pi);")
    wrong_case = _parse("qubit q; u(0,0,0) q;")
    assert [operation.name for operation in supported.circuit_ir.operations] == ["U", "gphase"]
    assert wrong_case.sidecar["file_status"] == "partial"
    assert "unrecognized" in _classifications(wrong_case)


@pytest.mark.parametrize(("name", "signature"), sorted(STANDARD_GATES.items()))
def test_complete_package_standard_gate_vocabulary(name: str, signature: tuple[int, int]) -> None:
    parameter_count, qubit_count = signature
    parameters = f"({','.join('0' for _ in range(parameter_count))})" if parameter_count else ""
    declarations = " ".join(f"qubit q{index};" for index in range(qubit_count))
    operands = ",".join(f"q{index}" for index in range(qubit_count))
    result = _parse(
        f'include "stdgates.inc"; {declarations} {name}{parameters}'
        + (f" {operands}" if operands else "")
        + ";"
    )
    assert result.sidecar["file_status"] == "supported"
    assert result.circuit_ir.operations[-1].name == name


def test_standard_gate_requires_exact_include() -> None:
    result = _parse("qubit q; x q;")
    assert result.sidecar["file_status"] == "partial"
    assert result.sidecar["construct_ledger"][-1]["classification"] == "unrecognized"


@pytest.mark.parametrize(
    "expression",
    [
        "1",
        "0x10",
        "0o10",
        "0b10",
        "1_000",
        "1.25",
        "1e-3",
        "pi",
        "tau",
        "euler",
        "π",
        "τ",
        "ℇ",
        "-(pi/2)+3**2",
    ],
)
def test_supported_expression_subset(expression: str) -> None:
    result = _parse(f"qubit q; U({expression}, 0, 0) q;")
    assert result.sidecar["file_status"] == "supported"


@pytest.mark.parametrize("expression", ["theta", "sin(pi)", "int[32](1.2)", "1/0"])
def test_unsupported_expression_qualifies_operation(expression: str) -> None:
    result = _parse(f"qubit q; U({expression}, 0, 0) q;")
    assert result.sidecar["file_status"] == "partial"
    assert result.circuit_ir is None
    assert result.sidecar["construct_ledger"][-1]["classification"] == "partially_supported"
    assert any(row["category"] == "unsupported_expression" for row in result.sidecar["diagnostics"])


def test_declarations_indexing_broadcast_reset_and_barrier() -> None:
    result = _parse(
        'include "stdgates.inc"; qubit[2] left; qubit[2] right; bit[2] c; '
        "cx left,right; reset left; barrier left,right; c = measure right;"
    )
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["derived_facts"]["quantum_width"]["value"] == 4
    assert [operation.qubits for operation in result.circuit_ir.operations[:2]] == [(0, 2), (1, 3)]
    assert result.sidecar["derived_facts"]["operation_count"]["value"] == 7


def test_unequal_broadcast_is_partial_and_never_complete_ir() -> None:
    result = _parse('include "stdgates.inc"; qubit[2] a; qubit[3] b; cx a,b;')
    assert result.sidecar["file_status"] == "partial"
    assert result.circuit_ir is None
    assert result.sidecar["derived_facts"]["operation_count"]["exactness"] == "lower_bound"


@pytest.mark.parametrize(
    ("statement", "form"),
    [
        ("c = measure q;", "assignment"),
        ("bit c = measure q;", "declaration"),
        ("measure q -> c;", "arrow"),
        ("measure q;", "unassigned"),
    ],
)
def test_measurement_forms(statement: str, form: str) -> None:
    declarations = "qubit q;" if form in {"declaration", "unassigned"} else "qubit q; bit c;"
    result = _parse(f"{declarations} {statement}")
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["measurements"][-1]["form"] == form
    assert result.sidecar["derived_facts"]["measurement_count"]["value"] == 1


def test_measurement_width_mismatch_is_partial() -> None:
    result = _parse("qubit[2] q; bit[3] c; c = measure q;")
    assert result.sidecar["file_status"] == "partial"
    assert result.sidecar["measurements"][0]["exactness"] == "partial"


def test_indexed_measurement_assignment_is_supported() -> None:
    result = _parse("qubit[2] q; bit[2] c; c[0] = measure q[1];")
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["measurements"][0]["quantum_targets"] == [1]
    assert result.sidecar["measurements"][0]["classical_targets"] == [0]


def test_custom_gate_formals_prior_calls_and_opaque_depth() -> None:
    result = _parse(
        'include "stdgates.inc"; gate pair(theta) a,b { rx(theta) a; cx a,b; } '
        "qubit[2] q; pair(pi/2) q[0],q[1];"
    )
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["custom_gates"][0]["body_call_names"] == ["rx", "cx"]
    assert result.circuit_ir is None
    assert result.sidecar["circuit_ir"] is None
    assert result.sidecar["derived_facts"]["gate_statistics"]["value"]["pair"] == 1
    assert result.sidecar["derived_facts"]["depth"]["exactness"] == "not_established"


@pytest.mark.parametrize(
    "body",
    [
        "gate self a { self a; } qubit q; self q;",
        "gate first a { second a; } gate second b { first b; } qubit q; first q;",
        "qubit q; later q; gate later a { U(0,0,0) a; }",
    ],
)
def test_recursive_cycle_and_forward_calls_are_not_supported(body: str) -> None:
    result = _parse(body)
    assert result.sidecar["file_status"] == "partial"
    assert result.circuit_ir is None


@pytest.mark.parametrize(
    "statement",
    [
        "inv @ x q;",
        "ctrl @ x c,q;",
        "ctrl(2) @ x a,b,q;",
        "negctrl @ x c,q;",
        "pow(1/2) @ x q;",
        "inv @ ctrl @ x c,q;",
    ],
)
def test_supported_modifier_chains(statement: str) -> None:
    names = sorted((set(re.findall(r"\b[a-z]\b", statement)) - {"x", "q"}) | {"q"})
    declarations = " ".join(f"qubit {name};" for name in names)
    result = _parse(f'include "stdgates.inc"; {declarations} {statement}')
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["modifier_chains"]
    assert result.circuit_ir is None


@pytest.mark.parametrize("statement", ["foo @ x q;", "inv(2) @ x q;", "ctrl(0) @ x q;"])
def test_unsupported_modifiers_are_partial(statement: str) -> None:
    result = _parse(f'include "stdgates.inc"; qubit q; {statement}')
    assert result.sidecar["file_status"] == "partial"
    assert any(row["category"] == "unsupported_modifier" for row in result.sidecar["diagnostics"])


@pytest.mark.parametrize(
    "statement",
    [
        "qreg q[2];",
        "creg c[2];",
        "int value = 1;",
        "array[int[8], 2] a;",
        "let alias = q;",
        "input angle theta;",
        "output bit result;",
        "if (flag) { x q; }",
        "for int i in [0:2] { x q; }",
        "while (flag) { x q; }",
        "switch (value) { case 0 { x q; } }",
        "def helper() { return; }",
        "extern helper();",
        "delay[10ns] q;",
        "box { x q; }",
        "duration value;",
        "stretch value;",
        'defcalgrammar "openpulse";',
        "cal { play; }",
        "pragma vendor value;",
        "nop;",
    ],
)
def test_recognized_unsupported_families_are_ledgered_without_descent(statement: str) -> None:
    result = _parse(f"qubit q; {statement}")
    assert result.sidecar["file_status"] == "partial"
    assert "recognized_but_unsupported" in _classifications(result)
    assert result.circuit_ir is None


def test_unknown_gate_is_unrecognized_not_custom() -> None:
    result = _parse("qubit q; mystery q;")
    assert result.sidecar["construct_ledger"][-1]["classification"] == "unrecognized"
    assert result.sidecar["construct_ledger"][-1]["family"] == "quantum_operation"


@pytest.mark.parametrize(
    "statement",
    ["x q[0:1];", "x {q[0],q[1]};", "q[0] ++ q[1];"],
)
def test_slice_set_and_concatenation_are_bounded_unsupported(statement: str) -> None:
    result = _parse(f'include "stdgates.inc"; qubit[2] q; {statement}')
    assert result.sidecar["file_status"] == "partial"
    assert result.sidecar["fatal_error"] is None
    assert result.circuit_ir is None


def test_comment_prefixed_openqasm3_routes_without_extension(tmp_path) -> None:
    selected = tmp_path / "selected.qasm"
    selected.write_text("// selected\nOPENQASM 3; qubit q; U(0,0,0) q;\n", encoding="utf-8")
    result = parse_circuit_file(str(selected))
    assert result.qasm_format == "qasm3"


def test_case_incorrect_openqasm3_routes_to_bounded_header_failure(tmp_path) -> None:
    selected = tmp_path / "selected.qasm"
    selected.write_text("/* selected */ openqasm 3; qubit q;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="openqasm3_complete_circuit_ir_not_established"):
        parse_circuit_file(str(selected))


def test_recoverable_malformed_statement_is_not_repaired_or_complete() -> None:
    result = _parse('include "stdgates.inc"; qubit[0] bad; qubit q; x q;')
    assert result.sidecar["file_status"] == "partial"
    assert result.sidecar["recovery_ledger"][0]["source_repaired"] is False
    assert result.circuit_ir is None


@pytest.mark.parametrize(
    "body",
    [
        "qubit q",
        "gate broken a { U(0,0,0) a;",
        'include "unterminated;',
        "qubit q; }",
    ],
)
def test_fatal_boundaries_never_return_parsed_prefix(body: str) -> None:
    result = _parse(body)
    assert result.sidecar["file_status"] == "fatal"
    assert result.circuit_ir is None
    assert result.sidecar["derived_facts"]["operation_count"]["value"] is None


def test_size_encoding_and_path_fail_closed() -> None:
    oversized = parse_openqasm3_bytes(b"OPENQASM 3;\n" + b" " * MAX_SOURCE_BYTES)
    invalid = parse_openqasm3_bytes(b"OPENQASM 3;\n\xff")
    assert oversized.sidecar["fatal_error"]["category"] == "input_size_exceeded"
    assert invalid.sidecar["fatal_error"]["category"] == "invalid_encoding"
    with pytest.raises(Exception, match="unsafe_path"):
        parse_openqasm3_text("OPENQASM 3;", artifact_label="/private/source.qasm3")


def test_nesting_and_modifier_limits_fail_or_qualify_without_completeness() -> None:
    nesting = "(" * (MAX_NESTING_DEPTH + 1) + "1" + ")" * (MAX_NESTING_DEPTH + 1)
    nested = _parse(f"qubit q; U({nesting},0,0) q;")
    modifiers = " @ ".join(["inv"] * (MAX_MODIFIER_DEPTH + 1) + ["x q"])
    too_many_modifiers = _parse(f'include "stdgates.inc"; qubit q; {modifiers};')
    assert nested.sidecar["file_status"] == "fatal"
    assert nested.sidecar["fatal_error"]["category"] == "parser_limit_exceeded"
    assert too_many_modifiers.sidecar["file_status"] == "partial"
    assert too_many_modifiers.circuit_ir is None


def test_strict_sidecar_validator_rejects_semantic_mutations() -> None:
    result = _parse('include "stdgates.inc"; qubit q; x q;')
    validate_openqasm3_static_evidence(result.sidecar)
    mutations = []
    changed = deepcopy(result.sidecar)
    changed["parser_identity"] = "other"
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["raw_source_included"] = True
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["construct_ledger"][0]["classification"] = "unrecognized"
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["circuit_ir"]["complete"] = False
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["non_claims"] = changed["non_claims"][:-1]
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["artifact_label"] = "/home/customer/private.qasm3"
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["construct_ledger"][0]["construct_id"] = "construct-9999"
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["derived_facts"]["operation_count"]["value"] += 1
    mutations.append(changed)
    changed = deepcopy(result.sidecar)
    changed["circuit_ir"]["n_qubits"] += 1
    mutations.append(changed)
    partial = _parse("qubit q; mystery q;").sidecar
    changed = deepcopy(partial)
    changed["unsupported_region_ledger"] = []
    mutations.append(changed)
    for mutation in mutations:
        with pytest.raises(OpenQASM3EvidenceError):
            validate_openqasm3_static_evidence(mutation)


def test_no_source_or_intent_is_retained() -> None:
    source = "OPENQASM 3; qubit customer_secret; U(0,0,0) customer_secret;"
    result = parse_openqasm3_text(source)
    serialized = canonical_openqasm3_json(result.sidecar)
    assert source not in serialized
    assert result.sidecar["raw_source_included"] is False
    assert result.sidecar["source_or_circuit_executed"] is False
    assert result.sidecar["motif_evidence_emitted"] is False
    assert result.sidecar["intent_inferred"] is False


def test_vocabulary_contract_is_exact() -> None:
    assert LANGUAGE_BUILTINS == {"U": (3, 1), "gphase": (1, 0)}
    assert len(STANDARD_GATES) == 32
    assert STANDARD_GATES["cu"] == (4, 2)
    assert STANDARD_GATES["CX"] == (0, 2)
