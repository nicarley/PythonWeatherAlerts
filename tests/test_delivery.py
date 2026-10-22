"""Durable delivery tests use injected senders and never contact real endpoints."""

from collections import Counter
import threading

import pytest
import requests

from weather_alert.delivery import DeliveryOutcome, DeliveryQueueFull, DeliveryService, JsonWebhookSender
from weather_alert.webhook import format_notification_payload


@pytest.fixture
def services(tmp_path):
    opened = []

    def make(name="outbox.sqlite", **kwargs):
        kwargs.setdefault("sender", lambda record: DeliveryOutcome.sent())
        service = DeliveryService(tmp_path / name, **kwargs)
        opened.append(service)
        return service

    yield make
    for service in opened:
        service.shutdown()


def enqueue(service, **overrides):
    options = dict(
        alert_id="nws-alert-1",
        revision="2026-10-22T14:00:00Z",
        location_id="home",
        channel="generic",
        destination="https://example.invalid/webhook",
        payload={"title": "Test warning"},
    )
    options.update(overrides)
    return service.enqueue(**options)


def test_enqueue_is_idempotent_across_restart_and_separates_revision_location_channel(services):
    service = services()
    initial = enqueue(service)
    assert enqueue(service).id == initial.id
    enqueue(service, revision="next")
    enqueue(service, location_id="work")
    enqueue(service, channel="slack")
    assert len(service.records()) == 4
    service.shutdown()

    reopened = services()
    assert enqueue(reopened).id == initial.id
    assert len(reopened.records()) == 4


def test_payload_snapshot_is_independent_of_callers_mutable_data(services):
    payload = {"title": "Original", "nested": {"severity": "Severe"}}
    service = services()
    record = enqueue(service, payload=payload)
    payload["nested"]["severity"] = "Changed"
    record.payload["title"] = "Changed"
    stored = service.get(record.id)
    assert stored.payload == {"title": "Original", "nested": {"severity": "Severe"}}


def test_restart_recovers_interrupted_send_as_uncertain_without_blind_resend(services):
    service = services()
    interrupted = enqueue(service)
    assert service._claim_next().id == interrupted.id
    queued = enqueue(service, alert_id="another-alert")
    service.shutdown()

    reopened = services()
    recovered = reopened.get(interrupted.id)
    assert recovered.state == "uncertain"
    assert recovered.attempts == 1
    assert not reopened.retry_failed(interrupted.id)
    assert reopened.process_next().id == queued.id
    assert reopened.process_next() is None


def test_definite_safe_failure_obeys_backoff_retry_after_and_attempt_budget(services):
    now = [1000.0]
    service = services(
        clock=lambda: now[0],
        sender=lambda record: DeliveryOutcome.failed("Rate limited", retryable=True, retry_after=20),
        retry_delays=(5, 30),
        max_attempts=3,
    )
    record = enqueue(service)
    first = service.process_next()
    assert (first.state, first.attempts, first.next_attempt_at) == ("failed", 1, 1020.0)
    assert service.process_next() is None
    now[0] = 1020.0
    second = service.process_next()
    assert second.next_attempt_at == 1050.0
    now[0] = 1050.0
    final = service.process_next()
    assert final.state == "failed"
    assert final.attempts == 3
    assert final.next_attempt_at is None
    assert not service.retry_failed(record.id)
    now[0] = 99999
    assert service.process_next() is None


def test_ambiguous_exception_is_terminal_and_does_not_persist_secret_exception_text(services):
    def fail(record):
        raise RuntimeError("secret-token-in-request-url")

    service = services(sender=fail)
    record = enqueue(service)
    result = service.process_next()
    assert result.state == "uncertain"
    assert "secret-token" not in result.error
    assert not service.retry_failed(record.id)
    assert service.process_next() is None
    service.shutdown()
    reopened = services()
    assert reopened.process_next() is None


def test_channel_success_is_not_repeated_when_another_channel_retries(services):
    now = [1000.0]
    attempts = Counter()

    def send(record):
        attempts[record.channel] += 1
        if record.channel == "generic" and attempts[record.channel] == 1:
            return DeliveryOutcome.failed("Connect timeout", retryable=True)
        return DeliveryOutcome.sent()

    service = services(sender=send, clock=lambda: now[0])
    enqueue(service)
    enqueue(service, channel="discord")
    service.process_next()
    service.process_next()
    assert attempts == {"generic": 1, "discord": 1}
    now[0] += 5
    service.process_next()
    assert attempts == {"generic": 2, "discord": 1}
    assert {record.state for record in service.records()} == {"sent"}


