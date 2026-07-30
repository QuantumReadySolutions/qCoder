from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import urllib.error
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qcoder import __version__
from qcoder.cli import main
from qcoder.algorithm_blueprint import ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS
from qcoder.blueprint_decisions import (
    build_decision_records,
    pack_decision_record_set,
    with_consistency_digest,
)
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
    build_client_activation_instructions,
    build_client_binding_descriptor,
    handle_jsonrpc_message,
    post_context_bridge,
    run_smoke,
    tool_descriptors,
    validate_token_file,
)
from qcoder.context_loop import (
    build_carry_forward_proposal,
    build_portable_current_build_context,
    canonical_context_bridge_request_sha256,
    canonical_portable_current_build_context_json,
)
import qcoder.context_bridge_mcp as context_bridge_mcp


class _FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            self.payload
            or {
                "ok": True,
                "tool_name": "get_guided_evidence_context",
                "context_status": "assistant_context_ready",
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        ).encode("utf-8")


def _write_token(path: Path, text: str = "ctxbridge-token-not-printed") -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _activation_runtime(instructions: str) -> dict[str, object]:
    marker = (
        "Configured qCoder runtime (JSON values are exact operational metadata; "
        "coordinator_prefix is diagnostics-only metadata):\n"
    )
    serialized = instructions.split(marker, 1)[1]
    runtime, _ = json.JSONDecoder().raw_decode(serialized)
    assert isinstance(runtime, dict)
    return runtime


def _client_binding_descriptor(instructions: str) -> dict[str, object]:
    marker = (
        "Connected-assistant client binding (JSON values are the versioned routing descriptor):\n"
    )
    serialized = instructions.split(marker, 1)[1]
    descriptor, _ = json.JSONDecoder().raw_decode(serialized)
    assert isinstance(descriptor, dict)
    return descriptor


def test_context_bridge_root_help_includes_command() -> None:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(["--help"])
    assert rc == 0
    assert "context-bridge" in out.getvalue()


def test_context_bridge_help_includes_mcp_serve_and_smoke() -> None:
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            rc = main(["context-bridge", "mcp", "--help"])
        except SystemExit as exc:
            rc = int(exc.code)
    assert rc == 0
    text = out.getvalue()
    assert "serve" in text
    assert "smoke" in text


def test_tool_descriptors_are_exact_public_context_bridge_tools() -> None:
    names = [tool["name"] for tool in tool_descriptors()]
    assert names == [
        "get_guided_evidence_context",
        "create_prompt_context",
        "create_evidence_context_pack",
        "create_context_session_card",
        "create_run_readiness_card",
        "create_result_review_context_card",
        "create_next_check_plan",
        "create_single_loop_evidence_diff",
        "create_algorithm_intent_card",
        "create_implementation_blueprint",
        "create_generation_context_pack",
        "create_source_blueprint_alignment_review",
    ]
    assert names == list(EXPECTED_TOOLS)
    assert "suggest_next_checks" not in names
    assert "apply_repo_edit" not in names
    result_review = next(
        tool for tool in tool_descriptors() if tool["name"] == "create_result_review_context_card"
    )
    assert "user-provided result evidence" in result_review["description"]
    next_check = next(
        tool for tool in tool_descriptors() if tool["name"] == "create_next_check_plan"
    )
    assert "current-request evidence" in next_check["description"]
    diff = next(
        tool for tool in tool_descriptors() if tool["name"] == "create_single_loop_evidence_diff"
    )
    assert "without history or lookup" in diff["description"]
    assert "preserve salient user-provided result observations" in diff["description"]
    assert "result_evidence" in diff["inputSchema"]["properties"]["after"]["properties"]
    assert (
        "Preserve salient user-provided observations"
        in diff["inputSchema"]["properties"]["before"]["description"]
    )
    assert (
        "generic 'result evidence is present'"
        in diff["inputSchema"]["properties"]["after"]["description"]
    )
    blueprint = next(
        tool for tool in tool_descriptors() if tool["name"] == "create_implementation_blueprint"
    )
    assert "allOf" not in blueprint["inputSchema"]
    parent_schema = blueprint["inputSchema"]["properties"]["evidence_parent_artifacts"]
    assert parent_schema["minItems"] == 1
    assert "no lookup occurs" in parent_schema["description"]
    assert "inherited exactly" in blueprint["description"]


def test_initialize_supplies_exact_runtime_without_reading_token_or_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token_dir = tmp_path / "token folder"
    token_dir.mkdir()
    token_file = token_dir / "context bridge token.txt"
    token_secret = "token-secret-must-never-appear"
    _write_token(token_file, token_secret)
    environment_secrets = {
        "QCODER_ACCOUNT_IDENTIFIER": "account-identifier-must-never-appear",
        "QCODER_ADMIN_CREDENTIAL": "admin-credential-must-never-appear",
        "QCODER_CONTEXT_BRIDGE_TOKEN": "environment-token-must-never-appear",
    }
    for name, value in environment_secrets.items():
        monkeypatch.setenv(name, value)
    base_url = "https://configured-runtime.example.invalid"

    initialized = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        base_url=base_url,
        token_file=token_file,
    )

    assert initialized is not None
    instructions = initialized["result"]["instructions"]
    runtime = _activation_runtime(instructions)
    descriptor = _client_binding_descriptor(instructions)
    executable = str(Path(sys.executable).absolute())
    token_path = str(token_file.resolve())
    assert runtime == {
        "python_executable": executable,
        "qcoder_version": __version__,
        "coordinator_prefix": [
            executable,
            "-m",
            "qcoder",
            "current-loop",
        ],
        "coordinator_prefix_diagnostics_only": True,
        "base_url": base_url,
        "token_file_path": token_path,
        "hosted_runtime_configuration": {
            "binding": "qcoder_owned_operation_specific_invocation_only",
            "base_url": base_url,
            "token_file_path": token_path,
            "globally_composable_transport_arguments": False,
            "assistant_routes_transport": False,
        },
    }
    normalized_instructions = " ".join(instructions.split())
    for required in (
        "explicitly asks to use qCoder",
        "Never activate silently",
        "Use the supplied python_executable only through qCoder's exact bootstrap",
        "Never run `which` or `where`",
        "inspect PATH or environment variables",
        "Never inspect Cursor, Claude Code, or Codex configuration",
        "Never list, browse, or inspect the executable path's parent directories",
        "Never open, read, print, copy, hash, or validate the token-file contents",
        "authorize only invoking the declared qCoder runtime",
        "grant no general access outside the active workspace",
        "Do not run current-loop --help",
        "Stop on authentication, entitlement, or hosted-service failure",
        "Never manually sequence Context Bridge tools",
        "never substitute a local or manual review fallback",
        "Conversational approval and canonical confirmation are distinct",
        "required_authority_input",
        "Follow supported_next_action and next_invocation exactly",
        "Never repeat an identical invocation after an unchanged checkpoint",
        "awaiting_confirmation_fields",
        "IDE WORK AND ARTIFACT HANDOFF",
        "Retain exact paths returned by your own write or modify operations",
        "truthful created, modified, or selected event disposition",
        "Never inspect .qcoder",
        "exclude .qcoder from every ordinary project inspection",
        "Do not use a glob, find, directory listing, Git status, repository map, or search result",
        "Ordinary inspection of relevant non-qCoder project files",
        "does not register a file or authorize qCoder review",
        "supported exact outputs attributable to a single-use operation receipt",
        "Never enumerate, list, search, open, read, copy, hash, parse, inspect, summarize, or reverse-engineer .qcoder",
        "home-directory qCoder state",
        "sibling repositories",
        "Do not replace coordinator truth with a locally assembled review",
        "Workspace freshness is not intent",
        "adaptive or Blueprint-required governance",
        "Preserve exact user-stated decision answers",
        "is not a full Generation Context Pack",
        "decision_resolution checkpoint",
        "exact decision-disposition authority channel",
        "do not ask a routine posture question",
        "immediate narrowing and explicit broadening confirmation",
        "QUIET EVERYDAY ASSIST",
        "customer_interaction envelope",
        "Hosted enrichment and Build Review are on request",
        "non-null permitted_input_source",
        "machine-readable no_action_disposition",
        "inspect proof records",
        "qCoder activation, IDE write/run permission, exact artifact-review permission",
        "does not grant IDE permission to write or run",
        "does not authorize artifact review",
    ):
        assert required in normalized_instructions
    assert token_secret not in instructions
    for value in environment_secrets.values():
        assert value not in instructions
    assert descriptor["client_binding_contract"]["package_version"] == __version__
    serialized_descriptor = json.dumps(descriptor, sort_keys=True)
    assert token_secret not in serialized_descriptor
    for value in environment_secrets.values():
        assert value not in serialized_descriptor


def test_initialize_binds_two_surfaces_and_three_workstyles_without_new_tool(
    tmp_path: Path,
) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://configured.example.invalid",
        token_file=tmp_path / "token.txt",
        python_executable=tmp_path / "runtime" / "python",
    )
    normalized = " ".join(instructions.split())
    for required in (
        "QCODER ASSISTANT SURFACES",
        "exactly twelve Context Bridge MCP tools",
        "bounded hosted capability and evidence surface",
        "separate supported local orchestration and continuity surface",
        "intentionally not one of the twelve MCP tools",
        "WORKSTYLE ROUTING",
        "Available but inactive",
        "Single capability",
        "Active build",
        "ACTIVE-BUILD LOCAL EXECUTION",
        "ordinary local command-execution capability",
        "fresh_active_build_request_baseline_staging",
        "client_execution_working_directory",
        "exact UTF-8 stdin",
        "Do not inspect help",
        "construct a command from coordinator_prefix",
        "supported qCoder active-build route",
        "not a local fallback",
        "customer-authored CLI choreography",
        "The customer never types the command",
        "explicit wording equivalent to “Use qCoder for this build.”",
        "local coordinator first",
        "never invent a hosted-tool order",
        "does not prohibit legitimate direct use of one applicable MCP tool",
        "Do not call one of the twelve domain tools in place of local coordinator activation",
        "Never embed arbitrary user-approved free text in shell argv",
        "approval only",
        "next_loop_ready",
        "governing-change branch is closed",
        "non-null permitted_input_source",
        "bounded input semantics",
        "machine-readable no_action_disposition",
    ):
        assert required in normalized
    assert len(tool_descriptors()) == 12
    assert "qcoder current-loop" not in [tool["name"] for tool in tool_descriptors()]


