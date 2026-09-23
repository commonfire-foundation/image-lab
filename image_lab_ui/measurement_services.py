"""Presentation of existing Imagescope measurements, never pixel algorithms."""
import math
from pathlib import Path
import re

from .analyzer_client import AnalyzerProcessError, inspect_measurements, validate_measurement_result
from .image_services import _display, _identity, metadata_error


def present_measurements(result, path, *, color_policy='legacy-v1', assume_srgb=False):
    validate_measurement_result(result, path, color_policy=color_policy, assume_srgb=assume_srgb)
    measurements = result['measurements']
    provenance = result['provenance']
    preprocessing = provenance['preprocessing']
    color = preprocessing['color_management']
    palette = measurements.get('palette')
    if type(palette) is not list or len(palette) > 6:
        raise ValueError('Invalid provider palette')
    for entry in palette:
        if (type(entry) is not dict or type(entry.get('hex')) is not str
                or not re.fullmatch(r'#[0-9a-f]{6}', entry['hex'])
                or type(entry.get('fraction')) not in (int, float)
                or not math.isfinite(entry['fraction']) or not 0 <= entry['fraction'] <= 1):
            raise ValueError('Invalid provider palette entry')

    def row(label, value):
        return {'label': label, 'value': _display(value)}

    def fraction(value):
        if value is None:
            return 'Unknown'
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Invalid provider fraction')
        return f'{value * 100:.2f}%'

    transparency = measurements.get('transparency', {})
    luminance = measurements.get('luminance_distribution', {})
    if type(transparency) is not dict or type(luminance) is not dict:
        raise ValueError('Invalid provider measurements')
    percentiles = luminance.get('percentiles') or {}
    if type(percentiles) is not dict:
        raise ValueError('Invalid luminance percentiles')
    profile = color.get('source_profile') or {}
    if type(profile) is not dict:
        raise ValueError('Invalid source profile provenance')
    groups = [
        {'title': 'COLOR POLICY & SAMPLING', 'rows': [
            row('Color policy', color['policy']),
            row('Color interpretation', color['status']),
            row('Source interpretation', color.get('source_interpretation')),
            row('Output color space', color.get('output_color_space')),
            row('Source profile state', profile.get('status')),
            row('Measurements / preprocessing versions', f"{provenance['measurements_version']} / {preprocessing['version']}"),
            row('Source dimensions', f"{result['input']['width']} × {result['input']['height']} px · EXIF-oriented"),
            row('Working raster', f"{preprocessing['working_width']} × {preprocessing['working_height']} px"),
            row('Downsampled', preprocessing['downsampled']),
            row('Scope', 'Original, unedited image · first frame only · no ROI'),
            row('Palette / distribution sampling', 'At most 256 × 256; approximate, not full-resolution counts'),
            row('Requested palette size', provenance['measurement_settings']['palette_size']),
            row('Palette alpha policy', preprocessing.get('palette_alpha')),
            row('Alpha resize policy', preprocessing.get('alpha_resize')),
            row('Encoded source SHA-256', result['input']['sha256']),
        ]},
        {'title': 'LUMINANCE', 'rows': [
            row('Mean · white-composited', measurements.get('mean_luminance')),
            row('Spread · white-composited', measurements.get('luminance_std')),
            row('Median · opacity-weighted, no background', percentiles.get('p50')),
            row('Near-black share', fraction(luminance.get('near_black_fraction'))),
            row('Near-white share', fraction(luminance.get('near_white_fraction'))),
        ]},
        {'title': 'TRANSPARENCY', 'rows': [
            row('Transparent share', fraction(transparency.get('transparent_fraction'))),
            row('Translucent share', fraction(transparency.get('translucent_fraction'))),
            row('Sample dimensions', f"{_display(transparency.get('width'))} × {_display(transparency.get('height'))} px"),
            row('Visible bounds · working pixels', 'None · no visible pixels' if 'visible_bounds' in transparency and transparency['visible_bounds'] is None else transparency.get('visible_bounds')),
            row('Bounds limitation', 'Sampled half-open bounds; never exact original-resolution crop coordinates'),
        ]},
    ]
    return {'provider': 'Imagescope', 'metadataVersion': None, 'metadata': None,
            'groups': groups, 'palette': palette, 'result': result,
            'source': {'path': str(path), 'sha256': result['input']['sha256']},
            'warnings': [], 'error': '', 'errorCode': '',
            'summary': f"{color['policy']} · {color['status']} · measurements v{provenance['measurements_version']}",
            'colorAgreement': False,
            'notice': 'Read-only, unmanaged measurements. Preview/measurement color agreement is unverified; color-guided adjustments remain disabled.'}


def measure_file(path, fingerprint=None):
    """Worker-only source I/O; never persist measurements as library predictions."""
    path = Path(path)
    try:
        path = path.resolve()
        before = path.stat()
        if fingerprint is not None and tuple(fingerprint) != (before.st_mtime_ns, before.st_size):
            return metadata_error('source_changed', 'The source changed since import. Rescan before measuring it.')
        result = inspect_measurements(path)
        after = path.stat()
        if _identity(before) != _identity(after):
            return metadata_error('source_changed', 'The source changed during measurement. Refresh to retry.')
        view = present_measurements(result, path)
        view['source']['revision'] = list(_identity(after))
        return view
    except ImportError:
        return metadata_error('measurement_provider_unavailable', 'The Imagescope public analysis API is unavailable.')
    except OSError:
        return metadata_error('source_unavailable', 'The original is missing or unreadable.')
    except AnalyzerProcessError as error:
        return metadata_error('measurement_failed', str(error)[:1900] + ' · No fallback was used.')
    except (ValueError, TypeError, KeyError, OverflowError):
        return metadata_error('measurement_failed', 'Imagescope could not return compatible measurements for this source. No fallback was used.')


def validate_measurement_view(view):
    """Rebuild display fields from the validated analysis result, not wire labels."""
    if type(view) is not dict:
        raise ValueError('Invalid measurement response')
    if view.get('error'):
        if (type(view['error']) is not str or len(view['error']) > 2048
                or type(view.get('errorCode')) is not str or len(view['errorCode']) > 128
                or view.get('groups') != [] or view.get('source') is not None):
            raise ValueError('Invalid measurement error')
        return metadata_error(view['errorCode'], view['error'])
    source = view['source']
    expected = present_measurements(view['result'], source['path'])
    if source.get('sha256') != expected['source']['sha256']:
        raise ValueError('Measurement source digest does not match')
    revision = source.get('revision')
    if type(revision) is not list or len(revision) != 5 or any(type(value) is not int for value in revision):
        raise ValueError('Missing measurement source revision')
    expected['source']['revision'] = revision
    return expected
