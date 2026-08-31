from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from qcoder.context_bridge_mcp import (
    build_client_activation_instructions,
    build_client_binding_descriptor,
)
from qcoder.current_loop_bootstrap import (
    BOOTSTRAP_INVOCATION_SCHEMA_ID,
    CURRENT_LOOP_STATUS_ENTRYPOINT,
    FRESH_ACTIVE_BUILD_ENTRYPOINT,
    INVOCATION_LIFECYCLE_SCHEMA_ID,
    PRE_RESULT_ENTRY_INVENTORY_SCHEMA_ID,
    REQUEST_BASELINE_MAX_UTF8_BYTES,
    bootstrap_contract_snapshot,
    build_fresh_active_build_bootstrap,
    invocation_lifecycle_snapshot,
    pre_result_entry_inventory,
)
from qcoder.current_loop_invocation import invocation_contract_snapshot
from qcoder.current_loop_invocation import operation_transport_inventory


def _run_bootstrap(
    invocation: dict[str, object],
    *,
    workspace: Path,
    request: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1] / "src"
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(source_root) if not existing else os.pathsep.join((str(source_root), existing))
    )
    return subprocess.run(
        [str(item) for item in invocation["qcoder_owned_structured_argv"]],
        cwd=workspace,
        input=request,
        capture_output=True,
        check=False,
        env=environment,
    )


def _descriptor(executable: str = sys.executable) -> dict[str, object]:
    return build_client_binding_descriptor(
        coordinator_prefix=[executable, "-m", "qcoder", "current-loop"],
    )["client_binding_contract"]


def test_pre_result_inventory_is_complete_and_does_not_create_synthetic_entries() -> None:
    inventory = pre_result_entry_inventory(executable="/runtime/python")
    assert inventory["schema_id"] == PRE_RESULT_ENTRY_INVENTORY_SCHEMA_ID
    assert inventory["assistant_constructs_commands_from_inventory"] is False
    assert inventory["new_customer_facing_operation_created"] is False
    assert [entry["entrypoint_id"] for entry in inventory["entries"]] == [
        "available_inactive",
        "bounded_single_capability",
        FRESH_ACTIVE_BUILD_ENTRYPOINT,
        CURRENT_LOOP_STATUS_ENTRYPOINT,
    ]
    inactive, bounded, active, status = inventory["entries"]
    assert inactive["current_loop_invocation"] is None
    assert inactive["action"] == "none"
    assert bounded["current_loop_invocation"] is None
    assert bounded["activates_context_loop"] is False
    assert active["current_loop_invocation"]["operation"] == "activate"
    assert status["current_loop_invocation"]["operation"] == "status"
    assert {entry["entrypoint_id"] for entry in inventory["unsupported_entries"]} == {
        "standalone_review_cli",
        "attach_to_loop",
        "start_next",
        "abandon",
        "direct_post_result_operation",
    }


def test_fresh_active_build_bootstrap_is_exact_local_assist_activation() -> None:
    executable = "/opt/qCoder Runtime/bin/python"
    bootstrap = build_fresh_active_build_bootstrap(executable=executable)
    assert bootstrap["schema_id"] == BOOTSTRAP_INVOCATION_SCHEMA_ID
    assert bootstrap["entrypoint_id"] == FRESH_ACTIVE_BUILD_ENTRYPOINT
    assert bootstrap["qcoder_owned_structured_argv"] == [
        executable,
        "-m",
        "qcoder",
        "current-loop",
        "activate",
        "--request-stdin",
        "--capture-mode",
        "exact_current_customer_message",
        "--approve",
    ]
    assert bootstrap["input_channel"] == {
        "type": "exact_utf8_stdin",
        "customer_value_source": "complete_explicit_active_build_customer_message",
        "assistant_supplies_only": ["exact_original_request_utf8_bytes"],
        "encoding": "utf-8",
        "normalization": "none",
        "maximum_codepoints": 20_000,
        "maximum_utf8_bytes": REQUEST_BASELINE_MAX_UTF8_BYTES,
        "empty_input_permitted": False,
        "interactive_tty_permitted": False,
        "bounded_file_alternative": False,
        "arbitrary_request_text_in_argv": False,
    }
    assert bootstrap["transport_classification"] == "local_only"
    assert bootstrap["hosted_operation_permitted"] is False
    assert bootstrap["hosted_transport_argument_names"] == []
    serialized = json.dumps(bootstrap, sort_keys=True)
    assert "--base-url" not in serialized
    assert "--token-file" not in serialized
    assert "bearer" not in serialized.casefold()
    assert bootstrap["authority_effect"]["stages_content"] is True
    assert bootstrap["authority_effect"]["grants_qcoder_activation"] is True
    assert bootstrap["authority_effect"]["protected_call_permitted"] is False
    assert bootstrap["state_binding"]["revision"] is None
    assert bootstrap["state_binding"]["absence_reason"]
    assert len(bootstrap["contract_digest"]) == 64


