from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import EXPECTED_TOOLS
from qcoder.current_loop_binding_mcp import binding_tool_descriptors
from qcoder.development_evidence import MOTIF_REGISTRY
from qcoder.protected_capability import (
    ProtectedCapabilityCategory,
    protected_capability_outcome,
)
from qcoder.protected_decision_client import ProtectedDecisionClient
from qcoder.protected_decision_contract import (
    PROPOSAL_CONTRACT_ID,
    REQUEST_CONTRACT_ID,
    RESPONSE_CONTRACT_ID,
    boundary_contract_manifest,
    canonical_digest,
    protected_contract_snapshot,
)
from qcoder.protected_decision_local_authority import (
    confirm_inert_proposal,
    inert_proposal_projection,
)
from qcoder.protected_decision_validation import (
    decode_json_strict,
    validate_request,
    validate_response,
)
from qcoder.public_motif_allowlist import PUBLIC_MOTIF_ALLOWLIST_V1

ROOT = Path(__file__).parents[1]
TIER_P = (
    "qcoder.connected_assistant_conformance",
    "qcoder.context_bridge_mcp",
    "qcoder.context_bridge_setup",
    "qcoder.current_loop",
    "qcoder.current_loop_artifact_satisfaction",
    "qcoder.current_loop_binding_mcp",
    "qcoder.current_loop_checkpoint_input",
    "qcoder.current_loop_contract_sidecar",
    "qcoder.current_loop_derivation",
    "qcoder.current_loop_evidence_reconciler",
    "qcoder.current_loop_invocation",
    "qcoder.current_loop_registration",
    "qcoder.current_loop_result_controls",
    "qcoder.current_loop_result_envelope",
    "qcoder.current_loop_retention",
    "qcoder.cursor_post_write_hook",
)
TIER_O = (
    "qcoder.current_loop_run_summary",
    "qcoder.development_evidence",
    "qcoder.engines.review.local_evidence",
    "qcoder.engines.review.openqasm3_manifestation",
    "qcoder.framework_native_evidence",
    "qcoder.source_evidence_depth",
)
TIER_D = (
    "qcoder.algorithm_blueprint",
    "qcoder.algorithm_intent_recovery",
    "qcoder.blueprint_decisions",
    "qcoder.context_loop",
    "qcoder.current_loop_adaptive_intent",
    "qcoder.current_loop_coordinator",
    "qcoder.d079_workflows",
)
MOTIFS = (
    "qiskit.circuit.construction",
    "qiskit.parameter.use",
    "qiskit.measurement.mapping",
    "qiskit.controlled.operations",
    "qiskit.result.processing",
    "grover.oracle.structure",
    "grover.diffusion.amplification",
    "grover.iteration.structure",
    "qaoa.cost.layer",
    "qaoa.mixer.layer",
    "qaoa.repetition.layer",
    "qaoa.parameterized.layer",
)
NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


def _request() -> dict[str, object]:
    request: dict[str, object] = {
        "contract_id": REQUEST_CONTRACT_ID,
        "contract_version": 1,
        "expires_at": "2026-09-02T18:00:00Z",
        "intent": {
            "artifact_kind": "python_source",
            "customer_visible_constraint_categories": ["source_free_review"],
            "framework_category": "qiskit",
            "objective_category": "review_before_generation",
            "operation_intent_categories": ["prepare", "measure"],
            "unresolved_choice_ids": [],
        },
        "nonce": "n" * 32,
        "privacy_assertions": {
            "bounded_customer_visible_intent_only": True,
            "contains_customer_payload": False,
            "contains_source_or_evidence": False,
        },
        "request_digest": "",
        "semantic_revision_digest": "b" * 64,
    }
    request["request_digest"] = canonical_digest(request, omit="request_digest")
    return request


def _proposal() -> dict[str, object]:
    proposal: dict[str, object] = {
        "authority": "inert_until_exact_local_confirmation",
        "groups": [
            {
                "group_id": "implementation",
                "label": "Implementation",
                "value": "Use the customer-visible bounded recommendation.",
            }
        ],
        "limitations": ["Execution remains a separate local authority."],
        "proposal_digest": "",
        "schema_id": PROPOSAL_CONTRACT_ID,
        "unresolved_choice_ids": [],
    }
    proposal["proposal_digest"] = canonical_digest(proposal, omit="proposal_digest")
    return proposal


def _response() -> dict[str, object]:
    response: dict[str, object] = {
        "contract_id": RESPONSE_CONTRACT_ID,
        "contract_version": 1,
        "expires_at": "2026-09-02T18:00:00Z",
        "outcome": ProtectedCapabilityCategory.COMPLETED.value,
        "proposal": _proposal(),
        "request_digest": _request()["request_digest"],
        "response_digest": "",
    }
    response["response_digest"] = canonical_digest(response, omit="response_digest")
    return response


def test_exact_29_names_import_and_have_one_tier() -> None:
    names = TIER_P + TIER_O + TIER_D
    assert len(names) == len(set(names)) == 29
    assert (len(TIER_P), len(TIER_O), len(TIER_D)) == (16, 6, 7)
    for name in names:
        assert importlib.import_module(name) is not None