def test_client_binding_descriptor_is_exact_deterministic_and_secret_free() -> None:
    prefix = ["/opt/qCoder Runtime/bin/python", "-m", "qcoder", "current-loop"]
    first = build_client_binding_descriptor(coordinator_prefix=prefix)
    second = build_client_binding_descriptor(coordinator_prefix=prefix)
    assert first == second
    serialized = json.dumps(first, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    assert (
        hashlib.sha256(serialized.encode()).hexdigest()
        == hashlib.sha256(
            json.dumps(second, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )

    binding = first["client_binding_contract"]
    assert binding["schema_id"] == CLIENT_BINDING_SCHEMA_ID
    assert binding["schema_version"] == CLIENT_BINDING_SCHEMA_VERSION
    assert binding["contract_id"] == CLIENT_BINDING_CONTRACT_ID
    assert binding["package_version"] == __version__
    assert len(binding["coordinator_contract_digest"]) == 64
    assert binding["operation_invocation_contract"]["global_transport_argument_array"] is False
    assert binding["operation_invocation_contract"]["assistant_routes_transport"] is False
    assert binding["operation_transport_inventory"]["diagnostics_only"] is True
    assert binding["bootstrap_invocation_contract"]["schema_id"] == (
        "qcoder.current_loop.bootstrap_invocation.v2"
    )
    assert binding["pre_result_entry_inventory"]["schema_id"] == (
        "qcoder.current_loop.pre_result_entry_inventory.v1"
    )
    assert binding["invocation_lifecycle_contract"]["schema_id"] == (
        "qcoder.current_loop.invocation_lifecycle.v1"
    )
    assert (
        binding["invocation_lifecycle_contract"]["gap_between_bootstrap_and_post_result"] is False
    )
    assert binding["checkpoint_input_contract"] == {
        "schema_id": "qcoder.current_loop.checkpoint_input.v3",
        "schema_version": 3,
        "construction_schema_id": ("qcoder.current_loop.checkpoint_input_construction.v2"),
        "construction_schema_version": 2,
        "semantic_field_schema_id": (
            "qcoder.current_loop.checkpoint_input_semantic_field_contract.v1"
        ),
        "semantic_field_schema_version": 1,
        "transports": ["stdin", "file"],
        "approval_only_promotion": True,
        "literal_free_text_in_argv": False,
        "qcoder_owns_fixed_construction_metadata": True,
        "assistant_supplies_only_declared_new_values": True,
        "field_shapes_and_bounded_domains_client_visible": True,
        "successful_staging_guarantees_semantic_promotion_compatibility": True,
    }
    assert binding["qcoder_domain_tool_count"] == 12
    assert binding["supported_workstyles"] == [
        "available_inactive",
        "single_capability",
        "active_build",
    ]
    assert binding["required_client_capability"] == "ordinary_local_command_execution"
    assert binding["surfaces"] == {
        "hosted_capability": {
            "transport": "mcp_tools",
            "tool_count": 12,
            "single_capability_supported": True,
        },
        "local_orchestration": {
            "transport": "local_command",
            "command_prefix": prefix,
            "command_prefix_diagnostics_only": True,
            "assistant_constructs_commands_from_prefix": False,
            "orchestration_surface_is_not_an_mcp_tool": True,
            "customer_never_types_command": True,
        },
    }
    assert binding["workstyle_routes"]["available_inactive"] == {
        "trigger": "no_explicit_qcoder_request",
        "action": "none",
    }
    assert binding["workstyle_routes"]["single_capability"] == {
        "trigger": "explicit_bounded_capability_request",
        "action": "use_applicable_mcp_tool",
        "activates_context_loop": False,
    }
    assert binding["workstyle_routes"]["active_build"] == {
        "trigger": "explicit_use_qcoder_for_this_build_or_accepted_offer",
        "action": "execute_fresh_active_build_bootstrap_invocation",
        "then": "follow_coordinator_directed_local_and_hosted_actions",
    }
    assert binding["manual_active_build_tool_sequencing_prohibited"] is True
    for prohibited_value in (
        "secret-token-value",
        "customer@example.invalid",
        "account-private-identifier",
        "administrator-secret",
    ):
        assert prohibited_value not in serialized
    assert '"token_contents_embedded":false' in serialized
    assert '"credential_bearing_metadata_embedded":false' in serialized


def test_client_binding_descriptor_supports_posix_windows_and_space_paths() -> None:
    paths = (
        "/opt/qCoder Runtime/bin/python",
        r"C:\Program Files\qCoder Runtime\python.exe",
    )
    for executable in paths:
        descriptor = build_client_binding_descriptor(
            coordinator_prefix=[executable, "-m", "qcoder", "current-loop"],
        )
        prefix = descriptor["client_binding_contract"]["surfaces"]["local_orchestration"][
            "command_prefix"
        ]
        assert prefix == [executable, "-m", "qcoder", "current-loop"]
        round_tripped = json.loads(json.dumps(descriptor))
        assert (
            round_tripped["client_binding_contract"]["surfaces"]["local_orchestration"][
                "command_prefix"
            ]
            == prefix
        )


def test_positive_local_execution_guidance_precedes_and_is_outside_prohibitions(
    tmp_path: Path,
) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://configured.example.invalid",
        token_file=tmp_path / "token.txt",
    )
    headings = [
        "QCODER ASSISTANT SURFACES",
        "WORKSTYLE ROUTING",
        "ACTIVE-BUILD LOCAL EXECUTION",
        "REQUEST FIDELITY",
        "ACTIVATION PROTOCOL",
        "CHECKPOINT PROTOCOL",
        "IDE WORK AND ARTIFACT HANDOFF",
        "CONFIGURED RUNTIME",
        "AUTHORITY BOUNDARIES",
        "PROHIBITED ACTIONS",
    ]
    assert [instructions.index(heading) for heading in headings] == sorted(
        instructions.index(heading) for heading in headings
    )
    active_section = " ".join(
        instructions.split("ACTIVE-BUILD LOCAL EXECUTION", 1)[1]
        .split("REQUEST FIDELITY", 1)[0]
        .split()
    )
    prohibited_section = instructions.split("PROHIBITED ACTIONS", 1)[1]
    assert "ordinary local command-execution capability" in active_section
    assert "customer never types the command" in active_section
    assert "first execute coordinator_prefix with --help" not in instructions
    assert "Do not run current-loop --help" in instructions
    assert "fresh_active_build_request_baseline_staging" in instructions
    assert "diagnostics only" in instructions
    assert "Use the supplied python_executable exactly" not in prohibited_section


def test_activation_runtime_paths_with_spaces_are_unambiguous_for_posix_and_windows() -> None:
    posix_python = "/opt/qCoder Runtime/bin/python"
    posix_token = "/Users/example/.qcoder/context bridge/token.txt"
    posix_runtime = _activation_runtime(
        build_client_activation_instructions(
            base_url="https://posix.example.invalid",
            token_file=posix_token,
            python_executable=posix_python,
            path_style="posix",
        )
    )
    assert posix_runtime["python_executable"] == posix_python
    assert posix_runtime["coordinator_prefix"] == [
        posix_python,
        "-m",
        "qcoder",
        "current-loop",
    ]
    assert posix_runtime["coordinator_prefix_diagnostics_only"] is True
    assert posix_runtime["token_file_path"] == posix_token

    windows_python = r"C:\Program Files\qCoder Runtime\python.exe"
    windows_token = r"C:\Users\Example User\.qcoder\context bridge\token.txt"
    windows_runtime = _activation_runtime(
        build_client_activation_instructions(
            base_url="https://windows.example.invalid",
            token_file=windows_token,
            python_executable=windows_python,
            path_style="nt",
        )
    )
    assert windows_runtime["python_executable"] == windows_python
    assert windows_runtime["coordinator_prefix"] == [
        windows_python,
        "-m",
        "qcoder",
        "current-loop",
    ]
    assert windows_runtime["coordinator_prefix_diagnostics_only"] is True
    assert windows_runtime["token_file_path"] == windows_token


def test_activation_instruction_preserves_lossless_request_baseline_protocol(
    tmp_path: Path,
) -> None:
    instructions = build_client_activation_instructions(
        base_url="https://configured.example.invalid",
        token_file=tmp_path / "token.txt",
        python_executable=tmp_path / "runtime with spaces" / "python",
    )
    headings = [
        "REQUEST FIDELITY",
        "ACTIVATION PROTOCOL",
        "CHECKPOINT PROTOCOL",
        "CONFIGURED RUNTIME",
        "AUTHORITY BOUNDARIES",
        "PROHIBITED ACTIONS",
    ]
    assert [instructions.index(heading) for heading in headings] == sorted(
        instructions.index(heading) for heading in headings
    )
    normalized = " ".join(instructions.split())
    for required in (
        "complete governing customer message verbatim as original_request",
        "Do not summarize",
        "abbreviate",
        "paraphrase",
        "reword",
        "is additive and never removes wording from original_request",
        "Stop before activation if exact transfer cannot be completed",
        "exact fresh-active-build bootstrap invocation",
        "exact UTF-8 stdin channel",
        "returned complete capture",
        "Do not ask the user to repeat the task",
        "never use a later one-word “Yes” as original_request",
        "exact authority-only invocation returned by qCoder",
        "Do not resend or reconstruct the request",
        "Material Blueprint decisions and action-specific authority remain separate",
    ):
        assert required in normalized
    assert "Claude-specific prompt hook" not in instructions
    assert "transcript scraping" not in instructions


def test_activation_runtime_preserves_virtual_environment_executable_identity(
    tmp_path: Path,
) -> None:
    real_python = tmp_path / "system" / "python"
    real_python.parent.mkdir()
    real_python.touch()
    virtualenv_python = tmp_path / "candidate venv" / "bin" / "python"
    virtualenv_python.parent.mkdir(parents=True)
    virtualenv_python.symlink_to(real_python)

    runtime = _activation_runtime(
        build_client_activation_instructions(
            base_url="https://example.invalid",
            token_file=tmp_path / "token.txt",
            python_executable=virtualenv_python,
        )
    )

    assert runtime["python_executable"] == str(virtualenv_python.absolute())
    assert runtime["python_executable"] != str(real_python.resolve())
    assert runtime["coordinator_prefix"][0] == str(virtualenv_python.absolute())


def test_initialize_adds_no_mcp_operation_or_domain_tool(tmp_path: Path) -> None:
    token_file = tmp_path / "not-read-during-initialize.txt"
    initialized = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        base_url="https://example.invalid",
        token_file=token_file,
    )
    listed = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        base_url="https://example.invalid",
        token_file=token_file,
    )
    prompts = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/list"},
        base_url="https://example.invalid",
        token_file=token_file,
    )
    resources = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
        base_url="https://example.invalid",
        token_file=token_file,
    )
    unknown = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 5, "method": "qcoder/runtime"},
        base_url="https://example.invalid",
        token_file=token_file,
    )

    assert initialized is not None
    assert listed is not None
    assert prompts is not None
    assert resources is not None
    assert unknown is not None
    assert len(listed["result"]["tools"]) == 12
    assert [tool["name"] for tool in listed["result"]["tools"]] == list(EXPECTED_TOOLS)
    assert prompts["result"]["prompts"] == []
    assert resources["result"]["resources"] == []
    assert unknown["error"] == {"code": -32601, "message": "method_not_supported"}


