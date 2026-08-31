from __future__ import annotations

import builtins
import json
from copy import deepcopy
from pathlib import Path

import pytest

from qcoder.context_loop import build_circuit_manifestation
from qcoder.engines.feature_extraction.ir import Operation
from qcoder.engines.feature_extraction.openqasm3_bounded_parser import (
    MAX_EXPRESSION_WORK,
    MAX_OPERATIONS,
    _Parser,
    parse_openqasm3_text,
)
from qcoder.engines.feature_extraction.openqasm3_static_evidence import (
    OpenQASM3EvidenceError,
    canonical_openqasm3_json,
    validate_openqasm3_static_evidence,
)
from qcoder.engines.review.local_evidence import (
    build_local_evidence_review,
    build_share_safe_local_evidence_review,
)
from qcoder.engines.review.openqasm3_manifestation import (
    build_openqasm3_circuit_manifestation,
)


def _parse(body: str, *, header: str = "OPENQASM 3;"):
    return parse_openqasm3_text(f"{header}\n{body}\n", artifact_label="selected.qasm3")


def _operation_names(result) -> list[str]:
    projection = result.sidecar["circuit_ir"]
    return [] if projection is None else [row["name"] for row in projection["operations"]]


def test_line_pragma_is_opaque_bounded_and_does_not_absorb_following_gate() -> None:
    payload = "vendor !? [] {} :: arbitrary-payload"
    result = _parse(f'include "stdgates.inc";\nqubit q;\npragma {payload}\nx q;')
    assert result.sidecar["file_status"] == "partial"
    assert result.sidecar["construct_ledger"][-2]["family"] == "pragma"
    assert result.sidecar["construct_ledger"][-1]["name"] == "x"
    assert result.sidecar["derived_facts"]["operation_count"] == {
        "value": 1,
        "exactness": "exact",
    }
    assert payload not in canonical_openqasm3_json(result.sidecar)


def test_line_annotations_bind_in_order_without_absorbing_following_gate() -> None:
    result = _parse('include "stdgates.inc";\nqubit q;\n@first opaque!?\n@second []{}\nh q;')
    annotations = [
        row for row in result.sidecar["construct_ledger"] if row["family"] == "annotation"
    ]
    gate = result.sidecar["construct_ledger"][-1]
    assert [row["construct_id"] for row in annotations] == [
        "construct-0003",
        "construct-0004",
    ]
    assert all(gate["construct_id"] in row["established"][-1] for row in annotations)
    assert gate["name"] == "h"
    assert result.sidecar["derived_facts"]["operation_count"]["value"] == 1


@pytest.mark.parametrize("directive", ["pragma vendor payload", "@annotation payload"])
def test_line_directive_at_eof_is_bounded_but_never_complete(directive: str) -> None:
    result = parse_openqasm3_text(f"OPENQASM 3;\n{directive}")
    assert result.sidecar["file_status"] == "partial"
    assert result.circuit_ir is None
    assert result.sidecar["fatal_error"] is None


def test_set_literal_braces_are_not_mistaken_for_control_flow_body() -> None:
    result = _parse('include "stdgates.inc"; qubit q; for int i in {0, 1} { x q; } h q;')
    assert [row["family"] for row in result.sidecar["construct_ledger"]][-1] == (
        "quantum_operation"
    )
    assert result.sidecar["construct_ledger"][-1]["name"] == "h"
    assert result.sidecar["derived_facts"]["operation_count"] == {
        "value": 1,
        "exactness": "lower_bound",
    }
    assert "x" not in result.sidecar["derived_facts"]["gate_statistics"]["value"]


def test_opaque_calibration_punctuation_is_bounded_and_cannot_absorb_next_gate() -> None:
    result = _parse('include "stdgates.inc"; qubit q; cal { play !? [] :: opaque; } h q;')
    assert result.sidecar["file_status"] == "partial"
    assert result.sidecar["construct_ledger"][-2]["family"] == "calibration"
    assert result.sidecar["construct_ledger"][-1]["name"] == "h"
    assert result.sidecar["derived_facts"]["operation_count"]["value"] == 1


