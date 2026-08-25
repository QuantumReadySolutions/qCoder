from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


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
    assert "0.6.0a18+wi0436.atomic.continuation.v1" in lowered
    assert "unfrozen, unpublished development identity" in lowered
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
    assert "Finish or restart an active qCoder loop before upgrading" in readme
    assert "outstanding pre-v4 operation receipt cannot be reused" in readme
    assert "IDE must provide a fresh authority grant for the new runtime" in readme
    assert "fails closed instead of silently reinterpreting old authority data" in readme


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
