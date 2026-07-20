import SwiftUI

struct ClientReleaseSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var controller = ClientReleaseController()

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            TabView {
                updatePanel
                    .tabItem {
                        Label("客户端更新", systemImage: "arrow.down.app")
                    }
                LocalProfilesView()
                    .tabItem {
                        Label("Profiles", systemImage: "person.2")
                    }
            }
        }
        .frame(width: 720, height: 620)
        .background(.regularMaterial)
        .task { await controller.refresh() }
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .font(.system(size: 34))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 3) {
                Text("FactorTester-Client")
                    .font(.title2.weight(.semibold))
                Text("更新客户端，并管理所有人类与 Agent Profiles")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("关闭") { dismiss() }
                .keyboardShortcut(.cancelAction)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var updatePanel: some View {
        ScrollView {
            VStack(spacing: 18) {
                ClientReleaseStatusCard(controller: controller)
                GroupBox("安全状态") {
                    LabeledContent("App 签名", value: controller.signatureText)
                        .padding(8)
                }
                GroupBox("更新来源") {
                    LabeledContent(
                        "公开仓库",
                        value: "maix00/FactorTester-Client"
                    )
                    .padding(8)
                    Text("Release 必须且只能包含 FactorTester-Client.dmg；下载后先校验 GitHub SHA-256 digest，再打开安装镜像。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.bottom, 8)
                }
                if let message = controller.lastError {
                    Label(message, systemImage: "info.circle.fill")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                        .background(.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                }
                HStack {
                    Button("检查更新") {
                        Task { await controller.refresh() }
                    }
                    Spacer()
                    Button("打开上一版 DMG") {
                        Task { await controller.rollback() }
                    }
                    .disabled(!controller.canRollback)
                    Button("下载、校验并打开 DMG") {
                        Task { await controller.update() }
                    }
                    .buttonStyle(.borderedProminent)
                }
                .disabled(controller.isWorking)
            }
            .padding(24)
        }
    }
}
