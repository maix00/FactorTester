import CryptoKit
import Foundation

struct ManagerTransferHTTPResponse {
    let statusCode: Int
    let data: Data
}

protocol ManagerTransferTransport {
    func data(
        for request: URLRequest,
        allowedHosts: Set<String>
    ) async throws -> ManagerTransferHTTPResponse
}

final class URLSessionManagerTransferTransport: ManagerTransferTransport {
    func data(
        for request: URLRequest,
        allowedHosts: Set<String>
    ) async throws -> ManagerTransferHTTPResponse {
        let session = URLSession(
            configuration: .ephemeral,
            delegate: SelfSignedTrustDelegate(allowedHosts: allowedHosts),
            delegateQueue: nil
        )
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport(L10n.text("服务器没有返回有效的 HTTP 响应"))
        }
        return ManagerTransferHTTPResponse(
            statusCode: http.statusCode,
            data: data
        )
    }
}

struct ManagerObjectTransferReceipt {
    let transferID: String
    let objectID: String
    let sizeBytes: Int
    let sha256: String
}

/// Client adapter for research object bytes.
///
/// Manager 7998 issues a short-lived capability. The returned URL is then
/// used directly on 7997; object bodies never travel in the JSON projection.
final class ManagerObjectTransferService {
    static let shared = ManagerObjectTransferService()

    private let configuredBaseURL: URL?
    private let configuredToken: String?
    private let transport: ManagerTransferTransport
    private let decoder = JSONDecoder()

    init(
        baseURL: URL? = nil,
        managerToken: String? = nil,
        transport: ManagerTransferTransport = URLSessionManagerTransferTransport()
    ) {
        configuredBaseURL = baseURL
        configuredToken = managerToken
        self.transport = transport
    }

    @discardableResult
    func uploadResearchAttachment(
        publicationID: String,
        attachmentID: String,
        content: Data,
        filename: String,
        contentType: String = "application/octet-stream"
    ) async throws -> ManagerObjectTransferReceipt {
        let digest = Self.sha256(content)
        let issued = try await issue(
            path: "/api/transfers/objects/access",
            body: [
                "publication_id": publicationID,
                "object_kind": "research_attachment",
                "object_id": attachmentID,
                "filename": filename,
                "content_type": contentType,
                "size_bytes": content.count,
                "sha256": digest,
            ],
            idempotencyKey: "research-upload:\(publicationID):\(attachmentID):\(digest)"
        )
        guard let access = issued.access,
              let url = URL(string: access.url),
              !access.bearer.isEmpty else {
            throw APIError.server(L10n.text("服务器返回的附件上传授权无效。"))
        }
        let request = dataRequest(
            url: url,
            method: "PUT",
            body: content,
            headers: [
                "Authorization": "Bearer \(access.bearer)",
                "Content-Length": String(content.count),
                "Content-Type": contentType,
                "X-FactorTester-Client": "swift",
            ]
        )
        let response = try await send(request, allowedHosts: hosts(for: url))
        try validateSuccess(
            response,
            fallback: L10n.text("研究附件上传失败")
        )
        return receipt(from: issued, objectID: attachmentID, digest: digest, size: content.count)
    }

    func downloadResearchAttachment(
        publicationID: String,
        attachmentID: String
    ) async throws -> Data {
        let issued = try await issue(
            path: "/api/transfers/objects/download-access",
            body: [
                "publication_id": publicationID,
                "object_kind": "research_attachment",
                "object_id": attachmentID,
            ],
            idempotencyKey: nil
        )
        guard let access = issued.access,
              let url = URL(string: access.url),
              !access.bearer.isEmpty else {
            throw APIError.server(L10n.text("服务器返回的附件下载授权无效。"))
        }
        let request = dataRequest(
            url: url,
            method: "GET",
            body: nil,
            headers: [
                "Authorization": "Bearer \(access.bearer)",
                "X-FactorTester-Client": "swift",
            ]
        )
        let response = try await send(request, allowedHosts: hosts(for: url))
        try validateSuccess(
            response,
            fallback: L10n.text("研究附件下载失败")
        )

        let expectedSize = access.expectedSize ?? issued.object?.sizeBytes
        if let expectedSize, response.data.count != expectedSize {
            throw APIError.server(L10n.text("研究附件大小校验失败。"))
        }
        if let expectedHash = issued.object?.sha256,
           Self.sha256(response.data) != expectedHash.lowercased() {
            throw APIError.server(L10n.text("研究附件完整性校验失败。"))
        }
        return response.data
    }

    @discardableResult
    func uploadEvidenceFile(
        content: Data,
        filename: String,
        contentType: String = "application/octet-stream"
    ) async throws -> ManagerObjectTransferReceipt {
        let digest = Self.sha256(content)
        let objectID = "evidence-file:v1:\(digest)"
        let issued = try await issue(
            path: "/api/transfers/objects/access",
            body: [
                "object_kind": "evidence_file", "object_id": objectID,
                "filename": filename, "content_type": contentType,
                "size_bytes": content.count, "sha256": digest,
            ],
            idempotencyKey: "evidence-file-upload:\(digest)"
        )
        guard let access = issued.access,
              let url = URL(string: access.url), !access.bearer.isEmpty else {
            throw APIError.server(L10n.text("服务器返回的证据文件上传授权无效。"))
        }
        let response = try await send(dataRequest(
            url: url, method: "PUT", body: content,
            headers: [
                "Authorization": "Bearer \(access.bearer)",
                "Content-Length": String(content.count),
                "Content-Type": contentType,
                "X-FactorTester-Client": "swift",
            ]
        ), allowedHosts: hosts(for: url))
        try validateSuccess(response, fallback: L10n.text("证据文件上传失败"))
        return receipt(
            from: issued, objectID: objectID, digest: digest, size: content.count
        )
    }

    func downloadEvidenceFile(
        evidenceRef: String,
        sourceRef: String
    ) async throws -> (data: Data, filename: String) {
        let issued = try await issue(
            path: "/api/transfers/objects/download-access",
            body: [
                "object_kind": "evidence_file",
                "evidence_ref": evidenceRef,
                "source_ref": sourceRef,
            ],
            idempotencyKey: nil
        )
        guard let access = issued.access,
              let url = URL(string: access.url), !access.bearer.isEmpty else {
            throw APIError.server(L10n.text("服务器返回的证据文件下载授权无效。"))
        }
        let response = try await send(dataRequest(
            url: url, method: "GET", body: nil,
            headers: [
                "Authorization": "Bearer \(access.bearer)",
                "X-FactorTester-Client": "swift",
            ]
        ), allowedHosts: hosts(for: url))
        try validateSuccess(response, fallback: L10n.text("证据文件下载失败"))
        if let size = access.expectedSize ?? issued.object?.sizeBytes,
           response.data.count != size {
            throw APIError.server(L10n.text("证据文件大小校验失败。"))
        }
        if let digest = issued.object?.sha256,
           Self.sha256(response.data) != digest.lowercased() {
            throw APIError.server(L10n.text("证据文件完整性校验失败。"))
        }
        return (response.data, issued.object?.filename ?? "evidence-file")
    }

    private func issue(
        path: String,
        body: [String: Any],
        idempotencyKey: String?
    ) async throws -> TransferAccessEnvelope {
        guard let baseURL = configuredBaseURL ?? ManagerConfig.shared.baseURL,
              let url = Self.url(baseURL: baseURL, path: path) else {
            throw APIError.notConfigured
        }
        var headers = [
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-FactorTester-Client": "swift",
        ]
        let token = managerToken(for: baseURL)
        if !token.isEmpty {
            headers["Authorization"] = "Bearer \(token)"
        }
        if let idempotencyKey, !idempotencyKey.isEmpty {
            headers["Idempotency-Key"] = idempotencyKey
        }
        let data = try JSONSerialization.data(withJSONObject: body)
        let request = dataRequest(url: url, method: "POST", body: data, headers: headers)
        let response = try await send(request, allowedHosts: hosts(for: url))
        try validateSuccess(response, fallback: "附件传输授权失败")
        let value = try decoder.decode(TransferAccessEnvelope.self, from: response.data)
        guard value.success, value.access != nil else {
            throw APIError.server(value.error ?? L10n.text("附件传输授权失败"))
        }
        return value
    }

    private func send(
        _ request: URLRequest,
        allowedHosts: Set<String>
    ) async throws -> ManagerTransferHTTPResponse {
        do {
            return try await transport.data(
                for: request,
                allowedHosts: Set(allowedHosts.map { $0.lowercased() })
            )
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
    }

    private func dataRequest(
        url: URL,
        method: String,
        body: Data?,
        headers: [String: String]
    ) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = 120
        headers.forEach { request.setValue($1, forHTTPHeaderField: $0) }
        return request
    }

    private func managerToken(for baseURL: URL) -> String {
        configuredToken ?? ManagerSessionTokenStore.read(for: baseURL)
    }

    private func hosts(for url: URL) -> Set<String> {
        guard let host = url.host, !host.isEmpty else { return [] }
        return [host.lowercased()]
    }

    private func receipt(
        from envelope: TransferAccessEnvelope,
        objectID: String,
        digest: String,
        size: Int
    ) -> ManagerObjectTransferReceipt {
        ManagerObjectTransferReceipt(
            transferID: envelope.access?.transferID ?? "",
            objectID: envelope.object?.objectID ?? objectID,
            sizeBytes: envelope.object?.sizeBytes ?? size,
            sha256: envelope.object?.sha256 ?? digest
        )
    }

    private func validateSuccess(
        _ response: ManagerTransferHTTPResponse,
        fallback: String
    ) throws {
        guard (200..<300).contains(response.statusCode) else {
            let message = Self.responseMessage(response.data) ?? fallback
            if response.statusCode == 401 || response.statusCode == 403 {
                throw APIError.unauthorized(message)
            }
            throw APIError.server("HTTP \(response.statusCode)：\(message)")
        }
    }

    private static func url(baseURL: URL, path: String) -> URL? {
        guard var components = URLComponents(
            url: baseURL,
            resolvingAgainstBaseURL: false
        ) else { return nil }
        components.path = path
        components.query = nil
        components.fragment = nil
        return components.url
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func responseMessage(_ data: Data) -> String? {
        guard let value = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any] else { return nil }
        for key in ["error", "message", "detail"] {
            if let message = value[key] as? String, !message.isEmpty {
                return message
            }
        }
        return nil
    }
}

private struct TransferAccessEnvelope: Decodable {
    let success: Bool
    let error: String?
    let object: TransferObjectMetadata?
    let access: TransferAccess?
}

private struct TransferObjectMetadata: Decodable {
    let objectID: String?
    let sizeBytes: Int?
    let sha256: String?
    let filename: String?

    enum CodingKeys: String, CodingKey {
        case objectID = "object_id"
        case sizeBytes = "size_bytes"
        case sha256, filename
    }
}

private struct TransferAccess: Decodable {
    let transferID: String?
    let url: String
    let bearer: String
    let expectedSize: Int?

    enum CodingKeys: String, CodingKey {
        case transferID = "transfer_id"
        case url, bearer
        case expectedSize = "expected_size"
    }
}
