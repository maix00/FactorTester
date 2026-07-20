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
                launcher(factorLibrary)
                launcher(products)
                launcher(.profiles)
                launcher(.account)
                launcher(.settings)
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
        .frame(minWidth: 210)
    }

    private func launcher(_ tab: ClientTab) -> some View {
        Button { open(tab) } label: {
            Label(tab.title, systemImage: tab.systemImage)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button("打开") { open(tab) }
        }
        .tag(tab.id)
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
        .tag(tab.id)
        .contextMenu {
            Button("关闭") { close(tab) }
        }
        .accessibilityIdentifier("sidebar.open.\(tab.id)")
    }

    private var factorLibrary: ClientTab {
        .web(
            id: "factor-library", title: "因子库",
            systemImage: "function", path: "/custom-factors/editor"
        )
    }

    private var products: ClientTab {
        .web(
            id: "products", title: "产品",
            systemImage: "shippingbox", path: "/products"
        )
    }
}
