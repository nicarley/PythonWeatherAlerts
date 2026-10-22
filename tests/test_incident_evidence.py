import csv
import json
from weather_alert.exporter import export_incident_csv, export_incident_json


def test_incident_export_distinguishes_delivery_and_acknowledgment(tmp_path):
    target = tmp_path / "incident.json"
    export_incident_json(str(target), "Station", [], [], acknowledgments=[{"operator": "Alex"}],
                         deliveries=[{"state": "sent", "channel": "discord"}],
                         sources={"alerts": {"fetched_at": 123}})
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["acknowledgments"][0]["operator"] == "Alex"
    assert payload["deliveries"][0]["state"] == "sent"
    assert payload["sources"]["alerts"]["fetched_at"] == 123
    assert "does not establish human receipt" in payload["delivery_note"]


def test_csv_includes_acknowledgment_and_treats_text_as_data(tmp_path):
    target = tmp_path / "incident.csv"
    export_incident_csv(str(target), [{"id": "alert", "title": "=DANGEROUS()",
        "acknowledgment": {"operator": "Alex", "acknowledged_at": 123, "note": "+formula"}}])
    with target.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["acknowledged_by"] == "Alex"
    assert row["title"] == "'=DANGEROUS()"
    assert row["acknowledgment_note"] == "'+formula"
