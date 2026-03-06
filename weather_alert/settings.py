import json
import logging
import os
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
                logging.info("Settings loaded from %s", self.file_path)
                return settings
        except (json.JSONDecodeError, IOError) as e:
            logging.error("Error loading settings from %s: %s", self.file_path, e)
            return {}

    def save(self, settings: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)
            logging.info("Settings saved to %s", self.file_path)
            return True
        except (IOError, OSError) as e:
            logging.error("Error saving settings to %s: %s", self.file_path, e)
            return False
