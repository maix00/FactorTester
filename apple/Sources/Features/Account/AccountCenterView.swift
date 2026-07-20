import SwiftUI

struct AccountCenterView: View {
    @EnvironmentObject private var session: SessionStore
    let open: (ClientTab) -> Void
    @State private var section = AccountSection.account
    @State private var showLogin = false

    var body: some View {
        HSplitView {
            List(AccountSection.allCases, selection: $section) { item in
                Label(item.title, systemImage: item.systemImage).tag(item)
            }
            .listStyle(.sidebar)
            .frame(minWidth: 180, idealWidth: 200)

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(section.title).font(.largeTitle.weight(.semibold))
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
        switch section {
        case .account:
            AccountIdentityCard(showLogin: { showLogin = true })
        case .security:
            PasswordChangeCard()
        case .productGroups:
            resource(
                "管理研究与回测可用的产品范围",
                "shippingbox",
                .web(
                    id: "products", title: "产品",
                    systemImage: "shippingbox", path: "/products"
                )
            )
        case .factorGrants:
            resource(
                "管理个人因子库与 Profile 初始化授权",
                "books.vertical",
                .web(
                    id: "factor-library", title: "因子库",
                    systemImage: "function", path: "/custom-factors/editor"
                )
            )
        case .language:
            LanguagePreferenceCard()
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
    case account, security, productGroups, factorGrants, language
    var id: String { rawValue }
    var title: String {
        switch self {
        case .account: return "账户"
        case .security: return "安全"
        case .productGroups: return "产品组"
        case .factorGrants: return "因子库授权"
        case .language: return "语言"
        }
    }
    var systemImage: String {
        switch self {
        case .account: return "person.text.rectangle"
        case .security: return "lock.shield"
        case .productGroups: return "shippingbox"
        case .factorGrants: return "books.vertical"
        case .language: return "globe"
        }
    }
}

private struct AccountIdentityCard: View {
    @EnvironmentObject private var session: SessionStore
    let showLogin: () -> Void

    var body: some View {
        GroupBox {
            if let user = session.user {
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

private struct LanguagePreferenceCard: View {
    @AppStorage("client.language") private var language =
        AppLanguage.system.rawValue

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                Picker("界面语言", selection: $language) {
                    Text("跟随系统").tag(AppLanguage.system.rawValue)
                    Text("简体中文").tag(AppLanguage.simplifiedChinese.rawValue)
                    Text("English").tag(AppLanguage.english.rawValue)
                }
                .pickerStyle(.segmented)
                Text("语言设置仅影响界面文案；机器 JSON、状态值与 API 协议保持不变。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(8)
        }
    }
}

private struct PasswordChangeCard: View {
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
            if response.success { current = ""; new = ""; confirmation = "" }
        } catch {
            message = (error as? APIError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}
