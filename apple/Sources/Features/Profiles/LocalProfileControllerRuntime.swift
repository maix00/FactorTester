import Foundation

extension LocalProfileController {
    func refresh(force: Bool = false) async {
        // The local descriptor is the same source-free record consumed by
        // the CLI. Do not cold-start the packaged Python runtime on every
        // Home/Profile view appearance; explicit refreshes remain authoritative.
        guard !refreshInFlight else { return }
        if !force && !profiles.isEmpty {
            loadState = .loaded
            return
        }
        refreshInFlight = true
        if profiles.isEmpty { loadState = .loading }
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
                arguments, executable: self.cliPath
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
        apply(values)
    }

    @discardableResult
    func refreshLocalReportsIfChanged() -> Bool {
        let fingerprint = snapshotStore.fileFingerprint()
        guard fingerprint != localFileFingerprint else { return false }
        let values = snapshotStore.loadCurrentFiles()
        guard !values.isEmpty else { return false }
        apply(values, fingerprint: fingerprint)
        return true
    }

    private func apply(
        _ values: [[String: Any]],
        fingerprint: String? = nil
    ) {
        profiles = values.map(LocalProfileModel.init)
            .filter { !$0.id.isEmpty }
        snapshotStore.cache(values)
        localFileFingerprint = fingerprint ?? snapshotStore.fileFingerprint()
        loadState = .loaded
    }

    func loadProfileValues() async throws -> [[String: Any]] {
        #if os(macOS)
        try await BundledRuntimeActivator.waitUntilReady()
        #endif
        if let task = Self.sharedProfileListTask {
            return try await task.value
        }
        let task = Task {
            try await ReleaseCommand.runArray(
                ["client", "profile", "list"], executable: self.cliPath
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
            if loadState == .loading { loadState = .failed }
        }
    }
}
