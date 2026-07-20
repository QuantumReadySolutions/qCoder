"""Deterministic local foundations for Explorer Algorithm Blueprint artifacts."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
ALGORITHM_BLUEPRINT_TOOL_NAMES = (
    "create_algorithm_intent_card",
    "create_implementation_blueprint",
    "create_generation_context_pack",
    "create_source_blueprint_alignment_review",
)
ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS = {
    "create_algorithm_intent_card": frozenset(
        {
            "artifact_kind",
            "client_context",
            "original_user_intent",
            "profile_id",
            "proposed_interpretation",
            "requirements",
            "constraints",
            "non_goals",
            "field_provenance",
            "revision_notes",
            "requested_confirmation_state",
            "confirmation_assertion",
            "accepted_unresolved_choices",
        }
    ),
    "create_implementation_blueprint": frozenset(
        {
            "artifact_kind",
            "client_context",
            "algorithm_intent_card",
            "intent_relationship",
        }
    ),
    "create_generation_context_pack": frozenset(
        {
            "artifact_kind",
            "client_context",
            "implementation_blueprint",
            "output_evidence_contract",
        }
    ),
    "create_source_blueprint_alignment_review": frozenset(
        {
            "artifact_kind",
            "client_context",
            "implementation_blueprint",
            "output_evidence_contract",
            "selected_python_source_evidence",
        }
    ),
}
ALGORITHM_BLUEPRINT_TOOL_REQUIRED_FIELDS = {
    "create_algorithm_intent_card": ("original_user_intent", "profile_id"),
    "create_implementation_blueprint": ("algorithm_intent_card", "intent_relationship"),
    "create_generation_context_pack": (
        "implementation_blueprint",
        "output_evidence_contract",
    ),
    "create_source_blueprint_alignment_review": (
        "implementation_blueprint",
        "output_evidence_contract",
        "selected_python_source_evidence",
    ),
}
ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS = {
    "create_algorithm_intent_card": {
        "field": "artifact_type",
        "value": "algorithm_intent_card",
    },
    "create_implementation_blueprint": {
        "field": "artifact_type",
        "value": "implementation_blueprint",
        "additional_artifact": "output_evidence_contract",
    },
    "create_generation_context_pack": {
        "field": "artifact_type",
        "value": "generation_context_pack",
    },
    "create_source_blueprint_alignment_review": {
        "field": "artifact_type",
        "value": "source_blueprint_alignment_review",
    },
}
CONFIRMATION_STATES = ("proposed", "needs_clarification", "confirmed")
PROFILE_IDS = ("generic_qiskit", "grover_search", "qaoa")
ORIGIN_VALUES = (
    "user",
    "connected_assistant",
    "algorithm_profile",
    "blueprint",
    "local_source_evidence",
    "explicitly_supplied_source_excerpt",
    "deterministic_qcoder_validation",
)
EVIDENCE_CONFIDENCE_LABELS = (
    ("observed", "Observed"),
    ("user_provided", "User-provided"),
    ("inferred", "Inferred"),
    ("assumed", "Assumed"),
    ("not_proven", "Not proven"),
    ("suggested_next_check", "Suggested next check"),
)
ARTIFACT_TYPES = {
    "algorithm_intent_card": "algorithm_intent_card",
    "implementation_blueprint": "implementation_blueprint",
    "output_evidence_contract": "output_evidence_contract",
    "generation_context_pack": "generation_context_pack",
    "selected_python_source_evidence": "selected_python_source_evidence",
    "source_blueprint_alignment_review": "source_blueprint_alignment_review",
}
RELATIONSHIP_TYPES = (
    "implemented_by",
    "expected_to_construct",
    "represented_by",
    "transformed_to",
    "executed_with",
    "produces",
    "interpreted_by",
)
EVIDENCE_COVERAGE_VALUES = ("complete", "partial", "ambiguous")

_COMMON_BOUNDARIES = (
    "current artifact and current session only",
    "all required artifacts must be explicitly supplied; no hidden lookup",
    "process-and-discard with no retained artifacts",
    "read-only; no repository scan, source execution, source editing, or autonomous work",
    "no correctness, completeness, executability, algorithm-identity, runtime, fidelity, backend-ranking, or quantum-advantage claim",
)


PROFILE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "generic_qiskit": {
        "display_name": "Generic Qiskit Blueprint",
        "required_fields": (
            "normalized_goal",
            "problem_size_meaning",
            "framework_requirement",
            "measurement_plan",
            "execution_intent",
            "desired_output",
        ),
        "questions": {
            "normalized_goal": "What implementation goal should the generated Python satisfy?",
            "problem_size_meaning": "What does problem size mean for this request?",
            "framework_requirement": "Which Qiskit and Python compatibility constraints apply?",
            "measurement_plan": "What should be measured and how should bits be interpreted?",
            "execution_intent": "Is the intended downstream use simulation, hardware, or construction only?",
            "desired_output": "What result form and classical post-processing are expected?",
        },
        "motifs": (
            "circuit_construction",
            "parameter_use",
            "measurement",
            "result_processing",
        ),
    },
    "grover_search": {
        "display_name": "Grover Search",
        "required_fields": (
            "normalized_goal",
            "problem_size_meaning",
            "framework_requirement",
            "search_space_meaning",
            "marked_state_meaning",
            "oracle_choice",
            "iteration_assumption",
            "ancilla_policy",
            "measurement_plan",
            "bit_order_expectation",
            "desired_output",
        ),
        "questions": {
            "search_space_meaning": "What states form the search space?",
            "marked_state_meaning": "What makes a state marked?",
            "oracle_choice": "Will the implementation use a phase oracle or a bit-flip oracle?",
            "iteration_assumption": "How is the amplification iteration count chosen?",
            "ancilla_policy": "What ancilla use is allowed or required?",
            "measurement_plan": "Which qubits are measured?",
            "bit_order_expectation": "How should measured bits be decoded?",
        },
        "motifs": (
            "oracle_structure",
            "diffusion_or_amplification",
            "controlled_operations",
            "iteration_structure",
            "measurement",
            "result_processing",
        ),
    },
    "qaoa": {
        "display_name": "QAOA",
        "required_fields": (
            "normalized_goal",
            "problem_size_meaning",
            "framework_requirement",
            "optimization_problem",
            "objective",
            "cost_encoding",
            "mixer_choice",
            "repetitions",
            "parameter_strategy",
            "initialization_strategy",
            "optimizer_boundary",
            "backend_intent",
            "shots",
            "measurement_plan",
            "bit_order_expectation",
            "result_post_processing",
            "desired_output",
        ),
        "questions": {
            "optimization_problem": "What optimization problem is being represented?",
            "objective": "What objective should be evaluated?",
            "cost_encoding": "How is the objective encoded into the cost operator or layer?",
            "mixer_choice": "Which mixer should be used?",
            "repetitions": "What QAOA depth or repetition count is intended?",
            "parameter_strategy": "How are parameters represented and updated?",
            "initialization_strategy": "How are initial parameters supplied?",
            "optimizer_boundary": "Which classical optimizer responsibilities remain outside the circuit builder?",
            "backend_intent": "What simulator or hardware intent applies?",
            "shots": "What shot policy, if any, is user-selected?",
            "measurement_plan": "What measurement data is required?",
            "bit_order_expectation": "How should measured bits be decoded?",
            "result_post_processing": "How should samples and objective values be interpreted?",
        },
        "motifs": (
            "cost_layer",
            "mixer_layer",
            "parameter_use",
            "repetition_structure",
            "measurement",
            "result_processing",
        ),
    },
}


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
    """Return a deterministic stateless SHA-256 reference for one supplied artifact."""

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


def profile_definition(profile_id: str) -> dict[str, Any]:
    if profile_id not in PROFILE_DEFINITIONS:
        raise ValueError("unsupported_algorithm_profile")
    return deepcopy(PROFILE_DEFINITIONS[profile_id])


def algorithm_blueprint_contract_snapshot() -> dict[str, Any]:
    return {
        "tool_names": list(ALGORITHM_BLUEPRINT_TOOL_NAMES),
        "confirmation_states": list(CONFIRMATION_STATES),
        "profile_ids": list(PROFILE_IDS),
        "profiles": {
            profile_id: {
                "display_name": definition["display_name"],
                "required_fields": list(definition["required_fields"]),
                "question_fields": list(definition["questions"]),
                "motifs": list(definition["motifs"]),
            }
            for profile_id, definition in PROFILE_DEFINITIONS.items()
        },
        "origin_values": list(ORIGIN_VALUES),
        "confidence_labels": [
            {"value": value, "display": display} for value, display in EVIDENCE_CONFIDENCE_LABELS
        ],
        "artifact_types": dict(sorted(ARTIFACT_TYPES.items())),
        "schema_version": SCHEMA_VERSION,
        "relationship_types": list(RELATIONSHIP_TYPES),
        "evidence_coverage": list(EVIDENCE_COVERAGE_VALUES),
        "digest": "sha256_canonical_json_without_artifact_digest_stateless_reference_only",
        "digest_test_vector": canonical_artifact_digest(
            {"artifact_type": "parity_fixture", "schema_version": 1, "value": [2, 1]}
        ),
        "scope": "current_artifact_current_session_explicit_supply_only",
        "retention": "process_and_discard",
        "boundaries": list(_COMMON_BOUNDARIES),
        "tool_input_fields": {
            name: sorted(ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS[name])
            for name in ALGORITHM_BLUEPRINT_TOOL_NAMES
        },
        "required_request_properties": {
            name: list(ALGORITHM_BLUEPRINT_TOOL_REQUIRED_FIELDS[name])
            for name in ALGORITHM_BLUEPRINT_TOOL_NAMES
        },
        "artifact_discriminators": ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS,
        "hosted_path_fields": [],
        "raw_source_fields": [],
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _constant_int(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


class _StaticPythonVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: list[dict[str, str | None]] = []
        self.calls: list[dict[str, Any]] = []
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.parameters: list[dict[str, Any]] = []
        self.circuit_declarations: list[dict[str, Any]] = []
        self.measurements: list[dict[str, Any]] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for item in node.names:
            self.imports.append({"module": item.name, "alias": item.asname})

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        for item in node.names:
            self.imports.append(
                {"module": f"{module}.{item.name}".strip("."), "alias": item.asname}
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.functions.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.functions.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.classes.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = _call_name(node.func)
        record = {"name": name, "line": node.lineno}
        self.calls.append(record)
        terminal = name.rsplit(".", 1)[-1]
        if terminal in {"Parameter", "ParameterVector"}:
            self.parameters.append(record)
        if terminal in {"QuantumCircuit", "QuantumRegister", "ClassicalRegister"}:
            declaration = dict(record)
            declaration["declared_sizes"] = [
                size for size in (_constant_int(arg) for arg in node.args[:2]) if size is not None
            ]
            self.circuit_declarations.append(declaration)
        if terminal in {"measure", "measure_all"}:
            self.measurements.append(record)
        self.generic_visit(node)


def _unique_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for record in records:
        key = json.dumps(record, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return result


def _motif_observations(visitor: _StaticPythonVisitor) -> list[dict[str, Any]]:
    call_names = [str(item["name"]).lower() for item in visitor.calls]
    symbol_names = [str(item["name"]).lower() for item in visitor.functions + visitor.classes]
    names = call_names + symbol_names
    observations: list[dict[str, Any]] = []

    def add(motif: str, matches: list[str]) -> None:
        if matches:
            observations.append(
                {
                    "motif": motif,
                    "status": "observed_in_supplied_static_source_evidence",
                    "matched_symbols": sorted(set(matches))[:12],
                    "evidence_label": "Observed",
                }
            )

    add("circuit_construction", [name for name in call_names if name.endswith("quantumcircuit")])
    add(
        "parameter_use",
        [name for name in call_names if name.endswith(("parameter", "parametervector"))],
    )
    add("measurement", [name for name in call_names if name.endswith(("measure", "measure_all"))])
    add("oracle_structure", [name for name in names if "oracle" in name])
    add(
        "diffusion_or_amplification",
        [name for name in names if any(term in name for term in ("diffus", "amplif"))],
    )
    add(
        "controlled_operations",
        [
            name
            for name in call_names
            if name.rsplit(".", 1)[-1] in {"cx", "cz", "ccx", "mcx", "mcp"}
        ],
    )
    add("cost_layer", [name for name in names if "cost" in name or "objective" in name])
    add("mixer_layer", [name for name in names if "mixer" in name])
    add(
        "result_processing",
        [
            name
            for name in names
            if any(term in name for term in ("counts", "decode", "result", "objective"))
        ],
    )
    return observations


def extract_selected_python_source_evidence(
    source_text: str,
    *,
    logical_source_label: str,
    safe_basename: str | None = None,
    selected_symbol: str | None = None,
    line_span: tuple[int, int] | None = None,
    origin: str = "explicitly_supplied_source_excerpt",
) -> dict[str, Any]:
    """Extract compact static evidence without importing or executing supplied Python."""

    if origin not in {"local_source_evidence", "explicitly_supplied_source_excerpt"}:
        raise ValueError("unsupported_source_evidence_origin")
    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError("source_text_missing")
    if len(source_text) > 100_000:
        raise ValueError("source_text_too_large")
    if not logical_source_label.strip() or len(logical_source_label) > 120:
        raise ValueError("invalid_logical_source_label")
    if line_span is not None:
        start, end = line_span
        lines = source_text.splitlines()
        if start < 1 or end < start or end > len(lines) or end - start + 1 > 2_000:
            raise ValueError("invalid_source_line_span")
        selected_text = "\n".join(lines[start - 1 : end])
        coverage = "partial"
    else:
        selected_text = source_text
        coverage = "partial" if selected_symbol else "complete"

    visitor = _StaticPythonVisitor()
    parse_status = "parsed"
    ambiguities: list[str] = []
    try:
        tree = ast.parse(selected_text, mode="exec")
    except (SyntaxError, ValueError):
        parse_status = "parse_failed"
        coverage = "ambiguous"
        ambiguities.append("The selected Python evidence could not be parsed statically.")
    else:
        if line_span is not None and line_span[0] > 1:
            ast.increment_lineno(tree, line_span[0] - 1)
        if selected_symbol:
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    visitor.visit(node)
            selected_nodes = [
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == selected_symbol
            ]
            if not selected_nodes:
                coverage = "ambiguous"
                ambiguities.append(
                    "The requested symbol was not observed in the selected evidence."
                )
            else:
                visitor.visit(selected_nodes[0])
        else:
            visitor.visit(tree)
        if any(not item.get("declared_sizes") for item in visitor.circuit_declarations):
            ambiguities.append(
                "One or more circuit or register sizes are not static integer literals."
            )

    imports = _unique_records(visitor.imports)
    framework = (
        "qiskit"
        if any(str(item["module"]).split(".")[0] == "qiskit" for item in imports)
        else "not_observed"
    )
    artifact = {
        "artifact_type": ARTIFACT_TYPES["selected_python_source_evidence"],
        "schema_version": SCHEMA_VERSION,
        "logical_source_label": logical_source_label.strip(),
        "safe_basename": Path(safe_basename).name if safe_basename else None,
        "selected_symbol": selected_symbol,
        "bounded_line_span": list(line_span) if line_span else None,
        "origin": origin,
        "evidence_scope": "explicitly_selected_python_source_only",
        "evidence_coverage": coverage,
        "parse_status": parse_status,
        "framework_observation": framework,
        "imports_and_aliases": imports,
        "circuit_construction_symbols": _unique_records(visitor.circuit_declarations),
        "parameter_declarations": _unique_records(visitor.parameters),
        "measurement_calls": _unique_records(visitor.measurements),
        "functions": _unique_records(visitor.functions),
        "classes": _unique_records(visitor.classes),
        "profile_motif_observations": _motif_observations(visitor),
        "source_references": sorted(
            {int(item["line"]) for item in visitor.calls + visitor.functions + visitor.classes}
        )[:100],
        "ambiguities": ambiguities,
        "extraction_limitations": [
            "Static syntax observations do not prove constructed-circuit or runtime behavior.",
            "Imports were recorded by name only and were not imported or followed.",
            "Dynamic values and generated circuit structure may not be statically observable.",
        ],
        "raw_source_included": False,
        "repository_scanned": False,
        "source_executed": False,
        "source_edited": False,
        "retention": "process_and_discard",
    }
    return with_artifact_digest(artifact)


def extract_selected_python_file_evidence(
    source_file: str | Path,
    *,
    logical_source_label: str | None = None,
    selected_symbol: str | None = None,
    line_span: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Read exactly one explicitly selected file and return compact local evidence."""

    path = Path(source_file)
    if not path.is_file():
        raise ValueError("selected_source_file_missing")
    if path.suffix.lower() != ".py":
        raise ValueError("selected_source_file_must_be_python")
    try:
        source_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("selected_source_file_unreadable") from exc
    return extract_selected_python_source_evidence(
        source_text,
        logical_source_label=(logical_source_label or path.name),
        safe_basename=path.name,
        selected_symbol=selected_symbol,
        line_span=line_span,
        origin="local_source_evidence",
    )
