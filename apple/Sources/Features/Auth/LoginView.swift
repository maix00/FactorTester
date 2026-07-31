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
                if mode == .login {
                    AccountCredentialAuthorizationView(
                        fixedUsername: nil,
                        submitTitle: L10n.text("登录"),
                        reason: L10n.text("使用 Touch ID 登录 FTClient"),
                        isWorking: session.isWorking,
                        submit: { username, password in
                            let ok = await session.login(
                                username: username,
                                password: password
                            )
                            if ok {
                                dismiss()
                                onFinish(true)
                            }
                            return ok
                        },
                        cancel: {
                            onFinish(false)
                            dismiss()
                        }
                    )
                } else {
                    registrationCredentials
                }
                if let error = session.lastError {
                    Label(error, systemImage: "exclamationmark.circle.fill")
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if mode == .register {
                    HStack {
                        Button("取消") { onFinish(false); dismiss() }
                        Spacer()
                        Button("创建账户") {
                            Task { await submitRegistration() }
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .disabled(
                            session.isWorking
                                || username.isEmpty
                                || password.isEmpty
                        )
                    }
                }
            }
            .padding(24)
            .onSubmit {
                if mode == .register {
                    Task { await submitRegistration() }
                }
            }
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

    private var registrationCredentials: some View {
        GroupBox {
            VStack(spacing: 12) {
                TextField("用户名", text: $username)
                    .textContentType(.username)
                Picker("所属机构", selection: $selectedOrg) {
                    ForEach(organizations) { org in
                        Text(org.name).tag(org.id)
                    }
                }
                SecureField("密码（至少 6 位）", text: $password)
                .textContentType(.password)
            }
            .padding(8)
        }
    }

    private func submitRegistration() async {
        guard !session.isWorking else { return }
        let ok = await session.register(
            username: username,
            password: password,
            organizationId: selectedOrg
        )
        if ok {
            dismiss()
            onFinish(true)
        }
    }
}
