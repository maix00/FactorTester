import Foundation

@MainActor
final class ResearchAuditObjectCache: ObservableObject {
    private var values: [String: ResearchAuditObjectPayload] = [:]
    private let decoder = JSONDecoder()

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

    func loadLocalRunSpec(
        namespace: String,
        journalRef: String,
        targetRef: String
    ) async throws -> ResearchAuditObjectPayload {
        let key = namespace + "|" + targetRef
        if let value = values[key] {
            return value
        }
        guard targetRef.hasPrefix("runspec:"),
              let journalURL = URL(string: journalRef),
              journalURL.isFileURL else {
            throw APIError.transport("RunSpec 本地引用无效")
        }
        let objectID = String(targetRef.dropFirst("runspec:".count))
        guard objectID.range(
            of: #"^[0-9a-f]{64}$"#,
            options: .regularExpression
        ) != nil else {
            throw APIError.transport("RunSpec 哈希无效")
        }
        let objectURL = journalURL
            .deletingLastPathComponent()
            .appendingPathComponent("objects", isDirectory: true)
            .appendingPathComponent("run_spec", isDirectory: true)
            .appendingPathComponent(objectID + ".json")
        let data = try await Task.detached {
            try PersonalWorkspaceAccessStore.withAccess(to: objectURL) {
                try Data(contentsOf: objectURL, options: .mappedIfSafe)
            }
        }.value
        let value = try decoder.decode(
            ResearchAuditObjectPayload.self,
            from: data
        )
        guard value.objectKind == "run_spec",
              value.runSpecHash == objectID else {
            throw APIError.transport("RunSpec 本地对象与引用不一致")
        }
        values[key] = value
        return value
    }
}
