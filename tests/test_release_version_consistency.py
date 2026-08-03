from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from qcoder import __version__


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/verify-release-version.py"
EXPECTED_VERSION = "0.6.0a7"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("qcoder_release_version", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_version_identity_is_prefreeze_cross_client_hardening() -> None:
    verifier = _load_verifier()
    versions = verifier.source_versions(REPO_ROOT)
    assert versions == {
        "pyproject": EXPECTED_VERSION,
        "qcoder.__version__": EXPECTED_VERSION,
    }
    assert __version__ == EXPECTED_VERSION


def test_release_identity_agrees_without_building_package_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verifier = _load_verifier()
    wheel = tmp_path / f"qcoder-{EXPECTED_VERSION}-py3-none-any.whl"
    sdist = tmp_path / f"qcoder-{EXPECTED_VERSION}.tar.gz"
    monkeypatch.setattr(verifier, "wheel_version", lambda _path: EXPECTED_VERSION)
    monkeypatch.setattr(verifier, "sdist_version", lambda _path: EXPECTED_VERSION)
    monkeypatch.setattr(
        verifier,
        "customer_pin_versions",
        lambda _roots: {"candidate-source-identity": [EXPECTED_VERSION]},
    )
    result = verifier.verify_release_version(
        source_root=REPO_ROOT,
        wheel=wheel,
        sdist=sdist,
        customer_roots=[REPO_ROOT],
    )
    assert result["version"] == EXPECTED_VERSION
    assert result["public_version"] == "0.6.0a7"
    assert result["private_candidate_identity"] is False
    assert result["old_candidate_identity_absent"] is True


def test_old_or_mixed_candidate_identity_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verifier = _load_verifier()
    monkeypatch.setattr(
        verifier,
        "source_versions",
        lambda _root: {
            "pyproject": "0.6.0a1",
            "qcoder.__version__": "0.6.0a1",
        },
    )
    monkeypatch.setattr(verifier, "wheel_version", lambda _path: "0.6.0a1")
    monkeypatch.setattr(verifier, "sdist_version", lambda _path: "0.6.0a1")
    monkeypatch.setattr(
        verifier,
        "customer_pin_versions",
        lambda _roots: {"README.md": ["0.6.0a1"]},
    )
    with pytest.raises(ValueError, match="candidate_reuses_0.6.0a1"):
        verifier.verify_release_version(
            source_root=tmp_path,
            wheel=tmp_path / "candidate.whl",
            sdist=tmp_path / "candidate.tar.gz",
            customer_roots=[tmp_path],
        )