def test_case_and_reserved_word_rules_are_exact() -> None:
    lowercase_identifier = _parse("qubit openqasm; U(0,0,0) openqasm;")
    reserved_identifier = _parse("qubit if;")
    wrong_gate_case = _parse('include "stdgates.inc"; qubit q; X q;')
    wrong_modifier_case = _parse('include "stdgates.inc"; qubit q; INV @ x q;')
    wrong_declaration_case = _parse("Qubit q;")
    assert lowercase_identifier.sidecar["file_status"] == "supported"
    assert reserved_identifier.sidecar["construct_ledger"][-1]["classification"] == "malformed"
    assert wrong_gate_case.sidecar["construct_ledger"][-1]["classification"] == "unrecognized"
    assert wrong_modifier_case.sidecar["file_status"] == "partial"
    assert wrong_declaration_case.sidecar["file_status"] == "partial"
    assert _parse("qubit q;").sidecar["declared_language_version"] == "3.0"


@pytest.mark.parametrize("version", ["3.1", "3.2", "3.99"])
def test_later_3x_version_is_preserved_without_parsing_as_30(version: str) -> None:
    result = parse_openqasm3_text(f"OPENQASM {version}; qubit q;")
    assert result.sidecar["file_status"] == "fatal"
    assert result.sidecar["declared_language_version"] == version
    assert result.sidecar["fatal_error"]["category"] == "unsupported_openqasm_version"


def test_standard_gate_collision_rules_activate_only_with_exact_include() -> None:
    before_include = _parse("gate x a { U(0,0,0) a; } qubit q; x q;")
    activation_collision = _parse('gate x a { U(0,0,0) a; } include "stdgates.inc"; qubit q; x q;')
    after_include = _parse('include "stdgates.inc"; gate x a { U(0,0,0) a; }')
    assert before_include.sidecar["file_status"] == "supported"
    assert before_include.sidecar["construct_ledger"][-1]["family"] == "custom_gate_call"
    assert any(
        row["family"] == "standard_gate_collision"
        for row in activation_collision.sidecar["construct_ledger"]
    )
    assert activation_collision.sidecar["file_status"] == "partial"
    assert after_include.sidecar["file_status"] == "partial"


def test_static_integer_expression_path_is_shared_by_sizes_indices_and_controls() -> None:
    result = _parse(
        'include "stdgates.inc"; qubit[1+1] q; bit[0x1+1] c; '
        "ctrl(1+1) @ x q[0],q[1],q[2-1]; measure q[1+0] -> c[1];"
    )
    assert result.sidecar["file_status"] == "supported"
    assert result.sidecar["quantum_declarations"][0]["size"] == 2
    assert result.sidecar["classical_declarations"][0]["size"] == 2
    assert result.sidecar["measurements"][0]["quantum_targets"] == [1]
    assert result.sidecar["modifier_chains"][0]["modifiers"][0]["argument"] == "(1+1)"


def test_valid_unresolved_static_expression_is_not_malformed() -> None:
    result = _parse("qubit[n] q;")
    row = result.sidecar["construct_ledger"][0]
    assert row["classification"] == "partially_supported"
    assert not result.sidecar["recovery_ledger"]
    assert result.sidecar["diagnostics"][0]["category"] == "unsupported_expression"


def test_classical_function_expression_is_not_a_quantum_operation() -> None:
    typed = _parse("int value = sin(1);")
    bare = _parse("sin(1);")
    for result in (typed, bare):
        assert result.sidecar["derived_facts"]["operation_count"]["value"] == 0
        assert result.sidecar["derived_facts"]["gate_statistics"]["value"] == {}
        assert all(
            row["family"] != "quantum_operation" for row in result.sidecar["construct_ledger"]
        )


