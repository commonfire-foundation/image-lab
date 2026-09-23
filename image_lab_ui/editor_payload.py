"""Bounded, cancellable payload transport for editor encoding and measurements."""
import hashlib
import json
import math
import os
import sys
from uuid import uuid4

from .edit_protocol import EditWorkerError, MAX_HEADER_BYTES, MAX_TIMEOUT, strict_json


def request_payload(module, values, *, limit, timeout=60, cancelled=lambda: False):
    from .edit_process import _run
    request = dict(values, version=1, request_id=uuid4().hex, generation=0, timeout=timeout)
    def header(raw, request):
        try:
            value = strict_json(raw)
            if (type(value) is not dict or set(value) != {'version', 'request_id', 'generation', 'status', 'error', 'info', 'payload'}
                    or type(value['version']) is not int or value['version'] != 1
                    or type(value['generation']) is not int or value['generation'] != 0):
                raise ValueError('Invalid payload header.')
            startup = value['status'] == 'error' and value['request_id'] == ''
            if not startup and (value['request_id'] != request['request_id'] or value['generation'] != 0):
                raise ValueError('Payload request mismatch.')
            if value['status'] == 'error':
                error = value['error']
                if (type(error) is not dict or set(error) != {'code', 'message'}
                        or not isinstance(error['code'], str) or not isinstance(error['message'], str)
                        or not 1 <= len(error['code']) <= 128 or len(error['message']) > 2048
                        or value['payload'] is not None or value['info'] is not None):
                    raise ValueError('Invalid payload error.')
                return value, 0
            if type(value['payload']) is not dict or set(value['payload']) != {'size', 'sha256'}:
                raise ValueError('Invalid payload fields.')
            size = value['payload']['size']
            digest = value['payload']['sha256']
            if (value['status'] != 'ok' or value['error'] is not None or type(value['info']) is not dict
                    or type(size) is not int or not 0 < size <= limit
                    or type(digest) is not str or len(digest) != 64):
                raise ValueError('Invalid payload descriptor.')
            return value, size
        except (ValueError, TypeError, KeyError) as error:
            raise EditWorkerError('protocol_error', 'Invalid editor payload response.') from error
    result, payload, _ = _run(request, cancelled, worker_module=module, header_decoder=header, payload_only=True)
    if hashlib.sha256(payload).hexdigest() != result['payload']['sha256']:
        raise EditWorkerError('protocol_error', 'Encoded payload digest mismatch.')
    return result['info'], payload


def worker_main(handler, keys, limit):
    from .edit_worker import _sandbox
    header = dict(version=1, request_id='', generation=0, status='error', error=None, info=None, payload=None)
    payload = b''
    try:
        _sandbox(int(sys.argv[1]), MAX_TIMEOUT)
        raw = sys.stdin.buffer.readline(MAX_HEADER_BYTES + 1)
        if len(raw) > MAX_HEADER_BYTES or not raw.endswith(b'\n'):
            raise ValueError('Request exceeds budget.')
        request = strict_json(raw)
        if (type(request) is not dict or set(request) != set(keys) | {'version', 'request_id', 'generation', 'timeout'}
                or type(request['version']) is not int or request['version'] != 1 or type(request['request_id']) is not str
                or not 1 <= len(request['request_id']) <= 128 or type(request['generation']) is not int or request['generation'] != 0
                or type(request['timeout']) not in (int, float) or not math.isfinite(request['timeout'])
                or not 0 < request['timeout'] <= MAX_TIMEOUT):
            raise ValueError('Invalid payload request.')
        header.update(request_id=request['request_id'])
        _sandbox(int(sys.argv[1]), request['timeout'])
        info, payload = handler(request)
        if type(payload) is not bytes or not 0 < len(payload) <= limit:
            raise EditWorkerError('output_limit', 'Encoded payload exceeds its budget.')
        header.update(status='ok', info=info, payload={'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
    except EditWorkerError as error:
        header['error'] = {'code': error.code, 'message': str(error)[:2048]}
    except Exception as error:
        header['error'] = {'code': 'payload_failed', 'message': str(error)[:2048] or 'Editor worker failed.'}
    wire = json.dumps(header, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    if len(wire) > MAX_HEADER_BYTES:
        return 2
    sys.stdout.buffer.write(wire)
    if header['status'] == 'ok': sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    return 0 if header['status'] == 'ok' else 1
