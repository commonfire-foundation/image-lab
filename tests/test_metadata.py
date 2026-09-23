import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PIL import Image
from image_lab_ui.catalog import Catalog
from image_lab_ui.metadata import edit_revision, effective_details, validate_details


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root / 'cache')
        self.addCleanup(self.catalog.close)
        self.image = self.root / 'image.png'
        Image.new('RGB', (20, 10), 'red').save(self.image)
        self.catalog.import_image(self.image)
        self.image_id = self.catalog.rows()[0]['id']
        self.generated = dict(caption='A crimson forest', tags=['crimson', 'trees'],
                              medium='photography', mood=['calm'], composition=['centered'],
                              text_present=False, watermark_present=True)
        self.catalog.store_result(self.image_id, self.catalog.fingerprint(self.image),
                                  {'vision': self.generated, 'model': 'original-model'})

    def row(self):
        return self.catalog.get(self.image_id)

    def save(self, **changes):
        self.catalog.save_details(self.image_id, edit_revision(self.row()), dict(self.generated, **changes))

    def test_save_preserves_model_output_and_source_updates_search(self):
        original, saved = self.image.read_bytes(), self.row()
        self.save(caption='A blue lake', tags=[' Blue ', 'blue', '', 'water'], watermark_present=False)
        row = self.row()
        self.assertEqual(row['prediction'], saved['prediction'])
        self.assertEqual(row['error'], saved['error'])
        self.assertEqual(self.image.read_bytes(), original)
        self.assertEqual(json.loads(row['user_edits']), {
            'caption': 'A blue lake', 'tags': ['Blue', 'water'], 'watermark_present': False})
        self.assertEqual(self.catalog.count('crimson'), 0)
        self.assertEqual(self.catalog.count('water'), 1)
        self.assertEqual(self.catalog.matching_ids('lake', status='tagged'), [self.image_id])
        other = Catalog(self.root / 'cache')
        try:
            self.assertEqual(effective_details(other.get(self.image_id))['caption'], 'A blue lake')
        finally:
            other.close()

    def test_reanalysis_keeps_corrections_but_updates_unedited_fields(self):
        self.save(caption='My correction', tags=[])
        self.catalog.store_result(self.image_id, self.catalog.fingerprint(self.image),
                                  {'vision': dict(self.generated, caption='New AI caption', medium='painting')})
        details = effective_details(self.row())
        self.assertEqual(details['caption'], 'My correction')
        self.assertEqual(details['tags'], [])
        self.assertEqual(details['medium'], 'painting')

    def test_unchanged_save_does_not_mark_metadata_edited(self):
        self.save()
        self.assertEqual(json.loads(self.row()['user_edits']), {})
        self.save(caption='Correction')
        self.save()  # Restoring generated values removes the overrides.
        self.assertEqual(json.loads(self.row()['user_edits']), {})

    def test_invalid_and_stale_edits_leave_catalog_unchanged(self):
        revision = edit_revision(self.row())
        self.save(caption='First correction')
        saved = self.row()
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.catalog.save_details(self.image_id, revision, self.generated)
        for changes in ({'tags': 'not a list'}, {'text_present': 'yes'}, {'caption': 'x' * 8001},
                        {'mood': ['x' * 121]}, {'tags': ['x'] * 101}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.save(**changes)
        with self.assertRaises(ValueError):
            validate_details({'unknown': 'value'})
        self.assertEqual(self.row(), saved)

    def test_queued_and_changed_sources_block_edits(self):
        self.catalog.db.execute('CREATE TABLE jobs (image_id INTEGER, state TEXT)')
        with self.catalog.db:
            self.catalog.db.execute("INSERT INTO jobs VALUES (?, 'queued')", (self.image_id,))
        with self.assertRaisesRegex(ValueError, 'queue'):
            self.save(caption='No')
        with self.catalog.db:
            self.catalog.db.execute('DELETE FROM jobs')
        self.image.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.save(caption='No')

    def test_rescan_keeps_edits_for_same_source_and_resets_for_changed_source(self):
        self.save(caption='Correction')
        Path(self.row()['thumbnail']).unlink()
        self.catalog.import_image(self.image)
        self.assertEqual(effective_details(self.row())['caption'], 'Correction')
        Image.new('RGB', (30, 30), 'blue').save(self.image)
        self.catalog.import_image(self.image)
        self.assertEqual(self.row()['user_edits'], '{}')
        self.assertIsNone(self.row()['prediction'])

    def test_rename_preserves_corrections_and_invalidates_open_draft(self):
        self.save(caption='A blue lake')
        row = self.row()
        self.catalog.rename_image(self.image_id, str(self.image), 'blue-lake.png')
        self.assertEqual(self.row()['user_edits'], row['user_edits'])
        self.assertEqual(self.row()['prediction'], row['prediction'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.catalog.save_details(self.image_id, edit_revision(row), self.generated)

    def test_existing_database_gets_non_destructive_column_migration(self):
        directory = self.root / 'legacy'
        directory.mkdir()
        db = sqlite3.connect(directory / 'catalog.sqlite3')
        db.execute("""CREATE TABLE images (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
            mtime INTEGER NOT NULL, bytes INTEGER NOT NULL, thumbnail TEXT NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL, prediction TEXT,
            error TEXT NOT NULL DEFAULT '')""")
        saved = self.row()
        columns = [key for key in saved if key != 'user_edits']
        db.execute(f"INSERT INTO images ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                   [saved[key] for key in columns])
        db.commit()
        db.close()
        migrated = Catalog(directory)
        try:
            self.assertEqual(migrated.get(self.image_id), saved)
        finally:
            migrated.close()


if __name__ == '__main__':
    unittest.main()
