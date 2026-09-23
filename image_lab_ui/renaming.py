"""Validated, same-directory renames that never replace a destination."""
import ctypes
import errno
import os
from pathlib import Path
import re
import sys


class FilenameConflict(ValueError):
    """A destination path is already reserved in the catalog."""


def rename_target(source, name):
    source = Path(source)
    if (not name or name != name.strip() or name in {'.', '..'}
            or any(char in name for char in '/\\<>:"|?*')
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or name.endswith('.') or len(os.fsencode(name)) > 255):
        raise ValueError('Enter a filename only, without paths or special characters.')
    if Path(name).suffix != source.suffix:
        raise ValueError(f'Keep the original {source.suffix} extension.')
    if not Path(name).stem.strip('.'):
        raise ValueError('Enter a name before the extension.')
    if name == source.name:
        raise ValueError('Choose a different filename.')
    return source.with_name(name)


def next_available_name(source, name, reserved=lambda path: False, limit=1000):
    """Find a numbered alternative without reserving or changing anything."""
    target = rename_target(source, name)
    stem, extension = target.stem, target.suffix
    match = re.fullmatch(r'(.+)-(\d+)', stem)
    start = 2
    if match and int(match[2]) >= 2:
        stem, start = match[1], int(match[2]) + 1
    for number in range(start, start + limit):
        suffix = f'-{number}{extension}'
        shortened = stem
        while shortened and len(os.fsencode(shortened + suffix)) > 255:
            shortened = shortened[:-1]
        if not shortened:
            return ''
        candidate = target.with_name(shortened + suffix)
        # lexists includes dangling symlinks; catalog rows reserve missing paths too.
        if candidate != Path(source) and not os.path.lexists(candidate) and not reserved(candidate):
            return candidate.name
    return ''


def rename_noreplace(source, destination):
    """Fail closed if this platform/filesystem lacks an atomic no-replace rename."""
    if sys.platform == 'win32':
        os.rename(source, destination)  # Windows refuses an existing destination.
        return
    if not sys.platform.startswith('linux'):
        raise OSError(errno.ENOTSUP, 'Safe renaming is not supported on this platform')
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError:
        raise OSError(errno.ENOTSUP, 'Safe renaming requires renameat2') from None
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    # AT_FDCWD, RENAME_NOREPLACE: existence checks alone would have a race.
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))
