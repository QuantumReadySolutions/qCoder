"""Deterministic review-before-generation validation and projection.

The connected assistant supplies the semantic interpretation and substantive
recommendations. qCoder owns request binding, fixed structure, attribution,
authority, projection safety, revision integrity, and confirmation boundaries.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Iterator, Mapping, Sequence
import unicodedata
import warnings

from qcoder.core.share_safe import contains_local_path, contains_token_or_header


PROPOSAL_SCHEMA_ID = "qcoder.connected_assistant.review_before_generation_proposal.v2"
SEMANTICS_SCHEMA_ID = "qcoder.current_loop.review_before_generation_semantics.v1"
FIRST_VALUE_SCHEMA_ID = "qcoder.current_loop.review_before_generation_first_value.v2"
TRANSACTION_SCHEMA_ID = "qcoder.current_loop.review_before_generation_transaction.v2"
CONTRACT_SCHEMA_ID = "qcoder.current_loop.review_before_generation_contract.v2"

PROPOSAL_ATTRIBUTION = "connected_assistant"
CONNECTED_ASSISTANT_ATTRIBUTION = "connected_assistant_recommendation"
CUSTOMER_ATTRIBUTION = "customer_explicit_constraint"
QCODER_ATTRIBUTION = "qcoder_deterministic_boundary"
GROUPS = (
    ("goal_and_scope", "Goal and scope"),
    ("implementation", "Implementation"),
    ("output_and_authority", "Output and authority"),
)
CUSTOMER_ACTIONS = ("Use recommended choices", "Review or change choices")
TRANSACTION_KINDS = (
    "review_before_source_generation",
    "review_before_source_modification",
)
EXECUTION_REQUESTS = ("not_requested", "held_for_separate_authorization")

_PLACEHOLDERS = {
    "tbd",
    "todo",
    "unknown",
    "unspecified",
    "placeholder",
    "generic approach",
    "details not assumed",
    "remaining details are not assumed",
    "as requested",
    "a concrete option will be used",
    "a framework will be selected",
    "use an appropriate approach",
    "use a suitable implementation",
    "follow best practices",
    "implement as requested",
    "details will be determined",
    "a standard method will be used",
    "the remaining choices are not assumed",
}
_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "credential",
    "authorization_header",
    "authentication",
    "profile_storage",
    "private_configuration",
    "reasoning_trace",
    "model_metadata",
    "raw_output",
    "raw_stream",
)
_CONSEQUENTIAL_VALUE = re.compile(
    r"\b(?:qiskit|quantumcircuit|cirq|pennylane|python|rust|javascript|openqasm|"
    r"circuit|register|qubit|classical bit|oracle|diffusion|ansatz|mixer|cost layer|"
    r"mapping|representation|measurement|measure|apply h|apply cx|cnot|conditional|"
    r"function|module|class|json|readable source)\b",
    re.IGNORECASE,
)
_SAFE_PYTHON_BINARY_OPERATORS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
)
_SAFE_PYTHON_UNARY_OPERATORS = (ast.UAdd, ast.USub)
_QASM_STATEMENT_KEYWORDS = (
    "OPENQASM",
    "include",
    "qubit",
    "bit",
    "qreg",
    "creg",
    "gate",
    "measure",
    "reset",
    "barrier",
    "delay",
    "defcalgrammar",
    "defcal",
    "cal",
    "let",
    "alias",
    "int",
    "uint",
    "float",
    "angle",
    "bool",
    "duration",
    "stretch",
    "complex",
    "array",
    "const",
    "box",
    "extern",
    "input",
    "output",
    "pragma",
    "if",
    "else",
    "for",
    "while",
    "switch",
    "return",
    "end",
    "break",
    "continue",
)
_QASM_STATEMENT_HEAD = "(?:" + "|".join(_QASM_STATEMENT_KEYWORDS) + ")"
_QASM_REFERENCE = r"(?:\$\d+|[A-Za-z_]\w*(?:\s*\[[^\]\r\n;{}]+\])?)"
_QASM_STRUCTURAL_PATTERNS = (
    re.compile(r"^\s*OPEN\s*QASM(?=\s*(?:\d|;|$))", re.IGNORECASE),
    re.compile(
        rf"^\s*{_QASM_STATEMENT_HEAD}\b[^\r\n]*;(?:\s*)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:gate|def|defcal|cal|box|if|else|for|while|switch)\b[^\r\n]*\{"
        r"[\s\S]*\}\s*;?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^\s*(?:ctrl|negctrl|inv|pow)(?:\s*\([^;\r\n]*\))?\s*@\s*"
        rf"[A-Za-z_]\w*(?:\s*\([^;\r\n]*\))?\s+{_QASM_REFERENCE}"
        rf"(?:\s*,\s*{_QASM_REFERENCE})*\s*;\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^\s*[A-Za-z_]\w*(?:\s*\([^;\r\n]*\))?\s+{_QASM_REFERENCE}"
        rf"(?:\s*,\s*{_QASM_REFERENCE})*\s*;\s*$",
    ),
    re.compile(
        rf"^\s*{_QASM_REFERENCE}\s*=\s*[^;\r\n]+;\s*$",
        re.IGNORECASE,
    ),
)
_MAX_PROJECTION_FIELDS = 256
_MAX_PROJECTION_BYTES = 100_000
_MAX_PROJECTION_SEQUENCE_WORK_BYTES = 8_000_000
_MATERIAL_CONSTRAINT_TERMS = frozenset(
    {
        "algorithm",
        "artifact",
        "before",
        "bell",
        "bit",
        "bits",
        "circuit",
        "code",
        "confirm",
        "confirmation",
        "create",
        "creating",
        "cx",
        "execute",
        "execution",
        "file",
        "generate",
        "generating",
        "h",
        "measure",
        "measures",
        "measuring",
        "measurement",
        "modify",
        "openqasm",
        "output",
        "program",
        "python",
        "qasm",
        "qiskit",
        "qubit",
        "qubits",
        "readable",
        "review",
        "source",
        "state",
        "two",
        "write",
        "writing",
        "φ",
    }
)
_TRIVIAL_CONSTRAINTS = frozenset(
    {
        "a",
        "an",
        "and",
        "help",
        "help me",
        "please",
        "qcoder",
        "the",
        "to",
        "use qcoder",
        "use qcoder to help me",
    }
)
_INTRINSIC_SINGLE_TOKEN_CONSTRAINTS = frozenset(
    {
        "bell",
        "cirq",
        "openqasm",
        "pennylane",
        "python",
        "qasm",
        "qiskit",
        "qubit",
        "qubits",
        "source",
        "φ",
    }
)


class ReviewBeforeGenerationError(ValueError):
    """Bounded customer-safe proposal or transaction rejection."""

    def __init__(self, category: str, *, clarification: str | None = None):
        self.category = category
        self.clarification = clarification
        super().__init__(category)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json(value: Any) -> str:
    """Return the product's stable human-readable JSON form."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def request_digest(exact_request: str) -> str:
    """Compute the authoritative digest from exact received UTF-8 request bytes."""

    return sha256(exact_request.encode("utf-8")).hexdigest()


