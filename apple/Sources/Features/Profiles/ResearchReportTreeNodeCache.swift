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

    private let lock = NSLock()
    private var entries: [Key: ResearchReportTreeNodeLoader.TreeState] = [:]

    func value(
        reportPath: String, generation: Int, reference: String
    ) -> ResearchReportTreeNodeLoader.TreeState? {
        lock.lock()
        defer { lock.unlock() }
        return entries[Key(
            reportPath: reportPath, generation: generation, reference: reference
        )]
    }

    func insert(
        _ state: ResearchReportTreeNodeLoader.TreeState,
        reportPath: String, generation: Int, reference: String
    ) {
        lock.lock()
        defer { lock.unlock() }
        entries[Key(
            reportPath: reportPath, generation: generation, reference: reference
        )] = state
    }

    func retainCurrentGeneration(reportPath: String, generation: Int) {
        lock.lock()
        defer { lock.unlock() }
        entries = entries.filter {
            $0.key.reportPath != reportPath || $0.key.generation == generation
        }
    }
}