def test_working_blueprint_inherits_exact_decision_context_from_confirmed_card(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    lineage_ref = "session-artifact-0123456789abcdef"
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=lineage_ref,
        parent_artifact_references=[{"artifact_ref": lineage_ref}],
    )
    record_set = pack_decision_record_set(profile_id="generic_qiskit", decision_records=records)
    card = {
        "artifact_type": "algorithm_intent_card",
        "artifact_digest": "a" * 64,
        "decision_loop": {
            "gate": "readiness_resolution_v1",
            "catalog_version": 1,
        },
        "blueprint_decision_records": record_set,
    }
    captured: dict[str, object] = {}

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _FakeResponse(
            {
                "ok": True,
                "tool_name": "create_implementation_blueprint",
                "context_status": "implementation_blueprint_ready",
                "implementation_blueprint": {"artifact_type": "implementation_blueprint"},
                "output_evidence_contract": {"artifact_type": "output_evidence_contract"},
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        )

    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_implementation_blueprint",
        artifact_text=None,
        tool_arguments={
            "algorithm_intent_card": card,
            "intent_relationship": {
                "relationship_type": "represented_by",
                "parent_artifact_digest": card["artifact_digest"],
            },
        },
        opener=opener,
    )

    assert result["ok"] is True, result
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["decision_loop"] == "readiness_resolution_v1"
    assert body["profile_decision_catalog_version"] == 1
    assert body["current_lineage_reference"] == lineage_ref
    assert "blueprint_decision_records" not in body


def test_working_blueprint_rejects_reconstructed_decision_context_before_network(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    lineage_ref = "session-artifact-0123456789abcdef"
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=lineage_ref,
        parent_artifact_references=[{"artifact_ref": lineage_ref}],
    )
    record_set = pack_decision_record_set(profile_id="generic_qiskit", decision_records=records)
    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_implementation_blueprint",
        artifact_text=None,
        tool_arguments={
            "decision_loop": "readiness_resolution_v1",
            "profile_decision_catalog_version": 1,
            "current_lineage_reference": "session-artifact-fedcba9876543210",
            "algorithm_intent_card": {
                "artifact_type": "algorithm_intent_card",
                "decision_loop": {
                    "gate": "readiness_resolution_v1",
                    "catalog_version": 1,
                },
                "blueprint_decision_records": record_set,
            },
            "intent_relationship": {
                "relationship_type": "represented_by",
                "parent_artifact_digest": "a" * 64,
            },
        },
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network should not be called")
        ),
    )

    assert result["ok"] is False
    assert result["error_category"] == "current_lineage_reference_parent_mismatch"


def test_next_generation_accepts_bounded_evolved_blueprint_payload(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    lineage_ref = "session-artifact-0123456789abcdef"
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=lineage_ref,
        parent_artifact_references=[{"artifact_ref": lineage_ref}],
    )
    record_set = pack_decision_record_set(profile_id="generic_qiskit", decision_records=records)
    blueprint = {
        "artifact_type": "implementation_blueprint",
        "decision_loop": {
            "gate": "readiness_resolution_v1",
            "catalog_version": 1,
        },
        "blueprint_decision_records": record_set,
        "bounded_projection": "",
    }
    base_size = len(json.dumps(blueprint, sort_keys=True, separators=(",", ":")))
    blueprint["bounded_projection"] = "x" * (100_000 - base_size)
    serialized_size = len(json.dumps(blueprint, sort_keys=True, separators=(",", ":")))
    assert 96_000 < serialized_size < context_bridge_mcp.MAX_DECISION_LOOP_PAYLOAD_CHARS
    captured: dict[str, object] = {}

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _FakeResponse(
            {
                "ok": True,
                "tool_name": "create_generation_context_pack",
                "context_status": "generation_context_ready",
                "generation_context_pack": {"artifact_type": "generation_context_pack"},
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        )

    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_generation_context_pack",
        artifact_text=None,
        tool_arguments={
            "implementation_blueprint": blueprint,
            "output_evidence_contract": {"artifact_type": "output_evidence_contract"},
        },
        opener=opener,
    )

    assert result["ok"] is True, result
    body = captured["body"]
    assert isinstance(body, dict)
    assert len(json.dumps(body, sort_keys=True, separators=(",", ":"))) < 131_072
    assert body["implementation_blueprint"] == blueprint

    oversized = dict(blueprint)
    oversized["bounded_projection"] = "x" * (context_bridge_mcp.MAX_DECISION_LOOP_PAYLOAD_CHARS)
    rejected = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_generation_context_pack",
        artifact_text=None,
        tool_arguments={
            "implementation_blueprint": oversized,
            "output_evidence_contract": {"artifact_type": "output_evidence_contract"},
        },
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network should not be called")
        ),
    )
    assert rejected["ok"] is False
    assert rejected["error_category"] == "artifact_text_too_large"


def test_explicit_decision_loop_generation_rejects_legacy_blueprint_before_network(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    legacy_blueprint = {
        "artifact_type": "implementation_blueprint",
        "artifact_digest": "a" * 64,
    }
    output_contract = {
        "artifact_type": "output_evidence_contract",
        "artifact_digest": "b" * 64,
    }

    rejected = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_generation_context_pack",
        artifact_text=None,
        tool_arguments={
            "decision_loop": "readiness_resolution_v1",
            "implementation_blueprint": legacy_blueprint,
            "output_evidence_contract": output_contract,
        },
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network should not be called")
        ),
    )

    assert rejected["ok"] is False
    assert rejected["error_category"] == "working_blueprint_not_decision_ready"
    assert rejected["message"] == (
        "This Working Blueprint does not contain the decision inventory required "
        "for Carry-Forward. Return to the Intent review and create a "
        "decision-loop-confirmed Working Blueprint before generating downstream "
        "evidence."
    )
    assert rejected["retained_artifacts"] == []

    captured: dict[str, object] = {}

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _FakeResponse(
            {
                "ok": True,
                "tool_name": "create_generation_context_pack",
                "generation_context_pack": {"artifact_type": "generation_context_pack"},
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        )

    legacy = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_generation_context_pack",
        artifact_text=None,
        tool_arguments={
            "implementation_blueprint": legacy_blueprint,
            "output_evidence_contract": output_contract,
        },
        opener=opener,
    )

    assert legacy["ok"] is True
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["implementation_blueprint"] == legacy_blueprint
    assert "decision_loop" not in body


