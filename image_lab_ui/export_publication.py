"""Blocking Linux copy-publication primitive; not an encoder or a UI export API.

Use on one supervisor thread, with a bounded encoder/verifier and a caller-owned
catalog reservation guard. Anonymous staging is linked by descriptor, never by a
replaceable temporary filename. No source or existing destination is written.
"""
from dataclasses import dataclass, field
import ctypes
import errno
import os
from pathlib import Path
import stat
import sys

from .edit_protocol import SourceSnapshot

MAX_ENCODED_BYTES = 192 * 1024 * 1024
_LOCAL_FILESYSTEMS = {0xEF53, 0x9123683E, 0x58465342, 0x01021994}  # ext, btrfs, xfs, tmpfs
_TMPFS = 0x01021994


class PublicationCancelled(RuntimeError):
    pass


class SourceChanged(RuntimeError):
    pass


class ReservedDestination(ValueError):
    pass


class PublicationUncertain(OSError):
    """A commit was attempted, but its outcome cannot safely be called failure."""
    published = None

    def __init__(self, path, cause):
        self.path = path
        super().__init__(cause.errno, 'Copy publication is uncertain; inspect the destination before retrying.', str(path))


@dataclass(frozen=True)
class PublicationReceipt:
    """Publication happened, even if its path or durability cannot be confirmed."""
    path: Path
    byte_count: int
    path_confirmed: bool
    directory_synced: bool
    warnings: tuple[str, ...]
    published: bool = field(default=True, init=False)


def export_name(name, format):
    extensions = {'PNG': {'.png'}, 'JPEG': {'.jpg', '.jpeg'}, 'WEBP': {'.webp'}}
    if type(format) is not str or format not in extensions:
        raise ValueError('Choose PNG, JPEG, or WebP explicitly.')
    if (type(name) is not str or not name or name != name.strip() or name in {'.', '..'}
            or any(c in name for c in '/\\<>:"|?*')
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or name.endswith('.') or len(os.fsencode(name)) > 255
            or not Path(name).stem.strip('.')):
        raise ValueError('Enter a filename only, without paths or special characters.')
    if Path(name).suffix.lower() not in extensions[format]:
        raise ValueError('Filename extension must match the selected export format.')
    return name


def _open_directory(path):
    """Walk from / using directory descriptors; do not follow any symlink."""
    path = Path(path)
    if not path.is_absolute() or path.anchor != '/' or '..' in path.parts or '\0' in str(path):
        raise ValueError('Choose an absolute directory without parent traversal.')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _filesystem(fd):
    # Linux statfs starts with a native signed long. The opaque buffer exceeds all
    # supported Linux statfs layouts; the remaining ABI fields are not interpreted.
    data = ctypes.create_string_buffer(512)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fstatfs.argtypes = [ctypes.c_int, ctypes.c_void_p]
    libc.fstatfs.restype = ctypes.c_int
    if libc.fstatfs(fd, data):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    kind = ctypes.c_long.from_buffer(data).value & 0xFFFFFFFF
    if kind not in _LOCAL_FILESYSTEMS:
        raise OSError(errno.ENOTSUP, 'Destination filesystem is not accepted for safe publication.')
    return kind


def _identity(value):
    return value.st_dev, value.st_ino


