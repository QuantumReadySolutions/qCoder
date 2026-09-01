"""Versioned non-UI Current Loop reference resources."""

from __future__ import annotations

import json
from typing import Any

REVIEW_REFERENCE_URI = "qcoder://current-loop/review-before-generation/v5"
OPERATIONS_REFERENCE_URI = "qcoder://current-loop/operations/v59"
AUTHORITY_REFERENCE_URI = "qcoder://current-loop/authority-continuation/v2"

_REFERENCES: dict[str, dict[str, Any]] = {
    REVIEW_REFERENCE_URI: {
        "schema_id": "qcoder.current_loop.review_before_generation.reference.v5",
        "first_call": ["request_text", "review_content"],
        "model_supplies": [
            "interpretation",
            "implementation_recommendations",
            "output_artifact",
            "limitations",
            "blocking_question",
            "proposed_source_target",
        ],
        "qcoder_derives_routing_and_authority": True,
        "confirmation_actions": ["Use recommended choices", "Review or change choices"],
        "source_before_confirmation": False,
        "execution_authorized_by_confirmation": False,
    },
    OPERATIONS_REFERENCE_URI: {
        "schema_id": "qcoder.current_loop.operations.reference.v59",
        "operations": ["begin_current_loop", "complete_current_step"],
        "public_context_bridge_tool_count": 12,
        "new_operation": False,
    },
    AUTHORITY_REFERENCE_URI: {
        "schema_id": "qcoder.current_loop.authority_continuation.reference.v2",
        "token_only_actions": True,
        "displayed_revision_confirmation_is_first_delivery_authority": True,
        "workspace_containment_after_file_confirmation_only": True,
        "stale_token_rejected": True,
        "duplicate_confirmation_idempotent": True,
        "execution_authority_separate": True,
    },
}


def resource_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "uri": uri,
            "name": uri.rsplit("/", 1)[-1],
            "description": "Versioned share-safe qCoder Current Loop reference.",
            "mimeType": "application/json",
        }
        for uri in sorted(_REFERENCES)
    ]


def read_resource(uri: str) -> dict[str, Any] | None:
    value = _REFERENCES.get(uri)
    if value is None:
        return None
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    }


__all__ = [
    "AUTHORITY_REFERENCE_URI",
    "OPERATIONS_REFERENCE_URI",
    "REVIEW_REFERENCE_URI",
    "read_resource",
    "resource_descriptors",
]
