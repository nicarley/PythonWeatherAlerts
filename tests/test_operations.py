import json
import zipfile

from weather_alert.operations import OperationsStore
from weather_alert.diagnostics import export_diagnostics
from weather_alert.secrets import CredentialStore


def test_acknowledgments_are_revision_and_location_specific(tmp_path):
    path = tmp_path / "ops.db"
    store = OperationsStore(path)
    store.acknowledge("A", "warning", "v1", note="Team informed")
    assert OperationsStore(path).acknowledgment("A", "warning", "v1")["note"] == "Team informed"
    assert store.acknowledgment("A", "warning", "v2") is None
    assert store.acknowledgment("B", "warning", "v1") is None


def test_snapshot_persistence_and_metrics(tmp_path):
    store = OperationsStore(tmp_path / "ops.db")
    store.save_snapshot("A", {"alerts": [], "fetched_at": 50})
    store.record("detection_delay_seconds", "A", 10)
    store.record("detection_delay_seconds", "A", 20)
    assert store.load_snapshots()["A"]["fetched_at"] == 50
    assert store.metrics()[0]["average"] == 15


def test_diagnostics_omit_credentials_and_location_data(tmp_path):
    path = tmp_path / "support.zip"
    export_diagnostics(path, "26.10.22.2", [], [{"destination": "https://hook/secret", "location_id": "home", "payload": {"title": "private"}, "error": "POST https://hook/secret failed"}], [])
    with zipfile.ZipFile(path) as archive:
        text = archive.read("diagnostics.json").decode()
    assert "secret" not in text and "home" not in text and "private" not in text
    assert json.loads(text)["app_version"] == "26.10.22.2"


def test_credentials_fail_closed_without_persistent_backend():
    class BrokenBackend:
        def set_password(self, *args):
            raise RuntimeError("locked")
    store = CredentialStore(BrokenBackend())
    assert store.set("generic", "https://example.test/token") is False
    assert store.resolve("credential:generic") == "https://example.test/token"
