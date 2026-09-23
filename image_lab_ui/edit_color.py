"""Explicit color preparation for the editor's shared preview/full render path.

Worker-only, already-decoded RGB/RGBA pixels. This module neither opens source
files nor performs measurements, encoding, or writes. The current worker wire
protocol carries color policy/provenance; desktop preview integration remains gated.
"""
from dataclasses import asdict, dataclass
import hashlib
from importlib import import_module
import io

from PIL import Image, __version__ as PILLOW_VERSION, features

from .edit_protocol import MAX_PROFILE_BYTES, validate_color_options
from .edit_recipe import Size
from .edit_render import RenderedImage, render_geometry

class EditColorError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ColorProvenance:
    policy: str
    assume_srgb: bool
    status: str
    source_mode: str
    source_interpretation: str
    source_profile_sha256: str | None
    output_color_space: str | None
    rendering_intent: str | None
    black_point_compensation: bool
    transform_optimization: str | None
    order: str | None
    pillow_version: str
    littlecms_version: str | None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ColorRenderedImage(RenderedImage):
    color: ColorProvenance


def _cms():
    try:
        return import_module('PIL.ImageCms')
    except ImportError as error:
        raise EditColorError('color_management_unavailable', 'ICC conversion requires Pillow ImageCms/LittleCMS.') from error


def prepare_color_pixels(image, *, policy, assume_srgb=False):
    """Return independent pixels and provenance; policy must be selected explicitly.

    The editor intentionally supports a narrower mode subset than Imagescope:
    RGB/RGBA only. Source eligibility/high-depth checks remain the decoder's job.
    ICC takes priority over declarations and assumptions, including invalid ICC.
    Declared/assumed sRGB needs no CMS transform and does not manufacture an ICC;
    an eventual encoder must honor output_color_space, not infer it from ICC absence.
    """
    try:
        validate_color_options(policy, assume_srgb)
    except ValueError as error:
        raise EditColorError('invalid_request', str(error)) from error
    if not isinstance(image, Image.Image) or getattr(image, 'fp', None) is not None:
        raise EditColorError('invalid_request', 'Color preparation requires decoded, isolated pixels.')
    if image.mode not in ('RGB', 'RGBA') or (image.mode == 'RGB' and 'transparency' in image.info):
        raise EditColorError('unsupported_color_mode', 'Editor color preparation supports 8-bit RGB/RGBA without color-key transparency.')
    Size(*image.size)  # Retain the editor's source-pixel budget.
    raw = image.info.get('icc_profile')
    if raw is not None and type(raw) is not bytes:
        raise EditColorError('invalid_color_profile', 'ICC metadata must contain profile bytes.')
    if raw is not None and len(raw) > MAX_PROFILE_BYTES:
        raise EditColorError('color_profile_too_large', 'ICC profile exceeds the editor metadata budget.')
    digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
    declared = type(image.info.get('srgb')) is int and image.info['srgb'] in range(4)
    interpretation = 'declared_srgb' if raw is None and declared else 'unknown'
    status, output_space, intent, optimization, cms_version = 'unmanaged', None, None, None, None
    output_profile = raw

    if policy == 'legacy-v1':
        # No profile validation or conversion; never relabel this output as sRGB.
        pixels = image.copy()
    elif raw is not None:
        cms = _cms()
        try:
            source_profile = cms.ImageCmsProfile(io.BytesIO(raw))
        except (OSError, ValueError, TypeError, cms.PyCMSError) as error:
            raise EditColorError('invalid_color_profile', 'Embedded ICC profile could not be parsed; no assumption can override it.') from error
        if source_profile.profile.xcolor_space.strip() != 'RGB':
            raise EditColorError('unsupported_color_mode', 'The embedded profile does not describe RGB channels.')
        pixels = None
        try:
            target_profile = cms.ImageCmsProfile(cms.createProfile('sRGB'))
            # 0x0100 = NOOPTIMIZE, explicitly excluding black-point compensation.
            flags = getattr(cms, 'Flags', int)(0x0100)
            with image.convert('RGB') as rgb:
                pixels = cms.profileToProfile(rgb, source_profile, target_profile,
                    renderingIntent=cms.Intent.RELATIVE_COLORIMETRIC,
                    outputMode='RGB', inPlace=False, flags=flags)
            if pixels is None:
                raise ValueError('CMS did not return converted pixels.')
            if image.mode == 'RGBA':
                with image.getchannel('A') as alpha:
                    pixels.putalpha(alpha)
            output_profile = target_profile.tobytes()
            cms_version = features.version('littlecms2')
        except (OSError, ValueError, TypeError, cms.PyCMSError) as error:
            if pixels is not None:
                pixels.close()
            raise EditColorError('color_conversion_failed', 'ICC conversion failed; no unmanaged fallback was used.') from error
        status, output_space, interpretation = 'converted', 'srgb', 'embedded_icc'
        intent, optimization = 'relative-colorimetric', 'disabled'
    else:
        if not declared and not assume_srgb:
            raise EditColorError('unknown_color_space', 'Choose an explicit sRGB assumption for untagged RGB/RGBA, or keep it unmanaged.')
        pixels = image.copy()
        status = interpretation = 'declared_srgb' if declared else 'assumed_srgb'
        output_space, output_profile = 'srgb', None

    # Never propagate source EXIF/GPS/orientation or an old source profile after conversion.
    pixels.info.clear()
    if output_profile is not None:
        pixels.info['icc_profile'] = output_profile
    provenance = ColorProvenance(policy, assume_srgb, status, image.mode, interpretation, digest,
        output_space, intent, False, optimization,
        None if policy == 'legacy-v1' else 'color_before_orientation_crop_rotate_flip_resize',
        PILLOW_VERSION, cms_version)
    return pixels, provenance


def render_color_geometry(image, recipe, *, orientation, policy, assume_srgb=False, preview_longest=None):
    """One color → geometry pipeline for preview and full-resolution pixels.

    Cropping/resize never occur before conversion. The existing preview guard and
    metadata-stripping behavior are retained. This is not an encoder/export API.
    """
    pixels, color = prepare_color_pixels(image, policy=policy, assume_srgb=assume_srgb)
    try:
        rendered = render_geometry(pixels, recipe, orientation=orientation, preview_longest=preview_longest)
    finally:
        pixels.close()
    return ColorRenderedImage(rendered.image, rendered.output_size, rendered.is_preview, color)
