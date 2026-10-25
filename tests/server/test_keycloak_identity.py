from server.identity.keycloak import (
    Identity, InMemoryKeycloak, group_subject, organization_subject, permission_subjects, user_subject,
)


def test_nested_group_and_org_membership():
    adapter = InMemoryKeycloak([
        Identity("alice", groups=("team/a/sub",), organizations=("org-a",)),
        Identity("bob", groups=("team/b",)),
    ])
    assert [u.username for u in adapter.group_members("team/a")] == ["alice"]
    assert [u.username for u in adapter.organization_members("org-a")] == ["alice"]
    assert user_subject("alice") == "user:alice"
    assert group_subject("/team/a/") == "group:team/a"
    assert permission_subjects(adapter.user("alice"))[0] == "user:alice"
    assert organization_subject("org-a") == "org:org-a"


def test_oidc_authorization_url_contains_state_and_redirect():
    from server.identity.keycloak import oidc_authorization_url
    url = oidc_authorization_url(
        base_url="https://id.example", realm="trade", client_id="web",
        redirect_uri="https://app.example/callback", state="s1",
    )
    assert url.startswith("https://id.example/realms/trade/protocol/openid-connect/auth?")
    assert "state=s1" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example%2Fcallback" in url
