from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

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


def _runtime_module():
    spec = importlib.util.spec_from_file_location(
        "wi0435_prepared_runtime", SCRIPT_ROOT / "runtime.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    completion = begun["current_step_contract"]["completion"]
    assert completion["artifact_path"] == "phi_plus_bell.py"
    assert completion["artifact_path_form"] == "workspace_relative_bound_target"
    complete_descriptor = binding_tool_descriptors()[1]
    artifact_schema = complete_descriptor["inputSchema"]["properties"]["artifact_path"]
    assert artifact_schema["x-qcoder-path-form"] == "workspace_relative_bound_target"
    assert "absolute paths are not accepted" in artifact_schema["description"]


def test_completion_refuses_unbound_neighbor_path_before_registration(tmp_path: Path) -> None:
    begun = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": REQUEST,
            "intended_artifact_paths": {"source": "phi_plus_bell.py"},
        },
    )
    handle = begun["current_step_contract"]["permitted_native_action"][
        "current_action_handle"
    ]
    neighbor = tmp_path / "neighbor.py"
    neighbor.write_text(SOURCE, encoding="utf-8")
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    rejected = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": neighbor.name},
    )
    assert rejected["ok"] is False
    assert rejected["category"] == "completed_artifact_path_not_bound_target"
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before

    source = tmp_path / "phi_plus_bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": source.name},
    )
    assert completed["ok"] is True
    assert completed["current_step_status"] == "complete_resumable"
    assert completed["artifact"]["role"] == "source"


def test_completion_uses_one_relative_form_and_rejects_absolute_retry(
    tmp_path: Path,
) -> None:
    begun = _call(
        tmp_path,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": REQUEST,
            "intended_artifact_paths": {"source": "phi_plus_bell.py"},
        },
    )
    handle = begun["current_step_contract"]["permitted_native_action"]["current_action_handle"]
    source = tmp_path / "phi_plus_bell.py"
    source.write_text(SOURCE, encoding="utf-8")
    before = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    absolute = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": str(source)},
    )
    assert absolute == {
        "schema_id": "qcoder.current_loop.typed_completion_rejection.v2",
        "ok": False,
        "category": "completion_artifact_path_must_be_bound_workspace_relative",
        "expected_path_form": "workspace_relative_bound_target",
        "copy_from": "current_step_contract.completion.artifact_path",
        "absolute_path_accepted": False,
        "workspace_discovery_permitted": False,
        "state_mutated": False,
        "raw_path_echoed": False,
    }
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == before

    completed = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": "phi_plus_bell.py"},
    )
    assert completed["ok"] is True
    assert completed["current_step_status"] == "complete_resumable"

    completed_state = deepcopy(CurrentLoopCoordinator(workspace_root=tmp_path).store.read())
    duplicate = _call(
        tmp_path,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {"current_action_handle": handle, "artifact_path": "phi_plus_bell.py"},
    )
    assert duplicate["category"] == "current_step_already_completed"
    assert duplicate["duplicate_delivery_noop"] is True
    assert duplicate["canonical_state_mutated"] is False
    assert CurrentLoopCoordinator(workspace_root=tmp_path).store.read() == completed_state


