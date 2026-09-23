from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event, get_ident
import time
import unittest
from unittest.mock import patch

from PIL import Image
from image_lab_ui.edit_process import prepare_source, render_source
from image_lab_ui.edit_protocol import EditWorkerError
from image_lab_ui.edit_recipe import EditRecipe

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
    from PySide6.QtGui import QGuiApplication
    from image_lab_ui.edit_session import EditorSession

ROOT = Path(__file__).resolve().parents[1]
FAULT = ROOT / 'tests/helpers/edit_worker_fault.py'


@unittest.skipUnless(HAS_QT, 'Install desktop extra for session tests')
class EditorSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'source.png'
        with Image.new('RGB', (120, 80), (100, 80, 60)) as image:
            image.save(self.path)
        self.session = EditorSession()
        self.addCleanup(self.cleanup_session)

    def wait(self, predicate, timeout=6000):
        if predicate():
            return
        loop = QEventLoop()
        poll = QTimer(); poll.setInterval(10)
        deadline = QTimer(); deadline.setSingleShot(True)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline.timeout.connect(loop.quit)
        poll.start(); deadline.start(timeout)
        loop.exec()
        poll.stop(); deadline.stop()
        poll.timeout.disconnect(); deadline.timeout.disconnect()
        self.assertTrue(predicate(), 'Session did not reach expected state before deadline')

    def cleanup_session(self):
        if self.session is not None:
            self.session.shutdown(discard=True, revision=self.session.revision)
            self.wait(lambda: self.session.state == 'closed' and not self.session.busy)
            self.session.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def open(self):
        self.assertTrue(self.session.open_source(str(self.path), color_policy='srgb-v1', assume_srgb=True))
        self.wait(lambda: self.session.state in ('ready', 'error'))
        self.assertEqual(self.session.state, 'ready', self.session.error)

    def test_open_and_commands_preserve_original_and_support_history(self):
        original, stamp = self.path.read_bytes(), self.path.stat().st_mtime_ns
        self.assertFalse(self.session.rotate())
        self.open()
        self.assertIs(self.session.property('preview'), self.session.preview)
        self.assertEqual(self.session.property('colorPolicy'), 'srgb-v1')
        self.assertTrue(self.session.property('assumeSrgb'))
        self.assertFalse(self.session.dirty)
        self.assertTrue(self.session.blocksExternalWork)
        self.assertTrue(self.session.crop(10, 10, 110, 70))
        self.assertTrue(self.session.rotate())
        self.assertTrue(self.session.flip(True, False))
        self.assertTrue(self.session.resizeWidth(30))
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.recipe['output_size'], [30, 50])
        self.assertTrue(self.session.dirty)
        self.assertTrue(self.session.canUndo)
        self.assertTrue(self.session.undo())
        self.assertTrue(self.session.canRedo)
        self.assertTrue(self.session.redo())
        self.assertTrue(self.session.reset())
        self.wait(lambda: self.session.state == 'ready')
        self.assertFalse(self.session.dirty)
        self.assertEqual(self.session.recipe, EditRecipe.original(120, 80).to_dict())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)

    def test_invalid_commands_and_upscale_consent_do_not_mutate_draft(self):
        self.open()
        original = self.session.recipe
        url = self.session.preview.url
        self.assertFalse(self.session.crop(0, 0, 999, 80))
        self.assertFalse(self.session.resizeWidth(240))
        self.assertEqual(self.session.errorCode, 'invalid_edit')
        self.assertEqual(self.session.recipe, original)
        self.assertEqual(self.session.preview.url, url)
        self.assertFalse(self.session.dirty)
        self.assertTrue(self.session.allowUpscale(True))
        self.assertTrue(self.session.resizeWidth(240))
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.recipe['output_size'], [240, 160])

    def test_dirty_close_and_navigation_require_explicit_discard(self):
        self.open()
        self.session.rotate()
        draft = self.session.recipe
        reasons = []
        self.session.transitionBlocked.connect(reasons.append)
        self.assertFalse(self.session.request_close())
        self.assertFalse(self.session.shutdown())
        self.assertFalse(self.session.open_source(str(self.path), color_policy='legacy-v1'))
        self.assertEqual(reasons, ['unsaved_edits'] * 3)
        self.assertEqual(self.session.recipe, draft)
        self.assertTrue(self.session.dirty)
        with self.assertRaises(ValueError):
            self.session.shutdown(discard=1)
        self.assertTrue(self.session.compareOriginal(True))  # Invalid shutdown did not dispose it.
        self.assertTrue(self.session.request_close(discard=True, revision=self.session.revision))
        self.wait(lambda: self.session.state == 'closed')
        self.assertFalse(self.session.blocksExternalWork)
        self.assertEqual(self.session.preview.url, '')
        self.assertEqual(self.session.recipe, {})
        self.open()  # Closing a document does not permanently dispose the controller.

    def test_stale_discard_confirmation_cannot_discard_newer_draft(self):
        self.open()
        self.session.rotate()
        revision = self.session.revision
        self.session.flip(True, False)
        draft = self.session.recipe
        reasons = []
        self.session.transitionBlocked.connect(reasons.append)
        self.assertFalse(self.session.request_close(discard=True, revision=revision))
        self.assertFalse(self.session.open_source(str(self.path), color_policy='legacy-v1', discard=True, revision=revision))
        self.assertFalse(self.session.shutdown(discard=True, revision=revision))
        self.assertFalse(self.session.request_close(discard=True))
        self.assertEqual(reasons, ['stale_confirmation'] * 4)
        self.assertEqual(self.session.recipe, draft)
        self.assertTrue(self.session.dirty)
        old_revision = self.session.revision
        self.assertTrue(self.session.request_close(discard=True, revision=old_revision))
        self.wait(lambda: self.session.state == 'closed')
        self.open()
        self.assertFalse(self.session.request_close(discard=True, revision=old_revision))
        self.assertEqual(self.session.state, 'ready')

    def test_original_comparison_does_not_change_recipe_or_dirty_state(self):
        self.open()
        self.session.rotate()
        draft = self.session.recipe
        self.assertTrue(self.session.compareOriginal(True))
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.preview._frame.recipe, EditRecipe.original(120, 80))
        self.assertEqual(self.session.recipe, draft)
        self.assertTrue(self.session.dirty)
        self.assertTrue(self.session.compareOriginal(False))
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.preview._frame.recipe.to_dict(), draft)
        self.assertTrue(self.session.undo())
        self.assertFalse(self.session.dirty)

    def test_policy_choice_is_explicit_and_remains_dirty_after_geometry_reset(self):
        self.assertTrue(self.session.open_source(str(self.path), color_policy='srgb-v1'))
        self.wait(lambda: self.session.state == 'error')
        self.assertEqual(self.session.errorCode, 'unknown_color_space')
        self.assertFalse(self.session.dirty)
        self.assertTrue(self.session.set_color_policy('srgb-v1', True))
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.preview._frame.color.status, 'assumed_srgb')
        self.assertTrue(self.session.dirty)
        self.session.rotate(); self.session.reset()
        self.assertTrue(self.session.dirty)
        self.assertTrue(self.session.set_color_policy('legacy-v1'))
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.preview._frame.color.status, 'unmanaged')
        self.assertTrue(self.session.dirty)

    def test_one_active_job_and_latest_only_pending_recipe(self):
        self.open()
        entered, released = Event(), Event()
        recipes, active, peak = [], [0], [0]
        main_thread = get_ident()
        def slow(source, recipe, **kwargs):
            self.assertNotEqual(get_ident(), main_thread)
            active[0] += 1; peak[0] = max(peak[0], active[0])
            recipes.append(recipe)
            try:
                if len(recipes) == 1:
                    entered.set()
                    while not released.wait(0.005):
                        if kwargs['cancelled']():
                            # Simulate an already-completed old response too: the
                            # controller must reject it even if cancellation loses.
                            return render_source(source, recipe, **dict(kwargs, cancelled=lambda: False))
                return render_source(source, recipe, **kwargs)
            finally:
                active[0] -= 1
        with patch('image_lab_ui.edit_session.render_source', side_effect=slow):
            self.session.rotate()
            self.wait(entered.is_set)
            for width in range(10, 31):
                self.assertTrue(self.session.resizeWidth(width))
            final = self.session.recipe
            released.set()
            self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(peak[0], 1)
        self.assertEqual(len(recipes), 2)
        self.assertEqual(self.session.preview._frame.recipe.to_dict(), final)
        self.assertEqual(recipes[-1].to_dict(), final)

    def test_prepare_is_off_qt_thread_and_superseded_load_cannot_replace_source(self):
        entered, release = Event(), Event()
        other = Path(self.temp.name) / 'other.png'
        with Image.new('RGB', (40, 60), 'blue') as image:
            image.save(other)
        main_thread = get_ident()
        paths = []
        def slow(path, **kwargs):
            self.assertNotEqual(get_ident(), main_thread)
            paths.append(path)
            if len(paths) == 1:
                entered.set()
                release.wait(3)
                return prepare_source(path)  # Deliberately ignore cancellation.
            return prepare_source(path, **kwargs)
        with patch('image_lab_ui.edit_session.prepare_source', side_effect=slow):
            self.session.open_source(str(self.path), color_policy='legacy-v1')
            self.wait(entered.is_set)
            self.session.open_source(str(other), color_policy='legacy-v1')
            self.assertEqual(self.session.state, 'opening')
            release.set()
            self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.recipe['source_size'], [40, 60])
        self.assertEqual(self.session.preview._frame.source.path, str(other))

    def test_close_reaps_real_stalled_child_without_blocking_qt(self):
        self.open()
        processes = []
        real = subprocess.Popen
        def launch(command, **kwargs):
            process = real([sys.executable, str(FAULT), 'hang'], **kwargs)
            processes.append(process)
            return process
        with patch('image_lab_ui.edit_process.subprocess.Popen', side_effect=launch):
            self.session.rotate()
            self.wait(lambda: bool(processes))
            start = time.monotonic()
            self.assertTrue(self.session.request_close(discard=True, revision=self.session.revision))
            self.assertLess(time.monotonic() - start, 0.1)
            self.wait(lambda: self.session.state == 'closed')
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)
        self.assertFalse(self.session.busy)

    def test_preview_publication_failure_preserves_draft_and_can_retry(self):
        self.open()
        with patch.object(self.session.preview, 'publish', side_effect=ValueError('Qt allocation failed')):
            self.session.rotate()
            draft = self.session.recipe
            self.wait(lambda: self.session.state == 'error')
            self.assertEqual(self.session.errorCode, 'preview_failed')
            self.assertEqual(self.session.recipe, draft)
            self.assertTrue(self.session.dirty)
            self.assertFalse(self.session.busy)
        self.assertTrue(self.session.refresh())
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.preview._frame.recipe.to_dict(), draft)

    def test_source_change_preserves_draft_and_never_rebases_implicitly(self):
        self.open()
        self.session.rotate()
        self.wait(lambda: self.session.state == 'ready')
        draft = self.session.recipe
        with Image.new('RGB', (40, 60), 'green') as image:
            image.save(self.path)
        self.session.refresh()
        self.wait(lambda: self.session.state == 'error')
        self.assertEqual(self.session.errorCode, 'source_changed')
        self.assertEqual(self.session.recipe, draft)
        self.assertTrue(self.session.dirty)
        self.assertFalse(self.session.open_source(str(self.path), color_policy='legacy-v1'))
        self.assertTrue(self.session.open_source(str(self.path), color_policy='legacy-v1', discard=True, revision=self.session.revision))
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.recipe['source_size'], [40, 60])
        self.assertFalse(self.session.dirty)

    def test_external_work_guard_and_owner_thread_commands(self):
        self.session._work_active = lambda: True
        self.assertFalse(self.session.open_source(str(self.path), color_policy='legacy-v1'))
        self.assertEqual(self.session.state, 'closed')
        self.session._work_active = lambda: False
        self.open()
        self.session.rotate()
        draft = self.session.recipe
        self.session._work_active = lambda: True
        self.assertFalse(self.session.open_source(str(self.path), color_policy='legacy-v1', discard=True))
        self.assertEqual(self.session.recipe, draft)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(RuntimeError):
                pool.submit(self.session.rotate).result(timeout=2)

    def test_cancel_preserves_draft_and_refresh_resumes(self):
        self.open()
        self.session.rotate()
        draft = self.session.recipe
        self.assertTrue(self.session.cancelPreview())
        self.wait(lambda: not self.session.busy)
        self.assertEqual(self.session.state, 'idle')
        self.assertEqual(self.session.preview.url, '')
        self.assertEqual(self.session.recipe, draft)
        self.assertTrue(self.session.dirty)
        self.assertTrue(self.session.refresh())
        self.wait(lambda: self.session.state == 'ready')
        self.assertEqual(self.session.preview._frame.recipe.to_dict(), draft)

    def test_qobject_destruction_cancels_without_worker_callback_into_qt(self):
        self.open()
        processes = []
        real = subprocess.Popen
        def launch(command, **kwargs):
            process = real([sys.executable, str(FAULT), 'hang'], **kwargs)
            processes.append(process)
            return process
        with patch('image_lab_ui.edit_process.subprocess.Popen', side_effect=launch):
            self.session.rotate()
            self.wait(lambda: bool(processes))
            runner = self.session._runner
            self.session.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.session = None
            self.wait(runner.future.done)
            with self.assertRaises(EditWorkerError):
                runner.future.result()
        self.assertIsNotNone(processes[0].poll())


if __name__ == '__main__':
    unittest.main()
