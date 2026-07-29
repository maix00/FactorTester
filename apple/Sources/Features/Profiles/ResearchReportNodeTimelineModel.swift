import Foundation

struct ResearchReportNodeTimelineItem: Identifiable, Equatable {
    let id: String
    let componentID: String
    let title: String
    let preview: String
    let timestamp: Double
    let graphVersion: String
}

enum ResearchReportNodeTimelineBuilder {
    static func items(
        detail: ProfileResearchDetail,
        workPackage: ProfileResearchWorkPackageDetail,
        steps: [ResearchTransitionStep],
        artifact: ResearchArtifactModel,
        reportOutline: [ResearchReportOutlineItem] = []
    ) -> [ResearchReportNodeTimelineItem] {
        if !reportOutline.isEmpty {
            return itemsFromReportOutline(
                reportOutline, workPackage: workPackage
            )
        }
        let refs = ResearchReportTreeNavigation.sectionRefs(for: artifact)
        if let tree = workPackage.tree {
            let nodes = tree.nodes
                .filter { $0.branchRef == detail.branchRef }
                .sorted { lhs, rhs in
                    lhs.sequenceRank == rhs.sequenceRank
                        ? lhs.createdAt < rhs.createdAt
                        : lhs.sequenceRank < rhs.sequenceRank
                }
            let values = nodes.compactMap { node in
                item(
                    componentID: refs[node.checkpointRef]
                        ?? refs["node:\(node.toNode)"],
                    title: node.toNode,
                    timestamp: node.createdAt,
                    graphRef: node.graphRef
                )
            }
            if !values.isEmpty { return unique(values) }
        }
        return unique(steps.sorted { $0.createdAt < $1.createdAt }.compactMap {
            item(
                componentID: refs[$0.stepRef] ?? refs["node:\($0.toNode)"],
                title: $0.toNode,
                timestamp: $0.createdAt,
                graphRef: ""
            )
        })
    }

    private static func itemsFromReportOutline(
        _ outline: [ResearchReportOutlineItem],
        workPackage: ProfileResearchWorkPackageDetail
    ) -> [ResearchReportNodeTimelineItem] {
        let nodes = workPackage.tree?.nodes ?? []
        return outline.map { item in
            let references = Set(item.references)
            let node = nodes.first {
                references.contains($0.checkpointRef)
                    || references.contains($0.traceRef)
                    || references.contains("node:\($0.toNode)")
            }
            return ResearchReportNodeTimelineItem(
                id: item.componentID,
                componentID: item.componentID,
                title: node.map { ResearchDisplayText.node($0.toNode) }
                    ?? item.fallbackTitle,
                preview: item.fallbackTitle == item.title
                    ? "" : item.fallbackTitle,
                timestamp: node?.createdAt ?? item.createdAt,
                graphVersion: node?.graphRef.split(separator: "@")
                    .last.map(String.init) ?? ""
            )
        }
    }

    static func initialComponentID(
        detail: ProfileResearchDetail,
        workPackage: ProfileResearchWorkPackageDetail,
        steps: [ResearchTransitionStep],
        artifact: ResearchArtifactModel,
        items: [ResearchReportNodeTimelineItem]
    ) -> String? {
        let latest = detail.latestTraceRef
            ?? (detail.currentNode.isEmpty ? "" : "node:\(detail.currentNode)")
        return ResearchReportTreeNavigation.componentID(
            for: latest, artifact: artifact, steps: steps, workPackage: workPackage
        ) ?? items.last?.componentID
    }

    private static func item(
        componentID: String?, title: String, timestamp: Double, graphRef: String
    ) -> ResearchReportNodeTimelineItem? {
        guard let componentID, !componentID.isEmpty else { return nil }
        return ResearchReportNodeTimelineItem(
            id: componentID,
            componentID: componentID,
            title: ResearchDisplayText.node(title),
            preview: "",
            timestamp: timestamp,
            graphVersion: graphRef.split(separator: "@").last.map(String.init) ?? ""
        )
    }

    private static func unique(
        _ values: [ResearchReportNodeTimelineItem]
    ) -> [ResearchReportNodeTimelineItem] {
        var seen = Set<String>()
        return values.filter { seen.insert($0.componentID).inserted }
    }
}

enum ResearchReportHeadFollow {
    /// Follows a newly appended chapter only while the reader is already at
    /// the previous tail. A reader inspecting an earlier node keeps context.
    static func nextChapter(
        previousOutline: [String], selectedID: String, centeredID: String,
        newOutline: [String]
    ) -> String? {
        guard let previousTail = previousOutline.last,
              let newTail = newOutline.last,
              previousTail != newTail,
              selectedID == previousTail || centeredID == previousTail
        else { return nil }
        return newTail
    }
}

enum ResearchReportNodeTimelineText {
    static func timestamp(_ value: Double) -> String {
        guard value > 0 else { return "" }
        return Date(timeIntervalSince1970: value).formatted(
            .dateTime.locale(L10n.locale)
                .month(.twoDigits).day(.twoDigits)
                .hour(.twoDigits(amPM: .omitted)).minute(.twoDigits)
        )
    }
}
