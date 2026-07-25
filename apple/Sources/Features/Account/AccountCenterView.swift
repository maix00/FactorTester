import SwiftUI

struct AccountCenterView: View {
    @EnvironmentObject private var session: SessionStore
    let open: (ClientTab) -> Void
    @State private var sectionID = AccountSection.account.id
    @State private var showLogin = false

    var body: some View {
        HSplitView {
            SettingsSidebar(
                selection: $sectionID,
                items: AccountSection.allCases.map {
                    SettingsSidebarItem(
                        id: $0.id,
                        title: $0.title,
                        systemImage: $0.systemImage
                    )
                }
            )

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    let section = AccountSection(rawValue: sectionID) ?? .account
                    SettingsPageHeader(title: section.title, subtitle: section.subtitle)
                    content
                }
                .padding(24)
                .frame(maxWidth: 760, alignment: .leading)
            }
            .frame(maxWidth: .infinity)
        }
        .sheet(isPresented: $showLogin) {
            LoginView { _ in showLogin = false }
                .environmentObject(session)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch AccountSection(rawValue: sectionID) ?? .account {
        case .account:
            AccountIdentityCard(showLogin: { showLogin = true })
        case .security:
            PasswordChangeCard()
        case .productGroups:
            resource(
                "管理研究与回测可用的产品范围",
                "shippingbox",
                .products
            )
        case .factorGrants:
            resource(
                "管理个人因子库与 Profile 初始化授权",
                "books.vertical",
                .factorLibrary
            )
        }
    }

    private func resource(
        _ description: String,
        _ image: String,
        _ destination: ClientTab
    ) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                Label(description, systemImage: image)
                    .font(.headline)
                Button("打开管理页面") { open(destination) }
                    .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
        }
    }
}

private enum AccountSection: String, CaseIterable, Identifiable {
    case account, security, productGroups, factorGrants
    var id: String { rawValue }
    var title: String {
        switch self {
        case .account: return "账户"
        case .security: return "安全"
        case .productGroups: return "产品组"
        case .factorGrants: return "因子库授权"
        }
    }
    var systemImage: String {
        switch self {
        case .account: return "person.text.rectangle"
        case .security: return "lock.shield"
        case .productGroups: return "shippingbox"
        case .factorGrants: return "books.vertical"
        }
    }

    var subtitle: String {
        switch self {
        case .account: return "查看当前身份、机构与登录状态。"
        case .security: return "修改密码并管理登录安全。"
        case .productGroups: return "管理研究与回测可用的产品范围。"
        case .factorGrants: return "管理个人因子库与 Profile 初始化授权。"
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
