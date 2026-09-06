from server.manager.state.worktrees import WorktreeStateMixin


def test_fixed_service_uses_manager_release_even_when_feat_has_a_worktree(tmp_path):
    class State(WorktreeStateMixin):
        repo = tmp_path / "release"
        fixed_port = 7999
        fixed_branch = "feat"
        server_role = "feat"

        def _worktree_entries(self):
            return [
                {"worktree": str(tmp_path / "root"), "branch": "refs/heads/feat", "HEAD": "old"},
                {"worktree": str(self.repo), "branch": "refs/heads/main", "HEAD": "new"},
            ]

    owners = [item for item in State().worktrees() if item.port == 7999]
    assert len(owners) == 1
    assert owners[0].path == State.repo
    assert owners[0].head == "new"
