"""Deterministic source isolation, cancellation, freshness, and adapter contracts."""

import threading
from concurrent.futures import Executor, Future
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from weather_alert.api import NwsApiClient
from weather_alert.models import ComponentSnapshot, LocationSnapshot
from weather_alert.monitoring import FORECAST_COMPONENTS, MonitoringCoordinator


class ManualExecutor(Executor):
    def __init__(self):
        self.jobs = []

    def submit(self, operation):
        future = Future()
        self.jobs.append((future, operation))
        return future

    def run_next(self):
        future, operation = self.jobs.pop(0)
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(operation())
            except BaseException as exc:
                future.set_exception(exc)
                raise

    def run_all(self):
        while self.jobs:
            self.run_next()


class FakeApi:
    def __init__(self):
        self.calls = []
        self.alerts = [{"id": "alert-1", "title": "Flood Warning", "sent": "2026-10-22T10:00:00Z"}]
        self.fail_forecast_urls = False
        self.fail_hourly = False
        self.fail_alerts = False
        self.on_alerts = None

    def get_coordinates_for_location(self, location_id):
        self.calls.append(("coords", location_id))
        return 38.6, -90.2

    def get_alerts(self, *coords):
        self.calls.append(("alerts", coords))
        if self.on_alerts:
            callback, self.on_alerts = self.on_alerts, None
            callback()
        if self.fail_alerts:
            raise RuntimeError("Alerts unavailable")
        return self.alerts

    def get_forecast_urls(self, *coords):
        self.calls.append(("forecast_urls", coords))
        if self.fail_forecast_urls:
            return None
        return {key: key for key in ("hourly", "daily", "grid", "observations")}

    def get_forecast_data(self, url):
        self.calls.append(("forecast", url))
        if self.fail_hourly and url == "hourly":
            return None
        return {"properties": {"updated": "2026-10-22T09:00:00Z", "periods": [{"name": url}]}}

    def get_current_conditions(self, url):
        self.calls.append(("observations", url))
        return {"timestamp": "2026-10-22T08:00:00Z", "temperature_f": 72}


class FakeMarine:
    def __init__(self):
        self.calls = 0

    def fetch_nearest_marine_data(self, *_coords):
        self.calls += 1
        return {"ndbc": {"observed_at": "2026-10-22 07:00 UTC", "value": "2 ft"}}


def test_alert_progress_arrives_before_forecast_failure_or_marine_work():
    api, marine, executor, updates = FakeApi(), FakeMarine(), ManualExecutor(), []
    api.fail_forecast_urls = True
    coordinator = MonitoringCoordinator(api, marine, executor=executor, clock=lambda: 100)

    coordinator.refresh("home", updates.append)
    executor.run_next()

    assert updates[-1].components["alerts"].has_data
    assert updates[-1].components["alerts"].error is None
    assert not updates[-1].complete
    assert [call[0] for call in api.calls] == ["coords", "alerts"]
    assert marine.calls == 0

    executor.run_all()
    final = coordinator.latest_snapshot("home")
    assert final.complete
    assert final.components["alerts"].data[0]["id"] == "alert-1"
    assert all(final.components[name].error for name in FORECAST_COMPONENTS)
    assert final.components["marine_data"].has_data


def test_source_failure_keeps_its_own_timestamp_and_recovers_independently():
    api, executor, updates = FakeApi(), ManualExecutor(), []
    now = [100.0]
    coordinator = MonitoringCoordinator(api, executor=executor, clock=lambda: now[0])
    coordinator.refresh("home", updates.append)
    executor.run_all()
    first = coordinator.latest_snapshot("home")
    assert first.components["alerts"].source_updated_at == "2026-10-22T10:00:00Z"
    assert first.components["current_conditions"].source_updated_at == "2026-10-22T08:00:00Z"

    now[0], api.fail_hourly, api.fail_alerts = 200.0, True, True
    coordinator.refresh("home", updates.append)
    assert coordinator.latest_snapshot("home").components["alerts"].is_stale
    executor.run_all()
    failed = coordinator.latest_snapshot("home")
    for name in ("alerts", "hourly_forecast"):
        assert failed.components[name].is_stale
        assert failed.components[name].fetched_at == 100
        assert failed.components[name].data == first.components[name].data
    assert failed.components["daily_forecast"].fetched_at == 200
    assert not failed.components["daily_forecast"].is_stale

    now[0], api.fail_hourly, api.fail_alerts, api.alerts = 300.0, False, False, []
    coordinator.refresh("home", updates.append)
    executor.run_all()
    recovered = coordinator.latest_snapshot("home")
    assert recovered.components["alerts"].has_data
    assert recovered.components["alerts"].data == ()
    assert not recovered.components["alerts"].is_stale
    assert recovered.components["alerts"].fetched_at == 300
    assert recovered.components["hourly_forecast"].error is None


