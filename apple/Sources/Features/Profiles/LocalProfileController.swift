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
    private let defaults: UserDefaults
    private let profileDirectory: URL
    private let cacheKey = "client.profile.list.cache.v1"

    init(
        defaults: UserDefaults = .standard,
        profileDirectory: URL? = nil
    ) {
        self.defaults = defaults
        self.profileDirectory = profileDirectory ?? Self.defaultProfileDirectory()
        if let data = defaults.data(forKey: cacheKey),
           let value = try? JSONSerialization.jsonObject(with: data),
           let values = value as? [[String: Any]] {
            profiles = values.map(LocalProfileModel.init)
                .filter { !$0.id.isEmpty }
        }
        if profiles.isEmpty {
            hydrateFromLocalStore()
        }
    }
    var cliPath: String {
        ClientCLIResolution.executable()
    }

    func refresh() async {
        loadState = .loading
        error = nil
        do {
            try await refreshFromCLI()
        } catch {
            loadState = .failed
            self.error = error.localizedDescription
        }
    }

    func refreshUntilCheckpoint(
        profileID: String,
        checkpointRef: String,
        attempts: Int = 3
    ) async {
        for attempt in 0..<max(attempts, 1) {
            await refresh()
            let synchronized = profiles.first { $0.id == profileID }?
                .researchRecords.contains { $0.checkpointRef == checkpointRef }
                ?? false
            if synchronized || attempt == attempts - 1 { return }
            try? await Task.sleep(nanoseconds: 500_000_000)
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
        cacheProfileValues(values)
        loadState = .loaded
    }

    private func loadProfileValues() async throws -> [[String: Any]] {
        let values = try await ReleaseCommand.runArray(
            ["client", "profile", "list"],
            executable: cliPath
        )
        return values
    }

    private func cacheProfileValues(_ values: [[String: Any]]) {
        guard JSONSerialization.isValidJSONObject(values),
              let data = try? JSONSerialization.data(
                  withJSONObject: values,
                  options: []
              ) else { return }
        defaults.set(data, forKey: cacheKey)
    }

    /// Profile JSON is the same local source the CLI reads.  Hydrating this
    /// small, source-free descriptor synchronously prevents a first launch
    /// from rendering an empty directory while the bundled one-file CLI is
    /// still extracting and starting.  The CLI remains authoritative and
    /// refreshes the snapshot in the background.
    private func hydrateFromLocalStore() {
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: profileDirectory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else { return }
        let values = urls
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
            .compactMap { url -> [String: Any]? in
                guard let data = try? Data(contentsOf: url),
                      let value = try? JSONSerialization.jsonObject(with: data),
                      let object = value as? [String: Any] else { return nil }
                return object
            }
        guard !values.isEmpty else { return }
        profiles = values.map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
        cacheProfileValues(values)
    }

    private static func defaultProfileDirectory() -> URL {
        #if os(macOS)
        let root = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support")
        return root.appendingPathComponent("FactorTester/profiles")
        #else
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".local/share/factortester/profiles")
        #endif
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
