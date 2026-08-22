"""Bounded, discovery-free artifact targets for one Current Step."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


ARTIFACT_TARGET_CONTRACT_SCHEMA_ID = "qcoder.current_loop.artifact_targets.v3"
SUPPORTED_TARGET_ROLES = ("source", "circuit_qasm", "results")
MAX_TARGET_PATH_BYTES = 4_096
_DISCOVERY_METACHARACTERS = frozenset("*?[]{}")


class ArtifactTargetError(ValueError):
    """A proposed Current Step target is not exact and bounded."""


def _normalize_relative_target(value: object, *, workspace_root: Path) -> dict[str, Any]:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_TARGET_PATH_BYTES
    ):
        raise ArtifactTargetError("intended_artifact_path_invalid")
    if any(character in value for character in _DISCOVERY_METACHARACTERS):
        raise ArtifactTargetError("intended_artifact_path_discovery_expression_prohibited")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ArtifactTargetError("intended_artifact_path_must_be_workspace_relative")
    if ".qcoder" in candidate.parts:
        raise ArtifactTargetError("qcoder_local_state_artifact_prohibited")
    workspace = Path(os.path.abspath(workspace_root))
    absolute = Path(os.path.abspath(workspace / candidate))
    try:
        absolute.relative_to(workspace)
    except ValueError as exc:
        raise ArtifactTargetError("intended_artifact_path_outside_workspace") from exc
    return {
        "workspace_relative_path": candidate.as_posix(),
        "exact_path_sha256": sha256(str(absolute).encode("utf-8")).hexdigest(),
        "workspace_discovery_permitted": False,
        "neighbor_artifact_discovery_permitted": False,
    }


def normalize_intended_artifact_targets(
    value: object,
    *,
    workspace_root: Path,
    required_roles: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Validate one exact target for every role authorized by current semantics."""

    roles = tuple(dict.fromkeys(str(role) for role in required_roles))
    if any(role not in SUPPORTED_TARGET_ROLES for role in roles):
        raise ArtifactTargetError("intended_artifact_role_unsupported")
    if not roles:
        if value in (None, {}):
            return {}
        raise ArtifactTargetError("intended_artifact_targets_not_applicable")
    if not isinstance(value, Mapping) or set(value) != set(roles):
        raise ArtifactTargetError("exact_intended_artifact_targets_required")
    normalized: dict[str, dict[str, Any]] = {}
    path_digests: set[str] = set()
    for role in roles:
        target = _normalize_relative_target(value[role], workspace_root=workspace_root)
        path_digest = str(target["exact_path_sha256"])
        if path_digest in path_digests:
            raise ArtifactTargetError("intended_artifact_targets_must_be_distinct")
        path_digests.add(path_digest)
        normalized[role] = target
    return normalized


def normalize_completion_artifact_path(
    value: object,
    *,
    workspace_root: Path,
) -> Path:
    """Translate the sole client-facing path form to a local absolute path.

    The private binding accepts only the exact workspace-relative representation used
    by the Current Step Contract. The coordinator continues to receive an absolute
    local path so hook adapters and the typed binding share its canonical validator.
    """

    try:
        target = _normalize_relative_target(value, workspace_root=workspace_root)
    except ArtifactTargetError as exc:
        raise ArtifactTargetError(
            "completion_artifact_path_must_be_bound_workspace_relative"
        ) from exc
    return Path(os.path.abspath(Path(workspace_root) / str(target["workspace_relative_path"])))


def current_registered_role_target(
    state: Mapping[str, Any],
    *,
    role: str,
    workspace_root: Path,
) -> dict[str, Any] | None:
    """Return one exact role-head target without discovering neighboring files."""

    if role not in SUPPORTED_TARGET_ROLES:
        raise ArtifactTargetError("intended_artifact_role_unsupported")
    registry = state.get("evidence_registry")
    if not isinstance(registry, Mapping):
        raise ArtifactTargetError("current_role_target_registry_invalid")
    heads = registry.get("role_heads")
    revisions = registry.get("artifact_revisions")
    if not isinstance(heads, Mapping) or not isinstance(revisions, Mapping):
        raise ArtifactTargetError("current_role_target_registry_invalid")
    revision_id = heads.get(role)
    if revision_id is None:
        return None
    revision = revisions.get(revision_id) if isinstance(revision_id, str) else None
    if (
        not isinstance(revision, Mapping)
        or revision.get("logical_role") != role
        or revision.get("artifact_revision_id") != revision_id
        or revision.get("workspace_binding") != str(workspace_root)
        or not isinstance(revision.get("exact_path"), str)
    ):
        raise ArtifactTargetError("current_role_target_revision_invalid")
    workspace = Path(os.path.abspath(workspace_root))
    candidate = Path(os.path.abspath(str(revision["exact_path"])))
    try:
        relative = candidate.relative_to(workspace)
    except ValueError as exc:
        raise ArtifactTargetError("current_role_target_outside_workspace") from exc
    if (
        candidate.is_symlink()
        or not candidate.is_file()
        or candidate.resolve(strict=True) != candidate
    ):
        raise ArtifactTargetError("current_role_target_file_unavailable")
    if sha256(candidate.read_bytes()).hexdigest() != revision.get("content_digest"):
        raise ArtifactTargetError("current_role_target_bytes_changed")
    target = _normalize_relative_target(relative.as_posix(), workspace_root=workspace)
    if target["exact_path_sha256"] != revision.get("path_digest"):
        raise ArtifactTargetError("current_role_target_path_identity_mismatch")
    target.update(
        {
            "binding_mode": "registered_current_role_head_exact_target",
            "artifact_revision_id": revision_id,
            "content_digest": revision.get("content_digest"),
        }
    )
    return target


def target_contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": ARTIFACT_TARGET_CONTRACT_SCHEMA_ID,
        "supported_roles": list(SUPPORTED_TARGET_ROLES),
        "selection_source": ("fresh_assistant_bound_target_or_active_loop_registered_role_head"),
        "active_loop_replacement_reuses_registered_role_head": True,
        "different_replacement_target_requires_exact_customer_path_selection": True,
        "path_form": "workspace_relative_exact_path",
        "completion_path_form": "same_workspace_relative_exact_path",
        "absolute_completion_path_accepted_from_assistant": False,
        "binding_translates_completion_path_to_local_absolute": True,
        "one_target_per_authorized_role": True,
        "discovery_or_glob_permitted": False,
        "neighbor_artifact_discovery_permitted": False,
        "completion_exact_path_match_required": True,
    }


__all__ = [
    "ARTIFACT_TARGET_CONTRACT_SCHEMA_ID",
    "ArtifactTargetError",
    "MAX_TARGET_PATH_BYTES",
    "SUPPORTED_TARGET_ROLES",
    "current_registered_role_target",
    "normalize_completion_artifact_path",
    "normalize_intended_artifact_targets",
    "target_contract_snapshot",
]
