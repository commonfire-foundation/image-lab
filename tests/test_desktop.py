import gc
import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image

HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QMetaObject, QObject, QTimer, QUrl, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtQuickControls2 import QQuickStyle
    from image_lab_ui.app import Controller, main


@unittest.skipUnless(HAS_QT, "Install the desktop extra for Qt tests")
class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("Basic")
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        # Run last (after window/engine cleanups and bound-method references are
        # released): finalize any orphaned PySide cycles on the GUI thread,
        # rather than letting a later worker collect a previous test's QObjects.
        self.addCleanup(self._collect_qt_garbage)
        self.root = Path(self.temp.name)
        self.fake_command = (sys.executable, str(Path(__file__).parent / 'helpers' / 'fake_analyzer.py'))
        self.theme_file = self.root / 'theme' / 'colors.toml'
        self.controller = Controller(self.root / "cache", analyzer_command=self.fake_command,
                                     theme_paths=[self.theme_file])
        self.addCleanup(self.controller.omarchy_palette.timer.stop)
        self.addCleanup(self.controller.catalog.close)
        self.image = self.root / "test.png"
        Image.new("RGB", (150, 100), "red").save(self.image)

    def _collect_qt_garbage(self):
        self.controller = None
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()

    @contextmanager
    def analyzer_mode(self, mode):
        self.controller.analyzer_command = (*self.fake_command, '--mode', mode)
        try:
            yield
        finally:
            self.controller.analyzer_command = self.fake_command

    def wait_for_submission(self):
        if not self.controller.submitting:
            return
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        def changed():
            if not self.controller.submitting:
                loop.quit()
        self.controller.changed.connect(changed)
        timer.start(10000)
        loop.exec()
        self.controller.changed.disconnect(changed)
        self.assertFalse(self.controller.submitting)

    def wait_for_worker(self):
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        def changed():
            if not self.controller.busy:
                loop.quit()
        self.controller.changed.connect(changed)
        timer.start(10000)
        loop.exec()
        self.controller.changed.disconnect(changed)
        if self.controller.busy:
            self.controller.thread.requestInterruption()
            self.controller.thread.quit()
            self.controller.thread.wait()
            self.fail("Worker failed to finish")

    def test_library_removal_confirmation_and_selection(self):
        from PySide6.QtTest import QTest

        original = self.image.read_bytes()
        self.controller.catalog.import_image(self.image)
        second = self.root / 'second.png'
        Image.new('RGB', (20, 20), 'blue').save(second)
        self.controller.catalog.import_image(second)
        self.controller.model.reload()
        image_id = next(row['id'] for row in self.controller.catalog.rows() if row['path'] == str(self.image))
        other_id = next(row['id'] for row in self.controller.catalog.rows() if row['id'] != image_id)
        self.controller.select(image_id)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        window.setWidth(900)
        window.setHeight(600)
        dialog = window.findChild(QObject, 'removeLibraryDialog')
        remove = window.findChild(QObject, 'removeLibraryImage')
        confirm = window.findChild(QObject, 'confirmLibraryRemoval')
        cancel = window.findChild(QObject, 'cancelLibraryRemoval')
        QTest.qWait(100)
        self.controller.select(image_id)
        QMetaObject.invokeMethod(remove, 'clicked')
        QTest.qWait(100)
        self.assertTrue(dialog.property('visible'))
        self.assertLessEqual(dialog.property('height'), 552)
        self.assertEqual(self.controller.catalog.count(), 2)
        QMetaObject.invokeMethod(cancel, 'clicked')
        self.assertEqual(self.controller.catalog.count(), 2)
        QMetaObject.invokeMethod(remove, 'clicked')
        QTest.qWait(100)
        confirm.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Space)
        QTest.qWait(100)
        self.assertFalse(dialog.property('visible'))
        self.assertIsNone(self.controller.catalog.get(image_id))
        self.assertEqual(self.controller.selected, {})
        self.assertEqual(self.controller.total, 1)
        self.assertEqual(self.image.read_bytes(), original)
        # Bulk confirmation snapshots the checked set, not a later selection.
        third = self.root / 'third.png'
        Image.new('RGB', (20, 20), 'green').save(third)
        self.controller.catalog.import_image(third)
        self.controller.model.reload()
        self.controller.select(other_id)
        self.controller.selectMatches()
        self.assertEqual(self.controller.checkedCount, 2)
        QMetaObject.invokeMethod(window.findChild(QObject, 'removeSelectedImages'), 'clicked')
        self.controller.clearChecked()
        QTest.qWait(100)
        QMetaObject.invokeMethod(confirm, 'clicked')
        QTest.qWait(100)
        self.assertEqual(self.controller.total, 0)
        self.assertEqual(self.controller.checkedCount, 0)
        self.assertEqual(self.controller.filterCounts['all'], 0)
        self.assertTrue(second.is_file())
        self.assertTrue(third.is_file())

    def test_context_menu_removes_right_clicked_image(self):
        from PySide6.QtTest import QTest

        self.controller.catalog.import_image(self.image)
        second = self.root / 'second.png'
        Image.new('RGB', (20, 20), 'blue').save(second)
        self.controller.catalog.import_image(second)
        self.controller.model.reload()
        ids = self.controller.catalog.matching_ids()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        QTest.qWait(100)
        self.controller.select(ids[0])
        # Delegate items are owned by the visual tree, not the QObject tree.
        items = [window.contentItem()]
        tile = None
        while items:
            item = items.pop()
            if item.objectName() == 'imageTileMouse' + str(ids[1]):
                tile = item
                break
            items.extend(item.childItems())
        self.assertIsNotNone(tile)
        point = tile.mapToScene(tile.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, point)
        QTest.qWait(100)
        menu = window.findChild(QObject, 'imageContextMenu')
        action = window.findChild(QObject, 'removeImageMenuAction')
        dialog = window.findChild(QObject, 'removeLibraryDialog')
        self.assertTrue(menu.property('visible'))
        self.assertTrue(action.property('enabled'))
        point = action.mapToScene(action.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        self.assertTrue(dialog.property('visible'))
        self.assertEqual(self.controller.catalog.count(), 2)
        QMetaObject.invokeMethod(window.findChild(QObject, 'confirmLibraryRemoval'), 'clicked')
        QTest.qWait(100)
        self.assertIsNotNone(self.controller.catalog.get(ids[0]))
        self.assertIsNone(self.controller.catalog.get(ids[1]))
        self.assertTrue(self.image.is_file())
        self.assertTrue(second.is_file())

    def test_library_removal_busy_guard_and_filtered_view(self):
        self.controller.catalog.import_image(self.image)
        image_id = self.controller.catalog.rows()[0]['id']
        self.controller.model.reload()
        self.controller.select(image_id)
        self.controller.toggleChecked(image_id)
        for attribute in ('_busy', '_submitting'):
            setattr(self.controller, attribute, True)
            if attribute == '_busy': self.controller._kind = 'scan'
            self.assertFalse(self.controller.removeImages([image_id])['ok'])
            self.assertIsNotNone(self.controller.catalog.get(image_id))
            setattr(self.controller, attribute, False)
            self.controller._kind = ''
        self.controller.search('test')
        self.controller.setLibraryFilter('needs_tags')
        self.assertTrue(self.controller.removeImages([image_id])['ok'])
        self.assertEqual(self.controller.viewQuery, 'test')
        self.assertEqual(self.controller.libraryFilter, 'needs_tags')
        self.assertEqual(self.controller.total, 0)
        self.assertEqual(self.controller.selected, {})

    def test_about_layout_and_close_controls(self):
        from PySide6.QtTest import QTest

        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        about = window.findChild(QObject, 'aboutDialog')
        close = window.findChild(QObject, 'aboutClose')
        credits = window.findChild(QObject, 'aboutCredits')
        for width, height in [(1280, 820), (900, 600)]:
            window.setWidth(width)
            window.setHeight(height)
            QMetaObject.invokeMethod(about, 'open')
            QTest.qWait(100)
            self.assertTrue(about.property('visible'))
            self.assertLessEqual(about.property('height'), height - 48)
            close_rect = close.mapRectToScene(close.boundingRect())
            credits_rect = credits.mapRectToScene(credits.boundingRect())
            self.assertLess(close_rect.bottom(), credits_rect.top())
            self.assertAlmostEqual(close.x() + close.width(), close.parentItem().width(), delta=1)
            self.assertLessEqual(credits.x() + credits.width(), credits.parentItem().width())
            self.assertGreaterEqual(close.width(), 38)
            self.assertGreaterEqual(close.height(), 38)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, close_rect.center().toPoint())
            QTest.qWait(100)
            self.assertFalse(about.property('visible'))
            QMetaObject.invokeMethod(about, 'open')
            QTest.qWait(100)
            close.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(100)
            self.assertFalse(about.property('visible'))
            QMetaObject.invokeMethod(about, 'open')
            QTest.qWait(100)
            QTest.keyClick(window, Qt.Key_Escape)
            QTest.qWait(100)
            self.assertFalse(about.property('visible'))

    def test_search_clear_preserves_filter_and_compact_layout(self):
        from PySide6.QtTest import QTest

        self.controller.catalog.import_image(self.image)
        self.controller.setLibraryFilter('needs_tags')
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        search = window.findChild(QObject, 'catalogSearch')
        clear = window.findChild(QObject, 'clearCatalogSearch')
        self.assertFalse(clear.property('visible'))
        for width, height in [(1280, 820), (900, 600)]:
            window.setWidth(width)
            window.setHeight(height)
            QTest.qWait(50)
            self.assertGreaterEqual(search.property('width'), 280)
            self.assertEqual(search.property('height'), 46)
            self.assertLessEqual(search.x() + search.width(), search.parentItem().width())
            search.setProperty('text', 'no-match')
            QTest.qWait(300)
            self.assertEqual(self.controller.total, 0)
            self.assertTrue(clear.property('visible'))
            # Exercise mouse activation and return focus to the text field.
            point = clear.mapToScene(clear.boundingRect().center()).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            self.assertEqual(search.property('text'), '')
            self.assertFalse(clear.property('visible'))
            self.assertTrue(search.property('activeFocus'))
            self.assertEqual(self.controller.libraryFilter, 'needs_tags')
            self.assertEqual(self.controller.total, 1)
            # Clear a query before its debounce expires using the keyboard.
            search.setProperty('text', 'pending-query')
            clear.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(300)
            self.assertEqual(search.property('text'), '')
            self.assertEqual(self.controller.total, 1)
            self.assertTrue(search.property('activeFocus'))
            self.assertEqual(self.controller.libraryFilter, 'needs_tags')

    def test_filename_suggestions_dialog_copies_without_renaming(self):
        from PySide6.QtTest import QTest

        catalog = self.controller.catalog
        catalog.import_image(self.image)
        row = catalog.rows()[0]
        image_id = row['id']
        original = self.image.read_bytes()
        self.controller.select(image_id)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        action = window.findChild(QObject, 'suggestNames')
        self.assertFalse(action.property('enabled'))
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {
            'caption': 'A misty pine forest beside a mountain lake',
            'tags': ['pine forest', 'mountain lake', 'fog'],
            'mood': ['quiet'], 'medium': 'photography'}})
        self.controller.select(image_id)
        saved = dict(catalog.get(image_id))
        self.assertTrue(action.property('enabled'))
        self.assertEqual(len(self.controller.suggestNames()), 5)
        QMetaObject.invokeMethod(action, 'clicked')
        QTest.qWait(100)
        dialog = window.findChild(QObject, 'namingDialog')
        field = window.findChild(QObject, 'suggestedFilename')
        copy = window.findChild(QObject, 'copySuggestedFilename')
        self.assertTrue(dialog.property('visible'))
        self.assertEqual(field.property('text'), self.controller.suggestNames()[0]['name'])
        window.setWidth(900)
        window.setHeight(600)
        QTest.qWait(100)
        self.assertLessEqual(dialog.property('height'), 552)
        items, options = [window.contentItem()], {}
        while items:
            item = items.pop()
            if item.objectName().startswith('filenameOption'):
                options[item.objectName()] = item
            items.extend(item.childItems())
        option = options['filenameOption1']
        point = option.mapToScene(option.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        self.assertEqual(field.property('text'), self.controller.suggestNames()[1]['name'])
        self.assertTrue(option.property('checked'))
        self.assertFalse(options['filenameOption0'].property('checked'))
        field.setProperty('text', 'my-quiet-forest.png')
        with patch('image_lab_ui.app.QGuiApplication.clipboard') as clipboard:
            point = copy.mapToScene(copy.boundingRect().center()).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            clipboard.return_value.setText.assert_called_once_with('my-quiet-forest.png')
        self.assertEqual(copy.property('text'), 'Copied')
        field.setProperty('text', 'another-name.png')
        self.assertEqual(copy.property('text'), 'Copy name')
        self.assertEqual(dict(catalog.get(image_id)), saved)
        self.assertEqual(self.image.read_bytes(), original)
        self.assertFalse((self.root / 'my-quiet-forest.png').exists())
        QMetaObject.invokeMethod(dialog, 'close')
        QTest.qWait(200)
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {'caption': 'Red flower'}})
        self.controller.select(image_id)
        QMetaObject.invokeMethod(action, 'clicked')
        QTest.qWait(100)
        self.assertEqual(field.property('text'), 'red-flower.png')
        self.assertEqual(copy.property('text'), 'Copy name')
        QMetaObject.invokeMethod(dialog, 'close')

    def test_confirmed_rename_updates_selection_and_preserves_tags(self):
        from PySide6.QtTest import QTest

        catalog = self.controller.catalog
        catalog.import_image(self.image)
        image_id = catalog.rows()[0]['id']
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {'caption': 'Red flower', 'tags': ['red']}})
        self.controller.search('')
        self.controller.select(image_id)
        saved = catalog.get(image_id)
        original = self.image.read_bytes()
        self.controller._busy = True
        self.controller._kind = 'scan'
        result = self.controller.renameImage(image_id, str(self.image), 'red-flower.png')
        self.assertFalse(result['ok'])
        self.controller._busy = False
        self.controller._kind = ''
        self.assertFalse(self.controller.renameImage(image_id + 1, str(self.image), 'red-flower.png')['ok'])
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        window.setWidth(900)
        window.setHeight(600)
        action = window.findChild(QObject, 'suggestNames')
        QMetaObject.invokeMethod(action, 'clicked')
        QTest.qWait(100)
        rename = window.findChild(QObject, 'renameSuggestedFile')
        QMetaObject.invokeMethod(rename, 'clicked')
        QTest.qWait(100)
        confirm = window.findChild(QObject, 'confirmRenameDialog')
        self.assertTrue(confirm.property('visible'))
        self.assertTrue(self.image.exists())
        self.assertEqual(confirm.property('proposedName'), 'red-flower.png')
        QMetaObject.invokeMethod(confirm, 'close')
        QTest.qWait(100)
        self.assertTrue(self.image.exists())
        QMetaObject.invokeMethod(rename, 'clicked')
        QTest.qWait(100)
        button = window.findChild(QObject, 'confirmRenameFile')
        point = button.mapToScene(button.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        renamed = self.root / 'red-flower.png'
        self.assertFalse(self.image.exists())
        self.assertEqual(renamed.read_bytes(), original)
        self.assertEqual(catalog.get(image_id), dict(saved, path=str(renamed)))
        self.assertEqual(self.controller.selected['imageId'], image_id)
        self.assertEqual(self.controller.selected['name'], 'red-flower.png')
        self.assertEqual(self.controller.model.items[0]['name'], 'red-flower.png')
        self.assertFalse(window.findChild(QObject, 'namingDialog').property('visible'))

    def test_rename_conflict_offers_alternative_and_reconfirms(self):
        from PySide6.QtTest import QTest

        catalog = self.controller.catalog
        catalog.import_image(self.image)
        image_id = catalog.rows()[0]['id']
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {'caption': 'Red flower'}})
        self.controller.select(image_id)
        occupied = self.root / 'red-flower.png'
        occupied.write_bytes(b'keep original destination')
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        window.setWidth(900)
        window.setHeight(600)
        QMetaObject.invokeMethod(window.findChild(QObject, 'suggestNames'), 'clicked')
        QTest.qWait(100)
        QMetaObject.invokeMethod(window.findChild(QObject, 'renameSuggestedFile'), 'clicked')
        QTest.qWait(100)
        confirm = window.findChild(QObject, 'confirmRenameDialog')
        confirm_button = window.findChild(QObject, 'confirmRenameFile')
        failure = window.findChild(QObject, 'renameFailureDialog')
        use_alternate = window.findChild(QObject, 'useAlternateFilename')
        for number in (2, 3):
            QMetaObject.invokeMethod(confirm_button, 'clicked')
            QTest.qWait(100)
            self.assertTrue(failure.property('visible'))
            name = f'red-flower-{number}.png'
            self.assertEqual(failure.property('alternative'), name)
            self.assertTrue(self.image.exists())
            point = use_alternate.mapToScene(use_alternate.boundingRect().center()).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            QTest.qWait(100)
            self.assertTrue(confirm.property('visible'))
            self.assertEqual(confirm.property('proposedName'), name)
            self.assertTrue(self.image.exists())  # Accepting the idea is not a rename.
            self.assertFalse((self.root / name).exists())
            if number == 2:
                # A competing file arriving after lookup must not be overwritten.
                (self.root / name).write_bytes(b'arrived after suggestion')
        QMetaObject.invokeMethod(confirm_button, 'clicked')
        QTest.qWait(100)
        self.assertFalse(self.image.exists())
        self.assertTrue((self.root / 'red-flower-3.png').is_file())
        self.assertEqual(occupied.read_bytes(), b'keep original destination')
        self.assertEqual((self.root / 'red-flower-2.png').read_bytes(), b'arrived after suggestion')
        self.assertEqual(self.controller.selected['name'], 'red-flower-3.png')

    def test_details_editor_saves_corrections_and_cancel_discards_draft(self):
        from PySide6.QtTest import QTest

        catalog = self.controller.catalog
        catalog.import_image(self.image)
        image_id = catalog.rows()[0]['id']
        self.controller.select(image_id)
        self.assertFalse(self.controller.canEditDetails)
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {
            'caption': 'Crimson forest', 'tags': ['crimson', 'trees'], 'medium': 'photography',
            'mood': ['calm'], 'composition': ['centered'], 'text_present': False, 'watermark_present': True}})
        self.controller.select(image_id)
        saved = catalog.get(image_id)
        original = self.image.read_bytes()
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        window.setWidth(900)
        window.setHeight(600)
        action = window.findChild(QObject, 'editImageDetails')
        editor = window.findChild(QObject, 'detailsEditor')
        description = window.findChild(QObject, 'editDescription')
        tags = window.findChild(QObject, 'editTags')
        save = window.findChild(QObject, 'saveImageDetails')
        cancel = window.findChild(QObject, 'cancelImageDetails')
        QMetaObject.invokeMethod(action, 'clicked')
        QTest.qWait(100)
        self.assertTrue(editor.property('visible'))
        self.assertLessEqual(editor.property('height'), 552)
        self.assertEqual(description.property('text'), 'Crimson forest')
        self.assertEqual(tags.property('text'), 'crimson\ntrees')
        description.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Tab)
        self.assertTrue(tags.property('activeFocus'))
        window.findChild(QObject, 'detailsTabs').setProperty('currentIndex', 1)
        QTest.qWait(50)
        window.findChild(QObject, 'editWatermarkPresent').forceActiveFocus()
        scroll = window.findChild(QObject, 'detailsEditorScroll').property('contentItem')
        self.assertGreater(scroll.property('contentY'), 0)
        description.setProperty('text', 'Discard this draft')
        QMetaObject.invokeMethod(cancel, 'clicked')
        QTest.qWait(100)
        self.assertEqual(catalog.get(image_id), saved)
        QMetaObject.invokeMethod(action, 'clicked')
        QTest.qWait(100)
        self.assertEqual(description.property('text'), 'Crimson forest')
        description.setProperty('text', 'A blue lake')
        tags.setProperty('text', ' blue \nBlue\nwater\n')
        window.findChild(QObject, 'editMedium').setProperty('text', 'painting')
        window.findChild(QObject, 'editMood').setProperty('text', 'peaceful')
        window.findChild(QObject, 'editComposition').setProperty('text', 'wide view')
        window.findChild(QObject, 'editTextPresent').setProperty('checked', True)
        window.findChild(QObject, 'editWatermarkPresent').setProperty('checked', False)
        point = save.mapToScene(save.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        self.assertFalse(editor.property('visible'), editor.property('saveError'))
        selected = self.controller.selected
        self.assertEqual(selected['caption'], 'A blue lake')
        self.assertEqual(selected['tags'], ['blue', 'water'])
        self.assertEqual(selected['medium'], 'painting')
        self.assertEqual(selected['mood'], 'peaceful')
        self.assertEqual(selected['composition'], 'wide view')
        self.assertTrue(selected['textPresent'])
        self.assertFalse(selected['watermarkPresent'])
        self.assertTrue(selected['userEdited'])
        self.assertEqual(catalog.get(image_id)['prediction'], saved['prediction'])
        self.assertEqual(self.image.read_bytes(), original)
        self.assertEqual(catalog.count('crimson'), 0)
        self.assertEqual(catalog.count('lake'), 1)
        self.assertIn('blue-lake.png', [entry['name'] for entry in self.controller.suggestNames()])
        self.assertEqual(warnings, [])

    def test_details_editor_stale_save_keeps_draft_and_reports_error(self):
        from PySide6.QtTest import QTest

        catalog = self.controller.catalog
        catalog.import_image(self.image)
        image_id = catalog.rows()[0]['id']
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {'caption': 'Old caption'}})
        self.controller.select(image_id)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        QMetaObject.invokeMethod(window.findChild(QObject, 'editImageDetails'), 'clicked')
        QTest.qWait(100)
        description = window.findChild(QObject, 'editDescription')
        description.setProperty('text', 'My draft')
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {'caption': 'New caption'}})
        QMetaObject.invokeMethod(window.findChild(QObject, 'saveImageDetails'), 'clicked')
        editor = window.findChild(QObject, 'detailsEditor')
        self.assertTrue(editor.property('visible'))
        self.assertIn('changed', editor.property('saveError'))
        self.assertEqual(description.property('text'), 'My draft')
        self.assertEqual(catalog.get(image_id)['user_edits'], '{}')
        QMetaObject.invokeMethod(window.findChild(QObject, 'cancelImageDetails'), 'clicked')
        QTest.qWait(100)
        QMetaObject.invokeMethod(window.findChild(QObject, 'editImageDetails'), 'clicked')
        QTest.qWait(100)
        self.assertEqual(description.property('text'), 'New caption')
        QMetaObject.invokeMethod(window.findChild(QObject, 'cancelImageDetails'), 'clicked')

    def test_app_menu_actions_keyboard_and_close_guard(self):
        from PySide6.QtTest import QTest

        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects(), warnings)
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        window.setWidth(900)
        window.setHeight(600)
        QTest.qWait(100)
        button = window.findChild(QObject, 'appMenuButton')
        menu = window.findChild(QObject, 'appMenu')
        point = button.mapToScene(button.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        self.assertTrue(menu.property('visible'))
        about_action = window.findChild(QObject, 'appMenuAbout')
        point = about_action.mapToScene(about_action.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        about = window.findChild(QObject, 'aboutDialog')
        self.assertTrue(about.property('visible'))
        QMetaObject.invokeMethod(about, 'close')
        QTest.qWait(100)
        button.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Space)
        QTest.qWait(100)
        self.assertTrue(menu.property('visible'))
        QTest.keyClick(window, Qt.Key_Escape)
        QTest.qWait(100)
        self.assertFalse(menu.property('visible'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'appMenuViewQueue'), 'triggered')
        queue = window.findChild(QObject, 'queuePanel')
        self.assertTrue(queue.property('visible'))
        QMetaObject.invokeMethod(queue, 'close')
        QTest.qWait(100)
        folder_action = window.findChild(QObject, 'appMenuChooseFolder')
        self.assertTrue(folder_action.property('enabled'))
        QMetaObject.invokeMethod(folder_action, 'triggered')
        folder = window.findChild(QObject, 'folderDialog')
        self.assertTrue(folder.property('visible'))
        QMetaObject.invokeMethod(folder, 'close')
        self.controller._busy = True
        self.controller.changed.emit()
        self.assertFalse(folder_action.property('enabled'))
        quit_action = window.findChild(QObject, 'appMenuQuit')
        QMetaObject.invokeMethod(quit_action, 'triggered')
        self.assertTrue(window.isVisible())
        quit_dialog = window.findChild(QObject, 'quitWorkDialog')
        self.assertTrue(quit_dialog.property('visible'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'cancelWindowQuit'), 'clicked')
        self.assertFalse(quit_dialog.property('visible'))
        self.assertTrue(window.isVisible())
        self.controller._busy = False
        self.controller.changed.emit()
        QMetaObject.invokeMethod(quit_action, 'triggered')
        self.assertFalse(window.isVisible())
        self.assertEqual(warnings, [])

    def test_folder_locations_are_validated_without_importing(self):
        nested = self.root / 'photos #1 ü'
        nested.mkdir()
        for location in (str(nested), QUrl.fromLocalFile(str(nested)).toString()):
            result = self.controller.resolveFolder(location)
            self.assertTrue(result['ok'], result)
            self.assertEqual(QUrl(result['url']).toLocalFile(), str(nested))
        for location in ('', 'relative/path', str(self.image), str(self.root / 'missing')):
            self.assertFalse(self.controller.resolveFolder(location)['ok'])
        self.assertFalse(self.controller.busy)
        self.assertEqual(self.controller.total, 0)

    def test_folder_panel_navigation_scan_and_escape(self):
        from PySide6.QtTest import QTest

        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui/Main.qml')))
        self.assertTrue(engine.rootObjects(), warnings)
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        window.setWidth(900)
        window.setHeight(600)
        panel = window.findChild(QObject, 'folderDialog')
        field = window.findChild(QObject, 'folderPath')
        QMetaObject.invokeMethod(panel, 'open')
        QTest.qWait(100)
        field.setProperty('text', str(self.root))
        QMetaObject.invokeMethod(field, 'accepted')
        QTest.qWait(100)
        self.assertEqual(panel.property('currentPath'), str(self.root))
        nested = self.root / 'browse' / 'photos #1 ü'
        nested.mkdir(parents=True)
        field.setProperty('text', str(nested.parent))
        QMetaObject.invokeMethod(field, 'accepted')
        QTest.qWait(150)
        folders = window.findChild(QObject, 'folderList')
        self.assertEqual(folders.property('count'), 1)
        folders.setProperty('currentIndex', 0)
        folders.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Return)
        QTest.qWait(100)
        self.assertEqual(panel.property('currentPath'), str(nested), panel.property('locationError'))
        QMetaObject.invokeMethod(window.findChild(QObject, 'folderUp'), 'clicked')
        self.assertEqual(panel.property('currentPath'), str(nested.parent))
        field.setProperty('text', str(self.root))
        QMetaObject.invokeMethod(field, 'accepted')
        field.setProperty('text', str(self.root / 'missing'))
        QMetaObject.invokeMethod(field, 'accepted')
        self.assertTrue(panel.property('locationError'))
        self.assertEqual(panel.property('currentPath'), str(self.root))
        with patch.object(self.controller, 'start') as start:
            QMetaObject.invokeMethod(window.findChild(QObject, 'scanFolder'), 'clicked')
            start.assert_not_called()
            self.assertTrue(panel.property('visible'))
            field.setProperty('text', str(self.root))
            QMetaObject.invokeMethod(window.findChild(QObject, 'scanFolder'), 'clicked')
            start.assert_called_once_with('scan', str(self.root))
        self.assertFalse(panel.property('visible'))
        QMetaObject.invokeMethod(panel, 'open')
        QTest.qWait(100)
        QTest.keyClick(window, Qt.Key_Escape)
        self.assertFalse(panel.property('visible'))
        self.assertEqual(warnings, [])

    def test_settings_panel_save_cancel_and_error(self):
        from PySide6.QtTest import QTest
        from image_lab_ui.preferences import DEFAULTS

        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects(), warnings)
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        window.setWidth(900)
        window.setHeight(600)
        action = window.findChild(QObject, 'appMenuSettings')
        panel = window.findChild(QObject, 'settingsPanel')
        checkbox = window.findChild(QObject, 'settingsViewerAutoplay')
        QMetaObject.invokeMethod(action, 'triggered')
        QTest.qWait(100)
        self.assertTrue(panel.property('visible'))
        self.assertLessEqual(panel.property('height'), 552)
        checkbox.setProperty('checked', False)
        self.assertEqual(self.controller.settings, DEFAULTS)
        QMetaObject.invokeMethod(window.findChild(QObject, 'cancelSettings'), 'clicked')
        QTest.qWait(100)
        QMetaObject.invokeMethod(action, 'triggered')
        QTest.qWait(100)
        self.assertTrue(checkbox.property('checked'))
        checkbox.setProperty('checked', False)
        self.controller.catalog.db.execute("CREATE TRIGGER reject_preferences BEFORE INSERT ON preferences BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        save = window.findChild(QObject, 'saveSettings')
        QMetaObject.invokeMethod(save, 'clicked')
        self.assertTrue(panel.property('visible'))
        self.assertIn('test failure', panel.property('saveError'))
        self.assertEqual(self.controller.settings, DEFAULTS)
        self.controller.catalog.db.execute('DROP TRIGGER reject_preferences')
        point = save.mapToScene(save.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        self.assertFalse(panel.property('visible'))
        self.assertEqual(self.controller.settings, dict(DEFAULTS, autoplayViewerGifs=False))
        self.assertEqual(warnings, [])

    def test_background_scan_and_analysis(self):
        self.controller.importFolder(QUrl.fromLocalFile(str(self.root.resolve())))
        self.assertTrue(self.controller.busy)
        self.wait_for_worker()
        self.assertEqual(self.controller.total, 1)
        image_id = self.controller.model.items[0]["imageId"]
        self.controller.select(image_id)
        stages = []
        self.controller.progressChanged.connect(lambda: stages.append(self.controller.progress.get("stage")))
        with self.analyzer_mode('success'):
            self.controller.analyze()
            self.wait_for_worker()
        self.assertTrue(self.controller.progress["success"])
        self.assertFalse(self.controller.progress["running"])
        self.assertEqual(self.controller.progress["stage"], 4)
        self.assertEqual(self.controller.progress["name"], "test.png")
        self.assertTrue({0, 1, 2, 3, 4}.issubset(set(stages)))
        self.assertFalse(self.controller._timer.isActive())
        self.assertEqual(self.controller.selected["caption"], "Red")
        self.assertTrue(self.controller.selected["analyzed"])
        self.controller.search("red")
        self.assertEqual(self.controller.total, 1)
        self.controller.search("does-not-exist")
        self.assertEqual(self.controller.total, 0)
        self.assertEqual(self.controller.selected, {})

    def test_ui_heartbeat_and_interaction_during_slow_analysis(self):
        self.controller.catalog.import_image(self.image)
        other = self.root / 'other.png'
        Image.new('RGB', (80, 80), 'blue').save(other)
        self.controller.catalog.import_image(other)
        self.controller.search('')
        ids = [item['imageId'] for item in self.controller.model.items]
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        frames = []
        window.frameSwapped.connect(lambda: frames.append(self.controller._progress.get('imageId')))
        for targets in ([ids[0]], ids):
            frames.clear()
            samples = {image_id: [] for image_id in targets}
            heartbeat = QTimer()
            heartbeat.setInterval(20)
            def interact():
                progress = self.controller._progress
                if progress.get('running') and progress.get('stage') == 2:
                    samples[progress['imageId']].append(time.monotonic())
                    self.controller.select(ids[1])
                    self.controller.toggleChecked(ids[1])
            heartbeat.timeout.connect(interact)
            with self.analyzer_mode('slow'):
                self.controller.enqueue(targets, replace=True)
                heartbeat.start()
                try:
                    self.wait_for_batch()
                finally:
                    heartbeat.stop()
            for image_id, ticks in samples.items():
                self.assertGreaterEqual(frames.count(image_id), 3, 'UI rendering stalled during inference')
                self.assertGreaterEqual(len(ticks), 10, 'UI callbacks stalled during inference')
                self.assertLess(max(b - a for a, b in zip(ticks, ticks[1:])), 0.75)
                self.assertGreater(ticks[-1] - ticks[0], 1.0)

    def test_worker_gc_guard_restores_previous_state_after_overlapping_jobs(self):
        self.controller.catalog.import_image(self.image)
        self.controller.select(self.controller.catalog.rows()[0]['id'])
        before = gc.isenabled()
        with self.analyzer_mode('slow'):
            self.controller.analyze()
            self.wait_for_submission()
            self.assertTrue(self.controller.busy)
            self.assertFalse(gc.isenabled())
            self.controller.analyze()  # submission and analysis overlap
            self.wait_for_submission()
            self.assertFalse(gc.isenabled())
            self.wait_for_batch()
        self.assertEqual(gc.isenabled(), before)
        self.assertEqual(self.controller._active_python_workers, 0)
        if before:
            gc.disable()
            try:
                with self.analyzer_mode('success'):
                    self.controller.analyze()
                    self.wait_for_batch()
                self.assertFalse(gc.isenabled())
            finally:
                gc.enable()
        self.assertEqual(self.controller._active_python_workers, 0)

    def test_gc_guard_is_shared_between_controllers(self):
        other = Controller(self.root / 'other-cache', analyzer_command=self.fake_command,
                           theme_paths=[self.theme_file])
        self.addCleanup(other.catalog.close)
        self.addCleanup(other.omarchy_palette.timer.stop)
        original = gc.isenabled()
        try:
            self.controller._begin_python_worker()
            other._begin_python_worker()
            self.controller._end_python_worker()
            self.assertFalse(gc.isenabled())
            other._end_python_worker()
            self.assertEqual(gc.isenabled(), original)
        finally:
            if self.controller._active_python_workers:
                self.controller._end_python_worker()
            if other._active_python_workers:
                other._end_python_worker()

    def test_unrelated_details_and_rename_remain_available_during_analysis(self):
        catalog = self.controller.catalog
        catalog.import_image(self.image)
        other = self.root / 'other.png'
        Image.new('RGB', (80, 80), 'blue').save(other)
        catalog.import_image(other)
        running_id = next(row['id'] for row in catalog.rows() if row['path'] == str(self.image))
        other_id = next(row['id'] for row in catalog.rows() if row['path'] == str(other))
        catalog.store_result(other_id, catalog.fingerprint(other),
                             {'vision': {'caption': 'Blue image', 'tags': ['blue']}})
        self.controller.select(other_id)
        with self.analyzer_mode('slow'):
            self.controller.enqueue([running_id], replace=True)
            loop = QEventLoop()
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: loop.quit() if self.controller._progress.get('stage') == 2 else None)
            timer.start()
            QTimer.singleShot(10000, loop.quit)
            loop.exec()
            timer.stop()
            try:
                self.assertTrue(self.controller.busy)
                self.assertEqual(self.controller._progress.get('stage'), 2)
                self.assertTrue(self.controller.canEditDetails)
                self.assertTrue(self.controller.canRename)
                revision = self.controller.detailsForEditing()['editRevision']
                result = self.controller.saveImageDetails(other_id, revision,
                                                          {'caption': 'Blue revised', 'tags': ['blue'],
                                                           'medium': '', 'mood': [], 'composition': [],
                                                           'text_present': False, 'watermark_present': False})
                self.assertTrue(result['ok'], result)
                renamed = self.controller.renameImage(other_id, str(other), 'other-renamed.png')
                self.assertTrue(renamed['ok'], renamed)
                self.assertTrue(other.with_name('other-renamed.png').is_file())
                self.assertEqual(catalog.get(other_id)['path'], str(other.with_name('other-renamed.png')))
                self.assertEqual(self.controller.imageDetails(other_id)['caption'], 'Blue revised')
                self.controller.select(running_id)
                self.assertFalse(self.controller.canRename)
                self.assertFalse(self.controller.canEditDetails)
                self.assertFalse(self.controller.removeImages([running_id])['ok'])
                removed = self.controller.removeImages([other_id])
                self.assertTrue(removed['ok'], removed)
                self.assertTrue(other.with_name('other-renamed.png').is_file())
            finally:
                self.wait_for_worker()
        self.assertIsNone(catalog.get(other_id))
        self.assertIsNotNone(catalog.get(running_id))

    def test_completion_updates_only_changed_tile_with_and_without_search(self):
        self.controller.catalog.import_image(self.image)
        other = self.root / 'other.png'
        Image.new('RGB', (80, 80), 'blue').save(other)
        self.controller.catalog.import_image(other)
        model = self.controller.model
        for query in ('', '.png'):
            self.controller.search(query)
            target = next(i for i, item in enumerate(model.items) if item['name'] == 'test.png')
            image_id = model.items[target]['imageId']
            # Reset the fixture prediction before each real worker completion.
            with self.controller.catalog.db:
                self.controller.catalog.db.execute('UPDATE images SET prediction=NULL WHERE id=?', (image_id,))
            model.refresh_loaded()
            self.controller.select(image_id)
            model.set_checked([image_id])
            changes, resets = [], []
            def changed(first, last, roles):
                changes.append((first.row(), last.row(), list(roles)))
            def reset():
                resets.append(True)
            model.dataChanged.connect(changed)
            model.modelReset.connect(reset)
            try:
                with self.analyzer_mode('success'):
                    self.controller.analyze()
                    self.wait_for_batch()
                self.assertEqual(resets, [])
                self.assertEqual(changes, [(target, target, [Qt.UserRole + model.roles.index('analyzed') + 1])])
                self.assertEqual(model.checked, {image_id})
                self.assertEqual(self.controller.selected['imageId'], image_id)
                self.assertTrue(model.items[target]['analyzed'])
                changes.clear()
                model.refresh_loaded()
                self.assertEqual(changes, [])
            finally:
                model.dataChanged.disconnect(changed)
                model.modelReset.disconnect(reset)

    def test_refresh_reconciles_search_membership_without_reset(self):
        catalog = self.controller.catalog
        catalog.import_image(self.image)
        image_id = catalog.rows()[0]['id']
        self.controller.search('red')
        model = self.controller.model
        resets = []
        model.modelReset.connect(lambda: resets.append(True))
        self.assertEqual(model.rowCount(), 0)
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {'caption': 'red'}})
        model.refresh_loaded()
        self.assertEqual(model.total, 1)
        self.assertEqual(model.items[0]['imageId'], image_id)
        catalog.store_result(image_id, catalog.fingerprint(self.image), {'vision': {'caption': 'blue'}})
        model.refresh_loaded()
        self.assertEqual(model.total, 0)
        self.assertEqual(model.rowCount(), 0)
        self.assertEqual(resets, [])

    def test_refresh_preserves_loaded_pages(self):
        catalog = self.controller.catalog
        for n in range(125):
            path = self.root / f'page-{n:03}.png'
            Image.new('RGB', (8, 8), 'red').save(path)
            catalog.import_image(path)
        model = self.controller.model
        model.reload()
        self.assertEqual(model.rowCount(), 120)
        model.refresh_loaded()
        self.assertTrue(model.canFetchMore())
        model.fetchMore()
        before = [item['imageId'] for item in model.items]
        model.refresh_loaded()
        self.assertEqual([item['imageId'] for item in model.items], before)
        self.assertEqual(model.rowCount(), 125)
        self.assertFalse(model.canFetchMore())

        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        try:
            grid = window.findChild(QObject, 'contactSheet')
            grid.setProperty('currentIndex', 60)
            self.app.processEvents()
            grid.setProperty('contentY', 1200.0)
            self.app.processEvents()
            scroll = grid.property('contentY')
            selected = self.controller.selected['imageId']
            item = model.items[60]
            catalog.store_result(item['imageId'], catalog.fingerprint(Path(item['path'])),
                                 {'vision': {'caption': 'red'}})
            model.refresh_loaded()
            self.app.processEvents()
            self.assertEqual(grid.property('contentY'), scroll)
            self.assertEqual(grid.property('currentIndex'), 60)
            self.assertEqual(self.controller.selected['imageId'], selected)
        finally:
            window.close()
            del engine

    def test_progress_belongs_only_to_selected_image(self):
        self.controller.catalog.import_image(self.image)
        other_dir = self.root / "other"
        other_dir.mkdir()
        other = other_dir / self.image.name  # Same filename, different catalog identity.
        Image.new("RGB", (80, 80), "blue").save(other)
        self.controller.catalog.import_image(other)
        first_id = next(r["id"] for r in self.controller.catalog.rows() if r["path"] == str(self.image.resolve()))
        other_id = next(r["id"] for r in self.controller.catalog.rows() if r["id"] != first_id)
        self.controller.select(first_id)
        self.assertEqual(self.controller.progress, {})
        self.controller._progress = {"imageId": first_id, "running": True, "stage": 2,
                                     "seconds": 1, "name": self.image.name}
        self.assertTrue(self.controller.progress["running"])
        notifications = []
        self.controller.progressChanged.connect(lambda: notifications.append(self.controller.progress))
        self.controller.select(other_id)
        self.assertEqual(self.controller.progress, {})
        self.assertEqual(notifications[-1], {})
        self.controller.setPhase(3, "Saving predictions")
        self.assertEqual(self.controller.progress, {})
        self.controller._kind = "analyze"
        self.controller.setOutcome(True)
        self.assertEqual(self.controller.progress, {})
        self.controller.select(first_id)
        self.assertTrue(self.controller.progress["success"])
        self.controller.search("no-such-image")
        self.assertEqual(self.controller.progress, {})

    def test_failed_progress_and_retry_reset(self):
        self.controller.catalog.import_image(self.image)
        self.controller.select(self.controller.catalog.rows()[0]["id"])
        for _ in range(2):
            with self.analyzer_mode('offline'):
                self.controller.analyze()
                self.wait_for_submission()
                self.assertTrue(self.controller.progress["running"])
                self.assertFalse(self.controller.progress["success"])
                self.assertEqual(self.controller.progress["stage"], 0)
                self.wait_for_worker()
            self.assertFalse(self.controller.progress["running"])
            self.assertFalse(self.controller.progress["success"])
            self.assertEqual(self.controller.progress["label"], "Analysis failed")
            self.assertIn("Ollama offline", self.controller.status)
            self.assertFalse(self.controller._timer.isActive())

    def wait_for_batch(self):
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        def changed():
            if not self.controller.busy and self.controller.batch.get('state') in ('complete', 'stopped'):
                loop.quit()
        self.controller.changed.connect(changed)
        timer.start(10000)
        loop.exec()
        self.controller.changed.disconnect(changed)
        self.assertFalse(self.controller.busy)
        self.assertIn(self.controller.batch.get('state'), ('complete', 'stopped'))

    def test_batch_failure_continues_and_retries(self):
        for n in range(3):
            path = self.root / f'batch-{n}.png'
            Image.new('RGB', (30,20), 'red').save(path)
            self.controller.catalog.import_image(path)
        self.controller.search('batch-')
        self.controller.selectMatches()
        self.assertEqual(self.controller.checkedCount, 3)
        with self.analyzer_mode('fail-one'):
            self.controller.generateSelected()
            self.wait_for_batch()
        self.assertEqual(self.controller.batch['failed'], 1)
        self.assertEqual(self.controller.batch['succeeded'], 2)
        self.assertEqual(len(self.controller.batch['errors']), 1)
        self.assertEqual(self.controller.model.rowCount(), 3)
        with self.analyzer_mode('success'):
            self.controller.retryFailed()
            self.wait_for_batch()
        self.assertEqual(self.controller.batch['total'], 1)
        self.assertEqual(self.controller.batch['succeeded'], 1)

    def test_batch_pause_resume_and_missing_scope(self):
        for name in ['included-one', 'included-two', 'excluded']:
            path = self.root / (name + '.png')
            Image.new('RGB', (30,20), 'blue').save(path)
            self.controller.catalog.import_image(path)
        self.controller.search('included')
        with self.analyzer_mode('success'):
            self.controller.generateMissing()
            self.wait_for_submission()
            self.controller.pauseBatch()
            self.wait_for_worker()
            self.assertEqual(self.controller.batch['succeeded'], 1)
            self.assertEqual(self.controller.batch['queued'], 1)
            self.assertTrue(self.controller.canQueue)
            self.assertFalse(self.controller.canImport)
            self.controller.resumeBatch()
            self.wait_for_batch()
        self.assertEqual(self.controller.batch['total'], 2)
        self.assertEqual(self.controller.catalog.matching_ids('included', missing=True), [])
        self.assertEqual(len(self.controller.catalog.matching_ids('excluded', missing=True)), 1)
        self.assertTrue(self.controller.canQueue)
        self.controller.generateMissing()
        self.wait_for_submission()
        self.assertIn('Nothing added', self.controller.status)

    def test_stop_batch_finishes_current_and_cancels_pending(self):
        for n in range(3):
            path = self.root / f'stop-{n}.png'
            Image.new('RGB', (30,20), 'red').save(path)
            self.controller.catalog.import_image(path)
        self.controller.search('stop-')
        self.controller.selectMatches()
        self.controller.generateSelected()
        self.wait_for_submission()
        self.controller.stopBatch()
        self.wait_for_batch()
        self.assertEqual(self.controller.batch['succeeded'], 1)
        self.assertEqual(self.controller.batch['canceled'], 2)
        self.assertEqual(self.controller.batch['queued'], 0)
        self.assertEqual(self.controller.batch['state'], 'stopped')

    def test_queue_refuses_changed_prompt_without_inference(self):
        self.controller.catalog.import_image(self.image)
        image_id = self.controller.catalog.rows()[0]['id']
        self.controller._batch_id = self.controller.queue.enqueue([image_id])
        with self.controller.catalog.db:
            self.controller.catalog.db.execute("UPDATE jobs SET prompt_version='older-prompt'")
        self.controller.refreshBatch()
        with self.analyzer_mode('offline'):
            self.controller.runNext()
            self.wait_for_batch()
        self.assertEqual(self.controller.batch['failed'], 1)
        self.assertIn('Analyzer changed', self.controller.batch['errors'][0]['error'])

    def test_process_failure_preserves_good_prediction_and_finishes_job(self):
        self.controller.catalog.import_image(self.image)
        image_id = self.controller.catalog.rows()[0]['id']
        self.controller.select(image_id)
        self.controller.analyze()
        self.wait_for_batch()
        saved = self.controller.catalog.get(image_id)['prediction']
        with self.analyzer_mode('truncated'):
            self.controller.analyze()
            self.wait_for_batch()
        self.assertEqual(self.controller.batch['failed'], 1)
        self.assertEqual(self.controller.catalog.get(image_id)['prediction'], saved)
        self.assertFalse(self.controller.busy)
        self.assertFalse(self.controller.progress['running'])

    def test_add_remove_and_resume_shared_queue_without_changing_selection(self):
        for n in range(3):
            path = self.root / f'queued-{n}.png'
            Image.new('RGB', (20, 20), 'red').save(path)
            self.controller.catalog.import_image(path)
        self.controller.search('queued-')
        ids = [item['imageId'] for item in self.controller.model.items]
        self.controller.select(ids[0])
        with self.analyzer_mode('slow'):
            self.controller.analyze()
            self.wait_for_submission()
            original_batch = self.controller.batch['id']
            self.assertEqual(self.controller.selectedState, 'running')
            self.assertTrue(self.controller.canQueue)
            self.assertFalse(self.controller.canImport)
            self.controller.select(ids[1])
            self.controller.analyze()
            self.wait_for_submission()
            self.assertEqual(self.controller.batch['id'], original_batch)
            self.assertEqual(self.controller.selectedState, 'queued')
            self.assertEqual(self.controller.queueProgress['imageId'], ids[0])
            self.controller.pauseBatch()
            self.controller.enqueue([ids[2]])
            self.wait_for_submission()
            self.assertEqual(self.controller.batch['state'], 'paused')
            entry = next(j for j in self.controller.queueEntries if j['image_id'] == ids[2])
            self.controller.removeQueued(entry['id'])
            self.assertEqual(self.controller.queue.image_state(ids[2]), 'canceled')
            self.wait_for_worker()
            self.assertEqual(self.controller.selected['imageId'], ids[1])
            self.assertEqual(self.controller.selectedState, 'queued')
            self.controller.resumeBatch()
            self.wait_for_batch()
        self.assertEqual(self.controller.batch['succeeded'], 2)
        self.assertEqual(self.controller.batch['canceled'], 1)
        self.assertEqual(self.controller.selected['imageId'], ids[1])
        self.assertEqual(self.controller.selectedState, 'succeeded')
        self.assertEqual(self.controller.queue.image_state(ids[0]), 'succeeded')

    def test_slow_submission_is_responsive_and_failure_recovers(self):
        self.controller.catalog.import_image(self.image)
        image_id = self.controller.catalog.rows()[0]['id']
        self.controller.select(image_id)
        ticks = []
        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        with self.analyzer_mode('slow-info'):
            timer.start()
            self.controller.analyze()
            self.assertTrue(self.controller.submitting)
            self.assertFalse(self.controller.canQueue)
            self.wait_for_submission()
            timer.stop()
            self.wait_for_batch()
        self.assertGreater(len(ticks), 20)
        with self.analyzer_mode('bad-info'):
            self.controller.analyze()
            self.wait_for_submission()
        self.assertFalse(self.controller.busy)
        self.assertTrue(self.controller.canQueue)
        self.assertIn('Could not add to queue', self.controller.status)

    def test_retry_failed_image_while_another_is_running(self):
        self.controller.catalog.import_image(self.image)
        first = self.controller.catalog.rows()[0]['id']
        self.controller.select(first)
        with self.analyzer_mode('offline'):
            self.controller.analyze()
            self.wait_for_batch()
        failed = self.controller.queueEntries[0]['id']
        other = self.root / 'other.png'
        Image.new('RGB', (20, 20), 'blue').save(other)
        self.controller.catalog.import_image(other)
        second = next(r['id'] for r in self.controller.catalog.rows() if r['id'] != first)
        with self.analyzer_mode('slow'):
            self.controller.enqueue([second])
            self.wait_for_submission()
            self.controller.retryJob(failed)
            self.wait_for_submission()
            self.assertEqual(self.controller.selectedState, 'queued')
            self.assertEqual(self.controller.batch['total'], 2)
            self.assertFalse(next(e for e in self.controller.queueEntries if e['id'] == failed)['retryable'])
            self.wait_for_batch()
        self.assertEqual(self.controller.selectedState, 'succeeded')

    def test_queue_drawer_loads_with_real_jobs(self):
        self.controller.catalog.import_image(self.image)
        image_id = self.controller.catalog.rows()[0]['id']
        self.controller._batch_id = self.controller.queue.enqueue([image_id])
        self.controller.queue.pause(self.controller._batch_id)
        self.controller.refreshBatch()
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda messages: warnings.extend(str(m) for m in messages))
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        try:
            panel = window.findChild(QObject, 'queuePanel')
            self.assertIsNotNone(panel)
            QMetaObject.invokeMethod(panel, 'open')
            self.app.processEvents()
            self.assertTrue(panel.property('opened') or panel.property('visible'))
            jobs = window.findChild(QObject, 'queueJobs')
            self.assertEqual(jobs.property('count'), 1)
            self.assertEqual(warnings, [])
        finally:
            window.close()
            del engine

    def test_library_filters_scope_selection_and_generation(self):
        catalog = self.controller.catalog
        for name in ('fresh', 'tagged', 'failed', 'retained'):
            path = self.root / f'filter-{name}.png'
            Image.new('RGB', (2, 2), 'red').save(path)
            catalog.import_image(path)
        rows = {Path(row['path']).stem: row for row in catalog.rows()}
        for name in ('tagged', 'retained'):
            row = rows['filter-' + name]
            catalog.store_result(row['id'], (row['mtime'], row['bytes']), {'vision': {'tags': ['ocean']}})
        for name in ('failed', 'retained'):
            row = rows['filter-' + name]
            catalog.store_result(row['id'], (row['mtime'], row['bytes']), error='offline')
        self.controller.search('filter-')
        self.controller.selectMatches()
        self.assertEqual(self.controller.checkedCount, 4)
        self.controller.setLibraryFilter('failed')
        self.assertEqual(self.controller.checkedCount, 0)
        self.assertEqual(self.controller.total, 2)
        self.assertEqual(self.controller.filterCounts, {'all': 4, 'needs_tags': 2, 'tagged': 2, 'failed': 2})
        self.controller.selectMatches()
        expected = {rows['filter-failed']['id'], rows['filter-retained']['id']}
        self.assertEqual(self.controller.model.checked, expected)
        with patch.object(self.controller, 'enqueue') as enqueue:
            self.controller.generateSelected()
            enqueue.assert_called_with(sorted(expected))
            self.controller.generateMissing()
            enqueue.assert_called_with([rows['filter-failed']['id']])
        # A text search intersects the filter and clears the old selection.
        self.controller.search('ocean')
        self.assertEqual(self.controller.libraryFilter, 'failed')
        self.assertEqual(self.controller.total, 1)
        self.assertEqual(self.controller.checkedCount, 0)
        self.assertEqual(self.controller.filterCounts['all'], 2)
        # Filtering is view-only; it must never change an existing queue.
        self.controller._batch_id = self.controller.queue.enqueue([rows['filter-fresh']['id']])
        self.controller.queue.pause(self.controller._batch_id)
        self.controller.refreshBatch()
        before = self.controller.batch
        self.controller.setLibraryFilter('tagged')
        self.assertEqual(self.controller.batch, before)
        self.assertEqual(self.controller.total, 2)
        self.controller.setLibraryFilter('invalid')
        self.assertEqual(self.controller.libraryFilter, 'tagged')

    def test_status_filter_updates_after_analysis_without_resetting_grid(self):
        self.controller.catalog.import_image(self.image)
        self.controller.search('test.png')
        self.controller.setLibraryFilter('needs_tags')
        self.controller.selectMatches()
        image_id = self.controller.model.items[0]['imageId']
        resets = []
        self.controller.model.modelReset.connect(lambda: resets.append(True))
        self.controller.generateSelected()
        self.wait_for_batch()
        self.assertEqual(self.controller.total, 0)
        self.assertEqual(self.controller.model.rowCount(), 0)
        self.assertEqual(self.controller.checkedCount, 0)
        self.assertEqual(resets, [])
        self.assertEqual(self.controller.filterCounts, {'all': 1, 'needs_tags': 0, 'tagged': 1, 'failed': 0})
        self.controller.setLibraryFilter('tagged')
        self.controller.select(image_id)
        with self.analyzer_mode('offline'):
            self.controller.analyze()
            self.wait_for_batch()
        self.assertEqual(self.controller.total, 1)
        self.assertEqual(self.controller.filterCounts['failed'], 1)
        self.controller.setLibraryFilter('failed')
        self.assertEqual(self.controller.total, 1)
        self.assertTrue(self.controller.model.items[0]['analyzed'])

    def test_live_theme_switch_preserves_running_queue_and_view(self):
        self.controller.catalog.import_image(self.image)
        other = self.root / 'other.png'
        Image.new('RGB', (30, 20), 'blue').save(other)
        self.controller.catalog.import_image(other)
        self.controller.search('.png')
        ids = [item['imageId'] for item in self.controller.model.items]
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda messages: warnings.extend(str(m) for m in messages))
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        self.addCleanup(lambda: (window.close(), engine.deleteLater()))
        grid = window.findChild(QObject, 'contactSheet')
        grid.setProperty('currentIndex', 1)
        self.controller.select(ids[1])
        self.controller.toggleChecked(ids[1])
        self.app.processEvents()
        before = (grid.property('contentY'), grid.property('currentIndex'), self.controller.selected['imageId'])
        resets = []
        self.controller.model.modelReset.connect(lambda: resets.append(True))
        with self.analyzer_mode('slow'):
            self.controller.enqueue([ids[0]])
            self.wait_for_submission()
            batch_id = self.controller.batch['id']
            self.theme_file.parent.mkdir()
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            self.controller.themeChanged.connect(loop.quit)
            self.theme_file.write_text('background="#fafafa"\nforeground="#202020"\naccent="#225599"\nlighter_bg="#eeeeee"\n')
            timer.start(1500)
            loop.exec()
            self.controller.themeChanged.disconnect(loop.quit)
            self.app.processEvents()
            self.assertEqual(window.property('color').name(), '#fafafa')
            self.assertEqual(window.findChild(QObject, 'queueBar').property('color').name(), '#eeeeee')
            self.assertEqual(self.controller.batch['id'], batch_id)
            self.assertTrue(self.controller.busy)
            self.assertEqual(self.controller.model.checked, {ids[1]})
            self.assertEqual((grid.property('contentY'), grid.property('currentIndex'), self.controller.selected['imageId']), before)
            self.assertEqual(resets, [])
            self.wait_for_batch()
        self.assertEqual(warnings, [])

    def test_default_software_rendering_respects_environment(self):
        for configured, expected in ((None, 'software'), ('rhi', 'rhi')):
            with patch.dict(os.environ):
                os.environ.pop('QT_QUICK_BACKEND', None)
                if configured:
                    os.environ['QT_QUICK_BACKEND'] = configured
                # Stop at app construction: configuration must precede Qt startup.
                with patch('image_lab_ui.app.QQuickStyle.setStyle'), patch(
                        'image_lab_ui.app.QGuiApplication', side_effect=RuntimeError('app construction')):
                    with self.assertRaisesRegex(RuntimeError, 'app construction'):
                        main([])
                self.assertEqual(os.environ['QT_QUICK_BACKEND'], expected)

    def test_grid_geometry_stays_fixed_between_batch_jobs(self):
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', self.controller)
        engine.rootContext().setContextProperty('gallery', self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui' / 'Main.qml')))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        grid = window.findChild(QObject, 'contactSheet')
        try:
            for width in (900, 1440):
                window.setWidth(width)
                window.setHeight(900)
                geometries = []
                for busy, name, queued in ((True, 'first.png', 2), (False, '', 2),
                                            (True, 'second.png', 1), (False, '', 1),
                                            (True, 'last.png', 0)):
                    self.controller._busy = busy
                    self.controller._batch = dict(total=3, state='running', queued=queued,
                                                  running=int(busy), currentName=name, eta=10,
                                                  finished=0, terminal=0, failed=0, errors=[])
                    self.controller.changed.emit()
                    for _ in range(3):
                        self.app.processEvents()
                    geometries.append((grid.property('y'), grid.property('height')))
                self.assertEqual(geometries, [geometries[0]] * len(geometries))
        finally:
            self.controller._busy = False
            window.close()
            del engine

    def test_qml_loads_and_close_guard(self):
        self.controller.catalog.import_image(self.image)
        self.controller.search('')
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda messages: warnings.extend(str(m) for m in messages))
        engine.rootContext().setContextProperty("controller", self.controller)
        engine.rootContext().setContextProperty("gallery", self.controller.model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "image_lab_ui" / "Main.qml")))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        window.setWidth(900)
        window.setHeight(600)
        self.app.processEvents()
        selection_status = window.findChild(QObject, 'selectionStatus')
        self.assertEqual(selection_status.property('text'), 'Ctrl-click or Space to select')
        self.controller.selectMatches()
        self.app.processEvents()
        self.assertEqual(selection_status.property('text'), '1 selected')
        self.controller.clearChecked()
        self.app.processEvents()
        self.assertEqual(selection_status.property('text'), 'Ctrl-click or Space to select')
        # Repeater delegates have visual parents outside QObject ownership.
        items = [window.contentItem()]
        filters = {}
        while items:
            item = items.pop()
            if item.objectName().startswith('filter-'):
                filters[item.objectName()] = item
            items.extend(item.childItems())
        needs_tags = filters.get('filter-needs_tags')
        self.assertIsNotNone(needs_tags)
        QMetaObject.invokeMethod(needs_tags, 'clicked')
        self.app.processEvents()
        self.assertEqual(self.controller.libraryFilter, 'needs_tags')
        self.assertTrue(needs_tags.property('checked'))
        all_images = filters['filter-all']
        self.assertFalse(all_images.property('checked'))
        self.controller._busy = True
        self.controller.changed.emit()
        window.close()
        self.assertTrue(window.isVisible())
        self.controller._busy = False
        window.close()
        self.assertFalse(window.isVisible())
        self.assertEqual(warnings, [])
        del engine


if __name__ == "__main__":
    unittest.main()
