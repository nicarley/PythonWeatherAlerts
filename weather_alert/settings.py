import json
import logging
import os
import tempfile
import shutil
import math
from datetime import datetime
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

    @staticmethod
    def validate(settings):
        if not isinstance(settings, dict):
            raise ValueError("Settings must be a JSON object")
        version = settings.get("schema_version", 1)
        if type(version) is not int or version not in (1, 2):
            raise ValueError("Unsupported settings schema version")
        bool_names = {"mute_audio", "dark_mode_enabled", "auto_refresh_content", "first_run_completed"}
        for key, value in settings.items():
            if key in bool_names or key.startswith(("announce_", "show_", "toolbar_show_", "enable_")):
                if type(value) is not bool:
                    raise ValueError(f"{key} must be true or false")
        for key in ("current_location_id", "check_interval_key", "repeater_info", "radar_url", "forecast_view", "log_sort_order"):
            if key in settings and not isinstance(settings[key], str):
                raise ValueError(f"{key} must be text")
        if "radar_options_dict" in settings:
            options = settings["radar_options_dict"]
            if not isinstance(options, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in options.items()):
                raise ValueError("Web sources must map names to URLs")
        state = settings.get("credential_state", {})
        if not isinstance(state, dict):
            raise ValueError("Credential state must be an object")
        for channel, value in state.items():
            if channel not in ("generic", "discord", "slack") or not isinstance(value, dict) or any(type(value.get(key)) is not bool for key in ("configured", "persisted")):
                raise ValueError("Credential state is invalid")
        locations = settings.get("locations")
        if locations is not None:
            if not isinstance(locations, list) or len(locations) > 100:
                raise ValueError("Locations must be a list of at most 100 entries")
            for location in locations:
                if not isinstance(location, dict) or not isinstance(location.get("id"), str) or not location["id"].strip():
                    raise ValueError("Each location needs a nonempty identifier")
                for name in ("name", "group"):
                    if name in location and not isinstance(location[name], str):
                        raise ValueError(f"Location {name} must be text")
                if "rules" in location:
                    from .rules import default_location_rules
                    SettingsManager._validate_rule_types(location["rules"], default_location_rules())
            if len({loc["id"] for loc in locations}) != len(locations):
                raise ValueError("Location identifiers must be unique")
        if "splitter_sizes" in settings:
            sizes = settings["splitter_sizes"]
            if not isinstance(sizes, dict) or any(not isinstance(values, list) or len(values) != 2 or any(type(value) is not int or value < 0 for value in values) for values in sizes.values()):
                raise ValueError("Saved panel sizes are invalid")
        for field in ("webhook_url", "discord_webhook_url", "slack_webhook_url"):
            if field in settings and not isinstance(settings[field], str):
                raise ValueError("Notification destinations must be text")
        return settings

    @staticmethod
    def _validate_rule_types(values, defaults):
        if not isinstance(values, dict):
            raise ValueError("Location rules must be an object")
        for key, value in values.items():
            if key not in defaults:
                continue
            expected = defaults[key]
            if isinstance(expected, dict):
                SettingsManager._validate_rule_types(value, expected)
            elif expected is None:
                if value is not None and type(value) is not bool:
                    raise ValueError(f"{key} must be true, false, or null")
            elif isinstance(expected, bool):
                if type(value) is not bool:
                    raise ValueError(f"{key} must be true or false")
            elif isinstance(expected, (int, float)):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{key} must be a nonnegative number")
            elif isinstance(expected, list):
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    raise ValueError(f"{key} must be a list of text values")
            elif not isinstance(value, str):
                raise ValueError(f"{key} must be text")

    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            logging.warning("Settings file not found: %s", self.file_path)
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                if not isinstance(settings, dict):
                    raise ValueError("Settings must contain a JSON object")
                logging.info("Settings loaded from %s", self.file_path)
                return self.validate(settings)
        except (ValueError, TypeError, UnicodeDecodeError, IOError) as e:
            logging.error("Error loading settings from %s: %s", self.file_path, e)
            # Preserve the original before any later save writes defaults.
            try:
                recovery = self.file_path + ".recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                shutil.copyfile(self.file_path, recovery)
                logging.warning("Preserved unreadable settings at %s", recovery)
            except OSError:
                logging.exception("Could not preserve unreadable settings")
            return {}

    def save(self, settings: Dict[str, Any]) -> bool:
        temporary_path = None
        try:
            self.validate(settings)
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
