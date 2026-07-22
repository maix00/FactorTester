import SwiftUI

enum ResearchTreeLayout {
    static let navigatorWidth: CGFloat = 208
    static let maximumVisibleBranches = 7
    static let laneSpacing: CGFloat = 13
    static let laneOriginX: CGFloat = 9
    static let selectedNodeDiameter: CGFloat = 17
    static let horizontalPadding: CGFloat = 8
    static let rowSpacing: CGFloat = 8
    static let minimumTimestampWidth: CGFloat = 68
    static let maximumLaneFootprint = graphColumnWidth(
        laneCount: maximumVisibleBranches
    )

    static func graphColumnWidth(laneCount: Int) -> CGFloat {
        let boundedCount = min(max(laneCount, 1), maximumVisibleBranches)
        let lastLane = boundedCount - 1
        return ceil(
            markerBounds(
                lane: lastLane,
                diameter: selectedNodeDiameter
            ).upperBound
        )
    }

    static func minimumLabelWidth(laneCount: Int) -> CGFloat {
        navigatorWidth - horizontalPadding * 2
            - graphColumnWidth(laneCount: laneCount) - rowSpacing
    }

    static func laneCenterX(_ lane: Int) -> CGFloat {
        laneOriginX + CGFloat(lane) * laneSpacing
    }

    static func canvasLaneCenterX(_ lane: Int) -> CGFloat {
        horizontalPadding + laneCenterX(lane)
    }

    static func markerBounds(
        lane: Int,
        diameter: CGFloat
    ) -> ClosedRange<CGFloat> {
        let center = laneCenterX(lane)
        return (center - diameter / 2)...(center + diameter / 2)
    }
}

enum ResearchTreeOrdering {
    static func isBefore(
        timestamp: Double,
        id: String,
        than otherTimestamp: Double,
        id otherID: String
    ) -> Bool {
        timestamp == otherTimestamp ? id < otherID : timestamp < otherTimestamp
    }
}

struct ResearchTreeHistoryMerge {
    let supplementalSteps: [ResearchTransitionStep]
    let remainingOmittedNodeCount: Int

    init(
        projection: ResearchVersionTreeProjection,
        loadedSteps: [ResearchTransitionStep]
    ) {
        let projectedRefs = Set(
            projection.nodes.map(\.checkpointRef)
        )
        supplementalSteps = loadedSteps
            .filter { !projectedRefs.contains($0.stepRef) }
            .sorted {
                ResearchTreeOrdering.isBefore(
                    timestamp: $0.createdAt,
                    id: $0.stepRef,
                    than: $1.createdAt,
                    id: $1.stepRef
                )
            }
        remainingOmittedNodeCount = max(
            projection.omittedNodeCount - supplementalSteps.count,
            0
        )
    }
}

enum ResearchTreeConnector {
    static func sourceRowIndex(
        sourceCheckpointRef: String?,
        nodeCheckpointRefs: [String]
    ) -> Int? {
        guard let sourceCheckpointRef, !sourceCheckpointRef.isEmpty else {
            return nil
        }
        return nodeCheckpointRefs.firstIndex(of: sourceCheckpointRef)
    }
}

enum ResearchTreeHeadResolver {
    static func isHead(
        projectedIsHead: Bool,
        nodeBranchRef: String,
        selectedBranchRef: String,
        checkpointRef: String,
        selectedLatestTraceRef: String?
    ) -> Bool {
        guard nodeBranchRef == selectedBranchRef else {
            return projectedIsHead
        }
        return checkpointRef == selectedLatestTraceRef
    }
}

struct ResearchTreeResolvedEdge: Equatable {
    let relation: String
    let sourceRow: Int?
    let targetRow: Int
}

