from tools.cli.release import factor_workspace_mirror


def test_registered_repository_is_used_for_matching_principal(monkeypatch, tmp_path):
    repository = tmp_path / "factor-library"
    repository.mkdir()

    class Store:
        def __init__(self, _root):
            pass

        def load(self):
            return {
                "owner_ref": "GTHT@alice@123",
                "path": str(repository),
            }

    monkeypatch.setattr(factor_workspace_mirror, "CanonicalFactorRepoStore", Store)

    assert factor_workspace_mirror.existing_client_factor_workspace(
        "alice", client_root=tmp_path / "client",
    ) == repository.resolve()


def test_mismatched_or_missing_registration_is_not_mirrored(monkeypatch, tmp_path):
    class MismatchStore:
        def __init__(self, _root):
            pass

        def load(self):
            return {"owner_ref": "GTHT@bob@456", "path": str(tmp_path)}

    monkeypatch.setattr(
        factor_workspace_mirror, "CanonicalFactorRepoStore", MismatchStore,
    )
    assert factor_workspace_mirror.existing_client_factor_workspace(
        "alice", client_root=tmp_path / "client",
    ) is None

    class MissingStore(MismatchStore):
        def load(self):
            raise ValueError("canonical factor repo is not registered")

    monkeypatch.setattr(
        factor_workspace_mirror, "CanonicalFactorRepoStore", MissingStore,
    )
    assert factor_workspace_mirror.existing_client_factor_workspace(
        "alice", client_root=tmp_path / "client",
    ) is None
