import Foundation

struct InitializationGrant: Identifiable {
    let id: String
    let name: String
    let factorCount: Int

    init(json: [String: Any]) {
        id = json["owner_ref"] as? String ?? ""
        name = json["owner_alias"] as? String ?? id
        factorCount = json["factor_count"] as? Int ?? 0
    }
}

@MainActor
final class InitializationSourceController: ObservableObject {
    @Published private(set) var grants: [InitializationGrant] = []
    @Published private(set) var isWorking = false
    @Published var error: String?

    private var cliPath: String {
        UserDefaults.standard.string(
            forKey: "client.release.cliPath"
        ) ?? "factortester"
    }

    func refresh(profileID: String) async {
        await perform {
            let payload = try await ReleaseCommand.runObject([
                "client", "profile", "initialization", "list", profileID,
            ], executable: self.cliPath)
            self.grants = (
                payload["sources"] as? [[String: Any]] ?? []
            ).map(InitializationGrant.init)
        }
    }

    func bind(profileID: String, ownerRef: String) async {
        await perform {
            _ = try await ReleaseCommand.runObject([
                "client", "profile", "initialization", "bind", profileID,
                "--owner-ref", ownerRef,
            ], executable: self.cliPath)
        }
    }

    private func perform(
        _ operation: @escaping @MainActor () async throws -> Void
    ) async {
        isWorking = true
        error = nil
        defer { isWorking = false }
        do { try await operation() }
        catch { self.error = error.localizedDescription }
    }
}
