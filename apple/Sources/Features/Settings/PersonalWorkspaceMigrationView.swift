import SwiftUI

struct PersonalWorkspaceMigrationView: View {
    @ObservedObject var controller: PersonalWorkspaceController
    @Binding var targetPath: String
    let suggestedPath: String
    @Binding var confirmsMigration: Bool

    var body: some View {
        GroupBox("迁移预览") {
            VStack(alignment: .leading, spacing: 10) {
                LabeledContent("建议路径", value: suggestedPath)
                TextField("迁移目标", text: $targetPath)
                if let plan = controller.plan {
                    Divider()
                    LabeledContent("源路径", value: plan.source)
                    LabeledContent("目标路径", value: plan.target)
                    LabeledContent("Dirty 文件", value: "\(plan.dirtyCount)")
                    LabeledContent(
                        "关联 Profiles",
                        value: plan.linkedProfiles.joined(separator: ", ")
                    )
                    LabeledContent(
                        "关联 Worktrees",
                        value: "\(plan.linkedWorktrees.count)"
                    )
                    preservation(plan)
                }
                HStack {
                    Button("生成迁移预览") {
                        Task { await controller.previewMigration(target: targetPath) }
                    }
                    .disabled(controller.current == nil || targetPath.isEmpty)
                    Button("执行预览中的迁移…") {
                        confirmsMigration = true
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(controller.plan?.ready != true)
                    Button("验收") {
                        Task { await controller.verifyMigration() }
                    }
                    .disabled(controller.receipt == nil)
                }
                if let receipt = controller.receipt {
                    LabeledContent("状态", value: receipt.status)
                    Text(receipt.receiptRef)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
                if !controller.verificationStatus.isEmpty {
                    LabeledContent("验收结果", value: controller.verificationStatus)
                }
            }
            .padding(8)
        }
    }

    private func preservation(
        _ plan: PersonalWorkspaceMigrationPlan
    ) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Label(
                plan.preservesBranches ? "保留所有 branch" : "branch 保留未确认",
                systemImage: plan.preservesBranches ? "checkmark.circle" : "xmark.circle"
            )
            Label(
                plan.preservesCommits ? "保留所有 commit" : "commit 保留未确认",
                systemImage: plan.preservesCommits ? "checkmark.circle" : "xmark.circle"
            )
            Label(
                plan.preservesUncommitted ? "保留未提交内容" : "未提交内容保留未确认",
                systemImage: plan.preservesUncommitted ? "checkmark.circle" : "xmark.circle"
            )
        }
        .font(.caption)
    }
}
