"""Immutable, pixel-coordinate edit recipes; no Qt, decoder, or file operations."""
from dataclasses import dataclass, replace
from math import ceil, floor, gcd, isfinite

RECIPE_VERSION = 1
MAX_PIXELS = 40_000_000
MAX_HISTORY = 100


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer of at least {minimum}.')
    return value


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f'{name} must be a boolean.')


def _finite(value, name):
    if type(value) not in (int, float):
        raise ValueError(f'{name} must be finite.')
    try:
        valid = isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be finite.')
    return value


def _rounded_ratio(value, numerator, denominator):
    # Integer half-up rounding avoids float drift and banker's rounding.
    return max(1, (2 * value * numerator + denominator) // (2 * denominator))


@dataclass(frozen=True)
class Size:
    width: int
    height: int

    def __post_init__(self):
        _integer(self.width, 'Width', 1)
        _integer(self.height, 'Height', 1)
        if self.width * self.height > MAX_PIXELS:
            raise ValueError('Image exceeds the 40 megapixel editing limit.')

    def swapped(self):
        return Size(self.height, self.width)

    def as_list(self):
        return [self.width, self.height]


@dataclass(frozen=True)
class Crop:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self):
        for key in ('left', 'top', 'right', 'bottom'):
            _integer(getattr(self, key), key)
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError('Crop must contain at least one pixel in each dimension.')

    @property
    def size(self):
        return Size(self.right - self.left, self.bottom - self.top)

    def as_list(self):
        return [self.left, self.top, self.right, self.bottom]


