import SwiftUI
import UniformTypeIdentifiers

struct LocalProfileForm: View {
    @EnvironmentObject private var session: SessionStore
    @ObservedObject var controller: LocalProfileController
    @State private var id = ""
    @State private var name = ""
    @State private var serverURL = ""
    @State private var workspaceRoot = ""
    @State private var agentID = ""
    @State private var choosingWorkspace = false

    var body: some View {
        GroupBox("新建或更新 Profile") {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                row("ID", "例如 maxa", $id)
                row("名称", "显示名称", $name)
                row("服务器", "https://server.example", $serverURL)
                row("Agent ID", "例如 research-maxa", $agentID)
                GridRow {
                    Text("初始化").frame(width: 64, alignment: .leading)
                    Text(session.user?.username ?? "请先在个人中心登录")
                        .foregroundStyle(session.isLoggedIn ? .primary : .secondary)
                }
                GridRow {
                    Spacer()
                    Text("Profile 只绑定当前登录身份；创建后再从服务器授权列表选择初始化因子库。")
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
                    Button("保存 Profile") {
                        Task {
                            await controller.bootstrapProfile(
                                id: id, name: name,
                                serverURL: serverURL,
                                workspaceRoot: workspaceRoot,
                                agentID: agentID,
                                principalRef: session.user?.username ?? ""
                            )
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!session.isLoggedIn || [
                        id, name, serverURL, workspaceRoot, agentID
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
}
