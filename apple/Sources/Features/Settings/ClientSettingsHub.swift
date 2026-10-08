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
                case .adapters:
                    ClientAdapterSettingsView(open: open)
                case .localResearch:
                    ClientLocalResearchSettingsView(open: open)
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
    case account, server, workspace, adapters, localResearch, language, updates
    var id: String { rawValue }
    var title: String {
        switch self {
        case .account: return "账户"
        case .server: return "服务器"
        case .workspace: return "工作区"
        case .adapters: return "本地适配器"
        case .localResearch: return "本地研究"
        case .language: return "语言"
        case .updates: return "客户端更新"
        }
    }
    var systemImage: String {
        switch self {
        case .account: return "person.text.rectangle"
        case .server: return "server.rack"
        case .workspace: return "folder.badge.person.crop"
        case .adapters: return "shippingbox.and.arrow.backward"
        case .localResearch: return "point.3.connected.trianglepath.dotted"
        case .language: return "globe"
        case .updates: return "arrow.down.app"
        }
    }
}

private struct ClientAdapterSettingsView: View {
    let open: (ClientTab) -> Void

    var body: some View {
        SettingsPageShell(
            title: "本地适配器",
            subtitle: "启动并打开安装在本机的 FactorTester 组件",
            systemImage: "shippingbox.and.arrow.backward"
        ) {
            SettingsSectionCard("本地适配器") {
                ClientAdapterPanel { adapter in
                    open(.adapter(adapter))
                }
            }
        }
    }
}

private struct ClientLocalResearchSettingsView: View {
    let open: (ClientTab) -> Void
    @StateObject private var tabSession = ClientTabSession()

    var body: some View {
        SettingsPageShell(
            title: "本地研究",
            subtitle: "管理本机研究页面与报告",
            systemImage: "point.3.connected.trianglepath.dotted"
        ) {
            ResearchModuleView(
                tabSession: tabSession,
                openReferencePage: { reference in
                    if let destination = ClientTab.reference(reference) {
                        open(destination)
                    }
                },
                openResearchPath: { path in
                    if let destination = ClientTab.embeddedNavigationDestination(
                        for: path
                    ) {
                        open(destination)
                    }
                },
                openExternalURL: { url in
                    open(.externalWeb(url))
                }
            )
        }
    }
}

private struct SettingsLanguageView: View {
    @EnvironmentObject private var languageStore: LanguageStore

    var body: some View {
        SettingsPageShell(
            title: "语言",
            subtitle: "选择 FTClient 的界面语言",
            systemImage: "globe"
        ) {
            SettingsSectionCard("界面语言") {
                SettingsRow(
                    title: "显示语言",
                    description: "JSON、状态值与 API 协议不会随界面语言改变"
                ) {
                    Picker(
                        "语言",
                        selection: Binding(
                            get: { languageStore.selection.rawValue },
                            set: { languageStore.select(rawValue: $0) }
                        )
                    ) {
                        ForEach(LanguageCatalog.options()) { option in
                            Text(L10n.resource(option.titleKey)).tag(option.id)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                }
            }
        }
    }
}
