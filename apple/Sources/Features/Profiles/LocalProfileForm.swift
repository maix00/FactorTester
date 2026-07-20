import SwiftUI
import UniformTypeIdentifiers

struct LocalProfileForm: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var config: ServerConfig
    @ObservedObject var controller: LocalProfileController
    @State private var id = ""
    @State private var name = ""
    @State private var serverURL = ""
    @State private var workspaceRoot = ""
    @State private var agentID = ""
    @State private var role = "research"
    @State private var choosingWorkspace = false

    var body: some View {
        GroupBox("新建 Profile") {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                row("ID", "例如 maxa", $id)
                row("名称", "显示名称", $name)
                row("服务器", "https://server.example", $serverURL)
                row("Agent ID", "例如 research-maxa", $agentID)
                GridRow {
                    Text("角色").frame(width: 64, alignment: .leading)
                    Picker("角色", selection: $role) {
                        Text("研究 Agent").tag("research")
                        Text("规划 Agent").tag("planning")
                    }
                    .labelsHidden()
                    .pickerStyle(.segmented)
                }
                GridRow {
                    Text("初始化").frame(width: 64, alignment: .leading)
                    Text(session.user?.username ?? "请先在个人中心登录")
                        .foregroundStyle(session.isLoggedIn ? .primary : .secondary)
                }
                GridRow {
                    Spacer()
                    Text("使用当前登录身份和 canonical 因子库初始化；自动创建 agent/\(branchProfileID) 独立分支与 worktree。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                GridRow {
                    Text("工作区").frame(width: 64, alignment: .leading)
                    HStack {
                        TextField(
                            "~/Documents/FactorTester/profiles/<profile-id>",
                            text: $workspaceRoot
                        )
                        .textFieldStyle(.roundedBorder)
                        Button("选择…") { choosingWorkspace = true }
                    }
                }
                GridRow {
                    Spacer()
                    Button("创建独立 Profile") {
                        Task {
                            await controller.createIsolatedProfile(
                                id: id, name: name,
                                serverURL: serverURL,
                                workspaceRoot: effectiveWorkspaceRoot,
                                agentID: agentID,
                                role: role,
                                principalRef: session.user?.username ?? ""
                            )
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!session.isLoggedIn || [
                        id, name, serverURL, agentID
                    ].contains(""))
                }
            }
            .padding(8)
        }
        .fileImporter(
            isPresented: $choosingWorkspace,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                workspaceRoot = url.path
            }
        }
        .onAppear {
            if serverURL.isEmpty {
                serverURL = config.baseURL?.absoluteString ?? ""
            }
        }
    }

    private func row(
        _ title: String,
        _ prompt: String,
        _ value: Binding<String>
    ) -> some View {
        GridRow {
            Text(title).frame(width: 64, alignment: .leading)
            TextField(prompt, text: value).textFieldStyle(.roundedBorder)
        }
    }

    private var branchProfileID: String {
        id.isEmpty ? "<profile-id>" : id
    }

    private var effectiveWorkspaceRoot: String {
        guard workspaceRoot.isEmpty else { return workspaceRoot }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/profiles")
            .appendingPathComponent(id)
            .path
    }
}