@dataclass(frozen=True)
class EditRecipe:
    # source_size is AFTER EXIF orientation; recipe rotation is an additional edit.
    source_size: Size
    crop: Crop
    quarter_turns: int = 0  # Clockwise, followed by flips in rotated axes.
    flip_horizontal: bool = False
    flip_vertical: bool = False
    output_size: Size | None = None  # None means natural size, not preview size.
    allow_upscale: bool = False
    version: int = RECIPE_VERSION

    def __post_init__(self):
        if type(self.version) is not int or self.version != RECIPE_VERSION:
            raise ValueError('Unsupported edit recipe version.')
        if not isinstance(self.source_size, Size) or not isinstance(self.crop, Crop):
            raise ValueError('Recipe requires source dimensions and a crop.')
        if self.crop.right > self.source_size.width or self.crop.bottom > self.source_size.height:
            raise ValueError('Crop lies outside the oriented original.')
        _integer(self.quarter_turns, 'Quarter turns')
        if self.quarter_turns > 3:
            raise ValueError('Quarter turns must be between 0 and 3.')
        _boolean(self.flip_horizontal, 'Horizontal flip')
        _boolean(self.flip_vertical, 'Vertical flip')
        _boolean(self.allow_upscale, 'Allow upscale')
        if self.output_size is not None:
            if not isinstance(self.output_size, Size):
                raise ValueError('Output dimensions must be a Size.')
            natural, output = self.natural_size, self.output_size
            if not self.allow_upscale and (output.width > natural.width or output.height > natural.height):
                raise ValueError('Enable upscaling explicitly to enlarge the result.')
            # Either dimension can drive the lock. The other rounds to one pixel.
            if (output.height != _rounded_ratio(output.width, natural.height, natural.width)
                    and output.width != _rounded_ratio(output.height, natural.width, natural.height)):
                raise ValueError('Output dimensions must preserve the crop aspect ratio.')

    @classmethod
    def original(cls, width, height):
        return cls(Size(width, height), Crop(0, 0, width, height))

    @property
    def natural_size(self):
        size = self.crop.size
        return size.swapped() if self.quarter_turns % 2 else size

    @property
    def result_size(self):
        return self.output_size or self.natural_size

    def with_crop(self, crop):
        return replace(self, crop=crop, output_size=None)

    def with_aspect(self, width, height):
        """Largest exact-ratio centered crop inside the current crop, as displayed."""
        _integer(width, 'Ratio width', 1)
        _integer(height, 'Ratio height', 1)
        divisor = gcd(width, height)
        width, height = width // divisor, height // divisor
        if self.quarter_turns % 2:
            width, height = height, width
        multiple = min(self.crop.size.width // width, self.crop.size.height // height)
        if not multiple:
            raise ValueError('This crop is too small for the requested exact ratio.')
        width, height = width * multiple, height * multiple
        left = self.crop.left + (self.crop.size.width - width) // 2
        top = self.crop.top + (self.crop.size.height - height) // 2
        return self.with_crop(Crop(left, top, left + width, top + height))

    def rotated(self, steps=1):
        if type(steps) is not int:
            raise ValueError('Rotation steps must be an integer.')
        # Preserve the visual meaning of clockwise rotation after any flips.
        horizontal, vertical = self.flip_horizontal, self.flip_vertical
        output = self.output_size
        if steps % 2:
            horizontal, vertical = vertical, horizontal
            if output:
                output = output.swapped()
        return replace(self, quarter_turns=(self.quarter_turns + steps) % 4,
                       flip_horizontal=horizontal, flip_vertical=vertical, output_size=output)

    def flipped(self, *, horizontal=False, vertical=False):
        _boolean(horizontal, 'Horizontal flip')
        _boolean(vertical, 'Vertical flip')
        return replace(self, flip_horizontal=self.flip_horizontal ^ horizontal,
                       flip_vertical=self.flip_vertical ^ vertical)

    def resized_width(self, width):
        _integer(width, 'Width', 1)
        natural = self.natural_size
        return replace(self, output_size=Size(width, _rounded_ratio(width, natural.height, natural.width)))

    def resized_height(self, height):
        _integer(height, 'Height', 1)
        natural = self.natural_size
        return replace(self, output_size=Size(_rounded_ratio(height, natural.width, natural.height), height))

    def resized_percent(self, percent):
        _finite(percent, 'Percentage')
        if not 0 < percent <= 10000:
            raise ValueError('Percentage must be greater than zero and at most 10000.')
        width = max(1, int(self.natural_size.width * percent / 100 + 0.5))
        return self.resized_width(width)

    def with_upscale(self, allowed):
        return replace(self, allow_upscale=allowed)

    def with_display_crop(self, left, top, right, bottom):
        """Crop a normalized rectangle on the current displayed result.

        Map all corners through resize/flip/rotation, then round outward to source
        pixel edges. Near-integer arithmetic noise is snapped within 1e-7 pixels.
        A real crop clears explicit resize; a full/no-op selection preserves it.
        """
        for value in (left, top, right, bottom):
            _finite(value, 'Display crop bound')
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError('Select a non-empty rectangle inside the displayed image.')
        size = self.result_size
        points = [self.result_to_source(x * size.width, y * size.height)
                  for x in (left, right) for y in (top, bottom)]
        def snap(value):
            rounded = round(value)
            return rounded if abs(value - rounded) <= 1e-7 else value
        def edges(values, minimum, maximum):
            lo = max(minimum, floor(snap(min(values))))
            hi = min(maximum, ceil(snap(max(values))))
            if hi <= lo:  # Do not collapse a positive subpixel selection when snapping.
                lo = max(minimum, min(maximum - 1, floor(min(values))))
                hi = max(lo + 1, min(maximum, ceil(max(values))))
            return lo, hi
        xs, ys = zip(*points)
        x0, x1 = edges(xs, self.crop.left, self.crop.right)
        y0, y1 = edges(ys, self.crop.top, self.crop.bottom)
        crop = Crop(x0, y0, x1, y1)
        return self if crop == self.crop else self.with_crop(crop)

    def source_to_result(self, x, y):
        """Continuous edge coordinates, not pixel-center indices; no rounding."""
        _finite(x, 'X')
        _finite(y, 'Y')
        if not self.crop.left <= x <= self.crop.right or not self.crop.top <= y <= self.crop.bottom:
            raise ValueError('Point is outside the crop.')
        x, y = x - self.crop.left, y - self.crop.top
        w, h = self.crop.size.width, self.crop.size.height
        x, y = ((x, y), (h - y, x), (w - x, h - y), (y, w - x))[self.quarter_turns]
        natural, output = self.natural_size, self.result_size
        if self.flip_horizontal:
            x = natural.width - x
        if self.flip_vertical:
            y = natural.height - y
        return x * output.width / natural.width, y * output.height / natural.height

    def result_to_source(self, x, y):
        _finite(x, 'X')
        _finite(y, 'Y')
        natural, output = self.natural_size, self.result_size
        if not 0 <= x <= output.width or not 0 <= y <= output.height:
            raise ValueError('Point is outside the result.')
        x, y = x * natural.width / output.width, y * natural.height / output.height
        if self.flip_horizontal:
            x = natural.width - x
        if self.flip_vertical:
            y = natural.height - y
        w, h = self.crop.size.width, self.crop.size.height
        x, y = ((x, y), (y, h - x), (w - x, h - y), (w - y, x))[self.quarter_turns]
        return x + self.crop.left, y + self.crop.top

    def to_dict(self):
        return {'version': self.version, 'source_size': self.source_size.as_list(),
                'crop': self.crop.as_list(), 'quarter_turns': self.quarter_turns,
                'flip_horizontal': self.flip_horizontal, 'flip_vertical': self.flip_vertical,
                'output_size': self.output_size.as_list() if self.output_size else None,
                'allow_upscale': self.allow_upscale}

    @classmethod
    def from_dict(cls, data):
        keys = {'version', 'source_size', 'crop', 'quarter_turns', 'flip_horizontal',
                'flip_vertical', 'output_size', 'allow_upscale'}
        if type(data) is not dict or set(data) != keys:
            raise ValueError('Recipe has missing or unknown fields.')
        for key, length in (('source_size', 2), ('crop', 4), ('output_size', 2)):
            value = data[key]
            if key == 'output_size' and value is None:
                continue
            if type(value) is not list or len(value) != length:
                raise ValueError(f'Invalid {key}.')
        return cls(source_size=Size(*data['source_size']), crop=Crop(*data['crop']),
                   quarter_turns=data['quarter_turns'], flip_horizontal=data['flip_horizontal'],
                   flip_vertical=data['flip_vertical'], allow_upscale=data['allow_upscale'],
                   version=data['version'], output_size=Size(*data['output_size']) if data['output_size'] is not None else None)


@dataclass(frozen=True)
class FitTransform:
    """Fit-to-window mapping in Qt logical coordinates; DPR is NOT applied twice."""
    image_size: Size
    viewport_width: float
    viewport_height: float

    def __post_init__(self):
        if not isinstance(self.image_size, Size):
            raise ValueError('Image dimensions must be a Size.')
        for value in (self.viewport_width, self.viewport_height):
            if _finite(value, 'Viewport dimension') <= 0:
                raise ValueError('Viewport dimensions must be positive.')
        if self.scale <= 0:
            raise ValueError('Viewport scale is too small.')

    @property
    def scale(self):
        return min(self.viewport_width / self.image_size.width, self.viewport_height / self.image_size.height)

    @property
    def offset(self):
        return ((self.viewport_width - self.image_size.width * self.scale) / 2,
                (self.viewport_height - self.image_size.height * self.scale) / 2)

    def to_view(self, x, y):
        _finite(x, 'X')
        _finite(y, 'Y')
        if not 0 <= x <= self.image_size.width or not 0 <= y <= self.image_size.height:
            raise ValueError('Point is outside the image.')
        left, top = self.offset
        return left + x * self.scale, top + y * self.scale

    def to_image(self, x, y, *, clamp=False):
        _finite(x, 'X')
        _finite(y, 'Y')
        _boolean(clamp, 'Clamp')
        left, top = self.offset
        x, y = (x - left) / self.scale, (y - top) / self.scale
        if clamp:
            return min(self.image_size.width, max(0, x)), min(self.image_size.height, max(0, y))
        if not 0 <= x <= self.image_size.width or not 0 <= y <= self.image_size.height:
            raise ValueError('Point is in the letterbox, not the image.')
        return x, y


class EditHistory:
    """Commit one immutable recipe per gesture, not per pointer movement."""
    def __init__(self, original, limit=MAX_HISTORY):
        if not isinstance(original, EditRecipe):
            raise ValueError('History requires an edit recipe.')
        _integer(limit, 'History limit', 1)
        if limit > MAX_HISTORY:
            raise ValueError('History cannot exceed 100 recipes.')
        self.original = original
        self.limit = limit
        self._entries = [original]
        self._index = 0
        self._exported = original

    @property
    def current(self):
        return self._entries[self._index]

    @property
    def can_undo(self):
        return self._index > 0

    @property
    def can_redo(self):
        return self._index < len(self._entries) - 1

    @property
    def dirty(self):
        return self.current != self._exported

    def commit(self, recipe):
        if not isinstance(recipe, EditRecipe) or recipe.source_size != self.original.source_size:
            raise ValueError('Recipe must belong to this source geometry.')
        if recipe == self.current:
            return False
        self._entries = self._entries[:self._index + 1] + [recipe]
        self._entries = self._entries[-self.limit:]
        self._index = len(self._entries) - 1
        return True

    def undo(self):
        if self.can_undo:
            self._index -= 1
        return self.current

    def redo(self):
        if self.can_redo:
            self._index += 1
        return self.current

    def reset(self):
        self.commit(self.original)
        return self.current

    def mark_exported(self, recipe):
        # Use the submitted recipe, not whichever revision is current on completion.
        # Called only after publication succeeds, never when encoding starts.
        if not isinstance(recipe, EditRecipe) or recipe.source_size != self.original.source_size:
            raise ValueError('Exported recipe must belong to this source geometry.')
        self._exported = recipe
