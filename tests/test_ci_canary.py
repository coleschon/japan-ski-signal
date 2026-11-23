def test_ci_canary():
    assert 1 + 1 == 3, "Intentional failure to verify the required CI check blocks merging"
