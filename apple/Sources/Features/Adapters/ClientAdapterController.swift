import Combine
import Foundation

@MainActor
final class ClientAdapterController: ObservableObject {
    @Published private(set) var adapters: [ClientAdapterModel] = []
    @Published private(set) var isWorking = false
    @Published var error: String?
    @Published var openTarget: ClientAdapterModel?

    private var cliPath: String {
        UserDefaults.standard.string(
            forKey: "client.release.cliPath"
        ) ?? "factortester"
    }

    private var releaseProfilePath: String {
        UserDefaults.standard.string(
            forKey: "client.release.profilePath"
        ) ?? ""
    }

    private var localProfileID: String {
        UserDefaults.standard.string(
            forKey: "client.profile.activeID"
        ) ?? ""
    }

    func refresh() async {
        await perform {
            self.adapters = try await self.loadAdapters()
        }
    }

    func toggle(_ adapter: ClientAdapterModel) async {
        await perform {
            let action = adapter.running ? "stop" : "start"
            _ = try await ReleaseCommand.runObject(
                self.arguments(["adapter", action, adapter.id]),
                executable: self.cliPath
            )
            self.adapters = try await self.loadAdapters()
        }
    }

    func open(_ adapter: ClientAdapterModel) async {
        guard adapter.uiURL != nil else {
            error = "该组件没有声明可嵌入的本地 Web UI。"
            return
        }
        await perform {
            if !adapter.running {
                _ = try await ReleaseCommand.runObject(
                    self.arguments(["adapter", "start", adapter.id]),
                    executable: self.cliPath
                )
            }
            self.adapters = try await self.loadAdapters()
            self.openTarget = self.adapters.first { $0.id == adapter.id }
                ?? adapter
        }
    }

    private func loadAdapters() async throws -> [ClientAdapterModel] {
        let values = try await ReleaseCommand.runArray(
            arguments(["adapter", "list"]),
            executable: cliPath
        )
        return values.map(ClientAdapterModel.init)
            .filter { !$0.id.isEmpty }
    }

    private func arguments(_ tail: [String]) -> [String] {
        var value = ["client"] + tail
        if !releaseProfilePath.isEmpty {
            value += ["--release-profile", releaseProfilePath]
        }
        if !localProfileID.isEmpty {
            value += ["--profile-id", localProfileID]
        }
        return value
    }

    private func perform(
        _ operation: @escaping @MainActor () async throws -> Void
    ) async {
        isWorking = true
        error = nil
        defer { isWorking = false }
        do {
            try await operation()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
