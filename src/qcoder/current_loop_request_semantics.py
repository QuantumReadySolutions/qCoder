"""Canonical D-080 current-request semantics and temporary stage authority.

This module is deliberately pure.  It classifies one exact customer message
from bounded linguistic features, never from transcript history, repository
state, local paths, or a remembered operation sequence.  The resulting object
is the single semantic input to bootstrap routing, action construction,
operation receipts, and artifact registration ceilings.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence


REQUEST_SEMANTICS_SCHEMA_ID = "qcoder.current_loop.request_semantics.v2"
REQUEST_SEMANTICS_SCHEMA_VERSION = 2
REQUEST_RECOVERY_SCHEMA_ID = "qcoder.current_loop.request_semantics_recovery.v1"

ARTIFACT_ROLES = ("source", "circuit_qasm", "results")
STAGE_OPERATIONS = (
    "source_generation",
    "source_and_qasm_generation",
    "source_and_local_execution",
    "qasm_export",
    "local_execution",
    "selected_artifact_review",
    "current_loop_evidence_diff",
    "close_current_loop",
    "abandon_current_loop",
    "bounded_single_capability",
    "informational",
    "setup_guidance",
    "ambiguous",
    "inactive",
)

_WORD = r"[\w+.-]+"
_SOURCE_ACTIONS = frozenset(
    {
        "write",
        "create",
        "make",
        "generate",
        "produce",
        "build",
        "draft",
        "edit",
        "modify",
        "update",
        "refactor",
    }
)
_SOURCE_NOUNS = frozenset(
    {
        "algorithm",
        "code",
        "example",
        "file",
        "implementation",
        "program",
        "python",
        "qiskit",
        "script",
        "source",
    }
)
_EXECUTION_WORDS = frozenset(
    {
        "run",
        "running",
        "execute",
        "executing",
        "execution",
        "simulate",
        "simulation",
        "backend",
    }
)
_RESULT_WORDS = frozenset({"count", "counts", "result", "results", "shots", "shot"})
_QASM_WORDS = frozenset({"qasm", "openqasm"})
_REVIEW_WORDS = frozenset({"review", "inspect", "analyze", "analyse", "check"})
_DEFERRED_MARKERS = ("later", "afterward", "afterwards", "next step", "another step")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("’", "'").replace("`", "'")
    normalized = re.sub(r"[\u2010-\u2015]", "-", normalized)
    return " ".join(normalized.split())


def _words(value: str) -> tuple[str, ...]:
    return tuple(token.strip(".-") for token in re.findall(_WORD, value) if token.strip(".-"))


def _has_any(words: Sequence[str], choices: frozenset[str]) -> bool:
    return any(word in choices for word in words)


def _has_affirmative_action(normalized: str, terms: Sequence[str]) -> bool:
    """Return whether at least one action occurrence is outside a negated clause."""

    joined = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    for match in re.finditer(rf"\b(?:{joined})\b", normalized):
        clause_start = max(
            normalized.rfind(delimiter, 0, match.start())
            for delimiter in (".", "!", "?", ";", ",", ":")
        )
        prefix = normalized[clause_start + 1 : match.start()]
        if len(prefix) > 64:
            prefix = prefix[-64:]
        if not re.search(r"\b(?:do not|don't|dont|never|not|without)\b", prefix):
            return True
    return False


def _negated(normalized: str, terms: Sequence[str]) -> bool:
    joined = "|".join(re.escape(term) for term in terms)
    patterns = (
        rf"\b(?:do not|don't|dont|not|never|without|no)\b[^.!?;]{{0,42}}\b(?:{joined})\b",
        rf"\b(?:{joined})\b[^.!?;]{{0,24}}\b(?:prohibited|forbidden|later)\b",
        rf"\b(?:stop|pause)\b[^.!?;]{{0,32}}\bbefore\b[^.!?;]{{0,16}}\b(?:{joined})\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _deferred(normalized: str, terms: Sequence[str]) -> bool:
    joined = "|".join(re.escape(term) for term in terms)
    later = "|".join(re.escape(term) for term in _DEFERRED_MARKERS)
    return bool(
        re.search(rf"\b(?:{joined})\b[^.!?;]{{0,40}}\b(?:{later})\b", normalized)
        or re.search(rf"\b(?:{later})\b[^.!?;]{{0,40}}\b(?:{joined})\b", normalized)
    )


def _explicit_qcoder_request(normalized: str) -> bool:
    return bool(re.search(r"\bqcoder\b", normalized))


def _question_or_information(
    normalized: str, *, concrete_supported_task: bool
) -> tuple[bool, str | None]:
    candidate = re.sub(r"^(?:please\s+|kindly\s+)", "", normalized)
    if re.search(r"\b(?:setup|install|configure|configuration)\b", normalized) and not (
        concrete_supported_task
    ):
        return True, "setup_guidance"
    if re.match(r"^(?:can|could|would|is|does|what|why|how)\b", candidate) and not (
        concrete_supported_task
    ):
        return True, "capability_or_information_question"
    return False, None


def _review_intent(normalized: str, words: Sequence[str]) -> bool:
    if _has_any(words, _REVIEW_WORDS):
        return True
    return bool(
        re.search(r"\blook\s+(?:at|over)\b", normalized)
        or re.search(r"\btell\s+me\b[^.!?;]{0,48}\b(?:evidence|results?)\b", normalized)
    )


def _affirmative_review_intent(normalized: str, words: Sequence[str]) -> bool:
    if _has_any(words, _REVIEW_WORDS) and _has_affirmative_action(normalized, tuple(_REVIEW_WORDS)):
        return True
    if re.search(r"\blook\s+(?:at|over)\b", normalized):
        return _has_affirmative_action(normalized, ("look",))
    if re.search(r"\btell\s+me\b[^.!?;]{0,48}\b(?:evidence|results?)\b", normalized):
        return _has_affirmative_action(normalized, ("tell",))
    return False


def _semantic_recovery(
    *,
    category: str,
    clarification: str | None,
    retained_narrowing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_id": REQUEST_RECOVERY_SCHEMA_ID,
        "schema_version": 1,
        "reason_category": category,
        "recovery_category": (
            "ask_one_concise_stage_clarification"
            if clarification
            else "retain_valid_semantics_and_retry_supported_stage"
        ),
        "customer_clarification": clarification,
        "valid_narrowing_retained": deepcopy(dict(retained_narrowing or {})),
        "loop_mutation_permitted_before_recovery": False,
        "authority_broadening_permitted": False,
        "raw_artifact_included": False,
        "local_path_included": False,
        "secret_included": False,
        "fail_closed": True,
    }
    result["recovery_digest"] = _digest(result)
    return result


def _stage_ceiling(
    *,
    operation: str,
    allowed_roles: Sequence[str],
    execution: str,
    evidence_review: str,
    stop_after: str,
) -> dict[str, Any]:
    roles = list(dict.fromkeys(str(role) for role in allowed_roles))
    prohibited = [role for role in ARTIFACT_ROLES if role not in roles]
    allowed_operations: list[str]
    if operation == "source_generation":
        allowed_operations = ["ide_write_source"]
    elif operation == "source_and_qasm_generation":
        allowed_operations = ["ide_write_source", "ide_export_qasm"]
    elif operation == "source_and_local_execution":
        allowed_operations = ["ide_write_source", "ide_execute_local"]
    elif operation == "qasm_export":
        allowed_operations = ["ide_export_qasm"]
    elif operation == "local_execution":
        allowed_operations = ["ide_execute_local"]
    elif operation == "selected_artifact_review":
        allowed_operations = ["local_selected_artifact_review"]
    elif operation == "current_loop_evidence_diff":
        allowed_operations = ["current_loop_evidence_diff"]
    else:
        allowed_operations = []
    result = {
        "schema_id": "qcoder.current_loop.current_step_ceiling.v1",
        "schema_version": 1,
        "temporary_current_step_authority": True,
        "durable_blueprint_constraint": False,
        "allowed_operations": allowed_operations,
        "allowed_artifact_roles": roles,
        "artifact_role_cardinality": {role: "exactly_one" for role in roles},
        "maximum_artifacts_per_authorized_substage": 1 if roles else 0,
        "prohibited_artifact_roles": prohibited,
        "execution_disposition": execution,
        "evidence_review_disposition": evidence_review,
        "stop_after": stop_after,
        "later_customer_instruction_may_create_new_step": True,
        "large_artifact_or_gate_enumeration": False,
    }
    result["ceiling_digest"] = _digest(result)
    return result


def _authority_layers(*, operation: str, active_loop: bool) -> dict[str, Any]:
    if operation in {
        "source_generation",
        "source_and_qasm_generation",
        "source_and_local_execution",
        "qasm_export",
    }:
        next_object = "exact_bounded_ide_write_or_export"
        native_action = "exact_local_file_write"
    elif operation == "local_execution":
        next_object = "exact_bounded_local_execution"
        native_action = "exact_local_execution"
    elif operation == "selected_artifact_review":
        next_object = "exact_selected_artifact_review"
        native_action = "exact_native_file_selection_and_read"
    elif operation == "current_loop_evidence_diff":
        next_object = "current_loop_evidence_diff"
        native_action = "none"
    else:
        next_object = "none"
        native_action = "none"
    return {
        "schema_id": "qcoder.current_loop.authority_layers.v2",
        "schema_version": 2,
        "current_loop_activation": {
            "required": not active_loop,
            "object": "exact_message_request_baseline_and_assist_only",
            "grants_ide_write": False,
            "grants_execution": False,
            "grants_evidence_review": False,
        },
        "qcoder_bounded_action": {
            "object": next_object,
            "derived_from_current_request_semantics": True,
            "defines_only_acceptable_completion_evidence": True,
            "grants_native_client_permission": False,
        },
        "native_client_permission": {
            "owner": "native_client",
            "applicable": native_action != "none",
            "requirement": "client_determined",
            "required_by_qcoder": False,
            "object": native_action,
            "action_specific": True,
            "granted_by_qcoder": False,
            "observed_by_qcoder": False,
            "user_approval_click_inferred": False,
            "explicit_client_telemetry": "optional_provenance_only",
            "customer_facing_label": (
                "The native client applies its controls to this source write"
                if operation
                in {"source_generation", "source_and_qasm_generation", "source_and_local_execution"}
                else "The native client applies its controls to this QASM export"
                if operation == "qasm_export"
                else "The native client applies its controls to this local execution"
                if operation in {"source_and_local_execution", "local_execution"}
                else "The native client applies its controls to these selected-file reads"
                if operation == "selected_artifact_review"
                else "The native client applies its controls to this bounded local action"
            ),
        },
        "native_action_completion_evidence": {
            "accepted_only_against_active_qcoder_bounded_action": True,
            "exact_workspace_loop_request_revision_role_path_bytes_required": True,
            "client_approval_telemetry_required": False,
            "registration_consumes_action_once": True,
        },
        "later_artifact_or_governing_authority": {
            "granted": False,
            "artifact_review_separate": True,
            "governing_change_confirmation_separate": True,
        },
        "use_qcoder_is_blanket_authority": False,
        "blueprint_confirmation_is_ide_authority": False,
        "source_write_is_execution_authority": False,
        "execution_is_evidence_review_authority": False,
        "evidence_review_is_governing_change_authority": False,
    }


def classify_current_request(
    exact_message: str,
    *,
    active_loop: bool = False,
    selected_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Return deterministic D-080 semantics for one exact customer message."""

    if not isinstance(exact_message, str) or not exact_message.strip():
        raise ValueError("current_request_exact_message_required")
    if len(exact_message) > 20_000:
        raise ValueError("current_request_exact_message_too_large")
    normalized = _normalized(exact_message)
    words = _words(normalized)
    explicit_qcoder = _explicit_qcoder_request(normalized)
    review_intent = _review_intent(normalized, words)
    affirmative_review_intent = _affirmative_review_intent(normalized, words)
    review_deferred = _deferred(
        normalized,
        tuple(_REVIEW_WORDS | frozenset({"look", "reviewing", "inspection"})),
    )
    diff_request = bool(
        active_loop
        and re.search(
            r"\b(?:show|review|compare)\b[^.!?;]{0,36}\b(?:changed|changes|difference|diff)\b",
            normalized,
        )
    )
    close_action = bool(
        re.search(
            r"\b(?:close|finish|end)\s+(?:(?:this|the)\s+)?(?:current\s+)?"
            r"(?:qcoder(?:\s+(?:loop|session))?|loop|session|build)\b",
            normalized,
        )
        or re.search(
            r"\bwe(?:'re| are)\s+done\b(?:\s+with)?\s+"
            r"(?:(?:this|the)\s+)?(?:qcoder\s+)?(?:loop|session|build)\b",
            normalized,
        )
    )
    close_request = bool(
        active_loop
        and close_action
        and _has_affirmative_action(normalized, ("close", "finish", "end", "done"))
    )
    abandon_action = bool(
        re.search(
            r"\b(?:abandon|discard|throw\s+away)\s+"
            r"(?:(?:this|the)\s+)?(?:current\s+)?"
            r"(?:qcoder(?:\s+(?:loop|session))?|loop|session|build)\b",
            normalized,
        )
    )
    abandon_request = bool(
        active_loop
        and abandon_action
        and _has_affirmative_action(normalized, ("abandon", "discard", "throw"))
    )

    qasm_mentioned = _has_any(words, _QASM_WORDS)
    execution_mentioned = _has_any(words, _EXECUTION_WORDS)
    results_mentioned = _has_any(words, _RESULT_WORDS)
    non_action_execution_reference = bool(
        re.search(
            r"\bkeep\b[^.!?;]{0,40}\b(?:run|running|execution|simulation)\b",
            normalized,
        )
        or re.search(
            r"\b(?:close|finish|end)\s+(?:(?:the|this)\s+)?(?:local\s+)?"
            r"(?:editor|execution|run|simulation|backend)\b",
            normalized,
        )
    )
    qasm_prohibited = qasm_mentioned and (
        _negated(normalized, tuple(_QASM_WORDS)) or _deferred(normalized, tuple(_QASM_WORDS))
    )
    execution_prohibited = execution_mentioned and (
        _negated(normalized, tuple(_EXECUTION_WORDS))
        or _deferred(normalized, tuple(_EXECUTION_WORDS))
    )
    results_prohibited = results_mentioned and (
        _negated(normalized, tuple(_RESULT_WORDS)) or _deferred(normalized, tuple(_RESULT_WORDS))
    )
    source_action_candidate = _has_any(words, _SOURCE_ACTIONS) and (
        _has_any(words, _SOURCE_NOUNS)
        or (
            (active_loop or explicit_qcoder)
            and bool(
                re.search(
                    r"\b(?:write|create|make|generate|produce|build|draft|edit|modify|update|refactor)\b"
                    r"[^.!?;]{0,28}\b(?:it|this)\b",
                    normalized,
                )
            )
        )
    )
    source_action = source_action_candidate and _has_affirmative_action(
        normalized, tuple(_SOURCE_ACTIONS)
    )
    negated_supported_task = bool(
        explicit_qcoder
        and (
            (source_action_candidate and not source_action)
            or (review_intent and not affirmative_review_intent)
        )
    )
    negated_terminal_action = bool(
        active_loop
        and ((close_action and not close_request) or (abandon_action and not abandon_request))
    )
    informational, information_category = _question_or_information(
        normalized,
        concrete_supported_task=source_action or (review_intent and not review_deferred),
    )
    qasm_requested = qasm_mentioned and not qasm_prohibited
    execution_requested = (
        execution_mentioned and not execution_prohibited and not non_action_execution_reference
    )
    results_requested = results_mentioned and not results_prohibited

    # "Stop after source/code" and "only source/code" are semantic ceiling
    # features independent of the particular customer sentence.
    source_stop = bool(
        re.search(
            r"\b(?:stop|pause)\b[^.!?;]{0,40}\b(?:after|at|with)\b[^.!?;]{0,24}"
            r"\b(?:source|code|python|file|program|script)\b",
            normalized,
        )
        or re.search(
            r"\b(?:only|just)\b[^.!?;]{0,32}\b(?:source|code|python|file|program|script)\b",
            normalized,
        )
        or re.search(
            r"\b(?:source|code|python|file|program|script)\b[^.!?;]{0,32}"
            r"\b(?:only|just|for now)\b",
            normalized,
        )
    )
    later_evidence = bool(
        re.search(r"\b(?:evidence|review|results?)\b[^.!?;]{0,32}\b(?:later|next)\b", normalized)
        or re.search(r"\b(?:later|next)\b[^.!?;]{0,32}\b(?:evidence|review|results?)\b", normalized)
    )
    if later_evidence:
        results_prohibited = True

    operation: str
    route: str
    allowed_roles: list[str]
    execution: str
    evidence_review: str
    stop_after: str
    ambiguity = "none"
    clarification: str | None = None
    recovery: dict[str, Any] | None = None

    if negated_supported_task or negated_terminal_action or non_action_execution_reference:
        operation = "inactive"
        route = "available_inactive"
        allowed_roles = []
        execution = "prohibited_for_current_step"
        evidence_review = "prohibited_for_current_step"
        stop_after = "no_qcoder_operation"
        ambiguity = (
            "stage_reference_without_action_authority"
            if non_action_execution_reference
            else "explicit_action_prohibition"
        )
        recovery = _semantic_recovery(
            category=(
                "stage_reference_not_action_authority"
                if non_action_execution_reference
                else "explicit_action_prohibited"
            ),
            clarification=None,
        )
    elif informational and explicit_qcoder:
        operation = (
            "setup_guidance" if information_category == "setup_guidance" else "informational"
        )
        route = "available_inactive"
        allowed_roles = []
        execution = "not_requested"
        evidence_review = "not_requested"
        stop_after = "answer_without_current_loop_activation"
    elif not explicit_qcoder and not active_loop:
        operation = "inactive"
        route = "available_inactive"
        allowed_roles = []
        execution = "not_requested"
        evidence_review = "not_requested"
        stop_after = "no_qcoder_operation"
    elif diff_request:
        operation = "current_loop_evidence_diff"
        route = "active_loop_continuation"
        allowed_roles = []
        execution = "prohibited_for_current_step"
        evidence_review = "existing_canonical_evidence_only"
        stop_after = "bounded_difference_ready"
    elif affirmative_review_intent and not review_deferred:
        operation = "selected_artifact_review"
        route = "named_d079_workflow"
        allowed_roles = []
        execution = "prohibited_for_current_step"
        evidence_review = "exact_selected_files_only"
        stop_after = "result_review"
        if not selected_paths:
            ambiguity = "missing_required_selection"
            clarification = "Which exact files should qCoder review?"
            recovery = _semantic_recovery(
                category="selected_artifact_required",
                clarification=clarification,
            )
    elif abandon_request:
        operation = "abandon_current_loop"
        route = "active_loop_continuation"
        allowed_roles = []
        execution = "prohibited_for_current_step"
        evidence_review = "prohibited_for_current_step"
        stop_after = "current_loop_abandoned"
    elif close_request:
        operation = "close_current_loop"
        route = "active_loop_continuation"
        allowed_roles = []
        execution = "prohibited_for_current_step"
        evidence_review = "prohibited_for_current_step"
        stop_after = "current_loop_closed"
    elif source_action:
        evidence_review = "prohibited_for_current_step"
        if execution_requested and results_prohibited:
            operation = "ambiguous"
            route = "clarification_required"
            allowed_roles = []
            execution = "not_determined"
            stop_after = "before_loop_mutation"
            ambiguity = "execution_result_disposition_conflict"
            clarification = "Should qCoder run locally without retaining a results artifact?"
            recovery = _semantic_recovery(
                category="requested_stage_combination_unsupported",
                clarification=clarification,
                retained_narrowing={"results_disposition": "prohibited_for_current_step"},
            )
        elif execution_requested or results_requested:
            route = "active_loop_continuation" if active_loop else "active_build"
            operation = "source_and_local_execution"
            allowed_roles = ["source", "results"]
            execution = "requires_separate_exact_execution_authority"
            stop_after = "bounded_local_results_registered"
        elif qasm_requested and not source_stop:
            route = "active_loop_continuation" if active_loop else "active_build"
            operation = "source_and_qasm_generation"
            allowed_roles = ["source", "circuit_qasm"]
            execution = "prohibited_for_current_step"
            stop_after = "qasm_registered"
        else:
            route = "active_loop_continuation" if active_loop else "active_build"
            operation = "source_generation"
            allowed_roles = ["source"]
            execution = "prohibited_for_current_step"
            stop_after = "source_registered"
            qasm_prohibited = True
            results_prohibited = True
    elif active_loop and qasm_requested:
        operation = "qasm_export"
        route = "active_loop_continuation"
        allowed_roles = ["circuit_qasm"]
        execution = "prohibited_for_current_step"
        evidence_review = "prohibited_for_current_step"
        stop_after = "qasm_registered"
    elif active_loop and (execution_requested or results_requested):
        if execution_requested and results_prohibited:
            operation = "ambiguous"
            route = "clarification_required"
            allowed_roles = []
            execution = "not_determined"
            evidence_review = "prohibited_for_current_step"
            stop_after = "before_loop_mutation"
            ambiguity = "execution_result_disposition_conflict"
            clarification = "Should qCoder run locally without retaining a results artifact?"
            recovery = _semantic_recovery(
                category="requested_stage_combination_unsupported",
                clarification=clarification,
                retained_narrowing={"results_disposition": "prohibited_for_current_step"},
            )
        else:
            operation = "local_execution"
            route = "active_loop_continuation"
            allowed_roles = ["results"]
            execution = "requires_separate_exact_execution_authority"
            evidence_review = "prohibited_for_current_step"
            stop_after = "bounded_local_results_registered"
    else:
        # Preserve semantically useful narrowing while refusing to invent a
        # positive operation.  A generic explicit bounded qCoder request may
        # still use the existing one-capability route when it names a concrete
        # review/context capability rather than an unresolved pronoun.
        content = re.sub(r"^(?:please\s+|kindly\s+)", "", normalized).rstrip(".!?")
        unresolved_pronoun = bool(
            re.fullmatch(r"(?:please\s+)?use qcoder for (?:this|it|that)", normalized.rstrip(".!?"))
        )
        underspecified_circuit_action = bool(
            active_loop
            and re.search(
                r"\b(?:make|create|generate|write)\b[^.!?;]{0,28}\bcircuit\b",
                normalized,
            )
            and not _has_any(words, _SOURCE_NOUNS | _QASM_WORDS)
        )
        fragment_only = bool(
            re.fullmatch(
                r"(?:please\s+)?(?:"
                r"(?:do not|don't|dont)\s+(?:run|execute)\s+(?:it|this)(?:\s+yet)?"
                r"|stop\s+(?:there|here)(?:\s+for now)?"
                r")",
                content,
            )
        )
        if unresolved_pronoun or underspecified_circuit_action or fragment_only:
            operation = "ambiguous"
            route = "clarification_required"
            allowed_roles = []
            execution = "prohibited_for_current_step" if execution_prohibited else "not_determined"
            evidence_review = "not_determined"
            stop_after = "before_loop_mutation"
            ambiguity = "stage_not_determinable"
            clarification = "What exact qCoder step should happen now?"
            recovery = _semantic_recovery(
                category="current_request_stage_ambiguous",
                clarification=clarification,
                retained_narrowing={"execution_disposition": execution},
            )
        else:
            operation = "bounded_single_capability"
            route = "single_capability"
            allowed_roles = []
            execution = "prohibited_for_current_step"
            evidence_review = "bounded_capability_only"
            stop_after = "bounded_customer_outcome"

    ceiling = _stage_ceiling(
        operation=operation,
        allowed_roles=allowed_roles,
        execution=execution,
        evidence_review=evidence_review,
        stop_after=stop_after,
    )
    result: dict[str, Any] = {
        "schema_id": REQUEST_SEMANTICS_SCHEMA_ID,
        "schema_version": REQUEST_SEMANTICS_SCHEMA_VERSION,
        "exact_original_message": exact_message,
        "original_message_utf8_sha256": sha256(exact_message.encode("utf-8")).hexdigest(),
        "qcoder_explicitly_requested": explicit_qcoder,
        "active_loop_at_classification": active_loop,
        "request_context": "active_loop_continuation" if active_loop else "fresh_request",
        "route": route,
        "requested_operation": operation,
        "requested_artifact_roles": list(allowed_roles),
        "prohibited_artifact_roles": list(ceiling["prohibited_artifact_roles"]),
        "qasm_disposition": (
            "permitted" if "circuit_qasm" in allowed_roles else "prohibited_for_current_step"
        ),
        "execution_disposition": execution,
        "results_disposition": (
            "permitted_after_exact_execution_authority"
            if "results" in allowed_roles
            else "prohibited_for_current_step"
        ),
        "evidence_review_disposition": evidence_review,
        "current_step_ceiling": ceiling,
        "ambiguity_state": ambiguity,
        "clarification_required": clarification is not None,
        "customer_clarification": clarification,
        "loop_mutation_permitted": clarification is None and route not in {"available_inactive"},
        "bootstrap_required": route == "active_build",
        "rebootstrap_permitted": False if active_loop else route == "active_build",
        "request_baseline_recreation_permitted": False if active_loop else route == "active_build",
        "authority_layers": _authority_layers(operation=operation, active_loop=active_loop),
        "next_authority_object": _authority_layers(operation=operation, active_loop=active_loop)[
            "native_client_permission"
        ]["object"],
        "recovery": recovery,
        "classifier_properties": {
            "compositional_feature_classification": True,
            "exact_sentence_identity_used_for_routing": False,
            "repository_or_transcript_consulted": False,
            "raw_artifact_consulted": False,
            "gate_count_consulted": False,
        },
    }
    result["semantics_digest"] = _digest(result)
    validate_request_semantics(result)
    return result


