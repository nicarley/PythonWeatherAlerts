import json
import logging
import os
import tempfile
from typing import Any, Dict


class SettingsManager:
    """Handles loading and saving of application settings from JSON."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._migrate_settings_if_needed()

    def _migrate_settings_if_needed(self) -> None:
        old_settings_path = self.file_path.replace(".json", ".txt")
        if os.path.exists(old_settings_path) and not os.path.exists(self.file_path):
            try:
                os.rename(old_settings_path, self.file_path)
                logging.info("Migrated settings file from %s to %s", old_settings_path, self.file_path)
            except OSError as e:
                logging.error("Failed to migrate settings file: %s", e)

    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            logging.warning("Settings file not found: %s", self.file_path)
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                if not isinstance(settings, dict):
                    logging.error("Settings in %s must contain a JSON object", self.file_path)
                    return {}
                logging.info("Settings loaded from %s", self.file_path)
                return settings
        except (json.JSONDecodeError, UnicodeDecodeError, IOError) as e:
            logging.error("Error loading settings from %s: %s", self.file_path, e)
            return {}

    def save(self, settings: Dict[str, Any]) -> bool:
        temporary_path = None
        try:
            directory = os.path.dirname(os.path.abspath(self.file_path))
            os.makedirs(directory, exist_ok=True)
            # Replace only after the complete JSON has reached disk, so a
            # failed save leaves the user's previous preferences intact.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory,
                prefix=".settings-", suffix=".tmp", delete=False,
            ) as f:
                temporary_path = f.name
                json.dump(settings, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, self.file_path)
            logging.info("Settings saved to %s", self.file_path)
            return True
        except (OSError, TypeError, ValueError) as e:
            logging.error("Error saving settings to %s: %s", self.file_path, e)
            return False
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except OSError as e:
                    logging.warning("Could not remove temporary settings file %s: %s", temporary_path, e)
