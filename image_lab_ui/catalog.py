"""Local catalog and thumbnail cache; source renames require an explicit action."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3

from PIL import Image
from imagescope.contracts import AnalyzerError
from imagescope.images import EXTENSIONS, prepare_image
from .renaming import FilenameConflict, next_available_name, rename_noreplace, rename_target
from .metadata import DEFAULTS, edit_revision, generated_details, validate_details


class Catalog:
    def __init__(self, directory, thumbnail_directory=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.thumbnails = (Path(thumbnail_directory) if thumbnail_directory is not None
                           else self.directory / "thumbnails").resolve()
        self.thumbnails.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.thumbnails.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.directory / "catalog.sqlite3", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
            mtime INTEGER NOT NULL, bytes INTEGER NOT NULL, thumbnail TEXT NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL,
            prediction TEXT, error TEXT NOT NULL DEFAULT '',
            user_edits TEXT NOT NULL DEFAULT '{}'
        )""")
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(images)')}
            if 'user_edits' not in columns:
                self.db.execute("ALTER TABLE images ADD COLUMN user_edits TEXT NOT NULL DEFAULT '{}'")
            self.db.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def close(self):
        self.db.close()

    @staticmethod
    def fingerprint(path):
        stat = Path(path).stat()
        return stat.st_mtime_ns, stat.st_size

    def import_image(self, path, *, expected_identity=None):
        requested = Path(path)
        path = requested.resolve()
        def check_expected():
            if expected_identity is not None:
                value = requested.stat(follow_symlinks=False)
                actual = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
                if requested != path or requested.is_symlink() or actual != expected_identity:
                    raise ValueError('Published copy changed before or during import.')
        check_expected()
        before = self.fingerprint(path)
        existing = self.db.execute("SELECT * FROM images WHERE path=?", (str(path),)).fetchone()
        if existing and (existing["mtime"], existing["bytes"]) == before and Path(existing["thumbnail"]).is_file():
            return False
        key = hashlib.sha256(f"{path}:{before}".encode()).hexdigest()
        thumbnail = self.thumbnails / (key + ".jpg")
        metadata, image = prepare_image(path)
        width, height = metadata['width'], metadata['height']
        try:
            image.thumbnail((512, 512))
            check_expected()
            if self.fingerprint(path) != before:
                raise ValueError("Image changed while creating its thumbnail; rescan it")
            # Thumbnails alone use a white matte; source/export alpha is untouched.
            if image.mode == 'RGBA':
                with Image.new('RGB', image.size, 'white') as display:
                    display.paste(image, mask=image.getchannel('A'))
                    display.save(thumbnail, 'JPEG', quality=85)
            else:
                image.save(thumbnail, 'JPEG', quality=85)
        finally:
            image.close()
        check_expected()
        with self.db:
            self.db.execute("""INSERT INTO images (path, mtime, bytes, thumbnail, width, height)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, bytes=excluded.bytes,
                thumbnail=excluded.thumbnail, width=excluded.width, height=excluded.height,
                prediction=CASE WHEN images.mtime=excluded.mtime AND images.bytes=excluded.bytes
                    THEN images.prediction ELSE NULL END,
                user_edits=CASE WHEN images.mtime=excluded.mtime AND images.bytes=excluded.bytes
                    THEN images.user_edits ELSE '{}' END,
                error=CASE WHEN images.mtime=excluded.mtime AND images.bytes=excluded.bytes
                    THEN images.error ELSE '' END""", (str(path), *before, str(thumbnail), width, height))
        return True

    def scan(self, folder, cancelled=lambda: False, progress=lambda count, errors: None):
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise ValueError("Choose an existing image folder")
        if folder.is_relative_to(self.directory) or folder.is_relative_to(self.thumbnails):
            raise ValueError("Choose source images, not the catalog or thumbnail cache")
        count = errors = 0
        for root, directories, files in os.walk(folder):
            # Do not recursively catalog our own generated thumbnails.
            directories[:] = sorted(d for d in directories
                                    if (Path(root) / d).resolve() not in (self.directory, self.thumbnails))
            for filename in sorted(files):
                if cancelled():
                    return count, errors, True
                path = Path(root) / filename
                if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                    continue
                try:
                    self.import_image(path)
                    count += 1
                except (OSError, ValueError, AnalyzerError, Image.DecompressionBombError):
                    errors += 1
                if (count + errors) % 20 == 0:
                    progress(count, errors)
        return count, errors, False

    @staticmethod
    def _search(query):
        # Treat wildcard characters literally; the user enters text, not SQL patterns.
        return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    FILTERS = {'all': '1', 'needs_tags': 'prediction IS NULL',
               'tagged': 'prediction IS NOT NULL', 'failed': "error != ''"}

    def _where(self, query, status='all'):
        if status not in self.FILTERS:
            raise ValueError('Unknown library filter')
        clause = """(path LIKE ? ESCAPE '\\' OR json_patch(COALESCE(json_extract(prediction, '$.vision'), '{}'), user_edits) LIKE ? ESCAPE '\\')"""
        return clause + ' AND (' + self.FILTERS[status] + ')', (self._search(query), self._search(query))

    def rows(self, query="", offset=0, limit=120, status='all'):
        where, params = self._where(query, status)
        return [dict(row) for row in self.db.execute(
            f'SELECT * FROM images WHERE {where} ORDER BY path LIMIT ? OFFSET ?', (*params, limit, offset))]

    def count(self, query="", status='all'):
        where, params = self._where(query, status)
        return self.db.execute(f'SELECT count(*) FROM images WHERE {where}', params).fetchone()[0]

    def status_counts(self, query=""):
        # Counts follow text search, not the selected status. Failed can overlap
        # Tagged when regeneration fails and the previous good result survives.
        where, params = self._where(query)
        row = self.db.execute(f"""SELECT count(*) AS 'all',
            count(CASE WHEN prediction IS NULL THEN 1 END) AS needs_tags,
            count(CASE WHEN prediction IS NOT NULL THEN 1 END) AS tagged,
            count(CASE WHEN error != '' THEN 1 END) AS failed
            FROM images WHERE {where}""", params).fetchone()
        return dict(row)

    def matching_ids(self, query="", missing=False, status='all'):
        where, params = self._where(query, status)
        return [row['id'] for row in self.db.execute(
            f'SELECT id FROM images WHERE {where} AND (?=0 OR prediction IS NULL) ORDER BY path',
            (*params, int(missing)))]

    def get(self, image_id):
        row = self.db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        return dict(row) if row else None

    def remove_images(self, image_ids):
        """Forget catalog records atomically; never touch source files or cache paths."""
        if not image_ids or any(type(image_id) is not int or image_id <= 0 for image_id in image_ids):
            raise ValueError('Choose images to remove from the library.')
        ids = list(dict.fromkeys(image_ids))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            has_jobs = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
            for image_id in ids:
                if not self.get(image_id):
                    raise ValueError('An image is no longer in the library. Close and reopen the confirmation.')
                if has_jobs and self.db.execute(
                        "SELECT 1 FROM jobs WHERE image_id=? AND state IN ('queued','running')",
                        (image_id,)).fetchone():
                    raise ValueError('Finish active work and remove these images from the queue first.')
            for image_id in ids:
                # Remove history too: SQLite may reuse a deleted image ID on import.
                if has_jobs:
                    self.db.execute('DELETE FROM jobs WHERE image_id=?', (image_id,))
                self.db.execute('DELETE FROM images WHERE id=?', (image_id,))
        return len(ids)

    def save_details(self, image_id, revision, values):
        values = validate_details(values)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.get(image_id)
            if not row or not generated_details(row):
                raise ValueError('Generate tags for this image before editing its details.')
            if edit_revision(row) != revision:
                raise ValueError('Image details changed. Close and reopen the editor before saving.')
            if self.fingerprint(row['path']) != (row['mtime'], row['bytes']):
                raise ValueError('Image changed since import; rescan before editing.')
            has_jobs = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
            if has_jobs and self.db.execute("SELECT 1 FROM jobs WHERE image_id=? AND state IN ('queued','running')", (image_id,)).fetchone():
                raise ValueError('Remove this image from the queue before editing.')
            generated = generated_details(row)
            edits = {key: value for key, value in values.items()
                     if value != generated.get(key, DEFAULTS[key])}
            self.db.execute('UPDATE images SET user_edits=? WHERE id=?',
                            (json.dumps(edits, ensure_ascii=False), image_id))

    def alternate_name(self, source, name):
        return next_available_name(source, name, reserved=lambda path: bool(
            self.db.execute('SELECT 1 FROM images WHERE path=?', (str(path),)).fetchone()))

    def rename_image(self, image_id, expected_path, name):
        """Rename one unchanged source and preserve its catalog identity/results."""
        moved = False
        source = Path(expected_path)
        target = rename_target(source, name)
        try:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                row = self.get(image_id)
                if not row or row['path'] != str(source):
                    raise ValueError('The selected image changed. Reopen the naming dialog.')
                if source.is_symlink() or not source.is_file():
                    raise ValueError('The source is missing or is not a regular image file.')
                if self.fingerprint(source) != (row['mtime'], row['bytes']):
                    raise ValueError('Image changed since import; rescan before renaming.')
                if self.db.execute('SELECT 1 FROM images WHERE path=?', (str(target),)).fetchone():
                    raise FilenameConflict('That filename is already in the catalog. Choose another name.')
                has_jobs = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
                if has_jobs and self.db.execute("SELECT 1 FROM jobs WHERE image_id=? AND state IN ('queued','running')", (image_id,)).fetchone():
                    raise ValueError('Remove this image from the queue before renaming.')
                rename_noreplace(source, target)
                moved = True
                self.db.execute('UPDATE images SET path=? WHERE id=?', (str(target), image_id))
        except Exception:
            if moved:
                try:
                    rename_noreplace(target, source)
                except OSError as recovery_error:
                    raise RuntimeError(f'Catalog update failed and the rename could not be undone. '
                                       f'The file is at {target}; the catalog still points to {source}. '
                                       'Restore the original name or rescan the folder.') from recovery_error
            raise
        return str(target)

    def store_result(self, image_id, fingerprint, prediction=None, error=""):
        row = self.get(image_id)
        if not row or self.fingerprint(row["path"]) != fingerprint or (row["mtime"], row["bytes"]) != fingerprint:
            raise ValueError("Image changed since import; rescan the folder before analyzing it")
        with self.db:
            if prediction is None:
                # A failed re-analysis does not erase a previous successful prediction.
                self.db.execute("UPDATE images SET error=? WHERE id=?", (error, image_id))
            else:
                self.db.execute("UPDATE images SET prediction=?, error='' WHERE id=?",
                                (json.dumps(prediction), image_id))