enum ResearchTreeEdgeResolver {
    static func resolve(
        _ edges: [ResearchVersionTreeEdge],
        checkpointRefs: [String],
        aliases: [String: String] = [:]
    ) -> [ResearchTreeResolvedEdge] {
        var rows: [String: Int] = [:]
        for (offset, checkpointRef) in checkpointRefs.enumerated()
        where !checkpointRef.isEmpty {
            // Expanded recovery groups intentionally expose their anchor
            // checkpoint twice (group + child). Prefer the concrete child row
            // and never trap on a duplicate local presentation identity.
            rows[checkpointRef] = offset
        }
        for (hiddenRef, visibleRef) in aliases {
            if let row = rows[visibleRef] { rows[hiddenRef] = row }
        }
        var identities = Set<String>()
        return edges.compactMap { edge in
            guard let target = rows[edge.targetNodeRef] else { return nil }
            let source = rows[edge.sourceNodeRef]
            guard source != target else { return nil }
            let identity = [
                edge.relation, edge.sourceNodeRef, edge.targetNodeRef,
            ].joined(separator: "|")
            guard identities.insert(identity).inserted else { return nil }
            return ResearchTreeResolvedEdge(
                relation: edge.relation,
                sourceRow: source,
                targetRow: target
            )
        }
    }
}

