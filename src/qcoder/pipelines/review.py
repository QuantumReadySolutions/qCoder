from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qcoder.engines.review.bundle import build_review_bundle
from qcoder.engines.review.counts_v0 import normalize_counts_v0
from qcoder.engines.review.markdown import render_review_markdown
from qcoder.engines.review.qiskit_counts import normalize_qiskit_counts_payload


def _load_json(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def build_execution_review(
    *,
    counts_json: str,
    counts_format: str,
    preflight_json: str | None = None,
) -> dict[str, Any]:
    raw_counts = _load_json(counts_json)
    if counts_format == "qcoder":
        counts_v0 = normalize_counts_v0(raw_counts)
    elif counts_format == "qiskit_counts":
        counts_v0 = normalize_qiskit_counts_payload(raw_counts)
    else:
        raise ValueError(f"unsupported counts format: {counts_format}")

    preflight = _load_json(preflight_json) if preflight_json else None
    return build_review_bundle(
        counts_format=counts_format,
        counts_v0=counts_v0,
        preflight_context=preflight,
        preflight_context_path=preflight_json,
    )


def write_execution_review(
    *,
    counts_json: str,
    counts_format: str,
    out_json: str,
    out_md: str,
    preflight_json: str | None = None,
) -> dict[str, Any]:
    bundle = build_execution_review(
        counts_json=counts_json,
        counts_format=counts_format,
        preflight_json=preflight_json,
    )
    out_json_path = Path(out_json)
    out_md_path = Path(out_md)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    out_md_path.write_text(render_review_markdown(bundle), encoding="utf-8")
    return bundle

