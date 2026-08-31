from __future__ import annotations

from copy import deepcopy

import pytest

from qcoder.engines.feature_extraction.openqasm3_bounded_parser import (
    OPENQASM3_0_RESERVED_FIXED_TOKENS,
    _parse_expression,
    _tokenize,
    parse_openqasm3_text,
)
from qcoder.engines.feature_extraction.openqasm3_static_evidence import (
    LIMIT_KEYS,
    PARSER_LIMIT_MAXIMA,
    OpenQASM3EvidenceError,
    canonical_openqasm3_json,
    render_openqasm3_static_evidence_markdown,
    validate_openqasm3_static_evidence,
)


def _parse(body: str):
    return parse_openqasm3_text(f"OPENQASM 3;\n{body}\n", artifact_label="selected.qasm3")


def _operations(result) -> list[str]:
    return [
        row["name"]
        for row in result.sidecar["construct_ledger"]
        if row["family"] in {"quantum_operation", "measurement", "reset", "barrier"}
        and row["classification"] == "supported"
    ]


@pytest.mark.parametrize(
    "directive",
    [
        "#pragma vendor !?[]{}",
        "pragma vendor !?[]{}",
        "/* ignored */ #pragma vendor payload",
    ],
)
def test_d121_pragma_forms_are_line_bounded_and_preserve_next_gate(directive: str) -> None:
    result = _parse(f'include "stdgates.inc"; qubit q;\n{directive}\nx q;')
    assert _operations(result) == ["x"]
    assert result.sidecar["derived_facts"]["operation_count"]["value"] == 1
    assert [row["family"] for row in result.sidecar["construct_ledger"]][-2:] == [
        "pragma",
        "quantum_operation",
    ]
    assert "vendor" not in canonical_openqasm3_json(result.sidecar)


def test_d121_midline_pragma_starts_after_a_completed_statement() -> None:
    result = _parse('include "stdgates.inc"; qubit q; h q; #pragma opaque\nx q;')
    assert _operations(result) == ["h", "x"]


@pytest.mark.parametrize("directive", ["pragma", "#pragma"])
def test_d121_bare_pragma_is_bounded_malformed(directive: str) -> None:
    result = _parse(f'include "stdgates.inc"; qubit q;\n{directive}\nx q;')
    assert any(
        row["family"] == "pragma" and row["classification"] == "malformed"
        for row in result.sidecar["construct_ledger"]
    )
    assert _operations(result) == ["x"]


def test_d121_annotations_bind_only_the_next_actual_statement() -> None:
    result = _parse('include "stdgates.inc"; qubit q;\n@first data\n@second more\nx q;')
    annotations = [
        row for row in result.sidecar["construct_ledger"] if row["family"] == "annotation"
    ]
    gate = result.sidecar["construct_ledger"][-1]
    assert len(annotations) == 2
    assert all(gate["construct_id"] in row["established"][-1] for row in annotations)
    assert _operations(result) == ["x"]


def test_d121_annotation_after_completed_same_line_statement_binds_forward() -> None:
    result = _parse('include "stdgates.inc"; qubit q; h q; @note data\nx q;')
    assert _operations(result) == ["h", "x"]
    annotation = next(
        row for row in result.sidecar["construct_ledger"] if row["family"] == "annotation"
    )
    assert result.sidecar["construct_ledger"][-1]["construct_id"] in annotation["established"][-1]


def test_d121_annotation_at_eof_is_bounded_invalid_placement() -> None:
    result = _parse('include "stdgates.inc"; qubit q;\n@note data')
    assert result.sidecar["file_status"] == "partial"
    assert any(row["category"] == "malformed_syntax" for row in result.sidecar["diagnostics"])


def test_d121_annotation_cannot_cross_pragma() -> None:
    result = _parse('include "stdgates.inc"; qubit q;\n@note data\n#pragma opaque\nx q;')
    assert _operations(result) == ["x"]
    assert any(
        row["category"] == "malformed_syntax" and row["severity"] == "error"
        for row in result.sidecar["diagnostics"]
    )


