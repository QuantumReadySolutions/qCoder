"""Real synthetic subprocess/PTY tests; no credential store or Google access."""

import io
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import termios
import time

import pytest

from qcoder import protected_blueprint_contract as c
from qcoder import protected_decision_client as client
from qcoder import protected_blueprint_native as native


CHILD = r"""
import json, os, sys, termios
from qcoder.protected_blueprint_native import read_private_from_tty
from qcoder.protected_blueprint_contract import ContractError
mode = sys.argv[1]
if mode == "echo_failure":
    original = termios.tcsetattr
    def reject_echo_off(fd, when, value):
        if not value[3] & termios.ECHO:
            raise termios.error(5, "synthetic")
        return original(fd, when, value)
    termios.tcsetattr = reject_echo_off
try:
    value = read_private_from_tty("HIDDEN_TEST: ")
    report = {"accepted": value == "SYNTHETIC_PRIVATE_INPUT"}
    value = None
except ContractError as exc:
    report = {"category": str(exc)}
if mode == "no_tty":
    report["stdin_unconsumed"] = sys.stdin.readline() == "SYNTHETIC_PRIVATE_INPUT\n"
print(json.dumps(report, sort_keys=True), flush=True)
"""


def _environment():
    return {
        "PATH": os.defpath,
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def test_old_primitive_fallback_and_corrected_no_controlling_tty():
    # Actual former primitive: warns and consumes stdin when /dev/tty is absent.
    old = subprocess.run(
        [
            sys.executable,
            "-c",
            'import getpass; print(getpass.getpass("TEST:") == "SYNTHETIC_PRIVATE_INPUT")',
        ],
        input=b"SYNTHETIC_PRIVATE_INPUT\n",
        capture_output=True,
        timeout=5,
        start_new_session=True,
        env=_environment(),
    )
    assert old.returncode == 0 and old.stdout == b"True\n"
    assert b"GetPassWarning" in old.stderr
    new = subprocess.run(
        [sys.executable, "-c", CHILD, "no_tty"],
        input=b"SYNTHETIC_PRIVATE_INPUT\n",
        capture_output=True,
        timeout=5,
        start_new_session=True,
        env=_environment(),
    )
    assert new.returncode == 0
    assert json.loads(new.stdout) == {
        "category": "private_input_unavailable",
        "stdin_unconsumed": True,
    }
    assert not new.stderr


@pytest.mark.parametrize("mode", ["success", "echo_failure", "eof", "interrupt"])
def test_real_pty_hidden_read_and_terminal_restoration(mode):
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)

    def controlling_tty():
        import fcntl

        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    process = subprocess.Popen(
        [sys.executable, "-c", CHILD, mode],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        preexec_fn=controlling_tty,
        env=_environment(),
    )
    output = bytearray()
    supplied = False
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                output.extend(os.read(master, 4096))
                assert len(output) <= 16384
            if b"HIDDEN_TEST:" in output and not supplied:
                assert not termios.tcgetattr(slave)[3] & termios.ECHO
                supplied = True
                if mode == "success":
                    os.write(master, b"SYNTHETIC_PRIVATE_INPUT\n")
                elif mode == "eof":
                    os.write(master, b"\x04")
                elif mode == "interrupt":
                    process.send_signal(signal.SIGINT)
                else:
                    pytest.fail("unsafe prompt reached after echo-control failure")
            if process.poll() is not None:
                while select.select([master], [], [], 0)[0]:
                    output.extend(os.read(master, 4096))
                break
        assert process.poll() == 0, "bounded child did not finish"
        assert termios.tcgetattr(slave) == before
        if b"SYNTHETIC_PRIVATE_INPUT" in output:
            pytest.fail("private input appeared in terminal output")
        if mode == "success":
            assert b'"accepted": true' in output
        else:
            assert b'"category": "private_input_unavailable"' in output
        assert supplied == (mode != "echo_failure")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        os.close(master)
        os.close(slave)


def test_operational_destination_rejects_before_private_input_or_dispatch(monkeypatch):
    monkeypatch.setattr(
        native, "read_private_from_tty", lambda *a, **k: pytest.fail("private input entered")
    )
    monkeypatch.setattr(
        client.BlueprintHTTPTransport, "exchange", lambda *a, **k: pytest.fail("dispatch entered")
    )

    class PretendTTY(io.StringIO):
        def isatty(self):
            return True

    # Generic configuration is syntactically valid, but operationally unapproved.
    endpoint = "https://unapproved.example.org" + c.ROUTE
    client.BlueprintHTTPTransport(endpoint)
    for target, release in (
        (endpoint, "candidate"),
        ("https://internal.invalid" + c.ROUTE, "wrong-release"),
    ):
        with pytest.raises(c.ContractError, match="destination_not_admitted"):
            native.native_review(
                intent_path="not-opened",
                endpoint=target,
                release=release,
                input_stream=PretendTTY(),
                output_stream=PretendTTY(),
            )
    assert client.APPROVED_NATIVE_BLUEPRINT_DESTINATIONS == frozenset()
