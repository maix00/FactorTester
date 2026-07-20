import SwiftUI

struct LoginView: View {
    @EnvironmentObject var session: SessionStore
    @Environment(\.dismiss) private var dismiss
    var onFinish: (Bool) -> Void

    private enum Mode { case login, register }
    @State private var mode = Mode.login
    @State private var username = ""
    @State private var password = ""
    @State private var organizations: [Organization] = []
    @State private var selectedOrg = ""

    var body: some View {
        VStack(spacing: 0) {
            welcome
            Divider()
            VStack(spacing: 16) {
                Picker("", selection: $mode) {
                    Text("登录").tag(Mode.login)
                    Text("注册").tag(Mode.register)
                }
                .pickerStyle(.segmented)
                credentials
                if let error = session.lastError {
                    Label(error, systemImage: "exclamationmark.circle.fill")
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack {
                    Button("取消") { onFinish(false); dismiss() }
                    Spacer()
                    Button(mode == .login ? "登录" : "创建账户") {
                        Task { await submit() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(
                        session.isWorking || username.isEmpty || password.isEmpty
                    )
                }
            }
            .padding(24)
        }
        .frame(width: 460)
        .background(.regularMaterial)
        .task {
            organizations = (try? await APIClient.shared.organizations()) ?? []
            selectedOrg = organizations.first?.id ?? ""
        }
    }

    private var welcome: some View {
        HStack(spacing: 16) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 34, weight: .medium))
                .foregroundStyle(.tint)
                .frame(width: 56, height: 56)
                .background(.tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
            VStack(alignment: .leading, spacing: 4) {
                Text("欢迎使用 FTClient")
                    .font(.title2.weight(.semibold))
                Text("连接研究工作区，继续你的因子研究。")
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(24)
    }

    private var credentials: some View {
        GroupBox {
            VStack(spacing: 12) {
                TextField("用户名", text: $username)
                    .textContentType(.username)
                if mode == .register {
                    Picker("所属机构", selection: $selectedOrg) {
                        ForEach(organizations) { org in
                            Text(org.name).tag(org.id)
                        }
                    }
                }
                SecureField(
                    mode == .register ? "密码（至少 6 位）" : "密码",
                    text: $password
                )
                .textContentType(.password)
            }
            .padding(8)
        }
    }

    private func submit() async {
        let ok: Bool
        if mode == .login {
            ok = await session.login(username: username, password: password)
        } else {
            ok = await session.register(
                username: username,
                password: password,
                organizationId: selectedOrg
            )
        }
        if ok { onFinish(true); dismiss() }
    }
}