def test_current_build_proposal_call_requires_and_transports_evidence_parents(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    lineage_ref = "session-artifact-0123456789abcdef"
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=lineage_ref,
        parent_artifact_references=[{"artifact_ref": lineage_ref}],
        dispositions={
            item["profile_decision_id"]: {
                "resolution_state": "resolved",
                "user_disposition": "selected_choice",
                "generation_effect": "non_blocking",
                "choice_origin": "human_specified",
            }
            for item in context_bridge_mcp.catalog_entries("generic_qiskit")
        },
    )
    record_set = pack_decision_record_set(profile_id="generic_qiskit", decision_records=records)
    target = records[0]
    working_blueprint = {
        "artifact_type": "implementation_blueprint",
        "artifact_ref": "session-artifact-dddddddddddddddd",
        "artifact_digest": "b" * 64,
        "blueprint_decision_records": record_set,
        "blueprint_readiness_summary": {
            "aggregate_readiness_result": "ready_to_generate",
            "generation_context_eligibility": True,
            "blocking_decision_references": [],
            "bounded_discretion_decision_references": [],
            "evidence_deferred_decision_references": [],
            "non_proof": "Readiness is contract-relative.",
        },
    }
    current_context = {
        **_passive_current_context(),
        "artifact_digest": "c" * 64,
        "artifact_references": {
            "working_blueprint": {
                "artifact_ref": working_blueprint["artifact_ref"],
                "digest": working_blueprint["artifact_digest"],
            },
            "lineage": {
                "artifact_ref": _passive_lineage()["artifact_ref"],
                "digest": _passive_lineage()["artifact_digest"],
            },
        },
    }
    parents = [
        working_blueprint,
        {
            **_passive_lineage(),
            "artifact_type": "decision_evidence_lineage",
        },
        {
            **current_context,
            "artifact_type": "current_build_context",
        },
    ]
    common = {
        "context_loop": "current_build_context_v1",
        "decision_loop": "readiness_resolution_v1",
        "profile_decision_catalog_version": 1,
        "current_lineage_reference": lineage_ref,
        "resolution_context": "current_build_context",
        "resolution_phase": "propose",
        "selected_action": "accept_and_add_to_blueprint",
        "selected_decision_references": [target["decision_ref"]],
        "proposed_updates": [
            {
                "decision_ref": target["decision_ref"],
                "resource_architecture_selection": {
                    "logical_resource_architecture": "simple_flat",
                    "allowed_patterns": ["direct_inline"],
                    "disallowed_patterns": ["avoid_opaque_or_unbounded_dynamic_construction"],
                    "construction_form": "direct_quantum_circuit",
                },
            }
        ],
        "algorithm_intent_card": {"artifact_type": "algorithm_intent_card"},
        "intent_relationship": {"relationship_type": "implemented_by"},
        "working_blueprint": working_blueprint,
        "current_build_context": current_context,
    }
    missing = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_implementation_blueprint",
        artifact_text=None,
        tool_arguments=common,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network should not be called")
        ),
    )
    assert missing["ok"] is False
    assert missing["error_category"] == "evidence_parent_artifacts_required"

    captured: dict[str, object] = {}

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        captured["body"] = body
        proposal = build_carry_forward_proposal(
            selected_action=body["selected_action"],
            profile_id="generic_qiskit",
            decision_records=records,
            parent_artifacts=body["evidence_parent_artifacts"],
            current_build_context=body["current_build_context"],
            selected_decision_references=body["selected_decision_references"],
            proposed_updates=body["proposed_updates"],
            current_lineage_reference=body["current_lineage_reference"],
            remaining_uncertainty=["Correctness remains unproven."],
            generation_context_effect="Apply only after explicit confirmation.",
            proposal_ref="proposal-1234567890abcdefghijkl",
            prospective_derived_references=["derived-1234567890abcdefghijkl"],
        )
        return _FakeResponse(
            {
                "ok": True,
                "tool_name": "create_implementation_blueprint",
                "context_status": "carry_forward_proposal_ready",
                "proposal_state": "unconfirmed",
                "carry_forward_proposal": proposal,
                "derived_artifact_materialized": False,
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        )

    complete = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_implementation_blueprint",
        artifact_text=None,
        tool_arguments={**common, "evidence_parent_artifacts": parents},
        opener=opener,
    )
    assert complete["ok"] is True, complete
    assert captured["body"]["evidence_parent_artifacts"] == parents  # type: ignore[index]
    assert captured["body"]["blueprint_decision_records"] == record_set  # type: ignore[index]
    assert len(captured["body"]["blueprint_decision_records"]["records"]) == 19  # type: ignore[index]
    expanded = captured["body"]["proposed_updates"]  # type: ignore[index]
    assert len(expanded) == 1
    assert expanded[0]["semantic_classification"] == "blueprint_decision"
    assert (
        expanded[0]["resource_architecture"]["logical_resource_architecture"]["value"]
        == "simple_flat"
    )
    assert "resource_architecture_selection" not in expanded[0]
    assert complete["proposal_state"] == "unconfirmed"
    assert complete["derived_artifact_materialized"] is False
    proposal = complete["carry_forward_proposal"]
    portable = complete["portable_current_build_context"]
    assert len(portable["decision_records"]) == 19
    assert portable["carry_forward_proposal"]["proposal_ref"] == ("proposal-1234567890abcdefghijkl")
    assert portable["carry_forward_proposal"]["proposed_outcome"]["decision_updates"] == (expanded)
    assert "confirmation_transport" not in portable
    expected_tool_input = {
        key: value
        for key, value in captured["body"].items()
        if key not in {"tool_name", "artifact_kind", "client_context"}
    }
    assert portable["transport"]["proposal_resupply"]["tool_input"] == expected_tool_input
    selected_file = tmp_path / "proposal-bearing.portable.json"
    selected_file.write_text(
        canonical_portable_current_build_context_json(portable),
        encoding="utf-8",
    )
    confirmation = {"confirmed": True, "confirmed_by": "test-user"}
    exact_confirm, digest, error = context_bridge_mcp._expand_selected_portable_bundle(
        {
            "use_selected_portable_bundle": True,
            "proposal_ref": proposal["proposal_ref"],
            "selected_action": proposal["selected_action"],
            "resolution_confirmation": confirmation,
        },
        selected_file=selected_file,
    )
    assert error is None
    assert exact_confirm is not None
    assert exact_confirm["resolution_phase"] == "confirm"
    assert exact_confirm["decision_resolution_pack"] == proposal
    assert exact_confirm["evidence_parent_artifacts"] == parents
    assert exact_confirm["blueprint_decision_records"] == record_set
    assert exact_confirm["resolution_confirmation"] == confirmation
    assert (
        exact_confirm["confirmation_payload"]
        == proposal["explicit_confirmation_requirements"]["confirmation_payload"]
    )
    assert digest == canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=exact_confirm,
    )


def test_current_build_accept_proposal_rejects_empty_update_before_network(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    lineage_ref = "session-artifact-0123456789abcdef"
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=lineage_ref,
        parent_artifact_references=[{"artifact_ref": lineage_ref}],
    )
    record_set = pack_decision_record_set(profile_id="generic_qiskit", decision_records=records)
    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_implementation_blueprint",
        artifact_text=None,
        tool_arguments={
            "context_loop": "current_build_context_v1",
            "decision_loop": "readiness_resolution_v1",
            "resolution_context": "current_build_context",
            "resolution_phase": "propose",
            "selected_action": "accept_and_add_to_blueprint",
            "selected_decision_references": [records[0]["decision_ref"]],
            "proposed_updates": [],
            "algorithm_intent_card": {"artifact_type": "algorithm_intent_card"},
            "intent_relationship": {"relationship_type": "implemented_by"},
            "working_blueprint": {
                "artifact_type": "implementation_blueprint",
                "blueprint_decision_records": record_set,
            },
            "current_build_context": {"schema_id": "qcoder.current_build_context.v1"},
            "evidence_parent_artifacts": [{"artifact_type": "parent"}],
        },
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network should not be called")
        ),
    )
    assert result["ok"] is False
    assert result["error_category"] == "proposed_updates_missing"


def test_current_build_context_composes_share_safe_request_baseline_from_existing_fields(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    captured: dict[str, object] = {}

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _FakeResponse(
            {
                "ok": True,
                "tool_name": "create_context_session_card",
                "context_status": "current_build_context_ready",
                "current_build_context": _passive_current_context(),
                "retained_artifacts": [],
            }
        )

    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_context_session_card",
        artifact_text=None,
        tool_arguments={
            "context_loop": "current_build_context_v1",
            "request_baseline": {
                "text": "Create a selected Bell circuit example.",
                "profile": "generic_qiskit",
            },
            "request_share_safe_summary": "Create a selected Bell circuit example.",
            "request_text_share_safe": True,
            "assistant_interpretation": {
                "summary": "Use a direct two-qubit Qiskit circuit.",
                "provenance_role": "assistant_proposed",
            },
            "profile_suggestions": ["generic_qiskit"],
            "working_blueprint": {"artifact_type": "implementation_blueprint"},
            "stage_availability": {"schema_id": "qcoder.stage_availability.v1"},
            "decision_evidence_lineage": _passive_lineage(),
        },
        opener=opener,
    )

    assert result["ok"] is True, result
    body = captured["body"]
    assert isinstance(body, dict)
    baseline = body["request_baseline"]
    assert baseline["artifact_type"] == "request_baseline_handoff"
    assert baseline["request_summary"] == "Create a selected Bell circuit example."
    assert baseline["original_request_text_withheld"] is False
    assert baseline["share_safe_selection"] == "explicit_verbatim_selection"
    assert baseline["share_safe"] is True
    assert baseline["retention"] == "process_and_discard"
    assert baseline["assistant_interpretation"]["provenance_role"] == "assistant_proposed"
    assert baseline["profile_suggestions"] == ["generic_qiskit"]
    assert len(baseline["artifact_digest"]) == 64
    assert result["portable_current_build_context"]["schema_id"] == (
        "qcoder.current_build_context.portable.v1"
    )
    assert result["portable_current_build_context"]["decision_records"] == []

    schema = next(
        tool["inputSchema"]
        for tool in tool_descriptors()
        if tool["name"] == "create_context_session_card"
    )
    assert any(
        set(branch.get("required", []))
        >= {
            "request_share_safe_summary",
            "request_text_share_safe",
            "working_blueprint",
            "stage_availability",
            "decision_evidence_lineage",
        }
        for branch in schema["anyOf"]
    )
    properties = schema["properties"]
    stage_schema = properties["stage_availability"]
    assert stage_schema["required"] == ["schema_id", "artifact_type", "stages"]
    assert set(stage_schema["properties"]["stages"]["required"]) == {
        "human_intent",
        "python_source",
        "logical_circuit",
        "target_circuit",
        "run_results",
        "next_human_intent",
    }
    lineage_schema = properties["decision_evidence_lineage"]
    assert lineage_schema["properties"]["schema_id"]["const"] == (
        "qcoder.decision_evidence_lineage.v1"
    )
    relationship_schema = lineage_schema["properties"]["links"]["items"]["properties"][
        "relationship"
    ]
    assert relationship_schema["required"] == [
        "relationship_type",
        "source",
        "target",
        "direction",
        "supplied_evidence_basis",
        "declaration_state",
        "non_proof",
    ]
    assert relationship_schema["properties"]["source"]["properties"]["artifact_reference"][
        "properties"
    ]["retrievable"] == {"const": False}
    assert properties["current_lineage_reference"]["pattern"] == (
        r"^session-artifact-[0-9a-f]{16,64}$"
    )
    intent_schema = next(
        tool["inputSchema"]
        for tool in tool_descriptors()
        if tool["name"] == "create_algorithm_intent_card"
    )
    dispositions = intent_schema["properties"]["decision_dispositions"]["oneOf"][0]["items"]
    assert dispositions["properties"]["user_disposition"]["enum"] == [
        "selected_choice",
        "bounded_alternatives",
        "bounded_value_range",
        "deferred_to_source_evidence",
        "deferred_to_later_evidence",
        "left_unresolved",
        "not_supplied",
    ]
    assert "selected_value" in dispositions["properties"]
    assert "selected_choice" not in dispositions["properties"]


