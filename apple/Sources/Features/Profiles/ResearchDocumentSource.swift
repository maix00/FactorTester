import Foundation

struct ResearchDocumentPayload {
    let title: String
    let components: [ResearchDocumentComponent]
    let assets: [ResearchDocumentAsset]
}

enum ResearchDocumentSource {
    static func load(localRef: String) async throws -> ResearchDocumentPayload {
        guard let url = URL(string: localRef), url.isFileURL else {
            throw ResearchDocumentSourceError.invalidURL
        }
        return try await Task.detached {
            let data = try PersonalWorkspaceAccessStore.withAccess(to: url) {
                try Data(contentsOf: url)
            }
            guard let root = try JSONSerialization.jsonObject(with: data)
                as? [String: Any] else { throw ResearchDocumentSourceError.invalid }
            return ResearchDocumentPayload(
                title: root["title"] as? String ?? "",
                components: (root["components"] as? [[String: Any]] ?? [])
                    .compactMap(ResearchDocumentParser.parseComponent),
                assets: (root["assets"] as? [[String: Any]] ?? [])
                    .compactMap(ResearchDocumentParser.parseAsset)
            )
        }.value
    }
}

enum ResearchDocumentSourceError: Error {
    case invalidURL
    case invalid
}

final class ResearchDocumentFileObserver: NSObject, ObservableObject,
    NSFilePresenter {
    let presentedItemURL: URL?
    let presentedItemOperationQueue: OperationQueue = .main

    @Published private(set) var revision = 0
    private var observing = false

    init(localRef: String) {
        presentedItemURL = URL(string: localRef)?.isFileURL == true
            ? URL(string: localRef) : nil
    }

    func start() {
        guard !observing, presentedItemURL != nil else { return }
        observing = true
        NSFileCoordinator.addFilePresenter(self)
    }

    func stop() {
        guard observing else { return }
        observing = false
        NSFileCoordinator.removeFilePresenter(self)
    }

    func presentedItemDidChange() {
        DispatchQueue.main.async { [weak self] in
            self?.revision &+= 1
        }
    }

    deinit { stop() }
}
