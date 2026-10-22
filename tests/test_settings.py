import json

import pytest

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


def test_settings_save_supports_a_relative_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SettingsManager("settings.json")

    assert manager.save({"locations": [{"id": "62881"}]})
    assert manager.load() == {"locations": [{"id": "62881"}]}


@pytest.mark.parametrize("content", ["[]", "null", '"settings"', "42", "{incomplete"])
def test_settings_invalid_contents_fall_back_to_defaults(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")

    assert SettingsManager(str(path)).load() == {}


def test_settings_invalid_encoding_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfeinvalid")

    assert SettingsManager(str(path)).load() == {}


def test_failed_serialization_preserves_saved_preferences(tmp_path):
    path = tmp_path / "settings.json"
    manager = SettingsManager(str(path))
    assert manager.save({"theme": "dark", "locations": [{"id": "62881"}]})
    original = path.read_bytes()

    assert manager.save({"theme": "light", "unsupported": object()}) is False
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_failed_replacement_preserves_saved_preferences(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    manager = SettingsManager(str(path))
    assert manager.save({"theme": "dark"})
    original = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("Disk unavailable")

    monkeypatch.setattr("weather_alert.settings.os.replace", fail_replace)

    assert manager.save({"theme": "light"}) is False
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("payload", [{"schema_version": 99}, {"locations": "wrong"},
    {"locations": [{"id": "same"}, {"id": "same"}]}, {"splitter_sizes": {"workbench": [-1, 2]}},
    {"webhook_url": 42}])
def test_invalid_restore_cannot_replace_good_settings(tmp_path, payload):
    path = tmp_path / "settings.json"
    manager = SettingsManager(str(path))
    assert manager.save({"schema_version": 2, "locations": [{"id": "62881"}]})
    original = path.read_bytes()
    assert manager.save(payload) is False
    assert path.read_bytes() == original


def test_corrupt_settings_are_preserved_before_defaults_are_saved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{truncated", encoding="utf-8")
    manager = SettingsManager(str(path))
    assert manager.load() == {}
    assert manager.save({"schema_version": 2})
    recovered = list(tmp_path.glob("settings.json.recovery-*"))
    assert len(recovered) == 1
    assert recovered[0].read_text(encoding="utf-8") == "{truncated"
