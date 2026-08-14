"""Extract and verify node signatures from Manager HTTP requests."""

from __future__ import annotations

from server.manager.transfers.node_models import NodeIdentityRecord


NODE_ID_HEADER = "X-FactorTester-Node-ID"
CHALLENGE_HEADER = "X-FactorTester-Node-Challenge"
SIGNATURE_HEADER = "X-FactorTester-Node-Signature"


def authenticated_node(
    handler,
    *,
    method: str,
    body: bytes,
) -> NodeIdentityRecord:
    node_id = str(handler.headers.get(NODE_ID_HEADER) or "").strip()
    challenge = str(handler.headers.get(CHALLENGE_HEADER) or "").strip()
    signature = str(handler.headers.get(SIGNATURE_HEADER) or "").strip()
    if not node_id or not challenge or not signature:
        raise PermissionError("node authentication headers are required")
    return handler.state.node_authenticator.verify(
        node_id=node_id,
        challenge=challenge,
        signature=signature,
        method=method,
        path=handler.path,
        body=body,
    )
