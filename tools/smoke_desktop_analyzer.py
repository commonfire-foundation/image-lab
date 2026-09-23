"""Opt-in real-model acceptance check using a disposable catalog, never user state.

Run with Python from an environment containing both installed wheels and Qt:
  python -I /path/to/tools/smoke_desktop_analyzer.py /path/to/results image1 image2
Uses the environment's installed packages, not checkout imports. Needs Ollama.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
import image_lab_ui.app as desktop
import imagescope


def main():
    if len(sys.argv) != 4:
        raise SystemExit('Usage: smoke_desktop_analyzer.py RESULTS_DIRECTORY IMAGE1 IMAGE2')
    output = Path(sys.argv[1]).resolve()
    sources = [Path(p).resolve() for p in sys.argv[2:]]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
    directory = Path(tempfile.mkdtemp(prefix='analyzer-live-desktop-', dir=output))
    # Child -m invocations must resolve installed packages, not checkout sources.
    os.chdir(directory)
    QQuickStyle.setStyle('Basic')
    app = QGuiApplication([])
    controller = desktop.Controller(directory / 'catalog')
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(str(item) for item in items))
    engine.rootContext().setContextProperty('controller',controller)
    engine.rootContext().setContextProperty('gallery',controller.model)
    engine.load(QUrl.fromLocalFile(str(Path(desktop.__file__).with_name('Main.qml'))))
    assert engine.rootObjects(), 'QML failed to load'
    try:
        for source in sources:
            controller.catalog.import_image(source)
        controller.search('')
        controller.selectMatches()
        controller.select(controller.model.items[0]['imageId'])

        def wait():
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            def changed():
                if not controller.busy and controller.batch.get('state') in ('paused','complete'):
                    loop.quit()
            controller.changed.connect(changed)
            timer.start(120000)
            loop.exec()
            controller.changed.disconnect(changed)
            timer.stop()
            if controller.busy:
                controller.thread.requestInterruption()
                controller.thread.quit()
                controller.thread.wait()
                raise AssertionError('Live batch timed out')

        controller.generateSelected()
        controller.pauseBatch()
        wait()
        assert controller.batch['succeeded']==1 and controller.batch['queued']==1, controller.batch
        paused=dict(controller.batch)
        controller.resumeBatch()
        wait()
        assert controller.batch['succeeded']==2 and controller.batch['failed']==0,controller.batch
        after=[hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
        assert before==after, 'Original changed'
        assert not warnings,warnings
        report={'catalog':str(directory/'catalog/catalog.sqlite3'), 'paused':paused,
                'complete':dict(controller.batch),'original_hashes_unchanged':True,
                'qml_warnings':warnings,'desktop_module':desktop.__file__,
                'analyzer_module':imagescope.__file__}
        (directory/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
        engine.rootObjects()[0].close()
    finally:
        del engine
        controller.catalog.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
