"""Exact scientific code and installed dependency currentness."""
from importlib.metadata import distributions, version
from pathlib import Path
import platform
import sys

from .contracts import file_digest, seal

PINS = {"numpy": "2.2.6", "scipy": "1.15.3", "scikit-learn": "1.6.1", "pennylane": "0.44.0", "torch": "2.6.0+cpu", "mlflow": "3.1.4"}
CODE_FILES = ("__init__.py", "contracts.py", "fixture.py", "models.py", "training.py", "runtime.py", "job.py", "tracker.py", "__main__.py")


def runtime():
    from .contracts import require
    versions = {name: version(name) for name in PINS}
    require(versions == PINS, "runtime_unqualified")
    return seal({"schema": "d148.runtime.v1", "python": platform.python_version(), "implementation": sys.implementation.name, "platform": platform.platform(), "machine": platform.machine(), "dependencies": dict(sorted((d.metadata["Name"].lower().replace("_", "-"), d.version) for d in distributions() if d.metadata["Name"].lower() not in {"qcoder", "pip"})), "versions": versions, "device": "cpu", "dtype": "float64", "torch_threads": 1, "deterministic_algorithms": True})


def code_identity():
    root = Path(__file__).parent
    from qcoder.focused_loop import canonical
    return seal({"schema": "d148.execution_identity.v2", "files": {name: file_digest(root / name) for name in CODE_FILES}, "canonical_primitive": file_digest(canonical.__file__)})

# Scientific identity intentionally excludes execution/approval/tracker presentation.
# Remaining top-level nodes are included by default; new scientific globals cannot
# silently escape the identity. ASTs normalize formatting, not numerical semantics.
SCIENTIFIC_PINS = {"numpy": "2.2.6", "scipy": "1.15.3", "scikit-learn": "1.6.1", "pennylane": "0.44.0", "torch": "2.6.0+cpu", "gast": "0.6.0", "astunparse": "1.6.3"}
SCIENTIFIC_MODULES = ("__init__.py", "fixture.py", "models.py", "training.py")
SCIENTIFIC_EXCLUSIONS = {
    "contracts.py": ("locked", "now", "file_digest"),
    "runtime.py": ("PINS", "CODE_FILES", "runtime", "code_identity", "approval_identity"),
}


def _component_digest(path, *, exclude=(), only=None):
    """Digest bounded top-level Python syntax without executing source artifacts."""
    import ast
    from qcoder.focused_loop.canonical import canonical_digest
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        names = [getattr(node, "name", None)]
        if isinstance(node, ast.Assign):
            names = [getattr(target, "id", None) for target in node.targets]
        if any(name in exclude for name in names):
            continue
        if only is not None and not isinstance(node, (ast.Import, ast.ImportFrom)) and not any(name in only for name in names):
            continue
        nodes.append(ast.dump(node, include_attributes=False))
    return canonical_digest(nodes)


def _scientific_dependencies():
    """Scientific dependency closure, including PennyLane import support pins."""
    from importlib.metadata import requires
    from packaging.requirements import Requirement
    pending = list(SCIENTIFIC_PINS)
    found = {}
    while pending:
        name = pending.pop().lower().replace("_", "-")
        if name in found:
            continue
        found[name] = version(name)
        for text in requires(name) or ():
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    return dict(sorted(found.items()))


def scientific_runtime():
    from .contracts import require
    versions = {name: version(name) for name in SCIENTIFIC_PINS}
    require(versions == SCIENTIFIC_PINS, "scientific_runtime_unqualified")
    return seal({"schema": "d148.scientific_runtime.v2", "python": platform.python_version(), "implementation": sys.implementation.name, "platform": platform.platform(), "machine": platform.machine(), "dependencies": _scientific_dependencies(), "versions": versions, "device": "cpu", "dtype": "float64", "torch_threads": 1, "deterministic_algorithms": True})


def scientific_identity():
    root = Path(__file__).parent
    from qcoder.focused_loop import canonical
    components = {name: _component_digest(root / name) for name in SCIENTIFIC_MODULES}
    components.update({name: _component_digest(root / name, exclude=excluded) for name, excluded in SCIENTIFIC_EXCLUSIONS.items()})
    return seal({"schema": "d148.scientific_identity.v2", "representation": "python-top-level-AST-v1", "components": components, "excluded_symbols": {name: list(symbols) for name, symbols in SCIENTIFIC_EXCLUSIONS.items()}, "canonical_primitive": file_digest(canonical.__file__)})


def approval_identity():
    root = Path(__file__).parent
    return seal({"schema": "d148.approval_surface.v2", "components": {"job.py": _component_digest(root / "job.py", only=("_approval_summary", "approve", "valid_approval")), "runtime.py": _component_digest(root / "runtime.py", only=("_component_digest", "approval_identity")), "contracts.py": file_digest(root / "contracts.py")}})
