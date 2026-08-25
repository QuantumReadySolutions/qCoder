from __future__ import annotations

import json
from pathlib import Path

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.algorithm_intent_recovery import build_atomic_clarification_continuation
from qcoder.connected_assistant_conformance import (
    CUSTOMER_AUTHORITY_OR_DECISION_BOUNDARY,
    CUSTOMER_TERMINAL_OUTCOME,
    GENUINE_BLOCKER,
    NON_TERMINAL_PREPARATORY,
    evaluate_named_workflow_result,
    named_workflow_completion_contract,
    process_and_discard_retention_satisfied,
    retention_evidence_contract,
)
from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
    handle_jsonrpc_message,
    tool_descriptors,
)


def _result(*, tool_name: str, context_status: str, **extra: object) -> dict[str, object]:
    return {
        "ok": True,
        "tool_name": tool_name,
        "context_status": context_status,
        "adapter_status_category": "success_2xx",
        "retention": "process_and_discard",
        **extra,
    }


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_actual_adapter_results_drive_evidence_review_to_exact_customer_outcome(
    tmp_path: Path,
) -> None:
    token = tmp_path / "dummy-token.txt"
    token.write_text(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
        encoding="utf-8",
    )
    token.chmod(0o600)
    observed_tools: list[str] = []

    def opener(request: object, timeout: int = 20) -> _Response:
        assert timeout == 20
        body = json.loads(request.data.decode())  # type: ignore[attr-defined]
        tool_name = body["tool_name"]
        observed_tools.append(tool_name)
        if tool_name == "get_guided_evidence_context":
            return _Response(
                _result(
                    tool_name=tool_name,
                    context_status="assistant_context_ready",
                )
            )
        assert tool_name == "create_result_review_context_card"
        return _Response(
            _result(
                tool_name=tool_name,
                context_status="result_review_context_card_ready",
            )
        )

    first_message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_guided_evidence_context",
            "arguments": {"artifact_text": "synthetic share-safe selected result evidence"},
        },
    }
    first = handle_jsonrpc_message(
        first_message,
        base_url="https://example.invalid",
        token_file=token,
        opener=opener,
    )
    assert first is not None
    first_state = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result=first["result"]["structuredContent"],
    )
    assert first_state["classification"] == NON_TERMINAL_PREPARATORY

    second = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": first_state["next_tool_name"],
                "arguments": {"artifact_text": "synthetic share-safe selected result evidence"},
            },
        },
        base_url="https://example.invalid",
        token_file=token,
        opener=opener,
    )
    assert second is not None
    second_state = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="create_result_review_context_card",
        structured_result=second["result"]["structuredContent"],
        prior_tool_names=tuple(observed_tools[:-1]),
    )

    assert second_state["classification"] == CUSTOMER_TERMINAL_OUTCOME
    assert second_state["next_tool_name"] is None
    assert observed_tools == [
        "get_guided_evidence_context",
        "create_result_review_context_card",
    ]


def test_preparatory_state_is_non_terminal_and_continues_without_ceremony() -> None:
    evaluated = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result=_result(
            tool_name="get_guided_evidence_context",
            context_status="assistant_context_ready",
        ),
    )

    assert evaluated == {
        "workflow_name": "Evidence Review",
        "tool_name": "get_guided_evidence_context",
        "classification": NON_TERMINAL_PREPARATORY,
        "next_tool_name": "create_result_review_context_card",
        "automatic_continuation_allowed": True,
        "customer_interaction_required": False,
        "stop_reason": None,
    }


def test_result_review_customer_outcome_is_terminal_and_stops() -> None:
    evaluated = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="create_result_review_context_card",
        structured_result=_result(
            tool_name="create_result_review_context_card",
            context_status="result_review_context_card_ready",
        ),
        prior_tool_names=("get_guided_evidence_context",),
    )

    assert evaluated["classification"] == CUSTOMER_TERMINAL_OUTCOME
    assert evaluated["next_tool_name"] is None
    assert evaluated["automatic_continuation_allowed"] is False
    assert evaluated["stop_reason"] == "named_customer_outcome_ready"


