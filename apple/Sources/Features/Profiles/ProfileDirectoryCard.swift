import SwiftUI

struct ProfileDirectoryCard: View {
    let profile: LocalProfileModel
    let open: () -> Void
    @ObservedObject var controller: LocalProfileController
    @State private var intent: ProfileLifecycleIntent?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button(action: open) {
                HStack {
                    Image(systemName: "person.crop.rectangle.stack")
                        .font(.title2).foregroundStyle(.tint)
                    Text(profile.displayName).font(.title3.weight(.semibold))
                    Spacer()
                    Image(systemName: "arrow.up.right").foregroundStyle(.secondary)
                }
            }
            .buttonStyle(.plain)
            Label(statusText, systemImage: statusIcon)
                .font(.callout).foregroundStyle(statusColor)
            HStack {
                Text(profile.factorWorkspaceBinding?.branch ?? profile.id)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer()
                Menu {
                    Button("停用 Profile") { intent = .deactivate }
                    Button("解绑 Worktree") { intent = .unbind }
                        .disabled(profile.factorWorkspaceBinding == nil)
                    Divider()
                    Button("解绑并删除本地 Profile", role: .destructive) {
                        intent = .delete
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .menuStyle(.borderlessButton)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .confirmationDialog(
            intent?.title ?? "",
            isPresented: Binding(
                get: { intent != nil },
                set: { if !$0 { intent = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button(intent?.buttonTitle ?? "", role: intent?.role) {
                let selected = intent
                intent = nil
                Task { await perform(selected) }
            }
            Button("取消", role: .cancel) { intent = nil }
        } message: {
            Text(intent?.message ?? "")
        }
    }

    private var statusText: String {
        if profile.status == "inactive" { return "已停用 · 可安全解绑或删除" }
        return profile.factorWorkspaceBinding == nil
            ? "尚未绑定独立因子 Worktree"
            : "已绑定 · \(profile.researchRecords.count) 项研究"
    }
    private var statusIcon: String {
        if profile.status == "inactive" { return "pause.circle.fill" }
        return profile.factorWorkspaceBinding == nil
            ? "exclamationmark.circle" : "checkmark.circle.fill"
    }
    private var statusColor: Color {
        profile.factorWorkspaceBinding == nil ? .orange : .secondary
    }

    private func perform(_ selected: ProfileLifecycleIntent?) async {
        switch selected {
        case .deactivate: await controller.deactivateProfile(profile.id)
        case .unbind: await controller.unbindFactorWorkspace(profile)
        case .delete: await controller.deleteProfile(profile.id)
        case nil: break
        }
    }
}

enum ProfileLifecycleIntent {
    case deactivate, unbind, delete
    var title: String {
        switch self {
        case .deactivate: return "停用 \(label)？"
        case .unbind: return "解绑 \(label) 的 Worktree？"
        case .delete: return "解绑并删除 \(label)？"
        }
    }
    var label: String { "Profile" }
    var buttonTitle: String {
        switch self {
        case .deactivate: return "停用"
        case .unbind: return "解绑"
        case .delete: return "解绑并删除"
        }
    }
    var role: ButtonRole? { self == .deactivate ? nil : .destructive }
    var message: String {
        switch self {
        case .deactivate:
            return "停止本地身份继续认领；研究记录、worktree、分支和提交均保留。"
        case .unbind:
            return "仅 clean worktree 可解绑。分支、提交和操作 receipt 永久保留。"
        case .delete:
            return "dirty worktree 会被拒绝。删除本地 Profile 元数据，但不删除分支、提交或 receipt。"
        }
    }
}
