"""Read-only exact archive/source/installed-byte verification for D-148 evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--wheel', type=Path, required=True)
    p.add_argument('--sdist', type=Path, required=True)
    p.add_argument('--python', type=Path, required=True)
    p.add_argument('--commit', required=True)
    args=p.parse_args()
    allow=json.loads((args.source/'packaging/public-package-allowlist-v1.json').read_text())
    payload=allow['allowed_python_sources']+allow['allowed_package_data_filenames']
    with zipfile.ZipFile(args.wheel) as wheel, tarfile.open(args.sdist) as sdist:
        prefix=sdist.getnames()[0].split('/')[0]+'/'
        source_members=[]
        for name in sorted(payload):
            raw=(args.source/name).read_bytes()
            assert raw==wheel.read(name.removeprefix('src/'))
            assert raw==sdist.extractfile(prefix+name).read()
            source_members.append({'path':name,'sha256':digest(raw),'bytes':len(raw)})
        wheel_members=[{'path':n,'sha256':digest(wheel.read(n)),'bytes':len(wheel.read(n))} for n in sorted(wheel.namelist())]
        sdist_members=[{'path':i.name,'sha256':digest(sdist.extractfile(i).read()),'bytes':i.size} for i in sdist.getmembers() if i.isfile()]
    script='''
import hashlib,json,pathlib,sys
import qcoder,qcoder.ml_research
assert not any(m in sys.modules for m in ('torch','pennylane','mlflow'))
from qcoder.ml_research.runtime import runtime,code_identity
root=pathlib.Path(qcoder.__file__).parent.parent
assert 'site-packages' in str(root)
expected=json.loads(sys.stdin.read())
for item in expected:
    path=root/item['path'].removeprefix('src/')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],str(path)
print(json.dumps({'site_packages':str(root),'qcoder_origin':qcoder.__file__,'ml_research_origin':qcoder.ml_research.__file__,'version':qcoder.__version__,'verified_file_count':len(expected),'runtime':runtime(),'code_identity':code_identity()}))
'''
    observed=subprocess.run([str(args.python),'-I','-c',script],input=json.dumps(source_members),capture_output=True,text=True,check=True,cwd='/tmp')
    installed=json.loads(observed.stdout)
    assert not Path(installed['site_packages']).is_relative_to(args.source)
    print(json.dumps({'schema':'d148.artifact_proof.v1','source_commit':args.commit,'source_members':source_members,'wheel':{'name':args.wheel.name,'sha256':digest(args.wheel.read_bytes()),'members':wheel_members},'sdist':{'name':args.sdist.name,'sha256':digest(args.sdist.read_bytes()),'members':sdist_members},'source_wheel_sdist_bytes_equal':True,'installed':installed},sort_keys=True,indent=2))


if __name__=='__main__':
    main()