def test_tier_d_facades_use_all_six_bounded_states_without_fallback() -> None:
    categories = {item.value for item in ProtectedCapabilityCategory}
    assert categories == {
        "protected_capability_completed",
        "protected_capability_unavailable",
        "protected_capability_unauthorized",
        "protected_capability_expired",
        "protected_capability_quota_limited",
        "protected_capability_unsupported_contract",
    }
    for category in categories:
        result = protected_capability_outcome(category).as_dict()
        assert result["category"] == category
        assert result["local_authority_granted"] is False
        assert result["local_effect_performed"] is False
        assert result["historical_policy_fallback"] is False
        assert result["retry_performed"] is False
    for name in TIER_D:
        facade = importlib.import_module(name)
        for category in categories:
            result = facade.protected_capability_state(category)
            assert result["category"] == category
            assert result["local_authority_granted"] is False
            assert result["local_effect_performed"] is False
            assert result["historical_policy_fallback"] is False


def test_offline_client_is_truthful_and_has_zero_effect() -> None:
    result, proposal = ProtectedDecisionClient().request(_request(), now=NOW)
    assert result.category == ProtectedCapabilityCategory.UNAVAILABLE
    assert result.local_authority_granted is False
    assert result.local_effect_performed is False
    assert proposal is None


def test_packaged_boundary_manifest_matches_source_constants() -> None:
    manifest = boundary_contract_manifest()
    snapshot = protected_contract_snapshot()
    assert manifest["request_contract_id"] == REQUEST_CONTRACT_ID
    assert manifest["response_contract_id"] == RESPONSE_CONTRACT_ID
    assert manifest["proposal_contract_id"] == PROPOSAL_CONTRACT_ID
    assert manifest["request_keys"] == snapshot["request_keys"]
    assert manifest["intent_keys"] == snapshot["intent_keys"]
    assert manifest["outcomes"] == snapshot["outcomes"]


def test_valid_synthetic_proposal_is_inert_until_exact_local_confirmation() -> None:
    outcome, proposal = ProtectedDecisionClient(transport=lambda _request: _response()).request(
        _request(), now=NOW
    )
    assert outcome.category == ProtectedCapabilityCategory.COMPLETED
    assert outcome.local_effect_performed is False
    assert proposal == _proposal()
    projection = inert_proposal_projection(
        proposal,
        semantic_revision_digest="b" * 64,
    )
    assert projection["local_effect_performed"] is False
    assert projection["write_authorized"] is False
    assert projection["execution_authorized"] is False
    confirmation = confirm_inert_proposal(
        projection,
        displayed_proposal_digest=proposal["proposal_digest"],
        displayed_semantic_revision_digest="b" * 64,
    )
    assert confirmation["customer_confirmation_exact"] is True
    assert confirmation["write_authorized"] is False
    assert confirmation["execution_authorized"] is False
    assert confirmation["continuation_authorized"] is False


def test_stale_proposal_or_revision_fails_closed() -> None:
    projection = inert_proposal_projection(_proposal(), semantic_revision_digest="b" * 64)
    with pytest.raises(ValueError, match="proposal_stale"):
        confirm_inert_proposal(
            projection,
            displayed_proposal_digest="0" * 64,
            displayed_semantic_revision_digest="b" * 64,
        )
    with pytest.raises(ValueError, match="revision_stale"):
        confirm_inert_proposal(
            projection,
            displayed_proposal_digest=_proposal()["proposal_digest"],
            displayed_semantic_revision_digest="0" * 64,
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"raw_prompt": "example"},
        {"source": "example"},
        {"qasm": "example"},
        {"path": "example.py"},
        {"counts": {"0": 1}},
        {"provider_result": {}},
        {"credential": "example"},
    ],
)
def test_customer_or_raw_fields_reject_before_transport(extra: dict[str, object]) -> None:
    request = _request() | extra
    with pytest.raises(ValueError, match="keys_invalid"):
        validate_request(request, now=NOW)


def test_strict_json_and_contract_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate_key"):
        decode_json_strict(b'{"a":1,"a":2}')
    with pytest.raises(ValueError, match="utf8_invalid"):
        decode_json_strict(b"\xff")
    with pytest.raises(ValueError, match="nonfinite_number"):
        decode_json_strict(b'{"a":NaN}')
    request = _request()
    request["request_digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest_mismatch"):
        validate_request(request, now=NOW)
    response = _response()
    response["contract_version"] = 0
    with pytest.raises(ValueError, match="unsupported"):
        validate_response(response, now=NOW)


def test_graph_break_and_zero_non_facade_reachability() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_wi0441_public_boundary.py", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    graph = json.loads(result.stdout)
    assert graph["non_facade_to_tier_d_direct"] == {}
    assert graph["non_facade_to_tier_d_transitive"] == {}
    assert graph["mixed_tier_d_components"] == []
    assert graph["post_change"]["largest_component"] == 2
    assert graph["cursor_post_write_hook_reaches_tier_d"] == []
    assert "qcoder.current_loop_coordinator" not in graph["cursor_post_write_hook_direct_imports"]
    assert graph["protected_package_imports"] == []


def test_exact_12_plus_2_inventory() -> None:
    assert len(EXPECTED_TOOLS) == len(set(EXPECTED_TOOLS)) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]


def test_flat_public_motif_allowlist_is_exact() -> None:
    assert tuple(MOTIF_REGISTRY) == MOTIFS == PUBLIC_MOTIF_ALLOWLIST_V1
