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
            var createArguments = [
                "client", "profile", "create",
                "--profile-id", id, "--display-name", name,
                "--server-url", serverURL,
                "--agent-id", agentID, "--role", role,
                "--principal-ref", principalRef,
            ]
            if let managerURL = ManagerConfig.shared.baseURL?.absoluteString {
                createArguments += ["--manager-url", managerURL]
            }
            let created = try await ReleaseCommand.runObject(
                createArguments, executable: self.cliPath
            )
            self.lifecycleReceipt = ProfileLifecycleReceipt(
                json: created, fallbackAction: "create"
            )
            try await self.refreshFromCLI()
        }
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
            try await self.refreshFromCLI()
        }
    }
}
