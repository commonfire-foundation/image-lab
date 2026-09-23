"""Run with an extracted wheel as cwd/PYTHONPATH and an offscreen Qt backend."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageCms
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from image_lab_ui import edit_preview
from image_lab_ui.analyzer_client import inspect_measurements
from image_lab_ui.edit_process import prepare_source, render_source
from image_lab_ui.edit_recipe import EditRecipe


def main():
    root = Path.cwd()
    assert Path(edit_preview.__file__).resolve().is_relative_to(root)
    app = QGuiApplication.instance() or QGuiApplication([])
    bridge = edit_preview.EditorPreview()
    engine = QQmlApplicationEngine()
    engine.addImageProvider('editor-preview', bridge.provider)
    engine.rootContext().setContextProperty('previewBridge', bridge)
    with tempfile.TemporaryDirectory(dir=root) as directory, ThreadPoolExecutor(max_workers=1) as pool:
        path = Path(directory) / 'source.png'
        with Image.new('RGBA', (3, 2), (128, 64, 32, 128)) as image:
            image.save(path, icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        original = path.read_bytes()
        source = pool.submit(prepare_source, path).result(timeout=35)
        recipe = EditRecipe.original(3, 2)
        frame = pool.submit(render_source, source, recipe, color_policy='srgb-v1',
                            request_id='wheel-preview', generation=1).result(timeout=65)
        measurement = pool.submit(inspect_measurements, path, color_policy='srgb-v1').result(timeout=35)
        bridge.begin(source, recipe, request_id='wheel-preview', generation=1, color_policy='srgb-v1')
        assert bridge.publish(frame)
        bridge.matching_original_measurements(measurement)
        qml = Path(directory) / 'Preview.qml'
        qml.write_text('''import QtQuick
import QtQuick.Window
Window { width: 120; height: 80; visible: true; color: "white"
 property bool imageReady: picture.status === Image.Ready
 Image { id: picture; anchors.fill: parent; source: previewBridge.url; cache: false; asynchronous: true }
}''')
        engine.load(QUrl.fromLocalFile(str(qml)))
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        loop = QEventLoop()
        timer = QTimer(); timer.setInterval(10)
        timer.timeout.connect(lambda: loop.quit() if window.property('imageReady') else None)
        deadline = QTimer(); deadline.setSingleShot(True); deadline.timeout.connect(loop.quit)
        try:
            timer.start(); deadline.start(3000); loop.exec()
            assert window.property('imageReady')
            screenshot = window.grabWindow()
            assert not screenshot.isNull()
            actual = screenshot.pixelColor(screenshot.width() // 2, screenshot.height() // 2).getRgb()[:3]
            expected = tuple(round((c * 128 + 255 * 127) / 255) for c in (128, 64, 32))
            assert all(abs(a - b) <= 2 for a, b in zip(actual, expected)), (actual, expected)
            assert path.read_bytes() == original
            print(json.dumps({'packaged_qt_preview': True, 'rendered_rgb': actual,
                              'source_policy_matched': True, 'module': edit_preview.__file__}))
        finally:
            timer.stop(); deadline.stop()
            timer.timeout.disconnect(); deadline.timeout.disconnect()
            bridge.clear(); window.close(); engine.deleteLater(); QTest.qWait(20)


if __name__ == '__main__':
    main()
