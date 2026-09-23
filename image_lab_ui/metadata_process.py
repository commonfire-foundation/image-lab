"""Private metadata API bridge. All source I/O lives in this disposable process."""
import ctypes
import json
import os
import signal
import sys

from .image_services import MAX_METADATA_BYTES, inspect_file, metadata_error


def main(inspector=inspect_file):
    generation = -1
    key = None
    try:
        if not sys.platform.startswith('linux'):
            raise ValueError('Metadata process isolation requires Linux.')
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise ValueError('Cannot install parent-lifetime guard.')
        if os.getppid() != int(sys.argv[1]):
            return 1
        wire = sys.stdin.buffer.readline(16385)
        if len(wire) > 16384 or not wire.endswith(b'\n'):
            raise ValueError('Invalid metadata request size.')
        request = json.loads(wire)
        generation, key = request['generation'], request['key']
        if (type(generation) is not int or generation < 0 or type(key) is not list or len(key) != 4
                or type(key[0]) is not int or type(key[1]) is not str
                or type(key[2]) is not int or type(key[3]) is not int):
            raise ValueError('Invalid metadata load revision.')
        view = inspector(key[1], (key[2], key[3]))
    except Exception:
        view = metadata_error('metadata_process_failed', 'The metadata process could not inspect this source.')
    result = {'generation': generation, 'key': key, 'view': view}
    wire = json.dumps(result, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    if len(wire) > MAX_METADATA_BYTES:
        result['view'] = metadata_error('metadata_output_limit', 'Metadata presentation exceeded its output budget.')
        wire = json.dumps(result, separators=(',', ':')).encode() + b'\n'
    sys.stdout.buffer.write(wire)
    sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
