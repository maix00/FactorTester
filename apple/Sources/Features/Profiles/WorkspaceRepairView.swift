import SwiftUI

struct WorkspaceRepairView: View {
    let profile: LocalProfileModel
    @StateObject private var controller = WorkspaceRepairController()
    @State private var workspaceID = ""

    var body: some View {
        GroupBox("旧研究现场迁移与修复") {
            VStack(alignment: .leading, spacing: 10) {
                Picker("工作区", selection: $workspaceID) {
                    Text("请选择").tag("")
                    ForEach(profile.workspaces) { workspace in
                        Text("\(workspace.id) · \(workspace.ownerRef)")
                            .tag(workspace.id)
                    }
                }
                Text("预览不会改动文件。执行前会备份旧副本与回执，并保留研究引用。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let plan = controller.plan {
                    LabeledContent(
                        "可安全修复",
                        value: (plan["repairable"] as? Bool) == true
                            ? "是" : "否"
                    )
                    let issues = plan["issues"] as? [String] ?? []
                    Text(issues.joined(separator: " · "))
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
                HStack {
                    Button("预览") {
                        Task {
                            await controller.preview(
                                profileID: profile.id,
                                workspaceID: workspaceID
                            )
                        }
                    }
                    .disabled(workspaceID.isEmpty || controller.isWorking)
                    Button("备份并原子修复") {
                        Task { await controller.apply() }
                    }
                    .disabled(
                        controller.plan == nil
                        || !controller.repairID.isEmpty
                        || controller.isWorking
                    )
                    Button("验收") {
                        Task {
                            await controller.verify(profileID: profile.id)
                        }
                    }
                    .disabled(controller.repairID.isEmpty)
                    Button("回滚") {
                        Task {
                            await controller.rollback(profileID: profile.id)
                        }
                    }
                    .disabled(controller.repairID.isEmpty)
                }
                if !controller.repairID.isEmpty {
                    Text("Repair receipt: \(controller.repairID)")
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
                if let error = controller.error {
                    Text(error).foregroundStyle(.red)
                }
            }
            .padding(8)
        }
    }
}
