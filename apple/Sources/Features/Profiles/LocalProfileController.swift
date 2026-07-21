import Foundation

@MainActor
final class LocalProfileController: ObservableObject {
    @Published var profiles: [LocalProfileModel] = []
    @Published private(set) var isWorking = false
    @Published var error: String?
    @Published var lifecycleReceipt: ProfileLifecycleReceipt?
    var cliPath: String {
        ClientCLIResolution.executable()
    }

    func refresh() async {
        await perform {
            self.profiles = try await self.loadProfiles()
        }
    }

    func saveAgent(
        profileID: String,
        agentID: String,
        role: String,
        workspaceID: String,
        instanceID: String,
        branchID: String
    ) async {
        var arguments = [
            "client", "profile", "agent", "set", profileID,
            "--agent-id", agentID, "--role", role,
        ]
        if role == "planning" {
            arguments += ["--workspace-id", workspaceID]
        } else {
            arguments += [
                "--instance-id", instanceID, "--branch-id", branchID,
            ]
        }
        await run(arguments)
    }

    func saveAdapter(
        profileID: String,
        adapterID: String,
        enabled: Bool,
        credentialRef: String,
        configurationRef: String
    ) async {
        var arguments = [
            "client", "profile", "adapter", "set", profileID,
            "--adapter-id", adapterID,
            enabled ? "--enabled" : "--disabled",
        ]
        if !credentialRef.isEmpty {
            arguments += ["--credential-ref", credentialRef]
        }
        if !configurationRef.isEmpty {
            arguments += ["--configuration-ref", configurationRef]
        }
        await run(arguments)
    }

    func run(_ arguments: [String]) async {
        await perform {
            _ = try await ReleaseCommand.runObject(
                arguments,
                executable: self.cliPath
            )
            self.profiles = try await self.loadProfiles()
        }
    }

    func loadProfiles() async throws -> [LocalProfileModel] {
        let values = try await ReleaseCommand.runArray(
            ["client", "profile", "list"],
            executable: cliPath
        )
        return values.map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
    }

    func perform(
        _ operation: @escaping @MainActor () async throws -> Void
    ) async {
        isWorking = true
        error = nil
        defer { isWorking = false }
        do {
            try await operation()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
