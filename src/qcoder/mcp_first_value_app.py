"""Versioned MCP resources for canonical Current Loop first-value delivery."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

FIRST_VALUE_APP_URI = "ui://qcoder/current-loop/first-value/v1"
FIRST_VALUE_APP_MIME = "text/html;profile=mcp-app"
REVIEW_REFERENCE_URI = "qcoder://current-loop/review-before-generation/v4"
OPERATIONS_REFERENCE_URI = "qcoder://current-loop/operations/v58"
AUTHORITY_REFERENCE_URI = "qcoder://current-loop/authority-continuation/v1"

_REFERENCES: dict[str, dict[str, Any]] = {
    REVIEW_REFERENCE_URI: {
        "schema_id": "qcoder.current_loop.review_before_generation.reference.v4",
        "preferred_proposal": "qcoder.connected_assistant.review_before_generation_proposal.v4",
        "legacy_accepted": ["qcoder.connected_assistant.review_before_generation_proposal.v3"],
        "first_call": ["request_text", "connected_assistant_proposal"],
        "delivery_modes": ["inline", "workspace_file"],
        "confirmation_actions": ["Use recommended choices", "Review or change choices"],
        "source_before_confirmation": False,
        "execution_authorized_by_confirmation": False,
    },
    OPERATIONS_REFERENCE_URI: {
        "schema_id": "qcoder.current_loop.operations.reference.v58",
        "operations": ["begin_current_loop", "complete_current_step"],
        "public_context_bridge_tool_count": 12,
        "new_operation": False,
    },
    AUTHORITY_REFERENCE_URI: {
        "schema_id": "qcoder.current_loop.authority_continuation.reference.v1",
        "token_only_actions": True,
        "displayed_revision_confirmation_is_first_delivery_authority": True,
        "workspace_containment_after_file_confirmation_only": True,
        "stale_token_rejected": True,
        "duplicate_confirmation_idempotent": True,
        "execution_authority_separate": True,
    },
}


def app_tool_metadata() -> dict[str, Any]:
    """Return current MCP Apps metadata without legacy home-grown keys."""

    return {"ui": {"resourceUri": FIRST_VALUE_APP_URI}}


def resource_descriptors() -> list[dict[str, Any]]:
    resources = [
        {
            "uri": FIRST_VALUE_APP_URI,
            "name": "qCoder canonical first value",
            "description": "Progressive MCP App rendering of the canonical Current Loop review.",
            "mimeType": FIRST_VALUE_APP_MIME,
            "_meta": {
                "ui": {
                    "csp": {"connectDomains": [], "resourceDomains": []},
                    "permissions": {},
                }
            },
        }
    ]
    resources.extend(
        {
            "uri": uri,
            "name": uri.rsplit("/", 1)[-1],
            "description": "Versioned share-safe qCoder Current Loop reference.",
            "mimeType": "application/json",
        }
        for uri in sorted(_REFERENCES)
    )
    return resources


def read_resource(uri: str) -> dict[str, Any] | None:
    if uri == FIRST_VALUE_APP_URI:
        text = (
            files("qcoder.mcp_apps")
            .joinpath("current_loop_first_value_v1.html")
            .read_text(encoding="utf-8")
        )
        return {
            "uri": uri,
            "mimeType": FIRST_VALUE_APP_MIME,
            "text": text,
            "_meta": {
                "ui": {
                    "csp": {"connectDomains": [], "resourceDomains": []},
                    "permissions": {},
                }
            },
        }
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
    "FIRST_VALUE_APP_MIME",
    "FIRST_VALUE_APP_URI",
    "OPERATIONS_REFERENCE_URI",
    "REVIEW_REFERENCE_URI",
    "app_tool_metadata",
    "read_resource",
    "resource_descriptors",
]
