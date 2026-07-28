from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import ntpath
import os
from pathlib import Path
import posixpath
import stat
import sys
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from qcoder import __version__
from qcoder.algorithm_blueprint import (
    ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS,
    ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS,
    ALGORITHM_BLUEPRINT_TOOL_NAMES,
    ALGORITHM_BLUEPRINT_TOOL_REQUIRED_FIELDS,
    CONFIRMATION_STATES,
    EVIDENCE_COVERAGE_VALUES,
    ORIGIN_VALUES,
    PROFILE_IDS,
    algorithm_blueprint_contract_snapshot,
    compact_selected_python_source_evidence_for_hosted,
)
from qcoder.blueprint_decisions import (
    ACTION_IDS,
    CONSTRUCTION_POLICY_PATTERNS,
    DECISION_LOOP_DISABLED,
    DECISION_LOOP_GATE,
    GENERATION_EFFECTS,
    LOGICAL_RESOURCE_ARCHITECTURES,
    PROFILE_DECISION_CATALOG_VERSION,
    QISKIT_CONSTRUCTION_FORMS,
    RESOLUTION_CONTEXTS,
    RESOLUTION_PHASES,
    RESOLUTION_STATES,
    USER_DISPOSITIONS,
    build_resource_architecture,
    catalog_entries,
    unpack_decision_record_set,
)
from qcoder.context_loop import (
    CONTEXT_LOOP_DISABLED,
    CONTEXT_LOOP_GATE,
    DEVELOPMENT_STAGES,
    GENERATION_POSTURES,
    PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS,
    RELATIONSHIP_TYPES,
    STAGE_AVAILABILITY_VALUES,
    STAGE_IDENTITY_STATUSES,
    attach_portable_proposal_parent_resupply,
    attach_portable_proposal_resupply,
    build_portable_current_build_context,
    build_request_baseline,
    canonical_context_bridge_request_sha256,
    context_loop_contract_snapshot,
    portable_current_build_context_error,
    share_safe_request_baseline,
)
from qcoder.current_loop_coordinator import coordinator_contract_snapshot
from qcoder.current_loop_checkpoint_input import (
    CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
    CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION,
    CHECKPOINT_INPUT_SCHEMA_ID,
    CHECKPOINT_INPUT_SCHEMA_VERSION,
)
from qcoder.current_loop import (
    CurrentLoopError,
    canonical_operation_request_sha256,
    expand_next_loop_seed,
)
from qcoder.development_evidence import (
    ALIGNMENT_STATUSES,
    CHOICE_ORIGINS,
    EVIDENCE_CONFIDENCE_LABELS as DECISION_EVIDENCE_CONFIDENCE_LABELS,
    RELATIONSHIP_DECLARATION_STATES,
)

DEFAULT_BASE_URL = "https://preview-api.qcoder.ai"
ROUTE_PATH = "/v0/internal/hosted-mcp/context"
SESSION_ARTIFACT_REFERENCE_PATTERN = r"^session-artifact-[0-9a-f]{16,64}$"
EXPECTED_TOOLS = (
    "get_guided_evidence_context",
    "create_prompt_context",
    "create_evidence_context_pack",
    "create_context_session_card",
    "create_run_readiness_card",
    "create_result_review_context_card",
    "create_next_check_plan",
    "create_single_loop_evidence_diff",
    *ALGORITHM_BLUEPRINT_TOOL_NAMES,
)
CLIENT_BINDING_SCHEMA_ID = "qcoder.connected_assistant.client_binding"
CLIENT_BINDING_SCHEMA_VERSION = 2
CLIENT_BINDING_CONTRACT_ID = "qcoder.connected_assistant.client_binding.v2"
CLIENT_ACTIVATION_INSTRUCTIONS = """QCODER ASSISTANT SURFACES
qCoder provides exactly twelve Context Bridge MCP tools. They are qCoder's bounded hosted
capability and evidence surface for source review, circuit analysis, result review, Blueprint
preparation, and the other supported bounded operations. qcoder current-loop is qCoder's separate
supported local orchestration and continuity surface for an active build. Current Loop is
intentionally not one of the twelve MCP tools; both surfaces belong to qCoder.

WORKSTYLE ROUTING
Available but inactive: when there is no explicit qCoder request, no accepted qCoder activation
offer, and no explicit bounded qCoder capability request, perform no qCoder operation. Do not
invoke the coordinator, call a qCoder MCP domain tool, or create qCoder state. A proactive offer
is permitted but must not activate qCoder without acceptance.

Single capability: for an explicit bounded qCoder capability request without active-build
activation, use the applicable existing Context Bridge MCP tool. Do not invoke qcoder current-loop,
activate a complete Context Loop, attach the bounded result to loop lineage, transform it into
governing intent, or create continuity. Direct bounded use of one applicable MCP tool is legitimate
in this workstyle.

Active build: explicit wording equivalent to “Use qCoder for this build.” or explicit acceptance
of a qCoder activation offer routes to the local coordinator first. Then follow
coordinator-directed local and hosted actions. Generation posture is a later generation choice,
not a workstyle route.

ACTIVE-BUILD LOCAL EXECUTION
Execute the supplied coordinator_prefix argv through the client's ordinary local command-execution
capability. That capability may be displayed as terminal, shell, Bash, or another client-specific
name; qCoder does not depend on its displayed name. Do not compare coordinator_prefix against the
twelve-tool catalog: its absence from that catalog is intentional. Invoking the exact declared
coordinator is the supported qCoder active-build route, not a local fallback, customer-authored
CLI choreography, or an improvised review. The customer never types the command. Do not perform
the requested IDE write or run before the coordinator reaches its separate authority checkpoint.

Hosted operations during active build: the coordinator may invoke or direct existing Context
Bridge operations. Follow those directions and never invent a hosted-tool order. Do not call one
of the twelve domain tools in place of local coordinator activation. This restriction does not
prohibit legitimate direct use of one applicable MCP tool in the single-capability workstyle.

REQUEST FIDELITY
Preserve the complete governing customer message verbatim as original_request. Do not summarize,
abbreviate, paraphrase, reword, or omit activation wording, posture wording, constraints, choices,
review preferences, continuation wording, or Blueprint boundaries. Extracting activation,
posture, constraints, choices, a label, or an assistant interpretation is additive and never
removes wording from original_request. Stop before activation if exact transfer cannot be
completed.

ACTIVATION PROTOCOL
qCoder Current Loop is opt-in: do nothing unless the user explicitly asks to use qCoder for the
current build or explicitly accepts an activation offer. Never activate silently. For a task
received before activation, stage the exact complete message through activate without --approve.
Use inline transfer for concise text and prefer explicit --request-stdin for longer or multiline
text so no project file is created; never ask the customer to create a request file.
Use qCoder's returned complete capture when asking: “Use qCoder for this build and preserve the
following exact Request Baseline?” Do not ask the user to repeat the task, and never use a later
one-word “Yes” as original_request. After approval, invoke activate with --approve only; let qCoder
reuse the pending capture. Do not resend or reconstruct the request. Posture remains separate
unless explicitly supplied with its own attributable authority.

CHECKPOINT PROTOCOL
Conversational approval and canonical confirmation are distinct. After the user approves a
checkpoint, transmit that authority through the exact required_authority_input. Follow
supported_next_action and next_invocation exactly; do not infer or reconstruct an invocation from
chat history. Never repeat an identical invocation after an unchanged checkpoint without new
authority or corrected input. If the same checkpoint remains after authority was transmitted,
report awaiting_confirmation_fields and stop instead of searching for state. Workspace freshness
is not intent. Ground posture in explicit wording, lineage, or an assistant recommendation the
user explicitly accepts. Posture is a bounded enumerated authority decision: present only qCoder's
supported values naturally, never infer a default, and transmit only the selected enum through the
generated invocation. It does not use arbitrary checkpoint-input transport. Preserve exact
user-stated decision answers. Exploratory first pass is not a full Generation Context Pack;
Blueprint-guided generation stops at the decision_resolution checkpoint and uses the exact
decision-disposition authority channel. A posture transition requires its separate explicit
authority and must not rewrite the Working Blueprint.
Never embed arbitrary user-approved free text in shell argv. When qCoder requests checkpoint
input, consume the complete checkpoint_input_construction object in that exact coordinator
result. Copy its fixed_payload unchanged and supply only the declared new value fields. Never
invent or independently duplicate schema, operation, checkpoint kind, phase, loop, workspace,
revision, digest, canonicalization, or transport metadata. Use the construction's exact stdin or
file staging invocation, present every complete staged value, and then transmit approval only.
Never reconstruct, quote, or reserialize a staged value from conversation. Never inspect package
source, qcoder.__file__, proof records, transcripts, or .qcoder to derive construction values.
The customer never creates the machine input or types the command. A correction replaces the
pending set and requires a new display and approval. Every active result's
next_invocation is authoritative. Every actionable result must provide a non-null
permitted_input_source and bounded input semantics; if it does not, stop rather than infer,
reconstruct, inspect source, inspect proof records, search transcripts, or inspect .qcoder. A
machine-readable no_action_disposition means no invocation is currently permitted. At
next_loop_ready the completed build's governing-change branch is closed: use only the
qCoder-managed start-next route or stop with no further action.

IDE WORK AND ARTIFACT HANDOFF
After IDE write/run authority, perform only the user-authorized development work. Retain exact
paths returned by your own write or modify operations; no directory orientation is needed before
creating a new file. Register only those retained exact paths or paths the user explicitly
selected, with truthful assistant_created, assistant_modified, or user_selected provenance.
Never inspect .qcoder, and exclude .qcoder from every ordinary project inspection. Do not use a
glob, find, directory listing, Git status, repository map, or search result as the qCoder review
set. The Quick Demo requires no workspace discovery: retain the exact source and QASM paths
returned by the two IDE write operations. Ordinary inspection of relevant non-qCoder project
files may occur only under the user's development request and the IDE/client permission model;
that inspection does not register a file or authorize qCoder review. After registration, present
the exact visible candidate set for separate artifact-review authorization.
"""

CLIENT_AUTHORITY_AND_PROHIBITED_INSTRUCTIONS = """AUTHORITY BOUNDARIES
Keep qCoder activation and exact-baseline confirmation, posture authority, IDE write/run
permission, exact artifact-review permission, and governing-change confirmation separate. qCoder
activation does not grant IDE permission to write or run and does not authorize artifact review.
Keep qCoder activation, IDE write/run permission, exact artifact-review permission, and
governing-change confirmation distinct. Present exact artifact candidates before review. Never
confirm a governing proposal without proposal-specific explicit confirmation. Offer Review in
this IDE, optional passive Build Review, and Continue without visual review. Unchanged
Continuation creates no Evolved Blueprint.

PROHIBITED ACTIONS
Never activate silently. Never run `which` or `where`, inspect PATH or environment variables,
or traverse the filesystem for a runtime. Never inspect Cursor, Claude Code, or Codex configuration
to rediscover the runtime. Never list, browse, or inspect the executable path's parent directories.
Never enumerate, list, search, open, read, copy, hash, parse, inspect, summarize, or
reverse-engineer .qcoder or anything below it. Never search for canonical state, inspect parent or
home-directory qCoder state, or inspect sibling repositories. Never use workspace discovery to
construct a qCoder review set, turn a listing or search result into candidates, or infer
neighboring artifacts. Never open, read, print, copy, hash, or validate the token-file contents.
The declared paths authorize only invoking the declared qCoder runtime and passing its token-file
path; they grant no general access outside the active workspace. Stop on authentication,
entitlement, or hosted-service failure. Never manually sequence Context Bridge tools for an active
build and never substitute a local or manual review fallback. Do not replace coordinator truth
with a locally assembled review. Never reconstruct canonical artifacts, transfer raw artifacts,
inspect client configuration, search transcripts, or inspect source or package files to recover
canonical values.
"""


def _resolved_configuration_path(
    value: str | Path,
    *,
    path_style: str | None = None,
    preserve_symlink_identity: bool = False,
) -> str:
    style = path_style or os.name
    if style == os.name:
        path = Path(value).expanduser()
        if preserve_symlink_identity:
            return str(path.absolute())
        return str(path.resolve(strict=False))
    if style == "nt":
        return ntpath.abspath(str(value))
    if style == "posix":
        return posixpath.abspath(str(value))
    raise ValueError("configured_runtime_path_style_invalid")


