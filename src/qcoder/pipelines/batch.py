from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qcoder.pipelines.analyze import analyze_qasm


@dataclass
class BatchItemResult:
    qasm_path: str
    report: dict  # same structure as AnalyzeReport.to_json_dict()


def analyze_directory(
    circuits_dir: str,
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
) -> list[dict]:
    root = Path(circuits_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {circuits_dir}")

    if recursive:
        paths = sorted(root.rglob(pattern), key=str)
    else:
        paths = sorted(root.glob(pattern), key=str)

    # only files (rglob/glob can return dirs if pattern allows)
    paths = [p for p in paths if p.is_file()]

    results: list[dict] = []
    for p in paths:
        path_str = str(p)
        try:
            report = analyze_qasm(
                path_str,
                processor=processor,
                backend=backend,
                precision=precision,
                threshold=threshold,
                mirror_artifacts_dir=mirror_artifacts_dir,
            )
            results.append(report.to_json_dict(include_guidance=include_guidance))
        except Exception as e:
            if fail_fast:
                raise
            results.append({"qasm_path": path_str, "error": str(e)})
    return results
