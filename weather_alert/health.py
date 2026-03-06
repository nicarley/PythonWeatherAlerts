import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class DeliveryHealthTracker:
    def __init__(self, max_events: int = 500):
        self.max_events = max_events
        self.events: Deque[Dict[str, Any]] = deque(maxlen=max_events)

    def record(self, channel: str, success: bool, error: str = "") -> None:
        self.events.appendleft(
            {
                "timestamp": time.time(),
                "channel": channel,
                "success": bool(success),
                "error": error,
            }
        )

    def stats(self) -> Dict[str, Dict[str, Any]]:
        channels: Dict[str, Dict[str, Any]] = {}
        for event in self.events:
            entry = channels.setdefault(
                event["channel"],
                {"attempts": 0, "successes": 0, "failures": 0, "success_rate": 0.0, "last_error": "", "last_ts": 0.0},
            )
            entry["attempts"] += 1
            if event["success"]:
                entry["successes"] += 1
            else:
                entry["failures"] += 1
                if not entry["last_error"]:
                    entry["last_error"] = event.get("error", "")
            if event["timestamp"] > entry["last_ts"]:
                entry["last_ts"] = event["timestamp"]

        for entry in channels.values():
            attempts = entry["attempts"] or 1
            entry["success_rate"] = round((entry["successes"] / attempts) * 100.0, 1)
        return channels

    def recent_events(self, count: int = 100) -> List[Dict[str, Any]]:
        return list(self.events)[:count]

