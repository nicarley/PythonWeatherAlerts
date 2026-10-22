"""Bounded background monitoring without Qt, persistence, or notifications."""

import copy
import logging
import math
import threading
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Set, Tuple

from .api import NwsApiClient
from .marine import MarineDataService
from .models import COMPONENT_NAMES, ComponentSnapshot, LocationSnapshot


FORECAST_COMPONENTS = {
    "hourly_forecast": "hourly",
    "daily_forecast": "daily",
    "grid_forecast": "grid",
    "current_conditions": "observations",
}
UpdateCallback = Callable[[LocationSnapshot], None]


@dataclass
class _Request:
    snapshot: LocationSnapshot
    callback: UpdateCallback
    pending: Set[str]
    futures: Set[Future] = field(default_factory=set)


def _source_updated_at(data: Any) -> Optional[str]:
    """Keep a provider timestamp when one exists; never invent one from fetch time."""
    candidates = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key in ("updated", "updateTime", "timestamp", "observed_at", "sent"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate:
                    candidates.append(candidate)
            for key, child in value.items():
                if key not in {"raw", "geometry"} and isinstance(child, (Mapping, list, tuple)):
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(data)
    if not candidates:
        return None

    def sort_key(value: str) -> float:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return float("-inf")

    return max(candidates, key=sort_key)


class MonitoringCoordinator:
    """Publish source-by-source snapshots and discard superseded responses.

    Callbacks may run on the requesting thread or a worker thread. UI adapters
    must marshal them to their UI thread and ignore older snapshot revisions.
    Callback exceptions are logged and do not stop a refresh. Cancellation
    prevents subsequent publication and cancels queued work; already-running
    HTTP requests finish within their client's configured timeout/retry policy.

    Built-in clients use an isolated requests session per worker. Other supplied
    clients are serialized behind a lock unless they implement fork_for_worker().
    The injected executor is an optional test/embedding seam, owned by its caller.
    """

    def __init__(
        self, api_client: Any, marine_service: Any = None, max_workers: int = 4,
        *, clock: Callable[[], float] = time.time,
        executor: Optional[Executor] = None, max_pending_locations: int = 64,
    ):
        if max_workers < 1 or max_pending_locations < 1:
            raise ValueError("Worker and pending-location limits must be positive")
        self.api_client = api_client
        self.marine_service = marine_service
        self._clock = clock
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="weather-monitor"
        )
        self._owns_executor = executor is None
        self._max_pending_locations = max_pending_locations
        self._lock = threading.RLock()
        self._shared_client_lock = threading.RLock()
        self._coordinates_lock = threading.Lock()
        self._local = threading.local()
        self._requests: Dict[str, _Request] = {}
        self._futures: Set[Future] = set()
        self._owned_clients = []
        self._closed = False

    def latest_snapshot(self, location_id: str) -> Optional[LocationSnapshot]:
        with self._lock:
            request = self._requests.get(location_id)
            return request.snapshot if request else None

    def seed(self, location_id: str, legacy_dict: Mapping[str, Any]) -> LocationSnapshot:
        """Restore last-known data without presenting it as a new successful check.

        Payloads produced by to_legacy_dict retain each source's timestamps.
        Older whole-check payloads use their recorded fetched_at for present data.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Monitoring coordinator is shut down")
            old = self._requests.get(location_id)
            if old and not old.snapshot.complete:
                raise RuntimeError("Cannot seed a location while it is refreshing")
            metadata = legacy_dict.get("component_status") or {}
            components = {}
            for name in COMPONENT_NAMES:
                status = metadata.get(name, {}) if isinstance(metadata, Mapping) else {}
                status = status if isinstance(status, Mapping) else {}
                data = legacy_dict.get(name)
                fetched_at = status.get("fetched_at", legacy_dict.get("fetched_at")) if data is not None else None
                if not isinstance(fetched_at, (int, float)) or not math.isfinite(fetched_at):
                    fetched_at = None
                revision = status.get("revision", 0)
                components[name] = ComponentSnapshot(
                    data=data, fetched_at=fetched_at,
                    source_updated_at=status.get("source_updated_at") or _source_updated_at(data),
                    error=status.get("error"), revision=revision if isinstance(revision, int) else 0,
                    cached=fetched_at is not None,
                )
            coords = legacy_dict.get("coords")
            if not isinstance(coords, (list, tuple)) or len(coords) != 2:
                coords = None
            timestamps = [component.fetched_at for component in components.values() if component.fetched_at is not None]
            snapshot = LocationSnapshot(
                location_id, old.snapshot.generation if old else 0,
                min(timestamps) if timestamps else self._clock(), coords=coords,
                components=components, finished_at=max(timestamps) if timestamps else self._clock(),
            )
            self._requests[location_id] = _Request(snapshot, lambda _snapshot: None, set())
            return snapshot

    def refresh(self, location_id: str, on_update: UpdateCallback) -> int:
        if not location_id or not callable(on_update):
            raise ValueError("A location and update callback are required")
        with self._lock:
            if self._closed:
                raise RuntimeError("Monitoring coordinator is shut down")
            previous = self._requests.get(location_id)
            active_count = sum(not item.snapshot.complete for item in self._requests.values())
            if (previous is None or previous.snapshot.complete) and active_count >= self._max_pending_locations:
                raise RuntimeError("Too many pending location refreshes")
            old = previous.snapshot if previous else None
            generation = old.generation + 1 if old else 1
            pending = set(COMPONENT_NAMES)
            if self.marine_service is None:
                pending.remove("marine_data")
            components = {
                name: replace(
                    old.components.get(name, ComponentSnapshot()) if old else ComponentSnapshot(),
                    loading=name in pending, error=None,
                ) for name in COMPONENT_NAMES
            }
            request = _Request(LocationSnapshot(
                location_id=location_id, generation=generation, started_at=self._clock(),
                coords=old.coords if old else None, components=components,
            ), on_update, pending)
            self._requests[location_id] = request
            if previous:
                for future in tuple(previous.futures):
                    future.cancel()
        self._emit(request, request.snapshot)
        self._submit(request, lambda: self._resolve_and_fetch_alerts(request), pending)
        return generation

    def cancel(self, location_id: str) -> bool:
        with self._lock:
            request = self._requests.get(location_id)
            if request is None or request.snapshot.complete:
                return False
            components = {
                name: replace(component, loading=False,
                              error="Refresh cancelled" if component.loading else component.error)
                for name, component in request.snapshot.components.items()
            }
            request.snapshot = replace(
                request.snapshot, components=components, cancelled=True,
                finished_at=self._clock(), revision=request.snapshot.revision + 1,
            )
            request.pending.clear()
            for future in tuple(request.futures):
                future.cancel()
            snapshot = request.snapshot
        self._emit(request, snapshot)
        return True

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            self._closed = True
            for location_id in tuple(self._requests):
                self.cancel(location_id)
        if self._owns_executor:
            self._executor.shutdown(wait=wait, cancel_futures=True)
        self._close_idle_clients()

    def _current(self, request: _Request) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._requests.get(request.snapshot.location_id) is request
                and not request.snapshot.complete
            )

    def _emit(self, request: _Request, snapshot: LocationSnapshot) -> None:
        with self._lock:
            if (self._closed or self._requests.get(snapshot.location_id) is not request
                    or snapshot.revision < request.snapshot.revision):
                return
            # Keep publication ordered with cancellation. Callbacks should only
            # enqueue work (for example, emit a Qt signal), not perform I/O.
            try:
                request.callback(snapshot)
            except Exception:
                logging.exception("Weather update callback failed for %s", snapshot.location_id)

    def _submit(self, request: _Request, operation: Callable[[], None], failure_keys: Iterable[str]) -> None:
        with self._lock:
            if not self._current(request):
                return
            try:
                future = self._executor.submit(operation)
            except Exception as exc:
                for name in tuple(failure_keys):
                    self._settle(request, name, error=str(exc))
                return
            self._futures.add(future)
            request.futures.add(future)
            future.add_done_callback(lambda done: self._job_finished(request, done))

    def _job_finished(self, request: _Request, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
            request.futures.discard(future)
        self._close_idle_clients()

    def _close_idle_clients(self) -> None:
        with self._lock:
            if not self._closed or self._futures:
                return
            clients, self._owned_clients = self._owned_clients, []
        for client in clients:
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            except Exception:
                logging.exception("Could not close weather client")

    def _worker_api(self) -> Any:
        if not hasattr(self._local, "api"):
            factory = getattr(self.api_client, "fork_for_worker", None)
            self._local.api = factory() if callable(factory) else self.api_client
            if self._local.api is not self.api_client:
                with self._lock:
                    self._owned_clients.append(self._local.api)
        return self._local.api

    def _call_api(self, method: str, *args: Any) -> Any:
        if method == "get_coordinates_for_location":
            # Initialize geocoding only on a worker, once on the original
            # client. Cloning does not trigger constructor/network activity.
            with self._shared_client_lock:
                return getattr(self.api_client, method)(*args)
        api = self._worker_api()
        if api is self.api_client:
            with self._shared_client_lock:
                return getattr(api, method)(*args)
        return getattr(api, method)(*args)

    def _resolve_and_fetch_alerts(self, request: _Request) -> None:
        if not self._current(request):
            return
        try:
            # pgeocode's data frame is shared by built-in worker clients.
            with self._coordinates_lock:
                if not self._current(request):
                    return
                coords = self._call_api("get_coordinates_for_location", request.snapshot.location_id)
            if not coords or len(coords) != 2:
                raise ValueError("Could not resolve location coordinates")
            lat, lon = float(coords[0]), float(coords[1])
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Location coordinates are out of range")
            with self._lock:
                if not self._current(request):
                    return
                request.snapshot = replace(request.snapshot, coords=(lat, lon), revision=request.snapshot.revision + 1)
            # Publish alerts before starting optional/forecast I/O for this request.
            self._fetch_component(request, "alerts", lambda: self._call_api("get_alerts", lat, lon))
            self._submit(request, lambda: self._fetch_forecast_urls(request, lat, lon), FORECAST_COMPONENTS)
            if self.marine_service is not None:
                self._submit(request, lambda: self._fetch_component(
                    request, "marine_data", lambda: self._fetch_marine(lat, lon)
                ), ("marine_data",))
        except Exception as exc:
            for name in tuple(request.pending):
                self._settle(request, name, error=str(exc))

    def _fetch_forecast_urls(self, request: _Request, lat: float, lon: float) -> None:
        if not self._current(request):
            return
        try:
            urls = self._call_api("get_forecast_urls", lat, lon)
            if not isinstance(urls, Mapping) or not urls:
                raise ValueError("Forecast endpoints unavailable")
            for name, key in FORECAST_COMPONENTS.items():
                url = urls.get(key)
                if not url:
                    self._settle(request, name, error=f"{key.title()} endpoint unavailable")
                    continue
                method = "get_current_conditions" if name == "current_conditions" else "get_forecast_data"
                self._submit(request, lambda n=name, m=method, u=url: self._fetch_component(
                    request, n, lambda: self._call_api(m, u), forecast_url=u if m == "get_forecast_data" else None
                ), (name,))
        except Exception as exc:
            for name in FORECAST_COMPONENTS:
                self._settle(request, name, error=str(exc))

    def _fetch_marine(self, lat: float, lon: float) -> Any:
        api = self._worker_api()
        if type(self.marine_service) is MarineDataService and isinstance(api, NwsApiClient) and api is not self.api_client:
            if not hasattr(self._local, "marine"):
                # Copy configuration/caches without sharing the mutable Session.
                service = copy.copy(self.marine_service)
                for key, value in self.marine_service.__dict__.items():
                    if key != "session":
                        setattr(service, key, copy.deepcopy(value))
                service.session = api.session
                self._local.marine = service
            return self._local.marine.fetch_nearest_marine_data(lat, lon)
        with self._shared_client_lock:
            return self.marine_service.fetch_nearest_marine_data(lat, lon)

    def _fetch_component(
        self, request: _Request, name: str, fetch: Callable[[], Any], *, forecast_url: Optional[str] = None,
    ) -> None:
        if not self._current(request):
            return
        try:
            data = fetch()
            if data is None or (name == "alerts" and not isinstance(data, (list, tuple))):
                raise ValueError(f"{name.replace('_', ' ').title()} unavailable")
            fetched_at = self._clock()
            if forecast_url:
                api = self._worker_api()
                if isinstance(api, NwsApiClient):
                    cached_at = api.get_forecast_fetched_at(forecast_url)
                    if cached_at is not None:
                        fetched_at = cached_at
            self._settle(request, name, data=data, fetched_at=fetched_at)
        except Exception as exc:
            self._settle(request, name, error=str(exc))

    def _settle(
        self, request: _Request, name: str, *, data: Any = None,
        fetched_at: Optional[float] = None, error: Optional[str] = None,
    ) -> None:
        with self._lock:
            if not self._current(request) or name not in request.pending:
                return
            old = request.snapshot.components[name]
            component = (
                replace(old, error=error, loading=False, revision=old.revision + 1)
                if error is not None else
                ComponentSnapshot(data, fetched_at, _source_updated_at(data), revision=old.revision + 1)
            )
            components = dict(request.snapshot.components)
            components[name] = component
            request.pending.remove(name)
            request.snapshot = replace(
                request.snapshot, components=components,
                finished_at=self._clock() if not request.pending else None,
                revision=request.snapshot.revision + 1,
            )
            snapshot = request.snapshot
        self._emit(request, snapshot)
