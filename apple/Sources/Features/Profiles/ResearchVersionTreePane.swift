import SwiftUI

enum ResearchTreeLayout {
    static let navigatorWidth: CGFloat = 208
    static let maximumVisibleBranches = 7
    static let laneSpacing: CGFloat = 13
    static let laneOriginX: CGFloat = 9
    static let selectedNodeDiameter: CGFloat = 17
    static let horizontalPadding: CGFloat = 8
    static let maximumLaneFootprint = laneOriginX
        + CGFloat(maximumVisibleBranches - 1) * laneSpacing
        + selectedNodeDiameter
}

struct ResearchVersionTreePane: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    @Binding var selectedCheckpointRef: String
    let select: (String) -> Void
    let loadEarlier: () async -> Void
    let canLoadEarlier: Bool

    private let rowHeight: CGFloat = 46
    private let laneSpacing = ResearchTreeLayout.laneSpacing

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 5) {
                Text("研究版本树")
                    .font(.headline)
                Text("时间向下 · 点击定位正文")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack(spacing: 10) {
                    treeLegend(filled: true, label: "报告")
                    treeLegend(filled: false, label: "分叉/接续")
                    if hiddenBranchCount > 0 {
                        Text("另有 \(hiddenBranchCount) 条分支")
                            .font(.system(size: 9))
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 13)
            Divider()
            ScrollView {
                ZStack(alignment: .topLeading) {
                    laneBackground
                    LazyVStack(spacing: 0) {
                        ForEach(nodes) { node in
                            nodeRow(node)
                        }
                    }
                }
                .padding(.vertical, 8)
            }
            if canLoadEarlier {
                Divider()
                Button {
                    Task { await loadEarlier() }
                } label: {
                    Label("更早记录", systemImage: "clock.arrow.circlepath")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.plain)
                .padding(12)
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
                let x = laneX(lane)
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
                    x: laneX(node.lane),
                    y: (CGFloat(index) + 0.5) * rowHeight
                )
                let sourceX = node.sourceLane.map(laneX) ?? 0
                var connector = Path()
                connector.move(to: CGPoint(x: sourceX, y: target.y - 13))
                connector.addCurve(
                    to: target,
                    control1: CGPoint(x: sourceX, y: target.y),
                    control2: CGPoint(x: target.x, y: target.y - 13)
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
            select(node.checkpointRef)
        } label: {
            HStack(spacing: 8) {
                ZStack {
                    Circle()
                        .fill(node.isLineage ? Color(nsColor: .windowBackgroundColor) : nodeColor(node))
                        .frame(width: node.isHead ? 11 : 8, height: node.isHead ? 11 : 8)
                        .overlay {
                            if node.isLineage {
                                Circle().stroke(nodeColor(node), lineWidth: 2)
                            }
                            if selectedCheckpointRef == node.checkpointRef {
                                Circle()
                                    .stroke(Color.accentColor, lineWidth: 2)
                                    .frame(width: 17, height: 17)
                            }
                        }
                        .offset(x: laneX(node.lane) - 26)
                }
                .frame(width: CGFloat(laneCount) * laneSpacing + 8)

                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 4) {
                        Text(node.title)
                            .font(.caption.weight(node.isHead ? .semibold : .regular))
                            .lineLimit(1)
                            .truncationMode(.middle)
                        if node.isCurrentHead {
                            Text("当前")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundStyle(.tint)
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
        var result = steps.map { step in
            ResearchTreeNode(
                id: "step|\(step.stepRef)",
                checkpointRef: step.stepRef,
                title: ResearchDisplayText.node(step.toNode),
                subtitle: compactDate(step.createdAt),
                timestamp: step.createdAt,
                lane: selectedLane,
                status: detail.status,
                isHead: step.stepRef == detail.latestTraceRef,
                isCurrentHead: step.stepRef == detail.latestTraceRef,
                isLineage: false,
                sourceLane: nil
            )
        }
        for branch in visibleBranches {
            let branchLane = lane(for: branch.branchRef)
            if branch.branchRef != detail.branchRef {
                result.append(ResearchTreeNode(
                    id: "branch|\(branch.branchRef)",
                    checkpointRef: branch.latestTraceRef ?? "",
                    title: branch.label,
                    subtitle: treeStatusLabel(branch.status),
                    timestamp: branch.updatedAt,
                    lane: branchLane,
                    status: branch.status,
                    isHead: true,
                    isCurrentHead: false,
                    isLineage: false,
                    sourceLane: nil
                ))
            }
            if let lineage = branch.lineage,
               ["fork", "continuation"].contains(lineage.relation),
               let sourceBranchRef = lineage.sourceBranchRef {
                let sourceIndex = visibleBranches.firstIndex {
                    $0.branchRef == sourceBranchRef
                }
                let sourceLabel = sourceIndex.map {
                    visibleBranches[$0].label
                } ?? "上一研究版本"
                result.append(ResearchTreeNode(
                    id: "lineage|\(branch.branchRef)",
                    checkpointRef: "",
                    title: lineage.relation == "fork" ? "从 \(sourceLabel) 分叉" : "接续 \(sourceLabel)",
                    subtitle: sourceIndex == nil ? "外部研究工作包" : "已验证来源",
                    timestamp: branch.createdAt,
                    lane: branchLane,
                    status: branch.status,
                    isHead: false,
                    isCurrentHead: false,
                    isLineage: true,
                    sourceLane: sourceIndex
                ))
            }
        }
        return result.sorted {
            if $0.timestamp != $1.timestamp { return $0.timestamp > $1.timestamp }
            return $0.id < $1.id
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

    private var selectedLane: Int { lane(for: detail.branchRef) }

    private func lane(for branchRef: String) -> Int {
        let index = visibleBranches.firstIndex {
            $0.branchRef == branchRef
        } ?? 0
        return index
    }

    private func laneX(_ lane: Int) -> CGFloat {
        ResearchTreeLayout.laneOriginX + CGFloat(lane) * laneSpacing
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
    let isLineage: Bool
    let sourceLane: Int?
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
