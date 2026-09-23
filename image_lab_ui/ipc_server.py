"""Bounded Qt local transport; instantiated only while holding the catalog lock."""
from collections import deque
import os
import socket

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer

from .ipc_protocol import (VERSION, MAX_MESSAGE, MAX_OUTPUT, MAX_CLIENTS, MAX_PENDING,
                           ControlError, encode, request, endpoint, check_socket)


class Peer(QObject):
    def __init__(self, server, connection):
        super().__init__(server)
        self.server = server
        self.connection = connection
        self.buffer = b''
        self.pending = deque()
        self.ids = set()
        self.subscribed = False
        self.closed = False
        self.scheduled = False
        connection.setReadBufferSize(MAX_MESSAGE + 1)
        connection.readyRead.connect(self.read)
        connection.disconnected.connect(self.close)
        self.timer = QTimer(self)
        self.timer.setInterval(10000)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.abort)
        self.send(server.router.hello())

    def close(self):
        if not self.closed:
            self.closed = True
            self.timer.stop()
            self.server.peers.discard(self)
            self.connection.deleteLater()
            self.deleteLater()

    def abort(self):
        self.connection.abort()
        self.close()

    def send(self, value):
        if self.closed:
            return
        data = encode(value)
        if self.connection.bytesToWrite() + len(data) > MAX_OUTPUT:
            self.abort()
            return
        self.connection.write(data)

    def read(self):
        if self.closed:
            return
        self.buffer += bytes(self.connection.read(MAX_MESSAGE + 1 - len(self.buffer)))
        try:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                item = request(line)
                if len(self.pending) >= MAX_PENDING or item['id'] in self.ids:
                    raise ControlError('invalid_request', 'Too many pending requests or duplicate in-flight ID')
                self.pending.append(item)
                self.ids.add(item['id'])
            if len(self.buffer) > MAX_MESSAGE:
                raise ControlError('invalid_request', 'Oversized partial message')
        except ControlError as exc:
            self.send({'protocol_version': VERSION, 'id': None,
                       'error': {'code': exc.code, 'message': str(exc)}})
            self.pending.clear()
            self.connection.disconnectFromServer()
            return
        if self.buffer:
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()
        if self.pending and not self.scheduled:
            self.scheduled = True
            QTimer.singleShot(0, self.process)

    def process(self):
        self.scheduled = False
        if self.closed or not self.pending:
            return
        item = self.pending.popleft()
        response = {'protocol_version': VERSION, 'id': item['id']}
        try:
            result = self.server.router.dispatch(item['method'], item['params'])
            response['result'] = result
            self.send(response)
            if item['method'] == 'events.subscribe':
                self.subscribed = True
        except ControlError as exc:
            response.pop('result', None)
            response['error'] = {'code': exc.code, 'message': str(exc)}
            self.send(response)
        except Exception:
            response.pop('result', None)
            response['error'] = {'code': 'internal_error', 'message': 'Application operation failed'}
            self.send(response)
        self.ids.discard(item['id'])
        if self.pending:
            self.scheduled = True
            QTimer.singleShot(0, self.process)
        if self.connection.bytesAvailable():
            QTimer.singleShot(0, self.read)


class ControlServer(QObject):
    def __init__(self, router, catalog):
        super().__init__(router)
        self.router = router
        self.peers = set()
        self.path = endpoint(catalog, create=True)
        if self.path.exists() or self.path.is_symlink():
            check_socket(self.path)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                try:
                    probe.connect(str(self.path))
                except ConnectionRefusedError:
                    self.path.unlink()
                except OSError as exc:
                    raise ControlError('unavailable', 'Cannot establish stale socket ownership') from exc
                else:
                    raise ControlError('conflict', 'A server already owns this endpoint')
        self.listener = QLocalServer(self)
        self.listener.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.listener.setMaxPendingConnections(MAX_CLIENTS)
        if not self.listener.listen(str(self.path)):
            raise ControlError('unavailable', 'Cannot listen on the IPC socket')
        os.chmod(self.path, 0o600)
        check_socket(self.path)
        self.identity = self.path.stat().st_ino
        self.listener.newConnection.connect(self.accept)
        router.eventReady.connect(self.broadcast)

    def accept(self):
        while self.listener.hasPendingConnections():
            connection = self.listener.nextPendingConnection()
            if len(self.peers) >= MAX_CLIENTS:
                connection.abort()
                connection.deleteLater()
            else:
                self.peers.add(Peer(self, connection))

    def broadcast(self, event):
        for peer in tuple(self.peers):
            if peer.subscribed:
                try:
                    peer.send(event)
                except ControlError:
                    peer.abort()

    def close(self):
        for peer in tuple(self.peers):
            peer.abort()
        # QLocalServer removes its listening endpoint on close. The catalog lock
        # prevents another legitimate instance from replacing it in the meantime.
        self.listener.close()
