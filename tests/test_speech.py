"""Fake-engine tests: no installed speech engine or speakers are used."""

import threading

import pytest

from weather_alert.speech import SpeechQueue


class FakeEngine:
    def __init__(self, operations, *, entered=None, release=None, fail=False):
        self.operations = operations
        self.entered = entered
        self.release = release
        self.fail = fail
        self.operations.append(("create", threading.get_ident()))

    def setProperty(self, name, value):
        self.operations.append(("property", threading.get_ident(), name, value))

    def say(self, text):
        self.operations.append(("say", threading.get_ident(), text))

    def runAndWait(self):
        self.operations.append(("run", threading.get_ident()))
        if self.entered:
            self.entered.set()
        if self.release:
            assert self.release.wait(3)
        if self.fail:
            raise RuntimeError("fake engine failure")

    def stop(self):
        self.operations.append(("stop", threading.get_ident()))


def test_engine_lifecycle_stays_on_single_worker_thread_and_preserves_fifo():
    operations = []
    results = []
    queue = SpeechQueue(factory=lambda: FakeEngine(operations), on_result=results.append)
    assert queue.submit("First", key="first", rate=185)
    assert queue.submit("Second", key="second")
    assert queue.shutdown(drain=True, timeout=3)

    assert [op[2] for op in operations if op[0] == "say"] == ["First", "Second"]
    assert [op[3] for op in operations if op[0] == "property"] == [185, 150]
    owners = {op[1] for op in operations}
    assert len(owners) == 1
    assert threading.get_ident() not in owners
    assert [result.key for result in results] == ["first", "second"]
    assert all(result.success for result in results)
    assert queue.pending_count == 0
    assert not queue.submit("After shutdown")


def test_bounded_queue_rejects_pending_duplicates_and_full_queue():
    entered = threading.Event()
    release = threading.Event()
    operations = []
    queue = SpeechQueue(
        factory=lambda: FakeEngine(operations, entered=entered, release=release),
        max_queue=1,
    )
    try:
        assert queue.submit("First", key="same")
        assert entered.wait(3)
        assert not queue.submit("Duplicate active", key="same")
        assert queue.submit("Second", key="second")
        assert not queue.submit("Full", key="third")
        assert queue.pending_count == 2
    finally:
        release.set()
        assert queue.shutdown(drain=True, timeout=3)


def test_nonblocking_shutdown_cancels_pending_without_cross_thread_stop():
    entered = threading.Event()
    release = threading.Event()
    operations = []
    results = []
    queue = SpeechQueue(
        factory=lambda: FakeEngine(operations, entered=entered, release=release),
        on_result=results.append,
    )
    assert queue.submit("Active", key="active")
    assert entered.wait(3)
    assert queue.submit("Pending", key="pending")
    assert queue.shutdown(wait=False) is False
    assert not any(op[0] == "stop" for op in operations)
    assert not queue.submit("Too late")
    release.set()
    assert queue.shutdown(timeout=3)
    assert [op[2] for op in operations if op[0] == "say"] == ["Active"]
    assert [(result.key, result.success) for result in results] == [("active", True), ("pending", False)]
    assert queue.pending_count == 0


def test_engine_failure_reports_once_and_recovers_for_next_job():
    operations = []
    results = []
    factories = []

    def factory():
        factories.append(True)
        return FakeEngine(operations, fail=len(factories) == 1)

    queue = SpeechQueue(factory=factory, on_result=results.append)
    queue.submit("Fails", key="failed")
    queue.submit("Works", key="next")
    assert queue.shutdown(drain=True, timeout=3)
    assert [result.success for result in results] == [False, True]
    assert len(factories) == 2
    assert [op[2] for op in operations if op[0] == "say"] == ["Fails", "Works"]


def test_factory_failure_and_callback_failure_do_not_hang_queue():
    attempts = []
    results = []

    def factory():
        attempts.append(True)
        raise RuntimeError("not installed")

    def callback(result):
        results.append(result)
        raise RuntimeError("GUI reporting failure")

    queue = SpeechQueue(factory=factory, on_result=callback)
    queue.submit("One")
    queue.submit("Two")
    assert queue.shutdown(drain=True, timeout=3)
    assert len(results) == 2
    assert all(not result.success for result in results)
    assert queue.pending_count == 0


def test_no_engine_is_initialized_without_speech_and_invalid_rate_is_rejected():
    operations = []
    queue = SpeechQueue(factory=lambda: FakeEngine(operations))
    assert not queue.submit("  ")
    with pytest.raises(ValueError):
        queue.submit("Bad rate", rate=0)
    assert queue.shutdown(timeout=3)
    assert operations == []


def test_clear_drops_pending_jobs_and_keeps_engine_owned_by_worker():
    entered = threading.Event()
    release = threading.Event()
    operations = []
    callback_threads = []
    results = []

    def callback(result):
        callback_threads.append(threading.get_ident())
        results.append(result)

    queue = SpeechQueue(
        factory=lambda: FakeEngine(operations, entered=entered, release=release),
        on_result=callback,
    )
    queue.submit("Active", key="active")
    assert entered.wait(3)
    queue.submit("Pending", key="pending")
    assert queue.clear() == 1
    assert queue.pending_count == 1
    assert not any(op[0] == "stop" for op in operations)
    release.set()
    assert queue.shutdown(drain=True, timeout=3)
    assert [op[2] for op in operations if op[0] == "say"] == ["Active"]
    assert sorted((result.key, result.success) for result in results) == [("active", True), ("pending", False)]
    assert threading.get_ident() not in callback_threads
    assert next(result for result in results if result.key == "pending").cancelled is True
