"""One managed speech worker; the engine never crosses thread boundaries."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class SpeechResult:
    text: str
    key: Optional[str]
    success: bool
    error: str = ""
    cancelled: bool = False


@dataclass(frozen=True)
class _SpeechJob:
    text: str
    key: Optional[str]
    rate: Optional[int]


def _default_factory():
    import pyttsx3

    return pyttsx3.init()


class SpeechQueue:
    """Serialize speech on the thread that creates the engine.

    The engine factory and result callback both run on the worker thread.
    UI integrations must forward results through their framework's signals.
    submit returns False for duplicates still pending, a full queue, empty
    text, or a stopped queue. No real engine is initialized until first use.
    """

    def __init__(
        self,
        factory: Optional[Callable] = None,
        *,
        on_result: Optional[Callable[[SpeechResult], None]] = None,
        max_queue: int = 100,
        default_rate: int = 150,
    ) -> None:
        if max_queue < 1 or default_rate < 1:
            raise ValueError("max_queue and default_rate must be positive")
        self._factory = factory or _default_factory
        self._on_result = on_result
        self._default_rate = default_rate
        self._jobs: queue.Queue[_SpeechJob] = queue.Queue(maxsize=max_queue)
        self._lock = threading.Lock()
        self._pending_keys: set[str] = set()
        self._pending_count = 0
        self._cancelled: list[_SpeechJob] = []
        self._accepting = True
        self._stop = threading.Event()
        self._drain = False
        self._thread = threading.Thread(target=self._run, name="weather-speech", daemon=True)
        self._thread.start()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._pending_count

    def submit(self, text: str, key: Optional[str] = None, rate: Optional[int] = None) -> bool:
        text = str(text).strip()
        if not text:
            return False
        if rate is not None and (isinstance(rate, bool) or not isinstance(rate, int) or rate < 1):
            raise ValueError("rate must be a positive integer")
        with self._lock:
            if not self._accepting or (key is not None and key in self._pending_keys):
                return False
            job = _SpeechJob(text, key, rate)
            try:
                self._jobs.put_nowait(job)
            except queue.Full:
                return False
            if key is not None:
                self._pending_keys.add(key)
            self._pending_count += 1
            return True

    def clear(self) -> int:
        """Drop queued speech, keeping an in-flight engine on its owning thread."""
        removed = 0
        with self._lock:
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                if job.key is not None:
                    self._pending_keys.discard(job.key)
                self._pending_count -= 1
                self._cancelled.append(job)
                self._jobs.task_done()
                removed += 1
        return removed

    def _flush_cancelled(self) -> None:
        with self._lock:
            cancelled, self._cancelled = self._cancelled, []
        if self._on_result:
            for job in cancelled:
                try:
                    self._on_result(SpeechResult(job.text, job.key, False, "Queued speech cleared.", cancelled=True))
                except Exception:
                    pass

    def _report(self, job: _SpeechJob, success: bool, error: str = "", *, cancelled: bool = False) -> None:
        with self._lock:
            if job.key is not None:
                self._pending_keys.discard(job.key)
            self._pending_count -= 1
        if self._on_result:
            try:
                self._on_result(SpeechResult(job.text, job.key, success, error, cancelled=cancelled))
            except Exception:
                # Reporting must not repeat speech that may already have played.
                pass

    @staticmethod
    def _stop_engine(engine) -> None:
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

    def _run(self) -> None:
        engine = None
        try:
            while True:
                self._flush_cancelled()
                if self._stop.is_set() and (not self._drain or self._jobs.empty()):
                    break
                try:
                    job = self._jobs.get(timeout=0.1)
                except queue.Empty:
                    continue
                if self._stop.is_set() and not self._drain:
                    self._report(job, False, "Speech cancelled during shutdown.", cancelled=True)
                    self._jobs.task_done()
                    break
                try:
                    if engine is None:
                        engine = self._factory()
                    engine.setProperty("rate", job.rate if job.rate is not None else self._default_rate)
                    engine.say(job.text)
                    engine.runAndWait()
                except Exception as exc:
                    # A failed engine is discarded on its owning thread. Never
                    # replay an utterance that might have partially played.
                    self._report(job, False, f"Speech failed ({type(exc).__name__}).")
                    self._stop_engine(engine)
                    engine = None
                else:
                    self._report(job, True)
                finally:
                    self._jobs.task_done()
        finally:
            self._stop_engine(engine)
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                self._report(job, False, "Speech cancelled during shutdown.", cancelled=True)
                self._jobs.task_done()

            self._flush_cancelled()

    def shutdown(
        self, *, wait: bool = True, timeout: Optional[float] = 5.0, drain: bool = False
    ) -> bool:
        """Stop accepting jobs, finish current speech, and optionally drain pending work.

        wait=False returns immediately. The engine is always stopped and
        released by its own thread. A platform engine that hangs can therefore
        never force the caller's UI thread to wait during shutdown.
        """
        with self._lock:
            self._accepting = False
            self._drain = drain
            self._stop.set()
        if wait and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread.is_alive()