def test_same_generic_mechanism_completes_algorithm_blueprint_workflow() -> None:
    intent = evaluate_named_workflow_result(
        workflow_name="Algorithm Blueprint / Generation Context",
        tool_name="create_algorithm_intent_card",
        structured_result=_result(
            tool_name="create_algorithm_intent_card",
            context_status="algorithm_intent_card_ready",
            algorithm_intent_card={"confirmation_state": "confirmed"},
        ),
    )
    blueprint = evaluate_named_workflow_result(
        workflow_name="Algorithm Blueprint / Generation Context",
        tool_name="create_implementation_blueprint",
        structured_result=_result(
            tool_name="create_implementation_blueprint",
            context_status="implementation_blueprint_ready",
        ),
        prior_tool_names=("create_algorithm_intent_card",),
    )
    generation = evaluate_named_workflow_result(
        workflow_name="Algorithm Blueprint / Generation Context",
        tool_name="create_generation_context_pack",
        structured_result=_result(
            tool_name="create_generation_context_pack",
            context_status="generation_context_pack_ready",
        ),
        prior_tool_names=(
            "create_algorithm_intent_card",
            "create_implementation_blueprint",
        ),
    )

    assert intent["classification"] == NON_TERMINAL_PREPARATORY
    assert intent["next_tool_name"] == "create_implementation_blueprint"
    assert blueprint["classification"] == NON_TERMINAL_PREPARATORY
    assert blueprint["next_tool_name"] == "create_generation_context_pack"
    assert generation["classification"] == CUSTOMER_TERMINAL_OUTCOME
    assert generation["next_tool_name"] is None


def test_algorithm_intent_confirmation_is_a_real_customer_decision_boundary() -> None:
    card = with_artifact_digest(
        {
            "artifact_type": "algorithm_intent_card",
            "schema_version": 1,
            "original_user_intent": "Prepare one bounded Bell example.",
            "profile": {"id": "generic_qiskit"},
            "interpretation": {},
            "unresolved_questions": ["normalized_goal"],
            "field_provenance": {"original_user_intent": "user"},
            "confirmation_state": "needs_clarification",
        }
    )
    evaluated = evaluate_named_workflow_result(
        workflow_name="Algorithm Blueprint / Generation Context",
        tool_name="create_algorithm_intent_card",
        structured_result=_result(
            tool_name="create_algorithm_intent_card",
            context_status="algorithm_intent_card_ready",
            algorithm_intent_card=card,
            clarification_continuation=build_atomic_clarification_continuation(card),
        ),
    )

    assert evaluated["classification"] == CUSTOMER_AUTHORITY_OR_DECISION_BOUNDARY
    assert evaluated["customer_interaction_required"] is True
    assert evaluated["next_tool_name"] == "create_algorithm_intent_card"
    assert evaluated["clarification_continuation_available"] is True


def test_genuine_blocker_stops_without_bypass() -> None:
    evaluated = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result={
            "ok": False,
            "tool_name": "get_guided_evidence_context",
            "context_status": "assistant_context_ready",
            "status_category": "adapter_rejected",
            "error_category": "forbidden_input_value",
            "retention": "process_and_discard",
        },
    )

    assert evaluated["classification"] == GENUINE_BLOCKER
    assert evaluated["next_tool_name"] is None
    assert evaluated["automatic_continuation_allowed"] is False


def test_customer_authority_boundary_stops_and_cannot_be_auto_approved() -> None:
    evaluated = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result=_result(
            tool_name="get_guided_evidence_context",
            context_status="assistant_context_ready",
            required_authority_input={"authority_kind": "artifact_selection"},
            awaiting_confirmation_fields=["selected_artifact"],
        ),
    )

    assert evaluated["classification"] == CUSTOMER_AUTHORITY_OR_DECISION_BOUNDARY
    assert evaluated["next_tool_name"] is None
    assert evaluated["automatic_continuation_allowed"] is False
    assert evaluated["customer_interaction_required"] is True


def test_artifact_boundary_is_never_broadened_by_completion_contract() -> None:
    contract = named_workflow_completion_contract(EXPECTED_TOOLS)
    evaluated = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result=_result(
            tool_name="get_guided_evidence_context",
            context_status="assistant_context_ready",
            selected_artifact_reference="customer-selected",
            neighboring_artifact_reference="not-authorized",
        ),
    )

    assert contract["artifact_scope_may_be_broadened"] is False
    assert contract["repository_discovery_permitted"] is False
    assert contract["neighboring_file_access_permitted"] is False
    assert contract["hidden_file_selection_permitted"] is False
    assert "selected_artifact_reference" not in evaluated
    assert "neighboring_artifact_reference" not in evaluated


