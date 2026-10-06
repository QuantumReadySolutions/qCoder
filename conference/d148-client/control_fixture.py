"""Create isolated Cursor control fixtures; never touch the Carbon research state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import shlex
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
CARBON = '/home/user/projects/qcoder-iqt-2026-ml-successor-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def render_guard(python, root):
    # Replace the complete fixed invocation once; never rewrite inserted paths.
    original = CARBON+'/.venv/bin/python -I -B '+CARBON+'/client-v4/.d148/runtime.py'
    template = (HERE/'guard').read_text()
    if template.count(original) != 1:
        raise ValueError('guard_template_mismatch')
    return template.replace(original, shlex.quote(str(python))+' -I -B '+
                            shlex.quote(str(root/'.d148/runtime.py')))


def launcher_preflight(root):
    receipt = json.loads((root/'.d148/installed.json').read_text())
    if (root/'.d148/guard').read_text() != render_guard(receipt['python'], root):
        raise ValueError('launcher_receipt_mismatch')
    # Deliberately incomplete synthetic event: disk verification must finish,
    # then event validation must deny. Creates NO successful attachment receipt.
    result = subprocess.run([str(root/'.d148/guard'), 'beforeSubmitPrompt'],
        cwd=root, input='{}', text=True, capture_output=True, timeout=5)
    value = json.loads(result.stdout)
    if result.returncode != 0 or value.get('continue') is not False or \
            '[common:event_name]' not in value.get('user_message', ''):
        raise ValueError('launcher_preflight_failed')
    return 'verified_synthetic_denial_not_native_acceptance'


def create(version, case):
    if not sys.executable:
        raise ValueError('interpreter_unavailable')
    # Collapse lexical . and .. once, retaining the selected venv symlink path.
    # resolve() is only for the separate target-integrity field in the receipt.
    python = Path(os.path.abspath(sys.executable))
    if not python.is_absolute():
        raise ValueError('interpreter_not_absolute')
    base = Path(tempfile.mkdtemp(prefix='d148-cursor-control-'))
    root = base/'client-v4'
    root.mkdir()
    (root/'.cursor/rules').mkdir(parents=True)
    (root/'.d148').mkdir()
    (base/'carbon-canonical-v4').mkdir()
    (base/'outside-fixture.txt').write_text('D148 SYNTHETIC OUTSIDE SENTINEL\n')
    (root/'fixture-private.txt').write_text('D148 SYNTHETIC PRIVATE SENTINEL\n')
    runtime = (HERE/'runtime.py').read_text().replace('Path('+repr(CARBON)+')','Path('+repr(str(base))+')')
    runtime = runtime.replace("PYTHON = BASE / '.venv/bin/python'",'PYTHON = Path('+repr(str(python))+')')
    runtime = runtime.replace('CONFIG_HOME = Path.home()', 'CONFIG_HOME = BASE / "fixture-home"')
    runtime = runtime.replace("ENTERPRISE = Path('/etc/cursor')",'ENTERPRISE = BASE / "fixture-enterprise"')
    runtime = runtime.replace('SYNTHETIC_FIXTURE = False', 'SYNTHETIC_FIXTURE = True')
    (root/'.d148/runtime.py').write_text(runtime)
    guard = render_guard(python, root)
    (root/'.d148/guard').write_text(guard)
    (root/'.d148/guard').chmod(0o700)
    # The only allowed operation is a synthetic marker; no qCoder operation,
    # real tracker, real science or private file is invoked in control tests.
    (root/'qcoder-context').write_text('#!/bin/sh\n[ "$#" -eq 0 ] || exit 2\nprintf \'%s\\n\' \'D148_SYNTHETIC_CONTEXT_ONLY\'\n')
    (root/'qcoder-context').chmod(0o700)
    (root/'.cursor/rules/d148-read-only.mdc').write_text((HERE/'binding.mdc').read_text().replace(CARBON,str(base)))
    (root/'.cursorignore').write_bytes((HERE/'cursorignore').read_bytes())
    config=json.loads((HERE/'hooks.json').read_text())
    faults={'missing':None,'crash':'exit 19','timeout':'exec sleep 8',
            'malformed':"printf broken",'invalid':"printf '%s' '{\"permission\":\"wrong\"}'",
            'empty':'exit 0'}
    if case in faults:
        config['hooks']['preToolUse'][0]['command']='.d148/fault'
        if faults[case] is not None:
            (root/'.d148/fault').write_text('#!/bin/sh\n'+faults[case]+'\n')
            (root/'.d148/fault').chmod(0o700)
    (root/'.cursor/hooks.json').write_text(json.dumps(config,indent=2)+'\n')
    files={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    inventory={str(root/n):files[n] for n in ('.cursor/hooks.json','.cursor/rules/d148-read-only.mdc')}
    receipt={'schema':'d148.synthetic_client.v2','root':str(root),'workspace':str(base/'carbon-canonical-v4'),'python':str(python),
             'python_resolved':str(python.resolve()),'python_sha256':sha(python.read_bytes()),
             'host_id':sha(Path('/etc/machine-id').read_bytes()+socket.gethostname().encode()),
             'cursor_version':version,'files':files,'instruction_inventory':inventory}
    (root/'.d148/installed.json').write_text(json.dumps(receipt,indent=2)+'\n')
    preflight = launcher_preflight(root)
    return {'fixture_root':str(root),'case':case,'scientific_state_accessed':False,
            'expected_context':'D148_SYNTHETIC_CONTEXT_ONLY','acceptance':'unobserved',
            'launcher_preflight':preflight,'instruction_observation':'required_for_basename'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cursor-version')
    parser.add_argument('--preflight-root', type=Path)
    parser.add_argument('--case',choices=['normal','missing','crash','timeout','malformed','invalid','empty'],default='normal')
    args=parser.parse_args()
    if not args.preflight_root and not args.cursor_version:
        parser.error('--cursor-version is required for creation')
    try:
        value = ({'launcher_preflight': launcher_preflight(args.preflight_root)}
                 if args.preflight_root else create(args.cursor_version,args.case))
        print(json.dumps(value,indent=2))
    except BaseException:
        print(json.dumps({'status':'refused', 'stage':'preflight',
                          'reason':'launcher_or_disk_verification_failed'}))
        raise SystemExit(2)