@pytest.mark.parametrize(
    "statement",
    [
        "measure q -> ;",
        "= measure q;",
        "bit c = measure;",
        "measure -> c;",
        "measure q -> c[;",
    ],
)
def test_malformed_measurement_forms_never_become_supported(statement: str) -> None:
    result = _parse(f"qubit q; bit c; {statement}")
    assert result.sidecar["file_status"] in {"partial", "fatal"}
    assert result.circuit_ir is None
    assert result.sidecar["derived_facts"]["measurement_count"]["exactness"] != "exact"


def test_unassigned_measurement_has_no_invented_classical_target_or_crash() -> None:
    result = _parse("qubit q; measure q;")
    measurement = result.sidecar["measurements"][0]
    assert measurement["quantum_targets"] == [0]
    assert measurement["classical_targets"] == []
    manifestation = build_openqasm3_circuit_manifestation(result.sidecar)
    assert manifestation["measurement_mapping"] == []
    assert manifestation["structural_metrics"]["measurement_count"] == 1


def test_measurement_index_and_register_width_relationships() -> None:
    indexed = _parse("qubit[2] q; bit[2] c; measure q[1] -> c[0];")
    mismatch = _parse("qubit[2] q; bit[1] c; c = measure q;")
    assert indexed.sidecar["measurements"][0]["quantum_targets"] == [1]
    assert indexed.sidecar["measurements"][0]["classical_targets"] == [0]
    assert mismatch.sidecar["file_status"] == "partial"
    assert mismatch.circuit_ir is None


def test_reset_grammar_accepts_one_reference_and_rejects_comma_list() -> None:
    scalar = _parse("qubit q; reset q;")
    whole = _parse("qubit[2] q; reset q;")
    comma = _parse("qubit[2] q; reset q[0],q[1];")
    unresolved = _parse("qubit[2] q; reset q[n];")
    out_of_range = _parse("qubit[2] q; reset q[2];")
    assert scalar.sidecar["derived_facts"]["operation_count"]["value"] == 1
    assert whole.sidecar["derived_facts"]["operation_count"]["value"] == 2
    assert comma.sidecar["construct_ledger"][-1]["classification"] == "malformed"
    assert unresolved.sidecar["file_status"] == "partial"
    assert out_of_range.sidecar["file_status"] == "partial"


def test_modifier_and_opaque_custom_calls_withhold_complete_ir_and_manifestation() -> None:
    modifier = _parse('include "stdgates.inc"; qubit[2] q; ctrl @ x q[0],q[1];')
    custom = _parse("gate g a { U(0,0,0) a; } qubit q; g q;")
    for result in (modifier, custom):
        assert result.sidecar["file_status"] == "supported"
        assert result.circuit_ir is None
        assert result.sidecar["circuit_ir"] is None
        with pytest.raises(ValueError, match="complete_circuit_ir_required"):
            build_openqasm3_circuit_manifestation(result.sidecar)


def test_openqasm3_bell_reuses_established_qcoder_metric_meanings() -> None:
    qasm3 = _parse(
        'include "stdgates.inc"; qubit[2] q; bit[2] c; h q[0]; cx q[0],q[1]; c = measure q;'
    )
    qasm2_text = (
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
        "h q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n"
    )
    established = build_circuit_manifestation(qasm_text=qasm2_text)
    projected = build_openqasm3_circuit_manifestation(qasm3.sidecar)
    for key in ("depth", "sequential_gate_count", "entangling_depth"):
        assert projected["structural_metrics"][key] == established["structural_metrics"][key]
    assert qasm3.sidecar["derived_facts"]["depth"]["value"] == 2
    assert projected["structural_metrics"]["entangling_depth"] == 1


def test_barrier_never_creates_interaction_edge() -> None:
    result = _parse("qubit[2] q; barrier q;")
    assert result.sidecar["derived_facts"]["interaction_graph"] == {
        "value": [],
        "exactness": "exact",
    }


