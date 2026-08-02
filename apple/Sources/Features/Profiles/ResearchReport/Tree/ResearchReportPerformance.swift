import Foundation
import os.signpost

enum ResearchReportPerformance {
    private static let log = OSLog(
        subsystem: Bundle.main.bundleIdentifier ?? "com.gtht.client",
        category: "ResearchReport"
    )

    static func beginLoad() -> OSSignpostID {
        let id = OSSignpostID(log: log)
        os_signpost(.begin, log: log, name: "ReportLoad", signpostID: id)
        return id
    }

    static func endLoad(_ id: OSSignpostID) {
        os_signpost(.end, log: log, name: "ReportLoad", signpostID: id)
    }

    static func recordChapterApply(
        chapterCount: Int,
        generationChanged: Bool
    ) {
        os_signpost(
            .event,
            log: log,
            name: "ChapterApply",
            "chapters=%{public}d generation=%{public}d",
            chapterCount,
            generationChanged ? 1 : 0
        )
    }
}
