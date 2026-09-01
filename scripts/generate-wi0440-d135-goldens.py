#!/usr/bin/env python3
"""Generate the minimal deterministic D-135 first-value golden set."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from qcoder.review_before_generation import (
    build_first_value,
    canonical_first_value_delivery,
    canonical_json,
    review_revision,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "goldens"
BELL_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)


def proposal(*, ghz: bool = False) -> dict:
    if not ghz:
        return json.loads(
            (
                ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
            ).read_text(encoding="utf-8")
        )
    return {
        "schema_id": "qcoder.connected_assistant.review_before_generation_proposal.v4",
        "schema_version": 4,
        "transaction_kind": "review_before_source_generation",
        "execution_request": "not_requested",
        "source_delivery": {"mode": "inline", "target": None},
        "interpretation": "Create a three-qubit GHZ Qiskit program and wait for confirmation before producing source.",
        "constraints": [],
        "recommendations": [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Registers", "value": "Use three qubits and three classical bits."},
            {"label": "Preparation", "value": "Apply H to q0, then CX from q0 to q1 and q2."},
            {"label": "Measurement", "value": "Measure all qubits to matching classical bits."},
        ],
        "output_artifact": "Readable Python source after confirmation",
        "deferred": ["Backend, shots, seed, and result handling remain deferred."],
        "limitations": ["The review does not claim hardware performance."],
        "clarification": None,
    }


def emit(stem: str, request: str, value: dict) -> None:
    first = build_first_value(request, value)
    revision = review_revision(request, value)
    delivery = canonical_first_value_delivery(first, review_revision_value=revision)
    (OUT / f"{stem}.json").write_text(canonical_json(delivery), encoding="utf-8")
    (OUT / f"{stem}.md").write_text(delivery["canonical_markdown"], encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bell = proposal()
    emit("wi0440_d135_bell_inline", BELL_REQUEST, bell)

    file_request = "Use qCoder to review the Qiskit Bell plan before generating source in bell.py."
    file_proposal = deepcopy(bell)
    file_proposal["constraints"] = []
    file_proposal["source_delivery"] = {"mode": "workspace_file", "target": "bell.py"}
    emit("wi0440_d135_bell_workspace_file", file_request, file_proposal)

    ghz_request = "Use qCoder to review a three-qubit GHZ Qiskit program before generating source."
    emit("wi0440_d135_ghz_inline", ghz_request, proposal(ghz=True))

    clarification = proposal(ghz=True)
    clarification["clarification"] = "Should measurements cover all three qubits?"
    emit("wi0440_d135_bounded_clarification", ghz_request, clarification)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
