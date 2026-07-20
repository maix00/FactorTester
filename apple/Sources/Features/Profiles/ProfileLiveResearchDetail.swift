import SwiftUI

struct ProfileLiveResearchDetail: View {
    let profile: LocalProfileModel
    @ObservedObject var controller: ProfileLiveProcessController
    @State private var section = LiveDetailSection.overview
    @State private var linkedRefs: Set<String> = []

    var body: some View {
        VStack(spacing: 0) {
            if let workPackage = controller.workPackage {
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(workPackage.productGroup)
                            .font(.headline)
                        Text("Work Package · \(workPackage.branchCount) 个分支")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Picker(
                        "假设分支",
                        selection: $controller.selectedBranchID
                    ) {
                        ForEach(workPackage.branches) { branch in
                            Text(branch.label).tag(branch.branchID)
                        }
                    }
                    .frame(maxWidth: 260)
                }
                .padding(.horizontal, 16)
                .padding(.top, 14)
            }
            Picker("", selection: $section) {
                ForEach(LiveDetailSection.allCases) {
                    Text($0.title).tag($0)
                }
            }
            .pickerStyle(.segmented)
            .padding(14)
            Divider()
            content
        }
    }

    @ViewBuilder
    private var content: some View {
        if let detail = controller.detail {
            switch section {
            case .overview:
                LiveResearchOverview(detail: detail)
            case .timeline:
                ProfileLiveTimeline(
                    steps: controller.timeline,
                    nextCursor: controller.nextTimelineCursor,
                    highlightedRefs: linkedRefs,
                    select: { linkedRefs = $0 },
                    loadEarlier: {
                        await controller.loadEarlierTimeline()
                    }
                )
            case .obligations:
                LiveObligationsView(
                    obligations: detail.researchCycle.obligations
                )
            case .reports:
                ProfileLiveReportLinks(
                    profile: profile,
                    reportLookupRef: detail.reportLookupRef,
                    timeline: controller.timeline,
                    highlightedRefs: linkedRefs,
                    select: { linkedRefs = $0 }
                )
            }
        } else {
            VStack(spacing: 10) {
                Image(systemName: "waveform.path.ecg")
                    .font(.largeTitle)
                Text(controller.error ?? "选择一项研究查看实时过程")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

private enum LiveDetailSection: String, CaseIterable, Identifiable {
    case overview, timeline, obligations, reports
    var id: String { rawValue }
    var title: String {
        switch self {
        case .overview: return "当前状态"
        case .timeline: return "步骤"
        case .obligations: return "义务"
        case .reports: return "报告关联"
        }
    }
}
