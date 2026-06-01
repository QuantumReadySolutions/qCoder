from __future__ import annotations

from .ir import CircuitIR


def _name_hint(name: str) -> str | None:
    s = name.strip().lower()
    if not s:
        return None

    # Small, deterministic keyword map (expand later as needed)
    if "qft" in s:
        return "qft"
    if "qaoa" in s:
        return "qaoa"
    if "grover" in s:
        return "grover"
    if "ucc" in s or "vqe" in s:
        return "vqe_ucc"
    if "adder" in s or "arith" in s or "mult" in s:
        return "arithmetic"
    if "qnn" in s or "ansatz" in s or "vqc" in s:
        return "variational"
    return None


def infer_function(circuit_name: str | None, ir: CircuitIR) -> tuple[str, str]:
    """
    Returns: (function_hint, source) where source ∈ {"name", "qasm", "unknown"}.

    Keep categories small/stable. This is metadata for models to optionally consume.
    """
    if circuit_name:
        h = _name_hint(circuit_name)
        if h is not None:
            return (h, "name")

    # QASM-derived minimal heuristics (cheap + robust)
    counts: dict[str, int] = {}
    n_gate = 0
    n_param = 0

    for op in ir.operations:
        if op.is_measure or op.is_barrier or op.is_reset:
            continue
        if not op.qubits:
            continue
        n_gate += 1
        counts[op.name] = counts.get(op.name, 0) + 1
        if op.params:
            n_param += 1

    ccx = counts.get("ccx", 0)
    cp_like = counts.get("cp", 0) + counts.get("cu1", 0)
    h = counts.get("h", 0)

    if ccx > 0:
        return ("arithmetic", "qasm")

    # Very rough QFT signal: many controlled-phase-like ops + some H
    if cp_like >= 3 and h >= 1 and cp_like >= int(0.25 * max(1, n_gate)):
        return ("qft", "qasm")

    # Variational-ish: lots of parameterized rotations
    if n_gate >= 10 and n_param >= int(0.30 * n_gate):
        return ("variational", "qasm")

    return ("unknown", "unknown")
