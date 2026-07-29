import SwiftUI

struct ResearchBranchPicker: View {
    let branches: [ProfileResearchBranchSummary]
    let profiles: [LocalProfileModel]
    @Binding var selectedBranchID: String

    var body: some View {
        HStack(spacing: 8) {
            Text("研究路径")
                .font(.caption)
                .foregroundStyle(.secondary)
            Picker("研究路径", selection: selection) {
                ForEach(branches) { branch in
                    Text(title(branch)).tag(branch.branchID)
                }
            }
            .labelsHidden()
            .frame(width: 210)
        }
    }

    private var selection: Binding<String> {
        Binding(
            get: {
                Self.resolvedSelection(
                    branches: branches,
                    selectedBranchID: selectedBranchID
                )
            },
            set: { selectedBranchID = $0 }
        )
    }

    static func resolvedSelection(
        branches: [ProfileResearchBranchSummary],
        selectedBranchID: String
    ) -> String {
        branches.contains { $0.branchID == selectedBranchID }
            ? selectedBranchID
            : branches.first?.branchID ?? ""
    }

    private func title(_ branch: ProfileResearchBranchSummary) -> String {
        let recordTitle = profiles
            .flatMap(\.researchRecords)
            .first { $0.graphBranchRef == branch.branchRef }?
            .title
        return ResearchDisplayText.branchLabel(
            recordTitle ?? branch.label,
            currentNode: branch.currentNode
        )
    }
}
