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


def test_private_development_identity_preserves_public_a22_release_record() -> None:
    verifier = _verifier()
    assert __version__ == "0.6.0a22.dev2+wi0440.natural.first.value.v1"
    assert verifier.source_versions(ROOT) == {
        "pyproject": "0.6.0a22.dev2+wi0440.natural.first.value.v1",
        "qcoder.__version__": "0.6.0a22.dev2+wi0440.natural.first.value.v1",
        "release_metadata": "0.6.0a22",
    }
    with pytest.raises(ValueError, match="authoritative_version_mismatch"):
        verifier.verify_release_version(source_root=ROOT, customer_roots=[ROOT])
    spec = importlib.util.spec_from_file_location(
        "development_verifier", ROOT / "scripts/verify-development-version.py"
    )
    assert spec is not None and spec.loader is not None
    development_verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(development_verifier)
    result = development_verifier.verify(ROOT)
    assert result["ok"] is True
    assert result["basis_version"] == "0.6.0a22"
    assert result["publication_permitted"] is False


def _write_fixture(root: Path, metadata: dict[str, object]) -> None:
    (root / "src/qcoder").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname="qcoder"\nversion="0.6.0a22"\n')
    (root / "src/qcoder/__init__.py").write_text('__version__ = "0.6.0a22"\n')
    (root / "release-version.json").write_text(json.dumps(metadata))
    (root / "README.md").write_text("durable release source\n")


@pytest.mark.parametrize(
    "mutation",
    [
        "remove_public",
        "substitute_public",
        "remove_lineage",
        "substitute_lineage",
        "conflate",
        "reverse_versions",
        "reverse_relationships",
        "public_a19",
        "publishable_a20",
        "public_a21",
    ],
)
def test_relationship_record_mutation_matrix_fails_closed(tmp_path: Path, mutation: str) -> None:
    verifier = _verifier()
    data = copy.deepcopy(json.loads((ROOT / "release-version.json").read_text()))
    if mutation == "remove_public":
        del data["public_upgrade_predecessor"]
    elif mutation == "substitute_public":
        data["public_upgrade_predecessor"]["version"] = "0.6.0a17"
    elif mutation == "remove_lineage":
        del data["implementation_lineage_predecessor"]
    elif mutation == "substitute_lineage":
        data["implementation_lineage_predecessor"]["version"] = "0.6.0a20"
    elif mutation == "conflate":
        data["implementation_lineage_predecessor"] = copy.deepcopy(
            data["public_upgrade_predecessor"]
        )
    elif mutation == "reverse_versions":
        (
            data["public_upgrade_predecessor"]["version"],
            data["implementation_lineage_predecessor"]["version"],
        ) = (
            data["implementation_lineage_predecessor"]["version"],
            data["public_upgrade_predecessor"]["version"],
        )
    elif mutation == "reverse_relationships":
        data["public_upgrade_predecessor"]["relationship_to_source"] = (
            "behavior_preserving_except_release_identity_publication_truth_and_release_tooling"
        )
        data["implementation_lineage_predecessor"]["relationship_to_source"] = "behavior_changing"
    elif mutation == "public_a19":
        data["intervening_nonpublic_versions"][0]["state"] = "published"
    elif mutation == "publishable_a20":
        data["intervening_nonpublic_versions"][1]["state"] = "publishable"
    elif mutation == "public_a21":
        data["intervening_nonpublic_versions"][2]["state"] = "public_customer_predecessor"
    _write_fixture(tmp_path, data)
    with pytest.raises(ValueError):
        verifier.release_metadata(tmp_path)


def test_non_external_publication_authority_fails(tmp_path: Path) -> None:
    verifier = _verifier()
    data = copy.deepcopy(json.loads((ROOT / "release-version.json").read_text()))
    data["publication_state_authority"] = "embedded_mutable_state"
    _write_fixture(tmp_path, data)
    with pytest.raises(ValueError, match="publication_authority"):
        verifier.release_metadata(tmp_path)


