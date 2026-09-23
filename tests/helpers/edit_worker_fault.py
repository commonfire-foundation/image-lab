"""Test-only worker failures; launched with repository cwd and no user images."""
import json
import os
from pathlib import Path
import signal
import sys
import time

# Script-directory invocation would otherwise omit the repository package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_lab_ui.edit_worker import _sandbox
from image_lab_ui.edit_protocol import MEMORY_BYTES, PROTOCOL_VERSION
from image_lab_ui.edit_color import ColorProvenance
import hashlib

mode = sys.argv[1]
request = json.loads(sys.stdin.buffer.readline())
if mode == 'hang':
    time.sleep(60)
    raise SystemExit(0)
if mode == 'crash':
    os._exit(3)
if mode == 'signal':
    os.kill(os.getpid(), signal.SIGKILL)
if mode == 'cpu':
    _sandbox(os.getppid(), 1)
    while True:
        pass
if mode == 'header_flood':
    sys.stdout.buffer.write(b'x' * 100000)
    sys.stdout.buffer.flush()
    time.sleep(60)
if mode == 'stderr_flood':
    sys.stderr.buffer.write(b'x' * 100000)
    sys.stderr.buffer.flush()
    time.sleep(60)

source = request['snapshot']
size = request['recipe']['output_size'] or source['stored_size']
length = size[0] * size[1] * (4 if source['mode'] == 'RGBA' else 3)
managed = request['color_policy'] == 'srgb-v1'
converted = managed and source['icc_sha256'] is not None
profile = b''
if converted:
    from PIL import ImageCms
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
color = ColorProvenance(request['color_policy'], request['assume_srgb'],
    'converted' if converted else 'assumed_srgb' if managed else 'unmanaged',
    source['mode'], 'embedded_icc' if converted else 'assumed_srgb' if managed else 'unknown',
    source['icc_sha256'], 'srgb' if managed else None,
    'relative-colorimetric' if converted else None, False, 'disabled' if converted else None,
    'color_before_orientation_crop_rotate_flip_resize' if managed else None,
    'test-pillow', 'test-cms' if converted else None).to_dict()
header = {'version': PROTOCOL_VERSION, 'request_id': request['request_id'], 'generation': request['generation'],
          'status': 'ok', 'source': source, 'error': None,
          'color_conversion': 'converted' if converted else 'none',
          'color_interpretation': 'srgb' if managed else 'unmanaged', 'color': color,
          'profile': {'byte_count': len(profile), 'sha256': hashlib.sha256(profile).hexdigest()} if converted else None,
          'render': {'size': size, 'output_size': size, 'mode': source['mode'],
                     'is_preview': request['preview_longest'] is not None, 'byte_count': length}}
exit_code = 0
if mode == 'memory':
    _sandbox(os.getppid(), 5)
    try:
        allocation = bytearray(MEMORY_BYTES)
    except MemoryError:
        header.update(status='error', source=None, render=None, color=None, profile=None,
                      error={'code': 'resource_limit', 'message': 'Memory limit enforced.'})
        length = 0
        exit_code = 1
if mode == 'stale':
    header['generation'] += 1
if mode == 'wrong_id':
    header['request_id'] = 'some-other-request'
if mode == 'wrong_dimensions':
    header['render']['size'][0] += 1
if mode == 'preview_mismatch':
    header['render']['is_preview'] = not header['render']['is_preview']
if mode == 'color_claim':
    header['color_conversion'] = 'srgb'
if mode == 'oversized':
    header['render']['byte_count'] = 10 ** 12
if mode == 'false_declaration':
    header['color'].update(status='declared_srgb', source_interpretation='declared_srgb')
if mode == 'old_version':
    header['version'] = 1
if mode == 'wrong_policy':
    header['color']['policy'] = 'legacy-v1' if managed else 'srgb-v1'
if mode == 'wrong_assumption':
    header['color']['assume_srgb'] = not request['assume_srgb']
if mode == 'wrong_icc_identity':
    header['color']['source_profile_sha256'] = '0' * 64
if mode == 'wrong_intent':
    header['color']['rendering_intent'] = 'perceptual'
if mode == 'wrong_order':
    header['color']['order'] = 'resize-before-color'
if mode == 'bpc':
    header['color']['black_point_compensation'] = True
if mode == 'optimization':
    header['color']['transform_optimization'] = None
if mode == 'missing_color':
    header['color'] = None
if mode == 'profile_hash':
    header['profile']['sha256'] = '0' * 64
if mode == 'profile_large':
    header['profile']['byte_count'] = 1024 * 1024 + 1
if mode == 'profile_missing':
    header['profile'] = None
if mode == 'profile_header':
    profile = b'bad!' + profile[4:]
    header['profile']['sha256'] = hashlib.sha256(profile).hexdigest()
if mode == 'profile_truncated':
    profile = profile[:-1]
wire = json.dumps(header).encode()
if mode == 'duplicate':
    wire = b'{"version":1,' + wire[1:]
sys.stdout.buffer.write(wire + b'\n')
if mode == 'truncated':
    length -= 1
elif mode == 'extra':
    length += 1
sys.stdout.buffer.write(b'\0' * max(0, length))
sys.stdout.buffer.write(profile)
sys.stdout.buffer.flush()
raise SystemExit(exit_code)
