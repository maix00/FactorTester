import Foundation

enum ClientCLIResolution {
    struct BundledExecutable {
        let resources: URL
        let executable: URL
    }

    /// Keep the executable and its receipt under the same bundle root.
    /// Legacy paths are read only for upgrades from previously shipped apps.
    static func bundledExecutable(
        resourceURL: URL?,
        names: [String],
        isExecutable: (String) -> Bool
    ) -> BundledExecutable? {
        guard let resourceURL else { return nil }
        for directory in ["TradeResearch", "FactorTester"] {
            let resources = resourceURL.appendingPathComponent(directory, isDirectory: true)
            for name in names {
                let executable = resources.appendingPathComponent("bin/\(name)")
                if isExecutable(executable.path) {
                    return BundledExecutable(resources: resources, executable: executable)
                }
            }
        }
        return nil
    }

    static func executable(
        bundle: Bundle = .main,
        defaults: UserDefaults = .standard,
        fileManager: FileManager = .default
    ) -> String {
        let bundled = bundledExecutable(resourceURL: bundle.resourceURL,
            names: ["traderesearch", "factortester"],
            isExecutable: fileManager.isExecutableFile(atPath:))?.executable.path
        return resolve(
            bundledPath: bundled,
            configuredPath: defaults.string(
                forKey: "client.release.cliPath"
            ),
            isExecutable: fileManager.isExecutableFile(atPath:)
        )
    }

    static func managerExecutable(
        bundle: Bundle = .main,
        defaults: UserDefaults = .standard,
        fileManager: FileManager = .default
    ) -> String {
        let bundled = bundledExecutable(resourceURL: bundle.resourceURL,
            names: ["traderesearch-manager", "factortester-manager"],
            isExecutable: fileManager.isExecutableFile(atPath:))?.executable.path
        return resolve(
            bundledPath: bundled,
            configuredPath: defaults.string(
                forKey: "client.release.managerCLIPath"
            ),
            isExecutable: fileManager.isExecutableFile(atPath:),
            fallback: "traderesearch-manager"
        )
    }

    static func resolve(
        bundledPath: String?,
        configuredPath: String?,
        isExecutable: (String) -> Bool,
        fallback: String = "traderesearch"
    ) -> String {
        if let bundledPath, isExecutable(bundledPath) {
            return bundledPath
        }
        if let configuredPath, !configuredPath.isEmpty {
            return configuredPath
        }
        return fallback
    }

    static func firstExecutable(
        _ candidates: [String?],
        isExecutable: (String) -> Bool
    ) -> String? {
        candidates.compactMap { $0 }.first(where: isExecutable)
    }
}
