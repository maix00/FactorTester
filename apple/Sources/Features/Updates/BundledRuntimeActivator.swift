import Foundation

enum BundledRuntimeActivator {
    static func run() async throws {
        try await coordinator.activate()
    }

    /// Profile refreshes can start at the same time as the app's launch task.
    /// They must wait for the one-file runtime activation rather than starting
    /// another cold process against the same bundled runtime directory.
    static func waitUntilReady() async throws {
        try await coordinator.activate()
    }

    private static let coordinator = BundledRuntimeActivationCoordinator(
        operation: performActivation
    )

    #if DEBUG
    // The test target uses this to verify coalescing without a packaged app.
    static func makeTestCoordinator(
        operation: @escaping @Sendable () async throws -> Void
    ) -> BundledRuntimeActivationCoordinator {
        BundledRuntimeActivationCoordinator(operation: operation)
    }
    #endif

    private static func performActivation() async throws {
        guard let bundled = ClientCLIResolution.bundledExecutable(
            resourceURL: Bundle.main.resourceURL,
            names: ["traderesearch", "factortester"],
            isExecutable: FileManager.default.isExecutableFile(atPath:)
        )
        else {
            throw BundledRuntimeActivationError.runtimeMissing
        }
        _ = try await ReleaseCommand.runObject(
            [
                "client",
                "activate-bundle",
                "--bundle-resources",
                bundled.resources.path,
                "--json",
            ],
            executable: bundled.executable.path
        )
    }
}

actor BundledRuntimeActivationCoordinator {
    private let operation: @Sendable () async throws -> Void
    private var activationTask: Task<Void, Error>?

    init(operation: @escaping @Sendable () async throws -> Void) {
        self.operation = operation
    }

    func activate() async throws {
        if let activationTask {
            return try await activationTask.value
        }

        let operation = operation
        let task = Task { try await operation() }
        activationTask = task
        do {
            try await task.value
        } catch {
            // A transient launch failure must not poison later retries.
            activationTask = nil
            throw error
        }
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
