import SwiftUI

struct ClientSettingsHub: View {
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
                case .updates:
                    ClientReleaseSettingsView(embedded: true)
                }
            }
            .frame(minWidth: 560, maxWidth: .infinity)
        }
    }
}

private enum SettingSection: String, CaseIterable, Identifiable {
    case server, updates
    var id: String { rawValue }
    var title: String { self == .server ? "服务器" : "客户端更新" }
    var systemImage: String {
        self == .server ? "server.rack" : "arrow.down.app"
    }
}
