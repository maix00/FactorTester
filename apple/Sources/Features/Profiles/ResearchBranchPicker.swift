import SwiftUI

struct ResearchBranchPicker: View {
    static let controlWidth: CGFloat = 300
    static let controlHeight: CGFloat = 32
    static let popoverWidth: CGFloat = 380
    static let branchRowHeight: CGFloat = 36
    static let maximumVisibleRows = 8

    let branches: [ProfileResearchBranchSummary]
    let profiles: [LocalProfileModel]
    @Binding var selectedBranchID: String
    @State private var isPresented = false

    var body: some View {
        HStack(spacing: 8) {
            Text("研究路径")
                .font(.caption)
                .foregroundStyle(.secondary)
            Button {
                isPresented.toggle()
            } label: {
                HStack(spacing: 8) {
                    Text(selectedTitle)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.bordered)
            .controlSize(.regular)
            .frame(
                width: Self.controlWidth,
                height: Self.controlHeight
            )
            .popover(isPresented: $isPresented, arrowEdge: .top) {
                Group {
                    if branches.count > Self.maximumVisibleRows {
                        ScrollView {
                            branchRows
                        }
                        .frame(
                            height: Self.branchRowHeight
                                * CGFloat(Self.maximumVisibleRows)
                        )
                    } else {
                        branchRows
                    }
                }
                .padding(6)
                .frame(width: Self.popoverWidth)
            }
        }
        .frame(height: Self.controlHeight)
    }

    private var branchRows: some View {
        LazyVStack(alignment: .leading, spacing: 2) {
            ForEach(branches) { branch in
                Button {
                    selectedBranchID = branch.branchID
                    isPresented = false
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: "checkmark")
                            .opacity(
                                branch.branchID == selection.wrappedValue
                                    ? 1 : 0
                            )
                            .frame(width: 14)
                        Text(title(branch))
                            .multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 10)
                    .frame(
                        minHeight: Self.branchRowHeight,
                        alignment: .leading
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var selectedTitle: String {
        guard let branch = branches.first(where: {
            $0.branchID == selection.wrappedValue
        }) ?? branches.first else { return L10n.text("无研究路径") }
        return title(branch)
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
