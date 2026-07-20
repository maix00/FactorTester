import SwiftUI

struct ProfileWorkspaceView: View {
    let profile: LocalProfileModel
    @State private var section = ProfileSection.overview

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            HSplitView {
                sectionList
                sectionContent
                    .frame(minWidth: 520, maxWidth: .infinity)
            }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "person.crop.rectangle.stack")
                .font(.title)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 3) {
                Text(profile.displayName).font(.title2.weight(.semibold))
                Text("\(profile.researchRecords.count) 项研究")
                    .font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(18)
    }

    private var sectionList: some View {
        List(ProfileSection.allCases, selection: $section) { item in
            Label(item.title, systemImage: item.systemImage).tag(item)
        }
        .listStyle(.sidebar)
        .frame(minWidth: 170, idealWidth: 190)
    }

    @ViewBuilder
    private var sectionContent: some View {
        switch section {
        case .overview:
            ProfileOverviewSection(profile: profile)
        case .live:
            ProfileLiveProcessView(profile: profile)
        case .trialPlans:
            ProfileReferenceSection(
                profile: profile, kind: "trial",
                title: "Trial Plans", empty: "尚无关联的 Trial Plan。"
            )
        case .obligations:
            ProfileReferenceSection(
                profile: profile, kind: "obligation",
                title: "义务", empty: "尚无关联的研究义务。"
            )
        case .evidence:
            ProfileReferenceSection(
                profile: profile, kind: "evidence",
                title: "Evidence", empty: "尚无关联 Evidence。"
            )
        case .reports:
            ProfileReportsSection(profile: profile)
        }
    }
}

enum ProfileSection: String, CaseIterable, Identifiable {
    case overview, live, trialPlans, obligations, evidence, reports
    var id: String { rawValue }
    var title: String {
        switch self {
        case .overview: return "概览"
        case .live: return "实时过程"
        case .trialPlans: return "Trial Plans"
        case .obligations: return "义务"
        case .evidence: return "Evidence"
        case .reports: return "报告"
        }
    }
    var systemImage: String {
        switch self {
        case .overview: return "rectangle.grid.2x2"
        case .live: return "dot.radiowaves.left.and.right"
        case .trialPlans: return "list.bullet.clipboard"
        case .obligations: return "checklist"
        case .evidence: return "doc.text.magnifyingglass"
        case .reports: return "doc.richtext"
        }
    }
}
