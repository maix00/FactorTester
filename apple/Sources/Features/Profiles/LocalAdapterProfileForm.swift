import SwiftUI

struct LocalAdapterProfileForm: View {
    @ObservedObject var controller: LocalProfileController
    let profileID: String
    @State private var adapterID = ""
    @State private var configurationRef = ""
    @State private var secret = ""
    @State private var enabled = true

    var body: some View {
        GroupBox("Adapter 配置") {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                field("Adapter ID", "例如 vibe-trading", $adapterID)
                field(
                    "配置引用", "file://… 或 profile://…",
                    $configurationRef
                )
                GridRow {
                    Text("凭据").frame(width: 74, alignment: .leading)
                    SecureField("仅写入 macOS Keychain", text: $secret)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Toggle("启用", isOn: $enabled)
                    Button("保存 Adapter") {
                        Task { await save() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(adapterID.isEmpty)
                }
            }
            .padding(8)
        }
    }

    private func save() async {
        var credentialRef = ""
        if !secret.isEmpty {
            let account = "\(profileID)/\(adapterID)"
            do {
                try KeychainStore.save(secret, account: account)
                credentialRef = "keychain://\(KeychainStore.service)/\(account)"
                secret = ""
            } catch {
                controller.error = error.localizedDescription
                return
            }
        }
        await controller.saveAdapter(
            profileID: profileID, adapterID: adapterID,
            enabled: enabled, credentialRef: credentialRef,
            configurationRef: configurationRef
        )
    }

    private func field(
        _ title: String,
        _ prompt: String,
        _ value: Binding<String>
    ) -> some View {
        GridRow {
            Text(title).frame(width: 74, alignment: .leading)
            TextField(prompt, text: value).textFieldStyle(.roundedBorder)
        }
    }
}
