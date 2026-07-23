"""Bounded Qiskit selected-source depth implementation.

This module implements syntax-directed inspection only. Contract ownership remains
in :mod:`qcoder.development_evidence` and this implementation is invoked only by
that canonical authority when the explicit ``depth_v1`` gate is selected.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from qcoder.development_evidence import (
    INTRODUCED_AFTER_BLUEPRINT_NON_CAUSAL as _NON_CAUSAL_INTRODUCED,
    SOURCE_EVIDENCE_DEPTH_NEGATIVE_SCOPE as _NEGATIVE_SCOPE,
    STATIC_SOURCE_NON_PROOF as _STATIC_NON_PROOF,
)

_INSPECTION_METHOD = "bounded_qiskit_ast_depth_v1"

_QISKIT_CONSTRUCTORS = {"QuantumCircuit", "QuantumRegister", "ClassicalRegister"}
_PARAMETER_CONSTRUCTORS = {"Parameter", "ParameterVector"}
_MEASUREMENT_CALLS = {"measure", "measure_all"}
_CONTROLLED_CALLS = {"cx", "cz", "ccx", "mcx", "mcp", "cp", "crx", "cry", "crz"}
_BINDING_CALLS = {"assign_parameters", "bind_parameters"}
_BIT_ORDER_CALLS = {"reverse_bits", "reverse", "reversed"}
_EXECUTION_CALLS = {
    "transpile",
    "run",
    "execute",
    "generate_preset_pass_manager",
    "sampler",
    "estimator",
    "backendsampler",
    "backendestimator",
}
_RESULT_CALLS = {
    "result",
    "get_counts",
    "get_memory",
    "quasi_dists",
    "binary_probabilities",
    "data",
    "join_data",
    "sort",
    "sorted",
    "normalize",
}
_ALLOWED_CONFIG_KEYWORDS = {
    "shots": "bounded_shot_count",
    "seed": "seed_value",
    "seed_simulator": "seed_value",
    "seed_transpiler": "seed_value",
    "optimization_level": "optimization_level",
    "reps": "bounded_repetition_count",
}
_UNSUPPORTED_CONTROL_NODES = (ast.While, ast.Try, ast.Match) + (
    (getattr(ast, "TryStar"),) if hasattr(ast, "TryStar") else ()
)
_SDK_CONSTRUCTION_OBSERVATION_SCHEMA_ID = (
    "qcoder.qiskit_construction_form_observation.v1"
)
_QISKIT_CONSTRUCTION_OBSERVATIONS = (
    "direct_quantum_circuit",
    "explicit_named_registers",
    "ambiguous",
    "not_observed",
)


@dataclass(frozen=True)
class _SafeScalar:
    value: int | float | bool
    value_type: str
    expression_depth: int


def _raw_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _raw_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _terminal(node: ast.AST) -> str:
    return _raw_name(node).rsplit(".", 1)[-1]


def _safe_symbol(value: str) -> str:
    return value[:120] if value and len(value) <= 120 else "bounded_symbol"


def _safe_scalar(
    node: ast.AST,
    constants: Mapping[str, _SafeScalar],
    *,
    maximum_depth: int,
    maximum_absolute_value: int,
    depth: int = 0,
) -> _SafeScalar | None:
    if depth > maximum_depth:
        return None
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return _SafeScalar(value, "boolean", depth)
        if isinstance(value, int) and abs(value) <= maximum_absolute_value:
            return _SafeScalar(value, "integer", depth)
        if (
            isinstance(value, float)
            and math.isfinite(value)
            and abs(value) <= maximum_absolute_value
        ):
            return _SafeScalar(value, "finite_float", depth)
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        item = _safe_scalar(
            node.operand,
            constants,
            maximum_depth=maximum_depth,
            maximum_absolute_value=maximum_absolute_value,
            depth=depth + 1,
        )
        if item is None or isinstance(item.value, bool):
            return None
        value = +item.value if isinstance(node.op, ast.UAdd) else -item.value
        if abs(value) > maximum_absolute_value:
            return None
        return _SafeScalar(value, item.value_type, max(depth, item.expression_depth))
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)
    ):
        left = _safe_scalar(
            node.left,
            constants,
            maximum_depth=maximum_depth,
            maximum_absolute_value=maximum_absolute_value,
            depth=depth + 1,
        )
        right = _safe_scalar(
            node.right,
            constants,
            maximum_depth=maximum_depth,
            maximum_absolute_value=maximum_absolute_value,
            depth=depth + 1,
        )
        if (
            left is None
            or right is None
            or isinstance(left.value, bool)
            or isinstance(right.value, bool)
        ):
            return None
        try:
            if isinstance(node.op, ast.Add):
                value = left.value + right.value
            elif isinstance(node.op, ast.Sub):
                value = left.value - right.value
            elif isinstance(node.op, ast.Mult):
                value = left.value * right.value
            elif isinstance(node.op, ast.FloorDiv):
                if right.value == 0:
                    return None
                value = left.value // right.value
            else:
                if right.value == 0:
                    return None
                value = left.value % right.value
        except (ArithmeticError, TypeError, ValueError):
            return None
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None
        if abs(value) > maximum_absolute_value:
            return None
        value_type = "integer" if isinstance(value, int) else "finite_float"
        return _SafeScalar(value, value_type, max(left.expression_depth, right.expression_depth))
    return None


def _qiskit_import_bindings(
    tree: ast.Module,
) -> tuple[set[str], dict[str, str]]:
    module_aliases: set[str] = set()
    constructor_aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "qiskit":
                    module_aliases.add(alias.asname or "qiskit")
        elif isinstance(node, ast.ImportFrom) and (
            node.module == "qiskit"
            or isinstance(node.module, str)
            and node.module.startswith("qiskit.")
        ):
            for alias in node.names:
                if alias.name in _QISKIT_CONSTRUCTORS:
                    constructor_aliases[alias.asname or alias.name] = alias.name
    return module_aliases, constructor_aliases


def _qiskit_constructor_name(
    node: ast.AST,
    *,
    module_aliases: set[str],
    constructor_aliases: Mapping[str, str],
) -> str | None:
    if isinstance(node, ast.Name):
        return constructor_aliases.get(node.id)
    if (
        isinstance(node, ast.Attribute)
        and node.attr in _QISKIT_CONSTRUCTORS
        and isinstance(node.value, ast.Name)
        and node.value.id in module_aliases
    ):
        return node.attr
    return None


def _bounded_integer_bindings(tree: ast.Module) -> dict[str, int]:
    bindings: dict[str, int] = {}
    invalid: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and not isinstance(value.value, bool)
                and 0 <= value.value <= 1_000_000
                and target.id not in bindings
            ):
                bindings[target.id] = value.value
            else:
                invalid.add(target.id)
    return {
        name: value for name, value in bindings.items() if name not in invalid
    }


def _is_bounded_width_expression(
    node: ast.AST, integer_bindings: Mapping[str, int]
) -> bool:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return 0 <= node.value <= 1_000_000
    return isinstance(node, ast.Name) and node.id in integer_bindings


def _qiskit_construction_form_observation(
    tree: ast.Module, *, source_reference: Mapping[str, Any]
) -> dict[str, Any]:
    module_aliases, constructor_aliases = _qiskit_import_bindings(tree)
    integer_bindings = _bounded_integer_bindings(tree)
    register_symbols: dict[str, str] = {}
    circuit_calls: list[ast.Call] = []
    unresolved_constructor_like_call = False

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        constructor = _qiskit_constructor_name(
            value.func,
            module_aliases=module_aliases,
            constructor_aliases=constructor_aliases,
        )
        if constructor in {"QuantumRegister", "ClassicalRegister"}:
            for target in targets:
                if isinstance(target, ast.Name):
                    register_symbols[target.id] = constructor

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        constructor = _qiskit_constructor_name(
            node.func,
            module_aliases=module_aliases,
            constructor_aliases=constructor_aliases,
        )
        if constructor == "QuantumCircuit":
            circuit_calls.append(node)
        elif _terminal(node.func) == "QuantumCircuit":
            unresolved_constructor_like_call = True

    observed_forms: set[str] = set()
    ambiguous = unresolved_constructor_like_call
    for call in circuit_calls:
        positional = list(call.args)
        direct = (
            len(positional) in {1, 2}
            and all(
                _is_bounded_width_expression(item, integer_bindings)
                for item in positional
            )
            and all(keyword.arg in {"name"} for keyword in call.keywords)
        )
        explicit = (
            bool(positional)
            and all(
                isinstance(item, ast.Name) and item.id in register_symbols
                for item in positional
            )
            and any(
                isinstance(item, ast.Name)
                and register_symbols.get(item.id) == "QuantumRegister"
                for item in positional
            )
            and not call.keywords
        )
        if direct:
            observed_forms.add("direct_quantum_circuit")
        elif explicit:
            observed_forms.add("explicit_named_registers")
        else:
            ambiguous = True

    if ambiguous or len(observed_forms) > 1:
        observation = "ambiguous"
    elif observed_forms:
        observation = next(iter(observed_forms))
    else:
        observation = "not_observed"
    if observation not in _QISKIT_CONSTRUCTION_OBSERVATIONS:
        raise RuntimeError("qiskit_construction_observation_invalid")
    return {
        "schema_id": _SDK_CONSTRUCTION_OBSERVATION_SCHEMA_ID,
        "schema_version": 1,
        "sdk": "qiskit",
        "construction_form_observation": observation,
        "bounded_inspection_method": _INSPECTION_METHOD,
        "source_evidence_reference": deepcopy(dict(source_reference)),
        "observed_quantum_circuit_constructor_calls": len(circuit_calls),
        "imports_followed": False,
        "source_executed": False,
        "raw_source_included": False,
        "effective_circuit_structure_proven": False,
        "source_to_circuit_equivalence_proven": False,
        "non_proof": (
            "The bounded AST observation identifies only a safely established "
            "Qiskit constructor form; it does not prove effective circuit "
            "structure, correctness, or source-to-circuit lineage."
        ),
    }


def observe_qiskit_construction_form(
    source_text: str, *, source_reference: Mapping[str, Any]
) -> dict[str, Any]:
    """Observe one local Qiskit constructor form without importing or executing source."""

    try:
        tree = ast.parse(source_text, mode="exec")
    except (SyntaxError, ValueError):
        return {
            "schema_id": _SDK_CONSTRUCTION_OBSERVATION_SCHEMA_ID,
            "schema_version": 1,
            "sdk": "qiskit",
            "construction_form_observation": "ambiguous",
            "bounded_inspection_method": _INSPECTION_METHOD,
            "source_evidence_reference": deepcopy(dict(source_reference)),
            "observed_quantum_circuit_constructor_calls": 0,
            "imports_followed": False,
            "source_executed": False,
            "raw_source_included": False,
            "effective_circuit_structure_proven": False,
            "source_to_circuit_equivalence_proven": False,
            "non_proof": "The source did not parse; no constructor form was established.",
        }
    return _qiskit_construction_form_observation(
        tree, source_reference=source_reference
    )


def _collection_shape(node: ast.AST, maximum_length: int) -> dict[str, Any] | None:
    values: Sequence[ast.AST] | None = None
    category = ""
    if isinstance(node, ast.List):
        category, values = "list", node.elts
    elif isinstance(node, ast.Tuple):
        category, values = "tuple", node.elts
    elif isinstance(node, ast.Set):
        category, values = "set", node.elts
    elif isinstance(node, ast.Dict):
        category, values = "mapping", node.keys
    if values is None or len(values) > maximum_length:
        return None
    return {
        "value_disclosure": "withheld",
        "structural_category": category,
        "bounded_length": len(values),
        "collection_contents_included": False,
    }


def _source_basis(
    _source_reference: Mapping[str, Any],
    _logical_source_label: str,
    detector_id: str,
    lines: Sequence[int],
) -> dict[str, Any]:
    return {
        "inspection_scope_reference": "source_evidence_depth.inspection_scope",
        "detector_id": detector_id,
        "bounded_line_references": sorted(set(int(line) for line in lines if line > 0))[:20],
        "source_visible_only": True,
    }


def _alternative_records(
    motif_registry: Mapping[str, Mapping[str, Any]], motif_id: str
) -> list[dict[str, Any]]:
    motif = motif_registry.get(motif_id) or {}
    return [
        {
            "name": str(name),
            "decision_family": str(
                (motif.get("related_implementation_decisions") or [motif_id])[0]
            ),
            "provenance": "maintained_profile_metadata",
            "relevance": motif_id,
            "requirement_addressed": motif_id,
            "unresolved_facts": ["suitability"],
            "blueprint_clarification_required": True,
            "non_preference": "No alternative is ranked or preferred.",
        }
        for name in motif.get("profile_supported_alternatives") or []
    ]


def _action(name: str, decision: str, evidence: str) -> dict[str, Any]:
    return {
        "action": name,
        "decision_or_ambiguity": decision,
        "supporting_evidence": evidence,
        "intended_update": "next_human_intent_or_confirmed_blueprint",
        "could_establish": "explicit_requirement_choice_or_evidence_request",
        "still_not_proven_reference": "source_evidence_depth.non_proofs[0]",
        "executed": False,
    }


class _DepthAnalyzer:
    def __init__(
        self,
        tree: ast.Module,
        *,
        logical_source_label: str,
        source_reference: Mapping[str, Any],
        resource_limits: Mapping[str, int],
        detector_inventory: Sequence[str],
    ) -> None:
        self.tree = tree
        self.logical_source_label = logical_source_label
        self.source_reference = source_reference
        self.limits = resource_limits
        self.detectors = tuple(detector_inventory)
        self.aliases: dict[str, str] = {}
        self.imported_names: set[str] = set()
        self.constants: dict[str, _SafeScalar] = {}
        self.parameter_symbols: set[str] = set()
        self.module_parameter_symbols: set[str] = self.parameter_symbols
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.facts: list[dict[str, Any]] = []
        self.ambiguities: list[dict[str, Any]] = []
        self.call_records: list[dict[str, Any]] = []
        self.helper_records: list[dict[str, Any]] = []
        self._fact_counter = 0

    def resolve(self, node: ast.AST) -> str:
        raw = _raw_name(node)
        first, separator, rest = raw.partition(".")
        canonical = self.aliases.get(first, first)
        return f"{canonical}.{rest}" if separator else canonical

    def fact(
        self,
        detector_id: str,
        decision_family: str,
        observation: str,
        *,
        line: int,
        safe_value: _SafeScalar | None = None,
        structure: Mapping[str, Any] | None = None,
        symbol: str | None = None,
        alignment_status: str = "not_applicable",
        choice_origin: str = "explicit_in_source",
        evidence_confidence: str = "Observed",
        required_later_evidence: str = "logical_circuit",
    ) -> None:
        self._fact_counter += 1
        record: dict[str, Any] = {
            "finding_id": f"{detector_id}.{self._fact_counter:03d}",
            "detector_id": detector_id,
            "decision_family": decision_family,
            "bounded_observation": observation,
            "alignment_status": alignment_status,
            "choice_origin": choice_origin,
            "evidence_confidence": evidence_confidence,
            "source_evidence_basis": _source_basis(
                self.source_reference, self.logical_source_label, detector_id, [line]
            ),
            "required_later_evidence": required_later_evidence,
            "non_proof_reference": "source_evidence_depth.non_proofs[0]",
        }
        if safe_value is not None:
            record["safe_scalar_fact"] = {
                "value": safe_value.value,
                "value_type": safe_value.value_type,
                "source_visible_not_effective": True,
                "range_checked": True,
            }
        if structure is not None:
            record["structural_fact"] = deepcopy(dict(structure))
        if symbol:
            record["safe_symbol_reference"] = _safe_symbol(symbol)
        self.facts.append(record)

    def ambiguous(self, detector_id: str, category: str, line: int, explanation: str) -> None:
        self.ambiguities.append(
            {
                "detector_id": detector_id,
                "category": category,
                "alignment_status": "ambiguous",
                "choice_origin": "unknown",
                "evidence_confidence": "Not proven",
                "bounded_observation": explanation,
                "source_evidence_basis": _source_basis(
                    self.source_reference, self.logical_source_label, detector_id, [line]
                ),
                "required_later_evidence": "logical_circuit",
                "non_proof_reference": "source_evidence_depth.non_proofs[0]",
            }
        )

    def collect_definitions(self) -> None:
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                for item in node.names:
                    local = item.asname or item.name.split(".")[0]
                    self.aliases[local] = item.name
                    self.imported_names.add(local)
                    if item.name.split(".")[0] == "qiskit":
                        self.fact(
                            "qiskit.imports.v1",
                            "framework_import",
                            "A Qiskit import declaration is visible in the selected source.",
                            line=node.lineno,
                            symbol=item.name,
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for item in node.names:
                    local = item.asname or item.name
                    canonical = f"{module}.{item.name}".strip(".")
                    self.aliases[local] = canonical
                    self.imported_names.add(local)
                    if module.split(".")[0] == "qiskit":
                        self.fact(
                            "qiskit.imports.v1",
                            "framework_import",
                            "A Qiskit API import declaration is visible in the selected source.",
                            line=node.lineno,
                            symbol=canonical,
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node

    def _collect_assignment(
        self,
        node: ast.Assign | ast.AnnAssign,
        constants: dict[str, _SafeScalar],
    ) -> None:
        target = (
            node.target
            if isinstance(node, ast.AnnAssign)
            else (node.targets[0] if node.targets else None)
        )
        value = node.value
        if not isinstance(target, ast.Name) or value is None:
            return
        if isinstance(value, ast.Call):
            terminal = self.resolve(value.func).rsplit(".", 1)[-1]
            if terminal in _PARAMETER_CONSTRUCTORS:
                self.parameter_symbols.add(target.id)
            if terminal == "QuantumRegister" and "ancilla" in target.id.lower():
                self.fact(
                    "qiskit.register.width.v1",
                    "explicit_ancilla_construction",
                    "An explicitly named ancilla register construction is visible; its circuit role remains unproven.",
                    line=node.lineno,
                    symbol=target.id,
                )
        safe = _safe_scalar(
            value,
            constants,
            maximum_depth=self.limits["maximum_constant_expression_depth"],
            maximum_absolute_value=self.limits["maximum_safe_scalar_absolute_value"],
        )
        if safe is not None:
            constants[target.id] = safe
            self.fact(
                "python.safe.constant.v1",
                "safe_local_constant",
                "A bounded safe scalar alias is visible; its value is withheld unless consumed by an allowlisted product fact.",
                line=node.lineno,
                structure={
                    "value_disclosure": "withheld",
                    "structural_category": "safe_scalar_alias",
                    "scalar_type": safe.value_type,
                    "collection_contents_included": False,
                },
                symbol=target.id,
            )
            return
        shape = _collection_shape(value, self.limits["maximum_safe_collection_length"])
        if shape is not None:
            normalized_name = target.id.lower()
            decision_family = (
                "qaoa_problem_structure"
                if any(term in normalized_name for term in ("problem", "graph", "edge"))
                else "withheld_collection_structure"
            )
            self.fact(
                "python.safe.constant.v1",
                decision_family,
                "A collection is visible; only its safe structural category and bounded length are reported.",
                line=node.lineno,
                structure=shape,
                symbol=target.id,
            )
            return
        if isinstance(value, ast.Constant) and isinstance(value.value, (str, bytes)):
            normalized_name = target.id.lower()
            decision_family = (
                "grover_marked_state_structure"
                if any(term in normalized_name for term in ("marked", "target_state"))
                else "withheld_literal"
            )
            self.fact(
                "python.safe.constant.v1",
                decision_family,
                "A literal is visible but its value is not allowlisted for disclosure.",
                line=node.lineno,
                structure={
                    "value_disclosure": "withheld",
                    "structural_category": "string" if isinstance(value.value, str) else "bytes",
                    "bounded_length": min(
                        len(value.value), self.limits["maximum_safe_collection_length"]
                    ),
                    "collection_contents_included": False,
                },
                symbol=target.id,
            )

    def inspect(self) -> None:
        self.collect_definitions()
        if sum(1 for _ in ast.walk(self.tree)) > self.limits["maximum_ast_nodes"]:
            raise ValueError("source_evidence_depth_ast_limit_exceeded")
        module_constants: dict[str, _SafeScalar] = {}
        self.constants = module_constants
        module_parameter_symbols: set[str] = set()
        self.parameter_symbols = module_parameter_symbols
        self.module_parameter_symbols = module_parameter_symbols
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(node, ast.ClassDef):
                self.ambiguous(
                    "qiskit.helper.expansion.v1",
                    "unsupported_class_body",
                    node.lineno,
                    "Class bodies are outside the bounded same-file helper expansion contract.",
                )
                continue
            self._inspect_node(
                node,
                constants=module_constants,
                helper_depth=-1,
                helper_path=(),
            )
        self.constants = dict(module_constants)
        self.module_parameter_symbols = set(module_parameter_symbols)
        for name, function in sorted(self.functions.items()):
            if self._contains_qiskit_constructor(function):
                self._inspect_helper(
                    name,
                    depth=0,
                    path=(),
                    module_constants=module_constants,
                )
        self.facts = self.facts[: self.limits["maximum_findings"]]
        self.ambiguities = self.ambiguities[: self.limits["maximum_findings"]]

    def _contains_qiskit_constructor(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> bool:
        stack = list(reversed(function.body))
        while stack:
            node = stack.pop()
            if isinstance(node, ast.Call) and (
                self.resolve(node.func).rsplit(".", 1)[-1] in _QISKIT_CONSTRUCTORS
            ):
                return True
            stack.extend(
                reversed(
                    [
                        child
                        for child in ast.iter_child_nodes(node)
                        if not isinstance(
                            child,
                            (
                                ast.FunctionDef,
                                ast.AsyncFunctionDef,
                                ast.ClassDef,
                                ast.Lambda,
                            ),
                        )
                    ]
                )
            )
        return False

    def _inspect_helper(
        self,
        name: str,
        *,
        depth: int,
        path: tuple[str, ...],
        module_constants: Mapping[str, _SafeScalar],
    ) -> None:
        function = self.functions[name]
        if name in path:
            self.ambiguous(
                "qiskit.helper.expansion.v1",
                "recursive_helper",
                function.lineno,
                "A recursive or cyclic same-file helper path was detected and not expanded.",
            )
            return
        if depth > self.limits["same_file_helper_expansion_depth"]:
            self.ambiguous(
                "qiskit.helper.expansion.v1",
                "helper_depth_limit",
                function.lineno,
                "A same-file helper reference exceeds the fixed expansion depth of two.",
            )
            return
        self.helper_records.append(
            {
                "helper": _safe_symbol(name),
                "line": function.lineno,
                "expansion_depth": depth,
                "inspection_method": _INSPECTION_METHOD,
                "body_visits_on_path": 1,
            }
        )
        self.fact(
            "qiskit.helper.expansion.v1",
            "bounded_same_file_helper",
            "A same-file helper body was inspected within the fixed expansion ceiling.",
            line=function.lineno,
            safe_value=_SafeScalar(depth, "integer", 0),
            symbol=name,
        )
        constants = dict(module_constants)
        previous_parameter_symbols = self.parameter_symbols
        self.parameter_symbols = set(self.module_parameter_symbols)
        try:
            for statement in function.body:
                self._inspect_node(
                    statement,
                    constants=constants,
                    helper_depth=depth,
                    helper_path=(*path, name),
                )
        finally:
            self.parameter_symbols = previous_parameter_symbols

    def _inspect_node(
        self,
        node: ast.AST,
        *,
        constants: dict[str, _SafeScalar],
        helper_depth: int,
        helper_path: tuple[str, ...],
    ) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            self._collect_assignment(node, constants)
        if isinstance(node, ast.If):
            selected = self._inspect_branch(node, constants)
            if selected is None:
                return
            for statement in node.body if selected else node.orelse:
                self._inspect_node(
                    statement,
                    constants=constants,
                    helper_depth=helper_depth,
                    helper_path=helper_path,
                )
            return
        if isinstance(node, ast.For):
            count = self._inspect_loop(node, constants)
            if count is None:
                return
            if count > 0:
                for statement in node.body:
                    self._inspect_node(
                        statement,
                        constants=constants,
                        helper_depth=helper_depth,
                        helper_path=helper_path,
                    )
            if node.orelse:
                self.ambiguous(
                    "python.loop.repetition.v1",
                    "unsupported_loop_else",
                    node.lineno,
                    "Loop-else behavior is not expanded by the bounded source analyzer.",
                )
            return
        if isinstance(node, _UNSUPPORTED_CONTROL_NODES):
            self.ambiguous(
                "qiskit.helper.expansion.v1",
                "unsupported_control_flow",
                int(getattr(node, "lineno", 0)),
                "This control-flow form is outside the bounded syntax-directed expansion contract.",
            )
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            self.ambiguous(
                "python.safe.constant.v1",
                "unsupported_expression",
                node.lineno,
                "Comprehensions and generators are not evaluated or expanded.",
            )
            return
        if isinstance(node, ast.Assert):
            self.fact(
                "qiskit.result.processing.v1",
                "source_visible_expected_output_assertion",
                "A source-visible assertion is present; no runtime result or assertion outcome was inspected.",
                line=node.lineno,
                required_later_evidence="run_results",
            )
        if isinstance(node, ast.Call):
            self._inspect_call(node)
            if isinstance(node.func, ast.Name) and node.func.id in self.functions:
                self._inspect_helper(
                    node.func.id,
                    depth=max(0, helper_depth + 1),
                    path=helper_path,
                    module_constants=self.constants,
                )
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            self.fact(
                "qiskit.bit_order.v1",
                "source_visible_bit_slicing",
                "Source-visible slicing may affect bit-order interpretation.",
                line=node.lineno,
                alignment_status="ambiguous",
                choice_origin="explicit_in_source",
                evidence_confidence="Observed",
            )
        for child in ast.iter_child_nodes(node):
            self._inspect_node(
                child,
                constants=constants,
                helper_depth=helper_depth,
                helper_path=helper_path,
            )

    def _inspect_call(self, node: ast.Call) -> None:
        resolved = self.resolve(node.func)
        terminal = resolved.rsplit(".", 1)[-1]
        lower = terminal.lower()
        line = node.lineno
        self.call_records.append({"resolved": resolved, "terminal": terminal, "line": line})
        if resolved.startswith("qiskit") or terminal in _QISKIT_CONSTRUCTORS:
            self.fact(
                "qiskit.api.references.v1",
                "qiskit_api_reference",
                "A maintained Qiskit API call shape is visible in the selected source.",
                line=line,
                symbol=resolved,
            )
        if terminal in _QISKIT_CONSTRUCTORS:
            self.fact(
                "qiskit.circuit.construction.v1",
                "circuit_or_register_construction",
                "A circuit or register construction call shape is visible in the selected source.",
                line=line,
                symbol=terminal,
                alignment_status="appears_aligned",
            )
            for index, argument in enumerate(node.args[:2]):
                safe = _safe_scalar(
                    argument,
                    self.constants,
                    maximum_depth=self.limits["maximum_constant_expression_depth"],
                    maximum_absolute_value=self.limits["maximum_safe_scalar_absolute_value"],
                )
                if safe is not None and isinstance(safe.value, int) and safe.value >= 0:
                    family = (
                        "source_declared_quantum_width"
                        if terminal != "ClassicalRegister" and index == 0
                        else "source_declared_classical_width"
                    )
                    self.fact(
                        "qiskit.register.width.v1",
                        family,
                        "A bounded source-declared width is visible; it is not a verified circuit width.",
                        line=line,
                        safe_value=safe,
                        symbol=terminal,
                    )
        if terminal in _PARAMETER_CONSTRUCTORS:
            self.fact(
                "qiskit.parameter.declaration.v1",
                "parameter_declaration",
                "A Qiskit parameter declaration call shape is visible.",
                line=line,
                symbol=terminal,
                alignment_status="appears_aligned",
            )
            if terminal == "ParameterVector" and len(node.args) > 1:
                count = _safe_scalar(
                    node.args[1],
                    self.constants,
                    maximum_depth=self.limits["maximum_constant_expression_depth"],
                    maximum_absolute_value=self.limits["maximum_safe_scalar_absolute_value"],
                )
                if count is not None and isinstance(count.value, int) and count.value >= 0:
                    self.fact(
                        "qiskit.parameter.declaration.v1",
                        "bounded_parameter_count",
                        "A bounded source-declared parameter count is visible.",
                        line=line,
                        safe_value=count,
                        symbol=terminal,
                    )
        elif any(
            isinstance(item, ast.Name) and item.id in self.parameter_symbols
            for argument in (*node.args, *(keyword.value for keyword in node.keywords))
            for item in ast.walk(argument)
        ):
            self.fact(
                "qiskit.parameter.declaration.v1",
                "source_visible_parameter_use",
                "A maintained call shape references a source-declared parameter; runtime binding remains unproven.",
                line=line,
                symbol=terminal,
                alignment_status="appears_aligned",
            )
        if lower in _BINDING_CALLS:
            self.fact(
                "qiskit.parameter.binding.v1",
                "source_visible_parameter_binding",
                "A maintained parameter-binding call shape is visible in the selected source.",
                line=line,
                symbol=terminal,
                alignment_status="appears_aligned",
            )
        if lower in _MEASUREMENT_CALLS:
            measurement_structure = {
                "value_disclosure": "withheld",
                "structural_category": (
                    "measure_all_call" if lower == "measure_all" else "explicit_measure_mapping"
                ),
                "bounded_argument_count": min(len(node.args), 2),
                "collection_contents_included": False,
            }
            self.fact(
                "qiskit.measurement.v1",
                "source_visible_measurement",
                "An explicit measurement call shape is visible in the selected source.",
                line=line,
                symbol=terminal,
                structure=measurement_structure,
                alignment_status="appears_aligned",
            )
        if lower in _BIT_ORDER_CALLS:
            self.fact(
                "qiskit.bit_order.v1",
                "source_visible_bit_order_transformation",
                "A source-visible reversal call shape may affect bit-order interpretation.",
                line=line,
                symbol=terminal,
                alignment_status="ambiguous",
            )
        if lower in _EXECUTION_CALLS:
            self.fact(
                "qiskit.execution.configuration.v1",
                "source_visible_execution_call_shape",
                "An execution-related call shape is visible; invocation and effective settings are not proven.",
                line=line,
                symbol=terminal,
                required_later_evidence="run_results",
            )
        for keyword in node.keywords:
            if keyword.arg not in _ALLOWED_CONFIG_KEYWORDS:
                continue
            value = _safe_scalar(
                keyword.value,
                self.constants,
                maximum_depth=self.limits["maximum_constant_expression_depth"],
                maximum_absolute_value=self.limits["maximum_safe_scalar_absolute_value"],
            )
            if value is not None:
                if keyword.arg == "optimization_level" and value.value not in {0, 1, 2, 3}:
                    continue
                self.fact(
                    "qiskit.execution.configuration.v1",
                    _ALLOWED_CONFIG_KEYWORDS[keyword.arg],
                    "A bounded source-visible configuration scalar is present; effective use is not proven.",
                    line=line,
                    safe_value=value,
                    symbol=keyword.arg,
                    required_later_evidence="run_results",
                )
            else:
                self.ambiguous(
                    "qiskit.execution.configuration.v1",
                    "unresolved_source_configuration",
                    line,
                    "A source-visible configuration argument could not be resolved under the safe scalar rules.",
                )
        if lower in _RESULT_CALLS or any(
            term in lower
            for term in ("count", "sample", "probab", "frequen", "postselect", "rank", "decode")
        ):
            self.fact(
                "qiskit.result.processing.v1",
                "source_visible_result_processing",
                "A result-processing call shape is visible; no run result or output value was inspected.",
                line=line,
                symbol=terminal,
                required_later_evidence="run_results",
            )
        if lower == "int" and len(node.args) >= 2:
            base = _safe_scalar(
                node.args[1],
                self.constants,
                maximum_depth=self.limits["maximum_constant_expression_depth"],
                maximum_absolute_value=self.limits["maximum_safe_scalar_absolute_value"],
            )
            if base is not None and base.value == 2:
                self.fact(
                    "qiskit.result.processing.v1",
                    "source_visible_bit_string_conversion",
                    "A source-visible base-two conversion call shape is present; no input or runtime result value was inspected.",
                    line=line,
                    required_later_evidence="run_results",
                )
        if lower in _CONTROLLED_CALLS:
            self.fact(
                "profile.grover.structure.v1",
                "controlled_operation_structure",
                "A controlled-operation call shape is visible and may be relevant to maintained Grover motifs.",
                line=line,
                symbol=terminal,
            )
        if any(term in lower for term in ("oracle", "diffus", "amplif")):
            self.fact(
                "profile.grover.structure.v1",
                "grover_named_structure",
                "A Grover-related source symbol is visible; its name does not prove algorithm identity.",
                line=line,
                symbol=terminal,
            )
        if lower in {"rzz", "rz", "paulievolutiongate"} or "cost" in lower:
            self.fact(
                "profile.qaoa.structure.v1",
                "qaoa_cost_layer_structure",
                "A maintained cost-layer source call shape is visible.",
                line=line,
                symbol=terminal,
            )
        if lower in {"rx", "ry"} or "mixer" in lower:
            self.fact(
                "profile.qaoa.structure.v1",
                "qaoa_mixer_layer_structure",
                "A maintained mixer-layer source call shape is visible.",
                line=line,
                symbol=terminal,
            )
        raw_root = _raw_name(node.func).split(".", 1)[0]
        if raw_root in self.imported_names and not resolved.startswith("qiskit"):
            self.ambiguous(
                "qiskit.helper.expansion.v1",
                "imported_helper_unresolved",
                line,
                "An imported helper reference was observed but imports are not followed.",
            )
        if not isinstance(node.func, (ast.Name, ast.Attribute)):
            self.ambiguous(
                "qiskit.helper.expansion.v1",
                "dynamic_dispatch_unresolved",
                line,
                "A dynamically dispatched call cannot be expanded by the bounded same-file analyzer.",
            )

    def _inspect_loop(self, node: ast.For, constants: Mapping[str, _SafeScalar]) -> int | None:
        if isinstance(node.iter, ast.Call) and _terminal(node.iter.func) == "range":
            values = [
                _safe_scalar(
                    item,
                    constants,
                    maximum_depth=self.limits["maximum_constant_expression_depth"],
                    maximum_absolute_value=self.limits["maximum_safe_scalar_absolute_value"],
                )
                for item in node.iter.args
            ]
            if values and all(item is not None and isinstance(item.value, int) for item in values):
                ints = [int(item.value) for item in values if item is not None]
                try:
                    count = len(range(*ints))
                except (TypeError, ValueError):
                    count = -1
                if 0 <= count <= self.limits["maximum_safe_collection_length"]:
                    self.fact(
                        "python.loop.repetition.v1",
                        "statically_established_repetition",
                        "A bounded range-like repetition count is statically established.",
                        line=node.lineno,
                        safe_value=_SafeScalar(count, "integer", 0),
                        alignment_status="appears_aligned",
                    )
                    return count
        self.ambiguous(
            "python.loop.repetition.v1",
            "dynamic_repetition",
            node.lineno,
            "A loop is visible but its repetition count is not established by the safe scalar rules.",
        )
        return None

    def _inspect_branch(self, node: ast.If, constants: Mapping[str, _SafeScalar]) -> bool | None:
        value = _safe_scalar(
            node.test,
            constants,
            maximum_depth=self.limits["maximum_constant_expression_depth"],
            maximum_absolute_value=self.limits["maximum_safe_scalar_absolute_value"],
        )
        if value is not None and isinstance(value.value, bool):
            self.fact(
                "python.branch.structure.v1",
                "statically_established_branch",
                "A Boolean branch condition is statically established under the safe scalar rules.",
                line=node.lineno,
            )
            return bool(value.value)
        else:
            self.ambiguous(
                "python.branch.structure.v1",
                "dynamic_branch",
                node.lineno,
                "A branch is visible but runtime branch selection is not statically established.",
            )
        return None


def _compact_source_facts(facts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Coalesce repeated call-shape facts without discarding bounded evidence lines."""

    compact: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for supplied in facts:
        fact = deepcopy(dict(supplied))
        key = (
            str(fact["detector_id"]),
            str(fact["decision_family"]),
            repr(fact.get("safe_scalar_fact")),
            repr(fact.get("structural_fact")),
        )
        existing = by_key.get(key)
        if existing is None:
            symbol = fact.pop("safe_symbol_reference", None)
            if symbol:
                fact["safe_symbol_references"] = [symbol]
            by_key[key] = fact
            compact.append(fact)
            continue
        existing_basis = existing["source_evidence_basis"]
        supplied_basis = fact["source_evidence_basis"]
        existing_basis["bounded_line_references"] = sorted(
            set(existing_basis.get("bounded_line_references") or [])
            | set(supplied_basis.get("bounded_line_references") or [])
        )[:20]
        symbols = set(existing.get("safe_symbol_references") or [])
        symbol = fact.get("safe_symbol_reference")
        if symbol:
            symbols.add(str(symbol))
        existing["safe_symbol_references"] = sorted(symbols)[:20]
    return compact


