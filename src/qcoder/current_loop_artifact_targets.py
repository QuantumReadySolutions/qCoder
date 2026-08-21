"""Bounded, discovery-free artifact targets for one Current Step."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


ARTIFACT_TARGET_CONTRACT_SCHEMA_ID = "qcoder.current_loop.artifact_targets.v1"
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


def target_contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": ARTIFACT_TARGET_CONTRACT_SCHEMA_ID,
        "supported_roles": list(SUPPORTED_TARGET_ROLES),
        "selection_source": "assistant_supplied_with_exact_begin_request",
        "path_form": "workspace_relative_exact_path",
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
    "normalize_intended_artifact_targets",
    "target_contract_snapshot",
]
