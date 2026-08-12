"""Typed failures shared by Flask and Manager catalog routes."""


class ProductMarketDataError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
