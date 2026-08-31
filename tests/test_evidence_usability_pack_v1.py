from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.cli import main as cli_main
from qcoder.context_bridge_connection import PRIVATE_OPERATION_NAMES, PUBLIC_TOOL_NAMES
from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.evidence_usability import (
    EvidenceUsabilityError,
    build_blueprint_intent_card,
    build_evidence_prompt_pack,
    build_evidence_usability_pack,
    build_run_readiness_checklist,
    canonical_json,
    render_blueprint_intent_card,
    render_evidence_prompt_pack,
    render_run_readiness_checklist,
    validate_blueprint_intent_card,
    validate_evidence_prompt_pack,
    validate_run_readiness_checklist,
)
from qcoder.engines.review.local_evidence import build_local_evidence_review


ROOT = Path(__file__).resolve().parents[1]
BELL_PY = ROOT / "examples/fixtures/local_evidence_bell.py"
BELL_QASM = ROOT / "examples/circuits/bell.qasm"
EXAMPLE = ROOT / "examples/deterministic_evidence_usability_pack"


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _intent(state: str = "confirmed") -> dict[str, object]:
    return with_artifact_digest(
        {
            "artifact_type": "algorithm_intent_card",
            "schema_version": 1,
            "original_user_intent": "Prepare a Bell-state circuit example without executing it.",
            "profile": {"id": "generic_qiskit"},
            "interpretation": {},
            "unresolved_questions": [],
            "field_provenance": {"original_user_intent": "user"},
            "confirmation_state": state,
        }
    )


def _blueprint(state: str = "confirmed") -> dict[str, object]:
    return with_artifact_digest(
        {
            "artifact_type": "implementation_blueprint",
            "schema_version": 1,
            "profile_id": "generic_qiskit",
            "requirements": [
                "Use two logical qubits.",
                "Include explicit measurements for both logical qubits.",
            ],
            "confirmation_state": state,
        }
    )


def _inputs(tmp_path: Path, *, intent_state: str = "confirmed") -> tuple[Path, Path]:
    return (
        _write_json(tmp_path / "intent.json", _intent(intent_state)),
        _write_json(tmp_path / "blueprint.json", _blueprint()),
    )


def test_prompt_pack_is_explicit_share_safe_and_deterministic() -> None:
    paths = [str(BELL_PY), str(BELL_QASM)]
    report = build_local_evidence_review(paths)
    first = build_evidence_prompt_pack(paths=paths, report=report)
    second = build_evidence_prompt_pack(
        paths=list(reversed(paths)), report=build_local_evidence_review(list(reversed(paths)))
    )
    assert canonical_json(first) == canonical_json(second)
    assert render_evidence_prompt_pack(first) == render_evidence_prompt_pack(second)
    assert len(first["selected_artifacts"]) == 2
    assert first["supported_findings"]
    assert first["limitations"]
    assert first["unsupported_statements"]
    assert first["bounded_next_checks"]
    serialized = canonical_json(first)
    assert str(ROOT) not in serialized
    assert "RobWa" not in serialized
    assert '"token"' not in serialized.casefold()
    assert first["boundaries"] == {
        "assistant_quality_guaranteed": False,
        "model_called": False,
        "network_accessed": False,
        "repository_scanned": False,
        "source_or_circuit_executed": False,
        "persistent_memory_created": False,
        "customer_review_required_before_sharing": True,
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n',
            {"ready", "missing_evidence"},
        ),
        (
            'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\n',
            {"ready", "warning", "missing_evidence"},
        ),
        ("OPENQASM 3.0;\nqubit[1] q;\n", {"ready", "warning", "missing_evidence"}),
    ],
)
def test_readiness_dispositions_are_evidence_grounded(
    tmp_path: Path, payload: str, expected: set[str]
) -> None:
    selected = tmp_path / "selected.qasm"
    selected.write_text(payload, encoding="utf-8")
    paths = [str(selected)]
    checklist = build_run_readiness_checklist(
        paths=paths, report=build_local_evidence_review(paths)
    )
    dispositions = {row["disposition"] for row in checklist["checks"]}
    assert expected <= dispositions
    assert checklist["disposition_vocabulary"] == [
        "ready",
        "warning",
        "missing_evidence",
        "unsupported",
        "not_applicable",
    ]
    serialized = canonical_json(checklist).casefold()
    for prohibited in (
        "estimated runtime",
        "predicted fidelity",
        "best backend",
        "recommended shots",
        "will execute successfully",
    ):
        assert prohibited not in serialized


