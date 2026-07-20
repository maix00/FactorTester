import SwiftUI
import UniformTypeIdentifiers

struct PersonalWorkspaceView: View {
    @EnvironmentObject private var session: SessionStore
    @StateObject private var controller = PersonalWorkspaceController()
    @State private var selectedPath = ""
    @State private var targetPath = ""
    @State private var choosingFolder = false
    @State private var confirmsMigration = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                canonicalCard
                migrationCard
                cleanupCard
                if let error = controller.error {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
            .padding(24)
        }
        .overlay { if controller.isWorking { ProgressView() } }
        .task {
            targetPath = suggestedPath
            await controller.refresh(principal: session.user?.username ?? "")
        }
        .fileImporter(
            isPresented: $choosingFolder,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                selectedPath = url.path
            }
        }
        .confirmationDialog(
            "迁移个人 canonical 因子库？",
            isPresented: $confirmsMigration,
            titleVisibility: .visible
        ) {
            Button("按预览执行迁移") {
                Task { await controller.applyMigration() }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("这是设置操作，不是研究审批。CLI 会保留分支、提交与未提交内容，并生成 receipt；实际行为以当前预览为准。")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("个人工作区").font(.largeTitle.weight(.semibold))
            Text("登记当前用户的 canonical 因子库，并安全迁移到统一目录。")
                .foregroundStyle(.secondary)
        }
    }

    private var suggestedPath: String {
        let principal = session.user?.username ?? "<principal>"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/personal-workspaces")
            .appendingPathComponent(principal)
            .appendingPathComponent("factor-library").path
    }

    private var canonicalCard: some View {
        GroupBox("当前 canonical 因子库") {
            VStack(alignment: .leading, spacing: 10) {
                if let current = controller.current {
                    LabeledContent("当前用户", value: current.ownerRef)
                    LabeledContent("外部路径", value: current.path)
                    Text(current.repositoryRef)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                } else {
                    Text("尚未登记。选择当前登录用户已有的 Git 因子库。")
                        .foregroundStyle(.secondary)
                }
                HStack {
                    TextField("选择 canonical repo", text: $selectedPath)
                    Button("选择…") { choosingFolder = true }
                    Button("登记") {
                        Task {
                            await controller.register(
                                path: selectedPath,
                                ownerRef: session.user?.username ?? ""
                            )
                        }
                    }
                    .disabled(selectedPath.isEmpty || !session.isLoggedIn)
                }
            }
            .padding(8)
        }
    }

    private var migrationCard: some View {
        PersonalWorkspaceMigrationView(
            controller: controller,
            targetPath: $targetPath,
            suggestedPath: suggestedPath,
            confirmsMigration: $confirmsMigration
        )
    }

    private var cleanupCard: some View {
        GroupBox("旧 Profile 工作区 cleanup preview") {
            VStack(alignment: .leading, spacing: 8) {
                Text("这里只显示确定性预览；不会从 UI 直接删除目录。")
                    .foregroundStyle(.secondary)
                if let plan = controller.plan {
                    LabeledContent("关联 Worktrees", value: "\(plan.linkedWorktrees.count)")
                    ForEach(plan.linkedWorktrees, id: \.self) { path in
                        Text(path).font(.caption.monospaced())
                    }
                } else {
                    Text("生成迁移预览后显示受影响的旧 Profile worktrees。")
                        .font(.caption)
                }
            }
            .padding(8)
        }
    }
}