struct ResearchVersionTreePane: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let sectionRefsByCheckpoint: [String: String]
    @Binding var selectedCheckpointRef: String
    let select: (_ checkpointRef: String, _ branchID: String) -> Void
    let loadEarlier: () async -> Void
    let canLoadEarlier: Bool

    private let rowHeight: CGFloat = 46
    private let laneSpacing = ResearchTreeLayout.laneSpacing
    @State private var isLoadingEarlier = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 5) {
                Text("研究版本树")
                    .font(.headline)
                Text("时间向下 · 点击定位正文")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 10) {
                        treeLegend(filled: true, label: "检查点")
                        treeLegend(filled: false, label: "分叉/承接")
                    }
                    HStack(spacing: 9) {
                        statusLegend(color: .orange, label: "暂停")
                        statusLegend(color: .green, label: "完成")
                        if hiddenBranchCount > 0 {
                            Text("另有 \(hiddenBranchCount) 条分支")
                                .font(.system(size: 9))
                                .foregroundStyle(.secondary)
                        }
                    }
                    if let omittedNodeCount = remainingOmittedNodeCount,
                       omittedNodeCount > 0 {
                        Text("尚有 \(omittedNodeCount) 个检查点未载入")
                            .font(.system(size: 9))
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 13)
            Divider()
            ScrollViewReader { proxy in
                if canLoadEarlier {
                    Button {
                        loadEarlierPreservingAnchor(proxy)
                    } label: {
                        if isLoadingEarlier {
                            ProgressView()
                                .controlSize(.small)
                                .frame(maxWidth: .infinity)
                        } else {
                            Label(
                                "更早记录",
                                systemImage: "clock.arrow.circlepath"
                            )
                            .frame(maxWidth: .infinity)
                        }
                    }
                    .buttonStyle(.plain)
                    .disabled(isLoadingEarlier)
                    .padding(12)
                    Divider()
                }
                ScrollView {
                    ZStack(alignment: .topLeading) {
                        laneBackground
                        LazyVStack(spacing: 0) {
                            ForEach(nodes) { node in
                                nodeRow(node)
                                    .id(node.id)
                            }
                        }
                    }
                    .padding(.vertical, 8)
                }
                .onChange(of: selectedCheckpointRef) { checkpointRef in
                    guard let node = nodes.first(where: {
                        represents($0, checkpointRef: checkpointRef)
                    }) else { return }
                    withAnimation(.easeInOut(duration: 0.22)) {
                        proxy.scrollTo(node.id, anchor: .center)
                    }
                }
            }
        }
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.45))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .clipped()
    }

    private var laneBackground: some View {
        Canvas { context, size in
            let visibleNodes = nodes
            for edge in resolvedEdges(for: visibleNodes) {
                let index = edge.targetRow
                let node = visibleNodes[index]
                let target = CGPoint(
                    x: ResearchTreeLayout.canvasLaneCenterX(node.lane),
                    y: (CGFloat(index) + 0.5) * rowHeight
                )
                let sourceLane = edge.sourceRow.map {
                    visibleNodes[$0].lane
                } ?? node.sourceLane ?? node.lane
                let sourceX = ResearchTreeLayout.canvasLaneCenterX(sourceLane)
                let sourceY = edge.sourceRow.map {
                    (CGFloat($0) + 0.5) * rowHeight
                } ?? target.y - 13
                let source = CGPoint(x: sourceX, y: sourceY)
                var connector = Path()
                connector.move(to: source)
                if edge.relation == "transition" && sourceX == target.x {
                    connector.addLine(to: target)
                } else {
                    connector.addCurve(
                        to: target,
                        control1: CGPoint(
                            x: sourceX,
                            y: sourceY + (target.y - sourceY) * 0.55
                        ),
                        control2: CGPoint(
                            x: target.x,
                            y: sourceY + (target.y - sourceY) * 0.55
                        )
                    )
                }
                context.stroke(
                    connector,
                    with: .color(laneColor(node.lane).opacity(
                        edge.relation == "transition" ? 0.35 : 0.75
                    )),
                    lineWidth: edge.relation == "transition" ? 1.5 : 1.8
                )
            }
        }
        .frame(height: CGFloat(nodes.count) * rowHeight)
        .allowsHitTesting(false)
    }

    private func resolvedEdges(
        for visibleNodes: [ResearchTreeNode]
    ) -> [ResearchTreeResolvedEdge] {
        guard let projection = workPackage.tree else { return [] }
        return ResearchTreeEdgeResolver.resolve(
            projection.edges,
            checkpointRefs: visibleNodes.map(\.checkpointRef)
        )
    }

    private func nodeRow(_ node: ResearchTreeNode) -> some View {
        Button {
            guard !node.checkpointRef.isEmpty,
                  !node.sectionRef.isEmpty else { return }
            select(node.checkpointRef, node.branchID)
        } label: {
            HStack(spacing: ResearchTreeLayout.rowSpacing) {
                ZStack {
                    Circle()
                        .fill(node.isLineage ? Color(nsColor: .windowBackgroundColor) : nodeColor(node))
                        .frame(width: node.isHead ? 11 : 8, height: node.isHead ? 11 : 8)
                        .overlay {
                            if node.isLineage {
                                Circle().stroke(nodeColor(node), lineWidth: 2)
                            }
                        }
                    if represents(node, checkpointRef: selectedCheckpointRef) {
                        Circle()
                            .stroke(Color.accentColor, lineWidth: 2)
                            .frame(
                                width: ResearchTreeLayout.selectedNodeDiameter,
                                height: ResearchTreeLayout.selectedNodeDiameter
                            )
                    }
                }
                .frame(
                    width: ResearchTreeLayout.selectedNodeDiameter,
                    height: ResearchTreeLayout.selectedNodeDiameter
                )
                .offset(
                    x: ResearchTreeLayout.markerBounds(
                        lane: node.lane,
                        diameter: ResearchTreeLayout.selectedNodeDiameter
                    ).lowerBound
                )
                .frame(
                    width: ResearchTreeLayout.graphColumnWidth(
                        laneCount: laneCount
                    ),
                    height: rowHeight,
                    alignment: .leading
                )

                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 4) {
                        Text(node.title)
                            .font(.caption.weight(node.isHead ? .semibold : .regular))
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer(minLength: 2)
                        if !node.graphRef.isEmpty {
                            Text(graphVersion(node.graphRef))
                                .font(.system(size: 8, weight: .semibold))
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 4)
                                .padding(.vertical, 1)
                                .background(
                                    Color.secondary.opacity(0.08),
                                    in: Capsule()
                                )
                                .fixedSize()
                        }
                        if node.isHead {
                            Text("HEAD")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundStyle(
                                    node.isCurrentHead
                                        ? Color.accentColor : Color.secondary
                                )
                        }
                        if node.isRoot {
                            Text("根")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundStyle(.secondary)
                        }
                    }
                    Text(node.subtitle)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .frame(
                            minWidth: ResearchTreeLayout.minimumTimestampWidth,
                            alignment: .leading
                        )
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .clipped()
                Spacer(minLength: 0)
            }
            .frame(height: rowHeight)
            .padding(.horizontal, ResearchTreeLayout.horizontalPadding)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(node.sectionRef.isEmpty)
        .accessibilityLabel("\(node.title)，\(node.subtitle)")
        .accessibilityIdentifier("research.tree.node.\(node.id)")
    }

    private var nodes: [ResearchTreeNode] {
        if let projection = workPackage.tree,
           !projection.nodes.isEmpty {
            return projectedNodes(projection)
        }
        let rootStepRef = steps.min {
            ResearchTreeOrdering.isBefore(
                timestamp: $0.createdAt,
                id: $0.id,
                than: $1.createdAt,
                id: $1.id
            )
        }?.stepRef
        let selectedLineage = visibleBranches.first {
            $0.branchRef == detail.branchRef
        }?.lineage
        var result = steps.map { step in
            ResearchTreeNode(
                id: "step|\(step.stepRef)",
                checkpointRef: step.stepRef,
                sectionRef: sectionRefsByCheckpoint[step.stepRef] ?? "",
                title: ResearchDisplayText.node(step.toNode),
                subtitle: ResearchTreeTimestamp.text(step.createdAt),
                timestamp: step.createdAt,
                lane: selectedLane,
                status: step.status
                    ?? (step.stepRef == detail.latestTraceRef
                        ? detail.status : "historical"),
                isHead: step.stepRef == detail.latestTraceRef,
                isCurrentHead: step.stepRef == detail.latestTraceRef,
                isRoot: step.stepRef == rootStepRef
                    && selectedLineage?.relation == "root",
                isLineage: false,
                sourceLane: nil,
                sourceCheckpointRef: nil,
                branchID: branchID(for: detail.branchRef)
            )
        }
        for branch in visibleBranches {
            let branchLane = lane(for: branch.branchRef)
            if branch.branchRef != detail.branchRef {
                result.append(ResearchTreeNode(
                    id: "branch|\(branch.branchRef)",
                    checkpointRef: branch.latestTraceRef ?? "",
                    sectionRef: branch.latestTraceRef.flatMap {
                        sectionRefsByCheckpoint[$0]
                    } ?? "",
                    title: ResearchDisplayText.branchLabel(
                        branch.label,
                        currentNode: branch.currentNode
                    ),
                    subtitle: treeStatusLabel(branch.status),
                    timestamp: branch.updatedAt,
                    lane: branchLane,
                    status: branch.status,
                    isHead: true,
                    isCurrentHead: false,
                    isRoot: false,
                    isLineage: false,
                    sourceLane: nil,
                    sourceCheckpointRef: nil,
                    branchID: branch.branchID
                ))
            }
            if let lineage = branch.lineage,
               ["fork", "continuation"].contains(lineage.relation),
               let sourceBranchRef = lineage.sourceBranchRef {
                let sourceIndex = visibleBranches.firstIndex {
                    $0.branchRef == sourceBranchRef
                }
                let sourceLabel = sourceIndex.map {
                    ResearchDisplayText.branchLabel(
                        visibleBranches[$0].label,
                        currentNode: visibleBranches[$0].currentNode
                    )
                } ?? "较早研究分支"
                result.append(ResearchTreeNode(
                    id: "lineage|\(branch.branchRef)",
                    checkpointRef: "",
                    sectionRef: "",
                    title: lineage.relation == "fork"
                        ? "从 \(sourceLabel) 分叉"
                        : "沿用 \(sourceLabel) 的研究证据",
                    subtitle: sourceIndex == nil ? "来源未载入" : "已验证来源",
                    timestamp: branch.createdAt,
                    lane: branchLane,
                    status: branch.status,
                    isHead: false,
                    isCurrentHead: false,
                    isRoot: false,
                    isLineage: true,
                    sourceLane: sourceIndex,
                    sourceCheckpointRef: lineage.sourceTraceRef,
                    branchID: branch.branchID
                ))
            }
        }
        return result.sorted {
            ResearchTreeOrdering.isBefore(
                timestamp: $0.timestamp,
                id: $0.id,
                than: $1.timestamp,
                id: $1.id
            )
        }
    }

    private func projectedNodes(
        _ projection: ResearchVersionTreeProjection
    ) -> [ResearchTreeNode] {
        let lineageByTarget = Dictionary(
            projection.edges.filter {
                $0.relation == "fork" || $0.relation == "continuation"
            }.map { ($0.targetNodeRef, $0) },
            uniquingKeysWith: { first, _ in first }
        )
        var result = projection.nodes.map { node in
            let lineage = lineageByTarget[node.nodeRef]
            let sourceLane = lineage.flatMap { edge in
                visibleBranches.firstIndex {
                    $0.branchRef == edge.sourceBranchRef
                }
            }
            let isHead = ResearchTreeHeadResolver.isHead(
                projectedIsHead: node.isHead,
                nodeBranchRef: node.branchRef,
                selectedBranchRef: detail.branchRef,
                checkpointRef: node.checkpointRef,
                selectedLatestTraceRef: detail.latestTraceRef
            )
            let isContinuation = node.edgeRef.contains(
                "__graph_continuation__"
            ) || lineage?.relation == "continuation"
            let sourceGraphRef = lineage.flatMap { edge in
                projection.nodes.first {
                    $0.nodeRef == edge.sourceNodeRef
                        || $0.checkpointRef == edge.sourceNodeRef
                }?.graphRef
            }
            return ResearchTreeNode(
                id: "checkpoint|\(node.nodeRef)",
                checkpointRef: node.checkpointRef,
                sectionRef: sectionRefsByCheckpoint[node.checkpointRef] ?? "",
                title: isContinuation
                    ? continuationTitle(
                        from: sourceGraphRef,
                        to: node.graphRef
                    )
                    : ResearchDisplayText.node(node.toNode),
                subtitle: ResearchTreeTimestamp.text(node.createdAt),
                timestamp: node.createdAt,
                lane: lane(for: node.branchRef),
                status: node.status,
                isHead: isHead,
                isCurrentHead: node.branchRef == detail.branchRef
                    && isHead,
                isRoot: node.isRoot,
                isLineage: lineage != nil,
                sourceLane: sourceLane,
                sourceCheckpointRef: lineage?.sourceNodeRef,
                branchID: branchID(for: node.branchRef),
                graphRef: node.graphRef,
                edgeRef: node.edgeRef,
                toNode: node.toNode,
                physicalBranchRef: node.branchRef
            )
        }
        let merge = ResearchTreeHistoryMerge(
            projection: projection,
            loadedSteps: steps
        )
        result.append(contentsOf: merge.supplementalSteps.map { step in
            ResearchTreeNode(
                id: "step|\(step.stepRef)",
                checkpointRef: step.stepRef,
                sectionRef: sectionRefsByCheckpoint[step.stepRef] ?? "",
                title: ResearchDisplayText.node(step.toNode),
                subtitle: ResearchTreeTimestamp.text(step.createdAt),
                timestamp: step.createdAt,
                lane: selectedLane,
                status: step.status ?? "historical",
                isHead: step.stepRef == detail.latestTraceRef,
                isCurrentHead: step.stepRef == detail.latestTraceRef,
                isRoot: false,
                isLineage: false,
                sourceLane: nil,
                sourceCheckpointRef: nil,
                branchID: branchID(for: detail.branchRef)
            )
        })
        // A branch may have no checkpoint yet (or may be outside the bounded
        // sample). Keep its status/head visible as a non-clickable branch
        // marker instead of silently dropping the branch lane.
        let projectedBranches = Set(projection.nodes.map(\.branchRef))
        for branch in visibleBranches
        where !projectedBranches.contains(branch.branchRef) {
            result.append(ResearchTreeNode(
                id: "branch|\(branch.branchRef)",
                checkpointRef: branch.latestTraceRef ?? "",
                sectionRef: branch.latestTraceRef.flatMap {
                    sectionRefsByCheckpoint[$0]
                } ?? "",
                title: ResearchDisplayText.branchLabel(
                    branch.label,
                    currentNode: branch.currentNode
                ),
                subtitle: treeStatusLabel(branch.status),
                timestamp: branch.updatedAt,
                lane: lane(for: branch.branchRef),
                status: branch.status,
                isHead: true,
                isCurrentHead: branch.branchRef == detail.branchRef,
                isRoot: false,
                isLineage: false,
                sourceLane: nil,
                sourceCheckpointRef: nil,
                branchID: branch.branchID
            ))
        }
        let ordered = result.sorted {
            ResearchTreeOrdering.isBefore(
                timestamp: $0.timestamp,
                id: $0.id,
                than: $1.timestamp,
                id: $1.id
            )
        }
        return ordered
    }

    private func loadEarlierPreservingAnchor(
        _ proxy: ScrollViewProxy
    ) {
        let anchor = nodes.first?.id
        isLoadingEarlier = true
        Task {
            await loadEarlier()
            await Task.yield()
            if let anchor {
                proxy.scrollTo(anchor, anchor: .top)
            }
            isLoadingEarlier = false
        }
    }

    private var laneCount: Int {
        max(visibleBranches.count, 1)
    }

    /// Keep the narrow navigator readable without collapsing unrelated
    /// branches onto the same visual lane. The selected branch is always
    /// present; additional branches remain available through the branch
    /// selector above the report.
    private var visibleBranches: [ProfileResearchBranchSummary] {
        guard workPackage.branches.count
                > ResearchTreeLayout.maximumVisibleBranches else {
            return workPackage.branches
        }
        let selected = workPackage.branches.first {
            $0.branchRef == detail.branchRef
        }
        let others = workPackage.branches.filter {
            $0.branchRef != detail.branchRef
        }.prefix(ResearchTreeLayout.maximumVisibleBranches - 1)
        if let selected {
            return [selected] + Array(others)
        }
        return Array(
            workPackage.branches.prefix(
                ResearchTreeLayout.maximumVisibleBranches
            )
        )
    }

    private var hiddenBranchCount: Int {
        workPackage.omittedBranchCount
            + max(workPackage.branches.count - visibleBranches.count, 0)
    }

    private var remainingOmittedNodeCount: Int? {
        guard let projection = workPackage.tree else { return nil }
        return ResearchTreeHistoryMerge(
            projection: projection,
            loadedSteps: steps
        ).remainingOmittedNodeCount
    }

    private var selectedLane: Int { lane(for: detail.branchRef) }

    private func lane(for branchRef: String) -> Int {
        let index = visibleBranches.firstIndex {
            $0.branchRef == branchRef
        } ?? 0
        return index
    }

    private func branchID(for branchRef: String) -> String {
        branchRef.split(separator: ":").last.map(String.init) ?? branchRef
    }

    private func laneX(_ lane: Int) -> CGFloat {
        ResearchTreeLayout.laneCenterX(lane)
    }

    private func laneColor(_ lane: Int) -> Color {
        let colors: [Color] = [.blue, .purple, .orange, .green, .pink, .teal, .indigo]
        return colors[lane % colors.count]
    }

    private func nodeColor(_ node: ResearchTreeNode) -> Color {
        switch node.status {
        case "failed": return .red
        case "paused", "blocked": return .orange
        case "completed", "closed": return .green
        default: return laneColor(node.lane)
        }
    }

    private func represents(
        _ node: ResearchTreeNode,
        checkpointRef: String
    ) -> Bool {
        node.checkpointRef == checkpointRef
    }

    private func treeLegend(filled: Bool, label: String) -> some View {
        HStack(spacing: 4) {
            Circle()
                .fill(filled ? Color.accentColor : Color.clear)
                .overlay {
                    Circle().stroke(Color.accentColor, lineWidth: 1.4)
                }
                .frame(width: 7, height: 7)
            Text(label)
        }
        .font(.system(size: 9))
        .foregroundStyle(.secondary)
    }

    private func statusLegend(color: Color, label: String) -> some View {
        HStack(spacing: 4) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
            Text(label)
        }
        .font(.system(size: 9))
        .foregroundStyle(.secondary)
    }
}

