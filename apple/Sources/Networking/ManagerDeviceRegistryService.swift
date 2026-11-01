import Foundation

struct ManagerDeviceAudit: Decodable, Equatable {
    let deviceID: String
    let deviceName: String
    let clientType: String
    let clientName: String
    let enrollmentIP: String
    let lastSeenIP: String

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case deviceName = "device_name"
        case clientType = "client_type"
        case clientName = "client_name"
        case enrollmentIP = "enrollment_ip"
        case lastSeenIP = "last_seen_ip"
    }
}

final class ManagerDeviceRegistryService {
    static let shared = ManagerDeviceRegistryService()

    func enroll(endpoint: URL, username: String) async throws {
        guard ManagerConnectionBridgeContract.endpoint(endpoint.absoluteString) != nil,
              let url = URL(string: "/api/devices/enroll", relativeTo: endpoint)?.absoluteURL else {
            throw APIError.notConfigured
        }
        let token = ManagerSessionTokenStore.read(for: endpoint)
        guard !token.isEmpty else { throw APIError.unauthorized("Manager session required") }
        let credential = try ManagerDeviceKeyStore.ensureForEnrollment(username: username)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("TradeResearch-Swift/1", forHTTPHeaderField: "User-Agent")
        #if os(iOS)
        request.setValue("mobile", forHTTPHeaderField: "X-FactorTester-Client")
        #else
        request.setValue("swift", forHTTPHeaderField: "X-FactorTester-Client")
        #endif
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "device_id": credential.deviceID, "public_key": credential.publicKey,
        ])
        let network = URLSession(configuration: .ephemeral,
            delegate: SelfSignedTrustDelegate(allowedHosts: [url.host ?? ""]), delegateQueue: nil)
        defer { network.finishTasksAndInvalidate() }
        let (data, response) = try await network.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIError.unauthorized("Device enrollment was not authorized")
        }
        let value = try JSONDecoder().decode(EnrollmentResponse.self, from: data)
        guard value.success, value.device.deviceID == credential.deviceID else {
            throw APIError.server("Invalid device enrollment response")
        }
        try ManagerDeviceKeyStore.updateUsername(username)
    }

    private struct EnrollmentResponse: Decodable {
        let success: Bool
        let device: DeviceIdentity
    }

    private struct DeviceIdentity: Decodable {
        let deviceID: String
        enum CodingKeys: String, CodingKey { case deviceID = "device_id" }
    }

    func currentDevice(endpoint: URL? = nil) async throws -> ManagerDeviceAudit? {
        guard let credential = ManagerDeviceKeyStore.load() else { return nil }
        guard let baseURL = endpoint ?? ManagerConfig.shared.baseURL,
              let url = URL(string: "/api/devices", relativeTo: baseURL)?.absoluteURL else {
            throw APIError.notConfigured
        }
        let token = ManagerSessionTokenStore.read(for: baseURL)
        guard !token.isEmpty else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("FactorTester-Swift/1", forHTTPHeaderField: "User-Agent")
        request.setValue("swift", forHTTPHeaderField: "X-FactorTester-Client")

        let session = URLSession(
            configuration: .ephemeral,
            delegate: SelfSignedTrustDelegate(allowedHosts: [url.host ?? ""]),
            delegateQueue: nil
        )
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport(L10n.text("服务器没有返回有效的 HTTP 响应"))
        }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server("HTTP \(http.statusCode)")
        }
        let payload = try JSONDecoder().decode(DeviceListResponse.self, from: data)
        return payload.devices.first { $0.deviceID == credential.deviceID }
    }

    private struct DeviceListResponse: Decodable {
        let devices: [ManagerDeviceAudit]
    }
}