def _source_current(source):
    path = Path(source.path)
    parent = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        try:
            value = os.fstat(fd)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    actual = (*_identity(value), value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if not stat.S_ISREG(value.st_mode) or actual != source.stat_identity:
        raise SourceChanged('Original changed before copy publication.')


def _link_fd(fd, directory_fd, name):
    # dst_dir_fd forces linkat; follow_symlinks follows the proc descriptor, not a
    # staging pathname. linkat creates a new entry atomically and never replaces.
    os.link(f'/proc/self/fd/{fd}', name, dst_dir_fd=directory_fd, follow_symlinks=True)


class CopyPublication:
    """One-shot private staging transaction. No GUI/decoder work belongs here.

    verify(readable_stream) must raise on invalid output and return None on success.
    Reservation callbacks must stay valid through publication (the caller owns
    catalog serialization). Source bytes/digest must already be checked by the
    isolated renderer; this layer rechecks filesystem identity, not pixel provenance.
    Cancellation is checked up to the link attempt; a racing commit may win.
    Afterwards return a receipt, never delete the copy or pretend that publication
    did not happen. Indeterminate link failures raise PublicationUncertain.
    """
    def __init__(self, source, directory, name, format, *, is_reserved,
                 cancelled=lambda: False, max_bytes=MAX_ENCODED_BYTES):
        self._directory_fd = self._fd = None
        self._sealed = False
        self._count = 0
        if not sys.platform.startswith('linux') or not hasattr(os, 'O_TMPFILE'):
            raise OSError(errno.ENOTSUP, 'Safe copy publication requires Linux anonymous staging.')
        if not isinstance(source, SourceSnapshot):
            raise TypeError('A prepared source snapshot is required.')
        if not callable(is_reserved) or not callable(cancelled):
            raise TypeError('Reservation and cancellation callbacks are required.')
        if type(max_bytes) is not int or not 0 < max_bytes <= MAX_ENCODED_BYTES:
            raise ValueError('Invalid encoded-output budget.')
        self._source = source
        self._directory = Path(directory)
        self._name = export_name(name, format)
        if len(os.fsencode(self.path)) >= 4096:
            raise ValueError('Destination path exceeds the supported path budget.')
        self._reserved, self._cancelled, self._max_bytes = is_reserved, cancelled, max_bytes
        try:
            self._cancel()
            self._directory_fd = _open_directory(self.directory)
            self._directory_identity = _identity(os.fstat(self._directory_fd))
            self._kind = _filesystem(self._directory_fd)
            _source_current(source)
            if self.path == Path(source.path):
                raise ReservedDestination('Choose a copy name, not the original path.')
            self._destination_clear()
            self._fd = os.open('.', os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC,
                               0o600, dir_fd=self._directory_fd)
        except BaseException:
            self.close()
            raise

    @property
    def source(self):
        return self._source

    @property
    def directory(self):
        return self._directory

    @property
    def name(self):
        return self._name

    @property
    def path(self):
        return self._directory / self._name

    def _cancel(self):
        if self._cancelled():
            raise PublicationCancelled('Copy publication cancelled before creating a destination.')

    def _destination_clear(self):
        if self._reserved(self.path):
            raise ReservedDestination('Destination is reserved by the library, even if its file is missing.')
        try:
            os.stat(self.name, dir_fd=self._directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError(errno.EEXIST, 'Choose a new name; destination already exists.', str(self.path))

    def _directory_current(self):
        current = _open_directory(self.directory)
        try:
            if _identity(os.fstat(current)) != self._directory_identity:
                raise OSError(errno.ESTALE, 'Destination directory changed.')
        finally:
            os.close(current)

    def write(self, data):
        if self._sealed or self._fd is None:
            raise RuntimeError('Publication is sealed or closed.')
        try:
            if type(data) is not bytes:
                raise TypeError('Encoded chunks must be bytes.')
            if self._count + len(data) > self._max_bytes:
                raise ValueError('Encoded copy exceeds the output budget.')
            view = memoryview(data)
            while view:
                self._cancel()
                count = os.write(self._fd, view[:1024 * 1024])
                if count <= 0:
                    raise OSError(errno.EIO, 'Incomplete staging write.')
                self._count += count
                view = view[count:]
            return len(data)
        except BaseException:
            self.close()
            raise

    def publish(self, verify):
        if self._sealed or self._fd is None or self._directory_fd is None:
            raise RuntimeError('Publication is sealed or closed.')
        self._sealed = True
        try:
            self._cancel()
            if not callable(verify) or not self._count:
                raise ValueError('A nonempty encoded copy and verifier are required.')
            value = os.fstat(self._fd)
            if value.st_size != self._count or value.st_nlink != 0:
                raise ValueError('Staging identity or encoded size changed.')
            with os.fdopen(os.dup(self._fd), 'rb') as stream:
                stream.seek(0)
                if verify(stream) is not None:
                    raise ValueError('Verifier must raise on failure and return None on success.')
            checked = os.fstat(self._fd)
            if (checked.st_size != value.st_size or checked.st_nlink != 0
                    or checked.st_mtime_ns != value.st_mtime_ns or checked.st_ctime_ns != value.st_ctime_ns):
                raise ValueError('Verifier modified staged output.')
            self._cancel()
            os.fsync(self._fd)
            _source_current(self.source)
            self._directory_current()
            self._destination_clear()
            self._cancel()
            warnings = []
            try:
                _link_fd(self._fd, self._directory_fd, self.name)
            except OSError as error:
                # A positive link count proves publication. Zero does not prove it
                # never happened (e.g. I/O failure plus concurrent removal).
                try:
                    linked = os.fstat(self._fd).st_nlink > 0
                except OSError as inspection_error:
                    raise PublicationUncertain(self.path, inspection_error) from error
                if not linked:
                    known_rejection = {errno.EACCES, errno.EEXIST, errno.EINVAL, errno.ELOOP,
                        errno.EMLINK, errno.ENAMETOOLONG, errno.ENOENT, errno.ENOMEM,
                        errno.ENOSPC, errno.ENOTDIR, errno.EPERM, errno.EROFS, errno.EXDEV,
                        errno.ENOTSUP, errno.EDQUOT, errno.EBADF}
                    if error.errno not in known_rejection:
                        raise PublicationUncertain(self.path, error) from error
                    raise
                warnings.append('Publication reported an error after linking; inspect the copy.')
            # Commit point crossed: subsequent problems MUST be partial success.
            synced = False
            try:
                os.fsync(self._directory_fd)
                synced = True
            except OSError:
                warnings.append('Copy published, but directory synchronization failed; durability is uncertain.')
            confirmed = False
            try:
                self._directory_current()
                target = os.stat(self.name, dir_fd=self._directory_fd, follow_symlinks=False)
                confirmed = _identity(target) == _identity(value) and stat.S_ISREG(target.st_mode)
            except OSError:
                pass
            if not confirmed:
                warnings.append('Copy was published, but its destination path changed or is no longer confirmed.')
            try:
                _source_current(self.source)
            except (OSError, SourceChanged):
                warnings.append('Original changed during publication; the published copy was not removed.')
            if self._kind == _TMPFS:
                warnings.append('Destination is memory-backed; synchronization does not make it persistent.')
            receipt = PublicationReceipt(self.path, self._count, confirmed, synced, tuple(warnings))
        finally:
            close_errors = self.close()
        if close_errors:
            receipt = PublicationReceipt(receipt.path, receipt.byte_count, receipt.path_confirmed,
                                         receipt.directory_synced, receipt.warnings + close_errors)
        return receipt

    def close(self):
        self._sealed = True
        errors = []
        for attribute in ('_fd', '_directory_fd'):
            fd = getattr(self, attribute, None)
            if fd is not None:
                setattr(self, attribute, None)
                try:
                    os.close(fd)
                except OSError:
                    # Linux releases the descriptor even on close I/O errors;
                    # retrying risks closing an unrelated, reused descriptor.
                    errors.append('Descriptor close reported an error; inspect the published copy if present.')
        return tuple(errors)

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        self.close()

    def __del__(self):
        self.close()
