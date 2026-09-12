"""Neutral public-contract fixtures: no private recommendation expectations."""

import http.client
import io
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qcoder import protected_blueprint_contract as c
from qcoder.protected_decision_client import BlueprintClient, BlueprintHTTPTransport
from qcoder.protected_decision_local_authority import BlueprintReview

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
RELEASE = "neutral-contract-fixture"


def intent():
    return {
        **{k: "unspecified" for k in c.SCALARS},
        "constraints": [],
        "non_goals": [],
        "unresolved": [],
    }


def response(req):
    p = {
        "authority": c.AUTHORITY,
        "groups": [
            {
                "id": "framework",
                "recommended": None,
                "alternatives": [],
                "basis": "insufficient_intent",
                "unresolved": True,
            }
        ],
        "limitations": sorted(c.LIMITATIONS),
        "unresolved": ["framework"],
        "semantic_digest": "",
    }
    p["semantic_digest"] = c.digest(p, "semantic_digest")
    r = {
        "schema": c.RESPONSE,
        "version": 1,
        **{k: req[k] for k in ("nonce", "revision", "expires_at", "request_digest")},
        "release": RELEASE,
        "outcome": "completed",
        "proposal": p,
        "response_digest": "",
    }
    r["response_digest"] = c.digest(r, "response_digest")
    return r


@pytest.fixture
def socket_transport(monkeypatch):
    state = {"status": 200, "headers": [], "mutate": lambda r: r, "calls": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["calls"] += 1
            assert self.path == c.ROUTE
            assert self.headers["X-QCoder-Entitlement-Token"] == "synthetic_token"
            req = c.decode(self.rfile.read(int(self.headers["Content-Length"])))
            state["request"] = req
            body = state.get("body", c.encode(state["mutate"](response(req))))
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in state["headers"]:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    transport = BlueprintHTTPTransport("https://internal.invalid" + c.ROUTE)
    monkeypatch.setattr(
        transport,
        "_connection",
        lambda: http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2),
    )
    yield transport, state
    server.shutdown()
    server.server_close()
    t.join()


def test_socket_envelope_and_exact_customer_confirmation(socket_transport):
    transport, state = socket_transport
    local = {"revision": 7, "deferred_decisions": []}
    review = BlueprintReview(
        BlueprintClient(transport, release=RELEASE, clock=lambda: NOW),
        current_state=lambda: local,
        clock=lambda: NOW,
    )
    inspected = review.prepare(intent())
    displayed = review.acquire(bearer="synthetic_token")
    envelope = c.decode(displayed.encode())
    assert state["request"] == inspected and state["calls"] == 1
    assert envelope == response(inspected)

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    answer = Terminal("CONFIRM " + envelope["response_digest"] + "\n")
    shown = Terminal()
    result = review.confirm_native(answer, shown)
    assert shown.getvalue().startswith(displayed + "\n")
    assert result["customer_confirmation_exact"]
    assert all(v is False for k, v in result.items() if k.endswith("authorized"))
    with pytest.raises(c.ContractError, match="consumed"):
        review.confirm_native(answer, shown)


@pytest.mark.parametrize(
    "boundary",
    [
        "transport_expiry",
        "review_expiry",
        "local_during_transport",
        "local_during_review",
        "assistant_confirmation",
        "modified_display",
    ],
)
def test_currentness_and_customer_negatives(socket_transport, boundary):
    transport, state = socket_transport
    time = [NOW]
    local = {"revision": 1}
    review = BlueprintReview(
        BlueprintClient(transport, release=RELEASE, clock=lambda: time[0]),
        current_state=lambda: local,
        clock=lambda: time[0],
    )
    review.prepare(intent())

    def mutate(r):
        if boundary == "transport_expiry":
            time[0] += timedelta(minutes=5)
        if boundary == "local_during_transport":
            local["revision"] += 1
        return r

    state["mutate"] = mutate
    if boundary.endswith("transport") or boundary == "transport_expiry":
        with pytest.raises(c.ContractError):
            review.acquire(bearer="synthetic_token")
        return
    review.acquire(bearer="synthetic_token")
    if boundary == "review_expiry":
        time[0] += timedelta(minutes=5)
    if boundary == "local_during_review":
        local["revision"] += 1
    if boundary == "modified_display":
        review._response["revision"] = 2

    class Terminal(io.StringIO):
        def isatty(self):
            return boundary != "assistant_confirmation"

    with pytest.raises(c.ContractError):
        review.confirm_native(Terminal("yes\n"), Terminal())


