import Foundation

extension LocalProfileController {
    func createIsolatedProfile(
        id: String,
        name: String,
        serverURL: String,
        agentID: String,
        role: String,
        principalRef: String
    ) async {
        await perform {
            let created = try await ReleaseCommand.runObject([
                "client", "profile", "create",
                "--profile-id", id, "--display-name", name,
                "--server-url", serverURL,
                "--agent-id", agentID, "--role", role,
                "--principal-ref", principalRef,
            ], executable: self.cliPath)
            let planURL = FileManager.default.temporaryDirectory
                .appendingPathComponent("factor-worktree-\(UUID()).json")
            defer { try? FileManager.default.removeItem(at: planURL) }
            _ = try await ReleaseCommand.runObject([
                "client", "profile", "factor-worktree", "plan", id,
                "--output", planURL.path,
            ], executable: self.cliPath)
            _ = try await ReleaseCommand.runObject([
                "client", "profile", "factor-worktree", "apply", planURL.path,
            ], executable: self.cliPath)
            self.lifecycleReceipt = ProfileLifecycleReceipt(
                json: created, fallbackAction: "create"
            )
            self.profiles = try await self.loadProfiles()
        }
    }

    func unbindFactorWorkspace(_ profile: LocalProfileModel) async {
        guard let binding = profile.factorWorkspaceBinding else { return }
        await lifecycle([
            "client", "profile", "factor-worktree", "rollback",
            profile.id, binding.id,
        ], action: "unbind")
    }

    func deactivateProfile(_ profileID: String) async {
        await lifecycle([
            "client", "profile", "deactivate", profileID,
        ], action: "deactivate")
    }

    func purgeProfile(_ profileID: String) async {
        await lifecycle([
            "client", "profile", "purge", profileID,
        ], action: "purge")
    }

    private func lifecycle(_ arguments: [String], action: String) async {
        await perform {
            let value = try await ReleaseCommand.runObject(
                arguments, executable: self.cliPath
            )
            self.lifecycleReceipt = ProfileLifecycleReceipt(
                json: value, fallbackAction: action
            )
            self.profiles = try await self.loadProfiles()
        }
    }
}
