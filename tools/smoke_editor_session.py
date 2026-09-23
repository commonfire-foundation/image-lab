"""Run from an extracted wheel with offscreen Qt and its path on PYTHONPATH."""
import json
from pathlib import Path
import tempfile

from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
from image_lab_ui import edit_session


def wait_until(predicate):
    if predicate():
        return
    loop = QEventLoop()
    poll = QTimer(); poll.setInterval(10)
    deadline = QTimer(); deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit)
    try:
        poll.start(); deadline.start(10000); loop.exec()
        assert predicate(), 'Session smoke deadline exceeded'
    finally:
        poll.stop(); deadline.stop()
        poll.timeout.disconnect(); deadline.timeout.disconnect()


def main():
    root = Path.cwd()
    assert Path(edit_session.__file__).resolve().is_relative_to(root)
    app = QGuiApplication.instance() or QGuiApplication([])
    session = edit_session.EditorSession()
    try:
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path = Path(directory) / 'source.png'
            with Image.new('RGBA', (120, 80), (128, 64, 32, 128)) as image:
                image.save(path)
            original, stamp = path.read_bytes(), path.stat().st_mtime_ns
            assert session.open_source(str(path), color_policy='srgb-v1', assume_srgb=True)
            wait_until(lambda: session.state in ('ready', 'error'))
            assert session.state == 'ready', session.error
            assert session.crop(10, 10, 110, 70)
            assert session.rotate()
            assert session.resizeWidth(30)
            wait_until(lambda: session.state in ('ready', 'error'))
            assert session.state == 'ready', session.error
            assert session.recipe['output_size'] == [30, 50]
            assert session.preview._frame.recipe.to_dict() == session.recipe
            assert session.preview.url.startswith('image://editor-preview/')
            assert session.dirty and not session.request_close()
            token = session.revision
            assert session.flip(True, False)
            assert not session.request_close(discard=True, revision=token)
            assert session.compareOriginal(True)
            wait_until(lambda: session.state == 'ready')
            assert session.preview._frame.recipe.source_size.width == 120
            assert session.preview._frame.recipe.output_size is None
            assert session.dirty
            assert path.read_bytes() == original and path.stat().st_mtime_ns == stamp
            assert session.shutdown(discard=True, revision=session.revision)
            wait_until(lambda: session.state == 'closed' and not session.busy)
            print(json.dumps({'packaged_editor_session': True, 'draft_guarded': True,
                              'closed_after_reaping': True, 'module': edit_session.__file__}))
    finally:
        session.shutdown(discard=True, revision=session.revision)
        wait_until(lambda: session.state == 'closed' and not session.busy)
        session.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    main()