def test_supplied_counts_produce_result_evidence_readiness(tmp_path: Path) -> None:
    counts = _write_json(tmp_path / "counts.json", {"counts": {"00": 5, "11": 7}})
    paths = [str(counts)]
    checklist = build_run_readiness_checklist(
        paths=paths, report=build_local_evidence_review(paths)
    )
    result = next(
        row for row in checklist["checks"] if row["check_id"] == "supplied-result-evidence"
    )
    assert result["disposition"] == "ready"


def test_malformed_partial_and_unsupported_evidence_remain_bounded(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    partial = tmp_path / "partial.qasm"
    partial.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\nmystery q[0];\n',
        encoding="utf-8",
    )
    unsupported = tmp_path / "unsupported.qasm"
    unsupported.write_text("OPENQASM 3.0;\nqubit[1] q;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed JSON"):
        build_local_evidence_review([str(malformed)])
    paths = [str(partial), str(unsupported)]
    report = build_local_evidence_review(paths)
    assert {item["status"] for item in report["artifacts"]} >= {
        "partial",
        "established_with_qualifications",
    }
    prompt = build_evidence_prompt_pack(paths=paths, report=report)
    checklist = build_run_readiness_checklist(paths=paths, report=report)
    assert prompt["limitations"]
    assert prompt["unsupported_statements"]
    assert any(row["disposition"] == "warning" for row in checklist["checks"])
    assert str(tmp_path) not in canonical_json(prompt)


def test_blueprint_intent_preserves_confirmed_proposed_and_absent_states(tmp_path: Path) -> None:
    report = build_local_evidence_review([str(BELL_QASM)])
    intent_path, blueprint_path = _inputs(tmp_path)
    confirmed = build_blueprint_intent_card(
        report=report,
        intent_json=str(intent_path),
        blueprint_json=str(blueprint_path),
    )
    assert confirmed["intent_state"] == "confirmed"
    assert confirmed["user_stated_intent"] == [
        "Prepare a Bell-state circuit example without executing it."
    ]
    assert [row["selected_value"] for row in confirmed["confirmed_blueprint_decisions"]] == [
        "Use two logical qubits.",
        "Include explicit measurements for both logical qubits.",
    ]
    assert all(
        row["authority"] == "selected_evidence_only_not_intent"
        for row in confirmed["observed_evidence"]
    )
    assert confirmed["boundaries"]["intent_inferred_from_source_or_circuit"] is False

    proposed_path = _write_json(tmp_path / "proposed.json", _intent("needs_clarification"))
    proposed = build_blueprint_intent_card(report=report, intent_json=str(proposed_path))
    assert proposed["intent_state"] == "proposed_unconfirmed"
    assert proposed["confirmed_blueprint_decisions"] == []

    absent = build_blueprint_intent_card(report=report)
    assert absent["intent_state"] == "absent"
    assert absent["user_stated_intent"] == []
    assert "Bell" not in canonical_json(absent)


def test_intent_projection_redacts_token_and_credential_assignments(tmp_path: Path) -> None:
    unsafe = _intent()
    unsafe.pop("artifact_digest")
    unsafe["original_user_intent"] = (
        "Prepare the selected example; token=fixture-token-value and password=fixture-password."
    )
    path = _write_json(tmp_path / "intent.json", with_artifact_digest(unsafe))
    card = build_blueprint_intent_card(
        report=build_local_evidence_review([str(BELL_QASM)]),
        intent_json=str(path),
    )
    serialized = canonical_json(card)
    assert "fixture-token-value" not in serialized
    assert "fixture-password" not in serialized
    assert serialized.count("<redacted-sensitive-value>") == 2