def test_current_build_context_rejects_conflicting_reconstructed_request_baseline(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    def opener(*args: object, **kwargs: object) -> _FakeResponse:
        raise AssertionError("conflicting request must not be sent")

    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_context_session_card",
        artifact_text=None,
        tool_arguments={
            "context_loop": "current_build_context_v1",
            "request_baseline": {"text": "Different request."},
            "request_share_safe_summary": "Create a selected Bell circuit example.",
            "request_text_share_safe": True,
            "working_blueprint": {"artifact_type": "implementation_blueprint"},
            "stage_availability": {"schema_id": "qcoder.stage_availability.v1"},
            "decision_evidence_lineage": {"schema_id": "qcoder.decision_evidence_lineage.v1"},
        },
        opener=opener,
    )

    assert result["ok"] is False
    assert result["error_category"] == "conflicting_tool_argument"
    assert result["retained_artifacts"] == []
    assert result["raw_payload_printed"] is False


def test_intent_card_context_loop_stage_is_absent_and_rejected_before_network(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_algorithm_intent_card",
        artifact_text=None,
        tool_arguments={
            "context_loop": "current_build_context_v1",
            "decision_loop": "readiness_resolution_v1",
            "request_share_safe_summary": "Create a selected Bell circuit example.",
            "request_text_share_safe": True,
            "original_user_intent": "Create a selected Bell circuit example.",
            "assistant_interpretation": {
                "summary": "Use a direct two-qubit Qiskit circuit.",
                "provenance_role": "assistant_proposed",
            },
            "profile_suggestions": ["generic_qiskit"],
            "profile_id": "generic_qiskit",
        },
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network should not be called")
        ),
    )

    assert result["ok"] is False
    assert result["error_category"] == "context_loop_stage_not_supported"
    intent_schema = next(
        tool["inputSchema"]
        for tool in tool_descriptors()
        if tool["name"] == "create_algorithm_intent_card"
    )
    assert "context_loop" not in intent_schema["properties"]


def _passive_current_context() -> dict[str, object]:
    return {
        "schema_id": "qcoder.current_build_context.v1",
        "artifact_ref": "session-artifact-aaaaaaaaaaaaaaaa",
        "profile_id": "generic_qiskit",
        "artifact_references": {},
        "stage_availability": {},
        "stage_identity": {},
        "selected_share_safe_summaries": {},
        "non_proofs": ["No correctness or run-readiness claim."],
    }


def _passive_lineage() -> dict[str, object]:
    return {
        "schema_id": "qcoder.decision_evidence_lineage.v1",
        "artifact_ref": "session-artifact-bbbbbbbbbbbbbbbb",
        "artifact_digest": "b" * 64,
        "links": [],
    }


def _passive_portable_bundle() -> dict[str, object]:
    return build_portable_current_build_context(
        current_build_context=_passive_current_context(),
        decision_evidence_lineage=_passive_lineage(),
    )


def test_selected_portable_bundle_file_is_single_local_safe_input(tmp_path: Path) -> None:
    portable = _passive_portable_bundle()
    selected = tmp_path / "selected.json"
    selected.write_text(
        canonical_portable_current_build_context_json(portable),
        encoding="utf-8",
    )
    loaded, error = context_bridge_mcp._load_selected_portable_bundle(selected)
    assert error is None
    assert loaded == portable

    directory, error = context_bridge_mcp._load_selected_portable_bundle(tmp_path)
    assert directory is None
    assert error == "selected_portable_bundle_file_required"

    link = tmp_path / "linked.json"
    link.symlink_to(selected)
    linked, error = context_bridge_mcp._load_selected_portable_bundle(link)
    assert linked is None
    assert error == "selected_portable_bundle_symlink_rejected"

    unsafe = dict(portable)
    unsafe["raw_qasm"] = "withheld"
    unsafe = with_consistency_digest(unsafe)
    unsafe_file = tmp_path / "unsafe.json"
    unsafe_file.write_text(json.dumps(unsafe), encoding="utf-8")
    rejected, error = context_bridge_mcp._load_selected_portable_bundle(unsafe_file)
    assert rejected is None
    assert error == "portable_bundle_prohibited_content"
    assert str(selected) not in error


def test_preproposal_selected_bundle_expands_exact_parents_without_model_reconstruction(
    tmp_path: Path,
) -> None:
    lineage_ref = "session-artifact-0123456789abcdef"
    records = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=lineage_ref,
        parent_artifact_references=[{"artifact_ref": lineage_ref}],
    )
    record_set = pack_decision_record_set(profile_id="generic_qiskit", decision_records=records)
    working_blueprint = {
        "artifact_type": "implementation_blueprint",
        "artifact_digest": "2" * 64,
        "decision_loop": {
            "gate": "readiness_resolution_v1",
            "catalog_version": 1,
        },
        "blueprint_decision_records": record_set,
        "blueprint_readiness_summary": {
            "aggregate_readiness_result": "ready_to_generate",
            "generation_context_eligibility": True,
        },
    }
    supplied = {
        "request_baseline": {
            "artifact_type": "request_baseline_handoff",
            "artifact_ref": "session-artifact-1111111111111111",
            "artifact_digest": "1" * 64,
        },
        "working_blueprint": working_blueprint,
        "generation_context": {
            "artifact_type": "generation_context_pack",
            "artifact_digest": "3" * 64,
        },
        "python_manifestation": {
            "artifact_type": "python_manifestation",
            "artifact_ref": "session-artifact-4444444444444444",
            "artifact_digest": "4" * 64,
        },
        "circuit_manifestation": {
            "artifact_type": "circuit_manifestation",
            "artifact_ref": "session-artifact-5555555555555555",
            "artifact_digest": "5" * 64,
        },
        "result_manifestation": {
            "artifact_type": "result_manifestation",
            "artifact_ref": "session-artifact-6666666666666666",
            "artifact_digest": "6" * 64,
        },
        "decision_evidence_lineage": {
            "schema_id": "qcoder.decision_evidence_lineage.v1",
            "artifact_type": "decision_evidence_lineage",
            "artifact_ref": "session-artifact-7777777777777777",
            "artifact_digest": "7" * 64,
            "links": [],
        },
    }
    current = {
        **_passive_current_context(),
        "artifact_digest": "8" * 64,
        "artifact_references": {
            "request_baseline": {
                "artifact_ref": "session-artifact-1111111111111111",
                "digest": "1" * 64,
            },
            "working_blueprint": {
                "artifact_ref": "session-artifact-2222222222222222",
                "digest": "2" * 64,
            },
            "generation_context": {
                "artifact_ref": "session-artifact-3333333333333333",
                "digest": "3" * 64,
            },
            "python_manifestation": {
                "artifact_ref": "session-artifact-4444444444444444",
                "digest": "4" * 64,
            },
            "circuit_manifestation": {
                "artifact_ref": "session-artifact-5555555555555555",
                "digest": "5" * 64,
            },
            "result_manifestation": {
                "artifact_ref": "session-artifact-6666666666666666",
                "digest": "6" * 64,
            },
            "lineage": {
                "artifact_ref": "session-artifact-7777777777777777",
                "digest": "7" * 64,
            },
        },
    }
    payload = {"current_build_context": current}
    assert context_bridge_mcp._attach_portable_current_build_context(payload, supplied) is None
    portable = payload["portable_current_build_context"]
    selected = tmp_path / "preproposal.json"
    selected.write_text(
        canonical_portable_current_build_context_json(portable),
        encoding="utf-8",
    )
    card = {
        "artifact_type": "algorithm_intent_card",
        "artifact_digest": "a" * 64,
        "decision_loop": {
            "gate": "readiness_resolution_v1",
            "catalog_version": 1,
        },
        "blueprint_decision_records": record_set,
    }
    target = next(
        record
        for record in records
        if record["profile_decision_id"] == "generic_qiskit.circuit_construction"
    )
    expanded, digest, error = context_bridge_mcp._expand_selected_portable_bundle(
        {
            "use_selected_portable_bundle": True,
            "algorithm_intent_card": card,
            "intent_relationship": {
                "relationship_type": "represented_by",
                "parent_artifact_digest": card["artifact_digest"],
            },
            "selected_action": "accept_and_add_to_blueprint",
            "selected_decision_references": [target["decision_ref"]],
            "proposed_updates": [
                {
                    "decision_ref": target["decision_ref"],
                    "resource_architecture_selection": {
                        "logical_resource_architecture": "simple_flat",
                        "allowed_patterns": ["direct_inline"],
                        "disallowed_patterns": ["avoid_opaque_or_unbounded_dynamic_construction"],
                        "construction_form": "direct_quantum_circuit",
                    },
                }
            ],
        },
        selected_file=selected,
    )
    assert error is None
    assert expanded is not None
    assert digest == canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=expanded,
    )
    assert len(expanded["evidence_parent_artifacts"]) == 8
    assert len(expanded["blueprint_decision_records"]["records"]) == 19
    assert expanded["working_blueprint"]["artifact_ref"] == ("session-artifact-2222222222222222")
    generation_parent = next(
        parent
        for parent in expanded["evidence_parent_artifacts"]
        if parent["artifact_type"] == "generation_context_pack"
    )
    assert generation_parent["artifact_ref"] == "session-artifact-3333333333333333"
    assert len(expanded["proposed_updates"]) == 1
    assert "resource_architecture_selection" not in expanded["proposed_updates"][0]
    assert "resolution_confirmation" not in expanded
    assert "confirmation_payload" not in expanded
    assert "use_selected_portable_bundle" not in expanded


