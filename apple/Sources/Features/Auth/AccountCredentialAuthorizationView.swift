import SwiftUI

struct AccountCredentialAuthorizationView: View {
    let fixedUsername: String?
    let submitTitle: String
    let reason: String
    let isWorking: Bool
    let submit: (String, String) async -> Bool
    let cancel: (() -> Void)?

    @State private var username = ""
    @State private var password = ""
    @State private var localError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let fixedUsername {
                LabeledContent(L10n.text("登录账户")) {
                    Text(verbatim: fixedUsername)
                        .foregroundStyle(.secondary)
                }
            } else {
                TextField(L10n.text("用户名"), text: $username)
                    .textContentType(.username)
            }
            SecureField(L10n.text("密码"), text: $password)
                .textContentType(.password)
            if let localError {
                Label(localError, systemImage: "exclamationmark.circle.fill")
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
            HStack(spacing: 8) {
                if SessionCredentialStore.hasUserPresenceCredentials() {
                    Button {
                        Task { await unlockAndSubmit() }
                    } label: {
                        Label(
                            L10n.text("使用 Touch ID"),
                            systemImage: "touchid"
                        )
                    }
                    .disabled(isWorking)
                }
                Spacer()
                if let cancel {
                    Button(L10n.text("取消"), action: cancel)
                }
                Button(submitTitle) {
                    Task { await submitCurrent() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    isWorking
                        || resolvedUsername.isEmpty
                        || password.isEmpty
                )
            }
        }
        .onSubmit { Task { await submitCurrent() } }
    }

    private var resolvedUsername: String {
        fixedUsername ?? username
    }

    private func unlockAndSubmit() async {
        do {
            guard let credentials = try SessionCredentialStore
                .loadWithUserPresence(
                    serverURL: ServerConfig.shared.baseURL,
                    reason: reason
                ) else { return }
            if let fixedUsername,
               fixedUsername != credentials.username {
                localError = L10n.text("保存的凭证不属于当前登录账户")
                return
            }
            username = credentials.username
            password = credentials.password
            await submitCurrent()
        } catch {
            localError = error.localizedDescription
        }
    }

    private func submitCurrent() async {
        guard !resolvedUsername.isEmpty, !password.isEmpty else { return }
        localError = nil
        if await submit(resolvedUsername, password) {
            password = ""
        }
    }
}
