import Foundation

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
        let mergedComponents = shouldMerge
            ? Self.mergeByID(components, payload.components)
            : payload.components
        let retainedRootIDs = Set(payload.loadedComponentIDs)
        components = Self.retainingSubtrees(
            mergedComponents,
            rootedAt: retainedRootIDs
        )
        let retainedComponentIDs = Set(components.map(\.id))
        let mergedBindings = shouldMerge
            ? Self.mergeByID(bindings, payload.bindings)
            : payload.bindings
        bindings = mergedBindings.filter {
            retainedComponentIDs.contains($0.componentID)
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

    private static func retainingSubtrees(
        _ components: [ResearchDocumentComponent],
        rootedAt retainedRootIDs: Set<String>
    ) -> [ResearchDocumentComponent] {
        guard !retainedRootIDs.isEmpty else { return [] }
        let parentByID = Dictionary(
            components.map { ($0.id, $0.parentID) },
            uniquingKeysWith: { _, latest in latest }
        )
        var membership: [String: Bool] = [:]

        func isRetained(_ component: ResearchDocumentComponent) -> Bool {
            if let cached = membership[component.id] { return cached }
            var cursor: String? = component.id
            var visited = Set<String>()
            while let id = cursor, visited.insert(id).inserted {
                if retainedRootIDs.contains(id) {
                    membership[component.id] = true
                    return true
                }
                cursor = parentByID[id] ?? nil
            }
            membership[component.id] = false
            return false
        }

        return components.filter(isRetained)
    }
}

struct ResearchReportDocumentApplyResult: Equatable {
    let generationChanged: Bool
    let windowChanged: Bool
    let prependedChapters: Bool
}
