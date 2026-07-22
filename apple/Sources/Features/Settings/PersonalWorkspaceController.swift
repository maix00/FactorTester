import Foundation

@MainActor
final class PersonalWorkspaceController: ObservableObject {
    @Published private(set) var current: PersonalCanonicalWorkspace?
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var cliPath: String {
        ClientCLIResolution.executable()
    }

    func refresh(principal: String) async {
        guard !principal.isEmpty else { return }
        await perform {
            guard let rootPath = PersonalWorkspaceAccessStore.authorizedRootPath
            else {
                throw ResearchJournalError.workspaceAccessRequired
            }
            let root = URL(fileURLWithPath: rootPath, isDirectory: true)
            let value = try await PersonalWorkspaceAccessStore.withAccess(
                to: root
            ) {
                try await ReleaseCommand.runObject([
                    "client", "profile", "user-layout", "show",
                    "--principal", principal,
                ], executable: self.cliPath)
            }
            let canonical = value["canonical"] as? [String: Any] ?? [:]
            self.current = PersonalCanonicalWorkspace(
                json: canonical, principal: principal
            )
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
