"""Bounded, goal-specific currentness over exact Current Loop revisions."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from typing import Any


RECONCILER_SCHEMA_ID = "qcoder.current_loop.bounded_evidence_reconciliation.v1"
RECONCILER_SCHEMA_VERSION = 1
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


def reconcile_current_evidence(
    *,
    role_revision_set: Mapping[str, str],
    artifact_revisions: Mapping[str, Any],
    normalized_result_manifest: Mapping[str, Any] | None,
    active_goal: str = "current_run_evidence",
) -> dict[str, Any]:
    """Classify exact evidence without mutating or discovering historical facts."""

    source_id = role_revision_set.get("source")
    lineage = (
        normalized_result_manifest.get("circuit_lineage")
        if isinstance(normalized_result_manifest, Mapping)
        else None
    )
    circuit_ids = {
        revision_id
        for role in ("circuit_qasm", "framework_circuit")
        if isinstance((revision_id := role_revision_set.get(role)), str)
    }
    circuit_id = (
        lineage.get("artifact_revision_id")
        if isinstance(lineage, Mapping) and lineage.get("artifact_revision_id") in circuit_ids
        else role_revision_set.get("circuit_qasm") or role_revision_set.get("framework_circuit")
    )
    result_id = role_revision_set.get("results")
    lineage_status = lineage.get("status") if isinstance(lineage, Mapping) else "unknown"
    exact_circuit_id = (
        lineage.get("artifact_revision_id")
        if isinstance(lineage, Mapping) and lineage_status == "exact"
        else None
    )
    exact_circuit_digest = (
        lineage.get("content_digest")
        if isinstance(lineage, Mapping) and lineage_status == "exact"
        else None
    )
    exact_source_id = (
        lineage.get("source_artifact_revision_id")
        if isinstance(lineage, Mapping) and lineage_status == "exact"
        else None
    )
    exact_source_digest = (
        lineage.get("source_content_digest")
        if isinstance(lineage, Mapping) and lineage_status == "exact"
        else None
    )
    circuit_revision = artifact_revisions.get(circuit_id) if isinstance(circuit_id, str) else None
    exact_circuit_current = bool(
        isinstance(circuit_revision, Mapping)
        and exact_circuit_id == circuit_id
        and exact_circuit_digest == circuit_revision.get("content_digest")
    )
    source_revision = artifact_revisions.get(source_id) if isinstance(source_id, str) else None
    exact_source_current = bool(
        exact_source_id is None
        or (
            isinstance(source_revision, Mapping)
            and exact_source_id == source_id
            and exact_source_digest == source_revision.get("content_digest")
        )
    )
    valid_result = bool(isinstance(result_id, str) and normalized_result_manifest is not None)
    current_run = bool(valid_result and exact_circuit_current and exact_source_current)
    limitations: list[str] = []
    if valid_result and lineage_status != "exact":
        limitations.append("Result evidence is valid, but exact circuit lineage is unknown.")
    if valid_result and lineage_status == "exact" and not exact_circuit_current:
        limitations.append(
            "Result evidence is historical for a different circuit revision and is not current."
        )
    if valid_result and lineage_status == "exact" and not exact_source_current:
        limitations.append(
            "The producing source revision is historical; downstream circuit and result "
            "evidence are not current for the active source."
        )
    if source_id is not None and circuit_id is not None:
        limitations.append(
            "No source-to-circuit causality is inferred from role heads or workspace proximity."
        )
    entities = []
    entity_revision_ids: set[str] = set()
    for role, revision_id in sorted(role_revision_set.items()):
        entities.append(
            {
                "entity_type": _ROLE_ENTITY_TYPES.get(role, role),
                "logical_role": role,
                "artifact_revision_id": revision_id,
                "content_digest": artifact_revisions.get(revision_id, {}).get("content_digest"),
                "currentness": "current_role_head",
                "active_goal_eligible": bool(
                    (role == "results" and valid_result)
                    or (role in {"circuit_qasm", "framework_circuit"} and exact_circuit_current)
                    or (
                        role == "source" and exact_source_id == revision_id and exact_source_current
                    )
                ),
                "historical_truth_retained": True,
            }
        )
        entity_revision_ids.add(revision_id)
    for role, revision_id, content_digest in (
        ("circuit_qasm", exact_circuit_id, exact_circuit_digest),
        ("source", exact_source_id, exact_source_digest),
    ):
        if isinstance(revision_id, str) and revision_id not in entity_revision_ids:
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
            entity_revision_ids.add(revision_id)
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
    if valid_result:
        entities.append(
            {
                "entity_type": "execution_configuration",
                "entity_id": configuration_entity_id,
                "status": (
                    configuration.get("status") if isinstance(configuration, Mapping) else "unknown"
                ),
                "configuration_reference": (
                    configuration.get("reference") if isinstance(configuration, Mapping) else None
                ),
                "configuration_digest": configuration_digest,
                "settings_embedded": False,
            }
        )
    attempt_id = (
        normalized_result_manifest.get("execution_attempt_id")
        if isinstance(normalized_result_manifest, Mapping)
        else None
    )
    producer = (
        normalized_result_manifest.get("producer")
        if isinstance(normalized_result_manifest, Mapping)
        else None
    )
    attempt_entity_id = (
        "execution-attempt-" + _digest({"attempt_id": attempt_id, "producer": producer})[:32]
        if valid_result and isinstance(attempt_id, str)
        else "execution-attempt-unknown"
    )
    if valid_result:
        entities.extend(
            [
                {
                    "entity_type": "execution_attempt",
                    "entity_id": attempt_entity_id,
                    "attempt_identity": attempt_id,
                    "native_execution_owned_by_qcoder": False,
                },
                {
                    "entity_type": "execution_environment_observation",
                    "entity_id": "execution-environment-"
                    + _digest(
                        {
                            "producer": producer,
                            "explicit_missingness": normalized_result_manifest.get(
                                "explicit_missingness", []
                            ),
                        }
                    )[:32],
                    "producer_kind": (
                        producer.get("kind") if isinstance(producer, Mapping) else None
                    ),
                    "capture_method": (
                        producer.get("capture_method") if isinstance(producer, Mapping) else None
                    ),
                    "producer_identity_embedded": False,
                    "explicit_missingness": list(
                        normalized_result_manifest.get("explicit_missingness", [])
                    ),
                },
                {
                    "entity_type": "evidence_projection",
                    "entity_id": "run-summary-projection-pending-"
                    + _digest(
                        {
                            "result_revision_id": result_id,
                            "active_goal": active_goal,
                        }
                    )[:24],
                    "canonical_family": "qcoder.current_loop.run_summary.v2",
                    "currentness": "current" if current_run else "historical_not_current",
                },
            ]
        )
    relationships = []
    if valid_result and lineage_status == "exact":
        relationships.extend(
            [
                {
                    "relationship": "executed_from",
                    "from_artifact_revision_id": result_id,
                    "to_artifact_revision_id": exact_circuit_id,
                    "to_content_digest": exact_circuit_digest,
                    "relationship_source": "strict_result_manifest",
                },
                {
                    "relationship": "reused_input",
                    "from_entity_id": attempt_entity_id,
                    "to_artifact_revision_id": exact_circuit_id,
                    "to_content_digest": exact_circuit_digest,
                    "relationship_source": "strict_result_manifest",
                },
            ]
        )
        if exact_source_id is not None:
            relationships.extend(
                [
                    {
                        "relationship": "derived_from",
                        "from_artifact_revision_id": exact_circuit_id,
                        "to_artifact_revision_id": exact_source_id,
                        "to_content_digest": exact_source_digest,
                        "relationship_source": "strict_result_manifest",
                    },
                    {
                        "relationship": "reused_input",
                        "from_entity_id": attempt_entity_id,
                        "to_artifact_revision_id": exact_source_id,
                        "to_content_digest": exact_source_digest,
                        "relationship_source": "strict_result_manifest",
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
        "implicit_filename_adjacency_or_role_head_causality": False,
        "directory_or_repository_discovery": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload
