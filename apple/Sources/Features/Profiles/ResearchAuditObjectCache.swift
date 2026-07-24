import CryptoKit
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
        let objectURL = try Self.localRunSpecObjectURL(
            journalRef: journalRef,
            targetRef: targetRef
        )
        let data = try await Task.detached {
            try PersonalWorkspaceAccessStore.withAccess(to: objectURL) {
                try Data(contentsOf: objectURL, options: .mappedIfSafe)
            }
        }.value
        let value = try Self.decodeLocalRunSpec(
            data,
            targetRef: targetRef,
            using: decoder
        )
        values[key] = value
        return value
    }

    static func localRunSpecObjectURL(
        journalRef: String,
        targetRef: String
    ) throws -> URL {
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
        return journalURL
            .deletingLastPathComponent()
            .appendingPathComponent("objects", isDirectory: true)
            .appendingPathComponent("run_spec", isDirectory: true)
            .appendingPathComponent(objectID + ".json")
    }

    static func decodeLocalRunSpec(
        _ data: Data,
        targetRef: String,
        using decoder: JSONDecoder = JSONDecoder()
    ) throws -> ResearchAuditObjectPayload {
        guard targetRef.hasPrefix("runspec:") else {
            throw APIError.transport("RunSpec 本地引用无效")
        }
        let objectID = String(targetRef.dropFirst("runspec:".count))
        let value = try decoder.decode(
            ResearchAuditObjectPayload.self,
            from: data
        )
        guard value.objectKind == "run_spec",
              value.runSpecHash == objectID,
              let parameters = value.completeParametersJSON,
              !parameters.isEmpty,
              let parametersData = parameters.data(using: .utf8),
              (try? JSONSerialization.jsonObject(
                  with: parametersData
              )) != nil,
              let canonical = compactJSONData(parameters),
              SHA256.hash(data: canonical).map({
                  String(format: "%02x", $0)
              }).joined() == objectID else {
            throw APIError.transport("RunSpec 本地对象缺少完整配置或与引用不一致")
        }
        return value
    }

    private static func compactJSONData(_ source: String) -> Data? {
        var result = String.UnicodeScalarView()
        var insideString = false
        var escaped = false
        for scalar in source.unicodeScalars {
            if insideString {
                result.append(scalar)
                if escaped {
                    escaped = false
                } else if scalar == "\\" {
                    escaped = true
                } else if scalar == "\"" {
                    insideString = false
                }
            } else if scalar == "\"" {
                insideString = true
                result.append(scalar)
            } else if !CharacterSet.whitespacesAndNewlines.contains(scalar) {
                result.append(scalar)
            }
        }
        guard !insideString, !escaped else { return nil }
        return String(result).data(using: .utf8)
    }
}
