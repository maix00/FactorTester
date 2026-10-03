import SwiftUI

/// Profile 只管理本地研究身份与工作区配置。
/// 研究目录和报告由独立的 Research 模块管理。
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
