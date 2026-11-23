import copy

import pytest

from ski_signal.config import load_config, validate_config


def test_weights_validation_raises_on_bad_sum():
    config = load_config()
    config = copy.deepcopy(config)
    config["weights"]["snow"] = 0.4
    with pytest.raises(ValueError, match="sum to 1.0"):
        validate_config(config)


def test_load_config_uses_email_environment_overrides(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "recipient@example.com")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")

    config = load_config()

    assert config["email_to"] == "recipient@example.com"
    assert config["email_from"] == "sender@example.com"