@pytest.mark.parametrize("block_name", ["relationship", "history", "upgrade", "nonclaim"])
@pytest.mark.parametrize("mutation", ["delete", "substitute"])
def test_active_publication_copy_mutations_fail_closed(block_name: str, mutation: str) -> None:
    verifier = _verifier()
    blocks = {
        "relationship": verifier.RELATIONSHIP_PRODUCT_BLOCK,
        "history": verifier.HISTORICAL_STATUS_BLOCK,
        "upgrade": verifier.UPGRADE_BLOCK,
        "nonclaim": verifier.NONCLAIM_BLOCK,
    }
    complete = "\n\n".join(blocks.values())
    replacement = "" if mutation == "delete" else "materially altered governed copy"
    mutated = complete.replace(blocks[block_name], replacement, 1)
    with pytest.raises(ValueError, match="publication_truth"):
        verifier._validate_active_surface(mutated, "mutation fixture")


@pytest.mark.parametrize(
    "mutation",
    [
        "conflate_arrows",
        "reverse_arrows",
        "reverse_relationship_labels",
        "public_a21",
        "remove_contract_change",
        "support_mid_step",
        "support_receipt_reuse",
    ],
)
def test_active_relationship_contradiction_matrix_fails_closed(mutation: str) -> None:
    verifier = _verifier()
    complete = verifier._normalized("\n\n".join(verifier.ACTIVE_BLOCKS))
    if mutation == "conflate_arrows":
        mutated = complete.replace(
            "qCoder 0.6.0a21 → qCoder 0.6.0a22",
            "qCoder 0.6.0a18 → qCoder 0.6.0a22",
            1,
        )
    elif mutation == "reverse_arrows":
        mutated = complete.replace("qCoder 0.6.0a18 → qCoder 0.6.0a22", "__PUBLIC__", 1)
        mutated = mutated.replace(
            "qCoder 0.6.0a21 → qCoder 0.6.0a22",
            "qCoder 0.6.0a18 → qCoder 0.6.0a22",
            1,
        ).replace("__PUBLIC__", "qCoder 0.6.0a21 → qCoder 0.6.0a22", 1)
    elif mutation == "reverse_relationship_labels":
        mutated = complete.replace(
            "behavior-changing pre-release successor",
            "behavior-preserving pre-release successor",
            1,
        )
    elif mutation == "public_a21":
        mutated = complete.replace(
            "qCoder 0.6.0a21 was never public",
            "qCoder 0.6.0a21 was public",
            1,
        )
    elif mutation == "remove_contract_change":
        mutated = complete.replace(
            "changes the Current Loop contract from binding v44 / Current Step Contract v10 to binding v45 / Current Step Contract v11",
            "keeps the same Current Loop contract",
            1,
        )
    elif mutation == "support_mid_step":
        mutated = complete.replace(
            "is not a supported mid-step migration", "is a supported mid-step migration", 1
        )
    else:
        mutated = complete.replace(
            "must not be reused or reinterpreted", "may be reused or reinterpreted", 1
        )
    with pytest.raises(ValueError, match="publication_truth"):
        verifier._validate_active_surface(mutated, "mutation fixture")


@pytest.mark.parametrize("mutation", ["delete", "substitute"])
def test_changelog_and_a21_historical_copy_mutations_fail_closed(mutation: str) -> None:
    verifier = _verifier()
    replacement = "" if mutation == "delete" else "materially altered governed copy"
    changelog = (
        (ROOT / "CHANGELOG.md")
        .read_text(encoding="utf-8")
        .replace(verifier.CHANGELOG_BLOCK, replacement, 1)
    )
    history = (
        (ROOT / "docs/releases/0.6.0a21.md")
        .read_text(encoding="utf-8")
        .replace(verifier.A21_HISTORICAL_CORRECTION, replacement, 1)
    )
    with pytest.raises(ValueError, match="publication_truth"):
        verifier._validate_changelog(changelog)
    with pytest.raises(ValueError, match="publication_truth"):
        verifier._validate_a21_history(history)
