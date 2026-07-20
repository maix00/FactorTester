import SwiftUI
import UniformTypeIdentifiers

struct ClientReleaseSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var controller = ClientReleaseController()
    @State private var choosingProfile = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            TabView {
                ScrollView {
                    VStack(spacing: 18) {
                        ClientReleaseStatusCard(controller: controller)
                        configuration
                        actions
                        if let error = controller.lastError {
                            errorCallout(error)
                        }
                    }
                    .padding(24)
                }
                .tabItem {
                    Label("组件", systemImage: "shippingbox")
                }

                LocalProfilesView()
                    .tabItem {
                        Label("Profiles", systemImage: "person.2")
                    }
            }
        }
        .frame(width: 720, height: 620)
        .background(.regularMaterial)
        .fileImporter(
            isPresented: $choosingProfile,
            allowedContentTypes: [.json],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                controller.profilePath = url.path
            }
        }
        .task { await controller.refresh() }
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .font(.system(size: 34))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 3) {
                Text("客户端与组件")
                    .font(.title2.weight(.semibold))
                Text("保持 FactorTester CLI 与本地研究组件兼容")
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

    private var configuration: some View {
        GroupBox("安装来源") {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 12) {
                configRow(
                    icon: "terminal",
                    title: "命令",
                    prompt: "factortester 或可执行文件绝对路径",
                    text: $controller.cliPath
                )
                GridRow {
                    Label("Profile", systemImage: "doc.badge.gearshape")
                        .frame(width: 92, alignment: .leading)
                    HStack(spacing: 8) {
                        TextField("选择发布 Profile JSON", text: $controller.profilePath)
                            .textFieldStyle(.roundedBorder)
                        Button("选择…") { choosingProfile = true }
                    }
                }
            }
            .padding(8)
        }
    }

    private var actions: some View {
        HStack {
            Text("密码、token 与审批不会由此界面保存。")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Button("回滚") { Task { await controller.rollback() } }
            Button("首次安装") { Task { await controller.bootstrap() } }
            Button("更新") { Task { await controller.update() } }
                .buttonStyle(.borderedProminent)
        }
        .disabled(controller.isWorking)
    }

    private func configRow(
        icon: String,
        title: String,
        prompt: String,
        text: Binding<String>
    ) -> some View {
        GridRow {
            Label(title, systemImage: icon)
                .frame(width: 92, alignment: .leading)
            TextField(prompt, text: text)
                .textFieldStyle(.roundedBorder)
        }
    }

    private func errorCallout(_ message: String) -> some View {
        Label(message, systemImage: "exclamationmark.triangle.fill")
            .font(.callout)
            .foregroundStyle(.red)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
    }
}
