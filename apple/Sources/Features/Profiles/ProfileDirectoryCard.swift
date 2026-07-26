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
            Label {
                Text(verbatim: statusText)
            } icon: {
                Image(systemName: statusIcon)
            }
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
            Button(role: intent?.role) {
                let selected = intent
                intent = nil
                Task { await perform(selected) }
            } label: {
                Text(LocalizedStringKey(intent?.buttonTitle ?? ""))
            }
            Button("取消", role: .cancel) { intent = nil }
        } message: {
            Text(intent?.message ?? "")
        }
    }

    private var statusText: String {
        if profile.status == "inactive" {
            return L10n.text("已停用 · 可安全解绑 Worktree")
        }
        return profile.factorWorkspaceBinding == nil
            ? L10n.text("尚未绑定独立因子 Worktree")
            : L10n.format("已绑定 · %lld 项研究", profile.researchRecords.count)
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
        case nil: break
        }
    }
}

enum ProfileLifecycleIntent {
    case deactivate, unbind
    var title: String {
        switch self {
        case .deactivate: return L10n.format("停用 %@？", label)
        case .unbind: return L10n.format("解绑 %@ 的 Worktree？", label)
        }
    }
    var label: String { "Profile" }
    var buttonTitle: String {
        switch self {
        case .deactivate: return "停用"
        case .unbind: return "解绑"
        }
    }
    var role: ButtonRole? { self == .deactivate ? nil : .destructive }
    var message: String {
        switch self {
        case .deactivate:
            return L10n.text("停止本地身份继续认领；研究记录、worktree、分支和提交均保留。")
        case .unbind:
            return L10n.text("仅 clean worktree 可解绑。分支、提交和操作 receipt 永久保留。")
        }
    }
}
