from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import importlib.metadata


PUBLIC_SERVER = "wi0435-qcoder-context-bridge"
PRIVATE_SERVER = "wi0435-qcoder-current-loop"
PREEXISTING_SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def packet_identity(packet: Path) -> dict:
    value = json.loads((packet / "PACKET-MANIFEST.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("Packet manifest is invalid.")
    return value


def wheel_identity(packet: Path) -> tuple[Path, dict]:
    manifest = packet_identity(packet)
    value = manifest.get("wheel")
    if not isinstance(value, dict) or not isinstance(value.get("filename"), str):
        raise SystemExit("Packet wheel identity is missing.")
    return packet / "artifacts" / value["filename"], value


def check_global_cursor_configuration() -> None:
    path = Path.home() / ".cursor" / "mcp.json"
    if not path.exists():
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("Cannot safely validate the existing User MCP configuration.") from exc
    servers = value.get("mcpServers", {}) if isinstance(value, dict) else {}
    if not isinstance(servers, dict):
        raise SystemExit("The existing User MCP server collection is not a JSON object.")
    conflicts = [
        str(name)
        for name, descriptor in servers.items()
        if "qcoder" in str(name).casefold()
        or "qcoder" in json.dumps(descriptor, sort_keys=True).casefold()
    ]
    if conflicts:
        raise SystemExit(
            "User-scope qCoder MCP configuration must be disabled before this checkpoint; "
            f"conflicting server names: {', '.join(sorted(conflicts))}. Preserve it for restoration."
        )


def preflight(packet: Path, workspace: Path, token_file: Path) -> None:
    wheel, identity = wheel_identity(packet)
    if workspace.exists():
        raise SystemExit(f"Fresh workspace required; path already exists: {workspace}")
    if not token_file.is_file():
        raise SystemExit("The supplied Context Bridge token-file path is not a regular file.")
    if (
        not wheel.is_file()
        or wheel.stat().st_size != identity.get("bytes")
        or digest(wheel) != identity.get("sha256")
    ):
        raise SystemExit("Exact rehearsal wheel identity check failed.")
    check_global_cursor_configuration()
    print("PREPARE_PREFLIGHT_PASS")


def configure(packet: Path, workspace: Path, token_file: Path, python: Path) -> None:
    if not python.is_file():
        raise SystemExit("Installed-wheel Python is missing.")
    # Preserve the venv launcher path exactly. Resolving its symlink would bypass
    # the venv and select the base interpreter where qCoder is not installed.
    runtime_python = Path(os.path.abspath(python))
    cursor_dir = workspace / ".cursor"
    fixtures = workspace / "fixtures"
    safe_return = workspace / "safe-return"
    client_runtime = workspace / ".qcoder-client-runtime"
    cursor_dir.mkdir(parents=True, exist_ok=False)
    fixtures.mkdir()
    safe_return.mkdir()
    client_runtime.mkdir()
    runtime_source = packet / "helpers" / "runtime.py"
    if not runtime_source.is_file():
        raise SystemExit("Prepared external execution runtime helper is missing.")
    runtime_target = client_runtime / "run-sampled-result.py"
    runtime_target.write_bytes(runtime_source.read_bytes())
    os.chmod(runtime_target, stat.S_IRUSR | stat.S_IXUSR)
    mcp = {
        "mcpServers": {
            PUBLIC_SERVER: {
                "command": str(runtime_python),
                "args": [
                    "-m",
                    "qcoder",
                    "context-bridge",
                    "mcp",
                    "serve",
                    "--token-file",
                    str(token_file.resolve()),
                ],
            },
            PRIVATE_SERVER: {
                "command": str(runtime_python),
                "args": [
                    "-m",
                    "qcoder",
                    "current-loop",
                    "--workspace",
                    str(workspace.resolve()),
                    "serve-binding-mcp",
                ],
            },
        }
    }
    mcp_path = cursor_dir / "mcp.json"
    mcp_path.write_bytes(canonical_bytes(mcp) + b"\n")
    os.chmod(mcp_path, stat.S_IRUSR | stat.S_IWUSR)
    rules_dir = cursor_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "wi0435-prepared-runtime.mdc").write_text(
        "---\nalwaysApply: true\n---\n"
        "For a qCoder external result step, use only the already prepared workspace "
        "runtime at .venv/bin/python with .qcoder-client-runtime/run-sampled-result.py. "
        "Do not install or upgrade dependencies, mutate the environment, substitute analytic "
        "probabilities or constructed counts for sampled shots, or perform more than the one "
        "requested execution attempt. If that runtime is unavailable, report a blocker.\n",
        encoding="utf-8",
    )
    source = fixtures / "preexisting_bell.py"
    source.write_text(PREEXISTING_SOURCE, encoding="utf-8")
    bare = fixtures / "bare-counts.json"
    bare.write_text(json.dumps({"00": 512, "11": 512}, sort_keys=True) + "\n", encoding="utf-8")
    fixture_state = source.stat()
    fixture_identity = {
        "schema_id": "qcoder.wi0435.preexisting_fixture_identity.v1",
        "relative_path": "fixtures/preexisting_bell.py",
        "bytes": fixture_state.st_size,
        "sha256": digest(source),
        "mtime_ns": fixture_state.st_mtime_ns,
        "mode": stat.S_IMODE(fixture_state.st_mode),
    }
    identity_path = fixtures / "preexisting-identity.json"
    identity_path.write_bytes(canonical_bytes(fixture_identity) + b"\n")
    os.chmod(identity_path, stat.S_IRUSR | stat.S_IWUSR)
    print(f"WORKSPACE={workspace}")
    print(f"RUNTIME_PYTHON={runtime_python}")
    print(f"CURSOR_MCP_SERVERS={PUBLIC_SERVER},{PRIVATE_SERVER}")
    print("PUBLIC_TOOL_EXPECTATION=12")
    print("PRIVATE_OPERATION_EXPECTATION=2")
    print("CONFIGURE_PASS")


def installed_check(packet: Path, workspace: Path) -> None:
    manifest = packet_identity(packet)
    import qcoder
    from qcoder.context_bridge_mcp import EXPECTED_TOOLS
    from qcoder.current_loop_binding_mcp import binding_tool_descriptors

    if importlib.metadata.version("qiskit") != "2.5.2":
        raise SystemExit("Prepared Qiskit version mismatch.")
    if importlib.metadata.version("qiskit-aer") != "0.17.2":
        raise SystemExit("Prepared Qiskit Aer version mismatch.")

    if qcoder.__version__ != manifest.get("version"):
        raise SystemExit("Installed qCoder version mismatch.")
    if len(EXPECTED_TOOLS) != 12:
        raise SystemExit("Public Context Bridge inventory mismatch.")
    if [item["name"] for item in binding_tool_descriptors()] != [
        "begin_current_loop",
        "complete_current_step",
    ]:
        raise SystemExit("Private Current Loop inventory mismatch.")
    runtime_identity = workspace / ".qcoder-client-runtime" / "runtime-identity.json"
    if not runtime_identity.is_file():
        raise SystemExit("Prepared external execution runtime preflight identity is missing.")
    runtime = json.loads(runtime_identity.read_text(encoding="utf-8"))
    if runtime.get("preflight", {}).get("status") != "pass":
        raise SystemExit("Prepared external execution runtime preflight failed.")
    unknown_fixture = workspace / "fixtures" / "unknown-result-manifest.json"
    if not unknown_fixture.is_file():
        raise SystemExit("Prepared sampled unknown-lineage fixture is missing.")
    print("INSTALLED_IDENTITY_AND_INVENTORY_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["preflight", "configure", "installed-check", "wheel-name"])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--python", type=Path)
    args = parser.parse_args()
    packet = args.packet.absolute()
    if args.mode == "wheel-name":
        print(wheel_identity(packet)[1]["filename"])
        return
    if args.mode == "installed-check":
        if args.workspace is None:
            parser.error("--workspace is required for installed-check")
        installed_check(packet, args.workspace.absolute())
        return
    if args.workspace is None or args.token_file is None:
        parser.error("--workspace and --token-file are required")
    workspace = args.workspace.absolute()
    if args.mode == "preflight":
        preflight(packet, workspace, args.token_file)
        return
    if args.python is None:
        parser.error("--python is required for configure")
    configure(packet, workspace, args.token_file, args.python.absolute())


if __name__ == "__main__":
    main()
