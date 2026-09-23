"""Shared geometry on already-decoded RGB/RGBA pixels; not an image-file loader.

This module has no UI, catalog, decoder, color conversion, encoder, or file writes.
The future bounded worker must decode and establish the accepted source color
policy before calling it. Never call it on an untrusted lazy image in the UI.
"""
from dataclasses import dataclass

from PIL import Image

from .edit_recipe import EditRecipe, Size

MAX_PREVIEW_SIDE = 2048
_ORIENTATION = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
_ROTATION = {1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180, 3: Image.Transpose.ROTATE_90}


@dataclass(frozen=True)
class RenderedImage:
    image: Image.Image
    output_size: Size  # Intended full output size, never the reduced preview size.
    is_preview: bool

    def full_resolution_image(self):
        """An encoder must not quietly promote a preview into an export source."""
        if self.is_preview or self.image.size != (self.output_size.width, self.output_size.height):
            raise ValueError('A preview cannot be used as a full-resolution export.')
        return self.image


def preview_size(output, longest_side):
    if not isinstance(output, Size):
        raise ValueError('Output dimensions must be a Size.')
    if type(longest_side) is not int or not 1 <= longest_side <= MAX_PREVIEW_SIDE:
        raise ValueError('Preview size must be between 1 and 2048 pixels.')
    longest = max(output.width, output.height)
    if longest <= longest_side:
        return output
    width = max(1, (2 * output.width * longest_side + longest) // (2 * longest))
    height = max(1, (2 * output.height * longest_side + longest) // (2 * longest))
    return Size(width, height)


def render_geometry(image, recipe, *, orientation, preview_longest=None):
    """Apply EXIF orientation once, then crop → clockwise rotate → H/V flip → size.

    `orientation` is explicitly supplied by the caller; it is never guessed from
    absent metadata. `recipe.source_size` must match the oriented original.
    Preview and full output share geometry but may differ in resampling detail.
    Color/profile interpretation is the caller's responsibility: existing ICC
    bytes are retained, never synthesized or treated as proof of sRGB.
    """
    if not isinstance(image, Image.Image) or not isinstance(recipe, EditRecipe):
        raise ValueError('Rendering requires decoded pixels and an edit recipe.')
    if image.mode not in ('RGB', 'RGBA'):
        raise ValueError('Geometry rendering requires prevalidated 8-bit RGB or RGBA pixels.')
    if getattr(image, 'fp', None) is not None:
        raise ValueError('Decode and isolate the source before geometry rendering.')
    if type(orientation) is not int or orientation not in range(1, 9):
        raise ValueError('A known EXIF orientation from 1 to 8 is required.')
    stored_size = Size(*image.size)
    oriented_size = stored_size.swapped() if orientation in (5, 6, 7, 8) else stored_size
    if oriented_size != recipe.source_size:
        raise ValueError('Recipe dimensions do not match the oriented original.')
    output_size = recipe.result_size
    target = preview_size(output_size, preview_longest) if preview_longest is not None else output_size
    profile = image.info.get('icc_profile')
    if profile is not None and (type(profile) is not bytes or len(profile) > 1024 * 1024):
        raise ValueError('ICC profile bytes exceed the supported geometry metadata budget.')

    oriented = image.transpose(_ORIENTATION[orientation]) if orientation != 1 else image
    try:
        result = oriented.crop(tuple(recipe.crop.as_list()))
    finally:
        if oriented is not image:
            oriented.close()
    try:
        operations = []
        if recipe.quarter_turns:
            operations.append(_ROTATION[recipe.quarter_turns])
        if recipe.flip_horizontal:
            operations.append(Image.Transpose.FLIP_LEFT_RIGHT)
        if recipe.flip_vertical:
            operations.append(Image.Transpose.FLIP_TOP_BOTTOM)
        for operation in operations:
            transformed = result.transpose(operation)
            result.close()
            result = transformed
        dimensions = (target.width, target.height)
        if result.size != dimensions:
            resized = result.resize(dimensions, Image.Resampling.LANCZOS)
            result.close()
            result = resized
        # Do not propagate stale EXIF orientation, dimensions, GPS, or arbitrary text.
        result.info.clear()
        if profile is not None:
            result.info['icc_profile'] = profile
        return RenderedImage(result, output_size, is_preview=preview_longest is not None)
    except Exception:
        result.close()
        raise
