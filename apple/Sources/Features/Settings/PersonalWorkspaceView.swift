import SwiftUI
import UniformTypeIdentifiers

struct PersonalWorkspaceView: View {
    @EnvironmentObject private var session: SessionStore
    @StateObject private var controller = PersonalWorkspaceController()
    @State private var isSelectingWorkspace = false
    @State private var authorizedRoot =
        PersonalWorkspaceAccessStore.authorizedRootPath
    @State private var accessError: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                layoutCard
                canonicalCard
                accessCard
                if let error = controller.error {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
            .padding(24)
        }
        .overlay { if controller.isWorking { ProgressView() } }
        .task {
            await controller.refresh(principal: session.user?.username ?? "")
        }
        .fileImporter(
            isPresented: $isSelectingWorkspace,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            do {
                guard let url = try result.get().first else { return }
                try PersonalWorkspaceAccessStore.authorize(url)
                authorizedRoot = PersonalWorkspaceAccessStore.authorizedRootPath
                accessError = nil
            } catch {
                accessError = "无法保存个人工作区授权：\(error.localizedDescription)"
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("个人工作区").font(.largeTitle.weight(.semibold))
            Text("一个用户目录、一份 canonical 因子库，以及按 Profile 隔离的研究现场。")
                .foregroundStyle(.secondary)
        }
    }

    private var suggestedPath: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users")
            .appendingPathComponent(principal)
            .appendingPathComponent("personal-workspace/factor-library").path
    }

    private var layoutCard: some View {
        GroupBox("用户目录结构") {
            VStack(alignment: .leading, spacing: 7) {
                pathRow("用户根目录", userRoot)
                pathRow("唯一 canonical 因子库", suggestedPath)
                pathRow("Profile 根目录", "\(userRoot)/profiles")
                Text("每个 Profile 只链接 canonical repo 的独立 worktree；不会复制第二份因子库。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(8)
        }
    }

    private var userRoot: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/users")
            .appendingPathComponent(principal).path
    }

    private func pathRow(_ label: String, _ value: String) -> some View {
        LabeledContent(label) {
            Text(value).font(.caption.monospaced()).textSelection(.enabled)
        }
    }

    private var canonicalCard: some View {
        GroupBox("当前 canonical 因子库") {
            VStack(alignment: .leading, spacing: 10) {
                if let current = controller.current {
                    LabeledContent("当前用户", value: current.ownerRef)
                    LabeledContent("因子库路径", value: current.path)
                    Text(current.repositoryRef)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                } else {
                    Text("尚未初始化当前用户的 canonical 因子库。")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(8)
        }
    }

    private var accessCard: some View {
        GroupBox("研究报告读取权限") {
            VStack(alignment: .leading, spacing: 10) {
                Text("选择当前用户目录后，FTClient 才会读取其中的中文研究报告；该授权不会上传因子源码。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                if let authorizedRoot {
                    pathRow("已授权目录", authorizedRoot)
                } else {
                    Text("尚未授权个人工作区。")
                        .foregroundStyle(.secondary)
                }
                if let accessError {
                    Text(accessError)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
                Button("选择用户目录…") {
                    isSelectingWorkspace = true
                }
                .buttonStyle(.borderedProminent)
            }
            .padding(8)
        }
    }

}
