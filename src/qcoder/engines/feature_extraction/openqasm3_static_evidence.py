"""Strict OpenQASM 3 static-evidence sidecar contract.

The sidecar is a local, deterministic description of one explicitly selected
source artifact.  It carries qualified static facts; it is not an execution or
language-compliance receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID = "qcoder.openqasm3_static_evidence.v1"
OPENQASM3_PARSER_ID = "qcoder.openqasm3.bounded_parser.v1"
OPENQASM3_STANDARD_GATE_VOCABULARY_ID = "qcoder.openqasm3.stdgates_3_0.v1"

SUPPORT_STATES = (
    "supported",
    "partially_supported",
    "recognized_but_unsupported",
    "unrecognized",
)
EXACTNESS_STATES = (
    "exact",
    "lower_bound",
    "partial",
    "not_established",
    "not_applicable",
)
FILE_STATUSES = ("supported", "partial", "fatal")

LANGUAGE_BUILTINS: dict[str, tuple[int, int]] = {
    "U": (3, 1),
    "gphase": (1, 0),
}
STANDARD_GATES: dict[str, tuple[int, int]] = {
    "p": (1, 1),
    "x": (0, 1),
    "y": (0, 1),
    "z": (0, 1),
    "h": (0, 1),
    "s": (0, 1),
    "sdg": (0, 1),
    "t": (0, 1),
    "tdg": (0, 1),
    "sx": (0, 1),
    "rx": (1, 1),
    "ry": (1, 1),
    "rz": (1, 1),
    "cx": (0, 2),
    "cy": (0, 2),
    "cz": (0, 2),
    "ch": (0, 2),
    "swap": (0, 2),
    "cp": (1, 2),
    "crx": (1, 2),
    "cry": (1, 2),
    "crz": (1, 2),
    "cu": (4, 2),
    "ccx": (0, 3),
    "cswap": (0, 3),
    "CX": (0, 2),
    "phase": (1, 1),
    "cphase": (1, 2),
    "id": (0, 1),
    "u1": (1, 1),
    "u2": (2, 1),
    "u3": (3, 1),
}

DIAGNOSTIC_CATEGORIES = (
    "missing_header",
    "invalid_header",
    "unsupported_openqasm_version",
    "malformed_syntax",
    "input_size_exceeded",
    "parser_limit_exceeded",
    "unsupported_include",
    "unsupported_construct",
    "unrecognized_construct",
    "duplicate_declaration",
    "invalid_register_reference",
    "index_out_of_range",
    "unsupported_expression",
    "unsupported_modifier",
    "unsafe_path",
    "invalid_encoding",
)

NON_CLAIMS = (
    "No source or circuit was executed.",
    "This is not full OpenQASM 3 language support or a language-compliance claim.",
    "No conversion, semantic equivalence, algorithm correctness, or expected output was established.",
    "No hardware compatibility, backend suitability, runtime, resource, fidelity, shot-count, or statistical-sufficiency conclusion was established.",
    "Observed OpenQASM structure does not establish user intent, author intent, or algorithm identity.",
)

LIMIT_KEYS = (
    "source_bytes",
    "tokens",
    "statements",
    "declarations",
    "operations",
    "nesting_depth",
    "expression_depth",
    "custom_gates",
    "modifier_depth",
    "broadcast_expansion",
    "recovery_events",
    "diagnostics",
    "construct_ledger_entries",
    "individual_quantum_width",
    "total_quantum_width",
    "individual_classical_width",
    "total_classical_width",
)
PARSER_LIMIT_MAXIMA = {
    "source_bytes": 100_000,
    "tokens": 40_000,
    "statements": 12_000,
    "declarations": 1_000,
    "operations": 10_000,
    "nesting_depth": 32,
    "expression_depth": 32,
    "custom_gates": 256,
    "modifier_depth": 8,
    "broadcast_expansion": 4_096,
    "recovery_events": 128,
    "diagnostics": 512,
    "construct_ledger_entries": 12_000,
    "individual_quantum_width": 4_096,
    "total_quantum_width": 4_096,
    "individual_classical_width": 4_096,
    "total_classical_width": 4_096,
}
if tuple(PARSER_LIMIT_MAXIMA) != LIMIT_KEYS:  # pragma: no cover - import-time contract
    raise RuntimeError("openqasm3_parser_limit_contract_invalid")

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s'\"])(?:/[A-Za-z0-9_.-]+/|[A-Za-z]:\\)")


class OpenQASM3EvidenceError(ValueError):
    """Bounded sidecar validation failure."""


def canonical_openqasm3_json(value: Mapping[str, Any]) -> str:
    """Return stable UTF-8 JSON text."""

    validate_openqasm3_static_evidence(value)
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _exact_keys(value: object, keys: set[str], category: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise OpenQASM3EvidenceError(category)
    return value


def _span(value: object) -> None:
    mapped = _exact_keys(
        value,
        {"start_line", "start_column", "end_line", "end_column"},
        "sidecar_span_invalid",
    )
    coordinates = tuple(mapped[key] for key in mapped)
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in coordinates):
        raise OpenQASM3EvidenceError("sidecar_span_invalid")
    if (mapped["end_line"], mapped["end_column"]) < (
        mapped["start_line"],
        mapped["start_column"],
    ):
        raise OpenQASM3EvidenceError("sidecar_span_invalid")


def _string_list(value: object, category: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise OpenQASM3EvidenceError(category)
    return value


def _fact(value: object, *, allow_mapping: bool = False) -> Mapping[str, Any]:
    mapped = _exact_keys(value, {"value", "exactness"}, "sidecar_derived_fact_invalid")
    if mapped["exactness"] not in EXACTNESS_STATES:
        raise OpenQASM3EvidenceError("sidecar_exactness_invalid")
    if mapped["value"] is None and mapped["exactness"] in {"exact", "lower_bound"}:
        raise OpenQASM3EvidenceError("sidecar_derived_fact_invalid")
    if (
        not allow_mapping
        and mapped["value"] is not None
        and (not isinstance(mapped["value"], int) or isinstance(mapped["value"], bool))
    ):
        raise OpenQASM3EvidenceError("sidecar_derived_fact_invalid")
    return mapped


def _validate_privacy(value: object, *, path: str = "$") -> None:
    prohibited_key_tokens = {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "raw_request",
        "raw_response",
        "raw_stream",
        "secret",
        "session",
        "token",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(
                normalized == token
                or normalized.startswith(token + "_")
                or normalized.endswith("_" + token)
                for token in prohibited_key_tokens
            ):
                raise OpenQASM3EvidenceError(f"sidecar_private_field:{path}.{key}")
            if key == "name" and value.get("family") == "include":
                continue
            _validate_privacy(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_privacy(item, path=f"{path}[{index}]")
    elif (
        isinstance(value, str)
        and _ABSOLUTE_PATH_RE.search(value)
        and not re.fullmatch(r"\$\.include_ledger\[\d+\]\.target", path)
    ):
        raise OpenQASM3EvidenceError(f"sidecar_absolute_path:{path}")


def validate_openqasm3_static_evidence(
    value: object,
    *,
    source_bytes: bytes | None = None,
    artifact_label: str | None = None,
) -> str:
    """Validate structure, semantics, and optionally bind evidence to source bytes.

    The standalone mode proves only the sidecar's internal consistency.  Supplying
    the explicitly selected bytes additionally proves the digest and source-span
    bounds used by parser-produced evidence.
    """

    keys = {
        "schema_id",
        "schema_version",
        "parser_identity",
        "standard_gate_vocabulary_identity",
        "declared_language_version",
        "source_sha256",
        "selection_provenance",
        "artifact_label",
        "file_status",
        "fatal_error",
        "quantum_declarations",
        "classical_declarations",
        "include_ledger",
        "construct_ledger",
        "unsupported_region_ledger",
        "recovery_ledger",
        "modifier_chains",
        "custom_gates",
        "measurements",
        "diagnostics",
        "derived_facts",
        "parser_limits",
        "circuit_ir",
        "limitations",
        "non_claims",
        "raw_source_included",
        "source_or_circuit_executed",
        "repository_scanned",
        "network_accessed",
        "motif_evidence_emitted",
        "intent_inferred",
    }
    mapped = _exact_keys(value, keys, "openqasm3_sidecar_shape_invalid")
    if (
        mapped["schema_id"] != OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID
        or type(mapped["schema_version"]) is not int
        or mapped["schema_version"] != 1
    ):
        raise OpenQASM3EvidenceError("openqasm3_sidecar_schema_invalid")
    if mapped["parser_identity"] != OPENQASM3_PARSER_ID:
        raise OpenQASM3EvidenceError("openqasm3_parser_identity_invalid")
    if mapped["standard_gate_vocabulary_identity"] != OPENQASM3_STANDARD_GATE_VOCABULARY_ID:
        raise OpenQASM3EvidenceError("openqasm3_vocabulary_identity_invalid")
    if mapped["declared_language_version"] is not None and not (
        isinstance(mapped["declared_language_version"], str)
        and _VERSION_RE.fullmatch(mapped["declared_language_version"])
    ):
        raise OpenQASM3EvidenceError("openqasm3_declared_version_invalid")
    if not isinstance(mapped["source_sha256"], str) or not _DIGEST_RE.fullmatch(
        mapped["source_sha256"]
    ):
        raise OpenQASM3EvidenceError("openqasm3_source_digest_invalid")
    if mapped["selection_provenance"] != "explicit_file_argument":
        raise OpenQASM3EvidenceError("openqasm3_selection_provenance_invalid")
    if not isinstance(mapped["artifact_label"], str) or not mapped["artifact_label"]:
        raise OpenQASM3EvidenceError("openqasm3_artifact_label_invalid")
    if "/" in mapped["artifact_label"] or "\\" in mapped["artifact_label"]:
        raise OpenQASM3EvidenceError("openqasm3_artifact_label_unsafe")
    if mapped["file_status"] not in FILE_STATUSES:
        raise OpenQASM3EvidenceError("openqasm3_file_status_invalid")

    if mapped["fatal_error"] is not None:
        fatal = _exact_keys(
            mapped["fatal_error"], {"category", "message", "span"}, "sidecar_fatal_error_invalid"
        )
        if fatal["category"] not in DIAGNOSTIC_CATEGORIES or not isinstance(fatal["message"], str):
            raise OpenQASM3EvidenceError("sidecar_fatal_error_invalid")
        _span(fatal["span"])
    if (mapped["file_status"] == "fatal") != (mapped["fatal_error"] is not None):
        raise OpenQASM3EvidenceError("sidecar_fatal_status_inconsistent")

    declaration_keys = {"name", "size", "base", "support", "span"}
    all_declaration_names: set[str] = set()
    for field in ("quantum_declarations", "classical_declarations"):
        if not isinstance(mapped[field], list):
            raise OpenQASM3EvidenceError("sidecar_declarations_invalid")
        names: set[str] = set()
        expected_base = 0
        for row in mapped[field]:
            item = _exact_keys(row, declaration_keys, "sidecar_declaration_invalid")
            if (
                not isinstance(item["name"], str)
                or not item["name"]
                or item["name"] in names
                or type(item["size"]) is not int
                or isinstance(item["size"], bool)
                or item["size"] < 1
                or type(item["base"]) is not int
                or item["base"] < 0
                or item["base"] != expected_base
                or item["support"] not in SUPPORT_STATES
                or item["name"] in all_declaration_names
            ):
                raise OpenQASM3EvidenceError("sidecar_declaration_invalid")
            names.add(item["name"])
            all_declaration_names.add(item["name"])
            expected_base += item["size"]
            _span(item["span"])
        if expected_base > 4_096 or any(row["size"] > 4_096 for row in mapped[field]):
            raise OpenQASM3EvidenceError("sidecar_declaration_width_limit_invalid")

    if not isinstance(mapped["include_ledger"], list):
        raise OpenQASM3EvidenceError("sidecar_include_ledger_invalid")
    for row in mapped["include_ledger"]:
        item = _exact_keys(row, {"target", "support", "span", "opened"}, "sidecar_include_invalid")
        if (
            not isinstance(item["target"], str)
            or item["support"] not in SUPPORT_STATES
            or item["opened"] is not False
        ):
            raise OpenQASM3EvidenceError("sidecar_include_invalid")
        if (item["target"] == "stdgates.inc") != (item["support"] == "supported"):
            raise OpenQASM3EvidenceError("sidecar_include_semantics_invalid")
        _span(item["span"])

    if not isinstance(mapped["construct_ledger"], list):
        raise OpenQASM3EvidenceError("sidecar_construct_ledger_invalid")
    construct_ids: set[str] = set()
    for construct_index, row in enumerate(mapped["construct_ledger"], start=1):
        item = _exact_keys(
            row,
            {
                "construct_id",
                "family",
                "name",
                "classification",
                "span",
                "established",
                "unavailable",
                "dependent_fact_effects",
            },
            "sidecar_construct_invalid",
        )
        if (
            not isinstance(item["construct_id"], str)
            or item["construct_id"] != f"construct-{construct_index:04d}"
            or item["construct_id"] in construct_ids
            or not isinstance(item["family"], str)
            or not item["family"]
            or not isinstance(item["name"], str)
            or item["classification"] not in (*SUPPORT_STATES, "malformed")
        ):
            raise OpenQASM3EvidenceError("sidecar_construct_invalid")
        construct_ids.add(item["construct_id"])
        _span(item["span"])
        _string_list(item["established"], "sidecar_construct_established_invalid")
        unavailable = _string_list(item["unavailable"], "sidecar_construct_unavailable_invalid")
        effects = _string_list(item["dependent_fact_effects"], "sidecar_construct_effects_invalid")
        if item["classification"] == "supported" and (unavailable or effects):
            raise OpenQASM3EvidenceError("sidecar_supported_construct_qualified")
        if item["classification"] != "supported" and not (unavailable and effects):
            raise OpenQASM3EvidenceError("sidecar_qualified_construct_unexplained")

    region_keys = {"construct_id", "classification", "category", "span", "limitation"}
    if not isinstance(mapped["unsupported_region_ledger"], list):
        raise OpenQASM3EvidenceError("sidecar_unsupported_regions_invalid")
    constructs_by_id = {row["construct_id"]: row for row in mapped["construct_ledger"]}
    unsupported_region_ids: list[str] = []
    for row in mapped["unsupported_region_ledger"]:
        item = _exact_keys(row, region_keys, "sidecar_unsupported_region_invalid")
        construct = constructs_by_id.get(item["construct_id"])
        if (
            construct is None
            or item["classification"] != construct["classification"]
            or item["classification"]
            not in {"partially_supported", "recognized_but_unsupported", "unrecognized"}
            or item["category"] not in DIAGNOSTIC_CATEGORIES
            or not isinstance(item["limitation"], str)
            or not item["limitation"]
        ):
            raise OpenQASM3EvidenceError("sidecar_unsupported_region_invalid")
        unsupported_region_ids.append(item["construct_id"])
        _span(item["span"])
        if item["span"] != construct["span"]:
            raise OpenQASM3EvidenceError("sidecar_unsupported_region_span_invalid")

    if not isinstance(mapped["recovery_ledger"], list):
        raise OpenQASM3EvidenceError("sidecar_recovery_ledger_invalid")
    recovery_ids: list[str] = []
    for row in mapped["recovery_ledger"]:
        item = _exact_keys(
            row,
            {"construct_id", "category", "span", "boundary_reliable", "source_repaired"},
            "sidecar_recovery_invalid",
        )
        if (
            item["construct_id"] not in construct_ids
            or item["category"] != "malformed_syntax"
            or item["boundary_reliable"] is not True
            or item["source_repaired"] is not False
        ):
            raise OpenQASM3EvidenceError("sidecar_recovery_invalid")
        recovery_ids.append(item["construct_id"])
        _span(item["span"])
        if item["span"] != constructs_by_id[item["construct_id"]]["span"]:
            raise OpenQASM3EvidenceError("sidecar_recovery_span_invalid")

    expected_unsupported_ids = [
        row["construct_id"]
        for row in mapped["construct_ledger"]
        if row["classification"]
        in {"partially_supported", "recognized_but_unsupported", "unrecognized"}
    ]
    expected_recovery_ids = [
        row["construct_id"]
        for row in mapped["construct_ledger"]
        if row["classification"] == "malformed"
    ]
    if len(unsupported_region_ids) != len(set(unsupported_region_ids)) or set(
        unsupported_region_ids
    ) != set(expected_unsupported_ids):
        raise OpenQASM3EvidenceError("sidecar_unsupported_region_coverage_invalid")
    if recovery_ids != expected_recovery_ids:
        raise OpenQASM3EvidenceError("sidecar_recovery_coverage_invalid")

    if not isinstance(mapped["modifier_chains"], list):
        raise OpenQASM3EvidenceError("sidecar_modifier_chains_invalid")
    for row in mapped["modifier_chains"]:
        item = _exact_keys(row, {"construct_id", "modifiers"}, "sidecar_modifier_chain_invalid")
        if item["construct_id"] not in construct_ids or not isinstance(item["modifiers"], list):
            raise OpenQASM3EvidenceError("sidecar_modifier_chain_invalid")
        modifier_construct = constructs_by_id[item["construct_id"]]
        if (
            modifier_construct["family"] not in {"quantum_operation", "custom_gate_call"}
            or modifier_construct["classification"]
            not in {"supported", "partially_supported", "recognized_but_unsupported"}
            or not item["modifiers"]
        ):
            raise OpenQASM3EvidenceError("sidecar_modifier_chain_invalid")
        for modifier in item["modifiers"]:
            mod = _exact_keys(
                modifier,
                {"name", "argument", "support"},
                "sidecar_modifier_invalid",
            )
            if (
                mod["name"] not in {"inv", "ctrl", "negctrl", "pow"}
                or mod["support"] not in SUPPORT_STATES
                or (mod["argument"] is not None and not isinstance(mod["argument"], str))
            ):
                raise OpenQASM3EvidenceError("sidecar_modifier_invalid")

    if not isinstance(mapped["custom_gates"], list):
        raise OpenQASM3EvidenceError("sidecar_custom_gates_invalid")
    custom_names: set[str] = set()
    for row in mapped["custom_gates"]:
        item = _exact_keys(
            row,
            {
                "name",
                "parameter_arity",
                "qubit_arity",
                "declaration_construct_id",
                "support",
                "body_call_names",
            },
            "sidecar_custom_gate_invalid",
        )
        if (
            not isinstance(item["name"], str)
            or item["name"] in custom_names
            or type(item["parameter_arity"]) is not int
            or item["parameter_arity"] < 0
            or type(item["qubit_arity"]) is not int
            or item["qubit_arity"] < 1
            or item["declaration_construct_id"] not in construct_ids
            or item["support"] not in SUPPORT_STATES
        ):
            raise OpenQASM3EvidenceError("sidecar_custom_gate_invalid")
        custom_names.add(item["name"])
        declaration = constructs_by_id[item["declaration_construct_id"]]
        if (
            declaration["family"] != "custom_gate_declaration"
            or declaration["name"] != item["name"]
        ):
            raise OpenQASM3EvidenceError("sidecar_custom_gate_declaration_mismatch")
        _string_list(item["body_call_names"], "sidecar_custom_gate_calls_invalid")

    if not isinstance(mapped["measurements"], list):
        raise OpenQASM3EvidenceError("sidecar_measurements_invalid")
    quantum_width = sum(row["size"] for row in mapped["quantum_declarations"])
    classical_width = sum(row["size"] for row in mapped["classical_declarations"])
    for row in mapped["measurements"]:
        item = _exact_keys(
            row,
            {"construct_id", "form", "quantum_targets", "classical_targets", "exactness", "span"},
            "sidecar_measurement_invalid",
        )
        if (
            item["construct_id"] not in construct_ids
            or item["form"] not in {"assignment", "declaration", "arrow", "unassigned"}
            or item["exactness"] not in EXACTNESS_STATES
            or not isinstance(item["quantum_targets"], list)
            or not isinstance(item["classical_targets"], list)
            or any(type(index) is not int or index < 0 for index in item["quantum_targets"])
            or any(type(index) is not int or index < 0 for index in item["classical_targets"])
        ):
            raise OpenQASM3EvidenceError("sidecar_measurement_invalid")
        if any(index >= quantum_width for index in item["quantum_targets"]) or any(
            index >= classical_width for index in item["classical_targets"]
        ):
            raise OpenQASM3EvidenceError("sidecar_measurement_target_out_of_range")
        if item["exactness"] == "exact":
            if not item["quantum_targets"]:
                raise OpenQASM3EvidenceError("sidecar_measurement_relationship_invalid")
            if item["form"] == "unassigned":
                if item["classical_targets"]:
                    raise OpenQASM3EvidenceError("sidecar_measurement_relationship_invalid")
            elif not item["classical_targets"] or len(item["quantum_targets"]) != len(
                item["classical_targets"]
            ):
                raise OpenQASM3EvidenceError("sidecar_measurement_relationship_invalid")
        _span(item["span"])
        if item["span"] != constructs_by_id[item["construct_id"]]["span"]:
            raise OpenQASM3EvidenceError("sidecar_measurement_span_invalid")

    if not isinstance(mapped["diagnostics"], list):
        raise OpenQASM3EvidenceError("sidecar_diagnostics_invalid")
    for row in mapped["diagnostics"]:
        item = _exact_keys(
            row,
            {"category", "severity", "construct_id", "span", "message"},
            "sidecar_diagnostic_invalid",
        )
        if (
            item["category"] not in DIAGNOSTIC_CATEGORIES
            or item["severity"] not in {"limitation", "error", "fatal"}
            or (item["construct_id"] is not None and item["construct_id"] not in construct_ids)
            or not isinstance(item["message"], str)
            or not item["message"]
        ):
            raise OpenQASM3EvidenceError("sidecar_diagnostic_invalid")
        _span(item["span"])
        if (
            item["construct_id"] is not None
            and item["span"] != constructs_by_id[item["construct_id"]]["span"]
        ):
            raise OpenQASM3EvidenceError("sidecar_diagnostic_span_invalid")

    construct_order = {
        row["construct_id"]: index for index, row in enumerate(mapped["construct_ledger"])
    }
    malformed_diagnostic_ids = {
        row["construct_id"]
        for row in mapped["diagnostics"]
        if row["category"] == "malformed_syntax" and row["construct_id"] is not None
    }
    for annotation in (row for row in mapped["construct_ledger"] if row["family"] == "annotation"):
        prefix = "The annotation is associated with following "
        associations = [
            item[len(prefix) : -1]
            for item in annotation["established"]
            if item.startswith(prefix) and item.endswith(".")
        ]
        if not associations:
            if annotation["construct_id"] not in malformed_diagnostic_ids:
                raise OpenQASM3EvidenceError("sidecar_annotation_relationship_invalid")
            continue
        if len(associations) != 1 or associations[0] not in constructs_by_id:
            raise OpenQASM3EvidenceError("sidecar_annotation_relationship_invalid")
        target = constructs_by_id[associations[0]]
        annotation_index = construct_order[annotation["construct_id"]]
        target_index = construct_order[associations[0]]
        if (
            target_index <= annotation_index
            or target["family"] in {"annotation", "pragma"}
            or any(
                row["family"] not in {"annotation"}
                for row in mapped["construct_ledger"][annotation_index + 1 : target_index]
            )
        ):
            raise OpenQASM3EvidenceError("sidecar_annotation_relationship_invalid")

    facts = _exact_keys(
        mapped["derived_facts"],
        {
            "quantum_width",
            "classical_width",
            "operation_count",
            "measurement_count",
            "depth",
            "interaction_graph",
            "gate_statistics",
        },
        "sidecar_derived_facts_invalid",
    )
    for key in (
        "quantum_width",
        "classical_width",
        "operation_count",
        "measurement_count",
        "depth",
    ):
        _fact(facts[key])
    graph = _fact(facts["interaction_graph"], allow_mapping=True)
    if not isinstance(graph["value"], list):
        raise OpenQASM3EvidenceError("sidecar_interaction_graph_invalid")
    for edge in graph["value"]:
        if (
            not isinstance(edge, list)
            or len(edge) != 2
            or any(type(index) is not int or index < 0 for index in edge)
            or edge[0] >= edge[1]
        ):
            raise OpenQASM3EvidenceError("sidecar_interaction_graph_invalid")
        if edge[1] >= quantum_width:
            raise OpenQASM3EvidenceError("sidecar_interaction_graph_target_out_of_range")
    stats = _fact(facts["gate_statistics"], allow_mapping=True)
    if not isinstance(stats["value"], Mapping) or any(
        not isinstance(key, str) or type(count) is not int or count < 0
        for key, count in stats["value"].items()
    ):
        raise OpenQASM3EvidenceError("sidecar_gate_statistics_invalid")

    scalar_fact_names = (
        "quantum_width",
        "classical_width",
        "operation_count",
        "measurement_count",
        "depth",
    )
    if mapped["file_status"] == "fatal":
        if any(
            facts[name]["value"] is not None or facts[name]["exactness"] != "not_established"
            for name in scalar_fact_names
        ):
            raise OpenQASM3EvidenceError("sidecar_fatal_fact_semantics_invalid")
        if graph != {"value": [], "exactness": "not_established"} or stats != {
            "value": {},
            "exactness": "not_established",
        }:
            raise OpenQASM3EvidenceError("sidecar_fatal_fact_semantics_invalid")
    elif mapped["file_status"] == "partial":
        independently_nonexecuting_families = {
            "include",
            "input_declaration",
            "output_declaration",
            "pragma",
            "annotation",
        }
        execution_may_be_incomplete = any(
            row["classification"] != "supported"
            and row["family"] not in independently_nonexecuting_families
            for row in mapped["construct_ledger"]
        )
        permitted_count_exactness = (
            {"lower_bound", "not_established"}
            if execution_may_be_incomplete
            else {"exact", "lower_bound", "not_established"}
        )
        if facts["operation_count"]["exactness"] not in permitted_count_exactness:
            raise OpenQASM3EvidenceError("sidecar_partial_fact_semantics_invalid")
        if facts["measurement_count"]["exactness"] not in permitted_count_exactness:
            raise OpenQASM3EvidenceError("sidecar_partial_fact_semantics_invalid")
        if facts["depth"]["exactness"] != "not_established":
            raise OpenQASM3EvidenceError("sidecar_partial_fact_semantics_invalid")
        if graph["exactness"] not in {"partial", "not_established"}:
            raise OpenQASM3EvidenceError("sidecar_partial_fact_semantics_invalid")
        if stats["exactness"] not in {"partial", "not_established"}:
            raise OpenQASM3EvidenceError("sidecar_partial_fact_semantics_invalid")
    elif any(
        facts[name]["exactness"] != "exact"
        for name in ("quantum_width", "classical_width", "operation_count", "measurement_count")
    ):
        raise OpenQASM3EvidenceError("sidecar_supported_fact_semantics_invalid")

    if (
        not isinstance(mapped["parser_limits"], Mapping)
        or tuple(mapped["parser_limits"]) != LIMIT_KEYS
    ):
        raise OpenQASM3EvidenceError("sidecar_parser_limits_invalid")
    for name, row in mapped["parser_limits"].items():
        limit = _exact_keys(row, {"maximum", "observed", "status"}, "sidecar_limit_invalid")
        if (
            type(limit["maximum"]) is not int
            or limit["maximum"] < 1
            or type(limit["observed"]) is not int
            or limit["observed"] < 0
            or limit["status"] not in {"within_limit", "exceeded"}
            or (limit["observed"] <= limit["maximum"]) != (limit["status"] == "within_limit")
        ):
            raise OpenQASM3EvidenceError(f"sidecar_limit_invalid:{name}")
    if any(
        mapped["parser_limits"][name]["maximum"] != maximum
        for name, maximum in PARSER_LIMIT_MAXIMA.items()
    ):
        raise OpenQASM3EvidenceError("sidecar_limit_contract_invalid")
    observed_contract = {
        "declarations": len(mapped["quantum_declarations"]) + len(mapped["classical_declarations"]),
        "operations": (
            facts["operation_count"]["value"]
            if facts["operation_count"]["exactness"] == "exact"
            else mapped["parser_limits"]["operations"]["observed"]
        ),
        "custom_gates": len(mapped["custom_gates"]),
        "modifier_depth": max(
            (len(row["modifiers"]) for row in mapped["modifier_chains"]), default=0
        ),
        "recovery_events": len(mapped["recovery_ledger"]),
        "diagnostics": len(mapped["diagnostics"]),
        "construct_ledger_entries": len(mapped["construct_ledger"]),
        "individual_quantum_width": max(
            (row["size"] for row in mapped["quantum_declarations"]), default=0
        ),
        "total_quantum_width": quantum_width,
        "individual_classical_width": max(
            (row["size"] for row in mapped["classical_declarations"]), default=0
        ),
        "total_classical_width": classical_width,
    }
    if any(
        mapped["parser_limits"][name]["observed"] != observed
        for name, observed in observed_contract.items()
        if mapped["parser_limits"][name]["status"] == "within_limit"
    ):
        raise OpenQASM3EvidenceError("sidecar_limit_observation_inconsistent")
    any_limit_exceeded = any(
        row["status"] == "exceeded" for row in mapped["parser_limits"].values()
    )
    if mapped["file_status"] == "supported" and any_limit_exceeded:
        raise OpenQASM3EvidenceError("sidecar_supported_limit_exceeded")

    circuit_ir = mapped["circuit_ir"]
    if circuit_ir is not None:
        ir = _exact_keys(
            circuit_ir,
            {"source_format", "n_qubits", "n_cbits", "qregs", "operations", "complete"},
            "sidecar_circuit_ir_invalid",
        )
        if mapped["file_status"] != "supported" or ir["complete"] is not True:
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_completeness_invalid")
        if ir["source_format"] != "qasm3":
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_invalid")
        if (
            any(type(ir[key]) is not int or ir[key] < 0 for key in ("n_qubits", "n_cbits"))
            or not isinstance(ir["qregs"], list)
            or not isinstance(ir["operations"], list)
        ):
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_invalid")
        expected_base = 0
        for qreg in ir["qregs"]:
            register = _exact_keys(
                qreg, {"name", "size", "base"}, "sidecar_circuit_ir_register_invalid"
            )
            if (
                not isinstance(register["name"], str)
                or not register["name"]
                or type(register["size"]) is not int
                or register["size"] < 1
                or type(register["base"]) is not int
                or register["base"] != expected_base
            ):
                raise OpenQASM3EvidenceError("sidecar_circuit_ir_register_invalid")
            expected_base += register["size"]
        if expected_base != ir["n_qubits"]:
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_register_invalid")
        if ir["qregs"] != [
            {"name": row["name"], "size": row["size"], "base": row["base"]}
            for row in mapped["quantum_declarations"]
        ]:
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_register_mismatch")
        operations: list[Mapping[str, Any]] = []
        for operation in ir["operations"]:
            item = _exact_keys(
                operation,
                {
                    "name",
                    "qubits",
                    "params",
                    "is_measure",
                    "is_barrier",
                    "is_reset",
                    "is_custom",
                },
                "sidecar_circuit_ir_operation_invalid",
            )
            if (
                not isinstance(item["name"], str)
                or not item["name"]
                or not isinstance(item["qubits"], list)
                or any(
                    type(index) is not int or index < 0 or index >= ir["n_qubits"]
                    for index in item["qubits"]
                )
                or not isinstance(item["params"], list)
                or any(not isinstance(parameter, str) for parameter in item["params"])
                or any(
                    not isinstance(item[key], bool)
                    for key in ("is_measure", "is_barrier", "is_reset", "is_custom")
                )
                or sum(
                    bool(item[key]) for key in ("is_measure", "is_barrier", "is_reset", "is_custom")
                )
                > 1
                or (item["is_measure"] != (item["name"] == "measure"))
                or (item["is_barrier"] != (item["name"] == "barrier"))
                or (item["is_reset"] != (item["name"] == "reset"))
            ):
                raise OpenQASM3EvidenceError("sidecar_circuit_ir_operation_invalid")
            operations.append(item)
        if mapped["modifier_chains"]:
            raise OpenQASM3EvidenceError("sidecar_modifier_circuit_ir_prohibited")
        if any(row["family"] == "custom_gate_call" for row in mapped["construct_ledger"]):
            raise OpenQASM3EvidenceError("sidecar_custom_call_circuit_ir_prohibited")
        if (
            ir["n_qubits"] != facts["quantum_width"]["value"]
            or ir["n_cbits"] != facts["classical_width"]["value"]
            or len(ir["operations"]) != facts["operation_count"]["value"]
            or sum(operation.get("name") == "measure" for operation in ir["operations"])
            != facts["measurement_count"]["value"]
        ):
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_fact_mismatch")
        operation_counts = Counter(str(operation["name"]) for operation in operations)
        if dict(sorted(operation_counts.items())) != dict(facts["gate_statistics"]["value"]):
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_gate_statistics_mismatch")
        expected_edges = sorted(
            {
                (min(left, right), max(left, right))
                for operation in operations
                if not (
                    operation["is_measure"]
                    or operation["is_barrier"]
                    or operation["is_reset"]
                    or operation["is_custom"]
                )
                for offset, left in enumerate(operation["qubits"])
                for right in operation["qubits"][offset + 1 :]
                if left != right
            }
        )
        if [list(edge) for edge in expected_edges] != graph["value"]:
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_interaction_mismatch")
        frontier = [0] * max(ir["n_qubits"], 1)
        for operation in operations:
            if (
                operation["is_measure"]
                or operation["is_barrier"]
                or operation["is_reset"]
                or not operation["qubits"]
            ):
                continue
            level = 1 + max(frontier[index] for index in operation["qubits"])
            for index in operation["qubits"]:
                frontier[index] = level
        if facts["depth"] != {"value": max(frontier), "exactness": "exact"}:
            raise OpenQASM3EvidenceError("sidecar_circuit_ir_depth_mismatch")
    if mapped["file_status"] != "supported" and circuit_ir is not None:
        raise OpenQASM3EvidenceError("sidecar_partial_circuit_ir_prohibited")

    if (
        facts["quantum_width"]["value"] is not None
        and facts["quantum_width"]["value"] != quantum_width
    ):
        raise OpenQASM3EvidenceError("sidecar_quantum_width_fact_mismatch")
    if (
        facts["classical_width"]["value"] is not None
        and facts["classical_width"]["value"] != classical_width
    ):
        raise OpenQASM3EvidenceError("sidecar_classical_width_fact_mismatch")
    exact_measurements = sum(
        len(row["quantum_targets"]) for row in mapped["measurements"] if row["exactness"] == "exact"
    )
    if (
        facts["measurement_count"]["exactness"] == "exact"
        and facts["measurement_count"]["value"] != exact_measurements
    ):
        raise OpenQASM3EvidenceError("sidecar_measurement_fact_mismatch")
    if facts["operation_count"]["value"] is not None and (
        facts["operation_count"]["value"] != mapped["parser_limits"]["operations"]["observed"]
        or sum(facts["gate_statistics"]["value"].values()) != facts["operation_count"]["value"]
    ):
        raise OpenQASM3EvidenceError("sidecar_operation_fact_mismatch")
    supported_operation_names = {
        row["name"]
        for row in mapped["construct_ledger"]
        if row["classification"] == "supported"
        and row["family"]
        in {"quantum_operation", "custom_gate_call", "measurement", "reset", "barrier"}
    } | ({"measure"} if mapped["measurements"] else set())
    if set(facts["gate_statistics"]["value"]) - supported_operation_names:
        raise OpenQASM3EvidenceError("sidecar_gate_statistics_ledger_mismatch")

    _string_list(mapped["limitations"], "sidecar_limitations_invalid")
    if tuple(mapped["non_claims"]) != NON_CLAIMS:
        raise OpenQASM3EvidenceError("sidecar_non_claims_invalid")
    fixed_false = (
        "raw_source_included",
        "source_or_circuit_executed",
        "repository_scanned",
        "network_accessed",
        "motif_evidence_emitted",
        "intent_inferred",
    )
    if any(mapped[key] is not False for key in fixed_false):
        raise OpenQASM3EvidenceError("sidecar_boundary_invalid")
    if mapped["file_status"] == "supported" and any(
        row["classification"] != "supported" for row in mapped["construct_ledger"]
    ):
        raise OpenQASM3EvidenceError("sidecar_file_aggregation_invalid")
    if mapped["file_status"] == "partial" and not any(
        row["classification"] != "supported" for row in mapped["construct_ledger"]
    ):
        raise OpenQASM3EvidenceError("sidecar_file_aggregation_invalid")
    _validate_privacy(mapped)
    if source_bytes is None:
        if artifact_label is not None:
            raise OpenQASM3EvidenceError("openqasm3_source_bytes_required")
        return "standalone_structural_internal"
    if not isinstance(source_bytes, bytes):
        raise OpenQASM3EvidenceError("openqasm3_source_bytes_invalid")
    if not isinstance(artifact_label, str) or not artifact_label:
        raise OpenQASM3EvidenceError("openqasm3_source_artifact_label_required")
    if hashlib.sha256(source_bytes).hexdigest() != mapped["source_sha256"]:
        raise OpenQASM3EvidenceError("openqasm3_source_digest_mismatch")
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        source_text = ""
    source_lines = source_text.splitlines() or [""]

    def check_source_spans(item: object) -> None:
        if isinstance(item, Mapping):
            if set(item) == {"start_line", "start_column", "end_line", "end_column"}:
                start_line = item["start_line"]
                end_line = item["end_line"]
                if start_line > len(source_lines) or end_line > len(source_lines):
                    raise OpenQASM3EvidenceError("sidecar_source_span_out_of_bounds")
                if (
                    item["start_column"] > len(source_lines[start_line - 1]) + 1
                    or item["end_column"] > len(source_lines[end_line - 1]) + 1
                ):
                    raise OpenQASM3EvidenceError("sidecar_source_span_out_of_bounds")
                return
            for child in item.values():
                check_source_spans(child)
        elif isinstance(item, list):
            for child in item:
                check_source_spans(child)

    check_source_spans(mapped)
    # Local import avoids a module cycle.  The internal builder performs only
    # standalone validation; source-bound validation therefore cannot recurse.
    from .openqasm3_bounded_parser import _build_openqasm3_evidence

    reconstructed = _build_openqasm3_evidence(source_bytes, artifact_label=artifact_label)

    def collect_spans(item: object, path: str = "$") -> dict[str, object]:
        result: dict[str, object] = {}
        if isinstance(item, Mapping):
            if set(item) == {"start_line", "start_column", "end_line", "end_column"}:
                result[path] = dict(item)
            else:
                for key, child in item.items():
                    result.update(collect_spans(child, f"{path}.{key}"))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                result.update(collect_spans(child, f"{path}[{index}]"))
        return result

    if collect_spans(mapped) != collect_spans(reconstructed.sidecar):
        raise OpenQASM3EvidenceError("sidecar_source_span_content_mismatch")
    if mapped["modifier_chains"] != reconstructed.sidecar["modifier_chains"]:
        raise OpenQASM3EvidenceError("sidecar_source_modifier_binding_mismatch")
    if dict(mapped) != reconstructed.sidecar:
        raise OpenQASM3EvidenceError("openqasm3_source_semantic_mismatch")
    return "source_bound"


def openqasm3_sidecar_without_ir(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy without the optional complete CircuitIR projection."""

    validate_openqasm3_static_evidence(value)
    result = deepcopy(dict(value))
    result["circuit_ir"] = None
    return result


