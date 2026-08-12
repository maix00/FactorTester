"""Stable Flask session secret for server restarts and client updates."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.data_dir import DATA_DIR


def load_session_secret() -> str:
    """Return the configured secret, persisting a generated one if needed.

    A process-random secret invalidates every browser and Swift client cookie
    whenever the server restarts.  The data directory is the server's durable
    state location, so the generated value belongs there rather than in the
    application bundle or a temporary directory.
    """
    configured = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if configured:
        return configured

    configured_path = os.environ.get("FACTORTESTER_SESSION_SECRET_FILE", "").strip()
    path = Path(configured_path).expanduser() if configured_path else Path(DATA_DIR) / "server-session-secret"
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = ""
    if value:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return value

    generated = os.urandom(32).hex()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Another server worker won the first-create race.  Use its value.
        return path.read_text(encoding="utf-8").strip()

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(generated)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return generated