def test_completion_path_escape_traversal_glob_and_symlink_fail_closed(
    tmp_path: Path,
) -> None:
    for invalid in ("../phi_plus_bell.py", "*.py", str(tmp_path.parent / "outside.py")):
        root = tmp_path / str(abs(hash(invalid)))
        root.mkdir()
        begun = _call(
            root,
            BEGIN_CURRENT_LOOP_TOOL_NAME,
            {
                "request_text": REQUEST,
                "intended_artifact_paths": {"source": "phi_plus_bell.py"},
            },
        )
        before = deepcopy(CurrentLoopCoordinator(workspace_root=root).store.read())
        rejected = _call(
            root,
            COMPLETE_CURRENT_STEP_TOOL_NAME,
            {
                "current_action_handle": begun["current_step_contract"][
                    "permitted_native_action"
                ]["current_action_handle"],
                "artifact_path": invalid,
            },
        )
        assert rejected["category"] == (
            "completion_artifact_path_must_be_bound_workspace_relative"
        )
        assert rejected["state_mutated"] is False
        assert CurrentLoopCoordinator(workspace_root=root).store.read() == before

    root = tmp_path / "symlink-case"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "phi_plus_bell.py").write_text(SOURCE, encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    begun = _call(
        root,
        BEGIN_CURRENT_LOOP_TOOL_NAME,
        {
            "request_text": REQUEST,
            "intended_artifact_paths": {"source": "linked/phi_plus_bell.py"},
        },
    )
    before = deepcopy(CurrentLoopCoordinator(workspace_root=root).store.read())
    rejected = _call(
        root,
        COMPLETE_CURRENT_STEP_TOOL_NAME,
        {
            "current_action_handle": begun["current_step_contract"][
                "permitted_native_action"
            ]["current_action_handle"],
            "artifact_path": "linked/phi_plus_bell.py",
        },
    )
    assert rejected["ok"] is False
    assert rejected["category"] == "artifact_candidate_alias_prohibited"
    assert rejected["recovery"]["state_mutated"] is False
    assert CurrentLoopCoordinator(workspace_root=root).store.read() == before


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
    (packet / "helpers").mkdir()
    (packet / "helpers" / "runtime.py").write_bytes((SCRIPT_ROOT / "runtime.py").read_bytes())
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
    assert (workspace / ".qcoder-client-runtime" / "run-sampled-result.py").is_file()
    assert (workspace / "fixtures" / "preexisting_bell.py").is_file()
    assert (workspace / "fixtures" / "bare-counts.json").is_file()
    assert (workspace / "fixtures" / "preexisting-identity.json").is_file()
    rule = workspace / ".cursor" / "rules" / "wi0435-prepared-runtime.mdc"
    assert "Do not install or upgrade dependencies" in rule.read_text(encoding="utf-8")


def test_prepared_runtime_is_pinned_and_missing_or_wrong_runtime_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime_module()
    observed = []

    def version(name: str) -> str:
        observed.append(name)
        return "0.0"

    monkeypatch.setattr(runtime.importlib.metadata, "version", version)
    with pytest.raises(SystemExit, match="version mismatch"):
        runtime._versions()
    assert observed == ["qiskit", "qiskit-aer"]
    setup = (SCRIPT_ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "'qiskit==2.5.2' 'qiskit-aer==0.17.2'" in setup
    assert "preflight --identity" in setup
    assert "--unknown-result" in setup


def test_prepared_runtime_emits_one_sampled_attempt_without_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime_module()
    qasm = tmp_path / "bell.qasm"
    qasm.write_text("OPENQASM 2.0;", encoding="utf-8")
    result = tmp_path / "result.json"
    monkeypatch.setattr(
        runtime,
        "_versions",
        lambda: {"python": "3.12.0", "qiskit": "2.5.2", "qiskit_aer": "0.17.2"},
    )
    monkeypatch.setattr(runtime, "_bell_from_qasm", lambda _path: object())
    samples = []

    def sample(_circuit, *, shots: int):
        samples.append(shots)
        return {"00": shots // 2, "11": shots - shots // 2}, "qiskit_aer.AerSimulator"

    monkeypatch.setattr(runtime, "_sample", sample)
    runtime.run(qasm, result, shots=1_024, attempt_id="native-attempt-one")
    assert samples == [1_024]
    manifest = json.loads(result.read_text(encoding="utf-8"))
    assert manifest["execution_method"]["kind"] == "sampled_shots"
    assert manifest["execution_observation"] == {
        "status": "client_reported_completed",
        "external_execution_attempt_count": 1,
        "dependency_installation_performed": False,
        "environment_mutated": False,
        "qcoder_independently_verified_execution": False,
    }