def render_openqasm3_static_evidence_markdown(value: Mapping[str, Any]) -> str:
    """Render the sidecar deterministically without source text or local paths."""

    validate_openqasm3_static_evidence(value)
    lines = [
        "# OpenQASM 3 static evidence",
        "",
        f"- Schema: `{value['schema_id']}`",
        f"- Parser: `{value['parser_identity']}`",
        f"- Standard-gate vocabulary: `{value['standard_gate_vocabulary_identity']}`",
        f"- Declared version: `{value['declared_language_version']}`",
        f"- Selected artifact: `{value['artifact_label']}`",
        f"- Source SHA-256: `{value['source_sha256']}`",
        f"- Support status: `{value['file_status']}`",
        "- Selection: explicit file argument",
        "",
        "## Established declarations",
        "",
    ]
    declarations = [("qubit", row) for row in value["quantum_declarations"]] + [
        ("bit", row) for row in value["classical_declarations"]
    ]
    if declarations:
        lines.extend(
            f"- {kind} `{row['name']}`: size `{row['size']}`, base `{row['base']}` ({row['support']})"
            for kind, row in declarations
        )
    else:
        lines.append("- None established.")
    lines += ["", "## Construct classifications", ""]
    if value["construct_ledger"]:
        lines.extend(
            f"- `{row['construct_id']}` {row['family']} `{row['name']}`: `{row['classification']}`"
            for row in value["construct_ledger"]
        )
    else:
        lines.append("- No bounded construct occurrence was established.")
    lines += ["", "## Derived facts", ""]
    for name, fact in value["derived_facts"].items():
        rendered = json.dumps(fact["value"], ensure_ascii=False, sort_keys=True)
        lines.append(f"- {name}: `{rendered}` — `{fact['exactness']}`")
    lines += ["", "## Limitations", ""]
    lines.extend(f"- {item}" for item in value["limitations"])
    lines += ["", "## Non-claims", ""]
    lines.extend(f"- {item}" for item in value["non_claims"])
    lines += ["", "This evidence was produced without executing the source or circuit.", ""]
    return "\n".join(lines)
