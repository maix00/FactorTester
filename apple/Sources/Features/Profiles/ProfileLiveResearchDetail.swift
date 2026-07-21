import SwiftUI

struct ProfileLiveResearchDetail: View {
    let profiles: [LocalProfileModel]
    @ObservedObject var controller: ProfileLiveProcessController

    var body: some View {
        VStack(spacing: 0) {
            if let detail = controller.detail,
               let workPackage = controller.workPackage {
                ResearchNarrativeReportView(
                    detail: detail,
                    workPackage: workPackage,
                    steps: controller.timeline,
                    nextCursor: controller.nextTimelineCursor,
                    profileName: profiles.first?.displayName ?? "未知 Profile",
                    artifact: reportArtifact(for: detail),
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

    private func reportArtifact(
        for detail: ProfileResearchDetail
    ) -> ResearchArtifactModel? {
        profiles.lazy
            .flatMap(\.researchRecords)
            .filter { $0.graphBranchRef == detail.branchRef }
            .flatMap(\.artifacts)
            .first { !$0.journalRef.isEmpty }
    }
}
