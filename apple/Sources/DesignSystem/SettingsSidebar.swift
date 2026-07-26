import SwiftUI

struct SettingsSidebarItem: Identifiable, Hashable {
    let id: String
    let title: String
    let systemImage: String
}

struct SettingsSidebar: View {
    @Binding var selection: String
    let items: [SettingsSidebarItem]

    var body: some View {
        List(items, selection: $selection) { item in
            Label {
                Text(L10n.resource(item.title))
            } icon: {
                Image(systemName: item.systemImage)
            }
                .tag(item.id)
        }
        .listStyle(.sidebar)
        .frame(width: 210)
        .layoutPriority(1)
        .fixedSize(horizontal: true, vertical: false)
    }
}
