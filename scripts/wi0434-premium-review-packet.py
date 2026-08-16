#!/usr/bin/env python3
"""Seal the WI-0434 pre-freeze premium adversarial review packet."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_binding_descriptor
from qcoder.current_loop_coordinator import coordinator_contract_snapshot
from qcoder.current_loop_request_semantics import semantics_contract_snapshot


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--d079-packet", type=Path, required=True)
    parser.add_argument("--d080-packet", type=Path, required=True)
    parser.add_argument("--routine-review", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_root.absolute()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    head = git(source, "rev-parse", "HEAD")
    tree = git(source, "rev-parse", "HEAD^{tree}")
    branch = git(source, "branch", "--show-current")
    if git(source, "status", "--porcelain"):
        raise RuntimeError("premium_packet_requires_clean_source")

    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    binding_digest = sha256(canonical(descriptor)).hexdigest()
    workflow_contract = coordinator_contract_snapshot()
    workflow_digest = sha256(canonical(workflow_contract)).hexdigest()

    material_diff = subprocess.run(
        ["git", "diff", "--binary", f"{args.baseline}..{head}"],
        cwd=source,
        check=True,
        capture_output=True,
    ).stdout
    (output / "material-source.diff").write_bytes(material_diff)
    (output / "material-source.stat").write_text(
        git(source, "diff", "--stat", f"{args.baseline}..{head}") + "\n",
        encoding="utf-8",
    )

    architecture = {
        "schema_id": "qcoder.wi0434.integrated_architecture.v1",
        "source": {"branch": branch, "commit": head, "tree": tree, "baseline": args.baseline},
        "canonical_request_semantics": semantics_contract_snapshot(),
        "ownership": {
            "qcoder": [
                "exact-message semantic classification",
                "Request Baseline and one-loop bootstrap",
                "bounded readiness and compact next action",
                "temporary stage ceiling",
                "operation receipt and artifact-role enforcement",
                "local evidence and protected projection boundaries",
            ],
            "connected_assistant": "conversation and execution of qCoder-supplied invocation",
            "native_client_customer": [
                "exact file selection and reads",
                "action-specific source write permission",
                "separate QASM/export permission",
                "separate local execution permission",
            ],
            "customer": [
                "durable Blueprint confirmation",
                "later artifact review authority",
                "governing change confirmation",
            ],
        },
        "single_canonical_loop": True,
        "parallel_semantic_system_created": False,
        "public_context_bridge_tool_count": len(EXPECTED_TOOLS),
        "protected_source_changed": False,
        "production_changed": False,
    }
    write_json(output / "architecture-and-ownership.json", architecture)

    invariant_map = {
        "schema_id": "qcoder.wi0434.premium_review_invariant_map.v1",
        "review_focus": [
            "authority escalation",
            "stage-ceiling bypass",
            "temporary-vs-durable leakage",
            "WI-0432 confirmation regression",
            "compact-next-action bypass or procedural archaeology",
            "raw/path protected leakage",
            "hidden persistent procedural state",
            "semantic and authority scale boundedness",
            "cross-client and release effects",
            "actual customer usability",
        ],
        "required_invariants": {
            "activation_is_not_native_permission": True,
            "blueprint_confirmation_is_not_source_write": True,
            "source_write_is_not_execution": True,
            "execution_is_not_evidence_review": True,
            "evidence_review_is_not_governing_change": True,
            "source_only_qasm_prohibited_preconstruction": True,
            "source_only_execution_prohibited_preconstruction": True,
            "source_only_artifact_cardinality_exactly_one": True,
            "compact_next_action_sole_procedural_source": True,
            "transcript_repository_and_qcoder_archaeology_prohibited": True,
            "active_continuation_no_rebootstrap": True,
            "active_continuation_no_baseline_recreation": True,
            "temporary_ceiling_not_blueprint_intent": True,
            "selected_file_review_stays_exact_and_local_first": True,
            "raw_or_path_protected_transfer": False,
            "process_and_discard": True,
            "public_tool_count": 12,
        },
        "direct_negative_evidence": [
            "registration without the exact live D-080 receipt rejected before path normalization",
            "caller-broadened ide_execute plus source/QASM/results rejected before authority",
            "QASM registration under source-only receipt rejected without state mutation",
            "multiple source artifacts rejected without consuming the valid receipt",
            "ambiguous active-loop continuation returns one clarification without state mutation",
            "WI-0432 stale/wrong/digest/lineage/review/envelope negatives rerun",
            "WI-0433 path/raw/neighbor/limit negatives rerun",
        ],
    }
    write_json(output / "invariant-and-adversarial-focus.json", invariant_map)

    validation = {
        "schema_id": "qcoder.wi0434.pre_freeze_validation_summary.v1",
        "supported_python_full_suite": {
            "result": "pass",
            "collected": 1149,
            "passed": 1144,
            "skipped": 5,
            "subtests_passed": 10,
        },
        "focused_d079_d080_suite": {"result": "pass", "passed": 104},
        "changed_source_ruff": "pass",
        "changed_source_ruff_format": "pass",
        "d079_terminal_generator": "pass",
        "d080_terminal_generator": "pass",
        "public_tool_inventory": {"result": "pass", "count": 12},
        "binding_identity": descriptor["contract_id"],
        "binding_descriptor_sha256": binding_digest,
        "workflow_contract_sha256": workflow_digest,
        "release_posture": "private_unpublished_development_source_not_frozen",
        "premium_review_executed": False,
    }
    write_json(output / "validation-summary.json", validation)

    d066 = {
        "schema_id": "qcoder.wi0434.preliminary_d066_impact.v1",
        "package_bytes_changed": True,
        "binding_identity_changed": True,
        "protected_identity_changed": False,
        "customer_visible_workflow_behavior_changed": True,
        "affected_profiles": ["CL-025", "CL-026", "CL-028"],
        "omitted_profiles": ["CL-027"],
        "cursor_qualification_owner": "WI-0429",
        "likely_reusable_under_freshness": [
            "unchanged protected service boundary",
            "exact twelve-tool inventory",
            "unchanged authentication entitlement consent and retention contracts",
            "existing raw/path rejection architecture",
        ],
        "reexecution_required": [
            "installed-wheel provenance",
            "machine-readable semantic routing",
            "universal authority assertions affected by D-080",
            "five-seam evidence for new binding and package bytes",
            "Scenario Coverage for source-only/QASM/run/review continuations",
            "stage-ceiling and recovery negatives",
            "workflow completion and timing",
        ],
        "claims_activated": False,
        "formal_cursor_qualification_performed": False,
    }
    write_json(output / "preliminary-d066-impact.json", d066)

    predecessor_paths = [
        Path(
            "/home/rob/projects/_ops/qcoder/d079-wi0432-wi0433-integrated-private-candidate-v1/"
            "independent-high-reasoning-review-v1/packet-manifest.json"
        ),
        Path(
            "/home/rob/projects/_ops/qcoder/d079-wi0432-wi0433-integrated-private-candidate-v1/"
            "post-correction-v1/focused-high-reasoning-recheck-v1/packet-manifest.json"
        ),
        Path(
            "/home/rob/projects/_ops/qcoder/d079-wi0432-wi0433-integrated-private-candidate-v1/"
            "m4-closure-v1/m4-only-review-closure-v1/packet-manifest.json"
        ),
    ]
    predecessor = {
        "schema_id": "qcoder.wi0434.predecessor_review_chain.v1",
        "immutable_packet_manifests": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha(path)}
            for path in predecessor_paths
        ],
        "authorized_handoff_disposition": "FOCUSED_INDEPENDENT_RECHECK_PASS / M4_CLOSED",
        "standalone_final_external_receipt_present": False,
        "freeze_guard": (
            "Import or independently reproduce the missing standalone predecessor external-review "
            "receipt after this premium review and before any immutable successor freeze."
        ),
        "predecessor_evidence_rewritten": False,
        "current_reproduction_packet": {
            "path": str(args.d079_packet.absolute()),
            "manifest_sha256": file_sha(args.d079_packet / "packet-manifest.json"),
        },
    }
    write_json(output / "predecessor-review-chain.json", predecessor)

    readme = f"""# WI-0434 premium adversarial review packet

