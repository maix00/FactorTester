import SwiftUI

enum ResearchTreeLayout {
    static let navigatorWidth: CGFloat = 208
    static let maximumVisibleBranches = 7
    static let laneSpacing: CGFloat = 13
    static let laneOriginX: CGFloat = 9
    static let selectedNodeDiameter: CGFloat = 17
    static let horizontalPadding: CGFloat = 8
    static let rowSpacing: CGFloat = 8
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

struct ResearchVersionTreePane: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
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
                        $0.checkpointRef == checkpointRef
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
            for lane in 0..<laneCount {
                let indices = nodes.indices.filter { nodes[$0].lane == lane }
                guard let first = indices.first, let last = indices.last else {
                    continue
                }
                let x = ResearchTreeLayout.canvasLaneCenterX(lane)
                var path = Path()
                path.move(to: CGPoint(
                    x: x,
                    y: max(CGFloat(first) * rowHeight, 0)
                ))
                path.addLine(to: CGPoint(
                    x: x,
                    y: min((CGFloat(last) + 1) * rowHeight, size.height)
                ))
                context.stroke(
                    path,
                    with: .color(laneColor(lane).opacity(0.28)),
                    lineWidth: 1.5
                )
            }
            for (index, node) in nodes.enumerated()
            where node.isLineage {
                let target = CGPoint(
                    x: ResearchTreeLayout.canvasLaneCenterX(node.lane),
                    y: (CGFloat(index) + 0.5) * rowHeight
                )
                let sourceX = node.sourceLane.map(
                    ResearchTreeLayout.canvasLaneCenterX
                ) ?? ResearchTreeLayout.canvasLaneCenterX(node.lane)
                let sourceRow = ResearchTreeConnector.sourceRowIndex(
                    sourceCheckpointRef: node.sourceCheckpointRef,
                    nodeCheckpointRefs: nodes.map(\.checkpointRef)
                )
                let sourceY = sourceRow.map {
                    (CGFloat($0) + 0.5) * rowHeight
                } ?? target.y - 13
                let source = CGPoint(x: sourceX, y: sourceY)
                var connector = Path()
                connector.move(to: source)
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
                context.stroke(
                    connector,
                    with: .color(laneColor(node.lane).opacity(0.75)),
                    lineWidth: 1.8
                )
            }
        }
        .frame(height: CGFloat(nodes.count) * rowHeight)
        .allowsHitTesting(false)
    }

    private func nodeRow(_ node: ResearchTreeNode) -> some View {
        Button {
            guard !node.checkpointRef.isEmpty else { return }
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
                    if selectedCheckpointRef == node.checkpointRef {
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
                title: ResearchDisplayText.node(step.toNode),
                subtitle: compactDate(step.createdAt),
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
            return ResearchTreeNode(
                id: "checkpoint|\(node.nodeRef)",
                checkpointRef: node.checkpointRef,
                title: ResearchDisplayText.node(node.toNode),
                subtitle: compactDate(node.createdAt),
                timestamp: node.createdAt,
                lane: lane(for: node.branchRef),
                status: node.status,
                isHead: node.isHead,
                isCurrentHead: node.branchRef == detail.branchRef
                    && node.isHead,
                isRoot: node.isRoot,
                isLineage: lineage != nil,
                sourceLane: sourceLane,
                sourceCheckpointRef: lineage?.sourceNodeRef,
                branchID: branchID(for: node.branchRef)
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
                title: ResearchDisplayText.node(step.toNode),
                subtitle: compactDate(step.createdAt),
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
        return result.sorted {
            ResearchTreeOrdering.isBefore(
                timestamp: $0.timestamp,
                id: $0.id,
                than: $1.timestamp,
                id: $1.id
            )
        }
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
}

private func compactDate(_ timestamp: Double) -> String {
    Date(timeIntervalSince1970: timestamp).formatted(
        .dateTime.month(.abbreviated).day().hour().minute()
    )
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
