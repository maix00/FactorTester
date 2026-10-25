from scripts.migrations.keycloak_import_accounts import import_accounts


class Fake:
    def create_user(self, **kwargs):
        assert kwargs["username"]
        return "id-" + kwargs["username"]


def test_import_is_dry_run_safe_and_skips_duplicates():
    accounts = [{"username": "alice"}, {"username": "bob"}]

    class Dup(Fake):
        def create_user(self, **kwargs):
            if kwargs["username"] == "bob":
                raise ValueError("Keycloak user already exists")
            return super().create_user(**kwargs)

    assert import_accounts(accounts, None, dry_run=True)["created"] == ["alice", "bob"]
    result = import_accounts(accounts, Dup(), dry_run=False)
    assert result["created"][0]["username"] == "alice"
    assert result["skipped"][0]["username"] == "bob"
