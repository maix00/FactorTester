import Foundation

private struct OwnedResearchPublicationResponse: Decodable {
    let reports: [OwnedResearchPublication]
}

private struct OwnedResearchPublication: Decodable {
    let reportID: String

    private enum CodingKeys: String, CodingKey {
        case reportID = "report_id"
    }
}

@MainActor
final class ResearchPublicationStatusController: ObservableObject {
    @Published private(set) var sharedReportIDs: Set<String> = []

    func refresh() async {
        guard let url = ManagerConfig.shared.url(
            forPath: "/api/research-publications/settings"
        ) else { return }
        var request = URLRequest(url: url)
        let token = ManagerSessionTokenStore.read()
        if !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        request.cachePolicy = .reloadIgnoringLocalCacheData
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse,
                  (200..<300).contains(http.statusCode) else { return }
            let value = try JSONDecoder().decode(
                OwnedResearchPublicationResponse.self,
                from: data
            )
            sharedReportIDs = Set(value.reports.map(\.reportID))
        } catch {
            // Sharing status is supplementary metadata. A transient Manager
            // failure must never hide or block the native local research list.
        }
    }
}
