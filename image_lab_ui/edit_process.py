"""Blocking supervisor API for isolated editing work; call off the Qt UI thread.

Source resolution/reading/decoding are all inside the killable child. No temporary
files or destination files are created here. Render results contain validated raw
pixels. The private transport also supports bounded export/inspection payloads;
encoded-output decoding/verification stays in the child, never the Qt parent.
"""
from dataclasses import dataclass
import json
import hashlib
import math
import os
import selectors
import signal
import subprocess
import sys
import time
from uuid import uuid4

from .edit_protocol import (EditWorkerError, MAX_HEADER_BYTES, MAX_RASTER_BYTES,
                            MAX_STDERR_BYTES, MAX_TIMEOUT, PROTOCOL_VERSION,
                            SourceSnapshot, strict_json, validate_color_options)
from .edit_color import ColorProvenance
from .edit_color_transport import validate_color_result
from .edit_recipe import EditRecipe, Size


@dataclass(frozen=True)
class WorkerImage:
    source: SourceSnapshot
    request_id: str
    generation: int
    size: Size
    output_size: Size
    mode: str
    is_preview: bool
    pixels: bytes
    color_conversion: str = 'none'
    color_interpretation: str = 'unmanaged'
    color: ColorProvenance | None = None
    icc_profile: bytes | None = None
    recipe: EditRecipe | None = None

    def full_resolution_pixels(self):
        if self.is_preview or self.size != self.output_size:
            raise EditWorkerError('preview_not_exportable', 'Preview pixels cannot be used as a full-resolution export.')
        return self.pixels


def _header(raw, request):
    try:
        result = strict_json(raw)
        keys = {'version', 'request_id', 'generation', 'status', 'source', 'render',
                'error', 'color_conversion', 'color_interpretation', 'color', 'profile'}
        if type(result) is not dict or set(result) != keys:
            raise ValueError('Invalid response fields.')
        if type(result['version']) is not int or result['version'] != PROTOCOL_VERSION:
            raise ValueError('Unsupported worker protocol.')
        startup_error = (result['status'] == 'error' and result['request_id'] == ''
                         and type(result['error']) is dict
                         and result['error'].get('code') in ('worker_unavailable', 'cancelled'))
        if not startup_error and (result['request_id'] != request['request_id']
                or type(result['generation']) is not int or result['generation'] != request['generation']):
            raise ValueError('Stale worker response.')
        if result['status'] == 'error' or request['operation'] == 'prepare':
            if (result['color_conversion'] != 'none' or result['color_interpretation'] != 'unmanaged'
                    or result['color'] is not None or result['profile'] is not None):
                raise ValueError('Non-render response contains color state.')
        if result['status'] == 'error':
            error = result['error']
            if result['source'] is not None or result['render'] is not None:
                raise ValueError('Error contains partial raster state.')
            if (type(error) is not dict or set(error) != {'code', 'message'}
                    or type(error['code']) is not str or not 1 <= len(error['code']) <= 80
                    or type(error['message']) is not str or not 1 <= len(error['message']) <= 1024):
                raise ValueError('Invalid error envelope.')
            return result, 0
        if result['status'] != 'ok' or result['error'] is not None:
            raise ValueError('Invalid terminal status.')
        source = SourceSnapshot.from_dict(result['source'])
        if request['operation'] == 'prepare':
            if result['render'] is not None:
                raise ValueError('Unexpected preparation raster.')
            return result, 0
        if source != SourceSnapshot.from_dict(request['snapshot']):
            raise ValueError('Mismatched source snapshot.')
        descriptor = result['render']
        if type(descriptor) is not dict or set(descriptor) != {'size', 'output_size', 'mode', 'is_preview', 'byte_count'}:
            raise ValueError('Invalid raster descriptor.')
        for name in ('size', 'output_size'):
            if type(descriptor[name]) is not list or len(descriptor[name]) != 2:
                raise ValueError('Invalid raster dimensions.')
        size, output = Size(*descriptor['size']), Size(*descriptor['output_size'])
        recipe = EditRecipe.from_dict(request['recipe'])
        if output != recipe.result_size or descriptor['mode'] != source.mode:
            raise ValueError('Raster does not match requested output.')
        preview = request['preview_longest'] is not None
        if type(descriptor['is_preview']) is not bool or descriptor['is_preview'] != preview:
            raise ValueError('Preview/full output mismatch.')
        if preview:
            # Pure calculation; importing this helper does not decode any pixels.
            from .edit_render import preview_size
            if size != preview_size(output, request['preview_longest']):
                raise ValueError('Unexpected preview dimensions.')
        elif size != output:
            raise ValueError('Unexpected full output dimensions.')
        length = size.width * size.height * (4 if source.mode == 'RGBA' else 3)
        if type(descriptor['byte_count']) is not int or descriptor['byte_count'] != length or length > MAX_RASTER_BYTES:
            raise ValueError('Invalid raster length.')
        profile_length = validate_color_result(result, request, source)
        return result, length + profile_length
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise EditWorkerError('protocol_error', 'Invalid or mismatched editing worker response.') from error


