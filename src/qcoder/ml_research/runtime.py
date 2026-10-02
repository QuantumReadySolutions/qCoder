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
    return seal({"schema": "d148.code.v1", "files": {name: file_digest(root / name) for name in CODE_FILES}, "canonical_primitive": file_digest(canonical.__file__)})