Review the exact private source `{head}` / tree `{tree}` on branch `{branch}`.

This is the single pre-freeze premium review. It has not yet been executed. Review only the
authority, stage-ceiling, procedural-source, locality, boundedness, cross-client, release-impact,
and customer-usability boundaries enumerated in `invariant-and-adversarial-focus.json`.

Do not redesign D-079, request a thirteenth MCP tool, weaken local-first processing, deploy,
publish, freeze artifacts, activate claims, edit Roadmap records, or treat this packet as formal
Cursor qualification. Contained defects may be returned for narrow correction before freeze.

Terminal evidence:

- WI-0432/WI-0433: `{args.d079_packet.absolute()}`
- WI-0434/semantic matrix/scale/interaction: `{args.d080_packet.absolute()}`
- routine implementation review: `{args.routine_review.absolute()}`
"""
    (output / "README.md").write_text(readme, encoding="utf-8")

    references = {
        "d079_terminal_packet": {
            "path": str(args.d079_packet.absolute()),
            "manifest_sha256": file_sha(args.d079_packet / "packet-manifest.json"),
        },
        "d080_terminal_packet": {
            "path": str(args.d080_packet.absolute()),
            "manifest_sha256": file_sha(args.d080_packet / "packet-manifest.json"),
        },
        "routine_review": {
            "path": str(args.routine_review.absolute()),
            "sha256": file_sha(args.routine_review),
        },
    }
    write_json(output / "evidence-references.json", references)

    inventory = [
        {
            "path": str(path.relative_to(output)),
            "bytes": path.stat().st_size,
            "sha256": file_sha(path),
        }
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "packet-manifest.json"
    ]
    manifest = {
        "schema_id": "qcoder.wi0434.premium_adversarial_review_packet.v1",
        "result": "ready_for_review_not_executed",
        "source": {"branch": branch, "commit": head, "tree": tree, "baseline": args.baseline},
        "binding_identity": descriptor["contract_id"],
        "binding_descriptor_sha256": binding_digest,
        "workflow_contract_sha256": workflow_digest,
        "public_context_bridge_tool_count": len(EXPECTED_TOOLS),
        "inventory": inventory,
        "packet_identity_canonicalization": (
            "sha256 over ensure_ascii=true, sort_keys=true, separators=(',', ':'), "
            "before packet_identity is added"
        ),
    }
    manifest["packet_identity"] = "sha256:" + sha256(canonical(manifest)).hexdigest()
    write_json(output / "packet-manifest.json", manifest)
    print(
        json.dumps(
            {
                "packet": str(output),
                "packet_identity": manifest["packet_identity"],
                "manifest_sha256": file_sha(output / "packet-manifest.json"),
                "binding_identity": descriptor["contract_id"],
                "binding_descriptor_sha256": binding_digest,
                "workflow_contract_sha256": workflow_digest,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
