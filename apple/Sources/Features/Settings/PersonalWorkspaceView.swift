import AppKit
import SwiftUI

struct PersonalWorkspaceView: View {
    let openProfiles: (() -> Void)?
    @EnvironmentObject private var session: SessionStore
    @StateObject private var controller = PersonalWorkspaceController()
    @State private var authorizedRoot =
        PersonalWorkspaceAccessStore.authorizedRootPath
    @State private var factorLibraryRoot =
        CanonicalFactorLibraryAccessStore.rootPath
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
            await controller.refresh()
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
                description: "本地 Git 工作副本；同步前请先检查本地改动"
            ) {
                VStack(alignment: .trailing, spacing: 5) {
                    pathValue(factorLibraryRoot ?? "未设置")
                    Button(factorLibraryRoot == nil ? "选择目录…" : "更改目录…") {
                        chooseFactorLibrary()
                    }
                    .buttonStyle(.bordered)
                }
            }
            Divider()
            SettingsRow(
                title: "Git 版本",
                description: "分别显示本地工作副本与服务器 canonical 版本"
            ) {
                VStack(alignment: .trailing, spacing: 4) {
                    Text("本地 · \(controller.localFactorLibrary?.gitHead ?? "—")")
                        .font(.caption.monospaced())
                    Text("服务器 · \(controller.serverFactorLibrary?.gitHead ?? "—")")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
            Divider()
            SettingsRow(
                title: "同步",
                description: "按方向传输因子源码；同步到本地更新同名文件但不删除其他文件"
            ) {
                HStack(spacing: 8) {
                    Button("同步到服务器") { Task { await controller.syncToServer() } }
                        .buttonStyle(.bordered)
                        .disabled(factorLibraryRoot == nil || controller.isWorking)
                    Button("同步到本地") { Task { await controller.syncToLocal() } }
                        .buttonStyle(.bordered)
                        .disabled(factorLibraryRoot == nil || controller.isWorking)
                }
            }
            if let local = controller.localFactorLibrary {
                Divider()
                SettingsRow(title: "本地因子数量", description: "当前本地工作副本的文件统计") {
                    Text("自定义 \(local.customCount) · 公共 \(local.publicCount)")
                        .foregroundStyle(.secondary)
                }
            }
            if let server = controller.serverFactorLibrary {
                Divider()
                SettingsRow(title: "服务器因子数量", description: "当前登录用户可同步的服务器快照") {
                    Text("自定义 \(server.customCount) · 公共 \(server.publicCount)")
                        .foregroundStyle(.secondary)
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
                await controller.refresh()
            }
        } catch {
            accessError = "无法保存个人工作区授权：\(error.localizedDescription)"
        }
    }

    private func chooseFactorLibrary() {
        let panel = NSOpenPanel()
        panel.title = "选择本地 canonical 因子库"
        panel.message = "请选择用于同步因子源码的本地 Git 工作副本目录。"
        panel.prompt = "选择目录"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if let factorLibraryRoot {
            panel.directoryURL = URL(fileURLWithPath: factorLibraryRoot, isDirectory: true)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try CanonicalFactorLibraryAccessStore.authorize(url)
            factorLibraryRoot = CanonicalFactorLibraryAccessStore.rootPath
            accessError = nil
            Task { await controller.refresh() }
        } catch {
            accessError = "无法保存 canonical 因子库授权：\(error.localizedDescription)"
        }
    }

}
