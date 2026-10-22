"""Build and smoke-test a native desktop bundle using the GUI's version only."""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parent
APP_NAME = "Weather Alert Station"


def static_assets(root):
    """Package only shipped presentation assets; never settings or alert history."""
    root = Path(root)
    paths = [root / "resources" / name for name in (
        "icon.ico", "icon.png", "icon.icns", "pyweather.png", "modern.qss", "dark_modern.qss",
    )]
    image_suffixes = {".svg", ".png", ".ico", ".icns", ".jpg", ".jpeg", ".gif", ".webp"}
    paths.extend(path for path in (root / "resources" / "icons").rglob("*")
                 if path.is_file() and path.suffix.lower() in image_suffixes)
    return sorted(path for path in paths if path.is_file())


def source_fingerprint(root):
    """Identify the application inputs used by a native release build."""
    root = Path(root)
    paths = {
        root / name for name in (
            "PyWeatherAlertGui.py", "smoke.py", "requirements.txt",
            "requirements-build.txt", "build_release.py",
            "macOS/PyWeatherAlertMacOS/Resources/icon.icns",
        )
    }
    paths.update((root / "weather_alert").rglob("*.py"))
    paths.update(static_assets(root))
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths) if path.is_file()
    }
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"sha256": digest, "files": files}
VERSION_PATTERN = re.compile(r"\d{2}\.\d{2}\.\d{2}\.\d+")


def read_gui_version(source: Path) -> str:
    """Read a literal assignment without importing Qt or executing application code."""
    tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
    values = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == "versionnumber" for target in targets):
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                raise ValueError("GUI versionnumber must be one literal string")
            values.append(node.value.value)
    if len(values) != 1 or not VERSION_PATTERN.fullmatch(values[0]):
        raise ValueError("GUI versionnumber must use yy.mm.dd.buildnumber")
    version = values[0]
    year, month, day, build = map(int, version.split("."))
    date(2000 + year, month, day)
    if build > 65535:
        raise ValueError("Build number exceeds the Windows version-resource limit (65535)")
    return version


def release_plan(
    root: Path = ROOT, output_dir: Optional[Path] = None, *, system: Optional[str] = None,
    machine: Optional[str] = None,
) -> Dict[str, Any]:
    root = root.resolve()
    system = system or platform.system()
    if system not in {"Windows", "Darwin", "Linux"}:
        raise ValueError(f"Unsupported release platform: {system}")
    version = read_gui_version(root / "PyWeatherAlertGui.py")
    label = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[system]
    architecture = (machine or platform.machine()).lower()
    target = Path(output_dir).resolve() if output_dir else root / "dist"
    bundle = target / "native" / (f"{APP_NAME}.app" if system == "Darwin" else APP_NAME)
    executable = (
        bundle / "Contents" / "MacOS" / APP_NAME if system == "Darwin" else
        bundle / (f"{APP_NAME}.exe" if system == "Windows" else APP_NAME)
    )
    return {
        "version": version, "system": system, "platform": label, "architecture": architecture,
        "root": str(root), "entry_point": str(root / "PyWeatherAlertGui.py"),
        "output_dir": str(target), "bundle": str(bundle), "executable": str(executable),
        "work_dir": str(root / "Build" / "release-work" / f"{label}-{architecture}"),
        "artifact_name": f"weather-alert-station-{version}-{label}-{architecture}",
    }


