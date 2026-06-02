from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from qcoder.pro_preview.config import (
    DEFAULT_PRO_API_URL,
    default_config_path,
    resolve_api_url,
    resolve_token,
    store_local_bootstrap_config,
)


def test_store_local_bootstrap_config_restricts_permissions_on_posix(
    tmp_path: Path, monkeypatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX-only config permission hardening")
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_path = store_local_bootstrap_config(token="dev-token-123")
    assert (cfg_path.stat().st_mode & 0o777) == 0o600


def test_store_local_bootstrap_config_writes_outside_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_path = store_local_bootstrap_config(token="dev-token-123", api_url="https://example.invalid/pro")
    assert cfg_path == default_config_path()
    assert cfg_path.exists()
    assert str(cfg_path).startswith(str(tmp_path))
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["token"] == "dev-token-123"
    assert data["api_url"] == "https://example.invalid/pro"


def test_env_overrides_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store_local_bootstrap_config(token="config-token", api_url="https://config.example")
    monkeypatch.setenv("QCODER_PRO_TOKEN", "env-token")
    monkeypatch.setenv("QCODER_PRO_API_URL", "https://env.example")

    token = resolve_token()
    api_url = resolve_api_url()
    assert token.source == "env"
    assert token.value == "env-token"
    assert api_url.source == "env"
    assert api_url.value == "https://env.example"


def test_default_api_url_used_when_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("QCODER_PRO_TOKEN", raising=False)
    monkeypatch.delenv("QCODER_PRO_API_URL", raising=False)

    token = resolve_token()
    api_url = resolve_api_url()
    assert token.source == "unset"
    assert token.value is None
    assert api_url.source == "default"
    assert api_url.value == DEFAULT_PRO_API_URL
