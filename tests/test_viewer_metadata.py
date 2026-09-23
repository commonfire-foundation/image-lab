import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from PIL import Image

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtTest import QTest
    from image_lab_ui.viewer_metadata import ViewerMetadata


@unittest.skipUnless(HAS_QT, 'Install the desktop extra for Qt tests')
class ViewerMetadataProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Full discovery also creates QGuiApplication: never precede it with QCoreApplication.
        from PySide6.QtGui import QGuiApplication
        cls.app = QCoreApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'source.png'
        Image.new('RGB', (20, 10)).save(self.path)
        stamp = self.path.stat()
        self.row = {'id': 1, 'path': str(self.path), 'mtime': stamp.st_mtime_ns, 'bytes': stamp.st_size}
        self.helper = Path(__file__).parent / 'helpers/metadata_fault.py'

    def reader(self, mode=None, timeout=3000):
        command = (sys.executable, str(self.helper), mode) if mode else None
        reader = ViewerMetadata(worker_command=command, deadline_ms=timeout)
        self.addCleanup(reader.shutdown)
        return reader

    def finish(self, reader):
        deadline = time.monotonic() + 5
        while reader.data['loading'] and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(reader.data['loading'])
        for _ in range(50):
            if not reader._jobs:
                break
            QTest.qWait(10)
        self.assertFalse(reader._jobs)

    def test_real_api_process_returns_source_and_revision(self):
        reader = self.reader()
        reader.request(self.row)
        self.assertTrue(reader.data['loading'])
        self.finish(reader)
        self.assertEqual(reader.data['error'], '')
        self.assertEqual(reader.data['sourceKey'], list(self.row.values()))
        self.assertEqual(reader.data['source']['path'], str(self.path))
        self.assertEqual(reader.data['metadata']['stored_size'], {'width': 20, 'height': 10})
        generation = reader.generation
        reader.request(dict(self.row, mtime=0))
        self.finish(reader)
        self.assertGreater(reader.data['loadRevision'], generation)
        self.assertTrue(any(item['code'] == 'catalog_source_changed' for item in reader.data['warnings']))

    def test_deadline_kills_blocked_outer_read_and_clears_loading(self):
        reader = self.reader('hang', timeout=150)
        started = time.monotonic()
        reader.request(self.row)
        self.finish(reader)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(reader.data['errorCode'], 'metadata_timeout')

    def test_malformed_stale_excess_and_failed_worker_results(self):
        for mode in ('malformed', 'stale', 'wrong-key', 'wrong-source', 'version', 'duplicate', 'crash', 'oversized', 'stderr'):
            with self.subTest(mode=mode):
                reader = self.reader(mode)
                reader.request(self.row)
                self.finish(reader)
                self.assertEqual(reader.data['groups'], [])
                self.assertEqual(reader.data['errorCode'], 'metadata_output_limit' if mode in ('oversized', 'stderr') else 'metadata_process_result')

    def test_failed_start_is_visible_and_does_not_leave_jobs(self):
        reader = self.reader()
        reader._command = (str(self.path.parent / 'no-executable'),)
        reader.request(self.row)
        self.finish(reader)
        self.assertEqual(reader.data['errorCode'], 'metadata_process_unavailable')

    def test_close_cancels_active_inspection_and_drops_delayed_completion(self):
        reader = self.reader('hang')
        reader.request(self.row)
        QTest.qWait(50)
        generation = reader.generation
        reader.request(None)
        reader.complete(generation, {'error': 'stale', 'groups': []})
        self.finish(reader)
        self.assertEqual(reader.data['groups'], [])
        self.assertEqual(reader.data['error'], '')


if __name__ == '__main__':
    unittest.main()
