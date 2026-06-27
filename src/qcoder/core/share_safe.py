from __future__ import annotations

import copy
import re
from pathlib import PurePath
from typing import Any


SHARE_SAFE_NOTE = (
    "Share-safe artifact: local paths and sensitive runtime details have been "
    "omitted or redacted. Review before sharing externally."
)

_REDACTED_LOCAL_PATH = "<redacted-local-path>"
_REDACTED_SENSITIVE_VALUE = "<redacted-sensitive-value>"

_PATH_TERMINATOR_CHARS = r"\s`'\"<>|"
_LOCAL_PATH_RE = re.compile(
    r"(?P<path>"
    r"(?:[A-Za-z]:[\\/][^" + _PATH_TERMINATOR_CHARS + r"]+)"
    r"|(?:\\\\[^\\/" + _PATH_TERMINATOR_CHARS + r"]+[\\/][^" + _PATH_TERMINATOR_CHARS + r"]+)"
    r"|(?:~[\\/][^" + _PATH_TERMINATOR_CHARS + r"]+)"
    r"|(?:/(?:home|Users|mnt|private|var|tmp|workspace|workspaces)/[^" + _PATH_TERMINATOR_CHARS + r"]+)"
    r")"
)
_TOKEN_LIKE_RE = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}|"
    r"(authorization\s*[:=]\s*)(?:bearer\s+)?[^\n,;]+|"
    r"(cookie\s*[:=]\s*)[^\n,;]+|"
    r"(session\s*[:=]\s*)[^\n,;]+|"
    r"(identity[-_ ]?token\s*[:=]\s*)[^\n,;]+|"
    r"(QCODER_[A-Z_]*TOKEN\s*=\s*)[^\s]+|"
    r"(pypi-)[A-Za-z0-9._-]{8,}"
)
_FORBIDDEN_TEXT_MARKERS = (
    "OPENQASM 2.0",
    "OPENQASM 3.0",
    "qreg ",
    "creg ",
    "Secret Manager",
    "Postmark",
)
_PATH_KEYS = {
    "qasm_path",
    "preflight_context_path",
    "counts_json",
    "source_path",
    "local_path",
    "path",
}
_RAW_KEYS = {
    "raw_qasm",
    "qasm_text",
    "source_text",
    "raw_source_text",
    "prompt",
    "notebook",
    "auth_header",
    "authorization",
    "cookie",
    "session",
    "token",
}


def make_share_safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redactions: set[str] = set()
    sanitized = _sanitize(copy.deepcopy(payload), redactions=redactions, key_path=())
    if not isinstance(sanitized, dict):
        sanitized = {"value": sanitized}
    sanitized["share_safe"] = True
    sanitized["redactions_applied"] = sorted(redactions)
    serialized = _stable_string(sanitized)
    sanitized["raw_qasm_included"] = contains_raw_qasm_marker(serialized)
    sanitized["local_paths_included"] = contains_local_path(serialized)
    sanitized["tokens_included"] = contains_token_or_header(serialized)
    sanitized["share_safe_note"] = SHARE_SAFE_NOTE
    return sanitized


def render_share_safe_note() -> str:
    return f"> **{SHARE_SAFE_NOTE}**\n\n"


def _sanitize(value: Any, *, redactions: set[str], key_path: tuple[str, ...]) -> Any:
    key = key_path[-1] if key_path else ""
    key_lower = key.lower()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_key_str = str(child_key)
            if child_key_str.lower() in _RAW_KEYS:
                out[child_key_str] = _REDACTED_SENSITIVE_VALUE
                redactions.add(f"field:{child_key_str}")
                continue
            out[child_key_str] = _sanitize(
                child_value,
                redactions=redactions,
                key_path=key_path + (child_key_str,),
            )
        return out
    if isinstance(value, list):
        return [_sanitize(item, redactions=redactions, key_path=key_path) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item, redactions=redactions, key_path=key_path) for item in value]
    if isinstance(value, str):
        if key_lower in _PATH_KEYS:
            redactions.add(f"field:{key}")
            return _REDACTED_LOCAL_PATH
        return _sanitize_text(value, redactions=redactions)
    return value


def _sanitize_text(text: str, *, redactions: set[str]) -> str:
    out = text
    for marker in _FORBIDDEN_TEXT_MARKERS:
        if marker in out:
            out = out.replace(marker, _REDACTED_SENSITIVE_VALUE)
            redactions.add("raw_or_sensitive_text")

    def _path_repl(match: re.Match[str]) -> str:
        redactions.add("absolute_path")
        return _REDACTED_LOCAL_PATH

    out = _LOCAL_PATH_RE.sub(_path_repl, out)

    def _token_repl(match: re.Match[str]) -> str:
        redactions.add("token_or_header_like_text")
        return _REDACTED_SENSITIVE_VALUE

    out = _TOKEN_LIKE_RE.sub(_token_repl, out)
    return out


def _stable_string(value: Any) -> str:
    try:
        import json

        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(value)


def contains_local_path(text: str) -> bool:
    return bool(_LOCAL_PATH_RE.search(text))


def contains_token_or_header(text: str) -> bool:
    return bool(_TOKEN_LIKE_RE.search(text))


def contains_raw_qasm_marker(text: str) -> bool:
    return any(marker in text for marker in ("OPENQASM 2.0", "OPENQASM 3.0", "qreg ", "creg "))


def is_probable_absolute_path(value: str) -> bool:
    try:
        return PurePath(value).is_absolute() or contains_local_path(value)
    except Exception:
        return False
