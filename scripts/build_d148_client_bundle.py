"""Reproducible client-only archive; never build or install qCoder."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

NAMES = ('runtime.py','setup.py','guard','qcoder-context','binding.mdc','hooks.json',
         'cursorignore','package.json','control_fixture.py','CARBON-INSTALL.txt',
         'acceptance-template.json')


def build(source, destination):
    files = {name:(source/name).read_bytes() for name in NAMES}
    manifest = {name:hashlib.sha256(value).hexdigest() for name,value in files.items()}
    files['payload.json'] = (json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    files['SHA256SUMS'] = ''.join(hashlib.sha256(value).hexdigest()+'  '+name+'\n'
                                  for name,value in sorted(files.items())).encode()
    destination.mkdir(parents=True,exist_ok=True)
    archive=destination/'d148-client-invocation-correction-v3.tar.gz'
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as tar:
        for name,value in sorted(files.items()):
            item=tarfile.TarInfo('d148-client-invocation-correction-v3/'+name)
            item.size=len(value);item.mtime=1790899200
            item.mode=0o755 if name in ('guard','qcoder-context') else 0o644
            tar.addfile(item,io.BytesIO(value))
    with archive.open('xb') as output:
        with gzip.GzipFile(filename='',fileobj=output,mode='wb',mtime=0,compresslevel=9) as gz:
            gz.write(stream.getvalue())
    receipt={'archive':archive.name,'bytes':archive.stat().st_size,
             'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
             'members':{name:{'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()} for name,value in sorted(files.items())},
             'wheel_included':False,'scientific_state_included':False}
    (destination/'bundle-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    # Verify membership, regular entries, bytes and checksums after packaging.
    with tarfile.open(archive) as tar:
        assert len(tar.getmembers())==len(files)
        for member in tar:
            assert member.isfile()
            name=member.name.removeprefix('d148-client-invocation-correction-v3/')
            assert tar.extractfile(member).read()==files[name]
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.source,args.destination),indent=2))
