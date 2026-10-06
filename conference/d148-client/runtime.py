"""D-148 client-only binding. No science, authority, tracker or provider API."""
import hashlib
import importlib.metadata
import json
import os
import re
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import time

BASE = Path('/home/user/projects/qcoder-iqt-2026-ml-successor-v1')
ROOT = BASE / 'client-v5'
PYTHON = BASE / '.venv/bin/python'
WORKSPACE = BASE / 'carbon-canonical-v4'
RULE = '.cursor/rules/d148-read-only.mdc'
ACTION = './qcoder-context'
VERSION = '0.6.0a24.post0.dev8+iqt.d148.context.v5'
CONFIG_HOME = Path.home()
ENTERPRISE = Path('/etc/cursor')
MESSAGE = 'Read-only context unavailable or inconsistent; no discovery or execution fallback.'
SYNTHETIC_FIXTURE = False
MANAGED = ('qcoder-context', '.cursor/hooks.json', RULE, '.cursorignore',
           '.d148/runtime.py', '.d148/guard', '.d148/package.json')
REASONS = frozenset(('binding_mismatch', 'wrong_root', 'workspace_unavailable',
    'missing_launcher', 'launcher_or_guard_not_executable', 'missing_binding',
    'host_mismatch', 'wrong_interpreter', 'stale_binding_file', 'event_name',
    'event_root', 'event_version', 'event_ids', 'attachment_shape',
    'attachment_identifier', 'attachment_multiple', 'session_missing',
    'session_mismatch', 'dev8_version_mismatch', 'installed_dev8_payload_mismatch',
    'deadline', 'input_size', 'invalid_input', 'unavailable', 'action_denied',
    'context_invalid', 'context_unavailable', 'context_digest'))
STAGES = frozenset(('input', 'disk', 'common', 'attachment', 'session', 'action', 'context'))
REPRESENTATIONS = ('absolute', 'project_relative', 'basename')
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
        try:
            actual = digest(regular(root / name))
        except OSError:
            raise Refused('stale_binding_file') from None
        require(actual == expected, 'stale_binding_file')


def verify(root=None, package=True):
    root = ROOT if root is None else root
    require(root == ROOT and root.resolve() == ROOT and Path.cwd() == ROOT, 'wrong_root')
    require(WORKSPACE.is_dir() and WORKSPACE.resolve() == WORKSPACE, 'workspace_unavailable')
    require((root/'qcoder-context').is_file(), 'missing_launcher')
    require(os.access(root/'qcoder-context', os.X_OK) and os.access(root/'.d148/guard', os.X_OK), 'launcher_or_guard_not_executable')
    require((root/'.d148/installed.json').is_file(), 'missing_binding')
    receipt = load(root/'.d148/installed.json')
    require(receipt.get('schema') == ('d148.synthetic_client.v5' if SYNTHETIC_FIXTURE else 'd148.client_binding.v5'))
    require(receipt['host_id'] == host_id(), 'host_mismatch')
    require(receipt['root'] == str(ROOT) and receipt['python'] == str(PYTHON))
    require(receipt['workspace'] == str(WORKSPACE))
    require(os.path.abspath(sys.executable) == str(PYTHON), 'wrong_interpreter')
    require(str(PYTHON.resolve()) == receipt['python_resolved'])
    require(digest(PYTHON.read_bytes()) == receipt['python_sha256'])
    require(set(MANAGED) <= set(receipt['files']))
    hashes(root, receipt['files'])
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


def bounded_version(value):
    # A bounded native version token, never an installed patch allowlist.
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,79}', value) is not None


def event_common(event, name, receipt):
    require(isinstance(event, dict) and event.get('hook_event_name') == name, 'event_name')
    require(event.get('workspace_roots') == [str(ROOT)], 'event_root')
    require(bounded_version(event.get('cursor_version')), 'event_version')
    require(bounded_token(event.get('conversation_id')) and bounded_token(event.get('generation_id')), 'event_ids')


