import Foundation

enum ResearchReportNavigationBehavior: Equatable {
    case instant
    case smooth
}

struct ResearchReportScrollRequest: Equatable {
    let componentID: String
    let token: Int
    let behavior: ResearchReportNavigationBehavior
}

enum ResearchReportChapterViewport {
    /// Selects the chapter whose top edge most recently crossed the reading
    /// anchor. This keeps a long chapter active until the next chapter
    /// actually reaches the top, instead of selecting whichever edge happens
    /// to be numerically closest.
    static func activeID(
        positions: [String: CGFloat],
        orderedIDs: [String],
        readingAnchor: CGFloat = 96
    ) -> String? {
        let visible = orderedIDs.compactMap { id in
            positions[id].map { (id, $0) }
        }
        guard !visible.isEmpty else { return nil }
        return visible.last(where: { $0.1 <= readingAnchor })?.0
            ?? visible.first?.0
    }

    static func completedScroll(
        to targetID: String,
        positions: [String: CGFloat],
        loadedIDs: [String],
        canClampAtDocumentBottom: Bool = false,
        viewportHeight: CGFloat = 0,
        readingAnchor: CGFloat = 96
    ) -> Bool {
        guard loadedIDs.contains(targetID),
              let targetPosition = positions[targetID] else {
            return false
        }
        let loaded = Set(loadedIDs)
        let loadedPositions = positions.filter { loaded.contains($0.key) }
        if activeID(
            positions: loadedPositions,
            orderedIDs: loadedIDs,
            readingAnchor: readingAnchor
        ) == targetID {
            return true
        }
        // The final chapter can be shorter than the viewport. AppKit then
        // clamps the scroll offset at the document bottom, so its top cannot
        // reach the reading anchor even though the real chapter is visible.
        return canClampAtDocumentBottom
            && viewportHeight > 0
            && targetPosition >= 0
            && targetPosition < viewportHeight
    }
}

struct ResearchReportScrollExecutionKey: Equatable {
    let token: Int
    let targetIsLoaded: Bool
}

enum ResearchReportChapterWindow {
    /// Keeps enough materialized chapters around the reading position for
    /// fast wheel/trackpad traversal without mounting the whole report.
    static let navigationRadius = 5

    static func loadedIDs(
        outlineIDs: [String], focusedID: String?, radius: Int = 1
    ) -> [String] {
        guard !outlineIDs.isEmpty else { return [] }
        let focus = focusedID.flatMap { outlineIDs.firstIndex(of: $0) }
            ?? (outlineIDs.count - 1)
        let boundedRadius = max(0, radius)
        let lower = max(outlineIDs.startIndex, focus - boundedRadius)
        let upper = min(outlineIDs.endIndex, focus + boundedRadius + 1)
        return Array(outlineIDs[lower..<upper])
    }

    static func prefetchIDs(
        outlineIDs: [String], loadedIDs: [String]
    ) -> [String] {
        guard let first = loadedIDs.first,
              let last = loadedIDs.last,
              let firstIndex = outlineIDs.firstIndex(of: first),
              let lastIndex = outlineIDs.firstIndex(of: last) else {
            return []
        }
        let previous = outlineIDs.indices.contains(firstIndex - 1)
            ? outlineIDs[firstIndex - 1] : nil
        let next = outlineIDs.indices.contains(lastIndex + 1)
            ? outlineIDs[lastIndex + 1] : nil
        return [previous, next].compactMap { $0 }
    }
}

enum ResearchReportNavigationFocus {
    static func preferred(
        pendingID: String,
        selectedID: String,
        initialID: String?
    ) -> String? {
        if !pendingID.isEmpty {
            return pendingID
        }
        if !selectedID.isEmpty {
            return selectedID
        }
        return initialID
    }
}

struct ResearchReportLoadedDocument {
    private(set) var title = ""
    private(set) var generation: Int?
    private(set) var outline: [ResearchReportOutlineItem] = []
    private(set) var outlineIDs: [String] = []
    private(set) var components: [ResearchDocumentComponent] = []
    private(set) var assets: [ResearchDocumentAsset] = []
    private(set) var bindings: [ResearchDocumentBinding] = []

    var rootComponentIDs: [String] {
        components.filter { $0.parentID == nil }.map(\.id)
    }

    func containsChapter(_ componentID: String) -> Bool {
        components.contains {
            $0.parentID == nil && $0.id == componentID
        }
    }

    func containsWindow(
        centeredAt componentID: String,
        radius: Int
    ) -> Bool {
        let wanted = ResearchReportChapterWindow.loadedIDs(
            outlineIDs: outlineIDs,
            focusedID: componentID,
            radius: radius
        )
        let loaded = Set(rootComponentIDs)
        return !wanted.isEmpty && wanted.allSatisfy(loaded.contains)
    }

    mutating func apply(
        _ payload: ResearchReportTreePayload,
        focusedAt _: String?
    ) -> ResearchReportDocumentApplyResult {
        let generationChanged = generation != payload.generation
        let oldRootIDs = rootComponentIDs

        title = payload.title
        generation = payload.generation
        outline = payload.outline
        outlineIDs = payload.outlineIDs
        assets = payload.assets
        components = payload.components
        bindings = payload.bindings
        return ResearchReportDocumentApplyResult(
            generationChanged: generationChanged,
            windowChanged: oldRootIDs != rootComponentIDs
        )
    }
}

struct ResearchReportDocumentApplyResult: Equatable {
    let generationChanged: Bool
    let windowChanged: Bool
}
