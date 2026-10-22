"""Native bundles must never include local settings or alert history."""
import ast

from build_release import release_plan, source_fingerprint, spec_source


def test_release_packages_only_static_assets_and_fingerprints_the_same_inputs(tmp_path):
    (tmp_path / "PyWeatherAlertGui.py").write_text('versionnumber = "26.10.22.1"', encoding="utf-8")
    resources = tmp_path / "resources"
    resources.mkdir()
    allowed = {"icon.ico", "icon.png", "icon.icns", "pyweather.png", "modern.qss", "dark_modern.qss"}
    for name in allowed | {"settings.json", "settings.txt", "alert_history.dat", "compile.cmd"}:
        (resources / name).write_text("fixture", encoding="utf-8")
    nested = resources / "icons" / "nested"
    nested.mkdir(parents=True)
    (nested / "safe.svg").write_text("<svg/>", encoding="utf-8")
    (resources / "icons" / "personal.json").write_text('{"secret": "private"}', encoding="utf-8")
    source = spec_source(release_plan(tmp_path, system="Windows", machine="AMD64"))
    tree = ast.parse(source)
    analysis = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "Analysis")
    data = ast.literal_eval(next(argument.value for argument in analysis.keywords if argument.arg == "datas"))
    expected = {(str(resources / name), "resources") for name in allowed}
    expected.add((str(nested / "safe.svg"), "resources/icons/nested"))
    assert set(data) == expected
    inputs = set(source_fingerprint(tmp_path)["files"])
    assert inputs == {"PyWeatherAlertGui.py", *["resources/" + name for name in allowed], "resources/icons/nested/safe.svg"}
