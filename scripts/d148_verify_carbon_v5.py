"""Offline qCoder-only update verification. Does not access any workspace/tracker."""
import argparse
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path

import qcoder
from qcoder.ml_research import runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    for line in (bundle/'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        path = (bundle/name).resolve()
        assert path.is_relative_to(bundle)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    manifest = json.loads((bundle/'transfer-manifest.json').read_text())
    phase = 'dev7' if args.preflight else 'dev8'
    assert qcoder.__version__ == manifest[phase]['version']
    site = Path(qcoder.__file__).resolve().parent.parent
    assert site.name == 'site-packages'
    expected = manifest[phase]['payload_sha256']
    actual = {str(p.relative_to(site)) for p in (site/'qcoder').rglob('*') if p.is_file() and p.suffix not in ('.pyc', '.pyo')}
    assert actual == set(expected), 'installed payload membership'
    for name, digest in expected.items():
        assert hashlib.sha256((site/name).read_bytes()).hexdigest() == digest, name
    dependencies = {}
    for line in (bundle/'dependencies.lock.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            name, version = line.split('==')
            dependencies[name.lower().replace('_','-')] = version
    observed = {d.metadata['Name'].lower().replace('_','-'):d.version for d in distributions() if d.metadata['Name'].lower() != 'qcoder'}
    assert observed == dependencies and len(observed) == 99, 'exact dependency set'
    for name, digest in manifest['preserved_identity_digests'].items():
        assert getattr(runtime, name)()['digest'] == digest, name
    print(json.dumps({'status':'preflight_pass' if args.preflight else 'installed_update_pass',
                      'version':qcoder.__version__, 'verified_payload_files':len(expected),
                      'exact_dependencies':99, 'identity_domains_preserved':True,
                      'new_canonical_science':0, 'tracker_access':False}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