def validate_request_semantics(value: Mapping[str, Any]) -> None:
    if (
        value.get("schema_id") != REQUEST_SEMANTICS_SCHEMA_ID
        or value.get("schema_version") != REQUEST_SEMANTICS_SCHEMA_VERSION
        or value.get("requested_operation") not in STAGE_OPERATIONS
    ):
        raise ValueError("current_request_semantics_invalid")
    message = value.get("exact_original_message")
    if not isinstance(message, str) or not message:
        raise ValueError("current_request_semantics_message_invalid")
    if value.get("original_message_utf8_sha256") != sha256(message.encode("utf-8")).hexdigest():
        raise ValueError("current_request_semantics_message_digest_mismatch")
    roles = value.get("requested_artifact_roles")
    if not isinstance(roles, list) or any(role not in ARTIFACT_ROLES for role in roles):
        raise ValueError("current_request_semantics_role_invalid")
    ceiling = value.get("current_step_ceiling")
    if not isinstance(ceiling, Mapping) or ceiling.get("allowed_artifact_roles") != roles:
        raise ValueError("current_request_semantics_ceiling_mismatch")
    supplied = value.get("semantics_digest")
    unsigned = deepcopy(dict(value))
    unsigned.pop("semantics_digest", None)
    if supplied != _digest(unsigned):
        raise ValueError("current_request_semantics_digest_mismatch")


