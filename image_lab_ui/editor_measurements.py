"""Original-source measurement transport and presentation, never edited statistics."""
from .analyzer_client import validate_measurement_result
from .editor_payload import request_payload
from .edit_protocol import strict_json
from .measurement_services import present_measurements

MAX_MEASUREMENT_BYTES = 1024 * 1024


def validate_source_measurements(source, color, result):
    """Align original source/color provenance, independent of the current geometry."""
    if color is None or color.policy != 'srgb-v1':
        raise ValueError('Unmanaged previews have no accepted color agreement.')
    validate_measurement_result(result, source.path, color_policy=color.policy, assume_srgb=color.assume_srgb)
    if (result['input']['sha256'] != source.sha256
            or result['input']['width'] != source.oriented_size.width
            or result['input']['height'] != source.oriented_size.height):
        raise ValueError('Measurements refer to another source revision.')
    actual = result['provenance']['preprocessing']['color_management']
    for key in ('policy', 'assume_srgb', 'status', 'source_mode', 'source_interpretation',
                'output_color_space', 'rendering_intent', 'black_point_compensation',
                'transform_optimization', 'pillow_version', 'littlecms_version'):
        if actual.get(key) != getattr(color, key):
            raise ValueError('Measurement and preview color provenance differ.')
    if actual['source_profile'].get('sha256') != source.icc_sha256:
        raise ValueError('Measurement and preview source profiles differ.')
    return result


def measure_source(source, policy, assumption, *, cancelled):
    request = {'source': source.to_dict(), 'policy': policy, 'assumption': assumption}
    info, payload = request_payload('image_lab_ui.editor_measurement_worker', request,
        limit=MAX_MEASUREMENT_BYTES, timeout=35, cancelled=cancelled)
    if info != request: raise ValueError('Measurement request correlation failed.')
    return strict_json(payload)


def empty_measurements(**values):
    return dict(loading=False, error='', errorCode='', groups=[], palette=[], result=None,
                summary='', notice='Original image only; never edited-image statistics.') | values


def present_source_measurements(frame, result, revision):
    validate_source_measurements(frame.source, frame.color, result)
    view = present_measurements(result, frame.source.path, color_policy=frame.color.policy,
                                assume_srgb=frame.color.assume_srgb)
    view.update(loading=False, revision=revision, sourcePolicyAligned=True,
                notice='Managed original-image measurements; source digest, profile and color policy match this editing revision. '
                       'These are NOT edited-image statistics. Sampling differs from the preview; monitor/HDR agreement is not certified. '
                       'Color-guided adjustments remain disabled.')
    return view
