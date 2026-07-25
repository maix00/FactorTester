import AppKit
import SwiftUI

struct PersonalWorkspaceView: View {
    @EnvironmentObject private var session: SessionStore
    @StateObject private var controller = PersonalWorkspaceController()
    @State private var authorizedRoot =
        PersonalWorkspaceAccessStore.authorizedRootPath
    @State private var accessError: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                SettingsPageHeader(
                    title: "个人工作区",
                    subtitle: "一个用户目录、一份 canonical 因子库，以及按 Profile 隔离的研究现场。"
                )
                workspaceLayoutSection
                Divider()
                reportAccessSection
                Divider()
                canonicalSection
                if let error = controller.error {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
            .padding(24)
        }
        .overlay { if controller.isWorking { ProgressView() } }
        .task {
            guard authorizedRoot != nil else { return }
            await controller.refresh(principal: session.user?.username ?? "")
        }
    }

    private var suggestedPath: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users")
            .appendingPathComponent(principal)
            .appendingPathComponent("personal-workspace/factor-library").path
    }

    private var workspaceLayoutSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("用户目录结构")
                .font(.title3.weight(.semibold))
            pathText("用户根目录", userRoot)
            pathText("唯一 canonical 因子库", suggestedPath)
            pathText("Profile 根目录", "\(userRoot)/profiles")
            Text("每个 Profile 只链接 canonical repo 的独立 worktree；不会复制第二份因子库。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var userRoot: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users")
            .appendingPathComponent(principal).path
    }

    private func pathText(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.monospaced())
                .lineLimit(2)
        }
    }

    private var canonicalSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("当前 canonical 因子库")
                .font(.title3.weight(.semibold))
            if let current = controller.current {
                pathText("当前用户", current.ownerRef)
                pathText("因子库路径", current.path)
                Text(current.repositoryRef)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            } else {
                Text("尚未读取当前用户的 canonical 因子库。")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var reportAccessSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("本地研究报告")
                .font(.title3.weight(.semibold))
            if let authorizedRoot {
                Label("已启用", systemImage: "checkmark.circle.fill")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.green)
                Text("FTClient 会持续读取该目录中的中文研究报告；应用更新后无需重新授权，也不会因此上传因子源码。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                pathText("正在读取", authorizedRoot)
            } else {
                Text("首次选择当前用户目录后，FTClient 会在本机读取其中的中文研究报告；不会因此上传因子源码。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Text("尚未选择个人工作区。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            if let accessError {
                Text(accessError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
            if authorizedRoot == nil {
                Button("选择用户目录…") {
                    chooseWorkspace()
                }
                .buttonStyle(.borderedProminent)
            } else {
                Button("更改用户目录…") {
                    chooseWorkspace()
                }
                .buttonStyle(.bordered)
            }
        }
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