def test_named_client_ref_file_substitution_remains_rejected(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    result = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_implementation_blueprint",
                "arguments": {"$refFile": "/local/path/that/must/not/be-read.json"},
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
    )
    assert result is not None
    payload = result["result"]["structuredContent"]
    assert payload["error_category"] == "unsupported_tool_argument"
    assert "/local/path" not in json.dumps(payload)


def test_selected_bundle_expansion_preserves_exact_input_and_digest(
    tmp_path: Path, monkeypatch: object
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    parents = [
        {
            "artifact_type": artifact_type,
            "artifact_ref": f"session-artifact-{index:016x}",
            "artifact_digest": f"{index:x}" * 64,
        }
        for index, artifact_type in enumerate(
            (
                "request_baseline_handoff",
                "implementation_blueprint",
                "generation_context_pack",
                "python_source_manifestation",
                "circuit_manifestation",
                "result_manifestation",
                "decision_evidence_lineage",
                "current_build_context",
            ),
            start=1,
        )
    ]
    decision_records = {
        "artifact_type": "blueprint_decision_record_set",
        "schema_version": 1,
        "records": [{"decision_ref": f"decision-{index:019d}"} for index in range(19)],
    }
    exact_input = {
        "context_loop": "current_build_context_v1",
        "resolution_context": "current_build_context",
        "resolution_phase": "confirm",
        "proposal_ref": "proposal-0123456789abcdefghijkl",
        "selected_action": "accept_and_add_to_blueprint",
        "resolution_confirmation": {"confirmed": True, "confirmed_by": "Rob"},
        "confirmation_payload": {
            "proposal_ref": "proposal-0123456789abcdefghijkl",
            "selected_action": "accept_and_add_to_blueprint",
        },
        "decision_resolution_pack": {
            "proposal_ref": "proposal-0123456789abcdefghijkl",
            "selected_action": "accept_and_add_to_blueprint",
        },
        "algorithm_intent_card": {"artifact_type": "algorithm_intent_card"},
        "intent_relationship": {
            "relationship_type": "represented_by",
            "parent_artifact_digest": "b" * 64,
        },
        "working_blueprint": {
            "artifact_type": "implementation_blueprint",
            "blueprint_decision_records": decision_records,
        },
        "blueprint_decision_records": decision_records,
        "current_build_context": {
            "schema_id": "qcoder.current_build_context.v1",
            "artifact_ref": "session-artifact-aaaaaaaaaaaaaaaa",
        },
        "evidence_parent_artifacts": parents,
    }
    digest = canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=exact_input,
    )
    bundle = {
        "confirmation_transport": {
            "tool_input": exact_input,
            "canonical_request_sha256": digest,
        }
    }
    monkeypatch.setattr(  # type: ignore[attr-defined]
        context_bridge_mcp,
        "_load_selected_portable_bundle",
        lambda _selected: (bundle, None),
    )
    captured: dict[str, object] = {}

    class Response:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": True,
                    "tool_name": "create_implementation_blueprint",
                    "retained_artifacts": [],
                    "request_fidelity": {
                        "local_canonical_request_sha256": digest,
                        "protected_received_request_sha256": digest,
                        "digests_equal": True,
                    },
                }
            ).encode("utf-8")

    def opener(request: object, timeout: int = 20) -> Response:
        captured["body"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return Response()

    result = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_implementation_blueprint",
                "arguments": {
                    "use_selected_portable_bundle": True,
                    "proposal_ref": exact_input["proposal_ref"],
                    "selected_action": exact_input["selected_action"],
                    "resolution_confirmation": exact_input["resolution_confirmation"],
                },
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
        selected_portable_bundle_file=tmp_path / "selected.json",
        opener=opener,
    )
    assert result is not None
    assert result["result"]["structuredContent"]["ok"] is True
    body = captured["body"]
    assert isinstance(body, dict)
    for key, value in exact_input.items():
        assert body[key] == value
    assert len(body["evidence_parent_artifacts"]) == 8
    assert len(body["blueprint_decision_records"]["records"]) == 19
    assert "use_selected_portable_bundle" not in body
    assert "selected_portable_bundle_file" not in body
    assert str(tmp_path) not in json.dumps(body, sort_keys=True)
    assert body["client_context"]["canonical_request_sha256"] == digest


def test_tool_descriptors_advertise_only_tool_specific_fields() -> None:
    schemas = {tool["name"]: tool["inputSchema"] for tool in tool_descriptors()}
    expected_properties = {
        "get_guided_evidence_context": {"artifact_text", "artifact_kind", "client_context"},
        "create_prompt_context": {"artifact_text", "artifact_kind", "client_context", "mode"},
        "create_evidence_context_pack": {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
        },
        "create_context_session_card": {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
        },
        "create_run_readiness_card": {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
        },
        "create_result_review_context_card": {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "share_safe_evidence_summary",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
        },
        "create_next_check_plan": {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
        },
        "create_single_loop_evidence_diff": {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "before",
            "after",
        },
        "create_algorithm_intent_card": {
            "artifact_kind",
            "client_context",
            "original_user_intent",
            "profile_id",
            "proposed_interpretation",
            "requirements",
            "constraints",
            "non_goals",
            "field_provenance",
            "revision_notes",
            "requested_confirmation_state",
            "confirmation_assertion",
            "accepted_unresolved_choices",
        },
        "create_implementation_blueprint": {
            "artifact_kind",
            "client_context",
            "algorithm_intent_card",
            "intent_relationship",
        },
        "create_generation_context_pack": {
            "artifact_kind",
            "client_context",
            "implementation_blueprint",
            "output_evidence_contract",
        },
        "create_source_blueprint_alignment_review": {
            "artifact_kind",
            "client_context",
            "implementation_blueprint",
            "output_evidence_contract",
            "selected_python_source_evidence",
        },
    }
    assert set(schemas) == set(expected_properties)
    for tool_name, expected in expected_properties.items():
        schema = schemas[tool_name]
        if tool_name in ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS:
            expected = set(ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS[tool_name])
            if tool_name == "create_implementation_blueprint":
                expected.add(context_bridge_mcp.LOCAL_SELECTED_BUNDLE_FIELD)
            if tool_name == "create_generation_context_pack":
                expected.add(context_bridge_mcp.LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD)
        elif tool_name in {
            "create_context_session_card",
            "create_run_readiness_card",
            "create_result_review_context_card",
            "create_next_check_plan",
            "create_single_loop_evidence_diff",
        }:
            expected = expected | set(context_bridge_mcp._CONTEXT_LOOP_EVIDENCE_FIELDS)
        assert set(schema["properties"]) == expected
        expected_required = {
            "create_algorithm_intent_card": ["original_user_intent", "profile_id"],
            "create_implementation_blueprint": ["algorithm_intent_card", "intent_relationship"],
            "create_generation_context_pack": [],
            "create_source_blueprint_alignment_review": [
                "implementation_blueprint",
                "output_evidence_contract",
                "selected_python_source_evidence",
            ],
            "create_context_session_card": [],
            "create_result_review_context_card": [],
            "create_single_loop_evidence_diff": [],
        }.get(tool_name, ["artifact_text"])
        assert schema["required"] == expected_required
        assert schema["additionalProperties"] is False

    # Codex projects conditional top-level allOf schemas as zero-argument tools.
    # The adapter enforces the Current Build Context parent requirements at runtime.
    assert "allOf" not in schemas["create_implementation_blueprint"]

    assert schemas["create_prompt_context"]["properties"]["mode"]["enum"] == sorted(
        ["explain", "review", "revise", "troubleshoot", "plan_next_checks"]
    )
    assert all(
        "mode" not in schema["properties"]
        for name, schema in schemas.items()
        if name != "create_prompt_context"
    )
    assert all(
        "before" not in schema["properties"] and "after" not in schema["properties"]
        for name, schema in schemas.items()
        if name != "create_single_loop_evidence_diff"
    )
    diff_properties = schemas["create_single_loop_evidence_diff"]["properties"]
    assert diff_properties["before"]["type"] == "object"
    assert diff_properties["after"]["type"] == "object"


def test_tools_call_rejects_fields_not_advertised_for_selected_tool(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "create_run_readiness_card",
                "arguments": {
                    "artifact_text": "Share-safe current evidence summary.",
                    "mode": "review",
                },
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
    )

    assert response is not None
    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error_category"] == "unsupported_tool_argument"


def test_run_readiness_call_promotes_existing_label_contract_for_named_clients(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    approved_labels = [
        "Observed",
        "User-provided",
        "Inferred",
        "Assumed",
        "Not proven",
        "Suggested next check",
    ]
    readiness_card = {
        "card_type": "share_safe_current_run_readiness",
        "readiness_summary": "Current supplied evidence supports a bounded readiness discussion.",
        "evidence_supplied": [{"label": "User-provided", "text": "Current evidence."}],
        "observations": [{"label": "Observed", "text": "A bounded plan is present."}],
        "user_provided_facts": [{"label": "User-provided", "text": "An external run is planned."}],
        "inferences": [{"label": "Inferred", "text": "A bounded next step can be planned."}],
        "assumptions": [{"label": "Assumed", "text": "Result bit ordering is unresolved."}],
        "what_the_evidence_supports": [
            {"label": "Inferred", "text": "Readiness can be discussed, not certified."}
        ],
        "what_remains_unproven": [
            {"label": "Not proven", "text": "Execution and circuit correctness."}
        ],
        "suggested_next_check_items": [
            {"label": "Suggested next check", "text": "Confirm result bit ordering."}
        ],
        "evidence_confidence_labels": [
            {"label": label, "meaning": "Approved provenance or evidentiary status."}
            for label in approved_labels
        ],
    }

    class _ReadinessResponse:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self) -> "_ReadinessResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": True,
                    "tool_name": "create_run_readiness_card",
                    "context_status": "run_readiness_card_ready",
                    "retention": "process_and_discard",
                    "retained_artifacts": [],
                    "readiness_card": readiness_card,
                }
            ).encode("utf-8")

    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "create_run_readiness_card",
                "arguments": {"artifact_text": "Share-safe current readiness evidence."},
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
        opener=lambda *_args, **_kwargs: _ReadinessResponse(),
    )

    assert response is not None
    result = response["result"]
    structured = result["structuredContent"]
    assert structured["readiness_card"] == readiness_card
    assert [item["label"] for item in structured["evidence_confidence_labels"]] == approved_labels
    text_payload = json.loads(result["content"][0]["text"])
    assert [item["label"] for item in text_payload["evidence_confidence_labels"]] == approved_labels
    assert text_payload["readiness_card"] == readiness_card
    serialized = json.dumps(result, sort_keys=True).lower()
    for forbidden in (
        "confidence_score",
        "confidence percentage",
        "assurance rating",
        "high confidence",
        "medium confidence",
        "low confidence",
        "runtime prediction",
        "fidelity prediction",
        "backend ranking",
        "entanglement verified",
    ):
        assert forbidden not in serialized


