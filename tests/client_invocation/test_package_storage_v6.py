"""Installed distribution content and managed-file identity are distinct boundaries."""
import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from test_client_invocation import installed, r, setup


DATA = b'# exact installed payload\n'
NAME = 'qcoder/__init__.py'


@pytest.fixture
def payload(tmp_path):
    root = tmp_path/'distribution'
    candidate = root/NAME
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(DATA)
    distribution = SimpleNamespace(version=r.VERSION, locate_file=lambda name: root/name)
    return distribution, candidate


def test_production_reader_single_link(payload):
    distribution, candidate = payload
    assert candidate.stat().st_nlink == 1
    assert r.installed_package_bytes(distribution, NAME, r.digest(DATA)) == DATA


@pytest.mark.parametrize('links', [2, 3])
def test_production_reader_regular_hardlinks(payload, tmp_path, links):
    distribution, candidate = payload
    for i in range(links-1):
        os.link(candidate, tmp_path/('package-alias-'+str(i)))
    assert candidate.lstat().st_nlink == links
    assert r.installed_package_bytes(distribution, NAME, r.digest(DATA)) == DATA
    with pytest.raises(r.Refused, match='^binding_mismatch$'):
        r.regular(candidate)


@pytest.mark.parametrize('damage', ['leaf_symlink', 'fifo', 'socket', 'directory', 'missing', 'hash'])
def test_production_reader_unsafe_or_wrong_content(payload, tmp_path, damage):
    distribution, candidate = payload
    candidate.unlink()
    sock = None
    if damage == 'leaf_symlink':
        target = tmp_path/'exact-bytes'
        target.write_bytes(DATA)
        candidate.symlink_to(target)
    elif damage == 'fifo':
        os.mkfifo(candidate)
    elif damage == 'socket':
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(candidate))
    elif damage == 'directory':
        candidate.mkdir()
    elif damage == 'hash':
        candidate.write_bytes(b'wrong payload')
    reason = 'installed_dev8_payload_mismatch' if damage == 'hash' else 'installed_dev8_payload_missing_or_type'
    try:
        with pytest.raises(r.Refused, match='^'+reason+'$'):
            r.installed_package_bytes(distribution, NAME, r.digest(DATA))
    finally:
        if sock is not None:
            sock.close()


def test_production_reader_resolved_distribution_root(payload, tmp_path):
    distribution, candidate = payload
    root_alias = tmp_path/'venv-site-packages'
    root_alias.symlink_to(candidate.parent.parent, target_is_directory=True)
    distribution.locate_file = lambda name: root_alias/name
    assert r.installed_package_bytes(distribution, NAME, r.digest(DATA)) == DATA


def test_production_reader_internal_ancestor_symlink(payload):
    distribution, candidate = payload
    package = candidate.parent
    internal = package.parent/'retained-package'
    package.rename(internal)
    package.symlink_to(internal, target_is_directory=True)
    assert not candidate.is_symlink()
    assert r.installed_package_bytes(distribution, NAME, r.digest(DATA)) == DATA


@pytest.mark.parametrize('escape', ['locator', 'ancestor'])
def test_production_reader_distribution_escape(payload, tmp_path, escape):
    distribution, candidate = payload
    outside = tmp_path/'outside'
    outside.mkdir()
    (outside/'__init__.py').write_bytes(DATA)
    if escape == 'locator':
        root = candidate.parent.parent
        distribution.locate_file = lambda name: root if name == '' else outside/'__init__.py'
    else:
        candidate.unlink()
        candidate.parent.rmdir()
        candidate.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(r.Refused, match='^installed_dev8_payload_escape$'):
        r.installed_package_bytes(distribution, NAME, r.digest(DATA))


@pytest.mark.parametrize('name', ['../qcoder/__init__.py', '/qcoder/__init__.py',
    'qcoder/../outside', 'qcoder/sub/../../outside', 'other/__init__.py', 'qcoder',
    'qcoder/', 'qcoder//__init__.py', 'qcoder/./__init__.py',
    'qcoder\\__init__.py', 'C:/qcoder/__init__.py', 'qcoder/\x00', None, 1])
def test_production_reader_bad_manifest_path(payload, name):
    distribution, _ = payload
    with pytest.raises(r.Refused, match='^installed_dev8_payload_manifest$'):
        r.installed_package_bytes(distribution, name, r.digest(DATA))


