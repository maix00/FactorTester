import SwiftUI

struct AccountCenterView: View {
    let open: (ClientTab) -> Void

    var body: some View {
        AccountSettingsView()
    }
}

private enum AccountPanel: String, CaseIterable, Identifiable {
    case session, register, password
    var id: String { rawValue }
}

struct AccountSettingsView: View {
    @EnvironmentObject private var session: SessionStore
    @State private var panel: AccountPanel = .session

    var body: some View {
        SettingsPageShell(
            title: "账户",
            subtitle: "登录账户、账户身份与安全设置",
            systemImage: "person.text.rectangle"
        ) {
            SettingsSectionCard("账户操作") {
                SettingsRow(
                    title: "登录账户",
                    description: session.isLoggedIn
                        ? "当前已登录，可在这里登出或切换账户"
                        : "尚未登录；登录后可访问研究工作区和测试任务"
                ) {
                    HStack(spacing: 8) {
                        if let username = session.user?.username, !username.isEmpty {
                            Text(verbatim: username)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        } else {
                            Text("未登录")
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        Picker("账户操作", selection: $panel) {
                            Text(session.isLoggedIn ? "登出" : "登入")
                                .tag(AccountPanel.session)
                            Text("注册").tag(AccountPanel.register)
                            Text("修改密码").tag(AccountPanel.password)
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                    }
                }

                Divider()

                Group {
                    switch panel {
                    case .session:
                        SessionPanel()
                    case .register:
                        RegisterPanel()
                    case .password:
                        PasswordPanel()
                    }
                }
                .padding(.vertical, 8)
            }

            SettingsSectionCard("账户身份") {
                SettingsRow(title: "用户角色", description: "由服务器分配，客户端不能修改") {
                    if let role = session.user?.role, !role.isEmpty {
                        Text(verbatim: role).foregroundStyle(.secondary)
                    } else {
                        Text("—").foregroundStyle(.secondary)
                    }
                }
                Divider()
                SettingsRow(title: "用户组织", description: "账户所属组织，由服务器管理") {
                    if let organization = session.user?.organizationName,
                       !organization.isEmpty {
                        Text(verbatim: organization)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    } else {
                        Text("—")
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            }
        }
        .onChange(of: session.isLoggedIn) { _ in
            panel = .session
        }
    }
}

private struct SessionPanel: View {
    @EnvironmentObject private var session: SessionStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if session.isLoggedIn {
                HStack {
                    Label("已登录", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Spacer()
                    Button("登出", role: .destructive) {
                        Task { await session.logout() }
                    }
                    .buttonStyle(.bordered)
                }
            } else {
                AccountCredentialAuthorizationView(
                    fixedUsername: nil,
                    submitTitle: L10n.text("登录"),
                    reason: L10n.text("使用 Touch ID 登录 FTClient"),
                    isWorking: session.isWorking,
                    submit: { username, password in
                        await session.login(
                            username: username,
                            password: password
                        )
                    },
                    cancel: nil
                )
                if let error = session.lastError {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
        }
    }
}

private struct RegisterPanel: View {
    @EnvironmentObject private var session: SessionStore
    @State private var username = ""
    @State private var password = ""
    @State private var organization = ""
    @State private var organizations: [Organization] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("用户名", text: $username)
            if organizations.isEmpty {
                TextField("组织 ID", text: $organization)
            } else {
                Picker("组织", selection: $organization) {
                    ForEach(organizations) { item in
                        Text(item.name).tag(item.id)
                    }
                }
            }
            SecureField("密码（至少 6 位）", text: $password)
            HStack {
                Spacer()
                Button("注册") {
                    Task {
                        _ = await session.register(
                            username: username,
                            password: password,
                            organizationId: organization
                        )
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(session.isWorking || username.isEmpty || password.count < 6)
            }
            if let error = session.lastError {
                Text(error).font(.caption).foregroundStyle(.red)
            }
        }
        .task {
            organizations = (try? await APIClient.shared.organizations()) ?? []
            organization = organizations.first?.id ?? organization
        }
    }
}

private struct PasswordPanel: View {
    @EnvironmentObject private var session: SessionStore
    @State private var current = ""
    @State private var new = ""
    @State private var confirmation = ""
    @State private var working = false
    @State private var message: String?
    @State private var succeeded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !session.isLoggedIn {
                Text("请先登录账户，再修改密码。")
                    .foregroundStyle(.secondary)
            } else {
                SecureField("当前密码", text: $current)
                SecureField("新密码（至少 6 位）", text: $new)
                SecureField("确认新密码", text: $confirmation)
                if let message {
                    Text(message).font(.caption).foregroundStyle(succeeded ? .green : .red)
                }
                HStack {
                    Spacer()
                    Button("更新密码") { Task { await submit() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(working || current.isEmpty || new.count < 6 || confirmation.isEmpty)
                }
            }
        }
    }

    @MainActor private func submit() async {
        succeeded = false
        guard new == confirmation else {
            message = L10n.text("两次输入的新密码不一致")
            return
        }
        working = true
        defer { working = false }
        do {
            let response = try await APIClient.shared.changePassword(
                currentPassword: current,
                newPassword: new
            )
            succeeded = response.success
            message = response.success ? L10n.text("密码已更新") : response.error
            if response.success {
                session.updateSavedPassword(new)
                current = ""; new = ""; confirmation = ""
            }
        } catch {
            message = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
    }
}