def test_blueprint_decision_states_are_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        {
            "profile_decision_id": "choice.confirmed",
            "resolution_state": "resolved",
            "user_disposition": "selected_choice",
            "selected_value": "fixed",
        },
        {
            "profile_decision_id": "choice.unresolved",
            "resolution_state": "unresolved",
            "user_disposition": "left_unresolved",
        },
        {
            "profile_decision_id": "choice.deferred",
            "resolution_state": "evidence_deferred",
            "user_disposition": "deferred_to_later_evidence",
        },
    ]
    monkeypatch.setattr(
        "qcoder.evidence_usability.unpack_decision_record_set", lambda value: records
    )
    monkeypatch.setattr("qcoder.evidence_usability.decision_record_error", lambda value: None)
    report = build_local_evidence_review([str(BELL_QASM)])
    confirmed_blueprint = with_artifact_digest(
        {
            "artifact_type": "implementation_blueprint",
            "schema_version": 1,
            "confirmation_state": "confirmed",
            "blueprint_decision_records": {"synthetic": True},
        }
    )
    monkeypatch.setattr(
        "qcoder.evidence_usability._load_json",
        lambda path, label: None if path is None else confirmed_blueprint,
    )
    card = build_blueprint_intent_card(report=report, blueprint_json="selected.json")
    assert [row["decision_id"] for row in card["confirmed_blueprint_decisions"]] == [
        "choice.confirmed"
    ]
    assert [row["decision_id"] for row in card["unresolved_choices"]] == ["choice.unresolved"]
    assert [row["decision_id"] for row in card["explicitly_deferred_choices"]] == [
        "choice.deferred"
    ]


@pytest.mark.parametrize("field", ["artifact_type", "schema_version", "confirmation_state"])
def test_invalid_confirmed_inputs_fail_closed(tmp_path: Path, field: str) -> None:
    card = _intent()
    card[field] = {"artifact_type": "wrong", "schema_version": 2, "confirmation_state": "approved"}[
        field
    ]
    path = _write_json(tmp_path / "invalid.json", card)
    with pytest.raises(EvidenceUsabilityError):
        build_blueprint_intent_card(
            report=build_local_evidence_review([str(BELL_QASM)]),
            intent_json=str(path),
        )


@pytest.mark.parametrize(
    ("kind", "missing", "expected"),
    [
        ("intent", True, "algorithm_intent_card_confirmed_digest_required"),
        ("intent", False, "algorithm_intent_card_digest_invalid"),
        ("blueprint", True, "implementation_blueprint_confirmed_digest_required"),
        ("blueprint", False, "implementation_blueprint_digest_invalid"),
    ],
)
def test_confirmed_inputs_require_valid_artifact_digest(
    tmp_path: Path, kind: str, missing: bool, expected: str
) -> None:
    selected = _intent() if kind == "intent" else _blueprint()
    if missing:
        selected.pop("artifact_digest")
    else:
        selected["artifact_digest"] = "0" * 64
    selected_path = _write_json(tmp_path / f"{kind}.json", selected)
    kwargs = {f"{kind}_json": str(selected_path)}
    with pytest.raises(EvidenceUsabilityError, match=expected):
        build_blueprint_intent_card(
            report=build_local_evidence_review([str(BELL_QASM)]),
            **kwargs,
        )


