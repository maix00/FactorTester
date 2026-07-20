import SwiftUI

struct LocalProfileForm: View {
    @ObservedObject var controller: LocalProfileController
    @State private var id = ""
    @State private var name = ""
    @State private var serverURL = ""
    @State private var workspaceRoot = ""

    var body: some View {
        GroupBox("新建或更新 Profile") {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                row("ID", "例如 maxa", $id)
                row("名称", "显示名称", $name)
                row("服务器", "https://server.example", $serverURL)
                row("工作区", "/Users/name/Documents/FactorWorkspace", $workspaceRoot)
                GridRow {
                    Spacer()
                    Button("保存 Profile") {
                        Task {
                            await controller.saveProfile(
                                id: id, name: name,
                                serverURL: serverURL,
                                workspaceRoot: workspaceRoot
                            )
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled([id, name, serverURL, workspaceRoot].contains(""))
                }
            }
            .padding(8)
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
