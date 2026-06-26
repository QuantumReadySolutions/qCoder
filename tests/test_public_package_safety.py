from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from qcoder.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "qcoder"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_source_tree_excludes_pro_implementation() -> None:
    pro_dir = SRC_ROOT / "pro_v0"
    assert not any(pro_dir.glob("*.py"))


def test_cli_has_no_pro_v0_imports() -> None:
    cli_text = _read(SRC_ROOT / "cli.py")
    assert "qcoder.pro_v0" not in cli_text


def test_pro_preview_manifest_has_no_pro_v0_imports() -> None:
    manifest_text = _read(SRC_ROOT / "pro_preview" / "manifest.py")
    assert "qcoder.pro_v0" not in manifest_text


def test_pro_preview_module_docstring_uses_public_wording() -> None:
    module_text = _read(SRC_ROOT / "pro_preview" / "__init__.py")
    assert "Pro Preview client surface" in module_text
    assert "Pro Preview/V0" not in module_text
    assert "V0 local bootstrap" not in module_text


def test_manifest_excludes_private_alpha_docs() -> None:
    manifest = _read(REPO_ROOT / "MANIFEST.in")
    assert "exclude docs/pro-v0-install.md" in manifest
    assert "exclude docs/private-alpha-quickstart.md" in manifest
    assert "exclude docs/private-alpha-release-candidate-validation.md" in manifest
    assert "prune src/qcoder/pro_v0" in manifest
    assert "graft tests" not in manifest


def test_pro_shell_help_marks_archived_public_boundary() -> None:
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            rc = main(["pro", "--help"])
        except SystemExit as exc:
            rc = int(exc.code)
    assert rc == 0
    text = out.getvalue().lower()
    assert "archived" in text
    assert "not a current public product" in text
    assert "install" in text
    assert "validate" in text


def test_pro_workflow_stub_fails_cleanly_without_service() -> None:
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main(["pro", "workflow", "--qasm", "demo.qasm", "--project-dir", "/tmp/project"])
    assert rc == 2
    text = err.getvalue().lower()
    assert "dry-run-manifest" in text
    assert "--dry-run-manifest" in text


def test_pro_human_output_avoids_internal_v0_terms(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(["pro", "validate"])
    assert rc == 0
    text = out.getvalue()
    assert "pro_v0" not in text
    assert "Pro Preview/V0" not in text
    assert "V0 local bootstrap" not in text
