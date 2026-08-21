"""Canonical local Run Summary and bounded current-build evidence views.

This module consumes only exact, already registered current-loop evidence.  It
does not discover files, execute code, call Protected, or infer an unrecorded
run.  The Run Summary is execution evidence and is never a Blueprint object.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from typing import Any, Mapping, Sequence

from qcoder.algorithm_blueprint import artifact_digest_matches, with_artifact_digest
from qcoder.current_loop_contract import permits, validate_contract
from qcoder.engines.review.counts_v0 import normalize_counts_v0


RUN_SUMMARY_SCHEMA_ID = "qcoder.current_loop.run_summary.v2"
RUN_SUMMARY_SCHEMA_VERSION = 2
EVIDENCE_VIEW_SCHEMA_ID = "qcoder.current_loop.evidence_view.v1"
EVIDENCE_VIEW_SCHEMA_VERSION = 1
CONCISE_LOOP_SUMMARY_SCHEMA_ID = "qcoder.current_loop.concise_loop_summary.v1"
CONCISE_LOOP_SUMMARY_SCHEMA_VERSION = 1
BUILD_REVIEW_PROJECTION_SCHEMA_ID = "qcoder.current_loop.build_review_projection.v1"
RUN_SUMMARY_MAX_INPUT_OUTCOMES = 1_024
RUN_SUMMARY_MAX_TOP_OUTCOMES = 8
RUN_SUMMARY_MAX_SETTINGS_BYTES = 8_192

EVIDENCE_VIEW_IDS = (
    "top_results",
    "gate_count",
    "circuit_width",
    "circuit_depth",
    "execution_backend",
    "shot_count",
    "bond_dimension",
    "evidence_limitations",
    "concise_loop_summary",
    "full_run_summary",
    "current_build_facts",
)

EVIDENCE_VIEW_MEANINGS = {
    "top_results": "Show the bounded top observed outcomes and percentages.",
    "gate_count": "Show the observed circuit gate count.",
    "circuit_width": "Show the observed circuit width.",
    "circuit_depth": "Show the observed circuit depth.",
    "execution_backend": "Show the recorded backend or simulator.",
    "shot_count": "Show the observed or declared shot count.",
    "bond_dimension": "Show an observed bond dimension when recorded.",
    "evidence_limitations": "Show missing, stale, excluded, or otherwise limited evidence.",
    "concise_loop_summary": "Show a concise projection of current-loop evidence.",
    "full_run_summary": "Show the complete bounded canonical Run Summary.",
    "current_build_facts": (
        "Show run results, simulator, shots, circuit gate count, width, depth, and limitations "
        "through one qCoder-managed composite view."
    ),
}

_EXECUTION_FIELD_SOURCES = {
    "backend": ("backend", "backend_name", "simulator", "simulator_name"),
    "simulator_method": ("simulator_method", "method"),
    "sdk_version": ("sdk_version", "qiskit_version"),
    "runtime_version": ("runtime_version",),
    "shots": ("shots", "shots_total"),
    "seed": ("seed", "simulator_seed", "seed_simulator"),
    "bond_dimension": ("bond_dimension", "mps_bond_dimension"),
    "noise_settings": ("noise_settings", "noise_model"),
    "mitigation_settings": ("mitigation_settings", "mitigation"),
    "execution_time_seconds": ("execution_time_seconds", "execution_time"),
    "reported_memory": ("reported_memory", "memory", "memory_mb", "max_memory_mb"),
    "resource_metadata": ("resource_metadata", "resources"),
}
_FORBIDDEN_SETTING_KEYS = frozenset(
    {
        "authorization",
        "credential",
        "password",
        "raw_result",
        "secret",
        "token",
    }
)


class RunSummaryError(ValueError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _artifact_reference(value: Mapping[str, Any]) -> str:
    reference = value.get("artifact_ref") or value.get("artifact_reference")
    if not isinstance(reference, str) or not reference:
        raise RunSummaryError("run_summary_evidence_reference_missing")
    return reference


def _artifact_digest(value: Mapping[str, Any]) -> str:
    digest = value.get("artifact_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RunSummaryError("run_summary_evidence_digest_missing")
    return digest


def _safe_setting(value: object, *, depth: int = 0) -> object:
    if depth > 4:
        raise RunSummaryError("run_summary_setting_depth_invalid")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RunSummaryError("run_summary_setting_number_invalid")
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 1_024 or "\x00" in value:
            raise RunSummaryError("run_summary_setting_text_invalid")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        if len(value) > 32:
            raise RunSummaryError("run_summary_setting_object_too_large")
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            name = str(key)
            if not name or len(name) > 80 or name.casefold() in _FORBIDDEN_SETTING_KEYS:
                raise RunSummaryError("run_summary_setting_key_invalid")
            result[name] = _safe_setting(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 32:
            raise RunSummaryError("run_summary_setting_array_too_large")
        return [_safe_setting(item, depth=depth + 1) for item in value]
    raise RunSummaryError("run_summary_setting_type_invalid")


def _execution_observations(result_payload: Mapping[str, Any]) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for field, candidates in _EXECUTION_FIELD_SOURCES.items():
        observed_key = next(
            (key for key in candidates if result_payload.get(key) is not None), None
        )
        if observed_key is None:
            observations[field] = {
                "status": "missing",
                "value": None,
                "provenance": "not_present_in_registered_result",
            }
            continue
        value = _safe_setting(result_payload[observed_key])
        observations[field] = {
            "status": "observed",
            "value": value,
            "source_field": observed_key,
            "provenance": "registered_result_artifact",
        }
    if len(_canonical_json(observations).encode("utf-8")) > RUN_SUMMARY_MAX_SETTINGS_BYTES:
        raise RunSummaryError("run_summary_settings_too_large")
    return observations


def _bounded_counts(result_payload: Mapping[str, Any]) -> dict[str, Any]:
    supplied = result_payload.get("counts")
    if not isinstance(supplied, Mapping):
        raise RunSummaryError("run_summary_counts_missing")
    if len(supplied) > RUN_SUMMARY_MAX_INPUT_OUTCOMES:
        raise RunSummaryError("run_summary_outcome_count_too_large")
    normalized = normalize_counts_v0(
        {
            "schema": "qcoder.counts.v0",
            "counts": deepcopy(dict(supplied)),
            "shots_total": (
                result_payload.get("shots")
                if result_payload.get("shots") is not None
                else result_payload.get("shots_total")
            ),
        }
    )
    counts = normalized["counts"]
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    selected = ranked[:RUN_SUMMARY_MAX_TOP_OUTCOMES]
    selected_total = sum(count for _label, count in selected)
    top = [
        {
            "rank": rank,
            "bitstring": label,
            "count": count,
            "percentage": round((count / total) * 100, 6) if total else 0.0,
        }
        for rank, (label, count) in enumerate(selected, start=1)
    ]
    return {
        "representation": "bounded_top_outcomes",
        "observed_shots": total,
        "declared_shots": normalized["shots_total"],
        "total_observed_outcomes": len(ranked),
        "top_outcomes": top,
        "omitted_outcome_count": max(0, len(ranked) - len(selected)),
        "omitted_count_remainder": max(0, total - selected_total),
        "complete_raw_counts_embedded": False,
        "bounded_top_n": RUN_SUMMARY_MAX_TOP_OUTCOMES,
    }


def _evidence_binding(value: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "artifact_reference": _artifact_reference(value),
        "artifact_digest": _artifact_digest(value),
    }


def build_run_summary(
    *,
    loop_ref: str,
    workspace_binding: str,
    state_revision: int,
    contract_revision: int,
    result_payload: Mapping[str, Any],
    result_manifestation: Mapping[str, Any],
    circuit_manifestation: Mapping[str, Any] | None = None,
    source_manifestation: Mapping[str, Any] | None = None,
    operation_lineage: Mapping[str, Any] | None = None,
    evidence_snapshot_id: str | None = None,
    artifact_revision_bindings: Mapping[str, str] | None = None,
    artifact_revision_digests: Mapping[str, str] | None = None,
    manifestation_revision_bindings: Mapping[str, str] | None = None,
    derivation_version: str = "qcoder.current_loop.derivation.v1",
    evidence_reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one bounded canonical execution-evidence summary."""

    if not isinstance(loop_ref, str) or not loop_ref:
        raise RunSummaryError("run_summary_loop_binding_invalid")
    if not isinstance(workspace_binding, str) or not workspace_binding:
        raise RunSummaryError("run_summary_workspace_binding_invalid")
    if result_manifestation.get("artifact_type") != "result_manifestation":
        raise RunSummaryError("run_summary_result_manifestation_invalid")
    if not artifact_digest_matches(dict(result_manifestation)):
        raise RunSummaryError("run_summary_result_manifestation_digest_invalid")
    counts = _bounded_counts(result_payload)
    observations = _execution_observations(result_payload)
    declared = observations["shots"]
    warnings: list[str] = []
    if (
        declared["status"] == "observed"
        and isinstance(declared["value"], int)
        and declared["value"] != counts["observed_shots"]
    ):
        warnings.append(
            "The declared shot value differs from the observed sum of registered counts."
        )
    missing = [
        field for field, observation in observations.items() if observation["status"] == "missing"
    ]
    reconciliation = deepcopy(
        dict(
            evidence_reconciliation
            or {
                "schema_id": "qcoder.current_loop.explicit_run_summary_inputs.v1",
                "eligibility": {
                    "valid_result_evidence": True,
                    "current_run_evidence": True,
                    "reproducibility_rich_run_evidence": False,
                },
                "relationships": [],
                "limitations": [],
            }
        )
    )
    eligibility = reconciliation.get("eligibility", {})
    current_run = bool(eligibility.get("current_run_evidence"))
    bindings = [_evidence_binding(result_manifestation, role="result_manifestation")]
    if circuit_manifestation is not None and current_run:
        if not artifact_digest_matches(dict(circuit_manifestation)):
            raise RunSummaryError("run_summary_circuit_manifestation_digest_invalid")
        bindings.append(_evidence_binding(circuit_manifestation, role="circuit_manifestation"))
    exact_source_relationship = any(
        isinstance(item, Mapping) and item.get("relationship") == "derived_from"
        for item in reconciliation.get("relationships", [])
    )
    if source_manifestation is not None and current_run and exact_source_relationship:
        if not artifact_digest_matches(dict(source_manifestation)):
            raise RunSummaryError("run_summary_source_manifestation_digest_invalid")
        bindings.append(_evidence_binding(source_manifestation, role="python_manifestation"))
    snapshot_id = evidence_snapshot_id or (
        "evidence-snapshot-legacy-"
        + _digest(
            {
                "loop_ref": loop_ref,
                "result_digest": _artifact_digest(result_manifestation),
                "state_revision": state_revision,
            }
        )[:24]
    )
    artifact_revisions = dict(artifact_revision_bindings or {})
    artifact_digests = dict(artifact_revision_digests or {})
    manifestation_revisions = dict(manifestation_revision_bindings or {})
    summary = {
        "schema_id": RUN_SUMMARY_SCHEMA_ID,
        "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
        "artifact_type": "run_summary",
        "loop_ref": loop_ref,
        "workspace_binding": workspace_binding,
        "evidence_snapshot_id": snapshot_id,
        "artifact_revision_bindings": artifact_revisions,
        "artifact_revision_digests": artifact_digests,
        "manifestation_revision_bindings": manifestation_revisions,
        "derivation_version": derivation_version,
        "evidence_reconciliation": reconciliation,
        "evidence_classification": (
            "reproducibility_rich_run_evidence"
            if eligibility.get("reproducibility_rich_run_evidence")
            else "current_run_evidence"
            if current_run
            else "valid_result_evidence"
        ),
        "source_state_revision": state_revision,
        "source_contract_revision": contract_revision,
        "creation_revision": state_revision + 1,
        "evidence_bindings": bindings,
        "result_evidence_reference": _artifact_reference(result_manifestation),
        "result_evidence_digest": _artifact_digest(result_manifestation),
        "result_manifestation_counts_digest": result_manifestation.get("bounded_counts_digest"),
        "operation_lineage": (
            deepcopy(dict(operation_lineage))
            if isinstance(operation_lineage, Mapping)
            else {
                "status": "missing",
                "operation_receipt_id": None,
                "activity_digest": None,
            }
        ),
        "execution_observations": observations,
        "count_projection": counts,
        "circuit_relationship": {
            "circuit_reference": (
                _artifact_reference(circuit_manifestation)
                if circuit_manifestation is not None and current_run
                else result_manifestation.get("related_circuit_ref")
            ),
            "structural_metrics_reused_by_reference": bool(
                circuit_manifestation is not None and current_run
            ),
            "circuit_structure_proves_output_state_entanglement": False,
        },
        "freshness": {
            "status": "fresh",
            "stale_reasons": [],
            "source_digest_validation_required": True,
        },
        "integrity_status": "fresh",
        "currency": "current" if current_run else "prior",
        "missing_execution_fields": missing,
        "warnings": warnings,
        "limitations": [
            "qCoder did not execute the circuit.",
            "The summary reports registered evidence and does not prove correctness.",
            "Circuit structure does not by itself prove output-state entanglement.",
            "Missing execution settings remain missing and are not inferred from source.",
            *(
                [
                    "Circuit structural evidence is unavailable; circuit width, depth, "
                    "and gate count are omitted."
                ]
                if circuit_manifestation is None
                else []
            ),
            *list(reconciliation.get("limitations", [])),
        ],
        "raw_result_artifact_embedded": False,
        "complete_raw_counts_embedded": False,
        "blueprint_mutated": False,
        "evolved_blueprint_created": False,
        "persistent_project_history": False,
        "cross_loop_evidence_used": False,
    }
    summary["count_projection_support_digest"] = _digest(
        {
            "result_artifact_revision": artifact_revisions.get("results"),
            "result_artifact_digest": artifact_digests.get("results"),
            "result_manifestation_digest": _artifact_digest(result_manifestation),
            "result_manifestation_counts_digest": result_manifestation.get("bounded_counts_digest"),
            "count_projection": counts,
        }
    )
    summary["artifact_ref"] = "run-summary-" + _digest(summary)[:32]
    return with_artifact_digest(summary)


