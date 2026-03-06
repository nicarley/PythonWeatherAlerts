import hashlib
import time
from typing import Any, Dict, Tuple


def alert_thread_key(alert: Dict[str, Any]) -> str:
    event = (alert.get("event") or "").strip().lower()
    area = (alert.get("area_desc") or "").strip().lower()
    title = (alert.get("title") or "").strip().lower()
    raw = f"{event}|{area}|{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def alert_fingerprint(alert: Dict[str, Any]) -> str:
    fields = [
        alert.get("event", ""),
        alert.get("severity", ""),
        alert.get("urgency", ""),
        alert.get("certainty", ""),
        (alert.get("summary") or "")[:400],
    ]
    raw = "|".join(str(v) for v in fields)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class AlertDeduplicator:
    def __init__(self, default_cooldown_s: int = 900):
        self.default_cooldown_s = default_cooldown_s
        self.last_sent_at: Dict[str, float] = {}
        self.last_fingerprint: Dict[str, str] = {}

    def classify(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        thread_id = alert_thread_key(alert)
        fingerprint = alert_fingerprint(alert)
        previous_fp = self.last_fingerprint.get(thread_id)
        is_near_duplicate = previous_fp == fingerprint
        self.last_fingerprint[thread_id] = fingerprint
        return {"thread_id": thread_id, "fingerprint": fingerprint, "is_near_duplicate": is_near_duplicate}

    def should_send(self, alert: Dict[str, Any], *, cooldown_s: int = 0, force: bool = False) -> Tuple[bool, str]:
        thread_id = alert_thread_key(alert)
        now = time.time()
        effective_cooldown = cooldown_s or self.default_cooldown_s
        if force:
            self.last_sent_at[thread_id] = now
            return True, "forced"
        last = self.last_sent_at.get(thread_id)
        if last is not None and (now - last) < effective_cooldown:
            remaining = int(effective_cooldown - (now - last))
            return False, f"suppressed ({remaining}s cooldown remaining)"
        self.last_sent_at[thread_id] = now
        return True, "allowed"

