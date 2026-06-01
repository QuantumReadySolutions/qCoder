from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from qcoder.core.run_config import RunConfig
from qcoder.engines.feature_extraction.extractor import CircuitExample, extract_example


@dataclass(frozen=True)
class AnalyzeReport:
    example: CircuitExample
    run_config: RunConfig
    mirror_metadata: dict | None = None  # when --mirror-artifacts-dir used

    def to_json_dict(self, *, include_guidance: bool = False, include_profiles: bool = False) -> dict:
        ex = self.example
        fv = ex.global_features
        feature_map = dict(zip(fv.feature_names, fv.features))
        out = {
            "circuit_id": ex.id,
            "circuit_name": ex.name,
            "function_hint": ex.function_hint,
            "function_source": ex.function_source,
            "qasm_path": ex.qasm_path,
            "source_format": ex.ir.source_format,
            "n_qubits": ex.ir.n_qubits,
            "n_cbits": ex.ir.n_cbits,
            "n_ops": ex.ir.n_ops,
            "run_config": self.run_config.to_dict(),
            "features": fv.to_dict(),
            # Derived view for readability; canonical vector remains "features" (schema_version, names, values).
            "feature_map": feature_map,
        }
        if include_guidance:
            from qcoder.engines.guidance.resource import build_resource_guidance

            out["guidance"] = build_resource_guidance(
                feature_map,
                feature_schema_version=fv.schema_version,
            )
        if include_profiles:
            from qcoder.engines.profiles.feature_profiles_v0 import build_feature_profiles

            out["feature_profiles"] = build_feature_profiles(
                feature_map,
                feature_schema_version=fv.schema_version,
            )
        if self.mirror_metadata is not None:
            out["adjoint_supported"] = self.mirror_metadata["adjoint_supported"]
            out["adjoint_reason"] = self.mirror_metadata["adjoint_reason"]
            if self.mirror_metadata.get("mirror_qasm_ref") is not None:
                out["mirror_qasm_ref"] = self.mirror_metadata["mirror_qasm_ref"]
        return out


def analyze_qasm(
    qasm_path: str,
    *,
    circuit_id: str | None = None,
    circuit_name: str | None = None,
    processor: str | None = None,
    backend: str | None = None,
    precision: str | None = None,
    threshold: float | None = None,
    mirror_artifacts_dir: str | None = None,
) -> AnalyzeReport:
    ex = extract_example(qasm_path, circuit_id=circuit_id, circuit_name=circuit_name)
    rc = RunConfig.from_raw(
        processor=processor,
        backend=backend,
        precision=precision,
        threshold=threshold,
    )
    mirror_metadata = None
    if mirror_artifacts_dir:
        from qcoder.core.qasm2.adjoint_eligibility import check_adjoint_eligibility

        qasm_text = Path(qasm_path).read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(qasm_text.encode("utf-8")).hexdigest()
        eligibility = check_adjoint_eligibility(qasm_text, include_mirror_qasm=True)
        mirror_qasm_ref = None
        if eligibility.adjoint_supported and eligibility.mirror_qasm:
            Path(mirror_artifacts_dir).mkdir(parents=True, exist_ok=True)
            mirror_path = Path(mirror_artifacts_dir) / f"{content_hash}__mirror.qasm"
            mirror_path.write_text(eligibility.mirror_qasm, encoding="utf-8")
            mirror_qasm_ref = f"{content_hash}__mirror.qasm"
        mirror_metadata = {
            "adjoint_supported": eligibility.adjoint_supported,
            "adjoint_reason": eligibility.adjoint_reason,
            "mirror_qasm_ref": mirror_qasm_ref,
        }
    return AnalyzeReport(example=ex, run_config=rc, mirror_metadata=mirror_metadata)


def analyze_qasm_json(
    qasm_path: str,
    *,
    circuit_id: str | None = None,
    circuit_name: str | None = None,
    processor: str | None = None,
    backend: str | None = None,
    precision: str | None = None,
    threshold: float | None = None,
    mirror_artifacts_dir: str | None = None,
    include_guidance: bool = False,
    include_profiles: bool = False,
) -> dict:
    """
    Run analyze and return a JSON-serializable dict.
    When mirror_artifacts_dir is set, compute adjoint eligibility and optionally write mirror QASM.
    """
    report = analyze_qasm(
        qasm_path,
        circuit_id=circuit_id,
        circuit_name=circuit_name,
        processor=processor,
        backend=backend,
        precision=precision,
        threshold=threshold,
        mirror_artifacts_dir=mirror_artifacts_dir,
    )
    return report.to_json_dict(include_guidance=include_guidance, include_profiles=include_profiles)
