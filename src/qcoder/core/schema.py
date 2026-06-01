from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FeatureSchema:
    version: str
    feature_names: tuple[str, ...]
    transforms: dict[str, str]

    def index(self) -> dict[str, int]:
        return {n: i for i, n in enumerate(self.feature_names)}


# Feature schema version (append-only updates).
SCHEMA_VERSION = "0.4.0"


def make_schema(names: Iterable[str], *, transforms: dict[str, str] | None = None) -> FeatureSchema:
    return FeatureSchema(
        version=SCHEMA_VERSION,
        feature_names=tuple(names),
        transforms=dict(transforms or {}),
    )
