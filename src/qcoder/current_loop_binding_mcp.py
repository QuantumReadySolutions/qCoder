"""Project-local typed MCP transport for Current Step transactions.

This adapter is deliberately separate from the twelve-tool public Context
Bridge surface.  It exposes two binding-owned internal operations so a connected
assistant can begin and complete one exact Current Step without reconstructing
a local command, stdin pipeline, receipt, digest, or stage ceiling.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Literal, Mapping

from qcoder import __version__
from qcoder.context_bridge_connection import record_server_exchange
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_artifact_targets import (
    ArtifactTargetError,
    MAX_TARGET_PATH_BYTES,
    current_registered_role_target,
    normalize_completion_artifact_path,
    normalize_intended_artifact_targets,
    normalize_selected_artifact_paths,
    target_contract_snapshot,
)
from qcoder.current_loop_request_semantics import classify_current_request
from qcoder.current_loop_pending_completion import (
    PendingCompletionError,
    validate_pending_completion_checkpoint,
)
from qcoder.current_loop_result_controls import ResultControlError
from qcoder.current_loop_operator_timing import (
    clear_stdio_operator_timing,
    record_stdio_operator_timing,
)
from qcoder.current_step_contract import (
    derive_current_step_contract,
    quiet_customer_visibility_contract,
)
from qcoder.review_before_generation import (
    CUSTOMER_ACTIONS as REVIEW_BEFORE_GENERATION_ACTIONS,
    ReviewBeforeGenerationError,
    contract_snapshot as review_before_generation_contract_snapshot,
    proposal_input_schema as review_before_generation_proposal_input_schema,
    validate_review_transaction_kind,
)

BINDING_MCP_SCHEMA_ID = "qcoder.current_loop.binding_mcp.v14"
BINDING_MCP_SCHEMA_VERSION = 14
BINDING_MCP_SERVER_NAME = "qcoder-current-loop"
BEGIN_CURRENT_LOOP_TOOL_NAME = "begin_current_loop"
COMPLETE_CURRENT_STEP_TOOL_NAME = "complete_current_step"
MAX_REQUEST_BYTES = 65_536
MAX_PATH_BYTES = 16_384
MAX_REVIEW_SOURCE_TARGET_CANDIDATES = 32
_LAST_BINDING_TIMING: ContextVar[dict[str, Any] | None] = ContextVar(
    "qcoder_last_binding_timing", default=None
)
_SOURCE_TARGET_PATTERN = re.compile(
    r"(?<![\w./-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|pyw|qasm)(?![\w/-])",
    re.IGNORECASE,
)
_TARGET_AUTHORITY_QUOTED_SPAN_PATTERN = re.compile(
    r'"[^"\r\n]*"|\'[^\'\r\n]*\'|“[^”\r\n]*”|‘[^’\r\n]*’|`+[^`\r\n]*`+'
)
_TARGET_AUTHORITY_DIRECTIVE_BOUNDARY_PATTERN = re.compile(
    r"\b(?:for\s+example|for\s+illustration|for\s+comparison)\s*,|"
    r"\b(?:actually|no)\b\s*,?|\brather\s+than\b|\b(?:but|then|however|or)\b|"
    r"(?:—|–)(?=\s*(?:actually|no)\b)|[,;?!:\n]|\.(?=\s|$)",
    re.IGNORECASE,
)
_TARGET_AUTHORITY_ILLUSTRATIVE_PATTERN = re.compile(
    r"\b(?:example|illustration|placeholder|sample\s+name)\b|\bonly\s+for\s+comparison\b",
    re.IGNORECASE,
)
_TARGET_AUTHORITY_COMPARATIVE_PATTERN = re.compile(
    r"\b(?:compare|comparison|versus)\b|\bpossible\s+(?:alternative|filename|name)\b|"
    r"\balternative\s+(?:filename|name)\b",
    re.IGNORECASE,
)
_TARGET_AUTHORITY_TENTATIVE_PATTERN = re.compile(
    r"\b(?:if|maybe|might|could|would|hypothetical|tentative|possibly)\b",
    re.IGNORECASE,
)
_TARGET_AUTHORITY_NEGATION_PATTERN = re.compile(
    r"\b(?:prefer\s+not\s+to|do\s+not|don't|dont|never|must\s+not|should\s+not|"
    r"avoid(?:\s+ever)?|refrain\s+from|without)\b",
    re.IGNORECASE,
)
_TARGET_AUTHORITY_INLINE_DIRECTIVE_PATTERN = re.compile(
    r"\b(?:show|return|provide|produce|generate|write|output)\b[^.;!?]{0,80}"
    r"\b(?:source|code|program|it)\b[^.;!?]{0,48}\binline\b|"
    r"\b(?:show|return|provide|produce|generate|write|output)\b[^.;!?]{0,80}\binline\b|"
    r"\binline\b[^.;!?]{0,64}\b(?:source|code|program|delivery)\b",
    re.IGNORECASE,
)

TargetAuthorityState = Literal["affirmative", "non_authoritative", "unresolved"]


@dataclass(frozen=True)
class _TargetDirectiveUnit:
    index: int
    start: int
    end: int
    text: str
    leading_boundary: str
    trailing_boundary: str


@dataclass(frozen=True)
class _TargetDirectiveOccurrence:
    target: str
    start: int
    end: int
    unit_index: int
    state: TargetAuthorityState
    reason: str


@dataclass(frozen=True)
class _OutputDirective:
    unit_index: int
    mode: Literal["file", "inline"]
    state: TargetAuthorityState
    target_occurrence_index: int | None
    reason: str


@dataclass(frozen=True)
class _TargetAuthorityResolution:
    state: Literal["affirmative", "target_free", "ambiguous"]
    affirmative_targets: tuple[str, ...]
    occurrences: tuple[_TargetDirectiveOccurrence, ...]
    reason: str


def _target_occurrence_pattern(target: str) -> re.Pattern[str]:
    normalized_target = target.replace("\\", "/").casefold()
    return re.compile(
        rf"(?<![\w./-]){re.escape(normalized_target)}(?![\w/-])",
        re.IGNORECASE,
    )


def _request_explicitly_selects_target(request_text: str, target: str) -> bool:
    """Preserve exact lexical selection checks for non-review target branches."""

    normalized_request = request_text.replace("\\", "/")
    return _target_occurrence_pattern(target).search(normalized_request) is not None


def _target_authority_request_view(request_text: str) -> str:
    """Mask quotation and Markdown-code spans without changing source offsets."""

    normalized = request_text.replace("\\", "/")
    return _TARGET_AUTHORITY_QUOTED_SPAN_PATTERN.sub(
        lambda match: " " * len(match.group(0)), normalized
    )


def _target_authority_units(request_text: str) -> tuple[_TargetDirectiveUnit, ...]:
    """Split one bounded request into ordered local directive units."""

    request = request_text.replace("\\", "/")
    boundary_view = _target_authority_request_view(request_text)
    units: list[_TargetDirectiveUnit] = []
    cursor = 0
    pending_boundaries: list[str] = []
    for match in _TARGET_AUTHORITY_DIRECTIVE_BOUNDARY_PATTERN.finditer(boundary_view):
        raw_segment = request[cursor : match.start()]
        leading_trim = len(raw_segment) - len(raw_segment.lstrip())
        trailing_trim = len(raw_segment.rstrip())
        if trailing_trim > leading_trim:
            start = cursor + leading_trim
            end = cursor + trailing_trim
            units.append(
                _TargetDirectiveUnit(
                    index=len(units),
                    start=start,
                    end=end,
                    text=request[start:end],
                    leading_boundary=" ".join(pending_boundaries),
                    trailing_boundary=match.group(0).strip().casefold(),
                )
            )
            pending_boundaries = []
        pending_boundaries.append(" ".join(match.group(0).casefold().split()))
        cursor = match.end()
    raw_segment = request[cursor:]
    leading_trim = len(raw_segment) - len(raw_segment.lstrip())
    trailing_trim = len(raw_segment.rstrip())
    if trailing_trim > leading_trim:
        start = cursor + leading_trim
        end = cursor + trailing_trim
        units.append(
            _TargetDirectiveUnit(
                index=len(units),
                start=start,
                end=end,
                text=request[start:end],
                leading_boundary=" ".join(pending_boundaries),
                trailing_boundary="",
            )
        )
    return tuple(units)


def _target_authority_positive_pattern(target: str) -> re.Pattern[str]:
    exact = re.escape(target)
    return re.compile(
        rf"(?:"
        rf"\b(?:create|creating)\b[^,;!?]{{0,48}}{exact}|"
        rf"\b(?:write|writing|save|saving)\b[^,;!?]{{0,64}}(?:\b(?:as|to|in)\b\s*)?{exact}|"
        rf"\b(?:generate|generating)\b[^,;!?]{{0,80}}\b(?:in|to|as)\b\s*{exact}|"
        rf"\b(?:put|putting|output|outputting|store|storing)\b[^,;!?]{{0,80}}"
        rf"\b(?:in|to|as)\b\s*{exact}|"
        rf"\b(?:modify|modifying|edit|editing|update|updating|replace|replacing)\b"
        rf"[^,;!?]{{0,48}}{exact}"
        rf")\s*$",
        re.IGNORECASE,
    )


def _span_is_quoted_or_code(request: str, start: int, end: int) -> bool:
    return any(
        match.start() <= start and end <= match.end()
        for match in _TARGET_AUTHORITY_QUOTED_SPAN_PATTERN.finditer(request)
    )


def _unit_for_occurrence(
    units: tuple[_TargetDirectiveUnit, ...], start: int, end: int
) -> _TargetDirectiveUnit:
    for unit in units:
        if unit.start <= start and end <= unit.end:
            return unit
    return _TargetDirectiveUnit(
        index=len(units),
        start=start,
        end=end,
        text="",
        leading_boundary="",
        trailing_boundary="",
    )


def _classify_target_occurrence(
    *,
    request: str,
    occurrence: re.Match[str],
    unit: _TargetDirectiveUnit,
) -> _TargetDirectiveOccurrence:
    target = occurrence.group(0).replace("\\", "/")
    if _span_is_quoted_or_code(request, occurrence.start(), occurrence.end()):
        return _TargetDirectiveOccurrence(
            target,
            occurrence.start(),
            occurrence.end(),
            unit.index,
            "non_authoritative",
            "quoted_or_code",
        )
    local = unit.text
    local_folded = local.casefold()
    leading = unit.leading_boundary.casefold()
    relative_end = occurrence.end() - unit.start
    directive_through_target = local[:relative_end].rstrip()
    if "rather than" in leading:
        state: TargetAuthorityState = "non_authoritative"
        reason = "comparative_rejected_alternative"
    elif any(marker in leading for marker in ("for example", "for illustration", "for comparison")):
        state = "non_authoritative"
        reason = "illustrative_boundary"
    elif "?" in unit.trailing_boundary:
        state = "non_authoritative"
        reason = "interrogative"
    elif _TARGET_AUTHORITY_ILLUSTRATIVE_PATTERN.search(local_folded):
        state = "non_authoritative"
        reason = "illustrative"
    elif _TARGET_AUTHORITY_COMPARATIVE_PATTERN.search(local_folded):
        state = "non_authoritative"
        reason = "comparative_or_alternative"
    elif _TARGET_AUTHORITY_NEGATION_PATTERN.search(directive_through_target):
        state = "non_authoritative"
        reason = "negated_or_prohibited"
    elif _TARGET_AUTHORITY_TENTATIVE_PATTERN.search(directive_through_target):
        state = "non_authoritative"
        reason = "conditional_or_tentative"
    elif _target_authority_positive_pattern(target).search(directive_through_target):
        state = "affirmative"
        reason = "bounded_affirmative_source_directive"
    else:
        state = "unresolved"
        reason = "target_bearing_directive_not_proven"
    return _TargetDirectiveOccurrence(
        target=target,
        start=occurrence.start(),
        end=occurrence.end(),
        unit_index=unit.index,
        state=state,
        reason=reason,
    )


def _classify_inline_directive(unit: _TargetDirectiveUnit) -> _OutputDirective | None:
    local = _TARGET_AUTHORITY_QUOTED_SPAN_PATTERN.sub(" ", unit.text)
    if "inline" not in local.casefold():
        return None
    if "rather than" in unit.leading_boundary.casefold():
        return _OutputDirective(
            unit.index, "inline", "non_authoritative", None, "comparative_rejected_alternative"
        )
    if "?" in unit.trailing_boundary:
        return _OutputDirective(unit.index, "inline", "non_authoritative", None, "interrogative")
    if _TARGET_AUTHORITY_NEGATION_PATTERN.search(local):
        return _OutputDirective(
            unit.index, "inline", "non_authoritative", None, "negated_or_prohibited"
        )
    if _TARGET_AUTHORITY_TENTATIVE_PATTERN.search(local):
        return _OutputDirective(
            unit.index, "inline", "non_authoritative", None, "conditional_or_tentative"
        )
    if _TARGET_AUTHORITY_INLINE_DIRECTIVE_PATTERN.search(local):
        return _OutputDirective(
            unit.index, "inline", "affirmative", None, "bounded_affirmative_inline_directive"
        )
    return _OutputDirective(unit.index, "inline", "unresolved", None, "inline_directive_not_proven")


def _explicit_replacement(unit: _TargetDirectiveUnit) -> bool:
    combined = f"{unit.leading_boundary} {unit.text}".casefold()
    return "actually" in combined and "instead" in combined


def _resolve_request_source_target_authority(request_text: str) -> _TargetAuthorityResolution:
    """Resolve ordered target and output directives without path processing."""

    request = request_text.replace("\\", "/")
    units = _target_authority_units(request_text)
    raw_occurrences = list(_SOURCE_TARGET_PATTERN.finditer(request))
    if len(raw_occurrences) > MAX_REVIEW_SOURCE_TARGET_CANDIDATES:
        return _TargetAuthorityResolution("ambiguous", (), (), "candidate_bound_exceeded")
    occurrences = [
        _classify_target_occurrence(
            request=request,
            occurrence=occurrence,
            unit=_unit_for_occurrence(units, occurrence.start(), occurrence.end()),
        )
        for occurrence in raw_occurrences
    ]
    for index, occurrence in enumerate(occurrences):
        if occurrence.state != "unresolved" or index == 0:
            continue
        unit = units[occurrence.unit_index]
        previous = occurrences[index - 1]
        if (
            "or" in unit.leading_boundary.split()
            and previous.state == "non_authoritative"
            and previous.reason
            in {
                "illustrative",
                "illustrative_boundary",
                "comparative_or_alternative",
            }
        ):
            occurrences[index] = replace(
                occurrence,
                state="non_authoritative",
                reason="coordinated_nonauthoritative_alternative",
            )
    output_directives: list[_OutputDirective] = [
        _OutputDirective(
            occurrence.unit_index,
            "file",
            occurrence.state,
            index,
            occurrence.reason,
        )
        for index, occurrence in enumerate(occurrences)
    ]
    output_directives.extend(
        directive for unit in units if (directive := _classify_inline_directive(unit)) is not None
    )
    output_directives.sort(key=lambda item: item.unit_index)

    for current_index, current in enumerate(output_directives):
        if current.state != "affirmative" or not _explicit_replacement(units[current.unit_index]):
            continue
        prior = next(
            (
                item
                for item in reversed(output_directives[:current_index])
                if item.state == "affirmative" and item.mode != current.mode
            ),
            None,
        )
        if prior is None:
            continue
        prior_position = output_directives.index(prior)
        output_directives[prior_position] = replace(
            prior, state="non_authoritative", reason="superseded_by_explicit_correction"
        )
        if prior.target_occurrence_index is not None:
            occurrence = occurrences[prior.target_occurrence_index]
            occurrences[prior.target_occurrence_index] = replace(
                occurrence,
                state="non_authoritative",
                reason="superseded_by_explicit_correction",
            )

    if any(item.state == "unresolved" for item in output_directives):
        return _TargetAuthorityResolution(
            "ambiguous", (), tuple(occurrences), "unresolved_target_or_output_directive"
        )
    affirmative_targets = tuple(
        dict.fromkeys(
            occurrence.target for occurrence in occurrences if occurrence.state == "affirmative"
        )
    )
    unique_targets = {target.casefold() for target in affirmative_targets}
    if len(unique_targets) > 1:
        return _TargetAuthorityResolution(
            "ambiguous", (), tuple(occurrences), "multiple_affirmative_targets"
        )
    active_modes = {item.mode for item in output_directives if item.state == "affirmative"}
    if active_modes == {"file", "inline"}:
        return _TargetAuthorityResolution(
            "ambiguous", (), tuple(occurrences), "inline_file_output_conflict"
        )
    if affirmative_targets:
        return _TargetAuthorityResolution(
            "affirmative",
            affirmative_targets[:1],
            tuple(occurrences),
            "one_unique_affirmative_target",
        )
    return _TargetAuthorityResolution(
        "target_free", (), tuple(occurrences), "all_target_occurrences_non_authoritative"
    )


def _request_source_target_directive_diagnostics(
    request_text: str,
) -> tuple[dict[str, object], ...]:
    """Return bounded ephemeral tri-state facts for direct safety tests only."""

    units = _target_authority_units(request_text)
    unit_spans = {unit.index: [unit.start, unit.end] for unit in units}
    resolution = _resolve_request_source_target_authority(request_text)
    return tuple(
        {
            "target": occurrence.target,
            "target_span": [occurrence.start, occurrence.end],
            "directive_unit": occurrence.unit_index,
            "directive_span": unit_spans.get(
                occurrence.unit_index, [occurrence.start, occurrence.end]
            ),
            "state": occurrence.state,
            "reason": occurrence.reason,
        }
        for occurrence in resolution.occurrences
    )


def _request_source_target_authority(request_text: str, target: str) -> str:
    """Return one target's tri-state result under the complete request resolution."""

    resolution = _resolve_request_source_target_authority(request_text)
    matches = [
        occurrence
        for occurrence in resolution.occurrences
        if occurrence.target.casefold() == target.replace("\\", "/").casefold()
    ]
    if not matches:
        return "absent"
    if resolution.state == "ambiguous" or any(item.state == "unresolved" for item in matches):
        return "contradictory_or_ambiguous"
    if any(item.state == "affirmative" for item in matches):
        return "affirmative"
    return "non_authoritative"


