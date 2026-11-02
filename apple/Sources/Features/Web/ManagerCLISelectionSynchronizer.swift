#if os(macOS)
import Foundation
import OSLog

/// Serializes native selection updates so a slow older subprocess cannot be
/// the final writer after a second Manager switch. An explicit CLI choice is
/// intentionally preserved by the command itself.
@MainActor
final class ManagerCLISelectionSynchronizer {
    static let shared = ManagerCLISelectionSynchronizer()
    typealias Runner = (URL) async throws -> Void
    private let runner: Runner
    private let current: () -> URL?
    private var pending: URL?
    private var task: Task<Void, Never>?
    private let logger = Logger(subsystem: "com.gtht.client", category: "manager-selection")

    init(current: @escaping () -> URL? = { ManagerConfig.shared.baseURL },
         runner: @escaping Runner = { target in
             try await BundledRuntimeActivator.waitUntilReady()
             _ = try await ReleaseCommand.runObject(
                 ["client", "profile", "select-manager", "--server-url", target.absoluteString],
                 executable: ClientCLIResolution.executable()
             )
         }) {
        self.current = current
        self.runner = runner
    }

    func schedule(_ target: URL) {
        pending = target
        guard task == nil else { return }
        task = Task { @MainActor [weak self] in await self?.drain() }
    }

    private func drain() async {
        while let target = pending {
            pending = nil
            guard current() == target else { continue }
            do { try await runner(target) }
            catch { logger.error("CLI Manager selection could not be updated") }
            // A later selection remains in pending and is processed next.
        }
        task = nil
    }
}
#endif
