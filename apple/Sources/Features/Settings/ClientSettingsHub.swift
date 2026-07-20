import SwiftUI

struct ClientSettingsHub: View {
    let open: (ClientTab) -> Void
    @State private var selection = SettingSection.server

    var body: some View {
        HSplitView {
            List(SettingSection.allCases, selection: $selection) { item in
                Label(item.title, systemImage: item.systemImage).tag(item)
            }
            .listStyle(.sidebar)
            .frame(minWidth: 180, idealWidth: 200)

            Group {
                switch selection {
                case .server:
                    ServerSettingsView()
                case .workspaces:
                    WorkspaceSettingsView(openProfiles: {
                        open(.profiles)
                    })
                case .language:
                    SettingsLanguageView()
                case .updates:
                    ClientReleaseSettingsView(embedded: true)
                }
            }
            .frame(minWidth: 560, maxWidth: .infinity)
        }
    }
}

private enum SettingSection: String, CaseIterable, Identifiable {
    case server, workspaces, language, updates
    var id: String { rawValue }
    var title: String {
        switch self {
        case .server: return "服务器"
        case .workspaces: return "工作区"
        case .language: return "语言"
        case .updates: return "客户端更新"
        }
    }
    var systemImage: String {
        switch self {
        case .server: return "server.rack"
        case .workspaces: return "externaldrive.connected.to.line.below"
        case .language: return "globe"
        case .updates: return "arrow.down.app"
        }
    }
}

private struct WorkspaceSettingsView: View {
    let openProfiles: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("工作区与 Profiles")
                        .font(.title2.weight(.semibold))
                    Text("管理本地路径、同步、容量、Pylance 与 Git 策略。")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("在独立工作现场打开", action: openProfiles)
            }
            .padding(20)
            Divider()
            LocalProfilesView()
        }
    }
}

private struct SettingsLanguageView: View {
    @AppStorage("client.language") private var language =
        AppLanguage.system.rawValue

    var body: some View {
        ScrollView {
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
            .padding(24)
        }
    }
}
