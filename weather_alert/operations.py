"""Local operational records. An acknowledgment never dismisses an NWS alert."""
import json
from contextlib import contextmanager
import sqlite3
import time
from pathlib import Path


class OperationsStore:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS acknowledgments (
                    location_id TEXT NOT NULL, alert_id TEXT NOT NULL, revision TEXT NOT NULL,
                    acknowledged_at REAL NOT NULL, operator TEXT NOT NULL, note TEXT NOT NULL,
                    PRIMARY KEY(location_id, alert_id, revision));
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY, recorded_at REAL NOT NULL, kind TEXT NOT NULL,
                    location_id TEXT NOT NULL, value REAL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (
                    location_id TEXT PRIMARY KEY, saved_at REAL NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS local_effects (
                    location_id TEXT NOT NULL, alert_id TEXT NOT NULL, revision TEXT NOT NULL,
                    effect TEXT NOT NULL, claimed_at REAL NOT NULL,
                    PRIMARY KEY(location_id, alert_id, revision, effect));
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def acknowledge(self, location_id, alert_id, revision, operator="Local operator", note=""):
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO acknowledgments VALUES (?,?,?,?,?,?)",
                       (location_id, alert_id, revision, time.time(), operator.strip() or "Local operator", note.strip()))

    def acknowledgment(self, location_id, alert_id, revision):
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM acknowledgments WHERE location_id=? AND alert_id=? AND revision=?",
                             (location_id, alert_id, revision)).fetchone()
        return dict(row) if row else None

    def acknowledgments(self, location_id=None):
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            if location_id:
                rows = db.execute("SELECT * FROM acknowledgments WHERE location_id=? ORDER BY acknowledged_at DESC", (location_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM acknowledgments ORDER BY acknowledged_at DESC").fetchall()
        return [dict(row) for row in rows]

    def record(self, kind, location_id="", value=None, detail=""):
        with self._connect() as db:
            db.execute("INSERT INTO metrics(recorded_at,kind,location_id,value,detail) VALUES (?,?,?,?,?)",
                       (time.time(), kind, location_id, value, detail))
            db.execute("DELETE FROM metrics WHERE id NOT IN (SELECT id FROM metrics ORDER BY id DESC LIMIT 10000)")

    def metrics(self):
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT kind, COUNT(*) AS count, AVG(value) AS average, MAX(value) AS maximum FROM metrics GROUP BY kind").fetchall()
        return [dict(row) for row in rows]

    def save_snapshot(self, location_id, payload):
        serialized = json.dumps(payload, allow_nan=False)
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)", (location_id, time.time(), serialized))

    def load_snapshots(self):
        with self._connect() as db:
            rows = db.execute("SELECT location_id,payload FROM snapshots").fetchall()
        result = {}
        for location_id, payload in rows:
            try:
                value = json.loads(payload)
                if isinstance(value, dict):
                    result[location_id] = value
            except (ValueError, TypeError):
                continue
        return result

    def claim_effect(self, location_id, alert_id, revision, effect):
        """Claim once before an irreversible local effect; seeing an alert is separate."""
        with self._connect() as db:
            return bool(db.execute("INSERT OR IGNORE INTO local_effects VALUES (?,?,?,?,?)",
                (location_id, alert_id, revision, effect, time.time())).rowcount)
