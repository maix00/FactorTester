import Foundation

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
