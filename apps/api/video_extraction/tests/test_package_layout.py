"""Offline regression coverage for physical moves and existing-plan guards."""
import hashlib
import importlib
import json
import unittest
from unittest.mock import patch
from video_extraction import _layout as layout


class LayoutTests(unittest.TestCase):
    def test_modules_exist_once_and_import_at_new_location(self):
        manifest = layout._migration()
        for name, relative in manifest['modules'].items():
            with self.subTest(module=name):
                target = layout.source_path(name + '.py')
                self.assertEqual(target, layout.PACKAGE_ROOT / relative)
                self.assertTrue(target.is_file())
                self.assertFalse(target.is_symlink())
                if '/' in relative:
                    self.assertFalse((layout.PACKAGE_ROOT / (name + '.py')).exists())
                importlib.import_module('video_extraction.' + relative[:-3].replace('/', '.'))

    def test_only_recorded_code_move_is_accepted(self):
        for name, row in layout._migration()['files'].items():
            actual = hashlib.sha256((layout.PACKAGE_ROOT / row['path']).read_bytes()).hexdigest()
            # Later functional edits must NOT acquire the import-only compatibility exception.
            self.assertEqual(layout.code_hashes_match({name: row['before']}, {name: actual}),
                             actual in (row['before'], row['after']), name)
            self.assertFalse(layout.code_hashes_match({name: 'unrelated-version'}, {name: actual}))
            self.assertFalse(layout.code_hashes_match({name: row['before']}, {name: 'later-edit'}))
        row = next(r for r in layout._migration()['files'].values() if r['before'] != r['after'])
        self.assertFalse(layout.code_hashes_match({'data.json': row['before']}, {'data.json': row['after']}))
        self.assertFalse(layout.code_hashes_match({'a': 'same'}, {'b': 'same'}))

    def test_edited_compatibility_helper_disables_exception(self):
        manifest = layout._migration()
        row = next(r for r in manifest['files'].values() if r['before'] != r['after'])
        manifest['helper_sha256'] = 'edited'
        with patch.object(layout, '_migration', return_value=manifest):
            self.assertFalse(layout.code_hashes_match(row['before'], row['after']))

    def test_intermediate_layout_plans_remain_compatible(self):
        checked = 0
        for name, row in layout._migration()['files'].items():
            for previous in row.get('previous_hashes', []):
                self.assertTrue(layout.code_hashes_match({name: previous}, {name: row['after']}))
                self.assertFalse(layout.code_hashes_match({name: previous}, {name: 'unknown-new-code'}))
                checked += 1
        self.assertGreater(checked, 0)

    def test_source_names_do_not_escape_package(self):
        for name in ['../common.py', '/tmp/common.py', 'data.json']:
            with self.assertRaises(ValueError):
                layout.source_path(name)


if __name__ == '__main__':
    unittest.main()
