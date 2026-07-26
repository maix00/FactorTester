import Foundation

@MainActor
final class PersonalWorkspaceController: ObservableObject {
    @Published private(set) var localFactorLibrary: CanonicalFactorLibraryState?
    @Published private(set) var serverFactorLibrary: CanonicalFactorLibraryState?
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var cliPath: String { ClientCLIResolution.executable() }

    func refresh() async {
        await perform {
            if let rootPath = CanonicalFactorLibraryAccessStore.rootPath {
                let root = URL(fileURLWithPath: rootPath, isDirectory: true)
                let local = try await CanonicalFactorLibraryAccessStore.withAccess(to: root) {
                    try await ReleaseCommand.runObject([
                        "custom_factors", "workspace", "local-state", root.path, "--json",
                    ], executable: self.cliPath)
                }
                self.localFactorLibrary = CanonicalFactorLibraryState(json: local, source: "local")
            } else {
                self.localFactorLibrary = nil
            }

            let server = try await ReleaseCommand.runObject([
                "custom_factors", "workspace", "server-state", "--json",
            ], executable: self.cliPath)
            self.serverFactorLibrary = CanonicalFactorLibraryState(json: server, source: "server")
        }
    }

    func syncToServer() async {
        guard let rootPath = CanonicalFactorLibraryAccessStore.rootPath else {
            error = "请先选择本地 canonical 因子库目录"
            return
        }
        await perform {
            let root = URL(fileURLWithPath: rootPath, isDirectory: true)
            _ = try await CanonicalFactorLibraryAccessStore.withAccess(to: root) {
                try await ReleaseCommand.runObject([
                    "custom_factors", "workspace", "sync-to-server", root.path, "--json",
                ], executable: self.cliPath)
            }
            await self.refresh()
        }
    }

    func syncToLocal() async {
        guard let rootPath = CanonicalFactorLibraryAccessStore.rootPath else {
            error = "请先选择本地 canonical 因子库目录"
            return
        }
        await perform {
            let root = URL(fileURLWithPath: rootPath, isDirectory: true)
            _ = try await CanonicalFactorLibraryAccessStore.withAccess(to: root) {
                try await ReleaseCommand.runObject([
                    "custom_factors", "workspace", "sync-to-local", root.path, "--json",
                ], executable: self.cliPath)
            }
            await self.refresh()
        }
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