def migrate_request_semantics(value: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade the pre-D-081 authority projection without changing request meaning."""

    result = deepcopy(dict(value))
    if (
        result.get("schema_id") == "qcoder.current_loop.request_semantics.v1"
        and result.get("schema_version") == 1
    ):
        operation = str(result.get("requested_operation"))
        active_loop = bool(result.get("active_loop_at_classification"))
        result["schema_id"] = REQUEST_SEMANTICS_SCHEMA_ID
        result["schema_version"] = REQUEST_SEMANTICS_SCHEMA_VERSION
        result["authority_layers"] = _authority_layers(
            operation=operation, active_loop=active_loop
        )
        result["next_authority_object"] = result["authority_layers"][
            "native_client_permission"
        ]["object"]
        result.pop("semantics_digest", None)
        result["semantics_digest"] = _digest(result)
    validate_request_semantics(result)
    return result


def ceiling_allows(
    semantics: Mapping[str, Any],
    *,
    operation: str | None = None,
    artifact_roles: Sequence[str] = (),
) -> bool:
    """Return whether the exact current-step ceiling permits an action."""

    validate_request_semantics(semantics)
    ceiling = semantics["current_step_ceiling"]
    if operation is not None and operation not in ceiling["allowed_operations"]:
        return False
    allowed = set(ceiling["allowed_artifact_roles"])
    return all(role in allowed for role in artifact_roles)


def semantics_contract_snapshot() -> dict[str, Any]:
    result = {
        "schema_id": "qcoder.current_loop.request_semantics_contract.v2",
        "schema_version": 2,
        "semantic_schema_id": REQUEST_SEMANTICS_SCHEMA_ID,
        "natural_language_in_exact_authority_out": True,
        "exact_original_message_preserved": True,
        "temporary_current_step_ceiling": True,
        "durable_blueprint_constraint": False,
        "authority_layers": [
            "current_loop_activation",
            "qcoder_bounded_action",
            "native_client_permission",
            "later_artifact_or_governing_authority",
        ],
        "classifier_uses_sentence_phrasebook": False,
        "classifier_uses_compositional_features": True,
        "active_loop_continuation_recreates_baseline": False,
        "stage_ceiling_applies_to": [
            "compact_next_action",
            "operation_invocation",
            "bounded_action_expectation",
            "native_action_completion_evidence",
            "artifact_registration",
        ],
        "native_client_permission_owner": "native_client",
        "native_client_permission_observed_or_granted_by_qcoder": False,
        "repository_or_transcript_lookup": False,
        "gate_count_or_raw_artifact_in_semantics": False,
    }
    result["contract_digest"] = _digest(result)
    return result
