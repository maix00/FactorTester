import SwiftUI

struct WorkPackageResearchView: View {
    let item: ResearchDirectoryItem
    let profiles: [LocalProfileModel]
    let primaryProfile: LocalProfileModel
    let isActive: Bool
    let openJob: (TestJob) -> Void
    let openProfile: (String, String) -> Void
    let onCheckpointChange: @MainActor (String) -> Void

    @StateObject private var controller: ProfileLiveProcessController
    @State private var branchTask: Task<Void, Never>?

    init(
        item: ResearchDirectoryItem,
        profiles: [LocalProfileModel],
        primaryProfile: LocalProfileModel,
        isActive: Bool,
        openJob: @escaping (TestJob) -> Void,
        openProfile: @escaping (String, String) -> Void,
        onCheckpointChange: @escaping @MainActor (String) -> Void
    ) {
        self.item = item
        self.profiles = profiles
        self.primaryProfile = primaryProfile
        self.isActive = isActive
        self.openJob = openJob
        self.openProfile = openProfile
        self.onCheckpointChange = onCheckpointChange
        _controller = StateObject(
            wrappedValue: ProfileLiveProcessController(
                profile: primaryProfile,
                pinnedSummary: item.summary,
                initialWorkspaceID: item.workspaceID,
                onCheckpointChange: onCheckpointChange
            )
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ProfileLiveResearchDetail(
                profiles: profiles,
                controller: controller,
                serverURL: item.serverURL,
                openJob: openJob,
                openProfile: openProfile
            )
        }
        .task(id: "\(isActive)|\(item.id)") {
            guard isActive else { return }
            await controller.observeSelectedResearch()
        }
        .onChange(of: controller.selectedBranchID) { _ in
            guard isActive, controller.detail != nil else { return }
            branchTask?.cancel()
            branchTask = Task { await controller.observeSelectedResearch() }
        }
        .onChange(of: isActive) { active in
            if !active {
                branchTask?.cancel()
                branchTask = nil
            }
        }
        .onDisappear {
            branchTask?.cancel()
            branchTask = nil
        }
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(.title2)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 4) {
                Text(item.displayTitle)
                    .font(.title2.weight(.semibold))
                HStack(spacing: 8) {
                    Text("研究工作包")
                    Text(item.summary.workPackageRef).monospaced()
                    Text("·")
                    Text(verbatim: L10n.format(
                        "研究身份：%@",
                        item.profileNames.joined(separator: "、")
                    ))
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            }
            Spacer()
            if let workPackage = controller.workPackage {
                Picker("假设分支", selection: $controller.selectedBranchID) {
                    ForEach(workPackage.branches) { branch in
                        Text(branchTitle(branch)).tag(branch.branchID)
                    }
                }
                .labelsHidden()
                .frame(width: 210)
            }
            if controller.isLoading {
                ProgressView().controlSize(.small)
            }
            if item.summary.runningBranchCount > 0 {
                Button {
                    Task { await controller.refreshSelectedResearch() }
                } label: {
                    Label("刷新进度", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
                .disabled(controller.selectedBranch == nil)
            }
        }
        .padding(18)
    }

    private func branchTitle(
        _ branch: ProfileResearchBranchSummary
    ) -> String {
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
