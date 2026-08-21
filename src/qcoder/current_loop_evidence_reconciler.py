"""Bounded, goal-specific currentness over exact Current Loop revisions."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from typing import Any


RECONCILER_SCHEMA_ID = "qcoder.current_loop.bounded_evidence_reconciliation.v2"
RECONCILER_SCHEMA_VERSION = 2
_ROLE_ENTITY_TYPES = {
    "source": "source_revision",
    "circuit_qasm": "circuit_manifestation",
    "framework_circuit": "circuit_manifestation",
    "results": "result_manifestation",
}


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _revision(
    artifact_revisions: Mapping[str, Any], revision_id: object
) -> Mapping[str, Any] | None:
    value = artifact_revisions.get(revision_id) if isinstance(revision_id, str) else None
    return value if isinstance(value, Mapping) else None


def _current_circuit_id(role_revision_set: Mapping[str, str]) -> str | None:
    candidates = [
        role_revision_set[role]
        for role in ("circuit_qasm", "framework_circuit")
        if isinstance(role_revision_set.get(role), str)
    ]
    return candidates[0] if len(candidates) == 1 else None


def reconcile_current_evidence(
    *,
    role_revision_set: Mapping[str, str],
    artifact_revisions: Mapping[str, Any],
    normalized_result_manifest: Mapping[str, Any] | None,
    active_goal: str = "current_run_evidence",
) -> dict[str, Any]:
    """Classify an exact causal chain without discovery or historical mutation."""

    source_id = role_revision_set.get("source")
    current_circuit_id = _current_circuit_id(role_revision_set)
    result_id = role_revision_set.get("results")
    source_revision = _revision(artifact_revisions, source_id)
    current_circuit_revision = _revision(artifact_revisions, current_circuit_id)
    result_revision = _revision(artifact_revisions, result_id)
    circuit_lineage = (
        normalized_result_manifest.get("circuit_lineage")
        if isinstance(normalized_result_manifest, Mapping)
        else None
    )
    producing_circuit_id = (
        circuit_lineage.get("artifact_revision_id")
        if isinstance(circuit_lineage, Mapping) and circuit_lineage.get("status") == "exact"
        else None
    )
    producing_circuit_digest = (
        circuit_lineage.get("content_digest")
        if isinstance(circuit_lineage, Mapping) and circuit_lineage.get("status") == "exact"
        else None
    )
    producing_circuit = _revision(artifact_revisions, producing_circuit_id)
    circuit_is_current = bool(
        isinstance(current_circuit_revision, Mapping)
        and producing_circuit_id == current_circuit_id
        and producing_circuit_digest == current_circuit_revision.get("content_digest")
    )
    circuit_source = (
        producing_circuit.get("causal_lineage", {}).get("source")
        if isinstance(producing_circuit, Mapping)
        else None
    )
    if source_id is None:
        source_is_current = True
        exact_source_id = None
        exact_source_digest = None
    elif isinstance(circuit_source, Mapping) and circuit_source.get("status") == "exact":
        exact_source_id = circuit_source.get("artifact_revision_id")
        exact_source_digest = circuit_source.get("content_digest")
        source_is_current = bool(
            isinstance(source_revision, Mapping)
            and exact_source_id == source_id
            and exact_source_digest == source_revision.get("content_digest")
        )
    else:
        exact_source_id = None
        exact_source_digest = None
        source_is_current = False
    valid_result = bool(
        isinstance(result_revision, Mapping)
        and isinstance(normalized_result_manifest, Mapping)
        and result_revision.get("logical_role") == "results"
    )
    current_run = bool(valid_result and circuit_is_current and source_is_current)
    reasons: list[str] = []
    limitations: list[str] = []
    if not valid_result:
        reasons.append("valid_result_manifest_missing")
    elif not isinstance(circuit_lineage, Mapping) or circuit_lineage.get("status") != "exact":
        reasons.append("exact_circuit_lineage_unknown")
        limitations.append("Result evidence is valid, but exact circuit lineage is unknown.")
    elif not circuit_is_current:
        reasons.append("producing_circuit_not_current_role_head")
        limitations.append(
            "Result evidence is historical for a different circuit revision and is not current."
        )
    if source_id is not None and not source_is_current:
        reasons.append("current_source_not_causal_input_to_producing_circuit")
        limitations.append(
            "The current source is not the recorded causal input to the producing circuit; "
            "downstream circuit and result evidence are historical for this goal."
        )
    entities: list[dict[str, Any]] = []
    represented_ids: set[str] = set()
    for role, revision_id in sorted(role_revision_set.items()):
        revision = _revision(artifact_revisions, revision_id)
        active_goal_eligible = bool(
            role == "results"
            and valid_result
            and current_run
            or role in {"circuit_qasm", "framework_circuit"}
            and circuit_is_current
            or role == "source"
            and source_is_current
        )
        entities.append(
            {
                "entity_type": _ROLE_ENTITY_TYPES.get(role, role),
                "logical_role": role,
                "artifact_revision_id": revision_id,
                "content_digest": revision.get("content_digest") if revision else None,
                "currentness": "current_role_head",
                "active_goal_eligible": active_goal_eligible,
                "historical_truth_retained": True,
            }
        )
        represented_ids.add(revision_id)
    for role, revision_id, content_digest in (
        ("circuit_qasm", producing_circuit_id, producing_circuit_digest),
        ("source", exact_source_id, exact_source_digest),
    ):
        if isinstance(revision_id, str) and revision_id not in represented_ids:
            entities.append(
                {
                    "entity_type": _ROLE_ENTITY_TYPES[role],
                    "logical_role": role,
                    "artifact_revision_id": revision_id,
                    "content_digest": content_digest,
                    "currentness": "historical_not_current",
                    "active_goal_eligible": False,
                    "historical_truth_retained": True,
                }
            )
            represented_ids.add(revision_id)
    configuration = (
        normalized_result_manifest.get("execution_configuration")
        if isinstance(normalized_result_manifest, Mapping)
        else None
    )
    configuration_digest = (
        configuration.get("digest")
        if isinstance(configuration, Mapping) and configuration.get("status") == "exact"
        else None
    )
    configuration_entity_id = (
        "execution-configuration-" + str(configuration_digest)[:32]
        if isinstance(configuration_digest, str)
        else "execution-configuration-unknown"
    )
    attempt_id = (
        normalized_result_manifest.get("execution_attempt_id")
        if isinstance(normalized_result_manifest, Mapping)
        else None
    )
    attempt_entity_id = (
        "execution-attempt-" + _digest({"attempt_id": attempt_id})[:32]
        if valid_result and isinstance(attempt_id, str)
        else "execution-attempt-unknown"
    )
    if valid_result:
        capture = normalized_result_manifest.get("capture_provenance", {})
        producer = normalized_result_manifest.get("producer_provenance", {})
        environment_entity_id = (
            "execution-environment-"
            + _digest(
                {
                    "producer": producer,
                    "capture": capture,
                    "explicit_missingness": normalized_result_manifest.get(
                        "explicit_missingness", []
                    ),
                }
            )[:32]
        )
        projection_entity_id = (
            "run-summary-projection-"
            + _digest({"result_revision_id": result_id, "active_goal": active_goal})[:24]
        )
        entities.extend(
            [
                {
                    "entity_type": "execution_configuration",
                    "entity_id": configuration_entity_id,
                    "status": (
                        configuration.get("status")
                        if isinstance(configuration, Mapping)
                        else "unknown"
                    ),
                    "configuration_reference": (
                        configuration.get("reference")
                        if isinstance(configuration, Mapping)
                        else None
                    ),
                    "configuration_digest": configuration_digest,
                    "settings_embedded": False,
                },
                {
                    "entity_type": "execution_attempt",
                    "entity_id": attempt_entity_id,
                    "attempt_identity": attempt_id,
                    "native_execution_owned_by_qcoder": False,
                },
                {
                    "entity_type": "execution_environment_observation",
                    "entity_id": environment_entity_id,
                    "producer_kind": producer.get("kind"),
                    "capture_kind": capture.get("kind"),
                    "producer_or_capture_identity_embedded": False,
                    "explicit_missingness": list(
                        normalized_result_manifest.get("explicit_missingness", [])
                    ),
                },
                {
                    "entity_type": "evidence_projection",
                    "entity_id": projection_entity_id,
                    "canonical_family": "qcoder.current_loop.run_summary",
                    "currentness": "current" if current_run else "historical_not_current",
                },
            ]
        )
    relationships: list[dict[str, Any]] = []
    if valid_result and isinstance(producing_circuit_id, str):
        relationships.extend(
            [
                {
                    "relationship": "executed_from",
                    "from_artifact_revision_id": result_id,
                    "to_artifact_revision_id": producing_circuit_id,
                    "to_content_digest": producing_circuit_digest,
                    "relationship_source": "strict_result_manifest",
                },
                {
                    "relationship": "reused_input",
                    "from_entity_id": attempt_entity_id,
                    "to_artifact_revision_id": producing_circuit_id,
                    "to_content_digest": producing_circuit_digest,
                    "relationship_source": "strict_result_manifest",
                },
            ]
        )
        if isinstance(exact_source_id, str):
            relationships.extend(
                [
                    {
                        "relationship": "derived_from",
                        "from_artifact_revision_id": producing_circuit_id,
                        "to_artifact_revision_id": exact_source_id,
                        "to_content_digest": exact_source_digest,
                        "relationship_source": "registered_circuit_causal_lineage",
                    },
                    {
                        "relationship": "reused_input",
                        "from_entity_id": attempt_entity_id,
                        "to_artifact_revision_id": exact_source_id,
                        "to_content_digest": exact_source_digest,
                        "relationship_source": "registered_circuit_causal_lineage",
                    },
                ]
            )
    if valid_result:
        environment_entity_id = next(
            item["entity_id"]
            for item in entities
            if item.get("entity_type") == "execution_environment_observation"
        )
        projection_entity_id = next(
            item["entity_id"]
            for item in entities
            if item.get("entity_type") == "evidence_projection"
        )
        relationships.extend(
            [
                {
                    "relationship": "captured_from",
                    "from_artifact_revision_id": result_id,
                    "to_entity_id": environment_entity_id,
                    "relationship_source": "strict_result_manifest",
                },
                {
                    "relationship": "produced",
                    "from_entity_id": attempt_entity_id,
                    "to_artifact_revision_id": result_id,
                    "relationship_source": "strict_result_manifest",
                },
                {
                    "relationship": "configured_by",
                    "from_entity_id": attempt_entity_id,
                    "to_entity_id": configuration_entity_id,
                    "relationship_source": "strict_result_manifest",
                },
                {
                    "relationship": "produced",
                    "from_artifact_revision_id": result_id,
                    "to_entity_id": projection_entity_id,
                    "relationship_source": "bounded_evidence_reconciler",
                },
            ]
        )
    result = {
        "schema_id": RECONCILER_SCHEMA_ID,
        "schema_version": RECONCILER_SCHEMA_VERSION,
        "active_goal": active_goal,
        "entities": entities,
        "relationships": relationships,
        "eligibility": {
            "valid_result_evidence": valid_result,
            "current_run_evidence": current_run,
            "reproducibility_rich_run_evidence": bool(
                current_run
                and normalized_result_manifest.get("execution_configuration", {}).get("status")
                == "exact"
                and normalized_result_manifest.get("bit_register_ordering", {}).get("status")
                == "known"
            )
            if isinstance(normalized_result_manifest, Mapping)
            else False,
        },
        "currentness_reasons": reasons,
        "current_role_references": deepcopy(dict(role_revision_set)),
        "historical_role_references_deleted": False,
        "entity_count_bounded_by_current_roles_and_exact_lineage": True,
        "lineage_inferred_from_filename_or_adjacency": False,
        "directory_or_repository_discovery_performed": False,
        "limitations": limitations,
    }
    result["reconciliation_digest"] = _digest(result)
    return result


def reconciler_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": RECONCILER_SCHEMA_ID,
        "schema_version": RECONCILER_SCHEMA_VERSION,
        "bounded_current_loop_entities_only": True,
        "persistent_project_graph": False,
        "historical_truth_immutable": True,
        "currentness_goal_specific": True,
        "current_run_requires_exact_circuit_and_source_causality_when_source_exists": True,
        "implicit_filename_adjacency_or_role_head_causality": False,
        "directory_or_repository_discovery": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload


__all__ = [
    "RECONCILER_SCHEMA_ID",
    "RECONCILER_SCHEMA_VERSION",
    "reconcile_current_evidence",
    "reconciler_contract_snapshot",
]