@pytest.mark.parametrize(
    "raw",
    [b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff", b"{} ", b"[" * 1000 + b"]" * 1000, b"x" * 16385],
)
def test_wire_negatives(raw):
    with pytest.raises(c.ContractError):
        c.decode(raw)


@pytest.mark.parametrize("field", list(c.SCALARS) + list(c.SETS))
def test_prohibited_value_inside_allowed_field(field):
    obj = intent()
    marker = "PRIVATE_MARKER/source.py Bearer synthetic-secret"
    obj[field] = [marker] if field in c.SETS else marker
    with pytest.raises(c.ContractError) as err:
        c.validate_intent(obj)
    assert marker not in str(err.value)


@pytest.mark.parametrize(
    "change",
    [
        "nonce",
        "release",
        "revision",
        "request_digest",
        "response_digest",
        "expires_at",
        "version",
        "unknown",
        "authority",
    ],
)
def test_bindings_and_authority(change):
    req = c.make_request(intent(), "n" * 32, 1, NOW)
    obj = response(req)
    if change == "authority":
        obj["proposal"]["authority"] = "write_and_run"
    elif change == "unknown":
        obj["private_rule"] = "secret"
    else:
        obj[change] = 2 if change in ("version", "revision") else "wrong"
    with pytest.raises(c.ContractError):
        c.validate_response(obj, req, RELEASE, NOW)


@pytest.mark.parametrize(
    "status,body,headers",
    [
        (401, b'{"category":"unauthorized"}', []),
        (401, b'{"category":"PRIVATE_MARKER"}', []),
        (302, b"{}", [("Location", "https://another.invalid/")]),
        (200, b"{}", [("Content-Type", "application/json")]),
        (200, b"{}", [("Content-Encoding", "gzip")]),
        (200, b"x" * 16385, []),
    ],
)
def test_http_failure_no_retry_no_raw_echo(socket_transport, status, body, headers):
    transport, state = socket_transport
    state.update(status=status, body=body, headers=headers)
    with pytest.raises(c.ContractError) as err:
        transport.exchange(c.make_request(intent(), "n" * 32, 1, NOW), bearer="synthetic_token")
    assert "PRIVATE_MARKER" not in str(err.value) and state["calls"] == 1


def test_production_guard_offline_and_inventory():
    for url in (
        "http://127.0.0.1" + c.ROUTE,
        "https://user:pass@example.org" + c.ROUTE,
        "https://example.org" + c.ROUTE + "?redirect=1",
    ):
        with pytest.raises(c.ContractError):
            BlueprintHTTPTransport(url)
    req = c.make_request(intent(), "n" * 32, 1, NOW)
    with pytest.raises(c.ContractError, match="unavailable"):
        BlueprintClient(None, release=RELEASE, clock=lambda: NOW).recommend(req, bearer="synthetic")
    from qcoder.context_bridge_mcp import EXPECTED_TOOLS
    from qcoder.current_loop_binding_mcp import binding_tool_descriptors

    assert len(EXPECTED_TOOLS) == 12 and len(binding_tool_descriptors()) == 2


def test_actual_native_cli_has_inspection_hidden_input_and_no_effect(
    socket_transport, monkeypatch, tmp_path
):
    transport, server = socket_transport
    from qcoder import cli
    from qcoder import protected_blueprint_native as native

    # Test-side clock and socket substitution only; actual CLI/codec/acceptance run.
    monkeypatch.setattr(BlueprintHTTPTransport, "_connection", lambda _: transport._connection())
    # Bind the instance override before patching the class to avoid any remote call.
    real_init = native.BlueprintClient
    monkeypatch.setattr(
        native,
        "BlueprintClient",
        lambda t, release: real_init(t, release=release, clock=lambda: NOW),
    )
    real_review = native.BlueprintReview
    monkeypatch.setattr(
        native,
        "BlueprintReview",
        lambda client, current_state: real_review(
            client, current_state=current_state, clock=lambda: NOW
        ),
    )
    tokens = iter(["synthetic_token", ""])
    monkeypatch.setattr(native.getpass, "getpass", lambda _: next(tokens))
    path = tmp_path / "intent.json"
    path.write_bytes(c.encode(intent()))
    monkeypatch.chdir(tmp_path)

    class Terminal(io.StringIO):
        def isatty(self):
            return True

        def readline(self, limit=-1):
            if "For local evaluation only" not in self.getvalue():
                return "SEND STRUCTURED INTENT\n"
            return self.getvalue().split("type ")[-1].strip() + "\n"

    terminal = Terminal()
    monkeypatch.setattr(cli.sys, "stdin", terminal)
    monkeypatch.setattr(cli.sys, "stdout", terminal)
    assert (
        cli._cmd_blueprint(
            [
                "recommend",
                "--intent-file",
                str(path),
                "--endpoint",
                "https://internal.invalid" + c.ROUTE,
                "--release",
                RELEASE,
            ]
        )
        == 0
    )
    assert server["calls"] == 1
    assert "synthetic_token" not in terminal.getvalue()
    assert not (tmp_path / ".qcoder").exists()
    assert list(tmp_path.iterdir()) == [path]


def test_deferrals_conflicts_superseded_and_cross_request(socket_transport):
    transport, state = socket_transport
    for kind in ("deferred", "conflict", "cross_request"):
        review = BlueprintReview(
            BlueprintClient(transport, release=RELEASE, clock=lambda: NOW),
            current_state=lambda: {
                "deferred_decisions": ["framework"] if kind == "deferred" else []
            },
            clock=lambda: NOW,
        )
        obj = intent()
        obj["framework"] = "cirq"
        review.prepare(obj)

        def modify(r):
            r["proposal"]["groups"][0].update(
                recommended="qiskit", basis="explicit_intent", unresolved=False
            )
            r["proposal"]["semantic_digest"] = c.digest(r["proposal"], "semantic_digest")
            if kind == "cross_request":
                r["nonce"] = "x" * 32
            r["response_digest"] = c.digest(r, "response_digest")
            return r

        state["mutate"] = modify
        with pytest.raises(c.ContractError):
            review.acquire(bearer="synthetic_token")
