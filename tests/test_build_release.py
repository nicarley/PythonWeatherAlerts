"""Version ownership and the packaged-smoke release gate are deployment contracts."""

import ast
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import build_release


def test_version_read_does_not_import_or_execute_gui(tmp_path):
    source = tmp_path / "PyWeatherAlertGui.py"
    source.write_text('raise RuntimeError("must not execute")\nversionnumber = "26.10.22.7"\n')

    assert build_release.read_gui_version(source) == "26.10.22.7"


@pytest.mark.parametrize("assignment", [
    'versionnumber = "1.2.3"', 'versionnumber = "26.02.30.1"',
    'versionnumber = "26.10.22.65536"', 'versionnumber = "26.10.22." + "1"',
    'versionnumber = "26.10.22.1"\nversionnumber = "26.10.22.2"',
])
def test_invalid_or_ambiguous_gui_version_prevents_release(tmp_path, assignment):
    source = tmp_path / "PyWeatherAlertGui.py"
    source.write_text(assignment)
    with pytest.raises(ValueError):
        build_release.read_gui_version(source)


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_native_plan_has_exact_entry_point_and_derived_version_metadata(tmp_path, system):
    (tmp_path / "PyWeatherAlertGui.py").write_text('versionnumber = "26.10.22.7"')
    plan = build_release.release_plan(tmp_path, system=system, machine="testarch")
    spec = build_release.spec_source(plan)

    ast.parse(spec)
    assert Path(plan["entry_point"]).name == "PyWeatherAlertGui.py"
    assert "26.10.22.7" in plan["artifact_name"]
    assert "testarch" in plan["artifact_name"]
    if system == "Darwin":
        assert "'CFBundleShortVersionString': '26.10.22'" in spec
        assert "'CFBundleVersion': '7'" in spec
    if system == "Windows":
        resource = build_release.windows_version_resource(plan["version"])
        ast.parse(resource)
        assert "filevers=(26, 10, 22, 7)" in resource
        assert "StringStruct('ProductVersion', '26.10.22.7')" in resource


def test_smoke_failure_prevents_release_archive_and_manifest(tmp_path, monkeypatch):
    (tmp_path / "PyWeatherAlertGui.py").write_text('versionnumber = "26.10.22.7"')
    output = tmp_path / "output"
    plan = build_release.release_plan(tmp_path, output)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "PyInstaller" in command:
            executable = Path(plan["executable"])
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("stand-in package")
            return
        assert command == [plan["executable"], "--smoke-test"]
        assert kwargs["timeout"] == 60
        assert kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"
        raise subprocess.CalledProcessError(1, command)

    archive = Mock()
    monkeypatch.setattr(build_release.subprocess, "run", fake_run)
    monkeypatch.setattr(build_release.shutil, "make_archive", archive)

    with pytest.raises(subprocess.CalledProcessError):
        build_release.build_release(tmp_path, output)

    assert len(calls) == 2
    archive.assert_not_called()
    assert list(output.glob("*.json")) == []
