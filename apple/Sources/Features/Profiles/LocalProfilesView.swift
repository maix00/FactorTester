import SwiftUI

struct LocalProfilesView: View {
    @StateObject private var controller = LocalProfileController()
    @State private var selectedID: String?
    @AppStorage("client.profile.activeID") private var activeID = ""

    var body: some View {
        HSplitView {
            Group {
                if controller.profiles.isEmpty {
                    VStack(spacing: 10) {
                        if controller.loadState == .loading {
                            ProgressView().controlSize(.small)
                            Text("正在读取本地 Profile…")
                                .foregroundStyle(.secondary)
                        } else if controller.loadState == .failed {
                            Image(systemName: "exclamationmark.triangle")
                                .foregroundStyle(.orange)
                            Text("本地 Profile 读取失败")
                            Text("暂不判断为空，请稍后重试。")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            Image(systemName: "person.crop.circle.badge.plus")
                                .foregroundStyle(.secondary)
                            Text("尚无已注册 Profile")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List(controller.profiles, selection: $selectedID) { profile in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(profile.displayName)
                            Text(profile.id)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .tag(profile.id)
                    }
                }
            }
            .frame(minWidth: 170, idealWidth: 190)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let profile = selectedProfile {
                        profileDetails(profile)
                        InitializationSourceView(profile: profile)
                        Button(
                            activeID == profile.id
                                ? "当前 Adapter Profile"
                                : "用于本地 Adapter"
                        ) {
                            activeID = profile.id
                        }
                        .disabled(activeID == profile.id)
                    }
                    if let error = controller.error {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                    }
                }
                .padding(18)
            }
            .frame(minWidth: 440)
        }
        .overlay {
            if controller.isWorking { ProgressView().controlSize(.small) }
        }
        .task {
            // The local snapshot is available synchronously.  Select it before
            // waiting for the bundled one-file CLI to finish its cold start.
            selectedID = selectedID ?? controller.profiles.first?.id
            await controller.refresh()
            selectedID = selectedID ?? controller.profiles.first?.id
        }
    }

    private var selectedProfile: LocalProfileModel? {
        controller.profiles.first { $0.id == selectedID }
    }

    private func profileDetails(_ profile: LocalProfileModel) -> some View {
        GroupBox(profile.displayName) {
            VStack(alignment: .leading, spacing: 8) {
                Text(profile.serverURL).font(.callout)
                Text(profile.workspaceRoot)
                    .font(.caption).foregroundStyle(.secondary)
                Divider()
                Text("初始化来源")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                if profile.initializationSources.isEmpty {
                    Text("尚未登记当前登录用户的个人因子库")
                        .foregroundStyle(.secondary)
                }
                ForEach(profile.initializationSources) { source in
                    HStack {
                        Label {
                            Text(verbatim: L10n.format("当前 principal：%@", source.ownerRef))
                        } icon: {
                            Image(systemName: "books.vertical")
                        }
                        Text(verbatim: ProfilePresentationText.initializationSourceMode(source.mode))
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(source.sourceRef).font(.caption)
                    }
                }
                Divider()
                Text("可见工作区")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                if profile.workspaces.isEmpty {
                    Text("尚未登记工作区")
                        .foregroundStyle(.secondary)
                }
                ForEach(profile.workspaces) { workspace in
                    WorkspaceRegistryRow(workspace: workspace)
                }
                Divider()
                if profile.agents.isEmpty {
                    Text("尚未登记 Agent").foregroundStyle(.secondary)
                }
                ForEach(profile.agents) { agent in
                    HStack {
                        Label(agent.id, systemImage: "person.crop.circle")
                        Text(verbatim: ProfilePresentationText.agentRole(agent.role))
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(verbatim: ProfilePresentationText.agentScope(agent.scope))
                            .font(.caption)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
        }
    }
}
