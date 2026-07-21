from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Callable
import urllib.error
import urllib.request

from qcoder.algorithm_blueprint import (
    ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS,
    ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS,
    ALGORITHM_BLUEPRINT_TOOL_NAMES,
    ALGORITHM_BLUEPRINT_TOOL_REQUIRED_FIELDS,
    CONFIRMATION_STATES,
    EVIDENCE_COVERAGE_VALUES,
    ORIGIN_VALUES,
    PROFILE_IDS,
    algorithm_blueprint_contract_snapshot,
)

DEFAULT_BASE_URL = "https://preview-api.qcoder.ai"
ROUTE_PATH = "/v0/internal/hosted-mcp/context"
EXPECTED_TOOLS = (
    "get_guided_evidence_context",
    "create_prompt_context",
    "create_evidence_context_pack",
    "create_context_session_card",
    "create_run_readiness_card",
    "create_result_review_context_card",
    "create_next_check_plan",
    "create_single_loop_evidence_diff",
    *ALGORITHM_BLUEPRINT_TOOL_NAMES,
)
TOOL_ALIASES = {
    "get_context_from_share_safe_artifact": "get_guided_evidence_context",
    "build_assistant_prompt_context": "create_prompt_context",
}
PROMPT_CONTEXT_MODES = frozenset(
    {
        "explain",
        "review",
        "revise",
        "troubleshoot",
        "plan_next_checks",
    }
)
TOOL_INPUT_FIELDS = {
    "get_guided_evidence_context": frozenset({"artifact_text", "artifact_kind", "client_context"}),
    "create_prompt_context": frozenset(
        {"artifact_text", "artifact_kind", "client_context", "mode"}
    ),
    "create_evidence_context_pack": frozenset(
        {"artifact_text", "artifact_kind", "client_context", "current_goal", "evidence_basis"}
    ),
    "create_context_session_card": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
        }
    ),
    "create_run_readiness_card": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
        }
    ),
    "create_result_review_context_card": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "share_safe_evidence_summary",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
        }
    ),
    "create_next_check_plan": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
        }
    ),
    "create_single_loop_evidence_diff": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "before",
            "after",
        }
    ),
    **ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS,
}
TOOL_REQUIRED_FIELDS = {
    tool_name: ("artifact_text",)
    for tool_name in EXPECTED_TOOLS
    if tool_name not in ALGORITHM_BLUEPRINT_TOOL_NAMES
}
TOOL_REQUIRED_FIELDS.update(ALGORITHM_BLUEPRINT_TOOL_REQUIRED_FIELDS)
EVIDENCE_CONFIDENCE_LABELS = (
    (
        "observed",
        "Observed",
        "Information directly present in the explicitly supplied circuit, result, or workflow evidence.",
    ),
    (
        "user_provided",
        "User-provided",
        "Information asserted or entered by the user but not independently verified by qCoder.",
    ),
    (
        "inferred",
        "Inferred",
        "A bounded interpretation derived from explicitly supplied evidence.",
    ),
    (
        "assumed",
        "Assumed",
        "A premise used to organize or interpret the supplied evidence but not established by it.",
    ),
    (
        "not_proven",
        "Not proven",
        "A statement, explanation, property, outcome, or conclusion that the supplied evidence does not establish.",
    ),
    (
        "suggested_next_check",
        "Suggested next check",
        "An ordered, user-controlled recommendation for obtaining more evidence or resolving uncertainty.",
    ),
)
EVIDENCE_REVIEW_ARTIFACT_DISCRIMINATORS = {
    "get_guided_evidence_context": {"field": "context_status", "value": "assistant_context_ready"},
    "create_prompt_context": {"field": "context_status", "value": "prompt_context_ready"},
    "create_evidence_context_pack": {"field": "pack_type", "value": "share_safe_current_evidence"},
    "create_context_session_card": {"field": "card_type", "value": "share_safe_current_session"},
    "create_run_readiness_card": {
        "field": "card_type",
        "value": "share_safe_current_run_readiness",
    },
    "create_result_review_context_card": {
        "field": "card_type",
        "value": "share_safe_current_result_review",
    },
    "create_next_check_plan": {
        "field": "plan_type",
        "value": "bounded_current_request_next_checks",
    },
    "create_single_loop_evidence_diff": {
        "field": "diff_type",
        "value": "explicit_before_after_current_loop",
    },
    **ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS,
}
EVIDENCE_REVIEW_BOUNDARIES = (
    "current artifact and current session only",
    "explicitly supplied evidence only; no hidden lookup",
    "process-and-discard with no retained artifacts",
    "no project memory, evidence history, or multi-run comparison",
    "no repository access or file editing",
    "no autonomous execution",
    "no correctness verification, runtime or fidelity prediction, backend ranking, or quantum-advantage claim",
)
DEFAULT_ARTIFACT_KIND = "share_safe_evidence_summary"
MAX_ARTIFACT_TEXT_CHARS = 20_000
FORBIDDEN_TEXT_MARKERS = (
    "openqasm",
    "qreg ",
    "creg ",
    "counts=",
    '"counts"',
    "'counts'",
    "/home/",
    "\\users\\",
    "c:\\",
    "../",
    "repo_path",
    "file_path",
    "repository_root",
    "directory_root",
    "workspace_root",
    "source_code",
    '"command"',
    "raw_qasm",
    "raw_counts",
    "provider_result",
    "result_payload",
    "raw_provider_result",
    "artifact_id",
    "stored_card_id",
    "prior_session_id",
    "session_id",
    "raw_source",
    "notebook",
    ".ipynb",
    "project memory",
    "prior run history",
    "multi-run comparison",
    "remember it",
    "compare with prior run",
    "backend selection",
    "rank backends",
    "optimize shots",
    "execute this",
    "edit code",
)
FORBIDDEN_PAYLOAD_FIELDS = frozenset(
    {
        "file_path",
        "path",
        "workspace_path",
        "workspace_root",
        "repository_root",
        "directory_root",
        "source_path",
        "notebook_path",
        "raw_source",
        "source_code",
        "source_excerpt",
        "raw_circuit",
        "raw_qasm",
        "qasm_text",
        "raw_counts",
        "counts",
        "provider_result",
        "provider_result_payload",
        "raw_provider_result",
        "result_payload",
        "mcp_payload",
        "stored_card_id",
        "prior_session_id",
        "session_id",
        "artifact_id",
        "command",
        "token",
        "authorization",
    }
)


