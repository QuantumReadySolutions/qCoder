"""Role-specific, no-mutation satisfaction for exact selected artifacts."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from qcoder.current_loop import CurrentLoopError, MAX_LOCAL_FILE_BYTES
from qcoder.current_loop_evidence_processing import detect_exact_artifact_format


SATISFACTION_SCHEMA_ID = "qcoder.current_loop.artifact_satisfaction.v1"
SATISFACTION_DISPOSITIONS = (
    "created",
    "modified",
    "pre_existing_exact_artifact",
    "explicitly_user_selected_or_supplied",
)


def evaluate_exact_artifact_satisfaction(
    *,
    workspace_root: Path,
    path: Path,
    role: str,
    origin: str,
    expected_content_digest: str | None = None,
) -> dict[str, Any]:
    """Validate an exact artifact without writing, touching, or discovering files."""

    if origin not in {"pre_existing", "user_selected"}:
        raise CurrentLoopError("artifact_satisfaction_origin_invalid")
    if not path.is_absolute() or ".." in path.parts or path.is_symlink() or not path.is_file():
        raise CurrentLoopError("artifact_candidate_file_required")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(workspace_root.resolve(strict=True))
    except ValueError as exc:
        raise CurrentLoopError("external_artifact_selection_required") from exc
    before_stat = path.stat()
    raw = path.read_bytes()
    if len(raw) > MAX_LOCAL_FILE_BYTES:
        raise CurrentLoopError("artifact_candidate_file_too_large")
    digest = sha256(raw).hexdigest()
    if expected_content_digest is not None and expected_content_digest != digest:
        raise CurrentLoopError("selected_file_stale")
    detected = detect_exact_artifact_format(path, role)
    if detected == "unsupported":
        raise CurrentLoopError("artifact_format_unsupported")
    after_stat = path.stat()
    if (
        before_stat.st_mtime_ns != after_stat.st_mtime_ns
        or before_stat.st_size != after_stat.st_size
        or before_stat.st_ino != after_stat.st_ino
        or before_stat.st_mode != after_stat.st_mode
    ):
        raise CurrentLoopError("artifact_changed_during_satisfaction_check")
    return {
        "schema_id": SATISFACTION_SCHEMA_ID,
        "disposition": (
            "pre_existing_exact_artifact"
            if origin == "pre_existing"
            else "explicitly_user_selected_or_supplied"
        ),
        "role": role,
        "content_digest": digest,
        "size_bytes": len(raw),
        "detected_format": detected,
        "native_write_required": False,
        "native_write_permission_required": False,
        "bytes_changed": False,
        "timestamp_changed": False,
        "permissions_changed": False,
        "assistant_created_provenance_claimed": False,
        "directory_or_repository_discovery_performed": False,
        "role_specific_eligibility_required": True,
    }


def satisfaction_contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": SATISFACTION_SCHEMA_ID,
        "dispositions": list(SATISFACTION_DISPOSITIONS),
        "identical_source_implies_runtime_circuit_eligible": False,
        "native_write_required_for_preexisting_exact": False,
        "false_assistant_creation_provenance_permitted": False,
        "directory_or_repository_discovery_permitted": False,
    }