def build_client_binding_descriptor(
    *,
    coordinator_prefix: list[str],
) -> dict[str, Any]:
    contract_digest = hashlib.sha256(
        json.dumps(
            coordinator_contract_snapshot(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "client_binding_contract": {
            "schema_id": CLIENT_BINDING_SCHEMA_ID,
            "schema_version": CLIENT_BINDING_SCHEMA_VERSION,
            "contract_id": CLIENT_BINDING_CONTRACT_ID,
            "package_version": __version__,
            "coordinator_contract_digest": contract_digest,
            "checkpoint_input_contract": {
                "schema_id": CHECKPOINT_INPUT_SCHEMA_ID,
                "schema_version": CHECKPOINT_INPUT_SCHEMA_VERSION,
                "construction_schema_id": CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_ID,
                "construction_schema_version": (CHECKPOINT_INPUT_CONSTRUCTION_SCHEMA_VERSION),
                "transports": ["stdin", "file"],
                "approval_only_promotion": True,
                "literal_free_text_in_argv": False,
                "qcoder_owns_fixed_construction_metadata": True,
                "assistant_supplies_only_declared_new_values": True,
            },
            "qcoder_domain_tool_count": len(EXPECTED_TOOLS),
            "supported_workstyles": [
                "available_inactive",
                "single_capability",
                "active_build",
            ],
            "active_build_activation_phrase_category": (
                "explicit_use_qcoder_for_this_build_or_accepted_offer"
            ),
            "required_client_capability": "ordinary_local_command_execution",
            "surfaces": {
                "hosted_capability": {
                    "transport": "mcp_tools",
                    "tool_count": len(EXPECTED_TOOLS),
                    "single_capability_supported": True,
                },
                "local_orchestration": {
                    "transport": "local_command",
                    "command_prefix": list(coordinator_prefix),
                    "orchestration_surface_is_not_an_mcp_tool": True,
                    "customer_never_types_command": True,
                },
            },
            "workstyle_routes": {
                "available_inactive": {
                    "trigger": "no_explicit_qcoder_request",
                    "action": "none",
                },
                "single_capability": {
                    "trigger": "explicit_bounded_capability_request",
                    "action": "use_applicable_mcp_tool",
                    "activates_context_loop": False,
                },
                "active_build": {
                    "trigger": "explicit_use_qcoder_for_this_build_or_accepted_offer",
                    "action": "invoke_local_coordinator_first",
                    "then": "follow_coordinator_directed_local_and_hosted_actions",
                },
            },
            "manual_active_build_tool_sequencing_prohibited": True,
        }
    }


def build_client_activation_instructions(
    *,
    base_url: str,
    token_file: str | Path,
    python_executable: str | Path | None = None,
    path_style: str | None = None,
) -> str:
    executable = _resolved_configuration_path(
        python_executable or sys.executable,
        path_style=path_style,
        preserve_symlink_identity=True,
    )
    token_path = _resolved_configuration_path(token_file, path_style=path_style)
    runtime = {
        "python_executable": executable,
        "qcoder_version": __version__,
        "coordinator_prefix": [
            executable,
            "-m",
            "qcoder",
            "current-loop",
        ],
        "base_url": str(base_url),
        "token_file_path": token_path,
        "transport_arguments": [
            "--base-url",
            str(base_url),
            "--token-file",
            token_path,
        ],
    }
    binding = build_client_binding_descriptor(
        coordinator_prefix=runtime["coordinator_prefix"],
    )
    runtime_block = json.dumps(runtime, indent=2, sort_keys=False)
    binding_block = json.dumps(binding, indent=2, sort_keys=False)
    return (
        f"{CLIENT_ACTIVATION_INSTRUCTIONS}\n"
        "CONFIGURED RUNTIME\n"
        "Use the supplied python_executable exactly and extend coordinator_prefix without replacing "
        "its executable. Pass transport_arguments exactly where supported. As a positive setup "
        "check, first execute coordinator_prefix with --help through the ordinary local "
        "command-execution capability; stop if it does not expose qCoder current-loop.\n\n"
        "Configured qCoder runtime (JSON values are exact operational metadata; "
        "coordinator_prefix is an argv array):\n"
        f"{runtime_block}\n\n"
        "Use the coordinator_prefix argv array exactly as supplied.\n\n"
        "Connected-assistant client binding (JSON values are the versioned routing descriptor):\n"
        f"{binding_block}\n\n"
        f"{CLIENT_AUTHORITY_AND_PROHIBITED_INSTRUCTIONS}"
    )


TOOL_ALIASES = {
    "get_context_from_share_safe_artifact": "get_guided_evidence_context",
    "build_assistant_prompt_context": "create_prompt_context",
}
_CONTEXT_LOOP_EVIDENCE_FIELDS = {
    "context_loop",
    "profile_id",
    "current_lineage_reference",
    "request_baseline",
    "request_share_safe_summary",
    "request_text_share_safe",
    "assistant_interpretation",
    "profile_suggestions",
    "generation_posture",
    "exploratory_authorization",
    "exploratory_constraints",
    "exploratory_prohibitions",
    "unresolved_assistant_choices",
    "working_blueprint",
    "generation_context",
    "python_manifestation",
    "circuit_manifestation",
    "result_manifestation",
    "stage_availability",
    "stage_identities",
    "decision_evidence_lineage",
    "current_build_context",
    "carry_forward_proposal",
    "evolved_blueprint",
    "decision_records",
    "evidence_parent_artifacts",
    "artifact_references",
    "missing_stage_requests",
    "remaining_uncertainty",
    "generation_context_effect",
}
PROMPT_CONTEXT_MODES = frozenset(
    {
        "explain",
        "review",
        "revise",
        "troubleshoot",
        "plan_next_checks",
    }
)
TOOL_INPUT_FIELDS = {
    "get_guided_evidence_context": frozenset({"artifact_text", "artifact_kind", "client_context"}),
    "create_prompt_context": frozenset(
        {"artifact_text", "artifact_kind", "client_context", "mode"}
    ),
    "create_evidence_context_pack": frozenset(
        {"artifact_text", "artifact_kind", "client_context", "current_goal", "evidence_basis"}
    ),
    "create_context_session_card": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
            *_CONTEXT_LOOP_EVIDENCE_FIELDS,
        }
    ),
    "create_run_readiness_card": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
            *_CONTEXT_LOOP_EVIDENCE_FIELDS,
        }
    ),
    "create_result_review_context_card": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "share_safe_evidence_summary",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
            *_CONTEXT_LOOP_EVIDENCE_FIELDS,
        }
    ),
    "create_next_check_plan": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "evidence_basis",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
            *_CONTEXT_LOOP_EVIDENCE_FIELDS,
        }
    ),
    "create_single_loop_evidence_diff": frozenset(
        {
            "artifact_text",
            "artifact_kind",
            "client_context",
            "current_goal",
            "before",
            "after",
            *_CONTEXT_LOOP_EVIDENCE_FIELDS,
        }
    ),
    **ALGORITHM_BLUEPRINT_TOOL_INPUT_FIELDS,
}
# Current Build Context is composed only after intent and blueprint review. The
# Intent Card must not advertise an opt-in that its protected stage cannot use.
TOOL_INPUT_FIELDS["create_algorithm_intent_card"] = TOOL_INPUT_FIELDS[
    "create_algorithm_intent_card"
] - frozenset({"context_loop"})
LOCAL_SELECTED_BUNDLE_FIELD = "use_selected_portable_bundle"
LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD = "use_selected_next_loop_seed"
TOOL_INPUT_FIELDS["create_implementation_blueprint"] = TOOL_INPUT_FIELDS[
    "create_implementation_blueprint"
] | frozenset({LOCAL_SELECTED_BUNDLE_FIELD})
TOOL_INPUT_FIELDS["create_generation_context_pack"] = TOOL_INPUT_FIELDS[
    "create_generation_context_pack"
] | frozenset({LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD})
TOOL_REQUIRED_FIELDS = {
    tool_name: ("artifact_text",)
    for tool_name in EXPECTED_TOOLS
    if tool_name not in ALGORITHM_BLUEPRINT_TOOL_NAMES
}
TOOL_REQUIRED_FIELDS.update(ALGORITHM_BLUEPRINT_TOOL_REQUIRED_FIELDS)
for _context_loop_tool in (
    "create_context_session_card",
    "create_result_review_context_card",
    "create_single_loop_evidence_diff",
):
    TOOL_REQUIRED_FIELDS[_context_loop_tool] = ()
EVIDENCE_CONFIDENCE_LABELS = (
    (
        "observed",
        "Observed",
        "Information directly present in the explicitly supplied circuit, result, or workflow evidence.",
    ),
    (
        "user_provided",
        "User-provided",
        "Information asserted or entered by the user but not independently verified by qCoder.",
    ),
    (
        "inferred",
        "Inferred",
        "A bounded interpretation derived from explicitly supplied evidence.",
    ),
    (
        "assumed",
        "Assumed",
        "A premise used to organize or interpret the supplied evidence but not established by it.",
    ),
    (
        "not_proven",
        "Not proven",
        "A statement, explanation, property, outcome, or conclusion that the supplied evidence does not establish.",
    ),
    (
        "suggested_next_check",
        "Suggested next check",
        "An ordered, user-controlled recommendation for obtaining more evidence or resolving uncertainty.",
    ),
)
EVIDENCE_REVIEW_ARTIFACT_DISCRIMINATORS = {
    "get_guided_evidence_context": {"field": "context_status", "value": "assistant_context_ready"},
    "create_prompt_context": {"field": "context_status", "value": "prompt_context_ready"},
    "create_evidence_context_pack": {"field": "pack_type", "value": "share_safe_current_evidence"},
    "create_context_session_card": {"field": "card_type", "value": "share_safe_current_session"},
    "create_run_readiness_card": {
        "field": "card_type",
        "value": "share_safe_current_run_readiness",
    },
    "create_result_review_context_card": {
        "field": "card_type",
        "value": "share_safe_current_result_review",
    },
    "create_next_check_plan": {
        "field": "plan_type",
        "value": "bounded_current_request_next_checks",
    },
    "create_single_loop_evidence_diff": {
        "field": "diff_type",
        "value": "explicit_before_after_current_loop",
    },
    **ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS,
}
EVIDENCE_REVIEW_BOUNDARIES = (
    "current artifact and current session only",
    "explicitly supplied evidence only; no hidden lookup",
    "process-and-discard with no retained artifacts",
    "no project memory, evidence history, or multi-run comparison",
    "no repository access or file editing",
    "no autonomous execution",
    "no correctness verification, runtime or fidelity prediction, backend ranking, or quantum-advantage claim",
)
DEFAULT_ARTIFACT_KIND = "share_safe_evidence_summary"
MAX_ARTIFACT_TEXT_CHARS = 20_000
MAX_DECISION_LOOP_PAYLOAD_CHARS = 131_072
MAX_CONTEXT_LOOP_PAYLOAD_CHARS = 131_072
FORBIDDEN_TEXT_MARKERS = (
    "openqasm",
    "qreg ",
    "creg ",
    "counts=",
    '"counts"',
    "'counts'",
    "/home/",
    "\\users\\",
    "c:\\",
    "../",
    "repo_path",
    "file_path",
    "repository_root",
    "directory_root",
    "workspace_root",
    "source_code",
    '"command"',
    "raw_qasm",
    "raw_counts",
    "provider_result",
    "result_payload",
    "raw_provider_result",
    "artifact_id",
    "stored_card_id",
    "prior_session_id",
    "session_id",
    "raw_source",
    "notebook",
    ".ipynb",
    "project memory",
    "prior run history",
    "multi-run comparison",
    "remember it",
    "compare with prior run",
    "backend selection",
    "rank backends",
    "optimize shots",
    "execute this",
    "edit code",
)
FORBIDDEN_PAYLOAD_FIELDS = frozenset(
    {
        "file_path",
        "path",
        "workspace_path",
        "workspace_root",
        "repository_root",
        "directory_root",
        "source_path",
        "notebook_path",
        "raw_source",
        "source_code",
        "source_excerpt",
        "original_request",
        "raw_circuit",
        "raw_qasm",
        "qasm_text",
        "raw_counts",
        "counts",
        "sampled_bitstrings",
        "provider_result",
        "provider_result_payload",
        "raw_provider_result",
        "result_payload",
        "mcp_payload",
        "stored_card_id",
        "prior_session_id",
        "session_id",
        "artifact_id",
        "command",
        "token",
        "authorization",
    }
)


def default_token_file() -> Path:
    return Path.home() / ".qcoder" / "context-bridge" / "token.txt"


