from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_public_readme_is_release_truthful_and_keeps_client_boundaries() -> None:
    readme = _normalized(ROOT / "README.md")
    lowered = readme.lower()
    for forbidden in (
        "quiet assist",
        "held, unpublished",
        "public installation remains unavailable",
        "does not claim publication or public rollout",
        "release candidate combines",
        "candidate full active current loop support",
    ):
        assert forbidden not in lowered
    assert 'python -m pip install "qcoder==0.6.0a5"' in readme
    assert 'python -m pip install "qcoder==0.6.0a6"' not in readme
    assert 'python -m pip install "qcoder==0.6.0a7"' not in readme
    assert "**Cursor Desktop:** full active Current Loop support." in readme
    assert "**Cursor terminal/CLI:**" in readme
    assert "full active-loop support is not claimed" in readme
    assert "**Generic MCP clients:** no support claim." in readme
    assert "does not scan repositories" in readme
    assert "does not independently generate the Python" in readme
    assert "0.6.0a7 is a proposed source correction candidate" in readme
    assert "0.6.0a6 remains a frozen, rejected, unpublished candidate" in readme
    assert "0.6.0a5 release remains the current official public release" in readme
    assert "0.6.0a7" in readme and "not published" in readme
    assert "Finish or restart an active qCoder loop before upgrading" in readme
    assert "outstanding pre-v4 operation receipt cannot be reused" in readme
    assert "IDE must provide a fresh authority grant for the new runtime" in readme
    assert "fails closed instead of silently reinterpreting old authority data" in readme


def test_changelog_records_published_superseded_history_without_runtime_claim() -> None:
    changelog = _normalized(ROOT / "CHANGELOG.md")
    lowered = changelog.lower()
    assert "## 0.6.0a7" in changelog
    assert "## 0.6.0a6" in changelog
    assert "## 0.6.0a5" in changelog
    assert "0.6.0a7` is a proposed source correction candidate" in changelog
    assert "0.6.0a6` was frozen and then rejected as an unpublished candidate" in changelog
    assert "0.6.0a5" in changelog and "remains the current official public release" in changelog
    assert "after `0.6.0a3` was published with stale distribution metadata" in changelog
    assert "metadata-only corrections" in changelog
    assert "unpublished superseded metadata-correction candidate" in changelog
    assert "bounded first-build receipt hardening" in changelog
    assert "package bytes remain the runtime-valid artifacts that were published" in changelog
    assert "0.6.0a3` candidate" not in lowered
    assert "0.6.0a3` artifacts remain unpublished" not in lowered
    assert "0.6.0a4` was published" not in lowered
    assert "0.6.0a4` artifacts were published" not in lowered
    assert "quiet assist" not in lowered
    assert "finish or restart an active qcoder loop before upgrading" in lowered
    assert "outstanding pre-v4 operation receipt cannot be reused" in lowered
    assert "ide must provide a fresh authority grant for the new runtime" in lowered
    assert "fails closed instead of silently reinterpreting old authority data" in lowered
