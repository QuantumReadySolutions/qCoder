"""Identity boundaries tested on inert source copies; no canonical models run."""
import shutil
from pathlib import Path

import pytest

from qcoder.ml_research import runtime


@pytest.mark.parametrize("filename,before,after,scientific,approval", [
    ("job.py", "[y/N]", "[Y/n]", False, True),
    ("__main__.py", "D-148 local analytic ML research", "D-148 human-readable research", False, False),
    ("tracker.py", "Predeclared accuracy", "Fixed accuracy", False, False),
    ("models.py", '"learning_rate": 0.03', '"learning_rate": 0.04', True, False),
    ("fixture.py", "314159", "314160", True, False),
    ("training.py", "def train(", "def train_changed(", True, False),
    ("contracts.py", "def metric(", "def metric_changed(", True, True),
    ("contracts.py", "def locked(", "def locked_changed(", True, True),
    ("runtime.py", '"mlflow": "3.1.4"', '"mlflow": "3.1.5"', False, False),
    ("runtime.py", 'SCIENTIFIC_PINS = {"numpy": "2.2.6"', 'SCIENTIFIC_PINS = {"numpy": "2.2.7"', True, False),
])
def test_identity_domains(tmp_path, monkeypatch, filename, before, after, scientific, approval):
    source = Path(runtime.__file__).parent
    for name in runtime.CODE_FILES:
        shutil.copyfile(source / name, tmp_path / name)
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "runtime.py"))
    old = (runtime.scientific_identity(), runtime.code_identity(), runtime.approval_identity())
    path = tmp_path / filename
    text = path.read_text()
    assert before in text
    path.write_text(text.replace(before, after, 1) + "\n# inert byte-change witness\n")
    new = (runtime.scientific_identity(), runtime.code_identity(), runtime.approval_identity())
    assert (new[0] != old[0]) == scientific
    assert new[1] != old[1]
    assert (new[2] != old[2]) == approval


def test_pure_state_lock_body_excluded_from_scientific_identity(tmp_path, monkeypatch):
    source = Path(runtime.__file__).parent
    for name in runtime.CODE_FILES:
        shutil.copyfile(source / name, tmp_path / name)
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "runtime.py"))
    old = runtime.scientific_identity()
    path = tmp_path / "contracts.py"
    text = path.read_text()
    # Rename introduces an unknown top-level symbol (fail closed above); changing
    # the explicitly excluded lock implementation alone is execution provenance.
    text = text.replace("def locked(root):", "def locked(root):\n    inert_lock_marker = 1")
    path.write_text(text)
    assert runtime.scientific_identity() == old


def test_scientific_runtime_is_explicit_numerical_closure():
    profile = runtime.scientific_runtime()
    assert profile["versions"] == runtime.SCIENTIFIC_PINS
    assert "mlflow" not in profile["dependencies"]
    assert all(runtime.runtime()["dependencies"][name] == version for name, version in profile["dependencies"].items())
