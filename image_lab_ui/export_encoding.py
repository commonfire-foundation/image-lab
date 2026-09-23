"""Managed full-source export requests; encoding/decoding stay in a bounded child."""
from dataclasses import dataclass
import hashlib
import re

from .edit_protocol import EditWorkerError
from .export_publication import MAX_ENCODED_BYTES
from .editor_payload import request_payload


def validate_options(options):
    if type(options) is not dict or set(options) != {'format', 'quality', 'lossless', 'matte'}:
        raise ValueError('Invalid export options.')
    if (options['format'] not in ('PNG', 'JPEG', 'WEBP') or type(options['quality']) is not int
            or not 1 <= options['quality'] <= 95 or type(options['lossless']) is not bool
            or (options['matte'] is not None and (type(options['matte']) is not str
                or not re.fullmatch(r'#[0-9a-fA-F]{6}', options['matte'])))):
        raise ValueError('Choose a supported format, quality 1–95 and an explicit #RRGGBB JPEG matte.')
    if options['lossless'] and options['format'] != 'WEBP':
        raise ValueError('The lossless switch applies only to WebP; PNG is always lossless.')
    if options['matte'] is not None and options['format'] != 'JPEG':
        raise ValueError('Only JPEG accepts a matte. PNG/WebP preserve transparency.')
    return dict(options)


@dataclass(frozen=True)
class EncodedCopy:
    data: bytes
    info: dict

    def verify_staging(self, stream):
        digest = hashlib.sha256()
        count = 0
        while chunk := stream.read(65536):
            count += len(chunk)
            if count > len(self.data): raise ValueError('Staged output grew.')
            digest.update(chunk)
        if count != len(self.data) or digest.hexdigest() != hashlib.sha256(self.data).hexdigest():
            raise ValueError('Staged copy differs from the child-verified encoded output.')


def encode_copy(source, recipe, *, color_policy, assume_srgb, options, cancelled=lambda: False, timeout=60):
    from .edit_process import _request
    from .edit_protocol import SourceSnapshot
    from .edit_recipe import EditRecipe
    from .edit_color_transport import validate_color_result
    options = validate_options(options)
    if color_policy != 'srgb-v1':
        raise ValueError('Export requires the explicit managed sRGB interpretation.')
    render = _request('render', source.path, source.to_dict(), recipe.to_dict(), None,
                      timeout, None, 0, color_policy, assume_srgb)
    info, data = request_payload('image_lab_ui.export_worker', {'render': render, 'options': options},
                                 limit=MAX_ENCODED_BYTES, timeout=timeout, cancelled=cancelled)
    if (info.get('source') != source.to_dict() or info.get('recipe') != recipe.to_dict()
            or info.get('options') != options or info.get('size') != recipe.result_size.as_list()
            or info.get('color_policy') != color_policy or info.get('assume_srgb') != assume_srgb
            or info.get('verified') is not True or info.get('metadata_stripped') is not True):
        raise EditWorkerError('protocol_error', 'Encoded output does not match the export request.')
    try:
        if (SourceSnapshot.from_dict(info['source']) != source or EditRecipe.from_dict(info['recipe']) != recipe
                or validate_options(info['options']) != options or type(info['assume_srgb']) is not bool
                or type(info['size']) is not list or any(type(value) is not int for value in info['size'])
                or info.get('mode') != ('RGB' if options['format'] == 'JPEG' else source.mode)):
            raise ValueError('Invalid encoded source/geometry/mode binding.')
        validate_color_result({'color': info['color'], 'profile': info['render_profile'],
            'color_conversion': 'converted' if info['color']['status'] == 'converted' else 'none',
            'color_interpretation': info['color']['output_color_space']}, render, source)
    except (ValueError, TypeError, KeyError) as error:
        raise EditWorkerError('protocol_error', 'Invalid encoded color/geometry provenance.') from error
    return EncodedCopy(data, info)
