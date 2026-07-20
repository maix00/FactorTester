import Foundation

enum BundledRuntimeActivator {
    static func run() async throws {
        guard let resources = Bundle.main.resourceURL?
            .appendingPathComponent("FactorTester"),
              let executable = Bundle.main.resourceURL?
                .appendingPathComponent("FactorTester/bin/factortester"),
              FileManager.default.isExecutableFile(atPath: executable.path)
        else {
            throw BundledRuntimeActivationError.runtimeMissing
        }
        _ = try await ReleaseCommand.runObject(
            [
                "client",
                "activate-bundle",
                "--bundle-resources",
                resources.path,
                "--json",
            ],
            executable: executable.path
        )
    }
}

enum BundledRuntimeActivationError: LocalizedError {
    case runtimeMissing

    var errorDescription: String? {
        switch self {
        case .runtimeMissing:
            return L10n.text("内嵌客户端运行时缺失。")
        }
    }
}
