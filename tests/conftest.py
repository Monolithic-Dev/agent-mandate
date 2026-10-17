import pytest
from fakes.world import World

from mandate.logging import configure_logging


@pytest.fixture(autouse=True)
def quiet_logs() -> None:
    """Keep decision logs out of test output; tests that need logs configure their own."""
    configure_logging("WARNING")


@pytest.fixture
def w() -> World:
    return World()
