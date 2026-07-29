import SwiftUI

/// Special report sections are still ordinary report content. The marker only
/// changes presentation; it never changes graph navigation or evidence data.
enum ResearchReportSectionSpecialKind: Equatable {
    case obligationChange
    case graphContinuation

    static func resolve(
        displayKind: String,
        sectionRole: String?,
        hasObligationChanges: Bool
    ) -> Self? {
        if displayKind == "graph_continuation"
            || sectionRole == "graph_continuation"
            || sectionRole == "upgrade_reentry" {
            return .graphContinuation
        }
        if displayKind == "obligation_changes"
            || sectionRole == "obligation_changes"
            || hasObligationChanges {
            return .obligationChange
        }
        return nil
    }

    var title: String {
        switch self {
        case .obligationChange: return L10n.text("义务变化")
        case .graphContinuation: return L10n.text("图版本承接")
        }
    }

    var icon: String {
        switch self {
        case .obligationChange: return "exclamationmark.bubble"
        case .graphContinuation: return "arrow.triangle.branch"
        }
    }

    var tint: Color {
        switch self {
        case .obligationChange: return .orange
        case .graphContinuation: return .indigo
        }
    }
}

struct ResearchReportSectionDisclosureHeader: View {
    let title: String
    let subtitle: String
    let specialKind: ResearchReportSectionSpecialKind?
    let isExpanded: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                    .font(.caption.weight(.bold))
                    .frame(width: 14, height: 20)
                    .foregroundStyle(specialKind?.tint ?? .secondary)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        if let specialKind {
                            Label(specialKind.title, systemImage: specialKind.icon)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(specialKind.tint)
                        }
                        Text(title)
                            .font(.headline)
                            .foregroundStyle(.primary)
                            .multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 8)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(
            L10n.format(
                "%@，%@",
                title,
                isExpanded ? L10n.text("已展开") : L10n.text("已收起")
            )
        )
    }
}