@pytest.mark.parametrize("invalid", ["@", "@ Identifier"])
def test_d121_invalid_annotation_tokens_do_not_absorb_next_line(invalid: str) -> None:
    result = _parse(f'include "stdgates.inc"; qubit q;\n{invalid}\nx q;')
    assert _operations(result) == ["x"]
    assert any(
        row["family"] == "annotation" and row["classification"] == "malformed"
        for row in result.sidecar["construct_ledger"]
    )


def test_d121_newline_at_is_a_modifier_not_an_annotation() -> None:
    result = _parse('include "stdgates.inc"; qubit[2] q;\nctrl\n@ x q[0],q[1];')
    assert result.sidecar["construct_ledger"][-1]["family"] == "quantum_operation"
    assert result.sidecar["modifier_chains"][0]["modifiers"][0]["name"] == "ctrl"
    assert not any(row["family"] == "annotation" for row in result.sidecar["construct_ledger"])


def test_d121_annotation_requires_a_token_boundary() -> None:
    result = _parse("qubit foo; foo@bar;")
    assert not any(row["family"] == "annotation" for row in result.sidecar["construct_ledger"])


@pytest.mark.parametrize("directive", ["#pragma opaque", "@note opaque"])
def test_d121_custom_gate_body_directives_are_bounded_without_exception(directive: str) -> None:
    result = _parse(f'include "stdgates.inc"; gate g a {{ {directive}\n x a; }} qubit q; g q;')
    assert result.sidecar["file_status"] == "partial"
    assert any(row["name"] == "x" for row in result.sidecar["construct_ledger"])
    assert result.sidecar["fatal_error"] is None


@pytest.mark.parametrize(
    "loop",
    [
        "for int i in {0,1} x q;",
        "for int i in {0,1} { x q; }",
        "for int i in [0:1] x q;",
        "for int i in {0,1} if (true) x q;",
    ],
)
def test_d121_unsupported_statement_or_scope_does_not_leak_body_operations(loop: str) -> None:
    result = _parse(f'include "stdgates.inc"; qubit q; {loop} h q;')
    assert _operations(result) == ["h"]
    assert result.sidecar["derived_facts"]["gate_statistics"]["value"] == {"h": 1}
    assert result.sidecar["construct_ledger"][-2]["family"] == "control_flow_for"


@pytest.mark.parametrize("calibration", ["cal", "defcal measure q -> c"])
def test_d121_opaque_calibration_hides_inner_tokens_and_preserves_outside_gate(
    calibration: str,
) -> None:
    source = (
        f'include "stdgates.inc"; qubit q; {calibration} {{ OPENQASM #pragma @annotation '
        "// /* */ ; x q; { gate_like; } } h q;"
    )
    result = _parse(source)
    assert result.sidecar["fatal_error"] is None
    assert _operations(result) == ["h"]
    assert [row["family"] for row in result.sidecar["construct_ledger"]][-2:] == [
        "calibration",
        "quantum_operation",
    ]


def test_d121_unbalanced_opaque_calibration_is_fatal_without_prefix_completeness() -> None:
    result = _parse("qubit q; cal { OPENQASM #pragma @annotation x q;")
    assert result.sidecar["file_status"] == "fatal"
    assert result.sidecar["circuit_ir"] is None
    assert result.sidecar["derived_facts"]["operation_count"]["value"] is None


def test_d121_zero_operand_barrier_is_lossless_and_non_depth_adding() -> None:
    result = _parse('include "stdgates.inc"; qubit[2] q; h q[0]; barrier; cx q[0],q[1];')
    sidecar = result.sidecar
    barrier = sidecar["circuit_ir"]["operations"][1]
    assert sidecar["file_status"] == "supported"
    assert barrier == {
        "name": "barrier",
        "qubits": [],
        "params": [],
        "is_measure": False,
        "is_barrier": True,
        "is_reset": False,
        "is_custom": False,
    }
    assert sidecar["derived_facts"]["depth"] == {"value": 2, "exactness": "exact"}
    assert sidecar["derived_facts"]["interaction_graph"]["value"] == [[0, 1]]
    assert canonical_openqasm3_json(sidecar) == canonical_openqasm3_json(sidecar)
    assert render_openqasm3_static_evidence_markdown(
        sidecar
    ) == render_openqasm3_static_evidence_markdown(sidecar)


