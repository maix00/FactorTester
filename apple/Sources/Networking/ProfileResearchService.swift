import Foundation

struct ResearchHTTPResponse {
    let data: Data
    let statusCode: Int
    let etag: String?
}

protocol ProfileResearchTransport {
    func data(for request: URLRequest) async throws -> ResearchHTTPResponse
    func events(
        for request: URLRequest
    ) -> AsyncThrowingStream<Void, Error>
}

final class URLSessionProfileResearchTransport: ProfileResearchTransport {
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func data(for request: URLRequest) async throws -> ResearchHTTPResponse {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport("Invalid server response")
        }
        return ResearchHTTPResponse(
            data: data,
            statusCode: http.statusCode,
            etag: http.value(forHTTPHeaderField: "ETag")
        )
    }

    func events(
        for request: URLRequest
    ) -> AsyncThrowingStream<Void, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse,
                          (200..<300).contains(http.statusCode) else {
                        throw APIError.transport("SSE connection failed")
                    }
                    for try await line in bytes.lines {
                        try Task.checkCancellation()
                        if line.hasPrefix("data:") {
                            continuation.yield(())
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

enum ConditionalProjection<Value> {
    case notModified
    case value(Value, responseETag: String?)
}

struct ProfileResearchService {
    let baseURL: URL
    let transport: ProfileResearchTransport
    private let servicePort: Int?
    private let managerToken: String
    private let decoder = JSONDecoder()

    init(
        baseURL: URL,
        transport: ProfileResearchTransport =
            URLSessionProfileResearchTransport(),
        servicePort: Int? = nil,
        managerToken: String = ""
    ) {
        self.baseURL = baseURL
        self.transport = transport
        self.servicePort = servicePort
        self.managerToken = managerToken
    }

    static func unified(
        serviceURL: URL,
        transport: ProfileResearchTransport = URLSessionProfileResearchTransport()
    ) -> ProfileResearchService {
        guard let managerURL = ManagerConfig.shared.baseURL else {
            return ProfileResearchService(baseURL: serviceURL, transport: transport)
        }
        return ProfileResearchService(
            baseURL: managerURL,
            transport: transport,
            servicePort: Int(
                ServerConfig.shared.port.trimmingCharacters(in: .whitespaces)
            ),
            managerToken: ManagerSessionTokenStore.read()
        )
    }

    func auditObject(href: String) async throws -> ResearchAuditObjectPayload {
        let envelope = try await value(
            path: href,
            as: ResearchAuditObjectEnvelope.self
        )
        return envelope.object
    }

    func events(href: String) -> AsyncThrowingStream<Void, Error> {
        transport.events(for: request(path: href, etag: nil))
    }

    func frozenObjectJSON(
        reference: ResearchDocumentTypedLink
    ) async throws -> String {
        switch reference.kind {
        case "trial_plan":
            let digest = try frozenDigest(
                reference.targetRef,
                prefix: "trial-plan:sha256:"
            )
            let envelope = try await value(
                path: "/api/trial-plans/direct/\(digest)",
                as: ResearchDirectTrialPlanEnvelope.self
            )
            return try completeJSON(envelope.trialPlan.trialPlan)
        case "run_spec":
            let digest = try frozenDigest(
                reference.targetRef,
                prefix: "runspec:sha256:"
            )
            let envelope = try await value(
                path: "/api/run-specs/\(digest)",
                as: ResearchRunSpecEnvelope.self
            )
            return try completeJSON(envelope.runSpec.runSpec)
        case "run":
            let runID = try safeObjectID(
                reference.targetRef,
                prefix: "run:"
            )
            let envelope = try await value(
                path: "/api/runs/\(runID)",
                as: ResearchRunEnvelope.self
            )
            return try completeJSON(envelope.run.runSpec)
        default:
            throw APIError.transport(L10n.text("该引用没有冻结提交 JSON"))
        }
    }

    func evidence(
        reference: String
    ) async throws -> ResearchEvidenceDetailPayload {
        try await evidenceDetail(reference: reference).evidence
    }

    func evidenceDetail(
        reference: String
    ) async throws -> ResearchEvidenceResolvedDetail {
        let allowed = CharacterSet.urlPathAllowed.subtracting(
            CharacterSet(charactersIn: "/?#")
        )
        guard reference.hasPrefix("evidence:"),
              let encoded = reference.addingPercentEncoding(
                withAllowedCharacters: allowed
              ) else {
            throw APIError.transport(L10n.text("证据引用格式无效"))
        }
        let value = try await self.value(
            path: "/api/research-evidence/\(encoded)",
            as: ResearchEvidenceDetailEnvelope.self
        )
        return ResearchEvidenceResolvedDetail(
            evidence: value.evidence,
            access: value.access
        )
    }

    // MARK: - Canonical Research catalog (ADR-142)

    func researches(
        scope: String = "all",
        includeArchived: Bool = false
    ) async throws -> [ResearchCatalogItem] {
        let envelope = try await value(
            path: path("/api/research", query: [
                URLQueryItem(name: "scope", value: scope),
                URLQueryItem(
                    name: "include_archived",
                    value: includeArchived ? "1" : "0"
                ),
            ]),
            as: ResearchCatalogListEnvelope.self
        )
        return envelope.researches
    }

    func research(researchID: String) async throws -> ResearchCatalogDetail {
        let envelope = try await value(
            path: "/api/research/\(encodedPathComponent(researchID))",
            as: ResearchCatalogDetailEnvelope.self
        )
        return envelope.research
    }

    func createResearch(
        title: String,
        description: String = "",
        visibility: String = "private",
        authorizedUsers: [String] = [],
        profileRef: String = ""
    ) async throws -> ResearchCatalogItem {
        let envelope = try await writeValue(
            path: "/api/research",
            method: "POST",
            body: [
                "title": title,
                "description": description,
                "visibility": visibility,
                "authorized_users": authorizedUsers,
                "profile_ref": profileRef,
            ],
            as: ResearchCatalogCreateEnvelope.self
        )
        return envelope.research
    }

    func addResearchMember(
        researchID: String,
        principalRef: String,
        profileRef: String,
        role: String = "contributor"
    ) async throws -> ResearchCatalogMembership {
        let envelope = try await writeValue(
            path: "/api/research/\(encodedPathComponent(researchID))/members",
            method: "POST",
            body: [
                "principal_ref": principalRef,
                "profile_ref": profileRef,
                "role": role,
                "status": "active",
            ],
            as: ResearchCatalogMemberEnvelope.self
        )
        return envelope.member
    }

    func createResearchWorkspace(
        researchID: String,
        principalRef: String,
        profileRef: String,
        title: String = ""
    ) async throws -> ResearchCatalogWorkspace {
        let envelope = try await writeValue(
            path: "/api/research/\(encodedPathComponent(researchID))/workspaces",
            method: "POST",
            body: [
                "principal_ref": principalRef,
                "profile_ref": profileRef,
                "title": title,
            ],
            as: ResearchCatalogWorkspaceEnvelope.self
        )
        return envelope.workspace
    }

    func linkResearchReport(
        researchID: String,
        reportID: String,
        title: String,
        profileRef: String = "",
        workspaceID: String = "",
        buildSource: String = "client"
    ) async throws -> ResearchCatalogReport {
        let envelope = try await writeValue(
            path: "/api/research/\(encodedPathComponent(researchID))/reports",
            method: "POST",
            body: [
                "report_id": reportID,
                "title": title,
                "profile_ref": profileRef,
                "workspace_id": workspaceID,
                "build_source": buildSource,
            ],
            as: ResearchCatalogReportEnvelope.self
        )
        return envelope.report
    }

    private func value<T: Decodable>(
        path: String,
        as type: T.Type
    ) async throws -> T {
        switch try await conditional(path: path, etag: nil, as: type) {
        case .notModified:
            throw APIError.transport("Unexpected not-modified response")
        case .value(let value, _):
            return value
        }
    }

    private func writeValue<T: Decodable>(
        path: String,
        method: String,
        body: [String: Any],
        as type: T.Type
    ) async throws -> T {
        let data = try JSONSerialization.data(withJSONObject: body)
        let response = try await transport.data(for: request(
            path: path, etag: nil, method: method, body: data
        ))
        guard (200..<300).contains(response.statusCode) else {
            if let payload = try? decoder.decode(
                ResearchProjectionErrorPayload.self,
                from: response.data
            ), !payload.error.isEmpty {
                throw APIError.transport(payload.error)
            }
            throw APIError.transport(
                "Research catalog HTTP \(response.statusCode)"
            )
        }
        return try decoder.decode(type, from: response.data)
    }

    private func encodedPathComponent(_ value: String) -> String {
        let allowed = CharacterSet.urlPathAllowed.subtracting(
            CharacterSet(charactersIn: "/?#")
        )
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    private func conditional<T: Decodable>(
        path: String,
        etag: String?,
        as type: T.Type = T.self
    ) async throws -> ConditionalProjection<T> {
        let response = try await transport.data(
            for: request(path: path, etag: etag)
        )
        if response.statusCode == 304 { return .notModified }
        guard (200..<300).contains(response.statusCode) else {
            if response.statusCode == 401 || response.statusCode == 403 {
                throw APIError.transport(L10n.text("没有权限读取该研究工作区"))
            }
            if let payload = try? decoder.decode(
                ResearchProjectionErrorPayload.self,
                from: response.data
            ), !payload.error.isEmpty {
                throw APIError.transport(payload.error)
            }
            throw APIError.transport(
                "Research projection HTTP \(response.statusCode)"
            )
        }
        do {
            return .value(
                try decoder.decode(type, from: response.data),
                responseETag: response.etag
            )
        } catch is DecodingError {
            throw APIError.transport(
                L10n.text("研究投影格式无法识别；客户端与服务器协议版本可能不一致。")
            )
        }
    }

    private func request(
        path: String,
        etag: String?,
        method: String = "GET",
        body: Data? = nil
    ) -> URLRequest {
        let url = URL(
            string: managerPath(path), relativeTo: baseURL
        )!.absoluteURL
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue(
                "application/json",
                forHTTPHeaderField: "Content-Type"
            )
        }
        if let etag {
            request.setValue(etag, forHTTPHeaderField: "If-None-Match")
        }
        if !managerToken.isEmpty {
            request.setValue(
                "Bearer \(managerToken)",
                forHTTPHeaderField: "Authorization"
            )
        }
        return request
    }

    private func managerPath(_ value: String) -> String {
        guard let servicePort else { return value }
        var components = URLComponents(string: value)
        var items = components?.queryItems ?? []
        items.removeAll { $0.name == "port" }
        items.append(URLQueryItem(name: "port", value: String(servicePort)))
        components?.queryItems = items
        return components?.string ?? value
    }

    private func frozenDigest(
        _ reference: String,
        prefix: String
    ) throws -> String {
        let digest = try safeObjectID(reference, prefix: prefix)
        guard digest.count == 64,
              digest.allSatisfy({ $0.isHexDigit && !$0.isUppercase }) else {
            throw APIError.transport(L10n.text("冻结对象引用格式无效"))
        }
        return digest
    }

    private func safeObjectID(
        _ reference: String,
        prefix: String
    ) throws -> String {
        guard reference.hasPrefix(prefix) else {
            throw APIError.transport(L10n.text("冻结对象引用格式无效"))
        }
        let value = String(reference.dropFirst(prefix.count))
        guard !value.isEmpty, value.utf8.count <= 128,
              value.unicodeScalars.allSatisfy({
                  CharacterSet.alphanumerics.contains($0)
                      || "._-".unicodeScalars.contains($0)
              }) else {
            throw APIError.transport(L10n.text("冻结对象引用格式无效"))
        }
        return value
    }

    private func completeJSON(_ value: ResearchJSONValue) throws -> String {
        guard let json = value.prettyJSONString, !json.isEmpty else {
            throw APIError.transport(L10n.text("冻结对象 JSON 无法读取"))
        }
        return json
    }

    private func path(
        _ value: String,
        query: [URLQueryItem]
    ) -> String {
        var components = URLComponents()
        components.path = value
        components.queryItems = query.filter { $0.value != nil }
        return components.string ?? value
    }
}

private struct ResearchProjectionErrorPayload: Decodable {
    let error: String
    let errorCode: String?

    enum CodingKeys: String, CodingKey {
        case error
        case errorCode = "error_code"
    }
}

private struct ResearchDirectTrialPlanEnvelope: Decodable {
    let trialPlan: ResearchDirectTrialPlanRecord

    enum CodingKeys: String, CodingKey {
        case trialPlan = "trial_plan"
    }
}

private struct ResearchDirectTrialPlanRecord: Decodable {
    let trialPlan: ResearchJSONValue

    enum CodingKeys: String, CodingKey {
        case trialPlan = "trial_plan"
    }
}

private struct ResearchRunSpecEnvelope: Decodable {
    let runSpec: ResearchRunSpecRecord

    enum CodingKeys: String, CodingKey {
        case runSpec = "run_spec"
    }
}

private struct ResearchRunSpecRecord: Decodable {
    let runSpec: ResearchJSONValue

    enum CodingKeys: String, CodingKey {
        case runSpec = "run_spec"
    }
}

private struct ResearchRunEnvelope: Decodable {
    let run: ResearchRunRecord
}

private struct ResearchRunRecord: Decodable {
    let runSpec: ResearchJSONValue

    enum CodingKeys: String, CodingKey {
        case runSpec = "run_spec"
    }
}
