from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

MANDATORY_UPGRADE_PARAGRAPHS = (
    (
        "Install qCoder 0.6.0a24 for a new installation or before starting a new Current Loop. "
        "If qCoder 0.6.0a22 already has an active Current Loop, upgrade only at a clean Current "
        "Loop boundary: before a new loop begins or after the current loop has reached a truthful "
        "terminal boundary."
    ),
    (
        "Do not upgrade while any binding v45 / Current Step Contract v11 step, completion, "
        "continuation capsule, pending receipt, or recovery action remains outstanding. Finish "
        "the outstanding step on qCoder 0.6.0a22, or explicitly abandon it and restart the work "
        "under qCoder 0.6.0a24 at a clean boundary."
    ),
    (
        "qCoder does not support or claim mid-step migration from binding v45 / Current Step "
        "Contract v11 to binding v48 / Current Step Contract v11. A v45/v11 operation receipt, "
        "authority grant, completion input, continuation capsule, or pending step must not be "
        "reused or reinterpreted under v48/v11. Project evidence history may remain; this "
        "boundary applies to the active step."
    ),
)
MANDATORY_UPGRADE_TEXT = " ".join(MANDATORY_UPGRADE_PARAGRAPHS)
MANDATORY_CLAUSES = (
    "upgrade only at a clean Current Loop boundary",
    "step, completion, continuation capsule, pending receipt, or recovery action remains outstanding",
    "Finish the outstanding step on qCoder 0.6.0a22, or explicitly abandon it and restart the work",
    "does not support or claim mid-step migration",
    "must not be reused or reinterpreted under v48/v11",
)
RELATIONSHIP_CLAUSES = (
    "qCoder 0.6.0a24 is a behavior-changing pre-release successor to public qCoder 0.6.0a22",
    "Public qCoder 0.6.0a22 is its customer upgrade predecessor",
    "Frozen qCoder 0.6.0a23 at commit `9c984936ab0067d2109eb24b9b1ea072b09b686d` is the implementation lineage predecessor",
    "a23 is unpublished, consumed, terminal, do-not-publish evidence and is not a customer release",
    "The a24 product correction basis is commit `59f0755e965f55a782d220f292ddb8e789af35a1`",
    "That exact basis → a24 relationship preserves runtime implementation and product behavior except for release identity",
    "The public a22 → a24 and terminal a23 → a24 relationships are behavior-changing",
    "Managed setup now reports `qCoder configured`",
    "A bounded verification command reports `qCoder connected` only after an actual client initializes both canonical MCP servers",
    "Direct server smoke is only a credential and server-readiness preflight",
    "binding v47 / schema 46 to binding v48 / schema 47",
    "does not activate Tested, First-class, Client Compatibility, CL-023, named-client support, website, or marketing claims",
)


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _assert_exact_upgrade_copy(text: str) -> None:
    normalized = " ".join(text.split())
    assert MANDATORY_UPGRADE_TEXT in normalized
    for clause in MANDATORY_CLAUSES:
        assert clause in normalized


def _assert_relationship_truth(text: str) -> None:
    normalized = " ".join(text.split())
    for clause in RELATIONSHIP_CLAUSES:
        assert clause in normalized
    assert "behavior-preserving pre-release successor to public qCoder 0.6.0a22" not in normalized
    assert "behavior-preserving successor to qCoder 0.6.0a23" not in normalized


def test_readme_is_publication_truthful_and_keeps_client_claims_held() -> None:
    readme = _normalized(ROOT / "README.md")
    lowered = readme.lower()
    assert 'python -m pip install "qcoder==0.6.0a5"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a9"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a10"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a11"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a12"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a13"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a14"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a15"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a16"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a17"' not in readme
    assert "**Cursor Desktop:** full active Current Loop support." not in readme
    assert "This package does not activate a named-client support claim." in readme
    assert (
        "Connection, MCP tool discovery, or evidence for a related client does not establish qualification."
        in readme
    )
    assert "0.6.0a17" in readme
    assert "qcoder 0.6.0a18 is a behavior-changing pre-release successor" in lowered
    assert "one atomic qcoder-supplied copy-through capsule" in lowered
    assert "release candidate was rejected and must not be published" in lowered
    assert "preserved a17 implementation corrected the a16 mixed-revision limitation" in lowered
    assert "bare counts fail closed" in lowered
    assert "without repository discovery" in lowered
    assert "does not authorize another execution" in lowered
    assert "stable or generally available release" in lowered
    assert "Review local evidence (OSS development branch)" not in readme
    assert "WI-0421 development branch" not in readme
    assert "does not scan repositories" in readme
    assert "does not independently generate the Python" in readme
    assert "upgrade only at a clean Current Loop boundary" in readme
    assert "recovery action remains outstanding" in readme
    assert "explicitly abandon it and restart the work" in readme
    assert "must not be reused or reinterpreted under v48/v11" in readme


