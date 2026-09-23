import os
import importlib.util
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    from PySide6.QtCore import QObject, QEvent, QEventLoop, QMetaObject, QPointF, QTimer, QUrl, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from image_lab_ui.edit_recipe import EditRecipe
    from image_lab_ui.app import Controller
    from image_lab_ui.ipc_actions import ControlRouter
    from image_lab_ui.ipc_protocol import ControlError

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=8000):
    if predicate():
        return
    loop = QEventLoop()
    timer = QTimer(); timer.setInterval(10)
    deadline = QTimer(); deadline.setSingleShot(True)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit)
    timer.start(); deadline.start(timeout)
    loop.exec()
    timer.stop(); deadline.stop()
    timer.timeout.disconnect(); deadline.timeout.disconnect()
    assert predicate(), 'Timed out waiting for editor state'


@unittest.skipUnless(HAS_QT, 'Install the desktop extra for live editor tests')
class LiveEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle('Basic')
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name)
        self.c = Controller(self.root / 'catalog', theme_paths=[self.root / 'no-theme'])
        self.path = self.root / 'original.png'
        info = PngImagePlugin.PngInfo(); info.add(b'sRGB', b'\0')
        with Image.new('RGB', (120, 80), '#507c82') as image:
            image.save(self.path, pnginfo=info)
        self.c.catalog.import_image(self.path)
        self.image_id = self.c.catalog.rows()[0]['id']
        self.c.search(''); self.c.select(self.image_id)
        self.original = self.path.read_bytes()
        self.engine = None
        self.router = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.c.editor.exporting:
            self.c.editor.cancelExport()
            wait_for(lambda: not self.c.editor.exporting)
        self.c.editor.shutdown(discard=True, revision=self.c.editor.revision)
        wait_for(lambda: self.c.editor.state == 'closed')
        if self.router:
            self.router.timer.stop()
        if self.engine:
            for window in self.engine.rootObjects():
                window.close()
            self.engine.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.c.viewerMetadata.shutdown(); self.c.viewerMeasurements.shutdown()
        self.c.omarchy_palette.timer.stop()
        self.c.catalog.close()
        self.c.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def open(self):
        self.assertTrue(self.c.openEditor(self.image_id))
        wait_for(lambda: self.c.editor.state in ('ready', 'error'))
        self.assertEqual(self.c.editor.state, 'ready', self.c.editor.error)

    def load_ui(self, width=900, height=600):
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(e.toString() for e in errors))
        self.engine.addImageProvider('editor-preview', self.c.editor.preview.provider)
        self.engine.rootContext().setContextProperty('controller', self.c)
        self.engine.rootContext().setContextProperty('gallery', self.c.model)
        self.engine.load(QUrl.fromLocalFile(str(ROOT / 'image_lab_ui/Main.qml')))
        self.assertTrue(self.engine.rootObjects(), self.warnings)
        self.window = self.engine.rootObjects()[0]
        self.window.setWidth(width); self.window.setHeight(height)
        return self.window

    def obj(self, name):
        found = self.window.findChild(QObject, name)
        self.assertIsNotNone(found, name)
        return found

    def invoke(self, name, method='clicked'):
        self.assertTrue(QMetaObject.invokeMethod(self.obj(name), method))

    def drag(self, start, end):
        QTest.mousePress(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(self.window, end, 20)
        QTest.mouseRelease(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)

    def bounds(self):
        value = self.obj('cropOverlay').property('bounds')
        return value.toVariant() if hasattr(value, 'toVariant') else value

    def point(self, x, y):
        overlay = self.obj('cropOverlay')
        return overlay.mapToScene(QPointF(x * overlay.width(), y * overlay.height())).toPoint()

    def test_crop_presets_dimensions_and_export_guidance(self):
        self.load_ui(); self.open()
        wait_for(lambda: self.obj('geometryEditor').property('previewReady'))
        for index, ratio in enumerate(((3, 2), (1, 1), (4, 3), (3, 2), (16, 9), (9, 16), (21, 9))):
            self.c.editor.reset()
            wait_for(lambda: self.c.editor.state == 'ready')
            self.obj('geometryCropPreset').setProperty('currentIndex', index)
            self.invoke('applyGeometryPreset')
            wait_for(lambda: self.c.editor.state == 'ready')
            width, height = EditRecipe.from_dict(self.c.editor.recipe).result_size.as_list()
            self.assertEqual(width * ratio[1], height * ratio[0])
            self.assertEqual(self.obj('editorOutputDimensions').property('text'), f'Output: {width} × {height} px')
        self.obj('cropLeft').setProperty('text', '1')
        self.invoke('cropLeft', 'textEdited')
        self.assertIn('Apply or revert', self.obj('editorExportHint').property('text'))
        self.assertFalse(self.obj('openExportCopy').property('enabled'))
        self.invoke('revertGeometryFields')
        wait_for(lambda: self.c.editor.state == 'ready')
        self.c.editor.compareOriginal(True)
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertIn('Turn off original comparison', self.obj('editorExportHint').property('text'))
        self.assertFalse(self.obj('openExportCopy').property('enabled'))
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.warnings, self.warnings)

    def test_export_dialog_shows_specific_validation_error_and_keeps_draft(self):
        self.load_ui(); self.open()
        wait_for(lambda: self.obj('geometryEditor').property('previewReady'))
        self.invoke('openExportCopy')
        self.obj('exportFolder').setProperty('text', 'relative-folder')
        self.obj('exportFilename').setProperty('text', 'chosen-name.png')
        self.invoke('confirmExportCopy')
        self.assertTrue(self.obj('exportGeometryDialog').property('visible'))
        self.assertEqual(self.obj('exportValidationError').property('text'), 'Choose an absolute destination folder.')
        self.assertEqual(self.obj('exportFilename').property('text'), 'chosen-name.png')
        self.assertFalse(self.c.editor.exporting)
        self.assertFalse(self.c.exportEditorCopy(str(self.root), 'copy.png', 'PNG', 90, False, '', False, self.c.editor.revision - 1))
        self.assertIn('Reopen Export copy', self.c.status)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.warnings, self.warnings)

    def test_drag_draw_resize_move_and_single_undo_across_transforms(self):
        self.load_ui(); self.open()
        for turns, horizontal, vertical in ((0,False,False), (1,True,False), (2,False,True), (3,True,True)):
            self.c.editor.reset()
            self.c.editor.crop(10, 10, 110, 70)
            self.c.editor.rotate(turns)
            self.c.editor.flip(horizontal, vertical)
            self.c.editor.resizeWidth(30)
            wait_for(lambda: self.c.editor.state == 'ready' and self.obj('geometryEditor').property('previewReady'))
            before = EditRecipe.from_dict(self.c.editor.recipe)
            self.invoke('beginDragCrop')
            self.drag(self.point(.25,.25), self.point(.75,.75))
            self.assertTrue(self.obj('cropOverlay').property('changedSelection'))
            b = self.bounds()
            self.drag(self.point(b[0],b[1]), self.point(b[0]+.05,b[1]+.05))
            resized = self.bounds()
            self.assertGreater(resized[0], b[0]); self.assertGreater(resized[1], b[1])
            cx, cy = (resized[0]+resized[2])/2, (resized[1]+resized[3])/2
            self.drag(self.point(cx,cy), self.point(cx+.05,cy+.05))
            moved = self.bounds()
            self.assertGreater(moved[0], resized[0])
            self.assertAlmostEqual(moved[2]-moved[0], resized[2]-resized[0])
            self.assertEqual(self.c.editor.recipe, before.to_dict())
            expected = before.with_display_crop(*moved)
            self.invoke('applyDragCrop')
            wait_for(lambda: self.c.editor.state == 'ready')
            self.assertEqual(self.c.editor.recipe, expected.to_dict())
            self.assertTrue(self.c.editor.undo())
            wait_for(lambda: self.c.editor.state == 'ready')
            self.assertEqual(self.c.editor.recipe, before.to_dict())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.warnings, self.warnings)

    def test_drag_cancel_letterbox_stale_frame_and_comparison_guards(self):
        self.load_ui(); self.open()
        wait_for(lambda: self.obj('geometryEditor').property('previewReady'))
        before = self.c.editor.recipe
        self.invoke('beginDragCrop')
        overlay = self.obj('cropOverlay')
        top = overlay.mapToScene(QPointF(overlay.width()/2, 0)).toPoint()
        outside = top - type(top)(0, 10)
        self.drag(outside, top - type(top)(0, 4))
        self.assertFalse(overlay.property('changedSelection'))
        self.drag(self.point(.2,.2), self.point(1.2,1.2))
        self.assertEqual(self.bounds()[2:], [1, 1])
        self.invoke('cancelDragCrop'); self.invoke('beginDragCrop')
        self.drag(self.point(.2,.2), self.point(.8,.8))
        start_left = self.bounds()[0]
        QTest.keyClick(self.window, Qt.Key.Key_Right)
        self.assertAlmostEqual(self.bounds()[0] - start_left, 1 / overlay.property('pixelWidth'))
        QTest.keyClick(self.window, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        self.assertAlmostEqual(self.bounds()[0] - start_left, 11 / overlay.property('pixelWidth'))
        self.assertTrue(overlay.property('changedSelection'))
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        self.assertFalse(self.obj('geometryEditor').property('dragMode'))
        self.assertTrue(self.c.editorActive)
        self.assertEqual(self.c.editor.recipe, before)
        self.invoke('beginDragCrop')
        self.drag(self.point(.2,.2), self.point(.8,.8))
        token = self.c.editor.revision
        self.c.editor.refresh()
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertFalse(self.c.editor.cropView(.2,.2,.8,.8,token))
        self.assertEqual(self.c.editor.recipe, before)
        self.invoke('cancelDragCrop')
        self.c.editor.compareOriginal(True)
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertFalse(self.c.editor.cropView(.2,.2,.8,.8,self.c.editor.revision))
        self.assertFalse(self.obj('beginDragCrop').property('enabled'))
        self.assertFalse(self.warnings, self.warnings)

    def test_exif_oriented_drag_draft_survives_close_and_resize_cancel(self):
        info = PngImagePlugin.PngInfo(); info.add(b'sRGB', b'\0')
        exif = Image.Exif(); exif[274] = 6
        with Image.new('RGB', (120, 80), 'teal') as image:
            image.save(self.path, pnginfo=info, exif=exif)
        original = self.path.read_bytes()
        self.load_ui(1280, 820); self.open()
        wait_for(lambda: self.obj('geometryEditor').property('previewReady'))
        self.assertEqual(self.c.editor.recipe['source_size'], [80, 120])
        before = self.c.editor.recipe
        self.invoke('beginDragCrop')
        self.drag(self.point(.2,.2), self.point(.8,.8))
        seed = self.bounds()
        self.invoke('closeGeometryEditor')
        self.assertTrue(self.obj('discardGeometryDialog').property('visible'))
        self.invoke('keepGeometry')
        self.assertEqual(self.bounds(), seed)
        overlay = self.obj('cropOverlay')
        start = self.point(seed[0],seed[1]); end = self.point(.3,.3)
        QTest.mousePress(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(self.window, end, 20)
        old_width = overlay.width()
        self.window.setWidth(900); self.window.setHeight(600)
        wait_for(lambda: overlay.width() != old_width)
        QTest.mouseRelease(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        self.assertFalse(overlay.property('dragging'))
        self.assertEqual(self.bounds(), seed)
        self.assertEqual(self.c.editor.recipe, before)
        self.invoke('applyDragCrop')
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertEqual(self.c.editor.recipe, EditRecipe.from_dict(before).with_display_crop(*seed).to_dict())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.warnings, self.warnings)

    def test_drag_extreme_aspects_use_actual_painted_bounds(self):
        self.load_ui()
        for size in ((4000, 40), (40, 4000)):
            info = PngImagePlugin.PngInfo(); info.add(b'sRGB', b'\0')
            with Image.new('RGB', size, 'teal') as image:
                image.save(self.path, pnginfo=info)
            original = self.path.read_bytes()
            self.open()
            wait_for(lambda: self.obj('geometryEditor').property('previewReady'))
            before = EditRecipe.from_dict(self.c.editor.recipe)
            self.invoke('beginDragCrop')
            self.drag(self.point(.25,.25), self.point(.75,.75))
            bounds = self.bounds()
            self.assertTrue(self.obj('cropOverlay').property('changedSelection'))
            self.invoke('applyDragCrop')
            wait_for(lambda: self.c.editor.state == 'ready')
            self.assertEqual(self.c.editor.recipe, before.with_display_crop(*bounds).to_dict())
            self.assertEqual(self.path.read_bytes(), original)
            self.assertTrue(self.c.closeEditor(True, self.c.editor.revision))
            wait_for(lambda: not self.c.editorActive)
        self.assertFalse(self.warnings, self.warnings)

    def test_live_export_formats_import_and_selection_preservation(self):
        self.c.search('original'); self.c.select(self.image_id)
        query, selected = self.c.model.query, self.c.selected['imageId']
        self.load_ui(); self.open()
        self.c.editor.rotate(1)
        wait_for(lambda: self.c.editor.state == 'ready' and self.obj('geometryEditor').property('previewReady'))
        for index, suffix in enumerate(('png','jpg','webp')):
            self.invoke('openExportCopy')
            dialog = self.obj('exportGeometryDialog')
            self.assertTrue(dialog.property('visible'))
            self.assertLessEqual(dialog.property('height'), self.window.height())
            self.obj('exportFolder').setProperty('text', str(self.path.parent))
            self.obj('exportFilename').setProperty('text', 'original-copy.'+suffix)
            self.obj('exportFormat').setProperty('currentIndex', index)
            self.obj('exportImport').setProperty('checked', True)
            self.invoke('confirmExportCopy')
            wait_for(lambda: not self.c.editor.exporting)
            self.assertTrue(self.c.editor.lastExport.get('imported'), self.c.editor.lastExport)
            self.assertFalse(self.c.editor.dirty)
            self.assertEqual(self.c.model.query,query)
            self.assertEqual(self.c.selected['imageId'], selected)
            with Image.open(self.path.parent/('original-copy.'+suffix)) as image: self.assertEqual(image.size,(80,120))
        self.assertEqual(self.c.catalog.count(),4)
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse(self.warnings,self.warnings)

    def test_live_measurements_stay_original_scoped_and_escape_closes_only_panel(self):
        self.load_ui(); self.open()
        wait_for(lambda:self.obj('geometryEditor').property('previewReady'))
        self.invoke('openEditorMeasurements')
        wait_for(lambda:not self.c.editor.measurements['loading'])
        self.assertTrue(self.obj('editorMeasurementsDialog').property('visible'))
        self.assertFalse(self.c.editor.measurements['error'])
        self.assertTrue(self.c.editor.measurements['colorAgreement'])
        self.assertIn('NOT edited-image',self.obj('editorMeasurementsGate').property('text'))
        QTest.keyClick(self.window,Qt.Key.Key_Escape)
        self.assertFalse(self.obj('editorMeasurementsDialog').property('visible'))
        self.assertTrue(self.c.editorActive)
        self.c.editor.rotate(1)
        wait_for(lambda:self.c.editor.state=='ready' and not self.c.editor.measurements['loading'])
        self.assertFalse(self.c.editor.measurements['colorAgreement'])
        self.assertEqual(self.c.editor.measurements['revision'],self.c.editor.revision)
        self.assertFalse(self.warnings,self.warnings)

    def test_jpeg_dialog_requires_explicit_valid_alpha_matte(self):
        info=PngImagePlugin.PngInfo(); info.add(b'sRGB',bytes([0]))
        with Image.new('RGBA',(80,40),(120,80,40,128)) as image: image.save(self.path,pnginfo=info)
        self.c.catalog.import_image(self.path)
        self.load_ui(); self.open()
        wait_for(lambda:self.obj('geometryEditor').property('previewReady'))
        self.invoke('openExportCopy')
        self.obj('exportFormat').setProperty('currentIndex',1)
        self.obj('exportFilename').setProperty('text','alpha.jpg')
        self.assertFalse(self.obj('confirmExportCopy').property('enabled'))
        self.obj('exportMatteConsent').setProperty('checked',True)
        self.obj('exportMatte').setProperty('text','#bad')
        self.assertFalse(self.obj('confirmExportCopy').property('enabled'))
        self.obj('exportMatte').setProperty('text','#ffffff')
        self.assertTrue(self.obj('confirmExportCopy').property('enabled'))
        self.invoke('confirmExportCopy'); wait_for(lambda:not self.c.editor.exporting)
        self.assertTrue(self.c.editor.lastExport.get('published'),self.c.editor.error)
        with Image.open(self.path.parent/'alpha.jpg') as image:
            self.assertEqual(image.mode,'RGB'); self.assertIn('icc_profile',image.info)
            for actual,expected in zip(image.getpixel((0,0)),(187,167,147)): self.assertLessEqual(abs(actual-expected),3)
        self.assertFalse(self.warnings,self.warnings)

    def test_editor_shortcuts_do_not_steal_text_undo(self):
        self.load_ui(); self.open()
        self.c.editor.rotate(1)
        wait_for(lambda: self.c.editor.state=='ready' and self.obj('geometryEditor').property('previewReady'))
        before=self.c.editor.recipe
        field=self.obj('cropLeft'); field.forceActiveFocus()
        QMetaObject.invokeMethod(field,'selectAll')
        QTest.keyClick(self.window,Qt.Key.Key_5)
        QTest.keyClick(self.window,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.c.editor.recipe,before)
        self.invoke('revertGeometryFields')
        wait_for(lambda:self.c.editor.state=='ready')
        self.obj('geometryPreview').forceActiveFocus()
        QTest.keyClick(self.window,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
        wait_for(lambda:self.c.editor.state=='ready')
        self.assertEqual(self.c.editor.recipe['quarter_turns'],0)
        QTest.keyClick(self.window,Qt.Key.Key_Y,Qt.KeyboardModifier.ControlModifier)
        wait_for(lambda:self.c.editor.state=='ready' and self.obj('geometryEditor').property('previewReady'))
        self.assertEqual(self.c.editor.recipe['quarter_turns'],1)
        QTest.keyClick(self.window,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(self.obj('exportGeometryDialog').property('visible'))
        QTest.keyClick(self.window,Qt.Key.Key_Escape)
        self.assertFalse(self.obj('exportGeometryDialog').property('visible'))
        self.assertTrue(self.c.editorActive)
        self.assertFalse(self.warnings,self.warnings)

    def test_controller_guards_context_until_close(self):
        self.open()
        self.assertFalse(self.c.canQueue)
        self.assertFalse(self.c.canImport)
        self.assertFalse(self.c.canClose)
        self.assertFalse(self.c.canRename)
        self.assertEqual(self.c.editorRecord['imageId'], self.image_id)
        self.c.select(-1); self.c.search('missing'); self.c.setLibraryFilter('analyzed')
        self.assertEqual(self.c.selected['imageId'], self.image_id)
        self.assertEqual(self.c.viewQuery, '')
        self.assertEqual(self.c.libraryFilter, 'all')
        self.assertFalse(self.c.removeImages([self.image_id])['ok'])
        self.assertFalse(self.c.renameById(self.image_id, str(self.path), 'changed.png')['ok'])
        self.assertFalse(self.c.updateImageDetails(self.image_id, '', {})['ok'])
        self.assertFalse(self.c.saveSettings(self.c.settings)['ok'])
        with patch.object(self.c.queue, 'claim') as claim, patch.object(self.c.queue, 'resume') as resume:
            self.c.runNext(); self.c.resumeBatch(); self.c.enqueue([self.image_id]); self.c.start('scan', str(self.root))
            claim.assert_not_called(); resume.assert_not_called()
        self.assertFalse(self.c.busy)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(self.c.closeEditor(False, self.c.editor.revision))
        wait_for(lambda: not self.c.editorActive)
        self.assertTrue(self.c.canImport)
        self.assertTrue(self.c.canClose)

    def test_closing_keeps_guards_until_stalled_child_is_reaped(self):
        self.open()
        processes = []
        real = subprocess.Popen
        def launch(command, **kwargs):
            process = real([sys.executable, str(ROOT / 'tests/helpers/edit_worker_fault.py'), 'hang'], **kwargs)
            processes.append(process)
            return process
        with patch('image_lab_ui.edit_process.subprocess.Popen', side_effect=launch):
            self.c.editor.rotate()
            wait_for(lambda: bool(processes))
            self.assertTrue(self.c.closeEditor(True, self.c.editor.revision))
            self.assertEqual(self.c.editor.state, 'closing')
            self.assertFalse(self.c.canImport)
            self.assertFalse(self.c.canQueue)
            self.assertFalse(self.c.canClose)
            self.assertFalse(self.c.openEditor(self.image_id))
            wait_for(lambda: not self.c.editorActive)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(self.c.canClose)

    def test_entry_blocked_during_work_and_paused_queued_items(self):
        for key in ('_busy', '_submitting'):
            setattr(self.c, key, True)
            self.assertFalse(self.c.openEditor(self.image_id))
            setattr(self.c, key, False)
        self.load_ui()
        self.c.uiAction.emit('viewer.open', self.image_id)
        self.c._batch = dict(self.c._batch, queued=9186, state='paused')
        self.c.changed.emit()
        self.assertFalse(self.c.openEditor(self.image_id))
        self.assertEqual(self.c.editor.state, 'closed')
        reason = self.obj('viewerEditorBlockedReason')
        self.assertTrue(reason.property('visible'))
        self.assertIn('9,186 queued images', reason.property('text'))
        self.assertIn('pausing does not release it', reason.property('text'))
        self.assertFalse(self.obj('openGeometryEditor').property('enabled'))
        self.assertEqual(self.c._batch['queued'], 9186)
        self.c._batch = dict(self.c._batch, queued=0, state='idle')
        self.c.changed.emit()
        self.assertFalse(reason.property('visible'))
        self.assertTrue(self.obj('openGeometryEditor').property('enabled'))
        self.assertFalse(self.warnings, self.warnings)

    def test_ipc_read_only_access_remains_but_mutation_and_navigation_are_busy(self):
        self.router = ControlRouter(self.c)
        self.open(); self.c.editor.rotate()
        for method, params in (
            ('viewer.close', {}), ('viewer.open', {'image_id': self.image_id}),
            ('window.hide', {}), ('window.close', {}), ('queue.resume', {}),
            ('selection.clear', {}), ('view.search', {'query': 'elsewhere'}),
            ('analyze', {'ids': [self.image_id]}),
        ):
            with self.subTest(method=method), self.assertRaises(ControlError) as caught:
                self.router.dispatch(method, params)
            self.assertEqual(caught.exception.code, 'busy')
        status = self.router.dispatch('app.status', {})
        self.assertTrue(status['editor']['dirty'])
        self.assertEqual(status['editor']['image_id'], self.image_id)
        self.assertEqual(self.router.dispatch('library.list', {})['total'], 1)

    def test_live_qml_crop_preview_and_revision_bound_discard(self):
        self.load_ui()
        self.c.uiAction.emit('viewer.open', self.image_id)
        self.invoke('openGeometryEditor')
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertTrue(self.obj('geometryEditor').property('visible'))
        for name in ('cropLeft', 'cropRight', 'geometryWidth', 'geometryHeight'):
            field = self.obj(name)
            grid = field.parentItem()
            self.assertLessEqual(grid.width(), grid.parentItem().width())
            self.assertLessEqual(field.x() + field.width(), grid.width())
        wait_for(lambda: self.obj('geometryEditor').property('previewReady'))
        self.obj('cropLeft').setProperty('text', '10')
        self.invoke('cropLeft', 'textEdited')
        self.invoke('applyGeometryCrop')
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertEqual(self.c.editor.recipe['crop'], [10, 0, 120, 80])
        self.invoke('closeGeometryEditor')
        self.assertTrue(self.obj('discardGeometryDialog').property('visible'))
        self.c.editor.rotate()  # Simulate a newer local command after prompt creation.
        self.invoke('discardGeometry')
        self.assertTrue(self.c.editorActive)
        self.assertTrue(self.obj('discardGeometryDialog').property('stale'))
        self.invoke('keepGeometry'); self.invoke('closeGeometryEditor'); self.invoke('discardGeometry')
        wait_for(lambda: not self.c.editorActive)
        self.assertFalse(self.obj('geometryEditor').property('visible'))
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.warnings, self.warnings)

    def test_numeric_resize_keeps_pending_input_until_apply_or_revert(self):
        self.load_ui(); self.open()
        self.obj('geometryWidth').setProperty('text', '1,000')
        self.invoke('geometryWidth', 'textEdited')
        self.assertFalse(self.obj('geometryWidth').property('acceptableInput'))
        self.invoke('applyGeometryWidth')
        self.assertIsNone(self.c.editor.recipe['output_size'])
        self.obj('geometryWidth').setProperty('text', '60')
        self.invoke('geometryWidth', 'textEdited')
        self.assertFalse(self.obj('rotateGeometry').property('enabled'))
        self.assertFalse(self.obj('geometryHeight').property('enabled'))
        self.invoke('geometryWidth', 'accepted')
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertEqual(self.c.editor.recipe['output_size'], [60, 40])
        self.assertTrue(self.obj('geometryHeight').property('enabled'))
        self.obj('geometryHeight').setProperty('text', '20')
        self.invoke('geometryHeight', 'textEdited')
        self.invoke('revertGeometryFields')
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertEqual(self.obj('geometryHeight').property('text'), '40')
        self.assertEqual(self.c.editor.recipe['output_size'], [60, 40])
        self.assertTrue(self.obj('geometryWidth').property('enabled'))
        self.assertFalse(self.warnings, self.warnings)

    def test_untagged_image_defaults_to_disclosed_srgb_and_can_opt_out(self):
        with Image.new('RGB', (120, 80), 'blue') as image:
            image.save(self.path, format='JPEG')
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        self.load_ui()
        self.assertTrue(self.c.openEditor(self.image_id))
        wait_for(lambda: self.c.editor.state == 'ready'
                 and self.obj('geometryEditor').property('previewReady'))
        self.assertTrue(self.c.editor.assumeSrgb)
        self.assertFalse(self.c.editor.dirty)
        self.assertTrue(self.obj('editorAssumedSrgbNotice').property('visible'))
        self.assertFalse(self.obj('editorPreviewRecovery').property('visible'))
        self.assertTrue(self.obj('openExportCopy').property('enabled'))
        self.obj('assumeEditorSrgb').setProperty('checked', False)
        self.invoke('assumeEditorSrgb', 'toggled')
        wait_for(lambda: self.c.editor.state == 'error' and not self.c.editor.busy
                 and self.obj('geometryEditor').property('previewReady'))
        self.assertEqual(self.c.editor.errorCode, 'unknown_color_space')
        self.assertTrue(self.obj('editorPreviewRecovery').property('visible'))
        self.assertEqual(self.c.editor.preview._frame.color.policy, 'legacy-v1')
        self.assertFalse(self.c.editor.assumeSrgb)
        self.assertFalse(self.obj('openExportCopy').property('enabled'))
        self.invoke('confirmEditorSrgb')
        wait_for(lambda: self.c.editor.state == 'ready')
        self.assertTrue(self.c.editor.assumeSrgb)
        self.assertFalse(self.c.editor.dirty)
        self.assertEqual(self.c.editor.preview._frame.color.policy, 'srgb-v1')
        self.assertFalse(self.obj('editorPreviewRecovery').property('visible'))
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)
        self.assertFalse(self.warnings, self.warnings)

    def test_untagged_rgba_default_exports_tagged_copy_without_changing_source(self):
        with Image.new('RGBA', (120,80), (80,120,160,128)) as image: image.save(self.path)
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        self.open()
        self.assertTrue(self.c.editor.assumeSrgb)
        self.assertFalse(self.c.editor.dirty)
        target = self.root / 'tagged-copy.png'
        self.assertTrue(self.c.editor.export_copy(str(target),
            {'format':'PNG','quality':90,'lossless':False,'matte':None}))
        wait_for(lambda: not self.c.editor.exporting)
        self.assertTrue(self.c.editor.lastExport.get('published'), self.c.editor.error)
        with Image.open(target) as copy:
            self.assertEqual(copy.info.get('srgb'),0)
            self.assertEqual(copy.getpixel((0,0)),(80,120,160,128))
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns),before)

    def test_untagged_default_does_not_override_profiles_or_unsupported_modes(self):
        from PIL import ImageCms
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        for label, mode, icc, declared, expected in (
            ('declared', 'RGB', None, True, 'ready'),
            ('profiled', 'RGB', profile, False, 'ready'),
            ('broken', 'RGB', b'broken profile', False, 'error'),
            ('grayscale', 'L', None, False, 'error')):
            with self.subTest(label=label):
                info = PngImagePlugin.PngInfo()
                if declared: info.add(b'sRGB',bytes([0]))
                with Image.new(mode,(120,80)) as image: image.save(self.path,icc_profile=icc,pnginfo=info)
                before = self.path.read_bytes()
                self.assertTrue(self.c.openEditor(self.image_id))
                wait_for(lambda:self.c.editor.state in ('ready','error') and not self.c.editor.busy)
                self.assertEqual(self.c.editor.state,expected,self.c.editor.error)
                self.assertFalse(self.c.editor.assumeSrgb)
                self.assertFalse(self.c.editor.canAssumeSrgb)
                self.assertEqual(self.path.read_bytes(),before)
                self.assertTrue(self.c.closeEditor(True,self.c.editor.revision))
                wait_for(lambda:self.c.editor.state=='closed')

    def test_single_window_close_leaves_clean_editor_and_closes_window(self):
        self.load_ui(); self.open()
        self.window.close()
        wait_for(lambda: not self.c.editorActive and not self.window.isVisible())
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse(self.warnings,self.warnings)

    def test_keep_editing_cancels_pending_window_close(self):
        self.load_ui(); self.open(); self.c.editor.rotate(1)
        wait_for(lambda:self.c.editor.state=='ready')
        self.window.close(); self.invoke('keepGeometry')
        self.assertFalse(self.window.property('quitRequested'))
        self.invoke('closeGeometryEditor'); self.invoke('discardGeometry')
        wait_for(lambda:not self.c.editorActive)
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.warnings,self.warnings)

    def test_busy_close_is_visible_and_waits_without_starting_more_work(self):
        self.load_ui(); self.c._busy=True; self.c._kind='analyze'
        self.window.close()
        self.assertTrue(self.obj('quitWorkDialog').property('visible'))
        self.invoke('cancelWindowQuit')
        self.assertFalse(self.window.property('quitRequested'))
        self.assertTrue(self.window.isVisible())
        self.window.close(); self.invoke('confirmWindowQuit')
        self.assertTrue(self.c._close_requested)
        self.assertTrue(self.window.isVisible())
        self.c._busy=False
        self.c._batch=dict(self.c._batch,state='running')
        with patch.object(self.c.queue,'claim') as claim:
            self.c.runNext(); claim.assert_not_called()
        self.c.changed.emit()
        wait_for(lambda:not self.window.isVisible())
        self.assertFalse(self.warnings,self.warnings)

    def test_window_close_waits_for_export_then_closes_without_a_second_request(self):
        from threading import Event
        from image_lab_ui import export_job
        release = Event(); started = Event(); encode = export_job.encode_copy
        def delayed(*args,**kwargs):
            started.set()
            if not release.wait(5): raise RuntimeError('Test release timed out')
            return encode(*args,**kwargs)
        self.load_ui(); self.open(); self.c.editor.rotate(1)
        wait_for(lambda:self.c.editor.state=='ready')
        target = self.root/'close-copy.png'
        with patch.object(export_job,'encode_copy',side_effect=delayed):
            try:
                self.assertTrue(self.c.editor.export_copy(str(target),
                    {'format':'PNG','quality':90,'lossless':False,'matte':None}))
                wait_for(started.is_set)
                self.window.close()
                self.assertTrue(self.obj('quitWorkDialog').property('visible'))
                self.invoke('confirmWindowQuit')
                self.assertTrue(self.window.isVisible())
                self.assertTrue(self.c.editor.exporting)
            finally: release.set()
            wait_for(lambda:not self.window.isVisible())
        self.assertTrue(target.exists())
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse(self.warnings,self.warnings)

    def test_unapplied_fields_and_window_quit_are_guarded(self):
        self.load_ui(1280, 820)
        self.open()
        self.obj('cropLeft').setProperty('text', '5'); self.invoke('cropLeft', 'textEdited')
        self.assertFalse(self.c.editor.dirty)
        self.window.close()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.obj('discardGeometryDialog').property('visible'))
        self.invoke('keepGeometry')
        self.assertTrue(self.c.eventFilter(self.app, QEvent(QEvent.Type.Quit)))
        self.assertTrue(self.obj('discardGeometryDialog').property('visible'))
        self.invoke('discardGeometry')
        wait_for(lambda: not self.c.editorActive)
        wait_for(lambda: not self.window.isVisible())  # The accepted close request completes.
        self.assertEqual(self.path.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
