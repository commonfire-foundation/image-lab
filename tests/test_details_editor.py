"""Live details-form interactions, independent of model inference."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    from PySide6.QtCore import QObject, QEvent, QMetaObject, QUrl, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from image_lab_ui.app import Controller

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_QT, 'Install the desktop extra for details UI tests')
class DetailsEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle('Basic')
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name)
        self.path = self.root / 'landscape.png'
        with Image.new('RGB', (200, 120), '#507c82') as image:
            image.save(self.path)
        self.original = self.path.read_bytes()
        self.c = Controller(self.root / 'catalog', theme_paths=[self.root / 'no-theme'])
        self.c.catalog.import_image(self.path)
        self.image_id = self.c.catalog.rows()[0]['id']
        self.c.catalog.store_result(self.image_id, self.c.catalog.fingerprint(self.path), {'vision': {
            'caption': 'A quiet mountain scene', 'tags': ['mountains', 'sky'],
            'medium': 'illustration', 'mood': ['calm'], 'composition': ['wide view'],
            'text_present': False, 'watermark_present': False}})
        self.c.select(self.image_id)
        self.saved = self.c.catalog.get(self.image_id)
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(e.toString() for e in errors))
        self.engine.rootContext().setContextProperty('controller', self.c)
        self.engine.rootContext().setContextProperty('gallery', self.c.model)
        self.engine.load(QUrl.fromLocalFile(str(ROOT / 'image_lab_ui/Main.qml')))
        self.addCleanup(self.cleanup)
        self.assertTrue(self.engine.rootObjects(), self.warnings)
        self.window = self.engine.rootObjects()[0]
        self.window.setWidth(900); self.window.setHeight(600)
        self.open()

    def cleanup(self):
        if self.engine.rootObjects():
            QMetaObject.invokeMethod(self.obj('detailsEditor'), 'close')
            self.window.close()
        self.engine.deleteLater(); self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.c.viewerMetadata.shutdown(); self.c.viewerMeasurements.shutdown()
        self.c.omarchy_palette.timer.stop(); self.c.catalog.close()
        self.c.deleteLater(); self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def obj(self, name):
        obj = self.window.findChild(QObject, name)
        if obj is None:
            # Repeater delegates have visual parents but not necessarily QObject ownership.
            pending = [self.window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name:
                    return item
                pending.extend(item.childItems())
        self.assertIsNotNone(obj, name)
        return obj

    def invoke(self, name):
        self.assertTrue(QMetaObject.invokeMethod(self.obj(name), 'clicked'))

    def open(self):
        self.invoke('editImageDetails')
        QTest.qWait(80)
        self.assertTrue(self.obj('detailsEditor').property('visible'))

    def test_tokens_add_paste_deduplicate_remove_and_save_pending_across_tabs(self):
        field = self.obj('editTagsInput')
        field.forceActiveFocus()
        for char in 'dusk':
            QTest.keyClick(self.window, Qt.Key(ord(char.upper())))
        QTest.keyClick(self.window, Qt.Key_Return)
        self.assertEqual(self.obj('editTags').property('text'), 'mountains\nsky\ndusk')
        field.setProperty('text', 'DUSK, blue\n green ,blue')
        self.assertEqual(self.obj('editTags').property('text'), 'mountains\nsky\ndusk\nblue\ngreen')
        self.invoke('editTagsRemove1')
        self.assertNotIn('sky', self.obj('editTags').property('text'))
        field.setProperty('text', 'pending tag')
        self.obj('detailsTabs').setProperty('currentIndex', 1)
        self.obj('editMoodInput').setProperty('text', 'reflective')
        self.obj('editCompositionInput').setProperty('text', 'open horizon')
        self.invoke('saveImageDetails')
        self.assertFalse(self.obj('detailsEditor').property('visible'))
        self.assertEqual(self.c.selected['tags'], ['mountains', 'dusk', 'blue', 'green', 'pending tag'])
        self.assertEqual(self.c.selected['moodEntries'], ['calm', 'reflective'])
        self.assertEqual(self.c.selected['compositionEntries'], ['wide view', 'open horizon'])
        self.assertEqual(self.c.catalog.get(self.image_id)['prediction'], self.saved['prediction'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.warnings, self.warnings)

    def test_cancel_discards_removed_tokens_pending_inputs_and_other_tab_drafts(self):
        self.invoke('editTagsRemove0')
        self.obj('editTagsInput').setProperty('text', 'unsaved tag')
        self.obj('detailsTabs').setProperty('currentIndex', 1)
        self.obj('editMoodInput').setProperty('text', 'unsaved mood')
        self.invoke('cancelImageDetails')
        self.assertEqual(self.c.catalog.get(self.image_id), self.saved)
        self.open()
        self.assertEqual(self.obj('detailsTabs').property('currentIndex'), 0)
        self.assertEqual(self.obj('editTags').property('text'), 'mountains\nsky')
        self.assertEqual(self.obj('editTagsInput').property('text'), '')
        self.assertEqual(self.obj('editMoodInput').property('text'), '')
        self.assertFalse(self.warnings, self.warnings)

    def test_keyboard_save_includes_uncommitted_tag(self):
        field = self.obj('editTagsInput')
        field.forceActiveFocus()
        for char in 'night':
            QTest.keyClick(self.window, Qt.Key(ord(char.upper())))
        QTest.keyClick(self.window, Qt.Key_Return, Qt.ControlModifier)
        QTest.qWait(50)
        self.assertFalse(self.obj('detailsEditor').property('visible'))
        self.assertEqual(self.c.selected['tags'], ['mountains', 'sky', 'night'])
        self.assertFalse(self.warnings, self.warnings)

    def test_empty_lists_long_tokens_and_footer_fit_both_layouts(self):
        self.obj('editTags').setProperty('text', '')
        self.obj('editMood').setProperty('text', '')
        self.obj('editComposition').setProperty('text', '')
        for width, height in ((900, 600), (1280, 820)):
            self.window.setWidth(width); self.window.setHeight(height)
            self.obj('editTagsInput').setProperty('text', 'long token ' * 30 + ',')
            QTest.qWait(80)
            chip = self.obj('editTagsRemove0')
            self.assertLess(chip.mapToScene(chip.boundingRect().center()).x(), width)
            save = self.obj('saveImageDetails')
            center = save.mapToScene(save.boundingRect().center())
            self.assertTrue(0 < center.x() < width and 0 < center.y() < height)
            self.invoke('editTagsRemove0')
        self.invoke('saveImageDetails')
        self.assertEqual(self.c.selected['tags'], [])
        self.assertEqual(self.c.selected['moodEntries'], [])
        self.assertEqual(self.c.selected['compositionEntries'], [])
        self.assertFalse(self.warnings, self.warnings)