def test_changelog_records_a17_behavior_successor_and_a13_history() -> None:
    changelog = _normalized(ROOT / "CHANGELOG.md")
    lowered = changelog.lower()
    assert "## 0.6.0a17" in changelog
    assert "## 0.6.0a16" in changelog
    assert "## 0.6.0a15" in changelog
    assert "## 0.6.0a14" in changelog
    assert "## 0.6.0a13" in changelog
    assert "## 0.6.0a12" in changelog
    assert "## Unreleased integrated source" not in changelog
    assert "unpublished successor candidate" in lowered
    assert "no openqasm 3 parser" in lowered
    assert "historical account-free oss mcp" in lowered
    assert "named-client support claim" in lowered
    assert "canonical context bridge credential grammar" in lowered
    assert "assistant_context_ready" in changelog
    assert "process_and_discard" in changelog
    assert "qcoder 0.6.0a13 is a public pre-release" in lowered
    assert "publication-neutral immutable release metadata" in lowered
    assert "exactly twelve public context bridge tools" in lowered
    assert "preserve the exact qcoder 0.6.0a12 runtime behavior" in lowered
    assert "after `0.6.0a3` was published with stale distribution metadata" in changelog
    assert "unpublished superseded metadata-correction candidate" in changelog
    assert "bounded first-build receipt hardening" in changelog


def test_a16_release_note_is_durable_and_keeps_claims_separate() -> None:
    note = _normalized(ROOT / "docs/releases/0.6.0a16.md")
    lowered = note.lower()
    assert "qcoder 0.6.0a16 is a behavior-changing pre-release successor" in lowered
    assert "exactly twelve public context bridge tools" in lowered
    assert "package publication does not activate a named-client support claim" in lowered
    assert (
        "publication state, deployment state, and qualification claims remain separate" in lowered
    )
    assert "unpublished" not in lowered
    assert "never published" not in lowered
    assert "private-only" not in lowered


def test_a17_release_note_is_durable_and_keeps_claims_separate() -> None:
    note = _normalized(ROOT / "docs/releases/0.6.0a17.md")
    lowered = note.lower()
    assert "qcoder 0.6.0a17 is a behavior-changing pre-release successor" in lowered
    assert "causally coherent" in lowered
    assert "strict result manifests" in lowered
    assert "exactly twelve public context bridge tools" in lowered
    assert "package publication does not activate a named-client support claim" in lowered
    assert "latency or quiet-operation guarantee" in lowered
    assert "immutable historical failure evidence" in lowered
    assert "release-candidate disposition was rejected" in lowered
    assert "must not be published" in lowered
    assert "private-only" not in lowered


def test_a18_release_note_is_publication_truthful_and_keeps_claims_separate() -> None:
    note = _normalized(ROOT / "docs/releases/0.6.0a18.md")
    lowered = note.lower()
    assert "qcoder 0.6.0a18 is a behavior-changing pre-release successor" in lowered
    assert "atomic continuation capsule" in lowered
    assert "causal currentness" in lowered
    assert "exactly twelve public context bridge tools" in lowered
    assert "package publication does not activate a named-client support claim" in lowered
    assert "latency or quiet-operation guarantee" in lowered
    assert "general framework qualification" in lowered
    assert "private-only" not in lowered
    assert "unfrozen" not in lowered


