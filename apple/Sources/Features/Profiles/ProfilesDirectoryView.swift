import SwiftUI

struct ProfilesDirectoryView: View {
    @ObservedObject var controller: LocalProfileController
    let openProfile: (LocalProfileModel) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            if controller.profiles.isEmpty && controller.loadState == .loading {
                loadingState
            } else if controller.profiles.isEmpty && controller.loadState == .failed {
                failedState
            } else if controller.profiles.isEmpty {
                emptyState
            } else {
                profileList
            }
            if let receipt = controller.lifecycleReceipt {
                ProfileLifecycleReceiptView(receipt: receipt, controller: controller)
            }
            if let error = controller.error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            }
        }
        .padding(24)
        .overlay {
            if controller.isWorking { ProgressView().controlSize(.small) }
        }
    }

    private var profileList: some View {
        List(controller.profiles) { profile in
            Button { openProfile(profile) } label: {
                profileRow(profile)
            }
            .buttonStyle(.plain)
            .contextMenu {
                Button("打开 Profile") { openProfile(profile) }
            }
        }
        .listStyle(.inset)
        .frame(minHeight: 180)
    }

    private func profileRow(_ profile: LocalProfileModel) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "person.crop.rectangle.stack")
                .font(.title3)
                .foregroundStyle(.tint)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 3) {
                Text(profile.displayName).font(.headline)
                Text(profile.id)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 18)
            VStack(alignment: .trailing, spacing: 3) {
                Text(profile.status == "inactive" ? "已停用" : "研究 Agent")
                    .font(.callout)
                    .foregroundStyle(profile.status == "inactive" ? .secondary : .primary)
                Text(L10n.format("%lld 个 Agent · %@", profile.agents.count,
                                 profile.serverURL.isEmpty ? "未绑定服务器" : (URL(string: profile.serverURL)?.host ?? profile.serverURL)))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            VStack(alignment: .leading, spacing: 5) {
                Text("Profiles").font(.largeTitle.weight(.semibold))
                Text("每个 Profile 保持独立的 Agent 身份、工作区和初始化来源。")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("刷新") {
                Task { await controller.refresh(force: true) }
            }
            .buttonStyle(.bordered)
        }
    }

    private var emptyState: some View {
        GroupBox {
            Label(
                "尚无已注册 Profile。请使用 CLI 创建并注册研究 Agent Profile。",
                systemImage: "person.crop.circle.badge.plus"
            )
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 100)
        }
    }

    private var loadingState: some View {
        GroupBox {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("正在读取本地 Profile…")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 100)
        }
    }

    private var failedState: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                Label(
                    "本地 Profile 读取失败，尚未确认为空。",
                    systemImage: "exclamationmark.triangle.fill"
                )
                .foregroundStyle(.orange)
                Button("重新读取") {
                    Task { await controller.refresh(force: true) }
                }
                .buttonStyle(.bordered)
            }
            .frame(maxWidth: .infinity, minHeight: 100, alignment: .leading)
        }
    }

}
