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
            Label(item.title, systemImage: item.systemImage)
                .tag(item.id)
        }
        .listStyle(.sidebar)
        .frame(width: 210)
        .fixedSize(horizontal: true, vertical: false)
    }
}
