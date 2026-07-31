import Foundation

struct ResearchHumanGateOverrideStatus: Codable, Equatable {
    let enabled: Bool
    let nodeID: String
    let checkpointRef: String
    let revision: Int
    let authorizedAt: Double
    let scope: String
    let stale: Bool?

    enum CodingKeys: String, CodingKey {
        case enabled
        case nodeID = "node_id"
        case checkpointRef = "checkpoint_ref"
        case revision
        case authorizedAt = "authorized_at"
        case scope, stale
    }
}

private struct ResearchHumanGateOverrideResponse: Decodable {
    let success: Bool
    let override: ResearchHumanGateOverrideStatus
}

final class ResearchHumanGateOverrideService {
    private let baseURL: URL
    private let session: URLSession

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    func status(
        instanceID: String,
        branchID: String
    ) async throws -> ResearchHumanGateOverrideStatus {
        try await request(
            instanceID: instanceID,
            branchID: branchID,
            method: "GET",
            payload: nil
        )
    }

    func authorize(
        instanceID: String,
        branchID: String,
        expectedNode: String,
        expectedCheckpointRef: String,
        enabled: Bool,
        password: String
    ) async throws -> ResearchHumanGateOverrideStatus {
        try await request(
            instanceID: instanceID,
            branchID: branchID,
            method: "PUT",
            payload: [
                "expected_node": expectedNode,
                "expected_checkpoint_ref": expectedCheckpointRef,
                "enabled": enabled,
                "password": password,
            ]
        )
    }

    private func request(
        instanceID: String,
        branchID: String,
        method: String,
        payload: [String: Any]?
    ) async throws -> ResearchHumanGateOverrideStatus {
        var request = URLRequest(url: Self.endpoint(
            baseURL: baseURL,
            instanceID: instanceID,
            branchID: branchID
        ))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let payload {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue(
                "macos-native-user-presence-v1",
                forHTTPHeaderField: "X-FactorTester-Interactive-Authorization"
            )
            request.httpBody = try JSONSerialization.data(
                withJSONObject: payload
            )
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode) else {
            let message = (try? JSONSerialization.jsonObject(with: data))
                .flatMap { $0 as? [String: Any] }?["error"] as? String
            throw APIError.server(message ?? L10n.text("门闸授权请求失败"))
        }
        return try JSONDecoder().decode(
            ResearchHumanGateOverrideResponse.self,
            from: data
        ).override
    }

    static func endpoint(
        baseURL: URL,
        instanceID: String,
        branchID: String
    ) -> URL {
        baseURL
            .appendingPathComponent("api")
            .appendingPathComponent("research-graph-instances")
            .appendingPathComponent(instanceID)
            .appendingPathComponent("branches")
            .appendingPathComponent(branchID)
            .appendingPathComponent("human-gate-override")
    }
}
