"""Deterministic local continuity for one explicitly activated Explorer loop.

This module deliberately owns local files and portable references only. It does
not retrieve earlier loops, persist continuity remotely, traverse parent
references, or infer user authority from conversation.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

from qcoder.algorithm_blueprint import (
    artifact_digest_matches,
    with_artifact_digest,
)
from qcoder.blueprint_decisions import (
    PROFILE_DECISION_CATALOG_ID,
    PROFILE_DECISION_CATALOG_VERSION,
    catalog_entries,
    consistency_digest,
    decision_record_error,
    unpack_decision_record_set,
)

LOOP_INSTANCE_RECORD_SCHEMA_ID = "qcoder.loop_instance_record.v1"
NEXT_LOOP_SEED_SCHEMA_ID = "qcoder.next_loop_seed.v1"
UNCHANGED_CONTINUATION_SCHEMA_ID = "qcoder.unchanged_continuation.v1"
SELECTED_ARTIFACT_AUTHORIZATION_SCHEMA_ID = "qcoder.selected_artifact_authorization.v1"
CURRENT_LOOP_STATE_SCHEMA_ID = "qcoder.current_loop.local_state.v1"

LOOP_INSTANCE_RECORD_MAX_BYTES = 65_536
NEXT_LOOP_SEED_MAX_BYTES = 65_536
CURRENT_LOOP_STATE_MAX_BYTES = 262_144
MAX_STAGE_ARTIFACTS = 32
MAX_REQUIRED_PARENTS = 16
MAX_CHANGED_DECISIONS = 64
MAX_AUTHORIZED_ARTIFACTS = 32
MAX_LABEL_LENGTH = 160
MAX_LOCAL_FILE_BYTES = 8 * 1024 * 1024

ACTIVATION_STATES = ("active", "completed", "abandoned")
COMPLETION_STATES = (
    "in_progress",
    "completed_unchanged",
    "completed_changed",
    "abandoned",
)
CONTINUATION_OUTCOMES = (
    "not_decided",
    "unchanged_continuation",
    "confirmed_change",
    "abandoned",
)
AUTHORIZATION_STATES = ("proposed", "approved", "declined", "stale")
GENERATION_POSTURES = ("blueprint_guided", "exploratory_first_pass")
AUTHORIZED_ARTIFACT_ROLES = (
    "source",
    "circuit_qasm",
    "results",
    "other_supported",
)
PERMITTED_CONTINUITY_OPERATION_FAMILIES = ("create_generation_context_pack",)

_LOOP_REF_PATTERN = re.compile(r"^loop-[A-Za-z0-9_-]{32,64}$")
_AUTH_REF_PATTERN = re.compile(r"^authorization-[A-Za-z0-9_-]{22,64}$")
_ARTIFACT_REF_PATTERN = re.compile(
    r"^(?:session-artifact-[0-9a-f]{16,64}|"
    r"(?:proposal|derived|continuation|seed)-[A-Za-z0-9_-]{22,64})$"
)
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PORTABLE_KEYS = {
    "authorization",
    "credential",
    "customer_identity",
    "local_path",
    "password",
    "path",
    "raw_bitstrings",
    "raw_circuit",
    "raw_counts",
    "raw_qasm",
    "raw_results",
    "raw_source",
    "token",
    "workspace_root",
}

_CANONICAL_ARTIFACT_ROLES = {
    "request_baseline",
    "request_baseline_handoff",
    "algorithm_intent_card",
    "working_blueprint",
    "output_evidence_contract",
    "generation_context_pack",
    "exploratory_generation_context",
    "stage_availability",
    "python_manifestation",
    "circuit_manifestation",
    "result_manifestation",
    "source_evidence",
    "source_blueprint_alignment",
    "result_review_context_card",
    "decision_evidence_lineage",
    "current_build_context",
    "portable_current_build_context",
    "pre_proposal_portable_current_build_context",
    "proposal_bearing_portable_current_build_context",
    "carry_forward_proposal",
    "evolved_blueprint",
    "loop_instance_record",
    "unchanged_continuation",
    "next_loop_seed",
}

_STALE_RECOVERY = {
    "selected_file_changed": {
        "explanation": "An approved selected file no longer matches its approved content.",
        "affected": [
            "selected_artifact_authorization",
            "stage_manifestation",
            "current_build_context",
            "carry_forward_proposal",
            "next_loop_seed",
        ],
        "blocked": "dependent_context_loop_transition",
        "recovery": "Review the exact selected set again, approve it, and recreate dependent evidence.",
        "renewed_authorization_required": True,
        "reextraction_required": True,
    },
    "selected_file_missing": {
        "explanation": "An approved selected file is missing or no longer a regular file.",
        "affected": [
            "selected_artifact_authorization",
            "stage_manifestation",
            "current_build_context",
            "carry_forward_proposal",
            "next_loop_seed",
        ],
        "blocked": "dependent_context_loop_transition",
        "recovery": "Restore the exact file or explicitly select and approve its replacement.",
        "renewed_authorization_required": True,
        "reextraction_required": True,
    },
    "selected_set_changed": {
        "explanation": "The proposed selected set differs from the approved set.",
        "affected": [
            "selected_artifact_authorization",
            "stage_manifestations",
            "current_build_context",
        ],
        "blocked": "evidence_extraction",
        "recovery": "Approve the complete changed set before extracting evidence.",
        "renewed_authorization_required": True,
        "reextraction_required": True,
    },
    "manifestation_missing": {
        "explanation": "A saved stage manifestation required by this transition is missing.",
        "affected": ["stage_manifestation", "current_build_context"],
        "blocked": "dependent_context_loop_transition",
        "recovery": "Recreate and save the missing manifestation from the currently approved artifact.",
        "renewed_authorization_required": False,
        "reextraction_required": True,
    },
    "canonical_artifact_modified": {
        "explanation": "A saved canonical qCoder artifact no longer matches its recorded bytes or digest.",
        "affected": [
            "canonical_artifact",
            "current_build_context",
            "carry_forward_proposal",
            "unchanged_continuation",
            "next_loop_seed",
        ],
        "blocked": "canonical_parent_resupply",
        "recovery": "Restore the exact saved artifact or recreate it through the supported qCoder operation.",
        "renewed_authorization_required": False,
        "reextraction_required": False,
    },
    "parent_digest_mismatch": {
        "explanation": "An explicitly supplied parent does not match the required digest.",
        "affected": ["parent_set", "next_operation"],
        "blocked": "protected_request",
        "recovery": "Supply the exact saved parent file named by the seed or portable bundle.",
        "renewed_authorization_required": False,
        "reextraction_required": False,
    },
    "loop_instance_record_mismatch": {
        "explanation": "The Loop Instance Record does not match current exact local state.",
        "affected": ["loop_instance_record", "continuity_transition"],
        "blocked": "continuity_transition",
        "recovery": "Recreate the record from exact saved canonical artifacts and current explicit state.",
        "renewed_authorization_required": False,
        "reextraction_required": False,
    },
    "next_loop_seed_mismatch": {
        "explanation": "The next-loop seed is incomplete, stale, or does not match its supplied parents.",
        "affected": ["next_loop_seed", "next_loop_activation"],
        "blocked": "next_loop_activation",
        "recovery": "Recreate the seed through Unchanged Continuation or the confirmed-change path.",
        "renewed_authorization_required": False,
        "reextraction_required": False,
    },
    "concurrent_state_update": {
        "explanation": "Another local client updated the current-loop state first.",
        "affected": ["current_loop_state"],
        "blocked": "local_state_update",
        "recovery": "Reload local state, revalidate it, and retry the explicit action.",
        "renewed_authorization_required": False,
        "reextraction_required": False,
    },
    "source_changed": {
        "explanation": "The approved source changed after its evidence was created.",
        "affected": [
            "source_evidence",
            "source_blueprint_alignment",
            "current_build_context",
            "carry_forward_proposal",
            "next_loop_seed",
        ],
        "blocked": "dependent_context_loop_transition",
        "recovery": "Approve the changed source and recreate Source Evidence and dependent review.",
        "renewed_authorization_required": True,
        "reextraction_required": True,
    },
    "circuit_changed": {
        "explanation": "The approved circuit or QASM changed without a new causal run review.",
        "affected": [
            "circuit_evidence",
            "run_relationship",
            "current_build_context",
            "carry_forward_proposal",
            "next_loop_seed",
        ],
        "blocked": "dependent_context_loop_transition",
        "recovery": "Approve and recreate Circuit Evidence; treat prior Run Evidence as historical until reviewed.",
        "renewed_authorization_required": True,
        "reextraction_required": True,
    },
    "result_changed": {
        "explanation": "The approved result changed after Run Evidence was created.",
        "affected": [
            "run_evidence",
            "result_review",
            "current_build_context",
            "carry_forward_proposal",
            "next_loop_seed",
        ],
        "blocked": "dependent_context_loop_transition",
        "recovery": "Approve the changed result and recreate Run Evidence and dependent review.",
        "renewed_authorization_required": True,
        "reextraction_required": True,
    },
    "governing_blueprint_changed": {
        "explanation": "The governing Blueprint differs from the lineage used by downstream artifacts.",
        "affected": [
            "current_build_context",
            "carry_forward_proposal",
            "unchanged_continuation",
            "next_loop_seed",
        ],
        "blocked": "continuity_transition",
        "recovery": "Use one exact governing Blueprint lineage and recreate dependent artifacts.",
        "renewed_authorization_required": False,
        "reextraction_required": False,
    },
}


class CurrentLoopError(ValueError):
    """Bounded local continuity failure with a stable category."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


