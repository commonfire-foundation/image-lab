import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND','software')
    from PySide6.QtGui import QGuiApplication
    from image_lab_ui.analyzer_client import analyzer_identity, run_analyzer, AnalyzerProcessError

ROOT = Path(__file__).resolve().parents[1]
FAKE = (sys.executable, str(ROOT / 'tests/helpers/fake_analyzer.py'))


@unittest.skipUnless(HAS_QT, 'Qt process adapter requires desktop extra')
class ProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'image with spaces.png'
        Image.new('RGB',(120,60),'red').save(self.path)
        self.identity = analyzer_identity(FAKE)

    def test_success_and_progress(self):
        phases=[]
        result=run_analyzer(self.path, self.identity, lambda stage,label:phases.append((stage, label)), command=FAKE)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(phases, [(0, 'Preparing image'), (1, 'Checking local model'),
                                  (2, 'Generating image description')])

    def test_process_and_protocol_failures(self):
        for mode in ('crash','garbage','incompatible','truncated','flood','wrong-path','duplicate','nonzero','offline'):
            with self.subTest(mode=mode), self.assertRaises(AnalyzerProcessError):
                run_analyzer(self.path,self.identity,lambda *args:None,command=(*FAKE,'--mode',mode))
        with self.assertRaisesRegex(AnalyzerProcessError,'Cannot start'):
            run_analyzer(self.path,self.identity,lambda *args:None,command=('/not/an/executable',))

    def test_hung_process_deadline_and_interruption(self):
        with self.assertRaisesRegex(AnalyzerProcessError,'timed out'):
            run_analyzer(self.path,self.identity,lambda *args:None,command=(*FAKE,'--mode','hang'),timeout=0.01)
        with self.assertRaisesRegex(AnalyzerProcessError,'interrupted'):
            run_analyzer(self.path,self.identity,lambda *args:None,command=(*FAKE,'--mode','hang'),interrupted=lambda:True)