def default_token_file() -> Path:
    return Path.home() / ".qcoder" / "context-bridge" / "token.txt"


def safe_error(error_category: str, *, status_category: str = "adapter_rejected") -> dict[str, Any]:
    return {
        "ok": False,
        "error_category": error_category,
        "status_category": status_category,
        "retention": "process_and_discard",
        "retained_artifacts": [],
        "token_printed": False,
        "raw_payload_printed": False,
        "raw_response_printed": False,
    }


def validate_token_file(token_file: str | Path) -> tuple[bool, str, str]:
    path = Path(token_file)
    if not path.is_file():
        return False, "token_file_missing", ""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return False, "token_file_unreadable", ""
    if os.name != "nt" and mode & 0o077:
        return False, "token_file_permissions_unsafe", ""
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "token_file_unreadable", ""
    if not token:
        return False, "token_file_empty", ""
    if "\n" in token or "\r" in token:
        return False, "token_file_malformed", ""
    return True, "ok", token


def validate_artifact_text(artifact_text: object) -> str:
    if not isinstance(artifact_text, str) or not artifact_text.strip():
        return "artifact_text_missing"
    if len(artifact_text) > MAX_ARTIFACT_TEXT_CHARS:
        return "artifact_text_too_large"
    lowered = artifact_text.lower()
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        return "forbidden_input_value"
    return "ok"


def validate_optional_payload(value: object) -> str:
    if value is None:
        return "ok"
    try:
        serialized = json.dumps(value, sort_keys=True)
    except TypeError:
        return "payload_not_json_serializable"
    if len(serialized) > MAX_ARTIFACT_TEXT_CHARS:
        return "artifact_text_too_large"
    if _contains_forbidden_payload_field(value):
        return "forbidden_input_value"
    for text_value in _payload_text_values(value):
        lowered = text_value.lower()
        if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
            return "forbidden_input_value"
    return "ok"


def _contains_forbidden_payload_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in FORBIDDEN_PAYLOAD_FIELDS
            or _contains_forbidden_payload_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_payload_field(item) for item in value)
    return False


def _payload_text_values(value: object) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_payload_text_values(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_payload_text_values(item))
        return result
    return [value] if isinstance(value, str) else []


