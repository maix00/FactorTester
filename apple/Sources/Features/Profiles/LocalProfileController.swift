import Foundation

enum LocalProfileLoadState: Equatable {
    case idle
    case loading
    case loaded
    case failed
}

@MainActor
final class LocalProfileController: ObservableObject {
    @Published var profiles: [LocalProfileModel] = []
    @Published private(set) var isWorking = false
    @Published private(set) var loadState: LocalProfileLoadState = .loading
    @Published var error: String?
    @Published var lifecycleReceipt: ProfileLifecycleReceipt?
    private let snapshotStore: LocalProfileSnapshotStore
    private var localFileFingerprint: String
    private var refreshInFlight = false
    private static var sharedProfileListTask:
        Task<[[String: Any]], Error>?

    init(
        defaults: UserDefaults = .standard,
        profileDirectory: URL? = nil
    ) {
        let store = LocalProfileSnapshotStore(
            defaults: defaults,
            profileDirectory: profileDirectory
        )
        snapshotStore = store
        localFileFingerprint = store.fileFingerprint()
        profiles = store.hydrate().map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
    }
    var cliPath: String {
        ClientCLIResolution.executable()
    }

    func refresh() async {
        // SwiftUI can re-run a view task when the root scene changes from its
        // initial configuration screen to Home.  Coalesce that race so the
        // bundled one-file CLI is not cold-started twice on first launch.
        guard !refreshInFlight else { return }
        refreshInFlight = true
        loadState = .loading
        error = nil
        defer { refreshInFlight = false }
        do {
            try await refreshFromCLI()
        } catch {
            loadState = .failed
            self.error = error.localizedDescription
        }
    }

    func run(_ arguments: [String]) async {
        await perform {
            _ = try await ReleaseCommand.runObject(
                arguments,
                executable: self.cliPath
            )
            try await self.refreshFromCLI()
        }
    }

    func loadProfiles() async throws -> [LocalProfileModel] {
        (try await loadProfileValues()).map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
    }

    func refreshFromCLI() async throws {
        let values = try await loadProfileValues()
        profiles = values.map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
        snapshotStore.cache(values)
        localFileFingerprint = snapshotStore.fileFingerprint()
        loadState = .loaded
    }

    /// Refresh source-free local report descriptors only after a filesystem
    /// head change. This is the report hot path: no server request, CLI cold
    /// start, or database read occurs on an unchanged poll.
    @discardableResult
    func refreshLocalReportsIfChanged() -> Bool {
        let fingerprint = snapshotStore.fileFingerprint()
        guard fingerprint != localFileFingerprint else { return false }
        let values = snapshotStore.loadCurrentFiles()
        guard !values.isEmpty else { return false }
        profiles = values.map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
        snapshotStore.cache(values)
        localFileFingerprint = fingerprint
        loadState = .loaded
        return true
    }

    private func loadProfileValues() async throws -> [[String: Any]] {
        #if os(macOS)
        // The app activates the bundled one-file CLI from the root scene at
        // the same time that HomeView starts its Profile refresh.  Waiting on
        // the shared coordinator prevents two cold starts from racing over
        // the extracted runtime and makes the first refresh deterministic.
        try await BundledRuntimeActivator.waitUntilReady()
        #endif
        if let task = Self.sharedProfileListTask {
            return try await task.value
        }
        let executable = cliPath
        let task = Task {
            try await ReleaseCommand.runArray(
                ["client", "profile", "list"],
                executable: executable
            )
        }
        Self.sharedProfileListTask = task
        do {
            let values = try await task.value
            Self.sharedProfileListTask = nil
            return values
        } catch {
            Self.sharedProfileListTask = nil
            throw error
        }
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
            if loadState == .loading {
                loadState = .failed
            }
        }
    }
}
