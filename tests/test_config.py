import copy

import pytest

from ski_signal.config import load_config, validate_config


def test_weights_validation_raises_on_bad_sum():
    config = load_config()
    config = copy.deepcopy(config)
    config["weights"]["snow"] = 0.4
    with pytest.raises(ValueError, match="sum to 1.0"):
        validate_config(config)
