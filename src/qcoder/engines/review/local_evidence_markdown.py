"""Human-readable rendering for the OSS local-evidence composition."""

from __future__ import annotations

from typing import Any, Mapping

from qcoder.current_loop_run_summary import RUN_SUMMARY_SCHEMA_ID
from qcoder.development_evidence import DEVELOPMENT_EVIDENCE_SCHEMA_ID


def _bullets(lines: list[str], values: object, *, empty: str = "None.") -> None:
    if not isinstance(values, list) or not values:
        lines.append(f"- {empty}")
        return
    for value in values:
        lines.append(f"- {value}")


def _render_development_evidence(lines: list[str], artifact: Mapping[str, Any]) -> None:
    observations = artifact.get("motif_observations")
    emitted = False
    if isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            status = observation.get("observation_status")
            if status not in {"observed", "ambiguous"}:
                continue
            emitted = True
            motif_id = observation.get("motif_id")
            display = observation.get("display_name") or motif_id
            lines.append(f"- `{motif_id}` — {display} ({status})")
    if not emitted:
        lines.append("- No canonical Python motif structure was observed.")
    lines.extend(
        (
            "",
            "> Structural motif evidence is not proof of algorithm identity, completeness, "
            "correctness, parameterization, result causation, performance, or quantum advantage.",
            "",
        )
    )


def _render_run_summary(lines: list[str], artifact: Mapping[str, Any]) -> None:
    projection = artifact.get("count_projection")
    observations = artifact.get("execution_observations")
    lines.append(f"- Schema: `{RUN_SUMMARY_SCHEMA_ID}`")
    if isinstance(projection, Mapping):
        lines.append(f"- Observed shots: `{projection.get('observed_shots')}`")
        lines.append(f"- Declared shots: `{projection.get('declared_shots')}`")
        lines.append("- Bounded dominant outcomes:")
        for outcome in projection.get("top_outcomes", []):
            if isinstance(outcome, Mapping):
                lines.append(
                    f"  - `{outcome.get('bitstring')}`: `{outcome.get('count')}` "
                    f"({outcome.get('percentage')}%)"
                )
    if isinstance(observations, Mapping):
        lines.append("- Supplied execution metadata:")
        for name, observation in observations.items():
            if not isinstance(observation, Mapping):
                continue
            value = (
                observation.get("value") if observation.get("status") == "observed" else "missing"
            )
            lines.append(f"  - {name}: `{value}`")
    lines.extend(
        (
            "",
            "> qCoder reviewed supplied evidence only. It did not execute a backend or simulator "
            "and does not claim correctness, causation, fidelity, or optimality.",
            "",
        )
    )


