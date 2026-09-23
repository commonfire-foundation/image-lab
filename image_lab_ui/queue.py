"""One additive, durable analysis queue; batches group runs for recovery/history."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .analyzer_client import DEFAULT_COMMAND, analyzer_identity


class JobQueue:
    def __init__(self, catalog, analyzer_command=DEFAULT_COMMAND):
        self.analyzer_command = analyzer_command
        self.catalog = catalog
        self.db = catalog.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL,
                image_id INTEGER NOT NULL, mtime INTEGER NOT NULL, bytes INTEGER NOT NULL,
                model TEXT NOT NULL, prompt_version TEXT NOT NULL, prompt TEXT NOT NULL,
                state TEXT NOT NULL, elapsed REAL, error TEXT NOT NULL DEFAULT '',
                started REAL, finished REAL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_image ON jobs(image_id)
                WHERE state IN ('queued', 'running');
            CREATE INDEX IF NOT EXISTS batch_jobs ON jobs(batch_id, state, id);
            CREATE INDEX IF NOT EXISTS image_jobs ON jobs(image_id, id);
        """)

    def recover(self):
        """Only call after obtaining exclusive desktop ownership of the catalog."""
        with self.db:
            self.db.execute("""UPDATE jobs SET state=CASE
                WHEN batch_id IN (SELECT id FROM batches WHERE state='stopped') THEN 'canceled'
                ELSE 'queued' END, started=NULL WHERE state='running'""")
            self.db.execute("UPDATE batches SET state='paused' WHERE state='running'")
        for row in self.db.execute("SELECT id FROM batches WHERE state='paused'").fetchall():
            self.settle(row['id'])

    def latest(self):
        row = self.db.execute("SELECT id FROM batches ORDER BY id DESC LIMIT 1").fetchone()
        return row['id'] if row else None

    def enqueue(self, image_ids, replace=False):
        # Snapshot task metadata through the public CLI, not inference internals.
        identity = analyzer_identity(self.analyzer_command)
        # Serialize with worker completion so an append cannot land in a run
        # that was just marked complete. Each job keeps its own source snapshot.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            active = self.db.execute("SELECT id FROM batches WHERE state IN ('running','paused') ORDER BY id DESC LIMIT 1").fetchone()
            batch_id = active['id'] if active else self.db.execute(
                "INSERT INTO batches(state, created) VALUES ('running', ?)", (time.time(),)).lastrowid
            count = 0
            for image_id in dict.fromkeys(image_ids):
                row = self.catalog.get(image_id)
                if row is None or (row['prediction'] and not replace):
                    continue
                if self.db.execute("SELECT 1 FROM jobs WHERE image_id=? AND state IN ('queued','running')", (image_id,)).fetchone():
                    continue
                self.db.execute("""INSERT INTO jobs
                    (batch_id,image_id,mtime,bytes,model,prompt_version,prompt,state)
                    VALUES (?,?,?,?,?,?,?,'queued')""",
                    (batch_id, image_id, row['mtime'], row['bytes'], identity['model'], identity['prompt_version'], identity['prompt']))
                count += 1
            if not count:
                if not active:
                    self.db.execute("DELETE FROM batches WHERE id=?", (batch_id,))
                return None
        return batch_id

    def get(self, job_id):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def claim(self, batch_id):
        # The write transaction makes claim atomic, even with multiple DB connections.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("""SELECT j.* FROM jobs j JOIN batches b ON b.id=j.batch_id
                WHERE j.batch_id=? AND b.state='running' AND j.state='queued'
                AND NOT EXISTS (SELECT 1 FROM jobs WHERE state='running') ORDER BY j.id LIMIT 1""",
                (batch_id,)).fetchone()
            if row:
                self.db.execute("UPDATE jobs SET state='running',started=? WHERE id=?", (time.time(),row['id']))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get(row['id']) if row else None

    def succeed(self, job_id, prediction):
        job = self.get(job_id)
        row = self.catalog.get(job['image_id'])
        fingerprint = (job['mtime'], job['bytes'])
        if not row or (row['mtime'], row['bytes']) != fingerprint or self.catalog.fingerprint(row['path']) != fingerprint:
            raise ValueError("Image changed since it was queued; rescan before retrying")
        if job['state'] != 'running':
            raise ValueError("Job is no longer running")
        # Prediction and completion commit together: restart cannot rerun a saved success.
        with self.db:
            self.db.execute("UPDATE images SET prediction=?,error='' WHERE id=?",
                            (json.dumps(prediction), job['image_id']))
            self.db.execute("UPDATE jobs SET state='succeeded',elapsed=?,finished=?,error='' WHERE id=?",
                            (prediction['elapsed_seconds'], time.time(), job_id))
        self.settle(job['batch_id'])

    def fail(self, job_id, error, elapsed):
        job = self.get(job_id)
        with self.db:
            self.db.execute("UPDATE jobs SET state='failed',error=?,elapsed=?,finished=? WHERE id=? AND state='running'",
                            (error, elapsed, time.time(), job_id))
            self.db.execute("UPDATE images SET error=? WHERE id=?", (error, job['image_id']))
        self.settle(job['batch_id'])

    def settle(self, batch_id):
        with self.db:
            self.db.execute("""UPDATE batches SET state='complete' WHERE id=? AND state='running'
                AND NOT EXISTS (SELECT 1 FROM jobs WHERE batch_id=? AND state IN ('queued','running'))""",
                (batch_id, batch_id))

    def pause(self, batch_id):
        with self.db:
            self.db.execute("UPDATE batches SET state='paused' WHERE id=? AND state='running'", (batch_id,))

    def resume(self, batch_id):
        with self.db:
            self.db.execute("UPDATE batches SET state='running' WHERE id=? AND state='paused'", (batch_id,))

    def stop(self, batch_id):
        with self.db:
            self.db.execute("UPDATE batches SET state='stopped' WHERE id=?", (batch_id,))
            self.db.execute("UPDATE jobs SET state='canceled',finished=? WHERE batch_id=? AND state='queued'",
                            (time.time(), batch_id))

    def remove(self, job_id):
        """Only waiting work can be removed; never interrupt an in-flight result."""
        job = self.get(job_id)
        if not job:
            return False
        with self.db:
            changed = self.db.execute("UPDATE jobs SET state='canceled',finished=? WHERE id=? AND state='queued'",
                                      (time.time(), job_id)).rowcount
        self.settle(job['batch_id'])
        return bool(changed)

    def image_state(self, image_id):
        row = self.db.execute('SELECT state FROM jobs WHERE image_id=? ORDER BY id DESC LIMIT 1', (image_id,)).fetchone()
        return row['state'] if row else ''

    def entries(self, offset=0, limit=50):
        # Waiting/running first, newest history last; bounded for large catalogs.
        return [dict(row) for row in self.db.execute("""SELECT jobs.id, jobs.image_id,
            jobs.state, jobs.error, images.path,
            (jobs.state='failed' AND NOT EXISTS (SELECT 1 FROM jobs newer
                WHERE newer.image_id=jobs.image_id AND newer.id>jobs.id)) AS retryable
            FROM jobs JOIN images ON images.id=jobs.image_id
            ORDER BY CASE jobs.state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                CASE WHEN jobs.state IN ('running','queued') THEN jobs.id ELSE -jobs.id END
            LIMIT ? OFFSET ?""", (limit, offset))]

    def entry_count(self):
        return self.db.execute('SELECT count(*) FROM jobs').fetchone()[0]

    def failed_ids(self, batch_id):
        return [row['image_id'] for row in self.db.execute("""SELECT image_id FROM jobs j
            WHERE batch_id=? AND state='failed' AND NOT EXISTS
                (SELECT 1 FROM jobs newer WHERE newer.image_id=j.image_id AND newer.id>j.id)
            ORDER BY id""", (batch_id,))]

    def summary(self, batch_id):
        batch = self.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            return {}
        counts = {key: 0 for key in ('queued','running','succeeded','failed','canceled')}
        counts.update({r['state']: r['n'] for r in self.db.execute(
            "SELECT state,count(*) n FROM jobs WHERE batch_id=? GROUP BY state", (batch_id,))})
        finished = counts['succeeded'] + counts['failed']
        durations = [r['elapsed'] for r in self.db.execute("""SELECT elapsed FROM jobs
            WHERE batch_id=? AND state='succeeded' AND elapsed IS NOT NULL ORDER BY id DESC LIMIT 10""", (batch_id,))]
        eta = round(sum(durations) / len(durations) * (counts['queued'] + counts['running'])) if len(durations) >= 3 else -1
        failures = [dict(row) for row in self.db.execute("""SELECT images.path,jobs.error
            FROM jobs JOIN images ON images.id=jobs.image_id
            WHERE batch_id=? AND jobs.state='failed' ORDER BY jobs.id LIMIT 10""", (batch_id,))]
        current = self.db.execute("""SELECT images.path FROM jobs JOIN images ON images.id=jobs.image_id
            WHERE batch_id=? AND jobs.state='running' LIMIT 1""", (batch_id,)).fetchone()
        return {**counts, 'currentName': Path(current['path']).name if current else '',
                'id': batch_id, 'state': batch['state'], 'total': sum(counts.values()),
                'finished': finished, 'terminal': finished + counts['canceled'], 'eta': eta, 'errors': failures}
