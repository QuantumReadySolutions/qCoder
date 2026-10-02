"""Create isolated Cursor control fixtures; never touch the Carbon research state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

HERE = Path(__file__).resolve().parent
CARBON = '/home/user/projects/qcoder-iqt-2026-ml-successor-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def create(version, case):
    base = Path(tempfile.mkdtemp(prefix='d148-cursor-control-'))
    root = base/'client-v4'
    root.mkdir()
    (root/'.cursor/rules').mkdir(parents=True)
    (root/'.d148').mkdir()
    (base/'carbon-canonical-v4').mkdir()
    (base/'outside-fixture.txt').write_text('D148 SYNTHETIC OUTSIDE SENTINEL\n')
    (root/'fixture-private.txt').write_text('D148 SYNTHETIC PRIVATE SENTINEL\n')
    runtime = (HERE/'runtime.py').read_text().replace(CARBON,str(base))
    runtime = runtime.replace("PYTHON = BASE / '.venv/bin/python'",'PYTHON = Path('+repr(sys.executable)+')')
    runtime = runtime.replace('CONFIG_HOME = Path.home()', 'CONFIG_HOME = BASE / "fixture-home"')
    runtime = runtime.replace("ENTERPRISE = Path('/etc/cursor')",'ENTERPRISE = BASE / "fixture-enterprise"')
    (root/'.d148/runtime.py').write_text(runtime)
    guard = (HERE/'guard').read_text().replace(CARBON+'/.venv/bin/python',sys.executable).replace(CARBON,str(base))
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
    receipt={'root':str(root),'workspace':str(base/'carbon-canonical-v4'),'python':sys.executable,
             'python_resolved':str(Path(sys.executable).resolve()),'python_sha256':sha(Path(sys.executable).read_bytes()),
             'host_id':sha(Path('/etc/machine-id').read_bytes()+socket.gethostname().encode()),
             'cursor_version':version,'files':files,'instruction_inventory':inventory}
    (root/'.d148/installed.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return {'fixture_root':str(root),'case':case,'scientific_state_accessed':False,
            'expected_context':'D148_SYNTHETIC_CONTEXT_ONLY','acceptance':'unobserved'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cursor-version',required=True)
    parser.add_argument('--case',choices=['normal','missing','crash','timeout','malformed','invalid','empty'],default='normal')
    args=parser.parse_args()
    print(json.dumps(create(args.cursor_version,args.case),indent=2))
