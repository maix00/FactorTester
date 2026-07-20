import SwiftUI

struct ProfileLiveProcessView: View {
    let profile: LocalProfileModel
    @StateObject private var controller: ProfileLiveProcessController

    init(profile: LocalProfileModel) {
        self.profile = profile
        _controller = StateObject(
            wrappedValue: ProfileLiveProcessController(profile: profile)
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            workspaceBar
            Divider()
            HSplitView {
                researchList
                    .frame(minWidth: 220, idealWidth: 260)
                ProfileLiveResearchDetail(
                    profile: profile,
                    controller: controller
                )
                .frame(minWidth: 520, maxWidth: .infinity)
            }
        }
        .task(id: controller.selectedWorkspaceID) {
            await controller.loadSelectedWorkspace()
        }
        .task(id: controller.observationKey) {
            await controller.observeSelectedResearch()
        }
    }

    private var workspaceBar: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("实时过程").font(.title2.weight(.semibold))
                Text("有界 projection · 离开页面即停止更新")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if controller.workspaces.isEmpty {
                Label(
                    "未映射服务器工作区",
                    systemImage: "externaldrive.badge.questionmark"
                )
                .foregroundStyle(.secondary)
            } else {
                Picker(
                    "工作区",
                    selection: $controller.selectedWorkspaceID
                ) {
                    ForEach(controller.workspaces) { workspace in
                        Text(workspaceLabel(workspace)).tag(workspace.id)
                    }
                }
                .frame(maxWidth: 300)
            }
        }
        .padding(18)
    }

    private var researchList: some View {
        List(
            controller.research,
            selection: $controller.selectedResearchRef
        ) { item in
            VStack(alignment: .leading, spacing: 3) {
                Text(item.productGroup).lineLimit(1)
                HStack(spacing: 6) {
                    Text("\(item.branchCount) 个假设分支").lineLimit(1)
                    Spacer()
                    Text(
                        item.runningBranchCount > 0
                            ? "\(item.runningBranchCount) 进行中"
                            : item.status
                    )
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            .tag(item.researchRef)
        }
        .overlay {
            if controller.isLoading {
                ProgressView()
            } else if controller.research.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "clock.badge.questionmark")
                    Text(controller.error ?? "尚无研究记录")
                        .multilineTextAlignment(.center)
                }
                .foregroundStyle(.secondary)
                .padding()
            }
        }
    }

    private func workspaceLabel(_ workspace: LocalWorkspaceModel) -> String {
        let owner = workspace.ownerRef.isEmpty
            ? workspace.id : workspace.ownerRef
        return "\(owner) · \(workspace.accessMode)"
    }
}
