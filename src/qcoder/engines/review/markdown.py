from __future__ import annotations

from typing import Any

from qcoder.core.share_safe import render_share_safe_note


def render_review_markdown(bundle: dict[str, Any]) -> str:
    lines: list[str] = []
    inputs = bundle.get("inputs", {})
    linkage = bundle.get("linkage", {})
    preflight_excerpt = bundle.get("preflight_excerpt")
    derived = bundle.get("derived", {})
    checks = bundle.get("checks", [])
    warnings = bundle.get("warnings", [])

    lines.append("# qCoder Execution Review")
    lines.append("")
    if bundle.get("share_safe") is True:
        lines.append(render_share_safe_note().strip())
        lines.append("")
    lines.append("## Purpose")
    lines.append("Deterministic post-execution review artifact from provided counts.")
    lines.append("Counts are user-provided; qCoder did not execute the circuit.")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- Counts format: `{inputs.get('counts_format')}`")
    lines.append(f"- Preflight context path: `{inputs.get('preflight_context_path')}`")
    lines.append("")
    lines.append("## Linkage")
    lines.append(f"- qasm_sha256: `{linkage.get('qasm_sha256')}`")
    lines.append(f"- analysis_fingerprint: `{linkage.get('analysis_fingerprint')}`")
    lines.append(
        "- preflight_context_bundle_schema_version: "
        f"`{linkage.get('preflight_context_bundle_schema_version')}`"
    )
    lines.append("")
    if preflight_excerpt is not None:
        lines.append("## Preflight Context Summary")
        circuit = preflight_excerpt.get("circuit", {})
        lines.append(
            f"- Circuit size: n_qubits=`{circuit.get('n_qubits')}` "
            f"n_cbits=`{circuit.get('n_cbits')}` n_ops=`{circuit.get('n_ops')}`"
        )
        feature_map = preflight_excerpt.get("selected_feature_map", {})
        feature_defs = preflight_excerpt.get("selected_feature_definitions", {})
        if feature_map:
            lines.append("- Selected structural features:")
            for k, v in feature_map.items():
                meaning = feature_defs.get(k, "")
                if meaning:
                    lines.append(f"  - {k}: `{v}` — {meaning}")
                else:
                    lines.append(f"  - {k}: `{v}`")
        guidance_summary = preflight_excerpt.get("guidance_summary")
        if isinstance(guidance_summary, dict):
            lines.append("- Guidance summary (if present in preflight):")
            lines.append(
                "  - "
                f"shot_applicability=`{guidance_summary.get('shot_applicability')}` "
                f"shot_starting_shots=`{guidance_summary.get('shot_starting_shots')}`"
            )
            lines.append(
                "  - "
                f"statevector_scale=`{guidance_summary.get('statevector_scale')}` "
                f"mps_pressure=`{guidance_summary.get('mps_pressure')}` "
                f"mps_starting_points=`{guidance_summary.get('mps_starting_points')}`"
            )
        lines.append("")

    lines.append("## Counts Summary")
    lines.append(f"- total_shots: `{derived.get('total_shots')}`")
    lines.append(f"- declared_shots_total: `{derived.get('declared_shots_total')}`")
    lines.append(f"- shots_total_basis: `{derived.get('shots_total_basis')}`")
    lines.append(f"- n_observed_bitstrings: `{derived.get('n_observed_bitstrings')}`")
    lines.append(f"- top_bitstring_probability: `{derived.get('top_bitstring_probability')}`")
    lines.append("")
    lines.append("## Distribution Shape")
    lines.append(f"- concentration: `{derived.get('concentration')}`")
    lines.append(f"- entropy: `{derived.get('entropy')}`")
    lines.append(f"- effective_support_size: `{derived.get('effective_support_size')}`")
    lines.append("- top_k:")
    for row in derived.get("top_k", []):
        lines.append(f"  - `{row.get('bitstring')}`: `{row.get('count')}`")
    lines.append("")
    lines.append("## Checks")
    if checks:
        for check in checks:
            lines.append(
                f"- {check.get('id')}: {check.get('status')} — {check.get('detail')}"
            )
    else:
        lines.append("- No checks were emitted.")
    lines.append("")
    lines.append("## Warnings")
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- No warnings.")
    lines.append("")
    assumptions = bundle.get("assumptions", [])
    llm_limits = bundle.get("llm_use", {}).get("limits", [])
    if assumptions or llm_limits:
        lines.append("## Assumptions and Limits")
        for item in assumptions:
            lines.append(f"- {item}")
        for item in llm_limits:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## Suggested Use With an LLM")
    lines.append(bundle.get("llm_use", {}).get("intended_use", ""))
    lines.append("")
    return "\n".join(lines)
