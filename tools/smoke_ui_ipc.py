"""Installed-package UI IPC acceptance with fake inference and disposable state.

Run with the installed environment, outside the checkout:
  /absolute/venv/bin/python -I /path/to/tools/smoke_ui_ipc.py SHORT_WORK_DIRECTORY
The work directory must be writable; all fixtures/runtime files stay beneath it.
No live Ollama service or personal catalog is used.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def fake_analyzer():
    from imagescope.cli import info
    from imagescope import AnalysisRequest, analyze
    if 'info' in sys.argv:
        print(json.dumps(info()))
        return
    path = Path(sys.argv[sys.argv.index('describe') + 1])
    class Backend:
        def check_model(self, model):
            return {'name': model, 'digest': 'fake'}, {'version': 'fake'}
        def describe(self, image, model, preview_size, *, profile):
            assert profile == 'wallpaper', profile
            time.sleep(0.2)
            return {'caption': 'Synthetic red image', 'subjects': [], 'medium': 'abstract',
                    'mood': [], 'lighting': [], 'composition': [], 'tags': ['red'],
                    'text_present': False, 'watermark_present': False}, {}
    print(json.dumps({'protocol_version': 1, 'type': 'hello', 'schema_version': 1}), flush=True)
    result = analyze(AnalysisRequest(path, measurements=True), backend=Backend())
    print(json.dumps({'protocol_version': 1, 'type': 'result', 'result': result}), flush=True)
    if result['status'] != 'ok':
        raise SystemExit(1)


def main():
    import imagescope
    import image_lab_ui.app as desktop
    from image_lab_ui.ipc_client import Client
    from image_lab_ui.ipc_protocol import ControlError
    from PIL import Image
    for module in (imagescope, desktop):
        assert 'site-packages' in module.__file__, module.__file__
    executable = Path(sys.executable).absolute()
    command = executable.parent / 'image-lab'
    work = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(dir=work, prefix='s') as temporary:
        root = Path(temporary)
        runtime = root / 'r'
        runtime.mkdir(mode=0o700)
        catalog = root / 'catalog'
        images = root / 'images'
        images.mkdir()
        Image.new('RGB', (40, 20), 'red').save(images / 'red.png')
        env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
        launch = '''
from functools import partial
import sys
from image_lab_ui import app
app.Controller = partial(app.Controller, analyzer_command=(sys.executable, '-I', sys.argv.pop(1), '--fake-analyzer'))
raise SystemExit(app.main())
'''
        with (root / 'gui.log').open('w+') as log:
            process = subprocess.Popen([str(executable), '-I', '-c', launch, str(Path(__file__).resolve()),
                                        '--data-dir', str(catalog)], cwd=root, env=env, stdout=log, stderr=log)
            previous = os.environ.get('XDG_RUNTIME_DIR')
            os.environ['XDG_RUNTIME_DIR'] = str(runtime)
            try:
                def cli(*args):
                    result = subprocess.run([str(command), 'ctl', '--data-dir', str(catalog), '--json', *args],
                                            cwd=root, env=env, capture_output=True, text=True, timeout=20)
                    assert result.returncode == 0, result.stdout + result.stderr
                    return json.loads(result.stdout)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with Client(catalog):
                            break
                    except ControlError:
                        if process.poll() is not None or time.monotonic() > deadline:
                            log.seek(0)
                            raise AssertionError(log.read())
                        time.sleep(0.03)
                assert cli('status')['ready']
                assert len(cli('instances')) == 1
                operation = cli('library', 'import', str(images))
                assert cli('operation', 'wait', operation['operation_id'])['state'] == 'succeeded'
                image_id = str(cli('library', 'list')['items'][0]['image_id'])
                cli('view', 'search', 'red')
                cli('selection', 'set', image_id)
                cli('viewer', 'open', image_id)
                cli('viewer', 'close')
                with Client(catalog) as subscriber:
                    snapshot = subscriber.call('events.subscribe')
                    operation = cli('analyze', '--ids', image_id)
                    assert cli('operation', 'wait', operation['operation_id'])['state'] == 'succeeded'
                    sequence = snapshot['sequence']
                    while True:
                        event = subscriber.receive(5)
                        assert event['sequence'] == sequence + 1
                        sequence = event['sequence']
                        if (event['event'] == 'operation.changed' and event['data']['id'] == operation['operation_id']
                                and event['data']['state'] == 'succeeded'):
                            break
                details = cli('details', 'get', image_id)
                values = dict(details['values'], caption='Human-edited smoke fixture')
                cli('details', 'update', image_id, '--revision', details['revision'], '--values', json.dumps(values))
                source = details['image']['path']
                args = [image_id, '--expected-path', source, '--name', 'renamed.png']
                preview = cli('rename', 'preview', *args)
                cli('rename', 'apply', *args, '--confirm', preview['confirmation'])
                assert (images / 'renamed.png').exists() and not Path(source).exists()
                settings = cli('settings', 'get')
                key = next(key for key, value in settings.items() if type(value) is bool)
                cli('settings', 'set', '--values', json.dumps({key: not settings[key]}))
                cli('window', 'close')
                assert process.wait(timeout=5) == 0
                log.seek(0)
                output = log.read()
                assert 'ReferenceError' not in output and 'TypeError' not in output, output
                print(json.dumps({'status': 'ok', 'desktop': desktop.__file__, 'backend': imagescope.__file__,
                                  'checks': ['installed CLI', 'import', 'viewer', 'analysis', 'events',
                                             'metadata', 'rename', 'settings', 'safe close']}))
            finally:
                if previous is None:
                    os.environ.pop('XDG_RUNTIME_DIR', None)
                else:
                    os.environ['XDG_RUNTIME_DIR'] = previous
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == '__main__':
    if '--fake-analyzer' in sys.argv:
        fake_analyzer()
    else:
        main()
