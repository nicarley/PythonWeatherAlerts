import json

from weather_alert.settings import SettingsManager


def test_settings_migrates_txt_to_json(tmp_path):
    json_path = tmp_path / "settings.json"
    txt_path = tmp_path / "settings.txt"
    txt_path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    manager = SettingsManager(str(json_path))
    loaded = manager.load()
    assert loaded["x"] == 1


def test_settings_save_and_load(tmp_path):
    path = tmp_path / "settings.json"
    manager = SettingsManager(str(path))
    assert manager.save({"abc": 123})
    assert manager.load()["abc"] == 123
