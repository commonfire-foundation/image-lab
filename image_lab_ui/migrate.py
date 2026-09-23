"""Explicit, non-destructive migration from a development catalog to user storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .storage import storage_paths


def migrate_catalog(source_directory, destination_directory, thumbnail_directory):
    # Use the same locks as the GUI; never copy underneath an active desktop owner.
    from PySide6.QtCore import QLockFile

    source = Path(source_directory).resolve()
    destination = Path(destination_directory).resolve()
    thumbnails = Path(thumbnail_directory).resolve()
    source_db = source / 'catalog.sqlite3'
    destination_db = destination / 'catalog.sqlite3'
    if not source_db.is_file():
        raise ValueError(f'No source catalog: {source_db}')
    if source == destination:
        raise ValueError('Source and destination must be different')
    if destination_db.exists():
        raise FileExistsError(f'Refusing to replace an existing catalog: {destination_db}')
    if thumbnails.is_relative_to(source):
        raise ValueError('Destination thumbnails must be outside the source catalog')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    locks = []
    created = []
    temporary = None
    published = False
    src = dst = None
    try:
        for directory in (source, destination):
            lock = QLockFile(str(directory / 'desktop.lock'))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                raise RuntimeError(f'Close Image Lab before migrating: {directory}')
            locks.append(lock)
        thumbnails.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        thumbnails.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix='.migration-', suffix='.sqlite3', dir=destination)
        os.close(fd)
        temporary = Path(name)
        src = sqlite3.connect(source_db.as_uri() + '?mode=ro', uri=True)
        dst = sqlite3.connect(temporary)
        # SQLite backup includes committed WAL data; copying just the DB file does not.
        src.backup(dst)
        dst.execute('PRAGMA journal_mode=DELETE')
        report = {'copied_thumbnails': 0, 'reused_thumbnails': 0, 'missing_thumbnails': 0}
        tables = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('images', 'jobs', 'batches'):
            report[table] = dst.execute(f'SELECT count(*) FROM {table}').fetchone()[0] if table in tables else 0
        report['predictions'] = dst.execute('SELECT count(*) FROM images WHERE prediction IS NOT NULL').fetchone()[0]
        for image_id, old_name in dst.execute('SELECT id, thumbnail FROM images').fetchall():
            old_path = Path(old_name).resolve()
            if not old_path.is_relative_to(source / 'thumbnails'):
                raise ValueError(f'Thumbnail is outside the source cache: {old_path}')
            new_path = thumbnails / old_path.name
            if old_path.is_file():
                if new_path.exists():
                    with old_path.open('rb') as old, new_path.open('rb') as new:
                        if hashlib.file_digest(old, 'sha256').digest() != hashlib.file_digest(new, 'sha256').digest():
                            raise FileExistsError(f'Conflicting cached thumbnail: {new_path}')
                    report['reused_thumbnails'] += 1
                else:
                    with old_path.open('rb') as old, new_path.open('xb') as new:
                        created.append(new_path)
                        shutil.copyfileobj(old, new)
                    report['copied_thumbnails'] += 1
            else:
                report['missing_thumbnails'] += 1
            dst.execute('UPDATE images SET thumbnail=? WHERE id=?', (str(new_path), image_id))
        dst.commit()
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Migrated database failed its integrity check')
        dst.close()
        dst = None
        # Publish atomically, without ever overwriting a database created concurrently.
        os.link(temporary, destination_db)
        published = True
        temporary.unlink()
        temporary = None
        report.update(database=str(destination_db), thumbnails=str(thumbnails), source_preserved=str(source_db))
        return report
    except Exception:
        if not published:
            for path in created:
                path.unlink(missing_ok=True)
        raise
    finally:
        if src:
            src.close()
        if dst:
            dst.close()
        if temporary:
            temporary.unlink(missing_ok=True)
        for lock in reversed(locks):
            lock.unlock()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Copy a project catalog to XDG user storage; keep the source as backup')
    parser.add_argument('--source', type=Path, required=True, help='Existing catalog directory, e.g. ./results/desktop')
    parser.add_argument('--data-dir', type=Path, help='Destination catalog override')
    parser.add_argument('--cache-dir', type=Path, help='Destination cache root override')
    args = parser.parse_args(argv)
    paths = storage_paths(args.data_dir, args.cache_dir)
    try:
        report = migrate_catalog(args.source, paths.data, paths.thumbnails)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f'Migration stopped: {exc}\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
