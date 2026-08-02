import Foundation

@MainActor
final class ResearchFactorSetMemberPageCache {
    static let shared = ResearchFactorSetMemberPageCache()

    private struct Key: Hashable {
        let targetRef: String
        let offset: Int
        let limit: Int
    }

    private var values: [Key: [String: Any]] = [:]
    private var inFlight: [Key: Task<[String: Any], Error>] = [:]

    func value(
        targetRef: String,
        offset: Int,
        limit: Int,
        loader: @escaping @MainActor () async throws -> [String: Any]
    ) async throws -> [String: Any] {
        let key = Key(targetRef: targetRef, offset: offset, limit: limit)
        if let value = values[key] { return value }
        if let task = inFlight[key] { return try await task.value }
        let task = Task { @MainActor in try await loader() }
        inFlight[key] = task
        do {
            let value = try await task.value
            values[key] = value
            inFlight[key] = nil
            return value
        } catch {
            inFlight[key] = nil
            throw error
        }
    }

    func removeAll() {
        inFlight.values.forEach { $0.cancel() }
        inFlight.removeAll()
        values.removeAll()
    }
}
