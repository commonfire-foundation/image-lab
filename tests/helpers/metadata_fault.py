"""Deterministic private-process faults for the viewer's metadata supervisor."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_lab_ui.image_services import inspect_file

mode = sys.argv[1]
request = json.loads(sys.stdin.buffer.readline())
if mode == 'hang' or (mode == 'slow-first' and Path(request['key'][1]).stem == 'landscape'):
    time.sleep(30)
if mode == 'crash':
    raise SystemExit(9)
if mode == 'malformed':
    print('{broken')
    raise SystemExit()
if mode == 'oversized':
    sys.stdout.write('x' * (1024 * 1024 + 1))
    raise SystemExit()
if mode == 'stderr':
    sys.stderr.write('x' * 17000)
    sys.stderr.flush()
    time.sleep(30)
measurements = len(sys.argv) > 2 and sys.argv[2] == 'measurements'
if measurements:
    from image_lab_ui.measurement_services import measure_file
    request['view'] = measure_file(request['key'][1], request['key'][2:])
else:
    request['view'] = inspect_file(request['key'][1], request['key'][2:])
if mode == 'stale':
    request['generation'] -= 1
if mode == 'wrong-key':
    request['key'][2] -= 1
if mode == 'wrong-source':
    request['view']['source']['path'] += '.old'
if mode == 'revision':
    request['view']['source']['revision'][3] -= 1
if mode == 'version':
    if measurements:
        request['view']['result']['provenance']['measurements_version'] = 99
    else:
        request['view']['metadataVersion'] = 2
wire = json.dumps(request)
if mode == 'duplicate':
    wire = '{"generation":-1,' + wire[1:]
print(wire)
