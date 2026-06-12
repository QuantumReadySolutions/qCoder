from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qcoder.pipelines.analyze import analyze_qasm
from qcoder.pipelines.context import write_preflight_context
from qcoder.pipelines.review import write_execution_review
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

PREVIEW_SIGNUP_URL = "https://qcoder.ai/preview"


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
        help='Processor/backend label (aliases: Scarlet/Amber, CPU/GPU)',
    )
    p.add_argument("--precision", default="single", help="Precision: single|double (aliases: fp32/fp64)")
    p.add_argument("--threshold", type=float, default=None, help="Optional threshold/bond-dim conditioning value")
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
        print(
            json.dumps(
                report.to_json_dict(include_guidance=args.guidance, include_profiles=args.profiles),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    ex = report.example
    rc = report.run_config
    print(f"file: {ex.qasm_path}")
    print(f"format: {ex.ir.source_format}")
    if ex.name:
        print(f"name: {ex.name}")
    print(f"function_hint: {ex.function_hint} ({ex.function_source})")
    print(f"processor: {rc.processor}  backend: {rc.backend}  precision: {rc.precision}  threshold: {rc.threshold}")
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
    p.add_argument("--recursive", dest="recursive", action="store_true", help="Discover files recursively (default)")
    p.add_argument("--non-recursive", dest="recursive", action="store_false", help="Only discover top-level files")
    p.add_argument("--pattern", default="*.qasm", help="Glob pattern for files (default: *.qasm)")
    p.add_argument("--skip-errors", action="store_true", help="Continue on error, emit error records (default: fail-fast)")
    p.add_argument("--processor", default=None, help="Processor/backend label for run_config")
    p.add_argument("--backend", default=None, help="Backend label (CPU/GPU, etc.)")
    p.add_argument("--precision", default=None, help="Precision: single|double|fp32|fp64")
    p.add_argument("--threshold", type=float, default=None, help="Optional threshold for run_config")
    p.add_argument(
        "--mirror-artifacts-dir",
        default=None,
        metavar="DIR",
        help="If set, write mirror QASM to DIR and add adjoint_supported/adjoint_reason/mirror_qasm_ref to each record",
    )
    p.add_argument("--guidance", action="store_true", help="Include heuristic resource guidance block in each successful JSONL record")
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
    p.add_argument("--guidance", action="store_true", help="Include heuristic resource guidance in context artifacts")
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
    )
    print(f"Wrote preflight context JSON to {args.out_json}", file=sys.stderr)
    print(f"Wrote preflight context Markdown to {args.out_md}", file=sys.stderr)
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
    p.add_argument("--preflight-json", default=None, help="Optional preflight context JSON path for linkage/checks")
    p.add_argument("--out-json", required=True, help="Output execution review JSON path")
    p.add_argument("--out-md", required=True, help="Output execution review Markdown path")
    args = p.parse_args(argv)

    write_execution_review(
        counts_json=args.counts_json,
        counts_format=args.counts_format,
        preflight_json=args.preflight_json,
        out_json=args.out_json,
        out_md=args.out_md,
    )
    print(f"Wrote execution review JSON to {args.out_json}", file=sys.stderr)
    print(f"Wrote execution review Markdown to {args.out_md}", file=sys.stderr)
    return 0


def _run_pro_preview_demo_check(*, base_url_override: str | None) -> int:
    try:
        config = resolve_preview_client_config(base_url_override=base_url_override)
    except ValueError as exc:
        print(f"qcoder pro preview: {exc}", file=sys.stderr)
        return 2

    try:
        response = call_builtin_review_demo(config)
    except PreviewClientNetworkError:
        print(
            "qCoder Pro Preview demo: FAIL (network). Base URL may be unreachable.",
            file=sys.stderr,
        )
        print(f"  base_url: {config.base_url}", file=sys.stderr)
        return 2

    if response.status_code == 200:
        print("qCoder Pro Preview demo: PASS (HTTP 200).")
        print(f"  base_url: {config.base_url}")
        for line in summarize_demo_payload(response.payload):
            print(f"  {line}")
        return 0
    if response.status_code == 401:
        print(
            "qCoder Pro Preview demo: FAIL (HTTP 401). Token is missing, invalid, or revoked.",
            file=sys.stderr,
        )
        return 1
    if response.status_code == 403:
        print(
            "qCoder Pro Preview demo: FAIL (HTTP 403). Private/outer service access may be blocking access.",
            file=sys.stderr,
        )
        return 1

    print(f"qCoder Pro Preview demo: FAIL (HTTP {response.status_code}).", file=sys.stderr)
    for line in summarize_demo_payload(response.payload):
        print(f"  {line}", file=sys.stderr)
    return 2


def _cmd_pro(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="qcoder pro",
        add_help=True,
        description=(
            "qCoder Pro Preview shell (service-backed).\n"
            "Confidential Pro analysis is not shipped in this package."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON where available.",
    )
    sub = p.add_subparsers(dest="pro_command")

    p_signup = sub.add_parser("signup", help="Show Pro Preview signup URL.")
    p_signup.set_defaults(pro_command="signup")

    p_status = sub.add_parser("status", help="Show local Pro Preview client status.")
    p_status.set_defaults(pro_command="status")

    p_login = sub.add_parser("login", help="Store Preview token locally (no remote validation in this slice).")
    p_login.add_argument(
        "--token",
        required=True,
        help="QRS-provided Preview token for local config. Treat as private credential.",
    )
    p_login.add_argument("--api-url", required=False, help="Optional service URL override for local config.")
    p_login.set_defaults(pro_command="login")

    p_install = sub.add_parser("install", help="Configure local Pro Preview token (no code download in this slice).")
    p_install.add_argument(
        "--token",
        required=True,
        help="QRS-provided Preview token for local config. Treat as private credential.",
    )
    p_install.add_argument("--api-url", required=False, help="Optional service URL override for local config.")
    p_install.set_defaults(pro_command="install")

    p_validate = sub.add_parser("validate", help="Validate local Pro Preview config and public package boundaries.")
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

    p_preview = sub.add_parser("preview", help="Hosted Preview demo connectivity checks.")
    p_preview_sub = p_preview.add_subparsers(dest="pro_preview_command")

    p_preview_status = p_preview_sub.add_parser(
        "status",
        help="Call hosted Preview demo endpoint and print safe connectivity summary.",
    )
    p_preview_status.add_argument(
        "--base-url",
        default=None,
        help="Override hosted Preview base URL (default env: QCODER_PREVIEW_BASE_URL or QCODER_PRO_API_URL).",
    )
    p_preview_status.set_defaults(pro_command="preview-status")

    p_preview_demo = p_preview_sub.add_parser(
        "demo",
        help="Alias of preview status check; calls /v0/demo/builtin-review.",
    )
    p_preview_demo.add_argument(
        "--base-url",
        default=None,
        help="Override hosted Preview base URL (default env: QCODER_PREVIEW_BASE_URL or QCODER_PRO_API_URL).",
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
            "signup_url": PREVIEW_SIGNUP_URL,
            "service_backed": True,
            "local_only": False,
            "cards_local": False,
            "status": "signup_required",
        }
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("qCoder Pro Preview signup")
            print(f"  url: {PREVIEW_SIGNUP_URL}")
            print("  mode: service-backed")
            print("  note: no confidential Pro analysis is bundled locally")
        return 0

    if cmd == "status":
        payload = _build_pro_bootstrap_payload(status="configured" if resolve_token().present else "not_configured")
        submit_ready = bool(payload["token_present"]) and _is_non_default_service_url(resolve_api_url().value)
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"qCoder Pro status: {payload['status']}.")
            print("  mode: service-backed bootstrap shell")
            print(f"  token: {'present' if payload['token_present'] else 'not set'} ({payload['token_source']})")
            if payload["api_url_source"] == "default":
                print("  submit-ready service URL: not set (default Preview URL is informational)")
            else:
                print("  submit-ready service URL: configured")
            print(f"  service URL source: {payload['api_url_source']}")
            print(f"  pilot submit readiness: {'ready' if submit_ready else 'not ready'}")
            print("  submit requirement: QRS-provided token + non-default service URL")
            print("  service validation: not available in this slice")
            print("  local cards/analysis: disabled in public package")
            print(f"  signup: {PREVIEW_SIGNUP_URL}")
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
            print("Configured qCoder Pro Preview local token settings.")
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
                print("  submit-ready service URL: not set (default Preview URL is informational)")
            else:
                print("  submit-ready service URL: configured")
            print(f"  service URL source: {api_url.source}")
            print(f"  public package boundary checks: {'ok' if payload['public_boundary_ok'] else 'needs attention'}")
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
                "confidential_analysis_performed": workflow_payload.get("confidential_analysis_performed"),
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
                print(f"  confidential_analysis_performed: {payload['confidential_analysis_performed']}")
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
        f"Run `qcoder pro signup` for preview information: {PREVIEW_SIGNUP_URL}",
        file=sys.stderr,
    )
    return 2


def _print_root_help() -> None:
    print(
        "usage: qcoder [--version | -V] [-h] {analyze,batch,context,review,pro} ...\n\n"
        "Quantum circuit analysis CLI.\n\n"
        "positional arguments:\n"
        "  {analyze,batch,context,review,pro}  subcommand\n\n"
        "  analyze          Analyze a QASM file (feature extraction + metadata + run config).\n"
        "  batch            Batch extract a directory to JSONL (requires --out).\n"
        "  context          Build deterministic preflight context artifacts.\n"
        "  review           Build deterministic execution review artifacts from counts.\n"
        "  pro              Service-backed Pro shell (signup/install/status/validate/workflow).\n\n"
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
    if cmd == "pro":
        return _cmd_pro(rest)

    print(
        f"qcoder: unknown subcommand {cmd!r} (expected analyze, batch, context, review, or pro)",
        file=sys.stderr,
    )
    print("Run `qcoder --help` for usage.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
