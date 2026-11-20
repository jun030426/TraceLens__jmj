"""Package paths and exact code-hash compatibility for this folder-only refactor.

Existing plans/results are not rewritten. Data hashes and unknown code changes
retain their exact-match requirements; no extraction judgments change here.
"""
import hashlib
import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent


def _migration():
    return json.loads((PACKAGE_ROOT / 'layout-migration.json').read_text())


def source_path(filename):
    name = str(filename)
    if Path(name).name != name or not name.endswith('.py'):
        raise ValueError('invalid_source_module_name')
    return PACKAGE_ROOT / _migration()['modules'][name[:-3]]


def code_hashes_match(expected, current):
    if expected == current:
        return True
    migration = _migration()
    if migration.get('helper_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        return False
    if isinstance(expected, dict) and isinstance(current, dict):
        if expected.keys() != current.keys():
            return False
        for name in expected:
            if expected[name] == current[name]:
                continue
            record = migration['files'].get(name)
            if not record or current[name] != record['after'] or expected[name] not in [record['before'], *record.get('previous_hashes', [])]:
                return False
        return True
    if not isinstance(expected, str) or not isinstance(current, str):
        return False
    return any(current == r['after'] and expected in [r['before'], *r.get('previous_hashes', [])]
               for r in migration['files'].values())
