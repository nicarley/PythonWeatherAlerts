import pickle

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


def test_history_migrates_from_pickle(tmp_path):
    json_path = tmp_path / "alert_history.json"
    legacy_path = tmp_path / "alert_history.dat"
    with open(legacy_path, "wb") as f:
        pickle.dump({"seen_alerts": {"legacy-id"}, "history": [{"id": "legacy-id", "title": "Legacy"}]}, f)

    manager = AlertHistoryManager(str(json_path), max_history_items=10)
    items = manager.get_recent_alerts()
    assert items[0]["id"] == "legacy-id"
    assert json_path.exists()
