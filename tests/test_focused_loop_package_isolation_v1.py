"""Conference-branch isolation and provisional package-closure proof.

The D-143 Phase A source-isolation invariants remain controlling: no focused-loop
production module may import Current Loop production integration or protected policy,
and the bounded executor remains incapable of shell, package installation, arbitrary
customer Python, or network-provider execution.

This conference branch additionally prototypes the smallest source-package closure
needed for an unpublished local wheel: only qcoder.focused_loop and qcoder.executors
and their exact Python files are added to the existing public package allowlist. This
does not claim post-WI-0441 production integration, installed-wheel acceptance, release
authority, or public-demo authority.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

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

#: Phase A production source must not integrate with these hot files at all. There is no
#: production-source exception: strict-manifest composition is Phase B work, so the v3
#: compatibility proof lives in test support instead.
PROHIBITED_INTEGRATION_MODULES = frozenset(
    {
        "qcoder.context_bridge_connection",
        "qcoder.context_bridge_mcp",
        "qcoder.current_step_contract",
    }
)

#: Every ``qcoder.current_loop_*`` module, including the strict result manifest, is
#: prohibited in new production source. Matching is by prefix so a future current-loop
#: module cannot slip in simply by not being listed above.
PROHIBITED_INTEGRATION_PREFIXES = ("qcoder.current_loop",)

#: Evidence wording for the one known, intentional Phase B consequence.
PACKAGE_ALLOWLIST_STATUS = "CONFERENCE_PROVISIONAL_SOURCE_PACKAGE_CLOSURE"


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

    current_loop = {
        module
        for module in modules
        if any(module.startswith(prefix) for prefix in PROHIBITED_INTEGRATION_PREFIXES)
    }
    assert not current_loop, (
        f"{path.name} imports current-loop module(s) {sorted(current_loop)}; "
        "strict-manifest composition belongs in test support until Phase B"
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


def test_no_production_source_imports_any_current_loop_module() -> None:
    """Package-level invariant, stated once and without any per-file exception."""
    offenders: dict[str, list[str]] = {}
    for path in _source_files():
        modules = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        found = sorted(
            module
            for module in modules
            if any(module.startswith(prefix) for prefix in PROHIBITED_INTEGRATION_PREFIXES)
        )
        if found:
            offenders[path.name] = found
    assert offenders == {}, f"new production source imports current-loop modules: {offenders}"


def test_importing_production_source_loads_no_current_loop_module() -> None:
    """Runtime proof, not just a static one: the real import graph stays clean.

    A static AST check can miss a lazy or transitive import, so this imports every new
    production module in a fresh interpreter and inspects ``sys.modules``.
    """
    modules = [
        f"qcoder.focused_loop.{name}"
        for name in sorted(
            path.stem
            for path in (REPO_ROOT / "src" / "qcoder" / "focused_loop").glob("*.py")
            if path.stem != "__init__"
        )
    ] + ["qcoder.executors.aer_stabilizer_v1"]
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'src')!r})\n"
        f"for name in {modules!r}:\n"
        "    __import__(name)\n"
        "print(sorted(m for m in sys.modules if m.startswith('qcoder.current_loop')))\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, no shell, no user input
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]", (
        f"production imports pulled in current-loop modules: {completed.stdout.strip()}"
    )


def test_v3_compatibility_proof_lives_in_test_support_and_uses_the_real_validator() -> None:
    """The proof must be retained, out of production, and bound to the real module."""
    support = REPO_ROOT / "tests" / "focused_loop_manifest_v3_test_support.py"
    assert support.exists(), "the v3 compatibility proof must still exist"
    tree = ast.parse(support.read_text(encoding="utf-8"))
    modules = _imported_modules(tree)
    assert "qcoder.current_loop_result_manifest" in modules, (
        "the compatibility proof must import the real unmodified v3 validator"
    )
    # The generic joins must be reused from production, not reimplemented here.
    assert "qcoder.focused_loop.attempt_join" in modules

    # No fake, forked, or relaxed validator may stand in for the real one. This is an
    # AST check, not a text search, so the prose above may name what it refuses to do.
    forbidden_definitions = frozenset(
        {"normalize_strict_result_manifest", "StrictResultManifestError"}
    )
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert node.name not in forbidden_definitions, (
                f"{node.name} would fork or shadow the real validator"
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "setattr", "the real validator must not be patched"
        if isinstance(node, ast.Name):
            assert node.id != "monkeypatch", "the real validator must not be monkeypatched"


def test_conference_package_allowlist_closes_only_the_focused_source_packages() -> None:
    """The prototype package delta is exactly the two D-143 source packages.

    This proves source/package inventory closure only. It is not an installed-wheel
    acceptance or a production-integration claim.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"qcoder.focused_loop"' in pyproject
    assert '"qcoder.executors"' in pyproject

    allowlist = json.loads(
        (REPO_ROOT / "packaging" / "public-package-allowlist-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert "qcoder.focused_loop" in allowlist["allowed_packages"]
    assert "qcoder.executors" in allowlist["allowed_packages"]

    allowed_sources = set(allowlist["allowed_python_sources"])
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for path in _source_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        assert relative in allowed_sources
        assert f"include {relative}" in manifest

    assert PACKAGE_ALLOWLIST_STATUS == "CONFERENCE_PROVISIONAL_SOURCE_PACKAGE_CLOSURE"
