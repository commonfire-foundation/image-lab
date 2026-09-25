"""Qt Quick shell; slow disk and inference work runs on a single worker thread."""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from PySide6.QtCore import (QAbstractListModel, QEvent, QModelIndex, QObject, Property,
                            QThread, QTimer, QLockFile, Qt, QUrl, Signal, Slot)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .analyzer_client import DEFAULT_COMMAND, analyzer_identity, run_analyzer
from .records import legacy_record
from .naming import suggest_names
from .preferences import load_preferences, save_preferences
from .metadata import edit_revision, effective_details
from .renaming import FilenameConflict
from .catalog import Catalog
from .viewer_metadata import ViewerMetadata
from .viewer_measurements import ViewerMeasurements
from .queue import JobQueue
from .edit_session import EditorSession
from .storage import storage_paths
from .omarchy_palette import OmarchyPalette, qt_palette


# Cyclic PySide wrappers can otherwise be finalized by CPython's collector on
# whichever Python-backed QThread happens to allocate next. Track *all*
# controllers, not just one, so an idle controller cannot re-enable collection
# while another controller's worker is still running.
_python_workers_active = 0
_python_workers_restore_gc = False


def view_record(row):
    if not row:
        return {}
    result = json.loads(row["prediction"]) if row["prediction"] else {}
    vision = effective_details(row)
    return {"imageId": row["id"], "name": Path(row["path"]).name, "path": row["path"],
            "thumbnail": QUrl.fromLocalFile(row["thumbnail"]).toString(),
            "preview": QUrl.fromLocalFile(row["path"]).toString(),
            "isGif": Path(row['path']).suffix.lower() == '.gif',
            "pixelWidth": row['width'], "pixelHeight": row['height'],
            "dimensions": f'{row["width"]} × {row["height"]}',
            "analyzed": bool(vision), "caption": vision.get("caption", ""),
            "userEdited": bool(json.loads(row.get('user_edits', '{}'))),
            "editRevision": edit_revision(row),
            "fileRevision": f'{row["mtime"]}:{row["bytes"]}',
            "moodEntries": vision.get('mood', []), "compositionEntries": vision.get('composition', []),
            "medium": vision.get("medium", "" if vision else "Not analyzed"), "error": row["error"],
            "tags": vision.get("tags", []), "composition": ", ".join(vision.get("composition", [])),
            "mood": ", ".join(vision.get("mood", [])),
            "textPresent": vision.get("text_present", False),
            "watermarkPresent": vision.get("watermark_present", False),
            "elapsed": str(result.get("elapsed_seconds", ""))}


