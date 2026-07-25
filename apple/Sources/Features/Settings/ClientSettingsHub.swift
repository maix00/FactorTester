import SwiftUI

struct ClientSettingsHub: View {
    let open: (ClientTab) -> Void
    @EnvironmentObject private var releaseController: ClientReleaseController
    @State private var selectionID = SettingSection.account.id

    var body: some View {
        HSplitView {
            SettingsSidebar(
                selection: $selectionID,
                items: SettingSection.allCases.map {
                    SettingsSidebarItem(
                        id: $0.id,
                        title: $0.title,
                        systemImage: $0.systemImage
                    )
                }
            )

            Group {
                switch SettingSection(rawValue: selectionID) ?? .server {
                case .account:
                    AccountSettingsView()
                case .server:
                    ServerSettingsView()
                case .workspace:
                    PersonalWorkspaceView(openProfiles: {
                        open(.profiles)
                    })
                case .language:
                    SettingsLanguageView()
                case .updates:
                    ClientReleaseSettingsView(
                        controller: releaseController,
                        embedded: true
                    )
                }
            }
            .frame(minWidth: 560, maxWidth: .infinity)
        }
    }
}

private enum SettingSection: String, CaseIterable, Identifiable {
    case account, server, workspace, language, updates
    var id: String { rawValue }
    var title: String {
        switch self {
        case .account: return "账户"
        case .server: return "服务器"
        case .workspace: return "工作区"
        case .language: return "语言"
        case .updates: return "客户端更新"
        }
    }
    var systemImage: String {
        switch self {
        case .account: return "person.text.rectangle"
        case .server: return "server.rack"
        case .workspace: return "folder.badge.person.crop"
        case .language: return "globe"
        case .updates: return "arrow.down.app"
        }
    }
}

private struct SettingsLanguageView: View {
    @AppStorage("client.language") private var language =
        AppLanguage.system.rawValue

    var body: some View {
        SettingsPageShell(
            title: "语言",
            subtitle: "选择 FTClient 的界面语言。",
            systemImage: "globe"
        ) {
            SettingsSectionCard("界面语言") {
                SettingsRow(
                    title: "显示语言",
                    description: "JSON、状态值与 API 协议不会随界面语言改变。"
                ) {
                    Picker("语言", selection: $language) {
                        Text("跟随系统").tag(AppLanguage.system.rawValue)
                        Text("简体中文").tag(AppLanguage.simplifiedChinese.rawValue)
                        Text("English").tag(AppLanguage.english.rawValue)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                }
            }
        }
    }
}
