import SwiftUI

struct ResearchGraphRequirementDetailView: View {
    let graph: ResearchGraphVersion
    @Binding var selection: ResearchGraphSelection?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let selection {
                    selectionHeader(selection)
                    if case .node(let nodeID) = selection {
                        outgoingTransitions(nodeID)
                    }
                    if requirements.isEmpty {
                        Label(
                            emptyMessage,
                            systemImage: "checkmark.circle"
                        )
                        .foregroundStyle(.secondary)
                    } else {
                        ForEach(requirements) { requirement in
                            requirementCard(requirement)
                        }
                    }
                } else {
                    ResearchGraphEmptyState(
                        title: "选择节点或边",
                        systemImage: "cursorarrow.click.2",
                        description: "选择图中的节点或边查看义务小类"
                    )
                }
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .textSelection(.enabled)
    }

    private var requirements: [ResearchGraphRequirement] {
        switch selection {
        case .node(let id): return graph.requirements(forNode: id)
        case .edge(let id): return graph.requirements(forEdge: id)
        case nil: return []
        }
    }

    private var emptyMessage: String {
        switch selection {
        case .node: return L10n.text("该节点没有声明义务小类")
        case .edge: return L10n.text("该边没有声明义务小类")
        case nil: return ""
        }
    }

    @ViewBuilder
    private func selectionHeader(_ selection: ResearchGraphSelection) -> some View {
        switch selection {
        case .node(let nodeID):
            Text(verbatim: ResearchDisplayText.node(nodeID))
                .font(.title2.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
            Text("节点义务小类")
                .font(.callout)
                .foregroundStyle(.secondary)
        case .edge(let edgeID):
            if let edge = graph.edge(id: edgeID) {
                Text(verbatim: L10n.format(
                    "%@ → %@",
                    ResearchDisplayText.node(edge.fromNode),
                    ResearchDisplayText.node(edge.toNode)
                ))
                .font(.title2.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
                Text(verbatim: edge.id)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
            Text("边义务小类")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }

    private func requirementCard(
        _ requirement: ResearchGraphRequirement
    ) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            VStack(alignment: .leading, spacing: 4) {
                Text(verbatim: requirement.title)
                    .font(.headline)
                    .fixedSize(horizontal: false, vertical: true)
                Text(verbatim: L10n.format(
                    "%@ · r%lld",
                    requirement.categoryTitle,
                    requirement.revision
                ))
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Text(verbatim: requirement.id)
                .font(.caption2.monospaced())
                .foregroundStyle(.tertiary)
            if !requirement.question.isEmpty {
                Text(verbatim: requirement.question)
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
            }
            detail(
                title: L10n.text("适用时机"),
                values: requirement.selectWhen.isEmpty
                    ? [] : [requirement.selectWhen]
            )
            detail(
                title: L10n.text("期望证据"),
                values: requirement.expectedEvidence
            )
            detail(
                title: L10n.text("不足以满足"),
                values: requirement.notSufficient
            )
        }
        .padding(12)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder
    private func detail(title: String, values: [String]) -> some View {
        if !values.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                Text(verbatim: title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(values, id: \.self) { value in
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Circle()
                            .fill(.secondary)
                            .frame(width: 4, height: 4)
                        Text(verbatim: value)
                            .font(.caption)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func outgoingTransitions(_ nodeID: String) -> some View {
        let edges = graph.outgoingEdges(from: nodeID)
        if !edges.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("出边")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(edges) { edge in
                    Button {
                        selection = .edge(edge.id)
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "arrow.right")
                                .foregroundStyle(.secondary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(verbatim: ResearchDisplayText.node(edge.toNode))
                                    .font(.callout.weight(.medium))
                                    .lineLimit(2)
                                Text(verbatim: edge.type)
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 6)
                            Text(verbatim: L10n.format(
                                "%lld 项义务小类",
                                graph.requirements(forEdge: edge.id).count
                            ))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        }
                        .padding(9)
                        .contentShape(Rectangle())
                        .background(
                            Color.primary.opacity(0.04),
                            in: RoundedRectangle(cornerRadius: 8)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}
