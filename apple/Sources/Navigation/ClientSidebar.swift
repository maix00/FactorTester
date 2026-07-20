import SwiftUI

struct ClientSidebar: View {
    @Binding var selection: String
    let openTabs: [ClientTab]
    let open: (ClientTab) -> Void
    let close: (ClientTab) -> Void

    var body: some View {
        List(selection: $selection) {
            Section("功能入口") {
                launcher(.home)
                launcher(.research)
                launcher(.factorLibrary)
                launcher(.products)
                launcher(.profiles)
            }
            if !openTabs.filter(\.isClosable).isEmpty {
                Section("已打开") {
                    ForEach(openTabs.filter(\.isClosable)) { tab in
                        openedRow(tab)
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("FTClient")
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 0) {
                Divider()
                bottomLauncher(.account)
                bottomLauncher(.settings)
            }
            .padding(.vertical, 6)
            .background(.regularMaterial)
        }
        .frame(minWidth: 210)
    }

    private func launcher(_ tab: ClientTab) -> some View {
        Label(tab.title, systemImage: tab.systemImage)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture { open(tab) }
            .tag(tab.id)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { open(tab) }
            .accessibilityIdentifier("sidebar.launch.\(tab.id)")
    }

    private func bottomLauncher(_ tab: ClientTab) -> some View {
        Button { open(tab) } label: {
            Label(tab.title, systemImage: tab.systemImage)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(
                    selection == tab.id
                        ? Color.accentColor.opacity(0.14) : Color.clear,
                    in: RoundedRectangle(cornerRadius: 7)
                )
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 8)
        .accessibilityIdentifier("sidebar.launch.\(tab.id)")
    }

    private func openedRow(_ tab: ClientTab) -> some View {
        HStack(spacing: 8) {
            Label(tab.title, systemImage: tab.systemImage)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 4)
            Button { close(tab) } label: {
                Image(systemName: "xmark")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help("关闭")
        }
        .contentShape(Rectangle())
        .onTapGesture { selection = tab.id }
        .tag(tab.id)
        .accessibilityIdentifier("sidebar.open.\(tab.id)")
    }
}
