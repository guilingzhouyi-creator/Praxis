"""Shared fixtures for infra slice tests.

Deterministic ordering: the pytest-random-order plugin shuffles tests by
default, causing cross-test state pollution in githooks and local-merge
scratch-repo suites. Pinning to seed=0 ensures reproducible runs while
still exercising the full test set.
"""


def pytest_configure(config):
    """Pin random-order seed to 0 for deterministic infra test execution."""
    plugin = config.pluginmanager.get_plugin("random_order")
    if plugin:
        # Re-shuffle with a fixed seed so failures are reproducible.
        config.option.random_order_seed = "0"
