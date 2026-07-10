from __future__ import annotations


class ReplSkin:
    """Small local skin compatible with CLI-Anything harness expectations."""

    def __init__(self, name: str, version: str = "0.1.0") -> None:
        self.name = name
        self.version = version

    def print_banner(self) -> None:
        print(f"{self.name} research harness v{self.version}")

    def info(self, message: str) -> None:
        print(f"* {message}")

    def success(self, message: str) -> None:
        print(f"OK {message}")

    def warning(self, message: str) -> None:
        print(f"WARN {message}")

    def error(self, message: str) -> None:
        print(f"ERR {message}")

    def status(self, key: str, value: object) -> None:
        print(f"{key}: {value}")
