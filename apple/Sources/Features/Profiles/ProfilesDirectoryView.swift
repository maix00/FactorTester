import SwiftUI

struct ProfilesDirectoryView: View {
    @ObservedObject var controller: LocalProfileController
    let openProfile: (LocalProfileModel) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                if controller.profiles.isEmpty {
                    emptyState
                } else {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 260), spacing: 14)],
                        spacing: 14
                    ) {
                        ForEach(controller.profiles) { profile in
                            profileCard(profile)
                        }
                    }
                }
                Divider()
                LocalProfileForm(controller: controller)
                if let error = controller.error {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
            .padding(24)
        }
        .overlay {
            if controller.isWorking { ProgressView().controlSize(.small) }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Profiles").font(.largeTitle.weight(.semibold))
            Text("每个 Profile 保持独立的 Agent 身份、工作区与研究记录。")
                .foregroundStyle(.secondary)
        }
    }

    private var emptyState: some View {
        GroupBox {
            Label(
                "尚无已注册 Profile。可在下方创建，注册完成后会立即显示。",
                systemImage: "person.crop.circle.badge.plus"
            )
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 100)
        }
    }

    private func profileCard(_ profile: LocalProfileModel) -> some View {
        Button { openProfile(profile) } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: "person.crop.rectangle.stack")
                        .font(.title2)
                        .foregroundStyle(.tint)
                    Text(profile.displayName).font(.title3.weight(.semibold))
                    Spacer()
                    Image(systemName: "arrow.up.right")
                        .foregroundStyle(.secondary)
                }
                Label(
                    "\(profile.researchRecords.count) 项研究",
                    systemImage: "doc.text.magnifyingglass"
                )
                .font(.callout)
                .foregroundStyle(.secondary)
                Text(profile.workspaceRoot)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
    }
}
