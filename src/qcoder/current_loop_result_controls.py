"""Read-only evaluation of exact selected result-evidence controls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from qcoder.current_loop import MAX_LOCAL_FILE_BYTES
from qcoder.current_loop_artifact_targets import (
    ArtifactTargetError,
    normalize_selected_artifact_paths,
)
from qcoder.current_loop_evidence_processing import detect_exact_artifact_format
from qcoder.current_loop_result_manifest import (
    StrictResultManifestError,
    normalize_strict_result_manifest,
)


RESULT_CONTROL_PROJECTION_SCHEMA_ID = "qcoder.current_loop.selected_result_controls.v1"


class ResultControlError(ValueError):
    """A bounded selected control could not be evaluated safely."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _read_exact(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ResultControlError("selected_artifact_exact_file_required")
    raw = path.read_bytes()
    if len(raw) > MAX_LOCAL_FILE_BYTES:
        raise ResultControlError("selected_artifact_file_too_large")
    return raw


def evaluate_selected_result_controls(
    *,
    state: Mapping[str, Any],
    workspace_root: Path,
    selected_paths: Sequence[str],
) -> dict[str, Any]:
    """Evaluate exactly two selected controls without enrollment or currentness mutation."""

    try:
        targets = normalize_selected_artifact_paths(
            selected_paths,
            workspace_root=workspace_root,
            minimum_count=2,
            maximum_count=2,
        )
    except (ArtifactTargetError, OSError, RuntimeError) as exc:
        raise ResultControlError(str(exc)) from exc
    registry = state.get("evidence_registry")
    if not isinstance(registry, Mapping):
        raise ResultControlError("selected_result_control_registry_invalid")
    revisions = registry.get("artifact_revisions")
    role_heads = registry.get("role_heads")
    if not isinstance(revisions, Mapping) or not isinstance(role_heads, Mapping):
        raise ResultControlError("selected_result_control_registry_invalid")
    current_result = role_heads.get("results")
    current_result_revision = (
        revisions.get(current_result) if isinstance(current_result, str) else None
    )
    current_result_digest = (
        current_result_revision.get("content_digest")
        if isinstance(current_result_revision, Mapping)
        else None
    )
    prior_attempts = {
        binding.get("execution_attempt_id")
        for revision in revisions.values()
        if isinstance(revision, Mapping)
        and isinstance(binding := revision.get("strict_result_manifest_binding"), Mapping)
    }
    controls: list[dict[str, Any]] = []
    observed: list[tuple[Path, int, str]] = []
    for target in targets:
        path = target["absolute_path"]
        raw = _read_exact(path)
        digest = sha256(raw).hexdigest()
        observed.append((path, len(raw), digest))
        try:
            detected = detect_exact_artifact_format(path, "results")
        except (OSError, ValueError) as exc:
            raise ResultControlError(
                str(getattr(exc, "category", "selected_result_control_format_invalid"))
            ) from exc
        projection: dict[str, Any] = {
            "position": target["position"],
            "customer_selected_name": path.name,
            "content_digest": digest,
            "size_bytes": len(raw),
            "detected_format": detected,
            "registered": False,
            "current_result_evidence": False,
            "attributed_to_registered_circuit": False,
            "lineage_inferred_from_filename_or_workspace": False,
        }
        if detected == "qcoder_legacy_bare_counts":
            projection.update(
                {
                    "valid_result_evidence": False,
                    "disposition": "strict_manifest_and_causal_lineage_required",
                    "historical_non_current_eligibility": False,
                }
            )
        elif detected == "qcoder_strict_result_manifest":
            try:
                decoded = json.loads(raw.decode("utf-8"))
                if not isinstance(decoded, Mapping):
                    raise StrictResultManifestError("result_manifest_schema_invalid")
                manifest = normalize_strict_result_manifest(
                    decoded,
                    artifact_revisions=revisions,
                    expected_circuit_lineage=None,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, StrictResultManifestError) as exc:
                raise ResultControlError(
                    str(getattr(exc, "category", "result_manifest_schema_invalid"))
                ) from exc
            if manifest["execution_attempt_id"] in prior_attempts:
                raise ResultControlError("selected_result_control_attempt_already_registered")
            lineage = manifest["circuit_lineage"]
            projection.update(
                {
                    "valid_result_evidence": True,
                    "disposition": "explicit_selected_historical_non_current_only",
                    "historical_non_current_eligibility": True,
                    "circuit_lineage_status": lineage["status"],
                    "manifest_digest": manifest["manifest_digest"],
                    "limitations": list(manifest["limitations"]),
                }
            )
        else:
            raise ResultControlError("selected_result_control_format_unsupported")
        controls.append(projection)
    for path, expected_size, expected_digest in observed:
        raw = _read_exact(path)
        if len(raw) != expected_size or sha256(raw).hexdigest() != expected_digest:
            raise ResultControlError("selected_result_control_bytes_changed")
    bare_names = [
        str(item["customer_selected_name"])
        for item in controls
        if item["detected_format"] == "qcoder_legacy_bare_counts"
    ]
    unknown_names = [
        str(item["customer_selected_name"])
        for item in controls
        if item.get("circuit_lineage_status") == "unknown"
    ]
    disposition_sentences = []
    if bare_names:
        disposition_sentences.append(
            f"{', '.join(bare_names)} lacks the strict manifest and causal lineage required "
            "for current result evidence."
        )
    if unknown_names:
        disposition_sentences.append(
            f"{', '.join(unknown_names)} is valid only as unknown-lineage historical, "
            "non-current evidence."
        )
    disposition_sentences.append("Neither control changed the registered current result.")
    result = {
        "schema_id": RESULT_CONTROL_PROJECTION_SCHEMA_ID,
        "schema_version": 1,
        "ok": True,
        "operation": "evaluate_selected_result_evidence_controls",
        "customer_summary": " ".join(disposition_sentences),
        "selected_artifact_count": 2,
        "controls": controls,
        "current_result": {
            "artifact_revision_id": current_result,
            "content_digest": current_result_digest,
            "unchanged": True,
        },
        "state_revision": state.get("state_revision"),
        "state_mutated": False,
        "bootstrap_count": state.get("coordinator", {}).get("bootstrap_count"),
        "request_baseline_count": state.get("coordinator", {}).get("request_baseline_count"),
        "execution_performed": False,
        "workspace_discovery_performed": False,
        "neighboring_file_inspection_performed": False,
        "cli_or_help_required": False,
        "package_or_state_inspection_required": False,
        "raw_artifact_included": False,
        "absolute_path_included": False,
    }
    result["projection_digest"] = sha256(
        json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return result


__all__ = [
    "RESULT_CONTROL_PROJECTION_SCHEMA_ID",
    "ResultControlError",
    "evaluate_selected_result_controls",
]
