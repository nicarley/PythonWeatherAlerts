import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def export_incident_json(path: str, location_name: str, alerts: List[Dict[str, Any]], lifecycle: List[Dict[str, Any]], *, acknowledgments=None, deliveries=None, sources=None) -> str:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "location_name": location_name,
        "alert_count": len(alerts),
        "alerts": alerts,
        "timeline": lifecycle,
        "acknowledgments": acknowledgments or [],
        "deliveries": deliveries or [],
        "sources": sources or {},
        "delivery_note": "Provider acceptance does not establish human receipt or acknowledgment.",
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out)


def export_incident_csv(path: str, alerts: List[Dict[str, Any]]) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "title", "severity", "event", "updated", "expires", "status", "message_type", "distance_miles", "link", "acknowledged_by", "acknowledged_at", "acknowledgment_note"]
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for alert in alerts:
            row = {field: alert.get(field, "") for field in fields}
            acknowledgment = alert.get("acknowledgment") or {}
            row.update(acknowledged_by=acknowledgment.get("operator", ""),
                       acknowledged_at=acknowledgment.get("acknowledged_at", ""),
                       acknowledgment_note=acknowledgment.get("note", ""))
            # Spreadsheet programs must treat provider/operator text as data.
            writer.writerow({key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value for key, value in row.items()})
    return str(out)

