import SwiftUI

struct ClientSettingsHub: View {
    let open: (ClientTab) -> Void
    @EnvironmentObject private var releaseController: ClientReleaseController
    @State private var selectionID = SettingSection.server.id

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
                case .server:
                    ServerSettingsView()
                case .personalWorkspace:
                    PersonalWorkspaceView()
                case .workspaces:
                    WorkspaceSettingsView(openProfiles: {
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
    case server, personalWorkspace, workspaces, language, updates
    var id: String { rawValue }
    var title: String {
        switch self {
        case .server: return "服务器"
        case .personalWorkspace: return "个人工作区"
        case .workspaces: return "工作区"
        case .language: return "语言"
        case .updates: return "客户端更新"
        }
    }
    var systemImage: String {
        switch self {
        case .server: return "server.rack"
        case .personalWorkspace: return "folder.badge.person.crop"
        case .workspaces: return "externaldrive.connected.to.line.below"
        case .language: return "globe"
        case .updates: return "arrow.down.app"
        }
    }
}

private struct WorkspaceSettingsView: View {
    let openProfiles: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SettingsPageHeader(
                    title: "工作区",
                    subtitle: "这里只管理本地路径、同步、容量、Pylance 与 Git 策略。"
                )
                GroupBox("Profile 与研究过程") {
                    HStack(spacing: 16) {
                        Image(systemName: "person.2.crop.square.stack")
                            .font(.title2)
                            .foregroundStyle(.tint)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("在独立 tab 中管理")
                                .font(.headline)
                            Text("Profile、实时研究步骤、Trial Plan、义务与报告不属于设置。")
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("打开 Profiles", action: openProfiles)
                            .buttonStyle(.borderedProminent)
                    }
                    .padding(8)
                }
            }
            .padding(24)
        }
    }
}

private struct SettingsLanguageView: View {
    @AppStorage("client.language") private var language =
        AppLanguage.system.rawValue

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SettingsPageHeader(
                    title: "语言",
                    subtitle: "选择 FTClient 的界面语言。"
                )
                GroupBox("界面语言") {
                    VStack(alignment: .leading, spacing: 12) {
                        Picker("语言", selection: $language) {
                            Text("跟随系统").tag(AppLanguage.system.rawValue)
                            Text("简体中文")
                                .tag(AppLanguage.simplifiedChinese.rawValue)
                            Text("English").tag(AppLanguage.english.rawValue)
                        }
                        .pickerStyle(.segmented)
                        Text("JSON、状态值与 API 协议不会随界面语言改变。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(8)
                }
            }
            .padding(24)
        }
    }
}
