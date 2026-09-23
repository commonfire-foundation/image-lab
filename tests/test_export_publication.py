"""Real local-filesystem publication plus deterministic boundary fault injection."""
import errno
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier, Event
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from PIL import Image
from image_lab_ui.edit_protocol import SourceSnapshot
from image_lab_ui.edit_recipe import Size
from image_lab_ui import export_publication as publication

ROOT = Path(__file__).resolve().parents[1]


def png(size, color):
    stream = io.BytesIO()
    with Image.new('RGB', size, color) as image:
        image.save(stream, format='PNG')
    return stream.getvalue()


def snapshot(path):
    value = path.stat()
    return SourceSnapshot(str(path), value.st_dev, value.st_ino, value.st_size,
                          value.st_mtime_ns, value.st_ctime_ns,
                          hashlib.sha256(path.read_bytes()).hexdigest(),
                          Size(6, 4), 1, True, 'PNG', 'RGB', None)


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux publication contract')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'results')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.png'
        self.original = png((6, 4), 'red')
        self.source.write_bytes(self.original)
        self.snapshot = snapshot(self.source)
        self.output = self.root / 'copies'; self.output.mkdir()
        self.payload = png((5, 3), 'blue')
        self.destination = self.output / 'copy.png'
        self.cancel = Event()
        self.reserved = False

    def transaction(self, **options):
        return publication.CopyPublication(self.snapshot, self.output, 'copy.png', 'PNG',
                  is_reserved=lambda path: self.reserved, cancelled=self.cancel.is_set, **options)

    def verify(self, stream):
        with Image.open(stream) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.size, (5, 3))
            image.verify()

    def staged(self, **options):
        transaction = self.transaction(**options)
        self.addCleanup(transaction.close)
        transaction.write(self.payload)
        return transaction

    def test_real_publication_private_permissions_and_original_unchanged(self):
        with self.transaction() as transaction:
            self.assertEqual(transaction.write(self.payload[:10]), 10)
            transaction.write(self.payload[10:])
            self.assertEqual(list(self.output.iterdir()), [])
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published and receipt.path_confirmed and receipt.directory_synced)
        self.assertEqual(receipt.byte_count, len(self.payload))
        self.assertEqual(receipt.path, self.destination)
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertEqual(self.destination.stat().st_mode & 0o077, 0)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.source.stat().st_mtime_ns, self.snapshot.mtime_ns)
        with self.assertRaises(RuntimeError):
            transaction.publish(self.verify)

    def test_filename_and_format_validation(self):
        for name in ('../x.png', '/x.png', ' x.png', 'x.png ', '..png', 'x\0.png',
                     'x\\y.png', 'x:.png', 'x.jpg', 'x.png.', 'a'*256+'.png'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                publication.export_name(name, 'PNG')
        for format in ('png', 'TIFF', None, False):
            with self.assertRaises(ValueError): publication.export_name('x.png', format)
        self.assertEqual(publication.export_name('copy.PNG', 'PNG'), 'copy.PNG')
        self.assertEqual(publication.export_name('copy.jpeg', 'JPEG'), 'copy.jpeg')
        self.assertEqual(publication.export_name('copy.webp', 'WEBP'), 'copy.webp')

    def test_original_path_and_missing_catalog_reservation_rejected(self):
        with self.assertRaises(publication.ReservedDestination):
            publication.CopyPublication(self.snapshot, self.root, 'source.png', 'PNG', is_reserved=lambda p: False)
        self.reserved = True
        with self.assertRaises(publication.ReservedDestination): self.transaction()
        self.assertFalse(self.destination.exists())

    def test_existing_files_symlinks_and_hardlinks_never_replaced(self):
        for kind in ('file', 'symlink', 'dangling', 'hardlink'):
            with self.subTest(kind=kind):
                if kind == 'file': self.destination.write_bytes(b'existing')
                elif kind == 'symlink': self.destination.symlink_to(self.source)
                elif kind == 'dangling': self.destination.symlink_to(self.root / 'missing')
                else: os.link(self.source, self.destination)
                self.snapshot = snapshot(self.source)  # Creating a hardlink changes ctime.
                before = self.destination.lstat()
                with self.assertRaises(FileExistsError): self.transaction()
                self.assertEqual(self.destination.lstat().st_ino, before.st_ino)
                self.assertEqual(self.source.read_bytes(), self.original)
                self.destination.unlink()

    def test_parent_symlink_and_traversal_rejected(self):
        alias = self.root / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        for path in (alias / 'copies', self.output / '..' / 'copies'):
            with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                publication.CopyPublication(self.snapshot, path, 'copy.png', 'PNG', is_reserved=lambda p: False)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_changed_source_rejected_at_entry_and_after_verification(self):
        transaction = self.staged()
        def modify(stream):
            self.verify(stream)
            self.source.write_bytes(png((6, 4), 'green'))
        with self.assertRaises(publication.SourceChanged): transaction.publish(modify)
        with self.assertRaises(publication.SourceChanged): self.transaction()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_new_catalog_reservation_rechecked_before_commit(self):
        transaction = self.staged()
        def reserve(stream):
            self.verify(stream); self.reserved = True
        with self.assertRaises(publication.ReservedDestination): transaction.publish(reserve)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_destination_race_uses_atomic_no_replace(self):
        transaction = self.staged()
        real_link = publication._link_fd
        def collide(fd, directory_fd, name):
            self.destination.write_bytes(b'racing owner')
            real_link(fd, directory_fd, name)
        with patch.object(publication, '_link_fd', side_effect=collide), self.assertRaises(FileExistsError):
            transaction.publish(self.verify)
        self.assertEqual(self.destination.read_bytes(), b'racing owner')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_two_publishers_have_exactly_one_winner(self):
        first, second = self.staged(), self.staged()
        barrier = Barrier(2); real_link = publication._link_fd
        def link(fd, directory_fd, name):
            barrier.wait(timeout=5)
            real_link(fd, directory_fd, name)
        def run(transaction):
            try: return transaction.publish(self.verify)
            except FileExistsError: return 'collision'
        with patch.object(publication, '_link_fd', side_effect=link), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(run, item) for item in (first, second)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results.count('collision'), 1)
        self.assertEqual(sum(isinstance(result, publication.PublicationReceipt) for result in results), 1)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_directory_swap_before_commit_aborts_without_output(self):
        transaction = self.staged(); moved = self.root / 'moved'
        def move(stream):
            self.verify(stream); self.output.rename(moved); self.output.mkdir()
        with self.assertRaises(OSError): transaction.publish(move)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(moved.iterdir()), [])

    def test_directory_swap_at_commit_is_reported_and_does_not_redirect_write(self):
        transaction = self.staged(); moved = self.root / 'moved'
        real_link = publication._link_fd
        def move(fd, directory_fd, name):
            self.output.rename(moved); self.output.mkdir()
            real_link(fd, directory_fd, name)
        with patch.object(publication, '_link_fd', side_effect=move):
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published)
        self.assertFalse(receipt.path_confirmed)
        self.assertTrue(receipt.warnings)
        self.assertFalse(self.destination.exists())
        self.assertEqual((moved / 'copy.png').read_bytes(), self.payload)

    def test_cancellation_before_and_during_verification_leaves_no_copy(self):
        self.cancel.set()
        with self.assertRaises(publication.PublicationCancelled): self.transaction()
        self.cancel.clear(); transaction = self.staged()
        def cancel(stream): self.verify(stream); self.cancel.set()
        with self.assertRaises(publication.PublicationCancelled): transaction.publish(cancel)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_cancellation_after_link_is_success_not_rollback(self):
        transaction = self.staged(); real_link = publication._link_fd
        def cancel(fd, directory_fd, name):
            real_link(fd, directory_fd, name); self.cancel.set()
        with patch.object(publication, '_link_fd', side_effect=cancel):
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_invalid_or_mutating_verifier_cannot_publish(self):
        def invalid(stream): raise ValueError('bad encoded output')
        def mutating(stream): os.ftruncate(stream.fileno(), 1)
        for verify in (invalid, mutating, lambda stream: False):
            with self.subTest(verify=verify):
                transaction = self.staged()
                with self.assertRaises(ValueError): transaction.publish(verify)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_empty_and_oversize_output_rejected(self):
        with self.transaction() as transaction, self.assertRaises(ValueError): transaction.publish(self.verify)
        with self.transaction(max_bytes=4) as transaction, self.assertRaises(ValueError): transaction.write(self.payload)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_disk_full_and_file_sync_failure_leave_no_copy(self):
        with self.transaction() as transaction:
            with patch.object(publication.os, 'write', side_effect=OSError(errno.ENOSPC, 'disk full')):
                with self.assertRaises(OSError): transaction.write(self.payload)
        transaction = self.staged()
        with patch.object(publication.os, 'fsync', side_effect=OSError(errno.EIO, 'sync failed')):
            with self.assertRaises(OSError): transaction.publish(self.verify)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_directory_sync_failure_is_partial_success(self):
        transaction = self.staged(); real_sync = os.fsync
        def sync(fd):
            if fd == transaction._directory_fd: raise OSError(errno.EIO, 'directory sync failed')
            return real_sync(fd)
        with patch.object(publication.os, 'fsync', side_effect=sync):
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published and receipt.path_confirmed)
        self.assertFalse(receipt.directory_synced)
        self.assertTrue(receipt.warnings)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_error_reported_after_link_is_partial_success(self):
        transaction = self.staged(); real_link = publication._link_fd
        def error(fd, directory_fd, name):
            real_link(fd, directory_fd, name); raise OSError(errno.EIO, 'late error')
        with patch.object(publication, '_link_fd', side_effect=error):
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published and receipt.warnings)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_indeterminate_link_error_does_not_claim_nothing_was_published(self):
        transaction = self.staged()
        with patch.object(publication, '_link_fd', side_effect=OSError(errno.EIO, 'I/O failure')):
            with self.assertRaises(publication.PublicationUncertain) as caught:
                transaction.publish(self.verify)
        self.assertIsNone(caught.exception.published)
        self.assertEqual(caught.exception.path, self.destination)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_source_change_after_link_does_not_delete_copy(self):
        transaction = self.staged(); real_link = publication._link_fd
        def change(fd, directory_fd, name):
            real_link(fd, directory_fd, name); self.source.write_bytes(b'changed externally')
        with patch.object(publication, '_link_fd', side_effect=change):
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published and receipt.warnings)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_permission_and_link_unavailability_leave_no_copy(self):
        for code in (errno.EACCES, errno.ENOTSUP, errno.ENOENT):
            transaction = self.staged()
            with patch.object(publication, '_link_fd', side_effect=OSError(code, 'link denied')):
                with self.assertRaises(OSError): transaction.publish(self.verify)
            self.assertEqual(list(self.output.iterdir()), [])

    def test_partial_write_failure_cleans_anonymous_stage(self):
        transaction = self.transaction(); real_write = os.write
        calls = 0
        def full(fd, data):
            nonlocal calls
            calls += 1
            if calls == 1: return real_write(fd, data[:4])
            raise OSError(errno.ENOSPC, 'disk filled mid-write')
        with patch.object(publication.os, 'write', side_effect=full):
            with self.assertRaises(OSError): transaction.write(self.payload)
        self.assertIsNone(transaction._fd)
        self.assertEqual(list(self.output.iterdir()), [])
        with self.assertRaises(RuntimeError): transaction.publish(self.verify)

    def test_removed_destination_after_commit_is_not_reported_as_unpublished(self):
        transaction = self.staged(); real_link = publication._link_fd
        def remove(fd, directory_fd, name):
            real_link(fd, directory_fd, name); self.destination.unlink()
        with patch.object(publication, '_link_fd', side_effect=remove):
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published)
        self.assertFalse(receipt.path_confirmed)
        self.assertTrue(receipt.warnings)

    def test_close_error_after_commit_preserves_receipt(self):
        transaction = self.staged(); real_close = os.close
        file_fd = transaction._fd
        def close(fd):
            real_close(fd)
            if fd == file_fd: raise OSError(errno.EIO, 'close reported error')
        with patch.object(publication.os, 'close', side_effect=close):
            receipt = transaction.publish(self.verify)
        self.assertTrue(receipt.published and receipt.warnings)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_unsupported_filesystem_or_anonymous_staging_fails_closed(self):
        with patch.object(publication, '_filesystem', side_effect=OSError(errno.ENOTSUP, 'filesystem')):
            with self.assertRaises(OSError): self.transaction()
        real_open = os.open
        def unsupported(path, flags, *args, **kwargs):
            if flags & os.O_TMPFILE == os.O_TMPFILE: raise OSError(errno.ENOTSUP, 'anonymous staging')
            return real_open(path, flags, *args, **kwargs)
        with patch.object(publication.os, 'open', side_effect=unsupported):
            with self.assertRaises(OSError): self.transaction()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_crash_before_publication_leaves_no_staging_names(self):
        script = '''import os, sys
from image_lab_ui.export_publication import CopyPublication
from image_lab_ui.edit_protocol import SourceSnapshot, strict_json
source = SourceSnapshot.from_dict(strict_json(sys.argv[1]))
transaction = CopyPublication(source, sys.argv[2], 'copy.png', 'PNG', is_reserved=lambda p: False)
transaction.write(b'partial encoded output')
os._exit(23)
'''
        import json
        result = subprocess.run([sys.executable, '-c', script, json.dumps(self.snapshot.to_dict()), str(self.output)],
                                cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__': unittest.main()
