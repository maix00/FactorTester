"""One-way migration of removed flat IC analysis settings."""

from .analyses import migrate_analysis_nodes

__all__ = ["migrate_analysis_nodes"]
