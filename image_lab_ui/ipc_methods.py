"""Explicit, Qt-free method inventory and parameter schema."""
from .ipc_protocol import ControlError, MAX_IDS

# A trailing '?' marks an optional parameter. Defaults are applied by handlers.
METHODS = {
    'app.status': {}, 'app.capabilities': {}, 'events.subscribe': {},
    'window.show': {}, 'window.hide': {}, 'window.focus': {}, 'window.close': {},
    'library.list': {'query?': 'text', 'filter?': 'filter', 'offset?': 'offset', 'limit?': 'limit'},
    'library.get': {'image_id': 'id'}, 'library.import': {'path': 'text'}, 'library.scan-stop': {},
    'view.search': {'query': 'text'}, 'view.filter': {'filter': 'filter'},
    'view.page': {}, 'view.reveal': {'image_id': 'id'},
    'selection.get': {}, 'selection.set': {'ids': 'ids'}, 'selection.clear': {},
    'selection.highlight': {'image_id': 'id'},
    'selection.matches': {'query?': 'text', 'filter?': 'filter'},
    'viewer.status': {}, 'viewer.open': {'image_id': 'id'}, 'viewer.close': {},
    'viewer.next': {}, 'viewer.previous': {}, 'viewer.play': {}, 'viewer.pause': {},
    'panel.open': {'panel': 'panel'}, 'panel.close': {'panel': 'panel'},
    'analyze': {'ids': 'ids', 'replace?': 'bool'},
    'analyze.missing': {'query?': 'text', 'filter?': 'filter'},
    'queue.status': {}, 'queue.list': {'offset?': 'offset', 'limit?': 'limit'},
    'queue.pause': {}, 'queue.resume': {}, 'queue.stop': {},
    'queue.retry': {'job_id': 'id'}, 'queue.remove': {'job_id': 'id'},
    'details.get': {'image_id': 'id'},
    'details.update': {'image_id': 'id', 'revision': 'text', 'values': 'object'},
    'rename.preview': {'image_id': 'id', 'expected_path': 'text', 'name': 'text'},
    'rename.apply': {'image_id': 'id', 'expected_path': 'text', 'name': 'text', 'confirmation': 'text'},
    'settings.get': {}, 'settings.set': {'values': 'object'},
    'operation.get': {'operation_id': 'text'},
}


def validate(method, params):
    if method not in METHODS:
        raise ControlError('unknown_method', 'Unknown control method')
    schema = METHODS[method]
    required = {key for key in schema if not key.endswith('?')}
    allowed = {key.rstrip('?') for key in schema}
    if not required <= params.keys() or params.keys() - allowed:
        raise ControlError('invalid_request', 'Missing or unknown parameters')
    for key, kind in schema.items():
        key = key.rstrip('?')
        if key not in params:
            continue
        value = params[key]
        valid = False
        if kind == 'text':
            valid = type(value) is str and len(value) <= 4096 and '\x00' not in value
        elif kind in ('id', 'offset', 'limit'):
            low, high = {'id': (1, 2**63-1), 'offset': (0, 2**31-1), 'limit': (1, 200)}[kind]
            valid = type(value) is int and low <= value <= high
        elif kind == 'bool':
            valid = type(value) is bool
        elif kind == 'object':
            valid = type(value) is dict
        elif kind == 'ids':
            valid = (type(value) is list and len(value) <= MAX_IDS and
                     all(type(i) is int and 1 <= i <= 2**63-1 for i in value) and len(set(value)) == len(value))
        elif kind == 'filter':
            valid = type(value) is str and value in ('all', 'needs_tags', 'tagged', 'failed')
        elif kind == 'panel':
            valid = type(value) is str and value in ('queue', 'settings', 'details', 'about')
        if not valid:
            raise ControlError('invalid_request', f'Invalid {key}: expected {kind}')
    return params