class CurrentLoopConflict(CurrentLoopError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def new_loop_ref() -> str:
    return f"loop-{secrets.token_urlsafe(32)}"


def _new_ref(prefix: str) -> str:
    if prefix == "session-artifact":
        return f"session-artifact-{secrets.token_hex(16)}"
    return f"{prefix}-{secrets.token_urlsafe(24)}"


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and bool(_DIGEST_PATTERN.fullmatch(value))


def _bounded_text(value: object, *, category: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurrentLoopError(category)
    result = value.strip()
    if len(result) > maximum:
        raise CurrentLoopError(category)
    return result


def _canonical_size(value: Mapping[str, Any]) -> int:
    return len(canonical_json(value).encode("utf-8"))


def _nested_forbidden_key(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _FORBIDDEN_PORTABLE_KEYS:
                return lowered
            nested = _nested_forbidden_key(item)
            if nested:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            nested = _nested_forbidden_key(item)
            if nested:
                return nested
    return None


def _artifact_digest(value: Mapping[str, Any]) -> str:
    artifact_digest = value.get("artifact_digest")
    if isinstance(artifact_digest, str):
        if not artifact_digest_matches(dict(value)):
            raise CurrentLoopError("canonical_artifact_digest_mismatch")
        return artifact_digest
    supplied_consistency = value.get("consistency_digest")
    if isinstance(supplied_consistency, str):
        if supplied_consistency != consistency_digest(dict(value)):
            raise CurrentLoopError("canonical_artifact_digest_mismatch")
        return supplied_consistency
    raise CurrentLoopError("canonical_artifact_digest_missing")


def _artifact_reference(value: Mapping[str, Any]) -> str:
    candidates = (
        value.get("artifact_ref"),
        value.get("derived_artifact_reference"),
        value.get("proposal_ref"),
        value.get("continuation_ref"),
        value.get("next_loop_seed_ref"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and _ARTIFACT_REF_PATTERN.fullmatch(candidate):
            return candidate
    nested = value.get("artifact_reference")
    if isinstance(nested, Mapping):
        candidate = nested.get("reference_id")
        if isinstance(candidate, str) and _ARTIFACT_REF_PATTERN.fullmatch(candidate):
            return candidate
    digest = _artifact_digest(value)
    return f"session-artifact-{digest[:32]}"


def artifact_descriptor(
    value: Mapping[str, Any], *, role: str, request_field: str | None = None
) -> dict[str, Any]:
    if _nested_forbidden_key(value):
        raise CurrentLoopError("canonical_artifact_prohibited_field")
    result = {
        "artifact_role": _bounded_text(role, category="artifact_role_invalid", maximum=80),
        "artifact_reference": _artifact_reference(value),
        "artifact_digest": _artifact_digest(value),
    }
    if request_field is not None:
        result["request_field"] = _bounded_text(
            request_field, category="request_field_invalid", maximum=80
        )
    artifact_type = value.get("artifact_type") or value.get("section_type")
    if isinstance(artifact_type, str) and artifact_type:
        result["artifact_type"] = artifact_type[:120]
    return result


def decision_inventory_binding(blueprint: Mapping[str, Any]) -> dict[str, Any]:
    packed = blueprint.get("blueprint_decision_records")
    if isinstance(packed, Mapping):
        try:
            records = unpack_decision_record_set(dict(packed))
        except ValueError as exc:
            raise CurrentLoopError(str(exc)) from exc
    else:
        supplied = blueprint.get("decision_records")
        if not isinstance(supplied, list) or not supplied:
            raise CurrentLoopError("blueprint_decision_records_missing")
        records = [deepcopy(item) for item in supplied if isinstance(item, dict)]
        if len(records) != len(supplied):
            raise CurrentLoopError("blueprint_decision_records_invalid")
        for record in records:
            error = decision_record_error(record)
            if error:
                raise CurrentLoopError(error)
    profile = records[0].get("selected_profile")
    if not isinstance(profile, str):
        raise CurrentLoopError("blueprint_decision_profile_missing")
    expected = [item["profile_decision_id"] for item in catalog_entries(profile)]
    actual = [item.get("profile_decision_id") for item in records]
    if actual != expected:
        raise CurrentLoopError("blueprint_decision_inventory_incomplete")
    catalog_binding = records[0].get("contract_binding")
    if not isinstance(catalog_binding, Mapping):
        raise CurrentLoopError("blueprint_decision_catalog_binding_missing")
    expected_catalog = f"{PROFILE_DECISION_CATALOG_ID}@{PROFILE_DECISION_CATALOG_VERSION}"
    if catalog_binding.get("catalog") != expected_catalog:
        raise CurrentLoopError("blueprint_decision_catalog_binding_mismatch")
    return {
        "profile_id": profile,
        "catalog_id": PROFILE_DECISION_CATALOG_ID,
        "catalog_version": PROFILE_DECISION_CATALOG_VERSION,
        "decision_count": len(records),
        "decision_inventory_digest": sha256_bytes(canonical_json(records).encode("utf-8")),
    }


def _descriptor_error(value: object, *, request_field_required: bool = False) -> str | None:
    if not isinstance(value, Mapping):
        return "artifact_descriptor_invalid"
    if not isinstance(value.get("artifact_role"), str):
        return "artifact_role_invalid"
    if not isinstance(value.get("artifact_reference"), str) or not _ARTIFACT_REF_PATTERN.fullmatch(
        value["artifact_reference"]
    ):
        return "canonical_artifact_reference_invalid"
    if not _is_digest(value.get("artifact_digest")):
        return "canonical_artifact_digest_invalid"
    if request_field_required and not isinstance(value.get("request_field"), str):
        return "request_field_invalid"
    return None


def build_loop_instance_record(
    *,
    loop_ref: str,
    generation_posture: str,
    parent_loop_ref: str | None = None,
    label: str | None = None,
    activation_state: str = "active",
    governing_blueprint: Mapping[str, Any] | None = None,
    stage_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    stage_availability: Mapping[str, str] | None = None,
    stage_freshness: Mapping[str, str] | None = None,
    current_build_context: Mapping[str, Any] | None = None,
    continuation_outcome: str = "not_decided",
    changed_decision_references: Sequence[str] = (),
    completion_state: str = "in_progress",
    next_loop_seed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not _LOOP_REF_PATTERN.fullmatch(loop_ref):
        raise CurrentLoopError("loop_ref_invalid")
    if parent_loop_ref is not None and not _LOOP_REF_PATTERN.fullmatch(parent_loop_ref):
        raise CurrentLoopError("parent_loop_ref_invalid")
    if generation_posture not in GENERATION_POSTURES:
        raise CurrentLoopError("generation_posture_invalid")
    if activation_state not in ACTIVATION_STATES:
        raise CurrentLoopError("activation_state_invalid")
    if continuation_outcome not in CONTINUATION_OUTCOMES:
        raise CurrentLoopError("continuation_outcome_invalid")
    if completion_state not in COMPLETION_STATES:
        raise CurrentLoopError("completion_state_invalid")
    if len(changed_decision_references) > MAX_CHANGED_DECISIONS:
        raise CurrentLoopError("changed_decision_references_too_many")
    supplied_stages = stage_artifacts or {}
    if len(supplied_stages) > MAX_STAGE_ARTIFACTS:
        raise CurrentLoopError("stage_artifacts_too_many")
    descriptors = {
        role: artifact_descriptor(artifact, role=role)
        for role, artifact in sorted(supplied_stages.items())
    }
    result: dict[str, Any] = {
        "schema_id": LOOP_INSTANCE_RECORD_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "loop_instance_record",
        "artifact_ref": _new_ref("session-artifact"),
        "loop_ref": loop_ref,
        "parent_loop_ref": parent_loop_ref,
        "activation_state": activation_state,
        "generation_posture": generation_posture,
        "governing_blueprint": (
            artifact_descriptor(governing_blueprint, role="governing_blueprint")
            if governing_blueprint is not None
            else None
        ),
        "decision_inventory_binding": (
            decision_inventory_binding(governing_blueprint)
            if governing_blueprint is not None
            else None
        ),
        "stage_artifacts": descriptors,
        "stage_availability": dict(sorted((stage_availability or {}).items())),
        "stage_freshness": dict(sorted((stage_freshness or {}).items())),
        "current_build_context": (
            artifact_descriptor(current_build_context, role="current_build_context")
            if current_build_context is not None
            else None
        ),
        "continuation_outcome": continuation_outcome,
        "changed_decision_references": list(changed_decision_references),
        "completion_state": completion_state,
        "next_loop_seed": (
            artifact_descriptor(next_loop_seed, role="next_loop_seed")
            if next_loop_seed is not None
            else None
        ),
        "retention": "caller_controlled_local_file",
        "process_and_discard": True,
        "persistent": False,
        "server_lookup": False,
        "graph_traversal": False,
        "project_reopen": False,
        "integrity_proof": False,
    }
    if label is not None:
        result["label"] = _bounded_text(
            label, category="loop_label_invalid", maximum=MAX_LABEL_LENGTH
        )
    result = with_artifact_digest(result)
    error = loop_instance_record_error(result)
    if error:
        raise CurrentLoopError(error)
    return result


def loop_instance_record_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "loop_instance_record_invalid"
    if (
        value.get("schema_id") != LOOP_INSTANCE_RECORD_SCHEMA_ID
        or value.get("schema_version") != 1
        or value.get("artifact_type") != "loop_instance_record"
    ):
        return "loop_instance_record_version_invalid"
    if not artifact_digest_matches(dict(value)):
        return "loop_instance_record_digest_mismatch"
    if not isinstance(value.get("loop_ref"), str) or not _LOOP_REF_PATTERN.fullmatch(
        value["loop_ref"]
    ):
        return "loop_ref_invalid"
    parent = value.get("parent_loop_ref")
    if parent is not None and (
        not isinstance(parent, str) or not _LOOP_REF_PATTERN.fullmatch(parent)
    ):
        return "parent_loop_ref_invalid"
    if value.get("generation_posture") not in GENERATION_POSTURES:
        return "generation_posture_invalid"
    if value.get("activation_state") not in ACTIVATION_STATES:
        return "activation_state_invalid"
    if value.get("completion_state") not in COMPLETION_STATES:
        return "completion_state_invalid"
    if value.get("continuation_outcome") not in CONTINUATION_OUTCOMES:
        return "continuation_outcome_invalid"
    stages = value.get("stage_artifacts")
    if not isinstance(stages, Mapping) or len(stages) > MAX_STAGE_ARTIFACTS:
        return "stage_artifacts_invalid"
    for descriptor in stages.values():
        error = _descriptor_error(descriptor)
        if error:
            return error
    governing = value.get("governing_blueprint")
    if governing is not None and _descriptor_error(governing):
        return "loop_instance_record_governing_blueprint_invalid"
    binding = value.get("decision_inventory_binding")
    if governing is None and binding is not None:
        return "loop_instance_record_inventory_without_blueprint"
    if governing is not None and (
        not isinstance(binding, Mapping)
        or not isinstance(binding.get("decision_count"), int)
        or binding["decision_count"] < 1
        or not _is_digest(binding.get("decision_inventory_digest"))
    ):
        return "loop_instance_record_inventory_binding_invalid"
    current = value.get("current_build_context")
    if current is not None and _descriptor_error(current):
        return "loop_instance_record_current_build_context_invalid"
    seed = value.get("next_loop_seed")
    if seed is not None and _descriptor_error(seed):
        return "loop_instance_record_seed_invalid"
    if value.get("persistent") is not False or value.get("server_lookup") is not False:
        return "loop_instance_record_boundary_invalid"
    if value.get("graph_traversal") is not False or value.get("project_reopen") is not False:
        return "loop_instance_record_boundary_invalid"
    if _nested_forbidden_key(value):
        return "loop_instance_record_prohibited_field"
    if _canonical_size(value) > LOOP_INSTANCE_RECORD_MAX_BYTES:
        return "loop_instance_record_too_large"
    return None


def build_next_loop_seed(
    *,
    source_loop_ref: str,
    continuation_outcome: str,
    governing_blueprint: Mapping[str, Any],
    required_parent_artifacts: Mapping[str, tuple[str, Mapping[str, Any]] | Mapping[str, Any]],
    next_permitted_operation_family: str,
    continuation_artifact_reference: str | None = None,
) -> dict[str, Any]:
    if not _LOOP_REF_PATTERN.fullmatch(source_loop_ref):
        raise CurrentLoopError("loop_ref_invalid")
    if continuation_outcome not in {
        "unchanged_continuation",
        "confirmed_change",
    }:
        raise CurrentLoopError("continuation_outcome_invalid")
    if next_permitted_operation_family not in PERMITTED_CONTINUITY_OPERATION_FAMILIES:
        raise CurrentLoopError("next_permitted_operation_invalid")
    if not required_parent_artifacts or len(required_parent_artifacts) > MAX_REQUIRED_PARENTS:
        raise CurrentLoopError("next_loop_seed_parent_inventory_invalid")
    descriptors = []
    for role, supplied in sorted(required_parent_artifacts.items()):
        if (
            isinstance(supplied, tuple)
            and len(supplied) == 2
            and isinstance(supplied[0], str)
            and isinstance(supplied[1], Mapping)
        ):
            request_field, artifact = supplied
        elif isinstance(supplied, Mapping):
            request_field, artifact = role, supplied
        else:
            raise CurrentLoopError("next_loop_seed_parent_inventory_invalid")
        descriptors.append(artifact_descriptor(artifact, role=role, request_field=request_field))
    result: dict[str, Any] = {
        "schema_id": NEXT_LOOP_SEED_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "next_loop_seed",
        "artifact_ref": _new_ref("seed"),
        "source_loop_ref": source_loop_ref,
        "continuation_outcome": continuation_outcome,
        "governing_blueprint": artifact_descriptor(governing_blueprint, role="governing_blueprint"),
        "decision_inventory_binding": decision_inventory_binding(governing_blueprint),
        "required_parent_artifact_inventory": descriptors,
        "next_permitted_operation_family": _bounded_text(
            next_permitted_operation_family,
            category="next_permitted_operation_invalid",
            maximum=100,
        ),
        "retention": "caller_controlled_portable_file",
        "process_and_discard": True,
        "persistent": False,
        "server_lookup": False,
        "project_reopen": False,
        "graph_traversal": False,
        "freshness_proof": False,
        "authorization_credential": False,
    }
    if continuation_artifact_reference is not None:
        if not _ARTIFACT_REF_PATTERN.fullmatch(continuation_artifact_reference):
            raise CurrentLoopError("continuation_artifact_reference_invalid")
        result["continuation_artifact_reference"] = continuation_artifact_reference
    result = with_artifact_digest(result)
    error = next_loop_seed_error(result)
    if error:
        raise CurrentLoopError(error)
    return result


def next_loop_seed_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "next_loop_seed_invalid"
    if (
        value.get("schema_id") != NEXT_LOOP_SEED_SCHEMA_ID
        or value.get("schema_version") != 1
        or value.get("artifact_type") != "next_loop_seed"
    ):
        return "next_loop_seed_version_invalid"
    if not artifact_digest_matches(dict(value)):
        return "next_loop_seed_digest_mismatch"
    if not isinstance(value.get("source_loop_ref"), str) or not _LOOP_REF_PATTERN.fullmatch(
        value["source_loop_ref"]
    ):
        return "loop_ref_invalid"
    if value.get("continuation_outcome") not in {
        "unchanged_continuation",
        "confirmed_change",
    }:
        return "continuation_outcome_invalid"
    if value.get("next_permitted_operation_family") not in PERMITTED_CONTINUITY_OPERATION_FAMILIES:
        return "next_permitted_operation_invalid"
    inventory = value.get("required_parent_artifact_inventory")
    if not isinstance(inventory, list) or not inventory or len(inventory) > MAX_REQUIRED_PARENTS:
        return "next_loop_seed_parent_inventory_invalid"
    roles = []
    fields = []
    for descriptor in inventory:
        error = _descriptor_error(descriptor, request_field_required=True)
        if error:
            return error
        roles.append(descriptor["artifact_role"])
        fields.append(descriptor["request_field"])
    if len(roles) != len(set(roles)) or len(fields) != len(set(fields)):
        return "next_loop_seed_parent_inventory_duplicate"
    if _descriptor_error(value.get("governing_blueprint")):
        return "next_loop_seed_governing_blueprint_invalid"
    binding = value.get("decision_inventory_binding")
    if (
        not isinstance(binding, Mapping)
        or not isinstance(binding.get("decision_count"), int)
        or binding["decision_count"] < 1
        or not _is_digest(binding.get("decision_inventory_digest"))
    ):
        return "next_loop_seed_inventory_binding_invalid"
    for key in ("persistent", "server_lookup", "project_reopen", "graph_traversal"):
        if value.get(key) is not False:
            return "next_loop_seed_boundary_invalid"
    if _nested_forbidden_key(value):
        return "next_loop_seed_prohibited_field"
    if _canonical_size(value) > NEXT_LOOP_SEED_MAX_BYTES:
        return "next_loop_seed_too_large"
    return None


def build_unchanged_continuation(
    *,
    loop_instance_record: Mapping[str, Any],
    governing_working_blueprint: Mapping[str, Any],
    retained_evidence: Mapping[str, Mapping[str, Any]],
    explicit_user_action: Mapping[str, Any],
    required_parent_artifacts: Mapping[str, tuple[str, Mapping[str, Any]] | Mapping[str, Any]],
    next_permitted_operation_family: str,
    unadopted_proposal: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    error = loop_instance_record_error(loop_instance_record)
    if error:
        raise CurrentLoopError(error)
    if explicit_user_action.get("confirmed") is not True or explicit_user_action.get(
        "provenance"
    ) not in {"direct_user_action", "explicit_api_authority"}:
        raise CurrentLoopError("unchanged_continuation_explicit_action_required")
    statement = _bounded_text(
        explicit_user_action.get("statement"),
        category="unchanged_continuation_statement_required",
        maximum=500,
    )
    governing = artifact_descriptor(governing_working_blueprint, role="governing_blueprint")
    existing_governing = loop_instance_record.get("governing_blueprint")
    if isinstance(existing_governing, Mapping) and dict(existing_governing) != governing:
        raise CurrentLoopError("governing_blueprint_mismatch")
    continuation_ref = _new_ref("continuation")
    seed = build_next_loop_seed(
        source_loop_ref=str(loop_instance_record["loop_ref"]),
        continuation_outcome="unchanged_continuation",
        governing_blueprint=governing_working_blueprint,
        required_parent_artifacts=required_parent_artifacts,
        next_permitted_operation_family=next_permitted_operation_family,
        continuation_artifact_reference=continuation_ref,
    )
    proposal_descriptor = (
        artifact_descriptor(unadopted_proposal, role="unadopted_proposal")
        if unadopted_proposal is not None
        else None
    )
    if unadopted_proposal is not None:
        proposal_state = unadopted_proposal.get("proposal_state")
        if proposal_state not in {None, "unconfirmed", "declined"}:
            raise CurrentLoopError("unchanged_continuation_proposal_already_adopted")
        if (
            unadopted_proposal.get("confirmed") is True
            or unadopted_proposal.get("derived_artifact_materialized") is True
        ):
            raise CurrentLoopError("unchanged_continuation_proposal_already_adopted")
    continuation = {
        "schema_id": UNCHANGED_CONTINUATION_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "unchanged_continuation",
        "artifact_ref": continuation_ref,
        "explicit_user_action": {
            "confirmed": True,
            "provenance": explicit_user_action["provenance"],
            "statement": statement,
        },
        "source_loop_ref": loop_instance_record["loop_ref"],
        "governing_working_blueprint": governing,
        "decision_inventory_binding": decision_inventory_binding(governing_working_blueprint),
        "retained_evidence": [
            artifact_descriptor(artifact, role=role)
            for role, artifact in sorted(retained_evidence.items())
        ],
        "governing_decisions_changed": False,
        "evolved_blueprint_created": False,
        "proposal_adopted": False,
        "unadopted_proposal": proposal_descriptor,
        "continuation_outcome": "unchanged_continuation",
        "next_loop_seed": artifact_descriptor(seed, role="next_loop_seed"),
        "retention": "caller_controlled_portable_file",
        "process_and_discard": True,
        "persistent": False,
        "server_lookup": False,
    }
    continuation = with_artifact_digest(continuation)
    continuation_error = unchanged_continuation_error(continuation)
    if continuation_error:
        raise CurrentLoopError(continuation_error)
    return {
        "unchanged_continuation": continuation,
        "next_loop_seed": seed,
    }


def unchanged_continuation_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "unchanged_continuation_invalid"
    if (
        value.get("schema_id") != UNCHANGED_CONTINUATION_SCHEMA_ID
        or value.get("schema_version") != 1
        or value.get("artifact_type") != "unchanged_continuation"
    ):
        return "unchanged_continuation_version_invalid"
    if not artifact_digest_matches(dict(value)):
        return "unchanged_continuation_digest_mismatch"
    action = value.get("explicit_user_action")
    if (
        not isinstance(action, Mapping)
        or action.get("confirmed") is not True
        or action.get("provenance") not in {"direct_user_action", "explicit_api_authority"}
    ):
        return "unchanged_continuation_explicit_action_required"
    required_false = (
        "governing_decisions_changed",
        "evolved_blueprint_created",
        "proposal_adopted",
        "persistent",
        "server_lookup",
    )
    if any(value.get(key) is not False for key in required_false):
        return "unchanged_continuation_boundary_invalid"
    if value.get("continuation_outcome") != "unchanged_continuation":
        return "continuation_outcome_invalid"
    if _descriptor_error(value.get("governing_working_blueprint")):
        return "unchanged_continuation_governing_blueprint_invalid"
    if _descriptor_error(value.get("next_loop_seed")):
        return "unchanged_continuation_seed_invalid"
    if _nested_forbidden_key(value):
        return "unchanged_continuation_prohibited_field"
    if _canonical_size(value) > NEXT_LOOP_SEED_MAX_BYTES:
        return "unchanged_continuation_too_large"
    return None


def build_changed_next_loop_seed(
    *,
    source_loop_ref: str,
    evolved_blueprint: Mapping[str, Any],
    required_parent_artifacts: Mapping[str, tuple[str, Mapping[str, Any]] | Mapping[str, Any]],
    next_permitted_operation_family: str,
) -> dict[str, Any]:
    if evolved_blueprint.get("artifact_type") != "evolved_blueprint":
        raise CurrentLoopError("evolved_blueprint_required")
    provenance = evolved_blueprint.get("provenance_entries")
    if not isinstance(provenance, list) or not any(
        isinstance(item, Mapping) and item.get("role") == "user_confirmed_carry_forward"
        for item in provenance
    ):
        raise CurrentLoopError("evolved_blueprint_confirmation_provenance_missing")
    if (
        evolved_blueprint.get("parent_mutated") is not False
        or evolved_blueprint.get("hidden_lookup_performed") is not False
    ):
        raise CurrentLoopError("evolved_blueprint_boundary_invalid")
    return build_next_loop_seed(
        source_loop_ref=source_loop_ref,
        continuation_outcome="confirmed_change",
        governing_blueprint=evolved_blueprint,
        required_parent_artifacts=required_parent_artifacts,
        next_permitted_operation_family=next_permitted_operation_family,
        continuation_artifact_reference=_artifact_reference(evolved_blueprint),
    )


def _normalize_selected_item(item: Mapping[str, Any], *, bind_content: bool) -> dict[str, Any]:
    role = item.get("artifact_role")
    if role not in AUTHORIZED_ARTIFACT_ROLES:
        raise CurrentLoopError("selected_artifact_role_invalid")
    supplied_path = item.get("local_path")
    if not isinstance(supplied_path, (str, Path)):
        raise CurrentLoopError("selected_artifact_path_invalid")
    path = Path(supplied_path).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise CurrentLoopError("selected_artifact_path_invalid")
    result: dict[str, Any] = {
        "artifact_role": role,
        "artifact_type": _bounded_text(
            item.get("artifact_type") or role,
            category="selected_artifact_type_invalid",
            maximum=100,
        ),
        "local_path": str(path),
    }
    if not bind_content:
        result["content_digest"] = None
        result["size_bytes"] = None
        return result
    stat_result, content_digest = _safe_local_file_digest(path, maximum_bytes=MAX_LOCAL_FILE_BYTES)
    result["content_digest"] = content_digest
    result["size_bytes"] = stat_result.st_size
    return result


def _approved_set_digest(items: Sequence[Mapping[str, Any]]) -> str:
    share_safe = [
        {
            "artifact_role": item["artifact_role"],
            "artifact_type": item["artifact_type"],
            "content_digest": item["content_digest"],
            "size_bytes": item["size_bytes"],
        }
        for item in sorted(items, key=lambda value: (value["artifact_role"], value["local_path"]))
    ]
    return sha256_bytes(canonical_json(share_safe).encode("utf-8"))


def propose_selected_artifact_authorization(
    *,
    loop_ref: str,
    proposed_artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not _LOOP_REF_PATTERN.fullmatch(loop_ref):
        raise CurrentLoopError("loop_ref_invalid")
    if not proposed_artifacts or len(proposed_artifacts) > MAX_AUTHORIZED_ARTIFACTS:
        raise CurrentLoopError("selected_artifact_set_invalid")
    items = [_normalize_selected_item(item, bind_content=False) for item in proposed_artifacts]
    paths = [item["local_path"] for item in items]
    if len(paths) != len(set(paths)):
        raise CurrentLoopError("selected_artifact_duplicate_path")
    return {
        "schema_id": SELECTED_ARTIFACT_AUTHORIZATION_SCHEMA_ID,
        "schema_version": 1,
        "artifact_type": "selected_artifact_authorization",
        "authorization_ref": _new_ref("authorization"),
        "loop_ref": loop_ref,
        "state": "proposed",
        "items": items,
        "approval_action": None,
        "explicit_action_provenance": None,
        "approved_set_digest": None,
        "local_only": True,
        "paths_share_safe": False,
        "artifact_review_authority_only": True,
        "ide_write_authorized": False,
        "ide_execution_authorized": False,
        "other_file_inspection_authorized": False,
    }


def update_selected_artifact_authorization(
    authorization: Mapping[str, Any],
    *,
    action: str,
    explicit_action_provenance: str,
    selected_path: str | Path | None = None,
    artifact_role: str | None = None,
    artifact_type: str | None = None,
) -> dict[str, Any]:
    error = selected_artifact_authorization_error(authorization)
    if error:
        raise CurrentLoopError(error)
    if authorization.get("state") not in {"proposed", "stale"}:
        raise CurrentLoopError("selected_artifact_authorization_final")
    provenance = _bounded_text(
        explicit_action_provenance,
        category="selected_artifact_explicit_action_required",
        maximum=160,
    )
    result = deepcopy(dict(authorization))
    items = deepcopy(result["items"])
    if action == "remove_one":
        if selected_path is None:
            raise CurrentLoopError("selected_artifact_path_required")
        exact = str(Path(selected_path).expanduser())
        filtered = [item for item in items if item["local_path"] != exact]
        if len(filtered) == len(items) or not filtered:
            raise CurrentLoopError("selected_artifact_remove_invalid")
        result["items"] = filtered
        result["state"] = "proposed"
        result["approval_action"] = action
        result["explicit_action_provenance"] = provenance
    elif action == "add_one_explicitly":
        if selected_path is None or artifact_role is None:
            raise CurrentLoopError("selected_artifact_add_invalid")
        new_item = _normalize_selected_item(
            {
                "local_path": selected_path,
                "artifact_role": artifact_role,
                "artifact_type": artifact_type or artifact_role,
            },
            bind_content=False,
        )
        if any(item["local_path"] == new_item["local_path"] for item in items):
            raise CurrentLoopError("selected_artifact_duplicate_path")
        if len(items) >= MAX_AUTHORIZED_ARTIFACTS:
            raise CurrentLoopError("selected_artifact_set_invalid")
        result["items"] = items + [new_item]
        result["state"] = "proposed"
        result["approval_action"] = action
        result["explicit_action_provenance"] = provenance
    elif action == "decline":
        result["state"] = "declined"
        result["approval_action"] = action
        result["explicit_action_provenance"] = provenance
        result["approved_set_digest"] = None
    elif action == "approve_all":
        bound = [_normalize_selected_item(item, bind_content=True) for item in items]
        result["items"] = bound
        result["state"] = "approved"
        result["approval_action"] = action
        result["explicit_action_provenance"] = provenance
        result["approved_set_digest"] = _approved_set_digest(bound)
    else:
        raise CurrentLoopError("selected_artifact_action_invalid")
    return result


def selected_artifact_authorization_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "selected_artifact_authorization_invalid"
    if (
        value.get("schema_id") != SELECTED_ARTIFACT_AUTHORIZATION_SCHEMA_ID
        or value.get("schema_version") != 1
        or value.get("artifact_type") != "selected_artifact_authorization"
    ):
        return "selected_artifact_authorization_version_invalid"
    if not isinstance(value.get("authorization_ref"), str) or not _AUTH_REF_PATTERN.fullmatch(
        value["authorization_ref"]
    ):
        return "selected_artifact_authorization_ref_invalid"
    if not isinstance(value.get("loop_ref"), str) or not _LOOP_REF_PATTERN.fullmatch(
        value["loop_ref"]
    ):
        return "loop_ref_invalid"
    if value.get("state") not in AUTHORIZATION_STATES:
        return "selected_artifact_authorization_state_invalid"
    items = value.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_AUTHORIZED_ARTIFACTS:
        return "selected_artifact_set_invalid"
    seen = set()
    for item in items:
        if not isinstance(item, Mapping):
            return "selected_artifact_item_invalid"
        if item.get("artifact_role") not in AUTHORIZED_ARTIFACT_ROLES:
            return "selected_artifact_role_invalid"
        path = item.get("local_path")
        if not isinstance(path, str) or not Path(path).is_absolute() or ".." in Path(path).parts:
            return "selected_artifact_path_invalid"
        if path in seen:
            return "selected_artifact_duplicate_path"
        seen.add(path)
        if value.get("state") == "approved":
            if not _is_digest(item.get("content_digest")):
                return "selected_artifact_content_digest_missing"
            if not isinstance(item.get("size_bytes"), int):
                return "selected_artifact_size_missing"
    if value.get("state") == "approved":
        expected = _approved_set_digest(items)
        if value.get("approved_set_digest") != expected:
            return "selected_artifact_approved_set_digest_mismatch"
    required_false = (
        "paths_share_safe",
        "ide_write_authorized",
        "ide_execution_authorized",
        "other_file_inspection_authorized",
    )
    if any(value.get(key) is not False for key in required_false):
        return "selected_artifact_authority_boundary_invalid"
    return None


def share_safe_artifact_authorization_projection(
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    error = selected_artifact_authorization_error(authorization)
    if error:
        raise CurrentLoopError(error)
    return {
        "schema_id": "qcoder.selected_artifact_authorization.share_safe.v1",
        "schema_version": 1,
        "authorization_ref": authorization["authorization_ref"],
        "loop_ref": authorization["loop_ref"],
        "state": authorization["state"],
        "artifact_count": len(authorization["items"]),
        "artifacts": [
            {
                "artifact_role": item["artifact_role"],
                "artifact_type": item["artifact_type"],
                "content_digest": item.get("content_digest"),
                "size_bytes": item.get("size_bytes"),
            }
            for item in authorization["items"]
        ],
        "authorization_state_digest": sha256_bytes(
            canonical_json(
                {
                    "authorization_ref": authorization["authorization_ref"],
                    "state": authorization["state"],
                    "approved_set_digest": authorization.get("approved_set_digest"),
                }
            ).encode("utf-8")
        ),
        "local_paths_included": False,
    }


def _symlink_component(path: Path) -> Path | None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return current
        except OSError:
            return current
    return None


def _safe_local_file_digest(path: Path, *, maximum_bytes: int) -> tuple[os.stat_result, str]:
    if not path.is_absolute() or ".." in path.parts:
        raise CurrentLoopError("local_file_path_invalid")
    if _symlink_component(path) is not None:
        raise CurrentLoopError("local_file_symlink_rejected")
    try:
        stat_before = path.stat()
    except OSError as exc:
        raise CurrentLoopError("local_file_missing") from exc
    if not path.is_file():
        raise CurrentLoopError("local_file_required")
    if stat_before.st_size > maximum_bytes:
        raise CurrentLoopError("local_file_too_large")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(65_536)
                if not chunk:
                    break
                digest.update(chunk)
        stat_after = path.stat()
    except OSError as exc:
        raise CurrentLoopError("local_file_unreadable") from exc
    if (
        stat_before.st_size != stat_after.st_size
        or stat_before.st_mtime_ns != stat_after.st_mtime_ns
    ):
        raise CurrentLoopError("local_file_changed_during_read")
    return stat_after, digest.hexdigest()


def _validate_state_path(
    state_path: Path, *, workspace_root: Path, explicit_external: bool
) -> None:
    if not state_path.is_absolute() or ".." in state_path.parts:
        raise CurrentLoopError("current_loop_state_path_invalid")
    expected = workspace_root / ".qcoder" / "current-loop" / "state.json"
    if not explicit_external and state_path != expected:
        raise CurrentLoopError("current_loop_external_state_requires_explicit_selection")
    if _symlink_component(state_path.parent) is not None:
        raise CurrentLoopError("current_loop_state_symlink_rejected")


def _apply_private_permissions(path: Path, *, directory: bool) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    # Native Windows inherits the explicitly selected directory ACL. Python's
    # chmod does not provide a complete owner-only ACL contract.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _atomic_write_bytes(path: Path, payload: bytes, *, maximum_bytes: int) -> None:
    if len(payload) > maximum_bytes:
        raise CurrentLoopError("local_state_or_artifact_too_large")
    path.parent.mkdir(parents=True, exist_ok=True)
    _apply_private_permissions(path.parent, directory=True)
    if _symlink_component(path.parent) is not None or path.is_symlink():
        raise CurrentLoopError("local_file_symlink_rejected")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        _apply_private_permissions(temporary, directory=False)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _apply_private_permissions(path, directory=False)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class CurrentLoopStore:
    """Single-file, inspectable current-loop state with bounded CAS updates."""

    def __init__(
        self,
        *,
        state_path: str | Path,
        workspace_root: str | Path,
        explicit_external: bool = False,
        lock_timeout_seconds: float = 2.0,
    ):
        self.state_path = Path(state_path).expanduser().absolute()
        self.workspace_root = Path(workspace_root).expanduser().absolute()
        self.explicit_external = explicit_external
        self.lock_timeout_seconds = lock_timeout_seconds
        _validate_state_path(
            self.state_path,
            workspace_root=self.workspace_root,
            explicit_external=explicit_external,
        )

    @classmethod
    def for_workspace(
        cls, workspace_root: str | Path, *, lock_timeout_seconds: float = 2.0
    ) -> "CurrentLoopStore":
        workspace = Path(workspace_root).expanduser().absolute()
        return cls(
            state_path=workspace / ".qcoder" / "current-loop" / "state.json",
            workspace_root=workspace,
            lock_timeout_seconds=lock_timeout_seconds,
        )

    @property
    def lock_path(self) -> Path:
        return self.state_path.with_name(f"{self.state_path.name}.lock")

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _apply_private_permissions(self.state_path.parent, directory=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise CurrentLoopConflict("current_loop_lock_timeout")
                time.sleep(0.025)
        try:
            os.write(descriptor, b'{"schema_version":1,"single_writer":true}\n')
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            _apply_private_permissions(self.lock_path, directory=False)
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def read(self) -> dict[str, Any]:
        if self.state_path.is_symlink() or _symlink_component(self.state_path.parent):
            raise CurrentLoopError("current_loop_state_symlink_rejected")
        try:
            raw = self.state_path.read_bytes()
        except FileNotFoundError as exc:
            raise CurrentLoopError("current_loop_not_active") from exc
        except OSError as exc:
            raise CurrentLoopError("current_loop_state_unreadable") from exc
        if len(raw) > CURRENT_LOOP_STATE_MAX_BYTES:
            raise CurrentLoopError("current_loop_state_too_large")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CurrentLoopError("current_loop_state_corrupt") from exc
        error = current_loop_state_error(value)
        if error:
            raise CurrentLoopError(error)
        return value

    def create(self, state: Mapping[str, Any]) -> dict[str, Any]:
        error = current_loop_state_error(state)
        if error:
            raise CurrentLoopError(error)
        with self.lock():
            if self.state_path.exists():
                raise CurrentLoopConflict("current_loop_already_active")
            _atomic_write_bytes(
                self.state_path,
                canonical_bytes(state),
                maximum_bytes=CURRENT_LOOP_STATE_MAX_BYTES,
            )
        return deepcopy(dict(state))

    def replace(
        self,
        state: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        with self.lock():
            current = self.read()
            if current["state_revision"] != expected_revision:
                raise CurrentLoopConflict("concurrent_state_update")
            result = deepcopy(dict(state))
            result["state_revision"] = expected_revision + 1
            result["state_digest"] = _state_digest(result)
            error = current_loop_state_error(result)
            if error:
                raise CurrentLoopError(error)
            _atomic_write_bytes(
                self.state_path,
                canonical_bytes(result),
                maximum_bytes=CURRENT_LOOP_STATE_MAX_BYTES,
            )
        return result

    def update(
        self,
        mutator: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        current = self.read()
        if current["state_revision"] != expected_revision:
            raise CurrentLoopConflict("concurrent_state_update")
        return self.replace(mutator(deepcopy(current)), expected_revision=expected_revision)

    def delete_state(self, *, explicit_authority: bool) -> dict[str, Any]:
        if explicit_authority is not True:
            raise CurrentLoopError("current_loop_delete_authority_required")
        with self.lock():
            state = self.read()
            try:
                self.state_path.unlink()
            except OSError as exc:
                raise CurrentLoopError("current_loop_state_delete_failed") from exc
        return {
            "deleted": True,
            "state_path": str(self.state_path),
            "source_artifacts_deleted": False,
            "saved_qcoder_artifacts_deleted": False,
            "protected_deletion_required": False,
            "loop_ref": state["loop_ref"],
        }


def _state_digest(value: Mapping[str, Any]) -> str:
    projected = {key: deepcopy(item) for key, item in value.items() if key != "state_digest"}
    return sha256_bytes(canonical_json(projected).encode("utf-8"))


def current_loop_state_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "current_loop_state_invalid"
    if value.get("schema_id") != CURRENT_LOOP_STATE_SCHEMA_ID or value.get("schema_version") != 1:
        return "current_loop_state_version_invalid"
    if not isinstance(value.get("state_revision"), int) or value["state_revision"] < 1:
        return "current_loop_state_revision_invalid"
    if value.get("state_digest") != _state_digest(value):
        return "current_loop_state_digest_mismatch"
    if not isinstance(value.get("loop_ref"), str) or not _LOOP_REF_PATTERN.fullmatch(
        value["loop_ref"]
    ):
        return "loop_ref_invalid"
    workspace = value.get("workspace_root")
    if not isinstance(workspace, str) or not Path(workspace).is_absolute():
        return "current_loop_workspace_invalid"
    if value.get("generation_posture") not in GENERATION_POSTURES:
        return "generation_posture_invalid"
    if value.get("activation_state") not in ACTIVATION_STATES:
        return "activation_state_invalid"
    if not isinstance(value.get("saved_artifacts"), Mapping):
        return "current_loop_saved_artifacts_invalid"
    if not isinstance(value.get("stage_freshness"), Mapping):
        return "current_loop_freshness_invalid"
    if value.get("persistent") is not False:
        return "current_loop_state_boundary_invalid"
    if value.get("server_lookup") is not False or value.get("automatic_reopen") is not False:
        return "current_loop_state_boundary_invalid"
    if _canonical_size(value) > CURRENT_LOOP_STATE_MAX_BYTES:
        return "current_loop_state_too_large"
    return None


def activate_current_loop(
    *,
    workspace_root: str | Path,
    generation_posture: str,
    explicit_authority: bool,
    parent_loop_ref: str | None = None,
    label: str | None = None,
    external_state_path: str | Path | None = None,
    governing_blueprint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if explicit_authority is not True:
        raise CurrentLoopError("current_loop_activation_authority_required")
    workspace = Path(workspace_root).expanduser().absolute()
    if not workspace.exists() or not workspace.is_dir():
        raise CurrentLoopError("current_loop_workspace_invalid")
    if workspace.is_symlink():
        raise CurrentLoopError("current_loop_workspace_symlink_rejected")
    explicit_external = external_state_path is not None
    state_path = (
        Path(external_state_path).expanduser().absolute()
        if external_state_path is not None
        else workspace / ".qcoder" / "current-loop" / "state.json"
    )
    store = CurrentLoopStore(
        state_path=state_path,
        workspace_root=workspace,
        explicit_external=explicit_external,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _apply_private_permissions(state_path.parent, directory=True)
    if not explicit_external:
        _apply_private_permissions(workspace / ".qcoder", directory=True)
    loop_ref = new_loop_ref()
    record = build_loop_instance_record(
        loop_ref=loop_ref,
        parent_loop_ref=parent_loop_ref,
        generation_posture=generation_posture,
        label=label,
        governing_blueprint=governing_blueprint,
    )
    record_path = state_path.with_name(f"loop-instance-record-{loop_ref}.json")
    if record_path.exists():
        raise CurrentLoopConflict("current_loop_record_already_exists")
    _atomic_write_bytes(
        record_path,
        canonical_bytes(record),
        maximum_bytes=LOOP_INSTANCE_RECORD_MAX_BYTES,
    )
    state: dict[str, Any] = {
        "schema_id": CURRENT_LOOP_STATE_SCHEMA_ID,
        "schema_version": 1,
        "state_revision": 1,
        "loop_ref": loop_ref,
        "parent_loop_ref": parent_loop_ref,
        "workspace_root": str(workspace),
        "state_location_explicitly_selected": explicit_external,
        "generation_posture": generation_posture,
        "activation_state": "active",
        "completion_state": "in_progress",
        "artifact_authorization": None,
        "selected_artifacts": {},
        "extraction_status": {},
        "saved_artifacts": {},
        "stage_freshness": {},
        "freshness_events": [],
        "next_operation": None,
        "loop_instance_record_path": str(record_path),
        "loop_instance_record_digest": record["artifact_digest"],
        "continuation_path": None,
        "next_loop_seed_path": None,
        "directory_scan_performed": False,
        "watcher_active": False,
        "upload_performed": False,
        "automatic_git_commit": False,
        "automatic_gitignore_edit": False,
        "automatic_reopen": False,
        "server_lookup": False,
        "persistent": False,
    }
    state["state_digest"] = _state_digest(state)
    try:
        store.create(state)
    except Exception:
        try:
            record_path.unlink()
        except OSError:
            pass
        raise
    return {
        "state": state,
        "loop_instance_record": record,
        "state_path": str(state_path),
        "loop_instance_record_path": str(record_path),
    }


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    return True


def save_exact_canonical_artifact(
    *,
    store: CurrentLoopStore,
    role: str,
    artifact: Mapping[str, Any],
    destination: str | Path,
    expected_revision: int,
) -> dict[str, Any]:
    if role not in _CANONICAL_ARTIFACT_ROLES:
        raise CurrentLoopError("canonical_artifact_role_invalid")
    artifact_value = deepcopy(dict(artifact))
    digest = _artifact_digest(artifact_value)
    path = Path(destination).expanduser().absolute()
    if not _path_within(path, store.workspace_root):
        raise CurrentLoopError("canonical_artifact_path_escape")
    if _symlink_component(path.parent) is not None or path.is_symlink():
        raise CurrentLoopError("canonical_artifact_symlink_rejected")
    payload = canonical_bytes(artifact_value)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise CurrentLoopError("canonical_artifact_unreadable") from exc
        if existing != payload:
            raise CurrentLoopError("canonical_artifact_overwrite_conflict")
    else:
        _atomic_write_bytes(path, payload, maximum_bytes=MAX_LOCAL_FILE_BYTES)
    try:
        reloaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CurrentLoopError("canonical_artifact_save_verification_failed") from exc
    if reloaded != artifact_value or _artifact_digest(reloaded) != digest:
        raise CurrentLoopError("canonical_artifact_save_verification_failed")
    file_digest = sha256_bytes(path.read_bytes())

    def mutator(state: dict[str, Any]) -> Mapping[str, Any]:
        existing = state["saved_artifacts"].get(role)
        descriptor = {
            "local_path": str(path),
            "artifact_reference": _artifact_reference(artifact_value),
            "artifact_digest": digest,
            "file_digest": file_digest,
            "status": "fresh",
        }
        if existing is not None and existing != descriptor:
            raise CurrentLoopError("canonical_artifact_role_already_bound")
        state["saved_artifacts"][role] = descriptor
        state["stage_freshness"][role] = "fresh"
        return state

    updated = store.update(mutator, expected_revision=expected_revision)
    return {
        "saved": True,
        "role": role,
        "path": str(path),
        "artifact_digest": digest,
        "file_digest": file_digest,
        "state_revision": updated["state_revision"],
        "wrapper_added": False,
        "notes_added": False,
    }


def _read_saved_artifact(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(descriptor.get("local_path") or ""))
    value = _load_exact_json_file(
        path,
        maximum_bytes=MAX_LOCAL_FILE_BYTES,
        missing_category="canonical_artifact_missing",
        invalid_category="canonical_artifact_invalid",
    )
    if _artifact_digest(value) != descriptor.get("artifact_digest") or sha256_bytes(
        path.read_bytes()
    ) != descriptor.get("file_digest"):
        raise CurrentLoopError("canonical_artifact_modified")
    return value


def refresh_loop_instance_record(
    *,
    store: CurrentLoopStore,
    expected_revision: int,
    explicit_authority: bool,
    changed_decision_references: Sequence[str] = (),
) -> dict[str, Any]:
    if explicit_authority is not True:
        raise CurrentLoopError("loop_instance_record_refresh_authority_required")
    state = store.read()
    if state["state_revision"] != expected_revision:
        raise CurrentLoopConflict("concurrent_state_update")
    loaded = {
        role: _read_saved_artifact(descriptor)
        for role, descriptor in state["saved_artifacts"].items()
    }
    governing = loaded.get("evolved_blueprint") or loaded.get("working_blueprint")
    stage_roles = {
        key: loaded[key]
        for key in (
            "request_baseline",
            "algorithm_intent_card",
            "output_evidence_contract",
            "generation_context_pack",
            "python_manifestation",
            "circuit_manifestation",
            "result_manifestation",
            "source_evidence",
            "source_blueprint_alignment",
            "result_review_context_card",
            "carry_forward_proposal",
            "unchanged_continuation",
        )
        if key in loaded
    }
    seed = loaded.get("next_loop_seed")
    completion = state["completion_state"]
    continuation_outcome = {
        "completed_unchanged": "unchanged_continuation",
        "completed_changed": "confirmed_change",
        "abandoned": "abandoned",
    }.get(completion, "not_decided")
    record = build_loop_instance_record(
        loop_ref=state["loop_ref"],
        parent_loop_ref=state.get("parent_loop_ref"),
        generation_posture=state["generation_posture"],
        activation_state=state["activation_state"],
        governing_blueprint=governing,
        stage_artifacts=stage_roles,
        stage_availability={role: "available" for role in sorted(stage_roles)},
        stage_freshness=state["stage_freshness"],
        current_build_context=loaded.get("current_build_context"),
        continuation_outcome=continuation_outcome,
        changed_decision_references=changed_decision_references,
        completion_state=completion,
        next_loop_seed=seed,
    )
    record_path = Path(state["loop_instance_record_path"])
    _atomic_write_bytes(
        record_path,
        canonical_bytes(record),
        maximum_bytes=LOOP_INSTANCE_RECORD_MAX_BYTES,
    )

    def mutator(value: dict[str, Any]) -> Mapping[str, Any]:
        value["loop_instance_record_digest"] = record["artifact_digest"]
        return value

    updated = store.update(mutator, expected_revision=expected_revision)
    return {
        "loop_instance_record": record,
        "path": str(record_path),
        "state_revision": updated["state_revision"],
    }


def set_artifact_authorization(
    *,
    store: CurrentLoopStore,
    authorization: Mapping[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    error = selected_artifact_authorization_error(authorization)
    if error:
        raise CurrentLoopError(error)

    def mutator(state: dict[str, Any]) -> Mapping[str, Any]:
        if state["loop_ref"] != authorization["loop_ref"]:
            raise CurrentLoopError("selected_artifact_loop_mismatch")
        previous = state.get("artifact_authorization")
        if (
            isinstance(previous, Mapping)
            and previous.get("state") == "approved"
            and authorization.get("approved_set_digest") != previous.get("approved_set_digest")
        ):
            stale = deepcopy(dict(previous))
            stale["state"] = "stale"
            state["artifact_authorization"] = stale
            state["freshness_events"].append(stale_recovery_result("selected_set_changed"))
        state["artifact_authorization"] = deepcopy(dict(authorization))
        state["selected_artifacts"] = {
            f"{item['artifact_role']}:{index}": deepcopy(item)
            for index, item in enumerate(authorization["items"], start=1)
        }
        return state

    return store.update(mutator, expected_revision=expected_revision)


def stale_recovery_result(
    category: str, *, affected_artifacts: Sequence[str] | None = None
) -> dict[str, Any]:
    if category not in _STALE_RECOVERY:
        raise CurrentLoopError("stale_category_invalid")
    result = deepcopy(_STALE_RECOVERY[category])
    if affected_artifacts is not None:
        result["affected"] = list(affected_artifacts)
    return {
        "category": category,
        "customer_explanation": result["explanation"],
        "affected_artifacts": result["affected"],
        "blocked_transition": result["blocked"],
        "supported_recovery": result["recovery"],
        "renewed_authorization_required": result["renewed_authorization_required"],
        "reextraction_required": result["reextraction_required"],
        "assistant_reconstruction_allowed": False,
    }


def _selected_role_category(role: str) -> str:
    return {
        "source": "source_changed",
        "circuit_qasm": "circuit_changed",
        "results": "result_changed",
    }.get(role, "selected_file_changed")


def check_current_loop_freshness(
    *,
    store: CurrentLoopStore,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    state = store.read()
    if expected_revision is not None and state["state_revision"] != expected_revision:
        raise CurrentLoopConflict("concurrent_state_update")
    events: list[dict[str, Any]] = []
    authorization = state.get("artifact_authorization")
    if isinstance(authorization, Mapping) and authorization.get("state") == "approved":
        for item in authorization.get("items", []):
            path = Path(item["local_path"])
            try:
                _stat, digest = _safe_local_file_digest(path, maximum_bytes=MAX_LOCAL_FILE_BYTES)
            except CurrentLoopError:
                events.append(
                    stale_recovery_result(
                        "selected_file_missing",
                        affected_artifacts=[item["artifact_role"]],
                    )
                )
                continue
            if digest != item.get("content_digest"):
                events.append(
                    stale_recovery_result(
                        _selected_role_category(item["artifact_role"]),
                        affected_artifacts=[item["artifact_role"]],
                    )
                )
    record_path = Path(state["loop_instance_record_path"])
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        events.append(stale_recovery_result("loop_instance_record_mismatch"))
    else:
        if (
            loop_instance_record_error(record)
            or record.get("loop_ref") != state["loop_ref"]
            or record.get("artifact_digest") != state.get("loop_instance_record_digest")
        ):
            events.append(stale_recovery_result("loop_instance_record_mismatch"))
    for role, descriptor in state.get("saved_artifacts", {}).items():
        path = Path(descriptor["local_path"])
        try:
            raw = path.read_bytes()
            parsed = json.loads(raw.decode("utf-8"))
            embedded = _artifact_digest(parsed)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            CurrentLoopError,
        ):
            events.append(
                stale_recovery_result(
                    "manifestation_missing"
                    if role
                    in {
                        "python_manifestation",
                        "circuit_manifestation",
                        "result_manifestation",
                    }
                    else "canonical_artifact_modified",
                    affected_artifacts=[role],
                )
            )
            continue
        if sha256_bytes(raw) != descriptor.get("file_digest") or embedded != descriptor.get(
            "artifact_digest"
        ):
            category = (
                "governing_blueprint_changed"
                if role == "working_blueprint"
                else "canonical_artifact_modified"
            )
            events.append(stale_recovery_result(category, affected_artifacts=[role]))
    if not events:
        return {
            "fresh": True,
            "state_revision": state["state_revision"],
            "events": [],
            "protected_request_allowed": True,
        }
    if expected_revision is None:
        expected_revision = state["state_revision"]

    def mutator(value: dict[str, Any]) -> Mapping[str, Any]:
        value["freshness_events"] = deepcopy(events)
        for event in events:
            for role in event["affected_artifacts"]:
                if role in value["stage_freshness"]:
                    value["stage_freshness"][role] = "stale"
        if isinstance(value.get("artifact_authorization"), Mapping) and any(
            event["renewed_authorization_required"] for event in events
        ):
            stale = deepcopy(dict(value["artifact_authorization"]))
            stale["state"] = "stale"
            value["artifact_authorization"] = stale
        return value

    updated = store.update(mutator, expected_revision=expected_revision)
    return {
        "fresh": False,
        "state_revision": updated["state_revision"],
        "events": events,
        "protected_request_allowed": False,
    }


def mark_local_dependency_stale(
    *,
    store: CurrentLoopStore,
    category: str,
    affected_artifacts: Sequence[str],
    expected_revision: int,
) -> dict[str, Any]:
    event = stale_recovery_result(category, affected_artifacts=affected_artifacts)

    def mutator(state: dict[str, Any]) -> Mapping[str, Any]:
        state["freshness_events"].append(event)
        for role in affected_artifacts:
            state["stage_freshness"][role] = "stale"
        return state

    return store.update(mutator, expected_revision=expected_revision)


def complete_current_loop(
    *,
    store: CurrentLoopStore,
    completion_state: str,
    continuation_artifact: Mapping[str, Any] | None,
    next_loop_seed: Mapping[str, Any] | None,
    expected_revision: int,
) -> dict[str, Any]:
    if completion_state not in {
        "completed_unchanged",
        "completed_changed",
        "abandoned",
    }:
        raise CurrentLoopError("completion_state_invalid")
    if completion_state == "completed_unchanged":
        if (
            continuation_artifact is None
            or unchanged_continuation_error(continuation_artifact)
            or next_loop_seed is None
            or next_loop_seed_error(next_loop_seed)
        ):
            raise CurrentLoopError("unchanged_completion_artifacts_required")
    if completion_state == "completed_changed" and (
        next_loop_seed is None or next_loop_seed_error(next_loop_seed)
    ):
        raise CurrentLoopError("changed_completion_seed_required")
    if completion_state == "abandoned" and (
        continuation_artifact is not None or next_loop_seed is not None
    ):
        raise CurrentLoopError("abandoned_completion_artifacts_forbidden")

    def mutator(state: dict[str, Any]) -> Mapping[str, Any]:
        state["activation_state"] = "abandoned" if completion_state == "abandoned" else "completed"
        state["completion_state"] = completion_state
        return state

    return store.update(mutator, expected_revision=expected_revision)


def _load_exact_json_file(
    path: str | Path,
    *,
    maximum_bytes: int,
    missing_category: str,
    invalid_category: str,
) -> dict[str, Any]:
    selected = Path(path).expanduser().absolute()
    try:
        _stat, _digest = _safe_local_file_digest(selected, maximum_bytes=maximum_bytes)
        value = json.loads(selected.read_text(encoding="utf-8"))
    except CurrentLoopError as exc:
        if exc.category in {
            "local_file_missing",
            "local_file_required",
            "local_file_unreadable",
        }:
            raise CurrentLoopError(missing_category) from exc
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentLoopError(invalid_category) from exc
    if not isinstance(value, dict):
        raise CurrentLoopError(invalid_category)
    return value


def canonical_operation_request_sha256(*, tool_name: str, tool_input: Mapping[str, Any]) -> str:
    if not isinstance(tool_name, str) or not tool_name:
        raise CurrentLoopError("next_permitted_operation_invalid")
    return sha256_bytes(
        (
            json.dumps(
                {"tool": tool_name, "input": deepcopy(dict(tool_input))},
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )


def expand_next_loop_seed(
    *,
    seed_file: str | Path,
    parent_files: Mapping[str, str | Path],
    tool_name: str,
    base_tool_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    seed = _load_exact_json_file(
        seed_file,
        maximum_bytes=NEXT_LOOP_SEED_MAX_BYTES,
        missing_category="next_loop_seed_missing",
        invalid_category="next_loop_seed_invalid",
    )
    error = next_loop_seed_error(seed)
    if error:
        raise CurrentLoopError(error)
    if seed["next_permitted_operation_family"] != tool_name:
        raise CurrentLoopError("next_loop_seed_operation_mismatch")
    inventory = seed["required_parent_artifact_inventory"]
    expected_roles = {item["artifact_role"] for item in inventory}
    if set(parent_files) != expected_roles:
        raise CurrentLoopError("next_loop_seed_parent_set_incomplete")
    tool_input = deepcopy(dict(base_tool_input or {}))
    supplied_parents: dict[str, dict[str, Any]] = {}
    for descriptor in inventory:
        role = descriptor["artifact_role"]
        field = descriptor["request_field"]
        if field in tool_input:
            raise CurrentLoopError("next_loop_seed_parent_overlay_forbidden")
        artifact = _load_exact_json_file(
            parent_files[role],
            maximum_bytes=MAX_LOCAL_FILE_BYTES,
            missing_category="next_loop_seed_parent_missing",
            invalid_category="next_loop_seed_parent_invalid",
        )
        try:
            actual = artifact_descriptor(artifact, role=role, request_field=field)
        except CurrentLoopError as exc:
            raise CurrentLoopError("next_loop_seed_parent_invalid") from exc
        if actual != descriptor:
            raise CurrentLoopError("parent_digest_mismatch")
        tool_input[field] = deepcopy(artifact)
        supplied_parents[role] = artifact
    governing_descriptor = seed["governing_blueprint"]
    governing_matches = [
        artifact
        for role, artifact in supplied_parents.items()
        if artifact_descriptor(artifact, role=role)["artifact_reference"]
        == governing_descriptor["artifact_reference"]
        and _artifact_digest(artifact) == governing_descriptor["artifact_digest"]
    ]
    if len(governing_matches) != 1:
        raise CurrentLoopError("next_loop_seed_governing_parent_missing")
    binding = decision_inventory_binding(governing_matches[0])
    if binding != seed["decision_inventory_binding"]:
        raise CurrentLoopError("next_loop_seed_inventory_binding_mismatch")
    request_digest = canonical_operation_request_sha256(tool_name=tool_name, tool_input=tool_input)
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "canonical_request_sha256": request_digest,
        "seed": seed,
        "explicit_parent_count": len(supplied_parents),
        "local_paths_transmitted": False,
        "server_lookup_performed": False,
        "project_reopened": False,
    }


def activate_next_loop_from_seed(
    *,
    workspace_root: str | Path,
    generation_posture: str,
    explicit_authority: bool,
    seed_file: str | Path,
    parent_files: Mapping[str, str | Path],
    tool_name: str,
    base_tool_input: Mapping[str, Any] | None = None,
    external_state_path: str | Path | None = None,
) -> dict[str, Any]:
    expanded = expand_next_loop_seed(
        seed_file=seed_file,
        parent_files=parent_files,
        tool_name=tool_name,
        base_tool_input=base_tool_input,
    )
    seed = expanded["seed"]
    activated = activate_current_loop(
        workspace_root=workspace_root,
        generation_posture=generation_posture,
        explicit_authority=explicit_authority,
        parent_loop_ref=seed["source_loop_ref"],
        external_state_path=external_state_path,
        governing_blueprint=next(
            artifact
            for artifact in expanded["tool_input"].values()
            if isinstance(artifact, Mapping)
            and (
                artifact.get("artifact_ref") == seed["governing_blueprint"]["artifact_reference"]
                or artifact.get("derived_artifact_reference")
                == seed["governing_blueprint"]["artifact_reference"]
            )
        ),
    )
    activated["expanded_next_operation"] = {
        key: deepcopy(value) for key, value in expanded.items() if key != "seed"
    }
    return activated


def current_loop_contract_snapshot() -> dict[str, Any]:
    return {
        "schemas": {
            "loop_instance_record": LOOP_INSTANCE_RECORD_SCHEMA_ID,
            "next_loop_seed": NEXT_LOOP_SEED_SCHEMA_ID,
            "unchanged_continuation": UNCHANGED_CONTINUATION_SCHEMA_ID,
            "selected_artifact_authorization": (SELECTED_ARTIFACT_AUTHORIZATION_SCHEMA_ID),
            "local_state": CURRENT_LOOP_STATE_SCHEMA_ID,
        },
        "bounds": {
            "loop_instance_record_maximum_serialized_bytes": (LOOP_INSTANCE_RECORD_MAX_BYTES),
            "next_loop_seed_maximum_serialized_bytes": NEXT_LOOP_SEED_MAX_BYTES,
            "current_loop_state_maximum_serialized_bytes": CURRENT_LOOP_STATE_MAX_BYTES,
            "maximum_stage_artifacts": MAX_STAGE_ARTIFACTS,
            "maximum_required_parents": MAX_REQUIRED_PARENTS,
            "maximum_changed_decisions": MAX_CHANGED_DECISIONS,
            "maximum_authorized_artifacts": MAX_AUTHORIZED_ARTIFACTS,
        },
        "generation_postures": list(GENERATION_POSTURES),
        "authorization_states": list(AUTHORIZATION_STATES),
        "authorization_actions": [
            "approve_all",
            "remove_one",
            "add_one_explicitly",
            "decline",
        ],
        "authorized_artifact_roles": list(AUTHORIZED_ARTIFACT_ROLES),
        "permitted_continuity_operation_families": list(PERMITTED_CONTINUITY_OPERATION_FAMILIES),
        "completion_states": list(COMPLETION_STATES),
        "continuation_outcomes": list(CONTINUATION_OUTCOMES),
        "stale_categories": sorted(_STALE_RECOVERY),
        "one_current_loop": True,
        "maximum_parent_loop_references": 1,
        "explicit_activation_required": True,
        "explicit_seed_import_required": True,
        "exact_parent_resupply_required": True,
        "directory_scan": False,
        "background_watcher": False,
        "automatic_reopen": False,
        "server_lookup": False,
        "graph_traversal": False,
        "cross_loop_comparison": False,
        "historical_index": False,
        "persistent": False,
        "protected_policy_included": False,
        "windows_acl_posture": (
            "inherits_explicitly_selected_directory_acl; Python chmod is not a "
            "complete owner-only Windows ACL guarantee"
        ),
    }
