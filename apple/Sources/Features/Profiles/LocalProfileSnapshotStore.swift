import Foundation

struct LocalProfileSnapshotStore {
    private let defaults: UserDefaults
    private let profileDirectory: URL
    private let cacheKey = "client.profile.list.cache.v1"

    init(defaults: UserDefaults, profileDirectory: URL?) {
        self.defaults = defaults
        self.profileDirectory = profileDirectory ?? Self.defaultDirectory()
    }

    /// Profile JSON is the same source-free local descriptor the CLI reads.
    /// It prevents a blank first render while the bundled CLI activates; the
    /// following CLI refresh remains authoritative.
    func hydrate() -> [[String: Any]] {
        let local = loadLocalFiles()
        if !local.isEmpty {
            cache(local)
            return local
        }
        guard let data = defaults.data(forKey: cacheKey),
              let value = try? JSONSerialization.jsonObject(with: data),
              let cached = value as? [[String: Any]] else {
            return []
        }
        return cached
    }

    /// A metadata-only fingerprint for cheap foreground observation. Profile
    /// publishers replace these small JSON descriptors after a new journal
    /// head is committed, so unchanged polls do not launch the CLI, read a
    /// database, or reopen the report.
    func fileFingerprint() -> String {
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: profileDirectory,
            includingPropertiesForKeys: [
                .contentModificationDateKey, .fileSizeKey,
                .fileResourceIdentifierKey,
            ],
            options: [.skipsHiddenFiles]
        ) else { return "missing" }
        return urls.filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
            .map { url in
                let values = try? url.resourceValues(forKeys: [
                    .contentModificationDateKey, .fileSizeKey,
                    .fileResourceIdentifierKey,
                ])
                return [
                    url.lastPathComponent,
                    String(values?.contentModificationDate?
                        .timeIntervalSince1970 ?? -1),
                    String(values?.fileSize ?? -1),
                    String(describing: values?.fileResourceIdentifier),
                ].joined(separator: "|")
            }
            .joined(separator: "\n")
    }

    func loadCurrentFiles() -> [[String: Any]] {
        loadLocalFiles()
    }

    func cache(_ values: [[String: Any]]) {
        guard JSONSerialization.isValidJSONObject(values),
              let data = try? JSONSerialization.data(
                  withJSONObject: values,
                  options: []
              ) else { return }
        defaults.set(data, forKey: cacheKey)
    }

    private func loadLocalFiles() -> [[String: Any]] {
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: profileDirectory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else { return [] }
        return urls
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
            .compactMap { url in
                guard let data = try? Data(contentsOf: url),
                      let value = try? JSONSerialization.jsonObject(with: data)
                        as? [String: Any] else { return nil }
                return value
            }
    }

    private static func defaultDirectory() -> URL {
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
}
