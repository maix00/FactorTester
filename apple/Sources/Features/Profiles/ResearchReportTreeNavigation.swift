import Foundation

enum ResearchReportTreeNavigation {
    static func sectionRefs(
        for artifact: ResearchArtifactModel
    ) -> [String: String] {
        Dictionary(
            artifact.sectionRefs.map { ($0.targetRef, $0.sectionRef) },
            uniquingKeysWith: { first, _ in first }
        )
    }

    static func componentID(
        for checkpointRef: String,
        artifact: ResearchArtifactModel,
        steps: [ResearchTransitionStep],
        workPackage: ProfileResearchWorkPackageDetail
    ) -> String? {
        let refs = sectionRefs(for: artifact)
        if let id = refs[checkpointRef] { return id }
        if let step = steps.first(where: { $0.stepRef == checkpointRef }) {
            return refs["node:\(step.toNode)"]
        }
        if let node = workPackage.tree?.nodes.first(
            where: { $0.checkpointRef == checkpointRef }
        ) {
            return refs["node:\(node.toNode)"]
        }
        return nil
    }

    static func neighbors(
        focused: String,
        outline: [String]
    ) -> [String] {
        guard let index = outline.firstIndex(of: focused) else { return [] }
        let previous = outline.indices.contains(index - 1)
            ? outline[index - 1] : nil
        let next = outline.indices.contains(index + 1)
            ? outline[index + 1] : nil
        return [previous, next].compactMap { $0 }
    }
}