def run_summary_error(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return "run_summary_invalid"
    if (
        value.get("schema_id") != RUN_SUMMARY_SCHEMA_ID
        or value.get("schema_version") != RUN_SUMMARY_SCHEMA_VERSION
        or value.get("artifact_type") != "run_summary"
    ):
        return "run_summary_version_invalid"
    if not artifact_digest_matches(dict(value)):
        return "run_summary_digest_invalid"
    if not isinstance(value.get("loop_ref"), str) or not isinstance(
        value.get("workspace_binding"), str
    ):
        return "run_summary_binding_invalid"
    if not isinstance(value.get("evidence_snapshot_id"), str):
        return "run_summary_snapshot_binding_invalid"
    if not isinstance(value.get("artifact_revision_bindings"), Mapping):
        return "run_summary_artifact_revision_binding_invalid"
    if not isinstance(value.get("artifact_revision_digests"), Mapping):
        return "run_summary_artifact_revision_digest_binding_invalid"
    if not isinstance(value.get("manifestation_revision_bindings"), Mapping):
        return "run_summary_manifestation_revision_binding_invalid"
    if not isinstance(value.get("derivation_version"), str):
        return "run_summary_derivation_binding_invalid"
    if value.get("integrity_status") not in {"fresh", "stale", "incomplete", "failed"}:
        return "run_summary_integrity_status_invalid"
    if value.get("currency") not in {
        "current",
        "prior",
        "prior_newer_pending",
        "prior_newer_failed",
        "superseded",
    }:
        return "run_summary_currency_invalid"
    if not isinstance(value.get("evidence_bindings"), list) or not value["evidence_bindings"]:
        return "run_summary_evidence_binding_invalid"
    if not isinstance(value.get("result_evidence_reference"), str) or not isinstance(
        value.get("result_evidence_digest"), str
    ):
        return "run_summary_result_binding_invalid"
    projection = value.get("count_projection")
    if not isinstance(projection, Mapping):
        return "run_summary_count_projection_invalid"
    if projection.get("complete_raw_counts_embedded") is not False:
        return "run_summary_raw_counts_boundary_invalid"
    if value.get("raw_result_artifact_embedded") is not False:
        return "run_summary_raw_result_boundary_invalid"
    if value.get("blueprint_mutated") is not False:
        return "run_summary_blueprint_boundary_invalid"
    if value.get("cross_loop_evidence_used") is not False:
        return "run_summary_cross_loop_boundary_invalid"
    reconciliation = value.get("evidence_reconciliation")
    if reconciliation is not None:
        if not isinstance(reconciliation, Mapping) or not isinstance(
            reconciliation.get("eligibility"), Mapping
        ):
            return "run_summary_reconciliation_invalid"
        expected_current = bool(reconciliation["eligibility"].get("current_run_evidence"))
        if (value.get("currency") == "current") != expected_current:
            return "run_summary_currentness_binding_invalid"
    return None


def validate_run_summary_snapshot_binding(
    summary: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> str | None:
    """Reject count/metric bindings that mix independent evidence generations."""

    error = run_summary_error(summary)
    if error:
        return error
    if summary.get("evidence_snapshot_id") != snapshot.get("snapshot_id"):
        return "run_summary_snapshot_mismatch"
    if summary.get("artifact_revision_bindings") != snapshot.get("role_revision_set"):
        return "run_summary_artifact_revision_set_mismatch"
    if summary.get("artifact_revision_digests") != snapshot.get(
        "artifact_revision_digest_bindings"
    ):
        return "run_summary_artifact_revision_digest_set_mismatch"
    manifestation_set = snapshot.get("manifestation_revision_set")
    if not isinstance(manifestation_set, Mapping):
        return "run_summary_manifestation_revision_set_invalid"
    expected = summary.get("manifestation_revision_bindings")
    if expected != {
        role: descriptor.get("manifestation_revision_id")
        for role, descriptor in manifestation_set.items()
        if isinstance(descriptor, Mapping)
    }:
        return "run_summary_manifestation_revision_set_mismatch"
    role_parents = {
        "result_manifestation": "results",
        "circuit_manifestation": "circuit_qasm",
        "python_manifestation": "source",
        "source_evidence": "source",
    }
    binding_by_role = {
        binding.get("role"): binding
        for binding in summary["evidence_bindings"]
        if isinstance(binding, Mapping)
    }
    for manifestation_role, descriptor in manifestation_set.items():
        if not isinstance(descriptor, Mapping):
            return "run_summary_manifestation_revision_set_invalid"
        parent_role = role_parents.get(str(manifestation_role))
        if parent_role is not None and descriptor.get("parent_artifact_revision_id") != summary[
            "artifact_revision_bindings"
        ].get(parent_role):
            return "run_summary_manifestation_parent_mismatch"
        summary_role = (
            "python_manifestation"
            if manifestation_role == "python_manifestation"
            else manifestation_role
        )
        binding = binding_by_role.get(summary_role)
        if binding is not None and binding.get("artifact_digest") != descriptor.get(
            "artifact_digest"
        ):
            return "run_summary_manifestation_digest_mismatch"
    result_binding = summary["artifact_revision_bindings"].get("results")
    result_manifestation = next(
        (
            binding
            for binding in summary["evidence_bindings"]
            if binding.get("role") == "result_manifestation"
        ),
        None,
    )
    if not isinstance(result_binding, str) or not isinstance(result_manifestation, Mapping):
        return "run_summary_result_revision_binding_missing"
    expected_support = _digest(
        {
            "result_artifact_revision": result_binding,
            "result_artifact_digest": summary["artifact_revision_digests"].get("results"),
            "result_manifestation_digest": result_manifestation.get("artifact_digest"),
            "result_manifestation_counts_digest": summary.get("result_manifestation_counts_digest"),
            "count_projection": summary["count_projection"],
        }
    )
    if summary.get("count_projection_support_digest") != expected_support:
        return "run_summary_count_projection_binding_mismatch"
    return None


def mark_run_summary_stale(summary: Mapping[str, Any], *, reasons: Sequence[str]) -> dict[str, Any]:
    if run_summary_error(summary):
        raise RunSummaryError("run_summary_invalid")
    result = deepcopy(dict(summary))
    result["freshness"] = {
        "status": "stale",
        "stale_reasons": sorted(set(str(reason) for reason in reasons)),
        "source_digest_validation_required": True,
    }
    result["integrity_status"] = "stale"
    return with_artifact_digest(
        {key: value for key, value in result.items() if key != "artifact_digest"}
    )


def mark_run_summary_fresh(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Refresh freshness only after callers revalidate every bound digest."""

    if run_summary_error(summary):
        raise RunSummaryError("run_summary_invalid")
    result = deepcopy(dict(summary))
    result["freshness"] = {
        "status": "fresh",
        "stale_reasons": [],
        "source_digest_validation_required": True,
    }
    result["integrity_status"] = "fresh"
    return with_artifact_digest(
        {key: value for key, value in result.items() if key != "artifact_digest"}
    )


def share_safe_run_summary_projection(summary: Mapping[str, Any], *, full: bool) -> dict[str, Any]:
    if run_summary_error(summary):
        raise RunSummaryError("run_summary_invalid")
    if full:
        permitted = {
            key: deepcopy(value)
            for key, value in summary.items()
            if key
            not in {
                "workspace_binding",
                "operation_lineage",
            }
        }
    else:
        permitted = {
            "schema_id": RUN_SUMMARY_SCHEMA_ID,
            "artifact_ref": summary["artifact_ref"],
            "loop_ref": summary["loop_ref"],
            "evidence_snapshot_id": summary["evidence_snapshot_id"],
            "freshness": deepcopy(summary["freshness"]),
            "integrity_status": summary["integrity_status"],
            "currency": summary["currency"],
            "execution_observations": {
                key: deepcopy(value)
                for key, value in summary["execution_observations"].items()
                if key in {"backend", "shots", "bond_dimension"}
            },
            "count_projection": deepcopy(summary["count_projection"]),
            "warnings": deepcopy(summary["warnings"]),
            "limitations": deepcopy(summary["limitations"]),
        }
    permitted["projection"] = "share_safe_derived"
    permitted["raw_result_artifact_included"] = False
    permitted["complete_raw_counts_included"] = False
    permitted["local_paths_included"] = False
    return permitted


def _select_run_summary(
    summaries: Sequence[Mapping[str, Any]],
    *,
    selected_reference: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    valid = [deepcopy(dict(item)) for item in summaries if run_summary_error(item) is None]
    if selected_reference is not None:
        selected = next(
            (item for item in valid if item.get("artifact_ref") == selected_reference),
            None,
        )
        if selected is None:
            raise RunSummaryError("run_summary_reference_not_eligible")
        return selected, {
            "selection": "explicit_qcoder_owned_reference",
            "eligible_references": [item["artifact_ref"] for item in valid],
        }
    if not valid:
        return None, {"selection": "none_available", "eligible_references": []}
    if len(valid) == 1:
        return valid[0], {
            "selection": "only_eligible_run",
            "eligible_references": [valid[0]["artifact_ref"]],
        }
    maximum = max(int(item.get("creation_revision") or 0) for item in valid)
    latest = [item for item in valid if int(item.get("creation_revision") or 0) == maximum]
    if len(latest) == 1:
        return latest[0], {
            "selection": "deterministic_unique_latest_creation_revision",
            "eligible_references": [item["artifact_ref"] for item in valid],
            "selected_creation_revision": maximum,
        }
    return None, {
        "selection": "ambiguous_explicit_selection_required",
        "eligible_references": [item["artifact_ref"] for item in valid],
    }


def _circuit_metric(
    circuit: Mapping[str, Any] | None, key: str, missing: str
) -> tuple[object | None, str]:
    if not isinstance(circuit, Mapping):
        return None, missing
    value = circuit.get("structural_metrics", {}).get(key)
    if value is None:
        value = circuit.get(key)
    return value, ("observed" if value is not None else missing)


def concise_loop_summary(
    *,
    contract: Mapping[str, Any],
    baseline_reference: str | None,
    circuit_manifestation: Mapping[str, Any] | None,
    selected_run_summary: Mapping[str, Any] | None,
    evidence_limitations: Sequence[str],
    unresolved_material_questions: Sequence[str] = (),
) -> dict[str, Any]:
    validate_contract(contract)
    width, _width_status = _circuit_metric(circuit_manifestation, "width", "circuit_width_missing")
    depth, _depth_status = _circuit_metric(circuit_manifestation, "depth", "circuit_depth_missing")
    gates, _gate_status = _circuit_metric(
        circuit_manifestation, "gate_count", "circuit_gate_count_missing"
    )
    run = (
        share_safe_run_summary_projection(selected_run_summary, full=False)
        if selected_run_summary is not None
        else None
    )
    result = {
        "schema_id": CONCISE_LOOP_SUMMARY_SCHEMA_ID,
        "schema_version": CONCISE_LOOP_SUMMARY_SCHEMA_VERSION,
        "projection_type": "current_loop_state_and_evidence",
        "request_baseline_reference": baseline_reference,
        "effective_preset": contract["effective_preset"],
        "circuit": {
            "width": width,
            "depth": depth,
            "gate_count": gates,
        },
        "latest_run": run,
        "evidence_limitations": list(evidence_limitations),
        "unresolved_material_questions": list(unresolved_material_questions),
        "blueprint": False,
        "persistent_project_history": False,
        "correctness_proof": False,
    }
    result["projection_digest"] = _digest(result)
    return result


def build_evidence_view(
    *,
    view_id: str,
    contract: Mapping[str, Any],
    run_summaries: Sequence[Mapping[str, Any]],
    circuit_manifestation: Mapping[str, Any] | None,
    baseline_reference: str | None,
    evidence_limitations: Sequence[str],
    selected_run_reference: str | None = None,
    destination: str = "connected_assistant",
) -> dict[str, Any]:
    """Return one bounded view without reading any project file."""

    validate_contract(contract)
    if view_id not in EVIDENCE_VIEW_IDS:
        raise RunSummaryError("evidence_view_invalid")
    if destination not in {"connected_assistant", "local_presentation"}:
        raise RunSummaryError("evidence_view_destination_invalid")
    if destination == "connected_assistant" and not permits(
        contract, category="derived_metrics", dimension="assistant_derived_exposure"
    ):
        raise RunSummaryError("evidence_view_assistant_exposure_prohibited")
    selected, selection = _select_run_summary(
        run_summaries,
        selected_reference=selected_run_reference,
    )
    answer: object
    status = "available"
    if view_id == "current_build_facts":
        gate_count, gate_status = _circuit_metric(
            circuit_manifestation,
            "gate_count",
            "Gate count is unavailable because no circuit manifestation is registered.",
        )
        width, width_status = _circuit_metric(
            circuit_manifestation,
            "width",
            "Circuit width is unavailable because no circuit manifestation is registered.",
        )
        depth, depth_status = _circuit_metric(
            circuit_manifestation,
            "depth",
            "Circuit depth is unavailable because no circuit manifestation is registered.",
        )
        if selected is None:
            run = {
                "status": selection["selection"],
                "top_results": None,
                "backend_or_simulator": None,
                "shots": None,
            }
            status = (
                "selection_required"
                if selection["selection"] == "ambiguous_explicit_selection_required"
                else "incomplete"
            )
        else:
            backend = selected["execution_observations"]["backend"]
            shots = selected["execution_observations"]["shots"]
            run = {
                "status": selected["freshness"]["status"],
                "run_reference": selected["artifact_ref"],
                "top_results": deepcopy(selected["count_projection"]["top_outcomes"]),
                "backend_or_simulator": (
                    backend["value"] if backend["status"] == "observed" else None
                ),
                "shots": (
                    shots["value"]
                    if shots["status"] == "observed"
                    else selected["count_projection"]["observed_shots"]
                ),
            }
        answer = {
            "run": run,
            "circuit": {
                "gate_count": gate_count if gate_count is not None else gate_status,
                "width": width if width is not None else width_status,
                "depth": depth if depth is not None else depth_status,
            },
            "limitations": list(evidence_limitations),
        }
    elif (
        view_id
        in {
            "top_results",
            "execution_backend",
            "shot_count",
            "bond_dimension",
            "full_run_summary",
        }
        and selected is None
    ):
        status = (
            "selection_required"
            if selection["selection"] == "ambiguous_explicit_selection_required"
            else "missing"
        )
        answer = (
            "Select one eligible qCoder run reference."
            if status == "selection_required"
            else "No authorized run result is available yet."
        )
    elif view_id == "top_results":
        answer = deepcopy(selected["count_projection"]["top_outcomes"])
    elif view_id == "execution_backend":
        observation = selected["execution_observations"]["backend"]
        answer = (
            observation["value"]
            if observation["status"] == "observed"
            else "The backend is not observed in the available result evidence."
        )
        status = observation["status"]
    elif view_id == "shot_count":
        observation = selected["execution_observations"]["shots"]
        answer = (
            observation["value"]
            if observation["status"] == "observed"
            else selected["count_projection"]["observed_shots"]
        )
    elif view_id == "bond_dimension":
        observation = selected["execution_observations"]["bond_dimension"]
        answer = (
            observation["value"]
            if observation["status"] == "observed"
            else "Bond dimension was not present in the recorded execution settings."
        )
        status = observation["status"]
    elif view_id == "full_run_summary":
        answer = share_safe_run_summary_projection(selected, full=True)
    elif view_id == "gate_count":
        answer, metric_status = _circuit_metric(
            circuit_manifestation,
            "gate_count",
            "Gate count cannot be established because no authorized circuit manifestation is registered.",
        )
        if answer is None:
            answer = metric_status
            status = "missing"
    elif view_id == "circuit_width":
        answer, metric_status = _circuit_metric(
            circuit_manifestation,
            "width",
            "Circuit width cannot be established because no authorized circuit manifestation is registered.",
        )
        if answer is None:
            answer = metric_status
            status = "missing"
    elif view_id == "circuit_depth":
        answer, metric_status = _circuit_metric(
            circuit_manifestation,
            "depth",
            "Circuit depth cannot be established because no authorized circuit manifestation is registered.",
        )
        if answer is None:
            answer = metric_status
            status = "missing"
    elif view_id == "evidence_limitations":
        answer = list(evidence_limitations) or ["No additional evidence limitation is recorded."]
    else:
        answer = concise_loop_summary(
            contract=contract,
            baseline_reference=baseline_reference,
            circuit_manifestation=circuit_manifestation,
            selected_run_summary=selected,
            evidence_limitations=evidence_limitations,
        )
    if (
        status == "available"
        and selected is not None
        and selected.get("freshness", {}).get("status") != "fresh"
    ):
        status = "stale"
    result = {
        "schema_id": EVIDENCE_VIEW_SCHEMA_ID,
        "schema_version": EVIDENCE_VIEW_SCHEMA_VERSION,
        "view_id": view_id,
        "customer_meaning": EVIDENCE_VIEW_MEANINGS[view_id],
        "status": status,
        "answer": answer,
        "run_selection": selection,
        "destination": destination,
        "source": "registered_current_loop_evidence_only",
        "raw_artifact_included": False,
        "workspace_scanned": False,
        "project_file_inspected": False,
        "cross_loop_evidence_used": False,
    }
    result["view_digest"] = _digest(result)
    return result


def run_summary_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": RUN_SUMMARY_SCHEMA_ID,
        "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
        "maximum_input_outcomes": RUN_SUMMARY_MAX_INPUT_OUTCOMES,
        "maximum_top_outcomes": RUN_SUMMARY_MAX_TOP_OUTCOMES,
        "exact_registered_evidence_only": True,
        "raw_result_artifact_embedded": False,
        "blueprint_object": False,
        "cross_loop_evidence": False,
        "missing_fields_inferred": False,
        "exact_artifact_revision_bindings": True,
        "exact_manifestation_revision_bindings": True,
        "evidence_snapshot_binding": True,
        "integrity_and_currency_separate": True,
        "prior_summary_implicitly_current": False,
        "count_projection_binding_validated": True,
    }
    payload["contract_digest"] = _digest(payload)
    return payload


def evidence_view_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": EVIDENCE_VIEW_SCHEMA_ID,
        "schema_version": EVIDENCE_VIEW_SCHEMA_VERSION,
        "views": [
            {"value": view_id, "customer_meaning": EVIDENCE_VIEW_MEANINGS[view_id]}
            for view_id in EVIDENCE_VIEW_IDS
        ],
        "eligible_run_references_qcoder_owned": True,
        "multiple_run_selection": "explicit_reference_or_deterministic_unique_latest",
        "arbitrary_query_text": False,
        "project_file_inspection": False,
        "raw_assistant_exposure": False,
    }
    payload["contract_digest"] = _digest(payload)
    return payload
