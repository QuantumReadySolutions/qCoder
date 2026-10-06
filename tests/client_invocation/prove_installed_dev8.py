from pathlib import Path
import subprocess,tempfile,sys,json,hashlib,os
source=Path.cwd(); client=Path(os.environ.get('D148_CLIENT_SOURCE', source/'conference/d148-client')); base=Path(tempfile.mkdtemp(prefix='d148-client-v5-installed-proof-')); venv=base/'.venv'
subprocess.run([sys.executable,'-I','-B','-m','venv','--without-pip',str(venv)],check=True)
python=venv/'bin/python'
wheel=source/'artifacts/d148/packages-v5/qcoder-0.6.0a24.post0.dev8+iqt.d148.context.v5-py3-none-any.whl'
subprocess.run([sys.executable,'-m','pip','--python',str(python),'install','--no-index','--no-deps',str(wheel)],check=True)
site=next((venv/'lib').glob('python*/site-packages'))
(site/'d148-isolated-dependencies.pth').write_text(str(source/'.venv/lib/python3.12/site-packages')+'\n')
(base/'tests').mkdir()
for name in ('test_client_invocation_installed.py','test_client_context.py','test_d148.py'):
    (base/'tests'/name).write_bytes((source/'tests/ml_research'/name).read_bytes())
identity=subprocess.run([str(python),'-I','-B','-c',
    'import json,sys,importlib.metadata,hashlib; from pathlib import Path; d=importlib.metadata.distribution("qcoder"); p=json.load(open(sys.argv[1])); assert d.version=="0.6.0a24.post0.dev8+iqt.d148.context.v5"; assert len(p)==157; assert all(hashlib.sha256(Path(d.locate_file(n)).read_bytes()).hexdigest()==s for n,s in p.items()); import qcoder; print(json.dumps({"package_file":qcoder.__file__,"sys_executable":sys.executable,"version":d.version,"payload_hashes_verified":len(p)}))', str(client/'package.json')],cwd=base,check=True,capture_output=True,text=True)
value=json.loads(identity.stdout);assert value['package_file'].startswith(str(venv))
value.update({'proof_root':str(base),'wheel':str(wheel),'wheel_bytes':wheel.stat().st_size,'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'dependency_source':str(source/'.venv/lib/python3.12/site-packages'),'canonical_science':0})
(source/'evidence/d148/client-invocation-v5/installed-runtime-identity.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value,indent=2),flush=True)
result=subprocess.run([str(python),'-I','-B','-m','pytest','-q','--tb=short','-c','/dev/null','--basetemp',str(base/'test-state'),'tests/test_client_invocation_installed.py'],cwd=base,env={**__import__('os').environ,'D148_CLIENT_SOURCE':str(client),'D148_PROOF_EVIDENCE':str(source/'evidence/d148/client-invocation-v5/successor-doctor-lifecycle.json')},text=True,capture_output=True)
(source/'evidence/d148/client-invocation-v5/installed-context-integration.txt').write_text(result.stdout+result.stderr)
print(result.stdout+result.stderr,flush=True)
raise SystemExit(result.returncode)