@pytest.mark.parametrize("kind", ["qubit", "bit"])
def test_individual_width_ceiling_at_and_above_4096(kind: str) -> None:
    accepted = _parse(f"{kind}[4096] register_name;")
    rejected = _parse(f"{kind}[4097] register_name;")
    assert accepted.sidecar["file_status"] == "supported"
    assert rejected.sidecar["file_status"] == "fatal"
    assert rejected.sidecar["fatal_error"]["category"] == "parser_limit_exceeded"
    assert not rejected.sidecar[f"{'quantum' if kind == 'qubit' else 'classical'}_declarations"]


@pytest.mark.parametrize("kind", ["qubit", "bit"])
def test_total_width_ceiling_at_and_above_4096_precedes_allocation(kind: str) -> None:
    accepted = _parse(f"{kind}[2048] a; {kind}[2048] b;")
    rejected = _parse(f"{kind}[2048] a; {kind}[2049] b;")
    field = "quantum_declarations" if kind == "qubit" else "classical_declarations"
    assert accepted.sidecar["file_status"] == "supported"
    assert rejected.sidecar["file_status"] == "fatal"
    assert [row["size"] for row in rejected.sidecar[field]] == [2048]


def _many_register_operations(operation: str, tail_count: int) -> str:
    return "qubit[4096] q; " + operation * 2 + (operation.replace(" q;", " q[0];") * tail_count)


@pytest.mark.parametrize(
    ("operation", "tail_at_limit"),
    [("measure q;", 1808), ("reset q;", 1808)],
)
def test_measurement_and_reset_operation_limit_at_and_above(
    operation: str, tail_at_limit: int
) -> None:
    at = _parse(_many_register_operations(operation, tail_at_limit))
    above = _parse(_many_register_operations(operation, tail_at_limit + 1))
    assert at.sidecar["file_status"] == "supported"
    assert at.sidecar["derived_facts"]["operation_count"]["value"] == MAX_OPERATIONS
    assert above.sidecar["file_status"] == "fatal"
    assert above.sidecar["parser_limits"]["operations"]["status"] == "exceeded"
    assert above.circuit_ir is None


def test_common_preappend_guard_covers_barriers_and_mixed_operation_classes() -> None:
    parser = _Parser(b"", "", "selected.qasm3")
    barriers = [
        Operation("barrier", (0,), (), 0, 0, is_barrier=True) for _ in range(MAX_OPERATIONS)
    ]
    assert parser._append_operations(barriers, ()) is True
    assert len(parser.operations) == MAX_OPERATIONS
    assert (
        parser._append_operations([Operation("reset", (0,), (), 0, 0, is_reset=True)], ()) is False
    )
    assert len(parser.operations) == MAX_OPERATIONS
    assert parser.fatal_error["category"] == "parser_limit_exceeded"


def test_custom_gate_operation_production_obeys_uniform_limit() -> None:
    source = "gate g a { U(0,0,0) a; } qubit[4096] q; " + "g q;" * 2 + "g q[0];" * 1809
    result = _parse(source)
    assert result.sidecar["file_status"] == "fatal"
    assert result.sidecar["parser_limits"]["operations"]["status"] == "exceeded"
    assert result.circuit_ir is None


def test_broadcast_over_4096_is_preempted_by_width_guard_before_expansion() -> None:
    result = _parse('include "stdgates.inc"; qubit[4097] q; x q;')
    assert result.sidecar["file_status"] == "fatal"
    assert result.sidecar["parser_limits"]["individual_quantum_width"]["status"] == "exceeded"
    assert result.sidecar["parser_limits"]["operations"]["observed"] == 0


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1e999", "1e999"),
        ("1e-999", "1e-999"),
        ("0.123456789012345678901234567890123456789", "0.123456789012345678901234567890123456789"),
        ("1/3", "(1/3)"),
    ],
)
def test_exact_numeric_lexemes_never_pass_through_binary_float(
    expression: str, expected: str
) -> None:
    first = _parse(f"qubit q; U({expression},0,0) q;")
    second = _parse(f"qubit q; U({expression},0,0) q;")
    assert first.sidecar["file_status"] == "supported"
    assert first.sidecar["circuit_ir"]["operations"][0]["params"][0] == expected
    assert canonical_openqasm3_json(first.sidecar) == canonical_openqasm3_json(second.sidecar)
    serialized = canonical_openqasm3_json(first.sidecar).casefold()
    assert "infinity" not in serialized


