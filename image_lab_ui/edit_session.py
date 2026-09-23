"""Qt editor lifecycle: preview, export and original-source measurement scheduling.

One off-Qt supervisor thread, one disposable child at a time, one coalesced pending
job. Worker completion never calls Qt from that thread. Owners must honor dirty
transition results and keep the Qt event loop alive until closed is emitted.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from uuid import uuid4
from queue import SimpleQueue

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from .edit_preview import EditorPreview
from .edit_process import WorkerImage, prepare_source, render_source
from .edit_protocol import EditWorkerError, SourceSnapshot, validate_color_options
from .edit_recipe import Crop, EditHistory, EditRecipe
from .editor_measurements import empty_measurements, present_source_measurements


@dataclass(frozen=True)
class _Job:
    kind: str
    generation: int
    request_id: str
    source: object
    recipe: EditRecipe | None
    policy: str
    assumption: bool
    cancelled: Event
    destination: str = ''
    options: dict | None = None
    catalog: tuple | None = None
    add_to_library: bool = False
    progress: object = None
    prior: dict | None = None

    def run(self):
        if self.kind == 'measure':
            from .editor_measurements import measure_source
            return measure_source(self.source, self.policy, self.assumption, cancelled=self.cancelled.is_set)
        if self.kind == 'export':
            from .export_job import export_copy
            return export_copy(self.source, self.recipe, self.policy, self.assumption,
                               self.destination, self.options, self.catalog, self.add_to_library,
                               self.cancelled.is_set, self.progress.put)
        if self.kind == 'import':
            from .export_job import import_copy
            return import_copy(self.prior, self.catalog, self.cancelled.is_set, self.progress.put)
        if self.kind == 'prepare':
            return prepare_source(self.source, cancelled=self.cancelled.is_set)
        return render_source(self.source, self.recipe, color_policy=self.policy,
            assume_srgb=self.assumption, request_id=self.request_id,
            generation=self.generation, cancelled=self.cancelled.is_set)


class _Runner:
    """No QObject references: destruction can cancel work without a Qt callback."""
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='editor-supervisor')
        self.job: _Job | None = None
        self.future: Future | None = None

    def cancel(self):
        if self.job is not None:
            self.job.cancelled.set()

    def close(self):
        self.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def start(self, job):
        if self.future is not None:
            raise RuntimeError('Editing workers cannot overlap.')
        self.job = job
        self.future = self.pool.submit(job.run)

    def take(self):
        job, future = self.job, self.future
        if job is None or future is None or not future.done():
            raise RuntimeError('No completed editor job to consume.')
        self.job = self.future = None
        try:
            return job, future.result(), None
        except Exception as error:
            return job, None, error


class EditorSession(QObject):
    changed = Signal()
    closed = Signal()
    transitionBlocked = Signal(str)
    exportFinished = Signal('QVariantMap')

    def __init__(self, parent=None, *, work_active=lambda: False, export_catalog=None):
        super().__init__(parent)
        self._preview = EditorPreview(self)
        self._runner = _Runner()
        # Capture only the Qt-free runner, not self: no late signal into a dead QObject.
        runner = self._runner
        self.destroyed.connect(lambda *_: runner.close())
        self._work_active = work_active
        self._pending = None
        self._export_catalog = export_catalog
        self._progress = SimpleQueue()
        self._export_phase = ''
        self._last_export = {}
        self._measurement_requested = False
        self._measurements = empty_measurements()
        self._saved_recipe = None
        self._saved_policy = None
        self._assume_untagged = False
        self._generation = 0
        self._source = None
        self._history = None
        self._policy = self._base_policy = ('legacy-v1', False)
        self._comparison = False
        self._state = 'closed'
        self._error = self._error_code = ''
        self._disposed = False
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._poll)

    def _owner(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError('Editor session commands belong on its owning Qt thread.')

    @Property(QObject, constant=True)
    def preview(self):
        return self._preview

    @Property(str, notify=changed)
    def sourceMode(self):
        return self._source.mode if self._source is not None else ''

    @Property(bool, notify=changed)
    def canAssumeSrgb(self):
        return (self._source is not None and self._source.mode in ('RGB', 'RGBA')
                and self._source.icc_sha256 is None and self._source.srgb_intent is None)

    @Property(str, notify=changed)
    def sourceColorDescription(self):
        if self._source is None: return 'Reading source color metadata…'
        if self._source.icc_sha256 is not None: return 'Embedded ICC profile'
        if self._source.srgb_intent is not None: return 'Declared sRGB'
        return 'Unknown color space · no ICC profile or sRGB declaration'

    @Property(str, notify=changed)
    def colorPolicy(self):
        return self._policy[0]

    @Property(bool, notify=changed)
    def assumeSrgb(self):
        return self._policy[1]

    @Property(str, notify=changed)
    def state(self):
        return self._state

    @Property(bool, notify=changed)
    def busy(self):
        return self._runner.future is not None or self._pending is not None

    @Property(int, notify=changed)
    def revision(self):
        return self._generation

    @Property(bool, notify=changed)
    def dirty(self):
        return self._history is not None and (self._history.current != self._saved_recipe or self._policy != self._saved_policy)

    @Property(bool, notify=changed)
    def canUndo(self):
        return self._history is not None and self._history.can_undo

    @Property(bool, notify=changed)
    def canRedo(self):
        return self._history is not None and self._history.can_redo

    @Property(bool, notify=changed)
    def comparingOriginal(self):
        return self._comparison

    @Property(bool, notify=changed)
    def blocksExternalWork(self):
        return self._state != 'closed' or self.busy

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Property(str, notify=changed)
    def errorCode(self):
        return self._error_code

    @Property('QVariantMap', notify=changed)
    def recipe(self):
        return self._history.current.to_dict() if self._history else {}

    @Property('QVariantMap', notify=changed)
    def measurements(self):
        return dict(self._measurements)

    @Slot(result=bool)
    def requestMeasurements(self):
        self._owner()
        if self._state != 'ready' or self._policy[0] != 'srgb-v1' or self._preview._frame is None:
            return False
        self._measurement_requested = True
        self._runner.cancel()
        self._schedule_measurements()
        self.changed.emit()
        return True

    def _schedule_measurements(self):
        if not self._measurement_requested or self._policy[0] != 'srgb-v1': return
        frame = self._preview._frame
        if frame is None or self._state != 'ready': return
        self._measurements = empty_measurements(loading=True, revision=self._generation)
        self._queue(_Job('measure', self._generation, uuid4().hex, frame.source, frame.recipe,
                         *self._policy, Event()))

    def _invalidate(self):
        self._generation += 1
        self._measurements = empty_measurements()
        self._runner.cancel()
        self._pending = None
        self._preview.clear()

    def _queue(self, job):
        self._pending = job
        self._start_pending()
        self._timer.start()

    def _start_pending(self):
        if self._runner.future is None and self._pending is not None:
            job, self._pending = self._pending, None
            self._runner.start(job)

    def _discard_allowed(self, discard, revision):
        if self._state == 'exporting':
            self.transitionBlocked.emit('export_active')
            return False
        if type(discard) is not bool:
            raise ValueError('Discard must be an explicit boolean.')
        if revision is not None and (type(revision) is not int or revision != self._generation):
            self.transitionBlocked.emit('stale_confirmation')
            return False
        if not self.dirty:
            return True
        if not discard:
            self.transitionBlocked.emit('unsaved_edits')
            return False
        if revision is None:
            self.transitionBlocked.emit('stale_confirmation')
            return False
        return True

    def open_source(self, path, *, color_policy, assume_srgb=False, assume_untagged=False, discard=False, revision=None):
        self._owner()
        validate_color_options(color_policy, assume_srgb)
        if type(assume_untagged) is not bool or (assume_untagged and color_policy != 'srgb-v1'):
            raise ValueError('The untagged default requires an explicit managed policy.')
        if type(path) is not str or not path or '\0' in path or type(discard) is not bool:
            raise ValueError('Opening requires a source path and an explicit discard boolean.')
        if self._disposed or self._state == 'closing':
            self.transitionBlocked.emit('closing')
            return False
        if self._work_active():
            self.transitionBlocked.emit('work_active')
            return False
        if not self._discard_allowed(discard, revision):
            return False
        self._invalidate()
        self._source = self._history = None
        self._saved_recipe = self._saved_policy = None
        self._last_export = {}
        self._measurement_requested = False
        self._comparison = False
        self._policy = self._base_policy = (color_policy, assume_srgb)
        self._assume_untagged = assume_untagged
        self._error = self._error_code = ''
        self._state = 'opening'
        self._queue(_Job('prepare', self._generation, uuid4().hex, path, None,
                         color_policy, assume_srgb, Event()))
        self.changed.emit()
        return True

    def _schedule_preview(self):
        self._invalidate()
        history, source = self._history, self._source
        if history is None or source is None:
            raise RuntimeError('Rendering requires a prepared editor source.')
        recipe = history.original if self._comparison else history.current
        policy, assumption = self._policy
        request_id = uuid4().hex
        self._preview.begin(source, recipe, request_id=request_id, generation=self._generation,
                           color_policy=policy, assume_srgb=assumption)
        self._error = self._error_code = ''
        self._state = 'rendering'
        self._queue(_Job('render', self._generation, request_id, self._source, recipe,
                         policy, assumption, Event()))

    def _schedule_unmanaged_reference(self):
        """Read-only reference for missing interpretation; never an export fallback."""
        self._invalidate()
        recipe = self._history.original
        request_id = uuid4().hex
        self._preview.begin(self._source, recipe, request_id=request_id,
                            generation=self._generation, color_policy='legacy-v1', assume_srgb=False)
        self._queue(_Job('reference', self._generation, request_id, self._source, recipe,
                         'legacy-v1', False, Event()))

    def _command(self, action):
        self._owner()
        if self._disposed or self._state in ('closing', 'exporting') or self._history is None:
            return False
        try:
            changed = action(self._history)
        except (ValueError, TypeError, OverflowError) as error:
            self._error, self._error_code = str(error), 'invalid_edit'
            self.changed.emit()
            return False
        if not changed:
            return False
        self._comparison = False
        self._schedule_preview()
        self.changed.emit()
        return True

    def _edit(self, transform):
        return self._command(lambda history: history.commit(transform(history.current)))

    @Slot(int, int, int, int, result=bool)
    def crop(self, left, top, right, bottom):
        return self._edit(lambda recipe: recipe.with_crop(Crop(left, top, right, bottom)))

    @Slot(float, float, float, float, int, result=bool)
    def cropView(self, left, top, right, bottom, revision):
        """Accept one staged display-space crop, never a stale/comparison frame."""
        self._owner()
        if (type(revision) is not int or revision != self._generation
                or self._state != 'ready' or self._comparison or self._history is None
                or self._preview._frame is None
                or self._preview._frame.recipe != self._history.current):
            self._error_code, self._error = 'stale_crop', 'Preview changed. Cancel drag crop and start again.'
            self.changed.emit()
            return False
        try:
            recipe = self._history.current.with_display_crop(left, top, right, bottom)
        except (ValueError, TypeError, OverflowError) as error:
            self._error_code, self._error = 'invalid_edit', str(error)
            self.changed.emit()
            return False
        if recipe == self._history.current:
            self._error_code = self._error = ''
            self.changed.emit()
            return True
        return self._edit(lambda current: recipe)

    @Slot(int, int, result=bool)
    def aspect(self, width, height):
        return self._edit(lambda recipe: recipe.with_aspect(width, height))

    @Slot(int, result=bool)
    def rotate(self, steps=1):
        return self._edit(lambda recipe: recipe.rotated(steps))

    @Slot(bool, bool, result=bool)
    def flip(self, horizontal=False, vertical=False):
        return self._edit(lambda recipe: recipe.flipped(horizontal=horizontal, vertical=vertical))

    @Slot(int, result=bool)
    def resizeWidth(self, width):
        return self._edit(lambda recipe: recipe.resized_width(width))

    @Slot(int, result=bool)
    def resizeHeight(self, height):
        return self._edit(lambda recipe: recipe.resized_height(height))

    @Slot(bool, result=bool)
    def allowUpscale(self, allowed):
        return self._edit(lambda recipe: recipe.with_upscale(allowed))

    @Slot(result=bool)
    def undo(self):
        return self._command(lambda history: history.undo() if history.can_undo else False)

    @Slot(result=bool)
    def redo(self):
        return self._command(lambda history: history.redo() if history.can_redo else False)

    @Slot(result=bool)
    def reset(self):
        # Geometry-only reset; never silently change an explicit color interpretation.
        return self._command(lambda history: history.commit(history.original))

    @Slot(str, bool, result=bool)
    def set_color_policy(self, policy, assume_srgb=False):
        self._owner()
        validate_color_options(policy, assume_srgb)
        if self._history is None or self._disposed or self._state in ('closing', 'exporting'):
            return False
        if (policy, assume_srgb) == self._policy:
            return False
        self._policy = (policy, assume_srgb)
        self._schedule_preview()
        self.changed.emit()
        return True

    @Slot(bool, result=bool)
    def compareOriginal(self, enabled):
        self._owner()
        if type(enabled) is not bool:
            raise ValueError('Comparison must be an explicit boolean.')
        if self._history is None or self._disposed or self._state in ('closing', 'exporting') or enabled == self._comparison:
            return False
        self._comparison = enabled
        self._schedule_preview()
        self.changed.emit()
        return True

    @Slot(result=bool)
    def refresh(self):
        self._owner()
        if self._history is None or self._disposed or self._state in ('closing', 'exporting'):
            return False
        self._schedule_preview()
        self.changed.emit()
        return True

    @Slot(result=bool)
    def cancelPreview(self):
        self._owner()
        if self._source is None:
            return self.request_close()
        if self._disposed or self._state in ('closing', 'exporting'):
            return False
        self._invalidate()
        self._state = 'idle'
        self.changed.emit()
        return True

    @Property(bool, notify=changed)
    def exporting(self):
        return self._state == 'exporting'

    @Property(str, notify=changed)
    def exportPhase(self):
        return self._export_phase

    @Property('QVariantMap', notify=changed)
    def lastExport(self):
        return dict(self._last_export)

    def export_copy(self, destination, options, *, add_to_library=False):
        from .export_encoding import validate_options
        self._owner()
        if (self._disposed or self._state != 'ready' or self._source is None
                or self._history is None or self._comparison or self._policy[0] != 'srgb-v1'):
            return False
        options = validate_options(options)
        if type(add_to_library) is not bool: raise ValueError('Import choice must be explicit.')
        self._runner.cancel()
        self._error = self._error_code = ''
        self._last_export = {}
        self._measurements = empty_measurements()
        self._state = 'exporting'
        self._export_phase = 'Preparing export…'
        self._queue(_Job('export', self._generation, uuid4().hex, self._source, self._history.current,
                         *self._policy, Event(), destination, options, self._export_catalog,
                         add_to_library, self._progress))
        self.changed.emit()
        return True

    @Slot(result=bool)
    def cancelExport(self):
        self._owner()
        if not self.exporting: return False
        self._runner.cancel()
        if self._pending is not None: self._pending.cancelled.set()
        self._export_phase = 'Cancelling; waiting for worker/publication completion…'
        self.changed.emit()
        return True

    @Slot(result=bool)
    def retryImport(self):
        self._owner()
        if (self._state != 'ready' or self._export_catalog is None
                or not self._last_export.get('published') or not self._last_export.get('path_confirmed')
                or self._last_export.get('imported')): return False
        self._runner.cancel()
        self._state = 'exporting'
        self._measurements = empty_measurements()
        self._export_phase = 'Retrying library import…'
        self._queue(_Job('import', self._generation, uuid4().hex, self._source, None,
                         *self._policy, Event(), catalog=self._export_catalog,
                         progress=self._progress, prior=dict(self._last_export)))
        self.changed.emit()
        return True

    def request_close(self, *, discard=False, revision=None):
        self._owner()
        if type(discard) is not bool:
            raise ValueError('Discard must be an explicit boolean.')
        if self._state == 'closed' and not self.busy:
            return True
        if not self._discard_allowed(discard, revision):
            return False
        self._invalidate()
        self._source = self._history = None
        self._comparison = False
        self._state = 'closing'
        if self._runner.future is None:
            self._finish_close()
        else:
            self._timer.start()
            self.changed.emit()
        return True

    def shutdown(self, *, discard=False, revision=None):
        self._owner()
        if type(discard) is not bool:
            raise ValueError('Discard must be an explicit boolean.')
        if self._disposed:
            return True
        if not self._discard_allowed(discard, revision):
            return False
        # Keep polling until the active supervisor has reaped its child.
        self._disposed = True
        self._runner.close()
        if self._state == 'closed' and not self.busy:
            self._timer.stop()
            self._timer.timeout.disconnect()
            return True
        return self.request_close(discard=discard, revision=revision)

    def _finish_close(self):
        self._state = 'closed'
        self._error = self._error_code = ''
        self._timer.stop()
        if self._disposed:
            self._timer.timeout.disconnect()
        self.changed.emit()
        self.closed.emit()

    @Slot()
    def _poll(self):
        progress_changed = False
        while not self._progress.empty():
            self._export_phase = self._progress.get()
            progress_changed = True
        if progress_changed: self.changed.emit()
        if self._runner.future is not None and self._runner.future.done():
            job, result, error = self._runner.take()
            if job.generation == self._generation and job.kind in ('export', 'import'):
                # A late cancellation must never hide a successfully published copy.
                self._state = 'ready'
                self._export_phase = ''
                if error is not None:
                    self._error_code = getattr(error, 'code', 'export_failed')
                    self._error = str(error)[:1024] or 'Export failed.'
                else:
                    self._last_export = result
                    if (job.kind == 'export' and result.get('published') and result.get('path_confirmed')
                            and result.get('directory_synced') and not result.get('warnings')):
                        self._saved_recipe, self._saved_policy = job.recipe, (job.policy, job.assumption)
                    self.exportFinished.emit(dict(result))
                self._schedule_measurements()
            elif job.generation == self._generation and job.kind == 'measure' and not job.cancelled.is_set():
                try:
                    if error is not None: raise error
                    frame = self._preview._frame
                    if frame is None or frame.source != job.source or frame.recipe != job.recipe or frame.generation != job.generation:
                        raise ValueError('Measurement revision no longer matches the preview.')
                    self._measurements = present_source_measurements(frame, result, self._generation)
                    if frame.recipe == self._history.original:
                        self._preview.matching_original_measurements(result)
                        self._measurements['colorAgreement'] = True
                except Exception as error:
                    self._measurements = empty_measurements(error=str(error)[:1024],
                        errorCode=getattr(error, 'code', 'measurement_failed'), revision=self._generation)
            elif job.generation == self._generation and not job.cancelled.is_set():
                if error is not None:
                    self._state = 'error'
                    self._error_code = error.code if isinstance(error, EditWorkerError) else 'worker_failed'
                    self._error = str(error)[:1024] or 'Editing worker failed.'
                    if job.kind == 'render' and self._error_code == 'unknown_color_space':
                        self._schedule_unmanaged_reference()
                else:
                    try:
                        if job.kind == 'prepare':
                            if result is None or not isinstance(result, SourceSnapshot):
                                raise ValueError('Invalid prepared source result.')
                            self._source = result
                            if self._assume_untagged and self.canAssumeSrgb:
                                self._policy = self._base_policy = ('srgb-v1', True)
                            self._history = EditHistory(EditRecipe.original(result.oriented_size.width, result.oriented_size.height))
                            self._saved_recipe, self._saved_policy = self._history.original, self._policy
                            self._schedule_preview()
                        elif isinstance(result, WorkerImage) and self._preview.publish(result):
                            if job.kind == 'reference':
                                self._state = 'error'  # Consent is still required; export stays blocked.
                            else:
                                self._state = 'ready'
                                self._schedule_measurements()
                        else:
                            raise ValueError('Editing response did not match this request.')
                    except Exception as error:
                        # A Qt image allocation/publication failure must not leave
                        # the session stuck rendering or destroy its draft.
                        self._state, self._error_code = 'error', 'preview_failed'
                        self._error = str(error)[:1024] or 'Could not publish the editing preview.'
            self._start_pending()
            if self._state == 'closing' and self._runner.future is None:
                self._finish_close()
                return
            if not self.busy:
                self._timer.stop()
            self.changed.emit()
