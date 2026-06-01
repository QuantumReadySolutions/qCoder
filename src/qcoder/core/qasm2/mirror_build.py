"""
Build mirror QASM (U then U†) from OpenQASM 2 source for counts-based mirror runs.

Tolerates standard OpenQASM 2 include "qelib1.inc"; and preserves it in output.
Raises UnsupportedQasm for other include statements or gates that cannot be
inverted in this minimal implementation (no gate definitions, no opaque).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


class UnsupportedQasm(Exception):
    """Raised when the QASM cannot be mirrored (e.g. include, unsupported gate)."""
    pass


# Gate name -> (adjoint_param_negate_mask, self_adjoint)
# u1(t)† = u1(-t); u2(p,l)† = u2(-l,-p); u3(t,p,l)† = u3(-t,-l,-p)
# cx, cz, swap, id, x, y, z, h are self-adjoint; s<->sdg, t<->tdg
_ADJOINT_U1 = (True,)   # one param negate
_ADJOINT_U2 = (True, True)  # swap and negate both
_ADJOINT_U3 = (True, True, True)  # negate all three
_SELF_ADJOINT = ()
_GATE_ADJOINT: dict[str, tuple] = {
    "u1": _ADJOINT_U1,
    "u2": _ADJOINT_U2,
    "u3": _ADJOINT_U3,
    "u": (True, True, True),  # U(theta,phi,lambda) same as u3
    "cu3": _ADJOINT_U3,
    "p": _ADJOINT_U1,
    "cp": _ADJOINT_U1,
    "cu1": _ADJOINT_U1,
    "rx": _ADJOINT_U1,
    "ry": _ADJOINT_U1,
    "rz": _ADJOINT_U1,
    "rxx": _ADJOINT_U1,
    "rzz": _ADJOINT_U1,
    "crx": _ADJOINT_U1,
    "cry": _ADJOINT_U1,
    "crz": _ADJOINT_U1,
    "cx": _SELF_ADJOINT,
    "ch": _SELF_ADJOINT,
    "cy": _SELF_ADJOINT,
    "cz": _SELF_ADJOINT,
    "swap": _SELF_ADJOINT,
    "cswap": _SELF_ADJOINT,
    "ccx": _SELF_ADJOINT,
    "rccx": _SELF_ADJOINT,
    "id": _SELF_ADJOINT,
    "x": _SELF_ADJOINT,
    "y": _SELF_ADJOINT,
    "z": _SELF_ADJOINT,
    "h": _SELF_ADJOINT,
    "s": ("sdg",),   # S† = Sdg (name swap, no params)
    "sdg": ("s",),
    "t": ("tdg",),
    "tdg": ("t",),
    "sx": ("sxdg",),
    "sxdg": ("sx",),
}

_RE_INCLUDE = re.compile(r'^\s*include\s+"([^"]+)"\s*;\s*$', re.I)
_RE_OPENQASM = re.compile(r'^\s*OPENQASM\s+', re.I)
_RE_QREG = re.compile(r'^\s*qreg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;\s*$')
_RE_CREG = re.compile(r'^\s*creg\s+', re.I)
_RE_BARRIER = re.compile(r'^\s*barrier\s+', re.I)
_RE_MEASURE = re.compile(r'^\s*measure\s+', re.I)
# gate line: name ( params )? qubit_operands ;
_RE_OP = re.compile(r'^\s*([A-Za-z_]\w*)\s*(\([^)]*\))?\s+(.+?)\s*;\s*$')


def _parse_float(s: str) -> float:
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _negate_param(p: str) -> str:
    s = p.strip()

    def _strip_outer_parens(x: str) -> str:
        x = x.strip()
        while x.startswith("(") and x.endswith(")"):
            depth = 0
            ok = True
            for i, ch in enumerate(x):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0 and i != len(x) - 1:
                        ok = False
                        break
            if not ok or depth != 0:
                break
            x = x[1:-1].strip()
        return x

    def _is_zero_literal(x: str) -> bool:
        try:
            return float(x.strip()) == 0.0
        except Exception:
            return False

    try:
        v = -float(s)
        return "0" if v == 0.0 else str(v)
    except ValueError:
        core = _strip_outer_parens(s)
        # Simplify double negation: -(-x) -> x
        if core.startswith("-"):
            pos = _strip_outer_parens(core[1:])
            return "0" if _is_zero_literal(pos) else pos
        # Keep symbolic form explicit for non-numeric params.
        return f"-({core})"


def _emit_adjoint_gate(name: str, params: List[str], operands: str) -> str:
    key = name.lower()
    adj = _GATE_ADJOINT.get(key)
    if adj is None:
        raise UnsupportedQasm(f"Unsupported gate for mirror: {name}")
    if adj == _SELF_ADJOINT:
        param_str = f"({', '.join(params)})" if params else ""
        return f"{name}{param_str} {operands};"
    if isinstance(adj, tuple) and len(adj) == 1 and isinstance(adj[0], str):
        # name swap only: s->sdg, sdg->s, t->tdg, tdg->t
        adj_name = adj[0]
        param_str = f"({', '.join(params)})" if params else ""
        return f"{adj_name}{param_str} {operands};"
    # negate params: adj is (bool,) for each param to negate
    out_params: List[str] = []
    for i, p in enumerate(params):
        if i < len(adj) and adj[i]:
            out_params.append(_negate_param(p))
        else:
            out_params.append(p)
    if key == "u2":
        # u2(phi, lambda)† = u2(-lambda, -phi): swap and negate
        if len(out_params) >= 2:
            out_params[0], out_params[1] = out_params[1], out_params[0]
    if key == "cu3":
        # cu3(theta, phi, lambda)† = cu3(-theta, -lambda, -phi)
        if len(out_params) >= 3:
            out_params[1], out_params[2] = out_params[2], out_params[1]
    param_str = f"({', '.join(out_params)})" if out_params else ""
    return f"{name}{param_str} {operands};"


def build_mirror_qasm(orig_text: str, drop_barriers: bool = True) -> Tuple[str, Optional[int]]:
    """
    Build mirror circuit QASM (U then U†) from OpenQASM 2 source.

    Returns (mirror_qasm_string, n_qubits). Drops measure and optionally barrier.
    Raises UnsupportedQasm if non-standard includes or unsupported gates are present.
    """
    lines = orig_text.splitlines()
    header_lines: List[str] = []
    qregs: List[Tuple[str, int]] = []
    gate_lines: List[Tuple[str, List[str], str]] = []  # (name, params, operands)

    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("//"):
            continue
        m = _RE_INCLUDE.match(s)
        if m:
            inc = m.group(1).strip().lower()
            if inc != "qelib1.inc":
                raise UnsupportedQasm(f'Unsupported include for mirror: "{m.group(1).strip()}"')
            header_lines.append(s)
            continue
        if _RE_OPENQASM.match(s):
            header_lines.append(s)
            continue
        if _RE_CREG.match(s):
            continue
        if _RE_MEASURE.match(s):
            continue
        if _RE_BARRIER.match(s):
            if not drop_barriers:
                raise UnsupportedQasm("barrier in circuit (use drop_barriers=True)")
            continue
        m = _RE_QREG.match(s)
        if m:
            header_lines.append(s)
            qregs.append((m.group(1), int(m.group(2))))
            continue
        m = _RE_OP.match(s)
        if m:
            name = m.group(1)
            params_raw = (m.group(2) or "").strip()
            operands = (m.group(3) or "").strip()
            params: List[str] = []
            if params_raw.startswith("(") and params_raw.endswith(")"):
                inside = params_raw[1:-1].strip()
                if inside:
                    params = [x.strip() for x in inside.split(",")]
            gate_lines.append((name, params, operands))
            continue
        # unknown line (gate def, etc.)
        raise UnsupportedQasm(f"Unsupported line for mirror: {s[:60]}")

    if not qregs:
        raise UnsupportedQasm("No qreg declaration found")
    total_width = sum(sz for _, sz in qregs)

    # Ensure OPENQASM 2.0 header
    if not any(_RE_OPENQASM.match(h) for h in header_lines):
        header_lines.insert(0, "OPENQASM 2.0;")

    out: List[str] = []
    out.extend(header_lines)
    # U
    for name, params, operands in gate_lines:
        param_str = f"({', '.join(params)})" if params else ""
        out.append(f"{name}{param_str} {operands};")
    # U† (reversed, adjoint)
    for name, params, operands in reversed(gate_lines):
        out.append(_emit_adjoint_gate(name, params, operands))
    # Final measurements for counts-based mirror mode.
    out.append(f"creg c[{total_width}];")
    cidx = 0
    for qreg_name, qreg_size in qregs:
        for i in range(int(qreg_size)):
            out.append(f"measure {qreg_name}[{i}] -> c[{cidx}];")
            cidx += 1

    return "\n".join(out) + "\n", total_width
