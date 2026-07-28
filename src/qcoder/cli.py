from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qcoder.pipelines.analyze import analyze_qasm
from qcoder.pipelines.context import write_preflight_context
from qcoder.pipelines.review import write_execution_review
from qcoder.core.share_safe import (
    make_share_safe_payload,
    render_share_safe_note,
    render_share_safe_provenance,
)
from qcoder.explorer.derived_evidence import (
    ExplorerDerivedEvidenceRequestError,
    build_derived_evidence_request_from_context_json,
    build_derived_evidence_request_from_qasm,
)
from qcoder.pro_preview.config import (
    DEFAULT_PRO_API_URL,
    ProPreviewConfigError,
    load_local_config,
    resolve_api_url,
    resolve_token,
    store_local_bootstrap_config,
)
from qcoder.pro_preview.client import ProServiceClient, ProServiceClientError
from qcoder.pro_preview.client import (
    PreviewClientNetworkError,
    call_builtin_review_demo,
    call_student_custom_guided_evidence,
    call_student_guided_evidence,
    resolve_preview_client_config,
    summarize_demo_payload,
)
from qcoder.pro_preview.errors import ProPreviewManifestError
from qcoder.pro_preview.manifest import (
    build_workflow_manifest,
    sanitize_manifest_for_submit,
    write_workflow_manifest,
)
from qcoder.tools.batch import analyze_qasm_dir_to_jsonl
from qcoder.algorithm_blueprint import (
    extract_selected_python_file_evidence,
    extract_selected_python_source_evidence,
)
from qcoder.development_evidence import PROFILE_IDS, SOURCE_EVIDENCE_DEPTH_GATE

EXPLORER_BETA_DOCS_URL = "https://qcoder.ai/manual/student-beta/"
OSS_DOCS_URL = "https://qcoder.ai/manual/oss/"
_CURRENT_LOOP_REQUEST_MAX_CODEPOINTS = 20_000
_CURRENT_LOOP_REQUEST_MAX_UTF8_BYTES = _CURRENT_LOOP_REQUEST_MAX_CODEPOINTS * 4


def _is_non_default_service_url(value: str | None) -> bool:
    if not value:
        return False
    return value.strip() != DEFAULT_PRO_API_URL


def _build_pro_bootstrap_payload(status: str) -> dict[str, object]:
    token = resolve_token()
    api_url = resolve_api_url()
    configured = token.present
    return {
        "schema_id": "qcoder.pro_preview_bootstrap.v0",
        "status": status,
        "service_backed": True,
        "configured": configured,
        "token_present": token.present,
        "token_source": token.source,
        "api_url_configured": api_url.present,
        "api_url_source": api_url.source,
        "service_validation": "not_available",
        "cards_local": False,
        "local_pro_analysis": False,
        "confidential_analysis_local": False,
        "upload_performed": False,
    }


