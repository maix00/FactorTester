import SwiftUI

struct ProfileLiveResearchDetail: View {
    let profiles: [LocalProfileModel]
    @ObservedObject var controller: ProfileLiveProcessController
    let serverURL: URL
    let openJob: (TestJob) -> Void

    var body: some View {
        VStack(spacing: 0) {
            if let detail = controller.detail,
               let workPackage = controller.workPackage {
                let context = reportContext(for: detail)
                let artifact = context?.record.currentReportArtifact
                VStack(spacing: 0) {
                    if let error = controller.error {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(Color.orange.opacity(0.08))
                    }
                    reportView(
                        detail: detail,
                        workPackage: workPackage,
                        context: context,
                        reportArtifact: artifact
                    )
                }
            } else {
                VStack(spacing: 10) {
                    Image(systemName: controller.error == nil
                        ? "waveform.path.ecg"
                        : "exclamationmark.triangle")
                        .font(.largeTitle)
                    Text(emptyStateMessage)
                        .foregroundStyle(.secondary)
                    if controller.error != nil {
                        Button("重试") {
                            Task {
                                await controller.observeSelectedResearch()
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    @ViewBuilder
    private func reportView(
        detail: ProfileResearchDetail,
        workPackage: ProfileResearchWorkPackageDetail,
        context: (profile: LocalProfileModel, record: ResearchRecordModel)?,
        reportArtifact: ResearchArtifactModel?
    ) -> some View {
        if let reportArtifact {
            ResearchDocumentReportView(
                detail: detail,
                workPackage: workPackage,
                steps: controller.timeline,
                profileName: context?.profile.displayName
                    ?? L10n.text("未知 Profile"),
                reportTitle: ResearchDisplayText.reportTitle(
                    context?.record.title ?? ""
                ),
                artifact: reportArtifact,
                serverURL: serverURL,
                openJob: openJob
            )
            .id(reportArtifact.localRef)
        } else {
            VStack(spacing: 8) {
                Image(systemName: "doc.badge.ellipsis")
                    .font(.title2)
                Text(L10n.text("当前分支尚无报告"))
                    .font(.headline)
                Text(L10n.text("报告会在研究节点进入时自动建立章节"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var emptyStateMessage: String {
        if let error = controller.error { return error }
        if controller.isLoadingResearch { return L10n.text("正在读取研究过程…") }
        return L10n.text("当前研究分支尚无可显示的检查点。")
    }

    private func reportContext(
        for detail: ProfileResearchDetail
    ) -> (profile: LocalProfileModel, record: ResearchRecordModel)? {
        let matches = profiles.flatMap { profile in
            profile.researchRecords
                .filter { $0.graphBranchRef == detail.branchRef }
                .map { (profile: profile, record: $0) }
        }
        return matches.first { item in
            item.record.currentReportArtifact != nil
        } ?? matches.first
    }
}