def test_a20_release_note_is_publication_truthful_and_keeps_claims_separate() -> None:
    note = _normalized(ROOT / "docs/releases/0.6.0a20.md")
    lowered = note.lower()
    assert "qcoder 0.6.0a20 is a behavior-changing pre-release successor" in lowered
    assert "terminal-closure route" in lowered
    assert "plain 0.6.0a19 remains intentionally reserved" in lowered
    assert "exactly twelve public context bridge tools" in lowered
    assert "package publication does not activate a named-client support claim" in lowered
    assert "latency or quiet-operation guarantee" in lowered
    assert "private-only" not in lowered
    assert "unfrozen" not in lowered


def test_a20_release_note_is_immutable_historical_do_not_publish_evidence() -> None:
    lowered = _normalized(ROOT / "docs/releases/0.6.0a20.md").lower()
    for statement in (
        "immutable",
        "unpublished",
        "technically qualified",
        "rejected for publication truth",
        "terminal",
        "must not be published",
    ):
        assert statement in lowered


def test_a24_release_note_and_readme_have_exact_relationship_and_upgrade_copy() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_note = (ROOT / "docs/releases/0.6.0a24.md").read_text(encoding="utf-8")
    heading = "## Upgrading from qCoder 0.6.0a22"
    assert heading in release_note
    assert heading in readme or f"#{heading}" in readme
    _assert_exact_upgrade_copy(readme)
    _assert_exact_upgrade_copy(release_note)
    _assert_relationship_truth(readme)
    _assert_relationship_truth(release_note)


@pytest.mark.parametrize("clause", MANDATORY_CLAUSES)
def test_a24_upgrade_guard_rejects_each_missing_or_changed_clause(clause: str) -> None:
    assert clause in MANDATORY_UPGRADE_TEXT
    mutated = MANDATORY_UPGRADE_TEXT.replace(clause, "materially altered clause", 1)
    with pytest.raises(AssertionError):
        _assert_exact_upgrade_copy(mutated)


@pytest.mark.parametrize("clause", RELATIONSHIP_CLAUSES)
def test_a24_relationship_guard_rejects_removal_or_substitution(clause: str) -> None:
    complete = " ".join(RELATIONSHIP_CLAUSES)
    for replacement in ("", "materially altered relationship"):
        with pytest.raises(AssertionError):
            _assert_relationship_truth(complete.replace(clause, replacement, 1))


def test_a24_release_history_is_complete_and_noncontradictory() -> None:
    readme = _normalized(ROOT / "README.md").lower()
    changelog = _normalized(ROOT / "CHANGELOG.md").lower()
    a20 = _normalized(ROOT / "docs/releases/0.6.0a20.md").lower()
    a21 = _normalized(ROOT / "docs/releases/0.6.0a21.md").lower()
    a23 = _normalized(ROOT / "docs/releases/0.6.0a23.md").lower()
    release = json.loads((ROOT / "release-version.json").read_text(encoding="utf-8"))
    assert release["source_version"] == "0.6.0a24"
    assert release["public_upgrade_predecessor"]["version"] == "0.6.0a22"
    assert release["implementation_lineage_predecessor"]["version"] == "0.6.0a23"
    assert release["implementation_lineage_predecessor"]["state"] == (
        "consumed_terminal_unpublished_do_not_publish"
    )
    assert release["product_correction_basis"]["source_commit"] == (
        "59f0755e965f55a782d220f292ddb8e789af35a1"
    )
    assert release["intervening_nonpublic_versions"] == []
    assert "0.6.0a19 remains intentionally reserved" in readme
    assert "0.6.0a20 (unpublished terminal candidate; do not publish)" in changelog
    assert "must not be published" in a20
    assert "0.6.0a21" in a21
    assert "0.6.0a21 (unpublished terminal candidate; do not publish)" in changelog
    assert "publication-truth defect consumed the a21 identity" in a21
    assert "0.6.0a23" in a23
    for surface in (readme, changelog, a20, a21):
        assert "qcoder 0.6.0a20 is public" not in surface
        assert "publish qcoder 0.6.0a20" not in surface
        assert "mid-step migration is supported" not in surface
    assert "0.6.0a23" in readme
    assert "consumed" in readme
    assert "must not be published" in readme
