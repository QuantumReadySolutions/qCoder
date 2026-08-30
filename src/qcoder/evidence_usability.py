"""Deterministic, share-safe views over explicitly selected qCoder evidence.

The views in this module do not discover artifacts, execute source or circuits,
contact a service, or establish new evidence or intent authority.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from qcoder.algorithm_blueprint import artifact_digest_matches
from qcoder.blueprint_decisions import decision_record_error, unpack_decision_record_set
from qcoder.core.share_safe import contains_local_path, redact_local_paths
from qcoder.engines.review.local_evidence import (
    build_local_evidence_review,
    build_share_safe_local_evidence_review,
    resolve_explicit_files,
)


PROMPT_PACK_SCHEMA_ID = "qcoder.evidence_prompt_pack.v1"
READINESS_SCHEMA_ID = "qcoder.run_readiness_checklist.v1"
INTENT_CARD_SCHEMA_ID = "qcoder.blueprint_intent_card_projection.v1"
SCHEMA_VERSION = 1
READINESS_DISPOSITIONS = (
    "ready",
    "warning",
    "missing_evidence",
    "unsupported",
    "not_applicable",
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:api_key|authorization|cookie|credential|password|secret|session|token)(?:_|$)",
    re.IGNORECASE,
)
_RAW_KEY_RE = re.compile(
    r"(?:^|_)(?:raw_(?:client|model|mcp|request|response|stream)|authentication_state|configuration_body)(?:_|$)",
    re.IGNORECASE,
)
_PROHIBITED_PREDICTIONS = (
    "runtime prediction",
    "fidelity prediction",
    "backend ranking",
    "optimal shot count",
    "algorithm correctness",
    "execution success",
    "hardware suitability",
    "statistical sufficiency",
)


class EvidenceUsabilityError(ValueError):
    """Bounded failure for local evidence usability projections."""


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(131_072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_text(value: object) -> str:
    text = redact_local_paths(str(value).strip())
    return " ".join(text.split())


def _unique_text(values: Sequence[object]) -> list[str]:
    return sorted({_safe_text(value) for value in values if _safe_text(value)})


def _privacy_error(value: object, *, path: str = "$") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            normalized = name.casefold().replace("-", "_")
            if _SENSITIVE_KEY_RE.search(normalized) or _RAW_KEY_RE.search(normalized):
                return f"unsafe_output_field:{path}.{name}"
            error = _privacy_error(item, path=f"{path}.{name}")
            if error:
                return error
        return None
    if isinstance(value, list):
        for index, item in enumerate(value):
            error = _privacy_error(item, path=f"{path}[{index}]")
            if error:
                return error
        return None
    if isinstance(value, str) and contains_local_path(value):
        return f"unsafe_output_path:{path}"
    return None


def _require_exact_keys(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise EvidenceUsabilityError(f"{label}_shape_invalid")
    return value


def _selected_artifacts(paths: Sequence[str], report: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected = resolve_explicit_files(paths)
    rows = []
    for path, item in zip(selected, report["artifacts"], strict=True):
        digest = _sha256(path)
        canonical = item.get("canonical_artifacts")
        schema_ids = sorted(
            {
                str(entry.get("schema_id") or entry.get("artifact_type"))
                for entry in canonical or []
                if isinstance(entry, Mapping)
                and (entry.get("schema_id") or entry.get("artifact_type"))
            }
        )
        rows.append(
            {
                "artifact_id": f"selected-evidence-{digest[:16]}",
                "artifact_kind": str(item["input"]["kind"]),
                "sha256": digest,
                "evidence_schemas": schema_ids,
                "selection": "explicit_file_argument",
            }
        )
    return sorted(rows, key=lambda row: (row["artifact_kind"], row["sha256"]))


def _statements(report: Mapping[str, Any], field: str) -> list[str]:
    values: list[object] = []
    for item in report["artifacts"]:
        values.extend(item.get(field) or [])
    return _unique_text(values)


def _next_checks(report: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = []
    for item in report["artifacts"]:
        for index, instruction in enumerate(item.get("supported_next_actions") or [], start=1):
            text = _safe_text(instruction)
            if text:
                rows.append(
                    {
                        "check_id": f"existing-next-check-{str(item['input']['kind']).replace('_', '-')}-{index}",
                        "instruction": text,
                        "basis": "existing_local_evidence_supported_next_action",
                    }
                )
    return sorted(rows, key=lambda row: (row["check_id"], row["instruction"]))


def build_evidence_prompt_pack(
    *, paths: Sequence[str], report: Mapping[str, Any]
) -> dict[str, Any]:
    selected = _selected_artifacts(paths, report)
    supported = _statements(report, "established")
    limitations = _statements(report, "limitations")
    unsupported = _statements(report, "not_established")
    if not unsupported:
        unsupported = ["The selected evidence establishes no statement beyond its listed findings."]
    value = {
        "schema_id": PROMPT_PACK_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "projection_role": "share_safe_assistant_input_from_explicitly_selected_evidence",
        "selected_artifacts": selected,
        "supported_findings": supported,
        "limitations": limitations,
        "unsupported_statements": unsupported,
        "bounded_next_checks": _next_checks(report),
        "boundaries": {
            "assistant_quality_guaranteed": False,
            "model_called": False,
            "network_accessed": False,
            "repository_scanned": False,
            "source_or_circuit_executed": False,
            "persistent_memory_created": False,
            "customer_review_required_before_sharing": True,
        },
    }
    validate_evidence_prompt_pack(value)
    return value


def _canonical_artifacts(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        artifact
        for item in report["artifacts"]
        for artifact in item.get("canonical_artifacts") or []
        if isinstance(artifact, Mapping)
    ]


def build_run_readiness_checklist(
    *, paths: Sequence[str], report: Mapping[str, Any]
) -> dict[str, Any]:
    selected = _selected_artifacts(paths, report)
    items = list(report["artifacts"])
    artifacts = _canonical_artifacts(report)
    unsupported_items = [item for item in items if item["status"] in {"unsupported", "invalid"}]
    qasm_items = [item for item in items if str(item["input"]["kind"]).startswith("openqasm")]
    qasm2_items = [item for item in items if item["input"]["kind"] == "openqasm_2"]
    measurement_count = sum(
        int((artifact.get("structural_metrics") or {}).get("measurement_count") or 0)
        for artifact in artifacts
    )
    result_evidence = any(
        artifact.get("schema_id")
        in {
            "qcoder.result_manifestation.v1",
            "qcoder.current_loop_run_summary.v1",
        }
        for artifact in artifacts
    )
    checks = [
        {
            "check_id": "selected-artifact-validation",
            "label": "Selected artifact validation",
            "disposition": "unsupported" if unsupported_items else "ready",
            "explanation": (
                "One or more explicitly selected artifacts are unsupported or invalid."
                if unsupported_items
                else "Every explicitly selected artifact was parsed within a supported local evidence path."
            ),
            "supporting_evidence_ids": [row["artifact_id"] for row in selected],
            "limitation": "This validation does not establish correctness or execution success.",
        },
        {
            "check_id": "supported-input-format",
            "label": "Supported input format",
            "disposition": "unsupported" if unsupported_items else "ready",
            "explanation": (
                "At least one selected format is outside the supported local evidence set."
                if unsupported_items
                else "The selected formats are supported by the existing bounded local evidence readers."
            ),
            "supporting_evidence_ids": [row["artifact_id"] for row in selected],
            "limitation": "Format support is not backend, hardware, or runtime suitability.",
        },
        {
            "check_id": "openqasm-2-readiness",
            "label": "OpenQASM 2 evidence availability",
            "disposition": (
                "ready" if qasm2_items else "unsupported" if qasm_items else "not_applicable"
            ),
            "explanation": (
                "Explicit OpenQASM 2 evidence is available."
                if qasm2_items
                else "A selected QASM artifact is not OpenQASM 2."
                if qasm_items
                else "No QASM artifact was selected."
            ),
            "supporting_evidence_ids": [
                row["artifact_id"]
                for row in selected
                if row["artifact_kind"].startswith("openqasm")
            ],
            "limitation": "Static QASM parsing does not establish executable hardware support.",
        },
        {
            "check_id": "measurement-evidence",
            "label": "Measurement evidence",
            "disposition": "ready" if measurement_count else "warning",
            "explanation": (
                f"The selected circuit evidence records {measurement_count} measurement operation(s)."
                if measurement_count
                else "No measurement operation was established in the selected circuit evidence."
            ),
            "supporting_evidence_ids": [row["artifact_id"] for row in selected],
            "limitation": "Measurement presence does not establish output quality or statistical sufficiency.",
        },
        {
            "check_id": "supplied-result-evidence",
            "label": "Supplied result evidence",
            "disposition": "ready" if result_evidence else "missing_evidence",
            "explanation": (
                "A supported result-evidence artifact was explicitly selected."
                if result_evidence
                else "No supported result-evidence artifact was explicitly selected."
            ),
            "supporting_evidence_ids": [row["artifact_id"] for row in selected]
            if result_evidence
            else [],
            "limitation": "Result presence does not establish circuit lineage unless that relationship is explicit in the evidence.",
        },
    ]
    value = {
        "schema_id": READINESS_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "projection_role": "customer_readable_view_of_existing_preflight_evidence",
        "selected_artifacts": selected,
        "disposition_vocabulary": list(READINESS_DISPOSITIONS),
        "checks": checks,
        "prohibited_conclusions": list(_PROHIBITED_PREDICTIONS),
        "boundaries": {
            "execution_performed": False,
            "prediction_performed": False,
            "new_evidence_created": False,
            "repository_scanned": False,
            "network_accessed": False,
        },
    }
    validate_run_readiness_checklist(value)
    return value


def _load_json(path_value: str | None, *, label: str) -> dict[str, Any] | None:
    if path_value is None:
        return None
    path = resolve_explicit_files([path_value])[0]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceUsabilityError(f"{label}_malformed") from exc
    if not isinstance(value, dict):
        raise EvidenceUsabilityError(f"{label}_must_be_object")
    return value


def _validate_intent_card(value: Mapping[str, Any]) -> None:
    if value.get("artifact_type") != "algorithm_intent_card" or value.get("schema_version") != 1:
        raise EvidenceUsabilityError("algorithm_intent_card_schema_unsupported")
    if value.get("confirmation_state") not in {"proposed", "needs_clarification", "confirmed"}:
        raise EvidenceUsabilityError("algorithm_intent_card_confirmation_state_invalid")
    if "artifact_digest" in value and not artifact_digest_matches(value):
        raise EvidenceUsabilityError("algorithm_intent_card_digest_invalid")
    original = value.get("original_user_intent")
    if not isinstance(original, str) or not original.strip():
        raise EvidenceUsabilityError("algorithm_intent_card_user_intent_missing")


def _validate_blueprint(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value.get("artifact_type") != "implementation_blueprint" or value.get("schema_version") != 1:
        raise EvidenceUsabilityError("implementation_blueprint_schema_unsupported")
    if value.get("confirmation_state") not in {"proposed", "needs_clarification", "confirmed"}:
        raise EvidenceUsabilityError("implementation_blueprint_confirmation_state_invalid")
    if "artifact_digest" in value and not artifact_digest_matches(value):
        raise EvidenceUsabilityError("implementation_blueprint_digest_invalid")
    record_set = value.get("blueprint_decision_records")
    if record_set is None:
        return []
    try:
        records = unpack_decision_record_set(record_set)
    except ValueError as exc:
        raise EvidenceUsabilityError("implementation_blueprint_decisions_invalid") from exc
    if any(decision_record_error(record) for record in records):
        raise EvidenceUsabilityError("implementation_blueprint_decisions_invalid")
    return records


def _choice_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    selected = deepcopy(record.get("selected_value"))
    if isinstance(selected, (Mapping, list)):
        selected = json.loads(json.dumps(selected, sort_keys=True))
    return {
        "decision_id": str(record["profile_decision_id"]),
        "resolution_state": str(record["resolution_state"]),
        "user_disposition": str(record["user_disposition"]),
        "selected_value": selected,
    }


def build_blueprint_intent_card(
    *,
    report: Mapping[str, Any],
    intent_json: str | None = None,
    blueprint_json: str | None = None,
) -> dict[str, Any]:
    intent = _load_json(intent_json, label="algorithm_intent_card")
    blueprint = _load_json(blueprint_json, label="implementation_blueprint")
    if intent is not None:
        _validate_intent_card(intent)
    records = _validate_blueprint(blueprint) if blueprint is not None else []
    intent_state = "absent"
    stated: list[str] = []
    if intent is not None:
        intent_state = (
            "confirmed" if intent["confirmation_state"] == "confirmed" else "proposed_unconfirmed"
        )
        stated = [_safe_text(intent["original_user_intent"])]
    blueprint_confirmed = bool(blueprint and blueprint["confirmation_state"] == "confirmed")
    confirmed = []
    unresolved = []
    deferred = []
    for record in records:
        projection = _choice_projection(record)
        state = record["resolution_state"]
        disposition = record["user_disposition"]
        if (
            blueprint_confirmed
            and state == "resolved"
            and disposition
            in {
                "selected_choice",
                "bounded_alternatives",
                "bounded_value_range",
            }
        ):
            confirmed.append(projection)
        elif state == "evidence_deferred" or disposition in {
            "deferred_to_source_evidence",
            "deferred_to_later_evidence",
        }:
            deferred.append(projection)
        else:
            unresolved.append(projection)
    if blueprint_confirmed:
        requirements = blueprint.get("requirements")
        if requirements is not None and (
            not isinstance(requirements, list)
            or any(not isinstance(item, str) or not item.strip() for item in requirements)
        ):
            raise EvidenceUsabilityError("implementation_blueprint_requirements_invalid")
        for index, requirement in enumerate(requirements or [], start=1):
            confirmed.append(
                {
                    "decision_id": f"implementation-blueprint.requirement-{index:03d}",
                    "resolution_state": "resolved",
                    "user_disposition": "selected_choice",
                    "selected_value": _safe_text(requirement),
                }
            )
    observed = [
        {"observation": statement, "authority": "selected_evidence_only_not_intent"}
        for statement in _statements(report, "established")
    ]
    unsupported = _statements(report, "not_established")
    unsupported.append("Observed source or circuit structure does not establish user intent.")
    value = {
        "schema_id": INTENT_CARD_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "projection_role": "view_of_existing_intent_and_confirmed_blueprint_state",
        "intent_state": intent_state,
        "user_stated_intent": stated,
        "confirmed_blueprint_decisions": sorted(confirmed, key=lambda row: row["decision_id"]),
        "observed_evidence": observed,
        "unresolved_choices": sorted(unresolved, key=lambda row: row["decision_id"]),
        "explicitly_deferred_choices": sorted(deferred, key=lambda row: row["decision_id"]),
        "unsupported_assumptions": _unique_text(unsupported),
        "boundaries": {
            "intent_inferred_from_source_or_circuit": False,
            "choice_auto_confirmed": False,
            "confirmation_authority_changed": False,
            "persistent_source_of_truth_created": False,
            "model_called": False,
        },
    }
    validate_blueprint_intent_card(value)
    return value


def _validate_selected(rows: object) -> None:
    if not isinstance(rows, list) or not rows:
        raise EvidenceUsabilityError("selected_artifacts_invalid")
    keys = {"artifact_id", "artifact_kind", "sha256", "evidence_schemas", "selection"}
    for row in rows:
        mapped = _require_exact_keys(row, keys, "selected_artifact")
        if not _DIGEST_RE.fullmatch(str(mapped["sha256"])):
            raise EvidenceUsabilityError("selected_artifact_digest_invalid")
        if mapped["selection"] != "explicit_file_argument":
            raise EvidenceUsabilityError("selected_artifact_selection_invalid")
        if not isinstance(mapped["evidence_schemas"], list):
            raise EvidenceUsabilityError("selected_artifact_schemas_invalid")


def validate_evidence_prompt_pack(value: object) -> None:
    mapped = _require_exact_keys(
        value,
        {
            "schema_id",
            "schema_version",
            "projection_role",
            "selected_artifacts",
            "supported_findings",
            "limitations",
            "unsupported_statements",
            "bounded_next_checks",
            "boundaries",
        },
        "evidence_prompt_pack",
    )
    if mapped["schema_id"] != PROMPT_PACK_SCHEMA_ID or mapped["schema_version"] != 1:
        raise EvidenceUsabilityError("evidence_prompt_pack_schema_unsupported")
    _validate_selected(mapped["selected_artifacts"])
    for key in ("supported_findings", "limitations", "unsupported_statements"):
        if not isinstance(mapped[key], list) or any(
            not isinstance(item, str) for item in mapped[key]
        ):
            raise EvidenceUsabilityError(f"evidence_prompt_pack_{key}_invalid")
    next_keys = {"check_id", "instruction", "basis"}
    if not isinstance(mapped["bounded_next_checks"], list):
        raise EvidenceUsabilityError("evidence_prompt_pack_next_checks_invalid")
    for row in mapped["bounded_next_checks"]:
        _require_exact_keys(row, next_keys, "evidence_prompt_pack_next_check")
    _require_exact_keys(
        mapped["boundaries"],
        {
            "assistant_quality_guaranteed",
            "model_called",
            "network_accessed",
            "repository_scanned",
            "source_or_circuit_executed",
            "persistent_memory_created",
            "customer_review_required_before_sharing",
        },
        "evidence_prompt_pack_boundaries",
    )
    error = _privacy_error(mapped)
    if error:
        raise EvidenceUsabilityError(error)


def validate_run_readiness_checklist(value: object) -> None:
    mapped = _require_exact_keys(
        value,
        {
            "schema_id",
            "schema_version",
            "projection_role",
            "selected_artifacts",
            "disposition_vocabulary",
            "checks",
            "prohibited_conclusions",
            "boundaries",
        },
        "run_readiness_checklist",
    )
    if mapped["schema_id"] != READINESS_SCHEMA_ID or mapped["schema_version"] != 1:
        raise EvidenceUsabilityError("run_readiness_checklist_schema_unsupported")
    _validate_selected(mapped["selected_artifacts"])
    if mapped["disposition_vocabulary"] != list(READINESS_DISPOSITIONS):
        raise EvidenceUsabilityError("run_readiness_disposition_vocabulary_invalid")
    check_keys = {
        "check_id",
        "label",
        "disposition",
        "explanation",
        "supporting_evidence_ids",
        "limitation",
    }
    if not isinstance(mapped["checks"], list):
        raise EvidenceUsabilityError("run_readiness_checks_invalid")
    for row in mapped["checks"]:
        check = _require_exact_keys(row, check_keys, "run_readiness_check")
        if check["disposition"] not in READINESS_DISPOSITIONS:
            raise EvidenceUsabilityError("run_readiness_disposition_invalid")
    _require_exact_keys(
        mapped["boundaries"],
        {
            "execution_performed",
            "prediction_performed",
            "new_evidence_created",
            "repository_scanned",
            "network_accessed",
        },
        "run_readiness_boundaries",
    )
    error = _privacy_error(mapped)
    if error:
        raise EvidenceUsabilityError(error)


def validate_blueprint_intent_card(value: object) -> None:
    mapped = _require_exact_keys(
        value,
        {
            "schema_id",
            "schema_version",
            "projection_role",
            "intent_state",
            "user_stated_intent",
            "confirmed_blueprint_decisions",
            "observed_evidence",
            "unresolved_choices",
            "explicitly_deferred_choices",
            "unsupported_assumptions",
            "boundaries",
        },
        "blueprint_intent_card",
    )
    if mapped["schema_id"] != INTENT_CARD_SCHEMA_ID or mapped["schema_version"] != 1:
        raise EvidenceUsabilityError("blueprint_intent_card_schema_unsupported")
    if mapped["intent_state"] not in {"absent", "proposed_unconfirmed", "confirmed"}:
        raise EvidenceUsabilityError("blueprint_intent_state_invalid")
    choice_keys = {"decision_id", "resolution_state", "user_disposition", "selected_value"}
    for field in (
        "confirmed_blueprint_decisions",
        "unresolved_choices",
        "explicitly_deferred_choices",
    ):
        if not isinstance(mapped[field], list):
            raise EvidenceUsabilityError(f"blueprint_intent_{field}_invalid")
        for row in mapped[field]:
            _require_exact_keys(row, choice_keys, "blueprint_intent_choice")
    if not isinstance(mapped["observed_evidence"], list):
        raise EvidenceUsabilityError("blueprint_intent_observed_evidence_invalid")
    for row in mapped["observed_evidence"]:
        _require_exact_keys(row, {"observation", "authority"}, "blueprint_intent_observation")
    _require_exact_keys(
        mapped["boundaries"],
        {
            "intent_inferred_from_source_or_circuit",
            "choice_auto_confirmed",
            "confirmation_authority_changed",
            "persistent_source_of_truth_created",
            "model_called",
        },
        "blueprint_intent_boundaries",
    )
    error = _privacy_error(mapped)
    if error:
        raise EvidenceUsabilityError(error)


def render_evidence_prompt_pack(value: Mapping[str, Any]) -> str:
    validate_evidence_prompt_pack(value)
    lines = ["# Evidence Prompt Pack", "", "Selected evidence:"]
    lines.extend(
        f"- `{row['artifact_id']}` — {row['artifact_kind']} — SHA-256 `{row['sha256']}`"
        for row in value["selected_artifacts"]
    )
    for title, key in (
        ("Supported findings", "supported_findings"),
        ("Limitations", "limitations"),
        ("Unsupported statements", "unsupported_statements"),
    ):
        lines += ["", f"## {title}", ""]
        lines.extend(f"- {item}" for item in value[key])
    lines += ["", "## Bounded next checks", ""]
    lines.extend(f"- {row['instruction']}" for row in value["bounded_next_checks"])
    lines += [
        "",
        "This pack is local, deterministic, share-safe by default, and does not guarantee an assistant's answer.",
        "",
    ]
    return "\n".join(lines)


def render_run_readiness_checklist(value: Mapping[str, Any]) -> str:
    validate_run_readiness_checklist(value)
    lines = [
        "# Run Readiness Checklist",
        "",
        "This is an evidence view, not an execution prediction.",
        "",
    ]
    for row in value["checks"]:
        lines += [
            f"## {row['label']} — {row['disposition']}",
            "",
            row["explanation"],
            "",
            f"Limitation: {row['limitation']}",
            "",
        ]
    return "\n".join(lines)


def render_blueprint_intent_card(value: Mapping[str, Any]) -> str:
    validate_blueprint_intent_card(value)
    lines = ["# Blueprint Intent Card", "", f"Intent state: `{value['intent_state']}`", ""]
    sections = (
        ("User-stated intent", "user_stated_intent"),
        ("Confirmed Blueprint decisions", "confirmed_blueprint_decisions"),
        ("Observed evidence", "observed_evidence"),
        ("Unresolved choices", "unresolved_choices"),
        ("Explicitly deferred choices", "explicitly_deferred_choices"),
        ("Unsupported assumptions", "unsupported_assumptions"),
    )
    for title, key in sections:
        lines += [f"## {title}", ""]
        rows = value[key]
        if not rows:
            lines.append("- None established.")
        elif key == "observed_evidence":
            lines.extend(f"- {row['observation']} ({row['authority']})" for row in rows)
        elif key in {
            "confirmed_blueprint_decisions",
            "unresolved_choices",
            "explicitly_deferred_choices",
        }:
            lines.extend(
                f"- `{row['decision_id']}`: {row['resolution_state']} / {row['user_disposition']} / {json.dumps(row['selected_value'], sort_keys=True)}"
                for row in rows
            )
        else:
            lines.extend(f"- {item}" for item in rows)
        lines.append("")
    lines += ["Observed source or circuit structure is evidence, not inferred intent.", ""]
    return "\n".join(lines)


def build_evidence_usability_pack(
    *,
    paths: Sequence[str],
    python_profile: str = "generic_qiskit",
    intent_json: str | None = None,
    blueprint_json: str | None = None,
) -> dict[str, tuple[dict[str, Any], str]]:
    report = build_local_evidence_review(paths, python_profile=python_profile)
    build_share_safe_local_evidence_review(report, paths)
    prompt = build_evidence_prompt_pack(paths=paths, report=report)
    readiness = build_run_readiness_checklist(paths=paths, report=report)
    intent = build_blueprint_intent_card(
        report=report, intent_json=intent_json, blueprint_json=blueprint_json
    )
    return {
        "evidence-prompt-pack": (prompt, render_evidence_prompt_pack(prompt)),
        "run-readiness-checklist": (readiness, render_run_readiness_checklist(readiness)),
        "blueprint-intent-card": (intent, render_blueprint_intent_card(intent)),
    }


def write_evidence_usability_pack(
    *,
    paths: Sequence[str],
    out_dir: str,
    python_profile: str = "generic_qiskit",
    intent_json: str | None = None,
    blueprint_json: str | None = None,
) -> list[Path]:
    destination = Path(out_dir)
    if destination.exists() and not destination.is_dir():
        raise EvidenceUsabilityError("output_destination_is_not_directory")
    destination.mkdir(parents=True, exist_ok=True)
    outputs = build_evidence_usability_pack(
        paths=paths,
        python_profile=python_profile,
        intent_json=intent_json,
        blueprint_json=blueprint_json,
    )
    written = []
    for stem, (payload, markdown) in outputs.items():
        json_path = destination / f"{stem}.json"
        md_path = destination / f"{stem}.md"
        json_path.write_text(canonical_json(payload), encoding="utf-8")
        md_path.write_text(markdown, encoding="utf-8")
        written.extend((json_path, md_path))
    return written