def attachment_info(event):
    values = event.get('attachments')
    info = {'attachment_count': len(values) if isinstance(values, list) else 0,
            'qcoder_match_count': 0, 'qcoder_representation': 'missing',
            'extra_attachment_count': 0}
    if not isinstance(values, list) or len(values) > 128:
        return info, 'attachment_shape'
    forms = {str(ROOT/RULE): 'absolute', RULE: 'project_relative',
             'd148-read-only.mdc': 'basename'}
    matches, suspect, malformed = [], False, False
    for item in values:
        if not isinstance(item, dict):
            continue
        path = item.get('file_path')
        if isinstance(path, str) and path in forms:
            if item.get('type') == 'rule':
                matches.append(forms[path])
            else:
                malformed = True
        elif isinstance(path, str) and 'd148-read-only' in path.casefold():
            # Detection only: never normalize, suffix-match or authorize it.
            suspect = True
        elif item.get('type') == 'rule' and not isinstance(path, str):
            malformed = True
    info['qcoder_match_count'] = len(matches)
    info['extra_attachment_count'] = len(values) - len(matches)
    if len(matches) > 1 or (matches and suspect):
        info['qcoder_representation'] = 'ambiguous'
        return info, 'attachment_multiple'
    if malformed:
        info['qcoder_representation'] = 'unsupported'
        return info, 'attachment_shape'
    if suspect:
        info['qcoder_representation'] = 'unsupported'
        return info, 'attachment_identifier'
    if not matches:
        return info, 'attachment_identifier'
    info['qcoder_representation'] = matches[0]
    return info, None


def attachment(event, receipt):
    info, reason = attachment_info(event)
    require(reason is None, reason)
    return {'representation': info['qcoder_representation']}


def session_path(event):
    return ROOT/'.d148'/('attachment-'+digest(event['conversation_id'].encode())+'.json')


def exact_shell(command, cwd):
    return command == ACTION and cwd == str(ROOT)


def invalidate_submit(event):
    # An invalid resubmission must never reuse an earlier successful receipt.
    if isinstance(event, dict) and bounded_token(event.get('conversation_id')):
        path = session_path(event)
        if os.path.lexists(path):
            regular(path)
            previous = load(path)
            path.unlink()
            if previous.get('generation') == event.get('generation_id'):
                require(previous.get('cursor_version') == event.get('cursor_version'), 'event_version')


