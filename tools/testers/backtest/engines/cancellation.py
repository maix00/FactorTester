"""Shared cooperative cancellation contract for backtest execution."""


class BacktestCancelled(RuntimeError):
    """Raised when a user cancels an active backtest run."""

    def __init__(self, message: str = "回测已由用户取消") -> None:
        super().__init__(message)
