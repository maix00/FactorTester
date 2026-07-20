import SwiftUI

struct LocalAgentForm: View {
    @ObservedObject var controller: LocalProfileController
    let profileID: String
    @State private var agentID = ""
    @State private var role = "research"
    @State private var workspaceID = ""
    @State private var instanceID = ""
    @State private var branchID = ""

    var body: some View {
        GroupBox("新建或更新 Agent 身份") {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                field("Agent ID", "例如 sgccs-research", $agentID)
                GridRow {
                    Text("角色").frame(width: 74, alignment: .leading)
                    Picker("角色", selection: $role) {
                        Text("Research").tag("research")
                        Text("Planning").tag("planning")
                    }
                    .labelsHidden()
                }
                if role == "planning" {
                    field("Workspace", "用户工作区 ID", $workspaceID)
                } else {
                    field("Instance", "研究实例 ID", $instanceID)
                    field("Branch", "研究分支 ID", $branchID)
                }
                GridRow {
                    Spacer()
                    Button("保存 Agent") {
                        Task {
                            await controller.saveAgent(
                                profileID: profileID, agentID: agentID,
                                role: role, workspaceID: workspaceID,
                                instanceID: instanceID, branchID: branchID
                            )
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!isComplete)
                }
            }
            .padding(8)
        }
    }

    private var isComplete: Bool {
        guard !agentID.isEmpty else { return false }
        return role == "planning"
            ? !workspaceID.isEmpty
            : !instanceID.isEmpty && !branchID.isEmpty
    }

    private func field(
        _ title: String,
        _ prompt: String,
        _ value: Binding<String>
    ) -> some View {
        GridRow {
            Text(title).frame(width: 74, alignment: .leading)
            TextField(prompt, text: value).textFieldStyle(.roundedBorder)
        }
    }
}
