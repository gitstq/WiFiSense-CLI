"""
WiFiSense-CLI Configuration Manager

Manages application configuration using JSON format. Supports default
configuration, user-defined overrides, configuration validation, and
runtime modification. Zero external dependencies.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Default Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "scanner": {
        "interface": "auto",
        "poll_interval": 1.0,
        "scan_timeout": 10.0,
        "max_retries": 3,
        "retry_delay": 0.5,
        "include_hidden": False,
    },
    "analyzer": {
        "moving_average_window": 5,
        "ewma_alpha": 0.3,
        "z_score_threshold": 2.0,
        "iqr_factor": 1.5,
        "trend_window": 10,
        "anomaly_cooldown": 5.0,
        "fingerprint_min_aps": 2,
    },
    "events": {
        "enabled": True,
        "rules_file": "rules.json",
        "cooldown": 30.0,
        "max_events_per_minute": 10,
        "log_file": "events.log",
    },
    "dashboard": {
        "refresh_rate": 0.5,
        "history_length": 60,
        "show_hidden": False,
        "color_scheme": "default",
    },
    "data": {
        "storage_dir": "data",
        "session_file": "session.json",
        "max_sessions": 100,
        "csv_export_dir": "exports",
        "retention_days": 30,
    },
    "logging": {
        "level": "INFO",
        "file": None,
        "max_size_mb": 10,
        "backup_count": 3,
    },
    "notification": {
        "ntfy_url": "https://ntfy.sh",
        "ntfy_topic": "",
        "webhook_url": "",
        "webhook_method": "POST",
        "webhook_headers": {},
    },
}


# ---------------------------------------------------------------------------
# Configuration Schema for Validation
# ---------------------------------------------------------------------------

CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    "scanner": {
        "interface": {"type": str, "default": "auto"},
        "poll_interval": {"type": (int, float), "min": 0.1, "max": 60.0, "default": 1.0},
        "scan_timeout": {"type": (int, float), "min": 1.0, "max": 120.0, "default": 10.0},
        "max_retries": {"type": int, "min": 0, "max": 10, "default": 3},
        "retry_delay": {"type": (int, float), "min": 0.0, "max": 10.0, "default": 0.5},
        "include_hidden": {"type": bool, "default": False},
    },
    "analyzer": {
        "moving_average_window": {"type": int, "min": 2, "max": 100, "default": 5},
        "ewma_alpha": {"type": (int, float), "min": 0.01, "max": 1.0, "default": 0.3},
        "z_score_threshold": {"type": (int, float), "min": 0.5, "max": 5.0, "default": 2.0},
        "iqr_factor": {"type": (int, float), "min": 0.5, "max": 5.0, "default": 1.5},
        "trend_window": {"type": int, "min": 3, "max": 100, "default": 10},
        "anomaly_cooldown": {"type": (int, float), "min": 0.0, "max": 300.0, "default": 5.0},
        "fingerprint_min_aps": {"type": int, "min": 1, "max": 20, "default": 2},
    },
    "events": {
        "enabled": {"type": bool, "default": True},
        "rules_file": {"type": str, "default": "rules.json"},
        "cooldown": {"type": (int, float), "min": 0.0, "max": 3600.0, "default": 30.0},
        "max_events_per_minute": {"type": int, "min": 1, "max": 1000, "default": 10},
        "log_file": {"type": str, "default": "events.log"},
    },
    "dashboard": {
        "refresh_rate": {"type": (int, float), "min": 0.1, "max": 5.0, "default": 0.5},
        "history_length": {"type": int, "min": 10, "max": 1000, "default": 60},
        "show_hidden": {"type": bool, "default": False},
        "color_scheme": {"type": str, "default": "default"},
    },
    "data": {
        "storage_dir": {"type": str, "default": "data"},
        "session_file": {"type": str, "default": "session.json"},
        "max_sessions": {"type": int, "min": 1, "max": 10000, "default": 100},
        "csv_export_dir": {"type": str, "default": "exports"},
        "retention_days": {"type": int, "min": 1, "max": 365, "default": 30},
    },
    "logging": {
        "level": {"type": str, "default": "INFO"},
        "file": {"type": (str, type(None)), "default": None},
        "max_size_mb": {"type": (int, float), "min": 1, "max": 1000, "default": 10},
        "backup_count": {"type": int, "min": 0, "max": 100, "default": 3},
    },
    "notification": {
        "ntfy_url": {"type": str, "default": "https://ntfy.sh"},
        "ntfy_topic": {"type": str, "default": ""},
        "webhook_url": {"type": str, "default": ""},
        "webhook_method": {"type": str, "default": "POST"},
        "webhook_headers": {"type": dict, "default": {}},
    },
}


class ConfigError(Exception):
    """Raised when a configuration error is encountered."""

    pass


class ConfigManager:
    """Manages WiFiSense-CLI configuration.

    Handles loading, saving, validating, and accessing configuration
    values. Supports layered configuration: defaults are overridden by
    user configuration file, which can be further overridden by
    programmatic changes.

    Attributes:
        config_dir: Directory where configuration files are stored.
        config_path: Full path to the main configuration file.
        config: The active configuration dictionary.
    """

    def __init__(self, config_dir: Optional[str] = None) -> None:
        """Initialize the configuration manager.

        Args:
            config_dir: Path to the configuration directory. If None,
                       uses ~/.wifisense/ or the current directory.
        """
        if config_dir is None:
            # Try user home directory first, fall back to current dir
            home = os.path.expanduser("~")
            config_dir = os.path.join(home, ".wifisense")
            if not os.path.isdir(config_dir):
                config_dir = os.getcwd()

        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, "config.json")
        self.config: Dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)

        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)

        # Load user configuration if it exists
        self._load_user_config()

    def _load_user_config(self) -> None:
        """Load user configuration from the config file, merging with defaults."""
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                self.config = self._deep_merge(self.config, user_config)
            except (json.JSONDecodeError, IOError) as e:
                # Log warning but continue with defaults
                import sys
                print(
                    f"Warning: Failed to load config from {self.config_path}: {e}",
                    file=sys.stderr,
                )

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries. Override values take precedence.

        Args:
            base: The base dictionary.
            override: The override dictionary.

        Returns:
            A new dictionary with merged values.
        """
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get a configuration value using a dot-separated key path.

        Args:
            key_path: Dot-separated path (e.g., 'scanner.poll_interval').
            default: Default value if the key is not found.

        Returns:
            The configuration value, or default if not found.
        """
        keys = key_path.split(".")
        value: Any = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any) -> None:
        """Set a configuration value using a dot-separated key path.

        Args:
            key_path: Dot-separated path (e.g., 'scanner.poll_interval').
            value: The value to set.
        """
        keys = key_path.split(".")
        target = self.config
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value

    def get_section(self, section: str) -> Dict[str, Any]:
        """Get an entire configuration section.

        Args:
            section: The top-level section name.

        Returns:
            The section dictionary, or an empty dict if not found.
        """
        return self.config.get(section, {}).copy()

    def save(self, path: Optional[str] = None) -> None:
        """Save the current configuration to a JSON file.

        Args:
            path: Path to save to. If None, uses the default config path.

        Raises:
            ConfigError: If saving fails.
        """
        save_path = path or self.config_path
        try:
            os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except (IOError, OSError) as e:
            raise ConfigError(f"Failed to save configuration: {e}")

    def load(self, path: str) -> None:
        """Load configuration from a specific JSON file.

        Args:
            path: Path to the configuration file.

        Raises:
            ConfigError: If loading or parsing fails.
        """
        if not os.path.isfile(path):
            raise ConfigError(f"Configuration file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            self.config = copy.deepcopy(DEFAULT_CONFIG)
            self.config = self._deep_merge(self.config, user_config)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in configuration file: {e}")
        except IOError as e:
            raise ConfigError(f"Failed to read configuration file: {e}")

    def reset(self) -> None:
        """Reset configuration to default values."""
        self.config = copy.deepcopy(DEFAULT_CONFIG)

    def validate(self) -> List[str]:
        """Validate the current configuration against the schema.

        Returns:
            A list of validation error messages. Empty if valid.
        """
        errors: List[str] = []
        for section_name, section_schema in CONFIG_SCHEMA.items():
            if section_name not in self.config:
                errors.append(f"Missing section: {section_name}")
                continue
            section = self.config[section_name]
            if not isinstance(section, dict):
                errors.append(f"Section '{section_name}' must be a dictionary")
                continue
            for key_name, key_schema in section_schema.items():
                if key_name not in section:
                    continue  # Missing keys are filled by defaults
                value = section[key_name]
                expected_type = key_schema.get("type")
                # Type check
                if expected_type and not isinstance(value, expected_type):
                    if isinstance(expected_type, tuple):
                        if not any(isinstance(value, t) for t in expected_type):
                            errors.append(
                                f"{section_name}.{key_name}: "
                                f"expected {expected_type}, got {type(value).__name__}"
                            )
                    else:
                        errors.append(
                            f"{section_name}.{key_name}: "
                            f"expected {expected_type.__name__}, got {type(value).__name__}"
                        )
                # Range check for numeric values
                if isinstance(value, (int, float)):
                    min_val = key_schema.get("min")
                    max_val = key_schema.get("max")
                    if min_val is not None and value < min_val:
                        errors.append(
                            f"{section_name}.{key_name}: "
                            f"value {value} is below minimum {min_val}"
                        )
                    if max_val is not None and value > max_val:
                        errors.append(
                            f"{section_name}.{key_name}: "
                            f"value {value} is above maximum {max_val}"
                        )
        return errors

    def apply_defaults(self) -> None:
        """Fill in any missing configuration values with defaults."""
        for section_name, section_schema in CONFIG_SCHEMA.items():
            if section_name not in self.config:
                self.config[section_name] = {}
            section = self.config[section_name]
            for key_name, key_schema in section_schema.items():
                if key_name not in section:
                    section[key_name] = key_schema["default"]

    def export(self, path: str) -> None:
        """Export the current configuration to a specified file path.

        Args:
            path: Destination file path.
        """
        self.save(path)

    def to_dict(self) -> Dict[str, Any]:
        """Return a deep copy of the current configuration.

        Returns:
            A dictionary copy of the configuration.
        """
        return copy.deepcopy(self.config)

    def __repr__(self) -> str:
        return f"ConfigManager(config_dir={self.config_dir!r})"


def create_default_config(path: str) -> None:
    """Create a default configuration file at the specified path.

    Args:
        path: File path to write the default configuration to.
    """
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        f.write("\n")
