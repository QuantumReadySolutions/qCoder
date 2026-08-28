#!/usr/bin/env python3
"""Prove that a23 differs from its selected private basis only at release surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from qcoder.context_bridge_mcp import EXPECTED_TOOLS, build_client_binding_descriptor
from qcoder.current_loop_binding_mcp import binding_tool_descriptors

BASIS_COMMIT = "a0d0d39237c2e51c0346fdc0214566c4d473639c"
BASIS_TREE = "580188c5b3225297382fda1e7a8c4a407d393d62"
EXPECTED_VERSION = "0.6.0a23"
EXPECTED_CONTRACT = "qcoder.connected_assistant.client_binding.v47"
EXPECTED_SCHEMA = 46
EXPECTED_PUBLIC_TOOLS = (
    "get_guided_evidence_context",
    "create_prompt_context",
    "create_evidence_context_pack",
    "create_context_session_card",
    "create_run_readiness_card",
    "create_result_review_context_card",
    "create_next_check_plan",
    "create_single_loop_evidence_diff",
    "create_algorithm_intent_card",
    "create_implementation_blueprint",
    "create_generation_context_pack",
    "create_source_blueprint_alignment_review",
)
EXPECTED_PRIVATE_OPERATIONS = ("begin_current_loop", "complete_current_step")
ALLOWED_PATHS = {
    "CHANGELOG.md",
    "README.md",
    "development-version.json",
    "docs/releases/0.6.0a23.md",
    "pyproject.toml",
    "release-version.json",
    "scripts/verify-a23-release-normalization.py",
    "scripts/verify-development-version.py",
    "scripts/verify-release-version.py",
    "scripts/wi0440-natural-campaign-evaluate.py",
    "src/qcoder/__init__.py",
    "tests/test_a23_release_normalization.py",
    "tests/test_local_evidence_review_v1.py",
    "tests/test_public_package_metadata.py",
    "tests/test_release_version_consistency.py",
    "tests/test_wi0440_natural_campaign_evaluator_v1.py",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _changed_paths(root: Path) -> set[str]:
    tracked = set(filter(None, _git(root, "diff", "--name-only", BASIS_COMMIT, "--").splitlines()))
    untracked = set(
        filter(None, _git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    )
    return tracked | untracked


def verify(root: Path) -> dict[str, object]:
    root = root.resolve()
    if _git(root, "rev-parse", f"{BASIS_COMMIT}^{{tree}}") != BASIS_TREE:
        raise ValueError("a23_basis_tree_mismatch")
    changed = _changed_paths(root)
    unexpected = sorted(changed - ALLOWED_PATHS)
    if unexpected:
        raise ValueError(f"a23_normalization_path_outside_allowlist:{unexpected}")
    runtime_changed = sorted(path for path in changed if path.startswith("src/qcoder/"))
    if runtime_changed != ["src/qcoder/__init__.py"]:
        raise ValueError(f"a23_runtime_delta_invalid:{runtime_changed}")
    init_text = (root / "src/qcoder/__init__.py").read_text(encoding="utf-8")
    expected_init = '__all__ = []\n__version__ = "0.6.0a23"\nfile = __file__\n'
    if init_text != expected_init:
        raise ValueError("a23_runtime_version_surface_invalid")
    if (root / "development-version.json").exists() or (
        root / "scripts/verify-development-version.py"
    ).exists():
        raise ValueError("a23_private_development_identity_retained")
    public_tools = tuple(EXPECTED_TOOLS)
    private_operations = tuple(item["name"] for item in binding_tool_descriptors())
    if public_tools != EXPECTED_PUBLIC_TOOLS:
        raise ValueError("a23_public_tool_inventory_changed")
    if private_operations != EXPECTED_PRIVATE_OPERATIONS:
        raise ValueError("a23_private_operation_inventory_changed")
    descriptor = build_client_binding_descriptor(
        coordinator_prefix=["python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    if (
        descriptor.get("contract_id") != EXPECTED_CONTRACT
        or descriptor.get("schema_version") != EXPECTED_SCHEMA
    ):
        raise ValueError("a23_binding_identity_changed")
    descriptor_sha256 = hashlib.sha256(_canonical(descriptor)).hexdigest()
    return {
        "ok": True,
        "result": "pass",
        "basis_commit": BASIS_COMMIT,
        "basis_tree": BASIS_TREE,
        "version": EXPECTED_VERSION,
        "changed_paths": sorted(changed),
        "runtime_delta": runtime_changed,
        "binding_contract": EXPECTED_CONTRACT,
        "binding_schema": EXPECTED_SCHEMA,
        "binding_descriptor_sha256": descriptor_sha256,
        "public_tool_count": len(public_tools),
        "private_operation_count": len(private_operations),
        "behavior_preserving_from_private_basis": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.source_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "result": "fail", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
