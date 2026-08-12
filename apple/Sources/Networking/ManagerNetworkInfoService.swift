import Foundation

struct ManagerNetworkInfo: Decodable, Equatable {
    let serverID: String
    let role: String
    let internalAddresses: [String]
    let managerPort: Int
    let advertisedPublicEndpoint: String
    let currentPublicTarget: ManagerPublicTarget?

    enum CodingKeys: String, CodingKey {
        case role
        case serverID = "server_id"
        case internalAddresses = "internal_addresses"
        case managerPort = "manager_port"
        case advertisedPublicEndpoint = "advertised_public_endpoint"
        case currentPublicTarget = "current_public_target"
    }

    var internalEndpointSummary: String {
        internalAddresses.map { address in
            managerPort > 0 ? "\(address):\(managerPort)" : address
        }.joined(separator: " · ")
    }

    var publicEndpointSummary: String {
        if !advertisedPublicEndpoint.isEmpty {
            return advertisedPublicEndpoint
        }
        guard let target = currentPublicTarget else { return "" }
        return "\(target.endpoint.absoluteString) (\(target.serverID))"
    }
}

final class ManagerNetworkInfoService {
    static let shared = ManagerNetworkInfoService()

    func fetch(endpoint: URL? = nil) async throws -> ManagerNetworkInfo {
        guard let baseURL = endpoint ?? ManagerConfig.shared.baseURL,
              let url = URL(
                string: "/api/server/network-info",
                relativeTo: baseURL
              )?.absoluteURL else {
            throw APIError.notConfigured
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("FactorTester-Swift/1", forHTTPHeaderField: "User-Agent")
        request.setValue("swift", forHTTPHeaderField: "X-FactorTester-Client")
        let token = ManagerSessionTokenStore.read(for: baseURL)
        if !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
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
                throw APIError.transport(
                    L10n.text("服务器没有返回有效的 HTTP 响应")
                )
            }
            guard (200..<300).contains(http.statusCode) else {
                throw APIError.server("HTTP \(http.statusCode)")
            }
            return try JSONDecoder().decode(ManagerNetworkInfo.self, from: data)
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
    }
}
