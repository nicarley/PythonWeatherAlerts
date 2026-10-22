import json
import pickle

import pytest

from weather_alert.history import AlertHistoryManager


def test_history_add_and_persist(tmp_path):
    history_path = tmp_path / "alert_history.json"
    manager = AlertHistoryManager(str(history_path), max_history_items=10)
    added = manager.add_alert("abc", {"id": "abc", "title": "Test"})
    assert added is True
    manager.save_history()

    manager2 = AlertHistoryManager(str(history_path), max_history_items=10)
    items = manager2.get_recent_alerts()
    assert len(items) == 1
    assert items[0]["id"] == "abc"


def test_history_lifecycle_persist(tmp_path):
    history_path = tmp_path / "alert_history.json"
    manager = AlertHistoryManager(str(history_path), max_history_items=10)
    manager.add_lifecycle_event({"location_id": "62881", "lifecycle": "issued", "title": "Test"})
    manager.save_history()

    manager2 = AlertHistoryManager(str(history_path), max_history_items=10)
    timeline = manager2.get_recent_lifecycle(location_id="62881")
    assert len(timeline) == 1
    assert timeline[0]["lifecycle"] == "issued"


def test_history_migrates_from_pickle(tmp_path):
    json_path = tmp_path / "alert_history.json"
    legacy_path = tmp_path / "alert_history.dat"
    with open(legacy_path, "wb") as f:
        pickle.dump({"seen_alerts": {"legacy-id"}, "history": [{"id": "legacy-id", "title": "Legacy"}]}, f)

    manager = AlertHistoryManager(str(json_path), max_history_items=10)
    items = manager.get_recent_alerts()
    assert items[0]["id"] == "legacy-id"
    assert json_path.exists()


def test_history_legacy_protocol_sets_migrate_without_arbitrary_classes(tmp_path):
    path = tmp_path / "history.json"
    path.with_suffix(".dat").write_bytes(pickle.dumps({"seen_alerts": {"a"}, "history": [{"id": "a"}]}, protocol=2))

    manager = AlertHistoryManager(str(path))

    assert manager.get_recent_alerts()[0]["id"] == "a"
    assert json.loads(path.read_text())["schema_version"] == 1


_PICKLE_CALLS = []


def _untrusted_pickle_callable():
    _PICKLE_CALLS.append(True)
    return {"history": []}


class _UntrustedLegacyPayload:
    def __reduce__(self):
        return _untrusted_pickle_callable, ()


def test_legacy_migration_never_executes_pickle_callables(tmp_path):
    path = tmp_path / "history.json"
    legacy_path = path.with_suffix(".dat")
    legacy_path.write_bytes(pickle.dumps(_UntrustedLegacyPayload()))
    _PICKLE_CALLS.clear()

    manager = AlertHistoryManager(str(path))

    assert _PICKLE_CALLS == []
    assert manager.get_recent_alerts() == []
    assert legacy_path.exists()
    assert not path.exists()


@pytest.mark.parametrize("content", ["{broken", "[]", '{"history": [42]}', '{"seen_alerts": "abc"}'])
def test_corrupt_history_is_preserved_before_fresh_storage(tmp_path, content):
    path = tmp_path / "history.json"
    path.write_text(content, encoding="utf-8")

    manager = AlertHistoryManager(str(path))

    backups = list(tmp_path.glob("history.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == content
    assert manager.get_recent_alerts() == []
    manager.add_alert("new", {"id": "new"})
    assert manager.save_history()
    assert AlertHistoryManager(str(path)).get_recent_alerts()[0]["id"] == "new"


def test_newer_history_schema_is_preserved_on_downgrade(tmp_path):
    path = tmp_path / "history.json"
    original = '{"schema_version": 99, "history": [{"id": "future"}]}'
    path.write_text(original, encoding="utf-8")

    manager = AlertHistoryManager(str(path))
    manager.add_alert("new", {"id": "new"})

    assert manager.save_history() is False
    assert path.read_text(encoding="utf-8") == original


def test_failed_history_save_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    manager = AlertHistoryManager(str(path))
    manager.add_alert("old", {"id": "old"})
    assert manager.save_history()
    original = path.read_bytes()
    manager.add_alert("new", {"id": "new"})

    def reject_replace(*_args):
        raise OSError("Disk unavailable")

    monkeypatch.setattr("weather_alert.history.os.replace", reject_replace)

    assert manager.save_history() is False
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_history_load_keeps_newest_records_when_limit_decreases(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"history": [{"id": "newest"}, {"id": "older"}, {"id": "oldest"}]}))

    manager = AlertHistoryManager(str(path), max_history_items=2)

    assert [record["id"] for record in manager.get_recent_alerts()] == ["newest", "older"]


def test_history_relative_path_and_invalid_serialization_are_safe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = AlertHistoryManager("history.json")
    manager.add_alert("old", {"id": "old"})
    assert manager.save_history()
    original = (tmp_path / "history.json").read_bytes()
    manager.add_alert("invalid", {"id": "invalid", "value": object()})

    assert manager.save_history() is False
    assert (tmp_path / "history.json").read_bytes() == original
    assert list(tmp_path.glob(".history-*.tmp")) == []
