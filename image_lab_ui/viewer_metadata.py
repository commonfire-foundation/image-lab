"""Cancelable, revision-bound metadata inspection via the public Imagescope API."""
import json
import os
import sys

from PySide6.QtCore import QCoreApplication, QObject, Property, QProcess, QTimer, Signal

from .image_services import MAX_METADATA_BYTES, metadata_error, validate_metadata_result


def _empty(loading=False):
    return dict(metadata_error('', ''), loading=loading)


def _json(data):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate metadata process field.')
            result[key] = value
        return result
    def invalid(_value):
        raise ValueError('Nonfinite metadata process value.')
    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)


def _validate_view(view):
    if type(view) is not dict or view.get('provider') != 'Imagescope':
        raise ValueError('Invalid metadata provider.')
    if any(type(view.get(key)) is not str for key in ('error', 'errorCode')):
        raise ValueError('Invalid metadata failure.')
    if len(view['error']) > 2048 or len(view['errorCode']) > 128:
        raise ValueError('Oversized metadata failure.')
    groups, warnings = view.get('groups'), view.get('warnings')
    if type(groups) is not list or len(groups) > 10 or type(warnings) is not list or len(warnings) > 33:
        raise ValueError('Invalid metadata presentation.')
    for group in groups:
        if type(group) is not dict or type(group.get('title')) is not str or type(group.get('rows')) is not list or len(group['rows']) > 64:
            raise ValueError('Invalid metadata group.')
        for row in group['rows']:
            if type(row) is not dict or any(type(row.get(key)) is not str or len(row[key]) > 1024 for key in ('label', 'value')):
                raise ValueError('Invalid metadata display row.')
    for notice in warnings:
        if type(notice) is not dict or any(type(notice.get(key)) is not str or len(notice[key]) > 2048 for key in ('code', 'field', 'message')):
            raise ValueError('Invalid metadata warning.')
    version = view.get('metadataVersion')
    if version is not None and (type(version) is not int or version != 1):
        raise ValueError('Invalid metadata version.')
    if view['error']:
        if not view['errorCode'] or groups or view.get('metadata') is not None or view.get('source') is not None:
            raise ValueError('Failed metadata has success fields.')
    else:
        validate_metadata_result({'metadata_version': view.get('metadataVersion'), 'status': 'ok',
            'input': view.get('source'), 'metadata': view.get('metadata'), 'warnings': warnings[:32],
            'error': None, 'elapsed_seconds': 0})
    return view


class ViewerMetadata(QObject):
    changed = Signal()
    _validate_view = staticmethod(_validate_view)

    def __init__(self, parent=None, *, worker_command=None, deadline_ms=15000):
        super().__init__(parent)
        self.generation = 0
        self._key = None
        self._data = _empty()
        self._jobs = {}
        self._command = worker_command or (sys.executable, '-m', 'image_lab_ui.metadata_process', str(os.getpid()))
        self._deadline_ms = deadline_ms
        application = QCoreApplication.instance()
        if application:
            application.aboutToQuit.connect(self.shutdown)

    @Property('QVariantMap', notify=changed)
    def data(self):
        return dict(self._data)

    def request(self, row):
        self.generation += 1
        generation = self.generation
        key = [row['id'], row['path'], row['mtime'], row['bytes']] if row else None
        self._key = key
        # Kill old inspection rather than leave a stale filesystem read blocking a pool.
        for process in tuple(self._jobs):
            self._jobs[process]['timer'].stop()
            process.kill()
        self._data = _empty(bool(row))
        self.changed.emit()
        if key is None or generation != self.generation:
            return
        wire = json.dumps({'generation': generation, 'key': key}).encode() + b'\n'
        if len(wire) > 16384:
            self.complete(generation, metadata_error('metadata_request_limit', 'Source path exceeds the metadata request budget.'))
            return
        process = QProcess(self)
        timer = QTimer(process)
        timer.setSingleShot(True)
        state = {'out': bytearray(), 'err': bytearray(), 'generation': generation,
                 'key': list(key), 'timer': timer, 'failed': False}
        self._jobs[process] = state
        process.setProgram(self._command[0])
        process.setArguments(list(self._command[1:]))

        def started():
            # It may have been superseded while QProcess was still starting.
            if generation != self.generation:
                process.kill()
                return
            process.write(wire)
            process.closeWriteChannel()

        process.started.connect(started)
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.readyReadStandardError.connect(lambda: self._read(process))
        process.finished.connect(lambda code, status: self._finished(process, code, status))
        process.errorOccurred.connect(lambda error: self._process_error(process, error))
        timer.timeout.connect(lambda: self._fail(process, 'metadata_timeout', 'Metadata inspection timed out. Refresh to retry.'))
        timer.start(self._deadline_ms)
        process.start()

    def _read(self, process):
        state = self._jobs.get(process)
        if state is None:
            return
        state['out'].extend(bytes(process.readAllStandardOutput()))
        state['err'].extend(bytes(process.readAllStandardError()))
        if len(state['out']) > MAX_METADATA_BYTES or len(state['err']) > 16384:
            self._fail(process, 'metadata_output_limit', 'Metadata process exceeded its output budget.')

    def _fail(self, process, code, message):
        state = self._jobs.get(process)
        if state is None or state['failed']:
            return
        state['failed'] = True
        state['timer'].stop()
        process.kill()
        self.complete(state['generation'], metadata_error(code, message))

    def _process_error(self, process, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._fail(process, 'metadata_process_unavailable', 'Cannot start the Imagescope metadata process.')
            self._dispose(process)

    def _finished(self, process, code, status):
        self._read(process)
        state = self._jobs.get(process)
        if state is None:
            return
        try:
            if state['failed'] or state['generation'] != self.generation:
                return
            if code != 0 or status != QProcess.ExitStatus.NormalExit:
                raise ValueError('Metadata process crashed.')
            result = _json(state['out'])
            key = result.get('key') if type(result) is dict else None
            if (type(result) is not dict or type(result.get('generation')) is not int
                    or result['generation'] != state['generation'] or type(key) is not list
                    or len(key) != len(state['key'])
                    or any(type(actual) is not type(expected) or actual != expected for actual, expected in zip(key, state['key']))
                    or state['key'] != self._key):
                raise ValueError('Metadata load revision does not match.')
            view = self._validate_view(result['view'])
            if not view['error'] and view['source'].get('path') != state['key'][1]:
                raise ValueError('Metadata source path does not match.')
            self.complete(state['generation'], view)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            self.complete(state['generation'], metadata_error('metadata_process_result', 'Metadata process returned an invalid or stale result.'))
        finally:
            self._dispose(process)

    def _dispose(self, process):
        state = self._jobs.pop(process, None)
        if state:
            state['timer'].stop()
            # Break Python callback cycles before Qt deletes child objects.
            state['timer'].timeout.disconnect()
            for signal in (process.started, process.readyReadStandardOutput,
                           process.readyReadStandardError, process.finished, process.errorOccurred):
                signal.disconnect()
            process.deleteLater()

    def complete(self, generation, result):
        if generation == self.generation:
            self._data = dict(result, loading=False, loadRevision=generation, sourceKey=self._key)
            self.changed.emit()

    def shutdown(self):
        self.request(None)
        # Only teardown waits. Ordinary loading/navigation never blocks the UI.
        for process in tuple(self._jobs):
            process.kill()
            process.waitForFinished(1000)
            self._dispose(process)
