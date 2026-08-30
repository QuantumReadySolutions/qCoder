from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from qcoder import __version__

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify-release-version.py"


def _verifier():
    spec = importlib.util.spec_from_file_location("release_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_development_identity_preserves_public_a24_release_truth() -> None:
    verifier = _verifier()
    development_version = "0.6.0a24.dev1+deterministic.evidence.usability.pack.v1"
    assert __version__ == development_version
    assert verifier.source_versions(ROOT) == {
        "pyproject": development_version,
        "qcoder.__version__": development_version,
        "release_metadata": "0.6.0a24",
    }
    with pytest.raises(ValueError, match="authoritative_version_mismatch"):
        verifier.verify_release_version(source_root=ROOT, customer_roots=[ROOT / "examples"])
    spec = importlib.util.spec_from_file_location(
        "development_verifier", ROOT / "scripts/verify-development-version.py"
    )
    assert spec is not None and spec.loader is not None
    development_verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(development_verifier)
    result = development_verifier.verify(ROOT)
    assert result == {
        "ok": True,
        "version": development_version,
        "basis_version": "0.6.0a24",
        "public_release_record_unchanged": True,
        "publication_permitted": False,
    }


def _write_fixture(root: Path, metadata: dict[str, object]) -> None:
    (root / "release-version.json").write_text(json.dumps(metadata), encoding="utf-8")


@pytest.mark.parametrize(
    "mutation",
    [
        "remove_public",
        "substitute_public",
        "remove_lineage",
        "substitute_lineage",
        "conflate",
        "reverse_relationships",
        "add_intervening",
        "publication_authority",
        "remove_product_basis",
        "substitute_product_basis",
    ],
)
def test_relationship_record_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    verifier = _verifier()
    data = copy.deepcopy(json.loads((ROOT / "release-version.json").read_text(encoding="utf-8")))
    if mutation == "remove_public":
        del data["public_upgrade_predecessor"]
    elif mutation == "substitute_public":
        data["public_upgrade_predecessor"]["version"] = "0.6.0a21"
    elif mutation == "remove_lineage":
        del data["implementation_lineage_predecessor"]
    elif mutation == "substitute_lineage":
        data["implementation_lineage_predecessor"]["source_commit"] = "0" * 40
    elif mutation == "conflate":
        data["implementation_lineage_predecessor"] = copy.deepcopy(
            data["public_upgrade_predecessor"]
        )
    elif mutation == "reverse_relationships":
        data["public_upgrade_predecessor"]["relationship_to_source"] = (
            verifier.PRODUCT_CORRECTION_BASIS["relationship_to_source"]
        )
    elif mutation == "add_intervening":
        data["intervening_nonpublic_versions"] = [{"version": "0.6.0a22.dev3", "state": "unknown"}]
    elif mutation == "remove_product_basis":
        del data["product_correction_basis"]
    elif mutation == "substitute_product_basis":
        data["product_correction_basis"]["source_commit"] = "0" * 40
    else:
        data["publication_state_authority"] = "embedded_mutable_state"
    _write_fixture(tmp_path, data)
    with pytest.raises(ValueError):
        verifier.release_metadata(tmp_path)


@pytest.mark.parametrize("block_name", ["relationship", "history", "upgrade", "nonclaim"])
@pytest.mark.parametrize("mutation", ["delete", "substitute"])
def test_active_release_copy_mutations_fail_closed(block_name: str, mutation: str) -> None:
    verifier = _verifier()
    blocks = {
        "relationship": verifier.RELATIONSHIP_PRODUCT_BLOCK,
        "history": verifier.HISTORICAL_STATUS_BLOCK,
        "upgrade": verifier.UPGRADE_BLOCK,
        "nonclaim": verifier.NONCLAIM_BLOCK,
    }
    complete = "\n\n".join(blocks.values())
    replacement = "" if mutation == "delete" else "materially altered governed copy"
    with pytest.raises(ValueError, match="release_truth"):
        verifier._validate_active_surface(
            complete.replace(blocks[block_name], replacement, 1), "mutation fixture"
        )


@pytest.mark.parametrize(
    "contradiction",
    [
        "behavior-preserving pre-release successor to public qCoder 0.6.0a22",
        "private candidate was public",
        "private candidate is a customer upgrade predecessor",
        "mid-step migration is supported",
        "receipt reuse is supported",
        "behavior-preserving successor to qCoder 0.6.0a23",
        "qCoder 0.6.0a23 is a customer upgrade predecessor",
        "direct server smoke test establishes client connection",
    ],
)
def test_active_release_contradictions_fail_closed(contradiction: str) -> None:
    verifier = _verifier()
    complete = "\n\n".join(verifier.ACTIVE_BLOCKS)
    with pytest.raises(ValueError, match="release_truth"):
        verifier._validate_active_surface(f"{complete}\n{contradiction}", "mutation fixture")


def test_changelog_and_historical_release_notes_are_guarded() -> None:
    verifier = _verifier()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="changelog"):
        verifier._validate_changelog(changelog.replace(verifier.CHANGELOG_BLOCK, "", 1))
    assert (
        __import__("hashlib").sha256((ROOT / "docs/releases/0.6.0a22.md").read_bytes()).hexdigest()
        == verifier.A22_RELEASE_NOTE_SHA256
    )
    assert (
        __import__("hashlib").sha256((ROOT / "docs/releases/0.6.0a23.md").read_bytes()).hexdigest()
        == verifier.A23_RELEASE_NOTE_SHA256
    )
