import Foundation

/// A transient cache for adjacent chapters.  The on-disk report tree remains
/// authoritative; changing HEAD advances the generation and evicts this view
/// cache rather than retaining historical report roots.
final class ResearchReportTreeNodeCache: @unchecked Sendable {
    static let shared = ResearchReportTreeNodeCache()

    private struct Key: Hashable {
        let reportPath: String
        let generation: Int
        let reference: String
    }

    private struct Entry {
        let state: ResearchReportTreeNodeLoader.TreeState
        let cost: Int
        var lastAccess: UInt64
    }

    private struct OutlineEntry {
        let value: ResearchReportTreeOutline
        var lastAccess: UInt64
    }

    private let lock = NSLock()
    private var entries: [Key: Entry] = [:]
    private var outlines: [Key: OutlineEntry] = [:]
    private var accessCounter: UInt64 = 0
    private var totalCost = 0

    private let maximumEntryCount = 24
    private let maximumTotalCost = 8_192
    private let maximumOutlineCount = 8

    func value(
        reportPath: String, generation: Int, reference: String
    ) -> ResearchReportTreeNodeLoader.TreeState? {
        lock.lock()
        defer { lock.unlock() }
        let key = Key(
            reportPath: reportPath, generation: generation, reference: reference
        )
        guard var entry = entries[key] else { return nil }
        entry.lastAccess = nextAccess()
        entries[key] = entry
        return entry.state
    }

    func insert(
        _ state: ResearchReportTreeNodeLoader.TreeState,
        reportPath: String, generation: Int, reference: String
    ) {
        lock.lock()
        defer { lock.unlock() }
        let key = Key(
            reportPath: reportPath, generation: generation, reference: reference
        )
        if let previous = entries[key] {
            totalCost -= previous.cost
        }
        let cost = max(1, state.components.count + state.bindings.count)
        entries[key] = Entry(
            state: state,
            cost: cost,
            lastAccess: nextAccess()
        )
        totalCost += cost
        trimEntries()
    }

    func outline(
        reportPath: String, generation: Int, reference: String
    ) -> ResearchReportTreeOutline? {
        lock.lock()
        defer { lock.unlock() }
        let key = Key(
            reportPath: reportPath, generation: generation, reference: reference
        )
        guard var entry = outlines[key] else { return nil }
        entry.lastAccess = nextAccess()
        outlines[key] = entry
        return entry.value
    }

    func insertOutline(
        _ value: ResearchReportTreeOutline,
        reportPath: String,
        generation: Int,
        reference: String
    ) {
        lock.lock()
        defer { lock.unlock() }
        outlines[Key(
            reportPath: reportPath, generation: generation, reference: reference
        )] = OutlineEntry(value: value, lastAccess: nextAccess())
        trimOutlines()
    }

    func retainCurrentGeneration(reportPath: String, generation: Int) {
        lock.lock()
        defer { lock.unlock() }
        entries = entries.filter {
            $0.key.reportPath != reportPath || $0.key.generation == generation
        }
        totalCost = entries.values.reduce(0) { $0 + $1.cost }
        outlines = outlines.filter {
            $0.key.reportPath != reportPath || $0.key.generation == generation
        }
    }

    private func nextAccess() -> UInt64 {
        accessCounter &+= 1
        return accessCounter
    }

    private func trimEntries() {
        while entries.count > maximumEntryCount
            || totalCost > maximumTotalCost {
            guard let oldest = entries.min(by: {
                $0.value.lastAccess < $1.value.lastAccess
            }) else { return }
            totalCost -= oldest.value.cost
            entries.removeValue(forKey: oldest.key)
        }
    }

    private func trimOutlines() {
        while outlines.count > maximumOutlineCount {
            guard let oldest = outlines.min(by: {
                $0.value.lastAccess < $1.value.lastAccess
            }) else { return }
            outlines.removeValue(forKey: oldest.key)
        }
    }
}

struct ResearchReportTreeOutline {
    let items: [ResearchReportTreeNodeLoader.OutlineItem]
    let details: [ResearchReportOutlineItem]
}
