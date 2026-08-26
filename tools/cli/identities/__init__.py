"""Frozen business-identity protocols shared by the installed CLI and server."""

from .base import identity_registry, require_identity_envelope

__all__ = ["identity_registry", "require_identity_envelope"]
