from __future__ import annotations

from dataclasses import dataclass

CPU_ALIASES = {"cpu", "scarlet"}
GPU_ALIASES = {"gpu", "amber"}

SINGLE_ALIASES = {"single", "fp32", "float32"}
DOUBLE_ALIASES = {"double", "fp64", "float64"}


def normalize_backend(x: str | None) -> str:
    s = (x or "").strip().lower()
    if s in CPU_ALIASES:
        return "CPU"
    if s in GPU_ALIASES:
        return "GPU"
    return "CPU"


def normalize_precision(x: str | None) -> str:
    s = (x or "").strip().lower()
    if s in SINGLE_ALIASES:
        return "single"
    if s in DOUBLE_ALIASES:
        return "double"
    return "single"


@dataclass(frozen=True)
class RunConfig:
    """
    User-supplied run context for analyze reports.

    These are NOT circuit-derived features.
    """
    processor: str | None           # raw label like "Amber", "Scarlet", "CPU", "GPU"
    backend: str                    # normalized: "CPU" | "GPU"
    precision: str                  # normalized: "single" | "double"
    threshold: float | None = None  # e.g. bond-dimension/threshold conditioning

    @staticmethod
    def from_raw(
        *,
        processor: str | None = None,
        backend: str | None = None,
        precision: str | None = None,
        threshold: float | None = None,
    ) -> "RunConfig":
        # accept processor OR backend as the same input channel
        raw = processor if processor is not None else backend
        proc = (raw or "").strip()
        proc = proc if proc else None

        return RunConfig(
            processor=proc,
            backend=normalize_backend(raw or backend),
            precision=normalize_precision(precision),
            threshold=float(threshold) if threshold is not None else None,
        )

    def to_dict(self) -> dict:
        return {
            "processor": self.processor,
            "backend": self.backend,
            "precision": self.precision,
            "threshold": self.threshold,
        }
