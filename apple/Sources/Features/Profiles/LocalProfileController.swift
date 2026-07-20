import Foundation

@MainActor
final class LocalProfileController: ObservableObject {
    @Published private(set) var profiles: [LocalProfileModel] = []
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var cliPath: String {
        UserDefaults.standard.string(
            forKey: "client.release.cliPath"
        ) ?? "factortester"
    }

    func refresh() async {
        await perform {
            self.profiles = try await self.loadProfiles()
        }
    }

    func saveProfile(
        id: String,
        name: String,
        serverURL: String,
        workspaceRoot: String
    ) async {
        await run([
            "client", "profile", "init",
            "--profile-id", id,
            "--display-name", name,
            "--server-url", serverURL,
            "--workspace-root", workspaceRoot,
        ])
    }

    func bootstrapProfile(
        id: String,
        name: String,
        serverURL: String,
        workspaceRoot: String,
        agentID: String,
        principalRef: String
    ) async {
        var arguments = [
            "client", "profile", "bootstrap",
            "--profile-id", id,
            "--display-name", name,
            "--server-url", serverURL,
            "--workspace-root", workspaceRoot,
            "--agent-id", agentID,
        ]
        arguments += ["--principal-ref", principalRef]
        await run(arguments)
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

    private func run(_ arguments: [String]) async {
        await perform {
            _ = try await ReleaseCommand.runObject(
                arguments,
                executable: self.cliPath
            )
            self.profiles = try await self.loadProfiles()
        }
    }

    private func loadProfiles() async throws -> [LocalProfileModel] {
        let values = try await ReleaseCommand.runArray(
            ["client", "profile", "list"],
            executable: cliPath
        )
        return values.map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
    }

    private func perform(
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
