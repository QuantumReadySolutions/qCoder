"""Static isolation proof for the Phase A focused-loop source.

These checks are deliberately independent of the focused-loop implementation: they
parse the new source files and assert structural properties rather than calling the
code. They stand in for the packaging half of P26 while the final post-WI-0441 import
graph and package allowlist remain unaccepted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NEW_SOURCE_DIRS = (
    REPO_ROOT / "src" / "qcoder" / "focused_loop",
    REPO_ROOT / "src" / "qcoder" / "executors",
)

#: Protected-tier identifiers that must never appear in public source.
PROTECTED_MARKERS = (
    "qcoder_protected_decision_service",
    "qcoder-protected-decision-service",
    "protected_decision_service",
)

#: Modules that would give the bounded executor unbounded reach.
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "http",
        "httpx",
        "importlib",
        "pip",
        "requests",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
        "webbrowser",
        "xmlrpc",
    }
)

#: Dynamic-execution builtins that must not be called anywhere in the new source.
FORBIDDEN_CALL_NAMES = frozenset({"compile", "eval", "exec", "execfile", "system"})

#: Phase A must not integrate with these hot files. The strict result manifest is the
#: single deliberate exception: the adapter imports its real validator read-only to
#: prove compatibility without editing or reinterpreting it.
PROHIBITED_INTEGRATION_MODULES = frozenset(
    {
        "qcoder.context_bridge_connection",
        "qcoder.context_bridge_mcp",
        "qcoder.current_loop_artifact_targets",
        "qcoder.current_loop_coordinator_public_kernel",
        "qcoder.current_loop_evidence_reconciler",
        "qcoder.current_loop_request_semantics",
        "qcoder.current_step_contract",
    }
)
MANIFEST_MODULE = "qcoder.current_loop_result_manifest"
MANIFEST_IMPORT_ALLOWED_IN = frozenset({"manifest_adapter.py"})


def _source_files() -> list[Path]:
    files: list[Path] = []
    for directory in NEW_SOURCE_DIRS:
        if directory.exists():
            files.extend(sorted(directory.rglob("*.py")))
    return files


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def test_new_source_directories_exist() -> None:
    assert _source_files(), "expected Phase A focused-loop source files to exist"


@pytest.mark.parametrize("path", _source_files(), ids=lambda path: path.name)
def test_source_file_is_isolated(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    modules = _imported_modules(tree)

    for marker in PROTECTED_MARKERS:
        assert marker not in text, f"{path.name} references protected tier marker {marker}"

    for module in modules:
        root = module.split(".")[0]
        assert root not in FORBIDDEN_IMPORT_ROOTS, f"{path.name} imports {module}"

    prohibited = modules & PROHIBITED_INTEGRATION_MODULES
    assert not prohibited, f"{path.name} imports prohibited integration module(s) {prohibited}"

    if MANIFEST_MODULE in modules:
        assert path.name in MANIFEST_IMPORT_ALLOWED_IN, (
            f"{path.name} may not import {MANIFEST_MODULE}"
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            assert name not in FORBIDDEN_CALL_NAMES, f"{path.name} calls {name}()"


def test_focused_loop_does_not_import_executors_package() -> None:
    """The schema/science core must not depend on the executor implementation."""
    for path in sorted((REPO_ROOT / "src" / "qcoder" / "focused_loop").rglob("*.py")):
        modules = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        assert not any(
            module.startswith("qcoder.executors") for module in modules
        ), f"{path.name} imports the executor package"


def test_no_protected_marker_anywhere_in_new_tests() -> None:
    """No new test may name the protected tier. This file declares the markers itself."""
    for path in sorted(REPO_ROOT.glob("tests/test_focused_loop_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in PROTECTED_MARKERS:
            assert marker not in text, f"{path.name} references protected marker {marker}"


def test_production_package_allowlist_unchanged() -> None:
    """Phase A must not speculatively add itself to the packaging allowlist."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"qcoder.focused_loop"' not in pyproject
    assert '"qcoder.executors"' not in pyproject