def _terminate(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def _run(request, cancelled, *, worker_module='image_lab_ui.edit_worker', header_decoder=_header, payload_only=False):
    if not sys.platform.startswith('linux'):
        raise EditWorkerError('worker_unavailable', 'Bounded editing workers require Linux.')
    wire = json.dumps(request, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    if len(wire) > MAX_HEADER_BYTES:
        raise EditWorkerError('invalid_request', 'Editing request exceeds the protocol budget.')
    if cancelled():
        raise EditWorkerError('cancelled', 'Editing request cancelled.')
    deadline = time.monotonic() + request['timeout']
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen([sys.executable, '-m', worker_module, str(os.getpid())],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True, bufsize=0)
    except OSError as error:
        selector.close()
        raise EditWorkerError('worker_unavailable', 'Cannot start the editing worker.') from error
    header_buffer, pixels, stderr = bytearray(), bytearray(), bytearray()
    result, expected_length, written = None, 0, 0
    try:
        stdin, stdout, stderr_stream = process.stdin, process.stdout, process.stderr
        assert stdin is not None and stdout is not None and stderr_stream is not None
        for stream, event, label in ((stdin, selectors.EVENT_WRITE, 'stdin'),
                                     (stdout, selectors.EVENT_READ, 'stdout'),
                                     (stderr_stream, selectors.EVENT_READ, 'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event, data=label)
        while selector.get_map() or process.poll() is None:
            if cancelled():
                raise EditWorkerError('cancelled', 'Editing request cancelled.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EditWorkerError('timeout', 'Editing request exceeded its wall-clock budget.')
            for key, _ in selector.select(min(remaining, 0.05)):
                if key.data == 'stdin':
                    try:
                        written += os.write(key.fd, wire[written:written + 4096])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        written = len(wire)
                    if written == len(wire):
                        selector.unregister(key.fd)
                        stdin.close()
                    continue
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                if key.data == 'stderr':
                    stderr.extend(chunk)
                    if len(stderr) > MAX_STDERR_BYTES:
                        raise EditWorkerError('output_limit', 'Editing worker exceeded its diagnostic budget.')
                    continue
                if result is None:
                    newline = chunk.find(b'\n')
                    head = chunk if newline < 0 else chunk[:newline]
                    header_buffer.extend(head)
                    if len(header_buffer) > MAX_HEADER_BYTES:
                        raise EditWorkerError('output_limit', 'Editing worker exceeded its header budget.')
                    if newline < 0:
                        continue
                    result, expected_length = header_decoder(header_buffer, request)
                    chunk = chunk[newline + 1:]
                if len(pixels) + len(chunk) > expected_length:
                    raise EditWorkerError('protocol_error', 'Editing worker sent excess raster bytes.')
                pixels.extend(chunk)
        returncode = process.wait()
        if result is None:
            code = 'resource_limit' if returncode in (-signal.SIGKILL, -signal.SIGXCPU) else 'worker_failed'
            raise EditWorkerError(code, 'Editing worker exited without a complete result.')
        if result['status'] == 'error':
            if returncode != 1:
                raise EditWorkerError('protocol_error', 'Editing worker error/exit status disagree.')
            raise EditWorkerError(result['error']['code'], result['error']['message'])
        if returncode != 0 or len(pixels) != expected_length:
            raise EditWorkerError('protocol_error', 'Editing worker returned an incomplete raster.')
        if payload_only:
            return result, bytes(pixels), None
        descriptor = result['profile']
        raster_length = result['render']['byte_count'] if result['render'] is not None else 0
        profile_bytes = None
        if descriptor is not None:
            profile = memoryview(pixels)[raster_length:]
            if hashlib.sha256(profile).hexdigest() != descriptor['sha256']:
                raise EditWorkerError('protocol_error', 'Destination profile digest mismatch.')
            # No ICC parser is run in the parent. These are framing/signature
            # checks; conversion semantics remain the bounded producer's job.
            if result['color']['status'] == 'converted' and (
                    int.from_bytes(profile[:4], 'big') != len(profile)
                    or profile[36:40] != b'acsp' or profile[16:20] != b'RGB '):
                raise EditWorkerError('protocol_error', 'Invalid destination profile framing.')
            profile_bytes = bytes(profile)
        return result, bytes(memoryview(pixels)[:raster_length]), profile_bytes
    finally:
        _terminate(process)
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def _request(operation, path, snapshot, recipe, preview_longest, timeout, request_id, generation,
             color_policy='legacy-v1', assume_srgb=False):
    validate_color_options(color_policy, assume_srgb)
    if type(timeout) not in (int, float) or not 0 < timeout <= MAX_TIMEOUT or not math.isfinite(timeout):
        raise ValueError('Timeout must be positive and at most 60 seconds.')
    if type(generation) is not int or generation < 0:
        raise ValueError('Generation must be a nonnegative integer.')
    if request_id is None:
        request_id = uuid4().hex
    if type(request_id) is not str or not 1 <= len(request_id) <= 128:
        raise ValueError('Request ID must contain 1–128 characters.')
    return {'version': PROTOCOL_VERSION, 'operation': operation, 'path': path,
            'snapshot': snapshot, 'recipe': recipe, 'preview_longest': preview_longest,
            'timeout': timeout, 'request_id': request_id, 'generation': generation,
            'color_policy': color_policy, 'assume_srgb': assume_srgb}


def prepare_source(path, *, timeout=30, cancelled=lambda: False):
    # abspath performs lexical normalization only. No parent-side stat/resolve/read.
    path = os.path.abspath(os.fspath(path))
    if not isinstance(path, str) or '\x00' in path:
        raise ValueError('Source path must be text without NUL characters.')
    request = _request('prepare', path, None, None, None, timeout, None, 0)
    result, _, _ = _run(request, cancelled)
    return SourceSnapshot.from_dict(result['source'])


def render_source(snapshot, recipe, *, preview_longest=2048, timeout=60,
                  cancelled=lambda: False, request_id=None, generation=0,
                  color_policy='legacy-v1', assume_srgb=False):
    if not isinstance(snapshot, SourceSnapshot) or not isinstance(recipe, EditRecipe):
        raise ValueError('Rendering requires a source snapshot and validated recipe.')
    if recipe.source_size != snapshot.oriented_size:
        raise ValueError('Recipe does not match oriented source dimensions.')
    if preview_longest is not None:
        from .edit_render import preview_size
        preview_size(recipe.result_size, preview_longest)
    request = _request('render', snapshot.path, snapshot.to_dict(), recipe.to_dict(),
                       preview_longest, timeout, request_id, generation, color_policy, assume_srgb)
    result, pixels, profile = _run(request, cancelled)
    descriptor = result['render']
    return WorkerImage(snapshot, result['request_id'], result['generation'],
                       Size(*descriptor['size']), Size(*descriptor['output_size']),
                       descriptor['mode'], descriptor['is_preview'], pixels,
                       result['color_conversion'], result['color_interpretation'],
                       ColorProvenance(**result['color']),
                       profile, recipe)
