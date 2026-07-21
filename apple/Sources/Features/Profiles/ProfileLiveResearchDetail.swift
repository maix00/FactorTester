import SwiftUI

struct ProfileLiveResearchDetail: View {
    let profiles: [LocalProfileModel]
    @ObservedObject var controller: ProfileLiveProcessController

    var body: some View {
        VStack(spacing: 0) {
            if let detail = controller.detail,
               let workPackage = controller.workPackage {
                let context = reportContext(for: detail)
                let artifact = context?.record.artifacts.first {
                    !$0.journalRef.isEmpty
                }
                ResearchNarrativeReportView(
                    detail: detail,
                    workPackage: workPackage,
                    steps: controller.timeline,
                    nextCursor: controller.nextTimelineCursor,
                    profileName: context?.profile.displayName ?? "未知 Profile",
                    auditCacheNamespace: context.map {
                        "\($0.profile.id)|\($0.profile.serverURL)"
                    } ?? detail.branchRef,
                    reportTitle: ResearchDisplayText.reportTitle(
                        context?.record.title ?? ""
                    ),
                    artifact: artifact,
                    selectBranch: { branchID in
                        controller.selectedBranchID = branchID
                    },
                    loadEarlier: { await controller.loadEarlierTimeline() },
                    loadAuditObject: { href in
                        guard let url = context.flatMap({
                            URL(string: $0.profile.serverURL)
                        }) else {
                            throw APIError.transport(
                                "研究记录没有有效的服务器地址"
                            )
                        }
                        return try await ProfileResearchService(
                            baseURL: url
                        ).auditObject(href: href)
                    }
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

    private func reportContext(
        for detail: ProfileResearchDetail
    ) -> (profile: LocalProfileModel, record: ResearchRecordModel)? {
        let matches = profiles.flatMap { profile in
            profile.researchRecords
                .filter { $0.graphBranchRef == detail.branchRef }
                .map { (profile: profile, record: $0) }
        }
        // Prefer a protocol-complete record when a stale duplicate exists,
        // but retain an exact legacy record so the UI can explain why the
        // report is unavailable instead of pretending the Profile is absent.
        return matches.first { item in
            item.record.artifacts.contains { !$0.journalRef.isEmpty }
        } ?? matches.first
    }
}
