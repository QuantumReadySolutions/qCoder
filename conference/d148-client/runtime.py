"""D-148 client-only binding. No science, authority, tracker or provider API."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import time

BASE = Path('/home/user/projects/qcoder-iqt-2026-ml-successor-v1')
ROOT = BASE / 'client-v4'
PYTHON = BASE / '.venv/bin/python'
WORKSPACE = BASE / 'carbon-canonical-v4'
RULE = '.cursor/rules/d148-read-only.mdc'
ACTION = './qcoder-context'
VERSION = '0.6.0a24.post0.dev8+iqt.d148.context.v5'
CONFIG_HOME = Path.home()
ENTERPRISE = Path('/etc/cursor')
MESSAGE = 'Read-only context unavailable or inconsistent; no discovery or execution fallback.'
EVENTS = ('preToolUse', 'beforeShellExecution', 'beforeReadFile',
          'beforeMCPExecution', 'subagentStart', 'beforeTabFileRead', 'beforeSubmitPrompt')


class Refused(Exception):
    pass


def require(ok, code='binding_mismatch'):
    if not ok:
        raise Refused(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    # Never follow a binding-file symlink, FIFO, socket or device.
    p = Path(path)
    info = p.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    require(p.resolve() == p.absolute())
    return p.read_bytes()


def host_id():
    return digest(Path('/etc/machine-id').read_bytes() + socket.gethostname().encode())


def parse(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj)
            obj[key] = value
        return obj
    return json.loads(raw, object_pairs_hook=unique)


def load(path):
    return parse(regular(path))


def hashes(root, mapping):
    for name, expected in mapping.items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts)
        require(digest(regular(root / name)) == expected, 'stale_binding_file')


def instruction_inventory(root):
    """Only explicit instruction locations; no project/Python/transcript discovery."""
    found = {}
    for directory in (root, *root.parents):
        for name in ('AGENTS.md', 'CLAUDE.md', '.cursorrules', '.cursor/hooks.json'):
            path = directory / name
            if os.path.lexists(path):
                found[str(path)] = digest(regular(path))
        rules = directory / '.cursor/rules'
        if os.path.lexists(rules):
            require(rules.is_dir() and not rules.is_symlink())
            for path in sorted(rules.rglob('*')):
                require(not path.is_symlink())
                if path.is_file():
                    found[str(path)] = digest(regular(path))
    # Detect user/enterprise hooks without changing or reading general settings.
    for path in (CONFIG_HOME/'.cursor/hooks.json', ENTERPRISE/'hooks.json'):
        if os.path.lexists(path):
            found[str(path)] = digest(regular(path))
    user_rules = CONFIG_HOME/'.cursor/rules'
    if user_rules.exists():
        require(not user_rules.is_symlink())
        for path in sorted(user_rules.rglob('*')):
            require(not path.is_symlink())
            if path.is_file():
                found[str(path)] = digest(regular(path))
    # Only detect these additional instruction/config sources. Do not read
    # settings contents (which may contain credentials), or inspect plugins.
    for directory in (root, *root.parents, CONFIG_HOME):
        for name in ('.cursor/agents', '.cursor/skills', '.cursor/commands',
                     '.claude/settings.json', '.claude/settings.local.json',
                     '.cursor/managed/active-team-hooks/hooks.json'):
            if os.path.lexists(directory/name):
                found[str(directory/name)] = 'additional_instruction_source_present'
    return found


def verify(root=None, package=True):
    root = ROOT if root is None else root
    require(root == ROOT and root.resolve() == ROOT and Path.cwd() == ROOT, 'wrong_root')
    require(WORKSPACE.is_dir() and WORKSPACE.resolve() == WORKSPACE, 'workspace_unavailable')
    require((root/'qcoder-context').is_file(), 'missing_launcher')
    require(os.access(root/'qcoder-context', os.X_OK) and os.access(root/'.d148/guard', os.X_OK), 'launcher_or_guard_not_executable')
    require((root/'.d148/installed.json').is_file(), 'missing_binding')
    receipt = load(root/'.d148/installed.json')
    require(receipt['host_id'] == host_id(), 'host_mismatch')
    require(receipt['root'] == str(ROOT) and receipt['python'] == str(PYTHON))
    require(receipt['workspace'] == str(WORKSPACE))
    require(sys.executable == str(PYTHON), 'wrong_interpreter')
    require(str(PYTHON.resolve()) == receipt['python_resolved'])
    require(digest(PYTHON.read_bytes()) == receipt['python_sha256'])
    hashes(root, receipt['files'])
    require(instruction_inventory(root) == receipt['instruction_inventory'], 'conflicting_or_changed_instruction_source')
    require(set(p.relative_to(root).as_posix() for p in (root/'.cursor/rules').rglob('*') if p.is_file()) == {RULE})
    if package:
        expected = load(root/'.d148/package.json')
        distribution = importlib.metadata.distribution('qcoder')
        require(distribution.version == VERSION, 'dev8_version_mismatch')
        for name, sha in expected.items():
            require(name.startswith('qcoder/') and '..' not in Path(name).parts)
            require(digest(regular(Path(distribution.locate_file(name)))) == sha, 'installed_dev8_payload_mismatch')
    return receipt


def audit(row):
    # Local operational metadata only; never commands, paths, prompt, user email,
    # transcript, source, tracker payload or private exception strings.
    row = {'time_ns': time.time_ns(), **row}
    path = ROOT/'.d148/events.jsonl'
    fd = os.open(path, os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode) and os.fstat(fd).st_nlink == 1)
        os.write(fd, (json.dumps(row, sort_keys=True)+'\n').encode())
    finally:
        os.close(fd)


def bounded_token(value):
    return isinstance(value, str) and 0 < len(value) <= 160 and all(c.isalnum() or c in '._-[]=:,' for c in value)


def event_common(event, name, receipt):
    require(isinstance(event, dict) and event.get('hook_event_name') == name)
    require(event.get('workspace_roots') == [str(ROOT)])
    require(event.get('cursor_version') == receipt['cursor_version'])
    require(bounded_token(event.get('conversation_id')) and bounded_token(event.get('generation_id')))


def attachment(event):
    values = event.get('attachments')
    require(isinstance(values, list))
    # Attachment is evidence from Cursor's event, not a claim inferred from disk.
    require(values == [{'type': 'rule', 'file_path': str(ROOT/RULE)}])


def session_path(event):
    return ROOT/'.d148'/('attachment-'+digest(event['conversation_id'].encode())+'.json')


def exact_shell(command, cwd):
    return command == ACTION and cwd == str(ROOT)


def decide(event, name, receipt):
    event_common(event, name, receipt)
    if name == 'beforeSubmitPrompt':
        attachment(event)
        bound = {'conversation': event['conversation_id'], 'generation': event['generation_id'],
                 'rule_hash': receipt['files'][RULE], 'cursor_version': event['cursor_version']}
        path = session_path(event)
        require(not path.is_symlink())
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(bound, stream)
        return True
    bound = load(session_path(event))
    require(bound == {'conversation': event['conversation_id'], 'generation': event['generation_id'],
                      'rule_hash': receipt['files'][RULE], 'cursor_version': event['cursor_version']})
    if name == 'preToolUse':
        if event.get('tool_name') != 'Shell':
            return False
        value = event.get('tool_input')
        require(isinstance(value, dict))
        # Reject unknown argument fields instead of assuming harmless semantics.
        # Current docs use working_directory; installed Precision CLI normalizes
        # this to cwd. Validate either spelling and reject contradictory values.
        require(set(value) <= {'command', 'working_directory', 'cwd', 'timeout'})
        for key in ('timeout',):
            if key in value:
                require(type(value[key]) in (int, float) and 0 < value[key] <= 120000)
        require(value.get('working_directory', str(ROOT)) == str(ROOT))
        require(value.get('cwd', str(ROOT)) == str(ROOT))
        return exact_shell(value.get('command'), event.get('cwd'))
    if name == 'beforeShellExecution':
        return exact_shell(event.get('command'), event.get('cwd'))
    return False


def hook(name):
    allowed = False
    event = {}
    try:
        # Internal deadline precedes Cursor's 5-second outer deadline. Native
        # failClosed is still required for missing interpreter/guard or SIGKILL.
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Refused()))
        signal.setitimer(signal.ITIMER_REAL, 3)
        raw = sys.stdin.buffer.read(65537)
        require(len(raw) <= 65536)
        event = parse(raw)
        require(isinstance(event, dict))
        receipt = verify(package=False)
        allowed = decide(event, name, receipt)
        row = {'event': name, 'decision': 'allow' if allowed else 'deny',
               'conversation_hash': digest(str(event.get('conversation_id','')).encode()),
               'generation_hash': digest(str(event.get('generation_id','')).encode()),
               'exact_context_action': event.get('command') == ACTION or
                   (isinstance(event.get('tool_input'),dict) and event['tool_input'].get('command') == ACTION),
               'tool_class': event.get('tool_name') if event.get('tool_name') in ('Shell','Read','Grep','Task','Write','Delete','Glob') else 'other',
               'attachment_observed': name == 'beforeSubmitPrompt' and allowed,
               'cursor_version': receipt['cursor_version'],
               'model':event.get('model_id',event.get('model')) if bounded_token(event.get('model_id',event.get('model'))) else 'unreported'}
        audit(row)
    except BaseException:
        allowed = False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    if name == 'beforeSubmitPrompt':
        value = {'continue': allowed}
    else:
        value = {'permission': 'allow' if allowed else 'deny'}
    if not allowed:
        value['user_message'] = MESSAGE
        if name in ('preToolUse','beforeShellExecution','beforeMCPExecution'):
            value['agent_message'] = MESSAGE
    print(json.dumps(value), flush=True)
    # A valid deny is a successful hook response. Exit 2 is reserved for a
    # wrapper/process failure so Cursor does not reinterpret JSON as prose.
    return 0


def context():
    try:
        verify()
        start = time.monotonic_ns()
        # No shell, no substituted arguments, no environment-selected interpreter.
        result = subprocess.run([str(PYTHON), '-I', '-B', '-m',
            'qcoder.ml_research.client_context', '--workspace', str(WORKSPACE)],
            cwd=ROOT, capture_output=True, timeout=90, check=False)
        elapsed = time.monotonic_ns()-start
        require(len(result.stdout) <= 65536)
        value = json.loads(result.stdout)
        require(value.get('schema') == 'd148.client_context.v1')
        require(value.get('status') in ('verified', 'refused'))
        require(value.get('new_scientific_jobs') == 0 and value.get('approval_created') is False
                and value.get('plan_mutated') is False)
        require(result.returncode == (0 if value['status'] == 'verified' else 2))
        body = dict(value)
        claimed = body.pop('digest')
        canonical = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        require(digest(canonical.encode()) == claimed)
        audit({'event':'context', 'context_ns':elapsed, 'status':value['status'],
               'projection_digest':claimed, 'new_scientific_jobs':0})
        print(json.dumps(value, sort_keys=True))
        return result.returncode
    except BaseException:
        print(json.dumps({'status':'unavailable', 'message':MESSAGE}))
        return 2


if __name__ == '__main__':
    if sys.argv[1:] == ['context']:
        raise SystemExit(context())
    if len(sys.argv) == 3 and sys.argv[1] == 'hook' and sys.argv[2] in EVENTS:
        raise SystemExit(hook(sys.argv[2]))
    print(MESSAGE)
    raise SystemExit(2)
