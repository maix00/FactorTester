import Foundation

struct ResearchReportTreePayload {
    let title: String
    let generation: Int
    let focusedComponentID: String?
    let outline: [ResearchReportOutlineItem]
    let outlineIDs: [String]
    let loadedComponentIDs: [String]
    let components: [ResearchDocumentComponent]
    let assets: [ResearchDocumentAsset]
    let bindings: [ResearchDocumentBinding]
}

struct ResearchReportOutlineItem: Equatable {
    let componentID: String
    let title: String
    let fallbackTitle: String
    let createdAt: Double
    let references: [String]
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
            ResearchReportTreeNodeCache.shared.retainCurrentGeneration(
                reportPath: headURL.path, generation: first.generation
            )
            do {
                return try loadPayload(
                    first, focusedComponentID: focusedComponentID,
                    windowRadius: windowRadius
                )
            } catch {
                let retryHead = try ResearchReportTreeNodeLoader.readHead(at: headURL)
                let retry = try Metadata(head: retryHead, headURL: headURL)
                guard retry.generation != first.generation else { throw error }
                ResearchReportTreeNodeCache.shared.retainCurrentGeneration(
                    reportPath: headURL.path, generation: retry.generation
                )
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
        let outlineValue = try cachedOutline(metadata: metadata)
        let outline = outlineValue.items
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
                reference: item.reference, parentID: nil, root: metadata.authoringRoot,
                cachedAt: metadata
            ))
        }
        return ResearchReportTreePayload(
            title: metadata.title, generation: metadata.generation,
            focusedComponentID: focused?.id, outline: outlineValue.details,
            outlineIDs: outlineIDs,
            loadedComponentIDs: loadedIDs,
            components: state.components, assets: metadata.assets,
            bindings: state.bindings
        )
    }

    private static func cachedOutline(
        metadata: Metadata
    ) throws -> ResearchReportTreeOutline {
        if let cached = ResearchReportTreeNodeCache.shared.outline(
            reportPath: metadata.headURL.path,
            generation: metadata.generation,
            reference: metadata.rootRef
        ) {
            return cached
        }
        let root = try ResearchReportTreeNodeLoader.readNode(
            reference: metadata.rootRef, root: metadata.authoringRoot
        )
        let items = try ResearchReportTreeNodeLoader.outline(
            from: root, root: metadata.authoringRoot
        )
        let value = ResearchReportTreeOutline(
            items: items,
            details: try ResearchReportTreeNodeLoader.outlineDetails(
                items, root: metadata.authoringRoot
            )
        )
        ResearchReportTreeNodeCache.shared.insertOutline(
            value,
            reportPath: metadata.headURL.path,
            generation: metadata.generation,
            reference: metadata.rootRef
        )
        return value
    }

    static func prefetch(localRef: String, componentIDs: [String]) async {
        guard !componentIDs.isEmpty,
              let headURL = URL(string: localRef), headURL.isFileURL else { return }
        _ = try? await Task.detached {
            let head = try ResearchReportTreeNodeLoader.readHead(at: headURL)
            let metadata = try Metadata(head: head, headURL: headURL)
            ResearchReportTreeNodeCache.shared.retainCurrentGeneration(
                reportPath: headURL.path, generation: metadata.generation
            )
            let wanted = Set(componentIDs)
            for item in try cachedOutline(metadata: metadata).items
            where wanted.contains(item.id) {
                _ = try ResearchReportTreeNodeLoader.loadSubtree(
                    reference: item.reference, parentID: nil, root: metadata.authoringRoot,
                    cachedAt: metadata
                )
            }
        }.value
    }
}

private extension ResearchReportTreeNodeLoader {
    static func loadSubtree(
        reference: String, parentID: String?, root: URL, cachedAt metadata: Metadata
    ) throws -> TreeState {
        guard parentID == nil else {
            return try loadSubtree(reference: reference, parentID: parentID, root: root)
        }
        if let cached = ResearchReportTreeNodeCache.shared.value(
            reportPath: metadata.headURL.path,
            generation: metadata.generation, reference: reference
        ) {
            return cached
        }
        let state = try loadSubtree(reference: reference, parentID: nil, root: root)
        ResearchReportTreeNodeCache.shared.insert(
            state, reportPath: metadata.headURL.path,
            generation: metadata.generation, reference: reference
        )
        return state
    }
}

private struct Metadata {
    let title: String
    let generation: Int
    let rootRef: String
    let assets: [ResearchDocumentAsset]
    let authoringRoot: URL
    let headURL: URL

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
        self.headURL = headURL
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
