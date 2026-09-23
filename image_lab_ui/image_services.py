"""Imagescope metadata-v1 adapter. No Pillow decoding or analysis validation.

inspect_file is blocking: production calls belong in metadata_process, not the Qt
thread. Filesystem facts supplement the provider; no alternate metadata parser is
used on errors or unsupported versions.
"""
from datetime import datetime
import json
from math import gcd, isfinite
from pathlib import Path
import re

MAX_METADATA_BYTES = 1024 * 1024
METADATA_VERSION = 1


class MetadataContractError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise MetadataContractError(message)


def _text(value, limit=1024):
    return type(value) is str and len(value) <= limit


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _finite_number(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


def _digest(value):
    return _text(value, 64) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _object(value, fields):
    if type(value) is not dict or not set(fields) <= value.keys():
        raise MetadataContractError('Missing metadata fields.')
    return value


def validate_metadata_result(result):
    """Validate only metadata-v1; additive fields are allowed, never guessed."""
    try:
        encoded = json.dumps(result, allow_nan=False).encode()
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise MetadataContractError('Metadata is not bounded, finite JSON.') from error
    _require(len(encoded) <= MAX_METADATA_BYTES, 'Metadata exceeds the result budget.')
    result = _object(result, ('metadata_version', 'status', 'input', 'metadata', 'warnings', 'error', 'elapsed_seconds'))
    _require(type(result['metadata_version']) is int and result['metadata_version'] == METADATA_VERSION,
             'Unsupported Imagescope metadata version; this app requires metadata-v1.')
    _require(result['status'] in ('ok', 'error'), 'Unknown metadata status.')
    elapsed = result['elapsed_seconds']
    _require(_finite_number(elapsed) and elapsed >= 0, 'Invalid metadata timing.')
    notices = result['warnings']
    _require(type(notices) is list and len(notices) <= 32, 'Invalid metadata warnings.')
    for notice in notices:
        notice = _object(notice, ('code', 'field', 'message'))
        _require(_text(notice['code'], 128) and _text(notice['field'], 128)
                 and _text(notice['message'], 2048), 'Invalid structured warning.')
    _require(type(result['input']) is dict, 'Invalid metadata input identity.')
    if result['input']:
        identity = _object(result['input'], ('sha256', 'size_bytes'))
        _require(_digest(identity['sha256']) and _integer(identity['size_bytes'])
                 and identity['size_bytes'] <= 64 * 1024 * 1024, 'Invalid input digest/size.')
    if result['status'] == 'error':
        error = _object(result['error'], ('code', 'message'))
        _require(_text(error['code'], 128) and _text(error['message'], 2048)
                 and result['metadata'] is None, 'Invalid metadata error.')
        return result
    _require(result['error'] is None and bool(result['input']), 'Incomplete successful metadata result.')
    facts = _object(result['metadata'], ('format', 'mode', 'stored_size', 'oriented_size',
                     'orientation', 'orientation_assumed', 'has_alpha_channel', 'exif', 'icc', 'sequence', 'color_conversion'))
    _require(_text(facts['format'], 32) and bool(facts['format'])
             and _text(facts['mode'], 32) and bool(facts['mode']), 'Invalid format/mode.')
    for name in ('stored_size', 'oriented_size'):
        size = _object(facts[name], ('width', 'height'))
        _require(_integer(size['width'], 1) and _integer(size['height'], 1)
                 and size['width'] * size['height'] <= 500_000_000, 'Invalid image dimensions.')
    orientation = facts['orientation']
    _require(orientation is None or (type(orientation) is int and 1 <= orientation <= 8), 'Invalid orientation.')
    _require(type(facts['orientation_assumed']) is bool and facts['orientation_assumed'] == (orientation is None),
             'Invalid orientation assumption.')
    stored, oriented = facts['stored_size'], facts['oriented_size']
    expected = (stored['height'], stored['width']) if orientation in (5, 6, 7, 8) else (stored['width'], stored['height'])
    _require((oriented['width'], oriented['height']) == expected, 'Inconsistent oriented dimensions.')
    _require(facts['has_alpha_channel'] is None or type(facts['has_alpha_channel']) is bool, 'Invalid alpha declaration.')
    _require(facts['color_conversion'] == 'none', 'Metadata unexpectedly claims pixel conversion.')
    exif = _object(facts['exif'], ('status', 'tags'))
    _require(exif['status'] in ('present', 'absent', 'unknown', 'invalid', 'omitted'), 'Unknown EXIF state.')
    _require(type(exif['tags']) is dict and len(exif['tags']) <= 64, 'Invalid EXIF fields.')
    for key, value in exif['tags'].items():
        _require(type(key) is str and len(key) <= 12 and key.isdigit(), 'Invalid EXIF tag identifier.')
        _require(value is None or type(value) in (bool, int, float) or _text(value, 512), 'Invalid EXIF value.')
    icc = _object(facts['icc'], ('status', 'size_bytes', 'sha256', 'description', 'color_space'))
    _require(icc['status'] in ('present', 'absent', 'invalid', 'omitted', 'unavailable', 'unknown'), 'Unknown ICC state.')
    _require(icc['size_bytes'] is None or _integer(icc['size_bytes']), 'Invalid ICC size.')
    _require(icc['sha256'] is None or _digest(icc['sha256']), 'Invalid ICC identity.')
    for name in ('description', 'color_space'):
        _require(icc[name] is None or _text(icc[name], 512), 'Invalid ICC description.')
    sequence = _object(facts['sequence'], ('kind', 'count', 'animated', 'loop', 'first_frame_duration_ms'))
    _require(sequence['kind'] in ('frames', 'pages'), 'Invalid sequence type.')
    _require(sequence['count'] is None or _integer(sequence['count'], 1), 'Invalid sequence count.')
    _require(sequence['animated'] is None or type(sequence['animated']) is bool, 'Invalid animation state.')
    _require(sequence['loop'] is None or type(sequence['loop']) is int, 'Invalid loop declaration.')
    duration = sequence['first_frame_duration_ms']
    _require(duration is None or _finite_number(duration), 'Invalid frame duration.')
    return result


def metadata_error(code, message):
    return {'provider': 'Imagescope', 'metadataVersion': None, 'groups': [], 'warnings': [],
            'error': message, 'errorCode': code, 'source': None, 'metadata': None}


def _display(value):
    if value is None:
        return 'Unknown'
    if type(value) is bool:
        return 'Yes' if value else 'No'
    return ' '.join(str(value).replace('\x00', '').split())[:512]


def _size_text(value):
    return f"{value['width']:,} × {value['height']:,} px"


def _bytes_text(value):
    if value is None:
        return 'Unknown'
    return f'{value:,} bytes' if value < 1024 else f'{value / 1024:,.1f} KiB · {value:,} bytes'


def present_metadata(result, path, modified=None):
    result = validate_metadata_result(result)
    if result['status'] == 'error':
        view = metadata_error(result['error']['code'], result['error']['message'])
        view.update(metadataVersion=1, warnings=result['warnings'])
        return view
    facts = result['metadata']
    oriented = facts['oriented_size']
    divisor = gcd(oriented['width'], oriented['height'])
    rows = []

    def row(label, value):
        rows.append({'label': label, 'value': _display(value)})

    row('Format', facts['format'])
    row('Stored dimensions', _size_text(facts['stored_size']))
    row('Oriented dimensions', _size_text(oriented) + (' · assumed orientation' if facts['orientation_assumed'] else ''))
    row('Megapixels', f"{oriented['width'] * oriented['height'] / 1_000_000:.2f} MP")
    row('Aspect ratio', f"{oriented['width'] // divisor}:{oriented['height'] // divisor}")
    row('EXIF orientation', 'Unknown · dimensions assume 1' if facts['orientation'] is None else facts['orientation'])
    row('Color mode', facts['mode'])
    row('Alpha / transparency declared', facts['has_alpha_channel'])
    row('Pixel color conversion', 'None · source color space is not assumed')
    row('Resolution (DPI)', 'Unavailable in metadata-v1')
    groups = [{'title': 'IMAGE', 'rows': rows}]
    rows = []
    icc = facts['icc']
    states = {'present': 'Embedded', 'absent': 'Not embedded', 'invalid': 'Invalid profile',
              'omitted': 'Parsing omitted', 'unavailable': 'Parser unavailable', 'unknown': 'Unknown'}
    row('ICC profile', states[icc['status']])
    if icc['status'] != 'absent':
        row('Description', icc['description'])
        row('Profile color space', icc['color_space'])
        row('Profile size', _bytes_text(icc['size_bytes']))
        row('Profile SHA-256', icc['sha256'])
    row('Interpretation', 'Profile identification only · not converted or verified sRGB')
    groups.append({'title': 'COLOR PROFILE', 'rows': rows})
    rows = []
    sequence = facts['sequence']
    row('Sequence type', sequence['kind'].capitalize())
    row('Page count' if sequence['kind'] == 'pages' else 'Frame count', sequence['count'])
    row('Animated', sequence['animated'])
    row('Loop declaration', sequence['loop'])
    row('First frame duration', None if sequence['first_frame_duration_ms'] is None else f"{sequence['first_frame_duration_ms']:g} ms")
    groups.append({'title': 'SEQUENCE', 'rows': rows})
    rows = []
    row('EXIF status', facts['exif']['status'].capitalize())
    tags = facts['exif']['tags']
    # Only a safe named subset is displayed; arbitrary/GPS/vendor tags stay hidden.
    for tag, label in [('271', 'Camera make'), ('272', 'Camera model'), ('36867', 'Captured'),
                       ('42036', 'Lens'), ('33434', 'Exposure'), ('33437', 'Aperture'),
                       ('34855', 'ISO'), ('37386', 'Focal length'), ('305', 'Software'),
                       ('315', 'Artist'), ('33432', 'Copyright')]:
        if tag in tags:
            row(label, tags[tag])
    row('Metadata scope', 'Top-level EXIF only; nested lens/exposure fields are unavailable')
    groups.append({'title': 'EMBEDDED METADATA', 'rows': rows})
    rows = []
    path = Path(path)
    row('Name', path.name)
    row('Size', _bytes_text(result['input']['size_bytes']))
    row('Modified', modified)
    row('Location', str(path.parent))
    row('Source SHA-256', result['input']['sha256'])
    groups.append({'title': 'FILE', 'rows': rows})
    return {'provider': 'Imagescope', 'metadataVersion': 1, 'groups': groups,
            'warnings': result['warnings'], 'error': '', 'errorCode': '',
            'source': result['input'], 'metadata': facts}


def _identity(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def inspect_file(path, fingerprint=None):
    """Public API call + filesystem revision checks; use only off the UI thread."""
    try:
        from imagescope import MetadataRequest, inspect_metadata
    except ImportError:
        return metadata_error('provider_unavailable', 'Imagescope metadata API is unavailable in this Python environment.')
    path = Path(path)
    try:
        before = path.stat()
        result = inspect_metadata(MetadataRequest(path, timeout=10))
        validate_metadata_result(result)
        if result['status'] == 'ok':
            after = path.stat()
            if _identity(before) != _identity(after) or result['input']['size_bytes'] != after.st_size:
                return metadata_error('source_changed', 'The original changed while metadata was being read. Refresh to retry.')
        modified = datetime.fromtimestamp(before.st_mtime).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
        view = present_metadata(result, path, modified)
        if not view['error']:
            view['source'] = dict(view['source'], path=str(path), revision=list(_identity(before)))
            if fingerprint is not None and tuple(fingerprint) != (before.st_mtime_ns, before.st_size):
                view['warnings'] = [*view['warnings'], {'code': 'catalog_source_changed', 'field': 'source',
                    'message': 'File changed since import. Facts describe the current file; rescan to refresh the library preview.'}]
        return view
    except MetadataContractError as error:
        return metadata_error('metadata_contract', str(error))
    except OSError:
        return metadata_error('source_unavailable', 'The original file is missing or cannot be read. Saved library notes are still available.')
    except Exception:
        return metadata_error('metadata_failed', 'Imagescope metadata inspection failed. No alternate reader was used.')
