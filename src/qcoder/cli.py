from __future__ import annotations

import argparse
import json
import sys

from qcoder.pipelines.analyze import analyze_qasm
from qcoder.pipelines.context import write_preflight_context
from qcoder.pipelines.review import write_execution_review
from qcoder.tools.batch import analyze_qasm_dir_to_jsonl

PREVIEW_SIGNUP_URL = "https://qcoder.ai/preview"


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

    p_login = sub.add_parser("login", help="Store Preview token (service validation not available in this slice).")
    p_login.add_argument("--token", required=False, help="Preview token (optional in this stub).")
    p_login.set_defaults(pro_command="login")

    p_workflow = sub.add_parser("workflow", help="Submit a Pro workflow to the hosted service (not yet available).")
    p_workflow.add_argument("--qasm", default=None, help="Path to a single QASM file.")
    p_workflow.add_argument("--before-qasm", default=None, help="Path to before QASM file.")
    p_workflow.add_argument("--after-qasm", default=None, help="Path to after QASM file.")
    p_workflow.add_argument("--project-dir", default=None, help="Local project directory.")
    p_workflow.set_defaults(pro_command="workflow")

    args, _unknown = p.parse_known_args(argv)
    cmd = args.pro_command

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
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("qCoder Pro Preview signup")
            print(f"  url: {PREVIEW_SIGNUP_URL}")
            print("  mode: service-backed")
            print("  note: no confidential Pro analysis is bundled locally")
        return 0

    if cmd == "status":
        payload = {
            "schema_id": "qcoder.pro_preview_shell.v0",
            "service_backed": True,
            "configured": False,
            "status": "not_configured",
            "cards_local": False,
            "upload_on_explicit_pro_command_only": True,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("qCoder Pro status: not configured.")
            print("  mode: service-backed preview shell")
            print("  local cards/analysis: disabled in public package")
            print(f"  signup: {PREVIEW_SIGNUP_URL}")
        return 0

    print(
        "qcoder pro: hosted Pro Preview service is not configured in this build.\n"
        f"Run `qcoder pro signup` for access details: {PREVIEW_SIGNUP_URL}",
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
        "  pro              Service-backed Pro Preview shell (signup/status/workflow stub).\n\n"
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
