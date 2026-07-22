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
