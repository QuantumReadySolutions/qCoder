from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from qcoder import __version__


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/verify-release-version.py"
EXPECTED_VERSION = "0.6.0a18+wi0436.structured.intent.recovery.v1"
EXPECTED_PREDECESSOR_VERSION = "0.6.0a16"
EXPECTED_IDENTITY_KIND = "prerelease_successor"
EXPECTED_INTERVENING: list[str] = ["0.6.0a17"]


def _load_verifier():
    spec = importlib.util.spec_from_file_location("qcoder_release_version", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_version_identity_is_wi0436_a18_development_successor() -> None:
    verifier = _load_verifier()
    assert verifier.source_versions(REPO_ROOT) == {
        "pyproject": EXPECTED_VERSION,
        "qcoder.__version__": EXPECTED_VERSION,
        "release_metadata": EXPECTED_VERSION,
    }
    assert __version__ == EXPECTED_VERSION


def test_real_repository_release_identity_has_no_stale_install_pin() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-root",
            str(REPO_ROOT),
            "--customer-root",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["source_version"] == EXPECTED_VERSION
    assert result["release_identity_kind"] == EXPECTED_IDENTITY_KIND
    assert result["predecessor_public_version"] == EXPECTED_PREDECESSOR_VERSION
    assert result["publication_state_authority"] == "external_release_control"
    assert result["customer_pin_files"] == []
    assert result["detected_customer_pin_versions"] == []
    assert result["forbidden_customer_pin_versions"] == [*EXPECTED_INTERVENING, EXPECTED_VERSION]
    assert result["artifact_versions_checked"] is False
    assert result["result"] == "pass"


def _write_candidate_fixture(
    root: Path,
    *,
    pyproject_version: str = EXPECTED_VERSION,
    init_version: str = EXPECTED_VERSION,
    metadata_version: str = EXPECTED_VERSION,
    identity_kind: str = EXPECTED_IDENTITY_KIND,
    predecessor_public_version: str = EXPECTED_PREDECESSOR_VERSION,
    publication_state_authority: str = "external_release_control",
    intervening_versions: list[str] | None = None,
    customer_pin: str | None = None,
) -> None:
    (root / "src/qcoder").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "qcoder"\nversion = "{pyproject_version}"\n',
        encoding="utf-8",
    )
    (root / "src/qcoder/__init__.py").write_text(
        f'__version__ = "{init_version}"\n',
        encoding="utf-8",
    )
    metadata = {
        "schema": "qcoder.release_version_source.v2",
        "source_version": metadata_version,
        "release_identity_kind": identity_kind,
        "predecessor_public_version": predecessor_public_version,
        "publication_state_authority": publication_state_authority,
        "intervening_reserved_versions": (
            EXPECTED_INTERVENING if intervening_versions is None else intervening_versions
        ),
    }
    (root / "release-version.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme = "qCoder prerelease source. Publication governance is external.\n"
    if customer_pin is not None:
        readme += f'python -m pip install "qcoder=={customer_pin}"\n'
    (root / "README.md").write_text(readme, encoding="utf-8")


def _verify_fixture(root: Path):
    return _load_verifier().verify_release_version(source_root=root, customer_roots=[root])


def test_prerelease_successor_without_customer_install_pin_passes(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path)
    result = _verify_fixture(tmp_path)
    assert result["source_version"] == EXPECTED_VERSION
    assert result["customer_pins"] == {}


@pytest.mark.parametrize(
    ("customer_pin", "error"),
    [
        (EXPECTED_VERSION, "release_version_customer_pin"),
        ("0.6.0a8", "customer_package_pin_mismatch"),
        ("0.6.0a4", "customer_package_pin_mismatch"),
    ],
)
def test_release_and_stale_customer_pins_fail(
    tmp_path: Path,
    customer_pin: str,
    error: str,
) -> None:
    _write_candidate_fixture(tmp_path, customer_pin=customer_pin)
    with pytest.raises(ValueError, match=error):
        _verify_fixture(tmp_path)


def test_predecessor_pin_is_permitted_outside_release_package_docs(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path, customer_pin=EXPECTED_PREDECESSOR_VERSION)
    result = _verify_fixture(tmp_path)
    assert result["detected_customer_pin_versions"] == [EXPECTED_PREDECESSOR_VERSION]


def test_source_version_mismatch_fails(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path, init_version="0.6.0a8")
    with pytest.raises(ValueError, match="authoritative_version_mismatch"):
        _verify_fixture(tmp_path)


def test_immutable_metadata_rejects_non_external_publication_authority(tmp_path: Path) -> None:
    _write_candidate_fixture(
        tmp_path,
        publication_state_authority="embedded_mutable_state",
    )
    with pytest.raises(ValueError, match="release_metadata_publication_authority_invalid"):
        _verify_fixture(tmp_path)


def test_intervening_reserved_inventory_must_be_complete(tmp_path: Path) -> None:
    _write_candidate_fixture(
        tmp_path,
        predecessor_public_version="0.6.0a5",
        intervening_versions=[],
    )
    with pytest.raises(ValueError, match="intervening_reserved_versions_mismatch"):
        _verify_fixture(tmp_path)


def test_declared_intervening_reserved_pin_is_rejected(tmp_path: Path) -> None:
    _write_candidate_fixture(
        tmp_path,
        predecessor_public_version="0.6.0a5",
        intervening_versions=[
            "0.6.0a6",
            "0.6.0a7",
            "0.6.0a8",
            "0.6.0a9",
            "0.6.0a10",
            "0.6.0a11",
            "0.6.0a12",
            "0.6.0a13",
            "0.6.0a14",
            "0.6.0a15",
            "0.6.0a16",
            "0.6.0a17",
        ],
        customer_pin="0.6.0a8",
    )
    with pytest.raises(ValueError, match="intervening_reserved_customer_pin"):
        _verify_fixture(tmp_path)


def test_old_candidate_identity_fails(tmp_path: Path) -> None:
    _write_candidate_fixture(
        tmp_path,
        pyproject_version="0.6.0a1",
        init_version="0.6.0a1",
        metadata_version="0.6.0a1",
        predecessor_public_version="0.6.0a0",
        intervening_versions=[],
    )
    with pytest.raises(ValueError, match="candidate_reuses_0.6.0a1"):
        _verify_fixture(tmp_path)
