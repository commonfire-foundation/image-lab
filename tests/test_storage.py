import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from image_lab_ui.catalog import Catalog
from image_lab_ui.queue import JobQueue
from image_lab_ui.storage import storage_paths
from image_lab_ui.migrate import migrate_catalog


class StorageTests(unittest.TestCase):
    def test_defaults_and_absolute_xdg_overrides(self):
        home = Path('/example/home')
        defaults = storage_paths(environ={}, home=home)
        self.assertEqual(defaults.data, home / '.local/share/image-lab')
        self.assertEqual(defaults.thumbnails, home / '.cache/image-lab/thumbnails')
        self.assertEqual(defaults.config, home / '.config/image-lab')
        paths = storage_paths(environ={'XDG_DATA_HOME':'/custom/data', 'XDG_CACHE_HOME':'/custom/cache',
                                       'XDG_CONFIG_HOME':'/custom/config'}, home=home)
        self.assertEqual(paths.data, Path('/custom/data/image-lab'))
        self.assertEqual(paths.thumbnails, Path('/custom/cache/image-lab/thumbnails'))
        self.assertEqual(paths.config, Path('/custom/config/image-lab'))

    def test_invalid_xdg_values_and_explicit_development_override(self):
        paths = storage_paths(environ={'XDG_DATA_HOME':'relative', 'XDG_CACHE_HOME':''}, home='/example/home')
        self.assertEqual(paths.data, Path('/example/home/.local/share/image-lab'))
        paths = storage_paths('/explicit/catalog', environ={}, home='/example/home')
        self.assertEqual(paths.thumbnails, Path('/explicit/catalog/thumbnails'))
        paths = storage_paths('/explicit/catalog', '/other/cache', environ={}, home='/example/home')
        self.assertEqual(paths.thumbnails, Path('/other/cache/thumbnails'))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Migration uses Qt desktop locks')
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = Catalog(self.root / 'source')
        self.addCleanup(self.source.close)
        image = self.root / 'sample.png'
        Image.new('RGB', (80, 60), 'blue').save(image)
        self.source.import_image(image)
        self.row = self.source.rows()[0]
        queue = JobQueue(self.source)
        batch = queue.enqueue([self.row['id']])
        job = queue.claim(batch)
        queue.succeed(job['id'], {'vision':{'tags':['blue']}, 'elapsed_seconds':3.0})
        self.destination = self.root / 'user-data'
        self.thumbnails = self.root / 'user-cache' / 'thumbnails'

    def test_backup_preserves_predictions_jobs_and_originals(self):
        old = self.source.get(self.row['id'])
        report = migrate_catalog(self.source.directory, self.destination, self.thumbnails)
        self.assertEqual((report['images'],report['jobs'],report['batches'],report['predictions']), (1,1,1,1))
        new = Catalog(self.destination, self.thumbnails)
        try:
            row = new.get(old['id'])
            self.assertEqual(row['prediction'], old['prediction'])
            self.assertEqual(row['path'], old['path'])
            self.assertTrue(Path(row['thumbnail']).is_relative_to(self.thumbnails))
            self.assertEqual(Path(row['thumbnail']).read_bytes(),Path(old['thumbnail']).read_bytes())
            self.assertEqual(JobQueue(new).summary(1)['succeeded'],1)
            self.assertEqual(new.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertFalse((self.destination / 'thumbnails').exists())
        finally:
            new.close()
        self.assertEqual(self.source.get(old['id']), old)
        self.assertTrue(Path(old['thumbnail']).exists())
        self.assertEqual((self.destination / 'catalog.sqlite3').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            migrate_catalog(self.source.directory, self.destination, self.thumbnails)

    def test_refuses_active_source_lock(self):
        from PySide6.QtCore import QLockFile
        lock = QLockFile(str(self.source.directory / 'desktop.lock'))
        self.assertTrue(lock.tryLock(0))
        try:
            with self.assertRaisesRegex(RuntimeError, 'Close Image Lab'):
                migrate_catalog(self.source.directory, self.destination, self.thumbnails)
            self.assertFalse((self.destination / 'catalog.sqlite3').exists())
        finally:
            lock.unlock()

    def test_conflicting_thumbnail_does_not_overwrite(self):
        self.thumbnails.mkdir(parents=True)
        target = self.thumbnails / Path(self.row['thumbnail']).name
        target.write_bytes(b'user file')
        with self.assertRaises(FileExistsError):
            migrate_catalog(self.source.directory, self.destination, self.thumbnails)
        self.assertEqual(target.read_bytes(), b'user file')
        self.assertFalse((self.destination / 'catalog.sqlite3').exists())
        self.assertEqual(list(self.destination.glob('.migration-*')), [])

    def test_cache_regeneration_preserves_saved_prediction(self):
        migrate_catalog(self.source.directory, self.destination, self.thumbnails)
        new = Catalog(self.destination, self.thumbnails)
        try:
            row = new.rows()[0]
            prediction = row['prediction']
            Path(row['thumbnail']).unlink()
            self.assertTrue(new.import_image(row['path']))
            self.assertEqual(new.get(row['id'])['prediction'], prediction)
            self.assertTrue(Path(row['thumbnail']).is_file())
        finally:
            new.close()


if __name__ == '__main__':
    unittest.main()
