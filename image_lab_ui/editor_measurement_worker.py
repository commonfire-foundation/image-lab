"""Disposable bounded public-API inspection worker for managed editor sources."""
from .editor_payload import worker_main


def execute(request):
    import json
    from .analyzer_client import inspect_measurements
    from .edit_protocol import SourceSnapshot, validate_color_options
    from .edit_worker import _check_current
    source = SourceSnapshot.from_dict(request['source'])
    validate_color_options(request['policy'], request['assumption'])
    if request['policy'] != 'srgb-v1': raise ValueError('Managed measurements require sRGB.')
    _check_current(source)
    result = inspect_measurements(source.path, color_policy=request['policy'], assume_srgb=request['assumption'])
    _check_current(source)
    return {key: request[key] for key in ('source','policy','assumption')}, json.dumps(result, allow_nan=False, separators=(',', ':')).encode()


if __name__ == '__main__':
    raise SystemExit(worker_main(execute, {'source','policy','assumption'}, 1024 * 1024))