@pytest.mark.parametrize(
    ("kind", "state"),
    [
        ("intent", "proposed"),
        ("intent", "needs_clarification"),
        ("blueprint", "proposed"),
        ("blueprint", "needs_clarification"),
    ],
)
def test_unconfirmed_inputs_may_omit_artifact_digest(tmp_path: Path, kind: str, state: str) -> None:
    selected = _intent(state) if kind == "intent" else _blueprint(state)
    selected.pop("artifact_digest")
    selected_path = _write_json(tmp_path / f"{kind}.json", selected)
    kwargs = {f"{kind}_json": str(selected_path)}
    card = build_blueprint_intent_card(
        report=build_local_evidence_review([str(BELL_QASM)]),
        **kwargs,
    )
    if kind == "intent":
        assert card["intent_state"] == "proposed_unconfirmed"
    else:
        assert card["confirmed_blueprint_decisions"] == []


@pytest.mark.parametrize(
    ("kind", "state"),
    [
        ("intent", "proposed"),
        ("intent", "needs_clarification"),
        ("blueprint", "proposed"),
        ("blueprint", "needs_clarification"),
    ],
)
def test_unconfirmed_inputs_reject_invalid_supplied_digest(
    tmp_path: Path, kind: str, state: str
) -> None:
    selected = _intent(state) if kind == "intent" else _blueprint(state)
    selected["artifact_digest"] = "0" * 64
    selected_path = _write_json(tmp_path / f"{kind}.json", selected)
    kwargs = {f"{kind}_json": str(selected_path)}
    with pytest.raises(EvidenceUsabilityError, match=f"{kind}.*digest_invalid"):
        build_blueprint_intent_card(
            report=build_local_evidence_review([str(BELL_QASM)]),
            **kwargs,
        )


def test_valid_confirmed_intent_and_blueprint_project(tmp_path: Path) -> None:
    intent_path, blueprint_path = _inputs(tmp_path)
    card = build_blueprint_intent_card(
        report=build_local_evidence_review([str(BELL_QASM)]),
        intent_json=str(intent_path),
        blueprint_json=str(blueprint_path),
    )
    assert card["intent_state"] == "confirmed"
    assert card["confirmed_blueprint_decisions"]


@pytest.mark.parametrize(
    ("builder", "validator"),
    [
        ("evidence-prompt-pack", validate_evidence_prompt_pack),
        ("run-readiness-checklist", validate_run_readiness_checklist),
        ("blueprint-intent-card", validate_blueprint_intent_card),
    ],
)
def test_projection_validators_reject_extra_fields(
    tmp_path: Path, builder: str, validator: object
) -> None:
    intent_path, blueprint_path = _inputs(tmp_path)
    outputs = build_evidence_usability_pack(
        paths=[str(BELL_QASM)],
        intent_json=str(intent_path),
        blueprint_json=str(blueprint_path),
    )
    mutated = deepcopy(outputs[builder][0])
    mutated["unexpected"] = "unsafe"
    with pytest.raises(EvidenceUsabilityError):
        validator(mutated)  # type: ignore[operator]


