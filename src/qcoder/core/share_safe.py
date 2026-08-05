from __future__ import annotations

import copy
import re
from pathlib import PurePath
from typing import Any


SHARE_SAFE_NOTE = (
    "Share-safe means local paths, raw circuit text, and token-like values are "
    "omitted or redacted where detected. It is designed for safer sharing, not "
    "a privacy guarantee, and it does not hide circuit structure."
)
SCHEMA_VERSION_NOTE = (
    "qCoder package versions and artifact/schema versions are versioned separately."
)
SUPPORTED_CLAIMS = (
    "deterministic structural features",
    "pre-execution circuit shape",
    "local artifact review context",
)
UNSUPPORTED_CLAIMS = (
    "runtime prediction",
    "fidelity or backend ranking",
    "correctness proof",
    "quantum advantage",
    "raw hosted QASM",
)

_REDACTED_LOCAL_PATH = "<redacted-local-path>"
_REDACTED_SENSITIVE_VALUE = "<redacted-sensitive-value>"

_PATH_TERMINATOR_CHARS = r"\s`'\"<>|,;)\]}"
_ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(?P<path>"
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/][^" + _PATH_TERMINATOR_CHARS + r"]+)"
    r"|(?:\\\\[^\\/" + _PATH_TERMINATOR_CHARS + r"]+[\\/][^" + _PATH_TERMINATOR_CHARS + r"]+)"
    r"|(?:~[\\/][^" + _PATH_TERMINATOR_CHARS + r"]+)"
    r"|(?:(?<![A-Za-z0-9:/\\])/(?!/)[^"
    + _PATH_TERMINATOR_CHARS
    + r"]+/[^"
    + _PATH_TERMINATOR_CHARS
    + r"]+)"
    r")"
)
_RELATIVE_LOCAL_PATH_RE = re.compile(
    r"(?P<path>"
    r"(?<![A-Za-z0-9:/\\])"
    r"(?:\.\.?[\\/]|[A-Za-z0-9_.-]+[\\/])"
    r"(?:[A-Za-z0-9_. -]+[\\/])*"
    r"[A-Za-z0-9_. -]+\.(?:py|qasm|qasm2|qasm3|json|md|txt|yaml|yml|toml|csv)"
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
    "customer_filename",
    "qasm_path",
    "preflight_context_path",
    "counts_json",
    "source_path",
    "local_path",
    "logical_source_label",
    "selected_source",
    "selected_path",
    "customer_path",
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
    _add_artifact_identity(sanitized)
    _clarify_run_config(sanitized)
    sanitized["share_safe"] = True
    sanitized["redactions_applied"] = sorted(redactions)
    serialized = _stable_string(sanitized)
    sanitized["raw_qasm_included"] = contains_raw_qasm_marker(serialized)
    sanitized["local_paths_included"] = contains_local_path(serialized)
    token_like_secrets_included = contains_token_or_header(serialized)
    sanitized["token_like_secrets_included"] = token_like_secrets_included
    sanitized["tokens_included"] = token_like_secrets_included
    sanitized["tokens_included_meaning"] = (
        "authentication tokens or token-like secrets, not LLM token counts"
    )
    sanitized["share_safe_note"] = SHARE_SAFE_NOTE
    sanitized["schema_version_note"] = SCHEMA_VERSION_NOTE
    sanitized["supported_claims"] = list(SUPPORTED_CLAIMS)
    sanitized["unsupported_claims"] = list(UNSUPPORTED_CLAIMS)
    return sanitized


def render_share_safe_note() -> str:
    return f"> **{SHARE_SAFE_NOTE}**\n\n"


def render_share_safe_provenance(payload: dict[str, Any]) -> str:
    """Render compact share-safe provenance for Markdown artifacts."""
    lines = ["## Share-safe provenance", ""]
    for label, value in _provenance_items(payload):
        lines.append(f"- {label}: `{value}`")
    redactions = payload.get("redactions_applied")
    if isinstance(redactions, list):
        redaction_text = ", ".join(str(item) for item in redactions) if redactions else "none"
        lines.append(f"- redactions_applied: `{redaction_text}`")
    lines.append("")
    lines.append(SCHEMA_VERSION_NOTE)
    lines.append("")
    lines.append("## Supported by this artifact")
    for item in SUPPORTED_CLAIMS:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Not supported by this artifact")
    for item in UNSUPPORTED_CLAIMS:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _provenance_items(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    schema = (
        payload.get("schema_id")
        or payload.get("context_bundle_schema_version")
        or payload.get("review_bundle_schema_version")
        or payload.get("artifact_type")
        or "unknown"
    )
    fingerprint = None
    hashes = payload.get("hashes")
    if isinstance(hashes, dict):
        fingerprint = hashes.get("qasm_sha256") or hashes.get("analysis_fingerprint")
    if fingerprint is None:
        linkage = payload.get("linkage")
        if isinstance(linkage, dict):
            fingerprint = linkage.get("qasm_sha256") or linkage.get("analysis_fingerprint")
    return [
        ("qcoder_version", payload.get("qcoder_version", "unknown")),
        ("artifact_schema", schema),
        ("qcoder_product_path", payload.get("qcoder_product_path", "unknown")),
        ("artifact_role", payload.get("artifact_role", "unknown")),
        ("share_safe", payload.get("share_safe", "unknown")),
        ("raw_qasm_included", payload.get("raw_qasm_included", "unknown")),
        ("local_paths_included", payload.get("local_paths_included", "unknown")),
        (
            "token_like_secrets_included",
            payload.get("token_like_secrets_included", payload.get("tokens_included", "unknown")),
        ),
        ("qasm_sha256_or_analysis_fingerprint", fingerprint or "not_available"),
    ]


def _add_artifact_identity(payload: dict[str, Any]) -> None:
    if payload.get("qcoder_product_path") and payload.get("artifact_role"):
        return
    schema_id = str(payload.get("schema_id") or "")
    mode = str(payload.get("mode") or "")
    artifact_type = str(payload.get("artifact_type") or "")
    if schema_id.startswith("qcoder.explorer.") or mode == "explorer-custom-guided-evidence":
        payload.setdefault("qcoder_product_path", "explorer_beta")
        payload.setdefault("artifact_role", "derived_context_guided_evidence")
    elif payload.get("context_bundle_schema_version") or artifact_type == "qcoder.preflight_context":
        payload.setdefault("qcoder_product_path", "oss")
        payload.setdefault("artifact_role", "local_preflight_context")
    elif payload.get("review_bundle_schema_version") or artifact_type == "qcoder.execution_review":
        payload.setdefault("qcoder_product_path", "oss")
        payload.setdefault("artifact_role", "local_execution_review")
    elif "feature_map" in payload and "features" in payload:
        payload.setdefault("qcoder_product_path", "oss")
        payload.setdefault("artifact_role", "local_analysis_report")


def _clarify_run_config(payload: dict[str, Any]) -> None:
    run_config = payload.get("run_config")
    if not isinstance(run_config, dict):
        return
    backend = str(run_config.get("backend") or "").strip().lower()
    if backend == "gpu":
        local_backend = "local_gpu"
    else:
        local_backend = "local_cpu"
    run_config.setdefault("analysis_backend", local_backend)
    run_config.setdefault("local_analysis_backend", local_backend)
    run_config.setdefault(
        "backend_meaning",
        "local analysis backend; not a simulator, QPU, or hardware execution backend",
    )


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
        if _is_path_key(key_lower):
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

    path_redacted = redact_local_paths(out)
    if path_redacted != out:
        # Retain the established metadata category for compatibility.  It now
        # covers both absolute and conservative relative local-path forms.
        redactions.add("absolute_path")
        redactions.add("local_path")
        out = path_redacted

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
    return bool(_ABSOLUTE_LOCAL_PATH_RE.search(text) or _RELATIVE_LOCAL_PATH_RE.search(text))


def redact_local_paths(text: str) -> str:
    """Redact supported absolute and conservative relative customer path forms.

    Relative-path detection intentionally requires a file-like suffix.  This
    avoids treating URLs, schema identifiers, QASM expressions, or ordinary
    slash-separated prose as customer filesystem paths.
    """

    redacted = _ABSOLUTE_LOCAL_PATH_RE.sub(_REDACTED_LOCAL_PATH, text)
    return _RELATIVE_LOCAL_PATH_RE.sub(_REDACTED_LOCAL_PATH, redacted)


def contains_token_or_header(text: str) -> bool:
    return bool(_TOKEN_LIKE_RE.search(text))


def contains_raw_qasm_marker(text: str) -> bool:
    return any(marker in text for marker in ("OPENQASM 2.0", "OPENQASM 3.0", "qreg ", "creg "))


def is_probable_absolute_path(value: str) -> bool:
    try:
        return PurePath(value).is_absolute() or bool(_ABSOLUTE_LOCAL_PATH_RE.search(value))
    except Exception:
        return False


def _is_path_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return (
        normalized in _PATH_KEYS
        or normalized.endswith("_file_path")
        or normalized.endswith("_source_path")
        or normalized.endswith("_output_path")
        or normalized.endswith("_local_path")
        or normalized.endswith("_customer_path")
        or normalized.endswith("_paths")
    )
