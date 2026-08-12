import Combine
import Foundation

struct ResearchGraphEndpoint: Identifiable, Hashable {
    let serverURL: URL

    var id: String { serverURL.absoluteString }
    var displayName: String { serverURL.host ?? serverURL.absoluteString }

    static func available(
        from profiles: [LocalProfileModel]
    ) -> [ResearchGraphEndpoint] {
        var values: [String: ResearchGraphEndpoint] = [:]
        for profile in profiles where profile.status == "active" {
            guard let url = canonicalURL(profile.serverURL) else { continue }
            values[url.absoluteString] = ResearchGraphEndpoint(serverURL: url)
        }
        return values.values.sorted { $0.id < $1.id }
    }

    private static func canonicalURL(_ rawValue: String) -> URL? {
        guard var components = URLComponents(string: rawValue),
              let scheme = components.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              components.host != nil else {
            return nil
        }
        components.scheme = scheme
        components.host = components.host?.lowercased()
        components.path = components.path == "/" ? "" : components.path
        components.query = nil
        components.fragment = nil
        return components.url
    }
}

@MainActor
final class ResearchGraphBrowserController: ObservableObject {
    typealias Loader = @MainActor (
        _ endpoint: ResearchGraphEndpoint
    ) async throws -> (
        versions: [ResearchGraphVersion],
        active: ResearchGraphVersion?
    )

    @Published private(set) var endpoints: [ResearchGraphEndpoint]
    @Published var selectedEndpointID: String?
    @Published private(set) var versions: [ResearchGraphVersion] = []
    @Published private(set) var selectedVersion: Int?
    @Published private(set) var activeVersion: Int?
    @Published private(set) var isLoading = false
    @Published private(set) var error: String?

    private let graphID: String
    private let load: Loader

    init(
        endpoints: [ResearchGraphEndpoint],
        initialEndpointID: String? = nil,
        initialVersion: Int? = nil,
        graphID: String = "factor-research",
        load: Loader? = nil
    ) {
        self.endpoints = endpoints
        self.selectedEndpointID = endpoints.contains {
            $0.id == initialEndpointID
        } ? initialEndpointID : endpoints.first?.id
        self.selectedVersion = initialVersion
        self.graphID = graphID
        self.load = load ?? { endpoint in
            let service = ProfileResearchService.unified(
                serviceURL: endpoint.serverURL
            )
            let versions = try await service.researchGraphVersions(
                graphID: graphID
            )
            let active = try? await service.activeResearchGraph(
                graphID: graphID
            )
            return (versions, active)
        }
    }

    var selectedGraph: ResearchGraphVersion? {
        guard let selectedVersion else { return nil }
        return versions.first { $0.version == selectedVersion }
    }

    var newerVersion: Int? {
        adjacentVersion(offset: -1)
    }

    var olderVersion: Int? {
        adjacentVersion(offset: 1)
    }

    func replaceEndpoints(_ values: [ResearchGraphEndpoint]) {
        guard values != endpoints else { return }
        endpoints = values
        if !values.contains(where: { $0.id == selectedEndpointID }) {
            selectedEndpointID = values.first?.id
            versions = []
            selectedVersion = nil
            activeVersion = nil
        }
    }

    func selectVersion(_ version: Int) {
        guard versions.contains(where: { $0.version == version }) else {
            return
        }
        selectedVersion = version
    }

    private func adjacentVersion(offset: Int) -> Int? {
        guard let selectedVersion,
              let index = versions.firstIndex(where: {
                  $0.version == selectedVersion
              }) else { return nil }
        let target = index + offset
        guard versions.indices.contains(target) else { return nil }
        return versions[target].version
    }

    func refresh() async {
        guard let endpoint = endpoints.first(where: {
            $0.id == selectedEndpointID
        }) else {
            versions = []
            selectedVersion = nil
            activeVersion = nil
            return
        }
        isLoading = true
        error = nil
        defer { isLoading = false }
        do {
            let loaded = try await load(endpoint)
            versions = loaded.versions.sorted { $0.version > $1.version }
            activeVersion = loaded.active?.version
            if let selectedVersion,
               versions.contains(where: { $0.version == selectedVersion }) {
                return
            }
            selectedVersion = activeVersion ?? versions.first?.version
        } catch {
            self.error = error.localizedDescription
            versions = []
            selectedVersion = nil
            activeVersion = nil
        }
    }
}