@pytest.mark.parametrize("reserved", sorted(OPENQASM3_0_RESERVED_FIXED_TOKENS))
@pytest.mark.parametrize(
    "declaration", ["qubit {name};", "bit {name};", "gate {name} a {{ U(0,0,0) a; }}"]
)
def test_d121_exact_openqasm30_reserved_tokens_cannot_be_declared_names(
    reserved: str, declaration: str
) -> None:
    result = _parse(declaration.format(name=reserved))
    assert result.sidecar["file_status"] != "supported"


def test_d121_reserved_behavior_is_case_sensitive_and_does_not_import_nop() -> None:
    assert _parse("qubit In;").sidecar["file_status"] == "supported"
    assert _parse("qubit Gphase;").sidecar["file_status"] == "supported"
    assert _parse("qubit nop;").sidecar["file_status"] == "supported"
    assert "nop" not in OPENQASM3_0_RESERVED_FIXED_TOKENS


@pytest.mark.parametrize(
    "body",
    [
        "qubit[1.0] q;",
        "qubit[1e1] q;",
        "bit[1.0] c;",
        "bit[1e1] c;",
        'include "stdgates.inc"; qubit[2] q; x q[1.0];',
        'include "stdgates.inc"; qubit[2] q; ctrl(1.0) @ x q[0],q[1];',
        'include "stdgates.inc"; qubit[2] q; negctrl(1e1) @ x q[0],q[1];',
    ],
)
def test_d121_float_typed_integral_values_are_not_static_integers(body: str) -> None:
    assert _parse(body).sidecar["file_status"] != "supported"


def test_d121_integer_typed_arithmetic_remains_supported() -> None:
    result = _parse('include "stdgates.inc"; qubit[1+1] q; bit[4/2] c; x q[3-2];')
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["quantum_declarations"][0]["size"] == 2
    assert result.sidecar["classical_declarations"][0]["size"] == 2


def test_d121_unresolved_valid_integer_context_is_qualified_not_malformed() -> None:
    result = _parse("qubit[pi] q;")
    assert result.sidecar["construct_ledger"][-1]["classification"] == "partially_supported"
    assert not result.sidecar["recovery_ledger"]


@pytest.mark.parametrize("expression", ["pi/0", "pi/(1-1)", "pi**5000", "pi**-5000"])
def test_d121_symbolic_operator_bounds_apply_before_symbolic_short_circuit(expression: str) -> None:
    result = _parse(f"qubit q; U({expression},0,0) q;")
    operation = result.sidecar["construct_ledger"][-1]
    assert operation["classification"] == "partially_supported"
    assert result.sidecar["fatal_error"] is None


def test_d121_bounded_symbolic_and_exact_rational_expressions_are_stable() -> None:
    symbolic = _parse_expression(_tokenize("pi**2")[0])
    rational = _parse_expression(_tokenize("(1+1)/2")[0])
    assert symbolic.supported and symbolic.canonical == "(pi**2)"
    assert rational.supported and rational.integer_typed and rational.integer_value == 1


def _source_bound(sidecar: dict, source: bytes) -> str:
    return validate_openqasm3_static_evidence(
        sidecar,
        source_bytes=source,
        artifact_label="selected.qasm3",
    )