def test_bootstrap_owns_platform_serialization_and_cwd_semantics() -> None:
    bootstrap = build_fresh_active_build_bootstrap(
        executable=r"C:\Program Files\qCoder Runtime\python.exe"
    )
    platform = bootstrap["platform_serialization"]
    assert '"C:\\Program Files\\qCoder Runtime\\python.exe"' in platform["windows"]
    assert "'C:\\Program Files\\qCoder Runtime\\python.exe'" in platform["posix"]
    assert platform["assistant_reserializes"] is False
    workspace = bootstrap["working_directory"]
    assert workspace["source"] == "exact_active_ide_or_explicit_customer_selected_workspace"
    assert workspace["transport"] == "client_execution_working_directory"
    assert workspace["argv_contains_workspace"] is False
    assert workspace["assistant_discovers_workspace"] is False
    assert workspace["later_invocations_bound_to_exact_recorded_workspace"] is True


def test_binding_v7_delivers_bootstrap_and_complete_lifecycle() -> None:
    binding = _descriptor("/runtime/python")
    assert binding["schema_version"] == 49
    assert binding["contract_id"] == "qcoder.connected_assistant.client_binding.v50"
    bootstrap = binding["bootstrap_invocation_contract"]
    assert bootstrap["schema_id"] == BOOTSTRAP_INVOCATION_SCHEMA_ID
    assert bootstrap["supported_entrypoints"][FRESH_ACTIVE_BUILD_ENTRYPOINT][
        "qcoder_owned_structured_argv"
    ] == [
        "/runtime/python",
        "-m",
        "qcoder",
        "current-loop",
        "activate",
        "--request-stdin",
        "--capture-mode",
        "exact_current_customer_message",
        "--approve",
    ]
    surface = binding["surfaces"]["local_orchestration"]
    assert surface["command_prefix_diagnostics_only"] is True
    assert surface["assistant_constructs_commands_from_prefix"] is False
    lifecycle = binding["invocation_lifecycle_contract"]
    assert lifecycle["schema_id"] == INVOCATION_LIFECYCLE_SCHEMA_ID
    assert lifecycle["gap_between_bootstrap_and_post_result"] is False
    assert lifecycle["qcoder_owns_complete_invocation_lifecycle"] is True
    assert len(lifecycle["contract_digest"]) == 64


def test_bootstrap_and_lifecycle_digests_are_deterministic() -> None:
    first = bootstrap_contract_snapshot(executable="/runtime/python")
    second = bootstrap_contract_snapshot(executable="/runtime/python")
    assert first == second
    lifecycle = invocation_lifecycle_snapshot(
        executable="/runtime/python",
        post_result_invocation_contract=invocation_contract_snapshot(),
    )
    projection = dict(lifecycle)
    supplied = projection.pop("contract_digest")
    expected = hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert supplied == expected


def test_binding_prohibits_help_and_prefix_command_construction(tmp_path: Path) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://configured.example.invalid",
        token_file=tmp_path / "token.txt",
        python_executable=tmp_path / "runtime with spaces" / "python",
    )
    lowered = instructions.casefold()
    for prohibited in (
        "first execute coordinator_prefix with --help",
        "use the coordinator_prefix argv array exactly as supplied",
        "inspect activate --help",
    ):
        assert prohibited not in lowered
    for required in (
        "begin_current_loop",
        "request_text",
        "never construct a shell, cli, or stdin bootstrap",
        "do not run current-loop --help",
        "coordinator_prefix and both inventories are diagnostics only",
        "never execute coordinator_prefix as an invocation",
    ):
        assert required in lowered


def test_black_box_bootstrap_activates_assist_with_exact_receipt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "Bell workspace Ω"
    workspace.mkdir()
    binding = json.loads(json.dumps(_descriptor()))
    bootstrap = binding["bootstrap_invocation_contract"]["supported_entrypoints"][
        FRESH_ACTIVE_BUILD_ENTRYPOINT
    ]
    request = (
        "Use qCoder for this build. Create and run a simple Bell Qiskit program.\n"
        "Keep `00` and `11`; literal $(printf no), quotes ' \" and Ω 😀."
    ).encode("utf-8")
    completed = _run_bootstrap(bootstrap, workspace=workspace, request=request)
    assert completed.returncode == 0, completed.stderr.decode()
    result = json.loads(completed.stdout)
    display = result["details"]
    exact = request.decode("utf-8")
    assert result["request_identity"]["exact_original_message"] == exact
    assert (
        result["request_identity"]["original_message_utf8_sha256"]
        == hashlib.sha256(request).hexdigest()
    )
    assert "original_request" not in display
    assert "exact_original_message" not in result["current_request_semantics"]
    assert display["assist_ready"] is True
    assert display["request_baseline_saved"] is True
    assert display["posture_deferred"] is False
    assert display["generation_governance"] == "adaptive"
    assert display["activation_receipt"]["preset"] == "assist"
    assert result["current_request_semantics"]["requested_operation"] == (
        "source_and_local_execution"
    )
    assert "operation_specific_invocation" not in result["compact_next_action"]
    assert result["current_step_contract"]["completion"]["operation"] == ("complete_current_step")
    assert "next_invocation" not in result


