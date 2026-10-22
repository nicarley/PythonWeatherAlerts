"""Durable, conservative delivery of alert notifications, independent of Qt.

Each destination is a separate job.  A job is never automatically resent after
an outcome that could mean the remote service already accepted the message.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlsplit


STATES = frozenset({"queued", "sending", "sent", "failed", "uncertain", "expired", "cancelled"})


class DeliveryQueueFull(RuntimeError):
    """The configured bound on pending delivery work was reached."""


@dataclass(frozen=True)
class DeliveryRecord:
    id: str
    alert_id: str
    revision: str
    location_id: str
    channel: str
    destination: str
    payload: dict[str, Any]
    state: str
    attempts: int
    created_at: float
    updated_at: float
    next_attempt_at: Optional[float]
    retryable: bool
    error: str
    expires_at: Optional[float] = None


@dataclass(frozen=True)
class DeliveryOutcome:
    state: str
    error: str = ""
    retryable: bool = False
    retry_after: Optional[float] = None

    def __post_init__(self) -> None:
        if self.state not in {"sent", "failed", "uncertain"}:
            raise ValueError("A delivery outcome must be sent, failed, or uncertain")
        if self.retryable and self.state != "failed":
            raise ValueError("Only a definite failed delivery may be retryable")
        if self.retry_after is not None and (
            not math.isfinite(self.retry_after) or self.retry_after < 0
        ):
            raise ValueError("retry_after must be a finite nonnegative delay")

    @classmethod
    def sent(cls) -> "DeliveryOutcome":
        return cls("sent")

    @classmethod
    def failed(
        cls, error: str, *, retryable: bool = False, retry_after: Optional[float] = None
    ) -> "DeliveryOutcome":
        return cls("failed", error, retryable, retry_after)

    @classmethod
    def uncertain(cls, error: str) -> "DeliveryOutcome":
        return cls("uncertain", error)


class JsonWebhookSender:
    """Post once with no HTTP retries or redirects and classify the outcome.

    A connect timeout is safe to retry; a read timeout, a dropped connection,
    or a server error can occur after acceptance and is therefore uncertain.
    HTTP 429 explicitly rejects the attempt and can be retried with backoff.
    Other HTTP rejections require configuration/operator attention.
    """

    def __init__(self, *, timeout_s: float = 8.0, session_factory=None) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be positive and finite")
        self.timeout_s = timeout_s
        self.session_factory = session_factory

    def __call__(self, record: DeliveryRecord) -> DeliveryOutcome:
        import requests

        session = self.session_factory() if self.session_factory else requests.Session()
        try:
            response = session.post(
                record.destination,
                json=record.payload,
                timeout=self.timeout_s,
                allow_redirects=False,
            )
            status = response.status_code
            if 200 <= status < 300:
                return DeliveryOutcome.sent()
            if status == 429:
                delay = None
                try:
                    parsed = float(response.headers.get("Retry-After", ""))
                    if math.isfinite(parsed) and parsed >= 0:
                        delay = min(parsed, 86400.0)
                except (ValueError, TypeError):
                    pass
                return DeliveryOutcome.failed(
                    "Remote service rate limited the request (HTTP 429).",
                    retryable=True,
                    retry_after=delay,
                )
            if status >= 500 or status == 408:
                return DeliveryOutcome.uncertain(
                    f"Remote service returned HTTP {status}; acceptance is unknown."
                )
            return DeliveryOutcome.failed(f"Remote service rejected the request (HTTP {status}).")
        except requests.ConnectTimeout:
            return DeliveryOutcome.failed("Connection timed out before sending.", retryable=True)
        except requests.RequestException as exc:
            # Do not persist exception URLs: webhook URLs can contain credentials.
            return DeliveryOutcome.uncertain(
                f"{type(exc).__name__}; remote acceptance could not be confirmed."
            )
        finally:
            session.close()


class DeliveryService:
    """A persistent outbox with one bounded delivery worker.

    Call ``start`` after configuring the application's enabled channels.
    ``on_result`` runs on the worker thread; GUI callers must bridge it through
    their GUI framework's signal mechanism.  Queue methods are thread safe.
    Sender callbacks must perform one attempt with a bounded network timeout.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        sender: Optional[Callable[[DeliveryRecord], DeliveryOutcome]] = None,
        on_result: Optional[Callable[[DeliveryRecord], None]] = None,
        max_attempts: int = 3,
        retry_delays: Iterable[float] = (5.0, 30.0),
        max_pending: int = 1000,
        clock: Callable[[], float] = time.time,
        destination_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        if max_attempts < 1 or max_pending < 1:
            raise ValueError("max_attempts and max_pending must be positive")
        delays = tuple(float(delay) for delay in retry_delays)
        if not delays or any(not math.isfinite(delay) or delay < 0 for delay in delays):
            raise ValueError("retry_delays must contain finite nonnegative delays")
        self.max_attempts = max_attempts
        self.max_pending = max_pending
        self.retry_delays = delays
        self._sender = sender or JsonWebhookSender()
        self._on_result = on_result
        self._clock = clock
        self._destination_resolver = destination_resolver
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._closed = False
        self._enabled_channels: Optional[frozenset[str]] = None
        self._enabled_locations: Optional[frozenset[str]] = None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        with self._db:
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    location_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('queued','sending','sent','failed','uncertain','expired','cancelled')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    next_attempt_at REAL,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    expires_at REAL,
                    UNIQUE(alert_id, revision, location_id, channel)
                )"""
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS delivery_due ON deliveries(state, next_attempt_at)"
            )
            # A process can stop after remote acceptance but before persisting sent.
            # Preserve this ambiguity rather than delivering the same alert again.
            self._db.execute(
                "UPDATE deliveries SET state='uncertain', retryable=0, next_attempt_at=NULL, "
                "updated_at=?, error='Application stopped during delivery; remote acceptance is unknown.' "
                "WHERE state='sending'",
                (self._clock(),),
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> DeliveryRecord:
        values = dict(row)
        values["payload"] = json.loads(values["payload"])
        values["retryable"] = bool(values["retryable"])
        return DeliveryRecord(**values)

    def _ensure_open(self) -> None:
        if self._closed or self._stop.is_set():
            raise RuntimeError("Delivery service has been shut down")

    def enqueue(
        self,
        *,
        alert_id: str,
        revision: str,
        location_id: str,
        channel: str,
        destination: str,
        payload: dict[str, Any],
        expires_at: Optional[float] = None,
    ) -> DeliveryRecord:
        key = tuple(str(value).strip() for value in (alert_id, revision, location_id, channel))
        if not all(key):
            raise ValueError("alert_id, revision, location_id, and channel are required")
        parsed_url = urlsplit(destination)
        credential_reference = destination.startswith("credential:") and self._destination_resolver is not None
        if not credential_reference and (parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname):
            raise ValueError("A valid HTTP(S) notification destination is required")
        if expires_at is not None and not math.isfinite(expires_at):
            raise ValueError("expires_at must be a finite timestamp")
        if not isinstance(payload, dict):
            raise TypeError("Notification payload must be a dictionary")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        now = self._clock()
        with self._lock:
            self._ensure_open()
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                existing = self._db.execute(
                    "SELECT * FROM deliveries WHERE alert_id=? AND revision=? AND location_id=? AND channel=?",
                    key,
                ).fetchone()
                if existing:
                    return self._record(existing)
                # A newer revision replaces only unsent work, preserving durable
                # deduplication keys and all confirmed/ambiguous delivery outcomes.
                self._db.execute(
                    "UPDATE deliveries SET state='cancelled',retryable=0,next_attempt_at=NULL,updated_at=?,"
                    "error='Superseded by a newer alert revision.' WHERE alert_id=? AND location_id=? "
                    "AND channel=? AND revision<>? AND state IN ('queued','failed')",
                    (now, key[0], key[2], key[3], key[1]),
                )
                pending = self._db.execute(
                    "SELECT COUNT(*) FROM deliveries WHERE state IN ('queued','sending') "
                    "OR (state='failed' AND retryable=1 AND next_attempt_at IS NOT NULL)"
                ).fetchone()[0]
                if pending >= self.max_pending:
                    raise DeliveryQueueFull("Notification delivery queue is full")
                delivery_id = uuid.uuid4().hex
                state = "expired" if expires_at is not None and expires_at <= now else "queued"
                self._db.execute(
                    "INSERT INTO deliveries (id,alert_id,revision,location_id,channel,destination,payload,"
                    "state,created_at,updated_at,next_attempt_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (delivery_id, *key, destination, encoded, state, now, now, now if state == "queued" else None, expires_at),
                )
                row = self._db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            self._wake.set()
            return self._record(row)

    def records(self, states: Optional[Iterable[str]] = None) -> list[DeliveryRecord]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Delivery service has been closed")
            if states is None:
                rows = self._db.execute("SELECT * FROM deliveries ORDER BY created_at,id").fetchall()
            else:
                selected = tuple(states)
                if not selected:
                    return []
                if any(state not in STATES for state in selected):
                    raise ValueError("Unknown delivery state")
                marks = ",".join("?" for _ in selected)
                rows = self._db.execute(
                    f"SELECT * FROM deliveries WHERE state IN ({marks}) ORDER BY created_at,id", selected
                ).fetchall()
            return [self._record(row) for row in rows]

    def get(self, delivery_id: str) -> Optional[DeliveryRecord]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Delivery service has been closed")
            row = self._db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            return self._record(row) if row else None

    def set_enabled_channels(self, channels: Optional[Iterable[str]]) -> None:
        """Pause disabled channels without losing their queued work; None enables all."""
        with self._lock:
            self._ensure_open()
            self._enabled_channels = None if channels is None else frozenset(channels)
        self._wake.set()

    def set_enabled_locations(self, location_ids: Optional[Iterable[str]]) -> None:
        """Gate alert recovery on a fresh successful check for each location.

        None enables all locations. An empty set pauses alert jobs; explicitly
        requested test: jobs remain eligible, subject to channel enablement.
        An in-flight request cannot be recalled by changing this gate.
        """
        with self._lock:
            self._ensure_open()
            self._enabled_locations = None if location_ids is None else frozenset(str(value) for value in location_ids)
        self._wake.set()

    def retry_failed(self, delivery_id: str) -> bool:
        """Explicitly retry a definite failure within budget; never retry uncertainty.

        This also permits a manual retry after correcting credentials or an HTTP
        rejection; those failures do not automatically retry on their own.
        """
        with self._lock:
            self._ensure_open()
            with self._db:
                changed = self._db.execute(
                    "UPDATE deliveries SET next_attempt_at=?,updated_at=?,retryable=1 WHERE id=? AND state='failed' "
                    "AND attempts<?",
                    (self._clock(), self._clock(), delivery_id, self.max_attempts),
                ).rowcount
        self._wake.set()
        return bool(changed)

    def cancel_alert(self, location_id: str, alert_id: str) -> int:
        """Cancel unsent jobs for a cleared alert; an in-flight post cannot be undone."""
        with self._lock:
            self._ensure_open()
            with self._db:
                changed = self._db.execute(
                    "UPDATE deliveries SET state='cancelled',retryable=0,next_attempt_at=NULL,updated_at=?,"
                    "error='Alert is no longer active.' WHERE location_id=? AND alert_id=? "
                    "AND state IN ('queued','failed')",
                    (self._clock(), str(location_id), str(alert_id)),
                ).rowcount
        self._wake.set()
        return changed

    def _claim_next(self) -> Optional[DeliveryRecord]:
        with self._lock:
            if self._stop.is_set():
                return None
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "UPDATE deliveries SET state='expired',retryable=0,next_attempt_at=NULL,updated_at=?,"
                    "error='Alert expired before delivery.' WHERE expires_at<=? AND state IN ('queued','failed')",
                    (self._clock(), self._clock()),
                )
                channels = self._enabled_channels
                if channels is not None and not channels:
                    return None
                clause = ""
                params: list[Any] = [self._clock(), self.max_attempts]
                if channels is not None:
                    clause = " AND channel IN (" + ",".join("?" for _ in channels) + ")"
                    params.extend(sorted(channels))
                locations = self._enabled_locations
                if locations is not None:
                    if locations:
                        clause += " AND (location_id IN (" + ",".join("?" for _ in locations) + ") OR alert_id LIKE 'test:%')"
                        params.extend(sorted(locations))
                    else:
                        clause += " AND alert_id LIKE 'test:%'"
                row = self._db.execute(
                    "SELECT * FROM deliveries WHERE next_attempt_at<=? AND attempts<? "
                    "AND (state='queued' OR (state='failed' AND retryable=1))" + clause +
                    " ORDER BY next_attempt_at,created_at,id LIMIT 1", params,
                ).fetchone()
                if row is None:
                    return None
                self._db.execute(
                    "UPDATE deliveries SET state='sending',attempts=attempts+1,updated_at=?,"
                    "next_attempt_at=NULL WHERE id=?", (self._clock(), row["id"]),
                )
                return self._record(self._db.execute("SELECT * FROM deliveries WHERE id=?", (row["id"],)).fetchone())

    def _complete(self, record: DeliveryRecord, outcome: DeliveryOutcome) -> DeliveryRecord:
        now = self._clock()
        due = None
        if outcome.retryable and record.attempts < self.max_attempts:
            backoff = self.retry_delays[min(record.attempts - 1, len(self.retry_delays) - 1)]
            due = now + max(backoff, outcome.retry_after or 0.0)
        with self._lock:
            with self._db:
                self._db.execute(
                    "UPDATE deliveries SET state=?,error=?,retryable=?,updated_at=?,next_attempt_at=? "
                    "WHERE id=? AND state='sending' AND attempts=?",
                    (outcome.state, outcome.error[:1000], int(outcome.retryable), now, due, record.id, record.attempts),
                )
                return self._record(self._db.execute("SELECT * FROM deliveries WHERE id=?", (record.id,)).fetchone())

    def process_next(self) -> Optional[DeliveryRecord]:
        """Perform one due job. Useful for deterministic schedulers and tests.

        Do not call from the UI thread: use ``start`` in an interactive app.
        """
        record = self._claim_next()
        if record is None:
            return None
        try:
            send_record = record
            if self._destination_resolver:
                try:
                    destination = self._destination_resolver(record.destination)
                    parsed_url = urlsplit(destination or "")
                    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
                        raise ValueError("Destination unavailable")
                    send_record = replace(record, destination=destination)
                except Exception as exc:
                    outcome = DeliveryOutcome.failed(
                        f"Destination credentials unavailable ({type(exc).__name__})."
                    )
                else:
                    outcome = self._sender(send_record)
            else:
                outcome = self._sender(send_record)
            if not isinstance(outcome, DeliveryOutcome):
                raise TypeError("Sender must return DeliveryOutcome")
        except Exception as exc:
            outcome = DeliveryOutcome.uncertain(
                f"Delivery interrupted by {type(exc).__name__}; remote acceptance is unknown."
            )
        result = self._complete(record, outcome)
        if self._on_result:
            try:
                self._on_result(result)
            except Exception:
                # GUI/reporting failures must never turn a delivered message into a retry.
                pass
        return result

    def start(self) -> None:
        with self._lock:
            self._ensure_open()
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="weather-delivery", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._wake.clear()
                try:
                    result = self.process_next()
                except sqlite3.Error:
                    # A durable write failed. Stop rather than risk sending more work
                    # whose outcomes cannot be committed. Restart recovers sending.
                    self._stop.set()
                    break
                if result is None:
                    self._wake.wait(0.5)
        finally:
            if self._stop.is_set():
                self._close_database()

    def _close_database(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def shutdown(self, *, wait: bool = True, timeout: Optional[float] = 10.0) -> bool:
        """Stop claiming work, keep pending jobs, and finish the current bounded attempt.

        Returns whether the worker stopped. ``wait=False`` never blocks the GUI.
        A process exit during an attempt is recovered as uncertain on next open.
        """
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            if wait and thread is not threading.current_thread():
                thread.join(timeout)
            return not thread.is_alive()
        self._close_database()
        return True
