"""D-148 explicit successor package delta against the inherited public inventory."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[2]
FILES = {'__init__.py','__main__.py','contracts.py','fixture.py','models.py','training.py','runtime.py','job.py','tracker.py'}


def test_exact_successor_delta():
    old = json.loads(subprocess.check_output(['git','show','6eb17cbc68752cf0ed4d29b0d67e4544d6efd8f8:packaging/public-package-allowlist-v1.json'], cwd=ROOT))
    new = json.loads((ROOT/'packaging/public-package-allowlist-v1.json').read_text())
    additions = {'src/qcoder/ml_research/'+name for name in FILES}
    assert set(new['allowed_python_sources']) == set(old['allowed_python_sources']) | additions
    assert set(new['allowed_packages']) == set(old['allowed_packages']) | {'qcoder.ml_research'}
    assert new['allowed_package_data_filenames'] == old['allowed_package_data_filenames']
    manifest=(ROOT/'MANIFEST.in').read_text()
    assert all('include '+name+'\n' in manifest for name in additions)
    assert 'graft ' not in manifest and 'recursive-include' not in manifest
    assert {p.name for p in (ROOT/'src/qcoder/ml_research').glob('*.py')} == FILES


def test_source_package_inventory_and_version():
    spec=importlib.util.spec_from_file_location('verify',ROOT/'scripts/verify_public_package_allowlist.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # Bytecode is disabled in all D-148 validation commands.
    report=module.verify_source_tree(ROOT)
    assert report['member_count'] == len(module.expected_source_payload(module.load_allowlist()))
    p=tomllib.loads((ROOT/'pyproject.toml').read_text())
    d=json.loads((ROOT/'development-version.json').read_text())
    assert p['project']['version']==d['version']=='0.6.0a24.post0.dev4+iqt.d148.ml.v1'
    assert d['publication_permitted'] is False
    assert all('==' in pin for pin in p['project']['optional-dependencies']['ml-research'])


def test_isolated_source():
    for path in (ROOT/'src/qcoder/ml_research').glob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.module:
                assert not node.module.startswith(('qcoder.current_loop','qcoder.protected','qcoder.explorer','qcoder.executors'))
            if isinstance(node,ast.Call):
                name = getattr(node.func,'id',getattr(node.func,'attr',''))
                assert name not in {'exec','compile','load','loads','load_model','search_runs'}
                assert not (isinstance(node.func, ast.Name) and name == 'eval')
