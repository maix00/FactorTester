import SwiftUI

struct ResearchGraphTopologyView: View {
    let graph: ResearchGraphVersion
    @Binding var selection: ResearchGraphSelection?
    @State private var layout: ResearchGraphCanvasLayout

    init(
        graph: ResearchGraphVersion,
        selection: Binding<ResearchGraphSelection?>
    ) {
        self.graph = graph
        _selection = selection
        _layout = State(initialValue: ResearchGraphCanvasLayout(graph: graph))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            topologyHeader
            Divider()
            if !globalEdges.isEmpty {
                globalEdgeStrip
                Divider()
            }
            ScrollView([.horizontal, .vertical]) {
                canvas
                    .padding(18)
            }
            .background(.quaternary.opacity(0.12))
        }
    }

    private var topologyHeader: some View {
        HStack(spacing: 14) {
            Label(
                L10n.format("%lld 个节点", graph.nodes.count),
                systemImage: "circle.grid.cross"
            )
            Label(
                L10n.format("%lld 条边", graph.edges.count),
                systemImage: "arrow.triangle.branch"
            )
            Spacer()
            edgeLegend(L10n.text("推荐"), color: .green)
            edgeLegend(L10n.text("失败"), color: .red)
            edgeLegend(L10n.text("恢复"), color: .orange)
            Text("点击连线查看义务")
                .foregroundStyle(.secondary)
        }
        .font(.caption)
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private var globalEdgeStrip: some View {
        HStack(spacing: 10) {
            Text("全局边")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            ForEach(globalEdges) { edge in
                Button {
                    selection = .edge(edge.id)
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "asterisk")
                        Text(verbatim: ResearchDisplayText.node(edge.toNode))
                            .lineLimit(1)
                        requirementCount(graph.requirements(forEdge: edge.id).count)
                    }
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(
                        selection == .edge(edge.id)
                            ? Color.accentColor.opacity(0.14)
                            : Color.primary.opacity(0.04),
                        in: Capsule()
                    )
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }

    private var canvas: some View {
        let canvasLayout = layout
        return ZStack(alignment: .topLeading) {
            ResearchGraphEdgesCanvas(
                graph: graph,
                layout: canvasLayout,
                selectedEdgeID: selectedEdgeID
            )
            .contentShape(Rectangle())
            .simultaneousGesture(
                DragGesture(minimumDistance: 0)
                    .onEnded { value in
                        guard hypot(
                            value.translation.width,
                            value.translation.height
                        ) < 5,
                        let edgeID = canvasLayout.nearestEdge(
                            to: value.location
                        ) else { return }
                        selection = .edge(edgeID)
                    }
            )

            ForEach(graph.nodes) { node in
                if let frame = canvasLayout.nodeFrames[node.id] {
                    nodeButton(node)
                        .frame(width: frame.width, height: frame.height)
                        .position(x: frame.midX, y: frame.midY)
                }
            }
        }
        .frame(
            width: canvasLayout.canvasSize.width,
            height: canvasLayout.canvasSize.height,
            alignment: .topLeading
        )
        .accessibilityElement(children: .contain)
        .accessibilityLabel(L10n.text("研究图拓扑"))
    }

    private func nodeButton(_ node: ResearchGraphNode) -> some View {
        let requirements = graph.requirements(forNode: node.id)
        let selected = selection == .node(node.id)
        return Button {
            selection = .node(node.id)
        } label: {
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 8) {
                    Image(systemName: node.id == graph.entryNode
                          ? "play.circle.fill" : "circle.fill")
                        .foregroundStyle(node.id == graph.entryNode
                                         ? Color.green : Color.accentColor)
                    Text(verbatim: ResearchDisplayText.node(node.id))
                        .font(.headline)
                        .lineLimit(2)
                    Spacer(minLength: 4)
                }
                Text(verbatim: node.purpose)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                Spacer(minLength: 0)
                HStack(spacing: 8) {
                    Text(verbatim: node.kind)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer()
                    requirementCount(requirements.count)
                }
            }
            .padding(12)
            .contentShape(Rectangle())
            .background(
                selected ? Color.accentColor.opacity(0.13) : Color.primary.opacity(0.045),
                in: RoundedRectangle(cornerRadius: 11)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 11)
                    .stroke(
                        selected ? Color.accentColor : Color.secondary.opacity(0.24),
                        lineWidth: selected ? 2 : 1
                    )
            }
        }
        .buttonStyle(.plain)
        .help(node.purpose)
        .accessibilityLabel(
            L10n.format("节点：%@", ResearchDisplayText.node(node.id))
        )
    }

    private func edgeLegend(_ title: String, color: Color) -> some View {
        HStack(spacing: 4) {
            Capsule().fill(color).frame(width: 14, height: 3)
            Text(verbatim: title).foregroundStyle(.secondary)
        }
    }

    private func requirementCount(_ count: Int) -> some View {
        Text(verbatim: L10n.format("%lld 项义务小类", count))
            .font(.caption2.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(.quaternary, in: Capsule())
    }

    private var selectedEdgeID: String? {
        guard case .edge(let edgeID) = selection else { return nil }
        return edgeID
    }

    private var globalEdges: [ResearchGraphEdge] {
        graph.outgoingEdges(from: "*")
    }
}

private struct ResearchGraphEdgesCanvas: View {
    let graph: ResearchGraphVersion
    let layout: ResearchGraphCanvasLayout
    let selectedEdgeID: String?

    var body: some View {
        Canvas { context, _ in
            for edge in graph.edges {
                guard let route = layout.edgeRoutes[edge.id] else { continue }
                let selected = edge.id == selectedEdgeID
                let color = edgeColor(edge.type)
                var path = Path()
                path.move(to: route.start)
                path.addCurve(
                    to: route.end,
                    control1: route.control1,
                    control2: route.control2
                )
                context.stroke(
                    path,
                    with: .color(selected ? color : color.opacity(0.62)),
                    style: StrokeStyle(
                        lineWidth: selected ? 3 : 1.5,
                        lineCap: .round,
                        dash: edge.type.lowercased() == "recovery" ? [6, 4] : []
                    )
                )
                drawArrowhead(
                    context: &context,
                    route: route,
                    color: color,
                    selected: selected
                )
            }
        }
    }

    private func drawArrowhead(
        context: inout GraphicsContext,
        route: ResearchGraphEdgeRoute,
        color: Color,
        selected: Bool
    ) {
        let angle = atan2(
            route.end.y - route.control2.y,
            route.end.x - route.control2.x
        )
        let length: CGFloat = selected ? 10 : 8
        var arrow = Path()
        arrow.move(to: route.end)
        arrow.addLine(to: CGPoint(
            x: route.end.x - length * cos(angle - .pi / 6),
            y: route.end.y - length * sin(angle - .pi / 6)
        ))
        arrow.move(to: route.end)
        arrow.addLine(to: CGPoint(
            x: route.end.x - length * cos(angle + .pi / 6),
            y: route.end.y - length * sin(angle + .pi / 6)
        ))
        context.stroke(
            arrow,
            with: .color(color),
            style: StrokeStyle(lineWidth: selected ? 3 : 1.5, lineCap: .round)
        )
    }

    private func edgeColor(_ type: String) -> Color {
        switch type.lowercased() {
        case "failure": return .red
        case "recovery": return .orange
        case "recommended": return .green
        default: return .accentColor
        }
    }
}
