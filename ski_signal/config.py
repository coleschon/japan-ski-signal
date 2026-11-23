import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def validate_config(config: dict[str, Any]) -> None:
    weights = config.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise ValueError("config.weights must be a non-empty mapping")
    if any(not isinstance(value, (int, float)) for value in weights.values()):
        raise ValueError("config.weights values must be numeric")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("config.weights must sum to 1.0 within 1e-9")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    validate_config(config)
    for name in ("email_to", "email_from"):
        value = os.environ.get(name.upper())
        if value is not None:
            config[name] = value
    return config
