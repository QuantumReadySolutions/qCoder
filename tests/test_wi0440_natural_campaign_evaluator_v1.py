from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wi0440-natural-campaign-evaluate.py"


def _evaluator():
    spec = importlib.util.spec_from_file_location("wi0440_campaign_evaluator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(run_id: str, *, arm: str, phase: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "arm": arm,
        "phase": phase,
        "status": "pass",
        "started_utc": "2026-08-28T18:00:00Z",
        "finished_utc": "2026-08-28T18:01:00Z",
        "stage_timestamps_utc": {
            "configuration_loaded": "2026-08-28T18:00:00Z",
            "schema_discovery_finished": "2026-08-28T18:00:01Z",
            "first_model_cycle": "2026-08-28T18:00:02Z",
            "first_qcoder_call": "2026-08-28T18:00:03Z",
            "first_useful_interpretation": "2026-08-28T18:00:08Z",
            "first_material_decision": "2026-08-28T18:00:10Z",
            "confirmation": "2026-08-28T18:00:15Z",
            "source_ready": "2026-08-28T18:00:25Z",
            "loop_closed": "2026-08-28T18:01:00Z",
        },
        "model_cycles": 4,
        "qcoder_call_count": 5 if arm != "plain_cursor" else 0,
        "qcoder_call_categories": (
            ["intent", "blueprint", "generation_context", "begin", "complete"]
            if arm != "plain_cursor"
            else []
        ),
        "routine_narration_count": 0,
        "authorized_source_actions": 1,
        "validated_registrations": 1,
        "artifact_counts": {"source": 1, "qasm": 1, "results": 1, "surplus": 0},
        "timings_seconds": {
            "first_useful_interpretation": 8.0,
            "first_material_decision": 10.0,
            "source_after_confirmation": 10.0,
            "continuation_max": 12.0,
            "complete_workflow": 60.0,
        },
        "configuration_restored": True,
        "failure_category": None,
    }


def _campaign() -> dict[str, object]:
    runs = []
    for index in range(5):
        runs.extend(
            [
                _run(f"matched-public-{index}", arm="public_a22_12_only", phase="matched"),
                _run(
                    f"matched-candidate-{index}",
                    arm="candidate_12_plus_2",
                    phase="matched",
                ),
                _run(f"matched-plain-{index}", arm="plain_cursor", phase="matched"),
            ]
        )
    runs.extend(
        _run(f"canonical-{index}", arm="candidate_12_plus_2", phase="canonical")
        for index in range(20)
    )
    return {
        "schema_id": "qcoder.wi0440.lenovo_cursor_natural_campaign.v1",
        "schema_version": 1,
        "client_profile": {
            "product": "Cursor Desktop",
            "version": "3.16.29",
            "platform": "Windows native",
            "python": "3.12.10",
            "model": "Grok 4.6 High",
            "fast_mode": False,
        },
        "public_version": "0.6.0a22",
        "candidate_version": "0.6.0a23",
        "runs": runs,
        "attempt_ledger_count": len(runs),
        "matched_source_overhead_seconds": [5.0, 6.0, 7.0, 8.0, 9.0],
        "raw_evidence_retained": False,
    }


def test_complete_matched_and_twenty_run_campaign_passes() -> None:
    result = _evaluator().evaluate(_campaign())
    assert result["ok"] is True
    assert result["matched_pairs"] == 5
    assert result["plain_controls"] == 5
    assert result["canonical_runs"] == 20
    assert result["matched_source_overhead_p95_seconds"] == 9.0
    assert result["raw_evidence_retained"] is False


@pytest.mark.parametrize(
    "mutation,category",
    [
        ("client", "campaign_client_profile_mismatch"),
        ("canonical_count", "campaign_canonical_population_incomplete"),
        ("ledger", "campaign_attempt_ledger_incomplete"),
        ("failure", "campaign_canonical_failure_present"),
        ("narration", "campaign_routine_narration_present"),
        ("registration", "campaign_source_action_or_registration_count_invalid"),
        ("latency", "campaign_first_useful_max_failed"),
        ("overhead", "campaign_matched_overhead_gate_failed"),
        ("restoration", "campaign_configuration_restoration_failed"),
        ("secret_key", "campaign_prohibited_field_present"),
    ],
)
def test_fail_closed_campaign_mutations(mutation: str, category: str) -> None:
    campaign = deepcopy(_campaign())
    runs = campaign["runs"]
    assert isinstance(runs, list)
    canonical = next(run for run in runs if run["phase"] == "canonical")
    if mutation == "client":
        campaign["client_profile"]["version"] = "different"
    elif mutation == "canonical_count":
        campaign["runs"] = [run for run in runs if run["phase"] != "canonical"]
        campaign["attempt_ledger_count"] = len(campaign["runs"])
    elif mutation == "ledger":
        campaign["attempt_ledger_count"] = len(runs) - 1
    elif mutation == "failure":
        canonical["status"] = "fail"
        canonical["failure_category"] = "bounded_failure"
    elif mutation == "narration":
        canonical["routine_narration_count"] = 1
    elif mutation == "registration":
        canonical["validated_registrations"] = 0
    elif mutation == "latency":
        canonical["timings_seconds"]["first_useful_interpretation"] = 31.0
    elif mutation == "overhead":
        campaign["matched_source_overhead_seconds"] = [11.0] * 5
    elif mutation == "restoration":
        canonical["configuration_restored"] = False
    else:
        campaign["credential_value"] = "not-retained"
    with pytest.raises(ValueError, match=category):
        _evaluator().evaluate(campaign)
