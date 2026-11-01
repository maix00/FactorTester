import Foundation

/// Serializes CLI-session writes with logout and ignores obsolete requests.
@MainActor
final class ClientSessionBridgeCoordinator {
    private var tail: Task<Void, Never>?
    private var revision: UInt64 = 0
    private var lastSuccessfulKey: String?

    func submit(key: String?, valid: @escaping @MainActor () -> Bool,
                operation: @escaping @MainActor () async -> Bool) async -> Bool {
        let ticket = revision
        let previous = tail
        let task = Task { @MainActor [weak self] () -> Bool in
            await previous?.value
            guard let self, self.revision == ticket, valid() else { return false }
            if let key, self.lastSuccessfulKey == key { return true }
            let result = await operation()
            guard self.revision == ticket, valid() else { return false }
            if result { self.lastSuccessfulKey = key }
            return result
        }
        tail = Task { @MainActor in _ = await task.value }
        return await task.value
    }

    /// Invalidate queued writes, wait for the active write, then clear. The
    /// clear operation must be last even when the active writer ignores cancellation.
    func invalidateAndClear(_ operation: @escaping @MainActor () async -> Void) async {
        revision &+= 1
        lastSuccessfulKey = nil
        let previous = tail
        let task = Task { @MainActor in
            await previous?.value
            await operation()
        }
        tail = task
        await task.value
    }
}
