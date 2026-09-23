"""Private, bounded editor worker protocol; not an Imagescope result contract."""
from dataclasses import asdict, dataclass
import json
import os
import re

from .edit_recipe import Size, MAX_PIXELS

PROTOCOL_VERSION = 2
MAX_PROFILE_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024
MAX_STDERR_BYTES = 16 * 1024
MAX_RASTER_BYTES = MAX_PIXELS * 4
MEMORY_BYTES = 1536 * 1024 * 1024
MAX_TIMEOUT = 60


class EditWorkerError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def validate_color_options(policy, assume_srgb):
    if (type(policy) is not str or policy not in ('legacy-v1', 'srgb-v1')
            or type(assume_srgb) is not bool or (assume_srgb and policy != 'srgb-v1')):
        raise ValueError('Invalid editor color policy or assumption.')


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field.')
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('Nonfinite JSON value.')

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def _digest(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


@dataclass(frozen=True)
class SourceSnapshot:
    path: str
    device: int
    inode: int
    size_bytes: int
    mtime_ns: int
    ctime_ns: int
    sha256: str
    stored_size: Size
    orientation: int
    orientation_assumed: bool
    format: str
    mode: str
    icc_sha256: str | None
    srgb_intent: int | None = None

    def __post_init__(self):
        if type(self.path) is not str or not os.path.isabs(self.path) or '\x00' in self.path or len(os.fsencode(self.path)) > 4096:
            raise ValueError('Invalid snapshot path.')
        for name in ('device', 'inode', 'size_bytes', 'mtime_ns', 'ctime_ns'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('Invalid snapshot identity.')
        if not 0 < self.size_bytes <= MAX_INPUT_BYTES or not _digest(self.sha256):
            raise ValueError('Invalid snapshot size/digest.')
        if not isinstance(self.stored_size, Size):
            raise ValueError('Invalid stored dimensions.')
        if type(self.orientation) is not int or not 1 <= self.orientation <= 8 or type(self.orientation_assumed) is not bool:
            raise ValueError('Invalid snapshot orientation.')
        if self.format not in ('JPEG', 'PNG', 'BMP', 'WEBP') or self.mode not in ('RGB', 'RGBA'):
            raise ValueError('Unsupported snapshot format/mode.')
        if self.icc_sha256 is not None and not _digest(self.icc_sha256):
            raise ValueError('Invalid profile fingerprint.')
        if self.srgb_intent is not None and (self.format != 'PNG'
                or type(self.srgb_intent) is not int or self.srgb_intent not in range(4)):
            raise ValueError('Invalid PNG sRGB declaration.')

    @property
    def oriented_size(self):
        return self.stored_size.swapped() if self.orientation in (5, 6, 7, 8) else self.stored_size

    @property
    def stat_identity(self):
        return self.device, self.inode, self.size_bytes, self.mtime_ns, self.ctime_ns

    def to_dict(self):
        data = asdict(self)
        data['stored_size'] = self.stored_size.as_list()
        return data

    @classmethod
    def from_dict(cls, data):
        if type(data) is not dict or set(data) != set(cls.__dataclass_fields__):
            raise ValueError('Invalid snapshot fields.')
        size = data['stored_size']
        if type(size) is not list or len(size) != 2:
            raise ValueError('Invalid snapshot dimensions.')
        return cls(**dict(data, stored_size=Size(*size)))
