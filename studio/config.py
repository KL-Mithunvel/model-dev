"""Load ``config.yaml``. Every tunable is read from here, never hard-coded elsewhere."""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class ConfigError(Exception):
    """Raised when the configuration file is missing or malformed."""


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Return the parsed configuration as a dict.

    Raises:
        ConfigError: the file does not exist, is not valid YAML, or is not a mapping.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as error:
        raise ConfigError(f"Config file is not valid YAML: {config_path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain a mapping at the top level: {config_path}")
    return data
