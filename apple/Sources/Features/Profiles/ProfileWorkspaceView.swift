import SwiftUI

/// Profile 只管理本地研究身份与工作区配置。
/// 所有进行中和已完成的研究统一从 Research -> Work Package 打开。
struct ProfileWorkspaceView: View {
    let profile: LocalProfileModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "person.crop.rectangle.stack")
                    .font(.title)
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 3) {
                    Text(profile.displayName).font(.title2.weight(.semibold))
                    Text("Profile 身份与工作区")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(18)
            Divider()
            ProfileOverviewSection(profile: profile)
        }
    }
}

/// Detail view for a report already indexed locally. It does not require a
/// server projection request to open.
struct LocalResearchDetailView: View {
    let item: LocalResearchDirectoryItem

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "doc.text")
                    .font(.title2)
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title).font(.title2.weight(.semibold))
                    Text("本地报告 · \(item.profileName)")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(18)
            Divider()
            ResearchStructuredDetailView(record: item.record)
        }
    }
}
