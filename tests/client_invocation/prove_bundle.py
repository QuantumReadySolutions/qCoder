from pathlib import Path
import subprocess,tempfile,hashlib,json,tarfile,importlib.util,sys
source=Path.cwd(); evidence=source/'evidence/d148/client-invocation-v6'
spec=importlib.util.spec_from_file_location('bundle',source/'scripts/build_d148_client_bundle.py'); b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
receipt=b.build(source/'conference/d148-client',source/'artifacts/d148/client-invocation-v6')
second=Path(tempfile.mkdtemp(prefix='d148-v6-deterministic-'))
repeat=b.build(source/'conference/d148-client',second)
assert receipt==repeat
archive=source/'artifacts/d148/client-invocation-v6'/receipt['archive']
assert archive.read_bytes()==(second/receipt['archive']).read_bytes()
proof=Path(tempfile.mkdtemp(prefix='d148-client-v6-bundle-proof-'))
with tarfile.open(archive) as tar:
    assert all(m.isfile() and m.name.startswith('d148-client-invocation-resilient-v6/') and '..' not in Path(m.name).parts for m in tar)
    tar.extractall(proof,filter='data')
extracted=proof/'d148-client-invocation-resilient-v6'
verified=subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=extracted,capture_output=True,text=True,check=True)
subprocess.run([sys.executable,'-I','-B','-m','venv','--without-pip',str(proof/'.venv')],check=True)
created=subprocess.run(['../.venv/bin/python','-I','-B','control_fixture.py','--case','normal'],cwd=extracted,capture_output=True,text=True,check=True)
root=Path(json.loads(created.stdout)['fixture_root'])
preflight=subprocess.run(['../.venv/bin/python','-I','-B','control_fixture.py','--preflight-root',str(root)],cwd=extracted,capture_output=True,text=True,check=True)
installed=json.loads((root/'.d148/installed.json').read_text())
assert installed['python']==str(proof/'.venv/bin/python')
assert not list((root/'.d148').glob('attachment-*.json'))
assert not list((root.parent/'carbon-canonical-v4').iterdir())
value={'archive':str(archive),'bytes':receipt['bytes'],'sha256':receipt['sha256'],'member_count':len(receipt['members']),'deterministic_build_byte_identical':True,
       'extraction':str(extracted),'generator_command':['../.venv/bin/python','-I','-B','control_fixture.py','--case','normal'],
       'generated_fixture':json.loads(created.stdout),'explicit_preflight':json.loads(preflight.stdout),
       'normalized_python':installed['python'],'no_attachment_receipt':True,'no_synthetic_science_access':True,'member_checks':verified.stdout.splitlines()}
(evidence/'bundle-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
(evidence/'bundle-extracted-verification.json').write_text(json.dumps(value,indent=2)+'\n')
Path('/tmp/d148-v6-extracted-path.txt').write_text(str(extracted))
print(json.dumps(value,indent=2))