class GalleryModel(QAbstractListModel):
    roles = ["imageId", "name", "thumbnail", "dimensions", "analyzed", "checked", "preview", "isGif", "pixelWidth", "pixelHeight"]

    def __init__(self, catalog):
        super().__init__()
        self.catalog = catalog
        self.items = []
        self.checked = set()
        self.query = ""
        self.status_filter = 'all'
        self.counts = {}
        self.total = 0
        self.reload()

    def roleNames(self):
        return {Qt.UserRole + i + 1: role.encode() for i, role in enumerate(self.roles)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        name = self.roleNames().get(role)
        if name == b"checked":
            return self.items[index.row()]["imageId"] in self.checked
        return self.items[index.row()].get(name.decode()) if name else None

    def set_checked(self, ids):
        self.checked = set(ids)
        if self.items:
            self.dataChanged.emit(self.index(0), self.index(len(self.items) - 1),
                                  [Qt.UserRole + self.roles.index("checked") + 1])

    def refresh_loaded(self):
        # Analysis can change search membership, but never the path ordering.
        # Reconcile the loaded prefix without resetting/recreating every delegate.
        self.counts = self.catalog.status_counts(self.query)
        self.total = self.counts[self.status_filter]
        if self.checked and (self.query or self.status_filter != 'all'):
            self.checked.intersection_update(self.catalog.matching_ids(self.query, status=self.status_filter))
        updated = [view_record(row) for row in self.catalog.rows(
            self.query, limit=max(120, len(self.items)), status=self.status_filter)]
        wanted = {item['imageId'] for item in updated}
        for row in range(len(self.items) - 1, -1, -1):
            if self.items[row]['imageId'] not in wanted:
                self.beginRemoveRows(QModelIndex(), row, row)
                del self.items[row]
                self.endRemoveRows()
        for row, item in enumerate(updated):
            if row == len(self.items) or self.items[row]['imageId'] != item['imageId']:
                self.beginInsertRows(QModelIndex(), row, row)
                self.items.insert(row, item)
                self.endInsertRows()
                continue
            previous = self.items[row]
            roles = [Qt.UserRole + i + 1 for i, name in enumerate(self.roles)
                     if name != 'checked' and previous.get(name) != item.get(name)]
            self.items[row] = item
            if roles:
                self.dataChanged.emit(self.index(row), self.index(row), roles)

    def reload(self, query=None, status=None):
        if status is not None:
            if status not in self.catalog.FILTERS:
                raise ValueError('Unknown library filter')
            self.status_filter = status
        if query is not None:
            self.query = query
        self.beginResetModel()
        self.counts = self.catalog.status_counts(self.query)
        self.total = self.counts[self.status_filter]
        self.items = [view_record(row) for row in self.catalog.rows(self.query, status=self.status_filter)]
        self.endResetModel()

    def canFetchMore(self, parent=QModelIndex()):
        return not parent.isValid() and len(self.items) < self.total

    def fetchMore(self, parent=QModelIndex()):
        if not self.canFetchMore(parent):
            return
        rows = self.catalog.rows(self.query, len(self.items), status=self.status_filter)
        if not rows:
            return
        start = len(self.items)
        self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
        self.items.extend(view_record(row) for row in rows)
        self.endInsertRows()


class Worker(QObject):
    status = Signal(str)
    phase = Signal(int, str)
    outcome = Signal(bool)
    finished = Signal(str)

    def __init__(self, directory, kind, target, job=None, thumbnail_directory=None, analyzer_command=DEFAULT_COMMAND):
        super().__init__()
        self.directory, self.kind, self.target = directory, kind, target
        self.job = job
        self.analyzer_command = analyzer_command
        self.thumbnail_directory = thumbnail_directory

    @Slot()
    def run(self):
        catalog = None
        success = False
        queue = None
        started = time.perf_counter()
        try:
            catalog = Catalog(self.directory, self.thumbnail_directory)
            if self.job:
                queue = JobQueue(catalog)
            if self.kind == "scan":
                count, errors, stopped = catalog.scan(
                    self.target, QThread.currentThread().isInterruptionRequested,
                    lambda n, e: self.status.emit(f"Scanning · {n} images · {e} unreadable"))
                message = f"{'Scan stopped' if stopped else 'Scan complete'} · {count} images · {errors} unreadable"
            else:
                row = catalog.get(self.target)
                if not row:
                    raise ValueError("Image is no longer in the catalog")
                fingerprint = (row["mtime"], row["bytes"])
                identity = self.job or analyzer_identity(self.analyzer_command)
                if self.job:
                    fingerprint = (self.job['mtime'], self.job['bytes'])
                if catalog.fingerprint(row["path"]) != fingerprint or (row['mtime'], row['bytes']) != fingerprint:
                    raise ValueError("Image changed; rescan its folder first")
                try:
                    result = run_analyzer(row['path'], identity, self.phase.emit,
                        command=self.analyzer_command,
                        interrupted=QThread.currentThread().isInterruptionRequested)
                    self.phase.emit(3, "Saving predictions")
                    result = legacy_record(result, row['path'])
                    if queue:
                        result['job_id'] = self.job['id']
                        queue.succeed(self.job['id'], result)
                    else:
                        catalog.store_result(self.target, fingerprint, result)
                except Exception as exc:
                    if not queue:
                        catalog.store_result(self.target, fingerprint, error=str(exc))
                    raise
                message = f"Tags ready · {result['elapsed_seconds']}s · predictions need review"
            success = True
        except Exception as exc:
            message = f"Could not {self.kind}: {exc}"
            if queue:
                try:
                    queue.fail(self.job['id'], str(exc), round(time.perf_counter() - started, 2))
                except Exception as queue_error:
                    message += f"; queue could not save failure: {queue_error}"
        finally:
            if catalog:
                catalog.close()
        self.outcome.emit(success)
        self.finished.emit(message)


class SubmissionWorker(QObject):
    result = Signal(object, str)
    finished = Signal()

    def __init__(self, directory, thumbnails, command, ids, replace):
        super().__init__()
        self.directory, self.thumbnails, self.command = directory, thumbnails, command
        self.ids, self.replace = ids, replace

    @Slot()
    def run(self):
        catalog = None
        try:
            catalog = Catalog(self.directory, self.thumbnails)
            batch_id = JobQueue(catalog, self.command).enqueue(self.ids, self.replace)
            self.result.emit(batch_id, '' if batch_id is not None else
                             'Nothing added · images are already queued or have tags')
        except Exception as exc:
            self.result.emit(None, f'Could not add to queue: {exc}')
        finally:
            if catalog:
                catalog.close()
            self.finished.emit()


class Controller(QObject):
    changed = Signal()
    progressChanged = Signal()
    themeChanged = Signal()
    settingsChanged = Signal()
    uiAction = Signal(str, int)
    uiStateChanged = Signal()
    submissionResult = Signal(object, str)
    workCompleted = Signal(str, bool, bool, str)

    def __init__(self, directory, thumbnail_directory=None, analyzer_command=DEFAULT_COMMAND, theme_paths=None):
        super().__init__()
        self.omarchy_palette = OmarchyPalette(self, paths=theme_paths)
        self.omarchy_palette.changed.connect(self.themeChanged.emit)
        self.catalog = Catalog(directory, thumbnail_directory)
        self._ui_state = {}
        self._work_success = False
        self._scan_cancelled = False
        self._settings = load_preferences(self.catalog.db)
        self.model = GalleryModel(self.catalog)
        self._viewer_metadata = ViewerMetadata(self)
        self._viewer_measurements = ViewerMeasurements(self)
        self.analyzer_command = analyzer_command
        self.queue = JobQueue(self.catalog, analyzer_command)
        self.queue.recover()
        self._batch_id = self.queue.latest()
        self._batch = self.queue.summary(self._batch_id)
        self._status = (f"{self.model.total} images in your local catalog · select one to inspect"
                        if self.model.total else "Choose a folder to build your local contact sheet")
        if self._batch.get('queued'):
            self._status = "Unfinished queue found · choose Resume to continue"
        self._selected = {}
        self.thread = None
        self.worker = None
        self.submission_thread = self.submission_worker = None
        self._submitting = False
        self._active_python_workers = 0
        self._close_requested = False
        self._selected_state = ''
        self._queue_page = 0
        self._queue_entries = self.queue.entries()
        self._queue_count = self.queue.entry_count()
        self._busy = False
        self._kind = ""
        self._progress = {}
        self._started_at = 0
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.tick)
        self._editor_record = {}
        self._editor = EditorSession(self, work_active=self._editing_work_active,
                                     export_catalog=(str(self.catalog.directory), str(self.catalog.thumbnails)))
        self._editor.changed.connect(self.changed.emit)
        self._editor.closed.connect(self._editor_closed)
        self._editor.exportFinished.connect(self._export_finished)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Quit and not self.canClose:
            self.uiAction.emit('window.close', 0)
            return True
        return super().eventFilter(watched, event)

    def _begin_python_worker(self):
        global _python_workers_active, _python_workers_restore_gc
        # These methods run on the GUI thread. Collect GUI-affine Qt wrappers
        # here, never from the Python slot running in a worker QThread.
        if not _python_workers_active:
            _python_workers_restore_gc = gc.isenabled()
            if _python_workers_restore_gc:
                gc.collect()
                gc.disable()
        _python_workers_active += 1
        self._active_python_workers += 1

    def _end_python_worker(self):
        global _python_workers_active, _python_workers_restore_gc
        self._active_python_workers -= 1
        _python_workers_active -= 1
        if not _python_workers_active and _python_workers_restore_gc:
            gc.collect()
            gc.enable()
            _python_workers_restore_gc = False

    def _editing_work_active(self):
        return self.busy or bool(self._batch.get('queued') or self._batch.get('running'))

    @Property(QObject, constant=True)
    def editor(self):
        return self._editor

    @Property(bool, notify=changed)
    def editorActive(self):
        return self._editor.blocksExternalWork

    @Property('QVariantMap', notify=changed)
    def editorRecord(self):
        return dict(self._editor_record)

    @Property(bool, notify=changed)
    def canOpenEditor(self):
        return not self.editorActive and not self._editing_work_active()

    @Slot()
    def prepareWindowClose(self):
        self._close_requested = True
        if not self.editorActive:
            self.pauseBatch()  # Preserve waiting jobs, rather than clearing them.
            if self.scanning: self.stopScan()

    @Slot()
    def cancelWindowClose(self):
        self._close_requested = False

    @Property(str, notify=changed)
    def editorBlockedReason(self):
        if self.editorActive:
            return 'Close the current editing session first.'
        queued = self._batch.get('queued', 0)
        if queued:
            return f'Editing blocked: {queued:,} queued images. Finish or clear the queue first; pausing does not release it.'
        if self._editing_work_active():
            return 'Editing blocked: wait for active scanning or analysis to finish.'
        return ''

    @Slot(int, result=bool)
    def openEditor(self, image_id):
        if not self.canOpenEditor:
            self.setStatus(self.editorBlockedReason)
            return False
        row = self.catalog.get(image_id)
        if row is None:
            self.setStatus('This image is no longer in the library.')
            return False
        self._editor_record = view_record(row)
        self._viewer_metadata.request(None)
        self._viewer_measurements.request(None)
        # Missing RGB/RGBA tags use a disclosed sRGB default after source inspection.
        # Embedded/broken profiles still take precedence; originals are never retagged.
        return self._editor.open_source(row['path'], color_policy='srgb-v1', assume_untagged=True)

    @Slot(bool, int, result=bool)
    def closeEditor(self, discard, revision):
        return self._editor.request_close(discard=discard, revision=revision)

    @Slot(str, str, str, int, bool, str, bool, int, result=bool)
    def exportEditorCopy(self, folder, name, format, quality, lossless, matte, add_to_library, revision):
        from .export_publication import export_name
        if revision != self._editor.revision:
            self.setStatus('The editing session changed. Reopen Export copy to export the current edits.')
            return False
        try:
            if folder.startswith('file:'):
                folder = QUrl(folder).toLocalFile()
            if not Path(folder).is_absolute(): raise ValueError('Choose an absolute destination folder.')
            export_name(name, format)
            accepted = self._editor.export_copy(str(Path(folder) / name),
                {'format': format, 'quality': quality, 'lossless': lossless,
                 'matte': matte if format == 'JPEG' and matte else None}, add_to_library=add_to_library)
            if not accepted:
                self.setStatus('Wait for a ready sRGB preview and turn off original comparison before exporting.')
            return accepted
        except (ValueError, TypeError) as error:
            self.setStatus(str(error))
            return False

    def _export_finished(self, result):
        if result.get('imported'):
            self.model.refresh_loaded()
        if result.get('published'):
            self.setStatus(result.get('import_error') or '; '.join(result.get('warnings', [])) or ('Copy saved: ' + result['path']))
        else:
            self.setStatus('Publication is uncertain; inspect the destination before retrying.')
        self.changed.emit()

    def _editor_closed(self):
        self._editor_record = {}
        self.changed.emit()

    @Slot('QVariantMap')
    def reportUiState(self, state):
        if state != self._ui_state:
            self._ui_state = dict(state)
            self.uiStateChanged.emit()

    @Property(bool, notify=changed)
    def canClose(self):
        return not self.busy and not self.editorActive

    @Property('QVariantMap', notify=settingsChanged)
    def settings(self):
        return dict(self._settings)

    @Slot('QVariantMap', result='QVariantMap')
    def saveSettings(self, values):
        if self.editorActive:
            return {'ok': False, 'error': 'Close the image editor before changing settings.'}
        try:
            save_preferences(self.catalog.db, values)
        except (ValueError, sqlite3.Error) as error:
            return {'ok': False, 'error': str(error)}
        self._settings = dict(values)
        self.settingsChanged.emit()
        return {'ok': True, 'error': ''}

    @Property('QVariantMap', notify=themeChanged)
    def themeColors(self):
        return dict(self.omarchy_palette.colors)

    @Property("QVariantMap", notify=changed)
    def batch(self):
        return dict(self._batch)

    @Property(int, notify=changed)
    def checkedCount(self):
        return len(self.model.checked)

    @Property(bool, notify=changed)
    def canQueue(self):
        return not self.editorActive and not self.scanning and not self._submitting

    @Property(bool, notify=changed)
    def submitting(self):
        return self._submitting

    @Property(bool, notify=changed)
    def canImport(self):
        return not self.editorActive and not self.busy and not (self._batch.get('queued', 0) or self._batch.get('running', 0))

    @Property(str, notify=changed)
    def selectedState(self):
        return self._selected_state

    @Property('QVariantList', notify=changed)
    def queueEntries(self):
        return self._queue_entries

    @Property(int, notify=changed)
    def queuePage(self):
        return self._queue_page

    @Property(int, notify=changed)
    def queuePages(self):
        return max(1, (self._queue_count + 49) // 50)

    @Property('QVariantMap', notify=progressChanged)
    def queueProgress(self):
        return dict(self._progress)

    @Slot(int)
    def showQueuePage(self, page):
        self._queue_page = max(0, min(page, self.queuePages - 1))
        self.refreshBatch()

    def refreshBatch(self):
        self._batch = self.queue.summary(self._batch_id)
        self._queue_count = self.queue.entry_count()
        self._queue_page = min(self._queue_page, self.queuePages - 1)
        self._queue_entries = self.queue.entries(offset=self._queue_page * 50)
        self._selected_state = self.queue.image_state(self._selected.get('imageId'))
        self.changed.emit()

    @Slot(int)
    def toggleChecked(self, image_id):
        if self.editorActive:
            return
        self.model.set_checked(self.model.checked ^ {image_id})
        self.changed.emit()

    @Slot()
    def selectMatches(self):
        if self.editorActive:
            return
        self.model.set_checked(self.catalog.matching_ids(self.model.query, status=self.model.status_filter))
        self.changed.emit()

    @Slot()
    def clearChecked(self):
        if self.editorActive:
            return
        self.model.set_checked([])
        self.changed.emit()

    def enqueue(self, ids, replace=False):
        if not self.canQueue:
            return
        self._submitting = True
        self._begin_python_worker()
        self.setStatus('Adding images to queue…')
        self.submission_thread = QThread(self)
        self.submission_worker = SubmissionWorker(self.catalog.directory, self.catalog.thumbnails,
                                                  self.analyzer_command, list(ids), replace)
        self.submission_worker.moveToThread(self.submission_thread)
        self.submission_thread.started.connect(self.submission_worker.run)
        self.submission_worker.result.connect(self.submitted)
        self.submission_worker.finished.connect(self.submission_thread.quit)
        self.submission_worker.finished.connect(self.submission_worker.deleteLater)
        self.submission_thread.finished.connect(self.submissionComplete)
        self.submission_thread.start()

    @Slot(object, str)
    def submitted(self, batch_id, error):
        if batch_id is not None:
            self._batch_id = batch_id
        self.refreshBatch()
        self.setStatus(error or ('Added to queue · paused' if self._batch.get('state') == 'paused' else 'Added to queue'))
        self.submissionResult.emit(batch_id, error)

    @Slot()
    def submissionComplete(self):
        self.submission_thread.deleteLater()
        self.submission_thread = self.submission_worker = None
        self._submitting = False
        if self._close_requested: self.pauseBatch()
        self.runNext()
        self._end_python_worker()
        self.changed.emit()

    @Slot(int)
    def removeQueued(self, job_id):
        if not self.editorActive and not self._submitting:
            self.queue.remove(job_id)
            self.refreshBatch()

    @Slot(int)
    def retryJob(self, job_id):
        job = self.queue.get(job_id)
        if job and job['state'] == 'failed' and self.queue.image_state(job['image_id']) == 'failed':
            self.enqueue([job['image_id']], replace=True)

    @Slot()
    def generateSelected(self):
        self.enqueue(sorted(self.model.checked))

    @Slot()
    def regenerateSelected(self):
        self.enqueue(sorted(self.model.checked), replace=True)

    @Slot()
    def generateMissing(self):
        self.enqueue(self.catalog.matching_ids(self.model.query, missing=True, status=self.model.status_filter))

    @Slot()
    def pauseBatch(self):
        if self.editorActive:
            return
        self.queue.pause(self._batch_id)
        self.refreshBatch()
        self.setStatus("Pausing after current image" if self._busy else "Queue paused")

    @Slot()
    def resumeBatch(self):
        if self.editorActive or self._submitting or self.scanning:
            return
        self.queue.resume(self._batch_id)
        self.refreshBatch()
        self.runNext()

    @Slot()
    def stopBatch(self):
        if self.editorActive:
            return
        self.queue.stop(self._batch_id)
        self.refreshBatch()
        self.setStatus("Waiting items cleared · current image will finish" if self.busy else "Waiting items cleared")

    @Slot()
    def retryFailed(self):
        if self.canQueue:
            self.enqueue(self.queue.failed_ids(self._batch_id), replace=True)

    @Slot()
    def runNext(self):
        if self._close_requested or self.editorActive or self.busy or self._batch.get('state') != 'running':
            return
        job = self.queue.claim(self._batch_id)
        if job:
            self.start('analyze', job['image_id'], job)
            self.refreshBatch()
        else:
            self.queue.settle(self._batch_id)
            self.refreshBatch()

    @Property("QVariantMap", notify=progressChanged)
    def progress(self):
        if not self._selected or self._progress.get("imageId") != self._selected.get("imageId"):
            return {}
        return dict(self._progress)

    @Slot()
    def tick(self):
        if self._progress.get("running"):
            self._progress["seconds"] = round(time.monotonic() - self._started_at, 1)
            self.progressChanged.emit()

    @Slot(int, str)
    def setPhase(self, stage, label):
        self._progress.update(stage=stage, label=label)
        self.progressChanged.emit()

    @Slot(bool)
    def setOutcome(self, success):
        self._work_success = success
        if self._kind == "analyze":
            self.tick()
            self._timer.stop()
            self._progress.update(running=False, success=success,
                                  stage=4 if success else self._progress.get("stage", 0),
                                  label="Tags ready" if success else "Analysis failed")
            self.progressChanged.emit()

    @Property(bool, notify=changed)
    def scanning(self):
        return self._busy and self._kind == "scan"

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy or self._submitting

    @Property(str, notify=changed)
    def viewQuery(self):
        return self.model.query

    @Property(str, notify=changed)
    def libraryFilter(self):
        return self.model.status_filter

    @Property('QVariantMap', notify=changed)
    def filterCounts(self):
        return dict(self.model.counts)

    @Slot(str)
    def setLibraryFilter(self, status):
        if self.editorActive:
            return
        if status not in self.catalog.FILTERS or status == self.model.status_filter:
            return
        self.model.set_checked([])
        self.model.reload(status=status)
        if not self.model.total:
            self._selected = {}
            self._selected_state = ''
        self.changed.emit()
        self.progressChanged.emit()

    @Property(int, notify=changed)
    def total(self):
        return self.model.total

    @Property("QVariantMap", notify=changed)
    def selected(self):
        return self._selected

    @Slot(result='QVariantList')
    def checkedImageIds(self):
        return sorted(self.model.checked)

    @Slot('QVariantList', result='QVariantMap')
    def removeImages(self, image_ids):
        if self.editorActive:
            return {'ok': False, 'error': 'Close the image editor before removing library images.'}
        if self.scanning or self._submitting:
            return {'ok': False, 'error': 'Wait for scanning or queue submission to finish before removing images.'}
        selected_id = self._selected.get('imageId')
        try:
            count = self.catalog.remove_images(image_ids)
        except (ValueError, sqlite3.Error) as error:
            return {'ok': False, 'error': str(error)}
        self.model.set_checked(self.model.checked.difference(image_ids))
        self.model.reload()
        # Model resets can move keyboard focus; retain the inspected image unless removed.
        self._selected = view_record(self.catalog.get(selected_id))
        if self._progress.get('imageId') in image_ids:
            self._progress = {}
        self._status = f'Removed {count} image' + ('s' if count != 1 else '') + ' from library · original files kept'
        self.refreshBatch()
        self.progressChanged.emit()
        return {'ok': True, 'error': '', 'count': count}

    def _can_change_image(self, image_id):
        # A queued/running source belongs to the analyzer. Other records can
        # change during inference, but not while scanning or submitting a batch
        # (before its target IDs have been reserved).
        return (not self.editorActive and not self.scanning and not self._submitting
                and self.queue.image_state(image_id) not in ('queued', 'running'))

    @Property(bool, notify=changed)
    def canEditDetails(self):
        image_id = self._selected.get('imageId')
        return bool(self._selected.get('analyzed')) and bool(image_id) and self._can_change_image(image_id)

    @Property(QObject, constant=True)
    def viewerMetadata(self):
        return self._viewer_metadata

    @Property(QObject, constant=True)
    def viewerMeasurements(self):
        return self._viewer_measurements

    @Slot(int)
    def inspectImageMeasurements(self, image_id):
        if self.editorActive and image_id > 0:
            return
        self._viewer_measurements.request(self.catalog.get(image_id) if image_id > 0 else None)

    @Slot(int)
    def inspectImageFile(self, image_id):
        if self.editorActive and image_id > 0:
            return
        self._viewer_measurements.request(None)
        self._viewer_metadata.request(self.catalog.get(image_id) if image_id > 0 else None)

    @Slot(int, result='QVariantMap')
    def imageDetails(self, image_id):
        return view_record(self.catalog.get(image_id))

    @Slot(result='QVariantMap')
    def detailsForEditing(self):
        return view_record(self.catalog.get(self._selected.get('imageId')))

    @Slot(int, str, 'QVariantMap', result='QVariantMap')
    def saveImageDetails(self, image_id, revision, values):
        if not self.canEditDetails:
            return {'ok': False, 'error': 'Finish scanning or submission, or wait for this image’s queued analysis.'}
        if self._selected.get('imageId') != image_id:
            return {'ok': False, 'error': 'Selection changed. Reopen the editor.'}
        return self.updateImageDetails(image_id, revision, values)

    def updateImageDetails(self, image_id, revision, values):
        """Selection-independent edit shared by QML's guarded wrapper and IPC."""
        if not self._can_change_image(image_id):
            return {'ok': False, 'error': 'Finish scanning or submission, or wait for this image’s queued analysis.'}
        try:
            self.catalog.save_details(image_id, revision, values)
        except (OSError, ValueError, sqlite3.Error) as error:
            return {'ok': False, 'error': str(error)}
        self.model.reload()
        self.model.set_checked(self.model.checked.intersection(self.catalog.matching_ids(self.model.query, status=self.model.status_filter)))
        if self._selected.get('imageId') == image_id:
            self._selected = view_record(self.catalog.get(image_id))
        self._status = 'Image details saved'
        self.changed.emit()
        return {'ok': True, 'error': ''}

    @Property(bool, notify=changed)
    def canRename(self):
        image_id = self._selected.get('imageId')
        return bool(image_id) and self._can_change_image(image_id)

    @Slot(int, str, str, result='QVariantMap')
    def renameImage(self, image_id, expected_path, name):
        if not self.canRename:
            return {'ok': False, 'error': 'Finish scanning or submission, or wait for this image’s queued analysis.'}
        if self._selected.get('imageId') != image_id or self._selected.get('path') != expected_path:
            return {'ok': False, 'error': 'Selection changed. Reopen the naming dialog.'}
        return self.renameById(image_id, expected_path, name)

    def renameById(self, image_id, expected_path, name):
        """Selection-independent rename; filesystem guards remain in Catalog."""
        if not self._can_change_image(image_id):
            return {'ok': False, 'error': 'Finish scanning or submission, or wait for this image’s queued analysis.'}
        try:
            new_path = self.catalog.rename_image(image_id, expected_path, name)
        except (FileExistsError, FilenameConflict):
            try:
                alternative = self.catalog.alternate_name(expected_path, name)
            except (OSError, ValueError, sqlite3.Error):
                alternative = ''
            return {'ok': False, 'error': 'That filename already exists or is reserved in the catalog. Choose another name.',
                    'alternative': alternative}
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            return {'ok': False, 'error': str(error)}
        self.model.reload()
        self.model.set_checked(self.model.checked.intersection(self.catalog.matching_ids(self.model.query, status=self.model.status_filter)))
        if self._selected.get('imageId') == image_id:
            self._selected = view_record(self.catalog.get(image_id))
        self._status = f'Renamed to {Path(new_path).name}'
        self.refreshBatch()
        self.progressChanged.emit()
        return {'ok': True, 'error': ''}

    @Slot(result='QVariantList')
    def suggestNames(self):
        return suggest_names(self._selected)

    @Slot(str)
    def copySuggestedName(self, name):
        # Copy only: no filesystem or catalog mutation.
        QGuiApplication.clipboard().setText(name)

    @Slot(int)
    def select(self, image_id):
        if self.editorActive:
            return
        self._selected = view_record(self.catalog.get(image_id))
        self._selected_state = self.queue.image_state(image_id)
        self.changed.emit()
        self.progressChanged.emit()

    @Slot(str)
    def search(self, query):
        if self.editorActive:
            return
        self.model.set_checked([])
        self.model.reload(query)
        if not self.model.total:
            self._selected = {}
            self._selected_state = ''
        self.changed.emit()
        self.progressChanged.emit()

    @Slot(str, result='QVariantMap')
    def resolveFolder(self, location):
        """Validate a browser location without scanning or changing the catalog."""
        try:
            url = QUrl(location)
            path = Path(url.toLocalFile() if url.isLocalFile() else location).expanduser()
            if not path.is_absolute() or not path.is_dir():
                return {'ok': False, 'error': 'Enter the full path to an existing folder.'}
            if not os.access(path, os.R_OK | os.X_OK):
                return {'ok': False, 'error': 'This folder cannot be opened. Choose a readable folder.'}
            return {'ok': True, 'url': QUrl.fromLocalFile(str(path)).toString(), 'path': str(path)}
        except (OSError, ValueError):
            return {'ok': False, 'error': 'This folder cannot be opened. Check the path and try again.'}

    @Slot(QUrl)
    def importFolder(self, url):
        if url.isLocalFile() and self.canImport:
            self.start("scan", url.toLocalFile())

    @Slot()
    def analyze(self):
        if self._selected:
            self.enqueue([self._selected["imageId"]], replace=True)

    @Slot()
    def stopScan(self):
        if self.thread and self._kind == "scan":
            self._scan_cancelled = True
            self.thread.requestInterruption()
            self.setStatus("Stopping scan after the current image…")

    @Slot(str)
    def setStatus(self, message):
        self._status = message
        self.changed.emit()

    def start(self, kind, target, job=None):
        if self.editorActive or self._busy:
            return
        self._busy = True
        self._begin_python_worker()
        self._work_success = False
        self._scan_cancelled = False
        self._kind = kind
        if kind == "analyze":
            row = self.catalog.get(target)
            self._started_at = time.monotonic()
            self._progress = {"imageId": target, "running": True, "stage": 0, "seconds": 0.0,
                              "label": "Preparing image", "success": False,
                              "name": Path(row["path"]).name if row else "Image"}
            self._timer.start()
        else:
            self._progress = {}
        self.progressChanged.emit()
        self.setStatus("Scanning folder…" if kind == "scan" else "Connecting to local Ollama…")
        self.thread = QThread(self)
        self.worker = Worker(self.catalog.directory, kind, target, job, self.catalog.thumbnails, self.analyzer_command)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self.setStatus)
        self.worker.phase.connect(self.setPhase)
        self.worker.outcome.connect(self.setOutcome)
        self.worker.finished.connect(self.setStatus)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.complete)
        self.thread.start()

    @Slot()
    def complete(self):
        selected_id = self._selected.get("imageId")
        if self._kind == 'scan':
            self.model.reload()
        else:
            self.model.refresh_loaded()
        if selected_id:
            self._selected = view_record(self.catalog.get(selected_id))
        self.thread.deleteLater()
        self.thread = self.worker = None
        self._busy = False
        self.refreshBatch()
        self._end_python_worker()
        self.workCompleted.emit(self._kind, self._work_success, self._scan_cancelled, self._status)
        self.progressChanged.emit()
        if self._batch.get('state') == 'running':
            QTimer.singleShot(0, self.runNext)


