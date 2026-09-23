"""Validate v2 color metadata without parsing profiles or decoding in the parent."""
from .edit_color import ColorProvenance
from .edit_protocol import MAX_PROFILE_BYTES, _digest


def validate_color_result(result, request, source):
    data, profile = result['color'], result['profile']
    if type(data) is not dict or set(data) != set(ColorProvenance.__dataclass_fields__):
        raise ValueError('Missing or unknown color provenance fields.')
    if (data['policy'] != request['color_policy']
            or type(data['assume_srgb']) is not bool or data['assume_srgb'] != request['assume_srgb']
            or data['source_mode'] != source.mode
            or data['source_profile_sha256'] != source.icc_sha256
            or data['black_point_compensation'] is not False):
        raise ValueError('Color provenance does not match request/source.')
    if type(data['pillow_version']) is not str or not 1 <= len(data['pillow_version']) <= 80:
        raise ValueError('Missing Pillow identity.')
    converted = data['status'] == 'converted'
    declared = source.srgb_intent is not None and source.icc_sha256 is None
    if data['policy'] == 'legacy-v1':
        if (data['status'] != 'unmanaged' or data['output_color_space'] is not None
                or data['order'] is not None
                or data['source_interpretation'] != ('declared_srgb' if declared else 'unknown')):
            raise ValueError('Legacy output must remain unmanaged.')
    else:
        if (data['output_color_space'] != 'srgb'
                or data['order'] != 'color_before_orientation_crop_rotate_flip_resize'):
            raise ValueError('Invalid managed output/order.')
        if source.icc_sha256 is not None:
            if not converted or data['source_interpretation'] != 'embedded_icc':
                raise ValueError('Embedded ICC must be converted, never assumed.')
        elif (data['status'] != ('declared_srgb' if declared else 'assumed_srgb')
              or data['source_interpretation'] != data['status']
              or (data['status'] == 'assumed_srgb' and not request['assume_srgb'])):
            raise ValueError('Unsupported source interpretation.')
    if data['source_interpretation'] == 'declared_srgb' and (source.format != 'PNG' or source.icc_sha256 is not None):
        raise ValueError('Declaration cannot override ICC or identify a non-PNG.')
    if converted:
        if (data['rendering_intent'] != 'relative-colorimetric'
                or data['transform_optimization'] != 'disabled'
                or type(data['littlecms_version']) is not str or not 1 <= len(data['littlecms_version']) <= 80):
            raise ValueError('Unsupported CMS transform.')
    elif any(data[key] is not None for key in ('rendering_intent', 'transform_optimization', 'littlecms_version')):
        raise ValueError('Unconverted output claims a CMS transform.')
    if (result['color_conversion'] != ('converted' if converted else 'none')
            or result['color_interpretation'] != (data['output_color_space'] or 'unmanaged')):
        raise ValueError('Conflicting color summary.')
    requires_profile = source.icc_sha256 is not None
    if not requires_profile:
        if profile is not None:
            raise ValueError('Unexpected destination profile.')
        return 0
    if (type(profile) is not dict or set(profile) != {'byte_count', 'sha256'}
            or type(profile['byte_count']) is not int or not 0 <= profile['byte_count'] <= MAX_PROFILE_BYTES
            or not _digest(profile['sha256'])):
        raise ValueError('Invalid bounded profile descriptor.')
    if converted and profile['byte_count'] < 128:
        raise ValueError('Converted output has no destination ICC header.')
    if not converted and profile['sha256'] != source.icc_sha256:
        raise ValueError('Legacy source profile was replaced.')
    return profile['byte_count']
