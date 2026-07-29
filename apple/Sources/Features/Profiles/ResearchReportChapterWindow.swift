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

enum ResearchReportChapterWindow {
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
        focusedAt componentID: String?
    ) -> ResearchReportDocumentApplyResult {
        let generationChanged = generation != payload.generation
        let disconnected = !rootComponentIDs.isEmpty
            && !windowsTouch(
                existing: rootComponentIDs,
                incoming: payload.loadedComponentIDs,
                outline: payload.outlineIDs
            )
        let replace = generationChanged || disconnected
        let oldRootIDs = Set(rootComponentIDs)

        title = payload.title
        generation = payload.generation
        outline = payload.outline
        outlineIDs = payload.outlineIDs
        assets = payload.assets
        if replace {
            components = payload.components
            bindings = payload.bindings
        } else {
            components = merged(
                components, payload.components, id: \.id
            )
            bindings = merged(bindings, payload.bindings, id: \.id)
        }

        let focusIndex = componentID.flatMap(outlineIDs.firstIndex)
        let addedBeforeFocus = focusIndex.map { focus in
            Set(rootComponentIDs).subtracting(oldRootIDs).contains { id in
                outlineIDs.firstIndex(of: id).map { $0 < focus } ?? false
            }
        } ?? false
        return ResearchReportDocumentApplyResult(
            replaced: replace,
            addedBeforeFocus: addedBeforeFocus
        )
    }

    private func windowsTouch(
        existing: [String],
        incoming: [String],
        outline: [String]
    ) -> Bool {
        let existingIndices = existing.compactMap(outline.firstIndex)
        let incomingIndices = incoming.compactMap(outline.firstIndex)
        guard let existingMin = existingIndices.min(),
              let existingMax = existingIndices.max(),
              let incomingMin = incomingIndices.min(),
              let incomingMax = incomingIndices.max() else {
            return false
        }
        return incomingMin <= existingMax + 1
            && existingMin <= incomingMax + 1
    }

    private func merged<Value>(
        _ existing: [Value],
        _ incoming: [Value],
        id: KeyPath<Value, String>
    ) -> [Value] {
        let updates = Dictionary(
            uniqueKeysWithValues: incoming.map { ($0[keyPath: id], $0) }
        )
        var seen = Set<String>()
        var values = existing.map { value in
            let key = value[keyPath: id]
            seen.insert(key)
            return updates[key] ?? value
        }
        values.append(contentsOf: incoming.filter {
            seen.insert($0[keyPath: id]).inserted
        })
        return values
    }
}

struct ResearchReportDocumentApplyResult: Equatable {
    let replaced: Bool
    let addedBeforeFocus: Bool
}
