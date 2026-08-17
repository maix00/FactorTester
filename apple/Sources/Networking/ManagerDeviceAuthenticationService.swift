import Foundation

/// Native counterpart of the browser device flow.
///
/// The Swift client keeps its P-256 private key in Keychain/Secure Enclave and
/// speaks the same challenge/verify protocol as the browser. Device enrollment
/// is intentionally not part of this service: public allowlist users enroll a
/// browser origin by signing in through public visitor mode. This service only
/// authenticates a device that has already been enrolled.
final class ManagerDeviceAuthenticationService {
    static let shared = ManagerDeviceAuthenticationService()

    func authenticate(
        endpoint: URL? = nil,
        expectedUsername: String? = nil
    ) async throws -> ManagerDeviceAuthenticationResult {
        guard let configuredEndpoint = endpoint ?? ManagerConfig.shared.baseURL else {
            throw APIError.notConfigured
        }
        let endpoint = try Self.normalizedEndpoint(configuredEndpoint)
        guard let credential = ManagerDeviceKeyStore.load() else {
            throw ManagerDeviceKeyStoreError.keyUnavailable
        }
        let expected = expectedUsername?.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        if let expected, !expected.isEmpty,
           !credential.username.isEmpty,
           credential.username != expected {
            throw APIError.unauthorized(
                L10n.text(
                    "当前设备绑定的用户与已登录用户不一致，已拒绝切换账号。"
                )
            )
        }
        let challenge: ChallengeResponse = try await request(
            endpoint: endpoint,
            path: "/api/device/challenge",
            method: "POST",
            body: ["device_id": credential.deviceID]
        )
        guard let challengeBytes = Self.decodeBase64URL(challenge.challenge) else {
            throw APIError.server(L10n.text("服务器返回的设备挑战无效。"))
        }
        let signature = try ManagerDeviceKeyStore.sign(Data(challengeBytes))
        let response: DeviceSessionResponse = try await request(
            endpoint: endpoint,
            path: "/api/device/verify",
            method: "POST",
            body: [
                "challenge_id": challenge.challengeID,
                "device_id": credential.deviceID,
                "public_key": credential.publicKey,
                "signature": Self.base64URL(signature),
            ]
        )
        if let expected, !expected.isEmpty, response.username != expected {
            ManagerSessionTokenStore.remove(for: endpoint)
            throw APIError.unauthorized(
                L10n.text(
                    "当前设备绑定的用户与已登录用户不一致，已拒绝切换账号。"
                )
            )
        }
        try ManagerDeviceKeyStore.updateUsername(response.username)
        ManagerSessionTokenStore.save(response.token, for: endpoint)
        return response.result(deviceID: credential.deviceID, endpoint: endpoint)
    }

    private func request<Response: Decodable>(
        endpoint: URL,
        path: String,
        method: String,
        body: [String: Any]?
    ) async throws -> Response {
        guard let url = Self.url(endpoint: endpoint, path: path) else {
            throw APIError.server(L10n.text("设备认证地址无效。"))
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        request.setValue("FactorTester-Swift/1", forHTTPHeaderField: "User-Agent")
        request.setValue("swift", forHTTPHeaderField: "X-FactorTester-Client")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let session = URLSession(
            configuration: .ephemeral,
            delegate: SelfSignedTrustDelegate(allowedHosts: [url.host ?? ""]),
            delegateQueue: nil
        )
        defer { session.finishTasksAndInvalidate() }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw APIError.transport(L10n.text("服务器没有返回有效的 HTTP 响应"))
            }
            guard (200..<300).contains(http.statusCode) else {
                let message = Self.responseMessage(data)
                    ?? "HTTP \(http.statusCode)"
                if http.statusCode == 401 || http.statusCode == 403 {
                    throw APIError.unauthorized(message)
                }
                throw APIError.server(message)
            }
            return try JSONDecoder().decode(Response.self, from: data)
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
    }

    private static func normalizedEndpoint(_ endpoint: URL) throws -> URL {
        guard let scheme = endpoint.scheme?.lowercased(),
              let host = endpoint.host,
              !host.isEmpty,
              endpoint.user == nil,
              endpoint.password == nil,
              endpoint.query == nil,
              endpoint.fragment == nil else {
            throw APIError.server(L10n.text("设备认证地址无效。"))
        }
        let loopback = ManagerEndpointPolicy.isLoopback(host)
        guard scheme == "https" || (scheme == "http" && loopback) else {
            throw APIError.server(L10n.text("公网设备认证需要 HTTPS，不能使用公网 HTTP。"))
        }
        return endpoint
    }

    private static func url(endpoint: URL, path: String) -> URL? {
        guard var components = URLComponents(
            url: endpoint,
            resolvingAgainstBaseURL: false
        ) else { return nil }
        let root = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let suffix = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + ([root, suffix].filter { !$0.isEmpty }).joined(separator: "/")
        components.query = nil
        components.fragment = nil
        return components.url
    }

    private static func decodeBase64URL(_ value: String) -> [UInt8]? {
        let padded = value.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
            + String(repeating: "=", count: (4 - value.count % 4) % 4)
        return Data(base64Encoded: padded).map(Array.init)
    }

    private static func base64URL(_ value: Data) -> String {
        value.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
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

    private struct ChallengeResponse: Decodable {
        let success: Bool
        let challengeID: String
        let challenge: String

        enum CodingKeys: String, CodingKey {
            case success, challenge
            case challengeID = "challenge_id"
        }
    }

    private struct DeviceSessionResponse: Decodable {
        let success: Bool
        let username: String
        let role: String?
        let token: String
        let expiresIn: Int?

        enum CodingKeys: String, CodingKey {
            case success, username, role, token
            case expiresIn = "expires_in"
        }

        func result(
            deviceID: String,
            endpoint: URL
        ) -> ManagerDeviceAuthenticationResult {
            ManagerDeviceAuthenticationResult(
                deviceID: deviceID,
                username: username,
                role: role ?? "user",
                expiresIn: expiresIn ?? 0,
                endpoint: endpoint
            )
        }
    }

}

struct ManagerDeviceAuthenticationResult: Equatable {
    let deviceID: String
    let username: String
    let role: String
    let expiresIn: Int
    let endpoint: URL
}

struct ManagerPublicTarget: Decodable, Equatable {
    let serverID: String
    let role: String
    let endpoint: URL
    let latencyMS: Double?
    let load: Double

    enum CodingKeys: String, CodingKey {
        case role, endpoint, load
        case serverID = "server_id"
        case latencyMS = "latency_ms"
    }
}