def _strict_keys(value: Mapping[str, Any], expected: set[str], category: str) -> None:
    if set(value) != expected:
        raise ReviewBeforeGenerationError(category)


def _privacy_error(value: Any, *, key: str = "") -> bool:
    normalized_key = key.casefold().replace("-", "_")
    if any(fragment in normalized_key for fragment in _FORBIDDEN_FIELD_FRAGMENTS):
        return True
    if isinstance(value, Mapping):
        return any(_privacy_error(child, key=str(child_key)) for child_key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_privacy_error(child, key=key) for child in value)
    if isinstance(value, str):
        return contains_local_path(value) or contains_token_or_header(value)
    return False


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _contains_customer_action(value: str) -> bool:
    normalized = _normalized_text(value)
    return any(_normalized_text(action) in normalized for action in CUSTOMER_ACTIONS)


def _is_harmless_python_expression(node: ast.AST, *, depth: int = 0) -> bool:
    """Accept only inert literals, names, and bounded mathematical composition."""

    if depth > 32:
        return False
    if isinstance(node, ast.Constant):
        return type(node.value) in {str, int, float, complex, bool, type(None)}
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, _SAFE_PYTHON_UNARY_OPERATORS) and _is_harmless_python_expression(
            node.operand, depth=depth + 1
        )
    if isinstance(node, ast.BinOp):
        return (
            isinstance(node.op, _SAFE_PYTHON_BINARY_OPERATORS)
            and _is_harmless_python_expression(node.left, depth=depth + 1)
            and _is_harmless_python_expression(node.right, depth=depth + 1)
        )
    if isinstance(node, ast.BoolOp):
        return isinstance(node.op, (ast.And, ast.Or)) and all(
            _is_harmless_python_expression(value, depth=depth + 1) for value in node.values
        )
    return False


def _contains_executable_python(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    # Python 3.12 introduced the soft-keyword type-alias statement. Preserve the
    # same fail-closed boundary when qCoder is running on an older supported AST.
    if re.match(r"^type\s+[A-Za-z_]\w*(?:\s*\[[^\]\r\n]+\])?\s*=", text):
        return True
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text, mode="exec")
    except (SyntaxError, ValueError):
        return False
    except (MemoryError, RecursionError, UnicodeError):
        return True
    if not tree.body:
        return False
    if ";" in text and len(tree.body) > 1:
        return True
    return not all(
        isinstance(statement, ast.Expr) and _is_harmless_python_expression(statement.value)
        for statement in tree.body
    )


def _contains_qasm_source(value: str) -> bool:
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _QASM_STRUCTURAL_PATTERNS)


def _contains_source_or_qasm(value: str) -> bool:
    if "```" in value or "~~~" in value:
        return True
    return _contains_executable_python(value) or _contains_qasm_source(value)


def _contiguous_projection_variants(values: Sequence[str]) -> Iterator[str]:
    bounded = [unicodedata.normalize("NFKC", value).strip() for value in values]
    if len(bounded) > _MAX_PROJECTION_FIELDS:
        raise ReviewBeforeGenerationError("review_projection_aggregate_limit_exceeded")
    if sum(len(value.encode("utf-8")) for value in bounded) > _MAX_PROJECTION_BYTES:
        raise ReviewBeforeGenerationError("review_projection_aggregate_limit_exceeded")
    work = 0
    for separator in ("", " ", "\n"):
        for start in range(len(bounded)):
            joined = ""
            for end in range(start, len(bounded)):
                joined = bounded[end] if end == start else joined + separator + bounded[end]
                work += len(joined.encode("utf-8"))
                if work > _MAX_PROJECTION_SEQUENCE_WORK_BYTES:
                    raise ReviewBeforeGenerationError("review_projection_aggregate_limit_exceeded")
                yield joined


def _projection_contains_source_or_qasm(values: Sequence[str]) -> bool:
    return any(_contains_source_or_qasm(value) for value in _contiguous_projection_variants(values))


def _projection_contains_customer_action(values: Sequence[str]) -> bool:
    return any(
        _contains_customer_action(value) for value in _contiguous_projection_variants(values)
    )


def _unsafe_projection_text(value: str) -> bool:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return True
    if re.search(r"^\s*#{1,6}\s", value):
        return True
    if re.search(r"!?\[[^\]]+\]\([^)]*\)", value):
        return True
    if re.search(r"<\s*/?\s*(?:script|style|iframe|object|embed|button|form|a)\b", value, re.I):
        return True
    if _contains_customer_action(value):
        return True
    return bool(
        re.search(
            r"\b(?:tools/call|inputSchema|connected_assistant_proposal|customer_actions)\b",
            value,
            re.IGNORECASE,
        )
    )


