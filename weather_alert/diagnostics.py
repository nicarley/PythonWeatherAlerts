"""Opt-in diagnostic exports with credentials and location identifiers removed."""
import json
import platform
import re
import sys
import zipfile
from importlib.metadata import PackageNotFoundError, version

_PRIVATE_KEYS = re.compile(r"url|token|secret|password|destination|location|coords|latitude|longitude|operator|note|payload|summary|title|repeater|path", re.I)
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def redact(value):
    if isinstance(value, dict):
        return {str(key): "[redacted]" if _PRIVATE_KEYS.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _URL.sub("[redacted URL]", value)
    return value


def export_diagnostics(path, app_version, metrics, delivery_records, component_states):
    packages = {}
    for name in ("PySide6", "requests", "pyttsx3", "keyring"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "not installed"
    document = {
        "app_version": app_version, "python": sys.version.split()[0],
        "platform": platform.system(), "platform_release": platform.release(),
        "packages": packages, "metrics": metrics, "delivery": delivery_records,
        "components": component_states,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(redact(document), indent=2, default=str))
        archive.writestr("README.txt", "Generated locally by PyWeatherAlert. No settings file, logs, credentials, location identifiers, or alert payloads are included.\n")
