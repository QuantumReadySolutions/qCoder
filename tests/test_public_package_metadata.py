from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_readme_is_candidate_qualified_and_keeps_client_claims_held() -> None:
    readme = _normalized(ROOT / "README.md")
    lowered = readme.lower()
    assert 'python -m pip install "qcoder==0.6.0a5"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a9"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a10"' not in readme
    assert "**Cursor Desktop:** full active Current Loop support." not in readme
    assert "This package does not activate a named-client support claim." in readme
    assert "Connection, MCP tool discovery, or evidence for a related client does not establish qualification." in readme
    assert "0.6.0a10" in readme
    assert "unpublished successor candidate" in lowered
    assert "package-index availability requires a separate publication decision" in lowered
    assert "Review local evidence (OSS development branch)" not in readme
    assert "WI-0421 development branch" not in readme
    assert "does not scan repositories" in readme
    assert "does not independently generate the Python" in readme
    assert "Finish or restart an active qCoder loop before upgrading" in readme
    assert "outstanding pre-v4 operation receipt cannot be reused" in readme
    assert "IDE must provide a fresh authority grant for the new runtime" in readme
    assert "fails closed instead of silently reinterpreting old authority data" in readme


def test_changelog_records_a10_repair_and_release_holds() -> None:
    changelog = _normalized(ROOT / "CHANGELOG.md")
    lowered = changelog.lower()
    assert "## 0.6.0a10" in changelog
    assert "## Unreleased integrated source" not in changelog
    assert "unpublished successor candidate" in lowered
    assert "no openqasm 3 parser" in lowered
    assert "historical account-free oss mcp" in lowered
    assert "named-client support claim" in lowered
    assert "binding from v17 to v18" in lowered
    assert "after `0.6.0a3` was published with stale distribution metadata" in changelog
    assert "unpublished superseded metadata-correction candidate" in changelog
    assert "bounded first-build receipt hardening" in changelog