def _cmd_analyze(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="qcoder analyze", add_help=True)
    p.add_argument("qasm", help="Path to a .qasm file")
    p.add_argument("--id", dest="circuit_id", default=None, help="Optional circuit id")
    p.add_argument("--name", dest="circuit_name", default=None, help="Optional circuit name")
    p.add_argument(
        "--processor",
        "--backend",
        dest="processor",
        default="CPU",
        help="Processor/backend label (aliases: Scarlet/Amber, CPU/GPU)",
    )
    p.add_argument(
        "--precision", default="single", help="Precision: single|double (aliases: fp32/fp64)"
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Optional threshold/bond-dim conditioning value",
    )
    p.add_argument(
        "--mirror-artifacts-dir",
        default=None,
        metavar="DIR",
        help="If set, write mirror QASM to DIR and add adjoint_supported/adjoint_reason/mirror_qasm_ref to output",
    )
    p.add_argument(
        "--guidance",
        action="store_true",
        help="Include heuristic resource guidance (shots and simulator/MPS starting points)",
    )
    p.add_argument(
        "--profiles",
        action="store_true",
        help="Include derived feature_profiles in JSON output (requires --json for analyze)",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    p.add_argument(
        "--share-safe",
        "--redact",
        dest="share_safe",
        action="store_true",
        help="Redact local paths and sensitive runtime details in JSON output intended for sharing.",
    )
    args = p.parse_args(argv)

    if args.profiles and not args.json:
        print(
            "qcoder: --profiles is currently emitted only with --json for analyze; use --json --profiles.",
            file=sys.stderr,
        )
        return 2

    report = analyze_qasm(
        args.qasm,
        circuit_id=args.circuit_id,
        circuit_name=args.circuit_name,
        processor=args.processor,
        precision=args.precision,
        threshold=args.threshold,
        mirror_artifacts_dir=args.mirror_artifacts_dir or None,
    )

    if args.json:
        payload = report.to_json_dict(
            include_guidance=args.guidance, include_profiles=args.profiles
        )
        if args.share_safe:
            payload = make_share_safe_payload(payload)
        print(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    ex = report.example
    rc = report.run_config
    print(f"file: {'<redacted-local-path>' if args.share_safe else ex.qasm_path}")
    if args.share_safe:
        print("share_safe: true")
    print(f"format: {ex.ir.source_format}")
    if ex.name:
        print(f"name: {ex.name}")
    print(f"function_hint: {ex.function_hint} ({ex.function_source})")
    print(
        f"processor: {rc.processor}  backend: {rc.backend}  precision: {rc.precision}  threshold: {rc.threshold}"
    )
    print(f"n_qubits: {ex.ir.n_qubits}")
    print(f"n_ops: {ex.ir.n_ops}")
    fv = ex.global_features
    print(f"schema: {fv.schema_version}")
    print(f"n_features: {len(fv.features)}")
    if args.guidance:
        out = report.to_json_dict(include_guidance=True, include_profiles=args.profiles)
        guidance = out.get("guidance", {})
        shot = guidance.get("shot_guidance", {})
        sim = guidance.get("simulation_guidance", {})
        mps = sim.get("mps_bond_dimension", {})
        print("guidance: non-guaranteed heuristic starting points only; no backend execution")
        print(
            f"shots: applicability={shot.get('applicability')} "
            f"starting={shot.get('starting_shots', [])}"
        )
        print(
            f"simulator starting points: statevector_scale={sim.get('statevector', {}).get('scale')} "
            f"mps_pressure={mps.get('pressure')} "
            f"mps_starting_points={mps.get('starting_points', [])}"
        )
    return 0


def _cmd_batch(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="qcoder batch", add_help=True)
    p.add_argument("circuits_dir", help="Directory containing QASM files")
    p.add_argument("--out", required=True, help="Output JSONL path")
    p.set_defaults(recursive=True)
    p.add_argument(
        "--recursive",
        dest="recursive",
        action="store_true",
        help="Discover files recursively (default)",
    )
    p.add_argument(
        "--non-recursive",
        dest="recursive",
        action="store_false",
        help="Only discover top-level files",
    )
    p.add_argument("--pattern", default="*.qasm", help="Glob pattern for files (default: *.qasm)")
    p.add_argument(
        "--skip-errors",
        action="store_true",
        help="Continue on error, emit error records (default: fail-fast)",
    )
    p.add_argument("--processor", default=None, help="Processor/backend label for run_config")
    p.add_argument("--backend", default=None, help="Backend label (CPU/GPU, etc.)")
    p.add_argument("--precision", default=None, help="Precision: single|double|fp32|fp64")
    p.add_argument(
        "--threshold", type=float, default=None, help="Optional threshold for run_config"
    )
    p.add_argument(
        "--mirror-artifacts-dir",
        default=None,
        metavar="DIR",
        help="If set, write mirror QASM to DIR and add adjoint_supported/adjoint_reason/mirror_qasm_ref to each record",
    )
    p.add_argument(
        "--guidance",
        action="store_true",
        help="Include heuristic resource guidance block in each successful JSONL record",
    )
    args = p.parse_args(argv)

    n = analyze_qasm_dir_to_jsonl(
        args.circuits_dir,
        args.out,
        processor=args.processor,
        backend=args.backend,
        precision=args.precision,
        threshold=args.threshold,
        recursive=args.recursive,
        pattern=args.pattern,
        fail_fast=not args.skip_errors,
        mirror_artifacts_dir=args.mirror_artifacts_dir or None,
        include_guidance=args.guidance,
    )
    print(f"Wrote {n} records to {args.out}", file=sys.stderr)
    return 0


def _cmd_context(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="qcoder context", add_help=True)
    p.add_argument("qasm", help="Path to a .qasm file")
    p.add_argument("--out-json", required=True, help="Output preflight JSON context path")
    p.add_argument("--out-md", required=True, help="Output preflight Markdown context path")
    p.add_argument("--id", dest="circuit_id", default=None, help="Optional circuit id")
    p.add_argument("--name", dest="circuit_name", default=None, help="Optional circuit name")
    p.add_argument(
        "--guidance",
        action="store_true",
        help="Include heuristic resource guidance in context artifacts",
    )
    p.add_argument(
        "--profiles",
        action="store_true",
        help="Include deterministic derived feature profiles in context artifacts",
    )
    p.add_argument(
        "--full-features",
        action="store_true",
        help="Include full feature glossary/appendix in context artifacts (default: selected structural features only)",
    )
    p.add_argument(
        "--share-safe",
        "--redact",
        dest="share_safe",
        action="store_true",
        help="Write artifacts designed for safer sharing by redacting local paths and sensitive runtime details.",
    )
    args = p.parse_args(argv)

    write_preflight_context(
        args.qasm,
        out_json=args.out_json,
        out_md=args.out_md,
        include_guidance=args.guidance,
        include_profiles=args.profiles,
        include_full_features=args.full_features,
        circuit_id=args.circuit_id,
        circuit_name=args.circuit_name,
        share_safe=args.share_safe,
    )
    json_label = "<redacted-local-path>" if args.share_safe else args.out_json
    md_label = "<redacted-local-path>" if args.share_safe else args.out_md
    print(f"Wrote preflight context JSON to {json_label}", file=sys.stderr)
    print(f"Wrote preflight context Markdown to {md_label}", file=sys.stderr)
    return 0


def _cmd_review(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="qcoder review", add_help=True)
    p.add_argument("--counts-json", required=True, help="Input counts JSON path")
    p.add_argument(
        "--format",
        dest="counts_format",
        choices=["qcoder", "qiskit_counts"],
        default="qcoder",
        help="Input counts format (default: qcoder)",
    )
    p.add_argument(
        "--preflight-json",
        default=None,
        help="Optional preflight context JSON path for linkage/checks",
    )
    p.add_argument("--out-json", required=True, help="Output execution review JSON path")
    p.add_argument("--out-md", required=True, help="Output execution review Markdown path")
    p.add_argument(
        "--share-safe",
        "--redact",
        dest="share_safe",
        action="store_true",
        help="Write artifacts designed for safer sharing by redacting local paths and sensitive runtime details.",
    )
    args = p.parse_args(argv)

    write_execution_review(
        counts_json=args.counts_json,
        counts_format=args.counts_format,
        preflight_json=args.preflight_json,
        out_json=args.out_json,
        out_md=args.out_md,
        share_safe=args.share_safe,
    )
    json_label = "<redacted-local-path>" if args.share_safe else args.out_json
    md_label = "<redacted-local-path>" if args.share_safe else args.out_md
    print(f"Wrote execution review JSON to {json_label}", file=sys.stderr)
    print(f"Wrote execution review Markdown to {md_label}", file=sys.stderr)
    return 0


def _run_pro_preview_demo_check(
    *,
    base_url_override: str | None,
    label: str = "qCoder Pro Preview demo",
    error_prefix: str = "qcoder pro preview",
) -> int:
    try:
        config = resolve_preview_client_config(
            base_url_override=base_url_override,
            include_student_aliases=True,
        )
    except ValueError as exc:
        print(f"{error_prefix}: {exc}", file=sys.stderr)
        return 2

    try:
        response = call_builtin_review_demo(config)
    except PreviewClientNetworkError:
        print(
            f"{label}: FAIL (network). Base URL may be unreachable.",
            file=sys.stderr,
        )
        print(f"  base_url: {config.base_url}", file=sys.stderr)
        return 2

    if response.status_code == 200:
        print(f"{label}: PASS (HTTP 200).")
        print(f"  base_url: {config.base_url}")
        for line in summarize_demo_payload(response.payload):
            print(f"  {line}")
        return 0
    if response.status_code == 401:
        print(
            f"{label}: FAIL (HTTP 401). Token is missing, invalid, or revoked.",
            file=sys.stderr,
        )
        return 1
    if response.status_code == 403:
        print(
            f"{label}: FAIL (HTTP 403). Private/outer service access may be blocking access.",
            file=sys.stderr,
        )
        return 1

    print(f"{label}: FAIL (HTTP {response.status_code}).", file=sys.stderr)
    for line in summarize_demo_payload(response.payload):
        print(f"  {line}", file=sys.stderr)
    return 2


def _format_summary_value(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _print_raw_payload_json(payload: dict[str, object] | None, *, share_safe: bool = False) -> None:
    out = payload or {}
    if share_safe:
        out = make_share_safe_payload(out)
    print(json.dumps(out, indent=2, sort_keys=True))


def _write_json_payload(
    path: str, payload: dict[str, object] | None, *, share_safe: bool = False
) -> None:
    out = payload or {}
    if share_safe:
        out = make_share_safe_payload(out)
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")


def _is_scalar(value: object) -> bool:
    return isinstance(value, (str, int, float, bool))


def _sample_count(payload: dict[str, object] | None) -> int | None:
    if not payload:
        return None
    samples = payload.get("samples")
    if isinstance(samples, list):
        return len(samples)
    sample_count = payload.get("sample_count")
    if isinstance(sample_count, int):
        return sample_count
    return None


def _format_beginner_metrics(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    parts: list[str] = []
    for key in sorted(value):
        metric = value[key]
        if _is_scalar(metric):
            parts.append(f"{key}={_format_summary_value(metric)}")
    return ", ".join(parts) if parts else None


def _summarize_student_glossary(value: object) -> list[str]:
    lines: list[str] = []
    if isinstance(value, dict):
        for term in sorted(value)[:4]:
            definition = value[term]
            if isinstance(definition, str):
                lines.append(f"  {term}: {definition}")
            elif isinstance(definition, dict):
                text = definition.get("definition") or definition.get("summary")
                if isinstance(text, str):
                    lines.append(f"  {term}: {text}")
    elif isinstance(value, list):
        for item in value[:4]:
            if isinstance(item, dict):
                term = item.get("term") or item.get("name")
                definition = item.get("definition") or item.get("summary")
                if isinstance(term, str) and isinstance(definition, str):
                    lines.append(f"  {term}: {definition}")
            elif isinstance(item, str):
                lines.append(f"  {item}")
    return lines


def _summarize_student_demo_payload(payload: dict[str, object] | None) -> list[str]:
    if not payload:
        return ["summary: built-in teaching demo reached; no summary payload returned"]
    lines: list[str] = []
    summary = payload.get("student_summary")
    if isinstance(summary, str):
        lines.append(f"summary: {summary}")
    elif isinstance(summary, dict):
        for key in ("title", "summary", "next_step"):
            value = summary.get(key)
            if _is_scalar(value):
                lines.append(f"{key}: {_format_summary_value(value)}")
    mode = payload.get("mode")
    if _is_scalar(mode):
        lines.append(f"mode: {_format_summary_value(mode)}")
    count = _sample_count(payload)
    if count is not None:
        lines.append(f"samples: {count}")
    samples = payload.get("samples")
    if isinstance(samples, list):
        for index, sample in enumerate(samples[:2], start=1):
            if isinstance(sample, dict):
                plain_summary = sample.get("plain_summary")
                if isinstance(plain_summary, str):
                    lines.append(f"sample {index}: {plain_summary}")
    return lines


def _summarize_student_evidence_payload(payload: dict[str, object] | None) -> list[str]:
    if not payload:
        return ["summary: Explorer Beta evidence endpoint reached; no summary payload returned"]
    lines: list[str] = []
    summary = payload.get("student_summary")
    if isinstance(summary, str):
        lines.append(f"summary: {summary}")
    elif isinstance(summary, dict):
        for key in ("title", "summary", "what_this_means", "next_step"):
            value = summary.get(key)
            if _is_scalar(value):
                lines.append(f"{key}: {_format_summary_value(value)}")
    anatomy_label = payload.get("anatomy_label")
    if _is_scalar(anatomy_label):
        lines.append(f"anatomy_label: {_format_summary_value(anatomy_label)}")
    count = _sample_count(payload)
    if count is not None:
        lines.append(f"samples: {count}")
    samples = payload.get("samples")
    if isinstance(samples, list):
        for index, sample in enumerate(samples[:3], start=1):
            if not isinstance(sample, dict):
                continue
            plain_summary = sample.get("plain_summary")
            if isinstance(plain_summary, str):
                lines.append(f"sample {index}: {plain_summary}")
            sample_anatomy = sample.get("anatomy_label")
            if _is_scalar(sample_anatomy):
                lines.append(f"sample {index} anatomy: {_format_summary_value(sample_anatomy)}")
            metrics = _format_beginner_metrics(sample.get("beginner_metrics"))
            if metrics:
                lines.append(f"sample {index} beginner_metrics: {metrics}")
    metrics = _format_beginner_metrics(payload.get("beginner_metrics"))
    if metrics:
        lines.append(f"beginner_metrics: {metrics}")
    glossary = _summarize_student_glossary(payload.get("glossary"))
    if glossary:
        lines.append("glossary:")
        lines.extend(glossary)
    ai_summary = payload.get("ai_grounding_summary")
    if isinstance(ai_summary, str):
        lines.append(f"ai_grounding_summary: {ai_summary}")
    guided = payload.get("guided_evidence")
    if isinstance(guided, list):
        for index, item in enumerate(guided[:4], start=1):
            if isinstance(item, str):
                lines.append(f"guided_evidence {index}: {item}")
            elif isinstance(item, dict):
                title = item.get("title")
                summary_text = item.get("summary")
                if isinstance(title, str) and isinstance(summary_text, str):
                    lines.append(f"guided_evidence {index}: {title} - {summary_text}")
                elif isinstance(summary_text, str):
                    lines.append(f"guided_evidence {index}: {summary_text}")
    return lines


def _render_student_evidence_markdown(payload: dict[str, object] | None) -> str:
    lines = [
        "# qCoder Explorer Beta Guided Evidence",
        "",
    ]
    if payload and payload.get("share_safe") is True:
        lines.append(render_share_safe_note().strip())
        lines.append("")
        lines.append(render_share_safe_provenance(payload).strip())
        lines.append("")
    for line in _summarize_student_evidence_payload(payload):
        lines.append(f"- {line}")
    if payload:
        privacy = payload.get("privacy_boundary")
        if isinstance(privacy, dict):
            lines.append("")
            lines.append("## Privacy boundary")
            for key in sorted(privacy):
                value = privacy[key]
                if _is_scalar(value):
                    lines.append(f"- {key}: {_format_summary_value(value)}")
        non_claims = payload.get("non_claims_summary")
        if isinstance(non_claims, list) and non_claims:
            lines.append("")
            lines.append("## Non-claims")
            for item in non_claims[:8]:
                if isinstance(item, str):
                    lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _write_markdown_payload(
    path: str, payload: dict[str, object] | None, *, share_safe: bool = False
) -> None:
    out = payload or {}
    if share_safe:
        out = make_share_safe_payload(out)
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_student_evidence_markdown(out), encoding="utf-8")


def _run_student_builtin_review_check(
    *,
    base_url_override: str | None,
    mode: str,
    json_output: bool,
    compatibility_alias: bool = False,
    command_prefix: str = "qcoder explorer",
) -> int:
    try:
        config = resolve_preview_client_config(
            base_url_override=base_url_override,
            include_student_aliases=True,
        )
    except ValueError as exc:
        print(f"{command_prefix}: {exc}", file=sys.stderr)
        return 2

    try:
        response = call_builtin_review_demo(config)
    except PreviewClientNetworkError:
        print(
            "qCoder Explorer Beta: FAIL (network). The service may be unreachable; check your base URL.",
            file=sys.stderr,
        )
        print(f"  base_url: {config.base_url}", file=sys.stderr)
        return 2

    if json_output:
        _print_raw_payload_json(response.payload)
        return 0 if response.status_code == 200 else 1 if response.status_code in {401, 403} else 2

    if response.status_code == 200:
        if mode == "status":
            print("qCoder Explorer Beta access: OK")
            print("  command: qcoder explorer status")
            if compatibility_alias:
                print("  compatibility_alias: qcoder student status")
            print(f"  http_status: {response.status_code}")
            print("  service: available")
            count = _sample_count(response.payload)
            if count is not None:
                print(f"  teaching_demo_samples: {count}")
            print("Next: try qcoder explorer demo, then qcoder explorer evidence.")
        else:
            print("qCoder Explorer Beta built-in teaching demo: PASS (HTTP 200).")
            print("  command: qcoder explorer demo")
            if compatibility_alias:
                print("  compatibility_alias: qcoder student demo")
            for line in _summarize_student_demo_payload(response.payload):
                print(f"  {line}")
        return 0
    if response.status_code == 401:
        print(
            "qCoder Explorer Beta: FAIL (HTTP 401). Your token is missing, invalid, revoked, or lacks Explorer Beta access.",
            file=sys.stderr,
        )
        return 1
    if response.status_code == 403:
        print(
            "qCoder Explorer Beta: FAIL (HTTP 403). Your token does not have access to this Explorer Beta command.",
            file=sys.stderr,
        )
        return 1

    print(f"qCoder Explorer Beta: FAIL (HTTP {response.status_code}).", file=sys.stderr)
    if mode == "demo":
        for line in _summarize_student_demo_payload(response.payload):
            print(f"  {line}", file=sys.stderr)
    return 2


def _run_student_evidence_check(
    *,
    base_url_override: str | None,
    json_output: bool,
    command_label: str = "qcoder explorer evidence",
    compatibility_alias: bool = False,
    qasm_path: str | None = None,
    context_json_path: str | None = None,
    out_json: str | None = None,
    out_md: str | None = None,
    share_safe: bool = False,
) -> int:
    request_payload: dict[str, object] | None = None
    if qasm_path and context_json_path:
        print(f"{command_label}: choose only one of --qasm or --context-json", file=sys.stderr)
        return 2
    if qasm_path:
        try:
            request_payload = build_derived_evidence_request_from_qasm(qasm_path)
        except ExplorerDerivedEvidenceRequestError as exc:
            print(f"{command_label}: {exc}", file=sys.stderr)
            return 2
    elif context_json_path:
        try:
            request_payload = build_derived_evidence_request_from_context_json(context_json_path)
        except ExplorerDerivedEvidenceRequestError as exc:
            print(f"{command_label}: {exc}", file=sys.stderr)
            return 2

    try:
        config = resolve_preview_client_config(
            base_url_override=base_url_override,
            include_student_aliases=True,
        )
    except ValueError as exc:
        print(f"{command_label.rsplit(' ', 1)[0]}: {exc}", file=sys.stderr)
        return 2

    try:
        if request_payload is None:
            response = call_student_guided_evidence(config)
        else:
            response = call_student_custom_guided_evidence(config, payload=request_payload)
    except PreviewClientNetworkError:
        print(
            "qCoder Explorer Beta evidence: FAIL (network). The service may be unreachable; check your base URL.",
            file=sys.stderr,
        )
        print(f"  base_url: {config.base_url}", file=sys.stderr)
        return 2

    if json_output:
        _print_raw_payload_json(response.payload, share_safe=share_safe)
        if out_json:
            _write_json_payload(out_json, response.payload, share_safe=share_safe)
        if out_md:
            _write_markdown_payload(out_md, response.payload, share_safe=share_safe)
        return 0 if response.status_code == 200 else 1 if response.status_code in {401, 403} else 2

    if response.status_code == 200:
        print("qCoder Explorer Beta evidence: PASS (HTTP 200).")
        print("  command: qcoder explorer evidence")
        if compatibility_alias:
            print("  compatibility_alias: qcoder student evidence")
        if request_payload is not None:
            print("  evidence_mode: derived_context")
            print("  raw_qasm_uploaded: false")
            print("  persisted: false")
        for line in _summarize_student_evidence_payload(response.payload):
            print(f"  {line}")
        if out_json:
            _write_json_payload(out_json, response.payload, share_safe=share_safe)
            print(f"  wrote_json: {'<redacted-local-path>' if share_safe else out_json}")
        if out_md:
            _write_markdown_payload(out_md, response.payload, share_safe=share_safe)
            print(f"  wrote_md: {'<redacted-local-path>' if share_safe else out_md}")
        return 0
    if response.status_code == 401:
        print(
            "qCoder Explorer Beta evidence: FAIL (HTTP 401). Your token is missing, invalid, revoked, or lacks Explorer Beta evidence access.",
            file=sys.stderr,
        )
        return 1
    if response.status_code == 403:
        print(
            "qCoder Explorer Beta evidence: FAIL (HTTP 403). Your token does not have access to Explorer Beta evidence.",
            file=sys.stderr,
        )
        return 1

    print(f"qCoder Explorer Beta evidence: FAIL (HTTP {response.status_code}).", file=sys.stderr)
    for line in _summarize_student_evidence_payload(response.payload):
        print(f"  {line}", file=sys.stderr)
    return 2


def _cmd_explorer(argv: list[str], *, compatibility_alias: bool = False) -> int:
    prog = "qcoder student" if compatibility_alias else "qcoder explorer"
    p = argparse.ArgumentParser(
        prog=prog,
        add_help=True,
        description=(
            "qCoder Explorer Beta account-backed status/demo/evidence checks. "
            + (
                "`qcoder student` is a compatibility alias; use `qcoder explorer` for the primary public surface."
                if compatibility_alias
                else "`qcoder student` remains available as a compatibility alias during beta."
            )
        ),
    )
    sub = p.add_subparsers(dest="explorer_command")

    p_status = sub.add_parser(
        "status",
        help="Check qCoder Explorer Beta access and print the next step.",
    )
    p_status.add_argument(
        "--base-url",
        default=None,
        help="Override qCoder Explorer Beta base URL (default env: QCODER_STUDENT_BASE_URL, QCODER_PREVIEW_BASE_URL, or QCODER_PRO_API_URL).",
    )
    p_status.add_argument("--json", action="store_true", help="Emit raw service payload as JSON.")
    p_status.set_defaults(explorer_command="status")

    p_demo = sub.add_parser(
        "demo",
        help="Run the built-in qCoder Explorer Beta teaching demo.",
    )
    p_demo.add_argument(
        "--base-url",
        default=None,
        help="Override qCoder Explorer Beta base URL (default env: QCODER_STUDENT_BASE_URL, QCODER_PREVIEW_BASE_URL, or QCODER_PRO_API_URL).",
    )
    p_demo.add_argument("--json", action="store_true", help="Emit raw service payload as JSON.")
    p_demo.set_defaults(explorer_command="demo")

    p_evidence = sub.add_parser(
        "evidence",
        help="Call Explorer Beta guided evidence. No input uses built-in samples; --qasm/--context-json uses derived local context.",
    )
    p_evidence.add_argument(
        "--base-url",
        default=None,
        help="Override qCoder Explorer Beta base URL (default env: QCODER_STUDENT_BASE_URL, QCODER_PREVIEW_BASE_URL, or QCODER_PRO_API_URL).",
    )
    p_evidence.add_argument("--json", action="store_true", help="Emit raw service payload as JSON.")
    p_evidence.add_argument(
        "--qasm",
        default=None,
        help="Build sanitized derived context from a local OpenQASM 2 file and request Explorer Beta guidance.",
    )
    p_evidence.add_argument(
        "--context-json",
        default=None,
        help="Use an existing qCoder preflight context JSON artifact; raw paths and source are not sent.",
    )
    p_evidence.add_argument(
        "--out-json", default=None, help="Write Explorer evidence response JSON."
    )
    p_evidence.add_argument(
        "--out-md", default=None, help="Write Explorer evidence response Markdown."
    )
    p_evidence.add_argument(
        "--share-safe",
        "--redact",
        dest="share_safe",
        action="store_true",
        help="Write output artifacts with explicit share-safe metadata and local-sensitive details redacted.",
    )
    p_evidence.set_defaults(explorer_command="evidence")

    args = p.parse_args(argv)
    if args.explorer_command is None:
        p.print_help()
        return 0

    if args.explorer_command in {"status", "demo"}:
        return _run_student_builtin_review_check(
            base_url_override=args.base_url,
            mode=args.explorer_command,
            json_output=args.json,
            compatibility_alias=compatibility_alias,
            command_prefix=prog,
        )
    if args.explorer_command == "evidence":
        return _run_student_evidence_check(
            base_url_override=args.base_url,
            json_output=args.json,
            command_label=f"{prog} evidence",
            compatibility_alias=compatibility_alias,
            qasm_path=args.qasm,
            context_json_path=args.context_json,
            out_json=args.out_json,
            out_md=args.out_md,
            share_safe=args.share_safe,
        )

    p.print_help()
    return 0


def _cmd_student(argv: list[str]) -> int:
    return _cmd_explorer(argv, compatibility_alias=True)


def _cmd_context_bridge(argv: list[str]) -> int:
    from qcoder.context_bridge_mcp import main as context_bridge_main

    return context_bridge_main(argv)


def _cmd_current_loop(argv: list[str]) -> int:
    from qcoder.context_bridge_mcp import DEFAULT_BASE_URL, default_token_file
    from qcoder.current_loop_coordinator import (
        ContextBridgeTransport,
        CurrentLoopCoordinator,
    )

    parser = argparse.ArgumentParser(
        prog="qcoder current-loop",
        description=(
            "Coordinate one explicit local Explorer Context Loop. Connected assistants "
            "invoke this surface; customers do not assemble canonical payloads."
        ),
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Explicit current-loop workspace (default: current directory).",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Explicit external local-state file; never selected automatically.",
    )
    sub = parser.add_subparsers(dest="current_loop_command")

    sub.add_parser("status", help="Show the bounded current-loop status.")

    activate = sub.add_parser(
        "activate",
        help=(
            "Stage an exact Request Baseline for review, then explicitly activate "
            "using the saved capture."
        ),
        description=(
            "A request source stages the complete message verbatim without activation. "
            "After the customer reviews that exact display, invoke activate again with "
            "--approve and no request source. Posture remains a separate authority."
        ),
    )
    request_source = activate.add_mutually_exclusive_group()
    request_source.add_argument(
        "--request",
        help=(
            "Complete governing customer message supplied inline and preserved exactly; "
            "this stages review and does not activate qCoder."
        ),
    )
    request_source.add_argument(
        "--request-file",
        help=(
            "Path to exact UTF-8 request bytes. The file is read directly without "
            "newline normalization; this stages review and does not activate qCoder."
        ),
    )
    request_source.add_argument(
        "--request-stdin",
        action="store_true",
        help=(
            "Read exact UTF-8 request bytes from non-interactive stdin. A TTY is rejected "
            "rather than awaited; this stages review and does not activate qCoder."
        ),
    )
    activate.add_argument(
        "--constraint",
        action="append",
        default=[],
        help=(
            "Add one user-stated constraint that occurs verbatim in the captured "
            "request. Extraction is additive and never removes request wording."
        ),
    )
    activate.add_argument(
        "--choice",
        action="append",
        default=[],
        help=(
            "Add one user-stated choice that occurs verbatim in the captured request. "
            "Extraction is additive and never removes request wording."
        ),
    )
    activate.add_argument(
        "--assistant-interpretation",
        default=None,
        help=(
            "Optional assistant proposal stored only as assistant_proposed. It is not "
            "confirmed by activation and remains subject to intent review."
        ),
    )
    activate.add_argument(
        "--posture",
        choices=("exploratory_first_pass", "blueprint_guided"),
        default=None,
        help=(
            "Separately selected generation posture. The value carries no authority "
            "without --approve-posture and attributable --posture-provenance."
        ),
    )
    activate.add_argument(
        "--approve-posture",
        action="store_true",
        help=(
            "Carry separate explicit human authority for --posture. Omission is not "
            "approval; supply only after the user selects or accepts that posture, "
            "and never infer or manufacture approval."
        ),
    )
    activate.add_argument(
        "--posture-provenance",
        choices=(
            "user_provided",
            "user_confirmed_assistant_recommendation",
            "inherited_confirmed_lineage",
        ),
        default=None,
        help=(
            "Attributable source of the separate posture choice. It carries no "
            "authority without --approve-posture."
        ),
    )
    activate.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Carry explicit human authority to activate qCoder and preserve the complete "
            "previously displayed pending capture as the exact Request Baseline. "
            "Omission is not approval; supply only after the user approves that exact "
            "display, and never infer or manufacture approval. A new request supplied "
            "in the same invocation is staged for review and is not activated."
        ),
    )
    activate.add_argument(
        "--label",
        default=None,
        help=(
            "Optional attributed display label; it never replaces or abbreviates original_request."
        ),
    )
    activate.add_argument(
        "--label-provenance",
        choices=("user_provided", "user_confirmed_assistant_interpretation"),
        default=None,
        help=(
            "Required provenance for a supplied --label. Omission with a label fails "
            "closed; the assistant may not invent customer label authority."
        ),
    )

    prepare = sub.add_parser(
        "prepare-generation",
        help=(
            "First create or refresh a proposed interpretation for review; after the "
            "user approves it, re-invoke with --confirm-intent to create the confirmed "
            "intent, Blueprint, contract, and generation context."
        ),
        description=(
            "The first unconfirmed call creates or refreshes a proposed interpretation. "
            "Conversational approval is not canonical by itself: the next invocation "
            "must transmit it with --confirm-intent and must follow the coordinator's "
            "supported_next_action and next_invocation."
        ),
    )
    _add_current_loop_transport_arguments(prepare, DEFAULT_BASE_URL, default_token_file())
    prepare.add_argument(
        "--profile",
        required=True,
        choices=("generic_qiskit", "grover_search", "qaoa"),
    )
    prepare.add_argument(
        "--interpretation-summary",
        required=True,
        help=(
            "Exact reviewed assistant-proposed summary. Reuse the coordinator-supplied "
            "value on confirmation; do not reconstruct a canonical artifact."
        ),
    )
    prepare.add_argument(
        "--profile-answer",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help=(
            "One reviewed profile answer as FIELD=VALUE; repeat for each answer and "
            "reuse the reviewed values exactly on confirmation."
        ),
    )
    prepare.add_argument("--constraint", action="append", default=[])
    prepare.add_argument("--non-goal", action="append", default=[])
    prepare.add_argument(
        "--confirm-intent",
        action="store_true",
        help=(
            "Carry explicit human authority confirming the reviewed interpretation. "
            "Omission is not approval; supply only after the user approves, and never "
            "infer or manufacture that approval. Chat approval alone does not transmit "
            "canonical confirmation."
        ),
    )
    prepare.add_argument(
        "--confirmation",
        default=None,
        help=(
            "Optional bounded human confirmation statement accompanying "
            "--confirm-intent. It is not approval by itself; supply only after the "
            "corresponding user approval and never infer or manufacture it."
        ),
    )
    prepare.add_argument(
        "--decision-disposition",
        action="append",
        nargs=4,
        default=[],
        metavar=("DECISION_ID", "ACTION", "VALUE", "PROVENANCE"),
        help=(
            "Carry one reviewed decision as four separate argv values: catalog decision "
            "ID, selected_choice or left_unresolved, the exact value (use - only for "
            "left_unresolved), and attributable provenance. Repeat for multiple "
            "decisions. Omission is not approval; use only after explicit user action, "
            "and never infer or manufacture a value."
        ),
    )
    prepare.add_argument(
        "--approve-decisions",
        action="store_true",
        help=(
            "Carry explicit human authority for every --decision-disposition in this "
            "invocation. Omission is not approval; supply only after the user approves "
            "those exact dispositions, and never infer or manufacture approval."
        ),
    )
    prepare.add_argument(
        "--posture",
        choices=("exploratory_first_pass", "blueprint_guided"),
        default=None,
        help=(
            "Keep or explicitly request the generation posture for this attempt. "
            "Workspace freshness is not posture authority."
        ),
    )
    prepare.add_argument(
        "--approve-posture-change",
        action="store_true",
        help=(
            "Carry explicit human authority to change this attempt's posture. Omission "
            "is not approval; supply only after the user approves, and never infer or "
            "manufacture the transition."
        ),
    )
    prepare.add_argument(
        "--posture-reason",
        default=None,
        help=(
            "Bounded user meaning for an explicitly authorized posture transition; "
            "not approval by itself."
        ),
    )
    prepare.add_argument(
        "--posture-provenance",
        choices=(
            "user_provided",
            "user_confirmed_assistant_recommendation",
            "inherited_confirmed_lineage",
        ),
        default=None,
        help=(
            "Attributable source of the posture transition. It carries no authority "
            "without --approve-posture-change."
        ),
    )

    authority = sub.add_parser(
        "record-ide-authority",
        help="Record the IDE host's separate explicit write/run decision.",
    )
    authority.add_argument(
        "--allow",
        action="store_true",
        help=(
            "Carry the human decision allowing the IDE host to write or run. Omission "
            "is not approval; supply only after that user approval, and never infer or "
            "manufacture it."
        ),
    )
    authority.add_argument(
        "--explicit",
        action="store_true",
        help=(
            "Assert that --allow came from an explicit human action. Omission is not "
            "approval; supply only after that action, and never infer or manufacture it."
        ),
    )

    register = sub.add_parser(
        "register-artifacts",
        help="Register only exact candidate paths; no scan or discovery.",
    )
    register.add_argument(
        "--source",
        action="append",
        default=[],
        help=(
            "Exact source-file path retained from an authorized IDE operation or exact "
            "user selection. Globs and discovery are prohibited."
        ),
    )
    register.add_argument(
        "--qasm",
        action="append",
        default=[],
        help=(
            "Exact circuit/QASM path retained from an authorized IDE operation or exact "
            "user selection. Do not search a directory for it."
        ),
    )
    register.add_argument(
        "--results",
        action="append",
        default=[],
        help=(
            "Exact result-evidence path retained from an authorized IDE operation or "
            "exact user selection. Do not infer neighboring result files."
        ),
    )
    register.add_argument(
        "--provenance",
        choices=(
            "assistant_created",
            "assistant_modified",
            "user_selected",
            "user_supplied",
        ),
        required=True,
        help=(
            "Truthful origin for every path in this invocation: assistant_created, "
            "assistant_modified, or user_selected. Legacy user_supplied is accepted as "
            "user_selected. Omission is invalid; use only after the corresponding IDE "
            "operation or explicit user selection, and never infer or manufacture it."
        ),
    )
    register.add_argument(
        "--related-circuit-ref",
        default=None,
        help=(
            "Existing canonical circuit reference for exact related artifacts. It does "
            "not authorize discovery or review."
        ),
    )
    register.add_argument(
        "--allow-external",
        action="store_true",
        help=(
            "Carry explicit selection authority for a named artifact outside the active "
            "workspace. Omission is not approval; supply only after the user selects "
            "that exact path, and never infer or manufacture approval. It authorizes no "
            "directory discovery and never permits qCoder local state."
        ),
    )

    authorize = sub.add_parser(
        "authorize-artifacts",
        help="Apply one explicit exact-set authorization action.",
    )
    authorize.add_argument(
        "--action",
        required=True,
        choices=("approve_all", "remove_one", "add_one_explicitly", "decline"),
        help=(
            "Carry the user's exact artifact-set decision. Omission is not approval; "
            "supply only the action the user selected, and never infer or manufacture "
            "it."
        ),
    )
    authorize.add_argument(
        "--provenance",
        required=True,
        help="Bounded provenance for the explicit artifact-set action.",
    )
    authorize.add_argument("--path", default=None)
    authorize.add_argument(
        "--role",
        choices=("source", "circuit_qasm", "results", "other_supported"),
        default=None,
    )
    authorize.add_argument("--artifact-type", default=None)

    process = sub.add_parser(
        "process-authorized-artifacts",
        help="Run supported local extraction for the exact approved set.",
    )
    _add_current_loop_transport_arguments(process, DEFAULT_BASE_URL, default_token_file())

    review = sub.add_parser(
        "review-build",
        help="Create current-build review from exact saved artifacts.",
    )
    _add_current_loop_transport_arguments(review, DEFAULT_BASE_URL, default_token_file())

    unchanged = sub.add_parser(
        "continue-unchanged",
        help="Explicitly continue with the unchanged governing Blueprint.",
    )
    unchanged.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Carry explicit human authority for Unchanged Continuation. Omission is not "
            "approval; supply only after the user approves, and never infer or "
            "manufacture that approval."
        ),
    )
    unchanged.add_argument(
        "--statement",
        required=True,
        help=(
            "Exact bounded user statement supporting Unchanged Continuation; do not "
            "invent or paraphrase it as authority."
        ),
    )
    unchanged.add_argument(
        "--decline-proposal",
        action="store_true",
        help=(
            "Carry the user's explicit decision to decline the pending proposal while "
            "continuing unchanged. Omission is not a decline; supply only after that "
            "user decision, and never infer or manufacture it."
        ),
    )

    propose = sub.add_parser(
        "propose-change",
        help="Request one unconfirmed proposal from an explicit semantic selection.",
    )
    _add_current_loop_transport_arguments(propose, DEFAULT_BASE_URL, default_token_file())
    propose.add_argument("--decision-ref", required=True)
    propose.add_argument("--selected-action", required=True)
    propose.add_argument("--proposed-value", required=True)
    propose.add_argument("--control-treatment", required=True)
    propose.add_argument(
        "--approve-selection",
        action="store_true",
        help=(
            "Carry explicit human authority for the exact semantic selection used to "
            "request a proposal. Omission is not approval; supply only after the user "
            "selects it, and never infer or manufacture approval."
        ),
    )

    confirm = sub.add_parser(
        "confirm-change",
        help="Confirm one exact proposal through selected-bundle parent resupply.",
    )
    _add_current_loop_transport_arguments(confirm, DEFAULT_BASE_URL, default_token_file())
    confirm.add_argument(
        "--confirmation",
        required=True,
        help=(
            "Exact proposal-specific semantic confirmation from the user. The text is "
            "not approval without --approve; never infer or manufacture either."
        ),
    )
    confirm.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Carry proposal-specific human confirmation for the exact reviewed change. "
            "Omission is not approval; supply only after the user confirms, and never "
            "infer or manufacture confirmation."
        ),
    )

    start_next = sub.add_parser(
        "start-next",
        help="Explicitly activate a new loop from one seed and exact parent files.",
    )
    start_next.add_argument("--next-workspace", required=True)
    start_next.add_argument(
        "--posture",
        required=True,
        choices=("exploratory_first_pass", "blueprint_guided"),
    )
    start_next.add_argument("--seed-file", required=True)
    start_next.add_argument(
        "--parent-file",
        action="append",
        default=[],
        metavar="ROLE=/ABSOLUTE/PATH",
    )
    start_next.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Carry explicit human authority to activate the next loop from the supplied "
            "seed and parents. Omission is not approval; supply only after the user "
            "approves, and never infer or manufacture it."
        ),
    )

    standalone = sub.add_parser(
        "standalone-review",
        help="Create bounded evidence without activating a current loop.",
    )
    standalone.add_argument("--role", required=True, choices=("source", "circuit_qasm", "results"))
    standalone.add_argument("--path", required=True)
    standalone.add_argument("--destination", required=True)
    standalone.add_argument("--related-circuit-ref", default=None)

    attach = sub.add_parser(
        "attach-to-loop",
        help="Propose one exact standalone artifact for explicit loop authorization.",
    )
    attach.add_argument(
        "--role",
        required=True,
        choices=("source", "circuit_qasm", "results", "other_supported"),
    )
    attach.add_argument("--path", required=True)
    attach.add_argument(
        "--provenance",
        choices=(
            "assistant_created",
            "assistant_modified",
            "user_selected",
            "user_supplied",
        ),
        default="user_selected",
    )

    abandon = sub.add_parser("abandon", help="Explicitly abandon the active local loop.")
    abandon.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Carry explicit human authority to abandon the active loop. Omission is not "
            "approval; supply only after the user approves, and never infer or "
            "manufacture that approval."
        ),
    )

    args = parser.parse_args(argv)
    if args.current_loop_command is None:
        parser.print_help()
        return 0
    transport = None
    if hasattr(args, "base_url"):
        transport = ContextBridgeTransport(
            base_url=args.base_url,
            token_file=args.token_file,
        )
    coordinator = CurrentLoopCoordinator(
        workspace_root=args.workspace,
        state_path=args.state_file,
        transport=transport,
    )
    try:
        command = args.current_loop_command
        if command == "status":
            result = coordinator.status()
        elif command == "activate":
            request, request_transport = _read_current_loop_request(args)
            result = coordinator.activate(
                original_request=request,
                generation_posture=args.posture,
                explicit_authority=args.approve,
                explicit_posture_authority=args.approve_posture,
                posture_authority_provenance=args.posture_provenance,
                request_transport=request_transport or "inline",
                explicit_constraints=args.constraint,
                explicit_choices=args.choice,
                label=args.label,
                label_provenance=args.label_provenance,
                assistant_interpretation=(
                    {
                        "text": args.assistant_interpretation,
                        "provenance_role": "assistant_proposed",
                    }
                    if args.assistant_interpretation is not None
                    else None
                ),
            )
        elif command == "prepare-generation":
            answers = _parse_current_loop_key_values(args.profile_answer)
            dispositions = _parse_current_loop_decision_dispositions(args.decision_disposition)
            result = coordinator.prepare_generation(
                profile_id=args.profile,
                proposed_interpretation={
                    "summary": args.interpretation_summary,
                    "provenance_role": "assistant_proposed",
                },
                reviewed_profile_answers=answers,
                constraints=args.constraint,
                non_goals=args.non_goal,
                explicit_intent_approval=args.confirm_intent,
                confirmation_assertion=args.confirmation,
                decision_dispositions=dispositions,
                explicit_decision_authority=args.approve_decisions,
                requested_generation_posture=args.posture,
                explicit_posture_authority=args.approve_posture_change,
                posture_change_reason=args.posture_reason,
                posture_authority_provenance=args.posture_provenance,
            )
        elif command == "record-ide-authority":
            result = coordinator.record_ide_authority(
                allowed=args.allow,
                explicit_user_action=args.explicit,
            )
        elif command == "register-artifacts":
            candidates = []
            for role, values in (
                ("source", args.source),
                ("circuit_qasm", args.qasm),
                ("results", args.results),
            ):
                candidates.extend(
                    {
                        "role": role,
                        "path": str(Path(value).expanduser().absolute()),
                        "provenance": args.provenance,
                        "explicit_external": args.allow_external,
                        "related_circuit_ref": (
                            args.related_circuit_ref if role == "results" else None
                        ),
                    }
                    for value in values
                )
            result = coordinator.register_artifacts(candidates=candidates)
        elif command == "authorize-artifacts":
            result = coordinator.authorize_artifacts(
                action=args.action,
                explicit_action_provenance=args.provenance,
                selected_path=args.path,
                artifact_role=args.role,
                artifact_type=args.artifact_type,
            )
        elif command == "process-authorized-artifacts":
            result = coordinator.process_authorized_artifacts()
        elif command == "review-build":
            result = coordinator.review_build()
        elif command == "continue-unchanged":
            result = coordinator.continue_unchanged(
                explicit_user_action=args.approve,
                user_statement=args.statement,
                decline_unconfirmed_proposal=args.decline_proposal,
            )
        elif command == "propose-change":
            result = coordinator.propose_change(
                decision_ref=args.decision_ref,
                selected_action=args.selected_action,
                proposed_value=_parse_current_loop_scalar(args.proposed_value),
                control_treatment=args.control_treatment,
                explicit_user_selection=args.approve_selection,
            )
        elif command == "confirm-change":
            result = coordinator.confirm_change(
                semantic_confirmation=args.confirmation,
                explicit_user_confirmation=args.approve,
            )
        elif command == "start-next":
            result = coordinator.start_next(
                next_workspace_root=args.next_workspace,
                generation_posture=args.posture,
                seed_file=args.seed_file,
                parent_files=_parse_current_loop_key_values(args.parent_file),
                explicit_authority=args.approve,
            )
        elif command == "standalone-review":
            result = coordinator.standalone_review(
                role=args.role,
                path=args.path,
                destination=args.destination,
                related_circuit_ref=args.related_circuit_ref,
            )
        elif command == "attach-to-loop":
            result = coordinator.attach_to_loop(
                role=args.role,
                path=args.path,
                provenance=args.provenance,
            )
        else:
            result = coordinator.abandon(explicit_authority=args.approve)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") is True else 2


