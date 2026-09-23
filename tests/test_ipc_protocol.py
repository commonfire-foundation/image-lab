import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from image_lab_ui.ipc_protocol import ControlError, decode, encode, request, endpoint, MAX_MESSAGE
from image_lab_ui.ipc_methods import METHODS, validate
from image_lab_ui.control_cli import parser


class ProtocolTests(unittest.TestCase):
    def test_strict_json_and_envelopes(self):
        good = {'protocol_version': 1, 'id': 'a', 'method': 'app.status', 'params': {}}
        self.assertEqual(request(encode(good)), good)
        for raw in (b'[]', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'\xff', b'{'):
            with self.subTest(raw=raw), self.assertRaises(ControlError):
                decode(raw)
        for bad in ({**good, 'extra': 1}, {**good, 'protocol_version': True},
                    {**good, 'params': []}, {**good, 'id': ''}):
            with self.assertRaises(ControlError):
                request(json.dumps(bad))
        with self.assertRaises(ControlError):
            decode(b'x' * (MAX_MESSAGE + 1))

    def test_every_method_rejects_unknown_parameters(self):
        for method in METHODS:
            with self.subTest(method=method), self.assertRaises(ControlError):
                validate(method, {'not_a_parameter': True})
        for method, params in [('library.get', {'image_id': True}),
                               ('selection.set', {'ids': [1, 1]}),
                               ('selection.set', {'ids': list(range(1, 1002))}),
                               ('library.list', {'limit': 201}),
                               ('library.list', {'offset': -1}),
                               ('view.filter', {'filter': 'bad'}),
                               ('panel.open', {'panel': '__dict__'})]:
            with self.assertRaises(ControlError):
                validate(method, params)

    def test_endpoint_privacy_and_canonical_identity(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(root)}):
                a = endpoint(root / 'catalog', create=True)
                self.assertEqual(a, endpoint(root / 'x/../catalog'))
                self.assertEqual(a.parent.stat().st_mode & 0o777, 0o700)
                root.chmod(0o755)
                with self.assertRaises(ControlError):
                    endpoint(root / 'catalog')
                root.chmod(0o700)
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': ''}):
                with self.assertRaises(ControlError):
                    endpoint(root)

    def test_cli_parsing_is_qt_free_and_options_work_at_both_ends(self):
        for argv in (['--json','--data-dir','/catalog','status'],
                     ['status','--json','--data-dir','/catalog']):
            args = parser().parse_args(argv)
            self.assertEqual(args.method, 'app.status')
            self.assertEqual(args.data_dir, '/catalog')
            self.assertTrue(args.json)
        self.assertEqual(parser().parse_args(['rename','apply','1','--expected-path','/a.png',
                         '--name','b.png','--confirm','token']).confirmation, 'token')