def test_unrelated_workflow_operation_is_isolated_and_stops() -> None:
    evaluated = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="create_generation_context_pack",
        structured_result=_result(
            tool_name="create_generation_context_pack",
            context_status="generation_context_pack_ready",
        ),
    )

    assert evaluated["classification"] == GENUINE_BLOCKER
    assert evaluated["stop_reason"] == "unrelated_workflow_operation"
    assert evaluated["next_tool_name"] is None


def test_canonical_process_and_discard_satisfies_retention_without_literal_list() -> None:
    without_projection = {
        "tool_name": "get_guided_evidence_context",
        "retention": "process_and_discard",
    }
    with_projection = {**without_projection, "retained_artifacts": []}

    assert process_and_discard_retention_satisfied(
        structured_evidence=without_projection,
        expected_tool_name="get_guided_evidence_context",
    )
    assert process_and_discard_retention_satisfied(
        structured_evidence=with_projection,
        expected_tool_name="get_guided_evidence_context",
    )
    contract = retention_evidence_contract()
    assert contract["meaning"] == "no_customer_artifact_retained_for_this_operation"
    assert contract["literal_empty_retained_artifacts_required"] is False
    assert contract["free_form_prose_sufficient"] is False


def test_retention_evidence_fails_closed_when_absent_ambiguous_contradictory_or_wrong() -> None:
    cases = [
        {"tool_name": "get_guided_evidence_context"},
        {
            "tool_name": "get_guided_evidence_context",
            "retention_description": "process and discard",
        },
        {
            "tool_name": "get_guided_evidence_context",
            "retention": "process_and_discard",
            "retained_artifacts": ["contradiction"],
        },
        {
            "tool_name": "get_guided_evidence_context",
            "retention": "process_and_discard",
            "retained_artifact_count": 1,
        },
        {
            "tool_name": "get_guided_evidence_context",
            "retention": "process_and_discard",
            "artifact_retained": True,
        },
        {
            "tool_name": "get_guided_evidence_context",
            "retention": "process_and_discard",
            "retention_state": {"state": "retained", "retained_artifacts": []},
        },
        {
            "tool_name": "create_result_review_context_card",
            "retention": "process_and_discard",
        },
    ]

    assert not any(
        process_and_discard_retention_satisfied(
            structured_evidence=case,
            expected_tool_name="get_guided_evidence_context",
        )
        for case in cases
    )


def test_loop_terminal_blocker_and_authority_states_cannot_continue() -> None:
    repeated = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result=_result(
            tool_name="get_guided_evidence_context",
            context_status="assistant_context_ready",
        ),
        prior_tool_names=("get_guided_evidence_context",),
    )
    unsupported = evaluate_named_workflow_result(
        workflow_name="Evidence Review",
        tool_name="get_guided_evidence_context",
        structured_result=_result(
            tool_name="get_guided_evidence_context",
            context_status="unknown_success_state",
        ),
    )

    assert repeated["classification"] == GENUINE_BLOCKER
    assert repeated["stop_reason"] == "automatic_continuation_loop_or_budget_exhausted"
    assert unsupported["classification"] == GENUINE_BLOCKER
    assert unsupported["stop_reason"] == "qcoder_non_success_or_unsupported_state"
    assert repeated["next_tool_name"] is unsupported["next_tool_name"] is None


def test_distributed_binding_and_tool_descriptions_expose_shared_d072_semantics() -> None:
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["/exact/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    workflow = descriptor["named_workflow_completion"]
    descriptions = {item["name"]: item["description"] for item in tool_descriptors()}

    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v45"
    assert len(EXPECTED_TOOLS) == 12
    assert workflow["preparatory_success_is_completion"] is False
    assert workflow["automatic_continuation_scope"] == "already_selected_named_workflow_only"
    assert (
        "assistant_context_ready is preparatory and non-terminal"
        in descriptions["get_guided_evidence_context"]
    )
    assert "create_result_review_context_card" in descriptions["get_guided_evidence_context"]
    assert "customer-terminal outcome" in descriptions["create_result_review_context_card"]
    assert "claude" not in descriptions["get_guided_evidence_context"].casefold()
