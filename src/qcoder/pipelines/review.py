from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from qcoder.engines.review.bundle import build_review_bundle
from qcoder.engines.review.counts_v0 import normalize_counts_v0
from qcoder.engines.review.markdown import render_review_markdown
from qcoder.engines.review.qiskit_counts import normalize_qiskit_counts_payload
from qcoder.core.share_safe import make_share_safe_payload
from qcoder.engines.review.local_evidence import (
    build_local_evidence_review,
    build_share_safe_local_evidence_review,
)
from qcoder.engines.review.local_evidence_markdown import render_local_evidence_markdown


def _qcoder_version() -> str:
    try:
        return version("qcoder")
    except PackageNotFoundError:
        return "0+unknown"


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
        qcoder_version=_qcoder_version(),
    )


def write_execution_review(
    *,
    counts_json: str,
    counts_format: str,
    out_json: str,
    out_md: str,
    preflight_json: str | None = None,
    share_safe: bool = False,
) -> dict[str, Any]:
    bundle = build_execution_review(
        counts_json=counts_json,
        counts_format=counts_format,
        preflight_json=preflight_json,
    )
    if share_safe:
        bundle = make_share_safe_payload(bundle)
    out_json_path = Path(out_json)
    out_md_path = Path(out_md)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    out_md_path.write_text(render_review_markdown(bundle), encoding="utf-8")
    return bundle


def write_local_evidence_review(
    *,
    paths: list[str],
    python_profile: str = "generic_qiskit",
    out_json: str | None = None,
    out_md: str | None = None,
    share_safe_json: str | None = None,
    share_safe_md: str | None = None,
    share_safe_opt_ins: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build and optionally write one explicit-file OSS evidence presentation."""

    report = build_local_evidence_review(paths, python_profile=python_profile)
    if out_json:
        output = Path(out_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if out_md:
        output = Path(out_md)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_local_evidence_markdown(report), encoding="utf-8")
    if share_safe_json or share_safe_md:
        safe = build_share_safe_local_evidence_review(
            report,
            paths,
            opt_ins=share_safe_opt_ins,
        )
        if share_safe_json:
            output = Path(share_safe_json)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if share_safe_md:
            output = Path(share_safe_md)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render_local_evidence_markdown(safe), encoding="utf-8")
    return report
