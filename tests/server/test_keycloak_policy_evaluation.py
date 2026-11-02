import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator


class Directory:
    enabled = True
    def _get(self, _path):
        return [{"clientId": "tr-resources", "id": "client"}]
    def user_by_identity_id(self, identity):
        return {"id": "subject", "enabled": self.enabled,
                "attributes": {"tr_identity_id": [identity]}}


def test_device_policy_evaluator_has_explicit_type_scope_and_complete_results():
    calls = []
    def request(_adapter, _client, payload):
        calls.append(payload)
        return {"results": [{"resource": {"_id": row["_id"]}, "scopes": row["scopes"],
            "status": "PERMIT" if row["_id"].endswith(":0") else "DENY",
            "allowedScopes": row["scopes"] if row["_id"].endswith(":0") else []}
            for row in payload["resources"]]}
    directory = Directory()
    evaluator = KeycloakPolicyEvaluator(allowed_kinds={"device"}, allowed_scopes={"use"},
        adapter=directory, settings={"authz_client_id": "tr-resources"}, protection_token="pat",
        resource_lookup=lambda _s, _p, kind, ref: {"_id": kind + ":" + ref}, request=request)
    values = evaluator.evaluate("stable", candidates=[("device", str(i), ("use",)) for i in range(33)])
    assert len(values) == 33 and values[("device", "0", "use")] is True
    assert values[("device", "1", "use")] is False
    assert [len(row["resources"]) for row in calls] == [32, 1]
    with pytest.raises(ValueError, match="candidate"):
        evaluator.evaluate("stable", candidates=[("research", "0", ("use",))])
    with pytest.raises(ValueError, match="candidate"):
        evaluator.evaluate("stable", candidates=[("device", "0", ("manage",))])
    directory.enabled = False
    with pytest.raises(AuthorizationUnavailable):
        evaluator.evaluate("stable", candidates=[("device", "0", ("use",))])
