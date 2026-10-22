import json
import logging
import os
import pickle
import tempfile
import uuid
from collections import deque
from typing import Any, Deque, Dict, List


HISTORY_SCHEMA_VERSION = 1


class _PrimitiveHistoryUnpickler(pickle.Unpickler):
    """Allow only primitive containers used by old history files."""

    def find_class(self, module: str, name: str):
        # Older pickle protocols encode sets using a global constructor.
        if module in {"builtins", "__builtin__"} and name in {"set", "frozenset"}:
            return set if name == "set" else frozenset
        raise pickle.UnpicklingError(f"Legacy history contains unsupported type {module}.{name}")


class _UnsupportedHistoryVersion(ValueError):
    pass


class AlertHistoryManager:
    """Manages persistent storage of seen alerts using JSON with pickle migration."""

    def __init__(self, file_path: str, max_history_items: int = 100):
        self.file_path = file_path
        self.persistence_error = ""
        self._preserve_existing_file = False
        self.max_history_items = max_history_items
        self.seen_alerts = set()
        self.alert_history: Deque[Dict[str, Any]] = deque(maxlen=max_history_items)
        self.lifecycle_timeline: Deque[Dict[str, Any]] = deque(maxlen=max_history_items * 10)
        self._load_history()

    def _legacy_pickle_candidates(self) -> List[str]:
        stem, ext = os.path.splitext(self.file_path)
        candidates = []
        if ext.lower() != ".dat":
            candidates.append(stem + ".dat")
        if ext.lower() != ".pickle":
            candidates.append(stem + ".pickle")
        return candidates

    def _load_legacy_pickle(self) -> bool:
        for legacy_path in self._legacy_pickle_candidates():
            if not os.path.exists(legacy_path):
                continue
            try:
                with open(legacy_path, "rb") as f:
                    data = _PrimitiveHistoryUnpickler(f).load()
                self._accept_history(data)
                if self.save_history():
                    logging.info("Migrated alert history from legacy pickle: %s", legacy_path)
                return True
            except Exception as e:
                logging.error("Error loading legacy alert history %s: %s", legacy_path, e)
        return False

    def _load_history(self) -> None:
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._accept_history(data)
                return
            self._load_legacy_pickle()
        except _UnsupportedHistoryVersion as e:
            # A downgrade must not overwrite history written by a newer app.
            self._preserve_existing_file = True
            self.persistence_error = str(e)
            logging.error("Error loading alert history: %s", e)
        except (ValueError, TypeError, UnicodeError) as e:
            self.persistence_error = str(e)
            logging.error("Error loading alert history: %s", e)
            quarantine_path = f"{self.file_path}.corrupt-{uuid.uuid4().hex}"
            try:
                os.replace(self.file_path, quarantine_path)
                logging.warning("Preserved unreadable alert history at %s", quarantine_path)
            except OSError:
                self._preserve_existing_file = True
                logging.exception("Could not preserve unreadable alert history")
        except OSError as e:
            self._preserve_existing_file = True
            self.persistence_error = str(e)
            logging.error("Error loading alert history: %s", e)

    def _accept_history(self, data: Any) -> None:
        if not isinstance(data, dict):
            raise ValueError("Alert history must contain a JSON object")
        version = data.get("schema_version", 0)
        if type(version) is not int or version < 0:
            raise ValueError("Invalid alert history schema version")
        if version > HISTORY_SCHEMA_VERSION:
            raise _UnsupportedHistoryVersion(f"Alert history schema {version} is newer than this application supports")
        seen = data.get("seen_alerts", [])
        history, lifecycle = data.get("history", []), data.get("lifecycle", [])
        if not isinstance(seen, (list, tuple, set, frozenset)) or any(not isinstance(item, str) for item in seen):
            raise ValueError("History seen_alerts must contain alert identifiers")
        for name, items in (("history", history), ("lifecycle", lifecycle)):
            if not isinstance(items, (list, tuple)) or any(not isinstance(item, dict) for item in items):
                raise ValueError(f"History {name} must contain record objects")
        # Validate all records before committing any loaded state. This also
        # rejects bytes/custom objects from legacy files before JSON migration.
        json.dumps({"history": history, "lifecycle": lifecycle}, allow_nan=False)
        self.seen_alerts = set(seen)
        self.alert_history = deque(history[:self.max_history_items], maxlen=self.max_history_items)
        self.lifecycle_timeline = deque(lifecycle[:self.max_history_items * 10], maxlen=self.max_history_items * 10)

    def save_history(self) -> bool:
        if self._preserve_existing_file:
            logging.error("Preserving unreadable or newer history file: %s", self.file_path)
            return False
        temporary_path = None
        try:
            directory = os.path.dirname(os.path.abspath(self.file_path))
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory,
                prefix=".history-", suffix=".tmp", delete=False,
            ) as f:
                temporary_path = f.name
                json.dump(
                    {
                        "schema_version": HISTORY_SCHEMA_VERSION,
                        "seen_alerts": sorted(list(self.seen_alerts)),
                        "history": list(self.alert_history),
                        "lifecycle": list(self.lifecycle_timeline),
                    },
                    f,
                    indent=2,
                    allow_nan=False,
                )
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, self.file_path)
            self.persistence_error = ""
            return True
        except (OSError, ValueError, TypeError) as e:
            self.persistence_error = str(e)
            logging.error("Error saving alert history: %s", e)
            return False
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except OSError:
                    logging.exception("Could not remove temporary history file")

    def add_alert(self, alert_id: str, alert_data: Dict[str, Any]) -> bool:
        if alert_id not in self.seen_alerts:
            self.seen_alerts.add(alert_id)
            self.alert_history.appendleft(alert_data)
            return True
        return False

    def remove_alert(self, alert_id: str) -> None:
        if alert_id in self.seen_alerts:
            self.seen_alerts.remove(alert_id)
        self.alert_history = deque(
            [alert for alert in self.alert_history if alert.get("id") != alert_id],
            maxlen=self.max_history_items,
        )
        self.save_history()

    def get_recent_alerts(self, count: int = 100) -> List[Dict[str, Any]]:
        return list(self.alert_history)[:count]

    def add_lifecycle_event(self, event: Dict[str, Any]) -> None:
        self.lifecycle_timeline.appendleft(event)

    def get_recent_lifecycle(self, count: int = 250, location_id: str = "") -> List[Dict[str, Any]]:
        items = list(self.lifecycle_timeline)
        if location_id:
            items = [item for item in items if item.get("location_id") == location_id]
        return items[:count]

    def clear_history(self) -> None:
        self.seen_alerts.clear()
        self.alert_history.clear()
        self.lifecycle_timeline.clear()
        self.save_history()
