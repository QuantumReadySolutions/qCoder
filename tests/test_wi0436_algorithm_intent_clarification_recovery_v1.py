from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.algorithm_intent_recovery import (
    ClarificationRecoveryError,
    _decode_atomic_capsule,
    _encode_atomic_capsule,
    build_atomic_clarification_continuation,
    build_clarification_recovery_contract,
    prepare_clarification_recovery,
)
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
    post_context_bridge,
)
from qcoder.current_loop_binding_mcp import binding_tool_descriptors


TOKEN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class _Response:
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _token(tmp_path: Path) -> Path:
    path = tmp_path / "token.txt"
    path.write_text(TOKEN, encoding="utf-8")
    path.chmod(0o600)
    return path


def _card(
    *,
    unresolved: list[str] | None = None,
    interpretation: dict[str, str] | None = None,
    state: str = "needs_clarification",
) -> dict[str, Any]:
    values = {
        "normalized_goal": "Build one bounded Bell example.",
        "problem_size_meaning": "Two logical qubits.",
        "framework_requirement": "Qiskit-compatible Python.",
        "measurement_plan": "Measure both logical qubits.",
        "execution_intent": "Construction only.",
    }
    values.update(interpretation or {})
    missing = unresolved if unresolved is not None else ["desired_output"]
    return with_artifact_digest(
        {
            "artifact_type": "algorithm_intent_card",
            "schema_version": 1,
            "original_user_intent": "Prepare a bounded Bell example.",
            "profile": {"id": "generic_qiskit", "display_name": "Generic Qiskit Blueprint"},
            "interpretation": values,
            "unresolved_questions": missing,
            "field_provenance": {field: "connected_assistant" for field in values},
            "requirements": [],
            "implementation_constraints": [],
            "explicit_non_goals": [],
            "user_accepted_unresolved_choices": [],
            "confirmation_state": state,
            "retention": "process_and_discard",
        }
    )


