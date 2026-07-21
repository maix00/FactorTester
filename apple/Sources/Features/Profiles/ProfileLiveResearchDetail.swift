import SwiftUI

struct ProfileLiveResearchDetail: View {
    let profiles: [LocalProfileModel]
    @ObservedObject var controller: ProfileLiveProcessController

    var body: some View {
        VStack(spacing: 0) {
            if let workPackage = controller.workPackage {
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(workPackage.productGroup).font(.headline)
                        Text("研究过程 · \(workPackage.branchCount) 个假设分支")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Picker("假设分支", selection: $controller.selectedBranchID) {
                        ForEach(workPackage.branches) { branch in
                            Text(branch.label).tag(branch.branchID)
                        }
                    }
                    .frame(maxWidth: 260)
                }
                .padding(16)
                Divider()
            }

            if let detail = controller.detail {
                ResearchCheckpointTimeline(
                    detail: detail,
                    steps: controller.timeline,
                    nextCursor: controller.nextTimelineCursor,
                    profiles: profiles,
                    loadEarlier: { await controller.loadEarlierTimeline() }
                )
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "waveform.path.ecg")
                        .font(.largeTitle)
                    Text(controller.error ?? "正在读取研究过程…")
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}
