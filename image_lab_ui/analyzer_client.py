"""Desktop adapter for analyzer protocol v1. Processes are never launched via a shell."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

from imagescope.contracts import AnalyzerError, MAX_EVENT_BYTES, validate_result, strict_json_loads

from .edit_protocol import validate_color_options

DEFAULT_COMMAND = (sys.executable, '-m', 'imagescope')


class AnalyzerProcessError(ValueError):
    pass


def analyzer_identity(command=DEFAULT_COMMAND):
    """Small, bounded-time metadata query, used when snapshotting a batch."""
    try:
        process = subprocess.run([*command, 'info', '--json'], capture_output=True, timeout=10)
        if process.returncode or len(process.stdout) > 64 * 1024:
            raise ValueError('metadata command failed')
        info = strict_json_loads(process.stdout)
        if type(info.get('protocol_version')) is not int or info['protocol_version'] != 1 or info.get('schema_version') != 1:
            raise ValueError('unsupported protocol/schema version')
        model = info['default_model']
        profile = info['profiles']['wallpaper']
        if not all(isinstance(v, str) and v for v in (model, profile['version'], profile['prompt'])):
            raise ValueError('missing model/profile identity')
        return {'model': model, 'prompt_version': profile['version'], 'prompt': profile['prompt']}
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        raise AnalyzerProcessError(f'Cannot query image analyzer: {exc}. Install the compatible imagescope package in this Python environment.') from exc


def validate_measurement_result(result, path, *, color_policy='legacy-v1', assume_srgb=False):
    """Read-only inspection contract; distinct from metadata-v1 and descriptions."""
    try:
        validate_color_options(color_policy, assume_srgb)
        if len(json.dumps(result, allow_nan=False).encode()) > MAX_EVENT_BYTES:
            raise ValueError('Measurement result exceeds the protocol budget')
        validate_result(result)
        if result['status'] == 'error':
            raise AnalyzerProcessError(f"{result['error']['code']}: {result['error']['message']}")
        provenance = result['provenance']
        preprocessing = provenance['preprocessing']
        color = preprocessing['color_management']
        if type(preprocessing) is not dict or type(color) is not dict:
            raise ValueError('Invalid color provenance')
        if (result['input'].get('path') != str(path) or provenance.get('task') != 'inspect'
                or type(provenance.get('measurements_version')) is not int or provenance['measurements_version'] != 6
                or type(preprocessing.get('version')) is not int or preprocessing['version'] != (3 if color_policy == 'legacy-v1' else 4)
                or color.get('policy') != color_policy
                or type(color.get('assume_srgb')) is not bool or color['assume_srgb'] != assume_srgb
                or type(provenance.get('measurement_settings')) is not dict
                or type(provenance['measurement_settings'].get('palette_size')) is not int
                or provenance['measurement_settings']['palette_size'] != 6
                or type(result.get('measurements')) is not dict):
            raise ValueError('Measurements do not match the requested source, version, or color policy')
        if color_policy == 'legacy-v1':
            if color.get('status') != 'unmanaged':
                raise ValueError('Legacy measurements must remain unmanaged')
        else:
            _validate_managed_measurement_color(color, assume_srgb)
        for name in ('working_width', 'working_height'):
            if type(preprocessing.get(name)) is not int or not 1 <= preprocessing[name] <= 2048:
                raise ValueError('Missing or invalid measurement working dimensions')
        if type(preprocessing.get('downsampled')) is not bool:
            raise ValueError('Missing sampling provenance')
    except (AnalyzerError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise AnalyzerProcessError(str(exc)) from exc
    return result


def _validate_managed_measurement_color(color, assume_srgb):
    if (color.get('output_color_space') != 'srgb' or color.get('source_mode') not in ('RGB', 'RGBA')
            or color.get('black_point_compensation') is not False
            or color.get('order') != 'color-before-reduction-orientation-compositing'
            or type(color.get('pillow_version')) is not str or not color['pillow_version']):
        raise ValueError('Unsupported managed measurement color provenance')
    profile = color.get('source_profile')
    if type(profile) is not dict:
        raise ValueError('Missing source profile provenance')
    status = color.get('status')
    if status == 'converted':
        from .edit_protocol import _digest
        if (color.get('source_interpretation') != 'embedded_icc' or profile.get('status') != 'valid'
                or not _digest(profile.get('sha256'))
                or color.get('rendering_intent') != 'relative-colorimetric'
                or color.get('transform_optimization') != 'disabled'
                or type(color.get('littlecms_version')) is not str or not color['littlecms_version']):
            raise ValueError('Unsupported measurement ICC transform')
    elif (status not in ('declared_srgb', 'assumed_srgb') or color.get('source_interpretation') != status
            or (status == 'assumed_srgb' and not assume_srgb)
            or profile.get('status') != 'absent' or profile.get('sha256') is not None
            or any(color.get(key) is not None for key in ('rendering_intent', 'transform_optimization', 'littlecms_version'))):
        raise ValueError('Unsupported measurement interpretation')


def inspect_measurements(path, *, color_policy='legacy-v1', assume_srgb=False):
    """Blocking public inspect API, for the isolated viewer worker only.

    No model calls, local palette algorithm, color conversion, or fallback.
    Keep the existing queued describe path and its default semantics unchanged.
    """
    from imagescope import AnalysisRequest, analyze
    validate_color_options(color_policy, assume_srgb)
    path = Path(path).resolve()
    result = analyze(AnalysisRequest(source=path, task='inspect', timeout=30,
                                    palette_size=6, color_policy=color_policy, assume_srgb=assume_srgb))
    return validate_measurement_result(result, path, color_policy=color_policy, assume_srgb=assume_srgb)


class EventReader:
    def __init__(self, phase):
        self.phase = phase
        self.buffer = b''
        self.total = 0
        self.hello = False
        self.result = None

    def feed(self, data):
        self.total += len(data)
        self.buffer += data
        if self.total > 2 * MAX_EVENT_BYTES:
            raise AnalyzerProcessError('Analyzer output exceeds the protocol limit')
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n',1)
            if len(line) > MAX_EVENT_BYTES:
                raise AnalyzerProcessError('Analyzer event exceeds the protocol limit')
            try:
                event = strict_json_loads(line.decode('utf-8'))
                if not isinstance(event, dict) or type(event.get('protocol_version')) is not int or event['protocol_version'] != 1:
                    raise ValueError('unsupported event protocol')
                kind = event.get('type')
                if self.result is not None:
                    raise ValueError('event after terminal result')
                if not self.hello:
                    if kind != 'hello' or event.get('schema_version') != 1:
                        raise ValueError('missing or incompatible hello')
                    self.hello = True
                elif kind == 'progress':
                    stages = {'preparing':0, 'checking':1, 'generating':2}
                    if event.get('stage') not in stages or not isinstance(event.get('label'), str):
                        raise ValueError('invalid progress event')
                    self.phase(stages[event['stage']], event['label'][:200])
                elif kind == 'result':
                    self.result = validate_result(event.get('result'))
                else:
                    raise ValueError('unexpected event type')
            except (ValueError, KeyError, TypeError, AnalyzerError) as exc:
                raise AnalyzerProcessError(f'Invalid analyzer event: {exc}') from exc
        if len(self.buffer) > MAX_EVENT_BYTES:
            raise AnalyzerProcessError('Analyzer event exceeds the protocol limit')

    def finish(self):
        if self.buffer or not self.hello or self.result is None:
            raise AnalyzerProcessError('Analyzer exited without a complete terminal result')
        return self.result


def run_analyzer(path, identity, phase, *, command=DEFAULT_COMMAND, timeout=300, interrupted=lambda: False):
    """Worker-only subprocess I/O; Python's selector wait releases the GIL.

    Qt's blocking process waits can starve Python-backed QML bindings while
    the scene graph is rendering, even when the process lives in a QThread.
    """
    process = None
    selector = selectors.DefaultSelector()
    reader = EventReader(phase)
    stderr = b''
    args = [*command[1:], 'describe', str(path), '--profile', 'wallpaper', '--model', identity['model'],
            '--measurements', '--events=jsonl', '--protocol-version', '1', '--timeout', str(timeout),
            '--expect-profile-version', identity['prompt_version'], '--expect-prompt-sha256',
            hashlib.sha256(identity['prompt'].encode()).hexdigest()]
    started = time.monotonic()
    try:
        try:
            process = subprocess.Popen([str(command[0]), *args], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise AnalyzerProcessError(f'Cannot start image analyzer: {exc}') from exc
        for pipe in (process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            if interrupted():
                raise AnalyzerProcessError('Analysis interrupted; Ollama may still finish the submitted request')
            if time.monotonic() - started > timeout + 5:
                raise AnalyzerProcessError('Analyzer process timed out')
            for key, _ in selector.select(0.05):
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                elif key.fileobj is process.stdout:
                    reader.feed(data)
                else:
                    stderr = (stderr + data)[-8192:]
        if process.returncode < 0:
            raise AnalyzerProcessError('Analyzer process crashed')
        result = reader.finish()
        if result['status'] == 'error':
            if process.returncode == 0:
                raise AnalyzerProcessError('Analyzer reported failure with a successful exit code')
            raise AnalyzerProcessError(f"{result['error']['code']}: {result['error']['message']}")
        if process.returncode != 0:
            raise AnalyzerProcessError(f'Analyzer exited with code {process.returncode} despite reporting success')
        provenance = result['provenance']
        if (result['input'].get('path') != str(Path(path).resolve())
                or provenance.get('task') != 'describe'
                or provenance.get('profile') != 'wallpaper'
                or provenance.get('profile_version') != identity['prompt_version']
                or provenance.get('prompt') != identity['prompt']
                or not isinstance(provenance.get('model'), dict)
                or provenance['model'].get('name') != identity['model']
                or not isinstance(provenance.get('settings'), dict)
                or 'ollama_version' not in provenance
                or not isinstance(result['measurements'], dict)):
            raise AnalyzerProcessError('Analyzer result does not match the queued request')
        return result
    except AnalyzerProcessError as exc:
        detail = stderr.decode('utf-8', errors='replace').strip()
        if detail:
            raise AnalyzerProcessError(f'{exc} · {detail[-1000:]}') from exc
        raise
    finally:
        selector.close()
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            finally:
                process.stdout.close()
                process.stderr.close()
