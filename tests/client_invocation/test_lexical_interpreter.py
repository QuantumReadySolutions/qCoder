"""Real venv and generated shell subprocesses; disposable synthetic roots only."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

CLIENT = Path(__file__).resolve().parents[2] / 'conference/d148-client'
CARBON = '/home/user/projects/qcoder-iqt-2026-ml-successor-v1'


def fixture_through_venv(tmp_path, placement, spelling, quoted):
    source = tmp_path / 'source'
    shutil.copytree(CLIENT, source)
    # Substitute the source base before generation, never an inserted interpreter.
    for name in ('runtime.py', 'guard', 'control_fixture.py'):
        path = source / name
        path.write_text(path.read_text().replace(CARBON, str(source)))
    owner = source if placement == 'inside' else tmp_path / 'external'
    venv = owner / ("venv space's" if quoted else '.venv')
    subprocess.run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', str(venv)],
                   check=True, capture_output=True, timeout=15)
    python = venv / 'bin/python'
    extraction = owner / 'extracted-v3'
    extraction.mkdir()
    invocation = {
        'canonical': str(python),
        'parent': str(owner) + '/extracted-v3/../' + venv.name + '/bin/../bin/python',
        'dot': str(owner) + '/./' + venv.name + '/bin/./python',
        'relative_parent': '../' + venv.name + '/bin/python',
        'relative_dot': './' + venv.name + '/bin/./python',
    }[spelling]
    assert python.is_symlink() and python.resolve() != python
    result = subprocess.run([invocation, '-I', '-B', str(source / 'control_fixture.py'),
                             '--cursor-version', '3.23.12', '--case', 'normal'],
                            cwd=owner if spelling == 'relative_dot' else extraction,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    created = json.loads(result.stdout)
    return Path(created['fixture_root']), python, created


@pytest.mark.parametrize('placement', ['inside', 'outside'])
@pytest.mark.parametrize('spelling', ['canonical', 'parent', 'dot', 'relative_parent', 'relative_dot'])
@pytest.mark.parametrize('quoted', [False, True], ids=['plain', 'spaces_apostrophe'])
def test_lexical_venv_guard_preflight(tmp_path, placement, spelling, quoted):
    root, python, created = fixture_through_venv(tmp_path, placement, spelling, quoted)
    receipt = json.loads((root / '.d148/installed.json').read_text())
    assert receipt['python'] == str(python)
    assert os.path.isabs(receipt['python'])
    assert receipt['python_resolved'] == str(python.resolve()) != receipt['python']
    assert receipt['python_sha256'] == hashlib.sha256(python.read_bytes()).hexdigest()
    runtime = ast.parse((root / '.d148/runtime.py').read_text())
    pinned = next(node.value for node in runtime.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'PYTHON'
                          for target in node.targets))
    assert ast.literal_eval(pinned.args[0]) == receipt['python']
    invocation = next(line for line in (root / '.d148/guard').read_text().splitlines()
                      if line.startswith('if '))
    assert invocation == ('if ' + shlex.quote(str(python)) + ' -I -B ' +
                          shlex.quote(str(root / '.d148/runtime.py')) + ' hook "$1" 2>/dev/null; then')
    child = subprocess.run([str(python), '-I', '-B', '-c', 'import sys; print(sys.executable)'],
                           cwd=root, check=True, capture_output=True, text=True)
    assert child.stdout.strip() == receipt['python']
    assert created['launcher_preflight'] == 'verified_synthetic_denial_not_native_acceptance'
    assert created['scientific_state_accessed'] is False
    assert not list((root / '.d148').glob('attachment-*.json'))
    # Execute the actual assembled shell launcher, after generator preflight.
    guard = subprocess.run([str(root / '.d148/guard'), 'beforeSubmitPrompt'], cwd=root,
                           input='{}', capture_output=True, text=True, timeout=5)
    assert guard.returncode == 0 and not guard.stderr
    value = json.loads(guard.stdout)
    assert value['continue'] is False and '[common:event_name]' in value['user_message']
    rows = [json.loads(line) for line in (root / '.d148/events.jsonl').read_text().splitlines()]
    assert len(rows) == 2
    assert all(row['stage'] == 'common' and row['reason'] == 'event_name'
               and row['synthetic_fixture'] is True and row['attachment_observed'] is False
               for row in rows)
    assert not list((root / '.d148').glob('attachment-*.json'))
    assert not list((root.parent / 'carbon-canonical-v4').iterdir())


@pytest.mark.parametrize('damage', ['wrong_interpreter', 'python_receipt', 'python_hash',
                                   'python_resolved', 'guard', 'runtime'])
def test_generated_venv_integrity_denials(tmp_path, damage):
    root, python, _ = fixture_through_venv(tmp_path, 'outside', 'canonical', False)
    command = [str(root / '.d148/guard'), 'beforeSubmitPrompt']
    if damage == 'wrong_interpreter':
        # Same target bytes, different lexical identity must still fail.
        command = [str(python.resolve()), '-I', '-B', str(root / '.d148/runtime.py'),
                   'hook', 'beforeSubmitPrompt']
    elif damage in ('python_receipt', 'python_hash', 'python_resolved'):
        path = root / '.d148/installed.json'
        receipt = json.loads(path.read_text())
        key = {'python_receipt': 'python', 'python_hash': 'python_sha256',
               'python_resolved': 'python_resolved'}[damage]
        receipt[key] = 'changed'
        path.write_text(json.dumps(receipt))
    else:
        path = root / '.d148' / ('runtime.py' if damage == 'runtime' else 'guard')
        path.write_text(path.read_text() + '\n# changed\n')
    result = subprocess.run(command, cwd=root, input='{}', capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0 and not result.stderr
    value = json.loads(result.stdout)
    assert value['continue'] is False
    expected = 'wrong_interpreter' if damage == 'wrong_interpreter' else (
        'stale_binding_file' if damage in ('guard', 'runtime') else 'binding_mismatch')
    assert '[disk:' + expected + ']' in value['user_message']
    assert not list((root / '.d148').glob('attachment-*.json'))
    assert not list((root.parent / 'carbon-canonical-v4').iterdir())