def test_restart_and_retry_do_not_send_expired_alerts(services):
    now = [1000.0]
    service = services(
        clock=lambda: now[0],
        sender=lambda record: DeliveryOutcome.failed("Connect timeout", retryable=True),
    )
    queued = enqueue(service, expires_at=1002)
    service.process_next()
    assert service.get(queued.id).state == "failed"
    service.shutdown()
    now[0] = 1005.0
    reopened = services(clock=lambda: now[0])
    assert reopened.process_next() is None
    assert reopened.get(queued.id).state == "expired"
    assert enqueue(reopened, alert_id="already-expired", expires_at=1000).state == "expired"


def test_cancelled_alert_cannot_be_delivered_or_retried(services):
    service = services()
    first = enqueue(service)
    second = enqueue(service, channel="slack")
    assert service.cancel_alert("home", "nws-alert-1") == 2
    assert service.process_next() is None
    assert service.get(first.id).state == "cancelled"
    assert service.get(second.id).state == "cancelled"
    assert not service.retry_failed(first.id)


def test_credentials_resolve_only_for_send_and_are_not_persisted(services, tmp_path):
    sent = []
    secret_url = "https://example.invalid/a-private-token"
    service = services(
        destination_resolver=lambda reference: secret_url,
        sender=lambda record: sent.append(record.destination) or DeliveryOutcome.sent(),
    )
    record = enqueue(service, destination="credential:generic")
    result = service.process_next()
    assert sent == [secret_url]
    assert result.destination == "credential:generic"
    assert service.get(record.id).destination == "credential:generic"
    service.shutdown()
    for path in tmp_path.glob("outbox.sqlite*"):
        assert b"a-private-token" not in path.read_bytes()


def test_missing_credentials_are_definite_failure_without_network_attempt(services):
    sent = []
    service = services(
        destination_resolver=lambda reference: None,
        sender=lambda record: sent.append(record) or DeliveryOutcome.sent(),
    )
    enqueue(service, destination="credential:generic")
    result = service.process_next()
    assert result.state == "failed"
    assert not result.retryable
    assert not sent


def test_queue_bound_does_not_prevent_idempotent_enqueue(services):
    service = services(max_pending=1)
    first = enqueue(service)
    assert enqueue(service).id == first.id
    with pytest.raises(DeliveryQueueFull):
        enqueue(service, channel="slack")
    service.process_next()
    assert enqueue(service, channel="slack").state == "queued"


def test_disabled_channel_waits_without_losing_queued_work(services):
    service = services()
    record = enqueue(service)
    service.set_enabled_channels([])
    assert service.process_next() is None
    assert service.get(record.id).attempts == 0
    service.set_enabled_channels(["generic"])
    assert service.process_next().state == "sent"


def test_worker_is_bounded_and_nonblocking_shutdown_preserves_pending_work(services):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = []

    def send(record):
        calls.append((record.id, threading.get_ident()))
        entered.set()
        assert release.wait(3)
        return DeliveryOutcome.sent()

    service = services(sender=send, on_result=lambda record: finished.set())
    first = enqueue(service)
    enqueue(service, channel="discord")
    service.start()
    assert entered.wait(3)
    assert len(calls) == 1
    assert calls[0][1] != threading.get_ident()
    assert service.shutdown(wait=False) is False
    release.set()
    assert finished.wait(3)
    assert service.shutdown(timeout=3)
    reopened = services()
    assert len(reopened.records(["sent"])) == 1
    assert len(reopened.records(["queued"])) == 1
    assert len(calls) == 1


class FakeSession:
    def __init__(self, status=204, error=None, retry_after=""):
        self.status = status
        self.error = error
        self.retry_after = retry_after
        self.closed = False
        self.calls = []

    def post(self, destination, **kwargs):
        self.calls.append((destination, kwargs))
        if self.error:
            raise self.error
        return type("Response", (), {"status_code": self.status, "headers": {"Retry-After": self.retry_after}})()

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "session,expected,retryable",
    [
        (FakeSession(status=204), "sent", False),
        (FakeSession(status=400), "failed", False),
        (FakeSession(status=302), "failed", False),
        (FakeSession(status=429, retry_after="17"), "failed", True),
        (FakeSession(status=503), "uncertain", False),
        (FakeSession(error=requests.ConnectTimeout("private")), "failed", True),
        (FakeSession(error=requests.ReadTimeout("private")), "uncertain", False),
        (FakeSession(error=requests.ConnectionError("private")), "uncertain", False),
    ],
)
def test_http_sender_conservatively_classifies_one_attempt(services, session, expected, retryable):
    service = services()
    record = enqueue(service)
    outcome = JsonWebhookSender(session_factory=lambda: session)(record)
    assert outcome.state == expected
    assert outcome.retryable is retryable
    assert "private" not in outcome.error
    assert len(session.calls) == 1
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.closed
    if session.status == 429:
        assert outcome.retry_after == 17


