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
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from image_lab_ui.viewer_measurements import ViewerMeasurements


@unittest.skipUnless(HAS_QT, 'Install the desktop extra for Qt tests')
class ViewerMeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'source.png'
        Image.new('RGB', (60, 40), 'red').save(self.path)
        stat = self.path.stat()
        self.row = {'id': 1, 'path': str(self.path), 'mtime': stat.st_mtime_ns, 'bytes': stat.st_size}
        self.helper = Path(__file__).parent / 'helpers/metadata_fault.py'

    def reader(self, mode=None, deadline_ms=5000):
        command = (sys.executable, str(self.helper), mode, 'measurements') if mode else None
        reader = ViewerMeasurements(worker_command=command, deadline_ms=deadline_ms)
        self.addCleanup(reader.shutdown)
        return reader

    def finish(self, reader):
        deadline = time.monotonic() + 7
        while reader.data['loading'] and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(reader.data['loading'])

    def test_real_worker_and_same_path_revision(self):
        reader = self.reader()
        reader.request(self.row)
        self.finish(reader)
        self.assertEqual(reader.data['error'], '')
        self.assertEqual(reader.data['palette'][0]['hex'], '#ff0000')
        generation = reader.generation
        Image.new('RGB', (60, 40), 'blue').save(self.path)
        stat = self.path.stat()
        reader.request(dict(self.row, mtime=stat.st_mtime_ns, bytes=stat.st_size))
        self.finish(reader)
        self.assertGreater(reader.generation, generation)
        self.assertEqual(reader.data['palette'][0]['hex'], '#0000ff')
        reader.complete(generation, {'groups': [{'title': 'stale'}]})
        self.assertEqual(reader.data['palette'][0]['hex'], '#0000ff')

    def test_stall_does_not_block_ui_and_navigation_cancels(self):
        reader = self.reader('hang')
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        self.addCleanup(timer.stop)
        reader.request(self.row)
        QTest.qWait(150)
        self.assertGreater(len(ticks), 5)
        reader.request(None)
        self.assertFalse(reader.data['loading'])
        self.assertEqual(reader.data['groups'], [])

    def test_timeout_is_visible(self):
        reader = self.reader('hang', deadline_ms=100)
        reader.request(self.row)
        self.finish(reader)
        self.assertEqual(reader.data['errorCode'], 'measurement_timeout')
        self.assertIn('Measurement', reader.data['error'])

    def test_stale_source_version_and_transport_failures_are_rejected(self):
        for mode in ('stale', 'wrong-key', 'wrong-source', 'revision', 'version', 'malformed', 'oversized'):
            with self.subTest(mode=mode):
                reader = self.reader(mode)
                reader.request(self.row)
                self.finish(reader)
                self.assertTrue(reader.data['error'])
                self.assertEqual(reader.data['groups'], [])
                reader.shutdown()


if __name__ == '__main__':
    unittest.main()
