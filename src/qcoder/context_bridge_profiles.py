from __future__ import annotations

from dataclasses import dataclass, field
import base64
import ctypes
from ctypes import wintypes
import getpass
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat
import subprocess
from typing import Any, Callable, Mapping, Protocol


PROFILE_REGISTRY_SCHEMA_ID = "qcoder.context_bridge.credential_profiles.v1"
PROFILE_REGISTRY_SCHEMA_VERSION = 1
MIGRATION_JOURNAL_SCHEMA_ID = "qcoder.context_bridge.legacy_migration_journal.v1"
PROFILE_ID_PATTERN = re.compile(r"qcp-[0-9a-f]{24}")
CREDENTIAL_REFERENCE_PATTERN = re.compile(r"cbcred-[A-Za-z0-9][A-Za-z0-9._-]{7,95}")
CONTEXT_BRIDGE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{64}")
LEGACY_PROFILE_ID = "legacy-default"
LEGACY_PROFILE_LABEL = "Legacy default"
MAX_REGISTRY_BYTES = 256 * 1024
MAX_SAFE_TEXT_LENGTH = 160


class CredentialProfileError(ValueError):
    """A bounded local-profile error whose category contains no secret material."""

    def __init__(self, category: str, *, choices: list[dict[str, str]] | None = None):
        super().__init__(category)
        self.category = category
        self.choices = choices or []


class SecretStore(Protocol):
    kind: str

    def available(self) -> bool: ...

    def put(self, profile_id: str, secret: str) -> None: ...

    def get(self, profile_id: str) -> str: ...

    def delete(self, profile_id: str) -> None: ...


def default_profiles_root() -> Path:
    return Path.home() / ".qcoder" / "context-bridge"


def default_registry_file() -> Path:
    return default_profiles_root() / "profiles.json"


def default_legacy_token_file() -> Path:
    return default_profiles_root() / "token.txt"


