"""Deterministic local foundations for Explorer Algorithm Blueprint artifacts."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from qcoder.development_evidence import (
    IMPLEMENTATION_DECISION_SUMMARY_CONTRACT,
    IMPLEMENTATION_DECISION_SUMMARY_VERSION,
    SOURCE_EVIDENCE_DEPTH_DISABLED,
    SOURCE_EVIDENCE_DEPTH_GATE,
    development_evidence_contract_snapshot,
    extract_qiskit_source_development_evidence,
)
from qcoder.blueprint_decisions import profile_decision_catalog_snapshot


SCHEMA_VERSION = 1
_DECISION_LOOP_COMMON_INPUT_FIELDS = {
    "decision_loop",
    "profile_decision_catalog_version",
    "current_lineage_reference",
    "decision_dispositions",
    "decision_references",
    "blueprint_decision_records",
    "resolution_phase",
    "resolution_context",
    "selected_action",
    "selected_decision_references",
    "source_finding_references",
    "proposed_updates",
    "proposal_ref",
    "prospective_derived_artifact_references",
    "decision_resolution_pack",
    "resolution_confirmation",
    "confirmation_payload",
    "resolution_parent_artifact",
}
_CONTEXT_LOOP_COMMON_INPUT_FIELDS = {
    "context_loop",
    "generation_posture",
    "request_baseline",
    "request_share_safe_summary",
    "request_text_share_safe",
    "assistant_interpretation",
    "profile_suggestions",
    "exploratory_authorization",
    "exploratory_constraints",
    "exploratory_prohibitions",
    "unresolved_assistant_choices",
    "stage_availability",
    "stage_identities",
    "working_blueprint",
    "generation_context",
    "python_manifestation",
    "circuit_manifestation",
    "result_manifestation",
    "decision_evidence_lineage",
    "current_build_context",
    "carry_forward_proposal",
    "evolved_blueprint",
    "decision_records",
    "evidence_parent_artifacts",
    "artifact_references",
    "missing_stage_requests",
    "remaining_uncertainty",
    "generation_context_effect",
}
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
            *_DECISION_LOOP_COMMON_INPUT_FIELDS,
            *(_CONTEXT_LOOP_COMMON_INPUT_FIELDS - {"context_loop"}),
        }
    ),
    "create_implementation_blueprint": frozenset(
        {
            "artifact_kind",
            "client_context",
            "algorithm_intent_card",
            "intent_relationship",
            *_DECISION_LOOP_COMMON_INPUT_FIELDS,
            *_CONTEXT_LOOP_COMMON_INPUT_FIELDS,
        }
    ),
    "create_generation_context_pack": frozenset(
        {
            "artifact_kind",
            "client_context",
            "implementation_blueprint",
            "output_evidence_contract",
            *_DECISION_LOOP_COMMON_INPUT_FIELDS,
            *_CONTEXT_LOOP_COMMON_INPUT_FIELDS,
        }
    ),
    "create_source_blueprint_alignment_review": frozenset(
        {
            "artifact_kind",
            "client_context",
            "implementation_blueprint",
            "output_evidence_contract",
            "selected_python_source_evidence",
            *_DECISION_LOOP_COMMON_INPUT_FIELDS,
            *_CONTEXT_LOOP_COMMON_INPUT_FIELDS,
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
    from qcoder.context_loop import context_loop_contract_snapshot

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
        "development_evidence": development_evidence_contract_snapshot(),
        "profile_decision_catalog": profile_decision_catalog_snapshot(),
        "context_loop": context_loop_contract_snapshot(),
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
    development_evidence_context: dict[str, Any] | None = None,
    source_evidence_depth: str | None = None,
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
    if source_evidence_depth not in {
        None,
        SOURCE_EVIDENCE_DEPTH_DISABLED,
        SOURCE_EVIDENCE_DEPTH_GATE,
    }:
        artifact["source_evidence_depth"] = {
            "gate": str(source_evidence_depth)[:64],
            "status": "unsupported_profile",
            "child_contract": IMPLEMENTATION_DECISION_SUMMARY_CONTRACT,
            "child_version": IMPLEMENTATION_DECISION_SUMMARY_VERSION,
            "diagnostics": ["The requested source-evidence depth is not supported."],
        }
    elif (
        source_evidence_depth == SOURCE_EVIDENCE_DEPTH_GATE and development_evidence_context is None
    ):
        artifact["source_evidence_depth"] = {
            "gate": SOURCE_EVIDENCE_DEPTH_GATE,
            "status": "unavailable",
            "child_contract": IMPLEMENTATION_DECISION_SUMMARY_CONTRACT,
            "child_version": IMPLEMENTATION_DECISION_SUMMARY_VERSION,
            "diagnostics": [
                "A confirmed blueprint context is required for blueprint-relative depth findings."
            ],
        }
    if development_evidence_context is not None:
        if not isinstance(development_evidence_context, dict):
            raise ValueError("development_evidence_context_must_be_object")
        development_evidence = extract_qiskit_source_development_evidence(
            selected_text,
            logical_source_label=logical_source_label.strip(),
            source_evidence_depth=source_evidence_depth,
            **development_evidence_context,
        )
        artifact["development_evidence"] = development_evidence
        depth = development_evidence.get("source_evidence_depth")
        if isinstance(depth, dict):
            artifact["source_evidence_depth"] = {
                key: deepcopy(depth[key])
                for key in (
                    "gate",
                    "status",
                    "child_contract",
                    "child_version",
                    "diagnostics",
                )
                if key in depth
            }
    return with_artifact_digest(artifact)


def compact_selected_python_source_evidence_for_hosted(
    artifact: dict[str, Any],
) -> dict[str, Any]:
    """Project opted-in local depth evidence to the bounded hosted contract."""

    supplied = deepcopy(artifact)
    depth_status = supplied.get("source_evidence_depth")
    development = supplied.get("development_evidence")
    if not (
        isinstance(depth_status, dict)
        and depth_status.get("status") == "available"
        and isinstance(development, dict)
    ):
        return supplied
    depth = development.get("source_evidence_depth")
    summary = development.get("implementation_decision_summary")
    if not isinstance(depth, dict) or not isinstance(summary, dict):
        return supplied
    already_compact = depth.get("local_detail_omitted_from_hosted_projection") is True

    if already_compact:
        compact_motifs = [
            {
                key: deepcopy(item[key])
                for key in (
                    "motif_id",
                    "observation_status",
                    "bounded_line_references",
                    "evidence_confidence",
                    "choice_origin",
                    "inspection_scope_reference",
                )
                if key in item
            }
            for item in depth.get("motif_observation_inventory") or []
            if isinstance(item, dict)
        ]
    else:
        compact_motifs = [
            {
                "motif_id": item.get("motif_id"),
                "observation_status": item.get("observation_status"),
                "bounded_line_references": [
                    reference.get("line")
                    for reference in item.get("bounded_evidence_references") or []
                    if isinstance(reference, dict) and isinstance(reference.get("line"), int)
                ][:20],
                "evidence_confidence": item.get("evidence_confidence"),
                "choice_origin": item.get("choice_origin"),
                "inspection_scope_reference": "source_evidence_depth.inspection_scope",
            }
            for item in development.get("motif_observations") or []
            if isinstance(item, dict)
        ]
    profile_prefix = {
        "grover_search": "grover.",
        "qaoa": "qaoa.",
        "generic_qiskit": "qiskit.",
    }.get(str(depth.get("profile_id")), "")
    if profile_prefix:
        compact_motifs = [
            item
            for item in compact_motifs
            if str(item.get("motif_id", "")).startswith(profile_prefix)
        ]
    negative_source = (
        depth.get("negative_alignment_inventory")
        if already_compact
        else development.get("alignment_findings")
    )
    compact_negative_findings = [
        {
            key: deepcopy(item[key])
            for key in (
                "expected_item",
                "alignment_status",
                "evidence_confidence",
                "choice_origin",
                "bounded_observation",
                "inspection_scope_reference",
                "detector_identifier",
                "supported_detector_inventory_reference",
                "what_was_not_found",
                "what_remains_unproven",
                "required_next_evidence",
            )
            if key in item
        }
        for item in negative_source or []
        if isinstance(item, dict)
        and item.get("alignment_status")
        in {"not_observed", "ambiguous", "requires_next_stage_evidence", "conflicting"}
    ]
    source_negative_source = (
        depth.get("negative_source_inventory")
        if already_compact
        else depth.get("source_negative_findings")
    )
    compact_source_negatives = [
        {
            key: deepcopy(item[key])
            for key in (
                "negative_id",
                "decision_family",
                "detector_id",
                "alignment_status",
                "evidence_confidence",
                "choice_origin",
                "bounded_observation",
                "inspection_scope_reference",
                "what_was_not_found",
                "what_remains_unproven",
                "required_later_evidence",
                "suggested_user_controlled_action",
            )
            if key in item
        }
        for item in source_negative_source or []
        if isinstance(item, dict)
    ]
    configuration_source = (
        depth.get("source_configuration_facts") if already_compact else depth.get("source_facts")
    )
    compact_configuration = [
        {
            "decision_family": item.get("decision_family"),
            "detector_id": item.get("detector_id"),
            "bounded_line_references": deepcopy(
                item.get("bounded_line_references")
                if already_compact
                else (item.get("source_evidence_basis") or {}).get("bounded_line_references") or []
            ),
            **(
                {"safe_scalar_fact": deepcopy(item["safe_scalar_fact"])}
                if item.get("safe_scalar_fact") is not None
                else {}
            ),
            **(
                {"structural_fact": deepcopy(item["structural_fact"])}
                if item.get("structural_fact") is not None
                else {}
            ),
            "classification": deepcopy(item.get("classification"))
            if already_compact
            else {
                "alignment_status": item.get("alignment_status"),
                "choice_origin": item.get("choice_origin"),
                "evidence_confidence": item.get("evidence_confidence"),
            },
        }
        for item in configuration_source or []
        if isinstance(item, dict)
        and (
            already_compact
            or item.get("safe_scalar_fact") is not None
            or item.get("structural_fact") is not None
            or item.get("decision_family")
            in {
                "source_visible_execution_call_shape",
                "source_visible_parameter_binding",
                "source_visible_measurement",
                "source_declared_quantum_width",
                "source_declared_classical_width",
                "statically_established_repetition",
            }
        )
    ][:2]
    hosted_depth = {
        key: deepcopy(depth[key])
        for key in (
            "gate",
            "status",
            "child_contract",
            "child_version",
            "analysis_unit",
            "detector_inventory",
            "resource_limits",
            "inspection_scope",
            "raw_source_included",
            "raw_path_included",
            "imports_followed",
            "source_imported",
            "source_executed",
            "network_accessed",
            "later_stage_analysis_performed",
            "profile_id",
            "parser_status",
            "non_causal_introduced_after_blueprint",
            "negative_finding_scope",
            "non_proofs",
        )
        if key in depth
    }
    construction_observation = depth.get(
        "qiskit_construction_form_observation"
    )
    if isinstance(construction_observation, dict):
        hosted_depth["qiskit_construction_form_observation"] = {
            "construction_form_observation": construction_observation[
                "construction_form_observation"
            ],
            "boundary": "bounded_static_ast_no_execution_no_equivalence",
        }
    hosted_depth["source_configuration_facts"] = compact_configuration
    hosted_depth["ambiguity_inventory"] = []
    hosted_depth["motif_observation_inventory"] = compact_motifs
    hosted_depth["negative_alignment_inventory"] = compact_negative_findings
    hosted_depth["negative_source_inventory"] = compact_source_negatives
    hosted_depth["local_detail_omitted_from_hosted_projection"] = True

    compact_summary = {
        key: deepcopy(summary[key])
        for key in (
            "section_type",
            "schema_version",
            "child_contract",
            "independent_artifact",
            "discoverable_capability",
            "current_session_only",
            "persistent",
            "actions_executed",
            "ordering_basis",
        )
        if key in summary
    }
    compact_summary["decision_non_proof_reference"] = "source_evidence_depth.non_proofs[0]"
    compact_summary["default_required_later_evidence"] = "logical_circuit"
    compact_summary["groups"] = []
    for group in summary.get("groups") or []:
        compact_items = []
        for item in group.get("items") or []:
            compact_item = {
                key: deepcopy(item[key])
                for key in (
                    "decision_id",
                    "apparent_implementation_choice",
                    "decision_family",
                    "blueprint_requirement_reference",
                    "relationship_to_confirmed_blueprint",
                    "choice_origin",
                    "evidence_confidence",
                    "alignment_status",
                    "bounded_source_evidence_basis",
                    "related_motif_evidence",
                    "why_the_choice_matters",
                    "profile_supported_alternatives",
                    "included_decision_families",
                    "included_ambiguity_families",
                    "ordering_key",
                    "action",
                    "actions",
                    "bounded_source_evidence_basis_reference",
                    "ordered_decisions",
                    "ordered_by",
                    "why_the_choices_matter",
                )
                if key in item
            }
            alternatives = compact_item.get("profile_supported_alternatives") or []
            if alternatives:
                compact_item["profile_supported_alternatives"] = [
                    {
                        key: deepcopy(alternative[key])
                        for key in (
                            "name",
                            "decision_family",
                            "provenance",
                            "requirement_addressed",
                            "blueprint_clarification_required",
                            "non_preference",
                        )
                        if key in alternative
                    }
                    for alternative in alternatives
                ]
            basis = compact_item.get("bounded_source_evidence_basis") or {}
            if not basis.get("bounded_line_references"):
                compact_item.pop("bounded_source_evidence_basis", None)
                compact_item["bounded_source_evidence_basis_reference"] = (
                    "source_evidence_depth.inspection_scope"
                )
            compact_items.append(compact_item)
        group_id = group.get("group_id")
        if group_id == "suggested_next_actions":
            action_items = list(group.get("items") or [])
            first_action = action_items[0] if action_items else {}
            if already_compact:
                compact_items = [
                    {
                        **{
                            key: deepcopy(first_action[key])
                            for key in (
                                "decision_id",
                                "choice_origin",
                                "evidence_confidence",
                                "alignment_status",
                            )
                            if key in first_action
                        },
                        "actions": [
                            {
                                key: deepcopy(action[key])
                                for key in ("action", "decision_references")
                                if key in action
                            }
                            for action in first_action.get("actions") or []
                            if isinstance(action, dict)
                        ],
                    }
                ]
            else:
                compact_items = [
                    {
                        "decision_id": "group.suggested_next_actions",
                        "actions": [
                            {
                                "action": (item.get("action") or {}).get("action"),
                                "decision_references": deepcopy(
                                    (item.get("action") or {}).get("decision_or_ambiguity") or []
                                ),
                            }
                            for item in action_items
                        ],
                        "choice_origin": first_action.get("choice_origin", "unknown"),
                        "evidence_confidence": first_action.get(
                            "evidence_confidence", "Suggested next check"
                        ),
                        "alignment_status": first_action.get("alignment_status", "not_applicable"),
                    }
                ]
            compact_summary["suggested_action_semantics"] = {
                "intended_update": "next_human_intent_or_confirmed_blueprint",
                "could_establish": "explicit_requirement_choice_or_evidence_request",
                "still_not_proven_reference": "source_evidence_depth.non_proofs[0]",
                "executed": False,
            }
        elif (
            group_id
            in {
                "blueprint_confirmed_choices",
                "choices_introduced_after_blueprint",
                "ambiguous_or_dynamic_behavior",
            }
            and len(compact_items) > 1
        ):
            first = compact_items[0]
            compact_items = [
                {
                    "decision_id": f"group.{group_id}",
                    "ordered_decisions": [
                        {
                            "decision_id": item.get("decision_id"),
                            "choice": item.get("apparent_implementation_choice"),
                            "family": item.get("decision_family"),
                            "motif_id": item.get("related_motif_evidence"),
                        }
                        for item in compact_items
                    ],
                    "relationship_to_confirmed_blueprint": first.get(
                        "relationship_to_confirmed_blueprint"
                    ),
                    "choice_origin": first.get("choice_origin"),
                    "evidence_confidence": first.get("evidence_confidence"),
                    "alignment_status": first.get("alignment_status"),
                    "bounded_source_evidence_basis_reference": (
                        "source_evidence_depth.inspection_scope"
                    ),
                    "related_motif_evidence": [
                        item.get("related_motif_evidence")
                        for item in compact_items
                        if item.get("related_motif_evidence")
                    ],
                    "why_the_choices_matter": "maintained_motif_or_analysis_metadata",
                    "profile_supported_alternatives": [
                        alternative
                        for item in compact_items
                        for alternative in item.get("profile_supported_alternatives") or []
                    ],
                    "ordered_by": "source_summary_ordering_basis",
                    "included_ambiguity_families": sorted(
                        {
                            family
                            for item in compact_items
                            for family in item.get("included_ambiguity_families") or []
                        }
                    ),
                }
            ]
        compact_summary["groups"].append(
            {
                "group_id": group_id,
                "order": group.get("order"),
                "items": compact_items,
            }
        )

    hosted_development = {
        key: deepcopy(development[key])
        for key in (
            "schema_id",
            "schema_version",
            "artifact_kind",
            "development_stage",
            "framework",
            "framework_version_facts",
            "current_session_scope",
            "artifact_reference",
            "related_artifact_references",
            "relationships",
            "retention_state",
            "non_proofs",
            "working_transition",
            "later_stage_analysis_performed",
        )
        if key in development
    }
    hosted_development["framework_version_facts"] = [
        {
            **{key: deepcopy(value) for key, value in fact.items() if key != "non_proof"},
            **(
                {"non_proof_reference": "development_evidence.non_proofs[0]"}
                if "non_proof" in fact
                else {}
            ),
        }
        for fact in development.get("framework_version_facts") or []
        if isinstance(fact, dict)
    ]
    hosted_development["motif_expectations"] = [
        {
            **{key: deepcopy(value) for key, value in item.items() if key != "non_proof"},
            "non_proof_reference": "development_evidence.non_proofs[0]",
        }
        for item in development.get("motif_expectations") or []
        if isinstance(item, dict)
    ]
    hosted_development["motif_observations"] = []
    hosted_development["alignment_findings"] = []
    hosted_development["implementation_decision_summary"] = compact_summary
    hosted_development["source_evidence_depth"] = hosted_depth

    projected = {
        key: deepcopy(supplied[key])
        for key in (
            "artifact_type",
            "schema_version",
            "logical_source_label",
            "origin",
            "evidence_scope",
            "evidence_coverage",
            "parse_status",
            "profile_motif_observations",
            "ambiguities",
            "extraction_limitations",
            "raw_source_included",
            "repository_scanned",
            "source_executed",
            "source_edited",
            "retention",
            "source_evidence_depth",
        )
        if key in supplied
    }
    projected["profile_motif_observations"] = [
        {key: deepcopy(item[key]) for key in ("motif", "status", "evidence_label") if key in item}
        for item in supplied.get("profile_motif_observations") or []
        if isinstance(item, dict)
    ]
    projected["extraction_limitations"] = [
        "Static selected-source evidence; imports and dynamic behavior remain unresolved."
    ]
    if not projected.get("ambiguities"):
        projected.pop("ambiguities", None)
    projected["development_evidence"] = hosted_development
    return with_artifact_digest(projected)


def extract_selected_python_file_evidence(
    source_file: str | Path,
    *,
    logical_source_label: str | None = None,
    selected_symbol: str | None = None,
    line_span: tuple[int, int] | None = None,
    development_evidence_context: dict[str, Any] | None = None,
    source_evidence_depth: str | None = None,
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
        development_evidence_context=development_evidence_context,
        source_evidence_depth=source_evidence_depth,
    )