def _add_current_loop_transport_arguments(
    parser: argparse.ArgumentParser,
    default_base_url: str,
    default_token_path: Path,
) -> None:
    parser.add_argument("--base-url", default=default_base_url)
    parser.add_argument("--token-file", default=str(default_token_path))


def _read_current_loop_request(
    args: argparse.Namespace,
) -> tuple[str | None, str | None]:
    if args.request is not None:
        request = args.request
        transport = "inline"
    elif args.request_file is not None:
        request_path = Path(args.request_file).expanduser()
        try:
            if request_path.is_symlink() or not request_path.is_file():
                raise ValueError("request_file_not_regular")
            if request_path.stat().st_size > _CURRENT_LOOP_REQUEST_MAX_UTF8_BYTES:
                raise ValueError("request_baseline_original_request_too_large")
            raw = request_path.read_bytes()
        except OSError as exc:
            raise ValueError("request_file_unreadable") from exc
        try:
            request = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("request_input_invalid_utf8") from exc
        transport = "file"
    elif args.request_stdin:
        if sys.stdin.isatty():
            raise ValueError("request_stdin_requires_noninteractive_input")
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        raw_or_text = stream.read(_CURRENT_LOOP_REQUEST_MAX_UTF8_BYTES + 1)
        if len(raw_or_text) > _CURRENT_LOOP_REQUEST_MAX_UTF8_BYTES:
            raise ValueError("request_baseline_original_request_too_large")
        if isinstance(raw_or_text, bytes):
            try:
                request = raw_or_text.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("request_input_invalid_utf8") from exc
        else:
            request = str(raw_or_text)
        transport = "stdin"
    else:
        return None, None
    if request == "":
        raise ValueError("request_input_empty")
    if len(request) > _CURRENT_LOOP_REQUEST_MAX_CODEPOINTS:
        raise ValueError("request_baseline_original_request_too_large")
    return request, transport