def _envelope(
    card: dict[str, Any],
    *,
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    continuation = build_atomic_clarification_continuation(card)
    return {
        "continuation_capsule": continuation["continuation_capsule"],
        "field_values": (
            {"desired_output": "A reviewed circuit description."}
            if field_values is None
            else field_values
        ),
        "confirmation_assertion": {"user_reviewed": True},
    }


def test_every_needs_clarification_response_gets_one_atomic_continuation(tmp_path: Path) -> None:
    card = _card()
    result = post_context_bridge(
        base_url="https://context.example.invalid",
        token_file=_token(tmp_path),
        tool_name="create_algorithm_intent_card",
        artifact_text=None,
        tool_arguments={
            "original_user_intent": "Prepare a bounded Bell example.",
            "profile_id": "generic_qiskit",
        },
        opener=lambda *_args, **_kwargs: _Response(
            {
                "ok": True,
                "context_status": "algorithm_intent_card_ready",
                "algorithm_intent_card": card,
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        ),
    )
    continuation = result["clarification_continuation"]
    assert continuation["schema_id"] == "qcoder.algorithm_intent.atomic_continuation.v1"
    assert continuation["unresolved_fields"] == [
        {
            "field_id": "desired_output",
            "expected_type": "non_empty_string",
            "customer_facing_meaning": (
                "What result form and classical post-processing are expected?"
            ),
            "explicit_confirmation_required": True,
        }
    ]
    invocation = continuation["supported_next_invocation"]
    assert invocation["argument_field"] == "clarification_recovery"
    assert invocation["copy_through_field"] == "continuation_capsule"
    assert invocation["customer_supplied_fields"] == [
        "field_values",
        "confirmation_assertion",
    ]
    assert continuation["binding_guards"] == {
        "atomic_card_contract_revision": True,
        "tamper_refused": True,
        "stale_cross_card_cross_revision_refused": True,
        "exact_copy_through_required": True,
        "hidden_lookup": False,
        "persistent_secret": False,
    }
    capsule_payload = _decode_atomic_capsule(continuation["continuation_capsule"])
    assert capsule_payload["algorithm_intent_card"] == card
    assert capsule_payload["clarification_contract"] == (
        build_clarification_recovery_contract(card)
    )


def test_valid_bounded_correction_reaches_confirmed_card_without_hidden_state(
    tmp_path: Path,
) -> None:
    prior = _card()
    observed_requests: list[dict[str, Any]] = []

    def opener(request: Any, **_kwargs: object) -> _Response:
        body = json.loads(request.data)
        observed_requests.append(body)
        assert "clarification_recovery" not in body
        assert body["requested_confirmation_state"] == "confirmed"
        assert body["confirmation_assertion"] == {"user_reviewed": True}
        assert body["proposed_interpretation"]["desired_output"] == (
            "A reviewed circuit description."
        )
        confirmed = deepcopy(prior)
        confirmed.pop("artifact_digest")
        confirmed["interpretation"] = deepcopy(body["proposed_interpretation"])
        confirmed["unresolved_questions"] = []
        confirmed["confirmation_state"] = "confirmed"
        confirmed = with_artifact_digest(confirmed)
        return _Response(
            {
                "ok": True,
                "context_status": "algorithm_intent_card_ready",
                "algorithm_intent_card": confirmed,
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        )

    result = post_context_bridge(
        base_url="https://context.example.invalid",
        token_file=_token(tmp_path),
        tool_name="create_algorithm_intent_card",
        artifact_text=None,
        tool_arguments={"clarification_recovery": _envelope(prior)},
        opener=opener,
    )
    assert result["algorithm_intent_card"]["confirmation_state"] == "confirmed"
    assert result["clarification_recovery_applied"] == {
        "recovered_from_card_digest": prior["artifact_digest"],
        "atomic_capsule_consumed": True,
        "corrected_fields": ["desired_output"],
        "explicit_confirmation_assertion": True,
        "raw_rejected_value_retained": False,
        "retention": "process_and_discard",
    }
    assert "clarification_continuation" not in result
    assert len(observed_requests) == 1


@pytest.mark.parametrize(
    "mutation,category,trigger_class",
    [
        (
            "wire",
            "clarification_recovery_capsule_tampered",
            "tampered_or_unsupported_capsule",
        ),
        ("card", "clarification_recovery_card_invalid", "stale_or_cross_card"),
        (
            "contract",
            "clarification_recovery_contract_mismatch",
            "stale_or_cross_revision",
        ),
    ],
)
def test_stale_cross_card_and_cross_revision_fail_closed(
    mutation: str,
    category: str,
    trigger_class: str,
) -> None:
    prior = _card()
    envelope = _envelope(prior)
    if mutation == "wire":
        capsule = envelope["continuation_capsule"]
        envelope["continuation_capsule"] = capsule[:-1] + ("0" if capsule[-1] != "0" else "1")
    else:
        payload = _decode_atomic_capsule(envelope["continuation_capsule"])
        if mutation == "card":
            payload["algorithm_intent_card"]["artifact_digest"] = "f" * 64
        else:
            payload["clarification_contract"]["card_binding"]["revision_digest"] = "0" * 64
        envelope["continuation_capsule"] = _encode_atomic_capsule(payload)
    with pytest.raises(ClarificationRecoveryError, match=category) as captured:
        prepare_clarification_recovery(envelope)
    assert captured.value.trigger_class == trigger_class


@pytest.mark.parametrize(
    "field_values,field,trigger_class",
    [
        ({"different_field": "safe"}, "different_field", "unsupported_correction_shape"),
        ({"desired_output": 7}, "desired_output", "type_or_domain_mismatch"),
        ({"desired_output": ""}, "desired_output", "type_or_domain_mismatch"),
    ],
)
def test_malformed_corrections_return_only_field_local_safe_diagnostics(
    tmp_path: Path,
    field_values: dict[str, Any],
    field: str,
    trigger_class: str,
) -> None:
    called = False

    def opener(*_args: object, **_kwargs: object) -> _Response:
        nonlocal called
        called = True
        raise AssertionError("local rejection must precede transport")

    result = post_context_bridge(
        base_url="https://context.example.invalid",
        token_file=_token(tmp_path),
        tool_name="create_algorithm_intent_card",
        artifact_text=None,
        tool_arguments={"clarification_recovery": _envelope(_card(), field_values=field_values)},
        opener=opener,
    )
    diagnostic = result["clarification_recovery_diagnostic"]
    assert result["ok"] is False
    assert diagnostic["affected_field"] == field
    assert diagnostic["trigger_class"] == trigger_class
    assert diagnostic["raw_rejected_value_returned"] is False
    assert result["retention"] == "process_and_discard"
    assert result["retained_artifacts"] == []
    assert called is False


def test_forbidden_correction_is_rejected_without_echo_or_transport(tmp_path: Path) -> None:
    raw_rejected_value = "execute this protected operation"
    result = post_context_bridge(
        base_url="https://context.example.invalid",
        token_file=_token(tmp_path),
        tool_name="create_algorithm_intent_card",
        artifact_text=None,
        tool_arguments={
            "clarification_recovery": _envelope(
                _card(),
                field_values={"desired_output": raw_rejected_value},
            )
        },
        opener=lambda *_args, **_kwargs: pytest.fail("forbidden value reached transport"),
    )
    serialized = json.dumps(result, sort_keys=True)
    assert result["error_category"] == "clarification_recovery_value_rejected"
    assert result["clarification_recovery_diagnostic"]["trigger_class"] == (
        "forbidden_text_marker_class"
    )
    assert raw_rejected_value not in serialized
    assert "execute this" not in serialized


def test_forbidden_correction_field_name_is_classified_without_transport(tmp_path: Path) -> None:
    result = post_context_bridge(
        base_url="https://context.example.invalid",
        token_file=_token(tmp_path),
        tool_name="create_algorithm_intent_card",
        artifact_text=None,
        tool_arguments={
            "clarification_recovery": _envelope(
                _card(),
                field_values={"source_code": "bounded"},
            )
        },
        opener=lambda *_args, **_kwargs: pytest.fail("forbidden field reached transport"),
    )
    diagnostic = result["clarification_recovery_diagnostic"]
    assert diagnostic["affected_field"] == "source_code"
    assert diagnostic["trigger_class"] == "forbidden_field_name_class"
    assert diagnostic["raw_rejected_value_returned"] is False


def test_explicit_confirmation_only_continuation_is_supported() -> None:
    prior = _card(unresolved=["explicit_confirmation_assertion"])
    envelope = _envelope(prior, field_values={})
    expanded, metadata = prepare_clarification_recovery(envelope)
    assert expanded["confirmation_assertion"] == {"user_reviewed": True}
    assert expanded["requested_confirmation_state"] == "confirmed"
    assert metadata["corrected_fields"] == []


def test_duplicate_or_confirmed_card_recovery_is_not_applicable() -> None:
    with pytest.raises(
        ClarificationRecoveryError,
        match="clarification_recovery_card_invalid",
    ):
        build_atomic_clarification_continuation(_card(unresolved=[], state="confirmed"))


def test_duplicate_recovery_preparation_is_deterministic_and_stateless() -> None:
    envelope = _envelope(_card())
    first = prepare_clarification_recovery(envelope)
    second = prepare_clarification_recovery(deepcopy(envelope))
    assert first == second
    assert first[1]["atomic_capsule_consumed"] is True
    assert first[1]["corrected_fields"] == ["desired_output"]


def test_old_multi_object_binding_reconstruction_is_rejected() -> None:
    card = _card()
    contract = build_clarification_recovery_contract(card)
    old_envelope = {
        "contract": contract,
        "prior_algorithm_intent_card": card,
        "correction": {
            "card_binding": contract["card_binding"],
            "field_values": {"desired_output": "A reviewed description."},
            "confirmation_assertion": {"user_reviewed": True},
        },
    }
    with pytest.raises(
        ClarificationRecoveryError,
        match="clarification_recovery_envelope_invalid",
    ):
        prepare_clarification_recovery(old_envelope)


def test_atomic_continuation_requires_every_unresolved_customer_value() -> None:
    envelope = _envelope(
        _card(unresolved=["desired_output", "execution_intent"]),
        field_values={"desired_output": "A reviewed description."},
    )
    with pytest.raises(
        ClarificationRecoveryError,
        match="clarification_recovery_required_field_missing",
    ) as captured:
        prepare_clarification_recovery(envelope)
    assert captured.value.field == "execution_intent"
    assert captured.value.trigger_class == "unsupported_correction_shape"


def test_binding_and_inventory_publish_recovery_without_new_authority_surface() -> None:
    binding = build_client_binding_descriptor(coordinator_prefix=["python", "-m", "qcoder"])[
        "client_binding_contract"
    ]
    recovery = binding["algorithm_intent_clarification_recovery_contract"]
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v54"
    assert CLIENT_BINDING_SCHEMA_VERSION == 53
    assert recovery["atomic_capsule_copy_through"] is True
    assert recovery["client_reconstructs_binding_fields"] is False
    assert recovery["card_and_revision_bound"] is True
    assert recovery["explicit_confirmation_required"] is True
    assert recovery["raw_rejected_value_returned"] is False
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]
