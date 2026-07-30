"""Immutable per-revision local derivation and coherent snapshot promotion."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from qcoder.algorithm_blueprint import (
    extract_selected_python_file_evidence,
    with_artifact_digest,
)
from qcoder.context_loop import build_circuit_manifestation, build_result_manifestation
from qcoder.current_loop import (
    MAX_LOCAL_FILE_BYTES,
    CurrentLoopError,
    CurrentLoopStore,
    canonical_bytes,
)
from qcoder.current_loop_contract import permits as contract_permits
from qcoder.current_loop_evidence_processing import (
    EvidenceProcessingError,
    detect_exact_artifact_format,
    hosted_enrichment_status,
    processing_outcome,
)
from qcoder.current_loop_quiet_workflow import assistant_context_update
from qcoder.current_loop_retention import apply_bounded_retention
from qcoder.current_loop_run_summary import (
    RunSummaryError,
    build_run_summary,
    validate_run_summary_snapshot_binding,
)

DERIVATION_SCHEMA_ID = "qcoder.current_loop.derivation.v1"
DERIVATION_SCHEMA_VERSION = 1
MANIFESTATION_REVISION_SCHEMA_ID = "qcoder.current_loop.manifestation_revision.v1"
MANIFESTATION_REVISION_SCHEMA_VERSION = 1
CURRENT_BUILD_CONTEXT_SCHEMA_ID = "qcoder.current_loop.current_build_context_snapshot.v2"
CURRENT_BUILD_CONTEXT_SCHEMA_VERSION = 2
PROCESSING_FAILURE_SCHEMA_ID = "qcoder.current_loop.processing_failure.v1"


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _artifact_digest(value: Mapping[str, Any]) -> str:
    digest = value.get("artifact_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise CurrentLoopError("derived_artifact_digest_invalid")
    return digest


def _deterministic_artifact(
    value: Mapping[str, Any],
    *,
    parent_revision_id: str,
    role: str,
) -> dict[str, Any]:
    result = {
        key: deepcopy(item)
        for key, item in value.items()
        if key not in {"artifact_digest", "artifact_ref", "artifact_reference"}
    }
    reference_digest = _digest(
        {
            "parent_revision_id": parent_revision_id,
            "role": role,
            "deriver": DERIVATION_SCHEMA_ID,
            "schema_id": result.get("schema_id"),
            "content": result,
        }
    )
    result["artifact_ref"] = f"session-artifact-{reference_digest[:32]}"
    return with_artifact_digest(result)


def _write_immutable_json(
    *,
    artifact_directory: Path,
    role: str,
    parent_revision_id: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    raw = canonical_bytes(value)
    if len(raw) > MAX_LOCAL_FILE_BYTES:
        raise CurrentLoopError("local_state_or_artifact_too_large")
    key = _digest(
        {
            "parent_revision_id": parent_revision_id,
            "role": role,
            "deriver": DERIVATION_SCHEMA_ID,
            "artifact_digest": _artifact_digest(value),
        }
    )
    manifestation_revision_id = f"manifestation-revision-{key[:32]}"
    path = artifact_directory / f"{role}-{key[:24]}.json"
    artifact_directory.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CurrentLoopError("derived_artifact_symlink_rejected")
    if path.exists():
        existing = path.read_bytes()
        if existing != raw:
            raise CurrentLoopError("derived_artifact_collision")
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=artifact_directory
        )
        temporary = Path(temporary_name)
        try:
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                os.chmod(path, 0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    return {
        "schema_id": MANIFESTATION_REVISION_SCHEMA_ID,
        "schema_version": MANIFESTATION_REVISION_SCHEMA_VERSION,
        "manifestation_revision_id": manifestation_revision_id,
        "manifestation_role": role,
        "parent_artifact_revision_id": parent_revision_id,
        "artifact_reference": value["artifact_ref"],
        "artifact_digest": value["artifact_digest"],
        "file_digest": sha256(raw).hexdigest(),
        "local_path": str(path),
        "deriver_identity": DERIVATION_SCHEMA_ID,
        "deriver_version": DERIVATION_SCHEMA_VERSION,
        "immutable": True,
    }


def _python_manifestation(
    source_evidence: Mapping[str, Any],
    *,
    parent_revision_id: str,
) -> dict[str, Any]:
    return _deterministic_artifact(
        {
            "schema_id": "qcoder.python_manifestation.v1",
            "schema_version": 1,
            "artifact_type": "python_manifestation",
            "selected_source_evidence_reference": {
                "artifact_ref": source_evidence["artifact_ref"],
                "digest": source_evidence["artifact_digest"],
                "retrievable": False,
            },
            "framework_observation": source_evidence.get("framework_observation"),
            "parse_status": source_evidence.get("parse_status"),
            "evidence_coverage": source_evidence.get("evidence_coverage"),
            "represented_in_selected_source_evidence": True,
            "raw_source_included": False,
            "source_executed": False,
            "repository_scanned": False,
            "retention": "active_loop_only",
            "non_proofs": [
                "Selected source evidence does not prove runtime behavior.",
                "This manifestation does not prove source-to-circuit equivalence.",
            ],
        },
        parent_revision_id=parent_revision_id,
        role="python_manifestation",
    )


def _read_revision_bytes(revision: Mapping[str, Any]) -> bytes:
    path = Path(str(revision["exact_path"]))
    if path.is_symlink() or not path.is_file():
        raise CurrentLoopError("artifact_revision_unavailable")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != revision.get("content_digest"):
        raise CurrentLoopError("artifact_revision_digest_mismatch")
    return raw


def _load_manifestation(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(descriptor["local_path"]))
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentLoopError("manifestation_revision_unavailable") from exc
    if sha256(raw).hexdigest() != descriptor.get("file_digest"):
        raise CurrentLoopError("manifestation_revision_digest_mismatch")
    if _artifact_digest(value) != descriptor.get("artifact_digest"):
        raise CurrentLoopError("manifestation_revision_digest_mismatch")
    return value


def read_manifestation_revision(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Read one exact qCoder-owned manifestation revision without discovery."""

    return _load_manifestation(descriptor)


