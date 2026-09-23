"""Standard-library client. Never launches a GUI, retries writes, or opens a DB."""
import socket
import time
import uuid
from pathlib import Path

from .ipc_protocol import (VERSION, MAX_MESSAGE, ControlError, encode, decode,
                           endpoint, runtime_directory, check_socket)


class Client:
    def __init__(self, catalog=None, *, path=None, timeout=10):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.buffer = b''
        self.timeout = timeout
        try:
            target = Path(path) if path else endpoint(catalog)
            check_socket(target)
            self.socket.settimeout(2)
            self.socket.connect(str(target))
            self.hello = self.receive(timeout)
            if (self.hello.get('type') != 'hello' or self.hello.get('protocol_version') != VERSION
                    or not isinstance(self.hello.get('instance_id'), str)
                    or not isinstance(self.hello.get('catalog'), str)):
                raise ControlError('unsupported_protocol', 'Incompatible UI IPC server')
            if catalog is not None and self.hello.get('catalog') != str(Path(catalog).expanduser().resolve()):
                raise ControlError('conflict', 'Server catalog does not match requested catalog')
        except Exception as exc:
            self.socket.close()
            if isinstance(exc, ControlError):
                raise
            raise ControlError('unavailable', 'No reachable Image Lab GUI for this catalog') from exc

    def close(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def receive(self, timeout=None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        try:
            while b'\n' not in self.buffer:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError()
                self.socket.settimeout(left)
                chunk = self.socket.recv(min(65536, MAX_MESSAGE + 1 - len(self.buffer)))
                if not chunk:
                    raise ControlError('unavailable', 'IPC connection closed; resnapshot before retrying a mutation')
                self.buffer += chunk
                if len(self.buffer) > MAX_MESSAGE and b'\n' not in self.buffer:
                    raise ControlError('invalid_request', 'Oversized server response')
            line, self.buffer = self.buffer.split(b'\n', 1)
            value = decode(line)
            if value.get('protocol_version') != VERSION:
                raise ControlError('unsupported_protocol', 'Incompatible server message')
            return value
        except TimeoutError as exc:
            raise ControlError('timeout', 'IPC deadline exceeded; accepted work may still be running') from exc
        except OSError as exc:
            raise ControlError('unavailable', 'IPC transport failed') from exc

    def call(self, method, params=None):
        request_id = uuid.uuid4().hex
        try:
            self.socket.settimeout(self.timeout)
            self.socket.sendall(encode({'protocol_version': VERSION, 'id': request_id,
                                       'method': method, 'params': params or {}}))
        except OSError as exc:
            raise ControlError('unavailable', 'IPC send failed; mutation outcome may be unknown') from exc
        response = self.receive()
        if response.get('id') != request_id or ('result' in response) == ('error' in response):
            raise ControlError('invalid_request', 'Uncorrelated or malformed IPC response')
        if 'error' in response:
            error = response['error']
            if (type(error) is not dict or type(error.get('code')) is not str
                    or type(error.get('message')) is not str):
                raise ControlError('invalid_request', 'Malformed server error')
            raise ControlError(error['code'], error['message'])
        return response['result']


def instances():
    found = []
    for path in sorted(runtime_directory().glob('*.sock'))[:64]:
        try:
            with Client(path=path, timeout=2) as client:
                found.append(client.hello)
        except (ControlError, OSError):
            continue
    return found
