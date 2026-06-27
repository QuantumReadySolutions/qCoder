from __future__ import annotations

from typing import Any

from qcoder.core.share_safe import render_share_safe_note


def _fmt_num(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_context_markdown(bundle: dict[str, Any]) -> str:
    circuit = bundle.get("circuit", {})
    analysis = bundle.get("analysis", {})
    feature_map = analysis.get("feature_map", {})
    feature_defs = analysis.get("feature_definitions", {})
    defs_scope = analysis.get("feature_definitions_scope", "selected")
    features_obj = analysis.get("features", {})
    feature_names = list(features_obj.get("feature_names") or [])
    feature_values = list(features_obj.get("features") or [])
    guidance = analysis.get("guidance")
    feature_profiles = analysis.get("feature_profiles")
    lines: list[str] = []

    lines.append("# qCoder Preflight Context")
    lines.append("")
    if bundle.get("share_safe") is True:
        lines.append(render_share_safe_note().strip())
        lines.append("")
    lines.append("## Purpose")
    lines.append("Deterministic pre-execution context artifact for planning and review.")
    lines.append("")
    lines.append("## Circuit")
    lines.append(f"- Path: `{circuit.get('qasm_path')}`")
    lines.append(f"- Source format: `{circuit.get('source_format')}`")
    lines.append(f"- Circuit id: `{circuit.get('circuit_id')}`")
    lines.append(f"- Circuit name: `{circuit.get('circuit_name')}`")
    lines.append(f"- n_qubits: `{_fmt_num(circuit.get('n_qubits'))}`")
    lines.append(f"- n_cbits: `{_fmt_num(circuit.get('n_cbits'))}`")
    lines.append(f"- n_ops: `{_fmt_num(circuit.get('n_ops'))}`")
    lines.append("")
    lines.append("## Structural Summary")
    summary_keys = [
        "real_depth",
        "entangling_depth",
        "n_2q_gate_ops",
        "span_max",
        "cut_max",
        "ig_edge_density",
    ]
    for key in summary_keys:
        if key in feature_map:
            meaning = feature_defs.get(key, "")
            if meaning:
                lines.append(f"- {key}: `{_fmt_num(feature_map.get(key))}` — {meaning}")
            else:
                lines.append(f"- {key}: `{_fmt_num(feature_map.get(key))}`")
    lines.append("")
    if feature_profiles is not None:
        profiles = feature_profiles.get("profiles", {})
        lines.append("## Derived feature profiles")
        lines.append(
            "- Deterministic structural taxonomy derived from `feature_map`; not execution evidence."
        )
        lines.append(
            "- Additive interpretation layer only; canonical `features` remains the source-of-truth vector."
        )
        ordered = [
            "size_profile",
            "sampling_profile",
            "entanglement_profile",
            "topology_profile",
            "locality_profile",
            "simulation_pressure_profile",
            "llm_summary_profile",
        ]
        for key in ordered:
            prof = profiles.get(key, {})
            if key == "llm_summary_profile":
                summary_lines = prof.get("lines", [])
                lines.append(f"- {key}:")
                for summary_line in summary_lines:
                    lines.append(f"  - {summary_line}")
                continue
            tiers = prof.get("tiers", {})
            tier_keys = sorted(tiers.keys())
            tier_str = ", ".join(f"{k}={tiers[k]}" for k in tier_keys)
            labels = prof.get("labels", [])
            labels_str = ", ".join(str(x) for x in labels)
            lines.append(f"- {key}: tiers=`{tier_str}` labels=`{labels_str}`")
        lines.append("")
    if guidance is not None:
        shot = guidance.get("shot_guidance", {})
        sim = guidance.get("simulation_guidance", {})
        mps = sim.get("mps_bond_dimension", {})
        lines.append("## Resource Guidance")
        lines.append("- Non-guaranteed heuristic starting points; no backend execution performed.")
        lines.append(
            f"- Shots: applicability=`{shot.get('applicability')}` starting=`{shot.get('starting_shots', [])}`"
        )
        lines.append(
            f"- Simulation: statevector_scale=`{sim.get('statevector', {}).get('scale')}` "
            f"mps_pressure=`{mps.get('pressure')}` mps_starting_points=`{mps.get('starting_points', [])}`"
        )
        lines.append("")
    if defs_scope == "full" and feature_names and feature_values:
        value_map = dict(zip(feature_names, feature_values))
        lines.append("## Full Feature Reference")
        for name in feature_names:
            value = value_map.get(name)
            meaning = feature_defs.get(name, "")
            if meaning:
                lines.append(f"- {name}: `{_fmt_num(value)}` — {meaning}")
            else:
                lines.append(f"- {name}: `{_fmt_num(value)}`")
        lines.append("")
    lines.append("## Assumptions and Limits")
    for item in bundle.get("assumptions", []):
        lines.append(f"- {item}")
    for item in bundle.get("llm_use", {}).get("limits", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Suggested Use With an LLM")
    lines.append(bundle.get("llm_use", {}).get("intended_use", ""))
    lines.append("")
    return "\n".join(lines)