def _activity_lineage(
    state: Mapping[str, Any],
    *,
    artifact_revision_id: str,
) -> dict[str, Any]:
    for activity in reversed(state.get("activity_receipts", [])):
        if not isinstance(activity, Mapping):
            continue
        for item in activity.get("registered_artifacts", []):
            if (
                isinstance(item, Mapping)
                and item.get("artifact_revision_id") == artifact_revision_id
            ):
                return {
                    "status": "recorded",
                    "operation_receipt_id": activity.get("operation_receipt_id"),
                    "activity_digest": activity.get("activity_digest"),
                }
    return {
        "status": "missing",
        "operation_receipt_id": None,
        "activity_digest": None,
    }


def derive_pending_snapshot(
    *,
    state: Mapping[str, Any],
    artifact_directory: Path,
) -> dict[str, Any]:
    """Derive exact registered heads independently, without mutating state."""

    registry = state["evidence_registry"]
    pending = state.get("registered_pending_derivation")
    if not isinstance(pending, Mapping):
        raise CurrentLoopError("registered_pending_derivation_missing")
    snapshot_id = str(pending["snapshot_id"])
    snapshot = registry["snapshots"].get(snapshot_id)
    if not isinstance(snapshot, Mapping) or snapshot.get("snapshot_status") != "pending_derivation":
        raise CurrentLoopError("registered_pending_derivation_invalid")
    role_set = deepcopy(dict(snapshot["role_revision_set"]))
    manifestations: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    values: dict[str, dict[str, Any]] = {}
    result_payload: dict[str, Any] | None = None
    for role, revision_id in sorted(role_set.items()):
        revision = registry["artifact_revisions"][revision_id]
        detected = str(revision["detected_format"])
        manifestation_roles: list[str] = []
        try:
            raw = _read_revision_bytes(revision)
            detected_now = detect_exact_artifact_format(Path(str(revision["exact_path"])), role)
            if detected_now != detected:
                raise CurrentLoopError("artifact_revision_format_changed")
            if role == "source":
                if detected != "python_source":
                    raise EvidenceProcessingError(
                        "artifact_format_unsupported", origin="local_source_derivation"
                    )
                source = extract_selected_python_file_evidence(
                    Path(str(revision["exact_path"])),
                    logical_source_label=Path(str(revision["exact_path"])).name,
                )
                source = _deterministic_artifact(
                    source,
                    parent_revision_id=revision_id,
                    role="source_evidence",
                )
                python = _python_manifestation(source, parent_revision_id=revision_id)
                manifestations["source_evidence"] = _write_immutable_json(
                    artifact_directory=artifact_directory,
                    role="source_evidence",
                    parent_revision_id=revision_id,
                    value=source,
                )
                manifestations["python_manifestation"] = _write_immutable_json(
                    artifact_directory=artifact_directory,
                    role="python_manifestation",
                    parent_revision_id=revision_id,
                    value=python,
                )
                values["source_evidence"] = source
                values["python_manifestation"] = python
                manifestation_roles = ["source_evidence", "python_manifestation"]
            elif role == "circuit_qasm":
                if detected != "openqasm_2":
                    raise EvidenceProcessingError(
                        "circuit_format_unsupported",
                        origin="local_circuit_derivation",
                        safe_details={
                            "detected_format": detected,
                            "supported_formats": ["openqasm_2"],
                        },
                    )
                circuit = build_circuit_manifestation(
                    qasm_text=raw.decode("utf-8-sig"),
                    stage="logical_circuit",
                )
                circuit = _deterministic_artifact(
                    circuit,
                    parent_revision_id=revision_id,
                    role="circuit_manifestation",
                )
                manifestations["circuit_manifestation"] = _write_immutable_json(
                    artifact_directory=artifact_directory,
                    role="circuit_manifestation",
                    parent_revision_id=revision_id,
                    value=circuit,
                )
                values["circuit_manifestation"] = circuit
                manifestation_roles = ["circuit_manifestation"]
            elif role == "results":
                if detected != "qcoder_result_json":
                    raise EvidenceProcessingError(
                        "artifact_format_unsupported", origin="local_result_derivation"
                    )
                loaded = json.loads(raw.decode("utf-8"))
                if not isinstance(loaded, Mapping):
                    raise EvidenceProcessingError(
                        "result_artifact_invalid", origin="local_result_derivation"
                    )
                result_payload = (
                    deepcopy(dict(loaded))
                    if "counts" in loaded
                    else {"counts": deepcopy(dict(loaded))}
                )
                counts_value = loaded.get("counts", loaded)
                if not isinstance(counts_value, Mapping):
                    raise EvidenceProcessingError(
                        "result_artifact_invalid", origin="local_result_derivation"
                    )
                counts = {str(key): int(value) for key, value in counts_value.items()}
                circuit = values.get("circuit_manifestation")
                related_ref = (
                    str(circuit["artifact_ref"])
                    if circuit is not None
                    else "session-artifact-"
                    + _digest({"unavailable_circuit_for": revision_id})[:32]
                )
                result = build_result_manifestation(
                    counts=counts,
                    related_circuit_ref=related_ref,
                    user_provided_shots=(
                        int(loaded["shots"]) if isinstance(loaded.get("shots"), int) else None
                    ),
                )
                result = with_artifact_digest(
                    {
                        **{
                            key: deepcopy(item)
                            for key, item in result.items()
                            if key != "artifact_digest"
                        },
                        "registered_result_content_digest": revision["content_digest"],
                        "bounded_counts_digest": _digest(
                            {str(key): int(value) for key, value in counts.items()}
                        ),
                    }
                )
                if circuit is None:
                    result = with_artifact_digest(
                        {
                            **{
                                key: deepcopy(item)
                                for key, item in result.items()
                                if key != "artifact_digest"
                            },
                            "related_circuit_availability": "unavailable",
                        }
                    )
                result = _deterministic_artifact(
                    result,
                    parent_revision_id=revision_id,
                    role="result_manifestation",
                )
                manifestations["result_manifestation"] = _write_immutable_json(
                    artifact_directory=artifact_directory,
                    role="result_manifestation",
                    parent_revision_id=revision_id,
                    value=result,
                )
                values["result_manifestation"] = result
                manifestation_roles = ["result_manifestation"]
            outcomes[revision_id] = processing_outcome(
                role=role,
                artifact_revision_id=revision_id,
                evidence_snapshot_id=snapshot_id,
                content_digest=str(revision["content_digest"]),
                detected_format=detected,
                status="completed",
                manifestation_roles=manifestation_roles,
            )
        except (EvidenceProcessingError, CurrentLoopError, OSError, ValueError) as exc:
            category = str(getattr(exc, "category", "unknown_local_internal"))
            unsupported = category in {
                "artifact_format_unsupported",
                "circuit_format_unsupported",
            }
            outcomes[revision_id] = processing_outcome(
                role=role,
                artifact_revision_id=revision_id,
                evidence_snapshot_id=snapshot_id,
                content_digest=str(revision["content_digest"]),
                detected_format=detected,
                status="unsupported_format" if unsupported else "failed_local",
                limitation=(
                    "Circuit structural derivation is unavailable because the exact "
                    "artifact is not OpenQASM 2."
                    if category == "circuit_format_unsupported"
                    else "Local derivation was unavailable for this exact artifact revision."
                ),
                safe_error_category=category,
            )
    summary: dict[str, Any] | None = None
    summary_failure: dict[str, Any] | None = None
    if (
        result_payload is not None
        and "result_manifestation" in values
        and contract_permits(
            state["current_loop_contract"],
            category="result_manifestation",
            dimension="prepare",
        )
    ):
        try:
            manifestation_ids = {
                role: descriptor["manifestation_revision_id"]
                for role, descriptor in manifestations.items()
            }
            summary = build_run_summary(
                loop_ref=str(state["loop_ref"]),
                workspace_binding=str(state["workspace_root"]),
                state_revision=int(state["state_revision"]),
                contract_revision=int(state["current_loop_contract"]["contract_revision"]),
                result_payload=result_payload,
                result_manifestation=values["result_manifestation"],
                circuit_manifestation=values.get("circuit_manifestation"),
                source_manifestation=values.get("python_manifestation"),
                operation_lineage=_activity_lineage(
                    state,
                    artifact_revision_id=str(role_set["results"]),
                ),
                evidence_snapshot_id=snapshot_id,
                artifact_revision_bindings=role_set,
                artifact_revision_digests=snapshot["artifact_revision_digest_bindings"],
                manifestation_revision_bindings=manifestation_ids,
                derivation_version=DERIVATION_SCHEMA_ID,
            )
            candidate_snapshot = {
                **deepcopy(dict(snapshot)),
                "manifestation_revision_set": manifestations,
            }
            error = validate_run_summary_snapshot_binding(summary, candidate_snapshot)
            if error:
                raise RunSummaryError(error)
        except (RunSummaryError, CurrentLoopError, ValueError) as exc:
            summary = None
            summary_failure = {
                "schema_id": PROCESSING_FAILURE_SCHEMA_ID,
                "safe_category": str(getattr(exc, "category", "local_run_summary_failed")),
                "evidence_snapshot_id": snapshot_id,
                "result_artifact_revision_id": role_set.get("results"),
            }
    completed = sum(1 for outcome in outcomes.values() if outcome.get("status") == "completed")
    snapshot_status = (
        "failed"
        if completed == 0
        else "complete"
        if completed == len(outcomes) and summary_failure is None
        else "partial"
    )
    if isinstance(summary, Mapping) and snapshot_status == "partial":
        summary_value = deepcopy(dict(summary))
        summary_value.pop("artifact_digest", None)
        summary_value["integrity_status"] = "incomplete"
        summary_value["freshness"] = {
            "status": "incomplete",
            "stale_reasons": [],
            "source_digest_validation_required": True,
        }
        summary = with_artifact_digest(summary_value)
    return {
        "schema_id": DERIVATION_SCHEMA_ID,
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "expected_state_revision": state["state_revision"],
        "snapshot_id": snapshot_id,
        "role_revision_set": role_set,
        "manifestation_revision_set": manifestations,
        "manifestation_values": values,
        "processing_outcomes": outcomes,
        "run_summary": summary,
        "run_summary_failure": summary_failure,
        "snapshot_status": snapshot_status,
        "all_side_writes_immutable": True,
        "state_mutated": False,
    }


