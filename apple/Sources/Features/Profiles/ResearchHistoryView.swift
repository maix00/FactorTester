import SwiftUI

struct ResearchHistoryView: View {
    let profile: LocalProfileModel
    @State private var selectedRecord: String?

    var body: some View {
        GroupBox("Research History / Reports") {
            if profile.researchRecords.isEmpty {
                Text("No indexed research records")
                    .foregroundStyle(.secondary)
                    .padding(8)
            } else {
                HSplitView {
                    List(profile.researchRecords, selection: $selectedRecord) {
                        record in
                        VStack(alignment: .leading) {
                            Text(record.title)
                            HStack(spacing: 6) {
                                Text(record.status)
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(
                                        record.status == "ready"
                                            ? Color.green : Color.secondary
                                    )
                                Text(record.agentID)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                        .tag(record.id)
                    }
                    .frame(minWidth: 180)
                    if let record = selected {
                        ResearchStructuredDetailView(record: record)
                    }
                }
                .frame(minHeight: 180)
            }
        }
    }

    private var selected: ResearchRecordModel? {
        profile.researchRecords.first { $0.id == selectedRecord }
    }

}
