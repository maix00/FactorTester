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
