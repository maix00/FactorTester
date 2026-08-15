import Foundation

struct ManagerNetworkInfo: Decodable, Equatable {
    let serverID: String
    let role: String
    let internalAddresses: [String]
    let managerPort: Int
    let publicServer: Bool?
    let advertisedPublicEndpoint: String
    let currentPublicTarget: ManagerPublicTarget?
    /// Server order is authoritative: the first online public target is the
    /// target selected by the client when the Manager is only a bootstrap.
    let publicServerTargets: [ManagerPublicTarget]?
    /// Uncapped online public candidates. The web home page intentionally
    /// uses the capped field above; Swift uses this field for probing.
    let onlinePublicServerTargets: [ManagerPublicTarget]?
    let onlinePublicServerAddresses: [String]?
    /// Online internal Manager nodes, each carrying its organization scope.
    let internalServerTargets: [ManagerInternalTarget]?

    enum CodingKeys: String, CodingKey {
        case role
        case serverID = "server_id"
        case internalAddresses = "internal_addresses"
        case managerPort = "manager_port"
        case publicServer = "public_server"
        case advertisedPublicEndpoint = "advertised_public_endpoint"
        case currentPublicTarget = "current_public_target"
        case publicServerTargets = "public_server_targets"
        case onlinePublicServerTargets = "online_public_server_targets"
        case onlinePublicServerAddresses = "online_public_server_addresses"
        case internalServerTargets = "internal_server_targets"
    }

    var internalEndpointSummary: String {
        internalAddresses.map { address in
            managerPort > 0 ? "\(address):\(managerPort)" : address
        }.joined(separator: " · ")
    }

    var publicEndpointSummary: String {
        if let target = currentPublicTarget {
            return "\(target.endpoint.absoluteString) (\(target.serverID))"
        }
        guard publicServer != false, !advertisedPublicEndpoint.isEmpty else {
            return ""
        }
        return "\(advertisedPublicEndpoint) (\(serverID))"
    }

    var nearestPublicTarget: ManagerPublicTarget? {
        publicCandidates.first ?? currentPublicTarget
    }

    var publicCandidates: [ManagerPublicTarget] {
        var values: [ManagerPublicTarget]
        if let onlinePublicServerTargets, !onlinePublicServerTargets.isEmpty {
            values = onlinePublicServerTargets
        } else {
            values = publicServerTargets ?? []
        }
        if values.isEmpty, let currentPublicTarget {
            values = [currentPublicTarget]
        }
        var seen = Set<String>()
        return values.filter { seen.insert($0.endpoint.absoluteString).inserted }
    }

    var internalCandidates: [ManagerInternalTarget] {
        internalServerTargets ?? []
    }
}

struct ManagerInternalTarget: Decodable, Equatable {
    let serverID: String
    let role: String
    let addresses: [String]
    let managerPort: Int
    let managedOrganizations: [String]
    let online: Bool

    enum CodingKeys: String, CodingKey {
        case role, addresses, online
        case serverID = "server_id"
        case managerPort = "manager_port"
        case managedOrganizations = "managed_organizations"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        serverID = (try? container.decode(String.self, forKey: .serverID)) ?? ""
        role = (try? container.decode(String.self, forKey: .role)) ?? "feat"
        addresses = (try? container.decode([String].self, forKey: .addresses)) ?? []
        managerPort = (try? container.decode(Int.self, forKey: .managerPort)) ?? 7998
        managedOrganizations = (try? container.decode([String].self, forKey: .managedOrganizations)) ?? []
        online = (try? container.decode(Bool.self, forKey: .online)) ?? true
    }

    func endpoints() -> [URL] {
        addresses.compactMap { address in
            var components = URLComponents()
            components.scheme = "http"
            components.host = address
            components.port = managerPort > 0 ? managerPort : 7998
            return components.url
        }
    }
}

struct ManagerNetworkProbe {
    let endpoint: URL
    let info: ManagerNetworkInfo
    let latencyMS: Double
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
        request.timeoutInterval = 3
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

    func probe(endpoint: URL) async -> ManagerNetworkProbe? {
        let started = Date().timeIntervalSinceReferenceDate
        do {
            let info = try await fetch(endpoint: endpoint)
            let elapsed = max(
                0,
                (Date().timeIntervalSinceReferenceDate - started) * 1000
            )
            return ManagerNetworkProbe(
                endpoint: endpoint,
                info: info,
                latencyMS: elapsed
            )
        } catch {
            return nil
        }
    }

    func probeAll(endpoints: [URL]) async -> [ManagerNetworkProbe] {
        let service = self
        return await withTaskGroup(of: ManagerNetworkProbe?.self) { group in
            for endpoint in endpoints {
                group.addTask {
                    await service.probe(endpoint: endpoint)
                }
            }
            var results: [ManagerNetworkProbe] = []
            for await result in group {
                if let result { results.append(result) }
            }
            return results
        }
    }
}
