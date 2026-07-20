import SwiftUI
import UniformTypeIdentifiers

struct PersonalWorkspaceView: View {
    @EnvironmentObject private var session: SessionStore
    @StateObject private var controller = PersonalWorkspaceController()
    @State private var selectedPath = ""
    @State private var choosingFolder = false
    @State private var confirmsMigration = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                layoutCard
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
            suggestedPath: suggestedPath,
            confirmsMigration: $confirmsMigration
        )
    }

    private var cleanupCard: some View {
        GroupBox("Legacy quarantine preview") {
            VStack(alignment: .leading, spacing: 8) {
                Text("旧目录只进入 quarantine，不再作为活动 workspace；UI 不提供无门禁删除。")
                    .foregroundStyle(.secondary)
                if let plan = controller.plan {
                    LabeledContent("隔离项", value: "\(plan.legacyQuarantine.count)")
                    ForEach(plan.legacyQuarantine, id: \.self) { path in
                        Text(path).font(.caption.monospaced())
                    }
                } else {
                    Text("生成统一布局预览后显示 legacy quarantine 目标。")
                        .font(.caption)
                }
            }
            .padding(8)
        }
    }
}
