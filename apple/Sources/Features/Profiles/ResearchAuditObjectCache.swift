import Foundation

@MainActor
final class ResearchAuditObjectCache: ObservableObject {
    private var values: [String: ResearchAuditObjectPayload] = [:]

    func load(
        namespace: String,
        href: String,
        using loader: (String) async throws -> ResearchAuditObjectPayload
    ) async throws -> ResearchAuditObjectPayload {
        let key = namespace + "|" + href
        if let value = values[key] {
            return value
        }
        let value = try await loader(href)
        values[key] = value
        return value
    }

    var cachedObjectCount: Int { values.count }
}
