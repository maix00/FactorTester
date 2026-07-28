import SwiftUI

struct ResearchDocumentBindingChipsView: View {
    let bindings: [ResearchDocumentBinding]

    var body: some View {
        if !bindings.isEmpty {
            ResearchDocumentChipFlowLayout(spacing: 6, lineSpacing: 6) {
                ForEach(bindings.sorted { $0.id < $1.id }) { binding in
                    Text(label(for: binding))
                        .font(.caption.weight(.medium))
                        .underline()
                        .foregroundStyle(Color.accentColor)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                        .help(binding.targetRef)
                        .accessibilityIdentifier(
                            "research.document.link.\(binding.kind).\(binding.id)"
                        )
                }
            }
        }
    }

    private func label(for binding: ResearchDocumentBinding) -> String {
        let value = binding.label.trimmingCharacters(in: .whitespacesAndNewlines)
        if !value.isEmpty { return value }
        switch binding.kind {
        case "evidence": return L10n.text("证据")
        case "job": return L10n.text("测试任务")
        case "obligation": return L10n.text("研究义务")
        case "claim": return L10n.text("研究主张")
        case "task": return L10n.text("任务")
        default: return L10n.text("关联记录")
        }
    }

}

private struct ResearchDocumentChipFlowLayout: Layout {
    let spacing: CGFloat
    let lineSpacing: CGFloat

    func sizeThatFits(
        proposal: ProposedViewSize, subviews: Subviews, cache: inout ()
    ) -> CGSize {
        let width = proposal.width ?? .greatestFiniteMagnitude
        return positions(for: subviews, width: width).size
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews,
        cache: inout ()
    ) {
        let result = positions(for: subviews, width: bounds.width)
        for (index, point) in result.points.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + point.x, y: bounds.minY + point.y),
                proposal: .unspecified
            )
        }
    }

    private func positions(for subviews: Subviews, width: CGFloat) -> (
        points: [CGPoint], size: CGSize
    ) {
        var points: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var maxWidth: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                x = 0
                y += rowHeight + lineSpacing
                rowHeight = 0
            }
            points.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            maxWidth = max(maxWidth, x - spacing)
        }
        return (points, CGSize(width: maxWidth, height: y + rowHeight))
    }
}
