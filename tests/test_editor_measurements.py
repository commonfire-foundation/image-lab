from copy import deepcopy
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication
from image_lab_ui.edit_session import EditorSession
from image_lab_ui.edit_protocol import EditWorkerError
from image_lab_ui.editor_measurements import measure_source
import test_edit_session as session_helpers

ROOT=Path(__file__).resolve().parents[1]


class EditorMeasurementTests(unittest.TestCase):
    wait=session_helpers.EditorSessionTests.wait
    @classmethod
    def setUpClass(cls): cls.app=QGuiApplication.instance() or QGuiApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'results'); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'source.png'
        info=PngImagePlugin.PngInfo(); info.add(b'sRGB',b'\0')
        with Image.new('RGBA',(32,20),(120,80,40,128)) as image: image.save(self.path,pnginfo=info)
        self.before=self.path.read_bytes(),self.path.stat().st_mtime_ns
        self.session=EditorSession(); self.addCleanup(self.cleanup)
        self.session.open_source(str(self.path),color_policy='srgb-v1')
        self.wait(lambda:self.session.state=='ready')
    def cleanup(self):
        self.session.shutdown(discard=True,revision=self.session.revision)
        self.wait(lambda:self.session.state=='closed' and not self.session.busy)
        self.session.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def measure(self):
        self.assertTrue(self.session.requestMeasurements())
        self.wait(lambda:not self.session.measurements['loading'],timeout=12000)
        self.assertFalse(self.session.measurements['error'],self.session.measurements)
        return self.session.measurements['result']
    def test_original_and_edited_views_are_revision_bound_and_truthfully_scoped(self):
        self.measure()
        self.assertTrue(self.session.measurements['colorAgreement'])
        self.assertTrue(self.session.measurements['sourcePolicyAligned'])
        self.session.rotate(1)
        self.assertIsNone(self.session.measurements['result'])
        self.wait(lambda:self.session.state=='ready' and not self.session.measurements['loading'],timeout=12000)
        view=self.session.measurements
        self.assertEqual(view['revision'],self.session.revision)
        self.assertEqual(view['result']['input']['width'],32)
        self.assertFalse(view['colorAgreement']); self.assertIn('NOT edited-image',view['notice'])
        self.session.compareOriginal(True)
        self.wait(lambda:self.session.state=='ready' and not self.session.measurements['loading'],timeout=12000)
        self.assertTrue(self.session.measurements['colorAgreement'])
        self.assertEqual((self.path.read_bytes(),self.path.stat().st_mtime_ns),self.before)
    def test_stale_measurement_is_rejected_and_latest_preview_runs_first(self):
        result=self.measure(); started=Event(); release=Event(); calls=[]
        def delayed(*args,**kwargs):
            calls.append(args)
            if len(calls)==1:
                started.set()
                while not release.is_set(): time.sleep(.005)
            return deepcopy(result)
        with patch('image_lab_ui.editor_measurements.measure_source',side_effect=delayed):
            try:
                self.session.requestMeasurements(); self.wait(started.is_set)
                future=self.session._runner.future
                self.session.rotate(1); self.session.flip(True,False); self.session.resizeWidth(10)
                self.assertIs(self.session._runner.future,future)
                self.assertEqual(self.session._pending.kind,'render')
                self.assertEqual(self.session._pending.generation,self.session.revision)
                self.assertIsNone(self.session.measurements['result'])
            finally: release.set()
            self.wait(lambda:self.session.state=='ready' and not self.session.measurements['loading'],timeout=12000)
        self.assertEqual(len(calls),2)
        self.assertEqual(self.session.measurements['revision'],self.session.revision)
    def test_bad_digest_is_an_inspection_error_not_an_editor_failure(self):
        result=deepcopy(self.measure()); result['input']['sha256']='0'*64
        with patch('image_lab_ui.editor_measurements.measure_source',return_value=result):
            self.session.requestMeasurements(); self.wait(lambda:not self.session.measurements['loading'])
        self.assertTrue(self.session.measurements['error'])
        self.assertIsNone(self.session.measurements['result']); self.assertEqual(self.session.state,'ready')
        self.assertTrue(self.session.preview.url)
    def test_measurement_cancellation_source_change_and_policy_change(self):
        with self.assertRaises(EditWorkerError) as caught:
            measure_source(self.session._source,'srgb-v1',False,cancelled=lambda:True)
        self.assertEqual(caught.exception.code,'cancelled')
        self.measure()
        self.session.set_color_policy('legacy-v1')
        self.assertIsNone(self.session.measurements['result'])
        self.wait(lambda:self.session.state=='ready')
        self.assertFalse(self.session.requestMeasurements())
        self.session.set_color_policy('srgb-v1')
        self.wait(lambda:self.session.state=='ready' and not self.session.measurements['loading'],timeout=12000)
        self.path.write_bytes(self.before[0]+b'changed')
        self.session.requestMeasurements(); self.wait(lambda:not self.session.measurements['loading'])
        self.assertEqual(self.session.measurements['errorCode'],'source_changed')
        self.assertIsNone(self.session.measurements['result'])
    def test_close_cancels_inspection_without_callback_into_closed_session(self):
        started=Event()
        def delayed(*args,cancelled,**kwargs):
            started.set()
            while not cancelled(): time.sleep(.005)
            raise EditWorkerError('cancelled','cancelled')
        with patch('image_lab_ui.editor_measurements.measure_source',side_effect=delayed):
            self.session.requestMeasurements(); self.wait(started.is_set)
            self.assertTrue(self.session.request_close())
            self.assertTrue(self.session.blocksExternalWork)
            self.wait(lambda:self.session.state=='closed')
        self.assertIsNone(self.session.measurements['result'])
        self.assertFalse(self.session.blocksExternalWork)


if __name__=='__main__': unittest.main()