def decide(event, name, receipt, invalidated=False):
    if name == 'beforeSubmitPrompt' and not invalidated:
        invalidate_submit(event)
    event_common(event, name, receipt)
    if name == 'beforeSubmitPrompt':
        evidence = attachment(event, receipt)
        bound = {'conversation': event['conversation_id'], 'generation': event['generation_id'],
                 'rule_hash': receipt['files'][RULE], 'cursor_version': event['cursor_version'],
                 **evidence}
        fd = os.open(session_path(event), os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(bound, stream)
        return True
    require(session_path(event).is_file(), 'session_missing')
    bound = load(session_path(event))
    require(bound.get('cursor_version') == event['cursor_version'], 'event_version')
    require(bound.get('representation') in REPRESENTATIONS, 'session_mismatch')
    require(bound == {'conversation': event['conversation_id'], 'generation': event['generation_id'],
                      'rule_hash': receipt['files'][RULE], 'cursor_version': event['cursor_version'],
                      'representation': bound['representation']}, 'session_mismatch')
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


def event_metadata(event, name):
    event = event if isinstance(event, dict) else {}
    value = {'event': name, 'synthetic_fixture': SYNTHETIC_FIXTURE,
             'workspace_root_match': event.get('workspace_roots') == [str(ROOT)],
             'cursor_version': event.get('cursor_version') if bounded_version(event.get('cursor_version')) else None,
             'exact_context_action': event.get('command') == ACTION or
                 (isinstance(event.get('tool_input'), dict) and event['tool_input'].get('command') == ACTION),
             'tool_class': event.get('tool_name') if event.get('tool_name') in
                 ('Shell', 'Read', 'Grep', 'Task', 'Write', 'Delete', 'Glob') else 'other'}
    for key in ('conversation_id', 'generation_id'):
        value[key.replace('_id', '_hash')] = digest(event[key].encode()) if bounded_token(event.get(key)) else None
    if name == 'beforeSubmitPrompt':
        value.update(attachment_info(event)[0])
    return value


def hook(name):
    allowed, event = False, {}
    stage, reason = 'input', 'invalid_input'
    try:
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Refused('deadline')))
        signal.setitimer(signal.ITIMER_REAL, 3)
        raw = sys.stdin.buffer.read(65537)
        require(len(raw) <= 65536, 'input_size')
        event = parse(raw)
        require(isinstance(event, dict), 'invalid_input')
        stage = 'session'
        if name == 'beforeSubmitPrompt':
            invalidate_submit(event)
        stage = 'disk'
        receipt = verify(package=False)
        stage = 'common'
        event_common(event, name, receipt)
        stage = 'attachment' if name == 'beforeSubmitPrompt' else 'action'
        allowed = decide(event, name, receipt, invalidated=True)
        reason = 'accepted' if allowed else 'action_denied'
        audit({**event_metadata(event, name), 'decision': 'allow' if allowed else 'deny',
               'stage': stage, 'reason': reason,
               'attachment_observed': name == 'beforeSubmitPrompt' and allowed})
    except BaseException as error:
        allowed = False
        reason = str(error) if isinstance(error, Refused) and str(error) in REASONS else 'unavailable'
        try:
            audit({**event_metadata(event, name), 'decision': 'deny', 'stage': stage,
                   'reason': reason, 'attachment_observed': False})
        except BaseException:
            pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    value = {'continue': allowed} if name == 'beforeSubmitPrompt' else {'permission': 'allow' if allowed else 'deny'}
    if not allowed:
        value['user_message'] = MESSAGE + ' ['+stage+':'+reason+']'
        if name in ('preToolUse', 'beforeShellExecution', 'beforeMCPExecution'):
            value['agent_message'] = MESSAGE
    print(json.dumps(value), flush=True)
    return 0


def read_context():
    # Shared read-only operation for the launcher and operator doctor.
    start = time.monotonic_ns()
    result = subprocess.run([str(PYTHON), '-I', '-B', '-m',
        'qcoder.ml_research.client_context', '--workspace', str(WORKSPACE)],
        cwd=ROOT if ROOT.is_dir() else BASE, capture_output=True, timeout=90, check=False)
    require(len(result.stdout) <= 65536, 'context_invalid')
    value = parse(result.stdout)
    require(isinstance(value, dict) and value.get('schema') == 'd148.client_context.v1', 'context_invalid')
    require(value.get('status') in ('verified', 'refused'), 'context_invalid')
    require(value.get('new_scientific_jobs') == 0 and value.get('approval_created') is False
            and value.get('plan_mutated') is False, 'context_invalid')
    require(result.returncode == (0 if value['status'] == 'verified' else 2), 'context_invalid')
    body = dict(value)
    claimed = body.pop('digest', None)
    canonical = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    require(digest(canonical.encode()) == claimed, 'context_digest')
    return value, time.monotonic_ns()-start, result.returncode


def context():
    try:
        verify()
        value, elapsed, code = read_context()
        audit({'event': 'context', 'context_ns': elapsed, 'status': value['status'],
               'projection_digest': value['digest'], 'new_scientific_jobs': 0})
        print(json.dumps(value, sort_keys=True))
        return code
    except BaseException as error:
        reason = str(error) if isinstance(error, Refused) and str(error) in REASONS else 'context_unavailable'
        try:
            audit({'event': 'context', 'stage': 'context', 'reason': reason, 'decision': 'deny'})
        except BaseException:
            pass
        print(json.dumps({'status': 'unavailable', 'message': MESSAGE, 'stage': 'context', 'reason': reason}))
        return 2


if __name__ == '__main__':
    if sys.argv[1:] == ['context']:
        raise SystemExit(context())
    if len(sys.argv) == 3 and sys.argv[1] == 'hook' and sys.argv[2] in EVENTS:
        raise SystemExit(hook(sys.argv[2]))
    print(MESSAGE)
    raise SystemExit(2)
