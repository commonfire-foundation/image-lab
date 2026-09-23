"""Qt-free export orchestration, catalog reservation and optional normal import."""
from pathlib import Path
import sqlite3
import hashlib
import os
import stat
import unicodedata

from .edit_protocol import EditWorkerError
from .export_encoding import encode_copy
from .export_publication import CopyPublication, PublicationUncertain, MAX_ENCODED_BYTES, _open_directory


def import_copy(result, catalog, cancelled, progress):
    result = dict(result)
    if not result.get('published') or not result.get('path_confirmed'):
        raise ValueError('Only a confirmed published copy may be imported.')
    result['imported'] = False
    result['import_error'] = ''
    if cancelled():
        result['import_error'] = 'Copy saved. Import was cancelled; retry import when ready.'
        return result
    progress('Importing the saved copy…')
    connection = None
    try:
        from .catalog import Catalog
        path = Path(result['path'])
        folder = _open_directory(path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=folder)
            with os.fdopen(fd, 'rb') as stream:
                value = os.fstat(stream.fileno())
                identity = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
                if not stat.S_ISREG(value.st_mode) or value.st_size != result['bytes']:
                    raise ValueError('Published copy changed.')
                digest = hashlib.sha256(); count = 0
                while chunk := stream.read(65536):
                    count += len(chunk)
                    if count > MAX_ENCODED_BYTES or cancelled(): raise ValueError('Import cancelled or output changed.')
                    digest.update(chunk)
                if digest.hexdigest() != result['sha256']: raise ValueError('Published copy contents changed.')
        finally:
            os.close(folder)
        connection = Catalog(catalog[0], catalog[1])
        connection.import_image(path, expected_identity=identity)
        result['imported'] = True
    except Exception as error:
        result['import_error'] = 'Copy saved, but library import failed: ' + str(error)[:800]
    finally:
        if connection is not None:
            try: connection.close()
            except sqlite3.Error as error:
                result['import_error'] = 'Copy retained; library connection cleanup failed: ' + str(error)[:500]
    return result


def export_copy(source, recipe, policy, assumption, destination, options, catalog,
                add_to_library, cancelled, progress):
    destination = Path(destination)
    if not destination.is_absolute(): raise ValueError('Choose an absolute output path.')
    progress('Rendering and verifying full-resolution output…')
    encoded = encode_copy(source, recipe, color_policy=policy, assume_srgb=assumption,
                          options=options, cancelled=cancelled)
    if cancelled(): raise EditWorkerError('cancelled', 'Export cancelled before publication.')
    progress('Publishing a new copy without overwriting…')
    connection = None
    cleanup_error = ''
    try:
        if catalog is not None:
            connection = sqlite3.connect(Path(catalog[0])/'catalog.sqlite3', timeout=10)
            # Other SQLite writers cannot reserve a missing destination between
            # this check and publication. GUI operations are independently guarded.
            connection.set_progress_handler(lambda: 1 if cancelled() else 0, 1000)
            connection.execute('BEGIN IMMEDIATE')
        def reserved(path):
            if connection is None: return False
            # Conservatively fold names even on case-sensitive mounts. This also
            # protects missing reservations on case-folding filesystems, while
            # physical parent identity covers bind-mounted directory aliases.
            name = unicodedata.normalize('NFD', path.name.casefold())
            destination_parent = path.parent.stat()
            for (existing,) in connection.execute('SELECT path FROM images'):
                if cancelled(): raise EditWorkerError('cancelled', 'Export cancelled during reservation checks.')
                if unicodedata.normalize('NFD', Path(existing).name.casefold()) != name: continue
                if existing == str(path): return True
                try: parent = Path(existing).parent.stat()
                except FileNotFoundError: continue
                if (parent.st_dev, parent.st_ino) == (destination_parent.st_dev, destination_parent.st_ino): return True
            return False
        with CopyPublication(source, destination.parent, destination.name, options['format'],
                             is_reserved=reserved, cancelled=cancelled) as transaction:
            transaction.write(encoded.data)
            receipt = transaction.publish(encoded.verify_staging)
        result = {'published': True, 'path': str(receipt.path), 'path_confirmed': receipt.path_confirmed,
                  'directory_synced': receipt.directory_synced, 'warnings': list(receipt.warnings),
                  'bytes': receipt.byte_count, 'sha256': hashlib.sha256(encoded.data).hexdigest(),
                  'size': encoded.info['size'], 'format': options['format'],
                  'imported': False, 'import_error': ''}
    except PublicationUncertain as error:
        result = {'published': None, 'path': str(error.path), 'path_confirmed': False,
                'directory_synced': False, 'warnings': [str(error)], 'imported': False, 'import_error': ''}
    finally:
        if connection is not None:
            # Read-only reservation transaction: rollback releases the write lock.
            try:
                connection.rollback()
            except sqlite3.Error as error:
                cleanup_error = 'Library lock cleanup failed: ' + str(error)[:500]
            finally:
                try: connection.close()
                except sqlite3.Error as error: cleanup_error = 'Library connection cleanup failed: ' + str(error)[:500]
    if cleanup_error: result['warnings'].append(cleanup_error)
    if add_to_library and result.get('published'):
        if catalog is None: result['import_error'] = 'Copy saved; no library is available for import.'
        elif result['path_confirmed']: result = import_copy(result, catalog, cancelled, progress)
        else: result['import_error'] = 'Copy publication needs inspection before library import.'
    return result
