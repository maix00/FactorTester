import SwiftUI

struct ProfileLiveResearchDetail: View {
    let profiles: [LocalProfileModel]
    @ObservedObject var controller: ProfileLiveProcessController

    var body: some View {
        VStack(spacing: 0) {
            if let detail = controller.detail,
               let workPackage = controller.workPackage {
                let context = reportContext(for: detail)
                let artifact = context?.record.currentJournalArtifact
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
                        journalArtifact: artifact,
                        documentArtifact: context?.record.currentDocumentArtifact
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
        journalArtifact: ResearchArtifactModel?,
        documentArtifact: ResearchArtifactModel?
    ) -> some View {
        if journalArtifact != nil {
            ResearchNarrativeReportView(
                detail: detail,
                workPackage: workPackage,
                steps: controller.timeline,
                nextCursor: controller.nextTimelineCursor,
                profileName: context?.profile.displayName
                    ?? L10n.text("未知 Profile"),
                auditCacheNamespace: context.map {
                    "\($0.profile.id)|\($0.profile.serverURL)"
                } ?? detail.branchRef,
                reportTitle: ResearchDisplayText.reportTitle(
                    context?.record.title ?? ""
                ),
                artifact: journalArtifact,
                selectBranch: { controller.selectedBranchID = $0 },
                loadEarlier: { await controller.loadEarlierTimeline() },
                loadHistory: { await controller.loadTimeline(through: $0) },
                loadAuditObject: { href in
                    guard let url = context.flatMap({
                        URL(string: $0.profile.serverURL)
                    }) else {
                        throw APIError.transport("研究记录没有有效的服务器地址")
                    }
                    return try await ProfileResearchService(
                        baseURL: url
                    ).auditObject(href: href)
                }
            )
        } else if let documentArtifact {
            ResearchDocumentReportView(
                detail: detail,
                workPackage: workPackage,
                steps: controller.timeline,
                nextCursor: controller.nextTimelineCursor,
                profileName: context?.profile.displayName
                    ?? L10n.text("未知 Profile"),
                reportTitle: ResearchDisplayText.reportTitle(
                    context?.record.title ?? ""
                ),
                artifact: documentArtifact,
                selectBranch: { controller.selectedBranchID = $0 },
                loadEarlier: { await controller.loadEarlierTimeline() }
            )
        } else {
            ResearchNarrativeReportView(
                detail: detail,
                workPackage: workPackage,
                steps: controller.timeline,
                nextCursor: controller.nextTimelineCursor,
                profileName: context?.profile.displayName
                    ?? L10n.text("未知 Profile"),
                auditCacheNamespace: detail.branchRef,
                reportTitle: ResearchDisplayText.reportTitle(
                    context?.record.title ?? ""
                ),
                artifact: nil,
                selectBranch: { controller.selectedBranchID = $0 },
                loadEarlier: { await controller.loadEarlierTimeline() },
                loadHistory: { await controller.loadTimeline(through: $0) },
                loadAuditObject: { _ in
                    throw APIError.transport("研究记录没有有效的服务器地址")
                }
            )
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
        // Prefer a protocol-complete record when a stale duplicate exists,
        // but retain an exact legacy record so the UI can explain why the
        // report is unavailable instead of pretending the Profile is absent.
        return matches.first { item in
            item.record.artifacts.contains { !$0.journalRef.isEmpty }
        } ?? matches.first
    }
}
