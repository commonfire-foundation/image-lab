from pathlib import Path
import tempfile
import unittest
from PIL import Image

from image_lab_ui.catalog import Catalog
from image_lab_ui.queue import JobQueue


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root / 'data')
        self.addCleanup(self.catalog.close)
        self.queue = JobQueue(self.catalog)
        self.ids = []
        for n in range(4):
            path = self.root / f'{n}.png'
            Image.new('RGB', (40, 30), 'red').save(path)
            self.catalog.import_image(path)
        self.ids = [r['id'] for r in self.catalog.rows()]

    def finish(self, job):
        self.queue.succeed(job['id'], {'vision': {'tags': ['red']}, 'elapsed_seconds': 10, 'job_id': job['id']})

    def test_serial_claim_dedup_and_missing(self):
        batch = self.queue.enqueue(self.ids + self.ids)
        self.assertEqual(self.queue.summary(batch)['total'], 4)
        first = self.queue.claim(batch)
        self.assertIsNone(self.queue.claim(batch))
        self.assertIsNone(self.queue.enqueue(self.ids))
        self.finish(first)
        second = self.queue.claim(batch)
        self.assertNotEqual(first['id'], second['id'])
        self.assertTrue(second['prompt'])
        self.queue.stop(batch)
        self.finish(second)
        next_batch = self.queue.enqueue(self.ids)
        self.assertEqual(self.queue.summary(next_batch)['total'], 2)

    def test_append_while_running_and_paused_preserves_order(self):
        batch = self.queue.enqueue(self.ids[:1])
        first = self.queue.claim(batch)
        self.assertEqual(self.queue.enqueue(self.ids[:3]), batch)
        self.assertEqual(self.queue.summary(batch)['total'], 3)
        self.queue.pause(batch)
        self.assertEqual(self.queue.enqueue(self.ids[3:]), batch)
        self.assertEqual(self.queue.summary(batch)['state'], 'paused')
        self.finish(first)
        self.assertIsNone(self.queue.claim(batch))
        self.queue.resume(batch)
        for image_id in self.ids[1:]:
            job = self.queue.claim(batch)
            self.assertEqual(job['image_id'], image_id)
            self.finish(job)
        self.assertEqual(self.queue.summary(batch)['succeeded'], 4)

    def test_pause_persists_when_current_finishes_before_append(self):
        batch = self.queue.enqueue(self.ids[:1])
        current = self.queue.claim(batch)
        self.queue.pause(batch)
        self.finish(current)
        self.assertEqual(self.queue.summary(batch)['state'], 'paused')
        self.assertEqual(self.queue.enqueue(self.ids[1:]), batch)
        self.assertIsNone(self.queue.claim(batch))
        self.queue.resume(batch)
        self.assertIsNotNone(self.queue.claim(batch))

    def test_remove_waiting_and_paginate_history(self):
        batch = self.queue.enqueue(self.ids)
        running = self.queue.claim(batch)
        entries = self.queue.entries(limit=2)
        self.assertEqual(self.queue.entry_count(), 4)
        self.assertEqual(entries[0]['id'], running['id'])
        self.assertFalse(self.queue.remove(running['id']))
        self.assertTrue(self.queue.remove(entries[1]['id']))
        self.assertFalse(self.queue.remove(entries[1]['id']))
        self.assertEqual(self.queue.image_state(entries[1]['image_id']), 'canceled')
        self.assertEqual(len(self.queue.entries(offset=2)), 2)
        self.assertEqual(self.queue.summary(batch)['queued'], 2)

    def test_add_after_stop_waits_for_current_to_finish(self):
        batch = self.queue.enqueue(self.ids[:2])
        current = self.queue.claim(batch)
        self.queue.stop(batch)
        next_batch = self.queue.enqueue(self.ids[2:])
        self.assertNotEqual(batch, next_batch)
        self.assertIsNone(self.queue.claim(next_batch))
        self.finish(current)
        self.assertEqual(self.queue.claim(next_batch)['image_id'], self.ids[2])

    def test_pause_resume_and_stop_after_current(self):
        batch = self.queue.enqueue(self.ids)
        job = self.queue.claim(batch)
        self.queue.pause(batch)
        self.finish(job)
        self.assertIsNone(self.queue.claim(batch))
        self.assertEqual(self.queue.summary(batch)['queued'], 3)
        self.queue.resume(batch)
        job = self.queue.claim(batch)
        self.queue.stop(batch)
        self.assertEqual(self.queue.summary(batch)['canceled'], 2)
        self.finish(job)
        self.assertEqual(self.queue.summary(batch)['state'], 'stopped')
        self.assertEqual(self.queue.summary(batch)['succeeded'], 2)

    def test_recovery_preserves_finished_and_pauses_pending(self):
        batch = self.queue.enqueue(self.ids)
        self.finish(self.queue.claim(batch))
        interrupted = self.queue.claim(batch)
        other = Catalog(self.root / 'data')
        try:
            reopened = JobQueue(other)
            reopened.recover()
            self.assertEqual(reopened.summary(batch)['state'], 'paused')
            self.assertEqual(reopened.summary(batch)['succeeded'], 1)
            self.assertEqual(reopened.get(interrupted['id'])['state'], 'queued')
            self.assertIsNone(reopened.claim(batch))
            reopened.resume(batch)
            self.assertEqual(reopened.claim(batch)['id'], interrupted['id'])
        finally:
            other.close()

    def test_stopped_inflight_recovery_does_not_resume(self):
        batch = self.queue.enqueue(self.ids)
        self.queue.claim(batch)
        self.queue.stop(batch)
        self.queue.recover()
        self.assertEqual(self.queue.summary(batch)['canceled'], 4)
        self.assertEqual(self.queue.summary(batch)['queued'], 0)

    def test_failure_continues_and_preserves_old_prediction(self):
        row = self.catalog.get(self.ids[0])
        self.catalog.store_result(row['id'], (row['mtime'],row['bytes']), {'vision': {'tags':['old']}})
        batch = self.queue.enqueue(self.ids, replace=True)
        job = self.queue.claim(batch)
        self.queue.fail(job['id'], 'offline', 2)
        self.assertIn('old', self.catalog.get(row['id'])['prediction'])
        self.assertEqual(self.queue.failed_ids(batch), [row['id']])
        self.assertIsNotNone(self.queue.claim(batch))
        self.assertEqual(self.queue.summary(batch)['errors'][0]['error'], 'offline')

    def test_source_change_rejected(self):
        batch = self.queue.enqueue([self.ids[0]])
        job = self.queue.claim(batch)
        Image.new('RGB', (80,80), 'blue').save(self.catalog.get(self.ids[0])['path'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.finish(job)
        self.assertIsNone(self.catalog.get(self.ids[0])['prediction'])
        self.queue.fail(job['id'], 'changed', 1)
        self.assertEqual(self.queue.summary(batch)['state'], 'complete')

    def test_progress_and_eta(self):
        batch = self.queue.enqueue(self.ids)
        self.assertEqual(self.queue.summary(batch)['eta'], -1)
        for _ in range(3):
            self.finish(self.queue.claim(batch))
        summary = self.queue.summary(batch)
        self.assertEqual((summary['finished'],summary['total'],summary['eta']), (3,4,10))
        self.finish(self.queue.claim(batch))
        self.assertEqual(self.queue.summary(batch)['state'], 'complete')
        self.assertIsNone(self.queue.enqueue(self.ids))
        self.assertEqual(self.queue.latest(), batch)


if __name__ == '__main__':
    unittest.main()
