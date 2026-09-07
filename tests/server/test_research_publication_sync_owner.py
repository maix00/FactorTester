from types import SimpleNamespace

import pytest

from server.manager.http import write_routes


@pytest.mark.parametrize("claimed_owner, status", [(None, 200), ("alice", 200), ("bob", 403)])
def test_loopback_agent_publication_uses_authenticated_owner(monkeypatch, claimed_owner, status):
    received = []
    responses = []

    class Handler(write_routes.WriteRoutesMixin):
        path = "/api/research-publications/sync"

        def __init__(self):
            self.state = SimpleNamespace(public_research=SimpleNamespace(sync=self.sync))

        def sync(self, payload):
            received.append(payload)
            return {}

        def _session(self):
            return {"username": "alice"}

        def _public_login_gate(self, *args, **kwargs):
            return True

        def _is_local_ftclient(self):
            return True

        def _json_body(self, maximum):
            payload = {"report_id": "report:v1:test"}
            if claimed_owner is not None:
                payload["owner_ref"] = claimed_owner
            return payload

        def __getattr__(self, name):
            # Unrelated dispatch routes are outside this request's scope.
            if name.startswith("_"):
                return lambda *args, **kwargs: False
            raise AttributeError(name)

    monkeypatch.setattr(write_routes, "json_response", lambda handler, payload, code=200: responses.append(code))
    Handler().do_POST()
    assert responses == [status]
    if status == 200:
        assert received[0]["owner_ref"] == "alice"
    else:
        assert received == []
