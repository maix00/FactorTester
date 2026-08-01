import Foundation

enum ResearchReportNavigationBehavior: Equatable {
    case instant
    case smooth
}

struct ResearchReportScrollRequest: Equatable {
    let componentID: String
    let token: Int
    let behavior: ResearchReportNavigationBehavior
    let chapterOffset: CGFloat

    init(
        componentID: String,
        token: Int,
        behavior: ResearchReportNavigationBehavior,
        chapterOffset: CGFloat = 0
    ) {
        self.componentID = componentID
        self.token = token
        self.behavior = behavior
        self.chapterOffset = max(0, chapterOffset)
    }
}

struct ResearchReportReadingAnchor: Equatable {
    let componentID: String
    let chapterOffset: CGFloat
}

enum ResearchReportChapterViewport {
    static func shouldReportVisibleChapter(
        _ activeID: String,
        after lastReportedID: String
    ) -> Bool {
        !activeID.isEmpty && activeID != lastReportedID
    }

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

    static func readingAnchor(
        positions: [String: CGFloat],
        orderedIDs: [String]
    ) -> ResearchReportReadingAnchor? {
        guard let componentID = activeID(
            positions: positions,
            orderedIDs: orderedIDs
        ), let position = positions[componentID] else { return nil }
        return ResearchReportReadingAnchor(
            componentID: componentID,
            chapterOffset: max(0, -position)
        )
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

enum ResearchReportScrollAnchorMath {
    static func restoredOffset(
        previousOffset: CGFloat,
        previousContentHeight: CGFloat,
        newContentHeight: CGFloat
    ) -> CGFloat {
        previousOffset + max(0, newContentHeight - previousContentHeight)
    }

    static func restoredReadingOffset(
        currentOffset: CGFloat,
        chapterOffset: CGFloat
    ) -> CGFloat {
        currentOffset + max(0, chapterOffset)
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
        let roots = Set(components.filter { $0.parentID == nil }.map(\.id))
        return outlineIDs.filter(roots.contains)
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

    func containsNavigationBuffer(
        around componentID: String,
        minimumNeighborCount: Int = 2
    ) -> Bool {
        guard let focus = outlineIDs.firstIndex(of: componentID) else {
            return false
        }
        let distance = max(0, minimumNeighborCount)
        let lower = max(outlineIDs.startIndex, focus - distance)
        let upper = min(outlineIDs.endIndex, focus + distance + 1)
        let loaded = Set(rootComponentIDs)
        return outlineIDs[lower..<upper].allSatisfy(loaded.contains)
    }

    mutating func apply(
        _ payload: ResearchReportTreePayload,
        focusedAt _: String?
    ) -> ResearchReportDocumentApplyResult {
        let generationChanged = generation != payload.generation
        let oldRootIDs = rootComponentIDs
        let incomingRootIDs = payload.components
            .filter { $0.parentID == nil }
            .map(\.id)
        let overlaps = !Set(oldRootIDs).isDisjoint(with: incomingRootIDs)
        let shouldMerge = !generationChanged && overlaps

        title = payload.title
        generation = payload.generation
        outline = payload.outline
        outlineIDs = payload.outlineIDs
        assets = payload.assets
        if shouldMerge {
            components = Self.mergeByID(components, payload.components)
            bindings = Self.mergeByID(bindings, payload.bindings)
        } else {
            components = payload.components
            bindings = payload.bindings
        }
        let nextRootIDs = rootComponentIDs
        let oldFirstIndex = oldRootIDs.first.flatMap(outlineIDs.firstIndex)
        let nextFirstIndex = nextRootIDs.first.flatMap(outlineIDs.firstIndex)
        let result = ResearchReportDocumentApplyResult(
            generationChanged: generationChanged,
            windowChanged: oldRootIDs != nextRootIDs,
            prependedChapters: shouldMerge
                && nextFirstIndex.map { next in
                    oldFirstIndex.map { next < $0 } ?? false
                } ?? false
        )
        ResearchReportPerformance.recordWindowApply(
            chapterCount: nextRootIDs.count,
            prepended: result.prependedChapters,
            generationChanged: result.generationChanged
        )
        return result
    }

    private static func mergeByID<Value: Identifiable>(
        _ existing: [Value],
        _ incoming: [Value]
    ) -> [Value] where Value.ID == String {
        let replacements = Dictionary(
            incoming.map { ($0.id, $0) },
            uniquingKeysWith: { _, latest in latest }
        )
        let existingIDs = Set(existing.map(\.id))
        return existing.map { replacements[$0.id] ?? $0 }
            + incoming.filter { !existingIDs.contains($0.id) }
    }
}

struct ResearchReportDocumentApplyResult: Equatable {
    let generationChanged: Bool
    let windowChanged: Bool
    let prependedChapters: Bool
}