@pytest.mark.parametrize('sha', [None, 1, 'a'*63, 'g'*64, 'A'*64])
def test_production_reader_bad_manifest_hash(payload, sha):
    distribution, _ = payload
    with pytest.raises(r.Refused, match='^installed_dev8_payload_manifest$'):
        r.installed_package_bytes(distribution, NAME, sha)


@pytest.mark.parametrize('count', [0, 156, 158])
def test_shared_verifier_exact_manifest_count(payload, count):
    distribution, _ = payload
    expected = {'qcoder/file'+str(i): r.digest(DATA) for i in range(count)}
    with pytest.raises(r.Refused, match='^installed_dev8_payload_manifest$'):
        r.verify_installed_payload(distribution, expected)


def test_shared_verifier_exact_version(payload):
    distribution, _ = payload
    distribution.version = '0.6.0a24.post0.dev9'
    with pytest.raises(r.Refused, match='^dev8_version_mismatch$'):
        r.verify_installed_payload(distribution, {NAME:r.digest(DATA)})


def test_both_production_callers_allow_hardlinks(installed, tmp_path):
    distribution = r.importlib.metadata.distribution('qcoder')
    candidate = Path(distribution.locate_file(NAME))
    os.link(candidate, tmp_path/'actual-package-hardlink')
    assert candidate.lstat().st_nlink == 2
    setup.environment()
    assert r.verify(package=True)


@pytest.mark.parametrize('damage,reason', [
    ('leaf_symlink', 'installed_dev8_payload_missing_or_type'),
    ('fifo', 'installed_dev8_payload_missing_or_type'),
    ('missing', 'installed_dev8_payload_missing_or_type'),
    ('hash', 'installed_dev8_payload_mismatch'),
    ('escape', 'installed_dev8_payload_escape'),
    ('version', 'dev8_version_mismatch')])
def test_doctor_and_runtime_package_reasons(installed, tmp_path, monkeypatch, capsys, damage, reason):
    distribution = r.importlib.metadata.distribution('qcoder')
    monkeypatch.setattr(r.importlib.metadata, 'distribution', lambda _: distribution)
    candidate = Path(distribution.locate_file(NAME))
    if damage == 'version':
        distribution.version = 'wrong-dev8'
    else:
        candidate.unlink()
        if damage == 'leaf_symlink':
            candidate.symlink_to(candidate.parent/'file1.py')
        elif damage == 'fifo':
            os.mkfifo(candidate)
        elif damage == 'hash':
            candidate.write_bytes(b'wrong')
        elif damage == 'escape':
            outside = tmp_path/'outside.py'
            outside.write_bytes(b'# synthetic identity-covered package\n')
            original = distribution.locate_file
            distribution.locate_file = lambda name: outside if name == NAME else original(name)
    for operation in (setup.environment, r.verify):
        with pytest.raises(r.Refused, match='^'+reason+'$'):
            operation()
    monkeypatch.setattr('sys.argv', ['setup.py', 'doctor'])
    assert setup.main() == 2
    doctor_output = capsys.readouterr().out
    assert json.loads(doctor_output) == {'status':'refused', 'stage':'doctor', 'reason':reason}
    assert str(tmp_path) not in doctor_output
    assert r.context() == 2
    assert json.loads(capsys.readouterr().out)['reason'] == reason


@pytest.mark.parametrize('count', [156, 158])
def test_both_callers_reject_incomplete_or_extra_manifest(installed, count):
    for path in (setup.HERE/'package.json', r.ROOT/'.d148/package.json'):
        expected = json.loads(path.read_text())
        if count == 156:
            expected.pop(next(iter(expected)))
        else:
            expected['qcoder/extra.py'] = r.digest(DATA)
        path.write_text(json.dumps(expected))
    path = r.ROOT/'.d148/installed.json'
    receipt = json.loads(path.read_text())
    receipt['files']['.d148/package.json'] = r.digest((r.ROOT/'.d148/package.json').read_bytes())
    path.write_text(json.dumps(receipt))
    for operation in (setup.environment, r.verify):
        with pytest.raises(r.Refused, match='^installed_dev8_payload_manifest$'):
            operation()


@pytest.mark.parametrize('name', list(r.MANAGED)+['.d148/installed.json', '.d148/events.jsonl'])
def test_managed_files_keep_single_link_identity(installed, tmp_path, name):
    candidate = r.ROOT/name
    os.link(candidate, tmp_path/'managed-alias')
    assert candidate.lstat().st_nlink == 2
    with pytest.raises(r.Refused, match='^binding_mismatch$'):
        r.regular(candidate)
