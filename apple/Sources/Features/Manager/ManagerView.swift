import SwiftUI

struct ManagerView: View {
    @State private var worktrees: [ManagerWorktree] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var activePort: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("服务器管理").font(.largeTitle.weight(.semibold))
                    Text("直接连接 Manager；业务服务停止后仍可操作。")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("刷新") { Task { await load() } }
                    .disabled(isLoading)
            }
            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
            }
            List(worktrees) { item in
                HStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(item.label).font(.headline)
                        Text(item.branch).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(verbatim: L10n.format("端口 %lld", item.port)).monospacedDigit()
                    status(item)
                    Menu("操作") {
                        Button("启动") { run(.start, item) }
                        Button("停止") { run(.stop, item) }
                        Divider()
                        Button("重启网页") { run(.restartWeb, item) }
                        Button("排队重启") { run(.restartAll, item) }
                        Divider()
                        Button("强制停止", role: .destructive) {
                            run(.forceStop, item)
                        }
                    }
                    .disabled(activePort != nil)
                }
                .padding(.vertical, 5)
            }
            .overlay {
                if isLoading && worktrees.isEmpty { ProgressView() }
            }
        }
        .padding(24)
        .task { await load() }
    }

    private func status(_ item: ManagerWorktree) -> some View {
        let text = item.running ? "运行中" : (item.portInUse ? "端口占用" : "已停止")
        let color: Color = item.running ? .green : (item.portInUse ? .orange : .secondary)
        return Text(LocalizedStringKey(text))
            .font(.caption.weight(.medium))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.12), in: Capsule())
    }

    private func run(_ action: ManagerAction, _ item: ManagerWorktree) {
        activePort = item.port
        errorMessage = nil
        Task {
            do {
                try await ManagerCLIClient.shared.perform(
                    action,
                    port: item.port
                )
                await load()
            } catch {
                errorMessage = error.localizedDescription
            }
            activePort = nil
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            worktrees = try await ManagerCLIClient.shared.worktrees()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