def _bounded_plain_text(value: Any, *, category: str, maximum: int = 2_000) -> str:
    if not isinstance(value, str):
        raise ReviewBeforeGenerationError(category)
    result = value.strip()
    if not result or len(result.encode("utf-8")) > maximum:
        raise ReviewBeforeGenerationError(category)
    if result.casefold().rstrip(".") in _PLACEHOLDERS:
        raise ReviewBeforeGenerationError("review_proposal_not_substantive")
    if contains_local_path(result) or contains_token_or_header(result):
        raise ReviewBeforeGenerationError("review_proposal_private_material_rejected")
    if _unsafe_projection_text(result):
        raise ReviewBeforeGenerationError("review_proposal_unsafe_projection_text")
    if _contains_source_or_qasm(result):
        raise ReviewBeforeGenerationError("review_proposal_source_or_qasm_rejected")
    return result


def _markdown_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "<", ">", "#", "|"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped


def _unquoted_request(exact_request: str) -> str:
    without_straight = re.sub(r'"[^"\r\n]*"', " ", exact_request)
    without_curly = re.sub(r"“[^”\r\n]*”", " ", without_straight)
    return re.sub(r"‘[^’\r\n]*’", " ", without_curly)


def _execution_request_state(exact_request: str) -> str:
    request = " ".join(_unquoted_request(exact_request).casefold().split())
    occurrences = list(re.finditer(r"\b(?:execute|execution|run|simulate|simulation)\b", request))
    if not occurrences:
        return "absent"
    positive = False
    negated = False
    deferred = False
    ambiguous = False
    for occurrence in occurrences:
        before = request[max(0, occurrence.start() - 48) : occurrence.start()]
        after = request[occurrence.end() : occurrence.end() + 64]
        nearby = before + occurrence.group(0) + after
        occurrence_negated = bool(
            re.search(r"\b(?:do\s+not|don't|never|without|no)\b[^.;]{0,32}$", before)
        )
        occurrence_deferred = bool(
            re.search(
                r"\b(?:later|deferred|another\s+step|separate\s+step|future\s+step)\b",
                after,
            )
            or re.search(r"\bdefer(?:red|ring)?\b[^.;]{0,24}$", before)
            or re.search(r"\bin\s+(?:an)?other\s+step\b", nearby)
        )
        if occurrence_negated:
            negated = True
        elif occurrence_deferred:
            deferred = True
        elif occurrence.group(0) in {"execute", "run", "simulate"}:
            positive = True
        else:
            ambiguous = True
    if positive and (negated or deferred):
        return "contradictory_or_ambiguous"
    if positive:
        return "explicit_affirmative"
    if deferred:
        return "deferred"
    if negated:
        return "negated"
    if ambiguous:
        return "contradictory_or_ambiguous"
    return "absent"


def _semantic_axes(transaction_kind: str, execution_request: str) -> dict[str, str]:
    if transaction_kind == "review_before_source_generation":
        ultimate_outcome = "source_generation"
        immediate_interaction = "review_proposed_intent_and_implementation"
        temporal_order = "review_then_confirm_before_generation"
        review_object = "proposed_intent_and_implementation"
    elif transaction_kind == "review_before_source_modification":
        ultimate_outcome = "source_modification"
        immediate_interaction = "review_proposed_changes"
        temporal_order = "review_then_confirm_before_modification"
        review_object = "proposed_changes"
    else:
        raise ReviewBeforeGenerationError("review_proposal_transaction_kind_invalid")
    execution_authority = (
        "not_requested"
        if execution_request == "not_requested"
        else "explicitly_requested_requires_separate_authority"
    )
    return {
        "ultimate_outcome": ultimate_outcome,
        "immediate_interaction": immediate_interaction,
        "temporal_order": temporal_order,
        "review_object": review_object,
        "generation_authority": "held_for_exact_review_confirmation",
        "execution_authority": execution_authority,
    }


def _validate_request_authority(
    exact_request: str,
    axes: Mapping[str, str],
    execution_request: str,
) -> tuple[str, str | None]:
    request = " ".join(_unquoted_request(exact_request).casefold().split())
    if re.search(r"\buse\s+qcoder\b", request) is None:
        raise ReviewBeforeGenerationError("review_request_does_not_activate_qcoder")
    if axes["generation_authority"] == "held_for_exact_review_confirmation" and re.search(
        r"\b(?:generate|write|create|modify|change)\b.{0,40}\b(?:now|immediately|before review)\b",
        request,
    ):
        raise ReviewBeforeGenerationError(
            "review_request_authority_contradiction",
            clarification="Should source be produced now, or only after you confirm the choices?",
        )
    execution_state = _execution_request_state(exact_request)
    if execution_state == "explicit_affirmative":
        if execution_request != "held_for_separate_authorization":
            raise ReviewBeforeGenerationError("review_proposal_execution_request_understated")
    elif execution_request != "not_requested":
        raise ReviewBeforeGenerationError("review_proposal_execution_authority_broadened")
    clarification = (
        "Should execution remain deferred, or be separately authorized after source generation?"
        if execution_state == "contradictory_or_ambiguous"
        else None
    )
    return execution_state, clarification


def _assistant_values_contradict_authority(values: Sequence[str], axes: Mapping[str, str]) -> bool:
    for value in values:
        text = " ".join(value.casefold().split())
        if axes["generation_authority"] == "held_for_exact_review_confirmation" and (
            re.search(r"\b(?:generate|create|write|modify)\b.{0,30}\b(?:now|immediately)\b", text)
            or re.search(
                r"\b(?:generation|source generation|file mutation)\b.{0,24}\b"
                r"(?:authorized|permitted|allowed)\b.{0,12}\bnow\b",
                text,
            )
            or re.search(
                r"\b(?:generate|create|write|modify)\b.{0,30}\bbefore confirmation\b", text
            )
        ):
            return True
        if re.search(
            r"\b(?:execute|run|simulate)\b.{0,24}\b(?:now|immediately|on hardware)\b",
            text,
        ):
            return True
        if re.search(r"\b(?:execution|simulation)\b.{0,20}\b(?:authorized|permitted)\b", text):
            if "not authorized" not in text and "separate authorization" not in text:
                return True
        if re.search(r"\b(?:submit|submission)\b.{0,20}\b(?:backend|hardware)\b", text):
            return True
        if re.search(r"\bconfirmation\b.{0,24}\b(?:grants|authorizes)\b.{0,16}\bexecution\b", text):
            return True
        if re.search(r"\bqcoder\b.{0,16}\b(?:executed|ran|submitted|simulated)\b", text):
            return True
    return False


