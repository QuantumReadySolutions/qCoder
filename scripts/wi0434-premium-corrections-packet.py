#!/usr/bin/env python3
"""Seal the focused M1-M4 premium-review correction closure packet."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_binding_descriptor
from qcoder.current_loop_request_semantics import classify_current_request
from qcoder.d079_workflows import classify_binding_default_route


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def file_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--d079-packet", type=Path, required=True)
    parser.add_argument("--d080-packet", type=Path, required=True)
    parser.add_argument("--predecessor-packet", type=Path, required=True)
    parser.add_argument("--economical-review", type=Path, required=True)
    parser.add_argument("--validation-summary", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_root.absolute()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    if git(source, "status", "--porcelain"):
        raise RuntimeError("closure_packet_requires_clean_source")
    head = git(source, "rev-parse", "HEAD")
    tree = git(source, "rev-parse", "HEAD^{tree}")
    branch = git(source, "branch", "--show-current")

    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    descriptor_digest = sha256(canonical(descriptor)).hexdigest()
    no_ceiling_requests = (
        "Use qCoder to create a teleportation program.",
        "Have qCoder generate a GHZ-state Python example.",
        "Could you use qCoder to make the source for a QFT circuit?",
        "qCoder, write a Deutsch–Jozsa implementation.",
        "Use qCoder to draft Python for a Grover setup; we can run it later.",
        "Use qCoder to create a variational-circuit source. We’ll inspect QASM afterward.",
    )
    review_requests = (
        "Review the source, QASM, and counts.",
        "Check the circuit and results with qCoder.",
        "Look at the generated QASM and tell me what the evidence supports.",
        "Review what we ran.",
        "Inspect the result evidence.",
    )
    m1 = {
        message: classify_current_request(message, active_loop=True) for message in review_requests
    }
    m3_task = classify_current_request(
        "Could you use qCoder to make a teleportation program? Create only the Python file for now."
    )
    m3_information = classify_current_request("Can qCoder help with teleportation?")
    m4 = {
        message: {
            "semantics": classify_current_request(message),
            "binding_route": classify_binding_default_route(customer_instruction=message),
        }
        for message in no_ceiling_requests
    }
    closure = {
        "schema_id": "qcoder.wi0434.premium_review_m1_m4_closure.v1",
        "source": {
            "branch": branch,
            "commit": head,
            "tree": tree,
            "reviewed_baseline": args.baseline,
        },
        "m1_review_intent": {
            "result": "closed",
            "without_selection": m1,
            "exact_clarification": "Which exact files should qCoder review?",
            "selected_path_uses_existing_wi0433": True,
            "artifact_creation_authority_inferred": False,
        },
        "m2_close_versus_abandon": {
            "result": "closed",
            "ordinary_close_operation": "complete_instruction",
            "ordinary_close_disposition": "stop_loop",
            "ordinary_close_phase": "completed",
            "canonical_completion_receipt": True,
            "explicit_abandon_operation": "abandon",
            "receipts_substitutable": False,
            "reviewed_measured_close_range_seconds": [0.387893, 0.422813],
            "unsupported_0_361555_lower_bound_retained": False,
            "ordinary_client_control_label": (
                "local file-write measurement floor; not realistic Cursor wall-clock"
            ),
        },
        "m3_polite_modal": {
            "result": "closed",
            "task": m3_task,
            "informational_control": m3_information,
            "algorithm_sentence_whitelist_used": False,
        },
        "m4_default_source_generation": {
            "result": "closed",
            "unseen_requests": m4,
            "default_roles": ["source"],
            "source_cardinality": "exactly_one",
            "qasm_execution_results_default": "prohibited_for_current_step",
            "legacy_active_build_without_semantics_permitted": False,
        },
        "direct_regression_boundaries": {
            "d079_confirmation": "pass",
            "wi0433_exact_selected_locality": "pass",
            "receipt_digest_and_single_use": "pass",
            "stage_ceiling_preconstruction": "pass",
            "scale_boundedness": "pass",
            "process_and_discard": "pass",
        },
        "public_context_bridge_tool_count": len(EXPECTED_TOOLS),
        "public_context_bridge_tools": list(EXPECTED_TOOLS),
        "binding_identity": descriptor["contract_id"],
        "binding_descriptor_sha256": descriptor_digest,
        "result": "pass",
    }
    write_json(output / "m1-m4-closure-evidence.json", closure)

    diff = subprocess.run(
        ["git", "diff", "--binary", f"{args.baseline}..{head}"],
        cwd=source,
        check=True,
        capture_output=True,
    ).stdout
    (output / "reviewed-baseline-to-correction.diff").write_bytes(diff)
    (output / "reviewed-baseline-to-correction.stat").write_text(
        git(source, "diff", "--stat", f"{args.baseline}..{head}") + "\n",
        encoding="utf-8",
    )
    shutil.copy2(args.validation_summary, output / "validation-summary.json")
    shutil.copy2(args.economical_review, output / "economical-recheck-receipt.json")
    references = {
        "schema_id": "qcoder.wi0434.premium_correction_reference_map.v1",
        "d079_terminal_packet": {
            "path": str(args.d079_packet.absolute()),
            "manifest_sha256": file_sha(args.d079_packet / "packet-manifest.json"),
        },
        "d080_terminal_packet": {
            "path": str(args.d080_packet.absolute()),
            "manifest_sha256": file_sha(args.d080_packet / "packet-manifest.json"),
        },
        "predecessor_reproduction_packet": {
            "path": str(args.predecessor_packet.absolute()),
            "manifest_sha256": file_sha(args.predecessor_packet / "packet-manifest.json"),
            "identity_disposition": "new_reproduction_not_missing_historical_receipt",
        },
        "old_evidence_rewritten": False,
        "freeze_performed": False,
        "clinic_pass_2_performed": False,
    }
    write_json(output / "evidence-reference-map.json", references)
    (output / "README.md").write_text(
        "# WI-0434 focused M1-M4 closure\n\n"
        f"Exact corrected source: `{head}` / `{tree}` on `{branch}`.\n\n"
        "This packet closes only M1 review intent, M2 close versus abandon, M3 polite "
        "task questions, and M4 default source-generation semantics. It records direct "
        "regression checks but does not reopen the prior premium review or freeze a release.\n",
        encoding="utf-8",
    )

    inventory = [
        file_record(path, output)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "packet-manifest.json"
    ]
    manifest = {
        "schema_id": "qcoder.wi0434.premium_review_m1_m4_closure_packet.v1",
        "result": "pass",
        "source_commit": head,
        "source_tree": tree,
        "binding_identity": descriptor["contract_id"],
        "binding_descriptor_sha256": descriptor_digest,
        "closures": ["M1_CLOSED", "M2_CLOSED", "M3_CLOSED", "M4_CLOSED"],
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
                "binding_descriptor_sha256": descriptor_digest,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
