"""Qt-free wire validation and private endpoint discovery for UI IPC v1."""
import hashlib
import json
import os
from pathlib import Path
import stat

VERSION = 1
MAX_MESSAGE = 1024 * 1024
MAX_OUTPUT = 4 * MAX_MESSAGE
MAX_CLIENTS = 16
MAX_PENDING = 32
MAX_IDS = 1000


class ControlError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def encode(value):
    data = json.dumps(value, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    if len(data) > MAX_MESSAGE:
        raise ControlError('invalid_request', 'Message exceeds 1 MiB; request a smaller page')
    return data


def decode(data):
    if len(data) > MAX_MESSAGE:
        raise ControlError('invalid_request', 'Message exceeds 1 MiB')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON number')
    try:
        result = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
        # Also rejects overflowing exponent notation, which parse_constant does not see.
        json.dumps(result, allow_nan=False)
        if type(result) is not dict:
            raise ValueError('Expected an object')
        return result
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ControlError('invalid_request', 'Invalid JSON object') from exc


def request(data):
    value = decode(data)
    if set(value) != {'protocol_version', 'id', 'method', 'params'}:
        raise ControlError('invalid_request', 'Expected protocol_version, id, method, params')
    if type(value['protocol_version']) is not int or value['protocol_version'] != VERSION:
        raise ControlError('unsupported_protocol', 'UI IPC protocol 1 is required')
    for field in ('id', 'method'):
        if type(value[field]) is not str or not 1 <= len(value[field]) <= 128:
            raise ControlError('invalid_request', f'Invalid {field}')
    if type(value['params']) is not dict:
        raise ControlError('invalid_request', 'params must be an object')
    return value


def runtime_directory(create=False):
    raw = os.environ.get('XDG_RUNTIME_DIR', '')
    if not raw or not Path(raw).is_absolute():
        raise ControlError('unavailable', 'An absolute private XDG_RUNTIME_DIR is required')
    root = Path(raw)
    directory = root / 'image-lab'
    try:
        check_private(root)
        if create:
            directory.mkdir(mode=0o700, exist_ok=True)
        check_private(directory)
    except OSError as exc:
        raise ControlError('unavailable', 'IPC runtime directory is unavailable') from exc
    return directory


def check_private(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ControlError('unavailable', 'IPC runtime directories must be owned by you with mode 0700, without symlinks')


def endpoint(catalog, create=False):
    canonical = str(Path(catalog).expanduser().resolve())
    digest = hashlib.sha256(os.fsencode(canonical)).hexdigest()[:32]
    path = runtime_directory(create) / (digest + '.sock')
    if len(os.fsencode(path)) > 103:
        raise ControlError('unavailable', 'IPC socket path is too long; use a shorter XDG_RUNTIME_DIR')
    return path


def check_socket(path):
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ControlError('unavailable', 'Unsafe IPC socket ownership, permissions, or type')
