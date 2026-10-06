"""Fresh unchanged dev8 installs, optionally reproducing Carbon's hardlink layout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--hardlink', action='store_true')
args = parser.parse_args()
source = Path.cwd()
client = Path(os.environ.get('D148_CLIENT_SOURCE', source/'conference/d148-client'))
evidence = source/'evidence/d148/client-invocation-v6'
evidence.mkdir(parents=True, exist_ok=True)
label = 'hardlink' if args.hardlink else 'installed'
base = Path(tempfile.mkdtemp(prefix='d148-client-v6-'+label+'-proof-'))
venv = base/'.venv'
subprocess.run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', str(venv)], check=True)
python = venv/'bin/python'
wheel = source/'artifacts/d148/packages-v5/qcoder-0.6.0a24.post0.dev8+iqt.d148.context.v5-py3-none-any.whl'
subprocess.run([sys.executable, '-m', 'pip', '--python', str(python), 'install',
                '--no-index', '--no-deps', str(wheel)], check=True)
site = next((venv/'lib').glob('python*/site-packages'))
(site/'d148-isolated-dependencies.pth').write_text(str(source/'.venv/lib/python3.12/site-packages')+'\n')
if args.hardlink:
    os.link(site/'qcoder/__init__.py', base/'installed-init-hardlink')
    assert (site/'qcoder/__init__.py').lstat().st_nlink >= 2
(base/'tests').mkdir()
for name in ('test_client_invocation_installed.py', 'test_client_context.py', 'test_d148.py'):
    (base/'tests'/name).write_bytes((source/'tests/ml_research'/name).read_bytes())
identity_code = '''
import importlib.metadata, importlib.util, json, sys
from pathlib import Path
d = importlib.metadata.distribution('qcoder')
spec = importlib.util.spec_from_file_location('proof_runtime', Path(sys.argv[1])/'runtime.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
p = json.loads((Path(sys.argv[1])/'package.json').read_text())
r.verify_installed_payload(d, p)
import qcoder
init = Path(d.locate_file('qcoder/__init__.py'))
assert init.lstat().st_nlink >= (2 if sys.argv[2] == 'hardlink' else 1)
print(json.dumps({'package_file':qcoder.__file__, 'sys_executable':sys.executable,
    'version':d.version, 'payload_hashes_verified':len(p),
    'init_link_count':init.lstat().st_nlink, 'init_sha256':r.digest(init.read_bytes()),
    'shared_production_verifier':'verify_installed_payload', 'leaf_symlink':init.is_symlink()}))
'''
identity = subprocess.run([str(python), '-I', '-B', '-c', identity_code, str(client), label],
                          cwd=base, check=True, capture_output=True, text=True)
value = json.loads(identity.stdout)
assert value['package_file'].startswith(str(venv))
value.update({'proof_root':str(base), 'wheel':str(wheel), 'wheel_bytes':wheel.stat().st_size,
    'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
    'dependency_source':str(source/'.venv/lib/python3.12/site-packages'), 'canonical_science':0})
(evidence/(label+'-runtime-identity.json')).write_text(json.dumps(value, indent=2)+'\n')
print(json.dumps(value, indent=2), flush=True)
result = subprocess.run([str(python), '-I', '-B', '-m', 'pytest', '-q', '--tb=short',
    '-c', '/dev/null', '--basetemp', str(base/'test-state'), 'tests/test_client_invocation_installed.py'],
    cwd=base, env={**os.environ, 'D148_CLIENT_SOURCE':str(client),
        'D148_EXPECT_INIT_NLINK':str(2 if args.hardlink else 1),
        'D148_PROOF_EVIDENCE':str(evidence/(label+'-successor-doctor-lifecycle.json'))},
    text=True, capture_output=True)
(evidence/(label+'-context-integration.txt')).write_text(result.stdout+result.stderr)
print(result.stdout+result.stderr, flush=True)
raise SystemExit(result.returncode)
