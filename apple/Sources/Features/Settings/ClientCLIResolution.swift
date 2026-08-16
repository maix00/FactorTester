import Foundation

enum ClientCLIResolution {
    static func executable(
        bundle: Bundle = .main,
        defaults: UserDefaults = .standard,
        fileManager: FileManager = .default
    ) -> String {
        let bundled = bundle.resourceURL?
            .appendingPathComponent("FactorTester/bin/factortester")
            .path
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
        let bundled = bundle.resourceURL?
            .appendingPathComponent("FactorTester/bin/factortester-manager")
            .path
        return resolve(
            bundledPath: bundled,
            configuredPath: defaults.string(
                forKey: "client.release.managerCLIPath"
            ),
            isExecutable: fileManager.isExecutableFile(atPath:),
            fallback: "factortester-manager"
        )
    }

    static func resolve(
        bundledPath: String?,
        configuredPath: String?,
        isExecutable: (String) -> Bool,
        fallback: String = "factortester"
    ) -> String {
        if let bundledPath, isExecutable(bundledPath) {
            return bundledPath
        }
        if let configuredPath, !configuredPath.isEmpty {
            return configuredPath
        }
        return fallback
    }
}