def _qualified_motif_records(
    baseline_observations: Sequence[Mapping[str, Any]],
    *,
    source_facts: Sequence[Mapping[str, Any]],
    ambiguities: Sequence[Mapping[str, Any]],
    source_reference: Mapping[str, Any],
    logical_source_label: str,
    detector_inventory: Sequence[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    unresolved_source = bool(ambiguities)
    motif_families = {
        "qiskit.circuit.construction": {"circuit_or_register_construction"},
        "qiskit.parameter.use": {
            "parameter_declaration",
            "bounded_parameter_count",
            "source_visible_parameter_binding",
            "qaoa_parameterized_layer_structure",
        },
        "qiskit.measurement.mapping": {"source_visible_measurement"},
        "qiskit.controlled.operations": {"controlled_operation_structure"},
        "qiskit.result.processing": {"source_visible_result_processing"},
        "grover.oracle.structure": {
            "controlled_operation_structure",
            "grover_named_structure",
        },
        "grover.diffusion.amplification": {"grover_named_structure"},
        "grover.iteration.structure": {"statically_established_repetition"},
        "qaoa.cost.layer": {"qaoa_cost_layer_structure"},
        "qaoa.mixer.layer": {"qaoa_mixer_layer_structure"},
        "qaoa.repetition.layer": {"statically_established_repetition"},
        "qaoa.parameterized.layer": {
            "parameter_declaration",
            "bounded_parameter_count",
            "qaoa_parameterized_layer_structure",
        },
    }
    observed_families = {str(item.get("decision_family")) for item in source_facts}
    for baseline in baseline_observations:
        record = deepcopy(dict(baseline))
        record["inspection_scope_reference"] = "source_evidence_depth.inspection_scope"
        record["supported_detector_inventory_reference"] = (
            "source_evidence_depth.detector_inventory"
        )
        record["non_proof_reference"] = "source_evidence_depth.non_proofs[0]"
        record.pop("non_proof", None)
        if record.get("limitation") == _STATIC_NON_PROOF:
            record["limitation_reference"] = "source_evidence_depth.non_proofs[0]"
            record.pop("limitation", None)
        motif_id = str(record.get("motif_id"))
        bounded_observed = bool(motif_families.get(motif_id, set()) & observed_families)
        if record.get("observation_status") == "observed" and not bounded_observed:
            record["observation_status"] = "ambiguous" if unresolved_source else "not_observed"
            record["evidence_confidence"] = "Not proven" if unresolved_source else "Observed"
        if record.get("observation_status") == "not_observed":
            if unresolved_source:
                record["observation_status"] = "ambiguous"
                record["evidence_confidence"] = "Not proven"
                record["limitation"] = (
                    "The bounded analyzer encountered unresolved source structure that may conceal this motif."
                )
                record.pop("bounded_negative_finding", None)
            else:
                record["bounded_negative_finding"] = _NEGATIVE_SCOPE
                record["what_was_not_found"] = str(record["motif_id"])
                record["what_remains_unproven"] = _STATIC_NON_PROOF
        records.append(record)
    return records


def _qualified_alignment_findings(
    baseline_findings: Sequence[Mapping[str, Any]],
    motif_observations: Sequence[Mapping[str, Any]],
    *,
    source_reference: Mapping[str, Any],
    logical_source_label: str,
    detector_inventory: Sequence[str],
) -> list[dict[str, Any]]:
    observations = {str(item["motif_id"]): item for item in motif_observations}
    result: list[dict[str, Any]] = []
    for baseline in baseline_findings:
        item = deepcopy(dict(baseline))
        motif_id = str(item["expected_item"])
        observation = observations.get(motif_id) or {}
        status = observation.get("observation_status")
        if item.get("choice_origin") == "introduced_after_blueprint" and status != "observed":
            continue
        if status == "ambiguous":
            item["alignment_status"] = "ambiguous"
            item["evidence_confidence"] = "Not proven"
            item["bounded_observation"] = str(
                observation.get("limitation")
                or "The bounded analyzer encountered unresolved source structure that may conceal this motif."
            )
        elif status == "not_observed":
            item["alignment_status"] = "not_observed"
            item["evidence_confidence"] = "Observed"
            item["bounded_observation"] = _NEGATIVE_SCOPE
        if item.get("choice_origin") == "introduced_after_blueprint":
            item["explanation"] = _NON_CAUSAL_INTRODUCED
        item["inspection_scope_reference"] = "source_evidence_depth.inspection_scope"
        item["detector_identifier"] = "canonical_motif_registry_depth_v1"
        item["supported_detector_inventory_reference"] = "source_evidence_depth.detector_inventory"
        item["non_proof_reference"] = "source_evidence_depth.non_proofs[0]"
        item.pop("non_proof", None)
        if item.get("alignment_status") == "not_observed":
            item["bounded_observation"] = _NEGATIVE_SCOPE
            item["what_was_not_found"] = motif_id
            item["what_remains_unproven"] = _STATIC_NON_PROOF
        result.append(item)
    return result


def _qualified_source_negative_findings(
    source_facts: Sequence[Mapping[str, Any]],
    ambiguities: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    observed = {str(item.get("decision_family")) for item in source_facts}
    unresolved = bool(ambiguities)
    candidates = (
        (
            "source_visible_parameter_binding",
            "qiskit.parameter.binding.v1",
            "parameter_declaration",
            "parameter binding",
            "logical_circuit",
        ),
        (
            "source_visible_measurement",
            "qiskit.measurement.v1",
            "circuit_or_register_construction",
            "measurement call or mapping",
            "logical_circuit",
        ),
        (
            "source_visible_result_processing",
            "qiskit.result.processing.v1",
            "circuit_or_register_construction",
            "result-access or result-processing call shape",
            "run_results",
        ),
    )
    records: list[dict[str, Any]] = []
    for family, detector_id, prerequisite, display, later_evidence in candidates:
        if prerequisite not in observed or family in observed:
            continue
        status = "ambiguous" if unresolved else "not_observed"
        records.append(
            {
                "negative_id": f"negative.{family}",
                "decision_family": family,
                "detector_id": detector_id,
                "alignment_status": status,
                "evidence_confidence": "Not proven" if unresolved else "Observed",
                "choice_origin": "unknown",
                "bounded_observation": (
                    "Unresolved source structure may conceal this maintained source fact."
                    if unresolved
                    else _NEGATIVE_SCOPE
                ),
                "inspection_scope_reference": "source_evidence_depth.inspection_scope",
                "parser_status": "parsed",
                "supported_detector_inventory_reference": (
                    "source_evidence_depth.detector_inventory"
                ),
                "alias_resolution_limitations_reference": (
                    "source_evidence_depth.inspection_scope.alias_resolution_limitations"
                ),
                "helper_expansion_limitations_reference": (
                    "source_evidence_depth.inspection_scope.helper_expansion_limitations"
                ),
                "branch_and_dynamic_limitations_reference": (
                    "source_evidence_depth.inspection_scope.branch_and_dynamic_limitations"
                ),
                "what_was_not_found": display,
                "what_remains_unproven": _STATIC_NON_PROOF,
                "required_later_evidence": later_evidence,
                "suggested_user_controlled_action": (
                    "Request logical-circuit evidence"
                    if later_evidence == "logical_circuit"
                    else "Leave unresolved"
                ),
            }
        )
    return records


def _decision_item(
    *,
    decision_id: str,
    choice: str,
    family: str,
    relationship: str,
    choice_origin: str,
    evidence_confidence: str,
    alignment_status: str,
    source_basis: Mapping[str, Any],
    motif_id: str | None,
    why: str,
    alternatives: Sequence[Mapping[str, Any]],
    action: Mapping[str, Any] | None,
    requirement_order: int,
    source_order: int,
    maintained_order: int,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "decision_id": decision_id,
        "apparent_implementation_choice": choice,
        "decision_family": family,
        "blueprint_requirement_reference": motif_id,
        "relationship_to_confirmed_blueprint": relationship,
        "choice_origin": choice_origin,
        "evidence_confidence": evidence_confidence,
        "alignment_status": alignment_status,
        "bounded_source_evidence_basis": deepcopy(dict(source_basis)),
        "why_the_choice_matters": why,
        "what_remains_unproven_reference": "source_evidence_depth.non_proofs[0]",
        "required_later_evidence": "logical_circuit",
        "suggested_user_controlled_actions": ([deepcopy(dict(action))] if action else []),
        "ordering_key": [requirement_order, source_order, maintained_order],
    }
    lines = list(source_basis.get("bounded_line_references") or [])
    if lines:
        item["safe_symbol_or_line_reference"] = {"line_references": lines}
    if motif_id:
        item["related_motif_evidence"] = motif_id
        item["profile_expectation"] = motif_id
    if alternatives:
        item["profile_supported_alternatives"] = deepcopy(list(alternatives))
    return item


def _decision_summary(
    *,
    facts: Sequence[Mapping[str, Any]],
    ambiguities: Sequence[Mapping[str, Any]],
    findings: Sequence[Mapping[str, Any]],
    source_negative_findings: Sequence[Mapping[str, Any]],
    version_facts: Sequence[Mapping[str, Any]],
    expected_requirements: Sequence[Mapping[str, Any]],
    motif_registry: Mapping[str, Mapping[str, Any]],
    decision_groups: Sequence[str],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in decision_groups}
    expected_order = {
        str(item["motif_id"]): index for index, item in enumerate(expected_requirements)
    }
    default_basis = {
        "inspection_scope_reference": "source_evidence_depth.inspection_scope",
        "bounded_line_references": [],
        "source_visible_only": True,
    }
    for index, finding in enumerate(findings):
        motif_id = str(finding["expected_item"])
        origin = str(finding["choice_origin"])
        if origin == "introduced_after_blueprint":
            group = "choices_introduced_after_blueprint"
            relationship = "not_represented_in_confirmed_blueprint_non_causal"
            action_name = "Clarify the requirement"
        elif origin == "blueprint_confirmed":
            group = "blueprint_confirmed_choices"
            relationship = "represented_in_confirmed_blueprint"
            action_name = "Accept and add to blueprint"
        elif origin == "profile_expected":
            group = "profile_expected_structures"
            relationship = "maintained_profile_expectation_not_observation"
            action_name = "Compare profile-supported alternatives"
        else:
            group = "ambiguous_or_dynamic_behavior"
            relationship = "unresolved_under_bounded_static_inspection"
            action_name = "Leave unresolved"
        basis = {
            "inspection_scope_reference": "source_evidence_depth.inspection_scope",
            "bounded_line_references": [],
            "source_visible_only": True,
        }
        action = _action(action_name, motif_id, str(finding["bounded_observation"]))
        grouped[group].append(
            _decision_item(
                decision_id=f"motif.{motif_id}",
                choice=motif_id,
                family=str(
                    (
                        motif_registry[motif_id].get("related_implementation_decisions")
                        or [motif_id]
                    )[0]
                ),
                relationship=relationship,
                choice_origin=origin,
                evidence_confidence=str(finding["evidence_confidence"]),
                alignment_status=str(finding["alignment_status"]),
                source_basis=basis,
                motif_id=motif_id,
                why=f"maintained_motif_metadata:{motif_id}",
                alternatives=_alternative_records(motif_registry, motif_id),
                action=action,
                requirement_order=expected_order.get(motif_id, 10_000),
                source_order=index,
                maintained_order=index,
            )
        )
    configuration_facts = [
        fact
        for fact in facts
        if str(fact["decision_family"])
        in {
            "source_visible_execution_call_shape",
            "bounded_shot_count",
            "seed_value",
            "optimization_level",
            "source_visible_parameter_binding",
            "source_visible_measurement",
        }
    ]
    if configuration_facts:
        configuration_families = sorted(
            {str(item["decision_family"]) for item in configuration_facts}
        )
        configuration_lines = sorted(
            {
                line
                for item in configuration_facts
                for line in item["source_evidence_basis"].get("bounded_line_references") or []
            }
        )[:20]
        item = _decision_item(
            decision_id="source.explicit_configuration",
            choice="explicit_source_configuration",
            family="explicit_source_configuration",
            relationship="explicit_bounded_source_configuration",
            choice_origin="explicit_in_source",
            evidence_confidence="Observed",
            alignment_status="not_applicable",
            source_basis={
                "inspection_scope_reference": "source_evidence_depth.inspection_scope",
                "bounded_line_references": configuration_lines,
                "source_visible_only": True,
            },
            motif_id=None,
            why="maintained_source_configuration_detectors",
            alternatives=[],
            action=_action(
                "Clarify the requirement",
                "explicit_source_configuration",
                "bounded_source_configuration_facts",
            ),
            requirement_order=10_000,
            source_order=configuration_lines[0] if configuration_lines else 10_000,
            maintained_order=0,
        )
        item["included_decision_families"] = configuration_families
        grouped["explicit_source_configuration"].append(item)
    if ambiguities:
        ambiguity_families = sorted({str(item["category"]) for item in ambiguities})
        ambiguity_lines = sorted(
            {
                line
                for item in ambiguities
                for line in item["source_evidence_basis"].get("bounded_line_references") or []
            }
        )[:20]
        item = _decision_item(
            decision_id="ambiguity.bounded_dynamic_behavior",
            choice="bounded_dynamic_behavior",
            family="ambiguous_or_dynamic_behavior",
            relationship="unresolved_bounded_source_relationship",
            choice_origin="unknown",
            evidence_confidence="Not proven",
            alignment_status="ambiguous",
            source_basis={
                "inspection_scope_reference": "source_evidence_depth.inspection_scope",
                "bounded_line_references": ambiguity_lines,
                "source_visible_only": True,
            },
            motif_id=None,
            why="maintained_static_analysis_ceiling",
            alternatives=[],
            action=_action(
                "Request logical-circuit evidence",
                "bounded_dynamic_behavior",
                "bounded_ambiguity_facts",
            ),
            requirement_order=10_000,
            source_order=ambiguity_lines[0] if ambiguity_lines else 10_000,
            maintained_order=0,
        )
        item["included_ambiguity_families"] = ambiguity_families
        grouped["ambiguous_or_dynamic_behavior"].append(item)
    for index, fact in enumerate(version_facts):
        if fact.get("fact_kind") != "version_bounded_candidate_default":
            continue
        grouped["sdk_default_candidates"].append(
            _decision_item(
                decision_id=f"sdk.{fact['rule_id']}",
                choice=str(fact["setting"]),
                family="sdk_default_candidate",
                relationship="version_bounded_candidate_not_effective_value",
                choice_origin="sdk_default_candidate",
                evidence_confidence="Inferred",
                alignment_status="not_applicable",
                source_basis=default_basis,
                motif_id="qiskit.measurement.mapping",
                why="maintained_sdk_rule",
                alternatives=[],
                action=_action(
                    "Clarify the requirement",
                    str(fact["setting"]),
                    "No explicit override was observed and a supported version fact was supplied.",
                ),
                requirement_order=10_000,
                source_order=10_000,
                maintained_order=index,
            )
        )
    for index, finding in enumerate(findings):
        if finding["alignment_status"] not in {
            "ambiguous",
            "not_observed",
            "requires_next_stage_evidence",
        }:
            continue
        motif_id = str(finding["expected_item"])
        grouped["requires_logical_circuit_evidence"].append(
            _decision_item(
                decision_id=f"next-stage.{motif_id}",
                choice=motif_id,
                family="next_stage_evidence_requirement",
                relationship="requires_separately_supplied_later_stage_evidence",
                choice_origin="target_derived",
                evidence_confidence="Not proven",
                alignment_status="requires_next_stage_evidence",
                source_basis=default_basis,
                motif_id=motif_id,
                why="maintained_motif_next_stage_requirement",
                alternatives=[],
                action=_action(
                    "Request logical-circuit evidence",
                    motif_id,
                    str(finding["bounded_observation"]),
                ),
                requirement_order=expected_order.get(motif_id, 10_000),
                source_order=10_000,
                maintained_order=index,
            )
        )
    for index, finding in enumerate(source_negative_findings):
        is_ambiguous = finding["alignment_status"] == "ambiguous"
        group = (
            "ambiguous_or_dynamic_behavior" if is_ambiguous else "requires_logical_circuit_evidence"
        )
        action_name = str(finding["suggested_user_controlled_action"])
        grouped[group].append(
            _decision_item(
                decision_id=str(finding["negative_id"]),
                choice=str(finding["what_was_not_found"]),
                family=str(finding["decision_family"]),
                relationship="bounded_source_fact_not_established",
                choice_origin=str(finding["choice_origin"]),
                evidence_confidence=str(finding["evidence_confidence"]),
                alignment_status=str(finding["alignment_status"]),
                source_basis={
                    "inspection_scope_reference": ("source_evidence_depth.inspection_scope"),
                    "bounded_line_references": [],
                    "source_visible_only": True,
                },
                motif_id=None,
                why=f"maintained_detector:{finding['detector_id']}",
                alternatives=[],
                action=_action(
                    action_name,
                    str(finding["decision_family"]),
                    str(finding["bounded_observation"]),
                ),
                requirement_order=10_000,
                source_order=10_000,
                maintained_order=index,
            )
        )
    action_decisions: dict[str, list[str]] = {}
    for group_name, items in grouped.items():
        if group_name == "suggested_next_actions":
            continue
        for item in items:
            for action in item["suggested_user_controlled_actions"]:
                action_decisions.setdefault(str(action["action"]), []).append(
                    str(item.get("decision_id", "unresolved_decision"))
                )
    grouped["suggested_next_actions"] = [
        {
            "decision_id": f"action.{index:03d}",
            "action": {
                "action": action_name,
                "decision_or_ambiguity": sorted(set(decision_ids)),
                "supporting_evidence_reference": sorted(set(decision_ids)),
                "intended_update": "next_human_intent_or_confirmed_blueprint",
                "could_establish": "explicit_requirement_choice_or_evidence_request",
                "still_not_proven_reference": "source_evidence_depth.non_proofs[0]",
                "executed": False,
            },
            "choice_origin": "unknown",
            "evidence_confidence": "Suggested next check",
            "alignment_status": "not_applicable",
        }
        for index, (action_name, decision_ids) in enumerate(sorted(action_decisions.items()))
    ]
    groups = []
    for order, name in enumerate(decision_groups, 1):
        items = grouped[name]
        items.sort(
            key=lambda item: (
                (item.get("ordering_key") or [10_000, 10_000, 10_000, ""])[0],
                (item.get("ordering_key") or [10_000, 10_000, 10_000, ""])[1],
                (item.get("ordering_key") or [10_000, 10_000, 10_000, ""])[2],
                str(item.get("decision_id", "")),
            )
        )
        groups.append({"group_id": name, "order": order, "items": items})
    return {
        "section_type": "implementation_decision_summary",
        "schema_version": 1,
        "child_contract": "implementation_decision_summary",
        "independent_artifact": False,
        "discoverable_capability": False,
        "current_session_only": True,
        "persistent": False,
        "actions_executed": False,
        "ordering_basis": [
            "confirmed_blueprint_requirement_order",
            "bounded_source_order",
            "maintained_rule_order",
            "canonical_identifier",
        ],
        "groups": groups,
    }


def analyze_qiskit_source_depth(
    source_text: str,
    *,
    logical_source_label: str,
    source_reference: Mapping[str, Any],
    profile_id: str,
    expected_requirements: Sequence[Mapping[str, Any]],
    motif_registry: Mapping[str, Mapping[str, Any]],
    baseline_findings: Sequence[Mapping[str, Any]],
    baseline_observations: Sequence[Mapping[str, Any]],
    version_facts: Sequence[Mapping[str, Any]],
    detector_inventory: Sequence[str],
    resource_limits: Mapping[str, int],
    decision_groups: Sequence[str],
    user_controlled_actions: Sequence[str],
) -> dict[str, Any]:
    """Return the explicitly gated, share-safe depth-v1 child representation."""

    gate_metadata = {
        "gate": "depth_v1",
        "child_contract": "implementation_decision_summary",
        "child_version": 1,
        "analysis_unit": "one_explicitly_selected_python_source_artifact",
        "detector_inventory": list(detector_inventory),
        "resource_limits": deepcopy(dict(resource_limits)),
        "raw_source_included": False,
        "raw_path_included": False,
        "imports_followed": False,
        "source_imported": False,
        "source_executed": False,
        "network_accessed": False,
        "later_stage_analysis_performed": False,
        "inspection_scope": {
            "selected_artifact_reference": deepcopy(dict(source_reference)),
            "logical_source_label": logical_source_label,
            "inspection_method": _INSPECTION_METHOD,
            "parser_status": "parsed",
            "supported_detector_inventory_reference": ("source_evidence_depth.detector_inventory"),
            "alias_resolution_limitations": "Local aliases only; imports are not followed.",
            "helper_expansion_limitations": ("Same-file direct helpers only, maximum depth two."),
            "branch_and_dynamic_limitations": (
                "Dynamic branches, dispatch, recursion, imported helpers, and unsupported expressions remain unresolved."
            ),
        },
    }
    try:
        tree = ast.parse(source_text, mode="exec")
    except (SyntaxError, ValueError):
        parse_limited_scope = deepcopy(gate_metadata["inspection_scope"])
        parse_limited_scope["parser_status"] = "parse_failed"
        return {
            **gate_metadata,
            "inspection_scope": parse_limited_scope,
            "status": "parse_limited",
            "parser_status": "parse_failed",
            "diagnostics": [
                "The selected source could not be parsed; deeper findings and the decision summary are unavailable."
            ],
        }
    analyzer = _DepthAnalyzer(
        tree,
        logical_source_label=logical_source_label,
        source_reference=source_reference,
        resource_limits=resource_limits,
        detector_inventory=detector_inventory,
    )
    try:
        analyzer.inspect()
    except ValueError as exc:
        if str(exc) != "source_evidence_depth_ast_limit_exceeded":
            raise
        return {
            **gate_metadata,
            "status": "unavailable",
            "diagnostics": [
                "The selected source exceeds the bounded AST resource limit; deeper findings and the decision summary are unavailable."
            ],
        }
    source_facts = _compact_source_facts(analyzer.facts)
    construction_form_observation = _qiskit_construction_form_observation(
        tree, source_reference=source_reference
    )
    motif_observations = _qualified_motif_records(
        baseline_observations,
        source_facts=source_facts,
        ambiguities=analyzer.ambiguities,
        source_reference=source_reference,
        logical_source_label=logical_source_label,
        detector_inventory=detector_inventory,
    )
    findings = _qualified_alignment_findings(
        baseline_findings,
        motif_observations,
        source_reference=source_reference,
        logical_source_label=logical_source_label,
        detector_inventory=detector_inventory,
    )
    source_negative_findings = _qualified_source_negative_findings(
        source_facts, analyzer.ambiguities
    )
    summary = _decision_summary(
        facts=source_facts,
        ambiguities=analyzer.ambiguities,
        findings=findings,
        source_negative_findings=source_negative_findings,
        version_facts=version_facts,
        expected_requirements=expected_requirements,
        motif_registry=motif_registry,
        decision_groups=decision_groups,
    )
    serialized = repr({"facts": source_facts, "summary": summary}).lower()
    for forbidden in (
        "ai-selected",
        "model-selected",
        "the model decided",
        "the author intended",
        "hidden reasoning",
        "confidence_score",
        "assurance_percentage",
    ):
        if forbidden in serialized:
            raise ValueError("source_evidence_depth_forbidden_claim")
    return {
        **gate_metadata,
        "status": "available",
        "profile_id": profile_id,
        "parser_status": "parsed",
        "source_facts": source_facts,
        "qiskit_construction_form_observation": construction_form_observation,
        "ambiguities": analyzer.ambiguities,
        "helper_expansion": analyzer.helper_records,
        "motif_observations": motif_observations,
        "alignment_findings": findings,
        "source_negative_findings": source_negative_findings,
        "implementation_decision_summary": summary,
        "supported_user_controlled_actions": list(user_controlled_actions),
        "non_causal_introduced_after_blueprint": _NON_CAUSAL_INTRODUCED,
        "negative_finding_scope": _NEGATIVE_SCOPE,
        "non_proofs": [_STATIC_NON_PROOF],
    }
