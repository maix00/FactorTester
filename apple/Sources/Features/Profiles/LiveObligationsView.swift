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
                                    ResearchJournalPresentation
                                        .readableObligationQuestion(
                                            obligation.questionSummary
                                        )
                                )
                                    .font(.headline)
                                Spacer()
                                Text(LocalizedStringKey(
                                    ResearchJournalPresentation.statusLabel(
                                        obligation.status
                                    )
                                ))
                                    .font(.caption.weight(.semibold))
                            }
                            Text(LocalizedStringKey(
                                ResearchJournalPresentation.materialityLabel(
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
