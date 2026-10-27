"""Testfixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Laat HA custom_components laden in alle tests."""
    yield
