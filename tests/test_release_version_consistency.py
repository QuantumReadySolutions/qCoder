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
EXPECTED_VERSION = "0.6.0a7"
EXPECTED_PUBLIC_VERSION = "0.6.0a5"
EXPECTED_POSTURE = "unpublished_candidate"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("qcoder_release_version", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_version_identity_is_a7_unpublished_correction_candidate() -> None:
    verifier = _load_verifier()
    versions = verifier.source_versions(REPO_ROOT)
    assert versions == {
        "pyproject": EXPECTED_VERSION,
        "qcoder.__version__": EXPECTED_VERSION,
        "release_metadata": EXPECTED_VERSION,
    }
    assert __version__ == EXPECTED_VERSION


def test_real_repository_release_identity_and_customer_pin_scan() -> None:
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
    assert result["source_posture"] == EXPECTED_POSTURE
    assert result["current_public_version"] == EXPECTED_PUBLIC_VERSION
    assert result["customer_pin_files"] == ["README.md"]
    assert result["detected_customer_pin_versions"] == [EXPECTED_PUBLIC_VERSION]
    assert result["candidate_pin_occurrences"] == []
    assert result["intervening_unpublished_pin_occurrences"] == []
    assert result["rejected_or_unpublished_pin_occurrences"] == []
    assert result["forbidden_customer_pin_versions"] == ["0.6.0a6", "0.6.0a7"]
    assert result["customer_pins"] == {"README.md": [EXPECTED_PUBLIC_VERSION]}
    assert result["result"] == "pass"
    assert result["private_candidate_identity"] is False
    assert result["old_candidate_identity_absent"] is True
    assert result["artifact_versions_checked"] is False


def _write_candidate_fixture(
    root: Path,
    *,
    pyproject_version: str = EXPECTED_VERSION,
    init_version: str = EXPECTED_VERSION,
    metadata_version: str = EXPECTED_VERSION,
    posture: str = EXPECTED_POSTURE,
    current_public_version: str = EXPECTED_PUBLIC_VERSION,
    published: bool = False,
    publicly_installable: bool = False,
    intervening_versions: list[str] | None = None,
    customer_pin: str | None = EXPECTED_PUBLIC_VERSION,
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
        "schema": "qcoder.release_version_source.v1",
        "source_version": metadata_version,
        "source_posture": posture,
        "current_public_version": current_public_version,
        "published": published,
        "publicly_installable": publicly_installable,
        "intervening_unpublished_versions": (
            ["0.6.0a6"] if intervening_versions is None else intervening_versions
        ),
    }
    (root / "release-version.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme = "qCoder candidate source. Not published or publicly installable.\n"
    if customer_pin is not None:
        readme += f'python -m pip install "qcoder=={customer_pin}"\n'
    (root / "README.md").write_text(readme, encoding="utf-8")


def _verify_fixture(root: Path):
    verifier = _load_verifier()
    return verifier.verify_release_version(source_root=root, customer_roots=[root])


def test_synthetic_unpublished_candidate_posture_passes(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path)
    result = _verify_fixture(tmp_path)
    assert result["source_version"] == EXPECTED_VERSION
    assert result["current_public_version"] == EXPECTED_PUBLIC_VERSION
    assert result["detected_customer_pin_versions"] == [EXPECTED_PUBLIC_VERSION]


@pytest.mark.parametrize(
    ("customer_pin", "error"),
    [
        (EXPECTED_VERSION, "unpublished_candidate_customer_pin"),
        ("0.6.0a6", "unpublished_intervening_customer_pin"),
        ("0.6.0a4", "customer_package_pin_mismatch"),
    ],
)
def test_customer_pin_must_be_exact_current_public_version(
    tmp_path: Path,
    customer_pin: str,
    error: str,
) -> None:
    _write_candidate_fixture(tmp_path, customer_pin=customer_pin)
    with pytest.raises(ValueError, match=error):
        _verify_fixture(tmp_path)


def test_source_version_mismatch_fails(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path, init_version="0.6.0a6")
    with pytest.raises(ValueError, match="authoritative_version_mismatch"):
        _verify_fixture(tmp_path)


@pytest.mark.parametrize(
    ("published", "publicly_installable", "error"),
    [
        (True, False, "unpublished_candidate_marked_published"),
        (False, True, "unpublished_candidate_marked_publicly_installable"),
    ],
)
def test_unpublished_candidate_metadata_cannot_claim_publication(
    tmp_path: Path,
    published: bool,
    publicly_installable: bool,
    error: str,
) -> None:
    _write_candidate_fixture(
        tmp_path,
        published=published,
        publicly_installable=publicly_installable,
    )
    with pytest.raises(ValueError, match=error):
        _verify_fixture(tmp_path)


def test_unpublished_candidate_cannot_equal_public_version(tmp_path: Path) -> None:
    _write_candidate_fixture(
        tmp_path,
        current_public_version=EXPECTED_VERSION,
        intervening_versions=[],
    )
    with pytest.raises(ValueError, match="unpublished_candidate_equals_current_public_version"):
        _verify_fixture(tmp_path)


def test_public_version_cannot_be_newer_than_source(tmp_path: Path) -> None:
    _write_candidate_fixture(
        tmp_path,
        current_public_version="0.6.0a8",
        intervening_versions=[],
        customer_pin="0.6.0a8",
    )
    with pytest.raises(ValueError, match="candidate_not_newer_than_current_public_version"):
        _verify_fixture(tmp_path)


def test_customer_pin_is_required(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path, customer_pin=None)
    with pytest.raises(ValueError, match="customer_package_pin_missing"):
        _verify_fixture(tmp_path)


def test_unsupported_release_posture_fails(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path, posture="ambiguous")
    with pytest.raises(ValueError, match="unsupported_release_posture"):
        _verify_fixture(tmp_path)


def test_intervening_unpublished_inventory_must_be_complete(tmp_path: Path) -> None:
    _write_candidate_fixture(tmp_path, intervening_versions=[])
    with pytest.raises(ValueError, match="intervening_unpublished_versions_mismatch"):
        _verify_fixture(tmp_path)


def test_old_candidate_identity_fails(tmp_path: Path) -> None:
    _write_candidate_fixture(
        tmp_path,
        pyproject_version="0.6.0a1",
        init_version="0.6.0a1",
        metadata_version="0.6.0a1",
        current_public_version="0.6.0a0",
        intervening_versions=[],
        customer_pin="0.6.0a0",
    )
    with pytest.raises(ValueError, match="candidate_reuses_0.6.0a1"):
        _verify_fixture(tmp_path)