def test_channel_formatters_keep_existing_wire_shapes():
    payload = {"title": "Warning", "severity": "Severe", "location": "Home", "summary": "Take shelter."}
    assert format_notification_payload("generic", payload) == payload
    assert "**Warning**" in format_notification_payload("discord", payload)["content"]
    assert "*Warning*" in format_notification_payload("slack", payload)["text"]
    with pytest.raises(ValueError):
        format_notification_payload("unsupported", payload)


def test_new_revision_supersedes_only_unsent_jobs_and_old_key_stays_deduplicated(services):
    service = services()
    old = enqueue(service)
    other_channel = enqueue(service, channel="discord")
    new = enqueue(service, revision="revised")
    assert service.get(old.id).state == "cancelled"
    assert "Superseded" in service.get(old.id).error
    assert service.get(other_channel.id).state == "queued"
    assert enqueue(service).id == old.id
    assert service.get(old.id).state == "cancelled"
    service.process_next()
    service.process_next()
    assert service.get(new.id).state == "sent"
    newest = enqueue(service, revision="third")
    assert service.get(new.id).state == "sent"
    assert service.get(newest.id).state == "queued"


def test_operator_can_retry_after_missing_credentials_are_corrected(services):
    destination = [None]
    sent = []
    service = services(
        destination_resolver=lambda reference: destination[0],
        sender=lambda record: sent.append(record.id) or DeliveryOutcome.sent(),
    )
    record = enqueue(service, destination="credential:generic")
    assert service.process_next().state == "failed"
    assert service.process_next() is None
    destination[0] = "https://example.invalid/repaired"
    assert service.retry_failed(record.id)
    assert service.process_next().state == "sent"
    assert sent == [record.id]


def test_recovery_waits_for_verified_location_and_reconciliation(services):
    service = services()
    obsolete = enqueue(service, alert_id="cleared-while-offline")
    still_active = enqueue(service, alert_id="still-active")
    other_location = enqueue(service, alert_id="elsewhere", location_id="work")
    service.shutdown()

    reopened = services()
    reopened.set_enabled_locations([])
    assert reopened.process_next() is None
    assert all(record.attempts == 0 for record in reopened.records())
    active_ids = {"still-active"}
    for record in reopened.records(("queued", "failed")):
        if record.location_id == "home" and record.alert_id not in active_ids:
            reopened.cancel_alert(record.location_id, record.alert_id)
    reopened.set_enabled_locations(["home"])

    assert reopened.process_next().id == still_active.id
    assert reopened.process_next() is None
    assert reopened.get(obsolete.id).state == "cancelled"
    assert reopened.get(other_location.id).state == "queued"


def test_explicit_test_bypasses_location_gate_but_respects_channel_opt_in(services):
    service = services()
    service.set_enabled_locations([])
    service.set_enabled_channels([])
    test = enqueue(service, alert_id="test:manual", expires_at=9999999999)
    alert = enqueue(service, alert_id="real-alert")
    assert service.process_next() is None
    service.set_enabled_channels(["generic"])
    assert service.process_next().id == test.id
    assert service.process_next() is None
    assert service.get(alert.id).state == "queued"


def test_location_error_gate_pauses_retry_until_fresh_verification(services):
    now = [1000.0]
    service = services(
        clock=lambda: now[0],
        sender=lambda record: DeliveryOutcome.failed("Connect timeout", retryable=True),
    )
    service.set_enabled_locations(["home"])
    record = enqueue(service)
    assert service.process_next().attempts == 1
    service.set_enabled_locations([])
    now[0] += 10
    assert service.process_next() is None
    assert service.get(record.id).attempts == 1
    service.set_enabled_locations(["home"])
    assert service.process_next().attempts == 2
