#!/usr/bin/env python3
"""Independently reproduce and seal the predecessor v22 M4 boundary."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


EXPECTED_COMMIT = "94eabb91a5776264cad4f63831fc4988da303839"
EXPECTED_TREE = "3f49fd079d9101bcab02d5378b68aa0eadbab88d"
EXPECTED_BINDING = "qcoder.connected_assistant.client_binding.v22"


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predecessor-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.predecessor_root.absolute()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)

    head = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    if head != EXPECTED_COMMIT or tree != EXPECTED_TREE:
        raise RuntimeError("predecessor_source_identity_mismatch")
    if git(root, "status", "--porcelain"):
        raise RuntimeError("predecessor_source_not_clean")

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root / "src")
    tests = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_d079_connected_assistant_workflows.py",
            "tests/test_context_bridge_mcp.py",
            "-k",
            "binding or ordinary or twelve or inventory",
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    probe_source = r"""
from hashlib import sha256
import json
from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_binding_descriptor
from qcoder.d079_workflows import classify_binding_default_route

def canonical(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()

descriptor = build_client_binding_descriptor(
    coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
)["client_binding_contract"]
blueprint = classify_binding_default_route(
    customer_instruction=(
        "Help me design a Bell-state Qiskit program. Do not edit or run anything yet."
    )
)
evidence = classify_binding_default_route(
    customer_instruction="Review these selected files with qCoder.",
    selected_paths=("selected.py",),
)
generic = classify_binding_default_route(
    customer_instruction="Create a prompt context with qCoder."
)
print(json.dumps({
    "binding_identity": descriptor["contract_id"],
    "binding_descriptor_sha256": sha256(canonical(descriptor)).hexdigest(),
    "public_tool_count": len(EXPECTED_TOOLS),
    "public_tools": list(EXPECTED_TOOLS),
    "blueprint_route": blueprint,
    "selected_review_route": evidence,
    "generic_fallthrough": generic,
}, sort_keys=True))
"""
    probe = subprocess.run(
        [sys.executable, "-c", probe_source],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(probe.stdout)
    if evidence["binding_identity"] != EXPECTED_BINDING:
        raise RuntimeError("predecessor_binding_identity_mismatch")
    if evidence["public_tool_count"] != 12:
        raise RuntimeError("predecessor_public_tool_inventory_changed")
    for route_name in ("blueprint_route", "selected_review_route"):
        route = evidence[route_name]
        if (
            route["selected_route"] != "named_d079_workflow"
            or route["operation"] != "connected_assistant_workflow"
            or route["raw_mcp_default_entrypoint"] is not False
        ):
            raise RuntimeError(f"predecessor_m4_route_failed:{route_name}")
    if evidence["generic_fallthrough"]["raw_mcp_default_entrypoint"] is not True:
        raise RuntimeError("predecessor_generic_fallthrough_changed")

    reproduction = {
        "schema_id": "qcoder.wi0434.predecessor_m4_independent_reproduction.v1",
        "identity_kind": "new_independent_reproduction_not_historical_receipt",
        "predecessor_source": {
            "commit": head,
            "tree": tree,
            "branch": git(root, "branch", "--show-current"),
            "clean": True,
        },
        "binding_identity": evidence["binding_identity"],
        "binding_descriptor_sha256": evidence["binding_descriptor_sha256"],
        "public_tool_inventory": {
            "count": evidence["public_tool_count"],
            "tools": evidence["public_tools"],
        },
        "m4_boundaries": {
            "blueprint_named_route_precedes_generic": True,
            "selected_review_named_route_precedes_generic": True,
            "generic_single_capability_fallthrough_preserved": True,
            "binding_owned_operation": "connected_assistant_workflow",
            "raw_mcp_default_for_named_workflows": False,
        },
        "focused_test_command": (
            "python -m pytest -q tests/test_d079_connected_assistant_workflows.py "
            "tests/test_context_bridge_mcp.py -k 'binding or ordinary or twelve or inventory'"
        ),
        "focused_test_result": tests.stdout.strip(),
        "result": "pass",
        "historical_predecessor_evidence_rewritten": False,
        "secret_bearing_values_included": False,
    }
    write_json(output / "predecessor-m4-reproduction.json", reproduction)
    manifest = {
        "schema_id": "qcoder.wi0434.predecessor_review_chain_reproduction_packet.v1",
        "result": "pass",
        "identity_disposition": "new_reproduction_not_missing_original_receipt",
        "source_commit": head,
        "source_tree": tree,
        "binding_identity": evidence["binding_identity"],
        "binding_descriptor_sha256": evidence["binding_descriptor_sha256"],
        "inventory": [file_record(output / "predecessor-m4-reproduction.json")],
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
                "manifest_sha256": sha256(
                    (output / "packet-manifest.json").read_bytes()
                ).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
