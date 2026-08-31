import Foundation

@MainActor
final class PersonalWorkspaceController: ObservableObject {
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var cliPath: String { ClientCLIResolution.executable() }

    func clearServerState() {
        error = nil
    }

    func refresh(principal: String? = nil) async {
        error = nil
    }

    func syncToServer(principal: String? = nil) async {
        await perform {
            _ = try self.ensureRoot(principal: principal)
            _ = try await ReleaseCommand.runObject([
                "factor-library", "workspace", "user", "upload", "--json",
            ], executable: self.cliPath)
        }
    }

    func syncToLocal(principal: String? = nil) async {
        await perform {
            _ = try self.ensureRoot(principal: principal)
            _ = try await ReleaseCommand.runObject([
                "factor-library", "workspace", "user", "download", "--json",
            ], executable: self.cliPath)
        }
    }

    private func ensureRoot(principal: String?) throws -> String {
        if let principal, !principal.isEmpty {
            return try CanonicalFactorLibraryAccessStore.ensureDefault(for: principal)
        }
        guard let rootPath = CanonicalFactorLibraryAccessStore.rootPath else {
            throw WorkspaceAccessError.required
        }
        return rootPath
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
