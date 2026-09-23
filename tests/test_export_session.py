from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import Image

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication
from image_lab_ui.catalog import Catalog
from image_lab_ui.edit_session import EditorSession
from image_lab_ui.edit_protocol import EditWorkerError
import test_edit_session as session_helpers

ROOT=Path(__file__).resolve().parents[1]
OPTIONS={'format':'PNG','quality':90,'lossless':False,'matte':None}


class ExportSessionTests(unittest.TestCase):
    wait=session_helpers.EditorSessionTests.wait
    @classmethod
    def setUpClass(cls): cls.app=QGuiApplication.instance() or QGuiApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'results'); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.path=self.root/'source.png'; self.target=self.root/'copy.png'
        with Image.new('RGBA',(80,60),(120,80,40,128)) as image: image.save(self.path)
        self.before=self.path.read_bytes(),self.path.stat().st_mtime_ns
        self.catalog=Catalog(self.root/'catalog'); self.addCleanup(self.catalog.close)
        self.catalog.import_image(self.path)
        self.session=EditorSession(export_catalog=(str(self.catalog.directory),str(self.catalog.thumbnails)))
        self.addCleanup(self.cleanup)
        self.session.open_source(str(self.path),color_policy='srgb-v1',assume_srgb=True)
        self.wait(lambda:self.session.state=='ready')
        self.session.rotate(1); self.wait(lambda:self.session.state=='ready')
    def cleanup(self):
        if self.session.exporting:
            self.session.cancelExport(); self.wait(lambda:not self.session.exporting,timeout=15000)
        self.session.shutdown(discard=True,revision=self.session.revision)
        self.wait(lambda:self.session.state=='closed' and not self.session.busy)
        self.session.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def export(self, add=False):
        self.assertTrue(self.session.export_copy(str(self.target),OPTIONS,add_to_library=add))
        self.wait(lambda:not self.session.exporting,timeout=15000)
    def test_export_import_saved_revision_and_original_preservation(self):
        recipe=self.session.recipe; revision=self.session.revision
        self.export(True)
        self.assertTrue(self.session.lastExport['published']); self.assertTrue(self.session.lastExport['imported'])
        self.assertFalse(self.session.dirty)
        self.assertEqual(self.session.revision,revision); self.assertEqual(self.session.recipe,recipe)
        rows=self.catalog.rows(); self.assertEqual(len(rows),2)
        copy=next(row for row in rows if row['path']==str(self.target))
        self.assertIsNone(copy['prediction']); self.assertEqual(copy['user_edits'],'{}')
        with Image.open(self.target) as image: self.assertEqual(image.size,(60,80)); self.assertEqual(image.mode,'RGBA')
        self.assertEqual((self.path.read_bytes(),self.path.stat().st_mtime_ns),self.before)
        self.session.undo(); self.wait(lambda:self.session.state=='ready'); self.assertTrue(self.session.dirty)
        self.session.redo(); self.wait(lambda:self.session.state=='ready'); self.assertFalse(self.session.dirty)
    def test_collision_keeps_draft_and_preview(self):
        self.target.write_bytes(b'existing'); preview=self.session.preview.url
        self.export()
        self.assertTrue(self.session.dirty); self.assertTrue(self.session.error)
        self.assertEqual(self.session.preview.url,preview); self.assertEqual(self.target.read_bytes(),b'existing')
    def test_export_blocks_mutation_close_and_shutdown_until_cancelled(self):
        def stalled(*args,cancelled,**kwargs):
            while not cancelled(): time.sleep(.005)
            raise EditWorkerError('cancelled','Cancelled')
        with patch('image_lab_ui.export_job.encode_copy',side_effect=stalled):
            self.assertTrue(self.session.export_copy(str(self.target),OPTIONS))
            self.assertFalse(self.session.rotate()); self.assertFalse(self.session.refresh())
            self.assertFalse(self.session.cancelPreview()); self.assertFalse(self.session.compareOriginal(True))
            self.assertFalse(self.session.request_close(discard=True,revision=self.session.revision))
            self.assertFalse(self.session.shutdown(discard=True,revision=self.session.revision))
            self.assertTrue(self.session.cancelExport()); self.wait(lambda:not self.session.exporting)
        self.assertTrue(self.session.dirty); self.assertFalse(self.target.exists())
    def test_import_failure_is_partial_success_and_retry(self):
        with patch.object(Catalog,'import_image',side_effect=ValueError('injected import failure')):
            self.export(True)
        self.assertTrue(self.target.exists()); self.assertFalse(self.session.dirty)
        self.assertTrue(self.session.lastExport['import_error']); self.assertFalse(self.session.lastExport['imported'])
        self.assertTrue(self.session.retryImport()); self.wait(lambda:not self.session.exporting,timeout=15000)
        self.assertTrue(self.session.lastExport['imported']); self.assertEqual(len(self.catalog.rows()),2)
    def test_retry_import_refuses_changed_published_copy(self):
        self.export()
        self.target.write_bytes(b'changed externally')
        self.assertTrue(self.session.retryImport()); self.wait(lambda:not self.session.exporting)
        self.assertFalse(self.session.lastExport['imported']); self.assertTrue(self.session.lastExport['import_error'])
        self.assertEqual(self.target.read_bytes(),b'changed externally')
    def test_missing_catalog_destination_stays_reserved(self):
        with Image.new('RGB',(8,8),'red') as image: image.save(self.target)
        self.catalog.import_image(self.target); self.target.unlink()
        self.export()
        self.assertFalse(self.target.exists()); self.assertTrue(self.session.dirty)
        self.assertIn('reserved',self.session.error)
        self.target=self.root/'COPY.png'
        self.export()
        self.assertFalse(self.target.exists()); self.assertIn('reserved',self.session.error)

    def test_catalog_writer_is_locked_through_publication(self):
        import sqlite3
        from image_lab_ui import export_publication
        real=export_publication._link_fd; checked=[]
        def link(*args):
            with sqlite3.connect(self.catalog.directory/'catalog.sqlite3',timeout=.01) as other:
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    other.execute('UPDATE images SET error=error')
                self.assertIn('locked',str(caught.exception)); checked.append(True)
            real(*args)
        with patch.object(export_publication,'_link_fd',side_effect=link): self.export()
        self.assertEqual(checked,[True]); self.assertTrue(self.session.lastExport['published'])

    def test_late_cancellation_cannot_hide_success(self):
        from image_lab_ui import export_publication
        real=export_publication._link_fd
        def link(*args):
            real(*args); self.session._runner.job.cancelled.set()
        with patch.object(export_publication,'_link_fd',side_effect=link): self.export()
        self.assertTrue(self.session.lastExport['published']); self.assertFalse(self.session.dirty)
        self.assertTrue(self.target.exists())


if __name__=='__main__': unittest.main()