def promote_derivation_snapshot(
    *,
    store: CurrentLoopStore,
    derivation: Mapping[str, Any],
    artifact_directory: Path,
) -> dict[str, Any]:
    """Publish all projections through one state CAS."""

    state = store.read()
    expected = int(derivation["expected_state_revision"])
    if state["state_revision"] != expected:
        raise CurrentLoopError("client_state_conflict")
    snapshot_id = str(derivation["snapshot_id"])
    summary = derivation.get("run_summary")
    summary_descriptor = None
    if isinstance(summary, Mapping):
        summary_descriptor = _write_immutable_json(
            artifact_directory=artifact_directory,
            role="run_summary",
            parent_revision_id=snapshot_id,
            value=summary,
        )
        summary_descriptor = {
            **summary_descriptor,
            "artifact_reference": summary["artifact_ref"],
            "result_evidence_reference": summary["result_evidence_reference"],
            "creation_revision": summary["creation_revision"],
            "status": summary["integrity_status"],
            "currency": "current",
            "evidence_snapshot_id": snapshot_id,
        }
    manifestations = deepcopy(dict(derivation["manifestation_revision_set"]))
    outcomes = deepcopy(dict(derivation["processing_outcomes"]))
    summary_reference = str(summary["artifact_ref"]) if isinstance(summary, Mapping) else None
    previous_snapshot_id = state["evidence_registry"].get("current_presentation_snapshot_id")
    previous_snapshot = state["evidence_registry"].get("snapshots", {}).get(previous_snapshot_id)
    previous_summary_reference = state.get("latest_run_summary_reference") or (
        previous_snapshot.get("run_summary_reference")
        if isinstance(previous_snapshot, Mapping)
        else None
    )
    current_build_context = {
        "schema_id": CURRENT_BUILD_CONTEXT_SCHEMA_ID,
        "schema_version": CURRENT_BUILD_CONTEXT_SCHEMA_VERSION,
        "evidence_snapshot_id": snapshot_id,
        "artifact_revision_references": deepcopy(dict(derivation["role_revision_set"])),
        "artifact_revision_digests": deepcopy(
            dict(
                state["evidence_registry"]["snapshots"][snapshot_id][
                    "artifact_revision_digest_bindings"
                ]
            )
        ),
        "manifestation_revision_references": {
            role: value["manifestation_revision_id"] for role, value in manifestations.items()
        },
        "processing_completeness": derivation["snapshot_status"],
        "available_context": sorted(manifestations),
        "missing_or_failed_roles": sorted(
            outcome["role"] for outcome in outcomes.values() if outcome["status"] != "completed"
        ),
        "limitations": sorted(
            {
                str(outcome["limitation"])
                for outcome in outcomes.values()
                if outcome.get("limitation")
            }
        ),
        "currentness": "current" if derivation["snapshot_status"] != "failed" else "prior",
        "newer_iteration_status": (
            "failed"
            if derivation["snapshot_status"] == "failed"
            or derivation.get("run_summary_failure") is not None
            else None
        ),
        "raw_evidence_included": False,
    }
    context_update = None
    if isinstance(summary, Mapping) and contract_permits(
        state["current_loop_contract"],
        category="result_manifestation",
        dimension="assistant_derived_exposure",
    ):
        observations = summary["execution_observations"]
        backend = observations["backend"]
        shots = observations["shots"]
        circuit = derivation.get("manifestation_values", {}).get("circuit_manifestation")
        context_update = assistant_context_update(
            run_reference=summary_reference or "",
            evidence_references=summary["evidence_bindings"],
            backend=(str(backend["value"]) if backend["status"] == "observed" else None),
            shots=(
                int(shots["value"])
                if shots["status"] == "observed" and isinstance(shots["value"], int)
                else int(summary["count_projection"]["observed_shots"])
            ),
            top_outcomes=summary["count_projection"]["top_outcomes"],
            warnings=summary["warnings"],
            limitations=summary["limitations"],
            circuit_metrics=(
                {
                    key: circuit.get(key)
                    for key in ("gate_count", "width", "depth")
                    if circuit.get(key) is not None
                }
                if isinstance(circuit, Mapping)
                else None
            ),
            freshness=("fresh" if derivation["snapshot_status"] == "complete" else "incomplete"),
            contract_revision=int(state["current_loop_contract"]["contract_revision"]),
            evidence_snapshot_id=snapshot_id,
            artifact_revision_references=derivation["role_revision_set"],
            currency="current",
            newer_iteration_status=None,
            prior_context_available=previous_summary_reference is not None,
        )
    elif (
        derivation["snapshot_status"] == "failed"
        or derivation.get("run_summary_failure") is not None
    ):
        context_update = assistant_context_update(
            run_reference=str(previous_summary_reference or "run-summary-unavailable"),
            evidence_references=[],
            backend=None,
            shots=None,
            top_outcomes=[],
            warnings=[
                (
                    "The newer registered iteration could not be derived locally."
                    if derivation["snapshot_status"] == "failed"
                    else "The newer registered result could not produce a Run Summary."
                )
            ],
            limitations=[
                "Prior derived context remains available but does not describe the newer evidence."
            ],
            circuit_metrics=None,
            freshness="failed",
            contract_revision=int(state["current_loop_contract"]["contract_revision"]),
            evidence_snapshot_id=snapshot_id,
            artifact_revision_references=derivation["role_revision_set"],
            currency="prior_newer_failed",
            newer_iteration_status="failed",
            prior_context_available=previous_summary_reference is not None,
        )

    deletion_paths: set[Path] = set()
    retention_result: dict[str, int] = {}

    def mutator(value: dict[str, Any]) -> Mapping[str, Any]:
        registry = value["evidence_registry"]
        pending = value.get("registered_pending_derivation")
        if not isinstance(pending, Mapping) or pending.get("snapshot_id") != snapshot_id:
            raise CurrentLoopError("registered_pending_derivation_changed")
        snapshot = registry["snapshots"].get(snapshot_id)
        if not isinstance(snapshot, Mapping):
            raise CurrentLoopError("evidence_snapshot_missing")
        promoted = deepcopy(dict(snapshot))
        promoted["manifestation_revision_set"] = manifestations
        promoted["processing_outcomes"] = outcomes
        promoted["run_summary_reference"] = summary_reference
        promoted["run_summary_failure"] = deepcopy(derivation.get("run_summary_failure"))
        promoted["current_build_context"] = deepcopy(current_build_context)
        promoted["assistant_context_update_reference"] = (
            context_update.get("context_digest") if isinstance(context_update, Mapping) else None
        )
        promoted["snapshot_status"] = derivation["snapshot_status"]
        promoted["promotion_state_revision"] = expected + 1
        registry["snapshots"][snapshot_id] = promoted
        registry["pending_snapshot_id"] = None
        if derivation["snapshot_status"] != "failed":
            registry["current_presentation_snapshot_id"] = snapshot_id
        value["registered_pending_derivation"] = None
        value["current_evidence_status"] = (
            "fresh"
            if derivation["snapshot_status"] == "complete"
            else "incomplete"
            if derivation["snapshot_status"] == "partial"
            else "failed"
        )
        for revision_id, outcome in outcomes.items():
            value["artifact_processing_outcomes"][revision_id] = deepcopy(outcome)
            revision = registry["artifact_revisions"].get(revision_id)
            if isinstance(revision, dict) and outcome["status"] == "completed":
                revision["revision_status"] = "derived"
        for role, descriptor in manifestations.items():
            value["saved_artifacts"][role] = deepcopy(descriptor)
            value["stage_freshness"][role] = (
                "fresh" if derivation["snapshot_status"] == "complete" else "incomplete"
            )
        if isinstance(previous_summary_reference, str):
            prior = value["run_summary_index"].get(previous_summary_reference)
            if isinstance(prior, dict):
                prior["currency"] = (
                    "prior_newer_failed"
                    if derivation["snapshot_status"] == "failed"
                    or derivation.get("run_summary_failure") is not None
                    else "superseded"
                )
        if isinstance(summary_descriptor, Mapping) and isinstance(summary, Mapping):
            value["run_summary_index"][summary_reference] = deepcopy(summary_descriptor)
            value["latest_run_summary_reference"] = summary_reference
        elif derivation["snapshot_status"] == "failed":
            value["latest_run_summary_reference"] = None
        value["current_build_context_refresh"] = deepcopy(current_build_context)
        if isinstance(context_update, Mapping):
            value["assistant_context_updates"].append(deepcopy(context_update))
            value["assistant_context_updates"] = value["assistant_context_updates"][-32:]
            value["latest_assistant_context_update"] = deepcopy(context_update)
        value["hosted_enrichment"] = hosted_enrichment_status(
            "available" if manifestations else "not_offered"
        )
        value["quiet_iteration_status"] = "assist_iteration_ready"
        retention_result.update(apply_bounded_retention(value, deletion_paths=deletion_paths))
        return value

    updated = store.update(mutator, expected_revision=expected)
    deletion_failures: list[str] = []
    for path in sorted(deletion_paths, key=str):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            deletion_failures.append(path.name)
    if deletion_failures:
        raise CurrentLoopError(
            "evidence_retention_side_file_cleanup_failed",
            safe_details={"qcoder_file_labels": deletion_failures},
        )
    return {
        "promoted": derivation["snapshot_status"] != "failed",
        "snapshot_id": snapshot_id,
        "snapshot_status": derivation["snapshot_status"],
        "run_summary_reference": summary_reference,
        "current_presentation_snapshot_id": updated["evidence_registry"][
            "current_presentation_snapshot_id"
        ],
        "state_revision": updated["state_revision"],
        "processing_outcomes": outcomes,
        "assistant_context_update": context_update,
        "current_build_context": current_build_context,
        "retention": retention_result,
    }


def derivation_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": DERIVATION_SCHEMA_ID,
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "manifestation_revision_schema_id": MANIFESTATION_REVISION_SCHEMA_ID,
        "current_build_context_schema_id": CURRENT_BUILD_CONTEXT_SCHEMA_ID,
        "per_item_independent": True,
        "side_files_immutable_before_promotion": True,
        "promotion_single_cas": True,
        "directory_discovery_permitted": False,
        "protected_calls_permitted": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload
