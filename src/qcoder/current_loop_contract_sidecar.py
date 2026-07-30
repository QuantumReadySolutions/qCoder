"""Secure optional loop-bound browser controls for the Current Loop Contract.

The sidecar is an ephemeral loopback authority surface.  It delegates all
domain decisions and state mutation to ``CurrentLoopCoordinator`` and has no
hosted transport, credential, discovery, execution, or project-edit endpoint.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from typing import Any, Mapping

from qcoder.current_loop_bounded_control import (
    bounded_control_contract_snapshot,
    bounded_control_contracts,
)
from qcoder.current_loop_contract import (
    GENERATION_GOVERNANCE_VALUES,
    policy_summary,
)
from qcoder.current_loop_run_summary import (
    evidence_view_contract_snapshot,
    run_summary_contract_snapshot,
)


SIDECAR_SCHEMA_ID = "qcoder.current_loop.contract_sidecar.v2"
SIDECAR_SCHEMA_VERSION = 2
SIDECAR_CAPABILITY_HEADER = "X-QCoder-Sidecar-Capability"
SIDECAR_SESSION_HEADER = "X-QCoder-Sidecar-Session"
SIDECAR_MAX_REQUEST_BYTES = 65_536
DEFAULT_IDLE_TIMEOUT_SECONDS = 900
MINIMUM_CAPABILITY_BITS = 256

_MUTATION_ACTIONS = frozenset(
    {
        "set_preset",
        "set_generation_governance",
        "adjust",
        "confirm_broadening",
        "exclude_evidence",
        "restore_evidence",
        "delete_evidence",
        "stop_loop",
    }
)
_READ_ACTIONS = frozenset({"evidence_view"})
_ALL_ACTIONS = _MUTATION_ACTIONS | _READ_ACTIONS

_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>How qCoder should help with this build</title>
<link rel="stylesheet" href="/app.css">
</head><body>
<main>
<h1>How qCoder should help with this build</h1>
<p id="summary">Loading the current one-loop contract…</p>
<section aria-labelledby="presets"><h2 id="presets">Choose a participation level</h2>
<button data-preset="assist">Assist</button>
<button data-preset="evidence_only">Evidence only</button>
<button id="custom">Custom</button>
<button id="stop">Stop qCoder for this build</button></section>
<section aria-labelledby="governance"><h2 id="governance">Generation governance</h2>
<p>Adaptive keeps ordinary work quiet. Blueprint required confirms material choices first.</p>
<button data-governance="adaptive">Adaptive</button>
<button data-governance="blueprint_required">Blueprint required</button></section>
<section><h2>Everyday Assist behavior</h2><ul>
<li>Exact authorized outputs are collected and processed locally.</li>
<li>Share-safe derived run context may update the connected assistant.</li>
<li>Hosted enrichment and Build Review are on request.</li>
</ul></section>
<section id="custom-controls" hidden><h2>Custom controls</h2><div id="selection-graph"></div></section>
<section><h2>Evidence and views</h2><div id="evidence"></div><div id="views"></div></section>
<details><summary>Advanced canonical details</summary><pre id="advanced"></pre></details>
<p><button id="return">Return to the IDE</button></p>
<output id="notice" aria-live="polite"></output>
</main><script src="/app.js" defer></script></body></html>"""

_CSS = """body{font:16px system-ui,sans-serif;max-width:76rem;margin:2rem auto;padding:0 1rem;color:#18212b;background:#fafbfc}
main{background:white;border:1px solid #d8dee6;border-radius:12px;padding:1.5rem}
button{margin:.3rem;padding:.65rem .85rem;border:1px solid #667789;border-radius:7px;background:#f5f7fa}
button:hover{background:#e9eef5}pre{overflow:auto;background:#f5f7fa;padding:1rem}
#notice{display:block;margin-top:1rem;font-weight:600}.danger{color:#8b1e1e}"""

_JS = r"""(() => {
  const capability = decodeURIComponent(location.hash.slice(1));
  history.replaceState(null, "", location.pathname);
  let snapshot = null;
  const session = document.documentElement.dataset.session;
  const headers = () => ({
    "X-QCoder-Sidecar-Capability": capability,
    "X-QCoder-Sidecar-Session": session,
    "Content-Type": "application/json"
  });
  async function api(path, options={}) {
    const response = await fetch(path, {...options, headers:{...headers(), ...(options.headers||{})}});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error_category || "sidecar_request_failed");
    return body;
  }
  function makeSelect(options, label) {
    const select = document.createElement("select"); select.setAttribute("aria-label", label);
    options.forEach(item => { const option=document.createElement("option"); option.value=item.value; option.textContent=item.customer_meaning; select.append(option); });
    return select;
  }
  function render(value) {
    snapshot = value;
    document.getElementById("summary").textContent = value.effective_policy_summary;
    document.getElementById("advanced").textContent = JSON.stringify(value.advanced, null, 2);
    const graph=document.getElementById("selection-graph"); graph.replaceChildren();
    const category=makeSelect(value.selection_graph,"Evidence category");
    const dimension=document.createElement("select"); dimension.setAttribute("aria-label","Participation dimension");
    const policyValue=document.createElement("select"); policyValue.setAttribute("aria-label","Policy value");
    function dimensions(){ const row=value.selection_graph.find(item=>item.value===category.value); dimension.replaceChildren(); row.dimensions.forEach(item=>{const option=document.createElement("option"); option.value=item.value; option.textContent=item.customer_meaning; dimension.append(option);}); values(); }
    function values(){ const row=value.selection_graph.find(item=>item.value===category.value).dimensions.find(item=>item.value===dimension.value); policyValue.replaceChildren(); row.accepted_values.forEach(item=>{const option=document.createElement("option"); option.value=item.value; option.textContent=item.customer_meaning; policyValue.append(option);});}
    category.addEventListener("change",dimensions); dimension.addEventListener("change",values);
    const apply=document.createElement("button"); apply.textContent="Apply bounded change"; apply.addEventListener("click",()=>action("adjust",{category:category.value,dimension:dimension.value,value:policyValue.value}));
    graph.append(category,dimension,policyValue,apply); dimensions();
    const evidence=document.getElementById("evidence"); evidence.replaceChildren();
    if (!value.evidence_references.length) evidence.textContent="No eligible qCoder evidence is registered.";
    value.evidence_references.forEach(item=>{const line=document.createElement("p"); line.textContent=item.customer_meaning; evidence.append(line);});
    Object.entries(value.evidence_controls).forEach(([name, control])=>{
      const choices=control.fields.find(field=>field.name==="artifact_reference")?.accepted_values||[];
      if (!choices.length) return;
      const select=makeSelect(choices, name.replaceAll("_"," "));
      const button=document.createElement("button"); button.textContent=name.replaceAll("_"," ");
      button.addEventListener("click",()=>action(name,{artifact_reference:select.value,reason:"customer_excluded",explicit_authority:name==="delete_evidence"}));
      evidence.append(select,button);
    });
    if (value.pending_broadening) {
      const confirm=document.createElement("button"); confirm.textContent="Confirm the displayed broader contract"; confirm.addEventListener("click",()=>action("confirm_broadening",{explicit_authority:true})); graph.append(confirm);
    }
    const views=document.getElementById("views"); views.replaceChildren();
    value.evidence_views.forEach(item=>{const button=document.createElement("button"); button.textContent=item.customer_meaning; button.addEventListener("click",()=>action("evidence_view",{view_id:item.value})); views.append(button);});
  }
  async function refresh(){ render(await api("/api/snapshot")); }
  async function action(action, payload={}) {
    try {
      const result = await api("/api/action", {
        method:"POST",
        body:JSON.stringify({action, payload, expected_contract_revision:snapshot.contract_revision})
      });
      document.getElementById("notice").textContent = result.summary;
      if (!result.loop_closed) await refresh();
    } catch (error) {
      document.getElementById("notice").textContent = `Refresh required: ${error.message}`;
      document.getElementById("notice").className = "danger";
      await refresh();
    }
  }
  document.querySelectorAll("[data-preset]").forEach(button =>
    button.addEventListener("click", () => action("set_preset", {preset:button.dataset.preset})));
  document.querySelectorAll("[data-governance]").forEach(button =>
    button.addEventListener("click", () => action("set_generation_governance", {governance:button.dataset.governance})));
  document.getElementById("custom").addEventListener("click", () =>
    document.getElementById("custom-controls").hidden = false);
  document.getElementById("stop").addEventListener("click", () => {
    if (confirm("Stop qCoder for this build? This closes only the active loop.")) action("stop_loop", {explicit_authority:true});
  });
  document.getElementById("return").addEventListener("click", () => window.close());
  refresh().catch(error => { document.getElementById("notice").textContent = error.message; });
})();"""


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sidecar_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": SIDECAR_SCHEMA_ID,
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "network_binding": "127.0.0.1",
        "port": "random_ephemeral",
        "platform_behavior": {
            "linux": "native_loopback",
            "windows": "native_loopback",
            "wsl": "ordinary_localhost_forwarding_only",
            "remote_bridge": False,
            "automatic_browser_open_required": False,
        },
        "capability": {
            "minimum_entropy_bits": MINIMUM_CAPABILITY_BITS,
            "delivery": "url_fragment",
            "request_header": SIDECAR_CAPABILITY_HEADER,
            "cookies": False,
            "web_storage": False,
            "query_or_path": False,
        },
        "operations": sorted(_ALL_ACTIONS),
        "accepted_domains": {
            "bounded_controls": bounded_control_contract_snapshot(),
            "evidence_views": evidence_view_contract_snapshot(),
            "generation_governance": list(GENERATION_GOVERNANCE_VALUES),
        },
        "request_requires": [
            "loop_bound_capability",
            "sidecar_session_identity",
            "host_validation",
            "same_origin_validation",
            "expected_contract_revision_for_mutation",
        ],
        "canonical_replacement_contract_accepted": False,
        "hosted_operation_endpoint": False,
        "protected_operation_endpoint": False,
        "project_edit_endpoint": False,
        "execution_endpoint": False,
        "workspace_discovery": False,
        "credentials_required": False,
        "idle_timeout_seconds": DEFAULT_IDLE_TIMEOUT_SECONDS,
        "loop_close_terminates": True,
    }
    payload["contract_digest"] = _digest(payload)
    return payload


class SidecarSession:
    """One in-memory capability and one exact loop/workspace binding."""

    def __init__(
        self,
        *,
        workspace: str | Path,
        coordinator: Any,
        idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
        clock: Any = time.monotonic,
    ):
        self.workspace = Path(workspace).expanduser().absolute()
        self.coordinator = coordinator
        state = coordinator.store.read()
        self.loop_ref = str(state["loop_ref"])
        self.workspace_binding = str(state["workspace_root"])
        self.session_id = f"sidecar-{secrets.token_hex(16)}"
        self.capability = secrets.token_urlsafe(48)
        self.idle_timeout_seconds = max(30, int(idle_timeout_seconds))
        self.clock = clock
        self.last_activity = float(clock())
        self.closed = False

    def touch(self) -> None:
        self.last_activity = float(self.clock())

    def expired(self) -> bool:
        return self.closed or (self.clock() - self.last_activity) >= self.idle_timeout_seconds

    def validate_live_binding(self) -> Mapping[str, Any]:
        if self.expired():
            raise ValueError("sidecar_expired")
        state = self.coordinator.store.read()
        if state.get("loop_ref") != self.loop_ref:
            raise ValueError("sidecar_loop_stale")
        if state.get("workspace_root") != self.workspace_binding:
            raise ValueError("sidecar_workspace_stale")
        if state.get("activation_state") != "active":
            self.closed = True
            raise ValueError("sidecar_loop_closed")
        self.touch()
        return state

    def snapshot(self) -> dict[str, Any]:
        state = self.validate_live_binding()
        contract = state["current_loop_contract"]
        controls = bounded_control_contracts(
            state, artifact_directory=self.coordinator.artifact_directory
        )
        evidence_refs = []
        for operation in ("evidence_exclude", "evidence_restore", "evidence_delete"):
            for field in controls[operation].get("fields", []):
                if field.get("name") == "artifact_reference":
                    evidence_refs.extend(field.get("accepted_values", []))
        unique = {str(item["value"]): deepcopy(dict(item)) for item in evidence_refs}
        return {
            "schema_id": SIDECAR_SCHEMA_ID,
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "sidecar_session_id": self.session_id,
            "workspace_label": self.workspace.name,
            "loop_label": self.loop_ref[-8:],
            "contract_revision": int(contract["contract_revision"]),
            "state_revision": int(state["state_revision"]),
            "effective_preset": contract["effective_preset"],
            "generation_governance": contract["generation_governance"],
            "generation_governance_options": [
                {
                    "value": "adaptive",
                    "customer_meaning": "Adaptive — proceed quietly unless a material decision is required.",
                },
                {
                    "value": "blueprint_required",
                    "customer_meaning": "Blueprint required — confirm material choices before generation.",
                },
            ],
            "quiet_everyday_behavior": deepcopy(contract["quiet_communication_policy"]),
            "iteration_context_policy": deepcopy(contract["iteration_context_policy"]),
            "effective_policy_summary": policy_summary(contract["effective_preset"]),
            "selection_graph": controls["contract_adjust"]["valid_selection_graph"]["categories"],
            "preset_options": controls["contract_set_preset"]["fields"][0]["accepted_values"],
            "pending_broadening": deepcopy(contract["pending_broadening_proposal"]),
            "evidence_references": list(unique.values()),
            "evidence_controls": {
                name: deepcopy(controls[operation])
                for name, operation in {
                    "exclude_evidence": "evidence_exclude",
                    "restore_evidence": "evidence_restore",
                    "delete_evidence": "evidence_delete",
                }.items()
            },
            "evidence_views": evidence_view_contract_snapshot()["views"],
            "run_summary": run_summary_contract_snapshot(),
            "separate_authority_still_required": [
                "IDE write or run",
                "raw assistant exposure",
                "artifact review",
                "governing Blueprint change",
                "external service or hardware",
            ],
            "build_review": {
                "optional": True,
                "browser_can_invoke_protected": False,
                "ordinary_language_action": "Ask qCoder in the IDE to review this build.",
            },
            "advanced": {
                "contract_schema_id": contract["schema_id"],
                "contract_schema_version": contract["schema_version"],
                "contract_revision": contract["contract_revision"],
                "state_revision": state["state_revision"],
                "effective_policy_digest": contract["effective_policy_digest"],
                "canonical_format": "JSON",
                "yaml_authoritative": False,
            },
            "raw_project_content_included": False,
            "credential_content_included": False,
        }

    def action(
        self,
        *,
        action: str,
        payload: Mapping[str, Any],
        expected_contract_revision: int,
    ) -> dict[str, Any]:
        state = self.validate_live_binding()
        if expected_contract_revision != state["current_loop_contract"]["contract_revision"]:
            raise ValueError("sidecar_contract_revision_stale")
        if action not in _ALL_ACTIONS:
            raise ValueError("sidecar_action_unsupported")
        if action == "set_preset":
            result = self.coordinator.contract_set_preset(
                preset=str(payload.get("preset") or ""),
                expected_contract_revision=expected_contract_revision,
            )
        elif action == "set_generation_governance":
            result = self.coordinator.contract_set_generation_governance(
                governance=str(payload.get("governance") or ""),
                expected_contract_revision=expected_contract_revision,
            )
        elif action == "adjust":
            result = self.coordinator.contract_adjust(
                category=str(payload.get("category") or ""),
                dimension=str(payload.get("dimension") or ""),
                value=str(payload.get("value") or ""),
                expected_contract_revision=expected_contract_revision,
            )
        elif action == "confirm_broadening":
            result = self.coordinator.contract_confirm_broadening(
                expected_contract_revision=expected_contract_revision,
                explicit_authority=payload.get("explicit_authority") is True,
            )
        elif action == "exclude_evidence":
            result = self.coordinator.evidence_exclude(
                artifact_reference=str(payload.get("artifact_reference") or ""),
                reason=str(payload.get("reason") or ""),
                expected_contract_revision=expected_contract_revision,
            )
        elif action == "restore_evidence":
            result = self.coordinator.evidence_restore(
                artifact_reference=str(payload.get("artifact_reference") or ""),
                expected_contract_revision=expected_contract_revision,
            )
        elif action == "delete_evidence":
            result = self.coordinator.evidence_delete(
                artifact_reference=str(payload.get("artifact_reference") or ""),
                expected_contract_revision=expected_contract_revision,
                explicit_authority=payload.get("explicit_authority") is True,
            )
        elif action == "stop_loop":
            result = self.coordinator.abandon(
                explicit_authority=payload.get("explicit_authority") is True
            )
            if result.get("ok"):
                self.closed = True
        else:
            result = self.coordinator.evidence_view(
                view_id=str(payload.get("view_id") or ""),
                selected_run_reference=(
                    str(payload["selected_run_reference"])
                    if payload.get("selected_run_reference") is not None
                    else None
                ),
                destination="local_presentation",
            )
        self.touch()
        return {
            "ok": bool(result.get("ok")),
            "category": result.get("category"),
            "summary": str(result.get("customer_summary") or result.get("summary") or ""),
            "details": deepcopy(result.get("details", {})),
            "loop_closed": self.closed,
            "hosted_operation_invoked": False,
            "protected_operation_invoked": False,
            "canonical_contract_replacement_accepted": False,
        }


