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

    static func resolve(
        bundledPath: String?,
        configuredPath: String?,
        isExecutable: (String) -> Bool
    ) -> String {
        if let bundledPath, isExecutable(bundledPath) {
            return bundledPath
        }
        if let configuredPath, !configuredPath.isEmpty {
            return configuredPath
        }
        return "factortester"
    }
}
