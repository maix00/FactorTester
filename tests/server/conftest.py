import pytest


@pytest.fixture(autouse=True)
def _restore_manager_handler_state():
    from server.manager import runtime as manager

    previous = manager.Handler.state
    try:
        yield
    finally:
        manager.Handler.state = previous
