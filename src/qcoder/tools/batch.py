from __future__ import annotations

import json
from pathlib import Path

from qcoder.pipelines.batch import analyze_directory


def analyze_qasm_dir_to_jsonl(
    circuits_dir: str,
    out_path: str,
    *,
    processor: str | None = None,
    backend: str | None = None,
    precision: str | None = None,
    threshold: float | None = None,
    recursive: bool = True,
    pattern: str = "*.qasm",
    fail_fast: bool = True,
    mirror_artifacts_dir: str | None = None,
    include_guidance: bool = False,
) -> int:
    """Run batch extraction and write one JSON object per line to out_path. Returns record count."""
    results = analyze_directory(
        circuits_dir,
        processor=processor,
        backend=backend,
        precision=precision,
        threshold=threshold,
        recursive=recursive,
        pattern=pattern,
        fail_fast=fail_fast,
        mirror_artifacts_dir=mirror_artifacts_dir,
        include_guidance=include_guidance,
    )
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in results:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    return len(results)