def test_duplicate_exact_message_bootstrap_fails_without_duplicate_activation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bootstrap = build_fresh_active_build_bootstrap(executable=sys.executable)
    request = b"Use qCoder for this build. Create a Bell Qiskit program."
    first = json.loads(_run_bootstrap(bootstrap, workspace=workspace, request=request).stdout)
    second = json.loads(_run_bootstrap(bootstrap, workspace=workspace, request=request).stdout)
    assert first["ok"] is True
    assert first["details"]["assist_ready"] is True
    assert second["ok"] is False
    assert second["category"] == "loop_already_active"
    assert second["details"]["recovery_contract"]["hosted_operation_permitted"] is False


def test_invalid_utf8_bootstrap_fails_with_safe_machine_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bootstrap = build_fresh_active_build_bootstrap(executable=sys.executable)
    completed = _run_bootstrap(bootstrap, workspace=workspace, request=b"\xff\xfe")
    assert completed.returncode == 2
    result = json.loads(completed.stdout)
    assert result["schema_id"] == "qcoder.current_loop.bootstrap_rejection.v1"
    assert result["error_category"] == "request_input_invalid_utf8"
    assert result["assistant_should_stop"] is True
    assert result["hosted_operation_permitted"] is False
    assert result["raw_request_content_included"] is False
    assert result["token_contents_included"] is False
    assert not (workspace / ".qcoder").exists()


def test_empty_and_oversized_bootstrap_inputs_fail_before_state(tmp_path: Path) -> None:
    bootstrap = build_fresh_active_build_bootstrap(executable=sys.executable)
    for name, request, category in (
        ("empty", b"", "request_input_empty"),
        (
            "oversized",
            b"x" * (REQUEST_BASELINE_MAX_UTF8_BYTES + 1),
            "request_baseline_original_request_too_large",
        ),
    ):
        workspace = tmp_path / name
        workspace.mkdir()
        completed = _run_bootstrap(bootstrap, workspace=workspace, request=request)
        assert completed.returncode == 2
        result = json.loads(completed.stdout)
        assert result["schema_id"] == "qcoder.current_loop.bootstrap_rejection.v1"
        assert result["error_category"] == category
        assert result["hosted_operation_permitted"] is False
        assert result["fresh_customer_input_required"] is True
        assert not (workspace / ".qcoder").exists()


def test_bootstrap_and_post_result_operation_names_and_transport_agree() -> None:
    inventory = operation_transport_inventory()
    by_operation = {
        row["operation"]: row
        for row in inventory["operations"]
        if row["operation"] in {"activate", "status"}
    }
    bootstrap = bootstrap_contract_snapshot(executable="/runtime/python")
    for entrypoint in (
        FRESH_ACTIVE_BUILD_ENTRYPOINT,
        CURRENT_LOOP_STATUS_ENTRYPOINT,
    ):
        entry = bootstrap["supported_entrypoints"][entrypoint]
        row = by_operation[entry["operation"]]
        assert entry["subcommand"] == row["subcommand"]
        assert entry["transport_classification"] == row["transport"] == "local_only"
        assert entry["hosted_operation_permitted"] is False


def test_status_bootstrap_is_local_non_authoritative_and_creates_no_state(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    status = _descriptor()["bootstrap_invocation_contract"]["supported_entrypoints"][
        CURRENT_LOOP_STATUS_ENTRYPOINT
    ]
    completed = _run_bootstrap(status, workspace=workspace)
    assert completed.returncode == 2
    result = json.loads(completed.stdout)
    assert result["operation"] == "status"
    assert result["category"] == "loop_not_activated"
    assert result["next_invocation"] is None
    assert result["no_action_disposition"]["assistant_should_stop"] is True
    assert status["transport_classification"] == "local_only"
    assert status["authority_effect"]["grants_any_workflow_authority"] is False
    assert not (workspace / ".qcoder").exists()
