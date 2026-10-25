import pytest


@pytest.fixture(autouse=True)
def _restore_manager_handler_state():
    from server.manager import runtime as manager

    had_state = hasattr(manager.Handler, "state")
    previous = getattr(manager.Handler, "state", None)
    try:
        yield
    finally:
        if had_state:
            manager.Handler.state = previous
        elif hasattr(manager.Handler, "state"):
            del manager.Handler.state