def _safe_text(value: object, *, field: str, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise CredentialProfileError(f"{field}_invalid")
    normalized = value.strip()
    if required and not normalized:
        raise CredentialProfileError(f"{field}_missing")
    if len(normalized) > MAX_SAFE_TEXT_LENGTH:
        raise CredentialProfileError(f"{field}_too_long")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise CredentialProfileError(f"{field}_invalid")
    if re.search(r"[A-Za-z0-9_-]{64}", normalized):
        raise CredentialProfileError(f"{field}_resembles_secret")
    return normalized


def validate_secret_value(value: object) -> str:
    if not isinstance(value, str):
        raise CredentialProfileError("credential_secret_invalid")
    normalized = value.strip()
    if CONTEXT_BRIDGE_TOKEN_PATTERN.fullmatch(normalized) is None:
        raise CredentialProfileError("credential_secret_malformed")
    return normalized


def _require_safe_file(path: Path, *, missing_category: str) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise CredentialProfileError(missing_category)
        info = path.stat()
    except OSError as exc:
        raise CredentialProfileError(missing_category) from exc
    if os.name != "nt":
        if info.st_uid != os.getuid():
            raise CredentialProfileError("profile_storage_owner_unsafe")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise CredentialProfileError("profile_storage_permissions_unsafe")
    if info.st_size > MAX_REGISTRY_BYTES:
        raise CredentialProfileError("profile_storage_too_large")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CredentialProfileError("profile_storage_unreadable") from exc


def _atomic_private_write(path: Path, payload: bytes) -> None:
    for ancestor in path.parents:
        if ancestor.is_symlink():
            raise CredentialProfileError("profile_storage_ancestor_symlink_rejected")
    if path.parent.exists() or path.parent.is_symlink():
        try:
            info = path.parent.stat()
        except OSError as exc:
            raise CredentialProfileError("profile_storage_directory_unreadable") from exc
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise CredentialProfileError("profile_storage_directory_unsafe")
        if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise CredentialProfileError("profile_storage_directory_permissions_unsafe")
    else:
        missing: list[Path] = []
        cursor = path.parent
        while not cursor.exists() and not cursor.is_symlink():
            missing.append(cursor)
            cursor = cursor.parent
        if cursor.is_symlink():
            raise CredentialProfileError("profile_storage_ancestor_symlink_rejected")
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
            if os.name != "nt":
                directory.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")


class HardenedFileSecretStore:
    kind = "hardened_file"

    def __init__(self, root: Path):
        self.root = root

    def available(self) -> bool:
        return True

    def _path(self, profile_id: str) -> Path:
        if PROFILE_ID_PATTERN.fullmatch(profile_id) is None:
            raise CredentialProfileError("profile_id_invalid")
        return self.root / f"{profile_id}.secret"

    def put(self, profile_id: str, secret: str) -> None:
        path = self._path(profile_id)
        if path.exists() or path.is_symlink():
            raise CredentialProfileError("profile_secret_already_exists")
        _atomic_private_write(path, (validate_secret_value(secret) + "\n").encode("utf-8"))

    def get(self, profile_id: str) -> str:
        raw = _require_safe_file(
            self._path(profile_id), missing_category="selected_profile_secret_missing"
        )
        try:
            return validate_secret_value(raw.decode("utf-8"))
        except UnicodeError as exc:
            raise CredentialProfileError("selected_profile_secret_malformed") from exc

    def delete(self, profile_id: str) -> None:
        path = self._path(profile_id)
        if path.is_symlink():
            raise CredentialProfileError("profile_secret_symlink_rejected")
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialProfileError("profile_secret_delete_failed") from exc


class SecretToolStore:
    """Freedesktop Secret Service adapter; secrets use stdin/stdout, never argv."""

    kind = "secret_service"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("secret-tool") or ""

    def available(self) -> bool:
        return bool(self.executable) and bool(
            os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("XDG_RUNTIME_DIR")
        )

    def _run(
        self, arguments: list[str], *, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        if not self.available():
            raise CredentialProfileError("protected_storage_unavailable")
        try:
            return subprocess.run(
                [self.executable, *arguments],
                input=stdin,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CredentialProfileError("protected_storage_unavailable") from exc

    def put(self, profile_id: str, secret: str) -> None:
        secret = validate_secret_value(secret)
        result = self._run(
            [
                "store",
                "--label=qCoder Context Bridge credential",
                "service",
                "qcoder",
                "profile",
                profile_id,
            ],
            stdin=secret,
        )
        if result.returncode != 0:
            raise CredentialProfileError("protected_storage_write_failed")

    def get(self, profile_id: str) -> str:
        result = self._run(["lookup", "service", "qcoder", "profile", profile_id])
        if result.returncode != 0:
            raise CredentialProfileError("selected_profile_secret_unavailable")
        try:
            return validate_secret_value(result.stdout)
        except CredentialProfileError as exc:
            raise CredentialProfileError("selected_profile_secret_malformed") from exc

    def delete(self, profile_id: str) -> None:
        result = self._run(["clear", "service", "qcoder", "profile", profile_id])
        if result.returncode not in {0, 1}:
            raise CredentialProfileError("protected_storage_delete_failed")


class WindowsDpapiStore:
    """Windows current-user DPAPI with one encrypted blob per local profile."""

    kind = "windows_dpapi"

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def __init__(self, root: Path):
        self.root = root

    def available(self) -> bool:
        return os.name == "nt" and hasattr(ctypes, "windll")

    def _path(self, profile_id: str) -> Path:
        if PROFILE_ID_PATTERN.fullmatch(profile_id) is None:
            raise CredentialProfileError("profile_id_invalid")
        return self.root / f"{profile_id}.dpapi"

    @classmethod
    def _blob(cls, raw: bytes) -> tuple["WindowsDpapiStore._Blob", Any]:
        buffer = ctypes.create_string_buffer(raw)
        return cls._Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _crypt(self, raw: bytes, *, protect: bool) -> bytes:
        if not self.available():
            raise CredentialProfileError("protected_storage_unavailable")
        source, source_buffer = self._blob(raw)
        output = self._Blob()
        function = (
            ctypes.windll.crypt32.CryptProtectData
            if protect
            else ctypes.windll.crypt32.CryptUnprotectData
        )
        description = wintypes.LPWSTR()
        arguments: list[Any] = [
            ctypes.byref(source),
            None if protect else ctypes.byref(description),
            None,
            None,
            None,
            0x1,
            ctypes.byref(output),
        ]
        if not function(*arguments):
            raise CredentialProfileError("protected_storage_operation_failed")
        try:
            # Keep the input allocation alive through the native call.
            del source_buffer
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            if description:
                ctypes.windll.kernel32.LocalFree(description)

    def put(self, profile_id: str, secret: str) -> None:
        path = self._path(profile_id)
        if path.exists() or path.is_symlink():
            raise CredentialProfileError("profile_secret_already_exists")
        encrypted = self._crypt(validate_secret_value(secret).encode("ascii"), protect=True)
        _atomic_private_write(path, base64.b64encode(encrypted) + b"\n")

    def get(self, profile_id: str) -> str:
        raw = _require_safe_file(
            self._path(profile_id), missing_category="selected_profile_secret_missing"
        )
        try:
            encrypted = base64.b64decode(raw.strip(), validate=True)
            return validate_secret_value(self._crypt(encrypted, protect=False).decode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise CredentialProfileError("selected_profile_secret_malformed") from exc

    def delete(self, profile_id: str) -> None:
        path = self._path(profile_id)
        if path.is_symlink():
            raise CredentialProfileError("profile_secret_symlink_rejected")
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialProfileError("profile_secret_delete_failed") from exc


@dataclass(frozen=True)
class SelectedCredential:
    profile_id: str
    label: str
    credential_reference: str
    account_label: str
    storage_kind: str
    selection_source: str
    secret: str = field(repr=False)
    legacy: bool = False

    def safe_metadata(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "credential_reference": self.credential_reference,
            "account_label": self.account_label,
            "storage_kind": self.storage_kind,
            "selection_source": self.selection_source,
            "legacy": self.legacy,
            "secret_included": False,
        }


class CredentialProfileManager:
    def __init__(
        self,
        *,
        registry_file: Path | None = None,
        legacy_token_file: Path | None = None,
        protected_store: SecretStore | None = None,
        fallback_store: SecretStore | None = None,
        profile_id_factory: Callable[[], str] | None = None,
    ):
        self.registry_file = registry_file or default_registry_file()
        self.migration_journal_file = self.registry_file.with_name("legacy-migration.json")
        self.legacy_token_file = legacy_token_file or default_legacy_token_file()
        root = self.registry_file.parent
        if protected_store is None:
            protected_store = (
                WindowsDpapiStore(root / "protected-secrets")
                if os.name == "nt"
                else SecretToolStore()
            )
        self.protected_store = protected_store
        self.fallback_store = fallback_store or HardenedFileSecretStore(root / "profile-secrets")
        self.profile_id_factory = profile_id_factory or (lambda: f"qcp-{secrets.token_hex(12)}")

    @staticmethod
    def _empty_registry() -> dict[str, Any]:
        return {
            "schema_id": PROFILE_REGISTRY_SCHEMA_ID,
            "schema_version": PROFILE_REGISTRY_SCHEMA_VERSION,
            "default_profile_id": None,
            "profiles": [],
        }

    def _validate_registry(self, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CredentialProfileError("profile_registry_invalid")
        if set(value) != {"schema_id", "schema_version", "default_profile_id", "profiles"}:
            raise CredentialProfileError("profile_registry_shape_invalid")
        if (
            value.get("schema_id") != PROFILE_REGISTRY_SCHEMA_ID
            or value.get("schema_version") != PROFILE_REGISTRY_SCHEMA_VERSION
        ):
            raise CredentialProfileError("profile_registry_schema_unsupported")
        profiles = value.get("profiles")
        if not isinstance(profiles, list):
            raise CredentialProfileError("profile_registry_profiles_invalid")
        validated: list[dict[str, Any]] = []
        ids: set[str] = set()
        labels: set[str] = set()
        for profile in profiles:
            if not isinstance(profile, dict) or set(profile) != {
                "profile_id",
                "label",
                "credential_reference",
                "account_label",
                "client_label",
                "device_label",
                "workspace_label",
                "client_selector",
                "workspace_selector",
                "storage_kind",
            }:
                raise CredentialProfileError("profile_metadata_shape_invalid")
            profile_id = str(profile.get("profile_id") or "")
            if PROFILE_ID_PATTERN.fullmatch(profile_id) is None or profile_id in ids:
                raise CredentialProfileError("profile_id_invalid")
            label = _safe_text(profile.get("label"), field="profile_label")
            label_key = label.casefold()
            if label_key in labels or label_key == LEGACY_PROFILE_LABEL.casefold():
                raise CredentialProfileError("profile_label_duplicate")
            credential_reference = str(profile.get("credential_reference") or "")
            if CREDENTIAL_REFERENCE_PATTERN.fullmatch(credential_reference) is None:
                raise CredentialProfileError("credential_reference_invalid")
            storage_kind = str(profile.get("storage_kind") or "")
            if storage_kind not in {self.protected_store.kind, self.fallback_store.kind}:
                raise CredentialProfileError("profile_storage_kind_unsupported")
            normalized = dict(profile)
            for metadata_field in (
                "account_label",
                "client_label",
                "device_label",
                "workspace_label",
                "client_selector",
                "workspace_selector",
            ):
                normalized[metadata_field] = _safe_text(
                    profile.get(metadata_field),
                    field=metadata_field,
                    required=metadata_field == "account_label",
                )
            normalized["label"] = label
            ids.add(profile_id)
            labels.add(label_key)
            validated.append(normalized)
        default_profile_id = value.get("default_profile_id")
        valid_defaults = ids | ({LEGACY_PROFILE_ID} if self.legacy_token_file.exists() else set())
        if default_profile_id is not None and default_profile_id not in valid_defaults:
            raise CredentialProfileError("default_profile_invalid")
        return {
            "schema_id": PROFILE_REGISTRY_SCHEMA_ID,
            "schema_version": PROFILE_REGISTRY_SCHEMA_VERSION,
            "default_profile_id": default_profile_id,
            "profiles": sorted(validated, key=lambda item: item["profile_id"]),
        }

    def read_registry(self) -> dict[str, Any]:
        if not self.registry_file.exists() and not self.registry_file.is_symlink():
            return self._empty_registry()
        raw = _require_safe_file(self.registry_file, missing_category="profile_registry_unreadable")
        try:
            return self._validate_registry(json.loads(raw.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialProfileError("profile_registry_invalid") from exc

    def write_registry(self, registry: Mapping[str, Any]) -> None:
        validated = self._validate_registry(dict(registry))
        _atomic_private_write(self.registry_file, _canonical_json(validated))

    def _store_for_kind(self, kind: str) -> SecretStore:
        if kind == self.protected_store.kind:
            return self.protected_store
        if kind == self.fallback_store.kind:
            return self.fallback_store
        raise CredentialProfileError("profile_storage_kind_unsupported")

    def _choose_store(self, storage: str, *, allow_hardened_file_fallback: bool) -> SecretStore:
        if storage not in {"auto", "protected", "hardened-file"}:
            raise CredentialProfileError("profile_storage_selection_invalid")
        if storage in {"auto", "protected"} and self.protected_store.available():
            return self.protected_store
        if storage == "protected":
            raise CredentialProfileError("protected_storage_unavailable")
        if storage == "hardened-file" or allow_hardened_file_fallback:
            return self.fallback_store
        raise CredentialProfileError(
            "protected_storage_unavailable_hardened_file_confirmation_required"
        )

    def preflight_storage(
        self, *, storage: str, allow_hardened_file_fallback: bool
    ) -> dict[str, object]:
        store = self._choose_store(
            storage, allow_hardened_file_fallback=allow_hardened_file_fallback
        )
        return {
            "ok": True,
            "storage_kind": store.kind,
            "protected_storage_selected": store is self.protected_store,
            "hardened_file_fallback_explicit": store is self.fallback_store,
            "secret_prompted": False,
            "secret_included": False,
        }

    @staticmethod
    def _profile_safe(profile: Mapping[str, Any], *, is_default: bool) -> dict[str, object]:
        return {
            "profile_id": profile["profile_id"],
            "label": profile["label"],
            "credential_reference": profile["credential_reference"],
            "account_label": profile["account_label"],
            "client_label": profile["client_label"],
            "device_label": profile["device_label"],
            "workspace_label": profile["workspace_label"],
            "client_binding_configured": bool(profile["client_selector"]),
            "workspace_binding_configured": bool(profile["workspace_selector"]),
            "storage_kind": profile["storage_kind"],
            "default": is_default,
            "legacy": False,
            "secret_included": False,
        }

    def list_safe(self) -> list[dict[str, object]]:
        registry = self.read_registry()
        rows = [
            self._profile_safe(
                profile, is_default=registry["default_profile_id"] == profile["profile_id"]
            )
            for profile in registry["profiles"]
        ]
        if self.legacy_token_file.exists() or registry["default_profile_id"] == LEGACY_PROFILE_ID:
            rows.append(
                {
                    "profile_id": LEGACY_PROFILE_ID,
                    "label": LEGACY_PROFILE_LABEL,
                    "credential_reference": "legacy-file-no-account-center-reference",
                    "account_label": "Legacy local configuration",
                    "client_label": "",
                    "device_label": "",
                    "workspace_label": "",
                    "client_binding_configured": False,
                    "workspace_binding_configured": False,
                    "storage_kind": "legacy_hardened_file",
                    "default": (
                        registry["default_profile_id"] == LEGACY_PROFILE_ID
                        or (
                            not self.registry_file.exists()
                            and not registry["profiles"]
                            and self.legacy_token_file.exists()
                        )
                    ),
                    "legacy": True,
                    "secret_included": False,
                }
            )
        return sorted(rows, key=lambda item: str(item["profile_id"]))

    def create_profile(
        self,
        *,
        label: str,
        credential_reference: str,
        account_label: str,
        secret: str,
        client_label: str = "",
        device_label: str = "",
        workspace_label: str = "",
        client_selector: str = "",
        workspace_selector: str = "",
        storage: str = "auto",
        allow_hardened_file_fallback: bool = False,
        set_default: bool = False,
        validator: Callable[[str], bool] | None = None,
        _profile_id: str | None = None,
    ) -> dict[str, object]:
        registry = self.read_registry()
        profile_id = _profile_id or self.profile_id_factory()
        if PROFILE_ID_PATTERN.fullmatch(profile_id) is None:
            raise CredentialProfileError("profile_id_factory_invalid")
        if any(item["profile_id"] == profile_id for item in registry["profiles"]):
            raise CredentialProfileError("profile_id_collision")
        profile = {
            "profile_id": profile_id,
            "label": _safe_text(label, field="profile_label"),
            "credential_reference": str(credential_reference).strip(),
            "account_label": _safe_text(account_label, field="account_label"),
            "client_label": _safe_text(client_label, field="client_label", required=False),
            "device_label": _safe_text(device_label, field="device_label", required=False),
            "workspace_label": _safe_text(workspace_label, field="workspace_label", required=False),
            "client_selector": _safe_text(client_selector, field="client_selector", required=False),
            "workspace_selector": _safe_text(
                workspace_selector, field="workspace_selector", required=False
            ),
            "storage_kind": "",
        }
        if CREDENTIAL_REFERENCE_PATTERN.fullmatch(profile["credential_reference"]) is None:
            raise CredentialProfileError("credential_reference_invalid")
        if profile["label"].casefold() == LEGACY_PROFILE_LABEL.casefold() or any(
            item["label"].casefold() == profile["label"].casefold() for item in registry["profiles"]
        ):
            raise CredentialProfileError("profile_label_duplicate")
        secret = validate_secret_value(secret)
        store = self._choose_store(
            storage, allow_hardened_file_fallback=allow_hardened_file_fallback
        )
        profile["storage_kind"] = store.kind
        store.put(profile_id, secret)
        try:
            stored_secret = store.get(profile_id)
            if validator is not None and validator(stored_secret) is not True:
                raise CredentialProfileError("credential_validation_failed")
            registry["profiles"].append(profile)
            if set_default:
                registry["default_profile_id"] = profile_id
            elif registry["default_profile_id"] is None and self.legacy_token_file.exists():
                registry["default_profile_id"] = LEGACY_PROFILE_ID
            self.write_registry(registry)
        except Exception:
            store.delete(profile_id)
            raise
        return self._profile_safe(profile, is_default=set_default)

    def _find_profile(self, registry: Mapping[str, Any], selector: str) -> dict[str, Any]:
        if selector == LEGACY_PROFILE_ID or selector.casefold() == LEGACY_PROFILE_LABEL.casefold():
            if not self.legacy_token_file.exists():
                raise CredentialProfileError("legacy_default_missing")
            return {"profile_id": LEGACY_PROFILE_ID}
        matches = [
            profile
            for profile in registry["profiles"]
            if profile["profile_id"] == selector
            or profile["label"].casefold() == selector.casefold()
        ]
        if len(matches) != 1:
            raise CredentialProfileError(
                "profile_selection_not_found" if not matches else "profile_selection_ambiguous"
            )
        return matches[0]

    def _load_selected(self, profile: Mapping[str, Any], *, source: str) -> SelectedCredential:
        if profile["profile_id"] == LEGACY_PROFILE_ID:
            raw = _require_safe_file(
                self.legacy_token_file, missing_category="legacy_default_missing"
            )
            try:
                secret = validate_secret_value(raw.decode("utf-8"))
            except (UnicodeError, CredentialProfileError) as exc:
                raise CredentialProfileError("legacy_default_malformed") from exc
            return SelectedCredential(
                profile_id=LEGACY_PROFILE_ID,
                label=LEGACY_PROFILE_LABEL,
                credential_reference="legacy-file-no-account-center-reference",
                account_label="Legacy local configuration",
                storage_kind="legacy_hardened_file",
                selection_source=source,
                secret=secret,
                legacy=True,
            )
        store = self._store_for_kind(str(profile["storage_kind"]))
        try:
            secret = store.get(str(profile["profile_id"]))
        except CredentialProfileError:
            raise
        return SelectedCredential(
            profile_id=str(profile["profile_id"]),
            label=str(profile["label"]),
            credential_reference=str(profile["credential_reference"]),
            account_label=str(profile["account_label"]),
            storage_kind=str(profile["storage_kind"]),
            selection_source=source,
            secret=secret,
        )

    def select(
        self,
        *,
        explicit_profile: str | None = None,
        client_selector: str | None = None,
        workspace_selector: str | None = None,
    ) -> SelectedCredential:
        registry = self.read_registry()
        if explicit_profile:
            profile = self._find_profile(registry, explicit_profile)
            return self._load_selected(profile, source="explicit_invocation")

        client = _safe_text(client_selector, field="client_selector", required=False)
        workspace = _safe_text(workspace_selector, field="workspace_selector", required=False)
        bound = []
        for profile in registry["profiles"]:
            configured_client = str(profile["client_selector"])
            configured_workspace = str(profile["workspace_selector"])
            if not configured_client and not configured_workspace:
                continue
            if configured_client and configured_client != client:
                continue
            if configured_workspace and configured_workspace != workspace:
                continue
            bound.append(profile)
        unique_bound = {profile["profile_id"]: profile for profile in bound}
        if len(unique_bound) == 1:
            return self._load_selected(
                next(iter(unique_bound.values())), source="configured_client_or_workspace"
            )
        if len(unique_bound) > 1:
            raise CredentialProfileError(
                "profile_selection_ambiguous", choices=self._choice_list(unique_bound.values())
            )

        default_profile = registry["default_profile_id"]
        if (
            default_profile is None
            and not self.registry_file.exists()
            and self.legacy_token_file.exists()
        ):
            default_profile = LEGACY_PROFILE_ID
        if isinstance(default_profile, str):
            return self._load_selected(
                self._find_profile(registry, default_profile), source="customer_selected_default"
            )
        raise CredentialProfileError(
            "profile_selection_required", choices=self._choice_list(registry["profiles"])
        )

    @staticmethod
    def _choice_list(profiles: Any) -> list[dict[str, str]]:
        return sorted(
            [
                {
                    "profile_id": str(profile["profile_id"]),
                    "label": str(profile["label"]),
                    "account_label": str(profile["account_label"]),
                    "client_label": str(profile["client_label"]),
                    "device_label": str(profile["device_label"]),
                    "workspace_label": str(profile["workspace_label"]),
                }
                for profile in profiles
            ],
            key=lambda item: item["profile_id"],
        )

    def set_default(self, selector: str | None) -> dict[str, object]:
        registry = self.read_registry()
        if selector is None:
            registry["default_profile_id"] = None
            self.write_registry(registry)
            return {"ok": True, "default_profile_id": None, "secret_included": False}
        profile = self._find_profile(registry, selector)
        registry["default_profile_id"] = profile["profile_id"]
        self.write_registry(registry)
        return {
            "ok": True,
            "default_profile_id": profile["profile_id"],
            "secret_included": False,
        }

    def replace_credential(
        self,
        *,
        selector: str,
        credential_reference: str,
        secret: str,
        validator: Callable[[str], bool] | None = None,
    ) -> dict[str, object]:
        registry = self.read_registry()
        profile = self._find_profile(registry, selector)
        if profile["profile_id"] == LEGACY_PROFILE_ID:
            raise CredentialProfileError("legacy_default_replacement_unsupported")
        reference = credential_reference.strip()
        if CREDENTIAL_REFERENCE_PATTERN.fullmatch(reference) is None:
            raise CredentialProfileError("credential_reference_invalid")
        secret = validate_secret_value(secret)
        store = self._store_for_kind(str(profile["storage_kind"]))
        profile_id = str(profile["profile_id"])
        previous_secret = store.get(profile_id)
        previous_reference = str(profile["credential_reference"])
        store.delete(profile_id)
        try:
            store.put(profile_id, secret)
            stored_secret = store.get(profile_id)
            if validator is not None and validator(stored_secret) is not True:
                raise CredentialProfileError("credential_validation_failed")
        except Exception:
            try:
                store.delete(profile_id)
                store.put(profile_id, previous_secret)
            except Exception:
                raise CredentialProfileError("credential_replacement_rollback_failed") from None
            raise CredentialProfileError(
                "credential_replacement_rejected_original_restored"
            ) from None
        profile["credential_reference"] = reference
        try:
            self.write_registry(registry)
        except Exception:
            try:
                store.delete(profile_id)
                store.put(profile_id, previous_secret)
                profile["credential_reference"] = previous_reference
            except Exception:
                raise CredentialProfileError("credential_replacement_rollback_failed") from None
            raise CredentialProfileError(
                "credential_replacement_rejected_original_restored"
            ) from None
        return {
            "ok": True,
            "profile_id": profile["profile_id"],
            "credential_reference": reference,
            "deliberate_replacement_adopted": True,
            "secret_included": False,
        }

    def remove_profile(self, selector: str, *, confirmed: bool = False) -> dict[str, object]:
        if not confirmed:
            return {
                "ok": False,
                "category": "profile_removal_confirmation_required",
                "secret_included": False,
            }
        registry = self.read_registry()
        profile = self._find_profile(registry, selector)
        if profile["profile_id"] == LEGACY_PROFILE_ID:
            raise CredentialProfileError("legacy_default_removal_unsupported")
        profile_id = str(profile["profile_id"])
        if registry["default_profile_id"] == profile_id:
            raise CredentialProfileError("default_profile_must_be_changed_before_removal")
        store = self._store_for_kind(str(profile["storage_kind"]))
        previous_secret = store.get(profile_id)
        store.delete(profile_id)
        registry["profiles"] = [
            item for item in registry["profiles"] if item["profile_id"] != profile_id
        ]
        try:
            self.write_registry(registry)
        except Exception:
            try:
                store.put(profile_id, previous_secret)
            except Exception:
                raise CredentialProfileError("profile_removal_rollback_failed") from None
            raise CredentialProfileError("profile_removal_rejected_original_restored") from None
        return {
            "ok": True,
            "profile_id": profile_id,
            "profile_removed": True,
            "secret_removed": True,
            "legacy_unchanged": True,
            "secret_included": False,
        }

    def migrate_legacy(
        self,
        *,
        label: str,
        credential_reference: str,
        account_label: str,
        storage: str = "auto",
        allow_hardened_file_fallback: bool = False,
        set_default: bool = False,
        validator: Callable[[str], bool] | None = None,
        confirmed: bool = False,
        **metadata: str,
    ) -> dict[str, object]:
        self.recover_incomplete_migration()
        if not confirmed:
            return {
                "ok": False,
                "category": "legacy_migration_confirmation_required",
                "legacy_unchanged": True,
                "secret_included": False,
            }
        raw = _require_safe_file(self.legacy_token_file, missing_category="legacy_default_missing")
        try:
            legacy_secret = validate_secret_value(raw.decode("utf-8"))
        except (UnicodeError, CredentialProfileError) as exc:
            raise CredentialProfileError("legacy_default_malformed") from exc
        store = self._choose_store(
            storage, allow_hardened_file_fallback=allow_hardened_file_fallback
        )
        profile_id = self.profile_id_factory()
        if PROFILE_ID_PATTERN.fullmatch(profile_id) is None:
            raise CredentialProfileError("profile_id_factory_invalid")
        _atomic_private_write(
            self.migration_journal_file,
            _canonical_json(
                {
                    "schema_id": MIGRATION_JOURNAL_SCHEMA_ID,
                    "profile_id": profile_id,
                    "storage_kind": store.kind,
                }
            ),
        )
        try:
            result = self.create_profile(
                label=label,
                credential_reference=credential_reference,
                account_label=account_label,
                secret=legacy_secret,
                storage=storage,
                allow_hardened_file_fallback=allow_hardened_file_fallback,
                set_default=set_default,
                validator=validator,
                _profile_id=profile_id,
                **metadata,
            )
        except Exception:
            self.recover_incomplete_migration()
            raise
        self.migration_journal_file.unlink(missing_ok=True)
        result.update(
            {
                "ok": True,
                "migration_validated": validator is not None,
                "legacy_unchanged": True,
                "legacy_retirement_offered": validator is not None,
                "legacy_deleted": False,
                "legacy_overwritten": False,
                "raw_token_backup_created": False,
                "secret_included": False,
            }
        )
        return result

    def recover_incomplete_migration(self) -> dict[str, object]:
        if (
            not self.migration_journal_file.exists()
            and not self.migration_journal_file.is_symlink()
        ):
            return {
                "ok": True,
                "recovery_required": False,
                "secret_included": False,
            }
        raw = _require_safe_file(
            self.migration_journal_file,
            missing_category="legacy_migration_journal_unreadable",
        )
        try:
            journal = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialProfileError("legacy_migration_journal_invalid") from exc
        if not isinstance(journal, dict) or set(journal) != {
            "schema_id",
            "profile_id",
            "storage_kind",
        }:
            raise CredentialProfileError("legacy_migration_journal_invalid")
        if journal.get("schema_id") != MIGRATION_JOURNAL_SCHEMA_ID:
            raise CredentialProfileError("legacy_migration_journal_invalid")
        profile_id = str(journal.get("profile_id") or "")
        if PROFILE_ID_PATTERN.fullmatch(profile_id) is None:
            raise CredentialProfileError("legacy_migration_journal_invalid")
        registry = self.read_registry()
        committed = any(profile["profile_id"] == profile_id for profile in registry["profiles"])
        if not committed:
            self._store_for_kind(str(journal.get("storage_kind") or "")).delete(profile_id)
        try:
            self.migration_journal_file.unlink()
        except OSError as exc:
            raise CredentialProfileError("legacy_migration_recovery_incomplete") from exc
        return {
            "ok": True,
            "recovery_required": True,
            "committed_profile_preserved": committed,
            "orphan_secret_removed": not committed,
            "legacy_unchanged": True,
            "secret_included": False,
        }


def safe_profile_error(error: CredentialProfileError) -> dict[str, object]:
    result: dict[str, object] = {
        "ok": False,
        "category": error.category,
        "secret_included": False,
        "raw_secret_printed": False,
    }
    if error.choices:
        result["choices"] = error.choices
        result["next_action"] = "select_one_profile_explicitly"
    elif error.category in {
        "profile_selection_required",
        "profile_selection_ambiguous",
    }:
        result["next_action"] = "select_one_profile_explicitly"
    elif error.category.startswith("protected_storage_unavailable"):
        result["next_action"] = (
            "choose_hardened_file_fallback_explicitly_or_enable_protected_storage"
        )
    elif "secret" in error.category or error.category.startswith("legacy_default"):
        result["next_action"] = "repair_the_selected_profile_without_selecting_another_profile"
    return result


def hidden_secret_prompt(prompt: str = "Context Bridge credential (input hidden): ") -> str:
    return getpass.getpass(prompt)


def platform_storage_capability() -> dict[str, object]:
    manager = CredentialProfileManager()
    return {
        "platform": platform.system().lower(),
        "protected_storage_kind": manager.protected_store.kind,
        "protected_storage_available": manager.protected_store.available(),
        "hardened_file_fallback_available": manager.fallback_store.available(),
        "hardened_file_fallback_requires_explicit_selection": True,
        "secret_included": False,
    }


def credential_profile_contract_snapshot() -> dict[str, object]:
    return {
        "schema_id": PROFILE_REGISTRY_SCHEMA_ID,
        "schema_version": PROFILE_REGISTRY_SCHEMA_VERSION,
        "profile_identity": "stable_nonsecret_local_id",
        "credential_reference": "stable_nonsecret_account_center_reference",
        "credential_reference_authenticates": False,
        "secret_separate_from_metadata": True,
        "selection_precedence": [
            "explicit_invocation_profile",
            "configured_client_or_workspace_profile",
            "customer_selected_default",
            "fail_closed",
        ],
        "multiple_matches": "safe_nonsecret_choice_list_and_one_bounded_next_action",
        "implicit_selection_prohibited": [
            "newest_credential",
            "first_file",
            "first_profile",
            "timestamp",
            "cross_account",
        ],
        "selected_rejection_fallback": False,
        "selected_replacement_adoption": "explicit",
        "protected_storage_preferred": True,
        "hardened_file_fallback": "explicit_one_secret_per_profile_mode_0600",
        "legacy_profile_id": LEGACY_PROFILE_ID,
        "legacy_profile_label": LEGACY_PROFILE_LABEL,
        "legacy_migration": {
            "explicit": True,
            "validated_before_completion": True,
            "legacy_file_deleted": False,
            "legacy_file_overwritten": False,
            "raw_token_backup": False,
            "rollback_supported": True,
        },
        "secret_in_status_or_diagnostics": False,
        "public_context_bridge_tool_added": False,
    }


__all__ = [
    "CREDENTIAL_REFERENCE_PATTERN",
    "CredentialProfileError",
    "CredentialProfileManager",
    "HardenedFileSecretStore",
    "LEGACY_PROFILE_ID",
    "LEGACY_PROFILE_LABEL",
    "PROFILE_REGISTRY_SCHEMA_ID",
    "PROFILE_REGISTRY_SCHEMA_VERSION",
    "SecretStore",
    "SelectedCredential",
    "default_legacy_token_file",
    "default_profiles_root",
    "default_registry_file",
    "hidden_secret_prompt",
    "credential_profile_contract_snapshot",
    "platform_storage_capability",
    "safe_profile_error",
    "validate_secret_value",
]
