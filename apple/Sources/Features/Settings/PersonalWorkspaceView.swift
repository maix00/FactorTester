import AppKit
import SwiftUI

struct PersonalWorkspaceView: View {
    let openProfiles: (() -> Void)?
    @EnvironmentObject private var session: SessionStore
    @StateObject private var controller = PersonalWorkspaceController()
    @State private var authorizedRoot =
        PersonalWorkspaceAccessStore.authorizedRootPath
    @State private var accessError: String?

    init(openProfiles: (() -> Void)? = nil) {
        self.openProfiles = openProfiles
    }

    var body: some View {
        SettingsPageShell(
            title: "个人工作区",
            subtitle: "用户目录、canonical 因子库，以及按 Profile 隔离的研究现场。",
            systemImage: "folder.badge.person.crop"
        ) {
            workspaceSection
        }
        .overlay { if controller.isWorking { ProgressView() } }
        .task {
            guard authorizedRoot != nil else { return }
            await controller.refresh(principal: session.user?.username ?? "")
        }
    }

    private var workspaceSection: some View {
        SettingsSectionCard("个人工作区") {
            SettingsRow(
                title: "用户根目录 / 本地研究目录",
                description: "本地研究报告读取目录；应用更新后授权仍然保留。"
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
            SettingsRow(title: "Profile 根目录", description: "各个研究现场的独立 worktree。") {
                pathValue("\(userRoot)/profiles")
            }
            if let openProfiles {
                Divider()
                SettingsRow(
                    title: "研究现场",
                    description: "Profile、实时研究步骤、Trial Plan、义务与报告。"
                ) {
                    Button("打开 Profiles", action: openProfiles)
                        .buttonStyle(.borderedProminent)
                }
            }
            Divider()
            if let current = controller.current {
                SettingsRow(title: "canonical 因子库所有者", description: "服务器确认的当前因子库所有者。") {
                    Text(current.ownerRef).foregroundStyle(.secondary)
                }
                Divider()
                SettingsRow(title: "canonical 因子库路径", description: current.repositoryRef) {
                    pathValue(current.path)
                }
            } else {
                Text("尚未读取当前用户的 canonical 因子库。")
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 8)
            }
            if let accessError {
                Divider()
                Text(accessError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.vertical, 6)
            }
        }
    }

    private var userRoot: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users")
            .appendingPathComponent(principal).path
    }

    private func pathValue(_ value: String) -> some View {
        Text(value)
            .font(.caption.monospaced())
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .multilineTextAlignment(.trailing)
    }

    private func chooseWorkspace() {
        let panel = NSOpenPanel()
        panel.title = "选择 FactorTester 用户目录"
        panel.message = "请选择当前用户目录，用于读取本地中文研究报告。"
        panel.prompt = "授权读取"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: userRoot, isDirectory: true)
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try PersonalWorkspaceAccessStore.authorize(url)
            authorizedRoot = PersonalWorkspaceAccessStore.authorizedRootPath
            accessError = nil
            Task {
                await controller.refresh(
                    principal: session.user?.username ?? ""
                )
            }
        } catch {
            accessError = "无法保存个人工作区授权：\(error.localizedDescription)"
        }
    }

}