class _SidecarServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address: tuple[str, int], session: SidecarSession):
        super().__init__(address, _SidecarHandler)
        self.session = session


class _SidecarHandler(BaseHTTPRequestHandler):
    server: _SidecarServer
    server_version = "qCoderContractSidecar/1"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _security_headers(self, *, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; font-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _send(self, status: int, body: bytes, *, content_type: str) -> None:
        self.send_response(status)
        self._security_headers(content_type=content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Mapping[str, Any]) -> None:
        self._send(
            status,
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    def _api_error(self, category: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._json(
            int(status),
            {
                "schema_id": SIDECAR_SCHEMA_ID,
                "error_category": category,
                "assistant_should_stop_or_refresh": True,
                "hosted_operation_permitted": False,
                "raw_content_echoed": False,
            },
        )

    def _validate_host(self) -> bool:
        expected = f"127.0.0.1:{self.server.server_port}"
        return self.headers.get("Host") == expected

    def _validate_api(self, *, mutation: bool) -> str | None:
        if not self._validate_host():
            return "sidecar_host_invalid"
        if self.headers.get(SIDECAR_SESSION_HEADER) != self.server.session.session_id:
            return "sidecar_session_invalid"
        supplied = self.headers.get(SIDECAR_CAPABILITY_HEADER)
        if not isinstance(supplied, str) or not secrets.compare_digest(
            supplied, self.server.session.capability
        ):
            return "sidecar_capability_invalid"
        expected_origin = f"http://127.0.0.1:{self.server.server_port}"
        origin = self.headers.get("Origin")
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if mutation and origin != expected_origin:
            return "sidecar_origin_invalid"
        if origin is not None and origin != expected_origin:
            return "sidecar_origin_invalid"
        if fetch_site is not None and fetch_site != "same-origin":
            return "sidecar_cross_site_request_rejected"
        try:
            self.server.session.validate_live_binding()
        except ValueError as exc:
            return str(exc)
        return None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            if not self._validate_host():
                self._api_error("sidecar_host_invalid", HTTPStatus.FORBIDDEN)
                return
            html = _HTML.replace(
                '<html lang="en">',
                f'<html lang="en" data-session="{self.server.session.session_id}">',
            )
            self._send(HTTPStatus.OK, html.encode("utf-8"), content_type="text/html; charset=utf-8")
            return
        if self.path == "/app.js":
            if not self._validate_host():
                self._api_error("sidecar_host_invalid", HTTPStatus.FORBIDDEN)
                return
            self._send(
                HTTPStatus.OK,
                _JS.encode("utf-8"),
                content_type="application/javascript; charset=utf-8",
            )
            return
        if self.path == "/app.css":
            if not self._validate_host():
                self._api_error("sidecar_host_invalid", HTTPStatus.FORBIDDEN)
                return
            self._send(HTTPStatus.OK, _CSS.encode("utf-8"), content_type="text/css; charset=utf-8")
            return
        if self.path != "/api/snapshot":
            self._api_error("sidecar_route_not_found", HTTPStatus.NOT_FOUND)
            return
        error = self._validate_api(mutation=False)
        if error:
            self._api_error(error, HTTPStatus.FORBIDDEN)
            return
        try:
            self._json(HTTPStatus.OK, self.server.session.snapshot())
        except (ValueError, OSError) as exc:
            self._api_error(str(exc))

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/action":
            self._api_error("sidecar_route_not_found", HTTPStatus.NOT_FOUND)
            return
        error = self._validate_api(mutation=True)
        if error:
            self._api_error(error, HTTPStatus.FORBIDDEN)
            return
        length_text = self.headers.get("Content-Length")
        if not length_text or not length_text.isdecimal():
            self._api_error("sidecar_request_length_invalid")
            return
        length = int(length_text)
        if length > SIDECAR_MAX_REQUEST_BYTES:
            self._api_error("sidecar_request_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, Mapping) or not isinstance(value.get("payload"), Mapping):
                raise ValueError("sidecar_request_invalid")
            result = self.server.session.action(
                action=str(value.get("action") or ""),
                payload=value["payload"],
                expected_contract_revision=int(value["expected_contract_revision"]),
            )
            self._json(HTTPStatus.OK if result["ok"] else HTTPStatus.CONFLICT, result)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._api_error(str(exc))


def start_in_process_sidecar(
    *,
    workspace: str | Path,
    coordinator: Any,
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> tuple[_SidecarServer, SidecarSession, threading.Thread]:
    session = SidecarSession(
        workspace=workspace,
        coordinator=coordinator,
        idle_timeout_seconds=idle_timeout_seconds,
    )
    server = _SidecarServer(("127.0.0.1", 0), session)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, session, thread


def _sanitized_environment() -> dict[str, str]:
    permitted = {
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONIOENCODING",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key in permitted}
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def launch_sidecar_process(
    *,
    workspace: str | Path,
    runtime_executable: str,
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    command = [
        runtime_executable,
        "-m",
        "qcoder.current_loop_contract_sidecar",
        "--serve",
        "--workspace",
        str(Path(workspace).expanduser().absolute()),
        "--idle-timeout",
        str(idle_timeout_seconds),
        "--parent-pid",
        "0",
    ]
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=Path(workspace).expanduser().absolute(),
        env=_sanitized_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=os.name != "nt",
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    try:
        ready = json.loads(line)
    except json.JSONDecodeError as exc:
        process.terminate()
        raise RuntimeError("sidecar_start_failed") from exc
    if ready.get("schema_id") != SIDECAR_SCHEMA_ID:
        process.terminate()
        raise RuntimeError("sidecar_start_failed")
    return {
        **ready,
        "process_id": process.pid,
        "structured_argv": command,
        "environment_categories": sorted(_sanitized_environment()),
        "credential_environment_inherited": False,
    }


def _serve(*, workspace: Path, idle_timeout_seconds: int, parent_pid: int) -> int:
    from qcoder.current_loop_coordinator import CurrentLoopCoordinator

    coordinator = CurrentLoopCoordinator(
        workspace_root=workspace,
        local_only_surface=True,
    )
    server, session, _thread = start_in_process_sidecar(
        workspace=workspace,
        coordinator=coordinator,
        idle_timeout_seconds=idle_timeout_seconds,
    )
    port = server.server_port
    ready = {
        "schema_id": SIDECAR_SCHEMA_ID,
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "sidecar_session_id": session.session_id,
        "loop_reference": session.loop_ref,
        "workspace_label": workspace.name,
        "local_url": f"http://127.0.0.1:{port}/#{session.capability}",
        "sanitized_origin": f"http://127.0.0.1:{port}",
        "capability_delivery": "url_fragment",
        "expires_after_idle_seconds": idle_timeout_seconds,
        "hosted_transport_metadata": False,
        "credential_values": False,
    }
    print(json.dumps(ready, sort_keys=True), flush=True)
    try:
        while not session.expired():
            if parent_pid > 1:
                try:
                    os.kill(parent_pid, 0)
                except OSError:
                    break
            try:
                session.validate_live_binding()
            except ValueError:
                break
            time.sleep(1)
    finally:
        session.closed = True
        server.shutdown()
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--idle-timeout", type=int, default=DEFAULT_IDLE_TIMEOUT_SECONDS)
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args(argv)
    if not args.serve:
        raise SystemExit("sidecar_internal_serve_mode_required")
    return _serve(
        workspace=Path(args.workspace),
        idle_timeout_seconds=args.idle_timeout,
        parent_pid=args.parent_pid,
    )


if __name__ == "__main__":
    raise SystemExit(main())