def test_non_readiness_calls_are_not_given_a_synthetic_label_projection(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "get_guided_evidence_context",
                "arguments": {"artifact_text": "Share-safe current evidence."},
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
        opener=lambda *_args, **_kwargs: _FakeResponse(),
    )

    assert response is not None
    assert "evidence_confidence_labels" not in response["result"]["structuredContent"]


def test_token_file_validation_requires_private_local_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    ok, category, token = validate_token_file(missing)
    assert (ok, category, token) == (False, "token_file_missing", "")

    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    ok, category, token = validate_token_file(token_file)
    assert ok is True
    assert category == "ok"
    assert token == "ctxbridge-token-not-printed"

    token_file.chmod(0o644)
    ok, category, token = validate_token_file(token_file)
    assert ok is False
    assert category == "token_file_permissions_unsafe"
    assert token == ""


def test_unsafe_inputs_rejected_before_network(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("network should not be called")

    for text in (
        "OPENQASM 2.0; qreg q[1];",
        "counts={'00': 4}",
        "provider_result={raw backend payload}",
        "/home/example/project/file.py",
        "repo_path=src/example.py",
        "Please compare with prior run history and remember it.",
    ):
        payload = post_context_bridge(
            base_url="https://example.invalid",
            token_file=token_file,
            tool_name="get_guided_evidence_context",
            artifact_text=text,
            opener=fail_if_called,
        )
        assert payload["ok"] is False
        assert payload["error_category"] == "forbidden_input_value"


def test_unknown_tool_and_artifact_lookup_rejected(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="suggest_next_checks",
        artifact_text="share-safe evidence summary",
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "unknown_tool"

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="get_guided_evidence_context",
        artifact_text="artifact id lookup",
        artifact_kind="server_artifact_id",
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "unsupported_artifact_kind"


def test_prompt_modes_and_diff_arguments_are_locally_validated(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        return _FakeResponse()

    for mode in ("explain", "review", "revise", "troubleshoot", "plan_next_checks"):
        payload = post_context_bridge(
            base_url="https://example.invalid",
            token_file=token_file,
            tool_name="create_prompt_context",
            artifact_text="Share-safe current evidence summary.",
            mode=mode,
            opener=opener,
        )
        assert payload["ok"] is True

    invalid = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_prompt_context",
        artifact_text="Share-safe current evidence summary.",
        mode="diagnose",
        opener=opener,
    )
    assert invalid["ok"] is False
    assert invalid["error_category"] == "invalid_prompt_context_mode"

    missing_side = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_single_loop_evidence_diff",
        artifact_text="Share-safe current evidence summary.",
        before={"summary": "before only"},
        opener=opener,
    )
    assert missing_side["ok"] is False
    assert missing_side["error_category"] == "missing_explicit_diff_side"

    diff = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_single_loop_evidence_diff",
        artifact_text="Share-safe current evidence summary.",
        before={"summary": "before current-loop context"},
        after={"summary": "after current-loop context"},
        opener=opener,
    )
    assert diff["ok"] is True

    next_check = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_next_check_plan",
        artifact_text="Share-safe current evidence summary.",
        current_goal="Choose a bounded next check.",
        opener=opener,
    )
    assert next_check["ok"] is True


def test_optional_payloads_reject_raw_or_history_values_before_network(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("network should not be called")

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_single_loop_evidence_diff",
        artifact_text="Share-safe current evidence summary.",
        before={"summary": "before"},
        after={"raw_counts": {"00": 10}},
        opener=fail_if_called,
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "forbidden_input_value"

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_next_check_plan",
        artifact_text="Share-safe current evidence summary.",
        current_goal="Compare with prior run history.",
        opener=fail_if_called,
    )
    assert payload["ok"] is False
    assert payload["error_category"] == "forbidden_input_value"


def test_approved_call_forwards_bearer_without_printing_token(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file, "ctxbridge-secret-token")
    seen: dict[str, str] = {}

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        assert timeout == 20
        seen["authorization"] = request.headers["Authorization"]  # type: ignore[attr-defined]
        return _FakeResponse()

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="get_guided_evidence_context",
        artifact_text="Share-safe current evidence summary.",
        opener=opener,
    )
    assert payload["ok"] is True
    assert seen["authorization"] == "Bearer ctxbridge-secret-token"
    assert payload["token_printed"] is False
    assert "ctxbridge-secret-token" not in json.dumps(payload)


def test_jsonrpc_lists_exact_tools_and_calls_tool(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)

    listed = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        base_url="https://example.invalid",
        token_file=token_file,
    )
    assert listed is not None
    assert [tool["name"] for tool in listed["result"]["tools"]] == list(EXPECTED_TOOLS)

    def opener(request: object, timeout: int = 20) -> _FakeResponse:
        return _FakeResponse()

    called = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_guided_evidence_context",
                "arguments": {"artifact_text": "Share-safe current evidence summary."},
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
        opener=opener,
    )
    assert called is not None
    assert called["result"]["structuredContent"]["ok"] is True
    assert called["result"]["isError"] is False

    diff_called = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "create_single_loop_evidence_diff",
                "arguments": {
                    "artifact_text": "Share-safe current evidence summary.",
                    "before": {"summary": "before current-loop context"},
                    "after": {"summary": "after current-loop context"},
                },
            },
        },
        base_url="https://example.invalid",
        token_file=token_file,
        opener=opener,
    )
    assert diff_called is not None
    assert diff_called["result"]["structuredContent"]["ok"] is True


