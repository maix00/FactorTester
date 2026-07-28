import Foundation

struct ResearchReportTreePayload {
    let title: String
    let generation: Int
    let focusedComponentID: String?
    let outlineIDs: [String]
    let loadedComponentIDs: [String]
    let components: [ResearchDocumentComponent]
    let assets: [ResearchDocumentAsset]
    let bindings: [ResearchDocumentBinding]
}

enum ResearchReportTreeSource {
    static func load(
        localRef: String, focusedComponentID: String?, windowRadius: Int = 0
    ) async throws -> ResearchReportTreePayload {
        guard let headURL = URL(string: localRef), headURL.isFileURL else {
            throw ResearchReportTreeSourceError.invalidURL
        }
        return try await Task.detached {
            let head = try ResearchReportTreeNodeLoader.readHead(at: headURL)
            let first = try Metadata(head: head, headURL: headURL)
            do {
                return try loadPayload(
                    first, focusedComponentID: focusedComponentID,
                    windowRadius: windowRadius
                )
            } catch {
                let retryHead = try ResearchReportTreeNodeLoader.readHead(at: headURL)
                let retry = try Metadata(head: retryHead, headURL: headURL)
                guard retry.generation != first.generation else { throw error }
                return try loadPayload(
                    retry, focusedComponentID: focusedComponentID,
                    windowRadius: windowRadius
                )
            }
        }.value
    }

    private static func loadPayload(
        _ metadata: Metadata, focusedComponentID: String?, windowRadius: Int
    ) throws -> ResearchReportTreePayload {
        let root = try ResearchReportTreeNodeLoader.readNode(
            reference: metadata.rootRef, root: metadata.authoringRoot
        )
        let outline = try ResearchReportTreeNodeLoader.outline(
            from: root, root: metadata.authoringRoot
        )
        let focused = focusedComponentID.flatMap { wanted in
            outline.first(where: { $0.id == wanted })
        } ?? outline.last
        let outlineIDs = outline.map(\.id)
        let loadedIDs = ResearchReportChapterWindow.loadedIDs(
            outlineIDs: outlineIDs, focusedID: focused?.id,
            radius: windowRadius
        )
        var state = ResearchReportTreeNodeLoader.TreeState()
        for item in outline where loadedIDs.contains(item.id) {
            state.merge(try ResearchReportTreeNodeLoader.loadSubtree(
                reference: item.reference, parentID: nil,
                root: metadata.authoringRoot
            ))
        }
        return ResearchReportTreePayload(
            title: metadata.title, generation: metadata.generation,
            focusedComponentID: focused?.id, outlineIDs: outlineIDs,
            loadedComponentIDs: loadedIDs,
            components: state.components, assets: metadata.assets,
            bindings: state.bindings
        )
    }

    static func prefetch(localRef: String, componentIDs: [String]) async {
        guard !componentIDs.isEmpty,
              let headURL = URL(string: localRef), headURL.isFileURL else { return }
        _ = try? await Task.detached {
            let head = try ResearchReportTreeNodeLoader.readHead(at: headURL)
            let metadata = try Metadata(head: head, headURL: headURL)
            let root = try ResearchReportTreeNodeLoader.readNode(
                reference: metadata.rootRef, root: metadata.authoringRoot
            )
            let wanted = Set(componentIDs)
            for item in try ResearchReportTreeNodeLoader.outline(
                from: root, root: metadata.authoringRoot
            )
            where wanted.contains(item.id) {
                _ = try ResearchReportTreeNodeLoader.loadSubtree(
                    reference: item.reference, parentID: nil,
                    root: metadata.authoringRoot
                )
            }
        }.value
    }
}

private struct Metadata {
    let title: String
    let generation: Int
    let rootRef: String
    let assets: [ResearchDocumentAsset]
    let authoringRoot: URL

    init(head: [String: Any], headURL: URL) throws {
        guard head["schema_version"] as? Int == 2,
              let title = head["title"] as? String,
              let generation = head["generation"] as? Int,
              let rootRef = head["root_ref"] as? String else {
            throw ResearchReportTreeSourceError.invalidHead
        }
        self.title = title
        self.generation = generation
        self.rootRef = rootRef
        self.assets = (head["assets"] as? [[String: Any]] ?? [])
            .compactMap(ResearchDocumentParser.parseAsset)
        self.authoringRoot = headURL.deletingLastPathComponent()
    }
}

enum ResearchReportTreeSourceError: LocalizedError {
    case invalidURL
    case invalidHead
    case invalidNode

    var errorDescription: String? {
        switch self {
        case .invalidURL: return L10n.text("报告树本地引用无效")
        case .invalidHead: return L10n.text("报告树 HEAD 格式无效")
        case .invalidNode: return L10n.text("报告树节点格式无效")
        }
    }
}
