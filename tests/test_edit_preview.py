from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image, PngImagePlugin
from test_edit_color import linear_rgb_profile
from image_lab_ui.analyzer_client import inspect_measurements, validate_measurement_result, AnalyzerProcessError
from image_lab_ui.edit_process import prepare_source, render_source
from image_lab_ui.edit_recipe import EditRecipe, Size

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    from PySide6.QtCore import QSize, QUrl, QEventLoop, QTimer
    from PySide6.QtGui import QColorSpace, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtTest import QTest
    from image_lab_ui.edit_preview import EditorPreview, preview_qimage, validate_original_measurements

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_QT, 'Install desktop extra for Qt preview tests')
class EditorPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'source.png'
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.pool.shutdown)
        self.bridge = EditorPreview()
        self.addCleanup(self.bridge.clear)

    def call(self, function, *args, **kwargs):
        # The production blocking worker/provider APIs never run on the Qt thread.
        return self.pool.submit(function, *args, **kwargs).result(timeout=45)

    def fixture(self, mode='RGBA', alpha=128, declaration=False, untagged=False, orientation=1):
        color = (128, 64, 32, alpha) if mode == 'RGBA' else (128, 64, 32)
        with Image.new(mode, (3, 2), color) as image:
            options = {}
            if declaration:
                info = PngImagePlugin.PngInfo(); info.add(b'sRGB', b'\0')
                options['pnginfo'] = info
            elif not untagged:
                options['icc_profile'] = linear_rgb_profile()
            exif = Image.Exif(); exif[274] = orientation
            image.save(self.path, exif=exif, **options)
        self.source = self.call(prepare_source, self.path)
        self.recipe = EditRecipe.original(self.source.oriented_size.width, self.source.oriented_size.height)

    def frame(self, generation=1, policy='srgb-v1', assumption=False, recipe=None, preview=2048):
        return self.call(render_source, self.source, recipe or self.recipe, request_id=f'preview-{generation}',
            generation=generation, color_policy=policy, assume_srgb=assumption, preview_longest=preview)

    def begin(self, generation=1, policy='srgb-v1', assumption=False, recipe=None):
        self.bridge.begin(self.source, recipe or self.recipe, request_id=f'preview-{generation}',
            generation=generation, color_policy=policy, assume_srgb=assumption)

    def test_qimage_rgb_stride_rgba_alpha_and_color_tags(self):
        for mode in ('RGB', 'RGBA'):
            with self.subTest(mode=mode):
                self.fixture(mode)
                frame = self.frame()
                image = preview_qimage(frame)
                self.assertEqual(image.colorSpace(), QColorSpace(QColorSpace.NamedColorSpace.SRgb))
                channels = 4 if mode == 'RGBA' else 3
                for y in range(2):
                    for x in range(3):
                        offset = (y * 3 + x) * channels
                        expected = tuple(frame.pixels[offset:offset + channels])
                        self.assertEqual(image.pixelColor(x, y).getRgb(), expected if channels == 4 else expected + (255,))
                legacy = preview_qimage(self.frame(policy='legacy-v1'))
                self.assertFalse(legacy.colorSpace().isValid())
                self.assertEqual(legacy.pixelColor(0, 0).red(), 128)

    def test_qimage_keeps_oriented_nonuniform_pixels_for_all_exif_values(self):
        for orientation in range(1, 9):
            with Image.frombytes('RGB', (3, 2), bytes((32, 64, 128, 60, 120, 10, 90, 30, 220,
                    0, 128, 255, 180, 190, 200, 210, 20, 40))) as source:
                exif = Image.Exif(); exif[274] = orientation
                source.save(self.path, exif=exif, icc_profile=linear_rgb_profile())
            self.source = self.call(prepare_source, self.path)
            self.recipe = EditRecipe.original(self.source.oriented_size.width, self.source.oriented_size.height)
            frame = self.frame()
            image = preview_qimage(frame)
            for y in range(frame.size.height):
                for x in range(frame.size.width):
                    offset = (y * frame.size.width + x) * 3
                    self.assertEqual(image.pixelColor(x, y).getRgb()[:3], tuple(frame.pixels[offset:offset + 3]))

    def test_declared_and_assumed_previews_match_requested_measurements(self):
        for declaration in (True, False):
            with self.subTest(declaration=declaration):
                self.fixture(declaration=declaration, untagged=not declaration)
                frame = self.frame(assumption=not declaration)
                result = self.call(inspect_measurements, self.path, color_policy='srgb-v1', assume_srgb=not declaration)
                validate_original_measurements(frame, self.recipe, result)
                self.assertTrue(preview_qimage(frame).colorSpace().isValid())
                self.assertEqual(frame.color.status, 'declared_srgb' if declaration else 'assumed_srgb')
                with self.assertRaises(AnalyzerProcessError):
                    validate_measurement_result(result, self.path)  # Legacy callers do not silently adopt v4.

    def test_qt_quick_pixels_match_converted_preview_and_alpha_compositing(self):
        engine = QQmlApplicationEngine()
        engine.addImageProvider('editor-preview', self.bridge.provider)
        engine.rootContext().setContextProperty('previewBridge', self.bridge)
        fixture = Path(self.temp.name) / 'Preview.qml'
        fixture.write_text('''import QtQuick
import QtQuick.Window
Window { width: 120; height: 80; visible: true; color: "white"
 property bool imageReady: picture.status === Image.Ready
 Image { id: picture; anchors.fill: parent; source: previewBridge.url; cache: false; smooth: false; asynchronous: true }
}''')
        engine.load(QUrl.fromLocalFile(str(fixture)))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        try:
            for generation, alpha in enumerate((255, 128, 0), 1):
                self.fixture(alpha=alpha)
                self.begin(generation)
                frame = self.frame(generation)
                self.assertTrue(self.bridge.publish(frame))
                loop = QEventLoop()
                timer = QTimer(); timer.setInterval(10)
                timer.timeout.connect(lambda: loop.quit() if window.property('imageReady') else None)
                deadline = QTimer(); deadline.setSingleShot(True); deadline.timeout.connect(loop.quit)
                timer.start(); deadline.start(3000)
                loop.exec()
                timer.stop(); deadline.stop()
                timer.timeout.disconnect(); deadline.timeout.disconnect()
                self.assertTrue(window.property('imageReady'), 'Preview did not become ready')
                QTest.qWait(40)
                screenshot = window.grabWindow()
                self.assertFalse(screenshot.isNull())
                actual = screenshot.pixelColor(screenshot.width() // 2, screenshot.height() // 2).getRgb()
                expected = tuple(round((channel * alpha + 255 * (255 - alpha)) / 255) for channel in frame.pixels[:3])
                for channel, reference in zip(actual[:3], expected):
                    self.assertLessEqual(abs(channel - reference), 2)
                if alpha == 128:
                    screenshot.save(str(ROOT / 'results' / 'editor-preview-qt.png'))
        finally:
            self.bridge.clear()
            window.close()
            engine.deleteLater()
            QTest.qWait(20)

    def test_stale_duplicate_cancelled_and_wrong_policy_results_rejected(self):
        self.fixture()
        self.begin()
        first = self.frame()
        self.assertTrue(self.bridge.publish(first))
        self.assertFalse(self.bridge.publish(first))
        old_token = self.bridge.url.rsplit('/', 1)[1]
        self.begin(2)
        self.assertEqual(self.bridge.url, '')
        self.assertFalse(self.bridge.publish(first))
        self.assertTrue(self.bridge.provider.requestImage(old_token, QSize(), QSize()).isNull())
        second = self.frame(2)
        self.assertFalse(self.bridge.publish(replace(second, source=replace(self.source, sha256='0' * 64))))
        self.assertFalse(self.bridge.publish(replace(second, recipe=self.recipe.flipped(horizontal=True))))
        self.assertFalse(self.bridge.publish(replace(second, color=replace(second.color, assume_srgb=True))))
        self.assertTrue(self.bridge.publish(second))
        self.assertNotEqual(self.bridge.url.rsplit('/', 1)[1], old_token)
        self.bridge.clear()
        self.assertFalse(self.bridge.publish(second))
        with self.assertRaises(ValueError):
            self.begin(2)

    def test_full_oversized_and_truncated_rasters_cannot_be_previews(self):
        self.fixture()
        frame = self.frame()
        for invalid in (self.frame(preview=None), replace(frame, size=Size(2049, 1)), replace(frame, pixels=frame.pixels[:-1])):
            with self.assertRaises(ValueError):
                preview_qimage(invalid)

    def test_original_measurements_reject_edits_source_policy_and_runtime_drift(self):
        self.fixture()
        self.begin()
        frame = self.frame()
        self.bridge.publish(frame)
        result = self.call(inspect_measurements, self.path, color_policy='srgb-v1')
        self.assertIs(self.bridge.matching_original_measurements(result), result)
        for field, value in (('policy', 'legacy-v1'), ('assume_srgb', True), ('rendering_intent', 'perceptual'),
                             ('pillow_version', 'different'), ('transform_optimization', None),
                             ('black_point_compensation', True), ('order', 'wrong')):
            changed = deepcopy(result)
            changed['provenance']['preprocessing']['color_management'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.bridge.matching_original_measurements(changed)
        changed = deepcopy(result); changed['input']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.bridge.matching_original_measurements(changed)
        with self.assertRaises(ValueError):
            validate_original_measurements(frame, self.recipe.rotated(), result)
        with self.assertRaises(ValueError):
            validate_original_measurements(self.frame(recipe=self.recipe.flipped(horizontal=True)), self.recipe, result)
        with self.assertRaises(ValueError):
            validate_original_measurements(self.frame(policy='legacy-v1'), self.recipe, result)
        self.bridge.clear()
        with self.assertRaises(ValueError):
            self.bridge.matching_original_measurements(result)

    def test_provider_copy_is_detached_and_publication_requires_owner_thread(self):
        self.fixture()
        self.begin()
        frame = self.frame()
        with self.assertRaises(RuntimeError):
            self.call(self.bridge.publish, frame)
        self.assertTrue(self.bridge.publish(frame))
        token = self.bridge.url.rsplit('/', 1)[1]
        first = self.bridge.provider.requestImage(token, QSize(), QSize(8000, 8000))
        original = first.pixelColor(0, 0)
        first.fill(0)
        second = self.bridge.provider.requestImage(token, QSize(), QSize())
        self.assertEqual(second.pixelColor(0, 0), original)
        self.assertEqual(second.size(), QSize(3, 2))


if __name__ == '__main__':
    unittest.main()