@pytest.mark.parametrize("mutation", ["missing_schema", "unsupported_schema", "malformed_digest"])
def test_projection_schema_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    output = build_evidence_usability_pack(paths=[str(BELL_QASM)])["evidence-prompt-pack"][0]
    mutated = deepcopy(output)
    if mutation == "missing_schema":
        mutated.pop("schema_id")
    elif mutation == "unsupported_schema":
        mutated["schema_version"] = 2
    else:
        mutated["selected_artifacts"][0]["sha256"] = "not-a-digest"
    with pytest.raises(EvidenceUsabilityError):
        validate_evidence_prompt_pack(mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "projection_role",
        "boundary:assistant_quality_guaranteed",
        "boundary:model_called",
        "boundary:network_accessed",
        "boundary:repository_scanned",
        "boundary:source_or_circuit_executed",
        "boundary:persistent_memory_created",
        "boundary:customer_review_required_before_sharing",
        "next_check_basis",
        "next_check_identity",
        "duplicate_next_check",
        "prohibited_model_meaning",
    ],
)
def test_prompt_pack_semantic_invariant_mutations_fail_closed(
    mutation: str,
) -> None:
    paths = [str(BELL_QASM)]
    original = build_evidence_prompt_pack(paths=paths, report=build_local_evidence_review(paths))
    mutated = deepcopy(original)
    if mutation == "projection_role":
        mutated["projection_role"] = "general_assistant_authority"
    elif mutation.startswith("boundary:"):
        key = mutation.partition(":")[2]
        mutated["boundaries"][key] = not mutated["boundaries"][key]
    elif mutation == "next_check_basis":
        mutated["bounded_next_checks"][0]["basis"] = "model_recommendation"
    elif mutation == "next_check_identity":
        mutated["bounded_next_checks"][0]["check_id"] = "existing-next-check-0000000000000000"
    elif mutation == "duplicate_next_check":
        mutated["bounded_next_checks"].append(deepcopy(mutated["bounded_next_checks"][0]))
    else:
        mutated["supported_findings"].append("A model was called to establish this finding.")
    with pytest.raises(EvidenceUsabilityError):
        validate_evidence_prompt_pack(mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "projection_role",
        "boundary:execution_performed",
        "boundary:prediction_performed",
        "boundary:new_evidence_created",
        "boundary:repository_scanned",
        "boundary:network_accessed",
        "vocabulary_reordered",
        "vocabulary_substituted",
        "prohibited_missing",
        "prohibited_added",
        "prohibited_substituted",
        "prohibited_reordered",
        "overall_execution_ready",
        "correctness_conclusion",
        "runtime_conclusion",
        "fidelity_conclusion",
        "backend_conclusion",
        "hardware_conclusion",
        "shot_count_conclusion",
        "statistical_conclusion",
    ],
)
def test_readiness_semantic_invariant_mutations_fail_closed(mutation: str) -> None:
    paths = [str(BELL_QASM)]
    original = build_run_readiness_checklist(paths=paths, report=build_local_evidence_review(paths))
    mutated = deepcopy(original)
    if mutation == "projection_role":
        mutated["projection_role"] = "execution_readiness_authority"
    elif mutation.startswith("boundary:"):
        key = mutation.partition(":")[2]
        mutated["boundaries"][key] = not mutated["boundaries"][key]
    elif mutation == "vocabulary_reordered":
        mutated["disposition_vocabulary"].reverse()
    elif mutation == "vocabulary_substituted":
        mutated["disposition_vocabulary"][0] = "execution_ready"
    elif mutation == "prohibited_missing":
        mutated["prohibited_conclusions"].pop()
    elif mutation == "prohibited_added":
        mutated["prohibited_conclusions"].append("model recommendation")
    elif mutation == "prohibited_substituted":
        mutated["prohibited_conclusions"][0] = "estimated duration"
    elif mutation == "prohibited_reordered":
        mutated["prohibited_conclusions"].reverse()
    else:
        claims = {
            "overall_execution_ready": "The selected artifact is execution-ready.",
            "correctness_conclusion": "The algorithm is correct.",
            "runtime_conclusion": "Runtime will be 10 seconds.",
            "fidelity_conclusion": "Fidelity is 99 percent.",
            "backend_conclusion": "This is the best backend.",
            "hardware_conclusion": "Hardware is suitable.",
            "shot_count_conclusion": "The optimal shot count is 1024.",
            "statistical_conclusion": "The evidence is statistically sufficient.",
        }
        mutated["checks"][0]["explanation"] = claims[mutation]
    with pytest.raises(EvidenceUsabilityError):
        validate_run_readiness_checklist(mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "projection_role",
        "boundary:intent_inferred_from_source_or_circuit",
        "boundary:choice_auto_confirmed",
        "boundary:confirmation_authority_changed",
        "boundary:persistent_source_of_truth_created",
        "boundary:model_called",
        "observed_authority",
        "observed_intent_meaning",
        "confirmed_resolution",
        "confirmed_disposition",
        "implicit_confirmation",
        "second_authority",
    ],
)
def test_intent_projection_semantic_invariant_mutations_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    intent_path, blueprint_path = _inputs(tmp_path)
    original = build_blueprint_intent_card(
        report=build_local_evidence_review([str(BELL_QASM)]),
        intent_json=str(intent_path),
        blueprint_json=str(blueprint_path),
    )
    mutated = deepcopy(original)
    if mutation == "projection_role":
        mutated["projection_role"] = "intent_confirmation_authority"
    elif mutation.startswith("boundary:"):
        key = mutation.partition(":")[2]
        mutated["boundaries"][key] = not mutated["boundaries"][key]
    elif mutation == "observed_authority":
        mutated["observed_evidence"][0]["authority"] = "confirms_intent"
    elif mutation == "observed_intent_meaning":
        mutated["observed_evidence"][0]["observation"] = "The circuit confirms user intent."
    elif mutation == "confirmed_resolution":
        mutated["confirmed_blueprint_decisions"][0]["resolution_state"] = "unresolved"
    elif mutation == "confirmed_disposition":
        mutated["confirmed_blueprint_decisions"][0]["user_disposition"] = "left_unresolved"
    elif mutation == "implicit_confirmation":
        mutated["user_stated_intent"] = []
    else:
        mutated["intent_authority"] = {"confirmed": True}
    with pytest.raises(EvidenceUsabilityError):
        validate_blueprint_intent_card(mutated)


