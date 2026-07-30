"""Canonical local evidence-processing, format, provenance, and recovery contracts."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID = "qcoder.current_loop.artifact_format_contract.v1"
ARTIFACT_FORMAT_CONTRACT_SCHEMA_VERSION = 1
PROCESSING_OUTCOME_SCHEMA_ID = "qcoder.current_loop.processing_outcome.v2"
PROCESSING_OUTCOME_SCHEMA_VERSION = 2
HOSTED_ENRICHMENT_SCHEMA_ID = "qcoder.current_loop.hosted_enrichment_status.v1"
HOSTED_ENRICHMENT_SCHEMA_VERSION = 1
RECOVERY_ACTION_SCHEMA_ID = "qcoder.current_loop.recovery_action.v1"
RECOVERY_ACTION_SCHEMA_VERSION = 1
FAILURE_PROVENANCE_SCHEMA_ID = "qcoder.current_loop.failure_provenance.v1"
FAILURE_PROVENANCE_SCHEMA_VERSION = 1

FAILURE_ORIGINS = (
    "local_artifact_validation",
    "local_source_derivation",
    "local_circuit_derivation",
    "local_result_derivation",
    "local_run_summary",
    "hosted_transport",
    "hosted_operation",
    "contract_or_authority",
    "client_environment",
    "unknown_local_internal",
)

SAFE_LOCAL_CATEGORIES = frozenset(
    {
        "artifact_format_unsupported",
        "artifact_missing",
        "artifact_stale",
        "artifact_digest_invalid",
        "circuit_format_unsupported",
        "current_loop_contract_policy_prohibited",
        "local_artifact_validation_failed",
        "local_circuit_derivation_failed",
        "local_result_derivation_failed",
        "local_run_summary_failed",
        "local_source_derivation_failed",
        "result_artifact_invalid",
        "unknown_local_internal",
    }
)

_ROLE_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "role": "source",
        "customer_meaning": "Exact Python source created or selected for this loop.",
        "accepted_automatic_registration_formats": ["python_source"],
        "local_derivation_formats": ["python_source"],
        "producer_requirements": {
            "filename_suffix": [".py"],
            "content_requirement": "valid_utf8_python_source",
        },
        "unsupported_exact_artifact_fallback": True,
        "optional": True,
        "safe_alternatives": ["exact_artifact_fallback", "skip_current_artifact_derivation"],
    },
    {
        "role": "circuit_qasm",
        "customer_meaning": (
            "Exact circuit interchange evidence. Structural analysis currently requires OpenQASM 2."
        ),
        "accepted_automatic_registration_formats": ["openqasm_2"],
        "local_derivation_formats": ["openqasm_2"],
        "producer_requirements": {
            "format": "openqasm_2",
            "header": "OPENQASM 2.0;",
            "assistant_must_not_convert_automatically": True,
        },
        "unsupported_exact_artifact_fallback": True,
        "optional": True,
        "safe_alternatives": [
            "provide_supported_circuit_artifact",
            "continue_with_limitations",
            "skip_current_artifact_derivation",
            "stop_loop",
        ],
    },
    {
        "role": "results",
        "customer_meaning": "Exact JSON result evidence created or selected for this loop.",
        "accepted_automatic_registration_formats": ["qcoder_result_json"],
        "local_derivation_formats": ["qcoder_result_json"],
        "producer_requirements": {
            "filename_suffix": [".json"],
            "top_level_json_type": "object",
        },
        "unsupported_exact_artifact_fallback": True,
        "optional": True,
        "safe_alternatives": ["exact_artifact_fallback", "skip_current_artifact_derivation"],
    },
)

_RECOVERY_MEANINGS = {
    "continue_with_limitations": "Continue using trustworthy local evidence and record the limitation.",
    "provide_supported_circuit_artifact": (
        "Authorize creation or selection of an exact OpenQASM 2 circuit artifact."
    ),
    "skip_current_artifact_derivation": "Skip derivation for this artifact only.",
    "retry_local_derivation": "Retry local derivation after the exact input changes.",
    "retry_hosted_enrichment": "Retry the optional hosted enrichment using current authority.",
    "skip_hosted_enrichment": "Skip only the optional hosted-enrichment attempt.",
    "decline_build_review": "Decline the optional Build Review and continue unchanged.",
    "return_to_iteration_ready": (
        "Return this valid active loop to quiet ordinary iteration without discarding evidence."
    ),
    "abandon_step": "Abandon only the current optional step.",
    "stop_loop": "Stop qCoder for this build.",
}


class EvidenceProcessingError(Exception):
    """A bounded local/hosted processing failure with explicit provenance."""

    def __init__(
        self,
        category: str,
        *,
        origin: str,
        deterministic: bool = True,
        safe_details: Mapping[str, Any] | None = None,
        protected_call_attempted: bool = False,
        protected_non_success: bool = False,
    ) -> None:
        if origin not in FAILURE_ORIGINS:
            raise ValueError("failure_origin_invalid")
        if category == "protected_operation_rejected" and not (
            protected_call_attempted and protected_non_success
        ):
            raise ValueError("protected_category_provenance_invalid")
        super().__init__(category)
        self.category = category
        self.origin = origin
        self.deterministic = deterministic
        self.safe_details = deepcopy(dict(safe_details or {}))
        self.protected_call_attempted = protected_call_attempted
        self.protected_non_success = protected_non_success


def _digest(value: Mapping[str, Any] | list[Any]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def artifact_format_contract_snapshot() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_id": ARTIFACT_FORMAT_CONTRACT_SCHEMA_ID,
        "schema_version": ARTIFACT_FORMAT_CONTRACT_SCHEMA_VERSION,
        "format_detection_scope": "exact_declared_artifact_only",
        "directory_discovery_performed": False,
        "git_discovery_performed": False,
        "automatic_conversion_performed": False,
        "roles": [deepcopy(row) for row in _ROLE_CONTRACTS],
    }
    payload["contract_digest"] = _digest(payload)
    return payload


def format_contract_for_role(role: str) -> dict[str, Any]:
    for row in _ROLE_CONTRACTS:
        if row["role"] == role:
            return deepcopy(row)
    raise EvidenceProcessingError(
        "unsupported_authorized_artifact_type",
        origin="local_artifact_validation",
    )


def detect_exact_artifact_format(path: Path, role: str) -> str:
    """Identify only the exact declared artifact; never discover alternatives."""

    format_contract_for_role(role)
    if path.is_symlink():
        raise EvidenceProcessingError(
            "selected_artifact_symlink_rejected",
            origin="local_artifact_validation",
        )
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise EvidenceProcessingError(
            "artifact_missing", origin="local_artifact_validation"
        ) from exc
    except OSError as exc:
        raise EvidenceProcessingError(
            "local_artifact_validation_failed",
            origin="local_artifact_validation",
        ) from exc
    if role == "source":
        if path.suffix.lower() != ".py":
            return "unsupported"
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return "unsupported"
        return "python_source"
    if role == "circuit_qasm":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return "unsupported"
        significant = "\n".join(
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("//")
        )
        if significant.startswith("OPENQASM 2.0;"):
            return "openqasm_2"
        if significant.startswith("OPENQASM 3"):
            return "openqasm_3"
        return "unsupported"
    if role == "results":
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "unsupported"
        return "qcoder_result_json" if isinstance(value, Mapping) else "unsupported"
    raise EvidenceProcessingError(
        "unsupported_authorized_artifact_type",
        origin="local_artifact_validation",
        safe_details={"known_roles": [row["role"] for row in _ROLE_CONTRACTS]},
    )


def registration_format_outcome(*, path: Path, role: str, provenance: str) -> dict[str, Any]:
    contract = format_contract_for_role(role)
    detected = detect_exact_artifact_format(path, role)
    automatic = detected in contract["accepted_automatic_registration_formats"]
    fallback = bool(contract["unsupported_exact_artifact_fallback"])
    return {
        "schema_id": PROCESSING_OUTCOME_SCHEMA_ID,
        "schema_version": PROCESSING_OUTCOME_SCHEMA_VERSION,
        "role": role,
        "detected_format": detected,
        "automatic_registration_supported": automatic,
        "local_derivation_supported": detected in contract["local_derivation_formats"],
        "registration_disposition": (
            "eligible"
            if automatic
            else "explicit_exact_artifact_fallback_available"
            if fallback and provenance == "customer_selected_exact_artifact"
            else "unsupported_format"
        ),
        "safe_alternatives": deepcopy(contract["safe_alternatives"]),
        "exact_declared_artifact_only": True,
    }


def processing_outcome(
    *,
    role: str,
    content_digest: str,
    detected_format: str,
    status: str,
    manifestation_roles: list[str] | None = None,
    limitation: str | None = None,
    safe_error_category: str | None = None,
    artifact_revision_id: str | None = None,
    evidence_snapshot_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_id": PROCESSING_OUTCOME_SCHEMA_ID,
        "schema_version": PROCESSING_OUTCOME_SCHEMA_VERSION,
        "role": role,
        "artifact_revision_id": artifact_revision_id,
        "evidence_snapshot_id": evidence_snapshot_id,
        "content_digest": content_digest,
        "detected_format": detected_format,
        "status": status,
        "manifestation_roles": list(manifestation_roles or []),
        "limitation": limitation,
        "safe_error_category": safe_error_category,
    }
    payload["outcome_digest"] = _digest(payload)
    return payload


def hosted_enrichment_status(
    status: str,
    *,
    provenance: str | None = None,
    attempts: int = 0,
    last_safe_category: str | None = None,
) -> dict[str, Any]:
    if status not in {
        "not_offered",
        "available",
        "in_progress",
        "completed",
        "rejected",
        "unavailable",
        "skipped",
        "declined",
    }:
        raise ValueError("hosted_enrichment_status_invalid")
    return {
        "schema_id": HOSTED_ENRICHMENT_SCHEMA_ID,
        "schema_version": HOSTED_ENRICHMENT_SCHEMA_VERSION,
        "status": status,
        "provenance": provenance,
        "attempts": attempts,
        "last_safe_category": last_safe_category,
        "local_evidence_preserved": True,
        "run_summary_preserved": True,
    }


def failure_provenance(
    *,
    origin: str,
    category: str,
    protected_call_attempted: bool,
    protected_non_success: bool,
) -> dict[str, Any]:
    if origin not in FAILURE_ORIGINS:
        origin = "unknown_local_internal"
    if category == "protected_operation_rejected" and not (
        protected_call_attempted and protected_non_success
    ):
        raise ValueError("protected_category_provenance_invalid")
    return {
        "schema_id": FAILURE_PROVENANCE_SCHEMA_ID,
        "schema_version": FAILURE_PROVENANCE_SCHEMA_VERSION,
        "origin": origin,
        "safe_category": category,
        "protected_call_attempted": protected_call_attempted,
        "protected_non_success": protected_non_success,
    }


def recovery_fingerprint(*, category: str, operation: str, input_digests: list[str]) -> str:
    return _digest(
        {
            "category": category,
            "operation": operation,
            "input_digests": sorted(input_digests),
        }
    )


def recovery_action_contract_snapshot() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_id": RECOVERY_ACTION_SCHEMA_ID,
        "schema_version": RECOVERY_ACTION_SCHEMA_VERSION,
        "refresh_executes_action": False,
        "selection_requires_qcoder_owned_recovery_reference": True,
        "actions": [
            {"action": action, "customer_meaning": meaning}
            for action, meaning in sorted(_RECOVERY_MEANINGS.items())
        ],
    }
    payload["contract_digest"] = _digest(payload)
    return payload


def evidence_processing_contract_snapshot() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_id": "qcoder.current_loop.evidence_processing_contract.v1",
        "schema_version": 1,
        "local_stage": {
            "operation": "process_authorized_artifacts",
            "transport": "local_only",
            "per_item_isolation": True,
            "protected_calls_permitted": False,
        },
        "hosted_stage": {
            "operation": "enrich_authorized_evidence",
            "transport": "hosted_capable",
            "optional": True,
            "may_be_skipped": True,
        },
        "format_contract": artifact_format_contract_snapshot(),
        "recovery_action_contract": recovery_action_contract_snapshot(),
    }
    payload["contract_digest"] = _digest(payload)
    return payload
