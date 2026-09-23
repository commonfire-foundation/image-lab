"""Real Qt server + independent socket/CLI clients, synthetic files, fake inference."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from image_lab_ui.ipc_client import Client
from image_lab_ui.ipc_protocol import ControlError, encode, endpoint

ROOT = Path(__file__).resolve().parents[1]
HAS_QT = importlib.util.find_spec('PySide6') is not None
LAUNCH = '''
from functools import partial
from image_lab_ui import app
import sys
app.Controller = partial(app.Controller, analyzer_command=(sys.executable, sys.argv.pop(1), '--mode', 'slow'))
raise SystemExit(app.main())
'''


@unittest.skipUnless(HAS_QT, 'Requires Qt')
class IpcIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT, prefix='i')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'r'
        self.runtime.mkdir(mode=0o700)
        self.catalog = self.root / 'data'
        self.patch = patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(self.runtime),
            'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.log = (self.root / 'gui.log').open('w+')
        self.addCleanup(self.log.close)
        self.process = self.launch(self.catalog)
        self.addCleanup(self.stop)
        self.wait_ready(self.catalog)

    def launch(self, catalog, extra=()):
        return subprocess.Popen([sys.executable, '-c', LAUNCH, str(ROOT/'tests/helpers/fake_analyzer.py'),
            '--data-dir', str(catalog), *extra], cwd=ROOT, stdout=self.log, stderr=self.log)

    def wait_ready(self, catalog):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.log.seek(0)
                self.fail(self.log.read())
            try:
                with Client(catalog, timeout=1) as client:
                    self.assertTrue(client.call('app.status')['ready'])
                    return
            except (ControlError, FileNotFoundError):
                time.sleep(0.03)
        self.log.seek(0)
        self.fail('GUI did not start: ' + self.log.read())

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def call(self, method, **params):
        with Client(self.catalog) as client:
            return client.call(method, params)

    def wait_operation(self, operation_id):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            operation = self.call('operation.get', operation_id=operation_id)
            if operation['state'] in ('succeeded', 'failed', 'cancelled'):
                return operation
            time.sleep(0.04)
        self.fail('Operation did not finish')

    def import_images(self, count=2):
        folder = self.root / 'images'
        folder.mkdir(exist_ok=True)
        for i in range(count):
            Image.new('RGB', (32, 16), 'red').save(folder / f'{i:04}.png')
        op = self.call('library.import', path=str(folder))
        self.assertEqual(self.wait_operation(op['operation_id'])['state'], 'succeeded')
        return [r['image_id'] for r in self.call('library.list', limit=min(count, 200))['items']]

    def test_discovery_cli_and_shutdown(self):
        hello = Client(self.catalog)
        self.assertEqual(hello.hello['catalog'], str(self.catalog.resolve()))
        hello.close()
        result = subprocess.run([sys.executable, '-m', 'image_lab', 'ctl', 'status', '--json',
                                 '--data-dir', str(self.catalog)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ready'])
        self.assertEqual(self.call('window.hide')['ui']['visible'], False)
        self.assertEqual(self.call('window.show')['ui']['visible'], True)
        self.call('window.close')
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assertFalse(endpoint(self.catalog).exists())

    def test_import_view_selection_panels_and_settings(self):
        ids = self.import_images()
        self.call('selection.set', ids=ids)
        self.call('selection.highlight', image_id=ids[0])
        self.call('viewer.open', image_id=ids[0])
        self.assertEqual(self.call('viewer.next')['ui']['viewerId'], ids[1])
        self.assertEqual(self.call('viewer.previous')['ui']['viewerId'], ids[0])
        self.assertEqual(self.call('selection.get')['checked'], ids)
        self.call('viewer.close')
        for panel in ('queue','settings','about'):
            self.assertTrue(self.call('panel.open', panel=panel)['ui']['panels'][panel])
            self.call('panel.close', panel=panel)
        settings = self.call('settings.get')
        key = next(k for k,v in settings.items() if type(v) is bool)
        self.assertEqual(self.call('settings.set', values={key: not settings[key]})[key], not settings[key])
        self.call('view.search', query='0001')
        self.assertEqual(self.call('app.status')['view']['total'], 1)
        self.assertEqual(self.call('library.list')['total'], 2)
        self.assertEqual(self.call('selection.get')['checked'], [])

    def test_queue_events_edits_and_rename(self):
        ids = self.import_images()
        with Client(self.catalog) as subscriber:
            snapshot = subscriber.call('events.subscribe')
            op = self.call('analyze', ids=[ids[0]])
            with self.assertRaises(ControlError) as error:
                self.call('window.close')
            self.assertEqual(error.exception.code, 'busy')
            sequence = snapshot['sequence']
            terminal = False
            deadline = time.monotonic() + 10
            while not terminal and time.monotonic() < deadline:
                event = subscriber.receive(10)
                self.assertEqual(event['sequence'], sequence + 1)
                sequence = event['sequence']
                terminal = (event['event'] == 'operation.changed' and
                            event['data']['id'] == op['operation_id'] and event['data']['state'] == 'succeeded')
            self.assertTrue(terminal)
        details = self.call('details.get', image_id=ids[0])
        values = dict(details['values'], caption='Edited through IPC')
        self.call('details.update', image_id=ids[0], revision=details['revision'], values=values)
        with self.assertRaises(ControlError) as error:
            self.call('details.update', image_id=ids[0], revision=details['revision'], values=values)
        self.assertEqual(error.exception.code, 'conflict')
        path = details['image']['path']
        rename = {'image_id': ids[0], 'expected_path': path, 'name': 'renamed.png'}
        preview = self.call('rename.preview', **rename)
        with self.assertRaises(ControlError):
            self.call('rename.apply', **rename, confirmation='wrong')
        result = self.call('rename.apply', **rename, confirmation=preview['confirmation'])
        self.assertTrue(Path(result['image']['path']).exists())
        self.assertFalse(Path(path).exists())
        self.assertIsNone(self.call('selection.get')['highlighted'])

    def test_fragmented_messages_unknown_methods_and_duplicate_ids(self):
        with Client(self.catalog) as client:
            raw = encode({'protocol_version':1, 'id':'a', 'method':'app.status', 'params':{}})
            client.socket.sendall(raw[:7])
            time.sleep(0.02)
            client.socket.sendall(raw[7:])
            self.assertEqual(client.receive()['id'], 'a')
            client.socket.sendall(raw + raw)
            self.assertIn('error', client.receive())
        with self.assertRaises(ControlError) as error:
            self.call('__getattribute__')
        self.assertEqual(error.exception.code, 'unknown_method')
        self.assertTrue(self.call('app.status')['ready'])

    def test_duplicate_launch_and_second_catalog(self):
        second = self.launch(self.catalog)
        self.assertEqual(second.wait(timeout=10), 1)
        self.assertTrue(self.call('app.status')['ready'])
        other = self.root / 'other'
        third = self.launch(other)
        try:
            self.wait_ready(other)
            with Client(other) as client:
                self.assertNotEqual(client.hello['instance_id'], self.call('app.status')['instance_id'])
                client.call('window.close')
            self.assertEqual(third.wait(timeout=5), 0)
        finally:
            if third.poll() is None:
                third.terminate()
                third.wait(timeout=5)

    def test_queue_pause_remove_stop_and_disconnected_submitter(self):
        ids = self.import_images(3)
        op = self.call('analyze', ids=ids)  # call() disconnects immediately after acceptance
        deadline = time.monotonic() + 5
        while self.call('app.status')['submitting']:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.03)
        self.call('queue.pause')
        jobs = self.call('queue.list')['items']
        queued = [j for j in jobs if j['state'] == 'queued']
        self.assertTrue(queued)
        self.call('queue.remove', job_id=queued[-1]['id'])
        self.call('queue.stop')
        terminal = self.wait_operation(op['operation_id'])
        self.assertEqual(terminal['state'], 'cancelled')
        self.assertEqual(self.call('queue.status')['state'], 'stopped')
        with self.assertRaises(ControlError):
            self.call('queue.remove', job_id=queued[-1]['id'])

    def test_failures_retry_and_stale_operation_after_restart(self):
        ids = self.import_images(1)
        source = Path(self.call('library.get', image_id=ids[0])['image']['path'])
        source.unlink()
        op = self.call('analyze', ids=ids)
        self.assertEqual(self.wait_operation(op['operation_id'])['state'], 'failed')
        job = self.call('queue.list')['items'][0]
        retry = self.call('queue.retry', job_id=job['id'])
        self.assertEqual(self.wait_operation(retry['operation_id'])['state'], 'failed')
        self.stop()
        self.process = self.launch(self.catalog)
        self.wait_ready(self.catalog)
        with self.assertRaises(ControlError) as error:
            self.call('operation.get', operation_id=op['operation_id'])
        self.assertEqual(error.exception.code, 'not_found')

    def test_limits_and_command_flood_leave_gui_usable(self):
        peers = []
        try:
            for _ in range(16):
                peers.append(Client(self.catalog))
            with self.assertRaises(ControlError):
                Client(self.catalog, timeout=1)
        finally:
            for peer in peers:
                peer.close()
        time.sleep(0.1)
        with Client(self.catalog) as client:
            payload = b''.join(encode({'protocol_version': 1, 'id': str(i),
                'method': 'app.status', 'params': {}}) for i in range(100))
            client.socket.sendall(payload)
            self.assertIn('error', client.receive())
        with Client(self.catalog) as client:
            try:
                client.socket.sendall(b'x' * (1024 * 1024 + 1))
                self.assertIn('error', client.receive())
            except (BrokenPipeError, ControlError):
                pass  # Oversized clients may be disconnected before the send completes.
        self.assertTrue(self.call('app.status')['ready'])

    def test_view_updates_do_not_clear_later_selection_and_invalid_actions_fail(self):
        ids = self.import_images()
        self.call('view.search', query='png')
        self.call('selection.set', ids=ids)
        time.sleep(0.3)
        self.assertEqual(self.call('selection.get')['checked'], ids)
        self.call('view.filter', filter='needs_tags')
        self.call('selection.matches')
        self.assertEqual(self.call('selection.get')['checked'], ids)
        self.call('view.page')
        self.call('view.reveal', image_id=ids[0])
        self.call('selection.clear')
        for method, params in [('viewer.open', {'image_id': 999999}),
                               ('panel.open', {'panel': 'details'}),
                               ('viewer.play', {}), ('library.scan-stop', {}),
                               ('settings.set', {'values': {'unknown': True}})]:
            with self.subTest(method=method), self.assertRaises(ControlError):
                self.call(method, **params)

    def test_remaining_controls_and_cli_wait(self):
        ids = self.import_images(1)
        self.assertTrue(self.call('window.focus')['focus_requested'])
        op = self.call('analyze.missing')
        self.assertEqual(self.wait_operation(op['operation_id'])['state'], 'succeeded')
        self.call('selection.highlight', image_id=ids[0])
        self.assertTrue(self.call('panel.open', panel='details')['ui']['panels']['details'])
        self.call('panel.close', panel='details')
        # Resume is idempotent for an already complete batch.
        self.call('queue.resume')
        result = subprocess.run([sys.executable, '-m', 'image_lab', 'ctl', 'operation', 'wait',
            op['operation_id'], '--data-dir', str(self.catalog), '--json'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'succeeded')
        folder = self.root / 'gif'
        folder.mkdir()
        Image.new('RGB', (8, 8), 'red').save(folder / 'test.gif', save_all=True,
            append_images=[Image.new('RGB', (8, 8), 'blue')], duration=100, loop=0)
        imported = self.call('library.import', path=str(folder))
        self.wait_operation(imported['operation_id'])
        gif_id = self.call('library.list', query='test.gif')['items'][0]['image_id']
        self.call('viewer.open', image_id=gif_id)
        self.assertTrue(self.call('viewer.pause')['ui']['gifPaused'])
        self.assertFalse(self.call('viewer.play')['ui']['gifPaused'])

    def test_scan_cancellation_and_protocol_version_errors(self):
        folder = self.root / 'scan'
        folder.mkdir()
        for i in range(40):
            Image.new('RGB', (16, 16), 'red').save(folder / f'{i}.png')
        operation = self.call('library.import', path=str(folder))
        self.call('library.scan-stop')
        self.assertEqual(self.wait_operation(operation['operation_id'])['state'], 'cancelled')
        with Client(self.catalog) as client:
            client.socket.sendall(encode({'protocol_version': 999, 'id': 'v',
                                          'method': 'app.status', 'params': {}}))
            self.assertEqual(client.receive()['error']['code'], 'unsupported_protocol')
        self.assertTrue(self.call('app.status')['ready'])

    def test_ipc_can_be_disabled(self):
        self.stop()
        # Remove the crashed test instance's stale socket so we can assert none is created.
        path = endpoint(self.catalog)
        path.unlink(missing_ok=True)
        self.process = self.launch(self.catalog, ('--no-ipc',))
        time.sleep(0.5)
        self.assertIsNone(self.process.poll())
        self.assertFalse(path.exists())
        with self.assertRaises(ControlError):
            Client(self.catalog, timeout=0.1)

    def test_stale_socket_recovery(self):
        self.stop()
        # SIGTERM leaves a stale endpoint; a new lock owner may clean it up.
        self.process = self.launch(self.catalog)
        self.wait_ready(self.catalog)
        self.assertTrue(self.call('app.status')['ready'])

    def test_viewer_navigation_beyond_loaded_page(self):
        self.import_images(300)
        loaded = self.call('app.status')['view']['loaded']
        self.assertLess(loaded, 300)
        rows = self.call('library.list', offset=loaded-1, limit=2)['items']
        self.call('viewer.open', image_id=rows[0]['image_id'])
        self.assertEqual(self.call('viewer.next')['ui']['viewerId'], rows[1]['image_id'])
        self.assertEqual(self.call('app.status')['view']['loaded'], loaded)
