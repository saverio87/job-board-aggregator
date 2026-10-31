"""SQLite storage and reconciliation.

Two things this owns that no source will do for you:

* **Newness.** No source exposes a reliable "changed since" field. We record
  `first_seen` ourselves, which on one of these boards is the only way to know a
  job is new at all — its list data carries no date.

* **Removal.** `last_seen` stops advancing when a job disappears from the source.
  That is our delisting signal, and it is only trustworthy if we refuse to run it
  on a failed or truncated fetch.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id            INTEGER PRIMARY KEY,
  source        TEXT NOT NULL,
  src_job_id    TEXT NOT NULL,
  title         TEXT NOT NULL,
  employer      TEXT DEFAULT '',
  src_employer_id TEXT DEFAULT '',
  location_raw  TEXT DEFAULT '',
  location_country TEXT DEFAULT '',
  location_city TEXT DEFAULT '',
  salary_raw    TEXT DEFAULT '',
  posted_at     TEXT DEFAULT '',
  url           TEXT DEFAULT '',
  apply_url     TEXT DEFAULT '',
  description_html TEXT DEFAULT '',
  tags_subject  TEXT DEFAULT '',
  tags_role     TEXT DEFAULT '',
  dedupe_key    TEXT DEFAULT '',
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  is_active     INTEGER DEFAULT 1,
  raw_json      TEXT DEFAULT '',
  UNIQUE(source, src_job_id)
);
CREATE INDEX IF NOT EXISTS idx_dedupe ON jobs(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_active ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_source ON jobs(source);

CREATE TABLE IF NOT EXISTS runs (
  id          INTEGER PRIMARY KEY,
  source      TEXT NOT NULL,
  ran_at      TEXT NOT NULL,
  status      TEXT NOT NULL,
  requests    INTEGER DEFAULT 0,
  bytes       INTEGER DEFAULT 0,
  collected   INTEGER DEFAULT 0,
  reported    INTEGER DEFAULT 0,
  notes       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_source ON runs(source, ran_at);
"""


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path=None):
        self.path = path or config.DB_PATH
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    # ── ingest ────────────────────────────────────────────────────────────────
    def upsert(self, jobs):
        """Insert new jobs, refresh ones we have seen before. Returns (new, updated)."""
        ts = now_iso()
        new = updated = 0
        for j in jobs:
            row = self.db.execute(
                "SELECT id FROM jobs WHERE source=? AND src_job_id=?",
                (j.source, j.src_job_id),
            ).fetchone()
            key = j.dedupe_key()
            if row:
                self.db.execute(
                    """UPDATE jobs SET title=?, employer=?, location_raw=?,
                       location_country=?, location_city=?, salary_raw=?, posted_at=?,
                       url=?, apply_url=?, description_html=?, tags_subject=?,
                       tags_role=?, dedupe_key=?, last_seen=?, is_active=1, raw_json=?
                       WHERE id=?""",
                    (j.title, j.employer, j.location_raw, j.location_country,
                     j.location_city, j.salary_raw, j.posted_at, j.url, j.apply_url,
                     j.description_html, ",".join(j.tags_subject),
                     ",".join(j.tags_role), key, ts, j.raw_json, row["id"]),
                )
                updated += 1
            else:
                self.db.execute(
                    """INSERT INTO jobs (source, src_job_id, title, employer,
                       src_employer_id, location_raw, location_country, location_city,
                       salary_raw, posted_at, url, apply_url, description_html,
                       tags_subject, tags_role, dedupe_key, first_seen, last_seen,
                       is_active, raw_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                    (j.source, j.src_job_id, j.title, j.employer, j.src_employer_id,
                     j.location_raw, j.location_country, j.location_city,
                     j.salary_raw, j.posted_at, j.url, j.apply_url,
                     j.description_html, ",".join(j.tags_subject),
                     ",".join(j.tags_role), key, ts, ts, j.raw_json),
                )
                new += 1
        self.db.commit()
        return new, updated

    def retire_missing(self, source, seen_ids):
        """Mark jobs that were not in this run's results as inactive.

        Only safe on a clean run. Called from the runner only when the source
        returned status 'ok' — a truncated fetch would otherwise retire everything
        past page one, and on teast.co that is 26 of 32 jobs.
        """
        ts = now_iso()
        seen = set(seen_ids)
        rows = self.db.execute(
            "SELECT src_job_id FROM jobs WHERE source=? AND is_active=1", (source,)
        ).fetchall()
        gone = [r["src_job_id"] for r in rows if r["src_job_id"] not in seen]
        for jid in gone:
            self.db.execute(
                "UPDATE jobs SET is_active=0 WHERE source=? AND src_job_id=?",
                (source, jid),
            )
        self.db.commit()
        return len(gone)

    def record_run(self, res):
        self.db.execute(
            """INSERT INTO runs (source, ran_at, status, requests, bytes, collected,
               reported, notes) VALUES (?,?,?,?,?,?,?,?)""",
            (res.source, now_iso(), res.status, res.requests, res.bytes,
             res.collected, res.reported, " | ".join(res.notes)),
        )
        self.db.commit()

    # ── read ──────────────────────────────────────────────────────────────────
    def last_run(self, source):
        return self.db.execute(
            "SELECT * FROM runs WHERE source=? ORDER BY ran_at DESC LIMIT 1",
            (source,),
        ).fetchone()

    def last_success(self, source):
        """Most recent run that did not error.

        Cadence is measured against this, not against the last attempt. A failed
        run must not buy the source a day of silence before it is retried.
        """
        return self.db.execute(
            "SELECT * FROM runs WHERE source=? AND status!='error' "
            "ORDER BY ran_at DESC LIMIT 1",
            (source,),
        ).fetchone()

    def last_runs(self):
        return self.db.execute(
            """SELECT r.* FROM runs r
               JOIN (SELECT source, MAX(ran_at) m FROM runs GROUP BY source) x
                 ON r.source=x.source AND r.ran_at=x.m
               ORDER BY r.source"""
        ).fetchall()

    def jobs_for(self, subject_terms, role_terms, active_only=True):
        """Return stored jobs that match a dashboard's tag set.

        Matching happens at read time, not write time, so a new tag works over the
        whole history immediately. Adding "Mathematics" tomorrow should not require
        having scraped differently today.
        """
        from core.tags import classify

        sql = "SELECT * FROM jobs"
        if active_only:
            sql += " WHERE is_active=1"
        out = []
        for r in self.db.execute(sql).fetchall():
            j = dict(r)
            ok, subs, roles = classify(j["title"], subject_terms, role_terms)
            if ok:
                j["matched_subject"] = subs
                j["matched_role"] = roles
                out.append(j)
        out.sort(key=lambda j: (j.get("posted_at") or "", j.get("first_seen") or ""),
                 reverse=True)
        return out

    def counts(self):
        return {
            "total": self.db.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"],
            "active": self.db.execute(
                "SELECT COUNT(*) c FROM jobs WHERE is_active=1").fetchone()["c"],
        }