def test_renderers_are_byte_deterministic(tmp_path: Path) -> None:
    intent_path, blueprint_path = _inputs(tmp_path)
    first = build_evidence_usability_pack(
        paths=[str(BELL_QASM), str(BELL_PY)],
        intent_json=str(intent_path),
        blueprint_json=str(blueprint_path),
    )
    second = build_evidence_usability_pack(
        paths=[str(BELL_PY), str(BELL_QASM)],
        intent_json=str(intent_path),
        blueprint_json=str(blueprint_path),
    )
    assert {key: (canonical_json(value[0]), value[1]) for key, value in first.items()} == {
        key: (canonical_json(value[0]), value[1]) for key, value in second.items()
    }


def test_guided_replay_commands_and_goldens(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out"
    assert (
        cli_main(
            [
                "review",
                "usability-pack",
                str(EXAMPLE / "bell.py"),
                str(EXAMPLE / "bell.qasm"),
                "--intent-json",
                str(EXAMPLE / "algorithm-intent-card.json"),
                "--blueprint-json",
                str(EXAMPLE / "implementation-blueprint.json"),
                "--out-dir",
                str(output),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "Deterministic evidence usability pack complete.\n"
    for path in sorted((EXAMPLE / "expected").iterdir()):
        assert (output / path.name).read_bytes() == path.read_bytes()
    all_output = "".join(path.read_text() for path in output.iterdir())
    assert "source_or_circuit_executed" in all_output
    assert "execution success" in all_output
    assert str(ROOT) not in all_output


def test_cli_errors_are_bounded(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.json"
    assert (
        cli_main(["review", "usability-pack", str(missing), "--out-dir", str(tmp_path / "out")])
        == 2
    )
    error = capsys.readouterr().err
    assert "selected input does not exist" in error
    assert "Traceback" not in error


def test_canonical_inventory_and_authority_boundaries_are_unchanged() -> None:
    assert tuple(PUBLIC_TOOL_NAMES) == tuple(EXPECTED_TOOLS)
    assert len(EXPECTED_TOOLS) == 12
    assert PRIVATE_OPERATION_NAMES == ("begin_current_loop", "complete_current_step")
    assert len(PRIVATE_OPERATION_NAMES) == 2


def test_markdown_renderers_validate_inputs() -> None:
    for renderer in (
        render_evidence_prompt_pack,
        render_run_readiness_checklist,
        render_blueprint_intent_card,
    ):
        with pytest.raises(EvidenceUsabilityError):
            renderer({"schema_id": "unsupported"})