def _is_consequential(value: str) -> bool:
    text = " ".join(value.casefold().split()).rstrip(".")
    if text in _PLACEHOLDERS:
        return False
    return bool(_CONSEQUENTIAL_VALUE.search(value))


def _customer_constraint_is_material(value: str) -> bool:
    normalized = _normalized_text(value).strip(" .,:;!?()[]{}\"'")
    if not normalized or normalized in _TRIVIAL_CONSTRAINTS:
        return False
    tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    if not tokens or (len(tokens) == 1 and len(tokens[0]) == 1):
        return False
    if len(tokens) == 1:
        return tokens[0] in _INTRINSIC_SINGLE_TOKEN_CONSTRAINTS
    if all(
        token in {"a", "an", "and", "for", "me", "of", "please", "the", "to"} for token in tokens
    ):
        return False
    return any(token in _MATERIAL_CONSTRAINT_TERMS for token in tokens)


def _assistant_item(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value, "attribution": CONNECTED_ASSISTANT_ATTRIBUTION}


def _qcoder_item(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value, "attribution": QCODER_ATTRIBUTION}


def _authority_items(axes: Mapping[str, str], request_execution_state: str) -> list[dict[str, str]]:
    generation = (
        "Source modification will begin after you confirm these choices."
        if axes["ultimate_outcome"] == "source_modification"
        else "Python source will be produced after you confirm these choices."
    )
    if request_execution_state == "explicit_affirmative":
        execution = "Execution remains held for separate authorization."
    elif request_execution_state == "negated":
        execution = "Execution was explicitly declined and is not authorized."
    elif request_execution_state == "deferred":
        execution = "Execution remains deferred and is not authorized for this step."
    elif request_execution_state == "contradictory_or_ambiguous":
        execution = "Execution is not authorized while the request remains unresolved."
    else:
        execution = "Execution was not requested and is not authorized."
    return [
        _qcoder_item("Generation authority", generation),
        _qcoder_item("Execution authority", execution),
        _qcoder_item(
            "Authority separation",
            "Confirming these choices does not authorize execution.",
        ),
        _qcoder_item(
            "Deferred execution choices",
            "Backend, shots, seed, and result handling remain deferred.",
        ),
    ]


