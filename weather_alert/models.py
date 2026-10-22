"""Immutable, toolkit-independent weather snapshots.

Retrieval time and provider observation/update time are deliberately separate:
a successful request can still contain an old observation.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple


COMPONENT_NAMES = (
    "alerts", "hourly_forecast", "daily_forecast", "grid_forecast",
    "current_conditions", "marine_data",
)


def freeze(value: Any) -> Any:
    """Copy JSON-like provider data into recursively immutable containers."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")


def thaw(value: Any) -> Any:
    """Return independent mutable data for legacy renderers and rule engines."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class ComponentSnapshot:
    data: Any = None
    fetched_at: Optional[float] = None
    source_updated_at: Optional[str] = None
    error: Optional[str] = None
    loading: bool = False
    revision: int = 0
    cached: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", freeze(self.data))

    @property
    def has_data(self) -> bool:
        # An empty alert collection is a valid successful observation.
        return self.fetched_at is not None

    @property
    def is_stale(self) -> bool:
        return self.has_data and (self.cached or self.loading or self.error is not None)


@dataclass(frozen=True)
class LocationSnapshot:
    location_id: str
    generation: int
    started_at: float
    coords: Optional[Tuple[float, float]] = None
    components: Mapping[str, ComponentSnapshot] = field(default_factory=dict)
    finished_at: Optional[float] = None
    cancelled: bool = False
    revision: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        if self.coords is not None:
            object.__setattr__(self, "coords", tuple(self.coords))

    @property
    def complete(self) -> bool:
        return self.finished_at is not None

    def to_legacy_dict(self) -> Dict[str, Any]:
        result = {
            name: thaw(self.components.get(name, ComponentSnapshot()).data)
            for name in COMPONENT_NAMES
        }
        result["alerts"] = result["alerts"] or []
        result["marine_data"] = result["marine_data"] or {}
        result.update(
            location_id=self.location_id,
            coords=self.coords,
            fetched_at=self.components.get("alerts", ComponentSnapshot()).fetched_at,
            component_status={
                name: {
                    "fetched_at": component.fetched_at,
                    "source_updated_at": component.source_updated_at,
                    "error": component.error,
                    "loading": component.loading,
                    "revision": component.revision,
                    "cached": component.cached,
                } for name, component in self.components.items()
            },
        )
        return result
