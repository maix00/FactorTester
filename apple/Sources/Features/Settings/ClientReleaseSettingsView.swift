import SwiftUI

struct ClientReleaseSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var controller: ClientReleaseController
    var embedded = false

    init(controller: ClientReleaseController, embedded: Bool = false) {
        self.controller = controller
        self.embedded = embedded
    }

    var body: some View {
        Group {
            if embedded {
                SettingsPageShell(
                    title: "客户端更新",
                    subtitle: "管理 Main / Beta 客户端版本、下载与更新策略",
                    systemImage: "arrow.down.app"
                ) {
                    updatePanel
                }
            } else {
                VStack(spacing: 0) {
                    header
                    Divider()
                    TabView {
                        ScrollView {
                            updatePanel.padding(24)
                        }
                        .tabItem {
                            Label("客户端更新", systemImage: "arrow.down.app")
                        }
                        LocalProfilesView()
                            .tabItem {
                                Label("Profiles", systemImage: "person.2")
                            }
                    }
                }
            }
        }
        .frame(minWidth: 560, minHeight: 460)
        .task { await controller.refresh() }
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .font(.system(size: 34))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 3) {
                Text("FTClient")
                    .font(.title2.weight(.semibold))
                Text("更新客户端，并管理所有人类与 Agent Profiles")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("关闭") { dismiss() }
                .keyboardShortcut(.cancelAction)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var updatePanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            SettingsSectionCard("客户端更新") {
                SettingsRow(
                    title: .verbatim(statusTitle),
                    description: .verbatim(statusSubtitle)
                ) {
                    VStack(alignment: .trailing, spacing: 8) {
                        Image(systemName: statusIcon)
                            .foregroundStyle(statusTint)
                        if controller.hasAvailableUpdate || controller.isUpdateReady {
                            Text(controller.pendingVersion ?? controller.latestVersion)
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        HStack(spacing: 8) {
                            Button(action: primaryAction) {
                                Label(primaryTitle, systemImage: primaryIcon)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(controller.isWorking)
                            if let checked = controller.lastChecked {
                                Text(checked.formatted(date: .abbreviated, time: .shortened))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Divider()
                SettingsRow(title: "更新渠道", description: "选择接收 Main 或 Beta 客户端") {
                    VStack(alignment: .trailing, spacing: 3) {
                        Picker("更新渠道", selection: $controller.channel) {
                            Text("Main").tag("stable")
                            Text("Beta").tag("beta")
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        Text(sourceLabel)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .disabled(controller.isWorking || controller.hasAvailableUpdate || controller.isUpdateReady)
                }
                Divider()
                SettingsRow(title: "自动下载", description: "发现新版本后自动准备更新") {
                    Toggle("自动下载更新", isOn: $controller.automaticallyUpdates)
                        .labelsHidden()
                }
                if let message = controller.lastError {
                    Divider()
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.vertical, 6)
                }
                Divider()
                SettingsRow(title: "签名", description: "发布包签名状态") {
                    Text(controller.signatureText).foregroundStyle(.secondary)
                }
            }
        }
    }

    private var installedVersion: String {
        controller.installedVersion.isEmpty
            ? L10n.text("未知") : controller.installedVersion
    }

    private var statusTitle: String {
        if controller.isUpdateReady {
            return L10n.text("更新已准备好")
        }
        if controller.hasAvailableUpdate {
            return L10n.text("发现新版本")
        }
        if controller.isWorking {
            return L10n.text("正在检查更新")
        }
        return L10n.text("FTClient 已是最新状态")
    }

    private var statusSubtitle: String {
        if let pendingVersion = controller.pendingVersion {
            return L10n.format(
                "当前版本 %@，%@ 将在重启后安装",
                installedVersion,
                pendingVersion
            )
        }
        if controller.hasAvailableUpdate {
            return L10n.format(
                "当前版本 %@，有可用更新，可下载并在重启后安装",
                installedVersion
            )
        }
        return L10n.format("当前版本 %@", installedVersion)
    }

    private var statusIcon: String {
        if controller.isUpdateReady { return "arrow.clockwise.circle.fill" }
        if controller.hasAvailableUpdate { return "arrow.down.circle.fill" }
        return "checkmark.circle.fill"
    }

    private var statusTint: Color {
        controller.isUpdateReady || controller.hasAvailableUpdate
            ? .accentColor : .green
    }

    private var primaryTitle: String {
        if controller.isUpdateReady { return L10n.text("重启并更新") }
        if controller.hasAvailableUpdate { return L10n.text("下载更新") }
        return L10n.text("检查更新")
    }

    private var primaryIcon: String {
        if controller.isUpdateReady { return "arrow.clockwise" }
        if controller.hasAvailableUpdate { return "arrow.down" }
        return "arrow.triangle.2.circlepath"
    }

    private var sourceLabel: String {
        controller.channel == "beta"
            ? L10n.text("Beta · FactorTester 服务器")
            : L10n.text("Main · GitHub")
    }

    private func primaryAction() {
        Task {
            if controller.isUpdateReady {
                await controller.restartToApply()
            } else if controller.hasAvailableUpdate {
                await controller.update()
            } else {
                await controller.refresh()
            }
        }
    }
}
