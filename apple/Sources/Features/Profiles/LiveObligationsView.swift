import SwiftUI

struct LiveObligationsView: View {
    let obligations: [ResearchObligationProjection]

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                if obligations.isEmpty {
                    Label(
                        "当前 projection 没有研究义务",
                        systemImage: "checklist"
                    )
                    .foregroundStyle(.secondary)
                }
                ForEach(obligations) { obligation in
                    GroupBox {
                        VStack(alignment: .leading, spacing: 7) {
                            HStack {
                                Text(
                                    ResearchObligationDisplay.title(
                                        obligation.titleZH,
                                        fallback: obligation.questionSummary
                                    )
                                )
                                    .font(.headline)
                                Spacer()
                                Text(LocalizedStringKey(
                                    ResearchObligationDisplay.status(
                                        obligation.status
                                    )
                                ))
                                    .font(.caption.weight(.semibold))
                            }
                            Text(LocalizedStringKey(
                                ResearchObligationDisplay.materiality(
                                    obligation.materiality
                                )
                            ))
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                    }
                }
            }
            .padding(20)
        }
    }
}

enum ResearchObligationDisplay {
    static func title(_ value: String?, fallback: String?) -> String {
        guard let value, !value.trimmingCharacters(
            in: .whitespacesAndNewlines
        ).isEmpty else { return question(fallback) }
        return value
    }

    static func question(_ value: String?) -> String {
        guard let value, !value.trimmingCharacters(
            in: .whitespacesAndNewlines
        ).isEmpty else { return L10n.text("义务描述缺失") }
        return value
    }

    static func status(_ value: String) -> String {
        switch value.lowercased() {
        case "open": return L10n.text("待处理")
        case "blocked": return L10n.text("受阻")
        case "satisfied", "closed": return L10n.text("已完成")
        default: return L10n.text("状态未知")
        }
    }

    static func materiality(_ value: String?) -> String {
        switch value?.lowercased() {
        case "decision_blocking": return L10n.text("决策阻断")
        case "material": return L10n.text("重要")
        case "informational": return L10n.text("信息性")
        default: return L10n.text("重要性未知")
        }
    }
}
