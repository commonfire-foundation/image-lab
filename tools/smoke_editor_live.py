"""Actual packaged Main.qml editor workflow; source/catalog/screenshots stay local."""
import json
from pathlib import Path
import sys
import tempfile

from PIL import Image, ImageDraw, PngImagePlugin
from PySide6.QtCore import QObject, QEvent, QEventLoop, QMetaObject, QPointF, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from image_lab_ui import app as module
from image_lab_ui.edit_recipe import EditRecipe


def wait(predicate):
    if predicate(): return
    loop = QEventLoop(); poll = QTimer(); end = QTimer()
    poll.setInterval(10); end.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    end.timeout.connect(loop.quit)
    poll.start(); end.start(15000); loop.exec()
    poll.stop(); end.stop(); poll.timeout.disconnect(); end.timeout.disconnect()
    assert predicate(), 'Packaged UI did not reach the expected state'


def main():
    root = Path.cwd().resolve()
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    output = Path(sys.argv[1]).resolve()
    QQuickStyle.setStyle('Basic')
    app = QGuiApplication([])
    with tempfile.TemporaryDirectory(dir=root) as directory:
        directory = Path(directory)
        path = directory / 'geometry-fixture.png'
        info = PngImagePlugin.PngInfo(); info.add(b'sRGB', b'\0')
        with Image.new('RGB', (1200, 800), '#263744') as image:
            draw = ImageDraw.Draw(image)
            for x, color in enumerate(('#658b85', '#cfa66b', '#897c9a', '#41657c')):
                draw.rectangle((x * 300 + 12, 12, (x + 1) * 300 - 12, 788), fill=color)
            draw.ellipse((100, 100, 500, 500), fill='#e6d9b4')
            draw.polygon(((700, 650), (1050, 650), (875, 200)), fill='#253a42')
            image.save(path, pnginfo=info)
        original, stamp = path.read_bytes(), path.stat().st_mtime_ns
        c = module.Controller(directory / 'catalog', theme_paths=[directory / 'no-theme'])
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.addImageProvider('editor-preview', c.editor.preview.provider)
        engine.rootContext().setContextProperty('controller', c)
        engine.rootContext().setContextProperty('gallery', c.model)
        window = None
        try:
            c.catalog.import_image(path); c.search('')
            image_id = c.catalog.rows()[0]['id']
            engine.load(QUrl.fromLocalFile(str(Path(module.__file__).with_name('Main.qml'))))
            assert engine.rootObjects(), warnings
            window = engine.rootObjects()[0]
            def obj(name):
                result = window.findChild(QObject, name)
                assert result is not None, name
                return result
            def invoke(name, signal='clicked'):
                assert QMetaObject.invokeMethod(obj(name), signal)
            def capture(name):
                frames = []
                callback = lambda: frames.append(True)
                window.frameSwapped.connect(callback)
                window.update(); wait(lambda: bool(frames))
                window.frameSwapped.disconnect(callback)
                shot = window.grabWindow()
                assert not shot.isNull() and shot.save(str(output / name))
            window.setWidth(900); window.setHeight(600)
            c.uiAction.emit('viewer.open', image_id)
            wait(lambda: obj('imageViewer').property('visible'))
            # Actual pointer activation of the live viewer's entry button.
            button = obj('openGeometryEditor')
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             button.mapToScene(button.boundingRect().center()).toPoint())
            wait(lambda: c.editor.state == 'ready' and obj('geometryEditor').property('previewReady'))
            capture('editor-live-900.png')
            for name, value in (('cropLeft', '100'), ('cropTop', '100'), ('cropRight', '1100'), ('cropBottom', '700')):
                obj(name).setProperty('text', value); invoke(name, 'textEdited')
            invoke('applyGeometryCrop'); invoke('rotateGeometry')
            obj('geometryWidth').setProperty('text', '300'); invoke('geometryWidth', 'textEdited')
            invoke('applyGeometryWidth')
            wait(lambda: c.editor.state == 'ready' and obj('geometryEditor').property('previewReady'))
            assert c.editor.recipe['output_size'] == [300, 500], c.editor.recipe
            if '--drag' in sys.argv[2:]:
                for width, height in ((900, 600), (1280, 820)):
                    window.setWidth(width); window.setHeight(height)
                    # Settle the fitted-image geometry before generating pointer coordinates.
                    capture(f'editor-drag-before-{width}.png')
                    before = EditRecipe.from_dict(c.editor.recipe)
                    invoke('beginDragCrop')
                    overlay = obj('cropOverlay')
                    start = overlay.mapToScene(QPointF(overlay.width()*.25, overlay.height()*.25)).toPoint()
                    end = overlay.mapToScene(QPointF(overlay.width()*.75, overlay.height()*.75)).toPoint()
                    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
                    QTest.mouseMove(window, end, 20)
                    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
                    assert overlay.property('changedSelection')
                    bounds = overlay.property('bounds').toVariant()
                    assert c.editor.recipe == before.to_dict()
                    capture(f'editor-drag-selection-{width}.png')
                    invoke('applyDragCrop')
                    wait(lambda: c.editor.state == 'ready' and obj('geometryEditor').property('previewReady'))
                    assert c.editor.recipe == before.with_display_crop(*bounds).to_dict()
                    assert c.editor.undo()
                    wait(lambda: c.editor.state == 'ready' and obj('geometryEditor').property('previewReady'))
                    assert c.editor.recipe == before.to_dict()
            window.setWidth(1280); window.setHeight(820)
            capture('editor-live-1280.png')
            QTest.keyClick(window, Qt.Key.Key_Escape)
            wait(lambda: obj('discardGeometryDialog').property('visible'))
            capture('editor-live-discard.png')
            invoke('keepGeometry')
            assert c.editor.dirty
            invoke('closeGeometryEditor'); invoke('discardGeometry')
            wait(lambda: not c.editorActive and not obj('geometryEditor').property('visible'))
            assert path.read_bytes() == original and path.stat().st_mtime_ns == stamp
            assert not warnings, warnings
            print(json.dumps({'packaged_live_editor': True, 'qml': str(Path(module.__file__).with_name('Main.qml')),
                              'numeric_output': [300, 500], 'original_unchanged': True,
                              'qml_warnings': warnings, 'device_pixel_ratio': window.devicePixelRatio(),
                              'drag_workflow': '--drag' in sys.argv[2:]}))
        finally:
            c.editor.shutdown(discard=True, revision=c.editor.revision)
            wait(lambda: c.editor.state == 'closed')
            if window: window.close()
            engine.deleteLater(); app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            c.viewerMetadata.shutdown(); c.viewerMeasurements.shutdown()
            c.omarchy_palette.timer.stop(); c.catalog.close()
            c.deleteLater(); app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    main()
