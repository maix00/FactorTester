import Foundation

struct ManagerWorktree: Identifiable {
    let instanceId: String
    let label: String
    let branch: String
    let port: Int
    let running: Bool
    let daemonRunning: Bool
    let portInUse: Bool

    var id: String { instanceId }

    init(json: [String: Any]) {
        instanceId = json["instance_id"] as? String ?? ""
        label = json["label"] as? String ?? instanceId
        branch = json["branch"] as? String ?? ""
        port = json["port"] as? Int ?? 0
        running = json["running"] as? Bool ?? false
        daemonRunning = json["daemon_running"] as? Bool ?? false
        portInUse = json["port_in_use"] as? Bool ?? false
    }
}

protocol ManagerSessionAPI {
    func login(username: String, password: String) async throws
    func restoreSession() async throws -> Bool
    func logout() async
}

enum ManagerAction: String {
    case start
    case stop
    case restartWeb = "restart-web"
    case restartAll = "restart-all"
    case forceStop = "force-stop"
}

final class ManagerCLIClient: ManagerSessionAPI {
    static let shared = ManagerCLIClient()

    private var executable: String { ClientCLIResolution.executable() }

    func configure(scheme: String, host: String, port: String) async throws {
        _ = try await ReleaseCommand.runObject([
            "manager", "configure",
            "--scheme", scheme,
            "--host", host,
            "--port", port,
            "--json",
        ], executable: executable)
    }

    func login(username: String, password: String) async throws {
        _ = try await ReleaseCommand.runObject([
            "manager", "login",
            "--username", username,
            "--credentials-stdin",
            "--json",
        ], executable: executable, stdinJSON: [
            "username": username,
            "password": password,
        ])
    }

    func restoreSession() async throws -> Bool {
        _ = try await ReleaseCommand.runObject([
            "manager", "status", "--json",
        ], executable: executable)
        return true
    }

    func logout() async {
        _ = try? await ReleaseCommand.runObject([
            "manager", "logout", "--json",
        ], executable: executable)
    }

    func worktrees() async throws -> [ManagerWorktree] {
        let value = try await ReleaseCommand.runObject([
            "manager", "list", "--json",
        ], executable: executable)
        return (value["worktrees"] as? [[String: Any]] ?? []).map(
            ManagerWorktree.init(json:)
        )
    }

    /// Manager 的服务顺序是端口发现的唯一来源；客户端不维护手工端口列表。
    /// main/feat 优先，其余运行中的服务按 Manager 返回的端口稳定排序。
    func availableServicePorts() async throws -> [Int] {
        let items = try await worktrees().filter { item in
            item.running && (1...65535).contains(item.port)
        }
        return items.sorted { lhs, rhs in
            let left = servicePriority(lhs)
            let right = servicePriority(rhs)
            if left != right { return left < right }
            return lhs.port < rhs.port
        }.map(\.port)
    }

    private func servicePriority(_ item: ManagerWorktree) -> Int {
        let text = "\(item.label) \(item.branch)".lowercased()
        if text.contains("main") { return 0 }
        if text.contains("feat") { return 1 }
        return 2
    }

    func perform(_ action: ManagerAction, port: Int) async throws {
        guard (1...65535).contains(port) else {
            throw ManagerClientError.invalidPort(port)
        }
        var arguments = [
            "manager", action.rawValue, String(port), "--json",
        ]
        if action == .forceStop {
            arguments.append("--yes")
        }
        _ = try await ReleaseCommand.runObject(
            arguments,
            executable: executable
        )
    }
}

private enum ManagerClientError: LocalizedError {
    case invalidPort(Int)

    var errorDescription: String? {
        switch self {
        case .invalidPort(let port):
            return L10n.format("无效的服务端口：%lld", port)
        }
    }
}
