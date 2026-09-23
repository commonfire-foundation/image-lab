"""Disposable details-editor layout and save acceptance; works from an extracted wheel.

Run with the intended package on PYTHONPATH and an in-project output directory.
No inference, personal catalog, or external image files are used.
"""
from pathlib import Path
import json
import sys
import tempfile

from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, QEvent, QMetaObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from image_lab_ui import app as module
from image_lab_ui.omarchy_palette import qt_palette


def main():
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    QQuickStyle.setStyle('Basic')
    app = QGuiApplication([])
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        root = Path(temporary)
        path = root / 'quiet-ridge.png'
        with Image.new('RGB', (1200, 800), '#9ab7b4') as image:
            draw = ImageDraw.Draw(image)
            draw.ellipse((790, 110, 930, 250), fill='#f1dcaa')
            draw.polygon(((0, 560), (310, 240), (630, 560), (940, 300), (1200, 530), (1200, 800), (0, 800)), fill='#607e83')
            draw.polygon(((0, 740), (440, 420), (840, 700), (1200, 540), (1200, 800), (0, 800)), fill='#324e5c')
            image.save(path)
        original = path.read_bytes()
        c = module.Controller(root / 'catalog', theme_paths=[root / 'theme.toml'])
        c.catalog.import_image(path)
        image_id = c.catalog.rows()[0]['id']
        c.catalog.store_result(image_id, c.catalog.fingerprint(path), {'vision': {
            'caption': 'Layered mountain ridges beneath a pale golden sun. Muted blue-green slopes leave an open, quiet sky.',
            'tags': ['mountains', 'golden sun', 'layered ridges', 'blue-green', 'minimal landscape', 'open sky'],
            'medium': 'illustration', 'mood': ['quiet', 'contemplative'],
            'composition': ['layered', 'negative space', 'wide view'],
            'text_present': False, 'watermark_present': False}})
        c.search(''); c.select(image_id)
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.rootContext().setContextProperty('controller', c)
        engine.rootContext().setContextProperty('gallery', c.model)
        app.setPalette(qt_palette(c.themeColors))
        engine.load(QUrl.fromLocalFile(str(Path(module.__file__).with_name('Main.qml'))))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        def obj(name):
            found = window.findChild(QObject, name)
            assert found is not None, name
            return found
        def invoke(name):
            assert QMetaObject.invokeMethod(obj(name), 'clicked')
        try:
            for theme in ('dark', 'light'):
                if theme == 'light':
                    (root / 'theme.toml').write_text('background = "#edf1f4"\nforeground = "#253342"\naccent = "#256467"\n')
                    c.omarchy_palette.reload()
                    app.setPalette(qt_palette(c.themeColors))
                for width, height in ((900, 600), (1280, 820)):
                    window.setWidth(width); window.setHeight(height)
                    invoke('editImageDetails')
                    for tab in (0, 1):
                        obj('detailsTabs').setProperty('currentIndex', tab)
                        QTest.qWait(200)
                        button = obj('saveImageDetails')
                        point = button.mapToScene(button.boundingRect().center())
                        assert 0 < point.x() < width and 0 < point.y() < height
                        assert window.grabWindow().save(str(output / f'details-{theme}-{width}-tab{tab}.png'))
                    invoke('cancelImageDetails')
            invoke('editImageDetails')
            obj('editTagsInput').setProperty('text', 'new pending tag')
            invoke('saveImageDetails')
            assert 'new pending tag' in c.selected['tags']
            assert not obj('detailsEditor').property('visible')
            assert path.read_bytes() == original
            assert not warnings, warnings
            print(json.dumps({'module': module.__file__, 'details_editor': True,
                              'pending_tag_saved': True, 'original_unchanged': True,
                              'layouts': ['900x600', '1280x820'], 'themes': ['dark', 'light'],
                              'device_pixel_ratio': window.devicePixelRatio(), 'qml_warnings': warnings}))
        finally:
            QMetaObject.invokeMethod(obj('detailsEditor'), 'close')
            window.close()
            engine.deleteLater(); app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            c.viewerMetadata.shutdown(); c.viewerMeasurements.shutdown()
            c.omarchy_palette.timer.stop(); c.catalog.close()
            c.deleteLater(); app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    main()
