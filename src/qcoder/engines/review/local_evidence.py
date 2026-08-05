"""Coherent OSS-local review of explicitly selected evidence artifacts.

This module is a presentation/composition layer.  It reuses canonical qCoder
artifacts and deliberately owns no evidence registry, project index, watcher,
network client, or persistent state.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import shlex
from typing import Any, Mapping, Sequence

from qcoder.algorithm_blueprint import artifact_digest_matches
from qcoder.context_loop import (
    CIRCUIT_MANIFESTATION_SCHEMA_ID,
    RESULT_MANIFESTATION_SCHEMA_ID,
    build_circuit_manifestation,
    build_result_manifestation,
)
from qcoder.core.share_safe import make_share_safe_payload
from qcoder.current_loop_quiet_workflow import local_evidence_help_response
from qcoder.current_loop_run_summary import (
    RUN_SUMMARY_SCHEMA_ID,
    build_run_summary,
    run_summary_error,
)
from qcoder.development_evidence import (
    DEVELOPMENT_EVIDENCE_SCHEMA_ID,
    MOTIF_REGISTRY,
    PROFILE_IDS,
    SOURCE_EVIDENCE_DEPTH_GATE,
    extract_qiskit_source_development_evidence,
    validate_development_evidence,
)
from qcoder.engines.feature_extraction.qasm2_regex_parser import parse_qasm2_text
from qcoder.engines.review.counts_v0 import normalize_counts_v0
from qcoder.engines.review.qiskit_counts import normalize_qiskit_counts_payload


MAX_SELECTED_FILES = 8
MAX_JSON_BYTES = 1_048_576
REPORT_SECTION_ORDER = (
    "review_scope",
    "provenance",
    "qasm_evidence",
    "circuit_facts",
    "motif_evidence",
    "factual_run_summary",
    "revision_evidence",
    "warnings_and_unsupported",
    "bounded_local_planning_guidance",
    "share_safe_export",
    "supported_next_actions",
    "local_qcoder_help",
)
SHARE_SAFE_OPT_IN_CATEGORIES = (
    "source_excerpts",
    "original_qasm",
    "normalized_circuit_ir",
    "raw_counts",
    "raw_run_result_payloads",
    "blueprint_material",
    "customer_filenames",
    "customer_paths",
)
_QASM2_HEADER = re.compile(
    r"^\s*OPENQASM\s+(?P<version>2(?:\.\d+)?)\s*;", re.IGNORECASE | re.MULTILINE
)
_QASM3_HEADER = re.compile(
    r"^\s*OPENQASM\s+(?P<version>3(?:\.\d+)?)\s*;", re.IGNORECASE | re.MULTILINE
)
_QASM2_KNOWN_OPERATIONS = frozenset(
    {
        "u",
        "u0",
        "u1",
        "u2",
        "u3",
        "id",
        "x",
        "y",
        "z",
        "h",
        "s",
        "sdg",
        "t",
        "tdg",
        "rx",
        "ry",
        "rz",
        "cx",
        "cy",
        "cz",
        "ch",
        "ccx",
        "crz",
        "cu1",
        "cu3",
        "swap",
        "cswap",
        "measure",
        "barrier",
        "reset",
    }
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)(?P<prefix>['\"]?\b(?:api[_-]?key|authorization|cookie|credential|password|secret|session|token)\b['\"]?\s*[:=]\s*)(?P<value>[^\s,;]+|['\"][^'\"\n]*['\"])",
)
_UNNECESSARY_SHARE_SAFE_IDENTITY_KEYS = frozenset(
    {
        "artifact_ref",
        "artifact_reference",
        "artifact_revision_bindings",
        "artifact_revision_digests",
        "evidence_bindings",
        "evidence_snapshot_id",
        "help_digest",
        "loop_ref",
        "manifestation_revision_bindings",
        "operation_lineage",
        "reference_id",
        "related_artifact_references",
        "related_circuit_ref",
        "circuit_reference",
        "result_evidence_reference",
        "workspace_binding",
    }
)
_DEFAULT_EXCLUDED_RAW_KEYS = frozenset({"counts", "raw_result", "sampled_bitstrings", "samples"})


class LocalEvidenceError(ValueError):
    """An ordinary, customer-actionable local evidence input error."""


def _qcoder_version() -> str:
    from qcoder import __version__

    return __version__


def _reference(position: int, suffix: int) -> str:
    value = position * 16 + suffix
    return f"session-artifact-{value:032x}"


def _display_command(path: str, *, extra: Sequence[str] = ()) -> str:
    argv = ["qcoder", "review", "local-evidence", path, *extra]
    return " ".join(shlex.quote(item) for item in argv)


def _selected_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.exists():
        raise LocalEvidenceError(f"selected input does not exist: {value}")
    if not path.is_file():
        raise LocalEvidenceError(
            f"selected input must be a file; directories, globs, and recursive discovery are not supported: {value}"
        )
    if any(part.startswith(".") and part not in {".", ".."} for part in path.parts):
        raise LocalEvidenceError(f"hidden files are not accepted by this workflow: {value}")
    return path.resolve()


def resolve_explicit_files(paths: Sequence[str]) -> list[Path]:
    if not paths:
        raise LocalEvidenceError("select at least one evidence file")
    if len(paths) > MAX_SELECTED_FILES:
        raise LocalEvidenceError(
            f"explicit collection limit exceeded: select at most {MAX_SELECTED_FILES} files"
        )
    selected = [_selected_path(item) for item in paths]
    if len(selected) != len(set(selected)):
        raise LocalEvidenceError("the explicit collection contains a duplicate file")
    return sorted(selected, key=lambda item: str(item))


def _read_text(path: Path, *, maximum: int) -> str:
    if path.stat().st_size > maximum:
        raise LocalEvidenceError(f"selected input exceeds the {maximum}-byte limit: {path.name}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise LocalEvidenceError(f"selected input must be UTF-8 text: {path.name}") from exc


def _canonical_item(
    *,
    position: int,
    path: Path,
    input_kind: str,
    status: str,
    inspected: Sequence[str],
    established: Sequence[str],
    not_established: Sequence[str],
    limitations: Sequence[str],
    next_actions: Sequence[str],
    canonical_artifacts: Sequence[Mapping[str, Any]] = (),
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "position": position,
        "input": {
            "kind": input_kind,
            "selected_source": str(path),
            "customer_filename": path.name,
            "selection": "explicit_file_argument",
        },
        "status": status,
        "inspected": list(inspected),
        "deliberately_not_inspected": [
            "other files",
            "directories",
            "hidden files",
            "imports or dependencies",
            "workspace or repository state",
            "network or hosted services",
        ],
        "established": list(established),
        "not_established": list(not_established),
        "limitations": list(limitations),
        "warnings": list(warnings),
        "canonical_artifacts": [deepcopy(dict(item)) for item in canonical_artifacts],
        "supported_next_actions": list(next_actions),
    }


def _review_python(path: Path, position: int, *, profile_id: str) -> dict[str, Any]:
    source = _read_text(path, maximum=100_000)
    evidence = extract_qiskit_source_development_evidence(
        source,
        logical_source_label=path.name,
        source_reference_id=_reference(position, 1),
        blueprint_reference_id=_reference(position, 2),
        profile_id=profile_id,
        expected_requirements=(),
        source_evidence_depth=SOURCE_EVIDENCE_DEPTH_GATE,
    )
    observations = [
        item
        for item in evidence.get("motif_observations", [])
        if item.get("observation_status") in {"observed", "ambiguous"}
    ]
    motif_ids = [str(item.get("motif_id")) for item in observations]
    limitations = [str(item) for item in evidence.get("non_proofs", [])]
    limitations.extend(str(item) for item in evidence.get("unresolved_questions", []))
    established = [
        "The explicitly selected Python file was parsed with bounded static AST inspection.",
        f"Observed motif structures: {', '.join(motif_ids) if motif_ids else 'none'}.",
    ]
    return _canonical_item(
        position=position,
        path=path,
        input_kind="python_qiskit_source",
        status=("established_with_qualifications" if observations else "partial"),
        inspected=("Python syntax", "bounded Qiskit source structure", "Python-only motifs"),
        established=established,
        not_established=(
            "Constructed circuit behavior, runtime behavior, and result causation were not established.",
            "A structural Grover or QAOA match does not establish complete or correct algorithm identity.",
        ),
        limitations=limitations,
        next_actions=(
            _display_command(
                str(path),
                extra=("--python-profile", profile_id, "--out-json", "local-evidence.json"),
            ),
            "Supply an exported OpenQASM 2 file to review constructed circuit facts.",
            "Supply counts JSON to review factual run results.",
        ),
        canonical_artifacts=(evidence,),
    )


def _qasm_format(text: str) -> str:
    if _QASM3_HEADER.search(text):
        return "openqasm_3"
    if _QASM2_HEADER.search(text):
        return "openqasm_2"
    return "unknown_qasm"


def _declared_qasm_version(text: str) -> str | None:
    for pattern in (_QASM2_HEADER, _QASM3_HEADER):
        match = pattern.search(text)
        if match:
            return str(match.group("version"))
    return None


def _ir_projection(text: str) -> dict[str, Any]:
    ir = parse_qasm2_text(text)
    return {
        "source_format": ir.source_format,
        "n_qubits": ir.n_qubits,
        "n_cbits": ir.n_cbits,
        "qregs": [{"name": item.name, "size": item.size, "base": item.base} for item in ir.qregs],
        "operations": [
            {
                "name": item.name,
                "qubits": list(item.qubits),
                "params": list(item.params),
                "is_measure": item.is_measure,
                "is_barrier": item.is_barrier,
                "is_reset": item.is_reset,
                "is_custom": item.is_custom,
            }
            for item in ir.operations
        ],
    }


def _review_qasm(path: Path, position: int) -> dict[str, Any]:
    text = _read_text(path, maximum=100_000)
    qasm_format = _qasm_format(text)
    declared_version = _declared_qasm_version(text)
    if qasm_format == "openqasm_3":
        return _canonical_item(
            position=position,
            path=path,
            input_kind="openqasm_3",
            status="unsupported",
            inspected=("OpenQASM version header only",),
            established=(f"The explicitly selected input declares OpenQASM {declared_version}.",),
            not_established=(
                "No circuit facts were extracted.",
                "OpenQASM 3 parsing and evidence extraction are not supported in this package.",
            ),
            limitations=(
                "The input was not passed to the bounded OpenQASM 2 parser.",
                "No constructs were discarded or represented as a complete circuit.",
            ),
            next_actions=(
                "Supply a supported OpenQASM 2 artifact.",
                "Supply explicitly selected Python/Qiskit source or supported counts JSON.",
            ),
        )
    if qasm_format != "openqasm_2":
        return _canonical_item(
            position=position,
            path=path,
            input_kind="qasm_unknown_version",
            status="unsupported",
            inspected=("QASM version header only",),
            established=("No supported OpenQASM 2 or recognized OpenQASM 3 header was found.",),
            not_established=("No circuit facts were extracted.",),
            limitations=("Only bounded OpenQASM 2 evidence extraction is supported.",),
            next_actions=("Supply a valid OpenQASM 2 artifact with an OPENQASM 2.x header.",),
        )
    manifestation = build_circuit_manifestation(
        qasm_text=text,
        stage="logical_circuit",
        artifact_ref=_reference(position, 3),
    )
    ir = parse_qasm2_text(text)
    unknown_operations = sorted(
        {
            operation.name
            for operation in ir.operations
            if operation.is_custom
            or (
                operation.name not in _QASM2_KNOWN_OPERATIONS
                and not operation.is_measure
                and not operation.is_barrier
                and not operation.is_reset
            )
        }
    )
    warnings = (
        [
            "Custom or unknown operation categories were retained with qualified semantics: "
            + ", ".join(unknown_operations)
            + "."
        ]
        if unknown_operations
        else []
    )
    facts = manifestation["structural_metrics"]
    return _canonical_item(
        position=position,
        path=path,
        input_kind="openqasm_2",
        status=("partial" if unknown_operations else "established_with_qualifications"),
        inspected=(
            "OpenQASM 2 declarations",
            "registers",
            "operations",
            "measurements",
            "bounded CircuitIR structure",
        ),
        established=(
            f"The input declares OpenQASM {declared_version}.",
            f"Circuit width {facts['width']}, depth {facts['depth']}, operation count {facts['operation_count']}, and measurement count {facts['measurement_count']} were deterministically established within parser bounds.",
        ),
        not_established=(
            "Circuit correctness, runtime behavior, output-state entanglement, and algorithm identity were not established.",
            "No motif evidence was inferred from QASM.",
        ),
        limitations=tuple(manifestation["parser_limitations"]),
        warnings=warnings,
        next_actions=(
            _display_command(str(path), extra=("--out-json", "local-evidence.json")),
            "Supply counts JSON separately to review supplied run evidence.",
        ),
        canonical_artifacts=(manifestation,),
    )


def _counts_payload(data: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if data.get("schema") == "qcoder.counts.v0":
        normalized = normalize_counts_v0(dict(data))
        return normalized, dict(data)
    if "counts" in data and isinstance(data.get("counts"), Mapping):
        normalized = normalize_qiskit_counts_payload(dict(data))
        return normalized, dict(data)
    if data and all(
        isinstance(key, str) and set(key.replace(" ", "")) <= {"0", "1"} for key in data
    ):
        normalized = normalize_qiskit_counts_payload(dict(data))
        return normalized, dict(data)
    raise LocalEvidenceError("JSON does not contain a supported supplied-counts form")


def _review_counts(path: Path, position: int, data: Mapping[str, Any]) -> dict[str, Any]:
    normalized, result_payload = _counts_payload(data)
    result_payload["counts"] = normalized["counts"]
    declared_shots = data.get("shots")
    if declared_shots is None:
        declared_shots = data.get("shots_total")
    related = _reference(position, 4)
    manifestation = build_result_manifestation(
        counts=normalized["counts"],
        related_circuit_ref=related,
        user_provided_shots=(int(declared_shots) if declared_shots is not None else None),
        safe_outcome_labels=True,
        artifact_ref=_reference(position, 5),
    )
    run_summary = build_run_summary(
        loop_ref="oss-local-evidence-review",
        workspace_binding="explicit-files-only-no-workspace",
        state_revision=0,
        contract_revision=0,
        result_payload=result_payload,
        result_manifestation=manifestation,
        evidence_snapshot_id=f"evidence-snapshot-local-{position:04d}",
    )
    projection = run_summary["count_projection"]
    return _canonical_item(
        position=position,
        path=path,
        input_kind="supplied_counts_or_run_result",
        status="established_with_qualifications",
        inspected=("supplied counts", "supplied execution metadata", "factual Run Summary"),
        established=(
            f"Observed {projection['observed_shots']} supplied shots across {projection['total_observed_outcomes']} outcomes.",
            "Bounded dominant outcomes and supplied execution metadata were normalized factually.",
        ),
        not_established=(
            "qCoder did not execute a backend or simulator.",
            "Correctness, causation, fidelity, backend quality, optimality, and bit-order meaning were not established.",
        ),
        limitations=tuple(run_summary["limitations"]),
        warnings=tuple(run_summary["warnings"])
        + tuple(
            f"Missing supplied metadata: {item}."
            for item in run_summary["missing_execution_fields"]
        ),
        next_actions=(
            _display_command(str(path), extra=("--out-json", "local-evidence.json")),
            "Supply the related OpenQASM 2 artifact as another explicit file to review circuit facts alongside these results.",
        ),
        canonical_artifacts=(manifestation, run_summary),
    )


def _review_canonical_json(path: Path, position: int, data: Mapping[str, Any]) -> dict[str, Any]:
    schema_id = data.get("schema_id")
    error: str | None
    if schema_id == DEVELOPMENT_EVIDENCE_SCHEMA_ID:
        status = validate_development_evidence(dict(data))
        error = None if status == "ok" else status
    elif schema_id == RUN_SUMMARY_SCHEMA_ID:
        error = run_summary_error(data)
    elif schema_id in {CIRCUIT_MANIFESTATION_SCHEMA_ID, RESULT_MANIFESTATION_SCHEMA_ID}:
        error = None if artifact_digest_matches(dict(data)) else "artifact_digest_invalid"
    else:
        return _canonical_item(
            position=position,
            path=path,
            input_kind="qcoder_evidence_json",
            status="unsupported",
            inspected=("JSON schema identity only",),
            established=(f"The supplied schema identity is {schema_id!r}.",),
            not_established=("The artifact was not interpreted as supported evidence.",),
            limitations=(
                "This workflow supports only the listed canonical evidence schema versions.",
            ),
            next_actions=("Use `qcoder review local-evidence --help` to list supported inputs.",),
        )
    if error is not None:
        return _canonical_item(
            position=position,
            path=path,
            input_kind="qcoder_evidence_json",
            status="invalid",
            inspected=("canonical schema and integrity validation",),
            established=(f"The artifact declares {schema_id}.",),
            not_established=("The artifact did not pass canonical validation.",),
            limitations=(f"Validation result: {error}.",),
            next_actions=(
                "Regenerate the artifact with the installed qCoder version and review it again.",
            ),
        )
    revisions = {
        key: deepcopy(data[key])
        for key in (
            "artifact_revision_bindings",
            "manifestation_revision_bindings",
            "currency",
            "freshness",
        )
        if key in data
    }
    return _canonical_item(
        position=position,
        path=path,
        input_kind="qcoder_evidence_json",
        status="established_with_qualifications",
        inspected=(
            "canonical schema identity",
            "canonical integrity fields",
            "retained provenance",
        ),
        established=(f"Canonical {schema_id} validation passed.",),
        not_established=(
            "The prior evidence was not independently reproduced.",
            "No additional project, loop, or runtime facts were inferred.",
        ),
        limitations=(
            "The report preserves only relationships explicitly present in the selected artifact.",
        ),
        next_actions=(_display_command(str(path), extra=("--out-md", "local-evidence.md")),),
        canonical_artifacts=(dict(data), {"explicit_revision_relationships": revisions}),
    )


def _review_execution_review_json(
    path: Path, position: int, data: Mapping[str, Any]
) -> dict[str, Any]:
    version_value = data.get("review_bundle_schema_version")
    valid = (
        version_value == "0.1"
        and data.get("artifact_type") == "qcoder.execution_review"
        and isinstance(data.get("inputs"), Mapping)
        and isinstance(data.get("derived"), Mapping)
        and isinstance(data.get("checks"), list)
        and isinstance(data.get("warnings"), list)
    )
    if not valid:
        return _canonical_item(
            position=position,
            path=path,
            input_kind="qcoder_execution_review_json",
            status="invalid",
            inspected=("execution-review artifact identity and required structure",),
            established=(f"The supplied review version is {version_value!r}.",),
            not_established=("The execution-review artifact did not pass structural validation.",),
            limitations=("Only qCoder execution review bundle version 0.1 is supported.",),
            next_actions=(
                "Regenerate the execution review with the installed qCoder version and review it again.",
            ),
        )
    return _canonical_item(
        position=position,
        path=path,
        input_kind="qcoder_execution_review_json",
        status="established_with_qualifications",
        inspected=("execution-review artifact identity", "derived facts", "checks and warnings"),
        established=(
            "The supplied qCoder execution review bundle version 0.1 is structurally valid.",
        ),
        not_established=(
            "The earlier analysis or supplied run evidence was not independently reproduced.",
        ),
        limitations=(
            "The selected report is presented as user-owned prior evidence; no project relationship is inferred.",
        ),
        next_actions=(_display_command(str(path), extra=("--out-md", "local-evidence.md")),),
        canonical_artifacts=(dict(data),),
    )


def _review_json(path: Path, position: int) -> dict[str, Any]:
    text = _read_text(path, maximum=MAX_JSON_BYTES)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalEvidenceError(f"malformed JSON in {path.name}: {exc.msg}") from exc
    if not isinstance(data, Mapping):
        raise LocalEvidenceError(f"JSON root must be an object: {path.name}")
    if "schema_id" in data:
        return _review_canonical_json(path, position, data)
    if data.get("artifact_type") == "qcoder.execution_review":
        return _review_execution_review_json(path, position, data)
    return _review_counts(path, position, data)


def _review_one(path: Path, position: int, *, profile_id: str) -> dict[str, Any]:
    suffix = path.suffix.casefold()
    if suffix == ".py":
        return _review_python(path, position, profile_id=profile_id)
    if suffix in {".qasm", ".qasm2", ".qasm3"}:
        return _review_qasm(path, position)
    if suffix == ".json":
        return _review_json(path, position)
    return _canonical_item(
        position=position,
        path=path,
        input_kind="unsupported_file_type",
        status="unsupported",
        inspected=("filename extension only",),
        established=(f"The selected file extension is {suffix or '<none>'}.",),
        not_established=("No file content was inspected.",),
        limitations=(
            "Supported inputs are Python, OpenQASM, supplied-counts JSON, and supported qCoder evidence JSON.",
        ),
        next_actions=("Select one explicitly supported file and run the same command.",),
    )


def _help_actions(
    selected: Sequence[Path], items: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    first = str(selected[0])
    actions = [
        {
            "action": "review_again",
            "command": _display_command(first),
            "category": "local_evidence",
        },
        {
            "action": "write_canonical_json",
            "command": _display_command(first, extra=("--out-json", "local-evidence.json")),
            "category": "local_output",
        },
        {
            "action": "write_share_safe_json",
            "command": _display_command(
                first, extra=("--share-safe-json", "local-evidence.share-safe.json")
            ),
            "category": "share_safe_export",
        },
        {
            "action": "show_local_help",
            "command": _display_command(first, extra=("--local-help",)),
            "category": "help",
        },
    ]
    if any(item["input"]["kind"] == "openqasm_3" for item in items):
        actions.insert(
            0,
            {
                "action": "use_supported_alternative",
                "instruction": "Supply OpenQASM 2, explicitly selected Python/Qiskit source, or supported counts JSON.",
                "category": "unsupported_input",
            },
        )
    return actions


def build_local_evidence_review(
    paths: Sequence[str], *, python_profile: str = "generic_qiskit"
) -> dict[str, Any]:
    if python_profile not in PROFILE_IDS:
        raise LocalEvidenceError(f"unsupported Python evidence profile: {python_profile}")
    selected = resolve_explicit_files(paths)
    items = [
        _review_one(path, position, profile_id=python_profile)
        for position, path in enumerate(selected, start=1)
    ]
    statuses = [str(item["status"]) for item in items]
    overall = (
        "completed"
        if all(status in {"established_with_qualifications", "partial"} for status in statuses)
        else "completed_with_unsupported_or_invalid_input"
    )
    kinds = [str(item["input"]["kind"]) for item in items]
    capabilities = sorted({capability for item in items for capability in item["inspected"]})
    unsupported = sorted({statement for item in items for statement in item["not_established"]})
    actions = _help_actions(selected, items)
    help_payload = local_evidence_help_response(
        qcoder_version=_qcoder_version(),
        selected_input_kinds=kinds,
        available_capabilities=capabilities,
        unsupported_capabilities=unsupported,
        report_sections=REPORT_SECTION_ORDER,
        supported_actions=actions,
    )
    return {
        "presentation": "Review local evidence",
        "presentation_role": "composition_of_existing_canonical_evidence",
        "qcoder_product_path": "oss",
        "artifact_role": "local_selected_evidence_review",
        "qcoder_version": _qcoder_version(),
        "status": overall,
        "section_order": list(REPORT_SECTION_ORDER),
        "review_scope": {
            "selection": "explicit_file_arguments_only",
            "selected_artifact_count": len(items),
            "collection_limit": MAX_SELECTED_FILES,
            "selected_artifacts": [deepcopy(item["input"]) for item in items],
            "directory_input_accepted": False,
            "glob_expansion_performed": False,
            "recursive_discovery_performed": False,
            "hidden_file_discovery_performed": False,
            "workspace_scanned": False,
            "watcher_started": False,
            "network_accessed": False,
        },
        "canonical_identity_reuse": {
            "development_evidence": DEVELOPMENT_EVIDENCE_SCHEMA_ID,
            "circuit_manifestation": CIRCUIT_MANIFESTATION_SCHEMA_ID,
            "run_summary": RUN_SUMMARY_SCHEMA_ID,
            "help": help_payload["schema_id"],
            "motif_registry_identifiers": list(MOTIF_REGISTRY),
            "replacement_schema_created": False,
            "evidence_registry_created": False,
        },
        "artifacts": items,
        "bounded_local_planning_guidance": {
            "status": "not_requested",
            "separate_from_evidence_facts": True,
            "not_optimality_proof": True,
            "not_fidelity_proof": True,
            "not_backend_ranking": True,
            "not_causal_savings": True,
            "structural_proxy_only": True,
        },
        "share_safe_export": {
            "status": "available_on_explicit_request",
            "default_raw_or_private_categories_included": False,
            "separate_opt_in_categories": list(SHARE_SAFE_OPT_IN_CATEGORIES),
            "automatic_transmission": False,
            "customer_review_required_before_sharing": True,
        },
        "supported_next_actions": actions,
        "local_qcoder_help": help_payload,
        "local_only": True,
        "account_required": False,
        "qcoder_token_required": False,
        "explorer_service_used": False,
        "mcp_required_or_implied": False,
        "telemetry_emitted": False,
        "persistent_state_created": False,
        "client_qualification_established": False,
    }


def _redact_explicit_text(value: str, *, include_paths: bool) -> str:
    redacted = _SECRET_ASSIGNMENT.sub(
        lambda match: match.group("prefix") + "<redacted-sensitive-value>", value
    )
    if not include_paths:
        redacted = re.sub(
            r"(?:[A-Za-z]:[\\/]|/(?:home|Users|mnt|private|tmp|workspace)/)[^\s'\"<>]+",
            "<redacted-local-path>",
            redacted,
        )
    return redacted


def _sanitize_explicit_value(value: Any, *, include_paths: bool) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name.casefold().replace("-", "_") in {
                "api_key",
                "authorization",
                "cookie",
                "credential",
                "password",
                "secret",
                "session",
                "token",
            }:
                result[name] = "<redacted-sensitive-value>"
            else:
                result[name] = _sanitize_explicit_value(item, include_paths=include_paths)
        return result
    if isinstance(value, list):
        return [_sanitize_explicit_value(item, include_paths=include_paths) for item in value]
    if isinstance(value, str):
        return _redact_explicit_text(value, include_paths=include_paths)
    return deepcopy(value)


def _drop_unnecessary_share_safe_identities(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if (
                name in _UNNECESSARY_SHARE_SAFE_IDENTITY_KEYS
                or name in _DEFAULT_EXCLUDED_RAW_KEYS
                or name.endswith("_digest")
            ):
                continue
            result[name] = _drop_unnecessary_share_safe_identities(item)
        return result
    if isinstance(value, list):
        return [_drop_unnecessary_share_safe_identities(item) for item in value]
    return deepcopy(value)


def build_share_safe_local_evidence_review(
    report: Mapping[str, Any],
    paths: Sequence[str],
    *,
    opt_ins: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    choices = {
        name: bool((opt_ins or {}).get(name, False)) for name in SHARE_SAFE_OPT_IN_CATEGORIES
    }
    unknown = set(opt_ins or {}) - set(SHARE_SAFE_OPT_IN_CATEGORIES)
    if unknown:
        raise LocalEvidenceError(f"unsupported share-safe opt-in categories: {sorted(unknown)}")
    selected = resolve_explicit_files(paths)
    safe = make_share_safe_payload(deepcopy(dict(report)))
    safe = _drop_unnecessary_share_safe_identities(safe)
    included: list[dict[str, Any]] = []
    for position, path in enumerate(selected, start=1):
        text = _read_text(path, maximum=MAX_JSON_BYTES)
        row: dict[str, Any] = {"position": position}
        if choices["customer_filenames"]:
            row["customer_filename"] = _redact_explicit_text(path.name, include_paths=False)
        if choices["customer_paths"]:
            row["customer_path"] = _redact_explicit_text(str(path), include_paths=True)
        if path.suffix.casefold() == ".py" and choices["source_excerpts"]:
            row["selected_source_excerpt"] = _redact_explicit_text(
                "\n".join(text.splitlines()[:40])[:4_000],
                include_paths=choices["customer_paths"],
            )
        if path.suffix.casefold() in {".qasm", ".qasm2", ".qasm3"}:
            if choices["original_qasm"]:
                row["selected_original_qasm"] = _redact_explicit_text(
                    text, include_paths=choices["customer_paths"]
                )
            if choices["normalized_circuit_ir"] and _qasm_format(text) == "openqasm_2":
                row["selected_normalized_circuit_ir"] = _ir_projection(text)
        if path.suffix.casefold() == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, Mapping) and (
                "counts" in data
                or (data and all(set(str(key).replace(" ", "")) <= {"0", "1"} for key in data))
            ):
                if choices["raw_counts"]:
                    raw = data.get("counts", data)
                    row["selected_raw_counts"] = (
                        deepcopy(dict(raw)) if isinstance(raw, Mapping) else None
                    )
                if choices["raw_run_result_payloads"]:
                    row["selected_run_result_payload"] = _sanitize_explicit_value(
                        data,
                        include_paths=choices["customer_paths"],
                    )
        if choices["blueprint_material"]:
            row["selected_blueprint_material"] = "not_applicable_to_supported_inputs"
        if len(row) > 1:
            included.append(row)
    safe["explicit_opt_ins"] = choices
    safe["explicitly_included_private_content"] = included
    safe["raw_source_included"] = choices["source_excerpts"] and any(
        path.suffix.casefold() == ".py" for path in selected
    )
    safe["raw_qasm_included"] = choices["original_qasm"] and any(
        path.suffix.casefold() in {".qasm", ".qasm2", ".qasm3"} for path in selected
    )
    safe["raw_counts_included"] = choices["raw_counts"]
    safe["raw_run_result_payloads_included"] = choices["raw_run_result_payloads"]
    safe["local_paths_included"] = choices["customer_paths"]
    safe["customer_filenames_included"] = choices["customer_filenames"]
    safe["explicit_opt_in_warning"] = (
        "Explicitly included content may contain customer-private material. Inspect this local export before sharing."
    )
    safe["automatic_network_transmission"] = False
    safe["customer_inspection_required"] = True
    serialized = json.dumps(safe, ensure_ascii=False, sort_keys=True)
    safe["token_like_secrets_included"] = "<redacted-sensitive-value>" not in serialized and bool(
        _SECRET_ASSIGNMENT.search(serialized)
    )
    safe["tokens_included"] = safe["token_like_secrets_included"]
    return safe
