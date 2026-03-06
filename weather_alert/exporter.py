import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def export_incident_json(path: str, location_name: str, alerts: List[Dict[str, Any]], lifecycle: List[Dict[str, Any]]) -> str:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "location_name": location_name,
        "alert_count": len(alerts),
        "alerts": alerts,
        "timeline": lifecycle,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out)


def export_incident_csv(path: str, alerts: List[Dict[str, Any]]) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "title", "severity", "event", "updated", "expires", "status", "message_type", "distance_miles", "link"]
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for alert in alerts:
            writer.writerow({field: alert.get(field, "") for field in fields})
    return str(out)