def _has_explicit_side(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(str(nested).strip() for nested in value.values())
    return False


def decode_json(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "error_category": "non_json_response"}
    return (
        decoded
        if isinstance(decoded, dict)
        else {"ok": False, "error_category": "non_object_response"}
    )


def _retry_after_category(value: object) -> str:
    retry_after = str(value or "").strip()
    if not retry_after:
        return "absent"
    if retry_after.isdigit():
        return "seconds"
    if "," in retry_after and ":" in retry_after:
        return "http_date"
    return "present_unparsed"


def _canonical_tool_name(tool_name: str) -> str:
    return TOOL_ALIASES.get(tool_name, tool_name)


def _client_visible_tool_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Expose nested core-contract metadata without changing the service response."""

    if tool_name != "create_run_readiness_card" or payload.get("ok") is not True:
        return payload
    readiness_card = payload.get("readiness_card")
    if not isinstance(readiness_card, dict):
        return payload
    labels = readiness_card.get("evidence_confidence_labels")
    if not isinstance(labels, list) or not labels:
        return payload
    projected = dict(payload)
    projected.setdefault("evidence_confidence_labels", labels)
    return projected


def evidence_review_contract_snapshot() -> dict[str, Any]:
    """Return the sanitized adapter contract mirrored by the protected implementation."""

    return {
        "capability": "Evidence Review",
        "tool_names": list(EXPECTED_TOOLS),
        "prompt_context_modes": sorted(PROMPT_CONTEXT_MODES),
        "confidence_labels": [
            {"value": value, "display": display}
            for value, display, _meaning in EVIDENCE_CONFIDENCE_LABELS
        ],
        "tool_input_fields": {name: sorted(TOOL_INPUT_FIELDS[name]) for name in EXPECTED_TOOLS},
        "required_request_properties": {
            name: list(TOOL_REQUIRED_FIELDS[name]) for name in EXPECTED_TOOLS
        },
        "compatibility_aliases": dict(sorted(TOOL_ALIASES.items())),
        "artifact_discriminators": EVIDENCE_REVIEW_ARTIFACT_DISCRIMINATORS,
        "context_scope": "current_artifact_current_session",
        "retention": "process_and_discard",
        "boundaries": list(EVIDENCE_REVIEW_BOUNDARIES),
        "algorithm_blueprint": algorithm_blueprint_contract_snapshot(),
    }


def post_context_bridge(
    *,
    base_url: str,
    token_file: str | Path,
    tool_name: str,
    artifact_text: object,
    artifact_kind: str = DEFAULT_ARTIFACT_KIND,
    client_context: dict[str, Any] | None = None,
    mode: str | None = None,
    current_goal: object | None = None,
    evidence_basis: object | None = None,
    share_safe_evidence_summary: object | None = None,
    open_questions: object | None = None,
    explicit_assumptions: object | None = None,
    current_card_context: object | None = None,
    before: object | None = None,
    after: object | None = None,
    tool_arguments: dict[str, Any] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    canonical_tool_name = _canonical_tool_name(tool_name)
    if canonical_tool_name not in EXPECTED_TOOLS:
        return safe_error("unknown_tool")
    direct_arguments = {
            "mode": mode,
            "current_goal": current_goal,
            "evidence_basis": evidence_basis,
            "share_safe_evidence_summary": share_safe_evidence_summary,
            "open_questions": open_questions,
            "explicit_assumptions": explicit_assumptions,
            "current_card_context": current_card_context,
            "before": before,
            "after": after,
    }
    arguments = dict(tool_arguments or {})
    for key, value in direct_arguments.items():
        if value is not None:
            if key in arguments and arguments[key] != value:
                return safe_error("conflicting_tool_argument")
            arguments[key] = value
    supplied_fields = set(arguments)
    if artifact_text is not None:
        supplied_fields.add("artifact_text")
    supplied_fields.update({"artifact_kind", "client_context"})
    if supplied_fields - TOOL_INPUT_FIELDS[canonical_tool_name]:
        return safe_error("unsupported_tool_argument")
    if mode is not None:
        if canonical_tool_name != "create_prompt_context":
            return safe_error("mode_not_supported_for_tool")
        if str(mode).strip() not in PROMPT_CONTEXT_MODES:
            return safe_error("invalid_prompt_context_mode")
    if canonical_tool_name == "create_single_loop_evidence_diff" and (
        not _has_explicit_side(arguments.get("before"))
        or not _has_explicit_side(arguments.get("after"))
    ):
        return safe_error("missing_explicit_diff_side")
    if artifact_kind != DEFAULT_ARTIFACT_KIND:
        return safe_error("unsupported_artifact_kind")
    if "artifact_text" in TOOL_REQUIRED_FIELDS[canonical_tool_name] or artifact_text is not None:
        text_validation = validate_artifact_text(artifact_text)
        if text_validation != "ok":
            return safe_error(text_validation)
    for required_field in TOOL_REQUIRED_FIELDS[canonical_tool_name]:
        required_value = artifact_text if required_field == "artifact_text" else arguments.get(required_field)
        if required_value is None or required_value == "" or required_value == [] or required_value == {}:
            return safe_error(f"missing_{required_field}")
    for payload in arguments.values():
        payload_validation = validate_optional_payload(payload)
        if payload_validation != "ok":
            return safe_error(payload_validation)
    token_ok, token_category, token = validate_token_file(token_file)
    if not token_ok:
        return safe_error(token_category, status_category="auth_preflight_failed")

    body: dict[str, Any] = {
        "tool_name": canonical_tool_name,
        "artifact_kind": artifact_kind,
        "client_context": {
            "client_version": "qcoder-context-bridge-mcp-adapter",
            **(client_context or {}),
        },
    }
    if artifact_text is not None:
        body["artifact_text"] = artifact_text
    body.update(arguments)
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + ROUTE_PATH,
        data=data,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
        method="POST",
    )
    urlopen = opener or urllib.request.urlopen
    try:
        with urlopen(request, timeout=20) as response:
            status = int(response.status)
            payload = decode_json(response.read())
            retry_after = (
                response.headers.get("Retry-After") if getattr(response, "headers", None) else None
            )
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        payload = decode_json(exc.read())
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
    except Exception:
        return safe_error("context_bridge_unreachable", status_category="network_error")

    payload.setdefault(
        "adapter_status_category", "success_2xx" if 200 <= status < 300 else f"http_{status}"
    )
    payload.setdefault("token_printed", False)
    payload.setdefault("raw_payload_printed", False)
    payload.setdefault("raw_response_printed", False)
    if status == 429:
        payload.setdefault("retry_after_category", _retry_after_category(retry_after))
    return payload


def _tool_property_schemas() -> dict[str, dict[str, Any]]:
    diff_side_properties = {
        "goal": {"type": "string"},
        "evidence_state": {"type": "string"},
        "result_evidence": {"type": "string"},
        "evidence": {"type": "string"},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "expectations": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "artifact_text": {
            "type": "string",
            "description": "Share-safe current qCoder evidence summary. Raw circuits, counts, paths, notebooks, and source files are rejected.",
        },
        "artifact_kind": {
            "type": "string",
            "enum": [DEFAULT_ARTIFACT_KIND],
            "default": DEFAULT_ARTIFACT_KIND,
        },
        "client_context": {
            "type": "object",
            "additionalProperties": True,
            "description": "Optional client metadata without secrets, paths, or raw artifacts.",
        },
        "mode": {
            "type": "string",
            "enum": sorted(PROMPT_CONTEXT_MODES),
            "description": "Optional create_prompt_context handoff mode.",
        },
        "current_goal": {
            "type": "string",
            "description": "Bounded goal for the current workflow request.",
        },
        "evidence_basis": {
            "type": "string",
            "description": "Compact share-safe evidence basis supplied for this current request.",
        },
        "share_safe_evidence_summary": {
            "type": "string",
            "description": "Compact user-provided result evidence for current-request review.",
        },
        "open_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Current user-controlled questions or candidate checks to preserve when safely relevant.",
        },
        "explicit_assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Assumptions explicitly supplied by the user for this request.",
        },
        "current_card_context": {
            "type": "object",
            "additionalProperties": True,
            "description": "Optional current-request card context without secrets, paths, or raw artifacts.",
        },
        "before": {
            "type": "object",
            "description": (
                "Explicit structured before context for Single-Loop Evidence Diff. Preserve salient user-provided "
                "observations instead of replacing them with generic summaries."
            ),
            "properties": diff_side_properties,
            "additionalProperties": False,
        },
        "after": {
            "type": "object",
            "description": (
                "Explicit structured after context for Single-Loop Evidence Diff. Keep salient user-reported result "
                "observations rather than reducing them to generic 'result evidence is present' wording."
            ),
            "properties": diff_side_properties,
            "additionalProperties": False,
        },
        "original_user_intent": {
            "type": "string",
            "description": "Original user request preserved in the Algorithm Intent Card.",
        },
        "profile_id": {
            "type": "string",
            "enum": list(PROFILE_IDS),
            "description": "Explicitly selected Algorithm Blueprint profile.",
        },
        "proposed_interpretation": {
            "type": "object",
            "additionalProperties": True,
            "description": "Assistant- or user-supplied proposed structured interpretation; qCoder validates but does not authoritatively infer it.",
        },
        "requirements": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "non_goals": {"type": "array", "items": {"type": "string"}},
        "field_provenance": {
            "type": "object",
            "additionalProperties": {"type": "string", "enum": list(ORIGIN_VALUES)},
        },
        "revision_notes": {"type": "array", "items": {"type": "string"}},
        "requested_confirmation_state": {
            "type": "string",
            "enum": list(CONFIRMATION_STATES),
            "default": "proposed",
        },
        "confirmation_assertion": {
            "type": "object",
            "properties": {"user_reviewed": {"type": "boolean"}},
            "required": ["user_reviewed"],
            "additionalProperties": False,
            "description": "Explicit assertion that the user reviewed the supplied interpretation; not identity or scientific verification.",
        },
        "accepted_unresolved_choices": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Named unresolved fields the user explicitly accepts retaining in a confirmed card.",
        },
        "algorithm_intent_card": {
            "type": "object",
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "original_user_intent",
                "field_provenance",
                "confirmation_state",
            ],
            "additionalProperties": True,
            "description": "Explicitly supplied current-session Algorithm Intent Card.",
        },
        "intent_relationship": {
            "type": "object",
            "properties": {
                "relationship_type": {"type": "string", "enum": ["represented_by"]},
                "parent_artifact_digest": {"type": "string"},
            },
            "required": ["relationship_type", "parent_artifact_digest"],
            "additionalProperties": False,
        },
        "implementation_blueprint": {
            "type": "object",
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "confirmation_state",
            ],
            "additionalProperties": True,
            "description": "Explicitly supplied confirmed current-session Implementation Blueprint.",
        },
        "output_evidence_contract": {
            "type": "object",
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "parent_artifact_digest",
                "expected_evidence",
            ],
            "additionalProperties": True,
            "description": "Explicitly supplied Output Evidence Contract returned with the blueprint.",
        },
        "selected_python_source_evidence": {
            "type": "object",
            "properties": {
                "artifact_type": {"type": "string", "enum": ["selected_python_source_evidence"]},
                "schema_version": {"type": "integer", "enum": [1]},
                "artifact_digest": {"type": "string"},
                "logical_source_label": {"type": "string"},
                "safe_basename": {"type": ["string", "null"]},
                "selected_symbol": {"type": ["string", "null"]},
                "bounded_line_span": {
                    "type": ["array", "null"],
                    "items": {"type": "integer"},
                },
                "origin": {"type": "string", "enum": list(ORIGIN_VALUES)},
                "evidence_scope": {"type": "string"},
                "evidence_coverage": {
                    "type": "string",
                    "enum": list(EVIDENCE_COVERAGE_VALUES),
                },
                "parse_status": {"type": "string"},
                "framework_observation": {"type": "string"},
                "imports_and_aliases": {"type": "array", "items": {"type": "object"}},
                "circuit_construction_symbols": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "parameter_declarations": {"type": "array", "items": {"type": "object"}},
                "measurement_calls": {"type": "array", "items": {"type": "object"}},
                "functions": {"type": "array", "items": {"type": "object"}},
                "classes": {"type": "array", "items": {"type": "object"}},
                "profile_motif_observations": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "source_references": {"type": "array", "items": {"type": "integer"}},
                "ambiguities": {"type": "array", "items": {"type": "string"}},
                "extraction_limitations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "raw_source_included": {"type": "boolean", "enum": [False]},
                "repository_scanned": {"type": "boolean", "enum": [False]},
                "source_executed": {"type": "boolean", "enum": [False]},
                "source_edited": {"type": "boolean", "enum": [False]},
                "retention": {"type": "string", "enum": ["process_and_discard"]},
                "development_evidence": {
                    "type": "object",
                    "properties": {
                        "schema_id": {
                            "type": "string",
                            "enum": ["qcoder.development_evidence.v0"],
                        },
                        "schema_version": {"type": "integer", "enum": [0]},
                        "artifact_kind": {
                            "type": "string",
                            "enum": ["selected_python_source_development_evidence"],
                        },
                        "development_stage": {"type": "string", "enum": ["python_source"]},
                        "framework": {"type": "string", "enum": ["qiskit"]},
                        "working_transition": {
                            "type": "array",
                            "prefixItems": [
                                {"type": "string", "enum": ["human_intent"]},
                                {"type": "string", "enum": ["python_source"]},
                            ],
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "artifact_reference": {"type": "object"},
                        "relationships": {"type": "array", "items": {"type": "object"}},
                        "motif_expectations": {"type": "array", "items": {"type": "object"}},
                        "motif_observations": {"type": "array", "items": {"type": "object"}},
                        "alignment_findings": {"type": "array", "items": {"type": "object"}},
                        "implementation_decision_summary": {"type": ["object", "null"]},
                        "later_stage_analysis_performed": {
                            "type": "boolean",
                            "enum": [False],
                        },
                    },
                    "required": [
                        "schema_id",
                        "schema_version",
                        "artifact_kind",
                        "development_stage",
                        "framework",
                        "working_transition",
                        "artifact_reference",
                        "relationships",
                        "motif_expectations",
                        "motif_observations",
                        "alignment_findings",
                        "later_stage_analysis_performed",
                    ],
                    "additionalProperties": True,
                    "description": (
                        "Optional share-safe current-session Development Evidence v0 data. "
                        "It contains no raw source, raw path, stable source identifier, or later-stage analysis."
                    ),
                },
            },
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "evidence_scope",
                "evidence_coverage",
                "parse_status",
                "raw_source_included",
            ],
            "additionalProperties": False,
            "description": "Compact machine-local static evidence only; paths and raw source are not accepted.",
        },
    }


def _tool_schema(tool_name: str) -> dict[str, Any]:
    property_schemas = _tool_property_schemas()
    return {
        "type": "object",
        "properties": {name: property_schemas[name] for name in TOOL_INPUT_FIELDS[tool_name]},
        "required": list(TOOL_REQUIRED_FIELDS[tool_name]),
        "additionalProperties": False,
    }


def tool_descriptors() -> list[dict[str, Any]]:
    descriptions = {
        "get_guided_evidence_context": "Create bounded assistant context from share-safe current qCoder evidence.",
        "create_prompt_context": (
            "Create a purpose-specific handoff context from current qCoder evidence, preserving Evidence Review "
            "labels, supported interpretations, unproven statements, and user-controlled next checks."
        ),
        "create_evidence_context_pack": "Create a current-evidence context packet with evidence limits and next-step framing.",
        "create_context_session_card": "Create a current-session context card without memory or history.",
        "create_run_readiness_card": (
            "Review current supplied evidence for readiness with applicable Observed, User-provided, Inferred, "
            "Assumed, Not proven, and Suggested next check labels, without claiming verification."
        ),
        "create_result_review_context_card": (
            "Review share-safe user-provided result evidence with Observed, User-provided, Inferred, Assumed, "
            "Not proven, and Suggested next check semantics."
        ),
        "create_next_check_plan": (
            "Create an ordered, bounded, user-controlled next-check plan tied to current-request evidence and "
            "uncertainties; qCoder does not execute the checks."
        ),
        "create_single_loop_evidence_diff": (
            "Describe what changed between two explicitly supplied current-loop contexts without history or lookup; "
            "this is not causal diagnosis or multi-run analysis. "
            "Use structured before/after fields and preserve salient user-provided result observations."
        ),
        "create_algorithm_intent_card": (
            "Preserve an explicitly supplied quantum algorithm request, validate a proposed interpretation, "
            "surface profile questions and provenance, and require explicit user-reviewed confirmation."
        ),
        "create_implementation_blueprint": (
            "Create a Qiskit-first Implementation Blueprint and distinct Output Evidence Contract from an "
            "explicitly supplied confirmed Algorithm Intent Card; no code or circuit is generated."
        ),
        "create_generation_context_pack": (
            "Create a current-session Generation Context Pack for external code generation from an explicitly "
            "supplied confirmed blueprint and matching evidence contract; qCoder does not invoke an assistant."
        ),
        "create_source_blueprint_alignment_review": (
            "Review compact machine-local Selected Python Source Evidence against a confirmed blueprint, scoped "
            "to supplied static evidence; no paths, raw source, execution, or correctness claim."
        ),
    }
    return [
        {"name": name, "description": descriptions[name], "inputSchema": _tool_schema(name)}
        for name in EXPECTED_TOOLS
    ]


def _jsonrpc_result(message_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(message_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def handle_jsonrpc_message(
    message: dict[str, Any],
    *,
    base_url: str,
    token_file: str | Path,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _jsonrpc_result(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "qcoder-context-bridge", "version": "1.0.0"},
            },
        )
    if method == "tools/list":
        return _jsonrpc_result(message_id, {"tools": tool_descriptors()})
    if method == "prompts/list":
        return _jsonrpc_result(message_id, {"prompts": []})
    if method == "resources/list":
        return _jsonrpc_result(message_id, {"resources": []})
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        tool_name = params.get("name")
        normalized_tool_name = str(tool_name or "")
        canonical_tool_name = _canonical_tool_name(normalized_tool_name)
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if (
            canonical_tool_name in TOOL_INPUT_FIELDS
            and set(arguments) - TOOL_INPUT_FIELDS[canonical_tool_name]
        ):
            payload = safe_error("unsupported_tool_argument")
            return _jsonrpc_result(
                message_id,
                {
                    "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                    "structuredContent": payload,
                    "isError": True,
                },
            )
        direct_field_names = {
            "mode",
            "current_goal",
            "evidence_basis",
            "share_safe_evidence_summary",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
            "before",
            "after",
        }
        payload = post_context_bridge(
            base_url=base_url,
            token_file=token_file,
            tool_name=normalized_tool_name,
            artifact_text=arguments.get("artifact_text"),
            artifact_kind=str(arguments.get("artifact_kind") or DEFAULT_ARTIFACT_KIND),
            client_context=arguments.get("client_context")
            if isinstance(arguments.get("client_context"), dict)
            else None,
            mode=str(arguments.get("mode")) if arguments.get("mode") is not None else None,
            current_goal=arguments.get("current_goal"),
            evidence_basis=arguments.get("evidence_basis"),
            share_safe_evidence_summary=arguments.get("share_safe_evidence_summary"),
            open_questions=arguments.get("open_questions"),
            explicit_assumptions=arguments.get("explicit_assumptions"),
            current_card_context=arguments.get("current_card_context"),
            before=arguments.get("before"),
            after=arguments.get("after"),
            tool_arguments={
                key: value
                for key, value in arguments.items()
                if key
                not in direct_field_names
                | {"artifact_text", "artifact_kind", "client_context"}
            },
            opener=opener,
        )
        payload = _client_visible_tool_payload(canonical_tool_name, payload)
        return _jsonrpc_result(
            message_id,
            {
                "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                "structuredContent": payload,
                "isError": payload.get("ok") is False,
            },
        )
    return _jsonrpc_error(message_id, -32601, "method_not_supported")


def serve_stdio(*, base_url: str, token_file: str | Path) -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _jsonrpc_error(None, -32700, "parse_error")
        else:
            if not isinstance(message, dict):
                response = _jsonrpc_error(None, -32600, "invalid_request")
            else:
                response = handle_jsonrpc_message(message, base_url=base_url, token_file=token_file)
        if response is None:
            continue
        print(json.dumps(response, sort_keys=True), flush=True)
    return 0


def _write_content_length_response(response: dict[str, Any]) -> None:
    data = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _read_mcp_headers(first_line: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    line = first_line
    while line:
        stripped = line.strip()
        if not stripped:
            break
        if b":" in stripped:
            key, value = stripped.split(b":", 1)
            headers[key.decode("ascii", errors="ignore").lower()] = value.decode(
                "ascii", errors="ignore"
            ).strip()
        line = sys.stdin.buffer.readline()
    return headers


def serve_mcp_stdio(*, base_url: str, token_file: str | Path) -> int:
    stdin = sys.stdin.buffer
    while True:
        first_line = stdin.readline()
        if not first_line:
            break
        if not first_line.strip():
            continue
        if first_line.lstrip().startswith(b"{"):
            try:
                message = json.loads(first_line.decode("utf-8"))
            except json.JSONDecodeError:
                response = _jsonrpc_error(None, -32700, "parse_error")
            else:
                response = handle_jsonrpc_message(message, base_url=base_url, token_file=token_file)
            if response is not None:
                print(json.dumps(response, sort_keys=True), flush=True)
            continue

        headers = _read_mcp_headers(first_line)
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            _write_content_length_response(_jsonrpc_error(None, -32600, "invalid_content_length"))
            continue
        if content_length <= 0:
            _write_content_length_response(_jsonrpc_error(None, -32600, "missing_content_length"))
            continue
        raw = stdin.read(content_length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            response = _jsonrpc_error(None, -32700, "parse_error")
        else:
            if not isinstance(message, dict):
                response = _jsonrpc_error(None, -32600, "invalid_request")
            else:
                response = handle_jsonrpc_message(message, base_url=base_url, token_file=token_file)
        if response is not None:
            _write_content_length_response(response)
    return 0


def _case_summary(*, payload: dict[str, Any], expected_success: bool) -> dict[str, Any]:
    serialized = json.dumps(payload, sort_keys=True)
    ok_value = payload.get("ok")
    retained = payload.get("retained_artifacts", [])
    status_category = str(
        payload.get("adapter_status_category") or payload.get("status_category") or "missing"
    )
    success = ok_value is True or status_category == "success_2xx"
    return {
        "expected_outcome_met": success if expected_success else not success,
        "ok_category": "true" if ok_value is True else "false" if ok_value is False else "missing",
        "status_category": status_category,
        "error_category": str(payload.get("error_category") or ""),
        "tool_name_category": payload.get("tool_name")
        if payload.get("tool_name") in EXPECTED_TOOLS
        else "other_or_missing",
        "context_status_category": str(payload.get("context_status") or "missing"),
        "retention_category": str(payload.get("retention") or "missing"),
        "retained_artifacts_empty_or_absent": retained in ([], None),
        "raw_payload_echo_absent": "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER" not in serialized,
        "token_printed": False,
        "raw_response_printed": False,
    }


def _run_full_smoke(*, base_url: str, token_file: str | Path) -> dict[str, Any]:
    token_ok, token_category, _ = validate_token_file(token_file)
    if not token_ok:
        return {
            "ok": False,
            "metadata_only": True,
            "token_file_category": token_category,
            "token_printed": False,
            "raw_token_printed": False,
            "instruction_category": "create_local_chmod_600_token_file",
        }
    safe_text = (
        "Share-safe current qCoder evidence summary. "
        "Small Bell-state style circuit workflow. Evidence summary says the user prepared "
        "a two-qubit entanglement example and wants bounded assistant context. "
        "No raw QASM, no raw counts, no file paths, no backend identifiers, and no source code are included. "
        "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER"
    )
    prompt_context_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="create_prompt_context",
        artifact_text=safe_text,
    )
    cases = {
        "guided_context_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "prompt_context_allowed": _case_summary(
            payload=prompt_context_payload,
            expected_success=True,
        ),
        "evidence_context_pack_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_evidence_context_pack",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "context_session_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_context_session_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "run_readiness_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_run_readiness_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "result_review_context_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_result_review_context_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "next_check_plan_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_next_check_plan",
                artifact_text=safe_text,
                current_goal="Choose the next bounded development check.",
                open_questions=["Which assumption should be clarified next?"],
                explicit_assumptions=[
                    "The evidence summary is share-safe and current-session only."
                ],
            ),
            expected_success=True,
        ),
        "single_loop_evidence_diff_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_single_loop_evidence_diff",
                artifact_text=safe_text,
                before={"summary": "Before context: readiness card requested one bounded check."},
                after={"summary": "After context: user-provided result evidence was reviewed."},
            ),
            expected_success=True,
        ),
        "raw_qasm_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="OPENQASM 2.0; qreg q[1];",
            ),
            expected_success=False,
        ),
        "repo_path_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="/home/private/project/source.py",
            ),
            expected_success=False,
        ),
        "artifact_lookup_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="artifact lookup request",
                artifact_kind="server_artifact_id",
            ),
            expected_success=False,
        ),
        "unknown_tool_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="suggest_next_checks",
                artifact_text=safe_text,
            ),
            expected_success=False,
        ),
        "invalid_prompt_mode_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_prompt_context",
                artifact_text=safe_text,
                mode="diagnose",
            ),
            expected_success=False,
        ),
        "diff_missing_side_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_single_loop_evidence_diff",
                artifact_text=safe_text,
                before={"summary": "before only"},
            ),
            expected_success=False,
        ),
    }
    prompt_mode_cases = (
        ("prompt_mode_explain_allowed", "explain"),
        ("prompt_mode_review_allowed", "review"),
        ("prompt_mode_revise_allowed", "revise"),
        ("prompt_mode_troubleshoot_allowed", "troubleshoot"),
        ("prompt_mode_plan_next_checks_allowed", "plan_next_checks"),
    )
    rate_limit_pause = (
        str(
            prompt_context_payload.get("adapter_status_category")
            or prompt_context_payload.get("status_category")
        )
        == "http_429"
    )
    retry_after_category = (
        str(prompt_context_payload.get("retry_after_category") or "absent")
        if rate_limit_pause
        else "absent"
    )
    if rate_limit_pause:
        for pending_name, _pending_mode in prompt_mode_cases:
            cases[pending_name] = {
                "expected_outcome_met": False,
                "ok_category": "missing",
                "status_category": "not_run_rate_limit_pause",
                "error_category": "",
                "tool_name_category": "create_prompt_context",
                "context_status_category": "missing",
                "retention_category": "process_and_discard",
                "retained_artifacts_empty_or_absent": True,
                "raw_payload_echo_absent": True,
                "token_printed": False,
                "raw_response_printed": False,
            }
    else:
        for index, (case_name, mode) in enumerate(prompt_mode_cases):
            payload = post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_prompt_context",
                artifact_text=safe_text,
                mode=mode,
            )
            cases[case_name] = _case_summary(payload=payload, expected_success=True)
            if (
                str(payload.get("adapter_status_category") or payload.get("status_category"))
                == "http_429"
            ):
                rate_limit_pause = True
                retry_after_category = str(payload.get("retry_after_category") or "absent")
                for pending_name, _pending_mode in prompt_mode_cases[index + 1 :]:
                    cases[pending_name] = {
                        "expected_outcome_met": False,
                        "ok_category": "missing",
                        "status_category": "not_run_rate_limit_pause",
                        "error_category": "",
                        "tool_name_category": "create_prompt_context",
                        "context_status_category": "missing",
                        "retention_category": "process_and_discard",
                        "retained_artifacts_empty_or_absent": True,
                        "raw_payload_echo_absent": True,
                        "token_printed": False,
                        "raw_response_printed": False,
                    }
                break

    approved = [
        "guided_context_allowed",
        "prompt_context_allowed",
        "evidence_context_pack_allowed",
        "context_session_card_allowed",
        "run_readiness_card_allowed",
        "result_review_context_card_allowed",
        "next_check_plan_allowed",
        "single_loop_evidence_diff_allowed",
        "prompt_mode_explain_allowed",
        "prompt_mode_review_allowed",
        "prompt_mode_revise_allowed",
        "prompt_mode_troubleshoot_allowed",
        "prompt_mode_plan_next_checks_allowed",
    ]
    unsafe = [
        "raw_qasm_rejected",
        "repo_path_rejected",
        "artifact_lookup_rejected",
        "unknown_tool_rejected",
        "invalid_prompt_mode_rejected",
        "diff_missing_side_rejected",
    ]
    result = {
        "ok": True,
        "metadata_only": True,
        "client_category": "qCoder Context Bridge MCP adapter",
        "token_source_category": "local_chmod_600_file",
        "tools_visible": list(EXPECTED_TOOLS),
        "tools_exact": True,
        "approved_tool_calls_passed": all(cases[name]["expected_outcome_met"] for name in approved),
        "unsafe_calls_rejected": all(cases[name]["expected_outcome_met"] for name in unsafe),
        "token_printed": False,
        "raw_payload_echo": "no"
        if all(case["raw_payload_echo_absent"] for case in cases.values())
        else "yes",
        "retention_category": "process_and_discard_or_rejected",
        "retained_artifacts_empty": "yes"
        if all(case["retained_artifacts_empty_or_absent"] for case in cases.values())
        else "no",
        "payment_auth_billing_mutation": "no",
        "public_claim_created": "no",
        "source_modified": "no",
        "diagnostic_mode": "full",
        "diagnostic_status_category": "rate_limit_pause_required"
        if rate_limit_pause
        else "complete",
        "retry_after_category": retry_after_category,
        "token_accepted": "yes",
        "token_onboarding_failure": False,
        "cases": cases,
    }
    result["all_expected_outcomes_met"] = (
        result["approved_tool_calls_passed"]
        and result["unsafe_calls_rejected"]
        and result["raw_payload_echo"] == "no"
        and result["retained_artifacts_empty"] == "yes"
    )
    result["ok"] = bool(result["all_expected_outcomes_met"])
    return result


def run_smoke(*, base_url: str, token_file: str | Path, full: bool = False) -> dict[str, Any]:
    if full:
        preflight = run_smoke(base_url=base_url, token_file=token_file)
        if not preflight.get("ok"):
            category = str(preflight.get("connection_status_category") or "connection_check_failed")
            return {
                **preflight,
                "diagnostic_mode": "full",
                "diagnostic_status_category": category,
                "token_onboarding_failure": category in {"token_file_not_ready", "token_rejected"},
            }
        return _run_full_smoke(base_url=base_url, token_file=token_file)

    token_ok, token_category, _ = validate_token_file(token_file)
    if not token_ok:
        return {
            "ok": False,
            "metadata_only": True,
            "connection_status_category": "token_file_not_ready",
            "token_file_category": token_category,
            "token_accepted": "no",
            "tools_visible": list(EXPECTED_TOOLS),
            "tools_exact": True,
            "tools_discovered": len(EXPECTED_TOOLS),
            "token_printed": False,
            "raw_token_printed": False,
            "instruction_category": "create_local_chmod_600_token_file",
        }

    safe_text = (
        "Share-safe current qCoder evidence summary for a harmless connection check. "
        "The user wants one bounded current-session context card. "
        "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER"
    )
    bounded_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="create_context_session_card",
        artifact_text=safe_text,
    )
    bounded_case = _case_summary(payload=bounded_payload, expected_success=True)
    status_category = str(
        bounded_payload.get("adapter_status_category")
        or bounded_payload.get("status_category")
        or "missing"
    )
    rate_limited = status_category == "http_429"
    token_rejected = status_category in {"http_401", "http_403"}
    endpoint_reachable = status_category not in {"network_error", "missing"}
    unsafe_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="get_guided_evidence_context",
        artifact_text="OPENQASM 2.0; qreg q[1];",
    )
    unsafe_case = _case_summary(payload=unsafe_payload, expected_success=False)
    ready = bounded_case["expected_outcome_met"] and unsafe_case["expected_outcome_met"]
    return {
        "ok": bool(ready),
        "metadata_only": True,
        "connection_status_category": (
            "ready"
            if ready
            else "rate_limit_pause_required"
            if rate_limited
            else "token_rejected"
            if token_rejected
            else "connection_check_failed"
        ),
        "token_file_category": "present_safe",
        "token_accepted": "yes"
        if ready
        else "not_rejected"
        if rate_limited
        else "no"
        if token_rejected
        else "unknown",
        "endpoint_reachable": endpoint_reachable,
        "tools_visible": list(EXPECTED_TOOLS),
        "tools_exact": True,
        "tools_discovered": len(EXPECTED_TOOLS),
        "bounded_call_passed": bounded_case["expected_outcome_met"],
        "unsafe_input_rejected": unsafe_case["expected_outcome_met"],
        "retry_after_category": str(bounded_payload.get("retry_after_category") or "absent"),
        "token_printed": False,
        "raw_payload_echo": "no"
        if bounded_case["raw_payload_echo_absent"] and unsafe_case["raw_payload_echo_absent"]
        else "yes",
        "retention_category": "process_and_discard_or_rejected",
        "retained_artifacts_empty": "yes"
        if bounded_case["retained_artifacts_empty_or_absent"]
        and unsafe_case["retained_artifacts_empty_or_absent"]
        else "no",
        "payment_auth_billing_mutation": "no",
        "cases": {
            "context_session_card_allowed": bounded_case,
            "unsafe_input_rejected": unsafe_case,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qcoder context-bridge",
        description="qCoder Context Bridge adapter tools for eligible Explorer users.",
    )
    sub = parser.add_subparsers(dest="context_bridge_command")
    mcp = sub.add_parser("mcp", help="Run or smoke-test the local Context Bridge MCP adapter.")
    mcp_sub = mcp.add_subparsers(dest="mcp_command")

    serve = mcp_sub.add_parser("serve", help="Run the local stdio MCP adapter.")
    serve.add_argument(
        "--token-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_TOKEN_FILE", str(default_token_file())),
        help="Path to a local Context Bridge token file. The token value is never printed.",
    )
    serve.add_argument(
        "--base-url",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_BASE_URL", DEFAULT_BASE_URL),
        help="Context Bridge service base URL.",
    )
    serve.set_defaults(context_bridge_command="mcp", mcp_command="serve")

    smoke = mcp_sub.add_parser("smoke", help="Check the Context Bridge connection safely.")
    smoke.add_argument(
        "--token-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_TOKEN_FILE", str(default_token_file())),
        help="Path to a local Context Bridge token file. The token value is never printed.",
    )
    smoke.add_argument(
        "--base-url",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_BASE_URL", DEFAULT_BASE_URL),
        help="Context Bridge service base URL.",
    )
    smoke.add_argument("--json", action="store_true", help="Emit sanitized JSON result.")
    smoke.add_argument(
        "--full",
        action="store_true",
        help="Run the exhaustive support/release diagnostic without automatic rate-limit retries.",
    )
    smoke.set_defaults(context_bridge_command="mcp", mcp_command="smoke")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.context_bridge_command is None or getattr(args, "mcp_command", None) is None:
        parser.print_help()
        return 0
    if args.mcp_command == "serve":
        return serve_mcp_stdio(base_url=args.base_url, token_file=args.token_file)
    if args.mcp_command == "smoke":
        result = run_smoke(base_url=args.base_url, token_file=args.token_file, full=args.full)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.full:
            print(
                f"Context Bridge full diagnostic: {result.get('diagnostic_status_category', 'check_required')}"
            )
            print(
                f"Token onboarding failure: {'yes' if result.get('token_onboarding_failure') else 'no'}"
            )
            print(f"Tools discovered: {len(result.get('tools_visible', []))}")
            if result.get("diagnostic_status_category") == "rate_limit_pause_required":
                print("Rate limit: pause before continuing the remaining diagnostic checks")
        else:
            status = (
                "ready"
                if result.get("ok")
                else result.get("connection_status_category", "check required")
            )
            print(f"Context Bridge connection: {status}")
            print(f"Token accepted: {result.get('token_accepted', 'unknown')}")
            print(f"Tools discovered: {result.get('tools_discovered', 0)}")
        if result.get("diagnostic_status_category") == "rate_limit_pause_required":
            return 2
        return 0 if result.get("ok") else 1
    parser.print_help()
    return 0
