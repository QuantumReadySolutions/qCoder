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
SYNTHETIC_FIXTURE = False
PROFILE = 'cursor-3.23.12-single-rule-v1'
OBSERVATION_KEYS = ('user_rules', 'team_rules', 'enterprise_rules',
                    'plugins_and_skills', 'other_attachments', 'same_name_sources')
REASONS = frozenset(('binding_mismatch', 'wrong_root', 'workspace_unavailable',
    'missing_launcher', 'launcher_or_guard_not_executable', 'missing_binding',
    'host_mismatch', 'wrong_interpreter', 'stale_binding_file',
    'conflicting_or_changed_instruction_source', 'event_name', 'event_root',
    'event_version', 'event_ids', 'attachment_shape', 'attachment_identifier',
    'profile_required', 'profile_unsupported', 'profile_ambiguous',
    'deadline', 'input_size', 'invalid_input', 'unavailable', 'action_denied'))
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
    require(isinstance(event, dict) and event.get('hook_event_name') == name, 'event_name')
    require(event.get('workspace_roots') == [str(ROOT)], 'event_root')
    require(event.get('cursor_version') == receipt['cursor_version'], 'event_version')
    require(bounded_token(event.get('conversation_id')) and bounded_token(event.get('generation_id')), 'event_ids')


def instruction_profile(receipt):
    require(receipt['cursor_version'] == '3.23.12', 'profile_unsupported')
    path = ROOT/'.d148/instruction-observation.json'
    require(path.is_file(), 'profile_required')
    raw = regular(path)
    value = parse(raw)
    basis = value.get('basis') if isinstance(value, dict) else None
    require(basis == 'operator_client_ui_observation' or
            (SYNTHETIC_FIXTURE and basis == 'synthetic_component_test'), 'profile_required')
    expected = {'schema': PROFILE, 'root': str(ROOT), 'cursor_version': '3.23.12',
                'rule_sha256': receipt['files'][RULE], 'basis': basis,
                'observations': {key: 'none_observed' for key in OBSERVATION_KEYS}}
    require(value == expected, 'profile_ambiguous')
    # A basename maps only to this pinned sole local rule. No inherited or
    # extra known instruction source is compatible, even if resealed locally.
    expected_inventory = {str(ROOT/name): receipt['files'][name]
                          for name in (RULE, '.cursor/hooks.json')}
    require(instruction_inventory(ROOT) == expected_inventory ==
            receipt['instruction_inventory'], 'profile_ambiguous')
    return digest(raw)


def attachment(event, receipt):
    values = event.get('attachments')
    require(isinstance(values, list) and len(values) == 1, 'attachment_shape')
    item = values[0]
    require(isinstance(item, dict) and set(item) == {'type', 'file_path'} and
            item['type'] == 'rule' and isinstance(item['file_path'], str), 'attachment_shape')
    if item['file_path'] == str(ROOT/RULE):
        return {'representation': 'exact_absolute_reported', 'profile_digest': None}
    require(item['file_path'] == 'd148-read-only.mdc', 'attachment_identifier')
    return {'representation': 'bound_identifier_reported',
            'profile_digest': instruction_profile(receipt)}


def session_path(event):
    return ROOT/'.d148'/('attachment-'+digest(event['conversation_id'].encode())+'.json')


def exact_shell(command, cwd):
    return command == ACTION and cwd == str(ROOT)


