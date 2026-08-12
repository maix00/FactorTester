"""Legacy import path for Manager authentication page helpers.

New server-side code imports these names from ``server.manager.http.pages``;
this module remains so older deployment scripts and third-party integrations
do not break during the incremental Manager refactor.
"""

from server.manager.http.pages import (
    PUBLIC_DEVICE_COMPLIANCE_NOTICE,
    PUBLIC_REGISTRATION_NOTICE,
    compliance_page,
    device_gate_page,
    login_page,
    safe_login_next,
)

__all__ = [
    "PUBLIC_DEVICE_COMPLIANCE_NOTICE",
    "PUBLIC_REGISTRATION_NOTICE",
    "compliance_page",
    "device_gate_page",
    "login_page",
    "safe_login_next",
]
