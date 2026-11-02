from types import SimpleNamespace

import pytest

from scripts.test.keycloak_browser_oidc import verify_assistant_admission


def test_claim_and_real_transport_decision_are_both_required():
    role = 'agent_assistant:internal:use'
    calls = []
    def get(path):
        calls.append(path)
        return SimpleNamespace(status=200, json=lambda: {'success': True, 'claims': []})
    assert verify_assistant_admission({'keycloak_roles': [role]}, get, role) == 'assistant_location_permission'
    assert calls == ['/api/client/profile-claims']
    with pytest.raises(SystemExit, match='omitted'):
        verify_assistant_admission({'keycloak_roles': ['agent_assistant:use']}, get, role)
    assert len(calls) == 1
    with pytest.raises(SystemExit, match='HTTP 403'):
        verify_assistant_admission({'keycloak_roles': [role]},
            lambda _: SimpleNamespace(status=403), role)


def test_denial_requires_forbidden_instead_of_an_unavailable_service():
    assert verify_assistant_admission({}, lambda _: SimpleNamespace(status=403, json=lambda: {}),
        'denied') == 'assistant_denied'
    with pytest.raises(SystemExit, match='HTTP 503'):
        verify_assistant_admission({}, lambda _: SimpleNamespace(status=503), 'denied')
    with pytest.raises(ValueError, match='invalid'):
        verify_assistant_admission({}, lambda _: None, 'agent_assistant:use')