def validate_connected_assistant_proposal(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate and normalize one assistant-authored semantic proposal."""

    if not isinstance(exact_request, str) or not exact_request or len(exact_request) > 20_000:
        raise ReviewBeforeGenerationError("review_exact_request_invalid")
    if not isinstance(proposal, Mapping):
        raise ReviewBeforeGenerationError("review_connected_assistant_proposal_required")
    expected = {
        "schema_id",
        "schema_version",
        "transaction_kind",
        "execution_request",
        "recommended_interpretation",
        "customer_constraints",
        "implementation_recommendations",
        "material_choices",
        "output_artifact",
        "deferred_choices",
        "limitations_nonclaims",
        "blocking_clarification",
    }
    _strict_keys(proposal, expected, "review_proposal_schema_invalid")
    if proposal.get("schema_id") != PROPOSAL_SCHEMA_ID or proposal.get("schema_version") != 2:
        raise ReviewBeforeGenerationError("review_proposal_contract_invalid")
    transaction_kind = str(proposal.get("transaction_kind") or "")
    execution_request = str(proposal.get("execution_request") or "")
    if transaction_kind not in TRANSACTION_KINDS or execution_request not in EXECUTION_REQUESTS:
        raise ReviewBeforeGenerationError("review_proposal_semantic_mode_invalid")
    axes = _semantic_axes(transaction_kind, execution_request)
    if transaction_kind == "review_before_source_modification" and not selected_artifact_identities:
        raise ReviewBeforeGenerationError(
            "review_source_modification_selection_required",
            clarification="Which exact source file should the proposed changes apply to?",
        )
    request_execution_state, generated_clarification = _validate_request_authority(
        exact_request, axes, execution_request
    )

    interpretation = _bounded_plain_text(
        proposal.get("recommended_interpretation"),
        category="review_proposal_interpretation_invalid",
        maximum=4_000,
    )
    if (
        interpretation.casefold() == exact_request.strip().casefold()
        or len(interpretation.split()) < 7
    ):
        raise ReviewBeforeGenerationError("review_proposal_goal_restatement_only")

    constraint_values = proposal.get("customer_constraints")
    if not isinstance(constraint_values, list) or len(constraint_values) > 16:
        raise ReviewBeforeGenerationError("review_proposal_customer_constraints_invalid")
    constraints: list[str] = []
    for value in constraint_values:
        excerpt = _bounded_plain_text(
            value, category="review_proposal_customer_constraint_invalid", maximum=500
        )
        if excerpt not in exact_request:
            raise ReviewBeforeGenerationError("review_proposal_customer_constraint_not_in_request")
        if not _customer_constraint_is_material(excerpt):
            raise ReviewBeforeGenerationError("review_proposal_customer_constraint_not_material")
        constraints.append(excerpt)
    if len(set(constraints)) != len(constraints):
        raise ReviewBeforeGenerationError("review_proposal_customer_constraint_duplicate")

    recommendation_values = proposal.get("implementation_recommendations")
    if (
        not isinstance(recommendation_values, list)
        or not recommendation_values
        or len(recommendation_values) > 24
    ):
        raise ReviewBeforeGenerationError("review_proposal_implementation_required")
    recommendations = [
        _bounded_plain_text(value, category="review_proposal_implementation_invalid")
        for value in recommendation_values
    ]
    if not any(_is_consequential(value) for value in recommendations):
        raise ReviewBeforeGenerationError("review_proposal_implementation_not_consequential")

    choices_value = proposal.get("material_choices")
    if not isinstance(choices_value, list) or not choices_value or len(choices_value) > 24:
        raise ReviewBeforeGenerationError("review_proposal_material_choices_required")
    choices: list[dict[str, str]] = []
    for value in choices_value:
        if not isinstance(value, Mapping):
            raise ReviewBeforeGenerationError("review_proposal_choice_invalid")
        _strict_keys(value, {"choice", "recommendation"}, "review_proposal_choice_invalid")
        choice = _bounded_plain_text(
            value.get("choice"), category="review_proposal_choice_invalid", maximum=160
        )
        recommendation = _bounded_plain_text(
            value.get("recommendation"), category="review_proposal_choice_invalid"
        )
        choices.append({"choice": choice, "recommendation": recommendation})
    if len({item["choice"].casefold() for item in choices}) != len(choices):
        raise ReviewBeforeGenerationError("review_proposal_choice_duplicate")

    output_artifact = _bounded_plain_text(
        proposal.get("output_artifact"), category="review_proposal_output_artifact_invalid"
    )
    if _assistant_values_contradict_authority([output_artifact], axes):
        raise ReviewBeforeGenerationError("review_proposal_authority_contradiction")
    if not re.search(
        r"\b(?:python|source|code|program|file|qasm|script|module)\b", output_artifact, re.I
    ):
        raise ReviewBeforeGenerationError("review_proposal_output_artifact_not_concrete")

    deferred_value = proposal.get("deferred_choices")
    limitations_value = proposal.get("limitations_nonclaims")
    if not isinstance(deferred_value, list) or len(deferred_value) > 24:
        raise ReviewBeforeGenerationError("review_proposal_deferred_choices_invalid")
    if (
        not isinstance(limitations_value, list)
        or not limitations_value
        or len(limitations_value) > 24
    ):
        raise ReviewBeforeGenerationError("review_proposal_limitations_required")
    deferred = [
        _bounded_plain_text(value, category="review_proposal_deferred_choice_invalid")
        for value in deferred_value
    ]
    limitations = [
        _bounded_plain_text(value, category="review_proposal_limitation_invalid")
        for value in limitations_value
    ]
    blocking = proposal.get("blocking_clarification")
    if blocking is not None:
        blocking = _bounded_plain_text(
            blocking, category="review_proposal_blocking_clarification_invalid", maximum=600
        )
    if generated_clarification is not None:
        blocking = generated_clarification

    untrusted_values = [
        interpretation,
        *constraints,
        *recommendations,
        *(item["choice"] for item in choices),
        *(item["recommendation"] for item in choices),
        output_artifact,
        *deferred,
        *limitations,
        *([blocking] if isinstance(blocking, str) else []),
    ]
    if _projection_contains_customer_action(untrusted_values):
        raise ReviewBeforeGenerationError("review_proposal_unsafe_projection_text")
    if _projection_contains_source_or_qasm(untrusted_values):
        raise ReviewBeforeGenerationError("review_proposal_source_or_qasm_rejected")
    if _assistant_values_contradict_authority(untrusted_values, axes):
        raise ReviewBeforeGenerationError("review_proposal_authority_contradiction")

    displayed_normalized: set[str] = set()

    def add_unique(items: list[dict[str, str]], item: dict[str, str]) -> None:
        normalized_value = _normalized_text(item["value"]).rstrip(".")
        if normalized_value not in displayed_normalized:
            displayed_normalized.add(normalized_value)
            items.append(item)

    goal_items: list[dict[str, str]] = []
    add_unique(goal_items, _assistant_item("Recommended interpretation", interpretation))
    for index, value in enumerate(constraints, start=1):
        add_unique(
            goal_items,
            {
                "label": f"Customer constraint {index}",
                "value": value,
                "attribution": CUSTOMER_ATTRIBUTION,
            },
        )
    for index, value in enumerate(limitations, start=1):
        add_unique(goal_items, _assistant_item(f"Limitation {index}", value))
    if isinstance(blocking, str):
        item = (
            _qcoder_item("Clarification needed", blocking)
            if generated_clarification is not None
            else _assistant_item("Clarification needed", blocking)
        )
        add_unique(goal_items, item)

    implementation_items: list[dict[str, str]] = []
    for index, value in enumerate(recommendations, start=1):
        add_unique(
            implementation_items,
            _assistant_item(f"Implementation recommendation {index}", value),
        )
    for item in choices:
        add_unique(
            implementation_items,
            _assistant_item(f"Material choice: {item['choice']}", item["recommendation"]),
        )
    add_unique(
        implementation_items,
        _qcoder_item("Dependency version", "No dependency version was selected silently."),
    )
    add_unique(
        implementation_items,
        _qcoder_item("Execution environment", "No execution environment was selected silently."),
    )

    output_items: list[dict[str, str]] = []
    add_unique(output_items, _assistant_item("Output artifact", output_artifact))
    for item in _authority_items(axes, request_execution_state):
        add_unique(output_items, item)
    for index, value in enumerate(deferred, start=1):
        if re.search(r"\b(?:backend|shots?|seed|result handling)\b", value, re.I):
            continue
        add_unique(output_items, _assistant_item(f"Deferred choice {index}", value))
    groups = [
        {"group_id": GROUPS[0][0], "label": GROUPS[0][1], "items": goal_items},
        {"group_id": GROUPS[1][0], "label": GROUPS[1][1], "items": implementation_items},
        {"group_id": GROUPS[2][0], "label": GROUPS[2][1], "items": output_items},
    ]
    normalized = {
        "schema_id": PROPOSAL_SCHEMA_ID,
        "schema_version": 2,
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "exact_request_utf8_sha256": request_digest(exact_request),
        "transaction_kind": transaction_kind,
        "execution_request": execution_request,
        "request_execution_state": request_execution_state,
        "semantic_axes": axes,
        "recommended_interpretation": interpretation,
        "customer_constraints": constraints,
        "implementation_recommendations": recommendations,
        "review_groups": groups,
        "material_choices": [
            {
                "label": item["choice"],
                "recommended_value": item["recommendation"],
                "attribution": CONNECTED_ASSISTANT_ATTRIBUTION,
            }
            for item in choices
        ],
        "output_artifact": output_artifact,
        "deferred_choices": [
            {
                "label": f"Deferred choice {index}",
                "deferred_value": value,
                "attribution": CONNECTED_ASSISTANT_ATTRIBUTION,
            }
            for index, value in enumerate(deferred, start=1)
        ],
        "limitations_nonclaims": [
            {"value": value, "attribution": CONNECTED_ASSISTANT_ATTRIBUTION}
            for value in limitations
        ],
        "blocking_clarification": blocking,
        "retention": "process_and_discard",
    }
    if _privacy_error(normalized):
        raise ReviewBeforeGenerationError("review_proposal_private_material_rejected")
    return normalized


def build_review_before_generation_semantics(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    validated = validate_connected_assistant_proposal(
        exact_request, proposal, selected_artifact_identities=selected_artifact_identities
    )
    result = {
        "schema_id": SEMANTICS_SCHEMA_ID,
        "schema_version": 1,
        "exact_request_utf8_sha256": request_digest(exact_request),
        "semantic_axes": deepcopy(validated["semantic_axes"]),
        "selected_artifact_identity_sha256": [
            sha256(value.encode("utf-8")).hexdigest()
            for value in sorted(selected_artifact_identities)
        ],
        "route": "binding_owned_review_before_generation",
        "operation": "begin_current_loop",
        "one_operation_before_useful_review": True,
        "source_generation_permitted_before_confirmation": False,
        "source_modification_permitted_before_confirmation": False,
        "execution_permitted": False,
        "execution_performed": False,
        "selected_file_review_inferred": False,
        "protected_service_required": False,
        "qcoder_authors_recommendations": False,
    }
    result["semantics_digest"] = _digest(result)
    return result


def review_revision(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> str:
    validated = validate_connected_assistant_proposal(
        exact_request, proposal, selected_artifact_identities=selected_artifact_identities
    )
    return "review-revision-" + _digest(
        {
            "exact_request": exact_request,
            "exact_request_utf8_sha256": request_digest(exact_request),
            "connected_assistant_proposal": validated,
            "selected_artifact_identity_sha256": [
                sha256(value.encode("utf-8")).hexdigest()
                for value in sorted(selected_artifact_identities)
            ],
            "privacy_safe_projection": True,
        }
    )


def _displayed_text_values(value: Mapping[str, Any], *, include_labels: bool = True) -> list[str]:
    values: list[str] = []
    for group in value.get("initial_decision_groups", ()):
        if not isinstance(group, Mapping):
            continue
        if include_labels:
            values.append(str(group.get("label") or ""))
        for item in group.get("items", ()):
            if not isinstance(item, Mapping):
                continue
            if include_labels:
                values.append(str(item.get("label") or ""))
            values.append(str(item.get("value") or ""))
    return values


_FIRST_VALUE_KEYS = {
    "proposal_attribution",
    "initial_decision_groups",
    "initial_decision_group_count",
    "initial_decision_group_maximum",
    "confirmable",
    "customer_actions",
    "one_qcoder_operation_before_useful_review",
    "source_or_qasm_included",
    "file_mutation_performed",
    "execution_permitted",
    "execution_performed",
    "protected_service_called",
    "qcoder_authored_recommendation",
    "retention",
}

_QCODER_ITEM_VALUES = {
    "Dependency version": {"No dependency version was selected silently."},
    "Execution environment": {"No execution environment was selected silently."},
    "Generation authority": {
        "Python source will be produced after you confirm these choices.",
        "Source modification will begin after you confirm these choices.",
    },
    "Execution authority": {
        "Execution was not requested and is not authorized.",
        "Execution was explicitly declined and is not authorized.",
        "Execution remains deferred and is not authorized for this step.",
        "Execution remains held for separate authorization.",
        "Execution is not authorized while the request remains unresolved.",
    },
    "Authority separation": {"Confirming these choices does not authorize execution."},
    "Deferred execution choices": {"Backend, shots, seed, and result handling remain deferred."},
    "Clarification needed": {
        "Should execution remain deferred, or be separately authorized after source generation?"
    },
}


def validate_first_value(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the customer projection and recompute its source/QASM invariant."""

    if not isinstance(value, Mapping):
        raise ReviewBeforeGenerationError("review_first_value_invalid")
    if set(value) != _FIRST_VALUE_KEYS:
        raise ReviewBeforeGenerationError("review_first_value_shape_invalid")
    forbidden = {
        "review_revision",
        "exact_request_utf8_sha256",
        "prior_result_token",
        "schema_id",
        "schema_version",
        "semantic_axes",
    }
    if set(value).intersection(forbidden):
        raise ReviewBeforeGenerationError("review_first_value_internal_metadata_exposed")
    groups = value.get("initial_decision_groups")
    if not isinstance(groups, list) or len(groups) != len(GROUPS):
        raise ReviewBeforeGenerationError("review_first_value_group_count_invalid")
    normalized_values: set[str] = set()
    untrusted_values: list[str] = []
    untrusted_item_values: list[str] = []
    for group, (_, expected_label) in zip(groups, GROUPS, strict=True):
        if not isinstance(group, Mapping) or set(group) != {"label", "items"}:
            raise ReviewBeforeGenerationError("review_first_value_group_shape_invalid")
        if group.get("label") != expected_label or not isinstance(group.get("items"), list):
            raise ReviewBeforeGenerationError("review_first_value_group_order_invalid")
        if not group["items"]:
            raise ReviewBeforeGenerationError("review_first_value_group_empty")
        labels: set[str] = set()
        for item in group["items"]:
            if not isinstance(item, Mapping) or set(item) != {"label", "value", "attribution"}:
                raise ReviewBeforeGenerationError("review_first_value_item_shape_invalid")
            label = item.get("label")
            item_value = item.get("value")
            attribution = item.get("attribution")
            if (
                not isinstance(label, str)
                or not label
                or not isinstance(item_value, str)
                or not item_value
                or attribution
                not in {CONNECTED_ASSISTANT_ATTRIBUTION, CUSTOMER_ATTRIBUTION, QCODER_ATTRIBUTION}
            ):
                raise ReviewBeforeGenerationError("review_first_value_item_invalid")
            if label in labels:
                raise ReviewBeforeGenerationError("review_first_value_item_label_duplicate")
            labels.add(label)
            normalized = _normalized_text(item_value).rstrip(".")
            if normalized in normalized_values:
                raise ReviewBeforeGenerationError("review_first_value_value_duplicate")
            normalized_values.add(normalized)
            if attribution == QCODER_ATTRIBUTION:
                if item_value not in _QCODER_ITEM_VALUES.get(label, set()):
                    raise ReviewBeforeGenerationError("review_first_value_qcoder_boundary_invalid")
            else:
                untrusted_values.extend((label, item_value))
                untrusted_item_values.append(item_value)
    displayed_values = _displayed_text_values(value)
    actual_source = _projection_contains_source_or_qasm(
        displayed_values
    ) or _projection_contains_source_or_qasm(_displayed_text_values(value, include_labels=False))
    if value.get("source_or_qasm_included") is not actual_source:
        raise ReviewBeforeGenerationError("review_first_value_source_invariant_mismatch")
    if actual_source:
        raise ReviewBeforeGenerationError("review_first_value_source_or_qasm_present")
    if _projection_contains_customer_action(
        untrusted_values
    ) or _projection_contains_customer_action(untrusted_item_values):
        raise ReviewBeforeGenerationError("review_first_value_untrusted_action_present")
    serialized_display = " ".join(displayed_values).casefold()
    if any(
        fragment in serialized_display
        for fragment in (
            "stored displayed review",
            "review-result-",
            "review-revision-",
            "exact_request_utf8_sha256",
        )
    ):
        raise ReviewBeforeGenerationError("review_first_value_internal_metadata_exposed")
    if value.get("initial_decision_group_count") != 3:
        raise ReviewBeforeGenerationError("review_first_value_group_count_invalid")
    if value.get("initial_decision_group_maximum") != 3:
        raise ReviewBeforeGenerationError("review_first_value_group_count_invalid")
    confirmable = value.get("confirmable")
    if type(confirmable) is not bool:
        raise ReviewBeforeGenerationError("review_first_value_confirmable_invalid")
    if value.get("customer_actions") != (list(CUSTOMER_ACTIONS) if confirmable else []):
        raise ReviewBeforeGenerationError("review_first_value_actions_invalid")
    if value.get("proposal_attribution") != PROPOSAL_ATTRIBUTION:
        raise ReviewBeforeGenerationError("review_first_value_attribution_invalid")
    if not any(
        item["attribution"] == CONNECTED_ASSISTANT_ATTRIBUTION and _is_consequential(item["value"])
        for item in groups[1]["items"]
    ):
        raise ReviewBeforeGenerationError("review_first_value_implementation_not_substantive")
    if not any(item["label"] == "Output artifact" for item in groups[2]["items"]):
        raise ReviewBeforeGenerationError("review_first_value_output_artifact_missing")
    for key, expected in (
        ("one_qcoder_operation_before_useful_review", True),
        ("file_mutation_performed", False),
        ("execution_permitted", False),
        ("execution_performed", False),
        ("protected_service_called", False),
        ("qcoder_authored_recommendation", False),
    ):
        if value.get(key) is not expected:
            raise ReviewBeforeGenerationError("review_first_value_boundary_invalid")
    if value.get("retention") != "current_loop_only_process_and_discard":
        raise ReviewBeforeGenerationError("review_first_value_retention_invalid")
    if _privacy_error(value):
        raise ReviewBeforeGenerationError("review_first_value_private_material_rejected")
    return deepcopy(dict(value))


def build_first_value(
    exact_request: str,
    proposal: Mapping[str, Any],
    *,
    selected_artifact_identities: Sequence[str] = (),
) -> dict[str, Any]:
    validated = validate_connected_assistant_proposal(
        exact_request, proposal, selected_artifact_identities=selected_artifact_identities
    )
    confirmable = validated["blocking_clarification"] is None
    displayed_groups = deepcopy(validated["review_groups"])
    for group in displayed_groups:
        group.pop("group_id", None)
    displayed_values = [str(item["value"]) for group in displayed_groups for item in group["items"]]
    result = {
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "initial_decision_groups": displayed_groups,
        "initial_decision_group_count": 3,
        "initial_decision_group_maximum": 3,
        "confirmable": confirmable,
        "customer_actions": list(CUSTOMER_ACTIONS) if confirmable else [],
        "one_qcoder_operation_before_useful_review": True,
        "source_or_qasm_included": _projection_contains_source_or_qasm(displayed_values),
        "file_mutation_performed": False,
        "execution_permitted": False,
        "execution_performed": False,
        "protected_service_called": False,
        "qcoder_authored_recommendation": False,
        "retention": "current_loop_only_process_and_discard",
    }
    return validate_first_value(result)


def render_first_value_markdown(value: Mapping[str, Any]) -> str:
    validated = validate_first_value(value)
    lines: list[str] = []
    for group in validated["initial_decision_groups"]:
        lines.extend([f"## {group['label']}", ""])
        for item in group["items"]:
            lines.append(
                f"- **{_markdown_escape(item['label'])}:** {_markdown_escape(item['value'])}"
            )
        lines.append("")
    if validated["customer_actions"]:
        lines.extend(f"- {action}" for action in validated["customer_actions"])
        lines.append("")
    return "\n".join(lines)


def contract_snapshot() -> dict[str, Any]:
    return {
        "schema_id": CONTRACT_SCHEMA_ID,
        "schema_version": 2,
        "proposal_schema_id": PROPOSAL_SCHEMA_ID,
        "semantics_schema_id": SEMANTICS_SCHEMA_ID,
        "first_value_schema_id": FIRST_VALUE_SCHEMA_ID,
        "transaction_schema_id": TRANSACTION_SCHEMA_ID,
        "proposal_attribution": PROPOSAL_ATTRIBUTION,
        "transaction_kinds": list(TRANSACTION_KINDS),
        "execution_requests": list(EXECUTION_REQUESTS),
        "initial_groups": [label for _, label in GROUPS],
        "customer_actions": list(CUSTOMER_ACTIONS),
        "request_digest_computed_by_qcoder": True,
        "customer_projection_excludes_revision_and_token": True,
        "customer_projection_group_count": 3,
        "customer_projection_source_free_revalidated": True,
        "token_only_action_call_strict": True,
        "execution_request_bound_to_exact_unquoted_request": True,
        "model_facing_confirmation_internal_mechanics": False,
        "one_operation_before_useful_review": True,
        "backward_compatible_optional_begin_input": True,
        "protected_service_required": False,
        "qcoder_authors_recommendations": False,
        "process_and_discard": True,
        "new_public_tool": False,
        "new_private_operation": False,
    }


def proposal_input_schema() -> dict[str, Any]:
    """Return the valid-by-construction v2 proposal schema."""

    plain_text = {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000,
        "description": (
            "One bounded plain-text value. Do not include Markdown, source code, QASM, customer "
            "action labels, qCoder boundary text, schema mechanics, or multiline content."
        ),
    }
    return {
        "type": "object",
        "description": (
            "Use only when the exact customer request asks to review proposed generation or "
            "modification choices before source is created. Supply concrete connected-assistant "
            "recommendations; qCoder supplies groups, labels, attribution, authority, revision, "
            "and actions."
        ),
        "properties": {
            "schema_id": {"const": PROPOSAL_SCHEMA_ID},
            "schema_version": {"const": 2},
            "transaction_kind": {
                "type": "string",
                "enum": list(TRANSACTION_KINDS),
                "description": (
                    "Select review before new source generation or review before changes to an "
                    "explicitly selected source artifact."
                ),
            },
            "execution_request": {
                "type": "string",
                "enum": list(EXECUTION_REQUESTS),
                "description": (
                    "Use not_requested unless execution was explicitly requested; even then it "
                    "remains held for separate authorization."
                ),
            },
            "recommended_interpretation": {
                **plain_text,
                "maxLength": 4000,
                "description": (
                    "Concrete reading of the customer's goal and scope. Do not include source, "
                    "QASM, Markdown, or an action label."
                ),
            },
            "customer_constraints": {
                "type": "array",
                "minItems": 0,
                "maxItems": 16,
                "uniqueItems": True,
                "items": {
                    **plain_text,
                    "maxLength": 500,
                    "description": "Exact nonempty excerpt copied from request_text.",
                },
                "description": (
                    "Optional exact material excerpts from unchanged request_text; use an empty "
                    "list instead of manufacturing a customer fact."
                ),
            },
            "implementation_recommendations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": plain_text,
                "description": (
                    "Concrete framework, construction, representation, mapping, operation, or "
                    "output-structure recommendations. Plain prose only; no source or QASM."
                ),
            },
            "material_choices": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": {
                    "type": "object",
                    "properties": {"choice": plain_text, "recommendation": plain_text},
                    "required": ["choice", "recommendation"],
                    "additionalProperties": False,
                },
                "description": "Ordinary-language material choices and concrete recommendations.",
            },
            "output_artifact": {
                **plain_text,
                "description": "Concrete source artifact form proposed after confirmation.",
            },
            "deferred_choices": {
                "type": "array",
                "maxItems": 24,
                "items": plain_text,
                "description": (
                    "Material choices deliberately deferred. Defer execution-only choices when "
                    "execution was not requested."
                ),
            },
            "limitations_nonclaims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": plain_text,
                "description": "Truthful limitations and nonclaims; no qCoder boundary attribution.",
            },
            "blocking_clarification": {
                "type": ["string", "null"],
                "maxLength": 600,
                "description": (
                    "One genuinely material unresolved question, or null when the concrete "
                    "recommendation is confirmable."
                ),
            },
        },
        "required": [
            "schema_id",
            "schema_version",
            "transaction_kind",
            "execution_request",
            "recommended_interpretation",
            "customer_constraints",
            "implementation_recommendations",
            "material_choices",
            "output_artifact",
            "deferred_choices",
            "limitations_nonclaims",
            "blocking_clarification",
        ],
        "additionalProperties": False,
    }


__all__ = [
    "CONTRACT_SCHEMA_ID",
    "CUSTOMER_ACTIONS",
    "FIRST_VALUE_SCHEMA_ID",
    "PROPOSAL_SCHEMA_ID",
    "ReviewBeforeGenerationError",
    "SEMANTICS_SCHEMA_ID",
    "TRANSACTION_SCHEMA_ID",
    "build_first_value",
    "build_review_before_generation_semantics",
    "canonical_json",
    "contract_snapshot",
    "proposal_input_schema",
    "render_first_value_markdown",
    "request_digest",
    "review_revision",
    "validate_connected_assistant_proposal",
    "validate_first_value",
]
