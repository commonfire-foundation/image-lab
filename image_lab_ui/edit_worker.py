"""Linux resource-bounded editor subprocess. Reads one request, never writes files."""
import ctypes
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import stat
import sys

from .edit_protocol import (EditWorkerError, MAX_HEADER_BYTES, MAX_INPUT_BYTES,
                            MAX_TIMEOUT, MEMORY_BYTES, PROTOCOL_VERSION,
                            SourceSnapshot, strict_json, validate_color_options, MAX_PROFILE_BYTES)
from .edit_recipe import EditRecipe, MAX_PIXELS, Size


def _sandbox(parent_pid, timeout):
    if not sys.platform.startswith('linux'):
        raise EditWorkerError('worker_unavailable', 'Bounded editing workers require Linux.')
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        cpu = max(1, math.ceil(timeout))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError('Parent-lifetime guard failed.')
        if os.getppid() != parent_pid:
            raise EditWorkerError('cancelled', 'The editing parent has exited.')
    except (OSError, ValueError) as error:
        raise EditWorkerError('worker_unavailable', 'Cannot enforce editing worker limits.') from error


def _stat_identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _read_source(path, expected):
    # Both resolution and file reading happen under the supervisor's deadline.
    try:
        if Path(path).is_symlink():
            code = 'source_changed' if expected else 'unsupported_source'
            raise EditWorkerError(code, 'Choose the original file, not a symbolic link.')
        canonical = str(Path(path).resolve(strict=True))
        fd = os.open(canonical, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise EditWorkerError('unsupported_source', 'Editing requires a regular file.')
            if not 0 < before.st_size <= MAX_INPUT_BYTES:
                raise EditWorkerError('input_limit', 'Source must be nonempty and no larger than 64 MiB.')
            if expected and (canonical != expected.path or _stat_identity(before) != expected.stat_identity):
                raise EditWorkerError('source_changed', 'Original changed since this edit session began.')
            data = stream.read(MAX_INPUT_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(data) > MAX_INPUT_BYTES:
            raise EditWorkerError('input_limit', 'Source exceeds the 64 MiB input limit.')
        if len(data) != before.st_size or _stat_identity(after) != _stat_identity(before):
            raise EditWorkerError('source_changed', 'Original changed while being read.')
        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected.sha256:
            raise EditWorkerError('source_changed', 'Original content changed since this edit session began.')
        return canonical, before, data, digest
    except OSError as error:
        code = 'source_changed' if expected else 'source_unavailable'
        raise EditWorkerError(code, 'The original is missing or cannot be read.') from error


def _check_current(snapshot):
    try:
        current = os.stat(snapshot.path, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or _stat_identity(current) != snapshot.stat_identity:
            raise OSError('Source changed.')
    except OSError as error:
        raise EditWorkerError('source_changed', 'Original changed during rendering.') from error


def execute(request):
    # Pillow and rendering imports occur only after resource/lifetime limits apply.
    from PIL import Image
    from .edit_color import EditColorError, render_color_geometry

    expected = SourceSnapshot.from_dict(request['snapshot']) if request['snapshot'] is not None else None
    canonical, before, encoded, digest = _read_source(request['path'], expected)
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(encoded)) as opened:
            if opened.format not in ('JPEG', 'PNG', 'BMP', 'WEBP'):
                raise EditWorkerError('unsupported_source', 'This slice supports JPEG, PNG, BMP, and WebP still images only.')
            # Pillow can expose a 16-bit/color RGB PNG as RGB after reducing precision.
            if opened.format == 'PNG' and encoded[24] > 8:
                raise EditWorkerError('unsupported_source', 'High-bit-depth images are read-only.')
            try:
                stored = Size(*opened.size)
            except ValueError as error:
                raise EditWorkerError('input_limit', 'Image dimensions exceed the 40 megapixel editing limit.') from error
            if opened.mode not in ('RGB', 'RGBA'):
                raise EditWorkerError('unsupported_source', 'Only 8-bit RGB/RGBA sources are enabled in this worker slice.')
            if opened.mode == 'RGB' and 'transparency' in opened.info:
                raise EditWorkerError('unsupported_source', 'Color-key transparency needs an accepted alpha-conversion policy.')
            # For these supported formats, counts are provided without traversing frames.
            if getattr(opened, 'n_frames', 1) != 1:
                raise EditWorkerError('unsupported_source', 'Animated and multiframe images are read-only.')
            opened.load()  # Full decode, protected by child memory/CPU + parent wall limits.
            exif = opened.getexif()
            orientation = exif.get(274)
            assumed = orientation is None
            if assumed:
                orientation = 1
            if type(orientation) is not int or not 1 <= orientation <= 8:
                raise EditWorkerError('unsupported_source', 'Invalid source orientation; editing is disabled.')
            icc = opened.info.get('icc_profile')
            if icc is not None and (type(icc) is not bytes or len(icc) > MAX_PROFILE_BYTES):
                raise EditWorkerError('metadata_limit', 'Embedded profile exceeds the editing metadata budget.')
            srgb_intent = opened.info.get('srgb')
            if opened.format != 'PNG' or type(srgb_intent) is not int or srgb_intent not in range(4):
                srgb_intent = None
            snapshot = SourceSnapshot(canonical, *_stat_identity(before), digest, stored,
                                      orientation, assumed, opened.format, opened.mode,
                                      hashlib.sha256(icc).hexdigest() if icc is not None else None,
                                      srgb_intent)
            if expected and snapshot != expected:
                raise EditWorkerError('source_changed', 'Source metadata no longer matches the edit session.')
            if request['operation'] == 'prepare':
                _check_current(snapshot)
                return snapshot, None, b'', None, None
            recipe = EditRecipe.from_dict(request['recipe'])
            # Copy detaches the decoded raster from the input stream; never pass lazy pixels.
            with opened.copy() as pixels:
                rendered = render_color_geometry(pixels, recipe, orientation=orientation,
                    preview_longest=request['preview_longest'], policy=request['color_policy'],
                    assume_srgb=request['assume_srgb'])
                try:
                    raster = rendered.image.tobytes()
                    profile = rendered.image.info.get('icc_profile')
                    color = rendered.color.to_dict()
                    descriptor = {'size': list(rendered.image.size), 'mode': rendered.image.mode,
                                  'output_size': rendered.output_size.as_list(),
                                  'is_preview': rendered.is_preview, 'byte_count': len(raster)}
                finally:
                    rendered.image.close()
        _check_current(snapshot)
        return snapshot, descriptor, raster, color, profile
    except EditColorError as error:
        raise EditWorkerError(error.code, str(error)) from error
    except EditWorkerError:
        raise
    except MemoryError as error:
        raise EditWorkerError('resource_limit', 'Image exceeded the worker memory budget.') from error
    except Image.DecompressionBombError as error:
        raise EditWorkerError('input_limit', 'Image dimensions exceed the editing budget.') from error
    except (OSError, SyntaxError) as error:
        raise EditWorkerError('decode_failed', 'Image pixels could not be decoded.') from error


def _validate_request(request):
    keys = {'version', 'request_id', 'generation', 'operation', 'path', 'snapshot',
            'recipe', 'preview_longest', 'timeout', 'color_policy', 'assume_srgb'}
    if type(request) is not dict or set(request) != keys or type(request['version']) is not int or request['version'] != PROTOCOL_VERSION:
        raise ValueError('Invalid worker request fields/version.')
    if type(request['request_id']) is not str or not 1 <= len(request['request_id']) <= 128:
        raise ValueError('Invalid request ID.')
    if type(request['generation']) is not int or request['generation'] < 0:
        raise ValueError('Invalid generation.')
    if type(request['timeout']) not in (int, float) or not math.isfinite(request['timeout']) or not 0 < request['timeout'] <= MAX_TIMEOUT:
        raise ValueError('Invalid timeout.')
    if type(request['path']) is not str or not os.path.isabs(request['path']) or '\x00' in request['path']:
        raise ValueError('Invalid source path.')
    validate_color_options(request['color_policy'], request['assume_srgb'])
    if request['operation'] == 'prepare':
        if request['color_policy'] != 'legacy-v1' or request['assume_srgb']:
            raise ValueError('Preparation is color-neutral; select policy when rendering.')
        if any(request[key] is not None for key in ('snapshot', 'recipe', 'preview_longest')):
            raise ValueError('Preparation does not accept render parameters.')
    elif request['operation'] == 'render':
        snapshot = SourceSnapshot.from_dict(request['snapshot'])
        recipe = EditRecipe.from_dict(request['recipe'])
        if snapshot.path != request['path'] or recipe.source_size != snapshot.oriented_size:
            raise ValueError('Recipe/source identity mismatch.')
        if request['preview_longest'] is not None:
            from .edit_render import preview_size
            preview_size(recipe.result_size, request['preview_longest'])
    else:
        raise ValueError('Unknown worker operation.')


def main():
    header = {'version': PROTOCOL_VERSION, 'request_id': '', 'generation': 0,
              'status': 'error', 'source': None, 'render': None, 'error': None,
              'color_conversion': 'none', 'color_interpretation': 'unmanaged',
              'color': None, 'profile': None}
    raster = b''
    profile = None
    try:
        # Set budgets before parsing input or loading decoder libraries.
        _sandbox(int(sys.argv[1]), MAX_TIMEOUT)
        raw = sys.stdin.buffer.readline(MAX_HEADER_BYTES + 1)
        if len(raw) > MAX_HEADER_BYTES or not raw.endswith(b'\n'):
            raise ValueError('Worker request exceeds its envelope.')
        request = strict_json(raw)
        _validate_request(request)
        header.update(request_id=request['request_id'], generation=request['generation'])
        _sandbox(int(sys.argv[1]), request['timeout'])
        snapshot, descriptor, raster, color, profile = execute(request)
        header.update(status='ok', source=snapshot.to_dict(), render=descriptor, color=color,
                      profile=None if profile is None else {'byte_count': len(profile),
                          'sha256': hashlib.sha256(profile).hexdigest()})
        if color is not None:
            header.update(color_conversion='converted' if color['status'] == 'converted' else 'none',
                          color_interpretation=color['output_color_space'] or 'unmanaged')
    except EditWorkerError as error:
        header['error'] = {'code': error.code, 'message': str(error)}
    except MemoryError:
        header['error'] = {'code': 'resource_limit', 'message': 'Worker memory budget exceeded.'}
    except (ValueError, TypeError, KeyError, OverflowError):
        header['error'] = {'code': 'invalid_request', 'message': 'Invalid source metadata or edit request.'}
    except Exception:
        header['error'] = {'code': 'worker_failed', 'message': 'Editing worker failed safely.'}
    wire = json.dumps(header, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    if len(wire) > MAX_HEADER_BYTES:
        return 2
    sys.stdout.buffer.write(wire)
    if header['status'] == 'ok':
        sys.stdout.buffer.write(raster)
        if profile is not None:
            sys.stdout.buffer.write(profile)
    sys.stdout.buffer.flush()
    return 0 if header['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
