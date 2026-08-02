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

    mutating func apply(
        _ payload: ResearchReportTreePayload,
        focusedAt _: String?
    ) -> ResearchReportDocumentApplyResult {
        let generationChanged = generation != payload.generation
        title = payload.title
        generation = payload.generation
        outline = payload.outline
        outlineIDs = payload.outlineIDs
        assets = payload.assets
        let oldRootIDs = rootComponentIDs
        components = payload.components
        bindings = payload.bindings
        let nextRootIDs = rootComponentIDs
        let result = ResearchReportDocumentApplyResult(
            generationChanged: generationChanged,
            chapterChanged: oldRootIDs != nextRootIDs
        )
        ResearchReportPerformance.recordChapterApply(
            chapterCount: nextRootIDs.count,
            generationChanged: result.generationChanged
        )
        return result
    }

}

struct ResearchReportDocumentApplyResult: Equatable {
    let generationChanged: Bool
    let chapterChanged: Bool
}
