from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from image_lab_ui.catalog import Catalog
from image_lab_ui.renaming import next_available_name, rename_noreplace, rename_target


class RenamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root / 'cache')
        self.addCleanup(self.catalog.close)
        self.source = self.root / 'original.png'
        Image.new('RGB', (20, 10), 'blue').save(self.source)
        self.original = self.source.read_bytes()
        self.catalog.import_image(self.source)
        self.image_id = self.catalog.rows()[0]['id']
        self.catalog.store_result(self.image_id, self.catalog.fingerprint(self.source), {'vision': {'tags': ['blue']}})
        self.saved = self.catalog.get(self.image_id)

    def rename(self, name='blue-image.png'):
        return self.catalog.rename_image(self.image_id, str(self.source), name)

    def test_rename_preserves_data_and_rescan_identity(self):
        target = Path(self.rename())
        self.assertFalse(self.source.exists())
        self.assertEqual(target.read_bytes(), self.original)
        updated = self.catalog.get(self.image_id)
        self.assertEqual(updated, dict(self.saved, path=str(target)))
        self.assertTrue(Path(updated['thumbnail']).is_file())
        self.assertFalse(self.catalog.import_image(target))
        self.assertEqual(self.catalog.count(), 1)
        self.assertEqual(self.catalog.count('blue-image'), 1)

    def test_existing_file_and_dangling_symlink_are_not_replaced(self):
        target = self.root / 'blue-image.png'
        target.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            self.rename()
        self.assertEqual(target.read_bytes(), b'existing')
        target.unlink()
        target.symlink_to(self.root / 'missing.png')
        with self.assertRaises(FileExistsError):
            self.rename()
        self.assertTrue(target.is_symlink())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.catalog.get(self.image_id), self.saved)

    def test_invalid_names_and_extension_changes(self):
        for name in ('', '../escape.png', '/tmp/escape.png', 'folder\\file.png',
                     'bad\x00.png', 'bad\n.png', 'new.jpg', 'new.PNG', '.png',
                     'original.png', ' spaced.png', 'x' * 260 + '.png'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                rename_target(self.source, name)

    def test_stale_source_and_catalog_collision_are_rejected(self):
        with self.assertRaises(ValueError):
            self.catalog.rename_image(self.image_id, str(self.root/'other.png'), 'new.png')
        target = self.root / 'blue-image.png'
        Image.new('RGB', (10, 10), 'red').save(target)
        self.catalog.import_image(target)
        target.unlink()
        with self.assertRaisesRegex(ValueError, 'catalog'):
            self.rename()
        self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.rename('another.png')

    def test_queued_image_is_rejected(self):
        self.catalog.db.execute('CREATE TABLE jobs (image_id INTEGER, state TEXT)')
        with self.catalog.db:
            self.catalog.db.execute("INSERT INTO jobs VALUES (?, 'queued')", (self.image_id,))
        with self.assertRaisesRegex(ValueError, 'queue'):
            self.rename()
        self.assertTrue(self.source.exists())

    def test_database_error_rolls_filesystem_back(self):
        self.catalog.db.execute("CREATE TRIGGER reject_rename BEFORE UPDATE OF path ON images BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.rename()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.root / 'blue-image.png').exists())
        self.assertEqual(self.catalog.get(self.image_id), self.saved)

    def test_missing_or_symlink_source_is_rejected(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.rename()
        replacement = self.root / 'replacement.png'
        replacement.write_bytes(self.original)
        self.source.symlink_to(replacement)
        with self.assertRaisesRegex(ValueError, 'regular'):
            self.rename()
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(replacement.read_bytes(), self.original)

    def test_failed_rollback_reports_actual_file_location(self):
        self.catalog.db.execute("CREATE TRIGGER reject_rename BEFORE UPDATE OF path ON images BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        calls = []
        def move_once(source, target):
            calls.append((source, target))
            if len(calls) == 1:
                return rename_noreplace(source, target)
            raise PermissionError('restoration denied')
        with patch('image_lab_ui.catalog.rename_noreplace', side_effect=move_once):
            with self.assertRaisesRegex(RuntimeError, 'blue-image.png.*catalog still points'):
                self.rename()
        self.assertFalse(self.source.exists())
        self.assertEqual((self.root / 'blue-image.png').read_bytes(), self.original)
        self.assertEqual(self.catalog.get(self.image_id), self.saved)

    def test_alternative_skips_files_directories_symlinks_and_catalog_paths(self):
        (self.root / 'blue-image.png').write_bytes(b'existing')
        (self.root / 'blue-image-2.png').mkdir()
        (self.root / 'blue-image-3.png').symlink_to(self.root / 'missing')
        reserved = self.root / 'blue-image-4.png'
        Image.new('RGB', (10, 10)).save(reserved)
        self.catalog.import_image(reserved)
        reserved.unlink()
        self.assertEqual(self.catalog.alternate_name(self.source, 'blue-image.png'), 'blue-image-5.png')
        self.assertEqual(self.catalog.alternate_name(self.source, 'blue-image-4.png'), 'blue-image-5.png')
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.root / 'blue-image-5.png').exists())
        self.assertEqual(self.catalog.get(self.image_id), self.saved)

    def test_alternative_length_extension_and_bounded_search(self):
        name = '湖' * 83 + '.png'
        alternative = next_available_name(self.source, name)
        self.assertTrue(alternative.endswith('-2.png'))
        self.assertLessEqual(len(alternative.encode('utf-8')), 255)
        self.assertEqual(next_available_name(self.root/'old.JPG', 'forest.JPG'), 'forest-2.JPG')
        self.assertEqual(next_available_name(self.source, 'forest.png', reserved=lambda path: True, limit=3), '')

    def test_alternative_avoids_original_name(self):
        self.assertEqual(next_available_name(self.root/'forest-2.png', 'forest.png'), 'forest-3.png')

    def test_filesystem_failure_leaves_catalog_unchanged(self):
        with patch('image_lab_ui.catalog.rename_noreplace', side_effect=PermissionError('read only')):
            with self.assertRaises(PermissionError):
                self.rename()
        self.assertEqual(self.catalog.get(self.image_id), self.saved)
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
