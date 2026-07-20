import Combine
import Foundation

@MainActor
final class ClientReleaseController: ObservableObject {
    private enum Keys {
        static let profilePath = "client.release.profilePath"
        static let cliPath = "client.release.cliPath"
    }

    @Published var profilePath: String {
        didSet {
            UserDefaults.standard.set(profilePath, forKey: Keys.profilePath)
        }
    }
    @Published var cliPath: String {
        didSet {
            UserDefaults.standard.set(cliPath, forKey: Keys.cliPath)
        }
    }
    @Published private(set) var installedVersion = ""
    @Published private(set) var latestVersion = ""
    @Published private(set) var compatible: Bool?
    @Published private(set) var healthy: Bool?
    @Published private(set) var isWorking = false
    @Published var lastError: String?

    init() {
        profilePath = UserDefaults.standard.string(
            forKey: Keys.profilePath
        ) ?? ""
        cliPath = UserDefaults.standard.string(forKey: Keys.cliPath)
            ?? "factortester"
    }

    func refresh() async {
        await perform {
            let status = try await ReleaseCommand.run(
                self.arguments(command: "status", needsProfile: false),
                executable: self.cliPath
            )
            self.installedVersion = status.string("current_version")
            self.healthy = status.bool("healthy")
            guard !self.profilePath.isEmpty else {
                self.latestVersion = ""
                self.compatible = nil
                return
            }
            let plan = try await ReleaseCommand.run(
                self.arguments(command: "update", extra: ["--dry-run"]),
                executable: self.cliPath
            )
            self.latestVersion = plan.string("target_version")
            self.compatible = true
        }
    }

    func bootstrap() async {
        await mutate("bootstrap")
    }

    func update() async {
        await mutate("update")
    }

    func rollback() async {
        await mutate("rollback")
    }

    private func mutate(_ command: String) async {
        guard !profilePath.isEmpty else {
            lastError = "请先选择客户端 profile。"
            return
        }
        await perform {
            _ = try await ReleaseCommand.run(
                self.arguments(command: command),
                executable: self.cliPath
            )
            await self.refresh()
        }
    }

    private func arguments(
        command: String,
        needsProfile: Bool = true,
        extra: [String] = []
    ) -> [String] {
        var value = ["client", command]
        if needsProfile || !profilePath.isEmpty {
            value += ["--profile", profilePath]
        }
        return value + extra + ["--json"]
    }

    private func perform(
        _ operation: @escaping @MainActor () async throws -> Void
    ) async {
        isWorking = true
        lastError = nil
        defer { isWorking = false }
        do {
            try await operation()
        } catch {
            compatible = false
            lastError = error.localizedDescription
        }
    }
}
