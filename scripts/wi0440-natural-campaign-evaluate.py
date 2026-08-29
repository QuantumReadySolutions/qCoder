#!/usr/bin/env python3
"""Fail-closed evaluator for the sanitized D-105 Lenovo natural campaign."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping


SCHEMA_ID = "qcoder.wi0440.lenovo_cursor_natural_campaign.v1"
EXPECTED_CLIENT = {
    "product": "Cursor Desktop",
    "version": "3.16.29",
    "platform": "Windows native",
    "python": "3.12.10",
    "model": "Grok 4.6 High",
    "fast_mode": False,
}
ARMS = {"public_a22_12_only", "candidate_12_plus_2", "plain_cursor"}
PROHIBITED_KEYS = {
    "secret",
    "token",
    "credential_value",
    "raw_prompt",
    "raw_request",
    "raw_response",
    "raw_mcp",
    "configuration_body",
    "customer_payload",
    "source_body",
    "circuit_body",
    "results_body",
}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("campaign_metric_population_empty")
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("campaign_timestamp_invalid")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _safe_tree(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in PROHIBITED_KEYS or any(
                marker in lowered
                for marker in ("password", "cookie", "authorization", "private_identity")
            ):
                raise ValueError("campaign_prohibited_field_present")
            _safe_tree(child)
    elif isinstance(value, list):
        for child in value:
            _safe_tree(child)


def _validate_run(run: Mapping[str, Any]) -> None:
    required = {
        "run_id",
        "arm",
        "phase",
        "status",
        "started_utc",
        "finished_utc",
        "stage_timestamps_utc",
        "model_cycles",
        "qcoder_call_count",
        "qcoder_call_categories",
        "routine_narration_count",
        "authorized_source_actions",
        "validated_registrations",
        "artifact_counts",
        "timings_seconds",
        "configuration_restored",
        "failure_category",
    }
    if set(run) != required:
        raise ValueError("campaign_run_shape_invalid")
    if run["arm"] not in ARMS or run["phase"] not in {"matched", "canonical"}:
        raise ValueError("campaign_run_classification_invalid")
    if run["status"] not in {"pass", "fail"}:
        raise ValueError("campaign_run_status_invalid")
    if _timestamp(run["finished_utc"]) < _timestamp(run["started_utc"]):
        raise ValueError("campaign_run_time_order_invalid")
    stages = run["stage_timestamps_utc"]
    required_stages = {
        "configuration_loaded",
        "schema_discovery_finished",
        "first_model_cycle",
        "first_qcoder_call",
        "first_useful_interpretation",
        "first_material_decision",
        "confirmation",
        "source_ready",
        "loop_closed",
    }
    if not isinstance(stages, Mapping) or not required_stages <= set(stages):
        raise ValueError("campaign_stage_timestamp_missing")
    for timestamp in stages.values():
        if timestamp is not None:
            _timestamp(timestamp)
    if not isinstance(run["qcoder_call_categories"], list):
        raise ValueError("campaign_call_projection_invalid")
    if run["configuration_restored"] is not True:
        raise ValueError("campaign_configuration_restoration_failed")
    if run["status"] == "fail" and not isinstance(run["failure_category"], str):
        raise ValueError("campaign_failure_category_missing")


def evaluate(document: Mapping[str, Any]) -> dict[str, Any]:
    _safe_tree(document)
    if document.get("schema_id") != SCHEMA_ID or document.get("schema_version") != 1:
        raise ValueError("campaign_schema_invalid")
    if document.get("client_profile") != EXPECTED_CLIENT:
        raise ValueError("campaign_client_profile_mismatch")
    if document.get("public_version") != "0.6.0a22":
        raise ValueError("campaign_public_version_mismatch")
    if document.get("candidate_version") != "0.6.0a24":
        raise ValueError("campaign_candidate_version_mismatch")
    if document.get("raw_evidence_retained") is not False:
        raise ValueError("campaign_raw_evidence_retention_invalid")
    runs = document.get("runs")
    if not isinstance(runs, list) or not all(isinstance(run, Mapping) for run in runs):
        raise ValueError("campaign_runs_invalid")
    ids = [run.get("run_id") for run in runs]
    if len(ids) != len(set(ids)):
        raise ValueError("campaign_run_id_duplicate")
    for run in runs:
        _validate_run(run)

    matched = [run for run in runs if run["phase"] == "matched"]
    canonical = [run for run in runs if run["phase"] == "canonical"]
    public = [run for run in matched if run["arm"] == "public_a22_12_only"]
    candidate_matched = [run for run in matched if run["arm"] == "candidate_12_plus_2"]
    plain = [run for run in matched if run["arm"] == "plain_cursor"]
    if len(public) < 5 or len(candidate_matched) < 5 or len(plain) < 5:
        raise ValueError("campaign_matched_population_incomplete")
    if len(canonical) < 20 or any(run["arm"] != "candidate_12_plus_2" for run in canonical):
        raise ValueError("campaign_canonical_population_incomplete")
    if document.get("attempt_ledger_count") != len(runs):
        raise ValueError("campaign_attempt_ledger_incomplete")
    if any(run["status"] != "pass" for run in canonical):
        raise ValueError("campaign_canonical_failure_present")

    for run in canonical:
        timings = run["timings_seconds"]
        if not isinstance(timings, Mapping) or not all(
            isinstance(value, (int, float)) for value in timings.values()
        ):
            raise ValueError("campaign_timing_projection_invalid")
        if run["routine_narration_count"] != 0:
            raise ValueError("campaign_routine_narration_present")
        if run["authorized_source_actions"] != 1 or run["validated_registrations"] != 1:
            raise ValueError("campaign_source_action_or_registration_count_invalid")
        artifacts = run["artifact_counts"]
        if artifacts != {"source": 1, "qasm": 1, "results": 1, "surplus": 0}:
            raise ValueError("campaign_artifact_inventory_invalid")
        if timings["first_useful_interpretation"] > 30:
            raise ValueError("campaign_first_useful_max_failed")
        if timings["first_material_decision"] > 45:
            raise ValueError("campaign_first_decision_max_failed")
        if timings["source_after_confirmation"] > 45:
            raise ValueError("campaign_source_max_failed")
        if timings["continuation_max"] > 40 or timings["complete_workflow"] > 120:
            raise ValueError("campaign_continuation_or_workflow_max_failed")

    first = [float(run["timings_seconds"]["first_useful_interpretation"]) for run in canonical]
    decision = [float(run["timings_seconds"]["first_material_decision"]) for run in canonical]
    source = [float(run["timings_seconds"]["source_after_confirmation"]) for run in canonical]
    continuation = [float(run["timings_seconds"]["continuation_max"]) for run in canonical]
    workflow = [float(run["timings_seconds"]["complete_workflow"]) for run in canonical]
    metrics = {
        "first_useful_interpretation": {
            "median": median(first),
            "p95": _percentile(first, 0.95),
            "max": max(first),
        },
        "first_material_decision": {
            "median": median(decision),
            "p95": _percentile(decision, 0.95),
            "max": max(decision),
        },
        "source_after_confirmation": {
            "median": median(source),
            "p95": _percentile(source, 0.95),
            "max": max(source),
        },
        "continuation": {"p95": _percentile(continuation, 0.95), "max": max(continuation)},
        "complete_workflow": {"p95": _percentile(workflow, 0.95), "max": max(workflow)},
    }
    if (
        metrics["first_useful_interpretation"]["median"] > 10
        or metrics["first_useful_interpretation"]["p95"] > 20
        or metrics["first_material_decision"]["median"] > 15
        or metrics["first_material_decision"]["p95"] > 30
        or metrics["source_after_confirmation"]["median"] > 20
        or metrics["source_after_confirmation"]["p95"] > 30
        or metrics["continuation"]["p95"] > 25
        or metrics["complete_workflow"]["p95"] > 120
    ):
        raise ValueError("campaign_latency_gate_failed")

    overhead = document.get("matched_source_overhead_seconds")
    if (
        not isinstance(overhead, list)
        or len(overhead) < 5
        or not all(isinstance(value, (int, float)) for value in overhead)
    ):
        raise ValueError("campaign_matched_overhead_invalid")
    overhead_p95 = _percentile([float(value) for value in overhead], 0.95)
    if overhead_p95 > 10:
        raise ValueError("campaign_matched_overhead_gate_failed")
    return {
        "schema_id": "qcoder.wi0440.lenovo_cursor_natural_campaign_evaluation.v1",
        "ok": True,
        "matched_pairs": min(len(public), len(candidate_matched)),
        "plain_controls": len(plain),
        "canonical_runs": len(canonical),
        "failed_attempts": sum(run["status"] == "fail" for run in runs),
        "metrics_seconds": metrics,
        "matched_source_overhead_p95_seconds": overhead_p95,
        "routine_narration_count": sum(run["routine_narration_count"] for run in canonical),
        "all_attempts_retained": True,
        "raw_evidence_retained": False,
        "public_claim_activated": False,
    }


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.campaign.read_text(encoding="utf-8"))
    result = evaluate(document)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("WI0440_NATURAL_CAMPAIGN_EVALUATION_PASS")


if __name__ == "__main__":
    main()
