# Desktop releases

`PyWeatherAlertGui.py` owns the application version through its literal `versionnumber`
assignment in `yy.mm.dd.buildnumber` format. Change it there once. The release helper
reads the assignment with Python's AST parser; it never imports or runs the GUI to
discover a version. Windows file metadata, macOS bundle metadata, artifact names,
and the release manifest are derived from that value.

From the repository root, use an active Python environment:

```text
python -m pip install -r requirements-build.txt
python build_release.py --dry-run
python build_release.py
```

`Build/compile.cmd` and `sh Build/compile.sh` delegate to the same helper. Build on
the target operating system: Windows, macOS, and Linux packages are native builds.
Generated work is under `Build/release-work`; deliverables are under `dist`.

Every build must pass the packaged executable's isolated `--smoke-test` before an
archive and manifest are produced. This checks startup and local resources without
weather requests, user preferences, audio, or notification delivery. It does not
verify live provider availability or configured delivery channels. CI performs
tests, source smoke, and packaged smoke on all three desktop platforms.

The manifest records the GUI version, Python/dependency versions, archive checksum,
and smoke result. PyInstaller is pinned in `requirements-build.txt`; runtime
dependencies retain their supported ranges, and the manifest records what resolved.

Distribution signing is optional and requires credentials outside this repository.
On macOS, `--macos-sign-identity "Developer ID Application: ..."` passes an installed
identity to PyInstaller and verifies the resulting signature. Notarization and
Windows signing are separate release steps. Default CI artifacts are not signed for
public distribution or notarized. Do not publish a package solely because smoke passed.
