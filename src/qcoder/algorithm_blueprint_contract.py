"""Policy-free canonical artifact digest contract."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


def _without_digest(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _without_digest(item)
            for key, item in value.items()
            if str(key) != "artifact_digest"
        }
    if isinstance(value, list):
        return [_without_digest(item) for item in value]
    return value


def canonical_artifact_digest(artifact: dict[str, Any]) -> str:
    canonical = json.dumps(
        _without_digest(artifact),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def with_artifact_digest(artifact: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(artifact)
    result["artifact_digest"] = canonical_artifact_digest(result)
    return result


def artifact_digest_matches(artifact: object) -> bool:
    if not isinstance(artifact, dict):
        return False
    supplied = artifact.get("artifact_digest")
    return isinstance(supplied, str) and supplied == canonical_artifact_digest(artifact)
