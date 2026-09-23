from pathlib import Path
import tempfile
import unittest

from PIL import Image
from image_lab_ui.catalog import Catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root / "cache")
        self.addCleanup(self.catalog.close)
        self.image = self.root / "sample.png"
        Image.new("RGB", (200, 100), "blue").save(self.image)

    def test_remove_preserves_original_and_reimport_starts_fresh(self):
        original = self.image.read_bytes()
        self.catalog.import_image(self.image)
        row = self.catalog.rows()[0]
        self.catalog.store_result(row['id'], (row['mtime'], row['bytes']), {'vision': {'tags': ['blue']}})
        self.assertEqual(self.catalog.remove_images([row['id'], row['id']]), 1)
        self.assertEqual(self.catalog.count(), 0)
        self.assertEqual(self.image.read_bytes(), original)
        self.catalog.import_image(self.image)
        self.assertIsNone(self.catalog.rows()[0]['prediction'])
        # Missing originals can still be removed from the library.
        self.image.unlink()
        self.catalog.remove_images([self.catalog.rows()[0]['id']])
        self.assertEqual(self.catalog.count(), 0)

    def test_remove_is_atomic_and_cleans_terminal_job_history(self):
        from image_lab_ui.queue import JobQueue

        queue = JobQueue(self.catalog)
        self.catalog.import_image(self.image)
        second = self.root / 'second.png'
        Image.new('RGB', (2, 2), 'red').save(second)
        self.catalog.import_image(second)
        ids = self.catalog.matching_ids()
        with self.catalog.db:
            self.catalog.db.execute("INSERT INTO batches VALUES (1, 'paused', 0)")
            self.catalog.db.execute("""INSERT INTO jobs
                (batch_id,image_id,mtime,bytes,model,prompt_version,prompt,state)
                VALUES (1,?,0,0,'test','test','test','queued')""", (ids[1],))
        for state in ('queued', 'running'):
            with self.catalog.db:
                self.catalog.db.execute('UPDATE jobs SET state=?', (state,))
            with self.assertRaisesRegex(ValueError, 'queue'):
                self.catalog.remove_images(ids)
            self.assertEqual(self.catalog.count(), 2)
        with self.catalog.db:
            self.catalog.db.execute("UPDATE jobs SET state='failed'")
        with self.assertRaises(ValueError):
            self.catalog.remove_images([ids[0], 999999])
        self.assertEqual(self.catalog.count(), 2)
        self.catalog.remove_images(ids)
        self.assertEqual(queue.entry_count(), 0)
        self.assertEqual(self.catalog.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        self.assertTrue(second.is_file())

    def test_remove_rejects_invalid_ids(self):
        for ids in ([], [True], ['1'], [0], [-1]):
            with self.assertRaises(ValueError):
                self.catalog.remove_images(ids)

    def test_import_preserves_source_and_deduplicates(self):
        original = self.image.read_bytes()
        self.assertTrue(self.catalog.import_image(self.image))
        self.assertFalse(self.catalog.import_image(self.image))
        self.assertEqual(self.catalog.count(), 1)
        row = self.catalog.rows()[0]
        self.assertEqual((row["width"], row["height"]), (200, 100))
        self.assertTrue(Path(row["thumbnail"]).is_file())
        self.assertEqual(self.image.read_bytes(), original)

    def test_prediction_search_and_failed_retry(self):
        self.catalog.import_image(self.image)
        row = self.catalog.rows()[0]
        stamp = self.catalog.fingerprint(self.image)
        self.catalog.store_result(row["id"], stamp, {"vision": {"tags": ["ocean"]}, "prompt": "notsearchable"})
        self.assertEqual(self.catalog.count("ocean"), 1)
        self.assertEqual(self.catalog.count("notsearchable"), 0)
        self.assertEqual(self.catalog.count("%"), 0)
        self.catalog.store_result(row["id"], stamp, error="offline")
        self.assertTrue(self.catalog.get(row["id"])["prediction"])
        self.assertEqual(self.catalog.get(row["id"])["error"], "offline")

    def test_status_filters_counts_and_search_intersection(self):
        for name in ('fresh', 'tagged', 'failed', 'retained'):
            path = self.root / f'group-{name}.png'
            Image.new('RGB', (2, 2), 'blue').save(path)
            self.catalog.import_image(path)
        rows = {Path(row['path']).stem: row for row in self.catalog.rows()}
        for name in ('tagged', 'retained'):
            row = rows['group-' + name]
            self.catalog.store_result(row['id'], (row['mtime'], row['bytes']), {'vision': {'tags': ['ocean']}})
        for name in ('failed', 'retained'):
            row = rows['group-' + name]
            self.catalog.store_result(row['id'], (row['mtime'], row['bytes']), error='offline')
        self.assertEqual(self.catalog.status_counts(), {'all': 4, 'needs_tags': 2, 'tagged': 2, 'failed': 2})
        self.assertEqual(self.catalog.status_counts('ocean'), {'all': 2, 'needs_tags': 0, 'tagged': 2, 'failed': 1})
        for status in self.catalog.FILTERS:
            matches = self.catalog.rows('group-', status=status)
            self.assertEqual(len(matches), self.catalog.count('group-', status=status))
            self.assertEqual([row['id'] for row in matches], self.catalog.matching_ids('group-', status=status))
        self.assertEqual(self.catalog.matching_ids('ocean', status='failed'), [rows['group-retained']['id']])
        self.assertEqual(self.catalog.matching_ids(status='failed', missing=True), [rows['group-failed']['id']])
        self.assertEqual(self.catalog.matching_ids(status='tagged', missing=True), [])
        self.assertEqual(self.catalog.status_counts('%'), dict.fromkeys(self.catalog.FILTERS, 0))
        with self.assertRaisesRegex(ValueError, 'Unknown library filter'):
            self.catalog.rows(status='invalid')

    def test_changed_source_rejects_result_and_rescan_invalidates(self):
        self.catalog.import_image(self.image)
        row = self.catalog.rows()[0]
        stamp = self.catalog.fingerprint(self.image)
        self.catalog.store_result(row["id"], stamp, {"vision": {"tags": ["blue"]}})
        Image.new("RGB", (300, 100), "red").save(self.image)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.catalog.store_result(row["id"], stamp, {"vision": {}})
        self.catalog.import_image(self.image)
        self.assertIsNone(self.catalog.get(row["id"])["prediction"])
        self.assertEqual(self.catalog.get(row["id"])["width"], 300)

    def test_scan_skips_cache_and_records_unreadable(self):
        (self.root / "broken.jpg").write_text("not an image")
        count, errors, stopped = self.catalog.scan(self.root)
        self.assertEqual((count, errors, stopped), (1, 1, False))
        self.assertEqual(self.catalog.scan(self.root), (1, 1, False))
        self.assertEqual(self.catalog.scan(self.root, cancelled=lambda: True), (0, 0, True))

    def test_missing_folder(self):
        with self.assertRaisesRegex(ValueError, "existing"):
            self.catalog.scan(self.root / "missing")

    def test_paging(self):
        for i in range(125):
            path = self.root / f"image-{i:03}.png"
            Image.new("RGB", (2, 2)).save(path)
            self.catalog.import_image(path)
        first = self.catalog.rows()
        second = self.catalog.rows(offset=120)
        self.assertEqual((len(first), len(second)), (120, 5))
        self.assertEqual(len(self.catalog.matching_ids()), 125)
        self.assertEqual(len(self.catalog.matching_ids('image-12', missing=True)), 5)
        self.assertFalse({r['id'] for r in first} & {r['id'] for r in second})
        with self.catalog.db:
            self.catalog.db.execute("UPDATE images SET prediction=? WHERE id % 2=0", ('{"vision":{"tags":["blue"]}}',))
        filtered = self.catalog.rows(status='needs_tags', limit=20)
        remainder = self.catalog.rows(status='needs_tags', offset=20)
        self.assertEqual(len(filtered) + len(remainder), 63)
        self.assertEqual([row['id'] for row in filtered + remainder], self.catalog.matching_ids(status='needs_tags'))


if __name__ == "__main__":
    unittest.main()