def _content_length_message(message: dict[str, object]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_content_length_response(stdout: object) -> dict[str, object]:
    headers: dict[str, str] = {}
    while True:
        line = stdout.readline()  # type: ignore[attr-defined]
        assert line
        stripped = line.strip()
        if not stripped:
            break
        key, value = stripped.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    body = stdout.read(int(headers["content-length"]))  # type: ignore[attr-defined]
    return json.loads(body.decode("utf-8"))


def test_mcp_stdio_content_length_lists_exact_tools(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qcoder",
            "context-bridge",
            "mcp",
            "serve",
            "--token-file",
            str(token_file),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(
            _content_length_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
        )
        proc.stdin.flush()
        initialized = _read_content_length_response(proc.stdout)
        assert initialized["result"]["serverInfo"] == {
            "name": "qcoder-context-bridge",
            "version": __version__,
        }
        instructions = initialized["result"]["instructions"]
        normalized_instructions = " ".join(instructions.split())
        runtime = _activation_runtime(instructions)
        executable = str(Path(sys.executable).absolute())
        assert runtime["python_executable"] == executable
        assert runtime["qcoder_version"] == __version__
        assert runtime["coordinator_prefix"] == [
            executable,
            "-m",
            "qcoder",
            "current-loop",
        ]
        assert runtime["base_url"] == "https://preview-api.qcoder.ai"
        assert runtime["token_file_path"] == str(token_file.resolve())
        for required in (
            "explicitly asks to use qCoder",
            "Use the supplied python_executable only through qCoder's exact bootstrap",
            "coordinator_prefix is diagnostics-only metadata",
            "fresh_active_build_request_baseline_staging",
            "Do not run current-loop --help",
            "Never run `which` or `where`",
            "Request Baseline",
            "Never manually sequence Context Bridge tools",
            "Never reconstruct canonical artifacts",
            "Conversational approval and canonical confirmation are distinct",
            "Follow supported_next_action and next_invocation exactly",
            "Never repeat an identical invocation after an unchanged checkpoint",
            "IDE WORK AND ARTIFACT HANDOFF",
            "Retain exact paths returned by your own write or modify operations",
            "truthful created, modified, or selected event disposition",
            "Never inspect .qcoder",
            "exclude .qcoder from every ordinary project inspection",
            "Do not use a glob, find, directory listing, Git status, repository map, or search result",
            "Ordinary inspection of relevant non-qCoder project files",
            "does not register a file or authorize qCoder review",
            "supported exact outputs attributable to a single-use operation receipt",
            "home-directory qCoder state",
            "client configuration",
            "sibling repositories",
            "Workspace freshness is not intent",
            "adaptive or Blueprint-required governance",
            "Preserve exact user-stated decision answers",
            "is not a full Generation Context Pack",
            "decision_resolution checkpoint",
            "exact decision-disposition authority channel",
            "do not ask a routine posture question",
            "does not grant IDE permission to write or run",
            "exact artifact candidates",
            "proposal-specific explicit confirmation",
            "local or manual review fallback",
            "Unchanged Continuation creates no Evolved Blueprint",
            "Never activate silently",
        ):
            assert required in normalized_instructions
        assert "ctxbridge-token-not-printed" not in instructions

        proc.stdin.write(
            _content_length_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        )
        proc.stdin.flush()
        listed = _read_content_length_response(proc.stdout)
        assert [tool["name"] for tool in listed["result"]["tools"]] == list(EXPECTED_TOOLS)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def test_mcp_stdio_content_length_preserves_structured_diff_arguments(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            captured["payload"] = payload
            serialized = json.dumps(payload, sort_keys=True)
            response = {
                "ok": True,
                "tool_name": "create_single_loop_evidence_diff",
                "context_status": "single_loop_evidence_diff_ready",
                "retention": "process_and_discard",
                "retained_artifacts": [],
                "content_specific_delta": "dominant correlated outcomes" in serialized,
            }
            data = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qcoder",
            "context-bridge",
            "mcp",
            "serve",
            "--token-file",
            str(token_file),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(
            _content_length_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
        )
        proc.stdin.flush()
        initialized = _read_content_length_response(proc.stdout)
        assert initialized["result"]["serverInfo"]["name"] == "qcoder-context-bridge"
        arguments = {
            "artifact_text": "Share-safe current evidence summary.",
            "before": {
                "goal": "verify whether the external result is consistent with the intended correlation pattern",
                "evidence": "circuit intent and readiness checks were documented",
                "unresolved": "no result evidence had yet been supplied",
                "assumptions": "external simulator configuration was appropriate",
            },
            "after": {
                "result_evidence": "user reports dominant correlated outcomes in a compact share-safe summary",
                "unresolved": "raw counts and independent execution verification were not supplied",
                "assumptions": "the compact result summary accurately reflects the external run",
            },
        }
        proc.stdin.write(
            _content_length_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "create_single_loop_evidence_diff",
                        "arguments": arguments,
                    },
                }
            )
        )
        proc.stdin.flush()
        called = _read_content_length_response(proc.stdout)
        structured = called["result"]["structuredContent"]
        assert structured["ok"] is True
        assert structured["content_specific_delta"] is True
        forwarded = captured["payload"]
        assert isinstance(forwarded, dict)
        assert isinstance(forwarded["before"], dict)
        assert isinstance(forwarded["after"], dict)
        assert forwarded["after"]["result_evidence"] == arguments["after"]["result_evidence"]
        assert forwarded["before"]["unresolved"] == arguments["before"]["unresolved"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        server.shutdown()
        server.server_close()


def test_smoke_without_token_reports_sanitized_category(tmp_path: Path) -> None:
    result = run_smoke(
        base_url="https://example.invalid", token_file=tmp_path / "missing-token.txt"
    )
    assert result["ok"] is False
    assert result["token_file_category"] == "token_file_missing"
    assert result["token_printed"] is False


def _successful_smoke_payload(tool_name: str) -> dict[str, object]:
    statuses = {
        "get_guided_evidence_context": "assistant_context_ready",
        "create_prompt_context": "prompt_context_ready",
        "create_evidence_context_pack": "evidence_context_pack_ready",
        "create_context_session_card": "context_session_card_ready",
        "create_run_readiness_card": "run_readiness_card_ready",
        "create_result_review_context_card": "result_review_context_card_ready",
        "create_next_check_plan": "next_check_plan_ready",
        "create_single_loop_evidence_diff": "single_loop_evidence_diff_ready",
    }
    return {
        "ok": True,
        "adapter_status_category": "success_2xx",
        "tool_name": tool_name,
        "context_status": statuses[tool_name],
        "retention": "process_and_discard",
        "retained_artifacts": [],
    }


def test_default_smoke_is_concise_and_uses_one_bounded_network_call(
    monkeypatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    network_calls: list[str] = []

    def fake_post(**kwargs: object) -> dict[str, object]:
        tool_name = str(kwargs["tool_name"])
        if "OPENQASM" in str(kwargs["artifact_text"]):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        network_calls.append(tool_name)
        return _successful_smoke_payload(tool_name)

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", fake_post)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file)

    assert result["ok"] is True
    assert result["connection_status_category"] == "ready"
    assert result["token_accepted"] == "yes"
    assert result["tools_discovered"] == 12
    assert result["tools_visible"] == list(EXPECTED_TOOLS)
    assert result["bounded_call_passed"] is True
    assert result["unsafe_input_rejected"] is True
    assert network_calls == ["create_context_session_card"]


def test_default_smoke_human_output_and_json_compatibility(monkeypatch, tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    result = {
        "ok": True,
        "connection_status_category": "ready",
        "token_accepted": "yes",
        "tools_discovered": 8,
        "metadata_only": True,
    }
    monkeypatch.setattr(context_bridge_mcp, "run_smoke", lambda **_kwargs: result)

    human = io.StringIO()
    with redirect_stdout(human):
        rc = context_bridge_mcp.main(["mcp", "smoke", "--token-file", str(token_file)])
    assert rc == 0
    assert human.getvalue().splitlines() == [
        "Context Bridge connection: ready",
        "Token accepted: yes",
        "Tools discovered: 8",
    ]

    structured = io.StringIO()
    with redirect_stdout(structured):
        rc = context_bridge_mcp.main(["mcp", "smoke", "--token-file", str(token_file), "--json"])
    assert rc == 0
    assert json.loads(structured.getvalue()) == result


def test_full_smoke_stops_prompt_matrix_on_rate_limit_without_retrying_or_rejecting_token(
    monkeypatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    prompt_modes_called: list[object] = []

    def fake_post(**kwargs: object) -> dict[str, object]:
        tool_name = str(kwargs["tool_name"])
        artifact_text = str(kwargs["artifact_text"])
        if tool_name not in EXPECTED_TOOLS:
            return context_bridge_mcp.safe_error("unknown_tool")
        if kwargs.get("artifact_kind") == "server_artifact_id":
            return context_bridge_mcp.safe_error("unsupported_artifact_kind")
        if kwargs.get("mode") == "diagnose":
            return context_bridge_mcp.safe_error("invalid_prompt_context_mode")
        if tool_name == "create_single_loop_evidence_diff" and kwargs.get("after") is None:
            return context_bridge_mcp.safe_error("missing_explicit_diff_side")
        if "OPENQASM" in artifact_text or artifact_text.startswith("/home/"):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        if tool_name == "create_prompt_context":
            prompt_modes_called.append(kwargs.get("mode"))
            if len(prompt_modes_called) == 4:
                return {
                    "ok": False,
                    "adapter_status_category": "http_429",
                    "error_category": "rate_limited",
                    "retry_after_category": "seconds",
                    "retention": "process_and_discard",
                    "retained_artifacts": [],
                }
        return _successful_smoke_payload(tool_name)

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", fake_post)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file, full=True)

    assert result["ok"] is False
    assert result["diagnostic_status_category"] == "rate_limit_pause_required"
    assert result["retry_after_category"] == "seconds"
    assert result["token_onboarding_failure"] is False
    assert prompt_modes_called == [None, "explain", "review", "revise"]
    assert result["cases"]["prompt_mode_troubleshoot_allowed"]["status_category"] == (
        "not_run_rate_limit_pause"
    )
    assert result["cases"]["prompt_mode_plan_next_checks_allowed"]["status_category"] == (
        "not_run_rate_limit_pause"
    )


def test_retry_after_is_categorized_without_automatic_retry(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    calls = 0

    def rate_limited(_request: object, timeout: int = 20) -> object:
        nonlocal calls
        calls += 1
        body = io.BytesIO(
            json.dumps({"ok": False, "error_category": "rate_limited"}).encode("utf-8")
        )
        raise urllib.error.HTTPError(
            "https://example.invalid",
            429,
            "Too Many Requests",
            {"Retry-After": "30"},
            body,
        )

    payload = post_context_bridge(
        base_url="https://example.invalid",
        token_file=token_file,
        tool_name="create_prompt_context",
        artifact_text="Share-safe current evidence summary.",
        opener=rate_limited,
    )

    assert calls == 1
    assert payload["adapter_status_category"] == "http_429"
    assert payload["retry_after_category"] == "seconds"


def test_full_smoke_does_not_call_prompt_modes_when_default_prompt_is_rate_limited(
    monkeypatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    prompt_calls: list[object] = []
    context_session_calls = 0

    def fake_post(**kwargs: object) -> dict[str, object]:
        nonlocal context_session_calls
        tool_name = str(kwargs["tool_name"])
        artifact_text = str(kwargs["artifact_text"])
        if tool_name not in EXPECTED_TOOLS:
            return context_bridge_mcp.safe_error("unknown_tool")
        if kwargs.get("artifact_kind") == "server_artifact_id":
            return context_bridge_mcp.safe_error("unsupported_artifact_kind")
        if kwargs.get("mode") == "diagnose":
            return context_bridge_mcp.safe_error("invalid_prompt_context_mode")
        if tool_name == "create_single_loop_evidence_diff" and kwargs.get("after") is None:
            return context_bridge_mcp.safe_error("missing_explicit_diff_side")
        if "OPENQASM" in artifact_text or artifact_text.startswith("/home/"):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        if tool_name == "create_context_session_card":
            context_session_calls += 1
        if tool_name == "create_prompt_context":
            prompt_calls.append(kwargs.get("mode"))
            return {
                "ok": False,
                "adapter_status_category": "http_429",
                "error_category": "rate_limited",
                "retry_after_category": "http_date",
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        return _successful_smoke_payload(tool_name)

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", fake_post)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file, full=True)

    assert context_session_calls == 2
    assert prompt_calls == [None]
    assert result["diagnostic_status_category"] == "rate_limit_pause_required"
    assert result["retry_after_category"] == "http_date"
    assert result["token_onboarding_failure"] is False


def test_full_smoke_stops_on_hard_token_rejection(monkeypatch, tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    _write_token(token_file)
    calls = 0

    def rejected(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        if "OPENQASM" in str(kwargs["artifact_text"]):
            return context_bridge_mcp.safe_error("forbidden_input_value")
        calls += 1
        return {
            "ok": False,
            "adapter_status_category": "http_401",
            "error_category": "token_rejected",
            "retention": "process_and_discard",
            "retained_artifacts": [],
        }

    monkeypatch.setattr(context_bridge_mcp, "post_context_bridge", rejected)
    result = run_smoke(base_url="https://example.invalid", token_file=token_file, full=True)

    assert calls == 1
    assert result["diagnostic_status_category"] == "token_rejected"
    assert result["token_onboarding_failure"] is True
    assert result["token_accepted"] == "no"