def _request_source_target_candidates(request_text: str) -> tuple[str, ...]:
    request = request_text.replace("\\", "/")
    return tuple(
        dict.fromkeys(match.group(0) for match in _SOURCE_TARGET_PATTERN.finditer(request))
    )


def _affirmatively_authorized_request_targets(request_text: str) -> tuple[str, ...]:
    resolution = _resolve_request_source_target_authority(request_text)
    if resolution.state == "ambiguous":
        raise ReviewBeforeGenerationError(
            "review_source_target_authority_ambiguous",
            clarification=("Should the reviewed source be inline, or written to one exact target?"),
        )
    return resolution.affirmative_targets


def _unconfirmed_generation_review_has_no_target_authority(
    request_text: str, proposal: object
) -> bool:
    """Give the immediate review interaction precedence over future production."""

    return (
        isinstance(proposal, Mapping)
        and proposal.get("transaction_kind") == "review_before_source_generation"
        and not _affirmatively_authorized_request_targets(request_text)
    )


def _quiet_review_success_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project only review content, its opaque continuation, and authority ceilings."""

    semantics = payload.get("current_request_semantics")
    axes = semantics.get("semantic_axes") if isinstance(semantics, Mapping) else None
    generation_authority = axes.get("generation_authority") if isinstance(axes, Mapping) else None
    execution_authority = axes.get("execution_authority") if isinstance(axes, Mapping) else None
    return {
        "ok": True,
        "review_before_generation": payload["review_before_generation"],
        "prior_result_token": payload["prior_result_token"],
        "generation_authority": generation_authority or "held_for_exact_review_confirmation",
        "execution_authority": execution_authority or "not_requested",
        "source_or_qasm_created": False,
        "file_mutation_performed": False,
        "execution_performed": False,
        "protected_service_called": False,
    }


def binding_tool_descriptors() -> list[dict[str, Any]]:
    """Return the two private operations in the client-neutral transaction."""

    return [
        {
            "name": BEGIN_CURRENT_LOOP_TOOL_NAME,
            "description": (
                "INTERNAL NORMAL-PATH OPERATION: call as the first response action without a "
                "customer-facing preface. Begin qCoder's bounded Current Loop, or interpret the "
                "exact next instruction against an already complete-resumable loop. "
                "Supply request_text exactly once as the complete unmodified customer message. "
                "For review before source generation or modification, make the initial call with "
                "that exact request and one concrete connected_assistant_proposal. Do not compute "
                "a hash, invent group identifiers or labels, include source or QASM, or provide "
                "qCoder authority text. Customer constraints must be exact request excerpts. "
                "qCoder supplies structure, attribution, authority, revision, and actions. Later "
                "confirm with only review_action and the opaque prior_result_token; do not replay "
                "the proposal. Execution authority remains separate. For review before generation, "
                "include exactly one proposal-v3 source_delivery recommendation: inline, or "
                "workspace_file with one safe workspace-relative Python target whose exact text "
                "occurs in request_text or has existing native selected-source provenance. This "
                "request-presence check prevents invention; qCoder does not interpret surrounding "
                "free-form delivery language. Missing, unsafe, or ungrounded file recommendations "
                "converge silently to inline. A grounded file recommendation is displayed but inert. "
                "Customer confirmation of that exact displayed revision is the first authority for "
                "source delivery and workspace write. Assistant envelope target fields cannot grant it. "
                "For a direct artifact-producing request, supply one exact workspace-relative "
                "intended_artifact_paths entry for every requested role on a fresh loop. For an "
                "active-loop replacement, omit the path: qCoder binds the current registered "
                "role-head target automatically. A different target is accepted only when the "
                "exact customer message names that workspace-relative path. Never read, list, "
                "glob, or search the workspace to choose a target. qCoder binds it before any "
                "native action. "
                "For an exact selected result-evidence control request, copy the customer-named "
                "workspace-relative paths in order into selected_artifact_paths; never read or "
                "search for them. qCoder returns the terminal bounded control disposition with "
                "no native action. For an exact pre-existing source satisfaction request, copy "
                "its one customer-named path into selected_artifact_paths; qCoder binds it as the "
                "source target without a write. "
                "This operation preserves the Request Baseline, classifies authority fail-closed, "
                "and grants no native write, execution, review, or governing authority. On an "
                "active loop, call it directly without narrating or reconstructing continuation "
                "procedure; the returned replacement Current Step Contract is the only action "
                "source."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_REQUEST_BYTES,
                        "description": "Exact complete current customer message, unchanged.",
                    },
                    "intended_artifact_paths": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "maxLength": MAX_TARGET_PATH_BYTES},
                            "circuit_qasm": {
                                "type": "string",
                                "maxLength": MAX_TARGET_PATH_BYTES,
                            },
                            "results": {"type": "string", "maxLength": MAX_TARGET_PATH_BYTES},
                        },
                        "additionalProperties": False,
                        "description": (
                            "Fresh-loop exact workspace-relative targets for direct generation. "
                            "These envelope fields do not establish authority for review before "
                            "generation and are ignored before path processing there; use the inert "
                            "proposal-v3 source_delivery recommendation instead. Omit for an active-loop "
                            "replacement so qCoder reuses the registered current role-head target."
                        ),
                    },
                    "selected_artifact_paths": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": MAX_TARGET_PATH_BYTES},
                        "description": (
                            "Copy only exact workspace-relative paths explicitly named by the "
                            "customer. Use two for bounded result-evidence controls or one for "
                            "pre-existing exact source satisfaction. Never discover paths."
                        ),
                    },
                    "connected_assistant_proposal": {
                        **review_before_generation_proposal_input_schema(),
                        "description": (
                            "Optional separately attributed, exact-request-bound semantic and "
                            "implementation proposal for review before generation. The connected "
                            "assistant supplies all substantive recommendations, including exactly "
                            "one inert source-delivery recommendation; qCoder validates and projects "
                            "them deterministically."
                        ),
                    },
                    "review_action": {
                        "type": "string",
                        "enum": list(REVIEW_BEFORE_GENERATION_ACTIONS),
                        "description": (
                            "Exact action for the active review. Supply only with prior_result_token; "
                            "do not replay the request digest, proposal, revision, or hidden fields."
                        ),
                    },
                    "prior_result_token": {
                        "type": "string",
                        "pattern": "^review-result-[0-9a-f]{64}$",
                        "description": (
                            "Opaque token returned by the prior review result. It is internal "
                            "transport, not customer-visible content."
                        ),
                    },
                },
                "oneOf": [
                    {
                        "title": "Ordinary existing begin call",
                        "required": ["request_text"],
                        "not": {
                            "anyOf": [
                                {"required": ["connected_assistant_proposal"]},
                                {"required": ["review_action"]},
                                {"required": ["prior_result_token"]},
                            ]
                        },
                    },
                    {
                        "title": "Initial or revised review-before-generation call",
                        "description": (
                            "Use exact request_text and a substantive proposal v3. Recommend inline, "
                            "or workspace_file with one safe target whose exact text occurs in the "
                            "request (or has native selected-source provenance). qCoder treats that "
                            "presence only as an anti-invention guard and does not interpret surrounding "
                            "delivery prose. Safe envelope targets are ignored. A grounded file "
                            "recommendation is displayed without write authority; exact displayed "
                            "customer confirmation is the first delivery/write authority."
                        ),
                        "required": ["request_text", "connected_assistant_proposal"],
                        "not": {"required": ["review_action"]},
                    },
                    {
                        "title": "Stored-review action call",
                        "type": "object",
                        "properties": {
                            "review_action": {
                                "type": "string",
                                "enum": list(REVIEW_BEFORE_GENERATION_ACTIONS),
                            },
                            "prior_result_token": {
                                "type": "string",
                                "pattern": "^review-result-[0-9a-f]{64}$",
                            },
                        },
                        "required": ["review_action", "prior_result_token"],
                        "additionalProperties": False,
                    },
                ],
                "additionalProperties": False,
            },
            "x-qcoder-binding-owned-internal-operation": True,
            "x-qcoder-public-context-bridge-tool": False,
            "x-qcoder-direct-generation-happy-path": {
                "request_text": "<exact current customer message>",
                "intended_artifact_paths": {"source": "<exact workspace-relative filename>"},
            },
            "x-qcoder-review-before-generation-happy-path": {
                "request_text": "<exact review-before-generation customer message>",
                "connected_assistant_proposal": (
                    "<substantive proposal v3 with source_delivery mode inline or workspace_file>"
                ),
            },
            "x-qcoder-selected-file-workflow-happy-path": {
                "request_text": "<exact selected-file customer message>",
                "selected_artifact_paths": ["<exact customer-named relative path>"],
            },
            "x-qcoder-artifact-target-contract": target_contract_snapshot(),
            "x-qcoder-selected-result-control-happy-path": {
                "request_text": "<exact complete customer message>",
                "selected_artifact_paths": [
                    "<first exact customer-named relative path>",
                    "<second exact customer-named relative path>",
                ],
                "terminal_read_only_projection": True,
                "native_action_required": False,
            },
            "x-qcoder-preexisting-source-happy-path": {
                "request_text": "<exact complete customer message>",
                "selected_artifact_paths": ["<exact customer-named relative source path>"],
                "native_write_required": False,
                "completion_arguments": {},
                "artifact_disposition_derived_by_qcoder": "pre_existing_exact_artifact",
            },
            "x-qcoder-review-before-generation": {
                "contract": review_before_generation_contract_snapshot(),
                "first_call_arguments": ["request_text", "connected_assistant_proposal"],
                "confirmation_call_arguments": ["review_action", "prior_result_token"],
                "proposal_replay_on_confirmation": False,
                "caller_supplies_request_digest": False,
                "caller_supplies_group_ids_or_labels": False,
                "qcoder_supplies_authority_and_attribution": True,
                "one_operation_before_useful_review": True,
                "protected_service_called": False,
                "source_before_confirmation": False,
                "qcoder_authors_recommendations": False,
                "immediate_review_precedes_future_artifact_target": True,
                "invented_target_required_before_confirmation": False,
                "irrelevant_target_disposition": "discarded_before_path_processing",
                "transaction_kind_bound_before_target_discard": True,
                "proposal_schema": "qcoder.connected_assistant.review_before_generation_proposal.v3",
                "assistant_source_delivery_modes": ["inline", "workspace_file"],
                "request_path_presence_is_anti_invention_only": True,
                "free_form_delivery_language_interpreted_by_qcoder": False,
                "grounded_file_recommendation_authoritative_before_confirmation": False,
                "displayed_revision_confirmation_is_first_delivery_authority": True,
                "assistant_envelope_target_fields_establish_authority": False,
                "invalid_or_ungrounded_file_recommendation_disposition": "silent_inline",
                "post_confirmation_write_target_displayed_before_confirmation": True,
                "target_free_review_remains_target_free_after_confirmation": True,
            },
            "x-qcoder-active-loop-continuation": {
                "request_text": "<exact next customer message>",
                "reuse_active_loop": True,
                "rebootstrap": False,
                "request_baseline_recreated": False,
                "pre_contract_procedure_reasoning": False,
                "customer_visible_transition_narration": False,
                "action_source": "replacement_current_step_contract",
                "replacement_target_source": "registered_current_role_head",
                "replacement_target_model_selection_required": False,
                "different_target_requires_exact_customer_path_selection": True,
            },
            "x-qcoder-customer-visibility": quiet_customer_visibility_contract(),
            "x-qcoder-normal-success-presentation": {
                "customer_message_before_tool_call": "none",
                "customer_message_after_tool_call": "none_or_task_level_progress_only",
                "internal_mechanics_explanation": False,
            },
        },
        {
            "name": COMPLETE_CURRENT_STEP_TOOL_NAME,
            "description": (
                "BOUNDED COMPLETION AND RECOVERY OPERATION: call this operation after the native "
                "action only when current_step_contract.completion.mode is "
                "binding_owned_typed_completion, or when qCoder reports pending recovery. "
                "When the contract selects synchronous_native_edit_event terminal closure, do not "
                "make a duplicate completion call. For an applicable pending completion, call "
                "this operation directly with an empty object, including "
                "on a later turn or same-host MCP restart. Do not call begin_current_loop, inspect "
                "state/help, refresh the result, or rerun execution. Call without a customer-facing "
                "transition message. "
                "a customer-facing transition message. Complete the exact active qCoder Current "
                "Step after the native client has "
                "performed its action under its own controls. qCoder resolves its durable opaque "
                "action handle and exact bound workspace-relative target. Optional explicit "
                "handle/path compatibility fields must match that same checkpoint exactly. "
                "qCoder reads and validates the actual bytes; do not supply permission state, "
                "digests, loop revisions, receipt identities, roles, or stage ceilings."
                " For a result step, artifact_path transports the exact strict-result-manifest "
                "file required by the returned Current Step Contract; bare counts are not "
                "current result evidence. Use only an already prepared and prevalidated "
                "native-client runtime. Dependency installation, environment mutation, analytic "
                "substitution for sampled shots, and additional execution attempts are outside "
                "the step; surface a blocker instead. On result success, use the returned "
                "canonical current_run_summary for the requested final outcome."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "current_action_handle": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                        "description": "Opaque current-action handle from Current Step Contract.",
                    },
                    "artifact_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                        "description": (
                            "Copy the exact workspace-relative artifact_path value from the "
                            "Current Step Contract; absolute paths are not accepted."
                        ),
                        "x-qcoder-path-form": "workspace_relative_bound_target",
                    },
                    "artifact_disposition": {
                        "type": "string",
                        "enum": [
                            "assistant_created",
                            "assistant_modified",
                            "pre_existing_exact_artifact",
                            "explicitly_user_selected_or_supplied",
                        ],
                        "default": "assistant_created",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            "x-qcoder-binding-owned-internal-operation": True,
            "x-qcoder-public-context-bridge-tool": False,
            "x-qcoder-normal-happy-path": {},
            "x-qcoder-pending-completion": {
                "sole_next_qcoder_operation": True,
                "direct_later_turn_completion": True,
                "begin_current_loop_required": False,
                "external_execution_rerun_permitted": False,
            },
            "x-qcoder-native-permission-owner": "native_client",
            "x-qcoder-hooks-required-for-correctness": False,
            "x-qcoder-strict-result-manifest-transport": "exact_artifact_path",
            "x-qcoder-customer-visibility": quiet_customer_visibility_contract(),
            "x-qcoder-normal-success-presentation": {
                "customer_message_before_tool_call": "none",
                "customer_message_after_tool_call": "one_concise_task_outcome",
                "internal_mechanics_explanation": False,
            },
        },
    ]


def _result(message_id: object, value: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": dict(value)}


def _error(message_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _tool_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    return {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
        "structuredContent": value,
        "isError": value.get("ok") is not True,
    }


def _handle_binding_jsonrpc_message(
    message: Mapping[str, Any], *, workspace_root: str | Path
) -> dict[str, Any] | None:
    """Handle one MCP request without accepting workspace or authority from the model."""

    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": BINDING_MCP_SERVER_NAME, "version": __version__},
                "instructions": (
                    "NORMAL SUCCESS EVENT ORDER: the first response event is begin_current_loop, "
                    "not customer-facing text. Do not send a customer-visible message before "
                    "begin_current_loop, between the native task and "
                    "complete_current_step, or to explain the transaction. Optional progress is "
                    "task-level only; after successful completion give one concise task outcome. "
                    "Never describe activation or loop/step transitions, contracts or bounded "
                    "authority, typed completion or registration, receipts, revisions, hooks, or "
                    "evidence bookkeeping during normal success. "
                    "Surface qCoder mechanics only for a real blocker, ambiguity, bounded "
                    "recovery, meaningful authority broadening, or requested qCoder help. "
                    "This project-local qCoder binding exposes two typed operations for one "
                    "Current Step transaction. Begin once. Then follow only "
                    "current_step_contract.completion: an exact native-edit event performs "
                    "synchronous deterministic terminal closure when selected; otherwise call "
                    "complete_current_step after the native action. Never duplicate completion. "
                    "Native permission remains client-owned. "
                    "For an active-loop continuation, call begin_current_loop immediately with "
                    "the exact next customer message; silently use its compact replacement "
                    "contract without re-bootstrap, baseline recreation, or procedure narration. "
                    "Do not construct Shell commands, stdin pipelines, receipts, digests, loop "
                    "revisions, roles, or stage ceilings. The returned current_step_contract is "
                    "the only current-stage action source. Hooks may accelerate completion but "
                    "are never required for correctness. For a fresh artifact-producing request, "
                    "supply intended_artifact_paths in the first begin call. For an active-loop "
                    "replacement, omit the path and let qCoder bind the registered current "
                    "role-head target; never rediscover or reselect it. A different target is "
                    "valid only when the exact customer message explicitly names it. Do not "
                    "Read, Glob, Grep, list, scan, or search the workspace to select a target. "
                    "Use only the exact target returned in the Current Step Contract."
                    " For exact selected result-evidence controls, copy the customer-named "
                    "relative paths directly into selected_artifact_paths and use the returned "
                    "terminal control projection. Do not use CLI/help, inspect state or package "
                    "files, read the controls yourself, or search any workspace. This operation "
                    "never executes or changes the current registered result. For an explicitly "
                    "selected pre-existing source, pass its one exact named path in the same "
                    "field; no native write is required and qCoder derives selected provenance."
                    " If a pending completion exists, complete_current_step is the sole next "
                    "qCoder operation: call it directly with an empty object even on a later turn "
                    "or same-host MCP restart. Do not call begin_current_loop, inspect state/help, "
                    "refresh/restage the artifact, or rerun external execution."
                    " For an external execution step, use only an already prepared and "
                    "prevalidated native-client runtime. The step does not authorize dependency "
                    "installation, environment mutation, analytic substitution for sampled "
                    "shots, or an additional execution attempt; return a blocker instead."
                ),
            },
        )
    if method == "tools/list":
        return _result(message_id, {"tools": binding_tool_descriptors()})
    if method != "tools/call":
        return _error(message_id, -32601, "method_not_supported")

    params = message.get("params")
    if not isinstance(params, Mapping) or params.get("name") not in {
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
    }:
        return _error(message_id, -32602, "unknown_binding_operation")
    operation_name = str(params.get("name"))
    arguments = params.get("arguments")
    if operation_name == COMPLETE_CURRENT_STEP_TOOL_NAME:
        allowed = {"current_action_handle", "artifact_path", "artifact_disposition"}
        explicit_identity = isinstance(arguments, Mapping) and (
            "current_action_handle" in arguments or "artifact_path" in arguments
        )
        if (
            not isinstance(arguments, Mapping)
            or set(arguments).difference(allowed)
            or (
                explicit_identity
                and not {"current_action_handle", "artifact_path"}.issubset(arguments)
            )
            or (
                explicit_identity
                and (
                    not isinstance(arguments.get("current_action_handle"), str)
                    or not arguments["current_action_handle"]
                    or len(arguments["current_action_handle"].encode("utf-8")) > 256
                    or not isinstance(arguments.get("artifact_path"), str)
                    or not arguments["artifact_path"]
                    or len(arguments["artifact_path"].encode("utf-8")) > MAX_PATH_BYTES
                )
            )
            or arguments.get("artifact_disposition", "assistant_created")
            not in {
                "assistant_created",
                "assistant_modified",
                "pre_existing_exact_artifact",
                "explicitly_user_selected_or_supplied",
            }
        ):
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.typed_completion_rejection.v1",
                        "ok": False,
                        "category": "typed_completion_shape_invalid",
                        "expected_shape": {
                            "canonical": {},
                            "compatibility": "both exact handle and bound relative path",
                            "artifact_disposition": (
                                "optional created, modified, pre-existing, or explicit-selection enum"
                            ),
                        },
                        "state_mutated": False,
                        "raw_path_echoed": False,
                    }
                ),
            )
        binding_workspace = Path(workspace_root).expanduser().absolute()
        try:
            normalized_completion_path = (
                normalize_completion_artifact_path(
                    arguments["artifact_path"], workspace_root=binding_workspace
                )
                if explicit_identity
                else None
            )
        except ArtifactTargetError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.typed_completion_rejection.v2",
                        "ok": False,
                        "category": str(exc),
                        "expected_path_form": "workspace_relative_bound_target",
                        "copy_from": "current_step_contract.completion.artifact_path",
                        "absolute_path_accepted": False,
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                        "raw_path_echoed": False,
                    }
                ),
            )
        coordinator = CurrentLoopCoordinator(
            workspace_root=binding_workspace,
            runtime_executable=sys.executable,
        )
        completion_disposition = arguments.get("artifact_disposition")
        if completion_disposition is None:
            current = coordinator.store.read()
            current_semantics = current.get("coordinator", {}).get("current_request_semantics")
            completion_disposition = (
                "pre_existing_exact_artifact"
                if isinstance(current_semantics, Mapping)
                and current_semantics.get("preexisting_exact_source_satisfaction_requested") is True
                else "assistant_created"
            )
        payload = coordinator.complete_current_step(
            current_action_handle=(
                str(arguments["current_action_handle"]) if explicit_identity else None
            ),
            artifact_path=(str(normalized_completion_path) if normalized_completion_path else None),
            artifact_disposition=str(completion_disposition),
        )
        return _result(message_id, _tool_result(payload))

    if not isinstance(arguments, Mapping) or set(arguments).difference(
        {
            "request_text",
            "intended_artifact_paths",
            "selected_artifact_paths",
            "connected_assistant_proposal",
            "review_action",
            "prior_result_token",
        }
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v1",
                    "ok": False,
                    "category": "exact_request_text_argument_required",
                    "expected_shape": {
                        "request_text": "nonempty exact customer message",
                        "intended_artifact_paths": (
                            "exact role-to-workspace-relative-path map for artifact requests"
                        ),
                        "selected_artifact_paths": (
                            "bounded exact customer-named workspace-relative path list"
                        ),
                        "connected_assistant_proposal": (
                            "optional exact-request-bound connected-assistant proposal"
                        ),
                    },
                    "state_mutated": False,
                    "raw_request_echoed": False,
                }
            ),
        )
    review_action = arguments.get("review_action")
    prior_result_token = arguments.get("prior_result_token")
    connected_assistant_proposal = arguments.get("connected_assistant_proposal")
    is_review_action = review_action is not None
    if is_review_action and (
        set(arguments) != {"review_action", "prior_result_token"}
        or review_action not in REVIEW_BEFORE_GENERATION_ACTIONS
        or not isinstance(prior_result_token, str)
        or re.fullmatch(r"review-result-[0-9a-f]{64}", prior_result_token) is None
        or connected_assistant_proposal is not None
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.review_before_generation_rejection.v2",
                    "schema_version": 2,
                    "ok": False,
                    "category": "review_action_and_prior_result_token_required",
                    "state_mutated": False,
                    "proposal_replay_required": False,
                }
            ),
        )
    request_text = arguments.get("request_text")
    if not is_review_action and (
        not isinstance(request_text, str)
        or not request_text
        or len(request_text.encode("utf-8")) > MAX_REQUEST_BYTES
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v1",
                    "ok": False,
                    "category": "exact_request_text_invalid",
                    "state_mutated": False,
                    "raw_request_echoed": False,
                }
            ),
        )

    coordinator = CurrentLoopCoordinator(
        workspace_root=Path(workspace_root).expanduser().absolute(),
        runtime_executable=sys.executable,
    )
    state_path = coordinator.workspace_root / ".qcoder" / "current-loop" / "state.json"
    continuation = False
    active_state: Mapping[str, Any] | None = None
    if state_path.is_file() and not state_path.is_symlink():
        current = coordinator.store.read()
        active_state = current
        current_status = current.get("coordinator", {}).get("current_step_status")
        if current_status == "awaiting_external_client_action" and not is_review_action:
            try:
                checkpoint, _receipt = validate_pending_completion_checkpoint(
                    state=current,
                    coordinator=coordinator._coordinator_state(current),
                    current_time=coordinator.clock(),
                )
                contract = derive_current_step_contract(current)
            except (PendingCompletionError, ValueError) as exc:
                return _result(
                    message_id,
                    _tool_result(
                        {
                            "schema_id": "qcoder.current_loop.pending_completion_blocker.v1",
                            "ok": False,
                            "category": str(getattr(exc, "category", exc)),
                            "state_mutated": False,
                            "external_execution_rerun_permitted": False,
                            "recovery": "honest_blocker_no_refresh_or_restage",
                        }
                    ),
                )
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.pending_completion_resume.v1",
                        "schema_version": 1,
                        "ok": True,
                        "operation": "begin_current_loop",
                        "category": "pending_completion_already_active",
                        "state_revision": current["state_revision"],
                        "state_mutated": False,
                        "bootstrap_count": current["coordinator"].get("bootstrap_count"),
                        "request_baseline_count": current["coordinator"].get(
                            "request_baseline_count"
                        ),
                        "current_step_contract": contract,
                        "pending_completion": {
                            "checkpoint_digest": checkpoint.get("checkpoint_digest"),
                            "sole_next_qcoder_operation": "complete_current_step",
                            "canonical_arguments": {},
                            "external_execution_rerun_permitted": False,
                            "state_or_help_archaeology_required": False,
                        },
                    }
                ),
            )
        continuation = current_status == "complete_resumable"
    if is_review_action:
        try:
            payload = coordinator.review_before_generation_transaction(
                exact_request=(str(request_text) if isinstance(request_text, str) else None),
                review_action=str(review_action),
                prior_result_token=str(prior_result_token),
            )
        except ReviewBeforeGenerationError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.review_before_generation_rejection.v2",
                        "schema_version": 2,
                        "ok": False,
                        "category": exc.category,
                        "state_mutated": False,
                        "source_or_qasm_created": False,
                        "file_mutation_performed": False,
                        "execution_performed": False,
                        "protected_service_called": False,
                        "proposal_replay_required": False,
                    }
                ),
            )
        payload.setdefault("details", {}).update(
            {
                "structured_confirmation_transport": "project_local_binding_mcp",
                "prior_result_token_received_once": True,
                "connected_assistant_proposal_replayed": False,
                "request_digest_received": False,
                "protected_service_called": False,
            }
        )
        return _result(message_id, _tool_result(payload))
    if connected_assistant_proposal is not None:
        try:
            transaction_kind = connected_assistant_proposal.get("transaction_kind")
            request_transaction_state = validate_review_transaction_kind(
                str(request_text), transaction_kind
            )
        except ReviewBeforeGenerationError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.review_before_generation_rejection.v2",
                        "schema_version": 2,
                        "ok": False,
                        "category": exc.category,
                        **(
                            {"customer_clarification": exc.clarification}
                            if exc.clarification
                            else {}
                        ),
                        "state_mutated": False,
                        "selected_artifact_identity_discarded": False,
                        "source_or_qasm_created": False,
                        "file_mutation_performed": False,
                        "execution_performed": False,
                        "protected_service_called": False,
                        "raw_request_echoed": False,
                        "raw_proposal_echoed": False,
                        "workspace_discovery_performed": False,
                    }
                ),
            )
    else:
        transaction_kind = None
        request_transaction_state = "not_established"
    ignore_review_targets = bool(
        connected_assistant_proposal is not None
        and transaction_kind == "review_before_source_generation"
        and request_transaction_state != "source_modification"
    )
    selected_paths_value = (
        None if ignore_review_targets else arguments.get("selected_artifact_paths")
    )
    if selected_paths_value is not None and (
        not isinstance(selected_paths_value, list)
        or any(not isinstance(item, str) for item in selected_paths_value)
    ):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.selected_artifact_transport_rejection.v1",
                    "ok": False,
                    "category": "exact_selected_artifact_paths_required",
                    "expected_shape": {
                        "selected_artifact_paths": ["exact customer-named workspace-relative path"]
                    },
                    "workspace_discovery_permitted": False,
                    "cli_or_help_fallback_permitted": False,
                    "state_mutated": False,
                }
            ),
        )
    selected_paths = list(selected_paths_value or [])
    if connected_assistant_proposal is not None:
        try:
            normalized_selected = (
                normalize_selected_artifact_paths(
                    selected_paths,
                    workspace_root=coordinator.workspace_root,
                    minimum_count=1,
                    maximum_count=2,
                )
                if selected_paths
                else []
            )
            selected_identities = [
                str(item["workspace_relative_path"]) for item in normalized_selected
            ]
            intended_value = (
                None if ignore_review_targets else arguments.get("intended_artifact_paths")
            )
            if intended_value is not None and not isinstance(intended_value, Mapping):
                raise ArtifactTargetError("exact_intended_artifact_targets_required")
            intended_input = dict(intended_value or {})
            if set(intended_input) - {"source"}:
                raise ArtifactTargetError("review_source_target_only")
            if (
                selected_identities
                and not intended_input
                and transaction_kind == "review_before_source_modification"
            ):
                intended_input = {"source": selected_identities[0]}
            normalized_targets = (
                {}
                if ignore_review_targets
                else normalize_intended_artifact_targets(
                    intended_input or None,
                    workspace_root=coordinator.workspace_root,
                    required_roles=("source",) if intended_input else (),
                )
            )
            payload = coordinator.review_before_generation_transaction(
                exact_request=str(request_text),
                connected_assistant_proposal=connected_assistant_proposal,
                selected_artifact_identities=selected_identities,
                intended_artifact_targets=normalized_targets,
                prior_result_token=(
                    str(prior_result_token) if prior_result_token is not None else None
                ),
            )
        except (ArtifactTargetError, ReviewBeforeGenerationError) as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": ("qcoder.current_loop.review_before_generation_rejection.v2"),
                        "schema_version": 2,
                        "ok": False,
                        "category": str(getattr(exc, "category", exc)),
                        **(
                            {"customer_clarification": exc.clarification}
                            if isinstance(exc, ReviewBeforeGenerationError) and exc.clarification
                            else {}
                        ),
                        "state_mutated": False,
                        "source_or_qasm_created": False,
                        "file_mutation_performed": False,
                        "execution_performed": False,
                        "protected_service_called": False,
                        "raw_request_echoed": False,
                        "raw_proposal_echoed": False,
                        "workspace_discovery_performed": False,
                    }
                ),
            )
        return _result(message_id, _tool_result(_quiet_review_success_payload(payload)))
    semantics = classify_current_request(
        request_text,
        active_loop=continuation,
        selected_paths=selected_paths,
    )
    if semantics.get("requested_operation") == "selected_result_evidence_controls":
        if arguments.get("intended_artifact_paths") is not None:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.selected_result_control_rejection.v1",
                        "ok": False,
                        "category": "selected_result_controls_use_selected_artifact_paths_only",
                        "workspace_discovery_permitted": False,
                        "cli_or_help_fallback_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        try:
            normalized_selected = normalize_selected_artifact_paths(
                selected_paths,
                workspace_root=coordinator.workspace_root,
                minimum_count=2,
                maximum_count=2,
            )
            if any(
                not _request_explicitly_selects_target(
                    request_text, str(item["workspace_relative_path"])
                )
                for item in normalized_selected
            ):
                raise ArtifactTargetError("selected_result_control_path_not_named_by_customer")
            payload = coordinator.interpret_current_request(
                exact_message=request_text,
                selected_paths=[
                    str(item["workspace_relative_path"]) for item in normalized_selected
                ],
            )
        except (ArtifactTargetError, ResultControlError) as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.selected_result_control_rejection.v1",
                        "ok": False,
                        "category": str(getattr(exc, "category", exc)),
                        "workspace_discovery_permitted": False,
                        "cli_or_help_fallback_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        payload.setdefault("details", {}).update(
            {
                "structured_selected_artifact_transport": "project_local_binding_mcp",
                "selected_artifact_paths_received_once": True,
                "selected_artifact_count": len(normalized_selected),
                "shell_or_cli_transport_used": False,
                "workspace_discovery_performed": False,
                "public_context_bridge_tool": False,
            }
        )
        return _result(message_id, _tool_result(payload))
    actionable_artifact_request = semantics.get(
        "clarification_required"
    ) is False and semantics.get("requested_operation") in {
        "source_generation",
        "source_and_qasm_generation",
        "source_and_local_execution",
        "qasm_export",
        "local_execution",
    }
    required_roles = (
        semantics.get("requested_artifact_roles", ()) if actionable_artifact_request else ()
    )
    intended_paths_value = arguments.get("intended_artifact_paths")
    if intended_paths_value is not None and not isinstance(intended_paths_value, Mapping):
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v2",
                    "ok": False,
                    "category": "exact_intended_artifact_targets_required",
                    "workspace_discovery_permitted": False,
                    "state_mutated": False,
                }
            ),
        )
    intended_paths = dict(intended_paths_value) if isinstance(intended_paths_value, Mapping) else {}
    if semantics.get("preexisting_exact_source_satisfaction_requested") is True:
        if len(selected_paths) != 1 or intended_paths:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.preexisting_satisfaction_rejection.v1",
                        "ok": False,
                        "category": "exact_one_selected_preexisting_source_required",
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        try:
            selected_source = normalize_selected_artifact_paths(
                selected_paths,
                workspace_root=coordinator.workspace_root,
                minimum_count=1,
                maximum_count=1,
            )[0]
        except ArtifactTargetError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.preexisting_satisfaction_rejection.v1",
                        "ok": False,
                        "category": str(exc),
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        selected_relative = str(selected_source["workspace_relative_path"])
        if not _request_explicitly_selects_target(request_text, selected_relative):
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.preexisting_satisfaction_rejection.v1",
                        "ok": False,
                        "category": "preexisting_source_path_not_named_by_customer",
                        "workspace_discovery_permitted": False,
                        "state_mutated": False,
                    }
                ),
            )
        intended_paths["source"] = selected_relative
    target_continuity: dict[str, dict[str, Any]] = {}
    if continuation and isinstance(active_state, Mapping) and isinstance(required_roles, list):
        try:
            for role in required_roles:
                if role not in {"source", "circuit_qasm"}:
                    continue
                current_target = current_registered_role_target(
                    active_state,
                    role=str(role),
                    workspace_root=coordinator.workspace_root,
                )
                if current_target is None:
                    continue
                current_relative = str(current_target["workspace_relative_path"])
                supplied = intended_paths.get(str(role))
                if supplied is None:
                    intended_paths[str(role)] = current_relative
                    target_continuity[str(role)] = current_target
                    continue
                normalized_supplied = normalize_intended_artifact_targets(
                    {str(role): supplied},
                    workspace_root=coordinator.workspace_root,
                    required_roles=(str(role),),
                )[str(role)]
                supplied_relative = str(normalized_supplied["workspace_relative_path"])
                if supplied_relative == current_relative:
                    target_continuity[str(role)] = current_target
                    continue
                if not _request_explicitly_selects_target(request_text, supplied_relative):
                    raise ArtifactTargetError(
                        "active_loop_replacement_target_requires_exact_customer_selection"
                    )
        except ArtifactTargetError as exc:
            return _result(
                message_id,
                _tool_result(
                    {
                        "schema_id": "qcoder.current_loop.replacement_target_rejection.v1",
                        "ok": False,
                        "category": str(exc),
                        "current_registered_target_retained": True,
                        "workspace_discovery_permitted": False,
                        "selected_file_review_inferred": False,
                        "state_mutated": False,
                    }
                ),
            )
    try:
        normalize_intended_artifact_targets(
            intended_paths or None,
            workspace_root=coordinator.workspace_root,
            required_roles=required_roles if isinstance(required_roles, list) else (),
        )
    except ArtifactTargetError as exc:
        return _result(
            message_id,
            _tool_result(
                {
                    "schema_id": "qcoder.current_loop.structured_activation_rejection.v2",
                    "ok": False,
                    "category": str(exc),
                    "expected_shape": {
                        "request_text": "exact customer message",
                        "intended_artifact_paths": {
                            str(role): "exact workspace-relative path" for role in required_roles
                        },
                    },
                    "workspace_discovery_permitted": False,
                    "state_mutated": False,
                    "raw_request_echoed": False,
                    "raw_absolute_path_echoed": False,
                }
            ),
        )
    payload = (
        coordinator.interpret_current_request(
            exact_message=request_text,
            selected_paths=selected_paths,
            intended_artifact_paths=(intended_paths or None),
            intended_artifact_target_binding_modes={
                role: "registered_current_role_head_exact_target" for role in target_continuity
            }
            or None,
        )
        if continuation
        else coordinator.activate(
            original_request=request_text,
            explicit_authority=True,
            capture_mode="exact_current_customer_message",
            request_transport="binding_owned_structured_mcp_argument",
            intended_artifact_paths=(intended_paths or None),
        )
    )
    payload.setdefault("details", {}).update(
        {
            "structured_activation_transport": "project_local_binding_mcp",
            "request_text_argument_received_once": True,
            "shell_or_cli_transport_used": False,
            "stdin_transport_used": False,
            "public_context_bridge_tool": False,
            "active_loop_continuation": continuation,
            "request_baseline_recreated": False if continuation else None,
            "rebootstrap_performed": False if continuation else None,
            "active_loop_target_continuity": {
                role: {
                    "binding_mode": value.get("binding_mode"),
                    "artifact_revision_id": value.get("artifact_revision_id"),
                    "workspace_discovery_performed": False,
                }
                for role, value in sorted(target_continuity.items())
            },
        }
    )
    return _result(message_id, _tool_result(payload))


def _write_content_length_response(response: Mapping[str, Any]) -> None:
    data = json.dumps(dict(response), sort_keys=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _record_connection_exchange_best_effort(
    *,
    connection_state_root: str | Path | None,
    connection_generation: str | None,
    connection_session_sha256: str | None,
    message: object,
    response: Mapping[str, Any] | None,
) -> None:
    if (
        connection_state_root is None
        or connection_generation is None
        or connection_session_sha256 is None
        or not isinstance(message, Mapping)
    ):
        return
    try:
        record_server_exchange(
            state_root=connection_state_root,
            setup_generation=connection_generation,
            configured_client_session_sha256=connection_session_sha256,
            server_name=BINDING_MCP_SERVER_NAME,
            request=message,
            response=response,
        )
    except Exception:  # noqa: BLE001 - diagnostic failure must not alter the protocol response
        return


def handle_binding_jsonrpc_message(
    message: Mapping[str, Any], *, workspace_root: str | Path
) -> dict[str, Any] | None:
    """Handle one MCP request and retain one bounded process-local timing receipt."""

    operation_entry = time.monotonic()
    response = _handle_binding_jsonrpc_message(message, workspace_root=workspace_root)
    processing_complete = time.monotonic()
    result_return_boundary = time.monotonic()
    _LAST_BINDING_TIMING.set(
        {
            "schema_id": "qcoder.current_loop.binding_local_timing.v1",
            "schema_version": 1,
            "operation_entry_monotonic_seconds": operation_entry,
            "processing_complete_monotonic_seconds": processing_complete,
            "result_return_boundary_monotonic_seconds": result_return_boundary,
            "processing_seconds": max(0.0, processing_complete - operation_entry),
            "return_boundary_seconds": max(0.0, result_return_boundary - processing_complete),
            "total_qcoder_local_seconds": max(0.0, result_return_boundary - operation_entry),
            "process_and_discard": True,
            "customer_visible": False,
        }
    )
    return response


def consume_last_binding_timing() -> dict[str, Any] | None:
    """Consume the latest request-local timing receipt without persistent telemetry."""

    value = _LAST_BINDING_TIMING.get()
    _LAST_BINDING_TIMING.set(None)
    return dict(value) if isinstance(value, Mapping) else None


def serve_binding_mcp_stdio(
    *,
    workspace_root: str | Path,
    connection_state_root: str | Path | None = None,
    connection_generation: str | None = None,
    connection_session_sha256: str | None = None,
) -> int:
    """Serve the internal binding MCP over JSON-lines or Content-Length stdio."""

    stdin = sys.stdin.buffer
    timing_enabled = bool(
        connection_state_root is not None
        and connection_generation is not None
        and connection_session_sha256 is not None
    )
    if timing_enabled:
        try:
            clear_stdio_operator_timing(state_root=connection_state_root)
        except Exception:  # noqa: BLE001 - operator evidence cannot alter MCP behavior
            pass
    while True:
        first = stdin.readline()
        if not first:
            break
        if not first.strip():
            continue
        stdio_operation_entry_ns = time.monotonic_ns()
        framed = not first.lstrip().startswith(b"{")
        raw = first
        if framed:
            headers: dict[str, str] = {}
            line = first
            while line:
                stripped = line.strip()
                if not stripped:
                    break
                if b":" in stripped:
                    key, value = stripped.split(b":", 1)
                    headers[key.decode("ascii", "ignore").lower()] = value.decode(
                        "ascii", "ignore"
                    ).strip()
                line = stdin.readline()
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 1_048_576:
                response = _error(None, -32600, "invalid_content_length")
                _write_content_length_response(response)
                continue
            raw = stdin.read(length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = _error(None, -32700, "parse_error")
        else:
            response = (
                handle_binding_jsonrpc_message(message, workspace_root=workspace_root)
                if isinstance(message, Mapping)
                else _error(None, -32600, "invalid_request")
            )
            _record_connection_exchange_best_effort(
                connection_state_root=connection_state_root,
                connection_generation=connection_generation,
                connection_session_sha256=connection_session_sha256,
                message=message,
                response=response,
            )
        stdio_processing_complete_ns = time.monotonic_ns()
        if response is None:
            continue
        if framed:
            _write_content_length_response(response)
        else:
            print(json.dumps(response, sort_keys=True), flush=True)
        stdio_result_return_ns = time.monotonic_ns()
        if timing_enabled:
            try:
                record_stdio_operator_timing(
                    state_root=connection_state_root,
                    setup_generation=str(connection_generation),
                    session_sha256=str(connection_session_sha256),
                    operation_entry_ns=stdio_operation_entry_ns,
                    processing_complete_ns=stdio_processing_complete_ns,
                    result_return_ns=stdio_result_return_ns,
                )
            except Exception:  # noqa: BLE001 - operator evidence cannot alter MCP behavior
                pass
    return 0


__all__ = [
    "BEGIN_CURRENT_LOOP_TOOL_NAME",
    "COMPLETE_CURRENT_STEP_TOOL_NAME",
    "BINDING_MCP_SCHEMA_ID",
    "BINDING_MCP_SERVER_NAME",
    "binding_tool_descriptors",
    "consume_last_binding_timing",
    "handle_binding_jsonrpc_message",
    "serve_binding_mcp_stdio",
]
