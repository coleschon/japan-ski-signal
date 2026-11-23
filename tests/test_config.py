import pytest

from ski_signal.config import load_config, validate_config


def write_weights(tmp_path, contents):
    path = tmp_path / "weights.yaml"
    path.write_text(contents, encoding="utf-8")
    return path


def test_weights_normalize_to_fractions(monkeypatch):
    monkeypatch.delenv("WEIGHTS_PATH", raising=False)
    config = load_config()
    assert config["weights"] == pytest.approx({
        "snow": 0.45,
        "crowds_events": 0.20,
        "flights": 0.20,
        "lodging": 0.10,
        "yen": 0.05,
    })


def test_weights_accept_any_positive_scale_and_environment_path(tmp_path, monkeypatch):
    path = write_weights(
        tmp_path,
        "snow: 9\ncrowds_events: 4\nflights: 4\nlodging: 2\nyen: 1\n",
    )
    monkeypatch.setenv("WEIGHTS_PATH", str(path))

    assert load_config()["weights"] == pytest.approx({
        "snow": 0.45,
        "crowds_events": 0.20,
        "flights": 0.20,
        "lodging": 0.10,
        "yen": 0.05,
    })


def test_weights_argument_overrides_default(tmp_path, monkeypatch):
    monkeypatch.delenv("WEIGHTS_PATH", raising=False)
    path = write_weights(
        tmp_path,
        "snow: 1\ncrowds_events: 1\nflights: 1\nlodging: 1\nyen: 0\n",
    )

    assert load_config(weights_path=path)["weights"] == pytest.approx({
        "snow": 0.25,
        "crowds_events": 0.25,
        "flights": 0.25,
        "lodging": 0.25,
        "yen": 0.0,
    })


def test_weights_require_all_expected_keys(tmp_path):
    path = write_weights(
        tmp_path,
        "snow: 45\ncrowds_events: 20\nflights: 20\nlodging: 10\n",
    )
    with pytest.raises(ValueError, match="missing keys: yen"):
        load_config(weights_path=path)


def test_weights_reject_unknown_keys(tmp_path):
    path = write_weights(
        tmp_path,
        "snow: 45\ncrowds_events: 20\nflights: 20\nlodging: 10\nyen: 5\nextra: 1\n",
    )
    with pytest.raises(ValueError, match="unknown keys: extra"):
        load_config(weights_path=path)


def test_weights_reject_negative_values(tmp_path):
    path = write_weights(
        tmp_path,
        "snow: -1\ncrowds_events: 20\nflights: 20\nlodging: 10\nyen: 5\n",
    )
    with pytest.raises(ValueError, match="weights.snow"):
        load_config(weights_path=path)


def test_weights_reject_all_zero_values(tmp_path):
    path = write_weights(
        tmp_path,
        "snow: 0\ncrowds_events: 0\nflights: 0\nlodging: 0\nyen: 0\n",
    )
    with pytest.raises(ValueError, match="positive value"):
        load_config(weights_path=path)


def test_load_config_uses_email_environment_overrides(monkeypatch):
    monkeypatch.delenv("WEIGHTS_PATH", raising=False)
    monkeypatch.setenv("EMAIL_TO", "recipient@example.com")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")

    config = load_config()

    assert config["email_to"] == "recipient@example.com"
    assert config["email_from"] == "sender@example.com"