def windows_version_resource(version: str) -> str:
    parts = tuple(map(int, version.split(".")))
    strings = {
        "FileDescription": APP_NAME, "FileVersion": version, "ProductName": APP_NAME,
        "ProductVersion": version, "OriginalFilename": f"{APP_NAME}.exe",
    }
    entries = ",\n".join(f"StringStruct({key!r}, {value!r})" for key, value in strings.items())
    return (
        "VSVersionInfo(ffi=FixedFileInfo(\n"
        f"filevers={parts!r}, prodvers={parts!r}, mask=0x3f, flags=0x0,\n"
        "OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        f"kids=[StringFileInfo([StringTable('040904B0', [{entries}])]),\n"
        "VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n"
    )


def spec_source(plan: Dict[str, Any], macos_sign_identity: Optional[str] = None) -> str:
    root, work = Path(plan["root"]), Path(plan["work_dir"])
    system = plan["system"]
    driver = {"Windows": "sapi5", "Darwin": "nsss", "Linux": "espeak"}[system]
    icon = root / "resources" / "icon.ico" if system == "Windows" else None
    version_file = work / "version-resource.txt" if system == "Windows" else None
    source = (
        "# Generated by build_release.py. Version comes from PyWeatherAlertGui.py.\n"
        f"a = Analysis([{plan['entry_point']!r}], pathex=[{str(root)!r}], binaries=[],\n"
        f"    datas={[(str(path), path.parent.relative_to(root).as_posix()) for path in static_assets(root)]!r},\n"
        f"    hiddenimports=['pyttsx3.drivers.{driver}'], hookspath=[],\n"
        "    hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)\n"
        "pyz = PYZ(a.pure)\n"
        "exe = EXE(pyz, a.scripts, [], exclude_binaries=True,\n"
        f"    name={APP_NAME!r}, debug=False, strip=False, upx=False, console=False,\n"
        f"    icon={str(icon) if icon else None!r}, version={str(version_file) if version_file else None!r},\n"
        f"    codesign_identity={macos_sign_identity!r}, entitlements_file=None)\n"
        f"coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name={APP_NAME!r})\n"
    )
    if system == "Darwin":
        parts = tuple(map(int, plan["version"].split(".")))
        info = {
            "CFBundleShortVersionString": ".".join(map(str, parts[:3])),
            "CFBundleVersion": str(parts[3]), "NSHighResolutionCapable": True,
        }
        icon = root / "macOS" / "PyWeatherAlertMacOS" / "Resources" / "icon.icns"
        source += (
            f"app = BUNDLE(coll, name={APP_NAME + '.app'!r}, icon={str(icon)!r},\n"
            "    bundle_identifier='org.pythonweatheralerts.desktop',\n"
            f"    info_plist={info!r})\n"
        )
    return source


def build_release(
    root: Path = ROOT, output_dir: Optional[Path] = None, *, macos_sign_identity: Optional[str] = None,
) -> Path:
    plan = release_plan(root, output_dir)
    if macos_sign_identity and plan["system"] != "Darwin":
        raise ValueError("A macOS signing identity can only be used on macOS")
    root, work, output = Path(plan["root"]), Path(plan["work_dir"]), Path(plan["output_dir"])
    source_state = source_fingerprint(root)
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    spec = work / "weather-alert.spec"
    spec.write_text(spec_source(plan, macos_sign_identity), encoding="utf-8")
    if plan["system"] == "Windows":
        (work / "version-resource.txt").write_text(windows_version_resource(plan["version"]), encoding="utf-8")

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(output / "native"), "--workpath", str(work / "pyinstaller"), str(spec),
    ], check=True, cwd=root)
    executable = Path(plan["executable"])
    if not executable.is_file():
        raise RuntimeError(f"Packager did not produce the expected executable: {executable}")
    smoke_env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([str(executable), "--smoke-test"], check=True, timeout=60, env=smoke_env, cwd=root)
    if macos_sign_identity:
        subprocess.run(["codesign", "--verify", "--deep", "--strict", plan["bundle"]], check=True)

    if source_fingerprint(root) != source_state:
        raise RuntimeError("Application sources changed during packaging; rerun the build before releasing it.")
    bundle = Path(plan["bundle"])
    archive_format = "zip" if plan["system"] == "Windows" else "gztar"
    archive = Path(shutil.make_archive(
        str(output / plan["artifact_name"]), archive_format,
        root_dir=bundle.parent, base_dir=bundle.name,
    ))
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    dependency_versions = {}
    for name in ("PyInstaller", "PySide6", "requests", "urllib3", "feedparser", "pyttsx3", "pgeocode", "pandas", "keyring"):
        try:
            dependency_versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependency_versions[name] = "not installed"
    manifest = {
        "source_sha256": source_state["sha256"],
        "source_files": source_state["files"],
        "version": plan["version"], "version_source": "PyWeatherAlertGui.py:versionnumber",
        "platform": plan["platform"], "architecture": plan["architecture"],
        "archive": archive.name, "sha256": digest.hexdigest(), "smoke_test": "passed",
        "python": platform.python_version(), "dependencies": dependency_versions,
        "distribution_signed": bool(macos_sign_identity), "notarized": False,
    }
    (output / f"{plan['artifact_name']}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return archive


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="Release output directory (default: dist)")
    parser.add_argument("--dry-run", action="store_true", help="Print the release plan without building or importing the GUI")
    parser.add_argument("--macos-sign-identity", help="Optional installed macOS signing identity; no notarization is performed")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            print(json.dumps(release_plan(output_dir=args.output_dir), indent=2))
        else:
            print(build_release(output_dir=args.output_dir, macos_sign_identity=args.macos_sign_identity))
        return 0
    except (OSError, ValueError, RuntimeError, SyntaxError, subprocess.SubprocessError) as exc:
        print(f"Release build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
