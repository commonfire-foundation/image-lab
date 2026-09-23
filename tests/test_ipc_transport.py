import importlib.util
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from image_lab_ui.ipc_client import Client
from image_lab_ui.ipc_protocol import ControlError, MAX_OUTPUT, encode


class ClientTransportTests(unittest.TestCase):
    def test_timeout_does_not_retry(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            path = Path(temp) / 's'
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen(1)
            stop = threading.Event()
            seen = []
            def serve():
                connection, _ = server.accept()
                with connection:
                    connection.sendall(encode({'protocol_version':1, 'type':'hello',
                                               'instance_id':'test', 'catalog':temp}))
                    seen.append(connection.recv(65536))
                    stop.wait(2)
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                with Client(path=path, timeout=0.05) as client:
                    with self.assertRaises(ControlError) as error:
                        client.call('app.status')
                    self.assertEqual(error.exception.code, 'timeout')
            finally:
                stop.set()
                thread.join(timeout=3)
                server.close()
            self.assertEqual(len(seen), 1)

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Requires Qt')
    def test_output_backpressure_disconnects_instead_of_dropping_events(self):
        from image_lab_ui.ipc_server import Peer
        class Connection:
            def bytesToWrite(self):
                return MAX_OUTPUT
            def write(self, value):
                raise AssertionError('Should not queue more output')
        class SlowPeer:
            closed = False
            connection = Connection()
            def abort(self):
                self.closed = True
        peer = SlowPeer()
        Peer.send(peer, {'protocol_version':1, 'type':'event'})
        self.assertTrue(peer.closed)
