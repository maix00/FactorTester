import AppKit
import SwiftUI

struct PersonalWorkspaceView: View {
    let openProfiles: (() -> Void)?
    @EnvironmentObject private var session: SessionStore
    @StateObject private var controller = PersonalWorkspaceController()
    @State private var authorizedRoot =
        PersonalWorkspaceAccessStore.authorizedRootPath
    @State private var factorLibraryRoot: String?
    @State private var accessError: String?

    init(openProfiles: (() -> Void)? = nil) {
        self.openProfiles = openProfiles
    }

    var body: some View {
        SettingsPageShell(
            title: "个人工作区",
            subtitle: "用户目录、canonical 因子库，以及按 Profile 隔离的研究现场",
            systemImage: "folder.badge.person.crop"
        ) {
            workspaceSection
        }
        .overlay { if controller.isWorking { ProgressView() } }
        .task {
            await refreshWorkspace()
        }
        .onChange(of: session.user?.username) { _ in
            Task { await refreshWorkspace() }
        }
    }

    private var workspaceSection: some View {
        SettingsSectionCard("个人工作区") {
            SettingsRow(
                title: "用户根目录 / 本地研究目录",
                description: "本地研究报告读取目录；应用更新后授权仍然保留"
            ) {
                VStack(alignment: .trailing, spacing: 5) {
                    pathValue(authorizedRoot ?? userRoot)
                    if authorizedRoot == nil {
                        Text("未授权").font(.caption).foregroundStyle(.secondary)
                    } else {
                        Text("已授权").font(.caption).foregroundStyle(.green)
                    }
                    if authorizedRoot == nil {
                        Button("选择目录…") { chooseWorkspace() }
                            .buttonStyle(.borderedProminent)
                    } else {
                        Button("更改目录…") { chooseWorkspace() }
                            .buttonStyle(.bordered)
                    }
                }
            }
            Divider()
            SettingsRow(title: "Profile 根目录", description: "各个研究现场的独立 worktree") {
                pathValue("\(userRoot)/profiles")
            }
            if let openProfiles {
                Divider()
                SettingsRow(
                    title: "研究现场",
                    description: "Profile、实时研究步骤、Trial Plan、义务与报告"
                ) {
                    Button("打开 Profiles", action: openProfiles)
                        .buttonStyle(.borderedProminent)
                }
            }
            Divider()
            canonicalFactorLibrarySection
            if let accessError = controller.error ?? accessError {
                Divider()
                Text(accessError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.vertical, 6)
            }
        }
    }

    private var canonicalFactorLibrarySection: some View {
        Group {
            SettingsRow(
                title: "本地 canonical 因子库",
                description: "固定的本地 Git 工作副本；安装或登录后自动建立"
            ) {
                VStack(alignment: .trailing, spacing: 5) {
                    pathValue(factorLibraryRoot ?? defaultFactorLibraryRoot)
                    Text("固定位置")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Divider()
            SettingsRow(
                title: "同步",
                description: "按方向传输因子源码；同步到本地更新同名文件但不删除其他文件"
            ) {
                HStack(spacing: 8) {
                    Button("同步到服务器") {
                        Task {
                            _ = await session.refreshCLIClientSession()
                            await controller.syncToServer(
                                principal: session.user?.username
                            )
                        }
                    }
                        .buttonStyle(.bordered)
                        .disabled(factorLibraryRoot == nil || controller.isWorking)
                    Button("同步到本地") {
                        Task {
                            _ = await session.refreshCLIClientSession()
                            await controller.syncToLocal(
                                principal: session.user?.username
                            )
                        }
                    }
                        .buttonStyle(.bordered)
                        .disabled(factorLibraryRoot == nil || controller.isWorking)
                }
            }
        }
    }

    private var userRoot: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users")
            .appendingPathComponent(principal).path
    }

    private var defaultFactorLibraryRoot: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users")
            .appendingPathComponent(principal)
            .appendingPathComponent("personal-workspace/factor-library").path
    }

    private func pathValue(_ value: String) -> some View {
        Text(value)
            .font(.caption.monospaced())
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .multilineTextAlignment(.trailing)
    }

    private func chooseWorkspace() {
        do {
            guard try PersonalWorkspaceAuthorizationPanel.present(
                suggestedRoot: URL(
                    fileURLWithPath: userRoot,
                    isDirectory: true
                )
            ) else { return }
            authorizedRoot = PersonalWorkspaceAccessStore.authorizedRootPath
            accessError = nil
            Task {
                await refreshWorkspace()
            }
        } catch {
            accessError = L10n.format(
                "无法保存个人工作区授权：%@",
                error.localizedDescription
            )
        }
    }

    private func refreshWorkspace() async {
        if let principal = session.user?.username, !principal.isEmpty {
            factorLibraryRoot = try? CanonicalFactorLibraryAccessStore.ensureDefault(
                for: principal
            )
            _ = await session.refreshCLIClientSession()
            await controller.refresh(principal: principal)
        } else {
            factorLibraryRoot = CanonicalFactorLibraryAccessStore.rootPath
            controller.clearServerState()
        }
    }

}
