from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from qcoder.engines.context.bundle import build_context_bundle
from qcoder.engines.context.markdown import render_context_markdown
from qcoder.pipelines.analyze import analyze_qasm


def _qcoder_version() -> str:
    try:
        return version("qcoder")
    except PackageNotFoundError:
        return "unknown"


def build_preflight_context(
    qasm_path: str,
    *,
    include_guidance: bool = False,
    include_profiles: bool = False,
    include_full_features: bool = False,
    circuit_id: str | None = None,
    circuit_name: str | None = None,
) -> dict[str, Any]:
    report = analyze_qasm(qasm_path, circuit_id=circuit_id, circuit_name=circuit_name)
    analysis = report.to_json_dict(
        include_guidance=include_guidance,
        include_profiles=include_profiles,
    )
    return build_context_bundle(
        qasm_path=qasm_path,
        analysis=analysis,
        qcoder_version=_qcoder_version(),
        include_full_features=include_full_features,
    )


def write_preflight_context(
    qasm_path: str,
    *,
    out_json: str,
    out_md: str,
    include_guidance: bool = False,
    include_profiles: bool = False,
    include_full_features: bool = False,
    circuit_id: str | None = None,
    circuit_name: str | None = None,
) -> dict[str, Any]:
    bundle = build_preflight_context(
        qasm_path,
        include_guidance=include_guidance,
        include_profiles=include_profiles,
        include_full_features=include_full_features,
        circuit_id=circuit_id,
        circuit_name=circuit_name,
    )
    out_json_path = Path(out_json)
    out_md_path = Path(out_md)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    out_md_path.write_text(render_context_markdown(bundle), encoding="utf-8")
    return bundle

