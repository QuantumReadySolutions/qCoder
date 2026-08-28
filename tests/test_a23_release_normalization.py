from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify-a23-release-normalization.py"


def _verifier():
    spec = importlib.util.spec_from_file_location("a23_normalization", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_a23_release_normalization_passes() -> None:
    result = _verifier().verify(ROOT)
    assert result["ok"] is True
    assert result["basis_commit"] == "a0d0d39237c2e51c0346fdc0214566c4d473639c"
    assert result["basis_tree"] == "580188c5b3225297382fda1e7a8c4a407d393d62"
    assert result["runtime_delta"] == ["src/qcoder/__init__.py"]
    assert result["public_tool_count"] == 12
    assert result["private_operation_count"] == 2
    assert result["behavior_preserving_from_private_basis"] is True


def test_allowlist_rejects_runtime_and_unrelated_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _verifier()
    monkeypatch.setattr(verifier, "_git", lambda *_args: verifier.BASIS_TREE)
    monkeypatch.setattr(
        verifier,
        "_changed_paths",
        lambda _root: {"README.md", "src/qcoder/context_bridge_mcp.py"},
    )
    with pytest.raises(ValueError, match="outside_allowlist"):
        verifier.verify(ROOT)


def test_wrong_basis_tree_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _verifier()
    monkeypatch.setattr(verifier, "_git", lambda *_args: "0" * 40)
    with pytest.raises(ValueError, match="basis_tree_mismatch"):
        verifier.verify(ROOT)