def configure_wheel_scrolling(app):
    # App-local wheel steps: three times Qt's usual three-line default.
    app.styleHints().setWheelScrollLines(9)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local QML wallpaper contact sheet")
    parser.add_argument("--data-dir", type=Path,
                        help="Catalog override (default: $XDG_DATA_HOME/image-lab)")
    parser.add_argument("--cache-dir", type=Path,
                        help="Cache root override (default: $XDG_CACHE_HOME/image-lab; with --data-dir, use that directory)")
    parser.add_argument("--folder", type=Path, help="Import a folder on launch")
    parser.add_argument("--no-ipc", action='store_true', help="Disable local UI control socket")
    args = parser.parse_args(argv)
    # Keep the image browser off the inference GPU. Saturated compute can stall
    # Qt's render thread and, through frame synchronization, the UI thread too.
    # An explicit QT_QUICK_BACKEND (e.g. rhi) still overrides this default.
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication([sys.argv[0]])
    app.setApplicationName("Image Lab")
    app.setOrganizationName("ImageLab")
    configure_wheel_scrolling(app)
    paths = storage_paths(args.data_dir, args.cache_dir)
    paths.data.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = QLockFile(str(paths.data / 'desktop.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        print('Image Lab is already using this catalog. Close that window before reopening.', file=sys.stderr)
        return 1
    controller = Controller(paths.data, paths.thumbnails)
    def update_palette():
        app.setPalette(qt_palette(controller.themeColors))
    controller.themeChanged.connect(update_palette)
    update_palette()
    app.installEventFilter(controller)
    engine = QQmlApplicationEngine()
    engine.addImageProvider('editor-preview', controller.editor.preview.provider)
    engine.rootContext().setContextProperty("gallery", controller.model)
    engine.rootContext().setContextProperty("controller", controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("Main.qml"))))
    if not engine.rootObjects():
        controller.catalog.close()
        return 1
    ipc = None
    if not args.no_ipc:
        from .ipc_actions import ControlRouter
        from .ipc_server import ControlServer
        from .ipc_protocol import ControlError
        try:
            ipc = ControlServer(ControlRouter(controller), paths.data)
        except (ControlError, OSError) as error:
            print(f'Image Lab IPC unavailable: {error}', file=sys.stderr)
            controller.setStatus(f'IPC unavailable: {error}')
    if args.folder and controller.canImport:
        controller.start("scan", str(args.folder))
    code = app.exec()
    if ipc is not None:
        ipc.close()
    # QML prevents ordinary close during work. Handle OS/application quit too.
    if controller.thread:
        controller.thread.requestInterruption()
        controller.thread.quit()
        controller.thread.wait()
    if controller.submission_thread:
        controller.submission_thread.quit()
        controller.submission_thread.wait()
    controller.editor.shutdown()
    controller.viewerMetadata.shutdown()
    controller.viewerMeasurements.shutdown()
    app.removeEventFilter(controller)
    del engine
    controller.catalog.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
