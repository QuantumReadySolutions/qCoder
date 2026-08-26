from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    build_parser,
    build_client_activation_instructions,
    post_context_bridge,
    resolve_credential_source,
    tool_descriptors,
)
from qcoder.current_loop_invocation import build_operation_invocation
from qcoder.context_bridge_profiles import (
    CredentialProfileError,
    CredentialProfileManager,
    HardenedFileSecretStore,
    LEGACY_PROFILE_ID,
    MIGRATION_JOURNAL_SCHEMA_ID,
    PROFILE_REGISTRY_SCHEMA_ID,
    PROFILE_REGISTRY_SCHEMA_VERSION,
    SelectedCredential,
    SecretToolStore,
    WindowsDpapiStore,
    safe_profile_error,
)


TOKEN_A = "A" * 64
TOKEN_B = "B" * 64
TOKEN_C = "C" * 64


class MemoryStore:
    kind = "test_protected"

    def __init__(self, *, available: bool = True) -> None:
        self.enabled = available
        self.values: dict[str, str] = {}

    def available(self) -> bool:
        return self.enabled

    def put(self, profile_id: str, secret: str) -> None:
        if not self.enabled:
            raise CredentialProfileError("protected_storage_unavailable")
        if profile_id in self.values:
            raise CredentialProfileError("profile_secret_already_exists")
        self.values[profile_id] = secret

    def get(self, profile_id: str) -> str:
        try:
            return self.values[profile_id]
        except KeyError as exc:
            raise CredentialProfileError("selected_profile_secret_missing") from exc

    def delete(self, profile_id: str) -> None:
        self.values.pop(profile_id, None)


def _manager(
    tmp_path: Path,
    *,
    protected: MemoryStore | None = None,
    ids: list[str] | None = None,
) -> CredentialProfileManager:
    values = iter(
        ids
        or [
            "qcp-000000000000000000000001",
            "qcp-000000000000000000000002",
            "qcp-000000000000000000000003",
        ]
    )
    return CredentialProfileManager(
        registry_file=tmp_path / "context-bridge" / "profiles.json",
        legacy_token_file=tmp_path / "context-bridge" / "token.txt",
        protected_store=protected or MemoryStore(),
        fallback_store=HardenedFileSecretStore(tmp_path / "context-bridge" / "profile-secrets"),
        profile_id_factory=lambda: next(values),
    )


def _create(
    manager: CredentialProfileManager,
    *,
    label: str,
    reference: str,
    account: str,
    secret: str,
    client: str = "",
    workspace: str = "",
    default: bool = False,
) -> dict[str, object]:
    return manager.create_profile(
        label=label,
        credential_reference=reference,
        account_label=account,
        client_label=client,
        device_label="Controlled device",
        workspace_label=workspace,
        client_selector=client,
        workspace_selector=workspace,
        secret=secret,
        set_default=default,
        validator=lambda candidate: candidate == secret,
    )