def test_superseded_inflight_generation_never_publishes_its_alerts():
    api, executor, updates = FakeApi(), ManualExecutor(), []
    coordinator = MonitoringCoordinator(api, executor=executor)
    api.on_alerts = lambda: coordinator.refresh("home", updates.append)
    coordinator.refresh("home", updates.append)

    executor.run_all()

    assert coordinator.latest_snapshot("home").generation == 2
    assert coordinator.latest_snapshot("home").complete
    assert all(not item.components["alerts"].has_data for item in updates if item.generation == 1)
    assert len([call for call in api.calls if call[0] == "forecast_urls"]) == 1
    assert [item.revision for item in updates if item.generation == 2] == sorted(
        item.revision for item in updates if item.generation == 2
    )


def test_cancel_stops_queued_work_and_allows_a_new_generation():
    api, executor, updates = FakeApi(), ManualExecutor(), []
    coordinator = MonitoringCoordinator(api, executor=executor)
    coordinator.refresh("home", updates.append)
    assert coordinator.cancel("home")
    assert updates[-1].complete and updates[-1].cancelled
    executor.run_all()
    assert api.calls == []
    assert not coordinator.cancel("home")

    assert coordinator.refresh("home", updates.append) == 2
    executor.run_all()
    assert coordinator.latest_snapshot("home").complete
    assert not coordinator.latest_snapshot("home").cancelled


def test_shutdown_suppresses_callbacks_and_rejects_new_work():
    api, executor, updates = FakeApi(), ManualExecutor(), []
    coordinator = MonitoringCoordinator(api, executor=executor)
    coordinator.refresh("home", updates.append)
    coordinator.shutdown()
    executor.run_all()

    assert len(updates) == 1
    assert coordinator.latest_snapshot("home").cancelled
    assert api.calls == []
    with pytest.raises(RuntimeError, match="shut down"):
        coordinator.refresh("home", updates.append)


def test_callback_failure_cannot_leave_a_refresh_running():
    executor = ManualExecutor()
    coordinator = MonitoringCoordinator(FakeApi(), executor=executor)

    def broken_callback(_snapshot):
        raise RuntimeError("view closed")

    coordinator.refresh("home", broken_callback)
    executor.run_all()

    assert coordinator.latest_snapshot("home").complete
    assert coordinator.latest_snapshot("home").components["alerts"].error is None


def test_snapshots_are_deeply_immutable_and_legacy_data_is_independent():
    source = [{"id": "a", "areas": ["A"]}]
    component = ComponentSnapshot(source, fetched_at=100)
    snapshot = LocationSnapshot("home", 1, 100, components={"alerts": component})
    source[0]["areas"].append("B")

    assert component.data[0]["areas"] == ("A",)
    with pytest.raises(TypeError):
        component.data[0]["id"] = "changed"
    with pytest.raises(TypeError):
        snapshot.components["alerts"] = ComponentSnapshot()
    with pytest.raises(FrozenInstanceError):
        component.fetched_at = 200
    legacy = snapshot.to_legacy_dict()
    legacy["alerts"][0]["areas"].append("C")
    assert component.data[0]["areas"] == ("A",)


def test_seed_round_trip_preserves_per_source_freshness_and_errors():
    executor = ManualExecutor()
    coordinator = MonitoringCoordinator(FakeApi(), executor=executor)
    original = LocationSnapshot("home", 3, 100, coords=(38.6, -90.2), components={
        "alerts": ComponentSnapshot([], fetched_at=150, revision=2),
        "hourly_forecast": ComponentSnapshot({"properties": {}}, fetched_at=100, error="timeout", revision=4),
    }, finished_at=160)

    seeded = coordinator.seed("home", original.to_legacy_dict())

    assert seeded.complete
    assert seeded.components["alerts"].fetched_at == 150
    assert seeded.components["alerts"].is_stale
    assert seeded.components["hourly_forecast"].fetched_at == 100
    assert seeded.components["hourly_forecast"].error == "timeout"
    assert not seeded.components["daily_forecast"].has_data
    coordinator.refresh("home", lambda _snapshot: None)
    with pytest.raises(RuntimeError, match="while it is refreshing"):
        coordinator.seed("home", original.to_legacy_dict())