def render_local_evidence_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Review local evidence",
        "",
        "A bounded local qCoder OSS review of only the files explicitly selected on the command line.",
        "",
        "## Review scope",
        "",
    ]
    scope = report.get("review_scope", {})
    lines.append(f"- Selected artifacts: `{scope.get('selected_artifact_count')}`")
    lines.append("- Inspected: explicitly listed files only")
    lines.append(
        "- Deliberately not inspected: directories, hidden files, imports, the workspace, or related files"
    )
    lines.append("- Network access: `false`")
    lines.append("- Persistent project state: `false`")
    lines.append("")

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
    lines.extend(("## Provenance", ""))
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        selected = item.get("input", {})
        lines.append(
            f"- Artifact {item.get('position')}: `{selected.get('selected_source')}` — "
            f"kind `{selected.get('kind')}`, status `{item.get('status')}`"
        )
        lines.append(
            f"  - Inspected: {', '.join(str(value) for value in item.get('inspected', []))}"
        )
        for value in item.get("established", []):
            lines.append(f"  - Established: {value}")
        for value in item.get("not_established", []):
            lines.append(f"  - Not established: {value}")
    lines.append("")

    lines.extend(("## QASM evidence", ""))
    qasm_items = [
        item
        for item in artifacts
        if isinstance(item, Mapping)
        and str(item.get("input", {}).get("kind", "")).startswith(("openqasm", "qasm_"))
    ]
    if not qasm_items:
        lines.append("- No QASM artifact was selected.")
    for item in qasm_items:
        lines.append(
            f"- Artifact {item.get('position')}: `{item.get('input', {}).get('kind')}` — "
            f"`{item.get('status')}`"
        )
        for value in item.get("established", []):
            lines.append(f"  - {value}")
        for value in item.get("not_established", []):
            lines.append(f"  - {value}")
    lines.append("")

    lines.extend(("## Circuit facts", ""))
    circuit_seen = False
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        canonical = item.get("canonical_artifacts")
        if isinstance(canonical, list):
            for artifact in canonical:
                if not isinstance(artifact, Mapping):
                    continue
                if artifact.get("schema_id") == "qcoder.circuit_manifestation.v1":
                    circuit_seen = True
                    metrics = artifact.get("structural_metrics", {})
                    lines.append(f"- Artifact {item.get('position')} deterministic metrics:")
                    for name in (
                        "width",
                        "classical_width",
                        "depth",
                        "operation_count",
                        "gate_count",
                        "multi_qubit_gate_count",
                        "measurement_count",
                    ):
                        lines.append(f"  - {name}: `{metrics.get(name)}`")
    if not circuit_seen:
        lines.append("- No supported constructed-circuit evidence was selected.")
    lines.append("")

    lines.extend(("## Motif evidence", ""))
    motif_seen = False
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        for artifact in item.get("canonical_artifacts", []):
            if isinstance(artifact, Mapping) and artifact.get("schema_id") == (
                DEVELOPMENT_EVIDENCE_SCHEMA_ID
            ):
                motif_seen = True
                _render_development_evidence(lines, artifact)
    if not motif_seen:
        lines.append("- No Python/Qiskit source was selected; QASM and results do not emit motifs.")
        lines.append("")

    lines.extend(("## Factual Run Summary", ""))
    run_seen = False
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        for artifact in item.get("canonical_artifacts", []):
            if isinstance(artifact, Mapping) and artifact.get("schema_id") == RUN_SUMMARY_SCHEMA_ID:
                run_seen = True
                _render_run_summary(lines, artifact)
    if not run_seen:
        lines.append("- No supported supplied-counts or run-result artifact was selected.")
        lines.append("")

    lines.extend(("## Revision evidence", ""))
    revisions_seen = False
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        for artifact in item.get("canonical_artifacts", []):
            if not isinstance(artifact, Mapping):
                continue
            relationships = artifact.get("explicit_revision_relationships")
            if isinstance(relationships, Mapping) and relationships:
                revisions_seen = True
                lines.append(f"- Artifact {item.get('position')}: `{dict(relationships)}`")
    if not revisions_seen:
        lines.append("- No explicit current/prior relationship was supplied; none was inferred.")
    lines.append("")

    lines.extend(("## Warnings and unsupported state", ""))
    warnings_seen = False
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        for value in list(item.get("limitations", [])) + list(item.get("warnings", [])):
            warnings_seen = True
            lines.append(f"- Artifact {item.get('position')}: {value}")
    if not warnings_seen:
        lines.append("- No additional warnings were emitted.")
    lines.append("")

    lines.extend(("## Bounded local planning guidance", ""))
    guidance = report.get("bounded_local_planning_guidance", {})
    lines.append(f"- Status: `{guidance.get('status')}`")
    lines.append("- This section is separate from evidence facts.")
    lines.append(
        "- It is not optimality proof, fidelity proof, backend ranking, causal savings, "
        "or a protected recommendation."
    )
    lines.append("")

    lines.extend(
        (
            "## Share-safe export",
            "",
            "A derived-only share-safe JSON or Markdown export is available only when requested.",
            "Raw or private categories require separate explicit opt-ins. Inspect every export before sharing.",
            "No export is transmitted automatically.",
            "",
            "## Supported next actions",
            "",
        )
    )
    actions = report.get("supported_next_actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            command = action.get("command")
            instruction = action.get("instruction")
            if command:
                lines.append(f"- `{command}`")
            elif instruction:
                lines.append(f"- {instruction}")
    lines.extend(
        (
            "",
            "## Local qCoder Help",
            "",
            f"- Installed qCoder version: `{report.get('qcoder_version')}`",
            "- Mode: local OSS; no qCoder account, qCoder token, Explorer service, or MCP is required.",
            "- This evidence review does not establish qualification for an IDE or assistant client.",
            "",
        )
    )
    lines.append("")
    return "\n".join(lines)
