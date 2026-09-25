"""Main-thread application control, explicit allowlist, and observable operations."""
from collections import OrderedDict
import copy
import hashlib
import json
from pathlib import Path
import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal

from .ipc_protocol import ControlError, VERSION, MAX_IDS
from .ipc_methods import METHODS, validate
from .metadata import DEFAULTS, effective_details, edit_revision, validate_details
from .renaming import rename_target

TERMINAL = {'succeeded', 'failed', 'cancelled'}

# The editor is modal. Read-only inspection and bringing the window forward stay
# available; IPC cannot dismiss a draft, change selection, or mutate its context.
EDITOR_SAFE_METHODS = frozenset({
    'app.status', 'app.capabilities', 'events.subscribe', 'library.list', 'library.get',
    'selection.get', 'viewer.status', 'queue.status', 'queue.list', 'details.get',
    'settings.get', 'operation.get', 'window.show', 'window.focus',
})


class ControlRouter(QObject):
    eventReady = Signal(dict)

    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self.instance = uuid.uuid4().hex
        self.sequence = 0
        self.operations = OrderedDict()
        self.submission = None
        self.scan = None
        self.dirty = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.flush)
        self.timer.start()
        controller.changed.connect(self.mark_dirty)
        controller.progressChanged.connect(self.mark_dirty)
        controller.settingsChanged.connect(self.mark_dirty)
        controller.uiStateChanged.connect(self.mark_dirty)
        controller.submissionResult.connect(self.submitted)
        controller.workCompleted.connect(self.completed)
        self.handlers = {
            'app.status': lambda p: self.snapshot(),
            'app.capabilities': lambda p: self.capabilities(),
            'events.subscribe': lambda p: {'instance_id': self.instance, 'sequence': self.sequence, 'snapshot': self.snapshot()},
            'library.list': self.library_list,
            'library.get': lambda p: self.details(p['image_id']),
            'library.import': self.import_folder,
            'library.scan-stop': self.stop_scan,
            'view.search': self.search, 'view.filter': self.filter,
            'view.page': self.page, 'view.reveal': self.reveal,
            'selection.get': lambda p: self.selection(), 'selection.set': self.set_selection,
            'selection.clear': lambda p: self.set_selection({'ids': []}),
            'selection.highlight': self.highlight, 'selection.matches': self.matches,
            'viewer.status': lambda p: dict(self.c._ui_state),
            'viewer.open': self.viewer_open,
            'viewer.next': lambda p: self.neighbor(True),
            'viewer.previous': lambda p: self.neighbor(False),
            'panel.open': lambda p: self.panel(p, True),
            'panel.close': lambda p: self.panel(p, False),
            'analyze': self.analyze, 'analyze.missing': self.missing,
            'queue.status': lambda p: self.c.queue.summary(self.c._batch_id),
            'queue.list': lambda p: {'items': self.c.queue.entries(p.get('offset', 0), p.get('limit', 50)),
                                     'total': self.c.queue.entry_count()},
            'queue.pause': lambda p: self.queue_action('pause'),
            'queue.resume': lambda p: self.queue_action('resume'),
            'queue.stop': lambda p: self.queue_action('stop'),
            'queue.retry': self.retry, 'queue.remove': self.remove,
            'details.get': lambda p: self.details(p['image_id']),
            'details.update': self.update_details,
            'rename.preview': lambda p: self.rename(p, False),
            'rename.apply': lambda p: self.rename(p, True),
            'settings.get': lambda p: self.c.settings,
            'settings.set': self.settings,
            'operation.get': self.operation_get,
        }
        for action in ('window.show', 'window.hide', 'window.focus', 'window.close',
                       'viewer.close', 'viewer.play', 'viewer.pause'):
            self.handlers[action] = lambda p, action=action: self.ui(action)
        assert set(self.handlers) == set(METHODS)

    def capabilities(self):
        return {'methods': METHODS, 'limits': {'page_size': 200, 'image_ids': MAX_IDS,
                'operations': 128, 'active_operations': 32}, 'event_replay': False}

    def hello(self):
        return {'protocol_version': VERSION, 'type': 'hello', 'instance_id': self.instance,
                'catalog': str(self.c.catalog.directory.resolve()), 'application_version': '0.1.0',
                'capabilities': self.capabilities()}

    def dispatch(self, method, params):
        validate(method, params)
        if self.c.editorActive and method not in EDITOR_SAFE_METHODS:
            raise ControlError('busy', 'Close the image editor before this action. Drafts cannot be discarded through IPC.')
        try:
            return self.handlers[method](params)
        except ControlError:
            raise
        except (ValueError, OSError) as exc:
            raise ControlError('conflict', str(exc)) from exc

    def mark_dirty(self):
        self.dirty = True

    def publish(self, kind, data):
        self.sequence += 1
        self.eventReady.emit({'protocol_version': VERSION, 'type': 'event', 'instance_id': self.instance,
                         'sequence': self.sequence, 'event': kind, 'data': copy.deepcopy(data)})

    def snapshot(self):
        return {'ready': True, 'instance_id': self.instance, 'sequence': self.sequence,
                'busy': self.c.busy, 'submitting': self.c.submitting,
                'scanning': self.c.scanning, 'status': self.c.status,
                'editor': {'active': self.c.editorActive, 'state': self.c.editor.state,
                           'dirty': self.c.editor.dirty, 'image_id': self.c.editorRecord.get('imageId')},
                'view': {'query': self.c.model.query, 'filter': self.c.libraryFilter,
                         'total': self.c.total, 'loaded': len(self.c.model.items)},
                'selection': self.selection(), 'ui': dict(self.c._ui_state),
                'batch': self.c.batch, 'progress': self.c.queueProgress,
                'settings': self.c.settings, 'operation_ids': list(self.operations)}

    def selection(self):
        ids = sorted(self.c.model.checked)
        return {'highlighted': self.c.selected.get('imageId'), 'checked': ids[:MAX_IDS],
                'checked_count': len(ids), 'truncated': len(ids) > MAX_IDS}

    def row(self, image_id):
        row = self.c.catalog.get(image_id)
        if row is None:
            raise ControlError('not_found', 'Image does not exist')
        return row

    def details(self, image_id):
        row = self.row(image_id)
        values = effective_details(row)
        return {'image': self.c.imageDetails(image_id),
                'values': {key: values.get(key, default) for key, default in DEFAULTS.items()},
                'revision': edit_revision(row)}

    def library_list(self, p):
        query, status = p.get('query', ''), p.get('filter', 'all')
        rows = self.c.catalog.rows(query, p.get('offset', 0), p.get('limit', 50), status)
        # Compact records keep a page bounded even with large saved predictions.
        return {'items': [{'image_id': r['id'], 'path': r['path'], 'width': r['width'],
                           'height': r['height'], 'analyzed': bool(r['prediction'])} for r in rows],
                'total': self.c.catalog.count(query, status)}

    def ui(self, action, image_id=0):
        if not self.c._ui_state:
            raise ControlError('unavailable', 'UI bridge is not ready')
        if action == 'window.close':
            if not self.c.canClose:
                raise ControlError('busy', 'Finish work before closing the GUI')
            # Return the response before the event loop exits. Recheck when executed.
            QTimer.singleShot(50, lambda: self.c.uiAction.emit(action, 0) if self.c.canClose else None)
            return {'requested': True}
        if action in ('viewer.play', 'viewer.pause'):
            current = self.c._ui_state.get('viewerId')
            if not current or not self.c.imageDetails(current).get('isGif'):
                raise ControlError('conflict', 'Open a GIF in the viewer first')
        self.c.uiAction.emit(action, image_id)
        return {'ui': dict(self.c._ui_state), 'focus_requested': action == 'window.focus'}

    def panel(self, p, opening):
        if p['panel'] == 'details' and opening and not self.c.canEditDetails:
            raise ControlError('busy', 'Highlight an editable image first')
        return self.ui(p['panel'] + ('.open' if opening else '.close'))

    def viewer_open(self, p):
        self.row(p['image_id'])
        return self.ui('viewer.open', p['image_id'])

    def neighbor(self, forward):
        current = self.c._ui_state.get('viewerId')
        if not current:
            raise ControlError('conflict', 'Viewer is closed')
        row = self.row(current)
        where, args = self.c.catalog._where(self.c.model.query, self.c.libraryFilter)
        operator, order = ('>', 'ASC') if forward else ('<', 'DESC')
        found = self.c.catalog.db.execute(
            f'SELECT id FROM images WHERE {where} AND path {operator} ? ORDER BY path {order} LIMIT 1',
            (*args, row['path'])).fetchone()
        if not found:
            raise ControlError('not_found', 'No adjacent image in the current view')
        return self.ui('viewer.open', found['id'])

    def search(self, p):
        self.c.search(p['query'])
        self.c.uiAction.emit('view.search', 0)
        return self.snapshot()['view']

    def filter(self, p):
        self.c.setLibraryFilter(p['filter'])
        return self.snapshot()['view']

    def page(self, p):
        self.c.model.fetchMore()
        return self.snapshot()['view']

    def reveal(self, p):
        self.row(p['image_id'])
        # Do not allocate the entire catalog on the UI thread for a reveal command.
        rows = self.c.catalog.rows(self.c.model.query, 0, MAX_IDS, self.c.libraryFilter)
        ids = [r['id'] for r in rows]
        if p['image_id'] not in ids:
            raise ControlError('not_found', 'Image is outside the first 1000 matches; narrow the visible search')
        index = ids.index(p['image_id'])
        while len(self.c.model.items) <= index and self.c.model.canFetchMore():
            self.c.model.fetchMore()
        self.c.uiAction.emit('view.reveal', index)
        return {'index': index}

    def set_selection(self, p):
        for image_id in p['ids']:
            self.row(image_id)
        self.c.model.set_checked(p['ids'])
        self.c.changed.emit()
        return self.selection()

    def highlight(self, p):
        self.row(p['image_id'])
        self.c.select(p['image_id'])
        return self.selection()

    def matching(self, p, missing=False):
        rows = self.c.catalog.rows(p.get('query', self.c.model.query), 0, MAX_IDS + 1,
                                  p.get('filter', 'needs_tags' if missing else self.c.libraryFilter))
        if len(rows) > MAX_IDS:
            raise ControlError('invalid_request', 'Too many matches; narrow the query to at most 1000 images')
        return [r['id'] for r in rows if not missing or not r['prediction']]

    def matches(self, p):
        return self.set_selection({'ids': self.matching(p)})

    def new_operation(self, kind, **fields):
        if sum(o['state'] not in TERMINAL for o in self.operations.values()) >= 32:
            raise ControlError('busy', 'Too many active operations')
        if len(self.operations) >= 128:
            for key, value in self.operations.items():
                if value['state'] in TERMINAL:
                    del self.operations[key]
                    break
        operation = {'id': uuid.uuid4().hex, 'instance_id': self.instance, 'kind': kind,
                     'state': 'queued', 'created': time.time(), **fields}
        self.operations[operation['id']] = operation
        self.publish('operation.changed', operation)
        return operation

    def update_operation(self, operation, **fields):
        operation.update(fields)
        self.publish('operation.changed', operation)

    def operation_get(self, p):
        operation = self.operations.get(p['operation_id'])
        if operation is None:
            raise ControlError('not_found', 'Operation expired or belongs to another instance')
        return copy.deepcopy(operation)

    def import_folder(self, p):
        if not self.c.canImport:
            raise ControlError('busy', 'Finish or stop queued work before importing')
        path = Path(p['path']).expanduser().resolve()
        if not path.is_dir():
            raise ControlError('invalid_request', 'Import path must be a directory')
        operation = self.new_operation('import')
        self.scan = operation
        self.update_operation(operation, state='running')
        self.c.start('scan', str(path))
        return {'accepted': True, 'operation_id': operation['id']}

    def stop_scan(self, p):
        if not self.c.scanning:
            raise ControlError('conflict', 'No scan is running')
        self.c.stopScan()
        return {'requested': True}

    def completed(self, kind, success, cancelled, message):
        if kind == 'scan' and self.scan:
            self.update_operation(self.scan, state='cancelled' if cancelled else 'succeeded' if success else 'failed', message=message)
            self.scan = None
        self.mark_dirty()

    def analyze(self, p):
        if not self.c.canQueue:
            raise ControlError('busy', 'A scan or queue submission is active')
        for image_id in p['ids']:
            self.row(image_id)
        if not p['ids']:
            raise ControlError('invalid_request', 'At least one image ID is required')
        operation = self.new_operation('analyze')
        self.submission = (operation, self.c.catalog.db.execute('SELECT COALESCE(MAX(id),0) FROM jobs').fetchone()[0])
        self.c.enqueue(p['ids'], p.get('replace', False))
        return {'accepted': True, 'operation_id': operation['id']}

    def missing(self, p):
        return self.analyze({'ids': self.matching(p, missing=True)})

    def submitted(self, batch_id, error):
        if not self.submission:
            return
        operation, after = self.submission
        self.submission = None
        if batch_id is None:
            self.update_operation(operation, state='failed', message=error)
            return
        jobs = [r['id'] for r in self.c.catalog.db.execute('SELECT id FROM jobs WHERE id>? ORDER BY id', (after,))]
        self.update_operation(operation, state='running', batch_id=batch_id, job_ids=jobs)

    def flush(self):
        if not self.dirty:
            return
        for operation in tuple(self.operations.values()):
            if operation['state'] in TERMINAL or not operation.get('job_ids'):
                continue
            ids = operation['job_ids']
            placeholders = ','.join('?' for _ in ids)
            jobs = self.c.catalog.db.execute(
                f'SELECT state FROM jobs WHERE id IN ({placeholders})', ids).fetchall()
            if len(jobs) != len(ids):
                self.update_operation(operation, state='failed', message='Tracked job disappeared')
            elif all(j['state'] in ('succeeded', 'failed', 'canceled') for j in jobs):
                state = ('failed' if any(j['state'] == 'failed' for j in jobs) else
                         'cancelled' if any(j['state'] == 'canceled' for j in jobs) else 'succeeded')
                self.update_operation(operation, state=state)
        if self.dirty:
            self.dirty = False
            self.publish('state.changed', self.snapshot())

    def queue_action(self, action):
        if self.c.submitting or self.c.scanning:
            raise ControlError('busy', 'Wait for scan or queue submission')
        if not self.c._batch_id:
            raise ControlError('not_found', 'No current batch')
        {'pause': self.c.pauseBatch, 'resume': self.c.resumeBatch, 'stop': self.c.stopBatch}[action]()
        return self.c.batch

    def retry(self, p):
        job = self.c.queue.get(p['job_id'])
        if not job:
            raise ControlError('not_found', 'Job does not exist')
        if job['state'] != 'failed' or self.c.queue.image_state(job['image_id']) != 'failed':
            raise ControlError('conflict', 'Only the latest failed job can be retried')
        return self.analyze({'ids': [job['image_id']], 'replace': True})

    def remove(self, p):
        if self.c.submitting:
            raise ControlError('busy', 'Queue submission is active')
        if not self.c.queue.get(p['job_id']):
            raise ControlError('not_found', 'Job does not exist')
        if not self.c.queue.remove(p['job_id']):
            raise ControlError('conflict', 'Only queued jobs can be removed')
        self.c.refreshBatch()
        return {'removed': True}

    def editable(self, image_id):
        row = self.row(image_id)
        if not self.c._can_change_image(image_id):
            raise ControlError('busy', 'Scanning/submission active or this image is queued/running')
        return row

    @staticmethod
    def outcome(result):
        if not result.get('ok'):
            raise ControlError('conflict', result.get('error', 'Operation failed'))
        return result

    def update_details(self, p):
        row = self.editable(p['image_id'])
        if edit_revision(row) != p['revision']:
            raise ControlError('conflict', 'Stale metadata revision; reload details')
        try:
            validate_details(p['values'])
        except ValueError as exc:
            raise ControlError('invalid_request', str(exc)) from exc
        self.outcome(self.c.updateImageDetails(p['image_id'], p['revision'], p['values']))
        return self.details(p['image_id'])

    def rename(self, p, apply):
        row = self.editable(p['image_id'])
        if row['path'] != p['expected_path']:
            raise ControlError('conflict', 'Stale source path')
        target = rename_target(Path(row['path']), p['name'])
        signature = json.dumps([self.instance, row['id'], row['path'], row['mtime'], row['bytes'], str(target)])
        confirmation = hashlib.sha256(signature.encode()).hexdigest()
        if not apply:
            return {'source': row['path'], 'target': str(target), 'confirmation': confirmation}
        if p['confirmation'] != confirmation:
            raise ControlError('confirmation_required', 'Use the confirmation from this exact rename preview')
        self.outcome(self.c.renameById(row['id'], row['path'], p['name']))
        return self.details(row['id'])

    def settings(self, p):
        values = {**self.c.settings, **p['values']}
        result = self.c.saveSettings(values)
        if not result['ok']:
            raise ControlError('invalid_request', result['error'])
        return self.c.settings
