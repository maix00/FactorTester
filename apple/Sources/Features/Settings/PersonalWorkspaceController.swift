import Foundation

@MainActor
final class PersonalWorkspaceController: ObservableObject {
    @Published private(set) var localFactorLibrary: CanonicalFactorLibraryState?
    @Published private(set) var serverFactorLibrary: CanonicalFactorLibraryState?
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var cliPath: String { ClientCLIResolution.executable() }

    func clearServerState() {
        serverFactorLibrary = nil
        error = nil
    }

    func refresh(principal: String? = nil) async {
        await perform {
            let rootPath: String?
            if let principal, !principal.isEmpty {
                rootPath = try CanonicalFactorLibraryAccessStore.ensureDefault(
                    for: principal
                )
            } else {
                rootPath = CanonicalFactorLibraryAccessStore.rootPath
            }
            if let rootPath {
                let root = URL(fileURLWithPath: rootPath, isDirectory: true)
                let local = try await CanonicalFactorLibraryAccessStore.withAccess(to: root) {
                    try await ReleaseCommand.runObject([
                        "factor-library", "workspace", "local-state", root.path, "--json",
                    ], executable: self.cliPath)
                }
                self.localFactorLibrary = CanonicalFactorLibraryState(json: local, source: "local")
            } else {
                self.localFactorLibrary = nil
            }

            let server = try await ReleaseCommand.runObject([
                "factor-library", "workspace", "server-state", "--json",
            ], executable: self.cliPath)
            self.serverFactorLibrary = CanonicalFactorLibraryState(json: server, source: "server")
        }
    }

    func syncToServer(principal: String? = nil) async {
        await perform {
            _ = try self.ensureRoot(principal: principal)
            _ = try await ReleaseCommand.runObject([
                "factor-library", "workspace", "push", "--branch-mode", "auto", "--json",
            ], executable: self.cliPath)
            await self.refresh(principal: principal)
        }
    }

    func syncToLocal(principal: String? = nil) async {
        await perform {
            _ = try self.ensureRoot(principal: principal)
            _ = try await ReleaseCommand.runObject([
                "factor-library", "workspace", "sync", "--branch-mode", "force", "--json",
            ], executable: self.cliPath)
            await self.refresh(principal: principal)
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
