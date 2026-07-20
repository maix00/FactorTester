import SwiftUI

/// 登录 / 注册 —— home.html 登录弹窗的原生版。
struct LoginView: View {
    @EnvironmentObject var session: SessionStore
    @Environment(\.dismiss) private var dismiss

    /// 关闭回调：参数表示是否登录成功（用于继续跳转之前点击的模块）。
    var onFinish: (Bool) -> Void

    private enum Tab { case login, register }
    @State private var tab: Tab = .login

    @State private var username = ""
    @State private var password = ""
    @State private var organizations: [Organization] = []
    @State private var selectedOrg: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Picker("", selection: $tab) {
                    Text("登录").tag(Tab.login)
                    Text("注册").tag(Tab.register)
                }
                .pickerStyle(.segmented)
                .listRowBackground(Color.clear)

                Section {
                    TextField("用户名", text: $username)
                        .textContentType(.username)
                        #if os(iOS)
                        .autocapitalization(.none)
                        #endif
                    if tab == .register {
                        Picker("所属机构", selection: $selectedOrg) {
                            ForEach(organizations) { org in
                                Text("\(org.name) (\(org.id))").tag(org.id)
                            }
                        }
                    }
                    SecureField(
                        L10n.text(tab == .register ? "密码（至少6位）" : "密码"),
                        text: $password
                    )
                        #if os(iOS)
                        .textContentType(.password)
                        #endif
                }

                if let err = session.lastError {
                    Section { Text(err).foregroundStyle(.red).font(.footnote) }
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Spacer()
                            if session.isWorking { ProgressView() }
                            else {
                                Text(L10n.text(tab == .login ? "登录" : "注册"))
                                    .bold()
                            }
                            Spacer()
                        }
                    }
                    .disabled(session.isWorking || username.isEmpty || password.isEmpty)
                }
            }
            .navigationTitle("欢迎使用")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { onFinish(false); dismiss() }
                }
            }
        }
        .task {
            organizations = (try? await APIClient.shared.organizations()) ?? []
            if selectedOrg.isEmpty { selectedOrg = organizations.first?.id ?? "" }
        }
    }

    private func submit() async {
        let ok: Bool
        if tab == .login {
            ok = await session.login(username: username, password: password)
        } else {
            ok = await session.register(username: username, password: password, organizationId: selectedOrg)
        }
        if ok { onFinish(true); dismiss() }
    }
}
