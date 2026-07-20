import Foundation

@MainActor
final class WorkspaceRepairController: ObservableObject {
    @Published private(set) var plan: [String: Any]?
    @Published private(set) var repairID = ""
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var planURL: URL?
    private var cliPath: String {
        UserDefaults.standard.string(
            forKey: "client.release.cliPath"
        ) ?? "factortester"
    }

    func preview(profileID: String, workspaceID: String) async {
        await perform {
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(
                "factortester-repair-\(profileID)-\(UUID().uuidString).json"
            )
            self.plan = try await ReleaseCommand.runObject([
                "client", "profile", "workspace", "repair-plan",
                profileID, workspaceID, "--output", url.path,
            ], executable: self.cliPath)
            self.planURL = url
        }
    }

    func apply() async {
        guard let planURL else { return }
        await perform {
            let receipt = try await ReleaseCommand.runObject([
                "client", "profile", "workspace", "repair-apply",
                planURL.path,
            ], executable: self.cliPath)
            self.repairID = receipt["repair_id"] as? String ?? ""
        }
    }

    func verify(profileID: String) async {
        guard !repairID.isEmpty else { return }
        await perform {
            let result = try await ReleaseCommand.runObject([
                "client", "profile", "workspace", "repair-verify",
                profileID, self.repairID,
            ], executable: self.cliPath)
            guard result["valid"] as? Bool == true else {
                throw CocoaError(.fileReadCorruptFile)
            }
        }
    }

    func rollback(profileID: String) async {
        guard !repairID.isEmpty else { return }
        await perform {
            _ = try await ReleaseCommand.runObject([
                "client", "profile", "workspace", "repair-rollback",
                profileID, self.repairID,
            ], executable: self.cliPath)
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
