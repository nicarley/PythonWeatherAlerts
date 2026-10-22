import json
from pathlib import Path

import pytest

import build_release


def test_source_fingerprint_covers_runtime_inputs_and_ignores_build_outputs(tmp_path):
    (tmp_path / "weather_alert").mkdir()
    (tmp_path / "resources").mkdir()
    (tmp_path / "Build").mkdir()
    (tmp_path / "PyWeatherAlertGui.py").write_text('versionnumber = "26.10.22.2"\n')
    module = tmp_path / "weather_alert" / "api.py"
    module.write_text("VALUE = 1\n")
    resource = tmp_path / "resources" / "modern.qss"
    resource.write_text("color: white;")
    original = build_release.source_fingerprint(tmp_path)
    assert "weather_alert/api.py" in original["files"]
    assert "resources/modern.qss" in original["files"]
    (tmp_path / "Build" / "generated.py").write_text("unrelated output")
    assert build_release.source_fingerprint(tmp_path) == original
    resource.write_text("color: black;")
    assert build_release.source_fingerprint(tmp_path)["sha256"] != original["sha256"]
    module.unlink()
    assert "weather_alert/api.py" not in build_release.source_fingerprint(tmp_path)["files"]


def test_source_changes_during_build_prevent_release_archive(tmp_path, monkeypatch):
    gui = tmp_path / "PyWeatherAlertGui.py"
    gui.write_text('versionnumber = "26.10.22.2"\n')
    output = tmp_path / "output"
    plan = build_release.release_plan(tmp_path, output)
    executable = Path(plan["executable"])

    def run(command, **kwargs):
        if "PyInstaller" in command:
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("test executable")
            gui.write_text('versionnumber = "26.10.22.2"\n# changed during build\n')

    monkeypatch.setattr(build_release.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="sources changed"):
        build_release.build_release(tmp_path, output)
    assert not list(output.glob("*.zip"))
    assert not list(output.glob("*.tar.gz"))
    assert not list(output.glob("*.json"))