def test_d121_source_bound_validation_uses_exact_canonical_reconstruction() -> None:
    source = (
        b'OPENQASM 3; include "stdgates.inc"; qubit[2] q; bit[2] c; h q[0]; h q[1]; c = measure q;'
    )
    sidecar = parse_openqasm3_text(source.decode(), artifact_label="selected.qasm3").sidecar
    assert _source_bound(sidecar, source) == "source_bound"

    mutations: list[dict] = []
    changed = deepcopy(sidecar)
    changed["parser_limits"]["source_bytes"]["observed"] = 1
    mutations.append(changed)
    changed = deepcopy(sidecar)
    changed["parser_limits"]["tokens"]["maximum"] -= 1
    mutations.append(changed)
    changed = deepcopy(sidecar)
    changed["circuit_ir"]["operations"][0]["qubits"] = [1]
    mutations.append(changed)
    changed = deepcopy(sidecar)
    changed["circuit_ir"]["operations"][0]["params"] = ["pi"]
    mutations.append(changed)
    changed = deepcopy(sidecar)
    changed["circuit_ir"]["operations"].append(deepcopy(changed["circuit_ir"]["operations"][0]))
    changed["derived_facts"]["operation_count"]["value"] += 1
    changed["derived_facts"]["gate_statistics"]["value"]["h"] += 1
    changed["parser_limits"]["operations"]["observed"] += 1
    mutations.append(changed)
    changed = deepcopy(sidecar)
    changed["measurements"][0]["quantum_targets"].reverse()
    changed["measurements"][0]["classical_targets"].reverse()
    mutations.append(changed)
    changed = deepcopy(sidecar)
    measurement_ir = [row for row in changed["circuit_ir"]["operations"] if row["is_measure"]]
    measurement_ir[0]["qubits"], measurement_ir[1]["qubits"] = (
        measurement_ir[1]["qubits"],
        measurement_ir[0]["qubits"],
    )
    mutations.append(changed)
    changed = deepcopy(sidecar)
    first, second = changed["construct_ledger"][3:5]
    first["span"], second["span"] = second["span"], first["span"]
    mutations.append(changed)
    changed = deepcopy(sidecar)
    changed["source_sha256"] = "0" * 64
    mutations.append(changed)

    for mutation in mutations:
        with pytest.raises(OpenQASM3EvidenceError):
            _source_bound(mutation, source)


@pytest.mark.parametrize("boolean", [False, True])
@pytest.mark.parametrize(
    "mutator",
    [
        lambda value, flag: value["quantum_declarations"][0].__setitem__("base", flag),
        lambda value, flag: value["measurements"][0]["quantum_targets"].__setitem__(0, flag),
        lambda value, flag: value["circuit_ir"]["operations"][0]["qubits"].__setitem__(0, flag),
        lambda value, flag: value["parser_limits"]["tokens"].__setitem__("observed", flag),
        lambda value, flag: value["parser_limits"]["tokens"].__setitem__("maximum", flag),
    ],
)
def test_d121_standalone_rejects_booleans_in_integer_fields(mutator, boolean: bool) -> None:
    sidecar = _parse("qubit q; bit c; c = measure q;").sidecar
    changed = deepcopy(sidecar)
    mutator(changed, boolean)
    with pytest.raises(OpenQASM3EvidenceError):
        validate_openqasm3_static_evidence(changed)


@pytest.mark.parametrize("limit_name", LIMIT_KEYS)
def test_d121_standalone_locks_every_serialized_parser_limit_maximum(limit_name: str) -> None:
    sidecar = _parse("qubit q;").sidecar
    assert sidecar["parser_limits"][limit_name]["maximum"] == PARSER_LIMIT_MAXIMA[limit_name]
    changed = deepcopy(sidecar)
    changed["parser_limits"][limit_name]["maximum"] += 1
    with pytest.raises(OpenQASM3EvidenceError, match="limit_contract_invalid"):
        validate_openqasm3_static_evidence(changed)


def test_d121_standalone_mode_claims_internal_consistency_only() -> None:
    sidecar = _parse("qubit q; U(0,0,0) q;").sidecar
    assert validate_openqasm3_static_evidence(sidecar) == "standalone_structural_internal"


def test_d121_standalone_rejects_annotation_relationship_contradiction() -> None:
    sidecar = _parse('include "stdgates.inc"; qubit q;\n@note data\nx q;').sidecar
    changed = deepcopy(sidecar)
    annotation = next(row for row in changed["construct_ledger"] if row["family"] == "annotation")
    annotation["established"][-1] = (
        f"The annotation is associated with following {changed['construct_ledger'][0]['construct_id']}."
    )
    with pytest.raises(OpenQASM3EvidenceError, match="annotation_relationship_invalid"):
        validate_openqasm3_static_evidence(changed)
