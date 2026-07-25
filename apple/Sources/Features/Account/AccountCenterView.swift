import SwiftUI

struct AccountCenterView: View {
    let open: (ClientTab) -> Void

    var body: some View {
        AccountSettingsView()
    }
}

struct AccountSettingsView: View {
    @EnvironmentObject private var session: SessionStore
    @State private var showLogin = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SettingsPageHeader(
                    title: "账户",
                    subtitle: "查看当前登录身份，并在这里管理账户安全。"
                )
                AccountIdentityCard(showLogin: { showLogin = true })
                PasswordChangeCard()
            }
            .padding(24)
            .frame(maxWidth: 760, alignment: .leading)
        }
        .sheet(isPresented: $showLogin) {
            LoginView { _ in showLogin = false }
                .environmentObject(session)
        }
    }

}

private struct AccountIdentityCard: View {
    @EnvironmentObject private var session: SessionStore
    let showLogin: () -> Void

    var body: some View {
        GroupBox {
            if session.isLoggedIn, let user = session.user {
                VStack(spacing: 10) {
                    LabeledContent("用户名", value: user.username ?? "—")
                    LabeledContent("角色", value: user.role ?? "—")
                    LabeledContent("机构", value: user.organizationName ?? "—")
                    Divider()
                    Button("退出登录", role: .destructive) {
                        Task { await session.logout() }
                    }
                }
                .padding(8)
            } else {
                VStack(alignment: .leading, spacing: 14) {
                    Label(
                        "当前未登录",
                        systemImage: "person.crop.circle.badge.xmark"
                    )
                    .foregroundStyle(.secondary)
                    Button("登录 / 注册", action: showLogin)
                        .buttonStyle(.borderedProminent)
                }
                .padding(24)
            }
        }
    }
}

private struct PasswordChangeCard: View {
    @EnvironmentObject private var session: SessionStore
    @State private var current = ""
    @State private var new = ""
    @State private var confirmation = ""
    @State private var working = false
    @State private var message: String?
    @State private var succeeded = false

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                SecureField("当前密码", text: $current)
                SecureField("新密码（至少 6 位）", text: $new)
                SecureField("确认新密码", text: $confirmation)
                if let message {
                    Text(message).foregroundStyle(succeeded ? .green : .red)
                }
                Button("更新密码") { Task { await submit() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(
                        working || current.isEmpty || new.count < 6
                            || confirmation.isEmpty
                    )
            }
            .padding(8)
        }
    }

    @MainActor private func submit() async {
        succeeded = false
        guard new == confirmation else {
            message = "两次输入的新密码不一致"
            return
        }
        working = true
        defer { working = false }
        do {
            let response = try await APIClient.shared.changePassword(
                currentPassword: current, newPassword: new
            )
            succeeded = response.success
            message = response.success ? "密码已更新" : response.error
            if response.success {
                session.updateSavedPassword(new)
                current = ""; new = ""; confirmation = ""
            }
        } catch {
            message = (error as? APIError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}
