import SwiftUI

struct ResearchDocumentBindingChipsView: View {
    let bindings: [ResearchDocumentBinding]

    var body: some View {
        if !bindings.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                ForEach(bindings.sorted { $0.id < $1.id }) { binding in
                    Label {
                        Text(ResearchDocumentBindingPresentation.label(for: binding))
                            .underline()
                    } icon: {
                        Image(systemName: ResearchDocumentBindingPresentation.symbol(for: binding))
                    }
                        .font(.caption.weight(.medium))
                        .foregroundStyle(Color.accentColor)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                        .help(binding.targetRef)
                        .accessibilityLabel(
                            ResearchDocumentBindingPresentation.label(for: binding)
                        )
                        .accessibilityHint(binding.targetRef)
                        .accessibilityIdentifier(
                            "research.document.link.\(binding.kind).\(binding.id)"
                        )
                }
            }
        }
    }
}

enum ResearchDocumentBindingPresentation {
    static func label(for binding: ResearchDocumentBinding) -> String {
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

    static func symbol(for binding: ResearchDocumentBinding) -> String {
        switch binding.kind {
        case "evidence": return "doc.text.magnifyingglass"
        case "job": return "checklist"
        case "obligation": return "checkmark.seal"
        case "claim": return "quote.bubble"
        case "task": return "checklist"
        case "trial_plan": return "map"
        case "checkpoint": return "flag"
        case "graph_reference": return "arrow.triangle.branch"
        case "report_requirement": return "list.bullet.clipboard"
        case "artifact": return "paperclip"
        default: return "link"
        }
    }
}
