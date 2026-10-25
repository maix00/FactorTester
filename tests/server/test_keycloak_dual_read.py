from scripts.migrations.keycloak_dual_read import compare_accounts


class Adapter:
    def user(self, username):
        class I:
            def __init__(self):
                self.username = username.lower()
                self.attributes = {"legacy_username": (username,), "legacy_role": ("user",)}
        return I()


def test_dual_read_reports_case_folding_and_roles():
    report = compare_accounts(
        [{"username": "Alice", "role": "user"}, {"username": "Bob", "role": "admin"}],
        Adapter(),
    )
    assert report["matched"] == ["Alice", "Bob"]
    assert report["case_folded"][0]["legacy"] == "Alice"
    assert report["role_mismatch"][0]["legacy"] == "Bob"
