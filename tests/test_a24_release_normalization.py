from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify-a24-release-normalization.py"


def _verifier():
    spec = importlib.util.spec_from_file_location("a24_normalization", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_a24_release_normalization_passes(tmp_path: Path) -> None:
    release_root = tmp_path / "exact-public-a24"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(ROOT), str(release_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(release_root),
            "checkout",
            "--detach",
            "c7ac21237cb6ce65d36d827cf0c93e78672dbbed",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = _verifier().verify(release_root)
    assert result["ok"] is True
    assert result["product_basis_commit"] == "75babdcc27f894094f776bc9e3d1382ab9e1496f"
    assert result["product_basis_tree"] == "6887f0fbdf27cfce7c2316f2eed336f663ac2bf2"
    assert result["terminal_a23_commit"] == "9c984936ab0067d2109eb24b9b1ea072b09b686d"
    assert result["terminal_a23_tree"] == "ea21765a855ed03642e729b10453bdfc17b8d27e"
    assert result["runtime_delta"] == ["src/qcoder/__init__.py"]
    assert result["public_tool_count"] == 12
    assert result["private_operation_count"] == 2
    assert result["behavior_preserving_from_product_basis"] is True
    assert result["behavior_changing_from_terminal_a23"] is True
    assert result["terminal_a23_release_note_immutable"] is True


def test_allowlist_rejects_runtime_and_unrelated_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _verifier()

    def exact_trees(_root: Path, *args: str) -> str:
        return (
            verifier.PRODUCT_BASIS_TREE
            if verifier.PRODUCT_BASIS_COMMIT in " ".join(args)
            else verifier.TERMINAL_A23_TREE
        )

    monkeypatch.setattr(verifier, "_git", exact_trees)
    monkeypatch.setattr(
        verifier,
        "_changed_paths",
        lambda _root: {"README.md", "src/qcoder/context_bridge_mcp.py"},
    )
    with pytest.raises(ValueError, match="outside_allowlist"):
        verifier.verify(ROOT)


def test_wrong_product_basis_tree_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _verifier()
    monkeypatch.setattr(verifier, "_git", lambda *_args: "0" * 40)
    with pytest.raises(ValueError, match="product_basis_tree_mismatch"):
        verifier.verify(ROOT)


def test_terminal_a23_tree_is_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _verifier()

    def fake_git(_root: Path, *args: str) -> str:
        joined = " ".join(args)
        if verifier.PRODUCT_BASIS_COMMIT in joined:
            return verifier.PRODUCT_BASIS_TREE
        return "0" * 40

    monkeypatch.setattr(verifier, "_git", fake_git)
    with pytest.raises(ValueError, match="terminal_a23_tree_mismatch"):
        verifier.verify(ROOT)