def _load_selected_portable_bundle(
    selected_file: str | Path | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if selected_file is None:
        return None, "selected_portable_bundle_not_configured"
    path = Path(selected_file)
    if not path.is_absolute() or ".." in path.parts:
        return None, "selected_portable_bundle_path_invalid"
    try:
        if path.is_symlink():
            return None, "selected_portable_bundle_symlink_rejected"
        stat_result = path.stat()
    except OSError:
        return None, "selected_portable_bundle_unreadable"
    if not path.is_file():
        return None, "selected_portable_bundle_file_required"
    if path.suffix.lower() != ".json":
        return None, "selected_portable_bundle_type_unsupported"
    if stat_result.st_size > PORTABLE_CURRENT_BUILD_CONTEXT_LIMITS["maximum_selected_file_bytes"]:
        return None, "selected_portable_bundle_file_too_large"
    try:
        raw = path.read_bytes()
        decoded = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "selected_portable_bundle_invalid"
    if not isinstance(decoded, dict):
        return None, "selected_portable_bundle_invalid"
    error = portable_current_build_context_error(decoded)
    if error:
        return None, error
    return decoded, None


def _expand_selected_portable_bundle(
    arguments: dict[str, Any],
    *,
    selected_file: str | Path | None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if arguments.get(LOCAL_SELECTED_BUNDLE_FIELD) is not True:
        return None, None, "selected_portable_bundle_selection_required"
    bundle, bundle_error = _load_selected_portable_bundle(selected_file)
    if bundle_error or bundle is None:
        return None, None, bundle_error
    envelope = bundle.get("transport")
    proposal_parent_resupply = (
        envelope.get("proposal_parent_resupply") if isinstance(envelope, dict) else None
    )
    if isinstance(proposal_parent_resupply, dict):
        allowed_proposal_overlay = {
            LOCAL_SELECTED_BUNDLE_FIELD,
            "algorithm_intent_card",
            "intent_relationship",
            "selected_action",
            "selected_decision_references",
            "proposed_updates",
            "source_finding_references",
            "remaining_uncertainty",
            "generation_context_effect",
            "prospective_derived_artifact_references",
            "proposal_ref",
        }
        if set(arguments) - allowed_proposal_overlay:
            return None, None, "selected_portable_bundle_proposal_overlay_invalid"
        parent_input = proposal_parent_resupply.get("tool_input")
        if not isinstance(parent_input, dict):
            return None, None, "portable_proposal_parent_resupply_input_invalid"
        exact_proposal = deepcopy(parent_input)
        exact_proposal.update(
            {
                key: deepcopy(value)
                for key, value in arguments.items()
                if key != LOCAL_SELECTED_BUNDLE_FIELD
            }
        )
        inherited_error = _inherit_decision_loop_context(
            "create_implementation_blueprint", exact_proposal
        )
        if inherited_error is not None:
            return None, None, inherited_error
        proposal_error = _prepare_current_build_proposal(
            "create_implementation_blueprint", exact_proposal
        )
        if proposal_error is not None:
            return None, None, proposal_error
        digest = canonical_context_bridge_request_sha256(
            tool_name="create_implementation_blueprint",
            tool_input=exact_proposal,
        )
        return exact_proposal, digest, None

    allowed_confirmation_overlay = {
        LOCAL_SELECTED_BUNDLE_FIELD,
        "proposal_ref",
        "selected_action",
        "resolution_confirmation",
    }
    if set(arguments) - allowed_confirmation_overlay:
        return None, None, "selected_portable_bundle_overlay_invalid"
    transport = bundle.get("confirmation_transport")
    exact_input: object
    stored_digest: object
    if isinstance(transport, dict):
        exact_input = transport.get("tool_input")
        stored_digest = transport.get("canonical_request_sha256")
    else:
        proposal_resupply = (
            envelope.get("proposal_resupply") if isinstance(envelope, dict) else None
        )
        if not isinstance(proposal_resupply, dict):
            return None, None, "portable_confirmation_transport_invalid"
        proposed_input = proposal_resupply.get("tool_input")
        proposal = proposal_resupply.get("carry_forward_proposal")
        confirmation = arguments.get("resolution_confirmation")
        if not isinstance(proposed_input, dict) or not isinstance(proposal, dict):
            return None, None, "portable_proposal_resupply_input_invalid"
        if (
            not isinstance(confirmation, dict)
            or confirmation.get("confirmed") is not True
            or not isinstance(confirmation.get("confirmed_by"), str)
            or not confirmation["confirmed_by"].strip()
        ):
            return None, None, "portable_confirmation_explicit_marker_required"
        exact_input = deepcopy(proposed_input)
        for field in (
            "selected_decision_references",
            "source_finding_references",
            "proposed_updates",
            "prospective_derived_artifact_references",
        ):
            exact_input.pop(field, None)
        exact_input.update(
            {
                "resolution_phase": "confirm",
                "proposal_ref": proposal.get("proposal_ref"),
                "decision_resolution_pack": deepcopy(proposal),
                "resolution_confirmation": deepcopy(confirmation),
                "confirmation_payload": deepcopy(
                    proposal.get("explicit_confirmation_requirements", {}).get(
                        "confirmation_payload"
                    )
                ),
            }
        )
        stored_digest = canonical_context_bridge_request_sha256(
            tool_name="create_implementation_blueprint",
            tool_input=exact_input,
        )
    if not isinstance(exact_input, dict):
        return None, None, "portable_confirmation_tool_input_invalid"
    for field in ("proposal_ref", "selected_action", "resolution_confirmation"):
        if arguments.get(field) != exact_input.get(field):
            return None, None, f"selected_portable_bundle_{field}_mismatch"
    digest = canonical_context_bridge_request_sha256(
        tool_name="create_implementation_blueprint",
        tool_input=exact_input,
    )
    if digest != stored_digest:
        return None, None, "portable_confirmation_request_digest_mismatch"
    return dict(exact_input), digest, None


def safe_error(error_category: str, *, status_category: str = "adapter_rejected") -> dict[str, Any]:
    payload = {
        "ok": False,
        "error_category": error_category,
        "status_category": status_category,
        "retention": "process_and_discard",
        "retained_artifacts": [],
        "token_printed": False,
        "raw_payload_printed": False,
        "raw_response_printed": False,
    }
    if error_category == "working_blueprint_not_decision_ready":
        payload["message"] = (
            "This Working Blueprint does not contain the decision inventory required "
            "for Carry-Forward. Return to the Intent review and create a "
            "decision-loop-confirmed Working Blueprint before generating downstream "
            "evidence."
        )
    return payload


def validate_token_file(token_file: str | Path) -> tuple[bool, str, str]:
    path = Path(token_file)
    if not path.is_file():
        return False, "token_file_missing", ""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return False, "token_file_unreadable", ""
    if os.name != "nt" and mode & 0o077:
        return False, "token_file_permissions_unsafe", ""
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "token_file_unreadable", ""
    if not token:
        return False, "token_file_empty", ""
    if "\n" in token or "\r" in token:
        return False, "token_file_malformed", ""
    return True, "ok", token


def validate_artifact_text(artifact_text: object) -> str:
    if not isinstance(artifact_text, str) or not artifact_text.strip():
        return "artifact_text_missing"
    if len(artifact_text) > MAX_ARTIFACT_TEXT_CHARS:
        return "artifact_text_too_large"
    lowered = artifact_text.lower()
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        return "forbidden_input_value"
    return "ok"


def validate_optional_payload(value: object, *, max_chars: int = MAX_ARTIFACT_TEXT_CHARS) -> str:
    if value is None:
        return "ok"
    try:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return "payload_not_json_serializable"
    if len(serialized) > max_chars:
        return "artifact_text_too_large"
    if _contains_forbidden_payload_field(value):
        return "forbidden_input_value"
    for text_value in _payload_text_values(value):
        lowered = text_value.lower()
        if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
            return "forbidden_input_value"
    return "ok"


def _contains_forbidden_payload_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in FORBIDDEN_PAYLOAD_FIELDS
            or _contains_forbidden_payload_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_payload_field(item) for item in value)
    return False


def _payload_text_values(value: object) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_payload_text_values(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_payload_text_values(item))
        return result
    return [value] if isinstance(value, str) else []


def _has_explicit_side(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(str(nested).strip() for nested in value.values())
    return False


def decode_json(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "error_category": "non_json_response"}
    return (
        decoded
        if isinstance(decoded, dict)
        else {"ok": False, "error_category": "non_object_response"}
    )


def _retry_after_category(value: object) -> str:
    retry_after = str(value or "").strip()
    if not retry_after:
        return "absent"
    if retry_after.isdigit():
        return "seconds"
    if "," in retry_after and ":" in retry_after:
        return "http_date"
    return "present_unparsed"


def _canonical_tool_name(tool_name: str) -> str:
    return TOOL_ALIASES.get(tool_name, tool_name)


def _client_visible_tool_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Expose nested core-contract metadata without changing the service response."""

    if tool_name != "create_run_readiness_card" or payload.get("ok") is not True:
        return payload
    readiness_card = payload.get("readiness_card")
    if not isinstance(readiness_card, dict):
        return payload
    labels = readiness_card.get("evidence_confidence_labels")
    if not isinstance(labels, list) or not labels:
        return payload
    projected = dict(payload)
    projected.setdefault("evidence_confidence_labels", labels)
    return projected


def evidence_review_contract_snapshot() -> dict[str, Any]:
    """Return the sanitized adapter contract mirrored by the protected implementation."""

    return {
        "capability": "Evidence Review",
        "tool_names": list(EXPECTED_TOOLS),
        "prompt_context_modes": sorted(PROMPT_CONTEXT_MODES),
        "confidence_labels": [
            {"value": value, "display": display}
            for value, display, _meaning in EVIDENCE_CONFIDENCE_LABELS
        ],
        "tool_input_fields": {name: sorted(TOOL_INPUT_FIELDS[name]) for name in EXPECTED_TOOLS},
        "required_request_properties": {
            name: list(TOOL_REQUIRED_FIELDS[name]) for name in EXPECTED_TOOLS
        },
        "compatibility_aliases": dict(sorted(TOOL_ALIASES.items())),
        "artifact_discriminators": EVIDENCE_REVIEW_ARTIFACT_DISCRIMINATORS,
        "context_scope": "current_artifact_current_session",
        "retention": "process_and_discard",
        "boundaries": list(EVIDENCE_REVIEW_BOUNDARIES),
        "algorithm_blueprint": algorithm_blueprint_contract_snapshot(),
        "context_loop": context_loop_contract_snapshot(),
    }


def _context_loop_argument_error(
    tool_name: str, arguments: dict[str, Any], artifact_text: object
) -> str | None:
    gate = arguments.get("context_loop")
    if gate not in {None, CONTEXT_LOOP_DISABLED, CONTEXT_LOOP_GATE}:
        return "context_loop_gate_invalid"
    if tool_name == "create_algorithm_intent_card" and gate == CONTEXT_LOOP_GATE:
        return "context_loop_stage_not_supported"
    enabled = gate == CONTEXT_LOOP_GATE
    if not enabled:
        if tool_name in {
            "create_context_session_card",
            "create_result_review_context_card",
            "create_single_loop_evidence_diff",
        } and (not isinstance(artifact_text, str) or not artifact_text.strip()):
            return "artifact_text_missing"
        return None
    if tool_name == "create_context_session_card":
        for field in (
            "request_baseline",
            "working_blueprint",
            "stage_availability",
            "decision_evidence_lineage",
        ):
            if not isinstance(arguments.get(field), dict):
                return f"missing_{field}"
    if tool_name == "create_result_review_context_card" and not isinstance(
        arguments.get("result_manifestation"), dict
    ):
        return "missing_result_manifestation"
    if tool_name == "create_single_loop_evidence_diff":
        for field in ("current_build_context", "decision_evidence_lineage", "decision_records"):
            value = arguments.get(field)
            if value is None or value == [] or value == {}:
                return f"missing_{field}"
    if (
        tool_name == "create_implementation_blueprint"
        and arguments.get("resolution_context") == "current_build_context"
    ):
        for field in ("working_blueprint", "current_build_context"):
            if not isinstance(arguments.get(field), dict):
                return f"missing_{field}"
        parents = arguments.get("evidence_parent_artifacts")
        if not isinstance(parents, list) or not parents:
            return "evidence_parent_artifacts_required"
        if any(not isinstance(parent, dict) for parent in parents):
            return "evidence_parent_artifact_invalid"
    return None


def _compose_request_baseline_handoff(tool_name: str, arguments: dict[str, Any]) -> str | None:
    if (
        tool_name != "create_context_session_card"
        or arguments.get("context_loop") != CONTEXT_LOOP_GATE
    ):
        return None
    existing_baseline = arguments.get("request_baseline")
    if (
        isinstance(existing_baseline, dict)
        and existing_baseline.get("artifact_type") == "request_baseline_handoff"
    ):
        return None
    summary = arguments.get("request_share_safe_summary")
    selected = arguments.get("request_text_share_safe")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(selected, bool):
        return "request_text_share_safe_required"
    if isinstance(existing_baseline, dict):
        reconstructed_text = existing_baseline.get("text")
        if isinstance(reconstructed_text, str) and reconstructed_text.strip() != summary.strip():
            return "conflicting_tool_argument"

    assistant = arguments.get("assistant_interpretation")
    suggestions = arguments.get("profile_suggestions")
    unresolved = arguments.get("open_questions")
    assistant_value = assistant if isinstance(assistant, dict) else {}
    suggestions_value = suggestions if isinstance(suggestions, list) else []
    unresolved_value = unresolved if isinstance(unresolved, list) else []
    reference_seed = json.dumps(
        {
            "request_summary": summary.strip(),
            "request_text_share_safe": selected,
            "assistant_interpretation": assistant_value,
            "profile_suggestions": suggestions_value,
            "unresolved_questions": unresolved_value,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    artifact_ref = f"session-artifact-{hashlib.sha256(reference_seed).hexdigest()[:32]}"
    try:
        baseline = build_request_baseline(
            original_request=summary,
            assistant_interpretation=assistant_value,
            profile_suggestions=suggestions_value,
            unresolved_questions=unresolved_value,
            artifact_ref=artifact_ref,
        )
        arguments["request_baseline"] = share_safe_request_baseline(
            baseline,
            include_selected_verbatim=selected,
            selected_verbatim=summary if selected else None,
            structural_summary=None if selected else summary,
        )
    except ValueError:
        return "request_baseline_handoff_invalid"
    return None


def _portable_decision_records(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    supplied = arguments.get("decision_records")
    if isinstance(supplied, list):
        return [dict(item) for item in supplied if isinstance(item, dict)]
    if isinstance(supplied, dict) and isinstance(supplied.get("records"), list):
        return [dict(item) for item in supplied["records"] if isinstance(item, dict)]
    blueprint = arguments.get("working_blueprint")
    if not isinstance(blueprint, dict):
        return []
    inherited = blueprint.get("blueprint_decision_records")
    if isinstance(inherited, dict) and isinstance(inherited.get("records"), list):
        try:
            return unpack_decision_record_set(inherited)
        except ValueError:
            return []
    return []


def _inherit_decision_loop_context(tool_name: str, arguments: dict[str, Any]) -> str | None:
    parent_field = {
        "create_implementation_blueprint": "algorithm_intent_card",
        "create_generation_context_pack": "implementation_blueprint",
        "create_source_blueprint_alignment_review": "implementation_blueprint",
    }.get(tool_name)
    if parent_field is None:
        return None
    parent = arguments.get(parent_field)
    if not isinstance(parent, dict):
        return None
    record_set = parent.get("blueprint_decision_records")
    if not isinstance(record_set, dict):
        if (
            tool_name == "create_generation_context_pack"
            and arguments.get("decision_loop") == DECISION_LOOP_GATE
        ):
            return "working_blueprint_not_decision_ready"
        return None
    parent_loop = parent.get("decision_loop")
    inherited_gate = parent_loop.get("gate") if isinstance(parent_loop, dict) else None
    if inherited_gate != DECISION_LOOP_GATE:
        return "parent_decision_loop_invalid"
    inherited = {
        "decision_loop": inherited_gate,
        "profile_decision_catalog_version": (
            parent_loop.get("catalog_version")
            if isinstance(parent_loop, dict) and parent_loop.get("catalog_version") is not None
            else PROFILE_DECISION_CATALOG_VERSION
        ),
        "current_lineage_reference": record_set.get("current_lineage_reference"),
    }
    if not isinstance(inherited["current_lineage_reference"], str):
        return "parent_current_lineage_reference_missing"
    for field, value in inherited.items():
        supplied = arguments.get(field)
        if supplied is not None and supplied != value:
            return f"{field}_parent_mismatch"
        arguments[field] = deepcopy(value)
    supplied_records = arguments.get("blueprint_decision_records")
    if supplied_records is not None and supplied_records != record_set:
        return "blueprint_decision_records_parent_mismatch"
    return None


def _proposal_lineage(arguments: dict[str, Any]) -> dict[str, Any] | None:
    supplied = arguments.get("decision_evidence_lineage")
    if isinstance(supplied, dict):
        return supplied
    parents = arguments.get("evidence_parent_artifacts")
    if not isinstance(parents, list):
        return None
    for parent in parents:
        if not isinstance(parent, dict):
            continue
        if (
            parent.get("schema_id") == "qcoder.decision_evidence_lineage.v1"
            or parent.get("artifact_type") == "decision_evidence_lineage"
        ):
            return parent
    return None


def _expand_resource_architecture_update(
    update: dict[str, Any],
    *,
    records: list[dict[str, Any]],
    current_build_context: dict[str, Any],
) -> dict[str, Any]:
    selection = update.get("resource_architecture_selection")
    if not isinstance(selection, dict):
        return update
    if set(update) != {"decision_ref", "resource_architecture_selection"}:
        raise ValueError("resource_architecture_selection_overlay_invalid")
    decision_ref = update.get("decision_ref")
    record = next(
        (item for item in records if item.get("decision_ref") == decision_ref),
        None,
    )
    if record is None:
        raise ValueError("resolution_decision_ref_unknown")
    if record.get("profile_decision_id") != "generic_qiskit.circuit_construction":
        raise ValueError("resource_architecture_selection_decision_mismatch")
    if set(selection) != {
        "logical_resource_architecture",
        "allowed_patterns",
        "disallowed_patterns",
        "construction_form",
    }:
        raise ValueError("resource_architecture_selection_invalid")
    definition = next(
        item
        for item in catalog_entries("generic_qiskit")
        if item["profile_decision_id"] == "generic_qiskit.circuit_construction"
    )
    architecture = build_resource_architecture(
        logical_resource_architecture=selection["logical_resource_architecture"],
        construction_form=selection["construction_form"],
        allowed_patterns=selection["allowed_patterns"],
        disallowed_patterns=selection["disallowed_patterns"],
    )
    provenance = deepcopy(record.get("provenance_entries") or [])
    provenance.append(
        {
            "role": "qcoder_observed",
            "current_build_context_ref": current_build_context.get("artifact_ref"),
        }
    )
    return {
        "decision_ref": decision_ref,
        "semantic_classification": "blueprint_decision",
        "control_treatment": "keep_fixed",
        "semantic_role": definition["semantic_role"],
        "applicable_scope": definition["applicable_scope"],
        "relationship_to_requirement": definition["relationship_to_requirement"],
        "related_requirement_references": [definition["relationship_to_requirement"]],
        "resolution_state": "resolved",
        "user_disposition": "selected_choice",
        "generation_effect": "non_blocking",
        "evidence_expectation": deepcopy(definition["later_evidence_requirements"]),
        "future_review_rule": definition["future_review_rule"],
        "remaining_non_proofs": deepcopy(definition["non_proofs"]),
        "provenance_entries": provenance,
        "selected_value": selection["construction_form"],
        "resource_architecture": architecture,
    }


def _prepare_current_build_proposal(tool_name: str, arguments: dict[str, Any]) -> str | None:
    if not (
        tool_name == "create_implementation_blueprint"
        and arguments.get("context_loop") == CONTEXT_LOOP_GATE
        and arguments.get("decision_loop") == DECISION_LOOP_GATE
        and arguments.get("resolution_context") == "current_build_context"
        and arguments.get("resolution_phase") == "propose"
    ):
        return None
    if any(
        field in arguments
        for field in (
            "resolution_confirmation",
            "confirmation_payload",
            LOCAL_SELECTED_BUNDLE_FIELD,
        )
    ):
        return "proposal_confirmation_not_allowed"
    working_blueprint = arguments.get("working_blueprint")
    if not isinstance(working_blueprint, dict):
        return "missing_working_blueprint"
    inherited = working_blueprint.get("blueprint_decision_records")
    if not isinstance(inherited, dict):
        return "working_blueprint_decision_records_missing"
    supplied = arguments.get("blueprint_decision_records")
    if supplied is not None and supplied != inherited:
        return "blueprint_decision_records_parent_mismatch"
    try:
        records = unpack_decision_record_set(inherited)
    except ValueError as exc:
        return str(exc)
    arguments["blueprint_decision_records"] = deepcopy(inherited)
    selected = arguments.get("selected_decision_references")
    updates = arguments.get("proposed_updates")
    if not isinstance(selected, list) or not selected:
        return "selected_decision_references_missing"
    if not isinstance(updates, list) or not updates:
        return "proposed_updates_missing"
    current = arguments.get("current_build_context")
    if not isinstance(current, dict):
        return "missing_current_build_context"
    try:
        expanded = [
            _expand_resource_architecture_update(
                dict(update),
                records=records,
                current_build_context=current,
            )
            for update in updates
            if isinstance(update, dict)
        ]
    except (KeyError, TypeError, ValueError) as exc:
        return str(exc)
    if len(expanded) != len(updates):
        return "proposed_update_invalid"
    arguments["proposed_updates"] = expanded
    return None


def _attach_portable_current_build_context(
    payload: dict[str, Any], arguments: dict[str, Any]
) -> str | None:
    current = payload.get("current_build_context")
    lineage = arguments.get("decision_evidence_lineage")
    if not isinstance(current, dict) or not isinstance(lineage, dict):
        return "portable_current_build_context_inputs_missing"
    working_blueprint = arguments.get("working_blueprint")
    readiness = (
        working_blueprint.get("blueprint_readiness_summary")
        if isinstance(working_blueprint, dict)
        and isinstance(working_blueprint.get("blueprint_readiness_summary"), dict)
        else None
    )
    proposal = arguments.get("carry_forward_proposal")
    try:
        portable = build_portable_current_build_context(
            current_build_context=current,
            decision_records=_portable_decision_records(arguments),
            decision_evidence_lineage=lineage,
            readiness=readiness,
            carry_forward_proposal=proposal if isinstance(proposal, dict) else None,
        )
        working_blueprint = arguments.get("working_blueprint")
        record_set = (
            working_blueprint.get("blueprint_decision_records")
            if isinstance(working_blueprint, dict)
            else None
        )
        artifact_references = current.get("artifact_references")
        if not isinstance(record_set, dict) or not isinstance(artifact_references, dict):
            payload["portable_current_build_context"] = portable
            return None
        parent_fields = (
            "request_baseline",
            "working_blueprint",
            "generation_context",
            "python_manifestation",
            "circuit_manifestation",
            "result_manifestation",
            "decision_evidence_lineage",
        )
        descriptor_names = {
            "decision_evidence_lineage": "lineage",
        }
        parents = []
        normalized_by_field: dict[str, dict[str, Any]] = {}
        for field in parent_fields:
            supplied = arguments.get(field)
            if not isinstance(supplied, dict):
                continue
            normalized = deepcopy(supplied)
            descriptor = artifact_references.get(descriptor_names.get(field, field))
            if not isinstance(descriptor, dict):
                payload["portable_current_build_context"] = portable
                return None
            artifact_ref = descriptor.get("artifact_ref")
            if not isinstance(artifact_ref, str):
                payload["portable_current_build_context"] = portable
                return None
            if normalized.get("artifact_ref") not in (None, artifact_ref):
                raise ValueError("current_build_parent_reference_mismatch")
            normalized["artifact_ref"] = artifact_ref
            normalized_by_field[field] = normalized
            parents.append(normalized)
        parents.append(deepcopy(current))
        normalized_working_blueprint = normalized_by_field["working_blueprint"]
        parent_input = {
            "context_loop": CONTEXT_LOOP_GATE,
            "decision_loop": DECISION_LOOP_GATE,
            "profile_decision_catalog_version": PROFILE_DECISION_CATALOG_VERSION,
            "current_lineage_reference": record_set["current_lineage_reference"],
            "resolution_context": "current_build_context",
            "resolution_phase": "propose",
            "working_blueprint": normalized_working_blueprint,
            "blueprint_decision_records": deepcopy(record_set),
            "current_build_context": deepcopy(current),
            "evidence_parent_artifacts": parents,
        }
        portable = attach_portable_proposal_parent_resupply(
            portable,
            tool_input=parent_input,
        )
        payload["portable_current_build_context"] = portable
    except ValueError:
        return "portable_current_build_context_projection_invalid"
    except (KeyError, TypeError):
        return "portable_proposal_parent_resupply_inputs_missing"
    return None


def _attach_proposal_portable_current_build_context(
    payload: dict[str, Any], arguments: dict[str, Any]
) -> str | None:
    current = arguments.get("current_build_context")
    lineage = _proposal_lineage(arguments)
    proposal = payload.get("carry_forward_proposal")
    if not isinstance(proposal, dict):
        resolution = payload.get("resolution")
        if isinstance(resolution, dict):
            proposal = resolution.get("decision_resolution_pack")
    if (
        not isinstance(current, dict)
        or not isinstance(lineage, dict)
        or not isinstance(proposal, dict)
    ):
        return "proposal_portable_inputs_missing"
    working_blueprint = arguments.get("working_blueprint")
    readiness = (
        working_blueprint.get("blueprint_readiness_summary")
        if isinstance(working_blueprint, dict)
        and isinstance(working_blueprint.get("blueprint_readiness_summary"), dict)
        else None
    )
    try:
        portable = build_portable_current_build_context(
            current_build_context=current,
            decision_records=_portable_decision_records(arguments),
            decision_evidence_lineage=lineage,
            readiness=readiness,
            applicable_actions=current.get("applicable_actions", ()),
            carry_forward_proposal=proposal,
        )
        portable = attach_portable_proposal_resupply(
            portable,
            tool_input=arguments,
            carry_forward_proposal=proposal,
        )
    except ValueError:
        return "proposal_portable_projection_invalid"
    if portable.get("confirmation_transport") is not None:
        return "proposal_portable_confirmation_transport_forbidden"
    payload["portable_current_build_context"] = portable
    return None


def post_context_bridge(
    *,
    base_url: str,
    token_file: str | Path,
    tool_name: str,
    artifact_text: object,
    artifact_kind: str = DEFAULT_ARTIFACT_KIND,
    client_context: dict[str, Any] | None = None,
    mode: str | None = None,
    current_goal: object | None = None,
    evidence_basis: object | None = None,
    share_safe_evidence_summary: object | None = None,
    open_questions: object | None = None,
    explicit_assumptions: object | None = None,
    current_card_context: object | None = None,
    before: object | None = None,
    after: object | None = None,
    tool_arguments: dict[str, Any] | None = None,
    expected_request_digest: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    canonical_tool_name = _canonical_tool_name(tool_name)
    if canonical_tool_name not in EXPECTED_TOOLS:
        return safe_error("unknown_tool")
    direct_arguments = {
        "mode": mode,
        "current_goal": current_goal,
        "evidence_basis": evidence_basis,
        "share_safe_evidence_summary": share_safe_evidence_summary,
        "open_questions": open_questions,
        "explicit_assumptions": explicit_assumptions,
        "current_card_context": current_card_context,
        "before": before,
        "after": after,
    }
    arguments = dict(tool_arguments or {})
    for key, value in direct_arguments.items():
        if value is not None:
            if key in arguments and arguments[key] != value:
                return safe_error("conflicting_tool_argument")
            arguments[key] = value
    context_loop_enabled = arguments.get("context_loop") == CONTEXT_LOOP_GATE
    baseline_error = _compose_request_baseline_handoff(canonical_tool_name, arguments)
    if baseline_error is not None:
        return safe_error(baseline_error)
    inherited_decision_error = _inherit_decision_loop_context(canonical_tool_name, arguments)
    if inherited_decision_error is not None:
        return safe_error(inherited_decision_error)
    proposal_error = _prepare_current_build_proposal(canonical_tool_name, arguments)
    if proposal_error is not None:
        return safe_error(proposal_error)
    context_error = _context_loop_argument_error(canonical_tool_name, arguments, artifact_text)
    if context_error is not None:
        return safe_error(context_error)
    if (
        context_loop_enabled
        and canonical_tool_name == "create_algorithm_intent_card"
        and arguments.get("request_text_share_safe") is not True
    ):
        arguments["original_user_intent"] = arguments["request_share_safe_summary"]
    if canonical_tool_name == "create_source_blueprint_alignment_review" and isinstance(
        arguments.get("selected_python_source_evidence"), dict
    ):
        arguments["selected_python_source_evidence"] = (
            compact_selected_python_source_evidence_for_hosted(
                arguments["selected_python_source_evidence"]
            )
        )
    supplied_fields = set(arguments)
    if artifact_text is not None:
        supplied_fields.add("artifact_text")
    supplied_fields.update({"artifact_kind", "client_context"})
    if supplied_fields - TOOL_INPUT_FIELDS[canonical_tool_name]:
        return safe_error("unsupported_tool_argument")
    if mode is not None:
        if canonical_tool_name != "create_prompt_context":
            return safe_error("mode_not_supported_for_tool")
        if str(mode).strip() not in PROMPT_CONTEXT_MODES:
            return safe_error("invalid_prompt_context_mode")
    if (
        canonical_tool_name == "create_single_loop_evidence_diff"
        and arguments.get("context_loop") != CONTEXT_LOOP_GATE
        and (
            not _has_explicit_side(arguments.get("before"))
            or not _has_explicit_side(arguments.get("after"))
        )
    ):
        return safe_error("missing_explicit_diff_side")
    if artifact_kind != DEFAULT_ARTIFACT_KIND:
        return safe_error("unsupported_artifact_kind")
    if "artifact_text" in TOOL_REQUIRED_FIELDS[canonical_tool_name] or artifact_text is not None:
        text_validation = validate_artifact_text(artifact_text)
        if text_validation != "ok":
            return safe_error(text_validation)
    for required_field in TOOL_REQUIRED_FIELDS[canonical_tool_name]:
        required_value = (
            artifact_text if required_field == "artifact_text" else arguments.get(required_field)
        )
        if (
            required_value is None
            or required_value == ""
            or required_value == []
            or required_value == {}
        ):
            return safe_error(f"missing_{required_field}")
    decision_loop_enabled = arguments.get("decision_loop") == DECISION_LOOP_GATE
    for payload in arguments.values():
        payload_validation = validate_optional_payload(
            payload,
            max_chars=(
                MAX_CONTEXT_LOOP_PAYLOAD_CHARS
                if context_loop_enabled
                else MAX_DECISION_LOOP_PAYLOAD_CHARS
                if decision_loop_enabled
                else MAX_ARTIFACT_TEXT_CHARS
            ),
        )
        if payload_validation != "ok":
            return safe_error(payload_validation)
    token_ok, token_category, token = validate_token_file(token_file)
    if not token_ok:
        return safe_error(token_category, status_category="auth_preflight_failed")

    body: dict[str, Any] = {
        "tool_name": canonical_tool_name,
        "artifact_kind": artifact_kind,
        "client_context": {
            "client_version": "qcoder-context-bridge-mcp-adapter",
            **(client_context or {}),
        },
    }
    if artifact_text is not None:
        body["artifact_text"] = artifact_text
    body.update(arguments)
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + ROUTE_PATH,
        data=data,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
        method="POST",
    )
    urlopen = opener or urllib.request.urlopen
    try:
        with urlopen(request, timeout=20) as response:
            status = int(response.status)
            payload = decode_json(response.read())
            retry_after = (
                response.headers.get("Retry-After") if getattr(response, "headers", None) else None
            )
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        payload = decode_json(exc.read())
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
    except Exception:
        return safe_error("context_bridge_unreachable", status_category="network_error")

    payload.setdefault(
        "adapter_status_category", "success_2xx" if 200 <= status < 300 else f"http_{status}"
    )
    payload.setdefault("token_printed", False)
    payload.setdefault("raw_payload_printed", False)
    payload.setdefault("raw_response_printed", False)
    if status == 429:
        payload.setdefault("retry_after_category", _retry_after_category(retry_after))
    if expected_request_digest is not None and 200 <= status < 300:
        fidelity = payload.get("request_fidelity")
        if (
            not isinstance(fidelity, dict)
            or fidelity.get("local_canonical_request_sha256") != expected_request_digest
            or fidelity.get("protected_received_request_sha256") != expected_request_digest
            or fidelity.get("digests_equal") is not True
        ):
            return safe_error(
                "request_digest_proof_mismatch",
                status_category="transport_consistency_failed",
            )
    if (
        200 <= status < 300
        and context_loop_enabled
        and canonical_tool_name == "create_context_session_card"
    ):
        portable_error = _attach_portable_current_build_context(payload, arguments)
        if portable_error is not None:
            return safe_error(portable_error)
    if (
        200 <= status < 300
        and context_loop_enabled
        and canonical_tool_name == "create_implementation_blueprint"
        and arguments.get("resolution_context") == "current_build_context"
        and arguments.get("resolution_phase") == "propose"
    ):
        portable_error = _attach_proposal_portable_current_build_context(payload, arguments)
        if portable_error is not None:
            return safe_error(portable_error)
    return payload


def _tool_property_schemas() -> dict[str, dict[str, Any]]:
    diff_side_properties = {
        "goal": {"type": "string"},
        "evidence_state": {"type": "string"},
        "result_evidence": {"type": "string"},
        "evidence": {"type": "string"},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "expectations": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    }
    stage_availability_schema = {
        "type": "object",
        "required": ["schema_id", "artifact_type", "stages"],
        "properties": {
            "schema_id": {"const": "qcoder.stage_availability.v1"},
            "schema_version": {"const": 1},
            "artifact_type": {"const": "stage_availability"},
            "artifact_ref": {
                "type": "string",
                "pattern": SESSION_ARTIFACT_REFERENCE_PATTERN,
            },
            "artifact_digest": {"type": "string"},
            "stages": {
                "type": "object",
                "required": list(DEVELOPMENT_STAGES),
                "properties": {
                    stage: {"type": "string", "enum": list(STAGE_AVAILABILITY_VALUES)}
                    for stage in DEVELOPMENT_STAGES
                },
                "additionalProperties": False,
            },
            "describes_evidence_availability_only": {"const": True},
            "proves_construction_or_execution": {"const": False},
            "retention": {"const": "process_and_discard"},
        },
        "additionalProperties": True,
        "description": (
            "Explicit supplied-evidence availability for all six canonical development "
            "stages. Availability does not prove construction or execution."
        ),
    }
    lineage_endpoint_schema = {
        "type": "object",
        "required": ["stage"],
        "properties": {
            "stage": {"type": "string", "enum": list(DEVELOPMENT_STAGES)},
            "artifact_reference": {
                "type": "object",
                "required": [
                    "reference_id",
                    "scope",
                    "opaque",
                    "retrievable",
                    "authentication_use",
                    "proof_use",
                    "cross_session_correlation",
                ],
                "properties": {
                    "reference_id": {
                        "type": "string",
                        "pattern": SESSION_ARTIFACT_REFERENCE_PATTERN,
                    },
                    "scope": {"const": "current_session"},
                    "opaque": {"const": True},
                    "retrievable": {"const": False},
                    "authentication_use": {"const": False},
                    "proof_use": {"const": False},
                    "cross_session_correlation": {"const": False},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }
    decision_evidence_lineage_schema = {
        "type": "object",
        "required": [
            "schema_id",
            "artifact_type",
            "links",
            "transitive_inference",
            "hidden_lookup",
            "persistent",
        ],
        "properties": {
            "schema_id": {"const": "qcoder.decision_evidence_lineage.v1"},
            "schema_version": {"const": 1},
            "artifact_type": {"const": "decision_evidence_lineage"},
            "artifact_ref": {
                "type": "string",
                "pattern": SESSION_ARTIFACT_REFERENCE_PATTERN,
            },
            "artifact_digest": {"type": "string"},
            "canonical_relationship_vocabulary": {
                "type": "array",
                "items": {"type": "string", "enum": list(RELATIONSHIP_TYPES)},
                "uniqueItems": True,
            },
            "links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["relationship", "explicitly_supplied", "non_transitive"],
                    "properties": {
                        "relationship": {
                            "type": "object",
                            "required": [
                                "relationship_type",
                                "source",
                                "target",
                                "direction",
                                "supplied_evidence_basis",
                                "declaration_state",
                                "non_proof",
                            ],
                            "properties": {
                                "relationship_type": {
                                    "type": "string",
                                    "enum": list(RELATIONSHIP_TYPES),
                                },
                                "source": lineage_endpoint_schema,
                                "target": lineage_endpoint_schema,
                                "direction": {"type": "string"},
                                "supplied_evidence_basis": {"type": "string"},
                                "declaration_state": {
                                    "type": "string",
                                    "enum": list(RELATIONSHIP_DECLARATION_STATES),
                                },
                                "non_proof": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                        "decision_references": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "explicitly_supplied": {"const": True},
                        "non_transitive": {"const": True},
                    },
                    "additionalProperties": False,
                },
            },
            "transitive_inference": {"const": False},
            "graph_traversal": {"const": False},
            "hidden_lookup": {"const": False},
            "persistent": {"const": False},
            "retention": {"const": "process_and_discard"},
        },
        "additionalProperties": True,
        "description": (
            "Explicit, directional, non-transitive current-session lineage. Every link "
            "must resupply both artifact references; no graph traversal or hidden lookup occurs."
        ),
    }
    decision_disposition_schema = {
        "type": "object",
        "required": [
            "profile_decision_id",
            "resolution_state",
            "user_disposition",
            "generation_effect",
        ],
        "properties": {
            "profile_decision_id": {"type": "string"},
            "decision_ref": {
                "type": "string",
                "pattern": r"^decision-[A-Za-z0-9_-]{22,64}$",
            },
            "resolution_state": {
                "type": "string",
                "enum": list(RESOLUTION_STATES),
            },
            "user_disposition": {
                "type": "string",
                "enum": list(USER_DISPOSITIONS),
            },
            "generation_effect": {
                "type": "string",
                "enum": list(GENERATION_EFFECTS),
            },
            "selected_value": {
                "description": (
                    "The explicit user-selected value. The field name is selected_value; "
                    "do not substitute selected_choice."
                )
            },
            "blueprint_representation_state": {
                "type": "string",
                "enum": [
                    "not_represented",
                    "represented",
                    "deferred",
                    "represented_in_derived_blueprint",
                ],
            },
            "choice_origin": {
                "type": "string",
                "enum": list(CHOICE_ORIGINS),
            },
            "evidence_confidence": {
                "type": "string",
                "enum": list(DECISION_EVIDENCE_CONFIDENCE_LABELS),
            },
            "alignment_status": {
                "type": "string",
                "enum": list(ALIGNMENT_STATUSES),
            },
        },
        "additionalProperties": True,
        "description": (
            "One explicit decision disposition. user_disposition=selected_choice is an "
            "enum value; the selected content belongs in selected_value."
        ),
    }
    return {
        "artifact_text": {
            "type": "string",
            "description": "Share-safe current qCoder evidence summary. Raw circuits, counts, paths, notebooks, and source files are rejected.",
        },
        "artifact_kind": {
            "type": "string",
            "enum": [DEFAULT_ARTIFACT_KIND],
            "default": DEFAULT_ARTIFACT_KIND,
        },
        LOCAL_SELECTED_BUNDLE_FIELD: {
            "type": "boolean",
            "const": True,
            "description": (
                "Use the one explicitly selected local portable bundle configured "
                "for this adapter process to resupply exact proposal parents or a "
                "confirmed proposal. The local path and file contents are not supplied "
                "by the assistant."
            ),
        },
        LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD: {
            "type": "boolean",
            "const": True,
            "description": (
                "Use one explicitly selected local next-loop seed and its separately "
                "configured exact parent files. The adapter validates and expands "
                "them into this existing operation; no path or loop reference is used "
                "for protected lookup."
            ),
        },
        "client_context": {
            "type": "object",
            "additionalProperties": True,
            "description": "Optional client metadata without secrets, paths, or raw artifacts.",
        },
        "context_loop": {
            "type": "string",
            "enum": [CONTEXT_LOOP_GATE, CONTEXT_LOOP_DISABLED],
            "description": "Explicit Current Build Context v1 opt-in. It does not activate either evidence-depth or decision-resolution behavior.",
        },
        "generation_posture": {
            "type": "string",
            "enum": list(GENERATION_POSTURES),
            "description": "Explicit generation posture, independent from Blueprint Readiness.",
        },
        "request_baseline": {
            "type": "object",
            "additionalProperties": True,
            "description": "Validated share-safe Request Baseline handoff. Local verbatim request text is withheld unless explicitly selected.",
        },
        "request_share_safe_summary": {"type": "string"},
        "request_text_share_safe": {
            "type": "boolean",
            "description": "True only when the user explicitly selected the supplied request text for this handoff.",
        },
        "assistant_interpretation": {
            "type": "object",
            "additionalProperties": True,
            "description": "Explicitly supplied assistant proposal; it is not user intent.",
        },
        "profile_suggestions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "exploratory_authorization": {"type": "boolean"},
        "exploratory_constraints": {
            "type": "array",
            "items": {"type": "string"},
        },
        "exploratory_prohibitions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "unresolved_assistant_choices": {
            "type": "array",
            "items": {"type": "string"},
        },
        "working_blueprint": {"type": "object", "additionalProperties": True},
        "generation_context": {"type": "object", "additionalProperties": True},
        "python_manifestation": {"type": "object", "additionalProperties": True},
        "circuit_manifestation": {"type": "object", "additionalProperties": True},
        "result_manifestation": {"type": "object", "additionalProperties": True},
        "stage_availability": stage_availability_schema,
        "stage_identities": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(STAGE_IDENTITY_STATUSES)},
                },
                "additionalProperties": True,
            },
        },
        "decision_evidence_lineage": decision_evidence_lineage_schema,
        "current_build_context": {"type": "object", "additionalProperties": True},
        "carry_forward_proposal": {"type": "object", "additionalProperties": True},
        "evolved_blueprint": {"type": "object", "additionalProperties": True},
        "decision_records": {
            "type": "array",
            "items": {"type": "object"},
        },
        "evidence_parent_artifacts": {
            "type": "array",
            "items": {"type": "object"},
            "minItems": 1,
            "description": (
                "Every bounded current-session parent relied upon by a current_build_context "
                "proposal, explicitly resupplied in this request. Include the Request Baseline, "
                "Working Blueprint, Generation Context, each supplied manifestation, Decision-"
                "Evidence Lineage, and Current Build Context when referenced; no lookup occurs."
            ),
        },
        "artifact_references": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "missing_stage_requests": {
            "type": "array",
            "items": {"type": "object"},
        },
        "remaining_uncertainty": {
            "type": "array",
            "items": {"type": "string"},
        },
        "generation_context_effect": {"type": "string"},
        "mode": {
            "type": "string",
            "enum": sorted(PROMPT_CONTEXT_MODES),
            "description": "Optional create_prompt_context handoff mode.",
        },
        "current_goal": {
            "type": "string",
            "description": "Bounded goal for the current workflow request.",
        },
        "evidence_basis": {
            "type": "string",
            "description": "Compact share-safe evidence basis supplied for this current request.",
        },
        "share_safe_evidence_summary": {
            "type": "string",
            "description": "Compact user-provided result evidence for current-request review.",
        },
        "open_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Current user-controlled questions or candidate checks to preserve when safely relevant.",
        },
        "explicit_assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Assumptions explicitly supplied by the user for this request.",
        },
        "current_card_context": {
            "type": "object",
            "additionalProperties": True,
            "description": "Optional current-request card context without secrets, paths, or raw artifacts.",
        },
        "before": {
            "type": "object",
            "description": (
                "Explicit structured before context for Single-Loop Evidence Diff. Preserve salient user-provided "
                "observations instead of replacing them with generic summaries."
            ),
            "properties": diff_side_properties,
            "additionalProperties": False,
        },
        "after": {
            "type": "object",
            "description": (
                "Explicit structured after context for Single-Loop Evidence Diff. Keep salient user-reported result "
                "observations rather than reducing them to generic 'result evidence is present' wording."
            ),
            "properties": diff_side_properties,
            "additionalProperties": False,
        },
        "original_user_intent": {
            "type": "string",
            "description": "Original user request preserved in the Algorithm Intent Card.",
        },
        "profile_id": {
            "type": "string",
            "enum": list(PROFILE_IDS),
            "description": "Explicitly selected Algorithm Blueprint profile.",
        },
        "proposed_interpretation": {
            "type": "object",
            "additionalProperties": True,
            "description": "Assistant- or user-supplied proposed structured interpretation; qCoder validates but does not authoritatively infer it.",
        },
        "requirements": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "non_goals": {"type": "array", "items": {"type": "string"}},
        "field_provenance": {
            "type": "object",
            "additionalProperties": {"type": "string", "enum": list(ORIGIN_VALUES)},
        },
        "revision_notes": {"type": "array", "items": {"type": "string"}},
        "requested_confirmation_state": {
            "type": "string",
            "enum": list(CONFIRMATION_STATES),
            "default": "proposed",
        },
        "confirmation_assertion": {
            "type": "object",
            "properties": {"user_reviewed": {"type": "boolean"}},
            "required": ["user_reviewed"],
            "additionalProperties": False,
            "description": "Explicit assertion that the user reviewed the supplied interpretation; not identity or scientific verification.",
        },
        "accepted_unresolved_choices": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Named unresolved fields the user explicitly accepts retaining in a confirmed card.",
        },
        "decision_loop": {
            "type": "string",
            "enum": [DECISION_LOOP_GATE, DECISION_LOOP_DISABLED],
            "description": "Single explicit Decision Readiness and Resolution v1 opt-in. Omission preserves legacy behavior.",
        },
        "profile_decision_catalog_version": {
            "type": "integer",
            "enum": [PROFILE_DECISION_CATALOG_VERSION],
        },
        "current_lineage_reference": {
            "type": "string",
            "pattern": SESSION_ARTIFACT_REFERENCE_PATTERN,
            "description": (
                "Opaque current-session lineage reference. It is non-retrievable and "
                "must not encode a path, customer identifier, or durable project identity."
            ),
        },
        "decision_dispositions": {
            "oneOf": [
                {"type": "array", "items": decision_disposition_schema},
                {
                    "type": "object",
                    "additionalProperties": decision_disposition_schema,
                },
            ]
        },
        "decision_references": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "blueprint_decision_records": {
            "oneOf": [
                {"type": "array", "items": {"type": "object"}},
                {"type": "object"},
            ],
        },
        "resolution_phase": {
            "type": "string",
            "enum": list(RESOLUTION_PHASES),
        },
        "resolution_context": {
            "type": "string",
            "enum": list(RESOLUTION_CONTEXTS),
        },
        "selected_action": {"type": "string", "enum": list(ACTION_IDS)},
        "selected_decision_references": {
            "type": "array",
            "items": {"type": "string"},
        },
        "source_finding_references": {
            "type": "array",
            "items": {"type": "string"},
        },
        "proposed_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "decision_ref": {"type": "string"},
                    "resource_architecture_selection": {
                        "type": "object",
                        "properties": {
                            "logical_resource_architecture": {
                                "type": "string",
                                "enum": list(LOGICAL_RESOURCE_ARCHITECTURES),
                            },
                            "allowed_patterns": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": list(CONSTRUCTION_POLICY_PATTERNS),
                                },
                            },
                            "disallowed_patterns": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": list(CONSTRUCTION_POLICY_PATTERNS),
                                },
                            },
                            "construction_form": {
                                "type": "string",
                                "enum": list(QISKIT_CONSTRUCTION_FORMS),
                            },
                        },
                        "required": [
                            "logical_resource_architecture",
                            "allowed_patterns",
                            "disallowed_patterns",
                            "construction_form",
                        ],
                        "additionalProperties": False,
                        "description": (
                            "Explicit customer-selected resource architecture. The local "
                            "adapter expands it deterministically from the governing "
                            "Working Blueprint record; it does not choose values."
                        ),
                    },
                },
                "required": ["decision_ref"],
                "additionalProperties": True,
            },
        },
        "proposal_ref": {"type": "string"},
        "prospective_derived_artifact_references": {
            "type": "array",
            "items": {"type": "string"},
        },
        "decision_resolution_pack": {"type": "object"},
        "resolution_confirmation": {
            "type": "object",
            "properties": {
                "confirmed": {"type": "boolean"},
                "confirmed_by": {"type": "string"},
            },
            "required": ["confirmed"],
            "additionalProperties": False,
        },
        "confirmation_payload": {"type": "object"},
        "resolution_parent_artifact": {"type": "object"},
        "algorithm_intent_card": {
            "type": "object",
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "original_user_intent",
                "field_provenance",
                "confirmation_state",
            ],
            "additionalProperties": True,
            "description": "Explicitly supplied current-session Algorithm Intent Card.",
        },
        "intent_relationship": {
            "type": "object",
            "properties": {
                "relationship_type": {"type": "string", "enum": ["represented_by"]},
                "parent_artifact_digest": {"type": "string"},
            },
            "required": ["relationship_type", "parent_artifact_digest"],
            "additionalProperties": False,
        },
        "implementation_blueprint": {
            "type": "object",
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "confirmation_state",
            ],
            "additionalProperties": True,
            "description": "Explicitly supplied confirmed current-session Implementation Blueprint.",
        },
        "output_evidence_contract": {
            "type": "object",
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "parent_artifact_digest",
                "expected_evidence",
            ],
            "additionalProperties": True,
            "description": "Explicitly supplied Output Evidence Contract returned with the blueprint.",
        },
        "selected_python_source_evidence": {
            "type": "object",
            "properties": {
                "artifact_type": {"type": "string", "enum": ["selected_python_source_evidence"]},
                "schema_version": {"type": "integer", "enum": [1]},
                "artifact_digest": {"type": "string"},
                "logical_source_label": {"type": "string"},
                "safe_basename": {"type": ["string", "null"]},
                "selected_symbol": {"type": ["string", "null"]},
                "bounded_line_span": {
                    "type": ["array", "null"],
                    "items": {"type": "integer"},
                },
                "origin": {"type": "string", "enum": list(ORIGIN_VALUES)},
                "evidence_scope": {"type": "string"},
                "evidence_coverage": {
                    "type": "string",
                    "enum": list(EVIDENCE_COVERAGE_VALUES),
                },
                "parse_status": {"type": "string"},
                "framework_observation": {"type": "string"},
                "imports_and_aliases": {"type": "array", "items": {"type": "object"}},
                "circuit_construction_symbols": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "parameter_declarations": {"type": "array", "items": {"type": "object"}},
                "measurement_calls": {"type": "array", "items": {"type": "object"}},
                "functions": {"type": "array", "items": {"type": "object"}},
                "classes": {"type": "array", "items": {"type": "object"}},
                "profile_motif_observations": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "source_references": {"type": "array", "items": {"type": "integer"}},
                "ambiguities": {"type": "array", "items": {"type": "string"}},
                "extraction_limitations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "raw_source_included": {"type": "boolean", "enum": [False]},
                "repository_scanned": {"type": "boolean", "enum": [False]},
                "source_executed": {"type": "boolean", "enum": [False]},
                "source_edited": {"type": "boolean", "enum": [False]},
                "retention": {"type": "string", "enum": ["process_and_discard"]},
                "source_evidence_depth": {
                    "type": "object",
                    "properties": {
                        "gate": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": [
                                "available",
                                "parse_limited",
                                "unavailable",
                                "unsupported_profile",
                            ],
                        },
                        "child_contract": {
                            "type": "string",
                            "enum": ["implementation_decision_summary"],
                        },
                        "child_version": {"type": "integer", "enum": [1]},
                        "diagnostics": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["gate", "status", "child_contract", "child_version"],
                    "additionalProperties": False,
                    "description": (
                        "The single explicit source-depth opt-in status. Omission preserves the "
                        "legacy response; unavailable or parse-limited requests return diagnostics only."
                    ),
                },
                "development_evidence": {
                    "type": "object",
                    "properties": {
                        "schema_id": {
                            "type": "string",
                            "enum": ["qcoder.development_evidence.v0"],
                        },
                        "schema_version": {"type": "integer", "enum": [0]},
                        "artifact_kind": {
                            "type": "string",
                            "enum": ["selected_python_source_development_evidence"],
                        },
                        "development_stage": {"type": "string", "enum": ["python_source"]},
                        "framework": {"type": "string", "enum": ["qiskit"]},
                        "working_transition": {
                            "type": "array",
                            "prefixItems": [
                                {"type": "string", "enum": ["human_intent"]},
                                {"type": "string", "enum": ["python_source"]},
                            ],
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "artifact_reference": {"type": "object"},
                        "relationships": {"type": "array", "items": {"type": "object"}},
                        "motif_expectations": {"type": "array", "items": {"type": "object"}},
                        "motif_observations": {"type": "array", "items": {"type": "object"}},
                        "alignment_findings": {"type": "array", "items": {"type": "object"}},
                        "implementation_decision_summary": {"type": ["object", "null"]},
                        "later_stage_analysis_performed": {
                            "type": "boolean",
                            "enum": [False],
                        },
                    },
                    "required": [
                        "schema_id",
                        "schema_version",
                        "artifact_kind",
                        "development_stage",
                        "framework",
                        "working_transition",
                        "artifact_reference",
                        "relationships",
                        "motif_expectations",
                        "motif_observations",
                        "alignment_findings",
                        "later_stage_analysis_performed",
                    ],
                    "additionalProperties": True,
                    "description": (
                        "Optional share-safe current-session Development Evidence v0 data. "
                        "It contains no raw source, raw path, stable source identifier, or later-stage analysis."
                    ),
                },
            },
            "required": [
                "artifact_type",
                "schema_version",
                "artifact_digest",
                "evidence_scope",
                "evidence_coverage",
                "parse_status",
                "raw_source_included",
            ],
            "additionalProperties": False,
            "description": "Compact machine-local static evidence only; paths and raw source are not accepted.",
        },
    }


def _tool_schema(tool_name: str) -> dict[str, Any]:
    property_schemas = _tool_property_schemas()
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {name: property_schemas[name] for name in TOOL_INPUT_FIELDS[tool_name]},
        "required": list(TOOL_REQUIRED_FIELDS[tool_name]),
        "additionalProperties": False,
    }
    context_requirements = {
        "create_context_session_card": [
            "context_loop",
            "request_baseline",
            "working_blueprint",
            "stage_availability",
            "decision_evidence_lineage",
        ],
        "create_result_review_context_card": ["context_loop", "result_manifestation"],
        "create_single_loop_evidence_diff": [
            "context_loop",
            "current_build_context",
            "decision_evidence_lineage",
            "decision_records",
        ],
    }
    if tool_name in context_requirements:
        schema["anyOf"] = [
            {"required": ["artifact_text"]},
            {
                "required": context_requirements[tool_name],
                "properties": {"context_loop": {"const": CONTEXT_LOOP_GATE}},
            },
        ]
        if tool_name == "create_context_session_card":
            schema["anyOf"].append(
                {
                    "required": [
                        "context_loop",
                        "request_share_safe_summary",
                        "request_text_share_safe",
                        "working_blueprint",
                        "stage_availability",
                        "decision_evidence_lineage",
                    ],
                    "properties": {"context_loop": {"const": CONTEXT_LOOP_GATE}},
                }
            )
    if tool_name == "create_generation_context_pack":
        normal_required = list(TOOL_REQUIRED_FIELDS[tool_name])
        schema["required"] = []
        schema["anyOf"] = [
            {"required": normal_required},
            {
                "required": [LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD],
                "properties": {LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD: {"const": True}},
            },
        ]
    return schema


def tool_descriptors() -> list[dict[str, Any]]:
    descriptions = {
        "get_guided_evidence_context": "Create bounded assistant context from share-safe current qCoder evidence.",
        "create_prompt_context": (
            "Create a purpose-specific handoff context from current qCoder evidence, preserving Evidence Review "
            "labels, supported interpretations, unproven statements, and user-controlled next checks."
        ),
        "create_evidence_context_pack": "Create a current-evidence context packet with evidence limits and next-step framing.",
        "create_context_session_card": "Create a current-session context card without memory or history.",
        "create_run_readiness_card": (
            "Review current supplied evidence for readiness with applicable Observed, User-provided, Inferred, "
            "Assumed, Not proven, and Suggested next check labels, without claiming verification."
        ),
        "create_result_review_context_card": (
            "Review share-safe user-provided result evidence with Observed, User-provided, Inferred, Assumed, "
            "Not proven, and Suggested next check semantics."
        ),
        "create_next_check_plan": (
            "Create an ordered, bounded, user-controlled next-check plan tied to current-request evidence and "
            "uncertainties; qCoder does not execute the checks."
        ),
        "create_single_loop_evidence_diff": (
            "Describe what changed between two explicitly supplied current-loop contexts without history or lookup; "
            "this is not causal diagnosis or multi-run analysis. "
            "Use structured before/after fields and preserve salient user-provided result observations."
        ),
        "create_algorithm_intent_card": (
            "Preserve an explicitly supplied quantum algorithm request, validate a proposed interpretation, "
            "surface profile questions and provenance, and require explicit user-reviewed confirmation."
        ),
        "create_implementation_blueprint": (
            "Create a Qiskit-first Implementation Blueprint and distinct Output Evidence Contract from an "
            "explicitly supplied confirmed Algorithm Intent Card. Decision-loop metadata and the complete "
            "decision-record set are inherited exactly from that supplied card; do not reconstruct them. "
            "No code or circuit is generated."
        ),
        "create_generation_context_pack": (
            "Create a current-session Generation Context Pack for external code generation from an explicitly "
            "supplied confirmed blueprint and matching evidence contract. Decision-loop metadata is inherited "
            "exactly from that supplied blueprint; qCoder does not invoke an assistant."
        ),
        "create_source_blueprint_alignment_review": (
            "Review compact machine-local Selected Python Source Evidence against a confirmed blueprint, scoped "
            "to supplied static evidence; no paths, raw source, execution, or correctness claim."
        ),
    }
    return [
        {"name": name, "description": descriptions[name], "inputSchema": _tool_schema(name)}
        for name in EXPECTED_TOOLS
    ]


def _jsonrpc_result(message_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(message_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def handle_jsonrpc_message(
    message: dict[str, Any],
    *,
    base_url: str,
    token_file: str | Path,
    selected_portable_bundle_file: str | Path | None = None,
    selected_next_loop_seed_file: str | Path | None = None,
    selected_next_loop_parent_files: Mapping[str, str | Path] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _jsonrpc_result(
            message_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "qcoder-context-bridge", "version": __version__},
                "instructions": build_client_activation_instructions(
                    base_url=base_url,
                    token_file=token_file,
                ),
            },
        )
    if method == "tools/list":
        return _jsonrpc_result(message_id, {"tools": tool_descriptors()})
    if method == "prompts/list":
        return _jsonrpc_result(message_id, {"prompts": []})
    if method == "resources/list":
        return _jsonrpc_result(message_id, {"resources": []})
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        tool_name = params.get("name")
        normalized_tool_name = str(tool_name or "")
        canonical_tool_name = _canonical_tool_name(normalized_tool_name)
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if (
            canonical_tool_name in TOOL_INPUT_FIELDS
            and set(arguments) - TOOL_INPUT_FIELDS[canonical_tool_name]
        ):
            payload = safe_error("unsupported_tool_argument")
            return _jsonrpc_result(
                message_id,
                {
                    "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                    "structuredContent": payload,
                    "isError": True,
                },
            )
        expected_request_digest: str | None = None
        if (
            canonical_tool_name == "create_implementation_blueprint"
            and arguments.get(LOCAL_SELECTED_BUNDLE_FIELD) is True
        ):
            expanded, expected_request_digest, expansion_error = _expand_selected_portable_bundle(
                arguments,
                selected_file=selected_portable_bundle_file,
            )
            if expansion_error or expanded is None:
                payload = safe_error(expansion_error or "selected_portable_bundle_invalid")
                return _jsonrpc_result(
                    message_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, sort_keys=True),
                            }
                        ],
                        "structuredContent": payload,
                        "isError": True,
                    },
                )
            arguments = expanded
        if (
            canonical_tool_name == "create_generation_context_pack"
            and arguments.get(LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD) is True
        ):
            if selected_next_loop_seed_file is None:
                payload = safe_error("selected_next_loop_seed_not_configured")
                return _jsonrpc_result(
                    message_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, sort_keys=True),
                            }
                        ],
                        "structuredContent": payload,
                        "isError": True,
                    },
                )
            base_arguments = {
                key: deepcopy(value)
                for key, value in arguments.items()
                if key != LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD
            }
            try:
                expanded_seed = expand_next_loop_seed(
                    seed_file=selected_next_loop_seed_file,
                    parent_files=selected_next_loop_parent_files or {},
                    tool_name=canonical_tool_name,
                    base_tool_input=base_arguments,
                )
            except CurrentLoopError as exc:
                payload = safe_error(exc.category)
                return _jsonrpc_result(
                    message_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, sort_keys=True),
                            }
                        ],
                        "structuredContent": payload,
                        "isError": True,
                    },
                )
            arguments = expanded_seed["tool_input"]
            inherited_error = _inherit_decision_loop_context(canonical_tool_name, arguments)
            if inherited_error is not None:
                payload = safe_error(inherited_error)
                return _jsonrpc_result(
                    message_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, sort_keys=True),
                            }
                        ],
                        "structuredContent": payload,
                        "isError": True,
                    },
                )
            expected_request_digest = canonical_operation_request_sha256(
                tool_name=canonical_tool_name,
                tool_input=arguments,
            )
        direct_field_names = {
            "mode",
            "current_goal",
            "evidence_basis",
            "share_safe_evidence_summary",
            "open_questions",
            "explicit_assumptions",
            "current_card_context",
            "before",
            "after",
        }
        payload = post_context_bridge(
            base_url=base_url,
            token_file=token_file,
            tool_name=normalized_tool_name,
            artifact_text=arguments.get("artifact_text"),
            artifact_kind=str(arguments.get("artifact_kind") or DEFAULT_ARTIFACT_KIND),
            client_context=(
                {
                    **(
                        arguments.get("client_context")
                        if isinstance(arguments.get("client_context"), dict)
                        else {}
                    ),
                    "canonical_request_representation": (
                        "qcoder.context_bridge.semantic_request.v1"
                    ),
                    "canonical_request_sha256": expected_request_digest,
                }
                if expected_request_digest is not None
                else (
                    arguments.get("client_context")
                    if isinstance(arguments.get("client_context"), dict)
                    else None
                )
            ),
            mode=str(arguments.get("mode")) if arguments.get("mode") is not None else None,
            current_goal=arguments.get("current_goal"),
            evidence_basis=arguments.get("evidence_basis"),
            share_safe_evidence_summary=arguments.get("share_safe_evidence_summary"),
            open_questions=arguments.get("open_questions"),
            explicit_assumptions=arguments.get("explicit_assumptions"),
            current_card_context=arguments.get("current_card_context"),
            before=arguments.get("before"),
            after=arguments.get("after"),
            tool_arguments={
                key: value
                for key, value in arguments.items()
                if key
                not in direct_field_names | {"artifact_text", "artifact_kind", "client_context"}
            },
            expected_request_digest=expected_request_digest,
            opener=opener,
        )
        payload = _client_visible_tool_payload(canonical_tool_name, payload)
        return _jsonrpc_result(
            message_id,
            {
                "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                "structuredContent": payload,
                "isError": payload.get("ok") is False,
            },
        )
    return _jsonrpc_error(message_id, -32601, "method_not_supported")


def serve_stdio(
    *,
    base_url: str,
    token_file: str | Path,
    selected_portable_bundle_file: str | Path | None = None,
    selected_next_loop_seed_file: str | Path | None = None,
    selected_next_loop_parent_files: Mapping[str, str | Path] | None = None,
) -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _jsonrpc_error(None, -32700, "parse_error")
        else:
            if not isinstance(message, dict):
                response = _jsonrpc_error(None, -32600, "invalid_request")
            else:
                response = handle_jsonrpc_message(
                    message,
                    base_url=base_url,
                    token_file=token_file,
                    selected_portable_bundle_file=selected_portable_bundle_file,
                    selected_next_loop_seed_file=selected_next_loop_seed_file,
                    selected_next_loop_parent_files=selected_next_loop_parent_files,
                )
        if response is None:
            continue
        print(json.dumps(response, sort_keys=True), flush=True)
    return 0


def _write_content_length_response(response: dict[str, Any]) -> None:
    data = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _read_mcp_headers(first_line: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    line = first_line
    while line:
        stripped = line.strip()
        if not stripped:
            break
        if b":" in stripped:
            key, value = stripped.split(b":", 1)
            headers[key.decode("ascii", errors="ignore").lower()] = value.decode(
                "ascii", errors="ignore"
            ).strip()
        line = sys.stdin.buffer.readline()
    return headers


def serve_mcp_stdio(
    *,
    base_url: str,
    token_file: str | Path,
    selected_portable_bundle_file: str | Path | None = None,
    selected_next_loop_seed_file: str | Path | None = None,
    selected_next_loop_parent_files: Mapping[str, str | Path] | None = None,
) -> int:
    stdin = sys.stdin.buffer
    while True:
        first_line = stdin.readline()
        if not first_line:
            break
        if not first_line.strip():
            continue
        if first_line.lstrip().startswith(b"{"):
            try:
                message = json.loads(first_line.decode("utf-8"))
            except json.JSONDecodeError:
                response = _jsonrpc_error(None, -32700, "parse_error")
            else:
                response = handle_jsonrpc_message(
                    message,
                    base_url=base_url,
                    token_file=token_file,
                    selected_portable_bundle_file=selected_portable_bundle_file,
                    selected_next_loop_seed_file=selected_next_loop_seed_file,
                    selected_next_loop_parent_files=selected_next_loop_parent_files,
                )
            if response is not None:
                print(json.dumps(response, sort_keys=True), flush=True)
            continue

        headers = _read_mcp_headers(first_line)
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            _write_content_length_response(_jsonrpc_error(None, -32600, "invalid_content_length"))
            continue
        if content_length <= 0:
            _write_content_length_response(_jsonrpc_error(None, -32600, "missing_content_length"))
            continue
        raw = stdin.read(content_length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            response = _jsonrpc_error(None, -32700, "parse_error")
        else:
            if not isinstance(message, dict):
                response = _jsonrpc_error(None, -32600, "invalid_request")
            else:
                response = handle_jsonrpc_message(
                    message,
                    base_url=base_url,
                    token_file=token_file,
                    selected_portable_bundle_file=selected_portable_bundle_file,
                    selected_next_loop_seed_file=selected_next_loop_seed_file,
                    selected_next_loop_parent_files=selected_next_loop_parent_files,
                )
        if response is not None:
            _write_content_length_response(response)
    return 0


def _case_summary(*, payload: dict[str, Any], expected_success: bool) -> dict[str, Any]:
    serialized = json.dumps(payload, sort_keys=True)
    ok_value = payload.get("ok")
    retained = payload.get("retained_artifacts", [])
    status_category = str(
        payload.get("adapter_status_category") or payload.get("status_category") or "missing"
    )
    success = ok_value is True or status_category == "success_2xx"
    return {
        "expected_outcome_met": success if expected_success else not success,
        "ok_category": "true" if ok_value is True else "false" if ok_value is False else "missing",
        "status_category": status_category,
        "error_category": str(payload.get("error_category") or ""),
        "tool_name_category": payload.get("tool_name")
        if payload.get("tool_name") in EXPECTED_TOOLS
        else "other_or_missing",
        "context_status_category": str(payload.get("context_status") or "missing"),
        "retention_category": str(payload.get("retention") or "missing"),
        "retained_artifacts_empty_or_absent": retained in ([], None),
        "raw_payload_echo_absent": "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER" not in serialized,
        "token_printed": False,
        "raw_response_printed": False,
    }


def _run_full_smoke(*, base_url: str, token_file: str | Path) -> dict[str, Any]:
    token_ok, token_category, _ = validate_token_file(token_file)
    if not token_ok:
        return {
            "ok": False,
            "metadata_only": True,
            "token_file_category": token_category,
            "token_printed": False,
            "raw_token_printed": False,
            "instruction_category": "create_local_chmod_600_token_file",
        }
    safe_text = (
        "Share-safe current qCoder evidence summary. "
        "Small Bell-state style circuit workflow. Evidence summary says the user prepared "
        "a two-qubit entanglement example and wants bounded assistant context. "
        "No raw QASM, no raw counts, no file paths, no backend identifiers, and no source code are included. "
        "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER"
    )
    prompt_context_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="create_prompt_context",
        artifact_text=safe_text,
    )
    cases = {
        "guided_context_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "prompt_context_allowed": _case_summary(
            payload=prompt_context_payload,
            expected_success=True,
        ),
        "evidence_context_pack_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_evidence_context_pack",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "context_session_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_context_session_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "run_readiness_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_run_readiness_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "result_review_context_card_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_result_review_context_card",
                artifact_text=safe_text,
            ),
            expected_success=True,
        ),
        "next_check_plan_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_next_check_plan",
                artifact_text=safe_text,
                current_goal="Choose the next bounded development check.",
                open_questions=["Which assumption should be clarified next?"],
                explicit_assumptions=[
                    "The evidence summary is share-safe and current-session only."
                ],
            ),
            expected_success=True,
        ),
        "single_loop_evidence_diff_allowed": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_single_loop_evidence_diff",
                artifact_text=safe_text,
                before={"summary": "Before context: readiness card requested one bounded check."},
                after={"summary": "After context: user-provided result evidence was reviewed."},
            ),
            expected_success=True,
        ),
        "raw_qasm_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="OPENQASM 2.0; qreg q[1];",
            ),
            expected_success=False,
        ),
        "repo_path_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="/home/private/project/source.py",
            ),
            expected_success=False,
        ),
        "artifact_lookup_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="get_guided_evidence_context",
                artifact_text="artifact lookup request",
                artifact_kind="server_artifact_id",
            ),
            expected_success=False,
        ),
        "unknown_tool_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="suggest_next_checks",
                artifact_text=safe_text,
            ),
            expected_success=False,
        ),
        "invalid_prompt_mode_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_prompt_context",
                artifact_text=safe_text,
                mode="diagnose",
            ),
            expected_success=False,
        ),
        "diff_missing_side_rejected": _case_summary(
            payload=post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_single_loop_evidence_diff",
                artifact_text=safe_text,
                before={"summary": "before only"},
            ),
            expected_success=False,
        ),
    }
    prompt_mode_cases = (
        ("prompt_mode_explain_allowed", "explain"),
        ("prompt_mode_review_allowed", "review"),
        ("prompt_mode_revise_allowed", "revise"),
        ("prompt_mode_troubleshoot_allowed", "troubleshoot"),
        ("prompt_mode_plan_next_checks_allowed", "plan_next_checks"),
    )
    rate_limit_pause = (
        str(
            prompt_context_payload.get("adapter_status_category")
            or prompt_context_payload.get("status_category")
        )
        == "http_429"
    )
    retry_after_category = (
        str(prompt_context_payload.get("retry_after_category") or "absent")
        if rate_limit_pause
        else "absent"
    )
    if rate_limit_pause:
        for pending_name, _pending_mode in prompt_mode_cases:
            cases[pending_name] = {
                "expected_outcome_met": False,
                "ok_category": "missing",
                "status_category": "not_run_rate_limit_pause",
                "error_category": "",
                "tool_name_category": "create_prompt_context",
                "context_status_category": "missing",
                "retention_category": "process_and_discard",
                "retained_artifacts_empty_or_absent": True,
                "raw_payload_echo_absent": True,
                "token_printed": False,
                "raw_response_printed": False,
            }
    else:
        for index, (case_name, mode) in enumerate(prompt_mode_cases):
            payload = post_context_bridge(
                base_url=base_url,
                token_file=token_file,
                tool_name="create_prompt_context",
                artifact_text=safe_text,
                mode=mode,
            )
            cases[case_name] = _case_summary(payload=payload, expected_success=True)
            if (
                str(payload.get("adapter_status_category") or payload.get("status_category"))
                == "http_429"
            ):
                rate_limit_pause = True
                retry_after_category = str(payload.get("retry_after_category") or "absent")
                for pending_name, _pending_mode in prompt_mode_cases[index + 1 :]:
                    cases[pending_name] = {
                        "expected_outcome_met": False,
                        "ok_category": "missing",
                        "status_category": "not_run_rate_limit_pause",
                        "error_category": "",
                        "tool_name_category": "create_prompt_context",
                        "context_status_category": "missing",
                        "retention_category": "process_and_discard",
                        "retained_artifacts_empty_or_absent": True,
                        "raw_payload_echo_absent": True,
                        "token_printed": False,
                        "raw_response_printed": False,
                    }
                break

    approved = [
        "guided_context_allowed",
        "prompt_context_allowed",
        "evidence_context_pack_allowed",
        "context_session_card_allowed",
        "run_readiness_card_allowed",
        "result_review_context_card_allowed",
        "next_check_plan_allowed",
        "single_loop_evidence_diff_allowed",
        "prompt_mode_explain_allowed",
        "prompt_mode_review_allowed",
        "prompt_mode_revise_allowed",
        "prompt_mode_troubleshoot_allowed",
        "prompt_mode_plan_next_checks_allowed",
    ]
    unsafe = [
        "raw_qasm_rejected",
        "repo_path_rejected",
        "artifact_lookup_rejected",
        "unknown_tool_rejected",
        "invalid_prompt_mode_rejected",
        "diff_missing_side_rejected",
    ]
    result = {
        "ok": True,
        "metadata_only": True,
        "client_category": "qCoder Context Bridge MCP adapter",
        "token_source_category": "local_chmod_600_file",
        "tools_visible": list(EXPECTED_TOOLS),
        "tools_exact": True,
        "approved_tool_calls_passed": all(cases[name]["expected_outcome_met"] for name in approved),
        "unsafe_calls_rejected": all(cases[name]["expected_outcome_met"] for name in unsafe),
        "token_printed": False,
        "raw_payload_echo": "no"
        if all(case["raw_payload_echo_absent"] for case in cases.values())
        else "yes",
        "retention_category": "process_and_discard_or_rejected",
        "retained_artifacts_empty": "yes"
        if all(case["retained_artifacts_empty_or_absent"] for case in cases.values())
        else "no",
        "payment_auth_billing_mutation": "no",
        "public_claim_created": "no",
        "source_modified": "no",
        "diagnostic_mode": "full",
        "diagnostic_status_category": "rate_limit_pause_required"
        if rate_limit_pause
        else "complete",
        "retry_after_category": retry_after_category,
        "token_accepted": "yes",
        "token_onboarding_failure": False,
        "cases": cases,
    }
    result["all_expected_outcomes_met"] = (
        result["approved_tool_calls_passed"]
        and result["unsafe_calls_rejected"]
        and result["raw_payload_echo"] == "no"
        and result["retained_artifacts_empty"] == "yes"
    )
    result["ok"] = bool(result["all_expected_outcomes_met"])
    return result


def run_smoke(*, base_url: str, token_file: str | Path, full: bool = False) -> dict[str, Any]:
    if full:
        preflight = run_smoke(base_url=base_url, token_file=token_file)
        if not preflight.get("ok"):
            category = str(preflight.get("connection_status_category") or "connection_check_failed")
            return {
                **preflight,
                "diagnostic_mode": "full",
                "diagnostic_status_category": category,
                "token_onboarding_failure": category in {"token_file_not_ready", "token_rejected"},
            }
        return _run_full_smoke(base_url=base_url, token_file=token_file)

    token_ok, token_category, _ = validate_token_file(token_file)
    if not token_ok:
        return {
            "ok": False,
            "metadata_only": True,
            "connection_status_category": "token_file_not_ready",
            "token_file_category": token_category,
            "token_accepted": "no",
            "tools_visible": list(EXPECTED_TOOLS),
            "tools_exact": True,
            "tools_discovered": len(EXPECTED_TOOLS),
            "token_printed": False,
            "raw_token_printed": False,
            "instruction_category": "create_local_chmod_600_token_file",
        }

    safe_text = (
        "Share-safe current qCoder evidence summary for a harmless connection check. "
        "The user wants one bounded current-session context card. "
        "QCODER_CONTEXT_BRIDGE_SMOKE_MARKER"
    )
    bounded_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="create_context_session_card",
        artifact_text=safe_text,
    )
    bounded_case = _case_summary(payload=bounded_payload, expected_success=True)
    status_category = str(
        bounded_payload.get("adapter_status_category")
        or bounded_payload.get("status_category")
        or "missing"
    )
    rate_limited = status_category == "http_429"
    token_rejected = status_category in {"http_401", "http_403"}
    endpoint_reachable = status_category not in {"network_error", "missing"}
    unsafe_payload = post_context_bridge(
        base_url=base_url,
        token_file=token_file,
        tool_name="get_guided_evidence_context",
        artifact_text="OPENQASM 2.0; qreg q[1];",
    )
    unsafe_case = _case_summary(payload=unsafe_payload, expected_success=False)
    ready = bounded_case["expected_outcome_met"] and unsafe_case["expected_outcome_met"]
    return {
        "ok": bool(ready),
        "metadata_only": True,
        "connection_status_category": (
            "ready"
            if ready
            else "rate_limit_pause_required"
            if rate_limited
            else "token_rejected"
            if token_rejected
            else "connection_check_failed"
        ),
        "token_file_category": "present_safe",
        "token_accepted": "yes"
        if ready
        else "not_rejected"
        if rate_limited
        else "no"
        if token_rejected
        else "unknown",
        "endpoint_reachable": endpoint_reachable,
        "tools_visible": list(EXPECTED_TOOLS),
        "tools_exact": True,
        "tools_discovered": len(EXPECTED_TOOLS),
        "bounded_call_passed": bounded_case["expected_outcome_met"],
        "unsafe_input_rejected": unsafe_case["expected_outcome_met"],
        "retry_after_category": str(bounded_payload.get("retry_after_category") or "absent"),
        "token_printed": False,
        "raw_payload_echo": "no"
        if bounded_case["raw_payload_echo_absent"] and unsafe_case["raw_payload_echo_absent"]
        else "yes",
        "retention_category": "process_and_discard_or_rejected",
        "retained_artifacts_empty": "yes"
        if bounded_case["retained_artifacts_empty_or_absent"]
        and unsafe_case["retained_artifacts_empty_or_absent"]
        else "no",
        "payment_auth_billing_mutation": "no",
        "cases": {
            "context_session_card_allowed": bounded_case,
            "unsafe_input_rejected": unsafe_case,
        },
    }


def _parse_selected_next_loop_parent_files(
    values: list[str] | None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        role, separator, path = value.partition("=")
        if (
            not separator
            or not role
            or not path
            or role in result
            or not Path(path).expanduser().is_absolute()
        ):
            raise ValueError("selected_next_loop_parent_file_invalid")
        result[role] = str(Path(path).expanduser())
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qcoder context-bridge",
        description="qCoder Context Bridge adapter tools for eligible Explorer users.",
    )
    sub = parser.add_subparsers(dest="context_bridge_command")
    mcp = sub.add_parser("mcp", help="Run or smoke-test the local Context Bridge MCP adapter.")
    mcp_sub = mcp.add_subparsers(dest="mcp_command")

    serve = mcp_sub.add_parser("serve", help="Run the local stdio MCP adapter.")
    serve.add_argument(
        "--token-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_TOKEN_FILE", str(default_token_file())),
        help="Path to a local Context Bridge token file. The token value is never printed.",
    )
    serve.add_argument(
        "--base-url",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_BASE_URL", DEFAULT_BASE_URL),
        help="Context Bridge service base URL.",
    )
    serve.add_argument(
        "--selected-portable-bundle-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_SELECTED_PORTABLE_BUNDLE_FILE"),
        help=(
            "One explicitly selected local portable Context Loop bundle. "
            "The path and file contents are never sent as path metadata."
        ),
    )
    serve.add_argument(
        "--selected-next-loop-seed-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_SELECTED_NEXT_LOOP_SEED_FILE"),
        help=(
            "One explicitly selected local next-loop seed. It is validated with "
            "separately selected exact parent files; no local path is transmitted."
        ),
    )
    serve.add_argument(
        "--selected-next-loop-parent-file",
        action="append",
        default=[],
        metavar="ROLE=/ABSOLUTE/PATH",
        help=(
            "One exact parent file required by the selected next-loop seed. "
            "Repeat for each required role."
        ),
    )
    serve.set_defaults(context_bridge_command="mcp", mcp_command="serve")

    smoke = mcp_sub.add_parser("smoke", help="Check the Context Bridge connection safely.")
    smoke.add_argument(
        "--token-file",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_TOKEN_FILE", str(default_token_file())),
        help="Path to a local Context Bridge token file. The token value is never printed.",
    )
    smoke.add_argument(
        "--base-url",
        default=os.getenv("QCODER_CONTEXT_BRIDGE_BASE_URL", DEFAULT_BASE_URL),
        help="Context Bridge service base URL.",
    )
    smoke.add_argument("--json", action="store_true", help="Emit sanitized JSON result.")
    smoke.add_argument(
        "--full",
        action="store_true",
        help="Run the exhaustive support/release diagnostic without automatic rate-limit retries.",
    )
    smoke.set_defaults(context_bridge_command="mcp", mcp_command="smoke")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.context_bridge_command is None or getattr(args, "mcp_command", None) is None:
        parser.print_help()
        return 0
    if args.mcp_command == "serve":
        try:
            selected_next_loop_parent_files = _parse_selected_next_loop_parent_files(
                args.selected_next_loop_parent_file
            )
        except ValueError as exc:
            parser.error(str(exc))
        return serve_mcp_stdio(
            base_url=args.base_url,
            token_file=args.token_file,
            selected_portable_bundle_file=args.selected_portable_bundle_file,
            selected_next_loop_seed_file=args.selected_next_loop_seed_file,
            selected_next_loop_parent_files=selected_next_loop_parent_files,
        )
    if args.mcp_command == "smoke":
        result = run_smoke(base_url=args.base_url, token_file=args.token_file, full=args.full)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.full:
            print(
                f"Context Bridge full diagnostic: {result.get('diagnostic_status_category', 'check_required')}"
            )
            print(
                f"Token onboarding failure: {'yes' if result.get('token_onboarding_failure') else 'no'}"
            )
            print(f"Tools discovered: {len(result.get('tools_visible', []))}")
            if result.get("diagnostic_status_category") == "rate_limit_pause_required":
                print("Rate limit: pause before continuing the remaining diagnostic checks")
        else:
            status = (
                "ready"
                if result.get("ok")
                else result.get("connection_status_category", "check required")
            )
            print(f"Context Bridge connection: {status}")
            print(f"Token accepted: {result.get('token_accepted', 'unknown')}")
            print(f"Tools discovered: {result.get('tools_discovered', 0)}")
        if result.get("diagnostic_status_category") == "rate_limit_pause_required":
            return 2
        return 0 if result.get("ok") else 1
    parser.print_help()
    return 0