@pytest.mark.parametrize("expression", ["1/0", "10**5000", "1e5000"])
def test_unbounded_or_invalid_exact_arithmetic_is_qualified(expression: str) -> None:
    result = _parse(f"qubit q; U({expression},0,0) q;")
    assert result.sidecar["file_status"] == "partial"
    assert result.circuit_ir is None
    assert result.sidecar["diagnostics"][-1]["category"] == "unsupported_expression"


def test_deep_additive_expression_is_bounded_without_recursion_escape() -> None:
    expression = "+".join("1" for _ in range(MAX_EXPRESSION_WORK + 2))
    result = _parse(f"qubit q; U({expression},0,0) q;")
    assert result.sidecar["file_status"] == "partial"
    assert result.sidecar["diagnostics"][-1]["category"] == "parser_limit_exceeded"


@pytest.mark.parametrize(
    "target",
    [
        "neighbor.inc",
        "../private/neighbor.inc",
        "/home/customer/private.inc",
        r"C:\\Users\\Customer\\private.inc",
        r"\\\\server\\share\\private.inc",
        ".hidden/private.inc",
        "vendor!?[]{}.inc",
    ],
)
def test_include_targets_are_classified_never_opened_and_share_safe_redacted(
    target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = f'OPENQASM 3;\ninclude "{target}";\nqubit q;\n'
    selected = tmp_path / "private-customer-name.qasm3"
    selected.write_text(source, encoding="utf-8")

    original_open = builtins.open

    def forbidden_include_open(file, *args, **kwargs):
        if str(file) != str(selected):
            raise AssertionError("an include target was opened")
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", forbidden_include_open)
    report = build_local_evidence_review([str(selected)])
    sidecar = report["artifacts"][0]["canonical_artifacts"][0]
    assert sidecar["include_ledger"][0]["opened"] is False
    safe = build_share_safe_local_evidence_review(report, [str(selected)])
    serialized = json.dumps(safe, sort_keys=True)
    assert target not in serialized
    assert "private.inc" not in serialized
    assert selected.name not in serialized


def test_share_safe_filename_requires_explicit_existing_opt_in(tmp_path: Path) -> None:
    selected = tmp_path / "customer-private-bell.qasm3"
    selected.write_text("OPENQASM 3; qubit q; U(0,0,0) q;", encoding="utf-8")
    report = build_local_evidence_review([str(selected)])
    default = build_share_safe_local_evidence_review(report, [str(selected)])
    opted = build_share_safe_local_evidence_review(
        report, [str(selected)], opt_ins={"customer_filenames": True}
    )
    assert selected.name not in json.dumps(default, sort_keys=True)
    assert selected.name in json.dumps(opted, sort_keys=True)
    assert default["customer_filenames_included"] is False
    assert opted["customer_filenames_included"] is True


def test_standalone_and_source_bound_validation_have_distinct_truthful_meanings() -> None:
    source = b"OPENQASM 3; qubit q; U(0,0,0) q;"
    sidecar = parse_openqasm3_text(source.decode()).sidecar
    assert validate_openqasm3_static_evidence(sidecar) == "standalone_structural_internal"
    assert (
        validate_openqasm3_static_evidence(
            sidecar, source_bytes=source, artifact_label="selected.qasm3"
        )
        == "source_bound"
    )
    substituted = deepcopy(sidecar)
    substituted["source_sha256"] = "0" * 64
    assert validate_openqasm3_static_evidence(substituted) == "standalone_structural_internal"
    with pytest.raises(OpenQASM3EvidenceError, match="source_digest_mismatch"):
        validate_openqasm3_static_evidence(
            substituted, source_bytes=source, artifact_label="selected.qasm3"
        )


def test_source_bound_validation_rejects_impossible_and_substituted_spans() -> None:
    source = b"OPENQASM 3;\nqubit q;\nU(0,0,0) q;\n"
    sidecar = parse_openqasm3_text(source.decode()).sidecar
    impossible = deepcopy(sidecar)
    impossible["quantum_declarations"][0]["span"]["start_line"] = 999
    impossible["quantum_declarations"][0]["span"]["end_line"] = 999
    with pytest.raises(OpenQASM3EvidenceError, match="source_span_out_of_bounds"):
        validate_openqasm3_static_evidence(
            impossible, source_bytes=source, artifact_label="selected.qasm3"
        )
    substituted = deepcopy(sidecar)
    substituted["construct_ledger"][-1]["span"] = deepcopy(
        substituted["construct_ledger"][0]["span"]
    )
    with pytest.raises(OpenQASM3EvidenceError, match="source_span_content_mismatch"):
        validate_openqasm3_static_evidence(
            substituted, source_bytes=source, artifact_label="selected.qasm3"
        )


def test_semantic_validator_rejects_d120_fact_target_limit_and_lossy_ir_mutations() -> None:
    bell = _parse(
        'include "stdgates.inc"; qubit[2] q; bit[2] c; h q[0]; cx q[0],q[1]; c = measure q;'
    ).sidecar
    mutations = []

    changed = deepcopy(bell)
    changed["circuit_ir"]["operations"][0]["qubits"] = [2]
    mutations.append(changed)

    changed = deepcopy(bell)
    changed["parser_limits"]["operations"] = {
        "maximum": MAX_OPERATIONS,
        "observed": MAX_OPERATIONS + 1,
        "status": "exceeded",
    }
    mutations.append(changed)

    changed = deepcopy(bell)
    changed["derived_facts"]["operation_count"]["value"] += 1
    mutations.append(changed)

    changed = deepcopy(bell)
    changed["derived_facts"]["gate_statistics"]["value"]["h"] += 1
    mutations.append(changed)

    changed = deepcopy(bell)
    changed["measurements"][0]["classical_targets"] = []
    mutations.append(changed)

    modifier = _parse('include "stdgates.inc"; qubit[2] q; ctrl @ x q[0],q[1];').sidecar
    changed = deepcopy(modifier)
    changed["circuit_ir"] = deepcopy(
        _parse('include "stdgates.inc"; qubit[2] q; cx q[0],q[1];').sidecar["circuit_ir"]
    )
    mutations.append(changed)

    custom = _parse("gate g a { U(0,0,0) a; } qubit q; g q;").sidecar
    changed = deepcopy(custom)
    changed["circuit_ir"] = deepcopy(_parse("qubit q; U(0,0,0) q;").sidecar["circuit_ir"])
    mutations.append(changed)

    for mutation in mutations:
        with pytest.raises(OpenQASM3EvidenceError):
            validate_openqasm3_static_evidence(mutation)


def test_source_bound_validation_rejects_removed_modifier_semantics() -> None:
    source = b'OPENQASM 3; include "stdgates.inc"; qubit[2] q; ctrl @ x q[0],q[1];'
    sidecar = parse_openqasm3_text(source.decode()).sidecar
    changed = deepcopy(sidecar)
    changed["modifier_chains"] = []
    changed["parser_limits"]["modifier_depth"]["observed"] = 0
    with pytest.raises(OpenQASM3EvidenceError, match="source_modifier_binding_mismatch"):
        validate_openqasm3_static_evidence(
            changed, source_bytes=source, artifact_label="selected.qasm3"
        )