def test_new_customer_creates_first_named_profile_without_implicit_default(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    created = _create(
        manager,
        label="Cursor on workstation",
        reference="cbcred-cursor-workstation",
        account="Research account",
        secret=TOKEN_A,
    )

    assert created["profile_id"] == "qcp-000000000000000000000001"
    assert created["default"] is False
    with pytest.raises(CredentialProfileError, match="profile_selection_required"):
        manager.select()
    selected = manager.select(explicit_profile="Cursor on workstation")
    assert selected.secret == TOKEN_A
    assert selected.selection_source == "explicit_invocation"
    assert TOKEN_A not in json.dumps(manager.list_safe())


def test_two_clients_one_account_and_client_workspace_selection(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    cursor = _create(
        manager,
        label="Cursor project",
        reference="cbcred-cursor-project",
        account="Research account",
        secret=TOKEN_A,
        client="cursor",
        workspace="workspace-alpha",
    )
    claude = _create(
        manager,
        label="Claude project",
        reference="cbcred-claude-project",
        account="Research account",
        secret=TOKEN_B,
        client="claude-code",
        workspace="workspace-alpha",
    )

    assert (
        manager.select(client_selector="cursor", workspace_selector="workspace-alpha").profile_id
        == cursor["profile_id"]
    )
    assert (
        manager.select(
            client_selector="claude-code", workspace_selector="workspace-alpha"
        ).profile_id
        == claude["profile_id"]
    )


def test_multiple_accounts_explicit_overrides_binding_and_default(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = _create(
        manager,
        label="Account one default",
        reference="cbcred-account-one-default",
        account="Account one",
        secret=TOKEN_A,
        default=True,
    )
    second = _create(
        manager,
        label="Account two Cursor",
        reference="cbcred-account-two-cursor",
        account="Account two",
        secret=TOKEN_B,
        client="cursor",
    )

    assert manager.select().profile_id == first["profile_id"]
    assert manager.select(client_selector="cursor").profile_id == second["profile_id"]
    selected = manager.select(explicit_profile=str(first["profile_id"]), client_selector="cursor")
    assert selected.profile_id == first["profile_id"]
    assert selected.account_label == "Account one"


def test_multiple_matching_profiles_fail_closed_with_nonsecret_choices(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _create(
        manager,
        label="Client-wide",
        reference="cbcred-client-wide",
        account="Account one",
        secret=TOKEN_A,
        client="cursor",
    )
    _create(
        manager,
        label="Workspace-wide",
        reference="cbcred-workspace-wide",
        account="Account two",
        secret=TOKEN_B,
        workspace="workspace-alpha",
    )

    with pytest.raises(CredentialProfileError) as captured:
        manager.select(client_selector="cursor", workspace_selector="workspace-alpha")
    assert captured.value.category == "profile_selection_ambiguous"
    safe = safe_profile_error(captured.value)
    assert safe["next_action"] == "select_one_profile_explicitly"
    assert len(safe["choices"]) == 2
    assert TOKEN_A not in json.dumps(safe)
    assert TOKEN_B not in json.dumps(safe)


def test_selected_revoked_secret_fails_without_default_fallback(tmp_path: Path) -> None:
    store = MemoryStore()
    manager = _manager(tmp_path, protected=store)
    default = _create(
        manager,
        label="Default profile",
        reference="cbcred-default-profile",
        account="Account one",
        secret=TOKEN_A,
        default=True,
    )
    selected = _create(
        manager,
        label="Revoked profile",
        reference="cbcred-revoked-profile",
        account="Account two",
        secret=TOKEN_B,
    )
    store.delete(str(selected["profile_id"]))

    with pytest.raises(CredentialProfileError, match="selected_profile_secret_missing"):
        manager.select(explicit_profile=str(selected["profile_id"]))
    assert manager.select().profile_id == default["profile_id"]


def test_replacement_requires_explicit_adoption_and_rolls_back_on_rejection(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    created = _create(
        manager,
        label="Replace me",
        reference="cbcred-original-reference",
        account="Account one",
        secret=TOKEN_A,
    )

    with pytest.raises(
        CredentialProfileError, match="credential_replacement_rejected_original_restored"
    ):
        manager.replace_credential(
            selector=str(created["profile_id"]),
            credential_reference="cbcred-rejected-replacement",
            secret=TOKEN_B,
            validator=lambda _: False,
        )
    assert manager.select(explicit_profile=str(created["profile_id"])).secret == TOKEN_A

    adopted = manager.replace_credential(
        selector=str(created["profile_id"]),
        credential_reference="cbcred-accepted-replacement",
        secret=TOKEN_C,
        validator=lambda candidate: candidate == TOKEN_C,
    )
    assert adopted["deliberate_replacement_adopted"] is True
    assert manager.select(explicit_profile=str(created["profile_id"])).secret == TOKEN_C


def test_protected_storage_never_silently_falls_back(tmp_path: Path) -> None:
    manager = _manager(tmp_path, protected=MemoryStore(available=False))
    arguments = {
        "label": "Fallback profile",
        "credential_reference": "cbcred-fallback-profile",
        "account_label": "Account one",
        "secret": TOKEN_A,
    }
    with pytest.raises(
        CredentialProfileError,
        match="protected_storage_unavailable_hardened_file_confirmation_required",
    ):
        manager.preflight_storage(storage="auto", allow_hardened_file_fallback=False)

    created = manager.create_profile(
        **arguments,
        allow_hardened_file_fallback=True,
    )
    assert created["storage_kind"] == "hardened_file"
    secret_path = (
        tmp_path / "context-bridge" / "profile-secrets" / f"{created['profile_id']}.secret"
    )
    if os.name != "nt":
        assert secret_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_unsafe_registry_and_secret_permissions_fail_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path, protected=MemoryStore(available=False))
    created = manager.create_profile(
        label="Fallback profile",
        credential_reference="cbcred-fallback-profile",
        account_label="Account one",
        secret=TOKEN_A,
        storage="hardened-file",
    )
    manager.registry_file.chmod(0o644)
    with pytest.raises(CredentialProfileError, match="profile_storage_permissions_unsafe"):
        manager.read_registry()
    manager.registry_file.chmod(0o600)
    secret_path = manager.fallback_store._path(str(created["profile_id"]))  # type: ignore[attr-defined]
    secret_path.chmod(0o644)
    with pytest.raises(CredentialProfileError, match="profile_storage_permissions_unsafe"):
        manager.select(explicit_profile=str(created["profile_id"]))


def test_missing_corrupt_and_wrong_schema_registry_fail_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    assert manager.read_registry()["profiles"] == []
    manager.registry_file.parent.mkdir(parents=True)
    manager.registry_file.write_text("not-json", encoding="utf-8")
    manager.registry_file.chmod(0o600)
    with pytest.raises(CredentialProfileError, match="profile_registry_invalid"):
        manager.read_registry()
    manager.registry_file.write_text(
        json.dumps(
            {
                "schema_id": PROFILE_REGISTRY_SCHEMA_ID,
                "schema_version": PROFILE_REGISTRY_SCHEMA_VERSION + 1,
                "default_profile_id": None,
                "profiles": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CredentialProfileError, match="profile_registry_schema_unsupported"):
        manager.read_registry()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_storage_ancestor_symlink_fails_closed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    manager = CredentialProfileManager(
        registry_file=linked / "context-bridge" / "profiles.json",
        legacy_token_file=linked / "context-bridge" / "token.txt",
        protected_store=MemoryStore(),
        fallback_store=HardenedFileSecretStore(linked / "context-bridge" / "profile-secrets"),
        profile_id_factory=lambda: "qcp-000000000000000000000001",
    )
    with pytest.raises(CredentialProfileError, match="profile_storage_ancestor_symlink_rejected"):
        _create(
            manager,
            label="Unsafe ancestor",
            reference="cbcred-unsafe-ancestor",
            account="Account one",
            secret=TOKEN_A,
        )


def test_legacy_default_selection_and_migration_are_explicit_reversible_and_no_overwrite(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager.legacy_token_file.parent.mkdir(parents=True)
    manager.legacy_token_file.parent.chmod(0o700)
    manager.legacy_token_file.write_text(TOKEN_A + "\n", encoding="utf-8")
    manager.legacy_token_file.chmod(0o600)
    original = manager.legacy_token_file.read_bytes()

    legacy = manager.select()
    assert legacy.profile_id == LEGACY_PROFILE_ID
    assert legacy.label == "Legacy default"
    assert legacy.selection_source == "customer_selected_default"

    cancelled = manager.migrate_legacy(
        label="Imported legacy",
        credential_reference="cbcred-imported-legacy",
        account_label="Account one",
        confirmed=False,
    )
    assert cancelled["category"] == "legacy_migration_confirmation_required"
    assert manager.legacy_token_file.read_bytes() == original

    with pytest.raises(CredentialProfileError, match="credential_validation_failed"):
        manager.migrate_legacy(
            label="Imported legacy",
            credential_reference="cbcred-imported-legacy",
            account_label="Account one",
            validator=lambda _: False,
            confirmed=True,
        )
    assert manager.read_registry()["profiles"] == []
    assert manager.legacy_token_file.read_bytes() == original

    migrated = manager.migrate_legacy(
        label="Imported legacy",
        credential_reference="cbcred-imported-legacy",
        account_label="Account one",
        validator=lambda candidate: candidate == TOKEN_A,
        confirmed=True,
    )
    assert migrated["migration_validated"] is True
    assert migrated["legacy_unchanged"] is True
    assert migrated["raw_token_backup_created"] is False
    assert manager.legacy_token_file.read_bytes() == original
    removed = manager.remove_profile(str(migrated["profile_id"]), confirmed=True)
    assert removed["profile_removed"] is True
    assert manager.legacy_token_file.read_bytes() == original


def test_deterministic_selection_survives_restart_and_metadata_reordering(tmp_path: Path) -> None:
    store = MemoryStore()
    manager = _manager(tmp_path, protected=store)
    first = _create(
        manager,
        label="First account",
        reference="cbcred-first-account",
        account="Account one",
        secret=TOKEN_A,
    )
    _create(
        manager,
        label="Second account",
        reference="cbcred-second-account",
        account="Account two",
        secret=TOKEN_B,
    )
    manager.set_default(str(first["profile_id"]))
    registry = manager.read_registry()
    registry["profiles"] = list(reversed(registry["profiles"]))
    manager.write_registry(registry)

    restarted = CredentialProfileManager(
        registry_file=manager.registry_file,
        legacy_token_file=manager.legacy_token_file,
        protected_store=store,
        fallback_store=manager.fallback_store,
    )
    assert restarted.select().profile_id == first["profile_id"]


def test_interrupted_legacy_migration_removes_only_orphan_profile_secret(tmp_path: Path) -> None:
    store = MemoryStore()
    manager = _manager(tmp_path, protected=store)
    profile_id = "qcp-000000000000000000000099"
    store.put(profile_id, TOKEN_A)
    manager.migration_journal_file.parent.mkdir(parents=True)
    manager.migration_journal_file.write_text(
        json.dumps(
            {
                "schema_id": MIGRATION_JOURNAL_SCHEMA_ID,
                "profile_id": profile_id,
                "storage_kind": store.kind,
            }
        ),
        encoding="utf-8",
    )
    manager.migration_journal_file.chmod(0o600)

    recovered = manager.recover_incomplete_migration()
    assert recovered["orphan_secret_removed"] is True
    assert profile_id not in store.values
    assert not manager.migration_journal_file.exists()


def test_resolution_conflicts_and_public_tool_inventory_remain_fail_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(CredentialProfileError, match="legacy_file_and_profile_selection_conflict"):
        resolve_credential_source(
            token_file=tmp_path / "token.txt",
            profile="any-profile",
            client_context=None,
            workspace_context=None,
            manager=manager,
        )
    assert len(tool_descriptors()) == 12
    assert len(EXPECTED_TOOLS) == 12


def test_profile_cli_never_accepts_secret_in_argv() -> None:
    parser = build_parser()
    create = parser.parse_args(
        [
            "profiles",
            "create",
            "--label",
            "Cursor",
            "--credential-reference",
            "cbcred-cursor-reference",
            "--account-label",
            "Account one",
        ]
    )
    assert not hasattr(create, "secret")
    help_text = parser.format_help()
    assert "--secret" not in help_text


def test_safe_diagnostics_contain_no_secret_or_storage_path(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _create(
        manager,
        label="Safe profile",
        reference="cbcred-safe-profile",
        account="Account one",
        secret=TOKEN_A,
    )
    serialized = json.dumps(manager.list_safe(), sort_keys=True)
    assert TOKEN_A not in serialized
    assert str(tmp_path) not in serialized


def test_selected_credential_safe_metadata_excludes_secret() -> None:
    selected = SelectedCredential(
        profile_id="qcp-000000000000000000000001",
        label="Safe profile",
        credential_reference="cbcred-safe-profile",
        account_label="Account one",
        storage_kind="test_protected",
        selection_source="explicit_invocation",
        secret=TOKEN_A,
    )
    assert TOKEN_A not in json.dumps(selected.safe_metadata())
    assert TOKEN_A not in repr(selected)


def test_secret_service_passes_secret_only_on_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[list[str], str | None]] = []

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append((arguments, kwargs.get("input")))  # type: ignore[arg-type]
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/synthetic")
    monkeypatch.setattr(subprocess, "run", run)
    store = SecretToolStore(executable="/synthetic/secret-tool")
    store.put("qcp-000000000000000000000001", TOKEN_A)

    assert captured == [
        (
            [
                "/synthetic/secret-tool",
                "store",
                "--label=qCoder Context Bridge credential",
                "service",
                "qcoder",
                "profile",
                "qcp-000000000000000000000001",
            ],
            TOKEN_A,
        )
    ]
    assert TOKEN_A not in json.dumps(captured[0][0])


def test_windows_dpapi_envelope_round_trip_and_malformed_blob_fail_closed(
    tmp_path: Path,
) -> None:
    class SyntheticDpapiStore(WindowsDpapiStore):
        def available(self) -> bool:
            return True

        def _crypt(self, raw: bytes, *, protect: bool) -> bytes:
            del protect
            return bytes(value ^ 0x5A for value in raw)

    store = SyntheticDpapiStore(tmp_path / "dpapi")
    profile_id = "qcp-000000000000000000000001"
    store.put(profile_id, TOKEN_A)
    assert store.get(profile_id) == TOKEN_A
    encrypted_path = store._path(profile_id)
    assert TOKEN_A.encode() not in encrypted_path.read_bytes()
    encrypted_path.write_bytes(b"not!base64\n")
    encrypted_path.chmod(0o600)
    with pytest.raises(CredentialProfileError, match="selected_profile_secret_malformed"):
        store.get(profile_id)


def test_profile_backed_activation_exposes_only_nonsecret_selection_metadata() -> None:
    selected = SelectedCredential(
        profile_id="qcp-000000000000000000000001",
        label="Safe profile",
        credential_reference="cbcred-safe-profile",
        account_label="Account one",
        storage_kind="test_protected",
        selection_source="explicit_invocation",
        secret=TOKEN_A,
    )
    instructions = build_client_activation_instructions(
        base_url="https://example.invalid", token_file=selected
    )
    assert selected.profile_id in instructions
    assert "credential_profile_id" in instructions
    assert "secret_material_exposed" in instructions
    assert TOKEN_A not in instructions
    assert "token_file_path" not in instructions


def test_qcoder_owned_hosted_invocation_propagates_exact_profile_without_secret() -> None:
    invocation = build_operation_invocation(
        {"subcommand": "prepare-generation", "required_flags": []},
        executable="/runtime/python",
        workspace="/workspace",
        base_url="https://example.invalid",
        token_file="",
        credential_profile="qcp-000000000000000000000001",
        state_revision=3,
        loop_ref="loop-example",
        checkpoint="intent_review",
    )
    operation = invocation["operation_specific_invocation"]
    argv = operation["structured_argv"]
    assert "--credential-profile" in argv
    assert "qcp-000000000000000000000001" in argv
    assert "--token-file" not in argv
    assert operation["credential_selection"] == {
        "kind": "named_profile",
        "profile_id": "qcp-000000000000000000000001",
        "secret_included": False,
        "selection_reconstructed_by_client": False,
    }


def test_selected_rejected_credential_does_not_trigger_another_profile(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _create(
        manager,
        label="Default profile",
        reference="cbcred-default-profile",
        account="Account one",
        secret=TOKEN_A,
        default=True,
    )
    rejected = _create(
        manager,
        label="Selected profile",
        reference="cbcred-selected-profile",
        account="Account two",
        secret=TOKEN_B,
    )
    selected = manager.select(explicit_profile=str(rejected["profile_id"]))
    calls = 0

    class Response:
        status = 401
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": False,
                    "error_category": "authentication_rejected",
                    "retention": "process_and_discard",
                    "retained_artifacts": [],
                }
            ).encode()

    def opener(*_: object, **__: object) -> Response:
        nonlocal calls
        calls += 1
        return Response()

    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=selected,
        tool_name="create_context_session_card",
        artifact_text="Share-safe bounded context.",
        opener=opener,
    )
    assert calls == 1
    assert result["adapter_status_category"] == "http_401"
    assert manager.select().profile_id != selected.profile_id