def test_worker_client_isolation_and_forecast_cache_keeps_original_fetch_time(monkeypatch):
    monkeypatch.setattr("weather_alert.api.pgeocode", None)
    monkeypatch.setattr("weather_alert.api.time.time", lambda: 200)
    api = NwsApiClient("test-agent")
    api.get_coordinates_for_location = lambda _location: (38.6, -90.2)
    api.get_alerts = lambda *_coords: []
    api.get_forecast_urls = lambda *_coords: {key: key for key in ("hourly", "daily", "grid", "observations")}
    api.get_current_conditions = lambda _url: {"timestamp": "2026-10-22T08:00:00Z"}
    for url in ("hourly", "daily", "grid"):
        api._forecast_data_cache[url] = (400, {"properties": {"updated": "2026-10-22T09:00:00Z"}})
    fork = api.fork_for_worker()
    assert fork.session is not api.session
    assert fork._forecast_data_cache is not api._forecast_data_cache
    fork.close()

    executor = ManualExecutor()
    coordinator = MonitoringCoordinator(api, executor=executor, clock=lambda: 300)
    coordinator.refresh("home", lambda _snapshot: None)
    executor.run_all()

    assert coordinator.latest_snapshot("home").components["hourly_forecast"].fetched_at == 100
    assert coordinator.latest_snapshot("home").components["alerts"].fetched_at == 300
    coordinator.shutdown()
    api.close()


def test_geocoder_is_lazy_and_backend_health_does_not_initialize_it(monkeypatch):
    calls = []
    backend = SimpleNamespace(Nominatim=lambda country: calls.append(country) or object())
    monkeypatch.setattr("weather_alert.api.pgeocode", backend)
    api = NwsApiClient("test-agent")

    assert api.geocoding_available
    assert api.get_coordinates_for_location("38.6,-90.2") == (38.6, -90.2)
    assert calls == []
    assert api.pgeocode_client is api.pgeocode_client
    assert calls == ["us"]
    api.close()


def test_worker_limit_and_inflight_shutdown_are_bounded():
    release = threading.Event()
    two_running = threading.Event()
    lock = threading.Lock()
    running, peak = [0], [0]

    class ConcurrentApi(FakeApi):
        def fork_for_worker(self):
            return ConcurrentApi()

        def get_alerts(self, *_coords):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
                if running[0] == 2:
                    two_running.set()
            try:
                assert release.wait(5), "test failed to release workers"
                return []
            finally:
                with lock:
                    running[0] -= 1

    coordinator = MonitoringCoordinator(ConcurrentApi(), max_workers=2)
    updates = []
    try:
        for location in ("one", "two", "three"):
            coordinator.refresh(location, updates.append)
        assert two_running.wait(5)
        coordinator.shutdown(wait=False)
        callback_count = len(updates)
        release.set()
        coordinator.shutdown(wait=True)
        assert len(updates) == callback_count
        assert peak[0] == 2
        assert all(coordinator.latest_snapshot(location).cancelled for location in ("one", "two", "three"))
    finally:
        release.set()
        coordinator.shutdown(wait=True)


def test_pending_location_limit_and_coordinate_failure_complete_cleanly():
    api, executor = FakeApi(), ManualExecutor()
    coordinator = MonitoringCoordinator(api, executor=executor, max_pending_locations=1)
    api.get_coordinates_for_location = lambda _location: None
    coordinator.refresh("home", lambda _snapshot: None)
    with pytest.raises(RuntimeError, match="Too many"):
        coordinator.refresh("other", lambda _snapshot: None)
    executor.run_all()
    final = coordinator.latest_snapshot("home")
    assert final.complete
    assert all(final.components[name].error for name in final.components if name != "marine_data")
    assert not final.components["alerts"].has_data
