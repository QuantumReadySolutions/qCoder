from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from qcoder.current_loop_binding_mcp import (
    BEGIN_CURRENT_LOOP_TOOL_NAME,
    COMPLETE_CURRENT_STEP_TOOL_NAME,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


REQUEST = (
    "Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. "
    "Stop after generating the code."
)
SOURCE = (
    "from qiskit import QuantumCircuit\n"
    "circuit = QuantumCircuit(2)\n"
    "circuit.h(0)\n"
    "circuit.cx(0, 1)\n"
)
SCRIPT_ROOT = Path(__file__).parents[1] / "scripts" / "wi0435-natural-cursor-checkpoint"


def _call(root: Path, name: str, arguments: dict) -> dict:
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        workspace_root=root,
    )
    assert response is not None
    return response["result"]["structuredContent"]


def test_source_begin_binds_exact_target_and_prohibits_discovery(tmp_path: Path) -> None:
    missing = _call(tmp_path, BEGIN_CURRENT_LOOP_TOOL_NAME, {"request_text": REQUEST})
    assert missing["ok"] is False
    assert missing["category"] == "exact_intended_artifact_targets_required"
    assert missing["state_mutated"] is False
    assert missing["workspace_discovery_permitted"] is False
    assert not (tmp_path / ".qcoder").exists()

    glob = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {"request_text": REQUEST, "intended_artifact_paths": {"source": "*.py"}},
    )
    assert glob["ok"] is False
    assert glob["category"] == "intended_artifact_path_discovery_expression_prohibited"
    assert not (tmp_path / ".qcoder").exists()

    begun = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": REQUEST,
            "intended_artifact_paths": {"source": "phi_plus_bell.py"},
        },
    )
    assert begun["ok"] is True
    target = begun["current_step_contract"]["permitted_native_action"]["exact_artifact_target"]
    assert target == {
        "workspace_relative_path": "phi_plus_bell.py",
        "selection": "bound_before_action_no_discovery",
    }
    descriptor = binding_tool_descriptors()[0]
    assert "intended_artifact_paths" in descriptor["inputSchema"]["properties"]
    assert descriptor["x-qcoder-artifact-target-contract"]["discovery_or_glob_permitted"] is False


def test_completion_refuses_unbound_neighbor_path_before_registration(tmp_path: Path) -> None:
    begun = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": REQUEST,
            "intended_artifact_paths": {"source": "phi_plus_bell.py"},
        },
    )
    handle = begun["current_step_contract"]["permitted_native_action"]["current_action_handle"]
    neighbor = tmp_path / "neighbor.py"
    neighbor.write_text(SOURCE, encoding="utf-8")
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    rejected = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": str(neighbor)},
    )
    assert rejected["ok"] is False
    assert rejected["category"] == "completed_artifact_path_not_bound_target"
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before

    source = tmp_path / "phi_plus_bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": str(source)},
    )
    assert completed["ok"] is True
    assert completed["current_step_status"] == "complete_resumable"
    assert completed["artifact"]["role"] == "source"


def test_checkpoint_selects_supported_python_and_preserves_venv_launcher(
    tmp_path: Path,
) -> None:
    setup = SCRIPT_ROOT / "setup.sh"
    prepare = SCRIPT_ROOT / "prepare.py"
    subprocess.run(["bash", "-n", str(setup)], check=True)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    old = fake_bin / "python3"
    old.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    supported = fake_bin / "python3.12"
    supported.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(old, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    os.chmod(supported, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    selected = subprocess.run(
        ["bash", str(setup), "--select-python-only"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert selected.stdout.strip() == str(supported)
    assert '"$bootstrap_python" -m venv' in setup.read_text(encoding="utf-8")
    assert "python3 -m venv" not in setup.read_text(encoding="utf-8")

    packet = tmp_path / "packet"
    packet.mkdir()
    workspace = tmp_path / "workspace"
    launcher_dir = workspace / ".venv" / "bin"
    launcher_dir.mkdir(parents=True)
    launcher = launcher_dir / "python"
    launcher.symlink_to(Path(sys.executable).resolve())
    token = tmp_path / "token"
    token.write_text("not-read-by-configure", encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(prepare),
            "configure",
            "--packet",
            str(packet),
            "--workspace",
            str(workspace),
            "--token-file",
            str(token),
            "--python",
            str(launcher),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    mcp = json.loads((workspace / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    commands = {value["command"] for value in mcp["mcpServers"].values()}
    assert commands == {str(launcher.absolute())}
    assert str(Path(sys.executable).resolve()) not in commands
