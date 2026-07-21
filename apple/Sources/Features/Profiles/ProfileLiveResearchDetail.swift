import SwiftUI

struct ProfileLiveResearchDetail: View {
    let profiles: [LocalProfileModel]
    @ObservedObject var controller: ProfileLiveProcessController

    var body: some View {
        VStack(spacing: 0) {
            if let detail = controller.detail,
               let workPackage = controller.workPackage {
                let record = reportRecord(for: detail)
                ResearchNarrativeReportView(
                    detail: detail,
                    workPackage: workPackage,
                    steps: controller.timeline,
                    nextCursor: controller.nextTimelineCursor,
                    profileName: profiles.first?.displayName ?? "未知 Profile",
                    reportTitle: ResearchDisplayText.reportTitle(
                        record?.title ?? ""
                    ),
                    artifact: record?.artifacts.first {
                        !$0.journalRef.isEmpty
                    },
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

    private func reportRecord(
        for detail: ProfileResearchDetail
    ) -> ResearchRecordModel? {
        profiles.lazy
            .flatMap(\.researchRecords)
            .filter { $0.graphBranchRef == detail.branchRef }
            .first { record in
                record.artifacts.contains { !$0.journalRef.isEmpty }
            }
    }
}
