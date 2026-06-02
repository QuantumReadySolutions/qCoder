from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qcoder.pro_preview.errors import ProPreviewConfigError

DEFAULT_PRO_API_URL = "https://qcoder.ai/preview"


def default_config_path() -> Path:
    return Path.home() / ".qcoder" / "pro-preview" / "config.json"


@dataclass(frozen=True)
class ValueResolution:
    source: str  # env | config | default | unset
    value: str | None

    @property
    def present(self) -> bool:
        return bool(self.value)


def _non_empty_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProPreviewConfigError(f"Invalid JSON in local Pro config: {path}") from exc
    if not isinstance(data, dict):
        raise ProPreviewConfigError(f"Local Pro config must be a JSON object: {path}")
    return data


def load_local_config(path: Path | None = None) -> dict[str, Any]:
    return _read_json(path or default_config_path())


def store_local_bootstrap_config(
    *,
    token: str,
    api_url: str | None = None,
    path: Path | None = None,
) -> Path:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(config_path)
    existing["token"] = token.strip()
    if api_url and api_url.strip():
        existing["api_url"] = api_url.strip()
    config_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return config_path


def resolve_token(path: Path | None = None) -> ValueResolution:
    env_token = _non_empty_env("QCODER_PRO_TOKEN")
    if env_token:
        return ValueResolution(source="env", value=env_token)
    cfg = _read_json(path or default_config_path())
    token = cfg.get("token")
    if isinstance(token, str) and token.strip():
        return ValueResolution(source="config", value=token.strip())
    return ValueResolution(source="unset", value=None)


def resolve_api_url(path: Path | None = None) -> ValueResolution:
    env_url = _non_empty_env("QCODER_PRO_API_URL")
    if env_url:
        return ValueResolution(source="env", value=env_url)
    cfg = _read_json(path or default_config_path())
    cfg_url = cfg.get("api_url")
    if isinstance(cfg_url, str) and cfg_url.strip():
        return ValueResolution(source="config", value=cfg_url.strip())
    return ValueResolution(source="default", value=DEFAULT_PRO_API_URL)
