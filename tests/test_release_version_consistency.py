from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tarfile
import zipfile

import pytest

from qcoder import __version__


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/verify-release-version.py"
EXPECTED_VERSION = "0.6.0a2+wi0418.workstylerouting1"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("qcoder_release_version", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_version_identity_is_workstyle_routing_candidate() -> None:
    verifier = _load_verifier()
    versions = verifier.source_versions(REPO_ROOT)
    assert versions == {
        "pyproject": EXPECTED_VERSION,
        "qcoder.__version__": EXPECTED_VERSION,
    }
    assert __version__ == EXPECTED_VERSION


def test_built_wheel_sdist_and_customer_pin_agree(tmp_path: Path) -> None:
    verifier = _load_verifier()
    wheel = tmp_path / f"qcoder-{EXPECTED_VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"qcoder-{EXPECTED_VERSION}.dist-info/METADATA",
            (f"Metadata-Version: 2.4\nName: qcoder\nVersion: {EXPECTED_VERSION}\n"),
        )
    sdist = tmp_path / f"qcoder-{EXPECTED_VERSION}.tar.gz"
    metadata = (f"Metadata-Version: 2.4\nName: qcoder\nVersion: {EXPECTED_VERSION}\n").encode()
    info = tarfile.TarInfo(f"qcoder-{EXPECTED_VERSION}/PKG-INFO")
    info.size = len(metadata)
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(metadata))
    result = verifier.verify_release_version(
        source_root=REPO_ROOT,
        wheel=wheel,
        sdist=sdist,
        customer_roots=[REPO_ROOT],
    )
    assert result["version"] == EXPECTED_VERSION
    assert result["public_version"] == "0.6.0a2"
    assert result["private_candidate_identity"] is True
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