def decide(event, name, receipt):
    event_common(event, name, receipt)
    if name == 'beforeSubmitPrompt':
        path = session_path(event)
        require(not path.is_symlink())
        path.unlink(missing_ok=True)
        evidence = attachment(event, receipt)
        bound = {'conversation': event['conversation_id'], 'generation': event['generation_id'],
                 'rule_hash': receipt['files'][RULE], 'cursor_version': event['cursor_version'],
                 **evidence}
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(bound, stream)
        return True
    bound = load(session_path(event))
    representation = bound.get('representation')
    require(representation in ('exact_absolute_reported', 'bound_identifier_reported'))
    profile_digest = instruction_profile(receipt) if representation == 'bound_identifier_reported' else None
    require(bound == {'conversation': event['conversation_id'], 'generation': event['generation_id'],
                      'rule_hash': receipt['files'][RULE], 'cursor_version': event['cursor_version'],
                      'representation': representation, 'profile_digest': profile_digest})
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
    stage, reason = 'input', 'invalid_input'
    try:
        # Internal deadline precedes Cursor's 5-second outer deadline. Native
        # failClosed is still required for missing interpreter/guard or SIGKILL.
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Refused('deadline')))
        signal.setitimer(signal.ITIMER_REAL, 3)
        raw = sys.stdin.buffer.read(65537)
        require(len(raw) <= 65536, 'input_size')
        event = parse(raw)
        require(isinstance(event, dict))
        stage = 'disk'
        receipt = verify(package=False)
        stage = 'common'
        event_common(event, name, receipt)
        stage = 'attachment' if name == 'beforeSubmitPrompt' else 'action'
        allowed = decide(event, name, receipt)
        reason = 'accepted' if allowed else 'action_denied'
        row = {'event': name, 'decision': 'allow' if allowed else 'deny',
               'stage': stage, 'reason': reason,
               'conversation_hash': digest(str(event.get('conversation_id','')).encode()),
               'generation_hash': digest(str(event.get('generation_id','')).encode()),
               'exact_context_action': event.get('command') == ACTION or
                   (isinstance(event.get('tool_input'),dict) and event['tool_input'].get('command') == ACTION),
               'tool_class': event.get('tool_name') if event.get('tool_name') in ('Shell','Read','Grep','Task','Write','Delete','Glob') else 'other',
               'attachment_observed': name == 'beforeSubmitPrompt' and allowed,
               'attachment_representation': (attachment(event, receipt)['representation']
                   if name == 'beforeSubmitPrompt' and allowed else 'not_observed'),
               'synthetic_fixture': SYNTHETIC_FIXTURE}
        audit(row)
    except BaseException as error:
        allowed = False
        reason = str(error) if isinstance(error, Refused) and str(error) in REASONS else 'unavailable'
        # Failure diagnostics are fixed codes, with no raw payload/error fields.
        try:
            audit({'event': name, 'decision': 'deny', 'stage': stage, 'reason': reason,
                   'attachment_observed': False, 'synthetic_fixture': SYNTHETIC_FIXTURE})
        except BaseException:
            pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    if name == 'beforeSubmitPrompt':
        value = {'continue': allowed}
    else:
        value = {'permission': 'allow' if allowed else 'deny'}
    if not allowed:
        value['user_message'] = MESSAGE + ' ['+stage+':'+reason+']'
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


def observe_instructions():
    """Operator UI inventory, not authorization or a native attachment event."""
    try:
        receipt = verify(package=False)
        require(receipt['cursor_version'] == '3.23.12', 'profile_unsupported')
        require(receipt.get('schema') in ('d148.client_binding.v2', 'd148.synthetic_client.v2'),
                'profile_unsupported')
        path = ROOT/'.d148/instruction-observation.json'
        require(not os.path.lexists(path), 'profile_ambiguous')
        print('Record actual Cursor 3.23.12 Agent instruction observations for this window.\n'
              'Inspect User/Team/Enterprise rules, enabled plugins/skills and attachments.\n'
              'Enter none_observed only after checking each surface. Unknown/conflict stops.\n'
              'This does not prove rule attachment, source origin or hidden-instruction absence.', flush=True)
        observations = {key: input(key+': ').strip() for key in OBSERVATION_KEYS}
        require(all(value == 'none_observed' for value in observations.values()), 'profile_ambiguous')
        expected_inventory = {str(ROOT/name): receipt['files'][name]
                              for name in (RULE, '.cursor/hooks.json')}
        require(instruction_inventory(ROOT) == expected_inventory, 'profile_ambiguous')
        value = {'schema': PROFILE, 'root': str(ROOT), 'cursor_version': '3.23.12',
                 'rule_sha256': receipt['files'][RULE], 'basis': 'operator_client_ui_observation',
                 'observations': observations}
        with path.open('x') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')
        path.chmod(0o600)
        print(json.dumps({'instruction_profile': PROFILE, 'active_attachment': 'unobserved',
                          'native_acceptance': 'pending', 'profile_digest': instruction_profile(receipt)}))
        return 0
    except BaseException:
        print(json.dumps({'status': 'refused', 'reason': 'instruction_profile_not_established'}))
        return 2


if __name__ == '__main__':
    if sys.argv[1:] == ['observe-instructions']:
        raise SystemExit(observe_instructions())
    if sys.argv[1:] == ['context']:
        raise SystemExit(context())
    if len(sys.argv) == 3 and sys.argv[1] == 'hook' and sys.argv[2] in EVENTS:
        raise SystemExit(hook(sys.argv[2]))
    print(MESSAGE)
    raise SystemExit(2)
