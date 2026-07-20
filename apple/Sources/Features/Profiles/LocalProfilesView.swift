import SwiftUI

struct LocalProfilesView: View {
    @StateObject private var controller = LocalProfileController()
    @State private var selectedID: String?
    @AppStorage("client.profile.activeID") private var activeID = ""

    var body: some View {
        HSplitView {
            List(controller.profiles, selection: $selectedID) { profile in
                VStack(alignment: .leading, spacing: 2) {
                    Text(profile.displayName)
                    Text(profile.id).font(.caption).foregroundStyle(.secondary)
                }
                .tag(profile.id)
            }
            .frame(minWidth: 170, idealWidth: 190)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    LocalProfileForm(controller: controller)
                    if let profile = selectedProfile {
                        profileDetails(profile)
                        InitializationSourceView(profile: profile)
                        WorkspaceRepairView(profile: profile)
                        ResearchHistoryView(profile: profile)
                        Button(
                            activeID == profile.id
                                ? "当前 Adapter Profile"
                                : "用于本地 Adapter"
                        ) {
                            activeID = profile.id
                        }
                        .disabled(activeID == profile.id)
                        LocalAgentForm(
                            controller: controller,
                            profileID: profile.id
                        )
                        LocalAdapterProfileForm(
                            controller: controller,
                            profileID: profile.id
                        )
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
                        Label("当前 principal：\(source.ownerRef)", systemImage: "books.vertical")
                        Text(source.mode).foregroundStyle(.secondary)
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
                        Text(agent.role).foregroundStyle(.secondary)
                        Spacer()
                        Text(agent.scope).font(.caption)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
        }
    }
}
