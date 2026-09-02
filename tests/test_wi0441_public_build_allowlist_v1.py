from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_public_package_allowlist",
    ROOT / "scripts" / "verify_public_package_allowlist.py",
)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def _minimal_tree(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "public-only"
    (root / "src/qcoder/model_packs").mkdir(parents=True)
    for name in [
        "CHANGELOG.md",
        "LICENSE",
        "MANIFEST.in",
        "NOTICE",
        "README.md",
        "pyproject.toml",
    ]:
        (root / name).write_text(name, encoding="utf-8")
    (root / "src/qcoder/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src/qcoder/model_packs/resource_guidance_local_v0.json").write_text(
        "{}\n", encoding="utf-8"
    )
    data = {
        "allowed_python_sources": ["src/qcoder/__init__.py"],
        "allowed_package_data_filenames": [
            "src/qcoder/model_packs/resource_guidance_local_v0.json"
        ],
        "allowed_sdist_root_files": [
            "CHANGELOG.md",
            "LICENSE",
            "MANIFEST.in",
            "NOTICE",
            "README.md",
            "pyproject.toml",
        ],
    }
    return root, data


def test_repository_source_allowlist_is_exact_and_has_no_broad_glob() -> None:
    for cache in (ROOT / "src/qcoder").rglob("__pycache__"):
        shutil.rmtree(cache)
    result = VERIFY.verify_source_tree(ROOT)
    assert result["member_count"] == 127
    manifest = json.loads((ROOT / "packaging/public-package-allowlist-v1.json").read_text())
    assert manifest["allowed_package_data_filenames"] == [
        "src/qcoder/contracts/protected_decision_contract_v1.json",
        "src/qcoder/model_packs/resource_guidance_local_v0.json"
    ]
    packaging = (ROOT / "MANIFEST.in").read_text()
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert "graft " not in packaging
    assert "recursive-include" not in packaging
    assert "model_packs/*.json" not in pyproject


@pytest.mark.parametrize(
    "member",
    [
        "/absolute.py",
        "../traversal.py",
        "qcoder\\backslash.py",
        "qcoder/source.py.map",
        "qcoder/source.pyc",
        "qcoder/editable.egg-link",
        "qcoder/private-policy.tar.gz",
        "docs/roadmap/current/governance.md",
        "docs/private-notes/evidence.md",
        "qcoder/setup.py",
    ],
)
def test_unsafe_archive_member_classes_reject(member: str) -> None:
    with pytest.raises(VERIFY.BoundaryError):
        VERIFY.validate_member_names([member])


def test_duplicate_casefold_and_unicode_confusable_members_reject() -> None:
    with pytest.raises(VERIFY.BoundaryError, match="duplicate"):
        VERIFY.validate_member_names(["qcoder/a.py", "qcoder/a.py"])
    with pytest.raises(VERIFY.BoundaryError, match="case-folding"):
        VERIFY.validate_member_names(["qcoder/A.py", "qcoder/a.py"])
    with pytest.raises(VERIFY.BoundaryError, match="Unicode"):
        VERIFY.validate_member_names(["qcoder/a.py", "ｑcoder/a.py"])


def test_missing_unexpected_generated_stale_private_and_build_hook_reject(tmp_path: Path) -> None:
    root, data = _minimal_tree(tmp_path)
    assert VERIFY.verify_source_tree(root, data)["member_count"] == 2
    target = root / "src/qcoder/__init__.py"
    target.unlink()
    with pytest.raises(VERIFY.BoundaryError, match="missing"):
        VERIFY.verify_source_tree(root, data)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    for name in [
        "private_policy_rules.py",
        "generated.py",
        "module.py.map",
        "stale.pyc",
        "setup.py",
        "payload.zip",
    ]:
        seeded = root / "src/qcoder" / name
        seeded.write_text("seed", encoding="utf-8")
        with pytest.raises(VERIFY.BoundaryError):
            VERIFY.verify_source_tree(root, data)
        seeded.unlink()


def test_symlink_and_hardlink_reject_before_build(tmp_path: Path) -> None:
    root, data = _minimal_tree(tmp_path)
    symlink = root / "src/qcoder/link.py"
    symlink.symlink_to(root / "src/qcoder/__init__.py")
    with pytest.raises(VERIFY.BoundaryError, match="symlink"):
        VERIFY.verify_source_tree(root, data)
    symlink.unlink()
    hardlink = root / "src/qcoder/hard.py"
    try:
        os.link(root / "src/qcoder/__init__.py", hardlink)
    except OSError:
        pytest.skip("hard links unavailable")
    with pytest.raises(VERIFY.BoundaryError, match="hard-linked"):
        VERIFY.verify_source_tree(root, data)


def test_public_only_fixture_has_no_private_repository_mount(tmp_path: Path) -> None:
    root, data = _minimal_tree(tmp_path)
    assert not (root / "qcoder-protected-decision-service").exists()
    assert VERIFY.verify_source_tree(root, data)["member_count"] == 2
    shutil.rmtree(root)