def _parse_current_loop_key_values(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key.strip() or not item or key in result:
            raise ValueError("current_loop_key_value_invalid")
        result[key.strip()] = item
    return result


def _parse_current_loop_decision_dispositions(
    values: list[list[str]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for value in values:
        if len(value) != 4 or any(not item.strip() for item in value):
            raise ValueError("current_loop_decision_disposition_invalid")
        decision_id, action, selected_value, provenance = value
        result.append(
            {
                "profile_decision_id": decision_id.strip(),
                "user_disposition": action.strip(),
                "selected_value": selected_value if selected_value != "-" else None,
                "authority_provenance": provenance.strip(),
            }
        )
    return result


def _parse_current_loop_scalar(value: str) -> object:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, (dict, list)):
        raise ValueError("current_loop_scalar_value_required")
    return parsed


def _cmd_blueprint(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="qcoder blueprint",
        description="Create deterministic machine-local Algorithm Blueprint evidence.",
    )
    subparsers = parser.add_subparsers(dest="blueprint_command")
    source_parser = subparsers.add_parser(
        "source-evidence",
        help="Extract compact static evidence from one selected Python file or bounded stdin.",
    )
    source_group = source_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--source-file",
        help="One explicitly selected .py file; no directory or import traversal is performed.",
    )
    source_group.add_argument(
        "--excerpt-stdin",
        action="store_true",
        help="Read one bounded Python excerpt from stdin and discard it after extraction.",
    )
    source_parser.add_argument(
        "--logical-label",
        default=None,
        help="Share-safe logical source label; defaults to the selected basename or 'stdin excerpt'.",
    )
    source_parser.add_argument(
        "--symbol", default=None, help="Optional selected function or class name."
    )
    source_parser.add_argument("--start-line", type=int, default=None)
    source_parser.add_argument("--end-line", type=int, default=None)
    source_parser.add_argument(
        "--source-evidence-depth",
        choices=("disabled", SOURCE_EVIDENCE_DEPTH_GATE),
        default=None,
        help="Explicitly opt into bounded blueprint-relative source depth v1.",
    )
    source_parser.add_argument("--profile", choices=PROFILE_IDS, default=None)
    source_parser.add_argument("--source-reference", default=None)
    source_parser.add_argument("--blueprint-reference", default=None)
    source_parser.add_argument(
        "--expected-motif",
        action="append",
        default=[],
        help="Confirmed or profile-expected canonical motif identifier; repeat as needed.",
    )
    source_parser.add_argument("--sdk-version", default=None)
    args = parser.parse_args(argv)
    if args.blueprint_command is None:
        parser.print_help()
        return 0
    if (args.start_line is None) != (args.end_line is None):
        print(
            "qcoder blueprint: --start-line and --end-line must be supplied together.",
            file=sys.stderr,
        )
        return 2
    line_span = (
        (args.start_line, args.end_line)
        if args.start_line is not None and args.end_line is not None
        else None
    )
    development_context = None
    if args.source_evidence_depth == SOURCE_EVIDENCE_DEPTH_GATE:
        if not all(
            (args.profile, args.source_reference, args.blueprint_reference, args.expected_motif)
        ):
            print(
                "qcoder blueprint: depth_v1 requires --profile, --source-reference, "
                "--blueprint-reference, and at least one --expected-motif.",
                file=sys.stderr,
            )
            return 2
        development_context = {
            "source_reference_id": args.source_reference,
            "blueprint_reference_id": args.blueprint_reference,
            "profile_id": args.profile,
            "expected_requirements": [
                {"motif_id": motif, "choice_origin": "blueprint_confirmed"}
                for motif in args.expected_motif
            ],
            "explicit_sdk_version": args.sdk_version,
        }
    try:
        if args.source_file:
            artifact = extract_selected_python_file_evidence(
                args.source_file,
                logical_source_label=args.logical_label,
                selected_symbol=args.symbol,
                line_span=line_span,
                development_evidence_context=development_context,
                source_evidence_depth=args.source_evidence_depth,
            )
        else:
            artifact = extract_selected_python_source_evidence(
                sys.stdin.read(),
                logical_source_label=args.logical_label or "stdin excerpt",
                selected_symbol=args.symbol,
                line_span=line_span,
                development_evidence_context=development_context,
                source_evidence_depth=args.source_evidence_depth,
            )
    except ValueError as exc:
        print(f"qcoder blueprint: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0


def _cmd_pro(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="qcoder pro",
        add_help=True,
        description=(
            "Archived qCoder Pro client-contract shell.\n"
            "Pro is not a current public product and confidential Pro analysis is not shipped in this package."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON where available.",
    )
    sub = p.add_subparsers(dest="pro_command")

    p_signup = sub.add_parser(
        "signup", help="Show archived Pro status and current public qCoder paths."
    )
    p_signup.set_defaults(pro_command="signup")

    p_status = sub.add_parser("status", help="Show archived Pro client status.")
    p_status.set_defaults(pro_command="status")

    p_login = sub.add_parser(
        "login", help="Store archived pilot token locally (no remote validation in this slice)."
    )
    p_login.add_argument(
        "--token",
        required=True,
        help="QRS-provided archived pilot token for local config. Treat as private credential.",
    )
    p_login.add_argument(
        "--api-url", required=False, help="Optional service URL override for local config."
    )
    p_login.set_defaults(pro_command="login")

    p_install = sub.add_parser(
        "install", help="Configure archived pilot token (no code download in this slice)."
    )
    p_install.add_argument(
        "--token",
        required=True,
        help="QRS-provided archived pilot token for local config. Treat as private credential.",
    )
    p_install.add_argument(
        "--api-url", required=False, help="Optional service URL override for local config."
    )
    p_install.set_defaults(pro_command="install")

    p_validate = sub.add_parser(
        "validate", help="Validate archived Pro client config and public package boundaries."
    )
    p_validate.set_defaults(pro_command="validate")

    p_workflow = sub.add_parser(
        "workflow",
        help="Prepare or explicitly submit a Pro workflow manifest to a configured service.",
    )
    p_workflow.add_argument("--qasm", default=None, help="Path to a single QASM file.")
    p_workflow.add_argument("--before-qasm", default=None, help="Path to before QASM file.")
    p_workflow.add_argument("--after-qasm", default=None, help="Path to after QASM file.")
    p_workflow.add_argument("--project-dir", default=None, help="Local project directory.")
    p_workflow.add_argument(
        "--dry-run-manifest",
        default=None,
        help="Write a local workflow manifest JSON and perform no upload.",
    )
    p_workflow.add_argument(
        "--submit",
        action="store_true",
        help="Submit a sanitized manifest to configured service (explicit only).",
    )
    p_workflow.add_argument(
        "--service-url",
        default=None,
        help="Invocation-only service URL override for --submit.",
    )
    p_workflow.add_argument(
        "--manifest-out",
        default=None,
        help="Optional path to write sanitized submit manifest JSON.",
    )
    p_workflow.set_defaults(pro_command="workflow")

    p_preview = sub.add_parser("preview", help="Archived preview demo connectivity checks.")
    p_preview_sub = p_preview.add_subparsers(dest="pro_preview_command")

    p_preview_status = p_preview_sub.add_parser(
        "status",
        help="Call archived preview demo endpoint and print safe connectivity summary.",
    )
    p_preview_status.add_argument(
        "--base-url",
        default=None,
        help="Override archived preview base URL (default env: QCODER_PREVIEW_BASE_URL or QCODER_PRO_API_URL).",
    )
    p_preview_status.set_defaults(pro_command="preview-status")

    p_preview_demo = p_preview_sub.add_parser(
        "demo",
        help="Alias of preview status check; calls /v0/demo/builtin-review.",
    )
    p_preview_demo.add_argument(
        "--base-url",
        default=None,
        help="Override archived preview base URL (default env: QCODER_PREVIEW_BASE_URL or QCODER_PRO_API_URL).",
    )
    p_preview_demo.set_defaults(pro_command="preview-demo")

    args, unknown = p.parse_known_args(argv)
    cmd = args.pro_command
    json_output = args.json or ("--json" in unknown)

    if cmd is None:
        p.print_help()
        return 0

    if cmd == "signup":
        payload = {
            "schema_id": "qcoder.pro_preview_shell.v0",
            "pro_public_signup": False,
            "explorer_beta_docs": EXPLORER_BETA_DOCS_URL,
            "oss_docs": OSS_DOCS_URL,
            "service_backed": False,
            "local_only": False,
            "cards_local": False,
            "status": "not_current_public_product",
        }
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("qCoder Pro is not a current public signup path.")
            print("  status: archived pilot/client-contract surface only")
            print(f"  Explorer Beta: {EXPLORER_BETA_DOCS_URL}")
            print(f"  OSS: {OSS_DOCS_URL}")
            print("  note: no confidential Pro analysis is bundled locally")
        return 0

    if cmd == "status":
        payload = _build_pro_bootstrap_payload(
            status="configured" if resolve_token().present else "not_configured"
        )
        submit_ready = bool(payload["token_present"]) and _is_non_default_service_url(
            resolve_api_url().value
        )
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"qCoder Pro status: {payload['status']}.")
            print("  mode: archived pilot bootstrap shell")
            print(
                f"  token: {'present' if payload['token_present'] else 'not set'} ({payload['token_source']})"
            )
            if payload["api_url_source"] == "default":
                print(
                    "  submit-ready service URL: not set (default archived preview URL is informational)"
                )
            else:
                print("  submit-ready service URL: configured")
            print(f"  service URL source: {payload['api_url_source']}")
            print(f"  pilot submit readiness: {'ready' if submit_ready else 'not ready'}")
            print("  submit requirement: QRS-provided token + non-default service URL")
            print("  service validation: not available in this slice")
            print("  local cards/analysis: disabled in public package")
            print(
                f"  current public paths: Explorer Beta {EXPLORER_BETA_DOCS_URL} / OSS {OSS_DOCS_URL}"
            )
        return 0

    if cmd in {"login", "install"}:
        try:
            config_path = store_local_bootstrap_config(token=args.token, api_url=args.api_url)
        except ProPreviewConfigError as exc:
            print(f"qcoder pro {cmd}: {exc}", file=sys.stderr)
            return 2
        payload = _build_pro_bootstrap_payload(status="configured")
        payload["operation"] = cmd
        payload["config_path"] = str(config_path)
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("Configured archived qCoder Pro pilot local token settings.")
            print(f"  operation: {cmd}")
            print(f"  config: {config_path}")
            print("  token: stored locally (not displayed)")
            print("  token hygiene: do not paste tokens into tickets, screenshots, or chat")
            print("  service validation: not performed in this slice")
            print("  upload: none performed")
            print("  local package: non-confidential bootstrap plumbing only")
            print("  confidential Pro analysis: remains service-side")
        return 0

    if cmd == "validate":
        token = resolve_token()
        api_url = resolve_api_url()
        try:
            _ = load_local_config()
            local_config_valid = True
        except ProPreviewConfigError:
            local_config_valid = False
        pro_v0_py_exists = any((Path(__file__).resolve().parent / "pro_v0").glob("*.py"))
        submit_ready = token.present and _is_non_default_service_url(api_url.value)
        payload = {
            "schema_id": "qcoder.pro_preview_validate.v0",
            "status": "ok" if local_config_valid else "config_error",
            "configured": token.present and local_config_valid,
            "token_present": token.present,
            "token_source": token.source,
            "api_url_configured": api_url.present,
            "api_url_source": api_url.source,
            "service_validation": "not_available",
            "cards_local": False,
            "local_pro_analysis": False,
            "confidential_analysis_local": False,
            "upload_performed": False,
            "pro_v0_local_module_present": pro_v0_py_exists,
            "public_boundary_ok": (not pro_v0_py_exists) and local_config_valid,
        }
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("qCoder Pro validate")
            print(f"  status: {payload['status']}")
            print(f"  token: {'present' if token.present else 'not set'} ({token.source})")
            if api_url.source == "default":
                print(
                    "  submit-ready service URL: not set (default archived preview URL is informational)"
                )
            else:
                print("  submit-ready service URL: configured")
            print(f"  service URL source: {api_url.source}")
            print(
                f"  public package boundary checks: {'ok' if payload['public_boundary_ok'] else 'needs attention'}"
            )
            print(f"  pilot submit readiness: {'ready' if submit_ready else 'not ready'}")
            print("  submit requirement: QRS-provided token + non-default service URL")
            print("  service validation: not available in this slice")
            print("  local cards/confidential analysis: absent")
            print("  artifact/source upload: not performed in this command path")
        return 0 if payload["status"] == "ok" else 2

    if cmd in {"preview-status", "preview-demo"}:
        return _run_pro_preview_demo_check(base_url_override=args.base_url)

    if cmd == "workflow":
        if args.dry_run_manifest:
            try:
                manifest = build_workflow_manifest(
                    qasm=args.qasm,
                    before_qasm=args.before_qasm,
                    after_qasm=args.after_qasm,
                    project_dir=args.project_dir,
                )
                output_path = write_workflow_manifest(manifest, args.dry_run_manifest)
            except (ProPreviewManifestError, OSError, RuntimeError, ValueError) as exc:
                print(f"qcoder pro workflow: {exc}", file=sys.stderr)
                return 2
            payload = {
                "schema_id": manifest["schema_id"],
                "status": "manifest_written",
                "manifest_path": str(output_path),
                "mode": manifest["mode"],
                "upload_performed": False,
                "network_performed": False,
            }
            if json_output:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("qCoder Pro workflow dry-run manifest written.")
                print(f"  manifest: {output_path}")
                print(f"  mode: {manifest['mode']}")
                print("  upload: none performed")
                print("  network: none performed")
                print("  confidential Pro analysis: remains service-side")
            return 0

        if args.submit:
            try:
                manifest = build_workflow_manifest(
                    qasm=args.qasm,
                    before_qasm=args.before_qasm,
                    after_qasm=args.after_qasm,
                    project_dir=args.project_dir,
                )
                submit_manifest = sanitize_manifest_for_submit(manifest)
            except (ProPreviewManifestError, OSError, RuntimeError, ValueError) as exc:
                print(f"qcoder pro workflow: {exc}", file=sys.stderr)
                return 2

            manifest_out_path = None
            if args.manifest_out:
                try:
                    manifest_out_path = write_workflow_manifest(submit_manifest, args.manifest_out)
                except (OSError, RuntimeError, ValueError) as exc:
                    print(f"qcoder pro workflow: {exc}", file=sys.stderr)
                    return 2

            token = resolve_token()
            if not token.present:
                print(
                    "qcoder pro workflow: --submit requires a configured token.\n"
                    "Run `qcoder pro login --token <token>` or set QCODER_PRO_TOKEN.\n"
                    "Do not share your token in tickets, screenshots, or chat.",
                    file=sys.stderr,
                )
                return 2

            if args.service_url and str(args.service_url).strip():
                service_url = str(args.service_url).strip()
                service_url_source = "flag"
            else:
                api_url = resolve_api_url()
                service_url = (api_url.value or "").strip()
                service_url_source = api_url.source

            if not service_url or service_url == DEFAULT_PRO_API_URL:
                print(
                    "qcoder pro workflow: No production hosted Pro service is configured for "
                    "this release. Service submit URL is not configured; use --service-url or "
                    "QCODER_PRO_API_URL only if QRS provided one.\n"
                    "For support, share only redacted output and error/status codes.",
                    file=sys.stderr,
                )
                return 2

            client = ProServiceClient(base_url=service_url)
            try:
                entitlement = client.post_entitlements_validate(token.value or "")
            except ProServiceClientError as exc:
                detail = exc.detail
                code = f"{detail.error_code}: " if detail.error_code else ""
                print(f"qcoder pro workflow: {code}{detail.message}", file=sys.stderr)
                return 2
            if entitlement.get("valid") is not True:
                error_code = None
                message = None
                if isinstance(entitlement.get("error"), dict):
                    error_code = entitlement["error"].get("error_code")
                    message = entitlement["error"].get("message")
                if not isinstance(error_code, str) or not error_code:
                    error_code = "ENTITLEMENT_INVALID"
                if not isinstance(message, str) or not message:
                    message = "token rejected by configured service"
                print(f"qcoder pro workflow: {error_code}: {message}", file=sys.stderr)
                return 2

            try:
                workflow_payload = client.post_workflow(submit_manifest, token.value or "")
            except ProServiceClientError as exc:
                detail = exc.detail
                code = f"{detail.error_code}: " if detail.error_code else ""
                print(f"qcoder pro workflow: {code}{detail.message}", file=sys.stderr)
                return 2

            payload = {
                "schema_id": "qcoder.pro_preview_submit_result.v0",
                "submitted": True,
                "service_url_configured": True,
                "service_url_source": service_url_source,
                "service_url": service_url,
                "manifest_schema_id": submit_manifest.get("schema_id"),
                "workflow_schema_id": workflow_payload.get("schema_id"),
                "job_id": workflow_payload.get("job_id"),
                "state": workflow_payload.get("state"),
                "result_refs": workflow_payload.get("result_refs", []),
                "analysis_performed": workflow_payload.get("analysis_performed"),
                "confidential_analysis_performed": workflow_payload.get(
                    "confidential_analysis_performed"
                ),
                "cards_generated": workflow_payload.get("cards_generated"),
                "production_execution": workflow_payload.get("production_execution"),
                "local_fake": workflow_payload.get("local_fake"),
                "upload_performed": False,
                "source_contents_included": False,
                "network_performed": True,
            }
            if manifest_out_path:
                payload["manifest_out_path"] = str(manifest_out_path)
            if json_output:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("qCoder Pro workflow submitted to configured service.")
                print(f"  service_url: {service_url}")
                print(f"  job_id: {payload['job_id']}")
                print(f"  state: {payload['state']}")
                print(f"  upload_performed: {payload['upload_performed']}")
                print(f"  source_contents_included: {payload['source_contents_included']}")
                print(f"  analysis_performed: {payload['analysis_performed']}")
                print(
                    f"  confidential_analysis_performed: {payload['confidential_analysis_performed']}"
                )
                print(f"  cards_generated: {payload['cards_generated']}")
                print(f"  production_execution: {payload['production_execution']}")
                if manifest_out_path:
                    print(f"  manifest_out: {manifest_out_path}")
            return 0

    print(
        "qcoder pro workflow: use --dry-run-manifest for local contract rehearsal (no network).\n"
        "For manifest-only submit, pass --submit with --service-url (or QCODER_PRO_API_URL) "
        "only if QRS provided a non-default service URL and token.\n"
        "No generally available production hosted Pro service is configured in this release.\n"
        "Run `qcoder pro signup` for current public qCoder paths.",
        file=sys.stderr,
    )
    return 2


def _print_root_help() -> None:
    print(
        "usage: qcoder [--version | -V] [-h] {analyze,batch,context,review,blueprint,current-loop,explorer,context-bridge,pro,student} ...\n\n"
        "Quantum circuit analysis CLI.\n\n"
        "positional arguments:\n"
        "  {analyze,batch,context,review,blueprint,current-loop,explorer,context-bridge,pro,student}  subcommand\n\n"
        "  analyze          Analyze a QASM file (feature extraction + metadata + run config).\n"
        "  batch            Batch extract a directory to JSONL (requires --out).\n"
        "  context          Build deterministic preflight context artifacts.\n"
        "  review           Build deterministic execution review artifacts from counts.\n"
        "  blueprint        Build machine-local static evidence for Algorithm Blueprint.\n"
        "  current-loop     Coordinate one explicit local Explorer Context Loop.\n"
        "  explorer         Explorer Beta status/demo/evidence checks.\n"
        "  context-bridge   Run the Context Bridge MCP adapter for eligible Explorer users.\n"
        "  pro              Archived Pro client-contract shell (not current public product).\n"
        "  student          Compatibility alias for Explorer Beta checks.\n\n"
        "Run `qcoder <subcommand> --help` for subcommand options.",
        end="",
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv in (["--version"], ["-V"]):
        from qcoder import __version__

        print(__version__)
        return 0

    if not argv or argv in (["-h"], ["--help"]):
        _print_root_help()
        return 0

    cmd, *rest = argv
    if cmd == "analyze":
        return _cmd_analyze(rest)
    if cmd == "batch":
        return _cmd_batch(rest)
    if cmd == "context":
        return _cmd_context(rest)
    if cmd == "review":
        return _cmd_review(rest)
    if cmd == "blueprint":
        return _cmd_blueprint(rest)
    if cmd == "current-loop":
        return _cmd_current_loop(rest)
    if cmd == "explorer":
        return _cmd_explorer(rest)
    if cmd == "context-bridge":
        return _cmd_context_bridge(rest)
    if cmd == "pro":
        return _cmd_pro(rest)
    if cmd == "student":
        return _cmd_student(rest)

    print(
        f"qcoder: unknown subcommand {cmd!r} (expected analyze, batch, context, review, blueprint, current-loop, explorer, context-bridge, pro, or student)",
        file=sys.stderr,
    )
    print("Run `qcoder --help` for usage.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
