import json
import logging
import os
import pickle
from collections import deque
from typing import Any, Deque, Dict, List


class AlertHistoryManager:
    """Manages persistent storage of seen alerts using JSON with pickle migration."""

    def __init__(self, file_path: str, max_history_items: int = 100):
        self.file_path = file_path
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
                    data = pickle.load(f)
                self.seen_alerts = set(data.get("seen_alerts", []))
                history = data.get("history", [])
                self.alert_history = deque(history, maxlen=self.max_history_items)
                self.lifecycle_timeline = deque(data.get("lifecycle", []), maxlen=self.max_history_items * 10)
                logging.info("Migrated alert history from legacy pickle: %s", legacy_path)
                self.save_history()
                return True
            except Exception as e:
                logging.error("Error loading legacy alert history %s: %s", legacy_path, e)
        return False

    def _load_history(self) -> None:
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.seen_alerts = set(data.get("seen_alerts", []))
                self.alert_history = deque(data.get("history", []), maxlen=self.max_history_items)
                self.lifecycle_timeline = deque(data.get("lifecycle", []), maxlen=self.max_history_items * 10)
                return
            self._load_legacy_pickle()
        except Exception as e:
            logging.error("Error loading alert history: %s", e)

    def save_history(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "seen_alerts": sorted(list(self.seen_alerts)),
                        "history": list(self.alert_history),
                        "lifecycle": list(self.lifecycle_timeline),
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logging.error("Error saving alert history: %s", e)

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
