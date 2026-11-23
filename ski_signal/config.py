import math
import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "weights.yaml"
WEIGHT_KEYS = ("snow", "crowds_events", "flights", "lodging", "yen")


def validate_config(config: dict[str, Any]) -> None:
    weights = config.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise ValueError("config.weights must be a non-empty mapping")
    if any(not isinstance(value, (int, float)) for value in weights.values()):
        raise ValueError("config.weights values must be numeric")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("config.weights must sum to 1.0 within 1e-9")


def _load_weights(path: str | Path) -> dict[str, float]:
    with Path(path).open(encoding="utf-8") as weights_file:
        weights = yaml.safe_load(weights_file)
    if not isinstance(weights, dict):
        raise ValueError("weights.yaml must be a mapping")
    keys = set(weights)
    expected = set(WEIGHT_KEYS)
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown keys: {', '.join(unknown)}")
        raise ValueError(f"Invalid weights.yaml: {'; '.join(problems)}")
    for key, value in weights.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise ValueError(f"weights.{key} must be a non-negative number")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive value")
    return {key: weights[key] / total for key in WEIGHT_KEYS}


def load_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    weights_path: str | Path | None = None,
) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    selected_weights_path = weights_path or os.environ.get("WEIGHTS_PATH") or DEFAULT_WEIGHTS_PATH
    config["weights"] = _load_weights(selected_weights_path)
    validate_config(config)
    for name in ("email_to", "email_from"):
        config[name] = os.environ.get(name.upper())
    return config
