import Foundation

@MainActor
final class PersonalWorkspaceController: ObservableObject {
    @Published private(set) var current: PersonalCanonicalWorkspace?
    @Published private(set) var plan: PersonalWorkspaceMigrationPlan?
    @Published private(set) var receipt: PersonalWorkspaceReceipt?
    @Published private(set) var verificationStatus = ""
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var principal = ""
    private var planURL: URL?
    private var cliPath: String {
        UserDefaults.standard.string(forKey: "client.release.cliPath")
            ?? "factortester"
    }

    func refresh(principal: String) async {
        self.principal = principal
        guard !principal.isEmpty else { return }
        await perform {
            let value = try await ReleaseCommand.runObject([
                "client", "profile", "personal-workspace", "show",
                "--principal", principal,
            ], executable: self.cliPath)
            self.current = PersonalCanonicalWorkspace(json: value)
        }
    }

    func register(path: String, ownerRef: String) async {
        guard !path.isEmpty, !ownerRef.isEmpty else { return }
        principal = ownerRef
        await perform {
            let value = try await ReleaseCommand.runObject([
                "client", "profile", "factor-worktree", "canonical-register",
                "--path", path, "--owner-ref", ownerRef,
            ], executable: self.cliPath)
            self.current = PersonalCanonicalWorkspace(json: value)
        }
    }

    func previewMigration(target: String) async {
        guard !principal.isEmpty, !target.isEmpty else { return }
        await perform {
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent(
                    "factortester-personal-workspace-\(UUID().uuidString).json"
                )
            let value = try await ReleaseCommand.runObject([
                "client", "profile", "personal-workspace", "migration", "plan",
                "--principal", self.principal,
                "--target", target,
                "--output", url.path,
            ], executable: self.cliPath)
            self.plan = PersonalWorkspaceMigrationPlan(json: value)
            self.planURL = url
            self.receipt = nil
            self.verificationStatus = ""
        }
    }

    func applyMigration() async {
        guard let planURL else { return }
        await perform {
            let value = try await ReleaseCommand.runObject([
                "client", "profile", "personal-workspace", "migration", "apply",
                planURL.path,
            ], executable: self.cliPath)
            self.receipt = PersonalWorkspaceReceipt(json: value)
        }
    }

    func verifyMigration() async {
        guard let receipt, !receipt.id.isEmpty else { return }
        await perform {
            let value = try await ReleaseCommand.runObject([
                "client", "profile", "personal-workspace", "migration", "verify",
                receipt.id,
            ], executable: self.cliPath)
            self.verificationStatus = value.string("status")
            let current = try await ReleaseCommand.runObject([
                "client", "profile", "personal-workspace", "show",
                "--principal", self.principal,
            ], executable: self.cliPath)
            self.current = PersonalCanonicalWorkspace(json: current)
        }
    }

    private func perform(
        _ operation: @escaping @MainActor () async throws -> Void
    ) async {
        isWorking = true
        error = nil
        defer { isWorking = false }
        do { try await operation() }
        catch { self.error = error.localizedDescription }
    }
}