private struct ResearchTreeNode: Identifiable {
    let id: String
    let checkpointRef: String
    let sectionRef: String
    let title: String
    let subtitle: String
    let timestamp: Double
    let lane: Int
    let status: String
    let isHead: Bool
    let isCurrentHead: Bool
    let isRoot: Bool
    let isLineage: Bool
    let sourceLane: Int?
    let sourceCheckpointRef: String?
    let branchID: String
    let graphRef: String
    let edgeRef: String
    let toNode: String
    let physicalBranchRef: String

    init(
        id: String,
        checkpointRef: String,
        sectionRef: String,
        title: String,
        subtitle: String,
        timestamp: Double,
        lane: Int,
        status: String,
        isHead: Bool,
        isCurrentHead: Bool,
        isRoot: Bool,
        isLineage: Bool,
        sourceLane: Int?,
        sourceCheckpointRef: String?,
        branchID: String,
        graphRef: String = "",
        edgeRef: String = "",
        toNode: String = "",
        physicalBranchRef: String = ""
    ) {
        self.id = id
        self.checkpointRef = checkpointRef
        self.sectionRef = sectionRef
        self.title = title
        self.subtitle = subtitle
        self.timestamp = timestamp
        self.lane = lane
        self.status = status
        self.isHead = isHead
        self.isCurrentHead = isCurrentHead
        self.isRoot = isRoot
        self.isLineage = isLineage
        self.sourceLane = sourceLane
        self.sourceCheckpointRef = sourceCheckpointRef
        self.branchID = branchID
        self.graphRef = graphRef
        self.edgeRef = edgeRef
        self.toNode = toNode
        self.physicalBranchRef = physicalBranchRef
    }
}

private func graphVersion(_ graphRef: String) -> String {
    graphRef.split(separator: "@").last.map(String.init) ?? "图版本"
}

private func continuationTitle(from source: String?, to target: String) -> String {
    let refs = [source, target].compactMap { value -> String? in
        guard let value, !value.isEmpty else { return nil }
        return value.split(separator: "@").last.map(String.init) ?? value
    }
    return refs.count == 2
        ? "图版本承接 \(refs[0]) → \(refs[1])"
        : "图版本承接"
}

enum ResearchTreeTimestamp {
    static func text(_ timestamp: Double) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: timestamp))
    }
}

private func treeStatusLabel(_ status: String) -> String {
    switch status {
    case "running": return "进行中"
    case "paused": return "已暂停"
    case "completed", "closed": return "已完成"
    case "blocked": return "等待处理"
    case "failed": return "失败"
    default: return "状态未知"
    }
}

private func treeReference(_ value: String) -> String {
    let suffix = value.split(separator: ":").last.map(String.init) ?? value
    return suffix.count > 14
        ? String(suffix.prefix(6)) + "…" + String(suffix.suffix(5))
        : suffix
}
