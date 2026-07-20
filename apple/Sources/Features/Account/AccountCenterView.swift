import SwiftUI

struct AccountCenterView: View {
    @EnvironmentObject private var session: SessionStore
    @Environment(\.dismiss) private var dismiss

    let open: (ClientTab) -> Void

    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var isChangingPassword = false
    @State private var passwordMessage: String?
    @State private var passwordSucceeded = false

    var body: some View {
        NavigationStack {
            Form {
                accountSection
                resourceSection
                passwordSection
            }
            .formStyle(.grouped)
            .navigationTitle("个人中心")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                }
            }
        }
        .frame(minWidth: 620, minHeight: 560)
    }

    private var accountSection: some View {
        Section("账号") {
            if let user = session.user {
                LabeledContent("用户名", value: user.username ?? "—")
                LabeledContent("角色", value: user.role ?? "—")
                LabeledContent("机构", value: user.organizationName ?? "—")
            } else {
                Text("当前未登录").foregroundStyle(.secondary)
            }
        }
    }

    private var resourceSection: some View {
        Section("研究资源") {
            resourceButton(
                title: "产品组与产品管理",
                subtitle: "管理可用于研究与回测的产品范围",
                systemImage: "shippingbox",
                tab: .web(
                    id: "products",
                    title: "产品管理",
                    systemImage: "shippingbox",
                    path: "/products"
                )
            )
            resourceButton(
                title: "因子库与因子管理",
                subtitle: "查看因子家族、参数与已登记因子",
                systemImage: "function",
                tab: .web(
                    id: "factor-library",
                    title: "因子库",
                    systemImage: "function",
                    path: "/custom-factors/editor"
                )
            )
        }
    }

    private var passwordSection: some View {
        Section("修改密码") {
            SecureField("当前密码", text: $currentPassword)
            SecureField("新密码（至少 6 位）", text: $newPassword)
            SecureField("确认新密码", text: $confirmPassword)
            if let passwordMessage {
                Text(passwordMessage)
                    .foregroundStyle(passwordSucceeded ? .green : .red)
            }
            Button {
                Task { await changePassword() }
            } label: {
                if isChangingPassword {
                    ProgressView().controlSize(.small)
                } else {
                    Text("更新密码")
                }
            }
            .disabled(
                isChangingPassword
                    || currentPassword.isEmpty
                    || newPassword.count < 6
                    || confirmPassword.isEmpty
            )
        }
    }

    private func resourceButton(
        title: String,
        subtitle: String,
        systemImage: String,
        tab: ClientTab
    ) -> some View {
        Button {
            open(tab)
        } label: {
            HStack(spacing: 12) {
                Image(systemName: systemImage)
                    .font(.title3)
                    .frame(width: 24)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "arrow.up.right.square")
                    .foregroundStyle(.secondary)
            }
        }
        .buttonStyle(.plain)
    }

    @MainActor
    private func changePassword() async {
        passwordSucceeded = false
        guard newPassword == confirmPassword else {
            passwordMessage = "两次输入的新密码不一致"
            return
        }
        isChangingPassword = true
        defer { isChangingPassword = false }
        do {
            let response = try await APIClient.shared.changePassword(
                currentPassword: currentPassword,
                newPassword: newPassword
            )
            if response.success {
                passwordSucceeded = true
                passwordMessage = "密码已更新"
                currentPassword = ""
                newPassword = ""
                confirmPassword = ""
            } else {
                passwordMessage = response.error ?? "密码更新失败"
            }
        } catch {
            passwordMessage =
                (error as? APIError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}
