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
    from PySide6.QtCore import QObject, QMetaObject, QPoint, QUrl, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from image_lab_ui.app import Controller
    from image_lab_ui.metadata import edit_revision


@unittest.skipUnless(HAS_QT, 'Install the desktop extra for Qt tests')
class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle('Basic')
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controller = Controller(self.root / 'cache', theme_paths=[self.root / 'no-theme'])
        self.addCleanup(self.controller.catalog.close)
        self.addCleanup(self.controller.viewerMetadata.shutdown)
        self.addCleanup(self.controller.viewerMeasurements.shutdown)
        self.addCleanup(self.controller.omarchy_palette.timer.stop)
        self.paths = []
        for name, size in [('landscape', (1200, 600)), ('portrait', (600, 1200))]:
            path = self.root / f'{name}.png'
            Image.new('RGB', size, '#507c82').save(path)
            self.controller.catalog.import_image(path)
            self.paths.append(path)
        rows = self.controller.catalog.rows()
        self.ids = [row['id'] for row in rows]
        self.vision = dict(caption='A quiet mountain lake', tags=['lake', 'mountains', 'calm water'],
                           medium='photography', mood=['quiet'], composition=['wide view'],
                           text_present=False, watermark_present=False)
        self.controller.catalog.store_result(self.ids[0], self.controller.catalog.fingerprint(self.paths[0]), {'vision': self.vision})
        self.controller.search('')
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.engine.rootContext().setContextProperty('controller', self.controller)
        self.engine.rootContext().setContextProperty('gallery', self.controller.model)
        self.engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'image_lab_ui/Main.qml')))
        self.assertTrue(self.engine.rootObjects(), self.warnings)
        self.window = self.engine.rootObjects()[0]
        self.window.setWidth(900)
        self.window.setHeight(600)
        self.addCleanup(lambda: (self.window.close(), self.engine.deleteLater()))
        QTest.qWait(100)
        self.viewer = self.window.findChild(QObject, 'imageViewer')
        self.grid = self.window.findChild(QObject, 'contactSheet')

    def visual_item(self, name):
        items = [self.window.contentItem()]
        while items:
            item = items.pop()
            if item.objectName() == name:
                return item
            items.extend(item.childItems())
        self.fail(f'No visual item named {name}')

    def tile_point(self, image_id):
        area = self.visual_item(f'imageTileMouse{image_id}')
        return area.mapToScene(area.boundingRect().center()).toPoint()

    def open_image(self, image_id):
        QTest.mouseDClick(self.window, Qt.LeftButton, Qt.NoModifier, self.tile_point(image_id))
        QTest.qWait(100)
        self.assertTrue(self.viewer.property('visible'))
        self.assertEqual(self.viewer.property('imageId'), image_id)

    def test_file_info_is_default_and_notes_remain_available(self):
        self.open_image(self.ids[0])
        reader = self.controller.viewerMetadata
        for _ in range(50):
            if not reader.data['loading']:
                break
            QTest.qWait(20)
        self.assertFalse(reader.data['loading'])
        self.assertEqual(reader.data['error'], '')
        facts = {row['label']: row['value'] for group in reader.data['groups'] for row in group['rows']}
        self.assertEqual(facts['Format'], 'PNG')
        self.assertEqual(facts['Aspect ratio'], '2:1')
        self.assertEqual(reader.data['provider'], 'Imagescope')
        self.assertEqual(reader.data['metadataVersion'], 1)
        self.assertEqual(facts['EXIF status'], 'Unknown')
        self.assertTrue(self.window.findChild(QObject, 'viewerMetadataWarnings').property('visible'))
        generation = reader.generation
        QMetaObject.invokeMethod(self.window.findChild(QObject, 'viewerMetadataRefresh'), 'clicked')
        self.assertGreater(reader.generation, generation)
        tabs = self.window.findChild(QObject, 'viewerInfoTabs')
        self.assertEqual(tabs.property('currentIndex'), 0)
        self.assertTrue(self.window.findChild(QObject, 'viewerFileInfo').property('visible'))
        notes = self.window.findChild(QObject, 'viewerNotesTab')
        point = notes.mapToScene(notes.boundingRect().center()).toPoint()
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
        self.assertEqual(tabs.property('currentIndex'), 1)
        self.assertTrue(self.window.findChild(QObject, 'viewerDetailsScroll').property('visible'))
        self.assertEqual(self.window.findChild(QObject, 'viewerDescription').property('text'), self.vision['caption'])
        QTest.keyClick(self.window, Qt.Key_Escape)
        QTest.qWait(100)
        self.assertEqual(reader.data['groups'], [])
        self.assertEqual(self.warnings, [])

    def test_metadata_loading_does_not_block_and_ignores_stale_results(self):
        import sys
        from PySide6.QtCore import QTimer

        reader = self.controller.viewerMetadata
        reader._command = (sys.executable, str(Path(__file__).parent / 'helpers/metadata_fault.py'), 'slow-first')
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        self.addCleanup(timer.stop)
        self.controller.inspectImageFile(self.ids[0])
        QTest.qWait(200)
        self.assertGreater(len(ticks), 5)
        self.assertTrue(reader.data['loading'])
        self.controller.inspectImageFile(self.ids[1])
        for _ in range(150):
            QTest.qWait(20)
            if not reader.data['loading']:
                break
        self.assertFalse(reader.data['loading'])
        self.assertEqual(reader.data['error'], '')
        self.assertEqual(reader.data['source']['path'], str(self.paths[1]))
        generation = reader.generation
        self.controller.inspectImageFile(-1)
        reader.complete(generation, {'groups': [{'title': 'stale'}]})
        self.assertEqual(reader.data['groups'], [])

    def test_single_click_sidebar_double_click_viewer_and_escape(self):
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, self.tile_point(self.ids[1]))
        self.assertEqual(self.controller.selected['imageId'], self.ids[1])
        self.assertFalse(self.viewer.property('visible'))
        self.open_image(self.ids[0])
        self.assertEqual(self.viewer.property('width'), self.window.width())
        self.assertEqual(self.viewer.property('height'), self.window.height())
        self.assertEqual(self.window.findChild(QObject, 'viewerDescription').property('text'), self.vision['caption'])
        image = self.window.findChild(QObject, 'viewerImage')
        for _ in range(40):
            if image.property('paintedWidth') > 0:
                break
            QTest.qWait(50)
        self.assertGreater(image.property('paintedWidth'), 0)
        self.assertAlmostEqual(image.property('paintedWidth') / image.property('paintedHeight'), 2, places=2)
        scroll = self.grid.property('contentY')
        QTest.keyClick(self.window, Qt.Key_Escape)
        QTest.qWait(100)
        self.assertFalse(self.viewer.property('visible'))
        self.assertEqual(self.controller.selected['imageId'], self.ids[0])
        self.assertEqual(self.grid.property('contentY'), scroll)
        self.assertTrue(self.grid.property('activeFocus'))
        self.assertEqual(image.property('source').toString(), '')
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(100)
        self.assertTrue(self.viewer.property('visible'))
        QMetaObject.invokeMethod(self.window.findChild(QObject, 'closeImageViewer'), 'clicked')
        QTest.qWait(100)
        self.assertFalse(self.viewer.property('visible'))
        self.assertEqual(self.warnings, [])

    def test_right_click_open_targets_clicked_image_without_checking_it(self):
        QTest.mouseClick(self.window, Qt.RightButton, Qt.ControlModifier, self.tile_point(self.ids[1]))
        QTest.qWait(100)
        menu = self.window.findChild(QObject, 'imageContextMenu')
        self.assertTrue(menu.property('visible'))
        self.assertFalse(self.viewer.property('visible'))
        self.assertEqual(self.controller.checkedCount, 0)
        action = self.window.findChild(QObject, 'openImageMenuAction')
        point = action.mapToScene(action.boundingRect().center()).toPoint()
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        self.assertTrue(self.viewer.property('visible'))
        self.assertEqual(self.viewer.property('imageId'), self.ids[1])
        self.assertIn('Generate tags', self.window.findChild(QObject, 'viewerDescription').property('text'))
        image = self.window.findChild(QObject, 'viewerImage')
        for _ in range(40):
            if image.property('paintedWidth') > 0:
                break
            QTest.qWait(50)
        self.assertGreater(image.property('paintedWidth'), 0)
        self.assertAlmostEqual(image.property('paintedWidth') / image.property('paintedHeight'), 0.5, places=2)
        self.assertLessEqual(image.property('paintedHeight'), image.property('height'))
        self.assertEqual(self.warnings, [])

    def test_open_close_preserves_scrolled_gallery_and_batch_selection(self):
        for number in range(12):
            path = self.root / f'z-extra-{number:02d}.png'
            Image.new('RGB', (20, 10), 'blue').save(path)
            self.controller.catalog.import_image(path)
        self.controller.search('')
        self.grid.setProperty('currentIndex', 8)
        QTest.qWait(100)
        self.grid.setProperty('contentY', 4 * self.grid.property('cellHeight'))
        QTest.qWait(100)
        image_id = self.controller.model.items[8]['imageId']
        self.controller.toggleChecked(image_id)
        scroll = self.grid.property('contentY')
        self.assertGreater(scroll, 0)
        self.open_image(image_id)
        QTest.keyClick(self.window, Qt.Key_Escape)
        QTest.qWait(100)
        self.assertAlmostEqual(self.grid.property('contentY'), scroll, delta=1)  # Qt rounds to a device pixel.
        self.assertEqual(self.grid.property('currentIndex'), 8)
        self.assertEqual(self.controller.model.checked, {image_id})
        self.assertEqual(self.warnings, [])

    def test_viewer_stays_on_opened_image_and_refreshes_saved_corrections(self):
        self.open_image(self.ids[0])
        row = self.controller.catalog.get(self.ids[0])
        self.controller.catalog.save_details(self.ids[0], edit_revision(row), dict(self.vision, caption='Corrected lake', tags=['water']))
        self.controller.select(self.ids[1])
        self.assertEqual(self.viewer.property('imageId'), self.ids[0])
        self.assertEqual(self.window.findChild(QObject, 'viewerDescription').property('text'), 'Corrected lake')
        self.assertEqual(self.window.findChild(QObject, 'viewerFilename').property('text'), 'landscape.png')
        self.assertEqual(self.warnings, [])

    def test_same_path_catalog_revision_restarts_file_info_without_changing_notes(self):
        self.open_image(self.ids[0])
        reader = self.controller.viewerMetadata
        generation = reader.generation
        Image.new('RGB', (300, 100), 'blue').save(self.paths[0])
        self.controller.catalog.import_image(self.paths[0])
        self.controller.changed.emit()
        self.assertGreater(reader.generation, generation)
        for _ in range(150):
            if not reader.data['loading']:
                break
            QTest.qWait(20)
        self.assertFalse(reader.data['loading'])
        self.assertEqual(reader.data['error'], '')
        self.assertEqual(reader.data['metadata']['stored_size'], {'width': 300, 'height': 100})
        self.assertEqual(self.viewer.property('imageId'), self.ids[0])
        self.assertEqual(self.warnings, [])

    def test_measurements_tab_is_read_only_and_shows_policy_and_sampling(self):
        self.open_image(self.ids[0])
        prediction = self.controller.catalog.get(self.ids[0])['prediction']
        reader = self.controller.viewerMeasurements
        self.assertEqual(reader.data['groups'], [])  # No pixel inspection merely for File info.
        tabs = self.window.findChild(QObject, 'viewerInfoTabs')
        tabs.setProperty('currentIndex', 2)
        for _ in range(200):
            if not reader.data['loading']:
                break
            QTest.qWait(20)
        self.assertFalse(reader.data['loading'])
        self.assertEqual(reader.data['error'], '')
        self.assertEqual(reader.data['palette'][0]['hex'], '#507c82')
        self.assertFalse(reader.data['colorAgreement'])
        self.assertIn('legacy-v1', self.window.findChild(QObject, 'viewerMeasurementsPolicy').property('text'))
        self.assertIn('unverified', self.window.findChild(QObject, 'viewerMeasurementsGate').property('text'))
        self.assertEqual(self.controller.catalog.get(self.ids[0])['prediction'], prediction)
        generation = reader.generation
        QMetaObject.invokeMethod(self.window.findChild(QObject, 'viewerMeasurementsRefresh'), 'clicked')
        self.assertGreater(reader.generation, generation)
        tabs.setProperty('currentIndex', 1)
        self.assertFalse(reader.data['loading'])
        self.assertEqual(reader.data['groups'], [])
        self.assertEqual(self.window.findChild(QObject, 'viewerDescription').property('text'), self.vision['caption'])
        self.assertEqual(self.warnings, [])

    def add_gif(self):
        path = self.root / 'a-animation.GIF'
        frames = [Image.new('RGB', (160, 80), color) for color in ('red', 'blue', 'green')]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
        self.controller.catalog.import_image(path)
        image_id = next(row['id'] for row in self.controller.catalog.rows() if row['path'] == str(path))
        self.controller.search('')
        self.controller.select(image_id)
        QTest.qWait(100)
        return path, image_id

    def frames_seen(self, animation):
        frames = set()
        for _ in range(20):
            QTest.qWait(25)
            frames.add(animation.property('currentFrame'))
        return frames

    def test_gif_hover_sidebar_viewer_pause_and_release(self):
        path, image_id = self.add_gif()
        original = path.read_bytes()
        self.assertTrue(self.controller.selected['isGif'])
        sidebar = self.window.findChild(QObject, 'sidebarGif')
        self.assertGreater(len(self.frames_seen(sidebar)), 1)
        self.assertFalse(sidebar.property('cache'))
        self.assertAlmostEqual(sidebar.property('paintedWidth') / sidebar.property('paintedHeight'), 2, places=2)
        tile = self.visual_item(f'tileGif{image_id}')
        QTest.mouseMove(self.window, QPoint(20, 20))
        QTest.qWait(50)
        self.assertEqual(tile.property('source').toString(), '')
        QTest.mouseMove(self.window, self.tile_point(image_id))
        self.assertGreater(len(self.frames_seen(tile)), 1)
        QTest.mouseMove(self.window, QPoint(20, 20))
        QTest.qWait(50)
        self.assertEqual(tile.property('source').toString(), '')
        self.open_image(image_id)
        animation = self.window.findChild(QObject, 'viewerGif')
        self.assertGreater(len(self.frames_seen(animation)), 1)
        self.assertEqual(sidebar.property('source').toString(), '')
        self.assertEqual(tile.property('source').toString(), '')
        self.assertEqual(animation.property('frameCount'), 3)
        self.assertAlmostEqual(animation.property('paintedWidth') / animation.property('paintedHeight'), 2, places=2)
        self.assertEqual(animation.property('sourceSize').width(), 160)
        self.assertEqual(animation.property('sourceSize').height(), 80)
        self.assertFalse(animation.property('cache'))
        pause = self.window.findChild(QObject, 'toggleGifPlayback')
        self.assertTrue(pause.property('enabled'))
        QMetaObject.invokeMethod(pause, 'clicked')
        self.assertTrue(animation.property('paused'))
        self.assertEqual(len(self.frames_seen(animation)), 1)
        QMetaObject.invokeMethod(pause, 'clicked')
        self.assertGreater(len(self.frames_seen(animation)), 1)
        QTest.keyClick(self.window, Qt.Key_Escape)
        QTest.qWait(100)
        self.assertEqual(animation.property('source').toString(), '')
        self.assertGreater(len(self.frames_seen(sidebar)), 1)
        self.controller.select(self.ids[0])
        self.assertEqual(sidebar.property('source').toString(), '')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.warnings, [])

    def test_gif_preferences_disable_autoplay_but_allow_manual_play(self):
        from image_lab_ui.preferences import DEFAULTS

        self.assertTrue(self.controller.saveSettings(dict.fromkeys(DEFAULTS, False))['ok'])
        path, image_id = self.add_gif()
        sidebar = self.window.findChild(QObject, 'sidebarGif')
        self.assertEqual(sidebar.property('source').toString(), '')
        QTest.mouseMove(self.window, self.tile_point(image_id))
        QTest.qWait(100)
        self.assertEqual(self.visual_item(f'tileGif{image_id}').property('source').toString(), '')
        self.open_image(image_id)
        animation = self.window.findChild(QObject, 'viewerGif')
        self.assertTrue(animation.property('paused'))
        self.assertGreater(animation.property('paintedWidth'), 0)
        self.assertEqual(len(self.frames_seen(animation)), 1)
        button = self.window.findChild(QObject, 'toggleGifPlayback')
        self.assertEqual(button.property('text'), 'Play GIF')
        QMetaObject.invokeMethod(button, 'clicked')
        self.assertGreater(len(self.frames_seen(animation)), 1)
        self.controller.saveSettings(dict.fromkeys(DEFAULTS, False))
        self.assertTrue(animation.property('paused'))
        self.controller.saveSettings(DEFAULTS)
        self.assertGreater(len(self.frames_seen(animation)), 1)
        self.assertEqual(self.warnings, [])

    def test_missing_gif_source_uses_viewer_error_state(self):
        path, image_id = self.add_gif()
        path.unlink()
        self.open_image(image_id)
        error = self.window.findChild(QObject, 'viewerImageError')
        for _ in range(40):
            if error.property('visible'):
                break
            QTest.qWait(50)
        self.assertTrue(error.property('visible'))

    def test_missing_source_shows_error_without_losing_metadata(self):
        self.paths[0].unlink()
        self.open_image(self.ids[0])
        error = self.window.findChild(QObject, 'viewerImageError')
        for _ in range(40):
            if error.property('visible'):
                break
            QTest.qWait(50)
        self.assertTrue(error.property('visible'))
        self.assertEqual(self.window.findChild(QObject, 'viewerDescription').property('text'), self.vision['caption'])


if __name__ == '__main__':
    unittest.main()
